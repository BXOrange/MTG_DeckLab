from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lethal_scheme() -> list[AbilitySpec]:
    """Convoke
    Destroy target creature or planeswalker. Each creature that convoked this spell connives.

    — PLAY-ALL Step 2 (Sultai Arisen). Convoke is the keyword fold-in. `_consume_cast_help` records the tapped
    creatures on the spell (`GameObject.convoked_by_ids`, RULE 702.51c) and `connive` with ``convoked`` makes each
    one still on the battlefield connive after the destroy (RULE 701.47: each draws/discards for its own controller).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "destroy", "params": {"target_kind": "creature_or_planeswalker"}},
                {"type": "connive", "params": {"convoked": True}},
            ]})],
        ),
    ]


register("Lethal Scheme", _lethal_scheme)
