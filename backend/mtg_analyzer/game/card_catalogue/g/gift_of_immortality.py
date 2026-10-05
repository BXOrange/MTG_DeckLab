from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Gift of Immortality (Aura death-loop) — PAR-60
# ===========================================================================
# Reuse of Ghoulish Impetus's `create_delayed_trigger` ->
# `return_self_from_graveyard` shape for the "return this Aura attached at
# the next end step" clause. New `return_dying_subject_to_battlefield`
# effect for the "return that card under its owner's control" clause (off
# the DIES event's ``instance_id``).


def _gift_of_immortality() -> list[AbilitySpec]:
    """Enchant creature (folds in).
    When enchanted creature dies, return that card to the battlefield under
    its owner's control. Return this card to the battlefield attached to
    that creature at the beginning of the next end step."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gift_of_immortality_dies", {})],
            trigger={"event": EventType.DIES, "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Gift of Immortality", _gift_of_immortality)
