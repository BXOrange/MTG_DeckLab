"""Segmenter: referents (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from ..catalogue.clause_reading import (
    CHOSEN_PLAYER_NOUN,
    COUNTERED_REFERENT,
    CREATED,
    CREATED_GROUP_REFERENT,
    CREATED_REFERENT,
    ClauseReading,
    EXILED_REFERENT,
    EXILE_POOL,
    PLAYER,
    MILLED_REFERENT,
    REVEALED_REFERENT,
    Referent,
    SELECTOR_REFERENT,
    STANDALONE,
    TARGET,
    TARGET_REFERENT,
)
from dataclasses import replace
from typing import Optional
from ..catalogue.clause_primitives import announces_creature_target, has_plural_targets
from ..spec import EffectSpec
from .late import parse_effect_body

#: PAR-117: the referent that answers "its controller may `<effect>`"'s own
#: question ("do they?") is also who *performs* the body once they say yes —
#: RULE 603.1's "its controller" is one pronoun, not two independent
#: resolutions of "whoever that is". `OptionalEffect`'s own pause (the
#: player has to actually answer before the body runs) already re-resolves
#: this referent at that later point (`_resume_composite_optional`), so the
#: inner effect just needs to *ask* for it explicitly instead of falling
#: back to its usual "this ability's own controller" default, which would
#: silently be the wrong player whenever the referent differs (Edric,
#: Spymaster of Trest: Edric's own controller vs. the damaging creature's).
#: A closed, narrow map — only the two inner effect shapes real cards in
#: this cluster actually use (`draw`'s own referent-dict ``player`` field;
#: `create_token`'s closed-string ``creators`` enum, needing the
#: referent's own ``of`` translated rather than passed through raw).
#: Anything else stays unrewritten rather than guessing a field name that
#: might not exist on that effect type.
_OPTIONAL_REFERENT_CREATORS_BY_OF: dict[str, str] = {
    "entering": "trigger_subject_controller",
    "previous_target": "previous_target_controller",
}


def rewrite_optional_referent_actor(spec_dict: dict, referent: dict) -> dict:
    if spec_dict.get("type") == "draw" and "player" not in (spec_dict.get("params") or {}):
        spec_dict = {**spec_dict, "params": {**spec_dict.get("params", {}), "player": referent}}
    elif spec_dict.get("type") == "create_token" and "creators" not in (spec_dict.get("params") or {}):
        creators = _OPTIONAL_REFERENT_CREATORS_BY_OF.get(str(referent.get("of")))
        if creators is not None:
            spec_dict = {
                **spec_dict, "params": {**spec_dict.get("params", {}), "creators": creators},
            }
    return spec_dict


#: PAR-142: "… for as long as it/that `<noun>` has a `<kind>` counter on it" (Aquitect's Will, Minas Morgul,
#: Aven Mimeomancer) — RULE 611.2b's condition-bounded duration over the pick an earlier clause just put the
#: counter on. Not a clause of its own: the body before (or after) it is an ordinary duration-less effect, and
#: this only re-times the `grant_until` it produced (`game/durations.py`, ``for_as_long_as``, its condition
#: read off the locked permanent — ``of="affected"``).
_FOR_AS_LONG_AS_WHO = r"(?:it|that [a-z]+)"
_FOR_AS_LONG_AS_COUNTER = (
    rf"for as long as (?P<who>{_FOR_AS_LONG_AS_WHO}) has an? (?P<kind>[a-z0-9+/\- ]+?) counters? on it"
)
_FOR_AS_LONG_AS_TRAILING_RE = re.compile(
    rf"^(?P<body>.+?),?\s+{_FOR_AS_LONG_AS_COUNTER}$", re.IGNORECASE | re.DOTALL,
)
_FOR_AS_LONG_AS_LEADING_RE = re.compile(
    rf"^{_FOR_AS_LONG_AS_COUNTER},\s+(?P<body>.+)$", re.IGNORECASE | re.DOTALL,
)


def for_as_long_as_counter_specs(body: str, *, reading: ClauseReading = STANDALONE, ) -> Optional[list[EffectSpec]]:
    m = _FOR_AS_LONG_AS_TRAILING_RE.match(body) or _FOR_AS_LONG_AS_LEADING_RE.match(body)
    if m is None or not reading.previous_subject:
        return None  # the pronoun needs a pick an earlier clause made
    inner = parse_effect_body(m.group("body").strip(), reading=ClauseReading(previous_subject=True))
    if not inner or any(spec.type != "grant_until" for spec in inner):
        return None  # only a duration effect can be re-timed; anything else fails closed
    condition = {"kind": "source_counters", "counter": m.group("kind").strip().lower(), "min": 1, "of": "affected"}
    return [
        EffectSpec(spec.type, {**spec.params, "duration": "for_as_long_as", "condition": dict(condition)},
                   condition=spec.condition)
        for spec in inner
    ]


def puts_counter_on_source(spec: EffectSpec) -> bool:
    """A plain ``add_counters`` naming no target, recipient or group — the counter went on ``~``."""
    return spec.type == "add_counters" and not any(
        key in spec.params for key in ("target_kind", "group", "selector", "choose_one", "recipient")
    )


def animates_source(spec: EffectSpec) -> bool:
    """PAR-287: "~ becomes a 5/5 ... creature until end of turn" (Gideon, Ally of Zendikar) -- a source-only type change, so the
    next sentence's "it" ("prevent all damage that would be dealt to it this turn") is still the source."""
    static = spec.params.get("static") or {}
    return (
        spec.type == "grant_until" and spec.params.get("self_subject") is True and not spec.params.get("target_kind")
        and static.get("type") == "type_change" and (static.get("params") or {}).get("affects") == "self"
    )


