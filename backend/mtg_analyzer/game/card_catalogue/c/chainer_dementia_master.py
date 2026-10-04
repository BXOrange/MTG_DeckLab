from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chainer_dementia_master() -> list[AbilitySpec]:
    """All Nightmares get +1/+1.
    {B}{B}{B}, Pay 3 life: Put target creature card from a graveyard onto
    the battlefield under your control. That creature is black and is a
    Nightmare in addition to its other creature types.
    When Chainer leaves the battlefield, exile all Nightmares.

    — MEC-43 round 2. The anthem is reproduced verbatim (whole-card
    hand-authoring replaces the parser's own output, which would
    otherwise have claimed it alone). The reanimation ability reuses
    `grant_until`'s type/colour addition exactly like Rise from the Grave;
    "Pay 3 life" is a plain life-payment cost component. The leaves
    trigger reuses `exile_all_graveyards`'s sibling mass-exile shape via
    the new ``"exile"`` ``filter={"subtype": ...}`` key — a *battlefield*
    sweep this time, not a graveyard one.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "all_creatures", "subtype": "nightmare", "power": 1, "toughness": 1})],
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "any_graveyard_creature", "under_your_control": True,
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "type_change", "params": {"add_subtypes": ["Nightmare"]}},
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "color_change", "params": {"colors": ["B"], "set": False}},
                }),
            ],
            cost={"text": "{B}{B}{B}", "pay_life": 3},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"selector": "all_creatures", "filter": {"subtype": "nightmare"}})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Chainer, Dementia Master", _chainer_dementia_master)
