from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gate_to_the_afterlife() -> list[AbilitySpec]:
    """Whenever a nontoken creature you control dies, you gain 1 life. Then you may draw a card. If you do, discard a card.
    {2}, {T}, Sacrifice this artifact: Search your graveyard, hand, and/or library for a card named God-Pharaoh's Gift and put it onto the battlefield. If you search your library this way, shuffle. Activate only if there are six or more creature cards in your graveyard.

    — PLAY-ALL Step 2 (Eternal Might). The dies trigger is the parser's own claim (re-added here). The activation
    is a `search` over graveyard, hand and library for the named card, gated by an `activation_condition`
    (the shipped ``graveyard_card_type_count_at_least``: six creature cards in your graveyard).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("gain_life", {"amount": 1}),
                EffectSpec("optional", {"effects": [
                    {"type": "draw", "params": {"count": 1}},
                    {"type": "discard", "params": {"count": 1}},
                ]}),
            ],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "controller": "you", "other": False,
                              "filter": {"nontoken": True, "card_type": "creature"}},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"name": "God-Pharaoh's Gift"}, "zones": ["graveyard", "hand", "library"],
                "destination": "battlefield", "count": 1,
            })],
            cost={
                "text": "{2}, {T}, Sacrifice ~",
                "activation_condition": {
                    "kind": "graveyard_card_type_count_at_least", "types": ["creature"], "amount": 6,
                },
            },
        ),
    ]


register("Gate to the Afterlife", _gate_to_the_afterlife)
