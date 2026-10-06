from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "+2/+0".
_POWER_BONUS = 2


def _gogo_mysterious_mime() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, you may have this creature become a copy of another target creature you control until end of turn, except its name is Gogo, Mysterious Mime. If you do, Gogo and that creature each get +2/+0 and gain haste until end of turn and attack this turn if able.

    — PLAY-ALL (Revival Trance). An optional begin-combat trigger: `become_copy_until_eot` (``set_name``) of another creature
    you control, then `pump` on Gogo itself and on the copied creature (``previous_subject``) for +2/+0, haste and
    ``attacks_if_able``.
    """
    pump = {"power": _POWER_BONUS, "toughness": 0, "keywords": ["haste", "attacks_if_able"]}
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("become_copy_until_eot", {
                    "target_kind": "other_creature_you_control", "set_name": "Gogo, Mysterious Mime",
                }),
                EffectSpec("pump", {**pump, "previous_subject": True}),
                EffectSpec("pump", {**pump, "target_kind": None}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
            optional=True,
        ),
    ]


register("Gogo, Mysterious Mime", _gogo_mysterious_mime)
