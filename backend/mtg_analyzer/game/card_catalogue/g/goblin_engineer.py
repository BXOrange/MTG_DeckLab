from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _goblin_engineer() -> list[AbilitySpec]:
    """When this creature enters, you may search your library for an
    artifact card, put it into your graveyard, then shuffle.
    {R}, {T}, Sacrifice an artifact: Return target artifact card with mana
    value 3 or less from your graveyard to the battlefield.

    — Goblin Engineer. The reanimation ability's "mana value 3 or less"
    restriction isn't modeled (no graveyard target kind carries a
    mana-value filter yet — the same documented simplification Sun Titan's
    own catalogue entry already uses, any artifact card in the graveyard is
    a legal target here).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "Artifact"}, "destination": "graveyard"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_artifact", "destination": "battlefield"})],
            cost={"text": "{R}, {T}, Sacrifice an artifact"},
        ),
    ]


register("Goblin Engineer", _goblin_engineer)
