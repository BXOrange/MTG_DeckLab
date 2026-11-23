"""PAR-292 M9: a search whose found cards are exiled (RULE 701.19, 406) and a card narrowed by two qualities at once
("an artifact creature card", "a snow land card", "a spider hero card", RULE 205.2 / 205.3 / 205.4).

Every claimed card runs on a real GameEngine, with bystanders in the library that must stay there."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.clause_hooks import match_clause
from tests.support.deck_batch import activate, card, cast, filler, game, put_on_battlefield

from tests.test_par292_dynamic_search_qualities import _drive_to_search, _library_card, _modeled, _offered


@pytest.mark.parametrize("name", [
    "Foresight", "Manipulate Fate", "Mana Severance", "Selective Memory", "Strata Scythe", "Sphinx Summoner",
    "Into the North", "Spirit of the Aldergard", "Radioactive Spider",
])
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _exiled(eng, player="p1"):
    return sorted(o.name for o in eng.state.player_by_id(player).exile)


def _pick(eng, label):
    choice = eng.state.pending_choice
    eng.resolve_pending_choice(str(next(o["id"] for o in choice["options"] if o["label"] == label)))


def _library_names(eng, player="p1"):
    return sorted(o.name for o in eng.state.player_by_id(player).library)


def test_manipulate_fate_exiles_three_chosen_cards_then_draws_and_leaves_the_rest():
    eng = game(library=0)
    for name in ("A", "B", "C", "D"):
        _library_card(eng, name, mv=1, type_line="Creature")
    _library_card(eng, "Theirs", mv=1, type_line="Creature", player="p2")
    cast(eng, card(eng, "Manipulate Fate", zone=Zone.HAND))
    for label in ("A", "B", "C"):
        _pick(eng, label)
    assert eng.state.pending_choice is None
    assert _exiled(eng) == ["A", "B", "C"]
    assert [o.name for o in eng.state.player_by_id("p1").hand] == ["D"]  # the drawn card; nothing went to hand
    assert _library_names(eng) == []
    assert _library_names(eng, "p2") == ["Theirs"]


def test_a_search_for_three_cards_may_find_fewer_when_declined():
    eng = game(library=0)
    for name in ("A", "B"):
        _library_card(eng, name, mv=1, type_line="Creature")
    cast(eng, card(eng, "Manipulate Fate", zone=Zone.HAND))
    _pick(eng, "A")
    eng.resolve_pending_choice("decline")
    assert _exiled(eng) == ["A"]


def test_foresight_exiles_and_does_not_draw_until_the_next_upkeep():
    eng = game(library=0)
    for name in ("A", "B", "C", "D"):
        _library_card(eng, name, mv=1, type_line="Creature")
    cast(eng, card(eng, "Foresight", zone=Zone.HAND))
    for label in ("A", "B", "C"):
        _pick(eng, label)
    assert _exiled(eng) == ["A", "B", "C"]
    assert not eng.state.player_by_id("p1").hand  # the draw is delayed to the next upkeep
    assert len(eng.state.delayed_triggers) == 1


def test_mana_severance_exiles_only_land_cards():
    eng = game(library=0)
    _library_card(eng, "Forest One", mv=0, type_line="Basic Land — Forest")
    _library_card(eng, "Forest Two", mv=0, type_line="Basic Land — Forest")
    _library_card(eng, "Bear", mv=2, type_line="Creature")
    cast(eng, card(eng, "Mana Severance", zone=Zone.HAND))
    assert _offered(eng) == {"Forest One", "Forest Two"}
    _pick(eng, "Forest One")
    _pick(eng, "Forest Two")
    assert _exiled(eng) == ["Forest One", "Forest Two"]
    assert _library_names(eng) == ["Bear"]


def test_selective_memory_exiles_only_nonland_cards():
    eng = game(library=0)
    _library_card(eng, "Forest One", mv=0, type_line="Basic Land — Forest")
    _library_card(eng, "Bear", mv=2, type_line="Creature")
    _library_card(eng, "Bolt", mv=1, type_line="Instant")
    cast(eng, card(eng, "Selective Memory", zone=Zone.HAND))
    assert _offered(eng) == {"Bear", "Bolt"}
    _pick(eng, "Bear")
    _pick(eng, "Bolt")
    assert _exiled(eng) == ["Bear", "Bolt"]
    assert _library_names(eng) == ["Forest One"]


def test_strata_scythe_imprints_a_land_and_counts_lands_sharing_its_name():
    eng = game(library=0)
    _library_card(eng, "Mountain", mv=0, type_line="Basic Land — Mountain")
    _library_card(eng, "Swamp", mv=0, type_line="Basic Land — Swamp")
    _library_card(eng, "Bear", mv=2, type_line="Creature")
    scythe = put_on_battlefield(eng, "Strata Scythe")
    _drive_to_search(eng)
    assert _offered(eng) == {"Mountain", "Swamp"}
    _pick(eng, "Mountain")
    assert _exiled(eng) == ["Mountain"]
    assert _library_names(eng) == ["Bear", "Swamp"]
    for _ in range(2):
        filler(eng, "Mountain", type_line="Basic Land — Mountain")
    filler(eng, "Swamp", type_line="Basic Land — Swamp")  # a different name: not counted
    body = filler(eng, "Holder", type_line="Creature", power=1, toughness=1)
    scythe.attached_to = body.instance_id
    eng.recompute_continuous_effects()
    assert (body.power, body.toughness) == (3, 3)


def test_sphinx_summoner_wants_both_artifact_and_creature():
    eng = game(library=0)
    _library_card(eng, "Golem", mv=3, type_line="Artifact Creature — Golem")
    _library_card(eng, "Rock", mv=1, type_line="Artifact")
    _library_card(eng, "Bear", mv=2, type_line="Creature — Bear")
    put_on_battlefield(eng, "Sphinx Summoner")
    _drive_to_search(eng)
    assert _offered(eng) == {"Golem"}
    _pick(eng, "Golem")
    assert [o.name for o in eng.state.player_by_id("p1").hand] == ["Golem"]


def test_into_the_north_fetches_only_a_snow_land():
    eng = game(library=0)
    _library_card(eng, "Snow Forest", mv=0, type_line="Basic Snow Land — Forest")
    _library_card(eng, "Forest", mv=0, type_line="Basic Land — Forest")
    _library_card(eng, "Snow Rock", mv=1, type_line="Snow Artifact")
    cast(eng, card(eng, "Into the North", zone=Zone.HAND))
    assert _offered(eng) == {"Snow Forest"}
    _pick(eng, "Snow Forest")
    found = [o for o in eng.state.battlefield if o.name == "Snow Forest"]
    assert found and found[0].tapped


def test_radioactive_spider_finds_a_card_with_both_subtypes():
    eng = game(library=0)
    _library_card(eng, "Peter", mv=3, type_line="Legendary Creature — Spider Human Hero")
    _library_card(eng, "Plain Spider", mv=2, type_line="Creature — Spider")
    _library_card(eng, "Plain Hero", mv=2, type_line="Creature — Human Hero")
    spider = put_on_battlefield(eng, "Radioactive Spider")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 2})
    activate(eng, spider, 0)
    _drive_to_search(eng)
    assert _offered(eng) == {"Peter"}


@pytest.mark.parametrize("text", [
    # two type words after a list: not an intersection of one first type
    "search your library for a creature or artifact land card, put it into your hand, then shuffle",
    # an exile clause with a tail this row does not read
    "search your library for a card, exile it, then shuffle and put it on top",
    "search your library for a card, exile it",
])
def test_near_misses_stay_unclaimed(text):
    assert not match_clause(text)
