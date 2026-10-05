from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _finale_of_devastation() -> list[AbilitySpec]:
    """Search your library and/or graveyard for a creature card with mana
    value X or less and put it onto the battlefield. If you search your
    library this way, shuffle. If X is 10 or more, creatures you control
    get +X/+X and gain haste until end of turn.

    — MEC-12 (fifth pass): the "search library and/or graveyard" half
    reuses `SearchLibraryEffect`'s ``zones``/``criteria`` exactly like the
    oracle-text `search_zone_put` handler does, just with the search's own
    ``max_mana_value`` bound left as the ``"x"`` sentinel
    `RulesEngine._substitute_x` now knows to walk into a nested
    ``criteria`` dict (a fifth-pass primitive, alongside Meltdown's
    matching `filter` case); the bonus half is `Martial Coup`'s own
    `source_x_paid_at_least` `ConditionalEffect` gate wrapping a
    `creatures_you_control`-selector `PumpEffect`. Not built as a general
    oracle-text handler (unlike the plain single-zone "with mana value X
    or less" qualifier, which is): this card's own two-sentence shape —
    a conditional bonus keyed to the *same* spell's {X} as its search —
    is a singleton template cache-wide, the sanctioned hand-authoring
    escape valve rather than a family worth its own grammar yet.

    Simplified: the search always shuffles the library when it's among
    the search zones (the same `search_zone_put` simplification the
    oracle-text handler already documents — it doesn't track which zone
    the found card actually came from), so this always shuffles rather
    than only "if you search your library this way".
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": {"type": "Creature", "max_mana_value": "x"},
                    "destination": "battlefield",
                    "zones": ["library", "graveyard"],
                }),
                EffectSpec(
                    "pump",
                    {"power": "x", "toughness": "x", "keywords": ["haste"], "selector": "creatures_you_control"},
                    condition={"source_x_paid_at_least": 10},
                ),
            ],
        ),
    ]


register("Finale of Devastation", _finale_of_devastation)
