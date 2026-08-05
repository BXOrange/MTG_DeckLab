"""Effect type hierarchy + registry (RULE 611/603/614/602, docs/07 PART 2/4/6).

docs/07 is emphatic: "Cards don't just do things. Cards CHANGE THE
RULES." So effects are first-class objects the engine consults, not
hardcoded branches. There are four kinds (docs/07 PART 2):

* ``StaticEffect``      — continuous modifiers (RULE 611), incl. rule
                          overrides like "skip your untap step".
* ``TriggeredAbility``  — fire on an event, go on the stack (RULE 603).
* ``ReplacementEffect`` — rewrite an event before it happens (RULE 614).
* ``ActivatedAbility``  — a cost the controller may pay for an effect
                          (RULE 602).

``WinConditionEffect`` is the special "you can't lose"-style override
(docs/07 PART 9). Concrete one-shot effects (deal damage, draw, …) plus
an `EffectRegistry` implement the hybrid class+registry design docs/07
PART 4 recommends: predefined classes for type-safety, a registry so new
effects need no engine change.

Effects act on the game through a `GameContext` facade rather than
touching `GameState` directly, so the primitive operations (draw, deal
damage, destroy) stay defined in one place (the rules engine) and pick up
their own replacement/trigger consequences.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

from ..models import card_query
from ..models.events import EventType, GameEvent
from ..models.game_object import Zone
from ..models.mana_cost import ManaCost
from .targeting import TargetSpec

if TYPE_CHECKING:  # avoid an import cycle with rules_engine at runtime
    from ..models.game_object import GameObject
    from ..models.game_state import GameState, StackItem
    from ..models.player import Player
    from .costs import ActivationCost
    from .rules_engine import RulesEngine


class GameContext:
    """Facade an effect uses to reach the game and the engine's primitives.

    Effects call these instead of mutating `GameState` directly so that
    e.g. a draw caused by an effect runs through the same replacement /
    trigger machinery as a draw-step draw.
    """

    def __init__(self, state: "GameState", engine: "RulesEngine") -> None:
        self.state = state
        self.engine = engine
        #: RULE 603.1: the `GameEvent` that fired the triggered ability
        #: currently resolving (`StackItem.trigger_event`), or ``None``
        #: outside that window. Set by `RulesEngine.resolve_top_of_stack`
        #: around the resolution and cleared afterward, so an effect whose
        #: behaviour genuinely depends on *this* firing — the mana a
        #: permanent just produced (Kinnan, Wild Growth, Mana Web), which
        #: player cast the spell (Possibility Storm), what type it was
        #: (Cloudstone Curio) — can read it without every effect's `apply`
        #: signature growing an event parameter. The `TriggeredAbility`
        #: docstring's "bake per-firing data into freshly-built effects"
        #: pattern stays the answer whenever the *shape* of the ability
        #: varies per firing; this covers the far commoner case where only a
        #: value does.
        self.trigger_event: Optional[GameEvent] = None
        #: The targets the last *targeting* effect of this same resolution
        #: used (RULE 608.2 applies an effect list in printed order), so a
        #: clause whose subject is a pronoun pointing back at an earlier one
        #: — "target creature you control gets +1/+2 until end of turn. **It**
        #: fights target creature you don't control." (Epic Confrontation),
        #: "Choose target creature you control and target creature you don't
        #: control. … Then **those creatures** fight each other." — can
        #: resolve that referent without the two clauses being fused into one
        #: bespoke effect class per verb pair. Maintained by
        #: `_apply_effects_partitioned`, which is the single choke point every
        #: resolution (spell, wrapper ability, resumed remainder) goes
        #: through. A *non*-targeting clause in between doesn't clear it: the
        #: referent is the last thing actually chosen, not the last thing that
        #: happened.
        self.previous_targets: list[Any] = []
        #: The permanents an earlier clause of this same resolution **just
        #: created**, for a follow-up clause whose subject is "the tokens" /
        #: "that token" — "…each player creates a tapped 2/2 Bird. **The
        #: tokens** are goaded for the rest of the game." (Rendmaw).
        #:
        #: `previous_targets`' sibling and the reason it isn't enough: those
        #: objects were never *targeted*, and never existed at all when the
        #: ability was put on the stack, so no `TargetSpec` can name them.
        #: `LivingWeaponEffect`'s docstring records the same gap from the
        #: other side ("there's no vocabulary for whatever the previous
        #: effect just made") — an atomic effect class per verb pair was the
        #: only alternative. Maintained by `_apply_effects_partitioned`
        #: alongside `previous_targets`, and appended to (not replaced) by a
        #: creating effect, since "each player creates …" makes several.
        self.created_objects: list[Any] = []

    @property
    def players(self) -> list["Player"]:
        return self.state.players

    @property
    def active_player(self) -> "Player":
        return self.state.active_player

    def fire_event(self, event: GameEvent) -> GameEvent:
        return self.state.fire_event(event)

    def deal_damage(self, target: Any, amount: int, source: Optional["GameObject"] = None) -> None:
        self.engine.deal_damage(target, amount, source)

    def draw(self, player: "Player", count: int = 1) -> None:
        self.engine.draw(player, count)

    def discard(self, player: "Player", count: int = 1) -> None:
        self.engine.discard(player, count)

    def discard_choice(self, player: "Player", count: int = 1) -> None:
        self.engine.discard_choice(player, count)

    def put_hand_cards_on_top(self, player: "Player", count: int = 1) -> None:
        self.engine.put_hand_cards_on_top(player, count)

    def destroy(self, target: "GameObject", can_be_regenerated: bool = True) -> None:
        self.engine.destroy(target, can_be_regenerated=can_be_regenerated)

    def regenerate(self, target: "GameObject") -> None:
        self.engine.regenerate(target)

    def exile(self, target: "GameObject") -> None:
        self.engine.exile(target)

    def mill(self, player: "Player", count: int = 1) -> None:
        self.engine.mill(player, count)

    def lose_game(self, player: "Player", reason: str = "effect") -> None:
        self.engine._player_loses(player, reason)

    def monstrosity(self, target: "GameObject", amount: int = 1) -> bool:
        # RULE 701.37a.
        return self.engine.monstrosity(target, amount)

    def adapt(self, target: "GameObject", amount: int = 1) -> bool:
        # RULE 701.46a.
        return self.engine.adapt(target, amount)

    def goad(self, target: "GameObject", goader_id: str, permanent: bool = False) -> None:
        # RULE 701.15a; ``permanent`` is the "for the rest of the game" form.
        self.engine.goad(target, goader_id, permanent=permanent)

    def become_monarch(self, player: "Player") -> None:
        self.engine.become_monarch(player)

    def take_initiative(self, player: "Player") -> None:
        self.engine.take_initiative(player)

    def get_city_blessing(self, player: "Player") -> None:
        # RULE 702.131a-c.
        self.engine.get_city_blessing(player)

    def create_emblem(self, player: "Player", ability: dict) -> None:
        self.engine.create_emblem(player, ability)

    def venture_into_the_dungeon(self, player: "Player", dungeon: Optional[str] = None) -> None:
        # RULE 701.49; ``dungeon`` is 701.49d's "venture into [quality]".
        self.engine.venture_into_the_dungeon(player, dungeon)

    def complete_dungeon(self, player: "Player") -> None:
        # RULE 309.6/309.7.
        self.engine.complete_dungeon(player)

    def manifest(self, player: "Player", count: int = 1, kind: str = "manifest") -> None:
        # RULE 701.40a manifest / RULE 701.58a cloak.
        self.engine.manifest(player, count, kind=kind)

    def request_manifest_dread(self, player: "Player") -> None:
        # RULE 701.40a's look-at-two variant.
        self.engine.request_manifest_dread(player)

    def take_extra_turn(self, player: "Player") -> None:
        # RULE 500.7: queue an extra turn for ``player``, taken after the
        # current one (`GameEngine.begin_turn` consumes `state.extra_turns`).
        self.state.extra_turns.append(player.id)

    def set_tapped(self, target: "GameObject", tapped: bool = True) -> None:
        self.engine.set_tapped(target, tapped)

    def attach_to_target(self, source: "GameObject", target: "GameObject") -> None:
        self.engine.attach_to_target(source, target)

    def add_counters(
        self, target: "GameObject", amount: int, kind: str = "+1/+1", source: Optional["GameObject"] = None
    ) -> None:
        self.engine.add_counters(target, amount, kind, source=source)

    def add_player_counters(
        self, player: "Player", amount: int, kind: str = "poison", source: Optional["GameObject"] = None
    ) -> None:
        self.engine.add_player_counters(player, amount, kind, source=source)

    def scry(self, player: "Player", count: int = 1) -> None:
        self.engine.scry(player, count)

    def surveil(self, player: "Player", count: int = 1) -> None:
        self.engine.surveil(player, count)

    def recompute(self) -> None:
        """Re-derive continuous characteristics now (RULE 613) — used by an
        effect that changes derived P/T mid-resolution (a pump)."""
        from . import continuous  # function-scoped: avoid an import cycle

        continuous.recompute(self.state)

    def create_token(self, controller_id: str, token_card: Any, count: int = 1) -> list[Any]:
        # Returns what it made (RULE 111.5) so a caller can keep the referent
        # for a following "the tokens …" clause — see `created_objects`.
        return self.engine.create_token(controller_id, token_card, count)

    def copy_permanent(self, controller_id: str, source: "GameObject", count: int = 1) -> None:
        self.engine.copy_permanent(controller_id, source, count)

    def copy_spell(
        self,
        target: Any,
        controller_id: str,
        count: int = 1,
        new_targets: Optional[list] = None,
    ) -> None:
        self.engine.copy_spell(target, controller_id, count, new_targets)

    def make_prepared(self, obj: "GameObject") -> None:
        self.engine.make_prepared(obj)

    def put_into_graveyard(self, obj: "GameObject") -> None:
        """RULE 701.16c: sacrifice isn't destruction — a permanent goes
        straight to the graveyard, never through a regeneration shield."""
        self.engine.put_into_graveyard(obj)

    def become_copy(
        self,
        obj: "GameObject",
        target: "GameObject",
        add_types: Optional[list] = None,
        add_subtypes: Optional[list] = None,
    ) -> None:
        self.engine.become_copy(obj, target, add_types, add_subtypes)

    def become_copy_until_end_of_turn(
        self,
        obj: "GameObject",
        target: "GameObject",
        add_types: Optional[list] = None,
        add_subtypes: Optional[list] = None,
    ) -> None:
        self.engine.become_copy_until_end_of_turn(obj, target, add_types, add_subtypes)

    def set_copy_target(self, obj: "GameObject", target: "GameObject") -> None:
        self.engine.set_copy_target(obj, target)

    def gain_life(self, player: "Player", amount: int) -> None:
        self.engine.gain_life(player, amount)

    def prevent_damage_to_player(self, player: "Player", amount: Union[int, str] = "all") -> None:
        self.engine.prevent_damage_to_player(player, amount)

    def prevent_damage_to_target(self, target: Any, amount: Union[int, str] = "all") -> None:
        self.engine.prevent_damage_to_target(target, amount)

    def prevent_all_combat_damage_this_turn(self, controller: "Player") -> None:
        self.engine.prevent_all_combat_damage_this_turn(controller)

    def lose_life(self, player: "Player", amount: int, cause: str = "effect") -> None:
        self.engine.lose_life(player, amount, cause=cause)

    def sacrifice(self, player: "Player", what: str = "permanent", count: int = 1) -> None:
        self.engine.sacrifice(player, what, count)

    def request_search(
        self,
        player: "Player",
        criteria: Any = "",
        destination: str = "hand",
        count: int = 1,
        optional: bool = True,
        zones: Optional[list[str]] = None,
        destinations: Optional[list[str]] = None,
        exile_rest: bool = False,
        extra_counters: Optional[dict[str, Any]] = None,
        destination_if: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self.engine.request_search(
            player, criteria, destination, count, optional,
            zones=zones, destinations=destinations, exile_rest=exile_rest,
            extra_counters=extra_counters, destination_if=destination_if,
        )

    def choose_objects(
        self,
        player: "Player",
        candidates: list["GameObject"],
        action: str,
        count: int = 1,
        optional: bool = False,
        prompt: str = "",
        source: Optional["GameObject"] = None,
        then_specs: Optional[list[dict[str, Any]]] = None,
        then_specs_if_commander: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """Open the general "which of these objects?" choice — see
        `RulesEngine.request_choose_objects`."""
        self.engine.request_choose_objects(
            player, candidates, action, count=count, optional=optional,
            prompt=prompt, source=source, then_specs=then_specs,
            then_specs_if_commander=then_specs_if_commander,
        )

    def impulsive_look(
        self,
        player: "Player",
        count: int,
        criteria: Any = "",
        hit_destination: str = "hand",
        miss_destination: str = "graveyard",
        optional: bool = True,
    ) -> None:
        self.engine.request_impulsive_look(
            player, count, criteria, hit_destination, miss_destination, optional
        )

    def exile_with_play_permission(
        self,
        player: "Player",
        count: int,
        source_name: Optional[str] = None,
        permission_player: Optional["Player"] = None,
        same_turn_only: bool = False,
    ) -> None:
        self.engine.exile_with_play_permission(
            player, count, source_name=source_name,
            permission_player=permission_player, same_turn_only=same_turn_only,
        )

    def shuffle_library(self, player: "Player") -> None:
        self.engine.shuffle_library(player)

    def shuffle_hand_and_graveyard_into_library(self, player: "Player") -> None:
        self.engine.shuffle_hand_and_graveyard_into_library(player)

    def cascade(self, player: "Player", max_mana_value: int) -> None:
        self.engine.request_cascade(player, max_mana_value)

    def discover(self, player: "Player", max_mana_value: int) -> None:
        self.engine.request_discover(player, max_mana_value)

    def counter(
        self,
        target: Any,
        unless_pays: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        self.engine.counter_unless_pays(target, unless_pays, source)

    def return_to_hand(self, target: "GameObject") -> None:
        self.engine.return_to_hand(target)

    def return_from_graveyard(
        self,
        target: "GameObject",
        destination: str = "battlefield",
        controller_id: Optional[str] = None,
        transformed: bool = False,
    ) -> None:
        self.engine.return_from_graveyard(
            target, destination, controller_id=controller_id, transformed=transformed
        )

    def blink(self, target: "GameObject", controller: Optional["Player"] = None) -> None:
        self.engine.blink(target, controller=controller)

    def exile_return_transformed(self, target: "GameObject") -> None:
        self.engine.exile_return_transformed(target)

    def return_dies_as_new_permanent(
        self,
        target: "GameObject",
        new_type_line: str,
        new_oracle_text: str,
        attach_to: Optional["GameObject"] = None,
    ) -> None:
        self.engine.return_dies_as_new_permanent(
            target, new_type_line, new_oracle_text, attach_to=attach_to
        )

    def add_mana(self, player: "Player", color: str, amount: int = 1) -> None:
        self.engine.add_mana(player, color, amount)

    def add_mana_any_color(
        self, player: "Player", colors: Optional[list[str]] = None
    ) -> None:
        self.engine.add_mana_any_color(player, colors)


def _event_player(context: GameContext, key: str = "controller_id") -> Optional["Player"]:
    """The `Player` named by the currently-resolving trigger's own event
    (`GameContext.trigger_event`), or ``None`` outside a trigger resolution
    / when the event carries no such id.

    ``key`` names *which* player the event means — ``"controller_id"`` (who
    tapped the permanent, `TAPPED_FOR_MANA`) or ``"player_id"`` (who cast
    the spell / whose library it was, `SPELL_CAST`/`MILL_CARD`).
    """
    event = context.trigger_event
    if event is None:
        return None
    player_id = event.get(key)
    if player_id is None:
        return None
    try:
        return context.state.player_by_id(player_id)
    except (KeyError, ValueError):
        return None


def _controller_of(source: Optional["GameObject"], context: GameContext) -> Optional["Player"]:
    """The `Player` controlling ``source`` (RULE 109.4), else the active player.

    An untargeted effect ("scry 2", "you draw a card") affects its own
    controller; if the effect has no source yet (a fixture/direct call), fall
    back to the active player.
    """
    controller_id = getattr(source, "controller_id", None)
    if controller_id is not None:
        try:
            return context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            pass
    return context.active_player


def _defending_player_of(source: Optional["GameObject"], context: GameContext) -> Optional["Player"]:
    """The player ``source`` (an attacking creature) is attacking (RULE 506.4),
    for a combat-math keyword's "defending player" clause (annihilator 702.86,
    afflict 702.130). Reads the ``combat_defender`` spec `declare_attackers`
    stamped onto the attacker — a player id directly, or a planeswalker's
    controller when the attack target was a planeswalker (RULE 506.4d).

    ENG-14: ``source`` itself might not be the one attacking. Reconfigure
    (RULE 702.151) lets an Equipment's own trigger fire off a
    ``self_or_attached_permanent`` subject (Simian Sling's "whenever this
    creature **or equipped creature** becomes blocked, it deals 1 damage to
    defending player") — correct when the Equipment is itself a creature
    currently attacking, but when it's attached to (and reconfigured off) a
    *different* attacking creature instead, only that host carries the
    `combat_defender` stamp. Falls back to the object ``source`` is
    currently attached to before giving up — the same self-or-host pair the
    trigger condition already scoped by — so every existing caller (always
    the attacking creature itself, never an attached permanent) sees no
    change: ``attached_to`` is unset for them.

    ``None`` if neither ``source`` nor its host (if any) is a live,
    currently-attacking object (e.g. a hand-built test event with no real
    attack declared).
    """
    spec = getattr(source, "combat_defender", None)
    if not spec:
        host_id = getattr(source, "attached_to", None)
        if host_id is not None:
            host = context.state.find_object(host_id)
            spec = getattr(host, "combat_defender", None) if host is not None else None
    if not spec:
        return None
    if spec.get("kind") == "player":
        try:
            return context.state.player_by_id(spec["id"])
        except (KeyError, ValueError):
            return None
    if spec.get("kind") == "planeswalker":
        pw = context.state.find_object(spec["instance_id"])
        if pw is None:
            return None
        try:
            return context.state.player_by_id(pw.controller_id)
        except (KeyError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class GameEffect(ABC):
    """Base class for all effects (docs/07 PART 2).

    ``target_spec`` is ``None`` for a global / fixed-set effect (draw, gain
    life, board wipe) and a `TargetSpec` for a *targeting* effect (RULE 115),
    so the engine can tell before casting whether a legal target is required
    and available (RULE 601.2c). Subclasses that target set it in ``__init__``.
    """

    target_spec: Optional[TargetSpec] = None
    #: A *second* (and further) requirement for effects that genuinely need
    #: two independently-chosen targets of different kinds in one clause —
    #: "attach target Equipment you control to target creature you control"
    #: (Brass Squire, Halvar), "put a +1/+1 counter on target creature you
    #: control. It deals damage equal to its power to target creature you
    #: don't control." (Archdruid's Charm). ``target_spec`` stays the first;
    #: this holds the rest, in printed order. Every gathering path reads
    #: `target_specs` below rather than ``target_spec`` directly, and
    #: `_apply_effects_partitioned` hands such an effect *all* of its groups
    #: flattened, so `apply` sees ``targets[0]``, ``targets[1]``, … in that
    #: same order. Empty for the overwhelming majority of effects.
    extra_target_specs: tuple[TargetSpec, ...] = ()

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        self.source = source

    @property
    def target_specs(self) -> list[TargetSpec]:
        """Every RULE 115.1 requirement this one effect announces, in printed
        order — ``[]`` for a non-targeting effect, one entry for the ordinary
        case, and 2+ only for the multi-target clauses `extra_target_specs`
        documents."""
        if self.target_spec is None:
            return []
        return [self.target_spec, *self.extra_target_specs]

    @abstractmethod
    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        """Apply this effect to the game."""

    def can_apply(self, context: GameContext) -> bool:  # noqa: D401 - simple default
        """Whether the effect can apply right now (default: always)."""
        return True

    def target_polarity(self) -> Optional[str]:
        """Best-effort "is this effect's target on the receiving end of
        something good or bad" — ``"harmful"``, ``"beneficial"``, or
        ``None`` for no opinion (the default, and every effect not
        overriding this below).

        Not rules data: nothing in the engine reads this, and it is never
        consulted while actually resolving anything. It exists purely so
        `targeting.spell_target_specs`/`ability_target_specs` can stamp a
        `TargetSpec.polarity` hint onto the offer a `cast_spell`/
        `activate_ability` action carries, which `services/bots.py`'s
        `GreedyBot` reads to point a removal spell at an opponent's
        permanent and a pump spell at its own, instead of always preferring
        an opponent's stuff regardless of what the spell actually does to
        it. Deliberately conservative: an effect whose sign genuinely
        depends on its own parameters (a "-N/-N" `PumpEffect`, a "-1/-1"
        `AddCountersEffect`) overrides this to inspect them; anything not
        listed below (a bounce, a granted keyword, a counter-removal of
        unknown sign, …) stays ``None`` rather than guessing.
        """
        return None


def _apply_effects_partitioned(
    effects: list["GameEffect"],
    context: GameContext,
    targets: Optional[list[Any]],
    target_groups: Optional[list[list[Any]]],
    source: Optional["GameObject"] = None,
    group_index: int = 0,
    previous_targets: Optional[list[Any]] = None,
    created_objects: Optional[list[Any]] = None,
) -> None:
    """Apply each of ``effects`` against its own share of ``targets``.

    Mirrors `RulesEngine.resolve_top_of_stack`'s per-effect
    `StackItem.target_groups` dispatch, for a *nested* effects list —
    `TriggeredAbility`/`ActivatedAbility` wrap their own sub-effects, so the
    outer stack-resolution loop only ever sees one effect (the wrapper) and
    can't partition *their* targets itself; this is the same logic run one
    level down. ``target_groups=None`` (the overwhelming common case: at
    most one targeting effect) keeps every sub-effect reading ``targets``
    directly, unchanged from before `target_groups` existed.

    RULE 608.2: an effect that opens an interactive `pending_choice`
    **suspends** the rest of the list rather than letting the next effect
    run — the game state holds one pending choice at a time, so a second
    interactive effect resolving now would silently overwrite the first
    player's prompt. The remainder is pushed onto
    `GameState.deferred_effects` and picked back up by
    `RulesEngine.resume_deferred_effects` once the choice is answered. Only
    ever reached by a resolution with 2+ interactive effects — an entwined
    modal spell (RULE 702.42a), or an ability whose clauses each prompt.
    ``group_index`` is where in ``target_groups`` to start, so a resumed
    remainder keeps reading its own slices.

    ``previous_targets`` seeds `GameContext.previous_targets` — the referent
    a later clause's pronoun points at ("… **It** fights target creature you
    don't control."). It is threaded here rather than kept on the context
    alone so a resumed remainder (below) picks the referent back up, and
    restored afterwards so a nested resolution can't leak its own.
    `GameContext.created_objects` ("**The tokens** are goaded…") is scoped
    the same way; ``created_objects`` is only ever passed by a *resumed*
    remainder picking its own referent back up, so a fresh resolution always
    starts empty and can't point at something an unrelated one made.
    """
    state = getattr(context, "state", None)
    already_pending = getattr(state, "pending_choice", None) if state is not None else None
    outer_previous = getattr(context, "previous_targets", [])
    outer_created = getattr(context, "created_objects", [])
    context.previous_targets = list(previous_targets or [])
    context.created_objects = list(created_objects or [])
    try:
        for position, effect in enumerate(effects):
            if source is not None and effect.source is None:
                effect.source = source
            specs = effect.target_specs
            if target_groups is not None and specs:
                # An effect with 2+ requirements consumes that many groups and
                # sees them flattened, so its `apply` reads targets[0],
                # targets[1], … in printed order (see `extra_target_specs`).
                group: list[Any] = []
                for _ in specs:
                    if group_index < len(target_groups):
                        group.extend(target_groups[group_index])
                    group_index += 1
                effect.apply(context, group)
                used = group
            else:
                effect.apply(context, targets)
                used = list(targets or [])
            if specs and used:
                context.previous_targets = list(used)
            if state is None or position + 1 >= len(effects):
                continue
            opened = getattr(state, "pending_choice", None)
            if opened is not None and opened is not already_pending:
                state.deferred_effects.append(
                    {
                        "effects": list(effects[position + 1:]),
                        "targets": targets,
                        "target_groups": target_groups,
                        "group_index": group_index,
                        "source": source,
                        "previous_targets": list(context.previous_targets),
                        "created_objects": list(context.created_objects),
                    }
                )
                return
    finally:
        context.previous_targets = outer_previous
        context.created_objects = outer_created


# ---------------------------------------------------------------------------
# TYPE 1: Static effects (RULE 611) + rule overrides (skip phase, etc.)
# ---------------------------------------------------------------------------


class StaticEffect(GameEffect):
    """A continuous effect / rule modification (docs/07 PART 1, PART 8).

    ``kind`` names what it overrides (e.g. ``"skip_phase"``). For a
    skip-phase effect, ``params["phase"]`` is the step/phase name to skip.
    ``duration`` controls when the engine discards it (``"permanent"``,
    ``"end_of_turn"``, ``"next_turn"``, ``"once"``).
    """

    def __init__(
        self,
        kind: str,
        params: Optional[dict[str, Any]] = None,
        duration: str = "permanent",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.params = params or {}
        self.duration = duration
        self.active = True

    def skips_step(self, step_name: str) -> bool:
        return (
            self.active
            and self.kind == "skip_phase"
            and self.params.get("phase") == step_name
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        # Static effects are consulted where relevant (e.g. skip checks in
        # the phase loop) rather than "applied" imperatively; nothing to do
        # on a generic apply.
        return None


class StaticAbility(GameEffect):
    """A continuous static ability applied through the layer system (RULE 613).

    Unlike `StaticEffect` (a player-scoped rule override like "skip your draw
    step"), this is a *battlefield* continuous effect that reshapes other
    permanents' characteristics — an anthem's +1/+1, a granted keyword, a
    type change, or a mana-cost reduction. It carries no imperative behaviour;
    `game/continuous.py` reads these off the battlefield and folds them into
    each object's derived characteristics in layer order.

    ``layer`` selects where it applies (RULE 613.7 sublayer names, plus the
    non-layer ``"cost"`` bucket for 601.2f cost adjustments):

    * ``"type"``   → layer 4 (add card types);
    * ``"ability"``→ layer 6 (add keyword abilities);
    * ``"pt_set"`` → layer 7b (set power/toughness);
    * ``"pt_mod"`` → layer 7c (modify power/toughness — anthems, counters);
    * ``"cost"``   → not a layer; a cost adjustment applied when the affected
      spell's total cost is calculated (RULE 601.2f).

    ``affects`` names the set it touches (see `continuous.affected_objects`);
    ``params`` is the modification (e.g. ``{"power": 1, "toughness": 1}``,
    ``{"keywords": ["flying"]}``, ``{"add_types": ["creature"]}``,
    ``{"generic": 1}``).
    """

    LAYER_NUMBERS: dict[str, int] = {
        "copy": 1,         # layer 1 — copy effects (RULE 707)
        "control": 2,      # layer 2 — control-changing effects (RULE 613.2)
        "text": 3,         # layer 3 — text-changing effects (RULE 612)
        "type": 4,         # layer 4 — type-changing effects
        "color": 5,        # layer 5 — colour-changing effects
        "ability": 6,      # layer 6 — ability-adding effects
        "pt_cda": 7,       # layer 7a — characteristic-defining P/T
        "pt_set": 7,       # layer 7b — set power/toughness
        "pt_mod": 7,       # layer 7d — modify power/toughness (anthems)
        "pt_switch": 7,    # layer 7e — switch power and toughness
        "cost": 99,        # not a layer — cost adjustment (RULE 601.2f)
    }

    def __init__(
        self,
        layer: str,
        affects: str = "self",
        params: Optional[dict[str, Any]] = None,
        source: Optional["GameObject"] = None,
        description: str = "",
        duration: Optional[str] = None,
        duration_data: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.layer = layer
        self.affects = affects
        self.params = params or {}
        self.description = description
        #: RULE 611: how long this continuous effect lasts, for one created by
        #: a *resolving* spell/ability and parked in `GameState.
        #: floating_statics` ("until your next turn, …"). ``None`` — the
        #: overwhelming majority — is a permanent's own printed static, which
        #: lasts exactly as long as the permanent is on the battlefield and
        #: needs no duration at all. See `game/durations.py`.
        self.duration = duration
        #: Per-duration payload: ``{"player_id": …}`` for ``your_next_turn``
        #: (whose turn ends it), ``{"condition": …}`` for ``for_as_long_as``.
        self.duration_data = duration_data or {}
        #: The objects a floating static applies to when it was created for
        #: specific permanents ("target creature gains flying until …") — an
        #: instance-id list, since the affected object is chosen at
        #: resolution and can't be a selector. Empty = use ``affects``.
        self.object_ids: list[int] = []

    @property
    def layer_number(self) -> int:
        return self.LAYER_NUMBERS.get(self.layer, 99)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # continuous — consulted by continuous.recompute, not applied


# ---------------------------------------------------------------------------
# TYPE 2: Triggered abilities (RULE 603)
# ---------------------------------------------------------------------------


class TriggeredAbility(GameEffect):
    """Fires on an event and goes on the stack (docs/07 PART 2, RULE 603).

    ``effects`` is one fixed list bound once, at bind-on-load, and reused
    for *every* firing — fine for the overwhelming majority of triggered
    abilities, whose effects don't depend on data specific to a given
    firing. A trigger whose magnitude genuinely depends on *that firing*
    (Rampage's per-block blocker count, RULE 702.23; a ward ability's own
    caster/target pair, RULE 702.21) can't be expressed this way. The
    sanctioned answer, rather than new IR here, is to build a fresh
    `TriggeredAbility` (or, when even the controller/shape varies per
    firing, a raw `StackItem`) right at the call site with the per-firing
    data baked directly into its effects, then place it exactly like any
    other trigger — see `RulesEngine.check_rampage` (rebuilds a
    `TriggeredAbility` and calls `_place_trigger`) and `check_ward` (skips
    `TriggeredAbility` entirely and pushes a `StackItem` straight on the
    stack, since ward's controller is the *target's*, not the source's).
    Follow that pattern for a new card needing "that creature"/"the object
    this ability just created" rather than adding a dynamic-reference
    target-spec kind — no card in this catalogue has needed one yet.

    ``trigger_event`` is the `EventType` to watch. ``condition`` is an
    optional extra predicate ``(event, context) -> bool``. ``effects`` are
    the one-shot effects placed on the stack when it triggers — or, for a
    modal ability (RULE 700.2), ignored in favour of ``modes``: a list of
    ``{"effects": [GameEffect, ...], "description": str}`` entries, one per
    printed mode. ``modes`` is chosen from interactively as the ability is
    placed on the stack (`game/rules_engine.py`'s `_place_triggers`/
    `resolve_trigger_mode_choice`, a `trigger_mode` `pending_choice` — the
    same "chosen before target/optional choice" ordering a modal spell's own
    mode gets at cast time); ``modes_or_both`` mirrors RULE 700.2e for a
    triggered ability with exactly two modes. ``modes_choose`` is RULE
    700.2's "choose *N* —" count (``1`` for the ordinary "choose one" case);
    for ``modes_choose > 1`` the choice is made iteratively, one mode per
    round, mirroring how a library search offers "up to N" one card at a
    time (`resolve_trigger_mode_choice`). ``modes_at_least`` is RULE 700.2's
    "choose *N* or more —" (Farewell-shaped): ``modes_choose`` becomes a
    minimum rather than an exact count, and the iterative choice offers a
    "done" option once that minimum is met instead of forcing every mode to
    be picked.
    """

    def __init__(
        self,
        trigger_event: str,
        effects: list[GameEffect],
        condition: Optional[Callable[[GameEvent, GameContext], bool]] = None,
        optional: bool = False,
        once_per_turn: bool = False,
        controller_id: Optional[str] = None,
        source: Optional["GameObject"] = None,
        description: str = "",
        modes: Optional[list[dict[str, Any]]] = None,
        modes_or_both: bool = False,
        modes_choose: int = 1,
        modes_at_least: bool = False,
        reflexive: bool = False,
        mana_ability: bool = False,
        functions_from_graveyard: bool = False,
    ) -> None:
        super().__init__(source)
        #: RULE 113.6a (PAR-16): whether this ability fires while its own
        #: source sits in the *graveyard* rather than the battlefield — the
        #: Eidolon/Phoenix family ("Whenever `<event>`, [you may] return
        #: this card from your graveyard to your hand"). Inferred by
        #: `effect_binder.bind_ability` whenever the built effects include a
        #: `ReturnSelfFromGraveyardToHandEffect`/
        #: `ReturnSelfFromGraveyardToBattlefieldEffect` — real printings
        #: carry no explicit "(this ability functions from your graveyard.)"
        #: reminder to key off instead, so the effect and the permission
        #: always travel together, the same inference PAR-10's
        #: `ActivationCost.graveyard_zone` already uses for the activated
        #: half of the same family. Consulted by `RulesEngine.
        #: _collect_triggers`'s graveyard scan, which — unlike the ordinary
        #: `state.permanents()` scan — only fires abilities carrying this flag.
        self.functions_from_graveyard = functions_from_graveyard
        #: RULE 605.1b/605.4: this is a **triggered mana ability** — it
        #: triggers off activating a mana ability and itself only produces
        #: mana. Such an ability never uses the stack: it resolves
        #: immediately, so the mana it adds is spendable within the very
        #: payment that triggered it (Wild Growth's extra {G} is available
        #: for the spell you were tapping the land to cast; Kinnan's copy is
        #: the whole reason he is played). `RulesEngine._collect_triggers`
        #: applies these on the spot instead of queueing them into
        #: `pending_triggers`.
        self.mana_ability = mana_ability
        self.trigger_event = trigger_event
        self.effects = effects
        self.condition = condition
        self.optional = optional
        self.controller_id = controller_id
        self.description = description
        self.modes = modes
        self.modes_or_both = modes_or_both
        self.modes_choose = modes_choose
        self.modes_at_least = modes_at_least
        #: RULE 603.3d "that permanent/spell": the ability's single targeting
        #: effect acts on *the exact object that fired the triggering event*
        #: (Lavinia/Boromir "counter that spell", Price of Glory "destroy
        #: that land") — not a freely chosen target. When set, `RulesEngine.
        #: _place_triggers` resolves the target from the event's
        #: ``instance_id`` at placement time and bakes it in, opening no
        #: `trigger_target` choice; if the object is already gone (e.g. the
        #: spell left the stack), the trigger is dropped (RULE 603.3c). This
        #: is the generic form of the per-firing "that object" reference the
        #: bespoke `check_ward`/`check_rampage` paths hand-build.
        self.reflexive = reflexive
        #: "This ability triggers only once each turn" (RULE 603.2, e.g.
        #: Dionus, Elvish Archdruid's granted ability). Stamped by
        #: `check_trigger` the moment it fires — regardless of whether the
        #: ability actually resolves — since this instance is cached/reused
        #: across recomputes for as long as a grant holds (see
        #: `GameState._granted_ability_cache`), so the turn stamp survives
        #: the pass that would otherwise have rebuilt it from scratch.
        self.once_per_turn = once_per_turn
        self._last_triggered_turn: Optional[int] = None

    def check_trigger(self, event: GameEvent, context: GameContext) -> bool:
        """RULE 603.1: does this ability trigger for ``event``?"""
        if event.type != self.trigger_event:
            return False
        if self.condition is not None and not self.condition(event, context):
            return False
        if self.once_per_turn:
            turn = context.state.turn_number
            if self._last_triggered_turn == turn:
                return False
            self._last_triggered_turn = turn
        return True

    def apply(
        self,
        context: GameContext,
        targets: Optional[list[Any]] = None,
        target_groups: Optional[list[list[Any]]] = None,
    ) -> None:
        """Resolve the triggered ability by applying each of its effects.

        ``target_groups``, when given (`StackItem.target_groups`, 2+
        *different* targeting effects), partitions ``targets`` per effect —
        see `_apply_effects_partitioned`.
        """
        _apply_effects_partitioned(self.effects, context, targets, target_groups, source=self.source)


# ---------------------------------------------------------------------------
# TYPE 3: Replacement effects (RULE 614)
# ---------------------------------------------------------------------------


class ReplacementEffect(GameEffect):
    """Rewrites an event before it happens; never uses the stack (RULE 614).

    ``replacement_fn`` maps ``(event, context) -> GameEvent | None`` — a
    new event, or ``None`` to prevent it entirely. ``self_replacement``
    marks effects that may only apply once to a given event (RULE 614.5),
    which the engine tracks to avoid infinite replacement loops.
    """

    def __init__(
        self,
        event_type: str,
        replacement_fn: Callable[[GameEvent, GameContext], Optional[GameEvent]],
        condition: Optional[Callable[[GameEvent, GameContext], bool]] = None,
        source: Optional["GameObject"] = None,
        description: str = "",
    ) -> None:
        super().__init__(source)
        self.event_type = event_type
        self.replacement_fn = replacement_fn
        self.condition = condition
        self.description = description

    def can_replace(self, event: GameEvent, context: GameContext) -> bool:
        if event.type != self.event_type:
            return False
        if self.condition is not None and not self.condition(event, context):
            return False
        return True

    def apply_replacement(self, event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        return self.replacement_fn(event, context)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        # Replacement effects are consulted via apply_replacement, not run
        # imperatively.
        return None


# ---------------------------------------------------------------------------
# TYPE 4: Activated abilities (RULE 602)
# ---------------------------------------------------------------------------


class ActivatedAbility(GameEffect):
    """A cost the controller may pay for an effect (docs/07 PART 2, RULE 602).

    ``cost`` is the full parsed `ActivationCost` (mana + tap/untap + sacrifice
    + life + discard + counter removal, see `game/costs.py`); ``effects`` go on
    the stack when the cost is paid. ``mana_cost``/``taps_source`` remain as
    read-only views over the cost for callers that only care about those two.

    ``once_per_turn=True`` (Quirion Ranger/Scryb Ranger's "Activate only
    once each turn.") mirrors `TriggeredAbility.once_per_turn`'s own
    RULE 603.2-style stamp: `game/game_engine.py`'s `can_activate`/
    `activate_ability` check/stamp `_last_activated_turn` against the
    current turn number, the same "stamped on the *ability instance* itself,
    not a GameObject field reset every turn" shape.
    """

    def __init__(
        self,
        effects: list[GameEffect],
        cost: Optional["ActivationCost"] = None,
        mana_cost: Optional[ManaCost] = None,
        taps_source: bool = False,
        source: Optional["GameObject"] = None,
        description: str = "",
        once_per_turn: bool = False,
        attach_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.effects = effects
        if cost is None:
            # Back-compat: build a cost from the old mana/tap parameters.
            from .costs import ActivationCost

            cost = ActivationCost(mana=mana_cost or ManaCost(), taps_self=taps_source)
        self.cost = cost
        self.description = description
        self.once_per_turn = once_per_turn
        self._last_activated_turn: Optional[int] = None
        #: Which RULE 301/303/704 attachment keyword generated this ability
        #: — ``"equip"``/``"fortify"``/``"reconfigure"`` (`effect_binder.
        #: _keyword_activated_ability`), or ``None`` for an ordinary
        #: activated ability. Surfaced on the `activate_ability` action
        #: (`legal_actions_mixin._activate_action`) purely so
        #: `services/bots.py`'s `GreedyBot` can deprioritize equipping —
        #: better spent mana on casting something else first — without
        #: guessing from the ability's description text.
        self.attach_kind = attach_kind

    @property
    def mana_cost(self) -> ManaCost:
        return self.cost.mana

    @property
    def taps_source(self) -> bool:
        return self.cost.taps_self

    def apply(
        self,
        context: GameContext,
        targets: Optional[list[Any]] = None,
        target_groups: Optional[list[list[Any]]] = None,
    ) -> None:
        """``target_groups``, when given (`StackItem.target_groups`, 2+
        *different* targeting effects), partitions ``targets`` per effect —
        see `_apply_effects_partitioned`."""
        _apply_effects_partitioned(self.effects, context, targets, target_groups, source=self.source)


# ---------------------------------------------------------------------------
# SPECIAL: Win/loss overrides (docs/07 PART 9)
# ---------------------------------------------------------------------------


class WinGameEffect(GameEffect):
    """"You win the game." (RULE 104.2) — Jace, Wielder of Mysteries' "-8:
    Draw seven cards. Then if your library has no cards in it, you win the
    game." tail (``if_empty_library=True`` gates it on the caster's current
    library being empty; unconditional win-the-game clauses would pass
    ``False``, though no card in the pool needs that shape yet). Calls
    `RulesEngine.player_wins` — the ability's own controller wins outright.
    """

    def __init__(self, if_empty_library: bool = False, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.if_empty_library = if_empty_library

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except Exception:
            return
        if self.if_empty_library and player.library:
            return
        context.engine.player_wins(player)


class BecomeMonarchEffect(GameEffect):
    """"[Player] become[s] the monarch." (RULE 725.1) — untargeted ("you
    become the monarch", Palace Jailer-shaped) by default; ``target_kind="player"``
    opts into a real RULE 115 target ("target player becomes the monarch",
    the Throne of the Damned-adjacent phrasing), mirroring `GainLifeEffect`.
    """

    def __init__(
        self,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        if player is not None:
            context.become_monarch(player)


class TakeInitiativeEffect(GameEffect):
    """"[Player] take[s] the initiative." (RULE 726.1) — same untargeted/
    targeted split as `BecomeMonarchEffect`.

    All three of RULE 726.2's inherent abilities are live: the combat-damage
    steal, the upkeep venture, and "whenever a player takes the initiative,
    that player ventures into Undercity" — the last one fired off the
    `EventType.TOOK_INITIATIVE` `RulesEngine.take_initiative` announces, which
    is also why RULE 726.5's "taking the initiative while you already have
    it" still ventures.
    """

    def __init__(
        self,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        if player is not None:
            context.take_initiative(player)


class GetCityBlessingEffect(GameEffect):
    """RULE 702.131a: Ascend's spell-ability form — "If you control ten or
    more permanents and you don't have the city's blessing, you get the
    city's blessing for the rest of the game." (the resolving instant/
    sorcery's own one-shot check).

    Ascend on a *permanent* (702.131b — "any time you control ten or more
    permanents…") is a continuous check instead, since the permanent must
    keep watching the board for as long as it's out there rather than
    checking once at resolution — see `RulesEngine._sba_check_ascend`, swept
    at SBA cadence like the day/night and Ring-bearer checks. This effect is
    only the spell form; both share `RulesEngine.get_city_blessing`'s
    idempotent flag-set (RULE 702.131c/d).
    """

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from . import continuous  # avoid the continuous<->effects import cycle

        player = self.player or _controller_of(self.source, context)
        if player is None or player.has_city_blessing:
            return
        if continuous.count_selector(context.state, player.id, "permanents_you_control") >= 10:
            context.get_city_blessing(player)


class VentureIntoTheDungeonEffect(GameEffect):
    """"Venture into the dungeon." (RULE 701.49) — enter a dungeon, or move
    the venture marker one room down the one you're in.

    ``dungeon`` names RULE 701.49d's "venture into [quality]" variant
    ("venture into Undercity", RULE 726.2's own wording); ``None`` is the
    plain keyword action, which lets the player choose."""

    def __init__(
        self,
        dungeon: Optional[str] = None,
        player: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.dungeon = dungeon
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or _controller_of(self.source, context)
        if player is not None:
            context.venture_into_the_dungeon(player, self.dungeon)


class CompleteDungeonEffect(GameEffect):
    """RULE 309.6/309.7: remove the completed dungeon card from the game.

    Appended by `RulesEngine._collect_dungeon_room_triggers` to a *bottommost*
    room's own ability, so it runs exactly when 309.6's condition first holds
    — "the venture marker is on the bottommost room and that dungeon isn't the
    source of a room ability that has triggered but not yet left the stack".
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.complete_dungeon(player)


class RadiationMillEffect(GameEffect):
    """RULE 728.1's rad-counter inherent ability: "that player mills a
    number of cards equal to the number of rad counters they have. For
    each nonland card milled this way, that player loses 1 life and
    removes one rad counter from themselves." Built fresh by
    `RulesEngine._collect_inherent_triggers` for whichever player's
    precombat main phase is beginning — no permanent hosts this ability,
    same shape as `BecomeMonarchEffect`/`TakeInitiativeEffect`. The count
    is read live at resolution time (not frozen at trigger time), matching
    the rule's present-tense "have".
    """

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None:
            return
        count = player.counters.get("rad", 0)
        if count <= 0:
            return
        before = len(player.graveyard)
        context.mill(player, count)
        milled = player.graveyard[before:]
        nonland = sum(1 for obj in milled if not obj.is_land)
        if nonland:
            # RULE 728.1a: life lost "from radiation" refers to exactly this.
            context.lose_life(player, nonland, cause="radiation")
            context.add_player_counters(player, -nonland, "rad")


class CreateEmblemEffect(GameEffect):
    """"[Player] get[s] an emblem with '[ability]'." (RULE 114.2) — the
    quoted ability was already recursively parsed into a full nested
    `AbilitySpec` at parse time (`parser/oracle/catalogue/handlers.py`'s
    `_emblem_ability_spec`, the same recursive-`segment_line` idiom
    `static_handlers._quoted_ability_grant_effects` uses for an Aura/
    Equipment's quoted grant) and carried here as a plain JSON dict
    (``self.ability``) — still pure IR, nothing derived from card text has
    executed yet.

    Binding it into a live `TriggeredAbility`/`StaticAbility` happens once,
    at resolve time (`RulesEngine.create_emblem`), against a synthetic
    `Emblem` "source" rather than a real permanent (`models/emblem.py`) —
    an emblem has no permanent to attach to, so this can't happen at
    bind-on-load like every other ability.
    """

    def __init__(
        self,
        ability: Optional[dict] = None,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.ability = ability
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        if player is None or not self.ability:
            return
        context.create_emblem(player, self.ability)


class WinConditionEffect(GameEffect):
    """Overrides a win/loss check, e.g. "you can't lose the game"."""

    def __init__(
        self,
        condition_type: str = "prevent_loss",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.condition_type = condition_type

    def prevents_loss(self) -> bool:
        return self.condition_type == "prevent_loss"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class TopLibraryPermissionEffect(GameEffect):
    """Standing permission to look at / play lands from / cast spells from
    the top of the controller's library (Oracle of Mul Daya/Glarb, Calamity's
    Augur/Future Sight-shaped) — RULE 701 has no native "play from the top"
    provision, so each real card grants it as its own static ability.

    Bound like any other ``static`` ability (`game/effect_binder.py`'s
    ordinary dispatch), so it lands in ``obj.static_effects`` alongside
    `StaticAbility` — but it carries no layer/characteristic behaviour of its
    own: `continuous.recompute` only ever reads `StaticAbility` instances off
    that list (this isn't one, the same precedent as `CantBeCounteredEffect`
    above), so it's inert there. The only consumer is
    `game/top_library.py`, which scans every battlefield permanent a player
    controls for one of these (honouring ``requires_attached`` — an
    Equipment/Reconfigure-shaped grant that only counts while actually
    attached to something) and merges the results: multiple simultaneous
    grants OR together (a spell is castable if *any* active grant's
    ``min_mana_value`` gate — or lack of one — allows it), never AND.

    ``noncreature_only`` narrows ``cast_spells`` to noncreature spells only
    (Elsha of the Infinite's own restriction — a closed vocabulary of one,
    not a general subtype filter, since no other real card needs a different
    restriction here today). ``grants_flash``/``life_payment`` are each
    card's own conditional tail on top of the base permission: Elsha's "you
    may cast it as though it had flash" (consulted by `game/top_library.py`'s
    `may_cast_flash_from_top_of_library`, `GameEngine.can_cast`'s flash
    union) and Bolas's Citadel's "pay life equal to its mana value rather
    than pay its mana cost" (`top_library.top_library_life_payment_required`,
    `GameEngine._top_library_life_payment`) — both apply automatically
    whenever a spell is actually cast via *this* grant, never as a separate
    opt-in choice, matching the printed wording ("If you cast a spell this
    way, ...").
    """

    def __init__(
        self,
        look: bool = False,
        play_lands: bool = False,
        cast_spells: bool = False,
        min_mana_value: Optional[int] = None,
        requires_attached: bool = False,
        noncreature_only: bool = False,
        grants_flash: bool = False,
        life_payment: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.look = look
        self.play_lands = play_lands
        self.cast_spells = cast_spells
        self.min_mana_value = min_mana_value
        self.requires_attached = requires_attached
        self.noncreature_only = noncreature_only
        self.grants_flash = grants_flash
        self.life_payment = life_payment

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # continuous marker — consulted by top_library.py, not applied


class GraveyardCastPermissionEffect(GameEffect):
    """Standing permission to cast [permanent] spells from the controller's
    own graveyard (Lurrus of the Dream-Den-shaped) — the graveyard sibling of
    `TopLibraryPermissionEffect` above, consulted the same "scan on demand"
    way by `game/graveyard_cast.py` rather than a closed keyword vocabulary
    like Flashback/Escape (`GameEngine._graveyard_cast_keyword`): those are
    an alternative *cost* printed on the card itself, this is a *permission*
    granted by some other permanent, paid at the card's own normal mana cost.

    ``permanent_only`` is Lurrus's own "a permanent spell" restriction
    (creature/artifact/enchantment/land/planeswalker); ``max_mana_value`` is
    its "with mana value 2 or less" gate (``None`` = unrestricted).
    ``once_per_turn`` (RULE 500.4-adjacent "once during each of your turns")
    is tracked per *granting object* (`GameObject.graveyard_casts_this_turn`,
    reset every untap step alongside `activated_loyalty_this_turn` — the same
    per-object, not per-player, precedent: two copies of the granting
    permanent each grant their own use).

    Bound like `TopLibraryPermissionEffect` (an ordinary ``static`` ability,
    inert to `continuous.recompute` — the only consumer is
    `game/graveyard_cast.py`).

    ``exile_if_would_be_put_into_graveyard`` is Lurrus's own trailing "if a
    spell cast this way would be put into a graveyard this turn, exile it
    instead" clause (RULE 616, ``False`` by default — a different card
    reusing this same base permission need not carry it). It isn't checked
    here: `GameEngine.cast_spell`'s dispatch stamps `GameObject.
    cast_via_graveyard_cast_permission_until_turn` with the casting turn
    only when the grant it used has this flag set, and `RulesEngine.
    _move_to_graveyard` (the one choke point every graveyard-bound move —
    destroy, sacrifice, or SBA "dies" — funnels through) redirects to exile
    while that still matches the current turn number. A per-cast turn
    number rather than a per-object bool so a later *normal* recast this
    same turn (no permission involved) correctly clears it, mirroring
    `GameObject.cast_via_flashback`'s own unconditional-reassignment
    pattern.
    """

    def __init__(
        self,
        max_mana_value: Optional[int] = None,
        permanent_only: bool = True,
        once_per_turn: bool = True,
        exile_if_would_be_put_into_graveyard: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.max_mana_value = max_mana_value
        self.permanent_only = permanent_only
        self.once_per_turn = once_per_turn
        self.exile_if_would_be_put_into_graveyard = exile_if_would_be_put_into_graveyard

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # continuous marker — consulted by graveyard_cast.py, not applied


# ---------------------------------------------------------------------------
# SPECIAL: Conditional effect wrapper (parser/oracle/spec.py's EffectSpec.condition)
# ---------------------------------------------------------------------------


class ConditionalEffect(GameEffect):
    """Gates ``inner`` so it only applies when ``condition`` holds (RULE
    702.33b's "if this spell was kicked, <effect>." — a *second, additional*
    effect on the same spell/ability, not a replacement of an earlier one;
    see `parser.oracle.spec.EffectSpec.condition`'s docstring for why "if
    kicked, ... instead" — overriding an *existing* effect's own amount —
    is a different, unmodeled shape). ``{"target_is_controller": True}``
    (The Ghoul, Gunslinger: "target player gets two rad counters. If that
    player is you, create a Treasure token.") is the RULE 603.4-style
    sibling gated on the ability's own *resolved target* instead of an
    announced-cost flag — checked against ``targets`` at apply time, which
    only works because this effect carries no `target_spec` of its own: a
    `target_groups=None` ability (the overwhelming common case) passes its
    *whole* targets list to every sub-effect (`_apply_effects_partitioned`),
    so this effect transparently sees the target chosen for whichever
    *other* effect in the same ability actually declared it.

    Built only by `game/effect_binder.py`'s `build_effects`, never directly
    by `EffectRegistry` (``condition`` lives on the `EffectSpec`, not inside
    ``params``, so there's no ``"conditional"`` registry entry to construct
    one from card-text-derived data — keeps the whitelist's shape/behaviour
    split from docs/09 intact).
    """

    def __init__(
        self,
        condition: dict[str, Any],
        inner: GameEffect,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.condition = condition
        self.inner = inner
        self.target_spec = inner.target_spec

    def _condition_holds(
        self, context: GameContext, targets: Optional[list[Any]] = None
    ) -> bool:
        """AND of every key present in ``condition`` — each existing card so
        far has set exactly one, so this was a plain if/elif chain until
        Frodo, Adventurous Hobbit's own second clause ("if ~ is your
        Ring-bearer **and** the Ring has tempted you N or more times this
        game") needed two keys to hold *together*. Backward compatible: a
        one-key dict still checks exactly that one key, same as before.
        """
        kicked = self.condition.get("kicked")
        if kicked is not None:
            count = getattr(self.source, "kicker_count", 0) or 0
            if not ((count > 0) if kicked else (count == 0)):
                return False
        kicked_at_least = self.condition.get("kicked_at_least")
        if kicked_at_least is not None:
            # RULE 702.34a: "if it was kicked twice, <effect>." (PAR-17,
            # Archangel of Wrath) — Multikicker's own count threshold,
            # distinct from the plain "was it kicked at all" gate above.
            count = getattr(self.source, "kicker_count", 0) or 0
            if count < kicked_at_least:
                return False
        bargained = self.condition.get("bargained")
        if bargained is not None:
            # RULE 701.x (Beseech the Mirror's "if this spell was bargained,
            # …") — Kicker's own gate for a different optional additional
            # cost, reading `GameObject.bargained` instead of a counter.
            was = bool(getattr(self.source, "bargained", False))
            if not (was if bargained else not was):
                return False
        target_is_controller = self.condition.get("target_is_controller")
        if target_is_controller is not None:
            target = targets[0] if targets else None
            controller_id = getattr(self.source, "controller_id", None)
            is_controller = (
                controller_id is not None
                and getattr(target, "id", None) == controller_id
            )
            if not (is_controller if target_is_controller else not is_controller):
                return False
        life_gained_at_least = self.condition.get("life_gained_this_turn_at_least")
        if life_gained_at_least is not None:
            # "if you gained N or more life this turn, <effect>." (RULE
            # 119.3 — Frodo, Adventurous Hobbit's own first clause).
            # `self` here means the ability's controller, not a target.
            player = _controller_of(self.source, context)
            gained = context.state.life_gained_this_turn.get(getattr(player, "id", None), 0)
            if gained < life_gained_at_least:
                return False
        is_ring_bearer = self.condition.get("is_ring_bearer")
        if is_ring_bearer is not None:
            # "if ~ is your Ring-bearer, <effect>." (RULE 701.52a) — reads
            # the ability's controller's `ring_bearer_id` against the
            # source's own `instance_id`, "not" for the Aragorn/Faramir-
            # shaped "if you chose a creature **other than** ~" mirror.
            player = _controller_of(self.source, context)
            bearer_id = getattr(player, "ring_bearer_id", None)
            source_id = getattr(self.source, "instance_id", None)
            is_bearer = bearer_id is not None and bearer_id == source_id
            if not (is_bearer if is_ring_bearer else not is_bearer):
                return False
        creatures_died_this_turn_at_least = self.condition.get("creatures_died_this_turn_at_least")
        if creatures_died_this_turn_at_least is not None:
            # "if a creature died under your control this turn, <effect>."
            # (Sméagol, Helpful Guide) — `GameState.creatures_died_this_turn`,
            # tallied by `RulesEngine._move_to_graveyard`'s own DIES handling,
            # the same "this turn" counter idiom as `life_gained_this_turn`.
            player = _controller_of(self.source, context)
            died = context.state.creatures_died_this_turn.get(getattr(player, "id", None), 0)
            if died < creatures_died_this_turn_at_least:
                return False
        source_x_paid_at_least = self.condition.get("source_x_paid_at_least")
        if source_x_paid_at_least is not None:
            # "If X is 5 or more, destroy all other creatures." (Martial
            # Coup) — the announced {X} this spell/ability was itself cast
            # or activated for (RULE 107.3c, `GameObject.x_paid`), unlike
            # `_substitute_x`'s ``"x"`` sentinel (which rewrites a plain
            # magnitude field, not a gate) or `ring_tempted_at_least`-style
            # keys (which read board/player state, not the source itself).
            x_paid = getattr(self.source, "x_paid", 0) or 0
            if x_paid < source_x_paid_at_least:
                return False
        controls_none_of_type = self.condition.get("controls_none_of_type")
        if controls_none_of_type is not None:
            # "if you don't control a Food, <effect>." (Butterbur, Bree
            # Innkeeper) — a live battlefield scan for the controller's own
            # permanents of that printed subtype, same word list
            # `segmenter._SACRIFICE_TYPE_TRIGGER_RE`/`_NAMED_TOKEN_WORDS`
            # already trust.
            controller_id = getattr(_controller_of(self.source, context), "id", None)
            word = str(controls_none_of_type).lower()
            controls_one = any(
                o.controller_id == controller_id
                and word in o.card.type_line.partition("—")[2].strip().lower().split()
                for o in context.state.battlefield
            )
            if controls_one:
                return False
        ring_tempted_at_least = self.condition.get("ring_tempted_at_least")
        if ring_tempted_at_least is not None:
            # "if the Ring has tempted you N or more times this game,
            # <effect>." (RULE 701.51b — `Player.ring_level`, capped at 4).
            player = _controller_of(self.source, context)
            level = int(getattr(player, "ring_level", 0) or 0)
            if level < ring_tempted_at_least:
                return False
        ring_tempted_at_most = self.condition.get("ring_tempted_at_most")
        if ring_tempted_at_most is not None:
            # The upper-bound mirror of `ring_tempted_at_least` — "…
            # <effect>. Otherwise, the Ring tempts you." (Frodo, Sauron's
            # Bane) is an if/else over the same threshold, expressed as two
            # independent conditionals rather than a dedicated "otherwise"
            # branch, so the complementary bound needs its own key.
            player = _controller_of(self.source, context)
            level = int(getattr(player, "ring_level", 0) or 0)
            if level > ring_tempted_at_most:
                return False
        return True

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.inner.source is None:
            self.inner.source = self.source
        if self._condition_holds(context, targets):
            self.inner.apply(context, targets)


# ---------------------------------------------------------------------------
# Concrete one-shot effects (RULE 608 resolution bodies)
# ---------------------------------------------------------------------------


#: `DealDamageEffect`'s closed selector vocabulary for a mass, untargeted hit
#: (RULE 601.2c — not RULE 115 targeting at all, e.g. Pyroclasm's "~ deals 2
#: damage to each creature"). Kept small and explicit rather than reusing
#: `continuous.group_selector_objects`'s full vocabulary, since only these
#: phrasings appear on real damage-dealing cards. ``each_creature_and_player``
#: is the compound "~ deals N damage to each creature and each player"
#: shape (Volcanic Fallout) — a single amount hitting both groups at once,
#: not two separate effects (so a doubling replacement like Furnace of Rath
#: sees — and can double — each hit individually, exactly as printed).
_DAMAGE_SELECTORS: frozenset[str] = frozenset(
    {"each_creature", "each_player", "each_opponent", "each_creature_and_player",
     # "~ deals 1 damage to each creature and each planeswalker." (MEC-11's
     # Stalwart Speartail) — the compound-selector sibling of
     # ``each_creature_and_player``, a creature-or-planeswalker union rather
     # than creature-or-player.
     "each_creature_and_planeswalker",
     # "it deals 1 damage to **you**" (Mana Vault's draw-step ping) — the
     # source's own controller, untargeted (RULE 115: "you" is never a
     # target). The single-player counterpart of "each_player" above.
     "controller",
     "defending_player"}
)


class DealDamageEffect(GameEffect):
    """Deal ``amount`` damage to a target player or creature — or, with
    ``selector`` set, to *every* object/player a closed vocabulary names
    (RULE 601.2c "each creature"/"each player"/"each opponent" — a mass
    effect, not a RULE 115 target, so it carries no ``target_spec`` at all,
    the same untargeted-group shape `PumpEffect.selector` uses).
    """

    def __init__(
        self,
        amount: int,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "any",
        selector: Optional[str] = None,
        optional: bool = False,
        count: int = 1,
        divided: bool = False,
        double_at: Optional[int] = None,
        amount_if_kicked: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self._base_amount = amount
        # RULE 702.33b's *override* kicked-conditional ("~ deals 2 damage to
        # any target. If this spell was kicked, it deals 4 damage instead." —
        # Burst Lightning-shaped), distinct from the *additive* "if kicked,
        # <effect>" shape `ConditionalEffect`/`EffectSpec.condition` already
        # cover — mirrors `PreventDamageEffect.amount_if_kicked` exactly, a
        # param on the effect rather than a generic wrapper since it's the
        # specific numeric param being overridden that differs per effect
        # type (amount here, a token count for `CreateTokenCopyEffect`, …).
        # A property (below) rather than resolving once in `__init__` since
        # `kicker_count` is only known once ``source`` is fully bound onto
        # the battlefield object, not necessarily yet at construction time.
        self.amount_if_kicked = amount_if_kicked
        self.target = target
        self.selector = selector if selector in _DAMAGE_SELECTORS else None
        # RULE 601.2d: a *divided* damage spell splits its total ``amount``
        # (typically {X}) among the chosen targets — "N damage divided as you
        # choose among …" (Fire Covenant, Shatterskull Smashing) — rather than
        # dealing the full amount to each (``count`` > 1's default). The "as
        # you choose" split is UI-less here: the total is distributed as
        # evenly as possible across whatever targets were chosen (an explicit
        # ``division`` list, if a caller sets one, wins) — a documented
        # simplification (the total dealt, and which permanents take damage,
        # are exactly right; only the player's freedom to lump it unevenly is
        # auto-made). ``double_at`` is Shatterskull's "if X is 6 or more,
        # deals twice X … instead" (RULE 107.3) — the pool doubles once the
        # resolved amount reaches that threshold.
        self.divided = divided
        self.double_at = double_at
        self.division: Optional[list[int]] = None
        if self.selector is None:
            # Damage targets "any target" by default (RULE 115.4); a card
            # that only hits creatures can narrow this to "creature".
            # ``optional`` is RULE 115.1a "up to one/N target(s)" — fewer
            # than ``count`` (including zero) is then a legal choice, so
            # casting is never locked on it. ``count`` > 1 is "to each of
            # up to N target X" (Volcanic Salvo-shaped) — the full amount
            # applies to *every* chosen target, not divided among them.
            self.target_spec = TargetSpec(kind=target_kind, optional=optional, count=count)

    @property
    def amount(self) -> Union[int, str]:
        kicker_count = getattr(self.source, "kicker_count", 0) or 0
        if self.amount_if_kicked is not None and kicker_count > 0:
            return self.amount_if_kicked
        return self._base_amount

    @amount.setter
    def amount(self, value: Union[int, str]) -> None:
        # `RulesEngine.resolve_top_of_stack`'s `_substitute_x` rewrites a
        # spell's own "x" sentinel to the announced X in place via plain
        # `setattr` — kept writable (onto `_base_amount`, not a fixed value)
        # so that substitution still composes with `amount_if_kicked`
        # exactly as an X-kicker spell's base amount would.
        self._base_amount = value

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            self._apply_selector(context)
            return
        chosen = _chosen_targets(targets, self.target_spec.count, self.target)
        if self.divided:
            self._apply_divided(context, chosen)
            return
        for target in chosen:
            context.deal_damage(target, self.amount, self.source)

    def _apply_divided(self, context: GameContext, targets: list[Any]) -> None:
        """Split the pool across ``targets`` (RULE 601.2d) — see ``divided``."""
        if not targets:
            return
        total = self.amount if isinstance(self.amount, int) else 0
        if self.double_at is not None and total >= self.double_at:
            total *= 2  # RULE 107.3: "deals twice X … instead"
        if self.division is not None and len(self.division) == len(targets):
            amounts = [int(a) for a in self.division]
        else:
            base, extra = divmod(total, len(targets))
            amounts = [base + (1 if i < extra else 0) for i in range(len(targets))]
        for target, amount in zip(targets, amounts):
            if amount > 0:
                context.deal_damage(target, amount, self.source)

    def _apply_selector(self, context: GameContext) -> None:
        if self.selector == "defending_player":
            # Simian Sling's "it deals 1 damage to defending player" — the
            # same per-firing dynamic-defender resolution afflict's
            # `LoseLifeEffect` selector uses (`_defending_player_of`), just
            # dealing damage instead of a direct life loss.
            player = _defending_player_of(self.source, context)
            if player is not None:
                context.deal_damage(player, self.amount, self.source)
            return
        if self.selector in ("each_creature", "each_creature_and_player", "each_creature_and_planeswalker"):
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            for obj in group_selector_objects(context.state, None, "all_creatures"):
                context.deal_damage(obj, self.amount, self.source)
            if self.selector == "each_creature_and_planeswalker":
                # A creature that's *also* a planeswalker (rare, but real —
                # RULE 205.2 multi-type permanents) was already hit above;
                # excluding ``is_creature`` here is what keeps it a single
                # hit, not two.
                for obj in context.state.permanents():
                    if obj.is_planeswalker and not obj.is_creature:
                        context.deal_damage(obj, self.amount, self.source)
                return
            if self.selector == "each_creature":
                return
        controller_id = getattr(self.source, "controller_id", None)
        if self.selector == "controller":
            # "it deals 1 damage to **you**" (Mana Vault) — the source's own
            # controller, and only them.
            player = _controller_of(self.source, context)
            if player is not None:
                context.deal_damage(player, self.amount, self.source)
            return
        for player in context.state.living_players():
            if self.selector == "each_opponent" and player.id == controller_id:
                continue
            context.deal_damage(player, self.amount, self.source)


#: `DrawCardEffect`'s ``count_selector`` vocabulary — a per-object dynamic
#: draw count (RULE 601.2c-style variable amount), the same "count instead
#: of a flat number" shape `continuous._pt_mod_count` uses for a per-count
#: anthem. Wyleth, Soul of Steel's "draw a card for each Aura and Equipment
#: attached to it"; ``"opponents_you_have"`` (Struggle for Project Purity's
#: Brotherhood mode: "each opponent draws a card. You draw a card for each
#: card drawn this way.") approximates "cards drawn this way" as the
#: opponent count — exact whenever nothing prevented an opponent's draw,
#: the same "auto-resolve the common case" simplification `ProliferateEffect`/
#: `SacrificeEffect` already use elsewhere in this engine.
_DRAW_COUNT_SELECTORS: frozenset[str] = frozenset(
    {"auras_and_equipment_attached_to_self", "opponents_you_have", "burden_counters_on_self"}
)


def _attached_auras_and_equipment_count(context: GameContext, source: Optional["GameObject"]) -> int:
    if source is None:
        return 0
    return sum(
        1 for o in context.state.battlefield
        if o.attached_to == source.instance_id
        and ("aura" in o.card.type_line.lower() or "equipment" in o.card.type_line.lower())
    )


class DrawCardEffect(GameEffect):
    """Draw ``count`` cards for the effect's controller (or a target player)
    — or, with ``count_selector`` set, a per-object dynamic count instead of
    a flat number (Wyleth, Soul of Steel's "draw a card for each Aura and
    Equipment attached to it"). ``selector="each_player"``/``"each_opponent"``
    (Struggle for Project Purity's Brotherhood mode: "each opponent draws a
    card") is instead a mass, untargeted draw for every matching living
    player — mirrors `AddPlayerCountersEffect.selector`'s shape.
    """

    def __init__(
        self,
        count: int = 1,
        player: Any = None,
        source: Optional["GameObject"] = None,
        count_selector: Optional[str] = None,
        target_kind: Optional[str] = None,
        selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.player = player
        self.count_selector = count_selector if count_selector in _DRAW_COUNT_SELECTORS else None
        self.selector = selector if selector in ("each_player", "each_opponent") else None
        # "Target player draws N cards" (Sign in Blood-shaped) — a genuine
        # RULE 115 target, unlike the untargeted default (most draw effects
        # just draw for their own controller).
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector in ("each_player", "each_opponent"):
            controller_id = getattr(self.source, "controller_id", None)
            for p in context.state.living_players():
                if self.selector == "each_opponent" and p.id == controller_id:
                    continue
                context.draw(p, self.count)
            return
        player = self.player or (targets[0] if targets else None) or _controller_of(self.source, context)
        count = self.count
        if self.count_selector == "auras_and_equipment_attached_to_self":
            count = _attached_auras_and_equipment_count(context, self.source)
        elif self.count_selector == "opponents_you_have":
            controller_id = getattr(self.source, "controller_id", None)
            count = sum(1 for p in context.state.living_players() if p.id != controller_id)
        elif self.count_selector == "burden_counters_on_self":
            # "…draw a card for each burden counter on The One Ring." — read
            # *after* this same activation's own ``add_counters`` effect has
            # already placed this turn's counter (RULE 608.2b, effects in
            # printed order), so the count includes it.
            counters = getattr(self.source, "counters", None) or {}
            count = int(counters.get("burden", 0))
        context.draw(player, count)


class RevealTopConditionalToHandEffect(GameEffect):
    """RULE 701.28's reveal, with a card-type-conditional move to hand
    (Goblin Guide-shaped): a player reveals the top card of their library;
    if it matches ``card_type``, that same player puts it into their hand
    — otherwise it's simply left on top (RULE 701.28's reveal has no
    mechanical weight of its own beyond the visibility, so "no match" does
    nothing rather than needing an explicit "leave it there" clause).

    ``whose="defending_player"`` (this card's only real use so far) reads
    RULE 506.4's per-firing attack defender via `_defending_player_of` —
    who's defending is only known once combat is declared, so it can't be
    a fixed target chosen at cast/trigger time the way an ordinary "target
    player" clause would be.
    """

    def __init__(
        self,
        whose: str = "defending_player",
        card_type: str = "land",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.whose = whose
        self.card_type = card_type

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.whose == "defending_player":
            player = _defending_player_of(self.source, context)
        else:
            player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        top = player.library[-1]
        checks = {
            "land": top.is_land,
            "creature": top.is_creature,
            "artifact": bool(top.card.is_artifact),
            "permanent": bool(
                top.is_land or top.is_creature or top.card.is_artifact
                or top.card.is_enchantment or top.is_planeswalker
            ),
        }
        if not checks.get(self.card_type, False):
            return
        player.library.pop()
        player.add_to_zone(top, Zone.HAND)


class DiscardEffect(GameEffect):
    """Make a player discard ``count`` cards — an interactive choice (RULE
    701.8: the discarding player, not this effect's controller, picks which
    cards), the looting-shaped template ("draw a card, then discard a
    card") shares with a directly-targeted forced discard (Mind Rot).

    ``target_kind="player"`` ("target player/opponent discards N cards")
    opts into a real RULE 115 target, exactly as `GainLifeEffect`'s own
    ``target_kind`` does — and for the same reason: without a declared
    `target_spec` this effect must *not* read ``targets[0]``, since any
    targets present would belong to a different effect on the same
    ability. ``scope`` ("each_player"/"each_opponent") is the untargeted
    mass form (RULE 601.2c), which hits everyone rather than one pick.
    """

    def __init__(
        self,
        count: int = 1,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        self.scope = scope

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.scope:
            controller = _controller_of(self.source, context)
            for other in context.state.living_players():
                if self.scope == "each_opponent" and other is controller:
                    continue
                context.discard_choice(other, self.count)
            return
        player = self.player
        if player is None and self.target_spec is not None and targets:
            player = targets[0]
        if player is None:
            player = _controller_of(self.source, context)
        context.discard_choice(player, self.count)


class RevealHandChooseDiscardEffect(GameEffect):
    """RULE 119/701.8's iconic hand-disruption template — "Target opponent
    reveals their hand. You choose a `<filter>` card from it. That player
    discards that card." (Duress/Thoughtseize/Coercion/Distress-shaped,
    one of the most repeated templates in the cache).

    "Reveals their hand" isn't a separate step to model (RULE 701.13's
    reveal is a zero-effect visibility action, and this engine has no
    client-visibility layer to update mid-resolution anyway) — the real
    behaviour is that the *chooser* is this effect's controller (the
    caster), not the revealed hand's owner, over that owner's *actual*
    cards. That's exactly `RulesEngine.request_choose_objects`'s shape
    (Tevesh Szat's sacrifice, Cloudstone Curio's bounce, …), just sourced
    from a hand instead of the battlefield, with its pre-existing
    ``action="discard"`` (`_apply_chosen_object` already resolves that
    against the *object's own owner*, regardless of who's choosing).

    ``exclude_land``/``exclude_creature`` are RULE 601.2c "non-X" card-type
    exclusions (composing — Duress's "noncreature, nonland" sets both);
    ``card_types`` is the inclusive opposite ("a creature or planeswalker
    card" — Despise-shaped). No filter at all (Coercion's bare "a card")
    leaves both unset and ``card_types`` `None`.
    """

    def __init__(
        self,
        target_kind: str = "player",
        target: Any = None,
        source: Optional["GameObject"] = None,
        exclude_land: bool = False,
        exclude_creature: bool = False,
        card_types: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind)
        self.target = target
        self.exclude_land = exclude_land
        self.exclude_creature = exclude_creature
        self.card_types = card_types

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def _matches(self, obj: "GameObject") -> bool:
        card = obj.card
        if self.exclude_land and obj.is_land:
            return False
        if self.exclude_creature and obj.is_creature:
            return False
        if self.card_types:
            checks = {
                "creature": obj.is_creature,
                "planeswalker": bool(getattr(obj, "is_planeswalker", False)),
                "artifact": bool(card.is_artifact),
                "instant": bool(card.is_instant),
                "sorcery": bool(card.is_sorcery),
                "enchantment": bool(card.is_enchantment),
            }
            if not any(checks.get(t, False) for t in self.card_types):
                return False
        return True

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        chosen = _chosen_targets(targets, 1, self.target)
        if not chosen:
            return
        revealed_player = chosen[0]
        caster = _controller_of(self.source, context)
        if caster is None:
            return
        candidates = [obj for obj in revealed_player.hand if self._matches(obj)]
        context.choose_objects(caster, candidates, "discard", count=1, source=self.source)


class PutHandCardsOnTopEffect(GameEffect):
    """"Put N cards from your hand on top of your library in any order"
    (Brainstorm's back half — the same loot-shaped template other
    draw-then-filter cards this pool doesn't need yet would share). See
    `RulesEngine.put_hand_cards_on_top` for why the missing "any order"
    choice is inert at this engine's fidelity.
    """

    def __init__(self, count: int = 1, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.put_hand_cards_on_top(player, self.count)


#: RULE 601.2c mass "destroy/exile all X" selectors (Wrath of God/Citywide
#: Bust/Farewell-shaped board wipes) — untargeted, unlike every RULE 115
#: target form above, so `DestroyEffect`/`ExileEffect` skip `target_spec`
#: entirely when one of these is set, mirroring `DealDamageEffect.selector`.
_MASS_DESTROY_SELECTORS: frozenset[str] = frozenset(
    {
        "all_creatures", "all_artifacts", "all_enchantments", "all_permanents",
        "all_planeswalkers", "all_lands",
    }
)


def _mass_selector_objects(
    context: GameContext, selector: str, filt: Optional[dict[str, Any]] = None
) -> list[Any]:
    """The battlefield objects a mass "all X [with condition]" selector
    picks — a snapshot list (the caller destroys/exiles each in turn, which
    mutates ``state.battlefield`` as it goes; iterating this separate list
    keeps that safe). ``filt`` is a small closed vocabulary of optional
    numeric conditions, all AND-combined: ``min_toughness``/``max_mana_
    value``/``min_mana_value`` (Citywide Bust/Austere Command-shaped).
    """
    # RULE 702.26c: a phased-out permanent is treated as though it doesn't
    # exist — a board wipe leaves it untouched.
    battlefield = context.state.permanents()
    if selector == "all_creatures":
        result = [o for o in battlefield if o.is_creature]
    elif selector == "all_artifacts":
        result = [o for o in battlefield if o.card.is_artifact]
    elif selector == "all_enchantments":
        result = [o for o in battlefield if o.card.is_enchantment]
    elif selector == "all_planeswalkers":
        result = [o for o in battlefield if getattr(o, "is_planeswalker", False)]
    elif selector == "all_permanents":
        result = list(battlefield)
    elif selector == "all_lands":
        result = [o for o in battlefield if o.card.is_land]
    else:
        result = []
    if filt:
        min_toughness = filt.get("min_toughness")
        if min_toughness is not None:
            result = [o for o in result if (o.toughness or 0) >= min_toughness]
        max_mv = filt.get("max_mana_value")
        if max_mv is not None:
            result = [o for o in result if o.card.converted_mana_cost <= max_mv]
        min_mv = filt.get("min_mana_value")
        if min_mv is not None:
            result = [o for o in result if o.card.converted_mana_cost >= min_mv]
        # "destroy all creatures with power 3 or greater" (Dusk // Dawn/The
        # Battle of Bywater-shaped) — the power-threshold sibling of
        # ``min_toughness`` above.
        min_power = filt.get("min_power")
        if min_power is not None:
            result = [o for o in result if (o.power or 0) >= min_power]
        max_power = filt.get("max_power")
        if max_power is not None:
            result = [o for o in result if (o.power or 0) <= max_power]
    return result


def _chosen_targets(targets: Optional[list[Any]], count: int, target: Any = None) -> list[Any]:
    """RULE 115.1a "up to N target(s)" resolution: only this effect's own
    ``count`` targets, off the front of a possibly-shared list — a stack
    item's ``targets`` list is shared by every effect on it, so a
    single-target effect (``count=1``, the default) must not swallow entries
    meant for something else sharing the same cast. Falls back to an
    explicit single ``target`` (a resolve-time pronoun/self reference) only
    when no shared list was supplied at all. Shared by `DestroyEffect`,
    `ExileEffect`, `ReturnToHandEffect`, `ReturnFromGraveyardEffect`,
    `TapEffect`, `AddCountersEffect` and `DealDamageEffect`, which otherwise
    each reimplemented this identically.
    """
    if targets:
        return targets[:count]
    return [target] if target is not None else []


class DestroyEffect(GameEffect):
    """Destroy a target permanent — or, with ``count`` > 1, every one of a
    fixed/"up to N" set of chosen target permanents (RULE 115.1a
    generalized to N>=2 — "destroy two target creatures"/"destroy up to two
    target artifacts and/or enchantments") — or, with ``selector`` set, a
    mass "destroy all X [with condition]" board wipe (RULE 601.2c, untargeted,
    same shape as `DealDamageEffect.selector`). ``can_be_regenerated=False``
    is Wrath of God's "They can't be regenerated." tail. ``max_mana_value``
    is Abrupt Decay-shaped "target nonland permanent with mana value 3 or
    less" — a target-offer-time cap (`targeting.TargetSpec.max_mana_value`),
    not a resolve-time check. ``creature_filter`` is the power/toughness/
    keyword quality filter (`targeting.TargetSpec.creature_filter`,
    "destroy target creature with power 4 or greater"/"…with flying"-shaped)
    — a different, orthogonal narrowing from ``filter`` above (which only
    ever applies to the untargeted ``selector`` mass-wipe path).

    ``distinct_controllers`` (Run Away Together/Protector of the Wastes-
    shaped "N target creatures/permanents controlled by **different
    players**") is `targeting.TargetSpec.distinct_controllers` — see its
    docstring; only meaningful with ``count >= 2``.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        optional: bool = False,
        count: int = 1,
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        can_be_regenerated: bool = True,
        color: Optional[str] = None,
        max_mana_value: Optional[int] = None,
        creature_filter: Optional[dict[str, Any]] = None,
        distinct_controllers: bool = False,
        exclude_created: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.selector = selector if selector in _MASS_DESTROY_SELECTORS else None
        self.filter = filter
        self.can_be_regenerated = can_be_regenerated
        #: "Create X tokens. If X is 5 or more, destroy all **other**
        #: creatures." (Martial Coup) — RULE 608.2's "the tokens" referent
        #: excluded from a mass wipe in the *same* resolution
        #: (`GameContext.created_objects`), the mirror image of
        #: `AttachEffect`'s ``target_kind="created"`` reading the same list.
        self.exclude_created = exclude_created
        if self.selector is None:
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, color=color,
                max_mana_value=max_mana_value, creature_filter=creature_filter,
                distinct_controllers=distinct_controllers,
            )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            excluded = set(context.created_objects) if self.exclude_created else ()
            for obj in _mass_selector_objects(context, self.selector, self.filter):
                if obj in excluded:
                    continue
                context.destroy(obj, can_be_regenerated=self.can_be_regenerated)
            return
        chosen = _chosen_targets(targets, self.target_spec.count, self.target)
        for target in chosen:
            context.destroy(target, can_be_regenerated=self.can_be_regenerated)


class RegenerateEffect(GameEffect):
    """Give a target permanent a regeneration shield (RULE 701.16).

    ``target_kind=None`` (unlike the default ``"creature"``) makes it act on
    the effect's own source with no player choice involved — "Regenerate
    ~."/"Regenerate this creature.", mirroring `TapEffect`'s self mode.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        creature_filter: Optional[dict] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = (
            TargetSpec(kind=target_kind, creature_filter=creature_filter)
            if target_kind is not None else None
        )

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None and self.target_spec is None:
            target = self.source
        if target is not None:
            context.regenerate(target)


class GainLifeEffect(GameEffect):
    """The effect's controller (or an explicitly given ``player``) gains
    ``amount`` life — untargeted by default.

    ``target_kind="player"`` (Abuna's Chant-shaped "target player gains N
    life") opts into a real RULE 115 target, mirroring `LoseLifeEffect`'s
    own ``target_kind``. Without it, this effect declares no `target_spec`
    of its own, so any ``targets`` passed to `apply` belong to a *different*
    effect on the same ability/spell (e.g. Deathrite Shaman's "Exile target
    creature card from a graveyard. You gain 2 life." — the exiled card,
    not a player) — reading `targets[0]` unconditionally would silently hand
    `RulesEngine.gain_life` a `GameObject` instead of a `Player`.
    """

    def __init__(
        self,
        amount: int = 0,
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        count_selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        self.count_selector = count_selector

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        amount = self.amount
        if self.count_selector and player is not None:
            from . import continuous  # avoid the continuous↔effects import cycle

            amount = continuous.count_selector(context.state, player.id, self.count_selector)
        context.gain_life(player, amount)


class PreventDamageEffect(GameEffect):
    """RULE 615: "Prevent all/the next N damage that would be dealt to you
    this turn" (Riot Control's spell-level "all"; Thought Lash's own
    repeatable "the next 1") — a one-shot effect that grants its own
    controller a turn-scoped damage-prevention shield, Regenerate-shaped:
    this class just triggers `RulesEngine.prevent_damage_to_player`, which
    builds+attaches the actual `ReplacementEffect` shield (unlike
    `RegenerateEffect`'s shield, this one lives on `Player.player_effects`,
    not a permanent's `replacement_effects` — nothing is being regenerated,
    the target is always the caster/activator, never chosen).

    ``amount="all"`` prevents every point of damage the player would take
    for the rest of the turn; an int prevents a cumulative bank of that
    many points total (Thought Lash's activated ability can be paid
    multiple times, each adding to the same turn's bank).

    PAR-15's targeted sibling ("prevent the next N damage that would be
    dealt this turn to any number of targets, divided as you choose" —
    Embolden/Remedy/Angel of Salvation) sets ``target_kind`` — the pool is
    then divided (RULE 601.2d-shaped, `DealDamageEffect(divided=True)`'s
    same as-evenly-as-possible split) among whichever targets were chosen
    and each gets its own `RulesEngine.prevent_damage_to_target` shield,
    rather than the single fixed "you" shield the untargeted shape above
    grants. ``amount_if_kicked`` is Pollen Remedy's own trailing "if this
    spell was kicked, prevent the next N damage this way instead" —
    an *override*, not an addition, so it's a param on this effect rather
    than a generic kicked-conditional wrapper (RULE 702.33b already covers
    the additive "if kicked, `<effect>`" shape via `ConditionalEffect`;
    this is the narrower override some cards use instead).
    """

    def __init__(
        self,
        amount: Union[int, str] = "all",
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        target: Any = None,
        count: int = 1,
        optional: bool = False,
        divided: bool = False,
        amount_if_kicked: Optional[Union[int, str]] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.amount_if_kicked = amount_if_kicked
        self.divided = divided
        self.target = target
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional, count=count)
            if target_kind is not None
            else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        kicker_count = getattr(self.source, "kicker_count", 0) or 0
        amount = self.amount_if_kicked if (self.amount_if_kicked is not None and kicker_count > 0) else self.amount
        if self.target_spec is None:
            player = _controller_of(self.source, context)
            if player is not None:
                context.prevent_damage_to_player(player, amount)
            return
        chosen = _chosen_targets(targets, self.target_spec.count, self.target)
        if not chosen:
            return
        if self.divided:
            total = amount if isinstance(amount, int) else 0
            base, extra = divmod(total, len(chosen))
            shares = [base + (1 if i < extra else 0) for i in range(len(chosen))]
        else:
            shares = [amount] * len(chosen)
        for target, share in zip(chosen, shares):
            if share == "all" or (isinstance(share, int) and share > 0):
                context.prevent_damage_to_target(target, share)


class PreventAllCombatDamageEffect(GameEffect):
    """RULE 615: "Prevent all combat damage that would be dealt this turn."
    (Fog) — deliberately a separate class from `PreventDamageEffect`
    rather than a third mode on it: that class's two modes both shield one
    resolved *recipient* (the caster, or a chosen target); this one has no
    recipient at all — every attacker's and every blocker's combat damage
    to *anyone* is prevented, for the rest of the turn, which is why it
    calls `RulesEngine.prevent_all_combat_damage_this_turn` instead of
    either of that class's per-recipient shield builders.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.prevent_all_combat_damage_this_turn(player)


class ExtraLandPlayEffect(GameEffect):
    """A one-shot "you may play N additional land(s) this turn" grant
    (Explore/Escape to the Wilds/Kiora's -1-shaped, RULE 305.2) — the
    resolve-time, single-turn sibling of the standing `"extra_land_drop"`
    `StaticAbility` a permanent like Exploration grants continuously
    (`game/continuous.py`'s `extra_land_plays_for`).

    Bumps the controller's `Player.extra_land_plays_this_turn` counter,
    which `GameEngine.can_play_land` adds to the per-turn cap alongside the
    standing static grant; `GameEngine.begin_turn` resets it to 0 each turn
    the same way `lands_played_this_turn` resets.
    """

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            player.extra_land_plays_this_turn += self.count


#: `LoseLifeEffect`'s mass-selector vocabulary ("each opponent loses N
#: life"/"each player loses N life", RULE 601.2c) — the same closed,
#: untargeted-group shape `DealDamageEffect`'s `_DAMAGE_SELECTORS` uses (no
#: "each_creature" here — life loss never targets a creature).
_LOSE_LIFE_SELECTORS: frozenset[str] = frozenset({"each_player", "each_opponent"})


class LoseLifeEffect(GameEffect):
    """A player loses ``amount`` life (RULE 118/119) — untargeted.

    ``selector="defending_player"`` (afflict, RULE 702.130) resolves the
    player dynamically at apply-time via `_defending_player_of`, since the
    same bound ability fires against a different defender each combat;
    a plain ``player``/target keeps the shape every other simple player
    effect (`GainLifeEffect`, `DiscardEffect`) already uses.
    ``selector="each_opponent"``/``"each_player"`` (RULE 601.2c) instead
    hits every matching player, the same mass-effect shape
    `DealDamageEffect.selector` uses for "~ deals N damage to each player".

    Like `GainLifeEffect`, the plain (no-selector) path never falls back to
    a shared ``targets`` list — this effect declares no `target_spec` of
    its own, so any ``targets`` passed to `apply` belong to a *different*
    effect in the same chain (Infernal Grasp's "Destroy target creature.
    You lose 2 life.", Deathrite Shaman's exile-then-drain ability, …).
    """

    def __init__(
        self,
        amount: int = 0,
        player: Any = None,
        selector: Optional[str] = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        player_id: Optional[str] = None,
        amount_from_trigger_event: Optional[str] = None,
        amount_from_life_gained_this_turn: bool = False,
        amount_from_burden_counters_on_self: bool = False,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.player = player
        #: "…you lose 1 life for each burden counter on The One Ring."
        #: Reads `GameObject.counters["burden"]` on this effect's own
        #: source, the `LoseLifeEffect` sibling of `DrawCardEffect`'s
        #: ``"burden_counters_on_self"`` count selector.
        self.amount_from_burden_counters_on_self = amount_from_burden_counters_on_self
        #: A specific player named by *id* rather than by object — the only
        #: form a serialized `EffectSpec` can carry (Professor Onyx's
        #: per-opponent "if you don't, they lose 3 life" branch, built fresh
        #: at answer time from spec data).
        self.player_id = player_id
        self.selector = selector
        # "Target player … loses 2 life" (Sign in Blood-shaped, sharing its
        # target with a sibling `DrawCardEffect` on the same spell) — opt-in
        # only, so every existing untargeted/selector caller keeps reading
        # no shared ``targets`` list at all (see the class docstring).
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None
        #: "Whenever you gain life, target opponent loses that much life."
        #: (Sanguine Bond-shaped) — the event field name (``"amount"``) to
        #: read off `GameContext.trigger_event` at resolution, the same
        #: "read this firing's own payload" idiom `AddManaEffect.
        #: amount_from_trigger_event` uses. Overrides ``amount`` when set.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "…loses life equal to the amount of life you gained this turn."
        #: (Gollum, Obsessed Stalker) — `GameState.life_gained_this_turn`,
        #: a *cumulative-this-turn* total rather than one firing's payload,
        #: so unlike `amount_from_trigger_event` this reads state, not the
        #: triggering event.
        self.amount_from_life_gained_this_turn = amount_from_life_gained_this_turn

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        amount = self.amount
        if self.amount_from_trigger_event:
            event = context.trigger_event
            amount = int((event or {}).get(self.amount_from_trigger_event) or 0)
        if self.amount_from_life_gained_this_turn:
            player = _controller_of(self.source, context)
            amount = context.state.life_gained_this_turn.get(getattr(player, "id", None), 0)
        if self.amount_from_burden_counters_on_self:
            counters = getattr(self.source, "counters", None) or {}
            amount = int(counters.get("burden", 0))
        if amount <= 0:
            return
        if self.selector in _LOSE_LIFE_SELECTORS:
            controller_id = getattr(self.source, "controller_id", None)
            for p in context.state.living_players():
                if self.selector == "each_opponent" and p.id == controller_id:
                    continue
                context.lose_life(p, amount)
            return
        player = self.player
        if player is None and self.player_id is not None:
            player = context.state.player_by_id(self.player_id)
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None and self.selector == "defending_player":
            player = _defending_player_of(self.source, context)
        if player is None:
            player = _controller_of(self.source, context)
        context.lose_life(player, amount)


class AddPlayerCountersEffect(GameEffect):
    """"[Player] get[s] N [kind] counters." (RULE 122 — only "rad", RULE
    728, in practice today) — the oracle-text-facing sibling of
    `RulesEngine.add_player_counters`. Same target_kind/selector split as
    `GainLifeEffect`/`LoseLifeEffect`: untargeted (the effect's controller)
    by default, ``target_kind="player"`` for a real RULE 115 target, or
    ``selector="each_player"``/``"each_opponent"``/``"defending_player"``
    for a mass/combat-relative recipient.

    ``selector="defending_player"`` resolves against the *attacking*
    object, which for an Aura/Equipment-hosted "whenever enchanted/equipped
    creature attacks, defending player gets ~" ability (Acquired Mutation)
    is ``self.source``'s *host*, not the Aura/Equipment itself — only the
    actual attacker gets `combat_defender` stamped on it by
    `declare_attackers` (RULE 506.4). Resolved here rather than widening
    the shared `_defending_player_of` helper, since every existing caller
    (afflict) is already the attacking creature itself.
    """

    def __init__(
        self,
        amount: Any = 0,
        kind: str = "rad",
        player: Any = None,
        selector: Optional[str] = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.kind = kind
        self.player = player
        self.selector = selector
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector in ("each_player", "each_opponent"):
            controller_id = getattr(self.source, "controller_id", None)
            for p in context.state.living_players():
                if self.selector == "each_opponent" and p.id == controller_id:
                    continue
                context.add_player_counters(p, self.amount, self.kind, source=self.source)
            return
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None and self.selector == "defending_player":
            host = self.source
            attached_to = getattr(host, "attached_to", None)
            if attached_to is not None:
                resolved = context.state.find_object(attached_to)
                if resolved is not None:
                    host = resolved
            player = _defending_player_of(host, context)
        if player is None:
            player = _controller_of(self.source, context)
        if player is not None:
            context.add_player_counters(player, self.amount, self.kind, source=self.source)


class LoseAllPlayerCountersEffect(GameEffect):
    """"[Player] loses all [kind] counters." (RULE 122's removal sibling —
    Survivor's Med Kit's "Target player loses all rad counters.") Reads the
    live count at apply time and removes exactly that many via
    `RulesEngine.add_player_counters`'s existing non-positive-amount path
    (bypasses RULE 616.1 replacements, same as any other counter removal).
    """

    def __init__(
        self,
        kind: str = "rad",
        player: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.player = player
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None:
            player = _controller_of(self.source, context)
        if player is None:
            return
        current = player.counters.get(self.kind, 0)
        if current > 0:
            context.add_player_counters(player, -current, self.kind, source=self.source)


class DiesGrantsRadCountersEqualPowerEffect(GameEffect):
    """"When this creature dies, each opponent gets a number of rad
    counters equal to its power." (Feral Ghoul-shaped) — an atomic effect
    reading the dying creature's own last-known power (RULE 400.7) at
    apply time, the same "read the characteristic directly rather than
    compose two effects" shape `ExileGainLifeToControllerEffect` uses for
    "exile ~; you gain life equal to its power" — a generic
    `AddPlayerCountersEffect` has no way to receive a dynamic amount from
    its own triggering object.
    """

    def __init__(self, kind: str = "rad", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.kind = kind

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        power = getattr(self.source, "power", 0) or 0
        if power <= 0:
            return
        controller_id = getattr(self.source, "controller_id", None)
        for p in context.state.living_players():
            if p.id == controller_id:
                continue
            context.add_player_counters(p, power, self.kind, source=self.source)


class SacrificeEffect(GameEffect):
    """A player sacrifices up to ``count`` permanents matching ``what``
    (RULE 701.17) — untargeted; a real RULE 601.2c-style choice via
    `RulesEngine.sacrifice`/`request_choose_objects`, not an auto-pick
    (`GameEngine._sacrifice_candidate`'s non-interactive convention is a
    *cost*-payment concern, a synchronous call that can't pause for a
    chooser — this is an effect resolving, which can).

    ``selector="defending_player"`` (annihilator, RULE 702.86) resolves the
    player dynamically at apply-time, the same way `LoseLifeEffect` does;
    ``selector="each_opponent"`` runs the sacrifice once per opponent
    (Professor Onyx's −3).

    ``greatest_power`` narrows the choice to "a creature with the greatest
    power among creatures that player controls" (Professor Onyx again) —
    still an auto-pick (`max()`) among the tied leaders rather than routed
    through the chooser, since only a tie among several actually leaves
    anything to decide and no shipped card sacrifices more than one this
    way (recomputing "greatest" between interactive picks isn't modeled).
    """

    def __init__(
        self,
        count: int = 1,
        what: str = "permanent",
        player: Any = None,
        selector: Optional[str] = None,
        greatest_power: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.what = what
        self.player = player
        self.selector = selector
        self.greatest_power = greatest_power

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector == "each_opponent":
            controller_id = getattr(self.source, "controller_id", None)
            for opponent in context.state.living_players():
                if opponent.id != controller_id:
                    self._sacrifice_one(context, opponent)
            return
        player = self.player or (targets[0] if targets else None)
        if player is None and self.selector == "defending_player":
            player = _defending_player_of(self.source, context)
        if player is None:
            return
        self._sacrifice_one(context, player)

    def _sacrifice_one(self, context: GameContext, player: "Player") -> None:
        if not self.greatest_power:
            context.sacrifice(player, self.what, self.count)
            return
        creatures = [
            o for o in context.state.permanents_controlled_by(player.id) if o.is_creature
        ]
        for _ in range(self.count):
            if not creatures:
                return
            victim = max(creatures, key=lambda o: o.power or 0)
            creatures.remove(victim)
            context.put_into_graveyard(victim)  # RULE 701.16c: sacrifice


class SacrificeSelfEffect(GameEffect):
    """"Sacrifice ~."/"Sacrifice this enchantment." (Dress Down/Underworld
    Breach-shaped standing end-step self-sac) — the effect's own source
    sacrifices itself, no player choice or RULE 115 target involved (RULE
    701.17). Uses `RulesEngine.put_into_graveyard` rather than `destroy`
    (RULE 701.16c: sacrifice isn't destruction, so it can't be regenerated),
    the same distinction `GameEngine._pay_activation_cost`'s own sacrifice
    cost-payment already makes.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.put_into_graveyard(self.source)


class SacrificeUnlessPayEffect(GameEffect):
    """"Sacrifice ~ unless you pay `<cost>`." (RULE 701.17 + an "unless"
    payment) — the single most common upkeep-trigger body on old cards
    (Arcades Sabboth, Breeding Pit, Child of Gaea, Kuro; Aura Flux/Coral Net
    grant it onto another permanent).

    ``cost`` is the printed cost *text* ("{G}{G}", "1 life", "a card"),
    parsed by `costs.parse_activation_cost` at resolution into the same
    `ActivationCost` an activated ability's cost uses — that's what makes
    the whole real vocabulary these cards print (mana / pay N life /
    discard a card / sacrifice another permanent) work without a bespoke
    cost model. Resolution itself is `RulesEngine.request_sacrifice_unless_
    pay`, which reuses ward's pay-or-lose-it choice machinery.
    """

    def __init__(self, cost: str = "", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.cost_text = str(cost or "")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import parse_activation_cost  # function-scoped: costs↔effects cycle

        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        if player is None:
            return
        cost = parse_activation_cost(self.cost_text)
        if cost.is_free:
            # `parse_activation_cost` returns a *free* cost for text it
            # doesn't recognize rather than raising. Honouring that here
            # would silently mean "pay nothing to keep it" — do nothing at
            # all instead. (The parser front end only claims cost shapes it
            # can express, so this is a belt-and-braces guard for a
            # hand-authored entry, not a path real oracle text reaches.)
            return
        context.engine.request_sacrifice_unless_pay(player, cost, source)


class EachPlayerPayOrEffect(GameEffect):
    """RULE 101.4's APNAP mass "unless" (PAR-13 — "Each player loses N life
    unless they discard a card."/"...unless they sacrifice a creature,
    artifact, or land of their choice." — Bellowing Mauler/Lim-Dûl's Hex/
    Tomb of Annihilation's own two dungeon rooms), the *mass* sibling of
    `SacrificeUnlessPayEffect`: every living player is asked in turn order,
    and ``effects`` lands on whoever doesn't (or can't) pay — never the
    ability's own controller, unlike that class's single fixed subject.

    ``cost`` is printed cost text exactly like `SacrificeUnlessPayEffect`'s
    own; ``effects`` are serialized `EffectSpec` dicts applied with the
    declining player as the sole target (`RulesEngine.
    request_each_player_pay_or` passes ``targets=[player]`` through to
    `request_pay_cost_then`), so a spec here should carry a matching
    ``target_kind`` (``"player"`` for `lose_life`/`discard`/etc.) rather
    than relying on an untargeted default.
    """

    def __init__(
        self,
        cost: str = "",
        effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost or "")
        self.inner_specs = list(effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import parse_activation_cost  # function-scoped: costs↔effects cycle

        cost = parse_activation_cost(self.cost_text)
        if cost.is_free:
            return  # see SacrificeUnlessPayEffect's identical guard
        context.engine.request_each_player_pay_or(cost, self.inner_specs, self.source)


class CounterSpellEffect(GameEffect):
    """Counter a target spell on the stack (RULE 701.5).

    ``noncreature``/``card_types``/``mana_value`` narrow *which* spells are
    legal targets in the first place (RULE 601.2c/115 — "counter target
    noncreature spell", "… target instant or sorcery spell", "… target spell
    with mana value N"), folded into `target_spec.spell_filter` and enforced
    by `targeting.legal_targets`. ``unless_pays`` (RULE 601's "Mana Leak"
    template — "counter target spell unless its controller pays {N}") is a
    resolve-time condition instead: the target's controller gets an
    interactive choice, handled by `RulesEngine.counter_unless_pays`.
    """

    def __init__(
        self,
        target: Any = None,
        unless_pays: Optional[str] = None,
        noncreature: bool = False,
        card_types: Optional[list[str]] = None,
        mana_value: Optional[int] = None,
        color: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.unless_pays = unless_pays
        spell_filter: dict[str, Any] = {}
        if noncreature:
            spell_filter["noncreature"] = True
        if card_types:
            spell_filter["card_types"] = list(card_types)
        if mana_value is not None:
            spell_filter["mana_value"] = mana_value
        if color:
            spell_filter["color"] = color
        self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.counter(target, unless_pays=self.unless_pays, source=self.source)


class CopySpellEffect(GameEffect):
    """Copy a target spell on the stack (RULE 707.10 — Dualcaster Mage/Flare
    of Duplication/Reiterate "copy target instant or sorcery spell").

    ``card_types`` narrows which spells are legal targets (default instant/
    sorcery), folded into ``target_spec.spell_filter`` exactly as
    `CounterSpellEffect` does. ``count`` copies are made (Flare of
    Duplication makes one; a hypothetical "copy it twice" would set 2). The
    copy is controlled by *this effect's source's controller* (RULE 707.10c
    — the copier), created by `RulesEngine.copy_spell`. "You may choose new
    targets for the copy" is a legal-but-optional refinement (RULE 707.10c);
    this MVP keeps the original's targets (the default outcome), which every
    real card in scope allows — a genuine new-target choice would open a
    `pending_choice`, deferred until a card needs it.
    """

    def __init__(
        self,
        card_types: Optional[list[str]] = None,
        count: int = 1,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        spell_filter: dict[str, Any] = {}
        if card_types:
            spell_filter["card_types"] = list(card_types)
        self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        if target is None:
            return
        controller_id = getattr(self.source, "controller_id", None)
        if controller_id is None:
            return
        context.copy_spell(target, controller_id, self.count)


class CounterCreateTokenEffect(GameEffect):
    """"Counter target spell. Its controller creates a token." (Swan Song,
    Strix Serenade, An Offer You Can't Refuse) — the stack-side sibling of
    `DestroyCreateTokenEffect`: the token goes to the *countered spell's own
    controller* (the player being answered), read off the stack item before
    it's countered, the same "read something off the target, then act" shape.

    ``noncreature``/``card_types`` narrow which spells are legal targets,
    folded into ``target_spec.spell_filter`` exactly as `CounterSpellEffect`
    does; ``power``/``toughness``/``colors``/``subtypes``/``token_name``
    describe the token exactly as `DestroyCreateTokenEffect`'s do.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        noncreature: bool = False,
        card_types: Optional[list[str]] = None,
        power: Optional[int] = None,
        toughness: Optional[int] = None,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        token_name: Optional[str] = None,
        count: int = 1,
        keywords: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        spell_filter: dict[str, Any] = {}
        if noncreature:
            spell_filter["noncreature"] = True
        if card_types:
            spell_filter["card_types"] = list(card_types)
        self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.token_name = token_name or (subtypes[0] if subtypes else "Token")
        self.count = count
        self.keywords = keywords or []

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..services.token_database import synthesize_token_card

        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.counter(target, source=self.source)
        if controller_id is None:
            return
        card = synthesize_token_card(
            self.token_name, power=self.power, toughness=self.toughness,
            colors=self.colors, subtypes=self.subtypes, keywords=self.keywords,
        )
        context.create_token(controller_id, card, self.count)


class WardEffect(GameEffect):
    """A ward triggered ability's own resolution body (RULE 702.21a):
    "counter that spell or ability unless that player pays [cost]."

    Unlike `CounterSpellEffect`/`CounterSpellEffect.unless_pays` (where the
    *target's controller* decides whether to pay — RULE 601's "Mana Leak"
    template), ward's decision belongs to the *caster* of the countered
    item. ``item``/``caster_id``/``cost`` are fixed the moment the warded
    permanent became a target (RULE 603.3a's trigger-time lock-in), not
    re-derived here — so even if the caster or the item's legality changes
    before this resolves, the ability still asks the right player about the
    right item (RULE 603.6/603.10 "look back in time").

    Never built via `EffectRegistry` — always constructed directly by
    `RulesEngine.check_ward`, one instance per warded target, each wrapped
    in its own `StackItem` placed on top of the triggering spell/ability so
    normal priority-passing carries it (RULE 603.3), rather than resolved
    inline as a synchronous choice.
    """

    def __init__(
        self,
        item: Any,
        caster_id: str,
        cost: Any,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.item = item
        self.caster_id = caster_id
        self.cost = cost

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        ability_controller_id = self.source.controller_id if self.source is not None else None
        context.engine.resolve_ward_effect(
            self.item, self.caster_id, self.cost, ability_controller_id=ability_controller_id
        )


class CantBeCounteredEffect(GameEffect):
    """Marker: "This spell can't be countered." (RULE 118-area).

    Bound like any other one-shot effect — via `spell_effect` on an instant/
    sorcery's own body, or `static` on a permanent's standing line — and so
    lands in ``obj.spell_effects``/``obj.static_effects`` respectively
    (`game/effect_binder.py`'s ordinary dispatch, no special-casing needed).
    It carries no continuous behaviour: `continuous.recompute` only ever
    reads `StaticAbility` instances off `static_effects` (this isn't one), and
    a spell's own resolution just calls `apply()` like every other effect in
    its list. The only consumer is `RulesEngine._is_cant_be_countered`, which
    scans both lists for this marker *before* the object would otherwise
    leave the stack — the one moment "can't be countered" actually matters.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None


class MillEffect(GameEffect):
    """Put the top ``count`` cards of a player's library into their graveyard.

    Untargeted ("Mill three cards.") mills the effect's controller; a
    ``target_kind`` of ``"player"`` mills a chosen player (RULE 701.13).
    """

    def __init__(
        self,
        count: int = 1,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        if target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is not None:
            player = targets[0] if targets else None
        else:
            player = context.active_player
        if player is not None:
            context.mill(player, self.count)


class ExileEffect(GameEffect):
    """Exile a target permanent (RULE 406 / 701.5a) — or, with ``count`` >
    1, every one of a fixed/"up to N" set of chosen targets (RULE 115.1a
    generalized to N>=2 — "exile up to two target creatures you control") —
    or, with ``selector`` set, a mass "exile all X" board wipe (RULE
    601.2c, untargeted — Farewell-shaped), the same shape
    `DestroyEffect.selector` uses.

    ``target_kind=None`` (unlike the default ``"permanent"``) is the *self*
    form — "Exile ~."/"Exile this spell/card." (Teferi's Protection/
    Mnemonic Betrayal-shaped trailing self-exile) — no RULE 115 target at
    all, mirroring `TapEffect`/`RegenerateEffect`'s own self mode.

    ``remember=True`` additionally stamps the exiled target's own
    ``instance_id`` onto this ability's own source (`GameObject.
    linked_exile_id`) — the O-Ring-shaped "when this leaves the
    battlefield, return the exiled card" half (`ReturnLinkedExileEffect`)
    reads it back later, arbitrarily many turns on. Only meaningful with a
    single (``count=1``) real target — a mass/selector exile has nothing
    single to remember.

    ``distinct_controllers`` (Protector of the Wastes-shaped "up to two
    target artifacts and/or enchantments controlled by **different
    players**") is `targeting.TargetSpec.distinct_controllers` — see its
    docstring; only meaningful with ``count >= 2``.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "permanent",
        optional: bool = False,
        count: int = 1,
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        remember: bool = False,
        creature_filter: Optional[dict[str, Any]] = None,
        distinct_controllers: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.selector = selector if selector in _MASS_DESTROY_SELECTORS else None
        self.filter = filter
        self.remember = remember
        self.target_spec: Optional[TargetSpec] = None
        if self.selector is None and target_kind is not None:
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, creature_filter=creature_filter,
                distinct_controllers=distinct_controllers,
            )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            for obj in _mass_selector_objects(context, self.selector, self.filter):
                context.exile(obj)
            return
        if self.target_spec is None:
            target = (targets[0] if targets else None) or self.target or self.source
            if target is not None:
                context.exile(target)
            return
        chosen = _chosen_targets(targets, self.target_spec.count, self.target)
        for target in chosen:
            if self.remember and self.source is not None:
                self.source.linked_exile_id = target.instance_id
            context.exile(target)


class ExileGainLifeToControllerEffect(GameEffect):
    """Exile a target creature; its controller gains life equal to its power
    (RULE 701.5a / 701.5.f-adjacent — Swords to Plowshares-shaped).

    A single atomic effect rather than a separate `ExileEffect` +
    `GainLifeEffect`: the life total depends on the *same* target's power,
    read before it leaves the battlefield, and — as `GainLifeEffect`'s own
    docstring explains — that effect deliberately never reads a shared
    ``targets`` list, so composing two effects here couldn't pass the power
    along anyway. Also handles the target's *own* controller (not
    necessarily the caster) gaining the life, unlike every other life-gain
    effect in this file, which defaults to the effect's controller.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        power = target.power or 0
        controller_id = getattr(target, "controller_id", None)
        context.exile(target)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return
        if power > 0:
            context.gain_life(player, power)


class ExileAllGraveyardsEffect(GameEffect):
    """"Exile all graveyards." (RULE 406 mass exile, Farewell-shaped) —
    every card in every player's graveyard, untargeted."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for player in context.players:
            for obj in list(player.graveyard):
                context.exile(obj)


class ExileGraveyardCardCounterIfPermanentEffect(GameEffect):
    """"{W}: Exile target card from a graveyard. If it was a permanent
    card, put a +1/+1 counter on this permanent." (Lion Sash) — a single
    atomic effect since the counter is conditional on *what* was exiled,
    not a separately-modeled clause."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "any_graveyard_card",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        card = target.card
        is_permanent = bool(
            card.is_creature or card.is_artifact or card.is_enchantment
            or card.is_land or getattr(card, "is_planeswalker", False)
        )
        context.exile(target)
        if is_permanent and self.source is not None:
            context.add_counters(self.source, 1, "+1/+1", source=self.source)


class ExileGraveyardCreaturesGainLifeEffect(GameEffect):
    """"Exile all creature cards from target player's graveyard. You gain 3
    life for each card exiled this way." (Crypt Incursion)."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
        life_per_card: int = 3,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.life_per_card = life_per_card
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        creatures = [o for o in list(player.graveyard) if o.card.is_creature]
        for obj in creatures:
            context.exile(obj)
        if creatures:
            controller = _controller_of(self.source, context)
            if controller is not None:
                context.gain_life(controller, self.life_per_card * len(creatures))


class ExileTargetGraveyardEffect(GameEffect):
    """"Exile target player's graveyard." (Bojuka Bog/Tormod's Crypt-shaped)
    — every card in that one graveyard, untargeted per-card unlike
    `_exile_from_graveyard`'s single-card family; the untargeted "every
    graveyard" sibling is `ExileAllGraveyardsEffect` above."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        for obj in list(player.graveyard):
            context.exile(obj)


class DestroyLoseLifeEqualManaValueEffect(GameEffect):
    """"Destroy target creature or enchantment an opponent controls. You
    lose life equal to that permanent's mana value." (Feed the Swarm) — a
    single atomic effect since the life total depends on the target's own
    mana value, read before it leaves the battlefield, mirroring
    `ExileGainLifeToControllerEffect`'s "read the target's own
    characteristic, then move it" shape. ``target_kind="permanent"``
    (broader than "creature or enchantment an opponent controls" — no
    target kind unions two card types *and* restricts to opponents at
    once) is the same documented simplification `_TARGET_ROWS`'s "target
    artifact or enchantment" → ``"permanent"`` row already uses elsewhere;
    the life-loss always hits the *caster*, not the target's controller,
    unlike `ExileGainLifeToControllerEffect`.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        mana_value = target.card.converted_mana_cost
        context.destroy(target)
        controller = _controller_of(self.source, context)
        if controller is not None and mana_value:
            context.lose_life(controller, mana_value)


class ExileCreateTokenEffect(GameEffect):
    """"Exile target artifact or creature. Its controller creates a 4/4
    blue and red Elemental creature token." (Resculpt) — a single atomic
    effect: the token goes to the *exiled permanent's own controller*
    (unlike `CreateTokenEffect`, which always creates under the effect's
    own source's controller), so the target's controller must be read
    before/alongside exiling it, the same "read something off the target,
    then act" shape `ExileGainLifeToControllerEffect` uses for life gain
    instead of a token.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        power: Optional[int] = None,
        toughness: Optional[int] = None,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        token_name: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.token_name = token_name or (subtypes[0] if subtypes else "Token")

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..services.token_database import synthesize_token_card

        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.exile(target)
        if controller_id is None:
            return
        card = synthesize_token_card(
            self.token_name, power=self.power, toughness=self.toughness,
            colors=self.colors, subtypes=self.subtypes,
        )
        context.create_token(controller_id, card, 1)


class DestroyCreateTokenEffect(GameEffect):
    """"Destroy target permanent. Its controller creates a 3/3 green Beast
    creature token." (Beast Within) — `ExileCreateTokenEffect`'s destroy-
    instead-of-exile sibling: the token still goes to the *destroyed
    permanent's own controller*, read before it leaves the battlefield,
    same "read something off the target, then act" shape.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        power: Optional[int] = None,
        toughness: Optional[int] = None,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        token_name: Optional[str] = None,
        can_be_regenerated: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.token_name = token_name or (subtypes[0] if subtypes else "Token")
        self.can_be_regenerated = can_be_regenerated

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..services.token_database import synthesize_token_card

        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.destroy(target, can_be_regenerated=self.can_be_regenerated)
        if controller_id is None:
            return
        card = synthesize_token_card(
            self.token_name, power=self.power, toughness=self.toughness,
            colors=self.colors, subtypes=self.subtypes,
        )
        context.create_token(controller_id, card, 1)


class DestroyGainLifeToControllerEffect(GameEffect):
    """"Destroy target artifact or enchantment. Its controller gains 4
    life." (Nature's Claim-shaped) — a fixed life amount, unlike
    `ExileGainLifeToControllerEffect`'s "equal to its power"; still a single
    atomic effect since the life goes to the *target's own controller*
    (read before it leaves the battlefield), not the caster.
    ``target_kind="permanent"`` (broader than "artifact or enchantment" — no
    target kind unions two card types) is the same documented `_TARGET_
    ROWS` simplification `DestroyLoseLifeEqualManaValueEffect` already uses.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        amount: int = 0,
        can_be_regenerated: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)
        self.amount = amount
        self.can_be_regenerated = can_be_regenerated

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.destroy(target, can_be_regenerated=self.can_be_regenerated)
        if controller_id is None or not self.amount:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return
        context.gain_life(player, self.amount)


class GainControlUntilEndOfTurnEffect(GameEffect):
    """"Gain control of target permanent until end of turn. Untap that
    permanent. It gains haste until end of turn." (RULE 108.4-adjacent —
    Zealous Conscripts/Coercive Recruiter-shaped) — a single atomic effect
    bundling the control change, the untap, and the haste grant (every real
    printed instance of this exact clause pairs all three on the *same*
    target), rather than composing 3 separate targeting effects that would
    each need their own copy of the shared target (the "two targeting
    effects double-prompt" reason `TargetPlayerDrawLoseLifeEffect`'s
    docstring gives — no plain `pump`/keyword-grant effect can reach the
    exact object this one just changed control of without `target_groups`
    machinery no real card here needs). Reverts control automatically at
    the next cleanup (`GameEngine._step_cleanup`, `GameObject.control_
    change_until_eot` remembers the original controller) — the haste grant
    is a `temp_keywords` entry, cleared at that same cleanup, matching
    "until end of turn" exactly. RULE 302.6's own "summoning sickness
    resets under a new controller" isn't separately modeled, since the
    haste grant makes the distinction unobservable either way. Doesn't move
    the object zones at all (unlike `blink`), so counters/attachments/
    damage marked all carry over exactly as the permanent itself would
    expect.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        haste: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)
        self.haste = haste

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller = _controller_of(self.source, context)
        if controller is None or target.controller_id == controller.id:
            return
        if target.control_change_until_eot is None:
            target.control_change_until_eot = target.controller_id
        target.controller_id = controller.id
        context.set_tapped(target, tapped=False)
        if self.haste:
            target.temp_keywords.add("haste")
        context.recompute()


class ReturnLinkedExileEffect(GameEffect):
    """"When this leaves the battlefield, return the exiled card to the
    battlefield under its owner's control." (Leonin Relic-Warder/O-Ring-
    shaped) — the return half of an `ExileEffect(remember=True)` pair:
    reads the linked card's ``instance_id`` off this ability's own source
    (stamped by the earlier ETB exile, survives however long the card
    stays exiled) rather than a RULE 115 target — nothing was ever chosen
    here, "the exiled card" is a fixed reference. A no-op if nothing is
    currently linked (the "may exile" ETB was declined) or the linked card
    already left exile some other way (bounced back by a third effect,
    etc.).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        linked_id = getattr(self.source, "linked_exile_id", None)
        self.source.linked_exile_id = None
        if linked_id is None:
            return
        card_obj = context.state.find_object(linked_id)
        if card_obj is None or card_obj.zone != Zone.EXILE:
            return
        context.return_from_graveyard(card_obj, "battlefield")


class ExileLibraryEffect(GameEffect):
    """"Exile all cards from your library." (Paradigm Shift-shaped) — an
    untargeted, hidden-zone-to-exile mass move: a library's contents are
    never legal RULE 115 targets, and `ExileEffect.selector`'s mass-board-
    wipe vocabulary only ever reads the *battlefield*, so this is its own
    effect rather than a reused selector.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for obj in list(player.library):
            context.exile(obj)


class ShuffleGraveyardIntoLibraryEffect(GameEffect):
    """"Shuffle your graveyard into your library." (RULE 701.20) — the
    graveyard-only sibling of `RulesEngine.shuffle_hand_and_graveyard_
    into_library`'s "hand AND graveyard" wheel template; reused wherever
    only the graveyard moves (Paradigm Shift).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for obj in list(player.graveyard):
            player.remove_from_zone(obj, Zone.GRAVEYARD)
            player.add_to_zone(obj, Zone.LIBRARY)
        context.shuffle_library(player)


class GraveyardToLibraryBottomRandomEffect(GameEffect):
    """"Up to one target player puts all the cards from their graveyard on
    the bottom of their library in a random order." (Endurance-shaped) —
    RULE 701.20-adjacent; unlike a plain `shuffle_library` call (which
    randomizes the *whole* library), this only randomizes the moved batch's
    own relative order among themselves before appending it to the bottom,
    leaving the existing library order above them untouched.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        moved = list(player.graveyard)
        if not moved:
            return
        random.shuffle(moved)
        for obj in moved:
            player.remove_from_zone(obj, Zone.GRAVEYARD)
        for obj in moved:
            player.library.insert(0, obj)
            obj.zone = Zone.LIBRARY


class ReturnToHandDrawIfControlledEffect(GameEffect):
    """"Return target nonland permanent to its owner's hand. If you
    controlled that permanent, draw a card." (Geistwave-shaped) — a single
    atomic effect: the draw is conditioned on the target's own controller,
    read *before* it leaves the battlefield, mirroring
    `ExileGainLifeToControllerEffect`'s "read something off the target,
    then act" shape (composing two separate `EffectSpec`s here couldn't
    check the target's controller after `ReturnToHandEffect` already moved
    it, the same reason that effect's docstring gives for not splitting its
    own life-gain out).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "nonland_permanent",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller = _controller_of(self.source, context)
        you_controlled_it = controller is not None and target.controller_id == controller.id
        context.return_to_hand(target)
        if you_controlled_it and controller is not None:
            context.draw(controller, 1)


class GrantFlashUntilEndOfTurnEffect(GameEffect):
    """"You may cast spells this turn as though they had flash." (Borne
    Upon a Wind-shaped) — stamps `GameState.temp_flash_until_turn` for the
    effect's controller, consulted by `GameEngine.can_cast`'s sorcery-speed
    timing gate; naturally expires once the turn number advances, no
    cleanup-step bookkeeping needed (unlike the `temp_*` `GameObject`
    fields `_step_cleanup` clears).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.state.temp_flash_until_turn[player.id] = context.state.turn_number


class ExileControllerSearchesBasicLandEffect(GameEffect):
    """"Exile target creature you don't control. For each creature exiled
    this way, its controller searches their library for a basic land
    card. Those players put those cards onto the battlefield tapped, then
    shuffle." (Winds of Abandon, single-target cast — Overload's "each
    opponent" rewrite isn't modeled, see the catalogue entry) — the search
    is offered to the *exiled creature's own controller*, not the caster,
    the same target-controller resolution `ExileCreateTokenEffect` uses.
    ``target_kind="creature"`` (broader than "you don't control" — no
    target kind carries an ownership exclusion yet) is a documented
    simplification, mirroring `ExileControllerSearchesBasicLandEffect`'s
    siblings elsewhere in this file.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = getattr(target, "controller_id", None)
        context.exile(target)
        if controller_id is None:
            return
        try:
            player = context.state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return
        context.request_search(player, {"basic": True}, "battlefield_tapped", 1, False)


class ReturnTopGraveyardCreatureWithHasteEffect(GameEffect):
    """Return the top creature card of your graveyard to the battlefield;
    that creature gains haste until end of turn (Corpse Dance). A single
    atomic effect, not `ReturnFromGraveyardEffect` (a RULE 115 *target*)
    plus a separate haste grant: the "top card" pick is untargeted/
    positional (the graveyard's own insertion order — the most recently
    added card is "on top"), and "that creature" refers to the exact object
    this same effect just returned — no shared targets-list slot for a
    second effect to reach it, the same "read/act on what I just did" shape
    `LivingWeaponEffect` uses for its own token-then-attach.

    ``delayed_exile_step`` is Corpse Dance's trailing "Exile it at the
    beginning of the next end step." — armed here rather than as a separate
    spec effect for the same "that creature" reason: `CreateDelayedTrigger
    Effect` bakes its targets in at arm time, and only *this* effect knows
    which object was returned. ``scope="any"`` matches "the **next** end
    step", whoever's turn it is.
    """

    def __init__(
        self,
        delayed_exile_step: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.delayed_exile_step = delayed_exile_step

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..models.game_state import DelayedTrigger

        player = _controller_of(self.source, context)
        if player is None:
            return
        creature = next((o for o in reversed(player.graveyard) if o.card.is_creature), None)
        if creature is None:
            return
        context.return_from_graveyard(creature, "battlefield")
        creature.temp_keywords.add("haste")
        if self.delayed_exile_step:
            context.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=player.id,
                    step=self.delayed_exile_step,
                    scope="any",
                    effects=[ExileEffect(target_kind=None, source=self.source)],
                    targets=[creature],
                    description=f"{creature.name}: im nächsten Endsegment exilieren",
                )
            )
        context.recompute()


class TargetPlayerDrawLoseLifeEffect(GameEffect):
    """"Target player draws N cards and loses M life." (Sign in Blood-shaped)
    — a single atomic effect over one shared target, since two independent
    `DrawCardEffect`/`LoseLifeEffect` objects each carrying their own
    ``target_kind`` would offer *two* separate target choices instead of
    one (docs/11 §5's "at most one targeting effect per ability" limit)."""

    def __init__(
        self,
        draw_count: int = 1,
        life_loss: int = 0,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "player",
    ) -> None:
        super().__init__(source)
        self.draw_count = draw_count
        self.life_loss = life_loss
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = (targets[0] if targets else None) or self.target
        if player is None:
            return
        context.draw(player, self.draw_count)
        context.lose_life(player, self.life_loss)


class CounterAndFirstStrikeEffect(GameEffect):
    """"Put a +1/+1 counter on up to one target creature. It gains first
    strike until end of turn." (The Wandering Emperor's +1) — a single
    atomic effect over one shared target, the same "two targeting effects
    would double-prompt" reason `TargetPlayerDrawLoseLifeEffect` exists."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        context.add_counters(target, 1, "+1/+1", source=self.source)
        target.temp_keywords.add("first_strike")
        context.recompute()


class PeekTopLandBattlefieldTappedEffect(GameEffect):
    """"Look at the top card of your library. If it's a land card, you may
    put it onto the battlefield tapped." (Explorer's Scope) — an "impulse
    peek", distinct from Sword of the Animist's own unconditional library
    *search* for a basic land."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        top = player.library[-1]
        if top.card.is_land:
            context.engine._put_searched_card(player, top, "battlefield_tapped")


class CreateTokenMayAttachEquipmentEffect(GameEffect):
    """Create a token, then optionally attach a *targeted* Equipment you
    control to it (Nahiri, Heir of the Ancients' +1) — the attach target is
    a real RULE 115 choice (unlike Living Weapon's own token, which always
    self-attaches), so this carries a `target_spec` the way `AttachEffect`
    does, just resolving onto the token this same effect just created
    rather than the effect's own source.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "equipment_you_control",
        optional: bool = True,
        token_name: str = "token",
        power: int = 1,
        toughness: int = 1,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)
        self.token_name = token_name
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        from ..services.token_database import synthesize_token_card

        card = synthesize_token_card(
            self.token_name, power=self.power, toughness=self.toughness,
            colors=self.colors, subtypes=self.subtypes,
        )
        tokens = context.engine.create_token(self.source.controller_id, card)
        if not tokens:
            return
        equipment = targets[0] if targets else self.target
        if equipment is not None:
            context.engine.attach_to_target(equipment, tokens[0])


class ReturnToHandEffect(GameEffect):
    """Return a target permanent to its owner's hand (RULE 701.3 "return").

    ``target_kind`` is usually ``"creature"``/``"permanent"``/``"any"`` (a
    plain "return target X to its owner's hand"), or a controller-restricted
    kind (``"land_you_control"``/``"creature_you_control"``) for a
    non-"target" resolve-time choice among the controller's own permanents —
    a bounce land's "return a land you control to its owner's hand" — see
    `targeting.legal_targets`. ``count`` > 1 targets several independent
    objects (RULE 115.1a generalized to N>=2, the same shape
    `DestroyEffect.count` uses) — "return two target creatures to their
    owners' hands".

    ``distinct_controllers`` (Run Away Together's "choose two target
    creatures controlled by **different players**. Return those creatures
    to their owners' hands.") is `targeting.TargetSpec.distinct_controllers`
    — see its docstring; only meaningful with ``count >= 2``.

    ``previous_subject=True`` (PAR-1) is Run Away Together's own two-sentence
    "choose N target X [constraint]. Verb **those** [referent]s." shape — a
    different, indirect-referent grammar from the single-sentence "destroy/
    exile N target X controlled by different players" `handlers.
    _MULTI_TARGET_DISTINCT_CONTROLLERS` claims: the *targets* are announced
    by a preceding `ChooseTargetsEffect` (RULE 601.2c, "choose N target
    creatures…") and read back here from `GameContext.previous_targets`
    (the same pronoun idiom `FightEffect`'s ``previous_target``/
    ``GrantUntilEffect.previous_subject`` use) instead of opening a fresh
    RULE 115 choice of its own — mutually exclusive with ``target_kind``,
    which is why it forces ``target_spec`` to ``None`` exactly like the self
    form below.

    ``target_kind=None`` is the **self** form — "Return ~ to its owner's
    hand." with no RULE 115 target and no player choice, mirroring
    `TapEffect`/`AddCountersEffect`'s own untargeted mode. It acts on the
    effect's own source wherever that currently is: Rancor's "When ~ dies,
    return it to its owner's hand." resolves with the source already in a
    *graveyard* (RULE 400.7 — it's a new object there), and
    `RulesEngine.return_to_hand` moves an object out of whatever zone it's
    in, so no separate graveyard path is needed. Flickering Ward's "{W}:
    Return ~ to its owner's hand." is the same effect from the
    battlefield.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "permanent",
        optional: bool = False,
        count: int = 1,
        distinct_controllers: bool = False,
        previous_subject: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.previous_subject = previous_subject
        # ``target_kind=None`` is the self form — no `TargetSpec` at all, the
        # same way `TapEffect`'s own untargeted modes leave it ``None``, so
        # `RulesEngine._trigger_target_specs` doesn't count this as a
        # targeting effect and open a RULE 115 choice with nothing to pick.
        # ``previous_subject`` is the same "nothing of its own to announce"
        # shape, for the same reason (PAR-1) — its targets already were the
        # preceding clause's.
        self.target_spec = (
            TargetSpec(
                kind=target_kind, optional=optional, count=count,
                distinct_controllers=distinct_controllers,
            )
            if target_kind is not None and not previous_subject
            else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.previous_subject:
            # "Return those creatures to their owners' hands." (PAR-1) — the
            # whole group the preceding "choose N target …" clause announced.
            for target in list(context.previous_targets):
                context.return_to_hand(target)
            return
        if self.target_spec is None:
            # Self form — the source itself, from whatever zone it's in.
            if self.source is not None:
                context.return_to_hand(self.source)
            return
        if self.target_spec.count != 1:
            chosen = _chosen_targets(targets, self.target_spec.count, self.target)
            for target in chosen:
                context.return_to_hand(target)
            return
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.return_to_hand(target)


class ReturnFromGraveyardEffect(GameEffect):
    """Return/put a target card from a graveyard onto the battlefield or to
    a hand (RULE 701.3, the Regrowth/Reanimate/Deathrite-adjacent recursion
    family — see `targeting.legal_targets`'s `_GRAVEYARD_TARGET_KINDS` for
    the full ``target_kind`` vocabulary: own/any/opponent graveyard scope ×
    card/creature/land/artifact/enchantment/instant-or-sorcery/permanent
    type). ``destination`` is ``"battlefield"`` (default) or ``"hand"``.

    ``under_your_control`` is the Reanimate/Rise from the Grave/Virtue of
    Persistence shape — "put target creature card from a graveyard onto
    the battlefield **under your control**" — as opposed to the plain
    Regrowth/Karmic Guide/Kenrith shape (this effect's default), which
    always returns to the card's *owner*'s control, matching how "return
    … to the battlefield"/"under its owner's control" reads. Only
    meaningful with ``destination="battlefield"`` — a card can't go to
    "your hand" when it isn't yours; real cards never combine the two.
    """

    #: Destinations this effect will route to (all handled by the engine's
    #: `_put_searched_card`): battlefield/hand (the recursion default pair)
    #: plus ``library_top`` (Noxious Revival "put … on top of its owner's
    #: library") / ``library_bottom``.
    _DESTINATIONS: frozenset[str] = frozenset(
        {"battlefield", "hand", "library_top", "library_bottom"}
    )

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "graveyard_creature",
        destination: str = "battlefield",
        under_your_control: bool = False,
        optional: bool = False,
        lose_life_equal_mv: bool = False,
        count: int = 1,
        shuffle_after: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.destination = destination if destination in self._DESTINATIONS else "battlefield"
        self.under_your_control = under_your_control
        # RULE 701.3 rider: "You lose life equal to that creature's mana
        # value." (Reanimate) — read off the returned card, paid by the
        # effect's own controller, after the return resolves.
        self.lose_life_equal_mv = lose_life_equal_mv
        # PAR-15: "shuffle target card(s) from your graveyard into your
        # library" (Piper's Melody/Renewing Touch/Perpetual Timepiece) —
        # RULE 701.3's own recursion, just with an unknown final position
        # rather than a fixed top/bottom; modeled as "put on the bottom,
        # then shuffle" (the position `_put_searched_card`'s
        # ``"library_bottom"`` gives it is immediately randomized away, so
        # the result is exactly "shuffled into the library") rather than a
        # third `_DESTINATIONS` entry, mirroring how `SearchLibraryEffect`
        # already treats a shuffle destination as a placement + a follow-up
        # `shuffle_library` call rather than its own zone.
        self.shuffle_after = shuffle_after
        self.target_spec = TargetSpec(kind=target_kind, optional=optional, count=count)

    def _apply_one(self, context: GameContext, target: Any) -> None:
        controller_id = None
        if self.under_your_control and self.destination == "battlefield":
            player = _controller_of(self.source, context)
            controller_id = player.id if player is not None else None
        mv = getattr(getattr(target, "card", None), "converted_mana_cost", 0) or 0
        owner_id = getattr(target, "owner_id", None)
        context.return_from_graveyard(target, self.destination, controller_id=controller_id)
        if self.shuffle_after and owner_id is not None:
            owner = context.state.player_by_id(owner_id)
            context.shuffle_library(owner)
        if self.lose_life_equal_mv and mv:
            player = _controller_of(self.source, context)
            if player is not None:
                context.lose_life(player, int(mv))

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec.count != 1:
            chosen = _chosen_targets(targets, self.target_spec.count, self.target)
            for target in chosen:
                self._apply_one(context, target)
            return
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        self._apply_one(context, target)


class BlinkEffect(GameEffect):
    """"Exile target permanent, then return it to the battlefield under its
    owner's control" (RULE 400.7 — Ephemerate/Momentary Blink-shaped).

    Distinct from `ReturnFromGraveyardEffect` (a graveyard-only recursion
    family): this targets a *battlefield* permanent. See `RulesEngine.
    blink`'s docstring for why exiling then re-entering is a genuine RULE
    400.7 "new object" rather than a single no-op move.

    ``under_your_control`` is Restoration Angel's own "return that card to
    the battlefield **under your control**" — this effect's controller
    rather than the target's owner (`RulesEngine.blink`'s ``controller``
    param). Default ``False`` is plain blink, always under the owner.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature_you_control",
        under_your_control: bool = False,
        creature_filter: Optional[dict] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, creature_filter=creature_filter)
        self.under_your_control = under_your_control

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller = _controller_of(self.source, context) if self.under_your_control else None
        context.blink(target, controller=controller)


class AddManaEffect(GameEffect):
    """Add mana straight to the effect's controller's pool (RULE 106.4) — a
    spell's own bare "Add {B}{B}{B}." resolve-time body (Dark Ritual-shaped),
    as opposed to a permanent's mana ability (`game/mana_abilities.py`,
    tapped for mana outside the stack entirely, never a resolve-time effect).
    Also covers a *targeted* activated ability's own "Add one mana of any
    color" body (Deathrite Shaman's graveyard-exile abilities) — RULE 605.1a
    excludes anything that targets from ever being a `mana_abilities.py`
    mana ability at all, so that shape can only ever resolve here.

    ``colors`` is one WUBRGC letter per mana symbol printed, in the order
    printed, or the sentinel ``"ANY"`` for "one mana of any color" — a
    genuine player decision, opened as an interactive `add_mana_any_color`
    `pending_choice` (`RulesEngine.add_mana_any_color`/`resolve_add_mana_
    any_color_choice`) rather than guessed at. Untargeted (mana itself
    can't be targeted, RULE 106.4 — unrelated to whatever cost the
    ability/spell producing it might target).
    """

    def __init__(
        self,
        colors: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
        amount: Optional[int] = None,
        color: str = "C",
        amount_selector: Optional[str] = None,
        amount_from_trigger_event: Optional[str] = None,
        recipient: str = "controller",
    ) -> None:
        super().__init__(source)
        #: "add that much {R}" (MEC-11's Raphael, Ninja Destroyer, an
        #: Enrage sibling — "whenever ~ is dealt damage, add that much
        #: {R}") — the event field name (``"amount"``) to read off
        #: `GameContext.trigger_event` at resolution, `MirrorProducedManaEffect`'s
        #: "read this firing's own payload" idiom applied to a plain
        #: numeric amount instead of a produced-colour set. **Documented
        #: simplification**: Raphael's own trailing "until end of turn, you
        #: don't lose this mana as steps and phases end" isn't modeled —
        #: `ManaPool` has no persist-past-a-step mechanism yet — so this
        #: mana empties at the current step's end like any other (RULE
        #: 500.4), rather than lasting the rest of the turn.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: Who the mana goes to: ``"controller"`` (the effect's own source's
        #: controller — every ordinary case) or ``"event_controller"``, the
        #: player named by the triggering event (`GameContext.trigger_event`).
        #: Wild Growth needs the latter: "whenever enchanted land is tapped
        #: for mana, **its controller** adds an additional {G}" — the land's
        #: controller, who need not be the Aura's (RULE 110.2 lets those
        #: diverge under a control-change effect).
        self.recipient = recipient
        self.colors = [str(c).upper() for c in (colors or [])]
        # ``amount``/``color`` are the *variable-count* form ("add an amount of
        # {C} equal to that spell's mana value" — Mana Drain): a resolved count
        # of one colour, threaded through the same ``"x"`` sentinel
        # `RulesEngine._substitute_x` rewrites, instead of one letter per
        # printed symbol. Kept separate from ``colors`` so the fixed-symbol
        # form (Dark Ritual's "{B}{B}{B}") is unchanged.
        self.amount = amount
        self.color = str(color).upper()
        #: A `continuous.count_selector` name resolved *at resolution time*
        #: for the board-dependent form — "then add {R} for each card named ~
        #: in each graveyard" (Rite of Flame). Additive with ``colors``
        #: above, so Rite of Flame's flat "{R}{R}" and its per-copy bonus are
        #: one effect rather than two: ``colors=["R","R"]`` plus this.
        #: Distinct from ``amount`` (a value the *caller* already resolved).
        self.amount_selector = amount_selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.recipient == "event_controller":
            player = _event_player(context)
        else:
            player = _controller_of(self.source, context)
        if player is None:
            return
        for color in self.colors:
            if color == "ANY":
                context.add_mana_any_color(player)
            else:
                context.add_mana(player, color)
        if isinstance(self.amount, int) and self.amount > 0:
            context.add_mana(player, self.color, self.amount)
        if self.amount_from_trigger_event:
            event = context.trigger_event
            extra = int((event or {}).get(self.amount_from_trigger_event) or 0)
            if extra > 0:
                context.add_mana(player, self.color, extra)
        if self.amount_selector:
            from . import continuous  # function-scoped: avoid an import cycle

            extra = continuous.count_selector(
                context.state, player.id, self.amount_selector, source=self.source
            )
            if extra > 0:
                context.add_mana(player, self.color, extra)


def _mana_value_of(target: Any) -> int:
    """The mana value of a targeted spell (a `StackItem` or its `GameObject`
    or a `Card`) — for a delayed trigger capturing "that spell's mana value"
    (Mana Drain) at setup, before the spell leaves the game."""
    obj = getattr(target, "obj", None) or target
    card = getattr(obj, "card", None) or obj
    return int(getattr(card, "converted_mana_cost", 0) or 0)


class CreateDelayedTriggerEffect(GameEffect):
    """Arm a delayed triggered ability (RULE 603.7) at resolution — "at the
    beginning of your next <step>, <effect>." (Mana Drain, the Pacts, Final
    Fortune, Corpse Dance).

    ``step`` is the step-name it waits for (``"upkeep"``/``"main1"``/
    ``"end"``/…); ``scope`` is ``"controller"`` (that controller's next such
    step) or ``"any"`` (the very next one). ``effects`` is a list of
    whitelisted ``{"type", "params"}`` effect descriptors built into live
    one-shot effects here (through the same `effect_binder.build_effects`
    whitelist as any other effect — nothing from card text escapes it) and
    stashed on `GameState.delayed_triggers`; `GameEngine._fire_delayed_
    triggers` places them on the stack when the step arrives.

    ``capture`` reads a dynamic value from this effect's own resolution and
    bakes it into the delayed effects: ``"target_mana_value"`` substitutes the
    ``"x"`` amount/count sentinel with the targeted spell's mana value (Mana
    Drain's "add an amount of {C} equal to that spell's mana value") — captured
    now, since the spell is gone by the time the delayed ability fires.

    ``description`` is a human-readable label for the UI's "planned"
    delayed-trigger panel (`DelayedTrigger.to_dict()`) — e.g. "Mana Drain:
    {C} in Höhe der Manakosten hinzufügen". Optional (defaults to empty);
    hand-authored specs should still set one so the panel isn't blank.
    """

    def __init__(
        self,
        step: str,
        effects: Optional[list[dict[str, Any]]] = None,
        scope: str = "controller",
        capture: Optional[str] = None,
        min_turn_offset: int = 0,
        description: str = "",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.step = str(step)
        self.inner_specs = list(effects or [])
        self.scope = str(scope)
        self.capture = capture
        # ``min_turn_offset`` arms the trigger to fire no earlier than
        # ``turn_number + offset`` — 1 makes "at the beginning of *that*
        # (extra) turn's end step" (Final Fortune) skip the *current* turn's
        # end step, which would otherwise be the very next one.
        self.min_turn_offset = int(min_turn_offset)
        self.description = str(description)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .effect_binder import build_effects  # function-scoped: effects↔binder cycle
        from ..parser.oracle.spec import EffectSpec
        from ..models.game_state import DelayedTrigger

        inner = build_effects(
            [EffectSpec(type=d["type"], params=dict(d.get("params") or {})) for d in self.inner_specs],
            self.source,
        )
        if self.capture == "target_mana_value" and targets:
            captured = _mana_value_of(targets[0])
            for effect in inner:
                for attr in ("amount", "count"):
                    if getattr(effect, attr, None) == "x":
                        setattr(effect, attr, captured)
        controller_id = getattr(self.source, "controller_id", None) or context.active_player.id
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=controller_id,
                step=self.step,
                effects=inner,
                scope=self.scope,
                targets=list(targets or []),
                description=self.description,
                min_turn=context.state.turn_number + self.min_turn_offset,
            )
        )


class InstallTemporaryPlayerTriggerEffect(GameEffect):
    """Arm a `TemporaryPlayerTrigger` (RULE 603.7-adjacent, but *recurring*
    and player-scoped rather than one-shot and step-scoped) — "until the
    end of defending player's next turn, that player gets two rad counters
    whenever they cast a spell" (Nuka-Nuke Launcher).

    The recipient defaults to the defending player (RULE 506.4). Like
    `AddPlayerCountersEffect.selector="defending_player"`, an Aura/
    Equipment-hosted "whenever equipped creature attacks, ..." trigger's
    own source is the Equipment, not the attacker — `combat_defender` is
    only ever stamped onto the actual attacking creature (RULE 506.4/
    `declare_attackers`), so this resolves the source's own ``attached_to``
    host first, exactly mirroring that effect's own docstring. ``event_type``
    is the `EventType`
    the installed trigger re-fires on (``"SPELL_CAST"`` — the only shape any
    real card in this pool needs); ``effects`` are whitelisted descriptors
    built into live effects immediately (mirroring `CreateDelayedTrigger
    Effect`) and reused for every firing while the trigger stays active —
    each is baked with ``player`` as its recipient (any effect carrying a
    settable, currently-``None`` ``player`` attribute, e.g.
    `AddPlayerCountersEffect`), since the specific player is fixed at
    install time, not re-resolved per firing.
    """

    def __init__(
        self,
        event_type: str,
        effects: Optional[list[dict[str, Any]]] = None,
        description: str = "",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.event_type = str(event_type)
        self.inner_specs = list(effects or [])
        self.description = str(description)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .effect_binder import build_effects  # function-scoped: effects↔binder cycle
        from ..parser.oracle.spec import EffectSpec
        from ..models.game_state import TemporaryPlayerTrigger

        host = self.source
        attached_to = getattr(host, "attached_to", None)
        if attached_to is not None:
            resolved = context.state.find_object(attached_to)
            if resolved is not None:
                host = resolved
        player = _defending_player_of(host, context)
        if player is None:
            return
        inner = build_effects(
            [EffectSpec(type=d["type"], params=dict(d.get("params") or {})) for d in self.inner_specs],
            self.source,
        )
        for effect in inner:
            if hasattr(effect, "player") and getattr(effect, "player", None) is None:
                effect.player = player
        context.state.temporary_player_triggers.append(
            TemporaryPlayerTrigger(
                player_id=player.id,
                event_type=self.event_type,
                effects=inner,
                install_turn=context.state.turn_number,
                description=self.description,
            )
        )


class PayEnergyThenEffect(GameEffect):
    """RULE 122/601.2b resolve-time optional cost: "you may pay {E}{E}. If you
    do, `<effect>`." (Aether Chaser/Herder/Inspector/Swooper — "…create a 1/1
    colorless Servo artifact creature token"). The controller may pay
    ``amount`` energy counters; only if they do do the ``effects`` follow —
    a genuine player decision (unlike the flat "Pay {E}" *activated-ability
    cost*, `ActivationCost.pay_energy`), so it opens an interactive yes/no
    `pay_energy_then` `pending_choice` at resolution (`RulesEngine.request_
    pay_energy_then`), mirroring the shock-land pay-life choice.

    ``effects`` are whitelisted descriptor dicts, built into live effects
    lazily at resolution (mirroring `InstallTemporaryPlayerTriggerEffect`);
    only untargeted follow-ups are modeled today (every real energy card
    with this rider creates a token / gains life / draws — none needs a
    freely-chosen target here). If the controller can't afford ``amount``
    energy, the payment simply never happens (no choice offered).
    """

    def __init__(
        self,
        amount: int = 0,
        effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = int(amount)
        self.inner_specs = list(effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or player.counters.get("energy", 0) < self.amount:
            return  # can't pay — the optional payment simply doesn't happen
        context.engine.request_pay_energy_then(player, self.amount, self.inner_specs, self.source)


class PayCostThenEffect(GameEffect):
    """RULE 118.3-style resolve-time optional payment: "you may pay
    `<cost>`. If you do, `<effect>`." — the general form of
    `PayEnergyThenEffect` above, which only ever handled ``{E}`` pips.

    ``cost`` is free-form cost *text* parsed by `game/costs.py`'s
    `parse_activation_cost`, so mana / life / discard / sacrifice all work
    through the one `_can_pay_player_cost`/`_pay_player_cost` path ward and
    "sacrifice ~ unless you pay" already share, rather than a fourth
    parallel payment implementation.

    ``payer`` says *who* is asked: ``"controller"`` (Mana Vault's own
    upkeep untap) or ``"event_controller"``/``"event_player"`` — the player
    named by the triggering event (Wandering Archaic taxes the **opponent
    who cast the spell**, not its own controller).

    ``else_effects`` is the "**If you don't**, `<effect>`." branch, which for
    Wandering Archaic is the entire point: the opponent *declining* is what
    lets you copy their spell.
    """

    def __init__(
        self,
        cost: str = "",
        effects: Optional[list[dict[str, Any]]] = None,
        else_effects: Optional[list[dict[str, Any]]] = None,
        payer: str = "controller",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.cost_text = str(cost)
        self.inner_specs = list(effects or [])
        self.else_specs = list(else_effects or [])
        self.payer = payer

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import parse_activation_cost  # function-scoped: import cycle

        if self.payer == "event_controller":
            player = _event_player(context)
        elif self.payer == "event_player":
            player = _event_player(context, key="player_id")
        else:
            player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.request_pay_cost_then(
            player,
            parse_activation_cost(self.cost_text),
            self.inner_specs,
            self.source,
            else_effect_specs=self.else_specs,
            # A reflexive trigger's baked-in "that spell" (Wandering
            # Archaic) has to reach the branch effects, which are built
            # fresh when the choice is answered rather than sitting on the
            # stack item where the usual target dispatch would find them.
            targets=list(targets or []),
        )


class UntapSelfEffect(GameEffect):
    """"Untap this permanent." (Mana Vault's upkeep payoff) — the untap
    sibling of `TapEffect`'s self mode, scoped to the effect's own source.

    Deliberately bypasses `continuous.has_no_untap_static`: that gate is
    about the *untap step* (RULE 502.4), and a permanent whose whole point
    is "doesn't untap during your untap step, but here's how to untap it
    anyway" (Mana Vault, Winter Orb's cousins) must not have this blocked by
    its own restriction.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.source
        if target is not None:
            context.set_tapped(target, False)


class ReboundFreeCastWindowEffect(GameEffect):
    """RULE 702.88b Rebound's delayed half: "At the beginning of your next
    upkeep, you may cast this card from exile without paying its mana
    cost." Fires as a `DelayedTrigger`'s effect, armed by `RulesEngine.
    resolve_top_of_stack` when a `GameObject.has_rebound` card resolves
    having been cast from hand (Ephemerate-shaped).

    Modeled as a *standing* temp-cast permission (`GameState.temp_play_
    permissions`, already known to `can_cast`/`cast_spell`) plus `GameState.
    free_cast_instance_ids` to zero the mana cost, rather than a forced
    yes/no choice at this trigger's own resolution: RULE 702.88b's delayed
    ability really does ask "you may cast X" right then, but this engine has
    no synchronous mid-resolution chooser for a one-shot optional action
    (`RulesEngine.discard`'s "auto-choose, no chooser in this MVP" is the
    same fidelity level elsewhere). Same-turn-only (swept at this upkeep's
    own cleanup, `GameEngine._step_cleanup`) — "use it this turn or lose
    it", matching Rebound's real one-shot window closely enough without new
    step-scoped cleanup machinery.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        if obj is None or obj.zone != Zone.EXILE:
            return
        context.engine.grant_free_cast_window_from_exile(obj)


class TheRingTemptsYouEffect(GameEffect):
    """"The Ring tempts you." (RULE 701.51a) — untargeted; the tempted
    player is the source's controller unless ``player`` names one.

    Everything the temptation *does* lives in `RulesEngine.
    the_ring_tempts_you`: level the emblem up, then choose a Ring-bearer
    (interactively when there's a real choice to make).
    """

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or _controller_of(self.source, context)
        if player is not None:
            context.engine.the_ring_tempts_you(player)


class ChooseObjectsEffect(GameEffect):
    """"[You] choose N <kind> you control and <do something to it>." — the
    spec-facing front for `RulesEngine.request_choose_objects`.

    The general answer to every clause that names *what kind* of permanent
    to act on but leaves *which one* to a player: Tevesh Szat's "you may
    sacrifice another creature or planeswalker", Professor Onyx's forced
    per-opponent sacrifice. Distinct from `SacrificeEffect`, which picks its
    own victim by criteria — use that where the rules pick (annihilator's
    "sacrifice N permanents" is still the defender's choice, but no shipped
    card cares which), and this where the player does.

    ``then``/``then_if_commander`` are serialized `EffectSpec` dicts applied
    once the picks are in: "**If you do**, draw two cards", and RULE 903's
    "if a commander was sacrificed this way, draw a card" on top. They can't
    be separate effects in the same list, because whether they apply is only
    known *after* the choice — which is exactly what a "you may" clause
    means.
    """

    def __init__(
        self,
        action: str = "sacrifice",
        what: str = "permanent",
        count: int = 1,
        optional: bool = False,
        exclude_self: bool = False,
        prompt: str = "",
        then: Optional[list[dict[str, Any]]] = None,
        then_if_commander: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.action = action
        self.what = what
        self.count = count
        self.optional = optional
        self.exclude_self = exclude_self
        self.prompt = prompt
        self.then = then
        self.then_if_commander = then_if_commander

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .rules_engine import _matches_permanent_type

        player = _controller_of(self.source, context)
        if player is None:
            return
        candidates = [
            obj
            for obj in context.state.permanents_controlled_by(player.id)
            if _matches_permanent_type(obj, self.what)
            and not (self.exclude_self and obj is self.source)
        ]
        context.choose_objects(
            player, candidates, self.action, count=self.count,
            optional=self.optional, prompt=self.prompt, source=self.source,
            then_specs=self.then, then_specs_if_commander=self.then_if_commander,
        )


class SacrificeSpecificEffect(GameEffect):
    """Sacrifice the exact permanents baked into this effect (RULE 701.17).

    The named-object counterpart of `SacrificeEffect`, which picks its
    victims by criteria and selector. Used where the rules already fixed
    *which* permanents ("that creature's controller sacrifices it at end of
    combat" — RULE 701.51a's third Ring ability), so there is nothing to
    choose and nothing to target. Silently skips any that already left the
    battlefield by the time this resolves.

    ``delay_step`` defers the sacrifice to a RULE 603.7 delayed trigger at
    that step instead of doing it now — "…sacrifices it **at end of
    combat**". Armed rather than executed, so a blocker that dies in combat
    first is simply gone when the delayed half fires.
    """

    def __init__(
        self,
        objects: list["GameObject"],
        delay_step: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.objects = objects
        self.delay_step = delay_step

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.delay_step:
            from ..models.game_state import DelayedTrigger

            controller_id = getattr(self.source, "controller_id", None) or (
                context.active_player.id if context.active_player else ""
            )
            context.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=controller_id,
                    step=self.delay_step,
                    scope="any",
                    effects=[SacrificeSpecificEffect(list(self.objects), source=self.source)],
                    description="Opfern am Ende des Kampfes",
                )
            )
            return
        for obj in list(self.objects):
            if obj in context.state.battlefield:
                # RULE 701.17a: a sacrifice is a non-destructive move to the
                # graveyard, so it can't be stopped by a regeneration shield
                # (RULE 701.16c) — `put_into_graveyard`, not `destroy`.
                context.engine.put_into_graveyard(obj)


class ReturnUncastExiledEffect(GameEffect):
    """The "…if it wasn't cast this way" tail every optional free-cast-from-
    exile window needs: Beseech the Mirror's "put the exiled card into your
    hand", Possibility Storm's and Tibalt's Trickery's "put it on the bottom
    of their library in a random order".

    Armed as a `DelayedTrigger` alongside the window itself and baked onto
    the exiled card (``exiled_object``) — "the exiled card" names one
    specific object, nothing targetable. Being still in exile when this
    fires *is* "wasn't cast this way": casting it moves the card to the
    stack, so the check is a zone read rather than a flag anything has to
    remember to clear.
    """

    def __init__(
        self,
        exiled_object: "GameObject",
        destination: str = "hand",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.exiled_object = exiled_object
        self.destination = destination

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.exiled_object
        if obj is None or obj.zone != Zone.EXILE:
            return
        obj.face_down_in_exile = False
        if self.destination == "library_bottom":
            owner = context.state.player_by_id(obj.owner_id)
            if owner is None:
                return
            owner.remove_from_zone(obj, Zone.EXILE)
            obj.zone = Zone.LIBRARY
            owner.library.insert(0, obj)
            return
        context.engine.return_to_hand(obj)


class CastExiledFaceDownEffect(GameEffect):
    """"You may cast the exiled card without paying its mana cost if that
    spell's mana value is N or less. Put the exiled card into your hand if
    it wasn't cast this way." (Beseech the Mirror.)

    Runs right after a search whose destination was ``"exile_face_down"``,
    and claims every face-down card in the controller's exile — only that
    destination ever sets `GameObject.face_down_in_exile`, and this effect
    always clears it, so the pairing is unambiguous within one resolution.

    ``require_bargained`` gates the *cast* half on the spell having been
    bargained (RULE 701.x, `GameObject.bargained`) — the "put it into your
    hand" half is unconditional, which is why this isn't the existing
    `ConditionalEffect` wrapper around a cast-only effect.

    The window itself is `RulesEngine.grant_free_cast_window_from_exile`'s
    (Rebound's), so the card is cast through the ordinary action loop with
    full targeting rather than a stripped mid-resolution cast. **Documented
    deviation**: the real card offers that cast *during its own resolution*
    and sends the card to hand immediately afterwards; here the window
    stays open until the beginning of the end step, when the delayed
    `ReturnUncastExiledEffect` performs the "if it wasn't cast this
    way" half. The engine has no synchronous mid-resolution chooser for an
    optional cast (the same fidelity limit `ReboundFreeCastWindowEffect`
    documents), and holding the window open only ever helps the caster —
    who, on this card, has already paid for it.
    """

    def __init__(
        self,
        max_mana_value: Optional[int] = None,
        require_bargained: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.max_mana_value = max_mana_value
        self.require_bargained = require_bargained

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..models.game_state import DelayedTrigger

        source = self.source
        player = None
        if source is not None:
            player = context.state.player_by_id(source.controller_id)
        player = player or context.active_player
        if player is None:
            return
        may_cast = not self.require_bargained or bool(getattr(source, "bargained", False))
        for obj in list(player.exile):
            if not getattr(obj, "face_down_in_exile", False):
                continue
            cheap_enough = (
                self.max_mana_value is None
                or obj.card.converted_mana_cost <= self.max_mana_value
            )
            if not (may_cast and cheap_enough):
                # Never eligible to be cast — the "put it into your hand"
                # half applies straight away rather than at the end step.
                obj.face_down_in_exile = False
                context.engine.return_to_hand(obj)
                continue
            context.engine.grant_free_cast_window_from_exile(obj)
            context.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=player.id,
                    step="end",
                    scope="any",
                    effects=[ReturnUncastExiledEffect(obj, source=source)],
                    description=f"{obj.name}: auf die Hand nehmen, falls nicht gewirkt",
                )
            )


class MarchesaDelayedReturnEffect(GameEffect):
    """RULE 603.7 delayed half of "return that card to the battlefield under
    your control at the beginning of the next end step" (Marchesa, the
    Black Rose-shaped: a creature you control with a counter on it dies).
    ``dying_object`` is baked in at construction — there's nothing left to
    target once the delayed trigger fires (the same RULE 603.4 per-firing
    shape `RulesEngine._collect_impulsive_draw_triggers`/`ImpulsiveDrawEffect`
    already use for Ragavan's per-firing damaged player).
    """

    def __init__(self, dying_object: "GameObject", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.dying_object = dying_object

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..models.game_state import DelayedTrigger

        controller_id = getattr(self.source, "controller_id", None) or context.active_player.id
        inner = ReturnFromGraveyardEffect(
            target=self.dying_object,
            destination="battlefield",
            under_your_control=True,
            source=self.source,
        )
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=controller_id,
                step="end",
                scope="any",
                effects=[inner],
                description=f"{self.dying_object.name}: unter Kontrolle zurück auf das Schlachtfeld",
            )
        )


class ReturnSelfFromGraveyardEffect(GameEffect):
    """"...if this creature is in your graveyard, you may return it to your
    hand." (RULE 112.6a, Infesting Radroach) — ``obj`` is baked in at
    construction (`RulesEngine._collect_mill_return_from_graveyard_
    triggers`, the same per-firing shape `MarchesaDelayedReturnEffect`
    above uses for its own dying object), deliberately with no
    `target_spec` of its own so `_place_or_pause_trigger` never opens a
    target choice for it — "it" is always this ability's own source, never
    a pick. Re-checks ``obj``'s zone at resolution time rather than
    assuming it's still in the graveyard (RULE 603.3c/608.2b: something
    else may have moved it between trigger and resolution, e.g. an
    opponent's graveyard-hate instant).
    """

    def __init__(self, obj: "GameObject", destination: str = "hand", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.obj = obj
        self.destination = destination

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.obj.zone != Zone.GRAVEYARD:
            return
        context.return_from_graveyard(self.obj, self.destination)


class SacrificeObjectEffect(GameEffect):
    """Sacrifice one specific, already-known permanent (RULE 701.17) — the
    delayed half of "sacrifice the creature at the beginning of the next end
    step" (Sneak Attack/Meek Attack-shaped): baked in at arm time, since
    there's no target left to choose once the delayed trigger fires.
    """

    def __init__(self, obj: "GameObject", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.obj = obj

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.obj in context.state.battlefield:
            context.engine.put_into_graveyard(self.obj)


class CheatCreatureFromHandEffect(GameEffect):
    """"You may put a creature card from your hand onto the battlefield.
    That creature gains haste. Sacrifice the creature at the beginning of
    the next end step." (Sneak Attack/Meek Attack-shaped — RULE 701 "cheat
    into play" plus a RULE 603.7 delayed sacrifice tail). ``max_total_pt``
    is Meek Attack's own "total power and toughness 5 or less" filter
    (``None`` for Sneak Attack's unrestricted version). The eligible
    creature is auto-picked — no chooser in this MVP, the same idiom
    `RulesEngine.discard` already uses for an un-targeted hand-card pick.
    """

    def __init__(
        self, max_total_pt: Optional[int] = None, source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.max_total_pt = max_total_pt

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..models.game_state import DelayedTrigger

        player = _controller_of(self.source, context)
        if player is None:
            return
        creature = context.engine.put_hand_creature_onto_battlefield(player, self.max_total_pt)
        if creature is None:
            return
        creature.temp_keywords.add("haste")
        context.recompute()
        source_name = self.source.name if self.source is not None else None
        label = f"{creature.name}: geopfert" + (f" ({source_name})" if source_name else "")
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=player.id,
                step="end",
                scope="any",
                effects=[SacrificeObjectEffect(creature, source=self.source)],
                description=label,
            )
        )


class TakeExtraTurnEffect(GameEffect):
    """Take an extra turn after this one (RULE 500.7) — Final Fortune, the
    Time Warp family. Queues the effect's controller onto
    `GameState.extra_turns`; `GameEngine.begin_turn` takes it right after the
    current turn."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.take_extra_turn(player)


class GrantProtectionEffect(GameEffect):
    """"Target creature gains protection from the color of your choice until
    end of turn" (RULE 702.16 — Mother of Runes; Giver of Runes adds a
    "colorless" option and targets *another* creature).

    Opens an interactive `grant_protection_color` choice (`RulesEngine.
    grant_protection_choice`) for the effect's controller; the chosen quality
    lands in ``target.temp_protections`` (cleared at cleanup, RULE 514.2).
    ``allow_colorless`` is Giver of Runes' extra option.
    """

    def __init__(
        self,
        target_kind: str = "creature_you_control",
        allow_colorless: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.allow_colorless = allow_colorless
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        if target is None:
            return
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        context.engine.grant_protection_choice(target, controller, self.allow_colorless)


class LoseGameEffect(GameEffect):
    """The effect's controller loses the game (RULE 104.3a) — Final Fortune's
    "you lose the game" downside, resolved via the same `_player_loses` path
    an SBA loss uses."""

    def __init__(self, reason: str = "effect", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.reason = reason

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.lose_game(player, self.reason)


#: `TapEffect.selector`'s whitelist — a mass "tap/untap all X" effect (RULE
#: 601.2c-style, untargeted, the same shape `DealDamageEffect.selector`/
#: `DestroyEffect.selector` use), not a RULE 115 target at all. Only the one
#: shape a real card needs so far: "untap all creatures you control"
#: (Village Bell-Ringer).
_TAP_SELECTORS: frozenset[str] = frozenset(
    {
        "creatures_you_control", "permanents_you_control", "nonland_permanents_you_control",
        # "Untap each other creature you control." (Copperhorn Scout).
        "other_creatures_you_control",
    }
)


class TapEffect(GameEffect):
    """Tap (or untap) a target permanent — or the source itself (RULE 701.21/22).

    ``target_kind=None`` (unlike the default ``"permanent"``) makes it act on
    the effect's own source with no player choice involved — "untap it" in a
    "whenever this creature becomes tapped, untap it" trigger (Dionus, Elvish
    Archdruid), mirroring `AddCountersEffect`'s untargeted mode.

    ``target_kind="attached_permanent"`` is a third, similarly targetless
    mode — "{U}: Tap enchanted creature."/"{U}: Untap enchanted creature."
    (Freed from the Real/Pemmin's Aura-shaped Aura activated abilities):
    acts on whatever the effect's own source (the Aura) is *currently*
    `attached_to`, re-read live at resolution (an Aura can move via
    Reconfigure-adjacent effects), mirroring `effect_binder._subject_
    condition`'s `"attached_permanent"` *trigger*-subject concept — this is
    the same idea applied to an effect's *target* instead.

    ``selector`` (see `_TAP_SELECTORS`) is a fourth mode — "untap all
    creatures you control" (Village Bell-Ringer's ETB) — untargeted, acting
    on every object `continuous.group_selector_objects` picks out for the
    effect's own controller, rather than a single target/self/attached host.

    ``count`` > 1 targets several independent objects (RULE 115.1a
    generalized to N>=2, the same shape `DestroyEffect.count` uses) — "untap
    up to two target lands" (Snap-shaped).

    ``previous_subject=True`` (PAR-15's "Untap those creatures." — Colossal
    Heroics' own trailing sentence, following "Any number of target
    creatures each get +2/+2 until end of turn.") is `ReturnToHandEffect`'s
    same pronoun shape: no target of its own, acting on whatever the
    preceding clause's own multi-target group was (`GameContext.
    previous_targets`).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "permanent",
        untap: bool = False,
        optional: bool = False,
        selector: Optional[str] = None,
        count: int = 1,
        previous_subject: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.untap = untap
        self.selector = selector if selector in _TAP_SELECTORS else None
        self._attached_mode = target_kind == "attached_permanent"
        self.previous_subject = previous_subject
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional, count=count)
            if target_kind is not None and not self._attached_mode and self.selector is None and not previous_subject
            else None
        )

    def target_polarity(self) -> Optional[str]:
        # Untapping is a favour (untap your own blocker/attacker); tapping
        # down is a combat trick against whoever's permanent it is (usually
        # an opponent's would-be blocker or attacker).
        return "beneficial" if self.untap else "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.previous_subject:
            for one in list(context.previous_targets):
                context.set_tapped(one, tapped=not self.untap)
            return
        if self.selector is not None:
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            for obj in group_selector_objects(context.state, controller_id, self.selector, src=self.source):
                context.set_tapped(obj, tapped=not self.untap)
            return
        if self._attached_mode:
            host_id = getattr(self.source, "attached_to", None)
            target = context.state.find_object(host_id) if host_id is not None else None
            if target is not None:
                context.set_tapped(target, tapped=not self.untap)
            return
        if self.target_spec is not None and self.target_spec.count != 1:
            chosen = _chosen_targets(targets, self.target_spec.count, self.target)
            for one in chosen:
                context.set_tapped(one, tapped=not self.untap)
            return
        target = (targets[0] if targets else None) or self.target
        if target is None and self.target_spec is None:
            target = self.source
        if target is not None:
            context.set_tapped(target, tapped=not self.untap)


class UnblockableEffect(GameEffect):
    """"Target creature can't be blocked this turn" (Rogue's Passage) — sets
    `GameObject.temp_unblockable`, read directly by `GameEngine.can_block`
    and cleared at cleanup (RULE 514.2).

    ``creature_filter`` (Access Tunnel's "target creature with power 3 or
    less") mirrors `DestroyEffect`'s own qualified-target filter.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        creature_filter: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, creature_filter=creature_filter)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            target.temp_unblockable = True


class CantBlockEffect(GameEffect):
    """"Target creature can't block this turn" (Falter/Abandon the Post) and
    its untargeted group form ("creatures your opponents control can't block
    this turn") — sets `GameObject.temp_cant_block`, read by
    `GameEngine.can_block` and cleared at cleanup (RULE 514.2).

    The blocker-side mirror of `UnblockableEffect` above, and shaped like it:
    ``selector`` (a `continuous.group_selector_objects` name) switches from
    RULE 115's targeted form to RULE 601.2c's mass one, ``count``
    generalizes the targeted form to N targets (RULE 115.1a — "up to two
    target creatures can't block this turn"), and ``filter`` narrows the mass
    form by characteristics `group_selector_objects`'s own selector params
    can't express ("creatures **without flying** can't block this turn" —
    `combat.matches_object_filter`'s shared vocabulary).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        count: int = 1,
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.selector = selector
        self.filter = dict(filter or {})
        self.target_spec = (
            None if selector else TargetSpec(kind=target_kind, count=count, optional=optional)
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector:
            from . import combat
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            for obj in group_selector_objects(
                context.state, controller_id, self.selector, src=self.source
            ):
                if obj.is_creature and combat.matches_object_filter(obj, self.filter):
                    obj.temp_cant_block = True
            return
        count = self.target_spec.count if self.target_spec is not None else 1
        # Only this effect's own ``count`` targets, off the front of a
        # possibly-shared list — see `DestroyEffect.apply`'s comment.
        chosen = (
            targets[:count] if targets else ([self.target] if self.target is not None else [])
        )
        for one in chosen:
            if one is not None:
                one.temp_cant_block = True


class GrantCombatRestrictionEffect(GameEffect):
    """""~ can't be blocked by creatures with power 2 or less **this turn**"
    (Cavern Stomper) / "target creature can't be blocked by Walls this turn"
    (Tower of Coireall) — the resolve-time sibling of the standing
    ``combat_restriction`` static.

    Grants the *same* clamped param dict onto `GameObject.
    temp_combat_restrictions`, which `combat.combat_restrictions` reads
    alongside the recompute-derived list, so no combat-time check has to know
    which of the two a restriction came from. Cleared at cleanup (RULE 514.2).

    ``restrict_to_source=True`` stamps ``self.source``'s own instance id onto
    the restriction's ``filter`` at apply time (``{"instance_id": ...}``) —
    the pairwise "target creature can't block **~** this turn"/"target
    creature blocks **~** this turn if able" shapes, where the *specific*
    attacker named is this ability's own source and so can't be baked into
    the `AbilitySpec` at parse time (it varies per game object). Combined
    with the ``cant_block_filtered``/``must_block_target`` restriction
    kinds, `combat.matches_object_filter`'s ``instance_id`` key then narrows
    the (otherwise unfiltered) restriction to that one attacker.
    """

    def __init__(
        self,
        restriction: Optional[dict[str, Any]] = None,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        restrict_to_source: bool = False,
    ) -> None:
        super().__init__(source)
        self.restriction = dict(restriction or {})
        self.target = target
        self.restrict_to_source = restrict_to_source
        # No ``target_kind`` at all is the self form ("~ can't be blocked
        # by … this turn"), matching `PumpEffect`'s own self/target split.
        self.target_spec = TargetSpec(kind=target_kind) if target_kind else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is None:
            target = self.source
        else:
            target = (targets[0] if targets else None) or self.target
        if target is None or not self.restriction.get("kind"):
            return
        restriction = dict(self.restriction)
        if self.restrict_to_source and self.source is not None:
            restriction["filter"] = {
                **dict(restriction.get("filter") or {}),
                "instance_id": self.source.instance_id,
            }
        target.temp_combat_restrictions.append(restriction)


class AttachEffect(GameEffect):
    """Attach a permanent to another permanent as an Aura/Equipment-style effect.

    ``target_kind="created"`` is a fourth, non-RULE-115 mode alongside the
    ordinary target/self ``TargetSpec`` shapes below — "create a 1/1 …
    creature token and attach ~ to it." (Auxiliary Boosters/Living Weapon-
    adjacent, Field-Tested Frying Pan): the host is whichever object an
    *earlier* effect in this same resolution just created
    (`GameContext.created_objects`, RULE 608.2's "the tokens/it" referent —
    see `RenownEffect`/goad's own use of the same list), not a chosen or
    printed-source permanent.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
    ) -> None:
        super().__init__(source)
        self.target = target
        self._created_mode = target_kind == "created"
        if not self._created_mode:
            self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self._created_mode:
            created = getattr(context, "created_objects", None)
            target = created[-1] if created else None
        else:
            target = (targets[0] if targets else None) or self.target
        if target is None or self.source is None:
            return
        context.engine.attach_to_target(self.source, target)


class AttachTriggeringPermanentEffect(GameEffect):
    """"Whenever a[n] <X> you control enters, you may attach it to target
    creature you control." (Sigarda's Aid-shaped) — RULE 603.3d's "it"
    pronoun for a **group**-subject trigger ("an Equipment you control
    enters", not "this permanent enters"), so unlike `AttachEffect` (always
    attaches the ability's own source) and `CreateTokenMayAttachEquipmentEffect`
    (a *chosen* Equipment onto a token this same resolution just created),
    the permanent being moved here is neither: it's whichever object
    actually fired the trigger this time, read off `GameContext.
    trigger_event`'s own ``instance_id`` (ENG-13's general per-firing
    dynamic reference — the same field `ReturnSharedTypePermanentEffect`
    reads for Cloudstone Curio's own "it").

    Only the destination is a real RULE 115 target (``target_kind``,
    "target creature you control" by default); the mover is never offered
    as one, so this can't be reused for a spell/ability that names the
    moving object as a *chosen* target instead of "it".
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature_you_control",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None:
            return
        mover = context.state.find_object(event.get("instance_id"))
        target = (targets[0] if targets else None) or self.target
        if mover is None or target is None:
            return
        context.engine.attach_to_target(mover, target)


class UnattachTapIndestructibleEffect(GameEffect):
    """Akiri, Fearless Voyager's own "{W}: You may unattach an Equipment
    from a creature you control. If you do, tap that creature and it gains
    indestructible until end of turn."

    ``target_kind="attached_equipment_you_control"`` (`game/targeting.py`)
    only offers an Equipment that's actually attached, so there's always a
    host to act on once one is chosen — unlike `AttachEffect`, the effect's
    own source (Akiri) is neither unattached nor the one gaining
    indestructible; both happen to the *targeted Equipment*'s host.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "attached_equipment_you_control",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        equipment = (targets[0] if targets else None) or self.target
        if equipment is None:
            return
        host_id = getattr(equipment, "attached_to", None)
        if host_id is None:
            return
        host = context.state.find_object(host_id)
        equipment.attached_to = None
        if host is not None:
            context.set_tapped(host, True)
            host.temp_keywords.add("indestructible")


class ReturnCreatureGrantIndestructibleEffect(GameEffect):
    """Temur Sabertooth's own "{1}{G}: You may return another creature you
    control to its owner's hand. If you do, this creature gains
    indestructible until end of turn." — the same "if you do" shape
    `UnattachTapIndestructibleEffect` (Akiri) uses, just returning a target
    to hand instead of unattaching one, and granting indestructible to the
    effect's own *source* instead of the targeted object's host.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature_you_control",
        optional: bool = True,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        context.return_to_hand(target)
        if self.source is not None:
            self.source.temp_keywords.add("indestructible")


class TransformEffect(GameEffect):
    """Flip a double-faced permanent to its other face (RULE 712.8/712.9).

    Untargeted, it transforms its own source ("Transform ~." / "transform
    it" on a triggered/activated/loyalty ability); with a ``target_kind`` it
    targets another permanent (rare, but the same shape as `AttachEffect`).
    Delegates to `RulesEngine.transform_permanent`, which also rebinds the
    new face's catalogue-derived abilities/keywords — a bare
    `GameObject.transform()` would leave those pointing at the old face.
    """

    def __init__(
        self,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        if target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is not None:
            target = targets[0] if targets else None
        else:
            target = self.source
        if target is not None:
            context.engine.transform_permanent(target)


class RevealTopThenTransformEffect(GameEffect):
    """"Look at the top card of your library. If it's a[n] <criteria> card,
    transform ~." (RULE 712.8 conditional flip — Delver of Secrets-shaped).

    Unlike the RULE 731 day/night flip (`RulesEngine.
    apply_day_night_turn_check`, spells-cast-last-turn-driven), this checks
    the top card of the *controller's* library, so it's its own one-shot
    effect rather than routed through the day/night machinery. ``criteria``
    is a `models.card_query` predicate (``{"type": ["instant", "sorcery"]}``
    for Delver; a plain string/dict works the same as `SearchLibraryEffect`)
    so the same effect covers any future card sharing this template, not
    just an instant/sorcery check. The card is only looked at, never moved.
    """

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        criteria: Any = "",
    ) -> None:
        super().__init__(source)
        self.criteria = criteria

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        top = player.library[-1]
        if card_query.matches(top.card, self.criteria):
            context.engine.transform_permanent(self.source)


class ExileReturnTransformedEffect(GameEffect):
    """"Exile ~, then return it to the battlefield transformed under its
    owner's control" (RULE 400.7 + RULE 712.8 combined). Untargeted and
    always self — a transforming Saga's own final chapter (Fable of the
    Mirror-Breaker-shaped) or a transform-flip permanent's activated
    ability phrased this way instead of a plain `TransformEffect`
    (Ayara/Clive/Jin-Gitaxias-shaped). See `RulesEngine.
    exile_return_transformed`'s docstring for why this is a genuine
    RULE 400.7 zone change rather than an in-place flip.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.exile_return_transformed(self.source)


class SiegeDefeatedEffect(GameEffect):
    """A Siege's intrinsic defeat ability (RULE 310.11b): "exile it, then you
    may cast it transformed without paying its mana cost."

    Untargeted and always self, like `ExileReturnTransformedEffect` above —
    but the destination differs in the way that matters: the Siege goes to
    **exile and stays there**, and its back face becomes castable from
    exile for free. It does *not* come back to the battlefield on its own.

    Never bound from oracle text or the catalogue: RULE 310.11b is
    intrinsic to the Siege subtype, so `RulesEngine.check_state_based_
    actions` builds this per firing when a Siege's defense hits 0. That's
    also why it takes its source at construction rather than relying on a
    bind-time one.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.engine.exile_siege_for_transformed_cast(self.source)


class ReturnFromGraveyardTransformedEffect(GameEffect):
    """"Return this card from your graveyard to the battlefield transformed
    under its owner's control." (Bruce Banner-shaped) — the graveyard-
    sourced sibling of `ExileReturnTransformedEffect` above: a dies
    trigger's own subject is always the card that just died, so this is
    untargeted and always acts on ``self.source``, exactly like that
    sibling — never a chosen target. See `RulesEngine.return_from_graveyard`'s
    ``transformed`` param for the RULE 400.7 + RULE 712.8 mechanics (a
    genuine new-object zone change, then a forced flip onto the back face —
    not an in-place face swap). A no-op if ``self.source`` isn't actually
    sitting in a graveyard when this resolves (e.g. something else already
    moved it) or has no back face at all.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        context.return_from_graveyard(self.source, "battlefield", transformed=True)


class ReturnSelfFromGraveyardToBattlefieldEffect(GameEffect):
    """"Return this card from your graveyard to the battlefield[, tapped]."
    (Dread Wanderer/Bloodsoaked Champion/Drownyard Temple &c) — the plain
    (non-transforming) sibling of `ReturnFromGraveyardTransformedEffect`:
    untargeted, always ``self.source``, since an activated ability's/
    triggered ability's "this card" can only ever mean the permanent whose
    text prints it. A no-op if ``self.source`` isn't actually in a
    graveyard when this resolves.

    Named distinctly from `ReturnSelfFromGraveyardEffect` above (mill's
    RULE 112.6a "return it to your hand", a *different* shape — a per-
    firing ``obj``, not always ``self.source``, and to hand rather than the
    battlefield) rather than reusing that name for an unrelated effect.
    """

    def __init__(self, tapped: bool = False, source: Optional["GameObject"] = None):
        super().__init__(source)
        self.tapped = tapped

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        destination = "battlefield_tapped" if self.tapped else "battlefield"
        context.return_from_graveyard(self.source, destination)


class ReturnSelfFromGraveyardToHandEffect(GameEffect):
    """"Return this card from your graveyard to your hand." (PAR-16 —
    Abzan Devotee/Clay Revenant/Chandra's Phoenix/Aurora Eidolon &c) — the
    hand-destination sibling of `ReturnSelfFromGraveyardToBattlefieldEffect`
    right above: same untargeted, always-``self.source``, no-op-unless-
    still-in-the-graveyard shape, just a different destination (so no
    ``tapped`` param applies here). Two real printed shapes reach it: an
    activated ability living in the graveyard (`ActivationCost.
    graveyard_zone`, the same inference `effect_binder.bind_ability` already
    does for the battlefield sibling) and a *triggered* ability whose
    source likewise sits in the graveyard when it fires (RULE 113.6a — the
    Eidolon/Phoenix family, "Whenever `<event>`, [you may] return this card
    from your graveyard to your hand": `TriggeredAbility.
    functions_from_graveyard`, inferred the same way, and consulted by
    `RulesEngine._collect_triggers`'s graveyard scan since real printings
    carry no explicit "(this ability functions from your graveyard.)"
    reminder to key off instead).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        context.return_from_graveyard(self.source, "hand")


class ReturnDiesAsNewPermanentEffect(GameEffect):
    """"When ~ dies, return it to the battlefield. It's a[n] <type> with
    '<ability>'. ~ loses all other abilities." (Harold and Bob, First
    Numens) — a genuinely *different* card, not RULE 712.8's ordinary
    "return transformed" (`ReturnFromGraveyardTransformedEffect`, which
    needs a real printed back face): see `RulesEngine.return_dies_as_new_
    permanent`'s docstring for the mechanics (a synthetic `Card` built from
    ``new_type_line``/``new_oracle_text``, same name/owner/set).

    ``target_kind``, when given, is a real RULE 115 target this dies
    trigger resolves before returning (RULE 303.4a's "enchant Forest you
    control" — the specific permanent the new Aura form attaches to);
    mandatory (no ``target_spec.optional``), so a dying object with no
    legal target at all simply fizzles like any other single-target
    triggered ability, rather than returning unattached.
    """

    def __init__(
        self,
        new_type_line: str,
        new_oracle_text: str,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.new_type_line = new_type_line
        self.new_oracle_text = new_oracle_text
        self.target_spec = TargetSpec(kind=target_kind) if target_kind else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None or self.source.zone != Zone.GRAVEYARD:
            return
        attach_to = None
        if self.target_spec is not None:
            attach_to = targets[0] if targets else None
            if attach_to is None:
                return  # no legal target — the ability fizzles (RULE 608.2b)
        context.return_dies_as_new_permanent(
            self.source, self.new_type_line, self.new_oracle_text, attach_to=attach_to
        )


class PhaseOutEffect(GameEffect):
    """Phase a permanent out (RULE 702.26) — treated as though it doesn't
    exist until it phases back in at its controller's next untap step
    (`GameEngine._step_untap`'s RULE 702.26a sweep).

    Untargeted with ``target_kind=None`` (the default): phases out whatever
    is currently attached to this effect's own source ("Equipped creature
    phases out" — Robe of Stars' Astral Projection — no RULE 115 target,
    the same "defaults to its own source/host, no targeting" shape
    `TransformEffect`'s "transform ~" uses). ``target_kind="creature"``
    (etc.) targets some other permanent instead, same alternative
    `TransformEffect` offers.

    Any Aura/Equipment attached to the phasing-out permanent becomes
    unattached rather than phasing out together with it (RULE 702.26e-
    family simplification — no card needing a multi-permanent phase chain
    yet, see docs/implementation-state/BACKLOG.md).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = None,
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        if target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is not None:
            target = (targets[0] if targets else None) or self.target
        elif self.source is not None:
            host_id = getattr(self.source, "attached_to", None)
            target = context.state.find_object(host_id) if host_id is not None else None
        else:
            target = None
        if target is None:
            return
        target.phased_out = True
        for obj in context.state.battlefield:
            if obj.attached_to == target.instance_id:
                obj.attached_to = None


class BecomePreparedEffect(GameEffect):
    """A preparation card's own permanent becomes prepared (RULE 722.3a).

    Always self-only, unlike `TransformEffect` — RULE 722.3a's "~ becomes
    prepared" has no targeted form on any real card. Delegates to
    `RulesEngine.make_prepared`, which creates the exiled prepare-spell
    copy (RULE 722.3c) and is itself a no-op if the source is already
    prepared or has no prepare spell.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is not None:
            context.make_prepared(self.source)


#: `AddCountersEffect.selector`'s closed vocabulary — a mass, untargeted
#: "put a counter on each …" (RULE 601.2c), the group `continuous.
#: group_selector_objects` already resolves for pump/anthem clauses.
#: ``each_other_creature_you_control`` (MEC-11's Bellowing Aegisaur — "put a
#: +1/+1 counter on each **other** creature you control") is the RULE 109.5
#: "another" exclusion of the ability's own source, `group_selector_objects`'s
#: existing ``"other_creatures_you_control"`` affects value.
_ADD_COUNTERS_SELECTORS: frozenset[str] = frozenset(
    {"each_creature_you_control", "each_other_creature_you_control"}
)


class AddCountersEffect(GameEffect):
    """Put ``amount`` +1/+1 counters on a target creature — or on the source.

    Untargeted, it buffs the effect's own source (an activated "put a +1/+1
    counter on this creature"); with a ``target_kind`` it targets (RULE 122),
    optionally as an RULE 115.1a "up to one" pick, or ``count`` > 1 several
    independent targets at once (the same shape `DestroyEffect.count` uses —
    "put a +1/+1 counter on each of up to two target creatures", the
    Support-keyword-shaped family; note ``count`` here is the *target*
    count, distinct from ``amount``, the number of counters placed on each).
    ``selector`` (`_ADD_COUNTERS_SELECTORS` — RULE 601.2c, Vastwood Surge's
    "put two +1/+1 counters on each creature you control") is instead a
    mass, untargeted effect over the group `continuous.
    group_selector_objects` already resolves for pump/anthem clauses —
    mirrors `DealDamageEffect.selector`'s "no `target_spec` at all" shape.
    ``subtypes`` (Vault 12: The Necropolis's own chapter III — "each
    creature you control that's a Zombie or Mutant") further narrows that
    same mass group to an OR-combined creature-subtype filter, checked
    against the *live* object (unlike a DIES trigger's own subtype filter,
    every affected creature here is still on the battlefield) — a real,
    broader gap beyond this one card (tribal mass-counter effects are common).
    """

    def __init__(
        self,
        amount: int = 1,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
        kind: str = "+1/+1",
        optional: bool = False,
        selector: Optional[str] = None,
        count: int = 1,
        subtypes: Optional[list[str]] = None,
        trigger_subject_key: Optional[str] = None,
        divided: bool = False,
        amount_from_trigger_event: Optional[str] = None,
        x_multiplier: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        #: "Whenever you gain life, put that many +1/+1 counters on ~/target
        #: X." (Ageless Entity/Treebeard-shaped) — the event field name
        #: (``"amount"``) to read off `GameContext.trigger_event` at
        #: resolution, overriding ``amount`` when set. Same idiom as
        #: `LoseLifeEffect.amount_from_trigger_event`; deliberately only
        #: wired into the plain self/single-target branches below, since
        #: "that many" is inherently a single recipient, never a mass
        #: selector or an N>=2 multi-target pick.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "~ enters with twice X +1/+1 counters on it." (Banquet Guests) —
        #: a self-only ETB trigger reading the *source's own* announced
        #: {X} (`GameObject.x_paid`, RULE 107.3c — set at cast time,
        #: already present by the time this same object's own ENTERS_
        #: BATTLEFIELD trigger resolves) times this multiplier. Distinct
        #: from `_substitute_x`'s ``"x"`` sentinel, which only rewrites a
        #: *spell's own* resolution effects — a separately-fired triggered
        #: ability has no `StackItem.x` of its own to substitute against.
        self.x_multiplier = x_multiplier
        # PAR-15: "distribute N +1/+1 counters among any number of target
        # creatures" (Blessings of Nature/Jugan, the Rising Star/Verdurous
        # Gearhulk) — ``amount`` is then a *pool* split across whichever
        # targets were chosen (as evenly as possible, no explicit
        # ``division`` list — same documented simplification
        # `DealDamageEffect.divided`/`_apply_divided` uses for "damage
        # divided as you choose"), unlike the plain ``count`` > 1 shape
        # above where every target gets the *full* ``amount`` independently.
        self.divided = divided
        # The counter type: "+1/+1" (default) or "-1/-1" (RULE 122). Both shift
        # net P/T the same machinery, just with opposite sign.
        self.kind = kind
        self.selector = selector if selector in _ADD_COUNTERS_SELECTORS else None
        self.subtypes = [s.lower() for s in subtypes] if subtypes else None
        #: "Whenever a creature you control is dealt damage, put a +1/+1
        #: counter on **it**." (MEC-11's Rite of Passage) — an untargeted
        #: "it" here is *not* the ability's own source (Rite of Passage
        #: itself, an Enchantment) the way ``target_kind=None`` everywhere
        #: else in this class means, but whichever *group member* the
        #: RULE 603.1 trigger actually fired for. `parser/oracle/
        #: segmenter.py`'s group-subject damage-recipient handler sets this
        #: to the same event key (``"target_id"``) `effect_binder.
        #: _subject_event_key` resolves the trigger's own condition
        #: against, so the two always agree on which object "it" is.
        self.trigger_subject_key = trigger_subject_key
        if self.selector is None and target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind, optional=optional, count=count)

    def target_polarity(self) -> Optional[str]:
        # "-1/-1"/"stun" counters are a downgrade for whoever's stuck with
        # them; every other kind this class ever places (+1/+1 chief among
        # them) is a buff.
        return "harmful" if self.kind in ("-1/-1", "stun") else "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.x_multiplier is not None:
            x_paid = getattr(self.source, "x_paid", 0) or 0
            self.amount = self.x_multiplier * x_paid
        if self.trigger_subject_key:
            event = context.trigger_event
            obj_id = (event or {}).get(self.trigger_subject_key)
            target = context.state.find_object(obj_id) if obj_id is not None else None
            if target is not None:
                context.add_counters(target, self.amount, self.kind, source=self.source)
            return
        if self.selector in _ADD_COUNTERS_SELECTORS:
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            affects = "other_creatures_you_control" if self.selector == "each_other_creature_you_control" else "creatures_you_control"
            for obj in group_selector_objects(context.state, controller_id, affects, src=self.source):
                if self.subtypes is not None:
                    sub = obj.card.type_line.partition("—")[2].strip().lower().split()
                    if not any(s in sub for s in self.subtypes):
                        continue
                context.add_counters(obj, self.amount, self.kind, source=self.source)
            return
        if self.target_spec is not None and self.target_spec.count != 1:
            chosen = _chosen_targets(targets, self.target_spec.count)
            if not chosen:
                return
            if self.divided:
                total = self.amount if isinstance(self.amount, int) else 0
                base, extra = divmod(total, len(chosen))
                shares = [base + (1 if i < extra else 0) for i in range(len(chosen))]
            else:
                shares = [self.amount] * len(chosen)
            for target, share in zip(chosen, shares):
                if share > 0:
                    context.add_counters(target, share, self.kind, source=self.source)
            return
        if self.target_spec is not None:
            target = targets[0] if targets else None
        else:
            target = self.source
        amount = self.amount
        if self.amount_from_trigger_event:
            event = context.trigger_event
            amount = int((event or {}).get(self.amount_from_trigger_event) or 0)
        if target is not None and amount > 0:
            context.add_counters(target, amount, self.kind, source=self.source)


class RenownEffect(GameEffect):
    """RULE 702.112b: Renown N's own triggered-ability body — put ``amount``
    +1/+1 counters on this creature and it becomes renowned. A single
    atomic effect (not `AddCountersEffect` alone) since the "becomes
    renowned" flag has to flip together with the counters — it's what the
    keyword's own "if it isn't renowned" guard (`effect_binder.
    _keyword_triggered_abilities`) checks to fire only once per creature.
    """

    def __init__(self, amount: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        context.add_counters(self.source, self.amount, "+1/+1", source=self.source)
        self.source.renowned = True
        context.fire_event(GameEvent(EventType.RENOWNED, instance_id=self.source.instance_id))


class GrantUntilEffect(GameEffect):
    """RULE 611: create a continuous effect that lasts for a stated duration.

    The resolve-time counterpart of a permanent's printed static ability, and
    the general form of every "…until end of turn"-shaped grant: it builds a
    `StaticAbility` (so the grant goes through the RULE 613 layer engine like
    any other, rather than being a special case read by whoever happens to
    look) and parks it in `GameState.floating_statics`, where
    `game/durations.py` sweeps it at the window its ``duration`` names.

    Why this exists next to the ``temp_power``/``temp_keywords`` fields the
    shipped pump/grant effects use: those fields *are* "until end of turn" —
    they're cleared wholesale at cleanup (RULE 514.2) and have nowhere to
    record any other ending. "Until your next turn", "until end of combat"
    and RULE 611.2b's "for as long as `<condition>`" are unreachable that
    way. Existing effects are deliberately left on the old path; anything
    needing a *different* duration comes here.

    ``static`` is the `EffectSpec`-shaped payload for the underlying static
    (``{"type": "grant_keyword", "params": {...}}``), built by the binder
    from the same whitelisted registry every printed static goes through —
    card text never reaches the layer engine except as a registered type.
    """

    def __init__(
        self,
        static: Optional[dict[str, Any]] = None,
        duration: str = "end_of_turn",
        target_kind: Optional[str] = "creature",
        optional: bool = False,
        count: int = 1,
        condition: Optional[dict[str, Any]] = None,
        previous_subject: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.static = dict(static or {})
        self.duration = duration
        self.condition = dict(condition) if condition else None
        #: Apply to whatever the *previous clause* of this ability targeted
        #: ("Tap target land. It doesn't untap … for as long as ~ remains
        #: tapped.") instead of declaring a target of this effect's own.
        self.previous_subject = previous_subject
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional, count=count)
            if target_kind is not None and not previous_subject
            else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from . import durations  # local: durations imports effects' siblings

        spec_type = self.static.get("type")
        if not spec_type or not EffectRegistry.is_registered(str(spec_type)):
            return  # fail closed — an unregistered static grants nothing
        ability = EffectRegistry.create(str(spec_type), dict(self.static.get("params") or {}))
        if not isinstance(ability, StaticAbility):
            return
        controller_id = getattr(self.source, "controller_id", None)
        ability.source = self.source
        ability.duration = durations.normalize_duration(self.duration)
        ability.duration_data = {"player_id": controller_id}
        if self.condition is not None:
            # RULE 611.2b's condition-bounded duration: the effect *ends*
            # when this stops holding, unlike an ``active_if`` gate, which
            # merely lies dormant and can come back on.
            ability.duration = "for_as_long_as"
            ability.duration_data["condition"] = dict(self.condition)
        if self.target_spec is not None or self.previous_subject:
            # A targeted grant applies to exactly the permanents chosen —
            # `affects="objects"` reads the ids off the ability. With
            # ``previous_subject`` the referent is instead whatever the
            # *previous clause* of this same ability targeted ("Tap target
            # land. **It** doesn't untap … for as long as ~ remains tapped."),
            # the same `GameContext.previous_targets` pronoun `FightEffect`
            # and `GoadEffect` use.
            if self.previous_subject:
                chosen = list(context.previous_targets)
            else:
                chosen = list(targets or [])[: self.target_spec.count]
            ids = [t.instance_id for t in chosen if getattr(t, "instance_id", None) is not None]
            if not ids:
                return
            ability.affects = "objects"
            ability.object_ids = ids
        context.state.floating_statics.append(ability)
        # A new continuous effect changes derived characteristics immediately
        # (RULE 613.1) — the caller's SBA pass would get there anyway, but a
        # grant whose effect isn't visible until then reads as a bug.
        context.recompute()


class MonstrosityEffect(GameEffect):
    """RULE 701.37a: "Monstrosity N" — the body of ``<cost>: Monstrosity N``.

    Untargeted and always about the ability's own source (701.37b: only
    permanents become monstrous, and every printed monstrosity ability is the
    permanent's own), so there is no `TargetSpec` here at all — the
    `RenownEffect` shape rather than the `TapEffect` one.

    ``amount`` accepts the ``"x"`` sentinel `RulesEngine._substitute_x`
    rewrites with the announced {X} ("{X}{X}{R}: Monstrosity X", Fanatic of
    Xenagos-shaped), which is also what makes RULE 701.37c's "other abilities
    may refer to that X" work: `RulesEngine.monstrosity` records the
    substituted value on the permanent.
    """

    def __init__(self, amount: Any = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        # A still-unsubstituted "x" means no {X} was announced (a fixture, or
        # an ability reached outside the stack) — 0 is the honest reading.
        amount = self.amount if isinstance(self.amount, int) else 0
        context.monstrosity(self.source, amount)


class AdaptEffect(GameEffect):
    """RULE 701.46a: "Adapt N" — "if this permanent has no +1/+1 counters on
    it, put N +1/+1 counters on it".

    Deliberately its own effect rather than a conditional `AddCountersEffect`:
    the "has no +1/+1 counters" gate is part of the keyword action itself, and
    every real adapt card is an activated ability on the creature, so like
    `MonstrosityEffect` this is untargeted and self-scoped.
    """

    def __init__(self, amount: Any = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        amount = self.amount if isinstance(self.amount, int) else 0
        context.adapt(self.source, amount)


class GoadEffect(GameEffect):
    """RULE 701.15a: "Goad target creature" — and its "up to N target
    creatures" (RULE 115.1a) and pronoun forms.

    The goader is the effect's *controller* (701.15b: "a player other than
    the controller of the permanent, spell, or ability that caused it to be
    goaded"), read off the source at resolution rather than baked in at bind
    time, so a stolen/copied source goads for whoever controls it now.

    ``target_kind=None`` is the pronoun form — "…deals 2 damage to target
    creature. Goad that creature." (`GameContext.previous_targets`, the same
    referent `FightEffect` uses), or with ``referent="created"`` the tokens an
    earlier clause of this same resolution just made ("…each player creates a
    tapped 2/2 Bird. **The tokens** are goaded for the rest of the game.",
    `GameContext.created_objects`). ``selector`` is the untargeted mass form
    ("Goad all creatures your opponents control").

    ``permanent`` is the "…for the rest of the game" duration: the same
    designation with no expiry (`RulesEngine.goad`), rather than 701.15a's
    printed default of "until your next turn".
    """

    _SELECTORS = frozenset({"creatures_opponents_control"})
    _REFERENTS = frozenset({"previous", "created"})

    def __init__(
        self,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        optional: bool = False,
        count: Any = 1,
        selector: Optional[str] = None,
        count_selector: Optional[str] = None,
        referent: str = "previous",
        permanent: bool = False,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.selector = selector if selector in self._SELECTORS else None
        self.referent = referent if referent in self._REFERENTS else "previous"
        self.permanent = bool(permanent)
        self.target_spec = (
            TargetSpec(
                kind=target_kind,
                optional=optional,
                count=count if isinstance(count, int) else 1,
                count_selector=count_selector,
                # "For each opponent, goad up to one target creature **that
                # player** controls" — one requirement of "as many as there
                # are opponents", with the per-opponent half being exactly
                # RULE 115's already-modeled "controlled by different
                # players" constraint.
                distinct_controllers=count_selector == "opponents",
            )
            if target_kind is not None and self.selector is None
            else None
        )

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        goader_id = getattr(self.source, "controller_id", None)
        if goader_id is None:
            return
        if self.selector is not None:
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            for obj in group_selector_objects(context.state, goader_id, self.selector):
                context.goad(obj, goader_id, permanent=self.permanent)
            return
        if self.target_spec is None:
            # A pronoun: whatever the previous clause of this same ability
            # targeted, or created (RULE 608.2 resolution order — either way
            # it has already resolved by the time this effect runs).
            chosen = list(
                context.created_objects if self.referent == "created"
                else context.previous_targets
            )
        elif self.target_spec.count_selector or self.target_spec.count != 1:
            # A dynamic count is only known at announce time, so take
            # everything that was actually chosen rather than re-deriving it.
            chosen = list(targets or [])
        else:
            chosen = [targets[0]] if targets else []
        for obj in chosen:
            # A permanent, not a player: `previous_targets` and a shared
            # targets list can both hold either, and only a creature can be
            # goaded (RULE 701.15b). Duck-typed rather than `isinstance` —
            # `game/` must not import `models/` at runtime (the module
            # boundary; `GameObject` here is a TYPE_CHECKING name only).
            if getattr(obj, "instance_id", None) is not None:
                context.goad(obj, goader_id, permanent=self.permanent)


class LivingWeaponEffect(GameEffect):
    """RULE 702.92: "When this Equipment enters, create a 0/0 black
    Phyrexian Germ creature token, then attach this Equipment to it."

    A single atomic effect rather than `CreateTokenEffect` + `AttachEffect`:
    the attach target is the *specific* token this same effect just
    created, not a RULE 115 target or an entry off a shared targets list —
    there's no vocabulary for "whatever the previous effect just made" in
    the ordinary effects-list composition.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        from ..services.token_database import synthesize_token_card

        card = synthesize_token_card(
            "Phyrexian Germ", power=0, toughness=0, colors=["B"], subtypes=["Phyrexian", "Germ"]
        )
        tokens = context.engine.create_token(self.source.controller_id, card)
        if tokens:
            context.engine.attach_to_target(self.source, tokens[0])


class ClassLevelEffect(GameEffect):
    """Set a Class's class level (RULE 716.2c) — the effect of activating one
    of its "Level N: <cost>" abilities, not the cost itself (mirrors how
    Saga's chapter advance is a dedicated step, not a generic counter add).

    Sets the source's ``class_level`` counter directly to ``level`` (never
    incremented — a Class's level-up abilities are only ever legal one level
    at a time, `GameEngine._can_activate_class_level`) and fires
    `EventType.CLASS_LEVEL` so a rare "when this Class becomes level N"
    trigger can scope to it via the same ``chapter`` trigger key Saga's
    chapter triggers already use (`effect_binder._trigger_condition`).
    """

    def __init__(self, level: int, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.level = level

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = self.source
        if target is None:
            return
        target.counters["class_level"] = self.level
        context.state.fire_event(
            GameEvent(
                EventType.CLASS_LEVEL,
                object=target.name,
                instance_id=target.instance_id,
                controller_id=target.controller_id,
                chapter=self.level,
            )
        )


class ProliferateEffect(GameEffect):
    """RULE 701.30: give an additional counter of each kind already there to
    any number of permanents and/or players.

    RULE 701.30a's per-permanent/per-player "choose any number" is a real
    interactive choice this MVP doesn't offer (no counter-proliferation
    picker exists yet) — auto-applies to *every* permanent/player that
    already carries at least one counter, the same "auto-choose, no chooser
    in MVP" simplification `SacrificeEffect`/`GameEngine._sacrifice_
    candidate` use elsewhere. Player-level counters (poison via `Player.
    poison`, everything else — rad/energy/experience — via `Player.
    counters`) proliferate the same way (Vexing Radgull's own "otherwise,
    proliferate" branch needs exactly this: a player who already has rad
    counters gets another).

    ``times`` > 1 repeats the whole pass that many times (Contagion Engine's
    "Proliferate twice."/War of the Spark's "Proliferate three times.") —
    mirrors `ScryEffect.count`'s param shape.
    """

    def __init__(self, times: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.times = times

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for _ in range(self.times):
            for obj in list(context.state.battlefield):
                for kind in list(obj.counters.keys()):
                    if obj.counters.get(kind, 0) > 0:
                        context.add_counters(obj, 1, kind, source=self.source)
            for player in list(context.state.players):
                if player.poison > 0:
                    context.add_player_counters(player, 1, "poison", source=self.source)
                for kind in list(player.counters.keys()):
                    if player.counters.get(kind, 0) > 0:
                        context.add_player_counters(player, 1, kind, source=self.source)


class RemoveCountersEffect(GameEffect):
    """Strip counters from a target permanent (Vampire Hexmage-shaped:
    "Remove all counters from target permanent") or from every permanent on
    the battlefield (Oblivion Stone/Aether Snap/Thief of Blood-shaped:
    "Remove all counters from all permanents") — the unconditional "all"
    shape, ``max_count=None``. Goes through `context.add_counters` with a
    negative amount per kind (not a raw dict mutation), the same idiom
    `ProliferateEffect` uses, so a counter-removed trigger still fires
    correctly (RULE 122's `add_counters` already treats a non-positive
    amount as removal, bypassing replacement effects, which only ever apply
    to counters being *added*).

    ``max_count`` (Glissa Sunslayer/Heartless Act/Render Inert-shaped
    "remove up to N counters from target permanent/creature") switches to a
    genuinely different, interactive **chosen**-quantity shape instead:
    resolution opens a `pending_choice` (`RulesEngine.
    request_remove_counters_choice`) asking how many (0..min(max_count,
    counters present)), then — only if the target carries 2+ counter kinds —
    which kind to remove one at a time, mirroring `request_search`'s
    "open a choice, the engine's `resolve_*_choice` finishes it" shape
    rather than doing anything synchronously here.
    """

    def __init__(
        self,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
        max_count: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self.max_count = max_count
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def _strip(self, context: GameContext, obj: "GameObject") -> None:
        for kind in list(obj.counters.keys()):
            amount = obj.counters.get(kind, 0)
            if amount:
                context.add_counters(obj, -amount, kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.max_count is not None:
            target = targets[0] if targets else None
            if target is not None:
                context.engine.request_remove_counters_choice(
                    target, self.max_count, _controller_of(self.source, context)
                )
            return
        if self.target_spec is not None:
            target = targets[0] if targets else None
            if target is not None:
                self._strip(context, target)
            return
        for obj in list(context.state.battlefield):
            self._strip(context, obj)


class PumpEffect(GameEffect):
    """Give a target creature a temporary P/T boost and/or keywords "until end
    of turn" (Giant Growth; RULE 613.4d layer 7d + layer 6 for keywords).

    ``power``/``toughness`` may be negative (a "-N/-N" debuff). The change is
    an *effect* with a duration, not counters — it lives on the object's
    ``temp_*`` fields, which `continuous.recompute` folds in and the cleanup
    step (RULE 514.2) clears. Untargeted (no ``target_kind``) it pumps its own
    source, e.g. an activated "~ gets +1/+0 until end of turn". ``selector``
    (e.g. ``"creatures_you_control"``) pumps a whole *group* instead — an
    untargeted resolve-time selection (RULE 601.2c — not a target at all), the
    common Saga-chapter/anthem-spell shape "Creatures you control get +N/+N
    until end of turn" (e.g. History of Benalia's chapter III).

    ``unblockable=True`` additionally sets the target's ``temp_unblockable``
    flag (the same one `UnblockableEffect` sets) — "target creature gets
    +1/+0 until end of turn and can't be blocked this turn" (You Come to a
    River-shaped) is one *ability* with one target, not two independent
    targeting effects, so it's folded into this single effect (mirroring how
    a granted keyword already rides along in ``keywords``) rather than paired
    with a second `UnblockableEffect` that would ask for its own target.

    ``target_kind="attached_permanent"`` is a fourth mode — "{U}: Enchanted
    creature gains flying until end of turn." (Pemmin's Aura-shaped Aura
    activated ability): acts on whatever the effect's own source is
    currently `attached_to`, re-read live at resolution, no RULE 115 target
    at all — the same concept `TapEffect`'s own ``"attached_permanent"``
    mode uses, see its docstring.
    """

    def __init__(
        self,
        power: int = 0,
        toughness: int = 0,
        keywords: Optional[list[str]] = None,
        target_kind: Optional[str] = None,
        selector: Optional[str] = None,
        unblockable: bool = False,
        source: Optional["GameObject"] = None,
        count: int = 1,
        optional: bool = False,
        amount_from_trigger_event: Optional[str] = None,
        per_recipient_controller_counter: Optional[str] = None,
        amount_from_count_selector: Optional[str] = None,
        creature_filter: Optional[dict] = None,
    ) -> None:
        super().__init__(source)
        self.power = power
        self.toughness = toughness
        self.keywords = list(keywords or [])
        self.selector = selector
        self.unblockable = unblockable
        #: "Each creature your opponents control gets -1/-1 until end of
        #: turn for each poison counter its controller has." (Phyresis
        #: Outbreak-shaped) — unlike `amount_from_trigger_event` (one
        #: shared magnitude for the whole group), each recipient's own
        #: boost scales independently by *its own controller's* count of
        #: this player-counter kind; ``power``/``toughness`` become the
        #: per-counter multiplier (``-1``) rather than a flat delta.
        #: ``selector``-only (no real card needs this on a single target).
        self.per_recipient_controller_counter = per_recipient_controller_counter
        #: "Whenever you gain life, ~ gets +X/+X until end of turn, where X
        #: is the amount of life you gained." (Field-Tested Frying Pan's
        #: granted ability) — the event field name (``"amount"``) to read
        #: off `GameContext.trigger_event` at resolution, overriding both
        #: ``power`` and ``toughness`` with the same value (always a
        #: symmetric "+X/+X" in practice). Same idiom as `LoseLifeEffect.
        #: amount_from_trigger_event`.
        self.amount_from_trigger_event = amount_from_trigger_event
        #: "Creatures you control gain trample and get +X/+X until end of
        #: turn, where X is the number of creatures you control."
        #: (Craterhoof Behemoth-shaped) — one shared magnitude for the
        #: whole group (unlike `per_recipient_controller_counter`'s
        #: per-object scaling), computed live via `continuous.
        #: count_selector` at resolve time rather than read off a firing
        #: event (`amount_from_trigger_event`'s job) — there's no trigger
        #: event to read here, this is the board state itself.
        self.amount_from_count_selector = amount_from_count_selector
        self._attached_mode = target_kind == "attached_permanent"
        if target_kind is not None and not self._attached_mode:
            # PAR-15: "any number of target creatures each get +N/+N [and
            # gain `<keyword>`] until end of turn" (Aerial Formation/Ajani's
            # Presence/Colossal Heroics-shaped) — ``count`` > 1 is the same
            # "each of N gets the *full* amount" shape `AddCountersEffect`'s
            # own N>=2 mode uses (as opposed to a *divided* pool), since a
            # pump spell's whole point is every chosen creature getting the
            # stated boost independently.
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, count=count, creature_filter=creature_filter,
            )

    def target_polarity(self) -> Optional[str]:
        return "harmful" if (self.power < 0 or self.toughness < 0) else "beneficial"

    def _pump_one(self, obj: "GameObject") -> None:
        obj.temp_power += self.power
        obj.temp_toughness += self.toughness
        obj.temp_keywords.update(self.keywords)
        if self.unblockable:
            obj.temp_unblockable = True
        # Record a per-source breakdown for the board's per-card effect
        # summary (display-only — the aggregate ints above drive the math).
        if self.power or self.toughness or self.keywords:
            obj.temp_effects.append(
                {
                    "source": self.source.name if self.source is not None else "Effekt",
                    "power": self.power,
                    "toughness": self.toughness,
                    "keywords": list(self.keywords),
                }
            )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.amount_from_trigger_event:
            event = context.trigger_event
            amount = int((event or {}).get(self.amount_from_trigger_event) or 0)
            self.power = amount
            self.toughness = amount
            if amount <= 0:
                return
        if self.amount_from_count_selector:
            from . import continuous  # avoid the continuous↔effects import cycle

            controller_id = getattr(self.source, "controller_id", None)
            amount = continuous.count_selector(context.state, controller_id, self.amount_from_count_selector)
            self.power = amount
            self.toughness = amount
            if amount <= 0:
                return
        if self.selector is not None:
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            group = group_selector_objects(context.state, controller_id, self.selector, src=self.source)
            if self.per_recipient_controller_counter:
                base_power, base_toughness = self.power, self.toughness
                for obj in group:
                    owner = context.state.player_by_id(obj.controller_id)
                    n = getattr(owner, self.per_recipient_controller_counter, 0) if owner else 0
                    self.power, self.toughness = base_power * n, base_toughness * n
                    self._pump_one(obj)
                self.power, self.toughness = base_power, base_toughness
                context.recompute()
                return
            for obj in group:
                self._pump_one(obj)
            context.recompute()
            return
        if self._attached_mode:
            host_id = getattr(self.source, "attached_to", None)
            target = context.state.find_object(host_id) if host_id is not None else None
        elif self.target_spec is not None:
            if self.target_spec.count != 1:
                chosen = _chosen_targets(targets, self.target_spec.count)
                for obj in chosen:
                    self._pump_one(obj)
                if chosen:
                    # Re-derive P/T now so a lethal -X/-X is caught by the
                    # SBA pass the caller runs right after this resolution.
                    context.recompute()
                return
            target = targets[0] if targets else None
        else:
            target = self.source
        if target is None:
            return
        self._pump_one(target)
        # Re-derive P/T now so a lethal -X/-X (toughness → 0) is caught by the
        # SBA pass the caller runs right after this resolution.
        context.recompute()


class ScryEffect(GameEffect):
    """Scry ``count`` for the effect's controller (RULE 701.18)."""

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.scry(player, self.count)


class SurveilEffect(GameEffect):
    """Surveil ``count`` for the effect's controller (RULE 701.31)."""

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.surveil(player, self.count)


class ManifestEffect(GameEffect):
    """Manifest (RULE 701.40a) or cloak (RULE 701.58a) the top ``count``
    cards of the effect controller's library.

    One effect for both keyword actions because they *are* the same action
    bar one characteristic — a cloaked permanent has ward {2} (701.58a) —
    which `RulesEngine.manifest` takes as its ``kind``, exactly the way the
    engine already parameterizes morph vs. disguise."""

    def __init__(
        self, count: int = 1, kind: str = "manifest", source: Optional["GameObject"] = None
    ) -> None:
        super().__init__(source)
        self.count = count
        self.kind = kind

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.manifest(player, self.count, kind=self.kind)


class ManifestDreadEffect(GameEffect):
    """"Manifest dread": look at the top two cards of your library, put one
    onto the battlefield face down and the other into your graveyard (RULE
    701.40a plus a look-and-choose wrapper).

    The choice is a real interactive one (`RulesEngine.request_manifest_dread`)
    rather than "take the top card", since which of the two is worth
    manifesting — and which is worth *binning*, for a graveyard deck — is
    the whole decision the mechanic exists for."""

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.request_manifest_dread(player)


class CreateTokenEffect(GameEffect):
    """Create one or more token permanents (RULE 111.5 / 701.6).

    A **named** token (``token_name`` with no inline stats) is looked up in the
    curated `TokenDatabase` so it keeps its real abilities (a Treasure's mana
    ability, a Clue's sacrifice-to-draw); an **inline** token (power/toughness
    + colours + subtypes from the oracle clause) is synthesized. Either way the
    created objects are flagged tokens, so RULE 704.5d removes them the instant
    they leave the battlefield. The tokens are created under the effect's
    controller (its source's controller, else the active player).

    ``count_selector``, when given, overrides ``count`` with a live
    `continuous.count_selector` evaluation at resolve time — "create X
    Treasure tokens, where X is the number of artifacts and enchantments
    your opponents control" (Dockside Extortionist-shaped), scoped to the
    effect's own controller the same way a per-count anthem's ``power_
    count`` is.

    ``creators`` is who does the creating: the effect's own controller by
    default, or **every** player / every opponent ("Each player creates three
    tapped 1/1 white Warrior creature tokens." — The War Games), each getting
    their own ``count`` tokens under their own control. ``tapped`` is the
    "creates a **tapped** …" wording (RULE 110.5a — a permanent enters
    untapped unless an effect says otherwise), applied as the token enters
    rather than as a separate tap, so nothing sees it untapped in between.

    Whatever it creates is appended to `GameContext.created_objects`, which
    is how a following clause says "**the tokens** are goaded".
    """

    _CREATORS = frozenset({"you", "each_player", "each_opponent"})

    def __init__(
        self,
        count: int = 1,
        token_name: Optional[str] = None,
        power: Optional[int] = None,
        toughness: Optional[int] = None,
        colors: Optional[list[str]] = None,
        subtypes: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
        count_selector: Optional[str] = None,
        creators: str = "you",
        tapped: bool = False,
        legendary: bool = False,
        pt_from_trigger_event: Optional[str] = None,
        count_from_trigger_event: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.token_name = token_name
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.keywords = keywords or []
        self.count_selector = count_selector
        self.creators = creators if creators in self._CREATORS else "you"
        self.tapped = bool(tapped)
        self.legendary = bool(legendary)
        # "…create an X/X blue Shark creature token with flying, where X is
        # that spell's mana value." (Shark Typhoon-shaped) — an X/X token
        # sized off the firing `SPELL_CAST` event's own field, read fresh at
        # resolve time (same idiom as `PumpEffect.amount_from_trigger_event`)
        # rather than a fixed ``power``/``toughness``. Always symmetric X/X
        # in practice, so one field sets both.
        self.pt_from_trigger_event = pt_from_trigger_event
        #: "…create **that many** 1/1 green Elf Warrior creature tokens."
        #: (Lathril, Blade of the Elves-shaped "whenever ~ deals combat
        #: damage to a player" payoff — "that many" always refers back to
        #: the firing event's own ``amount``, RULE 603.1) — the *count*
        #: sibling of ``pt_from_trigger_event`` (a token's stats, not how
        #: many get made). Overrides ``count``/``count_selector`` when set.
        self.count_from_trigger_event = count_from_trigger_event

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..services.token_database import default_token_database, synthesize_token_card

        power, toughness = self.power, self.toughness
        if self.pt_from_trigger_event:
            event = context.trigger_event
            x = int((event or {}).get(self.pt_from_trigger_event) or 0)
            power, toughness = x, x
        card = None
        # A bare named token (no inline stats) → the curated catalogue, so it
        # keeps its printed abilities. Inline stats always synthesize.
        if self.token_name and power is None and toughness is None:
            card = default_token_database().get_token(self.token_name)
        if card is None:
            card = synthesize_token_card(
                self.token_name or (self.subtypes[0] if self.subtypes else "Token"),
                power=power,
                toughness=toughness,
                colors=self.colors,
                subtypes=self.subtypes,
                keywords=self.keywords,
                legendary=self.legendary,
            )
        controller_id = (
            self.source.controller_id if self.source is not None
            else context.active_player.id
        )
        count = self.count
        if self.count_selector:
            from . import continuous  # avoid the continuous↔effects import cycle

            count = continuous.count_selector(context.state, controller_id, self.count_selector)
        if self.count_from_trigger_event:
            event = context.trigger_event
            count = int((event or {}).get(self.count_from_trigger_event) or 0)
        if count <= 0:
            return
        if self.creators == "each_player":
            creator_ids = [p.id for p in context.state.living_players()]
        elif self.creators == "each_opponent":
            creator_ids = [p.id for p in context.state.living_players() if p.id != controller_id]
        else:
            creator_ids = [controller_id]
        for creator_id in creator_ids:
            made = context.create_token(creator_id, card, count) or []
            if self.tapped:
                for token in made:
                    token.tapped = True
            # The referent for a following "the tokens are …" clause.
            context.created_objects.extend(made)


class CopyPermanentEffect(GameEffect):
    """Create a token that's a copy of a target permanent (RULE 707 / 707.2)
    — or, with ``target_kind=None``, of the effect's own source, untargeted
    (Bloodforged Battle-Axe's "create a token that's a copy of this
    Equipment" — no player choice involved, mirroring `TapEffect`'s/
    `AddCountersEffect`'s same ``target_kind=None`` self-acting mode).

    Targets a permanent (a creature by default — "create a token that's a copy
    of target creature") and makes ``count`` token copies under the effect's
    controller (its source's controller, else the active player). The basic
    version copies the printed card; layered/copy-of-copy nuances (RULE 707.2
    copiable values, other copy effects) are not modeled."""

    def __init__(
        self,
        count: int = 1,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        count_if_kicked: Optional[int] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        # RULE 702.33b's *override* kicked-conditional ("Create a token
        # that's a copy of target creature. If this spell was kicked,
        # create five of those tokens instead." — Rite of Replication) —
        # same shape as `DealDamageEffect.amount_if_kicked`, just overriding
        # ``count`` instead of ``amount``.
        self.count_if_kicked = count_if_kicked
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None and self.target_spec is None:
            target = self.source
        if target is None:
            return
        controller_id = (
            self.source.controller_id if self.source is not None
            else context.active_player.id
        )
        kicker_count = getattr(self.source, "kicker_count", 0) or 0
        count = self.count_if_kicked if (self.count_if_kicked is not None and kicker_count > 0) else self.count
        context.copy_permanent(controller_id, target, count)


class EnterAsCopyReplacement(GameEffect):
    """"You may have this permanent enter the battlefield as a copy of
    target X" (RULE 614.1c/614.12, Clever Impersonator/Phantasmal Image/Copy
    Artifact/Vesuvan Shapeshifter-style) — a pure data holder, never applied
    imperatively (``apply`` returns ``None``, same "consulted elsewhere"
    idiom as `StaticAbility`/`ReplacementEffect`).

    `RulesEngine._offer_enter_as_copy` reads this off `GameObject.
    enter_as_copy_effects` at the one choke point where the permanent is
    about to be added to the battlefield (`resolve_top_of_stack`/
    `create_token`), *before* `add_to_battlefield`/`ENTERS_BATTLEFIELD` — so
    the object is never observably "itself" first, unlike the previous
    ENTERS_BATTLEFIELD-trigger modeling this replaces. A legal-target check
    there resolves the choice (interactively, if 2+ options) and calls
    `copy_mechanics.become_copy` before finishing battlefield entry.

    ``add_types``/``add_subtypes`` cover a card's own "except it's a(n) X in
    addition to its other types" clause (`Card.as_copy`).
    """

    def __init__(
        self,
        target_kind: str = "permanent",
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
        optional: bool = True,
        description: str = "",
    ) -> None:
        super().__init__(None)
        self.target_kind = target_kind
        self.add_types = list(add_types or [])
        self.add_subtypes = list(add_subtypes or [])
        self.optional = optional
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_as_copy, not applied


class ChooseCreatureTypeReplacement(GameEffect):
    """"As ~ enters, choose a creature type." (RULE 601.2b-style
    characteristic-defining choice made as part of entering — not a
    triggered ability, so it's an ``enter_replacement`` like
    `EnterAsCopyReplacement`, just without a target — a pure data holder
    (``apply`` is never called).

    `RulesEngine._offer_enter_choices` reads this off `GameObject.
    enter_choice_effects` at the same battlefield-entry choke point
    `_offer_enter_as_copy` reads `enter_as_copy_effects` from, and stamps the
    answer onto `GameObject.chosen_type` — read back by `game/continuous.py`'s
    ``subtype_from_source`` selector param (Adaptive Automaton/Arcane
    Adaptation-shaped "creatures you control of the chosen type …"/"~ is the
    chosen type in addition to its other types" lords).
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseBasicLandTypeReplacement(GameEffect):
    """"As ~ enters, choose a basic land type." (RULE 601.2b, PAR-4 —
    Realmwright/A-Thran Portal-shaped) — the basic-land-type sibling of
    `ChooseCreatureTypeReplacement`; see its docstring. Deliberately its own
    class (rather than a flag on `ChooseCreatureTypeReplacement`) so
    `RulesEngine._offer_enter_choices` can tell which fixed option list to
    offer, but it stamps the very same `GameObject.chosen_type` field —
    "the chosen type" grant clause (`continuous.py`'s ``subtype_from_source``
    selector, already shipped for the creature-type family) reads a bare
    subtype string either way and doesn't care which family produced it.
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseColorReplacement(GameEffect):
    """"As ~ enters, choose a color." — the colour sibling of
    `ChooseCreatureTypeReplacement`; see its docstring. Stamps
    `GameObject.chosen_color`, read by `continuous.py`'s
    ``color_from_source`` selector param.
    """

    def __init__(self, description: str = "") -> None:
        super().__init__(None)
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class ChooseNamedModeReplacement(GameEffect):
    """"As this enters, choose <Label1> or <Label2>." (Struggle for Project
    Purity: "choose Brotherhood or Enclave") — a third `enter_choice_effects`
    sibling of `ChooseCreatureTypeReplacement`/`ChooseColorReplacement`,
    for a small closed set of *named* flavour modes rather than a creature
    type/colour. Each subsequent named-bullet ability ("Brotherhood — ...",
    "Enclave — ...") stays a normal, always-bound ability, just gated by
    `effect_binder._trigger_condition`'s ``"named_mode"`` predicate
    checking the answer this stamps onto `GameObject.chosen_mode` — so the
    "wrong" mode's ability simply never fires, rather than never being
    bound at all.

    ``options`` is the card's own printed label list (``["Brotherhood",
    "Enclave"]``); `RulesEngine._offer_enter_choices` offers them as a
    lowercase-slug choice and stamps the answer onto `chosen_mode`.
    """

    def __init__(self, options: Optional[list[str]] = None, description: str = "") -> None:
        super().__init__(None)
        self.options = list(options or [])
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # consulted by RulesEngine._offer_enter_choices, not applied


class BecomeCopyUntilEndOfTurnEffect(GameEffect):
    """*This* permanent becomes a copy of a target creature until end of
    turn (Cursed Mirror-style: "{T}: ~ becomes a copy of target creature
    until end of turn.").

    Unlike `RulesEngine.become_copy` (a permanent mutation, RULE 706.2), this
    reverts automatically at cleanup (RULE 514.2) — see `RulesEngine.
    become_copy_until_end_of_turn` and `GameEngine._step_cleanup`.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None or self.source is None or target is self.source:
            return
        context.become_copy_until_end_of_turn(self.source, target)


class SetCopyTargetEffect(GameEffect):
    """Choose/change the target a layer-1 conditional-copy static ability
    copies (Vesuvan Shapeshifter's "you may have it be a copy of another
    target creature") — sets `GameObject.copy_target_id`, which
    `continuous.recompute`'s layer-1 pass (`_apply_copy_layer`) reads fresh
    every pass. A simplified stand-in for RULE 707.9's "special action"
    timing (the same simplification tier `EnterAsCopyReplacement` uses
    elsewhere) — modeled as a costless activated ability instead.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None or self.source is None or target is self.source:
            return
        context.set_copy_target(self.source, target)


class SearchLibraryEffect(GameEffect):
    """Search the controller's library for a card (RULE 701.19), tutors.

    The search is parameterized on two independent axes so one effect covers
    the whole tutor family (Demonic Tutor, Rampant Growth, Cultivate, Vampiric
    Tutor, Entomb, …):

    * ``criteria`` — *what* to look for, as pure data understood by
      `models.card_query`: ``""`` for "a card", a type string like
      ``"Creature"``, or a dict like ``{"type": ["Plains", "Island"]}`` /
      ``{"basic": True}`` / ``{"type": "Creature", "max_mana_value": 3}``.
    * ``destination`` — *where* the found card goes: ``"hand"`` (default),
      ``"battlefield"``, ``"battlefield_tapped"``, ``"library_top"``,
      ``"library_bottom"``, ``"graveyard"``, or ``"exile"``.
    * ``count`` — how many cards (search for "up to N"); the choice is
      offered one card at a time.
    * ``zones`` — *where* to look: ``["library"]`` (default, RULE 701.19)
      or ``["library", "graveyard"]``/``["graveyard"]`` for "search your
      library and/or graveyard" (backgrounds/Lurrus-shaped).
    * ``destinations`` — an optional per-found-card override list,
      positional against the picks, for a split destination ("put one onto
      the battlefield tapped and the other into your hand" —
      Cultivate/Kodama's Reach); ``destination`` remains the fallback.
    * ``destination_if`` — a *conditional* override instead of a positional
      one: ``[{"criteria": {"type": "Land"}, "destination":
      "battlefield_tapped"}]`` is Archdruid's Charm's "put it onto the
      battlefield tapped if it's a land card. Otherwise, put it into your
      hand." Which branch applies depends on the card the player actually
      found, so it can only be decided once the search is answered.
    * ``exile_rest`` — once the search finishes, exile every remaining
      criteria-matching card still in ``zones`` and skip the shuffle
      entirely (Doomsday-shaped).

    Because *which* card is a player choice, this doesn't move a card itself
    — it asks the engine to open a choice (`GameContext.request_search`); the
    chosen card(s) are moved to their destination(s) and the library
    shuffled (unless ``exile_rest``) when the player answers.

    ``mana_value_from`` makes the criteria's mana-value bound *dynamic*
    rather than printed: ``{"source": "sacrificed_cost", "plus": 2, "cmp":
    "le"}`` is Eldritch Evolution's "with mana value X or less, where X is 2
    plus the sacrificed creature's mana value"; ``"cmp": "eq"`` is Neoform's
    exact "equal to 1 plus …". The base value is read off the spell object's
    own `GameObject.sacrificed_cost_mana_value`, stamped when the RULE
    601.2b additional cost was paid — `StackItem.x` can't carry it (it only
    ever threads an *announced* {X}). Merged into ``criteria`` at resolution
    time as ``max_mana_value``/``mana_value``, so `models.card_query` needs
    no dynamic vocabulary of its own.

    ``type_restriction`` is accepted as a deprecated alias for a string
    ``criteria`` so older fixtures keep working.
    """

    def __init__(
        self,
        criteria: Any = "",
        destination: str = "hand",
        count: int = 1,
        optional: bool = True,
        player: Any = None,
        source: Optional["GameObject"] = None,
        type_restriction: Optional[str] = None,
        zones: Optional[list[str]] = None,
        destinations: Optional[list[str]] = None,
        exile_rest: bool = False,
        mana_value_from: Optional[dict[str, Any]] = None,
        extra_counters: Optional[dict[str, Any]] = None,
        destination_if: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        super().__init__(source)
        #: A per-found-card *conditional* destination (RULE 701.19c), unlike
        #: the positional ``destinations`` above: a list of ``{"criteria":
        #: <card_query>, "destination": <str>}`` rules, first match wins,
        #: falling back to ``destinations``/``destination``. Archdruid's
        #: Charm's "put it onto the battlefield tapped **if it's a land
        #: card**. Otherwise, put it into your hand." — the branch depends
        #: on *which* card the player found, so it can't be decided when the
        #: search is opened.
        self.destination_if = destination_if
        self.criteria = type_restriction if type_restriction is not None else criteria
        self.destination = destination
        self.count = count
        self.optional = optional
        self.player = player
        self.zones = zones
        self.destinations = destinations
        self.exile_rest = exile_rest
        self.mana_value_from = mana_value_from
        #: "…put that card onto the battlefield **with an additional +1/+1
        #: counter on it**" (Neoform) — ``{"kind": "+1/+1", "count": 1}``,
        #: applied by `RulesEngine.resolve_search_choice` right after the
        #: found card reaches the battlefield.
        self.extra_counters = extra_counters

    def _resolved_criteria(self) -> Any:
        """``criteria`` with any `mana_value_from` bound to a real number."""
        if not self.mana_value_from:
            return self.criteria
        base = getattr(self.source, "sacrificed_cost_mana_value", None)
        if base is None:
            # RULE 601.2b's cost was never paid (or the record is gone) —
            # fail closed to "nothing matches" rather than silently
            # searching for an unrestricted card.
            base = -1
        value = base + int(self.mana_value_from.get("plus", 0))
        criteria = dict(self.criteria) if isinstance(self.criteria, dict) else (
            {"type": self.criteria} if self.criteria else {}
        )
        criteria["max_mana_value"] = value
        if self.mana_value_from.get("cmp") == "eq":
            # `card_query` has no single "exactly N" key — an equal bound is
            # the two-sided one (Neoform's "mana value equal to 1 plus …").
            criteria["min_mana_value"] = value
        return criteria

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.request_search(
            player, self._resolved_criteria(), self.destination, self.count, self.optional,
            zones=self.zones, destinations=self.destinations, exile_rest=self.exile_rest,
            extra_counters=self.extra_counters, destination_if=self.destination_if,
        )


# ---------------------------------------------------------------------------
# Registry (docs/07 PART 4 Option C / PART 6)
# ---------------------------------------------------------------------------


class ImpulsiveLookEffect(GameEffect):
    """"Look at the top N cards, take one matching a filter, rest to Y"
    (Grisly Salvage/Commune with the Gods-shaped) — distinct from
    `SearchLibraryEffect` (searches the *whole* library, always shuffles
    afterwards) and `top_library.py`'s standing "look at/play from the top"
    permission (never moves a card). Peels exactly ``count`` cards, offers a
    choice among only the ones matching ``criteria``, routes the pick to
    ``hit_destination`` and the rest to ``miss_destination`` (see
    `GameContext.impulsive_look`/`RulesEngine.request_impulsive_look`).
    """

    def __init__(
        self,
        count: int = 1,
        criteria: Any = "",
        hit_destination: str = "hand",
        miss_destination: str = "graveyard",
        optional: bool = True,
        player: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.criteria = criteria
        self.hit_destination = hit_destination
        self.miss_destination = miss_destination
        self.optional = optional
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.impulsive_look(
            player, self.count, self.criteria,
            self.hit_destination, self.miss_destination, self.optional,
        )


class ImpulsiveDrawEffect(GameEffect):
    """Exile the top ``count`` cards of the library; their controller may
    play any of them through the end of their next turn (RULE 601.3b
    analogue, Light Up the Stage-shaped "impulsive draw") — every card
    exiled becomes playable, unlike `ImpulsiveLookEffect`'s filtered
    choice-and-route shape (see `GameContext.exile_with_play_permission`/
    `RulesEngine.exile_with_play_permission`).

    ``player`` (whose library is exiled from) and ``permission_player``
    (who may play the exiled card) default to the same player — Light Up
    the Stage's own shape — but can differ (Ragavan, Nimble Pilferer-shaped:
    exile from *the player Ragavan just damaged*, permission to Ragavan's
    own controller). ``same_turn_only`` shortens the window from "until
    the end of your next turn" to "until end of turn" (Ragavan's own,
    shorter clause) — see `RulesEngine.exile_with_play_permission`.
    """

    def __init__(
        self,
        count: int = 1,
        player: Any = None,
        permission_player: Any = None,
        same_turn_only: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.player = player
        self.permission_player = permission_player
        self.same_turn_only = same_turn_only

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        permission_player = self.permission_player or player
        source_name = self.source.name if self.source is not None else None
        context.exile_with_play_permission(
            player, self.count, source_name=source_name,
            permission_player=permission_player, same_turn_only=self.same_turn_only,
        )


class DrawRevealCastOneFreeEffect(GameEffect):
    """"Draw N cards and reveal them. You may cast one of them without
    paying its mana cost." (RULE 121/601.3b combo — Dungeon of the Mad
    Mage's own "Mad Wizard's Lair" room, PAR-13).

    Reveal is purely informational (RULE 701.28 — no hidden-zone state to
    model, since `services/game_session.py`'s own redaction already keeps
    a hand private otherwise), so this only draws, then offers
    `RulesEngine.request_choose_objects`'s ``"cast_free"`` action over
    *exactly* the cards this draw put into hand (never the rest of the
    hand) — snapshotting the hand before/after rather than assuming a
    fixed append count, since a draw can be redirected (RULE 121.5's
    replacement family) or silently capped (a draw-limit static).
    """

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.count <= 0:
            return
        before = list(player.hand)
        context.draw(player, self.count)
        drawn = [c for c in player.hand if c not in before]
        if drawn:
            context.choose_objects(
                player, drawn, "cast_free", count=1, optional=True, source=self.source,
            )


class ReturnRemainingExiledEffect(GameEffect):
    """RULE 603.7 delayed cleanup: whichever of ``instance_ids`` are still
    sitting in exile move to their owner's graveyard — Mnemonic Betrayal's
    own "at the beginning of the next end step, if any of those cards
    remain exiled, return them to their owners' graveyards." Anything
    already cast by then is simply gone from the zone check (it resolved,
    or is on the stack/battlefield/graveyard through its own path), so this
    only ever touches leftovers. Plain data (``instance_ids`` are ints), so
    it survives `GameState.clone` like any other armed `DelayedTrigger`.
    """

    def __init__(self, instance_ids: list[int], source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.instance_ids = list(instance_ids)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for iid in self.instance_ids:
            obj = context.state.find_object(iid)
            if obj is None or obj.zone != Zone.EXILE:
                continue
            owner = context.state.player_by_id(obj.owner_id)
            owner.remove_from_zone(obj, Zone.EXILE)
            owner.add_to_zone(obj, Zone.GRAVEYARD)
            context.state.temp_play_permissions.pop(iid, None)
            context.state.temp_play_permission_player.pop(iid, None)
            context.state.temp_play_permission_source.pop(iid, None)
            context.state.mana_wildcard_permission.pop(iid, None)


class GraveyardImpulsiveCastEffect(GameEffect):
    """"Exile all opponents' graveyards. You may cast spells from among
    those cards this turn, and mana of any type can be spent to cast them.
    At the beginning of the next end step, if any of those cards remain
    exiled, return them to their owners' graveyards." (Mnemonic Betrayal) —
    the graveyard-sourced sibling of `ImpulsiveDrawEffect`'s library-top
    exile: the same dual-player permission shape (exile-owner vs.
    permission-holder can differ, `RulesEngine._grant_temp_play_permission`)
    plus RULE 605.1a's broadest "any type" mana-wildcard grant (``ManaPool``'s
    ``wildcard="type"``, see `RulesEngine.cast_spell`) and a RULE 603.7
    delayed cleanup (`ReturnRemainingExiledEffect`) for whatever's left
    unexiled at the next end step.
    """

    def __init__(
        self,
        mana_wildcard: Optional[str] = "type",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.mana_wildcard = mana_wildcard

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..models.game_state import DelayedTrigger  # avoid effects↔game_state cycle

        controller_id = getattr(self.source, "controller_id", None) or context.active_player.id
        controller = context.state.player_by_id(controller_id)
        source_name = self.source.name if self.source is not None else None
        exiled_ids: list[int] = []
        for player in context.state.living_players():
            if player.id == controller_id or not player.graveyard:
                continue
            exiled = context.engine.exile_graveyard_with_cast_permission(
                player, controller, source_name=source_name, mana_wildcard=self.mana_wildcard,
            )
            exiled_ids.extend(obj.instance_id for obj in exiled)
        if not exiled_ids:
            return
        context.state.delayed_triggers.append(
            DelayedTrigger(
                controller_id=controller_id,
                step="end",
                scope="any",
                effects=[ReturnRemainingExiledEffect(exiled_ids, source=self.source)],
                description=f"{source_name}: restliche Karten zurückgeben" if source_name else "",
            )
        )


class ShuffleLibraryEffect(GameEffect):
    """Shuffle the controller's (or a target player's) library (RULE 701.20)."""

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or (targets[0] if targets else None) or context.active_player
        context.shuffle_library(player)


class WheelEffect(GameEffect):
    """"Each player shuffles their hand and graveyard into their library,
    then draws seven cards." (Timetwister/Time Reversal/Echo of Eons — the
    identical printed line across all three, so this is a shared, not
    Timetwister-specific, effect.) An RULE 601.2c untargeted "each player"
    effect, unlike `DrawCardEffect`'s single-player default — resolved in
    an arbitrary player order (APNAP order has no observable effect here:
    every player's own shuffle only touches their own zones).
    """

    def __init__(self, draw_count: int = 7, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.draw_count = draw_count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for player in list(context.state.living_players()):
            context.shuffle_hand_and_graveyard_into_library(player)
            context.draw(player, self.draw_count)


class WindfallEffect(GameEffect):
    """"Each player discards their hand, then draws cards equal to the
    greatest number of cards a player discarded this way." (Windfall) —
    every player discards first (RULE 101.4's simultaneous-turn-based-action
    idiom this engine approximates with a plain sequential loop, same as
    `WheelEffect`), *then* every player draws the shared maximum, so a
    player who discards zero still draws if anyone else discarded more.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        players = list(context.state.living_players())
        discarded: dict[str, int] = {}
        for player in players:
            discarded[player.id] = len(player.hand)
            context.discard(player, discarded[player.id])
        greatest = max(discarded.values(), default=0)
        if greatest:
            for player in players:
                context.draw(player, greatest)


class CascadeEffect(GameEffect):
    """Cascade (RULE 702.85): free-cast the first cheaper nonland from the top.

    Exiles from the top of the library until a nonland card with mana value
    *less than* the cascade spell's, which the controller may cast without
    paying; the rest go to the bottom in a random order. This is a cast (it
    uses the stack), not a "put onto the battlefield" — the distinction the
    event model draws.

    ``mana_value`` is the threshold; left ``None`` it is read from the
    cascade spell (``source``) at resolution, since cascade's own spell is
    what sets the ceiling.
    """

    def __init__(
        self,
        mana_value: Optional[int] = None,
        player: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.mana_value = mana_value
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        mana_value = self.mana_value
        if mana_value is None and self.source is not None:
            mana_value = self.source.card.converted_mana_cost
        context.cascade(player, mana_value or 0)


class DiscoverEffect(GameEffect):
    """Discover N (RULE 702.164): like cascade, but the hit is a nonland with
    mana value ``N`` *or less*, and the controller casts it for free **or**
    puts it into their hand (never leaves it behind)."""

    def __init__(
        self,
        mana_value: int = 0,
        player: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.mana_value = mana_value
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.discover(player, self.mana_value)


# ---------------------------------------------------------------------------
# cEDH staples cube — player-scoped restrictions & history-driven effects
# ---------------------------------------------------------------------------


class PlayerCastRestrictionEffect(GameEffect):
    """"Until your next turn, target player can't cast noncreature spells."
    (Hope of Ghirapur) — a **player-scoped**, duration-bounded cast
    prohibition (RULE 601.3a), installed on `Player.player_effects` rather
    than derived by the layer engine.

    It isn't a `StaticAbility`: nothing on the battlefield keeps it alive
    (Hope of Ghirapur has *sacrificed itself* to pay for this), so there is
    no permanent for `continuous.recompute` to read it off. The parallel is
    `PreventDamageEffect`'s turn-scoped shield, which lives on
    `player_effects` for the same reason.

    ``until_next_turn_of`` is the player id whose next turn ends it (RULE
    611.2b) — `GameEngine.begin_turn` sweeps every `player_effects` list for
    entries keyed to the incoming active player. ``noncreature`` restricts
    only noncreature spells (leave ``False`` for a blanket "can't cast
    spells"). Consulted by `GameEngine.can_cast` via `_player_cast_
    restricted`.
    """

    #: Marker `GameEngine.can_cast` scans for, so it never has to import
    #: this class (the same duck-typed flag `damage_prevention_shield` uses).
    player_cast_restriction = True

    def __init__(
        self,
        noncreature: bool = True,
        until_next_turn_of: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.noncreature = noncreature
        self.until_next_turn_of = until_next_turn_of
        self.target_spec = TargetSpec(
            kind="player_dealt_combat_damage_by_source",
            description="Spieler, dem diese Kreatur in diesem Zug Kampfschaden zugefügt hat",
        )

    def restricts(self, card: Any) -> bool:
        """Whether this restriction blocks casting ``card`` (RULE 601.3a)."""
        if not self.noncreature:
            return True
        return not getattr(card, "is_creature", False)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        if target is None or not hasattr(target, "player_effects"):
            return
        controller = _controller_of(self.source, context)
        installed = PlayerCastRestrictionEffect(
            noncreature=self.noncreature,
            until_next_turn_of=controller.id if controller is not None else None,
            source=self.source,
        )
        # The installed copy is a plain marker read by `can_cast`; it must
        # not carry a `target_spec` that would make it look like a fresh
        # targeting effect if anything ever re-scanned `player_effects`.
        installed.target_spec = None
        target.player_effects.append(installed)


class LookTopKeepOneOnTopEffect(GameEffect):
    """"Look at the top X cards of your library … put up to one of them on
    top of your library and the rest on the bottom in a random order."
    (Thassa's Oracle) — a library-reordering dig with no card ever changing
    zone in the ordinary sense.

    ``count_selector`` (`continuous.count_selector`, e.g. ``"devotion_to_
    blue"``) resolves X live at resolution time rather than baking a number
    in; ``count`` is the fixed fallback when no selector is given.

    ``win_if_count_at_least_library`` is Thassa's Oracle's own alternative
    win condition (RULE 104.2a): checked *before* the reordering, against
    the library size at that moment — X >= library size wins the game
    outright, which is the whole reason the card is a cEDH staple. Routed
    through `RulesEngine.player_wins`, the same choke point Jace, Wielder of
    Mysteries uses, so "you can't win the game" effects stay in one place.

    "Put **up to one** of them on top" is a real choice, offered through
    the general `GameContext.choose_objects` chooser (optional, so declining
    bottoms all X). The rest go to the bottom in a random order, per the
    card — and they are bottomed *before* the choice rather than after, so
    the randomization can't depend on which card was kept; removing one card
    from an already-random sequence leaves the others just as random.
    """

    def __init__(
        self,
        count: int = 0,
        count_selector: Optional[str] = None,
        win_if_count_at_least_library: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.count_selector = count_selector
        self.win_if_count_at_least_library = win_if_count_at_least_library

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        amount = self.count
        if self.count_selector:
            from . import continuous  # function-scoped: avoid an import cycle

            amount = continuous.count_selector(context.state, player.id, self.count_selector)
        library = player.zones[Zone.LIBRARY]
        # RULE 104.2a, checked before anything moves — an empty library
        # satisfies "X >= 0 cards" and wins even with X of 0.
        if self.win_if_count_at_least_library and amount >= len(library):
            context.engine.player_wins(player)
            return
        if amount <= 0:
            return
        # The library's *end* is its top (see `Player.zones`): peel the top
        # ``amount`` and bottom them all in a random order, then let the
        # player lift up to one back onto the top.
        looked = [library.pop() for _ in range(min(amount, len(library)))]
        if not looked:
            return
        random.shuffle(looked)
        for card in looked:
            library.insert(0, card)  # bottom of library
        context.choose_objects(
            player, looked, "library_top", count=1, optional=True,
            prompt="Lege bis zu eine der angesehenen Karten oben auf deine Bibliothek",
            source=self.source,
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — mana-trigger bodies (RULE 605.1b/605.4)
# ---------------------------------------------------------------------------


class MirrorProducedManaEffect(GameEffect):
    """"Add one mana of any type that permanent produced." (Kinnan, Bonder
    Prodigy) — the amount is fixed at one, but the *type* is only knowable
    from the firing itself, read off `GameContext.trigger_event`'s
    ``produced`` payload (the `TAPPED_FOR_MANA` event `GameEngine.
    tap_for_mana` stamps with what actually went into the pool).

    Distinct from `AddManaEffect`'s ``"ANY"`` sentinel, which offers every
    colour: Kinnan is restricted to what that permanent *did* produce, so a
    Basalt Monolith copies {C} and a Bloom Tender copies only the colours it
    actually made.

    When a single tap produced 2+ distinct types (an "any combination of
    colours" ability — `ManaAbility.any_combination`, or a Bloom Tender),
    *which* one to copy is a real choice, offered through the narrowed
    `RulesEngine.add_mana_any_color` menu. One type produced needs no
    prompt, which is the overwhelmingly common case.
    """

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        event = context.trigger_event
        if player is None or event is None:
            return
        produced = event.get("produced") or {}
        colours = [c for c, n in produced.items() if n]
        if not colours:
            return
        # RULE 605.1a: "any type **that permanent produced**" — a real
        # choice whenever one tap made 2+ types (a Bloom Tender, a dual
        # land's "any combination"), narrowed to exactly those. Safe to open
        # a `pending_choice` here even though a triggered mana ability
        # resolves off-stack (RULE 605.4): the firing action, `GameEngine.
        # tap_for_mana`, is a discrete player action, not a mid-payment step.
        for _ in range(max(self.count, 1)):
            context.engine.add_mana_any_color(player, colours)


class TapMatchingLandsEffect(GameEffect):
    """"Tap all lands that player controls that could produce any type of
    mana that land could produce." (Mana Web) — a mana-denial sweep keyed to
    the *specific* land that was just tapped.

    Both halves come from `GameContext.trigger_event` (`TAPPED_FOR_MANA`):
    which player to sweep (``controller_id``) and which land set the
    reference types (``instance_id``). The reference land's *potential*
    production is re-derived from `game/mana_abilities.py`, not from the
    event's ``produced`` payload — RULE 605.1a is explicit that this is
    about what a land *could* produce, so a dual land tapped for {U} still
    locks down every land that makes {U} **or** its other colour.

    Not itself a mana ability (it produces none), so it uses the stack like
    any ordinary triggered ability.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    @staticmethod
    def _producible(obj: Any, state: Any) -> set[str]:
        """Every mana type ``obj`` could produce right now (RULE 605.1a)."""
        from .mana_abilities import mana_abilities_for  # function-scoped: import cycle

        types: set[str] = set()
        for ability in mana_abilities_for(obj, state=state):
            for option in ability.options:
                types.update(c for c, n in option.items() if n)
        return types

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None:
            return
        reference = context.state.find_object(event.get("instance_id"))
        player_id = event.get("controller_id")
        if reference is None or player_id is None:
            return
        wanted = self._producible(reference, context.state)
        if not wanted:
            return
        for obj in context.state.permanents():
            if obj.controller_id != player_id or not obj.is_land or obj.tapped:
                continue
            if self._producible(obj, context.state) & wanted:
                context.set_tapped(obj, True)


# ---------------------------------------------------------------------------
# cEDH staples cube — control exchange, mass phasing, copy+bounce
# ---------------------------------------------------------------------------


class ExchangeControlEffect(GameEffect):
    """"Exchange control of this creature and up to one target creature an
    opponent controls. If you don't or can't make an exchange, sacrifice
    this creature." (Gilded Drake) — RULE 108.4/701.10.

    A genuine *swap*, which neither shipped control shape could express: the
    layer-2 ``control_change`` static reassigns one permanent's controller
    for as long as its source stays around, and
    `GainControlUntilEndOfTurnEffect` is a one-way, duration-bounded grab.
    Exchange is permanent, two-way, and — crucially for Gilded Drake — has a
    failure mode with its own consequence.

    Implemented as a straight `GameObject.controller_id` swap rather than a
    pair of continuous effects, because RULE 701.10c makes an exchange a
    one-shot change of control that doesn't depend on any source remaining
    on the battlefield: Gilded Drake dying afterwards must *not* give the
    creature back, which is precisely why the card is played.

    ``sacrifice_self_if_no_exchange`` is Gilded Drake's own failure clause
    (RULE 701.10d: an exchange with only one exchangeable permanent doesn't
    happen at all). Note the drake's ability "still resolves if its target
    becomes illegal" — with `target_spec.optional` set, no legal target is
    itself a legal choice, so the ability resolves, the exchange doesn't
    happen, and the sacrifice does.
    """

    def __init__(
        self,
        target_kind: str = "creature",
        sacrifice_self_if_no_exchange: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind, optional=True)
        self.sacrifice_self_if_no_exchange = sacrifice_self_if_no_exchange

    def target_polarity(self) -> Optional[str]:
        return "harmful"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        mine = self.source
        theirs = targets[0] if targets else None
        battlefield = context.state.permanents()
        exchangeable = (
            mine is not None
            and theirs is not None
            and mine in battlefield
            and theirs in battlefield
            and mine.controller_id != theirs.controller_id
        )
        if exchangeable:
            mine.controller_id, theirs.controller_id = theirs.controller_id, mine.controller_id
            # RULE 302.6: each permanent is newly under its controller's
            # command, so both are summoning sick until that player's next
            # turn — the same treatment `RulesEngine` gives any other
            # battlefield arrival.
            mine.summoning_sick = True
            theirs.summoning_sick = True
            context.recompute()
            return
        if self.sacrifice_self_if_no_exchange and mine is not None and mine in battlefield:
            # RULE 701.10d + 701.16c: no exchange happened, so the drake
            # sacrifices itself — sacrifice, never destruction.
            context.put_into_graveyard(mine)


class PhaseOutAllYouControlEffect(GameEffect):
    """"Until your next turn, your life total can't change and you gain
    protection from everything. All permanents you control phase out."
    (Teferi's Protection) — RULE 702.26/611.2b.

    Three separate things the card does at once, kept as one effect because
    all three share the same "until your next turn" duration and the same
    player, and because none is meaningful without the others:

    * every permanent the controller controls phases out (RULE 702.26b) —
      the mass form of the shipped, single-permanent `PhaseOutEffect`. The
      RULE 702.26a sweep in `GameEngine._step_untap` already phases them all
      back in at that player's next untap step, so the duration needs no
      separate bookkeeping.
    * their life total can't change (`PlayerLifeLockEffect`-style marker on
      `Player.player_effects`, consulted by `RulesEngine.gain_life`/
      `lose_life`).
    * they gain protection from everything, which for a *player* reduces to
      "can't be dealt damage / targeted" — modeled with the same
      `player_effects` marker so both halves lapse together in
      `GameEngine.begin_turn`.

    Unlike `PhaseOutEffect`, attached Auras/Equipment are *not* unattached:
    here their host and they themselves both phase out together, so the
    attachment stays valid throughout (RULE 702.26e) — which is the whole
    point of Teferi's Protection as a board-preserving answer.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for obj in list(context.state.battlefield):
            if obj.controller_id == player.id:
                obj.phased_out = True
        shield = PlayerShieldEffect(
            life_locked=True,
            protection_from_everything=True,
            until_next_turn_of=player.id,
            source=self.source,
        )
        player.player_effects.append(shield)
        context.recompute()


class PlayerShieldEffect(GameEffect):
    """Teferi's Protection's player-scoped half: "your life total can't
    change and you gain protection from everything", until your next turn
    (RULE 611.2b).

    A marker on `Player.player_effects` — the same home the RULE 615 damage
    shield and `PlayerCastRestrictionEffect` use, and for the same reason:
    the spell that granted it is already in the graveyard, so there is no
    permanent for `continuous.recompute` to derive it from. Read by
    `RulesEngine.gain_life`/`lose_life` (life lock, RULE 119.6) and
    `RulesEngine.deal_damage` (protection from everything, RULE 702.16e);
    swept by `GameEngine.begin_turn` via ``until_next_turn_of``.
    """

    #: Duck-typed markers the engine scans for, so neither `RulesEngine` nor
    #: `GameEngine` needs to import this class (the same convention
    #: `damage_prevention_shield`/`player_cast_restriction` follow).
    player_life_locked = True

    def __init__(
        self,
        life_locked: bool = True,
        protection_from_everything: bool = True,
        until_next_turn_of: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.life_locked = life_locked
        self.player_life_locked = life_locked
        self.player_protected_from_everything = protection_from_everything
        self.until_next_turn_of = until_next_turn_of

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # a marker consulted by the engine, never applied itself


class CopySpellAndBounceEffect(GameEffect):
    """"Copy target instant or sorcery spell, then return it to its owner's
    hand." (Narset's Reversal) — RULE 707.10 + RULE 400.

    A single atomic effect rather than a `CopySpellEffect` plus a bounce,
    for the reason `GainControlUntilEndOfTurnEffect`'s docstring already
    gives about paired clauses: both halves act on the *same* chosen spell,
    and no shipped bounce effect can reach a `StackItem` (they all move a
    battlefield permanent). Order matters and is the card's whole trick —
    the copy is made **first**, so it still resolves after the original has
    been picked up, and the copy's targets are already locked in.
    """

    def __init__(
        self,
        card_types: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        spell_filter: dict[str, Any] = {}
        if card_types:
            spell_filter["card_types"] = list(card_types)
        self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        controller_id = getattr(self.source, "controller_id", None)
        if target is None or controller_id is None:
            return
        context.copy_spell(target, controller_id, 1)
        context.engine.return_spell_to_hand(target)


class ReturnSharedTypePermanentEffect(GameEffect):
    """"You may return another permanent you control that shares a permanent
    type with it to its owner's hand." (Cloudstone Curio) — the bounce half
    of a RULE 603.1 "whenever a permanent enters" trigger.

    "Shares a permanent type **with it**" is why this can't be an ordinary
    `ReturnToHandEffect` with a target kind: the legal set depends on the
    *entering* permanent, which is only known per firing. It is read off
    `GameContext.trigger_event`'s ``instance_id``/``object_types``, and the
    candidate list is narrowed to permanents sharing at least one of those
    main types (RULE 205.2a) excluding the trigger's own subject.

    *Which* matching permanent to return is the controller's own choice,
    offered through the general `GameContext.choose_objects` chooser — and
    optional there as well as on the trigger itself, so declining at either
    prompt leaves the board alone.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None:
            return
        entering = context.state.find_object(event.get("instance_id"))
        if entering is None:
            return
        wanted = {t for t in entering.type_words if t in _PERMANENT_TYPE_WORDS}
        candidates = [
            obj
            for obj in context.state.permanents()
            if obj is not entering
            and obj.controller_id == entering.controller_id
            and wanted & set(obj.type_words)
        ]
        controller = context.state.player_by_id(entering.controller_id)
        if candidates and controller is not None:
            context.choose_objects(
                controller, candidates, "return_to_hand", count=1, optional=True,
                prompt="Cloudstone Curio: Wähle ein bleibendes Objekt zum Zurücknehmen",
                source=self.source,
            )


class ExileTriggerDamagedCreatureEffect(GameEffect):
    """"Whenever this creature deals combat damage to a creature, exile
    that creature." (Kaldra Compleat-shaped — a Living Weapon's granted
    ability, RULE 613.7f) — RULE 603.3d's "that creature" pronoun refers to
    the `DAMAGE` event's *recipient*, not its source: `_GRANTED_EVENT_KEYS`
    scopes *which grantee* reacts off the event's ``source_id`` (the
    equipped creature that dealt the damage — "this creature"), a different
    field from who was hit. No target choice at all — `GameContext.
    trigger_event`'s own ``target_id`` (ENG-13's general per-firing dynamic
    reference) names the exact object, the granted-ability counterpart of
    what `TriggeredAbility.reflexive` does for an ordinary "that
    permanent/spell" off ``instance_id``. A damaged *player* (``is_player``)
    or a since-departed creature is simply nothing to exile.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None or event.get("is_player"):
            return
        creature = context.state.find_object(event.get("target_id"))
        if creature is None:
            return
        context.exile(creature)


class LoseGameTriggerDamagedPlayerEffect(GameEffect):
    """"…that player loses the game…" (Frodo, Sauron's Bane) — RULE 603.3d's
    "that player" pronoun refers to the `DAMAGE` event's *recipient*, the
    exact mirror of `ExileTriggerDamagedCreatureEffect` for a player instead
    of a creature: no target choice, `GameContext.trigger_event`'s own
    ``target_id`` is the damaged player's id (`is_player`). A damaged
    creature or a since-departed player is simply nothing to make lose.
    """

    def __init__(self, reason: str = "effect", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.reason = reason

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        if event is None or not event.get("is_player"):
            return
        context.lose_game(context.state.player_by_id(event.get("target_id")), self.reason)


#: RULE 205.2a's permanent card types — the vocabulary "shares a permanent
#: type with it" (Cloudstone Curio) compares against, so a shared *spell*
#: type (instant/sorcery, which no permanent has anyway) can never match.
_PERMANENT_TYPE_WORDS: frozenset[str] = frozenset(
    {"artifact", "creature", "enchantment", "land", "planeswalker", "battle"}
)


class PutFromHandOntoBattlefieldEffect(GameEffect):
    """"Put up to two creature cards from your hand onto the battlefield."
    (Tooth and Nail's second mode) — RULE 701.19-adjacent, but from **hand**.

    Every other "put onto the battlefield" shape in the engine moves a card
    out of a library (a search) or a graveyard (reanimation); none opens an
    arbitrary pick from hand. Reuses `RulesEngine.request_search`'s
    interactive one-at-a-time choice machinery by searching the ``"hand"``
    zone, so the UI, the undo snapshots and the "up to N" semantics are
    identical to every other pick — rather than a parallel choice kind that
    would need its own wiring in the session and the frontend.
    """

    def __init__(
        self,
        criteria: Any = "",
        count: int = 1,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.criteria = criteria
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.request_search(
            player, self.criteria, "battlefield", self.count, optional=True, zones=["hand"],
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — naming a card, and the three loop shapes
# ---------------------------------------------------------------------------


class NameCardThenEffect(GameEffect):
    """"Choose a card name. `<effect>`" (Demonic Consultation) — RULE 701's
    naming action, which no `pending_choice` could express before: every
    other choice in the engine picks from an enumerable set, and a player
    may name *any* card in Magic, including one nowhere in this game.

    `RulesEngine.request_name_card` therefore offers the names the player
    can actually see (their own hand/library/graveyard) as suggestions while
    accepting an arbitrary string, and substitutes it into the follow-up
    effects' ``"named_card"`` criteria sentinel — the naming counterpart of
    `_substitute_x`'s ``"x"``. The string is only ever *compared against*
    card names, never interpreted, so nothing derived from it becomes
    behaviour (docs/09's security boundary).
    """

    def __init__(
        self,
        effects: Optional[list[dict[str, Any]]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.inner_specs = list(effects or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.request_name_card(player, self.inner_specs, self.source)


class DigUntilEffect(GameEffect):
    """"Reveal/exile cards from the top of your library until `<predicate>`"
    (Demonic Consultation, Tibalt's Trickery, Possibility Storm) — the
    generalized form of the cascade/discover dig, which was hard-wired to
    "nonland cheaper than N, may cast it, rest to the bottom".

    Both the predicate (``criteria``, a `models.card_query` dict — including
    the new ``not_name`` for "a different name than that spell") and both
    destinations are parameters here. ``pre_exile`` is Demonic
    Consultation's "exile the top six cards" prologue, which happens before
    the dig and is never part of it.

    ``criteria`` may carry the ``"named_card"`` sentinel — the name just
    chosen (see `NameCardThenEffect`), substituted at answer time rather
    than baked in. The *spell*-derived predicates ("a different name than
    that spell", "shares a card type with it") live on
    `ScrambleSpellEffect` instead, which has the answered spell in hand.
    """

    def __init__(
        self,
        criteria: Any = "",
        hit_destination: str = "hand",
        rest_destination: str = "exile",
        pre_exile: int = 0,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.criteria = criteria
        self.hit_destination = hit_destination
        self.rest_destination = rest_destination
        self.pre_exile = int(pre_exile)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.dig_until(
            player,
            self.criteria,
            hit_destination=self.hit_destination,
            rest_destination=self.rest_destination,
            pre_exile=self.pre_exile,
        )


class MillUntilCreatureEffect(GameEffect):
    """"Target opponent mills a card, then repeats this process until a
    creature card or X cards have been put into their graveyard this way,
    whichever comes first. If one or more creature cards were put into that
    graveyard this way, sacrifice this artifact and put one of them onto the
    battlefield under your control." (Helm of Obedience)

    The engine's first **repeat-until-a-predicate-holds** loop: every other
    repetition primitive here has a count fixed before it starts (mill N,
    draw N, proliferate). Here the count is a *cap* and the real stopping
    condition is what the mill turned up, so the loop has to check after
    each iteration.

    Bounded on both sides by construction — ``X`` caps the iterations and an
    empty library ends it early — so this cannot spin, which is the property
    that makes a "repeat until" primitive safe to have at all.

    Note the reanimated creature comes back under **your** control, not its
    owner's (RULE 110.2), and the Helm sacrifices itself only when the mill
    actually hit a creature (RULE 701.16c: sacrifice, not destruction).
    """

    def __init__(
        self,
        amount: Any = 0,
        target_kind: str = "player",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        victim = targets[0] if targets else None
        cap = self.amount if isinstance(self.amount, int) else 0
        if victim is None or not hasattr(victim, "graveyard") or cap <= 0:
            return  # "X can't be 0."
        found: list[Any] = []
        for _ in range(cap):
            if not victim.library:
                break
            context.mill(victim, 1)
            milled = victim.graveyard[-1] if victim.graveyard else None
            if milled is not None and milled.is_creature:
                found.append(milled)
                break
        if not found:
            return
        controller = _controller_of(self.source, context)
        if self.source is not None and self.source in context.state.permanents():
            context.put_into_graveyard(self.source)
        context.return_from_graveyard(
            found[0], "battlefield",
            controller_id=controller.id if controller is not None else None,
        )


class LookTopPayLifeLoopEffect(GameEffect):
    """"Look at the top five cards of your library. As many times as you
    choose, you may pay 1 life, put those cards on the bottom of your
    library in any order, then look at the top five cards. Then shuffle and
    put the last cards you looked at on top in any order." (Lim-Dûl's Vault)

    The engine's first **open-ended** loop: every other repetition here has
    a fixed count or a hard cap (`MillUntilCreatureEffect`'s X, a search's
    "up to N"). Here the player decides after each iteration whether to go
    again, so it's driven by a `pending_choice` that re-opens itself —
    the same self-re-opening shape a multi-card search already uses, but
    with no counter running down.

    It is still bounded in practice by the payment: each iteration costs 1
    life, so it can run at most `Player.life` - 1 times, and the choice is
    simply not offered once the player can't pay. That is the card's own
    natural bound, not a safety cap bolted on.

    **Documented simplification**: "in any order" is not an interactive
    reorder — the five cards keep their relative order when bottomed, and
    the final five are left on top as they lie. The card is played to *find*
    a specific card, and the top card is what the next draw takes either
    way; a full five-card ordering UI is a separate feature.
    """

    def __init__(
        self,
        count: int = 5,
        life_cost: int = 1,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = int(count)
        self.life_cost = int(life_cost)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.request_look_top_pay_life_loop(player, self.count, self.life_cost)


class ScrambleSpellEffect(GameEffect):
    """The "answer a spell, then dig its controller's library for a
    replacement they may cast free" family — Possibility Storm and Tibalt's
    Trickery, which differ only in *how* the original spell is answered and
    what predicate the dig uses.

    One atomic effect rather than a composition, for the reason the paired-
    clause effects in this file already document: every clause acts on the
    *same* spell and on **its controller** (never the effect's own
    controller), and the dig's predicate is derived from that spell — none
    of which a separate `counter` + `mill` + `dig_until` chain could thread
    between its members.

    ``answer`` is ``"counter"`` (Tibalt's Trickery) or ``"exile"``
    (Possibility Storm, whose "that player exiles it" is a zone change, not
    a counter — which is why it also gets around "can't be countered").
    ``mill_random_max``, when set, mills the spell's controller a random
    1..N first (Tibalt's Trickery's "choose 1, 2, or 3 at random" — genuine
    randomness the card itself demands, not an engine shortcut).

    The replacement card is *offered*, never force-cast: the hit gets the
    same exile free-cast window Rebound and Beseech the Mirror use, and a
    delayed trigger performs the printed "put it on the bottom of their
    library" fallback at the next end step if they don't take it.
    ``match`` picks the dig predicate: ``"different_name"`` (a nonland card
    not named like the answered spell) or ``"shares_card_type"`` (RULE
    205.2, read off the answered spell's own main types).
    """

    def __init__(
        self,
        answer: str = "counter",
        match: str = "different_name",
        mill_random_max: int = 0,
        card_types: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.answer = answer
        self.match = match
        self.mill_random_max = int(mill_random_max)
        spell_filter: dict[str, Any] = {}
        if card_types:
            spell_filter["card_types"] = list(card_types)
        self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        item = context.engine._stack_item_for(target)
        if item is None or item.obj is None:
            return
        spell = item.obj
        try:
            caster = context.state.player_by_id(item.controller_id)
        except (KeyError, ValueError):
            return
        # Snapshot before the spell leaves the stack — both the dig
        # predicate and the mill are about *that* spell and *its* controller.
        name = spell.name
        types = [t for t in spell.type_words if t != "permanent"]

        if self.answer == "exile":
            context.engine.move_spell_off_stack(item, "exile")
        else:
            context.engine.counter_spell(item)

        if self.mill_random_max > 0:
            context.mill(caster, random.randint(1, self.mill_random_max))

        if self.match == "shares_card_type":
            criteria: dict[str, Any] = {"type": types or ["__none__"]}
        else:
            criteria = {"not_name": name}
        context.engine.dig_until(
            caster,
            criteria,
            # "That player **may** cast that card without paying its mana
            # cost" — an offer, not a forced cast (see `_place_dig_hit`).
            hit_destination="cast_free_window",
            rest_destination="library_bottom_random",
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — Fading, Soulbond, Mutate (RULE 702.32/702.94/702.140)
# ---------------------------------------------------------------------------


class RemoveCounterOrSacrificeEffect(GameEffect):
    """Fading's upkeep half (RULE 702.32b): "At the beginning of your upkeep,
    remove a fade counter from this permanent. If you can't, sacrifice it."

    Note the "if you can't" is about there being **no counter left**, not
    about any choice — a permanent at 0 fade counters is sacrificed, which
    is why Fading N lasts N+1 of your upkeeps rather than N. Vanishing (RULE
    702.61) is the same shape with a ``"time"`` counter and no such
    off-by-one, so this is written against a counter ``kind`` rather than
    hard-coding fade.

    Sacrifice, never destruction (RULE 701.16c), so nothing can regenerate
    or "if it would die, exile it instead" its way out.
    """

    def __init__(self, kind: str = "fade", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.kind = kind

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        if obj is None or obj not in context.state.permanents():
            return
        if obj.counters.get(self.kind, 0) > 0:
            obj.add_counters(self.kind, -1)
            return
        context.put_into_graveyard(obj)


class TapPermanentsPerCounterEffect(GameEffect):
    """"That player taps an untapped artifact, creature, or land they control
    for each fade counter on this artifact." (Tangle Wire) — a per-player
    tax whose *magnitude* is read live off the source's own counters, so it
    shrinks each upkeep as Fading counts down.

    *Which* permanents get tapped is the taxed player's own choice (RULE
    701.21a) — and on this card it is the whole decision, since leaving the
    right permanents open is what playing against a Tangle Wire consists
    of. Offered through the general `GameContext.choose_objects` chooser,
    one at a time; with N or fewer candidates it taps them all without
    asking, because there is nothing left to decide.
    """

    def __init__(
        self,
        kind: str = "fade",
        types: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.types = [t.lower() for t in (types or ["artifact", "creature", "land"])]

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        event = context.trigger_event
        if obj is None or event is None:
            return
        # "each player's upkeep" — the taxed player is whoever's turn it is,
        # since `STEP_BEGIN` carries no player of its own (see the
        # `phase_relation` predicate in `effect_binder`).
        player = context.state.active_player
        remaining = obj.counters.get(self.kind, 0)
        if remaining <= 0:
            return
        candidates = [
            candidate
            for candidate in context.state.permanents_controlled_by(player.id)
            if not candidate.tapped and (set(candidate.type_words) & set(self.types))
        ]
        context.choose_objects(
            player, candidates, "tap", count=remaining,
            prompt=f"{obj.name}: Wähle ein bleibendes Objekt zum Tappen",
            source=obj,
        )


class SoulbondPairEffect(GameEffect):
    """Soulbond's pairing half (RULE 702.94a): "You may pair this creature
    with another unpaired creature when either enters."

    Pairing is a genuine piece of game state, not a continuous effect —
    `GameObject.paired_with` holds the partner's instance id on **both**
    objects, and RULE 702.94c breaks the pair automatically the moment
    either leaves the battlefield or changes controller
    (`RulesEngine.check_state_based_actions`).

    Fires for *either* creature entering (the Soulbond creature itself, or a
    later unpaired one joining it), which is what the printed "when either
    enters" means; a creature already paired is skipped both ways.

    *Which* creature to pair with is the controller's choice (RULE
    702.94a), offered through the general `GameContext.choose_objects`
    chooser — and on Deadeye Navigator it is the entire decision, since the
    partner is whatever you intend to blink all game. Optional there too:
    the printed "you **may** pair" means declining leaves both unpaired.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event
        entering = (
            context.state.find_object(event.get("instance_id")) if event else None
        )
        obj = self.source
        if obj is None or entering is None:
            return
        # RULE 702.94a: whichever of the two just entered, the pair is always
        # "this creature" + some other unpaired creature.
        if obj.paired_with is not None:
            return
        candidates = [
            o
            for o in context.state.permanents_controlled_by(obj.controller_id)
            if o is not obj and o.is_creature and o.paired_with is None
        ]
        if not candidates:
            return
        controller = context.state.player_by_id(obj.controller_id)
        if controller is None:
            return
        context.choose_objects(
            controller, candidates, "soulbond_pair", count=1, optional=True,
            prompt=f"{obj.name}: Wähle eine Kreatur zum Paaren (Seelenbund)",
            source=obj,
        )
        context.recompute()


class MutateEffect(GameEffect):
    """Mutate's merge (RULE 702.140b-d): "put this creature over or under
    target non-Human creature you own. They mutate into the creature on top
    plus all abilities from under it."

    Both directions are modeled. On top (the usual choice): the mutating
    creature's characteristics (name, P/T, types) replace the host's, and
    the host's abilities merge in underneath. Under: the host keeps its
    characteristics and gains the mutating card's abilities. Which one
    applies is chosen *as the spell is cast* (RULE 702.140a), so it rides
    `GameObject.mutate_under` rather than being decided here.

    Implemented by `RulesEngine.mutate_onto`, which keeps the *host* as the
    surviving `GameObject` either way — so its counters, damage, Auras and
    summoning-sickness state all carry over untouched (RULE 702.140c: the
    merged permanent is the same permanent, never a new object, which is
    exactly why mutate dodges "enters the battlefield" triggers).

    Fires `EventType.MUTATES` afterwards so "whenever this creature mutates"
    (Lore Drakkis) has something to trigger on.
    """

    def __init__(
        self,
        target_kind: str = "non_human_creature_you_own",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        host = targets[0] if targets else None
        if host is None or self.source is None:
            return
        context.engine.mutate_onto(
            self.source, host, under=bool(getattr(self.source, "mutate_under", False))
        )


# ---------------------------------------------------------------------------
# cEDH staples cube — two independently-chosen targets in one clause
# ---------------------------------------------------------------------------


class AttachChosenEffect(GameEffect):
    """"Attach target Equipment you control to target creature you control."
    (Brass Squire; Halvar, God of Battle's combat trigger) — RULE 301.5c.

    The first card in this engine to need **two independently-chosen targets
    of different kinds in one clause**: the thing being attached is itself a
    target, not the ability's own source (which is what the shipped
    `AttachEffect` assumes). Expressed with `GameEffect.extra_target_specs`,
    so both requirements are gathered through the ordinary RULE 115.1
    one-at-a-time machinery and arrive here flattened in printed order:
    ``targets[0]`` is what moves, ``targets[1]`` is where it goes.

    ``what_kind`` widens the first requirement for Halvar, whose clause is
    "target Aura **or** Equipment attached to a creature you control".
    """

    def __init__(
        self,
        what_kind: str = "equipment_you_control",
        to_kind: str = "creature_you_control",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind=what_kind)
        self.extra_target_specs = (TargetSpec(kind=to_kind),)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = list(targets or [])
        if len(picks) < 2:
            return
        what, host = picks[0], picks[1]
        if what is None or host is None:
            return
        context.attach_to_target(what, host)


class CounterThenFightlikeDamageEffect(GameEffect):
    """"Put a +1/+1 counter on target creature you control. It deals damage
    equal to its power to target creature you don't control." (Archdruid's
    Charm's second mode) — a fight-adjacent clause with two independently
    chosen targets, the same `extra_target_specs` shape `AttachChosenEffect`
    uses.

    One atomic effect rather than a composition, because the damage amount
    is read off the *first* target **after** the counter lands (RULE 613's
    layer pass runs in between, which is exactly why the counter is worth
    putting on first) — no separate `DealDamageEffect` could see it.
    """

    def __init__(
        self,
        counters: int = 1,
        kind: str = "+1/+1",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.counters = counters
        self.kind = kind
        self.target_spec = TargetSpec(kind="creature_you_control")
        self.extra_target_specs = (TargetSpec(kind="creature_you_dont_control"),)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = list(targets or [])
        if len(picks) < 2:
            return
        mine, theirs = picks[0], picks[1]
        if mine is None:
            return
        context.add_counters(mine, self.counters, self.kind, source=self.source)
        context.recompute()  # so the damage reads the *boosted* power
        if theirs is not None:
            context.deal_damage(theirs, mine.power or 0, mine)


#: Subject names that are *not* a RULE 115 target choice — the four ways a
#: fight/one-sided-damage clause can name a creature without announcing a
#: requirement for it. Shared by `FightEffect` and
#: `DamageEqualToPowerEffect`, which take exactly the same subject vocabulary
#: on either side of the verb (a fight is two of these dealing damage to each
#: other; the one-sided family is one of them dealing to a target).
#:
#: * ``None`` — the effect's own source ("**it** fights …" in a trigger whose
#:   subject is that permanent, "when ~ dies, **it** deals damage equal to its
#:   power to any target");
#: * ``"attached_permanent"`` — an Aura/Equipment's current host ("when this
#:   Aura enters, **enchanted creature** fights …"), re-read live at
#:   resolution the way `TapEffect`'s attached mode does;
#: * ``"previous_target"`` / ``"previous_target_2"`` — the first/second target
#:   the *preceding* clause of this same resolution chose
#:   (`GameContext.previous_targets`): "target creature you control gets
#:   +1/+2 until end of turn. **It** fights target creature you don't
#:   control." (Epic Confrontation) and "Choose target creature you control
#:   and target creature you don't control. … Then **those creatures** fight
#:   each other." (Ancient Animus).
_IMPLICIT_FIGHT_SUBJECTS: frozenset = frozenset(
    {None, "attached_permanent", "previous_target", "previous_target_2"}
)


def _implicit_fight_subject(
    kind: Optional[str], effect: "GameEffect", context: GameContext
) -> Optional[Any]:
    """Resolve one of `_IMPLICIT_FIGHT_SUBJECTS` against the live game."""
    if kind is None:
        return effect.source
    if kind == "attached_permanent":
        host_id = getattr(effect.source, "attached_to", None)
        return context.state.find_object(host_id) if host_id is not None else None
    index = 1 if kind == "previous_target_2" else 0
    previous = getattr(context, "previous_targets", []) or []
    return previous[index] if len(previous) > index else None


class FightEffect(GameEffect):
    """RULE 701.14 — "Target creature you control fights target creature you
    don't control." (Prey Upon), "~ fights up to one target creature you don't
    control." (Kogla's ETB).

    Both creatures deal damage equal to their power to each other (701.14a),
    and it is **not** combat damage (701.14d) — so `context.deal_damage`'s
    default ``combat=False`` is exactly right, and a first-strike/deathtouch-
    style combat concept never enters into it.

    ``fighter_kind``/``other_kind`` each name either a RULE 115 target kind —
    the printed two-target form ("target creature you control fights target
    creature …"), where `extra_target_specs` carries the second requirement
    the same way `AttachChosenEffect` does — or one of the four implicit
    subjects `_IMPLICIT_FIGHT_SUBJECTS` documents (the source, an Aura's host,
    or a pronoun pointing back at the previous clause's target). An implicit
    subject announces no requirement at all, so "it fights target creature you
    don't control" is a *one*-target spell and "those creatures fight each
    other" is a zero-target one.

    RULE 701.14b is the whole reason this is one atomic effect rather than two
    `DealDamageEffect`s: if *either* creature has left the battlefield or
    stopped being a creature by resolution, **neither** deals damage. Both
    powers are also snapshotted before any damage is dealt, since 701.14a's
    two damage events are simultaneous — a creature whose power changes as a
    consequence of the first half (a dies-trigger, an SBA) must still deal
    what it had. A creature fighting itself deals twice its power to itself
    (701.14c), which falls out of dealing both halves to the same object —
    *unless* ``distinct`` marks the clause's RULE 109.5 "**another** target
    creature", where picking the same creature twice was never legal to begin
    with (`TargetSpec.distinct_from_others`); this is that constraint's
    resolve-time backstop.
    """

    def __init__(
        self,
        fighter_kind: Optional[str] = None,
        other_kind: Optional[str] = "creature",
        fighter_optional: bool = False,
        optional: bool = False,
        distinct: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.fighter_kind = fighter_kind
        self.other_kind = other_kind
        self.distinct = distinct
        specs: list[TargetSpec] = []
        if fighter_kind not in _IMPLICIT_FIGHT_SUBJECTS:
            specs.append(TargetSpec(kind=fighter_kind, optional=fighter_optional))
        if other_kind not in _IMPLICIT_FIGHT_SUBJECTS:
            specs.append(
                TargetSpec(kind=other_kind, optional=optional, distinct_from_others=distinct)
            )
        if specs:
            self.target_spec = specs[0]
            self.extra_target_specs = tuple(specs[1:])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = list(targets or [])
        chosen = iter(picks)
        if self.fighter_kind in _IMPLICIT_FIGHT_SUBJECTS:
            fighter = _implicit_fight_subject(self.fighter_kind, self, context)
        else:
            fighter = next(chosen, None)
        if self.other_kind in _IMPLICIT_FIGHT_SUBJECTS:
            other = _implicit_fight_subject(self.other_kind, self, context)
        else:
            other = next(chosen, None)
        # RULE 701.14b: gone from the battlefield, or no longer a creature →
        # neither fights (an "up to one" clause with no target lands here too).
        battlefield = context.state.permanents()
        for creature in (fighter, other):
            if creature is None or creature not in battlefield or not creature.is_creature:
                return
        if fighter is other and (self.distinct or self.fighter_kind == "previous_target"):
            # RULE 109.5: "another" was never a legal pick of itself. The same
            # guard covers a pronoun fighter whose clause declined its own
            # "up to one" target — a caller that sends a *flat* list can't
            # say which requirement was skipped (`targeting.partition_targets`
            # returns None there), so this clause would otherwise read the
            # earlier clause's pick as its own and have the creature fight
            # itself. No printed card means that.
            return
        fighter_power = fighter.power or 0
        other_power = other.power or 0
        context.deal_damage(other, fighter_power, fighter)
        context.deal_damage(fighter, other_power, other)


class DamageEqualToPowerEffect(GameEffect):
    """"Target creature you control deals damage equal to its power to target
    creature you don't control." (Rabid Bite) — the *one-sided* fight, and
    "When ~ dies, it deals damage equal to its power to any target." /
    "… to each opponent." (Ghoulcaller's Accomplice-shaped dies triggers).

    Shares `FightEffect`'s subject vocabulary for the **dealer**
    (`_IMPLICIT_FIGHT_SUBJECTS`, or a target kind) and `DealDamageEffect`'s
    for the **recipient** (a target kind, or an untargeted ``selector`` —
    RULE 601.2c's "each opponent"/"each player"/"each creature").

    Two rules-relevant differences from a fight, both deliberate: the damage
    is one-way, and the dealer is **not** required to still be on the
    battlefield. The commonest printed form of this clause is a dies trigger,
    where the dealer is already in the graveyard as the ability resolves —
    RULE 608.2h's last known information is what its power is read from, which
    is exactly what `GameObject.power` still reports there.
    """

    def __init__(
        self,
        dealer_kind: Optional[str] = None,
        target_kind: Optional[str] = "any",
        selector: Optional[str] = None,
        dealer_optional: bool = False,
        optional: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.dealer_kind = dealer_kind
        self.selector = selector if selector in _DAMAGE_SELECTORS else None
        specs: list[TargetSpec] = []
        if dealer_kind not in _IMPLICIT_FIGHT_SUBJECTS:
            specs.append(TargetSpec(kind=dealer_kind, optional=dealer_optional))
        if self.selector is None and target_kind is not None:
            specs.append(TargetSpec(kind=target_kind, optional=optional))
        if specs:
            self.target_spec = specs[0]
            self.extra_target_specs = tuple(specs[1:])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        picks = list(targets or [])
        chosen = iter(picks)
        if self.dealer_kind in _IMPLICIT_FIGHT_SUBJECTS:
            dealer = _implicit_fight_subject(self.dealer_kind, self, context)
        else:
            dealer = next(chosen, None)
        if dealer is None:
            return
        amount = dealer.power or 0
        if amount <= 0:
            return
        if self.selector is not None:
            for recipient in self._selected_recipients(context, dealer):
                context.deal_damage(recipient, amount, dealer)
            return
        recipient = next(chosen, None)
        if recipient is None:
            return
        if recipient is dealer and self.dealer_kind == "previous_target":
            # The same flat-list guard `FightEffect` makes: a declined "up to
            # one" would otherwise leave this clause reading the previous
            # clause's pick as its own recipient, damaging it with itself.
            return
        # A permanent that has since left the battlefield takes no damage
        # (RULE 608.2b's illegal-target check, the same guard a fight makes);
        # a player recipient (no ``instance_id``) is always still there.
        if hasattr(recipient, "instance_id") and recipient not in context.state.permanents():
            return
        context.deal_damage(recipient, amount, dealer)

    def _selected_recipients(self, context: GameContext, dealer: Any) -> list[Any]:
        """RULE 601.2c's untargeted recipient groups, scoped to the **dealer**
        (not the effect's source — "each opponent" of the creature dealing the
        damage, which for a granted/copied ability need not be the same
        player)."""
        if self.selector == "each_creature":
            return [obj for obj in context.state.permanents() if obj.is_creature]
        controller_id = getattr(dealer, "controller_id", None)
        return [
            player
            for player in context.state.living_players()
            if not (self.selector == "each_opponent" and player.id == controller_id)
        ]


class DamageEqualToCountersEffect(GameEffect):
    """"~ deals damage equal to the number of +1/+1 counters on it to any
    other target." (Red Hulk-shaped) — `DamageEqualToPowerEffect`'s sibling
    for a counter-count amount rather than power (the two aren't always the
    same number: a creature's power can be modified by other statics/pumps
    independently of its counters).

    Red Hulk's own printed shape ("put a +1/+1 counter on him. **When you
    do**, he deals damage equal to the number of +1/+1 counters on him to
    any other target.") is really two abilities under RULE 603.10 — a
    reflexive trigger off the counter-placement, not a plain sequential
    resolution. This engine has no reflexive "when you do" trigger
    primitive yet, so the catalogue entry runs both as one triggered
    ability's effect list instead (RULE 608.2a resolves a list in printed
    order, and nothing has a window to intervene between them either way in
    an automated engine) — a documented simplification, not a rules
    difference a real game could ever observe.
    """

    def __init__(
        self,
        kind: str = "+1/+1",
        target: Any = None,
        target_kind: Optional[str] = "any",
        optional: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.kind = kind
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional) if target_kind else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        amount = (
            self.source.plus_one_counters if self.kind == "+1/+1"
            else int((getattr(self.source, "counters", None) or {}).get(self.kind, 0) or 0)
        )
        if amount <= 0:
            return
        context.deal_damage(target, amount, self.source)


class ChooseTargetsEffect(GameEffect):
    """"Choose target creature you control **and** target creature you don't
    control." (Ancient Animus, Coven-style fight spells) — a clause that only
    *announces* targets (RULE 601.2c), doing nothing on its own; the clauses
    after it act on them by pronoun ("Then **those creatures** fight each
    other.", `_IMPLICIT_FIGHT_SUBJECTS`' ``previous_target``/
    ``previous_target_2`` via `GameContext.previous_targets`).

    Modeling it as a real, no-op effect rather than folding the targets into
    whichever later clause uses them keeps the announcement where the card
    prints it: the targets are chosen as the spell is *cast* (RULE 601.2c),
    so they must be part of what `targeting.spell_target_specs` reports even
    when the clause consuming them is conditional and may never happen ("if
    you control three or more snow permanents, …").

    ``count``/``distinct_controllers``/``optional`` (PAR-1, only meaningful
    with a single ``kinds`` entry) are Run Away Together's own "**choose two
    target creatures** controlled by different players." shape — one
    quantified requirement picking N objects of the *same* kind, unlike the
    Ancient Animus pair above (two independent, differently-kinded single
    choices). The whole chosen group is then read back — not by a
    positional ``previous_target``/``previous_target_2`` pronoun, which only
    ever names the *first*/*second* of exactly two — by a later clause's own
    ``previous_subject`` flag (`ReturnToHandEffect`'s, for now).
    """

    def __init__(
        self,
        kinds: Optional[list[str]] = None,
        source: Optional["GameObject"] = None,
        count: Optional[int] = None,
        distinct_controllers: bool = False,
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        kinds = kinds or []
        if len(kinds) == 1 and count:
            specs = [TargetSpec(
                kind=kinds[0], count=count, distinct_controllers=distinct_controllers,
                optional=optional,
            )]
        else:
            specs = [TargetSpec(kind=kind) for kind in kinds]
        if specs:
            self.target_spec = specs[0]
            self.extra_target_specs = tuple(specs[1:])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        # Nothing happens here; the picks reach the following clauses through
        # `_apply_effects_partitioned`'s `GameContext.previous_targets`.
        return


class DestroyEachWithManaValueEffect(GameEffect):
    """"Destroy each artifact with mana value X." (Dauntless Dismantler's
    ``{X}{X}{W}`` ability) — a mass destroy whose *filter* is the ability's
    own announced X rather than a printed constant.

    The shipped `DestroyEffect`'s ``max_mana_value`` is a printed cap; this
    is an exact match against a value only known at activation, threaded
    through the same ``"x"`` sentinel `RulesEngine._substitute_x` rewrites
    for every other X-scaled magnitude. Untargeted (RULE 601.2c), like every
    other board wipe here.
    """

    def __init__(
        self,
        amount: Any = 0,
        card_type: str = "artifact",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.card_type = card_type

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if not isinstance(self.amount, int):
            return
        doomed = [
            obj
            for obj in context.state.permanents()
            if self.card_type in obj.type_words
            and obj.card.converted_mana_cost == self.amount
        ]
        for obj in doomed:
            context.destroy(obj)


class DiscardOrLoseLifeEffect(GameEffect):
    """"Each opponent may discard a card. If they don't, they lose N life.
    Repeat this process M more times." (Professor Onyx's −8) — RULE 701.8
    plus a fixed-count repetition.

    ``times`` is the total number of rounds (7 for Onyx: the first plus "six
    more"), which makes this a *bounded* loop like `MillUntilCreatureEffect`
    rather than an open-ended one — the count is known before it starts.

    Whether to discard is each opponent's own decision (RULE 118.3-style
    optional payment), so every round is a real `pay_cost_then` prompt —
    the shipped primitive Mana Vault and Wandering Archaic already use,
    with discarding as the cost and losing the life as its "if you don't"
    branch. The loop is driven by making *both* branches carry a
    ``discard_or_lose_life`` spec for the remaining rounds/opponents, so
    resolving one prompt opens the next: `pending_choice` holds one
    decision at a time, which a Python loop here could never respect.

    ``round_index``/``player_index`` are that continuation's bookmark
    (rounds completed so far, and how far through the opponent list this
    round is) — internal, never authored on a card.
    """

    def __init__(
        self,
        count: int = 1,
        amount: int = 3,
        times: int = 1,
        selector: str = "each_opponent",
        round_index: int = 0,
        player_index: int = 0,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.amount = amount
        self.times = int(times)
        self.selector = selector
        self.round_index = int(round_index)
        self.player_index = int(player_index)

    def _continuation_spec(self, round_index: int, player_index: int) -> dict[str, Any]:
        """This same effect, bookmarked one step further on."""
        return {
            "type": "discard_or_lose_life",
            "params": {
                "count": self.count,
                "amount": self.amount,
                "times": self.times,
                "selector": self.selector,
                "round_index": round_index,
                "player_index": player_index,
            },
        }

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .costs import ActivationCost

        controller_id = getattr(self.source, "controller_id", None)
        opponents = [
            p for p in context.state.living_players()
            if not (self.selector == "each_opponent" and p.id == controller_id)
        ]
        round_index, player_index = self.round_index, self.player_index
        # Skip past anyone already handled this round, and past finished
        # rounds — the loop only ever advances, so a re-entry can't repeat.
        while round_index < max(self.times, 0):
            if player_index >= len(opponents):
                round_index += 1
                player_index = 0
                continue
            player = opponents[player_index]
            if not player.hand:
                # Nothing to discard: RULE 118.3's "a player who can't pay
                # isn't asked", so the else-branch applies straight away.
                context.lose_life(player, self.amount)
                player_index += 1
                continue
            cost = ActivationCost(discard=self.count)
            rest = [self._continuation_spec(round_index, player_index + 1)]
            context.engine.request_pay_cost_then(
                player,
                cost,
                effect_specs=rest,
                else_effect_specs=[
                    {
                        "type": "lose_life",
                        "params": {"amount": self.amount, "player_id": player.id},
                    },
                    *rest,
                ],
                source=self.source,
                prompt=f"{player.id}: Eine Karte abwerfen statt {self.amount} Leben zu verlieren?",
            )
            return


class GainControlOfAllCommandersEffect(GameEffect):
    """"Gain control of all commanders. Put all commanders from the command
    zone onto the battlefield under your control." (Tevesh Szat's −10) —
    RULE 903.3/110.2.

    Genuinely Commander-specific, with no near-miss anywhere in the engine:
    the layer-2 ``control_change`` static reassigns one permanent for as
    long as its source stays around, and no shipped effect moves a card out
    of the **command zone** onto the battlefield at all.

    The control change here is permanent (a one-shot RULE 110.2 change, like
    `ExchangeControlEffect`'s), not a duration-bounded grab — Tevesh Szat is
    an ultimate, and the board state it creates is meant to stick.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        for obj in list(context.state.battlefield):
            if obj.is_commander:
                obj.controller_id = controller.id
                obj.summoning_sick = True  # RULE 302.6: new controller
        for player in context.state.players:
            for obj in list(player.command):
                if not obj.is_commander:
                    continue
                player.remove_from_zone(obj, Zone.COMMAND)
                obj.controller_id = controller.id
                obj.zone = Zone.BATTLEFIELD
                obj.summoning_sick = True
                context.state.add_to_battlefield(obj)
                context.fire_event(
                    GameEvent(
                        EventType.ENTERS_BATTLEFIELD,
                        instance_id=obj.instance_id,
                        controller_id=obj.controller_id,
                        object_types=sorted(obj.type_words),
                    )
                )
        context.recompute()


class MultiplyDamageFromTargetEffect(GameEffect):
    """"Choose target creature. Until your next turn, if that creature would
    deal combat damage to one of your opponents, it deals triple that damage
    to that player instead." (Jeska, Thrice Reborn's 0) — RULE 616.1.

    The shipped damage-multiplying replacement family (Furnace of Rath/Fiery
    Emancipation) is standing, board-wide and sourced from a permanent whose
    presence keeps it alive. This is the same *rewrite*, scoped three ways
    that family never needed: to one specific source instance, to combat
    damage only, and to the effect's controller's opponents — and bounded by
    a duration rather than by its source sticking around.

    So it reuses the replacement machinery rather than a new one: a
    turn-scoped `ReplacementEffect` installed on the targeted creature's own
    `GameObject.replacement_effects`, exactly the per-object shield shape
    `RegenerateEffect` already uses.
    """

    def __init__(
        self,
        multiplier: int = 2,
        combat_only: bool = True,
        to: str = "opponents",
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.multiplier = int(multiplier)
        self.combat_only = combat_only
        self.to = to
        self.target_spec = TargetSpec(kind="creature")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = targets[0] if targets else None
        controller = _controller_of(self.source, context)
        if target is None or controller is None:
            return
        multiplier = self.multiplier
        combat_only = self.combat_only
        wants_opponents = self.to == "opponents"
        source_id = target.instance_id
        controller_id = controller.id

        def _replace(event: GameEvent, ctx: GameContext) -> Optional[GameEvent]:
            if event.get("source_id") != source_id:
                return event
            if combat_only and not event.get("combat"):
                return event
            if not event.get("is_player"):
                return event
            if wants_opponents and event.get("target_id") == controller_id:
                return event
            return event.copy_with(amount=int(event.get("amount", 0)) * multiplier)

        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=_replace,
            source=self.source,
            description=f"{target.name}: {multiplier}× Kampfschaden",
        )
        # "Until your next turn" (RULE 611.2b) — the same duration key
        # `GameEngine.begin_turn` already sweeps for `PlayerShieldEffect`
        # and Hope of Ghirapur's lock, here on a permanent instead.
        effect.until_next_turn_of = controller_id
        target.replacement_effects.append(effect)


class EffectRegistry:
    """Maps an effect-type name to a factory ``(params) -> GameEffect``.

    The hybrid design from docs/07 PART 4: predefined classes stay
    type-safe, but oracle-text parsing (a later step) can create effects
    by name + params without the engine knowing each card.
    """

    _factories: dict[str, Callable[[dict[str, Any]], GameEffect]] = {}

    @classmethod
    def register(cls, effect_type: str, factory: Callable[[dict[str, Any]], GameEffect]) -> None:
        cls._factories[effect_type] = factory

    @classmethod
    def create(cls, effect_type: str, params: Optional[dict[str, Any]] = None) -> GameEffect:
        if effect_type not in cls._factories:
            raise ValueError(f"unknown effect type: {effect_type!r}")
        return cls._factories[effect_type](params or {})

    @classmethod
    def is_registered(cls, effect_type: str) -> bool:
        return effect_type in cls._factories


# Register the core one-shot effects (RULE R3.1 in docs/02).
EffectRegistry.register(
    "damage",
    lambda p: DealDamageEffect(
        amount=p.get("amount", 0),
        target=p.get("target"),
        target_kind=p.get("target_kind", "any"),
        selector=p.get("selector"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        divided=bool(p.get("divided", False)),
        double_at=p.get("double_at"),
        amount_if_kicked=p.get("amount_if_kicked"),
    ),
)
EffectRegistry.register(
    "draw",
    lambda p: DrawCardEffect(
        count=p.get("count", 1), player=p.get("player"), count_selector=p.get("count_selector"),
        target_kind=p.get("target_kind"), selector=p.get("selector"),
    ),
)
EffectRegistry.register(
    "discard",
    lambda p: DiscardEffect(
        count=p.get("count", 1), player=p.get("player"),
        target_kind=p.get("target_kind"), scope=p.get("scope"),
    ),
)
EffectRegistry.register(
    "put_hand_cards_on_top",  # "put N cards from your hand on top of your library" (Brainstorm)
    lambda p: PutHandCardsOnTopEffect(count=p.get("count", 1), player=p.get("player")),
)
EffectRegistry.register(
    "reveal_hand_choose_discard",  # Duress/Thoughtseize/Coercion-shaped
    lambda p: RevealHandChooseDiscardEffect(
        target_kind=p.get("target_kind", "player"),
        target=p.get("target"),
        exclude_land=bool(p.get("exclude_land", False)),
        exclude_creature=bool(p.get("exclude_creature", False)),
        card_types=p.get("card_types"),
    ),
)
EffectRegistry.register(
    "reveal_top_conditional_to_hand",  # Goblin Guide-shaped
    lambda p: RevealTopConditionalToHandEffect(
        whose=p.get("whose", "defending_player"),
        card_type=p.get("card_type", "land"),
    ),
)
EffectRegistry.register(
    "destroy",
    lambda p: DestroyEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        selector=p.get("selector"),
        filter=p.get("filter"),
        can_be_regenerated=bool(p.get("can_be_regenerated", True)),
        color=p.get("color"),
        max_mana_value=p.get("max_mana_value"),
        creature_filter=p.get("creature_filter"),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        exclude_created=bool(p.get("exclude_created", False)),
    ),
)
EffectRegistry.register(
    "regenerate",
    lambda p: RegenerateEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    "gain_life",
    lambda p: GainLifeEffect(
        amount=p.get("amount", 0), player=p.get("player"), target_kind=p.get("target_kind"),
        count_selector=p.get("count_selector"),
    ),
)
EffectRegistry.register(
    "prevent_damage_shield",
    # RULE 615 one-shot "prevent all/the next N damage that would be dealt
    # to you this turn" (Riot Control/Thought Lash) — NOT the standing-
    # permanent shape; see `ReplacementRegistry`'s own unrelated
    # `"prevent_damage"` factory below for that (still uncarded/unused).
    lambda p: PreventDamageEffect(
        amount=p.get("amount", "all"),
        target_kind=p.get("target_kind"),
        target=p.get("target"),
        count=p.get("count", 1),
        optional=bool(p.get("optional", False)),
        divided=bool(p.get("divided", False)),
        amount_if_kicked=p.get("amount_if_kicked"),
    ),
)
EffectRegistry.register(
    "prevent_all_combat_damage",
    # RULE 615's unscoped Fog-shaped shield — distinct from
    # "prevent_damage_shield" above, which always shields one recipient.
    lambda p: PreventAllCombatDamageEffect(),
)
EffectRegistry.register(
    "extra_land_play",
    lambda p: ExtraLandPlayEffect(count=p.get("count", 1)),
)
EffectRegistry.register(
    "lose_life",
    lambda p: LoseLifeEffect(
        amount=p.get("amount", 0), player=p.get("player"), selector=p.get("selector"),
        target_kind=p.get("target_kind"), player_id=p.get("player_id"),
        amount_from_trigger_event=p.get("amount_from_trigger_event"),
        amount_from_life_gained_this_turn=bool(p.get("amount_from_life_gained_this_turn", False)),
        amount_from_burden_counters_on_self=bool(p.get("amount_from_burden_counters_on_self", False)),
    ),
)
EffectRegistry.register(
    "add_player_counters",
    lambda p: AddPlayerCountersEffect(
        amount=p.get("amount", 0), kind=p.get("kind", "rad"), player=p.get("player"),
        selector=p.get("selector"), target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    "lose_all_player_counters",
    lambda p: LoseAllPlayerCountersEffect(
        kind=p.get("kind", "rad"), player=p.get("player"), target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    "dies_grants_rad_counters_equal_power",
    lambda p: DiesGrantsRadCountersEqualPowerEffect(kind=p.get("kind", "rad")),
)
EffectRegistry.register(
    "counter",
    lambda p: CounterSpellEffect(
        target=p.get("target"),
        unless_pays=p.get("unless_pays"),
        noncreature=bool(p.get("noncreature", False)),
        card_types=p.get("card_types"),
        mana_value=p.get("mana_value"),
        color=p.get("color"),
    ),
)
EffectRegistry.register(
    "copy_spell",
    lambda p: CopySpellEffect(
        card_types=p.get("card_types"),
        count=p.get("count", 1),
    ),
)
EffectRegistry.register("cant_be_countered", lambda p: CantBeCounteredEffect())
EffectRegistry.register(
    "mill", lambda p: MillEffect(count=p.get("count", 1), target_kind=p.get("target_kind"))
)
EffectRegistry.register(
    "sacrifice_self",  # "Sacrifice ~." (Dress Down/Underworld Breach-shaped)
    lambda p: SacrificeSelfEffect(),
)
EffectRegistry.register(
    # "Sacrifice ~ unless you pay <cost>." (Arcades Sabboth/Breeding Pit/
    # Child of Gaea) — an interactive pay-or-lose-it choice, not a plain
    # sacrifice. ``cost`` is the printed cost *text*, parsed to an
    # `ActivationCost` at resolution.
    "sacrifice_unless_pay",
    lambda p: SacrificeUnlessPayEffect(cost=p.get("cost", "")),
)
EffectRegistry.register(
    # PAR-13: "Each player loses N life unless they `<pay cost>`." — the
    # APNAP mass sibling of `sacrifice_unless_pay` above.
    "each_player_pay_or",
    lambda p: EachPlayerPayOrEffect(cost=p.get("cost", ""), effects=list(p.get("effects", []))),
)
EffectRegistry.register(
    "exile",
    lambda p: ExileEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        selector=p.get("selector"),
        filter=p.get("filter"),
        remember=bool(p.get("remember", False)),
        creature_filter=p.get("creature_filter"),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
    ),
)
EffectRegistry.register(
    "exile_gain_life_equal_power",  # Swords to Plowshares-shaped
    lambda p: ExileGainLifeToControllerEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register("exile_all_graveyards", lambda p: ExileAllGraveyardsEffect())
EffectRegistry.register(
    "exile_graveyard_card_counter_if_permanent",  # Lion Sash
    lambda p: ExileGraveyardCardCounterIfPermanentEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "any_graveyard_card")
    ),
)
EffectRegistry.register(
    "exile_graveyard_creatures_gain_life",  # Crypt Incursion
    lambda p: ExileGraveyardCreaturesGainLifeEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "player"),
        life_per_card=p.get("life_per_card", 3),
    ),
)
EffectRegistry.register(
    "exile_target_graveyard",  # Bojuka Bog/Tormod's Crypt
    lambda p: ExileTargetGraveyardEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "player"),
    ),
)
EffectRegistry.register(
    "destroy_lose_life_equal_mana_value",  # Feed the Swarm
    lambda p: DestroyLoseLifeEqualManaValueEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
    ),
)
EffectRegistry.register(
    "exile_create_token",  # Resculpt
    lambda p: ExileCreateTokenEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
        power=p.get("power"), toughness=p.get("toughness"),
        colors=list(p.get("colors", [])), subtypes=list(p.get("subtypes", [])),
        token_name=p.get("token_name"),
    ),
)
EffectRegistry.register(
    "destroy_create_token",  # Beast Within
    lambda p: DestroyCreateTokenEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
        power=p.get("power"), toughness=p.get("toughness"),
        colors=list(p.get("colors", [])), subtypes=list(p.get("subtypes", [])),
        token_name=p.get("token_name"),
        can_be_regenerated=bool(p.get("can_be_regenerated", True)),
    ),
)
EffectRegistry.register(
    "counter_create_token",  # Swan Song, Strix Serenade, An Offer You Can't Refuse
    lambda p: CounterCreateTokenEffect(
        target=p.get("target"),
        noncreature=bool(p.get("noncreature", False)),
        card_types=list(p.get("card_types", [])) or None,
        power=p.get("power"), toughness=p.get("toughness"),
        colors=list(p.get("colors", [])), subtypes=list(p.get("subtypes", [])),
        token_name=p.get("token_name"),
        count=int(p.get("count", 1)),
        keywords=list(p.get("keywords", [])),
    ),
)
EffectRegistry.register(
    "destroy_gain_life_to_controller",  # Nature's Claim
    lambda p: DestroyGainLifeToControllerEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
        amount=int(p.get("amount", 0)),
        can_be_regenerated=bool(p.get("can_be_regenerated", True)),
    ),
)
EffectRegistry.register(
    "gain_control_until_eot",  # Zealous Conscripts / Coercive Recruiter
    lambda p: GainControlUntilEndOfTurnEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
        haste=bool(p.get("haste", True)),
    ),
)
EffectRegistry.register("return_linked_exile", lambda p: ReturnLinkedExileEffect())
EffectRegistry.register("exile_library", lambda p: ExileLibraryEffect())
EffectRegistry.register(
    "shuffle_graveyard_into_library", lambda p: ShuffleGraveyardIntoLibraryEffect()
)
EffectRegistry.register(
    "graveyard_to_library_bottom_random",  # Endurance
    lambda p: GraveyardToLibraryBottomRandomEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "player"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "return_to_hand_draw_if_controlled",  # Geistwave
    lambda p: ReturnToHandDrawIfControlledEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "nonland_permanent"),
    ),
)
EffectRegistry.register(
    "grant_flash_until_eot", lambda p: GrantFlashUntilEndOfTurnEffect()  # Borne Upon a Wind
)
EffectRegistry.register(
    "exile_controller_searches_basic_land",  # Winds of Abandon
    lambda p: ExileControllerSearchesBasicLandEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    "return_top_graveyard_creature_with_haste",  # Corpse Dance
    lambda p: ReturnTopGraveyardCreatureWithHasteEffect(
        delayed_exile_step=p.get("delayed_exile_step"),
    ),
)
EffectRegistry.register("peek_top_land_battlefield_tapped", lambda p: PeekTopLandBattlefieldTappedEffect())
EffectRegistry.register(
    "target_player_draw_lose_life",  # Sign in Blood
    lambda p: TargetPlayerDrawLoseLifeEffect(
        draw_count=p.get("draw_count", 1), life_loss=p.get("life_loss", 0),
        target=p.get("target"), target_kind=p.get("target_kind", "player"),
    ),
)
EffectRegistry.register(
    "add_counter_first_strike",  # The Wandering Emperor +1
    lambda p: CounterAndFirstStrikeEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "create_token_may_attach_equipment",  # Nahiri, Heir of the Ancients
    lambda p: CreateTokenMayAttachEquipmentEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "equipment_you_control"),
        optional=bool(p.get("optional", True)),
        token_name=p.get("token_name", "token"),
        power=p.get("power", 1),
        toughness=p.get("toughness", 1),
        colors=p.get("colors"),
        subtypes=p.get("subtypes"),
    ),
)
EffectRegistry.register(
    "return_to_hand",  # "return target X to its owner's hand" (RULE 701.3)
    lambda p: ReturnToHandEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    # "return target creature card from your graveyard to the battlefield/
    # your hand" (RULE 701.3, Regrowth/Reanimate-shaped)
    "return_from_graveyard",
    lambda p: ReturnFromGraveyardEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "graveyard_creature"),
        destination=p.get("destination", "battlefield"),
        under_your_control=bool(p.get("under_your_control", False)),
        optional=bool(p.get("optional", False)),
        lose_life_equal_mv=bool(p.get("lose_life_equal_mv", False)),
        count=p.get("count", 1),
        shuffle_after=bool(p.get("shuffle_after", False)),
    ),
)
EffectRegistry.register(
    "add_mana",  # a spell's own bare "Add {B}{B}{B}." body (RULE 106.4, Dark Ritual)
    lambda p: AddManaEffect(
        colors=list(p.get("colors", [])),
        amount=p.get("amount"),
        color=p.get("color", "C"),
        amount_selector=p.get("amount_selector"),
        amount_from_trigger_event=p.get("amount_from_trigger_event"),
        recipient=p.get("recipient", "controller"),
    ),
)
EffectRegistry.register(
    # "Add one mana of any type that permanent produced." (Kinnan) — RULE
    # 605.1b triggered-mana-ability body; the type comes from the firing.
    "mirror_produced_mana",
    lambda p: MirrorProducedManaEffect(count=int(p.get("count", 1) or 1)),
)
EffectRegistry.register(
    # "Tap all lands that player controls that could produce any type of
    # mana that land could produce." (Mana Web)
    "tap_matching_lands",
    lambda p: TapMatchingLandsEffect(),
)
EffectRegistry.register(
    "create_delayed_trigger",  # RULE 603.7 "at the beginning of your next … , …"
    lambda p: CreateDelayedTriggerEffect(
        step=p.get("step", "upkeep"),
        effects=list(p.get("effects", [])),
        scope=p.get("scope", "controller"),
        capture=p.get("capture"),
        min_turn_offset=p.get("min_turn_offset", 0),
        description=p.get("description", ""),
    ),
)
EffectRegistry.register(
    # RULE 603.7-adjacent recurring player-scoped trigger (Nuka-Nuke
    # Launcher's "until the end of defending player's next turn, that
    # player gets rad counters whenever they cast a spell").
    "install_temporary_player_trigger",
    lambda p: InstallTemporaryPlayerTriggerEffect(
        event_type=p.get("event_type", "SPELL_CAST"),
        effects=list(p.get("effects", [])),
        description=p.get("description", ""),
    ),
)
EffectRegistry.register(
    # RULE 122/601.2b resolve-time optional energy payment (Aether Chaser —
    # "you may pay {E}{E}. If you do, create a 1/1 Servo").
    "pay_energy_then",
    lambda p: PayEnergyThenEffect(
        amount=p.get("amount", 0),
        effects=list(p.get("effects", [])),
    ),
)
EffectRegistry.register(
    # RULE 118.3 resolve-time optional payment, generalized past energy:
    # "you may pay <cost>. If you do, <effect>. [If you don't, <effect>.]"
    # (Mana Vault's upkeep untap, Wandering Archaic's per-opponent {2}).
    "pay_cost_then",
    lambda p: PayCostThenEffect(
        cost=p.get("cost", ""),
        effects=list(p.get("effects", [])),
        else_effects=list(p.get("else_effects", [])),
        payer=p.get("payer", "controller"),
    ),
)
EffectRegistry.register(
    # RULE 301.5c: "attach target Equipment you control to target creature
    # you control" (Brass Squire, Halvar) — two independently-chosen targets
    # of different kinds in one clause.
    "attach_chosen",
    lambda p: AttachChosenEffect(
        what_kind=p.get("what_kind", "equipment_you_control"),
        to_kind=p.get("to_kind", "creature_you_control"),
    ),
)
EffectRegistry.register(
    # Archdruid's Charm's second mode — counter first, then damage equal to
    # the *boosted* power.
    "counter_then_fightlike_damage",
    lambda p: CounterThenFightlikeDamageEffect(
        counters=int(p.get("counters", 1) or 1), kind=p.get("kind", "+1/+1"),
    ),
)
EffectRegistry.register(
    # RULE 701.14 fight — "target creature you control fights target creature
    # you don't control" (Prey Upon), "it fights up to one target creature you
    # don't control" (Kogla's ETB, ``fighter_kind=None``).
    "fight",
    lambda p: FightEffect(
        fighter_kind=p.get("fighter_kind"),
        other_kind=p.get("other_kind", "creature"),
        fighter_optional=bool(p.get("fighter_optional", False)),
        optional=bool(p.get("optional", False)),
        distinct=bool(p.get("distinct", False)),
    ),
)
EffectRegistry.register(
    # The one-sided fight — "target creature you control deals damage equal to
    # its power to target creature you don't control" (Rabid Bite), "when ~
    # dies, it deals damage equal to its power to any target".
    "damage_equal_to_power",
    lambda p: DamageEqualToPowerEffect(
        dealer_kind=p.get("dealer_kind"),
        target_kind=p.get("target_kind", "any"),
        selector=p.get("selector"),
        dealer_optional=bool(p.get("dealer_optional", False)),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    # "~ deals damage equal to the number of +1/+1 counters on it to any
    # other target." (Red Hulk) — `damage_equal_to_power`'s counter-count
    # sibling.
    "damage_equal_to_counters",
    lambda p: DamageEqualToCountersEffect(
        kind=p.get("kind", "+1/+1"),
        target_kind=p.get("target_kind", "any"),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    # RULE 601.2c target announcement with no effect of its own — "choose
    # target creature you control and target creature you don't control."
    "choose_targets",
    lambda p: ChooseTargetsEffect(
        kinds=list(p.get("kinds", []) or []),
        count=p.get("count"),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    # "Destroy each artifact with mana value X." (Dauntless Dismantler)
    "destroy_each_with_mana_value",
    lambda p: DestroyEachWithManaValueEffect(
        amount=p.get("amount", 0), card_type=p.get("card_type", "artifact"),
    ),
)
EffectRegistry.register(
    # RULE 701.17: "each opponent sacrifices a creature with the greatest
    # power among creatures that player controls" (Professor Onyx's −3).
    # Previously only reachable from the annihilator keyword, never the
    # registry.
    "sacrifice",
    lambda p: SacrificeEffect(
        count=int(p.get("count", 1) or 1),
        what=p.get("what", "permanent"),
        selector=p.get("selector"),
        greatest_power=bool(p.get("greatest_power", False)),
    ),
)
EffectRegistry.register(
    # "Each opponent may discard a card. If they don't, they lose N life.
    # Repeat this process M more times." (Professor Onyx's −8)
    "discard_or_lose_life",
    lambda p: DiscardOrLoseLifeEffect(
        count=int(p.get("count", 1) or 1),
        amount=int(p.get("amount", 3) or 3),
        times=int(p.get("times", 1) or 1),
        selector=p.get("selector", "each_opponent"),
        round_index=int(p.get("round_index", 0) or 0),
        player_index=int(p.get("player_index", 0) or 0),
    ),
)
EffectRegistry.register(
    # RULE 903.3/110.2: "gain control of all commanders; put all commanders
    # from the command zone onto the battlefield under your control."
    # (Tevesh Szat, Doom of Fools' −10)
    "gain_control_of_all_commanders",
    lambda p: GainControlOfAllCommandersEffect(),
)
EffectRegistry.register(
    # RULE 616.1, scoped to one source / combat only / your opponents, and
    # duration-bounded (Jeska, Thrice Reborn's 0).
    "multiply_damage_from_target",
    lambda p: MultiplyDamageFromTargetEffect(
        multiplier=int(p.get("multiplier", 2) or 2),
        combat_only=bool(p.get("combat_only", True)),
        to=p.get("to", "opponents"),
    ),
)
EffectRegistry.register(
    "untap_self",  # "Untap this permanent." (Mana Vault)
    lambda p: UntapSelfEffect(),
)
EffectRegistry.register(
    # RULE 702.32b Fading / 702.61b Vanishing: "remove a counter … if you
    # can't, sacrifice it."
    "remove_counter_or_sacrifice",
    lambda p: RemoveCounterOrSacrificeEffect(kind=p.get("kind", "fade")),
)
EffectRegistry.register(
    # "That player taps an untapped artifact, creature, or land they control
    # for each fade counter on this artifact." (Tangle Wire)
    "tap_permanents_per_counter",
    lambda p: TapPermanentsPerCounterEffect(
        kind=p.get("kind", "fade"), types=p.get("types"),
    ),
)
EffectRegistry.register(
    "mutate",  # RULE 702.140b merge (Lore Drakkis)
    lambda p: MutateEffect(
        target_kind=p.get("target_kind", "non_human_creature_you_own"),
    ),
)
EffectRegistry.register(
    "name_card_then",  # "Choose a card name. <effect>" (Demonic Consultation)
    lambda p: NameCardThenEffect(effects=list(p.get("effects", []))),
)
EffectRegistry.register(
    # "…reveal/exile cards from the top of your library until <predicate>"
    # — the parameterized form of the cascade/discover dig.
    "dig_until",
    lambda p: DigUntilEffect(
        criteria=p.get("criteria", ""),
        hit_destination=p.get("hit_destination", "hand"),
        rest_destination=p.get("rest_destination", "exile"),
        pre_exile=int(p.get("pre_exile", 0) or 0),
    ),
)
EffectRegistry.register(
    # "…mills a card, then repeats this process until a creature card or X
    # cards…" (Helm of Obedience) — the first repeat-until-predicate loop.
    "mill_until_creature",
    lambda p: MillUntilCreatureEffect(
        amount=p.get("amount", 0), target_kind=p.get("target_kind", "player"),
    ),
)
EffectRegistry.register(
    # Possibility Storm / Tibalt's Trickery: answer a spell, then dig its
    # *controller's* library for a replacement they may cast for free.
    "scramble_spell",
    lambda p: ScrambleSpellEffect(
        answer=p.get("answer", "counter"),
        match=p.get("match", "different_name"),
        mill_random_max=int(p.get("mill_random_max", 0) or 0),
        card_types=p.get("card_types"),
    ),
)
EffectRegistry.register(
    # "As many times as you choose, you may pay 1 life…" (Lim-Dûl's Vault)
    "look_top_pay_life_loop",
    lambda p: LookTopPayLifeLoopEffect(
        count=int(p.get("count", 5) or 5), life_cost=int(p.get("life_cost", 1) or 1),
    ),
)
EffectRegistry.register(
    # RULE 108.4/701.10: "exchange control of ~ and up to one target
    # creature an opponent controls" (Gilded Drake) — a genuine two-way
    # swap, not a one-way grab.
    "exchange_control",
    lambda p: ExchangeControlEffect(
        target_kind=p.get("target_kind", "creature"),
        sacrifice_self_if_no_exchange=bool(p.get("sacrifice_self_if_no_exchange", False)),
    ),
)
EffectRegistry.register(
    # RULE 702.26b + 611.2b: "all permanents you control phase out", plus
    # the life lock and protection from everything (Teferi's Protection).
    "phase_out_all_you_control",
    lambda p: PhaseOutAllYouControlEffect(),
)
EffectRegistry.register(
    # RULE 707.10 + 400.1: "copy target instant or sorcery spell, then
    # return it to its owner's hand" (Narset's Reversal).
    "copy_spell_and_bounce",
    lambda p: CopySpellAndBounceEffect(card_types=p.get("card_types")),
)
EffectRegistry.register(
    # "return another permanent you control that shares a permanent type
    # with it to its owner's hand" (Cloudstone Curio).
    "return_shared_type_permanent",
    lambda p: ReturnSharedTypePermanentEffect(),
)
EffectRegistry.register(
    # "Whenever this creature deals combat damage to a creature, exile that
    # creature." (Kaldra Compleat's granted ability) — see
    # `ExileTriggerDamagedCreatureEffect`.
    "exile_trigger_damaged_creature",
    lambda p: ExileTriggerDamagedCreatureEffect(),
)
EffectRegistry.register(
    # "Put up to N <criteria> cards from your hand onto the battlefield."
    # (Tooth and Nail's second mode) — a pick from *hand*, unlike every
    # other "put onto the battlefield" (library/graveyard).
    "put_from_hand_onto_battlefield",
    lambda p: PutFromHandOntoBattlefieldEffect(
        criteria=p.get("criteria", p.get("type", "")),
        count=int(p.get("count", 1) or 1),
    ),
)
EffectRegistry.register("take_extra_turn", lambda p: TakeExtraTurnEffect())
EffectRegistry.register(
    # "You may sacrifice/tap/return a <kind> you control." — the player
    # picks which; see `RulesEngine.request_choose_objects`.
    "choose_objects",
    lambda p: ChooseObjectsEffect(
        action=str(p.get("action", "sacrifice")),
        what=str(p.get("what", "permanent")),
        count=int(p.get("count", 1) or 1),
        optional=bool(p.get("optional", False)),
        exclude_self=bool(p.get("exclude_self", False)),
        prompt=str(p.get("prompt", "")),
        then=p.get("then"),
        then_if_commander=p.get("then_if_commander"),
    ),
)
EffectRegistry.register(
    "the_ring_tempts_you",  # RULE 701.51a
    lambda p: TheRingTemptsYouEffect(),
)
EffectRegistry.register(
    "cast_exiled_face_down",  # Beseech the Mirror (RULE 701.20a)
    lambda p: CastExiledFaceDownEffect(
        max_mana_value=p.get("max_mana_value"),
        require_bargained=p.get("require_bargained", False),
    ),
)
EffectRegistry.register(
    "cheat_creature_from_hand",  # Sneak Attack/Meek Attack
    lambda p: CheatCreatureFromHandEffect(max_total_pt=p.get("max_total_pt")),
)
EffectRegistry.register(
    "grant_protection",
    lambda p: GrantProtectionEffect(
        target_kind=p.get("target_kind", "creature_you_control"),
        allow_colorless=bool(p.get("allow_colorless", False)),
    ),
)
EffectRegistry.register(
    "lose_game", lambda p: LoseGameEffect(reason=p.get("reason", "effect"))
)
EffectRegistry.register(
    "lose_game_trigger_damaged_player",
    lambda p: LoseGameTriggerDamagedPlayerEffect(reason=p.get("reason", "effect")),
)
EffectRegistry.register(
    "blink",  # "Exile target permanent, then return it to the battlefield" (Ephemerate)
    lambda p: BlinkEffect(
        target_kind=p.get("target_kind", "creature_you_control"),
        under_your_control=bool(p.get("under_your_control", False)),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    "tap",
    lambda p: TapEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        untap=bool(p.get("untap", False)),
        optional=bool(p.get("optional", False)),
        selector=p.get("selector"),
        count=int(p.get("count", 1)),
        previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    "unblockable",  # "Target creature can't be blocked this turn" (Rogue's Passage)
    lambda p: UnblockableEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    # "Target creature can't block this turn" (Falter/Abandon the Post) and
    # "creatures your opponents control can't block this turn" (the mass
    # form) — the blocker-side mirror of "unblockable" just above.
    "cant_block_this_turn",
    lambda p: CantBlockEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        selector=p.get("selector"),
        filter=dict(p.get("filter") or {}),
        count=int(p.get("count", 1)),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    # "~ can't be blocked by creatures with power 2 or less this turn"
    # (Cavern Stomper) — the resolve-time sibling of the standing
    # `combat_restriction` static registered further down.
    "combat_restriction_this_turn",
    lambda p: GrantCombatRestrictionEffect(
        restriction=dict(p.get("restriction") or {}),
        target=p.get("target"),
        target_kind=p.get("target_kind"),
        restrict_to_source=bool(p.get("restrict_to_source", False)),
    ),
)
EffectRegistry.register(
    "attach",
    lambda p: AttachEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
    ),
)
EffectRegistry.register(
    # "Whenever a[n] <X> you control enters, you may attach it to target
    # creature you control." (Sigarda's Aid) — the mover is the trigger
    # event's own subject, not a chosen target; see
    # `AttachTriggeringPermanentEffect`.
    "attach_triggering_permanent",
    lambda p: AttachTriggeringPermanentEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature_you_control"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "unattach_tap_indestructible",  # Akiri, Fearless Voyager
    lambda p: UnattachTapIndestructibleEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "attached_equipment_you_control"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "return_creature_grant_indestructible",  # Temur Sabertooth
    lambda p: ReturnCreatureGrantIndestructibleEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature_you_control"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "enter_as_copy",  # "You may have this enter as a copy of target X" (RULE 614.1c/614.12)
    lambda p: EnterAsCopyReplacement(
        target_kind=p.get("target_kind", "permanent"),
        add_types=list(p.get("add_types", [])),
        add_subtypes=list(p.get("add_subtypes", [])),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "choose_creature_type_on_enter",  # "As ~ enters, choose a creature type." (RULE 601.2b)
    lambda p: ChooseCreatureTypeReplacement(),
)
EffectRegistry.register(
    "choose_color_on_enter",  # "As ~ enters, choose a color." (RULE 601.2b)
    lambda p: ChooseColorReplacement(),
)
EffectRegistry.register(
    "choose_basic_land_type_on_enter",  # "As ~ enters, choose a basic land type." (RULE 601.2b, PAR-4)
    lambda p: ChooseBasicLandTypeReplacement(),
)
EffectRegistry.register(
    # "As this enters, choose <Label1> or <Label2>." (Struggle for Project
    # Purity-shaped) — hand-authored only, no oracle-text grammar yet.
    "choose_named_mode",
    lambda p: ChooseNamedModeReplacement(options=list(p.get("options", []))),
)
EffectRegistry.register(
    "become_copy_until_eot",  # "~ becomes a copy of target creature until end of turn" (Cursed Mirror)
    lambda p: BecomeCopyUntilEndOfTurnEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    "set_copy_target",  # Vesuvan Shapeshifter's "you may have it be a copy of another target creature"
    lambda p: SetCopyTargetEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    "conditional_copy",  # RULE 707/613 layer 1 — "as long as [condition], ~ is a copy of [target]"
    lambda p: StaticAbility(
        "copy",
        affects="self",
        params={
            "requires_untapped": bool(p.get("requires_untapped", False)),
            "add_types": list(p.get("add_types", [])),
            "add_subtypes": list(p.get("add_subtypes", [])),
        },
    ),
)
EffectRegistry.register(
    "text_change",  # RULE 612 layer 3 — word-substitution over effective_oracle_text
    lambda p: StaticAbility(
        "text",
        affects=p.get("affects", "self"),
        params={"replace": {str(k): str(v) for k, v in dict(p.get("replace", {})).items()}},
    ),
)
EffectRegistry.register(
    "add_counters",
    lambda p: AddCountersEffect(
        amount=p.get("amount", p.get("count", 1)),
        target_kind=p.get("target_kind"),
        kind=p.get("kind", "+1/+1"),
        optional=bool(p.get("optional", False)),
        selector=p.get("selector"),
        trigger_subject_key=p.get("trigger_subject_key"),
        # A distinct key from "count"/"amount" (both already the *counter*
        # amount per card) — this is the *target* count (RULE 115.1a N>=2,
        # "put a counter on each of up to two target creatures").
        count=p.get("target_count", 1),
        subtypes=p.get("subtypes"),
        divided=bool(p.get("divided", False)),
        amount_from_trigger_event=p.get("amount_from_trigger_event"),
        x_multiplier=p.get("x_multiplier"),
    ),
)
EffectRegistry.register(
    "class_level",  # RULE 716.2c: activating "Level N: <cost>" sets class level to N
    lambda p: ClassLevelEffect(level=p.get("level", 1)),
)
EffectRegistry.register(
    "pump",  # "target creature gets +N/+N (and gains <kw>) until end of turn"
    lambda p: PumpEffect(
        power=p.get("power", 0),
        toughness=p.get("toughness", 0),
        keywords=list(p.get("keywords", [])),
        target_kind=p.get("target_kind"),
        selector=p.get("selector"),
        unblockable=bool(p.get("unblockable", False)),
        count=p.get("target_count", 1),
        optional=bool(p.get("optional", False)),
        amount_from_trigger_event=p.get("amount_from_trigger_event"),
        per_recipient_controller_counter=p.get("per_recipient_controller_counter"),
        amount_from_count_selector=p.get("amount_from_count_selector"),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    "scry", lambda p: ScryEffect(count=p.get("count", p.get("amount", 1)))
)
EffectRegistry.register(
    "surveil", lambda p: SurveilEffect(count=p.get("count", p.get("amount", 1)))
)
EffectRegistry.register(
    # RULE 701.40a manifest / RULE 701.58a cloak — one effect, one ``kind``
    # param (see `ManifestEffect`).
    "manifest",
    lambda p: ManifestEffect(
        count=p.get("count", p.get("amount", 1)), kind=p.get("kind", "manifest")
    ),
)
EffectRegistry.register("manifest_dread", lambda p: ManifestDreadEffect())
EffectRegistry.register(
    "top_library_permission",
    lambda p: TopLibraryPermissionEffect(
        look=p.get("look", False),
        play_lands=p.get("play_lands", False),
        cast_spells=p.get("cast_spells", False),
        min_mana_value=p.get("min_mana_value"),
        requires_attached=p.get("requires_attached", False),
        noncreature_only=p.get("noncreature_only", False),
        grants_flash=p.get("grants_flash", False),
        life_payment=p.get("life_payment", False),
    ),
)
EffectRegistry.register(
    "graveyard_cast_permission",
    lambda p: GraveyardCastPermissionEffect(
        max_mana_value=p.get("max_mana_value"),
        permanent_only=p.get("permanent_only", True),
        once_per_turn=p.get("once_per_turn", True),
        exile_if_would_be_put_into_graveyard=p.get("exile_if_would_be_put_into_graveyard", False),
    ),
)
EffectRegistry.register(
    "create_token",
    lambda p: CreateTokenEffect(
        count=p.get("count", 1),
        token_name=p.get("token_name"),
        power=p.get("power"),
        toughness=p.get("toughness"),
        colors=list(p.get("colors", [])),
        subtypes=list(p.get("subtypes", [])),
        keywords=list(p.get("keywords", [])),
        count_selector=p.get("count_selector"),
        creators=p.get("creators", "you"),
        tapped=bool(p.get("tapped", False)),
        legendary=bool(p.get("legendary", False)),
        pt_from_trigger_event=p.get("pt_from_trigger_event"),
        count_from_trigger_event=p.get("count_from_trigger_event"),
    ),
)
EffectRegistry.register(
    "copy_permanent",  # "Create a token that's a copy of target creature" (RULE 707)
    lambda p: CopyPermanentEffect(
        count=p.get("count", 1),
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        count_if_kicked=p.get("count_if_kicked"),
    ),
)
EffectRegistry.register(
    "search",
    lambda p: SearchLibraryEffect(
        # "criteria" is the general form; "type" stays a shorthand for a
        # type-line restriction so an oracle handler can emit either.
        criteria=p.get("criteria", p.get("type", "")),
        destination=p.get("destination", "hand"),
        count=p.get("count", 1),
        optional=p.get("optional", True),
        zones=p.get("zones"),
        destinations=p.get("destinations"),
        destination_if=p.get("destination_if"),
        exile_rest=p.get("exile_rest", False),
        mana_value_from=p.get("mana_value_from"),
        extra_counters=p.get("extra_counters"),
    ),
)
EffectRegistry.register(
    "impulsive_look",
    lambda p: ImpulsiveLookEffect(
        count=p.get("count", 1),
        criteria=p.get("criteria", ""),
        hit_destination=p.get("hit_destination", "hand"),
        miss_destination=p.get("miss_destination", "graveyard"),
        optional=p.get("optional", True),
    ),
)
EffectRegistry.register(
    "impulsive_draw",
    lambda p: ImpulsiveDrawEffect(
        count=p.get("count", 1), same_turn_only=bool(p.get("same_turn_only", False)),
    ),
)
EffectRegistry.register(
    "draw_reveal_cast_one_free",
    lambda p: DrawRevealCastOneFreeEffect(count=p.get("count", 1)),
)
EffectRegistry.register(
    "exile_opponents_graveyards_impulsive_cast",  # Mnemonic Betrayal
    lambda p: GraveyardImpulsiveCastEffect(mana_wildcard=p.get("mana_wildcard", "type")),
)
EffectRegistry.register("shuffle", lambda p: ShuffleLibraryEffect())
EffectRegistry.register(
    "wheel",  # "Each player shuffles their hand and graveyard into their library, then draws seven cards." (Timetwister)
    lambda p: WheelEffect(draw_count=p.get("draw_count", p.get("count", 7))),
)
EffectRegistry.register(
    "windfall",  # "Each player discards their hand, then draws cards equal to the greatest number discarded." (Windfall)
    lambda p: WindfallEffect(),
)
EffectRegistry.register(
    "transform", lambda p: TransformEffect(target_kind=p.get("target_kind"))
)
EffectRegistry.register(
    # "Look at the top card of your library. If it's a[n] <type> card,
    # transform ~." (Delver of Secrets-shaped).
    "reveal_top_then_transform",
    lambda p: RevealTopThenTransformEffect(criteria=p.get("criteria", "")),
)
EffectRegistry.register(
    "exile_return_transformed", lambda p: ExileReturnTransformedEffect()
)
EffectRegistry.register(
    "return_from_graveyard_transformed", lambda p: ReturnFromGraveyardTransformedEffect()
)
EffectRegistry.register(
    # "Return this card from your graveyard to the battlefield[, tapped]."
    # (Dread Wanderer/Bloodsoaked Champion/Drownyard Temple &c) — the plain
    # sibling of `return_from_graveyard_transformed` above.
    "return_self_from_graveyard",
    lambda p: ReturnSelfFromGraveyardToBattlefieldEffect(tapped=bool(p.get("tapped", False))),
)
EffectRegistry.register(
    # "Return this card from your graveyard to your hand." (PAR-16 —
    # Abzan Devotee/Aurora Eidolon &c) — the hand-destination sibling of
    # `return_self_from_graveyard` right above.
    "return_self_from_graveyard_to_hand",
    lambda p: ReturnSelfFromGraveyardToHandEffect(),
)
EffectRegistry.register(
    # "return it to the battlefield. It's a[n] <type> with '<ability>'. ~
    # loses all other abilities." (Harold and Bob, First Numens) —
    # hand-authored only, no oracle-text grammar for this shape yet.
    "return_dies_as_new_permanent",
    lambda p: ReturnDiesAsNewPermanentEffect(
        new_type_line=p.get("new_type_line", ""),
        new_oracle_text=p.get("new_oracle_text", ""),
        target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register("become_prepared", lambda p: BecomePreparedEffect())
EffectRegistry.register(
    "phase_out",
    lambda p: PhaseOutEffect(target_kind=p.get("target_kind"), optional=bool(p.get("optional", False))),
)
EffectRegistry.register("cascade", lambda p: CascadeEffect(mana_value=p.get("mana_value")))
EffectRegistry.register("proliferate", lambda p: ProliferateEffect(times=p.get("times", 1)))
EffectRegistry.register(
    # "remove all counters from target permanent" / "remove all counters
    # from all permanents" (RULE 122 — Vampire Hexmage/Oblivion Stone/
    # Aether Snap/Thief of Blood-shaped); no ``target_kind`` = untargeted,
    # board-wide. ``max_count`` (Glissa Sunslayer/Heartless Act/Render
    # Inert-shaped "remove up to N counters") switches to the interactive
    # chosen-amount shape instead — see `RemoveCountersEffect`.
    "remove_counters",
    lambda p: RemoveCountersEffect(target_kind=p.get("target_kind"), max_count=p.get("max_count")),
)
EffectRegistry.register(
    "discover",
    lambda p: DiscoverEffect(mana_value=p.get("mana_value", p.get("amount", 0))),
)

# Static abilities applied through the layer system (RULE 613). Each becomes a
# `StaticAbility`; `game/continuous.py` folds them into derived characteristics.

#: The extra selector filters a static ability may narrow its `affects` set by —
#: a tribal subtype, tokens-only, a colour, "other" (exclude the source), or a
#: RULE 613.6-style "as long as this source's own <counter> is in range"
#: conditional gate (`min_level`/`max_level`/`level_counter` — Leveler tiers,
#: RULE 711, and cumulative Class levels, RULE 716). `continuous.
#: affected_objects`/`group_selector_objects` read these; only the non-
#: ``None`` ones are carried so a filter is off unless the parser/author set it.
_SELECTOR_KEYS: tuple[str, ...] = (
    "subtype", "tokens", "color", "exclude_self",
    "min_level", "max_level", "level_counter",
    # "During your turn, …" (Nahiri, Storm of Stone).
    "active_player_only",
    # Metalcraft-style "as long as you control N or more <count_selector>"
    # (Indomitable Archangel).
    "min_count_selector", "min_count",
    # A printed-card-type filter ("Artifacts your opponents control enter
    # tapped.", "Nonbasic lands are Mountains.") and its "nonbasic" qualifier
    # — `continuous._has_card_type`/the "basic" substring check.
    "card_type", "nonbasic",
    # RULE 601.2b "… of the chosen type/color …" (Adaptive Automaton/Caged
    # Sun-shaped) — read the ability source's own `chosen_type`/
    # `chosen_color` fresh each recompute instead of a literal `subtype`/
    # `color` baked in at parse time; see `continuous.group_selector_objects`.
    "subtype_from_source", "color_from_source",
    # A per-object power/toughness qualifier on the scope itself ("Each
    # creature you control **with power 4 or greater** …" — Challenger
    # Troll/Flopsie-shaped); read off each affected object's own *derived*
    # characteristics, unlike every filter above (all about type/colour).
    "min_power", "max_power", "min_toughness", "max_toughness",
    # The same qualifier with a *dynamic* threshold instead of a literal
    # ("Creatures your opponents control with power less than ~'s power are
    # goaded." — Baeloth Barrityl): `continuous.dynamic_threshold`'s
    # vocabulary, strict `<`/`>` to match the printed "less/greater than".
    "power_lt_selector", "power_gt_selector",
    # RULE 613.6's general "as long as <condition>" gate — one whitelisted
    # dict from `game/static_conditions.py`, evaluated live every recompute
    # (`continuous.group_selector_objects`). The three older gates above
    # (`active_player_only`, `min_level`/`max_level`, `min_count_selector`/
    # `min_count`) are the same idea per-card, and are translated into this
    # vocabulary rather than evaluated separately.
    "active_if",
)


def _selectors(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in _SELECTOR_KEYS if p.get(k) is not None}


EffectRegistry.register(
    "anthem",  # "Creatures you control get +N/+N" (layer 7c); tribal/colour-scoped
    lambda p: StaticAbility(
        "pt_mod",
        affects=p.get("affects", "other_creatures_you_control"),
        params={
            "power": p.get("power", 0), "toughness": p.get("toughness", 0),
            # A per-count anthem ("+1/+1 for each land you control") — see
            # `continuous._pt_mod_count` for the selector vocabulary
            # (controller-scoped `count_selector` names, plus the per-object
            # ``"equipment_attached_to_self"``).
            "power_count": p.get("power_count"), "toughness_count": p.get("toughness_count"),
            # The counter kind ``"counters_on_self"`` (`continuous.
            # _pt_mod_count`) reads — "unity"/other named counters, default
            # "+1/+1" so an unparameterized per-counter anthem is unchanged.
            "counter_kind": p.get("counter_kind", "+1/+1"),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    "pt_set",  # "Each creature is 1/1" (layer 7b)
    lambda p: StaticAbility(
        "pt_set",
        affects=p.get("affects", "all_creatures"),
        params={"power": p.get("power", 0), "toughness": p.get("toughness", 0),
                **_selectors(p)},
    ),
)
EffectRegistry.register(
    # RULE 701.15b goad as a *standing static* ("Enchanted creature gets +2/+2
    # and is goaded.") — not a layer at all: goaded is explicitly neither an
    # ability nor a copiable value, so it can't be a layer-6 grant. Stamped
    # onto `GameObject._goaded_by_static` by `continuous.recompute` in the
    # same non-RULE-613 bucket the combat restrictions use.
    "goaded",
    lambda p: StaticAbility(
        "goaded",
        affects=p.get("affects", "attached_permanent"),
        params={**_selectors(p)},
    ),
)
EffectRegistry.register(
    "grant_keyword",  # "Creatures you control have flying" (layer 6); tribal too
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "creatures_you_control"),
        params={"keywords": list(p.get("keywords", [])), **_selectors(p)},
    ),
)
EffectRegistry.register(
    # "Equipped creature … loses flying" (Colossus Hammer) — layer 6,
    # ability-*removing* (RULE 613.7f), the mirror image of `grant_keyword`:
    # strips a flag keyword from `_obj_keywords` (`game/combat.py`) instead
    # of adding one, regardless of which of the object's three keyword
    # sources granted it.
    "remove_keyword",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "attached_permanent"),
        params={"remove_keywords": list(p.get("keywords", [])), **_selectors(p)},
    ),
)
EffectRegistry.register(
    # "All creatures lose all abilities" (Humility, Dress Down) — layer 6,
    # RULE 613.7f, stripping *every* ability (keywords via `_obj_keywords`,
    # triggered/activated abilities gated at fire/activate time on
    # `GameObject.loses_all_abilities`), not just a named keyword.
    "remove_all_abilities",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "all_creatures"),
        params={"lose_all_abilities": True, **_selectors(p)},
    ),
)
EffectRegistry.register(
    # "Cats you control have protection from Rats." (Hungry Lynx) /
    # "White creatures you control have protection from black." (Righteous
    # War) / "All creatures have protection from black." (Absolute Grace) /
    # "Enchanted creature has protection from the chosen color."
    # (Flickering Ward/Cho-Manno's Blessing) — layer 6, ability-adding
    # (RULE 613.7f/702.16), the *standing* sibling of the resolve-time
    # "until end of turn" grant `GameObject.temp_protections` already
    # carried (Mother of Runes). `continuous.recompute` folds the qualities
    # onto `obj._granted_protections`; `combat.is_protected_from` unions
    # them with the printed ones.
    #
    # ``protections`` is the printed quality word list, normalized to
    # `combat.protections_of_text` tokens at recompute time (the parser
    # front-end can't do it — no `game/` imports).
    # ``protection_from_chosen_color`` is the RULE 601.2b dynamic variant,
    # re-read off the source's own `chosen_color` every pass.
    #
    # Named ``_static`` to distinguish it from the pre-existing, unrelated
    # one-shot `grant_protection` above (Mother of Runes' resolve-time
    # "until end of turn" grant onto `temp_protections`) — same rule,
    # opposite duration, and `EffectRegistry.register` silently overwrites
    # a duplicate name.
    "grant_protection_static",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "attached_permanent"),
        params={
            "protections": [str(q) for q in p.get("protections", [])],
            "protection_from_chosen_color": bool(
                p.get("protection_from_chosen_color", False)
            ),
            "protection_from_chosen_type": bool(
                p.get("protection_from_chosen_type", False)
            ),
            # RULE 702.16n/p: "This effect doesn't remove this Aura." —
            # exempts the *granting* object's own attachment from RULE
            # 704.5m/n's illegal-attachment fall-off (`continuous.py`'s
            # layer-6 pass sets `GameObject._protection_self_exempt` on the
            # ability's source when this is set).
            "exempt_own_attachment": bool(p.get("exempt_own_attachment", False)),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Elves you control have '{T}: Add {B}.'" (Tyvar Kell) — layer 6,
    # ability-adding (RULE 613.7f), same layer/bucket as `grant_keyword`, just
    # granting a mana ability's production options instead of a keyword.
    # `continuous.recompute` folds these onto `obj._granted_mana`; read
    # together with the object's own printed options via
    # `mana_abilities.mana_options_for`.
    "grant_mana_ability",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "creatures_you_control"),
        params={"mana": list(p.get("mana", [])), **_selectors(p)},
    ),
)
EffectRegistry.register(
    # PAR-8: "Each [<filter>] card in your hand has cycling `<cost>`."
    # (Jo Grant/Rhet-Tomb Mystic/Tectonic Reformation) — layer 6, but its
    # targets are *hand* cards, a zone none of the battlefield `affects`
    # selectors reach; `affects` is left at its unused default ("self") and
    # `continuous._apply_hand_cycling_grants` reads ``cost``/``card_type``
    # directly off the ability instead of going through `affected_objects`.
    "grant_cycling_to_hand",
    lambda p: StaticAbility(
        "ability",
        params={
            "grant_cycling_cost": str(p["cost"]),
            "card_type": p.get("card_type"),
        },
    ),
)
EffectRegistry.register(
    # "Elves you control have '<triggered ability text>'" (Dionus, Elvish
    # Archdruid) — layer 6, ability-adding, granting a full triggered ability
    # rather than a keyword or a mana ability. ``effects`` is a list of
    # ``{"type": ..., "params": {...}}`` one-shot-effect specs, bound through
    # the same whitelisted `EffectRegistry` as everything else (docs/09
    # security boundary) — just invoked per affected object at grant time
    # (`continuous.recompute`) instead of once at bind-on-load.
    "grant_triggered_ability",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "creatures_you_control"),
        params={
            "trigger_event": p.get("trigger_event"),
            "grant_effects": list(p.get("grant_effects", [])),
            "once_per_turn": bool(p.get("once_per_turn", False)),
            "optional": bool(p.get("optional", False)),
            "controllers_turn_only": bool(p.get("controllers_turn_only", False)),
            # RULE 120.3 "deals combat damage to a player/creature" — the
            # DAMAGE event's exact-match filter (`{"combat": ..., "is_player":
            # ...}`), threaded through by `static_handlers.
            # _quoted_ability_grant_effects`; `continuous._granted_trigger_
            # condition` ANDs it the same way `effect_binder._trigger_
            # condition`'s ``"filter"`` does for an ordinary printed trigger.
            # A granted RULE 500.7 phase trigger uses the same key for its
            # own ``{"step": "upkeep"}``.
            **({"filter": dict(p["filter"])} if p.get("filter") else {}),
            # RULE 500.7 "at the beginning of *your* upkeep" granted onto
            # another permanent ("Enchanted creature has '…'", Commander's
            # Authority/Aura Flux) — "you" is the *granted-to* permanent's
            # controller, not the granting source's, so unlike
            # `effect_binder._trigger_condition`'s own `phase_relation`
            # branch (which closes over the printed source) this is resolved
            # per affected object in `continuous._granted_trigger_condition`.
            **({"phase_relation": p["phase_relation"]} if p.get("phase_relation") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Equipped creature/Enchanted land has '{cost}: <effect>.'" (Umbral
    # Mantle/Squirrel Nest-shaped) — layer 6, ability-adding, the activated
    # sibling of `grant_triggered_ability` just above. `continuous.recompute`
    # builds (and per-relationship caches) a real `ActivatedAbility` per
    # affected object onto `GameObject._granted_activated_abilities`, read
    # together with the object's own printed ones by `GameEngine.
    # can_activate`/`activate_ability`/`legal_actions`.
    "grant_activated_ability",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "attached_permanent"),
        params={
            "activated_cost": dict(p.get("cost") or {}),
            "grant_effects": list(p.get("grant_effects", [])),
            "once_per_turn": bool(p.get("once_per_turn", False)),
            "sorcery_speed_only": bool(p.get("sorcery_speed_only", False)),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Each nonland card in your graveyard has escape. The escape cost is
    # equal to the card's mana cost plus exile N other cards from your
    # graveyard." (Underworld Breach) — RULE 702.138 as a *granted* keyword
    # onto cards in a graveyard, which no battlefield selector could reach;
    # consulted by `continuous.granted_escape_for` from `GameEngine.
    # _graveyard_cast_keyword`/`_escape_cost`.
    "grant_escape",
    lambda p: StaticAbility(
        "grant_escape",
        affects="all",
        params={
            "nonland_only": bool(p.get("nonland_only", True)),
            "exile_from_graveyard": int(p.get("exile_from_graveyard", 0) or 0),
        },
    ),
)
EffectRegistry.register(
    "type_change",  # "Lands you control are 0/0 creatures" (layer 4)
    lambda p: StaticAbility(
        "type",
        affects=p.get("affects", "self"),
        params={
            "add_types": list(p.get("add_types", [])),
            # RULE 601.2b/613.4a "~ is the chosen type in addition to its
            # other types" (Adaptive Automaton/A-Thran Portal-shaped) — a
            # literal `add_subtypes` list and/or the dynamic
            # `add_subtypes_from_source` flag (reads the ability source's
            # own `chosen_type` fresh every recompute); *adds* alongside the
            # object's printed subtypes, unlike `set_subtypes` below.
            "add_subtypes": list(p.get("add_subtypes", [])),
            "add_subtypes_from_source": bool(p.get("add_subtypes_from_source", False)),
            "power": p.get("power"),
            "toughness": p.get("toughness"),
            # RULE 613.5 full subtype overwrite ("Nonbasic lands are
            # Mountains.", Magus of the Moon/Blood Moon) — unlike
            # `add_types` (only *adds*), this *replaces* the affected
            # object's subtype set (`continuous._has_subtype`), only
            # included when the spec actually sets it so an ordinary
            # "are also creatures" clause is unaffected.
            **({"set_subtypes": list(p["set_subtypes"])} if p.get("set_subtypes") else {}),
            # RULE 613.4a *past* the battlefield — "The same is true for
            # creature spells you control and creature cards you own that
            # aren't on the battlefield" (Arcane Adaptation/Leyline of
            # Transformation, ``"cards_you_own"``) / "Each creature card in
            # your graveyard has the chosen creature type…" (Ashes of the
            # Fallen, ``"your_graveyard"``). The battlefield-side `affects`
            # selector above is independent: Arcane Adaptation sets both
            # (its battlefield half *and* this), Ashes of the Fallen only
            # this. See `continuous._apply_off_battlefield_types`.
            **({"off_battlefield": str(p["off_battlefield"])} if p.get("off_battlefield") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    "cost_reduction",  # "Spells you cast cost {N} less" (RULE 601.2f)
    lambda p: StaticAbility(
        "cost",
        # ``affects="your_spells"`` (default) is self-scoped — see
        # `continuous.cost_reduction_for`'s ownership check. ``"all_spells"``
        # (Thalia, Guardian of Thraben/Thorn of Amethyst/Vryn Wingmare-shaped:
        # an unqualified "<type> spells cost {N} more to cast") isn't scoped
        # by that check at all, so it taxes/discounts *every* player's
        # matching spells, its own controller's included.
        affects=p.get("affects", "your_spells"),
        params={
            "generic": p.get("generic", 1),
            "increase": bool(p.get("increase", False)),
            # Delve/Affinity-shaped "{N} less for each <count_selector>"
            # (`affects="self"`, printed on the spell itself) — see
            # `continuous._cost_static_amount`/`self_cost_reduction_for`.
            **({"per": p["per"]} if p.get("per") else {}),
            # A card-type filter on the spell *being cast* ("noncreature
            # spells…") — `continuous._spell_type_matches`; distinct from
            # `card_type` (a *permanent*-selector filter the other static
            # families above use) since this checks the object on the stack,
            # not a battlefield selector.
            **({"spell_type": p["spell_type"]} if p.get("spell_type") else {}),
            # ``scope="activation"`` (Power Artifact-shaped "Enchanted
            # artifact's activated abilities cost {2} less to activate.") —
            # a *different* cost this same "cost" layer/StaticAbility shape
            # adjusts: an activated ability's own activation cost (RULE
            # 601.2f-adjacent) rather than a spell's cast cost, consulted by
            # `continuous.activation_cost_reduction_for`/`GameEngine.
            # _reduced_activation_mana` instead of `cost_reduction_for` (which
            # explicitly skips these). ``min_total`` is the "can't reduce the
            # mana in that cost to less than N mana" floor.
            **({"scope": p["scope"]} if p.get("scope") else {}),
            **({"min_total": p["min_total"]} if p.get("min_total") else {}),
            # "Activated abilities of Foods you control cost {1} less to
            # activate." (Sam, Loyal Attendant) — the subtype-scoped
            # ``scope="activation"`` variant `continuous.
            # activation_cost_reduction_for` reads, unlike its "attached
            # Permanent" sibling above.
            **({"subtype": p["subtype"]} if p.get("subtype") else {}),
        },
    ),
)
EffectRegistry.register(
    # "Activated abilities of artifacts can't be activated." (RULE 602,
    # Collector Ouphe/Stony Silence/Null Rod) — reuses the ordinary
    # `affects`/selector vocabulary (default "all_permanents", global) purely
    # to pick out *which* permanents' activated abilities are silenced;
    # `game/continuous.activation_prohibited` is the actual consult point
    # (`GameEngine.can_activate`), there's no P/T/type/ability layer effect
    # to fold into `continuous.recompute` here.
    "activation_prohibition",
    lambda p: StaticAbility(
        "activation_prohibition",
        affects=p.get("affects", "all_permanents"),
        params={
            # RULE 605.1a's carve-out ("…and its activated abilities can't be
            # activated **unless they're mana abilities**" — Kasmina's
            # Transmutation/Imprisoned in the Moon). Without it the
            # prohibition covers mana abilities too, which is what makes Null
            # Rod stop an artifact's "{T}: Add {C}".
            "except_mana_abilities": bool(p.get("except_mana_abilities", False)),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # RULE 508.1a/509.1b's *qualified* combat restrictions — "~ can't be
    # blocked by creatures with power 2 or less", "…except by Walls", "…by
    # more than one creature", "~ can't attack unless defending player
    # controls an Island", "~ can't attack alone". Their unqualified siblings
    # ride synthetic `grant_keyword` flags (`cant_attack`/`cant_block`/
    # `cant_be_blocked`); these carry a parameter a flag can't, so the whole
    # entry is stamped onto `GameObject.combat_restrictions` by
    # `continuous.recompute` and evaluated at *combat* time instead — see
    # `game/combat.py`'s `COMBAT_RESTRICTIONS` for the ``kind`` whitelist and
    # `GameEngine._combat_condition_met` for the ``condition`` one.
    #
    # Not a RULE 613 layer (nothing here is a characteristic), so it sits in
    # `continuous._NON_RULE_613_LAYERS` alongside `activation_prohibition`.
    "combat_restriction",
    lambda p: StaticAbility(
        "combat_restriction",
        affects=p.get("affects", "self"),
        params={
            "kind": str(p.get("kind", "")),
            **({"filter": dict(p["filter"])} if p.get("filter") else {}),
            **({"condition": dict(p["condition"])} if p.get("condition") else {}),
            **({"count": int(p["count"])} if p.get("count") is not None else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Each player can't cast more than N spells each turn." (RULE 601-area,
    # Eidolon of Rhetoric/Rule of Law/Archon of Emeria) — a flat, global cap,
    # not scoped to any particular player's spells; consulted by
    # `continuous.max_spells_per_turn` (`GameEngine.can_cast`).
    "cast_limit",
    lambda p: StaticAbility(
        "cast_limit",
        affects="all",
        params={"max_per_turn": p.get("max_per_turn", 1)},
    ),
)
EffectRegistry.register(
    # "Each opponent can't cast noncreature spells with mana value greater
    # than the number of lands that player controls." (Lavinia, Azorius
    # Renegade) — a *conditional* prohibition on a specific spell, unlike
    # `cast_limit`'s flat count; consulted by `continuous.cast_prohibited`.
    "cast_prohibition",
    lambda p: StaticAbility(
        "cast_prohibition",
        affects="all",
        params={
            "scope": p.get("scope", "opponents"),
            "noncreature": bool(p.get("noncreature", False)),
            "max_mana_value_selector": p.get("max_mana_value_selector"),
        },
    ),
)
EffectRegistry.register(
    # "Each player can't draw more than N cards each turn." (RULE 121.5-
    # adjacent, Spirit of the Labyrinth-shaped) — the draw-side mirror of
    # `cast_limit`, a flat global cap consulted by `continuous.
    # max_draws_per_turn` (`RulesEngine._single_draw`).
    "draw_limit",
    lambda p: StaticAbility(
        "draw_limit",
        affects="all",
        params={"max_per_turn": p.get("max_per_turn", 1)},
    ),
)
EffectRegistry.register(
    # "~ doesn't untap during your untap step." (RULE 502.3-adjacent, Basalt
    # Monolith/Grim Monolith/Mana Vault — self-scoped) or "Enchanted creature
    # doesn't untap during its controller's untap step." (Paralyzing Grasp —
    # ``affects="attached_permanent"``); consulted by
    # `continuous.has_no_untap_static` (`GameEngine._step_untap`).
    "no_untap",
    lambda p: StaticAbility("no_untap", affects=p.get("affects", "self"), params={}),
)
EffectRegistry.register(
    # "As long as this artifact is untapped, players can't untap more than
    # one land during their untap steps." (Winter Orb) — a flat, unscoped
    # cap consulted by `continuous.untap_cap_for_lands`/`GameEngine.
    # _step_untap`, gated live on the source's own tapped state.
    "untap_cap",
    lambda p: StaticAbility("untap_cap", affects="all_players", params={"count": p.get("count", 1)}),
)
EffectRegistry.register(
    # "You may choose not to untap ~ during your untap step." (RULE 502.1
    # self-scoped opt-out, Rubinia Soulsinger/Hivis of the Scale/The
    # Pandorica-shaped) — unlike `no_untap` (unconditional), this only
    # actually skips untapping once the controller has separately toggled
    # `GameObject.skip_untap` on (`GameEngine.set_skip_untap`, since the
    # engine has no mid-untap-step pause to ask fresh every turn — a
    # standing toggle instead); consulted by `continuous.has_no_untap_static`.
    "no_untap_optional",
    lambda p: StaticAbility("no_untap_optional", affects="self", params={}),
)
EffectRegistry.register(
    # "You may play an additional land on each of your turns." (RULE 305.2,
    # Exploration/Dryad of the Ilysian Grove/Azusa-shaped, ``count`` for
    # Azusa's "two additional lands") or, unscoped, "Each player may play an
    # additional land on each of their turns." (Rites of Flourishing/Ghirapur
    # Orrery/Storm Cauldron, ``affects="each_player"``); consulted by
    # `continuous.extra_land_plays_for` (`GameEngine.can_play_land`). The
    # one-turn, resolve-time sibling is `ExtraLandPlayEffect`/``extra_land_play``.
    "extra_land_drop",
    lambda p: StaticAbility(
        "extra_land_drop", affects=p.get("affects", "you"), params={"count": p.get("count", 1)}
    ),
)
EffectRegistry.register(
    # "You have no maximum hand size." (RULE 402.2, A-Wizard Class/Body of
    # Knowledge-shaped) or "Players have no maximum hand size." (Anvil of
    # Bogardan/Folio of Fancies, ``affects="each_player"``); consulted by
    # `continuous.has_no_maximum_hand_size` (`GameEngine._step_cleanup`). The
    # durational "…for the rest of the game"/"…until your next turn" one-shot
    # variants are a different, resolve-time-granted shape, not modeled here.
    "no_max_hand_size",
    lambda p: StaticAbility("no_max_hand_size", affects=p.get("affects", "you"), params={}),
)
EffectRegistry.register(
    # "You gain life rather than lose life from radiation." (RULE 728.1a,
    # Strong, the Brutish Thespian) — consulted by `RulesEngine.lose_life`
    # (`continuous.has_radiation_life_gain`) before applying a
    # ``cause="radiation"`` life loss, redirecting it into a life *gain* of
    # the same amount instead. A per-player permission static, the same
    # "outside the layer engine proper" treatment as `no_max_hand_size`/
    # `no_untap_optional`.
    "radiation_life_gain",
    lambda p: StaticAbility("radiation_life_gain", affects=p.get("affects", "you"), params={}),
)
EffectRegistry.register(
    # "Creatures entering don't cause abilities to trigger." (RULE 603,
    # Tocatli Honor Guard/Hushwing Gryff/Torpor Orb) — global: silences every
    # triggered ability (including the entering object's own) that would fire
    # off a matching event; consulted by `continuous.trigger_suppressed`
    # (`RulesEngine._collect_triggers`), not a `continuous.recompute` layer.
    "trigger_prohibition",
    lambda p: StaticAbility(
        "trigger_prohibition",
        affects="all",
        params={"event": p.get("event"), "subject_type": p.get("subject_type")},
    ),
)
EffectRegistry.register(
    # "Artifacts your opponents control enter tapped." (RULE 614.1, board-
    # wide — Manglehorn/Dauntless Dismantler; Archon of Emeria's "Nonbasic
    # lands…" narrows further with ``nonbasic``) — distinct from
    # `ability_catalogue.enters_tapped` (a card's own printed clause about
    # itself): this is a *different* permanent's standing effect, consulted
    # by `continuous.enters_tapped_from_static`
    # (`RulesEngine._resolve_permanent_spell`/token creation).
    "enters_tapped_static",
    lambda p: StaticAbility(
        "enters_tapped",
        affects=p.get("affects", "opponents_permanents"),
        params={**_selectors(p)},
    ),
)
EffectRegistry.register(
    "color_change",  # "Enchanted creature is black" / "All creatures are red" (layer 5)
    lambda p: StaticAbility(
        "color",
        affects=p.get("affects", "attached_permanent"),
        params={
            "colors": [str(c).upper() for c in p.get("colors", [])],
            "set": bool(p.get("set", True)),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    "control_change",  # "You control enchanted creature" (Mind Control, layer 2)
    lambda p: StaticAbility(
        "control",
        affects=p.get("affects", "attached_permanent"),
        # No explicit "controller" defaults to the effect's own source's
        # controller (continuous.recompute), which is exactly "you" for a
        # hand-authored "you control enchanted/equipped permanent" clause.
        params={"controller": p.get("controller")},
    ),
)
EffectRegistry.register(
    "pt_cda",  # "*/* creature with power/toughness equal to …" (layer 7a, RULE 604.3)
    lambda p: StaticAbility(
        "pt_cda",
        affects=p.get("affects", "self"),
        params={
            "power_count": p.get("power_count"),
            "toughness_count": p.get("toughness_count"),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    "pt_switch",  # "Switch this creature's power and toughness" (layer 7e, RULE 613.4d/701.28)
    lambda p: StaticAbility(
        "pt_switch",
        affects=p.get("affects", "self"),
        params={**_selectors(p)},
    ),
)
EffectRegistry.register(
    "win_game",  # "you win the game" (Jace, Wielder of Mysteries' -8 tail)
    lambda p: WinGameEffect(if_empty_library=bool(p.get("if_empty_library", False))),
)
EffectRegistry.register(
    "become_monarch",  # "you become the monarch" (RULE 725.1, Palace Jailer-shaped)
    lambda p: BecomeMonarchEffect(target_kind=p.get("target_kind")),
)
EffectRegistry.register(
    "take_initiative",  # "you take the initiative" (RULE 726.1)
    lambda p: TakeInitiativeEffect(target_kind=p.get("target_kind")),
)
EffectRegistry.register(
    "venture",  # "venture into the dungeon" (RULE 701.49)
    lambda p: VentureIntoTheDungeonEffect(dungeon=p.get("dungeon")),
)
EffectRegistry.register(
    # RULE 702.131a: Ascend's spell-ability form — "you get the city's
    # blessing" checked once, at resolution, against the board.
    "get_city_blessing",
    lambda p: GetCityBlessingEffect(),
)
EffectRegistry.register(
    # RULE 611 "…until <duration>" — a continuous effect created on
    # resolution, for any duration the turn-scoped ``temp_*`` fields can't
    # express (`game/durations.py`). ``static`` is the underlying static's
    # own registered ``{"type", "params"}``.
    "grant_until",
    lambda p: GrantUntilEffect(
        static=p.get("static"),
        duration=str(p.get("duration") or "end_of_turn"),
        target_kind=p.get("target_kind", "creature") if "target_kind" in p else "creature",
        optional=bool(p.get("optional", False)),
        count=int(p.get("count", 1) or 1),
        condition=p.get("condition"),
        previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    # RULE 701.37a "monstrosity N" — ``amount`` may be the ``"x"`` sentinel
    # (`RulesEngine._substitute_x`) for "{X}{X}{R}: Monstrosity X".
    "monstrosity",
    lambda p: MonstrosityEffect(amount=p.get("amount", 1)),
)
EffectRegistry.register(
    # RULE 701.46a "adapt N".
    "adapt",
    lambda p: AdaptEffect(amount=p.get("amount", 1)),
)
EffectRegistry.register(
    # RULE 701.15a "goad target creature" — ``target_kind=None`` is the
    # "goad it"/"goad that creature" pronoun form, ``selector`` the mass one.
    "goad",
    lambda p: GoadEffect(
        target_kind=p.get("target_kind", "creature") if "target_kind" in p else "creature",
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        selector=p.get("selector"),
        count_selector=p.get("count_selector"),
        referent=p.get("referent", "previous"),
        permanent=bool(p.get("permanent", False)),
    ),
)
EffectRegistry.register(
    "create_emblem",  # "you get an emblem with '<ability>'" (RULE 114.2)
    lambda p: CreateEmblemEffect(ability=p.get("ability"), target_kind=p.get("target_kind")),
)
EffectRegistry.register(
    # "Until your next turn, target player … can't cast noncreature spells."
    # (Hope of Ghirapur) — a player-scoped cast prohibition, RULE 601.3a.
    "player_cast_restriction",
    lambda p: PlayerCastRestrictionEffect(noncreature=bool(p.get("noncreature", True))),
)
EffectRegistry.register(
    # "Look at the top X cards … put up to one on top and the rest on the
    # bottom in a random order." (+ Thassa's Oracle's own RULE 104.2a win)
    "look_top_keep_one_on_top",
    lambda p: LookTopKeepOneOnTopEffect(
        count=int(p.get("count", 0) or 0),
        count_selector=p.get("count_selector"),
        win_if_count_at_least_library=bool(p.get("win_if_count_at_least_library", False)),
    ),
)


# ---------------------------------------------------------------------------
# Replacement-effect registry (RULE 614) — the binder's whitelist
# ---------------------------------------------------------------------------


def _prevent_damage_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """A damage-prevention shield (RULE 615): prevent up to ``amount`` (or all)
    damage that would be dealt to a matching target.

    ``to`` selects what it protects, read off the effect's own source:
    ``"self"`` (the source permanent), ``"controller"`` (its controller — a
    player), or ``"any"``. ``amount`` is an integer to prevent that much, or
    ``"all"`` for total prevention. Consulted through the same
    `RulesEngine.apply_replacements` path `deal_damage` already runs, so it
    needs no new plumbing.
    """
    amount = params.get("amount", "all")
    to = params.get("to", "self")
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
        description=str(params.get("description", "prevent damage")),
    )

    def replace(event: GameEvent, _context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        is_player = bool(event.get("is_player"))
        target_id = event.get("target_id")
        if to == "self":
            matches = (not is_player) and src is not None and target_id == src.instance_id
        elif to == "controller":
            matches = is_player and src is not None and target_id == src.controller_id
        else:  # "any"
            matches = True
        if not matches:
            return event
        dealt = int(event.get("amount", 0) or 0)
        prevented_to = 0 if amount == "all" else max(0, dealt - int(amount))
        if prevented_to <= 0:
            return None  # fully prevented — the event doesn't happen
        return event.copy_with(amount=prevented_to)

    effect.replacement_fn = replace
    return effect


def _prevent_damage_convert_counters_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Prevent damage to the source while it has >=1 ``remove_kind`` counter,
    remove up to that many (capped by how many it actually has), then grant
    ``grant_kind`` counters equal to however many were actually removed
    (RULE 615/616 compound shield — Bloatfly Swarm: "If damage would be dealt
    to this creature while it has a +1/+1 counter on it, prevent that
    damage, remove that many +1/+1 counters from it, then give each player a
    rad counter for each +1/+1 counter removed this way").

    "That many" ties the removed-counter count to the damage amount that
    would have been dealt (not a flat number), so this can't be expressed as
    a plain `_prevent_damage_replacement` + a separate one-shot — the removal
    and the grant both need the *actual* damage amount, known only inside
    the replacement itself. ``to`` is always ``"self"`` in practice (the
    only real card needing this protects only its own source); ``grant_
    selector`` reuses `AddPlayerCountersEffect`'s vocabulary (``"each_
    player"``/``"each_opponent"``), read live off `context.state.players`
    rather than through that effect class, since this fires mid-replacement
    (before any stack item exists to carry an `EffectSpec`).
    """
    remove_kind = str(params.get("remove_kind", "+1/+1"))
    grant_kind = str(params.get("grant_kind", "rad"))
    grant_selector = str(params.get("grant_selector", "each_player"))
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
        description=str(params.get("description", "")),
    )

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        if src is None or event.get("is_player") or event.get("target_id") != src.instance_id:
            return event
        current = src.counters.get(remove_kind, 0)
        if current <= 0:
            return event
        dealt = int(event.get("amount", 0) or 0)
        if dealt <= 0:
            return event
        removed = min(current, dealt)
        context.engine.add_counters(src, -removed, remove_kind)
        for player in context.state.players:
            if grant_selector == "each_opponent" and player.id == src.controller_id:
                continue
            context.engine.add_player_counters(player, removed, grant_kind, source=src)
        return None  # fully prevented (RULE 614.5 — the damage never happens)

    effect.replacement_fn = replace
    return effect


def _double_damage_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Multiplies damage that would be dealt (RULE 614/616), e.g. Furnace of
    Rath/Dictate of the Twin Gods ("if a source would deal damage, it deals
    double that damage instead" — unscoped), Gratuitous Violence ("a
    *creature* you control", ``creature_only``+``your_sources_only``, no
    combat restriction despite the name), or Fiery Emancipation ("a source
    you control", ``multiplier=3``).

    ``combat_only``/``your_sources_only``/``creature_only`` scope the
    effect; ``your_sources_only`` reads the *replacement's own source's*
    controller (``effect.source``, set at bind time) against the damage
    event's ``source_controller_id`` — so it needs the object it's attached
    to on the battlefield to know whose damage counts as "yours".
    ``multiplier`` defaults to 2 (every real "double" card); Fiery
    Emancipation's "triple" is the only real 3.
    """
    combat_only = bool(params.get("combat_only", False))
    your_sources_only = bool(params.get("your_sources_only", False))
    creature_only = bool(params.get("creature_only", False))
    multiplier = int(params.get("multiplier", 2))
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
        # Left empty by default so `bind_ability` falls back to the card's
        # own (German) `raw_text` for the RULE 616.1 ordering-choice label —
        # only an explicit `description` param overrides that.
        description=str(params.get("description", "")),
    )

    def replace(event: GameEvent, _context: GameContext) -> Optional[GameEvent]:
        if combat_only and not event.get("combat"):
            return event
        if creature_only and not event.get("source_is_creature"):
            return event
        if your_sources_only:
            src = effect.source
            if src is None or event.get("source_controller_id") != src.controller_id:
                return event
        dealt = int(event.get("amount", 0) or 0)
        if dealt <= 0:
            return event
        return event.copy_with(amount=dealt * multiplier)

    effect.replacement_fn = replace
    return effect


def _additional_damage_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Damage that would be dealt is increased by a flat ``amount`` instead
    (RULE 614/616), e.g. Torbran, Thane of Red Fell ("if a red source you
    control would deal damage to an opponent or a permanent an opponent
    controls, it deals that much damage plus 2 instead").

    ``your_sources_only`` mirrors `_double_damage_replacement`; ``color``
    (a single RULE 105 letter, e.g. ``"R"``) further restricts to a damage
    source whose printed `Card.color_identity` includes it — a pragmatic
    stand-in for "is that color" (color identity, not true colour, per
    docs/Reference's existing simplifications elsewhere in this engine).
    ``to_opponent_only`` restricts the *target* side ("to an opponent or a
    permanent an opponent controls") to whoever isn't this effect's own
    source's controller — the only notion of "opponent" a 2-player
    goldfish/Replay board has.

    ``colors``/``types`` (Mechanized Warfare's "a red **or** artifact
    source") generalize ``color`` to an OR-combined compound source filter:
    a source qualifies if it matches *any* listed colour (``event``'s own
    ``source_colors``, same as plain ``color``) or *any* listed type word
    (currently only ``"artifact"`` — looked up fresh off the source object's
    printed card via ``event``'s ``source_id``, since `GameEvent.DAMAGE`
    carries no type flag of its own the way it carries ``source_colors``;
    extend the word list here as a real card needs one, mirroring
    `targeting`'s own "extend as needed" precedent). A single legacy
    ``color`` is still accepted standalone (kept for existing callers/tests);
    when either ``colors`` or ``types`` is given, ``color`` is ignored.
    """
    bonus = int(params.get("amount", 0))
    your_sources_only = bool(params.get("your_sources_only", False))
    to_opponent_only = bool(params.get("to_opponent_only", False))
    colors = list(params.get("colors") or ([params["color"]] if params.get("color") else []))
    types = list(params.get("types") or [])
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _source_matches(event: GameEvent, context: GameContext) -> bool:
        if not colors and not types:
            return True
        if colors and any(c in (event.get("source_colors") or ()) for c in colors):
            return True
        if types:
            source_id = event.get("source_id")
            src_obj = context.state.find_object(source_id) if source_id is not None else None
            if src_obj is not None:
                for type_word in types:
                    if type_word == "artifact" and bool(src_obj.card.is_artifact):
                        return True
        return False

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        if your_sources_only:
            if src is None or event.get("source_controller_id") != src.controller_id:
                return event
        if to_opponent_only:
            if src is None:
                return event
            if event.get("is_player"):
                if event.get("target_id") == src.controller_id:
                    return event
            else:
                target_obj = context.state.find_object(event.get("target_id"))
                if target_obj is not None and target_obj.controller_id == src.controller_id:
                    return event
        if not _source_matches(event, context):
            return event
        dealt = int(event.get("amount", 0) or 0)
        if dealt <= 0:
            return event
        return event.copy_with(amount=dealt + bonus)

    effect.replacement_fn = replace
    return effect


def _double_counters_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Counters that would be placed are doubled instead (RULE 122/614/616),
    e.g. Doubling Season's counter clause: "if an effect would put one or
    more counters on a permanent you control, it puts twice that many
    instead" — deliberately *not* scoped by ``kind`` (omitted, every kind is
    doubled) unless ``kind`` narrows it to one (``"+1/+1"``, ``"loyalty"``, …).

    ``your_effects_only`` (Innkeeper's Talent's "if **you** would put one or
    more counters on a permanent or player, put twice that many… instead")
    is a *different* scoping axis from Doubling Season's own real wording —
    Doubling Season reads the counters' **recipient**'s controller (handled
    by whatever `condition`/binder scoping wraps this replacement, not this
    function), while this flag reads who's **causing** the placement: it
    only doubles a `RulesEngine.add_counters`/`add_player_counters` call
    that named this effect's own source as its ``source`` (via the event's
    ``source_controller_id``, mirroring `_additional_damage_replacement`'s
    ``your_sources_only``) — irrespective of whose permanent or player ends
    up with the counters, which is exactly why the same unscoped
    `EventType.COUNTER` handling below already covers "or player" for free
    once a caller (`RulesEngine.add_player_counters`) fires that event for a
    player recipient too.

    ``plus`` (default ``None``) switches from the multiplicative "twice that
    many" to the *additive* "that many plus N" shape (Hardened Scales/
    Conclave Mentor's "that many plus one +1/+1 counters", RULE 616.1);
    ``multiplier`` (default 2) is the "twice"/"triple" factor otherwise.
    ``recipient`` scopes by the counters' recipient rather than the causer:
    ``"creature_you_control"`` (Branching Evolution/Corpsejack Menace/
    Hardened Scales — a creature this effect's source controls) or
    ``"permanent_you_control"`` (Kami of Whispered Hopes — any permanent);
    read off the event's ``recipient_controller_id``/``recipient_is_
    creature`` against ``effect.source``'s controller.
    """
    kind_filter = params.get("kind")
    your_effects_only = bool(params.get("your_effects_only", False))
    plus = params.get("plus")
    multiplier = int(params.get("multiplier", 2))
    recipient = params.get("recipient")
    effect = ReplacementEffect(
        event_type=EventType.COUNTER,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def replace(event: GameEvent, _context: GameContext) -> Optional[GameEvent]:
        if kind_filter and event.get("kind") != kind_filter:
            return event
        if your_effects_only:
            src = effect.source
            if src is None or event.get("source_controller_id") != src.controller_id:
                return event
        if recipient is not None:
            src = effect.source
            if src is None or event.get("recipient_controller_id") != src.controller_id:
                return event
            if recipient == "creature_you_control" and not event.get("recipient_is_creature"):
                return event
        amount = int(event.get("amount", 0) or 0)
        if amount <= 0:
            return event
        new_amount = amount + int(plus) if plus is not None else amount * multiplier
        return event.copy_with(amount=new_amount)

    effect.replacement_fn = replace
    return effect


def _die_to_exile_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If ~ would die, exile it instead" (RULE 616.1) — redirects a
    creature's battlefield→graveyard move to exile. Modeled like
    regeneration's shield: the fn performs the exile as a side effect and
    returns ``None`` to consume the `EventType.WOULD_DIE` event, so
    `RulesEngine._move_to_graveyard` skips the graveyard move.

    ``subject`` scopes which creatures it covers, read off the event's
    ``target_id``/``controller_id`` against ``effect.source``:
    ``"self"`` (Gloomshrieker — only the source itself), ``"you_control"``
    (a creature its controller controls), ``"opponents_control"``
    (Corpseweaver Prodigy — a creature an opponent controls), or ``"any"``.
    """
    subject = params.get("subject", "self")
    effect = ReplacementEffect(
        event_type=EventType.WOULD_DIE,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        controller_id = event.get("controller_id")
        target_id = event.get("target_id")
        if subject == "self":
            matches = src is not None and target_id == getattr(src, "instance_id", None)
        elif subject == "you_control":
            matches = src is not None and controller_id == src.controller_id
        elif subject == "opponents_control":
            matches = src is not None and controller_id not in (None, src.controller_id)
        else:  # "any"
            matches = True
        if not matches:
            return event
        obj = context.state.find_object(target_id)
        if obj is None:
            return event  # already gone — let the normal path no-op
        context.engine.exile(obj)
        return None  # event consumed; the graveyard move is replaced by exile

    effect.replacement_fn = replace
    return effect


def _gain_life_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """A life gain is rewritten instead (RULE 119.3/616.1) — the *additive*
    "you gain that much life plus N instead" (Angel of Vitality, ``plus``)
    or the *multiplicative* "you gain twice that much life instead" (Boon
    Reflection/Alhammarret's Archive/Rhox Faithmender, ``multiplier``,
    default 2). Always scoped to the effect's own controller ("if **you**
    would gain life"), read off the `EventType.LIFE_GAIN` event's
    ``player_id`` against ``effect.source``'s controller — every real card
    with this clause is a permanent whose controller is the gaining player.
    """
    plus = params.get("plus")
    multiplier = int(params.get("multiplier", 2))
    effect = ReplacementEffect(
        event_type=EventType.LIFE_GAIN,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def replace(event: GameEvent, _context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        if src is None or event.get("player_id") != src.controller_id:
            return event
        amount = int(event.get("amount", 0) or 0)
        if amount <= 0:
            return event
        new_amount = amount + int(plus) if plus is not None else amount * multiplier
        return event.copy_with(amount=new_amount)

    effect.replacement_fn = replace
    return effect


def _double_tokens_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Tokens that would be created under *this effect's controller* are
    doubled instead (RULE 111.5/614/616) — Doubling Season's/Parallel
    Lives' token clause: "if an effect would create one or more tokens
    under your control, it creates twice that many instead". Unlike the
    counter clause above this *is* controller-scoped in the real text.
    """
    effect = ReplacementEffect(
        event_type=EventType.CREATE_TOKENS,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def replace(event: GameEvent, _context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        if src is None or event.get("controller_id") != src.controller_id:
            return event
        amount = int(event.get("amount", 0) or 0)
        if amount <= 0:
            return event
        return event.copy_with(amount=amount * 2)

    effect.replacement_fn = replace
    return effect


#: The named-token vocabulary `_create_one_of_each_named_token_replacement`/
#: `_additional_named_token_replacement` build from — same closed
#: Treasure/Clue/Food set `parser.oracle.catalogue.handlers._NAMED_TOKEN_
#: WORDS` trusts (`services/token_database.py`'s curated `TokenDatabase`,
#: so the extra token keeps its own real activated ability).
_NAMED_TOKEN_DISPLAY_NAMES: tuple[str, ...] = ("Clue", "Food", "Treasure")


def _create_one_of_each_named_token_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If you would create a Clue, Food, or Treasure token, instead create
    one of each." (Academy Manufactor) — the original creation goes through
    unmodified (RULE 616 doesn't need to touch ``amount`` here), and the
    *other two* named tokens are created as a side effect alongside it.

    A side-effect `context.create_token` call is itself a new CREATE_TOKENS
    event this same replacement would otherwise see again — the ``_busy``
    re-entrancy guard on the `ReplacementEffect` instance is what stops that
    from looping (a Clue's own creation, made *by* this replacement, must
    not re-trigger it a second time).
    """
    effect = ReplacementEffect(
        event_type=EventType.CREATE_TOKENS,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )
    effect._busy = False  # type: ignore[attr-defined]

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        if src is None or event.get("controller_id") != src.controller_id:
            return event
        if effect._busy:  # type: ignore[attr-defined]
            return event
        token_name = event.get("token_name")
        if token_name not in _NAMED_TOKEN_DISPLAY_NAMES:
            return event
        effect._busy = True  # type: ignore[attr-defined]
        try:
            from ..services.token_database import default_token_database

            db = default_token_database()
            for name in _NAMED_TOKEN_DISPLAY_NAMES:
                if name == token_name:
                    continue
                card = db.get_token(name)
                if card is not None:
                    context.create_token(src.controller_id, card, 1)
        finally:
            effect._busy = False  # type: ignore[attr-defined]
        return event

    effect.replacement_fn = replace
    return effect


def _additional_named_token_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If one or more tokens would be created under your control, those
    tokens plus an additional Food token are created instead." (Peregrin
    Took) — ``token_name`` (default "Food") names the extra token; every
    token creation under this effect's controller gets one more of it
    alongside, guarded by the same ``_busy`` re-entrancy flag `_create_
    one_of_each_named_token_replacement` uses (the extra token's own
    creation must not trigger *another* extra token).
    """
    extra_name = str(params.get("token_name", "Food"))
    effect = ReplacementEffect(
        event_type=EventType.CREATE_TOKENS,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )
    effect._busy = False  # type: ignore[attr-defined]

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        if src is None or event.get("controller_id") != src.controller_id:
            return event
        if effect._busy:  # type: ignore[attr-defined]
            return event
        effect._busy = True  # type: ignore[attr-defined]
        try:
            from ..services.token_database import default_token_database

            card = default_token_database().get_token(extra_name)
            if card is not None:
                context.create_token(src.controller_id, card, 1)
        finally:
            effect._busy = False  # type: ignore[attr-defined]
        return event

    effect.replacement_fn = replace
    return effect


def _win_instead_of_empty_draw_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If you would draw a card while your library has no cards in it, you
    win the game instead." (Jace, Wielder of Mysteries/Laboratory Maniac,
    RULE 104.3a-adjacent alternative win condition) — intercepts the DRAW
    event for this effect's own source's controller: if their library is
    already empty, the draw is replaced with an outright win (`RulesEngine.
    player_wins`) and cancelled (returns ``None`` — RULE 614.5, the draw
    itself never happens, so the ordinary "drew from an empty library ⇒
    loses" state-based action never gets a chance to fire either). A draw
    with cards still in the library passes through unchanged.
    """
    effect = ReplacementEffect(
        event_type=EventType.DRAW,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        controller_id = getattr(src, "controller_id", None)
        if controller_id is None or event.get("player_id") != controller_id:
            return event
        try:
            player = context.state.player_by_id(controller_id)
        except Exception:
            return event
        if player.library:
            return event
        context.engine.player_wins(player)
        return None

    effect.replacement_fn = replace
    return effect


class ReplacementRegistry:
    """Maps a whitelisted replacement-type name to a `ReplacementEffect` factory.

    The replacement analogue of `EffectRegistry` (docs/09 security boundary):
    the binder turns a ``replacement`` `AbilitySpec` into behaviour only through
    a name registered here, so nothing derived from card text becomes an
    arbitrary callable."""

    _factories: dict[str, Callable[[dict[str, Any]], ReplacementEffect]] = {}

    @classmethod
    def register(cls, name: str, factory: Callable[[dict[str, Any]], ReplacementEffect]) -> None:
        cls._factories[name] = factory

    @classmethod
    def create(cls, name: str, params: Optional[dict[str, Any]] = None) -> ReplacementEffect:
        if name not in cls._factories:
            raise ValueError(f"unknown replacement type: {name!r}")
        return cls._factories[name](params or {})

    @classmethod
    def is_registered(cls, name: str) -> bool:
        return name in cls._factories


ReplacementRegistry.register("prevent_damage", _prevent_damage_replacement)
ReplacementRegistry.register("prevent_damage_convert_counters", _prevent_damage_convert_counters_replacement)
ReplacementRegistry.register("double_damage", _double_damage_replacement)
ReplacementRegistry.register("additional_damage", _additional_damage_replacement)
ReplacementRegistry.register("double_counters", _double_counters_replacement)
ReplacementRegistry.register("gain_life_replacement", _gain_life_replacement)
ReplacementRegistry.register("die_to_exile", _die_to_exile_replacement)
ReplacementRegistry.register("double_tokens", _double_tokens_replacement)
ReplacementRegistry.register("create_one_of_each_named_token", _create_one_of_each_named_token_replacement)
ReplacementRegistry.register("additional_named_token", _additional_named_token_replacement)
ReplacementRegistry.register("win_instead_of_empty_draw", _win_instead_of_empty_draw_replacement)
