"""Tests for RULE 601.2c's "Creatures you control gain `<keyword>` and get
+X/+X until end of turn, where X is the number of creatures you control."
template (Craterhoof Behemoth-shaped) — `PumpEffect.amount_from_count_
selector`, a single shared magnitude for the whole selector group computed
live off the board (`continuous.count_selector`), unlike
`per_recipient_controller_counter`'s per-object scaling or `amount_from_
trigger_event`'s firing-event read.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext, PumpEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _bear(name="Bear", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def test_group_pump_count_selector_is_recognized():
    (spec,) = parse_effect_body(
        "creatures you control gain trample and get +x/+x until end of turn, "
        "where x is the number of creatures you control"
    )
    assert spec.type == "pump"
    assert spec.params == {
        "keywords": ["trample"],
        "selector": "creatures_you_control",
        "amount_from_count_selector": "creatures_you_control",
    }


def test_craterhoof_behemoth_is_fully_modeled():
    card = Card(
        id="Craterhoof Behemoth", name="Craterhoof Behemoth",
        type_line="Creature — Beast", is_creature=True, power=5, toughness=5,
        keywords=["Haste"],
        oracle_text="Haste\nWhen this creature enters, creatures you control gain "
                     "trample and get +X/+X until end of turn, where X is the "
                     "number of creatures you control.",
    )
    assert parse_oracle(card).coverage == MODELED


# ---------------------------------------------------------------------------
# Engine: PumpEffect.amount_from_count_selector
# ---------------------------------------------------------------------------


def test_amount_from_count_selector_sizes_the_whole_group_by_one_shared_count():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    source = GameObject(_bear("Source"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(source)
    a = GameObject(_bear("A"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(a)
    b = GameObject(_bear("B"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(b)
    opp = GameObject(_bear("Opp"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(opp)
    ctx = GameContext(eng.state, eng.rules)

    PumpEffect(
        keywords=["trample"], selector="creatures_you_control",
        amount_from_count_selector="creatures_you_control", source=source,
    ).apply(ctx)
    eng.recompute_continuous_effects()

    # 3 creatures under p1's control (source, A, B) → +3/+3 each.
    assert source.power == 5 and source.toughness == 5
    assert a.power == 5 and a.toughness == 5
    assert b.power == 5 and b.toughness == 5
    assert "trample" in a.granted_keywords
    assert opp.power == 2 and opp.toughness == 2  # untouched


def test_craterhoof_behemoth_end_to_end_pumps_the_whole_board():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    a = GameObject(_bear("A"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(a)
    b = GameObject(_bear("B"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(b)

    craterhoof_card = Card(
        id="Craterhoof Behemoth", name="Craterhoof Behemoth",
        type_line="Creature — Beast", is_creature=True, power=5, toughness=5,
        keywords=["Haste"],
        oracle_text="Haste\nWhen this creature enters, creatures you control gain "
                     "trample and get +X/+X until end of turn, where X is the "
                     "number of creatures you control.",
    )
    craterhoof = GameObject(craterhoof_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(craterhoof)
    eng.state.add_to_battlefield(craterhoof)

    from mtg_analyzer.models.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=craterhoof.instance_id,
        object=craterhoof.name, object_types=sorted(craterhoof.type_words),
    ))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    # 3 creatures on p1's board (A, B, Craterhoof itself) → +3/+3 each.
    assert a.power == 5 and a.toughness == 5
    assert b.power == 5 and b.toughness == 5
    assert craterhoof.power == 8 and craterhoof.toughness == 8
    assert "trample" in a.granted_keywords


def test_each_creature_you_control_distributive_group_grant():
    # "Each creature you control gains X until end of turn." is the same
    # group as "creatures you control", just worded per-creature
    # (Avacyn and Griselbrand, Moonveil Dragon) — PAR-29 residue widening.
    (spec,) = parse_effect_body(
        "each creature you control gains indestructible until end of turn"
    )
    assert spec.type == "pump"
    assert spec.params == {
        "keywords": ["indestructible"],
        "selector": "creatures_you_control",
    }
    (spec2,) = parse_effect_body(
        "each creature you control gets +1/+1 until end of turn"
    )
    assert spec2.params["selector"] == "creatures_you_control"
    assert spec2.params["power"] == 1 and spec2.params["toughness"] == 1
