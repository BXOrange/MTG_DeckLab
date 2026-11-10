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
from .clause_reading import STANDALONE, ClauseReading, CREATED, PLAYER
from .object_phrase import ambiguous_object_reference, object_phrase_specs
from .effect_rows.shared import EffectHandler, match_clause_reading
from .clause_hooks import register_clause_matcher
from .effect_rows import damage_copy
from .effect_rows import damage_prevention
from .effect_rows import draw_discard_cast
from .effect_rows import life_loss
from .effect_rows import destroy_exile_counter
from .effect_rows import tap_return_zones
from .effect_rows import search_control_attach
from .effect_rows import costs_mana_limits
from .effect_rows import counters_blocking
from .effect_rows import pump_stats
from .effect_rows import pump_keywords
from .effect_rows import ability_loss
from .effect_rows import becomes
from .effect_rows import assimilate, keyword_actions
from .effect_rows import tokens_animate_misc
from .effect_rows import party
from .effect_rows import end_of_combat
from .effect_rows import delayed_steps
from .effect_rows import duration_bodies
from .duration_composition import duration_specs
from .clause_primitives import EXCLUDES_SOURCE_PARAM, TARGET_PARAM_KEYS
from .subgrammars import OTHER_TARGET_PART_RE, OTHER_THAN_SOURCE_RE


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
    reading = reading.entered()
    effects = match_clause_reading(clause, reading=reading)
    if effects is None and reading.group_clause:
        effects = object_phrase_specs(clause, reading, _match_registered_clause)
    if effects is None:
        effects = duration_specs(clause, reading)
    return _stamp_excludes_source(clause, effects)


#: Effect types whose target kind is implicit ("any target", the default) when no ``target_kind`` param is written.
_IMPLICIT_ANY_TARGET_TYPES = frozenset({"damage", "add_counters"})


def _names_target(spec: EffectSpec) -> bool:
    """Whether ``spec`` announces a RULE 115 requirement (explicit kind key, or a verb whose default is "any target")."""
    params = spec.params
    if any(key in TARGET_PARAM_KEYS or key.endswith("target_kind") for key in params):
        return True
    return spec.type in _IMPLICIT_ANY_TARGET_TYPES and params.get("selector") is None and params.get("group") is None


def _stamp_excludes_source(clause: str, effects: Optional[list[EffectSpec]]) -> Optional[list[EffectSpec]]:
    """``effects`` with `EXCLUDES_SOURCE_PARAM` set on each that announces a target, when ``clause`` says "another
    target ..." / "any other target" / "target ... other than ~". Marker only: the engine reads it in a later change.

    Conservative by construction for a multi-requirement effect (fight, "target X and another target Y"): the whole
    effect is marked, never a plain requirement left unmarked. Nested effects (a reflexive or delayed body) are marked
    too; an effect whose target lives inside a quoted ability was already marked by that ability's own clause."""
    if not effects or not (OTHER_TARGET_PART_RE.search(clause) or OTHER_THAN_SOURCE_RE.search(clause)):
        return effects
    if any(spec.params.get("distinct_from_others") for spec in effects):
        # "put a counter on target creature, 2 on another target creature, 3 on a third target creature": the
        # builder already told the plain first requirement from the "another" ones (ENG-52), so only those are marked.
        return [_with_excludes_source(spec) if spec.params.get("distinct_from_others") else spec for spec in effects]
    return [_with_excludes_source(spec) for spec in effects]


def _with_excludes_source(spec: EffectSpec) -> EffectSpec:
    params = {key: _stamp_nested(value) for key, value in spec.params.items()}
    if _names_target(spec):
        params[EXCLUDES_SOURCE_PARAM] = True
    return EffectSpec(spec.type, params, condition=spec.condition)


def _stamp_nested(value: Any) -> Any:
    """Nested effect bodies are `EffectSpec`s or their ``{"type", "params"}`` dict form (seq/bind/optional/delayed)."""
    if isinstance(value, EffectSpec):
        return _with_excludes_source(value)
    if isinstance(value, list):
        return [_stamp_nested(item) for item in value]
    if isinstance(value, dict):
        if isinstance(value.get("type"), str) and isinstance(value.get("params"), dict):
            stamped = _with_excludes_source(EffectSpec(value["type"], value["params"], condition=None))
            return {**value, "params": stamped.params}
        return {key: _stamp_nested(item) for key, item in value.items()}
    return value


def _match_clause_once(clause: str, *, reading: ClauseReading = STANDALONE) -> Optional[list[EffectSpec]]:
    if ambiguous_object_reference(clause, reading, _match_registered_clause):
        return None
    registered = _match_registered_clause(clause, reading=reading)
    if reading.group_clause:
        # Preserve the established group-trigger rereading/seed in match_clause_reading.
        return registered
    # These nodes already consume CREATED through the sequence's created-pronoun pass.
    if (any(ref.kind == CREATED for ref in reading.referents) and registered
            and all(spec.type in ("pump", "grant_until") for spec in registered)):
        return registered
    if any(ref.kind in (CREATED, PLAYER) for ref in reading.referents):
        bound = object_phrase_specs(clause, reading, _match_registered_clause, references_only=True)
        if bound is not None:
            return bound
    return registered or object_phrase_specs(clause, reading, _match_registered_clause)


def _match_registered_clause(clause: str, *, reading: ClauseReading = STANDALONE) -> Optional[list[EffectSpec]]:
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
    *ability_loss.ROWS,
    *keyword_actions.ROWS,
    *assimilate.ROWS,  # MEC-140: RULE 701.72
    *tokens_animate_misc.ROWS,
    *party.ROWS,
    *end_of_combat.ROWS,
    *delayed_steps.ROWS,
    *duration_bodies.ROWS,
    # PAR-216: last, so it only ever claims clauses no older row reads (the older en-Kor redirect row keeps its IR).
    *damage_prevention.ROWS,
    # PAR-217: last, so it only claims the "becomes" clauses the older animation rows decline (their IR is unchanged).
    *becomes.ROWS,
]


# The effect rows re-enter the table through `clause_hooks`; resolved at call time so patching the module
# globals (as `tests/test_par169_handler_shadowing.py` does) reaches every caller.
register_clause_matcher(
    match_clause=lambda *args, **kwargs: match_clause(*args, **kwargs),
    match_clause_once=lambda *args, **kwargs: _match_clause_once(*args, **kwargs),
)
