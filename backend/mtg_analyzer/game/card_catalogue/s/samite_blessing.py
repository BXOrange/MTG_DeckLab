from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _samite_blessing() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature has "{T}: The next time a source of your choice
    would deal damage to target creature this turn, prevent that damage."

    — The already-shipped RULE 613/RULE 714.2c layer-6 "grant an activated
    ability, affects=attached_permanent" static (Umbral Mantle/Squirrel
    Nest/Deadeye Navigator's own shape) — the granted ability's own effects
    get their `source` set to the *host* creature at grant time, so
    `request_prevent_damage_source`'s chooser/recipient resolution
    (defaulting to the host's own controller) behaves exactly like a real
    printed ability of the host's, no new primitive needed.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "enchant", "quality": "creature"}),
        AbilitySpec(
            "static",
            [EffectSpec("grant_activated_ability", {
                "affects": "attached_permanent",
                "cost": {"text": "{T}"},
                "grant_effects": [{
                    "type": "request_prevent_damage_source",
                    "params": {"target_kind": "creature", "amount": "all"},
                }],
            })],
        ),
    ]


register("Samite Blessing", _samite_blessing)
