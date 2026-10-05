from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gifts_ungiven() -> list[AbilitySpec]:
    """Search your library for up to four cards with different names and
    reveal them. Target opponent chooses two of those cards. Put the
    chosen cards into your graveyard and the rest into your hand. Then
    shuffle.

    — MEC-41. Intuition's own two-phase `intuition_search`/`RulesEngine.
    _request_intuition` shape, generalized with ``search_optional``/
    ``distinct_names``/``chosen_count``/``chosen_destination``/
    ``rest_destination`` — see that method's own docstring for exactly how
    Gifts Ungiven's shape differs from Intuition's (2 chosen instead of 1,
    and the chosen/rest destinations swapped — Gifts Ungiven's opponent
    pick sends the *chosen* pair to the graveyard and the *rest* to the
    searcher's hand, the mirror image of Intuition's "chosen → hand, rest
    → graveyard").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("intuition_search", {
                "count": 4, "search_optional": True, "distinct_names": True,
                "chosen_count": 2, "chosen_destination": "graveyard",
                "rest_destination": "hand",
            })],
        ),
    ]


register("Gifts Ungiven", _gifts_ungiven)
