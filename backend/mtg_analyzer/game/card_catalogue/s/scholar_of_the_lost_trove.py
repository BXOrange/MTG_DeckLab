from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scholar_of_the_lost_trove() -> list[AbilitySpec]:
    """Flying
    When this creature enters, you may cast target instant, sorcery, or artifact
    card from your graveyard without paying its mana cost. If an instant or
    sorcery spell cast this way would be put into your graveyard, exile it
    instead.

    — PLAY-ALL Step 2 (Oops! All Night's Whispers). Flying is the keyword
    fold-in. The ETB is MEC-24's per-card `grant_flashback_to_target` (Emry's
    shape) over the new graveyard target kind ``graveyard_instant_sorcery_or_
    artifact``, with ``cost: "{0}"`` — flashback at no mana cost *is* "cast without
    paying its mana cost" and "exile instead of the graveyard". **Documented
    simplification:** the permission lasts the turn rather than being used at
    once as the trigger resolves, and an artifact cast this way is simply cast.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_flashback_to_target", {
                "target_kind": "graveyard_instant_sorcery_or_artifact", "cost": "{0}",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Scholar of the Lost Trove", _scholar_of_the_lost_trove)
