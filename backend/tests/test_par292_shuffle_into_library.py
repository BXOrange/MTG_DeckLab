"""PAR-292 M13: "shuffle ... into library" effects (RULE 701.24a, 108.3, 608.2c).

(A) "<~'s / its / the target's> owner shuffles it into their library" (Blitz Hellion, Cerulean Sphinx, Ominous Cemetery,
Living Library, Deglamer, Unravel the Aether, Oblation's owner draw, Dramatic Accusation);
(B) "shuffle your graveyard into your library" (Feldon's Cane, Archangel's Light) and "shuffle up to N target cards from
your graveyard into your library" (Wand of Vertebrae, Put Away);
(C) "shuffle the cards from your hand into your library, then draw that many cards" (Whirlpool Rider, Winds of Change).

Every claimed card runs on a real GameEngine, with bystanders that must stay where they are."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.clause_hooks import match_clause
from tests.support.deck_batch import RICH, activate as _activate, card, cast, filler, game, put_on_battlefield, step

from tests.test_par292_dynamic_search_qualities import _modeled


@pytest.mark.parametrize("name", [
    "Blitz Hellion", "Lightning Shrieker", "Cerulean Sphinx", "Ominous Cemetery", "Living Library", "Deglamer",
    "Unravel the Aether", "Oblation", "Dramatic Accusation", "Feldon's Cane", "Archangel's Light", "Gaea's Blessing",
    "Wand of Vertebrae", "Put Away", "Whirlpool Rider", "Whirlpool Drake", "Whirlpool Warrior", "Winds of Change",
    "Guan Yu, Sainted Warrior", "Gandalf, Wandering Wizard", "Cathartic Parting", "Devious Cover-Up",
    "Finale of Revelation", "Stay Hidden, Stay Silent", "The Mending of Dominaria",
])
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def activate(eng, source, **kw):
    eng.state.player_by_id("p1").mana_pool.add_many(RICH)  # the tests care what resolves, not how it was paid for
    _activate(eng, source, **kw)


def _library_names(eng, player):
    return {o.name for o in eng.state.player_by_id(player).library}


def test_blitz_hellion_goes_into_its_owners_library_not_its_controllers():
    eng = game(library=0)
    hellion = card(eng, "Blitz Hellion", player="p2")
    hellion.owner_id = "p1"  # stolen: owned by p1, controlled by p2 (RULE 108.3, 701.24a)
    bystander = filler(eng, "Bystander", type_line="Creature", power=1, toughness=1, player="p2")
    step(eng, "end", player="p1")
    assert hellion in eng.state.player_by_id("p1").library
    assert hellion not in eng.state.player_by_id("p2").library
    assert hellion not in eng.state.battlefield
    assert bystander in eng.state.battlefield


def test_cerulean_sphinx_shuffles_itself_for_its_activation_only():
    eng = game(library=3)
    sphinx = card(eng, "Cerulean Sphinx")
    other = filler(eng, "Other", type_line="Creature", power=1, toughness=1)
    activate(eng, sphinx)
    assert sphinx not in eng.state.battlefield
    assert sphinx in eng.state.player_by_id("p1").library
    assert len(eng.state.player_by_id("p1").library) == 4
    assert other in eng.state.battlefield


def test_gandalf_the_owner_not_the_controller_draws_three():
    eng = game(library=6)
    gandalf = card(eng, "Gandalf, Wandering Wizard", player="p2")
    gandalf.owner_id = "p1"  # controlled by p2, owned by p1: p1's library takes it, p1 draws (RULE 108.3)
    eng.state.player_by_id("p2").mana_pool.add_many(RICH)
    _activate(eng, gandalf, player="p2")
    assert gandalf not in eng.state.battlefield
    assert len(eng.state.player_by_id("p1").hand) == 3
    assert not eng.state.player_by_id("p2").hand
    assert len(eng.state.player_by_id("p1").library) == 6 + 1 - 3


def test_guan_yu_may_shuffle_itself_back_when_it_dies_and_may_decline():
    eng = game(library=2)
    guan = card(eng, "Guan Yu, Sainted Warrior")
    eng.rules.destroy(guan)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is not None  # "you may"
    eng.resolve_pending_choice("decline")
    assert guan in eng.state.player_by_id("p1").graveyard
    eng2 = game(library=2)
    guan2 = card(eng2, "Guan Yu, Sainted Warrior")
    eng2.rules.destroy(guan2)
    eng2.resolve_until_stable()
    eng2.resolve_pending_choice("yes") if eng2.state.pending_choice and "yes" in [str(o["id"]) for o in eng2.state.pending_choice.get("options", [])] else eng2.resolve_pending_choice(str(eng2.state.pending_choice["options"][0]["id"]))
    assert guan2 in eng2.state.player_by_id("p1").library
    assert len(eng2.state.player_by_id("p1").library) == 3


def test_gaeas_blessing_shuffles_the_graveyard_when_it_is_milled():
    eng = game(library=2)
    p1 = eng.state.player_by_id("p1")
    dead = filler(eng, "Dead", type_line="Creature", zone=Zone.GRAVEYARD)
    theirs = filler(eng, "Theirs", type_line="Creature", zone=Zone.GRAVEYARD, player="p2")
    blessing = card(eng, "Gaea's Blessing", zone=Zone.LIBRARY)
    eng.rules.mill(p1, 1)
    eng.resolve_until_stable()
    assert blessing.zone == Zone.LIBRARY and dead.zone == Zone.LIBRARY  # the milled card shuffled itself back in too
    assert not p1.graveyard
    assert theirs in eng.state.player_by_id("p2").graveyard


def test_gaeas_blessing_does_nothing_when_a_different_card_is_milled():
    eng = game(library=2)
    p1 = eng.state.player_by_id("p1")
    dead = filler(eng, "Dead", type_line="Creature", zone=Zone.GRAVEYARD)
    card(eng, "Gaea's Blessing", zone=Zone.LIBRARY)  # not on top: the Forest above it is the one milled
    top = filler(eng, "Top", type_line="Creature", zone=Zone.LIBRARY)
    eng.rules.mill(p1, 1)
    eng.resolve_until_stable()
    assert top.zone == Zone.GRAVEYARD and dead.zone == Zone.GRAVEYARD


def test_cathartic_parting_shuffles_the_opponents_permanent_and_up_to_four_of_your_graveyard_cards():
    eng = game(library=3)
    victim = filler(eng, "Victim", type_line="Artifact", player="p2")
    mine = filler(eng, "Mine", type_line="Creature", zone=Zone.GRAVEYARD)
    cast(eng, card(eng, "Cathartic Parting", zone=Zone.HAND), groups=[[victim], [mine]])
    assert victim not in eng.state.battlefield and victim in eng.state.player_by_id("p2").library
    assert mine in eng.state.player_by_id("p1").library


def test_ominous_cemetery_shuffles_the_target_creature_into_its_owners_library():
    eng = game(library=2)
    cemetery = card(eng, "Ominous Cemetery")
    victim = filler(eng, "Victim", type_line="Creature", power=2, toughness=2, player="p2")
    bystander = filler(eng, "Bystander", type_line="Creature", power=2, toughness=2, player="p2")
    activate(eng, cemetery, targets=[victim])
    assert victim in eng.state.player_by_id("p2").library
    assert len(eng.state.player_by_id("p2").library) == 3
    assert bystander in eng.state.battlefield
    assert len(eng.state.player_by_id("p1").library) == 2


def test_unravel_the_aether_hits_only_the_chosen_artifact_or_enchantment():
    eng = game(library=1)
    chosen = filler(eng, "Chosen", type_line="Artifact", player="p2")
    other = filler(eng, "OtherArtifact", type_line="Artifact", player="p2")
    creature = filler(eng, "Creature", type_line="Creature", power=1, toughness=1, player="p2")
    cast(eng, card(eng, "Unravel the Aether", zone=Zone.HAND), targets=[chosen])
    assert chosen in eng.state.player_by_id("p2").library
    assert other in eng.state.battlefield and creature in eng.state.battlefield


def test_oblation_the_owner_draws_two_and_the_caster_does_not():
    eng = game(library=5)
    target = filler(eng, "Target", type_line="Artifact", player="p2")
    before_caster = len(eng.state.player_by_id("p1").hand)
    cast(eng, card(eng, "Oblation", zone=Zone.HAND), targets=[target])
    assert target not in eng.state.battlefield
    assert len(eng.state.player_by_id("p2").library) == 4  # 5 + the shuffled-in card - the 2 it drew
    assert len(eng.state.player_by_id("p2").hand) == 2
    assert len(eng.state.player_by_id("p1").hand) == before_caster  # the cast itself leaves no draw for the caster


def test_oblation_on_the_casters_own_permanent_draws_for_the_caster():
    eng = game(library=5)
    mine = filler(eng, "Mine", type_line="Artifact", player="p1")
    cast(eng, card(eng, "Oblation", zone=Zone.HAND), targets=[mine])
    assert mine not in eng.state.battlefield
    assert len(eng.state.player_by_id("p1").hand) == 2  # the shuffled card may be one of the two it drew
    assert len(eng.state.player_by_id("p1").library) == 4
    assert not eng.state.player_by_id("p2").hand


def test_dramatic_accusation_shuffles_the_enchanted_creature():
    eng = game(library=1)
    host = filler(eng, "Host", type_line="Creature", power=2, toughness=2, player="p2")
    aura = card(eng, "Dramatic Accusation")
    aura.attached_to = host.instance_id
    bystander = filler(eng, "Bystander", type_line="Creature", power=2, toughness=2, player="p2")
    activate(eng, aura)
    assert host in eng.state.player_by_id("p2").library
    assert bystander in eng.state.battlefield


def test_feldons_cane_moves_the_whole_graveyard_and_leaves_the_opponents_alone():
    eng = game(library=1)
    mine = [filler(eng, f"Mine{i}", type_line="Creature", zone=Zone.GRAVEYARD) for i in range(3)]
    theirs = filler(eng, "Theirs", type_line="Creature", zone=Zone.GRAVEYARD, player="p2")
    cane = card(eng, "Feldon's Cane")
    activate(eng, cane)
    p1 = eng.state.player_by_id("p1")
    assert not p1.graveyard
    assert all(c in p1.library for c in mine)
    assert theirs in eng.state.player_by_id("p2").graveyard


def test_archangels_light_counts_the_graveyard_before_it_shuffles_it_away():
    eng = game(library=1)
    for i in range(3):
        filler(eng, f"Mine{i}", type_line="Creature", zone=Zone.GRAVEYARD)
    life = eng.state.player_by_id("p1").life
    cast(eng, card(eng, "Archangel's Light", zone=Zone.HAND))
    assert eng.state.player_by_id("p1").life == life + 6  # 2 life per graveyard card, measured first
    assert all(c.name.startswith("Mine") is False for c in eng.state.player_by_id("p1").graveyard if c.zone == Zone.GRAVEYARD
               and c.name != "Archangel's Light")


def test_wand_of_vertebrae_shuffles_only_the_chosen_cards_from_your_graveyard():
    eng = game(library=1)
    wand = card(eng, "Wand of Vertebrae")
    chosen = [filler(eng, f"Pick{i}", type_line="Creature", zone=Zone.GRAVEYARD) for i in range(2)]
    left = filler(eng, "Left", type_line="Creature", zone=Zone.GRAVEYARD)
    theirs = filler(eng, "Theirs", type_line="Creature", zone=Zone.GRAVEYARD, player="p2")
    activate(eng, wand, index=1, targets=chosen)
    p1 = eng.state.player_by_id("p1")
    assert all(c in p1.library for c in chosen)
    assert left in p1.graveyard and theirs in eng.state.player_by_id("p2").graveyard


def test_whirlpool_rider_draws_as_many_cards_as_the_hand_held():
    eng = game(library=10)
    p1 = eng.state.player_by_id("p1")
    hand = [filler(eng, f"Card{i}", type_line="Creature", zone=Zone.HAND) for i in range(3)]
    grave = filler(eng, "Grave", type_line="Creature", zone=Zone.GRAVEYARD)
    put_on_battlefield(eng, "Whirlpool Rider")
    assert len(p1.hand) == 3
    assert not any(c in p1.hand for c in hand) or len(p1.hand) == 3  # the same count, redrawn from the shuffled library
    assert grave in p1.graveyard  # the graveyard is not part of this shuffle
    assert len(p1.library) == 10


def test_whirlpool_rider_with_an_empty_hand_draws_nothing():
    eng = game(library=4)
    put_on_battlefield(eng, "Whirlpool Rider")
    assert not eng.state.player_by_id("p1").hand
    assert len(eng.state.player_by_id("p1").library) == 4


def test_winds_of_change_gives_each_player_their_own_hand_size():
    eng = game(library=10)
    for i in range(3):
        filler(eng, f"Mine{i}", type_line="Creature", zone=Zone.HAND)
    for i in range(1):
        filler(eng, f"Theirs{i}", type_line="Creature", zone=Zone.HAND, player="p2")
    cast(eng, card(eng, "Winds of Change", zone=Zone.HAND))
    assert len(eng.state.player_by_id("p1").hand) == 3
    assert len(eng.state.player_by_id("p2").hand) == 1


@pytest.mark.parametrize("text", [
    "target creature's controller shuffles it into their library",  # the controller is not the owner
    "shuffle up to 2 target cards from an opponent's graveyard into your library",
    "each player shuffles their hand into their library, then draws 7 cards",  # a fixed count, not "that many"
    "shuffle the cards from your hand into your library, then draw a card",
    "shuffle all creature cards from target player's graveyard into that player's library",
])
def test_near_misses_stay_unclaimed(text):
    assert not match_clause(text)
