from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dual_strike() -> list[AbilitySpec]:
    """When you next cast an instant or sorcery spell with mana value 4
    or less this turn, copy that spell. You may choose new targets for
    the copy.
    Foretell {R}

    — Imodane deck batch. Foretell (RULE 702.166) is a RULE 702 keyword,
    auto-bound. "When you next cast … this turn" is a genuinely new
    primitive, `arm_spell_watcher`/`GameState.spell_watchers` — a one-shot
    watch for the *next* qualifying `SPELL_CAST` this turn, distinct from
    both an ordinary per-firing triggered ability (which only ever fires
    off a matching *object's own* event) and RULE 603.7's fixed-future-
    *step* `CreateDelayedTriggerEffect`. Its `then_specs` tail is the
    already-shipped `copy_spell` (RULE 707.10), applied against the
    just-cast spell's own stack item directly. **Documented
    simplification**: "you may choose new targets for the copy" isn't
    modeled — `CopySpellEffect` already keeps this simplification for
    every other consumer (Reiterate/Dualcaster Mage-shaped), so the copy
    keeps the original's targets.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("arm_spell_watcher", {
                "max_mana_value": 4, "card_types": ["instant", "sorcery"],
                "then_specs": [{"type": "copy_spell", "params": {}}],
            })],
        ),
    ]


register("Dual Strike", _dual_strike)
