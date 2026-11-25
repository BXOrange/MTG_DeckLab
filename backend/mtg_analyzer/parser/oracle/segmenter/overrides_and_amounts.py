"""Segmenter: overrides and amounts (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import json
import re

from ....models.cards.creature_types import CREATURE_SUBTYPES
from ..catalogue.clause_reading import CHOSEN_PLAYER_NOUN, ClauseReading, PLAYER, STANDALONE, TARGET
from typing import Any, Optional
from ..catalogue.count_phrase import parse_amount_phrase, parse_count_phrase
from ..catalogue.history_phrase import (
    parse_counters_put_count, parse_damage_taken_count, parse_graveyard_arrival_count, parse_history_count,
)
from ..catalogue.clause_primitives import TARGET_PARAM_KEYS
from ..catalogue.quantifier_scope import quantified_set
from ..catalogue.effect_rows.shared import EVENT_PLAYER_EVENTS_KEY
from ..catalogue.referent_condition import parse_referent_condition
from ..catalogue.static_handlers import static_condition
from ..spec import EffectSpec, ParserProvenance
from .activation_clauses import RESOLUTION_TIME
from .condition_riders import resolution_count_condition
from .conditions import group_pronoun_condition
from .late import parse_effect_body, segment_line

#: PAR-62: "if `<cond>`, `<A>`. otherwise, `<B>`." — the one connective that
#: needs the ``if_else`` node rather than a ``condition=`` gate, because it has
#: a second branch. RULE 701.30d's clash "otherwise" is the motivating shape.
#:
#: ENG-37's node is three-valued on purpose: a condition whose referent does
#: not exist runs **neither** branch. That is why this can emit an else at all
#: — a two-valued gate would make ``else`` the catch-all for every unmodelled
#: condition, which is fail-*open*.
_IF_OTHERWISE_RE = re.compile(
    r"^if (?P<cond>[^,]{2,160}),\s+(?P<then>.+?)[.]\s+otherwise,?\s+(?P<els>.+)$",
    re.IGNORECASE)


#: "put a +1/+1 counter on `<X>` and a +1/+1 counter on `<Y>`" — two placements in one sentence.
DOUBLE_COUNTERS_RE = re.compile(
    r"^put (?P<first>(?:an?|\d+) [+\-]?[a-z0-9/+\-]+ counters? on [^,]+?) "
    r"and (?P<second>(?:an?|\d+) [+\-]?[a-z0-9/+\-]+ counters? on [^,]+)$",
    re.IGNORECASE,
)

#: The suffix spelling of the same branch — "`<A>` if `<cond>`. Otherwise, `<B>`." — with the
#: negated second sentence ("If it doesn't, `<B>`.") read as its "otherwise".
_IF_OTHERWISE_SUFFIX_RE = re.compile(
    r"^(?P<then>[^.]+?),?\s+if (?P<cond>[^,.]{2,80})\.\s+"
    r"(?:otherwise|if (?:it|that creature) (?:doesn'?t|does not)),?\s+(?P<els>.+)$",
    re.IGNORECASE)


def if_else_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """"if `<cond>`, `<A>`. otherwise, `<B>`." → an ``if_else`` node.

    Fails closed unless all three parts resolve: the condition through the
    shared whitelist, and both branches through the ordinary grammar.
    """
    match = _IF_OTHERWISE_RE.match(body) or _IF_OTHERWISE_SUFFIX_RE.match(body)
    if match is None:
        return None
    condition = group_pronoun_condition(
        match.group("cond"), static_condition(match.group("cond")), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
    )
    if condition is None:
        return None
    branches = []
    for group in ("then", "els"):
        parsed = parse_effect_body(
            match.group(group).strip(), reading=reading.unattached(),
        )
        if not parsed:
            return None
        branches.append([spec.to_dict() for spec in parsed])
    return [EffectSpec("if_else", {
        "condition": condition, "then": branches[0], "else": branches[1],
    })]


_INSTEAD_OVERRIDE_RE = re.compile(
    r"^(?P<base>[^.]+)\.\s*if (?P<cond>[^,]{2,120}),\s*"
    r"(?:(?P<replacement>[^.]+?) instead|instead (?P<leading>[^.]+?))\.?$", re.I | re.S,
)
_DESTROY_TARGET_COUNTER_TOKEN_RE = re.compile(
    r"^destroy target creature\.\s*if that creature had a \+1/\+1 counter on it, "
    r"(?P<create>create [^.]+? creature token)\.?$", re.I | re.S,
)
_CREATED_TOKENS_HAVE_CDA_RE = re.compile(
    r'^(?P<create>each player creates a [^.]+ creature token)\.\s*'
    r'those creatures have "(?P<cda>(?:this token|this creature|~)\'s power[^\"]+)"\.?$',
    re.I | re.S,
)


def created_tokens_have_cda_specs(body: str) -> Optional[list[EffectSpec]]:
    """Fuse a distributive create and its quoted token ability (RULE 111.5)."""
    match = _CREATED_TOKENS_HAVE_CDA_RE.fullmatch(body)
    if match is None:
        return None
    # In the created token's *own* ability, "your" means that token's
    # controller. The source spell's controller is irrelevant (RULE 109.4).
    oracle = match.group("cda").replace("its controller's graveyard", "your graveyard")
    created = parse_effect_body(f'{match.group("create")} with "{oracle}"')
    if not created or len(created) != 1 or created[0].type != "create_token":
        return None
    return created


_CREATED_TOKENS_HAVE_ABILITY_RE = re.compile(
    r'^(?P<create>(?:you )?create [^.]+ creature tokens?)\.\s*'
    r'(?:it has|(?:they|those tokens) have) "(?P<ability>[^"]+)"$', re.I | re.S,
)


def created_tokens_have_ability_specs(body: str) -> Optional[list[EffectSpec]]:
    """RULE 111.3: a fully parsed quoted ability belongs to each new token."""
    match = _CREATED_TOKENS_HAVE_ABILITY_RE.fullmatch(body)
    if match is None:
        return None
    # RULE 201.5: a folded name of the creating card cannot become the
    # token's own self-reference (Sound the Call). Retain fail-closed scope.
    if re.search(r"\bnamed ~", match.group("ability"), re.I):
        return None
    created = parse_effect_body(match.group("create"))
    ability = segment_line(match.group("ability"), allow_spell_effect=False, provenance=ParserProvenance())
    if (not created or len(created) != 1 or created[0].type != "create_token"
            or not ability.claimed or (ability.spec is None and not ability.mana_ability)):
        return None
    # Preserve the token's own Oracle text. create_token binds this text on
    # each new object, so self references and controllers belong to the token.
    params = dict(created[0].params)
    params["oracle_text"] = "\n".join(filter(None, (
        params.get("oracle_text"), ability.native_oracle_text,
    )))
    return [EffectSpec("create_token", params)]


def destroy_target_counter_token_specs(body: str) -> Optional[list[EffectSpec]]:
    """Measure the target before destruction, then branch on that snapshot."""
    match = _DESTROY_TARGET_COUNTER_TOKEN_RE.fullmatch(body)
    if match is None:
        return None
    made = parse_effect_body(match.group("create"))
    if not made or len(made) != 1 or made[0].type != "create_token":
        return None
    return [EffectSpec("bind", {
        "name": "n", "amount": {"kind": "counters", "counter": "+1/+1", "of": "target"},
        "effects": [
            EffectSpec("destroy", {"target_kind": "creature"}).to_dict(),
            EffectSpec("if_else", {
                "condition": {"kind": "amount_compare",
                              "left": {"kind": "fixed", "amount": "$n"},
                              "right": {"kind": "fixed", "amount": 0}, "op": "gt"},
                "then": [made[0].to_dict()], "else": [],
            }).to_dict(),
        ],
    })]


_OVERRIDE_NUMBER_RE = re.compile(r"\b\d+\b")
_OVERRIDE_TARGET_RE = re.compile(
    # A graveyard card, with its qualifiers: "target creature card with mana
    # value 3 or less from your graveyard" (Doctor Jane Foster). First, so
    # "target creature" doesn't claim its head.
    r"\btarget (?:[a-z ]*?(?P<card>card)(?: with [^,.]+?)? from your graveyard"
    # PAR-288: a one-word state qualifier ("target attacking creature", Grey Knight Paragon) is part of the announced
    # phrase the replacement's "it" must repeat, and "defending player controls" (Purifying Dragon) is a controller scope.
    r"|(?:(?:attacking|blocking|tapped|untapped) )?"
    r"(?P<noun>creature(?: or planeswalker)?|player(?: or planeswalker)?|opponent|permanent|spell)"
    r"(?P<scope> you control| an opponent controls| you don't control| defending player controls)?\b)"
    r"|\b(?P<any>any target)\b", re.I,
)


#: PAR-288: the object pronoun a replacement ends on -- "put a +1/+1 counter on it" / "exile it" -- with the verb phrase
#: that governs it. Closed on purpose: the same pronoun after any other verb may name something else.
_OVERRIDE_OBJECT_PRONOUN_RE = re.compile(
    r"(?P<verb>\b(?:counters? on |(?:exile|destroy) ))it(?=\.?$)", re.I)


def _resolve_override_referents(base_text: str, replacement_text: str) -> str:
    """Spell the replacement's back-reference as the base's own target phrase.

    RULE 608.2c: "that creature" in "… instead" is the object the base
    targeted, and "she"/"he"/"it" leading the sentence is its subject (~).
    With exactly one target in the base the rewrite is unambiguous; with
    none or several the text is returned unchanged and fails to match.
    """
    rewritten = replacement_text.strip()
    if rewritten.lower().startswith("for each "):
        # RULE 608.2c: a quantified replacement introduces its own object
        # binding; "that creature" belongs to that loop, not the base target.
        return rewritten
    if re.match(r"^(?:she|he|it)\b", rewritten, re.I):
        subject = "~" if re.match(r"~ deals?\b", base_text, re.I) else None
        matches = list(_OVERRIDE_TARGET_RE.finditer(base_text))
        target = matches[0] if len(matches) == 1 else None
        if subject is None and target is not None:
            subject = target.group(0)
        if subject is not None:
            rewritten = re.sub(r"^(?:she|he|it)\b", subject, rewritten, flags=re.I)
    # Inside an optional replacement the pronoun still names that target.
    matches = list(_OVERRIDE_TARGET_RE.finditer(base_text))
    target = matches[0] if len(matches) == 1 else None
    if target is not None and target.group("noun"):
        # PAR-288 (RULE 608.2c): the replacement's object pronoun -- "put 2 +1/+1 counters on it" (Elder Cathar),
        # "exile it" (Grey Knight Paragon) -- is the one object the base targeted, spelled as that target phrase.
        rewritten = _OVERRIDE_OBJECT_PRONOUN_RE.sub(lambda m: f"{m.group('verb')}{target.group(0)}", rewritten, count=1)
    if target is not None:
        rewritten = re.sub(r"^you may put it\b", "you may put " + target.group(0), rewritten, flags=re.I)
    # PAR-139 (madness overrides): "instead create X of those tokens" names the base's own tokens, and
    # "divided … among those permanents and/or players" the base's own "any number of targets".
    base_tokens = re.search(r"\bcreate (?:a|an|\d+) (?P<phrase>.+? tokens?)\b", base_text, flags=re.I)
    if base_tokens is not None:
        rewritten = re.sub(r"\b(?P<n>x|\d+) of those tokens\b",
                           lambda m: f"{m.group('n')} {base_tokens.group('phrase')}", rewritten, flags=re.I)
    if "among any number of targets" in base_text:
        rewritten = rewritten.replace("among those permanents and/or players", "among any number of targets")
    # "~ deals 2 damage to any target. If you're the monarch, it deals 7 damage instead." (Court of
    # Ire): a replacement that names no recipient hits the base's own.
    bare_damage = re.fullmatch(r"~ deals? \d+ damage", rewritten, flags=re.I)
    base_recipient = re.match(r"~ deals? \d+ damage( to .+)$", base_text.strip(), flags=re.I)
    if bare_damage is not None and base_recipient is not None:
        rewritten += base_recipient.group(1)
    targets = list(_OVERRIDE_TARGET_RE.finditer(base_text))
    if len(targets) != 1:
        return rewritten
    noun = (targets[0].group("noun") or targets[0].group("card") or "permanent or player").lower()
    that = ("player" if noun in ("player", "opponent") else "permanent" if " or planeswalker" in noun
            else noun)
    # A replacement's object pronoun names the one already announced
    # recipient; its source pronoun was handled independently above.
    rewritten = re.sub(r"\bto it\b", "to " + targets[0].group(0).lower(), rewritten, flags=re.I)
    # Only the first mention is the announced target; a later "that player"
    # in the same sentence stays a back-reference to it (Devour Intellect).
    return re.sub(rf"\bthat {that}\b", targets[0].group(0).lower(), rewritten,
                  count=1, flags=re.I)


#: Params that narrow *which* objects are legal targets or how many — two
#: branches announcing one requirement must agree on all of them.
_TARGET_SHAPE_KEYS: frozenset[str] = frozenset({
    "count_max", "optional", "any_number", "max_mana_value", "min_mana_value", "mana_value",
    "color", "colors", "spell_filter", "creature_filter", "filter", "target_filter",
    "max_power", "exclude_self", "another",
})
#: Effect types whose ``count`` is a quantity (cards, counters, tokens), never
#: the number of targets — for every other type ``count`` shapes the target.
_COUNT_IS_A_QUANTITY: frozenset[str] = frozenset({
    "discard", "draw", "mill", "add_counters", "create_token", "scry", "surveil",
})


#: PAR-288: ``target_kind`` values that read an object the ability already has instead of announcing a target (RULE 115.1):
#: an Aura's host ("enchanted creature gets +2/+2", Erebos's Emissary) is bound when the ability resolves, so a branch that
#: names it announces nothing and may replace one that names nothing.
_UNANNOUNCED_TARGET_KINDS: frozenset[str] = frozenset({"attached_permanent"})


def _target_signature(specs: list["EffectSpec"]) -> list[tuple[str, Any]]:
    """What a branch announces (RULE 601.2c), or ``[]`` when it targets nothing."""
    signature: list[tuple[str, Any]] = []
    for spec in specs:
        if spec.type == "optional":
            signature.extend(_target_signature([EffectSpec(child["type"], child.get("params", {}), condition=child.get("condition")) for child in spec.params.get("effects", [])]))
            continue
        if not names_a_target(spec) or spec.params.get("target_kind") in _UNANNOUNCED_TARGET_KINDS:
            continue
        keys = set(TARGET_PARAM_KEYS | _TARGET_SHAPE_KEYS)
        if spec.type not in _COUNT_IS_A_QUANTITY:
            keys.add("count")
        signature.extend((key, spec.params.get(key)) for key in sorted(keys)
                         if spec.params.get(key) is not None)
    return signature


_UNPREVENTABLE_OVERRIDE_TAIL_RE = re.compile(r"\s+and the damage can'?t be prevented\s*$", re.I)


def _magnitude_override_specs(
    base_text: str, replacement_text: str, condition: dict[str, Any], *, reading: ClauseReading = STANDALONE,
) -> Optional[list[EffectSpec]]:
    """"~ deals 3 damage to target creature. If `<cond>`, ~ deals 5 damage to
    that creature instead." (Galvanize) — one effect, one target, two sizes.

    The replacement must be the base with only its number changed, so the
    target announced for the base is the one the bigger effect hits (RULE
    115.1). A `bind` measures the size once and keeps the base's target.
    """
    # PAR-216 (RULE 615.6): "... instead it deals 10 damage to that permanent or player and the damage can't be
    # prevented" (Urza's Rage, Lightning Surge) -- the bigger hit is also unpreventable, under the same condition.
    unpreventable_tail = _UNPREVENTABLE_OVERRIDE_TAIL_RE.search(replacement_text)
    if unpreventable_tail is not None:
        replacement_text = replacement_text[: unpreventable_tail.start()]
    base_numbers = _OVERRIDE_NUMBER_RE.findall(base_text)
    new_numbers = _OVERRIDE_NUMBER_RE.findall(replacement_text)
    if len(base_numbers) != 1 or len(new_numbers) != 1:
        return None
    rewritten = _resolve_override_referents(base_text, replacement_text)
    if _OVERRIDE_NUMBER_RE.sub("#", rewritten).lower() != (
            _OVERRIDE_NUMBER_RE.sub("#", base_text.strip()).lower()):
        return None
    base = parse_effect_body(base_text, reading=reading)
    bigger = parse_effect_body(rewritten, reading=reading)
    if not base or not bigger or len(base) != 1 or len(bigger) != 1:
        return None
    [base_spec], [bigger_spec] = base, bigger
    keys = [key for key in _MAGNITUDE_PARAM_KEYS
            if base_spec.params.get(key) == int(base_numbers[0])
            and bigger_spec.params.get(key) == int(new_numbers[0])]
    if (len(keys) != 1 or base_spec.type != bigger_spec.type
            # A targeted ``count`` fixes how many targets are announced, which
            # a resolution-time measurement cannot supply (RULE 601.2c).
            or (keys[0] == "count" and names_a_target(base_spec)
                and base_spec.type not in _COUNT_IS_A_QUANTITY)
            or base_spec.condition is not None
            or {**base_spec.params, keys[0]: None} != {**bigger_spec.params, keys[0]: None}):
        return None
    if unpreventable_tail is not None and base_spec.type != "damage":
        return None
    gated = {"unpreventable_if": condition} if unpreventable_tail is not None else {}
    return [EffectSpec("bind", {
        "name": "n",
        "amount": {"kind": "if", "condition": condition,
                   "then": int(new_numbers[0]), "otherwise": int(base_numbers[0])},
        "effects": [EffectSpec(base_spec.type, {**base_spec.params, keys[0]: "$n", **gated}).to_dict()],
    })]


#: PAR-288: the subject of a target-state gate ("that creature has a +1/+1 counter on it", "that permanent is black",
#: "that creature is attacking") -- only the demonstrative noun; a bare "it" may name the source or the spell.
_TARGET_STATE_SUBJECT_RE = re.compile(r"^that (?:creature|permanent)\b", re.I)


def _target_state_condition(condition_text: str, base_text: str) -> Optional[dict[str, Any]]:
    """RULE 608.2c / 614.6: "If that creature `<state>`, ... instead" is a gate on the one object the base targeted,
    read when the instruction resolves. Read through the shared referent grammar and scoped to the announced target; a
    base that does not announce exactly one target leaves "that creature" without a referent, so it fails closed."""
    if _TARGET_STATE_SUBJECT_RE.match(condition_text) is None:
        return None
    if len(list(_OVERRIDE_TARGET_RE.finditer(base_text))) != 1:
        return None
    referent = parse_referent_condition(condition_text)
    if referent is None or referent.get("kind") not in _TARGET_STATE_KINDS:
        return None
    return {**referent, "of": "target"}


#: PAR-288: the subject-less state kinds a bare "it" gate may be about the announced target ("If it's blocking",
#: Will of the All-Hunter). Flags such as ``kicked`` stay out: there "it" may be the spell itself (RULE 702.33).
_PRONOUN_STATE_KINDS: frozenset[str] = frozenset({
    "source_blocking", "source_attacking", "source_tapped", "source_untapped", "source_counters", "is_color",
    "is_subtype", "is_card_type",
})
_BARE_IT_SUBJECT_RE = re.compile(r"^it(?:'s| is| has)\b", re.I)


def _scope_pronoun_state_to_target(
    condition: dict[str, Any], condition_text: str, base_text: str,
) -> dict[str, Any]:
    """RULE 608.2c: after a sentence that announced one target ("Target creature gets +2/+2 ... If it's blocking,
    instead ..."), a bare "it" gate on a permanent's own state is that target's, not the resolving spell's. The shared
    vocabulary reads such a phrase about the ability source (right for "If ~ is an Aura", Erebos's Emissary, where the
    base names no target), so the scope is added only when the base announces exactly one."""
    if ("of" in condition or condition.get("kind") not in _PRONOUN_STATE_KINDS
            or _BARE_IT_SUBJECT_RE.match(condition_text) is None
            or len(list(_OVERRIDE_TARGET_RE.finditer(base_text))) != 1):
        return condition
    return {**condition, "of": "target"}


#: The referent-grammar kinds `_target_state_condition` scopes to the announced target. Each reads one characteristic or
#: state of the object at resolution; ``has_keyword`` and the stat comparisons are left to their own rows.
_TARGET_STATE_KINDS: frozenset[str] = frozenset({"source_counters", "is_color", "source_attacking", "is_subtype", "is_card_type"})


def instead_override_specs(body: str, *, reading: ClauseReading = STANDALONE) -> Optional[list[EffectSpec]]:
    """Replace an effect under one shared condition (RULE 614.6).

    The base must not resolve first: a second conditional effect after it
    would scry *and* draw for Rumor Gatherer. A targeted replacement is
    claimed only when it targets exactly what the base did, so `if_else`
    announces one requirement for whichever branch runs.
    """
    match = _INSTEAD_OVERRIDE_RE.fullmatch(body)
    suffix = re.fullmatch(r"(?P<base>[^.]+)\.\s*(?P<replacement>[^.]+?) instead if (?P<cond>[^.]+)\.?", body, re.I | re.S)
    if match is None and suffix is not None:
        return instead_override_specs(
            f"{suffix.group('base')}. if {suffix.group('cond')}, {suffix.group('replacement')} instead.",
            reading=reading,
        )
    if match is None:
        return None
    condition_text = match.group("cond")
    if (re.fullmatch(r"it was(?:n'?t)? kicked", condition_text, re.I)
            and not _OVERRIDE_TARGET_RE.search(match.group("base"))):
        # An untargeted ETB instruction's "it" is its source. Bare "it"
        # after a target-spell instruction could instead name that spell.
        condition_text = re.sub(r"^it\b", "this spell", condition_text, flags=re.I)
    ordinal = re.fullmatch(RESOLUTION_TIME, condition_text, re.I)
    condition = (resolution_count_condition(ordinal) if ordinal is not None
                 else static_condition(condition_text))
    if condition is None:
        condition = _target_state_condition(condition_text, match.group("base"))
    else:
        condition = _scope_pronoun_state_to_target(condition, condition_text, match.group("base"))
    if condition is None:
        return None
    # The unreplaced instruction never runs, so its target is this
    # instruction's current target, not a previous completed effect.
    def current_target(value):
        if isinstance(value, dict):
            return {key: ("target" if key == "of" and child == "previous_target" else current_target(child))
                    for key, child in value.items()}
        if isinstance(value, list):
            return [current_target(child) for child in value]
        return value
    condition = current_target(condition)
    base_text = match.group("base")
    replacement_text = match.group("replacement") or match.group("leading")
    # "If a creature died this turn, A. If seven or more died, instead B."
    # (Tallyman of Nurgle): the first gate covers the whole override — with
    # it false there is no A for B to replace (RULE 614.6).
    outer = re.fullmatch(r"if (?P<cond>[^,]{2,120}),\s*(?P<rest>.+)", base_text, re.I | re.S)
    if outer is not None:
        outer_condition = static_condition(outer.group("cond"))
        inner = instead_override_specs(
            f"{outer.group('rest')}. {body[match.end('base') + 1:].strip()}", reading=reading)
        if outer_condition is None or not inner or len(inner) != 1 or inner[0].condition:
            return None
        return [EffectSpec(inner[0].type, inner[0].params, condition=outer_condition)]
    magnitude = _magnitude_override_specs(base_text, replacement_text, condition, reading=reading)
    if magnitude is not None:
        return magnitude
    base = parse_effect_body(base_text, reading=reading)
    replacement = parse_effect_body(
        _resolve_override_referents(base_text, replacement_text), reading=reading)
    if (not base or not replacement
            or any(spec.condition is not None for spec in [*base, *replacement])):
        return None
    # Both branches must announce the same requirement (or none), the only case `if_else`
    # can announce a target (RULE 601.2c) — unless the cast itself already decided which
    # branch runs (a promised gift, RULE 702.174m), when only that branch announces, so the
    # two may differ ("destroy target artifact" / "destroy two target artifacts").
    if not _is_announced_condition(condition) and (
            _target_signature(base) != _target_signature(replacement)
            or (_target_signature(base) and (len(base) != 1 or len(replacement) != 1))):
        return None
    if _is_announced_condition(condition):
        for spec in replacement:
            if spec.type == "damage" and spec.params.get("divided"):
                spec.params["division_required"] = True
    if len(replacement) == 1 and replacement[0].type == "optional":
        # Declining an optional replacement performs the original event.
        replacement[0].params["else_effects"] = [spec.to_dict() for spec in base]
    return [EffectSpec("if_else", {
        "condition": condition,
        "then": [spec.to_dict() for spec in replacement],
        "else": [spec.to_dict() for spec in base],
    })]


#: PAR-261: a gated "… instead" override preceded by one independent sentence (Quest-counter Missions).
_LED_INSTEAD_RE = re.compile(r"^(?P<lead>put (?:a|an|\d+) [a-z+\-/0-9 ]+? counters? on ~)\.\s*(?P<tail>.+)$", re.I | re.S)


def led_instead_override_specs(body: str, *, reading: ClauseReading) -> Optional[list[EffectSpec]]:
    """"Put a quest counter on ~. `<A>`. If ~ has N or more quest counters on it, `<B>` instead."

    RULE 608.2c: the lead sentence runs first, then the override reads its own condition. The tail must itself
    be a complete override (it fails closed otherwise), so the lead can never change what the tail means.
    """
    match = _LED_INSTEAD_RE.fullmatch(body.strip())
    if match is None or "instead" not in match.group("tail").lower():
        return None
    lead = parse_effect_body(match.group("lead") + ".", reading=reading.unattached())
    tail = instead_override_specs(match.group("tail"), reading=reading.unattached())
    if not lead or not tail:
        return None
    return [*lead, *tail]


#: Flags the cast itself decides before targets are chosen — the parser-side mirror of
#: `game/effect_conditions.ANNOUNCED_FLAGS` (this package must not import `game/`).
_ANNOUNCED_FLAGS: frozenset[str] = frozenset({"gift_promised", "madness_cost_paid", "surge_cost_paid", "blitz_cost_paid", "teamwork_paid"})


def _is_announced_condition(condition: Optional[dict[str, Any]]) -> bool:
    """Whether ``condition`` is a (possibly negated) flag the cast already settled (RULE 601.2b)."""
    while condition and condition.get("kind") == "not":
        condition = condition.get("condition")
    if condition and condition.get("kind") == "kicked" and "of" not in condition:
        return True
    return bool(condition and condition.get("kind") == "flag"
                and condition.get("flag") in _ANNOUNCED_FLAGS and "of" not in condition)


def names_a_target(spec: "EffectSpec") -> bool:
    return any(
        key in spec.params and spec.params[key] is not None
        for key in TARGET_PARAM_KEYS
    )


#: The *quantity*-shaped "for each" operands — a number to multiply by, not a
#: group to iterate over. "for each card in your hand" is `effect_amounts`'
#: ``resource`` reading, and belongs on ENG-37's ``bind`` node (measure once,
#: hand the number to the body) rather than on ``for_each``, which would
#: iterate over objects that aren't on the battlefield at all.
#:
#: PAR-120 (PARSER_VERSION 471): "card[s] in your hand"/"card[s] in your
#: graveyard" retired — `count_amount`'s own `parse_count_phrase` fallback
#: below already reaches an unfiltered hand/graveyard zone count (`{"zone":
#: "hand"/"graveyard", "of": "you"}`), proven to count identically to
#: `_resource_of`'s `len(player.hand/graveyard)` (`test_par120_count_
#: phrase.py`). RULE 702.42a Domain stays: a *distinct-land-type* count, not
#: an object/card count, so it was never a `count_phrase` selector shape.
_FOR_EACH_AMOUNTS: dict[str, dict[str, Any]] = {
    # PAR-287 (RULE 608.2c): "you gain 1 life for each of those creatures" (Bounding Felidar) -- the creatures the
    # sentence before put counters on, read from the `mark_event_log` window `effect_body.open_this_way_window` opens.
    "of those creatures": {"kind": "counter_recipients_since_mark"},
    "basic land type among lands you control": {"kind": "domain"},
    "basic land types among lands you control": {"kind": "domain"},
    # MEC-84's turn history (Kutzil's Flanker) — the creatures are gone, so no zone
    # count can see them; `GameState.creatures_left_battlefield_this_turn` can.
    "creature that left the battlefield under your control this turn": {
        "kind": "count_selector", "selector": "creatures_that_left_battlefield_this_turn",
    },
    "creatures that left the battlefield under your control this turn": {
        "kind": "count_selector", "selector": "creatures_that_left_battlefield_this_turn",
    },
    # RULE 702.108a: "where X is the number of colors of mana spent to cast this spell" (Radiant Flames).
    "colors of mana spent to cast this spell": {"kind": "count_selector", "selector": "converge"},
    # PAR-314 / RULE 702.33d + 702.33e: "for each time it was kicked" is the Kicker/Multikicker payment count recorded
    # on the object the ability belongs to (`continuous.count_selector`'s ``source_kicker_count``).
    "time it was kicked": {"kind": "count_selector", "selector": "source_kicker_count"},
    "time ~ was kicked": {"kind": "count_selector", "selector": "source_kicker_count"},
    # RULE 702.82b: the source permanent's own devour record.
    "creature it devoured": {"kind": "count_selector", "selector": "devoured_creatures"},
    "creatures it devoured": {"kind": "count_selector", "selector": "devoured_creatures"},
    "creature ~ devoured": {"kind": "count_selector", "selector": "devoured_creatures"},
    "creatures ~ devoured": {"kind": "count_selector", "selector": "devoured_creatures"},
    # PAR-284 / RULE 102.2: "for each opponent you have" / "the number of opponents you have" -- the living opponents
    # (`effect_amounts` ``player_count``); "players being attacked" is the distinct defenders of this combat (RULE 506.2).
    "opponent you have": {"kind": "player_count", "scope": "each_opponent"},
    "opponents you have": {"kind": "player_count", "scope": "each_opponent"},
    "the number of opponents you have": {"kind": "player_count", "scope": "each_opponent"},
    # RULE 119.3: Rakdos, Lord of Riots / Neheb, the Eternal -- the life the opponents lost, summed over them.
    "1 life your opponents have lost this turn": {"kind": "count_selector", "selector": "opponents_life_lost_this_turn"},
    # RULE 506.2: "for each creature attacking you" -- the attackers whose declared defender is the controller
    # (`continuous.count_selector`'s ``creatures_attacking_you``; planeswalkers they protect do not count).
    "creature attacking you": {"kind": "count_selector", "selector": "creatures_attacking_you"},
    "creatures attacking you": {"kind": "count_selector", "selector": "creatures_attacking_you"},
    "player being attacked": {"kind": "count_selector", "selector": "players_being_attacked"},
    "players being attacked": {"kind": "count_selector", "selector": "players_being_attacked"},
    "the number of players being attacked": {"kind": "count_selector", "selector": "players_being_attacked"},
    # PAR-284 milestone 17 / RULE 506.2, 508.1a: only opponents can be attacked, so "opponents being attacked" is the
    # same distinct-defender count, and "for each opponent you attacked" (Raid's end-of-combat count) is the
    # turn's attacked opponents (`opponents_attacked_this_turn`).
    "opponent being attacked": {"kind": "count_selector", "selector": "players_being_attacked"},
    "opponents being attacked": {"kind": "count_selector", "selector": "players_being_attacked"},
    "the number of opponents being attacked": {"kind": "count_selector", "selector": "players_being_attacked"},
    # PAR-284 / RULE 122.1: "draw a card for each experience counter you have" (Atreus, Katara), "create a token for each
    # poison counter your opponents have" (Phyrexian Swarmlord) -- the named player-counter totals the statics already read.
    "experience counter you have": {"kind": "count_selector", "selector": "experience_counters_you_have"},
    "poison counter your opponents have": {"kind": "count_selector", "selector": "poison_counters_opponents_have"},
    "opponent you attacked": {"kind": "count_selector", "selector": "opponents_attacked_this_turn"},
    "opponents you attacked": {"kind": "count_selector", "selector": "opponents_attacked_this_turn"},
    # PAR-284 / RULE 903.8: the commander tax's own tally (`Player.commander_casts`), summed over the controller's commanders.
    "time you've cast a commander from the command zone this game": {
        "kind": "count_selector", "selector": "commander_casts_this_game",
    },
    "time you've cast your commander from the command zone this game": {
        "kind": "count_selector", "selector": "commander_casts_this_game",
    },
    # RULE 705 (PAR-151): the flips of this resolution's coin-flip instruction, by result.
    "flip you win": {"kind": "coin_flips", "won": True},
    "flip you won": {"kind": "coin_flips", "won": True},
    "flip you lose": {"kind": "coin_flips", "won": False},
    "flip you lost": {"kind": "coin_flips", "won": False},
    # RULE 706 (PAR-147): the dice a roll kept, by what they show — "for each even result, …".
    "even result": {"kind": "die_results", "which": "even"},
    "odd result": {"kind": "die_results", "which": "odd"},
    "different result": {"kind": "die_results", "which": "different"},
}

#: The params an effect states its own magnitude in. A ``bind`` body has to
#: name exactly one of these for the measured number to land somewhere; a body
#: with none (or several) is refused rather than guessed at.
_MAGNITUDE_PARAM_KEYS: tuple[str, ...] = ("amount", "count")


#: "for each creature destroyed this way" / "the number of permanents exiled this way" (Fumigate, Death Begets Life,
#: Sunfall) — `GameContext`'s own per-resolution tallies. They count every object the resolution destroyed or
#: exiled, so only the unqualified nouns are read (a "nontoken creature destroyed this way" is a narrower count).
#: "the number of counters removed this way" / "for each +1/+1 counter removed this way" (Catti-brie, Vish Kal): the
#: optional kind names the counter the cost removes ("elixir", "+1/+1"); without it any kind the cost removes counts.
COUNTERS_REMOVED_THIS_WAY_RE = re.compile(
    r"^(?:(?:the )?(?:number|amount) of )?(?:(?P<kind>[+\-]?\d+/[+\-]?\d+|[a-z]+) )?counters? removed this way$")
_THIS_WAY_TALLY_RE = re.compile(r"^(?:creature|permanent|card)s? (?P<verb>destroyed|exiled) this way$")
_THIS_WAY_TALLY_NAMES = {"destroyed": "permanents_destroyed_this_way", "exiled": "objects_exiled_this_way"}


#: RULE 120.3 / 120.4a: "the damage dealt this way" / "the amount of excess damage dealt to that creature this way" /
#: "that excess damage" -- `GameContext.damage_dealt_this_way` / `excess_damage_this_way`, the damage this resolution
#: actually dealt (after prevention) and the part beyond lethal. A recipient qualifier is the clause's own target, so
#: it is read as the whole tally (the earlier clause dealt damage to exactly that one recipient on every printing).
DAMAGE_THIS_WAY_RE = re.compile(
    r"^(?:the (?:amount of )?(?P<excess>excess )?damage dealt(?: to (?:that (?:creature|permanent|player)|it|them))? this way"
    r"|(?P<excess_ref>that excess damage))$"
)


_THIS_WAY_COUNT_PHRASE_RE = re.compile(
    r"^(?P<non>non)?(?P<color>white|blue|black|red|green)?(?P<type>creature|artifact|land|enchantment|planeswalker|instant|sorcery|permanent)?s? ?"
    r"(?:cards?|creatures?|artifacts?|lands?|enchantments?|permanents?)? ?(?P<verb>destroyed|exiled|milled|revealed|discarded|sacrificed) this way$"
)
#: MEC-173 / RULE 205.3: "for each Spirit sacrificed this way" (Devouring Greed / Rage) -- a creature subtype in place of a
#: card type. Only the sacrifice pool: `gate._respell_cost_sacrificed_pools` measures it off a cost's records, and any
#: other pool (or a sacrifice inside the effect) is left for the window gate to refuse.
_THIS_WAY_SUBTYPE_SACRIFICED_RE = re.compile(r"^(?P<subtype>[a-z-]+?)s? sacrificed this way$")
#: PAR-284: "the total power of creatures sacrificed this way" / "the greatest mana value among cards discarded this
#: way" -- the aggregate over a "this way" pool (`effect_amounts.this_way_sum` / `this_way_max`).
_THIS_WAY_AGGREGATE_RE = re.compile(
    r"^(?:the )?(?P<agg>total|greatest) (?P<what>power|toughness|mana value) (?:among|of) (?P<pool>.+ this way)$"
)
#: MEC-145 / RULE 608.2h: "the mana value of the permanent exiled this way" / "the power of the card you discarded this way" --
#: the single-object sibling of `_THIS_WAY_AGGREGATE_RE`, read through the same pool handle (a one-member pool sums to its
#: member's value). Only the pools whose members the engine records are named: a card returned from a graveyard leaves no
#: `returned` trace (that pool is the battlefield bounce), so "the card returned this way" stays unclaimed.
_THIS_WAY_SINGLE_RE = re.compile(
    r"^the (?P<what>power|toughness|mana value) of the (?:card|creature|permanent|artifact|enchantment|land)(?: you)? "
    r"(?P<verb>exiled|discarded|sacrificed) this way$"
)
#: "the toughness of the card returned this way" (Foul Renewal): a card moved from a graveyard to a hand, its own pool
#: (`returned_card`, `ReturnFromGraveyardEffect`) because the `returned` pool is the battlefield bounce.
_AMASSED_ARMY_RE = re.compile(r"^the amassed army'?s (?P<what>power|toughness)$")
_RETURNED_CARD_SINGLE_RE = re.compile(r"^the (?P<what>power|toughness|mana value) of the card returned this way$")
#: The pools whose instruction can pause for the affected player's answer: their tally is read from the
#: `mark_event_log` window (`effect_amounts.THIS_WAY_EVENTS`), so a body measuring one must open that window
#: (`open_this_way_window`).
WINDOWED_POOLS = frozenset({"discarded", "sacrificed"})


def _this_way_filter(m: "re.Match[str]") -> dict[str, Any]:
    """The ``card_type`` / ``negate`` / ``color`` filter a `_THIS_WAY_TYPES` match names (shared by every "this way" reader)."""
    filt: dict[str, Any] = {}
    if m.group("type"):  # "permanent" stays: RULE 110.4 permanent cards are matched by the engine marker
        filt["card_type"] = m.group("type")
        if m.group("non"):
            filt["negate"] = True
    if m.group("color"):
        filt["color"] = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[m.group("color")]
    return filt


#: "the number of <subtypes/type> that entered the battlefield under your control this turn" (Cloudspire Coordinator).
_ENTERED_THIS_TURN_COUNT_RE = re.compile(
    r"^(?P<what>[a-z/' -]+?) that entered the battlefield under your control this turn$", re.IGNORECASE
)

#: The group-filter keys the ENTERS_BATTLEFIELD trigger predicate and the count-phrase grammar spell identically,
#: so a count phrase's filter can be reused as the event filter without translation. Anything else stays unclaimed.
_ENTERED_THIS_TURN_FILTER_KEYS = frozenset({"subtype", "subtype_any", "card_type"})


def _entered_this_turn_amount(phrase: str) -> "Optional[dict[str, Any]]":
    """RULE 603.4-style turn history: an ``event_count`` over this turn's ENTERS_BATTLEFIELD events, re-measured
    when the ability resolves (RULE 608.2h). Same event predicate as "whenever a <type> enters under your control"."""
    m = _ENTERED_THIS_TURN_COUNT_RE.match(phrase)
    if m is None:
        return None
    selector = parse_count_phrase(m.group("what"))
    filt = selector.get("filter") if isinstance(selector, dict) else None
    if not filt or selector.get("zone") != "battlefield" or selector.get("of") != "any" \
            or not set(filt) <= _ENTERED_THIS_TURN_FILTER_KEYS or set(selector) - {"zone", "of", "filter"}:
        return None
    return {"kind": "event_count", "trigger": {
        "event": "ENTERS_BATTLEFIELD",
        "condition": {"subject": "group", "controller": "you", "other": False, "filter": dict(filt)},
    }}


#: "<kind> counter(s) among <permanents>" as the singular / plural tail of a "for each" or "the number of" phrase.
_COUNTERS_AMONG_RE = re.compile(r"^(?:(?P<kind>\+1/\+1|-1/-1|[a-z]+) )?counters? among (?P<on>.+)$")
_OTHER_THAN_THE_FIRST = " other than the first"
_AMONG_DISTINCT_PHRASE_RE = re.compile(
    r"^(?:card types|permanent types|colors|creature types|different mana values|different powers|different toughnesses"
    r"|different color pairs) among |^abilities from among ")
#: "for each color among permanents you control" names one value per iteration, singular; the count grammar spells the
#: same measure in the plural ("the number of colors among ...").
_AMONG_DISTINCT_SINGULAR_RE = re.compile(r"^(?:(?P<one>color|card type|creature type|different mana value|different power|different toughness)) among ")


#: PAR-284 / RULE 601.2h: what was spent to cast a spell -- "[the amount|number of] mana spent to cast it", "color[s] of
#: mana spent to cast this spell", "mana from a Treasure [that was] spent to cast it", "{S} spent to cast this spell".
_SPENT_TO_CAST_RE = re.compile(
    r"^(?:the (?:amount|number) of )?(?P<what>colors? of mana|mana from (?:an? )?treasures?|mana from an? (?P<land_subtype>cave|desert)|mana|\{s\})"
    r"(?: that (?:was|were))? spent to cast (?P<spell>this spell|it|that spell)$",
)
#: The spent-mana measurement each reading of `_SPENT_TO_CAST_RE` is: a `continuous.count_selector` for the spell
#: that owns the ability (its record survives onto the permanent), or the firing cast event's own payload for "that
#: spell" (`SPELL_CAST` carries ``mana_spent`` and the ``colors_spent`` list, RULE 601.2i).
_SPENT_SELECTORS: dict[str, str] = {
    "mana": "mana_spent_to_cast", "color": "converge", "treasure": "treasure_mana_spent_to_cast",
    "{s}": "snow_mana_spent_to_cast",
    "cave": "mana_spent_to_cast_by_source_subtype:cave",
    "desert": "mana_spent_to_cast_by_source_subtype:desert",
}
#: The selectors above that read the spell's own payment: unknown while its targets are announced (RULE 601.2c comes
#: before the payment of 601.2h), so a target ceiling cannot measure them (`where_x._inline_announce_time_mana_value`).
CAST_PAYMENT_SELECTORS: frozenset[str] = frozenset(_SPENT_SELECTORS.values())
_SPENT_EVENT_FIELDS: dict[str, str] = {"mana": "mana_spent", "color": "colors_spent"}


def spent_to_cast_amount(phrase: str, *, reading: ClauseReading = STANDALONE) -> "Optional[dict[str, Any]]":
    """The `effect_amounts` spec of a "spent to cast" phrase, or ``None`` outside the shapes the engine records.

    "this spell" is the ability's own object; "it" is that object only under a self-subject head (anything else has no
    antecedent); "that spell" is the spell a cast trigger fired for (`gate._spell_mv_antecedent_ok` limits it to one)."""
    m = _SPENT_TO_CAST_RE.match(phrase.strip().lower())
    if m is None:
        return None
    what = m.group("what")
    kind = m.group("land_subtype") or ("color" if what.startswith("color") else "treasure" if "treasure" in what else what)
    if m.group("spell") == "that spell":
        field = _SPENT_EVENT_FIELDS.get(kind)
        return None if field is None else {"kind": "trigger_event", "field": field}
    if m.group("spell") == "it" and not reading.self_subject:
        return None
    return {"kind": "count_selector", "selector": _SPENT_SELECTORS[kind]}


#: PAR-284 / RULE 105.1: how many colors a referent is -- "for each of its colors", "of that spell's colors", "the number
#: of colors that spell is", "the number of colors of that commander". Group "owner" is the referent's own noun.
_COLORS_OF_REFERENT_RE = re.compile(
    r"^(?:the number of )?(?:of (?P<poss>its|that (?:creature|permanent|spell|card)'s) colors"
    r"|colors (?:that (?P<is_spell>spell) is|of (?P<of>that commander|that spell|it)))$",
)
#: `effect_amounts.TRIGGER_SPELL_REFERENT`: the ``of`` of a ``color_count`` over the spell a cast trigger fired for
#: (the parser may not import `game/`).
TRIGGER_SPELL_REFERENT = "trigger_spell"
#: The cast trigger's spell: "that spell" and "that commander" (a commander is cast as the spell the trigger fired for).
_CAST_SPELL_OWNERS = frozenset({"that spell", "that commander", "that spell's"})


def referent_colors_amount(phrase: str, *, reading: ClauseReading = STANDALONE) -> "Optional[dict[str, Any]]":
    """The `effect_amounts` ``color_count`` of a colors-of-a-referent phrase, or ``None`` without a safe referent.

    "that spell" / "that commander" is the spell a cast trigger fired for (`gate._spell_mv_antecedent_ok` limits it to
    one); a pronoun is the host under a self-subject head or an earlier clause's pick (RULE 608.2h). Anywhere else
    nothing says whose colors, so the phrase is refused rather than measured against an empty referent."""
    m = _COLORS_OF_REFERENT_RE.match(phrase.strip().lower())
    if m is None:
        return None
    owner = m.group("poss") or ("that spell" if m.group("is_spell") else m.group("of"))
    if owner in _CAST_SPELL_OWNERS:
        return {"kind": "color_count", "of": TRIGGER_SPELL_REFERENT} if reading.self_subject else None
    if reading.previous_subject:
        return {"kind": "color_count", "of": "previous_target"}
    if reading.self_subject and owner in ("its", "it"):
        return {"kind": "color_count", "of": "source"}
    return None


#: PAR-284 milestone 19 / RULE 120.3, 119.3: an amount that is the firing event's own payload -- "the amount of damage it
#: dealt to that player" (Desmond Miles), "the amount of life you gained" (Hurska Sweet-Tooth), "for each 1 life you
#: lost" (Transcendence): ``amount`` of the `DAMAGE` / `LIFE_GAINED` / `LIFE_LOST` event, read as `trigger_event`. The
#: amount's ``event`` names the event the payload must come from, which `gate._event_amount_antecedent_ok` checks against
#: the ability's own trigger (any other head carries no such payload, so the clause stays unclaimed rather than read 0).
#: The fourth member is the payload key read; every damage / life event keeps its quantity under ``amount``, a scry
#: event under ``count`` (RULE 701.22a: the cards the player looked at, `RulesEngine._look_top`'s ``len(looked)``).
EVENT_PAYLOAD_AMOUNTS: tuple[tuple["re.Pattern[str]", str, bool, str], ...] = (
    (re.compile(r"^(?:the )?amount of damage (?:it|~) dealt to that (?:player|creature)$"), "DAMAGE", True, "amount"),
    (re.compile(r"^(?:the )?amount of life you gained$"), "LIFE_GAINED", False, "amount"),
    (re.compile(r"^(?:1 life you lost|the amount of life you lost)$"), "LIFE_LOST", False, "amount"),
    # "whenever you scry, ~ gets +1/+1 for each card looked at while scrying this way" (Celeborn the Wise, Elrond).
    (re.compile(r"^(?:the number of )?cards? looked at while scrying this way$"), "SCRY", False, "count"),
)
#: "for each 1 life lost this way" / "the amount of life lost this way": `GameContext.life_lost_this_way`.
_LIFE_LOST_THIS_WAY_RE = re.compile(r"^(?:1 life|the (?:amount of )?life) lost this way$")


def event_amount(phrase: str, *, reading: ClauseReading = STANDALONE) -> "Optional[dict[str, Any]]":
    """The amount of a damage / life event phrase (see `EVENT_PAYLOAD_AMOUNTS`, `history_phrase.parse_damage_taken_count`,
    "life lost this way"), or ``None``. "twice ..." doubles it."""
    phrase = phrase.strip().lower()
    twice = phrase.startswith(_TWICE_PREFIX)
    phrase = phrase.removeprefix(_TWICE_PREFIX)
    amount: "Optional[dict[str, Any]]" = None
    if _LIFE_LOST_THIS_WAY_RE.match(phrase):
        amount = {"kind": "this_way", "tally": "life_lost_this_way"}
    for pattern, event, needs_self, field in EVENT_PAYLOAD_AMOUNTS:
        if amount is None and pattern.match(phrase) and (reading.self_subject or not needs_self):
            amount = {"kind": "trigger_event", "field": field, "event": event}
    if amount is None:
        taken = parse_damage_taken_count(phrase, reading=reading)
        if taken is not None:
            amount = {"kind": "event_count", "trigger": taken, "sum_amount": True}
    if amount is not None and twice:
        amount["multiply"] = 2
    return amount


#: PAR-284 / RULE 506.3, 509.1a: combat-relation counts a source reads about itself. "for each other attacking ~" is the
#: other attackers that share the source's name (Aurochs); "for each creature it's blocking" is the attackers the source is
#: blocking; "for each creature blocking it beyond the first" is the blockers it has minus the one every block needs.
_OTHER_ATTACKING_NAMESAKES_RE = re.compile(r"^other attacking ~$")
_BLOCKING_BY_SELF_RE = re.compile(r"^(?P<noun>creatures?) (?:it's|it is) blocking$")
_BEYOND_THE_FIRST_RE = re.compile(r"^(?P<counted>creatures? blocking (?:it|~)) beyond the first$")
#: A block always has the first blocker, so "beyond the first" counts one fewer, never below zero (RULE 107.1b).
_BEYOND_THE_FIRST_MINUS = 1


def _combat_relation_amount(phrase: str, reading: ClauseReading) -> "Optional[dict[str, Any]]":
    """The `count_selector` amount of a combat-relation phrase (see `_OTHER_ATTACKING_NAMESAKES_RE`), or ``None``.
    "it" must be the source (a self-subject trigger body), since the block relation is read from the source's own
    ``blocked_by`` / blocked attackers; any other antecedent stays unclaimed."""
    if _OTHER_ATTACKING_NAMESAKES_RE.match(phrase):
        selector = parse_count_phrase("other attacking creatures named ~")
        return {"kind": "count_selector", "selector": selector} if selector is not None else None
    blocking = _BLOCKING_BY_SELF_RE.match(phrase)
    if blocking is not None and reading.self_subject and not reading.previous_subject:
        selector = parse_count_phrase(f"{blocking.group('noun')} blocked by ~")
        return {"kind": "count_selector", "selector": selector} if selector is not None else None
    beyond = _BEYOND_THE_FIRST_RE.match(phrase)
    if beyond is not None and reading.self_subject and not reading.previous_subject:
        selector = parse_count_phrase(beyond.group("counted"))
        return ({"kind": "count_selector", "selector": selector, "minus": _BEYOND_THE_FIRST_MINUS, "minimum": 0}
                if selector is not None else None)
    return None


def graveyard_arrival_amount(
    phrase: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[tuple[Optional[str], dict[str, Any]]]":
    """PAR-284 milestone 23 / RULE 109.5: the cards put into another player's graveyard this turn as ``(player kind to
    announce or None, event_count amount taken as that player)``. "that player" needs an earlier "Choose target
    player." (the `CHOSEN_PLAYER_NOUN` referent, nothing to announce); "target player's" is announced by the caller."""
    arrival = parse_graveyard_arrival_count(phrase)
    if arrival is None:
        return None
    who, trigger = arrival
    amount = {"kind": "event_count", "trigger": trigger, "of": "target"}
    if who == "that player":
        chosen = any(r.kind == PLAYER and r.noun == CHOSEN_PLAYER_NOUN and not r.group for r in reading.referents)
        return (None, amount) if chosen else None
    return who.split()[-1], amount


