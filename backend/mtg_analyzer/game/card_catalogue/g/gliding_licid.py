from __future__ import annotations

from .._shared.licid import _kw_at, _licid
from ...card_registry.core import register


def _gliding_licid() -> list:
    """{U}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {U} to end this effect.
    Enchanted creature has flying.

    — MEC-47 Tempest Licid cycle: shares `card_catalogue/_shared/licid.py`'s
    `_licid` factory (the common become-Aura/revert activated-ability pair)
    with every other Licid; only the granted "Enchanted creature …" clause
    differs per card.
    """
    return _licid("Gliding Licid", "{U}", "{U}", [_kw_at("flying")],
                  "Enchanted creature has flying.")


register("Gliding Licid", _gliding_licid)
