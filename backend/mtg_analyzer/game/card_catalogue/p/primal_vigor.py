from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _primal_vigor() -> list[AbilitySpec]:
    """If one or more tokens would be created, twice that many of those
    tokens are created instead.
    If one or more +1/+1 counters would be put on a creature, twice that
    many +1/+1 counters are put on that creature instead.

    — PLAY-ALL Step 2 (Hydranten). Doubling Season's two replacements with
    the scoping the printed text actually has: neither is "you"-scoped, so
    `double_tokens` takes the new ``any_controller`` flag (every player's
    tokens) and `double_counters` the new ``recipient="creature"`` (any
    creature, no controller test), narrowed to +1/+1 counters.
    """
    return [
        AbilitySpec(
            "replacement",
            [
                EffectSpec("double_tokens", {"any_controller": True}),
                EffectSpec("double_counters", {"kind": "+1/+1", "recipient": "creature"}),
            ],
        )
    ]


register("Primal Vigor", _primal_vigor)
