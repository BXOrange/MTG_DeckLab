"""ENG-48 — "you may pay {X}. If/When you do, `<X effect>`." announces X.

`RulesEngine._request_pay_cost_then` used to offer a single "pay" button for a
cost with {X} in it, pay X as 0 and leave the branch's ``"x"`` sentinel for
the effect to read off the source's `x_paid` (0) — so Vigil for the Lost
gained 0 life, Squealing Devil pumped +0/+0, and so on. The choice now offers
one option per affordable X (RULE 107.3a: the payer announces X as part of
paying), charges that X, and binds it into whichever branch runs.

Reference: mtg_analyzer/game/rules/misc_mixin.py (`_request_pay_cost_then`,
`_resume_pay_cost_then`, `_max_payable_x`), RULE 107.3a/118.3/603.11.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


START_LIFE = 0


def _card(name: str):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def two_player_engine():
    filler = _card("Grizzly Bears")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 10), ("p2", "Bob", [filler] * 10)],
        starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    global START_LIFE
    START_LIFE = p1.life
    return eng, p1


def battlefield(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def fire_etb(eng, obj):
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id=obj.controller_id, object_types=["creature"],
    ))
    eng.rules.put_triggers_on_stack()
    # Squealing Devil's second ETB ("sacrifice it unless {B} was spent")
    # shares the window — resolve until the payment is offered.
    while eng.state.stack and eng.state.pending_choice is None:
        eng.rules.resolve_top_of_stack()


def x_options(choice):
    return [o["x"] for o in choice["options"] if "x" in o]


@pytest.mark.parametrize("name", [
    "Decree of Justice", "Flameblast Dragon", "Squealing Devil",
    "Taj-Nar Swordsmith", "Vigil for the Lost", "Wildborn Preserver", "Hero of Leina Tower",
])
def test_pay_x_cards_are_modeled(name):
    assert parse_oracle(_card(name)).coverage == "MODELED"


def test_offer_lists_every_affordable_x_largest_first():
    eng, p1 = two_player_engine()
    devil = battlefield(eng, "Squealing Devil")
    bear = battlefield(eng, "Grizzly Bears")
    p1.mana_pool.add("R", 3)

    fire_etb(eng, devil)
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.resolve_pending_choice(bear.instance_id)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice["kind"] == "pay_cost_then"
    assert x_options(choice) == [3, 2, 1, 0]
    assert choice["options"][-1]["id"] == "decline"


def test_squealing_devil_pumps_its_target_by_the_announced_x():
    eng, p1 = two_player_engine()
    devil = battlefield(eng, "Squealing Devil")
    bear = battlefield(eng, "Grizzly Bears")
    p1.mana_pool.add("R", 3)

    fire_etb(eng, devil)
    # "If you do" targets with the original ETB trigger, before paying X.
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.resolve_pending_choice(bear.instance_id)
    eng.resolve_until_stable()
    eng.resolve_pending_choice("pay_x:2")
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert p1.mana_pool.total() == 1  # X = 2 charged, not 0 and not all 3
    assert bear.power == 4


def test_vigil_for_the_lost_gains_x_life():
    eng, p1 = two_player_engine()
    vigil = battlefield(eng, "Vigil for the Lost")
    bear = battlefield(eng, "Grizzly Bears")
    p1.mana_pool.add("C", 4)

    eng.rules.destroy(bear)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    assert x_options(eng.state.pending_choice)[0] == 4
    eng.resolve_pending_choice("pay_x:3")

    assert p1.life == START_LIFE + 3
    assert p1.mana_pool.total() == 1
    assert vigil.zone == Zone.BATTLEFIELD


def test_bare_pay_answer_means_the_largest_x():
    eng, p1 = two_player_engine()
    battlefield(eng, "Vigil for the Lost")
    bear = battlefield(eng, "Grizzly Bears")
    p1.mana_pool.add("C", 2)

    eng.rules.destroy(bear)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_pending_choice("pay")

    assert p1.life == START_LIFE + 2
    assert p1.mana_pool.total() == 0


def test_declining_charges_nothing():
    eng, p1 = two_player_engine()
    battlefield(eng, "Vigil for the Lost")
    bear = battlefield(eng, "Grizzly Bears")
    p1.mana_pool.add("C", 2)

    eng.rules.destroy(bear)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_pending_choice("decline")

    assert p1.life == START_LIFE
    assert p1.mana_pool.total() == 2


def test_an_x_beyond_the_offer_is_treated_as_declining():
    eng, p1 = two_player_engine()
    battlefield(eng, "Vigil for the Lost")
    bear = battlefield(eng, "Grizzly Bears")
    p1.mana_pool.add("C", 2)

    eng.rules.destroy(bear)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_pending_choice("pay_x:9")

    assert p1.life == START_LIFE
    assert p1.mana_pool.total() == 2


def test_colored_part_of_the_cost_still_gates_the_offer():
    """Flameblast Dragon's {X}{R}: colourless mana alone can't pay it."""
    eng, p1 = two_player_engine()
    dragon = battlefield(eng, "Flameblast Dragon")
    p1.mana_pool.add("C", 5)

    eng.state.fire_event(GameEvent(
        EventType.ATTACKS, instance_id=dragon.instance_id, controller_id="p1",
    ))
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.resolve_pending_choice("p2")
    eng.rules.resolve_top_of_stack()

    assert eng.state.pending_choice is None
    assert p1.mana_pool.total() == 5


def test_wildborn_preserver_puts_x_counters_on_itself():
    eng, p1 = two_player_engine()
    preserver = battlefield(eng, "Wildborn Preserver")
    bear = battlefield(eng, "Grizzly Bears")
    p1.mana_pool.add("G", 3)

    fire_etb(eng, bear)
    eng.resolve_pending_choice("pay_x:3")
    eng.rules.put_triggers_on_stack()
    if eng.state.stack:
        eng.rules.resolve_top_of_stack()

    assert preserver.counters.get("+1/+1", 0) == 3


def test_taj_nar_search_is_capped_at_the_announced_x():
    """The X lands one level deep, in the search's own criteria dict."""
    eng, p1 = two_player_engine()
    for name in ("Bonesplitter", "Loxodon Warhammer"):
        p1.library.append(GameObject(_card(name), owner_id="p1", zone=Zone.LIBRARY))
    smith = battlefield(eng, "Taj-Nar Swordsmith")
    p1.mana_pool.add("C", 3)

    fire_etb(eng, smith)
    eng.resolve_pending_choice("pay_x:1")

    offered = [o.get("label") for o in eng.state.pending_choice["options"] if o["id"] != "decline"]
    assert offered == ["Bonesplitter"]
