"""MEC-131 — "... at end of combat" delayed riders whose target is announced with the ability, executed on the engine.

RULE 601.2c / 602.2b: the target is chosen when the ability is activated. RULE 603.7c: the delayed ability then refers
to that object; it does not target again. RULE 400.7: an object that left and returned is a new object it leaves alone.
RULE 602.5d / 500.1: "Activate only before the end of combat step."
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

from tests.test_par202_end_of_combat import (
    _advance_to, _alive, _attack, _block_only, _creature, _end_of_combat, _engine, _parse,
)

ASSASSIN = "{3}{B}: Destroy target blocking creature at end of combat."
SEA_CLAN = (
    "{T}: Choose target attacking or blocking creature whose controller controls an Island. ~ deals 2 damage to that "
    "creature at end of combat. Activate only before the end of combat step."
)
TOUGH = 9


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


def _land(eng, owner, subtype="Island"):
    card = Card(id=subtype, name=subtype, type_line=f"Basic Land — {subtype}", is_land=True)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    eng.state.add_to_battlefield(obj)
    return obj


def _activate(eng, who, source, targets, mana=None):
    player = eng.state.player_by_id(who)
    if mana:
        player.mana_pool.add_many(mana)
    eng.activate_ability(player, source, 0, targets=targets)
    eng.resolve_until_stable()


# --- parse shape -----------------------------------------------------------------------------------------------


def test_assassin_announces_the_target_then_arms_a_delayed_destroy_on_that_pick():
    result = _parse(ASSASSIN)
    assert result.modeled
    effects = next(s for s in result.specs if s.ability_kind == "activated").effects
    assert [e.type for e in effects] == ["choose_targets", "create_delayed_trigger"]
    assert effects[0].params["creature_filter"] == {"blocking": True}
    assert effects[1].params["capture"] == "previous_targets" and effects[1].params["step"] == "end_combat"
    assert effects[1].params["effects"] == [{"type": "destroy_specific", "params": {}}]


def test_sea_clan_filters_on_the_controllers_island_and_gates_on_the_step():
    result = _parse(SEA_CLAN)
    assert result.modeled
    effects = next(s for s in result.specs if s.ability_kind == "activated").effects
    assert effects[0].params["kinds"] == ["creature"]
    assert effects[0].params["creature_filter"] == {
        "attacking_or_blocking": True, "controller_controls_land_subtype": "island",
    }
    assert effects[1].params["capture"] == "previous_targets"
    assert effects[1].params["effects"] == [{"type": "damage_specific", "params": {"amount": 2}}]
    assert effects[2].params["condition"] == {"kind": "before_step", "step": "end_combat"}


@pytest.mark.parametrize("name", ["Silent Assassin", "Dwarven Sea Clan"])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


@pytest.mark.parametrize(
    "oracle",
    [
        # a "tap"/"exile" rider is a different verb: only the destroy shape is claimed
        "{3}{B}: Exile target blocking creature at end of combat.",
        # a destroy that is not an end-of-combat rider is the ordinary spell
        "{3}{B}: Destroy target blocking creature with flying at end of combat and draw a card.",
    ],
)
def test_other_shapes_stay_unclaimed(oracle):
    assert _parse(oracle).modeled is False


# --- Silent Assassin -------------------------------------------------------------------------------------------


def _assassin_board():
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1", power=0, toughness=TOUGH)
    blocker = _creature(eng, "Blocker", "p2", power=0, toughness=TOUGH)
    assassin = _creature(eng, "Silent Assassin", "p2", ASSASSIN, power=1, toughness=1)
    return eng, attacker, blocker, assassin


def test_assassin_destroys_the_chosen_blocker_only_at_end_of_combat():
    eng, attacker, blocker, assassin = _assassin_board()
    _block_only(eng, blocker, attacker)
    _activate(eng, "p2", assassin, [blocker], {"B": 1, "C": 3})
    assert _alive(eng, blocker) and len(eng.state.delayed_triggers) == 1  # nothing happens yet
    _end_of_combat(eng)
    assert not _alive(eng, blocker) and _alive(eng, attacker) and _alive(eng, assassin)
    assert not eng.state.delayed_triggers  # once only


def test_assassin_cannot_target_a_creature_that_is_not_blocking():
    eng, attacker, blocker, assassin = _assassin_board()
    _block_only(eng, blocker, attacker)
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    spec = TargetSpec(kind="creature", creature_filter={"blocking": True})
    ids = [o["instance_id"] for o in legal_targets(eng.state, "p2", spec, assassin)]
    assert blocker.instance_id in ids and attacker.instance_id not in ids


def test_assassin_target_that_left_and_returned_is_untouched():
    # RULE 400.7: the delayed destroy names the blocker's earlier visit; the returned object is a new one.
    eng, attacker, blocker, assassin = _assassin_board()
    _block_only(eng, blocker, attacker)
    _activate(eng, "p2", assassin, [blocker], {"B": 1, "C": 3})
    eng.rules.blink(blocker)
    _end_of_combat(eng)
    assert _alive(eng, blocker)


def test_assassin_target_that_left_combat_zone_is_simply_gone():
    eng, attacker, blocker, assassin = _assassin_board()
    _block_only(eng, blocker, attacker)
    _activate(eng, "p2", assassin, [blocker], {"B": 1, "C": 3})
    eng.rules.put_into_graveyard(blocker)
    _end_of_combat(eng)
    assert not _alive(eng, blocker) and _alive(eng, attacker) and _alive(eng, assassin)


# --- Dwarven Sea Clan ------------------------------------------------------------------------------------------


def _clan_board(opponent_island=True):
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1", power=0, toughness=TOUGH)
    clan = _creature(eng, "Dwarven Sea Clan", "p2", SEA_CLAN, power=1, toughness=1)
    if opponent_island:
        _land(eng, "p1")
    return eng, attacker, clan


def test_sea_clan_damages_the_chosen_creature_at_end_of_combat():
    eng, attacker, clan = _clan_board()
    _attack(eng, [attacker])
    _activate(eng, "p2", clan, [attacker])
    assert attacker.damage_marked == 0
    _end_of_combat(eng)
    assert attacker.damage_marked == 2 and not eng.state.delayed_triggers


def test_sea_clan_needs_an_island_under_the_targets_controller():
    eng, attacker, clan = _clan_board(opponent_island=False)
    _land(eng, "p2")  # its own Island does not matter
    _attack(eng, [attacker])
    with pytest.raises(ValueError, match="illegal targets"):
        _activate(eng, "p2", clan, [attacker])
    assert not eng.state.delayed_triggers
    _end_of_combat(eng)
    assert attacker.damage_marked == 0


def test_sea_clan_cannot_be_activated_from_the_end_of_combat_step_on():
    eng, attacker, clan = _clan_board()
    _attack(eng, [attacker])
    _advance_to(eng, "end_combat")
    p2 = eng.state.player_by_id("p2")
    assert not eng.can_activate(p2, clan, clan.activated_abilities[0], targets=[attacker])
    with pytest.raises(ValueError, match="cannot activate"):
        _activate(eng, "p2", clan, [attacker])
    assert not eng.state.delayed_triggers


def test_sea_clan_damage_is_dealt_even_if_the_clan_is_gone():
    # RULE 608.2h: the source's last known information deals the damage.
    eng, attacker, clan = _clan_board()
    _attack(eng, [attacker])
    _activate(eng, "p2", clan, [attacker])
    eng.rules.put_into_graveyard(clan)
    _end_of_combat(eng)
    assert attacker.damage_marked == 2


def test_assassin_destroy_does_not_target_again_so_later_hexproof_is_irrelevant():
    # RULE 603.7c: the delayed ability refers to the object announced earlier; it is not a new targeting.
    eng, attacker, blocker, assassin = _assassin_board()
    _block_only(eng, blocker, attacker)
    _activate(eng, "p2", assassin, [blocker], {"B": 1, "C": 3})
    blocker.card.keywords = [*(blocker.card.keywords or []), "hexproof"]
    eng.recompute_continuous_effects()
    _end_of_combat(eng)
    assert not _alive(eng, blocker)


# --- Winter's Chill --------------------------------------------------------------------------------------------

CHILL = "Winter's Chill"
SNOW_LANDS = 2


def _chill_board(snow_lands=SNOW_LANDS, attackers=2, power=3):
    """p1 attacks with ``attackers`` creatures; p2 holds Winter's Chill with ``snow_lands`` snow Islands."""
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    creatures = [_creature(eng, f"Attacker {i}", "p1", power=power, toughness=TOUGH) for i in range(attackers)]
    for _ in range(snow_lands):
        land = Card(id="Snow Island", name="Snow Island", type_line="Basic Snow Land — Island", is_land=True)
        obj = GameObject(land, owner_id="p2", zone=Zone.BATTLEFIELD)
        obj.controller_id = "p2"
        eng.state.add_to_battlefield(obj)
    chill = GameObject(_named(CHILL), owner_id="p2", zone=Zone.HAND)
    chill.controller_id = "p2"
    p2.hand.append(chill)
    bind_from_catalogue(chill)
    return eng, p1, p2, creatures, chill