#: MEC-28: the structured creature groups a ``grant_until`` ("untap all attacking creatures. They gain ...", Karlach,
#: Fury of Avernus) may name and a following "they" still read back (`effects.GameContext.previous_selector`): the
#: attacking creatures, and the creatures your opponents control. ENG-61: the named strings (``attacking_creatures``,
#: ``creatures_opponents_control``, the ``each_*`` counter/damage names) are retired, so only the structured spelling
#: is recognised; a tap/pump/counter/damage group is replayable whenever it is a structured battlefield group.
_GROUP_SELECTOR_STRUCTURED_FILTERS: tuple[dict, ...] = (
    {"zone": "battlefield", "of": "any", "filter": {"attacking": True, "card_type": "creature"}},
    {"zone": "battlefield", "of": "opponents", "filter": {"card_type": "creature"}},
)
#: The params a tap / pump / counter spec may carry and still be replayable by its group alone (anything else narrows
#: the group past what `GameContext.previous_selector` records).
_BARE_COUNTER_GROUP_PARAMS: frozenset[str] = frozenset({"kind", "group", "count", "group_other"})


#: "each creature" / "each other creature": the filters that name a group by type and self-exclusion alone.
_BARE_CREATURE_GROUP_FILTERS = ({"card_type": "creature"}, {"card_type": "creature", "not_reference": True})


def _is_creature_only_group(group: object) -> bool:
    """A structured battlefield group whose members are all creatures."""
    return (
        isinstance(group, dict) and group.get("zone", "battlefield") == "battlefield"
        and isinstance(group.get("filter"), dict) and group["filter"].get("card_type") == "creature"
    )


def _is_bare_creature_group(group: object) -> bool:
    """An unnarrowed creature group: replaying it later names the same objects (no counter/state filter)."""
    return _is_creature_only_group(group) and group["filter"] in _BARE_CREATURE_GROUP_FILTERS
_BARE_TAP_PARAMS: frozenset[str] = frozenset({"selector", "untap", "selector_player"})
#: ``group_player`` (PAR-287, Great Oak Guardian): "creatures target player controls get +2/+2. Untap them." -- the group is
#: scoped to the chosen player, which `PumpEffect` itself records as the scoped `previous_selector`.
_BARE_PUMP_PARAMS: frozenset[str] = frozenset({"selector", "power", "toughness", "keywords", "group_player"})


def _is_group_selector_value(value: object) -> bool:
    return isinstance(value, dict) and value in _GROUP_SELECTOR_STRUCTURED_FILTERS


#: Effects that leave what they made in `GameContext.created_objects` for the next clause.
_CREATING_TYPES: frozenset[str] = frozenset({"create_token"})
# (``copy_permanent`` is not listed: `CopyPermanentEffect.created_objects_are_referent` already hands its copies on
# as the next clause's `previous_targets`, so "Create a token that's a copy of that card. It gains haste." is right.)


#: The effects that leave exactly one library card for the next sentence's "it" / "that card" (RULE 701.20): the
#: reveal stashes `GameContext.revealed_card`; the single-card exile leaves it on `GameContext.created_objects`.
_REVEALED_CARD_TYPES: frozenset[str] = frozenset({"reveal_top", "put_revealed_card", "reveal_random_hand_card"})


