"""PAR-286 milestone 5: "whenever an instant or sorcery spell you control deals damage [to an opponent]".

RULE 120.3 / 608.2: a resolving instant or sorcery is the damage source, so the head reads the DAMAGE event's
``source_is_instant_or_sorcery`` flag and its ``source_controller_id``. Blaze Commando, Satyr Firedancer and Flame
Channeler are driven by really casting a burn spell on the real engine; the near misses (an opponent's spell, a
creature's own damage, damage to a creature for the "to an opponent" head) must not fire.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import answer, card, cast, filler, game, named

CARDS = ["Blaze Commando", "Satyr Firedancer", "Flame Channeler // Embodiment of Flame"]
#: Lightning Bolt's printed damage.
BOLT = 3
SOLDIER_TOKENS = 2


def _segment(text):
    return segment_line(text, allow_spell_effect=True, provenance=ParserProvenance())


@pytest.mark.parametrize("name", CARDS)
def test_cards_are_modeled(name):
    card_ = CardDatabase(DB_PATH).get_card(name)
    assert card_ is not None
    assert parse_oracle(card_).coverage == MODELED


def test_head_reads_the_spell_source_you_control_and_nothing_nearby():
    assert _segment("whenever an instant or sorcery spell you control deals damage, draw a card.").claimed
    assert _segment("whenever a spell you control deals damage, draw a card.").claimed
    # near misses: an unscoped spell (no controller scope) and a colour-qualified spell stay unclaimed
    assert not _segment("whenever an instant or sorcery spell deals damage, draw a card.").claimed
    assert not _segment("whenever a red instant or sorcery spell you control deals damage, draw a card.").claimed


def _soldiers(engine):
    return [o for o in engine.state.battlefield if o.name == "Soldier"]


def test_blaze_commando_fires_for_my_burn_spell_not_for_the_opponents_or_a_creature():
    engine = game()
    card(engine, "Blaze Commando")
    victim = filler(engine, "Victim", type_line="Creature", player="p2", power=1, toughness=BOLT + 1)
    # near miss 1: the opponent's burn spell
    cast(engine, card(engine, "Lightning Bolt", player="p2", zone=Zone.HAND), targets=[victim])
    assert _soldiers(engine) == []
    # near miss 2: a creature I control dealing damage is not a spell
    attacker = filler(engine, "Pinger", type_line="Creature", power=2, toughness=2)
    engine.rules.deal_damage(victim, 1, source=attacker)
    engine.resolve_until_stable()
    assert _soldiers(engine) == []
    # the real thing: my Lightning Bolt
    cast(engine, card(engine, "Lightning Bolt", zone=Zone.HAND), targets=[engine.state.player_by_id("p2")])
    assert len(_soldiers(engine)) == SOLDIER_TOKENS


def _satyr_board():
    engine = game()
    card(engine, "Satyr Firedancer")
    theirs = filler(engine, "Theirs", type_line="Creature", player="p2", power=1, toughness=BOLT * 3)
    return engine, theirs


def test_satyr_firedancer_needs_the_damage_to_go_to_an_opponent():
    engine, theirs = _satyr_board()
    # near miss: burn aimed at a creature is not damage to an opponent, so Firedancer adds nothing
    cast(engine, card(engine, "Lightning Bolt", zone=Zone.HAND), targets=[theirs])
    assert theirs.damage_marked == BOLT
    # near miss: a creature of mine hitting the opponent is not a spell
    hitter = filler(engine, "Hitter", type_line="Creature", power=1, toughness=1)
    engine.rules.deal_damage(engine.state.player_by_id("p2"), 1, source=hitter)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and theirs.damage_marked == BOLT


def test_satyr_firedancer_repeats_the_damage_to_a_creature_that_player_controls():
    engine, theirs = _satyr_board()
    p2 = engine.state.player_by_id("p2")
    cast(engine, card(engine, "Lightning Bolt", zone=Zone.HAND), targets=[p2])
    assert p2.life == 20 - BOLT
    answer(engine)  # the trigger's target creature: the only one p2 controls
    assert theirs.damage_marked == BOLT  # "that much damage" to a creature that player controls


def test_flame_channeler_transforms_when_my_spell_deals_damage_but_not_theirs():
    engine = game()
    channeler = card(engine, "Flame Channeler // Embodiment of Flame")
    front = channeler.name
    cast(engine, card(engine, "Lightning Bolt", player="p2", zone=Zone.HAND), targets=[engine.state.player_by_id("p1")])
    assert channeler.name == front
    # near miss: a creature I control dealing damage is not a spell
    hitter = filler(engine, "Hitter", type_line="Creature", power=1, toughness=1)
    engine.rules.deal_damage(engine.state.player_by_id("p2"), 1, source=hitter)
    engine.resolve_until_stable()
    assert channeler.name == front
    cast(engine, card(engine, "Lightning Bolt", zone=Zone.HAND), targets=[engine.state.player_by_id("p2")])
    assert channeler.name != front
