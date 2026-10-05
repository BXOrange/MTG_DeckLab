from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _protean_hulk() -> list[AbilitySpec]:
    """When this creature dies, search your library for any number of
    creature cards with total mana value 6 or less, put them onto the
    battlefield, then shuffle.

    — Needed a genuinely new `SearchLibraryEffect` primitive (MEC-12):
    every existing multi-pick search bounds each round by a fixed
    per-card ``max_mana_value`` in ``criteria``, but this is a *running
    total* shared across the whole open-ended pick — a creature that costs
    5 and one that costs 1 are both individually well under 6, but picking
    both exhausts the budget for a third. `SearchLibraryEffect.total_mana_
    value_budget` (`RulesEngine._request_search`/`_search_choice`/
    `_resume_search`, all three threading a `spent_mana_value`
    running total through the recursive multi-round loop) narrows each
    round's own eligible pool to whatever still fits the *remaining*
    budget, on top of `criteria`'s ordinary type filter — orthogonal to,
    and reusable alongside, a real per-card cap should some future card
    need both at once. "Any number" reuses the already-established
    ``count=99`` sentinel other open-ended searches use, since the real
    stopping condition here is the budget running out, not the count.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"}, "destination": "battlefield",
                "count": 99, "optional": True, "total_mana_value_budget": 6,
            })],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
        ),
    ]


register("Protean Hulk", _protean_hulk)
