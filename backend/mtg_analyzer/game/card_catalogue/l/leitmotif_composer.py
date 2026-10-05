from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _leitmotif_composer() -> list[AbilitySpec]:
    """Whenever this creature deals combat damage to a player, draw a card.
    Whenever you cast an instant or sorcery spell with mana value 5 or
    greater, create a token that's a copy of this creature.
    {2}{U}: Creatures named Leitmotif Composer can't be blocked this turn.

    Documented simplification: the {2}{U} mass-unblockable activated ability
    is not modeled."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self"},
                     "filter": {"is_player": True, "combat": True}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token_copy_of_named", {"card_name": "Leitmotif Composer"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
                "spell_mana_value_at_least": 5,
            },
        ),
    ]


register("Leitmotif Composer", _leitmotif_composer)
