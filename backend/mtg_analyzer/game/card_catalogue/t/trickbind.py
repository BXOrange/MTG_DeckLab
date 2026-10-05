from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _trickbind() -> list[AbilitySpec]:
    """Split second (As long as this spell is on the stack, players can't
    cast spells or activate abilities that aren't mana abilities.)
    Counter target activated or triggered ability. If a permanent's
    ability is countered this way, activated abilities of that permanent
    can't be activated this turn. (Mana abilities can't be targeted.)

    — Trickbind. Shares Stifle's `counter_ability` core.

    **Documented simplifications**: RULE 702.61 Split Second (nothing in
    the codebase recognizes it yet — a cast-timing restriction, not a
    targeting/effect shape, so it's out of ENG-26's own scope) and the
    "activated abilities of that permanent can't be activated this turn"
    post-counter lockout (would need its own per-object, turn-scoped flag
    consulted by `GameEngine.can_activate` — a real but narrow primitive
    no other printed card needs yet) are both dropped; the core "counter
    target activated or triggered ability" line is real behaviour.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_ability", {})],
        )
    ]


register("Trickbind", _trickbind)
