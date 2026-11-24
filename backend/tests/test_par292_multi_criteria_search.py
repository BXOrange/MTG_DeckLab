"""PAR-292 M8: one search for several differently-qualified cards (RULE 701.19b, 701.20).

"Search your library for a white card, a blue card, ... and a green card", "a Forest card and a Plains card", "an Aura
card and/or an Equipment card": every slot is its own optional pick of at most one card matching that slot, a card
fills one slot only, and the library is shuffled once. All on a real GameEngine with bystanders."""
import pytest

from mtg_analyzer.game.effects.library import SearchLibraryEffect
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import activate, card, cast, filler, game, put_on_battlefield

from tests.test_par292_dynamic_search_qualities import _drive_to_search, _library_card, _modeled, _offered
from mtg_analyzer.parser.oracle.catalogue.clause_hooks import match_clause


@pytest.mark.parametrize("name", [
    "Aang's Journey", "Axgard Armory", "Conflux", "Corpse Harvester", "Gem of Becoming", "Krosan Verge",
    "Lotuslight Dancers", "Shard Convergence", "Journey for the Elixir", "Alpine Houndmaster",
])
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _pick(eng, label):
    choice = eng.state.pending_choice
    eng.resolve_pending_choice(str(next(o["id"] for o in choice["options"] if o["label"] == label)))


def _color_library(eng):
    for name, cost in (("WhiteOne", "{W}"), ("WhiteTwo", "{1}{W}"), ("BlueOne", "{U}"), ("BlackOne", "{B}"),
                       ("RedOne", "{R}"), ("GreenOne", "{G}"), ("Colorless", "{3}")):
        filler(eng, name, type_line="Creature", mv=1, zone=Zone.LIBRARY, mana_cost_string=cost)
    return eng


def _hand(eng):
    return sorted(o.name for o in eng.state.player_by_id("p1").hand)


def test_conflux_finds_one_card_of_each_color_and_no_bystander():
    eng = game(library=0)
    for name, cost in (("WhiteOne", "{W}"), ("WhiteTwo", "{1}{W}"), ("BlueOne", "{U}"), ("BlackOne", "{B}"),
                       ("RedOne", "{R}"), ("GreenOne", "{G}"), ("Colorless", "{3}")):
        filler(eng, name, type_line="Creature", mv=1, zone=Zone.LIBRARY, mana_cost_string=cost)
    cast(eng, card(eng, "Conflux", zone=Zone.HAND))
    assert _offered(eng) == {"WhiteOne", "WhiteTwo"}  # first slot is white: no other color, no colorless card
    _pick(eng, "WhiteTwo")
    assert _offered(eng) == {"BlueOne"}
    _pick(eng, "BlueOne")
    assert _offered(eng) == {"BlackOne"}
    _pick(eng, "BlackOne")
    _pick(eng, "RedOne")
    _pick(eng, "GreenOne")
    assert eng.state.pending_choice is None
    assert _hand(eng) == ["BlackOne", "BlueOne", "GreenOne", "RedOne", "WhiteTwo"]
    library = [o.name for o in eng.state.player_by_id("p1").library]
    assert sorted(library) == ["Colorless", "WhiteOne"]  # bystanders stay


def test_a_multicolored_card_fills_only_one_slot():
    eng = game(library=0)
    filler(eng, "Gold", type_line="Creature", mv=2, zone=Zone.LIBRARY, mana_cost_string="{W}{U}")
    filler(eng, "PlainBlue", type_line="Creature", mv=1, zone=Zone.LIBRARY, mana_cost_string="{U}")
    cast(eng, card(eng, "Conflux", zone=Zone.HAND))
    assert _offered(eng) == {"Gold"}  # white slot
    _pick(eng, "Gold")
    assert _offered(eng) == {"PlainBlue"}  # the blue slot cannot take Gold again
    _pick(eng, "PlainBlue")
    assert eng.state.pending_choice is None
    assert _hand(eng) == ["Gold", "PlainBlue"]


