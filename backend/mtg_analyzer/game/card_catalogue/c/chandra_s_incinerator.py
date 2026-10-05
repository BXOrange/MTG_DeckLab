from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chandras_incinerator() -> list[AbilitySpec]:
    """This spell costs {X} less to cast, where X is the total amount of
    noncombat damage dealt to your opponents this turn.
    Trample
    Whenever a source you control deals noncombat damage to an opponent,
    this creature deals that much damage to target creature or
    planeswalker that player controls.

    — MEC-45 (Ojer cEDH's last gap). The cost reduction reuses
    `self_cost_reduction_for`'s existing "generic-times-count_selector"
    multiply-by-`per` shape (Delve/Affinity's own mechanism) — the only
    new piece is `GameState.noncombat_damage_to_opponents_this_turn`, a
    running per-player *amount* total (`RulesEngine.deal_damage`
    increments it directly on any noncombat hit against an opponent),
    registered as a `count_selector` value the same way every other
    per-turn tracker is. The trigger's amount half is already fully
    general (`DealDamageEffect.amount_from_trigger_event`, Imodane's own
    primitive); its target half needed two genuinely new pieces: a
    `requires_damage_to_opponent` trigger-condition predicate (the DAMAGE
    event's recipient must be some player other than this ability's own
    controller — the "group"/"controller": "you" check only ever scopes
    the *source*, not who was hit) combined with the DAMAGE event's own
    already-general ``"filter": {"combat": False}`` for "noncombat", and a
    wholly new `targeting.py` kind, ``creature_or_planeswalker_that_
    player_controls`` — "that player" is whichever opponent the *firing*
    trigger event actually named, not a fixed "opponent" role, so
    `legal_targets` needed a new ``trigger_event`` parameter threaded from
    `triggers_mixin.py`'s own two target-gathering call sites.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 1,
                "per": "noncombat_damage_to_opponents_this_turn",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "target_kind": "creature_or_planeswalker_that_player_controls",
                "amount_from_trigger_event": "amount",
            })],
            trigger={
                "event": "DAMAGE",
                "condition": {"subject": "group", "controller": "you"},
                "filter": {"combat": False},
                "requires_damage_to_opponent": True,
            },
        ),
    ]


register("Chandra's Incinerator", _chandras_incinerator)