def _cast_chill(eng, p2, chill, targets, x):
    p2.mana_pool.add_many({"U": 1, "C": x})
    eng.cast_spell(p2, chill, targets=targets, x=x)
    eng.resolve_until_stable()


def _answer(eng, *answers):
    """Answer the pending payment questions in order (``pay`` or ``decline``) and return the prompts asked."""
    asked = []
    for answer in answers:
        choice = eng.state.pending_choice
        assert choice is not None and choice["kind"] == "pay_cost_then"
        asked.append((choice["player_id"], choice["cost_label"]))
        eng.resolve_pending_choice(answer)
    return asked


def test_winters_chill_is_modeled():
    assert parse_oracle(_named(CHILL)).modeled is True


def test_x_cannot_exceed_the_snow_lands_the_caster_controls():
    eng, p1, p2, creatures, chill = _chill_board()
    _attack(eng, creatures)
    p2.mana_pool.add_many({"U": 1, "C": 6})  # mana is not the limit here
    assert eng.can_cast(p2, chill, SNOW_LANDS) and not eng.can_cast(p2, chill, SNOW_LANDS + 1)


def test_targets_are_the_announced_attackers_only():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    eng, p1, p2, creatures, chill = _chill_board()
    bystander = _creature(eng, "Bystander", "p1", power=1, toughness=TOUGH)
    _attack(eng, creatures)
    spec = TargetSpec(kind="creature", creature_filter={"attacking": True})
    ids = {o["instance_id"] for o in legal_targets(eng.state, "p2", spec, chill)}
    assert {c.instance_id for c in creatures} <= ids and bystander.instance_id not in ids


