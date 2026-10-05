from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 15 (new core primitive: EventType.SACRIFICE)
# ---------------------------------------------------------------------------


def _mayhem_devil() -> list[AbilitySpec]:
    """Whenever a player sacrifices a permanent, Mayhem Devil deals 1 damage
    to any target.

    — Mayhem Devil. First consumer of the new `EventType.SACRIFICE`
    occurrence (RULE 701.17), fired by `RulesEngine._move_to_graveyard` for
    every `put_into_graveyard` sacrifice in addition to DIES/LEAVES. The
    trigger carries no subject condition — "a player" means *any* player's
    sacrifice, and SACRIFICE only ever fires for a permanent being
    sacrificed, so a bare trigger matches exactly the intended events. The
    1-damage effect targets "any target" (RULE 115.4), gathered
    interactively at resolution like any other targeted trigger.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "target_kind": "any"})],
            trigger={"event": EventType.SACRIFICE},
        )
    ]


register("Mayhem Devil", _mayhem_devil)
