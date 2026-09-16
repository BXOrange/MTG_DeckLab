from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _halvar_god_of_battle() -> list[AbilitySpec]:
    """Creatures you control that are enchanted or equipped have double
    strike.
    At the beginning of each combat, you may attach target Aura or Equipment
    attached to a creature you control to target creature you control.

    — Halvar, God of Battle. Brass Squire's clause widened to Auras, via the
    new ``attached_aura_or_equipment_you_control`` target kind — narrower
    than a bare "Equipment you control" in both directions: the attachment
    must already be on something, and that host must be yours.

    The static half uses the shipped layer-6 `grant_keyword` with the
    existing "enchanted or equipped" group selector, so it needed nothing
    new. The card is a DFC (// Sword of the Realms); registering the front
    face's own name is enough — `specs_for` falls back to the pre-"//" name.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "enchanted_or_equipped_creatures_you_control",
                "keywords": ["double strike"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_chosen", {
                "what_kind": "attached_aura_or_equipment_you_control",
                "to_kind": "creature_you_control",
            })],
            optional=True,
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}},
        ),
    ]


register("Halvar, God of Battle", _halvar_god_of_battle)