def count_amount(
    phrase: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[dict[str, Any]]":
    """The quantity a "for each `<phrase>`" / "the number of `<phrase>`" measures, as an
    `effect_amounts` spec, or ``None`` for a phrase outside every reading."""
    phrase = phrase.strip().lower()
    greatest_revealed = re.fullmatch(r"the greatest (mana value|power|toughness) among cards revealed this way", phrase)
    if greatest_revealed:
        return {"kind": "this_way_max", "pool": "revealed",
                "characteristic": greatest_revealed[1].replace(" ", "_")}
    amount = _FOR_EACH_AMOUNTS.get(phrase)
    if amount is not None:
        return amount
    arrival = graveyard_arrival_amount(phrase, reading=reading)
    if arrival is not None and arrival[0] is None:
        return arrival[1]
    combat_relation = _combat_relation_amount(phrase, reading)
    if combat_relation is not None:
        return combat_relation
    spent = spent_to_cast_amount(phrase, reading=reading)
    if spent is not None:
        return spent
    colors = referent_colors_amount(phrase, reading=reading)
    if colors is not None:
        return colors
    damage_way = DAMAGE_THIS_WAY_RE.match(phrase)
    if damage_way is not None:
        excess = damage_way.group("excess") or damage_way.group("excess_ref")
        return {"kind": "this_way", "tally": "excess_damage_this_way" if excess else "damage_dealt_this_way"}
    removed = COUNTERS_REMOVED_THIS_WAY_RE.match(phrase)
    if removed is not None:
        # RULE 602.2b / 118.12: the counters an activation's own "remove all <kind> counters from ~" cost took off
        # (`activation_mixin` stamps the total on the source). `gate._counters_removed_amounts_ok` accepts the amount only
        # in an activated ability whose cost text removes counters, so a resolving "remove ... this way" stays unclaimed.
        amount = {"kind": "counters_removed_as_cost", "of": "source"}
        if removed.group("kind"):
            amount["counter"] = removed.group("kind")
        return amount
    this_way = _THIS_WAY_TALLY_RE.match(phrase)
    if this_way is not None:
        return {"kind": "this_way", "tally": _THIS_WAY_TALLY_NAMES[this_way.group("verb")]}
    typed = _THIS_WAY_COUNT_PHRASE_RE.match(phrase)
    if typed is not None:
        # PAR-175 M4b: "the number of creature cards exiled this way" -- the typed handle (`effect_amounts.this_way_count`).
        filt = _this_way_filter(typed)
        if typed.group("verb") in ("milled", "revealed") or typed.group("verb") in WINDOWED_POOLS or filt:
            return {"kind": "this_way_count", "pool": typed.group("verb"), **filt}
    subtype_way = _THIS_WAY_SUBTYPE_SACRIFICED_RE.match(phrase)
    if subtype_way is not None and subtype_way.group("subtype") in CREATURE_SUBTYPES:
        return {"kind": "this_way_count", "pool": "sacrificed", "subtype": subtype_way.group("subtype")}
    army = _AMASSED_ARMY_RE.match(phrase)
    if army is not None:  # RULE 701.47a: refused at the gate unless an `amass` of the same ability precedes it
        return {"kind": "characteristic", "characteristic": army.group("what"), "of": "amassed_army"}
    returned = _RETURNED_CARD_SINGLE_RE.match(phrase)
    if returned is not None:
        return {"kind": "this_way_sum", "pool": "returned_card", "characteristic": returned.group("what").replace(" ", "_")}
    single = _THIS_WAY_SINGLE_RE.match(phrase)
    if single is not None:
        return {"kind": "this_way_sum", "pool": single.group("verb"), "characteristic": single.group("what").replace(" ", "_")}
    aggregate = _THIS_WAY_AGGREGATE_RE.match(phrase)
    if aggregate is not None:
        # RULE 608.2h: the characteristic the pooled objects had where they were (`this_way_sum` reads the events).
        pooled = _THIS_WAY_COUNT_PHRASE_RE.match(aggregate.group("pool"))
        if pooled is not None:
            return {
                "kind": "this_way_sum" if aggregate.group("agg") == "total" else "this_way_max",
                "pool": pooled.group("verb"), "characteristic": aggregate.group("what").replace(" ", "_"),
                **_this_way_filter(pooled),
            }
    cm = _FOR_EACH_COUNTER_RE.match(phrase)
    if cm is not None:
        who = cm.group("who").lower()
        # "~"/"this <type>" name the source; a bare "it" is the source under a
        # self-subject trigger ("when ~ dies, draw a card for each +1/+1 counter on
        # it") and an earlier clause's target only when one was announced — with
        # neither, nothing says which permanent it is, so the phrase is refused
        # rather than measured against an empty referent (which reads 0).
        if who == "~" or who.startswith("this ") or (who == "it" and reading.self_subject):
            of = "source"
        elif reading.previous_subject:
            # PAR-284: "that creature" (Parting Thoughts) is the earlier clause's pick like a bare "it".
            of = "previous_target"
        elif reading.group_subject and who in _GROUP_SUBJECT_COUNTER_HOLDERS:
            # PAR-284 / RULE 603.10a: under a group trigger ("whenever a creature with a fungus counter on it dies, ... for each
            # fungus counter on that creature") the holder is the firing object, counted as it last was (the event's snapshot);
            # `gate._trigger_subject_counters_ok` keeps it to the object events that carry that referent.
            of = "trigger_subject"
        else:
            return None
        return {"kind": "counters", "counter": (cm.group("counter") or ANY_COUNTER_KIND).lower(), "of": of}
    entered = _entered_this_turn_amount(phrase)
    if entered is not None:
        return entered
    # PAR-284: "for each creature that died this turn" / "card you've discarded this turn" -- the same turn-log
    # predicate the history conditions read, tallied.
    # A phrase the object-count grammar already reads ("nontoken permanents you control that entered this turn" counts
    # the permanents still there) keeps that reading; the log tally is for the departed ("creature that died").
    # RULE 601.2i: "for each spell you've cast this turn **other than the first**" (Outlaw Stitcher) is the cast tally less
    # the first spell, never below zero (`effect_amounts` ``exclude_first``, applied before any "N ... for each" multiplier).
    after_the_first = phrase.endswith(" this turn" + _OTHER_THAN_THE_FIRST)
    counted = phrase[: -len(_OTHER_THAN_THE_FIRST)] if after_the_first else phrase
    history = parse_history_count(counted) if parse_count_phrase(counted) is None else None
    if history is not None and after_the_first and history.get("event") != "SPELL_CAST":
        return None
    counters_put = parse_counters_put_count(phrase)
    if counters_put is not None:
        return {"kind": "event_count", "trigger": counters_put, "sum_amount": True}
    if history is not None:
        return {"kind": "event_count", "trigger": history, **({"exclude_first": True} if after_the_first else {})}
    event = event_amount(phrase, reading=reading)
    if event is not None:
        return event
    # PAR-284: "the number of cards in all graveyards with the same name as that spell" (the Shrines) -- the name
    # comparison is against the spell the cast trigger fired for, read as `named ~` (`named_as_reference`) measured against the
    # `trigger_subject` (`gate._spell_name_antecedent_ok` limits it to a cast trigger).
    spell_name = SAME_NAME_AS_SPELL_RE.search(phrase)
    if spell_name is not None:
        counted = phrase[:spell_name.start()]
        twice = counted.startswith(_TWICE_PREFIX)
        selector = parse_count_phrase(counted.removeprefix(_TWICE_PREFIX).removeprefix("the number of ")
                                      + " named ~")
        if selector is None:
            return None
        return {"kind": "count_selector", "selector": selector, "reference": "trigger_subject",
                **({"multiply": 2} if twice else {})}
    # PAR-120: any other count phrase — a structured selector over the shared
    # noun-phrase grammar, not a table row.
    selector = parse_count_phrase(phrase)
    singular = _AMONG_DISTINCT_SINGULAR_RE.match(phrase) if selector is None else None
    if singular is not None:
        phrase = f"{singular.group('one')}s{phrase[singular.end('one'):]}"
    if selector is None:
        # MEC-143: "the number of creature types among non-Borg creatures you control" -- a *distinct-values*
        # count, which `parse_amount_term` (not the object-count grammar) owns.
        selector = parse_amount_phrase(f"the number of {phrase}") if _AMONG_DISTINCT_PHRASE_RE.match(phrase) else None
    if selector is None and (among_counters := _COUNTERS_AMONG_RE.match(phrase)) is not None:
        # PAR-284 / RULE 122.1: "for each lore counter among Sagas you control" -- the sum of one kind (or every kind) of counter
        # over the permanents the group names (`count_selector` ``aggregate: sum`` of ``counters``), spelled "counters on" by
        # the amount grammar.
        kind = f"{among_counters.group('kind')} " if among_counters.group("kind") else ""
        summed = parse_amount_phrase(f"the number of {kind}counters among {among_counters.group('on')}")
        selector = summed if isinstance(summed, dict) else None
    if selector is None:
        # A history count with no noun phrase ("the number of opponents you attacked this turn", Battlefront): the
        # named selector the amount grammar already owns, reached here when the phrase arrives without its "the number of".
        named = parse_amount_phrase(f"the number of {phrase}")
        selector = named if isinstance(named, str) else None
    if selector is None:
        return None
    amount = {"kind": "count_selector", "selector": selector}
    filt = selector.get("filter") if isinstance(selector, dict) else None
    if isinstance(filt, dict) and filt.get("attached_to_reference") and phrase.endswith(" it"):
        # "for each Equipment attached to **it**": the pronoun names the firing object under a group trigger, an earlier
        # clause's pick, or the source under a self-subject trigger; with no antecedent it is refused, not measured as 0.
        if reading.previous_subject:
            amount["reference"] = "previous_target"
        elif reading.group_subject:
            amount["reference"] = "trigger_subject"
        elif not reading.self_subject:
            return None
    if isinstance(filt, dict) and (
        filt.get("blocking_source") or filt.get("shares_creature_type_with_reference")
        or (filt.get("not_reference") and reading.group_subject and not reading.previous_subject)
    ):
        # The counted-against object is the one a pronoun names — "for each creature blocking
        # **it**", "for each **other** creature that shares a creature type with **it**" — which
        # under a group trigger is the firing object, after an earlier clause its pick.
        if reading.group_subject and not reading.previous_subject:
            amount["reference"] = "trigger_subject"
        elif reading.previous_subject:
            amount["reference"] = "previous_target"
    return amount


#: "... with the same name as that spell": the cast trigger's own spell (RULE 201.2).
_TWICE_PREFIX = "twice "
SAME_NAME_AS_SPELL_RE = re.compile(r"\s+with the same name as (?:that|the) spell$")

#: "for each `<objects>` target player controls" / "for each card in target opponent's hand": the count is taken as the
#: player the phrase itself targets (`effect_amounts` ``of: target``).
_TARGET_PLAYER_COUNT_RE = re.compile(
    r"^(?:(?P<noun>.+?) target (?P<who>player|opponent) controls"
    r"|(?P<held>.+?) in target (?P<holder>player|opponent)'s (?P<zone>hand|graveyard))$"
)


def _target_player_count(phrase: str) -> "Optional[tuple[str, dict[str, Any]]]":
    """``(player kind, count amount)`` of a count phrase that names its own target player, or ``None``."""
    m = _TARGET_PLAYER_COUNT_RE.match(phrase)
    if m is None:
        return None
    if m.group("who"):
        who, as_you = m.group("who"), f"{m.group('noun')} you control"
    else:
        who, as_you = m.group("holder"), f"{m.group('held')} in your {m.group('zone')}"
    selector = parse_count_phrase(as_you)
    if not isinstance(selector, dict) or selector.get("of") != "you" or "distinct" in selector:
        return None
    return who, {"kind": "count_selector", "selector": selector, "of": "target"}


#: A pump whose own subject is the one permanent it targets ("target creature gets +2/+2 until end of turn").
_SAME_CLAUSE_PUMP_TARGET_RE = re.compile(r"^(?:another )?target (?:[a-z-]+ )*?creature gets ", re.I)


def for_each_amount_specs(
    match: "re.Match[str]", phrase: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """"<effect> for each `<quantity>`" → a ``bind`` node, or ``None``.

    Fails closed on an unlisted quantity phrase, a body that doesn't parse, a
    body that announces a target, or a body whose magnitude isn't a single
    recognised param — in the last case there is nowhere unambiguous to put
    the measured number, and putting it in the wrong place would scale
    something the card never scaled.
    """
    announced = _target_player_count(phrase)
    if announced is not None:
        # PAR-284 / RULE 115.1: the phrase itself names the player ("for each card in target opponent's hand"), so it
        # is the ability's one target, announced before the body; a body that already names a target stays unclaimed.
        who, amount = announced
        bound = bound_for_each_amount(match, amount, reading=reading.unattached())
        if bound is None or announces_real_target(bound):
            return None
        return [EffectSpec("choose_targets", {"kinds": [who]}), *bound]
    amount = count_amount(
        phrase, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER), group_subject=reading.group_subject),
    )
    if amount is None and _COLORS_OF_REFERENT_RE.match(phrase) and _SAME_CLAUSE_PUMP_TARGET_RE.match(match.group("rest")):
        # RULE 608.2h: "target creature gets +2/+2 until end of turn for each of its colors" -- with no earlier clause,
        # trigger subject or host to name, "its" is the one target this same clause announces.
        amount = {"kind": "color_count", "of": "target"}
    if amount is None:
        return None
    return bound_for_each_amount(
        match, amount, reading=reading.unattached(),
    )


