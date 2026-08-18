"""cEDH cube batch 25, wave 5 — RULE 702 keywords that had recognition but
no behaviour, plus a *granted* Escape and the Pacts.

* **Fading** (RULE 702.32) — entry counters off the parsed keyword, and the
  upkeep "remove a counter or sacrifice". Tangle Wire.
* **Soulbond** (RULE 702.94) — real pairing state, broken as an SBA, with a
  layer-6 grant over the new ``soulbond_pair`` selector. Deadeye Navigator.
* **Mutate** (RULE 702.140) — an alternative cast cost that merges onto its
  target instead of entering the battlefield. Lore Drakkis.
* **Bargain** — an optional additional cost plus an ``"if bargained"``
  effect condition. Beseech the Mirror.
* A **granted** Escape (RULE 702.138 from a permanent, not printed on the
  card). Underworld Breach.
* The Pacts and Corpse Dance's delayed exile, both riding
  `CreateDelayedTriggerEffect` + wave 2's `pay_cost_then`.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player


def _engine():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state, p1, p2


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    kw.setdefault("power", 2 if kw.get("is_creature") else None)
    kw.setdefault("toughness", 2 if kw.get("is_creature") else None)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bf(state, card, controller="p1", obj=None):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _catalogue_obj(name, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(_named(name), owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    return obj


def _step(step):
    return GameEvent(EventType.STEP_BEGIN, step=step)


def _etb(obj):
    return GameEvent(
        EventType.ENTERS_BATTLEFIELD,
        instance_id=obj.instance_id,
        controller_id=obj.controller_id,
        object_types=sorted(obj.type_words),
    )


# ---------------------------------------------------------------------------
# Fading (RULE 702.32) — Tangle Wire
# ---------------------------------------------------------------------------


def _play_tangle_wire(engine, state, p1):
    wire = _catalogue_obj("Tangle Wire")
    engine.rules._apply_entry_counters(wire)
    state.add_to_battlefield(wire)
    return wire


def test_fading_places_its_entry_counters_off_the_keyword():
    """RULE 702.32a, read off the *parsed keyword* rather than the reminder
    sentence — the keyword is the rule, the reminder needn't be printed."""
    engine, state, p1, _ = _engine()
    wire = _play_tangle_wire(engine, state, p1)

    assert wire.counters.get("fade") == 4


def test_fading_removes_a_counter_each_of_your_upkeeps():
    engine, state, p1, _ = _engine()
    wire = _play_tangle_wire(engine, state, p1)

    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    assert wire.counters.get("fade") == 3


def test_fading_sacrifices_the_permanent_once_the_counters_run_out():
    """RULE 702.32b's "if you can't" is about there being no counter left,
    not about any choice — which is why Fading N lasts N+1 upkeeps."""
    engine, state, p1, _ = _engine()
    wire = _play_tangle_wire(engine, state, p1)
    wire.counters["fade"] = 0

    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    assert wire not in state.battlefield
    assert wire in p1.graveyard


def test_fading_only_counts_down_on_its_own_controllers_upkeep():
    engine, state, p1, p2 = _engine()
    wire = _play_tangle_wire(engine, state, p1)
    state.active_player_index = 1  # p2's turn

    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    assert wire.counters.get("fade") == 4


def test_tangle_wire_taxes_the_active_player_per_remaining_fade_counter():
    engine, state, p1, p2 = _engine()
    wire = _play_tangle_wire(engine, state, p1)
    wire.counters["fade"] = 2
    theirs = [_bf(state, _card(f"Bear{i}"), controller="p2") for i in range(4)]
    state.active_player_index = 1

    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    # RULE 701.21a: *which* permanents get tapped is the taxed player's own
    # choice, offered one at a time.
    for expected in (2, 1):
        assert state.pending_choice["kind"] == "choose_objects"
        assert state.pending_choice["remaining"] == expected
        engine.resolve_pending_choice(state.pending_choice["options"][0]["id"])
    assert state.pending_choice is None

    assert sum(1 for o in theirs if o.tapped) == 2  # one per fade counter


