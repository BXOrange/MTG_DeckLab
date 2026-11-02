from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hagra_mauling_hagra_broodpit() -> list[AbilitySpec]:
    """This spell costs {1} less to cast if an opponent controls no basic lands.
    Destroy target creature.

    — Commander Cube singleton batch. The destroy body is the parser's own claim. The cost reduction is the
    `cost_reduction` static gated by `opponent_count` with ``max: 0`` over the basic-land selector: that condition is
    "some one opponent has no basic lands", the same single-opponent reading as the printed "an opponent controls no
    basic lands" (RULE 601.2f, a reduction applied while the spell is cast). The back face, Hagra Broodpit, is a plain
    land ("enters tapped, {T}: Add {B}") and is carried by the card model's modal-DFC back face, not by an ability here.
    """
    basic_lands_of_opponent = {"zone": "battlefield", "of": "you", "filter": {"card_type": "land", "basic": True}}
    return [
        AbilitySpec("static", [EffectSpec("cost_reduction", {
            "affects": "self", "generic": 1,
            "active_if": {"kind": "opponent_count", "selector": basic_lands_of_opponent, "max": 0},
        })]),
        AbilitySpec("spell_effect", [EffectSpec("destroy", {"target_kind": "creature"})]),
    ]


register("Hagra Mauling // Hagra Broodpit", _hagra_mauling_hagra_broodpit)
