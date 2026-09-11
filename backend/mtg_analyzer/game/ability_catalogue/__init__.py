"""Hand-authored card ability specifications, grouped by purpose.

Each imported module owns a cohesive family of cards (for example damage
prevention, competitive interaction, or a deck-specific mechanic).  Modules
are imported solely to register their pure card factories with ``core``.
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
    registry_signature,
    specs_for,
)

# Import catalogue modules so they register their card factories.  This keeps
# the former load order stable for deterministic duplicate-registration
# diagnostics while the names now express each module's responsibility.
from . import copying  # noqa: F401
from . import removal  # noqa: F401
from . import graveyard  # noqa: F401
from . import interaction  # noqa: F401
from . import fallout  # noqa: F401
from . import fast_mana  # noqa: F401
from . import enrage  # noqa: F401
from . import tribal  # noqa: F401
from . import red_spells  # noqa: F401
from . import competitive_interaction  # noqa: F401
from . import punishers  # noqa: F401
from . import damage_prevention  # noqa: F401
from . import denial  # noqa: F401
from . import value  # noqa: F401
from . import stax  # noqa: F401
from . import black  # noqa: F401
from . import special_mechanics  # noqa: F401
from . import blight_curse  # noqa: F401
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
