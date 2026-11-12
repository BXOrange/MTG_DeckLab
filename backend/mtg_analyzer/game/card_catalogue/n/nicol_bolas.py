"""Nicol Bolas, including the token copy offered by Fate Reforged."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nicol_bolas():
    """Flying
At the beginning of your upkeep, sacrifice Nicol Bolas unless you pay {U}{B}{R}.
Whenever Nicol Bolas deals damage to an opponent, that player discards their hand."""
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec("triggered", [EffectSpec("sacrifice_unless_pay", {"cost": "pay {U}{B}{R}"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"}),
        AbilitySpec("triggered", [EffectSpec("discard", {"whole_hand": True, "player_from_trigger_event": True})],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self"},
                     "requires_damage_to_opponent": True}),
    ]


register("Nicol Bolas", _nicol_bolas)
