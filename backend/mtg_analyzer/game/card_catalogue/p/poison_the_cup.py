from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _poison_the_cup() -> list[AbilitySpec]:
    """Poison the Cup (Instant, {1}{B}{B})

    "Destroy target creature. If this spell was foretold, scry 2.
    Foretell {1}{B} (During your turn, you may pay {2} and exile this
    card from your hand face down. Cast it on a later turn for its
    foretell cost.)"

    `EffectSpec.condition`'s ``source_was_foretold`` key reads the
    `GameObject.foretold` marker set by the complete RULE 702.143 special
    action/cast path, so the scry rider fires after a real foretold cast.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"target_kind": "creature"}),
                EffectSpec("scry", {"count": 2}, condition={"source_was_foretold": True}),
            ],
        ),
        AbilitySpec(
            "keyword", [], keyword={"name": "foretell", "cost": "{1}{B}"},
        ),
    ]


register("Poison the Cup", _poison_the_cup)
