from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _skyclave_apparition() -> list[AbilitySpec]:
    """When this creature enters, exile up to one target nonland, nontoken
    permanent you don't control with mana value 4 or less.
    When this creature leaves the battlefield, the exiled card's owner
    creates an X/X blue Illusion creature token, where X is the mana value
    of the exiled card.

    — MEC-12 (cEDH staples 2). Both clauses ride the O-Ring family's
    linkage — `ExileEffect(remember=True)` and the new
    `CreateTokenForLinkedExileEffect` (`ReturnLinkedExileEffect`'s
    token-creating sibling: same `linked_exile_id` read, but hands off to
    `GameContext.create_token` under the linked card's owner instead of
    returning it) — rather than ever returning the exiled card at all.
    `ExileEffect` gained its own `max_mana_value` this batch, the same
    target-offer-time cap `DestroyEffect` already had (`targeting.
    TargetSpec.max_mana_value`). `target_kind="nonland_permanent_you_dont_
    control"` doesn't itself exclude tokens (no ``exclude_tokens`` selector
    exists yet) — a narrow, documented simplification, the same shape as
    Leonin Relic-Warder's own `target_kind="permanent"` type-union
    simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "nonland_permanent_you_dont_control",
                "optional": True, "remember": True, "max_mana_value": 4,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token_for_linked_exile", {
                "colors": ["U"], "subtypes": ["Illusion"],
            })],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Skyclave Apparition", _skyclave_apparition)
