"""Segmenter: optional peel (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from ..catalogue.effect_rows.costs_mana_limits import MAY_COST_THEN_CLAUSE, MAY_EFFECT_THEN_ANTECEDENT_PHRASES
from .late import parse_effect_body

MAY_HAVE_TARGET_GET_RE = re.compile(
    r"(\byou may )have (target (?:[a-z-]+ )*?creature|it|that creature) (get|gain) ", re.IGNORECASE
)



#: "you may pay {E}… . If/When you do, <effect>." (Aether Chaser) / "you
#: may pay {1}. If you do, draw a card." (RULE 118.3's general
#: `pay_cost_then` idiom, Spellbomb-cycle-shaped) / MEC-18's wider "you may
#: sacrifice/discard/pay life `<X>`. When you do, `<effect>`." family / PAR-79
#: seventh increment's "you may return/tap another `<permanent>` you
#: control. If you do, `<effect>`." (`effect_rows.costs_mana_limits._may_effect_then`, via
#: `effect_rows.costs_mana_limits.MAY_EFFECT_THEN_ANTECEDENT_PHRASES`) — every one of these is a
#: *conditioned-on-success* choice `pay_energy_then`/`pay_cost_then`/
#: `optional`(`_may_effect_then`) model with their own interactive
#: machinery, not a whole-ability "you may". Left un-peeled so the full
#: clause reaches `parse_effect_body`'s own handler for whichever shape it
#: is intact (otherwise the ability would be marked doubly-optional *and*
#: the "if you do" gate lost outright — the trailing fragment "`<effect2>`"
#: alone, with no antecedent in front of it, generally can't parse as a
#: sensible effect on its own, so the whole clause silently fails instead
#: of half-modeling it).
#:
#: Deliberately does **not** cover every "you may `<X>`. if/when you do,
#: `<Y>`." shape — `_SACRIFICE_THEN_WHEN_YOU_DO_RE`/
#: `EXILE_SELF_THEN_DELAYED_RETURN_RE`/`_EARTHBEND_THEN_WHEN_YOU_DO_RE`/
#: `_DISCARD_THEN_IF_YOU_DO_RE` (below) are the mirror-image case: a bare,
#: *certain* self-referential antecedent ("sacrifice ~"/"exile it"/
#: "earthbend N"/"discard a card") that RULE 603.3's "if you do" reduces to
#: an unconditional sequence, and those handlers' own docstrings say so
#: explicitly — they run only *after* `peel_optional` has already stripped
#: the leading "you may " and need that peel, not this guard, so widening
#: this regex to catch every antecedent (tried and reverted) broke all four
#: families (Chaos Spewer/Hikari, Twilight Guardian/Sunfire Torch/Yawgmoth
#: Demon &c.) by preventing the very peel they depend on. This antecedent
#: list must therefore only ever grow to cover a **new interactive**
#: `pay_energy_then`/`pay_cost_then`/`_may_effect_then`-shaped handler, never
#: widen to "any antecedent" — the two families are deliberately disjoint by
#: design (`_pay_cost_then_general`'s own docstring on why its cost
#: vocabulary excludes bare self-sacrifice).
PAY_ENERGY_THEN_PEEL_GUARD_RE = re.compile(
    r"^you may (?:pay (?:\{e\})+|" + MAY_COST_THEN_CLAUSE + r"|"
    + MAY_EFFECT_THEN_ANTECEDENT_PHRASES + r")\.\s*(?:if|when) you do"
    # PAR-164: "you may exile it. When you do, …" keeps its "may" (`MAY_EXILE_SELF_THEN_WHEN_YOU_DO_RE`).
    r"|^you may exile (?:it|that card|~)\.\s*when you do",
    re.IGNORECASE,
)


#: RULE 603.3's reflexive trigger tail — "…, when you do, `<effect>`" /
#: "…, if you do, `<effect>`". A "you may" body containing one is a choice
#: *plus a trigger*, not a single optional block; see `MID_BODY_OPTIONAL_RE`'s
#: use site.
REFLEXIVE_TRIGGER_RE = re.compile(r"\b(?:when|if) you do\b", re.IGNORECASE)


#: PAR-62: RULE 601.2b's "you may `<effect>`" as a *clause* rather than as an
#: ability-level prefix — what `peel_optional` sees only when it leads the
#: whole body. Same shape, read at the other end of the pipeline.
MID_BODY_OPTIONAL_RE = re.compile(r"^you may\s+(?P<rest>.+)$", re.IGNORECASE | re.S)

#: PAR-117: "its controller may `<effect>`" — the referent-scoped sibling of
#: `MID_BODY_OPTIONAL_RE` above: the chooser is whichever pronoun referent
#: this body's own subject mode names (RULE 603.1's group-subject firing
#: object, the previous clause's target, or an Aura/Equipment's attached
#: host — never "you", so it can't reuse that row), not this ability's own
#: controller (Edric, Spymaster of Trest/Brood Sliver/Synapse Sliver:
#: "whenever a creature [you control] deals combat damage to a player, its
#: controller may `<effect>`."). Composes the identical ``"optional"`` node
#: `MID_BODY_OPTIONAL_RE`'s own dispatch does — any effect body "you may"
#: can wrap, "its controller may" can too — just with `OptionalEffect.
#: player` pointed at the active referent instead of defaulting to "you".
MID_BODY_ITS_CONTROLLER_MAY_RE = re.compile(
    r"^(?:its|that (?:creature|permanent|land|artifact)'s) controller may\s+(?P<rest>.+)$",
    re.IGNORECASE | re.S
)


#: A sentence that opens with the outcome test of an optional/cost clause before it (RULE 608.2c / 603.12).
_IF_YOU_DO_SENTENCE_RE = re.compile(r"\.\s+(?:if|when) you do\b", re.I)


def peel_optional(body: str) -> tuple[str, bool]:
    """Strip a leading "you may " and report whether it was present (RULE 601.2)."""
    body = body.strip()
    # RULE 608.2c: keep the optional action and its assignment rider atomic.
    if re.fullmatch(r"you may .+\.\s*if you do, .+assigns no combat damage this turn\.?", body, re.I | re.S):
        return body, False
    if MAY_HAVE_TARGET_GET_RE.match(body):
        # RULE 603.5/603.3d: targets are required when the trigger is put on
        # the stack; only applying the pump is optional on resolution.
        return body, False
    if PAY_ENERGY_THEN_PEEL_GUARD_RE.match(body):
        return body, False
    # PAR-152 (Jocasta): "…, if this card is in your graveyard, you may return it to the battlefield tapped and
    # attacking." — the intervening-if just says where the trigger functions (a graveyard-zone trigger, like
    # Bloodghast's), so it folds into the self-return clause the graveyard rows already read.
    in_graveyard = re.match(
        rf"^if (?:this card|~) is in your graveyard,\s+you may return it to the battlefield(?P<rest>.*)$",
        body, re.S,
    )
    if in_graveyard is not None:
        return f"return this card from your graveyard to the battlefield{in_graveyard.group('rest')}", True
    m = re.match(r"^you may\s+(?P<rest>.+)$", body, re.S)
    if m is not None:
        rest = m.group("rest")
        # PAR-130: the causative spelling "you may **have it deal** N/that
        # much damage …" (Mordant Dragon / Skirk Commando family) changes
        # neither source nor effect. Once the optional wrapper is recorded,
        # fold it to the ordinary self-subject "it deal…" body every damage
        # handler already understands. Narrow to this verb so an unrelated
        # "have <player/object> <do something>" choice stays fail-closed.
        causative_damage = re.match(
            r"^have\s+(?P<subject>it|~|this creature|this permanent)\s+"
            r"(?P<deal>deals?\s+.+)$", rest, re.S,
        )
        if causative_damage is not None:
            rest = f"{causative_damage.group('subject')} {causative_damage.group('deal')}"
        # PAR-175: "you may X. If you do, Y." -- "if you do" is the outcome of the optional X (RULE 608.2c,
        # 603.12), and the peel hands it a body whose first clause no longer says it was optional. When the peeled
        # body cannot be read, the whole sentence pair is the unit (`may_effect_then`); a body the peel already
        # reads keeps its meaning untouched.
        if _IF_YOU_DO_SENTENCE_RE.search(rest) and parse_effect_body(body) is not None:
            rest_specs = parse_effect_body(rest)
            # PAR-208: a mandatory-action outcome chain (`seq` + ``if_you_do_from``) reading the peeled remainder is
            # the same unit "you may <action>. If you do, ..." already had as one `optional` node.
            if rest_specs is None or (
                len(rest_specs) == 1 and rest_specs[0].type == "seq" and "if_you_do_from" in rest_specs[0].params
                and re.search(r"\.\s+if you do\b", rest, re.I)
            ):
                return body, False
        # PAR-208 (RULE 608.2c): "you may X. Then Y." -- only X is optional; peeling the "you may" would make the whole
        # ability (and so Y) skippable. The pair stays whole and unclaimed unless a row reads it.
        if re.search(r"\.\s+then\b", rest, re.I):
            return body, False
        return rest, True
    return body, False
