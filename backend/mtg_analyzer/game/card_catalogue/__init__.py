"""Hand-authored card entries, one module per card, organized alphabetically.

`game/card_registry` is the registration *mechanism* (`register`/
`register_family`/`specs_for`/`registry_signature`/the RULE 614.1-and-siblings
oracle-derived helpers) — see that package's own docstring and `core.py`.
This package is purely *content*: a folder per lowercased first letter of a
card's registered name (`a/`, `b/`, ... `z/`), and inside each, exactly one
module per card (e.g. `c/circle_of_solace.py`, `t/the_master_gallifreys_end
.py`), each calling `card_registry.core.register(name, factory)` (or,
for a small mechanically-identical cycle, `card_registry.families.
register_family`) at import time.

`_shared/` is the one carve-out: helpers genuinely reused by *several* cards
that don't fit `register_family`'s single-`EffectSpec`-shape template (e.g.
`_shared/licid.py`'s `_licid` factory for the Tempest Licid cycle, MEC-47).
It is not itself a letter folder and is not swept by the imports below —
each card module that needs one imports it directly.

Importing this package (transitively, via `card_registry`, which is the
established side-effect-triggering entry point every other module already
uses) registers every card here. The import list below is deliberately
explicit rather than a `pkgutil`/directory scan, mirroring
`card_registry/__init__.py`'s own former per-module import list: stable,
grep-able, and doesn't depend on filesystem iteration order.
"""

from . import (
    a, b, c, d, e, f, g, h, i, j, k, l, m, n, o, p, q, r, s, t, u, v, w, y, z,
)  # noqa: F401

__all__ = [
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o",
    "p", "q", "r", "s", "t", "u", "v", "w", "y", "z",
]
