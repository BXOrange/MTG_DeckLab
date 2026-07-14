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

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Optional

from ..models.events import EventType, GameEvent
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

    def destroy(self, target: "GameObject") -> None:
        self.engine.destroy(target)

    def exile(self, target: "GameObject") -> None:
        self.engine.exile(target)

    def mill(self, player: "Player", count: int = 1) -> None:
        self.engine.mill(player, count)

    def set_tapped(self, target: "GameObject", tapped: bool = True) -> None:
        self.engine.set_tapped(target, tapped)

    def attach_to_target(self, source: "GameObject", target: "GameObject") -> None:
        self.engine.attach_to_target(source, target)

    def add_counters(self, target: "GameObject", amount: int, kind: str = "+1/+1") -> None:
        self.engine.add_counters(target, amount, kind)

    def scry(self, player: "Player", count: int = 1) -> None:
        self.engine.scry(player, count)

    def recompute(self) -> None:
        """Re-derive continuous characteristics now (RULE 613) — used by an
        effect that changes derived P/T mid-resolution (a pump)."""
        from . import continuous  # function-scoped: avoid an import cycle

        continuous.recompute(self.state)

    def create_token(self, controller_id: str, token_card: Any, count: int = 1) -> None:
        self.engine.create_token(controller_id, token_card, count)

    def copy_permanent(self, controller_id: str, source: "GameObject", count: int = 1) -> None:
        self.engine.copy_permanent(controller_id, source, count)

    def make_prepared(self, obj: "GameObject") -> None:
        self.engine.make_prepared(obj)

    def become_copy(
        self,
        obj: "GameObject",
        target: "GameObject",
        add_types: Optional[list] = None,
        add_subtypes: Optional[list] = None,
    ) -> None:
        self.engine.become_copy(obj, target, add_types, add_subtypes)

    def gain_life(self, player: "Player", amount: int) -> None:
        self.engine.gain_life(player, amount)

    def request_search(
        self,
        player: "Player",
        criteria: Any = "",
        destination: str = "hand",
        count: int = 1,
        optional: bool = True,
    ) -> None:
        self.engine.request_search(player, criteria, destination, count, optional)

    def shuffle_library(self, player: "Player") -> None:
        self.engine.shuffle_library(player)

    def cascade(self, player: "Player", max_mana_value: int) -> None:
        self.engine.request_cascade(player, max_mana_value)

    def discover(self, player: "Player", max_mana_value: int) -> None:
        self.engine.request_discover(player, max_mana_value)

    def counter(self, target: Any) -> None:
        self.engine.counter_spell(target)


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

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        self.source = source

    @abstractmethod
    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        """Apply this effect to the game."""

    def can_apply(self, context: GameContext) -> bool:  # noqa: D401 - simple default
        """Whether the effect can apply right now (default: always)."""
        return True


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
        "control": 2,      # layer 2 — control-changing effects (RULE 613.2)
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
    ) -> None:
        super().__init__(source)
        self.layer = layer
        self.affects = affects
        self.params = params or {}
        self.description = description

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

    ``trigger_event`` is the `EventType` to watch. ``condition`` is an
    optional extra predicate ``(event, context) -> bool``. ``effects`` are
    the one-shot effects placed on the stack when it triggers.
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
    ) -> None:
        super().__init__(source)
        self.trigger_event = trigger_event
        self.effects = effects
        self.condition = condition
        self.optional = optional
        self.controller_id = controller_id
        self.description = description
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

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        """Resolve the triggered ability by applying each of its effects."""
        for effect in self.effects:
            if effect.source is None and self.source is not None:
                effect.source = self.source
            effect.apply(context, targets)


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
    """

    def __init__(
        self,
        effects: list[GameEffect],
        cost: Optional["ActivationCost"] = None,
        mana_cost: Optional[ManaCost] = None,
        taps_source: bool = False,
        source: Optional["GameObject"] = None,
        description: str = "",
    ) -> None:
        super().__init__(source)
        self.effects = effects
        if cost is None:
            # Back-compat: build a cost from the old mana/tap parameters.
            from .costs import ActivationCost

            cost = ActivationCost(mana=mana_cost or ManaCost(), taps_self=taps_source)
        self.cost = cost
        self.description = description

    @property
    def mana_cost(self) -> ManaCost:
        return self.cost.mana

    @property
    def taps_source(self) -> bool:
        return self.cost.taps_self

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for effect in self.effects:
            if effect.source is None and self.source is not None:
                effect.source = self.source
            effect.apply(context, targets)


# ---------------------------------------------------------------------------
# SPECIAL: Win/loss overrides (docs/07 PART 9)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Concrete one-shot effects (RULE 608 resolution bodies)
# ---------------------------------------------------------------------------


class DealDamageEffect(GameEffect):
    """Deal ``amount`` damage to a target player or creature."""

    def __init__(
        self,
        amount: int,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "any",
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.target = target
        # Damage targets "any target" by default (RULE 115.4); a card that
        # only hits creatures can narrow this to "creature".
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.deal_damage(target, self.amount, self.source)


class DrawCardEffect(GameEffect):
    """Draw ``count`` cards for the effect's controller (or a target player)."""

    def __init__(self, count: int = 1, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or (targets[0] if targets else None) or context.active_player
        context.draw(player, self.count)


class DiscardEffect(GameEffect):
    """Make a player discard ``count`` cards."""

    def __init__(self, count: int = 1, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or (targets[0] if targets else None) or context.active_player
        context.discard(player, self.count)


class DestroyEffect(GameEffect):
    """Destroy a target permanent."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.destroy(target)


class GainLifeEffect(GameEffect):
    """The effect's controller (or a target player) gains ``amount`` life."""

    def __init__(self, amount: int = 0, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or (targets[0] if targets else None) or context.active_player
        context.gain_life(player, self.amount)


class CounterSpellEffect(GameEffect):
    """Counter a target spell on the stack (RULE 701.5)."""

    def __init__(self, target: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind="spell")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.counter(target)


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

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is not None:
            player = targets[0] if targets else None
        else:
            player = context.active_player
        if player is not None:
            context.mill(player, self.count)


class ExileEffect(GameEffect):
    """Exile a target permanent (RULE 406 / 701.5a)."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.exile(target)


class TapEffect(GameEffect):
    """Tap (or untap) a target permanent — or the source itself (RULE 701.21/22).

    ``target_kind=None`` (unlike the default ``"permanent"``) makes it act on
    the effect's own source with no player choice involved — "untap it" in a
    "whenever this creature becomes tapped, untap it" trigger (Dionus, Elvish
    Archdruid), mirroring `AddCountersEffect`'s untargeted mode.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "permanent",
        untap: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.untap = untap
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None and self.target_spec is None:
            target = self.source
        if target is not None:
            context.set_tapped(target, tapped=not self.untap)


class AttachEffect(GameEffect):
    """Attach a permanent to another permanent as an Aura/Equipment-style effect."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None or self.source is None:
            return
        context.engine.attach_to_target(self.source, target)


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


class AddCountersEffect(GameEffect):
    """Put ``amount`` +1/+1 counters on a target creature — or on the source.

    Untargeted, it buffs the effect's own source (an activated "put a +1/+1
    counter on this creature"); with a ``target_kind`` it targets (RULE 122).
    """

    def __init__(
        self,
        amount: int = 1,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
        kind: str = "+1/+1",
    ) -> None:
        super().__init__(source)
        self.amount = amount
        # The counter type: "+1/+1" (default) or "-1/-1" (RULE 122). Both shift
        # net P/T the same machinery, just with opposite sign.
        self.kind = kind
        if target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.target_spec is not None:
            target = targets[0] if targets else None
        else:
            target = self.source
        if target is not None:
            context.add_counters(target, self.amount, self.kind)


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
    """

    def __init__(
        self,
        power: int = 0,
        toughness: int = 0,
        keywords: Optional[list[str]] = None,
        target_kind: Optional[str] = None,
        selector: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.power = power
        self.toughness = toughness
        self.keywords = list(keywords or [])
        self.selector = selector
        if target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind)

    def _pump_one(self, obj: "GameObject") -> None:
        obj.temp_power += self.power
        obj.temp_toughness += self.toughness
        obj.temp_keywords.update(self.keywords)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            group = group_selector_objects(context.state, controller_id, self.selector, src=self.source)
            for obj in group:
                self._pump_one(obj)
            context.recompute()
            return
        if self.target_spec is not None:
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


class CreateTokenEffect(GameEffect):
    """Create one or more token permanents (RULE 111.5 / 701.6).

    A **named** token (``token_name`` with no inline stats) is looked up in the
    curated `TokenDatabase` so it keeps its real abilities (a Treasure's mana
    ability, a Clue's sacrifice-to-draw); an **inline** token (power/toughness
    + colours + subtypes from the oracle clause) is synthesized. Either way the
    created objects are flagged tokens, so RULE 704.5d removes them the instant
    they leave the battlefield. The tokens are created under the effect's
    controller (its source's controller, else the active player).
    """

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
    ) -> None:
        super().__init__(source)
        self.count = count
        self.token_name = token_name
        self.power = power
        self.toughness = toughness
        self.colors = colors or []
        self.subtypes = subtypes or []
        self.keywords = keywords or []

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..services.token_database import default_token_database, synthesize_token_card

        card = None
        # A bare named token (no inline stats) → the curated catalogue, so it
        # keeps its printed abilities. Inline stats always synthesize.
        if self.token_name and self.power is None and self.toughness is None:
            card = default_token_database().get_token(self.token_name)
        if card is None:
            card = synthesize_token_card(
                self.token_name or (self.subtypes[0] if self.subtypes else "Token"),
                power=self.power,
                toughness=self.toughness,
                colors=self.colors,
                subtypes=self.subtypes,
                keywords=self.keywords,
            )
        controller_id = (
            self.source.controller_id if self.source is not None
            else context.active_player.id
        )
        context.create_token(controller_id, card, self.count)


class CopyPermanentEffect(GameEffect):
    """Create a token that's a copy of a target permanent (RULE 707 / 707.2).

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
        target_kind: str = "creature",
    ) -> None:
        super().__init__(source)
        self.count = count
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = (
            self.source.controller_id if self.source is not None
            else context.active_player.id
        )
        context.copy_permanent(controller_id, target, self.count)


class BecomeCopyEffect(GameEffect):
    """*This* permanent becomes a copy of a target permanent (RULE 706/707.2).

    Unlike `CopyPermanentEffect` (which creates a *new token* copy), this
    mutates the effect's own source in place — Clone/Phantasmal Image/Copy
    Artifact-style "you may have this [permanent] enter as a copy of target
    [permanent]" — while keeping the source's own instance identity, zone,
    controller, counters and attachments untouched (none of those are
    copiable characteristics, RULE 706.2).

    Modeled as an ordinary `ENTERS_BATTLEFIELD` trigger rather than the true
    RULE 614.1c/614.12 replacement-effect timing ("as ~ enters") — a known,
    documented simplification (ToDo_Backend.md), shared with the still-open
    conditional-tapland gap: there's a brief window after entering, before
    this trigger resolves, where the permanent is still legally itself.

    ``add_types``/``add_subtypes`` cover a card's own "except it's a(n) X in
    addition to its other types" clause (`Card.as_copy`).
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)
        self.add_types = list(add_types or [])
        self.add_subtypes = list(add_subtypes or [])

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None or self.source is None or target is self.source:
            return
        context.become_copy(self.source, target, self.add_types, self.add_subtypes)


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

    Because *which* card is a player choice, this doesn't move a card itself
    — it asks the engine to open a choice (`GameContext.request_search`); the
    chosen card(s) are moved to ``destination`` and the library shuffled when
    the player answers.

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
    ) -> None:
        super().__init__(source)
        self.criteria = type_restriction if type_restriction is not None else criteria
        self.destination = destination
        self.count = count
        self.optional = optional
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.request_search(
            player, self.criteria, self.destination, self.count, self.optional
        )


