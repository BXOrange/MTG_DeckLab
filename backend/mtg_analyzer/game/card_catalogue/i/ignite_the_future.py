from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ignite_the_future() -> list[AbilitySpec]:
    """Exile the top three cards of your library. Until the end of your next turn, you may play those cards. If this spell was cast from a graveyard, you may play cards this way without paying their mana costs.
    Flashback {7}{R} (You may cast this card from your graveyard for its flashback cost. Then exile it.)

    — Commander Cube singleton batch. The exile plus the end-of-next-turn play window is `ImpulsiveDrawEffect`; the
    free-cast rider is gated on the spell's own cast origin (`was_cast_from_graveyard`, RULE 601.2a) and reuses the
    PAR-167 casting window over the same pool (`exile_pool_from_created` bridges the two). Flashback is the keyword
    catalogue's own synthesized ability (RULE 702.34), so only the spell effect is authored here.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("seq", {"effects": [
            {"type": "impulsive_draw", "params": {"count": 3}},
            {"type": "exile_pool_from_created", "params": {}},
            {"type": "if_else", "params": {
                "condition": {"kind": "flag", "flag": "was_cast_from_graveyard"},
                "then": [{"type": "cast_window_exiled_pool", "params": {"free": True}}],
                "else": [],
            }},
        ]})]),
    ]


register("Ignite the Future", _ignite_the_future)