def test_each_controller_is_asked_and_declining_both_destroys_only_that_creature_at_end_of_combat():
    eng, p1, p2, (kept, doomed), chill = _chill_board()
    _attack(eng, [kept, doomed])
    p1.mana_pool.add_many({"C": 3})
    _cast_chill(eng, p2, chill, [kept, doomed], 2)
    # the attackers' controller decides for each creature in turn: first {2}, then {1}; after paying {2} for the first
    # creature only {1} is left, so the second creature's {2} offer is skipped and {1} is declined
    asked = _answer(eng, "pay", "decline")
    assert asked == [("p1", "{2}"), ("p1", "{1}")]
    assert p1.mana_pool.total() == 1 and eng.state.pending_choice is None
    assert len(eng.state.delayed_triggers) == 1  # only the creature whose controller paid nothing
    assert not kept.prevent_combat_damage_this_combat and not doomed.prevent_combat_damage_this_combat
    _end_of_combat(eng)
    assert _alive(eng, kept) and not _alive(eng, doomed)
    assert not eng.state.delayed_triggers and chill.zone == Zone.GRAVEYARD


def test_a_controller_who_cannot_pay_is_never_asked_and_loses_the_creature():
    eng, p1, p2, creatures, chill = _chill_board(attackers=1)
    _attack(eng, creatures)
    _cast_chill(eng, p2, chill, creatures, 1)
    assert eng.state.pending_choice is None and len(eng.state.delayed_triggers) == 1
    _end_of_combat(eng)
    assert not _alive(eng, creatures[0])


def test_paying_only_one_saves_the_creature_and_prevents_combat_damage_both_ways():
    eng, p1, p2, (attacker,), chill = _chill_board(attackers=1, power=3)
    blocker = _creature(eng, "Blocker", "p2", power=3, toughness=TOUGH)
    _advance_to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [{"attacker": attacker, "defender": {"kind": "player", "id": "p2"}}])
    p1.mana_pool.add_many({"C": 1})
    _cast_chill(eng, p2, chill, [attacker], 1)
    _answer(eng, "pay")  # only {1} is affordable, so the {2} offer is skipped
    assert attacker.prevent_combat_damage_this_combat and not eng.state.delayed_triggers
    _advance_to(eng, "declare_blockers")
    eng.declare_blockers(eng.state.player_by_id("p2"), [{"blocker": blocker, "attacker": attacker}])
    _end_of_combat(eng)
    assert attacker.damage_marked == 0 and blocker.damage_marked == 0  # nothing dealt to or by it
    assert _alive(eng, attacker)


