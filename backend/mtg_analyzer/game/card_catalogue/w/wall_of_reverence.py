from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wall_of_reverence() -> list[AbilitySpec]:
    """Defender, flying
    At the beginning of your end step, you may gain life equal to the power of target creature you control.

    — PLAY-ALL (Abzan Armor). Keywords are the catalogue's. An optional end-step trigger over `gain_life` with the new
    ``life_from_target_creature: power`` (a RULE 115 target that is a creature you control, the recipient is you).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"life_from_target_creature": "power", "target_creature_kind": "creature_you_control"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
            optional=True,
        ),
    ]


register("Wall of Reverence", _wall_of_reverence)
