from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _agadeem_s_awakening() -> list[AbilitySpec]:
    """Return from your graveyard to the battlefield any number of target creature cards that each have a different
    mana value X or less.

    — The sorcery *front* face of the MDFC (the back face is the land Agadeem, the Undercrypt, which the land-play path
    handles; same convention as Shatterskull Smashing). `return_from_graveyard` with ``any_number`` targets, the
    announced X as the mana-value ceiling (RULE 107.3 / 202.3) and ``distinct_mana_values`` for "each have a different
    mana value" -- validated with the other RULE 601.2c group limits (`targeting.target_group_within_budget`), so a
    target list with two cards of one mana value is refused at announcement.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "any_number": True, "optional": True,
                "max_mana_value": "x", "distinct_mana_values": True,
            }),
        ]),
    ]


register("Agadeem's Awakening // Agadeem, the Undercrypt", _agadeem_s_awakening)
register("Agadeem's Awakening", _agadeem_s_awakening)
