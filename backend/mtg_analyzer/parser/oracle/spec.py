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
_CLAMPED_PARAM_KEYS: tuple[str, ...] = ("amount", "count", "x", "n")

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
    """

    type: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EffectSpec":
        return cls(type=str(data["type"]), params=dict(data.get("params") or {}))


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
    #: ``triggered``: ``{"or_both": bool, "options": [[EffectSpec, ...], ...],
    #: "descriptions": [str, ...]}`` — one entry per printed mode, in
    #: printed order. ``or_both`` is RULE 700.2e ("Choose one or both —"):
    #: the engine also offers casting/resolving both modes together. When
    #: set, the ability carries no top-level ``effects`` of its own — each
    #: mode's effects only apply once that mode is chosen. A ``spell_effect``
    #: offers one cast action per mode (`game/game_engine.py`, like an MDFC's
    #: two faces); a ``triggered`` ability's mode is instead chosen as it's
    #: put on the stack (RULE 603.3), via a `trigger_mode` interactive choice
    #: (`game/rules_engine.py`'s `_place_triggers`/`resolve_trigger_mode_
    #: choice`) — the same "choice made before the target/optional choice"
    #: ordering RULE 601.2c already uses for a spell's own mode.
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

        if (
            self.ability_kind in _EFFECT_BEARING_KINDS
            and not self.effects
            and not self.modes
            and not self.additional_cost
        ):
            raise SpecValidationError(
                f"{self.ability_kind!r} ability must carry at least one effect"
            )

        if self.modes is not None:
            self._validate_modes()

        if self.additional_cost is not None:
            self._validate_additional_cost()

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
            "optional": self.optional,
            "raw_text": self.raw_text,
            "parser": self.parser.to_dict(),
        }

    def _modes_to_dict(self) -> Optional[dict[str, Any]]:
        if self.modes is None:
            return None
        return {
            "or_both": bool(self.modes.get("or_both", False)),
            "options": [[e.to_dict() for e in opt] for opt in self.modes.get("options", [])],
            "descriptions": list(self.modes.get("descriptions") or []),
        }

    @staticmethod
    def _modes_from_dict(data: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not data:
            return None
        return {
            "or_both": bool(data.get("or_both", False)),
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
            optional=bool(data.get("optional", False)),
            raw_text=str(data.get("raw_text", "")),
            parser=ParserProvenance.from_dict(data.get("parser") or {}),
        )
