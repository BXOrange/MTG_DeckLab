from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _phyrexian_revoker() -> list[AbilitySpec]:
    """As this creature enters, choose a nonland card name.
    Activated abilities of sources with the chosen name can't be activated.

    — MEC-12 (cEDH staples/staples 2). The new free-text `ChooseCardName
    Replacement` (a fourth RULE 601.2b `enter_choice_effects` sibling of
    the creature-type/colour/named-mode pickers — naming any card isn't an
    enumerable option list) feeds `activation_prohibition`'s new
    `card_name_from_source` selector, the naming-choice sibling of that
    static's existing `subtype_from_source`/`color_from_source`. Unlike
    Pithing Needle below, this one is unconditional — no mana-ability
    carve-out at all, so naming a mana dork silences its mana ability too.
    The printed "nonland" restriction on the *choice itself* isn't
    enforced (this engine's naming choices are never validated against
    real card data — `RulesEngine._request_name_card` accepts any string
    the same way); naming a land simply matches nothing, same as any other
    name that happens not to be on the board.
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
            })],
        ),
    ]


register("Phyrexian Revoker", _phyrexian_revoker)
