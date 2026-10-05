from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _glarb_calamitys_augur() -> list[AbilitySpec]:
    """Deathtouch
    You may look at the top card of your library any time.
    You may play lands and cast spells with mana value 4 or greater from
    the top of your library.
    {T}: Surveil 2.

    — Glarb, Calamity's Augur. Deathtouch comes from the RULE 702 keyword
    catalogue (Scryfall's own ``keywords`` array, folded in automatically
    regardless of registration — see `specs_for`), so only the top-library
    permission (`top_library_permission`, mana-value-gated via
    ``min_mana_value``) and the surveil activated ability need
    hand-authoring here.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {
                "look": True, "play_lands": True, "cast_spells": True, "min_mana_value": 4,
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("surveil", {"count": 2})],
            cost={"text": "{T}"},
        ),
    ]


register("Glarb, Calamity's Augur", _glarb_calamitys_augur)
