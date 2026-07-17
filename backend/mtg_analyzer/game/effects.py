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

    def destroy(self, target: "GameObject", can_be_regenerated: bool = True) -> None:
        self.engine.destroy(target, can_be_regenerated=can_be_regenerated)

    def regenerate(self, target: "GameObject") -> None:
        self.engine.regenerate(target)

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

    def surveil(self, player: "Player", count: int = 1) -> None:
        self.engine.surveil(player, count)

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

    def lose_life(self, player: "Player", amount: int) -> None:
        self.engine.lose_life(player, amount, cause="effect")

    def sacrifice(self, player: "Player", what: str = "permanent", count: int = 1) -> None:
        self.engine.sacrifice(player, what, count)

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
        self, target: "GameObject", destination: str = "battlefield", controller_id: Optional[str] = None
    ) -> None:
        self.engine.return_from_graveyard(target, destination, controller_id=controller_id)

    def add_mana(self, player: "Player", color: str, amount: int = 1) -> None:
        self.engine.add_mana(player, color, amount)

    def add_mana_any_color(self, player: "Player") -> None:
        self.engine.add_mana_any_color(player)


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
    ``None`` if ``source`` isn't a live, currently-attacking object (e.g. a
    hand-built test event with no real attack declared).
    """
    spec = getattr(source, "combat_defender", None)
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

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        self.source = source

    @abstractmethod
    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        """Apply this effect to the game."""

    def can_apply(self, context: GameContext) -> bool:  # noqa: D401 - simple default
        """Whether the effect can apply right now (default: always)."""
        return True


def _apply_effects_partitioned(
    effects: list["GameEffect"],
    context: GameContext,
    targets: Optional[list[Any]],
    target_groups: Optional[list[list[Any]]],
    source: Optional["GameObject"] = None,
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
    """
    group_index = 0
    for effect in effects:
        if source is not None and effect.source is None:
            effect.source = source
        if target_groups is not None and effect.target_spec is not None:
            group = target_groups[group_index] if group_index < len(target_groups) else []
            group_index += 1
            effect.apply(context, group)
        else:
            effect.apply(context, targets)


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
    ) -> None:
        super().__init__(source)
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
    """

    def __init__(
        self,
        look: bool = False,
        play_lands: bool = False,
        cast_spells: bool = False,
        min_mana_value: Optional[int] = None,
        requires_attached: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.look = look
        self.play_lands = play_lands
        self.cast_spells = cast_spells
        self.min_mana_value = min_mana_value
        self.requires_attached = requires_attached

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        return None  # continuous marker — consulted by top_library.py, not applied


# ---------------------------------------------------------------------------
# SPECIAL: Conditional effect wrapper (parser/oracle/spec.py's EffectSpec.condition)
# ---------------------------------------------------------------------------


class ConditionalEffect(GameEffect):
    """Gates ``inner`` so it only applies when ``condition`` holds (RULE
    702.33b's "if this spell was kicked, <effect>." — a *second, additional*
    effect on the same spell/ability, not a replacement of an earlier one;
    see `parser.oracle.spec.EffectSpec.condition`'s docstring for why "if
    kicked, ... instead" — overriding an *existing* effect's own amount —
    is a different, unmodeled shape).

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

    def _condition_holds(self) -> bool:
        kicked = self.condition.get("kicked")
        if kicked is not None:
            count = getattr(self.source, "kicker_count", 0) or 0
            return (count > 0) if kicked else (count == 0)
        return True

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.inner.source is None:
            self.inner.source = self.source
        if self._condition_holds():
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
    {"each_creature", "each_player", "each_opponent", "each_creature_and_player", "defending_player"}
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
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.target = target
        self.selector = selector if selector in _DAMAGE_SELECTORS else None
        if self.selector is None:
            # Damage targets "any target" by default (RULE 115.4); a card
            # that only hits creatures can narrow this to "creature".
            # ``optional`` is RULE 115.1a "up to one/N target(s)" — fewer
            # than ``count`` (including zero) is then a legal choice, so
            # casting is never locked on it. ``count`` > 1 is "to each of
            # up to N target X" (Volcanic Salvo-shaped) — the full amount
            # applies to *every* chosen target, not divided among them.
            self.target_spec = TargetSpec(kind=target_kind, optional=optional, count=count)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            self._apply_selector(context)
            return
        # Only this effect's own ``count`` targets, taken off the *front* of
        # a (possibly longer) shared targets list — see `TargetSpec.count`'s
        # docstring: a stack item's targets list is shared by every effect
        # on it, so a single-target effect (count=1, the default) must not
        # swallow entries meant for something else sharing the same cast.
        chosen = (
            targets[: self.target_spec.count] if targets
            else ([self.target] if self.target is not None else [])
        )
        for target in chosen:
            context.deal_damage(target, self.amount, self.source)

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
        if self.selector in ("each_creature", "each_creature_and_player"):
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            for obj in group_selector_objects(context.state, None, "all_creatures"):
                context.deal_damage(obj, self.amount, self.source)
            if self.selector == "each_creature":
                return
        controller_id = getattr(self.source, "controller_id", None)
        for player in context.state.living_players():
            if self.selector == "each_opponent" and player.id == controller_id:
                continue
            context.deal_damage(player, self.amount, self.source)


