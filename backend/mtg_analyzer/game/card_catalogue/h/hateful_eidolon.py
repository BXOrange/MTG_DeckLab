from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Hateful Eidolon (auras-attached snapshot on DIES) — PAR-60
# ===========================================================================
# New: `RulesEngine._move_to_graveyard` now snapshots
# ``attached_aura_controller_ids`` onto the DIES event (fired while the
# dying creature + its Auras are still on the battlefield, RULE 603.6a),
# read by the `draw_per_attached_aura_controller` effect. The trigger reuses
# (only fires when this controller had an Aura on the creature — exactly
# when the draw is nonzero).


def _hateful_eidolon() -> list[AbilitySpec]:
    """Lifelink (folds in).
    Whenever an enchanted creature dies, draw a card for each Aura you
    controlled that was attached to it."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw_per_attached_aura_controller", {})],
            trigger={"event": EventType.DIES,
                     "condition": {"subject": "group", "type": "creature",
                                   "enchanted_by_your_aura": True}},
        ),
    ]


register("Hateful Eidolon", _hateful_eidolon)
