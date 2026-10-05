from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _groundskeeper() -> list[AbilitySpec]:
    """{1}{G}: Return target basic land card from your graveyard to your hand.

    — PLAY-ALL Step 2 (World Shaper). The parser's own `return_from_graveyard`
    shape for "target land card", narrowed with the new graveyard target kind
    ``graveyard_basic_land`` (a `_GRAVEYARD_TYPE_FILTERS` suffix — "basic" in the
    printed type line).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_basic_land", "destination": "hand"})],
            cost={"text": "{1}{G}"},
        ),
    ]


register("Groundskeeper", _groundskeeper)
