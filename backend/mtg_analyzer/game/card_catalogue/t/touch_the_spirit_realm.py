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

    The entry ability exiles under RULE 610.3 with immediate return.
    Channel uses an ordinary delayed end-step return (RULE 603.7).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "artifact_or_creature", "optional": True, "until_source_leaves": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
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
