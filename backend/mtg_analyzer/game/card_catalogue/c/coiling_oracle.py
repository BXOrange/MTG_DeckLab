from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _coiling_oracle() -> list[AbilitySpec]:
    """When this creature enters, reveal the top card of your library. If it's a land card, put it onto the
    battlefield. Otherwise, put that card into your hand.

    — Peace Offering deck batch. Thrasios, Triton Hero's reveal-and-branch (`reveal_top` stashes the card as
    the ``revealed`` referent; `if_else` on its type) with an untapped land drop and a hand put (RULE 121.4:
    not a draw) for the miss.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "reveal_top", "params": {"whose": "you"}},
                {"type": "if_else", "params": {
                    "condition": {"kind": "is_card_type", "of": "revealed", "card_type": "land"},
                    "then": [{"type": "put_revealed_card", "params": {"destination": "battlefield"}}],
                    "else": [{"type": "put_revealed_card", "params": {"destination": "hand"}}],
                }},
            ]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Coiling Oracle", _coiling_oracle)
