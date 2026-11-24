"""Segmenter: pronoun stamping (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import json
import re
from ..catalogue.clause_reading import ClauseReading
from typing import Any, Optional
from ..catalogue.effect_rows.end_of_combat import NEEDS_BLOCK_HEAD
from ..catalogue.effect_rows.shared import base_verb
from ..catalogue.referent_condition import PRONOUN_NOUN_ALT
from ..catalogue.static_handlers import static_condition
from ..spec import EffectSpec, GROUP_SUBJECT_KEY_SENTINEL
from .conditions import acts_on_source_under_attached
from .late import parse_effect_body

#: A bare pronoun in a trigger body ("return **it**", "exile **that creature**").
_BARE_PRONOUN_RE = re.compile(rf"\b(?:it|that {PRONOUN_NOUN_ALT})\b(?!')")

#: An explicit naming of the ability's own source in a normalised body ("~", or the
#: "this card"/"this spell" phrasings `normalize` leaves alone).
_EXPLICIT_SOURCE_RE = re.compile(r"~|\bthis (?:card|spell|creature|permanent|artifact|enchantment|land)\b")

#: Effect types whose untargeted form ("it") has a ``"trigger_subject"`` mode — the
#: object that fired a group trigger, read off the event at resolution.
_GROUP_IT_RETARGETED: frozenset[str] = frozenset({"tap", "return_to_hand", "exile"})


IT_DEALS_RE = re.compile(rf"\b(?:it|that {PRONOUN_NOUN_ALT}) deals?\b")


def deals_damage(effect: "EffectSpec") -> bool:
    """A ``damage`` effect, or a ``bind`` whose body is one."""
    if effect.type == "damage":
        return True
    return effect.type == "bind" and any(
        isinstance(e, dict) and e.get("type") == "damage" for e in effect.params.get("effects", [])
    )


def _reads_blocked_attacker(effect: "EffectSpec") -> bool:
    """Whether ``effect`` carries a "creatures blocking it" group (`blocking_source`), which the
    engine reads off the effect's *source* — the blocked attacker."""
    return '"blocking_source"' in json.dumps(effect.to_dict(), default=str)


def _stamped_dealer(effect: "EffectSpec") -> bool:
    return GROUP_SUBJECT_KEY_SENTINEL in json.dumps(effect.to_dict(), default=str)


def _stamped_dealer_any(effects: "list[EffectSpec]") -> bool:
    """Whether any of ``effects`` reads the group trigger's firing object."""
    return any(_stamped_dealer(e) for e in effects)


def stamp_damage_dealer(effect: "EffectSpec") -> "EffectSpec":
    """``effect`` with each ``damage`` in it dealt by the group trigger's firing object."""
    if effect.type == "damage":
        return EffectSpec(
            "damage", {**effect.params, "dealer_event_key": GROUP_SUBJECT_KEY_SENTINEL},
            condition=effect.condition,
        )
    inner = [
        {**e, "params": {**e["params"], "dealer_event_key": GROUP_SUBJECT_KEY_SENTINEL}}
        if e.get("type") == "damage" else e
        for e in effect.params["effects"]
    ]
    return EffectSpec("bind", {**effect.params, "effects": inner}, condition=effect.condition)


#: Words that put another card in play for a later "that card" to name ("exile the top card of your
#: library. You may play that card"), so it is *not* the object a trigger fired for.
CARD_INTRODUCER_RE = re.compile(
    r"\b(?:top card|top \d+ cards|reveal|look at|from among|search your|cards? from|revealed|exile target|"
    r"target [a-z ]*card|the first card)\b"
)

#: A bare "it" (not "it's", not "its").
BARE_IT_RE = re.compile(r"\bit\b(?!')")
#: ENG-64: "...that shares a color / a creature type / a card type with **it**" -- an "it" that only ever means the
#: object the trigger fired for (`GROUP_REFERENCE_TAILS`), so it does not make a "~ or another <group>" head's body
#: ambiguous between the source and the firing object: whichever of the two fired, that object is the one compared.
SHARES_WITH_IT_RE = re.compile(r"\bshares? an? (?:color|creature type|card type) with it\b")

#: A boundary between one clause and the next in a normalised trigger body.
_CLAUSE_BOUNDARY_RE = re.compile(r"[.;,]| then | and ")


#: RULE 707.9a: a copy's "…, except it has …" tail — there "it" is the copy (the source), never the firing object.
_COPY_EXCEPTION_TAIL_RE = re.compile(r",? except it\b.*$")


def _without_copy_exception(lowered: str) -> str:
    return _COPY_EXCEPTION_TAIL_RE.sub("", lowered)


#: PAR-261: "put a quest counter on ~" / "if ~ has 5 or more quest counters on it" -- a "~" that only carries a counter
#: tally, never the antecedent of a later "that creature".
_SOURCE_COUNTER_PUT_RE = re.compile(r"\bput (?:a|an|\d+) [a-z+\-/0-9 ]+? counters? on ~$")
_SOURCE_COUNTER_GATE_RE = re.compile(r"\bif ~ has (?:a|an|\d+) or more [a-z+\-/0-9 ]+? counters? on it,")


def _source_counter_bookkeeping(lowered: str, source: "re.Match[str]") -> bool:
    return _SOURCE_COUNTER_PUT_RE.search(lowered, max(0, source.start() - 40), source.end()) is not None


def pronoun_continues_source(lowered: str) -> bool:
    """Whether a bare pronoun in ``lowered`` sits in a later clause than an explicit "~" and so
    most likely continues it ("put a +1/+1 counter on ~. **it** gains haste"), rather than
    naming the firing object. A pronoun in the *same* clause as the "~" is that clause's other
    participant ("attach ~ to **it**", "~ deals 2 damage to **that creature**")."""
    # PAR-261: a gate on the source's own counters ("if ~ has 5 or more quest counters on it,") neither names the
    # source as an antecedent nor holds a pronoun of its own.
    lowered = _without_copy_exception(lowered)
    # The counter-tally exemptions apply only to a body that really gates on the source's counters (a Mission).
    counter_gated = _SOURCE_COUNTER_GATE_RE.search(lowered) is not None
    lowered = _SOURCE_COUNTER_GATE_RE.sub("if the gate holds,", lowered)
    for source in _EXPLICIT_SOURCE_RE.finditer(lowered):
        for pronoun in _BARE_PRONOUN_RE.finditer(lowered, source.end()):
            if _CLAUSE_BOUNDARY_RE.search(lowered, source.end(), pronoun.start()) is not None:
                # PAR-261: a *named* "that creature" after a pure counter bookkeeping mention of "~" (the quest
                # counter put on it, or a count of its counters in a gate) still names the firing creature.
                if counter_gated and pronoun.group(0).startswith("that ") and _source_counter_bookkeeping(lowered, source):
                    continue
                return True
    return False


