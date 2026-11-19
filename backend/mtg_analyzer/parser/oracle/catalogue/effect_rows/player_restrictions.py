"""One-shot "target player can't ... this turn" restrictions (PAR-290).

RULE 611.2: a resolving effect that restricts a player lasts for the duration it names ("this turn") and binds exactly
the player chosen as it resolves. Both rows build `restrict_target_player_this_turn`, which parks a floating static
(``cast_prohibition`` / ``land_play_prohibition``) naming that player and expiring at end of turn:

* "Target player can't play lands this turn." (Solfatara, Turf Wound, Pardic Miner) -- RULE 305.1.
* "Target player can't cast creature spells this turn." (Cease-Fire) -- RULE 601.3a.

Anchored to "target player": a third-person "that player" / "its controller" names a referent an earlier clause chose
and stays unclaimed here.
"""

from __future__ import annotations

import re

from ...spec import EffectSpec
from .shared import EffectHandler, compile_clause

#: "creature" / "noncreature" / "instant or sorcery" -> the `cast_prohibition` params selecting those spells.
_SPELL_TYPE_PARAMS: dict[str, dict] = {
    "creature": {"spell_types": ["creature"]},
    "instant or sorcery": {"spell_types": ["instant", "sorcery"]},
}

_TARGET_PLAYER_CANT_PLAY_LANDS_RE = compile_clause(r"target player can't play lands this turn")
_TARGET_PLAYER_CANT_CAST_TYPE_RE = compile_clause(
    rf"target player can't cast (?P<type>{'|'.join(_SPELL_TYPE_PARAMS)}) spells this turn"
)


def _target_player_cant_play_lands(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("restrict_target_player_this_turn", {"land_plays": True, "casts": False})]


def _target_player_cant_cast_type(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("restrict_target_player_this_turn", {"spell_types": _SPELL_TYPE_PARAMS[m.group("type").lower()]["spell_types"]})]


ROWS: list[EffectHandler] = [
    EffectHandler("target_player_cant_play_lands", _TARGET_PLAYER_CANT_PLAY_LANDS_RE, _target_player_cant_play_lands),
    EffectHandler("target_player_cant_cast_type", _TARGET_PLAYER_CANT_CAST_TYPE_RE, _target_player_cant_cast_type),
]
