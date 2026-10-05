from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _consuming_aberration() -> list[AbilitySpec]:
    """Consuming Aberration's power and toughness are each equal to the number of cards in your opponents' graveyards.
    Whenever you cast a spell, each opponent reveals cards from the top of their library until they reveal a land
    card, then puts those cards into their graveyard.

    — PLAY-ALL Step 2 (Sultai Arisen). The characteristic-defining P/T is the parser's own claim, reproduced. The
    trigger is `reveal_until` with the new ``scope="each_opponent"`` (each opponent reveals from *their own* library)
    and ``hit_destination="graveyard"``: the revealed land and everything above it all go to that opponent's graveyard.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("pt_cda", {
                "affects": "self",
                "power_count": {"zone": "graveyard", "of": "opponents"},
                "toughness_count": {"zone": "graveyard", "of": "opponents"},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("reveal_until", {
                "criteria": {"type": "land"}, "count": 1, "scope": "each_opponent",
                "hit_destination": "graveyard", "rest_destination": "graveyard",
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group", "controller": "you"}},
        ),
    ]


register("Consuming Aberration", _consuming_aberration)
