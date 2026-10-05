from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tinder_wall() -> list[AbilitySpec]:
    """Tinder Wall (Creature — Plant Wall, {G})

    "Defender (This creature can't attack.)
    Sacrifice this creature: Add {R}{R}.
    {R}, Sacrifice this creature: It deals 2 damage to target creature it's
    blocking."

    Defender and the plain sacrifice-for-mana ability are both already
    picked up independent of this registration (`parse_keywords`/
    `mana_abilities_for` scan the card's own oracle text directly, not
    gated by `card_registry` registration) — hand-authored only for
    the damage ability, which needs the new `"creature_source_is_
    blocking"` target kind (`game/targeting.py`) no existing card had.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"target_kind": "creature_source_is_blocking", "amount": 2})],
            cost={"text": "{R}, Sacrifice ~"},
        ),
    ]


register("Tinder Wall", _tinder_wall)
