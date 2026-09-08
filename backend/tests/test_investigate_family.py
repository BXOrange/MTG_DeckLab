"""RULE 701.19a's "Investigate" keyword action — a Clue-token-creation
alias onto the already-existing `create_token`/`_NAMED_TOKEN_WORDS["clue"]`
shape (Shadows over Innistrad-introduced, reused across many later sets).

Reference: mtg_analyzer/parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_bare_investigate_parses():
    assert match_clause("investigate") == [
        EffectSpec("create_token", {"count": 1, "token_name": "Clue"})
    ]


def test_investigate_twice_parses():
    assert match_clause("investigate twice") == [
        EffectSpec("create_token", {"count": 2, "token_name": "Clue"})
    ]


def test_investigate_n_times_parses():
    assert match_clause("investigate 3 times") == [
        EffectSpec("create_token", {"count": 3, "token_name": "Clue"})
    ]


def test_investigate_x_times_stays_unclaimed():
    # A dynamic count ("investigate x times, where x is …") — `COUNT` only
    # ever resolves a literal int, fail-closed rather than guessing.
    assert match_clause("investigate x times") is None


def test_fugitive_doctor_first_line_is_modeled():
    card = Card(
        id="The Fugitive Doctor", name="The Fugitive Doctor",
        type_line="Legendary Creature — Time Lord Doctor",
        is_creature=True, power=1, toughness=3,
        oracle_text="When The Fugitive Doctor enters, investigate.",
    )
    result = parse_oracle(card)
    assert result.modeled
    spec = result.effect_specs[0]
    assert spec.effects[0] == EffectSpec("create_token", {"count": 1, "token_name": "Clue"})


def test_investigate_executes_and_creates_a_clue():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    p1 = state.player_by_id("p1")
    card = Card(
        id="Test Sleuth", name="Test Sleuth", type_line="Creature — Human Detective",
        is_creature=True, power=1, toughness=1,
        oracle_text="When this creature enters, investigate.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)

    from mtg_analyzer.models.events import EventType, GameEvent
    state.add_to_battlefield(obj)
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
            controller_id="p1", object_types=sorted(obj.type_words),
        )
    )
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    clues = [o for o in state.battlefield if o.name == "Clue" and o.controller_id == "p1"]
    assert len(clues) == 1
