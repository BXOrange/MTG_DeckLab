"""PAR-292 M28: "search your graveyard, hand, and/or library for <criteria>. If you search your library this way, shuffle."

RULE 701.23a: searching is looking through the cards of a zone; the player names which of the zones to look through.
RULE 701.23b: a hidden zone (library, hand) may be searched without finding a card that is there; a public zone
(graveyard) may not. RULE 701.24a: the library is shuffled when the effect says so, and the card says so only for the
case that the library was searched, so a find from the graveyard alone leaves the library alone."""
import pytest

from mtg_analyzer.models.cards import card_query
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.deck_batch import card, enter, filler, game
from tests.test_mec118_opponent_choice import _db_card

CLAIMED = ["Agency Outfitter", "Fang-Druid Summoner", "Mishra, Artificer Prodigy"]
#: Each one needs a second new piece that only this card prints (singletons.md "Library residue").
STILL_OPEN = ["Arachnus Spinner", "Say Its Name"]


@pytest.fixture
def shuffles(monkeypatch):
    """The ids of the players whose library was shuffled, in order."""
    from mtg_analyzer.models.game.player import Player
    seen: list[str] = []
    real = Player.shuffle_library
    monkeypatch.setattr(Player, "shuffle_library", lambda self: (seen.append(self.id), real(self))[1])
    return seen


@pytest.mark.parametrize("name", CLAIMED)
def test_real_cards_are_modeled(name):
    result = parse_oracle(_db_card(name))
    assert result.modeled, result.unclaimed


@pytest.mark.parametrize("name", STILL_OPEN)
def test_cards_with_a_second_new_clause_stay_unmodeled(name):
    assert not parse_oracle(_db_card(name)).modeled


def _search_params(text):
    specs = parse_effect_body(text)
    assert specs and len(specs) == 1 and specs[0].type == "search", specs
    return specs[0].params


def test_the_zone_union_reuses_the_library_search_grammar():
    params = _search_params(
        "search your graveyard, hand, and/or library for a creature card with no abilities, reveal it, and put it into "
        "your hand. if you search your library this way, shuffle")
    assert params["zones"] == ["graveyard", "hand", "library"] and params["choose_zones"] is True
    assert params["criteria"] == {"type": "creature", "no_abilities": True}
    assert params["reveal"] is True and params["destination"] == "hand"


def test_the_existing_library_and_graveyard_family_names_its_zones_too():
    params = _search_params(
        "search your library and/or graveyard for a creature card, reveal it, and put it into your hand. "
        "if you search your library this way, shuffle")
    assert params["zones"] == ["library", "graveyard"] and params["choose_zones"] is True


@pytest.mark.parametrize("text", [
    # A search that never names the library has no library shuffle to condition.
    "search your graveyard and/or hand for a creature card and put it onto the battlefield. if you search your library this way, shuffle",
    "search your library, library, and/or graveyard for a card and put it into your hand. if you search your library this way, shuffle",
    "search your graveyard and/or library for a card with no flavor and put it into your hand. if you search your library this way, shuffle",
])
def test_unsupported_zone_unions_are_refused(text):
    assert parse_effect_body(text) is None


def test_a_plain_library_search_keeps_the_library_only_form():
    params = _search_params("search your library for a creature card with no abilities, put it into your hand, then shuffle")
    assert "zones" not in params and "choose_zones" not in params and params["criteria"]["no_abilities"] is True


def test_no_abilities_matches_only_a_card_with_empty_rules_text():
    bear = Card(id="b", name="Bear", type_line="Creature — Bear", is_creature=True, oracle_text="")
    reach = Card(id="s", name="Spider", type_line="Creature — Spider", is_creature=True, oracle_text="Reach", keywords=["Reach"])
    assert card_query.matches(bear, {"no_abilities": True, "type": "creature"})
    assert not card_query.matches(reach, {"no_abilities": True, "type": "creature"})


