"""Delayed "<effect> at end of combat" riders on the source itself (PAR-202).

RULE 603.7: a trigger that says "<effect> at end of combat" creates a delayed triggered ability that fires
at the next end of combat step (RULE 511.1). The referent is fixed when the delayed ability is created:
here it is always the ability's own source ("it" / "~" of an "attacks or blocks" trigger), so
`create_delayed_trigger`'s ``capture="self"`` names it and the delayed effect runs with the source as its
own object — the Clockwork cycle's "remove a +1/+1 counter from it at end of combat".

The sacrifice / exile / destroy / return riders on other objects ("destroy that creature at end of combat")
are `pump_stats.DELAYED_SAC_EXILE_TAIL_RE`'s; this module holds the self-counter / library riders and the
block-relation / attached-host referents.
"""

from __future__ import annotations

import re
from typing import Optional

from ..clause_hooks import parse_effect_body
from ..clause_reading import ClauseReading
from ...spec import EffectSpec
from .shared import compile_clause, EffectHandler, mass_group_params

#: The `create_delayed_trigger` step name of the end of combat step (`game/phases.py`).
END_COMBAT_STEP = "end_combat"

#: The `ATTACKS` event field naming the attacking creature (`combat_mixin`'s declare-attackers event).
ATTACKER_EVENT_KEY = "instance_id"

#: The effect params a self-directed rider may carry, per effect type. Anything else (a ``target_kind``, a
#: ``group``, a ``selector``, an amount read from the game) names an object other than the source, so the clause is
#: left unclaimed instead of being captured wrongly. ``return_to_library`` keeps its ``target_kind: None`` (the
#: source itself) and its position.
_SELF_RIDER_PARAMS: dict[str, frozenset[str]] = {
    "add_counters": frozenset({"count", "kind"}),
    "remove_counters": frozenset({"self_only", "count", "kind"}),
    "return_to_library": frozenset({"target_kind", "position"}),
}

_DELAYED_SELF_RIDER_RE = compile_clause(r"(?P<body>(?:put|remove) .+?) at end of combat")