def _scaled_amount(amount: dict[str, Any], factor: int) -> dict[str, Any]:
    """``amount`` times ``factor``. The engine applies ``multiply`` before ``minus`` (`effect_amounts`), so a subtracted
    constant scales with it: "2 for each creature beyond the first" is ``2 * count - 2``, floored at 0 (RULE 107.1b)."""
    if factor == 1:
        return amount
    scaled = {**amount, "multiply": factor}
    if "minus" in scaled:
        scaled["minus"] = scaled["minus"] * factor
    return scaled


def _bound_pump_for_each(spec: EffectSpec, amount: dict[str, Any]) -> "Optional[list[EffectSpec]]":
    """"gets +1/+0 until end of turn for each `<quantity>`" (PAR-123) — a ``pump`` scales
    per counted object, so each nonzero printed half takes the measured number. Two
    different nonzero halves ("+2/+1 for each …") would need a per-half multiplier
    and are refused; so is anything that isn't a plain printed +N/+M."""
    params = dict(spec.params)
    halves = {k: params.get(k) for k in ("power", "toughness")}
    if any(isinstance(v, bool) or not isinstance(v, int) for v in halves.values()):
        return None
    scaled = {k: v for k, v in halves.items() if v}
    if len(set(scaled.values())) > 1 and "minus" in amount and len(scaled) == len(halves):
        # PAR-284: "gets -2/-1 until end of turn for each creature blocking it beyond the first" -- each half scales by its own
        # size, so each is its own bind of the same measurement (a loop over the members, the fallback for the plain count, cannot
        # express "beyond the first"). Both halves resolve in one resolution, so the count cannot change between them.
        return [
            EffectSpec("bind", {
                "name": "n", "amount": _scaled_amount(amount, abs(value)),
                "effects": [{"type": "pump", "params": {**{k: 0 for k in halves}, key: "$n" if value > 0 else "-$n"}}],
            })
            for key, value in scaled.items()
        ]
    # A shrinking pump ("gets -1/-1 until end of turn for each …", PAR-203) scales the same way, through the bind's
    # "-$n" spelling; both nonzero halves must agree in size *and* sign.
    if not scaled or len(set(scaled.values())) != 1:
        return None
    unit = next(iter(scaled.values()))
    amount = _scaled_amount(amount, abs(unit))
    for key in scaled:
        params[key] = "$n" if unit > 0 else "-$n"
    return [EffectSpec("bind", {
        "name": "n", "amount": amount,
        "effects": [{"type": "pump", "params": params}],
    })]


