from __future__ import annotations

from .._shared.licid import _kw_at, _licid
from ...card_registry.core import register


def _calming_licid() -> list:
    """{W}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {W} to end this effect.
    Enchanted creature can't attack.

    — MEC-47 Tempest Licid cycle: shares `card_catalogue/_shared/licid.py`'s
    `_licid` factory (the common become-Aura/revert activated-ability pair)
    with every other Licid; only the granted "Enchanted creature …" clause
    differs per card.
    """
    return _licid("Calming Licid", "{W}", "{W}", [_kw_at("cant_attack")],
                  "Enchanted creature can't attack.")


register("Calming Licid", _calming_licid)
