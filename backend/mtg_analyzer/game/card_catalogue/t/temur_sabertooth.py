from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# cEDH staples cube — batch B2
# ---------------------------------------------------------------------------


def _temur_sabertooth() -> list[AbilitySpec]:
    """{1}{G}: You may return another creature you control to its owner's
    hand. If you do, this creature gains indestructible until end of turn.

    — Temur Sabertooth. ENG-37 B6: `seq` of an *optional* (up-to-one)
    `return_to_hand` then an `if_else` — "if you do" is "a creature was
    returned", i.e. `is_card_type(creature, of: "previous_target")` (None,
    hence neither branch, when nothing was returned), and the `then` is a
    self-targeted `grant_until` of indestructible. Keeps the ability
    activatable with no other creature (the return target stays "up to
    one", so RULE 601.2c never blocks the activation).
    ``creature_you_control`` already excludes the ability's own source
    (`targeting.legal_targets`), so it reads as "another creature you
    control" with no extra plumbing.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("seq", {"effects": [
                {"type": "return_to_hand", "params": {
                    "target_kind": "creature_you_control", "optional": True,
                }},
                {"type": "if_else", "params": {
                    "condition": {"kind": "is_card_type", "of": "previous_target",
                                  "card_type": "creature"},
                    "then": [{"type": "grant_until", "params": {
                        "self_subject": True, "duration": "end_of_turn",
                        "static": {"type": "grant_keyword",
                                   "params": {"keywords": ["indestructible"]}},
                    }}],
                    "else": [],
                }},
            ]})],
            cost={"mana": "{1}{G}"},
        )
    ]


register("Temur Sabertooth", _temur_sabertooth)