def _revealed_card_referent(specs: list[EffectSpec]) -> tuple[Referent, ...]:
    """The library card the clause just parsed revealed or exiled, as the referent a later "its mana value" names."""
    if not specs:
        return ()
    last = specs[-1]
    if last.type in _REVEALED_CARD_TYPES:
        return (REVEALED_REFERENT,)
    params = last.params
    if (last.type == "inspect_cards" and params.get("zone") == "library" and params.get("count") == 1
            and params.get("reveal") and params.get("scope") == "you" and not params.get("steps")):
        # `InspectCardsEffect` stashes a lone revealed library card as `GameContext.revealed_card` (RULE 701.20).
        return (REVEALED_REFERENT,)
    if last.type == "exile_top_of_library" and last.params.get("count", 1) == 1:
        return (EXILED_REFERENT,)
    if last.type == "exile_hand_card" and last.params.get("count", 1) == 1:
        # ENG-58, RULE 608.2c / 400.7: "Target player exiles a card from their graveyard. If it's a creature card, ..."
        # -- "it" is the card the pick left in exile; the engine hands a finished pick to the rest of the
        # resolution as `GameContext.created_objects`, the same slot the single-card library exile fills.
        return (EXILED_REFERENT,)
    return ()


def produces(specs: list[EffectSpec]) -> tuple[Referent, ...]:
    """What a just-parsed clause leaves for the next one to name (the referent environment's one producer): the
    object it chose (``it`` / ``that creature``) and/or the group it acted on (``they`` / ``those creatures``)."""
    out: list[Referent] = []
    if specs and specs[-1].params.get("target_kind") in ("player", "opponent"):
        out.append(Referent(PLAYER, noun="player"))
    if (specs and specs[-1].type == "choose_targets" and specs[-1].params.get("kinds") in (["player"], ["opponent"])):
        # PAR-284 milestone 23 / RULE 601.2c: a bare "Choose target opponent." names the player(s) the next sentence's
        # "that player" / "those opponents" read back (`where_x._relative_player_amount`).
        out.append(Referent(PLAYER, noun=CHOSEN_PLAYER_NOUN, group=specs[-1].params.get("count", 1) > 1))
    if specs and specs[-1].type == "seq":
        children = specs[-1].params.get("effects", [])
        if children and children[0].get("type") == "choose_targets":
            params = children[0]["params"]
            out.append(Referent(TARGET, group=params.get("count", 1) > 1))
            if children[-1].get("type") == "for_each":
                body = children[-1].get("params", {}).get("effects", [])
                if body and body[-1].get("type") == "copy_permanent":
                    plural = params.get("count", 1) > 1 or body[-1].get("params", {}).get("count", 1) != 1
                    out.append(CREATED_GROUP_REFERENT if plural else CREATED_REFERENT)
    if specs and specs[-1].type == "for_each" and specs[-1].params.get("over", {}).get("remember"):
        out.append(Referent(TARGET, group=True))
    if announces_creature_target(specs):
        out.append(Referent(TARGET, group=has_plural_targets(specs[-1])))
    if _announces_group_selector(specs):
        out.append(SELECTOR_REFERENT)
    if specs and specs[-1].type == "counter" and not specs[-1].params.get("destination"):
        out.append(COUNTERED_REFERENT)
    exile_cores = list(specs)
    while exile_cores and exile_cores[-1].type in {'gain_life', 'lose_life', 'add_mana'}:
        exile_cores.pop()
    if exile_cores and exile_cores[-1].type in {'exile', 'exile_top_of_library'} and not exile_cores[-1].params.get('face_down'):
        last = exile_cores[-1]
        group = (last.params.get('count', 1) != 1 or bool(last.params.get('selector'))
                 or last.params.get('any_number', False)
                 or last.params.get('player_selector') in ('each_player', 'each_opponent'))
        out.append(Referent(EXILE_POOL, group=group))
    out.extend(_revealed_card_referent(specs))
    if specs and specs[-1].type == "mill" and specs[-1].params.get("count") == 1:
        out.append(MILLED_REFERENT)  # RULE 701.17: "the milled card" of a one-card mill
    if specs and specs[-1].type == "reveal_until" and specs[-1].params.get("hit_destination") == "battlefield":
        criteria = specs[-1].params.get("criteria") or {}
        noun = criteria.get("type") if isinstance(criteria, dict) else criteria
        out.append(Referent(CREATED, group=True, noun=noun or "permanent"))
    # The creation may be followed, inside the same clause, by riders that already consumed it ("create a token that's a
    # copy of …, except it has "…"" is a copy plus a grant on the copy): the last spec that is not such a rider decides.
    core = list(specs)
    while len(core) > 1 and core[-1].params.get("previous_subject") and core[-1].params.get("target_kind") is None:
        core.pop()
    if core and core[-1].type in _CREATING_TYPES | {"copy_permanent"}:
        out.append(CREATED_GROUP_REFERENT if core[-1].params.get("count", 1) != 1 else CREATED_REFERENT)
        if not any(r.kind == TARGET for r in out):
            out.append(TARGET_REFERENT)
    return tuple(out)


