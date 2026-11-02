"""Secret Tunnel (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Secret Tunnel'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first][:2] == ['static', 'activated']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.static_effects


def _setup(*type_lines):
    from tests.support.catalogue import battlefield_object

    engine = _game()
    tunnel = _card(engine, NAME)
    tunnel.summoning_sick = False
    creatures = [
        battlefield_object(engine, "p1", f"C{n}", tl, power=1, toughness=1, is_creature=True)
        for n, tl in enumerate(type_lines)
    ]
    engine.state.player_by_id("p1").mana_pool.add("C", 4)
    engine.state.current_step = "main1"
    return engine, tunnel, creatures


def _tunnel_index(tunnel):
    return next(i for i, a in enumerate(tunnel.activated_abilities) if not getattr(a, "mana_ability", False)
                and any(type(e).__name__ == "UnblockableEffect" for e in a.effects))


def test_end_to_end():
    # RULE 205.3m: two Elves share a type, so both become unblockable.
    engine, tunnel, (a, b) = _setup("Creature — Elf Warrior", "Creature — Elf Druid")
    engine.activate_ability(engine.state.player_by_id("p1"), tunnel, _tunnel_index(tunnel), targets=[a, b])
    engine.resolve_until_stable()
    assert a.temp_unblockable and b.temp_unblockable


def test_creatures_sharing_no_type_are_refused():
    engine, tunnel, (a, b) = _setup("Creature — Elf Warrior", "Creature — Goblin Shaman")
    with pytest.raises(ValueError):
        engine.activate_ability(engine.state.player_by_id("p1"), tunnel, _tunnel_index(tunnel), targets=[a, b])
    assert not a.temp_unblockable and not b.temp_unblockable


def test_changeling_shares_a_type_with_anything():
    # RULE 702.73a: a changeling is every creature type.
    engine, tunnel, (a, b) = _setup("Creature — Shapeshifter Changeling", "Creature — Goblin Shaman")
    engine.activate_ability(engine.state.player_by_id("p1"), tunnel, _tunnel_index(tunnel), targets=[a, b])
    engine.resolve_until_stable()
    assert a.temp_unblockable and b.temp_unblockable
