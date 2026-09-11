"""Internal support for focused effect modules.

Effect implementations historically shared one module namespace.  This small
compatibility layer keeps cross-family references working while modules are
loaded, without making the public API depend on it.
"""

from __future__ import annotations

import builtins
from types import ModuleType
from typing import Any

_symbols: dict[str, Any] = {}


class _EffectBuiltins(dict[str, Any]):
    def __missing__(self, name: str) -> Any:
        try:
            return _symbols[name]
        except KeyError:
            return getattr(builtins, name)


def install(namespace: dict[str, Any]) -> None:
    """Give an implementation module access to previously loaded families."""
    namespace["__builtins__"] = _EffectBuiltins(vars(builtins))


def register(namespace: dict[str, Any]) -> None:
    """Publish a module's definitions for later effect families."""
    _symbols.update({name: value for name, value in namespace.items() if not name.startswith("__")})


def public_names(module: ModuleType) -> tuple[str, ...]:
    return tuple(name for name in module.__dict__ if not name.startswith("__") and name not in {"install", "register"})
