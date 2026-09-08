"""Hand-authored card ability specifications and their registry."""

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
    registry_signature,
    specs_for,
)

# Import catalogue modules so they register their card factories.
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
from . import strixhaven_commander  # noqa: F401
from . import commander_cards  # noqa: F401

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
    "registry_signature",
    "specs_for",
]
