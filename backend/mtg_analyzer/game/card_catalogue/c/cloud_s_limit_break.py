from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Tiered mode costs (RULE 702.183), in printed order: Cross-Slash, Blade Beam, Omnislash.
_TIER_COSTS = ["{0}", "{1}", "{3}{W}"]
#: The parser's "any number of target …" cap (`_ANY_NUMBER_TARGET_CAP`).
_ANY_NUMBER = 10


def _cloud_s_limit_break() -> list[AbilitySpec]:
    """Tiered (Choose one additional cost.)
    • Cross-Slash — {0} — Destroy target tapped creature.
    • Blade Beam — {1} — Destroy any number of target tapped creatures with different controllers.
    • Omnislash — {3}{W} — Destroy all tapped creatures.

    — PLAY-ALL (Limit Break). Restoration Magic's Tiered shape (``modes["mode_costs"]``, RULE 702.183). `destroy` over a ``tapped`` creature filter; Blade Beam adds
    ``distinct_controllers`` (up to ten targets); Omnislash is a `destroy` of the structured group of every tapped creature (any controller).
    """
    tapped = {"tapped": True}
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={
                "choose": 1, "tiered": True, "mode_costs": list(_TIER_COSTS),
                "options": [
                    [EffectSpec("destroy", {"target_kind": "creature", "creature_filter": dict(tapped)})],
                    [EffectSpec("destroy", {
                        "target_kind": "creature", "creature_filter": dict(tapped), "count": _ANY_NUMBER,
                        "distinct_controllers": True, "optional": True,
                    })],
                    [EffectSpec("destroy", {
                        "group": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature", **tapped}},
                    })],
                ],
                "descriptions": [
                    "Cross-Slash — Zerstöre eine Ziel-getappte Kreatur.",
                    "Blade Beam — Zerstöre beliebig viele getappte Zielkreaturen verschiedener Kontrolleure.",
                    "Omnislash — Zerstöre alle getappten Kreaturen.",
                ],
            },
        ),
    ]


register("Cloud's Limit Break", _cloud_s_limit_break)
