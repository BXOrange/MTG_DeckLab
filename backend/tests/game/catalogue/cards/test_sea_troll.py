"""Sea Troll's activation uses the colors at block declaration time."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import filler
from tests.support.star_trek import advance_to, game, on_battlefield


def _blocked(attacking=True, color="U"):
    engine, p1, p2 = game(via_steps=True)
    troll_player, other_player = (p1, p2) if attacking else (p2, p1)
    troll = on_battlefield(engine, troll_player.id, "Sea Troll")
    other = filler(engine, "Other", player=other_player.id, power=2, toughness=4,
                   mana_cost_string="{" + color + "}")
    attacker, blocker = (troll, other) if attacking else (other, troll)
    advance_to(engine, "declare_attackers")
    engine.declare_attackers(p1, [{"attacker": attacker, "defender": p2}])
    advance_to(engine, "declare_blockers")
    engine.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
    troll_player.mana_pool.add("U", 1)
    return engine, troll_player, troll, other


@pytest.mark.parametrize("attacking", [True, False])
def test_can_regenerate_after_blocking_or_being_blocked_by_blue(attacking):
    engine, player, troll, other = _blocked(attacking)
    a, b = specs_for(troll.card), specs_for(troll.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    engine.activate_ability(player, troll)
    engine.resolve_until_stable()
    engine.rules.destroy(troll)
    assert troll.zone == Zone.BATTLEFIELD and troll.tapped
    assert player.mana_pool.total() == 0


@pytest.mark.parametrize("attacking", [True, False])
def test_red_creature_does_not_enable_activation(attacking):
    engine, player, troll, other = _blocked(attacking, "R")
    with pytest.raises(ValueError):
        engine.activate_ability(player, troll)
    assert player.mana_pool.total() == 1


@pytest.mark.parametrize("before,after,legal", [("U", "R", True), ("R", "U", False)])
def test_uses_historical_color_instead_of_creatures_current_color(before, after, legal):
    engine, player, troll, other = _blocked(color=before)
    other.card.mana_cost_string = "{" + after + "}"
    engine.recompute_continuous_effects()
    if legal:
        engine.activate_ability(player, troll)
        engine.resolve_until_stable()
        engine.rules.destroy(troll)
        assert troll.zone == Zone.BATTLEFIELD
    else:
        with pytest.raises(ValueError):
            engine.activate_ability(player, troll)


def test_departure_of_blue_blocker_does_not_erase_history_and_clone_keeps_it():
    engine, player, troll, other = _blocked()
    engine.rules.exile(other)
    clone = GameEngine(engine.state.clone())
    cloned_troll = clone.state.find_object(troll.instance_id)
    clone.activate_ability(clone.state.player_by_id(player.id), cloned_troll)
    clone.resolve_until_stable()
    clone.rules.destroy(cloned_troll)
    assert cloned_troll.zone == Zone.BATTLEFIELD
    assert player.mana_pool.total() == 1


def test_history_does_not_apply_to_a_new_zone_visit_or_a_later_turn():
    engine, player, troll, other = _blocked()
    engine.rules.exile(troll)
    engine.rules.return_from_graveyard(troll, "battlefield")
    with pytest.raises(ValueError):
        engine.activate_ability(player, troll)
    engine2, player2, troll2, other2 = _blocked()
    engine2.state.internal_turn.number += 1
    with pytest.raises(ValueError):
        engine2.activate_ability(player2, troll2)
