from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _corpse_augur() -> list[AbilitySpec]:
    """When this creature dies, you draw X cards and you lose X life, where X is the number of creature cards in target player's graveyard.

    — PLAY-ALL Step 2 (Eternal Might). `choose_targets` announces the player (RULE 601.2c) and a `bind` measures
    the creature cards in *that* player's graveyard (a structured graveyard selector counted as the previous
    clause's player) into a draw and a life loss for you.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "choose_targets", "params": {"kinds": ["player"]}},
                {"type": "bind", "params": {
                    "name": "n",
                    "amount": {"kind": "count_selector", "of": "previous_player", "selector": {
                        "zone": "graveyard", "of": "you", "filter": {"card_type": "creature"},
                    }},
                    "effects": [
                        {"type": "draw", "params": {"count": "$n"}},
                        {"type": "lose_life", "params": {"amount": "$n"}},
                    ],
                }},
            ]})],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Corpse Augur", _corpse_augur)
