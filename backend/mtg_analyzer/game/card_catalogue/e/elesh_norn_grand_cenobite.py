from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# cEDH staples cube — batch B3
# ---------------------------------------------------------------------------


def _elesh_norn_grand_cenobite() -> list[AbilitySpec]:
    """Vigilance. Other creatures you control get +2/+2. Creatures your
    opponents control get -2/-2.

    — Elesh Norn, Grand Cenobite. Vigilance is a keyword, already covered
    by the parser's keyword catalogue. The two-sided anthem is two
    independent ``anthem`` static effects on one card — one scoped
    ``"other_creatures_you_control"`` (the existing lord vocabulary), the
    other reusing `group_selector_objects`'s ``"opponents_permanents"``
    selector (built for Manglehorn's "Artifacts your opponents control
    enter tapped.") narrowed to creatures via the shared ``card_type``
    selector param — no new engine surface needed for either half.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "affects": "other_creatures_you_control", "power": 2, "toughness": 2,
                }),
                EffectSpec("anthem", {
                    "affects": "opponents_permanents", "card_type": "creature",
                    "power": -2, "toughness": -2,
                }),
            ],
        )
    ]


register("Elesh Norn, Grand Cenobite", _elesh_norn_grand_cenobite)
