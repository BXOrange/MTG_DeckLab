from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _observed_stasis() -> list[AbilitySpec]:
    """Flash
    Enchant creature an opponent controls
    When this Aura enters, remove enchanted creature from combat. Then draw a card for each tapped creature its controller controls.
    Enchanted creature loses all abilities and can't attack or block.

    — PLAY-ALL (Scions & Spellcraft). Flash and Enchant are keywords. The ETB is the new `remove_from_combat` (RULE 506.4)
    over the Aura's host, then a `draw` measuring the tapped creatures of the host's controller (the new ``attached_controller``
    scope of the structured selector). The static is Opportunistic Dragon's `remove_all_abilities` + ``cant_attack``/``cant_block``.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("remove_from_combat", {"target_kind": "attached_permanent"}),
                EffectSpec("draw", {"count": {"kind": "count_selector", "selector": {
                    "zone": "battlefield", "of": "attached_controller", "filter": {"card_type": "creature", "tapped": True},
                }}}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("remove_all_abilities", {"affects": "attached_permanent"}),
                EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["cant_attack", "cant_block"]}),
            ],
        ),
    ]


register("Observed Stasis", _observed_stasis)
