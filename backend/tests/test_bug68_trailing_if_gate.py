"""BUG-68: "A. If C, B." gates B, never the sentence before it.

RULE 608.2c: an instruction is performed as written, in order; a conditional clause ("if C, B") qualifies only the
instruction it introduces. The generic suffix gate (`segmenter._GENERIC_IF_SUFFIX_RE`) used to swallow the earlier
sentence, so Zealous Display pumped only on an opponent's turn and always untapped, and Scrib Nibblers always
gained life. RULE 701.20 / 608.2h: "it" in "exile the top card ... If it's a land card" is that exiled card.

Real cached cards through the real gate, and on a real `GameEngine`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import game, on_battlefield, vanilla

DISPLAY = "Zealous Display"
NIBBLERS = "Scrib Nibblers"
SHOVEL = "Graveyard Shovel"

#: Life gained by Scrib Nibblers' rider.
NIBBLERS_LIFE = 1
#: Pump granted by Zealous Display.
DISPLAY_POWER = 2


def _effects(name):
    return [e for spec in parse_oracle(get_cached_card(name)).specs for e in spec.effects]


def test_trailing_if_sentence_gates_only_its_own_effect_in_the_ir():
    by_type = {e.type: e for e in _effects(DISPLAY)}
    assert by_type["pump"].condition is None
    assert by_type["tap"].condition == {"kind": "not_your_turn"}
    effects = {e.type: e for e in _effects(NIBBLERS) if e.type in ("exile_top_of_library", "gain_life")}
    assert effects["exile_top_of_library"].condition is None
    assert effects["gain_life"].condition == {"kind": "is_card_type", "card_type": "land", "of": "created"}


def test_graveyard_shovel_is_never_claimed_with_a_misplaced_gate():
    # The exile is an interactive pick whose card the engine does not hand to a following sentence, so the card
    # stays unmodeled rather than gating the exile on its own condition and always gaining life.
    result = parse_oracle(get_cached_card(SHOVEL))
    gated = [e for spec in result.specs for e in spec.effects if e.type == "exile_hand_card" and e.condition]
    assert not gated
    assert not result.modeled


def test_inline_sentence_gate_does_not_reach_back_across_a_period():
    specs = parse_effect_body("You gain 2 life. If it's your turn, draw a card.")
    assert [(s.type, s.condition) for s in specs] == [
        ("gain_life", None), ("draw", {"kind": "your_turn"})]


def test_real_cards_stay_modeled():
    assert parse_oracle(get_cached_card(DISPLAY)).modeled
    assert parse_oracle(get_cached_card(NIBBLERS)).modeled


def _tapped_bear(engine):
    bear = vanilla(engine, "p1")
    bear.tapped = True
    engine.recompute_continuous_effects()
    return bear


def _cast_display(engine, player):
    player.mana_pool.add_many({"C": 12, "W": 3})
    engine.cast_spell(player, player.hand[0])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def test_zealous_display_on_your_turn_pumps_and_does_not_untap():
    eng, p1, _ = game(DISPLAY)
    bear = _tapped_bear(eng)
    _cast_display(eng, p1)
    assert bear.power == 2 + DISPLAY_POWER  # RULE 608.2c: the pump is not gated by the untap's condition
    assert bear.tapped


def test_zealous_display_on_an_opponents_turn_pumps_and_untaps():
    eng, p1, _ = game(DISPLAY)
    bear = _tapped_bear(eng)
    eng.state.active_player_index = 1  # "If it's not your turn": the opponent's turn
    _cast_display(eng, p1)
    assert bear.power == 2 + DISPLAY_POWER
    assert not bear.tapped


def _nibblers_activation(card_type_line, is_land):
    eng, p1, p2 = game()
    nibblers = on_battlefield(eng, "p1", NIBBLERS)
    top = GameObject(
        type(nibblers.card)(id="Top", name="Top", type_line=card_type_line, is_land=is_land),
        owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(top)
    life = p1.life
    eng.activate_ability(p1, nibblers, targets=[p2])
    eng.resolve_until_stable()
    assert top.zone == Zone.EXILE
    return p1.life - life


def test_scrib_nibblers_gains_life_only_when_the_exiled_card_is_a_land():
    assert _nibblers_activation("Land", True) == NIBBLERS_LIFE


def test_scrib_nibblers_gains_no_life_for_a_nonland_card():
    assert _nibblers_activation("Creature — Bear", False) == 0


def test_savage_offensive_gates_only_the_kicked_pump():
    # "Creatures you control gain first strike until end of turn. If this spell was kicked, they get +1/+1": the
    # first strike is unconditional, the kicker rider gates the +1/+1 alone.
    effects = _effects("Savage Offensive")
    assert [e.type for e in effects] == ["pump", "for_each"]
    assert effects[0].condition is None
    assert effects[1].condition == {"kind": "kicked", "min": 1}


def test_one_gate_covers_both_clauses_of_its_sentence():
    # Nissa's Revelation: "If it's a creature card, you draw cards equal to its power and you gain life equal to its
    # toughness" -- the gate covers the draw and the life gain (RULE 608.2c), never only the first conjunct.
    effects = _effects("Nissa's Revelation")
    gated = [e for e in effects if e.type == "bind"]
    gate = {"kind": "is_card_type", "card_type": "creature", "of": "revealed"}
    assert len(gated) == 2 and all(e.condition == gate for e in gated)
