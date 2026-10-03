from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sewer_nemesis() -> list[AbilitySpec]:
    """As this creature enters, choose a player.
    Sewer Nemesis's power and toughness are each equal to the number of cards in
    the chosen player's graveyard.
    Whenever the chosen player casts a spell, that player mills a card.

    — PLAY-ALL Step 2 (Oops! All Night's Whispers). The P/T clause is the parser's
    own `pt_cda` claim (``of: chosen`` graveyard count). The choice is Stuffy
    Doll's: an ETB `_request_choose_player` (any living player, yourself included)
    stashing `GameObject.chosen_player_id`. The cast trigger is a `SPELL_CAST` head
    with the new trigger key ``actor_is_chosen_player`` (the casting player must be
    the chosen one) over `mill` of the *caster* (``player_from_trigger_event``).
    **Simplification:** the choice is made by a trigger as it enters rather than as
    part of entering, so the P/T reads 0 for that moment.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("_request_choose_player", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
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
            [EffectSpec("mill", {"count": 1, "player_from_trigger_event": True})],
            trigger={"event": EventType.SPELL_CAST, "actor_is_chosen_player": True},
        ),
    ]


register("Sewer Nemesis", _sewer_nemesis)
