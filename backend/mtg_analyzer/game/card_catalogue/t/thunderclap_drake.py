from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Thunderclap Drake (one-shot turn trigger + commander-cast-count
# copy) — PAR-60
# ===========================================================================
# `CopySpellEffect` gained ``count_selector`` (copy count read live from a
# `continuous.count_selector`); the "when you next cast" hook is a one-shot
# `create_turn_trigger` (RULE 603.7a), so the copies go on the stack above the spell. The
# ``commander_casts_this_game`` selector


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
            [EffectSpec("create_turn_trigger", {
                "trigger": {
                    "event": "SPELL_CAST",
                    "condition": {"subject": "you"},
                    "spell_filter": {"card_type_any": ["instant", "sorcery"]},
                },
                "effects": [{
                    "type": "copy_spell",
                    "params": {
                        "spell_from_trigger_event": "instance_id",
                        "count_selector": "commander_casts_this_game",
                    },
                }],
                "once": True,
                "description": "when you next cast an instant or sorcery spell this turn, "
                               "copy it for each time you've cast your commander from the "
                               "command zone this game",
            })],
            cost={"text": "{2}{U}, Sacrifice ~"},
        ),
    ]


register("Thunderclap Drake", _thunderclap_drake)
