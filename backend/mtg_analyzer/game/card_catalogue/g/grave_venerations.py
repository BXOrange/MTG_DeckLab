from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _grave_venerations() -> list[AbilitySpec]:
    """When this enchantment enters, you become the monarch.
    At the beginning of your end step, if you're the monarch, return up to
    one target creature card from your graveyard to your hand.
    Whenever a creature you control dies, each opponent loses 1 life and
    you gain 1 life.

    Registered wholesale, so all three clauses are authored. The end-step
    clause carries a trigger-level RULE 603.4 intervening-if
    (``active_if={"kind": "is_monarch"}``) — the same `static_conditions`
    vocabulary a static's own `active_if` uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_monarch", {})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "hand", "optional": True,
            })],
            trigger={
                "event": "STEP_BEGIN", "filter": {"step": "end"}, "phase_relation": "you",
                "active_if": {"kind": "is_monarch"},
            },
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"}),
                EffectSpec("gain_life", {"amount": 1}),
            ],
            trigger={
                "event": "DIES",
                "condition": {"subject": "group", "type": "creature",
                              "controller": "you", "other": False},
            },
        ),
    ]


register("Grave Venerations", _grave_venerations)
