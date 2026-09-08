"""Runtime effect contracts, factories, and concrete mechanics."""

from .core import EffectRegistry


def bootstrap() -> type[EffectRegistry]:
    """Load the built-in effect registrations exactly once."""
    return EffectRegistry


bootstrap()
