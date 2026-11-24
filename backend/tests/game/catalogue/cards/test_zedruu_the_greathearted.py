"""Zedruu counts owned permanents under opposing control, then gains and draws the same X."""
import pytest

from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, game, RICH


def board():
    engine = game(players=3, library=40)
    return engine, card(engine, 'Zedruu the Greathearted')


def owned(engine, name='Grizzly Bears', owner='p1', controller='p2', zone=Zone.BATTLEFIELD):
    obj = card(engine, name, player=owner, zone=zone)
    obj.controller_id = controller
    return obj


def trigger(engine, player='p1'):
    engine.state.active_player_index = next(i for i, p in enumerate(engine.state.players) if p.id == player)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', player_id=player))
    engine.rules.put_triggers_on_stack()


def donate(engine, source, obj, recipient='p2', resolve=True):
    player = engine.state.player_by_id(source.controller_id)
    player.mana_pool.add_many(RICH)
    opponent = engine.state.player_by_id(recipient)
    engine.activate_ability(player, source, 0, targets=[opponent, obj], target_groups=[[opponent], [obj]])
    if resolve:
        engine.resolve_until_stable()


def test_fresh_specs_bind_both_abilities():
    engine, source = board()
    a, b = specs_for(source.card), specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.triggered_abilities) == len(source.activated_abilities) == 1


def test_real_cast_binds_upkeep_and_donation():
    engine = game(library=40); source = card(engine, 'Zedruu the Greathearted', zone=Zone.HAND)
    cast(engine, source)
    gift = card(engine, 'Sol Ring'); donate(engine, source, gift)
    assert gift.controller_id == 'p2' and gift.owner_id == 'p1'


def test_zero_owned_permanents_under_opponents_gains_and_draws_zero():
    engine, source = board(); player = engine.state.players[0]
    before = len(player.hand); trigger(engine); engine.resolve_until_stable()
    assert player.life == 20 and len(player.hand) == before


def test_counts_all_permanent_types_across_multiple_opponents():
    engine, source = board()
    owned(engine); owned(engine, 'Sol Ring', controller='p3'); owned(engine, 'Forest')
    player = engine.state.players[0]; trigger(engine); engine.resolve_until_stable()
    assert player.life == 23 and len(player.hand) == 3


def test_excludes_your_control_and_foreign_ownership():
    engine, source = board(); owned(engine)
    owned(engine, controller='p1')
    owned(engine, owner='p2', controller='p1')
    owned(engine, owner='p2', controller='p3')
    trigger(engine); engine.resolve_until_stable()
    assert engine.state.players[0].life == 21 and len(engine.state.players[0].hand) == 1


@pytest.mark.parametrize('zone', [Zone.HAND, Zone.GRAVEYARD, Zone.EXILE, Zone.LIBRARY])
def test_counts_only_battlefield_permanents(zone):
    engine, source = board(); owned(engine, zone=zone)
    before = len(engine.state.players[0].hand)
    trigger(engine); engine.resolve_until_stable()
    assert engine.state.players[0].life == 20 and len(engine.state.players[0].hand) == before


def test_opponents_upkeep_does_not_trigger():
    engine, source = board(); owned(engine)
    trigger(engine, 'p2'); engine.resolve_until_stable()
    assert engine.state.players[0].life == 20 and not engine.state.players[0].hand


def test_count_is_measured_at_resolution():
    engine, source = board(); gift = owned(engine)
    trigger(engine); gift.controller_id = 'p1'
    owned(engine, 'Sol Ring'); owned(engine, 'Forest', controller='p3')
    engine.resolve_until_stable()
    assert engine.state.players[0].life == 22 and len(engine.state.players[0].hand) == 2


def test_source_control_change_keeps_firing_controller_and_counts_source_itself():
    engine, source = board(); owned(engine)
    trigger(engine); donate(engine, source, source, resolve=False)
    engine.rules.resolve_top_of_stack()
    assert source.controller_id == 'p2'
    engine.resolve_until_stable()
    assert engine.state.players[0].life == 22 and len(engine.state.players[0].hand) == 2
    assert engine.state.players[1].life == 20 and not engine.state.players[1].hand


def test_departed_source_still_gains_and_draws_for_original_controller():
    engine, source = board(); owned(engine)
    trigger(engine); engine.rules.exile(source); engine.resolve_until_stable()
    assert engine.state.players[0].life == 21 and len(engine.state.players[0].hand) == 1


def test_stolen_zedruu_uses_new_controllers_owned_permanents():
    engine, source = board(); source.controller_id = 'p2'
    owned(engine, owner='p2', controller='p3')
    owned(engine, owner='p1', controller='p3')
    trigger(engine, 'p2'); engine.resolve_until_stable()
    assert engine.state.players[1].life == 21 and len(engine.state.players[1].hand) == 1
    assert engine.state.players[0].life == 20


def test_donation_has_both_real_target_requirements():
    from mtg_analyzer.game.targeting import ability_target_specs

    engine, source = board(); ability = source.activated_abilities[0]
    assert [spec.kind for spec in ability_target_specs(ability)] == ['opponent', 'permanent_you_control']
    gift = card(engine, 'Sol Ring'); donate(engine, source, gift, 'p3')
    assert gift.controller_id == 'p3' and gift.owner_id == 'p1'
    assert source.controller_id == 'p1'


def test_donation_does_not_retake_a_permanent_lost_before_resolution():
    engine, source = board(); gift = card(engine, 'Sol Ring')
    donate(engine, source, gift, 'p2', resolve=False)
    gift.controller_id = 'p3'; engine.resolve_until_stable()
    assert gift.controller_id == 'p3'


def test_countered_upkeep_does_nothing():
    engine, source = board(); owned(engine); trigger(engine)
    engine.rules.counter_ability(engine.state.stack[-1]); engine.resolve_until_stable()
    assert engine.state.players[0].life == 20 and not engine.state.players[0].hand


def test_pending_upkeep_survives_clone():
    engine, source = board(); owned(engine); trigger(engine)
    restored = GameEngine(engine.state.clone()); restored.resolve_until_stable()
    assert restored.state.players[0].life == 21 and len(restored.state.players[0].hand) == 1
    assert engine.state.players[0].life == 20


def test_owned_token_counts_after_real_donation():
    engine, source = board(); template = card(engine, 'Grizzly Bears')
    token = engine.rules.copy_permanent(controller_id='p1', source=template)[0]
    donate(engine, source, token, 'p3')
    assert token.owner_id == 'p1' and token.controller_id == 'p3'
    trigger(engine); engine.resolve_until_stable()
    assert engine.state.players[0].life == 21 and len(engine.state.players[0].hand) == 1


def test_foreign_owned_token_does_not_count():
    engine, source = board(); template = card(engine, 'Grizzly Bears', player='p2')
    token = engine.rules.copy_permanent(controller_id='p2', source=template)[0]
    token.controller_id = 'p3'
    trigger(engine); engine.resolve_until_stable()
    assert engine.state.players[0].life == 20 and not engine.state.players[0].hand


def test_donation_requires_all_three_printed_mana_colors():
    engine, source = board(); gift = card(engine, 'Sol Ring')
    player = engine.state.players[0]; player.mana_pool.add_many({'U': 2, 'R': 2, 'C': 10})
    opponent = engine.state.players[1]
    with pytest.raises(ValueError):
        engine.activate_ability(player, source, 0, targets=[opponent, gift], target_groups=[[opponent], [gift]])
    assert gift.controller_id == 'p1' and not engine.state.stack
