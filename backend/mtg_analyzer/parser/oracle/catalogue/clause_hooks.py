"""Late-bound entry points into the segmenter and the static handlers (PAR-172).

The effect handlers, the static handlers and a few sequence grammars all *recurse*
into the segmenter ("parse this sub-clause as an effect body", "parse this quoted
ability as a line"), while the segmenter dispatches *down* into them. That recursion
is the one genuine cycle in the parser: each of these callables is defined in a module
that sits above its callers. Instead of function-scoped imports, the callers import the
forwarding functions below (a leaf: it imports no parser module) and the defining
module registers its implementation once, at import time.

`mtg_analyzer.parser.oracle.__init__` imports `gate`, which imports the segmenter, so
every parse entry point has the registrations in place before any hook is called.
Signatures mirror the real functions; see them for the contracts.

Pure regex + data — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..spec import EffectSpec, ParserProvenance

_UNREGISTERED = "clause hook {name!r} called before its defining module was imported"

_parse_effect_body: Optional[Callable[..., Optional[list[EffectSpec]]]] = None
_segment_line: Optional[Callable[..., Any]] = None
_trigger_condition_dict: Optional[Callable[[str], Optional[dict[str, Any]]]] = None
_static_condition: Optional[Callable[[str], Optional[dict]]] = None


def register_segmenter(
    *,
    parse_effect_body: Callable[..., Optional[list[EffectSpec]]],
    segment_line: Callable[..., Any],
    trigger_condition_dict: Callable[[str], Optional[dict[str, Any]]],
) -> None:
    """Called once by `segmenter` when it finishes defining its entry points."""
    global _parse_effect_body, _segment_line, _trigger_condition_dict
    _parse_effect_body = parse_effect_body
    _segment_line = segment_line
    _trigger_condition_dict = trigger_condition_dict


def register_static_condition(static_condition: Callable[[str], Optional[dict]]) -> None:
    """Called once by `static_handlers`."""
    global _static_condition
    _static_condition = static_condition


def parse_effect_body(
    body: str, *, self_subject: bool = False, previous_subject: bool = False,
    group_subject: bool = False, previous_selector: bool = False,
    attached_subject: bool = False,
) -> Optional[list[EffectSpec]]:
    """`segmenter.parse_effect_body`."""
    assert _parse_effect_body is not None, _UNREGISTERED.format(name="parse_effect_body")
    return _parse_effect_body(
        body, self_subject=self_subject, previous_subject=previous_subject,
        group_subject=group_subject, previous_selector=previous_selector,
        attached_subject=attached_subject,
    )


def segment_line(
    line: str,
    *,
    allow_spell_effect: bool,
    provenance: ParserProvenance,
    is_saga: bool = False,
) -> Any:
    """`segmenter.segment_line` (returns a `segmenter.Segment`)."""
    assert _segment_line is not None, _UNREGISTERED.format(name="segment_line")
    return _segment_line(
        line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga,
    )


def trigger_condition_dict(cond_text: str) -> Optional[dict[str, Any]]:
    """`segmenter.trigger_condition_dict`."""
    assert _trigger_condition_dict is not None, _UNREGISTERED.format(name="trigger_condition_dict")
    return _trigger_condition_dict(cond_text)


def static_condition(text: str) -> Optional[dict]:
    """`static_handlers.static_condition`."""
    assert _static_condition is not None, _UNREGISTERED.format(name="static_condition")
    return _static_condition(text)
