from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hammerhead_tyrant() -> list[AbilitySpec]:
    """Flying
    Whenever you cast a spell, return up to one target nonland permanent an opponent controls with mana value less than or equal to that spell's mana value to its owner's hand.

    — PLAY-ALL Step 2 (Temur Roar). A cast trigger whose optional `return_to_hand` target is capped by the
    new ``max_mana_value: "trigger_spell_mana_value"`` sentinel — the ceiling sibling of Skyfire Kirin's
    ``exact_mana_value`` (`targeting.legal_targets` reads the firing SPELL_CAST event's ``mana_value``), so the
    cap is checked when targets are offered, not when the ability resolves.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {
                "target_kind": "nonland_permanent_you_dont_control",
                "max_mana_value": "trigger_spell_mana_value", "optional": True,
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group", "controller": "you"}},
        ),
    ]


register("Hammerhead Tyrant", _hammerhead_tyrant)
