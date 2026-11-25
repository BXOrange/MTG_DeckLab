"""PAR-292 M26: "look at the top card of target / each player's library" + "you may put that card into their graveyard /
on the bottom of that player's library" (RULE 701.20, 400.2, 400.3). The looker decides; the card goes to its owner's zone."""
import pytest

from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.game_session import GameSession
from tests.support.deck_batch import answer, game, filler, card, cast

GRAVEYARD_TEXT = "look at the top card of target player's library. you may put that card into their graveyard"
BOTTOM_TEXT = "look at the top card of target opponent's library. you may put that card on the bottom of that player's library"


def _top(eng, player, name="Top"):
    return filler(eng, name, player=player, zone=Zone.LIBRARY)


def _run(eng, text, target_id):
    from tests.test_par213_inspection import run
    return run(eng, text, targets=[eng.state.player_by_id(target_id)])


def test_peek_then_mill_the_targets_card_goes_to_its_owners_graveyard():
    eng = game(library=3)
    top = _top(eng, "p2")
    _run(eng, GRAVEYARD_TEXT, "p2")
    assert eng.state.pending_choice["player_id"] == "p1"          # the looker decides, not the library's owner
    eng.resolve_pending_choice("done")
    assert eng.state.pending_choice["mode"] == "choose"
    eng.resolve_pending_choice(str(top.instance_id))
    assert top in eng.state.player_by_id("p2").graveyard and top not in eng.state.player_by_id("p1").graveyard
    assert top not in eng.state.player_by_id("p2").library


def test_decline_leaves_the_card_on_top():
    eng = game(library=3)
    top = _top(eng, "p2")
    _run(eng, GRAVEYARD_TEXT, "p2")
    eng.resolve_pending_choice("done")
    eng.resolve_pending_choice("decline")
    assert eng.state.player_by_id("p2").library[-1] is top and not eng.state.player_by_id("p2").graveyard


def test_bottom_goes_under_the_owners_library():
    eng = game(library=3)
    top = _top(eng, "p2")
    _run(eng, BOTTOM_TEXT, "p2")
    eng.resolve_pending_choice("done")
    eng.resolve_pending_choice(str(top.instance_id))
    assert eng.state.player_by_id("p2").library[0] is top


def test_empty_library_does_nothing():
    eng = game(library=0)
    _run(eng, GRAVEYARD_TEXT, "p2")
    assert eng.state.pending_choice is None


def test_a_look_is_private_to_the_looker_and_not_public_knowledge():
    eng = game(library=3)
    top = _top(eng, "p2")
    _run(eng, GRAVEYARD_TEXT, "p2")
    session = GameSession(eng)
    seen = {}
    for viewer in ("p1", "p2"):
        state = session.view(perspective=viewer)["state"]
        library = next(p["library"] for p in state["players"] if p["id"] == "p2")
        seen[viewer] = {o["instance_id"] for o in library}
    assert seen["p1"] == {top.instance_id}
    assert seen["p2"] == set()                                     # the owner learns nothing from being looked at
    assert top.instance_id not in eng.state.public_card_knowledge.cards   # only a reveal is public (RULE 701.20)


def test_the_opponent_cannot_answer_for_the_looker():
    eng = game(library=3)
    _top(eng, "p2")
    _run(eng, GRAVEYARD_TEXT, "p2")
    session = GameSession(eng)
    assert [a["type"] for a in session.legal_actions("p2")] == []
    assert session.legal_actions("p1")


def test_each_players_top_card_is_looked_at():
    eng = game(players=3, library=3)
    tops = [_top(eng, p, "Top" + p) for p in ("p1", "p2", "p3")]
    from tests.test_par213_inspection import run
    run(eng, "draw 2 cards, then look at the top card of each player's library")
    choice = eng.state.pending_choice
    assert choice["kind"] == "inspection" and choice["player_id"] == "p1"


def test_optional_look_has_a_gate_that_shows_nothing_first():
    eng = game(library=3)
    top = _top(eng, "p2")
    text = ("you may look at the top card of target opponent's library. if you do, you may put that card on the bottom "
            "of that player's library")
    _run(eng, text, "p2")
    choice = eng.state.pending_choice
    assert choice["mode"] == "look_gate" and all("card_id" not in o for o in choice["options"])
    session = GameSession(eng)
    library = next(p["library"] for p in session.view(perspective="p1")["state"]["players"] if p["id"] == "p2")
    assert not library
    eng.resolve_pending_choice("look")
    assert eng.state.pending_choice["mode"] == "ack"
    eng.resolve_pending_choice("done")
    eng.resolve_pending_choice(str(top.instance_id))
    assert eng.state.player_by_id("p2").library[0] is top


def test_declining_the_optional_look_ends_it():
    eng = game(library=3)
    top = _top(eng, "p2")
    _run(eng, "you may look at the top card of target opponent's library. if you do, you may put that card on the bottom "
              "of that player's library", "p2")
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None and eng.state.player_by_id("p2").library[-1] is top


@pytest.mark.parametrize("name", ["Eye Spy", "Lurking Informant", "Draugr Thought-Thief", "Case the Joint", "Precognition"])
def test_real_cards_are_modeled(name):
    from mtg_analyzer.parser.oracle import parse_oracle
    from tests.test_mec118_opponent_choice import _db_card
    result = parse_oracle(_db_card(name))
    assert result.modeled, result.unclaimed


