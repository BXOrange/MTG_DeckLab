from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _curse_of_echoes() -> list[AbilitySpec]:
    """Enchant player
    Whenever enchanted player casts an instant or sorcery spell, each other player may copy that spell and may choose new targets for the copy they control.
    """
    return [AbilitySpec(
        "triggered",
        [EffectSpec("for_each", {
            "over": {"players": "each_other_player"},
            "effects": [{"type": "optional", "params": {
                "player": "target",
                "effects": [{"type": "copy_spell", "params": {
                    "spell_from_trigger_event": "instance_id",
                    "controller_from_target": True,
                    "choose_new_targets": True,
                }}],
            }}],
        })],
        trigger={
            "event": EventType.SPELL_CAST,
            "condition": {"subject": "player", "scope": "enchanted"},
            "spell_filter": {"card_type_any": ["instant", "sorcery"]},
        },
    )]


register("Curse of Echoes", _curse_of_echoes)
