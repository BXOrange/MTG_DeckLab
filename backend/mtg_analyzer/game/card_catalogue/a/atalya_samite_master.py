from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The shared activation cost of both modes: {X}, {T}.
_COST = {"text": "{x}, {t}"}


def _atalya_samite_master() -> list[AbilitySpec]:
    """{X}, {T}: Choose one —
    • Prevent the next X damage that would be dealt to target creature this turn. Spend only white mana on X.
    • You gain X life. Spend only white mana on X.

    PAR-109. Each mode body is exactly what the parser already claims on its own line (`prevent_damage_shield` /
    `gain_life` plus the `x_spend_color_marker` that `bind_ability` folds into `ActivationCost.x_spend_color`); only the
    "choose one" header over an *activated* ability has no general row. Like Moxite Refinery it is modelled as one
    activated ability per mode: the mode is chosen as the ability is activated (RULE 602.2b), so picking the ability is
    the choice and each mode keeps its own target. X is the announced X, shared by cost and effect, and the white-only
    rider applies whichever mode is picked (Gatherer ruling 2004-10-04).
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("prevent_damage_shield", {"amount": "x", "target_kind": "creature"}),
                EffectSpec("x_spend_color_marker", {"color": "W"}),
            ],
            cost=dict(_COST),
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("gain_life", {"amount": "x"}),
                EffectSpec("x_spend_color_marker", {"color": "W"}),
            ],
            cost=dict(_COST),
        ),
    ]


register("Atalya, Samite Master", _atalya_samite_master)
