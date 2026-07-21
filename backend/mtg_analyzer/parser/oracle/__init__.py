"""Oracle-text → effect *front-end* (docs/concepts/09_ORACLE_EFFECT_PARSER.md).

This subpackage is the parser front-end: it turns a card's English rules
text into the `AbilitySpec` intermediate representation (pure JSON-shaped
data). It deliberately has **no `game/` imports** so it stays pure,
independently testable, and safe to run anywhere — the data it emits only
ever references whitelisted effect types by name, never executable
behaviour. Turning an `AbilitySpec` into live `GameEffect` objects is the
*back-end*'s job (`mtg_analyzer/game/effect_binder.py`).

Phase 0 shipped the IR + its validation (`spec.py`) and the keyword catalogue
(`catalogue/keywords.py`). Phase 1 is in: `normalize` → `segmenter` →
`catalogue/handlers` (the effect-family table over shared `catalogue/subgrammars`)
→ `gate`, tied together by `parse_oracle`, which turns a card's oracle text
into `AbilitySpec`s with a fail-closed `MODELED`/`UNMODELED` coverage verdict
(plus `NEVER_SUPPORTED` for permanent non-goals like Stickers, RULE 123).
"""

from .gate import MODELED, NEVER_SUPPORTED, PARSER_VERSION, UNMODELED, ParseResult, parse_oracle
from .processing_list import (
    CoverageReport,
    TemplateEntry,
    abstract_clause,
    coverage_over_cards,
    coverage_report,
)
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
    "ParseResult",
    "parse_oracle",
    "MODELED",
    "UNMODELED",
    "NEVER_SUPPORTED",
    "PARSER_VERSION",
    "CoverageReport",
    "TemplateEntry",
    "abstract_clause",
    "coverage_report",
    "coverage_over_cards",
]