# ---- Agency Outfitter: two named cards, three zones ------------------------------------------------------------------

def _outfitter_setup(*, glass=Zone.GRAVEYARD, cap=Zone.LIBRARY, library=3):
    eng = game(library=library)
    g = filler(eng, "Magnifying Glass", type_line="Artifact", zone=glass) if glass else None
    c = filler(eng, "Thinking Cap", type_line="Artifact", zone=cap) if cap else None
    return eng, g, c


def _zone_choice(eng):
    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "search_zones", choice
    return choice


def _enter_outfitter(eng):
    enter(eng, card(eng, "Agency Outfitter"))
    choice = eng.state.pending_choice
    if choice and choice["kind"] == "trigger_target":  # the "you may" of the trigger
        eng.resolve_pending_choice("do")


def _finish(eng, limit=8):
    for _ in range(limit):
        choice = eng.state.pending_choice
        if choice is None:
            return
        eng.resolve_pending_choice(str(choice["options"][0]["id"]))


def test_the_player_is_offered_every_combination_of_the_zones_worth_searching(shuffles):
    eng, glass, cap = _outfitter_setup()
    _enter_outfitter(eng)
    assert [o["id"] for o in _zone_choice(eng)["options"]] == ["graveyard", "library", "graveyard+library"]


def test_searching_only_the_graveyard_finds_there_and_leaves_the_library_unshuffled(shuffles):
    eng, glass, cap = _outfitter_setup()
    _enter_outfitter(eng)
    eng.resolve_pending_choice("graveyard")
    _finish(eng)
    assert glass.zone == Zone.BATTLEFIELD and glass in eng.state.battlefield
    assert cap.zone == Zone.LIBRARY  # the library was never looked at
    assert shuffles == []


def test_searching_only_the_library_shuffles_it_and_cannot_reach_the_graveyard(shuffles):
    eng, glass, cap = _outfitter_setup()
    _enter_outfitter(eng)
    eng.resolve_pending_choice("library")
    _finish(eng)
    assert cap in eng.state.battlefield and glass.zone == Zone.GRAVEYARD
    assert shuffles == ["p1"]


def test_searching_both_finds_one_card_in_each_and_shuffles_once(shuffles):
    eng, glass, cap = _outfitter_setup()
    _enter_outfitter(eng)
    eng.resolve_pending_choice("graveyard+library")
    _finish(eng)
    assert glass in eng.state.battlefield and cap in eng.state.battlefield
    assert shuffles == ["p1"]


def test_the_hand_is_a_zone_to_search_and_hidden_so_it_may_be_skipped(shuffles):
    eng, glass, cap = _outfitter_setup(glass=Zone.HAND, cap=Zone.HAND)
    _enter_outfitter(eng)
    ids = [o["id"] for o in _zone_choice(eng)["options"]]
    assert ids == ["hand", "library", "hand+library"]
    eng.resolve_pending_choice("hand")
    _finish(eng)
    assert glass in eng.state.battlefield and cap in eng.state.battlefield and shuffles == []


def test_a_library_search_that_finds_nothing_still_shuffles(shuffles):
    eng, glass, cap = _outfitter_setup(glass=None, cap=None)
    filler(eng, "Unrelated", type_line="Artifact", zone=Zone.GRAVEYARD)
    _enter_outfitter(eng)
    assert eng.state.pending_choice is None  # nothing public to find: the library is the only zone worth naming
    assert shuffles == ["p1"]


def test_an_empty_graveyard_and_hand_leave_no_zone_to_choose(shuffles):
    eng, glass, cap = _outfitter_setup(glass=None, cap=Zone.LIBRARY)
    _enter_outfitter(eng)
    choice = eng.state.pending_choice
    assert choice is None or choice["kind"] == "search"
    _finish(eng)
    assert cap in eng.state.battlefield and shuffles == ["p1"]


