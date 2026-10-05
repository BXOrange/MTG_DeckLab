from __future__ import annotations

from .._shared.licid import _kw_at, _licid
from ...card_registry.core import register


def _corrupting_licid() -> list:
    """{B}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {B} to end this effect.
    Enchanted creature has fear.

    — MEC-47 Tempest Licid cycle: shares `card_catalogue/_shared/licid.py`'s
    `_licid` factory (the common become-Aura/revert activated-ability pair)
    with every other Licid; only the granted "Enchanted creature …" clause
    differs per card.
    """
    return _licid("Corrupting Licid", "{B}", "{B}", [_kw_at("fear")],
                  "Enchanted creature has fear.")


register("Corrupting Licid", _corrupting_licid)