# ---------------------------------------------------------------------------
# Vanishing (RULE 702.61) — Aven Riftwatcher
# ---------------------------------------------------------------------------


def _play_riftwatcher(engine, state, p1):
    bird = _catalogue_obj("Aven Riftwatcher")
    engine.rules._apply_entry_counters(bird)
    state.add_to_battlefield(bird)
    return bird


def test_vanishing_places_its_entry_counters_off_the_keyword():
    engine, state, p1, _ = _engine()
    bird = _play_riftwatcher(engine, state, p1)

    assert bird.counters.get("time") == 3


def test_vanishing_removes_a_counter_each_of_your_upkeeps():
    engine, state, p1, _ = _engine()
    bird = _play_riftwatcher(engine, state, p1)

    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    assert bird.counters.get("time") == 2
    assert bird in state.battlefield


def test_vanishing_sacrifices_the_same_upkeep_the_last_counter_is_removed():
    """RULE 702.61b has no Fading-style off-by-one: the removal that empties
    the last time counter sacrifices the permanent in that same upkeep."""
    engine, state, p1, _ = _engine()
    bird = _play_riftwatcher(engine, state, p1)
    bird.counters["time"] = 1

    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    assert bird not in state.battlefield
    assert bird in p1.graveyard


def test_vanishing_only_counts_down_on_its_own_controllers_upkeep():
    engine, state, p1, p2 = _engine()
    bird = _play_riftwatcher(engine, state, p1)
    state.active_player_index = 1  # p2's turn

    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    assert bird.counters.get("time") == 3


# ---------------------------------------------------------------------------
# Soulbond (RULE 702.94) — Deadeye Navigator
# ---------------------------------------------------------------------------


def _pair_navigator(engine, state):
    navigator = _catalogue_obj("Deadeye Navigator")
    state.add_to_battlefield(navigator)
    partner = _bf(state, _card("Partner"))
    state.fire_event(_etb(navigator))
    engine.rules.put_triggers_on_stack()
    while state.pending_choice and state.pending_choice["kind"] != "choose_objects":
        engine.rules.resolve_trigger_target_choice("do")
    engine.resolve_until_stable()
    # RULE 702.94a: which creature to pair with is a real choice now.
    if state.pending_choice and state.pending_choice["kind"] == "choose_objects":
        engine.resolve_pending_choice(str(partner.instance_id))
        engine.resolve_until_stable()
    return navigator, partner


def test_soulbond_pairs_two_creatures_and_records_it_on_both():
    engine, state, p1, _ = _engine()
    navigator, partner = _pair_navigator(engine, state)

    assert navigator.paired_with == partner.instance_id
    assert partner.paired_with == navigator.instance_id


def test_a_soulbond_pair_grants_the_quoted_ability_to_both_creatures():
    engine, state, p1, _ = _engine()
    navigator, partner = _pair_navigator(engine, state)
    engine.recompute_continuous_effects()

    assert navigator.granted_activated_abilities
    assert partner.granted_activated_abilities


def test_an_unpaired_soulbond_creature_grants_nothing():
    """The ``soulbond_pair`` selector resolves to nothing while unpaired, so
    the grant simply isn't there — no separate teardown."""
    engine, state, p1, _ = _engine()
    navigator = _catalogue_obj("Deadeye Navigator")
    state.add_to_battlefield(navigator)
    engine.recompute_continuous_effects()

    assert navigator.granted_activated_abilities == []


def test_a_pair_breaks_as_a_state_based_action_when_one_creature_leaves():
    """RULE 702.94c — swept centrally, so no individual removal site has to
    remember to tear the pair down."""
    engine, state, p1, _ = _engine()
    navigator, partner = _pair_navigator(engine, state)

    engine.rules.destroy(partner)
    engine.rules.check_state_based_actions()

    assert navigator.paired_with is None


