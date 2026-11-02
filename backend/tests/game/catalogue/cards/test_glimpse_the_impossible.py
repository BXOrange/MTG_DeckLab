"""Glimpse the Impossible (hand-authored)."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _end_step, _game

NAME = "Glimpse the Impossible"


def _cast_glimpse(engine):
    caster = engine.state.player_by_id("p1")
    caster.mana_pool.add("R", 1)
    caster.mana_pool.add("C", 2)
    spell = _card(engine, NAME, zone=Zone.HAND)
    engine.rules.cast_spell(caster, spell, targets=[])
    engine.resolve_until_stable()
    return spell


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first][:1] == ["spell_effect"]


def test_exiles_the_top_three_and_lets_you_play_them_this_turn():
    engine = _game()
    _cast_glimpse(engine)
    p1 = engine.state.player_by_id("p1")
    assert len(p1.exile) == 3
    assert len(p1.library) == 8 - 3
    # RULE 601.3b window: each exiled card carries a this-turn play permission.
    assert all(o.instance_id in engine.state.temp_play_permissions for o in p1.exile)


def test_leftovers_go_to_the_graveyard_at_the_next_end_step_and_each_makes_a_spawn():
    engine = _game()
    _cast_glimpse(engine)
    p1 = engine.state.player_by_id("p1")
    _end_step(engine)
    engine.resolve_until_stable()
    spawns = [o for o in engine.state.battlefield if o.name == "Eldrazi Spawn" and o.controller_id == "p1"]
    assert len(spawns) == 3
    assert (spawns[0].power, spawns[0].toughness) == (0, 1)
    assert len([o for o in p1.graveyard if o.name == "Forest"]) == 3
