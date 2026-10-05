from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ikra_shidiqi_the_usurper() -> list[AbilitySpec]:
    """Menace
    Whenever a creature you control deals combat damage to a player, you
    gain life equal to that creature's toughness.
    Partner (You can have two commanders if both have partner.)

    — MEC-43 round 4A. Menace and Partner are both RULE 702 keywords,
    folded in automatically by the keyword catalogue regardless of
    registration — only the triggered life-gain needs hand-authoring here.
    The trigger itself is the exact group-subject "a creature you control
    deals combat damage to a player" shape the oracle parser already fully
    models for Bident of Thassa/Deepfathom Skulker (confirmed by parsing
    that trigger's own text in isolation — reused verbatim, not re-derived);
    what blocks the *whole card* from `MODELED` is the effect body, "gain
    life equal to **that creature's** toughness" — a new
    `GainLifeEffect.amount_from_trigger_source_toughness`, which reads the
    firing DAMAGE event's own ``source_id`` (`GameContext.trigger_event`,
    the same "read this firing's own payload" idiom
    `DestroyEffect.target_from_trigger_event` already uses for Mikaeus, the
    Unhallowed) and that creature's current live toughness.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount_from_subject": "trigger_subject_toughness"})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "type": "creature", "other": False, "controller": "you"},
                "filter": {"is_player": True, "combat": True},
            },
        ),
    ]


register("Ikra Shidiqi, the Usurper", _ikra_shidiqi_the_usurper)