def _is_bare_referent_seed(node: Any) -> bool:
    """A `trigger_subject_referent` that only seeds the referent (no body to run, no acting player)."""
    if isinstance(node, EffectSpec):
        return (
            node.type == "trigger_subject_referent" and not node.params.get("effects")
            and node.params.get("event_key") == GROUP_SUBJECT_KEY_SENTINEL
        )
    if not isinstance(node, dict) or node.get("type") != "trigger_subject_referent":
        return False
    params = node.get("params") or {}
    return not params.get("effects") and params.get("event_key") == GROUP_SUBJECT_KEY_SENTINEL


def _strip_bare_seeds(node: Any) -> Any:
    if isinstance(node, list):
        return [_strip_bare_seeds(item) for item in node if not _is_bare_referent_seed(item)]
    if isinstance(node, dict):
        return {key: _strip_bare_seeds(value) for key, value in node.items()}
    return node


def _hoist_referent_seed(effects: "list[EffectSpec]") -> "list[EffectSpec]":
    """PAR-123: one seed of the group trigger's referent, first in the list.

    A clause read through a previous-subject row brings its own seed, but a gate on it ("if it
    has flying, …") is evaluated *before* the gated effect runs, so a seed nested inside would come
    too late for the condition that names the referent. The seeds are lifted out and one is put at
    the front, where every clause and every gate after it can read it. A gate that names the
    referent with nothing chosen anywhere in the body ("if it's a creature, tap it") needs it too."""
    dumped = [e.to_dict() for e in effects]
    text = json.dumps(dumped, default=str)
    chosen_something = re.search(r'"target_kind": "(?!trigger_subject|source")', text) is not None
    if not any(_has_bare_seed_deep(d) for d in dumped) and not (
        '"of": "previous_target"' in text and not chosen_something
    ):
        return effects
    kept: list[EffectSpec] = []
    for data in dumped:
        if _is_bare_referent_seed(data):
            continue
        data = _strip_bare_seeds(data)
        kept.append(EffectSpec(data["type"], data.get("params") or {}, condition=data.get("condition")))
    return [EffectSpec("trigger_subject_referent", {"event_key": GROUP_SUBJECT_KEY_SENTINEL}), *kept]


def _has_bare_seed_deep(node: Any) -> bool:
    if _is_bare_referent_seed(node):
        return True
    if isinstance(node, list):
        return any(_has_bare_seed_deep(item) for item in node)
    if isinstance(node, dict):
        return any(_has_bare_seed_deep(value) for value in node.values())
    return False


#: Player-event heads whose body speaks of "that attacking player" / "that player" / "they" (RULE 506.4).
ATTACKING_PLAYER_EVENTS = frozenset({"PLAYER_ATTACKED", "ATTACKERS_DECLARED", "ATTACKERS_AT_DEFENDER"})
#: "that attacking player [may] <verb>" / "they <verb>" — the acting player named by the event.
_ATTACKING_PLAYER_SUBJECT_RE = re.compile(r"\b(?:that (?:attacking )?player|they)\b(?!')")
#: The effect types that read "you" through `GameContext.acting_player_id` *and* keep it across a pause
#: ("you may …", "if you do …"); anything else would quietly act for the ability's controller.
_ACTING_EVENT_PLAYER_TYPES = frozenset({
    "draw", "create_token", "pay_cost_then", "optional", "lose_life", "gain_life", "discard",
})


def _effect_types(node: Any) -> set[str]:
    """Every effect ``type`` named anywhere inside a spec dict (nested bodies included)."""
    found: set[str] = set()
    if isinstance(node, dict):
        if isinstance(node.get("type"), str) and "params" in node:
            found.add(node["type"])
        for value in node.values():
            found |= _effect_types(value)
    elif isinstance(node, list):
        for value in node:
            found |= _effect_types(value)
    return found


#: "…creates a tapped `<token>` that's attacking that opponent" — the token joins the combat attacking the
#: defender the `PLAYER_ATTACKED` event names (RULE 508.4; `attacker_creates_attacking_token`).
_ATTACKING_THAT_OPPONENT_RE = re.compile(
    r"^that (?:attacking )?player creates an? tapped (?P<token>.+?) that's attacking that opponent$"
)
#: The `create_token` params `attacker_creates_attacking_token` carries over.
_ATTACKING_TOKEN_PARAMS = ("power", "toughness", "colors", "subtypes", "keywords", "token_name")


def _attacking_token_body(body: str) -> Optional[list[EffectSpec]]:
    """Combat Calligrapher's / Ellie, Brick Master's "that attacking player creates a tapped `<token>`
    that's attacking that opponent": the token read by the ordinary create-token grammar, then handed to
    the attacker (not this ability's controller) already attacking the defender."""
    m = _ATTACKING_THAT_OPPONENT_RE.fullmatch(body.strip().lower().rstrip("."))
    if m is None:
        return None
    token_text, _, name = m.group("token").partition(" named ")
    effects = parse_effect_body(f"create a {token_text}", reading=ClauseReading(self_subject=True))
    if not effects or len(effects) != 1 or effects[0].type != "create_token":
        return None
    params = dict(effects[0].params)
    if name:
        params["token_name"] = name.title()
    if params.get("count", 1) != 1 or any(k not in (*_ATTACKING_TOKEN_PARAMS, "count", "tapped") for k in params):
        return None
    return [EffectSpec("attacker_creates_attacking_token", {
        k: params[k] for k in _ATTACKING_TOKEN_PARAMS if k in params
    })]


