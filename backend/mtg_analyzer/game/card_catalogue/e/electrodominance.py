from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _electrodominance() -> list[AbilitySpec]:
    """Electrodominance deals X damage to any target. You may cast a spell
    with mana value X or less from your hand without paying its mana cost.

    — Electrodominance (MEC-20's own X-scaled "Expertise" cousin — RULE
    601.2f, same template as the Expertise cycle just with an announced
    {X} instead of a literal N, `effects.FreeCastFromHandEffect`'s
    ``criteria={"max_mana_value": "x"}``). Hand-authored rather than
    reached through the oracle-text parser's own ``damage`` handler:
    that handler's regex is digit-only (``NUMBER``, not ``COUNT_X``) and
    widening it to accept the "x" sentinel is a separate, real gap of its
    own (X-cost burn spells generally — Fireball/Rolling Thunder/Banefire-
    shaped, a family this ticket didn't size) rather than a one-line
    change safe to fold into this batch unreviewed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": "x", "target_kind": "any"})],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("free_cast_from_hand", {"max_mana_value": "x"})],
        ),
    ]


register("Electrodominance", _electrodominance)
