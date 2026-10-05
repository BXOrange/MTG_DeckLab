from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _malakir_rebirth() -> list[AbilitySpec]:
    """Choose target creature. You lose 2 life. Until end of turn, that
    creature gains "When this creature dies, return it to the battlefield
    tapped under its owner's control."

    — Eliferate deck batch. A single-target spell (the life loss is
    untargeted, so the *grant* carries the one real RULE 115 target): the
    granted ability is `grant_triggered_ability` (RULE 613.7f, the same
    shape `Kaldra Compleat`'s own quoted grant uses) at
    ``duration="end_of_turn"`` rather than a printed permanent's standing
    grant, wrapping the new `return_self_from_graveyard_untargeted` —
    `effects.ReturnSelfFromGraveyardEffect`'s ``obj=None`` fallback to its
    own ``source``, which `continuous.py`'s layer-6 grant machinery binds
    fresh per affected object, so "it" is always whichever creature the
    grant landed on.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("lose_life", {"amount": 2}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "target_kind": "creature",
                    "static": {
                        "type": "grant_triggered_ability",
                        "params": {
                            "trigger_event": EventType.DIES,
                            "grant_effects": [
                                {"type": "return_self_from_graveyard_untargeted",
                                 "params": {"destination": "battlefield", "tapped": True}},
                            ],
                        },
                    },
                }),
            ],
        ),
    ]


register("Malakir Rebirth", _malakir_rebirth)
register("Malakir Rebirth // Malakir Mire", _malakir_rebirth)
