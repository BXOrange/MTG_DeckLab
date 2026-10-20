"""The repo-committed handler catalogue (docs/09 "THE CATALOGUE").

The closed RULE 702 keyword vocabulary lives in `keywords.py` (each keyword mapped to
its `AbilitySpec` shape, with a regex for a parametric keyword's parameter). Effect
clauses are read by the handler rows in `handlers.py` (and the sibling per-family
modules: `counters`, `lands`, `levels`, `modal`, …), static abilities by
`static_handlers.py`; `segmenter.py` and `gate.py` drive them.
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
