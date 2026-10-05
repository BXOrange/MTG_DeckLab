"""RULE 400.7 "new object" identity — `RulesEngine.blink`/`return_from_graveyard`.

An object that moves from one zone to another and back becomes a *new*
object: counters, attachment linkage, control-change/copy state, cast-time
flags, the one-time renown flag, and every "until end of turn" grant are not
retained, and it re-enters with a fresh `ENTERS_BATTLEFIELD` occurrence
(ETB triggers refire, summoning sickness resets).

Before this fix, `blink()` reused the same `GameObject` without resetting
`temp_power`/`temp_toughness`/`temp_keywords` (an "until end of turn" pump
survived a flicker) and `return_from_graveyard()` never cleared counters at
all (a creature that died with +1/+1 counters would bring them back via
Reanimate/Regrowth) or a stale `controller_id` from a control-change effect
that applied before it left play. `GameObject.reset_as_new_object` is the
single, shared fix point both callers now use.

`instance_id` is deliberately left unchanged (documented on
`reset_as_new_object` itself) — this suite includes a positive check that a
self-referential trigger keeps firing correctly for the new incarnation,
proving that decision doesn't regress "self" scoping.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import StaticAbility
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.game.rules_engine import RulesEngine


def _bear(name="Bear", power=2, toughness=2, oracle_text=""):
    return Card(
        id=name, name=name, type_line="Creature — Bear",
        is_creature=True, power=power, toughness=toughness, oracle_text=oracle_text,
    )


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _bf(state, card, controller="p1", tapped=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = tapped
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# -- blink() ------------------------------------------------------------------


def test_blink_clears_until_end_of_turn_pump_and_keyword():
    engine, state, p1, p2 = _rules()
    obj = _bf(state, _bear("Firemaw"))
    # Simulate a resolved "until end of turn" pump/keyword-grant effect.
    obj.temp_power = 3
    obj.temp_toughness = 1
    obj.temp_keywords = {"flying"}
    obj.temp_effects = [{"source": "Giant Growth", "power": 3, "toughness": 3, "keywords": []}]
    obj.temp_unblockable = True
    obj.temp_protections = {"R"}

    engine.blink(obj)

    assert obj.temp_power == 0
    assert obj.temp_toughness == 0
    assert obj.temp_keywords == set()
    assert obj.temp_effects == []
    assert obj.temp_unblockable is False
    assert obj.temp_protections == set()


def test_blink_clears_counters_and_resets_summoning_sickness():
    engine, state, p1, p2 = _rules()
    obj = _bf(state, _bear("Veteran"))
    obj.add_counters("+1/+1", 3)
    obj.summoning_sick = False

    engine.blink(obj)

    assert obj.counters == {}
    assert obj.summoning_sick is True
    assert obj in state.battlefield


def test_blink_resets_the_one_time_renown_flag():
    engine, state, p1, p2 = _rules()
    obj = _bf(state, _bear("Hero of Bladehold"))
    obj.renowned = True

    engine.blink(obj)

    assert obj.renowned is False


def test_blink_restores_owner_control_after_a_control_change():
    engine, state, p1, p2 = _rules()
    obj = _bf(state, _bear("Stolen Bear"), controller="p1")
    obj.controller_id = "p2"  # simulate an active "gain control" effect

    engine.blink(obj)

    assert obj.controller_id == "p1"


def test_blink_with_explicit_controller_returns_under_that_player_not_the_owner():
    # Restoration Angel-shaped: "return that card to the battlefield under
    # your control" — the caster, not necessarily the owner.
    engine, state, p1, p2 = _rules()
    obj = _bf(state, _bear("Borrowed Bear"), controller="p1")
    obj.owner_id = "p1"

    engine.blink(obj, controller=state.player_by_id("p2"))

    assert obj.controller_id == "p2"
    assert obj.owner_id == "p1"  # ownership never changes, only control
    assert obj in state.battlefield


def test_blink_without_controller_still_defaults_to_the_owner():
    engine, state, p1, p2 = _rules()
    obj = _bf(state, _bear("Bear"), controller="p1")

    engine.blink(obj)

    assert obj.controller_id == "p1"


def test_blink_keeps_instance_id_stable_and_self_trigger_still_fires():
    # `instance_id` is deliberately NOT churned — a self-referential trigger
    # bound at object creation (`effect_binder._subject_condition`'s "self"
    # closure) snapshots it, so this proves blink doesn't silently break
    # "whenever ~ attacks" on the very card it ran for.
    engine, state, p1, p2 = _rules()
    obj = _bf(
        state,
        _bear("Bladed Trigger", oracle_text="Whenever ~ attacks, draw a card."),
    )
    before_id = obj.instance_id

    engine.blink(obj)

    assert obj.instance_id == before_id
    from mtg_analyzer.models.game.events import EventType, GameEvent

    state.fire_event(
        GameEvent(
            EventType.ATTACKS, attacker=obj.name, player_id="p1",
            instance_id=obj.instance_id, object_types=sorted(obj.type_words),
        )
    )
    placed = engine.put_triggers_on_stack()
    assert placed == 1  # the self-trigger matched its own (still-)instance_id


def test_blink_drops_attachments_from_the_blinked_host():
    engine, state, p1, p2 = _rules()
    host = _bf(state, _bear("Host"))
    aura = _bf(state, Card(id="Pump Aura", name="Pump Aura", type_line="Enchantment — Aura"))
    aura.attached_to = host.instance_id
    StaticAbility("pt_mod", affects="attached_permanent", params={"power": 2, "toughness": 2}, source=aura)

    engine.blink(host)

    # A fresh host has no attachment linkage of its own.
    assert host.attached_to is None
    # The Aura fell off (RULE 704.5m) — Auras go to the graveyard when their
    # host leaves, so it's no longer pointed at the (new) host object.
    assert aura not in state.battlefield or aura.attached_to != host.instance_id


def test_blink_fires_a_fresh_enters_battlefield_trigger():
    engine, state, p1, p2 = _rules()
    obj = _bf(
        state,
        _bear("Flicker Bear", oracle_text="When ~ enters the battlefield, draw a card."),
    )
    p1.library.append(GameObject(_bear("Library Bear"), owner_id="p1", zone=Zone.LIBRARY))

    engine.blink(obj)

    placed = engine.put_triggers_on_stack()
    assert placed == 1
    assert len(state.stack) == 1
    engine.resolve_top_of_stack()
    assert len(p1.hand) == 1


# -- return_from_graveyard() ---------------------------------------------------


def test_reanimate_does_not_bring_back_counters_from_a_prior_death():
    engine, state, p1, p2 = _rules()
    dead = GameObject(_bear("Fallen Giant", power=5, toughness=5), owner_id="p1", zone=Zone.GRAVEYARD)
    dead.add_counters("+1/+1", 2)  # died with counters still on it
    p1.add_to_zone(dead, Zone.GRAVEYARD)

    engine.return_from_graveyard(dead, "battlefield")

    assert dead.counters == {}
    assert dead in state.battlefield


def test_reanimate_defaults_to_owner_control_even_without_an_explicit_controller():
    engine, state, p1, p2 = _rules()
    dead = GameObject(_bear("Traitor"), owner_id="p1", zone=Zone.GRAVEYARD)
    dead.controller_id = "p2"  # stale from a control effect active before it died
    p1.add_to_zone(dead, Zone.GRAVEYARD)

    engine.return_from_graveyard(dead, "battlefield")

    assert dead.controller_id == "p1"


def test_return_from_graveyard_under_explicit_controller_still_resets_counters():
    engine, state, p1, p2 = _rules()
    dead = GameObject(_bear("Reanimator Target"), owner_id="p1", zone=Zone.GRAVEYARD)
    dead.add_counters("+1/+1", 1)
    p1.add_to_zone(dead, Zone.GRAVEYARD)

    engine.return_from_graveyard(dead, "battlefield", controller_id="p2")

    assert dead.counters == {}
    assert dead.controller_id == "p2"
