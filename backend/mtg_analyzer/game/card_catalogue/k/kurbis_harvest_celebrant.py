from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kurbis_harvest_celebrant() -> list[AbilitySpec]:
    """Kurbis enters with a number of +1/+1 counters on it equal to the amount
    of mana spent to cast it.
    Remove a +1/+1 counter from Kurbis: Prevent all damage that would be dealt
    this turn to another target creature with a +1/+1 counter on it.

    — PLAY-ALL Step 2 (Hydranten). The enters-with-counters clause is read off
    the card's text since PARSER_VERSION 589 (`mana_spent_scale`: one counter per
    mana spent, `GameObject.mana_spent_to_cast`, applied by `_apply_entry_
    counters`). The ability is `prevent_damage_shield` (``amount: all``, the one-shot
    "this turn" shield) on a creature target filtered to ``has_counter_kind:
    +1/+1``; the plain ``creature`` target kind already excludes the source, which
    is "another".
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("prevent_damage_shield", {
                "amount": "all", "target_kind": "creature",
                "creature_filter": {"has_counter_kind": "+1/+1"},
            })],
            cost={"text": "Remove a +1/+1 counter from ~"},
        ),
    ]


register("Kurbis, Harvest Celebrant", _kurbis_harvest_celebrant)
