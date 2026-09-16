from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-43 round 4, cluster C: library / graveyard / search / tokens
# ---------------------------------------------------------------------------


def _syphon_mind() -> list[AbilitySpec]:
    """Syphon Mind (Sorcery, {3}{B})

    "Each other player discards a card. You draw a card for each card
    discarded this way."

    `DiscardEffect`'s new ``draw_per_discard`` param (MEC-43 round 4C)
    queues a ``draw`` as `discard_choice`'s own ``then_specs`` tail for
    every opponent asked to discard — see its own docstring in
    `effects.py` for why this rides that "if you do" tail instead of a
    same-resolution `GameContext` accumulator (`life_lost_this_way`'s
    idiom): a non-forced discard is interactive (the discarding player
    picks their own card), so the true count isn't known synchronously
    the way a destroy/life-loss effect's own count already is.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("discard", {
                "count": 1, "scope": "each_opponent", "draw_per_discard": True,
            })],
        )
    ]


register("Syphon Mind", _syphon_mind)