#: PAR-132: "<Tap/Sacrifice/Return/Discard> any number of `<what>`. `<body>` for each `<what>` `<verb>ed` this way."
#: (Harmony of Nature, Minas Tirith Garrison, Charge Across the Araba, Mind Maggots, ...). RULE 608.2c: "this way"
#: names the objects the first instruction actually acted on, so the pick and its payoff are one `choose_objects`
#: whose ``then_that_many`` body is bound to how many were picked (the "x" sentinel, `_substitute_x_specs`) --
#: the body is the ordinary "for each" bind over that count. The pool noun must be the counted noun, so "for each
#: *other* thing" never aliases the pick.
_THIS_WAY_PAST = {"tap": "tapped", "sacrifice": "sacrificed", "return": "returned", "discard": "discarded"}
_THIS_WAY_PICK_ACTION = {"tap": "tap", "sacrifice": "sacrifice", "return": "return_to_hand", "discard": "discard"}
_ANY_NUMBER_LEAD = (
    r"(?:you may )?(?P<verb>tap|sacrifice|return|discard) any number of (?P<what>[a-z ]+?)"
    r"(?: to (?:its owner's|their owner's|their owners') hands?)?"
)
_ANY_NUMBER_THIS_WAY_TRAILING_RE = re.compile(
    rf"^{_ANY_NUMBER_LEAD}\.\s*(?P<rest>[^.]+?),? for each (?P<noun>[a-z ]+?) (?P<past>[a-z]+) this way\.?$"
)
_ANY_NUMBER_THIS_WAY_LEADING_RE = re.compile(
    rf"^{_ANY_NUMBER_LEAD}\.\s*for each (?P<noun>[a-z ]+?) (?P<past>[a-z]+) this way, (?P<rest>[^.]+?)\.?$"
)
#: The pick-pool characteristics a `choose_objects` ``permanent_filter`` can carry for this family.
_THIS_WAY_FILTER_KEYS = frozenset({"card_type", "subtype"})