#: RULE 603.4: "When ~ enters, if `<condition>`, `<effect>`" — the condition is checked when the trigger event occurs
#: (the ability does not trigger at all otherwise: no stack object, no target to choose) and again as it resolves.
#: The per-effect gate every body keeps is the resolution check; this is the trigger-time one (`trigger["active_if"]`).
#: These leading-if conditions are also checked at the trigger event (RULE 603.4);
#: the effect retains its resolution-time check. Extend only with verified live predicates.
_INTERVENING_IF_AT_TRIGGER_KINDS = frozenset({
    "mana_color_spent_to_cast_at_least", "card_types_in_graveyard_at_least", "devoured_creature",
})
#: PAR-242 (Sphinx of False Conclusions): a self "dies" trigger's token copy of the dying permanent, optionally behind
#: the RULE 603.4 "if it isn't a token" gate (peeled separately, as `SELF_TOKEN_STATUS_GATES`).
SELF_DIES_TOKEN_COPY_RE = re.compile(r"(?:if it isn't a token, )?create a token that's a copy of it", re.IGNORECASE)
#: RULE 111.1: the source-token-status conditions a self-subject trigger's leading "if" turns into a trigger-time gate.
SELF_TOKEN_STATUS_GATES: tuple[dict[str, Any], ...] = (
    {"kind": "is_token"}, {"kind": "not", "condition": {"kind": "is_token"}},
)
ETB_INTERVENING_IF_RE = re.compile(r"^if (?P<cond>[^,]{2,160}),\s+.+$", re.IGNORECASE | re.S)


def etb_intervening_if(event: Any, condition: Optional[dict[str, Any]], body: str) -> Optional[dict[str, Any]]:
    if event != "ENTERS_BATTLEFIELD" or (condition or {}).get("subject") != "self":
        return None
    lead = ETB_INTERVENING_IF_RE.match(body.strip())
    gated = static_condition(lead.group("cond")) if lead is not None else None
    return gated if gated is not None and gated.get("kind") in _INTERVENING_IF_AT_TRIGGER_KINDS else None


def event_player_body(body: str) -> Optional[list[EffectSpec]]:
    """"Whenever a player attacks …, **that attacking player** creates a Treasure token" — the body as
    that player's own second-person clause, run *as* them (`trigger_subject_referent` ``acting``
    ``"event_player"``, RULE 109.5). Refused when the body also names "you"/a target, or when an effect
    in it does not honour the acting player."""
    attacking_token = _attacking_token_body(body)
    if attacking_token is not None:
        return attacking_token
    text = body.lower()
    if re.search(r"\b(?:you|your|target|opponent)\b", text) or _ATTACKING_PLAYER_SUBJECT_RE.search(text) is None:
        return None
    text = re.sub(r"\bif (?:the player|they) does?\b", "if you do", text)
    text = re.sub(
        r"\bthat (?:attacking )?player (may )?([a-z]+)\b",
        lambda m: f"you {m.group(1) or ''}{m.group(2) if m.group(1) else base_verb(m.group(2))}", text,
    )
    text = re.sub(r"\bthey\b", "you", text)
    if _ATTACKING_PLAYER_SUBJECT_RE.search(text) or "their" in text:
        return None
    effects = parse_effect_body(text, reading=ClauseReading(self_subject=True))
    if not effects or not all(_effect_types(e.to_dict()) <= _ACTING_EVENT_PLAYER_TYPES for e in effects):
        return None
    return [EffectSpec("trigger_subject_referent", {
        "acting": "event_player", "effects": [e.to_dict() for e in effects],
    })]


#: PAR-164: under a player-recipient DAMAGE head ("whenever an opponent is dealt 3 or more damage by a single
#: source, **that player** discards a card"), "that player" is the player who was dealt the damage (RULE 120.3),
#: not the controller of the damage source that the group-subject dispatch reads it as ("its controller", the same
#: printed pronoun family). The group dispatch's player operand is swapped for the `damaged_player` referent.
_GROUP_SUBJECT_CONTROLLER_OPERAND = {"of": "entering", "as": "controller"}
_DAMAGED_PLAYER_OPERAND = {"of": "damaged_player"}
#: PAR-315 / RULE 508.1b: under an attack / unblocked / blocked head the same "that player" is the attacked player,
#: which the combat event names as ``defending_player_id`` (`effect_conditions` ``attacked_player``).
_ATTACKED_PLAYER_OPERAND = {"of": "attacked_player"}
THAT_PLAYER_BODY_RE = re.compile(r"^that player\b", re.IGNORECASE)


#: "that player" under an Aura / Equipment head reads as the host's controller (RULE 303.4c): the same "you" operand.
_ATTACHED_CONTROLLER_OPERAND = {"of": "attached", "as": "controller"}


def _swap_operand(
    value: Any, replacement: dict[str, str] = _DAMAGED_PLAYER_OPERAND,
    swapped: tuple[dict[str, str], ...] = (_GROUP_SUBJECT_CONTROLLER_OPERAND,),
) -> Any:
    if value in swapped:
        return dict(replacement)
    if isinstance(value, dict):
        return {k: _swap_operand(v, replacement, swapped) for k, v in value.items()}
    if isinstance(value, list):
        return [_swap_operand(v, replacement, swapped) for v in value]
    return value


#: PAR-287: "that player" anywhere in a body (Sword of Body and Mind's "you create a Wolf and that player mills ...").
THAT_PLAYER_ANYWHERE_RE = re.compile(r"\bthat player\b", re.IGNORECASE)
#: PAR-287: "its controller" names the dealer's (or host's) controller: a body that also says it is not retargeted.
_DEALER_CONTROLLER_RE = re.compile(r"\b(?:its|their|that creature's) controller\b", re.IGNORECASE)
#: A mill that read "that player" through the previous clause's referent; under a damage-to-a-player head it is the damaged one.
_PREVIOUS_CONTROLLER_SELECTOR = "previous_subject_controller"
_DAMAGED_PLAYER_SELECTOR = "event_damaged_player"


def names_damaged_player(body: str) -> bool:
    """Whether ``body`` names "that player" (the damaged one) and never "its controller" (the dealer's)."""
    return THAT_PLAYER_ANYWHERE_RE.search(body) is not None and _DEALER_CONTROLLER_RE.search(body) is None


def retarget_that_player_to_damaged(effects: list[EffectSpec]) -> Optional[list[EffectSpec]]:
    """``effects`` with the group dispatch's (or the host's, RULE 303.4c) controller operand read as the damaged
    player (RULE 120.3); ``None`` when a shape keyed to the source's controller by another route (a selector name)
    is present, so it fails closed. A mill's previous-clause controller selector is the damaged player too."""
    if "trigger_subject_controller" in repr(effects) or "attached_permanent_controller" in repr(effects):
        return None
    swapped = (_GROUP_SUBJECT_CONTROLLER_OPERAND, _ATTACHED_CONTROLLER_OPERAND)
    out: list[EffectSpec] = []
    for e in effects:
        params = _swap_operand(e.params, _DAMAGED_PLAYER_OPERAND, swapped)
        if e.type == "mill" and params.get("selector") == _PREVIOUS_CONTROLLER_SELECTOR:
            params = {**params, "selector": _DAMAGED_PLAYER_SELECTOR}
        out.append(EffectSpec(e.type, params, condition=e.condition))
    return out


