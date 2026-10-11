from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sepulchral_primordial() -> list[AbilitySpec]:
    """Intimidate
    When this creature enters, for each opponent, you may put up to one target creature card from that player's graveyard onto the battlefield under your control.

    — PLAY-ALL (Revival Trance). Intimidate is a keyword. The trigger announces an optional creature-card
    target from each opponent's graveyard before opponents may respond (RULE 603.3d/608.2b).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "that_player_graveyard_creature", "per_player": "opponents",
                "optional": True, "under_your_control": True, "destination": "battlefield",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Sepulchral Primordial", _sepulchral_primordial)
