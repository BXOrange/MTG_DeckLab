from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cemetery_desecrator() -> list[AbilitySpec]:
    """Menace
    When this creature enters or dies, exile another card from a graveyard. When you do, choose one —
    • Remove X counters from target permanent, where X is the mana value of the exiled card.
    • Target creature an opponent controls gets -X/-X until end of turn, where X is the mana value of the exiled card.

    Menace is the RULE 702 keyword catalogue's. "Enters or dies" is two triggered abilities running the same
    effect. `exile_graveyard_card_then_modal` (`effects/exile_graveyard_modal.py`) exiles another graveyard card
    by choice and then queues the RULE 603.12 reflexive "choose one" (`enqueue_reflexive_trigger` modes) with X
    baked in from the exiled card's mana value; its modes are the new exact `remove_exact_counters` and a
    `pump` of -X/-X on a creature an opponent controls.
    """
    return [
        AbilitySpec(
            "triggered", [EffectSpec("exile_graveyard_card_then_modal", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered", [EffectSpec("exile_graveyard_card_then_modal", {})],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Cemetery Desecrator", _cemetery_desecrator)
