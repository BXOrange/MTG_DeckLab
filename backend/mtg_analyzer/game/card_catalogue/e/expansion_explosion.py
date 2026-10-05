from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _expansion_explosion() -> list[AbilitySpec]:
    """Expansion — Copy target instant or sorcery spell with mana value 4 or less. You may choose
    new targets for the copy.
    Explosion — {X}{U}{U}{R}{R}: Explosion deals X damage to any target. Target player draws X cards.

    — Jeskai Striker deck batch. Only the front half needs authoring: the Explosion half parses on
    its own (`damage` + `draw`, both X) once the card is cast as its back face. The front is
    `copy_spell` with the new ``max_mana_value`` spell-target ceiling (RULE 115 — a spell with mana
    value 5 or more is not a legal target). "May choose new targets" keeps the original's targets, the
    `CopySpellEffect` simplification every copy card here shares.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"], "max_mana_value": 4})],
        ),
    ]


register("Expansion // Explosion", _expansion_explosion)
