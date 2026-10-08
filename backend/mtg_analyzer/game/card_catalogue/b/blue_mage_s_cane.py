from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _blue_mage_s_cane() -> list[AbilitySpec]:
    """Job select
    Equipped creature gets +0/+2, is a Wizard in addition to its other types, and has "Whenever this creature attacks, exile up to one target instant or sorcery card from defending player's graveyard. If you do, copy it. You may cast the copy by paying {3} rather than paying its mana cost."
    Spirit of the Whalaqee — Equip {2}

    The attack trigger targets the defending player’s graveyard and offers a real copy during resolution.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 0, "toughness": 2}),
                EffectSpec("type_change", {"affects": "attached_permanent", "add_subtypes": ["Wizard"]}),
                EffectSpec("grant_triggered_ability", {
                    "affects": "attached_permanent", "trigger_event": EventType.ATTACKS,
                    "grant_effects": [
                        {"type": "exile", "params": {"target_kind": "defending_graveyard_instant_or_sorcery", "optional": True}},
                        {"type": "copy_imprinted_card", "params": {"from_previous": True, "cast_cost": "{3}"}},
                    ],
                }),
            ],
        ),
    ]


register("Blue Mage's Cane", _blue_mage_s_cane)
