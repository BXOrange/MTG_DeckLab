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

from ..models.events import GameEvent
from ..models.mana_cost import ManaCost

if TYPE_CHECKING:  # avoid an import cycle with rules_engine at runtime
    from ..models.game_object import GameObject
    from ..models.game_state import GameState, StackItem
    from ..models.player import Player
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

    def gain_life(self, player: "Player", amount: int) -> None:
        self.engine.gain_life(player, amount)

    def request_search(
        self, player: "Player", type_restriction: str = "", destination: str = "hand"
    ) -> None:
        self.engine.request_search(player, type_restriction, destination)

    def counter(self, target: Any) -> None:
        self.engine.counter_spell(target)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class GameEffect(ABC):
    """Base class for all effects (docs/07 PART 2)."""

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

    def check_trigger(self, event: GameEvent, context: GameContext) -> bool:
        """RULE 603.1: does this ability trigger for ``event``?"""
        if event.type != self.trigger_event:
            return False
        if self.condition is not None and not self.condition(event, context):
            return False
        return True

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        """Resolve the triggered ability by applying each of its effects."""
        for effect in self.effects:
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

    ``mana_cost`` is the mana portion of the cost; ``taps_source`` marks
    the ``{T}`` symbol. ``effects`` go on the stack when activated.
    """

    def __init__(
        self,
        effects: list[GameEffect],
        mana_cost: Optional[ManaCost] = None,
        taps_source: bool = False,
        source: Optional["GameObject"] = None,
        description: str = "",
    ) -> None:
        super().__init__(source)
        self.effects = effects
        self.mana_cost = mana_cost or ManaCost()
        self.taps_source = taps_source
        self.description = description

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for effect in self.effects:
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

    def __init__(self, amount: int, target: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount
        self.target = target

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

    def __init__(self, target: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target = target

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

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.counter(target)


class SearchLibraryEffect(GameEffect):
    """Search the controller's library for a card of a given type (RULE 701.19).

    ``type_restriction`` is matched against the card's type line (e.g.
    "Land", "Basic Land", "Creature", "Forest"). Because *which* card is a
    player choice, this doesn't move a card itself — it asks the engine to
    open a choice (`GameContext.request_search`); the chosen card is moved
    to ``destination`` ("hand"/"battlefield") and the library shuffled when
    the player answers.
    """

    def __init__(
        self,
        type_restriction: str = "",
        destination: str = "hand",
        player: Any = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.type_restriction = type_restriction
        self.destination = destination
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or context.active_player
        context.request_search(player, self.type_restriction, self.destination)


# ---------------------------------------------------------------------------
# Registry (docs/07 PART 4 Option C / PART 6)
# ---------------------------------------------------------------------------


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
    "damage", lambda p: DealDamageEffect(amount=p.get("amount", 0), target=p.get("target"))
)
EffectRegistry.register(
    "draw", lambda p: DrawCardEffect(count=p.get("count", 1), player=p.get("player"))
)
EffectRegistry.register(
    "discard", lambda p: DiscardEffect(count=p.get("count", 1), player=p.get("player"))
)
EffectRegistry.register("destroy", lambda p: DestroyEffect(target=p.get("target")))
EffectRegistry.register(
    "gain_life", lambda p: GainLifeEffect(amount=p.get("amount", 0), player=p.get("player"))
)
EffectRegistry.register("counter", lambda p: CounterSpellEffect(target=p.get("target")))
EffectRegistry.register(
    "search",
    lambda p: SearchLibraryEffect(
        type_restriction=p.get("type", ""), destination=p.get("destination", "hand")
    ),
)
