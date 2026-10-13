"""PAR-126 - "a spell or ability an opponent controls causes you to discard `<X>`" (RULE 603.1 / 614.1).

MEC-101 built the engine primitive (``DISCARD_CARD.cause_controller_id`` + ``requires_opponent_caused_discard``);
this ticket teaches the parser the wrapper so the printed cycle is MODELED instead of hand-authored one by one:
the trigger head (self "this card" / controller "a card"), the delayed graveyard returns, "that player loses N
life" naming the cause's controller, and the Wilt-Leaf Liege replacement. Each family is parsed from its real
oracle text and then run against the real engine: an opponent-caused discard fires it, a self-caused one
(cleanup, own cost) does not.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

TRIGGER_KEYS = {"event": "DISCARD_CARD", "requires_opponent_caused_discard": True}

CARDS = {
    "Gorilla Tactics": (
        "Instant",
        "Create two 2/2 green Gorilla creature tokens.\n"
        "When a spell or ability an opponent controls causes you to discard this card, "
        "create two 2/2 green Gorilla creature tokens.",
    ),
    "Quagnoth": (
        "Creature - Beast",
        "Protection from red\nWhen a spell or ability an opponent controls causes you to discard this card, "
        "return it to your hand.",
    ),
    "Sand Golem": (
        "Artifact Creature - Golem",
        "When a spell or ability an opponent controls causes you to discard this card, return this card from "
        "your graveyard to the battlefield with a +1/+1 counter on it at the beginning of the next end step.",
    ),
    "Mangara's Blessing": (
        "Instant",
        "You gain 5 life.\nWhen a spell or ability an opponent controls causes you to discard this card, "
        "you gain 2 life, and you return this card from your graveyard to your hand at the beginning of the "
        "next end step.",
    ),
    "Psychic Purge": (
        "Sorcery",
        "Psychic Purge deals 1 damage to any target.\nWhen a spell or ability an opponent controls causes you "
        "to discard this card, that player loses 5 life.",
    ),
    "Spiritual Focus": (
        "Enchantment",
        "Whenever a spell or ability an opponent controls causes you to discard a card, you gain 2 life and "
        "you may draw a card.",
    ),
    "Wilt-Leaf Liege": (
        "Creature - Elf Knight",
        "If a spell or ability an opponent controls causes you to discard this card, put it onto the "
        "battlefield instead of putting it into your graveyard.",
    ),
}


def card_of(name):
    type_line, text = CARDS[name]
    creature = "Creature" in type_line
    return Card(
        id=name, name=name, type_line=type_line, oracle_text=text,
        is_instant=type_line.startswith("Instant"), is_sorcery=type_line.startswith("Sorcery"),
        is_creature=creature, power=1 if creature else None, toughness=1 if creature else None,
    )


def make(name, zone=Zone.HAND, owner="p1"):
    type_line, text = CARDS[name]
    obj = GameObject(card_of(name), owner_id=owner, zone=zone)
    obj.controller_id = owner
    return obj


def engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def opponent_cause(controller="p2"):
    obj = GameObject(Card(id="Hostile", name="Hostile", type_line="Sorcery"), owner_id=controller, zone=Zone.STACK)
    obj.controller_id = controller
    return obj


def hand_card(eng, name):
    obj = make(name)
    bind_from_catalogue(obj)
    eng.state.player_by_id("p1").hand.append(obj)
    return obj


def end_step(eng):
    eng.state.current_step = "end"
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()


def tokens(eng):
    return [p for p in eng.state.permanents_controlled_by("p1") if p.is_token]


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CARDS))
def test_cycle_is_modeled(name):
    result = parse_oracle(card_of(name))
    assert result.coverage == MODELED, result


def test_self_head_scopes_to_the_discarded_card():
    specs = parse_oracle(card_of("Quagnoth")).specs
    trig = next(s for s in specs if s.ability_kind == "triggered").trigger
    assert trig == {**TRIGGER_KEYS, "condition": {"subject": "self"}}


def test_player_head_scopes_to_the_controller():
    specs = parse_oracle(card_of("Spiritual Focus")).specs
    assert specs[0].trigger == {**TRIGGER_KEYS, "condition": {"subject": "you"}}


def test_wrapper_without_opponent_scope_is_not_claimed():
    """Library of Leng's "an effect causes you to discard" is a broader, non-opponent-scoped condition."""
    text = "If an effect causes you to discard a card, discard it, but you may put it on top of your library."
    result = parse_oracle(Card(id="l", name="Library of Leng", type_line="Artifact", oracle_text=text))
    assert result.coverage != MODELED
    text = "When a spell or ability you control causes you to discard this card, draw a card."
    result = parse_oracle(Card(id="l", name="X", type_line="Instant", oracle_text=text))
    assert result.coverage != MODELED


