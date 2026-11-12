from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bigger_on_the_inside() -> list[AbilitySpec]:
    """Enchant artifact or land
    Enchanted permanent has "{T}: Target player adds two mana of any one color. The next spell they cast this turn has cascade." (When they cast their next spell, they exile cards from the top of their library until they exile a nonland card that costs less. They may cast it without paying its mana cost. They put the exiled cards on the bottom in a random order.)
    """
    return [AbilitySpec("static", [EffectSpec("grant_activated_ability", {
        "affects": "attached_permanent", "cost": {"taps_self": True},
        "grant_effects": [{"type": "add_mana", "params": {
            "colors": ["ANY"], "any_amount": 2, "target_kind": "player", "recipient": "target_player"}},
            {"type": "grant_next_spell_cascade", "params": {}}],
    })])]


register("Bigger on the Inside", _bigger_on_the_inside)
