from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rhystic_circle() -> list[AbilitySpec]:
    """{1}: Any player may pay {1}. If no one does, the next time a source
    of your choice would deal damage to you this turn, prevent that
    damage.

    — Rhystic Circle (MEC-30, Phase 7 — the one flagged genuinely large
    build). "Any player may pay {1}." is a *resolve-time* tax, not the
    already-shipped single-payer `TaxedDrawEffect`/`pay_cost_then` shape —
    every player independently gets a chance to pay, in turn order, and
    the shield only grants once literally everyone has declined; the
    first player to pay cancels the whole thing. New primitive:
    `RequestAllPlayersDeclineOrEffect`/`RulesEngine.request_all_players_
    decline_or` (a chain of ordinary single-player pay/decline choices,
    the aggregate-outcome mirror of PAR-13's `_request_each_player_pay_or`
    — that one applies its effect *per decliner*, this one applies it
    *once*, only if *every* player declined). The activation cost itself
    ({1}) is ordinary — unlike Mercenaries, only Rhystic Circle's own
    controller may activate this ability at all; it's the ability's own
    *effect* that reaches out to every player at the table.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("all_players_decline_or", {
                "cost": "{1}",
                "effects": [{"type": "request_prevent_damage_source", "params": {"amount": "all"}}],
            })],
            cost={"mana": "{1}"},
        ),
    ]


register("Rhystic Circle", _rhystic_circle)
