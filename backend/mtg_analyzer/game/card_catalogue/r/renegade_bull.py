from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _renegade_bull() -> list[AbilitySpec]:
    """Trample
    Whenever you cast an instant or sorcery spell, this creature gets +X/+0
    until end of turn, where X is that spell's mana value.
    Whenever this creature attacks, exile up to one target instant or sorcery
    card from your graveyard and copy it. You may cast the copy without
    paying its mana cost.

    Documented simplification: the attack-trigger flashback-copy clause is
    not modeled."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0,
                "amount_from_trigger_event": "mana_value",
                "amount_from_count_selector_axis": "power",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
            },
        ),
    ]


register("Renegade Bull", _renegade_bull)