def _delayed_self_rider(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    """"remove a +1/+1 counter from it at end of combat" (Clockwork Beetle), "put a +1/+1 counter on ~ at end of
    combat" (Frostweb Spider), "put a -1/-1 counter on it at end of combat" (Wicker Warcrawler), "put it on top of
    its owner's library at end of combat" (Saprazzan Outrigger)."""
    body = parse_effect_body(m.group("body"), reading=reading)
    if not body or len(body) != 1:
        return None
    effect = body[0]
    allowed = _SELF_RIDER_PARAMS.get(effect.type)
    if allowed is None or effect.condition is not None or not set(effect.params) <= allowed:
        return None
    if effect.params.get("target_kind") is not None:
        return None
    return [EffectSpec("create_delayed_trigger", {
        "step": END_COMBAT_STEP, "scope": "any", "capture": "self", "effects": [effect.to_dict()],
    })]


#: RULE 611.2b: "gain control of all creatures blocking ~ for as long as you control ~" (The Wretched) — the
#: mass steal whose end is bound to the source (`GainControlUntilEndOfTurnEffect.group` + ``while_source``).
_GAIN_CONTROL_GROUP_WHILE_SOURCE_RE = compile_clause(
    r"gain control of (?P<quant>all|each) (?P<group>[a-z0-9' ,/+~-]+?)"
    r" for as long as (?:(?P<ctl>you control ~)|(?:~ remains on the battlefield))"
)


def _gain_control_group_while_source(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = mass_group_params(m.group("group"), m.group("quant"))
    if params is None or "group_player" in params:
        return None
    return [EffectSpec("gain_control_until_eot", {
        **params, "duration": "permanent", "haste": False, "untap": False,
        "while_source": "controlled" if m.group("ctl") else "on_battlefield",
    })]


#: RULE 509.3 / 603.7: under a block-relation head ("whenever ~ blocks or becomes blocked by a creature") "the other
#: creature" / "that creature" is the creature on the far side of the block, fixed when the delayed ability is
#: created — Venom's "destroy the other creature at end of combat", Tolarian Entrancer's "gain control of that
#: creature at end of combat".
#:
#: "The other creature" is emitted with ``capture="trigger_related"`` and no filter yet:
#: `segmenter._retarget_block_relation` fills in the head's ``related_filter``. "That creature" takes the shared
#: ``previous_or_self`` capture the sacrifice/exile/destroy riders use, which the segmenter converts to the head's
#: far-side object (`_retarget_block_relation` / the group-pronoun reading) — and ``needs_block_head`` makes any
#: other head fail closed, since there "that creature" would fall back to the source and take control of itself.
_DELAYED_RELATED_RE = compile_clause(
    r"(?:(?P<destroy>destroy) the other creature|(?P<steal>gain control of) that creature) at end of combat"
)

#: The marker param `_delayed_related` stamps on a ``previous_or_self`` capture it cannot resolve itself.
NEEDS_BLOCK_HEAD = "needs_block_head"


def _delayed_related(m: re.Match[str]) -> list[EffectSpec]:
    if m.group("destroy"):
        return [EffectSpec("create_delayed_trigger", {
            "step": END_COMBAT_STEP, "scope": "any", "capture": "trigger_related",
            "effects": [{"type": "destroy_specific", "params": {}}],
        })]
    # RULE 611.2: a no-duration control change (the delayed ability's own resolution does the taking).
    steal = {"type": "gain_control_until_eot", "params": {
        "target_kind": "creature", "duration": "permanent", "haste": False, "untap": False,
    }}
    return [EffectSpec("create_delayed_trigger", {
        "step": END_COMBAT_STEP, "scope": "any", "capture": "previous_or_self", "effects": [steal],
        NEEDS_BLOCK_HEAD: True,
    })]


#: RULE 603.7: "when enchanted creature attacks, return it and ~ to their owners' hands at end of combat" (Contempt)
#: — two delayed returns with two referents fixed now: the attacker the firing event names (the Aura's host) and
#: the Aura itself.
_DELAYED_RETURN_HOST_AND_SELF_RE = compile_clause(
    r"return it and ~ to their owners'? hands at end of combat"
)


def _delayed_return_host_and_self(m: re.Match[str]) -> list[EffectSpec]:
    returned = [{"type": "return_specific_to_hand", "params": {}}]
    return [
        EffectSpec("create_delayed_trigger", {
            "step": END_COMBAT_STEP, "scope": "any", "capture": "trigger_subject",
            "trigger_event_key": ATTACKER_EVENT_KEY, "effects": returned,
        }),
        EffectSpec("create_delayed_trigger", {
            "step": END_COMBAT_STEP, "scope": "any", "capture": "self", "effects": returned,
        }),
    ]


#: RULE 603.7 / 608.2h: "~ deals 1 damage to that creature at end of combat" (Sawtooth Ogre) — the far-side creature of a
#: block relation is fixed when the delayed ability is created, like the destroy/steal riders above (same
#: ``previous_or_self`` + ``needs_block_head`` capture, converted by `segmenter._retarget_block_relation`). The damage is
#: dealt by the source by last known information, so it still happens when the source left the battlefield first.
#: Self-subject heads only: under an attached-host head "it" would be the Equipment/Aura, not the host.
_DELAYED_DAMAGE_RELATED_RE = compile_clause(r"(?:~|it) deals (?P<n>\d+) damage to that creature at end of combat")


def _delayed_damage_related(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_delayed_trigger", {
        "step": END_COMBAT_STEP, "scope": "any", "capture": "previous_or_self",
        "effects": [{"type": "damage_specific", "params": {"amount": int(m.group("n"))}}],
        NEEDS_BLOCK_HEAD: True,
    })]


#: RULE 603.7c / 601.2c: "{3}{B}: Destroy target blocking creature at end of combat." (Silent Assassin) — the target is
#: announced with the ability, not when the delayed trigger fires, so it is split into a bare announcement
#: (`choose_targets`, the same pre-pick the "choose target ..." riders use) and a delayed destroy that captures exactly
#: that pick (``capture="previous_targets"``). The delayed ability then names the object by zone visit (RULE 400.7) and
#: never targets again, so hexproof gained in between does not stop it, and a creature that left and returned is a new
#: object it leaves alone.
_DELAYED_TARGET_DESTROY_RE = compile_clause(r"destroy (?P<target>target .+?) at end of combat")

#: The announcement params a delayed targeted destroy may carry over from the plain `destroy` clause it is read as.
_DELAYED_TARGET_PARAMS = frozenset({"target_kind", "creature_filter", "optional"})


def _delayed_target_destroy(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    body = parse_effect_body(f"destroy {m.group('target')}", reading=reading.but(previous_subject=False))
    if not body or len(body) != 1:
        return None
    effect = body[0]
    if effect.type != "destroy" or effect.condition is not None or not set(effect.params) <= _DELAYED_TARGET_PARAMS:
        return None
    if not effect.params.get("target_kind"):
        return None
    announce = {"kinds": [effect.params["target_kind"]], "optional": bool(effect.params.get("optional", False))}
    if effect.params.get("creature_filter"):
        announce["creature_filter"] = effect.params["creature_filter"]
    return [
        EffectSpec("choose_targets", announce),
        EffectSpec("create_delayed_trigger", {
            "step": END_COMBAT_STEP, "scope": "any", "capture": "previous_targets",
            "effects": [{"type": "destroy_specific", "params": {}}],
        }),
    ]


#: RULE 603.7c: the same pick, read back by a later clause — "Choose target attacking or blocking creature whose
#: controller controls an Island. ~ deals 2 damage to that creature at end of combat." (Dwarven Sea Clan). "That
#: creature" is the earlier clause's announced target (``previous_subject``), so the delayed damage captures
#: ``previous_targets``; the block-relation row above is the ``self_subject``/trigger-head reading of the same words.
_DELAYED_DAMAGE_PREVIOUS_RE = compile_clause(r"(?:~|it) deals (?P<n>\d+) damage to that creature at end of combat")


def _delayed_damage_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_delayed_trigger", {
        "step": END_COMBAT_STEP, "scope": "any", "capture": "previous_targets",
        "effects": [{"type": "damage_specific", "params": {"amount": int(m.group("n"))}}],
    })]


