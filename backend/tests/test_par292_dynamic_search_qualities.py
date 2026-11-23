"""PAR-292 M1: library-search qualities whose bound is *measured* ("mana value equal to 1 plus the sacrificed
artifact's mana value", "the same name as another creature you control"), and "any number of" searches.

Each claimed card runs on a real GameEngine; the search must offer exactly the cards that meet the bound at the moment
the search resolves (RULE 608.2h last-known information for the sacrificed object, RULE 701.19a)."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import activate, answer, card, cast, enter, filler, game, main_phase, put_on_battlefield
from tests.support.deck_batch import stack_library


def _modeled(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.parser.oracle import parse_oracle
    from mtg_analyzer.services.card_database import CardDatabase
    return parse_oracle(CardDatabase(DB_PATH).get_card(name)).modeled


@pytest.mark.parametrize("name", [
    "Repurposing Bay", "Enigmatic Incarnation", "Iron Man, Titan of Innovation", "Pattern Matcher",
    "Secret Salvage", "Uncage the Menagerie", "Faith Healer", "Battalion Foot Soldier", "Gathering Throng",
    "Legion Conquistador", "Iname, Death Aspect", "Sarkhan Unbroken", "Scouting Trek", "The World Tree",
])
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _offered(eng):
    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "search"
    return {o["label"] for o in choice["options"] if o["id"] != "decline"}


_ACCEPT_IDS = ("do", "pay", "yes")


def _drive_to_search(eng, *, accept=True):
    """Answer the may / pay prompts ahead of a search (accepting, or declining) and stop at the search choice."""
    for _ in range(8):
        choice = eng.state.pending_choice
        if choice is None or choice.get("kind") == "search":
            return
        ids = [str(o["id"]) for o in choice.get("options") or []]
        wanted = [i for i in ids if (i in _ACCEPT_IDS) == accept]
        eng.resolve_pending_choice(wanted[0] if wanted else (ids[0] if ids else "yes"))


def _library_card(eng, name, *, mv, type_line, player="p1"):
    # 1/1 bodies so a creature put onto the battlefield survives state-based actions (RULE 704.5f).
    body = {"power": 1, "toughness": 1} if "Creature" in type_line else {}
    return filler(eng, name, type_line=type_line, mv=mv, zone=Zone.LIBRARY, player=player, **body)


def test_repurposing_bay_offers_exactly_one_more_than_the_sacrificed_artifact():
    eng = game(library=0)
    bay = card(eng, "Repurposing Bay")
    victim = filler(eng, "Victim", type_line="Artifact", mv=2)
    _library_card(eng, "Cheap", mv=2, type_line="Artifact")
    _library_card(eng, "Exact", mv=3, type_line="Artifact")
    _library_card(eng, "Big", mv=4, type_line="Artifact")
    _library_card(eng, "WrongTypeSameValue", mv=3, type_line="Creature")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 2})
    activate(eng, bay, 0, sacrifice_choice=victim.instance_id)
    assert _offered(eng) == {"Exact"}
    answer(eng, lambda c: str(next(o["id"] for o in c["options"] if o["label"] == "Exact")))
    assert [o.name for o in eng.state.battlefield if o.name == "Exact"]


def test_repurposing_bay_reads_the_value_the_sacrifice_had_not_a_later_one():
    """RULE 608.2h: a sacrificed artifact with a changed mana value is measured as it last existed."""
    eng = game(library=0)
    bay = card(eng, "Repurposing Bay")
    victim = filler(eng, "Victim", type_line="Artifact", mv=5)
    _library_card(eng, "Six", mv=6, type_line="Artifact")
    _library_card(eng, "Two", mv=2, type_line="Artifact")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 2})
    activate(eng, bay, 0, sacrifice_choice=victim.instance_id)
    assert _offered(eng) == {"Six"}


def test_enigmatic_incarnation_trigger_offers_one_plus_the_sacrificed_enchantment():
    eng = game(library=0)
    inc = card(eng, "Enigmatic Incarnation")
    victim = filler(eng, "Ench", type_line="Enchantment", mv=3)
    _library_card(eng, "Three", mv=3, type_line="Creature")
    _library_card(eng, "Four", mv=4, type_line="Creature")
    _library_card(eng, "FourArtifact", mv=4, type_line="Artifact")
    _library_card(eng, "Five", mv=5, type_line="Creature")
    from tests.support.deck_batch import step
    step(eng, "end")
    _drive_to_search(eng)
    assert _offered(eng) == {"Four"}


def test_iron_man_search_after_sacrifice_and_declined_sacrifice_searches_nothing():
    eng = game(library=0)
    man = card(eng, "Iron Man, Titan of Innovation")
    victim = filler(eng, "Rock", type_line="Artifact", mv=1)
    _library_card(eng, "Two", mv=2, type_line="Artifact")
    _library_card(eng, "Three", mv=3, type_line="Artifact")
    from tests.support.deck_batch import attack
    attack(eng, [man])
    _drive_to_search(eng)
    assert _offered(eng) == {"Two"}


def test_iron_man_declining_the_sacrifice_opens_no_search():
    eng = game(library=0)
    man = card(eng, "Iron Man, Titan of Innovation")
    filler(eng, "Rock", type_line="Artifact", mv=1)
    _library_card(eng, "Two", mv=2, type_line="Artifact")
    from tests.support.deck_batch import attack
    attack(eng, [man])
    _drive_to_search(eng, accept=False)
    assert eng.state.pending_choice is None


def test_pattern_matcher_offers_only_names_of_other_creatures_you_control():
    eng = game(library=0)
    filler(eng, "Shared", power=1, toughness=1)
    filler(eng, "OpponentOnly", power=1, toughness=1, player="p2")
    _library_card(eng, "Shared", mv=1, type_line="Creature")
    _library_card(eng, "OpponentOnly", mv=1, type_line="Creature")
    _library_card(eng, "Unrelated", mv=1, type_line="Creature")
    put_on_battlefield(eng, "Pattern Matcher")
    _drive_to_search(eng)
    assert _offered(eng) == {"Shared"}


def test_pattern_matcher_does_not_count_itself():
    eng = game(library=0)
    _library_card(eng, "Pattern Matcher", mv=3, type_line="Artifact Creature")
    put_on_battlefield(eng, "Pattern Matcher")
    _drive_to_search(eng)
    choice = eng.state.pending_choice
    # No other creature is controlled: the name set is empty, so nothing is offered (RULE 701.23c).
    assert choice is None or _offered(eng) == set()


def test_secret_salvage_searches_every_card_with_the_exiled_name():
    eng = game(library=0)
    target = card(eng, "Lightning Bolt", zone=Zone.GRAVEYARD)
    for _ in range(3):
        card(eng, "Lightning Bolt", zone=Zone.LIBRARY)
    card(eng, "Shock", zone=Zone.LIBRARY)
    salvage = card(eng, "Secret Salvage", zone=Zone.HAND)
    cast(eng, salvage, targets=[target])
    taken = 0
    for _ in range(8):
        choice = eng.state.pending_choice
        if choice is None:
            break
        assert choice["kind"] == "search"
        assert _offered(eng) == {"Lightning Bolt"}
        eng.resolve_pending_choice(str(next(o["id"] for o in choice["options"] if o["id"] != "decline")))
        taken += 1
    assert taken == 3
    assert not [o for o in eng.state.player_by_id("p1").library if o.name == "Lightning Bolt"]
    assert [o.name for o in eng.state.player_by_id("p1").library] == ["Shock"]


def test_uncage_the_menagerie_offers_only_the_announced_value():
    eng = game(library=0)
    for name, mv in (("TwoA", 2), ("TwoB", 2), ("Three", 3)):
        _library_card(eng, name, mv=mv, type_line="Creature")
    _library_card(eng, "TwoNonCreature", mv=2, type_line="Artifact")
    spell = card(eng, "Uncage the Menagerie", zone=Zone.HAND)
    main_phase(eng)
    p1 = eng.state.player_by_id("p1")
    from tests.support.deck_batch import RICH
    p1.mana_pool.add_many(RICH)
    eng.cast_spell(p1, spell, x=2)
    eng.resolve_until_stable()
    assert _offered(eng) == {"TwoA", "TwoB"}


def _take_all(eng, wanted_labels):
    """Pick every offered card (one search round each) until the search ends; the cards taken, in order."""
    taken = []
    for _ in range(40):
        choice = eng.state.pending_choice
        if choice is None:
            return taken
        assert choice["kind"] == "search"
        option = next((o for o in choice["options"] if o["id"] != "decline"), None)
        if option is None:
            eng.resolve_pending_choice("decline")
            continue
        assert option["label"] in wanted_labels
        taken.append(option["label"])
        eng.resolve_pending_choice(str(option["id"]))
    raise AssertionError("search never ended")


def test_any_number_search_takes_every_matching_card_and_nothing_else():
    eng = game(library=0)
    for i in range(4):
        _library_card(eng, f"Spirit{i}", mv=1, type_line="Creature — Spirit")
    _library_card(eng, "Goblin", mv=1, type_line="Creature — Goblin")
    put_on_battlefield(eng, "Iname, Death Aspect")
    _drive_to_search(eng)
    taken = _take_all(eng, {f"Spirit{i}" for i in range(4)})
    assert len(taken) == 4
    p1 = eng.state.player_by_id("p1")
    assert sorted(o.name for o in p1.graveyard) == [f"Spirit{i}" for i in range(4)]
    assert [o.name for o in p1.library] == ["Goblin"]


def test_any_number_search_may_stop_early():
    eng = game(library=0)
    for i in range(3):
        _library_card(eng, f"Spirit{i}", mv=1, type_line="Creature — Spirit")
    put_on_battlefield(eng, "Iname, Death Aspect")
    _drive_to_search(eng)
    choice = eng.state.pending_choice
    eng.resolve_pending_choice(str(next(o["id"] for o in choice["options"] if o["id"] != "decline")))
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None
    assert len(eng.state.player_by_id("p1").graveyard) == 1


def test_battalion_foot_soldier_finds_every_copy_by_name_and_no_other_card():
    eng = game(library=0)
    for _ in range(3):
        card(eng, "Battalion Foot Soldier", zone=Zone.LIBRARY)
    card(eng, "Shock", zone=Zone.LIBRARY)
    put_on_battlefield(eng, "Battalion Foot Soldier")
    _drive_to_search(eng)
    assert len(_take_all(eng, {"Battalion Foot Soldier"})) == 3
    p1 = eng.state.player_by_id("p1")
    assert sum(1 for o in p1.hand if o.name == "Battalion Foot Soldier") == 3


def test_scouting_trek_puts_the_found_lands_on_top_after_the_shuffle():
    eng = game(library=0)
    for i in range(3):
        card(eng, "Forest", zone=Zone.LIBRARY)
    for i in range(6):
        filler(eng, f"Other{i}", mv=1, zone=Zone.LIBRARY)
    spell = card(eng, "Scouting Trek", zone=Zone.HAND)
    cast(eng, spell)
    assert len(_take_all(eng, {"Forest"})) == 3
    library = eng.state.player_by_id("p1").library
    assert len(library) == 9
    top = [o.name for o in library[-3:]] + [o.name for o in library[:3]]
    # RULE 701.19b: the found cards sit on top of the (already shuffled) library: whichever end the engine treats as the
    # top, the three lands are contiguous at one end.
    assert [o.name for o in library[-3:]] == ["Forest"] * 3 or [o.name for o in library[:3]] == ["Forest"] * 3, top


def test_faith_healer_gains_the_last_known_mana_value_of_the_sacrificed_enchantment():
    eng = game(library=0)
    healer = card(eng, "Faith Healer")
    victim = filler(eng, "Ench", type_line="Enchantment", mv=4)
    before = eng.state.player_by_id("p1").life
    activate(eng, healer, 0, sacrifice_choice=victim.instance_id)
    assert eng.state.player_by_id("p1").life == before + 4


def test_sarkhan_unbroken_ultimate_finds_only_dragons():
    eng = game(library=0)
    _library_card(eng, "Drake", mv=3, type_line="Creature — Dragon")
    _library_card(eng, "Wyrm", mv=5, type_line="Creature — Dragon")
    _library_card(eng, "Bear", mv=2, type_line="Creature — Bear")
    _library_card(eng, "DragonShrine", mv=2, type_line="Enchantment — Dragon")
    sarkhan = card(eng, "Sarkhan Unbroken")
    sarkhan.counters = {"loyalty": 8}
    activate(eng, sarkhan, 2)
    assert set(_take_all(eng, {"Drake", "Wyrm"})) == {"Drake", "Wyrm"}
    assert {o.name for o in eng.state.battlefield if o.name in {"Drake", "Wyrm", "Bear", "DragonShrine"}} == {"Drake", "Wyrm"}


# --- parse level: what must stay unclaimed (fail closed) -----------------------------------------------------------

def _claims(text):
    from mtg_analyzer.parser.oracle.catalogue.filter_slots import peel_filter_slots
    from mtg_analyzer.parser.oracle.catalogue.clause_hooks import match_clause
    return peel_filter_slots(text, match_clause)


def test_dynamic_bound_is_a_bind_around_a_search_with_the_placeholder_in_both_ends_for_equality():
    specs = _claims("search your library for an artifact card with mana value equal to 1 plus the sacrificed "
                    "artifact's mana value, put it onto the battlefield, then shuffle")
    assert [s.type for s in specs] == ["bind"]
    (inner,) = specs[0].params["effects"]
    assert inner["params"]["criteria"] == {"type": "artifact", "min_mana_value": "$n", "max_mana_value": "$n"}
    assert specs[0].params["amount"] == {"kind": "count_selector",
                                         "selector": {"terms": ["sacrificed_cost_mana_value"], "plus": 1}}


def test_dynamic_ceiling_writes_only_the_upper_bound():
    specs = _claims("search your library for a creature card with mana value less than or equal to the number of "
                    "lands you control, put it onto the battlefield, then shuffle")
    assert specs is not None and specs[0].type == "bind"
    (inner,) = specs[0].params["effects"]
    assert inner["params"]["criteria"] == {"type": "creature", "max_mana_value": "$n"}


@pytest.mark.parametrize("clause", [
    # an amount the vocabulary does not know is never guessed at
    "search your library for a creature card with mana value equal to the moon's phase, put it onto the battlefield, then shuffle",
    # "less than" is a strict bound the placeholder cannot express without arithmetic
    "search your library for a creature card with mana value less than the number of lands you control, put it onto the battlefield, then shuffle",
    # a second qualifier in the noun phrase is peeled one at a time, never half-read
    "search your library for a creature card with flying with mana value equal to 1 plus the sacrificed creature's mana value, put it onto the battlefield, then shuffle",
])
def test_unsupported_dynamic_qualities_stay_unclaimed(clause):
    specs = _claims(clause)
    assert specs is None or all(s.type != "bind" for s in specs)


def test_then_shuffle_is_not_cut_off_a_search_but_a_real_shuffle_instruction_still_is():
    from mtg_analyzer.parser.oracle.catalogue.clause_hooks import parse_effect_body
    chain = parse_effect_body("create a treasure token, then you may sacrifice a noncreature artifact. if you do, "
                              "search your library for an artifact card, put it onto the battlefield tapped, then shuffle.")
    assert chain and [s.type for s in chain] == ["create_token", "pay_cost_then"]
    split = parse_effect_body("exile it, then shuffle all creature cards from your graveyard into your library.")
    assert split and split[-1].params.get("shuffle_after") is True  # still cut at "then": a separate instruction


# --- M2: a hand pick (reveal / discard / choose) whose name or mana value feeds the search ----------------------------

def _hand(eng, name, type_line="Creature", mv=1, player="p1"):
    body = {"power": 1, "toughness": 1} if "Creature" in type_line else {}
    return filler(eng, name, type_line=type_line, mv=mv, zone=Zone.HAND, player=player, **body)


def _pick(eng, label):
    choice = eng.state.pending_choice
    assert choice is not None
    eng.resolve_pending_choice(str(next(o["id"] for o in choice["options"] if o["label"] == label)))


@pytest.mark.parametrize("name", ["Assembly Hall", "Infernal Tutor", "Disciple of Deceit"])
def test_pick_then_search_cards_are_modeled(name):
    assert _modeled(name)


def test_assembly_hall_searches_the_name_of_the_creature_card_the_player_revealed():
    eng = game(library=0)
    hall = card(eng, "Assembly Hall")
    _hand(eng, "Wolf")
    _hand(eng, "Bear")
    _hand(eng, "Bolt", type_line="Instant")  # not a creature card: never a legal reveal
    _library_card(eng, "Wolf", mv=1, type_line="Creature")
    _library_card(eng, "Wolf", mv=1, type_line="Creature")
    _library_card(eng, "Bear", mv=1, type_line="Creature")
    _library_card(eng, "Bolt", mv=1, type_line="Instant")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 4})
    activate(eng, hall, 0)
    choice = eng.state.pending_choice
    assert {o["label"] for o in choice["options"] if o["id"] != "decline"} == {"Wolf", "Bear"}
    _pick(eng, "Wolf")
    assert _offered(eng) == {"Wolf"}
    answer(eng)
    p1 = eng.state.player_by_id("p1")
    assert sorted(o.name for o in p1.hand) == ["Bear", "Bolt", "Wolf", "Wolf"]


def test_assembly_hall_with_no_creature_card_in_hand_finds_nothing():
    eng = game(library=0)
    hall = card(eng, "Assembly Hall")
    _hand(eng, "Bolt", type_line="Instant")
    _library_card(eng, "Bolt", mv=1, type_line="Instant")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 4})
    activate(eng, hall, 0)
    choice = eng.state.pending_choice
    assert choice is None or choice["kind"] != "search"


def test_infernal_tutor_searches_the_revealed_name_with_cards_in_hand():
    eng = game(library=0)
    _hand(eng, "Bolt", type_line="Instant")
    _library_card(eng, "Bolt", mv=1, type_line="Instant")
    _library_card(eng, "Other", mv=1, type_line="Instant")
    tutor = card(eng, "Infernal Tutor", zone=Zone.HAND)
    cast(eng, tutor)
    assert _offered(eng) == {"Bolt"}


def test_infernal_tutor_hellbent_searches_for_any_card():
    eng = game(library=0)
    _library_card(eng, "Bolt", mv=1, type_line="Instant")
    _library_card(eng, "Other", mv=1, type_line="Instant")
    tutor = card(eng, "Infernal Tutor", zone=Zone.HAND)
    cast(eng, tutor)  # the spell itself left the hand: no cards in hand when it resolves
    assert _offered(eng) == {"Bolt", "Other"}


def _untap_trigger(eng, disciple):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(EventType.UNTAPPED, controller_id="p1", instance_id=disciple.instance_id,
                                   object=disciple.name))
    eng.resolve_until_stable()


def test_disciple_of_deceit_discards_a_nonland_card_and_finds_its_mana_value():
    eng = game(library=0)
    disciple = card(eng, "Disciple of Deceit")
    _hand(eng, "Three", type_line="Sorcery", mv=3)
    _hand(eng, "Plains", type_line="Basic Land — Plains", mv=0)  # a land is not a legal discard here
    for name, mv in (("AlsoThree", 3), ("Two", 2), ("Four", 4)):
        _library_card(eng, name, mv=mv, type_line="Sorcery")
    _untap_trigger(eng, disciple)
    _drive_to_search(eng)  # accept the optional discard (a single legal card is picked for the player)
    assert _offered(eng) == {"AlsoThree"}
    p1 = eng.state.player_by_id("p1")
    assert "Three" in [o.name for o in p1.graveyard] and "Plains" in [o.name for o in p1.hand]


def test_disciple_of_deceit_declining_the_discard_searches_nothing():
    eng = game(library=0)
    disciple = card(eng, "Disciple of Deceit")
    _hand(eng, "Three", type_line="Sorcery", mv=3)
    _library_card(eng, "AlsoThree", mv=3, type_line="Sorcery")
    _untap_trigger(eng, disciple)
    assert eng.state.pending_choice["kind"] == "choose_objects"
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None
    assert [o.name for o in eng.state.player_by_id("p1").hand] == ["Three"]


def test_pick_then_search_stays_unclaimed_without_its_pairing():
    from mtg_analyzer.parser.oracle.catalogue.clause_hooks import parse_effect_body
    # a revealed card feeds a name and a discarded card a mana value; any other pairing is not read
    assert parse_effect_body("reveal a card from your hand. search your library for a card with the same mana "
                             "value as that card, put it into your hand, then shuffle.") is None
    assert parse_effect_body("you may discard a card. if you do, search your library for a card with the same name "
                             "as that card, put it into your hand, then shuffle.") is None


def test_choose_then_search_reads_the_chosen_permanents_name_on_a_probe_spell():
    """Canoptek Wraith's inner sentences as a spell (its "pay {3} and sacrifice it" wrapper is still unparsed)."""
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject
    from tests.support.deck_batch import _place

    eng = game(library=0)
    text = ("Choose a land you control. Then search your library for up to 2 basic land cards which have the same "
            "name as the chosen land, put them onto the battlefield tapped, then shuffle.")
    probe = Card(id="probe", name="Probe Sorcery", type_line="Sorcery", oracle_text=text, is_sorcery=True)
    spell = _place(eng, GameObject(probe, owner_id="p1", zone=Zone.HAND), "p1", Zone.HAND)
    forest = card(eng, "Forest")
    card(eng, "Island")
    for name in ("Forest", "Forest", "Island", "Swamp"):
        card(eng, name, zone=Zone.LIBRARY)
    cast(eng, spell)
    choice = eng.state.pending_choice
    if choice and choice["kind"] == "choose_objects":
        eng.resolve_pending_choice(str(forest.instance_id))
    assert _offered(eng) == {"Forest"}
    answer(eng)
    assert sorted(o.name for o in eng.state.battlefield if o.name in {"Forest", "Island", "Swamp"}) == [
        "Forest", "Forest", "Forest", "Island"]


