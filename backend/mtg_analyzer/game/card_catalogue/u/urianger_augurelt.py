from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _urianger_augurelt() -> list[AbilitySpec]:
    """Whenever you play a land from exile or cast a spell from exile, you gain 2 life.
    Draw Arcanum — {T}: Look at the top card of your library. You may exile it face down.
    Play Arcanum — {T}: Until end of turn, you may play cards exiled with Urianger Augurelt. Spells you cast this way cost {2} less to cast.

    Draw Arcanum privately shows the top card before the optional linked exile choice.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 2})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "spell_cast_from": ["exile"]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 2})],
            trigger={"event": EventType.LAND_PLAYED, "condition": {"subject": "you"}, "filter": {"from_exile": True}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("look_at_cards", {"target_kind": None}), EffectSpec("pay_cost_then", {
                "cost": "", "prompt": "Oberste Karte verdeckt ins Exil legen?",
                "effects": [{"type": "exile_top_of_library", "params": {"face_down": True, "track_exiled_with": True}}],
            })],
            cost={"text": "{t}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("play_cards_exiled_with_source", {"spell_discount": 2})],
            cost={"text": "{t}"},
        ),
    ]


register("Urianger Augurelt", _urianger_augurelt)