def retarget_that_player_to_attacked(effects: list[EffectSpec]) -> Optional[list[EffectSpec]]:
    """`retarget_that_player_to_damaged`'s sibling for a combat head: the dispatch's controller operand is the
    attacked player (the attacker's own controller is "you", never "that player")."""
    if "trigger_subject_controller" in repr(effects):
        return None
    return [EffectSpec(e.type, _swap_operand(
        e.params, _ATTACKED_PLAYER_OPERAND, (_GROUP_SUBJECT_CONTROLLER_OPERAND, _ATTACHED_CONTROLLER_OPERAND)), condition=e.condition)
            for e in effects]


def stamp_group_pronoun(
    condition: Optional[dict[str, Any]], body: str, effects: "list[EffectSpec]"
) -> "Optional[list[EffectSpec]]":
    stamped = _stamp_group_pronoun_once(condition, body, effects)
    if stamped is not None and (condition or {}).get("subject") in ("group", "self_or_group"):
        stamped = _hoist_referent_seed(stamped)
    return stamped


def _stamp_group_pronoun_once(
    condition: Optional[dict[str, Any]], body: str, effects: "list[EffectSpec]"
) -> "Optional[list[EffectSpec]]":
    """PAR-123: under a group-subject trigger a bare "it"/"that creature" is the
    object that fired the trigger, whereas "~" is the source. Both parse to the
    same untargeted spec (``target_kind: None``, which acts on the source), so the
    parser — the only place the words are visible — stamps the pronoun reading
    onto each effect that has a trigger-subject mode; the binder resolves which
    event field names the object (`GROUP_SUBJECT_KEY_SENTINEL`).

    A body that also names the source explicitly is left as parsed ("exile ~, then
    return it" is the source both times). ``None`` means the body is a pronoun
    reading no effect here can honour, so the line stays unclaimed."""
    subject = (condition or {}).get("subject")
    if subject not in (None, "self", "group", "self_or_group") and any(_reads_blocked_attacker(e) for e in effects):
        return None  # "equipped creature becomes blocked, it deals …": "it" isn't the source
    if subject not in ("group", "self_or_group"):
        return effects
    # A handler may already identify an explicit trigger referent even when
    # a leading condition names the source (Hixus). Unlike an ambiguous bare
    # "it", this reference still names the firing creature (RULE 603.1).
    effects = [EffectSpec(e.type, {**e.params, "trigger_event_key": GROUP_SUBJECT_KEY_SENTINEL},
                          condition=e.condition)
               if e.params.get("target_kind") == "trigger_subject" and not e.params.get("trigger_event_key")
               else e for e in effects]
    lowered = body.lower()
    # A leading state condition does not introduce an action's new referent.
    # "If ~ entered this turn, exile that creature" still names the dealer.
    referent_body = re.sub(r"^if [^,]+,\s*", "", lowered)
    # RULE 707.9a: in a copy's "…, except it has …" tail "it" is the copy (the source), not the firing object.
    referent_body = _without_copy_exception(referent_body)
    if _stamped_dealer_any(effects) and pronoun_continues_source(referent_body):
        return None  # "put a counter on ~. it gains haste": that "it" is the source, not the firing object
    if _BARE_PRONOUN_RE.search(lowered) is None or _EXPLICIT_SOURCE_RE.search(lowered):
        return effects
    stamped: list[EffectSpec] = []
    index = 0
    while index < len(effects):
        effect = effects[index]
        following = effects[index + 1] if index + 1 < len(effects) else None
        if (effect.type == "exile" and effect.params.get("target_kind", "unset") is None
                and following is not None and following.type == "return_self_to_battlefield"):
            # "exile it, then return it to the battlefield under its owner's control"
            if following.params != {"tapped": False}:
                return None
            stamped.append(EffectSpec(
                "blink", {"target_kind": "trigger_subject",
                          "trigger_event_key": GROUP_SUBJECT_KEY_SENTINEL},
                condition=effect.condition,
            ))
            index += 2
            continue
        if IT_DEALS_RE.search(lowered) and deals_damage(effect):
            # "Whenever a Dragon you control enters, it deals X damage to any target" — the
            # entering Dragon is the damage source (lifelink, deathtouch, protection), not the
            # Enchantment that carries the ability (PAR-123).
            effect = stamp_damage_dealer(effect)
        elif effect.type == "sacrifice_self" and not effect.params:
            # "Whenever another Goblin you control becomes blocked, sacrifice it." — the firing
            # creature, not the permanent carrying the ability.
            effect = EffectSpec(
                "sacrifice_self",
                {"target_kind": "trigger_subject", "trigger_event_key": GROUP_SUBJECT_KEY_SENTINEL},
                condition=effect.condition,
            )
        elif effect.type == "return_self_to_battlefield" and "target_kind" not in effect.params:
            # "Whenever a creature you control dies, return it to the battlefield under its
            # owner's control" — the dead creature, not the permanent carrying the ability.
            effect = EffectSpec(
                "return_self_to_battlefield",
                {**effect.params, "target_kind": "trigger_subject",
                 "trigger_event_key": GROUP_SUBJECT_KEY_SENTINEL},
                condition=effect.condition,
            )
        elif effect.type in _GROUP_IT_RETARGETED and effect.params.get("target_kind", "unset") is None:
            params = dict(effect.params)
            params["target_kind"] = "trigger_subject"
            params["trigger_event_key"] = GROUP_SUBJECT_KEY_SENTINEL
            effect = EffectSpec(effect.type, params, condition=effect.condition)
        elif effect.type == "create_delayed_trigger" and effect.params.get("capture") == "previous_or_self":
            # "Whenever a Minotaur attacks this turn, it gets +2/+0 … Destroy that creature at
            # end of combat." (Consuming Rage) — the delayed clause's own "that creature" parsed
            # to the default ``previous_or_self`` fallback (PAR-30), which has nothing to fall
            # back *to* here (this resolution's earlier effect is itself untargeted) and would
            # silently capture this ability's own source instead. Under a confirmed group
            # subject a bare pronoun is always RULE 603.1's firing object, never that fallback
            # chain — an explicit "~" would have failed the ``_EXPLICIT_SOURCE_RE`` guard above
            # before reaching here, so this can only be the pronoun.
            params = dict(effect.params)
            params["capture"] = "trigger_subject"
            params["trigger_event_key"] = GROUP_SUBJECT_KEY_SENTINEL
            params.pop(NEEDS_BLOCK_HEAD, None)
            effect = EffectSpec(effect.type, params, condition=effect.condition)
        if _reads_blocked_attacker(effect) and not _stamped_dealer(effect):
            return None  # the blocked attacker is the firing object; nothing here names it
        stamped.append(effect)
        index += 1
    return stamped


