from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cursed_mirror() -> list[AbilitySpec]:
    """{T}: Add {R}.
    As this artifact enters, you may have it become a copy of any creature on
    the battlefield until end of turn, except it has haste.

    — The copy happens only on entering (RULE 614.1c), never on tapping: the
    `enter_as_copy` replacement with ``until_end_of_turn`` (reverted by
    `GameEngine._step_cleanup`, RULE 514.2, via the same snapshot
    `become_copy_until_end_of_turn` uses). The "{T}: Add {R}." line needs no
    entry — `mana_abilities_for` reads it off oracle text — and, being part of
    the card's own text, it is correctly overwritten while the copy lasts
    (RULE 707.2) and back afterwards.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature", "add_keywords": ["Haste"],
                "until_end_of_turn": True, "optional": True,
            })],
        ),
    ]


register("Cursed Mirror", _cursed_mirror)
