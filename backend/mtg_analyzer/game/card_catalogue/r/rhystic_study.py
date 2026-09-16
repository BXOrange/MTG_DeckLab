from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# --- cEDH lists batch: tax-draw family ("unless that player pays") --------
#
# New primitive: `TaxedDrawEffect` (RULE 118.3's "unless" idiom applied to a
# draw, not a sacrifice) — the payer is the *triggering spell's own caster*,
# read off `GameContext.trigger_event`, not this ability's controller.


def _rhystic_study() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, you may draw a card unless that
    player pays {1}.

    — `TaxedDrawEffect`, see the batch header above.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("taxed_draw", {"cost": "{1}"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        )
    ]


register("Rhystic Study", _rhystic_study)
