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
    **Documented simplification**: the colour change ("black and green")
    isn't modeled — `type_change`'s layer-4 params have no colour field
    (RULE 613's own layer 5 does colour; no manland in this catalogue sets
    it yet), so the animated creature keeps whatever colour identity the
    land already had (usually colourless).
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
