from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _old_stickfingers() -> list[AbilitySpec]:
    """When you cast this spell, reveal cards from the top of your library until you reveal X creature cards. Put all creature cards revealed this way into your graveyard, then put the rest on the bottom of your library in a random order.
    Old Stickfingers's power and toughness are each equal to the number of creature cards in your graveyard.

    — PLAY-ALL (Death Toll). The P/T static is the parser's (`pt_cda`). The cast trigger is Open the Way's `reveal_until` (``count: x`` is the {X} paid)
    with the hits going to the graveyard instead of the battlefield; the rest go to the bottom in a random order.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("pt_cda", {
                "affects": "self",
                "power_count": {"zone": "graveyard", "of": "you", "filter": {"card_type": "creature"}},
                "toughness_count": {"zone": "graveyard", "of": "you", "filter": {"card_type": "creature"}},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("reveal_until", {
                "criteria": "creature", "count": "x", "hit_destination": "graveyard", "rest_destination": "library_bottom_random",
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "self"}},
        ),
    ]


register("Old Stickfingers", _old_stickfingers)
