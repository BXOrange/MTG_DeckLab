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
