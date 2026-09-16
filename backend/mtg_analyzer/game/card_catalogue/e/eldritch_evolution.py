from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eldritch_evolution() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Search your library for a creature card with mana value X or less, where
    X is 2 plus the sacrificed creature's mana value. Put that card onto the
    battlefield, then shuffle. Exile Eldritch Evolution.

    — Eldritch Evolution. The additional cost (RULE 601.2b) was already
    modeled; what was missing is that nothing *remembered what was
    sacrificed*. `StackItem.x` only ever threads a spell's announced {X},
    so the sacrificed permanent's mana value now gets its own channel
    (`GameObject.sacrificed_cost_mana_value`, stamped by `GameEngine.
    _pay_additional_cast_cost` right before the victim leaves) and
    `SearchLibraryEffect.mana_value_from` binds it into the search criteria
    at resolution time. With no cost paid it fails closed to "nothing
    matches" rather than searching unrestricted.

    "Exile Eldritch Evolution." is its own replacement of the normal
    graveyard destination — the shipped `ExileEffect` self mode
    (``target_kind=None``, no target), which `RulesEngine.resolve_top_of_
    stack` already honours by *not* also routing the card to the graveyard.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": {"type": "Creature"},
                    "destination": "battlefield",
                    "mana_value_from": {"source": "sacrificed_cost", "plus": 2, "cmp": "le"},
                }),
                EffectSpec("exile", {"target_kind": None}),
            ],
            additional_cost={"sacrifice": "creature"},
        ),
    ]


register("Eldritch Evolution", _eldritch_evolution)
