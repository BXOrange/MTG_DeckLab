"""PAR-292 M24: a search of ANOTHER player's library that the controller makes (RULE 701.19a, 401.2, 400.3).

"Search target player's | opponent's library for <cards> and exile them / put them into their graveyard. Then that
player shuffles." (Life's Finale, Neverending Torment, Nightmare Incursion) and "Choose target permanent an opponent
controls. Search that player's library for a card with the same name and put it onto the battlefield under your
control. Then that player shuffles." (Mimeofacture). The caster looks through and answers; the library, its shuffle and
every found card's ownership are the target's; a third player and the caster's own library are never touched."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.player import Player
from tests.support.deck_batch import answer, card, cast, filler, game
from tests.test_par292_dynamic_search_qualities import _library_card, _modeled, _offered


@pytest.mark.parametrize("name", ["Life's Finale", "Neverending Torment", "Nightmare Incursion", "Mimeofacture"])
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def test_earwig_squad_stays_open_until_the_prowl_alternative_cost_exists():
    # its search sentence reads, but "if its prowl cost was paid" has no engine flag (no prowl cast): not claimed
    assert not _modeled("Earwig Squad")


@pytest.fixture
def shuffles(monkeypatch):
    seen: list[str] = []
    original = Player.shuffle_library

    def spy(self):
        seen.append(self.id)
        return original(self)

    monkeypatch.setattr(Player, "shuffle_library", spy)
    return seen


def _three_libraries(eng):
    for who, creatures in (("p1", "Mine"), ("p2", "Their"), ("p3", "Third")):
        for i in range(4):
            _library_card(eng, f"{creatures}Bear{i}", mv=2, type_line="Creature", player=who)
        _library_card(eng, f"{creatures}Land", mv=0, type_line="Basic Land — Forest", player=who)


def _pick_first(eng):
    choice = eng.state.pending_choice
    eng.resolve_pending_choice(str(next(o["id"] for o in choice["options"] if o["id"] != "decline")))


def _names(player, zone):
    return sorted(o.name for o in getattr(player, zone))


def test_lifes_finale_destroys_then_the_caster_buries_up_to_three_of_the_targets_creatures(shuffles):
    eng = game(players=3, library=0)
    _three_libraries(eng)
    p1, p2, p3 = (eng.state.player_by_id(p) for p in ("p1", "p2", "p3"))
    mine = filler(eng, "MyBody", type_line="Creature", power=1, toughness=1)
    theirs = filler(eng, "TheirBody", type_line="Creature", power=1, toughness=1, player="p2")
    cast(eng, card(eng, "Life's Finale", zone=Zone.HAND), targets=[p2])
    assert mine.zone != Zone.BATTLEFIELD and theirs.zone != Zone.BATTLEFIELD  # "destroy all creatures" came first
    choice = eng.state.pending_choice
    assert choice["kind"] == "search" and choice["player_id"] == "p1"  # the caster searches (RULE 701.19a)
    assert _offered(eng) == {f"TheirBear{i}" for i in range(4)}  # only p2's creature cards, no land, nothing of p1 / p3
    for _ in range(3):
        _pick_first(eng)
    assert eng.state.pending_choice is None
    buried = [o for o in p2.graveyard if o.name.startswith("TheirBear")]
    assert len(buried) == 3 and all(o.owner_id == "p2" for o in buried)
    assert len(p2.library) == 2 and len(p1.library) == 5 and len(p3.library) == 5  # up to three, exactly three left p2
    assert not [o for o in p1.graveyard + p3.graveyard if o.name.endswith(tuple("0123"))]
    assert shuffles == ["p2"]  # only the searched library is shuffled, and it is the target's


def test_lifes_finale_search_may_stop_early(shuffles):
    eng = game(players=3, library=0)
    _three_libraries(eng)
    cast(eng, card(eng, "Life's Finale", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    _pick_first(eng)
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None and len(eng.state.player_by_id("p2").graveyard) == 1
    assert shuffles == ["p2"]


def test_lifes_finale_cannot_target_its_caster():
    # "target OPPONENT" (RULE 115.1): the caster is not a legal target, so nothing of her own library is searched
    eng = game(players=3, library=0)
    _three_libraries(eng)
    cast(eng, card(eng, "Life's Finale", zone=Zone.HAND), targets=[eng.state.player_by_id("p1")])
    assert eng.state.pending_choice is None  # the illegal target never reaches the search
    assert len(eng.state.player_by_id("p1").library) == 5


def test_nightmare_incursion_exiles_as_many_cards_as_the_casters_swamps(shuffles):
    eng = game(players=3, library=0)
    _three_libraries(eng)
    for i in range(2):
        filler(eng, f"Swamp{i}", type_line="Basic Land — Swamp")
    filler(eng, "OpponentSwamp", type_line="Basic Land — Swamp", player="p2")  # not "you control"
    filler(eng, "Forest", type_line="Basic Land — Forest")
    p2 = eng.state.player_by_id("p2")
    cast(eng, card(eng, "Nightmare Incursion", zone=Zone.HAND), targets=[p2])
    assert eng.state.pending_choice["player_id"] == "p1"
    assert "TheirLand" in _offered(eng) and not any(n.startswith(("Mine", "Third")) for n in _offered(eng))
    _pick_first(eng)
    _pick_first(eng)
    assert eng.state.pending_choice is None  # two Swamps -> two cards
    exiled = [o for o in p2.exile if o.name.startswith("Their")]  # exile is kept by owner: p2's cards, p2's exile
    assert len(exiled) == 2 and all(o.zone == Zone.EXILE for o in exiled)
    assert not eng.state.player_by_id("p1").exile
    assert len(p2.library) == 3 and shuffles == ["p2"]


def test_nightmare_incursion_with_no_swamps_finds_nothing_but_still_shuffles_the_target(shuffles):
    eng = game(players=3, library=0)
    _three_libraries(eng)
    p2 = eng.state.player_by_id("p2")
    cast(eng, card(eng, "Nightmare Incursion", zone=Zone.HAND), targets=[p2])
    answer(eng)
    assert len(p2.library) == 5 and not p2.exile
    assert shuffles == ["p2"]


def test_neverending_torment_counts_the_cards_in_the_casters_hand(shuffles):
    eng = game(players=3, library=0)
    _three_libraries(eng)
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    for i in range(3):
        filler(eng, f"HandCard{i}", type_line="Creature", zone=Zone.HAND)
    cast(eng, card(eng, "Neverending Torment", zone=Zone.HAND), targets=[p2])
    assert len(p1.hand) == 3  # the spell itself left the hand before it resolved
    for _ in range(3):
        assert eng.state.pending_choice["player_id"] == "p1"
        _pick_first(eng)
    assert eng.state.pending_choice is None
    assert len(p2.exile) == 3 and not p1.exile
    assert len(p2.library) == 2 and len(p1.library) == 5 and len(eng.state.player_by_id("p3").library) == 5
    assert "p2" in shuffles and "p3" not in shuffles


def test_neverending_torment_with_a_different_hand_size_exiles_a_different_amount():
    eng = game(players=3, library=0)
    _three_libraries(eng)
    p2 = eng.state.player_by_id("p2")
    filler(eng, "OnlyCard", type_line="Creature", zone=Zone.HAND)
    cast(eng, card(eng, "Neverending Torment", zone=Zone.HAND), targets=[p2])
    _pick_first(eng)
    assert eng.state.pending_choice is None and len(p2.library) == 4


def test_mimeofacture_fetches_a_same_named_card_from_the_owners_library_under_the_casters_control(shuffles):
    eng = game(players=3, library=0)
    for who in ("p1", "p2", "p3"):
        _library_card(eng, "Grizzly Bears", mv=2, type_line="Creature", player=who)
        _library_card(eng, f"Other-{who}", mv=2, type_line="Creature", player=who)
    p1, p2, p3 = (eng.state.player_by_id(p) for p in ("p1", "p2", "p3"))
    bears = filler(eng, "Grizzly Bears", type_line="Creature", power=2, toughness=2, player="p2")
    cast(eng, card(eng, "Mimeofacture", zone=Zone.HAND), targets=[bears])
    choice = eng.state.pending_choice
    assert choice["kind"] == "search" and choice["player_id"] == "p1"
    assert _offered(eng) == {"Grizzly Bears"}  # only the same name, only from p2's library
    _pick_first(eng)
    assert eng.state.pending_choice is None
    fetched = [o for o in eng.state.battlefield if o.name == "Grizzly Bears" and o is not bears]
    assert len(fetched) == 1 and fetched[0].controller_id == "p1" and fetched[0].owner_id == "p2"
    assert [o.name for o in p2.library] == ["Other-p2"]
    assert len(p1.library) == 2 and len(p3.library) == 2
    assert shuffles == ["p2"]


def test_mimeofacture_with_no_copy_left_finds_nothing_and_still_shuffles(shuffles):
    eng = game(players=3, library=0)
    _library_card(eng, "Unrelated", mv=2, type_line="Creature", player="p2")
    bears = filler(eng, "Grizzly Bears", type_line="Creature", power=2, toughness=2, player="p2")
    cast(eng, card(eng, "Mimeofacture", zone=Zone.HAND), targets=[bears])
    answer(eng)
    assert len(eng.state.player_by_id("p2").library) == 1 and shuffles == ["p2"]
    assert [o.name for o in eng.state.battlefield if o.name == "Grizzly Bears"] == ["Grizzly Bears"]


def test_mimeofacture_cannot_target_its_casters_own_permanent():
    eng = game(players=3, library=0)
    _library_card(eng, "Grizzly Bears", mv=2, type_line="Creature", player="p1")
    mine = filler(eng, "Grizzly Bears", type_line="Creature", power=2, toughness=2)
    with pytest.raises(ValueError, match="no legal target"):  # "an opponent controls" (RULE 115.1)
        cast(eng, card(eng, "Mimeofacture", zone=Zone.HAND), targets=[mine])
    assert len(eng.state.player_by_id("p1").library) == 1


@pytest.mark.parametrize("text", [
    # a hand destination would put the card into its owner's hand (RULE 400.3): not this shape
    "search target opponent's library for a creature card and put it into your hand. then that player shuffles.",
    # an X count with no "where x is" measurement
    "search target opponent's library for x cards and exile them. then that player shuffles.",
    # a measurement for a count that is not X
    "search target opponent's library for 3 cards, where x is the number of cards in your hand, and exile them. "
    "then that player shuffles.",
    # a measurement the grammar does not read
    "search target opponent's library for x cards, where x is the number of frobnications you control, and exile them. "
    "then that player shuffles.",
    # no shuffle sentence
    "search target opponent's library for x cards, where x is the number of cards in your hand, and exile them.",
    # Mimeofacture near misses: no opponent restriction on the chosen permanent / a hand destination
    "choose target permanent. search that player's library for a card with the same name and put it onto the "
    "battlefield under your control. then that player shuffles.",
    "choose target permanent an opponent controls. search that player's library for a card with the same name and "
    "put it into your hand. then that player shuffles.",
])
def test_near_misses_stay_unclaimed(text):
    from mtg_analyzer.parser.oracle.catalogue.clause_hooks import parse_effect_body
    assert not parse_effect_body(text)


def test_a_gated_lead_is_not_peeled_off_the_search():
    from mtg_analyzer.parser.oracle.catalogue.clause_hooks import parse_effect_body
    gated = ("if you control a swamp, destroy all creatures, then search target opponent's library for up to 3 "
             "creature cards and put them into their graveyard. then that player shuffles.")
    # the lead peel never claims an if-gated sentence (the gate must keep covering both instructions)
    from mtg_analyzer.parser.oracle.catalogue.effect_rows.search_control_attach import SEARCH_OTHER_LIBRARY_LEAD_RE
    assert SEARCH_OTHER_LIBRARY_LEAD_RE.fullmatch(gated) is None
