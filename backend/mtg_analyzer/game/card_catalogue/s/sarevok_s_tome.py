
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sarevok_s_tome() -> list[AbilitySpec]:
    "When this artifact enters, you take the initiative.\n{T}: Add {C}. If you have the initiative, add {C}{C} instead.\n{3}, {T}: Exile cards from the top of your library until you exile a nonland card. You may cast that card without paying its mana cost. Activate only if you've completed a dungeon."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('take_initiative', {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='when ~ enters, you take the initiative.',
        ),
        AbilitySpec("activated", [
            EffectSpec("dig_until", {"criteria": {"without_type": "land"}, "hit_destination": "cast_during_resolution", "rest_destination": "exile"}),
            EffectSpec("activation_condition_marker", {"condition": {"kind": "completed_dungeon"}}),
        ], cost={"mana": "{3}", "taps_self": True}),
    ]


register("Sarevok's Tome", _sarevok_s_tome)
