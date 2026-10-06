from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _torrential_gearhulk() -> list[AbilitySpec]:
    """Flash
    When this creature enters, you may cast target instant card from your graveyard without paying its mana cost. If that spell would be put into your graveyard, exile it instead.

    — PLAY-ALL (Scions & Spellcraft). Flash is the keyword's. Impulsivity's `cast_graveyard_instant_sorcery_free_exile` (a
    targeted exile-then-free-cast window) with the new ``graveyard_instant`` own-graveyard target kind.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("cast_graveyard_instant_sorcery_free_exile", {"target_kind": "graveyard_instant"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            optional=True,
        ),
    ]


register("Torrential Gearhulk", _torrential_gearhulk)
