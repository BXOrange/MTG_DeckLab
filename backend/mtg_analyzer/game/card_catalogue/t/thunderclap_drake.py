from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Thunderclap Drake (arm-a-spell-watcher + commander-cast-count
# copy) — PAR-60
# ===========================================================================
# `CopySpellEffect` gained ``count_selector`` (copy count read live from a
# `continuous.count_selector`); the delayed "when you next cast" hook is the
# existing `arm_spell_watcher`. The ``commander_casts_this_game`` selector


def _thunderclap_drake() -> list[AbilitySpec]:
    """Flying.  Instant and sorcery spells you cast cost {1} less (folds in
    from the parser).
    {2}{U}, Sacrifice this creature: When you next cast an instant or sorcery
    spell this turn, copy it for each time you've cast your commander from
    the command zone this game. You may choose new targets for the copies.

    Documented simplification (shared with `CopySpellEffect`): the copies
    keep the original's targets rather than opening a new-target pick."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("arm_spell_watcher", {
                "card_types": ["instant", "sorcery"],
                "then_specs": [{
                    "type": "copy_spell",
                    "params": {"count_selector": "commander_casts_this_game"},
                }],
            })],
            cost={"text": "{2}{U}, Sacrifice ~"},
        ),
    ]


register("Thunderclap Drake", _thunderclap_drake)
