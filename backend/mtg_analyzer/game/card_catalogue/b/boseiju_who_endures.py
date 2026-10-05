from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _boseiju_who_endures() -> list[AbilitySpec]:
    """{T}: Add {G}.
    Channel — {1}{G}, Discard this card: Destroy target artifact,
    enchantment, or nonbasic land an opponent controls. That player may
    search their library for a land card with a basic land type, put it
    onto the battlefield, then shuffle. This ability costs {1} less to
    activate for each legendary creature you control.

    — Eliferate deck batch. The mana ability is bound automatically off
    the printed "{T}: Add {G}." text. Same Channel/`dynamic_reduction`
    shape as `Eiganjo, Seat of the Empire`'s own per-legendary-creature
    discount (`costs.ActivationCost.dynamic_reduction`'s
    `legendary_creatures_you_control` count_selector). The destroy+search
    body is a new primitive, `effects.
    DestroyControllerMaySearchBasicLandEffect` — pairs `RulesEngine.destroy`
    (unlike Winds of Abandon's exile-then-search sibling, so an
    indestructible/regeneration-shielded target survives) with an
    *optional*, untapped basic-land search offered to the destroyed
    permanent's own controller. `target_kind` drops the "an opponent
    controls" restriction — the same documented simplification
    `ExileControllerSearchesBasicLandEffect` already uses (no target kind
    carries an ownership exclusion yet).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("destroy_controller_may_search_basic_land", {})],
            cost={
                "text": "{1}{G}, Discard this card",
                "dynamic_reduction": {
                    "count_selector": "legendary_creatures_you_control",
                    "generic_per": 1,
                },
            },
        ),
    ]


register("Boseiju, Who Endures", _boseiju_who_endures)
