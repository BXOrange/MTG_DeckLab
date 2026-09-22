from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _solitude() -> list[AbilitySpec]:
    """Flash
    Lifelink
    When this creature enters, exile up to one other target creature. That
    creature's controller gains life equal to its power.
    Evoke — Exile a white card from your hand.

    — MEC-12 (cEDH staples 2). Flash/Lifelink are already-bound printed
    keywords. The life gain is a `bind` over the exiled creature's power
    (RULE 608.2h, last-known information — it is gone by now), paid to that
    creature's controller (`{"of": "previous_target", "as": "controller"}`):
    without a recipient an untargeted `gain_life` falls back to this
    creature's own controller. MEC-65 binds its
    printed exile-a-white-card Evoke cost through the shared RULE 702.74
    alternate-cast path. "Target
    creature" (unqualified by "you control"/"you don't control") already
    excludes the source itself in this engine's `targeting.py` (RULE
    115's own "another" reading, not a new exclusion), matching "up to one
    **other** target creature" for free.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile", {"target_kind": "creature", "optional": True}),
                EffectSpec("bind", {
                    "name": "power",
                    "amount": {"kind": "characteristic", "characteristic": "power", "of": "previous_target"},
                    "effects": [{"type": "gain_life", "params": {
                        "amount": "$power", "player": {"of": "previous_target", "as": "controller"},
                    }}],
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Solitude", _solitude)