#: Pronoun consumers whose engine effect reads ``referent="created"`` (PumpEffect, GrantUntilEffect); a delayed
#: trigger's ``capture`` is switched to ``created_objects`` instead.
_CREATED_AWARE_TYPES: frozenset[str] = frozenset({"pump", "grant_until"})


_CREATED_DELAYED_BODIES: frozenset[str] = frozenset({"sacrifice_specific", "exile_specific", "destroy_specific"})


_CREATED_SUBJECT_RE = re.compile(r"^(?:those|the) tokens\b|^that token\b", re.IGNORECASE)
_CREATED_OBJECT_RE = re.compile(
    r"^(?P<verb>sacrifice|exile|destroy|untap|tap|return) (?:those|the) tokens\b|^(?P<verb1>sacrifice|exile|destroy|untap|tap|return) that token\b",
    re.IGNORECASE,
)


def created_noun_to_pronoun(part: str, referents: tuple[Referent, ...]) -> str:
    """"Create two tokens. **Those tokens** gain haste. Sacrifice **those tokens** at the beginning of the next end step."
    -- right after a creating clause the noun names exactly what was made, so it reads as the pronoun the pronoun rows
    already take (they / them / it). Without a CREATED referent the text is left alone (and stays unclaimed)."""
    if not any(r.kind == CREATED for r in referents):
        return part
    created = next(r for r in referents if r.kind == CREATED)
    group = created.group
    if created.noun and created.noun != "token":
        placed = re.match(rf"^(?P<verb>sacrifice|exile|destroy|untap|tap|return) those {re.escape(created.noun)}s\b", part)
        if placed:
            return f"{placed.group('verb')} them" + part[placed.end():]
    obj = _CREATED_OBJECT_RE.match(part)
    if obj is not None:
        verb = obj.group("verb") or obj.group("verb1")
        return f"{verb} {'them' if group or obj.group('verb') else 'it'}" + part[obj.end():]
    if _CREATED_SUBJECT_RE.match(part):
        return ("they" if group else "it") + part[_CREATED_SUBJECT_RE.match(part).end():]
    return part


def fold_counter_destination(sub: list[EffectSpec], collected: list[EffectSpec]) -> Optional[list[EffectSpec]]:
    """"Counter target spell. If that spell is countered this way, exile it instead of putting it into its owner's
    graveyard." -- the consumer row (offered only right after a counter) emits a ``counter_destination`` marker; it
    becomes the ``destination`` of the counter already collected. ``None`` when it has no counter to join."""
    if not any(s.type == "counter_destination" for s in sub):
        return sub
    if len(sub) != 1 or not collected or collected[-1].type != "counter" or collected[-1].params.get("destination"):
        return None
    collected[-1] = replace(collected[-1], params={**collected[-1].params, "destination": sub[0].params["destination"]})
    return []


def stamp_created_pronouns(specs: list[EffectSpec]) -> list[EffectSpec]:
    """"Tap up to 2 target creatures. Create a token. It gains haste." / "Exile target creature card from your
    graveyard. Create a token that's a copy of that card. It gains haste. Exile it at the beginning of the next end
    step." -- ``previous_targets`` still holds what an earlier clause picked, so a pronoun clause that follows a
    *creating* clause says so explicitly (`referent="created"`; a delayed trigger bakes ``capture="created_objects"``)
    when something was picked before the creation. Without an earlier pick the engine's own fallback to
    `created_objects` is already right, and the spec stays as it was. Idempotent."""
    picked = False  # an earlier clause chose something (`previous_targets` is not empty at the creation)
    stale = False  # ... and the most recent creating clause came after it
    out: list[EffectSpec] = []
    for spec in specs:
        if spec.type in _CREATING_TYPES:
            stale = picked
            out.append(spec)
            continue
        if stale and spec.type in _CREATED_AWARE_TYPES and spec.params.get("previous_subject") and "referent" not in spec.params:
            spec = replace(spec, params={**spec.params, "referent": CREATED})
        elif (
            stale and spec.type == "create_delayed_trigger" and spec.params.get("capture") == "previous_or_self"
            # "Sacrifice/exile/destroy it/them" names the creation; "return the exiled cards" (Disorder in the Court)
            # names the earlier pick even when a Clue was made in between.
            and all(e.get("type") in _CREATED_DELAYED_BODIES for e in spec.params.get("effects", []))
        ):
            spec = replace(spec, params={**spec.params, "capture": "created_objects"})
        elif spec.params.get("target_kind") or spec.params.get("selector") or spec.params.get("group"):
            picked, stale = True, False  # a new pick is what the next pronoun names
        out.append(spec)
    return out


