"""`AbilitySpec` — the intermediate representation between parse and bind.

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE INTERMEDIATE
REPRESENTATION").

One parsed ability = one `AbilitySpec`: pure, JSON-serializable data that
carries *no behaviour*. It is the contract the whole parser hangs off:

* the **front-end** (later phases) produces it from oracle text,
* it is what gets cached/versioned and, above all, **validated** — it is
  the security boundary, so nothing derived from card text ever becomes
  code; an effect is named by a whitelisted string + a params dict,
* the **back-end** (`game/effect_binder.py`) turns it into `GameEffect`
  objects via the `EffectRegistry`.

This module is intentionally **pure** (no `game/` imports). It validates
*structure* and clamps numeric magnitudes; whether an effect *type* is
actually known is the binder's check, because that requires the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

#: The kinds of ability an `AbilitySpec` can describe (docs/09 IR).
#: Mirrors the effect hierarchy in game/effects.py plus "keyword".
ALLOWED_ABILITY_KINDS: frozenset[str] = frozenset(
    {"spell_effect", "triggered", "activated", "static", "replacement",
     "enter_replacement", "keyword"}
)

#: Ability kinds that resolve one or more one-shot effects (and therefore
#: must carry at least one `EffectSpec`).
_EFFECT_BEARING_KINDS: frozenset[str] = frozenset(
    {"spell_effect", "triggered", "activated", "enter_replacement"}
)

#: Hard cap on numeric effect parameters. A malformed/hostile spec must not
#: be able to wedge a game session with an absurd loop count (e.g. "draw
#: 10^9 cards"); numeric params are clamped into ``[0, MAX_EFFECT_MAGNITUDE]``
#: at validation time (docs/09 "SECURITY MODEL": clamp params).
MAX_EFFECT_MAGNITUDE: int = 10_000

#: Numeric effect params subject to clamping (includes a keyword's "n").
_CLAMPED_PARAM_KEYS: tuple[str, ...] = ("amount", "count", "x", "n", "generic")

#: `EffectSpec.condition`'s whitelisted keys — see that field's docstring.
_ALLOWED_CONDITION_KEYS: frozenset[str] = frozenset({"kicked"})

#: `AbilitySpec.conditional_flash`'s whitelisted keys — see that field's
#: docstring. A deliberately separate whitelist from `_ALLOWED_CONDITION_KEYS`
#: above: that one gates whether an already-resolving *effect* applies;
#: this one gates a *cast/activation legality* check instead (RULE 601.3a's
#: sorcery-speed timing / RULE 606.3's loyalty timing), so the two security
#: boundaries stay distinct per docs/09.
ALLOWED_CAST_CONDITION_KEYS: frozenset[str] = frozenset({"entered_this_turn"})

#: RULE 601.2f/117.3a-adjacent: "If you control a commander, you may cast
#: this spell without paying its mana cost." (Deadly Rollick/Deflecting
#: Swat/Fierce Guardianship-shaped) — a condition-gated *alternative* cost
#: (free, not just reduced), whitelisted the same way `conditional_flash`
#: gates a cast-*timing* permission; this one instead gates a cast-*cost*
#: permission, so it's its own field/whitelist (`AbilitySpec.
#: free_cast_condition`) rather than reusing that one.
ALLOWED_FREE_CAST_CONDITION_KEYS: frozenset[str] = frozenset({"control_commander"})

#: RULE 601.2b/604.3 "as an additional cost to cast this spell, <cost>." —
#: the closed vocabulary an `AbilitySpec.additional_cost` may name. Kept this
#: small (rather than reusing the free-text `ActivationCost` parser) because
#: an additional cost is recognized off a fixed template, not open cost text;
#: `game/costs.py`'s `parse_activation_cost` still does the actual charging,
#: fed this dict the same way it already accepts an `AbilitySpec.cost` dict.
_ADDITIONAL_COST_SACRIFICE_TYPES: frozenset[str] = frozenset({"creature", "artifact", "land"})


class SpecValidationError(ValueError):
    """An `AbilitySpec` was structurally invalid (fail-closed)."""


@dataclass(frozen=True)
class ParserProvenance:
    """Where a spec came from — for audit and cache invalidation (docs/09).

    Present from day one so the (future) LLM tier and human review drop in
    without a data migration. ``source`` is ``"rule:<id>"`` for a catalogue
    handler, ``"llm"`` for the model tier, or ``"manual"`` for a
    hand-authored spec (as in the Phase 0 fixtures).
    """

    version: str = "0"
    source: str = "manual"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "source": self.source, "confidence": self.confidence}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParserProvenance":
        return cls(
            version=str(data.get("version", "0")),
            source=str(data.get("source", "manual")),
            confidence=float(data.get("confidence", 1.0)),
        )


@dataclass
class EffectSpec:
    """One whitelisted effect named by ``type`` + a ``params`` dict.

    ``type``/``params`` match `EffectRegistry.create(type, params)` exactly,
    so binding is a direct lookup (e.g. ``EffectSpec("damage", {"amount": 3})``).

    ``condition`` (parallel to `AbilitySpec.modes`) gates whether this
    *specific* effect fires at resolve time, checked against runtime state
    the binder wraps in a `game.effects.ConditionalEffect` — today just
    RULE 702.33b's "if this spell was kicked, <effect>." (``{"kicked":
    True}``, checked against ``obj.kicker_count``). A whitelisted shape
    (`_ALLOWED_CONDITION_KEYS`), not an arbitrary predicate — it can only
    gate whether an already-whitelisted effect applies, never choose *which*
    effect runs, so it doesn't widen the security boundary docs/09 sets out.

    A magnitude param (``"amount"``/``"count"``) may also be the literal
    string ``"x"`` instead of an int — the same "tie this to the spell/
    ability's own announced {X}" idiom `additional_cost`'s ``pay_life: "x"``
    uses (RULE 601.2b/107.3c). ``_clamp_params`` only touches ``int``
    values, so the sentinel string passes validation untouched;
    `RulesEngine.resolve_top_of_stack`'s ``_substitute_x`` swaps it for
    `StackItem.x` immediately before the effect applies.
    """

    type: str
    params: dict[str, Any] = field(default_factory=dict)
    condition: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type, "params": dict(self.params)}
        if self.condition is not None:
            d["condition"] = dict(self.condition)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EffectSpec":
        condition = data.get("condition")
        return cls(
            type=str(data["type"]),
            params=dict(data.get("params") or {}),
            condition=dict(condition) if condition else None,
        )


@dataclass
class AbilitySpec:
    """A single ability parsed off a card, as pure data (docs/09 IR)."""

    ability_kind: str
    effects: list[EffectSpec] = field(default_factory=list)
    #: Triggered abilities: ``{"event": EventType, "condition": {...}?}``.
    trigger: Optional[dict[str, Any]] = None
    #: Activated abilities: ``{"mana": "{2}{R}", "taps_self": bool, ...}``.
    cost: Optional[dict[str, Any]] = None
    #: What the ability may target, e.g. ``{"kind": "any", "count": 1}``.
    target: Optional[dict[str, Any]] = None
    #: Keyword abilities: the parsed identity + any single parameter, e.g.
    #: ``{"name": "flying"}``, ``{"name": "annihilator", "n": 2}``,
    #: ``{"name": "kicker", "cost": "{2}{R}"}``, ``{"name": "protection",
    #: "quality": "red"}`` (docs/09 "Keyword abilities: the privileged
    #: fast-path handler class"). ``name`` is a catalogue slug (RULE 702.x).
    keyword: Optional[dict[str, Any]] = None
    #: A modal "Choose one —" block (RULE 700.2), ``spell_effect`` or
    #: ``triggered``: ``{"or_both": bool, "at_least": bool, "choose": int,
    #: "options": [[EffectSpec, ...], ...], "descriptions": [str, ...]}`` —
    #: one entry per printed mode, in printed order. ``or_both`` is RULE
    #: 700.2e ("Choose one or both —"): the engine also offers casting/
    #: resolving both modes together. ``choose`` is RULE 700.2's "choose
    #: *N* —" header (``N>=2`` — "Choose two —"/"Choose three —"; ``1`` for
    #: the ordinary "choose one" case, the default when the key is absent so
    #: old specs keep working). ``at_least`` is "Choose *N* or more —" (a
    #: *variable* count, Farewell-shaped): ``choose`` becomes a minimum
    #: rather than an exact count, and any number of modes up to every mode
    #: may be chosen — mutually exclusive with ``or_both`` (Scryfall never
    #: prints both suffixes on one header). When set, the ability carries no
    #: top-level ``effects`` of its own — each mode's effects only apply
    #: once chosen. A ``spell_effect`` offers one cast action per *legal
    #: combination* of ``choose`` modes (`game/game_engine.py`, like an
    #: MDFC's two faces — `itertools.combinations` for ``choose > 1``, every
    #: size from ``choose`` to all modes when ``at_least``); a ``triggered``
    #: ability's mode(s) are instead chosen as it's put on the stack (RULE
    #: 603.3), via an iterative `trigger_mode` interactive choice
    #: (`game/rules_engine.py`'s `_place_triggers`/`resolve_trigger_mode_
    #: choice` — one mode picked per round, already-picked ones excluded
    #: from the next offer, mirroring the existing library-search
    #: `_search_choice`/`resolve_search_choice` "pick up to N one at a time"
    #: pattern, plus a "done" option once ``choose`` are picked when
    #: ``at_least``) — the same "choice made before the target/optional
    #: choice" ordering RULE 601.2c already uses for a spell's own mode.
    modes: Optional[dict[str, Any]] = None
    #: RULE 601.2b/604.3: a spell's "as an additional cost to cast this
    #: spell, <cost>." clause — ``spell_effect`` only, a single-key dict from
    #: a small closed vocabulary: ``{"sacrifice": "creature"|"artifact"|
    #: "land"}``, ``{"discard": <count>}``, or ``{"pay_life": <N>|"x"}`` (the
    #: literal string ``"x"`` ties the payment to the spell's own announced
    #: X, RULE 601.2b). May ride on a spec that otherwise carries no effects
    #: at all — the additional-cost line is its own oracle-text line,
    #: standalone from the spell's actual effect (see
    #: `game/effect_binder.py`'s `attach_to_object`, which scans every spec
    #: for this field regardless of which one carries the "real" effects).
    additional_cost: Optional[dict[str, Any]] = None
    #: RULE 702.8b/606.3: "you may cast this spell as though it had flash if
    #: <condition>" / "you may activate this permanent's loyalty abilities
    #: any time you could cast an instant if <condition>" (The Wandering
    #: Emperor-shaped) — a single-key dict from `ALLOWED_CAST_CONDITION_KEYS`
    #: (today just ``{"entered_this_turn": True}``, RULE 606.3's "as long as
    #: ~ entered the battlefield this turn"). A deliberately separate
    #: whitelist from `EffectSpec.condition`'s (see that constant's
    #: docstring) — this one gates *cast/activation timing*
    #: (`game/condition_query.py`, checked live off the object each time),
    #: not whether a resolving effect applies. May ride on any spec
    #: regardless of ``ability_kind``, same "scan every spec, attach to the
    #: object regardless of which one carries the real effects" idiom
    #: `additional_cost` uses (`game/effect_binder.py`'s `attach_to_object`).
    conditional_flash: Optional[dict[str, Any]] = None
    #: RULE 601.2f-adjacent: "If you control a commander, you may cast this
    #: spell without paying its mana cost." — a single-key dict from
    #: `ALLOWED_FREE_CAST_CONDITION_KEYS` (today just ``{"control_commander":
    #: True}``). Checked live off the game state at cast time
    #: (`game/condition_query.py`'s `free_cast_condition_holds`), mirroring
    #: `conditional_flash`'s "may ride on any spec regardless of
    #: ``ability_kind``" idiom — the clause is its own oracle-text line,
    #: standalone from the spell's actual effect.
    free_cast_condition: Optional[dict[str, Any]] = None
    #: RULE 603.4-style per-firing marker: "whenever ~ deals combat damage
    #: to a player, exile the top card of *that player's* library. Until
    #: end of turn, you may cast that card." (Ragavan, Nimble Pilferer) —
    #: the damaged player varies per firing, which a bind-on-load
    #: `TriggeredAbility`'s one fixed effects list can't carry (see that
    #: class's docstring, `game/effects.py`), so this rides as a plain
    #: marker dict (``{"count": N}``, ``N>=1``) stamped onto the
    #: `GameObject` at bind time instead of an ordinary effect —
    #: `RulesEngine._collect_impulsive_draw_triggers` reads it fresh off
    #: the event's own source every time a DAMAGE event fires, building the
    #: per-firing `ImpulsiveDrawEffect` the same way `_collect_inherent_
    #: triggers` already does for the Monarch/Initiative combat-damage
    #: swap. Hand-authored only (`game/ability_catalogue.py`) — the
    #: oracle-text parser front-end never produces this field. May ride on
    #: any spec regardless of ``ability_kind``, same "scan every spec,
    #: attach to the object" idiom `additional_cost`/`conditional_flash` use
    #: (`game/effect_binder.py`'s `attach_to_object`).
    impulsive_draw_on_combat_damage: Optional[dict[str, Any]] = None
    #: RULE 702.88b Rebound marker: "If you cast this spell from your hand,
    #: exile it as it resolves. At the beginning of your next upkeep, you
    #: may cast this card from exile without paying its mana cost."
    #: (Ephemerate) — hand-authored only, no effects of its own, same "scan
    #: every spec, attach to the object" idiom as `impulsive_draw_on_combat_
    #: damage`. Read by `RulesEngine.cast_spell` (arms ``obj.rebound_
    #: pending`` when cast from hand) and `resolve_top_of_stack` (exiles
    #: instead of routing to the graveyard, then arms the free-cast window
    #: via `GameState.free_cast_instance_ids` — a *standing* until-end-of-
    #: that-upkeep's-turn permission rather than a forced yes/no choice at
    #: the delayed trigger's own resolution, the same simplification
    #: `exile_with_play_permission`'s impulsive-draw window already uses).
    rebound: bool = False
    #: RULE 603.7-style per-firing marker: "whenever a creature you control
    #: with a counter of ``counter_kind`` on it dies, return that card to
    #: the battlefield under your control at the beginning of the next end
    #: step." (Marchesa, the Black Rose) — the dying creature varies per
    #: firing, so this rides as a marker (mirroring `impulsive_draw_on_
    #: combat_damage`'s own per-firing shape) rather than a bind-once
    #: `TriggeredAbility`; `RulesEngine._collect_counter_death_return_
    #: triggers` reads it fresh off every `DIES` event, checking the dying
    #: object's counters (snapshotted onto the event by `_move_to_graveyard`
    #: since the object may already be gone from the battlefield by the
    #: time this runs). Hand-authored only. ``{"counter_kind": "+1/+1"}``
    #: (default) — a single optional key, no other counter kind needed yet.
    counter_death_return: Optional[dict[str, Any]] = None
    optional: bool = False  # "you may"
    raw_text: str = ""
    parser: ParserProvenance = field(default_factory=ParserProvenance)

    def validate(self) -> "AbilitySpec":
        """Structurally validate and normalize (clamp) in place; return self.

        Raises `SpecValidationError` on any structural problem (fail-closed).
        Does **not** check whether an effect *type* is registered — that is
        the binder's job, since it needs the `EffectRegistry`.
        """
        if self.ability_kind not in ALLOWED_ABILITY_KINDS:
            raise SpecValidationError(
                f"unknown ability_kind {self.ability_kind!r} "
                f"(expected one of {sorted(ALLOWED_ABILITY_KINDS)})"
            )

        for effect in self.effects:
            if not isinstance(effect, EffectSpec) or not effect.type:
                raise SpecValidationError(f"malformed effect spec: {effect!r}")
            self._clamp_params(effect.params)
            if effect.condition is not None:
                self._validate_condition(effect.condition)

        if (
            self.ability_kind in _EFFECT_BEARING_KINDS
            and not self.effects
            and not self.modes
            and not self.additional_cost
            and not self.free_cast_condition
        ):
            raise SpecValidationError(
                f"{self.ability_kind!r} ability must carry at least one effect"
            )

        if self.modes is not None:
            self._validate_modes()

        if self.additional_cost is not None:
            self._validate_additional_cost()

        if self.conditional_flash is not None:
            self._validate_conditional_flash()

        if self.free_cast_condition is not None:
            self._validate_free_cast_condition()

        if self.impulsive_draw_on_combat_damage is not None:
            self._validate_impulsive_draw_on_combat_damage()

        if not isinstance(self.rebound, bool):
            raise SpecValidationError("'rebound' must be a bool")

        if self.counter_death_return is not None:
            self._validate_counter_death_return()

        if self.ability_kind == "triggered":
            if not self.trigger or "event" not in self.trigger:
                raise SpecValidationError("triggered ability needs a trigger with an 'event'")

        if self.keyword is not None:
            if not isinstance(self.keyword, dict) or not self.keyword.get("name"):
                raise SpecValidationError("keyword spec needs a non-empty 'name'")
            self._clamp_params(self.keyword)  # clamp an integer "n" the same way

        return self

    def _validate_modes(self) -> None:
        """Structural check for a modal ``modes`` block (RULE 700.2)."""
        if self.ability_kind not in ("spell_effect", "triggered"):
            raise SpecValidationError(
                "'modes' is only supported on spell_effect/triggered abilities"
            )
        if not isinstance(self.modes, dict):
            raise SpecValidationError("'modes' must be a dict")
        options = self.modes.get("options")
        if not isinstance(options, list) or len(options) < 2:
            raise SpecValidationError("'modes' needs at least two options")
        for option in options:
            if not isinstance(option, list) or not option:
                raise SpecValidationError("each mode needs at least one effect")
            for effect in option:
                if not isinstance(effect, EffectSpec) or not effect.type:
                    raise SpecValidationError(f"malformed effect spec in mode: {effect!r}")
                self._clamp_params(effect.params)
        descriptions = self.modes.get("descriptions")
        if descriptions is not None and (
            not isinstance(descriptions, list) or len(descriptions) != len(options)
        ):
            raise SpecValidationError("'modes' descriptions must match its options 1:1")
        choose = self.modes.get("choose", 1)
        if isinstance(choose, bool) or not isinstance(choose, int) or not 1 <= choose <= len(options):
            raise SpecValidationError(
                f"'modes' choose count must be an int in [1, {len(options)}]"
            )
        if self.modes.get("or_both") and self.modes.get("at_least"):
            raise SpecValidationError("'modes' or_both and at_least are mutually exclusive")

    def _validate_additional_cost(self) -> None:
        """Structural check for an ``additional_cost`` clause (RULE 601.2b/604.3)."""
        if self.ability_kind != "spell_effect":
            raise SpecValidationError(
                "'additional_cost' is only supported on spell_effect abilities"
            )
        cost = self.additional_cost
        if not isinstance(cost, dict) or len(cost) != 1:
            raise SpecValidationError("'additional_cost' must be a single-key dict")
        key, value = next(iter(cost.items()))
        if key == "sacrifice":
            if value not in _ADDITIONAL_COST_SACRIFICE_TYPES:
                raise SpecValidationError(
                    f"unsupported additional_cost sacrifice type {value!r}"
                )
        elif key == "discard":
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SpecValidationError("'additional_cost' discard count must be a positive int")
        elif key == "pay_life":
            valid_int = isinstance(value, int) and not isinstance(value, bool) and value > 0
            if value != "x" and not valid_int:
                raise SpecValidationError(
                    "'additional_cost' pay_life must be a positive int or 'x'"
                )
        else:
            raise SpecValidationError(f"unknown additional_cost kind {key!r}")

    def _validate_conditional_flash(self) -> None:
        """Structural check for a ``conditional_flash`` clause."""
        cond = self.conditional_flash
        if not isinstance(cond, dict) or len(cond) != 1:
            raise SpecValidationError("'conditional_flash' must be a single-key dict")
        key, value = next(iter(cond.items()))
        if key not in ALLOWED_CAST_CONDITION_KEYS:
            raise SpecValidationError(f"unknown conditional_flash key {key!r}")
        if key == "entered_this_turn" and not isinstance(value, bool):
            raise SpecValidationError("'entered_this_turn' condition must be a bool")

    def _validate_impulsive_draw_on_combat_damage(self) -> None:
        """Structural check for an ``impulsive_draw_on_combat_damage`` marker."""
        spec = self.impulsive_draw_on_combat_damage
        if not isinstance(spec, dict):
            raise SpecValidationError("'impulsive_draw_on_combat_damage' must be a dict")
        count = spec.get("count", 1)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_EFFECT_MAGNITUDE:
            raise SpecValidationError(
                "'impulsive_draw_on_combat_damage' count must be an int in "
                f"[1, {MAX_EFFECT_MAGNITUDE}]"
            )

    def _validate_counter_death_return(self) -> None:
        """Structural check for a ``counter_death_return`` marker."""
        spec = self.counter_death_return
        if not isinstance(spec, dict):
            raise SpecValidationError("'counter_death_return' must be a dict")
        kind = spec.get("counter_kind", "+1/+1")
        if not isinstance(kind, str) or not kind:
            raise SpecValidationError("'counter_death_return' counter_kind must be a non-empty str")

    def _validate_free_cast_condition(self) -> None:
        """Structural check for a ``free_cast_condition`` clause."""
        cond = self.free_cast_condition
        if not isinstance(cond, dict) or len(cond) != 1:
            raise SpecValidationError("'free_cast_condition' must be a single-key dict")
        key, value = next(iter(cond.items()))
        if key not in ALLOWED_FREE_CAST_CONDITION_KEYS:
            raise SpecValidationError(f"unknown free_cast_condition key {key!r}")
        if key == "control_commander" and not isinstance(value, bool):
            raise SpecValidationError("'control_commander' condition must be a bool")

    @staticmethod
    def _validate_condition(condition: dict[str, Any]) -> None:
        """Structural check for an `EffectSpec.condition` (RULE 702.33b's
        kicked-gate, so far the only member)."""
        if not isinstance(condition, dict) or not condition:
            raise SpecValidationError(f"malformed effect condition: {condition!r}")
        for key, value in condition.items():
            if key not in _ALLOWED_CONDITION_KEYS:
                raise SpecValidationError(f"unknown effect condition key {key!r}")
            if key == "kicked" and not isinstance(value, bool):
                raise SpecValidationError("'kicked' condition must be a bool")

    @staticmethod
    def _clamp_params(params: dict[str, Any]) -> None:
        for key in _CLAMPED_PARAM_KEYS:
            value = params.get(key)
            if isinstance(value, bool):  # bool is an int subclass — leave flags alone
                continue
            if isinstance(value, int):
                params[key] = max(0, min(value, MAX_EFFECT_MAGNITUDE))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ability_kind": self.ability_kind,
            "effects": [e.to_dict() for e in self.effects],
            "trigger": self.trigger,
            "cost": self.cost,
            "target": self.target,
            "keyword": self.keyword,
            "modes": self._modes_to_dict(),
            "additional_cost": self.additional_cost,
            "conditional_flash": self.conditional_flash,
            "free_cast_condition": self.free_cast_condition,
            "optional": self.optional,
            "raw_text": self.raw_text,
            "parser": self.parser.to_dict(),
        }

    def _modes_to_dict(self) -> Optional[dict[str, Any]]:
        if self.modes is None:
            return None
        return {
            "or_both": bool(self.modes.get("or_both", False)),
            "at_least": bool(self.modes.get("at_least", False)),
            "choose": int(self.modes.get("choose", 1)),
            "options": [[e.to_dict() for e in opt] for opt in self.modes.get("options", [])],
            "descriptions": list(self.modes.get("descriptions") or []),
        }

    @staticmethod
    def _modes_from_dict(data: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not data:
            return None
        return {
            "or_both": bool(data.get("or_both", False)),
            "at_least": bool(data.get("at_least", False)),
            "choose": int(data.get("choose", 1)),
            "options": [
                [EffectSpec.from_dict(e) for e in opt] for opt in (data.get("options") or [])
            ],
            "descriptions": list(data.get("descriptions") or []),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AbilitySpec":
        return cls(
            ability_kind=str(data["ability_kind"]),
            effects=[EffectSpec.from_dict(e) for e in (data.get("effects") or [])],
            trigger=data.get("trigger"),
            cost=data.get("cost"),
            target=data.get("target"),
            keyword=data.get("keyword"),
            modes=cls._modes_from_dict(data.get("modes")),
            additional_cost=data.get("additional_cost"),
            conditional_flash=data.get("conditional_flash"),
            free_cast_condition=data.get("free_cast_condition"),
            optional=bool(data.get("optional", False)),
            raw_text=str(data.get("raw_text", "")),
            parser=ParserProvenance.from_dict(data.get("parser") or {}),
        )
