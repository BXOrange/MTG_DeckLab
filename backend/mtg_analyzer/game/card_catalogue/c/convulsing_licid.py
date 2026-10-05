from __future__ import annotations

from .._shared.licid import _kw_at, _licid
from ...card_registry.core import register


def _convulsing_licid() -> list:
    """{R}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {R} to end this effect.
    Enchanted creature can't block.

    — MEC-47 Tempest Licid cycle: shares `card_catalogue/_shared/licid.py`'s
    `_licid` factory (the common become-Aura/revert activated-ability pair)
    with every other Licid; only the granted "Enchanted creature …" clause
    differs per card.
    """
    return _licid("Convulsing Licid", "{R}", "{R}", [_kw_at("cant_block")],
                  "Enchanted creature can't block.")


register("Convulsing Licid", _convulsing_licid)
