"""PAR-292 M23: the exiled top of your library as a casting pool with a cap and a bottom tail (Collected Conjuring, Herald of
Amity), the exiled pile one chooses to play from (Brilliant Ultimatum) and the library pile that yields one card (Truth or
Tale). RULE 608.2g (cast during resolution), 118.9 (free), 401.4 (bottom of the library), 700.3 / 101.4 (piles).

Parsed from the real oracle text, then run on a real engine with a bystander library: only the ability's controller is
offered the cards, a cap ends the offers, everything not cast goes to the bottom of the controller's own library."""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle

from tests.support.deck_batch import card, cast, filler, game, put_on_battlefield, stack_library
from tests.test_par292_dynamic_search_qualities import _modeled

CLAIMED = ["Collected Conjuring", "Herald of Amity", "Brilliant Ultimatum", "Truth or Tale", "Boonweaver Giant", "Runed Crown"]


@pytest.mark.parametrize("name", CLAIMED)
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _probe(text, type_line="Sorcery"):
    return parse_oracle(Card(id="t", name="Probe", type_line=type_line, oracle_text=text, is_sorcery=type_line == "Sorcery"))


_CONJURING = ("Exile the top six cards of your library. You may cast up to two sorcery spells with mana value 3 or less "
              "from among them without paying their mana costs. Put the exiled cards not cast this way on the bottom of "
              "your library in a random order.")
_ULTIMATUM = ("Exile the top five cards of your library. An opponent separates those cards into two piles. You may play "
              "lands and cast spells from one of those piles. If you cast a spell this way, you cast it without paying its "
              "mana cost.")
_TRUTH = ("Reveal the top five cards of your library and separate them into two piles. An opponent chooses one of those "
          "piles. Put a card from the chosen pile into your hand, then put all other cards revealed this way on the bottom "
          "of your library in any order.")


def test_the_probe_texts_are_modeled():
    assert _probe(_CONJURING).modeled and _probe(_ULTIMATUM).modeled and _probe(_TRUTH).modeled


@pytest.mark.parametrize("text", [
    # "any order" is the player's own sequence, not the engine's random bottom
    _CONJURING.replace("in a random order", "in any order"),
    # a cap over a window that lasts the turn cannot be enforced
    _CONJURING.replace("without paying", "this turn without paying").replace("them without", "them without"),
    # the bottom tail belongs to the controller's own exiled batch, not an opponent's
    _CONJURING.replace("of your library.", "of target opponent's library.", 1),
    # a milled pool has no "rest" that goes to the bottom
    _CONJURING.replace("Exile the top six cards of your library", "Mill six cards"),
    # a zero cap casts nothing
    _CONJURING.replace("up to two", "up to zero"),
    # three piles is another mechanism
    _ULTIMATUM.replace("two piles", "three piles"),
    # the free cast is the printed rider; without it the pile cast costs mana
    _ULTIMATUM.replace(" If you cast a spell this way, you cast it without paying its mana cost.", ""),
    # the bottom is the whole batch; "on top" is another card
    _TRUTH.replace("on the bottom of your library in any order", "on top of your library in any order"),
    # the attached-on-entry search is the combined-zone one, and the attachment is to ~, never to another permanent
    "When ~ enters, you may search your graveyard, hand, and/or library for an Aura card and put it onto the battlefield "
    "attached to target creature. If you search your library this way, shuffle.",
    # only a card that enters the battlefield can enter attached
    "When ~ enters, you may search your graveyard, hand, and/or library for an Aura card and put it into your hand "
    "attached to ~. If you search your library this way, shuffle.",
    # a different pile fate than the printed one
    _TRUTH.replace("Put a card from the chosen pile into your hand", "Put the chosen pile into your hand"),
])
def test_near_misses_stay_unmodeled(text):
    assert not _probe(text).modeled


def _stack(eng, player, *kinds):
    """``player``'s library, first kind = top; vanilla fillers named by position."""
    made = [filler(eng, f"{player}-{i}-{k.split()[0]}", type_line=k, player=player, zone=Zone.LIBRARY,
                   mv=int(k.split()[-1]) if k.split()[-1].isdigit() else 0)
            for i, k in enumerate(kinds)]
    stack_library(eng, player, *reversed(made))
    return made


