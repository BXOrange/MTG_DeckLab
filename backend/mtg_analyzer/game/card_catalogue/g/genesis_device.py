
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _genesis_device() -> list[AbilitySpec]:
    'When Genesis Device enters, search your library for a basic land card or Planet card, put it onto the battlefield tapped, then shuffle.\n{3}{G}{G}, {T}, Sacrifice Genesis Device: Sacrifice any number of lands you control, then search your library for up to that many land cards, put them onto the battlefield tapped, then shuffle. Activate only as a sorcery.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('search', {"criteria": {'or': [{'basic': True}, {'type': 'planet'}]}, "destination": 'battlefield_tapped'})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='when ~ enters, search your library for a basic land card or planet card, put it onto the battlefield tapped, then shuffle.',
        ),
        # RULE 701.17 / 701.19: the sacrificed-land count (any number, chosen on resolution) sizes the search: the
        # existing `choose_objects` ``then_that_many`` tail binds ``"x"`` to how many lands were actually sacrificed.
        AbilitySpec(
            "activated",
            [EffectSpec("choose_objects", {
                "action": "sacrifice", "what": "land", "count": "all", "optional": True,
                "prompt": "Beliebig viele Länder opfern",
                "then_that_many": {"effects": [{"type": "search", "params": {
                    "criteria": {"type": "land"}, "destination": "battlefield_tapped", "count": "x",
                }}]},
            })],
            cost={"text": "{3}{g}{g}, {t}, sacrifice ~", "sorcery_speed_only": True},
            raw_text="{3}{g}{g}, {t}, sacrifice ~: sacrifice any number of lands you control, then search your library for up to that many land cards, put them onto the battlefield tapped, then shuffle. activate only as a sorcery.",
        ),
    ]


register('Genesis Device', _genesis_device)
