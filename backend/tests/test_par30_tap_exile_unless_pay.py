"""PAR-30 — "tap/exile ~ unless you pay `<cost>`" (PARSER_VERSION 159).

The tap/exile consequence siblings of `sacrifice_unless_pay` /
`destroy_unless_pay` (RULE 118.3 "unless" payment). Modeled via
`pay_cost_then` with an empty pay-branch and the tap/exile in
`else_effects` — Carnophage/Sangrophage/Heavyweight Demolisher ("tap ~
unless you pay `<mana/life/energy>`"), Demonlord of Ashmouth ("exile it
unless you sacrifice another creature").

Also: `_UNLESS_COST` gained "discard N cards" (Avatar of Discord).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _fire_upkeep(eng):
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()


# -- parse -------------------------------------------------------------------


@pytest.mark.parametrize("body,cost,else_type", [
    ("tap ~ unless you pay {3}", "pay {3}", "tap"),
    ("tap ~ unless you pay 2 life", "pay 2 life", "tap"),
    ("tap ~ unless you sacrifice another creature", "sacrifice another creature", "tap"),
    ("exile it unless you sacrifice another creature", "sacrifice another creature", "exile"),
    ("exile ~ unless you pay 2 life", "pay 2 life", "exile"),
])
def test_tap_exile_unless_pay_parses(body, cost, else_type):
    (spec,) = parse_effect_body(body)
    assert spec.type == "pay_cost_then"
    assert spec.params["cost"] == cost
    assert spec.params["effects"] == []
    assert spec.params["else_effects"] == [
        {"type": else_type, "params": {"target_kind": None}}
    ]


def test_plain_tap_self_and_exile_self_unaffected():
    # regression: the new handlers sit before tap_self/exile_self, but their
    # regex requires "unless you …" so a bare self clause still routes there.
    assert parse_effect_body("tap ~")[0].type == "tap"
    assert parse_effect_body("exile ~")[0].type == "exile"


def test_discard_n_cards_cost_now_claimed():
    (spec,) = parse_effect_body("sacrifice it unless you discard 2 cards")
    assert spec.type == "sacrifice_unless_pay"
    assert spec.params == {"cost": "discard 2 cards"}
    # a typed discard is still fail-closed (parse_activation_cost → free)
    assert parse_effect_body("sacrifice it unless you discard a creature card") is None


def test_real_cards_modeled():
    for name, tl, txt in [
        ("Carnophage", "Creature — Zombie",
         "At the beginning of your upkeep, tap Carnophage unless you pay 1 life."),
        ("Heavyweight Demolisher", "Creature — Construct",
         "At the beginning of your upkeep, tap Heavyweight Demolisher unless "
         "you pay {3}."),
        ("Demonlord of Ashmouth", "Creature — Demon",
         "When Demonlord of Ashmouth enters, exile it unless you sacrifice "
         "another creature."),
        ("Avatar of Discord", "Creature — Avatar",
         "Flying\nWhen Avatar of Discord enters, sacrifice it unless you "
         "discard 2 cards."),
    ]:
        c = Card(id=name[:6], name=name, type_line=tl, is_creature=True,
                 power=2, toughness=2, oracle_text=txt)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# -- engine ---------------------------------------------------------------------


def _carnophage():
    return Card(id="carno", name="Carnophage", type_line="Creature — Zombie",
                is_creature=True, power=2, toughness=2, mana_cost_string="{B}",
                oracle_text="At the beginning of your upkeep, tap Carnophage "
                            "unless you pay 1 life.")


def test_declining_taps_the_source():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    carn = _bf(eng.state, _carnophage())
    assert not carn.tapped

    _fire_upkeep(eng)
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("decline")

    assert carn.tapped is True
    assert p1.life == 20  # declining costs nothing


def test_paying_the_life_keeps_it_untapped():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    carn = _bf(eng.state, _carnophage())

    _fire_upkeep(eng)
    eng.resolve_pending_choice("pay")

    assert carn.tapped is False
    assert p1.life == 19


def test_unaffordable_taps_outright_without_a_choice():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p1.life = 0  # can't pay 1 life (SBA would kill p1, but the tap resolves first here)
    carn = _bf(eng.state, _carnophage())

    _fire_upkeep(eng)
    assert eng.state.pending_choice is None
    assert carn.tapped is True


def test_exile_unless_sacrifice_declined_exiles_the_source():
    eng = _engine()
    state = eng.state
    dem = Card(id="dem", name="Demonlord of Ashmouth", type_line="Creature — Demon",
               is_creature=True, power=4, toughness=4,
               oracle_text="When Demonlord of Ashmouth enters, exile it unless "
                           "you sacrifice another creature.")
    obj = GameObject(dem, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    # fire the ETB trigger
    state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
                               controller_id="p1"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    # (the choice opens even with no *other* creature — "another" isn't
    # honoured by the cost checker, same as sacrifice_unless_pay). Decline:
    assert state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("decline")
    assert obj not in state.battlefield
    assert any(o.instance_id == obj.instance_id for o in state.player_by_id("p1").exile)
