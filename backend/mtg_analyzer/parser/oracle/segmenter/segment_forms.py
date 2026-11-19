"""Segmenter: segment forms (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from ..catalogue.clause_reading import ClauseReading, STANDALONE
from typing import Optional
from ..catalogue.static_handlers import static_condition
from ..spec import AbilitySpec, EffectSpec, ParserProvenance
from .segment_types import Segment
from .trigger_heads import TRIGGER_RE
from .keyword_and_trigger_conditions import (
    NEXT_CAST_RE,
    SOURCE_LEAVES_RE,
    TARGET_CREATURE_SUBJECT_RE,
    DEALT_DAMAGE_THIS_WAY_SUBJECT_RE,
    THAT_CREATURE_SUBJECT_RE,
    TURN_TRIGGER_RE,
    compound_candidates,
)
from .pronoun_stamping import stamp_group_pronoun
from .late import segment_line_unsplit
from .late import register

#: The event field naming the creature a turn-long trigger fired for: the damage source for a DAMAGE event, the
#: object itself for attacks / becomes-blocked (RULE 603.7c: "it" is the object the trigger is about).
_LINKED_SUBJECT_EVENT_KEYS = {"DAMAGE": "source_id", "ATTACKS": "instance_id", "BECOMES_BLOCKED": "instance_id"}
#: The number of blockers a BECOMES_BLOCKED event carries (RULE 509.1a): "for each creature blocking it" read off the
#: event, since the trigger's own source is the spell and not the blocked creature.
_BLOCKER_COUNT_AMOUNT = {"kind": "trigger_event", "field": "blocker_count"}


def aim_at_linked_creature(effect: dict, event: object) -> dict:
    """``effect`` with an untargeted pump / blocker count re-pointed at the creature a "that creature <event> this turn"
    trigger fired for. The ability stays bound to the spell (so "you" is its controller), hence a bare "it gets +1/+1"
    or "creatures blocking it" would otherwise read the spell. Other effects are returned unchanged."""
    key = _LINKED_SUBJECT_EVENT_KEYS.get(event) if isinstance(event, str) else None
    if key is None:
        return effect
    params = dict(effect.get("params") or {})
    if effect.get("type") == "pump" and not (params.get("target_kind") or params.get("selector")
                                             or params.get("trigger_subject")):
        params.update({"trigger_subject": True, "trigger_event_key": key})
    elif effect.get("type") == "bind" and event == "BECOMES_BLOCKED":
        amount = params.get("amount") or {}
        if amount.get("kind") == "count_selector" and (
                ((amount.get("selector") or {}).get("filter") or {}).get("blocking_source")):
            params["amount"] = dict(_BLOCKER_COUNT_AMOUNT)
        params["effects"] = [aim_at_linked_creature(e, event) for e in params.get("effects") or []]
    return {**effect, "params": params}


def turn_trigger_segment(
    line: str, *, provenance: ParserProvenance, reading: ClauseReading = STANDALONE,
) -> "Optional[Segment]":
    """A spell line that creates a turn-long trigger → its `create_turn_trigger` segment;
    an unclaimed `Segment` when the trigger inside is not one the grammar reads; ``None``
    when the line is not this shape at all."""
    m = TURN_TRIGGER_RE.match(line.strip())
    if m is None:
        return None
    keyword = (m.group("kw1") or m.group("kw2")).lower()
    condition = m.group("cond1") or m.group("cond2")
    once = NEXT_CAST_RE.search(condition.lower()) is not None
    if once:
        condition = NEXT_CAST_RE.sub("you cast", condition.lower())
    target_creature = TARGET_CREATURE_SUBJECT_RE.match(condition.strip())
    target_kind = None
    if target_creature is not None:
        target_kind = "creature"
        condition = f"~ {target_creature.group('verb')}"
    dealt_this_way = DEALT_DAMAGE_THIS_WAY_SUBJECT_RE.match(condition.strip())
    if dealt_this_way is not None:
        condition = f"{dealt_this_way.group('subject')} dies"
    that_creature = THAT_CREATURE_SUBJECT_RE.match(condition.strip())
    if that_creature is not None:
        if not reading.previous_subject:
            return Segment(raw=line.strip())
        condition = f"~ {that_creature.group('verb')}"
    unclaimed = Segment(raw=line.strip())
    if (
        SOURCE_LEAVES_RE.match(condition.strip()) and reading.previous_subject and target_kind is None
        and m.group("body").strip().lower() == "sacrifice that creature"
    ):
        # The shell supplies the trigger dict; the body is the baked `sacrifice_specific` (no re-parse of "that creature").
        shell = segment_line(
            f"{keyword} {condition}, draw a card.", allow_spell_effect=False, provenance=provenance,
        )
        if not shell.claimed or shell.spec is None or isinstance(shell.spec.trigger.get("event"), list):
            return unclaimed
        return Segment(
            raw=line.strip(),
            spec=AbilitySpec(
                "spell_effect",
                effects=[EffectSpec("create_turn_trigger", {
                    "trigger": shell.spec.trigger,
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "optional": False,
                    "bake_previous_objects": True,
                    "description": line.strip(),
                })],
                raw_text=line.strip(), parser=provenance,
            ),
            claimed=True,
        )
    inner = segment_line(
        f"{keyword} {condition}, {m.group('body')}",
        allow_spell_effect=False, provenance=provenance,
    )
    pinned = target_kind is not None or that_creature is not None
    if pinned and (not inner.claimed or inner.spec is None) and condition == "~ dies":
        # The body names the dying creature's controller/owner ("its controller gets a poison counter"): a self
        # subject can't say that, but the same body under a group head can — its effects carry the group-subject
        # referent, which the binder resolves for a chosen-object trigger too. The trigger shell stays the self one.
        group = segment_line(
            f"{keyword} a creature dies, {m.group('body')}",
            allow_spell_effect=False, provenance=provenance,
        )
        shell = segment_line(f"{keyword} {condition}, draw a card.", allow_spell_effect=False, provenance=provenance)
        if group.claimed and group.spec is not None and shell.claimed and shell.spec is not None:
            group.spec.trigger = shell.spec.trigger
            inner = group
    if not inner.claimed or inner.spec is None or inner.extra_specs:
        return unclaimed
    spec = inner.spec
    if spec.ability_kind != "triggered" or not spec.effects or isinstance(spec.trigger.get("event"), list):
        return unclaimed
    effect_dicts = [e.to_dict() for e in spec.effects]
    if that_creature is not None:
        effect_dicts = [aim_at_linked_creature(e, spec.trigger.get("event")) for e in effect_dicts]
    if pinned:
        # "…, return **it** to the battlefield": the pinned trigger is bound to the spell/ability, so a bare "it" must
        # name the creature that died (the trigger's subject), not the source — as "return that card" already does.
        for effect in effect_dicts:
            if effect.get("type") == "return_self_to_battlefield" and "target_kind" not in effect["params"]:
                effect["params"] = {**effect["params"], "target_kind": "trigger_subject"}
    return Segment(
        raw=line.strip(),
        spec=AbilitySpec(
            "spell_effect",
            effects=[EffectSpec("create_turn_trigger", {
                "trigger": spec.trigger,
                "effects": effect_dicts,
                "optional": bool(spec.optional),
                **({"once": True} if once else {}),
                **({"target_kind": target_kind} if target_kind else {}),
                **({"previous_subject": True} if that_creature is not None else {}),
                **({"damaged_this_way": True} if dealt_this_way is not None else {}),
                "description": line.strip(),
            })],
            raw_text=line.strip(), parser=provenance,
        ),
        claimed=True,
    )


def _stamp_group_pronoun_segment(segment: "Segment") -> "Segment":
    """`stamp_group_pronoun` over a finished triggered segment — every dispatch that
    builds a group-subject trigger (damage, batch, object-head, …) is covered here
    instead of at each of its call sites."""
    if not segment.claimed or segment.spec is None:
        return segment
    trigger_line = TRIGGER_RE.match(segment.raw.strip().lower())
    for spec in [segment.spec, *segment.extra_specs]:
        if spec.ability_kind != "triggered" or trigger_line is None:
            continue
        stamped = stamp_group_pronoun(
            (spec.trigger or {}).get("condition"), trigger_line.group("body"), spec.effects
        )
        if stamped is None:
            return Segment(raw=segment.raw)
        spec.effects = stamped
    return segment


#: "Whenever ~ attacks while <state>, <effect>" qualifies the event
#: (RULE 603.2); it is not RULE 603.4's intervening-if clause.
_WHILE_TAIL_RE = re.compile(
    r"^(?P<kw>when|whenever) (?P<head>[^,]+?) while (?P<state>[^,]+),\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)


def _while_condition_segment(
    line: str, *, allow_spell_effect: bool, provenance: ParserProvenance, is_saga: bool
) -> "Optional[Segment]":
    """Gate a normal trigger at event time; saddled retains its own stamp."""
    m = _WHILE_TAIL_RE.match(line.strip())
    if m is None:
        return None
    saddled = m.group("state").strip() == "saddled"
    gate = None if saddled else static_condition(m.group("state"))
    if not saddled and gate is None:
        # Leave-event power checks use the existing effect condition's
        # last-known event snapshot (RULE 603.10), not the moved source.
        return segment_line(
            f"{m.group('kw')} {m.group('head')}, if {m.group('state')}, {m.group('body')}",
            allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga,
        )
    inner = segment_line(
        f"{m.group('kw')} {m.group('head')}, {m.group('body')}",
        allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga,
    )
    if not inner.claimed or inner.spec is None or inner.spec.ability_kind != "triggered":
        return Segment(raw=line.strip())
    if saddled:
        # `requires_saddled` is source-relative, hence self subjects only.
        if inner.extra_specs or (inner.spec.trigger or {}).get("condition", {}).get("subject") != "self":
            return Segment(raw=line.strip())
        inner.spec.trigger = {**inner.spec.trigger, "requires_saddled": True}
    else:
        for spec in [inner.spec, *inner.extra_specs]:
            if spec.ability_kind != "triggered":
                return Segment(raw=line.strip())
            previous_gate = (spec.trigger or {}).get("active_if")
            spec_gate = {"kind": "all", "conditions": [previous_gate, gate]} if previous_gate else gate
            spec.trigger = {**spec.trigger, "active_if": spec_gate}
    inner.raw = inner.spec.raw_text = line.strip()
    return inner


#: PAR-204: a graveyard-recursion trigger ("At the beginning of your upkeep, if this card is in your graveyard, you may
#: pay {B}{B}{B}. If you do, return it to your hand." — Ghastly Remains, Pyre Zombie, Master of Death; "Whenever a
#: creature you control dies while this card is in your graveyard, …" — Furious Forebear, Boneyard Scourge).
#: RULE 113.6k: an ability that returns its own card from the graveyard functions only there, so the printed
#: "if this card is in your graveyard" is where the ability *works*, not an extra condition; the binder already infers
#: `functions_from_graveyard` from the self-return payoff (`binding.core._returns_self_from_graveyard`). The payoff's
#: pronoun ("it", "this card") names that same card, so it is spelled out as the existing graveyard self-return row.
_GRAVEYARD_FUNCTION_TRIGGER_RE = re.compile(
    r"^(?P<head>(?:when|whenever|at) [^,]+?),? (?:if|while) (?:this card|~) is in your graveyard,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)
_GRAVEYARD_SELF_RETURN_RE = re.compile(
    r"\breturn (?:this card|it|~)(?: from your graveyard)? to (?P<zone>your hand|the battlefield)", re.IGNORECASE,
)
#: The payoff is *only* the self-return (optionally paid for / optional): any other use of "it" would be ambiguous.
_GRAVEYARD_SELF_RETURN_BODY_RE = re.compile(
    r"^(?:you may )?(?:pay [^.]+\. if you do, )?return this card from your graveyard to "
    r"(?:your hand|the battlefield(?: tapped)?)(?: with an? [a-z+/0-9 -]+ counter on it)?\.?$",
    re.IGNORECASE,
)


def _graveyard_self_return_segment(
    line: str, *, allow_spell_effect: bool, provenance: ParserProvenance, is_saga: bool
) -> "Optional[Segment]":
    """The segment of a graveyard-recursion trigger read as its plain head plus the self-return payoff, or ``None``."""
    m = _GRAVEYARD_FUNCTION_TRIGGER_RE.match(line.strip())
    if m is None:
        return None
    body = _GRAVEYARD_SELF_RETURN_RE.sub(
        lambda r: f"return this card from your graveyard to {r.group('zone')}", m.group("body").strip(), count=1,
    )
    if not _GRAVEYARD_SELF_RETURN_BODY_RE.match(body):
        return None
    inner = segment_line_unsplit(
        f"{m.group('head')}, {body}", allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga,
    )
    return inner if inner.claimed else None


#: "if `<state>`, `<effect>`" at the head of a phase trigger's body — the state is read by
#: `static_condition`, so anything that vocabulary says is an intervening if.
PHASE_INTERVENING_IF_RE = re.compile(r"^if (?P<cond>[^,]+), (?P<rest>.+)$", re.IGNORECASE | re.S)
#: A second sentence after the first one — what makes a leading phase-trigger "if"
#: an ability-wide gate rather than one effect's (see its use in `segment_line`).
_NEXT_SENTENCE_RE = re.compile(r"\.\s+\S")


#: "Flashback {8}{G}{G}. This spell costs {X} less to cast this way, where X is …" (the Visions flashback cycle): a
#: keyword line carrying a sentence about its own cost, read as the keyword plus a graveyard-gated cost reduction.
FLASHBACK_DISCOUNT_LINE_RE = re.compile(
    r"(?P<keyword>flashback (?:\{[^{}]+\})+)\.\s+(?P<discount>this spell costs \{x\} less to cast this way, where x is .+)",
    re.IGNORECASE,
)


def segment_line(
    line: str,
    *,
    allow_spell_effect: bool,
    provenance: ParserProvenance,
    is_saga: bool = False,
) -> Segment:
    """Parse one normalised ability ``line`` into a `Segment` — whole first,
    then, if unclaimed, as two independent triggers sharing one body."""
    if allow_spell_effect:
        turn_trigger = turn_trigger_segment(line, provenance=provenance)
        if turn_trigger is not None:
            return turn_trigger
    while_reading = _while_condition_segment(
        line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    if while_reading is not None and while_reading.claimed:
        return while_reading
    whole = _stamp_group_pronoun_segment(segment_line_unsplit(
        line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    ))
    if whole.claimed:
        return whole
    graveyard_return = _graveyard_self_return_segment(
        line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    if graveyard_return is not None:
        return graveyard_return
    for first, second in compound_candidates(line):
        halves = [
            segment_line(
                half, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
            )
            for half in (first, second)
        ]
        if any(h.spec is None or not h.claimed for h in halves):
            continue
        specs = [h.spec for h in halves] + [x for h in halves for x in h.extra_specs]
        return Segment(raw=line.strip(), spec=specs[0], extra_specs=specs[1:], claimed=True)
    return whole


# Late-bound entry points other modules of this package call before this one is defined (see `late`).
register(segment_line=segment_line, turn_trigger_segment=turn_trigger_segment)