# ---------------------------------------------------------------------------
# Registry (docs/07 PART 4 Option C / PART 6)
# ---------------------------------------------------------------------------


class ShuffleLibraryEffect(GameEffect):
    """Shuffle the controller's (or a target player's) library (RULE 701.20)."""

    def __init__(self, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or (targets[0] if targets else None) or context.active_player
        context.shuffle_library(player)


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
    ),
)
EffectRegistry.register(
    "draw", lambda p: DrawCardEffect(count=p.get("count", 1), player=p.get("player"))
)
EffectRegistry.register(
    "discard", lambda p: DiscardEffect(count=p.get("count", 1), player=p.get("player"))
)
EffectRegistry.register(
    "destroy",
    lambda p: DestroyEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent")
    ),
)
EffectRegistry.register(
    "gain_life", lambda p: GainLifeEffect(amount=p.get("amount", 0), player=p.get("player"))
)
EffectRegistry.register("counter", lambda p: CounterSpellEffect(target=p.get("target")))
EffectRegistry.register(
    "mill", lambda p: MillEffect(count=p.get("count", 1), target_kind=p.get("target_kind"))
)
EffectRegistry.register(
    "exile",
    lambda p: ExileEffect(target=p.get("target"), target_kind=p.get("target_kind", "permanent")),
)
EffectRegistry.register(
    "tap",
    lambda p: TapEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        untap=bool(p.get("untap", False)),
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
    "become_copy",  # "You may have this enter as a copy of target permanent" (RULE 706/707)
    lambda p: BecomeCopyEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        add_types=list(p.get("add_types", [])),
        add_subtypes=list(p.get("add_subtypes", [])),
    ),
)
EffectRegistry.register(
    "add_counters",
    lambda p: AddCountersEffect(
        amount=p.get("amount", p.get("count", 1)),
        target_kind=p.get("target_kind"),
        kind=p.get("kind", "+1/+1"),
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
    ),
)
EffectRegistry.register(
    "scry", lambda p: ScryEffect(count=p.get("count", p.get("amount", 1)))
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
    ),
)
EffectRegistry.register(
    "copy_permanent",  # "Create a token that's a copy of target creature" (RULE 707)
    lambda p: CopyPermanentEffect(
        count=p.get("count", 1),
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
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
    ),
)
EffectRegistry.register("shuffle", lambda p: ShuffleLibraryEffect())
EffectRegistry.register(
    "transform", lambda p: TransformEffect(target_kind=p.get("target_kind"))
)
EffectRegistry.register("become_prepared", lambda p: BecomePreparedEffect())
EffectRegistry.register("cascade", lambda p: CascadeEffect(mana_value=p.get("mana_value")))
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
)