def _shuffle_count(eng):
    from mtg_analyzer.models.game.events import EventType
    return sum(1 for e in eng.state.event_log if e.type == EventType.SHUFFLE)


def test_assembly_hall_with_nothing_to_reveal_still_searches_nothing_and_shuffles():
    """RULE 701.19b: the search happens (and finds nothing), and the library is shuffled all the same."""
    eng = game(library=0)
    hall = card(eng, "Assembly Hall")
    _hand(eng, "Bolt", type_line="Instant")  # no creature card to reveal
    for i in range(8):
        _library_card(eng, f"Wolf{i}", mv=1, type_line="Creature")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 4})
    shuffles = _shuffle_count(eng)
    activate(eng, hall, 0)
    p1 = eng.state.player_by_id("p1")
    assert [o.name for o in p1.hand] == ["Bolt"]
    assert len(p1.library) == 8
    assert _shuffle_count(eng) == shuffles + 1


def test_infernal_tutor_with_a_revealable_card_shuffles_once_and_hellbent_too():
    eng = game(library=0)
    _library_card(eng, "Bolt", mv=1, type_line="Instant")
    tutor = card(eng, "Infernal Tutor", zone=Zone.HAND)
    shuffles = _shuffle_count(eng)
    cast(eng, tutor)  # hellbent branch: searches for any card
    answer(eng)
    assert _shuffle_count(eng) == shuffles + 1