def referents_from(
    target: bool, selector: bool, created: tuple[Referent, ...] = (), target_refs: tuple[Referent, ...] = (),
) -> tuple[Referent, ...]:
    """The environment for the next clause, after the sequencing loop has applied its carry-over rules."""
    return ((target_refs or (TARGET_REFERENT,)) if target else ()) + (
        (SELECTOR_REFERENT,) if selector else ()) + created


def sequel_reading(reading: ClauseReading, carry_self: bool, referents: tuple[Referent, ...]) -> ClauseReading:
    """The reading of the next clause of a sequence: the source keeps "it" until a clause chose something else, the
    group-trigger subject carries over, and the environment is what the clauses so far produced."""
    chose = any(r.kind == TARGET for r in referents)
    return ClauseReading(
        self_subject=carry_self and not chose, group_subject=reading.group_subject, referents=referents,
    )


def _announces_group_selector(specs: list[EffectSpec]) -> bool:
    """Whether the last of ``specs`` is an untargeted mass-selector effect
    ("untap all attacking creatures") the next clause's "they" can point at —
    `announces_creature_target`'s sibling for RULE 601.2c selectors rather
    than RULE 115 targets, since a selector clause has no target of its own
    to be caught by that check."""
    if not specs:
        return False
    last = specs[-1]
    if last.type == "for_each" and last.params.get("over", {}).get("remember"):
        return True
    if last.type == "exile" and (last.params.get("group") or last.params.get("selector")):
        # PAR-136: "Exile each creature you control. Return those cards …" (Ghostway) — a mass exile
        # leaves exactly what it exiled in `GameContext.previous_targets` (`ExileEffect`).
        return True
    if last.type == "tap":
        selector = last.params.get("selector")
        if isinstance(selector, dict) and selector.get("zone", "battlefield") == "battlefield":
            # PAR-128: a structured selector states its whole group (filter and
            # controller scope included), so replaying it names the same objects.
            return set(last.params) <= _BARE_TAP_PARAMS
        return False
    if last.type == "add_counters":
        # PAR-128: "put a +1/+1 counter on each creature you control. Untap
        # those creatures." — an unnarrowed creature group, replayable by name.
        return (
            # PAR-169: the structured form (`add_pt_counter_group`) of the same unnarrowed creature group.
            _is_bare_creature_group(last.params.get("group"))
            and set(last.params) <= _BARE_COUNTER_GROUP_PARAMS
        )
    if last.type == "damage":
        # PAR-128: "deals 1 damage to each creature with flying your opponents
        # control. Tap those creatures." — creature-only mass damage; the group
        # is the set the hit landed on (`GameContext.damaged_this_way`).
        return (
            # PAR-169: any creature-only structured group (`damage_group`), since the replayed set is the one
            # the hit landed on, not a re-run of the filter.
            _is_creature_only_group(last.params.get("group"))
            and "group_and_players" not in last.params and "group_player" not in last.params
        )
    if last.type == "pump":
        selector = last.params.get("selector")
        return (
            # PAR-128: "creatures you control get +2/+1 until end of turn.
            # Untap those creatures." (War Flare) — a structured selector
            # (PARSER_VERSION 473) states its whole group, filter included,
            # so replaying it for "those creatures" names the same objects —
            # provided the pump adds no narrowing param of its own.
            isinstance(selector, dict)
            and selector.get("zone", "battlefield") == "battlefield"
            and set(last.params) <= _BARE_PUMP_PARAMS
        )
    if last.type == "grant_until":
        return _is_group_selector_value(
            last.params.get("static", {}).get("params", {}).get("affects")
        )
    return False


#: RULE 702.6: an "Equip …" line that is more than the bare cost — the "Equip abilities you activate" static family, or a sentence
#: after the cost ("Equip {3}. This ability costs {1} less …"). "Equip legendary creature {3}" and "Equip—<cost>" stay bare.
EQUIP_RIDER_RE = re.compile(r"^equip(?:\s+abilities\b|\b[^.]*\.\s*\S)", re.IGNORECASE)
