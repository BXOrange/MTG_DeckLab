from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aetheric_amplifier() -> list[AbilitySpec]:
    """{T}: Add one mana of any color.
    {4}, {T}: Choose one. Activate only as a sorcery.
    • Double the number of each kind of counter on target permanent.
    • Double the number of each kind of counter you have.

    — PLAY-ALL (Living Energy). The mana ability is auto-bound from the printed text. The modal activated ability is
    Umezawa's Jitte's ``modes`` shape over `double_counters_on_target` (any permanent) and its new ``player`` mode (the
    controller's own energy/experience/poison counters).
    """
    return [
        AbilitySpec(
            "activated",
            [],
            cost={"text": "{4}, {t}", "sorcery_speed_only": True},
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("double_counters_on_target", {"target_kind": "permanent"})],
                    [EffectSpec("double_counters_on_target", {"mode": "player"})],
                ],
                "descriptions": [
                    "Double the number of each kind of counter on target permanent.",
                    "Double the number of each kind of counter you have.",
                ],
            },
        ),
    ]


register("Aetheric Amplifier", _aetheric_amplifier)