def test_a_slot_may_be_declined_and_an_empty_slot_is_skipped():
    eng = game(library=0)
    filler(eng, "WhiteOne", type_line="Creature", mv=1, zone=Zone.LIBRARY, mana_cost_string="{W}")
    filler(eng, "GreenOne", type_line="Creature", mv=1, zone=Zone.LIBRARY, mana_cost_string="{G}")
    cast(eng, card(eng, "Conflux", zone=Zone.HAND))
    eng.resolve_pending_choice("decline")  # decline white; blue/black/red have no card and are skipped
    assert _offered(eng) == {"GreenOne"}
    _pick(eng, "GreenOne")
    assert eng.state.pending_choice is None
    assert _hand(eng) == ["GreenOne"]


def test_the_library_is_shuffled_once():
    eng = game(library=0)
    _color_library(eng)
    shuffles = []
    original = eng.rules.shuffle_library
    eng.rules.shuffle_library = lambda player, *a, **k: (shuffles.append(player.id), original(player, *a, **k))[1]
    cast(eng, card(eng, "Conflux", zone=Zone.HAND))
    for label in ("WhiteOne", "BlueOne", "BlackOne", "RedOne", "GreenOne"):
        assert not shuffles
        _pick(eng, label)
    assert shuffles == ["p1"]


def test_nothing_to_find_still_shuffles_and_opens_no_choice():
    eng = game(library=0)
    filler(eng, "Colorless", type_line="Creature", mv=1, zone=Zone.LIBRARY)
    shuffles = []
    original = eng.rules.shuffle_library
    eng.rules.shuffle_library = lambda player, *a, **k: (shuffles.append(player.id), original(player, *a, **k))[1]
    cast(eng, card(eng, "Conflux", zone=Zone.HAND))
    assert eng.state.pending_choice is None and shuffles == ["p1"] and not _hand(eng)


def test_krosan_verge_puts_a_forest_and_a_plains_onto_the_battlefield_tapped():
    eng = game(library=0)
    _library_card(eng, "TheForest", mv=0, type_line="Basic Land — Forest")
    _library_card(eng, "ForestTwo", mv=0, type_line="Land — Forest Plains")  # one card matching both slots
    _library_card(eng, "ThePlains", mv=0, type_line="Basic Land — Plains")
    _library_card(eng, "TheIsland", mv=0, type_line="Basic Land — Island")
    verge = card(eng, "Krosan Verge")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 2})
    activate(eng, verge, 0)
    assert _offered(eng) == {"TheForest", "ForestTwo"}
    _pick(eng, "ForestTwo")
    assert _offered(eng) == {"ThePlains"}  # ForestTwo is a Plains too, but it already filled the Forest slot
    _pick(eng, "ThePlains")
    arrived = {o.name: o for o in eng.state.battlefield if o.name in {"ForestTwo", "ThePlains", "TheForest", "TheIsland"}}
    assert set(arrived) == {"ForestTwo", "ThePlains"} and all(o.tapped for o in arrived.values())
    assert verge not in eng.state.battlefield  # sacrificed as part of the cost


def test_axgard_armory_and_or_takes_either_or_both_and_reveals():
    eng = game(library=0)
    _library_card(eng, "TheAura", mv=1, type_line="Enchantment — Aura")
    _library_card(eng, "TheSword", mv=1, type_line="Artifact — Equipment")
    _library_card(eng, "TheRock", mv=1, type_line="Artifact")
    armory = card(eng, "Axgard Armory")
    eng.state.player_by_id("p1").mana_pool.add_many({"R": 2, "W": 1, "C": 1})
    activate(eng, armory, 0)
    assert _offered(eng) == {"TheAura"}
    _pick(eng, "TheAura")
    assert _offered(eng) == {"TheSword"}
    eng.resolve_pending_choice("decline")  # the Equipment half is optional ("and/or")
    assert eng.state.pending_choice is None
    assert _hand(eng) == ["TheAura"]


