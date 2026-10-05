from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _swarmyard() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}: Regenerate target Insect, Rat, Spider, or Squirrel. (The next time it would be destroyed this turn, instead tap it, remove it from combat, and heal all damage on it.)
    """
    return [
        AbilitySpec(
            'activated',
            [
                EffectSpec('regenerate', {'creature_filter': {'subtype_any': ['Insect',
                                                                'Rat',
                                                                'Spider',
                                                                'Squirrel']}}),
            ],
            cost={'text': '{T}'},
        ),
    ]


register('Swarmyard', _swarmyard)
