"""Glimmer Lens (hand-authored)."""

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game
from tests.support.catalogue import battlefield_object

NAME = "Glimmer Lens"


def _attack_setup(attackers_names):
    engine = _game()
    lens = _card(engine, NAME, zone=Zone.BATTLEFIELD)
    knight = battlefield_object(engine, "p1", "Knight", "Creature — Knight", is_creature=True, power=2, toughness=2)
    bear = battlefield_object(engine, "p1", "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    knight.summoning_sick = bear.summoning_sick = False
    lens.attached_to = knight.instance_id
    player = engine.state.player_by_id("p1")
    chosen = [{"Knight": knight, "Bear": bear}[n] for n in attackers_names]
    engine.state.current_phase = "combat"
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(player, chosen)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    return engine, player


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first][:2] == ["triggered", "triggered"]


def test_equipped_creature_with_another_attacker_draws_a_card():
    engine, player = _attack_setup(["Knight", "Bear"])
    assert len(player.hand) == 1


def test_equipped_creature_attacking_alone_draws_nothing():
    engine, player = _attack_setup(["Knight"])
    assert len(player.hand) == 0


def test_another_creature_attacking_without_the_equipped_one_draws_nothing():
    engine, player = _attack_setup(["Bear"])
    assert len(player.hand) == 0
