"""PAR-32 — "Commander creatures you own have '<ability>'" (and the shared
quoted-ability-grant recursion it rides).

Slice 1: compound-event self-trigger bodies — "When ~ enters or leaves
the battlefield, <effect>." (Candlekeep Sage). `_quoted_ability_grant_
effects_list` now returns one `grant_triggered_ability` per event of a
compound `AbilitySpec.trigger`, and `LEAVES_BATTLEFIELD` joined
`_GRANTABLE_TRIGGER_EVENTS` (it fires before removal — RULE 603.6a — so
the granted-to permanent still carries the granted ability when the
trigger is collected).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous  # noqa: F401  (kept for parity with sibling tests)
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


# --- parse -----------------------------------------------------------


def test_compound_event_body_emits_one_grant_per_event():
    specs = static_effect_specs(
        'commander creatures you own have '
        '"when ~ enters or leaves the battlefield, draw a card."'
    )
    assert specs is not None and len(specs) == 2
    events = {s.params["trigger_event"] for s in specs}
    assert events == {"ENTERS_BATTLEFIELD", "LEAVES_BATTLEFIELD"}
    for s in specs:
        assert s.type == "grant_triggered_ability"
        assert s.params["affects"] == "commander_creatures_you_own"
        assert s.params["grant_effects"] == [{"type": "draw", "params": {"count": 1}}]


def test_compound_event_also_works_for_attached_grant():
    specs = static_effect_specs(
        'enchanted creature has "when ~ enters or leaves the battlefield, draw a card."'
    )
    assert specs is not None and len(specs) == 2
    assert all(s.params["affects"] == "attached_permanent" for s in specs)


def test_single_event_body_unchanged():
    specs = static_effect_specs(
        'commander creatures you own have "whenever this creature attacks, draw a card."'
    )
    assert specs is not None and len(specs) == 1
    assert specs[0].params["trigger_event"] == "ATTACKS"


def test_compound_event_fails_closed_for_group_subject():
    # A non-self subject on a compound trigger can't be safely re-scoped.
    assert static_effect_specs(
        'commander creatures you own have '
        '"whenever a creature you control enters or leaves the battlefield, draw a card."'
    ) in (None, [])


# --- execute (LTB half; the ETB half shares the engine's pre-existing
#     granted-ETB-timing limitation, same as any Dionus-style grant) ---


def test_candlekeep_sage_granted_ltb_trigger_fires():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    p1 = st.player_by_id("p1")

    granter = GameObject(
        Card(id="cs", name="Candlekeep Sage",
             type_line="Enchantment Creature — Human", is_creature=True,
             power=1, toughness=1,
             oracle_text='Commander creatures you own have "When ~ enters or '
                         'leaves the battlefield, draw a card."'),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    granter.summoning_sick = False
    bind_from_catalogue(granter)
    st.add_to_battlefield(granter)

    cmd = GameObject(
        Card(id="k", name="My Commander",
             type_line="Legendary Creature — Human", is_creature=True,
             power=3, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    cmd.is_commander = True
    cmd.summoning_sick = False
    st.add_to_battlefield(cmd)
    for i in range(4):
        p1.library.append(GameObject(
            Card(id=f"l{i}", name=f"L{i}", type_line="Instant", is_instant=True),
            owner_id="p1", zone=Zone.LIBRARY))
    eng.recompute_continuous_effects()

    h0 = len(p1.hand)
    eng.rules._move_to_graveyard(cmd)          # LEAVES_BATTLEFIELD
    eng.rules.put_triggers_on_stack()
    while st.stack:
        eng.rules.resolve_top_of_stack()
    assert len(p1.hand) == h0 + 1


def test_candlekeep_sage_modeled():
    c = Card(id="cs2", name="Candlekeep Sage",
             type_line="Enchantment Creature — Human", is_creature=True,
             power=1, toughness=1,
             oracle_text='Vigilance\nCommander creatures you own have "When '
                         'this creature enters or leaves the battlefield, draw a card."')
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- slice 2: group-subject trigger regrant + multi-type group subject ---


def test_multi_main_type_group_subject_parses_as_a_type_list():
    from mtg_analyzer.parser.oracle.segmenter import segment_line
    from mtg_analyzer.parser.oracle.spec import ParserProvenance

    seg = segment_line(
        "whenever an artifact or creature you control dies, each opponent loses 1 life.",
        allow_spell_effect=False,
        provenance=ParserProvenance(version="x", source="y"),
    )
    assert seg.spec is not None
    assert seg.spec.trigger["condition"]["type"] == ["artifact", "creature"]
    # single-type unchanged
    seg2 = segment_line(
        "whenever a creature you control dies, draw a card.",
        allow_spell_effect=False,
        provenance=ParserProvenance(version="x", source="y"),
    )
    assert seg2.spec.trigger["condition"]["type"] == "creature"


def test_agent_of_the_iron_throne_granted_group_trigger_rescopes_you_control():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    p1, p2 = st.player_by_id("p1"), st.player_by_id("p2")

    granter = GameObject(
        Card(id="ait", name="Agent of the Iron Throne", type_line="Enchantment",
             oracle_text='Commander creatures you own have "Whenever an artifact '
                         'or creature you control dies, each opponent loses 1 life."'),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(granter)
    st.add_to_battlefield(granter)
    cmd = GameObject(
        Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
             is_creature=True, power=3, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    cmd.is_commander = True
    cmd.summoning_sick = False
    st.add_to_battlefield(cmd)
    eng.recompute_continuous_effects()

    def _kill(name, tl, owner="p1"):
        o = GameObject(Card(id=name, name=name, type_line=tl),
                       owner_id=owner, zone=Zone.BATTLEFIELD)
        st.add_to_battlefield(o)
        before = p2.life
        eng.rules._move_to_graveyard(o)
        eng.rules.put_triggers_on_stack()
        while st.stack:
            eng.rules.resolve_top_of_stack()
        return p2.life - before

    assert _kill("Bear", "Creature — Bear") == -1            # your creature
    assert _kill("Rock", "Artifact") == -1                   # your artifact
    assert _kill("OppBear", "Creature — Bear", owner="p2") == 0   # not yours
    assert _kill("MyAura", "Enchantment — Aura") == 0        # wrong type


def test_step_begin_phase_grant_still_claimed_after_the_refactor():
    # Regression: "Other enchantments have 'At the beginning of your upkeep,
    # sacrifice ~ unless you pay {2}.'" (Aura Flux) must not be swept into
    # the group-subject reject branch.
    specs = static_effect_specs(
        'other enchantments have "at the beginning of your upkeep, '
        'sacrifice ~ unless you pay {2}."'
    )
    assert specs is not None
    assert specs[0].params["trigger_event"] == "STEP_BEGIN"


# --- slice 3: self-attack keyword grant, the "no opponent has more life"
#     gate, two-sentence self body, and source-power pump ---


def test_it_gains_kw_until_eot_self_body():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    assert parse_effect_body(
        "it gains double strike until end of turn", self_subject=True
    ) == [__import__("mtg_analyzer.parser.oracle.spec", fromlist=["EffectSpec"]).EffectSpec(
        "pump", {"keywords": ["double_strike"]}
    )]


def test_flaming_fist_granted_self_attack_trigger():
    specs = static_effect_specs(
        'commander creatures you own have '
        '"whenever ~ attacks, it gains double strike until end of turn."'
    )
    assert specs is not None and len(specs) == 1
    assert specs[0].params["trigger_event"] == "ATTACKS"
    assert specs[0].params["grant_effects"][0]["params"]["keywords"] == ["double_strike"]


def test_two_sentence_self_body_carries_the_source_referent():
    # Agent of the Shadow Thieves: "put a +1/+1 counter on ~. it gains
    # deathtouch and indestructible until end of turn." — both clauses are
    # about the source; the split must carry `self_subject`.
    specs = static_effect_specs(
        'commander creatures you own have '
        '"whenever ~ attacks a player, if no opponent has more life than that '
        'player, put a +1/+1 counter on ~. it gains deathtouch and '
        'indestructible until end of turn."'
    )
    assert specs is not None and len(specs) == 1
    effs = specs[0].params["grant_effects"]
    assert [e["type"] for e in effs] == ["add_counters", "pump"]
    assert specs[0].params["attacked_player_has_lowest_life"] is True


def test_guild_artisan_lowest_life_gate_end_to_end():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
        starting_life=20, starting_hand=0,
    )
    st = eng.state
    p1, p3 = st.player_by_id("p1"), st.player_by_id("p3")
    granter = GameObject(
        Card(id="ga", name="Guild Artisan", type_line="Enchantment",
             oracle_text='Commander creatures you own have "Whenever ~ attacks '
                         'a player, if no opponent has more life than that '
                         'player, you create 2 Treasure tokens."'),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(granter)
    st.add_to_battlefield(granter)
    cmd = GameObject(
        Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
             is_creature=True, power=3, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    cmd.is_commander = True
    cmd.summoning_sick = False
    st.add_to_battlefield(cmd)
    eng.recompute_continuous_effects()

    from mtg_analyzer.models.events import EventType, GameEvent

    def _attack(defender_id):
        before = sum(1 for o in st.battlefield
                     if "Treasure" in o.name and o.controller_id == "p1")
        st.fire_event(GameEvent(EventType.ATTACKS, instance_id=cmd.instance_id,
                                attacker_id=cmd.instance_id,
                                defending_player_id=defender_id))
        eng.rules.put_triggers_on_stack()
        while st.stack:
            eng.rules.resolve_top_of_stack()
        return sum(1 for o in st.battlefield
                   if "Treasure" in o.name and o.controller_id == "p1") - before

    assert _attack("p2") == 2       # everyone at 20 → no opponent has more life
    p3.lose_life(5)                 # p3 now 15
    assert _attack("p2") == 0       # p2 (20) is not the lowest
    assert _attack("p3") == 2       # p3 is the lowest


def test_source_power_pump_selector():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    specs = parse_effect_body(
        "another target creature you control gets +x/+x until end of turn, "
        "where x is ~'s power"
    )
    assert specs == [__import__(
        "mtg_analyzer.parser.oracle.spec", fromlist=["EffectSpec"]
    ).EffectSpec("pump", {
        "amount_from_count_selector": "source_power",
        "target_kind": "other_creature_you_control",
    })]


# --- slice 4: player-subject SPELL_CAST regrant + "from exile" gate ---


def test_cast_from_exile_regrant_carries_the_gate():
    specs = static_effect_specs(
        'commander creatures you own have "whenever you cast a spell from '
        'exile, ~ deals damage equal to that spell\'s mana value to target '
        'opponent."'
    )
    assert specs is not None and len(specs) == 1
    p = specs[0].params
    assert p["trigger_event"] == "SPELL_CAST"
    assert p["spell_from_exile"] is True
    assert p["grant_effects"][0]["params"]["amount_from_trigger_event"] == "mana_value"


def test_passionate_archaeologist_regrant_fires_on_cast_from_exile():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    p1 = st.player_by_id("p1")
    granter = GameObject(
        Card(id="pa", name="Passionate Archaeologist", type_line="Enchantment",
             oracle_text='Commander creatures you own have "Whenever you cast '
                         'a spell from exile, this creature deals damage equal '
                         'to that spell\'s mana value to target opponent."'),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(granter)
    st.add_to_battlefield(granter)
    cmd = GameObject(
        Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
             is_creature=True, power=3, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    cmd.is_commander = True
    cmd.summoning_sick = False
    st.add_to_battlefield(cmd)
    eng.recompute_continuous_effects()

    granted = cmd._granted_triggered_abilities
    assert len(granted) == 1 and granted[0].trigger_event == "SPELL_CAST"

    from mtg_analyzer.models.events import EventType, GameEvent
    # from a hand cast → the "from exile" gate rejects it
    st.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", instance_id=1,
                            spell="X", mana_value=2, from_exile=False, from_hand=True))
    assert eng.rules.put_triggers_on_stack() == 0
    # from exile → it fires
    st.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", instance_id=2,
                            spell="Y", mana_value=3, from_exile=True, from_hand=False))
    assert eng.rules.put_triggers_on_stack() == 1


# --- slice 5: end-step blink filter + nontoken batch combat damage ---


def test_far_traveler_granted_end_step_blink():
    specs = static_effect_specs(
        'commander creatures you own have "at the beginning of your end step, '
        'exile up to 1 target tapped creature you control, then return it to '
        'the battlefield under its owner\'s control."'
    )
    assert specs is not None and len(specs) == 1
    p = specs[0].params
    assert p["trigger_event"] == "STEP_BEGIN" and p["filter"] == {"step": "end"}
    blink = p["grant_effects"][0]
    assert blink["type"] == "blink"
    assert blink["params"]["creature_filter"] == {"tapped": True}
    assert blink["params"]["target_count_max"] == 1


def test_feywild_visitor_nontoken_batch_combat_damage():
    specs = static_effect_specs(
        'commander creatures you own have "whenever 1 or more nontoken '
        'creatures you control deal combat damage to a player, you create a '
        '1/1 blue faerie dragon creature token with flying."'
    )
    assert specs is not None and len(specs) == 1
    p = specs[0].params
    assert p["trigger_event"] == "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER"
    assert p["filter"] == {"contributor_any_nontoken": True}
    # the bare form has no such filter
    bare = static_effect_specs(
        'commander creatures you own have "whenever 1 or more creatures you '
        'control deal combat damage to a player, draw a card."'
    )
    assert bare is not None and "filter" not in bare[0].params
