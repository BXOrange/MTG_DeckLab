from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cemetery_gatekeeper() -> list[AbilitySpec]:
    """First strike
    When this creature enters, exile a card from a graveyard.
    Whenever a player plays a land or casts a spell, if it shares a card
    type with the exiled card, this creature deals 2 damage to that
    player.

    — Cemetery Gatekeeper. ``any_graveyard_card`` is the existing Regrowth/
    Reanimate-family target kind ("a graveyard" — RULE 115's "any single
    graveyard, whosever it is"); `ExileEffect.remember` stamps the exiled
    card's `instance_id` onto `GameObject.linked_exile_id`, and the new
    `EffectSpec.condition` key ``shares_type_with_linked_exile`` (RULE
    205.2a real card types only) gates the two payoff triggers — one per
    firing event (LAND_PLAYED/SPELL_CAST), the same "one spec per event"
    shape the "scry or surveil" compound trigger uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "any_graveyard_card", "remember": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"},
                        condition={"shares_type_with_linked_exile": True})],
            trigger={"event": "LAND_PLAYED", "condition": {"subject": "group"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"},
                        condition={"shares_type_with_linked_exile": True})],
            trigger={"event": "SPELL_CAST", "condition": {"subject": "group"}},
        ),
    ]


register("Cemetery Gatekeeper", _cemetery_gatekeeper)
