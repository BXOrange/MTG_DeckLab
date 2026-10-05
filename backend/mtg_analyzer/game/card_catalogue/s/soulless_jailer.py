from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _soulless_jailer() -> list[AbilitySpec]:
    """Permanent cards in graveyards can't enter the battlefield.
    Players can't cast noncreature spells from graveyards or exile.

    — MEC-43. The first clause is `graveyard_library_entry_prohibition`'s
    new ``card_type="permanent"`` value (unconditionally true — everything
    this check is ever reached for is already a permanent card); the
    second is `cast_prohibition`'s new ``zones`` allowlist (the sibling of
    its existing ``hand_only`` single-zone exemption) combined with the
    already-shipped ``noncreature``/``scope="all"``.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_library_entry_prohibition", {"card_type": "permanent"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True, "zones": ["graveyard", "exile"],
            })],
        ),
    ]


register("Soulless Jailer", _soulless_jailer)