#: "Discard your hand[, then draw N cards]." (Pyretic Charge, Malfegor): the whole hand is the pick, so it is the
#: any-number pick made mandatory and complete; the redraw runs after the discard and its tally.
_DISCARD_HAND_LEAD_RE = re.compile(
    r"^discard (?:your hand|all the cards in your hand)(?:, then draw (?P<draw>\d+) cards)?\.\s*"
)


def _any_number_pick_pool(verb: str, what: str) -> "Optional[tuple[dict[str, Any], dict[str, Any]]]":
    """The pick pool of "<verb> any number of `what`": ``(parsed count phrase, its filter)`` or ``None``."""
    # The pool is the controller's own permanents ("you control") or, for a discard, their hand ("cards").
    if verb == "discard":
        if not what.endswith(" cards") and what != "cards":
            return None
        pool_phrase = what
    elif what.endswith(" you control"):
        pool_phrase = what[: -len(" you control")]
    elif verb == "sacrifice":
        pool_phrase = what  # "sacrifice any number of creatures": always the controller's own
    else:
        return None
    untapped = pool_phrase.startswith("untapped ")
    if untapped != (verb == "tap"):
        return None
    pool = parse_count_phrase(pool_phrase.removeprefix("untapped "))
    if pool is None:
        return None
    pool_filter = dict(pool.get("filter") or {})
    if set(pool_filter) - _THIS_WAY_FILTER_KEYS:
        return None
    return pool, pool_filter


