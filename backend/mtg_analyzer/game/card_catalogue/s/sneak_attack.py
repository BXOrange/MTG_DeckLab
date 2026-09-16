from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sneak_attack() -> list[AbilitySpec]:
    """{R}: You may put a creature card from your hand onto the
    battlefield. That creature gains haste. Sacrifice the creature at the
    beginning of the next end step.

    — Sneak Attack. `CheatCreatureFromHandEffect` (`game/effects/core.py`)
    covers the whole line in one atomic effect: the RULE 701 "cheat into
    play", the haste grant, and arming the RULE 603.7 delayed sacrifice.
    The hand-card pick is auto-chosen — no chooser in this MVP,
    `RulesEngine.discard`'s established precedent for an un-targeted
    hand-card pick — rather than an interactive choice among several
    eligible creatures.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("cheat_creature_from_hand", {})],
            cost={"text": "{R}"},
        )
    ]


register("Sneak Attack", _sneak_attack)
