from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _urzas_ruinous_blast() -> list[AbilitySpec]:
    """(You may cast a legendary sorcery only if you control a legendary
    creature or planeswalker.)
    Exile all nonland permanents that aren't legendary.

    — PLAY-ALL Step 2 (SpongeBob). The legendary-sorcery casting condition
    (RULE 205.4d) was not enforced anywhere (Jaya's Immolating Inferno
    documents the gap); here it is the spec's ``cast_condition`` with the new
    ``control_legendary_creature_or_planeswalker`` key in `condition_query.
    free_cast_condition_holds`, which `can_cast` already consults. The body is Evacuation's group form with `exile` instead of
    `return_to_hand`: a ``group`` over every player's battlefield filtered to
    ``without_card_type: land`` and ``nonlegendary``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile", {"group": {
                "zone": "battlefield", "of": "any",
                "filter": {"without_card_type": ["land"], "nonlegendary": True},
            }})],
            cast_condition={"control_legendary_creature_or_planeswalker": True},
        )
    ]


register("Urza's Ruinous Blast", _urzas_ruinous_blast)
