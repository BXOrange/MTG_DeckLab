from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _damn() -> list[AbilitySpec]:
    """Destroy target creature. A creature destroyed this way can't be
    regenerated.
    Overload {2}{W}{W} (You may cast this spell for its overload cost. If
    you do, change "target" in its text to "each.")

    — Damn. Overload (RULE 702.96) isn't modeled — no alternative-cost
    mechanism stamps "was this spell cast via its overload cost" anywhere a
    resolving effect can read it back (unlike kicker's `kicker_count`), so
    there's nothing to key a target→each rewrite off of; only the ordinary
    single-target cast is modeled, matching the Sword of Forge and
    Frontier partial-model precedent. ``can_be_regenerated=False`` covers
    "can't be regenerated" exactly.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "creature", "can_be_regenerated": False})],
        )
    ]


register("Damn", _damn)
