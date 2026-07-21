"""Tests for the 11 deferred rad-counter gaps closed in one batch (PARSER_
VERSION 22): Acquired Mutation, Bloatfly Swarm, Contaminated Drink, Harold
and Bob First Numens, Mariposa Military Base, Nuka-Nuke Launcher, Struggle
for Project Purity, The Ghoul Gunslinger, The Wise Mothman, Vault 12: The
Necropolis, and Vexing Radgull — see `backend/ToDo_Backend.md`'s former
"Rad counters (RULE 728)" entry (now closed) and `parser/oracle/gate.py`'s
PARSER_VERSION 22 comment block for the full list of new primitives.

Card oracle text below is copied verbatim from the local card cache
(`cache/db/cards.db`) as inline fixtures — not `CardDatabase(DEFAULT_DB_PATH)`
lookups — so these tests run in the ordinary suite rather than being gated
behind `--full-cache` (see `tests/conftest.py`).

Four cards (Acquired Mutation, Contaminated Drink, The Ghoul Gunslinger, The
Wise Mothman) are *not* registered in `ability_catalogue.py` — their new
grammar is pure oracle-text parsing. The Ghoul, Gunslinger and Contaminated
Drink end up fully `MODELED` (every line claimed) and so are also exercised
end-to-end via `bind_from_catalogue`/`cast_spell`. Acquired Mutation and The
Wise Mothman stay `UNMODELED` overall (an unrelated, out-of-scope line each
— "goaded" and a mill-triggered ability, respectively, neither ever modeled
by this engine) — for those two, only the newly-claimed clause is verified
at the parse level, plus a direct `attach_to_object` engine test of the
extracted spec in isolation (mirroring `test_rad_counters.py`'s own
`test_radiation_life_gain_redirects_lose_life`).

The other 7 cards are hand-authored in `ability_catalogue.py` (each needed a
compound shape no oracle-text grammar could express) and are exercised
end-to-end via `bind_from_catalogue`.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.effects import AddPlayerCountersEffect, DrawCardEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import StackItem
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _engine(starting_life=20, starting_hand=0):
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])],
        starting_life=starting_life, starting_hand=starting_hand,
    )


def _creature(name, power=2, toughness=2, oracle_text="", type_line="Creature — Bear", **kw):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text,
                is_creature=True, power=power, toughness=toughness, **kw)


def _put(state, card, controller="p1", zone=Zone.BATTLEFIELD, bind=True):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.summoning_sick = False
    if bind:
        bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _to_declare_attackers(eng):
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"


# ---------------------------------------------------------------------------
# Acquired Mutation — "whenever enchanted creature attacks, defending player
# gets two rad counters" (`_ATTACHED_SUBJECT_RE`, RULE 603.1's
# `attached_permanent` subject, now recognized from raw oracle text). The
# card's other line ("is goaded") is a wholly separate, never-modeled
# mechanic, so the card as a whole stays UNMODELED — only this one clause is
# under test here.
# ---------------------------------------------------------------------------

_ACQUIRED_MUTATION_TEXT = (
    "Enchant creature\n"
    "Enchanted creature gets +2/+2 and is goaded. (It attacks each combat "
    "if able and attacks a player other than you if able.)\n"
    "Whenever enchanted creature attacks, defending player gets two rad "
    "counters."
)


def _acquired_mutation_card():
    return Card(id="am", name="Acquired Mutation", type_line="Enchantment — Aura",
                oracle_text=_ACQUIRED_MUTATION_TEXT, mana_cost_string="{R}", converted_mana_cost=1)


def test_acquired_mutation_stays_unmodeled_but_only_goad_is_unclaimed():
    result = parse_oracle(_acquired_mutation_card())
    assert not result.modeled
    assert len(result.unclaimed) == 1
    assert "goaded" in result.unclaimed[0]


def test_acquired_mutation_attacks_trigger_parses_as_attached_permanent_subject():
    result = parse_oracle(_acquired_mutation_card())
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    assert len(triggered) == 1
    spec = triggered[0]
    assert spec.trigger == {"event": "ATTACKS", "condition": {"subject": "attached_permanent"}}
    assert spec.effects[0].type == "add_player_counters"
    assert spec.effects[0].params == {"amount": 2, "kind": "rad", "selector": "defending_player"}


def test_acquired_mutation_grants_defending_player_rad_counters_on_attack():
    eng = _engine()
    result = parse_oracle(_acquired_mutation_card())
    (spec,) = [s for s in result.specs if s.ability_kind == "triggered"]

    host = _put(eng.state, _creature("Enchanted Bear"), controller="p1", bind=False)
    aura = _put(eng.state, Card(id="am", name="Acquired Mutation", type_line="Enchantment — Aura"),
                controller="p1", bind=False)
    aura.attached_to = host.instance_id
    attach_to_object(aura, [spec])

    _to_declare_attackers(eng)
    eng.declare_attackers(eng.state.active_player, [host])

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    p2 = eng.state.player_by_id("p2")
    assert p2.counters.get("rad", 0) == 2


# ---------------------------------------------------------------------------
# Bloatfly Swarm — a compound damage-prevention replacement: prevent damage
# to itself while it has a +1/+1 counter, remove that many counters (capped
# by however many it has), then grant each player a rad counter per counter
# actually removed. Registered, hand-authored (`_bloatfly_swarm`).
# ---------------------------------------------------------------------------


def _bloatfly_swarm_card():
    return Card(
        id="bloatfly", name="Bloatfly Swarm", type_line="Creature — Insect Mutant",
        oracle_text=(
            "Flying\n"
            "This creature enters with five +1/+1 counters on it.\n"
            "If damage would be dealt to this creature while it has a +1/+1 "
            "counter on it, prevent that damage, remove that many +1/+1 "
            "counters from it, then give each player a rad counter for each "
            "+1/+1 counter removed this way."
        ),
        is_creature=True, power=0, toughness=0, mana_cost_string="{B}", converted_mana_cost=1,
    )


def test_bloatfly_swarm_prevents_damage_removes_counters_and_grants_rad_to_each_player():
    eng = _engine()
    swarm = _put(eng.state, _bloatfly_swarm_card())
    swarm.counters["+1/+1"] = 3
    source = _put(eng.state, _creature("Attacker"), controller="p2")

    eng.rules.deal_damage(swarm, 2, source=source)

    assert swarm.damage_marked == 0  # fully prevented
    assert swarm.counters.get("+1/+1", 0) == 1  # 3 - 2 removed
    assert eng.state.player_by_id("p1").counters.get("rad", 0) == 2
    assert eng.state.player_by_id("p2").counters.get("rad", 0) == 2


def test_bloatfly_swarm_removal_is_capped_by_counters_actually_present():
    eng = _engine()
    swarm = _put(eng.state, _bloatfly_swarm_card())
    swarm.counters["+1/+1"] = 2
    source = _put(eng.state, _creature("Attacker"), controller="p2")

    eng.rules.deal_damage(swarm, 5, source=source)  # more damage than counters

    assert swarm.damage_marked == 0
    assert swarm.counters.get("+1/+1", 0) == 0  # capped at 2, not 5
    assert eng.state.player_by_id("p1").counters.get("rad", 0) == 2
    assert eng.state.player_by_id("p2").counters.get("rad", 0) == 2


def test_bloatfly_swarm_does_not_prevent_damage_once_out_of_counters():
    eng = _engine()
    swarm = _put(eng.state, _bloatfly_swarm_card())
    swarm.counters["+1/+1"] = 0
    source = _put(eng.state, _creature("Attacker"), controller="p2")

    eng.rules.deal_damage(swarm, 3, source=source)

    assert swarm.damage_marked == 3  # no shield left — real damage applies
    assert eng.state.player_by_id("p1").counters.get("rad", 0) == 0


# ---------------------------------------------------------------------------
# Contaminated Drink — "Draw X cards, then you get half X rad counters,
# rounded up." Unregistered, fully MODELED (a single line). New grammar:
# `_add_rad_counters_half_x`/`_substitute_x`'s `half_x_up`/`half_x_down`.
# ---------------------------------------------------------------------------


def _contaminated_drink_card():
    return Card(id="cd", name="Contaminated Drink", type_line="Instant",
                oracle_text="Draw X cards, then you get half X rad counters, rounded up.",
                mana_cost_string="{X}{U}{B}", converted_mana_cost=2, is_instant=True)


def test_contaminated_drink_is_fully_modeled():
    result = parse_oracle(_contaminated_drink_card())
    assert result.modeled
    assert result.unclaimed == []


def test_contaminated_drink_parses_draw_x_then_half_x_rad_counters_rounded_up():
    result = parse_oracle(_contaminated_drink_card())
    (spec,) = result.specs
    assert [e.type for e in spec.effects] == ["draw", "add_player_counters"]
    assert spec.effects[0].params == {"count": "x"}
    assert spec.effects[1].params == {"amount": "half_x_up", "kind": "rad"}


def test_substitute_x_half_up_rounds_odd_x_up():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    eng.state.stack.append(StackItem(
        kind="ability", controller_id=p1.id,
        effects=[DrawCardEffect(count="x", player=p1),
                 AddPlayerCountersEffect(amount="half_x_up", kind="rad", player=p1)],
        x=3,
    ))
    eng.rules.resolve_top_of_stack()
    assert p1.counters.get("rad", 0) == 2  # ceil(3/2)


def test_substitute_x_half_down_rounds_odd_x_down():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    eng.state.stack.append(StackItem(
        kind="ability", controller_id=p1.id,
        effects=[AddPlayerCountersEffect(amount="half_x_down", kind="rad", player=p1)],
        x=3,
    ))
    eng.rules.resolve_top_of_stack()
    assert p1.counters.get("rad", 0) == 1  # floor(3/2)


def test_contaminated_drink_cast_end_to_end_draws_x_and_grants_half_rad_counters():
    eng = _engine(starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    for i in range(4):
        p1.library.append(GameObject(_creature(f"Card {i}"), owner_id=p1.id, zone=Zone.LIBRARY))
    p1.mana_pool.add_many({"U": 1, "B": 1, "C": 4})

    result = parse_oracle(_contaminated_drink_card())
    (spec,) = result.specs
    from mtg_analyzer.game.effect_binder import build_effects
    spell = GameObject(_contaminated_drink_card(), owner_id="p1", zone=Zone.HAND)
    spell.spell_effects = build_effects(spec.effects, spell)
    p1.add_to_zone(spell, Zone.HAND)

    eng.cast_spell(p1, spell, x=4)
    eng.resolve_until_stable()

    assert len(p1.hand) == 4  # drew all 4
    assert p1.counters.get("rad", 0) == 2  # ceil(4/2)


# ---------------------------------------------------------------------------
# Harold and Bob, First Numens — dies, returns as a synthetic Aura enchanting
# a chosen Forest, with its own quoted granted mana ability. Registered,
# hand-authored (`_harold_and_bob`); the target is a real RULE 115 choice
# (`forest_you_control`), so the trigger opens a `trigger_target`
# pending_choice (`test_trigger_targeting.py`'s pattern) before it resolves.
# ---------------------------------------------------------------------------


def _harold_and_bob_card():
    return Card(
        id="hab", name="Harold and Bob, First Numens", type_line="Legendary Creature — Treefolk Mutant",
        oracle_text=(
            "Vigilance, reach\n"
            "When Harold and Bob dies, if it was a creature, return it to "
            "the battlefield. It's an Aura enchantment with enchant Forest "
            "you control and \"{T}: Add three mana of any one color. You "
            "get two rad counters.\" Harold and Bob loses all other "
            "abilities."
        ),
        is_creature=True, power=3, toughness=3, keywords=["Vigilance", "Reach"],
        mana_cost_string="{G}", converted_mana_cost=1,
    )


def test_harold_and_bob_dies_returns_as_an_aura_attached_to_a_forest():
    eng = _engine()
    hab = _put(eng.state, _harold_and_bob_card())
    forest = _put(eng.state, Card(id="forest", name="Forest", type_line="Basic Land — Forest", is_land=True))

    eng.rules.destroy(hab)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target"
    forest_option = next(o for o in choice["options"] if o["instance_id"] == forest.instance_id)

    eng.rules.resolve_trigger_target_choice(forest_option["id"])
    assert eng.state.pending_choice is None
    eng.resolve_until_stable()

    assert hab in eng.state.battlefield
    assert hab.attached_to == forest.instance_id
    assert hab.card.type_line == "Enchantment — Aura"
    from mtg_analyzer.game import combat
    assert not combat.has(hab, "vigilance")  # "loses all other abilities"


def test_harold_and_bobs_granted_mana_ability_produces_three_mana_and_two_rad_counters():
    eng = _engine()
    hab = _put(eng.state, _harold_and_bob_card())
    forest = _put(eng.state, Card(id="forest", name="Forest", type_line="Basic Land — Forest", is_land=True))

    eng.rules.destroy(hab)
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    forest_option = next(o for o in choice["options"] if o["instance_id"] == forest.instance_id)
    eng.rules.resolve_trigger_target_choice(forest_option["id"])
    eng.resolve_until_stable()

    p1 = eng.state.player_by_id("p1")
    produced = eng.tap_for_mana(p1, hab, option_index=0)
    assert sum(produced.values()) == 3
    assert p1.mana_pool.total() == 3
    assert p1.counters.get("rad", 0) == 2


# ---------------------------------------------------------------------------
# Mariposa Military Base — "You may have this land enter tapped. If you do,
# you get two rad counters." (`optional_bonus_rad`, `enter_land_tapped`'s
# mirror of a shock land) + "This ability costs {1} less to activate for
# each rad counter you have." (`ActivationCost.dynamic_reduction`).
# Registered, hand-authored (`_mariposa_military_base`) for the cost
# reduction only — the land-enters-tapped choice and the plain "{T}: Add
# {C}." mana ability are both picked up unconditionally.
# ---------------------------------------------------------------------------


def _mariposa_military_base_card():
    return Card(
        id="mariposa", name="Mariposa Military Base", type_line="Land",
        oracle_text=(
            "You may have this land enter tapped. If you do, you get two "
            "rad counters.\n"
            "{T}: Add {C}.\n"
            "{5}, {T}: Draw a card. This ability costs {1} less to "
            "activate for each rad counter you have."
        ),
        is_land=True,
    )


def test_mariposa_military_base_choosing_tapped_grants_two_rad_counters():
    from mtg_analyzer.services.game_session import build_goldfish_engine

    engine = build_goldfish_engine([_mariposa_military_base_card()], starting_hand=1)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.active_player
    land = p1.hand[0]
    engine.play_land(p1, land)

    assert land.tapped is False  # untapped by default (mirror of a shock land)
    choice = engine.state.pending_choice
    assert choice["kind"] == "land_tapped_bonus"

    engine.resolve_pending_choice("tap")
    assert land.tapped is True
    assert p1.counters.get("rad", 0) == 2


def test_mariposa_military_base_declining_stays_untapped_with_no_bonus():
    from mtg_analyzer.services.game_session import build_goldfish_engine

    engine = build_goldfish_engine([_mariposa_military_base_card()], starting_hand=1)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.active_player
    land = p1.hand[0]
    engine.play_land(p1, land)

    engine.resolve_pending_choice("decline")
    assert land.tapped is False
    assert p1.counters.get("rad", 0) == 0


def test_mariposa_military_bases_draw_ability_costs_less_per_rad_counter():
    eng = _engine()
    land = _put(eng.state, _mariposa_military_base_card())
    p1 = eng.state.player_by_id("p1")
    p1.counters["rad"] = 3
    p1.mana_pool.add_many({"C": 2})  # {5} generic reduced by 3 -> only {2} needed
    hand_before = len(p1.hand)
    p1.library.append(GameObject(_creature("Filler"), owner_id="p1", zone=Zone.LIBRARY))

    eng.activate_ability(p1, land, ability_index=0)
    eng.resolve_until_stable()

    assert p1.mana_pool.total() == 0  # all paid
    assert len(p1.hand) == hand_before + 1


def test_mariposa_military_bases_draw_ability_costs_full_with_no_rad_counters():
    eng = _engine()
    land = _put(eng.state, _mariposa_military_base_card())
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"C": 2})  # not enough — no reduction, needs {5}

    try:
        eng.activate_ability(p1, land, ability_index=0)
        raised = False
    except ValueError:
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# Nuka-Nuke Launcher — "Whenever equipped creature attacks, until the end of
# defending player's next turn, that player gets two rad counters whenever
# they cast a spell." A recurring, bounded-duration player-scoped trigger
# (`InstallTemporaryPlayerTriggerEffect`/`GameState.temporary_player_
# triggers`). Registered, hand-authored (`_nuka_nuke_launcher`).
# ---------------------------------------------------------------------------


def _nuka_nuke_launcher_card():
    return Card(
        id="nnl", name="Nuka-Nuke Launcher", type_line="Artifact — Equipment",
        oracle_text=(
            "Equipped creature gets +3/+0 and has intimidate.\n"
            "Whenever equipped creature attacks, until the end of defending "
            "player's next turn, that player gets two rad counters whenever "
            "they cast a spell.\n"
            "Equip {3}"
        ),
    )


def test_nuka_nuke_launcher_installs_a_temporary_trigger_on_the_defending_player():
    eng = _engine()
    host = _put(eng.state, _creature("Wearer"), controller="p1")
    launcher = _put(eng.state, _nuka_nuke_launcher_card(), controller="p1")
    launcher.attached_to = host.instance_id

    _to_declare_attackers(eng)
    eng.declare_attackers(eng.state.active_player, [host])
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert len(eng.state.temporary_player_triggers) == 1
    trig = eng.state.temporary_player_triggers[0]
    assert trig.player_id == "p2"  # the defending player
    assert trig.phase == "waiting"


def test_nuka_nuke_launcher_grants_rad_counters_while_active_then_expires():
    eng = _engine()
    host = _put(eng.state, _creature("Wearer"), controller="p1")
    launcher = _put(eng.state, _nuka_nuke_launcher_card(), controller="p1")
    launcher.attached_to = host.instance_id

    _to_declare_attackers(eng)
    eng.declare_attackers(eng.state.active_player, [host])
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    p2 = eng.state.player_by_id("p2")

    # Casting a spell before the trigger is active does nothing yet.
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p2"))
    eng.rules.put_triggers_on_stack()
    assert p2.counters.get("rad", 0) == 0

    # p2's own next TURN_BEGIN activates it.
    eng.state.fire_event(GameEvent(EventType.TURN_BEGIN, player_id="p2", turn=2))
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p2"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    assert p2.counters.get("rad", 0) == 2

    # It re-fires on a second spell cast while still active.
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p2"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    assert p2.counters.get("rad", 0) == 4

    # The next TURN_BEGIN after p2's own turn started expires it.
    eng.state.fire_event(GameEvent(EventType.TURN_BEGIN, player_id="p1", turn=3))
    assert eng.state.temporary_player_triggers == []
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p2"))
    eng.rules.put_triggers_on_stack()
    assert p2.counters.get("rad", 0) == 4  # no further grant


# ---------------------------------------------------------------------------
# Struggle for Project Purity — "As this enchantment enters, choose
# Brotherhood or Enclave." A third `enter_choice_effects` sibling
# (`ChooseNamedModeReplacement`/`GameObject.chosen_mode`), gating each
# named-bullet ability via `effect_binder`'s new "named_mode" trigger
# condition. Registered, hand-authored (`_struggle_for_project_purity`).
# ---------------------------------------------------------------------------


def _struggle_card():
    return Card(
        id="sfpp", name="Struggle for Project Purity", type_line="Enchantment",
        oracle_text=(
            "As this enchantment enters, choose Brotherhood or Enclave.\n"
            "• Brotherhood — At the beginning of your upkeep, each "
            "opponent draws a card. You draw a card for each card drawn "
            "this way.\n"
            "• Enclave — Whenever a player attacks you with one or "
            "more creatures, that player gets twice that many rad counters."
        ),
        mana_cost_string="{U}", converted_mana_cost=1,
    )


def test_struggle_enter_choice_end_to_end_via_cast():
    eng = _engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"U": 1})
    struggle = GameObject(_struggle_card(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(struggle)
    p1.add_to_zone(struggle, Zone.HAND)

    eng.cast_spell(p1, struggle)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending["kind"] == "choose_named_mode"
    ids = {o["id"] for o in pending["options"]}
    assert ids == {"brotherhood", "enclave"}

    eng.resolve_pending_choice("enclave")
    assert struggle in eng.state.battlefield
    assert struggle.chosen_mode == "enclave"


def test_struggle_brotherhood_mode_draws_for_each_opponent_then_matches():
    eng = _engine()
    struggle = _put(eng.state, _struggle_card(), controller="p1")
    struggle.chosen_mode = "brotherhood"
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    for i in range(2):
        p1.library.append(GameObject(_creature(f"A{i}"), owner_id="p1", zone=Zone.LIBRARY))
        p2.library.append(GameObject(_creature(f"B{i}"), owner_id="p2", zone=Zone.LIBRARY))

    eng.state.active_player_index = 0
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert len(p2.hand) == 1  # each opponent draws a card
    assert len(p1.hand) == 1  # you draw one per opponent-draw (1 opponent)


def test_struggle_brotherhood_does_not_fire_when_enclave_is_chosen():
    eng = _engine()
    struggle = _put(eng.state, _struggle_card(), controller="p1")
    struggle.chosen_mode = "enclave"

    eng.state.active_player_index = 0
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    assert eng.rules.put_triggers_on_stack() == 0


def test_struggle_enclave_mode_grants_twice_the_attacking_creature_count():
    eng = _engine()
    struggle = _put(eng.state, _struggle_card(), controller="p2")  # p2 is attacked
    struggle.chosen_mode = "enclave"
    a1 = _put(eng.state, _creature("Attacker 1"), controller="p1")
    a2 = _put(eng.state, _creature("Attacker 2"), controller="p1")

    _to_declare_attackers(eng)
    eng.declare_attackers(eng.state.active_player, [a1, a2])
    eng.advance_step()  # leaves declare_attackers, fires PLAYER_ATTACKED

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    p1 = eng.state.player_by_id("p1")
    assert p1.counters.get("rad", 0) == 4  # 2 attackers * multiplier 2


def test_struggle_enclave_mode_does_not_fire_when_brotherhood_is_chosen():
    eng = _engine()
    struggle = _put(eng.state, _struggle_card(), controller="p2")
    struggle.chosen_mode = "brotherhood"
    a1 = _put(eng.state, _creature("Attacker 1"), controller="p1")

    _to_declare_attackers(eng)
    eng.declare_attackers(eng.state.active_player, [a1])
    eng.advance_step()

    assert eng.rules.put_triggers_on_stack() == 0


# ---------------------------------------------------------------------------
# The Ghoul, Gunslinger — "Whenever The Ghoul or another nontoken Zombie or
# Mutant you control dies, target player gets two rad counters. If that
# player is you, create a Treasure token." Unregistered, fully MODELED:
# a tribal "self_or_group" dies subject with a subtype/nontoken filter
# (`_GROUP_SUBTYPE_SUBJECT_RE`/`_SELF_OR_GROUP_SUBTYPE_RE`) + a target-based
# intervening-if (`_TARGET_IS_CONTROLLER_RE`) + a named Treasure token.
# ---------------------------------------------------------------------------


def _ghoul_card():
    return Card(
        id="ghoul", name="The Ghoul, Gunslinger", type_line="Legendary Creature — Zombie Mutant Rogue",
        oracle_text=(
            "First strike\n"
            "Whenever The Ghoul or another nontoken Zombie or Mutant you "
            "control dies, target player gets two rad counters. If that "
            "player is you, create a Treasure token."
        ),
        is_creature=True, power=2, toughness=3, keywords=["First Strike"],
        mana_cost_string="{B}{B}", converted_mana_cost=2,
    )


def test_ghoul_gunslinger_is_fully_modeled():
    result = parse_oracle(_ghoul_card())
    assert result.modeled
    assert result.unclaimed == []


def test_ghoul_gunslinger_parses_self_or_group_subtype_dies_subject():
    result = parse_oracle(_ghoul_card())
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    (spec,) = triggered
    assert spec.trigger["event"] == "DIES"
    cond = spec.trigger["condition"]
    assert cond["subject"] == "self_or_group"
    assert set(cond["subtypes"]) == {"zombie", "mutant"}
    assert cond["nontoken"] is True and cond["other"] is True and cond["controller"] == "you"


def test_ghoul_gunslinger_own_death_grants_rad_counters_and_a_treasure_when_self_targeted():
    eng = _engine()
    ghoul = _put(eng.state, _ghoul_card(), controller="p1", bind=False)
    bind_from_catalogue(ghoul)

    eng.rules.destroy(ghoul)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target"
    p1 = eng.state.player_by_id("p1")
    p1_option = next(o for o in choice["options"] if o.get("id") == "p1" or o.get("instance_id") == "p1")

    eng.rules.resolve_trigger_target_choice(p1_option["id"])
    eng.resolve_until_stable()

    assert p1.counters.get("rad", 0) == 2
    treasures = [o for o in eng.state.battlefield if o.name == "Treasure"]
    assert len(treasures) == 1


def test_ghoul_gunslinger_targeting_an_opponent_grants_no_treasure():
    eng = _engine()
    ghoul = _put(eng.state, _ghoul_card(), controller="p1", bind=False)
    bind_from_catalogue(ghoul)

    eng.rules.destroy(ghoul)
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    p2_option = next(o for o in choice["options"] if o.get("id") == "p2" or o.get("instance_id") == "p2")

    eng.rules.resolve_trigger_target_choice(p2_option["id"])
    eng.resolve_until_stable()

    p2 = eng.state.player_by_id("p2")
    assert p2.counters.get("rad", 0) == 2
    assert not any(o.name == "Treasure" for o in eng.state.battlefield)


def test_ghoul_gunslinger_fires_for_another_nontoken_zombie_but_not_an_unrelated_creature():
    eng = _engine()
    ghoul = _put(eng.state, _ghoul_card(), controller="p1", bind=False)
    bind_from_catalogue(ghoul)
    zombie = _put(eng.state, _creature("Random Zombie", type_line="Creature — Zombie"), controller="p1")
    unrelated = _put(eng.state, _creature("Random Bear"), controller="p1")

    eng.rules.destroy(unrelated)
    assert eng.rules.put_triggers_on_stack() == 0

    eng.rules.destroy(zombie)
    assert eng.rules.put_triggers_on_stack() == 1


# ---------------------------------------------------------------------------
# The Wise Mothman — "Whenever The Wise Mothman enters or attacks, each
# player gets a rad counter." A compound multi-event trigger
# (`_SELF_MULTI_EVENT_RE`, `trigger["event"]` as a `list[str]`). Unregistered;
# stays UNMODELED overall (its second ability is a mill-triggered-ability
# family this engine doesn't model at all) — only the rad-counter clause is
# under test.
# ---------------------------------------------------------------------------


def _mothman_card():
    return Card(
        id="mothman", name="The Wise Mothman", type_line="Legendary Creature — Insect Mutant",
        oracle_text=(
            "Flying\n"
            "Whenever The Wise Mothman enters or attacks, each player gets "
            "a rad counter.\n"
            "Whenever one or more nonland cards are milled, put a +1/+1 "
            "counter on each of up to X target creatures, where X is the "
            "number of nonland cards milled this way."
        ),
        is_creature=True, power=3, toughness=3, keywords=["Flying"],
        mana_cost_string="{U}{B}{G}", converted_mana_cost=3,
    )


def test_wise_mothman_stays_unmodeled_but_only_the_mill_trigger_is_unclaimed():
    result = parse_oracle(_mothman_card())
    assert not result.modeled
    assert len(result.unclaimed) == 1
    assert "milled" in result.unclaimed[0]


def test_wise_mothman_enters_or_attacks_parses_as_a_compound_event_list():
    result = parse_oracle(_mothman_card())
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    (spec,) = triggered
    assert spec.trigger["event"] == ["ENTERS_BATTLEFIELD", "ATTACKS"]
    assert spec.trigger["condition"] == {"subject": "self"}
    assert spec.effects[0].type == "add_player_counters"
    assert spec.effects[0].params == {"amount": 1, "kind": "rad", "selector": "each_player"}


def test_wise_mothman_grants_rad_counters_to_each_player_on_enters_and_on_attacks():
    eng = _engine()
    result = parse_oracle(_mothman_card())
    (spec,) = [s for s in result.specs if s.ability_kind == "triggered"]

    mothman = GameObject(_mothman_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    mothman.summoning_sick = False
    attach_to_object(mothman, [spec])
    eng.state.add_to_battlefield(mothman)
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", card_id=mothman.card.id,
        object=mothman.name, instance_id=mothman.instance_id, object_types=sorted(mothman.type_words),
    ))

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert eng.state.player_by_id("p1").counters.get("rad", 0) == 1
    assert eng.state.player_by_id("p2").counters.get("rad", 0) == 1

    _to_declare_attackers(eng)
    eng.declare_attackers(eng.state.active_player, [mothman])
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert eng.state.player_by_id("p1").counters.get("rad", 0) == 2
    assert eng.state.player_by_id("p2").counters.get("rad", 0) == 2


# ---------------------------------------------------------------------------
# Vault 12: The Necropolis — chapter II needs a cross-player aggregate rad
# counter count (`continuous.count_selector`'s
# "total_rad_counters_among_players"); chapter III needs a tribal mass-
# counter filter (`AddCountersEffect.subtypes`). Registered, hand-authored
# (`_vault_12_the_necropolis`, chapter I carried over verbatim since a
# registered card's other specs no longer fall back to the parser).
# ---------------------------------------------------------------------------


def _vault_12_card():
    return Card(
        id="vault12", name="Vault 12: The Necropolis", type_line="Enchantment — Saga",
        oracle_text=(
            "(As this Saga enters and after your draw step, add a lore "
            "counter. Sacrifice after III.)\n"
            "I — Each player gets three rad counters.\n"
            "II — Create X 2/2 black Zombie Mutant creature tokens, "
            "where X is the total number of rad counters among players.\n"
            "III — Put two +1/+1 counters on each creature you control "
            "that's a Zombie or Mutant."
        ),
        mana_cost_string="{B}{B}", converted_mana_cost=2,
    )


def _saga_in_play(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, controller_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def test_vault_12_chapter_i_grants_three_rad_counters_to_each_player():
    eng = _engine()
    eng.begin_turn()
    _saga_in_play(eng, _vault_12_card())
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert eng.state.player_by_id("p1").counters.get("rad", 0) == 3
    assert eng.state.player_by_id("p2").counters.get("rad", 0) == 3


def test_vault_12_chapter_ii_creates_tokens_equal_to_total_rad_counters_across_players():
    eng = _engine()
    eng.begin_turn()
    saga = _saga_in_play(eng, _vault_12_card())
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()  # chapter I: 3 rad counters each -> 6 total

    eng.rules.advance_sagas(eng.state.active_player)  # chapter II
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    tokens = [o for o in eng.state.battlefield if o is not saga and o.is_token]
    assert len(tokens) == 6
    for t in tokens:
        assert (t.power, t.toughness) == (2, 2)
        assert "zombie" in {s.lower() for s in t.card.type_line.partition("—")[2].split()}


def test_vault_12_chapter_iii_only_pumps_zombies_and_mutants_you_control():
    eng = _engine()
    eng.begin_turn()
    saga = _saga_in_play(eng, _vault_12_card())
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()  # chapter I
    eng.rules.advance_sagas(eng.state.active_player)  # chapter II
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    zombie = _put(eng.state, _creature("Plain Zombie", type_line="Creature — Zombie"), controller="p1")
    bear = _put(eng.state, _creature("Plain Bear"), controller="p1")

    eng.rules.advance_sagas(eng.state.active_player)  # chapter III
    assert saga.lore == 3
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert zombie.counters.get("+1/+1", 0) == 2
    assert bear.counters.get("+1/+1", 0) == 0


# ---------------------------------------------------------------------------
# Vexing Radgull — "Whenever this creature deals combat damage to a player,
# that player gets two rad counters if they don't have any rad counters.
# Otherwise, proliferate." A conditional branch between two different
# effects (`rad_counters_on_combat_damage`'s new "else" key). Registered,
# hand-authored (`_vexing_radgull`).
# ---------------------------------------------------------------------------


def _vexing_radgull_card():
    return Card(
        id="radgull", name="Vexing Radgull", type_line="Creature — Bird Mutant",
        oracle_text=(
            "Flying\n"
            "Whenever this creature deals combat damage to a player, that "
            "player gets two rad counters if they don't have any rad "
            "counters. Otherwise, proliferate."
        ),
        is_creature=True, power=1, toughness=2, keywords=["Flying"],
        mana_cost_string="{U}", converted_mana_cost=1,
    )


def test_vexing_radgull_grants_two_rad_counters_the_first_time():
    eng = _engine()
    radgull = _put(eng.state, _vexing_radgull_card())
    p2 = eng.state.player_by_id("p2")

    eng.rules.deal_damage(p2, 1, radgull, combat=True)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    assert p2.counters.get("rad", 0) == 2


def test_vexing_radgull_proliferates_instead_once_the_player_already_has_rad_counters():
    eng = _engine()
    radgull = _put(eng.state, _vexing_radgull_card())
    p2 = eng.state.player_by_id("p2")
    p2.counters["rad"] = 2  # already has some

    eng.rules.deal_damage(p2, 1, radgull, combat=True)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    assert p2.counters.get("rad", 0) == 3  # proliferated (+1), not reset to 2
