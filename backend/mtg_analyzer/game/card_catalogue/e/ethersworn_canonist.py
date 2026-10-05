from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ethersworn_canonist() -> list[AbilitySpec]:
    """Each player who has cast a nonartifact spell this turn can't cast
    additional nonartifact spells.

    — MEC-43, `cast_prohibition`'s second shared-primitive cluster: a
    boolean-flag restriction rather than any mana-value comparison at
    all — "already cast a nonartifact spell this turn", a different shape
    from the literal/selector mana-value family Gaddock Teeg/Sanctum
    Prelate use. `GameState.nonartifact_spells_cast_this_turn` (new, the
    nonartifact-scoped sibling of `noncreature_spells_cast_this_turn`,
    incremented in lockstep by the same `RulesEngine._track_spell_cast`)
    backs a new `min_count_selector` param: prohibited once that count is
    >= 1 **for the casting player**, checked before the current cast's own
    increment lands (the same "already reflects the very spell" ordering
    every other `spells_cast_this_turn`-family check relies on, so a
    player's own *first* nonartifact spell is never wrongly caught). RULE
    613.6-adjacent ``scope="all"``: the restriction binds every player,
    Canonist's own controller included, exactly like Gaddock Teeg.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "nonartifact": True,
                "min_count_selector": "nonartifact_spells_cast_this_turn",
            })],
        ),
    ]


register("Ethersworn Canonist", _ethersworn_canonist)
