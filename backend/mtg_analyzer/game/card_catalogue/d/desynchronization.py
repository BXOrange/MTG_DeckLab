from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _desynchronization() -> list[AbilitySpec]:
    """Return each nonland permanent that's not historic to its owner's hand.
    (Artifacts, legendaries, and Sagas are historic.)

    — PLAY-ALL Step 2 (SpongeBob). Evacuation's mass `return_to_hand`
    (``group`` over every player's battlefield) with the filter spelled out
    for "nonland and not historic": ``without_card_type`` excludes land and
    artifact, ``without_subtype: saga`` excludes Sagas (a *subtype*, not a card
    type word), ``nonlegendary`` excludes legendaries (RULE
    700.6's three historic kinds).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {"group": {
                "zone": "battlefield", "of": "any",
                "filter": {
                    "without_card_type": ["land", "artifact"], "without_subtype": "saga", "nonlegendary": True,
                },
            }})],
        )
    ]


register("Desynchronization", _desynchronization)
