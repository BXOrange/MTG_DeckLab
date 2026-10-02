"""PAR-107…114 residue batches, part 4 — "look at target player's hand and choose `<N>` cards from it" and the
reveal-and-pick forms that put the card into the library instead of the graveyard.

`reveal_hand_choose_discard` grew a pick ``count`` (an int, ``"x"``, or ``up_to``) and a ``destination``
(``discard`` / ``library_top`` / ``library_third``): Mind Warp / Abandon Hope (X), Extortion (up to 2), Agonizing
Memories (2, on top), Painful Memories (1, on top), Lost Hours (a nonland card, third from the top).

Reference: parser/oracle/catalogue/handlers.py (`_HAND_PICK_RE`), game/effects/damage_draw.py
(`RevealHandChooseDiscardEffect`), game/rules/misc_mixin.py (the `hand_to_library_*` choose-object actions).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effects.core import GameContext, RevealHandChooseDiscardEffect
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _setup():
    p1, p2 = Player(id="p1", life=20), Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    return RulesEngine(state), state, p1, p2


def _hand_card(player, name, type_line="Instant"):
    obj = GameObject(
        Card(id=name, name=name, type_line=type_line, is_instant="Instant" in type_line, is_land="Land" in type_line,
             is_creature="Creature" in type_line),
        owner_id=player.id, zone=Zone.HAND,
    )
    player.add_to_zone(obj, Zone.HAND)
    return obj


def _library_card(player, name):
    obj = GameObject(Card(id=name, name=name, type_line="Instant", is_instant=True), owner_id=player.id,
                     zone=Zone.LIBRARY)
    player.add_to_zone(obj, Zone.LIBRARY)
    return obj


def _spec(text):
    card = Card(id="Probe", name="Probe", type_line="Sorcery", is_sorcery=True, oracle_text=text)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    return result.specs[0].effects[0]


@pytest.mark.parametrize("text, params", [
    ("Look at target opponent's hand and choose X cards from it. That player discards those cards.",
     {"target_kind": "opponent", "count": "x"}),
    ("Look at target player's hand and choose up to two cards from it. That player discards those cards.",
     {"target_kind": "player", "count": 2, "up_to": True}),
    ("Look at target player's hand and choose two cards from it. Put them on top of that player's library in any order.",
     {"target_kind": "player", "count": 2, "destination": "library_top"}),
    ("Look at target opponent's hand and choose a card from it. Put that card on top of that player's library.",
     {"target_kind": "opponent", "destination": "library_top"}),
    ("Target player reveals their hand. You choose a nonland card from it. That player puts that card into their "
     "library third from the top.",
     {"target_kind": "player", "exclude_land": True, "destination": "library_third"}),
])
def test_parse(text, params):
    effect = _spec(text)
    assert effect.type == "reveal_hand_choose_discard" and effect.params == params


def test_an_unlisted_tail_stays_unclaimed():
    card = Card(id="Probe", name="Probe", type_line="Sorcery", is_sorcery=True,
                oracle_text="Look at target player's hand and choose two cards from it. Exile those cards.")
    assert not parse_oracle(card).modeled


def test_choose_two_discards_both_picks():
    engine, state, p1, p2 = _setup()
    cards = [_hand_card(p2, n) for n in ("A", "B", "C")]
    RevealHandChooseDiscardEffect(count=2).apply(GameContext(state, engine), targets=[p2])
    engine.resolve_choice(cards[0].instance_id)
    engine.resolve_choice(cards[2].instance_id)
    assert state.pending_choice is None
    assert set(p2.graveyard) == {cards[0], cards[2]} and p2.hand == [cards[1]]


def test_up_to_lets_the_caster_stop_early():
    engine, state, p1, p2 = _setup()
    cards = [_hand_card(p2, n) for n in ("A", "B", "C")]
    RevealHandChooseDiscardEffect(count=2, up_to=True).apply(GameContext(state, engine), targets=[p2])
    assert state.pending_choice["optional"]
    engine.resolve_choice(cards[1].instance_id)
    engine.resolve_choice(None)  # that is enough
    assert state.pending_choice is None
    assert p2.graveyard == [cards[1]] and len(p2.hand) == 2


def test_count_is_capped_by_the_hand():
    engine, state, p1, p2 = _setup()
    only = _hand_card(p2, "A")
    RevealHandChooseDiscardEffect(count=3).apply(GameContext(state, engine), targets=[p2])
    assert state.pending_choice is None and p2.graveyard == [only]


def test_painful_memories_puts_the_pick_on_top_of_the_owners_library():
    engine, state, p1, p2 = _setup()
    below = _library_card(p2, "Below")
    keep, pick = _hand_card(p2, "Keep"), _hand_card(p2, "Pick")
    RevealHandChooseDiscardEffect(destination="library_top").apply(GameContext(state, engine), targets=[p2])
    engine.resolve_choice(pick.instance_id)
    assert p2.hand == [keep] and p2.library[-1] is pick and p2.library[-2] is below
    assert not p2.graveyard and not p1.library  # the chooser's own library is untouched


def test_agonizing_memories_two_picks_both_go_on_top():
    engine, state, p1, p2 = _setup()
    below = _library_card(p2, "Below")
    a, b, c = (_hand_card(p2, n) for n in "ABC")
    RevealHandChooseDiscardEffect(count=2, destination="library_top").apply(GameContext(state, engine), targets=[p2])
    engine.resolve_choice(a.instance_id)
    engine.resolve_choice(c.instance_id)
    assert {p2.library[-1], p2.library[-2]} == {a, c} and p2.library[-3] is below and p2.hand == [b]


def test_lost_hours_puts_a_nonland_card_third_from_the_top():
    engine, state, p1, p2 = _setup()
    rest, second, top = (_library_card(p2, n) for n in ("Rest", "Second", "Top"))
    land = _hand_card(p2, "Forest", "Land")
    spell, other = _hand_card(p2, "Bolt"), _hand_card(p2, "Shock")
    RevealHandChooseDiscardEffect(exclude_land=True, destination="library_third").apply(
        GameContext(state, engine), targets=[p2])
    offered = {o["instance_id"] for o in state.pending_choice["options"] if "instance_id" in o}
    assert offered == {spell.instance_id, other.instance_id}
    engine.resolve_choice(spell.instance_id)
    assert p2.library[-4:] == [rest, spell, second, top]  # the list end is the top (RULE 401.7)
    assert p2.library[-1] is top and land in p2.hand


def test_mind_warp_reads_the_announced_x():
    # the effect sentinel `_substitute_x` rewrites for an X spell
    from mtg_analyzer.game.rules.casting_mixin import CastingResolutionMixin

    engine, state, p1, p2 = _setup()
    cards = [_hand_card(p2, n) for n in "ABC"]
    effect = RevealHandChooseDiscardEffect(count="x")
    CastingResolutionMixin._substitute_x([effect], 2)
    effect.apply(GameContext(state, engine), targets=[p2])
    engine.resolve_choice(cards[0].instance_id)
    engine.resolve_choice(cards[1].instance_id)
    assert set(p2.graveyard) == {cards[0], cards[1]} and p2.hand == [cards[2]]


def test_discordant_dirge_sizes_the_pick_from_its_verse_counters():
    # "…choose up to X cards from it, where X is the number of verse counters on this enchantment" — a `bind`
    # measures X and the `$n` count reaches the effect as a real int.
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.game.game_engine import GameEngine

    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    dirge = GameObject(Card(
        id="Dirge", name="Discordant Dirge", type_line="Enchantment",
        oracle_text="At the beginning of your upkeep, you may put a verse counter on this enchantment.\n"
                    "{B}, Sacrifice this enchantment: Look at target opponent's hand and choose up to X cards from "
                    "it, where X is the number of verse counters on this enchantment. That player discards those "
                    "cards."), owner_id="p1", zone=Zone.BATTLEFIELD)
    dirge.controller_id = "p1"
    bind_from_catalogue(dirge)
    eng.state.add_to_battlefield(dirge)
    dirge.counters["verse"] = 2
    cards = [_hand_card(p2, n) for n in "ABC"]
    p1.mana_pool.add_many({"B": 1})
    eng.activate_ability(p1, dirge, 0, targets=[p2])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["count"] == 2
    eng.rules.resolve_choice(cards[0].instance_id)
    eng.rules.resolve_choice(cards[1].instance_id)
    assert set(p2.graveyard) == {cards[0], cards[1]} and p2.hand == [cards[2]]
