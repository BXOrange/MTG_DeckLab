from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kediss_emberclaw_familiar() -> list[AbilitySpec]:
    """Whenever a commander you control deals combat damage to an
    opponent, it deals that much damage to each other opponent.
    Partner (You can have two commanders if both have partner.)

    — MEC-12 (cEDH M-K). The new top-level ``contributor_is_commander``
    trigger key (RULE 903's own designation, stamped onto the existing
    MEC-29 aggregate combat-damage event by `GameEngine.
    _apply_combat_damage` — the same "no single acting object, so the
    event carries the aggregate characteristic itself" reasoning as
    `contributor_power_at_least`/`contributor_subtype`, not a live
    per-object `_build_group_ok` filter, since this event names no
    instance to look one up on) combined with the new
    ``each_other_opponent`` `DealDamageEffect` selector (``each_opponent``
    minus whichever opponent the firing event itself already hit). Partner
    is a printed keyword, recognized independently of this entry.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "amount_from_trigger_event": "amount", "selector": "each_other_opponent",
            })],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "group", "controller": "you"},
                "contributor_is_commander": True,
            },
        ),
    ]


register("Kediss, Emberclaw Familiar", _kediss_emberclaw_familiar)
