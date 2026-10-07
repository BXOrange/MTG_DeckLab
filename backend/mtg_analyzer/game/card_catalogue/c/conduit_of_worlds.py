from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _conduit_of_worlds() -> list[AbilitySpec]:
    """You may play lands from your graveyard.
    {T}: Choose target nonland permanent card in your graveyard. If you haven't cast a spell this turn, you may cast
    that card. If you do, you can't cast additional spells this turn. Activate only as a sorcery.

    — PLAY-ALL Step 2 (Sultai Arisen). The land permission is the parser's own claim, reproduced. The activation is
    sorcery-speed and targets a nonland permanent card in your graveyard; `grant_flashback_to_target` with
    ``as_permission`` and ``during_resolution`` offers that card at its normal
    cost only while the ability resolves, gated on ``spells_cast_this_turn``
    being 0. ``lock_casting`` bars further spells this turn only if it is cast.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_cast_permission", {"lands_only": True})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec(
                "grant_flashback_to_target",
                {"target_kind": "graveyard_nonland_permanent", "as_permission": True, "lock_casting": True, "during_resolution": True},
                condition={"kind": "spells_cast_this_turn", "max": 0},
            )],
            cost={"taps_self": True, "sorcery_speed_only": True},
        ),
    ]


register("Conduit of Worlds", _conduit_of_worlds)
