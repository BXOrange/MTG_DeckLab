from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _angels_grace() -> list[AbilitySpec]:
    """Split second
    You can't lose the game this turn and your opponents can't win the
    game this turn. Until end of turn, damage that would reduce your life
    total to less than 1 reduces it to 1 instead.

    — MEC-43 round 4E. Split second is a plain printed keyword (RULE
    702.60, already enforced by the RULE 702 keyword catalogue's cast-
    timing gate). "You can't lose the game this turn" reuses the existing
    `WinConditionEffect`/`_loss_prevented` machinery (built for a
    *permanent's* standing "you can't lose" static, e.g. Platinum Angel)
    via the new `RulesEngine.grant_cant_lose_this_turn` — installs one
    directly onto the caster's own `player_effects`, turn-scoped instead
    of standing. The damage floor is the new `RulesEngine.
    cap_damage_life_floor` (RULE 104.3a — `Player.player_effects`-scoped
    exactly like RULE 615's `prevent_damage_to_player`, just rewriting the
    amount to land on a fixed floor instead of subtracting a prevented
    chunk).

    **Documented simplification**: "your opponents can't win the game
    this turn" has no engine consequence today — nothing in this engine
    ever makes a player win the game outright (no Door to Nothingness/
    Barren Glory-shaped alternate win condition is modeled; every game
    ends by every-other-player-losing, which "you can't lose" above
    already fully covers for the games this card is actually cast in).
    Tracked nowhere as an open gap since no card needing an explicit win
    condition exists in this project yet.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("grant_cant_lose_this_turn", {}),
                EffectSpec("damage_life_floor", {"floor": 1}),
            ],
        ),
    ]


register("Angel's Grace", _angels_grace)
