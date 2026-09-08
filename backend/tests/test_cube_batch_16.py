"""cEDH staples cube — batch 16: the reflexive per-firing "that object"
trigger primitive (RULE 603.3d).

New core capability: a `TriggeredAbility` may be ``reflexive`` — its single
targeting effect acts on *the exact object that fired the triggering event*
(the "counter that spell" / "destroy that land" shape), not a freely chosen
target. `RulesEngine._place_triggers` resolves the target from the event's
``instance_id`` at placement time and bakes it in, opening no
`trigger_target` choice; a vanished object drops the trigger (RULE 603.3c).
This is the generic form of the per-firing reference that `check_ward`/
`check_rampage` previously hand-built card-by-card, and the piece
Narset's Reversal (batch 17's spell-copy) will reuse.

No cube card is blocked *solely* on this primitive — Lavinia/Boromir also
need mana-spent tracking + a cast-prohibition, Price of Glory a per-tap mana
event (batch 20), Hope of Ghirapur damage-history tracking — so nothing is
registered here yet; these tests exercise the primitive directly through the
binder + engine so it's proven before those companion gaps land.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import StackItem
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec


def _engine() -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])],
        starting_life=40,
        starting_hand=0,
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _source_with_reflexive(eng, effect_spec: EffectSpec, event: str, condition=None):
    """A p1 battlefield permanent carrying one reflexive triggered ability."""
    src = GameObject(
        Card(id="Warden", name="Warden", type_line="Creature — Wizard",
             is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.summoning_sick = False
    trigger = {"event": event, "reflexive": True}
    if condition is not None:
        trigger["condition"] = condition
    ability = bind_ability(
        AbilitySpec("triggered", [effect_spec], trigger=trigger), src
    )
    src.triggered_abilities.append(ability)
    eng.state.add_to_battlefield(src)
    return src


def _push_spell(eng, player, card) -> GameObject:
    obj = GameObject(card, owner_id=player.id, zone=Zone.STACK)
    obj.spell_effects = []
    item = StackItem(kind="spell", controller_id=player.id, obj=obj,
                     description=card.name, effects=[])
    eng.state.stack.append(item)
    return obj


# ---------------------------------------------------------------------------
# 1. "Counter that spell" — reflexive on SPELL_CAST
# ---------------------------------------------------------------------------


def test_reflexive_counter_hits_the_spell_that_fired_the_trigger():
    eng = _engine()
    state = eng.state
    p2 = state.player_by_id("p2")
    _source_with_reflexive(eng, EffectSpec("counter", {}), EventType.SPELL_CAST)

    spell_card = Card(id="Bolt", name="Bolt", type_line="Instant")
    spell = _push_spell(eng, p2, spell_card)

    # Fire the cast exactly as `RulesEngine._cast` does (carries instance_id).
    state.fire_event(GameEvent(
        EventType.SPELL_CAST, player_id="p2", card_id="Bolt", spell="Bolt",
        instance_id=spell.instance_id, object_types=sorted(spell.type_words),
    ))
    eng.rules.put_triggers_on_stack()
    # No target choice — the spell is baked in reflexively.
    assert state.pending_choice is None
    eng.resolve_until_stable()

    assert all(getattr(i, "obj", None) is not spell for i in state.stack), \
        "the triggering spell should have been countered off the stack"
    assert spell in p2.graveyard


def test_reflexive_counter_drops_when_the_spell_already_left_the_stack():
    """RULE 603.3c: if the object that fired the event is gone by placement
    time, the reflexive trigger has no legal target and is never placed."""
    eng = _engine()
    state = eng.state
    p2 = state.player_by_id("p2")
    _source_with_reflexive(eng, EffectSpec("counter", {}), EventType.SPELL_CAST)

    # Fire a cast event for an instance_id that isn't anywhere in the game.
    state.fire_event(GameEvent(
        EventType.SPELL_CAST, player_id="p2", card_id="Ghost", spell="Ghost",
        instance_id=999999, object_types=["instant"],
    ))
    eng.rules.put_triggers_on_stack()

    # The trigger fired (unconditional) but its target vanished, so it is
    # dropped rather than placed — nothing reaches the stack.
    assert state.pending_choice is None
    assert len(state.stack) == 0


# ---------------------------------------------------------------------------
# 2. "Destroy that permanent" — reflexive on ENTERS_BATTLEFIELD
# ---------------------------------------------------------------------------


def test_reflexive_destroy_hits_the_permanent_that_entered():
    eng = _engine()
    state = eng.state
    p2 = state.player_by_id("p2")
    _source_with_reflexive(
        eng, EffectSpec("destroy", {"target_kind": "creature"}),
        EventType.ENTERS_BATTLEFIELD,
        condition={"subject": "group", "type": "creature", "controller": "not_you"},
    )

    intruder = GameObject(
        Card(id="Intruder", name="Intruder", type_line="Creature — Goblin",
             is_creature=True, power=2, toughness=2),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(intruder)
    state.add_to_battlefield(intruder)
    # ENTERS_BATTLEFIELD is fired by the resolve path, not add_to_battlefield;
    # fire it here with the same payload to isolate the reflexive mechanism.
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p2", card_id="Intruder",
        object=intruder.name, instance_id=intruder.instance_id,
        object_types=sorted(intruder.type_words),
    ))

    eng.rules.put_triggers_on_stack()
    assert state.pending_choice is None
    eng.resolve_until_stable()
    eng.rules.check_state_based_actions()

    assert intruder not in state.battlefield
    assert intruder in p2.graveyard


def test_reflexive_destroy_does_not_fire_for_your_own_permanent():
    eng = _engine()
    state = eng.state
    _source_with_reflexive(
        eng, EffectSpec("destroy", {"target_kind": "creature"}),
        EventType.ENTERS_BATTLEFIELD,
        condition={"subject": "group", "type": "creature", "controller": "not_you"},
    )

    friendly = GameObject(
        Card(id="Friend", name="Friend", type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(friendly)
    state.add_to_battlefield(friendly)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", card_id="Friend",
        object=friendly.name, instance_id=friendly.instance_id,
        object_types=sorted(friendly.type_words),
    ))

    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0
    assert friendly in state.battlefield
