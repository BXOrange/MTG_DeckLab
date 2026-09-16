from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sigarda_font_of_blessings() -> list[AbilitySpec]:
    """Sigarda, Font of Blessings (Legendary Creature — Angel, {2}{G}{W})

    "Flying
    Other permanents you control have hexproof.
    You may look at the top card of your library any time.
    You may cast Angel spells and Human spells from the top of your
    library."

    Flying and the hexproof anthem are already parser-claimable. The look
    permission is already-general `top_library_permission`. The cast
    permission reuses its own new ``subtypes`` filter (MEC-40, Eladamri's
    sibling ``creature_only`` narrowed to two named creature types
    instead) — union semantics, either subtype qualifies.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"look": True})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"cast_spells": True, "subtypes": ["Angel", "Human"]})],
        ),
    ]


register("Sigarda, Font of Blessings", _sigarda_font_of_blessings)
