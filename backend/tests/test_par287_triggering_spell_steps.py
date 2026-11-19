"""PAR-287 milestone 1: a SPELL_CAST trigger's body that acts on "that spell" (the spell whose cast fired it).

`counter that spell`, `copy that spell` and the source's own `sacrifice ~` chain as ordered steps; "that spell" is the
firing event's actual spell, never a RULE 115 target. Every behaviour test drives the real card against a bystander
spell or permanent that must stay untouched, plus the path where the trigger must not fire.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import RICH, card, cast, filler, game, main_phase

NEWLY_COVERED = ["Hesitation", "Lunar Force", "Double Down", "Case of the Shifting Visage", "Reflections of Littjara"]  # last: hand-authored too

#: The cast-trigger source's own spell and the bystander's spell are both vanilla creatures with this many bodies.
ONE_BODY = 1


def _creatures(engine, name):
    return [o for o in engine.state.battlefield if o.name == name]


def _cast_as(engine, obj, player):
    p = engine.state.player_by_id(player)
    # A creature spell is sorcery speed: it must be the caster's own turn.
    engine.state.active_player_index = next(i for i, pl in enumerate(engine.state.players) if pl.id == player)
    main_phase(engine)
    p.mana_pool.add_many(RICH)
    engine.cast_spell(p, obj)
    engine.resolve_until_stable()


@pytest.mark.parametrize("name", NEWLY_COVERED)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def test_hesitation_sacrifices_itself_and_counters_exactly_the_cast_spell():
    engine = game()
    hesitation = card(engine, "Hesitation")
    first = filler(engine, "First", mv=1, power=1, toughness=1, zone=Zone.HAND)
    _cast_as(engine, first, "p1")
    assert first.zone == Zone.GRAVEYARD                 # countered, not resolved
    assert not _creatures(engine, "First")
    assert hesitation.zone == Zone.GRAVEYARD            # sacrificed by its own trigger
    # The enchantment is gone, so a later spell by the same player is a near miss: nothing counters it.
    second = filler(engine, "Second", mv=1, power=1, toughness=1, zone=Zone.HAND)
    _cast_as(engine, second, "p1")
    assert len(_creatures(engine, "Second")) == ONE_BODY


def test_hesitation_counters_an_opponents_spell_too():
    engine = game()
    hesitation = card(engine, "Hesitation")
    theirs = filler(engine, "Theirs", mv=1, power=1, toughness=1, player="p2", zone=Zone.HAND)
    _cast_as(engine, theirs, "p2")
    assert theirs.zone == Zone.GRAVEYARD and hesitation.zone == Zone.GRAVEYARD


def test_lunar_force_ignores_its_controllers_own_spell_and_counters_an_opponents():
    engine = game()
    force = card(engine, "Lunar Force")
    mine = filler(engine, "Mine", mv=1, power=1, toughness=1, zone=Zone.HAND)
    _cast_as(engine, mine, "p1")
    assert len(_creatures(engine, "Mine")) == ONE_BODY    # "an opponent casts": the controller's own cast is a near miss
    assert force.zone == Zone.BATTLEFIELD
    theirs = filler(engine, "Theirs", mv=1, power=1, toughness=1, player="p2", zone=Zone.HAND)
    _cast_as(engine, theirs, "p2")
    assert theirs.zone == Zone.GRAVEYARD and not _creatures(engine, "Theirs")
    assert force.zone == Zone.GRAVEYARD
    assert len(_creatures(engine, "Mine")) == ONE_BODY    # the bystander permanent is untouched


def test_double_down_copies_only_the_outlaw_spell_you_cast():
    engine = game()
    card(engine, "Double Down")
    rogue = filler(engine, "Rogue Spell", type_line="Creature — Rogue", mv=1, power=1, toughness=1, zone=Zone.HAND)
    _cast_as(engine, rogue, "p1")
    assert len(_creatures(engine, "Rogue Spell")) == 2   # the spell and its token copy (RULE 707.10b)
    elf = filler(engine, "Elf Spell", type_line="Creature — Elf", mv=1, power=1, toughness=1, zone=Zone.HAND)
    _cast_as(engine, elf, "p1")
    assert len(_creatures(engine, "Elf Spell")) == ONE_BODY   # not an outlaw: no copy
    theirs = filler(engine, "Their Rogue", type_line="Creature — Rogue", mv=1, power=1, toughness=1,
                    player="p2", zone=Zone.HAND)
    _cast_as(engine, theirs, "p2")
    assert len(_creatures(engine, "Their Rogue")) == ONE_BODY   # "you cast": an opponent's outlaw is not copied


def test_double_down_copy_does_not_retrigger_on_the_copy():
    engine = game()
    card(engine, "Double Down")
    rogue = filler(engine, "Rogue Spell", type_line="Creature — Rogue", mv=1, power=1, toughness=1, zone=Zone.HAND)
    _cast_as(engine, rogue, "p1")
    assert len(_creatures(engine, "Rogue Spell")) == 2   # RULE 707.10: a copy is not cast, so no third body


def test_case_of_the_shifting_visage_copies_only_once_solved():
    engine = game()
    case = card(engine, "Case of the Shifting Visage")
    before = filler(engine, "Early", type_line="Creature", mv=1, power=1, toughness=1, zone=Zone.HAND)
    _cast_as(engine, before, "p1")
    assert len(_creatures(engine, "Early")) == ONE_BODY   # unsolved: no copy (RULE 719.4)
    case.is_solved = True
    after = filler(engine, "Late", type_line="Creature", mv=1, power=1, toughness=1, zone=Zone.HAND)
    _cast_as(engine, after, "p1")
    assert len(_creatures(engine, "Late")) == 2
    legend = filler(engine, "Legend", type_line="Legendary Creature", mv=1, power=1, toughness=1, zone=Zone.HAND)
    _cast_as(engine, legend, "p1")
    assert len(_creatures(engine, "Legend")) == ONE_BODY   # nonlegendary only
