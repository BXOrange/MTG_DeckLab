"""The repo-committed handler catalogue (docs/09 "THE CATALOGUE").

Phase 1's first, cheapest, highest-yield deliverable is the **keyword
catalogue** (`keywords.py`): the closed RULE 702 vocabulary, each keyword
mapped to its `AbilitySpec` shape, with a regex that extracts the single
parameter of a parametric keyword. The effect-clause handler rows and the
shared sub-grammars land alongside it in later phases.
"""

from .keywords import (
    KEYWORDS,
    KeywordDef,
    KeywordShape,
    keyword_slug,
    parse_keywords,
)

__all__ = [
    "KEYWORDS",
    "KeywordDef",
    "KeywordShape",
    "keyword_slug",
    "parse_keywords",
]
