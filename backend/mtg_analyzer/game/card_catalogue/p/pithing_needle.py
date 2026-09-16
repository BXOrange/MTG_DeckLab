from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pithing_needle() -> list[AbilitySpec]:
    """As this artifact enters, choose a card name.
    Activated abilities of sources with the chosen name can't be activated
    unless they're mana abilities.

    — MEC-12 (cEDH staples/staples 2), Phyrexian Revoker's own artifact
    sibling — same naming-choice mechanism, but unrestricted (any card, not
    just nonland) and with the mana-ability carve-out `activation_
    prohibition`'s ``except_mana_abilities`` rider already provides
    (Kasmina's Transmutation/Imprisoned in the Moon's own shape).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_card_name_on_enter", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {
                "affects": "all_permanents",
                "card_name_from_source": True,
                "except_mana_abilities": True,
            })],
        ),
    ]


register("Pithing Needle", _pithing_needle)
