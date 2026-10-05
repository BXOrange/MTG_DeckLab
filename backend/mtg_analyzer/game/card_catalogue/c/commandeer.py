from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _commandeer() -> list[AbilitySpec]:
    """You may exile two blue cards from your hand rather than pay this
    spell's mana cost.
    Gain control of target noncreature spell. You may choose new targets
    for it. (If that spell is an artifact, enchantment, or planeswalker,
    the permanent enters under your control.)

    — MEC-12 (cEDH M-K). The alt cost is already parser-claimed for free
    (`reuse` confirms it, `AbilitySpec.alt_cost`'s existing
    ``exile_hand_card_color_count`` key). The real gain-control-of-a-
    *spell* effect is new: `GainControlOfSpellEffect`/`RulesEngine.
    gain_control_of_spell` — see its own docstring for why only
    `StackItem.controller_id` (not a battlefield zone-change) needs to
    move, and why the optional retarget runs *before* that flip.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("gain_control_of_spell", {})],
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"exile_hand_card_color_count": [2, "U"]},
        ),
    ]


register("Commandeer", _commandeer)
