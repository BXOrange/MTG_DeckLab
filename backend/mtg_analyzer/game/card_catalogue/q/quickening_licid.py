from __future__ import annotations

from .._shared.licid import _kw_at, _licid
from ...card_registry.core import register


def _quickening_licid() -> list:
    """{1}{W}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {W} to end this effect.
    Enchanted creature has first strike.

    — MEC-47 Tempest Licid cycle: shares `card_catalogue/_shared/licid.py`'s
    `_licid` factory (the common become-Aura/revert activated-ability pair)
    with every other Licid; only the granted "Enchanted creature …" clause
    differs per card.
    """
    return _licid("Quickening Licid", "{1}{W}", "{W}", [_kw_at("first strike")],
                  "Enchanted creature has first strike.")


register("Quickening Licid", _quickening_licid)
