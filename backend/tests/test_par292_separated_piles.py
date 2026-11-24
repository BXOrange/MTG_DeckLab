"""PAR-292 M22: objects in a public zone separated into two piles (RULE 700.3, 101.4, 608.2c, 701.8, 701.21).

Do or Die, Liliana of the Veil's -6, Make an Example, Death or Glory, Bend or Break, Boneyard Parley, Split the Spoils.
Run on a real engine with bystanders: the right player separates and chooses, each pile meets its printed fate, the other
players' objects stay untouched, empty piles are legal."""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle

from tests.support.deck_batch import activate, card, cast, filler, game
from tests.test_par292_dynamic_search_qualities import _modeled

CLAIMED = ["Do or Die", "Liliana of the Veil", "Make an Example", "Death or Glory", "Bend or Break", "Boneyard Parley",
           "Split the Spoils"]


@pytest.mark.parametrize("name", CLAIMED)
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _probe(text, type_line="Sorcery"):
    return parse_oracle(Card(id="t", name="Probe", type_line=type_line, oracle_text=text))


@pytest.mark.parametrize("text", [
    # the pile fate must be a modeled one
    "Separate all creatures target player controls into two piles. Put all creatures in the pile of that player's choice "
    "on top of their library.",
    # three piles, a random pile (Whims of the Fates) is another mechanism
    "Starting with you, each player separates all permanents they control into three piles. "
    "Then each player chooses one of their piles at random and sacrifices those permanents.",
    # the no-regeneration rider only qualifies a destruction, not a sacrifice
    "Separate all creatures target player controls into two piles. That player sacrifices all creatures in the pile of "
    "their choice. They can't be regenerated.",
    # the separated cards must be exiled by this spell
    "Exile up to five target creature cards from graveyards. You separate those cards into two piles. "
    "Put all cards from the pile of your choice onto the battlefield under your control and the rest into their owners' graveyards.",
    # only the printed chooser words
    "Each opponent separates the creatures they control into two piles. For each opponent, that player chooses one of their piles. "
    "Each opponent sacrifices the creatures in their chosen pile.",
])
def test_near_misses_stay_unmodeled(text):
    assert not _probe(text).modeled


def _creatures(eng, player, *names, **kw):
    return [filler(eng, n, player=player, power=1, toughness=1, **kw) for n in names]


def _answer(eng, who, option):
    assert eng.state.pending_choice["player_id"] == who
    eng.resolve_pending_choice(option)


def _zone_names(eng, player, zone):
    return sorted(o.name for o in getattr(eng.state.player_by_id(player), zone))


def _battlefield(eng, player):
    return sorted(o.name for o in eng.state.battlefield if o.controller_id == player)


