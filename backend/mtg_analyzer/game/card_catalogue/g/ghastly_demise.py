from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ghastly_demise() -> list[AbilitySpec]:
    """Destroy target nonblack creature if its toughness is less than or equal to
    the number of cards in your graveyard.

    — PLAY-ALL Step 2 (Oops! All Night's Whispers). The parser's nonblack-creature
    `destroy` (``creature_filter without_color B``) gated on an `amount_compare`
    (``le``): the target's toughness (`characteristic` operand, ``of: target``)
    against a `count_selector` over your graveyard, both read as the spell
    resolves. (The target is chosen without regard to the condition, as printed.)
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {
                "target_kind": "creature", "creature_filter": {"without_color": "B"},
            }, condition={
                "kind": "amount_compare", "op": "le",
                "left": {"kind": "characteristic", "of": "target", "characteristic": "toughness"},
                "right": {"kind": "count_selector", "selector": {"zone": "graveyard", "of": "you"}},
            })],
        ),
    ]


register("Ghastly Demise", _ghastly_demise)
