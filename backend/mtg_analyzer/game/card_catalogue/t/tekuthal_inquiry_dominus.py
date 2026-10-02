from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tekuthal_inquiry_dominus() -> list[AbilitySpec]:
    """Flying
    If you would proliferate, proliferate twice instead.
    {1}{U/P}{U/P}, Remove three counters from among other artifacts, creatures,
    and planeswalkers you control: Put an indestructible counter on Tekuthal.

    — PLAY-ALL Step 2 (Counter Intelligence). Flying is the keyword fold-in.
    The activated ability is now the parser's own claim: its cost needed
    `cost_text._FROM_SOURCE` widened to a list of types after "among"
    ("other artifacts, creatures, and planeswalkers"), parsed into
    `remove_counters_from = artifact_or_creature_or_planeswalker` plus the new
    `ActivationCost.remove_counters_other` (the source itself is no legal
    holder). The proliferate replacement is the `proliferate_twice` marker
    static, read by `ProliferateEffect` through
    `continuous.proliferate_multiplier` (two such permanents give four).
    **Simplification:** only `ProliferateEffect` is affected — it already applies
    to every counter-bearing permanent and player (no chooser), so twice simply
    runs the pass again.
    """
    return [
        AbilitySpec("static", [EffectSpec("proliferate_twice", {})]),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"count": 1, "kind": "indestructible"})],
            cost={"text": "{1}{U/P}{U/P}, Remove 3 counters from among other artifacts, creatures, and planeswalkers you control"},
        ),
    ]


register("Tekuthal, Inquiry Dominus", _tekuthal_inquiry_dominus)
