"""ENG-65 -- RULE 118.9 / 601.2b-h: the caster picks which permanents an alternative cost returns or sacrifices.

Real cards from the cache (Gush, Thwart, Daze, Tidal Bore, the Borderposts, Delraich, Demon of Death's Gate, Flare of
Denial, Fireblast, Downhill Charge), each against a board with several eligible permanents and near misses: a wrong
type or colour, a token, an opponent's permanent, an unpayable cost, and a cast that is cloned or abandoned mid-pick.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import DEFAULT_DB_PATH
from tests.support.catalogue import two_player_game

pytestmark = pytest.mark.skipif(not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment")

CHOICE_KIND = "cast_alt_cost_object"


def card(engine, name, zone=Zone.BATTLEFIELD, owner="p1", token=False):
    with sqlite3.connect(f"file:{DEFAULT_DB_PATH.as_posix()}?mode=ro", uri=True) as db:
        row = db.execute("SELECT data FROM cards WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row is None:
        pytest.skip(f"{name!r} not in the local card cache")
    obj = GameObject(Card.from_dict(json.loads(row[0])), owner_id=owner, zone=zone)
    obj.controller_id = owner
    obj.is_token = token
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def main_phase(engine):
    engine.state.current_phase = engine.state.current_step = "main1"


def option_ids(engine):
    return [int(o["id"]) for o in engine.state.pending_choice["options"]]


def stack_spell(engine, owner="p2"):
    """A bolt on the stack, a legal target for the counterspells."""
    from mtg_analyzer.models.game.game_state import StackItem
    obj = card(engine, "Lightning Bolt", zone=Zone.HAND, owner=owner)
    engine.state.player_by_id(owner).hand.remove(obj)
    obj.zone = Zone.STACK
    item = StackItem(kind="spell", controller_id=owner, obj=obj, description=obj.name, effects=[])
    engine.state.stack.append(item)
    return obj


def cast_alt(engine, player, spell, **kwargs):
    return engine.cast_spell(player, spell, alt_cost=True, **kwargs)


# ---------------------------------------------------------------------------
# Counted return (Gush, Thwart): a real choice among several Islands.
# ---------------------------------------------------------------------------

def gush_board():
    engine, p1 = two_player_game()
    main_phase(engine)
    islands = [card(engine, "Island") for _ in range(3)]
    forest = card(engine, "Forest")
    enemy_island = card(engine, "Island", owner="p2")
    gush = card(engine, "Gush", Zone.HAND)
    for i in range(3):
        card(engine, "Island", Zone.LIBRARY)
    return engine, p1, islands, forest, enemy_island, gush


def test_gush_asks_which_islands_and_offers_only_own_islands():
    engine, p1, islands, forest, enemy_island, gush = gush_board()
    assert engine.can_cast(p1, gush, alt_cost=True)
    cast_alt(engine, p1, gush)
    pending = engine.state.pending_choice
    assert pending["kind"] == CHOICE_KIND and pending["player_id"] == "p1"
    assert sorted(option_ids(engine)) == sorted(i.instance_id for i in islands)  # not the Forest, not the enemy Island
    assert gush.zone == Zone.HAND and all(i.zone == Zone.BATTLEFIELD for i in islands)  # nothing paid yet
    # RULE 601.2b-h: the caster names the Islands -- the first AND last one here, not the engine's first two.
    engine.resolve_pending_choice(str(islands[2].instance_id))
    assert engine.state.pending_choice["kind"] == CHOICE_KIND
    assert sorted(option_ids(engine)) == sorted([islands[0].instance_id, islands[1].instance_id])
    engine.resolve_pending_choice(str(islands[0].instance_id))
    engine.resolve_until_stable()
    assert islands[2].zone == Zone.HAND and islands[0].zone == Zone.HAND
    assert islands[1].zone == Zone.BATTLEFIELD and forest.zone == Zone.BATTLEFIELD
    assert enemy_island.zone == Zone.BATTLEFIELD
    assert gush.zone == Zone.GRAVEYARD and len(p1.hand) == 2 + 2  # two returned Islands, two drawn cards


def test_gush_with_exactly_two_islands_has_no_real_choice():
    engine, p1 = two_player_game()
    main_phase(engine)
    islands = [card(engine, "Island") for _ in range(2)]
    gush = card(engine, "Gush", Zone.HAND)
    for _ in range(2):
        card(engine, "Island", Zone.LIBRARY)
    cast_alt(engine, p1, gush)  # forced payment is taken without asking (the `_pick_payment_object` convention)
    assert engine.state.pending_choice is None
    assert all(i.zone == Zone.HAND for i in islands)


def test_gush_unpayable_with_one_island_or_wrong_land_type():
    engine, p1 = two_player_game()
    main_phase(engine)
    isl = card(engine, "Island")
    card(engine, "Forest")
    card(engine, "Forest")
    gush = card(engine, "Gush", Zone.HAND)
    assert not engine.can_cast(p1, gush, alt_cost=True)
    with pytest.raises(ValueError):
        cast_alt(engine, p1, gush)
    assert engine.state.pending_choice is None and isl.zone == Zone.BATTLEFIELD and gush.zone == Zone.HAND


def test_thwart_three_islands_pick_three_of_four():
    engine, p1 = two_player_game()
    main_phase(engine)
    islands = [card(engine, "Island") for _ in range(4)]
    thwart = card(engine, "Thwart", Zone.HAND)
    target = stack_spell(engine)
    cast_alt(engine, p1, thwart, targets=[target])
    asked = []
    keep = islands[1]
    while engine.state.pending_choice:
        ids = option_ids(engine)
        asked.append(len(ids))
        engine.resolve_pending_choice(str(next(i for i in ids if i != keep.instance_id)))
    assert asked == [4, 3, 2]
    engine.resolve_until_stable()
    assert keep.zone == Zone.BATTLEFIELD and sum(i.zone == Zone.HAND for i in islands) == 3
    assert target.zone == Zone.GRAVEYARD  # Thwart countered the bolt


def test_thwart_with_two_islands_is_unpayable():
    engine, p1 = two_player_game()
    main_phase(engine)
    [card(engine, "Island") for _ in range(2)]
    thwart = card(engine, "Thwart", Zone.HAND)
    target = stack_spell(engine)
    assert not engine.can_cast(p1, thwart, alt_cost=True, targets=[target])


# ---------------------------------------------------------------------------
# Singular return (Daze, Tidal Bore) and "basic land" (Borderposts).
# ---------------------------------------------------------------------------

def test_daze_asks_which_island_to_return():
    engine, p1 = two_player_game()
    main_phase(engine)
    a, b = card(engine, "Island"), card(engine, "Island")
    card(engine, "Mountain")
    daze = card(engine, "Daze", Zone.HAND)
    target = stack_spell(engine)
    cast_alt(engine, p1, daze, targets=[target])
    assert engine.state.pending_choice["kind"] == CHOICE_KIND
    assert sorted(option_ids(engine)) == sorted([a.instance_id, b.instance_id])
    engine.resolve_pending_choice(str(b.instance_id))
    assert b.zone == Zone.HAND and a.zone == Zone.BATTLEFIELD
    assert engine.state.pending_choice["kind"] == "counter_unless_pays"  # Daze was cast and resolved


def test_tidal_bore_returns_the_chosen_island_only():
    engine, p1 = two_player_game()
    main_phase(engine)
    a, b = card(engine, "Island"), card(engine, "Island")
    bore = card(engine, "Tidal Bore", Zone.HAND)
    bear = card(engine, "Grizzly Bears", owner="p2")
    cast_alt(engine, p1, bore, targets=[bear])
    assert sorted(option_ids(engine)) == sorted([a.instance_id, b.instance_id])
    engine.resolve_pending_choice(str(a.instance_id))
    assert a.zone == Zone.HAND and b.zone == Zone.BATTLEFIELD
    assert bore.zone != Zone.HAND  # cast


def test_borderpost_offers_only_basic_lands():
    engine, p1 = two_player_game()
    main_phase(engine)
    basics = [card(engine, "Island"), card(engine, "Mountain")]
    nonbasic = card(engine, "Command Tower")
    card(engine, "Island", owner="p2")
    post = card(engine, "Firewild Borderpost", Zone.HAND)
    p1.mana_pool.add("C", 1)
    assert engine.can_cast(p1, post, alt_cost=True)
    cast_alt(engine, p1, post)
    assert sorted(option_ids(engine)) == sorted(b.instance_id for b in basics)
    assert nonbasic.instance_id not in option_ids(engine)
    engine.resolve_pending_choice(str(basics[1].instance_id))
    assert basics[1].zone == Zone.HAND and basics[0].zone == Zone.BATTLEFIELD
    assert p1.mana_pool.total() == 0  # the {1} was paid too


def test_borderpost_with_only_a_nonbasic_land_is_unpayable():
    engine, p1 = two_player_game()
    main_phase(engine)
    card(engine, "Command Tower")
    post = card(engine, "Firewild Borderpost", Zone.HAND)
    p1.mana_pool.add("C", 1)
    assert not engine.can_cast(p1, post, alt_cost=True)


# ---------------------------------------------------------------------------
# Sacrifice costs: singular, counted with a colour word, filtered, life + counted.
# ---------------------------------------------------------------------------

def test_downhill_charge_asks_which_mountain_to_sacrifice():
    engine, p1 = two_player_game()
    main_phase(engine)
    a, b = card(engine, "Mountain"), card(engine, "Mountain")
    card(engine, "Forest")
    charge = card(engine, "Downhill Charge", Zone.HAND)
    target = card(engine, "Grizzly Bears", owner="p2")
    cast_alt(engine, p1, charge, targets=[target, p1])
    pending = engine.state.pending_choice
    assert pending["kind"] == CHOICE_KIND
    assert sorted(option_ids(engine)) == sorted([a.instance_id, b.instance_id])
    engine.resolve_pending_choice(str(b.instance_id))
    assert b.zone == Zone.GRAVEYARD and a.zone == Zone.BATTLEFIELD


def test_fireblast_picks_two_of_three_mountains():
    engine, p1 = two_player_game()
    main_phase(engine)
    mountains = [card(engine, "Mountain") for _ in range(3)]
    card(engine, "Swamp")
    blast = card(engine, "Fireblast", Zone.HAND)
    target = card(engine, "Grizzly Bears", owner="p2")
    cast_alt(engine, p1, blast, targets=[engine.state.player_by_id("p2")])
    engine.resolve_pending_choice(str(mountains[2].instance_id))
    engine.resolve_pending_choice(str(mountains[1].instance_id))
    assert engine.state.pending_choice is None  # two picks owed, two made
    assert mountains[2].zone == Zone.GRAVEYARD and mountains[1].zone == Zone.GRAVEYARD
    assert mountains[0].zone == Zone.BATTLEFIELD
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p2").life == 16 and blast.zone == Zone.GRAVEYARD  # 4 damage, for no mana


def delraich_board(extra_black=1):
    engine, p1 = two_player_game()
    main_phase(engine)
    black = [card(engine, "Typhoid Rats") for _ in range(3 + extra_black)]
    green = card(engine, "Grizzly Bears")
    enemy_black = card(engine, "Typhoid Rats", owner="p2")
    delraich = card(engine, "Delraich", Zone.HAND)
    engine.recompute_continuous_effects()
    return engine, p1, black, green, enemy_black, delraich


def test_delraich_sacrifices_three_chosen_black_creatures():
    engine, p1, black, green, enemy_black, delraich = delraich_board()
    assert engine.can_cast(p1, delraich, alt_cost=True)
    cast_alt(engine, p1, delraich)
    assert sorted(option_ids(engine)) == sorted(b.instance_id for b in black)  # no Bears, no enemy Rats
    keep = black[0]
    while engine.state.pending_choice:
        ids = [i for i in option_ids(engine) if i != keep.instance_id]
        engine.resolve_pending_choice(str(ids[0]))
    engine.resolve_until_stable()
    assert keep.zone == Zone.BATTLEFIELD and green.zone == Zone.BATTLEFIELD and enemy_black.zone == Zone.BATTLEFIELD
    assert sum(b.zone == Zone.GRAVEYARD for b in black) == 3
    assert delraich.zone == Zone.BATTLEFIELD
    from mtg_analyzer.game.combat import has
    engine.recompute_continuous_effects()
    assert has(delraich, "trample")  # the rest of Delraich's oracle text is live too


def test_delraich_unpayable_with_only_two_black_creatures():
    engine, p1, black, green, enemy_black, delraich = delraich_board(extra_black=-1)
    assert not engine.can_cast(p1, delraich, alt_cost=True)
    with pytest.raises(ValueError):
        cast_alt(engine, p1, delraich)
    assert all(b.zone == Zone.BATTLEFIELD for b in black) and delraich.zone == Zone.HAND


def test_demon_of_deaths_gate_pays_life_and_chosen_creatures():
    engine, p1, black, green, enemy_black, _ = delraich_board()
    demon = card(engine, "Demon of Death's Gate", Zone.HAND)
    p1.life = 7
    cast_alt(engine, p1, demon)
    keep = black[3]
    while engine.state.pending_choice:
        engine.resolve_pending_choice(str(next(i for i in option_ids(engine) if i != keep.instance_id)))
    engine.resolve_until_stable()
    assert p1.life == 1 and keep.zone == Zone.BATTLEFIELD and demon.zone == Zone.BATTLEFIELD
    from mtg_analyzer.game.combat import has
    engine.recompute_continuous_effects()
    assert has(demon, "flying") and has(demon, "trample")

def test_demon_of_deaths_gate_unpayable_without_the_life():
    engine, p1, black, green, enemy_black, _ = delraich_board()
    demon = card(engine, "Demon of Death's Gate", Zone.HAND)
    p1.life = 5  # RULE 119.4: a player can't pay more life than they have
    assert not engine.can_cast(p1, demon, alt_cost=True)


def test_flare_of_denial_filter_excludes_tokens_and_off_colour():
    engine, p1 = two_player_game()
    main_phase(engine)
    blue_a = card(engine, "Looter il-Kor")
    blue_b = card(engine, "Looter il-Kor")
    blue_token = card(engine, "Looter il-Kor", token=True)
    red = card(engine, "Goblin Guide")
    flare = card(engine, "Flare of Denial", Zone.HAND)
    target = stack_spell(engine)
    cast_alt(engine, p1, flare, targets=[target])
    assert sorted(option_ids(engine)) == sorted([blue_a.instance_id, blue_b.instance_id])
    assert blue_token.instance_id not in option_ids(engine) and red.instance_id not in option_ids(engine)
    engine.resolve_pending_choice(str(blue_b.instance_id))
    assert blue_b.zone == Zone.GRAVEYARD and blue_a.zone == Zone.BATTLEFIELD


# ---------------------------------------------------------------------------
# Resumability: clone, wrong answers, undo, bots.
# ---------------------------------------------------------------------------

def test_pending_pick_survives_clone_and_is_independent():
    engine, p1, islands, *_rest, gush = gush_board()
    cast_alt(engine, p1, gush)
    engine.resolve_pending_choice(str(islands[0].instance_id))
    restored = GameEngine(engine.state.clone())
    assert restored.state.pending_choice["kind"] == CHOICE_KIND
    assert restored.state.pending_choice["picks"] == [islands[0].instance_id]
    restored.resolve_pending_choice(str(islands[2].instance_id))
    restored.resolve_until_stable()
    assert restored.state.find_object(islands[0].instance_id).zone == Zone.HAND
    assert restored.state.find_object(islands[2].instance_id).zone == Zone.HAND
    assert restored.state.find_object(islands[1].instance_id).zone == Zone.BATTLEFIELD
    # the live game is untouched and still waiting on its own second pick
    assert engine.state.pending_choice["kind"] == CHOICE_KIND and islands[2].zone == Zone.BATTLEFIELD


def test_answer_outside_the_pool_reasks_without_paying():
    engine, p1, islands, forest, enemy_island, gush = gush_board()
    cast_alt(engine, p1, gush)
    engine.resolve_pending_choice(str(forest.instance_id))
    assert engine.state.pending_choice["kind"] == CHOICE_KIND
    engine.resolve_pending_choice(str(enemy_island.instance_id))
    assert engine.state.pending_choice["kind"] == CHOICE_KIND
    assert gush.zone == Zone.HAND and all(i.zone == Zone.BATTLEFIELD for i in islands) and forest.zone == Zone.BATTLEFIELD


def test_cast_cannot_start_while_another_choice_is_open():
    engine, p1, islands, forest, enemy_island, gush = gush_board()
    cast_alt(engine, p1, gush)
    with pytest.raises(ValueError):
        cast_alt(engine, p1, gush)


def test_explicit_picks_skip_the_questions_and_are_validated():
    engine, p1, islands, forest, enemy_island, gush = gush_board()
    with pytest.raises(ValueError):
        cast_alt(engine, p1, gush, alt_cost_choices=[islands[0].instance_id, forest.instance_id])
    with pytest.raises(ValueError):
        cast_alt(engine, p1, gush, alt_cost_choices=[islands[0].instance_id, islands[0].instance_id])
    assert gush.zone == Zone.HAND and all(i.zone == Zone.BATTLEFIELD for i in islands)
    cast_alt(engine, p1, gush, alt_cost_choices=[islands[1].instance_id, islands[2].instance_id])
    assert engine.state.pending_choice is None
    assert islands[1].zone == islands[2].zone == Zone.HAND and islands[0].zone == Zone.BATTLEFIELD


def test_session_undo_rewinds_a_half_paid_cast():
    from mtg_analyzer.services.game_session import GameSession
    engine, p1, islands, forest, enemy_island, gush = gush_board()
    session = GameSession.__new__(GameSession)  # only the undo stack is exercised
    session.engine = engine
    snapshot = engine.state.clone()
    cast_alt(engine, p1, gush)
    engine.resolve_pending_choice(str(islands[0].instance_id))
    assert engine.state.pending_choice is not None
    rewound = GameEngine(snapshot)
    assert rewound.state.pending_choice is None
    assert rewound.state.find_object(gush.instance_id).zone == Zone.HAND
    assert all(rewound.state.find_object(i.instance_id).zone == Zone.BATTLEFIELD for i in islands)


def test_bot_answers_through_the_same_choice_and_gives_up_its_cheapest_permanent():
    from mtg_analyzer.services.bot_policies.base import Bot
    engine, p1 = two_player_game()
    main_phase(engine)
    big = card(engine, "Dragon Hatchling")
    black_big = card(engine, "Ravenous Chupacabra")  # offered first: an engine/bot taking "the first" would give it up
    rats = [card(engine, "Typhoid Rats") for _ in range(3)]
    delraich = card(engine, "Delraich", Zone.HAND)
    engine.recompute_continuous_effects()
    cast_alt(engine, p1, delraich)
    pending = engine.state.pending_choice
    assert pending["kind"] == CHOICE_KIND
    bot = Bot.__new__(Bot)
    view = {"pending_choice": pending, "state": {"battlefield": [
        {"instance_id": o.instance_id, "power": o.power, "toughness": o.toughness, "mana_value": o.mana_value}
        for o in engine.state.permanents()], "players": []}}
    answers = [{"type": "choose", "option_id": o["id"], "instance_id": o["instance_id"], "name": o["label"]}
               for o in pending["options"]]
    picked = Bot.answer_choice(bot, view, answers)
    assert int(picked["option_id"]) != black_big.instance_id  # the most expensive body is kept
    assert int(picked["option_id"]) in [r.instance_id for r in rats]
    assert big.instance_id not in option_ids(engine)  # a red Dragon Hatchling is not a black creature


# ---------------------------------------------------------------------------
# Parser rows: counts past two, singular Island, colour word, life + counted sacrifice.
# ---------------------------------------------------------------------------

def parsed_alt_cost(name):
    from mtg_analyzer.parser.oracle.gate import parse_oracle
    from mtg_analyzer.services.card_database import CardDatabase
    result = parse_oracle(CardDatabase(DEFAULT_DB_PATH).get_card(name))
    return result.modeled, [s.alt_cost for s in result.specs if s.alt_cost]


@pytest.mark.parametrize("name,alt_cost", [
    ("Thwart", {"return_to_hand_count": [3, "island"]}),
    ("Gush", {"return_to_hand_count": [2, "island"]}),
    ("Tidal Bore", {"return_to_hand": "island"}),
    ("Daze", {"return_to_hand": "island"}),
    ("Delraich", {"sacrifice_count": [3, "black_creature"]}),
    ("Demon of Death's Gate", {"sacrifice_count": [3, "black_creature"], "pay_life": 6}),
    ("Salvage Titan", {"sacrifice_count": [3, "artifact"]}),
])
def test_parser_claims_the_widened_alt_cost_rows(name, alt_cost):
    modeled, alts = parsed_alt_cost(name)
    assert modeled and alts == [alt_cost]


def test_parser_still_leaves_non_matching_alt_costs_unclaimed():
    # "Eldrazi Spawn" is a two-word subtype: not a one-word type phrase, so Hand of Emrakul stays unclaimed.
    modeled, alts = parsed_alt_cost("Hand of Emrakul")
    assert not modeled and alts == []


def test_tidal_bore_effect_executes_after_the_island_choice():
    engine, p1 = two_player_game()
    main_phase(engine)
    a, b = card(engine, "Island"), card(engine, "Island")
    bore = card(engine, "Tidal Bore", Zone.HAND)
    bear = card(engine, "Grizzly Bears", owner="p2")
    bear.tapped = True
    cast_alt(engine, p1, bore, targets=[bear])
    engine.resolve_pending_choice(str(b.instance_id))
    assert {o["id"] for o in engine.state.pending_choice["options"]} == {"tap", "untap", "decline"}
    engine.resolve_pending_choice("untap")  # "You may tap or untap target creature"
    engine.resolve_until_stable()
    assert b.zone == Zone.HAND and a.zone == Zone.BATTLEFIELD and bore.zone == Zone.GRAVEYARD
    assert not bear.tapped


def test_flare_of_duplication_now_carries_its_alternative_cost():
    engine, p1 = two_player_game()
    main_phase(engine)
    reds = [card(engine, "Goblin Guide"), card(engine, "Goblin Guide")]
    blue = card(engine, "Looter il-Kor")
    flare = card(engine, "Flare of Duplication", Zone.HAND)
    target = stack_spell(engine)
    cast_alt(engine, p1, flare, targets=[target])
    assert sorted(option_ids(engine)) == sorted(r.instance_id for r in reds)
    assert blue.instance_id not in option_ids(engine)


# ---------------------------------------------------------------------------
# The wire: legal actions offer the cast, the view carries the choice, answers and rewinds go through the session.
# ---------------------------------------------------------------------------

def test_session_offers_the_choice_over_the_wire_and_rewinds_it():
    from mtg_analyzer.services.game_session import GameSession
    engine, p1, islands, forest, enemy_island, gush = gush_board()
    session = GameSession(engine, require_setup=False)
    cast = next(a for a in session.legal_actions("p1")
                if a["type"] == "cast_spell" and a.get("alt_cost") and a.get("instance_id") == gush.instance_id)
    session.apply_action(cast, "p1")
    view = session.view("p1")
    assert view["pending_choice"]["kind"] == CHOICE_KIND
    wire_options = view["pending_choice"]["options"]
    assert {o["instance_id"] for o in wire_options} == {i.instance_id for i in islands}  # the generic popup's shape
    answers = [a for a in session.legal_actions("p1") if a["type"] == "choose"]
    assert {a["instance_id"] for a in answers} == {i.instance_id for i in islands}
    assert session.view("p2")["pending_choice"] is None  # the opponent only sees a "waiting" marker
    session.apply_action(answers[0], "p1")
    session.rewind(1)  # back before the second pick: the first pick is undone with it
    assert session.engine.state.pending_choice["kind"] == CHOICE_KIND
    assert session.engine.state.pending_choice["picks"] == []
    assert all(session.engine.state.find_object(i.instance_id).zone == Zone.BATTLEFIELD for i in islands)
    for _ in range(2):
        pending = session.engine.state.pending_choice
        session.apply_action({"type": "choose", "option_id": pending["options"][-1]["id"]}, "p1")
    assert session.engine.state.pending_choice is None
    live = [session.engine.state.find_object(i.instance_id) for i in islands]  # rewind restored a clone
    assert sum(i.zone == Zone.HAND for i in live) == 2  # two named Islands returned (two more were drawn)


def test_flashback_cost_that_sacrifices_asks_too():
    """RULE 702.34a: a flashback cost that sacrifices a creature is paid with the caster's pick as well."""
    engine, p1 = two_player_game()
    main_phase(engine)
    bears = [card(engine, "Grizzly Bears"), card(engine, "Grizzly Bears")]
    enemy = card(engine, "Grizzly Bears", owner="p2")
    bolt = card(engine, "Lightning Bolt", Zone.GRAVEYARD)
    bolt.parametric_keywords = {"flashback": {"cost": "Sacrifice a creature"}}  # no pool card prints this today
    engine.cast_spell(p1, bolt, targets=[engine.state.player_by_id("p2")])
    assert engine.state.pending_choice["kind"] == CHOICE_KIND
    assert sorted(option_ids(engine)) == sorted(b.instance_id for b in bears)  # not the opponent's creature
    engine.resolve_pending_choice(str(bears[1].instance_id))
    engine.resolve_until_stable()
    assert bears[1].zone == Zone.GRAVEYARD and bears[0].zone == Zone.BATTLEFIELD and enemy.zone == Zone.BATTLEFIELD
    assert engine.state.player_by_id("p2").life == 17 and bolt.zone == Zone.EXILE