def _bystander(eng):
    return list(eng.state.player_by_id("p2").library)


def test_collected_conjuring_offers_only_cheap_sorceries_and_stops_after_two_casts():
    eng = game(library=0)
    made = _stack(eng, "p1", "Sorcery 1", "Creature", "Sorcery 2", "Sorcery 3", "Sorcery 5", "Instant 1", "Land")
    below = made[6]  # the seventh card is under the exiled six
    by = _bystander(eng)
    cast(eng, card(eng, "Collected Conjuring", zone=Zone.HAND))
    p1 = eng.state.player_by_id("p1")
    choice = eng.state.resolution_play_choice
    offered = {made[0].instance_id, made[2].instance_id, made[3].instance_id}
    assert choice["player_id"] == "p1" and set(choice["instance_ids"]) == offered and choice["free"]
    eng.play_resolution_card(p1, made[0])
    eng.resolve_until_stable()
    choice = eng.state.resolution_play_choice
    assert choice is not None and set(choice["instance_ids"]) == {made[2].instance_id, made[3].instance_id}
    assert choice["bottom_remaining"]  # the rest waits for the end of the casting sequence
    assert made[1].zone == Zone.EXILE  # nothing went down yet
    eng.play_resolution_card(p1, made[2])
    eng.resolve_until_stable()
    assert eng.state.resolution_play_choice is None  # "up to two": no third offer
    assert made[3].zone == Zone.LIBRARY  # the third cheap sorcery was never cast and went down with the rest
    assert {o.name for o in p1.library[:4]} == {made[1].name, made[3].name, made[4].name, made[5].name}
    assert p1.library[-1] is below and not [o for o in p1.exile if o in made]
    assert made[0] in p1.graveyard and made[2] in p1.graveyard
    assert _bystander(eng) == by


def test_collected_conjuring_declining_after_one_cast_bottoms_the_rest():
    eng = game(library=0)
    made = _stack(eng, "p1", "Sorcery 1", "Sorcery 2", "Creature", "Land", "Instant", "Sorcery 3")
    cast(eng, card(eng, "Collected Conjuring", zone=Zone.HAND))
    p1 = eng.state.player_by_id("p1")
    eng.play_resolution_card(p1, made[1])
    eng.resolve_until_stable()
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert not p1.exile and made[1] in p1.graveyard
    assert {o.name for o in p1.library} == {o.name for o in made if o is not made[1]}


def test_collected_conjuring_with_nothing_castable_still_bottoms_the_batch():
    eng = game(library=0)
    made = _stack(eng, "p1", "Creature", "Land", "Instant 1", "Sorcery 4", "Creature", "Land", "Land")
    cast(eng, card(eng, "Collected Conjuring", zone=Zone.HAND))
    p1 = eng.state.player_by_id("p1")
    assert eng.state.resolution_play_choice is None and not p1.exile
    assert p1.library[-1] is made[6] and {o.name for o in p1.library[:6]} == {o.name for o in made[:6]}


def test_herald_of_amity_offers_only_an_aura_for_free_and_bottoms_the_rest():
    eng = game(library=0)
    made = _stack(eng, "p1", "Creature", "Enchantment — Aura", "Land", "Instant 1", "Sorcery 1", "Land", "Creature",
                  "Enchantment — Aura", "Land")
    below = made[8]
    by = _bystander(eng)
    put_on_battlefield(eng, "Herald of Amity")
    eng.resolve_until_stable()
    choice = eng.state.resolution_play_choice
    assert choice["player_id"] == "p1" and set(choice["instance_ids"]) == {made[1].instance_id, made[7].instance_id}
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    p1 = eng.state.player_by_id("p1")
    assert not p1.exile and p1.library[-1] is below
    assert {o.name for o in p1.library[:8]} == {o.name for o in made[:8]}
    assert _bystander(eng) == by


def _answer(eng, who, option):
    assert eng.state.pending_choice["player_id"] == who
    eng.resolve_pending_choice(option)


