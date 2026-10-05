"""The Beamtown Bullies: two targets, borrowed creature and delayed exile."""

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.targeting import effects_target_specs, legal_targets
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _game, _card, _end_step
from tests.test_weathered_sentinels import _to


def _position():
    engine = _game(seats=3)
    bullies = _card(engine, "The Beamtown Bullies")
    creature = _card(engine, "Grizzly Bears", zone=Zone.GRAVEYARD)
    _to(engine, "p2", "main1")
    return engine, bullies, creature


def _activate(engine, bullies, creature):
    engine.activate_ability(engine.state.player_by_id("p1"), bullies,
                            targets=[engine.state.player_by_id("p2"), creature])


def test_targets_are_active_opponent_and_own_nonlegendary_graveyard_creature():
    engine, bullies, creature = _position()
    _card(engine, "Henzie \"Toolbox\" Torre", zone=Zone.GRAVEYARD)
    _card(engine, "Grizzly Bears", player="p2", zone=Zone.GRAVEYARD)
    specs = effects_target_specs(bullies.activated_abilities[0].effects)
    assert len(specs) == 2
    assert [o["player_id"] for o in legal_targets(engine.state, "p1", specs[0], source=bullies)] == ["p2"]
    assert [o["instance_id"] for o in legal_targets(engine.state, "p1", specs[1], source=bullies)] == [creature.instance_id]


@pytest.mark.parametrize("invalid", ["inactive", "self", "legendary", "foreign", "battlefield"])
def test_illegal_targets_do_not_pay_tap_cost(invalid):
    engine, bullies, creature = _position()
    opponent = engine.state.player_by_id("p2")
    if invalid in {"inactive", "self"}:
        opponent = engine.state.player_by_id("p3" if invalid == "inactive" else "p1")
    else:
        creature = _card(engine, 'Henzie "Toolbox" Torre' if invalid == "legendary" else "Grizzly Bears",
                         player="p2" if invalid == "foreign" else "p1",
                         zone=Zone.BATTLEFIELD if invalid == "battlefield" else Zone.GRAVEYARD)
    with pytest.raises(ValueError):
        engine.activate_ability(engine.state.player_by_id("p1"), bullies, targets=[opponent, creature])
    assert not bullies.tapped and not engine.state.stack


def test_creature_gets_haste_and_goad_then_is_exiled_at_next_end_step():
    engine, bullies, creature = _position()
    _activate(engine, bullies, creature)
    engine.resolve_until_stable()
    assert bullies.tapped
    assert creature.zone == Zone.BATTLEFIELD
    assert creature.owner_id == "p1" and creature.controller_id == "p2"
    assert combat.has_haste(creature) and creature.goaded_by == {"p1"}
    _to(engine, "p2", "declare_attackers")
    action = next(a for a in engine.legal_actions(engine.state.player_by_id("p2"))
                  if a["type"] == "attack" and a.get("instance_id") == creature.instance_id)
    assert "p3" in {d["id"] for d in action["legal_defenders"]}
    engine.declare_attackers(engine.state.player_by_id("p2"), [
        {"attacker": creature, "defender": engine.state.player_by_id("p3")},
    ])
    _end_step(engine)
    engine.resolve_until_stable()
    assert creature.zone == Zone.EXILE


def test_source_leaving_does_not_change_ability_controller_or_stop_delayed_exile():
    engine, bullies, creature = _position()
    _activate(engine, bullies, creature)
    engine.rules.destroy(bullies)
    engine.resolve_until_stable()
    assert creature.controller_id == "p2" and creature.goaded_by == {"p1"}
    _to(engine, "p2", "declare_attackers")
    engine.declare_attackers(engine.state.player_by_id("p2"), [
        {"attacker": creature, "defender": engine.state.player_by_id("p3")},
    ])
    _end_step(engine)
    engine.resolve_until_stable()
    assert creature.zone == Zone.EXILE


def test_opponent_becoming_hexproof_prevents_return_without_exiling_source():
    engine, bullies, creature = _position()
    _activate(engine, bullies, creature)
    _card(engine, "Shalai, Voice of Plenty", player="p2")
    engine.recompute_continuous_effects()
    engine.resolve_until_stable()
    assert creature.zone == Zone.GRAVEYARD
    _end_step(engine)
    engine.resolve_until_stable()
    assert bullies.zone == Zone.BATTLEFIELD


def test_source_changing_controller_preserves_the_activated_abilitys_controller():
    engine, bullies, creature = _position()
    _activate(engine, bullies, creature)
    bullies.controller_id = "p3"
    engine.resolve_until_stable()
    assert creature.controller_id == "p2" and creature.goaded_by == {"p1"}


@pytest.mark.parametrize("blocked", ["removed_target", "cage", "priest"])
def test_no_creature_entry_does_not_exile_the_bullies(blocked):
    engine, bullies, creature = _position()
    if blocked != "removed_target":
        _card(engine, "Grafdigger's Cage" if blocked == "cage" else "Containment Priest", player="p3")
        engine.recompute_continuous_effects()
    _activate(engine, bullies, creature)
    if blocked == "removed_target":
        engine.rules.exile(creature)
    engine.resolve_until_stable()
    assert creature.zone != Zone.BATTLEFIELD
    _end_step(engine)
    engine.resolve_until_stable()
    assert bullies.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("return_again", [False, True])
def test_delayed_exile_does_not_follow_a_creature_that_left_battlefield(return_again):
    engine, bullies, creature = _position()
    _activate(engine, bullies, creature)
    engine.resolve_until_stable()
    engine.rules.destroy(creature)
    if return_again:
        engine.rules.return_from_graveyard(creature, "battlefield")
    _end_step(engine)
    engine.resolve_until_stable()
    assert creature.zone == (Zone.BATTLEFIELD if return_again else Zone.GRAVEYARD)


def test_catalogue_specs_are_fresh():
    engine, bullies, _ = _position()
    first = specs_for(bullies.card)
    first[0].effects[2].params["effects"][0]["params"]["target_kind"] = "player"
    assert specs_for(bullies.card)[0].effects[2].params["effects"][0]["params"]["target_kind"] is None
    assert len(bullies.activated_abilities) == 1
    assert combat.has_vigilance(bullies) and combat.has_haste(bullies)
