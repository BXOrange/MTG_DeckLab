"""Runtime effect contracts, factories, and concrete mechanics."""

from .core import EffectRegistry
from . import compound_permanents as _compound_permanents  # noqa: F401
from . import player_windows as _player_windows  # noqa: F401
from . import piles as _piles  # noqa: F401
from . import mill_recover_card as _mill_recover_card  # noqa: F401
from . import copy_sacrificed as _copy_sacrificed  # noqa: F401
from . import exile_graveyard_modal as _exile_graveyard_modal  # noqa: F401
from . import devour_token as _devour_token  # noqa: F401
from . import sacrificed_counters_damage as _sacrificed_counters_damage  # noqa: F401
from . import paradigm as _paradigm  # noqa: F401
from . import target_player_creates as _target_player_creates  # noqa: F401
from . import composition as _composition  # noqa: F401 - registers the ENG-37 nodes
from . import exile_top_pool as _exile_top_pool  # noqa: F401
from . import greatest_power_destroy as _greatest_power_destroy  # noqa: F401
from . import entered_this_turn_counters as _entered_this_turn_counters  # noqa: F401


def bootstrap() -> type[EffectRegistry]:
    """Load the built-in effect registrations exactly once."""
    return EffectRegistry


bootstrap()

from . import name_reference as _name_reference  # noqa: F401
