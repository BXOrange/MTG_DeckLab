from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _edgar_master_machinist() -> list[AbilitySpec]:
    """Once during each of your turns, you may cast an artifact spell from your graveyard. If you cast a spell this way, that artifact enters tapped.
    Whenever this creature attacks, it gets +X/+0 until end of turn, where X is the greatest mana value among artifacts you control.

    — PLAY-ALL (Revival Trance). Lurrus's `graveyard_cast_permission` for artifact spells (``spell_criteria``) with the new
    ``enters_tapped``; the attack pump is Pyreswipe Hawk's (``greatest_mana_value_among_artifacts_you_control``, power only).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_cast_permission", {
                "spell_criteria": {"type": "Artifact"}, "once_per_turn": True, "enters_tapped": True,
                "active_if": {"kind": "your_turn"},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "amount_from_count_selector": "greatest_mana_value_among_artifacts_you_control",
                "amount_from_count_selector_axis": "power",
                "selector": None, "trigger_subject": False, "target_kind": None,
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Edgar, Master Machinist", _edgar_master_machinist)
