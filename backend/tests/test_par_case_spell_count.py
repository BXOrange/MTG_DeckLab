"""Case solve conditions reuse the instant/sorcery cast-history selector."""
import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import parse_oracle


@pytest.mark.parametrize("number", ["four", "7"])
def test_case_cast_count_solve_condition_parses(number):
    card = Card(id="case", name="Case of Studies", type_line="Enchantment — Case",
                oracle_text=f"To solve — You've cast {number} or more instant and sorcery spells this turn.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    spec = result.specs[0]
    assert spec.trigger["active_if"] == {
        "kind": "control_count", "selector": "instant_and_sorcery_spells_cast_this_turn",
        "min": 4 if number == "four" else 7,
    }


def test_case_does_not_claim_a_different_cast_filter():
    card = Card(id="case", name="Case of Studies", type_line="Enchantment — Case",
                oracle_text="To solve — You've cast four or more creature spells this turn.")
    assert not parse_oracle(card).modeled


def test_parsed_case_counts_real_casts_and_ignores_creatures():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.models.game.events import EventType, GameEvent
    from mtg_analyzer.models.game.game_object import GameObject, Zone

    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.players[0]
    case = GameObject(Card(id="case", name="Case of Studies", type_line="Enchantment — Case",
                           oracle_text="To solve — You've cast four or more instant and sorcery spells this turn."),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(case)
    engine.state.add_to_battlefield(case)

    def cast(creature=False):
        spell = GameObject(Card(id=str(len(p1.graveyard)), name="Student" if creature else "Prayer",
                                type_line="Creature" if creature else "Instant",
                                is_creature=creature, is_instant=not creature,
                                power=1 if creature else None, toughness=1 if creature else None,
                                oracle_text="" if creature else "You gain 1 life."),
                           owner_id="p1", zone=Zone.HAND)
        bind_from_catalogue(spell)
        p1.hand.append(spell)
        engine.cast_spell(p1, spell)
        engine.resolve_until_stable()

    def end_step():
        engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()

    cast(creature=True)
    for _ in range(3):
        cast()
    end_step()
    assert not case.is_solved
    cast()
    end_step()
    assert case.is_solved
