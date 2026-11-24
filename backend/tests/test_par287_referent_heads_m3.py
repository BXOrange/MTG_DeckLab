"""PAR-287 milestone 3 (B): Volo's type filter, Nullstone Gargoyle's all-player ordinal, Decree of Silence's bookkeeping,
and the "that many" group (Phyrexian Negator / Totem, Varina). Real events on real cards; each with a near miss."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import RICH, answer, attack, card, cast, filler, game

NEWLY = ["Volo, Guide to Monsters", "Nullstone Gargoyle", "Decree of Silence", "Phyrexian Negator", "Phyrexian Totem",
         "Varina, Lich Queen"]
#: Decree of Silence's printed threshold of depletion counters.
DECREE_LIMIT = 3


@pytest.mark.parametrize("name", NEWLY)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


# --- Volo -------------------------------------------------------------------------------------------------------

def _volo_cast(engine, type_line, **kw):
    spell = filler(engine, "Spell", type_line=type_line, zone=Zone.HAND, power=1, toughness=1, **kw)
    cast(engine, spell)
    answer(engine)
    engine.resolve_until_stable()
    return [o for o in engine.state.battlefield if o.name == "Spell"]


def test_volo_copies_a_creature_spell_sharing_no_type():
    engine = game()
    card(engine, "Volo, Guide to Monsters")
    filler(engine, "Their Elf", type_line="Creature — Elf", player="p2", power=1, toughness=1)   # not "a creature you control"
    assert len(_volo_cast(engine, "Creature — Elf")) == 2                                          # the spell and its copy


def test_volo_does_not_copy_when_a_battlefield_creature_shares_a_type():
    engine = game()
    card(engine, "Volo, Guide to Monsters")
    filler(engine, "Mine", type_line="Creature — Elf", power=1, toughness=1)
    assert len(_volo_cast(engine, "Creature — Elf")) == 1


def test_volo_does_not_copy_when_a_graveyard_creature_card_shares_a_type():
    engine = game()
    card(engine, "Volo, Guide to Monsters")
    filler(engine, "Dead", type_line="Creature — Elf", zone=Zone.GRAVEYARD, power=1, toughness=1)
    assert len(_volo_cast(engine, "Creature — Elf")) == 1


def test_volo_does_not_copy_a_changeling_that_shares_a_type_with_volo():
    engine = game()
    card(engine, "Volo, Guide to Monsters")                            # a Human Wizard
    assert len(_volo_cast(engine, "Creature — Shapeshifter", keywords=["Changeling"])) == 1


def test_volo_ignores_noncreature_and_opponent_casts():
    engine = game()
    card(engine, "Volo, Guide to Monsters")
    spell = filler(engine, "Theirs", type_line="Creature — Elf", player="p2", zone=Zone.HAND, power=1, toughness=1,
                   keywords=["Flash"])
    cast(engine, spell)
    answer(engine)
    assert len([o for o in engine.state.battlefield if o.name == "Theirs"]) == 1


# --- Nullstone Gargoyle -----------------------------------------------------------------------------------------

def _opt(engine, player):
    spell = card(engine, "Opt", player=player, zone=Zone.HAND)
    cast(engine, spell)
    answer(engine)
    return spell


def _countered(engine):
    return [e for e in engine.state.events_this_turn() if str(e.type) == "SPELL_COUNTERED"]


def test_nullstone_counters_only_the_first_noncreature_spell_of_the_turn_across_players():
    engine = game()
    card(engine, "Nullstone Gargoyle")
    _opt(engine, "p2")
    assert len(_countered(engine)) == 1
    _opt(engine, "p1")                                                   # a different caster: still the second spell
    assert len(_countered(engine)) == 1


def test_nullstone_counts_its_own_controllers_spell_as_the_first():
    engine = game()
    card(engine, "Nullstone Gargoyle")
    _opt(engine, "p1")
    assert len(_countered(engine)) == 1


def test_nullstone_ignores_a_creature_spell_before_the_first_noncreature_one():
    engine = game()
    card(engine, "Nullstone Gargoyle")
    creature = filler(engine, "Bear", type_line="Creature — Bear", zone=Zone.HAND, power=2, toughness=2)
    cast(engine, creature)
    assert creature.zone == Zone.BATTLEFIELD and not _countered(engine)
    _opt(engine, "p2")
    assert len(_countered(engine)) == 1


# --- Decree of Silence ------------------------------------------------------------------------------------------

def test_decree_counters_each_opponent_spell_and_is_sacrificed_at_the_limit():
    engine = game()
    decree = card(engine, "Decree of Silence")
    for expected in range(1, DECREE_LIMIT + 1):
        _opt(engine, "p2")
        assert len(_countered(engine)) == expected
        if expected < DECREE_LIMIT:
            assert decree.zone == Zone.BATTLEFIELD and decree.counters.get("depletion") == expected
    assert decree.zone == Zone.GRAVEYARD


def test_decree_ignores_its_controllers_own_spells():
    engine = game()
    decree = card(engine, "Decree of Silence")
    _opt(engine, "p1")
    assert not _countered(engine) and not decree.counters.get("depletion")


# --- "that many" ------------------------------------------------------------------------------------------------

def test_negator_sacrifices_that_many_permanents_by_the_players_choice():
    engine = game()
    negator = card(engine, "Phyrexian Negator")
    mine = [filler(engine, f"Mine{i}", power=1, toughness=1) for i in range(3)]
    theirs = filler(engine, "Theirs", player="p2", power=1, toughness=1)
    before = len([o for o in engine.state.battlefield if o.controller_id == "p1"])
    engine.rules.deal_damage(negator, 2, source=theirs, combat=False)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is not None                       # the player picks, nothing auto-chosen
    answer(engine)
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.controller_id == "p1"]) == before - 2
    assert theirs.zone == Zone.BATTLEFIELD and mine


def test_negator_one_damage_sacrifices_one():
    engine = game()
    negator = card(engine, "Phyrexian Negator")
    filler(engine, "Mine", power=1, toughness=1)
    theirs = filler(engine, "Theirs", player="p2", power=1, toughness=1)
    before = len([o for o in engine.state.battlefield if o.controller_id == "p1"])
    engine.rules.deal_damage(negator, 1, source=theirs, combat=False)
    engine.resolve_until_stable()
    answer(engine)
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.controller_id == "p1"]) == before - 1


def test_totem_sacrifices_only_while_it_is_a_creature():
    engine = game()
    totem = card(engine, "Phyrexian Totem")
    filler(engine, "Mine", power=1, toughness=1)
    theirs = filler(engine, "Theirs", player="p2", power=1, toughness=1)
    before = len([o for o in engine.state.battlefield if o.controller_id == "p1"])
    engine.rules.deal_damage(totem, 1, source=theirs, combat=False)     # not a creature: the intervening if fails
    engine.resolve_until_stable()
    answer(engine)
    assert len([o for o in engine.state.battlefield if o.controller_id == "p1"]) == before


def test_varina_draws_discards_and_gains_the_number_of_attacking_zombies():
    engine = game()
    card(engine, "Varina, Lich Queen")
    zombies = [filler(engine, f"Z{i}", type_line="Creature — Zombie", power=1, toughness=1) for i in range(2)]
    other = filler(engine, "Other", type_line="Creature — Elf", power=1, toughness=1)
    for i in range(3):
        filler(engine, f"Hand{i}", zone=Zone.HAND, power=1, toughness=1)
    p1 = engine.state.player_by_id("p1")
    hand, library = len(p1.hand), len(p1.library)
    attack(engine, [*zombies, other])
    answer(engine)
    engine.resolve_until_stable()
    assert len(p1.library) == library - 2 and len(p1.hand) == hand       # drew 2, discarded 2
    assert p1.life == 20 + 2                                              # the elf is not a Zombie


def test_varina_does_not_trigger_for_a_nonzombie_attack():
    engine = game()
    card(engine, "Varina, Lich Queen")
    other = filler(engine, "Other", type_line="Creature — Elf", power=1, toughness=1)
    p1 = engine.state.player_by_id("p1")
    library = len(p1.library)
    attack(engine, [other])
    answer(engine)
    assert len(p1.library) == library and p1.life == 20
