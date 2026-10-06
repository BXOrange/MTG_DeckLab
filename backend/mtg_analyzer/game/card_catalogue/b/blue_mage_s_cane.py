from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _blue_mage_s_cane() -> list[AbilitySpec]:
    """Job select
    Equipped creature gets +0/+2, is a Wizard in addition to its other types, and has "Whenever this creature attacks, exile up to one target instant or sorcery card from defending player's graveyard. If you do, copy it. You may cast the copy by paying {3} rather than paying its mana cost."
    Spirit of the Whalaqee — Equip {2}

    — PLAY-ALL (Scions & Spellcraft). Job select (RULE 702.182a, new `_kw_job_select`: Living Weapon's create-then-attach
    with a 1/1 Hero) and Equip are keywords. The static is an attached anthem + Wizard `type_change` + a granted ATTACKS trigger:
    `exile` (an optional opponent-graveyard instant/sorcery) then `grant_conditional_cast_from_exile` with Gix's
    ``cost_override="{3}"``. **Simplification:** the exiled card itself — not a copy — is what may be cast for {3} (for as
    long as it stays in exile), and the graveyard is any opponent's rather than only the defending player's.
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
                        {"type": "exile", "params": {"target_kind": "opponent_graveyard_instant_or_sorcery", "optional": True}},
                        {"type": "grant_conditional_cast_from_exile", "params": {
                            "all_cards": True, "condition": {}, "cost_override": "{3}", "exiled_this_way": True,
                        }},
                    ],
                }),
            ],
        ),
    ]


register("Blue Mage's Cane", _blue_mage_s_cane)
