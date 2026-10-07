"""Card registration mechanism + entry point.

This package is the *mechanism* — `core.py`'s registry (`register`/
`specs_for`/`registry_signature`/the RULE 614.1-and-siblings oracle-derived
helpers) and `families.py`'s `register_family` template for a mechanically
identical card cycle. The actual card *content* — one hand-authored module
per card — lives next door in `game/card_catalogue/` (a folder per
lowercased first letter of the card's name, e.g. `card_catalogue/c/
circle_of_solace.py`), which this module imports below purely for its
import-time registration side effect.

Every other module that needs a card's specs already imports *this*
package (`from .. import card_registry` / `from mtg_analyzer.game import
card_registry`) to trigger registration — rather than touch every one
of those call sites to additionally import `card_catalogue`, this package
pulls `card_catalogue` in itself at the bottom of this file, once `register`
is already bound above. `card_catalogue`'s own modules import `register`/
`register_family` straight from `.core`/`.families` (not through this
package's own `__init__`), so that back-reference isn't a circular import:
by the time anything triggers `card_catalogue`'s import, `.core` has already
fully executed.
"""

from .core import (
    _REGISTRY,
    enters_tapped,
    entry_counters,
    is_authored_card,
    is_registered,
    kicker_x_mana_restriction,
    land_tap_condition,
    opening_hand_battlefield_permission,
    pregame_setup_permission,
    register,
    registry_signature,
    specs_for,
)

# Trigger card_catalogue's registration side effect. Must come after the
# .core import above (register() needs to already be bound), and is
# intentionally a plain import of the whole package rather than a
# re-export, since nothing here consumes card_catalogue's own names.
from .. import card_catalogue  # noqa: F401

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
