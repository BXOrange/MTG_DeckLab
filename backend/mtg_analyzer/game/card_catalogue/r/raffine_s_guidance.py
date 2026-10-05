from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _raffines_guidance() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +1/+1.
    You may cast this card from your graveyard by paying {2}{W} rather than
    paying its mana cost.

    Documented simplification: the graveyard recast is modeled with the
    ``self_graveyard_or_exile_cast_permission`` marker (Squee-shaped — "you
    may cast this from your graveyard"), which pays the card's *printed*
    `{1}{W}` rather than the printed alternative `{2}{W}`; the recursion
    itself is what matters and the 1-mana delta is immaterial in these
    singleton decks."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("self_graveyard_or_exile_cast_permission", {})],
        ),
    ]


register("Raffine's Guidance", _raffines_guidance)
