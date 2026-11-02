from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _indoctrination_attendant() -> list[AbilitySpec]:
    'Toxic 1 (Players dealt combat damage by this creature also get a poison counter.)\nWhen this creature enters, you may return another permanent you control to its owner\'s hand. If you do, create a 1/1 colorless Phyrexian Mite artifact creature token with toxic 1 and "This token can\'t block."'
    # The printed Toxic 1 is added by `specs_for` (parse_keywords) for every registered card.
    # "If you do" (RULE 608.2c) is "something was returned": an `if_else` on the optional
    # return's own referent, the Temur Sabertooth shape. Documented simplification: the
    # permanent is chosen as a RULE 115 target (offered at trigger time) although the
    # card does not target; `permanent_you_control` already excludes the source itself.
    # The token body is Skrelv's Hive's Phyrexian Mite verbatim.
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('seq', {"effects": [
                {"type": "return_to_hand", "params": {
                    "target_kind": "permanent_you_control", "optional": True,
                }},
                {"type": "if_else", "params": {
                    "condition": {"kind": "is_card_type", "of": "previous_target",
                                  "card_type": "permanent"},
                    "then": [{"type": "create_token", "params": {
                        "token_name": "Phyrexian Mite", "count": 1,
                        "power": 1, "toughness": 1, "colors": [],
                        "subtypes": ["Phyrexian", "Mite"], "is_artifact": True,
                        "parametric_keywords": [{"name": "toxic", "n": 1}],
                        "keywords": ["cant_block"],
                        "oracle_text": "Toxic 1\nThis token can't block.",
                    }}],
                    "else": [],
                }},
            ]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text='when ~ enters, you may return another permanent you control to its owner\'s hand. if you do, create a 1/1 colorless phyrexian mite artifact creature token with toxic 1 and "~ can\'t block."',
        ),
    ]


register('Indoctrination Attendant', _indoctrination_attendant)
