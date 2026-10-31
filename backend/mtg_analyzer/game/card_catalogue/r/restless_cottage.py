from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _restless_cottage() -> list[AbilitySpec]:
    """This land enters tapped.
    {T}: Add {B} or {G}.
    {2}{B}{G}: This land becomes a 4/4 black and green Horror creature
    until end of turn. It's still a land.
    Whenever this land attacks, create a Food token and exile up to one
    target card from a graveyard.

    — Eliferate deck batch. "Enters tapped" and the mana ability are both
    oracle-derived/auto-bound, needing no hand-authoring. The animation
    ability reuses the self-targeting `grant_until`/`type_change` shape
    the `Incubator` token's own transform already established (RULE
    613.7c, ``target_kind=None`` — "this land", no RULE 115 target).
    The colour change ("black and green") is a second `grant_until`
    over `color_change` (layer 5, RULE 613.4b).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None,
                "static": {
                    "type": "type_change",
                    "params": {
                        "add_types": ["creature"], "add_subtypes": ["Horror"],
                        "power": 4, "toughness": 4,
                    },
                },
            }),
             # RULE 613.4b: "black and green" replaces its colours (layer 5).
             EffectSpec("grant_until", {
                 "duration": "end_of_turn", "target_kind": None,
                 "static": {"type": "color_change", "params": {"colors": ["B", "G"], "set": True, "affects": "self"}},
             })],
            cost={"text": "{2}{B}{G}"},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {"count": 1, "token_name": "Food"}),
                EffectSpec("exile", {"target_kind": "any_graveyard_card", "optional": True}),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Restless Cottage", _restless_cottage)
