from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _unsubstantiate() -> list[AbilitySpec]:
    """Return target spell or creature to its owner's hand.

    — MEC-43. Reuses `RulesEngine.bounce_spell_or_permanent` (Sink into
    Stupor/Hullbreaker Horror's own "still on the stack" bounce,
    MEC-12 M-K) — that method is already fully generic (falls back to
    ordinary `return_to_hand` whenever the target *isn't* currently a
    spell on the stack), so only a new, narrower `targeting` union kind
    (``"spell_or_creature"``, the "target spell or ability" (ENG-26)
    idiom applied to a permanent instead of an ability) was needed, not a
    new resolve-time mechanism.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {
                "target_kind": "spell_or_creature", "spell_or_permanent": True,
            })],
        ),
    ]


register("Unsubstantiate", _unsubstantiate)
