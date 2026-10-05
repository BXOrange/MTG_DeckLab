from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _grothama_all_devouring() -> list[AbilitySpec]:
    """Other creatures have "Whenever this creature attacks, you may have it fight Grothama,
    All-Devouring."
    When Grothama leaves the battlefield, each player draws cards equal to the amount of damage dealt
    to Grothama this turn by sources they controlled.

    — Animated Army deck batch. The grant is `grant_triggered_ability` over every other creature
    (``all_other_creatures`` — any controller) whose optional ATTACKS effect is a `fight` against the
    granting permanent, pinned by the ``$grantor`` sentinel `continuous._build_grant_effect` resolves
    to Grothama's instance id (no RULE 115 target). The leaves-the-battlefield draw is
    `draw_per_damage_dealt_to_source`, summing this turn's DAMAGE events aimed at Grothama per
    source controller.
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_triggered_ability", {
            "affects": "all_other_creatures", "trigger_event": EventType.ATTACKS, "optional": True,
            "grant_effects": [{"type": "fight", "params": {"other_instance_id": "$grantor"}}],
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw_per_damage_dealt_to_source", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Grothama, All-Devouring", _grothama_all_devouring)
