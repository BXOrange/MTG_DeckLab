"""Late-bound entry points between the segmenter's modules (ENG-59): the effect-body parser, the line segmenter and the helpers they recurse through are mutually recursive, so a module earlier in the dependency order calls them through these forwarders and the defining module registers itself at import (the same device as `catalogue/clause_hooks.py`)."""

from __future__ import annotations

from typing import Any, Callable

_impl: dict[str, Callable[..., Any]] = {}


def register(**fns: Callable[..., Any]) -> None:
    """Called once by the module that defines each entry point, when it finishes importing."""
    _impl.update(fns)


def bind_x_specs(*args: Any, **kwargs: Any) -> Any:
    """Forwards to the registered `bind_x_specs`."""
    return _impl["bind_x_specs"](*args, **kwargs)


def parse_effect_body(*args: Any, **kwargs: Any) -> Any:
    """Forwards to the registered `parse_effect_body`."""
    return _impl["parse_effect_body"](*args, **kwargs)


def segment_line(*args: Any, **kwargs: Any) -> Any:
    """Forwards to the registered `segment_line`."""
    return _impl["segment_line"](*args, **kwargs)


def segment_line_unsplit(*args: Any, **kwargs: Any) -> Any:
    """Forwards to the registered `segment_line_unsplit`."""
    return _impl["segment_line_unsplit"](*args, **kwargs)


def turn_trigger_segment(*args: Any, **kwargs: Any) -> Any:
    """Forwards to the registered `turn_trigger_segment`."""
    return _impl["turn_trigger_segment"](*args, **kwargs)
