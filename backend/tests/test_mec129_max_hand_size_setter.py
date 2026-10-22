"""MEC-129: "Your maximum hand size is N." (RULE 402.2) — the absolute setter.

``hand_size_set`` orders by RULE 613.7 timestamp against ``no_max_hand_size``
(static and rest-of-game); the relative ``hand_size_modifier`` applies on top.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.game import land, make_engine


def _engine():
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    return GameEngine(state), state, p1, p2


def _permanent(name, text, type_line="Enchantment"):
    return Card(id=name, name=name, type_line=type_line, oracle_text=text)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _fill_hand(player, n):
    for i in range(n):
        player.hand.append(GameObject(
            Card(id=f"F{i}", name=f"F{i}", type_line="Instant", is_instant=True),
            owner_id=player.id, zone=Zone.HAND))


def _cleanup(engine, state):
    engine._step_cleanup()
    while state.pending_choice:
        engine.resolve_pending_choice(state.pending_choice["options"][0]["id"])


def test_parse_claims_fixed_size_statement():
    specs = static_effect_specs("your maximum hand size is 5")
    assert [(s.type, s.params) for s in specs] == [("hand_size_set", {"affects": "you", "amount": 5})]
    assert static_effect_specs("each opponent's maximum hand size is 5") is None


def test_real_oracle_text_is_modeled():
    card = _permanent("Null Profusion Shaped", "Your maximum hand size is two.")
    result = parse_oracle(card)
    assert result.unclaimed == []
    assert result.specs[0].effects[0].type == "hand_size_set"


def test_setter_lowers_and_raises_the_cleanup_limit():
    engine, state, p1, _ = _engine()
    _bf(state, _permanent("Low", "Your maximum hand size is two."))
    _fill_hand(p1, 5)
    _cleanup(engine, state)
    assert len(p1.hand) == 2

    engine, state, p1, _ = _engine()
    _bf(state, _permanent("High", "Your maximum hand size is eleven."))
    _fill_hand(p1, 10)
    _cleanup(engine, state)
    assert len(p1.hand) == 10


def test_setter_only_affects_its_controller():
    engine, state, p1, p2 = _engine()
    _bf(state, _permanent("Low", "Your maximum hand size is two."), controller="p2")
    _fill_hand(p1, 7)
    assert continuous.set_maximum_hand_size(state, p1) is None
    assert continuous.set_maximum_hand_size(state, p2) == 2


def test_newest_setter_wins_by_timestamp():
    engine, state, p1, _ = _engine()
    _bf(state, _permanent("Old", "Your maximum hand size is two."))
    _bf(state, _permanent("New", "Your maximum hand size is eleven."))
    assert continuous.set_maximum_hand_size(state, p1) == 11


def test_no_maximum_orders_against_setter_by_timestamp():
    engine, state, p1, _ = _engine()
    _bf(state, _permanent("Unlimited", "You have no maximum hand size."))
    _bf(state, _permanent("Low", "Your maximum hand size is two."))
    assert not continuous.has_no_maximum_hand_size(state, p1)
    assert continuous.set_maximum_hand_size(state, p1) == 2

    engine, state, p1, _ = _engine()
    _bf(state, _permanent("Low", "Your maximum hand size is two."))
    _bf(state, _permanent("Unlimited", "You have no maximum hand size."))
    assert continuous.has_no_maximum_hand_size(state, p1)
    assert continuous.set_maximum_hand_size(state, p1) is None


def test_rest_of_game_grant_is_ordered_too():
    engine, state, p1, _ = _engine()
    state.no_max_hand_size_player_ids.add("p1")
    state.no_max_hand_size_stamps["p1"] = state.next_timestamp()
    _bf(state, _permanent("Low", "Your maximum hand size is two."))
    assert continuous.set_maximum_hand_size(state, p1) == 2
    assert not continuous.has_no_maximum_hand_size(state, p1)


def test_relative_modifier_applies_on_top_of_setter():
    engine, state, p1, _ = _engine()
    _bf(state, _permanent("Low", "Your maximum hand size is five."))
    _bf(state, _permanent("Thought Eater Shaped", "Your maximum hand size is reduced by 3."))
    _fill_hand(p1, 6)
    _cleanup(engine, state)
    assert len(p1.hand) == 2


def test_setter_ends_when_source_leaves():
    engine, state, p1, _ = _engine()
    src = _bf(state, _permanent("Low", "Your maximum hand size is two."))
    state.remove_from_battlefield(src)
    assert continuous.set_maximum_hand_size(state, p1) is None


def test_sea_gate_restoration_draws_hand_plus_one_and_lifts_the_limit():
    eng = make_engine([land()] * 30, [land()] * 30, hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    state = eng.state
    p1 = state.player_by_id("p1")
    _fill_hand(p1, 3)
    spell = GameObject(
        Card(id="SGR", name="Sea Gate Restoration Shaped", type_line="Sorcery", is_sorcery=True,
             mana_cost_string="{4}{U}{U}", converted_mana_cost=6,
             oracle_text="Draw cards equal to the number of cards in your hand plus one. "
                         "You have no maximum hand size for the rest of the game."),
        owner_id="p1", zone=Zone.HAND)
    p1.hand.append(spell)
    bind_from_catalogue(spell)
    p1.mana_pool.add("U", 20)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert len(p1.hand) == 3 + 4  # hand of 3 (spell already on the stack) + 4 drawn
    assert continuous.has_no_maximum_hand_size(state, p1)
    assert continuous.set_maximum_hand_size(state, p1) is None
