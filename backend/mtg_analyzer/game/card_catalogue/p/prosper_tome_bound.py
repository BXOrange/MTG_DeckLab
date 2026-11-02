
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _prosper_tome_bound() -> list[AbilitySpec]:
    'Deathtouch\nMystic Arcanum — At the beginning of your end step, exile the top card of your library. Until the end of your next turn, you may play that card.\nPact Boon — Whenever you play a card from exile, create a Treasure token.'
    return [
        AbilitySpec("triggered", [
            EffectSpec("exile_top_of_library", {"count": 1}),
            EffectSpec("grant_play_window_previous_exiled", {}),
        ], trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"}),
        *[AbilitySpec("triggered", [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={"event": event, "condition": {"subject": "you"}, "filter": {"from_exile": True}})
          for event in (EventType.SPELL_CAST, EventType.LAND_PLAYED)],
    ]


register('Prosper, Tome-Bound', _prosper_tome_bound)