def test_do_or_die_caster_separates_target_chooses_destroyed_pile():
    eng = game()
    a, b, c = _creatures(eng, "p2", "A", "B", "C")
    mine = _creatures(eng, "p1", "Mine")
    cast(eng, card(eng, "Do or Die", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    _answer(eng, "p1", str(a.instance_id))
    _answer(eng, "p1", "decline")
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p2"  # the target player chooses
    assert [o["label"] for o in choice["options"]] == ["A", "B, C"]
    _answer(eng, "p2", "second")
    assert _battlefield(eng, "p2") == ["A"]
    assert _zone_names(eng, "p2", "graveyard") == ["B", "C"]
    assert _battlefield(eng, "p1") == ["Mine"] and mine[0].zone == Zone.BATTLEFIELD  # the caster's own board is untouched


def test_do_or_die_empty_pile_is_legal():
    eng = game()
    _creatures(eng, "p2", "A", "B")
    cast(eng, card(eng, "Do or Die", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    _answer(eng, "p1", "decline")  # nothing in the first pile
    assert [o["label"] for o in eng.state.pending_choice["options"]] == ["Leerer Stapel", "A, B"]
    _answer(eng, "p2", "first")  # the empty pile is destroyed: nothing happens
    assert _battlefield(eng, "p2") == ["A", "B"]


def test_do_or_die_regeneration_and_indestructible():
    eng = game()
    shielded, hardy, plain = _creatures(eng, "p2", "Shielded", "Hardy", "Plain")
    hardy.card.keywords = ["Indestructible"]
    eng.recompute_continuous_effects()
    eng.rules.regenerate(shielded)  # RULE 701.19: "they can't be regenerated" ignores the shield
    cast(eng, card(eng, "Do or Die", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    for obj in (shielded, hardy):
        _answer(eng, "p1", str(obj.instance_id))
    _answer(eng, "p1", str(plain.instance_id))
    _answer(eng, "p2", "first")
    assert _battlefield(eng, "p2") == ["Hardy"]  # RULE 702.12b: indestructible survives; the shield does not save Shielded
    assert _zone_names(eng, "p2", "graveyard") == ["Plain", "Shielded"]


def test_liliana_minus_six_sacrifices_the_chosen_permanents_of_the_target():
    eng = game(players=3)
    a, b = _creatures(eng, "p2", "A", "B")
    land = filler(eng, "Their Land", type_line="Land", player="p2")
    other = _creatures(eng, "p3", "Bystander")[0]
    liliana = card(eng, "Liliana of the Veil")
    liliana.counters["loyalty"] = 6
    activate(eng, liliana, 2, targets=[eng.state.player_by_id("p2")])
    _answer(eng, "p1", str(a.instance_id))
    _answer(eng, "p1", str(land.instance_id))
    _answer(eng, "p1", "decline")
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p2" and len(choice["options"]) == 2
    _answer(eng, "p2", "first")
    assert _battlefield(eng, "p2") == ["B"]
    assert _zone_names(eng, "p2", "graveyard") == ["A", "Their Land"]
    assert other.zone == Zone.BATTLEFIELD


def test_make_an_example_each_opponent_separates_and_the_caster_chooses():
    eng = game(players=3)
    _creatures(eng, "p2", "B1", "B2", "B3")
    _creatures(eng, "p3", "C1", "C2")
    mine = _creatures(eng, "p1", "Mine")[0]
    cast(eng, card(eng, "Make an Example", zone=Zone.HAND))
    first = eng.state.pending_choice
    assert first["player_id"] == "p2"  # each opponent separates their own creatures
    _answer(eng, "p2", str(next(o["instance_id"] for o in first["options"] if o.get("name") == "B1")))
    _answer(eng, "p2", "decline")
    assert eng.state.pending_choice["player_id"] == "p1"  # the caster chooses
    assert [o["label"] for o in eng.state.pending_choice["options"]] == ["B1", "B2, B3"]
    _answer(eng, "p1", "second")
    second = eng.state.pending_choice
    assert second["player_id"] == "p3"
    _answer(eng, "p3", "decline")  # an empty first pile
    _answer(eng, "p1", "first")  # the empty pile is the one sacrificed
    assert _battlefield(eng, "p2") == ["B1"] and _battlefield(eng, "p3") == ["C1", "C2"]
    assert _zone_names(eng, "p2", "graveyard") == ["B2", "B3"]
    assert mine.zone == Zone.BATTLEFIELD


def test_make_an_example_with_no_creatures_asks_nothing():
    eng = game()
    cast(eng, card(eng, "Make an Example", zone=Zone.HAND))
    assert eng.state.pending_choice is None


def test_death_or_glory_opponent_chooses_exile_pile_other_returns():
    eng = game()
    dead = [filler(eng, n, type_line="Creature", player="p1", power=1, toughness=1, zone=Zone.GRAVEYARD)
            for n in ("G1", "G2", "G3")]
    theirs = filler(eng, "TheirDead", type_line="Creature", player="p2", power=1, toughness=1, zone=Zone.GRAVEYARD)
    cast(eng, card(eng, "Death or Glory", zone=Zone.HAND))
    _answer(eng, "p1", str(dead[0].instance_id))
    _answer(eng, "p1", "decline")
    assert eng.state.pending_choice["player_id"] == "p2"  # an opponent chooses the pile to exile
    _answer(eng, "p2", "first")
    assert _zone_names(eng, "p1", "exile") == ["G1"]
    assert _battlefield(eng, "p1") == ["G2", "G3"]
    assert theirs.zone == Zone.GRAVEYARD  # an opponent's graveyard is not part of "your graveyard"


def test_bend_or_break_each_player_separates_an_opponent_chooses():
    eng = game()
    mine = [filler(eng, n, type_line="Land", player="p1") for n in ("M1", "M2")]
    theirs = [filler(eng, n, type_line="Land", player="p2") for n in ("T1", "T2")]
    token = filler(eng, "Treasure Land", type_line="Land", player="p1")
    token.is_token = True
    cast(eng, card(eng, "Bend or Break", zone=Zone.HAND))
    _answer(eng, "p1", str(mine[0].instance_id))  # APNAP: the caster's lands first
    _answer(eng, "p1", "decline")
    assert eng.state.pending_choice["player_id"] == "p2"  # the opponent chooses the pile of lands to destroy
    _answer(eng, "p2", "first")
    _answer(eng, "p2", str(theirs[1].instance_id))
    _answer(eng, "p2", "decline")
    assert eng.state.pending_choice["player_id"] == "p1"
    _answer(eng, "p1", "second")
    assert _battlefield(eng, "p1") == ["M2", "Treasure Land"] and _battlefield(eng, "p2") == ["T2"]
    assert mine[1].tapped and theirs[1].tapped and not token.tapped  # the other piles are tapped; tokens aren't separated
    assert _zone_names(eng, "p1", "graveyard") == ["Bend or Break", "M1"]


def test_bend_or_break_picks_the_opponent_when_there_are_several():
    eng = game(players=3)
    filler(eng, "M1", type_line="Land", player="p1")
    cast(eng, card(eng, "Bend or Break", zone=Zone.HAND))
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_pile_divider" and choice["player_id"] == "p1"  # the owner names the opponent
    assert [o["id"] for o in choice["options"]] == ["p2", "p3"]
    _answer(eng, "p1", "p3")
    _answer(eng, "p1", "decline")
    assert eng.state.pending_choice["player_id"] == "p3"


def test_boneyard_parley_exiles_targets_opponent_separates_caster_chooses():
    eng = game()
    mine = filler(eng, "MineDead", type_line="Creature", player="p1", power=2, toughness=2, zone=Zone.GRAVEYARD)
    theirs = filler(eng, "TheirDead", type_line="Creature", player="p2", power=3, toughness=3, zone=Zone.GRAVEYARD)
    extra = filler(eng, "Extra", type_line="Creature", player="p2", power=1, toughness=1, zone=Zone.GRAVEYARD)
    cast(eng, card(eng, "Boneyard Parley", zone=Zone.HAND), targets=[mine, theirs])
    assert eng.state.pending_choice["player_id"] == "p2"  # an opponent separates
    _answer(eng, "p2", str(mine.instance_id))
    _answer(eng, "p2", "decline")
    assert eng.state.pending_choice["player_id"] == "p1"
    _answer(eng, "p1", "second")
    assert _battlefield(eng, "p1") == ["TheirDead"]  # under the caster's control
    assert theirs.controller_id == "p1" and theirs.owner_id == "p2"
    assert _zone_names(eng, "p1", "graveyard") == ["Boneyard Parley", "MineDead"]
    assert extra.zone == Zone.GRAVEYARD  # not targeted


def test_split_the_spoils_opponent_chooses_hand_pile_other_to_graveyard():
    eng = game()
    perms = [filler(eng, n, type_line="Artifact", player="p1", zone=Zone.GRAVEYARD) for n in ("P1", "P2", "P3")]
    cast(eng, card(eng, "Split the Spoils", zone=Zone.HAND), targets=perms)
    _answer(eng, "p1", str(perms[0].instance_id))
    _answer(eng, "p1", "decline")
    assert eng.state.pending_choice["player_id"] == "p2"
    _answer(eng, "p2", "second")
    assert _zone_names(eng, "p1", "hand") == ["P2", "P3"]
    assert _zone_names(eng, "p1", "graveyard") == ["P1", "Split the Spoils"]
    assert _zone_names(eng, "p1", "exile") == []


def test_the_wrong_player_cannot_answer():
    eng = game()
    _creatures(eng, "p2", "A")
    cast(eng, card(eng, "Do or Die", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    with pytest.raises(Exception):
        eng.resolve_pending_choice("decline", player_id="p2")
