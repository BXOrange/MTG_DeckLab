from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _helm_of_obedience() -> list[AbilitySpec]:
    """{X}, {T}: Target opponent mills a card, then repeats this process
    until a creature card or X cards have been put into their graveyard this
    way, whichever comes first. If one or more creature cards were put into
    that graveyard this way, sacrifice this artifact and put one of them
    onto the battlefield under your control. X can't be 0.

    — Helm of Obedience. The engine's first **repeat-until-a-predicate**
    loop: every other repetition primitive (mill N, draw N, proliferate) has
    its count fixed before it starts. Here X is only a *cap* and the real
    stopping condition is what the mill turned up, so the loop has to
    re-check after every iteration.

    Bounded on both sides by construction — X caps the iterations, an empty
    library ends it early — which is the property that makes having a
    "repeat until" primitive safe at all. "X can't be 0" falls out of the
    same guard.

    Note the reanimated creature arrives under **your** control (RULE
    110.2), not its owner's, and the Helm sacrifices itself only when a
    creature was actually hit (RULE 701.16c: sacrifice, so nothing can
    regenerate out of it).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("mill_until_creature", {"amount": "x", "target_kind": "player"})],
            cost={"text": "{X}", "taps_self": True},
        ),
    ]


register("Helm of Obedience", _helm_of_obedience)