#: Effect params that read a number or object off the firing event. An `ATTACKERS_DECLARED`
#: event names the whole declaration, not "that many"/"that creature": the count a body means
#: depends on the head's own filter, which the shared event cannot carry.
EVENT_READS = (
    "amount_from_trigger_event", "count_from_trigger_event", "pt_from_trigger_event", "any_amount_from_trigger_event",
)


#: The `ATTACKS`-style event field naming the creature a DAMAGE event dealt damage to.
DAMAGED_CREATURE_EVENT_KEY = "target_id"


def retarget_damaged_creature_riders(effects: "list[EffectSpec]") -> "list[EffectSpec]":
    """Under a "deals combat damage to a creature" head a delayed rider's "that creature" is the damaged creature:
    its ``previous_or_self`` capture (which would fall back to the source) names the event's ``target_id`` instead."""
    out: "list[EffectSpec]" = []
    for e in effects:
        if e.type == "create_delayed_trigger" and e.params.get("capture") == "previous_or_self":
            params = {k: v for k, v in e.params.items() if k != NEEDS_BLOCK_HEAD}
            params["capture"] = "trigger_subject"
            params["trigger_event_key"] = DAMAGED_CREATURE_EVENT_KEY
            e = EffectSpec(e.type, params, condition=e.condition)
        out.append(e)
    return out


#: PAR-287 / RULE 120.3: under a group "<dealer> deals [combat] damage to a <recipient>" head a body's "that <noun>"
#: names the dealer or the recipient by its noun. The nouns a head's filters use for the two parties:
_THAT_NOUN_RE = re.compile(r"\bthat (creature|planeswalker|permanent|battle|artifact|enchantment|land)\b(?!')", re.IGNORECASE)


def group_damage_referent_party(head_condition: "dict[str, Any]", body: str) -> Optional[str]:
    """Which party of a group damage-to-a-permanent head the body's "that <noun>" names: ``"recipient"``, ``"dealer"``,
    ``"ambiguous"`` (both parties are that noun: "a creature you control deals combat damage to a creature, ... that
    creature"), or ``None`` when the body names no such noun or the head states no recipient noun."""
    named = {m.group(1).lower() for m in _THAT_NOUN_RE.finditer(body)}
    recipient = (head_condition.get("recipient_filter") or {}).get("card_type")
    if len(named) != 1 or recipient is None:
        return None
    noun = next(iter(named))
    dealer = (head_condition.get("filter") or {}).get("card_type")
    if noun == recipient:
        # Only a dealer filter that is the same bare noun makes the pronoun ambiguous; "a Sliver" is not "a creature".
        return "ambiguous" if dealer == noun or (noun == "permanent") else "recipient"
    if noun == dealer:
        return "dealer"
    return None


def stamp_group_recipient(effects: "list[EffectSpec]") -> "Optional[list[EffectSpec]]":
    """``effects`` with the group trigger's firing-object key swapped for the damage event's recipient (``target_id``);
    ``None`` when the body also reads the dealer (a ``dealer_event_key``), which one referent cannot serve."""
    text = json.dumps([e.to_dict() for e in effects], default=str)
    if GROUP_SUBJECT_KEY_SENTINEL not in text:
        return list(effects)  # already read off the recipient (a delayed rider keyed to ``target_id``)
    if "dealer_event_key" in text:
        return None
    swapped = json.loads(text.replace(f'"{GROUP_SUBJECT_KEY_SENTINEL}"', f'"{DAMAGED_CREATURE_EVENT_KEY}"'))
    return [EffectSpec(d["type"], d.get("params") or {}, condition=d.get("condition")) for d in swapped]


#: PAR-287: a body whose first sentence acts on "that creature" -- under a damage-to-a-creature head, the damaged one.
RECIPIENT_BODY_RE = re.compile(r"[^.]*\bthat creature\b")


#: PAR-287: the one informational body whose "that player" is the damaged player (Walker of Secret Ways).
DAMAGED_PLAYER_LOOK_RE = re.compile(r"look at that player's hand\.?")


#: RULE 509.3: the far side of a block relation, named "that creature" (or "the other creature").
_BLOCK_OTHER_RE = re.compile(r"\bthat creature\b|\bthe other creature\b", re.IGNORECASE)
_BLOCK_OTHER_NAME_RE = re.compile(r"\bthe other creature\b", re.IGNORECASE)


def block_related_body(
    body: str, head_trigger: dict[str, Any], subject: Optional[str],
) -> "list[EffectSpec] | None":
    """PAR-227: a block-relation head's body that acts on "that creature" (RULE 509.3) -- damage dealt to it, a
    characteristic change, an ability gained or lost -- bound as a per-relation `trigger_related_referent`.

    The body is read as the group-trigger reading reads "that creature" (the firing object), then that object is
    re-pointed from the head's own subject to each creature on the other side of the block. Anything still naming the
    firing event afterwards, or a damage source that is not the head's own creature, fails closed."""
    body = _BLOCK_OTHER_NAME_RE.sub("that creature", body)
    if _BLOCK_OTHER_RE.search(body) is None or subject not in ("self", "attached_permanent"):
        return None
    read = parse_effect_body(body, reading=ClauseReading(group_subject=True))
    if not read:
        return None

    unbound_source = False

    def repoint(node: Any) -> Any:
        nonlocal unbound_source
        if isinstance(node, dict):
            params = node.get("params")
            if isinstance(params, dict) and "target_kind" in params and params["target_kind"] is None:
                if node.get("type") != "tap":
                    unbound_source = True  # a bare None acts on the source: not the other creature
                else:
                    # "tap that creature": the untargeted tap names the referent explicitly
                    node = {**node, "params": {k: v for k, v in params.items() if k != "target_kind"}
                            | {"previous_subject": True}}
            if node.get("type") == "trigger_subject_referent":
                params = node.get("params") or {}
                if params.get("event_key") == GROUP_SUBJECT_KEY_SENTINEL:
                    inner = [repoint(e) for e in params.get("effects") or []]
                    return {"type": "trigger_subject_referent", "params": {"referent": "previous_subject",
                                                                          **({"effects": inner} if inner else {})}}
            return {k: repoint(v) for k, v in node.items()}
        if isinstance(node, list):
            return [repoint(v) for v in node]
        if node == "trigger_subject_controller":
            return "previous_subject_controller"
        return node

    effects: "list[dict[str, Any]]" = []
    for e in read:
        d = repoint(e.to_dict())
        if d["type"] == "trigger_subject_referent" and not (d["params"].get("effects")):
            continue  # the bare seed: the wrapper below seeds each relation instead
        effects.append(d)
    text = repr(effects)
    if (
        unbound_source or not effects or GROUP_SUBJECT_KEY_SENTINEL in text
        or "trigger_subject" in text.replace("trigger_subject_referent", "")
    ):
        return None
    if subject == "attached_permanent" and "damage" in text:
        return None  # the damage source would be the Equipment/Aura, not the host
    return [EffectSpec("trigger_related_referent", {
        "effects": effects, "related_filter": dict(head_trigger.get("related_filter") or {}),
    })]


