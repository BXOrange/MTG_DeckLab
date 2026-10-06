from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shellshock() -> list[AbilitySpec]:
    """Target up to one creature per opponent and create one Mutagen for each creature actually dealt damage."""
    return [AbilitySpec("spell_effect", [
        EffectSpec("mark_event_log", {}),
        EffectSpec("damage", {"amount": "x", "target_kind": "creature_that_player_controls",
                              "per_player": "any_opponents", "optional": True}),
        EffectSpec("create_token", {"token_name": "Mutagen",
            "count": {"kind": "damaged_creatures_since_mark"}}),
    ])]


register('Shellshock', _shellshock)
