from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _anger() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Mountain, creatures you control have haste.

    — Anger. RULE 112.7a's own printed exception: a static ability that
    explicitly functions from the graveyard rather than the battlefield
    (the "Timeshifted enemy-color cycle" — Brawn/Filth/Valor/Wonder are
    the same shape onto trample/swampwalk/first strike/flying, not in
    scope here). ``"from_graveyard": True`` is what `continuous.
    _battlefield_static_abilities` reads to scan each player's graveyard
    for this one marked ability instead of the battlefield — everything
    downstream (the layer-6 keyword grant, the "you control a Mountain"
    `active_if` gate) is the same machinery an ordinary battlefield anthem
    already uses; only the *source's own zone* is unusual. Re-evaluated
    fresh every `continuous.recompute` pass, so this stops granting haste
    the instant either half of the condition stops holding — Anger leaves
    the graveyard, or the last Mountain does.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["haste"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_mountain",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
        ),
    ]


register("Anger", _anger)
