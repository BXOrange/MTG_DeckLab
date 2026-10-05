from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _noble_heritage() -> list[AbilitySpec]:
    """Commander creatures you own have "When this creature enters and at
    the beginning of your upkeep, each player may put two +1/+1 counters
    on a creature they control. For each opponent who does, you gain
    protection from that player until your next turn." (You can't be
    targeted, dealt damage, or enchanted by anything controlled by that
    player.)

    — PAR-32 / MEC-62. Hand-authored on two counts: the compound "when ~
    enters **and** at the beginning of your upkeep" trigger is two
    *different* RULE 603.1/500.7 trigger families sharing one effect body
    (`_quoted_ability_grant_effects_list`'s own compound-event handling
    only ever fans out **one** event kind, e.g. "enters or leaves"), so
    this grants the same `grant_effects` twice — once on
    `ENTERS_BATTLEFIELD`, once on `STEP_BEGIN`/upkeep/``phase_relation:
    "you"``. And the body itself
    (`EachPlayerMayCounterThenProtectionEffect` + `PlayerShieldEffect`'s
    new `protected_from_player_id`) is a genuinely new interactive shape
    (a real per-player "may" this engine has no sequential chooser for
    yet) — see that effect's own docstring for the MVP simplification.
    """
    grant_effects = [{"type": "each_player_counter_then_protection", "params": {}}]
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("grant_triggered_ability", {
                    "affects": "commander_creatures_you_own",
                    "trigger_event": "ENTERS_BATTLEFIELD",
                    "grant_effects": grant_effects,
                }),
                EffectSpec("grant_triggered_ability", {
                    "affects": "commander_creatures_you_own",
                    "trigger_event": "STEP_BEGIN",
                    "filter": {"step": "upkeep"},
                    "phase_relation": "you",
                    "grant_effects": grant_effects,
                }),
            ],
        ),
    ]


register("Noble Heritage", _noble_heritage)
