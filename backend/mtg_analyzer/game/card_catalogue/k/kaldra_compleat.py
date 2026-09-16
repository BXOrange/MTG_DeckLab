from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kaldra_compleat() -> list[AbilitySpec]:
    """Living weapon
    Indestructible
    Equipped creature gets +5/+5 and has first strike, trample,
    indestructible, haste, and "Whenever this creature deals combat damage
    to a creature, exile that creature."
    Equip {7}

    — Kaldra Compleat. Living weapon and Indestructible come from the RULE
    702 keyword catalogue (Living Weapon's germ-token creation is now
    synthesized behaviourally too, see `effect_binder._keyword_triggered_
    abilities`). The granted "exile that creature" ability is a layer-6
    (RULE 613.7f) `grant_triggered_ability` onto the equipped creature —
    ``filter: {"combat": True, "is_player": False}`` narrows `DAMAGE` to
    combat damage dealt to a creature (not a player), and the per-firing
    "that creature" pronoun (ENG-13 — *which* creature was hit, a different
    `DAMAGE` field from the ``source_id`` that scopes *which grantee*
    reacts) is `ExileTriggerDamagedCreatureEffect`, reading the resolving
    event's own ``target_id`` off `GameContext.trigger_event` rather than a
    chosen target.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 5, "toughness": 5}),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent",
                    "keywords": ["first_strike", "trample", "indestructible", "haste"],
                }),
                EffectSpec("grant_triggered_ability", {
                    "affects": "attached_permanent",
                    "trigger_event": EventType.DAMAGE,
                    "filter": {"combat": True, "is_player": False},
                    "grant_effects": [{"type": "exile_trigger_damaged_creature", "params": {}}],
                }),
            ],
        )
    ]


register("Kaldra Compleat", _kaldra_compleat)
