"""PAR-292 M22, RULE 700.3 / 101.4 / 608.2c: "separate <objects> into two piles" over a set of objects in a public zone
(a player's creatures or permanents, a graveyard's creature cards, the cards a preceding clause exiled), all one
`separate_piles` (`game/effects/piles.py`, the choice flow of `reveal_split_piles`):

* Do or Die, Liliana of the Veil's -6: you separate the target player's objects, that player chooses the pile that is
  destroyed (can't be regenerated) / sacrificed;
* Make an Example: each opponent separates their creatures, you choose a pile of each, that pile is sacrificed;
* Death or Glory: you separate your graveyard's creature cards, an opponent chooses the exiled pile, the other returns;
* Bend or Break: each player separates their nontoken lands, an opponent of theirs chooses the destroyed pile, the other
  piles are tapped;
* Boneyard Parley, Split the Spoils: exile up to five target cards, then the piles over those cards, the chosen pile
  to the battlefield under your control / your hand and the rest to the graveyard;
* Brilliant Ultimatum (M23): exile the top N cards of your library, an opponent separates them, you may play lands and
  cast spells from one pile without paying their mana costs (the other pile stays exiled).

Pure data in, `EffectSpec`s out. Every clause is claimed whole: a pile fate the engine does not model leaves it unclaimed.
"""

from __future__ import annotations

import re
from typing import Optional

from ...spec import EffectSpec
from .shared import compile_clause, EffectHandler, graveyard_target_kind

_TWO_PILES = r"(?:2|two) piles"
#: "(creatures|permanents)" the printed object word -> `separate_piles` ``set``.
_SETS = {"creatures": "creatures", "permanents": "permanents"}
#: How many cards "exile up to five target ... cards" takes: the printed number, never above the printed word.
_COUNT_WORD = r"(?P<count>\d+)"

_TARGET_PLAYER_RE = compile_clause(
    rf"separate all (?P<what>creatures|permanents) target player controls into {_TWO_PILES}\.\s*"
    # "They can't be regenerated." is the segmenter's trailing rider (`last_destroy_denying_regeneration`), not this row's.
    r"(?:(?P<destroy>destroy all (?P=what) in the pile of that player'?s choice)"
    r"|(?P<sac>that player sacrifices all (?P=what) in the pile of their choice))"
)
_EACH_OPPONENT_RE = compile_clause(
    rf"each opponent separates the creatures they control into {_TWO_PILES}\.\s*"
    r"for each opponent, you choose (?:1|one) of their piles\.\s*"
    r"each opponent sacrifices the creatures in their chosen pile"
)
_GRAVEYARD_RE = compile_clause(
    rf"separate all creature cards in your graveyard into {_TWO_PILES}\.\s*"
    r"exile the pile of an opponent'?s choice and return the other to the battlefield"
)
_BEND_OR_BREAK_RE = compile_clause(
    rf"each player separates all nontoken lands they control into {_TWO_PILES}\.\s*"
    r"for each player, (?:1|one) of their piles is chosen by (?:1|one) of their opponents of their choice\.\s*"
    r"destroy all lands in the chosen piles\.\s*tap all lands in the other piles"
)
_EXILE_THEN_OPPONENT_SEPARATES_RE = compile_clause(
    rf"exile up to {_COUNT_WORD} target (?P<type>creature) cards from graveyards\.\s*"
    rf"an opponent separates those cards into {_TWO_PILES}\.\s*"
    r"put all cards from the pile of your choice onto the battlefield under your control "
    r"and the rest into their owners'? graveyards"
)
_EXILE_THEN_YOU_SEPARATE_RE = compile_clause(
    rf"exile up to {_COUNT_WORD} target (?P<type>permanent) cards from your graveyard and separate them into {_TWO_PILES}\.\s*"
    r"an opponent chooses (?:1|one) of those piles\.\s*"
    r"put that pile into your hand and the other into your graveyard"
)
_EXILE_TOP_THEN_PLAY_PILE_RE = compile_clause(
    rf"exile the top (?P<count>\d+) cards of your library\.\s*an opponent separates those cards into {_TWO_PILES}\.\s*"
    r"you may play lands and cast spells from (?:1|one) of those piles\.\s*"
    r"if you cast a spell this way, you cast it without paying its mana cost"
)


def _piles(**params) -> list[EffectSpec]:
    return [EffectSpec("separate_piles", params)]


def _target_player(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    fate = "destroy" if m.group("destroy") else "sacrifice"
    return _piles(set=_SETS[m.group("what")], owners="target_player", separator="you", chooser="owner", chosen_fate=fate)


def _each_opponent(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _piles(set="creatures", owners="each_opponent", separator="owner", chooser="you", chosen_fate="sacrifice")


def _graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _piles(set="graveyard_creature_cards", owners="you", separator="you", chooser="opponent",
                  chosen_fate="exile", other_fate="battlefield")


def _bend_or_break(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _piles(set="nontoken_lands", owners="each_player", separator="owner", chooser="opponent",
                  chosen_fate="destroy", other_fate="tap")


def _exile_target_cards(m: re.Match[str], scope: str) -> Optional[list[EffectSpec]]:
    count = int(m.group("count"))
    kind = graveyard_target_kind(m.group("type"), scope)
    if count < 2 or kind is None:
        return None
    return [EffectSpec("exile", {"target_kind": kind, "count": count, "optional": True})]


def _boneyard_parley(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    exile = _exile_target_cards(m, "a")
    if exile is None:
        return None
    return exile + _piles(set="exiled_this_way", owners="you", separator="opponent", chooser="you",
                          chosen_fate="battlefield", other_fate="graveyard")


def _split_the_spoils(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    exile = _exile_target_cards(m, "your")
    if exile is None:
        return None
    return exile + _piles(set="exiled_this_way", owners="you", separator="you", chooser="opponent",
                          chosen_fate="hand", other_fate="graveyard")


def _exile_top_play_pile(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    count = int(m.group("count"))
    if count < 2:
        return None  # one card cannot be divided between two piles
    exile = EffectSpec("exile_top_of_library", {"face_down": False, "player_selector": "controller", "count": count,
                                                "position": "top"})
    return [exile] + _piles(set="exiled_this_way", owners="you", separator="opponent", chooser="you",
                            chosen_fate="play_free")


ROWS: list[EffectHandler] = [
    EffectHandler("piles_separate_target_players_objects", _TARGET_PLAYER_RE, _target_player),
    EffectHandler("piles_each_opponent_separates_creatures", _EACH_OPPONENT_RE, _each_opponent),
    EffectHandler("piles_separate_own_graveyard_creatures", _GRAVEYARD_RE, _graveyard),
    EffectHandler("piles_each_player_separates_lands", _BEND_OR_BREAK_RE, _bend_or_break),
    EffectHandler("piles_exile_graveyard_cards_opponent_separates", _EXILE_THEN_OPPONENT_SEPARATES_RE, _boneyard_parley),
    EffectHandler("piles_exile_own_graveyard_cards_separate", _EXILE_THEN_YOU_SEPARATE_RE, _split_the_spoils),
    EffectHandler("piles_exile_top_play_chosen_pile", _EXILE_TOP_THEN_PLAY_PILE_RE, _exile_top_play_pile),
]
