from __future__ import annotations

from ....parser.oracle.spec import EffectSpec
from .._shared.licid import _licid
from ...card_registry.core import register


def _transmogrifying_licid() -> list:
    """{1}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {1} to end this effect.
    Enchanted creature gets +1/+1 and is an artifact in addition to its
    other types.

    — MEC-47 Tempest Licid cycle: shares `card_catalogue/_shared/licid.py`'s
    `_licid` factory (the common become-Aura/revert activated-ability pair)
    with every other Licid; the granted clause is a plain anthem + type
    change pair rather than a single keyword grant.
    """
    return _licid("Transmogrifying Licid", "{1}", "{1}", [
        EffectSpec("anthem", {"power": 1, "toughness": 1, "affects": "attached_permanent"}),
        EffectSpec("type_change", {"add_types": ["artifact"], "affects": "attached_permanent"}),
    ], "Enchanted creature gets +1/+1 and is an artifact in addition to its other types.")


register("Transmogrifying Licid", _transmogrifying_licid)