#: RULE 603.7 comma form: "when ~ attacks or blocks, **at end of combat**, sacrifice it and it deals 5 damage to you"
#: (Time Elemental) — the trigger's body is itself the delayed ability. The source is fixed when the trigger resolves
#: (``capture="self"``), so "sacrifice it" / "destroy it" name that very stay of the permanent (RULE 400.7: a copy that
#: left and returned is a new object and is left alone) and only its controller can sacrifice it (RULE 701.17a, "you
#: can't sacrifice it" once control changed). Damage the source deals is by last known information (RULE 608.2h), so
#: it is dealt even when the sacrifice just happened or could not.
_AT_END_OF_COMBAT_BODY_RE = compile_clause(r"at end of combat, (?P<body>.+)")

#: The self-bound effects a comma-form delayed body may use, and what each becomes inside the delayed ability.
_SELF_BODY_TYPES = frozenset({"sacrifice_self", "destroy", "damage"})


def _delayed_comma_body(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    body = parse_effect_body(m.group("body"), reading=reading)
    if not body:
        return None
    inner: list[dict] = []
    for effect in body:
        if effect.condition is not None or effect.type not in _SELF_BODY_TYPES:
            return None
        if effect.type == "sacrifice_self" and not effect.params:
            inner.append({"type": "sacrifice_specific", "params": {"controlled_only": True}})
        elif effect.type == "destroy" and effect.params == {"source_only": True}:
            inner.append({"type": "destroy_specific", "params": {}})
        elif effect.type == "damage" and effect.params.get("selector") == "controller":
            inner.append(effect.to_dict())
        else:
            return None
    return [EffectSpec("create_delayed_trigger", {
        "step": END_COMBAT_STEP, "scope": "any", "capture": "self", "effects": inner,
    })]


#: RULE 509.1a / 603.7: "when ~ blocks, at end of combat, destroy it and all creatures it blocked this turn" (Defiant
#: Vanguard) — the source and the attackers it was declared as a blocker of, fixed when the ability resolves
#: (``capture="source_and_blocked"``) so the set survives the source's own death.
_AT_END_OF_COMBAT_DESTROY_SELF_AND_BLOCKED_RE = compile_clause(
    r"at end of combat, destroy it and all creatures it blocked this turn"
)


def _delayed_destroy_self_and_blocked(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_delayed_trigger", {
        "step": END_COMBAT_STEP, "scope": "any", "capture": "source_and_blocked",
        "effects": [{"type": "destroy_specific", "params": {}}],
    })]


ROWS: list[EffectHandler] = [
    EffectHandler(
        "delayed_return_host_and_self_end_of_combat", _DELAYED_RETURN_HOST_AND_SELF_RE,
        _delayed_return_host_and_self, requires=ClauseReading(attached_subject=True),
    ),
    EffectHandler(
        "delayed_damage_previous_end_of_combat", _DELAYED_DAMAGE_PREVIOUS_RE, _delayed_damage_previous,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler("delayed_related_end_of_combat", _DELAYED_RELATED_RE, _delayed_related),
    EffectHandler(
        "delayed_damage_related_end_of_combat", _DELAYED_DAMAGE_RELATED_RE, _delayed_damage_related,
        requires=ClauseReading(self_subject=True),
    ),
    EffectHandler(
        "delayed_target_destroy_end_of_combat", _DELAYED_TARGET_DESTROY_RE, _delayed_target_destroy,
        reading_aware=True,
    ),
    EffectHandler(
        "delayed_destroy_self_and_blocked_end_of_combat", _AT_END_OF_COMBAT_DESTROY_SELF_AND_BLOCKED_RE,
        _delayed_destroy_self_and_blocked, requires=ClauseReading(self_subject=True),
    ),
    EffectHandler(
        "delayed_comma_body_end_of_combat", _AT_END_OF_COMBAT_BODY_RE, _delayed_comma_body,
        requires=ClauseReading(self_subject=True), reading_aware=True,
    ),
    EffectHandler("gain_control_group_while_source", _GAIN_CONTROL_GROUP_WHILE_SOURCE_RE, _gain_control_group_while_source),
    EffectHandler(
        "delayed_self_rider_end_of_combat", _DELAYED_SELF_RIDER_RE, _delayed_self_rider,
        requires=ClauseReading(self_subject=True), reading_aware=True,
    ),
]
