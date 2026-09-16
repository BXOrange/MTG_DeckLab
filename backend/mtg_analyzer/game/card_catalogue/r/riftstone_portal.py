from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _riftstone_portal() -> list[AbilitySpec]:
    """{T}: Add {C}.
    As long as this card is in your graveyard, lands you control have
    "{T}: Add {G} or {W}."

    — MEC-22's fifth "from the graveyard" card, and unlike Anger/Brawn/
    Filth/Valor/Wonder it grants a mana ability rather than a keyword
    (`grant_mana_ability` in place of `grant_keyword`, same
    ``"from_graveyard": True`` gate) onto lands rather than creatures
    (``affects="lands_you_control"``), and with no board-state gate of
    its own — unconditional once the card is in the graveyard. Its own
    printed "{T}: Add {C}." mana ability needs no `AbilitySpec` either,
    same reasoning as Brawn's own printed Trample: an ordinary printed
    mana ability is read directly by `mana_abilities.py`, not through
    this catalogue.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "lands_you_control",
                "mana": [{"G": 1}, {"W": 1}],
                "from_graveyard": True,
            })],
        ),
    ]


register("Riftstone Portal", _riftstone_portal)
