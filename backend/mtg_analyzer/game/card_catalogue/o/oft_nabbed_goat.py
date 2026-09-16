from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _oft_nabbed_goat() -> list[AbilitySpec]:
    """{1}: Draw a card. Gain control of this creature and put a -1/-1
    counter on it. Only your opponents may activate this ability and only
    as a sorcery.
    When this creature dies, if it had one or more -1/-1 counters on it,
    its owner draws that many cards and each other player loses that much
    life.

    Authored: the opponent-only activated ability
    (`ActivationCost.only_opponents_may_activate` — new inverse of
    Mercenaries' `any_player_may_activate`; sorcery-speed) whose effect
    body is a plain activator draw, `gain_control_by_source`
    (``recipient="activator"``, new branch — control moves to whoever
    activated it, RULE 602.2b) and a self ``add_counters``; and the dies
    trigger — new `OwnerDrawOthersLosePerDyingCounterEffect`
    ("owner_draw_others_lose_per_dying_counter"), gated by the trigger-level
    ``dying_had_counter`` intervening-if.
    """
    return [
        AbilitySpec(
            "activated",
            [
                # `gain_control_by_source` runs first so the plain untargeted
                # ``draw`` / self ``add_counters`` below resolve for the
                # activator (RULE 602.2b "you" = whoever activated it), which
                # both read off the source's *current* controller. Printed
                # order is "Draw a card. Gain control …"; nothing between the
                # two clauses observes the pre-swap state, so the reorder has
                # no observable effect.
                EffectSpec("gain_control_by_source", {"recipient": "activator"}),
                EffectSpec("draw", {"count": 1}),
                EffectSpec("add_counters", {"count": 1, "kind": "-1/-1"}),
            ],
            cost={"mana": "{1}", "only_opponents_may_activate": True,
                  "sorcery_speed_only": True},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("owner_draw_others_lose_per_dying_counter", {"counter_kind": "-1/-1"})],
            trigger={"event": "DIES", "condition": {"subject": "self"},
                     "dying_had_counter": "-1/-1"},
        ),
    ]


register("Oft-Nabbed Goat", _oft_nabbed_goat)
