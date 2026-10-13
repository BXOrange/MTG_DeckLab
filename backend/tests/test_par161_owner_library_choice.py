"""PAR-161 -- "<Target>'s owner puts it on their choice of the top or bottom of their library." (RULE 401.4).

Parser side: the "the owner of target X" / "target X's owner" forms bind to `owner_puts_on_top_or_bottom`.  Engine side: the
*owner* (not the caster) answers a `library_position` choice, and the card lands on the chosen end of that owner's library.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from tests.support.deck_batch import cast, filler, game, stack_library

OWNER_FIRST = "Target creature's owner puts it on their choice of the top or bottom of their library."
OWNER_OF = "The owner of target nonland permanent puts it on their choice of the top or bottom of their library."
OWNER_OF_SPELL = "The owner of target spell or nonland permanent puts it on their choice of the top or bottom of their library."
WITH_SCRY = OWNER_OF + " Scry 2."


def _spell_card(text):
    return Card(id="Src", name="Src", type_line="Instant", is_instant=True, oracle_text=text)


@pytest.mark.parametrize("text", [OWNER_FIRST, OWNER_OF, OWNER_OF_SPELL, WITH_SCRY])
def test_clause_is_modeled(text):
    assert parse_oracle(_spell_card(text)).coverage == MODELED


@pytest.mark.parametrize("text", [
    "Target attacking creature's owner puts it on their choice of the top or bottom of their library.",
    "Target creature or spacecraft's owner puts it on their choice of the top or bottom of their library.",
])
def test_unresolvable_target_stays_unclaimed(text):
    assert parse_oracle(_spell_card(text)).coverage != MODELED


def _board(text):
    engine = game()
    spell = filler(engine, "Setback", type_line="Instant", player="p1", zone=Zone.HAND, oracle_text=text)
    victim = filler(engine, "Victim", power=2, toughness=2, player="p2")
    return engine, spell, victim


@pytest.mark.parametrize("answer_id, expect_top", [("top", True), ("bottom", False)])
def test_opponent_owner_chooses_the_end(answer_id, expect_top):
    engine, spell, victim = _board(OWNER_FIRST)
    cast(engine, spell, targets=[victim])
    choice = engine.state.pending_choice
    assert choice["kind"] == "library_position" and choice["player_id"] == "p2"
    engine.resolve_pending_choice(answer_id)
    library = engine.state.player_by_id("p2").library
    assert victim.zone == Zone.LIBRARY
    assert (library[-1] is victim) == expect_top and (library[0] is victim) == (not expect_top)
    assert engine.state.pending_choice is None


def test_own_permanent_is_chosen_by_its_owner_the_caster():
    engine, spell, _ = _board(OWNER_FIRST)
    mine = filler(engine, "Mine", power=1, toughness=1, player="p1")
    cast(engine, spell, targets=[mine])
    assert engine.state.pending_choice["player_id"] == "p1"
    engine.resolve_pending_choice("bottom")
    assert engine.state.player_by_id("p1").library[0] is mine


def test_stolen_permanent_goes_to_its_owner_not_its_controller():
    engine, spell, victim = _board(OWNER_FIRST)
    victim.owner_id, victim.controller_id = "p1", "p2"  # p2 controls a creature p1 owns
    cast(engine, spell, targets=[victim])
    assert engine.state.pending_choice["player_id"] == "p1"
    engine.resolve_pending_choice("top")
    assert engine.state.player_by_id("p1").library[-1] is victim


def test_spell_target_leaves_the_stack_for_the_owners_library():
    engine, spell, _ = _board(OWNER_OF_SPELL)
    theirs = filler(engine, "Their Instant", type_line="Instant", mv=2, player="p2", zone=Zone.HAND)
    p2 = engine.state.player_by_id("p2")
    from tests.support.deck_batch import main_phase
    main_phase(engine)
    p2.mana_pool.add_many({"C": 2})
    engine.cast_spell(p2, theirs)
    cast(engine, spell, targets=[engine.state.stack[0]])
    assert engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice("bottom")
    assert theirs.zone == Zone.LIBRARY and p2.library[0] is theirs
    assert not [i for i in engine.state.stack if i.obj is theirs]


def test_trailing_clause_still_resolves_after_the_choice():
    engine, spell, victim = _board(WITH_SCRY)
    stack_library(engine, "p1", filler(engine, "L1", zone=Zone.LIBRARY), filler(engine, "L2", zone=Zone.LIBRARY))
    cast(engine, spell, targets=[victim])
    assert engine.state.pending_choice["kind"] == "library_position"
    engine.resolve_pending_choice("top")
    kinds = []
    while engine.state.pending_choice is not None and len(kinds) < 6:
        kinds.append(engine.state.pending_choice["kind"])
        engine.resolve_pending_choice(None)
    assert any("scry" in k for k in kinds), kinds
