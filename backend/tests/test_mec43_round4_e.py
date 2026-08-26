"""MEC-43 round 4E — Tergrid God of Fright, Swift Reconfiguration, Angel's
Grace, Mesmeric Orb, Smokestack, Oko Thief of Crowns.

One focused test (or a small closely-related pair) per card, each proving
the real new-primitive behaviour in a live `GameEngine`/`RulesEngine`
rather than just checking the parser's coverage verdict:

* Tergrid, God of Fright — an opponent's sacrifice/discard of a permanent
  reanimates it under Tergrid's controller (`ReturnFromGraveyardEffect`'s
  ``trigger_subject_key`` mode wrapped in a free `PayCostThenEffect`), and
  Tergrid's Lantern's own compound `ActivationCost.sacrifice_or_discard`
  cost plus its ``payer="target"`` mode.
* Swift Reconfiguration — the enchanted permanent becomes a non-creature
  Vehicle artifact with a granted Crew 5 ability, and crewing it turns it
  back into a creature at its own printed power/toughness.
* Angel's Grace — the new `EventType.DAMAGE` life-floor replacement and
  the turn-scoped `WinConditionEffect` grant.
* Mesmeric Orb — the new `EventType.UNTAPPED` event (`RulesEngine.
  set_tapped`'s widened untap direction) actually reaching a real
  triggered ability.
* Smokestack — `SacrificePermanentsPerCounterEffect`'s "each player's
  upkeep" mass tax, Tangle Wire-shaped.
* Oko, Thief of Crowns — the Elk template reused resolve-time, and
  `ExchangeControlEffect`'s new two-independently-chosen-targets mode.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.services.card_database import CardDatabase


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


def _engine(*player_ids):
    players = [Player(id=pid, life=20) for pid in player_ids] or [
        Player(id="p1", life=20), Player(id="p2", life=20),
    ]
    state = GameState(players=players)
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _card(name, type_line="Artifact", cost="{0}", cmc=0, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _land(name, subtype="Forest"):
    return Card(id=name, name=name, type_line=f"Basic Land — {subtype}", is_land=True)


def _step(step):
    return GameEvent(EventType.STEP_BEGIN, step=step)


# ---------------------------------------------------------------------------
# Tergrid, God of Fright — reanimating a sacrificed/discarded permanent
# ---------------------------------------------------------------------------


def test_tergrid_reanimates_an_opponents_sacrificed_permanent_under_her_control():
    engine, state = _engine("p1", "p2")
    tergrid = _bf(state, _named("Tergrid, God of Fright // Tergrid's Lantern"), controller="p1")
    victim = _bf(state, _card("Fodder Artifact"), controller="p2")
    engine.recompute_continuous_effects()

    engine.rules.put_into_graveyard(victim)  # RULE 701.17: a genuine sacrifice
    engine.resolve_until_stable()

    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "pay_cost_then"
    engine.rules.resolve_pay_cost_then_choice("pay")
    engine.resolve_until_stable()

    assert victim in state.battlefield
    assert victim.controller_id == "p1"


def test_tergrid_reanimates_an_opponents_discarded_permanent_card_but_not_a_spell():
    engine, state = _engine("p1", "p2")
    p2 = state.player_by_id("p2")
    tergrid = _bf(state, _named("Tergrid, God of Fright // Tergrid's Lantern"), controller="p1")
    permanent_card = GameObject(_card("Fodder Creature", "Creature", is_creature=True, power=1, toughness=1),
                                 owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(permanent_card, Zone.HAND)
    engine.recompute_continuous_effects()

    engine.rules.discard_specific(permanent_card)
    engine.resolve_until_stable()

    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "pay_cost_then"
    engine.rules.resolve_pay_cost_then_choice("pay")
    engine.resolve_until_stable()

    assert permanent_card in state.battlefield
    assert permanent_card.controller_id == "p1"


def test_tergrids_lantern_offers_a_sacrifice_or_discard_choice_and_forces_life_loss_otherwise():
    # First: the target has both a nonland permanent and a hand card, so
    # paying opens the new `sacrifice_or_discard` choice.
    engine, state = _engine("p1", "p2")
    p2 = state.player_by_id("p2")
    lantern_card = _named("Tergrid, God of Fright // Tergrid's Lantern")
    lantern = _bf(state, lantern_card, controller="p1")
    assert engine.rules.transform_permanent(lantern)
    assert lantern.card.name == "Tergrid's Lantern"

    junk = _bf(state, _card("Junk"), controller="p2")
    hand_card = GameObject(_card("Hand Filler"), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(hand_card, Zone.HAND)
    engine.recompute_continuous_effects()

    p1 = state.player_by_id("p1")
    engine.activate_ability(p1, lantern, 0, targets=[p2])
    engine.resolve_until_stable()

    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "pay_cost_then"
    engine.rules.resolve_pay_cost_then_choice("pay")
    engine.resolve_until_stable()

    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "sacrifice_or_discard"
    engine.resolve_pending_choice("discard")
    engine.resolve_until_stable()

    assert hand_card not in p2.hand
    assert junk in state.battlefield  # sacrifice half untouched
    assert p2.life == 20  # paid, so no life lost


def test_tergrids_lantern_forces_life_loss_when_the_target_cannot_pay_either_half():
    engine, state = _engine("p1", "p2")
    p2 = state.player_by_id("p2")
    lantern = _bf(state, _named("Tergrid, God of Fright // Tergrid's Lantern"), controller="p1")
    assert engine.rules.transform_permanent(lantern)
    engine.recompute_continuous_effects()

    p1 = state.player_by_id("p1")
    engine.activate_ability(p1, lantern, 0, targets=[p2])
    engine.resolve_until_stable()

    # p2 controls nothing and has an empty hand — can't pay either half, so
    # the "unless" resolves straight to the life-loss branch, no choice at all.
    assert state.pending_choice is None
    assert p2.life == 17


def test_tergrids_lantern_second_ability_untaps_itself():
    engine, state = _engine("p1")
    lantern = _bf(state, _named("Tergrid, God of Fright // Tergrid's Lantern"), controller="p1")
    assert engine.rules.transform_permanent(lantern)
    lantern.tapped = True
    engine.recompute_continuous_effects()

    p1 = state.player_by_id("p1")
    p1.mana_pool.add("C", 3)
    p1.mana_pool.add("B", 1)
    engine.activate_ability(p1, lantern, 1)
    engine.resolve_until_stable()

    assert lantern.tapped is False


# ---------------------------------------------------------------------------
# Swift Reconfiguration — the enchanted permanent becomes a Vehicle
# ---------------------------------------------------------------------------


def test_swift_reconfiguration_turns_the_host_into_an_uncrewed_vehicle_artifact():
    engine, state = _engine("p1")
    host = _bf(state, _card("Bear", "Creature — Bear", "{1}{G}", 2, is_creature=True,
                             power=2, toughness=2), controller="p1")
    aura = _bf(state, _named("Swift Reconfiguration"), controller="p1")
    aura.attached_to = host.instance_id
    engine.recompute_continuous_effects()

    assert host.is_creature is False
    assert host.card.type_line == "Creature — Bear"  # printed card itself is untouched
    assert "artifact" in host.type_words
    assert combat.matches_object_filter(host, {"subtype": "vehicle"})
    granted = [a for a in host.granted_activated_abilities if getattr(a.cost, "crew_power", None) == 5]
    assert granted, "Crew 5 should be granted onto the enchanted permanent"


def test_swift_reconfiguration_crewing_makes_the_host_a_creature_at_its_own_power():
    engine, state = _engine("p1")
    host = _bf(state, _card("Bear", "Creature — Bear", "{1}{G}", 2, is_creature=True,
                             power=2, toughness=2), controller="p1")
    aura = _bf(state, _named("Swift Reconfiguration"), controller="p1")
    aura.attached_to = host.instance_id
    crewer = _bf(state, _card("Big Crewer", "Creature — Giant", "{5}", 5, is_creature=True,
                               power=5, toughness=5), controller="p1")
    engine.recompute_continuous_effects()

    p1 = state.player_by_id("p1")
    engine.activate_ability(p1, host, 0)  # the sole granted ability: Crew 5
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()

    assert crewer.tapped is True
    assert host.is_creature is True
    assert host.power == 2 and host.toughness == 2


# ---------------------------------------------------------------------------
# Angel's Grace — the damage floor and the turn-scoped "can't lose"
# ---------------------------------------------------------------------------


def test_angels_grace_floors_lethal_damage_and_prevents_a_non_damage_loss():
    engine, state = _engine("p1", "p2")
    p1 = state.player_by_id("p1")
    grace = GameObject(_named("Angel's Grace"), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(grace, Zone.HAND)
    bind_from_catalogue(grace)
    p1.mana_pool.add("W", 1)

    engine.cast_spell(p1, grace)
    engine.resolve_until_stable()

    p1.life = 5
    engine.rules.deal_damage(p1, 20, source=None)
    assert p1.life == 1
    engine.rules.check_state_based_actions()
    assert p1.has_lost is False

    # A non-damage life loss (paying life as a cost, say) isn't floored by
    # the damage-only replacement, but the separate "can't lose" grant
    # still covers it for the rest of the turn.
    p1.life = 0
    engine.rules.check_state_based_actions()
    assert p1.has_lost is False


# ---------------------------------------------------------------------------
# Mesmeric Orb — a real per-permanent EventType.UNTAPPED
# ---------------------------------------------------------------------------


def test_mesmeric_orb_mills_when_a_permanent_becomes_untapped():
    engine, state = _engine("p1")
    p1 = state.player_by_id("p1")
    _bf(state, _named("Mesmeric Orb"), controller="p1")
    land = _bf(state, _land("Forest"), controller="p1")
    land.tapped = True
    for i in range(3):
        p1.library.append(GameObject(_land(f"Filler {i}"), owner_id="p1", zone=Zone.LIBRARY))
    engine.recompute_continuous_effects()

    before_library = len(p1.library)
    before_graveyard = len(p1.graveyard)
    engine.rules.set_tapped(land, False)
    engine.resolve_until_stable()

    assert len(p1.graveyard) == before_graveyard + 1
    assert len(p1.library) == before_library - 1


def test_mesmeric_orb_triggers_during_the_real_untap_step():
    engine, state = _engine("p1")
    p1 = state.player_by_id("p1")
    _bf(state, _named("Mesmeric Orb"), controller="p1")
    land = _bf(state, _land("Forest"), controller="p1")
    land.tapped = True
    for i in range(2):
        p1.library.append(GameObject(_land(f"Filler {i}"), owner_id="p1", zone=Zone.LIBRARY))
    engine.recompute_continuous_effects()

    before_graveyard = len(p1.graveyard)
    engine._step_untap()
    engine.resolve_until_stable()

    assert land.tapped is False
    assert len(p1.graveyard) == before_graveyard + 1


def test_untapping_does_not_mill_without_mesmeric_orb_on_the_battlefield():
    engine, state = _engine("p1")
    p1 = state.player_by_id("p1")
    land = _bf(state, _land("Forest"), controller="p1")
    land.tapped = True
    p1.library.append(GameObject(_land("Filler"), owner_id="p1", zone=Zone.LIBRARY))
    engine.recompute_continuous_effects()

    before = len(p1.library)
    engine.rules.set_tapped(land, False)
    engine.resolve_until_stable()

    assert len(p1.library) == before


# ---------------------------------------------------------------------------
# Smokestack — the "each player's upkeep" mass sacrifice tax
# ---------------------------------------------------------------------------


def test_smokestack_taxes_each_players_upkeep_by_its_soot_counters():
    engine, state = _engine("p1", "p2")
    smokestack = _bf(state, _named("Smokestack"), controller="p1")
    smokestack.counters["soot"] = 2
    theirs = [_bf(state, _card(f"Junk{i}"), controller="p2") for i in range(2)]
    engine.recompute_continuous_effects()

    state.active_player_index = 1  # p2's upkeep
    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    # Exactly as many candidates as the soot count — nothing to choose
    # between, so both are sacrificed without a prompt (RULE 701.17).
    assert state.pending_choice is None
    assert all(o not in state.battlefield for o in theirs)


def test_smokestacks_own_upkeep_soot_counter_is_optional():
    engine, state = _engine("p1")
    smokestack = _bf(state, _named("Smokestack"), controller="p1")
    engine.recompute_continuous_effects()

    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    # RULE 603.5's own "you may" trigger framing (`AbilitySpec(optional=
    # True)`), not `pay_cost_then` — this ability pays no cost at all.
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "trigger_target"
    engine.resolve_pending_choice("do")
    engine.resolve_until_stable()

    assert smokestack.counters.get("soot", 0) == 1


# ---------------------------------------------------------------------------
# Oko, Thief of Crowns
# ---------------------------------------------------------------------------


def test_okos_plus_one_turns_the_target_into_a_vanilla_green_elk():
    engine, state = _engine("p1")
    p1 = state.player_by_id("p1")
    host = _bf(state, _card("Angry Bear", "Creature — Bear", "{1}{G}", 2, is_creature=True,
                             power=4, toughness=4, oracle_text="Trample",
                             keywords=["Trample"]), controller="p1")
    oko = _bf(state, _named("Oko, Thief of Crowns"), controller="p1")
    engine.recompute_continuous_effects()

    engine.activate_ability(p1, oko, 1, targets=[host])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()

    assert host.power == 3 and host.toughness == 3
    assert "G" in host.colors
    assert combat.matches_object_filter(host, {"subtype": "elk"})
    assert host.loses_all_abilities is True


def test_okos_minus_five_exchanges_control_of_two_independent_targets():
    engine, state = _engine("p1", "p2")
    p1 = state.player_by_id("p1")
    mine = _bf(state, _card("My Rock"), controller="p1")
    theirs = _bf(state, _card("Weak Bear", "Creature — Bear", "{1}{G}", 2, is_creature=True,
                               power=2, toughness=2), controller="p2")
    strong_theirs = _bf(state, _card("Strong Titan", "Creature — Giant", "{5}{G}", 6, is_creature=True,
                                      power=6, toughness=6), controller="p2")
    oko = _bf(state, _named("Oko, Thief of Crowns"), controller="p1")
    oko.counters["loyalty"] = 5
    engine.recompute_continuous_effects()

    # The high-power opponent creature must not be a legal second target.
    from mtg_analyzer.game import targeting
    second_spec = targeting.ability_target_specs(oko.activated_abilities[2])[1]
    legal = targeting.legal_targets(state, "p1", second_spec, source=oko)
    legal_ids = {t["instance_id"] for t in legal}
    assert theirs.instance_id in legal_ids
    assert strong_theirs.instance_id not in legal_ids

    engine.activate_ability(p1, oko, 2, targets=[mine, theirs])
    engine.resolve_until_stable()

    assert mine.controller_id == "p2"
    assert theirs.controller_id == "p1"
    assert strong_theirs.controller_id == "p2"  # untouched


def test_okos_plus_two_creates_a_food_token():
    engine, state = _engine("p1")
    p1 = state.player_by_id("p1")
    oko = _bf(state, _named("Oko, Thief of Crowns"), controller="p1")
    engine.recompute_continuous_effects()

    engine.activate_ability(p1, oko, 0)
    engine.resolve_until_stable()

    assert any(o.name == "Food" and o.controller_id == "p1" for o in state.battlefield)