def test_brilliant_ultimatum_opponent_separates_caster_plays_lands_and_casts_free_from_one_pile():
    eng = game(players=3, library=0)
    made = _stack(eng, "p1", "Sorcery 4", "Land", "Instant 3", "Creature", "Land", "Land")
    below = made[5]
    by = _bystander(eng)
    cast(eng, card(eng, "Brilliant Ultimatum", zone=Zone.HAND))
    # with two opponents the caster names which one separates (RULE 101.4); the other is never asked
    assert eng.state.pending_choice["player_id"] == "p1"
    _answer(eng, "p1", "p2")
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p2"
    _answer(eng, "p2", str(made[0].instance_id))
    _answer(eng, "p2", str(made[1].instance_id))
    _answer(eng, "p2", "decline")
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p1" and [o["label"] for o in choice["options"]] == [
        f"{made[0].name}, {made[1].name}", f"{made[2].name}, {made[3].name}, {made[4].name}"]
    _answer(eng, "p1", "first")
    choice = eng.state.resolution_play_choice
    assert choice["player_id"] == "p1" and set(choice["instance_ids"]) == {made[0].instance_id, made[1].instance_id}
    assert choice["free"] and choice["repeat"]
    p1 = eng.state.player_by_id("p1")
    eng.play_resolution_card(p1, made[1])  # the land
    assert made[1].zone == Zone.BATTLEFIELD
    eng.resolve_until_stable()
    eng.play_resolution_card(p1, made[0])  # the spell, for free (pool empty after the Ultimatum was paid)
    eng.resolve_until_stable()
    assert made[0] in p1.graveyard
    # the other pile stays exiled, the card under the five is untouched
    assert {o.name for o in p1.exile} == {made[2].name, made[3].name, made[4].name}
    assert p1.library[-1] is below and _bystander(eng) == by


def test_brilliant_ultimatum_second_pile_can_be_chosen_and_declined():
    eng = game(library=0)
    made = _stack(eng, "p1", "Land", "Land", "Land", "Sorcery 2", "Land", "Land")
    cast(eng, card(eng, "Brilliant Ultimatum", zone=Zone.HAND))
    _answer(eng, "p2", "decline")  # an empty first pile: the whole batch is the second
    _answer(eng, "p1", "second")
    choice = eng.state.resolution_play_choice
    assert len(choice["instance_ids"]) == 5
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert len(eng.state.player_by_id("p1").exile) == 5  # nothing played: the cards stay exiled


def test_truth_or_tale_one_card_of_the_chosen_pile_to_hand_all_others_to_the_bottom():
    eng = game(library=0)
    made = _stack(eng, "p1", "Land", "Creature", "Instant 1", "Sorcery 1", "Land", "Creature")
    below = made[5]
    by = _bystander(eng)
    cast(eng, card(eng, "Truth or Tale", zone=Zone.HAND))
    p1 = eng.state.player_by_id("p1")
    _answer(eng, "p1", str(made[0].instance_id))
    _answer(eng, "p1", str(made[1].instance_id))
    _answer(eng, "p1", "decline")
    assert eng.state.pending_choice["player_id"] == "p2"  # the opponent chooses
    _answer(eng, "p2", "second")  # made[2], made[3], made[4]
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p1" and {o["instance_id"] for o in choice["options"] if "instance_id" in o} == {
        made[2].instance_id, made[3].instance_id, made[4].instance_id}
    _answer(eng, "p1", str(made[3].instance_id))
    for _ in range(8):  # the order of the four cards that go down is the controller's
        if eng.state.pending_choice is None:
            break
        eng.resolve_pending_choice(str(eng.state.pending_choice["options"][0]["id"]))
    assert made[3] in p1.hand and sum(1 for o in p1.hand if o in made) == 1
    assert {o.name for o in p1.library[:4]} == {made[0].name, made[1].name, made[2].name, made[4].name}
    assert p1.library[-1] is below and _bystander(eng) == by