def _selectors(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in _SELECTOR_KEYS if p.get(k) is not None}


EffectRegistry.register(
    "anthem",  # "Creatures you control get +N/+N" (layer 7c); tribal/colour-scoped
    lambda p: StaticAbility(
        "pt_mod",
        affects=p.get("affects", "other_creatures_you_control"),
        params={"power": p.get("power", 0), "toughness": p.get("toughness", 0),
                **_selectors(p)},
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
    "grant_keyword",  # "Creatures you control have flying" (layer 6); tribal too
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "creatures_you_control"),
        params={"keywords": list(p.get("keywords", [])), **_selectors(p)},
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
            **_selectors(p),
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
            "power": p.get("power"),
            "toughness": p.get("toughness"),
        },
    ),
)
EffectRegistry.register(
    "cost_reduction",  # "Spells you cast cost {N} less" (RULE 601.2f)
    lambda p: StaticAbility(
        "cost",
        affects=p.get("affects", "your_spells"),
        params={"generic": p.get("generic", 1), "increase": bool(p.get("increase", False))},
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


def _double_damage_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Doubles damage that would be dealt (RULE 614/616), e.g. Furnace of
    Rath ("if a source would deal damage, it deals double that damage
    instead") or Gratuitous Violence (the same, but only ``combat_only``
    damage from ``your_sources_only``).

    ``combat_only``/``your_sources_only`` scope the effect; ``your_sources_
    only`` reads the *replacement's own source's* controller (``effect.
    source``, set at bind time) against the damage event's ``source_
    controller_id`` — so it needs the object it's attached to on the
    battlefield to know whose damage counts as "yours".
    """
    combat_only = bool(params.get("combat_only", False))
    your_sources_only = bool(params.get("your_sources_only", False))
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
        if your_sources_only:
            src = effect.source
            if src is None or event.get("source_controller_id") != src.controller_id:
                return event
        dealt = int(event.get("amount", 0) or 0)
        if dealt <= 0:
            return event
        return event.copy_with(amount=dealt * 2)

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
    """
    bonus = int(params.get("amount", 0))
    your_sources_only = bool(params.get("your_sources_only", False))
    color = params.get("color")
    to_opponent_only = bool(params.get("to_opponent_only", False))
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

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
        if color and color not in (event.get("source_colors") or ()):
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
    more counters on a permanent or player, it puts twice that many
    instead" — deliberately *not* scoped to permanents/players its
    controller controls (that's the real card's own text: it also doubles
    an opponent's poison counters). ``kind`` optionally restricts to one
    counter kind (``"+1/+1"``, ``"loyalty"``, …); omitted, every kind is
    doubled.
    """
    kind_filter = params.get("kind")
    effect = ReplacementEffect(
        event_type=EventType.COUNTER,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def replace(event: GameEvent, _context: GameContext) -> Optional[GameEvent]:
        if kind_filter and event.get("kind") != kind_filter:
            return event
        amount = int(event.get("amount", 0) or 0)
        if amount <= 0:
            return event
        return event.copy_with(amount=amount * 2)

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
ReplacementRegistry.register("double_damage", _double_damage_replacement)
ReplacementRegistry.register("additional_damage", _additional_damage_replacement)
ReplacementRegistry.register("double_counters", _double_counters_replacement)
ReplacementRegistry.register("double_tokens", _double_tokens_replacement)
