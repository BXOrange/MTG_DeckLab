"""Geralf, the Fleshwright (hand-authored)."""

from tests.support.card_cache import get_cached_card

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game
from tests.support.catalogue import battlefield_object

NAME = "Geralf, the Fleshwright"


def _tokens(engine, name):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == "p1"]


def _enter(engine, obj):
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
                                      controller_id=obj.controller_id))
    engine.resolve_until_stable()


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first][:2] == ["triggered", "triggered"]


def test_second_spell_on_your_turn_makes_a_zombie_rogue_but_the_first_does_not():
    engine = _game()
    _card(engine, NAME, zone=Zone.BATTLEFIELD)
    caster = engine.state.player_by_id("p1")
    opponent = engine.state.player_by_id("p2")
    bolt = get_cached_card("Lightning Bolt")
    caster.mana_pool.add("R", 2)
    first = _card(engine, "Lightning Bolt", zone=Zone.HAND)
    second = _card(engine, "Lightning Bolt", zone=Zone.HAND)
    engine.rules.cast_spell(caster, first, targets=[opponent])
    engine.resolve_until_stable()
    assert _tokens(engine, "Zombie Rogue") == []
    engine.rules.cast_spell(caster, second, targets=[opponent])
    engine.resolve_until_stable()
    tokens = _tokens(engine, "Zombie Rogue")
    assert len(tokens) == 1 and (tokens[0].power, tokens[0].toughness) == (2, 2)
    assert bolt is not None


def test_zombie_entering_gets_one_counter_per_other_zombie_entered_this_turn():
    engine = _game()
    _card(engine, NAME, zone=Zone.BATTLEFIELD)
    first = battlefield_object(engine, "p1", "Zed", "Creature — Zombie", is_creature=True, power=2, toughness=2)
    second = battlefield_object(engine, "p1", "Zoe", "Creature — Zombie", is_creature=True, power=2, toughness=2)
    _enter(engine, first)   # no other Zombie entered yet: no counter
    _enter(engine, second)  # one other Zombie entered this turn: one counter
    assert first.counters.get("+1/+1", 0) == 0
    assert second.counters.get("+1/+1", 0) == 1