def test_a_public_zone_with_no_match_is_not_offered():
    eng, glass, cap = _outfitter_setup(glass=None)
    filler(eng, "Unrelated", type_line="Artifact", zone=Zone.GRAVEYARD)
    _enter_outfitter(eng)
    assert eng.state.pending_choice is None or eng.state.pending_choice["kind"] != "search_zones"


def test_a_public_zone_find_cannot_be_declined_once_only_it_was_searched():
    """RULE 701.23b: only a hidden zone lets the searcher miss a card that is there."""
    from tests.support.deck_batch import game as new_game
    eng = new_game(library=3)
    bear = filler(eng, "Bear", type_line="Creature", zone=Zone.GRAVEYARD, power=2, toughness=2)
    eng.rules._request_search(eng.state.player_by_id("p1"), {"type": "creature"}, "hand", 1, True,
                              zones=["graveyard", "library"], choose_zones=True)
    eng.resolve_pending_choice("graveyard")
    options = [o["id"] for o in eng.state.pending_choice["options"]]
    assert options == [str(bear.instance_id)]  # no "decline"
    eng.resolve_pending_choice(str(bear.instance_id))
    assert bear in eng.state.player_by_id("p1").hand


def test_a_hidden_zone_find_can_still_be_declined(shuffles):
    eng = game(library=3)
    filler(eng, "Bear", type_line="Creature", zone=Zone.LIBRARY, power=2, toughness=2)
    eng.rules._request_search(eng.state.player_by_id("p1"), {"type": "creature"}, "hand", 1, True,
                              zones=["graveyard", "library"], choose_zones=True)
    assert eng.state.pending_choice["kind"] == "search"  # only the library is worth naming
    assert "decline" in [o["id"] for o in eng.state.pending_choice["options"]]
    eng.resolve_pending_choice("decline")
    assert shuffles == ["p1"]


def test_a_refused_zone_answer_leaves_the_prompt_pending():
    eng, glass, cap = _outfitter_setup()
    _enter_outfitter(eng)
    with pytest.raises(ValueError):
        eng.resolve_pending_choice("exile")
    assert eng.state.pending_choice["kind"] == "search_zones"


def test_the_zone_prompt_survives_a_snapshot_round_trip():
    import copy
    eng, glass, cap = _outfitter_setup()
    _enter_outfitter(eng)
    saved = copy.deepcopy(eng.state.pending_choice)
    assert saved == eng.state.pending_choice and saved["request"]["criteria_each"]


# ---- Fang-Druid Summoner: no abilities, revealed ----------------------------------------------------------------------

def test_fang_druid_summoner_finds_only_a_vanilla_creature_and_reveals_it(shuffles):
    eng = game(library=3)
    vanilla = filler(eng, "Grizzly", type_line="Creature — Bear", zone=Zone.GRAVEYARD, power=2, toughness=2,
                     oracle_text="")
    keyworded = filler(eng, "Spider", type_line="Creature — Spider", zone=Zone.GRAVEYARD, power=1, toughness=1,
                       oracle_text="Reach", keywords=["Reach"])
    enter(eng, card(eng, "Fang-Druid Summoner"))
    choice = eng.state.pending_choice
    if choice["kind"] == "trigger_target":
        eng.resolve_pending_choice("do")
    # The library holds only lands, so the graveyard is the one zone with a find; the library is still hidden.
    assert eng.state.pending_choice["kind"] == "search_zones"
    eng.resolve_pending_choice("graveyard")
    offered = [o["id"] for o in eng.state.pending_choice["options"]]
    assert offered == [str(vanilla.instance_id)] and str(keyworded.instance_id) not in offered
    eng.resolve_pending_choice(str(vanilla.instance_id))
    assert vanilla in eng.state.player_by_id("p1").hand and shuffles == []
    assert not eng.state.public_card_knowledge.cards  # a graveyard card is public anyway; nothing to record


