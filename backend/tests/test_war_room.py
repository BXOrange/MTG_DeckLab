"""War Room — "{3}, {T}, Pay life equal to the number of colors in your
commanders' color identity: Draw a card." (hand-authored; amount resolved at
payment via `costs.PAY_LIFE_COMMANDER_COLORS`, RULE 903.4 / 119.4 / 602.2).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.costs import PAY_LIFE_COMMANDER_COLORS
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_abilities_for
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)

FOUR_COLOR_COMMANDER = "Atraxa, Praetors' Voice"  # W/U/B/G
MONO_COLOR_COMMANDER = "Isamaru, Hound of Konda"  # W
COLORLESS_COMMANDER = "Sol Ring"  # stand-in: empty identity


def _card(name: str):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _setup(commander: str):
    filler = _card("Grizzly Bears")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 10), ("p2", "Bob", [filler] * 10)],
        starting_hand=0,
    )
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    p1 = eng.state.player_by_id("p1")
    cmdr = GameObject(_card(commander), owner_id="p1", zone=Zone.COMMAND)
    cmdr.is_commander = True
    p1.zones.setdefault("command", []).append(cmdr)
    room = GameObject(_card("War Room"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(room)
    eng.state.add_to_battlefield(room)
    return eng, p1, room


def _activate(eng, p1, room):
    p1.mana_pool.add("C", 3)
    eng.activate_ability(p1, room, 0)
    eng.resolve_until_stable()


def test_war_room_binds_cost_sentinel_and_mana_ability():
    _eng, _p1, room = _setup(FOUR_COLOR_COMMANDER)
    assert [a.cost.pay_life for a in room.activated_abilities] == [PAY_LIFE_COMMANDER_COLORS]
    assert room.activated_abilities[0].cost.taps_self
    assert len(mana_abilities_for(room)) == 1  # {T}: Add {C}


@pytest.mark.parametrize(
    ("commander", "life_paid"),
    [(FOUR_COLOR_COMMANDER, 4), (MONO_COLOR_COMMANDER, 1), (COLORLESS_COMMANDER, 0)],
)
def test_war_room_pays_one_life_per_commander_color_and_draws(commander, life_paid):
    eng, p1, room = _setup(commander)
    life, hand = p1.life, len(p1.hand)
    _activate(eng, p1, room)
    assert p1.life == life - life_paid
    assert len(p1.hand) == hand + 1
    assert room.tapped


def test_war_room_is_unactivatable_without_enough_life():
    eng, p1, room = _setup(FOUR_COLOR_COMMANDER)
    p1.life = 3
    p1.mana_pool.add("C", 3)
    assert not eng._can_pay_activation_cost(p1, room, room.activated_abilities[0].cost, x=0)
    p1.life = 4
    assert eng._can_pay_activation_cost(p1, room, room.activated_abilities[0].cost, x=0)
