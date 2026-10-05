from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mnemonic_betrayal() -> list[AbilitySpec]:
    """Exile all opponents' graveyards. You may cast spells from among
    those cards this turn, and mana of any type can be spent to cast them.
    At the beginning of the next end step, if any of those cards remain
    exiled, return them to their owners' graveyards.
    Exile Mnemonic Betrayal.

    — Mnemonic Betrayal. The trailing "Exile ~." is the ordinary
    `ExileEffect` ``target_kind=None`` self mode (already claimed by the
    oracle-text parser — see `backend/tests/test_cube_batch_a1.py`'s
    ``test_mnemonic_betrayal_and_teferis_protection_self_exile_claimed``);
    only the graveyard-impulsive-cast body needed hand authoring, via
    `GraveyardImpulsiveCastEffect`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile_opponents_graveyards_impulsive_cast", {"mana_wildcard": "type"}),
                EffectSpec("exile", {"target_kind": None}),
            ],
        )
    ]


register("Mnemonic Betrayal", _mnemonic_betrayal)
