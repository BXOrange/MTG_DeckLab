"""PAR-120 — `catalogue.handlers._activation_condition_dict` now falls back
to `static_handlers.static_condition()` once its own closed table declines,
closing the real architectural duplication this ticket has flagged at each
of its earlier "activate only if" additions this session (commander, total
power, the desert compound) without ever taking the step. "Activate only
if …" is a genuinely narrower vocabulary than the shared one (few printed
cards gate an *activation* rather than a standing/triggered ability), but
every phrase it recognizes is a hand-copied subset of `_STATIC_CONDITION_
RES` — so a phrase new to *this* table almost always already resolves via
the shared one, with zero risk to an already-shipped card: the fallback is
tried only once every row in this table's own closed list has declined, so
an existing row's own kind spelling is preserved exactly.

`parser_probe.py diff`: +59, 0 regressed. Also fixed a stale test pin
(`test_par10_activation_conditions.py`) that had documented "activate only
if you control a Plains" as deliberately unrecognized tail work — it now
correctly resolves through the shared count-phrase grammar, same as "as
long as you control a Plains" already did.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import _activation_condition_dict
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# ---------------------------------------------------------------------------
# PARSER: the fallback itself
# ---------------------------------------------------------------------------


def test_a_phrase_new_to_this_table_falls_back_to_the_shared_vocabulary():
    assert _activation_condition_dict("you gained life this turn") == {
        "kind": "gained_life_this_turn",
    }


def test_a_phrase_this_tables_own_row_already_recognizes_keeps_its_own_kind():
    # `cast_instant_or_sorcery_this_turn` is this table's own row's kind —
    # unchanged, not silently swapped for whatever `static_condition` would
    # have produced for the same phrase.
    assert _activation_condition_dict("you've cast an instant or sorcery spell this turn") == {
        "kind": "cast_instant_or_sorcery_this_turn",
    }


def test_still_unmodeled_phrase_fails_closed():
    assert _activation_condition_dict("this creature is attacking") is None


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards
# ---------------------------------------------------------------------------


def test_real_cards_become_modeled():
    for name in (
        "Brackish Trudge", "Luminarch Ascension", "Idol of Oblivion",
        "Inventors' Fair", "Bonders' Enclave", "Cryptic Caves",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, real board
# ---------------------------------------------------------------------------


def test_brackish_trudge_only_returns_itself_once_life_was_gained():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    state = eng.state
    state.current_step = "main1"
    p1 = state.players[0]

    trudge = GameObject(_db().get_card("Brackish Trudge"), owner_id="p1", zone=Zone.GRAVEYARD)
    trudge.controller_id = "p1"
    bind_from_catalogue(trudge)
    p1.graveyard.append(trudge)

    ability = trudge.activated_abilities[0]
    assert eng.can_activate(p1, trudge, ability, assume_mana_available=True) is False

    eng.rules.gain_life(p1, 3)
    assert eng.can_activate(p1, trudge, ability, assume_mana_available=True) is True
