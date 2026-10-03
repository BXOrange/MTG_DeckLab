from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sewer_nemesis() -> list[AbilitySpec]:
    """As this creature enters, choose a player.
    Sewer Nemesis's power and toughness are each equal to the number of cards in
    the chosen player's graveyard.
    Whenever the chosen player casts a spell, that player mills a card.

    The RULE 614.12 choice is made before entry, including the controller.
    P/T and the cast trigger both read that chosen player's id.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_player_on_enter", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("pt_cda", {
                "affects": "self",
                "power_count": {"zone": "graveyard", "of": "chosen"},
                "toughness_count": {"zone": "graveyard", "of": "chosen"},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("mill", {"count": 1, "selector": "event_player"})],
            trigger={"event": EventType.SPELL_CAST, "actor_is_chosen_player": True},
        ),
    ]


register("Sewer Nemesis", _sewer_nemesis)
