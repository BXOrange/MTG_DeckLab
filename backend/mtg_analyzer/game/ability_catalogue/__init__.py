"""Card -> `AbilitySpec` catalogue package (mechanically split, 2026-08-27).

This used to be a single ~24.8k-line flat module. It's now a package:
`core.py` holds the shared registry infrastructure (`register`/`specs_for`/
`enters_tapped`/`entry_counters`/`opening_hand_battlefield_permission`/
`pregame_setup_permission`/`kicker_x_mana_restriction`, `_REGISTRY` itself,
and the module docstring explaining the design -- see `core.py` for that),
and `entries_NNN.py` (16 files) hold the ~660 hand-authored per-card
`AbilitySpec` factory functions + their `register(...)` calls, split by
plain original-file-order position -- not reorganized by mechanic or card
type, so a diff against the pre-split history stays easy to follow.

Every `entries_NNN` module is imported below purely for its side effect:
each one calls `register(...)` at module load time, populating `core.
_REGISTRY`. This package's public surface is otherwise identical to the
flat module it replaced -- `from mtg_analyzer.game import ability_catalogue`
and `from mtg_analyzer.game.ability_catalogue import specs_for` (etc.) both
keep working unchanged, since every name below is re-exported here.
"""

from .core import (
    _REGISTRY,
    enters_tapped,
    entry_counters,
    is_registered,
    kicker_x_mana_restriction,
    land_tap_condition,
    opening_hand_battlefield_permission,
    pregame_setup_permission,
    register,
    specs_for,
)

# Imported for their registration side effects only (each populates
# `core._REGISTRY` at module load time) -- see the package docstring above.
from . import entries_001  # noqa: F401
from . import entries_002  # noqa: F401
from . import entries_003  # noqa: F401
from . import entries_004  # noqa: F401
from . import entries_005  # noqa: F401
from . import entries_006  # noqa: F401
from . import entries_007  # noqa: F401
from . import entries_008  # noqa: F401
from . import entries_009  # noqa: F401
from . import entries_010  # noqa: F401
from . import entries_011  # noqa: F401
from . import entries_012  # noqa: F401
from . import entries_013  # noqa: F401
from . import entries_014  # noqa: F401
from . import entries_015  # noqa: F401
from . import entries_016  # noqa: F401
from . import entries_017  # noqa: F401

__all__ = [
    "_REGISTRY",
    "enters_tapped",
    "entry_counters",
    "is_registered",
    "kicker_x_mana_restriction",
    "land_tap_condition",
    "opening_hand_battlefield_permission",
    "pregame_setup_permission",
    "register",
    "specs_for",
]
