"""MEC-67 — Teamwork's optional cast cost (RULE 702.194)."""

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

from tests.support.game import creature, make_engine


def _teamwork_spell():
    return Card(
        id="teamwork-spell", name="Teamwork Spell", type_line="Sorcery",
        mana_cost_string="{1}{R}", converted_mana_cost=2,
        oracle_text="Teamwork 4\nTeamwork Spell deals 1 damage to any target.",
        keywords=["Teamwork"],
    )


def _put(engine, card, power):
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    engine.state.add_to_battlefield(obj)
    return obj


def test_teamwork_offer_and_payment_tap_selected_creatures_and_mark_spell():
    engine = make_engine([creature(name="Filler")], hand=0)
    state, player = engine.state, engine.state.player_by_id("p1")
    first = _put(engine, creature(name="Strong", power=3, toughness=3), 3)
    second = _put(engine, creature(name="Helper", power=1, toughness=1), 1)
    spell = GameObject(_teamwork_spell(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    player.mana_pool.add_many({"R": 1, "C": 1})
    engine.begin_turn()
    state.current_step = "main1"

    offer = next(a for a in engine.legal_actions(player) if a.get("teamwork"))
    assert offer["teamwork_power"] == 4
    assert {row["instance_id"] for row in offer["teamwork_candidates"]} == {first.instance_id, second.instance_id}

    engine.cast_spell(player, spell, teamwork=True, teamwork_choices=[first.instance_id, second.instance_id])
    assert first.tapped and second.tapped
    assert spell.teamwork_paid is True


def test_teamwork_rejects_insufficient_or_duplicate_choices_without_tapping():
    engine = make_engine([creature(name="Filler")], hand=0)
    state, player = engine.state, engine.state.player_by_id("p1")
    first = _put(engine, creature(name="Strong", power=3, toughness=3), 3)
    spell = GameObject(_teamwork_spell(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    player.mana_pool.add_many({"R": 1, "C": 1})
    engine.begin_turn()
    state.current_step = "main1"

    assert not engine.can_cast(player, spell, teamwork=True, teamwork_choices=[first.instance_id])
    assert not engine.can_cast(player, spell, teamwork=True, teamwork_choices=[first.instance_id, first.instance_id])
    with pytest.raises(ValueError):
        engine.cast_spell(player, spell, teamwork=True, teamwork_choices=[first.instance_id])
    assert not first.tapped
