from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _academy_ruins() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {1}{U}, {T}: Put target artifact card from your graveyard on top of your library.

    — PLAY-ALL (Living Energy). The mana ability is parsed from the printed text. The second is Unholy Grotto's
    `return_from_graveyard` with the ``library_top`` destination over the own-graveyard ``graveyard_artifact`` kind.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_artifact", "destination": "library_top"})],
            cost={"mana": "{1}{U}", "taps_self": True},
        ),
    ]


register("Academy Ruins", _academy_ruins)
