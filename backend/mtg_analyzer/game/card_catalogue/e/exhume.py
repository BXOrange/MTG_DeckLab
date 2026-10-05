from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _exhume() -> list[AbilitySpec]:
    """Each player puts a creature card from their graveyard onto the
    battlefield.

    — PLAY-ALL Step 2 (Oops! All Night's Whispers). `return_from_graveyard` with
    the new ``each_player_pick``: every living player in turn order chooses one
    creature card from *their own* graveyard (one prompt at a time, the rest parked
    on `deferred_effects` — `SacrificeEffect`'s idiom) and it enters under their
    control. A player with no creature card is simply skipped.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "battlefield", "each_player_pick": True,
            })],
        ),
    ]


register("Exhume", _exhume)