def retarget_block_relation(
    event: "str | list[str]", head_trigger: dict[str, Any], effects: "list[EffectSpec]"
) -> "list[EffectSpec]":
    """Under a block-relation head ("~ blocks or becomes blocked by a non-Wall creature")
    "that creature" is the creature on the other side of the block. A delayed effect built
    from it captured the source when nothing preceded it; it now captures the event's
    related creatures, filtered as the head is."""
    events = event if isinstance(event, list) else [event]
    if not events or not set(events) <= {"BLOCKS", "BECOMES_BLOCKED"}:
        return effects
    out: "list[EffectSpec]" = []
    for e in effects:
        if e.params.get("trigger_related") and "related_filter" not in e.params:
            e = EffectSpec(
                e.type, {**e.params, "related_filter": dict(head_trigger.get("related_filter") or {})},
                condition=e.condition,
            )
        if e.type == "create_delayed_trigger" and e.params.get("capture") == "previous_or_self":
            params = dict(e.params)
            params["capture"] = "trigger_related"
            params["related_filter"] = dict(head_trigger.get("related_filter") or {})
            params.pop(NEEDS_BLOCK_HEAD, None)
            e = EffectSpec(e.type, params, condition=e.condition)
        elif (
            e.type == "create_delayed_trigger" and e.params.get("capture") == "trigger_related"
            and "related_filter" not in e.params
        ):
            e = EffectSpec(
                e.type, {**e.params, "related_filter": dict(head_trigger.get("related_filter") or {})},
                condition=e.condition,
            )
        out.append(e)
    return out


#: What "that many" measures for a counting head: the attack batch (RULE 508.3a, captured
#: by `trigger_quantities.capture_attackers`) or an object batch (RULE 603.2c, captured by
#: `binding.core`'s batch capture as the event's ``matching_count``).
_ATTACK_COUNT_AMOUNT: dict[str, Any] = {"kind": "attackers_declared"}
BATCH_COUNT_AMOUNT: dict[str, Any] = {"kind": "trigger_event", "field": "matching_count"}
#: "that much"/"that many" after a damage head is the damage that event dealt (its ``amount``).
_DAMAGE_EVENT_AMOUNT: dict[str, Any] = {"kind": "trigger_event", "field": "amount"}
#: PAR-287 (RULE 122.6 / 603.2c): "that many" after a counters-put head is the counters that placement put (the `COUNTER`
#: event's ``amount``, `RulesEngine.add_counters`): Bioessence Hydra's "put that many +1/+1 counters on ~", Lonis's
#: "investigate that many times".
_COUNTER_EVENT_AMOUNT: dict[str, Any] = {"kind": "trigger_event", "field": "amount"}
_LIFE_LOST_EVENT_AMOUNT: dict[str, Any] = {"kind": "trigger_event", "field": "amount"}
HEAD_COUNT_AMOUNTS: dict[str, dict[str, Any]] = {
    "ATTACKERS_DECLARED": _ATTACK_COUNT_AMOUNT, "ATTACKERS_AT_DEFENDER": _ATTACK_COUNT_AMOUNT,
    "EVENT_BATCH": BATCH_COUNT_AMOUNT,
    "DAMAGE": _DAMAGE_EVENT_AMOUNT,
    "COUNTER": _COUNTER_EVENT_AMOUNT,
    # PAR-321 (RULE 119.3 / 603.2c): "that many" after a life-loss head is the life lost (`LIFE_LOST`'s ``amount``,
    # `RulesEngine.lose_life`): Mindcrank's "that player mills that many cards".
    "LIFE_LOST": _LIFE_LOST_EVENT_AMOUNT,
    # PAR-321 (RULE 122.6): "that many" after a counters-removed head is the batch's ``amount``.
    "COUNTERS_REMOVED": _COUNTER_EVENT_AMOUNT,
}
#: PAR-321: player-event heads whose body's leading "they" is the event's acting player (`targeting.trigger_player_antecedent`).
EVENT_PLAYER_THEY_EVENTS: frozenset[str] = frozenset({"SPELL_CAST", "LAND_PLAYED", "LIFE_LOST"})
def attackers_declared_filter(group_filter: dict[str, Any]) -> Optional[dict[str, Any]]:
    """RULE 508.3a (PAR-321): a "one or more <subtype> you control attack" head's group filter as the object filter
    `ATTACKERS_DECLARED` counts the declaration with (Poetic Ingenuity's "create that many Treasure tokens").

    An empty group is every creature. A creature-subtype group maps to the subtype filter and an ordinary object
    filter rides along; the other group keys (an excluded subtype, a second card type, "suspected") have no declared-
    attackers equivalent, so they answer ``None`` and the clause stays unclaimed.
    """
    if set(group_filter) - {"subtypes_any", "object_filter"}:
        return None
    subtypes = list(group_filter.get("subtypes_any") or [])
    declared: dict[str, Any] = dict(group_filter.get("object_filter") or {})
    if not subtypes and not declared:
        return {"card_type": "creature"}
    if len(subtypes) == 1:
        declared["subtype"] = subtypes[0]
    elif subtypes:
        declared["subtype_any"] = subtypes
    return declared


#: `targeting.TARGET_COUNT_SELECTORS`' name the "up to x target ..." rows read X as (the ability's own announced {X}).
_ANNOUNCED_X_COUNT_SELECTOR = "source_x_paid"