def _any_number_pick_params(verb: str, pool_filter: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "action": _THIS_WAY_PICK_ACTION[verb], "what": "permanent", "count": "all", "optional": True,
    }
    if pool_filter:
        params["permanent_filter"] = pool_filter
    if verb == "tap":
        params["require_untapped"] = True
    if verb == "discard":
        params["pool_zones"] = ["hand"]
    return params


#: PAR-132: "<Sacrifice/Discard> any number of `<what>`. `<body naming that many/much>`" (Landslide, Last-Ditch Effort,
#: Scapeshift, Rites of Spring, Angelic Aberration, Nantuko Cultivator). RULE 608.2c / 701.21: "that many" is how many
#: the first instruction actually sacrificed / discarded, so the pick (a mandatory-free `choose_objects`) is bracketed by
#: a `mark_event_log` and each body effect's one printed number is bound to the `sacrificed_this_way` /
#: `discarded_this_way` count over that window. Unlike the `then_that_many` form the body stays a top-level effect,
#: so a body target (Landslide's "target player or planeswalker") is announced on cast as usual (RULE 601.2c).
_ANY_NUMBER_THAT_MANY_RE = re.compile(
    rf"^{_ANY_NUMBER_LEAD}\.\s*(?:if you do, )?(?P<rest>[^.]*\bthat (?:many|much)\b[^.]*?)\.?$"
)
_THAT_MANY_TO_ONE_RE = re.compile(r"\bthat (?:many|much)\b")
_THIS_WAY_PICK_VERB_PAST = {"sacrifice": "sacrificed", "discard": "discarded"}


def _any_number_that_many_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    m = _ANY_NUMBER_THAT_MANY_RE.match(body)
    if m is None or m.group("verb") not in _THIS_WAY_PICK_VERB_PAST:
        return None
    verb = m.group("verb")
    pick = _any_number_pick_pool(verb, m.group("what"))
    if pick is None:
        return None
    _, pool_filter = pick
    # The measured number replaces one printed "1": parse the body with the placeholder, then bind it.
    inner = parse_effect_body(
        _THAT_MANY_TO_ONE_RE.sub("1", m.group("rest").strip()), reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject),
    )
    if not inner:
        return None
    amount = {"kind": f"{_THIS_WAY_PICK_VERB_PAST[verb]}_this_way"}
    bound: list[EffectSpec] = []
    for spec in inner:
        one = _bind_magnitude(spec, amount)
        if one is None or '"type": "sacrifice"' in json.dumps(one[0].to_dict(), default=str):
            return None
        bound += one
    return [EffectSpec("mark_event_log", {}), EffectSpec("choose_objects", _any_number_pick_params(verb, pool_filter)), *bound]


def any_number_this_way_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    whole_hand = _DISCARD_HAND_LEAD_RE.match(body)
    if whole_hand is not None:
        specs = any_number_this_way_specs(
            "discard any number of cards. " + body[whole_hand.end():], reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject),
        )
        if specs is None:
            return None
        # The whole hand is the pick, so it is mandatory; the `mark_event_log` bracket of the "that many" form
        # (index 0 there) is left in front of it.
        at = next(i for i, spec in enumerate(specs) if spec.type == "choose_objects")
        specs[at] = EffectSpec("choose_objects", {**specs[at].params, "optional": False})
        draw = whole_hand.group("draw")
        return specs + ([EffectSpec("draw", {"count": int(draw)})] if draw else [])
    m = _ANY_NUMBER_THIS_WAY_TRAILING_RE.match(body) or _ANY_NUMBER_THIS_WAY_LEADING_RE.match(body)
    if m is None:
        return _any_number_that_many_specs(body, reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject), )
    verb = m.group("verb")
    if m.group("past") != _THIS_WAY_PAST[verb]:
        return None
    pick = _any_number_pick_pool(verb, m.group("what"))
    if pick is None:
        return None
    _, pool_filter = pick
    counted = parse_count_phrase(m.group("noun"))
    if counted is None:
        return None
    # Every pick is in the pool, so a counted noun that is the pool's own or broader ("for each card discarded"
    # after "any number of creature cards") counts exactly the picks; a narrower one would not.
    counted_filter = dict(counted.get("filter") or {})
    if counted_filter and counted_filter != pool_filter:
        return None
    bound = bound_for_each_amount(
        re.match(r"(?P<rest>.+)", m.group("rest").strip()), {"kind": "fixed", "amount": "x"},
        reading=ClauseReading(self_subject=reading.self_subject, previous_subject=False, group_subject=reading.group_subject, previous_selector=False),
    )
    if bound is not None and len(bound) == 1 and verb == "return" and '"target_kind"' in json.dumps(
            bound[0].to_dict(), default=str):
        # PAR-225 (Sink into Takenuma, Plow Through Reito): a targeted payoff cannot ride ``then_that_many`` (its
        # effects resolve with no announced target), so it stays a top-level effect (RULE 601.2c announces its target
        # on cast) measuring the "returned this way" window the `mark_event_log` bracket opens.
        measured = bound_for_each_amount(
            re.match(r"(?P<rest>.+)", m.group("rest").strip()), {"kind": "this_way_count", "pool": "returned"},
            reading=ClauseReading(self_subject=reading.self_subject, previous_subject=False, group_subject=reading.group_subject, previous_selector=False),
        )
        if measured is None or len(measured) != 1:
            return None
        return [EffectSpec("mark_event_log", {}), EffectSpec("choose_objects", _any_number_pick_params(verb, pool_filter)), *measured]
    if bound is None or len(bound) != 1 or '"target_kind"' in json.dumps(bound[0].to_dict(), default=str):
        return None
    params = {**_any_number_pick_params(verb, pool_filter), "then_that_many": {"effects": [bound[0].to_dict()]}}
    return [EffectSpec("choose_objects", params)]


