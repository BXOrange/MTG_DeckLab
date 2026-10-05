from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _zul_ashur_lich_lord() -> list[AbilitySpec]:
    """Ward—Pay 2 life.
    {T}: You may cast target Zombie creature card from your graveyard this turn.

    — PLAY-ALL Step 2 (Wretched Ranks). Ward is a printed keyword. The activation is Emry's
    `grant_flashback_to_target` with ``as_permission`` (a plain this-turn cast permission, no exile) over the
    ``graveyard_zombie_card`` target kind.
    """
    return [AbilitySpec(
        "activated",
        [EffectSpec("grant_flashback_to_target", {"target_kind": "graveyard_zombie_card", "as_permission": True})],
        cost={"taps_self": True},
    )]


register("Zul Ashur, Lich Lord", _zul_ashur_lich_lord)
