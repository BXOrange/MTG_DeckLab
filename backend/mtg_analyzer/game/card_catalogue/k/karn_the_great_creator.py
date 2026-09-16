from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _karn_the_great_creator() -> list[AbilitySpec]:
    """Activated abilities of artifacts your opponents control can't be
    activated.
    +1: Until your next turn, up to one target noncreature artifact
    becomes an artifact creature with power and toughness each equal to
    its mana value.
    -2: You may reveal an artifact card you own from outside the game or
    choose a face-up artifact card you own in exile. Put that card into
    your hand.

    — Karn, the Great Creator. First static already parser-claimed
    (`activation_prohibition`). The +1 needs two new primitives: RULE
    115.1c's `"noncreature_artifact"` target kind, and `type_change`'s new
    ``pt_selector="mana_value"`` (a dynamic sibling of its existing literal
    ``power``/``toughness`` ints), wrapped in the RULE 611.2b
    `GrantUntilEffect` (``duration="your_next_turn"``) — the same primitive
    "until end of turn" grants use, just a different sweep window. The -2
    is a **documented simplification**: this engine has no "outside the
    game" zone (a sideboard-like concept with no Commander legal use), so
    only its real half — reclaim a face-up artifact card from exile — is
    modeled; the "reveal … from outside the game" branch is dropped.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {
                "affects": "opponents_permanents", "card_type": "artifact",
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "type_change", "params": {
                    "add_types": ["creature"], "pt_selector": "mana_value",
                }},
                "duration": "your_next_turn",
                "target_kind": "noncreature_artifact",
                "optional": True,
                "count": 1,
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact"}, "destination": "hand", "zones": ["exile"],
            })],
            cost={"loyalty": -2},
        ),
    ]


register("Karn, the Great Creator", _karn_the_great_creator)
