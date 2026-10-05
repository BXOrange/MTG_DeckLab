from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _witchs_mark() -> list[AbilitySpec]:
    """You may discard a card. If you do, draw two cards.
    Create a Wicked Role token attached to up to one target creature you
    control. (If you control another Role on it, put that one into the
    graveyard. Enchanted creature gets +1/+1. When this token is put
    into a graveyard, each opponent loses 1 life.)

    — Imodane deck batch. The loot half is `pay_cost_then` (RULE 118.3),
    the same "discard a card. If you do, …" shape Formidable Speaker's
    ETB already uses. **Documented simplification**: the Role token
    (RULE 701.62, an Aura-shaped token type this engine has no synthesis
    support for — `synthesize_token_card` only builds Creature/Artifact
    tokens, not Enchantment-Aura ones) isn't modeled; the card's real
    functional value (the loot) is fully modeled.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("pay_cost_then", {
                "cost": "Discard a card",
                "effects": [{"type": "draw", "params": {"count": 2}}],
            })],
        ),
    ]


register("Witch's Mark", _witchs_mark)
