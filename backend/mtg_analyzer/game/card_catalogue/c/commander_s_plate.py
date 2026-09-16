from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _commanders_plate() -> list[AbilitySpec]:
    """Equipped creature gets +3/+3 and has protection from each color
    that's not in your commander's color identity.
    Equip commander {3}
    Equip {5}

    — MEC-43 round 4A. The static anthem+protection half needed one new
    `continuous.commander_color_identity` selector (the union of every
    ``is_commander`` object's printed `Card.color_identity` this player
    owns, searched live across every zone) plus a matching
    ``protection_from_colors_not_in_commanders_identity`` param on
    `grant_protection_static`'s existing layer-6 machinery — no card had
    ever needed a live read of "your commander's color identity" during a
    game before. The ordinary "Equip {5}" is the automatic keyword-catalogue
    ability every Equipment gets; "Equip commander {3}" (RULE 702.6e) is a
    genuinely *second*, coexisting Equip ability restricted to only ever
    attach to a commander, hand-authored here via `AttachEffect`'s new
    ``creature_filter`` param (a new ``"is_commander"``
    `combat.matches_object_filter` key). Along the way, fixed a real
    pre-existing parser bug this card's own text exposed: the "equip"
    keyword's plain COST-shape regex was greedy enough to swallow "Equip
    commander {3}" and report **that** as the ordinary Equip cost instead of
    the real {5} (`parser/oracle/catalogue/keywords.py`'s new
    ``_SPECIAL_REGEX["equip"]`` override, negative-lookahead-excluding
    "commander" as a qualifier word) — silently mispricing the plain Equip
    ability for both cache cards that print this template.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"power": 3, "toughness": 3, "affects": "attached_permanent"}),
                EffectSpec("grant_protection_static", {
                    "affects": "attached_permanent",
                    "protection_from_colors_not_in_commanders_identity": True,
                }),
            ],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("attach", {
                "target_kind": "creature", "creature_filter": {"is_commander": True},
            })],
            cost={"text": "{3}"},
        ),
    ]


register("Commander's Plate", _commanders_plate)
