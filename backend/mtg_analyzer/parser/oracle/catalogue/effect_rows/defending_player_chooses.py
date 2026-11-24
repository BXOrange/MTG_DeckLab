"""PAR-317: the defending player makes a choice among their own permanents.

RULE 506.2 / 508.1b: under an attack / unblocked / blocked head "defending player" is the player the source attacks, and
"defending player chooses / sacrifices / exiles ..." is *that* player's choice (RULE 701.17a: the sacrificing player
picks; RULE 406: the exiling player picks here, "they control"), not the attacking controller's. Every row opens a
`choose_objects` for the defender (`player_selector="defending_player"`); the effects that follow ("if they do", "unless")
resolve as the ability's controller. The private ``event_player_events`` marker lets the gate drop the clause under any
head that does not name a defender (fail closed).

"that player" is accepted too: `segmenter.defending_player_trigger` re-reads the printed "defending player" as the
combat event's own "that player" before the body grammar sees it.
"""

from __future__ import annotations

import re
from typing import Optional

from ...spec import EffectSpec
from ..clause_hooks import match_clause
from ..clause_reading import ClauseReading
from .shared import (
    compile_clause, DEFENDING_PLAYER_COMBAT_EVENTS, EVENT_PLAYER_EVENTS_KEY, EffectHandler,
)

_DEFENDER = "(?:defending|that) player"
#: The chosen-from pool words: `RulesEngine._matches_permanent_type` names.
_POOL_WORDS = "creature|artifact|land|enchantment|permanent"


def _defender_chooser(**params) -> dict:
    """The chooser params every row shares. The marker is popped by `gate._resolve_event_player_tree`, which rejects the
    clause unless the trigger event names the attacked player."""
    return {"player_selector": "defending_player", EVENT_PLAYER_EVENTS_KEY: list(DEFENDING_PLAYER_COMBAT_EVENTS), **params}


#: "Defending player chooses an untapped creature they control. That creature blocks ~ this turn if able." (Crashing
#: Boars) -- RULE 509.1c: the defender names the one creature that must block this attacker. The pick is their own
#: (untargeted), so it is a `choose_objects` selection whose ``then`` stamps the `must_block_target` restriction on the
#: pick, pinned to this ability's source (`restrict_to_source`).
_CHOOSES_BLOCKER_RE = compile_clause(
    rf"{_DEFENDER} chooses an untapped creature they control\. that creature blocks (?:~|it|this creature) "
    r"this (?:turn|combat) if able"
)


def _chooses_blocker(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("choose_objects", _defender_chooser(
        action="select_referent", what="creature", count=1, require_untapped=True,
        then=[{"type": "combat_restriction_this_turn", "params": {
            "previous_subject": True, "restriction": {"kind": "must_block_target"}, "restrict_to_source": True,
        }}],
    ))]


#: "Defending player exiles 2 permanents they control." (Bane of Bala Ged) -- the exiling player chooses which of their
#: own permanents go; with no more than N, all of them do.
_EXILES_OWN_RE = compile_clause(
    rf"{_DEFENDER} exiles (?P<count>an?|\d+) (?P<what>{_POOL_WORDS})s? they control"
)


def _exiles_own(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    count = 1 if m.group("count").lower() in ("a", "an") else int(m.group("count"))
    return [EffectSpec("choose_objects", _defender_chooser(
        action="exile", what=m.group("what").lower(), count=count,
    ))]


#: "Defending player sacrifices a creature of their choice. If they do, `<rider>`." (Gisa's Favorite Shovel) -- RULE
#: 701.17a: the defender sacrifices (and picks); the rider is the controller's and only follows an actual sacrifice
#: (a defender with no creature sacrifices nothing, so no rider -- `choose_objects`' ``then`` only runs after a pick).
_SACRIFICES_THEN_RE = compile_clause(
    rf"{_DEFENDER} sacrifices an? (?P<what>{_POOL_WORDS}) of their choice\.\s*"
    r"if (?:they|that player) do(?:es)?,?\s*(?P<rider>[^.]+)"
)


def _sacrifices_then(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    rider = match_clause(m.group("rider").strip(), reading=ClauseReading(self_subject=reading.self_subject))
    if not rider or any(s.params.get("target_kind") not in (None, "source") or "referent" in s.params for s in rider):
        return None  # a rider that announces a target would be chosen at the wrong time
    return [EffectSpec("choose_objects", _defender_chooser(
        action="sacrifice", what=m.group("what").lower(), count=1, then=[s.to_dict() for s in rider],
    ))]


#: "~ gains "~ can't be blocked" until end of turn unless defending player sacrifices a creature of their choice." (Ogre
#: Marauder) -- the defender may pay the sacrifice to keep the attacker blockable (RULE 118.12 shape, a sacrifice rather
#: than mana): an optional pick whose *failure* (declined, or no creature to sacrifice) grants the evasion.
_UNLESS_SACRIFICES_RE = compile_clause(
    r"(?:~|it) gains \"(?:~|this creature) can'?t be blocked\" until end of turn "
    rf"unless {_DEFENDER} sacrifices an? (?P<what>{_POOL_WORDS}) of their choice"
)


def _unless_sacrifices(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    if m.group(0).lower().startswith("it") and not reading.self_subject:
        return None  # "it" is only the ability's source under a self-subject reading
    return [EffectSpec("choose_objects", _defender_chooser(
        action="sacrifice", what=m.group("what").lower(), count=1, optional=True,
        else_effects=[{"type": "unblockable", "params": {"target_kind": None}}],
    ))]


#: "Create a Walker token." (Gisa's Favorite Shovel's rider) -- the Walking Dead set's 2/2 black Zombie creature token
#: named Walker (not in `data/tokens.json`, so it is spelled out like any "2/2 ... token named" clause).
_WALKER_TOKEN_RE = compile_clause(r"(?:you )?create an? walker token")


def _walker_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("create_token", {
        "count": 1, "power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Zombie"], "keywords": [],
        "token_name": "Walker",
    })]


ROWS: list[EffectHandler] = [
    EffectHandler("defending_player_chooses_blocker", _CHOOSES_BLOCKER_RE, _chooses_blocker),
    EffectHandler("defending_player_exiles_own", _EXILES_OWN_RE, _exiles_own),
    EffectHandler("defending_player_sacrifices_then", _SACRIFICES_THEN_RE, _sacrifices_then, reading_aware=True),
    EffectHandler("unless_defending_player_sacrifices", _UNLESS_SACRIFICES_RE, _unless_sacrifices, reading_aware=True),
    EffectHandler("walker_token", _WALKER_TOKEN_RE, _walker_token),
]
