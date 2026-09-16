from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _simian_sling() -> list[AbilitySpec]:
    """Equipped creature gets +1/+1.
    Whenever this creature or equipped creature becomes blocked, it deals
    1 damage to defending player.
    Reconfigure {2}

    — Simian Sling. The trigger's "defending player" resolves via
    `_defending_player_of`, which reads the ability's own source's
    combat-defender stamp — correct when Simian Sling itself is the
    attacking creature — and, since ENG-14, falls back to the permanent
    it's reconfigured onto when that's the one actually attacking instead
    (RULE 702.151), matching this trigger's own "this creature **or
    equipped creature**" subject scoping.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "defending_player"})],
            trigger={"event": EventType.BECOMES_BLOCKED, "condition": {"subject": "self_or_attached_permanent"}},
        ),
    ]


register("Simian Sling", _simian_sling)
