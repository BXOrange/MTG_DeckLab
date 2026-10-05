from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Serra Paragon (graveyard recursion once/turn) — PAR-60
# ===========================================================================
# Reuse of `graveyard_cast_permission` (Lurrus-shaped: MV cap + once/turn +
# its own ``exile_if_would_be_put_into_graveyard`` rider — exactly Serra's
# "it gains 'when put into a graveyard from the battlefield, exile it'").
# Documented simplification: the "play a land from your graveyard"
# alternative and the "you gain 2 life" tail are dropped.


def _serra_paragon() -> list[AbilitySpec]:
    """Flying (folds in).
    Once during each of your turns, you may play a land from your graveyard
    or cast a permanent spell with mana value 3 or less from your graveyard.
    If you do, it gains "When this permanent is put into a graveyard from
    the battlefield, exile it and you gain 2 life."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_cast_permission", {
                "max_mana_value": 3, "permanent_only": True, "once_per_turn": True,
                "exile_if_would_be_put_into_graveyard": True,
            })],
        ),
    ]


register("Serra Paragon", _serra_paragon)
