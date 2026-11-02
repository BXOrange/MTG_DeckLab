from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

# "Two target creatures you control that share a creature type" — RULE 115.1a fixes the number of
# targets (two, mandatory) and RULE 205.3m defines creature types. The shared-type relation between the
# two picks is `TargetSpec.shared_creature_type` (game/shared_type_targets.py), enforced with the other
# cross-target budgets. RULE 509.1b: the effect sets `temp_unblockable`, cleared at cleanup (RULE 514.2).
SECRET_TUNNEL_TARGET_COUNT = 2  # printed "two target creatures"


def _secret_tunnel() -> list[AbilitySpec]:
    "This land can't be blocked.\n{T}: Add {C}.\n{4}, {T}: Two target creatures you control that share a creature type can't be blocked this turn."
    return [
        AbilitySpec(
            'static',
            [EffectSpec('grant_keyword', {"keywords": ['cant_be_blocked'], "affects": 'self'})],
            raw_text="~ can't be blocked.",
        ),
        # {T}: Add {C}. is bound automatically off the printed text (game/mana_abilities.py).
        AbilitySpec(
            "activated",
            [EffectSpec("unblockable", {
                "target_kind": "creature_you_control", "count": SECRET_TUNNEL_TARGET_COUNT,
                "shared_creature_type": True,
            })],
            cost={"mana": "{4}", "taps_self": True},
            raw_text="{4}, {t}: 2 target creatures you control that share a creature type can't be blocked this turn.",
        ),
    ]


register('Secret Tunnel', _secret_tunnel)