#: PAR-132 / PAR-175 M4b: "<instruction>. If a [non]creature card was `<verb>`ed this way, <body>." and "<instruction>.
#: <effect> for each [non]land card `<verb>`ed this way." / "for each … this way, <effect>." (Diregraf Scavenger,
#: Seasoned Pyromancer, Multani's Decree, Tribune of Rot ...). RULE 608.2c: "this way" is exactly what the instruction
#: before it exiled / destroyed / milled / discarded / sacrificed -- one grammar over one typed handle
#: (`effect_amounts.THIS_WAY_POOLS`, the ``this_way_pool`` condition, the ``this_way_count`` amount). A discard or
#: sacrifice can pause for the affected player's answer, so those two read the `mark_event_log` window instead of a
#: per-resolution list; their amounts keep the older ``discarded_this_way`` / ``sacrificed_this_way`` spelling.
_THIS_WAY_TYPES = (
    r"(?P<non>non)?(?P<color>white|blue|black|red|green)?(?P<type>creature|artifact|land|enchantment|planeswalker|instant|sorcery|permanent)?"
)
#: verb -> the effect types that perform it (the first clause must contain one) and whether it needs the event window.
_THIS_WAY_VERBS: dict[str, tuple[frozenset[str], bool]] = {
    "exiled": (frozenset({"exile"}), False),
    "destroyed": (frozenset({"destroy"}), False),
    "milled": (frozenset({"mill"}), False),
    "discarded": (frozenset({"discard"}), True),
    "sacrificed": (frozenset({"sacrifice"}), True),
    # RULE 701.20a: the picks of "reveal any number of <quality> cards in your hand" (the Seer cycle).
    "revealed": (frozenset({"reveal_any_number_hand_cards"}), False),
}
_THIS_WAY_VERB_RE = "|".join(_THIS_WAY_VERBS)
_THIS_WAY_IF_RE = re.compile(
    rf"^if an? {_THIS_WAY_TYPES} ?(?:card )?(?P<aux>was|is) (?P<verb>{_THIS_WAY_VERB_RE}) this way, (?P<then>.+?)\.?$"
)
_THIS_WAY_EACH_RE = re.compile(
    rf"^(?:then )?(?P<rest>.+?) for each {_THIS_WAY_TYPES} ?(?:card )?(?P<verb>{_THIS_WAY_VERB_RE}) this way\.?$"
)
_THIS_WAY_EACH_LEAD_RE = re.compile(
    rf"^for each {_THIS_WAY_TYPES} ?(?:card )?(?P<verb>{_THIS_WAY_VERB_RE}) this way, (?P<rest>.+?)\.?$"
)
#: PAR-207 (RULE 603.12): "**When you discard** a nonland card **this way**, <effect>." -- the reflexive sibling of the
#: "if a nonland card was discarded this way" consumer: a trigger of its own (so its targets are chosen after the
#: discard), which exists only if the pool holds a matching card. Discard is the one verb that prints in this form.
_THIS_WAY_WHEN_RE = re.compile(
    rf"^when you (?P<action>discard) (?:an? |1 or more )?{_THIS_WAY_TYPES} ?cards? this way, (?P<then>.+?)\.?$"
)
#: PAR-284 (RULE 701.17a): a milled card is "put into its owner's graveyard", so "for each creature card put into their
#: graveyard this way" (Coerced Confession, Liliana's Indignation, Patient Rebuilding) names the `milled` pool. Whose
#: graveyard is immaterial to the tally (every card the resolution milled); a non-mill producer ("put that pile into your
#: graveyard") is refused later by the producer check, so only a real `mill` instruction can feed it.
_PUT_INTO_GRAVEYARD_THIS_WAY_RE = re.compile(r"\bput into (?:your|their|its owner's|that player's) graveyards? this way\b")
_THIS_WAY_SPLIT_RE = re.compile(
    rf"(?:\.\s+|,\s+(?=then [^.]+ for each [a-z ]*(?:{_THIS_WAY_VERB_RE}) this way))(?=(?:if an? [a-z]+ (?:card )?(?:was|is) (?:{_THIS_WAY_VERB_RE}) this way, "
    rf"|when you discard (?:an? |1 or more )?[a-z]* ?cards? this way, "
    rf"|for each [a-z ]*(?:{_THIS_WAY_VERB_RE}) this way, "
    rf"|.+ for each [a-z ]*(?:{_THIS_WAY_VERB_RE}) this way))"
)


def announces_real_target(specs: "list[EffectSpec]") -> bool:
    """Whether any (nested) spec names a RULE 115 target; ``target_kind`` null/"source" is the untargeted self form."""
    return re.search(
        r'"target_kind": "(?!source")', json.dumps([spec.to_dict() for spec in specs], default=str),
    ) is not None


def this_way_sequences(
    body: str, *, verbs: frozenset[str], reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """The instruction + its "this way" consumers (see the block comment above), for the pools in ``verbs``."""
    body = _PUT_INTO_GRAVEYARD_THIS_WAY_RE.sub("milled this way", body)
    if " this way" not in body or not (
        any(f" {v} this way" in body for v in verbs)
        or ("discarded" in verbs and _THIS_WAY_WHEN_RE.search(body.split(". ")[-1].strip()))
    ):
        return None
    parts = _THIS_WAY_SPLIT_RE.split(body)
    if len(parts) < 2:
        return None
    before = parse_effect_body(parts[0].strip().rstrip("."), reading=ClauseReading(group_subject=reading.group_subject))
    if not before:
        return None
    before_json = json.dumps([s.to_dict() for s in before], default=str)
    windowed = False
    specs = list(before)
    for sentence in parts[1:]:
        sentence = sentence.strip()
        reflexive = _THIS_WAY_WHEN_RE.match(sentence)
        if reflexive is not None:
            if "discarded" not in verbs or (reflexive.group("non") and not reflexive.group("type")):
                return None
            if '"type": "discard"' not in before_json:
                return None  # the measured verb must be the one the first clause performs
            # The payoff's own pronouns ("that card's mana value", "it") name the pooled card, which no row binds yet.
            if re.search(r"\b(?:it|its|that|those|them|they|their)\b", reflexive.group("then")):
                return None
            payoff = parse_effect_body(
                reflexive.group("then"), reading=ClauseReading(self_subject=reading.self_subject),
            )
            if not payoff or any(spec.condition for spec in payoff):
                return None
            pool: dict[str, Any] = {"kind": "this_way_pool", "pool": "discarded"}
            if reflexive.group("type"):
                pool["card_type"] = reflexive.group("type")
                if reflexive.group("non"):
                    pool["negate"] = True
            if reflexive.group("color"):
                pool["color"] = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[reflexive.group("color")]
            windowed = True
            specs.append(EffectSpec(
                "reflexive_trigger", {"then_trigger": [spec.to_dict() for spec in payoff]}, condition=pool,
            ))
            continue
        m = _THIS_WAY_IF_RE.match(sentence)
        each = None
        if m is None:
            each = m = _THIS_WAY_EACH_RE.match(sentence) or _THIS_WAY_EACH_LEAD_RE.match(sentence)
        if m is None or (m.group("non") and not m.group("type")) or m.group("verb") not in verbs:
            return None
        verb = m.group("verb")
        producers, needs_window = _THIS_WAY_VERBS[verb]
        # The measured verb must be the one the first clause performs ("sacrificed this way" after a discard is not).
        if not any(f'"type": "{effect_type}"' in before_json for effect_type in producers):
            return None
        windowed = windowed or needs_window
        filt: dict[str, Any] = {}
        if m.group("type"):
            filt["card_type"] = m.group("type")
            if m.group("non"):
                filt["negate"] = True
        if m.group("color"):
            filt["color"] = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[m.group("color")]
        if each is None:
            if verb == "destroyed" and m.group("aux") == "is":
                return None  # "if a creature is destroyed this way" is the older condition-peel row's (`static_handlers`)
            if verb in ("destroyed", "milled") and re.search(r"\b(?:it|its|that|those|them|they|their)\b", m.group("then")):
                return None  # a pronoun would name the pooled object, which no row can bind yet: stay unclaimed
            then = parse_effect_body(m.group("then"), reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject), )
            if not then or any(spec.condition for spec in then) or announces_real_target(then):
                return None
            condition: dict[str, Any] = {"kind": "this_way_pool", "pool": verb, **filt}
            specs += [EffectSpec(spec.type, dict(spec.params), condition=condition) for spec in then]
            continue
        if verb in ("destroyed", "exiled") and not filt.get("negate") and not filt.get("color") and filt.get("card_type", "creature") in ("creature", "permanent"):
            return None  # the untyped destroyed/exiled tally (`_THIS_WAY_TALLY_RE`, permanents_destroyed_this_way) already owns this
        amount: dict[str, Any] = (
            {"kind": f"{verb}_this_way", **filt} if needs_window else {"kind": "this_way_count", "pool": verb, **filt}
        )
        bound = bound_for_each_amount(
            m, amount, reading=ClauseReading(self_subject=reading.self_subject, previous_subject=False, group_subject=reading.group_subject, previous_selector=False),
        )
        # A `bind` only scales effects whose factory reads a ``$n`` count (a `sacrifice` count is a plain int).
        if bound is None or (announces_real_target(bound) and verb != "milled") or '"type": "sacrifice"' in json.dumps(
                [s.to_dict() for s in bound], default=str):
            return None
        specs += bound
    return [EffectSpec("mark_event_log", {}), *specs] if windowed else specs


