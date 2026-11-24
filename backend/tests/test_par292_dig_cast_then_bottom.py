"""PAR-292 M20: "<that player | target opponent | you> exile[s] / reveal cards from the top of <their | your> library until
<quality>. You may cast that card without paying its mana cost. Then put the exiled cards that weren't cast this way on the
bottom of <that | their | your> library in a random order." (RULE 608.2g cast during resolution, 118.9 free cast, 401.4
random bottom, 108.3 ownership stays with the library owner).

Parsed from real oracle wording, then run on a real engine with bystanders: only the dug library is touched, only the
ability's controller may cast the hit and only for free, an uncast hit goes down with the rest, a land is passed over."""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle

from tests.support.deck_batch import activate, attack, card, filler, game, stack_library
from tests.test_par292_dynamic_search_qualities import _modeled

CLAIMED = ["Chaos Wand", "Dazzling Sphinx", "Gríma, Saruman's Footman", "Treasure Keeper", "Plargg, Dean of Chaos"]


@pytest.mark.parametrize("name", CLAIMED)
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _probe(text):
    return parse_oracle(Card(id="t", name="Probe", type_line="Artifact", oracle_text=text))


_WAND = ("{4}, {T}: Target opponent exiles cards from the top of their library until they exile an instant or sorcery "
         "card. You may cast that card without paying its mana cost. Then put the exiled cards that weren't cast this "
         "way on the bottom of that library in a random order.")


@pytest.mark.parametrize("text", [
    # "any order" is the player's own sequence (BUG-80), not the engine's random bottom
    _WAND.replace("in a random order", "in any order"),
    # paying life / mana is not the free cast
    _WAND.replace("without paying its mana cost", "by paying life equal to its mana value rather than paying its mana cost"),
    # the bottom must be the dug library: "your" library when an opponent dug is another library
    _WAND.replace("of that library", "of your library"),
    # a bare "that player" with no trigger or target naming one
    "{4}, {T}: " + _WAND.split(": ", 1)[1].replace("Target opponent exiles", "That player exiles"),
    # a reveal that does not say where the revealed cards go
    "{4}, {T}: Reveal cards from the top of your library until you reveal a nonland card with mana value 3 or less. "
    "You may cast that card without paying its mana cost.",
    # a conditional cast is not a plain free cast
    "Whenever ~ attacks, exile cards from the top of your library until you exile a nonland card. You may cast the "
    "exiled card without paying its mana cost if it's a spell with mana value less than or equal to ~'s power. Put the "
    "exiled cards not cast this way on the bottom of your library in a random order.",
])
def test_near_misses_stay_unclaimed(text):
    assert not _probe(text).modeled


def _stack(eng, player, *kinds):
    """``player``'s library, first kind = top; every card is a vanilla filler named by its position."""
    made = [filler(eng, f"{player}-{i}-{k.split()[0]}", type_line=k, player=player, zone=Zone.LIBRARY,
                   mv=int(k.split()[-1]) if k.split()[-1].isdigit() else 0,
                   **({"power": 1, "toughness": 1} if "Creature" in k else {}))
            for i, k in enumerate(kinds)]
    stack_library(eng, player, *reversed(made))
    return made


def _wand_game():
    eng = game(players=3, library=3)
    wand = card(eng, "Chaos Wand")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 4})
    return eng, wand


def _names(eng, player, zone):
    return [o.name for o in getattr(eng.state.player_by_id(player), zone)]


