from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cloudstone_curio() -> list[AbilitySpec]:
    """Whenever a nonartifact permanent you control enters, you may return
    another permanent you control that shares a permanent type with it to
    its owner's hand.

    — Cloudstone Curio. "Shares a permanent type **with it**" is why this
    can't be an ordinary bounce with a target kind: the legal set depends on
    the *entering* permanent, which is only known per firing. It reads
    `GameContext.trigger_event` (the RULE 603.1 firing event, exposed for
    exactly the resolution window) and narrows to permanents sharing one of
    its RULE 205.2a main types.

    The trigger's group subject uses the negated type filter added for
    Kinnan (``"type": "nonartifact"``), so the artifact half of the printed
    restriction is real rather than dropped.

    **Documented simplification**: the "you may … return" *pick* is
    non-interactive (most recently added matching permanent). The trigger
    itself is already ``optional``, so the machinery does ask whether to
    bounce at all — and Cloudstone Curio's real use is a deliberate two-card
    loop where the intended permanent is unambiguous.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_shared_type_permanent", {})],
            optional=True,
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "controller": "you", "type": "nonartifact",
                },
            },
        ),
    ]


register("Cloudstone Curio", _cloudstone_curio)