def test_a_pair_breaks_when_the_two_stop_sharing_a_controller():
    engine, state, p1, p2 = _engine()
    navigator, partner = _pair_navigator(engine, state)

    partner.controller_id = "p2"
    engine.rules.check_state_based_actions()

    assert navigator.paired_with is None
    assert partner.paired_with is None


# ---------------------------------------------------------------------------
# Mutate (RULE 702.140) — Lore Drakkis
# ---------------------------------------------------------------------------


def _mutate_drakkis(engine, state, p1, host):
    drakkis = _catalogue_obj("Lore Drakkis", zone=Zone.HAND)
    p1.add_to_zone(drakkis, Zone.HAND)
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("R", 1)
    engine.cast_spell(p1, drakkis, targets=[host], mutate=True)
    return drakkis


def test_a_mutate_cast_pays_the_mutate_cost_instead_of_the_printed_one():
    engine, state, p1, _ = _engine()
    host = _bf(state, _card("Host"))
    drakkis = _catalogue_obj("Lore Drakkis", zone=Zone.HAND)
    p1.add_to_zone(drakkis, Zone.HAND)

    # Printed {1}{U}{R} = 3; mutate {U/R}{U/R} = 2.
    assert engine.effective_cast_cost(p1, drakkis).converted_mana_cost == 3
    assert engine.effective_cast_cost(p1, drakkis, mutate=True).converted_mana_cost == 2


def test_mutating_keeps_the_host_as_the_same_permanent():
    """RULE 702.140c: the merged permanent is the *same* permanent, which is
    why counters, damage and summoning sickness all carry over — and why
    mutate fires no enters-the-battlefield trigger."""
    engine, state, p1, _ = _engine()
    host = _bf(state, _card("Host"))
    host.add_counters("+1/+1", 2)
    host_id = host.instance_id
    etb_before = len([e for e in state.event_log if e.type == "ENTERS_BATTLEFIELD"])

    drakkis = _mutate_drakkis(engine, state, p1, host)
    engine.resolve_until_stable()

    survivor = state.find_object(host_id)
    assert survivor is not None and survivor in state.battlefield
    assert survivor.name == "Lore Drakkis"          # the creature on top
    assert survivor.counters.get("+1/+1") == 2      # same permanent
    assert drakkis not in state.battlefield         # never its own permanent
    etb_after = len([e for e in state.event_log if e.type == "ENTERS_BATTLEFIELD"])
    assert etb_after == etb_before


def test_mutating_keeps_all_abilities_from_under_it():
    engine, state, p1, _ = _engine()
    host = _bf(
        state,
        # Both halves of "all abilities from under it" have to carry: the
        # oracle text *and* the RULE 702 keyword list, which the keyword
        # catalogue reads directly rather than off the text.
        _card("Host", "Creature — Bear", oracle_text="Flying\nWhen this dies, draw a card.",
              keywords=["Flying"]),
    )
    _mutate_drakkis(engine, state, p1, host)
    engine.resolve_until_stable()

    survivor = state.find_object(host.instance_id)
    assert "When this dies" in survivor.card.oracle_text  # banked from underneath
    assert "flying" in survivor.intrinsic_keywords


def test_mutating_fires_its_own_event_and_the_drakkis_trigger():
    engine, state, p1, _ = _engine()
    host = _bf(state, _card("Host"))
    p1.add_to_zone(
        GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p1", zone=Zone.GRAVEYARD),
        Zone.GRAVEYARD,
    )

    _mutate_drakkis(engine, state, p1, host)
    engine.rules.resolve_top_of_stack()

    assert [e for e in state.event_log if e.type == "MUTATES"]
    engine.rules.put_triggers_on_stack()
    while state.pending_choice:
        options = [o for o in state.pending_choice["options"] if o["id"] != "decline"]
        engine.rules.resolve_trigger_target_choice(options[0]["id"])
    engine.resolve_until_stable()

    assert any(o.name == "Bolt" for o in p1.hand)


