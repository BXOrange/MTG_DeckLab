"""Tests for BACKLOG ENG-9, ENG-11, ENG-13, ENG-14.

ENG-9 (RULE 613.8 dependency ordering, `continuous._order_control_effects`)
is re-verified rather than changed: no selector anywhere in the P/T layers
(7a-7e) reads another object's *derived* characteristics — the only
selectors that do (`group_selector_objects`'s ``min_power``/``max_power``/
``power_lt_selector``/``power_gt_selector``) are consumed exclusively by
`combat_restriction`/``goaded`` statics, both stamped strictly after the
layer-7 pass finishes (`_apply_post_layer_combat_restrictions_and_goad`) —
downstream consumers of finished layer-7 output, not a same-sublayer
ordering dependency. `test_power_threshold_selector_sees_same_pass_anthem`
below pins that down as a regression: an anthem and a goad/restriction
qualifier that both apply this same recompute must still compose correctly
without `_order_control_effects` needing to know about layer 7 at all.

ENG-11 (`continuous._granted_trigger_condition` fails closed when a firing
event doesn't carry the identity key it expects, instead of the previous
"no key -> don't filter" default that would have let every object under a
shared grant react to an event about none of them).

ENG-13 (a per-firing dynamic reference for a *granted* ability, via
`GameContext.trigger_event` — already general enough for an ordinary
printed trigger's own "it" pronoun (`ReturnSharedTypePermanentEffect`), now
demonstrated for a *granted* ability too): Kaldra Compleat's "exile that
creature" (`ExileTriggerDamagedCreatureEffect`) and Sigarda's Aid's "attach
it" (`AttachTriggeringPermanentEffect`).

ENG-14 (`effects._defending_player_of` falls back to the object a source is
attached to when the source itself isn't the one attacking): Simian Sling
reconfigured onto a different attacking creature.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.models.player import Player


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def creature(name="Bear", power=2, toughness=2, **kw):
    return Card(
        id=name, name=name, type_line=kw.pop("type_line", "Creature — Bear"),
        is_creature=True, power=power, toughness=toughness, **kw,
    )


def make_engine(*player_ids):
    libs = [(pid, pid, [land()]) for pid in player_ids]
    return GameEngine.new_game(libs, starting_life=20, starting_hand=0)


def put(state, card, controller="p1", bind=True):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    if bind:
        bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _to_declare_attackers(eng):
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"


# ---------------------------------------------------------------------------
# ENG-9: re-verify the RULE 613.8 invariant still holds
# ---------------------------------------------------------------------------


def test_power_threshold_selector_sees_same_pass_anthem():
    """A goad/combat-restriction power threshold must read the *derived*
    (post-anthem) power of the objects it filters, proving these selectors
    are downstream of the whole layer-7 pass rather than interleaved with
    it — the fact ENG-9's "only layer 2 needs RULE 613.8 ordering" claim
    depends on.
    """
    state = GameState(players=[Player(id="p1", life=20), Player(id="p2", life=20)])
    small = GameObject(creature("Small", power=1, toughness=1), owner_id="p2", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(small)

    anthem_source = GameObject(
        Card(id="Anthem", name="Anthem", type_line="Enchantment", is_creature=False),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(anthem_source)
    from mtg_analyzer.game.effects.core import StaticAbility

    anthem_source.static_effects.append(
        StaticAbility(
            layer="pt_mod", affects="creatures_you_control",
            params={"power": 3, "toughness": 3}, source=anthem_source,
        )
    )
    goad_source = GameObject(
        Card(id="Goader", name="Goader", type_line="Enchantment", is_creature=False),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(goad_source)
    goad_source.static_effects.append(
        StaticAbility(
            layer="goaded", affects="creatures_opponents_control",
            params={"power_gt_selector": "source_power"}, source=goad_source,
        )
    )
    goad_source._derived_power = 2  # the threshold the selector reads

    continuous.recompute(state)

    # Without the same-pass anthem, Small (power 1) would not be goaded
    # (1 is not > 2). *With* it (1 + 3 = 4 > 2), it must be.
    assert small.power == 4
    from mtg_analyzer.game import combat

    assert combat.is_goaded(small)


# ---------------------------------------------------------------------------
# ENG-11: granted-trigger identity scoping fails closed
# ---------------------------------------------------------------------------


def test_granted_trigger_condition_fails_closed_on_unregistered_event_shape():
    """A `trigger_event` whose payload doesn't carry the key
    `_GRANTED_EVENT_KEYS` maps it to (a hypothetical future registration
    gap) must not fire for an object it isn't about — the fail-open reading
    would let *every* grantee react to a single event.
    """
    state = GameState(players=[Player(id="p1", life=20)])
    target = GameObject(creature("Elf A"), owner_id="p1", zone=Zone.BATTLEFIELD)
    other = GameObject(creature("Elf B"), owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(target)
    state.add_to_battlefield(other)

    condition = continuous._granted_trigger_condition(target, False, "SOME_UNMAPPED_EVENT")

    class _Ctx:
        state = None

    event = GameEvent("SOME_UNMAPPED_EVENT")  # carries no `instance_id` at all
    assert condition(event, _Ctx()) is False


def test_granted_trigger_condition_still_scopes_by_identity():
    """Unaffected: an event that *does* carry the expected key still only
    matches its own grantee (Dionus, Elvish Archdruid's shape)."""
    state = GameState(players=[Player(id="p1", life=20)])
    target = GameObject(creature("Elf A"), owner_id="p1", zone=Zone.BATTLEFIELD)
    other = GameObject(creature("Elf B"), owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(target)
    state.add_to_battlefield(other)

    condition = continuous._granted_trigger_condition(target, False, EventType.TAPPED)

    class _Ctx:
        state = None

    for_target = GameEvent(EventType.TAPPED, instance_id=target.instance_id)
    for_other = GameEvent(EventType.TAPPED, instance_id=other.instance_id)
    assert condition(for_target, _Ctx()) is True
    assert condition(for_other, _Ctx()) is False


def test_granted_trigger_condition_step_begin_still_has_no_subject():
    """The one legitimate no-subject case (RULE 500.7 phase grants) is
    unaffected by the fail-closed default."""
    state = GameState(players=[Player(id="p1", life=20), Player(id="p2", life=20)])
    state.active_player_index = 0
    target = GameObject(creature("Host"), owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(target)

    condition = continuous._granted_trigger_condition(
        target, False, EventType.STEP_BEGIN, {"step": "upkeep"}, "you",
    )

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.state = state
    event = GameEvent(EventType.STEP_BEGIN, step="upkeep")  # no object subject at all
    assert condition(event, ctx) is True


# ---------------------------------------------------------------------------
# ENG-13: per-firing dynamic reference for a granted/printed ability
# ---------------------------------------------------------------------------


def _equipment(name, cost="{7}", attach="equip"):
    # `_attachment_legal` (game/rules/casting_mixin.py) only recognizes an
    # Equipment/Reconfigure permanent via `GameObject.parametric_keywords`,
    # populated from the card's own printed keyword/oracle text at bind
    # time (`parse_keywords`) — a bare type line isn't enough, or a direct
    # `attached_to=` assignment gets unwound as illegal the moment an SBA
    # pass revalidates it (RULE 704.5m/n).
    label = "Equip" if attach == "equip" else "Reconfigure"
    return Card(
        id=name, name=name, type_line="Legendary Artifact — Equipment",
        mana_cost_string=cost, keywords=[label],
        oracle_text=f"{label} {cost}",
    )


def test_kaldra_compleat_exiles_the_damaged_creature():
    eng = make_engine("p1", "p2")
    state = eng.state
    kaldra = put(state, _equipment("Kaldra Compleat"))
    wearer = put(state, creature("Wearer", power=1, toughness=1))
    victim = put(state, creature("Victim", power=1, toughness=1), controller="p2")
    kaldra.attached_to = wearer.instance_id
    eng.recompute_continuous_effects()

    eng.rules.deal_damage(victim, 5, source=wearer, combat=True)
    eng.resolve_until_stable()

    assert victim not in state.battlefield
    p2 = state.player_by_id("p2")
    assert any(o.instance_id == victim.instance_id for o in p2.exile)


def test_kaldra_compleat_does_not_exile_on_player_damage():
    """Only "a creature" is exiled — combat damage to a player must not
    misfire the same effect (`event.get("is_player")` guard)."""
    eng = make_engine("p1", "p2")
    state = eng.state
    kaldra = put(state, _equipment("Kaldra Compleat"))
    wearer = put(state, creature("Wearer", power=1, toughness=1))
    kaldra.attached_to = wearer.instance_id
    eng.recompute_continuous_effects()

    p2 = state.player_by_id("p2")
    life_before = p2.life
    eng.rules.deal_damage(p2, 5, source=wearer, combat=True)
    eng.resolve_until_stable()

    assert p2.life == life_before - 5
    assert len(state.battlefield) == 2  # nothing got exiled


def test_sigardas_aid_attaches_the_entering_equipment_to_chosen_target():
    eng = make_engine("p1", "p2")
    state = eng.state
    put(state, Card(id="Sigarda's Aid", name="Sigarda's Aid", type_line="Enchantment"))
    creature_obj = put(state, creature("Knight", power=2, toughness=2))

    equip_card = _equipment("Loyal Sidearm", cost="{1}")
    equip_obj = GameObject(equip_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(equip_obj)
    state.add_to_battlefield(equip_obj)
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD,
            instance_id=equip_obj.instance_id,
            controller_id="p1",
            object_types=["artifact"],
            subtypes=["equipment"],
            is_token=False,
        )
    )
    eng.resolve_until_stable()

    # The "you may" target choice: answer it with the creature.
    choice = state.pending_choice
    assert choice is not None and choice.get("kind") == "trigger_target"
    eng.rules.resolve_trigger_target_choice(str(creature_obj.instance_id))
    eng.resolve_until_stable()

    assert equip_obj.attached_to == creature_obj.instance_id


# ---------------------------------------------------------------------------
# ENG-14: Simian Sling reconfigured onto a different attacking creature
# ---------------------------------------------------------------------------


def test_simian_sling_hits_defending_player_when_reconfigured_elsewhere():
    eng = make_engine("p1", "p2")
    state = eng.state
    sling = put(state, _equipment("Simian Sling", cost="{2}", attach="reconfigure"))
    attacker = put(state, creature("Attacker", power=2, toughness=2))
    blocker = put(state, creature("Blocker", power=1, toughness=1), controller="p2")
    sling.attached_to = attacker.instance_id
    eng.recompute_continuous_effects()

    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, [attacker])
    state.current_step = "declare_blockers"
    eng.declare_blockers(state.player_by_id("p2"), [(blocker, attacker)])
    eng.resolve_until_stable()

    p2 = state.player_by_id("p2")
    assert p2.life == 19  # 20 - 1 from Simian Sling's granted trigger
