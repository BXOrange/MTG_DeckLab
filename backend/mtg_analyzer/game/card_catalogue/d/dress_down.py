from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dress_down() -> list[AbilitySpec]:
    """Flash
    When this enchantment enters, draw a card.
    Creatures lose all abilities.
    At the beginning of the end step, sacrifice this enchantment.

    — Dress Down. All three abilities were individually expressible — the
    board-wide ability strip is the shipped ``remove_all_abilities`` layer-6
    static (RULE 613.7f) — but the card was left unregistered, so the
    fail-closed coverage gate gave it nothing. Flash comes from the RULE 702
    keyword catalogue.

    Note the ordering that makes the card work: the ETB draw is a triggered
    ability that goes on the stack *before* the strip is ever consulted, and
    the strip doesn't remove the enchantment's own abilities (it names
    creatures), so the end-step sacrifice still fires.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
        ),
        AbilitySpec(
            "static",
            [EffectSpec("remove_all_abilities", {"affects": "all_creatures"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
        ),
    ]


register("Dress Down", _dress_down)