def test_a_revealed_library_find_becomes_public_knowledge(shuffles):
    eng = game(library=3)
    vanilla = filler(eng, "Grizzly", type_line="Creature — Bear", zone=Zone.LIBRARY, power=2, toughness=2, oracle_text="")
    filler(eng, "Spider", type_line="Creature — Spider", zone=Zone.GRAVEYARD, power=1, toughness=1, oracle_text="Reach",
           keywords=["Reach"])
    enter(eng, card(eng, "Fang-Druid Summoner"))
    assert eng.state.pending_choice is not None
    if eng.state.pending_choice["kind"] == "trigger_target":
        eng.resolve_pending_choice("do")
    assert eng.state.pending_choice["kind"] == "search"  # the keyworded graveyard card is no find: only the library
    eng.resolve_pending_choice(str(vanilla.instance_id))
    assert vanilla in eng.state.player_by_id("p1").hand and shuffles == ["p1"]
    assert vanilla.instance_id in eng.state.public_card_knowledge.cards  # RULE 701.20: the revealed find is public


# ---- Mishra: the cast spell's name --------------------------------------------------------------------------------------

def test_mishra_searches_every_zone_for_the_cast_spells_name(shuffles):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng = game(library=3)
    mishra = card(eng, "Mishra, Artificer Prodigy")
    spell = filler(eng, "Bonesplitter", type_line="Artifact — Equipment", zone=Zone.HAND)
    copy_in_library = filler(eng, "Bonesplitter", type_line="Artifact — Equipment", zone=Zone.LIBRARY)
    other = filler(eng, "Sol Ring", type_line="Artifact", zone=Zone.LIBRARY)
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", card_id=spell.card.id, spell=spell.name,
                                   instance_id=spell.instance_id, object_types=["artifact"]))
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    if choice and choice["kind"] == "trigger_target":
        eng.resolve_pending_choice("do")
    assert eng.state.pending_choice["kind"] == "search_zones"
    # The cast spell itself is on the stack, not in the hand; only the library holds the other Bonesplitter.
    eng.resolve_pending_choice("library") if "library" in [o["id"] for o in eng.state.pending_choice["options"]] else None
    _finish(eng)
    assert copy_in_library in eng.state.battlefield and other.zone == Zone.LIBRARY
    assert shuffles == ["p1"]


# ---- a bot answers the zone prompt from legal_actions -------------------------------------------------------------------

def test_a_bot_answers_the_zone_prompt_from_its_own_view_and_legal_actions():
    from mtg_analyzer.services.bots import create_bot
    from mtg_analyzer.services.game_session import GameSessionManager

    session = GameSessionManager().create_multiplayer(
        [{"player_id": p, "name": p, "library": []} for p in ("p1", "p2")], mulligan_style="none", keep_history=False,
    )
    eng = session.engine
    for seat in ("p1", "p2"):
        session.apply_action({"type": "keep_hand", "bottom_count": 0}, actor_id=seat)
    me = eng.state.active_player.id
    other = next(x.id for x in eng.state.players if x.id != me)
    glass = filler(eng, "Magnifying Glass", type_line="Artifact", zone=Zone.GRAVEYARD, player=me)
    filler(eng, "Thinking Cap", type_line="Artifact", zone=Zone.LIBRARY, player=me)
    filler(eng, "Pad", type_line="Artifact", zone=Zone.LIBRARY, player=me)
    eng.rules._request_search(
        eng.state.player_by_id(me), "", "battlefield", 1, True, zones=["graveyard", "library"], choose_zones=True)
    assert eng.state.pending_choice["kind"] == "search_zones"
    assert not [a for a in session.legal_actions(perspective=other) if a["type"] == "choose"]
    actions = session.legal_actions(perspective=me)
    assert [a for a in actions if a["type"] == "choose"]
    action = create_bot("greedy", me).decide(session.view(perspective=me), actions)
    session.apply_action(action, actor_id=me)
    assert eng.state.pending_choice is None or eng.state.pending_choice["kind"] == "search"
