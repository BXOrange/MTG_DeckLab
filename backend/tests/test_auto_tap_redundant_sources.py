"""Auto-tap must discard early taps made redundant by later colour sources."""
import pytest

from test_auto_tap_action import _make_engine, _land
from mtg_analyzer.models.mana.mana_cost import ManaCost


@pytest.mark.parametrize('cost,floating,expected', [
    ('{U}{G}', 0, 2),
    ('{1}{U}{G}', 0, 3),
    ('{U}{G}', 1, 1),
])
def test_auto_tap_leaves_unneeded_earlier_lands_untapped(cost, floating, expected):
    engine = _make_engine()
    engine.begin_turn()
    player = engine.state.active_player
    for name in ['Island', 'Island', 'Island', 'Forest']:
        engine.state.add_to_battlefield(_land(name))
    if floating:
        player.mana_pool.add('U', floating)

    engine.auto_tap_for(player, cost=ManaCost.parse(cost))

    assert sum(obj.tapped for obj in engine.state.battlefield) == expected
    assert player.mana_pool.total() == expected + floating
    assert player.mana_pool.can_pay(ManaCost.parse(cost), life_available=player.life)


def test_cast_multicolour_spell_does_not_leave_redundant_floating_mana():
    from test_auto_tap_action import _bear

    engine = _make_engine([_bear(cost='{U}{G}')], hand=1)
    engine.begin_turn()
    engine.state.current_step = 'main1'
    player = engine.state.active_player
    for name in ['Island', 'Island', 'Island', 'Forest']:
        engine.state.add_to_battlefield(_land(name))

    engine.cast_spell(player, player.hand[0])

    assert sum(obj.tapped for obj in engine.state.battlefield) == 2
    assert player.mana_pool.total() == 0
    assert len(engine.state.stack) == 1
