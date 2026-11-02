
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ironsoul_enforcer() -> list[AbilitySpec]:
    """Whenever this creature or a commander you control attacks alone, return target artifact card from your
    graveyard to the battlefield.

    RULE 508.1 / ATTACKS_ALONE (the aggregate "attacks alone" event, fired once per combat for the single attacker)
    with a RULE 903.3 commander attacker: ``subject="self_or_group"`` admits the source itself, and ``commander``
    (`_build_group_ok`'s live-board check) admits any other creature you control that is a commander. The return is
    the ordinary targeted `return_from_graveyard` onto the battlefield (RULE 115.1), the target chosen when the
    trigger goes on the stack (RULE 603.3d).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_artifact", "destination": "battlefield", "optional": False,
            })],
            trigger={
                "event": EventType.ATTACKS_ALONE,
                "condition": {"subject": "self_or_group", "controller": "you", "commander": True},
            },
        ),
    ]


register("Ironsoul Enforcer", _ironsoul_enforcer)