def test_chaos_wand_offers_the_hit_to_its_controller_for_free_and_bottoms_the_rest():
    eng, wand = _wand_game()
    made = _stack(eng, "p2", "Land", "Creature", "Instant 3", "Sorcery")
    before = {p: list(eng.state.player_by_id(p).library) for p in ("p1", "p3")}
    activate(eng, wand, 0, targets=[eng.state.player_by_id("p2")])
    choice = eng.state.resolution_play_choice
    assert choice["player_id"] == "p1" and choice["instance_ids"] == [made[2].instance_id]  # only the caster, only the hit
    assert choice["free"] and made[2].zone == Zone.EXILE
    p1 = eng.state.player_by_id("p1")
    eng.play_resolution_card(p1, made[2])
    eng.resolve_until_stable()
    p2 = eng.state.player_by_id("p2")
    assert made[2] in p2.graveyard and made[2].owner_id == "p2"  # the cast spell resolved; its owner's graveyard  # no mana was left to pay its 3
    assert {o.name for o in p2.library[:2]} == {made[0].name, made[1].name}  # land and creature went to the bottom
    assert p2.library[-1] is made[3]  # the card under the hit was never touched
    assert not [o for o in p2.exile if o in made]
    assert {p: list(eng.state.player_by_id(p).library) for p in ("p1", "p3")} == before  # bystanders untouched


def test_an_uncast_hit_goes_to_the_bottom_with_the_rest():
    eng, wand = _wand_game()
    made = _stack(eng, "p2", "Land", "Sorcery", "Creature")
    activate(eng, wand, 0, targets=[eng.state.player_by_id("p2")])
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    p2 = eng.state.player_by_id("p2")
    assert {o.name for o in p2.library[:2]} == {made[0].name, made[1].name}  # the hit joined the bottom
    assert p2.library[-1] is made[2] and not p2.exile and not p2.graveyard


def test_with_no_hit_the_whole_library_is_exiled_and_put_back_on_the_bottom():
    eng, wand = _wand_game()
    made = _stack(eng, "p2", "Land", "Creature")
    p2 = eng.state.player_by_id("p2")
    p2.library[:] = made[::-1]  # only these two cards
    activate(eng, wand, 0, targets=[p2])
    assert eng.state.resolution_play_choice is None and eng.state.pending_choice is None
    assert sorted(o.name for o in p2.library) == sorted(o.name for o in made) and not p2.exile


def test_dazzling_sphinx_digs_the_player_it_hurt_not_the_other_opponent():
    eng = game(players=3, library=3)
    sphinx = card(eng, "Dazzling Sphinx")
    sphinx.summoning_sick = False
    made = _stack(eng, "p2", "Land", "Sorcery", "Creature")
    other = _stack(eng, "p3", "Sorcery", "Instant")
    attack(eng, [sphinx], defender=eng.state.player_by_id("p2"))
    eng._step_combat_damage()
    eng.resolve_until_stable()
    choice = eng.state.resolution_play_choice
    assert choice is not None and choice["player_id"] == "p1" and choice["instance_ids"] == [made[1].instance_id]
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert [o.name for o in eng.state.player_by_id("p3").library[-2:]] == [o.name for o in reversed(other)]
    assert made[1] in eng.state.player_by_id("p2").library  # declined: back under their library


def test_plargg_reveal_dig_passes_over_lands_and_expensive_cards_and_casts_for_free():
    eng = game(players=2, library=3)
    plargg = card(eng, "Plargg, Dean of Chaos")
    plargg.summoning_sick = False
    made = _stack(eng, "p1", "Land", "Sorcery 5", "Legendary Creature 2", "Instant 2", "Sorcery 1")
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"R": 5})
    p2_library = list(eng.state.player_by_id("p2").library)
    plargg_dig = 1  # {T}, discard a card: draw is ability 0
    activate(eng, plargg, plargg_dig)
    choice = eng.state.resolution_play_choice
    # nonlegendary, nonland, mana value <= 3: the land, the 5-drop and the legendary creature are passed over
    assert choice is not None and choice["instance_ids"] == [made[3].instance_id]
    eng.play_resolution_card(p1, made[3])
    eng.resolve_until_stable()
    assert made[3] in p1.graveyard
    assert {o.name for o in p1.library[:3]} == {o.name for o in made[:3]}  # passed-over cards went to the bottom
    assert p1.library[-1] is made[4]  # below the hit: untouched
    assert list(eng.state.player_by_id("p2").library) == p2_library