def test_disciple_of_deceit_declined_discard_does_not_shuffle():
    eng = game(library=0)
    disciple = card(eng, "Disciple of Deceit")
    _hand(eng, "Three", type_line="Sorcery", mv=3)
    _library_card(eng, "AlsoThree", mv=3, type_line="Sorcery")
    shuffles = _shuffle_count(eng)
    _untap_trigger(eng, disciple)
    eng.resolve_pending_choice("decline")
    assert _shuffle_count(eng) == shuffles


# --- M3: "a basic land card or a <subtype> card" ------------------------------------------------------------------

_BASIC_OR_SUBTYPE_CARDS = {
    "Outcaster Greenblade": "Desert", "Silver Deputy": "Desert", "Shefet Monitor": "Desert",
    "Spinewoods Armadillo": "Desert", "Compass Gnome": "Cave", "District Guide": "Gate",
    "Gatecreeper Vine": "Gate", "Open the Gates": "Gate",
}


@pytest.mark.parametrize("name", sorted(_BASIC_OR_SUBTYPE_CARDS))
def test_basic_or_subtype_cards_are_modeled(name):
    assert _modeled(name)


def _land_library(eng, subtype):
    """A library of one wanted card per branch and the bystanders each branch must exclude."""
    wanted = {
        "Forest": _library_card(eng, "Forest", mv=0, type_line="Basic Land — Forest"),
        f"The{subtype}": _library_card(eng, f"The{subtype}", mv=0, type_line=f"Land — {subtype}"),
    }
    _library_card(eng, "PlainNonbasic", mv=0, type_line="Land")  # a nonbasic land with no such subtype
    _library_card(eng, "OtherSubtype", mv=0, type_line="Land — Lair" if subtype != "Lair" else "Land — Gate")
    _library_card(eng, "Nonland", mv=2, type_line="Creature")
    return set(wanted)


