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


def _timed_prohibition(**params):
    return lambda match: [EffectSpec("timed_player_prohibition", params)]


def _named_prohibition(match):
    named_land = match["land"] is not None
    if named_land != (match["nonland"] is None):
        return None
    return [EffectSpec("timed_player_prohibition", {
        "choose_name": True, "nonland": not named_land,
        "scope": "all" if named_land else "opponents", "land_plays": named_land,
    })]


def _lock_permanent(match):
    return [EffectSpec("grant_until", {
        "target_kind": "nonland_permanent", "duration": "your_next_turn",
        "static": {"type": "grant_keyword", "params": {"keywords": ["cant_attack", "cant_block"]}},
        "extra_statics": [{"type": "activation_prohibition", "params": {}}],
    })]


ROWS.extend([
    EffectHandler("opponents_cast_from_hand_until_next_turn", compile_clause(
        r"until your next turn, your opponents can't cast spells from anywhere other than their hands"
    ), _timed_prohibition(scope="opponents", hand_only=True)),
    EffectHandler("cast_prohibition_during_opponents_next_turn", compile_clause(
        rf"each opponent can't cast (?P<spell_types>{'|'.join(_SPELL_TYPE_PARAMS)}) spells during that player's next turn"
    ), lambda m: [EffectSpec("timed_player_prohibition", {
        "during_next_turn": True, **_SPELL_TYPE_PARAMS[m["spell_types"]],
    })]),
    EffectHandler("named_cast_prohibition_until_next_turn", compile_clause(
        r"choose a(?P<nonland> nonland)? card name\. "
        r"(?:until your next turn, spells with the chosen name can't be cast and (?P<land>lands with the chosen name can't be played)"
        r"|opponents can't cast spells with the chosen name until your next turn)"
    ), _named_prohibition),
    EffectHandler("bounce_and_prohibit_name_until_next_turn", compile_clause(
        r"return target creature an opponent controls to its owner's hand\. "
        r"that creature's owner can't cast spells with the same name as that creature until your next turn"
    ), _timed_prohibition(bounce_owner=True)),
    EffectHandler("target_permanent_lock_until_next_turn", compile_clause(
        r"choose target nonland permanent\. until your next turn, it can't attack or block, and its activated abilities can't be activated"
    ), _lock_permanent),
    EffectHandler("players_cannot_cast_until_hydras_next_turn", compile_clause(
        r"players can't cast spells until the hydra's next turn"
    ), _timed_prohibition()),
])
