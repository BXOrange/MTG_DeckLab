from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from ...creature_type_counts import CREATURE_TYPES_AMONG_NON_BORG_CREATURES_YOU_CONTROL


def _jean_luc_mon_capitaine() -> list[AbilitySpec]:
    """Flying
    Federation — Faeries you control enter with an additional +1/+1 counter on them for each creature type among
    non-Borg creatures you already control.

    — MEC-143. Flying is the keyword's. The counters are the `extra_etb_counter` static (Giada's/Metallic Mimic's
    entry-counter grant, RULE 614.1c) filtered to Faeries, counted off the distinct-creature-types selector. The entering
    Faerie is not on the battlefield while the replacement is applied, so "already control" holds by construction.
    Jean-Luc is not himself a Faerie, so he is not special-cased (``other`` False keeps a Faerie Jean-Luc counted).
    """
    return [
        AbilitySpec("static", [EffectSpec("extra_etb_counter", {
            "kind": "+1/+1", "filter": {"subtype": "faerie"}, "other": False,
            "count_selector": CREATURE_TYPES_AMONG_NON_BORG_CREATURES_YOU_CONTROL,
        })]),
    ]


register("Jean-Luc, Mon Capitaine", _jean_luc_mon_capitaine)