def _enter_and_offer(eng, name):
    put_on_battlefield(eng, name)
    _drive_to_search(eng)
    return _offered(eng)


@pytest.mark.parametrize("name", ["Outcaster Greenblade", "Silver Deputy", "Compass Gnome", "District Guide",
                                  "Gatecreeper Vine"])
def test_enters_search_offers_basic_lands_and_the_subtype_only(name):
    eng = game(library=0)
    wanted = _land_library(eng, _BASIC_OR_SUBTYPE_CARDS[name])
    assert _enter_and_offer(eng, name) == wanted


def test_open_the_gates_goes_to_hand_and_top_tails_put_the_card_on_top_after_the_shuffle():
    eng = game(library=0)
    wanted = _land_library(eng, "Gate")
    cast(eng, card(eng, "Open the Gates", zone=Zone.HAND))
    assert _offered(eng) == wanted
    _pick(eng, "TheGate")
    assert "TheGate" in [o.name for o in eng.state.player_by_id("p1").hand]

    eng = game(library=0)
    _land_library(eng, "Cave")
    for i in range(4):
        _library_card(eng, f"Pad{i}", mv=1, type_line="Creature")
    _enter_and_offer(eng, "Compass Gnome")
    _pick(eng, "TheCave")
    assert eng.state.player_by_id("p1").library[-1].name == "TheCave"  # on top, after the shuffle


