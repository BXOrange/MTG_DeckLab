from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _takenuma_abandoned_mire() -> list[AbilitySpec]:
    """{T}: Add {B}.
    Channel — {3}{B}, Discard this card: Mill three cards, then return a
    creature or planeswalker card from your graveyard to your hand. This
    ability costs {1} less to activate for each legendary creature you
    control.

    — Eliferate deck batch, same Channel/`dynamic_reduction` shape as
    `Boseiju, Who Endures`/`Eiganjo, Seat of the Empire`. "Return a creature
    or planeswalker card from your graveyard to your hand" is untargeted
    RAW (no "target"), but reuses `ReturnFromGraveyardEffect`'s own new
    `graveyard_creature_or_planeswalker` kind (`targeting.py`'s
    `_GRAVEYARD_TYPE_FILTERS`) as a targeted choice instead — the same
    targeted-vs-untargeted-choice simplification this engine's whole
    Regrowth-adjacent recursion family already makes.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("mill", {"count": 3}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature_or_planeswalker",
                    "destination": "hand",
                }),
            ],
            cost={
                "text": "{3}{B}, Discard this card",
                "dynamic_reduction": {
                    "count_selector": "legendary_creatures_you_control",
                    "generic_per": 1,
                },
            },
        ),
    ]


register("Takenuma, Abandoned Mire", _takenuma_abandoned_mire)