def test_gem_of_becoming_finds_an_island_a_swamp_and_a_mountain():
    eng = game(library=0)
    for name, line in (("Isle", "Basic Land — Island"), ("Bog", "Basic Land — Swamp"),
                       ("Peak", "Basic Land — Mountain"), ("Wood", "Basic Land — Forest")):
        _library_card(eng, name, mv=0, type_line=line)
    gem = card(eng, "Gem of Becoming")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 3})
    activate(eng, gem, 0)
    for label in ("Isle", "Bog", "Peak"):
        assert _offered(eng) == {label}
        _pick(eng, label)
    assert eng.state.pending_choice is None
    assert _hand(eng) == ["Bog", "Isle", "Peak"]


def test_lotuslight_dancers_puts_three_colors_into_the_graveyard():
    eng = game(library=0)
    for name, cost in (("B1", "{B}"), ("G1", "{G}"), ("U1", "{U}"), ("R1", "{R}")):
        filler(eng, name, type_line="Creature", mv=1, zone=Zone.LIBRARY, mana_cost_string=cost)
    put_on_battlefield(eng, "Lotuslight Dancers")
    for label in ("B1", "G1", "U1"):
        _pick(eng, label)
    assert eng.state.pending_choice is None
    assert sorted(o.name for o in eng.state.player_by_id("p1").graveyard) == ["B1", "G1", "U1"]
    assert not _hand(eng)


def test_corpse_harvester_finds_a_zombie_and_a_swamp():
    eng = game(library=0)
    _library_card(eng, "Ghoul", mv=2, type_line="Creature — Zombie")
    _library_card(eng, "Elf", mv=2, type_line="Creature — Elf")
    _library_card(eng, "TheSwamp", mv=0, type_line="Basic Land — Swamp")
    harvester = card(eng, "Corpse Harvester")
    victim = filler(eng, "Victim")
    eng.state.player_by_id("p1").mana_pool.add_many({"B": 2})
    activate(eng, harvester, 0, sacrifice_choice=victim.instance_id)
    assert _offered(eng) == {"Ghoul"}
    _pick(eng, "Ghoul")
    assert _offered(eng) == {"TheSwamp"}
    _pick(eng, "TheSwamp")
    assert _hand(eng) == ["Ghoul", "TheSwamp"]


def test_aangs_journey_kicked_adds_a_shrine_to_the_basic_land():
    for kicked, expected in ((0, ["BasicForest"]), (1, ["BasicForest", "TheShrine"])):
        eng = game(library=0)
        _library_card(eng, "BasicForest", mv=0, type_line="Basic Land — Forest")
        _library_card(eng, "TheShrine", mv=2, type_line="Legendary Enchantment — Shrine")
        cast(eng, card(eng, "Aang's Journey", zone=Zone.HAND), kicked=kicked)
        _pick(eng, "BasicForest")
        if kicked:
            _pick(eng, "TheShrine")
        assert eng.state.pending_choice is None
        assert _hand(eng) == expected


def test_each_slot_must_be_read_by_the_plain_criteria_grammar():
    # An X bound is not claimed (the slot needs the announced X); nor is a mixed destination or a counted slot.
    assert match_clause("search your library for a creature card with mana value x or less and a forest card, "
                        "put them into your hand, then shuffle") is None
    # differing destinations per slot, and a count / "up to" slot, are other shapes
    assert match_clause("search your library for a forest card and a plains card, put one into your hand and "
                        "the other onto the battlefield, then shuffle") is None
    assert match_clause("search your library for up to two forest cards and a plains card, put them into your hand, "
                        "then shuffle") is None


