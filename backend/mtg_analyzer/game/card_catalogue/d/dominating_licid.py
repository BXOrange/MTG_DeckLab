from __future__ import annotations

from ....parser.oracle.spec import EffectSpec
from .._shared.licid import _licid
from ...card_registry.core import register


def _dominating_licid() -> list:
    """{1}{U}{U}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {U} to end this effect.
    You control enchanted creature.

    — MEC-47 Tempest Licid cycle: shares `card_catalogue/_shared/licid.py`'s
    `_licid` factory (the common become-Aura/revert activated-ability pair)
    with every other Licid; the granted clause is a plain `"control_change"`
    static rather than a keyword grant.
    """
    return _licid("Dominating Licid", "{1}{U}{U}", "{U}", [EffectSpec("control_change", {})],
                  "You control enchanted creature.")


register("Dominating Licid", _dominating_licid)
