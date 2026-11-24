"""Static-ability helpers: matcher types (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Union
from ...spec import EffectSpec

class _Decline:
    """Type of `DECLINE`: a matcher recognised the clause but refuses to model it."""


#: Returned by a `StaticMatcher` that matched and then declined: `static_effect_specs` stops and returns ``None``
#: (the original branch ended in ``return None``). A plain ``None`` instead means "not mine, try the next row".
DECLINE = _Decline()

StaticResult = Union[list[EffectSpec], None, _Decline]


def claim(result: Optional[list[EffectSpec]]) -> StaticResult:
    """A matched branch's helper result: ``None`` from the helper ends the search (`DECLINE`), it does not fall through."""
    return DECLINE if result is None else result


@dataclass(frozen=True)
class StaticContext:
    """What every `STATIC_MATCHERS` row sees: the raw clause and its normalised ``text`` (period-stripped and, after
    the ``fold_additional`` rewrite, with "gets an additional" folded to "gets")."""

    clause: str
    text: str


@dataclass(frozen=True)
class StaticMatcher:
    """One ordered row: returns the specs to claim the clause, ``DECLINE`` to stop with ``None``, or ``None`` to fall
    through to the next row. ORDER IS SEMANTICS (first row to answer wins)."""

    name: str
    match: Callable[[StaticContext], StaticResult]


@dataclass(frozen=True)
class StaticRewrite:
    """An in-table step that rewrites ``text`` for every later row (a matcher cannot, its context is frozen)."""

    name: str
    rewrite: Callable[[str], str]