#: `DrawCardEffect`'s ``count_selector`` vocabulary — a per-object dynamic
#: draw count (RULE 601.2c-style variable amount), the same "count instead
#: of a flat number" shape `continuous._pt_mod_count` uses for a per-count
#: anthem. Only one shape needed so far: Wyleth, Soul of Steel's "draw a
#: card for each Aura and Equipment attached to it".
_DRAW_COUNT_SELECTORS: frozenset[str] = frozenset({"auras_and_equipment_attached_to_self"})


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
    Equipment attached to it")."""

    def __init__(
        self,
        count: int = 1,
        player: Any = None,
        source: Optional["GameObject"] = None,
        count_selector: Optional[str] = None,
        target_kind: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.player = player
        self.count_selector = count_selector if count_selector in _DRAW_COUNT_SELECTORS else None
        # "Target player draws N cards" (Sign in Blood-shaped) — a genuine
        # RULE 115 target, unlike the untargeted default (most draw effects
        # just draw for their own controller).
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or (targets[0] if targets else None) or context.active_player
        count = self.count
        if self.count_selector == "auras_and_equipment_attached_to_self":
            count = _attached_auras_and_equipment_count(context, self.source)
        context.draw(player, count)


class DiscardEffect(GameEffect):
    """Make a player discard ``count`` cards."""

    def __init__(self, count: int = 1, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or (targets[0] if targets else None) or context.active_player
        context.discard(player, self.count)


#: RULE 601.2c mass "destroy/exile all X" selectors (Wrath of God/Citywide
#: Bust/Farewell-shaped board wipes) — untargeted, unlike every RULE 115
#: target form above, so `DestroyEffect`/`ExileEffect` skip `target_spec`
#: entirely when one of these is set, mirroring `DealDamageEffect.selector`.
_MASS_DESTROY_SELECTORS: frozenset[str] = frozenset(
    {"all_creatures", "all_artifacts", "all_enchantments", "all_permanents", "all_planeswalkers"}
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
    battlefield = context.state.battlefield
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
    return result


class DestroyEffect(GameEffect):
    """Destroy a target permanent — or, with ``count`` > 1, every one of a
    fixed/"up to N" set of chosen target permanents (RULE 115.1a
    generalized to N>=2 — "destroy two target creatures"/"destroy up to two
    target artifacts and/or enchantments") — or, with ``selector`` set, a
    mass "destroy all X [with condition]" board wipe (RULE 601.2c, untargeted,
    same shape as `DealDamageEffect.selector`). ``can_be_regenerated=False``
    is Wrath of God's "They can't be regenerated." tail.
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
    ) -> None:
        super().__init__(source)
        self.target = target
        self.selector = selector if selector in _MASS_DESTROY_SELECTORS else None
        self.filter = filter
        self.can_be_regenerated = can_be_regenerated
        if self.selector is None:
            self.target_spec = TargetSpec(kind=target_kind, optional=optional, count=count)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            for obj in _mass_selector_objects(context, self.selector, self.filter):
                context.destroy(obj, can_be_regenerated=self.can_be_regenerated)
            return
        # See `DealDamageEffect.apply`'s comment: only this effect's own
        # ``count`` targets, off the front of a possibly-shared list.
        chosen = (
            targets[: self.target_spec.count] if targets
            else ([self.target] if self.target is not None else [])
        )
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
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None and self.target_spec is None:
            target = self.source
        if target is not None:
            context.regenerate(target)


class GainLifeEffect(GameEffect):
    """The effect's controller (or an explicitly given ``player``) gains
    ``amount`` life — untargeted (no parser handler currently emits a
    genuinely-targeted "target player gains N life"; ``player`` is for a
    hand-authored/direct construction only).

    Deliberately does **not** fall back to a shared ``targets`` list the
    way `DealDamageEffect`/`DestroyEffect` do: this effect never declares
    its own `target_spec`, so any ``targets`` passed to `apply` belong to
    a *different* effect on the same ability/spell (e.g. Deathrite
    Shaman's "Exile target creature card from a graveyard. You gain 2
    life." — the exiled card, not a player) — reading `targets[0]` here
    would silently hand `RulesEngine.gain_life` a `GameObject` instead of
    a `Player`.
    """

    def __init__(self, amount: int = 0, player: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.amount = amount
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or _controller_of(self.source, context)
        context.gain_life(player, self.amount)


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
    ) -> None:
        super().__init__(source)
        self.amount = amount
        self.player = player
        self.selector = selector
        # "Target player … loses 2 life" (Sign in Blood-shaped, sharing its
        # target with a sibling `DrawCardEffect` on the same spell) — opt-in
        # only, so every existing untargeted/selector caller keeps reading
        # no shared ``targets`` list at all (see the class docstring).
        self.target_spec = TargetSpec(kind=target_kind) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector in _LOSE_LIFE_SELECTORS:
            controller_id = getattr(self.source, "controller_id", None)
            for p in context.state.living_players():
                if self.selector == "each_opponent" and p.id == controller_id:
                    continue
                context.lose_life(p, self.amount)
            return
        player = self.player
        if player is None and self.target_spec is not None:
            player = targets[0] if targets else None
        if player is None and self.selector == "defending_player":
            player = _defending_player_of(self.source, context)
        if player is None:
            player = _controller_of(self.source, context)
        context.lose_life(player, self.amount)


class SacrificeEffect(GameEffect):
    """A player sacrifices up to ``count`` permanents matching ``what``
    (RULE 701.17) — untargeted, an MVP auto-choice matching
    `GameEngine._sacrifice_candidate`'s non-interactive convention (an
    interactive picker is a future upgrade, not modeled here).

    ``selector="defending_player"`` (annihilator, RULE 702.86) resolves the
    player dynamically at apply-time, the same way `LoseLifeEffect` does.
    """

    def __init__(
        self,
        count: int = 1,
        what: str = "permanent",
        player: Any = None,
        selector: Optional[str] = None,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.count = count
        self.what = what
        self.player = player
        self.selector = selector

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self.player or (targets[0] if targets else None)
        if player is None and self.selector == "defending_player":
            player = _defending_player_of(self.source, context)
        if player is None:
            return
        context.sacrifice(player, self.what, self.count)


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
        self.target_spec = TargetSpec(kind="spell", spell_filter=spell_filter or None)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.counter(target, unless_pays=self.unless_pays, source=self.source)


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
    `DestroyEffect.selector` uses."""

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        optional: bool = False,
        count: int = 1,
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.selector = selector if selector in _MASS_DESTROY_SELECTORS else None
        self.filter = filter
        if self.selector is None:
            self.target_spec = TargetSpec(kind=target_kind, optional=optional, count=count)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector is not None:
            for obj in _mass_selector_objects(context, self.selector, self.filter):
                context.exile(obj)
            return
        # See `DealDamageEffect.apply`'s comment: only this effect's own
        # ``count`` targets, off the front of a possibly-shared list.
        chosen = (
            targets[: self.target_spec.count] if targets
            else ([self.target] if self.target is not None else [])
        )
        for target in chosen:
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
            context.add_counters(self.source, 1, "+1/+1")


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
        context.add_counters(target, 1, "+1/+1")
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
    `targeting.legal_targets`.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent",
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
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

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "graveyard_creature",
        destination: str = "battlefield",
        under_your_control: bool = False,
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.destination = destination if destination in ("battlefield", "hand") else "battlefield"
        self.under_your_control = under_your_control
        self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        controller_id = None
        if self.under_your_control and self.destination == "battlefield":
            player = _controller_of(self.source, context)
            controller_id = player.id if player is not None else None
        context.return_from_graveyard(target, self.destination, controller_id=controller_id)


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

    def __init__(self, colors: Optional[list[str]] = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.colors = [str(c).upper() for c in (colors or [])]

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        for color in self.colors:
            if color == "ANY":
                context.add_mana_any_color(player)
            else:
                context.add_mana(player, color)


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
        optional: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        self.untap = untap
        self.target_spec = TargetSpec(kind=target_kind, optional=optional) if target_kind is not None else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None and self.target_spec is None:
            target = self.source
        if target is not None:
            context.set_tapped(target, tapped=not self.untap)


class UnblockableEffect(GameEffect):
    """"Target creature can't be blocked this turn" (Rogue's Passage) — sets
    `GameObject.temp_unblockable`, read directly by `GameEngine.can_block`
    and cleared at cleanup (RULE 514.2)."""

    def __init__(
        self, target: Any = None, source: Optional["GameObject"] = None, target_kind: str = "creature"
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            target.temp_unblockable = True


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
    counter on this creature"); with a ``target_kind`` it targets (RULE 122),
    optionally as an RULE 115.1a "up to one" pick. ``selector=
    "each_creature_you_control"`` (RULE 601.2c, Vastwood Surge's "put two
    +1/+1 counters on each creature you control") is instead a mass,
    untargeted effect over the group `continuous.group_selector_objects`
    already resolves for pump/anthem clauses — mirrors `DealDamageEffect.
    selector`'s "no `target_spec` at all" shape.
    """

    def __init__(
        self,
        amount: int = 1,
        target_kind: Optional[str] = None,
        source: Optional["GameObject"] = None,
        kind: str = "+1/+1",
        optional: bool = False,
        selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.amount = amount
        # The counter type: "+1/+1" (default) or "-1/-1" (RULE 122). Both shift
        # net P/T the same machinery, just with opposite sign.
        self.kind = kind
        self.selector = selector if selector == "each_creature_you_control" else None
        if self.selector is None and target_kind is not None:
            self.target_spec = TargetSpec(kind=target_kind, optional=optional)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.selector == "each_creature_you_control":
            from .continuous import group_selector_objects  # avoid the continuous↔effects cycle

            controller_id = getattr(self.source, "controller_id", None)
            for obj in group_selector_objects(context.state, controller_id, "creatures_you_control"):
                context.add_counters(obj, self.amount, self.kind)
            return
        if self.target_spec is not None:
            target = targets[0] if targets else None
        else:
            target = self.source
        if target is not None:
            context.add_counters(target, self.amount, self.kind)


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
        context.add_counters(self.source, self.amount, "+1/+1")
        self.source.renowned = True
        context.fire_event(GameEvent(EventType.RENOWNED, instance_id=self.source.instance_id))


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
    picker exists yet) — auto-applies to *every* permanent that already
    carries at least one counter, the same "auto-choose, no chooser in MVP"
    simplification `SacrificeEffect`/`GameEngine._sacrifice_candidate` use
    elsewhere. Player-level counters (poison/energy/experience) aren't
    proliferated: `RulesEngine.add_counters` only operates on a `GameObject`
    today (`Player` has no matching primitive) — a documented gap, not
    silently wrong (no card in this pool needs it yet).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for obj in list(context.state.battlefield):
            for kind in list(obj.counters.keys()):
                if obj.counters.get(kind, 0) > 0:
                    context.add_counters(obj, 1, kind)


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


class SurveilEffect(GameEffect):
    """Surveil ``count`` for the effect's controller (RULE 701.31)."""

    def __init__(self, count: int = 1, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is not None:
            context.surveil(player, self.count)


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
    ) -> None:
        super().__init__(source)
        self.count = count
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
        context.copy_permanent(controller_id, target, self.count)


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
        selector=p.get("selector"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
    ),
)
EffectRegistry.register(
    "draw",
    lambda p: DrawCardEffect(
        count=p.get("count", 1), player=p.get("player"), count_selector=p.get("count_selector"),
        target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    "discard", lambda p: DiscardEffect(count=p.get("count", 1), player=p.get("player"))
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
    ),
)
EffectRegistry.register(
    "regenerate",
    lambda p: RegenerateEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature")
    ),
)
EffectRegistry.register(
    "gain_life", lambda p: GainLifeEffect(amount=p.get("amount", 0), player=p.get("player"))
)
EffectRegistry.register(
    "lose_life",
    lambda p: LoseLifeEffect(
        amount=p.get("amount", 0), player=p.get("player"), selector=p.get("selector"),
        target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    "counter",
    lambda p: CounterSpellEffect(
        target=p.get("target"),
        unless_pays=p.get("unless_pays"),
        noncreature=bool(p.get("noncreature", False)),
        card_types=p.get("card_types"),
        mana_value=p.get("mana_value"),
    ),
)
EffectRegistry.register("cant_be_countered", lambda p: CantBeCounteredEffect())
EffectRegistry.register(
    "mill", lambda p: MillEffect(count=p.get("count", 1), target_kind=p.get("target_kind"))
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
    ),
)
EffectRegistry.register(
    "add_mana",  # a spell's own bare "Add {B}{B}{B}." body (RULE 106.4, Dark Ritual)
    lambda p: AddManaEffect(colors=list(p.get("colors", []))),
)
EffectRegistry.register(
    "tap",
    lambda p: TapEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        untap=bool(p.get("untap", False)),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    "unblockable",  # "Target creature can't be blocked this turn" (Rogue's Passage)
    lambda p: UnblockableEffect(target=p.get("target"), target_kind=p.get("target_kind", "creature")),
)
EffectRegistry.register(
    "attach",
    lambda p: AttachEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
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
    "enter_as_copy",  # "You may have this enter as a copy of target X" (RULE 614.1c/614.12)
    lambda p: EnterAsCopyReplacement(
        target_kind=p.get("target_kind", "permanent"),
        add_types=list(p.get("add_types", [])),
        add_subtypes=list(p.get("add_subtypes", [])),
        optional=bool(p.get("optional", True)),
    ),
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
    "surveil", lambda p: SurveilEffect(count=p.get("count", p.get("amount", 1)))
)
EffectRegistry.register(
    "top_library_permission",
    lambda p: TopLibraryPermissionEffect(
        look=p.get("look", False),
        play_lands=p.get("play_lands", False),
        cast_spells=p.get("cast_spells", False),
        min_mana_value=p.get("min_mana_value"),
        requires_attached=p.get("requires_attached", False),
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
EffectRegistry.register("proliferate", lambda p: ProliferateEffect())
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
