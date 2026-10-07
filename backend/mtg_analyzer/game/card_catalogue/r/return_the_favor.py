from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _return_the_favor() -> list[AbilitySpec]:
    """Spree (Choose one or more additional costs.)
    + {1} — Copy target instant spell, sorcery spell, activated ability, or
    triggered ability. You may choose new targets for the copy.
    + {1} — Change the target of target spell or ability with a single
    target.

    — MEC-31, the ticket's own named card (`Ojer cEDH`). RULE 702.172a
    Spree — a genuine new modal shape, not RULE 700.2's "choose N or more"
    with a shared cost: every mode prices *itself*
    (`AbilitySpec.modes["mode_costs"]`, one raw mana-cost string per
    option, parallel to ``options``/``descriptions`` — the parser's own
    `catalogue/modal.split_spree_block` builds the same dict for a
    cache-wide Spree card; this one is hand-authored only for its first
    mode's effect body, not its modal shape). `effect_binder._build_mode_
    entries` folds ``mode_costs[i]`` onto ``spell_modes[i]["cost"]``;
    `GameEngine._modal_extra_cost` sums the chosen combination's own costs
    on top of the printed {R}{R}, consulted by `effective_cast_cost`/
    `can_cast`/`_auto_tap_for_cast_if_needed` and surfaced per legal-action
    combination by `_modal_cast_actions`/`_cast_action` (each combination
    locks independently when its own total isn't affordable).

    The second mode ("change the target…") is exactly the parser's own
    already-built `_change_target` handler output — `EffectSpec
    ("change_target", {"spell_or_ability": True})`, ENG-26's union
    spell-or-ability stack-item lookup, unchanged.

    The first mode targets both qualifying spells and activated/triggered
    abilities, using their corresponding copy primitive and optional targets.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "at_least": True,
                "mode_costs": ["{1}", "{1}"],
                "options": [
                    [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"], "target_kind": "spell_or_ability"})],
                    [EffectSpec("change_target", {"spell_or_ability": True})],
                ],
                "descriptions": [
                    "Copy target instant spell, sorcery spell, activated ability, "
                    "or triggered ability. You may choose new targets for the copy.",
                    "Change the target of target spell or ability with a single target.",
                ],
            },
        ),
    ]


register("Return the Favor", _return_the_favor)
