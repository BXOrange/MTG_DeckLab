"""RULE 701.72 Assimilate rows (MEC-140): the keyword action and the clauses that read what it did.

The action takes a battlefield permanent (701.72a) or puts a permanent card from another zone onto the battlefield
(701.72b); the same effect type serves every printed shape, and the readers of 701.72c's link are the linked-exile
pool ("a creature card exiled with ~") and "the Borg assimilated with this Saga".
"""

from __future__ import annotations

import re
from typing import Optional

from ..subgrammars import resolve_target_kind, TARGET, target_kind_allowed, target_quality_filter
from ...spec import EffectSpec
from .shared import compile_clause, EffectHandler, graveyard_target_kind, optional_param

#: RULE 701.72a: what a battlefield assimilation may take. Only creature phrases are printed; the engine action itself
#: also handles a noncreature permanent, but a phrase naming one is not claimed until a card needs it.
_ASSIMILATE_BATTLEFIELD_KINDS = ("creature", "creature_you_dont_control")

_ASSIMILATE_TARGET_RE = compile_clause(rf"assimilate {TARGET}")


def _assimilate_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _ASSIMILATE_BATTLEFIELD_KINDS):
        return None
    params: dict = {"target_kind": kind, **optional_param(m)}
    quality = target_quality_filter(m.group("target"))
    if quality:
        params["creature_filter"] = quality
    return [EffectSpec("assimilate", params)]


#: RULE 701.72b: "assimilate target creature card from an opponent's / a / that player's graveyard [that was put
#: there from the battlefield this turn]" (Borg Queen, Death Is Irrelevant, Assimilate the Wounded). "For each
#: opponent" scopes one optional target per opponent to that player's own graveyard (`TargetSpec.per_player`).
_ASSIMILATE_GRAVEYARD_RE = compile_clause(
    r"(?P<per_opp>for each opponent, )?assimilate (?P<up_to_one>up to 1 )?target creature card from "
    r"(?P<scope>an opponent'?s|a|that player'?s) graveyard"
    r"(?P<died> that was put there from the battlefield this turn)?"
)


def _assimilate_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    scope = m.group("scope").lower()
    if bool(m.group("per_opp")) != (scope == "that player's" or scope == "that players"):
        return None  # "that player's" needs the per-opponent iteration to name the player, and vice versa
    kind = graveyard_target_kind("creature", m.group("scope"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind}
    if m.group("up_to_one"):
        params["optional"] = True
    if m.group("per_opp"):
        params["per_player"] = "opponents"
    if m.group("died"):
        # RULE 700.4 / 400.7: the card died this turn, i.e. this very graveyard visit began from the battlefield.
        params["creature_filter"] = {"died_this_turn": True}
    return [EffectSpec("assimilate", params)]


#: RULE 701.72c / 607.2a: "assimilate a creature card exiled with ~" reads the pool the source's own exile ability
#: built (Assimilation Assessor); Borg Cube adds "If you can't, exile up to one target creature."
_ASSIMILATE_LINKED_RE = compile_clause(
    r"assimilate a creature card exiled with (?:~|it|this \w+)"
    r"(?P<fallback>\. if you can'?t, exile up to 1 target creature)?"
)


def _assimilate_linked(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {"pool": "linked_exile"}
    if m.group("fallback"):
        params["exile_else_target"] = True
    return [EffectSpec("assimilate", params)]


#: RULE 701.20 + 701.72b: the two library digs. Both are whole-sentence rows (one card each) because the dig, the
#: assimilation and the bottoming are one instruction sequence sharing the dug pool.
_ASSIMILATE_REVEAL_RE = compile_clause(
    r"each opponent reveals cards from the top of their library until they reveal a creature card\. "
    r"assimilate 1 of the creature cards revealed this way\. "
    r"then each opponent puts the other cards they revealed this way on the bottom of their library in a random order"
)
_ASSIMILATE_EXILE_RE = compile_clause(
    r"target opponent exiles cards from the top of their library until they exile a creature card\. "
    r"assimilate that card\. they put the rest on the bottom in a random order"
)


def _assimilate_reveal(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("assimilate_from_library", {"scope": "each_opponent", "dig": "reveal"})]


def _assimilate_exile(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("assimilate_from_library", {"scope": "target_opponent", "dig": "exile"})]


#: RULE 701.72c: "Exile the Borg assimilated with this Saga, then return it to the battlefield under its owner's
#: control." (The Best of Both Worlds III) -- the linked reader of the Saga's own chapter I.
_RETURN_ASSIMILATED_RE = compile_clause(
    r"exile the borg assimilated with (?:~|this \w+), then return it to the battlefield under its owner'?s control"
)


def _return_assimilated(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile_return_assimilated", {})]


#: "exile target opponent's graveyard" whose cards are later "exiled with ~" (Assimilation Assessor). The older
#: Bojuka Bog row only reads "target player's"; this one names the opponent and records the link (RULE 607.2a).
_EXILE_OPPONENT_GRAVEYARD_RE = compile_clause(r"exile target opponent'?s graveyard")


def _exile_opponent_graveyard(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile_target_graveyard", {"target_kind": "opponent", "track_exiled_with": True})]


ROWS: list[EffectHandler] = [
    EffectHandler("assimilate_linked", _ASSIMILATE_LINKED_RE, _assimilate_linked),
    EffectHandler("assimilate_graveyard", _ASSIMILATE_GRAVEYARD_RE, _assimilate_graveyard),
    EffectHandler("assimilate_target", _ASSIMILATE_TARGET_RE, _assimilate_target),
    EffectHandler("assimilate_reveal_until", _ASSIMILATE_REVEAL_RE, _assimilate_reveal),
    EffectHandler("assimilate_exile_until", _ASSIMILATE_EXILE_RE, _assimilate_exile),
    EffectHandler("exile_return_assimilated", _RETURN_ASSIMILATED_RE, _return_assimilated),
    EffectHandler("exile_opponent_graveyard", _EXILE_OPPONENT_GRAVEYARD_RE, _exile_opponent_graveyard),
]
