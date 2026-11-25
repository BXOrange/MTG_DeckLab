"""PAR-292 M29: the "from among them" picks after a dig.

(A) one card per class slot ("you may reveal a Cleric card, a Rogue card, a Warrior card, and/or a Wizard card from among
them and put those cards into your hand"; "mill five cards. You may put a creature card and/or a land card from among
them into your hand"): RULE 608.2c, each named slot is filled by at most one card and a card fills at most one slot.
(B) "reveal up to N / any number of <class> cards from among them, then put them on top of your library [in any order]
and the rest on the bottom": RULE 701.20 only the revealed cards are shown, RULE 401.4 the owner orders each pile."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.deck_batch import answer, card, filler, game, put_on_battlefield, stack_library
from tests.test_par292_dynamic_search_qualities import _modeled

CLAIMED = ("Harper Recruiter", "Kaalia, Zenith Seeker", "Sludge Titan", "Fertile Thicket", "Planar Atlas",
           "Munda, Ambush Leader")


@pytest.mark.parametrize("name", CLAIMED)
def test_real_cards_are_modeled(name):
    assert _modeled(name)


def test_eivor_stays_open_through_its_other_clause():
    # "you mill that many cards" (the combat damage dealt) is a different, one-card clause (singletons.md)
    assert not _modeled("Eivor, Wolf-Kissed")


@pytest.mark.parametrize("text", [
    "look at the top 4 cards of your library. you may reveal a cleric card, a cleric card and/or a wizard card from among "
    "them and put those cards into your hand. put the rest on the bottom of your library in a random order",
    # a union ("or"), not one card per slot, is the existing single pick
    "look at the top 4 cards of your library. you may reveal a cleric card or a wizard card from among them and put "
    "it into your hand. put the rest on the bottom of your library in a random order",
])
def test_slot_lists_and_unions_are_told_apart(text):
    specs = parse_effect_body(text)
    assert specs is not None
    params = specs[0].params
    assert ("pick_slots" in params) == ("and/or a wizard" in text)


def _slots_params(text):
    specs = parse_effect_body(text)
    assert specs and specs[0].type == "inspect_top_choose"
    return specs[0].params


def test_the_slot_list_parses_one_criteria_per_slot_and_a_revealed_pick():
    params = _slots_params(
        "look at the top 4 cards of your library. you may reveal a cleric card, a rogue card, a warrior card, and/or a "
        "wizard card from among them and put those cards into your hand. put the rest on the bottom of your library in "
        "a random order")
    assert params["pick_slots"] == [{"type": "cleric"}, {"type": "rogue"}, {"type": "warrior"}, {"type": "wizard"}]
    assert params["max_picks"] == 4 and params["optional"] is True
    assert params["action"] == "reveal_library_to_hand"  # RULE 701.20: only the picks are shown
    assert params["rest_destination"] == "library_bottom_random"
    assert params["criteria"] == {"or": params["pick_slots"]}


@pytest.mark.parametrize("text", [
    "look at the top 4 cards of your library. you may reveal a cleric card, a rogue card, a warrior card, a wizard card, "
    "and/or an elf card from among them and put those cards into your hand. put the rest on the bottom of your library "
    "in a random order",  # five slots: not a printed shape
    "look at the top 4 cards of your library. you may reveal a cleric card, a rogue creature and/or a wizard card from "
    "among them and put those cards into your hand. put the rest on the bottom of your library in a random order",
])
def test_unreadable_slot_lists_are_refused(text):
    assert parse_effect_body(text) is None


def _cast_stack(eng, *spec):
    """Stock the library; ``spec`` is (name, type line) listed bottom to top."""
    stack_library(eng, "p1", *[filler(eng, n, zone=Zone.LIBRARY, type_line=t) for n, t in spec])
    return eng.state.player_by_id("p1")


def _offered(eng):
    return sorted(o["label"] for o in eng.state.pending_choice["options"] if "instance_id" in o)


def _pick(eng, label):
    option = next(o for o in eng.state.pending_choice["options"] if o.get("label") == label)
    eng.rules.resolve_choice(option["instance_id"])
    eng.resolve_until_stable()


def _kaalia(eng):
    put_on_battlefield(eng, "Kaalia, Zenith Seeker")
    eng.resolve_until_stable()


def test_kaalia_takes_at_most_one_card_per_class_slot():
    eng = game(library=0)
    p = _cast_stack(eng, ("Deep", "Creature — Human"), ("Far", "Creature — Angel"), ("Angel B", "Creature — Angel"),
                    ("Demon A", "Creature — Demon"), ("Dragon A", "Creature — Dragon"), ("Angel A", "Creature — Angel"),
                    ("Bear", "Creature — Bear"))
    _kaalia(eng)
    assert eng.state.pending_choice["kind"] == "choose_objects"
    # the six looked-at cards: Bear, Angel A, Dragon A, Demon A, Angel B, Far; Deep is beyond them
    assert _offered(eng) == ["Angel A", "Angel B", "Demon A", "Dragon A", "Far"]
    _pick(eng, "Angel A")
    assert _offered(eng) == ["Demon A", "Dragon A"]  # the Angel slot is filled: no second Angel
    _pick(eng, "Dragon A")
    assert _offered(eng) == ["Demon A"]
    eng.rules.resolve_choice(None)  # "may": taking fewer than the slots is allowed
    eng.resolve_until_stable()
    assert sorted(o.name for o in p.hand) == ["Angel A", "Dragon A"]
    # the rest go to the bottom (random order), the unlooked Deep stays on top (RULE 401.4)
    assert p.library[-1].name == "Deep" and len(p.library) == 5
    assert sorted(o.name for o in p.library[:4]) == ["Angel B", "Bear", "Demon A", "Far"]


def test_a_slot_with_no_card_is_left_empty_and_fewer_cards_than_slots_is_fine():
    eng = game(library=0)
    p = _cast_stack(eng, ("Angel A", "Creature — Angel"), ("Bear", "Creature — Bear"))
    _kaalia(eng)
    assert _offered(eng) == ["Angel A"]  # no Demon, no Dragon in a two-card library
    _pick(eng, "Angel A")
    assert eng.state.pending_choice is None
    assert [o.name for o in p.hand] == ["Angel A"] and [o.name for o in p.library] == ["Bear"]


def test_no_card_fits_any_slot_puts_the_whole_window_on_the_bottom():
    eng = game(library=0)
    p = _cast_stack(eng, ("A", "Creature — Bear"), ("B", "Creature — Bear"))
    _kaalia(eng)
    assert eng.state.pending_choice is None and p.hand == [] and len(p.library) == 2


def test_a_card_that_fits_two_slots_fills_only_one():
    eng = game(library=0)
    p = _cast_stack(eng, ("Demon Dragon", "Creature — Demon Dragon"))
    _kaalia(eng)
    _pick(eng, "Demon Dragon")
    assert eng.state.pending_choice is None and [o.name for o in p.hand] == ["Demon Dragon"]


def test_only_the_picked_cards_are_revealed():
    from mtg_analyzer.models.game.events import EventType

    eng = game(library=0)
    _cast_stack(eng, ("Angel A", "Creature — Angel"), ("Bear", "Creature — Bear"))
    _kaalia(eng)
    _pick(eng, "Angel A")
    revealed = [e.get("object") for e in eng.state.event_log if e.type == EventType.REVEAL]
    assert revealed == ["Angel A"]  # RULE 701.20: the looked-at Bear stays private


def test_sludge_titan_mills_then_puts_a_creature_and_a_land_into_hand():
    eng = game(library=0)
    p = _cast_stack(eng, ("Under", "Sorcery"), ("Land B", "Land"), ("Bear B", "Creature — Bear"), ("Spell", "Sorcery"),
                    ("Land A", "Land"), ("Bear A", "Creature — Bear"))
    put_on_battlefield(eng, "Sludge Titan")
    eng.resolve_until_stable()
    assert _offered(eng) == ["Bear A", "Bear B", "Land A", "Land B"]
    _pick(eng, "Bear A")
    assert _offered(eng) == ["Land A", "Land B"]  # the creature slot is spent
    _pick(eng, "Land B")
    assert eng.state.pending_choice is None
    assert sorted(o.name for o in p.hand) == ["Bear A", "Land B"]
    assert sorted(o.name for o in p.graveyard) == ["Bear B", "Land A", "Spell"]
    assert [o.name for o in p.library] == ["Under"]


def test_a_bot_answers_a_slot_pick_through_legal_actions():
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject
    from mtg_analyzer.services.bots import create_bot
    from mtg_analyzer.services.game_session import GameSessionManager

    session = GameSessionManager().create_multiplayer(
        [{"player_id": p, "name": p, "library": []} for p in ("p1", "p2")], mulligan_style="none", keep_history=False,
    )
    eng = session.engine
    me = eng.state.active_player.id
    p = eng.state.player_by_id(me)
    for name, line in (("Angel A", "Creature — Angel"), ("Angel B", "Creature — Angel"), ("Demon A", "Creature — Demon")):
        g = GameObject(Card(id=name, name=name, type_line=line, is_creature=True, power=1, toughness=1),
                       owner_id=me, zone=Zone.LIBRARY)
        p.add_to_zone(g, Zone.LIBRARY)
    for seat in ("p1", "p2"):
        session.apply_action({"type": "keep_hand", "bottom_count": 0}, actor_id=seat)  # leave the setup phase
    from tests.test_par213_inspection import run

    run(eng, "look at the top 6 cards of your library. you may reveal an angel card, a demon card, and/or a dragon card "
             "from among them and put them into your hand. put the rest on the bottom of your library in a random order")
    choice = eng.state.pending_choice
    assert choice and choice["player_id"] == me
    other = next(x.id for x in eng.state.players if x.id != me)
    assert not [a for a in session.legal_actions(perspective=other) if a["type"] == "choose"]
    bot = create_bot("greedy", me)
    for _ in range(4):
        if eng.state.pending_choice is None:
            break
        actions = session.legal_actions(perspective=me)
        assert actions
        session.apply_action(bot.decide(session.view(perspective=me), actions), actor_id=me)
    assert eng.state.pending_choice is None
    hand = sorted(o.name for o in p.hand)
    assert len(hand) <= 2 and len(set(n.split()[0] for n in hand)) == len(hand)  # never two Angels


# ---- (B) reveal up to N / any number, put on top, the rest on the bottom -----------------------------------------

def _decide(eng, label_order):
    """Look (the gate), acknowledge, then pick the labelled cards in order; whatever else is asked takes its first option."""
    for _ in range(40):
        choice = eng.state.pending_choice
        if choice is None:
            return
        options = choice.get("options") or []
        wanted = next((str(o["id"]) for want in label_order for o in options if o.get("label") == want), None)
        if choice.get("mode") == "look_gate":
            wanted = "look"
        elif choice.get("mode") == "ack":
            wanted = "done"
        eng.resolve_pending_choice(wanted if wanted is not None else str(options[0]["id"]) if options else "decline")


def test_fertile_thicket_reveals_up_to_one_basic_and_puts_it_on_top():
    eng = game(library=0)
    p = _cast_stack(eng, ("Deep", "Creature — Bear"), ("Far Plain", "Basic Land — Plains"), ("Spell", "Sorcery"),
                    ("Dud", "Creature — Bear"), ("Island", "Basic Land — Island"), ("Dull", "Creature — Bear"),
                    ("Dust", "Creature — Bear"), ("Dross", "Creature — Bear"))
    put_on_battlefield(eng, "Fertile Thicket")
    eng.resolve_until_stable()
    _decide(eng, ["Island"])
    names = [o.name for o in reversed(p.library)]
    # Island on top (RULE 401.4), the unlooked cards below it, the other four looked-at cards on the bottom
    assert names[:4] == ["Island", "Spell", "Far Plain", "Deep"]
    assert sorted(names[4:]) == ["Dross", "Dud", "Dull", "Dust"]


def test_munda_puts_the_revealed_allies_on_top_in_the_order_chosen_and_the_rest_below():
    eng = game(library=0)
    p = _cast_stack(eng, ("Deep", "Creature — Bear"), ("Ally A", "Creature — Kor Ally"),
                    ("Bear", "Creature — Bear"), ("Ally B", "Creature — Kor Ally"), ("Ally C", "Creature — Kor Ally"))
    put_on_battlefield(eng, "Munda, Ambush Leader")
    eng.resolve_until_stable()
    _decide(eng, ["Ally B", "Ally C", "Ally A"])
    names = [o.name for o in reversed(p.library)]
    assert set(names[:3]) == {"Ally A", "Ally B", "Ally C"} and names.count("Bear") == 1 and "Deep" in names


# ---- (C) "put any number of <class> cards from among them onto the battlefield, then shuffle" ---------------------

SHUFFLE_CARDS = ("Ajani, Outland Chaperone", "Famished Worldsire", "Through the Forest Gate")


@pytest.mark.parametrize("name", SHUFFLE_CARDS)
def test_the_then_shuffle_pick_cards_are_modeled(name):
    assert _modeled(name)


@pytest.mark.parametrize("name", [
    # each of these prints a bound or operand that serves no second card (singletons.md "Library residue")
    "Kayla's Reconstruction", "Michelangelo's Technique", "Smelting Vat", "Rip, Spawn Hunter", "Glacial Revelation",
    "Kamahl's Druidic Vow", "Knickknack Ouphe",
])
def test_cards_with_a_bound_of_their_own_stay_unmodeled(name):
    assert not _modeled(name)


def test_the_shuffle_tail_leaves_the_rest_in_the_library_and_shuffles_it():
    params = _slots_params(
        "look at the top 20 cards of your library, put any number of land cards from among them onto the battlefield "
        "tapped, then shuffle")
    assert params["rest_destination"] == "library_shuffled" and params["max_picks"] == "all"
    assert params["action"] == "library_to_battlefield_tapped" and params["criteria"] == {"type": "land"}


def test_through_the_forest_gate_puts_every_chosen_land_tapped_then_shuffles(monkeypatch):
    from mtg_analyzer.models.game.player import Player

    shuffled = []
    real = Player.shuffle_library
    monkeypatch.setattr(Player, "shuffle_library", lambda self: (shuffled.append(self.id), real(self))[1])
    eng = game(library=0)
    p = _cast_stack(eng, ("Deep", "Creature — Bear"), ("Land C", "Basic Land — Forest"), ("Spell", "Sorcery"),
                    ("Land B", "Basic Land — Island"), ("Land A", "Basic Land — Plains"))
    from tests.test_par213_inspection import run

    run(eng, "look at the top 4 cards of your library, put any number of land cards from among them onto the battlefield "
             "tapped, then shuffle")
    assert _offered(eng) == ["Land A", "Land B", "Land C"]
    _pick(eng, "Land A")
    _pick(eng, "Land C")
    eng.rules.resolve_choice(None)  # "any number": stop after two
    eng.resolve_until_stable()
    lands = {o.name: o for o in eng.state.battlefield if o.name.startswith("Land")}
    assert set(lands) == {"Land A", "Land C"} and all(o.tapped for o in lands.values())
    assert shuffled == ["p1"]  # one shuffle, after the picks (RULE 701.24a)
    assert sorted(o.name for o in p.library) == ["Deep", "Land B", "Spell"]
