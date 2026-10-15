"""Gift of Immortality returns a creature after it dies."""

from __future__ import annotations

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _gift_card():
    return Card(id="gi", name="Gift of Immortality", type_line="Enchantment — Aura",
                oracle_text=("Enchant creature\nWhen enchanted creature dies, return "
                             "that card to the battlefield under its owner's control. "
                             "Return this card to the battlefield attached to that "
                             "creature at the beginning of the next end step."))


def test_registered_and_binds():
    assert is_registered("Gift of Immortality")
    spec = _REGISTRY["gift of immortality"]()[0]
    spec.validate()
    assert spec.trigger["event"] == "DIES"
    assert spec.trigger["condition"]["subject"] == "attached_permanent"
    assert [e.type for e in spec.effects] == ["gift_of_immortality_dies"]
    src = GameObject(_gift_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_gift_card())


def test_dying_creature_comes_back_immediately_and_aura_at_end_step():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    creature = GameObject(Card(id="c", name="Doomed Dissenter",
                               type_line="Creature — Human", is_creature=True,
                               power=1, toughness=1),
                          owner_id="p1", zone=Zone.BATTLEFIELD)
    creature.controller_id = "p1"
    eng.state.add_to_battlefield(creature)

    gift = GameObject(_gift_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    gift.controller_id = "p1"
    gift.attached_to = creature.instance_id
    eng.state.add_to_battlefield(gift)
    bind_from_catalogue(gift)
    eng.recompute_continuous_effects()

    eng.rules.destroy(creature)
    eng.resolve_until_stable()

    # the creature card is back on the battlefield (a fresh object with the
    # same underlying card), under its owner's control
    back = [o for o in eng.state.battlefield
            if o.card.name == "Doomed Dissenter" and o.controller_id == "p1"]
    assert len(back) == 1
    # the Aura is still in the graveyard until the end step
    assert gift.zone == Zone.GRAVEYARD

    # run to end step -> the delayed trigger returns the Aura
    eng.advance_to_phase("end") if hasattr(eng, "advance_to_phase") else None
    # generic: step through until an END step processes the delayed trigger
    for _ in range(40):
        eng.advance_step()
        eng.resolve_until_stable()
        if gift.zone == Zone.BATTLEFIELD:
            break
    assert gift.zone == Zone.BATTLEFIELD
    assert gift.attached_to == back[0].instance_id


def _gift_on_host(owner="p1", controller="p1"):
    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0,
    )
    host = GameObject(Card(id="host", name="Gift host", type_line="Creature",
                           is_creature=True, power=2, toughness=2), owner, Zone.BATTLEFIELD)
    host.controller_id = controller
    engine.state.add_to_battlefield(host)
    aura = GameObject(_gift_card(), "p1", Zone.BATTLEFIELD)
    aura.controller_id = "p1"
    aura.attached_to = host.instance_id
    engine.state.add_to_battlefield(aura)
    bind_from_catalogue(aura)
    engine.recompute_continuous_effects()
    return engine, host, aura


def _next_end(engine):
    # Deliver the real delayed trigger without advancing unrelated empty-library draws.
    engine._fire_delayed_triggers("end")
    engine.resolve_until_stable()


def _aura_entries(engine, aura):
    from mtg_analyzer.models.game.events import EventType
    return [event for event in engine.state.event_log
            if event.type == EventType.ENTERS_BATTLEFIELD
            and event.get("instance_id") == aura.instance_id]


def test_gift_does_not_find_host_after_another_graveyard_visit():
    engine, host, aura = _gift_on_host()
    engine.rules.destroy(host)
    engine.rules.check_state_based_actions()
    engine.rules.put_triggers_on_stack()
    original = host.zone_incarnation
    engine.rules.return_from_graveyard(host, "hand")
    engine.rules.discard_specific(host)
    assert host.zone_incarnation > original
    engine.resolve_until_stable()
    assert host.zone == Zone.GRAVEYARD
    _next_end(engine)
    assert aura.zone == Zone.GRAVEYARD
    assert not _aura_entries(engine, aura)


def test_gift_does_not_find_aura_after_another_graveyard_visit():
    engine, host, aura = _gift_on_host()
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    original = aura.zone_incarnation
    engine.rules.return_from_graveyard(aura, "hand")
    engine.rules.discard_specific(aura)
    assert aura.zone_incarnation > original
    _next_end(engine)
    assert aura.zone == Zone.GRAVEYARD
    assert not _aura_entries(engine, aura)


def test_gift_does_not_attach_to_blinked_returned_host():
    engine, host, aura = _gift_on_host()
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    original = host.zone_incarnation
    engine.rules.blink(host)
    assert host.zone == Zone.BATTLEFIELD and host.zone_incarnation > original
    _next_end(engine)
    assert aura.zone == Zone.GRAVEYARD
    assert aura.attached_to is None
    assert not _aura_entries(engine, aura)


def test_gift_without_returned_host_stays_in_graveyard_without_entry():
    engine, host, aura = _gift_on_host()
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    engine.rules.exile(host)
    _next_end(engine)
    assert aura.zone == Zone.GRAVEYARD
    assert not _aura_entries(engine, aura)


def test_gift_cannot_enter_attached_to_protected_host():
    engine, host, aura = _gift_on_host()
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    host.temp_protections.add("enchantments")
    assert not engine.rules._attachment_legal(aura, host, check_control=False)
    _next_end(engine)
    assert aura.zone == Zone.GRAVEYARD
    assert not _aura_entries(engine, aura)


def test_gift_returns_under_owner_control_and_is_attached_before_entry():
    from mtg_analyzer.models.game.events import EventType
    engine, host, aura = _gift_on_host(owner="p2", controller="p1")
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    assert host.zone == Zone.BATTLEFIELD and host.controller_id == "p2"
    observations = []
    engine.state._subscribers.append(
        lambda event: observations.append(aura.attached_to)
        if event.type == EventType.ENTERS_BATTLEFIELD
        and event.get("instance_id") == aura.instance_id else None
    )
    _next_end(engine)
    assert aura.zone == Zone.BATTLEFIELD and aura.controller_id == aura.owner_id == "p1"
    assert aura.attached_to == host.instance_id
    assert observations == [host.instance_id]
    _next_end(engine)
    assert len(observations) == 1


def test_gift_remembers_original_aura_visit_before_death_trigger_resolves():
    engine, host, aura = _gift_on_host()
    engine.rules.destroy(host)
    engine.rules.check_state_based_actions()
    engine.rules.put_triggers_on_stack()
    original = aura.zone_incarnation
    engine.rules.return_from_graveyard(aura, "hand")
    engine.rules.discard_specific(aura)
    assert aura.zone_incarnation > original
    engine.resolve_until_stable()
    assert host.zone == Zone.BATTLEFIELD
    _next_end(engine)
    assert aura.zone == Zone.GRAVEYARD
    assert not _aura_entries(engine, aura)


def test_gift_delayed_return_resolves_objects_from_restored_state():
    engine, host, aura = _gift_on_host()
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    restored = GameEngine(engine.state.clone())
    restored_host = restored.state.find_object(host.instance_id)
    restored_aura = restored.state.find_object(aura.instance_id)
    assert restored_host is not host and restored_aura is not aura
    _next_end(restored)
    assert restored_aura.zone == Zone.BATTLEFIELD
    assert restored_aura.attached_to == restored_host.instance_id
    assert aura.zone == Zone.GRAVEYARD
