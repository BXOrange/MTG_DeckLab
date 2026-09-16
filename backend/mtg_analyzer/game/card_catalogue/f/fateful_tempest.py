from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Fateful Tempest (council's dilemma) — PAR-60
# ===========================================================================
# Reuse of the PAR-29 vote subsystem (`VoteEffect` / `_request_vote` with
# ``per_vote_specs``). The past branch is an ordinary composed mill + bind
# over the resolution's moved-card batch. The present branch reuses
# `impulsive_draw`, whose default window is exactly "until the end of your
# next turn".


def _fateful_tempest() -> list[AbilitySpec]:
    """Council's dilemma — Starting with you, each player votes for past or
    present. You mill a card for each past vote, then Fateful Tempest deals
    damage to each opponent equal to the total mana value of cards milled
    this way. Exile the top card of your library for each present vote.
    Until the end of your next turn, you may play the exiled cards."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("vote", {
                "options": ["past", "present"],
                "per_vote_specs": [
                    {"option": 0,
                     "effects": [{"type": "seq", "params": {"effects": [
                         {"type": "mill", "params": {"count": 1}},
                         {"type": "bind", "params": {
                             "name": "mv",
                             "amount": {"kind": "moved_sum", "characteristic": "mana_value"},
                             "effects": [{"type": "damage", "params": {
                                 "amount": "$mv", "selector": "each_opponent",
                             }}],
                         }},
                     ]}}],
                     "scale": 1},
                    {"option": 1,
                     "effects": [{"type": "impulsive_draw", "params": {"count": 1}}],
                     "scale": 1},
                ],
            })],
        ),
    ]


register("Fateful Tempest", _fateful_tempest)
