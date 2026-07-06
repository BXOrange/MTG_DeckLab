"""Oracle-text → effect *front-end* (docs/09_ORACLE_EFFECT_PARSER.md).

This subpackage is the parser front-end: it turns a card's English rules
text into the `AbilitySpec` intermediate representation (pure JSON-shaped
data). It deliberately has **no `game/` imports** so it stays pure,
independently testable, and safe to run anywhere — the data it emits only
ever references whitelisted effect types by name, never executable
behaviour. Turning an `AbilitySpec` into live `GameEffect` objects is the
*back-end*'s job (`mtg_analyzer/game/effect_binder.py`).

Phase 0 ships only the IR + its validation (`spec.py`); the normalizer,
segmenter, and handler catalogue land in later phases.
"""

from .spec import (
    ALLOWED_ABILITY_KINDS,
    MAX_EFFECT_MAGNITUDE,
    AbilitySpec,
    EffectSpec,
    ParserProvenance,
    SpecValidationError,
)

__all__ = [
    "ALLOWED_ABILITY_KINDS",
    "MAX_EFFECT_MAGNITUDE",
    "AbilitySpec",
    "EffectSpec",
    "ParserProvenance",
    "SpecValidationError",
]
