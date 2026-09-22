from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tavern_brawler() -> list[AbilitySpec]:
    """Commander creatures you own have "At the beginning of your upkeep,
    exile the top card of your library. This creature gets +X/+0 until end
    of turn, where X is that card's mana value. You may play that card this
    turn."

    — PAR-32 / MEC-58. Hand-authored: the quoted body is a two-clause
    triggered ability whose second clause reads a value ("that card's mana
    value") off what the first clause just exiled — a resolve-time
    referent `_quoted_ability_grant_effects_list`'s single-effect-per-
    trigger recursion has no vocabulary for. Both clauses are existing
    primitives, composed as one granted trigger's ``grant_effects`` list
    (RULE 608.2 applies a trigger's own effects in printed order):
    `impulsive_draw` (`RulesEngine.exile_with_play_permission`,
    ``same_turn_only=True`` for "…this turn", not "…through your next
    turn") now also seeds `GameContext.created_objects` with the exiled
    card, and the `pump`
    is wrapped in a `bind` over that card's mana value (the `created` referent) for the
    "+X/+0" — both changes land in the shared primitives, not this card's own code, so
    any future card needing either shape reuses them for free.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("grant_triggered_ability", {
                    "affects": "commander_creatures_you_own",
                    "trigger_event": "STEP_BEGIN",
                    "filter": {"step": "upkeep"},
                    "phase_relation": "you",
                    "grant_effects": [
                        {"type": "impulsive_draw",
                         "params": {"count": 1, "same_turn_only": True}},
                        {"type": "bind", "params": {
                            "name": "mv",
                            "amount": {"kind": "characteristic", "characteristic": "mana_value",
                                       "of": "created"},
                            "effects": [{"type": "pump", "params": {"power": "$mv"}}],
                        }},
                    ],
                }),
            ],
        ),
    ]


register("Tavern Brawler", _tavern_brawler)
