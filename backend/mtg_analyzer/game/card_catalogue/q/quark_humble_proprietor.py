
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _quark_humble_proprietor() -> list[AbilitySpec]:
    'You can\'t sacrifice Treasure tokens.\nAt the beginning of each upkeep, create a Treasure token. (It\'s an artifact with "{T}, Sacrifice this token: Add one mana of any color.")'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('create_token', {"count": 1, "token_name": 'Treasure'})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'upkeep'}},
            raw_text='at the beginning of each upkeep, create a treasure token.',
        ),
        # RULE 701.17 / 101.2: only the Treasure tokens *its controller* controls (a rival's Treasures stay free).
        AbilitySpec(
            "static",
            [EffectSpec("sacrifice_prohibition", {
                "affects": {"zone": "battlefield", "of": "you", "filter": {}}, "subtype": "Treasure", "tokens": True,
            })],
            raw_text="you can't sacrifice treasure tokens.",
        ),
    ]


register('Quark, Humble Proprietor', _quark_humble_proprietor)