def bound_for_each_amount(
    match: "re.Match[str]", amount: dict[str, Any], *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """The body of "<effect> for each `<quantity>`" bound to a measured ``amount``."""
    inner = parse_effect_body(
        match.group("rest").strip(), reading=reading.unattached(),
    )
    if not inner or len(inner) != 1:
        return None
    # PAR-286 (RULE 608.2c): "<verb>ed this way" names what an EARLIER instruction did. When the scaled effect is itself
    # that pool's producer (a whole "exile X target ... . For each ... exiled this way, <effect>" body read as one
    # "<effect> for each <count>" clause), the bind would measure a pool its own body fills: stay unclaimed.
    pooled = amount.get("pool") if str(amount.get("kind", "")).startswith("this_way_") else None
    if pooled in _THIS_WAY_VERBS and inner[0].type in _THIS_WAY_VERBS[pooled][0]:
        return None
    # RULE 601.2c: unlike `for_each`, a `bind` runs its body exactly once and
    # `BindEffect.target_specs` forwards the body's requirement, so "target
    # opponent loses 1 life for each Vampire you control" keeps its target
    # (PAR-128). The measured amount never reads the target.
    if inner[0].type == "pump":
        # "other" counts against the ability's own source; under a group trigger the
        # counted-against object is the firing creature, which the count can't name yet.
        if reading.group_subject and "'not_reference': True" in repr(amount) and not amount.get("reference"):
            return None
        return _bound_pump_for_each(inner[0], amount)
    wrapper = inner[0].params
    if inner[0].type == "trigger_subject_referent" and not wrapper.get("acting") and len(
            wrapper.get("effects") or []) == 1:
        # "put a +1/+1 counter on that hero for each …": the scaled effect is the wrapper's one
        # body, so the measurement is bound inside it, where the firing object is in scope.
        nested = wrapper["effects"][0]
        bound = _bind_magnitude(EffectSpec(nested["type"], nested.get("params") or {}), amount)
        if bound is None:
            return None
        return [EffectSpec("trigger_subject_referent", {**wrapper, "effects": [bound[0].to_dict()]})]
    return _bind_magnitude(inner[0], amount)


def _bind_magnitude(spec: "EffectSpec", amount: dict[str, Any]) -> "Optional[list[EffectSpec]]":
    """``spec`` with its one printed magnitude replaced by the measured ``amount`` (a ``bind``)."""
    if spec.type == "add_mana":
        return _bind_mana_symbols(spec, amount)
    if spec.type == "counter":
        return _bind_counter_unless_pays(spec, amount)
    keys = [k for k in _MAGNITUDE_PARAM_KEYS if k in spec.params]
    if len(keys) != 1:
        return None
    params = dict(spec.params)
    printed = params[keys[0]]
    if isinstance(printed, bool) or not isinstance(printed, int) or printed < 1:
        return None  # only a printed number can scale the count ("lose 2 life for each …")
    if printed > 1:
        amount = {**amount, "multiply": printed}
    params[keys[0]] = "$n"
    return [EffectSpec("bind", {
        "name": "n",
        "amount": amount,
        "effects": [{"type": spec.type, "params": params}],
    })]


#: The one-generic unit of a "pays {1} for each <count>" tax (RULE 118.12: the unless-cost is one {1} per counted unit).
_UNLESS_PAYS_UNIT = "{1}"


def _bind_counter_unless_pays(spec: "EffectSpec", amount: dict[str, Any]) -> "Optional[list[EffectSpec]]":
    """"counter target spell unless its controller pays {1} for each `<count>`" (PAR-284, RULE 118.12): the measured number
    is the generic amount of the unless-cost. Any other printed cost or an existing tax has no unit to scale."""
    params = dict(spec.params)
    if params.get("unless_pays") != _UNLESS_PAYS_UNIT or "unless_pays_extra_selector" in params:
        return None
    del params["unless_pays"]
    params["unless_pays_generic"] = "$n"
    return [EffectSpec("bind", {"name": "n", "amount": amount, "effects": [{"type": "counter", "params": params}]})]


#: "counter target spell unless its controller pays {2} plus an additional {1} for each <count>" (Spell Stutter, Rune
#: Snag): the printed generic base plus the additional generic per counted unit (RULE 118.12).
_COUNTER_TAX_PLUS_RE = re.compile(
    r"^(?P<head>counter target [a-z ]*?spell unless its controller pays) \{(?P<base>\d+)\} plus an additional \{(?P<unit>\d+)\}$",
    re.IGNORECASE,
)


def _counter_tax_plus_specs(
    tax: "re.Match[str]", phrase: str, reading: ClauseReading,
) -> "Optional[list[EffectSpec]]":
    """The counter row of a "{N} plus an additional {1} for each <count>" tax: a `bind` whose measured count, plus the
    printed base, is the unless-cost's generic amount. A count the amount grammar cannot read stays unclaimed."""
    amount = count_amount(phrase, reading=ClauseReading(self_subject=reading.self_subject))
    if amount is None:
        counted = parse_amount_phrase(f"the number of {phrase}")
        amount = None if counted is None else {"kind": "count_selector", "selector": counted}
    inner = parse_effect_body(f"{tax.group('head')} {_UNLESS_PAYS_UNIT}", reading=reading.unattached())
    if amount is None or not inner or len(inner) != 1 or inner[0].type != "counter":
        return None
    unit = int(tax.group("unit"))
    if unit != 1:
        amount = {**amount, "multiply": unit}
    return _bind_counter_unless_pays(inner[0], {**amount, "plus": int(tax.group("base")) + int(amount.get("plus") or 0)})


def _bind_mana_symbols(spec: "EffectSpec", amount: dict[str, Any]) -> "Optional[list[EffectSpec]]":
    """"add {R} for each `<count>`" (PAR-284, RULE 106.4): the one printed colour repeated per counted unit, so the
    measured number becomes `AddManaEffect`'s variable-count ``amount``; a run of one colour ("add {C}{C} for each")
    scales that count. A mixed or choice-based mana body has no single colour to repeat and stays unclaimed."""
    params = dict(spec.params)
    colors = params.get("colors")
    if set(params) != {"colors"} or not isinstance(colors, list) or len(set(colors)) != 1 or colors[0] == "ANY":
        return None
    if len(colors) > 1:
        amount = {**amount, "multiply": len(colors)}
    return [EffectSpec("bind", {
        "name": "n", "amount": amount,
        "effects": [{"type": "add_mana", "params": {"color": colors[0], "amount": "$n"}}],
    })]


#: PAR-62: "<effect> for each <group>" (`13_` 5.2's 5.9% connective) as an
#: ENG-37 ``for_each`` node over `continuous.group_selector_objects`.
#:
#: Deliberately narrow, for one reason the measurement made concrete: only
#: *object-group* phrases belong on this node. The other frequent "for each"
#: operands are counts, not battlefield groups — "for each card in your
#: hand", "for each +1/+1 counter on it" — and those are an *amount*
#: (`game/effect_amounts.py`), not an iteration; routing them here would
#: iterate over nothing and silently do nothing at all.
#:
#: PAR-120 (PARSER_VERSION 473): the eleven values this table used to
#: hand-maintain are gone — `parse_count_phrase` resolves every one of them
#: to an equivalent *structured* selector instead of a named string (proven
#: equivalent to the `group_selector_objects` string each replaced,
#: `test_par120_count_phrase.py`; `group_selector_objects` itself now
#: accepts the structured form directly — see its own docstring). The
#: *phrase set* stays exactly these eleven, though, not "whatever the shared
#: grammar happens to recognize": the grammar is far more permissive than
#: this table ever was, and `for_each_amount_specs` below already reaches
#: `parse_count_phrase` too, for the *count* reading of a "for each `<X>`"
#: this node's own group/iteration reading isn't right for. Widening the
#: phrase set here would silently steal phrases that must stay on the
#: amount path — a `bind`-scaled single effect, not a `for_each` node
#: repeating the body once per object — which are not always
#: interchangeable even when they add up to the same total (`for_each`
#: hands each object to the body as its own target, `bind` never targets
#: anything the body didn't already announce).
_FOR_EACH_GROUP_PHRASES: frozenset[str] = frozenset({
    "creature you control", "creatures you control",
    "artifact you control", "artifacts you control",
    "land you control", "lands you control",
    "permanent you control", "permanents you control",
    "legendary creature you control",
    "attacking creature", "attacking creatures",
})

_FOR_EACH_SUFFIX_RE = re.compile(
    # MEC-83 widened the group class to admit "+1/+1 counter on it" — digits
    # and `+`/`/` — alongside the plain "creatures you control" phrasings;
    # PAR-120 adds `~` ("for each verse counter on ~", Lost Isle Calling); PAR-284 adds the apostrophe
    # ("for each card you've discarded this turn", "for each card in target opponent's hand"); PAR-284 adds braces
    # ("for each {S} spent to cast this spell", RULE 106.4 / 601.2h); PAR-284 lengthens the phrase to 90 ("for each nontoken
    # creature put into your graveyard from the battlefield this turn" is 72 characters).
    r"^(?P<rest>.+?),?\s+for each (?P<group>[a-z0-9+/ ~'{}-]{3,90})$", re.IGNORECASE)

#: MEC-83: "<effect> for each `<X>` counter on (it|~|this <type>)" — a named
#: counter read (`effect_amounts` ``counters`` kind), the amount sibling of
#: the group phrases in `_FOR_EACH_AMOUNTS`. Built dynamically rather than
#: enumerated: any `<word>` a card prints before "counter" *is* a real
#: counter name (RULE 122.1), and `GameObject.counters.get(name, 0)` is 0 on
#: a permanent that has none — safe either way.
#: `effect_amounts.ANY_COUNTER_KIND`: the ``counter`` of a count over counters of every kind ("for each counter on it").
ANY_COUNTER_KIND = "*"
#: "that creature" / "it" naming the object a group-subject trigger fired for, as the holder of a counters amount.
_GROUP_SUBJECT_COUNTER_HOLDERS = frozenset({"it", "that creature", "that permanent"})
_FOR_EACH_COUNTER_RE = re.compile(
    r"^(?:(?P<counter>[+\-]?\d+/[+\-]?\d+|[a-z][a-z-]*) )?counters? on "
    r"(?P<who>it|~|this [a-z]+|that [a-z]+)$",
    re.IGNORECASE,
)


#: A body whose subject is the one announced player ("target player loses 1 life ...").
_TARGET_PLAYER_SUBJECT_RE = re.compile(r"^target (?:player|opponent) ", re.IGNORECASE)
#: ... or the player the firing event names ("that player loses 1 life ...").
_THAT_PLAYER_SUBJECT_RE = re.compile(r"^that player ", re.IGNORECASE)
#: PAR-284: a count taken as the body's own player -- "for each artifact they control" / "for each creature card in
#: their graveyard". "They / their" can only name that subject (RULE 608.2h), so it is read only beside one.
_RELATIVE_COUNT_RE = re.compile(
    r"^(?:(?P<noun>.+?) they control|(?P<held>.+?) in their (?P<zone>hand|graveyard))$")


#: PAR-284 milestone 23: a body with no word that could name a player, an opponent or a pronoun's antecedent.
_BODY_PLAYER_WORD_RE = re.compile(r"\b(?:players?|opponents?|they|them|their|that|those|its?)\b")
#: `effect_conditions.subject_of`'s referent for the player a damage event hurt ("deals combat damage to a player").
_DAMAGED_PLAYER = "damaged_player"
#: The one event whose recipient that referent reads (`EventType.DAMAGE`: ``target_id`` with ``is_player``).
DAMAGE_EVENT = "DAMAGE"


#: The Domain phrase taken as the target player ("Target player draws a card for each basic land type among lands they control").
_RELATIVE_DOMAIN_PHRASES = frozenset({"basic land type among lands they control", "basic land types among lands they control"})


def _relative_player_count(phrase: str) -> "Optional[dict[str, Any]]":
    """The ``of: target`` count amount of a "they control" / "in their graveyard" phrase, or ``None``."""
    if phrase in _RELATIVE_DOMAIN_PHRASES:  # RULE 702.42a "basic land types among lands they control" (Allied Strategies)
        return {"kind": "count_selector", "selector": "basic_land_types_among_lands_you_control", "of": "target"}
    m = _RELATIVE_COUNT_RE.match(phrase)
    if m is None:
        return None
    as_you = f"{m.group('noun')} you control" if m.group("noun") else f"{m.group('held')} in your {m.group('zone')}"
    selector = parse_count_phrase(as_you)
    if not isinstance(selector, dict) or selector.get("of") != "you" or "distinct" in selector:
        return None
    return {"kind": "count_selector", "selector": selector, "of": "target"}


_LEADING_DURATION_FOR_EACH_RE = re.compile(
    r"^until end of turn, (?P<effect>.+?),? (?P<tail>for each [^,]+)$", re.IGNORECASE)


def _announces_target(body: str, reading: ClauseReading) -> bool:
    """Whether the effect ``body`` parses and announces a target of its own (RULE 115.1)."""
    inner = parse_effect_body(body.strip(), reading=reading.unattached())
    return bool(inner) and any(names_a_target(spec) for spec in inner)


def for_each_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """"<effect> for each <group>" → a ``for_each`` node, or ``None``.

    Fails closed on anything it cannot represent exactly: an unlisted group
    phrase, a body that doesn't parse, or — the subtle one — a body that
    **announces a target**. `ForEachEffect` hands each selected object to the
    body *as its targets*, which is right for "create a token for each …" and
    flatly wrong for "deal 1 damage to target creature for each …", where it
    would override the announced RULE 115 target with the iteration item.
    """
    # PAR-284 / RULE 611.2a: a leading duration ("until end of turn, ~ gets +1/+1 for each ...") reads as the trailing one.
    body = _LEADING_DURATION_FOR_EACH_RE.sub(r"\g<effect> until end of turn \g<tail>", body)
    match = _FOR_EACH_SUFFIX_RE.match(body)
    if match is None:
        return None
    phrase = match.group("group").strip().lower()
    rest = match.group("rest")
    tax = _COUNTER_TAX_PLUS_RE.match(rest)
    if tax is not None:
        return _counter_tax_plus_specs(tax, phrase, reading)
    if _TARGET_PLAYER_SUBJECT_RE.match(rest):
        # RULE 115.1: "target player loses 1 life for each tapped artifact they control" -- counted as that player.
        relative = _relative_player_count(phrase)
        if relative is not None:
            return bound_for_each_amount(match, relative, reading=reading.unattached())
    elif phrase.endswith(" they control") and not _BODY_PLAYER_WORD_RE.search(rest):
        # PAR-284 milestone 23 / RULE 109.5: "create a Treasure token for each artifact they control" (Hoard Hauler) names
        # no player in its body, so "they" is whoever the trigger head names. It is read as the damaged player, and the
        # gate strips the marker only under a damage-to-a-player head (`gate._resolve_event_player_tree`).
        relative = _relative_player_count(phrase)
        bound = None if relative is None else bound_for_each_amount(
            match, {**relative, "of": _DAMAGED_PLAYER}, reading=reading.unattached())
        if (bound is None or len(bound) != 1 or bound[0].type != "bind"
                or any(e["type"] != "create_token" or e["params"].get("creators") for e in bound[0].params["effects"])):
            return None  # only a token maker, whose creator is the ability's controller, may be scaled by the damaged player
        return [EffectSpec("bind", {**bound[0].params, EVENT_PLAYER_EVENTS_KEY: [DAMAGE_EVENT]})]
    elif _THAT_PLAYER_SUBJECT_RE.match(rest) and phrase.endswith(" they control"):
        phrase = phrase.removesuffix(" they control") + " that player controls"  # the event's player (object_set)
    selector = parse_count_phrase(phrase) if phrase in _FOR_EACH_GROUP_PHRASES else None
    if selector is not None and _TARGET_PLAYER_SUBJECT_RE.match(match.group("rest")):
        # RULE 115.1 / 608.2c: "target player loses 1 life for each creature you control" is one effect on the one
        # announced player scaled by the count; a `for_each` node would repeat it per creature with no target bound.
        selector = None
    if selector is not None and _announces_target(match.group("rest"), reading):
        # PAR-284 / RULE 115.1: a body with its own target ("target creature gets +1/+0 until end of turn for each
        # artifact you control") cannot be repeated per counted object (`for_each` hands each object to the body as
        # its target), so the group phrase takes the amount reading -- one effect scaled by the count.
        selector = None
    over = {"selector": selector} if selector is not None else None
    if selector is None:
        amount_specs = for_each_amount_specs(match, phrase, reading=reading.unattached())
        if amount_specs is not None:
            return amount_specs
        # A non-scaling instruction (e.g. proliferate) is repeated, rather than
        # assigned a fabricated magnitude. Counts and aggregates are never sets.
        over = quantified_set("each " + phrase, reading)
        if over is None:
            return None
    inner = parse_effect_body(
        match.group("rest").strip(), reading=reading.unattached(),
    )
    if not inner:
        return None
    if any(names_a_target(spec) for spec in inner):
        return None
    if selector is None and any(spec.type in ("pump", "coin_flip", "roll_die") for spec in inner):
        return None  # magnitude/recorded-result families keep their dedicated composition gates
    return [EffectSpec("for_each", {
        "over": over,
        "effects": [spec.to_dict() for spec in inner],
    })]
