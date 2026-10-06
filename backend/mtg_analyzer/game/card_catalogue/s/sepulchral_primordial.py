from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sepulchral_primordial() -> list[AbilitySpec]:
    """Intimidate
    When this creature enters, for each opponent, you may put up to one target creature card from that player's graveyard onto the battlefield under your control.

    — PLAY-ALL (Revival Trance). Intimidate is a keyword. `return_from_graveyard` ``pick_mode="controller_from_each_opponent"``:
    one optional pick per opponent, in turn order. **Simplification:** chosen as the trigger resolves, not as targets.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "pick_mode": "controller_from_each_opponent", "under_your_control": True, "destination": "battlefield",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Sepulchral Primordial", _sepulchral_primordial)
