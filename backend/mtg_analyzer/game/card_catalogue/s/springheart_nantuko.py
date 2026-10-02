from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The printed landfall payment.
_COPY_COST = "{1}{G}"
_INSECT = {
    "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
    "subtypes": ["Insect"], "keywords": [], "token_name": "Insect",
}


def _springheart_nantuko() -> list[AbilitySpec]:
    """Bestow {1}{G}
    Enchanted creature gets +1/+1.
    Landfall — Whenever a land you control enters, you may pay {1}{G} if this
    permanent is attached to a creature you control. If you do, create a token
    that's a copy of that creature. If you didn't create a token this way,
    create a 1/1 green Insect creature token.

    — PLAY-ALL Step 2 (Kodama). Bestow is the keyword fold-in and the anthem the
    parser's own claim (``affects: attached_permanent``). The landfall body is an
    `if_else` on `source_attached`: attached -> `pay_cost_then` {1}{G} ->
    `copy_permanent` of the attached permanent (``target_kind:
    attached_permanent``), *else* (you declined) the Insect; unattached -> the
    Insect straight away (the payment is never offered, as printed).
    **Documented simplification:** "a creature you control" is not checked — an
    attached-but-opponent-controlled host still offers the copy.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"power": 1, "toughness": 1, "affects": "attached_permanent"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("if_else", {
                "condition": {"kind": "source_attached"},
                "then": [{"type": "pay_cost_then", "params": {
                    "cost": _COPY_COST,
                    "effects": [{"type": "copy_permanent", "params": {"target_kind": "attached_permanent"}}],
                    "else_effects": [{"type": "create_token", "params": dict(_INSECT)}],
                }}],
                "else": [{"type": "create_token", "params": dict(_INSECT)}],
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "type": "land"},
            },
        ),
    ]


register("Springheart Nantuko", _springheart_nantuko)
