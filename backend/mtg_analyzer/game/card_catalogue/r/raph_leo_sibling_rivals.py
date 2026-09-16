from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _raph_and_leo_sibling_rivals() -> list[AbilitySpec]:
    """Whenever Raph & Leo attack, if it's the first combat phase of the
    turn, untap one or two target attacking creatures. After this phase,
    there is an additional combat phase.

    MEC-28: the same RULE 603.4 intervening-if extra-combat template as
    Finest Hour/Karlach, Fury of Avernus/Raiyuu, Storm's Edge (all four now
    parser-`MODELED`) — hand-authored here only because of its own
    remaining gap, a genuine RULE 601.2c "N or M target X" range. ENG-30
    built that primitive (`targeting.TargetSpec.count_max`) — this entry now
    uses the real "one or two" range (``count=1, count_max=2``) instead of
    the single-mandatory-target simplification it shipped with.

    Still hand-authored, not deleted in favor of the oracle-text parser: the
    parser's shared multi-target grammar (`catalogue.handlers.
    _MULTI_TARGET_ROWS`) has no row for a *targeted* "attacking creatures"
    phrase — only the untargeted mass-selector "untap all attacking
    creatures" form ENG-29 built. Adding one is real, separate scope (a new
    row plus threading a `creature_filter` through `_multi_target_params`,
    which has no such param today) that only this one card would exercise;
    left for whenever a second real card needs it rather than built
    speculatively here.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "tap",
                    {
                        "target_kind": "creature", "creature_filter": {"attacking": True}, "untap": True,
                        "count": 1, "count_max": 2,
                    },
                    condition={"is_first_combat_phase": True},
                ),
                EffectSpec("extra_combat_phase", {}, condition={"is_first_combat_phase": True}),
            ],
            trigger={"event": "ATTACKS", "condition": {"subject": "self"}},
        ),
    ]


register("Raph & Leo, Sibling Rivals", _raph_and_leo_sibling_rivals)