# ---------------------------------------------------------------------------
# Bargain — Beseech the Mirror
# ---------------------------------------------------------------------------


def test_bargain_is_only_payable_with_something_to_sacrifice():
    engine, state, p1, _ = _engine()
    spell = _catalogue_obj("Beseech the Mirror", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("B", 4)  # {1}{B}{B}{B}

    assert engine.can_cast(p1, spell, bargained=True) is False

    _bf(state, _card("Sol Ring", "Artifact", "{1}", 1))
    assert engine.can_cast(p1, spell, bargained=True) is True


def test_bargaining_sacrifices_the_permanent_and_sets_the_flag():
    engine, state, p1, _ = _engine()
    token = _bf(state, _card("Treasure", "Artifact — Treasure", "", 0))
    token.is_token = True
    spell = _catalogue_obj("Beseech the Mirror", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("B", 4)  # {1}{B}{B}{B}

    engine.cast_spell(p1, spell, bargained=True)

    assert spell.bargained is True
    assert token not in state.battlefield


def test_bargain_prefers_a_token_over_a_real_permanent():
    engine, state, p1, _ = _engine()
    real = _bf(state, _card("Sol Ring", "Artifact", "{1}", 1))
    token = _bf(state, _card("Treasure", "Artifact — Treasure", "", 0))
    token.is_token = True
    spell = _catalogue_obj("Beseech the Mirror", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("B", 4)  # {1}{B}{B}{B}

    engine.cast_spell(p1, spell, bargained=True)

    assert token not in state.battlefield
    assert real in state.battlefield


def test_an_unbargained_cast_leaves_the_conditional_effect_inert():
    engine, state, p1, _ = _engine()
    spell = _catalogue_obj("Beseech the Mirror", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("B", 4)  # {1}{B}{B}{B}

    engine.cast_spell(p1, spell)

    assert spell.bargained is False


# ---------------------------------------------------------------------------
# Underworld Breach — a *granted* Escape (RULE 702.138)
# ---------------------------------------------------------------------------


def test_underworld_breach_grants_escape_to_nonland_cards_in_your_graveyard():
    engine, state, p1, _ = _engine()
    breach = _catalogue_obj("Underworld Breach")
    state.add_to_battlefield(breach)
    bolt = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(bolt, Zone.GRAVEYARD)
    land = GameObject(_card("Mountain", "Basic Land — Mountain", "", 0),
                      owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(land, Zone.GRAVEYARD)

    assert engine._graveyard_cast_keyword(bolt) == "escape"
    assert engine._graveyard_cast_keyword(land) is None  # "each *nonland* card"


def test_a_granted_escape_cost_is_the_cards_own_mana_cost_plus_the_exile():
    engine, state, p1, _ = _engine()
    breach = _catalogue_obj("Underworld Breach")
    state.add_to_battlefield(breach)
    spell = GameObject(_card("Big", "Sorcery", "{2}{R}", 3), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(spell, Zone.GRAVEYARD)

    cost = engine._escape_cost(spell)
    assert cost.mana.converted_mana_cost == 3
    assert cost.exile_from_graveyard == 3


def test_a_granted_escape_needs_three_other_cards_in_the_graveyard():
    engine, state, p1, _ = _engine()
    breach = _catalogue_obj("Underworld Breach")
    state.add_to_battlefield(breach)
    bolt = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(bolt, Zone.GRAVEYARD)
    p1.mana_pool.add("R", 1)

    assert engine.can_cast(p1, bolt) is False  # nothing else to exile

    for i in range(3):
        p1.add_to_zone(
            GameObject(_card(f"Fuel{i}", "Instant", "{R}", 1), owner_id="p1",
                       zone=Zone.GRAVEYARD),
            Zone.GRAVEYARD,
        )
    assert engine.can_cast(p1, bolt) is True


def test_a_granted_escape_only_reaches_the_granting_players_own_graveyard():
    engine, state, p1, p2 = _engine()
    breach = _catalogue_obj("Underworld Breach")
    state.add_to_battlefield(breach)
    theirs = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p2", zone=Zone.GRAVEYARD)
    p2.add_to_zone(theirs, Zone.GRAVEYARD)

    assert engine._graveyard_cast_keyword(theirs) is None  # "**your** graveyard"


# ---------------------------------------------------------------------------
# The Pacts — a mandatory delayed payment with a consequence
# ---------------------------------------------------------------------------


def test_pact_of_negation_arms_a_delayed_payment_at_your_next_upkeep():
    engine, state, p1, p2 = _engine()
    victim = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(victim, Zone.HAND)
    p2.mana_pool.add("R", 1)
    engine.rules.cast_spell(p2, victim)

    pact = _catalogue_obj("Pact of Negation", zone=Zone.HAND)
    p1.add_to_zone(pact, Zone.HAND)
    engine.rules.cast_spell(p1, pact, targets=[victim])   # RULE 118.9: free
    engine.rules.resolve_top_of_stack()

    assert victim in p2.graveyard
    assert len(state.delayed_triggers) == 1


def test_paying_a_pact_keeps_you_in_the_game():
    engine, state, p1, _ = _engine()
    _arm_pact(engine, state, p1)
    p1.mana_pool.add("U", 5)

    engine._fire_delayed_triggers("upkeep")
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_pay_cost_then_choice("pay")

    assert p1.has_lost is False
    assert p1.mana_pool.total() == 0


def test_declining_a_pact_loses_the_game():
    engine, state, p1, _ = _engine()
    _arm_pact(engine, state, p1)
    p1.mana_pool.add("U", 5)

    engine._fire_delayed_triggers("upkeep")
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_pay_cost_then_choice("decline")

    assert p1.has_lost is True


def test_being_unable_to_pay_a_pact_loses_without_asking():
    """The "don't stall on a choice nobody can act on" shortcut — and here it
    is also the only correct outcome."""
    engine, state, p1, _ = _engine()
    _arm_pact(engine, state, p1)

    engine._fire_delayed_triggers("upkeep")
    engine.rules.resolve_top_of_stack()

    assert state.pending_choice is None
    assert p1.has_lost is True


def _arm_pact(engine, state, p1):
    pact = _catalogue_obj("Pact of Negation", zone=Zone.HAND)
    p1.add_to_zone(pact, Zone.HAND)
    from mtg_analyzer.game.effects import CreateDelayedTriggerEffect, GameContext

    CreateDelayedTriggerEffect(
        step="upkeep",
        scope="controller",
        effects=[{
            "type": "pay_cost_then",
            "params": {
                "cost": "{3}{U}{U}",
                "effects": [],
                "else_effects": [{"type": "lose_game", "params": {}}],
            },
        }],
        source=pact,
    ).apply(GameContext(state, engine.rules))
    return pact


# ---------------------------------------------------------------------------
# Corpse Dance — a delayed exile of "that creature"
# ---------------------------------------------------------------------------


def test_corpse_dance_returns_a_creature_and_arms_its_delayed_exile():
    engine, state, p1, _ = _engine()
    dead = GameObject(_card("Zombie"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(dead, Zone.GRAVEYARD)

    spell = _catalogue_obj("Corpse Dance", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("B", 3)  # {2}{B}
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()

    assert dead in state.battlefield
    assert "haste" in dead.temp_keywords
    assert len(state.delayed_triggers) == 1

    engine._fire_delayed_triggers("end")
    engine.resolve_until_stable()

    assert dead not in state.battlefield
    assert dead.zone == Zone.EXILE