def bind_target_count_to_event(
    effects: "list[EffectSpec]", count_amount: dict[str, Any], event: str,
) -> "Optional[list[EffectSpec]]":
    """RULE 601.2c / 603.3d (PAR-321): "return up to that many target permanents ..." under a counting head announces
    as many targets as the firing event's count (Cephalid Constable's combat damage). The body was read with a
    literal X, so its "up to x target" count names the announced {X}; re-key that to the event's payload
    (`targeting.resolved_count` reads a ``trigger_event`` dict ``count_selector`` as the trigger goes on the stack).

    ``None`` when no target count read X (nothing to rebind) or X is also used anywhere else in the body.
    """
    rebound = 0

    def rewrite(value):
        nonlocal rebound
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if not isinstance(value, dict):
            return value
        out = {key: rewrite(item) for key, item in value.items()}
        if out.get("count_selector") == _ANNOUNCED_X_COUNT_SELECTOR:
            out["count_selector"] = {**count_amount, "event": event}
            rebound += 1
        return out

    rewritten = rewrite([effect.to_dict() for effect in effects])
    if not rebound or "$x" in repr(rewritten) or "source_x" in repr(rewritten):
        return None
    return [EffectSpec(e["type"], e.get("params") or {}, condition=e.get("condition")) for e in rewritten]


THAT_MANY_RE = re.compile(r"\bthat (?:many|much)\b", re.IGNORECASE)


def reads_event_amount(effects: "list[EffectSpec]") -> bool:
    """Whether any effect (nested compositions included) reads a number off the firing event (`EVENT_READS`)."""
    return any(key in repr(effect.to_dict()) for effect in effects for key in EVENT_READS)


def batch_discard_this_way(effects: "list[EffectSpec]", batch_of: Optional[str]) -> "list[EffectSpec]":
    """PAR-286 (RULE 603.2c / 701.9): under "whenever you discard one or more cards", "for each card discarded this way"
    counts the cards of the batch that triggered the ability (its captured ``matching_count``), not a window opened in
    the body (the discard happened before the ability existed). Only the plain pool read is rewritten; its modifiers
    (``multiply`` ...) stay."""
    if batch_of != "DISCARD_CARD":
        return effects

    def rewrite(value):
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if not isinstance(value, dict):
            return value
        if value.get("kind") == "this_way_count" and value.get("pool") == "discarded" and not (
            set(value) - {"kind", "pool", "multiply", "plus", "minus"}
        ):
            return {**BATCH_COUNT_AMOUNT, **{k: v for k, v in value.items() if k not in ("kind", "pool")}}
        return {key: rewrite(item) for key, item in value.items()}

    return [EffectSpec(e["type"], e.get("params") or {}, condition=e.get("condition"))
            for e in rewrite([effect.to_dict() for effect in effects])]


def bind_attack_count(
    effects: "list[EffectSpec]", amount: Optional[dict[str, Any]] = None,
) -> "Optional[list[EffectSpec]]":
    """Bind 'that many/much' to this head's own count (RULE 508.3a / 603.2c).

    Walk compositions too: an optional/conditional draw has the same referent.
    Other event fields and an unresolved 'that creature' still fail closed.
    """
    # An adjacent library choice supplies 'that creature'; run the delayed
    # instruction only for the selected hit, including after an interactive pause.
    linked = []
    for effect in effects:
        if (effect.type == "create_delayed_trigger"
                and effect.params.get("capture") == "previous_or_self"
                and linked and linked[-1].type == "impulsive_look"
                and linked[-1].params.get("hit_destination", "").startswith("battlefield")
                and effect.condition is None):
            look = linked.pop()
            delayed = EffectSpec(effect.type, {**effect.params, "capture": "created_objects"})
            linked.append(EffectSpec(look.type, {
                **look.params,
                "hit_effect_specs": [*look.params.get("hit_effect_specs", []), delayed.to_dict()],
            }, condition=look.condition))
        else:
            linked.append(effect)
    effects = linked
    reads_count = False
    #: A delayed "it"/"that creature" capture inside the wrapped (`bind`) body would lose its referent.
    delayed_referent = False

    def rewrite(value):
        nonlocal reads_count, delayed_referent
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if not isinstance(value, dict):
            return value
        if value.get("type") == "create_delayed_trigger" and (
            value.get("params", {}).get("capture") == "previous_or_self"
        ):
            delayed_referent = True
        result = {}
        for key, item in value.items():
            if key in EVENT_READS:
                if item not in ("amount", "that_much") or key == "pt_from_trigger_event":
                    raise ValueError("Not an attacker count")
                reads_count = True
                result[key.removesuffix("_from_trigger_event")] = "$attack_count"
            else:
                result[key] = rewrite(item)
        return result

    try:
        rewritten = rewrite([effect.to_dict() for effect in effects])
    except ValueError:
        return None
    if not reads_count:
        # RULE 508.3d: a body that never counts the attackers (War Effort's token, Alora's unblockable creature)
        # runs as written, once per declaration, so its own referents stay valid.
        return effects
    if delayed_referent:
        return None
    return [EffectSpec("bind", {"name": "attack_count",
                               "amount": dict(amount or _ATTACK_COUNT_AMOUNT),
                               "effects": rewritten})]


def group_it_would_hit_source(
    condition: Optional[dict[str, Any]], body: str, effects: "list[EffectSpec]"
) -> bool:
    """Whether a group-subject trigger body's bare "it" would still resolve to the
    wrong permanent after `stamp_group_pronoun`. With a group subject "it" is the
    object that fired the trigger, but an effect parsed with no target
    (``target_kind: None``), or a delayed capture that falls back to the source,
    acts on *this ability's own source* — wrong, yet claimed."""
    if (condition or {}).get("subject") not in ("group", "self_or_group"):
        return False
    if _BARE_PRONOUN_RE.search(body.lower()) is None:
        return False
    return any(
        (
            e.params.get("target_kind", "unset") is None
            # PAR-124: `copy_permanent`'s own ``referent="trigger_event"``
            # (Theoretical Duplication's "create a token that's a copy of
            # **that creature**.") already reads the *firing object*, not
            # the source, via `_COPY_PERMANENT_GROUP_RE`'s own group-
            # subject-gated row — a correct resolution this guard would
            # otherwise reject on the same ``target_kind: None`` shape a
            # plain source fallback uses. "Previous" likewise names an explicit prior pick.
            and not (e.type == "copy_permanent" and e.params.get("referent") in ("trigger_event", "previous"))
        )
        or (e.type == "create_delayed_trigger" and e.params.get("capture") == "previous_or_self")
        for e in effects
    )