def test_journey_for_the_elixir_searches_the_graveyard_too_for_a_named_card():
    eng = game(library=0)
    p1 = eng.state.player_by_id("p1")
    _library_card(eng, "BasicForest", mv=0, type_line="Basic Land — Forest")
    _library_card(eng, "NonbasicLand", mv=0, type_line="Land")
    filler(eng, "Jiang Yanggu", type_line="Legendary Creature", mv=3, zone=Zone.GRAVEYARD)
    filler(eng, "Basic In Yard", type_line="Basic Land — Island", mv=0, zone=Zone.GRAVEYARD)
    cast(eng, card(eng, "Journey for the Elixir", zone=Zone.HAND))
    assert _offered(eng) == {"BasicForest", "Basic In Yard"}  # nonbasic land is a bystander
    _pick(eng, "BasicForest")
    assert _offered(eng) == {"Jiang Yanggu"}
    _pick(eng, "Jiang Yanggu")
    assert eng.state.pending_choice is None
    assert sorted(o.name for o in p1.hand) == ["BasicForest", "Jiang Yanggu"]


def test_alpine_houndmaster_finds_each_named_card_and_not_a_lookalike():
    eng = game(library=0)
    filler(eng, "Alpine Watchdog", type_line="Creature", mv=2, zone=Zone.LIBRARY)
    filler(eng, "Igneous Cur", type_line="Creature", mv=3, zone=Zone.LIBRARY)
    filler(eng, "Alpine Wolf", type_line="Creature", mv=2, zone=Zone.LIBRARY)
    put_on_battlefield(eng, "Alpine Houndmaster")
    _drive_to_search(eng)
    assert _offered(eng) == {"Alpine Watchdog"}
    _pick(eng, "Alpine Watchdog")
    assert _offered(eng) == {"Igneous Cur"}
    eng.resolve_pending_choice("decline")  # "and/or": the second card is optional
    assert eng.state.pending_choice is None
    assert _hand(eng) == ["Alpine Watchdog"]


@pytest.mark.parametrize("name", [
    "Shrine Steward", "Sun-Spider, Nimble Webber", "Deadeye Quartermaster", "Sazh Katzroy", "Treefolk Harbinger",
    "The Cave of Two Lovers", "The Huntsman's Redemption",
])
def test_two_alternative_qualities_are_modeled(name):
    assert _modeled(name)


def test_shrine_steward_finds_an_aura_or_a_shrine_but_not_an_equipment():
    eng = game(library=0)
    _library_card(eng, "TheAura", mv=1, type_line="Enchantment — Aura")
    _library_card(eng, "TheShrine", mv=1, type_line="Enchantment — Shrine")
    _library_card(eng, "TheSword", mv=1, type_line="Artifact — Equipment")
    _library_card(eng, "TheEnchantment", mv=1, type_line="Enchantment")
    put_on_battlefield(eng, "Shrine Steward")
    _drive_to_search(eng)
    assert _offered(eng) == {"TheAura", "TheShrine"}
    _pick(eng, "TheShrine")
    assert eng.state.pending_choice is None
    assert _hand(eng) == ["TheShrine"]


def test_sazh_katzroy_finds_a_bird_or_a_basic_land_and_not_a_nonbasic_land():
    eng = game(library=0)
    _library_card(eng, "TheBird", mv=2, type_line="Creature — Bird")
    _library_card(eng, "TheForest", mv=0, type_line="Basic Land — Forest")
    _library_card(eng, "TheNonbasic", mv=0, type_line="Land — Forest")
    _library_card(eng, "TheCat", mv=2, type_line="Creature — Cat")
    put_on_battlefield(eng, "Sazh Katzroy")
    _drive_to_search(eng)
    assert _offered(eng) == {"TheBird", "TheForest"}


def test_treefolk_harbinger_puts_the_found_card_on_top_after_shuffling():
    eng = game(library=0)
    _library_card(eng, "TheTreefolk", mv=3, type_line="Creature — Treefolk")
    _library_card(eng, "TheForest", mv=0, type_line="Basic Land — Forest")
    _library_card(eng, "TheIsland", mv=0, type_line="Basic Land — Island")
    put_on_battlefield(eng, "Treefolk Harbinger")
    _drive_to_search(eng)
    assert _offered(eng) == {"TheTreefolk", "TheForest"}
    _pick(eng, "TheForest")
    library = eng.state.player_by_id("p1").library
    assert library[-1].name == "TheForest"  # the top of a library is its last element
    assert not _hand(eng)
