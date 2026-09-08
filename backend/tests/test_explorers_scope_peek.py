"""Explorer's Scope: "Whenever equipped creature attacks, look at the top
card of your library. If it's a land card, you may put it onto the
battlefield tapped." Bug report, 2026-09-04: `PeekTopLandBattlefieldTapped
Effect` used to move a found land onto the battlefield *unconditionally*
(no "may" at all) by calling `RulesEngine._put_searched_card` directly
without first removing the card from the library — `_put_searched_card`
only ever *appends* to the battlefield, trusting its caller to already
have removed the object from its previous zone (every real search effect
does, via `_remove_search_hit`). The result was the same `GameObject`
sitting in both `player.library` and `state.battlefield` at once; a later
draw would then hand that very same still-in-library object into the
player's hand too, so it ended up "duplicated" across three zone lists,
tapped state and all, all pointing at one shared object.

Also: a non-land top card produced no feedback at all (silently did
nothing) — RULE 701.20's "look" still means the controller saw
*something*. Both are fixed via a genuine `peek_top_land` interactive
choice, `RulesEngine.peek_top_land_battlefield_tapped`/`resolve_peek_top_
land_choice` (`game/rules/search_mixin.py`), mirroring `explore`'s own
"reveal top card, offer a decision" shape just above it.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _card(name, type_line, **kw):
    return Card(id=name, name=name, type_line=type_line, **kw)


def _engine():
    return GameEngine.new_game([("p1", "Alice", [])], starting_life=20, starting_hand=0)


def _scope(state, controller="p1"):
    card = _card(
        "Explorer's Scope", "Artifact — Equipment",
        oracle_text="Whenever equipped creature attacks, look at the top card of your "
                    "library. If it's a land card, you may put it onto the battlefield "
                    "tapped.\nEquip {1}",
    )
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_finding_a_land_opens_a_genuine_put_or_decline_choice():
    eng = _engine()
    p1 = eng.state.active_player
    eng.begin_turn()
    scope = _scope(eng.state)
    top = GameObject(_card("Mountain", "Basic Land — Mountain", is_land=True),
                      owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(top)

    eng.rules.peek_top_land_battlefield_tapped(p1, source=scope)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "peek_top_land"
    ids = {opt["id"] for opt in choice["options"]}
    assert ids == {"put", "decline"}
    # Not yet moved anywhere — still exactly where it started.
    assert top in p1.library
    assert top not in eng.state.battlefield


def test_declining_leaves_the_land_on_top_untouched():
    eng = _engine()
    p1 = eng.state.active_player
    eng.begin_turn()
    top = GameObject(_card("Mountain", "Basic Land — Mountain", is_land=True),
                      owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(top)

    eng.rules.peek_top_land_battlefield_tapped(p1)
    eng.resolve_pending_choice("decline")

    assert top in p1.library
    assert top not in eng.state.battlefield
    assert eng.state.pending_choice is None


def test_putting_it_moves_it_exactly_once_never_leaving_the_library_behind():
    eng = _engine()
    p1 = eng.state.active_player
    eng.begin_turn()
    top = GameObject(_card("Mountain", "Basic Land — Mountain", is_land=True),
                      owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(top)

    eng.rules.peek_top_land_battlefield_tapped(p1)
    eng.resolve_pending_choice("put")

    assert top not in p1.library  # the actual bug: this used to still be True
    assert top in eng.state.battlefield
    assert eng.state.battlefield.count(top) == 1
    assert top.tapped is True
    assert top.zone == Zone.BATTLEFIELD


def test_no_later_draw_duplicates_the_moved_land_into_hand():
    # The concrete symptom from the bug report: a subsequent draw pulling
    # the *same* object (still sitting in the library list) into hand too.
    eng = _engine()
    p1 = eng.state.active_player
    eng.begin_turn()
    # `library[-1]` is the top of the deck (the convention this engine's
    # library list uses throughout) — Filler goes in first so Mountain,
    # appended after, is what actually gets peeked/put.
    filler = GameObject(_card("Filler", "Instant", is_instant=True),
                         owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(filler)
    top = GameObject(_card("Mountain", "Basic Land — Mountain", is_land=True),
                      owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(top)

    eng.rules.peek_top_land_battlefield_tapped(p1)
    eng.resolve_pending_choice("put")

    eng.rules.draw(p1, 1)
    assert [o.name for o in p1.hand] == ["Filler"]
    assert top not in p1.hand
    assert eng.state.battlefield.count(top) == 1


def test_a_nonland_top_card_is_still_shown_with_no_battlefield_action():
    eng = _engine()
    p1 = eng.state.active_player
    eng.begin_turn()
    top = GameObject(_card("Lightning Bolt", "Instant", is_instant=True),
                      owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(top)

    eng.rules.peek_top_land_battlefield_tapped(p1)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "peek_top_land"
    assert choice["card_id"] == top.instance_id  # the peeked card is nameable/visible
    assert [opt["id"] for opt in choice["options"]] == ["ok"]

    eng.resolve_pending_choice("ok")
    assert top in p1.library
    assert top not in eng.state.battlefield
    assert eng.state.pending_choice is None


def test_empty_library_opens_no_choice():
    eng = _engine()
    p1 = eng.state.active_player
    eng.begin_turn()
    eng.rules.peek_top_land_battlefield_tapped(p1)
    assert eng.state.pending_choice is None
