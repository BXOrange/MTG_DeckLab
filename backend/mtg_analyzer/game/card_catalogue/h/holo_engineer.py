
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _holo_engineer() -> list[AbilitySpec]:
    'When this creature enters, create a 3/3 colorless Illusion artifact creature token.\nIf one or more tokens would be created under your control, that many 3/3 colorless Illusion artifact creature tokens are created instead.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('create_token', {"count": 1, "power": 3, "toughness": 3, "colors": [], "subtypes": ['Illusion'], "keywords": [], "is_artifact": True, "token_name": 'Illusion'})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='when ~ enters, create a 3/3 colorless illusion artifact creature token.',
        ),
        # RULE 614.1 / 111.5: every token creation under your control (not only creature tokens) is replaced by the
        # same amount of 3/3 colorless Illusion artifact creature tokens (`substitute_token`'s `from_any_tokens`).
        AbilitySpec(
            "replacement",
            [EffectSpec("substitute_token", {
                "from_any_tokens": True,
                "to": {
                    "token_name": "Illusion", "power": 3, "toughness": 3, "colors": [],
                    "subtypes": ["Illusion"], "keywords": [], "is_artifact": True,
                },
            })],
            raw_text="if 1 or more tokens would be created under your control, that many 3/3 colorless illusion artifact creature tokens are created instead.",
        ),
    ]


register('Holo-Engineer', _holo_engineer)
