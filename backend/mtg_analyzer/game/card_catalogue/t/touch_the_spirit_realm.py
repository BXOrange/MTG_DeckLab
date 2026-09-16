from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _touch_the_spirit_realm() -> list[AbilitySpec]:
    """When this enchantment enters, exile up to one target artifact or
    creature until this enchantment leaves the battlefield.
    Channel — {1}{W}, Discard this card: Exile target artifact or
    creature. Return it to the battlefield under its owner's control at
    the beginning of the next end step.

    — MEC-42. The ETB half is the established O-Ring shape (`ExileEffect
    (remember=True)` + `ReturnLinkedExileEffect` on LEAVES_BATTLEFIELD,
    Shire Shirriff/Leonin Relic-Warder-shaped), just a new union target
    kind — `targeting`'s new ``"artifact_or_creature"``, the same "two
    single-type kinds getting their own combined kind" idiom
    ``artifact_or_enchantment`` already established. Channel (RULE
    702.29) needed no new primitive at all: its "Discard this card:" cost
    is already `ActivationCost.discard_self`, already fully wired for a
    hand-zone activation (`GameEngine.can_activate`'s own documented
    Channel/Cycling branch) — just never bound to a real card doing
    anything but Cycling before. Its own return clause reuses `Return
    LinkedExileEffect` again, this time fired from a plain
    `create_delayed_trigger` (``step="end", scope="any"``) rather than a
    LEAVES_BATTLEFIELD trigger, since nothing here is attached to a
    permanent still on the battlefield to fire that trigger.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "artifact_or_creature", "optional": True, "remember": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": "artifact_or_creature", "remember": True}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "any",
                    "effects": [{"type": "return_linked_exile", "params": {}}],
                    "description": "Touch the Spirit Realm: exiliertes "
                                   "Objekt zurückbringen",
                }),
            ],
            cost={"text": "{1}{W}, Discard this card"},
        ),
    ]


register("Touch the Spirit Realm", _touch_the_spirit_realm)
