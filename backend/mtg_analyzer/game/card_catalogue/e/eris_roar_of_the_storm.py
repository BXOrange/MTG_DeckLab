from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Generic mana Eris's discount removes per distinct mana value among instants/sorceries in the graveyard.
_ERIS_REDUCTION_PER_VALUE = 2


def _eris_roar_of_the_storm() -> list[AbilitySpec]:
    """This spell costs {2} less to cast for each different mana value among instant and sorcery cards in your
    graveyard.
    Whenever you cast your second spell each turn, create a 4/4 red Dragon Elemental creature token with flying and
    prowess.

    — The trigger is the parser's own claim, reproduced. The discount is Delve/Affinity's `self_cost_reduction_for`
    ``generic``-times-``per`` shape (RULE 601.2f) with a new count selector,
    `distinct_mana_values.distinct_instant_sorcery_mana_values_in_graveyard` (RULE 202.3: cards sharing a mana value
    count once), so the discount scales with the graveyard's variety, not its size.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": _ERIS_REDUCTION_PER_VALUE,
                "per": "distinct_instant_sorcery_mana_values_in_graveyard",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "power": 4, "toughness": 4, "colors": ['R'], "subtypes": ['Dragon', 'Elemental'], "keywords": ['flying', 'prowess'], "token_name": 'Dragon Elemental'})],
            trigger={"event": EventType.SPELL_CAST, "condition": {'subject': 'you'}, "is_nth_spell_cast_this_turn": 2},
            raw_text='whenever you cast your second spell each turn, create a 4/4 red dragon elemental creature token with flying and prowess.',
        ),
    ]


register('Eris, Roar of the Storm', _eris_roar_of_the_storm)
