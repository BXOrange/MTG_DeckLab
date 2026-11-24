"""PAR-292 M10: the search tail shapes (RULE 701.19, 701.8, 401.7).

(A) "...then shuffle and put those cards on top in any order" (Congregation at Dawn, Dwarven Recruiter, Insidious Dreams);
(B) a tutor to hand followed by a random discard (Curse-Marred Demon, Wild Research, Reckless Handling);
(D) "reveal those cards, put 1 onto the battlefield tapped and the other / the rest into your hand" with an "and/or"
union (Navigation Orb, Nissa's Pilgrimage).

Every claimed card runs on a real GameEngine, with bystanders that must stay where they are."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.clause_hooks import match_clause
from tests.support.deck_batch import activate, card, cast, filler, game, put_on_battlefield

from tests.test_par292_dynamic_search_qualities import _library_card, _modeled, _offered


@pytest.mark.parametrize("name", [
    "Congregation at Dawn", "Dwarven Recruiter", "Insidious Dreams", "Curse-Marred Demon", "Wild Research",
    "Reckless Handling", "Nissa's Pilgrimage", "Navigation Orb", "Goblin Recruiter", "Oreskos Explorer",
    "Surveyor's Scope",
])
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _pick(eng, label):
    choice = eng.state.pending_choice
    eng.resolve_pending_choice(str(next(o["id"] for o in choice["options"] if o["label"] == label)))


def _names(zone_list):
    return sorted(o.name for o in zone_list)


def _top(eng, n, player="p1"):
    return sorted(o.name for o in eng.state.player_by_id(player).library[-n:])


def test_congregation_at_dawn_puts_the_chosen_creatures_on_top_after_the_shuffle():
    eng = game(library=0)
    for name in ("A", "B", "C", "D"):
        _library_card(eng, name, mv=1, type_line="Creature")
    _library_card(eng, "Spell", mv=1, type_line="Instant")
    _library_card(eng, "Theirs", mv=1, type_line="Creature", player="p2")
    cast(eng, card(eng, "Congregation at Dawn", zone=Zone.HAND))
    assert _offered(eng) == {"A", "B", "C", "D"}
    for label in ("B", "C", "D"):
        _pick(eng, label)
    assert eng.state.pending_choice is None
    assert _top(eng, 3) == ["B", "C", "D"]  # on top, the unchosen creature and the instant below them
    assert _names(eng.state.player_by_id("p1").hand) == []
    assert _names(eng.state.player_by_id("p2").library) == ["Theirs"]
    assert len(eng.state.player_by_id("p1").library) == 5


def test_congregation_at_dawn_may_find_fewer():
    eng = game(library=0)
    for name in ("A", "B"):
        _library_card(eng, name, mv=1, type_line="Creature")
    cast(eng, card(eng, "Congregation at Dawn", zone=Zone.HAND))
    _pick(eng, "A")
    eng.resolve_pending_choice("decline")
    assert _top(eng, 1) == ["A"]


def test_dwarven_recruiter_finds_only_dwarves():
    eng = game(library=0)
    filler(eng, "Dwarf One", type_line="Creature — Dwarf", zone=Zone.LIBRARY, power=1, toughness=1)
    filler(eng, "Dwarf Two", type_line="Creature — Dwarf", zone=Zone.LIBRARY, power=1, toughness=1)
    filler(eng, "Elf", type_line="Creature — Elf", zone=Zone.LIBRARY, power=1, toughness=1)
    filler(eng, "Dwarf Spell", type_line="Instant", zone=Zone.LIBRARY)
    put_on_battlefield(eng, "Dwarven Recruiter")
    assert _offered(eng) == {"Dwarf One", "Dwarf Two"}
    _pick(eng, "Dwarf One")
    _pick(eng, "Dwarf Two")
    assert _top(eng, 2) == ["Dwarf One", "Dwarf Two"]


def test_insidious_dreams_searches_for_as_many_cards_as_it_discarded():
    eng = game(library=0)
    for name in ("A", "B", "C"):
        _library_card(eng, name, mv=1, type_line="Creature")
    dreams = card(eng, "Insidious Dreams", zone=Zone.HAND)
    for name in ("Pitch1", "Pitch2"):
        filler(eng, name, type_line="Instant", zone=Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    cast(eng, dreams, x=2, discard_choices=[o.instance_id for o in p1.hand if o.name.startswith("Pitch")])
    assert _names([o for o in p1.graveyard if o.name.startswith("Pitch")]) == ["Pitch1", "Pitch2"]
    _pick(eng, "A")
    _pick(eng, "B")
    assert eng.state.pending_choice is None
    assert _top(eng, 2) == ["A", "B"]
    assert len(p1.library) == 3


def test_curse_marred_demon_tutors_then_discards_one_card_at_random():
    eng = game(library=0)
    _library_card(eng, "Target", mv=1, type_line="Creature")
    _library_card(eng, "Other", mv=1, type_line="Creature")
    filler(eng, "InHand", type_line="Instant", zone=Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    put_on_battlefield(eng, "Curse-Marred Demon")
    _pick(eng, "Target")
    assert eng.state.pending_choice is None
    assert len(p1.hand) == 1 and len(p1.graveyard) == 1  # two cards in hand, one discarded
    assert _names(p1.hand + p1.graveyard) == ["InHand", "Target"]
    assert _names(p1.library) == ["Other"]


def test_curse_marred_demon_discard_is_random_not_chosen():
    seen = set()
    for _ in range(40):
        eng = game(library=0)
        _library_card(eng, "Target", mv=1, type_line="Creature")
        filler(eng, "InHand", type_line="Instant", zone=Zone.HAND)
        put_on_battlefield(eng, "Curse-Marred Demon")
        _pick(eng, "Target")
        seen.add(eng.state.player_by_id("p1").graveyard[0].name)
        if len(seen) == 2:
            break
    assert seen == {"Target", "InHand"}


def test_wild_research_discards_even_when_nothing_is_found():
    eng = game(library=0)
    _library_card(eng, "Creature", mv=1, type_line="Creature")
    filler(eng, "InHand", type_line="Instant", zone=Zone.HAND)
    wild = put_on_battlefield(eng, "Wild Research")
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"W": 1, "C": 1})
    activate(eng, wild, 0)
    # no enchantment in the library: the search finds nothing, the instruction still discards (RULE 701.19b)
    if eng.state.pending_choice is not None:
        eng.resolve_pending_choice("decline")
    assert _names(p1.graveyard) == ["InHand"]
    assert _names(p1.library) == ["Creature"]


def test_wild_research_enchantment_mode_finds_an_enchantment():
    eng = game(library=0)
    _library_card(eng, "Ench", mv=1, type_line="Enchantment")
    _library_card(eng, "Inst", mv=1, type_line="Instant")
    wild = put_on_battlefield(eng, "Wild Research")
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"W": 1, "C": 1})
    activate(eng, wild, 0)
    assert _offered(eng) == {"Ench"}
    _pick(eng, "Ench")
    assert _names(p1.graveyard) == ["Ench"]  # the only card in hand
    assert _names(p1.library) == ["Inst"]


def test_reckless_handling_hits_each_opponent_only_when_an_artifact_is_discarded():
    eng = game(library=0)
    _library_card(eng, "Gizmo", mv=1, type_line="Artifact")
    _library_card(eng, "Creature", mv=1, type_line="Creature")
    p2 = eng.state.player_by_id("p2")
    cast(eng, card(eng, "Reckless Handling", zone=Zone.HAND))
    _pick(eng, "Gizmo")
    assert _names(eng.state.player_by_id("p1").graveyard).count("Gizmo") == 1
    assert p2.life == 18


def test_reckless_handling_damage_follows_what_was_discarded():
    # one bulk card plus the found artifact: the random discard hits either, and the damage tracks the artifact
    outcomes = set()
    for _ in range(60):
        eng = game(library=0)
        _library_card(eng, "Gizmo", mv=1, type_line="Artifact")
        filler(eng, "Bulk", type_line="Instant", zone=Zone.HAND)
        p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
        cast(eng, card(eng, "Reckless Handling", zone=Zone.HAND))
        _pick(eng, "Gizmo")
        discarded = [o.name for o in p1.graveyard if o.name in ("Gizmo", "Bulk")]
        assert len(discarded) == 1
        assert p2.life == (18 if discarded == ["Gizmo"] else 20)
        outcomes.add(discarded[0])
        if len(outcomes) == 2:
            break
    assert outcomes == {"Gizmo", "Bulk"}


def test_navigation_orb_puts_one_onto_the_battlefield_tapped_and_the_other_into_hand():
    eng = game(library=0)
    filler(eng, "Basic", type_line="Basic Land — Forest", zone=Zone.LIBRARY)
    filler(eng, "Basic2", type_line="Basic Land — Island", zone=Zone.LIBRARY)
    filler(eng, "Gate", type_line="Land — Gate", zone=Zone.LIBRARY)
    filler(eng, "Nonbasic", type_line="Land", zone=Zone.LIBRARY)
    filler(eng, "Spell", type_line="Instant", zone=Zone.LIBRARY)
    filler(eng, "TheirsGate", type_line="Land — Gate", zone=Zone.LIBRARY, player="p2")
    orb = put_on_battlefield(eng, "Navigation Orb")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 2})
    activate(eng, orb, 0)
    assert _offered(eng) == {"Basic", "Basic2", "Gate"}
    _pick(eng, "Gate")
    _pick(eng, "Basic")
    p1 = eng.state.player_by_id("p1")
    gate = next(o for o in eng.state.battlefield if o.name == "Gate")
    assert gate.tapped
    assert _names(p1.hand) == ["Basic"]
    assert _names(eng.state.player_by_id("p2").library) == ["TheirsGate"]


def _nissa(eng):
    cast(eng, card(eng, "Nissa's Pilgrimage", zone=Zone.HAND))


def _forests(eng, n):
    for i in range(n):
        filler(eng, f"Forest{i}", type_line="Basic Land — Forest", zone=Zone.LIBRARY)
    filler(eng, "Island", type_line="Basic Land — Island", zone=Zone.LIBRARY)
    filler(eng, "Nonbasic Forest", type_line="Land — Forest", zone=Zone.LIBRARY)


def test_nissas_pilgrimage_without_spell_mastery_finds_two():
    eng = game(library=0)
    _forests(eng, 4)
    _nissa(eng)
    assert _offered(eng) == {"Forest0", "Forest1", "Forest2", "Forest3"}
    _pick(eng, "Forest0")
    _pick(eng, "Forest1")
    assert eng.state.pending_choice is None
    p1 = eng.state.player_by_id("p1")
    assert [o.name for o in eng.state.battlefield if o.name.startswith("Forest")] == ["Forest0"]
    assert next(o for o in eng.state.battlefield if o.name == "Forest0").tapped
    assert _names(p1.hand) == ["Forest1"]


def test_nissas_pilgrimage_with_spell_mastery_finds_three_the_rest_into_hand():
    eng = game(library=0)
    _forests(eng, 4)
    p1 = eng.state.player_by_id("p1")
    for i in range(2):
        filler(eng, f"Done{i}", type_line="Instant", zone=Zone.GRAVEYARD)
    _nissa(eng)
    for label in ("Forest0", "Forest1", "Forest2"):
        _pick(eng, label)
    assert eng.state.pending_choice is None
    assert [o.name for o in eng.state.battlefield if o.name.startswith("Forest")] == ["Forest0"]
    assert _names(p1.hand) == ["Forest1", "Forest2"]
    assert _names(p1.library) == ["Forest3", "Island", "Nonbasic Forest"]


def _lands(eng, player, n):
    for i in range(n):
        filler(eng, f"{player}-land{i}", type_line="Basic Land — Forest", player=player)


def _plains(eng, n):
    for i in range(n):
        filler(eng, f"Plains{i}", type_line="Basic Land — Plains", zone=Zone.LIBRARY)
    filler(eng, "Swamp", type_line="Basic Land — Swamp", zone=Zone.LIBRARY)


def test_oreskos_explorer_counts_the_players_with_more_lands():
    eng = game(players=4, library=0)
    _lands(eng, "p1", 3)
    _lands(eng, "p2", 5)   # more
    _lands(eng, "p3", 3)   # equal: not more
    _lands(eng, "p4", 4)   # more
    _plains(eng, 4)
    put_on_battlefield(eng, "Oreskos Explorer")
    assert _offered(eng) == {"Plains0", "Plains1", "Plains2", "Plains3"}
    _pick(eng, "Plains0")
    _pick(eng, "Plains1")
    assert eng.state.pending_choice is None  # x = 2
    assert _names(eng.state.player_by_id("p1").hand) == ["Plains0", "Plains1"]


def test_oreskos_explorer_finds_nothing_when_no_player_has_more_lands():
    eng = game(players=3, library=0)
    _lands(eng, "p1", 4)
    _lands(eng, "p2", 4)
    _plains(eng, 2)
    put_on_battlefield(eng, "Oreskos Explorer")
    assert eng.state.pending_choice is None or not _offered(eng)
    assert eng.state.player_by_id("p1").hand == []


def test_surveyors_scope_counts_only_players_with_at_least_two_more_lands():
    eng = game(players=3, library=0)
    _lands(eng, "p1", 2)
    _lands(eng, "p2", 4)   # exactly 2 more: counts
    _lands(eng, "p3", 3)   # only 1 more: does not
    _plains(eng, 3)
    scope = card(eng, "Surveyor's Scope")
    activate(eng, scope, 0)
    assert _offered(eng) == {"Plains0", "Plains1", "Plains2", "Swamp"}
    _pick(eng, "Swamp")
    assert eng.state.pending_choice is None  # x = 1
    assert [o.name for o in eng.state.battlefield if o.name == "Swamp"] == ["Swamp"]


@pytest.mark.parametrize("text", [
    # a split that names a third destination
    "search your library for up to 2 basic land cards, reveal those cards, and put 1 onto the battlefield tapped and the rest into your graveyard-ish pile, then shuffle",
    # the order tail attached to a hand destination is not a library placement
    "search your library for a card, then shuffle and put it into your hand in any order",
    # a random discard that is not the tutor's own follow-up
    "search your library for a card, put it into your hand, shuffle, then discard 2 cards at random",
    "search your library for a card, put it onto the battlefield, shuffle, then discard a card at random",
])
def test_near_misses_stay_unclaimed(text):
    assert not match_clause(text)
