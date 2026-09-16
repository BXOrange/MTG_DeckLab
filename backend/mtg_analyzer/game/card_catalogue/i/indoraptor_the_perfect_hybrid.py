from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _indoraptor_the_perfect_hybrid() -> list[AbilitySpec]:
    """Bloodthirst X
    Menace
    Enrage — Whenever Indoraptor is dealt damage, choose an opponent at
    random. Indoraptor deals damage equal to its power to that player
    unless they sacrifice a nontoken creature of their choice.

    Simplified: "at random" becomes an ordinary target choice — a real
    choice instead of randomness has no rules-relevant difference here and
    is never worse for the chosen opponent — and the "unless they
    sacrifice a nontoken creature" escape clause isn't modeled (that would
    need a genuinely new opponent-side interactive "unless" primitive; the
    existing `sacrifice_unless_pay`/`_request_pay_cost_then` family is
    always about *this ability's own controller* paying, not an
    opponent). The damage simply always happens. Bloodthirst is bind-on-
    load from the RULE 702 keyword catalogue, not hand-authored here.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage_equal_to_power", {"target_kind": "opponent"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
        ),
    ]


register("Indoraptor, the Perfect Hybrid", _indoraptor_the_perfect_hybrid)
