from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tezzeret_the_seeker() -> list[AbilitySpec]:
    """+1: Untap up to two target artifacts.
    −X: Search your library for an artifact card with mana value X or
    less, put it onto the battlefield, then shuffle.
    −5: Artifacts you control become artifact creatures with base power
    and toughness 5/5 until end of turn.

    — MEC-12 (cEDH Kinnan). Hand-authored whole (rather than reusing the
    parser's own claimed +1 spec) since that spec's ``target_kind`` reads
    "permanent" instead of "artifact" — fixed here rather than left
    inconsistent across the card's three abilities. The −X search is the
    existing `search` effect with the ``"x"`` sentinel
    (`RulesEngine._substitute_x` already walks a ``criteria`` dict's
    ``max_mana_value`` for exactly this). The −5 is `GrantUntilEffect`
    wrapping a `type_change` static scoped to ``affects="artifacts_you_
    control"`` — untargeted (``target_kind=None``), since nothing here is a
    RULE 115 target at all, just every artifact the activating player
    already controls.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {
                "target_kind": "artifact", "count": 2, "optional": True, "untap": True,
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact", "max_mana_value": "x"},
                "destination": "battlefield",
            })],
            cost={"loyalty": "-x"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "type_change", "params": {
                    "affects": "artifacts_you_control", "add_types": ["creature"],
                    "power": 5, "toughness": 5,
                }},
                "duration": "end_of_turn", "target_kind": None,
            })],
            cost={"loyalty": -5},
        ),
    ]


register("Tezzeret the Seeker", _tezzeret_the_seeker)