def test_the_prevention_ends_with_the_combat():
    eng, p1, p2, (attacker,), chill = _chill_board(attackers=1)
    _attack(eng, [attacker])
    p1.mana_pool.add_many({"C": 1})
    _cast_chill(eng, p2, chill, [attacker], 1)
    _answer(eng, "pay")
    _end_of_combat(eng)
    _advance_to(eng, "main2")
    assert not attacker.prevent_combat_damage_this_combat


def test_paying_the_larger_cost_does_nothing_at_all():
    eng, p1, p2, (attacker,), chill = _chill_board(attackers=1)
    _attack(eng, [attacker])
    p1.mana_pool.add_many({"C": 2})
    _cast_chill(eng, p2, chill, [attacker], 1)
    _answer(eng, "pay")
    assert not attacker.prevent_combat_damage_this_combat and not eng.state.delayed_triggers
    assert p1.mana_pool.total() == 0


def test_a_creature_that_left_and_returned_before_end_of_combat_is_a_new_object_and_survives():
    # RULE 400.7 / 603.7c: the delayed destroy names the visit that was chosen.
    eng, p1, p2, (attacker,), chill = _chill_board(attackers=1)
    _attack(eng, [attacker])
    _cast_chill(eng, p2, chill, [attacker], 1)
    assert len(eng.state.delayed_triggers) == 1
    eng.rules.blink(attacker)
    _end_of_combat(eng)
    assert _alive(eng, attacker)


def test_winters_chill_parse_shape():
    result = parse_oracle(_named(CHILL))
    effects = [e for s in result.specs for e in s.effects]
    cap = next(e for e in effects if e.type == "x_cap_marker")
    assert cap.params["selector"]["filter"] == {"snow": True, "card_type": "land"}
    choose = next(e for e in effects if e.type == "choose_targets")
    assert choose.params["count_selector"] == "source_x_paid"
    assert choose.params["creature_filter"] == {"attacking": True}


@pytest.mark.parametrize(
    "oracle",
    [
        # the cheaper cost must be the one that earns the prevention
        "Choose X target attacking creatures. For each of those creatures, its controller may pay {1} or {2}. If that "
        "player doesn't, destroy that creature at end of combat. If that player pays only {2}, prevent all combat "
        "damage that would be dealt to and dealt by that creature this combat.",
        # a different consequence is not claimed
        "Choose X target attacking creatures. For each of those creatures, its controller may pay {1} or {2}. If that "
        "player doesn't, exile that creature at end of combat. If that player pays only {1}, prevent all combat "
        "damage that would be dealt to and dealt by that creature this combat.",
    ],
)
def test_per_creature_payment_variants_stay_unclaimed(oracle):
    assert _parse(oracle, types="Instant").modeled is False


# --- the shared "choose target ..." announcement now keeps its qualifiers --------------------------------------


def test_cryptek_announces_an_artifact_creature_and_returns_it_when_it_dies():
    # `choose_target_single` used to drop the creature qualifier of "choose another target artifact creature you
    # control"; the filter now rides on the announcement, so a plain creature is not a legal pick.
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    result = parse_oracle(_named("Cryptek"))
    assert result.modeled
    choose = next(e for s in result.specs for e in s.effects if e.type == "choose_targets")
    assert choose.params["creature_filter"] == {"card_type": "artifact"}
    eng = _engine()
    plain = _creature(eng, "Bear", "p1")
    golem = _creature(eng, "Golem", "p1", types="Artifact Creature — Golem")
    cryptek = _creature(eng, "Cryptek", "p1", "")
    spec = TargetSpec(kind=choose.params["kinds"][0], creature_filter=choose.params["creature_filter"])
    ids = {o["instance_id"] for o in legal_targets(eng.state, "p1", spec, cryptek)}
    assert golem.instance_id in ids and plain.instance_id not in ids
