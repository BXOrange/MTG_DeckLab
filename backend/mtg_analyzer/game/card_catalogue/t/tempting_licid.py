from __future__ import annotations

from .._shared.licid import _kw_at, _licid
from ...card_registry.core import register


def _tempting_licid() -> list:
    """{G}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {G} to end this effect.
    All creatures able to block enchanted creature do so.

    — MEC-47 Tempest Licid cycle: shares `card_catalogue/_shared/licid.py`'s
    `_licid` factory (the common become-Aura/revert activated-ability pair)
    with every other Licid; only the granted "Enchanted creature …" clause
    differs per card.
    """
    return _licid("Tempting Licid", "{G}", "{G}", [_kw_at("all_must_block")],
                  "All creatures able to block enchanted creature do so.")


register("Tempting Licid", _tempting_licid)
