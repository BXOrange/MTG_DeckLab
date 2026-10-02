from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Structured group selector (PAR-120): noncreature artifacts the controller has.
_NONCREATURE_ARTIFACTS_YOU_CONTROL = {
    "zone": "battlefield", "of": "you",
    "filter": {"card_type": "artifact", "without_card_type": "creature"},
}


def _cyberdrive_awakener() -> list[AbilitySpec]:
    """Flying
    Other artifact creatures you control have flying.
    When this creature enters, each noncreature artifact you control becomes
    a 4/4 artifact creature until end of turn.

    — PLAY-ALL Step 2 (Counter Intelligence). Flying and the lord clause are
    the card's own keyword fold-in plus the parser's claimed `grant_keyword`
    over other artifact creatures, reproduced. The ETB is one `grant_until` ``type_change`` (Kamahl's
    resolve-time animate) with ``lock_group``: RULE 611.2c fixes the affected
    set when the trigger resolves — an artifact that enters later is not
    animated — and the structured ``affects`` selector picks the *noncreature*
    artifacts at that moment, before any of them has become a creature.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "card_type": "artifact", "keywords": ["flying"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "static": {"type": "type_change", "params": {
                    "add_types": ["creature"], "power": 4, "toughness": 4,
                    "affects": _NONCREATURE_ARTIFACTS_YOU_CONTROL,
                }},
                "duration": "end_of_turn", "target_kind": None, "lock_group": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Cyberdrive Awakener", _cyberdrive_awakener)