#: RULE 303.4 / 301.5: under an "enchanted / equipped creature <attacks | blocks | becomes blocked | becomes the target of
#: ...>" head the one creature the event is about *is* the attached host, so a body's "that creature" / "it" names that
#: creature (read off the firing event, so it still resolves once the Aura has left). The damage heads are not here: they
#: name a second creature (the recipient), which `recipient_body` reads.
ATTACHED_HOST_EVENTS = frozenset({"ATTACKS", "BLOCKS", "BECOMES_BLOCKED", "BECOMES_TARGET"})
#: A body that picks or names some other object ("target creature", "another creature") is not a plain host body.
_OTHER_OBJECT_RE = re.compile(r"\b(?:target|another|other|each|all)\b")


#: A head that names a second creature: "blocks a creature", "becomes blocked by a creature". The parsed head drops it
#: when the creature is just "a creature" (no related filter), so the printed head text is what says so.
_RELATED_CREATURE_HEAD_RE = re.compile(r"\bblocked by\b|\bblocks (?:a|an|another|one|\d)\b")


def _names_related_object(head_trigger: dict[str, Any], head_text: str) -> bool:
    return (
        "related_filter" in head_trigger or bool(head_trigger.get("per_blocked_creature"))
        or _RELATED_CREATURE_HEAD_RE.search(head_text.lower()) is not None
    )


def attached_host_body(
    body: str, event: Any, head_trigger: dict[str, Any], subject: Any, head_text: str,
) -> Optional[list[EffectSpec]]:
    """The body of an attached-host event trigger, its "that creature" / "it" read as the event's creature (the host).
    ``None`` when the head is not such a host event, names a related object ("... becomes blocked by a creature": two
    candidates for "that creature"), or the body names another object."""
    events = set(event) if isinstance(event, list) else {event}
    if subject != "attached_permanent" or not events <= ATTACHED_HOST_EVENTS or _names_related_object(head_trigger, head_text):
        return None
    if _OTHER_OBJECT_RE.search(body.lower()):
        return None
    effects = parse_effect_body(body, reading=ClauseReading(group_subject=True))
    # A top-level effect left at ``target_kind: None`` that the binder does not repoint would act on the Aura / Equipment
    # itself ("it can't be blocked", Writ of Passage), so such a body stays unclaimed.
    if effects is None or any(acts_on_source_under_attached(e) for e in effects):
        return None
    return effects


#: RULE 701.3b / 603.2: "whenever ~ becomes attached to a creature, <body>" -- the `ATTACHED_TO_CREATURE` event names the
#: Equipment / Aura (``instance_id``, the source) and the creature it became attached to (``target_id``), so a body's
#: "that creature" is the ``target_id`` one. A bare "it" stays the source and is not read here.
ATTACHED_TO_CREATURE_EVENT = "ATTACHED_TO_CREATURE"
_ATTACH_TARGET_EVENT_KEY = "target_id"
_THAT_CREATURE_RE = re.compile(r"\bthat creature\b(?!')")


def attach_target_body(body: str, event: Any, head_trigger: dict[str, Any], subject: Any) -> Optional[list[EffectSpec]]:
    """The body of "whenever ~ becomes attached to a creature" with its "that creature" read as the new host."""
    if (subject != "self" or event != ATTACHED_TO_CREATURE_EVENT or head_trigger.get("attach_host")
            or _THAT_CREATURE_RE.search(body) is None or BARE_IT_RE.search(body) or "~" in body
            or _OTHER_OBJECT_RE.search(body.lower())):
        return None
    effects = parse_effect_body(body, reading=ClauseReading(previous_subject=True))
    if not effects:
        return None
    return [EffectSpec("trigger_subject_referent", {"event_key": _ATTACH_TARGET_EVENT_KEY}), *effects]


#: RULE 303.4 / 608.2c: "When this Aura enters, if enchanted creature has toxic, **that creature** gains hexproof" -- the
#: gate names the host, so the gated clause's "that creature" is the same enchanted creature (Maze's Mantle).
_ENCHANTED_GATE_RE = re.compile(r"^(?P<lead>if (?P<noun>enchanted (?:creature|permanent|land)) [^,]+, )(?P<rest>.+)$")


def enchanted_gate_referent(body: str) -> str:
    """``body`` with the "that creature" of a gated clause spelled as the "enchanted creature" its gate names."""
    m = _ENCHANTED_GATE_RE.match(body)
    if m is None or _OTHER_OBJECT_RE.search(m.group("rest")) or "~" in m.group("rest"):
        return body
    rest = re.sub(r"\bthat (?:creature|permanent|land)\b(?!')", m.group("noun"), m.group("rest"))
    return m.group("lead") + rest


#: The attached-host trigger events whose firing object is the host itself (``instance_id``, or ``source_id`` for a
#: damage dealer), so a gate on "it" reads that object even after the host and the Aura have parted (RULE 400.7: a dying
#: host is no longer attached when its "dies" trigger resolves).
HOST_IS_EVENT_OBJECT_EVENTS = ATTACHED_HOST_EVENTS | {"DIES"}
_ATTACHED_REFERENT = "attached"
_EVENT_OBJECT_REFERENT = "trigger_subject"


def _rescope_attached_node(node: Any) -> Any:
    if isinstance(node, list):
        return [_rescope_attached_node(item) for item in node]
    if isinstance(node, dict):
        return {
            key: _EVENT_OBJECT_REFERENT if key == "of" and value == _ATTACHED_REFERENT else _rescope_attached_node(value)
            for key, value in node.items()
        }
    return node


def host_event_gates(effects: "list[EffectSpec]", event: Any, subject: Any) -> "list[EffectSpec]":
    """RULE 303.4 / 301.5 (PAR-323): under "whenever equipped creature dies / enchanted creature attacks", a gate on "it"
    ("... if it's a Samurai card") asks about the event's creature, not about whatever the Aura / Equipment is attached to
    when the ability finally resolves. Only the effects' *conditions* are rescoped; their params keep their reading."""
    events = set(event) if isinstance(event, list) else {event}
    if subject != "attached_permanent" or not events <= HOST_IS_EVENT_OBJECT_EVENTS:
        return effects
    return [EffectSpec(e.type, e.params, condition=_rescope_attached_node(e.condition)) for e in effects]
