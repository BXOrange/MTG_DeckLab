from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hildibrand_manderville_gentleman_s_rise() -> list[AbilitySpec]:
    """Creature tokens you control get +1/+1.
    When Hildibrand Manderville dies, you may cast it from your graveyard as an Adventure until the end of your next turn.

    — PLAY-ALL (Scions & Spellcraft). The anthem is the parser's. The dies trigger is the new
    `grant_self_adventure_cast_from_graveyard`: a `temp_play_permissions` entry (so it lapses at the end of your next turn)
    restricted to the Adventure half from the graveyard (`GameState.temp_play_adventure_only`).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"power": 1, "toughness": 1, "affects": "creatures_you_control", "tokens": True})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_self_adventure_cast_from_graveyard", {})],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            optional=True,
        ),
    ]


register("Hildibrand Manderville // Gentleman's Rise", _hildibrand_manderville_gentleman_s_rise)
register("Hildibrand Manderville", _hildibrand_manderville_gentleman_s_rise)