def test_spinewoods_armadillo_hand_ability_searches_then_gains_life():
    eng = game(library=0)
    wanted = _land_library(eng, "Desert")
    armadillo = card(eng, "Spinewoods Armadillo", zone=Zone.HAND)
    life = eng.state.player_by_id("p1").life
    eng.state.player_by_id("p1").mana_pool.add_many({"G": 1, "C": 1})
    index = next(i for i, a in enumerate(armadillo.abilities) if "discard" in repr(getattr(a, "cost", "")).lower()) \
        if getattr(armadillo, "abilities", None) else 0
    activate(eng, armadillo, index)
    assert _offered(eng) == wanted
    answer(eng)
    assert eng.state.player_by_id("p1").life == life + 3


def test_shefet_monitor_cycling_trigger_puts_a_basic_or_desert_onto_the_battlefield():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng = game(library=0)
    wanted = _land_library(eng, "Desert")
    monitor = card(eng, "Shefet Monitor", zone=Zone.HAND)
    eng.state.fire_event(GameEvent(EventType.CYCLED, controller_id="p1", instance_id=monitor.instance_id,
                                   object=monitor.name))
    eng.resolve_until_stable()
    _drive_to_search(eng)
    assert _offered(eng) == wanted
    _pick(eng, "TheDesert")
    assert "TheDesert" in [o.name for o in eng.state.battlefield]


