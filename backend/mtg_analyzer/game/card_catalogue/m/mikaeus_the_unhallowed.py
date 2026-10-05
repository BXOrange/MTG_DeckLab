from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mikaeus_the_unhallowed() -> list[AbilitySpec]:
    """Whenever a Human deals damage to you, destroy it.
    Other non-Human creatures you control get +1/+1 and have undying.

    — Mikaeus, the Unhallowed. The anthem is `other_nonhuman_creatures_
    you_control` (`continuous.group_selector_objects`'s new branch — the
    negated-subtype sibling of the existing `other_creatures_you_control`/
    `nonlegendary_creatures_you_control`), carrying both the +1/+1 anthem
    and the undying keyword grant.

    The first clause needed two small additions of its own: a group-
    subject DAMAGE trigger scoped to the *player* recipient specifically
    (`effect_binder`'s new ``condition["recipient_is_you"]`` — the
    existing ``condition["recipient"]`` only ever matches a *permanent*
    recipient's controller, since `RulesEngine.deal_damage` stamps
    ``target_controller_id`` as ``None`` for a player target), and
    `effects.DestroyEffect`'s new ``target_from_trigger_event="source_id"``
    to destroy the Human that actually dealt the damage — a group-subject
    trigger has no single chosen creature the way a self-subject "when ~
    enters" trigger's implicit "it" would, so "it" here has to be read
    back off the firing DAMAGE event itself.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy", {"target_kind": None, "target_from_trigger_event": "source_id"})],
            trigger={
                "event": "DAMAGE",
                "condition": {"subject": "group", "subtypes": ["human"], "recipient_is_you": True},
            },
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "affects": "other_nonhuman_creatures_you_control", "power": 1, "toughness": 1,
                }),
                EffectSpec("grant_keyword", {
                    "affects": "other_nonhuman_creatures_you_control", "keywords": ["undying"],
                }),
            ],
        ),
    ]


register("Mikaeus, the Unhallowed", _mikaeus_the_unhallowed)