def test_delayed_graveyard_return_row():
    (spec,) = parse_effect_body("return ~ from your graveyard to the battlefield with a +1/+1 counter on it at the "
                                "beginning of the next end step")
    assert spec.type == "create_delayed_trigger"
    assert spec.params["effects"][0]["type"] == "return_self_from_graveyard"
    assert spec.params["effects"][0]["params"]["extra_counters"] == {"kind": "+1/+1", "count": 1}


def test_attacking_delayed_return_is_not_claimed():
    assert parse_effect_body("return ~ from your graveyard to the battlefield tapped and attacking at the "
                             "beginning of the next end step") is None


# ---------------------------------------------------------------------------
# Engine: opponent-caused fires, self-caused does not
# ---------------------------------------------------------------------------


def test_gorilla_tactics_tokens_on_opponent_discard_only():
    eng = engine()
    obj = hand_card(eng, "Gorilla Tactics")
    eng.rules.discard_specific(obj, cause=opponent_cause())
    eng.resolve_until_stable()
    assert len(tokens(eng)) == 2

    eng2 = engine()
    obj2 = hand_card(eng2, "Gorilla Tactics")
    eng2.rules.discard_specific(obj2)  # cleanup / own cost: no cause
    eng2.resolve_until_stable()
    assert not tokens(eng2)


def test_quagnoth_returns_to_hand_only_when_opponent_caused():
    eng = engine()
    obj = hand_card(eng, "Quagnoth")
    eng.rules.discard_specific(obj, cause=opponent_cause())
    eng.resolve_until_stable()
    p1 = eng.state.player_by_id("p1")
    assert obj in p1.hand and obj not in p1.graveyard

    eng2 = engine()
    obj2 = hand_card(eng2, "Quagnoth")
    eng2.rules.discard_specific(obj2, cause=opponent_cause("p1"))  # a cost the discarder paid themself
    eng2.resolve_until_stable()
    assert obj2 in eng2.state.player_by_id("p1").graveyard


def test_sand_golem_returns_at_end_step_with_a_counter():
    eng = engine()
    obj = hand_card(eng, "Sand Golem")
    eng.rules.discard_specific(obj, cause=opponent_cause())
    eng.resolve_until_stable()
    p1 = eng.state.player_by_id("p1")
    assert obj in p1.graveyard
    end_step(eng)
    assert obj in eng.state.permanents()
    assert obj.counters.get("+1/+1") == 1


def test_mangaras_blessing_gains_life_and_returns_at_end_step():
    eng = engine()
    obj = hand_card(eng, "Mangara's Blessing")
    p1 = eng.state.player_by_id("p1")
    eng.rules.discard_specific(obj, cause=opponent_cause())
    eng.resolve_until_stable()
    assert p1.life == 22
    assert obj in p1.graveyard
    end_step(eng)
    assert obj in p1.hand


def test_psychic_purge_hits_the_cause_controller_not_the_discarder():
    eng = engine()
    obj = hand_card(eng, "Psychic Purge")
    eng.rules.discard_specific(obj, cause=opponent_cause("p2"))
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 15
    assert eng.state.player_by_id("p1").life == 20


def test_spiritual_focus_on_battlefield_gains_life_per_opponent_discard():
    eng = engine()
    p1 = eng.state.player_by_id("p1")
    focus = make("Spiritual Focus", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(focus)
    eng.state.add_to_battlefield(focus)
    victim = GameObject(Card(id="V", name="V", type_line="Instant"), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(victim)
    eng.rules.discard_specific(victim, cause=opponent_cause())
    eng.resolve_until_stable()
    assert p1.life == 22

    victim2 = GameObject(Card(id="V2", name="V2", type_line="Instant"), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(victim2)
    eng.rules.discard_specific(victim2)  # self-caused
    eng.resolve_until_stable()
    assert p1.life == 22


def test_wilt_leaf_liege_enters_battlefield_instead_of_graveyard():
    eng = engine()
    obj = hand_card(eng, "Wilt-Leaf Liege")
    eng.rules.discard_specific(obj, cause=opponent_cause())
    eng.resolve_until_stable()
    p1 = eng.state.player_by_id("p1")
    assert obj in eng.state.permanents() and obj not in p1.graveyard

    eng2 = engine()
    obj2 = hand_card(eng2, "Wilt-Leaf Liege")
    eng2.rules.discard_specific(obj2)
    assert obj2 in eng2.state.player_by_id("p1").graveyard
