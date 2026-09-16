from __future__ import annotations

from .._shared.licid import _kw_at, _licid
from ...card_registry.core import register


def _flanking_licid() -> list:
    """{R}, {T}: This creature loses this ability and becomes an Aura
    enchantment with enchant creature. Attach it to target creature. You
    may pay {R} to end this effect.
    Enchanted creature gains flanking.

    — Flanking Licid (Stronghold) is the one "Summon Licid" card never given
    the errata that turned the others into pure Auras: "{R}, {T}: ~ loses
    this ability and becomes a creature enchantment that reads 'Enchanted
    creature gains flanking' instead of a creature." It *stays a creature*
    (Gatherer 2004-10-04), so `keep_creature=True` keeps the parked layer-4
    type change from stripping "creature" — the one other Licid needs it.
    Otherwise shares `card_catalogue/_shared/licid.py`'s `_licid` factory
    like every sibling in the cycle.
    """
    return _licid("Flanking Licid", "{R}", "{R}", [_kw_at("flanking")],
                  "Enchanted creature gains flanking.", keep_creature=True)


register("Flanking Licid", _flanking_licid)
