"""BUG-83 (RULE 701.19, 701.24a, 608.2c): a same-name sweep whose lead picks nothing still ends with "Then that player
shuffles" -- Lobotomy against an empty or all-basic hand, Reap Intellect with X = 0 -- for the revealed player's library."""
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game
from tests.test_par292_same_name_sweep import _count_shuffles, _zone_names


def _lobotomy(hand):
    eng = game(library=0)
    for name, type_line in hand:
        filler(eng, name, type_line=type_line, player="p2", zone=Zone.HAND)
    filler(eng, "Bolt", type_line="Instant", player="p2", zone=Zone.LIBRARY)
    filler(eng, "Bolt", type_line="Instant", player="p1", zone=Zone.LIBRARY)
    shuffled = _count_shuffles(eng)
    cast(eng, card(eng, "Lobotomy", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    return eng, shuffled


def _settle(eng):
    for _ in range(4):
        choice = eng.state.pending_choice
        if choice is None:
            return
        eng.resolve_pending_choice("ok" if choice["kind"] == "look_hand" else "decline")


def test_lobotomy_against_an_empty_hand_still_shuffles_the_targets_library():
    eng, shuffled = _lobotomy([])
    _settle(eng)
    assert shuffled == ["p2"]
    assert _zone_names(eng, "exile") == [] and _zone_names(eng, "library") == ["Bolt"]


def test_lobotomy_against_an_all_basic_hand_still_shuffles_the_targets_library():
    eng, shuffled = _lobotomy([("Forest", "Basic Land — Forest")])
    _settle(eng)
    assert shuffled == ["p2"]
    assert _zone_names(eng, "hand") == ["Forest"]


def test_reap_intellect_with_x_zero_shuffles_the_targets_library():
    eng = game(library=0)
    filler(eng, "Bolt", type_line="Instant", player="p2", zone=Zone.HAND)
    shuffled = _count_shuffles(eng)
    cast(eng, card(eng, "Reap Intellect", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")], x=0)
    _settle(eng)
    assert shuffled == ["p2"]
    assert _zone_names(eng, "hand") == ["Bolt"]


def _pick_the_brain(delirium):
    eng = game(library=0)
    filler(eng, "Forest", type_line="Basic Land — Forest", player="p2", zone=Zone.HAND)
    filler(eng, "Bolt", type_line="Instant", player="p2", zone=Zone.LIBRARY)
    if delirium:
        for kind in ("Creature", "Land", "Artifact", "Enchantment"):
            filler(eng, f"{kind} card", type_line=kind, player="p1", zone=Zone.GRAVEYARD)
    shuffled = _count_shuffles(eng)
    cast(eng, card(eng, "Pick the Brain", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    _settle(eng)
    return shuffled


def test_pick_the_brain_with_nothing_to_pick_shuffles_only_with_delirium():
    # RULE 608.2c: the shuffle sits behind the same "Delirium --" gate as the search.
    assert _pick_the_brain(delirium=False) == []
    assert _pick_the_brain(delirium=True) == ["p2"]
