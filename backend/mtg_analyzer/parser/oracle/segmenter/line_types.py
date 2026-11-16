"""Segmenter: line types (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional
from ..spec import ParserProvenance
from .segment_types import Segment

@dataclass(frozen=True)
class LineContext:
    """What every `LINE_MATCHERS` row sees: the stripped line plus the three gates `segment_line` was given."""

    raw: str
    line: str
    allow_spell_effect: bool
    provenance: ParserProvenance
    is_saga: bool


@dataclass(frozen=True)
class LineMatcher:
    """One ordered row of `LINE_MATCHERS`: a named matcher returning a `Segment` to claim (or refuse) the line, or
    ``None`` to fall through to the next row. ORDER IS SEMANTICS: the first row to return a `Segment` wins, and a row
    that returns an unclaimed `Segment` ends the search (it recognised the shape but could not model it)."""

    name: str
    match: Callable[[LineContext], Optional[Segment]]
