"""PAR-284: the Shrine cycle -- "the number of cards in all graveyards with the same name as that spell" (RULE 201.2).

The count is measured as the cast trigger resolves, against the spell the trigger fired for (`trigger_subject`). The
spell is still on the stack then, so it is counted only if a copy of that name already sits in a graveyard.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par284_this_way_windows import _card, _engine

SHRINES = {
    "Aven Shrine": "Whenever a player casts a spell, that player gains X life, where X is the number of cards in all "
                   "graveyards with the same name as that spell.",
    "Cephalid Shrine": "Whenever a player casts a spell, counter that spell unless that player pays {X}, where X is the "
                       "number of cards in all graveyards with the same name as the spell.",
    "Nantuko Shrine": "Whenever a player casts a spell, that player creates X 1/1 green Squirrel creature tokens, where X "
                      "is the number of cards in all graveyards with the same name as that spell.",
    "Dwarven Shrine": "Whenever a player casts a spell, this enchantment deals X damage to that player, where X is twice "
                      "the number of cards in all graveyards with the same name as that spell.",
}
SPELL_NAME = "Twin Probe"
COPIES_IN_GRAVEYARDS = 2  # one in each graveyard


def _shrine(name):
    card = _card(name, "Enchantment", SHRINES[name])
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    return card, result


def _world(name):
    eng = _engine()
    card, result = _shrine(name)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    attach_to_object(obj, result.specs)
    eng.state.battlefield.append(obj)
    for player in eng.state.players:  # copies of the spell's name in *all* graveyards
        player.graveyard.append(GameObject(_card(SPELL_NAME, "Instant", is_instant=True), owner_id=player.id, zone=Zone.GRAVEYARD))
    player.graveyard.append(GameObject(_card("Other Card", "Instant", is_instant=True), owner_id=player.id, zone=Zone.GRAVEYARD))
    return eng


def _cast_probe(eng, caster_index=1):
    caster = eng.state.players[caster_index]
    spell = GameObject(_card(SPELL_NAME, "Instant", "You gain 1 life.", is_instant=True), owner_id=caster.id, zone=Zone.HAND)
    attach_to_object(spell, parse_oracle(spell.card).specs)
    caster.hand.append(spell)
    caster.mana_pool.add_many({"C": 10})
    eng.cast_spell(caster, spell)
    return caster, spell


@pytest.mark.parametrize("name", sorted(SHRINES))
def test_every_shrine_is_modeled(name):
    _shrine(name)


def test_the_name_count_is_claimed_only_under_a_cast_trigger():
    card = _card("Probe", "Enchantment", "Whenever a creature dies, you gain X life, where X is the number of cards in all "
                 "graveyards with the same name as that spell.")
    assert not parse_oracle(card).modeled


def test_aven_shrine_gains_one_life_per_same_name_card():
    eng = _world("Aven Shrine")
    caster, _ = _cast_probe(eng)
    before = caster.life
    eng.resolve_until_stable()
    assert caster.life == before + COPIES_IN_GRAVEYARDS + 1  # the gains of 2 from the trigger and 1 from the spell


def test_nantuko_shrine_makes_squirrels_for_the_caster():
    eng = _world("Nantuko Shrine")
    _cast_probe(eng)
    eng.resolve_until_stable()
    squirrels = [o for o in eng.state.battlefield if o.is_token and o.controller_id == "p2"]
    assert len(squirrels) == COPIES_IN_GRAVEYARDS


def test_dwarven_shrine_deals_twice_the_count_to_the_caster():
    eng = _world("Dwarven Shrine")
    caster, _ = _cast_probe(eng)
    before = caster.life
    eng.resolve_until_stable()
    assert caster.life == before - 2 * COPIES_IN_GRAVEYARDS + 1  # the spell's own 1 life


def test_a_different_name_counts_nothing():
    eng = _world("Aven Shrine")
    caster = eng.state.players[1]
    spell = GameObject(_card("Unrelated", "Instant", "You gain 1 life.", is_instant=True), owner_id=caster.id, zone=Zone.HAND)
    attach_to_object(spell, parse_oracle(spell.card).specs)
    caster.hand.append(spell)
    caster.mana_pool.add_many({"C": 5})
    before = caster.life
    eng.cast_spell(caster, spell)
    eng.resolve_until_stable()
    assert caster.life == before + 1


@pytest.mark.parametrize("answer", ["pay", "decline"])
def test_cephalid_shrine_taxes_the_caster_by_the_count(answer):
    eng = _world("Cephalid Shrine")
    caster, spell = _cast_probe(eng)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice  # the shared pay-or-counter flow reuses the ward choice
    assert choice is not None and choice["kind"] == "ward" and f"{{{COPIES_IN_GRAVEYARDS}}}" in choice["prompt"]
    before_pool = caster.mana_pool.total()
    eng.rules.resolve_choice(answer)
    eng.resolve_until_stable()
    if answer == "pay":
        assert caster.mana_pool.total() == before_pool - COPIES_IN_GRAVEYARDS
        assert spell.zone == Zone.GRAVEYARD and caster.life > 20  # resolved: its life gain happened
    else:
        assert caster.life == 20  # countered: no life gain
