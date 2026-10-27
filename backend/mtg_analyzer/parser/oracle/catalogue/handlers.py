"""The effect-clause handler table (docs/09 "THE CATALOGUE").

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE CATALOGUE", step 3 MATCH).
A **handler** is a regex that identifies + extracts an effect clause paired
with a builder that emits `EffectSpec`s (pure data → the `EffectRegistry`,
never executed behaviour). The set covers exactly what the engine already
supports as one-shot effects — damage / draw / discard / destroy / gain_life /
counter — each factored over the shared TARGET / NUMBER sub-grammars so the
table stays small (docs/09 "Factor shared sub-grammars").

Handlers match a single **normalised effect clause** (the segmenter has
already peeled trigger/cost wrappers and split on sentence boundaries), and
they **full-match** it: a clause is claimed only if a handler consumes it
end to end, which is what makes the coverage gate fail-closed (a half-matched
clause is *not* claimed, so its card stays `UNMODELED`).

Pure regex + data — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import copy
import re

from typing import Any, Optional
from .dying_hosts import dying_host_return_specs
from .fight_sequences import fight_sequence_specs, source_counter_fight_specs
from ..spec import EffectSpec
from .clause_reading import STANDALONE, ClauseReading
from .effect_rows.shared import EffectHandler, match_clause_reading
from .clause_hooks import register_clause_matcher
from .effect_rows import damage_copy
from .effect_rows import draw_discard_cast
from .effect_rows import life_loss
from .effect_rows import destroy_exile_counter
from .effect_rows import tap_return_zones
from .effect_rows import search_control_attach
from .effect_rows import costs_mana_limits
from .effect_rows import counters_blocking
from .effect_rows import pump_stats
from .effect_rows import pump_keywords
from .effect_rows import keyword_actions
from .effect_rows import tokens_animate_misc
from .effect_rows import party
from .effect_rows import end_of_combat
from .effect_rows import delayed_steps


def match_clause(clause: str, *, reading: ClauseReading = STANDALONE) -> Optional[list[EffectSpec]]:
    """The `EffectSpec`s for one normalised effect ``clause``, or ``None``.

    Runs the handler table; the first handler to claim the whole clause wins.
    ``None`` means no handler modeled it — the clause is unclaimed and its card
    will fail the coverage gate (docs/09 fail-closed).

    ``reading`` (`ClauseReading`) says what the clause's bare pronouns mean: ``self_subject`` -- "it" is the
    ability's own source; ``previous_subject`` -- the creature the *preceding* clause of the same body chose;
    ``group_subject`` -- whichever object matched this ability's own RULE 603.1 group-subject trigger condition;
    ``previous_selector`` -- "they" is the group a mass selector in the preceding clause acted on;
    ``attached_subject`` (PAR-117) -- "its" is RULE 303.4/301.5's attached host. Each unlocks the rows that
    declare it in `EffectHandler.requires`; with none set -- the default, and the only reading available to a
    clause standing alone -- a pronoun claims nothing at all.

    PAR-123: a group-subject clause no row claims outright is tried once more as though
    its pronoun named an earlier clause's pick, and the firing object is then made that
    pick (`trigger_subject_referent`) — "it"/"that creature" under a RULE 603.1 group
    trigger *is* an object nothing chose, and every effect with a previous-subject reading
    ("it explores", "it fights …", "that creature endures N") already reads the pick from
    `GameContext.previous_targets`. Rows written for the group subject itself win first, so
    nothing they claim changes reading.
    """
    return match_clause_reading(clause, reading=reading.entered())


def _match_clause_once(clause: str, *, reading: ClauseReading = STANDALONE) -> Optional[list[EffectSpec]]:
    fight_sequence = fight_sequence_specs(clause) or source_counter_fight_specs(clause)
    if fight_sequence is not None:
        return fight_sequence
    if reading.attached_subject:
        host_return = dying_host_return_specs(clause)
        if host_return is not None:
            return host_return
    for handler in HANDLERS:
        if not reading.satisfies(handler.requires):
            continue
        effects = handler.match(clause, reading)
        if effects is not None:
            return effects
    return _per_player_target_specs(clause, reading)


# -- PAR-130: "for each opponent/player, <verb> target <X> that player controls"
#
# The iteration is the antecedent of "that player": one RULE 115 requirement per
# player, each scoped to that player's permanents (`targeting.TargetSpec.
# per_player`). The body is whatever the ordinary table claims; this only stamps
# ``per_player`` onto the requirement(s) it scoped with "that player". Refused
# when the body names another player before "that player" (that player would be
# that one), or when nothing in it is "that player"-scoped. Only a triggered
# ability or a spell gathers its targets per round (`targeting.
# spell_target_rounds`), so `gate._that_player_antecedent_ok` refuses the
# stamp anywhere else.
_PER_PLAYER_RE = re.compile(
    r"for (?P<who>each opponent|each player|any number of opponents), (?P<body>.+)"
)
_PER_PLAYER_BODY_RIVAL_RE = re.compile(r"\b(?:players?|opponents?)\b")
#: "for any number of opponents" (Windgrace's Judgment) is the opponent
#: rounds with each one declinable.
_PER_PLAYER_SCOPE = {
    "each opponent": "opponents", "each player": "players",
    "any number of opponents": "any_opponents",
}


def _stamp_per_player(node: Any, scope: str) -> int:
    """Stamp ``per_player`` on every params dict holding a "that player" kind."""
    if isinstance(node, EffectSpec):
        return _stamp_per_player(node.params, scope)
    if isinstance(node, list):
        return sum(_stamp_per_player(item, scope) for item in node)
    if not isinstance(node, dict):
        return 0
    stamped = 0
    if str(node.get("target_kind") or "").endswith("_that_player_controls"):
        node["per_player"] = scope
        stamped += 1
    if any(str(kind).endswith("_that_player_controls") for kind in (node.get("kinds") or [])):
        node["per_player"] = scope
        stamped += 1
    for key, val in node.items():
        if key != "target_kind":
            stamped += _stamp_per_player(val, scope)
    return stamped


def _per_player_target_specs(clause: str, reading: ClauseReading) -> Optional[list[EffectSpec]]:
    m = _PER_PLAYER_RE.fullmatch(clause.strip())
    if m is None:
        return None
    body = m.group("body")
    if _PER_PLAYER_BODY_RIVAL_RE.search(body.split("that player", 1)[0]):
        return None
    specs = match_clause(body, reading=reading)
    if not specs:
        return None
    specs = copy.deepcopy(specs)
    if not _stamp_per_player(specs, _PER_PLAYER_SCOPE[m.group("who")]):
        return None
    return specs


HANDLERS: list[EffectHandler] = [
    *damage_copy.ROWS,
    *draw_discard_cast.ROWS,
    *life_loss.ROWS,
    *destroy_exile_counter.ROWS,
    *tap_return_zones.ROWS,
    *search_control_attach.ROWS,
    *costs_mana_limits.ROWS,
    *counters_blocking.ROWS,
    *pump_stats.ROWS,
    *pump_keywords.ROWS,
    *keyword_actions.ROWS,
    *tokens_animate_misc.ROWS,
    *party.ROWS,
    *end_of_combat.ROWS,
    *delayed_steps.ROWS,
]


# The effect rows re-enter the table through `clause_hooks`; resolved at call time so patching the module
# globals (as `tests/test_par169_handler_shadowing.py` does) reaches every caller.
register_clause_matcher(
    match_clause=lambda *args, **kwargs: match_clause(*args, **kwargs),
    match_clause_once=lambda *args, **kwargs: _match_clause_once(*args, **kwargs),
)
