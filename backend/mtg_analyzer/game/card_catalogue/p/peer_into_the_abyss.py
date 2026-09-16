from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _peer_into_the_abyss() -> list[AbilitySpec]:
    """Target player draws cards equal to half the number of cards in
    their library and loses half their life. Round up each time.

    — MEC-43 round 2. `DrawCardEffect`'s new ``count_selector=
    "half_target_library_round_up"`` and `LoseLifeEffect`'s new
    ``amount_from_half_target_life`` are the *targeted* siblings of the
    existing "half your own life" shapes (MEC-37's Doomsday), both scoped
    to whichever player the single "target player" resolves to rather
    than the caster. `LoseLifeEffect.previous_subject` reads that same
    resolved target back (`GameContext.previous_targets`) instead of
    declaring a second RULE 115 target of its own — the real card only
    targets once, for both verbs.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {
                    "target_kind": "player", "count_selector": "half_target_library_round_up",
                }),
                EffectSpec("lose_life", {
                    "previous_subject": True, "amount_from_half_target_life": True,
                }),
            ],
        )
    ]


register("Peer into the Abyss", _peer_into_the_abyss)
