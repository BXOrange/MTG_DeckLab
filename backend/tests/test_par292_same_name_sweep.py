"""PAR-292 M16: the Cranial Extraction family's same-name sweep with a name operand taken from a card (RULE 701.19,
701.23, 701.20): Lobotomy / Pick the Brain / Reap Intellect / Shimian Specter pick a card from a revealed hand,
Test of Talents / Invasive Surgery counter a spell, Deicide exiles a God; each then searches the owner's graveyard, hand
and library for cards with that name, exiles them, and the owner shuffles.

Real engine; every test carries bystanders (a card with another name, the caster's own copies)."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game, pick_label
from tests.test_par292_dynamic_search_qualities import _modeled

NAMES = [
    "Lobotomy", "Pick the Brain", "Reap Intellect", "Shimian Specter", "Test of Talents", "Invasive Surgery", "Deicide",
]


@pytest.mark.parametrize("name", NAMES)
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _zone_names(eng, zone, player="p2"):
    return sorted(o.name for o in getattr(eng.state.player_by_id(player), zone))


def _count_shuffles(eng):
    shuffled: list[str] = []
    original = eng.rules.shuffle_library

    def spy(player):
        shuffled.append(player.id)
        return original(player)

    eng.rules.shuffle_library = spy
    return shuffled


def _stock(eng, name="Bolt", other="Other"):
    """p2 owns copies of ``name`` in all three zones plus a differently named bystander in each; p1 has one of its own."""
    for zone in (Zone.GRAVEYARD, Zone.HAND, Zone.LIBRARY):
        filler(eng, name, type_line="Instant", player="p2", zone=zone)
        filler(eng, other, type_line="Instant", player="p2", zone=zone)
    filler(eng, name, type_line="Instant", player="p1", zone=Zone.LIBRARY)
    filler(eng, name, type_line="Instant", player="p1", zone=Zone.GRAVEYARD)


def _p2_casts(eng, spell):
    """p2 puts ``spell`` on the stack on p2's own turn; priority then passes back to p1 (the counter's caster)."""
    eng.state.active_player_index = 1
    eng.state.current_phase, eng.state.current_step = "main", "main1"
    eng.state.player_by_id("p2").mana_pool.add_many({"C": 5, "R": 5})
    eng.cast_spell(eng.state.player_by_id("p2"), spell)
    eng.state.active_player_index = 0


def _answer_search(eng, take):
    """Answer the sweep's search choices: take every offered card when ``take`` else decline."""
    for _ in range(12):
        choice = eng.state.pending_choice
        if choice is None:
            return
        assert choice["kind"] == "search" and choice["player_id"] == "p1" and choice["library_owner_id"] == "p2"
        options = [o for o in choice["options"] if o["id"] != "decline"]
        eng.resolve_pending_choice(str(options[0]["id"]) if options and take else "decline")


def _pick_card(eng, name):
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects" and choice["player_id"] == "p1"
    option = next(o for o in choice["options"] if o["label"] == name)
    eng.resolve_pending_choice(str(option["id"]))


