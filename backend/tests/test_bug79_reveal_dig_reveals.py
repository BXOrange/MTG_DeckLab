"""BUG-79: a "reveal the top N" dig reveals (RULE 701.20a, 400.2); a "look at" dig does not.

`parse_dig` never set `reveal` on `inspect_top_choose`, so the inspected cards never became public. The verb now
decides: "reveal the top N" shows the whole window (`reveal`), "look at the top N ... you may reveal a card from among
them and put it into your hand" shows only the pick (`reveal_library_to_hand`), a bare "look at" shows nothing.
Run on the real engine; the opponent's view (`known_cards`) is the witness.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.services.game_session import GameSession

from tests.support.deck_batch import answer, card, cast, filler, game, pick_label
from tests.test_par157_back_selections import _cached

REVEAL_DIG = ("Reveal the top 4 cards of your library. You may put a creature card from among them into your hand. "
              "Put the rest on the bottom of your library in a random order.")
LOOK_DIG = REVEAL_DIG.replace("Reveal the top", "Look at the top")
LOOK_REVEAL_PICK_DIG = ("Look at the top 4 cards of your library. You may reveal a creature card from among them and put "
                        "it into your hand. Put the rest on the bottom of your library in a random order.")
#: Window card names, top first; "Bear" is the only creature of the first four.
WINDOW = [("Alpha", "Land"), ("Bear", "Creature — Bear"), ("Gamma", "Sorcery"), ("Delta", "Land"), ("Below", "Land")]
WINDOW_SIZE = 4


def _dig_effects(text):
    return [e for s in parse_oracle(Card(id="t", name="Probe", type_line="Sorcery", oracle_text=text,
                                    is_sorcery=True)).specs
            for e in s.effects if e.type == "inspect_top_choose"]


def _known(session, perspective):
    return {c["name"] for c in session.view(perspective=perspective)["state"]["known_cards"]}


def _dig(text):
    eng = game()
    p1 = eng.state.player_by_id("p1")
    cards = [filler(eng, n, zone=Zone.LIBRARY, type_line=t, **({"power": 2, "toughness": 2} if "Creature" in t else {}))
             for n, t in WINDOW]
    p1.library[:] = list(reversed(cards))
    cast(eng, filler(eng, "Dig", "Sorcery", zone=Zone.HAND, oracle_text=text))
    answer(eng, pick_label("Bear"))
    return eng, p1, GameSession(eng, mode="replay", require_setup=False)


def test_the_backlog_clause_sets_reveal():
    reveal = match_clause(REVEAL_DIG.lower())
    assert reveal is not None and reveal[0].params["reveal"] is True


def test_a_look_at_dig_sets_neither_reveal_nor_reveal_pick():
    (spec,) = _dig_effects(LOOK_DIG)
    assert "reveal" not in spec.params and spec.params["action"] == "library_to_hand"


def test_a_look_then_reveal_the_pick_reveals_only_the_pick():
    (spec,) = _dig_effects(LOOK_REVEAL_PICK_DIG)
    assert "reveal" not in spec.params and spec.params["action"] == "reveal_library_to_hand"


def test_reveal_dig_shows_every_inspected_card_to_the_opponent():
    eng, p1, session = _dig(REVEAL_DIG)
    assert [o.name for o in p1.hand] == ["Bear"]
    # RULE 701.20a: the whole window was shown; the pick stays known in hand (the rest returns in a random order, so
    # their library positions are forgotten).
    assert "Bear" in _known(session, "p2")
    revealed = {e.get("object") for e in eng.state.event_log if e.type == EventType.REVEAL}
    assert revealed == {n for n, _ in WINDOW[:WINDOW_SIZE]}


def test_look_at_dig_leaves_the_opponent_blind():
    eng, _, session = _dig(LOOK_DIG)
    assert _known(session, "p2") == set()
    assert not any(e.type == EventType.REVEAL for e in eng.state.event_log)


def test_look_then_reveal_the_pick_shows_only_the_pick():
    _, p1, session = _dig(LOOK_REVEAL_PICK_DIG)
    assert [o.name for o in p1.hand] == ["Bear"]
    assert _known(session, "p2") == {"Bear"}


def test_a_parsed_real_card_end_to_end():
    # Mulch: "Reveal the top four cards of your library. Put all land cards revealed this way into your hand and the
    # rest into your graveyard." -- the lands in hand are public knowledge afterwards.
    assert parse_oracle(_cached("Mulch")).modeled
    eng = game()
    p1 = eng.state.player_by_id("p1")
    cards = [filler(eng, n, zone=Zone.LIBRARY, type_line=t) for n, t in WINDOW]
    p1.library[:] = list(reversed(cards))
    cast(eng, card(eng, "Mulch", zone=Zone.HAND))
    answer(eng)
    session = GameSession(eng, mode="replay", require_setup=False)
    assert {o.name for o in p1.hand} == {"Alpha", "Delta"}
    assert _known(session, "p2") == {"Alpha", "Delta"}


@pytest.mark.parametrize("name", ["Genesis Wave", "Atraxa, Grand Unifier", "Dihada, Binder of Wills",
                                  "Cavalier of Thorns", "Wrenn and Seven", "Shigeki, Jukai Visionary",
                                  "Earth's Mightiest Heroes"])
def test_hand_authored_reveal_digs_reveal(name):
    from mtg_analyzer.game.card_registry import specs_for
    specs = [e for s in specs_for(_cached(name)) for e in s.effects if e.type == "inspect_top_choose"]
    assert specs and all(e.params.get("reveal") is True for e in specs)


def test_hand_authored_look_then_reveal_pick_uses_the_reveal_pick_action():
    from mtg_analyzer.game.card_registry import specs_for
    (spec,) = [e for s in specs_for(_cached("Eclipsed Flamekin")) for e in s.effects if e.type == "inspect_top_choose"]
    assert spec.params["action"] == "reveal_library_to_hand" and "reveal" not in spec.params