def test_eye_spy_cast_end_to_end():
    eng = game(library=3)
    top = _top(eng, "p2")
    spell = card(eng, "Eye Spy", zone=Zone.HAND)
    cast(eng, spell, targets=[eng.state.player_by_id("p2")])
    eng.resolve_pending_choice("done")
    eng.resolve_pending_choice(str(top.instance_id))
    assert top in eng.state.player_by_id("p2").graveyard


@pytest.mark.parametrize("text", [
    "look at the top card of target player's library. you may put that card onto the battlefield",
    "look at the top 2 cards of target player's library. you may put that card into their graveyard",
    "look at the top card of each player's library. you may put that card into their graveyard",
])
def test_unsupported_shapes_refuse(text):
    assert parse_effect_body(text) is None


def test_a_bot_answers_the_look_through_legal_actions():
    """The decision is offered as plain legal actions to the looker (a bot sees nothing else) and applies through them."""
    eng = game(library=3)
    top = _top(eng, "p2")
    _run(eng, GRAVEYARD_TEXT, "p2")
    session = GameSession(eng)
    for _ in range(4):
        if eng.state.pending_choice is None:
            break
        actions = session.legal_actions("p1")
        assert actions, eng.state.pending_choice
        pick = next((a for a in actions if a["type"] == "choose" and str(a.get("option_id", a.get("id", ""))) == str(top.instance_id)), actions[0])
        session.apply_action(pick, actor_id="p1")
    assert eng.state.pending_choice is None


# --- the face-down exile variants (RULE 406.3, 701.20) ---------------------------------------------------------

def _extract_power_board():
    eng = game(library=3)
    mine = filler(eng, "MyTop", type_line="Instant", player="p1", zone=Zone.LIBRARY, mv=1)
    theirs = filler(eng, "TheirTop", type_line="Land", player="p2", zone=Zone.LIBRARY)
    cast(eng, card(eng, "Extract Power", zone=Zone.HAND))
    return eng, mine, theirs


def test_extract_power_exiles_every_top_card_face_down_and_the_exiler_plays_them_free():
    eng, mine, theirs = _extract_power_board()
    assert mine.zone == theirs.zone == Zone.EXILE and mine.face_down_in_exile and theirs.face_down_in_exile
    p1 = eng.state.player_by_id("p1")
    eng.play_land(p1, theirs)                                   # the opponent's land, played from exile
    assert theirs.zone == Zone.BATTLEFIELD and theirs.controller_id == "p1"
    eng.cast_spell(p1, mine)                                    # free: the pool is empty
    eng.resolve_until_stable()
    assert mine.zone == Zone.GRAVEYARD


def test_a_face_down_card_of_another_library_is_known_to_the_exiler_only():
    eng, mine, theirs = _extract_power_board()
    session = GameSession(eng)
    names = {}
    for viewer in ("p1", "p2"):
        state = session.view(perspective=viewer)["state"]
        names[viewer] = {o["instance_id"]: o["name"] for pl in state["players"] for o in pl["exile"]}
    assert names["p1"][theirs.instance_id] == "TheirTop"
    assert names["p2"][theirs.instance_id] == "" and names["p2"][mine.instance_id] == ""
    assert theirs.instance_id not in eng.state.public_card_knowledge.cards


def test_the_exiler_is_offered_the_play_through_legal_actions():
    eng, mine, theirs = _extract_power_board()
    session = GameSession(eng)
    offered = {a["instance_id"] for a in session.legal_actions("p1") if a["type"] in ("cast_spell", "play_land")}
    assert {mine.instance_id, theirs.instance_id} <= offered
    assert not any(a["type"] in ("cast_spell", "play_land") for a in session.legal_actions("p2"))


def test_rev_exiles_the_damaged_players_top_card_not_the_controllers():
    eng = game(players=3, library=4)
    rev = card(eng, "Rev, Tithe Extractor")
    mine = filler(eng, "MyTop", player="p1", zone=Zone.LIBRARY)
    hit = filler(eng, "HitTop", player="p2", zone=Zone.LIBRARY)
    other = filler(eng, "OtherTop", player="p3", zone=Zone.LIBRARY)
    eng.resolve_until_stable()
    eng.rules.deal_combat_damage([(eng.state.player_by_id("p2"), 3, rev)])
    eng.resolve_until_stable()
    answer(eng)
    assert hit.zone == Zone.EXILE and hit.face_down_in_exile and hit.face_down_exile_viewers == {"p1"}
    assert mine.zone == Zone.LIBRARY and other.zone == Zone.LIBRARY


@pytest.mark.parametrize("name", ["Extract Power", "Rev, Tithe Extractor"])
def test_face_down_variants_are_modeled(name):
    from mtg_analyzer.parser.oracle import parse_oracle
    from tests.test_mec118_opponent_choice import _db_card
    result = parse_oracle(_db_card(name))
    assert result.modeled, result.unclaimed


def test_blightwing_bandits_that_player_is_not_the_caster_so_it_stays_unclaimed():
    """RULE 603.2c: the SPELL_CAST antecedent is the caster (you), but the printed "that player" is the opponent."""
    from mtg_analyzer.parser.oracle import parse_oracle
    from tests.test_mec118_opponent_choice import _db_card
    assert not parse_oracle(_db_card("Blightwing Bandit")).modeled