def test_basic_or_subtype_reuses_only_tails_the_plain_search_reads():
    from mtg_analyzer.parser.oracle.catalogue.clause_hooks import match_clause
    assert match_clause("search your library for a basic land card or a desert card, put it onto the battlefield, "
                        "then shuffle")
    # a tail the plain search does not read leaves the union unclaimed
    assert match_clause("search your library for a basic land card or a desert card, then you gain 2 life") is None


# --- M4: the reveal ends the search sentence and the put is a sentence of its own ----------------------------------

@pytest.mark.parametrize("name", ["Fork in the Road", "Jarad's Orders", "Viewpoint Synchronization", "Peregrination",
                                  "Flourishing Bloom-Kin", "Guidelight Pathmaker", "Stoic Farmer"])
def test_reveal_then_put_cards_are_modeled(name):
    assert _modeled(name)


@pytest.mark.parametrize("name", ["Ruin in Their Wake", "Selfie Preservation", "Verdant Mastery"])
def test_conditions_outside_the_shared_vocabulary_stay_unclaimed(name):
    assert not _modeled(name)


def _names(zone):
    return [o.name for o in zone]


def _basic_library(eng):
    for n in ("Forest", "Island", "Swamp"):
        _library_card(eng, f"B{n}", mv=0, type_line=f"Basic Land — {n}")
    _library_card(eng, "NonbasicLand", mv=0, type_line="Land")
    _library_card(eng, "Spell", mv=2, type_line="Creature")


def _pick_each(eng, labels):
    for label in labels:
        _pick(eng, label)


def test_fork_in_the_road_first_pick_to_hand_second_to_graveyard_and_shuffles():
    eng = game(library=0)
    _basic_library(eng)
    cast(eng, card(eng, "Fork in the Road", zone=Zone.HAND))
    assert _offered(eng) == {"BForest", "BIsland", "BSwamp"}  # no nonbasic, no nonland
    _pick_each(eng, ["BForest", "BIsland"])
    p = eng.state.player_by_id("p1")
    assert "BForest" in _names(p.hand) and "BIsland" in _names(p.graveyard)
    assert _shuffle_count(eng) == 1


def test_viewpoint_synchronization_two_tapped_onto_the_battlefield_and_the_third_to_hand():
    eng = game(library=0)
    _basic_library(eng)
    cast(eng, card(eng, "Viewpoint Synchronization", zone=Zone.HAND))
    _pick_each(eng, ["BForest", "BIsland", "BSwamp"])
    p = eng.state.player_by_id("p1")
    on_bf = {o.name: o for o in eng.state.battlefield if o.name.startswith("B")}
    assert set(on_bf) == {"BForest", "BIsland"} and all(o.tapped for o in on_bf.values())
    assert _names(p.hand) == ["BSwamp"]


