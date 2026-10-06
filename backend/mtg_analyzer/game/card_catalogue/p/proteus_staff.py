from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _proteus_staff() -> list[AbilitySpec]:
    """{2}{U}, {T}: Put target creature on the bottom of its owner's library. That creature's controller reveals cards from
    the top of their library until they reveal a creature card. The player puts that card onto the battlefield and the rest on
    the bottom of their library in any order. Activate only as a sorcery.

    — PLAY-ALL (Multiverse Reforged). `replace_target_with_revealed` with ``removal="bottom"`` and
    ``revealer="target_controller"`` (read before the creature leaves). **Simplification:** "in any order" is the random
    bottom order.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("replace_target_with_revealed", {
                "target_kind": "creature", "removal": "bottom", "revealer": "target_controller",
                "criteria": {"type": "Creature"},
            })],
            cost={"text": "{2}{U}, {T}", "sorcery_speed_only": True},
        ),
    ]


register("Proteus Staff", _proteus_staff)
