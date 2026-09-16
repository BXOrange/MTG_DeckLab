from __future__ import annotations

from ....parser.oracle.spec import EffectSpec
from .._shared.licid import _licid
from ...card_registry.core import register


def _nurturing_licid() -> list:
    """{G}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {G} to end this effect.
    {G}: Regenerate enchanted creature.

    — MEC-47 Tempest Licid cycle (pass 3, the activated-grant Licids):
    shares `card_catalogue/_shared/licid.py`'s `_licid` factory; the granted
    clause is itself an activated ability (`granted_kind="activated"`)
    rather than a static/triggered one.
    """
    return _licid(
        "Nurturing Licid", "{G}", "{G}",
        [EffectSpec("regenerate", {"target_kind": "attached_permanent"})],
        "{G}: Regenerate enchanted creature.",
        granted_kind="activated", granted_cost="{G}",
    )


register("Nurturing Licid", _nurturing_licid)