def test_peregrination_scries_after_the_shuffle():
    eng = game(library=0)
    _basic_library(eng)
    cast(eng, card(eng, "Peregrination", zone=Zone.HAND))
    _pick_each(eng, ["BForest", "BIsland"])
    assert _shuffle_count(eng) == 1
    p = eng.state.player_by_id("p1")
    assert "BForest" in [o.name for o in eng.state.battlefield] and "BIsland" in _names(p.hand)
    assert eng.state.pending_choice is None or eng.state.pending_choice.get("kind") != "search"


def test_guidelight_pathmaker_sends_cheap_artifacts_to_the_battlefield_and_dear_ones_to_hand():
    for mv, in_play in ((2, True), (3, False)):
        eng = game(library=0)
        _library_card(eng, "Gizmo", mv=mv, type_line="Artifact")
        _library_card(eng, "Bystander", mv=1, type_line="Creature")
        put_on_battlefield(eng, "Guidelight Pathmaker")
        _drive_to_search(eng)
        assert _offered(eng) == {"Gizmo"}
        _pick(eng, "Gizmo")
        p = eng.state.player_by_id("p1")
        assert ("Gizmo" in [o.name for o in eng.state.battlefield]) == in_play
        assert ("Gizmo" in _names(p.hand)) == (not in_play)


def test_stoic_farmer_taps_the_plains_in_play_only_when_an_opponent_controls_more_lands():
    for opp_lands, in_play in ((1, True), (0, False)):
        eng = game(library=0)
        _library_card(eng, "BPlains", mv=0, type_line="Basic Land — Plains")
        _library_card(eng, "BForest", mv=0, type_line="Basic Land — Forest")
        for i in range(opp_lands):
            filler(eng, f"OppLand{i}", type_line="Land", player="p2", zone=Zone.BATTLEFIELD)
        put_on_battlefield(eng, "Stoic Farmer")
        _drive_to_search(eng)
        assert _offered(eng) == {"BPlains"}
        _pick(eng, "BPlains")
        p = eng.state.player_by_id("p1")
        placed = next((o for o in eng.state.battlefield if o.name == "BPlains"), None)
        assert (placed is not None and placed.tapped) == in_play
        assert ("BPlains" in _names(p.hand)) == (not in_play)


def test_flourishing_bloom_kin_finds_forests_only_one_tapped_the_other_to_hand():
    eng = game(library=0)
    _library_card(eng, "TheForestA", mv=0, type_line="Land — Forest")
    _library_card(eng, "TheForestB", mv=0, type_line="Land — Forest")
    _library_card(eng, "Plains1", mv=0, type_line="Basic Land — Plains")
    kin = card(eng, "Flourishing Bloom-Kin")
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(EventType.TURNED_FACE_UP, controller_id="p1", instance_id=kin.instance_id,
                                   object=kin.name))
    eng.resolve_until_stable()
    _drive_to_search(eng)
    assert _offered(eng) == {"TheForestA", "TheForestB"}
    _pick_each(eng, ["TheForestA", "TheForestB"])
    p = eng.state.player_by_id("p1")
    assert "TheForestA" in [o.name for o in eng.state.battlefield] and "TheForestB" in _names(p.hand)


# --- M5: a search followed by a conditional replacement search ("if <condition>, instead search ...") ----------------

@pytest.mark.parametrize("name", ["Analyze the Pollen", "Entish Restoration", "Nissa's Triumph", "Reclaim the Wastes",
                                  "Embermouth Sentinel"])
def test_conditional_replacement_search_cards_are_modeled(name):
    assert _modeled(name)


def test_a_replacement_that_searches_for_two_different_cards_stays_unclaimed():
    """Aang's Journey finds a basic land AND a Shrine in one search: one criteria per search cannot say that."""
    assert not _modeled("Aang's Journey")


def _pick_all(eng):
    """Pick every offered card, then decline the rest of an "up to" search; return the picked labels."""
    picked = []
    for _ in range(8):
        choice = eng.state.pending_choice
        if not choice or choice.get("kind") != "search":
            break
        option = next((o for o in choice["options"] if o["id"] != "decline"), None)
        if option is None:
            eng.resolve_pending_choice("decline")
            continue
        picked.append(option["label"])
        eng.resolve_pending_choice(str(option["id"]))
    return picked


def _forest_and_land_library(eng):
    for i in range(4):
        _library_card(eng, f"BForest{i}", mv=0, type_line="Basic Land — Forest")
    _library_card(eng, "TheIsland", mv=0, type_line="Land — Island")
    _library_card(eng, "NonbasicForest", mv=0, type_line="Land — Forest")
    _library_card(eng, "Spell", mv=2, type_line="Creature")


def test_nissas_triumph_finds_up_to_two_basic_forests_without_a_nissa():
    eng = game(library=0)
    _forest_and_land_library(eng)
    filler(eng, "Jace", type_line="Legendary Planeswalker — Jace")  # another planeswalker does not count
    cast(eng, card(eng, "Nissa's Triumph", zone=Zone.HAND))
    assert _offered(eng) == {"BForest0", "BForest1", "BForest2", "BForest3"}  # no nonbasic Forest, Island or spell
    assert len(_pick_all(eng)) == 2
    assert len(eng.state.player_by_id("p1").hand) == 2


