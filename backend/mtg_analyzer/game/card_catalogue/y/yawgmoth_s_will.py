from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _yawgmoths_will() -> list[AbilitySpec]:
    """Until end of turn, you may play lands and cast spells from your
    graveyard.
    If a card would be put into your graveyard from anywhere this turn,
    exile that card instead.

    — Two new player-scoped, turn-limited primitives (MEC-12), neither
    expressible as a permanent-anchored static since the sorcery granting
    them is gone from every zone but graveyard/exile long before end of
    turn — there is no permanent left on the battlefield for the layer
    engine to scan. `GraveyardPlayPermissionThisTurnEffect` stamps
    `Player.graveyard_play_permission_until_turn`, read by
    `game/graveyard_cast.py`'s new `has_temporary_graveyard_play_
    permission` from both `GameEngine.can_play_land` (lands) and
    `_graveyard_cast_permission` (spells) — the first graveyard-cast
    permission source that has ever covered lands too, since Lurrus of the
    Dream-Den's own permanent-anchored grant explicitly excludes them.
    `GraveyardRedirectToExileEffect` stamps `Player.graveyard_redirect_
    to_exile_until_turn`, checked directly in `RulesEngine.
    _move_to_graveyard` — the one choke point every graveyard-bound move
    funnels through regardless of cause — against whichever player *owns*
    the moving card, since a card only ever enters its own owner's
    graveyard (RULE 404.4/700.4), the player-scoped, whole-turn sibling of
    the existing per-*object* `cast_via_graveyard_cast_permission_until_
    turn` check (Lurrus's own trailing "exile instead" clause) already
    sitting right above it. Together: anything cast/played this way that
    would otherwise die/be discarded/be countered this same turn is exiled
    instead of returning to the graveyard for a second recursion — the
    actual point of the card.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("graveyard_play_permission_this_turn", {}),
                EffectSpec("graveyard_redirect_to_exile_this_turn", {}),
            ],
        ),
    ]


register("Yawgmoth's Will", _yawgmoths_will)