def test_truth_or_tale_an_empty_chosen_pile_sends_everything_to_the_bottom():
    eng = game(library=0)
    made = _stack(eng, "p1", "Land", "Creature", "Instant 1", "Sorcery 1", "Land", "Creature")
    cast(eng, card(eng, "Truth or Tale", zone=Zone.HAND))
    p1 = eng.state.player_by_id("p1")
    for o in made[:5]:
        _answer(eng, "p1", str(o.instance_id))
    _answer(eng, "p2", "second")  # every card went to the first pile; the second is empty
    for _ in range(8):
        if eng.state.pending_choice is None:
            break
        eng.resolve_pending_choice(str(eng.state.pending_choice["options"][0]["id"]))
    assert not [o for o in p1.hand if o in made]
    assert {o.name for o in p1.library[:5]} == {o.name for o in made[:5]} and p1.library[-1] is made[5]


def _aura_game():
    eng = game(library=3)
    return eng, card(eng, "Pacifism", zone=Zone.HAND), card(eng, "Pacifism", zone=Zone.LIBRARY)


def _accept_may(eng):
    """"you may search": accept the optional trigger, then the search choice is pending."""
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.resolve_pending_choice("do")


def _name_zone(eng, zone):
    """RULE 701.23a / PAR-292 M28: a search over several zones first asks which of them to look through."""
    assert eng.state.pending_choice["kind"] == "search_zones"
    eng.resolve_pending_choice(zone.value)


def _pick_found(eng, wanted):
    if eng.state.pending_choice and eng.state.pending_choice["kind"] == "trigger_target":
        _accept_may(eng)
    if eng.state.pending_choice and eng.state.pending_choice["kind"] == "search_zones":
        _name_zone(eng, wanted.zone)
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == "p1"
    eng.resolve_pending_choice(str(wanted.instance_id))
    eng.resolve_until_stable()


def test_boonweaver_giant_puts_a_found_aura_onto_the_battlefield_attached_to_itself():
    eng, in_hand, in_library = _aura_game()
    bystander_aura = card(eng, "Pacifism", player="p2", zone=Zone.HAND)
    giant = put_on_battlefield(eng, "Boonweaver Giant")
    _pick_found(eng, in_hand)  # hand, graveyard and library are all searched
    assert in_hand.zone == Zone.BATTLEFIELD and in_hand.attached_to == giant.instance_id
    assert in_library.zone == Zone.LIBRARY and bystander_aura.zone == Zone.HAND  # nothing else moved


def test_boonweaver_giant_finds_the_aura_in_the_library_too():
    eng, in_hand, in_library = _aura_game()
    in_hand.owner_id = "p1"
    eng.state.player_by_id("p1").hand.remove(in_hand)
    giant = put_on_battlefield(eng, "Boonweaver Giant")
    _pick_found(eng, in_library)
    assert in_library.zone == Zone.BATTLEFIELD and in_library.attached_to == giant.instance_id


def test_runed_crown_attaches_a_found_rune_to_the_equipment():
    eng = game(library=3)
    rune = card(eng, "Rune of Speed", zone=Zone.GRAVEYARD)
    plain = card(eng, "Pacifism", zone=Zone.HAND)  # an Aura, but not a rune
    crown = put_on_battlefield(eng, "Runed Crown")
    _accept_may(eng)
    _name_zone(eng, Zone.GRAVEYARD)
    options = [o for o in eng.state.pending_choice["options"] if "instance_id" in o]
    assert [o["instance_id"] for o in options] == [rune.instance_id]
    _pick_found(eng, rune)
    assert rune.zone == Zone.BATTLEFIELD and rune.attached_to == crown.instance_id and plain.zone == Zone.HAND


def test_brilliant_ultimatum_a_played_land_uses_the_land_drop():
    eng = game(library=0)
    made = _stack(eng, "p1", "Land", "Land", "Sorcery 1", "Land", "Land", "Land")
    cast(eng, card(eng, "Brilliant Ultimatum", zone=Zone.HAND))
    _answer(eng, "p2", str(made[0].instance_id))
    _answer(eng, "p2", str(made[1].instance_id))
    _answer(eng, "p2", "decline")
    _answer(eng, "p1", "first")
    p1 = eng.state.player_by_id("p1")
    eng.play_resolution_card(p1, made[0])
    eng.resolve_until_stable()
    assert p1.lands_played_this_turn == 1  # RULE 305.2: the land play is the turn's land drop
    with pytest.raises(ValueError):
        eng.play_resolution_card(p1, made[1])  # no second land this turn
