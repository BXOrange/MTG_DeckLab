from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _akiri_fearless_voyager() -> list[AbilitySpec]:
    """Whenever you attack a player with one or more equipped creatures,
    draw a card.
    {W}: You may unattach an Equipment from a creature you control. If you
    do, tap that creature and it gains indestructible until end of turn.

    — Akiri, Fearless Voyager. Simplified: the engine fires RULE 508.1a's
    ATTACKS event once *per attacking creature*, not once per combat, so
    this is authored as "whenever an equipped creature you control attacks
    a player, draw a card" — a per-attacker trigger rather than a true
    once-per-combat one (attacking with 2+ equipped creatures in the same
    combat draws more than the printed one card; see `effect_binder.
    _trigger_condition`'s ``requires_equipped`` for the equipped check).
    The second ability is composition: the optional unattach snapshots the
    selected Equipment's host as an operand referent for the tap/pump rider.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"},
                     "requires_equipped": True},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("optional", {"effects": [
                {"type": "unattach", "params": {
                    "target_kind": "attached_equipment_you_control",
                }},
                {"type": "tap", "params": {
                    "target_kind": None,
                    "target_operand": {"of": "previous_target", "as": "host"},
                }},
                {"type": "pump", "params": {
                    "keywords": ["indestructible"],
                    "target_kind": None,
                    "target_operand": {"of": "previous_target", "as": "host"},
                }},
            ]})],
            cost={"mana": "{W}"},
        ),
    ]


register("Akiri, Fearless Voyager", _akiri_fearless_voyager)
