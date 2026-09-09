"""MEC-43 "near-free reuses" batch (2026-08-21) — `cEDH staples 2`'s
remaining gaps that only needed an existing primitive recoloured/
param-widened. Covers the genuinely new/widened primitives each card
needed: `GameObject.sacrificed_cost_power` + `MillEffect.count_selector`
(Altar of Dementia); `graveyard_redirect` (Leyline of the Void/Rest in
Peace); the `draw_exile_face_up` replacement (Uba Mask);
`EachPlayerPayOrEffect`'s `scope`/`effect_targets` (Acererak the Archlich);
`BounceOwnLandFromTriggerEffect` (Mana Breach);
`DrawIfTriggerObjectGreatestPowerEffect` (Selvala, Heart of the Wilds);
`cast_prohibition`'s `color`/`creature_only` (Llawan, Cephalid Empress);
`grant_borrowed_activated_ability`'s `source_mode="top_of_library"`
(Conspicuous Snoop); `dig_until`'s `rest_destination="graveyard"`
(Hermit Druid); `AddManaEffect`'s widened ANY-branch (Burnt Offering);
`ManaPool.last_payment_types` + `ActivationCost.note_spent_color` +
`AddManaEffect.color_from_source_noted_color` (Jeweled Amulet — the
ticket's own deliberately-deferred card, closed in a follow-up pass).

Reference: docs/implementation-state/Done_Backend.md "MEC-43" entry.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _engine():
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    return GameEngine(state), state, p1, p2


def _card(name, type_line="Creature — Bear", cost="", cmc=0, **kw):
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=cmc, **kw,
    )


def _bear(name="Bear", cost="{1}{G}", cmc=2, power=2, toughness=2):
    return _card(
        name, "Creature — Bear", cost, cmc, is_creature=True, power=power, toughness=toughness,
    )


def _bf(state, card, controller="p1", obj=None, bind=False):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    if bind:
        bind_from_catalogue(obj)
    return obj


def _catalogue_obj(state, name, controller="p1", zone=Zone.BATTLEFIELD, sick=False):
    obj = GameObject(_named(name), owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    obj.summoning_sick = sick
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    return obj


def _to_hand(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).hand.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Altar of Dementia — sacrificed_cost_power + MillEffect.count_selector
# ---------------------------------------------------------------------------


def test_altar_of_dementia_mills_equal_to_sacrificed_power():
    engine, state, p1, p2 = _engine()
    altar = _catalogue_obj(state, "Altar of Dementia", controller="p1")
    victim = _bf(state, _bear("Big Bear", power=5, toughness=5), controller="p1", bind=True)
    for _ in range(10):
        p2.library.append(GameObject(_bear(f"Filler {_}"), owner_id="p2", zone=Zone.LIBRARY))
    engine.recompute_continuous_effects()

    engine.activate_ability(p1, altar, ability_index=0, targets=[p2], sacrifice_choice=victim.instance_id)
    engine.resolve_until_stable()

    assert len(p2.graveyard) == 5
    assert len(p2.library) == 5
    assert victim not in state.battlefield


# ---------------------------------------------------------------------------
# Leyline of the Void / Rest in Peace — graveyard_redirect
# ---------------------------------------------------------------------------


def test_leyline_of_the_void_exiles_only_opponents_graveyard_bound_cards():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Leyline of the Void", controller="p1")
    engine.recompute_continuous_effects()

    opp_creature = _bf(state, _bear("Opp Bear"), controller="p2", bind=True)
    own_creature = _bf(state, _bear("Own Bear"), controller="p1", bind=True)

    engine.rules.destroy(opp_creature)
    engine.rules.destroy(own_creature)

    assert opp_creature in p2.exile
    assert opp_creature not in p2.graveyard
    assert own_creature in p1.graveyard
    assert own_creature not in p1.exile


def test_rest_in_peace_exiles_every_players_graveyard_bound_cards():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Rest in Peace", controller="p1")
    engine.recompute_continuous_effects()

    own_creature = _bf(state, _bear("Own Bear"), controller="p1", bind=True)
    engine.rules.destroy(own_creature)

    assert own_creature in p1.exile
    assert own_creature not in p1.graveyard


# ---------------------------------------------------------------------------
# Uba Mask — the draw_exile_face_up replacement
# ---------------------------------------------------------------------------


def test_uba_mask_exiles_drawn_cards_and_grants_temp_play_permission():
    engine, state, p1, _ = _engine()
    _catalogue_obj(state, "Uba Mask", controller="p1")
    engine.recompute_continuous_effects()

    top = GameObject(_bear("Library Bear"), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(top)
    before_hand = len(p1.hand)

    engine.rules.draw(p1, 1)

    assert len(p1.hand) == before_hand
    assert top in p1.exile
    assert state.temp_play_permissions.get(top.instance_id) == state.internal_turn.number


# ---------------------------------------------------------------------------
# Acererak the Archlich — EachPlayerPayOrEffect's scope/effect_targets
# ---------------------------------------------------------------------------


def test_acererak_attack_makes_controller_a_token_when_opponent_declines():
    engine, state, p1, p2 = _engine()
    acererak = _catalogue_obj(state, "Acererak the Archlich", controller="p1")
    engine.recompute_continuous_effects()
    before = len(state.battlefield)

    state.fire_event(GameEvent(
        EventType.ATTACKS, attacker=acererak.name, player_id="p1",
        instance_id=acererak.instance_id, object_types=sorted(acererak.type_words),
    ))
    engine.resolve_until_stable()
    # Bob (p2) has no creature to sacrifice, so he can't pay — the
    # "unless" falls through without a choice and Acererak's own
    # controller gets the token.
    assert state.pending_choice is None

    assert len(state.battlefield) == before + 1
    zombies = [o for o in state.battlefield if o.name == "Zombie" and o.controller_id == "p1"]
    assert len(zombies) == 1


def test_acererak_attack_makes_no_token_when_opponent_sacrifices():
    engine, state, p1, p2 = _engine()
    acererak = _catalogue_obj(state, "Acererak the Archlich", controller="p1")
    victim = _bf(state, _bear("Bob's Bear"), controller="p2", bind=True)
    engine.recompute_continuous_effects()
    before = len(state.battlefield)

    state.fire_event(GameEvent(
        EventType.ATTACKS, attacker=acererak.name, player_id="p1",
        instance_id=acererak.instance_id, object_types=sorted(acererak.type_words),
    ))
    engine.resolve_until_stable()

    # A real pending_choice opens for Bob (he *could* sacrifice his bear) —
    # paying should remove the bear and create no token.
    assert state.pending_choice is not None
    assert state.pending_choice.get("kind") == "pay_cost_then"
    engine.rules.resolve_choice("pay")
    engine.resolve_until_stable()

    assert victim not in state.battlefield
    zombies = [o for o in state.battlefield if o.name == "Zombie"]
    assert not zombies
    assert len(state.battlefield) == before - 1  # only the sacrificed bear left the board


# ---------------------------------------------------------------------------
# Mana Breach — BounceOwnLandFromTriggerEffect
# ---------------------------------------------------------------------------


def test_mana_breach_bounces_the_casters_own_land_not_the_controllers():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Mana Breach", controller="p1")
    engine.recompute_continuous_effects()

    p1_land = _bf(state, _card("Forest", "Basic Land — Forest", is_land=True), controller="p1", bind=True)
    p2_land = _bf(state, _card("Island", "Basic Land — Island", is_land=True), controller="p2", bind=True)

    spell = _to_hand(state, _card("Shock", "Instant", "{R}", 1, is_instant=True), controller="p2")
    p2.mana_pool.add_many({"R": 1})
    state.current_step = "main1"
    state.active_player_index = state.players.index(p2)

    engine.cast_spell(p2, spell)
    engine.resolve_until_stable()

    assert p2_land not in state.battlefield
    assert any(o is p2_land for o in p2.hand)
    assert p1_land in state.battlefield


# ---------------------------------------------------------------------------
# Selvala, Heart of the Wilds — DrawIfTriggerObjectGreatestPowerEffect
# ---------------------------------------------------------------------------


def test_selvala_draws_when_entering_creature_has_strictly_greatest_power():
    engine, state, p1, _ = _engine()
    p1.library.append(GameObject(_bear("Library Filler"), owner_id="p1", zone=Zone.LIBRARY))
    _catalogue_obj(state, "Selvala, Heart of the Wilds", controller="p1")
    _bf(state, _bear("Small Bear", power=2, toughness=2), controller="p1", bind=True)
    engine.recompute_continuous_effects()
    before = len(p1.hand)

    big = GameObject(_bear("Huge Bear", power=9, toughness=9), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(big)
    state.add_to_battlefield(big)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", object=big.name,
        instance_id=big.instance_id, object_types=sorted(big.type_words),
    ))
    engine.resolve_until_stable()

    assert len(p1.hand) == before + 1


def test_selvala_does_not_draw_on_a_power_tie():
    engine, state, p1, _ = _engine()
    _catalogue_obj(state, "Selvala, Heart of the Wilds", controller="p1")
    _bf(state, _bear("Tied Bear", power=3, toughness=3), controller="p1", bind=True)
    engine.recompute_continuous_effects()
    before = len(p1.hand)

    twin = GameObject(_bear("Twin Bear", power=3, toughness=3), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(twin)
    state.add_to_battlefield(twin)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", object=twin.name,
        instance_id=twin.instance_id, object_types=sorted(twin.type_words),
    ))
    engine.resolve_until_stable()

    assert len(p1.hand) == before


# ---------------------------------------------------------------------------
# Llawan, Cephalid Empress — cast_prohibition's color + creature_only
# ---------------------------------------------------------------------------


def test_llawan_prohibits_only_blue_creature_spells():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Llawan, Cephalid Empress", controller="p1")
    engine.recompute_continuous_effects()

    blue_creature = _card(
        "Merfolk Looter", "Creature — Merfolk", "{1}{U}", 2, is_creature=True,
        power=1, toughness=1, color_identity=["U"],
    )
    blue_instant = _card("Counterspell", "Instant", "{U}{U}", 2, is_instant=True, color_identity=["U"])
    red_creature = _card(
        "Goblin", "Creature — Goblin", "{R}", 1, is_creature=True,
        power=1, toughness=1, color_identity=["R"],
    )

    assert continuous.cast_prohibited(state, p2, blue_creature) is True
    assert continuous.cast_prohibited(state, p2, blue_instant) is False
    assert continuous.cast_prohibited(state, p2, red_creature) is False
    # Llawan's own controller is unrestricted.
    assert continuous.cast_prohibited(state, p1, blue_creature) is False


# ---------------------------------------------------------------------------
# Conspicuous Snoop — grant_borrowed_activated_ability's top_of_library mode
# ---------------------------------------------------------------------------


def test_conspicuous_snoop_borrows_the_top_goblins_activated_ability():
    # A real cached card with an oracle-text activated ability — the
    # synthetic `_bear`-shaped test cards elsewhere in this file carry no
    # oracle text at all, so binding one would trivially grant nothing.
    engine, state, p1, _ = _engine()
    snoop = _catalogue_obj(state, "Conspicuous Snoop", controller="p1")
    goblin = _named("Krenko, Mob Boss")
    p1.library.append(GameObject(goblin, owner_id="p1", zone=Zone.LIBRARY))
    engine.recompute_continuous_effects()

    assert len(snoop.granted_activated_abilities) >= 1


def test_conspicuous_snoop_grants_nothing_when_top_card_is_not_a_goblin():
    engine, state, p1, _ = _engine()
    snoop = _catalogue_obj(state, "Conspicuous Snoop", controller="p1")
    p1.library.append(GameObject(_bear("Plain Bear"), owner_id="p1", zone=Zone.LIBRARY))
    engine.recompute_continuous_effects()

    assert snoop.granted_activated_abilities == []


# ---------------------------------------------------------------------------
# Hermit Druid — dig_until's rest_destination="graveyard"
# ---------------------------------------------------------------------------


def test_hermit_druid_puts_basic_in_hand_and_rest_in_graveyard():
    engine, state, p1, _ = _engine()
    druid = _catalogue_obj(state, "Hermit Druid", controller="p1")
    p1.mana_pool.add_many({"G": 1})

    nonland_a = _bear("Nonland A")
    nonland_b = _bear("Nonland B")
    basic = _card("Forest", "Basic Land — Forest", is_land=True)
    # Library top is the end of the list.
    for card in (basic, nonland_b, nonland_a):
        p1.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))
    before_hand = len(p1.hand)

    engine.activate_ability(p1, druid, ability_index=0)
    engine.resolve_until_stable()

    assert len(p1.hand) == before_hand + 1
    assert any(o.name == "Forest" for o in p1.hand)
    graveyard_names = {o.name for o in p1.graveyard}
    assert graveyard_names == {"Nonland A", "Nonland B"}


# ---------------------------------------------------------------------------
# Burnt Offering — AddManaEffect's widened ANY-branch amount_selector
# ---------------------------------------------------------------------------


def test_burnt_offering_adds_mana_equal_to_sacrificed_creatures_mana_value():
    engine, state, p1, _ = _engine()
    spell = _to_hand(state, _named("Burnt Offering"), controller="p1")
    p1.mana_pool.add_many({"B": 1})
    victim = _bf(state, _bear("Fat Bear", cost="{3}{G}", cmc=4), controller="p1", bind=True)
    state.current_step = "main1"

    engine.cast_spell(p1, spell, sacrifice_choice=victim.instance_id)
    engine.resolve_until_stable()
    if state.pending_choice and state.pending_choice.get("kind") == "add_mana_any_color":
        engine.rules.resolve_choice("B")
        engine.resolve_until_stable()

    total = sum(p1.mana_pool.pool.get(c, 0) for c in ("B", "R"))
    assert total == 4


# ---------------------------------------------------------------------------
# Jeweled Amulet — ManaPool.last_payment_types + note_spent_color +
# AddManaEffect.color_from_source_noted_color
# ---------------------------------------------------------------------------


def test_jeweled_amulet_notes_the_color_spent_and_replays_it():
    engine, state, p1, _ = _engine()
    amulet = _catalogue_obj(state, "Jeweled Amulet", controller="p1")
    engine.recompute_continuous_effects()

    p1.mana_pool.add_many({"G": 1})
    engine.activate_ability(p1, amulet, ability_index=0)
    engine.resolve_until_stable()

    assert amulet.noted_mana_color == "G"
    assert amulet.counters.get("charge") == 1
    # Can't activate the second ability again while still tapped from the
    # first — untap to simulate a later turn (RULE 302.6 taps-self cost).
    amulet.untap()

    engine.activate_ability(p1, amulet, ability_index=1)
    engine.resolve_until_stable()

    assert p1.mana_pool.pool.get("G") == 1
    assert amulet.counters.get("charge", 0) == 0


def test_jeweled_amulet_activation_gated_by_existing_charge_counter():
    engine, state, p1, _ = _engine()
    amulet = _catalogue_obj(state, "Jeweled Amulet", controller="p1")
    engine.recompute_continuous_effects()
    amulet.counters["charge"] = 1

    assert engine.can_activate(p1, amulet, amulet.activated_abilities[0]) is False
