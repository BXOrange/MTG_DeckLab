from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _leyline_tyrant() -> list[AbilitySpec]:
    """Flying
    You don't lose unspent red mana as steps and phases end.
    When this creature dies, you may pay any amount of {R}. When you do, it deals that much damage to any
    target.

    — Reign of Dragons deck batch. Flying is a keyword. The first is the new standing `retain_mana`
    (red only, `continuous.empty_mana_pool`). The dies trigger is `pay_cost_then` with an ``{X}`` cost paid
    in red (``x_color``, the announced X is the number of {R}) and a reflexive RULE 603.12 payoff
    (``then_trigger``) dealing X damage to any target.
    """
    return [
        AbilitySpec("static", [EffectSpec("retain_mana", {"colors": ["R"]})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{X}", "x_color": "R",
                "then_trigger": [{"type": "damage", "params": {"amount": "x", "target_kind": "any"}}],
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Leyline Tyrant", _leyline_tyrant)
