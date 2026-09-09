"""Runtime effect contracts, factories, and concrete mechanics."""

from .core import EffectRegistry
from . import composition as _composition  # noqa: F401 - registers the ENG-37 nodes


def bootstrap() -> type[EffectRegistry]:
    """Load the built-in effect registrations exactly once."""
    return EffectRegistry


bootstrap()
