"""PAR-120: intervening counter conditions use the departing object's snapshot."""

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle


def test_angelic_sleuth_uses_last_known_counters_on_departing_other_permanent():
    card = Card(id="angelic-sleuth", name="Angelic Sleuth",
                type_line="Creature — Angel Advisor", is_creature=True,
                oracle_text=("Flying\nWhenever another permanent you control leaves the battlefield, "
                             "if it had counters on it, investigate."))
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    trigger = next(ability.trigger for ability in parsed.specs if ability.ability_kind == "triggered")
    assert trigger["event_counter_gate"] == {"min": 1}

    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(source)
    bind_from_catalogue(source)

    plain = GameObject(Card(id="plain", name="Plain", type_line="Creature", is_creature=True),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(plain)
    engine.rules.put_into_graveyard(plain)
    assert engine.rules.put_triggers_on_stack() == 0

    marked = GameObject(Card(id="marked", name="Marked", type_line="Creature", is_creature=True),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    marked.counters["+1/+1"] = 1
    state.add_to_battlefield(marked)
    engine.rules.put_into_graveyard(marked)
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_top_of_stack()
    assert any(obj.name == "Clue" for obj in state.battlefield)


def test_counter_gate_normalizes_threshold_and_absence():
    for phrase, expected in (
        ("one or more counters", {"min": 1}),
        ("no time counters", {"kind": "time", "max": 0}),
        ("a +1/+1 counter", {"kind": "+1/+1", "min": 1}),
    ):
        card = Card(id=f"gate-{phrase}", name="Gate", type_line="Creature", is_creature=True,
                    oracle_text=f"When this creature dies, if it had {phrase} on it, draw a card.")
        parsed = parse_oracle(card)
        assert parsed.modeled, (phrase, parsed.unclaimed)
        trigger = next(ability.trigger for ability in parsed.specs if ability.ability_kind == "triggered")
        assert trigger["event_counter_gate"] == expected


def test_iron_apprentice_passes_every_counter_kind_from_death_snapshot():
    card = Card(id="iron-apprentice", name="Iron Apprentice",
                type_line="Artifact Creature — Construct", is_creature=True,
                oracle_text=("This creature enters with a +1/+1 counter on it.\n"
                             "When this creature dies, if it had counters on it, "
                             "put those counters on target creature you control."))
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    state = engine.state
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    target = GameObject(Card(id="target", name="Target", type_line="Creature", is_creature=True),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(source)
    state.add_to_battlefield(target)
    bind_from_catalogue(source)
    source.counters["+1/+1"] = 2
    source.counters["shield"] = 1
    engine.rules.put_into_graveyard(source)
    assert engine.rules.put_triggers_on_stack() == 1
    choice = state.pending_choice
    assert choice["kind"] == "trigger_target"
    engine.rules.resolve_choice(str(target.instance_id))
    engine.rules.resolve_top_of_stack()
    assert target.counters["+1/+1"] == 2
    assert target.counters["shield"] == 1
