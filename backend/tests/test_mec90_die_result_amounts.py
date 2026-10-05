"""MEC-90: a die result is a resolve-time amount across ordinary effects."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effect_amounts import amount_of
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_real_result_amount_cards_parse():
    for name in (
        "Adorable Kitten", "Ancient Bronze Dragon", "Ancient Copper Dragon",
        "Ancient Gold Dragon", "Ancient Silver Dragon", "Ancient Brass Dragon",
    ):
        card = _db().get_card(name)
        assert card is not None
        result = parse_oracle(card)
        assert result.coverage != UNMODELED, (name, result.unclaimed)


def test_roll_then_when_you_do_defers_targets_until_after_the_roll():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    source = GameObject(
        Card(id="bronze", name="Bronze", type_line="Creature — Dragon", is_creature=True,
             power=4, toughness=4),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    source.controller_id = "p1"
    state.add_to_battlefield(source)
    target = GameObject(
        Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    target.controller_id = "p1"
    state.add_to_battlefield(target)
    eng.rules.roll_die = lambda *_args, **_kwargs: [7]

    specs = parse_oracle(_db().get_card("Ancient Bronze Dragon")).specs
    trigger = next(spec for spec in specs if spec.ability_kind == "triggered")
    _apply_effects_partitioned(build_effects(trigger.effects, source), eng.rules.context, None, None, source=source)

    # The outer ability only rolls. Its reflexive trigger is what asks for a target.
    assert state.pending_choice is None
    eng.resolve_until_stable()
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "trigger_target_multi"


def test_die_result_amount_survives_into_the_reflexive_trigger_context():
    eng = GameEngine.new_game(
        [("p1", "Alice", [])], starting_life=20, starting_hand=0
    )
    context = eng.rules.context
    context.trigger_event = GameEvent(EventType.DICE_ROLLED, die_result=7)
    assert amount_of({"kind": "die_result"}, context, None, None) == 7