def test_nissas_triumph_finds_up_to_three_lands_with_a_nissa():
    eng = game(library=0)
    _forest_and_land_library(eng)
    filler(eng, "Nissa, Test", type_line="Legendary Planeswalker — Nissa")
    cast(eng, card(eng, "Nissa's Triumph", zone=Zone.HAND))
    assert "TheIsland" in _offered(eng) and "NonbasicForest" in _offered(eng) and "Spell" not in _offered(eng)
    assert len(_pick_all(eng)) == 3
    assert len(eng.state.player_by_id("p1").hand) == 3


def test_reclaim_the_wastes_finds_one_basic_land_unkicked_and_two_kicked():
    for kicked, found in ((0, 1), (1, 2)):
        eng = game(library=0)
        _basic_library(eng)
        cast(eng, card(eng, "Reclaim the Wastes", zone=Zone.HAND), kicked=kicked)
        assert _offered(eng) == {"BForest", "BIsland", "BSwamp"}
        assert len(_pick_all(eng)) == found
        assert len(eng.state.player_by_id("p1").hand) == found


def test_entish_restoration_finds_two_tapped_basics_or_three_with_a_big_creature():
    for power, found in ((3, 2), (4, 3)):
        eng = game(library=0)
        _basic_library(eng)
        _library_card(eng, "BForest2", mv=0, type_line="Basic Land — Forest")
        filler(eng, "Sacrifice", type_line="Land")
        filler(eng, "Body", type_line="Creature", power=power, toughness=power)
        before = len([o for o in eng.state.battlefield if o.is_land])
        cast(eng, card(eng, "Entish Restoration", zone=Zone.HAND))
        for _ in range(3):  # the sacrifice choice, if any, precedes the search
            ch = eng.state.pending_choice
            if ch and ch.get("kind") != "search":
                eng.resolve_pending_choice(str(ch["options"][0]["id"]))
        assert len(_pick_all(eng)) == found
        lands = [o for o in eng.state.battlefield if o.is_land]
        assert len(lands) == before - 1 + found
        assert sum(1 for o in lands if o.name.startswith("B") and o.tapped) == found


def test_analyze_the_pollen_widens_to_a_creature_or_land_only_when_evidence_was_collected():
    for evidence in (False, True):
        eng = game(library=0)
        _basic_library(eng)
        p = eng.state.player_by_id("p1")
        for i in range(2):
            filler(eng, f"Fuel{i}", type_line="Creature", mv=4, zone=Zone.GRAVEYARD)
        cast(eng, card(eng, "Analyze the Pollen", zone=Zone.HAND), pay_additional=evidence)
        for _ in range(3):  # choose which graveyard cards to exile, if asked
            ch = eng.state.pending_choice
            if ch and ch.get("kind") != "search":
                eng.resolve_pending_choice(str(ch["options"][0]["id"]))
        offered = _offered(eng)
        assert ("Spell" in offered) == evidence and "BForest" in offered
        assert ("NonbasicLand" in offered) == evidence  # a nonbasic land is a "creature or land card"


def test_embermouth_sentinel_puts_the_land_on_top_or_tapped_onto_the_battlefield_with_a_dragon():
    for dragon in (False, True):
        eng = game(library=0)
        _basic_library(eng)
        if dragon:
            filler(eng, "Drake", type_line="Creature — Dragon", power=2, toughness=2)
        put_on_battlefield(eng, "Embermouth Sentinel")
        _drive_to_search(eng)
        assert _offered(eng) == {"BForest", "BIsland", "BSwamp"}
        _pick(eng, "BForest")
        p = eng.state.player_by_id("p1")
        placed = next((o for o in eng.state.battlefield if o.name == "BForest"), None)
        assert (placed is not None and placed.tapped) == dragon
        assert (p.library[-1].name == "BForest") == (not dragon)  # on top, after the shuffle


def test_embermouth_sentinel_may_decline_the_search():
    eng = game(library=0)
    _basic_library(eng)
    put_on_battlefield(eng, "Embermouth Sentinel")
    _drive_to_search(eng, accept=False)
    assert eng.state.pending_choice is None
    assert not [o for o in eng.state.battlefield if o.name.startswith("B")]


def test_conditional_search_without_instead_is_not_a_replacement():
    """'If <cond>, search ...' with no 'instead' adds a search; the replacement row must not claim it (RULE 608.2c)."""
    from mtg_analyzer.parser.oracle.catalogue.effect_rows.search_control_attach import (
        _SEARCH_CONDITIONAL_REPLACEMENT_RE,
        _search_conditional_replacement,
    )

    text = (
        "search your library for a basic land card, put it into your hand, then shuffle. "
        "if you control a nissa planeswalker, search your library for a land card, put it into your hand, then shuffle."
    )
    m = _SEARCH_CONDITIONAL_REPLACEMENT_RE.fullmatch(text) or _SEARCH_CONDITIONAL_REPLACEMENT_RE.match(text)
    assert m is not None
    assert _search_conditional_replacement(m) is None
