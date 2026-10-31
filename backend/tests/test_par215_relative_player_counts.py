"""PAR-215 axis D: counts taken as another player ("the number of X that player controls / in their hand").

RULE 109.5: "they" / "that player" / "their" is the player the clause names, not the ability's controller, so the
count has to be evaluated for that player (`effect_amounts` ``of``).
"""
import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from tests.support.deck_batch import answer, card, cast, filler, game


def _parse(text, type_line="Sorcery"):
    c = Card(id="x", name="Probe Card", type_line=type_line, oracle_text=text, is_sorcery="Sorcery" in type_line,
             is_instant="Instant" in type_line)
    return parse_oracle(c)


def _flat(result):
    return [e for s in result.specs for e in s.to_dict()["effects"]]


def _amount(result):
    node = _flat(result)[0]
    if node["type"] == "for_each":
        node = node["params"]["effects"][0]
    return node["params"]["amount"]


@pytest.mark.parametrize("text,holder", [
    ("Probe Card deals damage to target player equal to the number of cards in that player's hand.", "target"),
    ("Target opponent loses life equal to the number of creatures they control.", "target"),
    ("Probe Card deals damage to each opponent equal to the number of islands that player controls.", "target"),
])
def test_relative_count_is_taken_as_the_named_player(text, holder):
    result = _parse(text)
    assert result.modeled, result.unclaimed
    amount = _amount(result)
    assert amount["kind"] == "count_selector" and amount["of"] == holder
    assert amount["selector"]["of"] == "you"  # evaluated with that player as the controller


def test_a_second_target_inside_the_phrase_is_not_guessed():
    # the count names a different player than the body's target: refuse rather than mis-measure
    assert not _parse("Target player draws cards equal to the number of cards in target opponent's hand.").modeled


def test_trigger_player_count_reads_the_upkeep_player():
    result = _parse("At the beginning of each player's upkeep, Probe Card deals damage to that player equal to the "
                    "number of swamps they control.", "Enchantment")
    assert result.modeled, result.unclaimed
    bind = _flat(result)[0]
    assert bind["params"]["amount"]["of"] == "active_player"
    assert bind["params"]["effects"][0]["params"]["selector"] == "active_player"


def test_twice_and_minus_modifiers_survive():
    twice = _amount(_parse("Probe Card deals damage to target player equal to twice the number of white creatures "
                           "they control."))
    assert twice["multiply"] == 2
    minus = _amount(_parse("At the beginning of each opponent's upkeep, Probe Card deals x damage to that player, "
                           "where x is the number of cards in their hand minus 4.", "Enchantment"))
    assert minus["minus"] == 4 and minus["minimum"] == 0


def test_gaze_of_adamaro_counts_the_targets_hand_not_the_casters():
    eng = game(library=3)
    for i in range(4):
        filler(eng, f"Spell{i}", player="p2", type_line="Instant", zone=Zone.HAND)
    for i in range(7):
        filler(eng, f"Mine{i}", player="p1", type_line="Instant", zone=Zone.HAND)
    victim = eng.state.player_by_id("p2")
    cast(eng, card(eng, "Gaze of Adamaro", zone=Zone.HAND), targets=[victim])
    assert victim.life == 16


def test_anathemancer_counts_the_targets_nonbasic_lands():
    eng = game(library=3)
    for i in range(2):
        filler(eng, f"Nonbasic{i}", player="p2", type_line="Land")
    filler(eng, "MyNonbasic", player="p1", type_line="Land")
    cast(eng, card(eng, "Anathemancer", zone=Zone.HAND))
    answer(eng, pick=lambda choice: next(o["id"] for o in choice["options"] if o["id"] == "p2"))
    assert eng.state.player_by_id("p2").life == 18


def test_typhoon_hits_each_opponent_for_its_own_island_count():
    eng = game(players=3, library=3)
    for i in range(2):
        filler(eng, f"Island{i}", player="p2", type_line="Basic Land — Island")
    for i in range(3):
        filler(eng, f"Island{i + 2}", player="p3", type_line="Basic Land — Island")
    cast(eng, card(eng, "Typhoon", zone=Zone.HAND))
    assert [p.life for p in eng.state.players] == [20, 18, 17]


def test_karma_burns_each_upkeep_player_for_their_own_swamps():
    eng = game(players=2, library=10)
    karma = card(eng, "Karma", player="p1")
    for i in range(3):
        filler(eng, f"MySwamp{i}", player="p1", type_line="Basic Land — Swamp")
    for i in range(1):
        filler(eng, f"TheirSwamp{i}", player="p2", type_line="Basic Land — Swamp")
    lives = {p.id: p.life for p in eng.state.players}
    seen = set()
    for _ in range(40):  # walk both players' upkeeps
        eng.advance_step()
        answer(eng)
        eng.resolve_until_stable()
        if eng.state.current_step == "upkeep":
            seen.add(eng.state.active_player.id)
        if seen == {"p1", "p2"} and eng.state.current_step == "draw":
            break
    assert karma and seen == {"p1", "p2"}
    # each player took damage equal to the swamps *they* control at their own upkeep
    assert eng.state.player_by_id("p1").life == lives["p1"] - 3
    assert eng.state.player_by_id("p2").life == lives["p2"] - 1


def test_each_player_creates_tokens_for_their_own_forests():
    eng = game(players=2, library=5)
    for i in range(3):
        filler(eng, f"F{i}", player="p1", type_line="Basic Land — Forest")
    filler(eng, "G0", player="p2", type_line="Basic Land — Forest")
    cast(eng, card(eng, "Waiting in the Weeds", zone=Zone.HAND))
    cats = {pid: sum(1 for o in eng.state.battlefield if o.controller_id == pid and "Cat" in o.name)
            for pid in ("p1", "p2")}
    assert cats == {"p1": 3, "p2": 1}


def test_each_player_draws_for_their_own_graveyard():
    eng = game(players=2, library=5)
    for i in range(2):
        filler(eng, f"C{i}", player="p1", type_line="Creature", zone=Zone.GRAVEYARD)
    for i in range(3):
        filler(eng, f"D{i}", player="p2", type_line="Creature", zone=Zone.GRAVEYARD)
    before = [len(p.hand) for p in eng.state.players]
    cast(eng, card(eng, "Nature's Resurgence", zone=Zone.HAND))
    assert [len(p.hand) - b for p, b in zip(eng.state.players, before)] == [2, 3]


def test_searing_rays_counts_each_players_creatures_of_the_chosen_colour():
    eng = game(players=2, library=3)
    for name, owner, pip in (("G1", "p1", "G"), ("G2", "p1", "G"), ("R1", "p1", "R"),
                             ("G3", "p2", "G"), ("R2", "p2", "R"), ("R3", "p2", "R")):
        filler(eng, name, player=owner, type_line="Creature", power=1, toughness=3, mv=1,
               mana_cost_string="{%s}" % pip)
    cast(eng, card(eng, "Searing Rays", zone=Zone.HAND))
    answer(eng, pick=lambda choice: next(o["id"] for o in choice["options"] if o["id"] == "G"))
    assert [p.life for p in eng.state.players] == [18, 19]
