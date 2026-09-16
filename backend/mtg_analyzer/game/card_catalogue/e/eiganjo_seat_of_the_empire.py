from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eiganjo_seat_of_the_empire() -> list[AbilitySpec]:
    """{T}: Add {W}.
    Channel — {2}{W}, Discard this card: It deals 4 damage to target
    attacking or blocking creature. This ability costs {1} less to
    activate for each legendary creature you control.

    — Eiganjo, Seat of the Empire. The mana ability is covered by the
    engine's mana model directly (no spec needed). Channel (RULE 702.29,
    `costs.ActivationCost.discard_self`) is modeled at its full, flat cost;
    "target attacking or blocking creature" collapses to a plain creature
    target (the same simplification `parser.oracle.catalogue.subgrammars`'s
    own "target attacking or blocking creature" row already uses
    elsewhere).

    "This ability costs {1} less to activate for each legendary creature you
    control." is a `costs.ActivationCost.dynamic_reduction` — the same field
    Mariposa Military Base's own per-rad-counter discount already used, now
    also accepting a **board**-reading ``count_selector`` (`continuous.
    count_selector`'s ``legendary_creatures_you_control``) instead of only a
    player-counter ``kind``. Re-evaluated live on every activation
    (`GameEngine._reduced_activation_mana`), so playing a legendary creature
    mid-turn immediately cheapens it, and `ManaCost.reduce_generic`'s own
    floor keeps the coloured {W} pip intact no matter how many legends are
    out. This is distinct from `continuous.cost_reduction_for`'s RULE 601.2f
    *spell*-cast discount, which never applied to an activated ability.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 4, "target_kind": "creature"})],
            cost={
                "text": "{2}{W}, Discard this card",
                "dynamic_reduction": {
                    "count_selector": "legendary_creatures_you_control",
                    "generic_per": 1,
                },
            },
        )
    ]


register("Eiganjo, Seat of the Empire", _eiganjo_seat_of_the_empire)
