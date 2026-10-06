"""Runtime effect contracts, factories, and concrete mechanics."""

from .core import EffectRegistry
from . import compound_permanents as _compound_permanents  # noqa: F401
from . import player_windows as _player_windows  # noqa: F401
from . import piles as _piles  # noqa: F401
from . import composition as _composition  # noqa: F401 - registers the ENG-37 nodes


def bootstrap() -> type[EffectRegistry]:
    """Load the built-in effect registrations exactly once."""
    return EffectRegistry


bootstrap()