def test_lobotomy_exiles_every_copy_of_the_chosen_card_and_shuffles():
    eng = game(library=0)
    _stock(eng)
    filler(eng, "Forest", type_line="Basic Land — Forest", player="p2", zone=Zone.HAND)
    shuffled = _count_shuffles(eng)
    cast(eng, card(eng, "Lobotomy", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    labels = {o["label"] for o in eng.state.pending_choice["options"]}
    assert "Forest" not in labels and {"Bolt", "Other"} <= labels  # RULE: "other than a basic land card"
    _pick_card(eng, "Bolt")
    _answer_search(eng, take=True)
    assert _zone_names(eng, "exile") == ["Bolt", "Bolt", "Bolt"]
    for zone in ("graveyard", "hand", "library"):
        assert "Bolt" not in _zone_names(eng, zone)
        assert "Other" in _zone_names(eng, zone)
    # the caster's own copies are not the searched player's cards
    assert _zone_names(eng, "library", "p1") == ["Bolt"] and "Bolt" in _zone_names(eng, "graveyard", "p1")
    assert shuffled == ["p2"]  # the library owner shuffles, once


def test_all_cards_leaves_the_hidden_copies_only_when_the_searcher_declines_but_the_graveyard_is_forced():
    eng = game(library=0)
    _stock(eng)
    cast(eng, card(eng, "Lobotomy", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    _pick_card(eng, "Bolt")
    _answer_search(eng, take=False)
    # RULE 701.23b: the public graveyard copy has to be found; the quality search may fail to find hidden cards.
    assert _zone_names(eng, "graveyard") == ["Other"]
    assert _zone_names(eng, "hand") == ["Bolt", "Other"] and _zone_names(eng, "library") == ["Bolt", "Other"]


def test_search_choice_belongs_to_the_caster_and_the_opponent_view_does_not_show_it():
    from mtg_analyzer.services.game_session import GameSession
    eng = game(library=0)
    _stock(eng)
    cast(eng, card(eng, "Lobotomy", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    _pick_card(eng, "Bolt")
    choice = eng.state.pending_choice
    assert choice["kind"] == "search" and choice["player_id"] == "p1"
    session = GameSession(eng)
    theirs = session.view(perspective="p2")["state"].get("pending_choice")
    assert not theirs or not theirs.get("options")  # what p1 is offered from p2's hidden zones is not p2-visible chatter


def test_pick_the_brain_exiles_the_pick_and_sweeps_only_with_delirium():
    for delirium in (False, True):
        eng = game(library=0)
        _stock(eng)
        if delirium:
            for kind in ("Creature", "Land", "Artifact", "Enchantment"):
                filler(eng, f"{kind} card", type_line=kind, player="p1", zone=Zone.GRAVEYARD)
        shuffled = _count_shuffles(eng)
        cast(eng, card(eng, "Pick the Brain", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
        _pick_card(eng, "Bolt")
        _answer_search(eng, take=True)
        if delirium:
            assert _zone_names(eng, "exile") == ["Bolt", "Bolt", "Bolt"] and shuffled == ["p2"]
        else:
            assert _zone_names(eng, "exile") == ["Bolt"] and shuffled == []
            assert _zone_names(eng, "graveyard") == ["Bolt", "Other"] and _zone_names(eng, "library") == ["Bolt", "Other"]
        assert _zone_names(eng, "library", "p1") == ["Bolt"]


def test_reap_intellect_sweeps_each_exiled_name_with_one_shuffle():
    eng = game(library=0)
    _stock(eng)
    _stock(eng, "Alpha", "Beta")
    filler(eng, "Forest", type_line="Basic Land — Forest", player="p2", zone=Zone.HAND)
    shuffled = _count_shuffles(eng)
    cast(eng, card(eng, "Reap Intellect", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")], x=2)
    choice = eng.state.pending_choice
    assert "Forest" not in {o["label"] for o in choice["options"]}  # nonland cards only
    _pick_card(eng, "Bolt")
    if eng.state.pending_choice and eng.state.pending_choice["kind"] == "choose_objects":
        _pick_card(eng, "Alpha")
    _answer_search(eng, take=True)
    assert _zone_names(eng, "exile") == ["Alpha", "Alpha", "Alpha", "Bolt", "Bolt", "Bolt"]
    assert "Beta" in _zone_names(eng, "hand") and "Other" in _zone_names(eng, "hand")
    assert shuffled == ["p2"]


def test_test_of_talents_counters_sweeps_and_draws_for_hand_cards_only():
    eng = game(library=6)
    # p2 casts a sorcery; copies of it sit in p2's graveyard, hand (two) and library.
    for zone in (Zone.GRAVEYARD, Zone.HAND, Zone.HAND, Zone.LIBRARY):
        filler(eng, "Burn", type_line="Sorcery", player="p2", zone=zone)
    filler(eng, "Other", type_line="Sorcery", player="p2", zone=Zone.HAND)
    for _ in range(3):
        filler(eng, "Draw fodder", type_line="Sorcery", player="p2", zone=Zone.LIBRARY)
    spell = filler(eng, "Burn", type_line="Sorcery", player="p2", zone=Zone.HAND)
    _p2_casts(eng, spell)
    hand_before = len(eng.state.player_by_id("p2").hand)
    shuffled = _count_shuffles(eng)
    cast(eng, card(eng, "Test of Talents", zone=Zone.HAND), targets=[spell])
    _answer_search(eng, take=True)
    p2 = eng.state.player_by_id("p2")
    # the countered spell is in the graveyard by then and is found with the graveyard copy, two hand copies and the library one
    assert sorted(o.name for o in p2.exile) == ["Burn"] * 5
    assert all(o.name != "Burn" for o in (*p2.hand, *p2.library, *p2.graveyard))
    # RULE 608.2c: "that player ... draws a card for each card exiled from their hand this way" -- two hand copies.
    assert len(p2.hand) == hand_before - 2 + 2 and shuffled == ["p2"]


def test_invasive_surgery_sweeps_only_with_delirium():
    for delirium in (False, True):
        eng = game(library=0)
        for zone in (Zone.GRAVEYARD, Zone.HAND, Zone.LIBRARY):
            filler(eng, "Burn", type_line="Sorcery", player="p2", zone=zone)
        filler(eng, "Other", type_line="Sorcery", player="p2", zone=Zone.HAND)
        if delirium:
            for kind in ("Creature", "Land", "Artifact", "Enchantment"):
                filler(eng, f"{kind} card", type_line=kind, player="p1", zone=Zone.GRAVEYARD)
        spell = filler(eng, "Burn", type_line="Sorcery", player="p2", zone=Zone.HAND)
        _p2_casts(eng, spell)
        shuffled = _count_shuffles(eng)
        cast(eng, card(eng, "Invasive Surgery", zone=Zone.HAND), targets=[spell])
        _answer_search(eng, take=True)
        p2 = eng.state.player_by_id("p2")
        if delirium:
            # the countered spell itself sits in the graveyard by then, so it is found with the three copies
            assert [o.name for o in p2.exile] == ["Burn"] * 4
            assert shuffled == ["p2"]
        else:
            assert not p2.exile and shuffled == []
            assert sorted(o.name for o in p2.hand) == ["Burn", "Other"] and spell.zone == Zone.GRAVEYARD


def test_deicide_sweeps_only_when_the_exiled_enchantment_is_a_god():
    for god in (False, True):
        eng = game(library=0)
        kind = "Legendary Enchantment Creature — God" if god else "Enchantment"
        body = {"power": 1, "toughness": 1} if god else {}
        target = filler(eng, "Theros", type_line=kind, player="p2", **body)
        for zone in (Zone.GRAVEYARD, Zone.HAND, Zone.LIBRARY):
            filler(eng, "Theros", type_line=kind, player="p2", zone=zone)
            filler(eng, "Other", type_line="Enchantment", player="p2", zone=zone)
        shuffled = _count_shuffles(eng)
        cast(eng, card(eng, "Deicide", zone=Zone.HAND), targets=[target])
        _answer_search(eng, take=True)
        assert target.zone == Zone.EXILE  # the exile is unconditional
        if god:
            assert _zone_names(eng, "exile") == ["Theros"] * 4 and shuffled == ["p2"]
        else:
            assert _zone_names(eng, "exile") == ["Theros"] and shuffled == []
            assert "Theros" in _zone_names(eng, "hand")


def test_shimian_specter_combat_damage_reveals_picks_and_sweeps():
    eng = game(library=0)
    _stock(eng)
    specter = card(eng, "Shimian Specter")
    specter.summoning_sick = False
    from tests.support.deck_batch import attack
    attack(eng, [specter])
    eng._step_combat_damage()
    eng.resolve_until_stable()
    _pick_card(eng, "Bolt")
    _answer_search(eng, take=True)
    assert _zone_names(eng, "exile") == ["Bolt", "Bolt", "Bolt"]
    assert "Other" in _zone_names(eng, "hand")


def test_any_number_leaves_every_copy_when_the_searcher_declines():
    eng = game(library=6)
    for zone in (Zone.GRAVEYARD, Zone.HAND, Zone.LIBRARY):
        filler(eng, "Burn", type_line="Sorcery", player="p2", zone=zone)
    spell = filler(eng, "Burn", type_line="Sorcery", player="p2", zone=Zone.HAND)
    _p2_casts(eng, spell)
    shuffled = _count_shuffles(eng)
    cast(eng, card(eng, "Test of Talents", zone=Zone.HAND), targets=[spell])
    _answer_search(eng, take=False)
    p2 = eng.state.player_by_id("p2")
    # "any number of": the searcher takes none; the countered spell and its graveyard twin stay, nothing drawn, still shuffled
    assert not p2.exile and sorted(o.name for o in p2.graveyard) == ["Burn", "Burn"]
    assert shuffled == ["p2"]


def test_deicide_gate_refuses_a_word_that_is_no_type():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    god = ("exile target enchantment. if the exiled card is a {kind} card, search its controller's graveyard, hand, and "
           "library for any number of cards with the same name as that card and exile them. then that player shuffles.")
    assert parse_effect_body(god.format(kind="god"))
    assert parse_effect_body(god.format(kind="flurb")) is None


@pytest.mark.parametrize("text", [
    # no lead clause supplies a name
    "search that player's graveyard, hand, and library for all cards with the same name as the chosen card and exile them. "
    "then that player shuffles.",
    # a zone is missing
    "target player reveals their hand, then you choose a card other than a basic land card from it. search that player's "
    "hand and library for all cards with the same name as the chosen card and exile them. then that player shuffles.",
    # a pick that is not one of the printed filters
    "target player reveals their hand, then you choose a creature card from it. search that player's graveyard, hand, and "
    "library for all cards with the same name as the chosen card and exile them. then that player shuffles.",
    # a different follow-up count
    "counter target instant or sorcery spell. search its controller's graveyard, hand, and library for any number of cards "
    "with the same name as that spell and exile them. that player shuffles, then draws two cards for each card exiled from "
    "their hand this way.",
    # an unreadable condition
    "counter target sorcery spell. if you feel lucky, search the graveyard, hand, and library of that spell's controller for "
    "any number of cards with the same name as that spell, exile those cards, then that player shuffles.",
    # your own zones are not "that player's"
    "target player reveals their hand, then you choose a card other than a basic land card from it. search your graveyard, "
    "hand, and library for all cards with the same name as the chosen card and exile them. then that player shuffles.",
])
def test_near_misses_stay_unclaimed(text):
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    assert parse_effect_body(text) is None
