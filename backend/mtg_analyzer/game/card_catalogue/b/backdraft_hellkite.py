from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _backdraft_hellkite() -> list[AbilitySpec]:
    """Flying
    Whenever this creature attacks, each instant and sorcery card in your
    graveyard gains flashback until end of turn. The flashback cost is
    equal to its mana cost.

    — Imodane deck batch. Flying is a RULE 702 keyword, auto-bound. The
    grant is the new `grant_graveyard_cast_permission_this_turn` — see
    its docstring for why it's a fresh primitive rather than the existing
    standing `graveyard_cast_permission` (Lurrus-shaped: tied to a
    permanent's continued presence, not turn-scoped).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_graveyard_cast_permission_this_turn", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Backdraft Hellkite", _backdraft_hellkite)
