from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_ravnica() -> list[AbilitySpec]:
    "(As a Siege enters, choose an opponent to protect it. You and others can attack it. When it's defeated, exile it, then cast it transformed.)\nWhen this Siege enters, exile target nonland permanent an opponent controls that isn't exactly two colors."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('exile', {"target_kind": 'nonland_permanent_you_dont_control', "creature_filter": {'not_color_count': 2}})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='',
        ),
    ]


register('Invasion of Ravnica', _invasion_of_ravnica)


def _guildpact_paragon() -> list[AbilitySpec]:
    "Whenever you cast a spell that's exactly two colors, look at the top six cards of your library. You may reveal a card that's exactly two colors from among them and put it into your hand. Put the rest on the bottom of your library in a random order."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('inspect_top_choose', {'count': 6, 'max_picks': 1, 'criteria': {'color_count': 2}, 'action': 'reveal_library_to_hand', 'optional': True, 'rest_destination': 'library_bottom_random'})],
            trigger={"event": EventType.SPELL_CAST, "condition": {'subject': 'you'}, "spell_filter": {'color_count': 2}},
            raw_text='',
        ),
    ]


register('Guildpact Paragon', _guildpact_paragon)
