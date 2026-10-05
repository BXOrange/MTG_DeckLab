from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kari_zevs_expertise() -> list[AbilitySpec]:
    """Gain control of target creature or Vehicle until end of turn.
    Untap it. It gains haste until end of turn.
    You may cast a spell with mana value 2 or less from your hand without
    paying its mana cost.

    — Kari Zev's Expertise. The threaten half reuses `effects.
    GainControlUntilEndOfTurnEffect` (built for Zealous Conscripts,
    already bundling the control change/untap/haste grant) with
    ``target_kind="permanent"`` rather than a creature-only kind, so a
    Vehicle target (an artifact, not a creature until crewed) is reachable
    the same way — narrower than the printed "creature or Vehicle" (any
    artifact is technically eligible here, not just Vehicles), a one-word
    substitution rather than a dedicated Vehicle target kind for this one
    card.

    MEC-20 closed the second sentence — RULE 601.2f's "Expertise" cycle
    template ("you may cast a spell with mana value N or less from your
    hand without paying its mana cost", also on Sram's/Yahenni's/Baral's/
    Rishkar's Expertise), via the new `effects.FreeCastFromHandEffect` and
    the oracle-text handler that now claims the other four automatically
    (`parser/oracle/catalogue/handlers.py`'s ``free_cast_from_hand`` row) —
    this card stays hand-authored only for its first, threaten sentence.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("gain_control_until_eot", {"target_kind": "permanent"})],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("free_cast_from_hand", {"max_mana_value": 2})],
        ),
    ]


register("Kari Zev's Expertise", _kari_zevs_expertise)
