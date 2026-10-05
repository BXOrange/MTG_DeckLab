from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _transmogrify() -> list[AbilitySpec]:
    """Exile target creature. That creature's controller reveals cards
    from the top of their library until they reveal a creature card. That
    player puts that card onto the battlefield, then shuffles the rest
    into their library.

    — MEC-12 (cEDH Kinnan). Transmogrify's own exile-mode sibling of
    Polymorph, sharing the same new effect (`mode="exile"` — no "can't be
    regenerated" clause to carry, since exile isn't destruction to begin
    with).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_exile_then_controller_reveal_creature", {
                "target_kind": "creature", "mode": "exile", "criteria": "Creature",
            })],
        ),
    ]


register("Transmogrify", _transmogrify)
