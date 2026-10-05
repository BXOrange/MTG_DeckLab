from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eladamri_korvecdal() -> list[AbilitySpec]:
    """Eladamri, Korvecdal (Legendary Creature — Elf Warrior, {1}{G}{G})

    "You may look at the top card of your library any time.
    You may cast creature spells from the top of your library.
    {G}, {T}, Tap two untapped creatures you control: Reveal a card from
    your hand or the top card of your library. If you reveal a creature
    card this way, put it onto the battlefield. Activate only during your
    turn."

    The "look" permission is already parser-claimable; the "cast creature
    spells from the top" clause is the same standing static widened with
    `TopLibraryPermissionEffect.creature_only` (MEC-40). **Documented
    simplification** on the reveal ability: `SearchLibraryEffect`'s
    ``zones`` param has no "just the top card" source (only whole-zone
    scans — "library"/"graveyard"/"hand"/"exile"), so it's modeled as
    "reveal a card from your hand" only, dropping the "or the top card of
    your library" alternative — Eladamri's own standing "look at the top
    card any time" permission still lets a player plan around what that
    card is even though this ability can't reach it directly.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"look": True})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"cast_spells": True, "creature_only": True})],
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "search",
                    {
                        "criteria": {"type": "creature"}, "zones": ["hand"],
                        "destination": "battlefield", "optional": True, "count": 1,
                    },
                )
            ],
            cost={"text": "{G}, {T}, Tap two untapped creatures you control"},
        ),
    ]


register("Eladamri, Korvecdal", _eladamri_korvecdal)
