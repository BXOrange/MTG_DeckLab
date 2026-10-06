from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _avalanche_of_sector_7() -> list[AbilitySpec]:
    """Menace
    Avalanche of Sector 7's power is equal to the number of artifacts your opponents control.
    Whenever an opponent activates an ability of an artifact they control, Avalanche of Sector 7 deals 1 damage to that player.

    — PLAY-ALL (Limit Break). Menace is the keyword. The power is a `pt_cda` (RULE 604.3) over the structured selector of artifacts your opponents control. The trigger is an
    ``ACTIVATED_ABILITY`` group head (a non-you controller, an artifact) over `damage` to the event's acting controller (``event_controller``). Mana abilities never fire that event
    (RULE 605.1a), so they do not count — a printed simplification of "activates an ability" only for mana abilities, which the card also excludes in practice.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("pt_cda", {
                "affects": "self",
                "power_count": {"zone": "battlefield", "of": "opponents", "filter": {"card_type": "artifact"}},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_controller"})],
            trigger={"event": EventType.ACTIVATED_ABILITY, "condition": {
                "subject": "group", "controller": "not_you", "type": "artifact",
            }},
        ),
    ]


register("Avalanche of Sector 7", _avalanche_of_sector_7)
