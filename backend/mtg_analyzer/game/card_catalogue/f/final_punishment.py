from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _final_punishment() -> list[AbilitySpec]:
    """Target player loses life equal to the damage already dealt to that
    player this turn.

    — MEC-43 round 4A. RULE 120.3's plain "damage dealt to a player" had no
    per-turn *amount* tracker at all — `GameState.combat_damage_to_players_
    this_turn` is a combat-only per-source hit-*set* ("was this player
    hit", never "how much") and `noncombat_damage_to_opponents_this_turn`
    is keyed by the *dealing* player and scoped to opponents only. New
    `GameState.damage_dealt_to_players_this_turn` (``{player_id: summed
    amount}``, combat and noncombat alike, from any source) closes that —
    incremented at both of `RulesEngine.deal_damage`'s player-damage sites
    (the ordinary branch and the infect-diverted one, since 702.90b
    redirects the life-loss consequence but the damage is still "dealt"),
    reset in `GameEngine.begin_turn`. `LoseLifeEffect`'s new
    ``amount_from_damage_dealt_this_turn`` reads it for whichever player
    this effect resolves against, the same "resolve the target first"
    shape ``amount_from_half_target_life`` (Peer into the Abyss, MEC-43
    round 2) already uses.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("lose_life", {
                "target_kind": "player", "amount_from_damage_dealt_this_turn": True,
            })],
        ),
    ]


register("Final Punishment", _final_punishment)
