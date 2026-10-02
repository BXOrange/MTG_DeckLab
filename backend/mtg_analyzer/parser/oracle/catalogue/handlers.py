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
import contextvars
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..normalize import SELF
from ..spec import GROUP_SUBJECT_KEY_SENTINEL, EffectSpec, ParserProvenance
from .dig import parse_dig
from .counters import KEYWORD_COUNTER_KINDS, counter_choice_list, parse_counter_choice_items
from .referent_condition import PRONOUN_NOUN_ALT
from .keywords import KEYWORDS, UNGRANTABLE_FLAG_KEYWORDS, KeywordShape, keyword_slug, resolve_keyword
from .subgrammars import (
    THAT_PLAYER_TAIL,
    target_kind_allowed,
    subtype_count_selector,
    CANT_BE_COUNTERED_RE,
    COLOR_LETTERS,
    COLOR_WORD_ALT,
    COUNT,
    COUNT_X,
    DEVOTION,
    IF_COLOR_SUFFIX,
    NUMBER,
    PERMANENT_TYPE_WORDS,
    SELF_SUBJECT_PREFIX,
    SPELL_TARGET,
    TARGET,
    NOT_YOU_TAIL,
    NOT_YOU_TARGET_KINDS,
    OTHER_PREFIX,
    OTHER_TARGET_KINDS,
    SOURCE_EXCLUDED_TARGET_KINDS,
    UP_TO_ONE,
    all_permanent_type_selector,
    count_of,
    count_or_x_of,
    devotion_selector,
    pluralize_permanent_type,
    resolve_color_word,
    resolve_spell_filter,
    resolve_target_creature_state_filter,
    target_quality_filter,
    resolve_target_kind,
    target_is_optional,
    target_macro,
)

#: Colour words → their WUBRG symbol (for a created token's colours).
#: PAR-63: the shared map, not a local copy.
_COLOR_WORDS = COLOR_LETTERS
#: Words in a token's description that are supertypes/joiners, not its subtype.
_TOKEN_NOISE_WORDS: frozenset[str] = frozenset(
    {"artifact", "enchantment", "legendary", "snow", "colorless", "and", "or"}
)


@dataclass(frozen=True)
class EffectHandler:
    """One catalogue row: a full-clause regex + a builder emitting `EffectSpec`s."""

    name: str
    regex: re.Pattern[str]
    build: Callable[[re.Match[str]], Optional[list[EffectSpec]]]
    #: A row whose clause says "**it**" about the ability's own source ("when
    #: ~ enters, it fights …"). English writes that pronoun the same way when
    #: it means something else entirely — a *previously targeted* creature
    #: ("target creature you control gets +1/+2 until end of turn. it fights
    #: target creature you don't control.", Epic Confrontation) — and a clause
    #: alone can't tell the two apart. So such a row is only offered when the
    #: caller states that the implicit subject really is the source
    #: (`match_clause`'s ``self_subject``, set by `segmenter.segment_line` for
    #: an unsplit self-subject trigger body). Claiming it blind would model
    #: Epic Confrontation as "the *sorcery* fights", which resolves to
    #: nothing at all — exactly the half-modeling the coverage gate exists to
    #: prevent.
    self_subject_only: bool = False
    #: The mirror image: a row whose clause says "it"/"that creature" about
    #: the creature an **earlier clause of the same ability** chose ("target
    #: creature you control gets +1/+2 until end of turn. **It** fights target
    #: creature you don't control."). Offered only when `segmenter.
    #: parse_effect_body` has actually parsed such a clause immediately before
    #: this one *and* it announced a creature target, so the referent really
    #: exists at resolution (`GameContext.previous_targets`). Never on at the
    #: same time as ``self_subject_only``: an unsplit trigger body has no
    #: earlier clause to point at, and a later part of a split body has no
    #: guarantee the pronoun still means the source.
    previous_subject_only: bool = False
    #: MEC-28: a row whose clause says "it"/"that creature" about *whichever
    #: object matched* a RULE 603.1 group-subject trigger condition
    #: ("whenever a creature you control attacks alone, … untap **that
    #: creature**.", Finest Hour-shaped) — a third, genuinely different
    #: pronoun referent from both flags above: not the ability's own source
    #: (`self_subject_only`), and not a creature an *earlier clause of this
    #: same body* picked (`previous_subject_only`), but the specific object
    #: that satisfied the trigger, which varies every firing. Offered only
    #: when the caller states the trigger really has a ``{"subject":
    #: "group"}`` condition; `effect_binder._retarget_implicit_subject_
    #: effects` is what turns the resulting ``target_kind: None`` into a
    #: live per-firing read at bind time.
    group_subject_only: bool = False
    #: MEC-28: a row whose clause says "they" about the *group a mass
    #: selector in the immediately preceding clause of this same body just
    #: acted on* ("untap all attacking creatures. **They** gain first
    #: strike until end of turn.", Karlach, Fury of Avernus-shaped) —
    #: distinct from `previous_subject_only`, which reads `GameContext.
    #: previous_targets` (a RULE 115 targeted group); a mass selector
    #: ("all attacking creatures") is untargeted (RULE 601.2c) and never
    #: populates that list. Offered only when the preceding split clause's
    #: own spec actually used a recognised group selector (`segmenter.
    #: _announces_group_selector`).
    previous_selector_only: bool = False
    #: PAR-117 (attached-permanent-controller residue): a row whose clause
    #: says "its controller `<verb>`" about RULE 303.4/301.5's *attached
    #: host* ("whenever enchanted creature attacks or blocks, its controller
    #: loses N life.", Contaminated Bond-shaped) — a fourth, genuinely
    #: different pronoun referent from all three above: not the ability's own
    #: source, not an earlier clause's chosen target, and not a RULE 603.1
    #: group-trigger's firing object, but the permanent this Aura/Equipment
    #: is attached to, a fact about the trigger's own subject the same way
    #: ``group_subject_only`` is. Offered only when the caller states the
    #: trigger really has a ``{"subject": "attached_permanent"}`` condition;
    #: reads through `effect_conditions.subject_of("attached", ...)`, the
    #: `game/effect_operands.py` ``{"of": "attached", "as": "controller"}``
    #: referent.
    attached_subject_only: bool = False

    def match(self, clause: str) -> Optional[list[EffectSpec]]:
        """Effects for ``clause`` if this handler claims it whole, else ``None``.

        A builder may still return ``None`` after a regex match (e.g. an
        unrecognised target phrase) — that also means "not claimed", keeping
        the gate fail-closed.
        """
        m = self.regex.fullmatch(clause.strip())
        if m is None:
            return None
        specs = self.build(m)
        if specs is not None and not _target_qualities_kept(m, specs):
            return None
        return specs


def _carries_filter(node: object, fragment: dict) -> bool:
    """Whether some ``creature_filter`` inside ``node`` (an effect's params, nested) holds ``fragment``."""
    if isinstance(node, dict):
        held = node.get("creature_filter")
        if isinstance(held, dict) and all(held.get(k) == v for k, v in fragment.items()):
            return True
        return any(_carries_filter(v, fragment) for v in node.values())
    if isinstance(node, (list, tuple)):
        return any(_carries_filter(v, fragment) for v in node)
    return False


def _target_qualities_kept(m: re.Match[str], specs: list[EffectSpec]) -> bool:
    """PAR-141: a matched TARGET phrase's negated quality ("without flying") must reach a spec.

    `resolve_target_kind` drops the quality from the kind, so a builder that never merges
    `resolve_target_creature_state_filter` would resolve against *every* creature — the silent
    over-wide claim v409 fixed for the combat-state adjectives. Refusing here keeps the slot
    fail-closed for all ~hundred `{TARGET}` handlers at once instead of trusting each builder.
    """
    for name, text in m.groupdict().items():
        if text and (name == "target" or name.startswith("target_")):
            fragment = target_quality_filter(text)
            if fragment and not any(_carries_filter(spec.params, fragment) for spec in specs):
                return False
    return True


def _c(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# --- Builders ---------------------------------------------------------------
# Each returns the effect list, or None when the clause can't be safely modeled
# (an unknown target phrase → fail-closed, don't guess).


#: RULE 115.1a "up to one" (`subgrammars.target_is_optional`) → the
#: `{"optional": True}` param sliver every `{TARGET}`-based builder below
#: merges in, or ``{}`` for a bare "target X" (still required, unchanged).
def _optional_param(m: re.Match[str]) -> dict:
    return {"optional": True} if target_is_optional(m) else {}


#: RULE 115.1a generalized to N>=2 — "destroy **two** target creatures",
#: "destroy **up to two** target artifacts and/or enchantments", "deals N
#: damage to each of **up to two** target creatures and/or planeswalkers".
#: A deliberately separate, self-contained grammar from the shared `TARGET`
#: macro above (`_TARGET_ROWS` is singular-only and reused by many other
#: handler families — return_to_hand/tap/attach/… — that this feature
#: doesn't touch): a plural noun phrase never collides with `TARGET`'s bare
#: "target X"/"up to one target X" shapes, so there's no dispatch ambiguity
#: registering both. Wired up for `destroy`/`exile`/`damage`/`tap`/
#: `return_to_hand`/`add_counters`/`return_from_graveyard` — every effect
#: class `game/effects/core.py` loops a `count` over. `return_from_graveyard`
#: doesn't reuse this alternation directly (graveyard clauses have their own
#: scope/type-word grammar, `_RETURN_FROM_GRAVEYARD_MULTI_RE`) but shares
#: `_MULTI_TARGET_QUANTIFIER`.
_MULTI_TARGET_ROWS: list[tuple[str, str]] = [
    (r"target creatures and/or planeswalkers", "any"),
    (r"target artifacts and/or enchantments", "artifact_or_enchantment"),
    # "exile X target artifacts and/or creatures" (Hide on the Ceiling) — its own pool, like the row above.
    (r"target artifacts and/or creatures", "artifact_or_creature"),
    (r"target creatures", "creature"),
    # "return 1 or 2 target nonland permanents to their owners' hands"
    # (Wanderwine Farewell) — tried before the bare `target permanents` row
    # below since RAW excludes lands, unlike that row.
    (r"target nonland permanents", "nonland_permanent"),
    (r"target permanents", "permanent"),
    # The single-type pools (`targeting.TARGET_FRAMES`' artifact/enchantment/land): "destroy X
    # target artifacts" must not offer a creature or a land.
    (r"target artifacts", "artifact"),
    (r"target enchantments", "enchantment"),
    (r"target lands", "land"),
    (r"target players", "player"),
]
#: PAR-128: the controller scope on a plural target phrase ("tap up to 2 target
#: creatures your opponents control"). Only the rows whose kind has a scoped
#: pool in `subgrammars.NOT_YOU_TARGET_KINDS` compose it; "target artifacts",
#: "target lands" and the like read as the broad ``permanent`` kind, so scoping
#: them would claim a narrower pool than the engine offers — they stay unclaimed.
_MULTI_TARGET_SCOPE_TAIL = r" (?:your opponents control|an opponent controls|you don'?t control|you control)"
#: "…each of up to 2 target creatures **you control**" — the plural mirror of the singular
#: `<kind>_you_control` pools (`targeting.TARGET_FRAMES`' ``SCOPE_YOU``).
_MULTI_TARGET_YOU_KINDS: dict[str, str] = {
    "creature": "creature_you_control", "permanent": "permanent_you_control",
    "nonland_permanent": "nonland_permanent_you_control",
}
_MULTI_TARGET_SCOPED_KINDS: dict[str, str] = {
    r"target creatures and/or planeswalkers": "creature_or_planeswalker",
    r"target creatures": "creature",
    r"target nonland permanents": "nonland_permanent",
    r"target permanents": "permanent",
    r"target artifacts and/or enchantments": "artifact_or_enchantment",
}
_MULTI_TARGET_ALT = (
    "(?:(?:" + "|".join(f"(?:{frag})" for frag, _ in _MULTI_TARGET_ROWS) + ")"
    f"(?:{_MULTI_TARGET_SCOPE_TAIL})?)"
)
#: "exile any number of target spells." (Mindbreak Trap) — a spell-kind
#: target row, deliberately *not* folded into the shared `_MULTI_TARGET_
#: ROWS`/`_MULTI_TARGET_ALT` every other multi-target family (destroy/
#: damage/tap/return_to_hand/…) also reads: "destroy target spells"/
#: "N damage to target spells" aren't real templates (you counter or exile
#: a spell, never destroy/damage one), so widening the shared alternation
#: would have let `destroy_multi_target` silently claim a nonsense clause
#: too (caught by `tests/test_multi_target.py`'s own unrecognized-phrase
#: regression test). Only `exile`'s own regex opts into this wider
#: alternation. Reuses the same `TargetSpec(kind="spell", …)` `CopyPermanentEffect`'s
#: "copy any number of target instant and/or sorcery spells" (Display of
#: Power) already exercises.
_MULTI_TARGET_ALT_WITH_SPELL = _MULTI_TARGET_ALT + "|(?:target spells)"


def _multi_target_kind_with_spell(phrase: str) -> Optional[str]:
    text = phrase.strip()
    if re.fullmatch(r"target spells", text, re.IGNORECASE):
        return "spell"
    return _multi_target_kind(phrase)


def _multi_target_kind(phrase: str) -> Optional[str]:
    text = phrase.strip()
    scoped = re.fullmatch(rf"(?P<base>.*?)(?P<tail>{_MULTI_TARGET_SCOPE_TAIL})", text, re.IGNORECASE)
    if scoped is not None:
        base = _MULTI_TARGET_SCOPED_KINDS.get(scoped.group("base").lower())
        if base is None:
            return None
        if scoped.group("tail").strip() == "you control":
            return _MULTI_TARGET_YOU_KINDS.get(base)
        return NOT_YOU_TARGET_KINDS.get(base)
    for frag, kind in _MULTI_TARGET_ROWS:
        if re.fullmatch(frag, text, re.IGNORECASE):
            return kind
    return None


#: A numeric quantifier before a plural TARGET phrase: "two "/"three " (a
#: mandatory count — RULE 601.2c needs that many legal targets to even be
#: castable) or "up to two "/"up to three " (optional, 0..N — never locks
#: casting, same as "up to one"). Digits only — `normalize.py` already
#: folds spelled-out numbers up to twelve. PAR-15's "any number of" is a
#: third alternative — RULE 115.1a's genuinely unbounded, freely-chosen
#: count (0..however many are legal), modeled the same way this codebase's
#: one pre-existing hand-authored example already did (`card_registry.
#: _fire_covenant`'s own comment: "a real board never has X-1's worth of
#: relevant creatures beyond that") — a generous fixed cap
#: (`_ANY_NUMBER_TARGET_CAP`) rather than a live `legal_targets` count,
#: since the existing "up to N, offered one at a time, stop early" round-
#: gathering machinery (`RulesEngine._continue_trigger_multi_target`)
#: already handles running out of legal targets *or* the player stopping
#: voluntarily before the cap — the cap only needs to never be the *true*
#: bottleneck.
_ANY_NUMBER_TARGET_CAP = 10
#: ENG-30: RULE 601.2c's third quantifier shape — a genuine mandatory
#: *range* ("one or two target creatures", digits already folded by
#: `normalize.py`) — at least ``range_min``, at most ``range_max``, unlike
#: "up to N" whose floor is always 0. Tried before the plain ``count``
#: alternative below so "1 or 2 " isn't swallowed by a bare `\d+` match on
#: just the "1" (`targeting.TargetSpec.count_max`).
_MULTI_TARGET_QUANTIFIER = (
    r"(?:(?P<any_number>any number of )"
    r"|(?P<range_min>\d+) or (?P<range_max>\d+) "
    r"|(?P<up_to>up to )?(?P<count>\d+) )"
    # PAR-128: "each of up to 2 **other** target creatures" (Felidar Savior) — RULE 109.5, not
    # the ability's own source. `_multi_target_params` reads it (`_OTHER_MULTI_KINDS`).
    r"(?P<other>other )?"
)


#: An optional trailing "controlled by different players/controllers"
#: clause (Run Away Together/Protector of the Wastes-shaped, RULE 115.1a's
#: N>=2 generalized with a cross-target constraint — `targeting.TargetSpec.
#: distinct_controllers`) — appended right after `_MULTI_TARGET_ALT`'s
#: target phrase in whichever multi-target handler regex opts in.
_MULTI_TARGET_DISTINCT_CONTROLLERS = r"(?P<dc> controlled by different (?:players|controllers))?"


#: PAR-128: "destroy **X** target creatures" / "tap **up to X** target creatures" — the target
#: count is the spell's or ability's announced {X} (`TargetSpec.count_selector="source_x_paid"`,
#: read at announce time). Only the handlers whose effect class takes a `count_selector` opt in
#: through this variant; every other handler keeps `_MULTI_TARGET_QUANTIFIER` and so never sees
#: an "x" count.
_MULTI_TARGET_QUANTIFIER_X = rf"(?:(?P<x_count>(?P<x_up_to>up to )?x )|{_MULTI_TARGET_QUANTIFIER})"
_OTHER_MULTI_SIBLINGS: dict[str, str] = dict(OTHER_TARGET_KINDS)


def _multi_target_params(m: re.Match[str], allow_spell: bool = False) -> Optional[dict]:
    """The shared ``{target_kind, count, optional?, distinct_controllers?}``
    params for a `_MULTI_TARGET_QUANTIFIER` + `_MULTI_TARGET_ALT` match, or
    ``None`` if the target phrase isn't recognized or the count is < 2 (the
    N=1 "up to one"/bare-target case is the existing singular handler's
    job, not this one's — a count of exactly 1 here would just be a
    confusing duplicate route to the same effect). PAR-15's "any number of"
    always carries ``optional=True`` (RULE 115.1a — 0 is always a legal
    choice) and a capped ``count`` (`_ANY_NUMBER_TARGET_CAP`). ENG-30's
    "N or M" range sets ``count`` to the RULE 601.2c *minimum* and
    ``count_max`` to the ceiling (`targeting.TargetSpec.count_max`) — never
    ``optional``, since fewer than the minimum isn't a legal choice.

    ``allow_spell=True`` (only `exile_multi_target`) additionally recognizes
    "target spells" — see `_MULTI_TARGET_ALT_WITH_SPELL`'s docstring for why
    this isn't just folded into the shared alternation every caller reads.
    """
    kind = (
        _multi_target_kind_with_spell(m.group("target"))
        if allow_spell else _multi_target_kind(m.group("target"))
    )
    if kind is None:
        return None
    if m.groupdict().get("other"):
        # The pool must already leave the source out, or have an "other" sibling.
        if kind in _OTHER_MULTI_SIBLINGS:
            kind = _OTHER_MULTI_SIBLINGS[kind]
        elif kind not in SOURCE_EXCLUDED_TARGET_KINDS:
            return None
    if m.groupdict().get("x_count"):
        # `count` is the cap `_chosen_targets` slices a resolved pick list to; the announced X
        # (`count_selector`) decides how many picks were offered.
        params: dict = {
            "target_kind": kind, "count": _ANY_NUMBER_TARGET_CAP,
            "count_selector": "source_x_paid", "optional": True,
        }
    elif m.groupdict().get("any_number"):
        params = {"target_kind": kind, "count": _ANY_NUMBER_TARGET_CAP, "optional": True}
    elif m.groupdict().get("range_min") is not None:
        range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
        if range_min < 1 or range_max <= range_min:
            return None  # fail closed on a nonsensical/degenerate range
        params = {"target_kind": kind, "count": range_min, "count_max": range_max}
    else:
        count = int(m.group("count"))
        if count < 2:
            return None
        params = {"target_kind": kind, "count": count}
        if m.groupdict().get("up_to"):
            params["optional"] = True
    if m.groupdict().get("dc"):
        params["distinct_controllers"] = True
    return params


def _targeted_damage(m: re.Match[str], **amount: Any) -> Optional[list[EffectSpec]]:
    """The one `damage` spec every "deals `<amount>` damage to `<target>`" row emits (PAR-121): the amount
    it names, the resolved target kind, "up to one", and the creature qualifier `resolve_target_kind`
    discards ("deals N damage to target **tapped** creature", "…to any target **that isn't a Dinosaur**"),
    merged here once instead of in a copy per amount spelling."""
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    params: dict = {**amount, "target_kind": kind, **_optional_param(m)}
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("damage", params)]


def _damage(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _targeted_damage(m, amount=int(m.group("n")))


def _damage_that_much(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """Damage equal to the amount carried by this ability's antecedent.

    The parser layer cannot assume which trigger/event supplied the value.
    ``gate._that_much_antecedent_ok`` replaces the private sentinel with the
    event's concrete payload field and fail-closes spells/activations or a
    trigger without a numeric antecedent.
    """
    return _targeted_damage(m, amount_from_trigger_event="that_much")


def _damage_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "deals twice X damage" (Purphoros's Intervention) is the ``"twice_x"`` sentinel
    # (`RulesEngine._substitute_x`, 2 × the announced X).
    return _targeted_damage(m, amount="twice_x" if m.groupdict().get("twice") else "x")


_DAMAGE_X_SOURCE_COUNTERS_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? x damage to (?P<target>target attacking or blocking creature), "
    r"where x is the number of (?P<counter>[a-z+-]+) counters on ~"
)


def _damage_x_source_counters(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "target_kind": "attacking_or_blocking_creature",
        "amount_from_count_selector": f"source_{m.group('counter').lower()}_counters",
    })]


#: "Whenever enchanted creature attacks, it deals X damage to defending
#: player, where X is the number of cards in their hand." (Unquenchable
#: Fury) — this has no announced-X value: it reads that combat's defender
#: at resolution, like the existing ``selector=defending_player`` route.
_DAMAGE_X_DEFENDING_PLAYER_HAND_RE = _c(
    r"(?:it|~|this creature) deals? x damage to defending player, where x is the number of cards in their hand"
)


def _damage_x_defending_player_hand(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "selector": "defending_player", "amount_from_defending_player_hand_size": True,
    })]


def _damage_spell_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _targeted_damage(m, amount_from_trigger_event="mana_value")


#: "~ [also] deals N damage to **that creature's controller**" — the
#: controller of a creature an earlier clause targeted ("Destroy target
#: creature. ~ deals 2 damage to that creature's controller." — Consign to
#: the Pit, Blur of Blades, Burn the Impure) or one a group/trigger subject
#: names ("Whenever a creature blocks/dies, ~ deals N damage to that
#: creature's controller." — Battle Strain, Dingus Staff, Gimli). ~22 SOLO.
#: `DealDamageEffect.recipient_subject` derives the player; no RULE 115
#: target of this effect's own.
_DAMAGE_TO_SUBJECT_CONTROLLER_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}(?:also )?deals? "
    r"(?P<n>\d+) damage to that (?:creature|permanent)'?s controller"
)


#: "~ deals N damage to **the player or planeswalker it's attacking**" (Hellrider, Cavalcade of Calamity,
#: Raid Bombardment) — what the attacker that fired the trigger was declared against. A group-subject
#: row: "it"/"that creature" is the attacker (`DealDamageEffect.recipient_subject`).
_DAMAGE_TO_ATTACKED_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to the player or planeswalker "
    r"(?:it'?s|that creature is|that creature'?s) attacking"
)


#: "**it** deals N damage to its controller" / "**that archer** deals that much damage to that
#: creature's controller" (Vengeful Ancestor, Greatbow Doyen) — the firing object is the *dealer*
#: (`segmenter._stamp_damage_dealer` names it from the sentinel) and its controller the recipient.
_GROUP_DEALS_TO_ITS_CONTROLLER_RE = _c(
    r"(?:it|that creature) deals? (?:(?P<n>\d+)|(?P<much>that much)) damage to "
    r"(?:its|that creature'?s) controller"
)


#: "**that archer** deals that much damage to **that creature's** controller" (Greatbow Doyen) — two
#: different objects: the dealer is the firing creature, "that creature" the one the damage went to.
_GROUP_DEALS_TO_DAMAGED_CONTROLLER_RE = _c(
    rf"that (?!creature\b){PRONOUN_NOUN_ALT} deals? that much damage to that creature'?s controller"
)


def _group_deals_to_damaged_controller(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "recipient_subject": "damage_recipient_controller", "amount_from_trigger_event": "amount",
    })]


def _group_deals_to_its_controller(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {"recipient_subject": "trigger_subject_controller"}
    if m.group("much"):
        params["amount_from_trigger_event"] = "amount"
    else:
        params["amount"] = int(m.group("n"))
    return [EffectSpec("damage", params)]


def _damage_to_attacked(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "recipient_subject": "trigger_subject_defender",
    })]


def _damage_to_prev_subject_controller(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "recipient_subject": "previous_subject_controller",
    })]


def _damage_to_trigger_subject_controller(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "recipient_subject": "trigger_subject_controller",
    })]


#: RULE 702.33b's *override* kicked-conditional ("~ deals 2 damage to any
#: target. If this spell was kicked, it deals 4 damage instead." — Burst
#: Lightning/Roil Eruption/Shivan Fire-shaped), distinct from the *additive*
#: "if kicked, `<effect>`." shape `EffectSpec.condition`/`ConditionalEffect`
#: already cover: this doesn't add a second effect, it replaces the first
#: one's amount. Mirrors `_prevent_divided_damage`'s own kicked-override
#: trailing group (`DealDamageEffect.amount_if_kicked`, the sibling of
#: `PreventDamageEffect.amount_if_kicked`). The optional "to that creature"
#: tail (Firebending Lesson) is cosmetic re-naming of the same already-bound
#: target, not a second target phrase.
#: The literal "if this spell was kicked, ... instead" RULE 702.33b override
#: tail shares this exact prefix across every variant below; only the
#: verb-specific middle clause ("it deals N damage"/"create N of those
#: tokens"/"prevent the next N damage this way") genuinely diverges, so only
#: the unconditionally-shared literal is factored out.
_KICKED_OVERRIDE_PREFIX = r"\. if this spell was kicked, "

_DAMAGE_KICKED_OVERRIDE_RE = _c(
    rf"(?:~|it) deals? {NUMBER} damage to {TARGET}"
    rf"{_KICKED_OVERRIDE_PREFIX}it deals (?P<n2>\d+) damage"
    r"(?: to (?:that|the) (?:creature|permanent|player))? instead"
)


def _damage_kicked_override(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "amount_if_kicked": int(m.group("n2")),
        "target_kind": kind, **_optional_param(m),
    })]


#: A single copy-permanent "except …" tail *modifier* — one comma/"and"-
#: separated piece of a (possibly compound) "except" clause — classified
#: into the params it safely maps to, or ``None`` if it's not one of the
#: well-defined shapes below. Deliberately still excludes anything genuinely
#: varied (a P/T override, an arbitrary granted ability, a name change, "it
#: loses all other card types") — those stay unclaimed rather than guessed
#: at, same as every other "can't safely represent this clause" case in this
#: file; a real card needing one is `game/card_catalogue`'s job
#: instead (PAR-18's own compound-except residue: Espers to Magicite/
#: Haunting Imitation/Lazav, Dimir Mastermind/Soul Separator).
#: Card-type words a copy-"except" tail can't be safely reduced to a colour /
#: subtype / `add_types=["Artifact"]` — "enchantment creature" &c. would need
#: `add_types` handling this shape doesn't do, so those stay fail-closed.
_COPY_EXCEPT_REJECT_TYPE_WORDS: frozenset[str] = frozenset(
    {"enchantment", "land", "planeswalker", "permanent"}
)

#: PAR-18 residue — "…except it's a 4/4 black zombie[ creature][ in addition
#: to its other types]" (the Anikthea / Ardyn / God-Pharaoh's Gift / Hour of
#: Eternity reanimator-token cycle). P/T + colour + one creature subtype;
#: the `CopyPermanentEffect.set_power`/`set_toughness`/`set_colors`/
#: `add_subtypes` params all already existed. **Documented simplification:**
#: without "in addition to its other types" the printed clause replaces the
#: copied creature's subtypes rather than adding to them — this always
#: appends (RULE-inexact for tribal synergies only).
_COPY_EXCEPT_PT_RE = re.compile(
    r"it'?s (?:an? )?"
    r"(?:(?P<p>\d+)/(?P<t>\d+)\s*)?"
    r"(?P<mid>[a-z][a-z ]*?)?"
    r"(?P<creature>\s*creature)?"
    # "…except it's a 3/3 black Wraith **with menace**" (Sauron, the
    # Necromancer) — a keyword the copy carries, not a subtype.
    r"(?:\s+with (?P<kw>[a-z][a-z, ]*?))?"
    # PAR-135: "…in addition to its other **colors and** types" adds the colour rather than replacing it.
    r"(?:\s+in addition to its other (?P<colors_too>colors and )?types)?",
    re.IGNORECASE,
)


#: The subject a copy-"except" piece may name for the copy: "it", "the token", or "they" (plural
#: tokens). Read as "it" so one grammar serves all three.
_COPY_EXCEPT_SUBJECT_RES = (
    (re.compile(r"^(?:the token|they) (?:isn'?t|aren'?t|is not|are not) "), "it isn't "),
    (re.compile(r"^(?:the token|they)(?:'re| is| are) "), "it's "),
    (re.compile(r"^(?:the token|they) (?:has|have) "), "it has "),
)


def _copy_except_modifier(piece: str) -> Optional[dict]:
    piece = piece.strip()
    for subject_re, replacement in _COPY_EXCEPT_SUBJECT_RES:
        piece = subject_re.sub(replacement, piece)
    # PAR-142: a later piece of a compound tail drops its subject ("…it isn't legendary and **is a** mutant in
    # addition to its other types"); read it as "it" like the pieces before it.
    if re.match(r"^is an? ", piece):
        piece = "it's " + piece[len("is "):]
    elif re.match(r"^has ", piece):
        piece = "it " + piece
    if piece == "it has haste":
        return {"haste": True}
    if re.fullmatch(r"it isn'?t legendary|it'?s not legendary", piece):
        return {"not_legendary": True}
    if piece in ("it's legendary", "it is legendary"):
        return {"legendary": True}
    m = re.fullmatch(r"it'?s an? (?P<mid>[a-z ]+?) in addition to its other types", piece)
    if m:
        # The shared type-word reader (card types, "legendary", the subtype vocabulary; an unknown word or a
        # colour fails the piece closed), so "enchantment"/"land" are added types rather than bogus subtypes.
        from .static_handlers import type_addition_params  # local: imports handlers

        parsed = type_addition_params(m.group("mid"))
        if parsed is None:
            return None
        out: dict = {}
        # `Card.as_copy` splices these straight into the type line (`f"{main} {' '.join(add_types)}"`), no
        # case-normalization of its own — a real MTG type line is title-cased ("Artifact Creature — Human").
        if parsed.get("add_types"):
            out["add_types"] = [t.capitalize() for t in parsed["add_types"]]
        if parsed.get("add_subtypes"):
            out["add_subtypes"] = list(parsed["add_subtypes"])
        if parsed.get("legendary"):
            out["legendary"] = True
        return out
    pt = _COPY_EXCEPT_PT_RE.fullmatch(piece)
    if pt:
        mid = (pt.group("mid") or "").strip()
        if any(w.rstrip("s") in _COPY_EXCEPT_REJECT_TYPE_WORDS for w in mid.lower().split()):
            return None
        colors, subtypes, is_artifact = _split_token_mid_words(mid)
        out = {}
        if pt.group("p") is not None:
            out["set_power"] = int(pt.group("p"))
            out["set_toughness"] = int(pt.group("t"))
        if colors:
            out["add_colors" if pt.group("colors_too") else "set_colors"] = colors
        add_types: list[str] = []
        if is_artifact:
            add_types.append("Artifact")
        # "…except it's a 3/3 black Zombie **creature** in addition to its
        # other types" (Anikthea, Hand of Erebos): a non-creature original
        # (an enchantment card) genuinely gains the creature type — without
        # it `Card.as_copy` would set P/T on a noncreature and trip
        # `Card.__init__`'s RULE 208.1 invariant (see `as_copy`'s own
        # PAR-30 note). Harmless (idempotent) when the original is already a
        # creature (God-Pharaoh's Gift / Hour of Eternity).
        if pt.group("creature"):
            add_types.append("Creature")
        if add_types:
            out["add_types"] = add_types
        if subtypes:
            out["add_subtypes"] = [s.capitalize() for s in subtypes]
        if pt.groupdict().get("kw"):
            keywords = _token_keywords(pt.group("kw"))
            if keywords is None:
                return None  # an unrecognised keyword — fail the whole tail closed
            out["extra_temp_keywords"] = keywords
        return out or None  # nothing recognised in the piece — fail closed
    return None


#: PAR-18: a (possibly *compound*) "except …" tail — "except it's an
#: artifact in addition to its other types" (a single modifier) / "except
#: it's not legendary and it's an artifact in addition to its other types"
#: (Dedicated Dollmaker-shaped, 2+ modifiers in one sentence) — split on its
#: top-level ", "/" and " connectors and each piece run through
#: `_copy_except_modifier` individually, merging the (fail-closed) results.
#: A comma is split first so a trailing "X, Y and Z" list's own "and" isn't
#: mistaken for a second connector inside one already-split piece.
def _parse_copy_except_tail(tail: str) -> Optional[dict]:
    pieces: list[str] = []
    for chunk in re.split(r",\s*", tail.strip()):
        # "…in addition to its other colors **and types**" is one phrase, not a connector (PAR-135).
        pieces.extend(p for p in re.split(r"\s+and\s+(?!types\b)", chunk) if p.strip())
    if not pieces:
        return None
    merged: dict = {}
    for piece in pieces:
        extra = _copy_except_modifier(piece)
        if extra is None:
            return None  # one unrecognised modifier fails the whole tail closed
        for key, value in extra.items():
            if isinstance(value, list):
                merged[key] = list(dict.fromkeys(merged.get(key, []) + value))
            elif key in merged and merged[key] != value:
                return None  # conflicting modifiers (shouldn't happen; fail closed)
            else:
                merged[key] = value
    return merged


#: Batch 4: the head of every "create … token(s) that's/are a copy/copies of <referent>" row — one token
#: (optionally tapped / attacking) or a counted plural ("create 2 tokens that are copies of", "create X tokens
#: that are copies of"). ``n`` is absent for the singular.
_COPY_HEAD = (
    r"create (?:an? (?P<ta>tapped and attacking |tapped |attacking )?token that'?s an? copy"
    r"|(?P<n>\d+|x|two|three) (?P<tb>tapped and attacking |tapped |attacking )?tokens that are copies) of "
)


def _copy_head_params(m: re.Match[str]) -> Optional[dict]:
    """The count / tapped / attacking params the shared head carries (``None`` = an unreadable count)."""
    groups = m.groupdict()
    params: dict = {}
    if groups.get("n"):
        count = count_or_x_of(groups["n"])
        if count is None:
            return None
        params["count"] = count
    flags = (groups.get("ta") or groups.get("tb") or "").strip()
    if "tapped" in flags:
        params["tapped"] = True
    if "attacking" in flags:
        params["attacking"] = True
    return params


#: RULE 707/706.2's "create a token that's a copy of target X[, except
#: <modifier>[, <modifier>...][ and <modifier>]]" (Cackling Counterpart/
#: Rite of Replication/Multiversal Recruitment/Impostor Syndrome-shaped) —
#: the bare form and every safely-generalizable "except" tail
#: (`_parse_copy_except_tail`) share one row; an "except" tail with even one
#: unrecognised modifier still fails the whole clause closed rather than
#: silently dropping it.
_COPY_PERMANENT_RE = _c(
    # The comma before "except" is optional: "a copy of that creature except it's an artifact" (Faerie Artisans).
    rf"{_COPY_HEAD}{TARGET}(?:,?\s+except (?P<except_tail>.+))?"
)

#: PAR-142: the granted end-step clause of a temporary copy — "…except it has haste and \"at the beginning of the
#: end step, sacrifice ~.\"" (Minion Reflector, Kindle the Inner Flame, Electroduplicate; "exile ~" on Heat
#: Shimmer). The same delayed trigger the sentence form "sacrifice it at the beginning of the next end step"
#: (Kiki-Jiki) emits, on the object the copy made — so the grant is modelled as that delayed trigger, not a
#: granted ability on the token.
_COPY_END_STEP_GRANT_RE = re.compile(
    r'(?:,? and |, )"at the beginning of the end step, (?P<verb>sacrifice|exile) ~\.?"\s*$', re.IGNORECASE,
)


def _copy_with_tail(params: dict, tail: Optional[str]) -> Optional[list[EffectSpec]]:
    """The `copy_permanent` spec for ``params`` with a copy-"except" ``tail`` folded in (PAR-142): the parsed
    modifiers, and — for a granted end-step clause — the delayed trigger that ends the copy. ``None`` (fail
    closed) when any piece of the tail is unrecognised."""
    delayed: Optional[str] = None
    if tail:
        grant = _COPY_END_STEP_GRANT_RE.search(tail)
        if grant is not None:
            delayed = grant.group("verb").lower()
            tail = tail[: grant.start()]
        extra = _parse_copy_except_tail(tail) if tail.strip() else {}
        if extra is None:
            return None
        params.update(extra)
    specs = [EffectSpec("copy_permanent", params)]
    if delayed is not None:
        specs.append(EffectSpec("create_delayed_trigger", {
            "step": "end", "scope": "any", "capture": "previous_or_self",
            "effects": [{"type": _DELAYED_TAIL_INNER[delayed], "params": {}}],
        }))
    return specs


def _copy_permanent(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    head = _copy_head_params(m)
    if head is None:
        return None
    params: dict = {"target_kind": kind, **_optional_param(m), **head}
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter  # "target nonlegendary creature" (Kiki-Jiki)
    return _copy_with_tail(params, m.groupdict().get("except_tail"))


#: "Create a token that's a copy of ~, except it has haste." (Splinter
#: Twin/Kiki-Jiki-shaped).  This is intentionally separate from TARGET:
#: ``~`` is not a RULE 115 target, so the copied permanent is the ability's
#: source and must remain stable when the ability was granted by an Aura.
_COPY_SELF_RE = _c(
    rf"{_COPY_HEAD}~(?:, except (?P<except_tail>[^.]+))?"
)

def _copy_self(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    head = _copy_head_params(m)
    if head is None:
        return None
    params: dict = {"target_kind": None, "referent": "source", **head}
    tail = m.groupdict().get("except_tail")
    if tail:
        extra = _parse_copy_except_tail(tail)
        if extra is None:
            return None
        params.update(extra)
    return [EffectSpec("copy_permanent", params)]


#: The RULE 702.33b kicked-override sibling — "Create a token that's a copy
#: of target creature. If this spell was kicked, create five of those
#: tokens instead." (Rite of Replication) — same override shape as
#: `_damage_kicked_override`, just replacing ``count`` instead of ``amount``
#: (`CopyPermanentEffect.count_if_kicked`).
_COPY_PERMANENT_KICKED_OVERRIDE_RE = _c(
    rf"create a token that'?s a copy of {TARGET}"
    rf"{_KICKED_OVERRIDE_PREFIX}create (?P<n2>\d+) of those tokens instead"
)


def _copy_permanent_kicked_override(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("copy_permanent", {
        "target_kind": kind, "count_if_kicked": int(m.group("n2")), **_optional_param(m),
    })]


#: PAR-18's own pronoun antecedent — "exile up to 1 target creature card
#: from a graveyard. Create a token that's a copy of **it**/**that
#: card**[, except <modifier(s)>]." (Ardyn, the Usurper/Anikthea, Hand of
#: Erebos-shaped): the copied object is what an *earlier clause of the same
#: ability* just targeted (RULE 608.2 resolution order, `GameContext.
#: previous_targets` — `CopyPermanentEffect.referent="previous"`), not a
#: fresh RULE 115 target of this clause's own and not the ability's own
#: source either. `previous_subject_only`-gated the same way `_goad_previous`
#: is: only offered once `segmenter.parse_effect_body` has actually split
#: off an earlier clause that announced a target. Shares
#: `_parse_copy_except_tail` with the plain-target row above.
_COPY_PERMANENT_PREVIOUS_RE = _c(
    rf"{_COPY_HEAD}(?:it|that (?:card|creature|permanent|artifact|enchantment|land))"
    r"(?:,?\s+except (?P<except_tail>.+))?"
)


def _copy_permanent_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    head = _copy_head_params(m)
    if head is None:
        return None
    # "create a **tapped and attacking** token that's a copy of that card…" (RULE 508.4 — Sauron, the
    # Necromancer). `CopyPermanentEffect` already takes ``tapped``/``attacking``.
    params: dict = {"target_kind": None, "referent": "previous", **head}
    return _copy_with_tail(params, m.groupdict().get("except_tail"))


#: PAR-124: the RULE 603.1 group-subject sibling of `_COPY_PERMANENT_
#: PREVIOUS_RE` above — "whenever a nontoken creature an opponent controls
#: enters[ this turn], create a token that's a copy of **that creature**."
#: (Theoretical Duplication). "That creature" here is whichever object
#: satisfied the *trigger condition*, not an earlier clause's own RULE 115
#: pick — `CopyPermanentEffect.referent="trigger_event"` already reads
#: exactly this off `GameContext.trigger_event["instance_id"]` (built for
#: Ashling, the Limitless's "…create a token that's a copy of **it**.",
#: MEC-42), and every event this row's own trigger head reaches
#: (`_subject_event_key`'s default) already keys the acting object the
#: same way, so no new event-field threading is needed.
_COPY_PERMANENT_GROUP_RE = _c(
    rf"{_COPY_HEAD}(?:it|that creature|that card)"
    r"(?:,?\s+except (?P<except_tail>.+))?"
)


def _copy_permanent_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    head = _copy_head_params(m)
    if head is None:
        return None
    params: dict = {"target_kind": None, "referent": "trigger_event", **head}
    return _copy_with_tail(params, m.groupdict().get("except_tail"))


#: "create a token that's [a] [tapped and attacking] copy of `<a specific
#: named real card>`" (The Joiner of Cats' "…a tapped and attacking copy of
#: Lurrus of the Dream-Den" — the else-branch of its `impulsive_look`). The
#: copied card is neither a RULE 115 target, a pronoun antecedent nor this
#: ability's own source — it's a fixed card *named in the text*, resolved
#: from the cache by `CreateNamedCardTokenEffect`. The name group rejects
#: the target/pronoun leading words the rows above own, so this only ever
#: fires on a genuine proper-noun card name.
_CREATE_NAMED_CARD_TOKEN_RE = _c(
    r"create a token that'?s (?:an? )?"
    r"(?P<ta>tapped and attacking |tapped |attacking )?copy of "
    r"(?!(?:target|that|it|the|this|each|another|a|an|any|one|those|your|"
    r"enchanted|equipped|up|chosen|exiled)\b)"
    r"(?P<name>[a-z][a-z0-9 ,'.\-]+?)"
    r"(?:, except (?P<except_tail>it isn'?t legendary))?"
)

#: A card name is only trusted in this narrow spot when it *looks* like a
#: proper name — a legendary's "`<given>`, `<title>`" / "`<given>` of `<place>`"
#: shape, or a hyphenated/possessive name — never a bare two plain words
#: ("enchanted creature", "target artifact" the lookahead above already
#: rules out; "chosen permanent" it doesn't). Fail-closed: better UNMODELED
#: than a token copy of a card that doesn't exist.
_NAMED_CARD_SHAPE_RE = re.compile(r" of | the |,|'|[a-z]-[a-z]")


#: "for each `<count>`, create a token that's a copy of ~[, except the
#: token isn't legendary]" (Living Laser — "for each card you've discarded
#: this turn, create a token that's a copy of Living Laser, except the
#: token isn't legendary"). The copied object is the ability's own source
#: (``target_kind=None`` / ``referent="source"``), the count comes from a
#: `continuous.count_selector`. Deliberately just the one selector phrase
#: seen so far; anything else fails the clause closed.
_COPY_SELF_FOR_EACH_SELECTORS: dict[str, str] = {
    "card you've discarded this turn": "cards_discarded_this_turn",
}
_COPY_SELF_FOR_EACH_RE = _c(
    r"for each (?P<sel>card you'?ve discarded this turn), "
    r"create a token that'?s a copy of ~"
    r"(?:, except (?:the token|it) (?P<not_legendary>isn'?t legendary))?"
)


#: "Exile a permanent card from your graveyard at random, then create a
#: tapped token that's a copy of that card. If the exiled card is a land
#: card, repeat this process." (Sin, Spira's Punishment) — one fixed
#: phrasing → the self-contained `random_graveyard_exile_copy_loop` effect
#: (RULE 706 randomization + RULE 707.2 copy in a land-keyed loop).
_RANDOM_GY_EXILE_COPY_LOOP_RE = _c(
    r"exile a permanent card from your graveyard at random, then create a "
    r"tapped token that'?s a copy of that card\. if the exiled card is a "
    r"land card, repeat this process"
)


def _random_gy_exile_copy_loop(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("random_graveyard_exile_copy_loop", {})]


def _copy_self_for_each(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector = _COPY_SELF_FOR_EACH_SELECTORS.get(m.group("sel").replace("'", "'"))
    if selector is None:
        # normalize may keep a curly apostrophe — retry with it straightened
        selector = _COPY_SELF_FOR_EACH_SELECTORS.get(
            m.group("sel").replace("’", "'")
        )
    if selector is None:
        return None
    params: dict = {"target_kind": None, "referent": "source", "count_selector": selector}
    if m.groupdict().get("not_legendary"):
        params["not_legendary"] = True
    return [EffectSpec("copy_permanent", params)]


def _create_named_card_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    name = (m.group("name") or "").strip().rstrip(".")
    if len(name) < 3 or not _NAMED_CARD_SHAPE_RE.search(name):
        return None
    ta = (m.groupdict().get("ta") or "").strip()
    params: dict = {"card_name": name}
    if "tapped" in ta:
        params["tapped"] = True
    if "attacking" in ta:
        params["attacking"] = True
    if m.groupdict().get("except_tail"):
        params["not_legendary"] = True
    return [EffectSpec("create_token_copy_of_named", params)]


def _damage_each_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None:
        return None
    return [EffectSpec("damage", {"amount": int(m.group("amount")), **params})]


#: RULE 601.2d's "divided as you choose among any number of target(s)"
#: (PAR-15's own named biggest cluster — Fire Covenant/Aurelia's Fury/
#: Avacyn's Judgment/Bogardan Hellkite-shaped) — a *split* total, not the
#: full amount to every chosen target the way `_damage_each_multi_target`
#: above is. `DealDamageEffect(divided=True)` (RULE 601.2d) already existed
#: as an engine primitive — Shatterskull Smashing/Fire Covenant, both
#: hand-authored (`game/card_catalogue`, cEDH-cube batch 19) — but no
#: oracle-text recognizer had ever reached it; this is that recognizer, not
#: a new primitive. "targets" (unqualified, RULE 115.4 "any target"),
#: "target creatures", and the Modern Horizons Incarnation wording
#: "target creatures and/or planeswalkers" are the real phrasings.
_DIVIDED_DAMAGE_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}"
    rf"deals? {COUNT_X} damage divided as you choose among any number of "
    r"(?P<target>targets|target creatures and/or planeswalkers|target creatures)"
    # PAR-128: "… your opponents control" (Dragonlord Atarka, Polukranos).
    rf"(?P<scope>{_MULTI_TARGET_SCOPE_TAIL})?"
)


def _divided_damage(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    target = m.group("target")
    kind = (
        "creature" if target == "target creatures"
        else "creature_or_planeswalker" if target == "target creatures and/or planeswalkers"
        else "any"
    )
    if m.group("scope"):
        kind = NOT_YOU_TARGET_KINDS.get(kind)
        if kind is None:  # bare "targets" has no scoped pool
            return None
    return [EffectSpec("damage", {
        "amount": count_or_x_of(m.group("n")), "target_kind": kind,
        "count": _ANY_NUMBER_TARGET_CAP, "optional": True, "divided": True,
    })]


#: ENG-30: "deals N damage divided as you choose among 1 or 2 targets"
#: (Arc Mage/Chandra's Pyrohelix/Electrolyze/Fire // Ice/Forked Bolt/
#: Skarrgan Hellkite-shaped) — the *fixed range* sibling of
#: `_DIVIDED_DAMAGE_RE`'s "any number of": a genuine RULE 601.2c minimum of
#: one. Same local ``targets|target creatures`` alternation as that row
#: (not the shared `_MULTI_TARGET_ALT`, which this family has never used).
_DIVIDED_DAMAGE_RANGE_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}"
    rf"deals? {COUNT_X} damage divided as you choose among "
    r"(?P<range_min>\d+) or (?P<range_max>\d+) (?P<target>targets|target creatures)"
)


def _divided_damage_range(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
    if range_min < 1 or range_max <= range_min:
        return None
    kind = "creature" if m.group("target") == "target creatures" else "any"
    return [EffectSpec("damage", {
        "amount": count_or_x_of(m.group("n")), "target_kind": kind,
        "count": range_min, "count_max": range_max, "divided": True,
    })]


#: ENG-30: "deals N damage to each of 1 or 2 targets" (Storm of Steel) — the
#: full-amount-to-each sibling of `_divided_damage_range` (mirrors how
#: `_damage_each_multi_target` relates to `_divided_damage` for the "any
#: number of"/"up to N" shapes), same local bare-``targets`` alternation.
_DAMAGE_EACH_RANGE_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}"
    rf"deals? (?P<amount>\d+) damage to each of "
    r"(?P<range_min>\d+) or (?P<range_max>\d+) (?P<target>targets|target creatures)"
)


def _damage_each_range(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
    if range_min < 1 or range_max <= range_min:
        return None
    kind = "creature" if m.group("target") == "target creatures" else "any"
    return [EffectSpec("damage", {
        "amount": int(m.group("amount")), "target_kind": kind,
        "count": range_min, "count_max": range_max,
    })]


#: RULE 615's targeted divided-prevention sibling of `_DIVIDED_DAMAGE_RE`
#: (PAR-15's own "prevent-divided" residue cluster — Embolden/Remedy/Angel
#: of Salvation): "prevent the next N damage that would be dealt this turn
#: to any number of targets, divided as you choose." `PreventDamageEffect`
#: already existed as the untargeted "prevent all/N damage to you" shield
#: (Riot Control/Thought Lash, hand-authored); this recognizer — and the
#: targeted/divided mode it drives — is new. The optional trailing group is
#: Pollen Remedy's own "if this spell was kicked, prevent the next N damage
#: this way instead" *override* (`PreventDamageEffect.amount_if_kicked`),
#: distinct from RULE 702.33b's additive kicked-conditional shape.
_PREVENT_DIVIDED_DAMAGE_RE = _c(
    r"prevent the next (?P<n>\d+) damage that would be dealt this turn to "
    r"any number of targets, divided as you choose"
    rf"(?:{_KICKED_OVERRIDE_PREFIX}prevent the next (?P<n2>\d+) damage this way instead)?"
)


def _prevent_divided_damage(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "amount": int(m.group("n")), "target_kind": "any",
        "count": _ANY_NUMBER_TARGET_CAP, "optional": True, "divided": True,
    }
    if m.group("n2") is not None:
        params["amount_if_kicked"] = int(m.group("n2"))
    return [EffectSpec("prevent_damage_shield", params)]


#: RULE 615's plain single-target sibling — "prevent the next N damage that
#: would be dealt to any target this turn." (Alabaster Wall/Amulet of Kroog/
#: Aven Redeemer-shaped, usually a `{cost}: <effect>` activated ability on an
#: artifact/creature) — note the different word order from
#: `_PREVENT_DIVIDED_DAMAGE_RE` just above ("dealt **to any target** this
#: turn" vs that row's "dealt this turn **to any number of targets**"), which
#: is what keeps the two rows from colliding. `PreventDamageEffect`'s
#: ``target_kind`` branch already supports exactly one real RULE 115 target
#: with no ``divided`` flag (its default) — only this oracle-text
#: recognition was missing.
_PREVENT_DAMAGE_SINGLE_TARGET_RE = _c(
    r"prevent the next (?P<n>\d+) damage that would be dealt to any target this turn"
)


def _prevent_damage_single_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_damage_shield", {"amount": int(m.group("n")), "target_kind": "any"})]


#: PAR-139: "prevent the next N damage that would be dealt to target creature this turn" (Test of Faith, Temper's
#: X) — the creature sibling of the any-target row above; ``x`` is the spell's announced X.
_PREVENT_NEXT_DAMAGE_TARGET_CREATURE_RE = _c(
    r"prevent the next (?P<n>\d+|x) damage that would be dealt to target creature this turn"
)


def _prevent_next_damage_target_creature(m: re.Match[str]) -> list[EffectSpec]:
    n = m.group("n").lower()
    return [EffectSpec("prevent_damage_shield", {
        "amount": "x" if n == "x" else int(n), "target_kind": "creature",
    })]


#: PAR-139: a one-shot shield followed by a rider keyed on the amount it prevented — "Prevent the next 3 damage
#: that would be dealt to target creature this turn. For each 1 damage prevented this way, put a +1/+1 counter on
#: that creature." (Test of Faith, Temper) / "… You gain life equal to the damage prevented this way." (Candles'
#: Glow). The shield sentence is read by the ordinary rows; the rider is `RulesEngine.apply_prevent_rider`'s.
_PREVENT_SHIELD_THEN_RIDER_RE = _c(
    r"(?P<shield>prevent the next (?:\d+|x) damage that would be dealt to [^.]+? this turn)\.\s+"
    r"(?:for each 1 damage prevented this way, put an? (?P<kind>[+\-]\d+/[+\-]\d+) counter on that creature"
    r"|(?P<life>you gain life equal to the damage prevented this way))"
)


def _prevent_shield_then_rider(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    shield = match_clause(m.group("shield"))
    if shield is None or len(shield) != 1 or shield[0].type != "prevent_damage_shield" or "rider" in shield[0].params:
        return None
    if m.group("life"):
        rider: dict = {"kind": "gain_life", "recipient": "you"}
    elif shield[0].params.get("target_kind") == "creature":
        rider = {"kind": "add_scaled_counters", "on": "recipient", "counter": m.group("kind")}
    else:
        return None  # "that creature" needs a creature-only target
    return [EffectSpec("prevent_damage_shield", {**shield[0].params, "rider": rider})]


_PREVENT_DAMAGE_PLAYER_PLANESWALKER_OR_SUBTYPE_RE = _c(
    r"prevent the next (?P<n>\d+) damage that would be dealt to target player, planeswalker, or "
    r"(?P<subtype>[a-z]+) creature this turn"
)


def _prevent_damage_player_planeswalker_or_subtype(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_damage_shield", {
        "amount": int(m.group("n")),
        "target_kind": "player_or_planeswalker_or_creature_subtype",
        "creature_filter": {"subtype": m.group("subtype").capitalize()},
    })]


#: "Prevent the next N damage that would be dealt to you this turn"
#: (Security Blockade). The existing shield effect defaults to the ability's
#: controller; unlike the adjacent any-target row, this has no target choice.
_PREVENT_NEXT_DAMAGE_TO_YOU_RE = _c(
    r"prevent the next (?P<n>\d+) damage that would be dealt to you this turn"
)


def _prevent_next_damage_to_you(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_damage_shield", {"amount": int(m.group("n"))})]


#: RULE 615's unscoped Fog-shaped form — "Prevent all combat damage that
#: would be dealt this turn." (Fog/Darkness/Constant Mists/Holy Day/Lull/
#: Moment's Peace/…, one of the most repeated templates in the cache). No
#: recipient, no ``TARGET`` group: everyone's combat damage, not the
#: single chosen shield `_PREVENT_DAMAGE_SINGLE_TARGET_RE`/
#: `_PREVENT_DIVIDED_DAMAGE_RE` build. Deliberately just the bare clause —
#: a qualified variant ("…by non-Spider creatures"/"…except combat damage
#: dealt by enchanted creatures") would need a source-filter param this
#: engine doesn't have yet, so those stay unclaimed rather than being
#: half-modeled as unqualified.
_PREVENT_ALL_COMBAT_DAMAGE_RE = _c(r"prevent all combat damage that would be dealt this turn")


def _prevent_all_combat_damage(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_all_combat_damage", {})]


#: "Prevent all combat damage that would be dealt to this creature this turn"
#: (Blinding Powder).  This is a personal, one-turn shield, not the global
#: Fog form above; `PreventDamageEffect.self_only` already supplies its
#: replacement-effect semantics.
_PREVENT_ALL_COMBAT_DAMAGE_TO_SELF_RE = _c(
    r"prevent all combat damage that would be dealt to (?:this creature|this permanent|~) this turn"
)


def _prevent_all_combat_damage_to_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_damage_shield", {
        "amount": "all", "self_only": True, "combat_only": True,
    })]


_PREVENT_ALL_COMBAT_DAMAGE_DEALT_SELF_RE = _c(
    r"prevent all combat damage (?:this creature|this permanent|~) would deal this turn"
)


def _prevent_all_combat_damage_dealt_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_combat_damage_dealt", {})]


#: PAR-78: "Prevent all damage that would be dealt to `<recipient>` **by
#: `<source filter>`**." (Argothian Pixies/Champion Lancer/Prismatic Ward/
#: Deep Wood/Scarecrow/…, ~50 real cards) — the source-qualified sibling of
#: the plain (unqualified) "prevent all damage…" rows below. A closed,
#: fail-closed whitelist (`PreventDamageEffect.source_filter`'s own
#: vocabulary, `RulesEngine._damage_source_matches`) rather than a
#: compositional grammar — an unrecognized filter phrase leaves the whole
#: clause unclaimed instead of guessing.
_PREVENT_SOURCE_FILTER_PHRASES: dict[str, dict] = {
    "creatures": {"creature": True},
    "artifact creatures": {"creature": True, "artifact": True},
    "artifact sources": {"artifact": True},
    "sources you control": {"controller": "you"},
    "sources you don'?t control": {"controller": "not_you"},
    "sources your opponents control": {"controller": "not_you"},
    "attacking creatures": {"creature": True, "attacking": True},
    "attacking creatures without flying": {"creature": True, "attacking": True, "without_keyword": "flying"},
    "creatures with flying": {"creature": True, "keyword": "flying"},
    "creatures with first strike": {"creature": True, "keyword": "first_strike"},
    "deserts": {"subtype": "desert"},
    "enchanted creatures": {"creature": True, "enchanted": True},
}
#: Built from the dict above, longest-alternative-first so e.g. "attacking
#: creatures without flying" wins over the shorter "attacking creatures".
_PREVENT_SOURCE_FILTER_ALT = "|".join(
    sorted(_PREVENT_SOURCE_FILTER_PHRASES, key=len, reverse=True)
)


def _parse_prevent_source_filter(phrase: str) -> Optional[dict]:
    """A matched `_PREVENT_SOURCE_FILTER_ALT` phrase → its `source_filter`
    dict, or ``None`` if unrecognized (fail-closed)."""
    text = phrase.strip().lower()
    for pattern, filt in _PREVENT_SOURCE_FILTER_PHRASES.items():
        if re.fullmatch(pattern, text):
            return dict(filt)
    return None


#: PAR-78: bare self — "Prevent all damage that would be dealt to
#: `<~/this creature/this permanent>`[ this turn][ **by** `<source
#: filter>`]." (Cho-Manno, Revolutionary/Dawn Elemental/Argothian Pixies/
#: Champion Lancer/Wall of Putrid Flesh/…).
_PREVENT_ALL_DAMAGE_SELF_RE = _c(
    r"prevent all damage that would be dealt to (?:~|this creature|this permanent)"
    r"(?: this turn)?"
    rf"(?: by (?P<filter>{_PREVENT_SOURCE_FILTER_ALT}))?"
)


def _prevent_all_damage_self(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"amount": "all", "self_only": True}
    filt = m.groupdict().get("filter")
    if filt:
        source_filter = _parse_prevent_source_filter(filt)
        if source_filter is None:
            return None
        params["source_filter"] = source_filter
    return [EffectSpec("prevent_damage_shield", params)]


#: PAR-78: the untargeted "you" shield — "Prevent all damage that would be
#: dealt to you[ **and** creatures/permanents you control][ this turn][
#: **by** `<source filter>`]." (Solitary Confinement/Endure/Safe Passage/
#: Deep Wood/Scarecrow/Eerie Interference/…).
_PREVENT_ALL_DAMAGE_YOU_RE = _c(
    r"prevent all damage that would be dealt to you"
    r"(?: and (?P<scope>creatures|permanents) you control)?"
    r"(?: this turn)?"
    rf"(?: by (?P<filter>{_PREVENT_SOURCE_FILTER_ALT}))?"
)


def _prevent_all_damage_you(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"amount": "all"}
    scope = m.groupdict().get("scope")
    if scope:
        params["recipient_scope"] = scope
    filt = m.groupdict().get("filter")
    if filt:
        source_filter = _parse_prevent_source_filter(filt)
        if source_filter is None:
            return None
        params["source_filter"] = source_filter
    return [EffectSpec("prevent_damage_shield", params)]


#: PAR-78: the board-wide creature-recipient shield — "Prevent all damage
#: that would be dealt to [`<attacking/artifact> `]creatures[ **you
#: control**]/creature tokens you control[ this turn][ **by** `<source
#: filter>`]." (Forfend/Bubble Matrix/Inner Sanctum/Emmara Tandris/Iroas/
#: Ethersworn Shieldmage/Light of Sanction/…) — no player-shield half at
#: all, unlike the "you" row above.
_PREVENT_ALL_DAMAGE_CREATURES_RE = _c(
    r"prevent all damage that would be dealt to "
    r"(?:(?P<attacking>attacking creatures)|(?P<artifact>artifact creatures)|"
    r"(?P<tokens>creature tokens)|creatures)"
    r"(?P<yc> you control)?"
    r"(?: this turn)?"
    rf"(?: by (?P<filter>{_PREVENT_SOURCE_FILTER_ALT}))?"
)


def _prevent_all_damage_creatures(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "amount": "all",
        "recipient_creatures_scope": "you_control" if m.groupdict().get("yc") else "all",
    }
    recipient_filter: dict = {}
    if m.groupdict().get("attacking"):
        recipient_filter["attacking"] = True
    elif m.groupdict().get("artifact"):
        recipient_filter["artifact"] = True
    elif m.groupdict().get("tokens"):
        recipient_filter["token"] = True
    if recipient_filter:
        params["recipient_filter"] = recipient_filter
    filt = m.groupdict().get("filter")
    if filt:
        source_filter = _parse_prevent_source_filter(filt)
        if source_filter is None:
            return None
        params["source_filter"] = source_filter
    return [EffectSpec("prevent_damage_shield", params)]


#: PAR-78: the RULE 115 target form — "Prevent all damage that would be
#: dealt to target creature[ with power `<N>` or greater] this turn[ **by**
#: `<source filter>`]." (Indestructible Aura/Shielded Passage/Godtoucher/
#: Harvestguard Alseids/…).
#: PAR-78: the closed subtype-word vocabulary `_prevent_all_damage_target`
#: accepts before "creature" — see its own docstring for why this isn't an
#: open vocabulary. Small on purpose; widen only when a real card needs
#: another word.
_PREVENT_TARGET_SUBTYPE_WORDS: frozenset[str] = frozenset({"merfolk", "kithkin"})
_PREVENT_ALL_DAMAGE_TARGET_RE = _c(
    r"prevent all damage that would be dealt to target "
    r"(?:(?P<tapped>tapped) )?(?:(?P<legendary>legendary) )?"
    r"(?:(?P<subtype1>[a-z]+)(?: or (?P<subtype2>[a-z]+))? )?creature"
    r"(?: with power (?P<minpower>\d+) or greater)?"
    r" this turn"
    rf"(?: by (?P<filter>{_PREVENT_SOURCE_FILTER_ALT}))?"
)


def _prevent_all_damage_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"amount": "all", "target_kind": "creature"}
    creature_filter: dict = {}
    minpower = m.groupdict().get("minpower")
    if minpower:
        creature_filter["min_power"] = int(minpower)
    if m.groupdict().get("legendary"):
        creature_filter["legendary"] = True
    if m.groupdict().get("tapped"):
        creature_filter["tapped"] = True
    # "target tapped Merfolk or Kithkin creature" (Wellgabber Apothecary,
    # PAR-78) — a two-word subtype OR-filter. ``_PREVENT_TARGET_SUBTYPE_
    # WORDS`` is a deliberately closed, explicit list (this project's own
    # convention — `static_handlers._SPELL_COST_SUBTYPE_WORDS`'s own
    # docstring — rather than an open vocabulary, since a word here could
    # just as easily be a qualifier like "attacking", not a subtype).
    subtype1 = m.groupdict().get("subtype1")
    subtype2 = m.groupdict().get("subtype2")
    if subtype1:
        words = [subtype1] + ([subtype2] if subtype2 else [])
        if not all(w in _PREVENT_TARGET_SUBTYPE_WORDS for w in words):
            return None
        if len(words) == 1:
            creature_filter["subtype"] = words[0].title()
        else:
            creature_filter["subtype_any"] = [w.title() for w in words]
    if creature_filter:
        params["creature_filter"] = creature_filter
    filt = m.groupdict().get("filter")
    if filt:
        source_filter = _parse_prevent_source_filter(filt)
        if source_filter is None:
            return None
        params["source_filter"] = source_filter
    return [EffectSpec("prevent_damage_shield", params)]


#: PAR-78: the previous-target pronoun form — "`<earlier clause>`. Prevent
#: all damage that would be dealt to it/that creature this turn[ **by**
#: `<source filter>`]." (Djeru's Resolve/Leap of Faith/Enshrouding Mist/
#: Glyph of Destruction) — "it"/"that creature" naming whichever creature
#: the *preceding* clause of this same body targeted, `previous_subject_
#: only`-gated (never offered to a clause parsed standalone).
_PREVENT_ALL_DAMAGE_PREVIOUS_RE = _c(
    r"prevent all damage that would be dealt to (?:it|that creature) this turn"
    rf"(?: by (?P<filter>{_PREVENT_SOURCE_FILTER_ALT}))?"
)


def _prevent_all_damage_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"amount": "all", "previous_subject": True}
    filt = m.groupdict().get("filter")
    if filt:
        source_filter = _parse_prevent_source_filter(filt)
        if source_filter is None:
            return None
        params["source_filter"] = source_filter
    return [EffectSpec("prevent_damage_shield", params)]


#: PAR-78: the self-subject pronoun sibling — "…put a +1/+1 counter on ~
#: and prevent all damage that would be dealt to **it** this turn."
#: (Favored Hoplite) — "it" naming this ability's own source, not a
#: previous RULE 115 pick (no target was ever chosen; "~" appears earlier
#: in the very same compound sentence). `self_subject_only`-gated, the
#: bare-imperative-clause sibling of `_PREVENT_ALL_DAMAGE_PREVIOUS_RE`.
#: "him"/"her" (Gideon, Ally of Zendikar — "~ becomes a 5/5 ... creature
#: ... . Prevent all damage that would be dealt to **him** this turn.") is
#: the identical self-reference, just gendered per the planeswalker's own
#: printed pronoun rather than "it".
_PREVENT_ALL_DAMAGE_SELF_PRONOUN_RE = _c(
    r"prevent all damage that would be dealt to (?:it|him|her) this turn"
    rf"(?: by (?P<filter>{_PREVENT_SOURCE_FILTER_ALT}))?"
)


def _prevent_all_damage_self_pronoun(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"amount": "all", "self_only": True}
    filt = m.groupdict().get("filter")
    if filt:
        source_filter = _parse_prevent_source_filter(filt)
        if source_filter is None:
            return None
        params["source_filter"] = source_filter
    return [EffectSpec("prevent_damage_shield", params)]


#: PAR-78: the Aura self-host form — "Prevent all damage that would be
#: dealt to enchanted creature[ **by** `<source filter>`]." (Inviolability).
_PREVENT_ALL_DAMAGE_ENCHANTED_RE = _c(
    r"prevent all damage that would be dealt to enchanted creature"
    rf"(?: by (?P<filter>{_PREVENT_SOURCE_FILTER_ALT}))?"
)


def _prevent_all_damage_enchanted(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"amount": "all", "attached_only": True}
    filt = m.groupdict().get("filter")
    if filt:
        source_filter = _parse_prevent_source_filter(filt)
        if source_filter is None:
            return None
        params["source_filter"] = source_filter
    return [EffectSpec("prevent_damage_shield", params)]


#: RULE 601.2c's mass/untargeted-selector vocabulary — shared by the
#: damage/lose_life/player-counter "each creature/player/opponent" families
#: below, not RULE 115 targeting (see `subgrammars._TARGET_ROWS`'s note on
#: why "each opponent"/"each player" stay out of that grammar). Each
#: family's own regex alternation still independently gates which of these
#: keys it can actually capture — this dict is a pure value lookup, not a
#: regex-alternation source — *except* `_DAMAGE_SELECTOR_ALT` below, which
#: intentionally reads only the damage-legal subset rather than every key
#: here, since no card prints "deals damage to each other player".
_SELECTOR_WORD_MAP: dict[str, str] = {
    "each creature": "each_creature",
    # PAR-128: RULE 109.5 — every creature but the damage's own source.
    "each other creature": "each_other_creature",
    "each player": "each_player",
    "each opponent": "each_opponent",
    # "each of your opponents" (Aurelia, the Law Above) — the same group, spelled for a trigger controlled by "you".
    "each of your opponents": "each_opponent",
    # Symmetric mass-damage board wipes (RULE 601.2c) — the global-scope
    # union selectors `DealDamageEffect` already resolves. "each creature
    # and each player" (Cave-In / Fire Tempest / Inferno / Pestilence-
    # shaped, ~32 SOLO); "each creature and each planeswalker" (Star of
    # Extinction / Dragonback Assault, ~7 SOLO). Only the `damage` family's
    # own regex row (`damage_selector`) opts these keys in.
    "each creature and each player": "each_creature_and_player",
    "each creature and each planeswalker": "each_creature_and_planeswalker",
    # "~ deals N damage to each creature your opponents control." (Village
    # Pillagers) / "…an opponent controls" — `DealDamageEffect`'s
    # ``each_creature_opponents_control`` (opponents' creatures, no players).
    "each creature your opponents control": "each_creature_opponents_control",
    "each creature an opponent controls": "each_creature_opponents_control",
    # "~ deals N damage to **you**" (RULE 109.5 — the source's own
    # controller, and only them; Mana Vault / Fledgling Djinn / Juzám Djinn
    # / Sulfuric Vortex-shaped upkeep bleed). `DealDamageEffect`'s
    # ``"controller"`` selector.
    "you": "controller",
    # "each other player" (Urborg Syphon-Mage, lose_life/rad-counter only) —
    # functionally identical to "each opponent" in this engine (no
    # team-variant life sharing, RULE 809/810/811 — PLR-14, still unbuilt).
    "each other player": "each_opponent",
    "each other opponent": "each_other_opponent",
    # "whenever a player casts a spell, ~ deals 2 damage to that player."
    # (Spellshock-shaped) — the player named by the trigger's own firing
    # event (`effects.DealDamageEffect`'s ``"event_player"`` selector), not
    # an untargeted group like the rows above.
    "that player": "event_player",
    # "…if it's not their turn, ~ deals 4 damage to them." (Scytheclaw
    # Raptor) — same firing-event player, just the pronoun object form
    # rather than "that player".
    "them": "event_player",
}


#: "~ deals N damage to target `<color>` or `<color>` creature." (Rending
#: Volley-shaped) — `TargetSpec.colors`' own OR narrowing (`_destroy`'s
#: single-``color`` sibling; only ever two colours on a real card so far).
_DAMAGE_TARGET_TWO_COLOR_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? {NUMBER} damage to target "
    rf"(?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) creature"
    # "The damage can't be prevented." (Combust, RULE 615.6) — an optional
    # rider on this one damage instance, folded in the way
    # `_destroy_non_creature` folds "it can't be regenerated".
    rf"(?P<unpreventable>\. (?:the|that) damage can'?t be prevented)?"
)


def _damage_target_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = [resolve_color_word(m.group("c1")), resolve_color_word(m.group("c2"))]
    if not all(colors):
        return None
    params: dict = {
        "amount": int(m.group("n")), "target_kind": "creature", "colors": colors,
    }
    if m.groupdict().get("unpreventable"):
        params["unpreventable"] = True
    return [EffectSpec("damage", params)]


def _damage_selector(m: re.Match[str]) -> list[EffectSpec]:
    selector = _SELECTOR_WORD_MAP[m.group("selector")]
    n = m.group("n").lower()
    # PAR-128: an X amount ("deals x damage to each creature and each player" — Crypt Rats).
    return [EffectSpec("damage", {"amount": "x" if n == "x" else int(n), "selector": selector})]


#: "~ deals N damage to any target and M damage to each creature" (Wildfire
#: Howl) — the second conjunct elides the repeated subject and verb.  Keep it
#: as two ordinary damage effects so the first announces its RULE 115 target
#: while the mass half remains untargeted (RULE 601.2c).
_DAMAGE_TARGET_AND_SELECTOR_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to {TARGET} "
    r"and (?P<n2>\d+) damage to (?P<selector>each creature|each player|each opponent)"
)


def _damage_target_and_selector(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [
        EffectSpec("damage", {"amount": int(m.group("n")), "target_kind": kind}),
        EffectSpec("damage", {
            "amount": int(m.group("n2")),
            "selector": _SELECTOR_WORD_MAP[m.group("selector")],
        }),
    ]


#: "~ deals 1 damage to each creature you don't control" / "…to each other creature
#: you control" / "…to each other creature without flying" (Barrage of Boulders, Cinder
#: Giant, Fire Ants — PAR-128) — the general mass form: the group is whatever the shared
#: noun-phrase grammar reads (`parse_count_phrase`, singular head pluralized), carried as
#: `DealDamageEffect.group`. After `damage_selector`, so its named selectors keep winning.
_DAMAGE_GROUP_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+|x) damage to each (?P<group>[a-z' -]+?)"
)
_SINGULAR_GROUP_HEADS = re.compile(r"\b(creature|planeswalker|permanent|artifact|land|enchantment)\b(?!s)")


#: The player a mass-damage group can be scoped to (`DealDamageEffect.group_player`).
_DAMAGE_GROUP_PLAYER_TAILS: dict[str, str] = {
    " defending player controls": "defending",
    " that player controls": "event_player",
    " target player controls": "player",
    " target opponent controls": "opponent",
}


def _damage_group(m: re.Match[str], *, that_player: str = "event_player") -> Optional[list[EffectSpec]]:
    from .count_phrase import parse_count_phrase

    text = m.group("group")
    and_players = None
    for tail, scope in ((" and each player", "each_player"), (" and each opponent", "each_opponent")):
        if text.endswith(tail):
            text, and_players = text[: -len(tail)], scope
            break
    group_player = None
    for tail, who in _DAMAGE_GROUP_PLAYER_TAILS.items():
        if text.endswith(tail):
            text, group_player = text[: -len(tail)], who
            break
    if group_player == "event_player":
        group_player = that_player
    # "…to each creature blocking it" (Battle-Scarred Goblin): RULE 509.1a, the blockers of
    # the dealer — the attacker whose `blocked_by` the engine reads.
    blocking_source = False
    for tail in (" blocking it", " blocking ~"):
        if text.endswith(tail):
            text, blocking_source = text[: -len(tail)], True
            break
    if any(word in text for word in ("target", "that player", "dealt damage", "blocking", "blocked")):
        return None
    group = parse_count_phrase(_SINGULAR_GROUP_HEADS.sub(r"\1s", text))
    if group is None or group.get("zone") != "battlefield":
        return None
    if blocking_source:
        if group.get("of") != "any":
            return None
        group = {**group, "filter": {**(group.get("filter") or {}), "blocking_source": True}}
    params: dict = {"group": group}
    if group_player is not None:
        # The group is that player's own: written `of: "you"`, evaluated for them.
        if group.get("of") != "any":
            return None
        params["group"] = {**group, "of": "you"}
        params["group_player"] = group_player
    if and_players is not None:
        if group_player is not None:
            return None  # "…creatures that player controls and each player" reads two scopes
        params["group_and_players"] = and_players
    n = m.group("n").lower()
    params["amount"] = "x" if n == "x" else int(n)
    return [EffectSpec("damage", params)]


#: "~ deals 1 damage to each nonblack creature **and an additional 1 damage to each green creature**." (Kaervek's
#: Hex) / "…to each creature with flying and 1 additional damage to each blue creature." (Tropical Storm) — two
#: mass hits by the same source in one resolution, each read by the ordinary mass-damage rows.
_DAMAGE_PLUS_ADDITIONAL_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+|x) damage to (?P<first>each [a-z' -]+?) "
    r"and (?:an additional (?P<n2>\d+|x)|(?P<n3>\d+|x) additional) damage to (?P<second>each [a-z' -]+)"
)


def _damage_plus_additional(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    n2 = m.group("n2") or m.group("n3")
    first = _match_clause_once(f"~ deals {m.group('n')} damage to {m.group('first')}")
    second = _match_clause_once(f"~ deals {n2} damage to {m.group('second')}")
    if not first or not second or any(e.type != "damage" for e in (*first, *second)):
        return None
    return [*first, *second]


def _damage_that_much_selector(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount_from_trigger_event": "that_much",
        "selector": _SELECTOR_WORD_MAP[m.group("selector")],
    })]


#: "This creature deals 2 damage to you for each Treasure you control."
#: (Black Market Tycoon) — the exact self-damage/count template; ``for each``
#: is a multiplier, not the existing additive count-selector form.
_DAMAGE_TO_YOU_PER_TREASURE_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? {NUMBER} damage to you for each treasure you control"
)


def _damage_to_you_per_treasure(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": 0,
        "selector": "controller",
        "amount_from_count_selector": "treasures_you_control",
        "amount_multiplier": int(m.group("n")),
    })]


#: "~ deals N damage to each creature without flying [and each player]."
#: (RULE 601.2c — Earthquake / Fault Line / Pyroclasm-with-a-filter, ~30
#: SOLO), widened (MEC-87) to "with/without horsemanship" (Borrowing the
#: East Wind / Rolling Earthquake — the RULE 702.31 evasion keyword's own
#: mass-damage cluster prints the identical shape one keyword over). The
#: `each_creature` mass selector narrowed by a `combat.matches_object_filter`
#: ``keyword``/``without_keyword`` — `DealDamageEffect.selector_filter`.
#: Digit or ``{X}`` amount; the optional "and each player" tail flips the
#: union selector (players are never filtered). Deliberately small/local
#: rather than reusing `_CREATURE_FILTER_KEYWORD_WORDS` (defined later in
#: this file) — same "closed list, extend as needed" style as every other
#: per-family keyword-filter vocabulary here.
_DAMAGE_EACH_CREATURE_KEYWORD_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+|x|twice x) damage to "
    rf"each creature (?P<neg>with|without) (?P<kw>flying|horsemanship)"
    # "…without flying and each planeswalker" (Magmaquake): the keyword filter narrows the creatures only.
    rf"(?:(?P<and_player> and each player)|(?P<and_pw> and each planeswalker)|(?P<opp>{_MULTI_TARGET_SCOPE_TAIL}))?"
)


def _damage_each_creature_keyword(m: re.Match[str]) -> list[EffectSpec]:
    n = m.group("n").lower()
    key = "without_keyword" if m.group("neg").lower() == "without" else "keyword"
    # PAR-128: "each creature with flying your opponents control" (Thundermaw Hellkite).
    selector = (
        "each_creature_and_player" if m.group("and_player")
        else "each_creature_and_planeswalker" if m.group("and_pw")
        else "each_creature_opponents_control" if m.group("opp") else "each_creature"
    )
    return [EffectSpec("damage", {
        "amount": count_or_x_of(n),
        "selector": selector,
        "selector_filter": {key: m.group("kw").lower()},
    })]


#: "~ deals 2 damage to each creature dealt damage this turn." (Inflame) — the `each_creature` mass selector narrowed
#: by the marked-damage filter — and "~ deals 1 damage to each creature. If it was kicked, it deals 2 damage to each
#: creature instead." (Cinderclasm), the mass sibling of `_DAMAGE_KICKED_OVERRIDE_RE`'s `amount_if_kicked`.
_DAMAGE_EACH_DAMAGED_CREATURE_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to each creature dealt damage this turn"
)
_DAMAGE_EACH_CREATURE_KICKED_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to each creature\. if (?:it|this spell) was kicked, "
    r"(?:it|~) deals (?P<n2>\d+) damage to each creature instead"
)


def _damage_each_damaged_creature(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "selector": "each_creature", "selector_filter": {"damaged_this_turn": True},
    })]


def _damage_each_creature_kicked(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "amount_if_kicked": int(m.group("n2")), "selector": "each_creature",
    })]


#: "~ deals damage to that player equal to the number of noncreature
#: spells they've cast this turn." (Magebane Lizard) — `DealDamageEffect.
#: amount_from_noncreature_spells_cast_this_turn`'s own trigger-body
#: sibling of `_lose_life_per_spell_cast_this_turn` (a different count and
#: a different effect type, so its own dedicated row rather than sharing
#: one).
_DAMAGE_PER_NONCREATURE_SPELL_CAST_THIS_TURN_RE = _c(
    r"(?:(?:~|it) )?deals? damage to that player equal to the number of noncreature spells "
    r"they'?ve cast this turn"
)


def _damage_per_noncreature_spell_cast_this_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "selector": "event_player", "amount_from_noncreature_spells_cast_this_turn": True,
    })]


#: "~ deals N damage to each opponent and each creature [and planeswalker]
#: they control." (Tectonic Hazard/End the Festivities/Delayed Blast
#: Fireball-shaped board wipes) — `DealDamageEffect`'s new
#: ``each_opponent_and_their_creatures[_and_planeswalkers]`` selector
#: (opponents-only, unlike ``each_creature_and_player``'s global scope).
_DAMAGE_EACH_OPPONENT_AND_CREATURES_RE = _c(
    rf"(?:(?:~|it) )?deals? {NUMBER} damage to each opponent and each creature"
    rf"(?P<pw> and planeswalker)? they control"
)


#: "~ deals N damage to each opponent and each creature they control. If
#: this spell was cast from exile, it deals M damage to each opponent and
#: each creature they control instead." (Delayed Blast Fireball) —
#: `DealDamageEffect.amount_if_cast_from_exile`'s own override, the same
#: shape `amount_if_kicked`/`amount_if_bargained` already use.
_DAMAGE_EACH_OPPONENT_AND_CREATURES_EXILE_RE = _c(
    rf"(?:(?:~|it) )?deals? {NUMBER} damage to each opponent and each creature they control\. "
    rf"if this spell was cast from exile, it deals (?P<n2>\d+) damage to each opponent and "
    rf"each creature they control instead"
)


def _damage_each_opponent_and_creatures_exile(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "selector": "each_opponent_and_their_creatures",
        "amount_if_cast_from_exile": int(m.group("n2")),
    })]


def _damage_each_opponent_and_creatures(m: re.Match[str]) -> list[EffectSpec]:
    selector = (
        "each_opponent_and_their_creatures_and_planeswalkers" if m.group("pw")
        else "each_opponent_and_their_creatures"
    )
    return [EffectSpec("damage", {"amount": int(m.group("n")), "selector": selector})]


#: RULE 202.2f/700.6 "it deals damage to each opponent equal to your
#: devotion to `<colour>`." (Fanatic of Mogis) — `_damage_selector`'s
#: devotion-amount sibling; ``it`` (not ``~``) is the ETB-trigger pronoun
#: this specific card prints, so `self_subject_only` gates it the same way
#: `_pump_self_subject` does.
_DAMAGE_SELECTOR_DEVOTION_RE = _c(
    rf"it deals damage to (?P<selector>each opponent|each player) equal to {DEVOTION}"
)


def _selector_devotion_builder(effect_type: str):
    """The shared "X to each opponent/player equal to your devotion to
    `<colour>`" body: `_damage_selector_devotion`/`_lose_life_selector_devotion`
    differ only in which `EffectSpec` type the resolved selector/devotion
    amount get attached to."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        selector = _SELECTOR_WORD_MAP[m.group("selector")]
        dsel = devotion_selector(m)
        if not dsel:
            return None
        return [EffectSpec(effect_type, {"amount_from_count_selector": dsel, "selector": selector})]

    return build


_damage_selector_devotion = _selector_devotion_builder("damage")


#: "Each creature deals N damage to its controller." (Rakdos Charm) — unlike
#: `_SELECTOR_WORD_MAP`'s rows, the subject here is "each creature"
#: itself, not "~"/the source, and the recipient varies per creature
#: (`effects.DealDamageEffect`'s ``"each_creature_controller"`` selector).
_DAMAGE_EACH_CREATURE_TO_CONTROLLER_RE = _c(
    rf"each creature deals {NUMBER} damage to its controller"
)


def _damage_each_creature_to_controller(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {"amount": int(m.group("n")), "selector": "each_creature_controller"})]


#: "draw that many cards" (Vilis, Broker of Blood's "whenever you lose
#: life, draw that many cards" — MEC-43) — "that many" refers back to the
#: firing event's own ``amount`` (RULE 603.1), the same `count_from_
#: trigger_event` idiom `_create_token_that_many`/the "put that many
#: counters" row already use for their own effect types.
_DRAW_THAT_MANY_RE = _c(r"draws? that many cards?")


def _draw_that_many(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {"count_from_trigger_event": "amount"})]


#: The wheel (RULE 701.8f): "Each player discards their hand, then draws N cards." (Reforge the Soul, Wheel
#: of Fate) is a `seq` of a whole-hand mass discard and a mass draw — the hand-authored Wheel of Fortune's
#: own shape. "…**may** discard their hand and draw N cards" (Raphael's Technique, Ruin Grinder, Will of the
#: Jeskai) is each player's own choice: a loop over the players whose body asks that player (`optional`'s
#: ``player="target"``, the loop item handed in as the target) and then acts on them.
_WHEEL_RE = _c(r"each player discards (?:their|all the cards in their) hand, then draws (?P<n>\d+) cards?")
_MAY_WHEEL_RE = _c(r"each player may discard their hand and draw (?P<n>\d+) cards?")


def _wheel(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("seq", {"effects": [
        {"type": "discard", "params": {"scope": "each_player", "whole_hand": True}},
        {"type": "draw", "params": {"selector": "each_player", "count": int(m.group("n"))}},
    ]})]


def _may_wheel(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("for_each", {"over": {"players": "each_player"}, "effects": [
        {"type": "optional", "params": {"player": "target", "effects": [
            {"type": "discard", "params": {"target_kind": "player", "whole_hand": True}},
            {"type": "draw", "params": {"target_kind": "player", "count": int(m.group("n"))}},
        ]}},
    ]})]


#: "draw an additional card" — a draw-step trigger's own bonus draw (Overbeing of Myth, Heightened
#: Awareness, Monastery Siege). "Additional" only says it comes on top of the step's draw; the effect
#: itself is one more ordinary draw. Fullmatched, so "… for each opponent who …" stays unclaimed.
_DRAW_ADDITIONAL_RE = _c(r"draw an additional card")


#: "Target player draws N cards, then discards M cards." (Prismari Command /
#: Whispering Madness-adjacent) — the loot shape aimed at a chosen player.
#: The trailing bare "discards" has no explicit subject, so the connector
#: split can't link it (that only fires after a *creature* target); this
#: dedicated row emits the `previous_subject` link itself.
_TARGET_PLAYER_LOOT_RE = _c(
    r"target player draws (?P<draw_n>a|an|\d+) cards?, "
    r"then discards (?P<disc_n>a|an|\d+|x) cards?"
)


def _target_player_loot(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("draw", {"count": count_of(m.group("draw_n")), "target_kind": "player"}),
        EffectSpec("discard", {
            "count": count_or_x_of(m.group("disc_n")), "previous_subject": True,
        }),
    ]


#: "You and target opponent each draw N cards." (Secret Rendezvous / Sky
#: Crier / Loran of the Third Path / Farsight Adept / Flumph) — a symmetric
#: two-player draw: one untargeted draw for the source's controller and one
#: `RULE 115` targeted draw for the chosen opponent, resolved in that order.
_YOU_AND_TARGET_OPP_DRAW_RE = _c(
    r"you and target opponent each draw (?P<n>a|an|\d+) cards?"
)


def _you_and_target_opponent_draw(m: re.Match[str]) -> list[EffectSpec]:
    n = count_of(m.group("n"))
    return [
        EffectSpec("draw", {"count": n}),
        EffectSpec("draw", {"count": n, "target_kind": "opponent"}),
    ]


def _draw(m: re.Match[str]) -> list[EffectSpec]:
    # `COUNT_X` also matches a literal "x" (RULE 107.3c's own announced
    # {X}, "draw X cards" — Contaminated Drink), resolved via the same
    # ``"x"`` sentinel `RulesEngine._substitute_x` already substitutes for
    # every other one-shot effect's magnitude field.
    params: dict = {"count": count_or_x_of(m.group("n"))}
    # "target player/opponent draws a card" (Kenrith/Oona's Grace-shaped) is
    # a real RULE 115 target, mirroring `_discard`'s own ``who`` treatment —
    # without this, "target player draws a card" would have made the
    # *source's controller* draw instead of the chosen player. "each
    # player/opponent draws" is the untargeted mass form (RULE 601.2c).
    who = (m.groupdict().get("who") or "").strip()
    if who in ("target player", "target opponent"):
        params["target_kind"] = "player"
    elif who in ("each player", "each opponent"):
        params["selector"] = who.replace(" ", "_")
    return [EffectSpec("draw", params)]


#: RULE 118.3's "You may pay `<cost>`. If you do, draw a card." — the single
#: most common tail on the `pay_cost_then` idiom (~21 real cards, mostly
#: Spellbombs and card-draw payoffs). Matched as *one whole clause*,
#: "you may" included, rather than through the generic "you may `<effect>`"
#: peeling `_peel_optional` does elsewhere: that peeling's own
#: `AbilitySpec.optional` flag means "you may decline this trigger's whole
#: effect", a different, *outer* optionality than RULE 118.3's "the
#: trigger always happens; paying the embedded cost is what's optional" —
#: setting both would double-gate the same choice. `pay_cost_then`
#: (`game/effects/core.py`'s `PayCostThenEffect`) already existed as an engine
#: primitive (Mana Vault/Wandering Archaic, hand-authored); this is its
#: first oracle-text recognizer.
_PAY_COST_THEN_DRAW_RE = _c(
    r"you may pay (?P<cost>\{[a-z0-9]+\})\. if you do, draw a card"
)


def _pay_cost_then_draw(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pay_cost_then", {
        "cost": m.group("cost"),
        "effects": [{"type": "draw", "params": {"count": 1}}],
    })]


def _draw_next_upkeep(m: re.Match[str]) -> list[EffectSpec]:
    """RULE 603.7 delayed trigger: "draw a card at the beginning of the next
    turn's upkeep" (Clairvoyance/Balduvian Rage/Carrier Pigeons-shaped, ~46
    real cards). Arms via `create_delayed_trigger` — the same primitive
    Batch 22 built for Mana Drain — with ``scope="any"``: no "your"
    qualifier means the very next upkeep regardless of whose turn (RULE
    603.7a), unlike Mana Drain's own controller-scoped "your next main
    phase". A pronoun-scoped variant ("its controller may draw...", Arcane
    Denial's own first sentence) is deliberately unclaimed here — a
    different, indirect-referent grammar shape, same family of gap as
    Run Away Together's (`docs/implementation-state/BACKLOG.md`)."""
    return [EffectSpec("create_delayed_trigger", {
        "step": "upkeep",
        "scope": "any",
        "effects": [{"type": "draw", "params": {"count": count_of(m.group("n"))}}],
    })]


#: RULE 601.3b's "impulsive draw" shape (PAR-13, Dungeon of the Mad Mage's
#: "Runestone Caverns" — "Exile the top two cards of your library. You may
#: play them."; also Bonehoard Dracosaur/Painter's Studio's own trailing
#: duration variants) — `ImpulsiveDrawEffect` already existed as a
#: hand-authored-only primitive (Light Up the Stage); this is the first
#: oracle-text recognizer to reach it. A bare, undurationed "you may play
#: them" (the dungeon room's own phrasing, with no explicit window at all)
#: defaults to the effect's own "until the end of your next turn" — the
#: more common real-card convention for an unqualified "you may play them".
#: MEC-12 fourth pass widened this: the *leading*-duration word order
#: ("Until the end of your next turn, you may play those cards." — Light Up
#: the Stage/Reckless Impulse/Commune with Lava's own real printed text,
#: not the trailing form this row was first written against) is at least as
#: common cache-wide as the trailing one, "that card"/"those cards" are as
#: real as the pronoun "them"/"it", the singular "the top card" (no number)
#: needs its own alternative since ``\d+`` can't match zero digits, and
#: ``count_or_x_of`` covers "the top x cards" (Commune with Lava) via the
#: same ``"x"``-sentinel/`RulesEngine._substitute_x` idiom every other
#: X-scaled one-shot effect already uses.
#: "…until your next end step." (Opera Love Song) accepted as a third
#: duration word alongside "this turn"/"until the end of your next turn" —
#: **documented simplification**: `ImpulsiveDrawEffect`'s window is turn-
#: scoped (`_grant_temp_play_permission`'s ``same_turn_only`` sweeps at
#: *this* turn's own cleanup, the finest granularity it has), so this maps
#: to ``same_turn_only=True`` rather than a genuine step-scoped expiry.
#: Exact when cast during the caster's own turn (their next end step
#: *is* later this same turn); an instant-speed cast on an opponent's turn
#: would close the window at that turn's cleanup instead of carrying it
#: into the caster's own next end step — narrower than RAW, not wider.
#: PAR-137 widened the row: the window word may also be "until end of turn", and a *choice* of one
#: of the exiled cards is accepted — "exile the top 2 cards of your library[,] [then] choose 1 of
#: them. You may play that card this turn" and "… you may play 1 of those cards this turn" — which
#: keeps the play permission on the pick alone (`ImpulsiveDrawEffect.choose_one`).
_EXILE_TOP_WINDOW = r"this turn|until (?:the )?end of turn|until the end of your next turn|until your next end step"
_EXILE_TOP_PLAY_RE = _c(
    r"exile the top (?:(?P<n>\d+|x) cards?|card) of your library(?:\.|, then) "
    r"(?P<choose>choose 1(?: of (?:them|those cards))?\. )?"
    rf"(?:(?P<dur_pre>{_EXILE_TOP_WINDOW}), )?"
    r"you may play (?P<what>them|it|that card|those cards|the exiled cards|cards exiled this way|1 of those cards)"
    rf"(?: (?P<dur_post>{_EXILE_TOP_WINDOW}))?"
)


def _exile_top_play(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dur = (m.groupdict().get("dur_pre") or m.groupdict().get("dur_post") or "").strip()
    same_turn_only = dur in ("this turn", "until end of turn", "until the end of turn", "until your next end step")
    n = m.group("n")
    what = m.group("what")
    choose_one = bool(m.group("choose")) or what == "1 of those cards"
    count = count_or_x_of(n) if n else 1
    # "that card"/"it" names *the* card — one exiled card, or the pick; "them"/"those cards" every one.
    singular = what in ("it", "that card")
    if singular and not choose_one and count != 1:
        return None
    if m.group("choose") and what != "that card":
        return None
    params: dict = {"count": count, "same_turn_only": same_turn_only}
    if choose_one:
        params["choose_one"] = True
    return [EffectSpec("impulsive_draw", params)]


#: "Draw N cards and reveal them. You may cast one of them without paying
#: its mana cost." (PAR-13, Dungeon of the Mad Mage's own "Mad Wizard's
#: Lair") — `DrawRevealCastOneFreeEffect`'s only oracle-text route; reveal
#: itself carries no mechanical weight to model (RULE 701.28).
_DRAW_REVEAL_CAST_FREE_RE = _c(
    r"draw (?P<n>\d+) cards? and reveal (?:them|it)\. you may cast (?:\d+|a) of "
    r"them without paying its mana cost"
)


def _draw_reveal_cast_free(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw_reveal_cast_one_free", {"count": int(m.group("n"))})]


#: RULE 601.2f-adjacent "Expertise" cycle template (MEC-20) — "You may cast
#: a spell with mana value N or less from your hand without paying its mana
#: cost." (Kari Zev's/Sram's/Yahenni's/Baral's/Rishkar's Expertise), its
#: ``{X}``-scaled sibling ("…mana value x or less…", Electrodominance —
#: ``COUNT_X``/``count_or_x_of``, resolved against the spell's own announced
#: {X} by `RulesEngine._substitute_x`'s existing ``criteria`` walk, no new
#: wiring needed), and the trailing "where x is the number of attacking
#: creatures" tail (Epistolary Librarian's own triggered-ability body, which
#: has no cast {X} of its own to substitute — a board-read count instead,
#: `continuous.count_selector`'s existing ``"attacking_creatures"`` entry).
#: `FreeCastFromHandEffect` (`game/effects/core.py`) is a resolve-time *choice*
#: among the controller's own hand, not a target — none of these print
#: "target". The leading "you may " is optional here (not required) since
#: `segmenter._peel_optional` already strips it before `parse_effect_body`
#: ever reaches a handler, for both the bare spell-effect and the
#: triggered-ability wrapper paths — MEC-18's own "the generic 'you may '
#: stripper eats the clause first" lesson, guarded against directly rather
#: than by exempting `_peel_optional` (nothing else about this clause is
#: sensitive to the optional marker: `spec.optional` is read only by the
#: ``triggered`` binder branch, never ``spell_effect``, and this effect's
#: own `_request_choose_objects(optional=True)` already models the "may").
_FREE_CAST_FROM_HAND_RE = _c(
    # ENG-33 (Great Intelligence's Plan) / ENG-32 (Waterbend "cast a
    # noncreature spell without paying"): the "with mana value N or less"
    # cap and the "noncreature" qualifier are both optional — an uncapped
    # `free_cast_from_hand` offers every nonland hand card.
    # "with mana value N or less" and "from your hand" appear in either
    # order — "…spell with mana value N or less from your hand…" (the
    # Expertise cycle) and "…spell from your hand with mana value N or
    # less…" (Marvo, Deep Operative). Two positions for the cap, read back
    # by `_free_cast_from_hand` as ``n`` or ``n_after``.
    rf"(?:you may )?cast an? (?P<noncreature>noncreature )?spell"
    rf"(?: with mana value {COUNT_X} or less)? from your hand"
    rf"(?: with mana value (?P<n_after>a|an|x|\d+) or less)? "
    rf"without paying its mana cost(?P<selector>, where x is the number of attacking creatures)?"
)


def _free_cast_from_hand(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {}
    if m.groupdict().get("noncreature"):
        params["noncreature_only"] = True
    cap = m.groupdict().get("n") or m.groupdict().get("n_after")
    if m.group("selector"):
        params["max_mana_value_selector"] = "attacking_creatures"
    elif cap is not None:
        params["max_mana_value"] = count_or_x_of(cap)
    return [EffectSpec("free_cast_from_hand", params)]


#: ENG-33: "you may put a `<type>` card from your hand onto the battlefield"
#: (Dr. Eggman, Sonic's Nemesis — a villainous-choice option body).
#: `PutFromHandOntoBattlefieldEffect` already exists (Tooth and Nail); this
#: reaches it from a resolving effect. Every named type/subtype must be a
#: recognized word (fail-closed) — a bare `card_query` substring test would
#: silently match nothing on a typo.
_PUT_FROM_HAND_TYPE_WORDS: frozenset[str] = frozenset(PERMANENT_TYPE_WORDS) | {
    "construct", "robot", "vehicle", "equipment", "aura", "clue",
    "food", "treasure",
}
_PUT_FROM_HAND_RE = _c(
    r"(?:you may )?put an? (?P<types>[a-z, ]+?) card"
    # RULE 601.2c-style card filter between "card" and "from your hand":
    # "with lesser power" (Shadowfax) — vs this effect's source; "with mana
    # value N or less" (fixed) / "with mana value x or less" (dynamic, needs
    # the trailing ", where X is …" clause below to resolve X).
    r"(?P<filt> with lesser power| with mana value (?P<mv>\d+) or less| with mana value x or less)?"
    r" from your hand(?P<or_gy> or graveyard)? onto the battlefield"
    # RULE 508.4 "…tapped and attacking" (Preeminent Captain, Kaalia of the
    # Vast) → `PutFromHandOntoBattlefieldEffect.attacking`; or the plain
    # "…tapped" entry (Dread Tiller, Arboreal Grazer, Cultivator Colossus).
    # Longer alternative first so "tapped and attacking" isn't mis-split.
    r"(?:(?P<tapped_attacking> tapped and attacking)|(?P<tapped_plain> tapped))?"
    # The trailing "that player"/"that opponent" (Kaalia, The Vast Scrier)
    # names the defender the source is already attacking — `put_onto_
    # battlefield_attacking` derives that from the other attackers, so the
    # phrase is consumed, not re-modeled.
    r"(?P<atk_defender> that (?:player|opponent))?"
    r"(?P<xdef>, where x is the number of attacking creatures you control)?"
    # The Vast Scrier's two trailing sentences: (1) an explicit instruction
    # that the placed creature's own "whenever ~ attacks" triggers fire —
    # unlike ordinary RULE 508.4 entry, this is *not* a no-op; (2) "if you don't put a card … this way,
    # <body>." → `miss_effect_specs` (via `_request_search`'s
    # ``then_specs_if_none``).
    r"(?:\. (?P<trigger_attacks>if it has any \"whenever ~ attacks\" triggers,? those trigger))?"
    r"(?:\. if you don'?t put a card onto the battlefield this way, (?P<elsebody>.+?))?"
)

#: The main card types a "put a … card from your hand" clause can name; a
#: two-word segment ending in one of these ("dragon creature") makes the
#: leading word a *subtype* filter.
_PUT_FROM_HAND_MAIN_TYPES: frozenset[str] = frozenset(
    {"creature", "artifact", "enchantment", "land", "planeswalker", "permanent"}
)


def _put_from_hand(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    segments = [
        s.strip() for s in re.split(r",\s*or\s+|,\s*|\s+or\s+", m.group("types"))
        if s.strip()
    ]
    if not segments:
        return None
    last = segments[-1].split()
    if (
        len(last) == 2
        and last[1] in _PUT_FROM_HAND_MAIN_TYPES
        and all(len(s.split()) == 1 for s in segments[:-1])
    ):
        # "soldier creature card" / "angel, demon, or dragon creature card"
        # — the leading words are creature subtypes (an OR), the trailing
        # main type is implied by them. `card_query` treats a ``type`` list
        # as an OR substring match, which is exactly a subtype filter here.
        qualifiers = segments[:-1] + [last[0]]
        colours = [resolve_color_word(w) for w in qualifiers]
        if all(colours):
            # "blue or red creature card" (Mindwrack Liege) — a colour
            # filter, not a subtype: nothing's type line contains "blue".
            criteria: dict = {"color": colours if len(colours) > 1 else colours[0]}
        elif any(
            w in ("multicolored", "monocolored", "colorless", "historic",
                  "nonlegendary", "nontoken", "nonbasic")
            for w in qualifiers
        ):
            return None  # a derived quality with no clean `card_query` key — fail closed
        else:
            criteria = {"type": qualifiers if len(qualifiers) > 1 else qualifiers[0]}
    elif all(s in _PUT_FROM_HAND_TYPE_WORDS for s in segments):
        criteria = {"type": segments if len(segments) > 1 else segments[0]}
    else:
        return None
    filt = (m.groupdict().get("filt") or "").strip()
    if filt == "with lesser power":
        params_extra: dict = {"power_less_than_source": True}
    elif m.groupdict().get("mv"):
        criteria = {**criteria, "max_mana_value": int(m.group("mv"))}
        params_extra = {}
    elif filt == "with mana value x or less":
        if not m.groupdict().get("xdef"):
            return None  # unresolvable X → fail closed
        params_extra = {"max_mana_value_selector": "attacking_creatures_you_control"}
    else:
        params_extra = {}
    params: dict = {"criteria": criteria, "count": 1, **params_extra}
    if m.groupdict().get("tapped_attacking"):
        params["tapped"] = True
        params["attacking"] = True
    elif m.groupdict().get("tapped_plain"):
        params["tapped"] = True
    if m.groupdict().get("or_gy"):
        params["zones"] = ["hand", "graveyard"]
    if m.groupdict().get("trigger_attacks"):
        params["trigger_attacks"] = True
    elsebody = (m.groupdict().get("elsebody") or "").strip().rstrip(".")
    if elsebody:
        from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

        else_specs = parse_effect_body(elsebody)
        if else_specs is None:
            return None  # else-branch didn't parse — fail closed
        params["miss_effect_specs"] = [s.to_dict() for s in else_specs]
    return [EffectSpec("put_from_hand_onto_battlefield", params)]


#: MEC-73: Sneak Attack's hand cheat with the haste/delayed-sacrifice tail.
#: The optional subtype is deliberately limited to one word: it is a creature
#: subtype in the printed ``<Subtype> creature card`` grammar, not an
#: arbitrary card-query string. The whole sequence must be one effect because
#: the chosen hand card is only known after the interactive choice resolves.
_CHEAT_CREATURE_FROM_HAND_RE = _c(
    r"(?:you may )?put an? (?:(?P<subtype>[a-z]+) )?creature card from your hand onto the battlefield\. "
    r"that creature gains haste until end of turn\. "
    r"sacrifice (?:it|that creature|the creature) at the beginning of the next end step"
)


def _cheat_creature_from_hand(m: re.Match[str]) -> list[EffectSpec]:
    params: dict[str, object] = {}
    if m.group("subtype"):
        params["subtypes"] = [m.group("subtype").capitalize()]
    return [EffectSpec("cheat_creature_from_hand", params)]


#: RULE 119/701.8's "Target opponent/player reveals their hand. You choose
#: a `<filter>` card from it[ with mana value N or less]. That player
#: discards that card[. You lose N life]." (Duress/Thoughtseize/Coercion/
#: Distress/Inquisition of Kozilek-shaped — one of the most repeated hand-
#: disruption templates in the cache). Deliberately just the five real
#: filter phrasings found so far (bare/nonland/noncreature+nonland/
#: creature-or-planeswalker/artifact-or-creature) rather than a fully
#: general card-type grammar, plus the two real trailing riders (MEC-43
#: round 2: a mana-value cap on the chosen card — Inquisition of Kozilek —
#: and the caster's own life loss — Thoughtseize) — "or a card from their
#: graveyard" and any other rider stays unclaimed rather than guessed at.
_HAND_DISRUPTION_FILTERS: dict[str, dict] = {
    "a card": {},
    "a nonland card": {"exclude_land": True},
    "a noncreature, nonland card": {"exclude_land": True, "exclude_creature": True},
    "a creature or planeswalker card": {"card_types": ["creature", "planeswalker"]},
    "an artifact or creature card": {"card_types": ["artifact", "creature"]},
}
_HAND_DISRUPTION_RE = _c(
    rf"(?P<target>target opponent|target player) reveals their hand(?:\. |, )"
    rf"you choose (?P<filter>{'|'.join(re.escape(k) for k in _HAND_DISRUPTION_FILTERS)}) "
    rf"from it(?: with mana value (?P<mv>\d+) or less)?"
    # PAR-128: the comma spelling ("…, you choose … from it, then that player
    # discards that card", Devour Intellect / River's Grasp) reads the same.
    r"(?:\. |, then )that player discards that card(?:\. you lose (?P<life>\d+) life)?"
)


def _hand_disruption_discard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if resolve_target_kind(m.group("target")) != "player":
        return None
    # PAR-128: "target opponent" is an opponent, not any player.
    kind = "opponent" if m.group("target") == "target opponent" else "player"
    params: dict = {"target_kind": kind, **_HAND_DISRUPTION_FILTERS[m.group("filter")]}
    if m.group("mv"):
        params["max_mana_value"] = int(m.group("mv"))
    specs = [EffectSpec("reveal_hand_choose_discard", params)]
    if m.group("life"):
        specs.append(EffectSpec("lose_life", {"amount": int(m.group("life"))}))
    return specs


#: "Target player reveals their hand. You choose a nonland card from it. That player puts that card into their library
#: third from the top." (Lost Hours) and "Look at target player's hand and choose `<N>` cards from it. `<tail>`" (Mind
#: Warp / Extortion / Abandon Hope discard them, Agonizing / Painful Memories put them on top of the library): the same
#: `reveal_hand_choose_discard` effect with a pick count (`count`, `up_to`) and a `destination`. Looking at a hand is
#: the same zero-effect visibility step as revealing it.
_HAND_PICK_FILTERS: dict[str, dict] = {"a nonland card": _HAND_DISRUPTION_FILTERS["a nonland card"], "a card": {}}
_HAND_PICK_TAILS: dict[str, str] = {
    "that player discards (?:that card|those cards)": "discard",
    "put (?:that card|them) on top of that player's library(?: in any order)?": "library_top",
    "that player puts that card into their library third from the top": "library_third",
}
_HAND_PICK_RE = _c(
    r"(?:(?P<reveal>target opponent|target player) reveals their hand\. you choose (?P<rfilter>a nonland card) from it"
    r"|look at (?P<look>target opponent|target player)'s hand and choose "
    r"(?:(?P<upto>up to )?(?P<n>\d+|x) cards?|(?P<a>a card)) from it)\. "
    rf"(?P<tail>{'|'.join(_HAND_PICK_TAILS)})"
)


def _hand_pick(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    target = m.group("reveal") or m.group("look")
    if resolve_target_kind(target) != "player":
        return None
    destination = next(dest for pattern, dest in _HAND_PICK_TAILS.items() if re.fullmatch(pattern, m.group("tail")))
    if m.group("reveal") and destination != "library_third":
        return None  # the plain reveal-and-discard form is `hand_disruption_discard`'s
    params: dict = {"target_kind": "opponent" if target == "target opponent" else "player"}
    if m.group("rfilter"):
        params.update(_HAND_PICK_FILTERS[m.group("rfilter")])
    if m.group("n"):
        params["count"] = "x" if m.group("n") == "x" else int(m.group("n"))
    if m.group("upto"):
        params["up_to"] = True
    if destination != "discard":
        params["destination"] = destination
    return [EffectSpec("reveal_hand_choose_discard", params)]


#: RULE 701.20's "defending player reveals the top card of their library.
#: If it's a land card, that player puts it into their hand." (Goblin
#: Guide-shaped) — a triggered-ability body (the "whenever ~ attacks,"
#: prefix that opens it is recognized separately, by the segmenter's own
#: trigger-condition grammar). Deliberately just the "defending player"
#: subject and the three real card-type words found so far.
_REVEAL_TOP_CONDITIONAL_RE = _c(
    r"defending player reveals the top card of their library\. "
    r"if it'?s an? (?P<type>land|creature|artifact) card, that player puts it into their hand"
)


def _reveal_top_conditional(m: re.Match[str]) -> list[EffectSpec]:
    # ENG-37 B5: a `seq` of `reveal_top` (stash the top card as the
    # `revealed` referent) then an `if_else` on its card type — the engine-
    # side `reveal_top_conditional_to_hand` fusion is retired.
    return [EffectSpec("seq", {"effects": [
        {"type": "reveal_top", "params": {"whose": "defending_player"}},
        {"type": "if_else", "params": {
            "condition": {
                "kind": "is_card_type", "of": "revealed",
                "card_type": m.group("type"),
            },
            "then": [{
                "type": "put_revealed_card",
                "params": {"destination": "hand", "whose": "defending_player"},
            }],
            "else": [],
        }},
    ]})]


def _split_token_mid_words(mid: str) -> tuple[list[str], list[str], bool]:
    """A created token's "<mid>" description words (everything between its
    P/T and "creature token") → ``(colors, subtypes, is_artifact)``.

    "artifact" is a `_TOKEN_NOISE_WORDS` entry — recognized, not just
    dropped: "colorless Construct **artifact** creature token" (Construct/
    Thopter/Servo-shaped) needs `CreateTokenEffect.is_artifact` set, or the
    synthesized token silently comes out as a bare Creature missing the
    Artifact card type entirely (RULE 704.5f's zero-toughness check, a
    "sacrifice an artifact" cost, and any artifact-count anthem all read
    `Card.is_artifact`). The one shared word-splitting loop for all three
    "<mid> creature token[s]" handler shapes (`_xx_token_mid_params`,
    `_inline_create_token_params`, `_create_named_legendary_token`) — kept
    as one function specifically so a future noise word only needs adding
    here once, not independently in three near-identical copies.
    """
    colors: list[str] = []
    subtypes: list[str] = []
    is_artifact = False
    for word in mid.split():
        if word in _COLOR_WORDS:
            colors.append(_COLOR_WORDS[word])
        elif word == "artifact":
            is_artifact = True
        elif word in _TOKEN_NOISE_WORDS:
            continue
        else:
            subtypes.append(word.capitalize())
    return colors, subtypes, is_artifact


def _xx_token_mid_params(mid: str, kw: Optional[str]) -> Optional[dict]:
    """The shared ``colors``/``subtypes``/``keywords`` params for an X/X
    token clause's "<mid> token[ with <kw>]" tail — the same word-splitting
    `_inline_create_token_params` uses for a literal-stats token, factored
    out since neither of the two X/X handlers below share that function's
    other (count/tapped/legendary) groups."""
    colors, subtypes, is_artifact = _split_token_mid_words(mid)
    keywords: list[str] = []
    if kw:
        parsed = _token_keywords(kw)
        if parsed is None:
            return None
        keywords = parsed
    params: dict = {"colors": colors, "subtypes": subtypes, "keywords": keywords}
    if is_artifact:
        params["is_artifact"] = True
    if subtypes:
        params["token_name"] = " ".join(subtypes)
    return params


#: "create an X/X blue Shark creature token with flying, where X is that
#: spell's mana value." (Shark Typhoon's spell-cast trigger) — an X/X token
#: sized off the firing `SPELL_CAST` event's own ``mana_value`` field
#: (`CreateTokenEffect.pt_from_trigger_event`), read fresh at resolve time.
_MANA_VALUE_XX_TOKEN_RE = _c(
    r"create an? x/x (?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z]+(?:, [a-z]+)*(?: and [a-z]+)?))?, "
    r"where x is that spell'?s mana value"
)


def _mana_value_xx_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    return [EffectSpec("create_token", {**params, "pt_from_trigger_event": "mana_value"})]


#: The RULE 702.28c Cycling-cost sibling — "create an X/X blue Shark
#: creature token with flying." (Shark Typhoon's own "When you cycle this
#: card" bonus) — X here is the Cycling cost's own paid {X}
#: (`GameObject.cycling_x_paid`), substituted through the same ``"x"``
#: sentinel/`_substitute_x` idiom (`"cycling_x"`) every other X-scaled
#: effect uses, just a different source field.
_CYCLING_XX_TOKEN_RE = _c(
    r"create an? x/x (?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z]+(?:, [a-z]+)*(?: and [a-z]+)?))?"
)


def _cycling_xx_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    return [EffectSpec("create_token", {**params, "power": "cycling_x", "toughness": "cycling_x"})]


#: RULE 400.7's "blink" family — "exile target non-<subtype> creature you
#: control, then return that card/it to the battlefield under
#: your/its owner's control" (Restoration Angel/Icewind Stalwart-shaped).
#: The pre-existing `BlinkEffect`/`RulesEngine.blink` primitive had no
#: oracle-text recognizer at all (Ephemerate/Momentary Blink are both
#: hand-authored in `card_catalogue`) — this is that recognizer, for
#: the specific "non-<subtype> creature you control" + explicit controller
#: shape those simpler cards don't need. ``subtype`` is a single word (every
#: real card in this shape names exactly one creature type); a compound
#: exclusion or any other target phrase stays unclaimed.
_BLINK_NON_SUBTYPE_RE = _c(
    r"exile target non-(?P<subtype>[a-z]+) creature you control, "
    r"then return (?:that card|it) to the battlefield under (?P<who>your|its owner'?s) control"
)


def _blink_non_subtype(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "target_kind": "creature_you_control",
        "creature_filter": {"without_subtype": m.group("subtype").capitalize()},
    }
    if m.group("who") == "your":
        params["under_your_control"] = True
    return [EffectSpec("blink", params)]


#: The plainer sibling of `_BLINK_NON_SUBTYPE_RE`, with no subtype
#: exclusion — "exile [up to N] [another] target creature/[nonland]
#: permanent you control, then return that card/it to the battlefield
#: under your/its owner's control" (Felidar Guardian/Emiel the Blessed/
#: Displacer Kitten-shaped). "another" needs no special handling: every
#: ``*_you_control`` `legal_targets` branch already excludes the source
#: object regardless (`o is not source`), so a plain and an "another"-
#: qualified target kind resolve identically. "up to N" threads through
#: to `BlinkEffect`'s own ``optional``/``count_max`` (MEC-12) rather than
#: the yes/no "you may" a *mandatory*-single-target blink relies on
#: (stripped upstream, same as `_blink_non_subtype` needs no "you may" in
#: its own pattern either). "other" (MEC-79's The Mind Stone — "up to one
#: **other** target nonland permanent you control") is the same free case as
#: "another": the source-excluding ``*_you_control`` `legal_targets` branch
#: makes plain / "another" / "other" resolve identically.
#: Plural targets (Displace / Illusionist's Stratagem "exile up to 2 target creatures you control, then return those
#: cards …", Brago "any number of target nonland permanents", Gandalf, Shadow's Foe "up to 3 target lands … tapped")
#: ride the same row: the count is the target count, "those cards"/"them" the referent, "under their owner's
#: control" the owner form.
_BLINK_PLAIN_RE = _c(
    r"exile (?:(?P<any_number>any number of )|up to (?P<up_to>one|[0-9]+) |(?P<exactly>[2-9]) )?"
    r"(?:(?:an)?other )?target "
    # "…target **tapped** creature you control…" (Far Traveler's granted
    # end-step blink) — a state filter on the target, `BlinkEffect.
    # creature_filter` (the same param `_blink_non_subtype` uses for its
    # subtype exclusion).
    r"(?P<tapped>tapped )?(?P<kind>nonland permanents?|permanents?|creatures?|lands?) you control, "
    r"then return (?:that card|it|those cards|them) to the battlefield(?P<enters_tapped> tapped)? "
    r"under (?P<who>your|its owner'?s|their owners?'?s?) control"
)
#: How many a plural blink target phrase may name when it says "any number" (the engine's own multi-target cap).
_BLINK_ANY_NUMBER_CAP = 10


def _blink_plain(m: re.Match[str]) -> list[EffectSpec]:
    kind_word = m.group("kind").rstrip("s") if m.group("kind") != "lands" else "land"
    target_kind = {
        "creature": "creature_you_control",
        "permanent": "permanent_you_control",
        "nonland permanent": "nonland_permanent_you_control",
        "land": "land_you_control",
    }[kind_word]
    params: dict = {"target_kind": target_kind}
    if m.group("who") == "your":
        params["under_your_control"] = True
    if m.group("tapped"):
        params["creature_filter"] = {"tapped": True}
    if m.group("enters_tapped"):
        params["tapped"] = True
    up_to = m.group("up_to")
    if m.group("any_number"):
        params["optional"] = True
        params["target_count_max"] = _BLINK_ANY_NUMBER_CAP
    elif up_to:
        params["optional"] = True
        params["target_count_max"] = 1 if up_to == "one" else int(up_to)
    elif m.group("exactly"):
        params["target_count"] = int(m.group("exactly"))
    return [EffectSpec("blink", params)]


def _discard(m: re.Match[str]) -> list[EffectSpec]:
    # "you discard"/bare "discard" is the controller (untargeted); "target
    # player/opponent discards" is a real RULE 115 target; "each player/
    # opponent discards" is the untargeted mass form (RULE 601.2c). Mirrors
    # `_gain_life`'s ``who``-group treatment — and without the target_kind
    # half, "target player discards a card" would have made the *source's
    # controller* discard instead of the chosen player.
    params: dict = {"count": count_of(m.group("n"))}
    who = (m.groupdict().get("who") or "").strip()
    if who == "target player":
        params["target_kind"] = "player"
    elif who == "target opponent":
        # PAR-128: an opponent, not any player — Honden of Night's Reach must
        # not be able to aim the discard at its own controller.
        params["target_kind"] = "opponent"
    elif who == "each player":
        params["scope"] = "each_player"
    elif who == "each opponent":
        params["scope"] = "each_opponent"
    if m.groupdict().get("at_random"):
        params["random"] = True
    return [EffectSpec("discard", params)]


#: "Discard N cards unless you discard a `<quality>` card." (Thirst for Knowledge, Compulsive Research, Alpharael,
#: Arm-Mounted Anchor, …) — `DiscardEffect.unless_discard`: the discarder may give up one matching card instead of N.
#: "that player" is the player an earlier clause chose (``previous_subject``). The quality is "nonland", a card type
#: or a creature/permanent subtype the shared count grammar knows (fail-closed on anything else).
_DISCARD_UNLESS_RE = _c(
    r"(?:then )?(?:(?P<who>you|that player|target player|target opponent|each opponent|each player) )?"
    rf"discards? {COUNT} cards? unless (?:you|they) discards? (?:a|an) (?P<quality>[a-z]+) card"
)
_DISCARD_UNLESS_CARD_TYPES = frozenset({"artifact", "creature", "land", "enchantment", "instant", "sorcery", "planeswalker"})


def _discard_unless(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .subgrammars import subtype_count_selector

    quality = m.group("quality").lower()
    if quality == "nonland":
        unless: dict = {"nonland": True}
    elif quality in _DISCARD_UNLESS_CARD_TYPES:
        unless = {"card_type": quality}
    else:
        selector = subtype_count_selector(f"{quality}s")
        subtype = ((selector or {}).get("filter") or {}).get("subtype")
        if not subtype:
            return None
        unless = {"subtype": subtype}
    who = (m.group("who") or "").strip()
    params: dict = {"count": count_of(m.group("n")), "unless_discard": unless}
    if who == "that player":
        params["previous_subject"] = True
    elif who == "target player":
        params["target_kind"] = "player"
    elif who == "target opponent":
        params["target_kind"] = "opponent"
    elif who == "each player":
        params["scope"] = "each_player"
    elif who == "each opponent":
        params["scope"] = "each_opponent"
    return [EffectSpec("discard", params)]


def _that_many_player_discards(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discard", {"count": 0, "previous_subject": True,
                                    "count_from_trigger_event": "amount"})]


#: RULE 601.2c mass edict — "each player sacrifices a nontoken creature of
#: their choice" (Accursed Marauder-shaped) / "each player sacrifices N
#: creatures of their choice" (Liliana, Dreadhorde General's own -4) — each
#: player independently choosing their own victim(s) via `effects.
#: SacrificeEffect`'s ``selector="each_player"``/``"each_opponent"``, not a
#: random/rules-picked edict (RulesEngine.sacrifice is a real interactive
#: choice per player).
_SACRIFICE_EDICT_SELECTOR_WORDS: dict[str, str] = {
    "each player": "each_player", "each opponent": "each_opponent",
    # PAR-128: RULE 109.5 "each other player" — every player but the controller,
    # the same reading `_SELECTOR_WORD_MAP` gives it (no team play, RULE 809+).
    "each other player": "each_opponent",
}
_SACRIFICE_EDICT_WHAT_WORDS: dict[str, str] = {
    "creature": "creature", "artifact": "artifact", "land": "land", "permanent": "permanent",
}
_SACRIFICE_EDICT_RE = _c(
    rf"(?P<selector>{'|'.join(_SACRIFICE_EDICT_SELECTOR_WORDS)}) sacrifices? "
    rf"(?P<count>a|an|\d+) (?P<nontoken>nontoken )?"
    rf"(?P<what>{'|'.join(_SACRIFICE_EDICT_WHAT_WORDS)})s? of their choice"
)


def _sacrifice_edict(m: re.Match[str]) -> list[EffectSpec]:
    selector = _SACRIFICE_EDICT_SELECTOR_WORDS[m.group("selector")]
    what = _SACRIFICE_EDICT_WHAT_WORDS[m.group("what")]
    if m.group("nontoken") and what == "creature":
        what = "nontoken_creature"
    count_word = m.group("count")
    count = 1 if count_word in ("a", "an") else int(count_word)
    return [EffectSpec("sacrifice", {"selector": selector, "what": what, "count": count})]


#: ENG-33: "target player/opponent sacrifices [N] [nontoken] `<what>` [of
#: their choice]" (Diabolic Edict / Chainer's Edict / Dead Drop-shaped, ~21
#: SOLO cards, and the recurring villainous-choice / vote *other* option).
#: A real RULE 115 player target (`SacrificeEffect.target_kind="player"` →
#: reads `targets[0]`), the single-target sibling of `_SACRIFICE_EDICT_RE`'s
#: `each_player`/`each_opponent` mass form.
_TARGET_PLAYER_EDICT_RE = _c(
    rf"target (?P<who>player|opponent) sacrifices? "
    rf"(?P<count>a|an|\d+) (?P<nontoken>nontoken )?"
    rf"(?P<what>{'|'.join(_SACRIFICE_EDICT_WHAT_WORDS)})s?(?: of their choice)?"
)


def _target_player_edict(m: re.Match[str]) -> list[EffectSpec]:
    what = _SACRIFICE_EDICT_WHAT_WORDS[m.group("what")]
    if m.group("nontoken") and what == "creature":
        what = "nontoken_creature"
    count_word = m.group("count")
    count = 1 if count_word in ("a", "an") else int(count_word)
    return [EffectSpec("sacrifice", {"target_kind": "player", "what": what, "count": count})]


#: "each opponent / target opponent sacrifices a creature with the greatest power among creatures they
#: control" (Crackling Doom, Gix's Command, Szat's Will, Professor Onyx's −3 — the hand-authored original) —
#: `SacrificeEffect.greatest_power` narrows the pick to the tied leaders of that player's own board.
#: …and the same edict by **mana value**, over creatures or creatures and planeswalkers, as a sacrifice or an exile
#: (Blot Out / End of the Hunt "exiles", Flare of Malice / Soul Shatter / Break Under Pressure "sacrifices"). A tie is
#: the chosen player's pick among the tied leaders (`SacrificeEffect.greatest`).
_SACRIFICE_GREATEST_POWER_RE = _c(
    r"(?P<who>each opponent|target opponent|target player) (?P<verb>sacrifices|exiles) a "
    r"(?P<what>creature|creature or planeswalker) "
    r"(?:with the greatest (?P<stat>power|mana value) among (?P<pool>creatures|creatures and planeswalkers) "
    r"(?:they|that player) controls?"
    r"|they control with the greatest (?P<stat2>power|mana value) among (?P<pool2>creatures|creatures and planeswalkers) "
    r"they control"
    r"|they control with the greatest power)"
)


def _sacrifice_greatest_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    groups = m.groupdict()
    stat = groups["stat"] or groups["stat2"] or "power"
    pool = groups["pool"] or groups["pool2"] or ("creatures" if groups["what"] == "creature" else None)
    # The "among …" pool must be the picked type: "creature" ↔ "creatures", "creature or planeswalker" ↔ both.
    if pool is not None and (pool == "creatures") != (groups["what"] == "creature"):
        return None
    if groups["verb"] == "exiles" and m.group("who") == "each opponent":
        return None  # an exile edict printed on every opponent is not a card yet
    params: dict = {
        "what": "creature" if groups["what"] == "creature" else "creature_or_planeswalker", "count": 1,
        "greatest": stat.replace(" ", "_"),
    }
    if groups["verb"] == "exiles":
        params["action"] = "exile"
    if m.group("who") == "each opponent":
        params["selector"] = "each_opponent"
    else:
        params["target_kind"] = "player"
    return [EffectSpec("sacrifice", params)]


#: "Create a number of 1/1 red Warrior creature tokens equal to the number of creatures target player
#: controls." (Will of the Mardu) — the count is taken *as that player* (`effect_amounts`' ``of: "target"``),
#: so the player is announced by a bare `choose_targets` and the token count bound to their creatures.
_TOKENS_PER_TARGET_PLAYER_CREATURE_RE = _c(
    r"create a number of (?P<token>\d+/\d+ [a-z ]+? creature) tokens equal to the number of creatures "
    r"target player controls"
)


def _tokens_per_target_player_creature(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    token = match_clause(f"create a {m.group('token')} token")
    if not token or len(token) != 1 or token[0].type != "create_token":
        return None
    params = {**token[0].params, "count": "$n"}
    return [
        EffectSpec("choose_targets", {"kinds": ["player"]}),
        EffectSpec("bind", {
            "name": "n",
            "amount": {
                "kind": "count_selector", "of": "target",
                "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
            },
            "effects": [{"type": "create_token", "params": params}],
        }),
    ]


#: "Any number of target opponents each sacrifice a creature with the greatest power among creatures that
#: player controls and lose N life." (Will of the Abzan) — the targets are announced by a bare
#: `choose_targets` ("any number" is a RULE 601.2c declinable count), then a loop over exactly those
#: chosen opponents hands each one to a sacrifice and a life loss that read the item as their player.
_ANY_OPPONENTS_SACRIFICE_LOSE_RE = _c(
    r"any number of target opponents each sacrifice a creature with the greatest power among creatures "
    r"that player controls and lose (?P<n>\d+) life"
)


def _any_opponents_sacrifice_lose(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("choose_targets", {
            "kinds": ["opponent"], "count": _ANY_NUMBER_TARGET_CAP, "optional": True,
        }),
        EffectSpec("for_each", {"over": {"targets": True}, "effects": [
            {"type": "sacrifice", "params": {
                "what": "creature", "count": 1, "greatest_power": True, "target_kind": "player",
            }},
            {"type": "lose_life", "params": {"amount": int(m.group("n")), "target_kind": "player"}},
        ]}),
    ]


#: "Sacrifice a creature." (Inevitable End's quoted upkeep ability) — an
#: untargeted RULE 701.17 choice made by the ability's controller.  This is
#: an effect body, not the superficially identical activated/casting *cost*;
#: those are peeled by the segmenter before this catalogue is consulted.
_SACRIFICE_CONTROLLER_RE = _c(
    r"sacrifice (?P<count>a|an|\d+) (?P<what>creature|artifact|land|permanent)s?"
)


def _sacrifice_controller(m: re.Match[str]) -> list[EffectSpec]:
    count_word = m.group("count")
    return [EffectSpec("sacrifice", {
        "selector": "controller", "what": m.group("what"),
        "count": 1 if count_word in ("a", "an") else int(count_word),
    })]


#: "Each player loses N life unless they discard a card."/"...unless they
#: sacrifice a creature, artifact, or land of their choice." (PAR-13, Tomb
#: of Annihilation's "Veils of Fear"/"Sandfall Cell" dungeon rooms) — RULE
#: 101.4's APNAP mass "unless", `RulesEngine._request_each_player_pay_or`'s
#: only oracle-text route. Only these two cost phrasings (the ones real
#: cards in the pool actually print for this shape) — a compound sacrifice
#: cost the plain-word `_SACRIFICE_RE`/`ActivationCost.sacrifice` vocabulary
#: doesn't otherwise reach (`costs._SACRIFICE_CREATURE_ARTIFACT_OR_LAND_RE`).
_EACH_PLAYER_LOSE_LIFE_UNLESS_RE = _c(
    r"each (?P<who>player|opponent) loses (?P<n>\d+) life unless they "
    r"(?P<cost>discard a card"
    # "…discard a card **or** sacrifice a creature." (Polygraph Orb) — the
    # OR form; `_each_player_lose_life_unless` sets `sacrifice_or_discard`.
    r"(?P<or_sac> or sacrifice a creature)?"
    r"|sacrifice a creature,\s*(?:an?\s+)?artifact,?\s*(?:or|and)\s*(?:an?\s+)?land of their choice)"
)


def _each_player_lose_life_unless(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "cost": "discard a card" if m.groupdict().get("or_sac") else m.group("cost"),
        "effects": [{
            "type": "lose_life",
            "params": {"amount": int(m.group("n")), "target_kind": "player"},
        }],
    }
    if m.group("who") == "opponent":
        params["scope"] = "each_opponent"
    if m.groupdict().get("or_sac"):
        params["sacrifice_or_discard"] = True
    return [EffectSpec("each_player_pay_or", params)]


#: "Discard a card and sacrifice a creature, an artifact, and a land."
#: (PAR-13, Dungeon of the Mad Mage's "Oubliette" room) — a mandatory
#: compound cost-shaped punishment, not an "unless" choice: one `discard`
#: plus three independent `choose_objects` sacrifices (the payer's own
#: pick within each type, RULE 701.17a — `ChooseObjectsEffect` already
#: resolves with no prompt when there's nothing to choose between, and as a
#: no-op when a type has no legal candidate at all). A standalone whole-
#: clause row rather than relying on the generic `" and "` connector split
#: (`segmenter._CONNECTORS`), since that would also split the sacrifice's
#: own internal "a creature, an artifact, **and** a land" list.
_DISCARD_AND_SACRIFICE_TRIPLE_RE = _c(
    r"discard a card and sacrifice a creature, an artifact, and a land"
)


def _discard_and_sacrifice_triple(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("discard", {"count": 1}),
        EffectSpec("choose_objects", {"action": "sacrifice", "what": "creature", "count": 1}),
        EffectSpec("choose_objects", {"action": "sacrifice", "what": "artifact", "count": 1}),
        EffectSpec("choose_objects", {"action": "sacrifice", "what": "land", "count": 1}),
    ]


def _gain_life(m: re.Match[str]) -> list[EffectSpec]:
    # "you gain N life" / "target player gains N life" (Abuna's Chant-shaped)
    # / "you gain X life" (Battle at the Bridge's trailing sentence, PAR-47's
    # widening sweep — the ``"x"`` sentinel `RulesEngine._substitute_x`
    # already resolves on `GainLifeEffect.amount`) — a real RULE 115 target
    # only for the "target player" phrasing.
    params: dict = {"amount": count_or_x_of(m.group("n"))}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("gain_life", params)]


#: RULE 119's "drain" idiom trailing sentence — "You gain life equal to the
#: life lost this way." (Gray Merchant of Asphodel/Exsanguinate/Kokusho, the
#: Evening Star-shaped, 16+ cache cards) — always the second sentence after
#: a "`<player(s)>` lose[s] `<amount>` life" clause that already parses on
#: its own (`_lose_life`/`_lose_life_selector`); only this trailing pronoun
#: sentence was ever unclaimed, discarding the *whole* two-sentence ability
#: fail-closed.
_GAIN_LIFE_LOST_THIS_WAY_RE = _c(r"you gain life equal to the life lost this way")


def _gain_life_lost_this_way(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"count_selector": "life_lost_this_way"})]


_GAIN_LIFE_SACRIFICED_TOUGHNESS_RE = _c(
    r"you gain life equal to the sacrificed creature'?s toughness"
)


def _gain_life_sacrificed_toughness(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"count_selector": "sacrificed_cost_toughness"})]


#: "You gain life equal to `<its / that creature's>` `<power / toughness>`."
#: (~36 SOLO — Bottle Golems / Angelic Chorus / Weed Strangle [a clash
#: card] / Brightmare / …). The creature isn't a RULE 115 target of the
#: gain-life effect itself; `GainLifeEffect.amount_from_subject` names which
#: object + characteristic. Three gated handlers, one per pronoun subject:
#: "its" on a bare-`~` trigger → ``self_*``; "its" on a group trigger
#: ("a creature you control enters" — the firing creature) →
#: ``trigger_subject_*``; "that creature's" after another clause →
#: ``previous_subject_*`` (RULE 608.2h last-known info — the creature is
#: usually gone by then).
_GAIN_LIFE_EQ_ITS_RE = _c(r"you (?:may )?gain life equal to its (?P<char>power|toughness)")
_GAIN_LIFE_EQ_THAT_RE = _c(
    r"you (?:may )?gain life equal to that (?:creature|permanent)'?s (?P<char>power|toughness)"
)


def _gain_life_eq_its_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount_from_subject": f"self_{m.group('char')}"})]


def _gain_life_eq_its_group(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount_from_subject": f"trigger_subject_{m.group('char')}"})]


def _gain_life_eq_that_prev(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount_from_subject": f"previous_subject_{m.group('char')}"})]


#: "When ~ dies, draw cards equal to its power." (Lifeblood Hydra / Return
#: of the Wildspeaker / Kavu Lair-shaped) and its combined sibling "…you
#: gain life **and** draw cards equal to its power." (Lifeblood Hydra's own
#: single clause, where "equal to its power" scopes both verbs at once, so
#: the ordinary "and" connector split can't reach it). ``trigger_subject_``
#: reads the DIES event's RULE 400.7 power/toughness snapshot
#: (`_characteristic_of_subject`); `DrawCardEffect.amount_from_subject` is
#: the new draw-side sibling of `GainLifeEffect`'s own field. `self_subject_
#: only` — "its" here is the trigger's own subject.
_DRAW_EQ_ITS_RE = _c(r"draw cards equal to its (?P<char>power|toughness)")
_GAIN_LIFE_AND_DRAW_EQ_ITS_RE = _c(
    r"you gain life and draw cards equal to its (?P<char>power|toughness)"
)


def _draw_eq_its_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {"amount_from_subject": f"trigger_subject_{m.group('char')}"})]


def _gain_life_and_draw_eq_its_self(m: re.Match[str]) -> list[EffectSpec]:
    key = f"trigger_subject_{m.group('char')}"
    return [
        EffectSpec("gain_life", {"amount_from_subject": key}),
        EffectSpec("draw", {"amount_from_subject": key}),
    ]


#: PAR-115 (`14_` S4 residue): "…. its controller `<verb>` …" — the
#: previous clause's own **controller**, not the previous clause's chosen
#: object itself (`gain_life_eq_that_prev`/`draw_eq_its_self` just above).
#: `EffectHandler.previous_subject_only` already gates on exactly the right
#: antecedent (`segmenter._announces_creature_target`: a destroyed/exiled/
#: countered/bounced/tapped permanent or a countered spell), so these rows
#: reuse that gate rather than adding a new one, and read the referent
#: through `game/effect_operands.py`'s ``{"of": "previous_target", "as":
#: "controller"}`` — the same vocabulary `game/card_catalogue/
#: swords_to_plowshares.py`/`nature_s_claim.py` already spell out by hand
#: for one card each. A trailing "and you {gain,lose} N life" (Certain
#: Death/Inevitable Defeat/Punish Ignorance) needs no grammar here at all:
#: `segmenter._CONNECTORS`' own " and " split recurses on the remainder
#: with the same referent, and the ordinary bare ``gain_life``/``lose_life``
#: rows already claim "you gain/lose N life" by themselves.
_PREVIOUS_TARGET_CONTROLLER: dict = {"of": "previous_target", "as": "controller"}
# "its controller"/"that creature's controller"/"that player" all name the
# same antecedent's controller. Which antecedent that is remains the handler
# gate's job: `previous_subject_only` for a preceding target,
# `group_subject_only` for a RULE 603.1 firing object (Blood Reckoning), and
# `attached_subject_only` for an Aura's host. Keeping the spelling together
# prevents a second parallel referent vocabulary from drifting out of sync.
#
# PAR-120: "that player" reads the same `_PREVIOUS_TARGET_CONTROLLER`
# operand unchanged — no separate referent needed. `effect_operands._derive`
# already resolves "controller of" a referent that turns out to *already be*
# a `Player` (a preceding "target player"/"target opponent" clause) to that
# player directly rather than a controller lookup (Diplomacy of the Wastes:
# "target opponent reveals their hand. … that player discards that card." —
# previous_target is already the opponent), and falls back to reading
# `.controller_id` off a `GameObject` referent otherwise (Carrion Locust's
# exiled graveyard card, Massacre Wurm's group-subject dying creature,
# Dalek Drone's destroyed creature) — the same disambiguation "its
# controller" already relies on, just under a different printed pronoun.
_CONTROLLER_REFERENT = r"(?:(?:its|that creature'?s) controller|that player)"
#: ``x`` is a "…loses life equal to <amount>" rewrite's own measurement (`segmenter._where_x_specs` — Deny the Witch);
#: the group/attached rows (`_its_controller_spec`) have nothing to bind it to and refuse it.
_ITS_CONTROLLER_LOSES_LIFE_RE = _c(rf"{_CONTROLLER_REFERENT} loses (?P<n>\d+|x) life")
_ITS_CONTROLLER_GAINS_LIFE_RE = _c(rf"{_CONTROLLER_REFERENT} gains (?P<n>\d+|x) life")
_ITS_CONTROLLER_DRAWS_RE = _c(rf"{_CONTROLLER_REFERENT} draws? {COUNT_X} cards?")
_ITS_CONTROLLER_DISCARDS_RE = _c(rf"{_CONTROLLER_REFERENT} discards? {COUNT} cards?")


def _its_controller_loses_life(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {
        "amount": count_or_x_of(m.group("n")), "player": _PREVIOUS_TARGET_CONTROLLER,
    })]


def _its_controller_gains_life(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {
        "amount": count_or_x_of(m.group("n")), "player": _PREVIOUS_TARGET_CONTROLLER,
    })]


def _its_controller_draws(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {
        "count": count_or_x_of(m.group("n")), "player": _PREVIOUS_TARGET_CONTROLLER,
    })]


def _its_controller_discards(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discard", {
        "count": count_of(m.group("n")), "player": _PREVIOUS_TARGET_CONTROLLER,
    })]


#: Torment of Venom — its targeted creature's controller, not the spell's
#: caster, may choose either half of the printed compound cost.  The earlier
#: counter instruction supplies the RULE 608.2 pronoun referent.
_ITS_CONTROLLER_LOSES_LIFE_UNLESS_SAC_OR_DISCARD_RE = _c(
    rf"{_CONTROLLER_REFERENT} loses (?P<n>\d+) life unless they sacrifice "
    r"another nonland permanent of their choice or discard a card"
)


def _its_controller_loses_life_unless_sac_or_discard(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pay_cost_then", {
        "cost": "sacrifice a nonland permanent",
        "payer": "previous_target_controller",
        "sacrifice_or_discard": True,
        "capture_previous": True,
        "effects": [],
        "else_effects": [{"type": "lose_life", "params": {
            "amount": int(m.group("n")), "player": _PREVIOUS_TARGET_CONTROLLER,
        }}],
    })]


#: "counter target spell. its controller mills N cards." (Countermand/
#: Didn't Say Please/Psychic Strike/Thought Collapse's own family) —
#: `MillEffect.selector="previous_subject_controller"` already exists,
#: built for Broken Ambitions' "that spell's controller mills four cards"
#: (see that effect's own docstring, RULE 608.2h) — this was only ever
#: missing the "its controller" parser row, not the engine primitive.
_ITS_CONTROLLER_MILLS_RE = _c(rf"{_CONTROLLER_REFERENT} mills {COUNT} cards?")


def _its_controller_mills(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {
        "count": count_of(m.group("n")), "selector": "previous_subject_controller",
    })]


#: "…, its controller gains life equal to its mana value." (Illumination)
#: / "…, its controller mills cards equal to that creature's power."
#: (Grisly Spectacle) — the referent's own `mana_value`/`power`, measured
#: once through a `bind` (ENG-37) exactly the way `swords_to_plowshares.py`
#: already does by hand for "its controller gains life equal to its
#: power", generalized here into an ordinary parser row.
_ITS_CONTROLLER_GAINS_LIFE_EQ_MV_RE = _c(
    r"its controller gains life equal to its mana value"
)
_ITS_CONTROLLER_MILLS_EQ_POWER_RE = _c(
    r"its controller mills cards equal to that creature'?s power"
)


def _its_controller_gains_life_eq_mv(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bind", {
        "name": "mv",
        "amount": {
            "kind": "characteristic", "characteristic": "mana_value", "of": "previous_target",
        },
        "effects": [{
            "type": "gain_life",
            "params": {"amount": "$mv", "player": _PREVIOUS_TARGET_CONTROLLER},
        }],
    })]


def _its_controller_mills_eq_power(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bind", {
        "name": "power",
        "amount": {"kind": "characteristic", "characteristic": "power", "of": "previous_target"},
        "effects": [{
            "type": "mill",
            "params": {"count": "$power", "selector": "previous_subject_controller"},
        }],
    })]


#: PAR-117 (PAR-115's group-subject residue): "whenever a `<type>` [you
#: control] `<verb>`, its controller `<verb2>` …" (Poisonbelly Ogre-shaped
#: — "whenever another creature enters, its controller loses 1 life.") —
#: "its" is RULE 603.1's own group-subject referent (whichever object
#: satisfied the trigger condition, a different one every firing), not a
#: creature an earlier clause of this body targeted (`_ITS_CONTROLLER_*`
#: above) or the ability's own source. `effect_conditions.subject_of
#: ("entering", ...)` already resolves exactly this — the firing event's
#: own ``instance_id`` (built for MEC-28's `group_subject_only` pronoun
#: gate) — so the same ``{"of": …, "as": "controller"}`` referent
#: `GainLifeEffect`/`LoseLifeEffect`/`DrawCardEffect`/`DiscardEffect`
#: already read via `_operand_player` (PAR-115) works unchanged; only
#: `MillEffect` needs a new selector value, the `"previous_subject_
#: controller"` sibling for this referent instead of `previous_targets`.
_ENTERING_CONTROLLER: dict = {"of": "entering", "as": "controller"}




#: "whenever a Sliver deals damage, its controller gains that much life."
#: (Essence Sliver) — "that much" is the firing DAMAGE event's own
#: ``amount`` field, the ``group_subject_only`` sibling of `_ITS_CONTROLLER_
#: LOSES_THAT_MUCH_LIFE_RE`'s `attached_subject_only` row above (Ragged
#: Veins/Visions of Brutality print the "loses" polarity off an attached
#: host; no cached card yet pairs a group subject with "loses" instead of
#: "gains", so only this polarity is added here).
_ITS_CONTROLLER_GAINS_THAT_MUCH_LIFE_RE = _c(r"its controller gains that much life")






#: PAR-117 (attached-permanent-controller residue): "whenever enchanted
#: creature/land `<trigger>`, its controller `<verb>` …" (Contaminated
#: Bond/Corrupted Roots/Sinister Possession/Ragged Veins/Visions of
#: Brutality/Chronic Flooding/Fate Foretold/Decomposition) — "its" is RULE
#: 303.4/301.5's attached host, a fourth referent alongside
#: `previous_subject_only`/`group_subject_only` above: the trigger
#: condition itself already names it (`{"subject": "attached_permanent"}`),
#: not a pronoun chain within the effect body. `segmenter._ATTACHED_
#: SUBJECT_RE`/`_ATTACHED_MULTI_EVENT_RE`/the ``attached`` groups on
#: `_DAMAGE_TRIGGER_RE`/`_DAMAGE_RECIPIENT_TRIGGER_RE` already recognize
#: every one of this cluster's antecedents; only these bodies were
#: unclaimed. Reuses the same compiled regexes as the `previous_subject`/
#: `group_subject` families above (the printed clause text is identical —
#: only the referent differs) and the same ``{"of": "attached", "as":
#: "controller"}`` operand `effect_conditions.subject_of`/`game/
#: effect_operands.py` now resolve (PAR-117's own `subject_of` widening);
#: `MillEffect` gets the `"attached_permanent_controller"` selector sibling
#: of `"trigger_subject_controller"` the same way `LoseLifeEffect` already
#: had one (built for the hand-authored Parasitic Impetus).
_ATTACHED_CONTROLLER: dict = {"of": "attached", "as": "controller"}







#: "whenever enchanted creature is dealt damage / deals damage, its
#: controller loses that much life." (Ragged Veins / Visions of Brutality)
#: — "that much" is the firing DAMAGE event's own ``amount`` field, the same
#: idiom `_lose_life_from_trigger_amount`/`_gain_life_from_trigger_amount`
#: already use for a RULE 115 target/the ability's own controller; this is
#: their attached-host-controller sibling.
_ITS_CONTROLLER_LOSES_THAT_MUCH_LIFE_RE = _c(r"its controller loses that much life")



#: PAR-117 (sacrifice-verb residue): "its controller sacrifices `<N>`
#: [nontoken] `<what>`[ or `<what2>`] of their choice" (Funeral March —
#: attached_permanent referent; Tainted Aether — group-subject referent).
#: `SacrificeEffect.player` now accepts the same ``{"of": …, "as":
#: "controller"}`` referent `GainLifeEffect`/`LoseLifeEffect`/`DrawCardEffect`/
#: `DiscardEffect`/`MillEffect` already read (widened alongside this row —
#: RULE 601.2c's interactive edict needed no different plumbing than any
#: other player-scoped effect, just the same operand). Reuses
#: `_SACRIFICE_EDICT_WHAT_WORDS`/`_sacrifice_edict`'s own vocabulary; the
#: optional "or `<what2>`" alternation only recognizes the one two-word
#: combination a real card needs (`_SACRIFICE_WHAT_OR_COMBOS`) rather than
#: every pairing, the same closed-vocabulary discipline `_matches_
#: permanent_type` itself follows.
_SACRIFICE_WHAT_OR_COMBOS: dict[frozenset, str] = {
    frozenset({"creature", "land"}): "creature_or_land",
}
_ITS_CONTROLLER_SACRIFICES_RE = _c(
    rf"its controller sacrifices (?P<count>a|an|\d+) (?P<nontoken>nontoken )?"
    rf"(?P<what>{'|'.join(_SACRIFICE_EDICT_WHAT_WORDS)})s?"
    rf"(?: or (?P<what2>{'|'.join(_SACRIFICE_EDICT_WHAT_WORDS)})s?)? of their choice"
)


def _its_controller_sacrifices_params(m: re.Match[str]) -> Optional[dict]:
    what = _SACRIFICE_EDICT_WHAT_WORDS[m.group("what")]
    what2 = m.groupdict().get("what2")
    if what2:
        combo = _SACRIFICE_WHAT_OR_COMBOS.get(frozenset({what, _SACRIFICE_EDICT_WHAT_WORDS[what2]}))
        if combo is None:
            return None  # an un-whitelisted "<x> or <y>" pairing → fail closed
        what = combo
    elif m.group("nontoken") and what == "creature":
        what = "nontoken_creature"
    count_word = m.group("count")
    return {"what": what, "count": 1 if count_word in ("a", "an") else int(count_word)}




#: PAR-121: "its controller `<verb>` …" — the verb × subject matrix. The same clause text reads as the controller
#: of the creature a group trigger fired for (``group``, `_ENTERING_CONTROLLER`; Poisonbelly Ogre-shaped) or of an
#: Aura's host (``attached``, `_ATTACHED_CONTROLLER`; Contaminated Bond-shaped) — the two referents differ only
#: in the operand a player-scoped effect reads (and the `MillEffect` selector sibling), so each verb is built once
#: from ``(player operand, mill selector)`` instead of once per subject. The third reading ("its" = an earlier
#: clause's pick, ``previous``) has its own builders above because it resolves through `previous_targets`.
#: "that much" is the firing DAMAGE event's own ``amount`` (Essence Sliver's "gains", Ragged Veins' "loses" —
#: each printed off a different subject only, so each polarity exists for one).
_ITS_CONTROLLER_SUBJECTS: dict[str, tuple[dict, str]] = {
    "group": (_ENTERING_CONTROLLER, "trigger_subject_controller"),
    "attached": (_ATTACHED_CONTROLLER, "attached_permanent_controller"),
}


def _its_controller_spec(verb: str, m: re.Match[str], player: dict, mill_selector: str) -> Optional[list[EffectSpec]]:
    if verb in ("loses_life", "gains_life") and m.group("n") == "x":
        return None
    if verb == "loses_life":
        return [EffectSpec("lose_life", {"amount": int(m.group("n")), "player": player})]
    if verb == "gains_life":
        return [EffectSpec("gain_life", {"amount": int(m.group("n")), "player": player})]
    if verb == "loses_that_much_life":
        return [EffectSpec("lose_life", {"amount_from_trigger_event": "amount", "player": player})]
    if verb == "gains_that_much_life":
        return [EffectSpec("gain_life", {"amount_from_trigger_event": "amount", "player": player})]
    if verb == "draws":
        return [EffectSpec("draw", {"count": count_or_x_of(m.group("n")), "player": player})]
    if verb == "discards":
        return [EffectSpec("discard", {"count": count_of(m.group("n")), "player": player})]
    if verb == "mills":
        return [EffectSpec("mill", {"count": count_of(m.group("n")), "selector": mill_selector})]
    if verb == "sacrifices":
        params = _its_controller_sacrifices_params(m)
        return None if params is None else [EffectSpec("sacrifice", {**params, "player": player})]
    return None


def _its_controller_handlers() -> list[EffectHandler]:
    """One row per (subject, verb) the printed cards use, in the order the rows were first written."""
    regexes = {
        "loses_life": _ITS_CONTROLLER_LOSES_LIFE_RE,
        "gains_life": _ITS_CONTROLLER_GAINS_LIFE_RE,
        "loses_that_much_life": _ITS_CONTROLLER_LOSES_THAT_MUCH_LIFE_RE,
        "gains_that_much_life": _ITS_CONTROLLER_GAINS_THAT_MUCH_LIFE_RE,
        "draws": _ITS_CONTROLLER_DRAWS_RE,
        "discards": _ITS_CONTROLLER_DISCARDS_RE,
        "mills": _ITS_CONTROLLER_MILLS_RE,
        "sacrifices": _ITS_CONTROLLER_SACRIFICES_RE,
    }
    matrix = (
        ("group", ("loses_life", "gains_life", "gains_that_much_life", "draws", "discards", "mills", "sacrifices")),
        ("attached", ("loses_life", "loses_that_much_life", "gains_life", "draws", "discards", "mills", "sacrifices")),
    )
    rows = []
    for subject, verbs in matrix:
        player, mill_selector = _ITS_CONTROLLER_SUBJECTS[subject]
        for verb in verbs:
            rows.append((
                f"{subject}_its_controller_{verb}", subject, regexes[verb],
                lambda m, verb=verb, player=player, mill_selector=mill_selector:
                    _its_controller_spec(verb, m, player, mill_selector),
            ))
    return _subject_handlers(rows)


#: "Whenever a player casts a spell, they lose 1 life for each spell
#: they've cast this turn." (Rug of Smothering) — the caster's own running
#: `GameState.spells_cast_this_turn` count (`LoseLifeEffect.
#: amount_from_spells_cast_this_turn`, including the cast that fired this
#: trigger), not a flat amount — tried before the plain `_lose_life` row
#: below, whose bare `{NUMBER}` group can't match "each spell...".
_LOSE_LIFE_PER_SPELL_CAST_THIS_TURN_RE = _c(
    rf"they lose {NUMBER} life for each spell they'?ve cast this turn"
)


def _lose_life_per_spell_cast_this_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {
        "amount": int(m.group("n")), "selector": "event_player",
        "amount_from_spells_cast_this_turn": True,
    })]


#: PAR-124: "Whenever a player gains life, **that player** loses N life for
#: each 1 life they gained." (False Cure) — the same "event's own firing
#: player" referent as `_lose_life`'s "they" row (`selector="event_player"`),
#: just spelled "that player"; the magnitude is a live multiple of the
#: `LIFE_GAINED` event's own ``amount`` field, read through the shared
#: `effect_amounts` ``"trigger_event"`` operand's generic ``multiply``
#: modifier (`ENG-47 b`) rather than a bespoke per-effect parameter.
_LOSE_LIFE_PER_LIFE_GAINED_RE = _c(
    r"that player loses (?P<n>\d+) life for each 1 life they gained"
)


def _lose_life_per_life_gained(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {
        "amount": {"kind": "trigger_event", "field": "amount", "multiply": int(m.group("n"))},
        "selector": "event_player",
    })]


def _lose_life(m: re.Match[str]) -> list[EffectSpec]:
    # "you lose N life" / "target player loses N life" / "target opponent
    # loses N life" — same targeting split as `_gain_life`. "target
    # opponent" is the RULE 115 opponent-restricted player target (the
    # `"opponent"` target kind), which pairs with a following "and you gain
    # N life" clause via the ordinary connector split for the Blood Artist
    # drain family. "they lose N life" (Sheoldred, the Apocalypse's
    # "whenever an opponent draws a card, they lose 2 life.") is the group-
    # subject trigger's own firing player, not a fresh RULE 115 target —
    # `LoseLifeEffect`'s ``selector="event_player"``, the same "that player"
    # idiom `_SELECTOR_WORD_MAP`'s ``"event_player"`` row already uses.
    who = (m.groupdict().get("who") or "").strip()
    # "x" is the announced {X} (substituted when the spell resolves) or the one a "where X is …" binds.
    params: dict = {"amount": "x" if m.group("n").lower() == "x" else int(m.group("n"))}
    if who == "target player":
        params["target_kind"] = "player"
    elif who == "target opponent":
        params["target_kind"] = "opponent"
    elif who == "they":
        params["selector"] = "event_player"
    return [EffectSpec("lose_life", params)]


def _lose_life_selector(m: re.Match[str]) -> list[EffectSpec]:
    # "each opponent loses N life" / "each player loses N life" / "each
    # other player loses N life" — the shared `_SELECTOR_WORD_MAP` mass/
    # untargeted-selector shape (RULE 601.2c, not RULE 115 targeting).
    selector = _SELECTOR_WORD_MAP[m.group("selector")]
    # ``COUNT_X`` (not just digits) so "each opponent loses X life."
    # (Exsanguinate) carries the ``"x"`` sentinel `RulesEngine._substitute_x`
    # resolves against the spell's actually-announced {X} at resolve time —
    # `LoseLifeEffect.amount` is a plain attribute that sentinel already
    # walks, so no engine change was needed, just this wider capture.
    return [EffectSpec("lose_life", {"amount": count_or_x_of(m.group("n")), "selector": selector})]


#: RULE 202.2f/700.6 "each opponent loses X life, where X is your devotion
#: to `<colour>`." (Gray Merchant of Asphodel-shaped) — `_lose_life_
#: selector`'s devotion-amount sibling, tried first since "x" never matches
#: that row's `NUMBER` (``\d+``).
_LOSE_LIFE_SELECTOR_DEVOTION_RE = _c(
    rf"(?P<selector>each player|each opponent) loses x life, where x is {DEVOTION}"
)


_lose_life_selector_devotion = _selector_devotion_builder("lose_life")


#: "Each opponent loses life equal to the number of Vampires you control."
#: (Malakir Bloodwitch) — `continuous.count_selector`'s existing
#: ``creatures_you_control_of_type_<subtype>`` vocabulary (already reached
#: by `_create_token_for_each`'s "for each `<subtype>` you control" reading)
#: applied to life loss instead of a token count.
_LOSE_LIFE_SELECTOR_SUBTYPE_RE = _c(
    r"(?P<selector>each player|each opponent) loses life equal to the number of "
    r"(?P<subtype>[a-z]+) you control"
)


def _lose_life_selector_subtype(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector = _SELECTOR_WORD_MAP[m.group("selector")]
    counted = subtype_count_selector(m.group("subtype"))
    if counted is None:
        return None
    return [EffectSpec("lose_life", {"amount_from_count_selector": counted, "selector": selector})]


#: MEC-27's own residual: the "draw"/"you gain life"/"you lose life" verb
#: families `{DEVOTION}` had never been wired to, unlike the "each player/
#: opponent loses life"/damage/counters/pump/token families above — always
#: the caster/ability's own controller (RULE 118), not a mass "each
#: player/opponent" recipient, so each is its own plain row rather than
#: routed through `_selector_devotion_builder`'s selector-word plumbing.
_DRAW_DEVOTION_RE = _c(rf"draws? x cards?, where x is {DEVOTION}")


def _draw_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [EffectSpec("draw", {"amount_from_count_selector": dsel})]


_GAIN_LIFE_DEVOTION_RE = _c(rf"you gains? x life, where x is {DEVOTION}")


def _gain_life_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [EffectSpec("gain_life", {"count_selector": dsel})]


#: "You gain life equal to the number of creatures/permanents … you
#: control." This is the non-X wording sibling of `_GAIN_LIFE_DEVOTION_RE`;
#: both use the existing live count-selector path. It can follow a token
#: creation clause, where the count includes the just-created tokens.
_GAIN_LIFE_EQUAL_DEVOTION_RE = _c(rf"you gains? life equal to {DEVOTION}")


def _gain_life_equal_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [EffectSpec("gain_life", {"count_selector": dsel})]


_LOSE_LIFE_SELF_DEVOTION_RE = _c(rf"you loses? x life, where x is {DEVOTION}")


def _lose_life_self_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [EffectSpec("lose_life", {"amount_from_count_selector": dsel})]


#: The three "draw X and gain/lose X life" combined templates (Champion of
#: Dusk/Graveborn Muse/Minions' Murmurs, Nissa/Camaraderie) — two one-shot
#: effects sharing one `{DEVOTION}` amount, in the printed clause's own
#: order (RULE 608.2b). The repeated "you" (Champion of Dusk's "you draw x
#: cards and **you** lose x life") is optional since some printings drop it
#: (Painful Truths' "you draw x cards and lose x life").
_DRAW_AND_LOSE_LIFE_DEVOTION_RE = _c(
    rf"you draws? x cards? and (?:you )?loses? x life, where x is {DEVOTION}"
)
_GAIN_LIFE_AND_DRAW_DEVOTION_RE = _c(
    rf"you gains? x life and draws? x cards?, where x is {DEVOTION}"
)
#: PAR-31 (Ob Nixilis of the Black Oath's −8 emblem): "You gain X life and
#: draw X cards, where X is the sacrificed creature's power." — the same
#: two-effects-share-one-X shape as the `{DEVOTION}` combos above, but X is
#: `continuous.count_selector`'s ``"sacrificed_cost_power"`` (stamped on the
#: ability source when a "sacrifice a creature" cost is paid — Altar of
#: Dementia's own idiom, MEC-43). Its own row rather than folded into
#: `{DEVOTION}` (a subgrammar reused far too widely to widen for one card).
_GAIN_LIFE_AND_DRAW_SAC_POWER_RE = _c(
    r"you gains? x life and draws? x cards?, "
    r"where x is the sacrificed creature'?s power"
)
_DRAW_AND_GAIN_LIFE_DEVOTION_RE = _c(
    rf"you draws? x cards? and (?:you )?gains? x life, where x is {DEVOTION}"
)


def _draw_and_lose_life_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [
        EffectSpec("draw", {"amount_from_count_selector": dsel}),
        EffectSpec("lose_life", {"amount_from_count_selector": dsel}),
    ]


def _gain_life_and_draw_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [
        EffectSpec("gain_life", {"count_selector": dsel}),
        EffectSpec("draw", {"amount_from_count_selector": dsel}),
    ]


def _draw_and_gain_life_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [
        EffectSpec("draw", {"amount_from_count_selector": dsel}),
        EffectSpec("gain_life", {"count_selector": dsel}),
    ]


def _gain_life_and_draw_sac_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [
        EffectSpec("gain_life", {"count_selector": "sacrificed_cost_power"}),
        EffectSpec("draw", {"amount_from_count_selector": "sacrificed_cost_power"}),
    ]


#: "Each opponent loses X life and you gain X life, where X is `{DEVOTION}`."
#: (Mishra, Claimed by Gix-shaped drain) — a fourth combined shape, distinct
#: from Gray Merchant's "each opponent loses X life... you gain life equal to
#: the life lost this way" (that one's already `_lose_life_selector_devotion`
#: + `_gain_life_lost_this_way`, two independently-claimed clauses): here
#: both halves name the *same* count directly, in one sentence, with no
#: {X}-cost of its own — critically, this must be claimed as **one** clause
#: rather than left to the generic `" and "` connector split
#: (`segmenter._CONNECTORS`), which would otherwise match its first half
#: ("each opponent loses x life") against the plain `_lose_life_selector`
#: row's `COUNT_X` — that row's "x" is RULE 107.3c's *announced-{X}*
#: sentinel, never substituted for a triggered ability with no X cost, so
#: the split would leave a `LoseLifeEffect(amount="x")` that crashes
#: (`"x" <= 0`) instead of reading `{DEVOTION}` at all.
_LOSE_LIFE_AND_GAIN_LIFE_DEVOTION_RE = _c(
    rf"each opponent loses x life and you gains? x life, where x is {DEVOTION}"
)


def _lose_life_and_gain_life_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [
        EffectSpec("lose_life", {"amount_from_count_selector": dsel, "selector": "each_opponent"}),
        EffectSpec("gain_life", {"count_selector": dsel}),
    ]


def _rad_counter_amount(token: str) -> "int | str":
    # "N rad counters"/"a rad counter" (COUNT) or "X rad counters" (RULE
    # 601.2b's own announced {X} — the same ``"x"`` sentinel
    # `additional_cost`'s `pay_life` uses, substituted at resolve time).
    return "x" if token.strip().lower() == "x" else count_of(token)


#: "[you/target player/defending player] get[s] N rad counters" (RULE 728,
#: player counters — see `_gain_life`/`_lose_life`'s identical who-prefix
#: shape). ``who`` omitted (bare "get two rad counters") covers a "you may"
#: prefix already peeled by the segmenter (Tato Farmer's Landfall).
#: "defending player" (Acquired Mutation, an Aura's "whenever enchanted
#: creature attacks, defending player gets ~") reuses the same
#: ``selector="defending_player"`` afflict/Simian Sling already established
#: for `LoseLifeEffect`/`DealDamageEffect` (`AddPlayerCountersEffect`'s own
#: apply()-time resolution accounts for the Aura-vs-host source split).
_RAD_COUNTER_WHO_SELECTOR: dict[str, str] = {"defending player": "defending_player"}


def _add_rad_counters(m: re.Match[str]) -> list[EffectSpec]:
    who = (m.groupdict().get("who") or "").strip().lower()
    params: dict = {"amount": _rad_counter_amount(m.group("n")), "kind": m.group("kind")}
    if who == "target player":
        params["target_kind"] = "player"
    elif who == "target opponent":
        # PAR-98 (Persuasive Interrogators): a real RULE 115 target, but only
        # among opponents — the "opponent" kind `targeting` already resolves.
        params["target_kind"] = "opponent"
    elif who in _RAD_COUNTER_WHO_SELECTOR:
        params["selector"] = _RAD_COUNTER_WHO_SELECTOR[who]
    return [EffectSpec("add_player_counters", params)]


#: "each player gets N rad counters" / "each opponent gets N poison
#: counters" (RULE 601.2c mass effect, RULE 122.1/104.3d — the same
#: `AddPlayerCountersEffect` primitive parametrized by ``kind``) — the
#: player-counter sibling of `_lose_life_selector`. ``kind`` is a real
#: regex alternation (not a fixed "rad") since Infectious Bite/Prologue to
#: Phyresis-shaped poison cards use the identical "each opponent gets a
#: `<kind>` counter" template.
def _add_rad_counters_selector(m: re.Match[str]) -> list[EffectSpec]:
    selector = _SELECTOR_WORD_MAP[m.group("selector")]
    return [EffectSpec("add_player_counters", {
        "amount": _rad_counter_amount(m.group("n")), "kind": m.group("kind"), "selector": selector,
    })]


#: "target player loses all rad counters" (Survivor's Med Kit's RadAway
#: mode) — the removal sibling, always ``target player`` in practice (no
#: real card grants this to "you" untargeted), so ``target_kind`` is
#: unconditional rather than an optional ``who`` group.
def _lose_all_rad_counters(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_all_player_counters", {"kind": "rad", "target_kind": "player"})]


#: "each opponent gets a number of rad counters equal to its power" (Feral
#: Ghoul's "When this creature dies, ..." — a dynamic amount tied to the
#: dying object's own power, RULE 400.7 last-known-information). ENG-37: this
#: is `bind` (measure the dying creature's power) over the generic
#: `add_player_counters`, not a fused effect type — `DiesGrantsRadCounters
#: EqualPowerEffect` is retired. `minimum: 0` reproduces that effect's own
#: `power <= 0` guard (RULE 122.1 — a negative counter count is zero; without
#: it a creature that died with negative power would *remove* opponents' rad
#: counters via `add_player_counters`' non-positive path).
def _dies_rad_counters_equal_power(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bind", {
        "name": "rad_pow",
        "amount": {
            "kind": "characteristic", "characteristic": "power",
            "of": "source", "minimum": 0,
        },
        "effects": [{"type": "add_player_counters", "params": {
            "kind": "rad", "selector": "each_opponent", "amount": "$rad_pow",
        }}],
    })]


#: "you get half X rad counters, rounded up/down" (Contaminated Drink's
#: "Draw X cards, then you get half X rad counters, rounded up.") — RULE
#: 107.1e's division-and-rounding phrasing, {X}-scaled only (no real card
#: needs a plain, non-X division yet); the ``"half_x_up"``/``"half_x_down"``
#: sentinel `RulesEngine._substitute_x` resolves against the spell's
#: actually-announced {X} at resolve time, mirroring the plain ``"x"``
#: sentinel exactly.
def _add_rad_counters_half_x(m: re.Match[str]) -> list[EffectSpec]:
    who = (m.groupdict().get("who") or "").strip().lower()
    amount = "half_x_up" if m.group("round") == "up" else "half_x_down"
    params: dict = {"amount": amount, "kind": "rad"}
    if who == "target player":
        params["target_kind"] = "player"
    elif who in _RAD_COUNTER_WHO_SELECTOR:
        params["selector"] = _RAD_COUNTER_WHO_SELECTOR[who]
    return [EffectSpec("add_player_counters", params)]


#: The single-printed-type permanent target kinds `resolve_target_kind`
#: resolves "target artifact"/"target enchantment"/"target land" to (RULE
#: 115.1c) — added to every guard tuple below that already accepted the
#: broad, untyped "target permanent" kind, so narrowing that mapping (fixing
#: e.g. Abrade's "Destroy target artifact." from wrongly offering any
#: permanent, including lands) doesn't regress these families to UNMODELED.
_SINGLE_TYPE_PERMANENT_KINDS: tuple[str, ...] = (
    "artifact", "enchantment", "land",
    # "destroy/exile target nonbasic land [an opponent controls]" (Fulminator
    # Mage / Dust Bowl / Field of Ruin / Ravenous Baboons — 21 SOLO on the
    # bare form). RULE 205.4 supertype filter; `targeting.legal_targets` has
    # a fully-implemented `nonbasic_land` branch and a new `nonbasic_land_
    # you_dont_control` sibling — same narrow-single-noun shape as `land`.
    "nonbasic_land", "nonbasic_land_you_dont_control",
)


def _destroy(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, (
        "creature", "attacking_or_blocking_creature", "permanent", "permanent_you_dont_control",
        # "destroy target nonland permanent [an opponent controls]"
        # (Binding the Old Gods' chapter I, Assassin's Trophy-adjacent) —
        # `targeting.legal_targets` has all three branches (RULE 115.1c).
        "nonland_permanent", "nonland_permanent_you_control",
        "nonland_permanent_you_dont_control",
        *_SINGLE_TYPE_PERMANENT_KINDS,
    )):
        return None
    color = resolve_color_word(m.groupdict().get("cond_color"))
    params: dict = {"target_kind": kind, **_optional_param(m)}
    if color:
        params["color"] = color
    # "destroy target tapped creature" (Assassinate-shaped) — `resolve_
    # target_kind` deliberately collapses "target attacking/blocking/
    # tapped/untapped creature" onto the bare "creature" kind (RULE 115's
    # own precision-loss convention); without this the qualifier is
    # silently dropped and the spell destroys *any* creature.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("destroy", params)]


#: "destroy target Equipment attached to it" — Shackles of Treachery's own
#: granted quoted trigger ("whenever this creature deals damage, …"), where
#: "it" is the granted-to creature, i.e. this ability's source
#: (`targeting.legal_targets`' new ``equipment_attached_to_source`` kind).
_DESTROY_EQUIPMENT_ATTACHED_TO_IT_RE = _c(
    r"destroy target equipment attached to it"
)


def _destroy_equipment_attached_to_it(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("destroy", {"target_kind": "equipment_attached_to_source"})]


#: "destroy target Equipment" (Manriki-Gusari).  Equipment is an artifact
#: subtype rather than a card type, so it deliberately is not part of the
#: broad ``TARGET`` grammar used by the ordinary destroy row.  The targeting
#: layer already has the precise subtype predicate.
_DESTROY_EQUIPMENT_RE = _c(rf"destroy target equipment(?P<that_player>{THAT_PLAYER_TAIL})?")


def _destroy_equipment(m: re.Match[str]) -> list[EffectSpec]:
    # PAR-130: "… that player controls" (Rustmouth Ogre's sibling Goblin
    # Gaveleer-shaped heads) — the trigger-scoped equipment pool.
    kind = "equipment_that_player_controls" if m.group("that_player") else "equipment"
    return [EffectSpec("destroy", {"target_kind": kind})]


#: "exile target `<c1>` or `<c2>` creature/permanent[ you don't control]"
#: (Celestial Purge) — `TargetSpec.colors`' OR narrowing, the
#: `_pump_target_two_color` / `_destroy_color_adj` sibling. The shared
#: `TARGET` macro's fixed rows have no colour slot, so a dedicated row.
_EXILE_TARGET_TWO_COLOR_RE = _c(
    rf"exile target (?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) "
    rf"(?P<noun>creature|permanent)(?P<yc> (?:you don't control|an opponent controls))?"
    rf"(?P<that_player>{THAT_PLAYER_TAIL})?"
)


def _two_color_letters(m: re.Match[str]) -> Optional[list[str]]:
    """A `(?P<c1>…) or (?P<c2>…)` colour pair → [W/U/B/R/G, …], or ``None``
    (an unrecognised colour word, or the same colour twice)."""
    colors = [resolve_color_word(m.group("c1")), resolve_color_word(m.group("c2"))]
    if not all(colors) or colors[0] == colors[1]:
        return None
    return colors


#: An open-ended colour list — "red, white, or black", "white or blue",
#: "red, white, black, or green" — the N-colour generalization of a
#: `(?P<c1>…) or (?P<c2>…)` pair. Matched as one `(?P<colors>…)` group; hand
#: the raw text to `_color_word_list` to get the WUBRG letters.
_COLOR_WORD_LIST_INNER = (
    rf"(?:{COLOR_WORD_ALT})(?:,? (?:or )?(?:{COLOR_WORD_ALT}))+"
)


def _color_word_list(text: Optional[str]) -> Optional[list[str]]:
    """"red, white, or black" → ``["R", "W", "B"]`` (order preserved), or
    ``None`` for an empty/unrecognised list or a repeated colour. The
    N-colour sibling of `_two_color_letters` — used where a `TargetSpec`
    colour narrowing may name three or more colours (Offspring's Revenge)."""
    if not text:
        return None
    words = re.findall(COLOR_WORD_ALT, text)
    letters = [resolve_color_word(w) for w in words]
    if len(letters) < 2 or not all(letters) or len(set(letters)) != len(letters):
        return None
    return letters


def _exile_target_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = _two_color_letters(m)
    if colors is None:
        return None
    noun = m.group("noun")
    kind = "permanent" if noun == "permanent" else "creature"
    if m.groupdict().get("yc"):
        kind = "permanent_you_dont_control" if noun == "permanent" else "creature_you_dont_control"
    elif m.groupdict().get("that_player"):
        kind = f"{kind}_that_player_controls"  # PAR-130
    return [EffectSpec("exile", {"target_kind": kind, "colors": colors})]


def _destroy_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "destroy target nonland permanent with mana value 3 or less"
    # (Abrupt Decay-shaped) — a target-offer-time mana-value cap
    # (`targeting.TargetSpec.max_mana_value`), tried before the plain
    # `_destroy` handler since it's a strict superset of that shape (the
    # trailing "with mana value N or less" clause `_destroy`'s own grammar
    # doesn't recognise). MEC-40: "nonland_permanent" was missing from this
    # tuple despite the docstring already naming Abrupt Decay by name — the
    # kind itself (`targeting.py`'s "nonland_permanent" branch) already
    # honours `max_mana_value`, so this was a plain oversight, not a missing
    # engine primitive.
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent", "nonland_permanent")):
        return None
    return [EffectSpec("destroy", {"target_kind": kind, _mana_value_bound_key(m): int(m.group("mv"))})]


def _mana_value_bound_key(m: re.Match[str]) -> str:
    """"…with mana value N or less" is a ceiling, "…or greater" a floor (`TargetSpec.max_/min_mana_value`)."""
    return "min_mana_value" if m.group("cmp") == "greater" else "max_mana_value"


def _exile_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "exile target permanent with mana value 4 or greater" (Despark, Kin-Tree Severance) / "…or less".
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent", "nonland_permanent")):
        return None
    return [EffectSpec("exile", {"target_kind": kind, _mana_value_bound_key(m): int(m.group("mv"))})]


#: A creature's power/toughness/keyword *quality* filter (RULE 115/601.2c —
#: "destroy target creature with power 4 or greater"/"…with flying"-shaped,
#: `targeting.TargetSpec.creature_filter`). English keyword word → the
#: internal snake_case token `combat.has` checks; only single-word-in-text
#: keywords a "with <keyword>" clause plausibly names are listed (extend as
#: a real card needs one — fail-closed for anything else via the ``kw``
#: alternation below).
_CREATURE_FILTER_KEYWORD_WORDS: dict[str, str] = {
    "flying": "flying", "defender": "defender", "first strike": "first_strike",
    "double strike": "double_strike", "trample": "trample", "vigilance": "vigilance",
    "deathtouch": "deathtouch", "lifelink": "lifelink", "menace": "menace",
    "haste": "haste", "indestructible": "indestructible", "hexproof": "hexproof",
    "reach": "reach", "horsemanship": "horsemanship",
}
#: One power/toughness/keyword clause, with named groups suffixed by
#: ``suffix`` so the same fragment can appear twice in one regex (a compound
#: "with power 4 or greater and flying" filter — two independent clauses
#: joined by "and", RULE 115/601.2c) without a group-name collision.
def _creature_filter_clause(suffix: str) -> str:
    return (
        rf"power (?P<pwr{suffix}>\d+) or (?P<pwr_cmp{suffix}>greater|less)"
        rf"|toughness (?P<tough{suffix}>\d+) or (?P<tough_cmp{suffix}>greater|less)"
        rf"|(?P<kw{suffix}>{'|'.join(_CREATURE_FILTER_KEYWORD_WORDS)})"
        # "with a -1/-1 counter on it" (Liliana, Death Wielder's -3 —
        # `TargetSpec.creature_filter` ``has_counter_kind``) / the kindless
        # "with a counter on it" (``has_counter``). Longer alternative first.
        rf"|a (?P<ctrkind{suffix}>-1/-1|\+1/\+1) counter on it"
        rf"|a (?P<ctrany{suffix}>counter) on it"
    )


#: The qualifier suffix shared by `_DESTROY_CREATURE_FILTER_RE`/
#: `_EXILE_CREATURE_FILTER_RE` — appended right after "target creature". The
#: trailing group is an optional second " and [with] <clause>" — only two
#: clauses (the real-card ceiling found so far); a third would need a third
#: suffixed group set.
_CREATURE_FILTER_SUFFIX = (
    rf"with (?:{_creature_filter_clause('')})"
    rf"(?: and (?:with )?(?:{_creature_filter_clause('2')}))?"
)


#: PAR-128: the controller scope on a quality-filtered creature target, on
#: either side of the filter ("target creature an opponent controls with power
#: 2 or less", "target creature with flying an opponent controls"). Used by the
#: rows that read `_scoped_creature_kind`; the can't-be-blocked row keeps the
#: bare suffix.
_CREATURE_FILTER_SCOPED = (
    rf"(?P<scope_pre>{NOT_YOU_TAIL})? {_CREATURE_FILTER_SUFFIX}(?P<scope_post>{NOT_YOU_TAIL})?"
)


def _scoped_creature_kind(m: re.Match[str]) -> Optional[str]:
    """The creature target kind a `_CREATURE_FILTER_SCOPED` match names, or
    ``None`` when the scope is written on both sides of the filter."""
    groups = m.groupdict()
    pre, post = groups.get("scope_pre"), groups.get("scope_post")
    if pre and post:
        return None
    return "creature_you_dont_control" if pre or post else "creature"


def _creature_quality_filter_clause(groups: dict, suffix: str) -> Optional[dict]:
    if groups.get(f"pwr{suffix}"):
        n = int(groups[f"pwr{suffix}"])
        return {"min_power": n} if groups[f"pwr_cmp{suffix}"] == "greater" else {"max_power": n}
    if groups.get(f"tough{suffix}"):
        n = int(groups[f"tough{suffix}"])
        return {"min_toughness": n} if groups[f"tough_cmp{suffix}"] == "greater" else {"max_toughness": n}
    if groups.get(f"kw{suffix}"):
        return {"keyword": _CREATURE_FILTER_KEYWORD_WORDS[groups[f"kw{suffix}"]]}
    if groups.get(f"ctrkind{suffix}"):
        return {"has_counter_kind": groups[f"ctrkind{suffix}"]}
    if groups.get(f"ctrany{suffix}"):
        return {"has_counter": True}
    return None


def _creature_quality_filter(m: re.Match[str]) -> Optional[dict]:
    groups = m.groupdict()
    first = _creature_quality_filter_clause(groups, "")
    if first is None:
        return None
    second = _creature_quality_filter_clause(groups, "2")
    if second is None:
        return first
    return {**first, **second}


def _quality_filter_builder(effect_type: str):
    """`_destroy_creature_filter`/`_exile_creature_filter`'s shared body —
    they differ only in which `EffectSpec` type the resolved creature-quality
    filter (power/toughness/keyword) attaches to."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        filt = _creature_quality_filter(m)
        kind = _scoped_creature_kind(m)
        if filt is None or kind is None:
            return None
        return [EffectSpec(effect_type, {"target_kind": kind, "creature_filter": filt})]

    return build


_destroy_creature_filter = _quality_filter_builder("destroy")
_exile_creature_filter = _quality_filter_builder("exile")

#: PAR-104: "destroy|exile [up to 1] target artifact, enchantment, or creature with flying / power 4 or greater"
#: (Mutant Chain Reaction, Spider Food, Broken Wings, Return to the Earth, Shoot Down, Exorcise, Make Your Move,
#: Vivien Reid's -3, …) — the three-type pool with the quality on its *creature* members only
#: (`TargetFrame.creature_filter_creatures_only`: an artifact or enchantment needs no flying).
_ARTIFACT_ENCHANTMENT_OR_CREATURE_FILTER_RE = _c(
    rf"(?P<verb>destroy|exile) (?P<up_to>up to 1 )?target artifact, enchantment, or creature {_CREATURE_FILTER_SUFFIX}"
)


def _artifact_enchantment_or_creature_filter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    filt = _creature_quality_filter(m)
    if filt is None:
        return None
    params: dict = {"target_kind": "artifact_creature_or_enchantment", "creature_filter": filt}
    if m.group("up_to"):
        params["optional"] = True
    return [EffectSpec(m.group("verb"), params)]


#: "~ deals N damage to target creature with flying" / "…with power 4 or
#: greater" (RULE 115/601.2c power/toughness/keyword quality filter on a
#: *damage* target — the sibling of `_destroy_creature_filter`/
#: `_exile_creature_filter`, ~13 SOLO: Leaf Arrow / Pierce the Sky /
#: Shredding Winds / Collision // Colossus / Centaur Archer / Grapeshot
#: Catapult / …). Shares `_CREATURE_FILTER_SUFFIX` and
#: `_creature_quality_filter` with them; only the leading subject-word
#: prefix (a triggered/activated body's own "~"/"it"/"this creature")
#: differs, mirrored from the plain `_damage` row's own regex. Registered
#: before the plain `damage` handler for the same "strict superset of
#: 'target creature'" reason `destroy_creature_filter` sits before
#: `destroy`. Amount is a bare digit here (no {X} form has surfaced with a
#: quality filter); `optional` isn't read since this phrasing has no
#: "up to one target creature with flying" card.
_DAMAGE_CREATURE_FILTER_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}"
    rf"deals? {NUMBER} damage to target creature{_CREATURE_FILTER_SCOPED}"
)


def _damage_creature_filter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    filt = _creature_quality_filter(m)
    kind = _scoped_creature_kind(m)
    if filt is None or kind is None:
        return None
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "target_kind": kind, "creature_filter": filt,
    })]


#: "destroy target non<word> creature[, optionally 'It can't be
#: regenerated.']" (RULE 105's colour-hoser *negated* adjective form,
#: Doom Blade/Dark Banishing/Cast Down-shaped — the single most repeated
#: removal template in the cache). ``neg`` covers the five colour words
#: (`combat.matches_object_filter`'s new ``without_color``) plus
#: "artifact" (its pre-existing ``without_card_type`` — Go for the Throat's
#: own filter shape, previously only reachable by hand-authoring since
#: nothing recognized this phrasing from oracle text).
_NEG_CREATURE_FILTER_WORDS: dict[str, tuple[str, str]] = {
    "black": ("without_color", "B"), "blue": ("without_color", "U"),
    "white": ("without_color", "W"), "red": ("without_color", "R"),
    "green": ("without_color", "G"),
    "artifact": ("without_card_type", "artifact"),
}
_DESTROY_NON_CREATURE_RE = _c(
    rf"destroy target non(?P<neg>{'|'.join(_NEG_CREATURE_FILTER_WORDS)})"
    rf"(?:, non(?P<second_neg>{'|'.join(_NEG_CREATURE_FILTER_WORDS)}))? creature"
    rf"(?P<that_player>{THAT_PLAYER_TAIL})?"
    r"(?P<no_regen>\. it can'?t be regenerated)?"
)


def _destroy_non_creature(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    key, value = _NEG_CREATURE_FILTER_WORDS[m.group("neg")]
    # PAR-130: "… that player controls" (Tooth Collector-shaped heads) —
    # `gate._that_player_antecedent_ok` checks the trigger names that player.
    kind = "creature_that_player_controls" if m.group("that_player") else "creature"
    params: dict = {"target_kind": kind, "creature_filter": {key: value}}
    # Terror/Shriekmaw's two independent negatives ("nonartifact,
    # nonblack") compose two already-supported target filters.  Do not accept
    # a duplicate filter key yet: no real card needs e.g. two colors here,
    # and silently choosing one would mis-model that future wording.
    if m.group("second_neg") is not None:
        second_key, second_value = _NEG_CREATURE_FILTER_WORDS[m.group("second_neg")]
        if second_key == key:
            return None
        params["creature_filter"][second_key] = second_value
    if m.group("no_regen"):
        params["can_be_regenerated"] = False
    return [EffectSpec("destroy", params)]


#: "destroy target [color] creature/permanent/artifact/enchantment/land"
#: (RULE 105's colour-hoser adjective form, Red Elemental Blast-shaped) — a
#: small dedicated noun list rather than a color slot spliced into the
#: shared `TARGET` macro's fixed rows (which many other handlers reuse
#: as-is); covers the same nouns `_destroy`'s plain `TARGET`-based match
#: already accepts. Tried before the plain `destroy` handler below — with
#: no colour word present it matches identically (same `target_kind`
#: mapping), so it never changes behaviour for an uncoloured clause.
#: RULE 115.1c: each single printed permanent type maps to its own narrow
#: target kind (`targeting.legal_targets` has a dedicated
#: artifact/enchantment/land branch that still honours `_color_ok`), exactly
#: as `_destroy`'s `resolve_target_kind` route does — so "destroy target
#: artifact" (Abrade's second mode) offers only artifacts, not every
#: permanent. This row used to collapse those three to "permanent"; once the
#: plain `_destroy` handler stopped doing that, this was the one place the
#: broad-pool bug still survived.
_DESTROY_COLOR_NOUN_KINDS: dict[str, str] = {
    "creature": "creature", "permanent": "permanent", "artifact": "artifact",
    "enchantment": "enchantment", "land": "land",
}
#: A two-colour adjective list ("black or red") — `TargetSpec.colors`'
#: OR narrowing, the multi-letter sibling of the single ``color`` form
#: (Deathmark, Wallop). Only ever two colours on a real card in this shape.
_DESTROY_COLOR_ADJ_RE = _c(
    rf"destroy target "
    rf"(?:(?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) |(?P<color>{COLOR_WORD_ALT}) )?"
    rf"(?P<noun>{'|'.join(_DESTROY_COLOR_NOUN_KINDS)})"
    rf"(?: with (?P<kw>{'|'.join(_CREATURE_FILTER_KEYWORD_WORDS)}))?"
    # "…that's attacking or blocking" (Surge of Righteousness) — RULE 506.4
    # attacker / RULE 509.1 blocker status, a `creature_filter` boolean the
    # same offer-time way `attacking` already is.
    rf"(?: that'?s (?P<combat_state>attacking or blocking|attacking|blocking))?"
    + IF_COLOR_SUFFIX
)


def _destroy_color_adj(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    gd = m.groupdict()
    params: dict = {"target_kind": _DESTROY_COLOR_NOUN_KINDS[m.group("noun")]}
    if gd.get("c1") and gd.get("c2"):
        colors = _two_color_letters(m)
        if colors is None:
            return None
        params["colors"] = colors
    else:
        color = resolve_color_word(gd.get("color")) or resolve_color_word(gd.get("cond_color"))
        if color:
            params["color"] = color
    kw = gd.get("kw")
    if kw:
        if params["target_kind"] != "creature":
            return None
        params["creature_filter"] = {"keyword": _CREATURE_FILTER_KEYWORD_WORDS[kw]}
    combat_state = gd.get("combat_state")
    if combat_state:
        if params["target_kind"] != "creature":
            return None
        key = {
            "attacking or blocking": "attacking_or_blocking",
            "attacking": "attacking", "blocking": "blocking",
        }[combat_state]
        params.setdefault("creature_filter", {})[key] = True
    return [EffectSpec("destroy", params)]


def _multi_target_builder(effect_type: str, allow_spell: bool = False):
    """`_destroy_multi_target`/`_exile_multi_target`'s shared body — they
    differ only in the emitted `EffectSpec` type and whether "target spell"
    is a legal recipient (legal to exile a spell, RULE 701.20b, not to
    destroy one)."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        params = _multi_target_params(m, allow_spell=allow_spell)
        if params is None:
            return None
        return [EffectSpec(effect_type, params)]

    return build


_destroy_multi_target = _multi_target_builder("destroy")


#: RULE 601.2c mass "destroy/exile all X [with a numeric filter]" board wipe
#: (Wrath of God/Damnation/Citywide Bust-shaped) — untargeted, the same
#: `selector` vocabulary `game/effects/core.py`'s `DestroyEffect`/`ExileEffect`
#: already support (previously only reachable via hand-authoring individual
#: cards in `card_catalogue`; this is the general oracle-text form).
#: Only the two numeric filter kinds `_mass_selector_objects` actually
#: implements are recognized here — "power N or greater" has no mass-form
#: engine support, so it's deliberately left unmatched (fail-closed) rather
#: than silently dropped.
#: Both keyed off the shared `PERMANENT_TYPE_WORDS` vocabulary
#: (`subgrammars.py`) rather than independently hand-typing the same
#: five-to-seven words twice, once per number — "destroy all nonland
#: permanents..."/"Destroy **each** nonland permanent..." (Culling Ritual,
#: MEC-40) both reach the same "all_nonland_permanents" selector
#: (`_mass_selector_objects`, built for `_return_all_nonland`'s bounce
#: sibling) this way for free.
_MASS_DESTROY_NOUNS: dict[str, str] = {
    pluralize_permanent_type(w): all_permanent_type_selector(w) for w in PERMANENT_TYPE_WORDS
}
#: "Destroy **each** artifact with mana value X or less." (Meltdown) —
#: the singular-noun/"each" phrasing of the same mass wipe, alongside the
#: far more common plural-noun/"all" one above; same selector targets, just
#: matched against a singular noun word.
_MASS_DESTROY_NOUNS_SINGULAR: dict[str, str] = {
    w: all_permanent_type_selector(w) for w in PERMANENT_TYPE_WORDS
}
#: The mana-value bound's own magnitude accepts ``x`` (Meltdown's own
#: "with mana value X or less", X being this spell's announced {X}) as well
#: as a literal digit — `_mass_destroy_filter_dict` carries the ``"x"``
#: sentinel straight into `DestroyEffect.filter`'s ``max_mana_value``/
#: ``min_mana_value`` key, which `RulesEngine._substitute_x` now knows how
#: to walk into (a plain digit bound like Damnation's own "mana value 3 or
#: less" never reaches this branch at all).
_MASS_DESTROY_FILTER = (
    r"(?: with (?:mana value (?P<mv>\d+|x) or (?P<mv_cmp>greater|less)"
    r"|toughness (?P<tough>\d+) or greater"
    r"|power (?P<power>\d+) or (?P<power_cmp>greater|less)"
    # PAR-74: "destroy all permanents with that spell's mana value."
    # (Celestial Kirin) — the exact-match sibling of the ``mv``/``mv_cmp``
    # bound above, reading the firing SPELL_CAST event's own mana value
    # (`_mass_selector_objects`'s new ``mana_value_from_trigger_event`` key).
    r"|(?P<trigger_mv>that spell'?s mana value)))?"
)


def _mass_destroy_filter_dict(m: re.Match[str]) -> Optional[dict]:
    groups = m.groupdict()
    filt: dict = {}
    if groups.get("mv"):
        n: Any = int(groups["mv"]) if groups["mv"] != "x" else "x"
        filt["max_mana_value" if groups["mv_cmp"] == "less" else "min_mana_value"] = n
    if groups.get("tough"):
        filt["min_toughness"] = int(groups["tough"])
    if groups.get("power"):
        n = int(groups["power"])
        filt["max_power" if groups["power_cmp"] == "less" else "min_power"] = n
    if groups.get("trigger_mv"):
        filt["mana_value_from_trigger_event"] = True
    return filt or None


_DESTROY_ALL_RE = _c(
    rf"destroy (?:all (?P<noun>{'|'.join(_MASS_DESTROY_NOUNS)})"
    rf"|each (?P<noun_sg>{'|'.join(_MASS_DESTROY_NOUNS_SINGULAR)}))"
    rf"(?P<opp> your opponents control)?{_MASS_DESTROY_FILTER}"
)

#: "Destroy all enchantments **your opponents control**." (Spring Cleaning)
#: — the opponent-scoped `_mass_selector_objects` sibling exists only for
#: artifacts/enchantments so far (no card needs "destroy all lands your
#: opponents control" &c. yet), so an ``opp`` scope on any other noun
#: fails closed.
_DESTROY_ALL_OPP_SELECTORS = {
    "all_enchantments": "opponents_enchantments",
    "all_artifacts": "opponents_artifacts",
    # PAR-128: "destroy all creatures your opponents control" (Dread Cacodemon) —
    # `opponents_creatures` already served Llawan's bounce.
    "all_creatures": "opponents_creatures",
}


def _destroy_all(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    noun = m.groupdict().get("noun")
    selector = _MASS_DESTROY_NOUNS[noun] if noun else _MASS_DESTROY_NOUNS_SINGULAR[m.group("noun_sg")]
    if m.groupdict().get("opp"):
        selector = _DESTROY_ALL_OPP_SELECTORS.get(selector)
        if selector is None:
            return None
    params: dict = {"selector": selector}
    filt = _mass_destroy_filter_dict(m)
    if filt:
        params["filter"] = filt
    return [EffectSpec("destroy", params)]


#: The "They can't be regenerated." tail (Wrath of God's own trailing
#: sentence) as one combined whole-body match — `parse_effect_body` tries
#: the *unsplit* body first, so this must span both sentences itself; the
#: plain `_destroy_all` above only ever sees this body with the tail still
#: attached (fullmatch fails) and so correctly declines it, falling through
#: to this row instead.
_DESTROY_ALL_NO_REGEN_RE = _c(
    rf"destroy all (?P<noun>{'|'.join(_MASS_DESTROY_NOUNS)}){_MASS_DESTROY_FILTER}"
    rf"\. they can'?t be regenerated"
)


def _destroy_all_no_regen(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "selector": _MASS_DESTROY_NOUNS[m.group("noun")],
        "can_be_regenerated": False,
    }
    filt = _mass_destroy_filter_dict(m)
    if filt:
        params["filter"] = filt
    return [EffectSpec("destroy", params)]


#: "Destroy all other creatures." / "…all creatures other than ~" / "…all
#: creatures except [for] ~" — a self-excluding mass wipe (RULE 400's
#: "other"), reaching the new `all_other_creatures` /
#: `other_creatures_you_control` (`effects._mass_selector_objects`)
#: selectors. Whole-body match (both sentences, like
#: `_DESTROY_ALL_NO_REGEN_RE`) so an optional "they/those creatures can't
#: be regenerated" tail is claimed here rather than fail-closing the split.
#: Novablast Wurm, Mageta the Lion, Magister of Worth's vote branch.
_DESTROY_ALL_OTHER_RE = _c(
    r"destroy all (?:other creatures(?P<you_control> you control)?"
    r"|creatures (?:other than|except(?: for)?) ~)"
    r"(?P<no_regen>\.? (?:those creatures|they) can'?t be regenerated)?"
)


def _destroy_all_other(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "selector": "other_creatures_you_control" if m.group("you_control")
        else "all_other_creatures",
    }
    if m.group("no_regen"):
        params["can_be_regenerated"] = False
    return [EffectSpec("destroy", params)]


_EXILE_ALL_RE = _c(rf"exile all (?P<noun>{'|'.join(_MASS_DESTROY_NOUNS)})")


def _exile_all(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile", {"selector": _MASS_DESTROY_NOUNS[m.group("noun")]})]


#: "destroy/exile all `<group>`" / "…each `<group>`" (PAR-128) — the general mass form: the group
#: is whatever the shared noun-phrase grammar reads (`parse_count_phrase`), carried as
#: `DestroyEffect.group` / `ExileEffect.group`. After the named-selector rows above, so their
#: closed vocabulary (and its numeric filters) keeps winning.
_MASS_GROUP_RE = _c(
    r"(?P<verb>destroy|exile) (?P<quant>all|each) (?P<group>[a-z0-9' ,/+-]+?)"
    r"(?P<no_regen>\.? (?:they|those [a-z ]+) can'?t be regenerated)?"
)
_MASS_GROUP_REFUSED_WORDS = (
    "target", "that player", "other than", "except", "chosen", "blocking", "blocked", "graveyard",
    "hand", "library", "exile", "sacrificed", "this way", "named",
)


def _mass_group_params(text: str, quant: str) -> Optional[dict]:
    """``{"group", "group_player"?}`` for a mass verb's "all/each `<group>`" object, or ``None``."""
    from .count_phrase import parse_count_phrase

    group_player = None
    for tail, who in _DAMAGE_GROUP_PLAYER_TAILS.items():
        if text.endswith(tail):
            text, group_player = text[: -len(tail)], who
            break
    if any(word in text for word in _MASS_GROUP_REFUSED_WORDS):
        return None
    if quant == "each":
        text = _SINGULAR_GROUP_HEADS.sub(r"\1s", text)
    group = parse_count_phrase(text)
    if group is None or group.get("zone") != "battlefield":
        return None
    params: dict = {"group": group}
    if group_player is not None:
        # The group is that player's own: written `of: "you"`, evaluated for them.
        if group.get("of") != "any":
            return None
        params["group"] = {**group, "of": "you"}
        params["group_player"] = group_player
    return params


def _mass_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _mass_group_params(m.group("group"), m.group("quant"))
    if params is None:
        return None
    if m.group("no_regen"):
        if m.group("verb") != "destroy":
            return None
        params["can_be_regenerated"] = False
    return [EffectSpec(m.group("verb"), params)]


#: "return all creatures to their owners' hands" / "return each other creature you control to
#: its owner's hand" (Evacuation, Denizen of the Deep — PAR-128): `ReturnToHandEffect.group`.
_RETURN_GROUP_RE = _c(
    r"return (?P<quant>all|each) (?P<group>[a-z0-9' ,/+-]+?) to (?:their owners'?|its owner'?s?) hands?"
)


def _return_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _mass_group_params(m.group("group"), m.group("quant"))
    return None if params is None else [EffectSpec("return_to_hand", params)]


#: "put all creatures on the bottom of their owners' libraries" (Terminus, Hallowed Burial) — `ReturnToLibraryEffect.group`.
_PUT_GROUP_ON_BOTTOM_RE = _c(
    r"put (?P<quant>all|each) (?P<group>[a-z0-9' ,/+-]+?) on the bottom of (?:their owners'?|its owner'?s?) librar(?:y|ies)"
)


def _put_group_on_bottom(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _mass_group_params(m.group("group"), m.group("quant"))
    if params is None or "group_player" in params:  # a "…target player controls" group needs a target; not built
        return None
    return [EffectSpec("return_to_library", {**params, "position": "bottom"})]


def _regenerate(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent")):
        return None
    return [EffectSpec("regenerate", {"target_kind": kind})]


def _regenerate_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("regenerate", {"target_kind": None})]


#: "regenerate enchanted creature" (RULE 701.16 / 303 — an Aura's own
#: activated ability regenerating its host: Regeneration / Gaea's Embrace /
#: Blessing of Leeches / Dark Privilege). No RULE 115 target — the host is
#: `RegenerateEffect`'s existing ``target_kind="attached_permanent"`` mode,
#: the same "act on whatever this Aura is attached to" resolution
#: `PumpEffect`/`GrantKeywordEffect`'s attached forms use.
_REGENERATE_ATTACHED_RE = _c(r"regenerate (?:enchanted|equipped) creature")


def _regenerate_attached(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("regenerate", {"target_kind": "attached_permanent"})]


#: "Regenerate another target Elf." (Ezuri, Renegade Leader/Mad Auntie/
#: Baron Sengir-shaped) — a creature-subtype-filtered target. "another" is
#: cosmetic here: the plain ``"creature"`` target kind's own `legal_targets`
#: branch already excludes the ability's own source unconditionally (every
#: real card in this shape is an activated ability on a creature of the
#: named subtype, so it would otherwise be offered as its own legal
#: target) — the same reason a bare "target creature" ability doesn't need
#: an explicit "other" qualifier to stay off itself in this engine.
_REGENERATE_ANOTHER_TARGET_RE = _c(r"regenerate another target (?P<subtype>[a-z]+)")
_REGENERATE_TARGET_SUBTYPE_RE = _c(r"regenerate target (?P<subtype>[a-z]+)")


def _regenerate_another_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("regenerate", {
        "target_kind": "creature",
        "creature_filter": {"subtype": m.group("subtype").capitalize()},
    })]


def _regenerate_target_subtype(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subtype = m.group("subtype").lower()
    # The broader subtype grammar is tried before the ordinary target row;
    # main type nouns must fall through to that row, never become a fictional
    # creature subtype such as "Creature".
    if subtype in {"creature", "permanent"}:
        return None
    return [EffectSpec("regenerate", {
        "target_kind": "creature",
        "creature_filter": {"subtype": subtype.capitalize()},
    })]


def _counter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "counter target spell" / "… target noncreature spell" / "… target
    # instant or sorcery spell" / "… target spell with mana value N" — the
    # filter is extracted by the dedicated `SPELL_TARGET` companion grammar
    # (RULE 601.2c/115), not the generic TARGET rows (a countered spell's
    # "kind" is always "spell"; only *which* spells vary). "unless its
    # controller pays <cost>" (RULE 601 "Mana Leak" template) is an optional
    # tail on the same clause, independent of the filter.
    filt = resolve_spell_filter(m.group("target"))
    if filt is None:
        return None
    params: dict = dict(filt)
    if m.groupdict().get("cost"):
        # "pays twice {X}" (Thassa's Intervention) is two X symbols: `ManaCost.with_x` fills both.
        params["unless_pays"] = "{x}{x}" if m.group("cost") == "twice {x}" else m.group("cost")
        # "…pays {1} plus an additional {1} for each creature in your
        # party." (Concerted Defense, PAR-72) — `CounterSpellEffect.
        # unless_pays_extra_selector` adds one more generic to the fixed
        # base cost per point of `creatures_in_your_party` at resolution
        # time, read for the counter spell's own caster.
        if m.groupdict().get("party_tax"):
            params["unless_pays_extra_selector"] = "creatures_in_your_party"
        # "…unless its controller pays {1} for each card in your graveyard." (Circular Logic) — a
        # zero base plus one generic per card, the same extra-selector mechanism.
        if m.groupdict().get("graveyard_tax"):
            if m.group("cost") != "{1}":
                return None
            params["unless_pays"] = "{0}"
            params["unless_pays_extra_selector"] = "cards_in_your_graveyard"
    cond_color = resolve_color_word(m.groupdict().get("cond_color"))
    if cond_color:
        params["color"] = cond_color
    # "…unless its controller pays {4}. **If they do**, you incubate 2."
    # (Assimilate Essence) — a reflexive follow-up on the branch where the
    # target's controller pays (`CounterSpellEffect.on_pay_effect_specs`).
    # Only meaningful after an "unless … pays" cost; the sub-body is parsed
    # recursively and must fully claim, else fail closed.
    reflexive = m.groupdict().get("reflexive")
    if reflexive:
        if not m.groupdict().get("cost"):
            return None
        from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

        sub = parse_effect_body(reflexive)
        if not sub:
            return None
        params["on_pay_effect_specs"] = [s.to_dict() for s in sub]
    return [EffectSpec("counter", params)]


#: "Until end of turn, target creature gains '`<cost>`: `<effect>`.'"
#: (Retraction Helix-shaped, ~23 cache-wide cards on this template) — a
#: *resolve-time* grant of a full quoted ability (activated/triggered/
#: mana), unlike every other "gains `<keyword>` until end of turn" row
#: above (a bare flag keyword, no quotes). Reuses `static_handlers.
#: _quoted_ability_grant_effects` (the Aura/Equipment quoted-grant parser,
#: already general over all three ability kinds) wrapped in `GrantUntil
#: Effect`'s existing ``duration="end_of_turn"`` resolve-time shape
#: instead of a standing layer-6 static.
_GRANT_QUOTED_ABILITY_UNTIL_EOT_RE = _c(
    r"until end of turn, target creature gains \"(?P<inner>.+)\""
)


def _grant_quoted_ability_until_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .static_handlers import _quoted_ability_grant_effects  # local: avoid a module cycle

    grant = _quoted_ability_grant_effects(m.group("inner"))
    if grant is None:
        return None
    return [EffectSpec("grant_until", {
        "static": {"type": grant.type, "params": grant.params},
        "duration": "end_of_turn",
        "target_kind": "creature",
    })]


def _cant_be_countered(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("cant_be_countered", {})]


#: RULE 119.3's "can't gain life this turn" rider — "your opponents"
#: (Roiling Vortex's activated-ability effect) or "players" (Skullcrack /
#: Call In a Professional / Rain of Gore — a burn spell's own rider). The
#: bare, *permanent* "Players can't gain life." is a standing static
#: (`static_handlers._PLAYERS_CANT_GAIN_LIFE_RE` → `prevent_all_life_gain`).
_CANT_GAIN_LIFE_RE = _c(r"(?P<who>your opponents|players) can'?t gain life this turn")


def _cant_gain_life(m: re.Match[str]) -> list[EffectSpec]:
    who = "all" if m.group("who").lower() == "players" else "opponents"
    return [EffectSpec("prevent_life_gain", {"recipient": who})]


def _change_target(m: re.Match[str]) -> list[EffectSpec]:
    # "…spell or ability…" always goes through `ChangeTargetEffect`'s
    # ``spell_or_ability`` branch (ENG-26's union stack-item lookup) rather
    # than folding "with a single target" into a spell-only filter — the
    # engine's own single-existing-target MVP limit already applies inside
    # that branch regardless of what's printed (see the effect's own
    # docstring), so the printed "with a single target" here is redundant
    # with, not narrower than, that limit.
    if m.group("kind") == "spell or ability":
        return [EffectSpec("change_target", {"spell_or_ability": True})]
    return [EffectSpec("change_target", {"single_target": True})]


#: PAR-71: "[you may ][have ]target player mill X cards, where X is that
#: spell's mana value." (Cloudhoof Kirin's spirit-or-arcane cast trigger) —
#: `MillEffect.count_from_trigger_event`'s ``mana_value`` reading, the same
#: `SPELL_CAST` event field `_pump_mana_value`/`_add_counters_spell_mv`
#: already use. RULE 601.2c's "have [player] mill" phrasing (rather than
#: bare "target player mills") doesn't change who does the milling —
#: `MillEffect` already only tracks the milled player, not who "had" it
#: happen — so the leading "have " is just consumed and dropped.
_MILL_SPELL_MV_RE = _c(
    r"(?:have )?target (?P<who>player|opponent) mills? x cards?, where x is that spell'?s mana value"
)


def _mill_spell_mv(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {"target_kind": "player", "count_from_trigger_event": "mana_value"})]


#: PAR-82: "target player mills X cards, where X is ~'s power/toughness."
#: (Phenax, God of Deception's own granted ability) — `MillEffect.
#: count_selector`'s already-shipped ``"source_power"``/``"source_
#: toughness"`` reading (`continuous.count_selector`, evaluated against
#: this effect's own bound ``source`` — the granted-to creature, once
#: regranted per RULE 613.7f); a parser-recognition gap only.
_MILL_SOURCE_PT_RE = _c(
    r"target (?P<who>player|opponent) mills? x cards?, where x is ~'?s (?P<pt>power|toughness)"
)


def _mill_source_pt(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {
        "target_kind": "player", "count_selector": f"source_{m.group('pt')}",
    })]


#: "target player mills half their library, rounded down." (Cut Your Losses, Traumatize, Kitsune's Technique,
#: Fleet Swallower) — `MillEffect.half`.
_MILL_HALF_RE = _c(
    r"target (?P<who>player|opponent) mills half their library, rounded (?P<dir>down|up)"
)


def _mill_half(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {
        "target_kind": "opponent" if m.group("who") == "opponent" else "player", "half": m.group("dir"),
    })]


#: "defending player mills half their library, rounded up." (Terisian Mindbreaker) — `MillEffect`'s ``defending_player``
#: selector with the same ``half`` count.
_MILL_HALF_DEFENDING_RE = _c(r"defending player mills half their library, rounded (?P<dir>down|up)")


def _mill_half_defending(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {"selector": "defending_player", "half": m.group("dir")})]


def _mill(m: re.Match[str]) -> list[EffectSpec]:
    # "you mill N" / bare "mill N" → self; "target player/opponent mills N" → targeted.
    who = (m.groupdict().get("who") or "").strip()
    count_word = m.group("n").lower()
    params: dict = {"count": "twice_x" if count_word == "twice x" else 1 if count_word == "a" else int(count_word)}
    if who in ("target player", "target opponent"):
        params["target_kind"] = "player"
    return [EffectSpec("mill", params)]


def _exile(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    # ``nonland_permanent`` ("exile target nonland permanent" — Excise the
    # Imperfect) is a real `targeting.legal_targets` kind (RULE 115.1c),
    # just never previously reachable from the plain exile handler.
    if not target_kind_allowed(kind, (
        "creature", "attacking_or_blocking_creature", "permanent", "nonland_permanent", *_SINGLE_TYPE_PERMANENT_KINDS
    )):
        return None
    params: dict = {"target_kind": kind, **_optional_param(m)}
    # See `_destroy`'s own comment: "exile target tapped creature" needs the
    # same qualifier `resolve_target_kind` alone discards.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("exile", params)]


#: "{1}{R}{G}, {T}: Exile ~ and target creature without flying that's attacking you." (Hunting Kavu,
#: Giant Trap Door Spider, Mangara of Corondor) — the source and one RULE 115 target, both exiled.
_EXILE_SELF_AND_TARGET_RE = _c(rf"exile ~ and {TARGET}")


def _exile_self_and_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    target = _exile(m)
    return None if target is None else [EffectSpec("exile", {"target_kind": None}), *target]


#: "Whenever this creature deals combat damage to a creature, exile that
#: creature." (Kaldra Compleat) — this is not a second RULE 115 target:
#: ``that creature`` is the recipient recorded on the firing DAMAGE event.
#: `ExileEffect`'s trigger-subject mode reads ``target_id`` for such an
#: event and falls back to ``instance_id`` for object-subject triggers.
_EXILE_TRIGGER_REFERENT_RE = _c(r"exile that creature")


def _exile_trigger_referent(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile", {"target_kind": "trigger_subject"})]


_exile_multi_target = _multi_target_builder("exile", allow_spell=True)


#: The target kinds "tap/untap target X" accepts — the plain permanent
#: types plus the controller-scoped creature kinds ("tap target creature
#: **an opponent controls**", Chillbringer/Berg Strider &c.; `legal_targets`
#: resolves all three).
_TAP_TARGET_KINDS = (
    "creature", "permanent", "legendary_permanent", "forest",
    "creature_you_control", "creature_you_dont_control", "other_creature_you_control",
    "werewolf_creature",
    "creature_defending_player_controls",
    "permanent_you_control", "permanent_you_dont_control",
    *_SINGLE_TYPE_PERMANENT_KINDS,
)


def _tap(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _TAP_TARGET_KINDS):
        return None
    untap = m.group("verb").lower() == "untap"
    params: dict = {"target_kind": kind, "untap": untap, **_optional_param(m)}
    # See `_destroy`'s own comment. "Tap target untapped creature"/"tap
    # target tapped creature" is a real, printed shape (Backlash, Ana
    # Battlemage's kicker mode) that needs the qualifier too — a "would be
    # a no-op either way" case for tap specifically only when the two words
    # happen to agree with the verb, which they usually don't.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("tap", params)]


#: "tap target `<c1>` or `<c2>` creature[ an opponent controls]"
#: (Tidebinder Mage) — `TargetSpec.colors`' OR narrowing, the
#: `_pump_target_two_color` / `_destroy_color_adj` idiom (the shared
#: `TARGET` macro carries no colour slot). Tidebinder's "…doesn't untap
#: for as long as you control ~" tail rides the pronoun as its own
#: `previous_subject` clause, so only the tap itself is this row's job.
_TAP_TWO_COLOR_RE = _c(
    rf"(?P<verb>tap|untap) target (?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) "
    rf"creature(?P<yc> (?:an opponent controls|you don't control))?"
)


def _tap_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = _two_color_letters(m)
    if colors is None:
        return None
    kind = "creature_you_dont_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("tap", {
        "target_kind": kind, "untap": m.group("verb").lower() == "untap", "colors": colors,
    })]


#: "tap N target creatures" / "untap up to two target lands" (RULE 115.1a
#: generalized to N>=2, Snap-shaped — `TapEffect.count` already supported
#: this; only the grammar was missing). Restricted to the same
#: creature/permanent kinds the singular `_tap` handler allows.
def _tap_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None or not target_kind_allowed(
        params["target_kind"], ("creature", "permanent", *_SINGLE_TYPE_PERMANENT_KINDS),
    ):
        return None
    untap = m.group("verb").lower() == "untap"
    params["untap"] = untap
    return [EffectSpec("tap", params)]


#: "Tap one or two target creatures without horsemanship." (MEC-87, Broken
#: Dam-shaped) — `_tap_multi_target`'s own sibling narrowed by a creature
#: keyword filter (`TapEffect.creature_filter`, the same field `destroy`/
#: `damage`'s own single-target filter siblings already use). Restricted to
#: the bare "target creatures" phrase — the only plural row this filter
#: family is printed against on a real card so far.
_TAP_MULTI_TARGET_KEYWORD_FILTER_RE = _c(
    rf"(?P<verb>tap|untap) {_MULTI_TARGET_QUANTIFIER}(?P<target>target creatures) "
    rf"(?P<neg>with|without) (?P<kw>{'|'.join(_CREATURE_FILTER_KEYWORD_WORDS)})"
)


def _tap_multi_target_keyword_filter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None or params["target_kind"] != "creature":
        return None
    key = "without_keyword" if m.group("neg").lower() == "without" else "keyword"
    params["creature_filter"] = {key: _CREATURE_FILTER_KEYWORD_WORDS[m.group("kw").lower()]}
    params["untap"] = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", params)]


def _tap_selector(m: re.Match[str]) -> list[EffectSpec]:
    # "untap all creatures you control" (Village Bell-Ringer's ETB) /
    # "untap each other creature you control" (Copperhorn Scout's own
    # attack trigger) — an untargeted mass effect, `game/effects/core.py`'s
    # `TapEffect.selector`, the same shape `_add_counters_selector` uses
    # for a mass counter effect.
    untap = m.group("verb").lower() == "untap"
    other = m.groupdict().get("other_all") or m.groupdict().get("other_each")
    selector = "other_creatures_you_control" if other else "creatures_you_control"
    return [EffectSpec("tap", {"selector": selector, "untap": untap})]


#: "tap all creatures target opponent controls" / "tap all lands target player
#: controls" (Tempest Caller, Gulf Squid, Mana Short — PAR-128): the mass group
#: scoped to a chosen player. The selector is written `of: "you"` and
#: `TapEffect.selector_player` evaluates it for that player.
_TAP_ALL_PLAYER_GROUP_RE = _c(
    r"(?P<verb>tap|untap) all (?P<group>[a-z' -]+?) "
    r"(?P<who>target player|target opponent|defending player|that player) controls"
)
_TAP_ALL_PLAYER_SCOPES: dict[str, str] = {
    "target player": "player", "target opponent": "opponent",
    "defending player": "defending", "that player": "event_player",
}


def _tap_all_player_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .count_phrase import parse_count_phrase

    selector = parse_count_phrase(m.group("group"))
    if selector is None or selector.get("zone") != "battlefield" or selector.get("of") != "any":
        return None
    return [EffectSpec("tap", {
        "selector": {**selector, "of": "you"},
        "selector_player": _TAP_ALL_PLAYER_SCOPES[m.group("who")],
        "untap": m.group("verb").lower() == "untap",
    })]


def _tap_all_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .count_phrase import parse_count_phrase

    group = m.group("group")
    if "target" in group or "that player" in group:
        return None
    selector = parse_count_phrase(group)
    if selector is None or selector.get("zone") != "battlefield":
        return None
    return [EffectSpec("tap", {"selector": selector, "untap": m.group("verb").lower() == "untap"})]


#: MEC-28: "untap all attacking creatures" (Karlach, Fury of Avernus) /
#: "untap each attacking creature" (Hexplate Wallbreaker's Equipment ETB) —
#: `TapEffect.selector`'s `"attacking_creatures"` mode, unscoped by
#: controller (`continuous.group_selector_objects`'s existing branch, the
#: same one Motivated Pony's anthem already reads).
def _tap_attacking_creatures(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"selector": "attacking_creatures", "untap": untap})]


#: "Untap it and all Samurai you control." (Godo, Bandit Warlord's own
#: attack trigger) — the compound "self **and** a subtype group" untap
#: `_tap_self`/`_tap_selector` each only cover one half of; two ordinary
#: `tap` `EffectSpec`s in sequence (the ability's own effect list, RULE
#: 608.2 printed order) rather than a single effect trying to express both
#: recipients at once.
_TAP_SELF_AND_SUBTYPE_RE = _c(
    r"(?P<verb>tap|untap) it and all (?P<subtype>[a-z]+) you control"
)


def _tap_self_and_subtype(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    subtype = m.group("subtype").rstrip("s")
    return [
        EffectSpec("tap", {"target_kind": None, "untap": untap}),
        EffectSpec("tap", {"selector": f"creatures_you_control_of_type_{subtype}", "untap": untap}),
    ]


#: "Untap this creature" (Devoted Druid's counter-cost untap ability) / "tap
#: ~" — the *self* form, no RULE 115 target at all (`target_kind=None` makes
#: `TapEffect` act on its own source, mirroring `AttachEffect`'s ``~``/"it"
#: self-reference).
_SELF_SUBJECT = (
    r"(?:~|it|this permanent|this creature|this artifact|this land|this enchantment)"
)


def _tap_self(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": None, "untap": untap})]


#: MEC-28: "untap that creature" (Finest Hour's own attacks-alone trigger) —
#: the `group_subject_only` sibling of `_tap_self`'s bare "it"/"~" pronoun:
#: "that creature" is genuinely ambiguous (it means *whichever creature
#: matched this ability's group-subject trigger condition* here, but means
#: an earlier clause's own target on `_lockdown`'s `previous_subject_only`
#: row), so it's a dedicated row rather than added to `_SELF_SUBJECT`, only
#: offered when the caller confirms the trigger really has a group subject.
#: Same output shape as `_tap_self` — `effect_binder.
#: _retarget_implicit_subject_effects` is what turns the resulting
#: ``target_kind: None`` into a live per-firing read at bind time.
_TAP_GROUP_SUBJECT_RE = _c(r"(?P<verb>tap|untap) that creature")


#: "enchanted creature"/"equipped creature"/"fortified land" — an Aura/
#: Equipment/Fortify's own activated-ability body implicitly acting on
#: whatever it's attached to (RULE 303.4/301.5), no player choice at all
#: (`TapEffect`/`PumpEffect`'s ``"attached_permanent"`` mode) — the
#: activated-ability sibling of `effect_binder._subject_condition`'s
#: ``"attached_permanent"`` *trigger*-subject concept. The same five printed
#: subject phrases `static_handlers._ATTACHED_SUBJECTS` lists — "enchanted
#: permanent"/"enchanted land" appear on real Auras that enchant something
#: other than a creature (Flood the Engine's "When ~ enters, tap enchanted
#: permanent.", Animal Boneyard).
_ATTACHED_SUBJECT = (
    r"(?:enchanted creature|equipped creature|fortified land"
    r"|enchanted permanent|enchanted land)"
)


#: "{U}: Tap enchanted creature."/"{U}: Untap enchanted creature." (Freed
#: from the Real/Pemmin's Aura-shaped Aura activated abilities).
def _tap_attached(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": "attached_permanent", "untap": untap})]


#: "Sacrifice ~."/"Sacrifice this enchantment." (Dress Down/Underworld
#: Breach-shaped standing end-step self-sac) — the self form, no player
#: choice or RULE 115 target (RULE 701.17).
def _sacrifice_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("sacrifice_self", {})]


#: "Sacrifice ~ unless you pay `<cost>`." (RULE 701.17 + an "unless"
#: payment) — the single most common upkeep-trigger body on older cards
#: (Arcades Sabboth, Breeding Pit, Child of Gaea, Chromium, Kuro; Aura
#: Flux/Coral Net grant it onto another permanent). Unlike `_sacrifice_self`
#: this is a *choice*: `SacrificeUnlessPayEffect` opens the same
#: pay-or-lose-it `pending_choice` ward uses.
#:
#: The cost is a deliberately **closed** list of shapes rather than free
#: text handed to `costs.parse_activation_cost`, because that function
#: returns a *free* cost for anything it doesn't understand — which here
#: would silently read as "pay nothing to keep it". Every excluded variant
#: is one the engine genuinely can't honour and so stays unclaimed:
#:
#: * "pay its echo cost"/"pay its upkeep cost for each age counter on it" —
#:   Echo and Cumulative Upkeep's own reminder text, a self-referential cost
#:   (and those two keywords aren't modeled at all).
#: * "pay {G} **for each** wind counter on it" (Sandstorm Ambush) — a scaled
#:   cost; `parse_activation_cost` would quietly drop the multiplier.
#: * "discard a card **at random**" — the engine's `discard` auto-picks and
#:   has no random mode, so claiming it would misrepresent the card.
#: * "discard a **`<type>`** card" (Body Snatcher's "discard a creature
#:   card") — `parse_activation_cost` returns a *free* cost for a typed
#:   discard, which would read as "pay nothing".
#: * "sacrifice **four** creatures" — `ActivationCost.sacrifice` is one
#:   permanent.
#:
#: "discard **N** cards" (a plain count — Avatar of Discord's "discard 2
#: cards", Skull of Orm) *is* included: `parse_activation_cost` reads the
#: count correctly and `_pay_player_cost` honours `cost.discard` as a
#: number.
_UNLESS_COST = (
    r"(?:pay (?:\{[^{}]+\})+"
    r"|pay \d+ life"
    r"|discard a card"
    r"|discard (?:\d+|two|three|four) cards"
    r"|sacrifice (?:a|another) (?:creature|permanent|artifact|enchantment|land))"
)
#: "`<sacrifice | destroy | tap | exile>` ~ unless you pay `<cost>`" (RULE 118.3) — one
#: row over the leading verb instead of four near-identical ones (PAR-121): the four
#: differ only in which consequence the *unpaid* branch performs, which
#: `_SELF_CONSEQUENCE_UNLESS_PAY` maps. "Pay its mana cost" is a sacrifice-only cost.
_SELF_UNLESS_PAY_RE = _c(
    rf"(?P<verb>sacrifice|destroy|tap|exile) {_SELF_SUBJECT} unless you "
    rf"(?P<cost>{_UNLESS_COST}|pay its mana cost)"
)

#: "Sacrifice this creature unless it attacked this turn." (Instill Furor)
#: is a noninteractive condition, unlike the similarly worded payment form.
_SACRIFICE_UNLESS_ATTACKED_RE = _c(
    rf"sacrifice {_SELF_SUBJECT} unless it attacked this turn"
)


def _self_unless_pay(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    verb, cost = m.group("verb"), m.group("cost")
    if verb == "sacrifice":
        return [EffectSpec("sacrifice_unless_pay", {
            "cost": "source_mana_cost" if cost == "pay its mana cost" else cost,
        })]
    if cost == "pay its mana cost":
        return None  # only the sacrifice form has this cost
    if verb == "destroy":
        return [EffectSpec("destroy_unless_pay", {"cost": cost})]
    # tap / exile: paying costs the resource and nothing happens, else the source
    # is tapped / exiled (`pay_cost_then` with the consequence in ``else_effects``).
    consequence = (
        {"type": "tap", "params": {"target_kind": None}} if verb == "tap"
        else {"type": "exile", "params": {"target_kind": None}}
    )
    return [EffectSpec("pay_cost_then", {
        "cost": cost, "effects": [], "else_effects": [consequence],
    })]


#: PAR-117: Fade Away / Killing Wave.  This is leading, unscoped
#: per-creature iteration, unlike the parser's existing trailing "for each"
#: connective.  The outer iterator snapshots every creature; the normal
#: composition runtime then pauses for each controller's individual choice.
_EACH_CREATURE_SACRIFICES_UNLESS_RE = _c(
    r"for each creature, its controller sacrifices "
    r"(?P<subject>a permanent of their choice|it) unless they "
    r"(?P<cost>pay \{1\}|pay x life)"
)


def _each_creature_sacrifices_unless(m: re.Match[str]) -> list[EffectSpec]:
    is_self = m.group("subject") == "it"
    cost: object = {"pay_life": "x"} if m.group("cost") == "pay x life" else "{1}"
    consequence = (
        {"type": "sacrifice_target", "params": {}}
        if is_self else
        {"type": "sacrifice_controller_permanent", "params": {"what": "permanent"}}
    )
    return [EffectSpec("for_each", {
        "over": {"selector": "all_creatures"},
        "effects": [{"type": "pay_cost_then", "params": {
            "cost": cost,
            "payer": "target_controller",
            "effects": [],
            "else_effects": [consequence],
        }}],
    })]


#: "This creature deals 8 damage to you unless you pay {G}{G}{G}{G}."
#: (Force of Nature / Minion of Tevesh Szat) — payment is optional at
#: resolution; declining is what performs the self-damage.
_DAMAGE_TO_YOU_UNLESS_PAY_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? {NUMBER} damage to you unless you (?P<cost>{_UNLESS_COST})"
)


def _damage_to_you_unless_pay(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pay_cost_then", {
        "cost": m.group("cost"),
        "effects": [],
        "else_effects": [{"type": "damage", "params": {
            "amount": int(m.group("n")), "selector": "controller",
        }}],
    })]


#: "you skip your draw step this turn" (Elfhame Sanctuary) is an instruction
#: that installs a one-shot player rule override, not the standing static
#: "Skip your draw step." parsed by ``static_handlers``.
_SKIP_YOUR_DRAW_STEP_THIS_TURN_RE = _c(r"you skip your draw step this turn")


def _skip_your_draw_step_this_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_step", {"step": "draw"})]


#: "`<player>` skips their next `<untap step | draw step | combat phase>`" (Fatigue, Yosei, Brine Elemental, Blinding
#: Angel, Stonehorn Dignitary, Moment of Silence): a one-shot skip installed on someone else
#: (`SkipNextStepEffect` ``target_kind`` / ``selector``). "…this turn" (Moment of Silence) is the same skip — it
#: is consumed by the first matching step still to come.
_SKIP_THEIR_NEXT_RE = _c(
    r"(?P<who>target player|target opponent|each opponent|that player) skips their next "
    r"(?P<step>untap step|draw step|combat phase)(?: this turn)?"
)
_SKIP_STEP_NAMES = {"untap step": "untap", "draw step": "draw", "combat phase": "combat"}


def _skip_their_next(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {"step": _SKIP_STEP_NAMES[m.group("step")]}
    who = m.group("who")
    if who == "target player":
        params["target_kind"] = "player"
    elif who == "target opponent":
        params["target_kind"] = "opponent"
    elif who == "each opponent":
        params["selector"] = "each_opponent"
    else:
        params["selector"] = "event_player"
    return [EffectSpec("skip_next_step", params)]


#: "Exile ~."/"Exile this card." (Teferi's Protection/Mnemonic Betrayal's
#: trailing self-exile) — the self form, `ExileEffect`'s `target_kind=None`.
def _exile_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile", {"target_kind": None})]


#: "return target creature to its owner's hand" / "return a land you control
#: to its owner's hand" (RULE 701.3) — the bounce family. ``target_kind``
#: reuses the shared `TARGET` grammar, so this claims both a genuine RULE 115
#: target and the "a land you control" controller-restricted choice the same
#: way; restricted to the shapes real bounce cards actually use.
#: ``other_creature_you_control`` (PAR-79 ninth increment — Deputy of
#: Acquittals/Jeskai Barricade's "you may return another target creature
#: you control to its owner's hand") is RULE 109.5's "another target
#: creature you control" — already whitelisted globally
#: (`ALLOWED_TARGET_KINDS`, built for Giver of Runes) and already resolved
#: by `resolve_target_kind`, just never added to this handler's own closed
#: kind list before now.
_RETURN_TO_HAND_KINDS: frozenset[str] = frozenset(
    {
        "creature", "permanent", "nonland_permanent", "nonland_permanent_you_control", "historic_permanent_you_control", "any", "creature_you_control",
        "land_you_control", "other_creature_you_control",
        # The single-type pools: "return target artifact to its owner's hand" and, plural, "return
        # X target artifacts …" (`targeting.TARGET_FRAMES`' artifact/enchantment/land).
        "artifact", "enchantment", "land",
    }
)


def _return_to_hand(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _RETURN_TO_HAND_KINDS):
        return None
    params: dict = {"target_kind": kind, **_optional_param(m)}
    # See `_destroy`'s own comment: "return target tapped creature to its
    # owner's hand" (Galestrike-shaped) needs the same qualifier.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("return_to_hand", params)]


#: RULE 601.2c mass "return all nonland permanents with mana value X or less
#: to their owners' hands." (Displacement Wave) — `ReturnToHandEffect`'s own
#: sibling of `_destroy_all`'s board wipe, reusing the exact same
#: `_MASS_DESTROY_FILTER`/`_mass_destroy_filter_dict` vocabulary (including
#: the ``"x"`` sentinel, substituted at cast time by `RulesEngine.
#: _substitute_x`, which already walks any effect's ``filter`` attribute
#: generically).
_RETURN_ALL_NONLAND_RE = _c(
    rf"return all (?P<other>other )?nonland permanents{_MASS_DESTROY_FILTER} to their owners'? hands?"
)


def _return_all_nonland(m: re.Match[str]) -> list[EffectSpec]:
    # PAR-128: RULE 109.5 "all other nonland permanents" (Kederekt Leviathan).
    params: dict = {"selector": "all_other_nonland_permanents" if m.group("other") else "all_nonland_permanents"}
    filt = _mass_destroy_filter_dict(m)
    if filt:
        params["filter"] = filt
    return [EffectSpec("return_to_hand", params)]


#: "put target creature on top of its owner's library" (RULE 701.3 — Time
#: Ebb/Griptide/Roil Spout/Vedalken Dismisser-shaped tempo bounce, 10 SOLO
#: cards, `parser_probe.py blocked`) / "…on the bottom of its owner's
#: library" (rarer — same shape, ``position="bottom"``). `ReturnToLibraryEffect`
#: is `return_to_hand`'s library-destination sibling.
#: "… library third from the top" (RULE 401.7 — God-Eternal Oketra, Enigma Sphinx, Long-Term Plans).
_NTH_FROM_TOP_WORDS = {"second": 2, "third": 3, "fourth": 4, "fifth": 5}
_NTH_FROM_TOP = r"(?P<nth>" + "|".join(_NTH_FROM_TOP_WORDS) + r") from the top"
#: Where "put … into/on … its owner's library" lands: on top, on the bottom, or Nth from the top.
_LIBRARY_PLACEMENT = (
    rf"(?:on (?:top|the (?P<pos>bottom)) of its owner's library|into (?:its owner's|your) library {_NTH_FROM_TOP})"
)


def _library_placement_params(m: re.Match[str]) -> dict:
    groups = m.groupdict()
    if groups.get("nth"):
        return {"position": "top", "depth": _NTH_FROM_TOP_WORDS[groups["nth"]]}
    return {"position": "bottom" if groups.get("pos") == "bottom" else "top"}


def _return_to_library(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    # PAR-104: the three-type pool ("put target artifact, creature, or enchantment on the bottom of its owner's
    # library" — Banishing Stroke, Banishment Decree) has its own frame; before it, it read as any permanent.
    if not target_kind_allowed(kind, _RETURN_TO_HAND_KINDS | {"artifact_creature_or_enchantment"}):
        return None
    return [
        EffectSpec(
            "return_to_library",
            {"target_kind": kind, **_library_placement_params(m), **_optional_param(m)},
        )
    ]


#: "put ~ on top of / on the bottom of its owner's library", "put it into its owner's library third from
#: the top" (self form — Fell Horseman's and Murderous Rider's dies trigger, God-Eternal Oketra, Bookwurm's
#: graveyard ability). The source may already be in the graveyard (RULE 400.7), which
#: `RulesEngine.return_to_library` handles ("from wherever it is"). The pronoun form is only offered when
#: the caller says the implicit subject is the source (`EffectHandler.self_subject_only`).
_RETURN_SELF_TO_LIBRARY_RE = _c(
    rf"put (?:~|this card)(?: from your graveyard)? {_LIBRARY_PLACEMENT}"
)
_RETURN_IT_TO_LIBRARY_RE = _c(rf"put it {_LIBRARY_PLACEMENT}")


#: "put enchanted creature into its owner's library third from the top" (Shattered Ego) — the Aura's host.
_RETURN_ATTACHED_TO_LIBRARY_RE = _c(rf"put enchanted (?:creature|permanent) {_LIBRARY_PLACEMENT}")


def _return_attached_to_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_library", {"target_kind": "attached_permanent", **_library_placement_params(m)})]


def _return_self_to_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_library", {"target_kind": None, **_library_placement_params(m)})]


#: "Put target card from a graveyard on the bottom of its owner's library."
#: (PAR-83 — Junktroller/Chrome Companion).  This is deliberately a
#: ``return_to_library`` spec rather than a shuffle: RulesEngine.
#: return_to_library already moves an object from any zone to its owner's
#: library without randomising it, and ``any_graveyard_card`` is the existing
#: RULE 115 target vocabulary for a card from any player's graveyard.
_GRAVEYARD_CARD_TO_LIBRARY_BOTTOM_RE = _c(
    r"put target card from a graveyard on the bottom of its owner's library"
)


def _graveyard_card_to_library_bottom(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_library", {
        "target_kind": "any_graveyard_card", "position": "bottom",
    })]


#: "Return ~ to its owner's hand." (RULE 701.3, self form — no RULE 115
#: target and no player choice, the bounce sibling of `_sacrifice_self`/
#: `_exile_self`). Two families of real cards, both Aura-heavy:
#: Rancor/Launch/Aspect of Mongoose's "When ~ dies, return it to its
#: owner's hand." trigger (`normalize` folds RULE 700.4's long "is put
#: into a graveyard from the battlefield" phrasing to "dies", and ``it``
#: to ``~``), and Flickering Ward/Fiery Mantle's "{W}: Return ~ to its
#: owner's hand." activated ability. Resolves against the effect's own
#: source wherever it currently is — battlefield *or* graveyard, since a
#: dies-trigger's source has already moved (RULE 400.7) by the time the
#: ability resolves and `RulesEngine.return_to_hand` moves an object from
#: whatever zone it's in.
def _return_self_to_hand(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_hand", {"target_kind": None})]


#: "return ~ and target `<c1>` or `<c2>` creature[ you control] to their
#: owner's hand" (Snow Hound) — a compound bounce: two `return_to_hand`
#: specs in printed order (RULE 608.2), the self one (`target_kind=None`)
#: then the RULE 115 colour-narrowed target. Same "two sequenced specs
#: rather than one effect expressing both recipients" idiom
#: `_tap_self_and_subtype` uses.
_RETURN_SELF_AND_TWO_COLOR_RE = _c(
    rf"return (?P<self>~|this creature) and target "
    rf"(?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) creature(?P<yc> you control)? "
    rf"to (?:its|their) owner'?s hand"
)


def _return_self_and_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = _two_color_letters(m)
    if colors is None:
        return None
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [
        EffectSpec("return_to_hand", {"target_kind": None}),
        EffectSpec("return_to_hand", {"target_kind": kind, "colors": colors}),
    ]


#: "return two target creatures to their owners' hands" (RULE 115.1a
#: generalized to N>=2) — the plural sibling of `_return_to_hand`.
def _return_to_hand_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None or not target_kind_allowed(params["target_kind"], _RETURN_TO_HAND_KINDS):
        return None
    return [EffectSpec("return_to_hand", params)]


#: "Return those creatures to their owners' hands." (PAR-1, Run Away
#: Together) — the indirect-referent sibling of `_return_to_hand_multi_
#: target`: the group was already announced (and, for "controlled by
#: different players", already constrained) by the preceding "choose N
#: target creatures …" clause (`_choose_targets_group`), so this clause
#: names no target of its own at all — only offered when that preceding
#: clause actually chose one (`EffectHandler.previous_subject_only`).
_RETURN_PREVIOUS_GROUP_RE = _c(
    r"(?:then )?return (?:those creatures|them) to their owners'? hands?"
)


def _return_previous_group(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_hand", {"previous_subject": True})]


#: A graveyard clause's card-*type* word, right before "card" — "target
#: [instant or sorcery/sorcery/nonland permanent/creature/artifact/
#: enchantment/land/permanent] card", or no word at all for a bare "target
#: card" (longest-alternative-first so "nonland permanent" wins over
#: "permanent"; ``sorcery`` alone — MEC-24, Recoup's own "target **sorcery**
#: card" — doesn't need the same ordering care since it starts on a
#: different word than "instant or sorcery").
#: PAR-77: "target **rebel/mercenary permanent** card" (Ramosian
#: Revivalist) — the graveyard-return sibling of PAR-70's own "`<subtype>`
#: permanent card" search qualifier; same fixed enum (Rebel/Mercenary are
#: exclusively creature subtypes in paper Magic, so no separate creature-
#: subtype vocabulary is needed here either). Tried before the bare
#: "permanent" alternative so it isn't swallowed by it.
_GRAVEYARD_TYPE_WORD = (
    r"instant or sorcery|sorcery|nonland permanent|rebel permanent|"
    r"mercenary permanent|artifact (?:and|or) enchantment|artifact or creature|creature|artifact|"
    r"non-aura enchantment|enchantment|land|permanent"
)
#: A graveyard clause's *scope* — whose graveyard — "your"/"a" (any single
#: graveyard)/"an opponent's" (longest-alternative-first, same reason).
_GRAVEYARD_SCOPE_WORD = r"an opponent'?s|your|a"
#: PAR-128: RULE 109.5's "another"/"other" before "target" on a graveyard card.
#: A slot, not a filter: the graveyard pool already leaves out the ability's own
#: source (`targeting.legal_targets`' `o is not source`), which is all "another"
#: asks for (Junk Diver's dies trigger names its own graveyard card).
_GRAVEYARD_OTHER = rf"(?:{OTHER_PREFIX})?"
#: Scope word → `targeting._GRAVEYARD_SCOPE_PREFIXES` key.
_GRAVEYARD_SCOPE_KIND: dict[str, str] = {
    "your": "graveyard", "a": "any_graveyard", "an opponents": "opponent_graveyard",
}


def _graveyard_target_kind(type_word: Optional[str], scope_word: str) -> Optional[str]:
    """A graveyard clause's ``(type_word, scope_word)`` → engine
    ``target_kind`` string (`game/targeting.py`'s `_GRAVEYARD_TARGET_KINDS`),
    or ``None`` if either half isn't one of the recognised shapes."""
    scope_key = _GRAVEYARD_SCOPE_KIND.get(re.sub(r"'", "", scope_word.strip().lower()))
    if scope_key is None:
        return None
    type_key = {
        "": "card", "instant or sorcery": "instant_or_sorcery",
        "nonland permanent": "nonland_permanent",
        "non-aura enchantment": "non_aura_enchantment",
        "rebel permanent": "rebel_permanent",
        "mercenary permanent": "mercenary_permanent",
        "artifact and enchantment": "artifact_or_enchantment",
        "artifact or enchantment": "artifact_or_enchantment",
        "artifact or creature": "artifact_or_creature",
    }.get((type_word or "").strip().lower(), (type_word or "").strip().lower() or "card")
    return f"{scope_key}_{type_key}"


#: "exile up to twice X target cards from graveyards." (Erebos's Intervention) / "exile X target cards
#: from graveyards" — several graveyard cards picked from any graveyards at once. The X forms size the
#: pick by the announced {X} (`TargetSpec.count_selector`, read at announce time); a literal count is
#: the plain multi-target shape. "a single graveyard" (a same-graveyard constraint) is not this row.
_EXILE_GRAVEYARD_CARDS_MULTI_RE = _c(
    r"exile (?:(?P<x_count>(?P<x_up_to>up to )?(?P<twice>twice )?x )"
    r"|(?P<up_to>up to )?(?P<count>\d+) )target cards from graveyards"
)


def _exile_graveyard_cards_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("x_count"):
        return [EffectSpec("exile", {
            "target_kind": "any_graveyard_card", "count": _ANY_NUMBER_TARGET_CAP, "optional": True,
            "count_selector": "source_twice_x_paid" if m.group("twice") else "source_x_paid",
        })]
    count = int(m.group("count"))
    if count < 2:
        return None
    params: dict = {"target_kind": "any_graveyard_card", "count": count}
    if m.group("up_to"):
        params["optional"] = True
    return [EffectSpec("exile", params)]


#: Colour-list ("`<c1>` or `<c2>`") siblings of the bounce / put-on-library
#: / graveyard-return handlers — `TargetSpec.colors`' OR narrowing, the
#: `_pump_target_two_color` / `_destroy_color_adj` idiom. Dedicated rows
#: because the shared `TARGET` macro carries no colour slot (see
#: `subgrammars.COLOR_WORD_ALT`'s note). Escape Routes (bounce), Hunting
#: Drake (library), Crypt Angel (graveyard).
_RETURN_TO_HAND_TWO_COLOR_RE = _c(
    rf"return target (?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) "
    rf"creature(?P<yc> you control)? to its owner's hand"
)
_RETURN_TO_LIBRARY_TWO_COLOR_RE = _c(
    rf"put target (?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) creature "
    rf"on (?:top|the (?P<pos>bottom)) of its owner's library"
)
_RETURN_FROM_GRAVEYARD_TWO_COLOR_RE = _c(
    rf"return target (?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) creature card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard to "
    r"(?P<dest>the battlefield|your hand|its owner'?s hand)"
)


def _return_to_hand_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = _two_color_letters(m)
    if colors is None:
        return None
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("return_to_hand", {"target_kind": kind, "colors": colors})]


def _return_to_library_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = _two_color_letters(m)
    if colors is None:
        return None
    position = "bottom" if m.group("pos") == "bottom" else "top"
    return [EffectSpec("return_to_library", {
        "target_kind": "creature", "position": position, "colors": colors,
    })]


def _return_from_graveyard_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = _two_color_letters(m)
    if colors is None:
        return None
    kind = _graveyard_target_kind("creature", m.group("scope"))
    if kind is None:
        return None
    destination = "battlefield" if m.group("dest") == "the battlefield" else "hand"
    return [EffectSpec("return_from_graveyard", {
        "target_kind": kind, "destination": destination, "colors": colors,
    })]


#: "return target [type] card [with mana value N or less] from [scope]
#: graveyard to the battlefield/your hand/its owner's hand" / "put target
#: [type] card from [scope] graveyard onto the battlefield under its
#: owner's control" (RULE 701.3, the Regrowth/Reanimate/Deathrite-adjacent
#: recursion family — see `game/targeting.py`'s `_GRAVEYARD_TARGET_KINDS`
#: for the scope × type vocabulary this claims). Both verb shapes land the
#: object under its own *owner*'s control — the "steal it for yourself"
#: shape is `_reanimate_under_your_control` below, a genuinely different
#: effect. The optional mana-value cap (Auriok Salvagers-shaped) is the
#: same `TargetSpec.max_mana_value` offer-time filter `destroy_mv` already
#: uses, not a new one.
_RETURN_FROM_GRAVEYARD_RE = _c(
    rf"return (?P<up_to_one>{UP_TO_ONE}){_GRAVEYARD_OTHER}target (?:(?P<nonleg>nonlegendary) )?"
    rf"(?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card(?P<adv> that has an adventure)?"
    # PAR-143: "with power 2 or less" (Alesha) rides the same slot as the mana-value cap.
    rf"(?: with (?:mana value (?P<mv>\d+)|power (?P<pw>\d+)) or less| with mana value (?P<emv>x))? from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard to "
    r"(?P<dest>the battlefield|your hand|its owner'?s hand)"
    # PAR-143: "…to the battlefield tapped [and attacking]" (RULE 110.5b / 508.4).
    r"(?P<tapped> tapped)?(?P<atk> and attacking)?"
    # "…to the battlefield with a -1/-1 counter on it." (Persist — RULE
    # 701.3 recursion plus an enters-with rider, distinct from the Persist
    # *keyword*'s in-place return). MEC-108 widened the counter to a +1/+1 or
    # RULE 122.1b keyword counter and its amount ("with a flying counter on it",
    # "with 2 +1/+1 counters on it").
        # "with an additional +1/+1 counter on it" (Prison Break) is the same counter: it adds to what the card enters with.
    rf"(?: with (?P<ewc_n>a|an|\d+)(?: additional)? (?P<ewc_kind>-1/-1|\+1/\+1|corpse|{'|'.join(KEYWORD_COUNTER_KINDS)}) counters? on it)?"
)
_PUT_FROM_GRAVEYARD_OWNER_CONTROL_RE = _c(
    rf"put (?P<up_to_one>{UP_TO_ONE}){_GRAVEYARD_OTHER}target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard onto the battlefield under its owner'?s control"
)


def _return_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    dest = m.groupdict().get("dest")
    destination = "battlefield" if dest is None or dest == "the battlefield" else "hand"
    params: dict = {"target_kind": kind, "destination": destination}
    if m.groupdict().get("up_to_one"):
        params["optional"] = True
    mv = m.groupdict().get("mv")
    if mv is not None:
        params["max_mana_value"] = int(mv)
    if m.groupdict().get("pw") is not None:
        params["creature_filter"] = {"max_power": int(m.group("pw"))}
    if m.groupdict().get("adv"):
        params["creature_filter"] = {"has_adventure": True}  # Edgewall Inn
    if m.groupdict().get("emv"):
        params["exact_mana_value"] = "x"  # Isareth the Awakener: bound by the preceding "pay {X}"
    if m.groupdict().get("tapped") or m.groupdict().get("atk"):
        if destination != "battlefield":
            return None  # only a battlefield entry is tapped or attacking
        if m.group("tapped"):
            params["tapped"] = True
        if m.group("atk"):
            if not m.group("tapped"):
                return None  # "attacking" on its own isn't a printed spelling
            params["attacking"] = True
    if m.groupdict().get("nonleg"):
        params["exclude_legendary"] = True
    if m.groupdict().get("ewc_kind"):
        if destination != "battlefield":
            return None  # an enters-with rider is meaningless returning to hand
        params["extra_counters"] = {"kind": m.group("ewc_kind"), "count": count_of(m.group("ewc_n"))}
    return [EffectSpec("return_from_graveyard", params)]


#: "return up to two target creature cards from your graveyard to your
#: hand"/"...to the battlefield" (RULE 115.1a generalized to N>=2 — Back for
#: Seconds/Dead Revels/Death's Duet/Entreat the Dead-shaped, a large real
#: family) — the plural sibling of `_RETURN_FROM_GRAVEYARD_RE`. The type
#: word itself doesn't inflect ("creature cards", not "creatures cards").
_RETURN_FROM_GRAVEYARD_MULTI_RE = _c(
    rf"return {_MULTI_TARGET_QUANTIFIER}{_GRAVEYARD_OTHER}target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?cards "
    rf"(?:each with mana value (?P<mv>\d+) or less )?from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyards? to "
    r"(?P<dest>the battlefield|your hand|their owners'? hands)"
)


def _return_from_graveyard_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    dest = m.groupdict().get("dest")
    destination = "battlefield" if dest is None or dest == "the battlefield" else "hand"
    if m.groupdict().get("range_min") is not None:
        # ENG-30: "return 1 or 2 target creature cards from your graveyard
        # to your hand/the battlefield" (Infernal Rebirth/Leonardo's
        # Technique-shaped) — a genuine RULE 601.2c range, not "up to N".
        range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
        if range_min < 1 or range_max <= range_min:
            return None
        return [EffectSpec("return_from_graveyard", {
            "target_kind": kind, "destination": destination,
            "count": range_min, "count_max": range_max,
        })]
    count = int(m.group("count"))
    if count < 2:
        return None
    params: dict = {"target_kind": kind, "destination": destination, "count": count}
    if m.groupdict().get("up_to"):
        params["optional"] = True
    if m.groupdict().get("mv") is not None:
        params["max_mana_value"] = int(m.group("mv"))
    return [EffectSpec("return_from_graveyard", params)]


#: "return [up to] X target `<type>` cards from [scope] graveyard to your
#: hand / the battlefield" (Death Denied, Entreat the Dead, Shattered
#: Crypt, Wake the Dead, Champion of Stray Souls) — the target count is
#: the spell/ability's own announced {X} (`GameObject.x_paid`), read at
#: target-gathering time via `TargetSpec.count_selector="source_x_paid"`,
#: the same idiom March of Swirling Mist's "up to X target creatures
#: phase out" and Change of Plans already use. Always `optional`: RULE
#: 601.2c lets an announced X be 0, and "up to X" is optional anyway.
_RETURN_FROM_GRAVEYARD_X_RE = _c(
    rf"return (?:up to )?x {_GRAVEYARD_OTHER}target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?cards from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyards? to "
    r"(?P<dest>the battlefield|your hand)"
)


def _return_from_graveyard_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    destination = "battlefield" if m.group("dest") == "the battlefield" else "hand"
    return [EffectSpec("return_from_graveyard", {
        "target_kind": kind, "destination": destination,
        "count_selector": "source_x_paid", "optional": True,
    })]


#: "put target [type] card from [scope] graveyard onto the battlefield
#: under your control" (Reanimate/Rise from the Grave/Virtue of Persistence)
#: — unlike the two shapes above, this one *steals* the card for the
#: activating/casting player regardless of whose graveyard it came from.
_REANIMATE_UNDER_YOUR_CONTROL_RE = _c(
    rf"put (?P<up_to_one>{UP_TO_ONE}){_GRAVEYARD_OTHER}target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard onto the battlefield under your control"
    # PAR-139: "…with a corpse counter on it" (From the Catacombs) — a named enters-with counter.
    r"(?: with (?P<ewc_n>a|an|\d+) (?P<ewc_kind>corpse) counters? on it)?"
)


def _reanimate_under_your_control(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind, "destination": "battlefield", "under_your_control": True}
    if m.groupdict().get("ewc_kind"):
        params["extra_counters"] = {"kind": m.group("ewc_kind"), "count": count_of(m.group("ewc_n"))}
    if m.groupdict().get("up_to_one"):
        params["optional"] = True
    return [EffectSpec("return_from_graveyard", params)]


#: "Put one, two, or three target creature cards from graveyards onto the
#: battlefield under your control. Each of them enters with an additional
#: -1/-1 counter on it." (Aberrant Return) — an enumerated RULE 601.2c
#: target-count range ("1, 2, or 3" → min 1, `count_max` 3) folded into the
#: same `return_from_graveyard` effect the singular reanimate row emits,
#: plus the whole-body enters-with rider (`ReturnFromGraveyardEffect.
#: extra_counters`, applied per returned card). Matched as one two-sentence
#: clause (`parse_effect_body` tries the whole body first) since the rider
#: has no standalone handler.
_REANIMATE_MULTI_UNDER_YOUR_CONTROL_RE = _c(
    r"put (?P<lo>\d+), (?:\d+, )*or (?P<hi>\d+) target "
    rf"(?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?cards from graveyards "
    r"onto the battlefield under your control"
    r"(?:\. (?:each of them|they) enters? with an additional "
    r"(?P<ck>-1/-1|\+1/\+1) counter on it)?"
)


def _reanimate_multi_under_your_control(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), "a")  # "from graveyards" = any
    if kind is None:
        return None
    lo, hi = int(m.group("lo")), int(m.group("hi"))
    if lo < 1 or hi <= lo:
        return None
    params: dict = {
        "target_kind": kind, "destination": "battlefield", "under_your_control": True,
        "count": lo, "count_max": hi,
    }
    if m.groupdict().get("ck"):
        params["extra_counters"] = {"kind": m.group("ck"), "count": 1}
    return [EffectSpec("return_from_graveyard", params)]


#: PAR-15's "any number of" siblings of the two shapes above — always "your
#: own graveyard" on every real card using either ("put ... on top of your
#: library": Bone Harvest/Footbottom Feast/Forever Young/Gravepurge; "shuffle
#: ... into your library": Piper's Melody/Renewing Touch/Perpetual Timepiece/
#: The Bath Song), so unlike `_RETURN_FROM_GRAVEYARD_RE` neither needs the
#: full opponent/any-graveyard scope vocabulary. The shuffle shape is
#: modeled as "put on the bottom, then shuffle" — see `ReturnFromGraveyard
#: Effect.shuffle_after` — since the position `library_bottom` gives it is
#: immediately randomized away by the shuffle, matching "shuffled into your
#: library" exactly.
_RETURN_FROM_GRAVEYARD_TOP_ANY_RE = _c(
    rf"put any number of target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?cards from "
    r"your graveyard on top of your library"
)
_RETURN_FROM_GRAVEYARD_SHUFFLE_ANY_RE = _c(
    rf"shuffle any number of target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?cards from "
    r"your graveyard into your library"
)


def _return_from_graveyard_top_any(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), "your")
    if kind is None:
        return None
    return [EffectSpec("return_from_graveyard", {
        "target_kind": kind, "destination": "library_top",
        "count": _ANY_NUMBER_TARGET_CAP, "optional": True,
    })]


def _return_from_graveyard_shuffle_any(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), "your")
    if kind is None:
        return None
    return [EffectSpec("return_from_graveyard", {
        "target_kind": kind, "destination": "library_bottom", "shuffle_after": True,
        "count": _ANY_NUMBER_TARGET_CAP, "optional": True,
    })]


#: "Target player shuffles up to N target cards from their graveyard into
#: their library." (PAR-86 — Dwell on the Past/Krosan Reclamation).  This
#: has two linked choices: the player target identifies the graveyard and
#: the controller then chooses its cards, represented by the existing
#: Quandrix Command effect rather than independent card TargetSpecs.
_SHUFFLE_TARGET_GRAVEYARD_CARDS_RE = _c(
    r"target player shuffles up to (?P<n>\d+) target cards from their graveyard into their library"
)


def _shuffle_target_graveyard_cards(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("shuffle_target_graveyard_cards_into_library", {
        "count_max": int(m.group("n")),
    })]


#: Living Death family — "[each player returns / you return / return] all
#: [or each] creature card[s] from [their / your / its owner's] graveyard
#: to the battlefield [or their/your hand]". A mass, untargeted recursion
#: over every matching graveyard card (`ReturnFromGraveyardEffect.players`
#: = ``"you"`` / ``"each_player"``). Deliberately only the plain creature-
#: card shape both branches of a will-of-the-council vote and the classic
#: reanimation sweeps use — Magister of Worth (its grace branch), Empty
#: the Catacombs, Storm of Souls, Finale of Eternity. Riders on the
#: returned cards (a -1/-1 counter, "each is a 1/1 Spirit") stay
#: fail-closed.
#: PAR-143 widened the type word from "creature" to the graveyard type vocabulary ("return all land
#: cards from your graveyard to the battlefield tapped", Aftermath Analyst, Lumra) and added the
#: tapped entry; `ReturnFromGraveyardEffect` filters by the kind's own type predicate.
_MASS_RETURN_GRAVEYARD_RE = _c(
    r"(?:(?P<each>each player returns)|you return|return) "
    rf"(?:all|each) (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?cards? from "
    r"(?:their|your|its owner'?s|(?P<all>all)) graveyards? to "
    r"(?P<dest>the battlefield|their hand|your hand)(?P<tapped> tapped)?"
    # "…from all graveyards to the battlefield under their owners' control" (Open the Vaults): every player's own cards.
    r"(?P<owners> under their owners'? control)?"
)


def _mass_return_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dest = m.group("dest")
    kind = _graveyard_target_kind(m.groupdict().get("type"), "your")
    if kind is None or (m.group("tapped") and dest != "the battlefield"):
        return None
    params: dict = {
        "target_kind": kind,
        "destination": "battlefield" if dest == "the battlefield" else "hand",
        "players": "each_player" if m.group("each") or m.group("all") else "you",
    }
    if m.group("owners") and not m.group("all"):
        return None
    if m.group("all") and not m.group("owners"):
        return None  # "all graveyards" without "under their owners' control" would be under the caster's
    if m.group("tapped"):
        params["tapped"] = True
    return [EffectSpec("return_from_graveyard", params)]


#: PAR-143: "[you may] return a `<type>` card [with mana value N or less] from your graveyard to the
#: battlefield [tapped] / your hand" and "put a `<type>` card from a graveyard onto the battlefield
#: [tapped] under your control" (Blossoming Tortoise, Deeproot Wayfinder, Soul of Windgrace) — the
#: untargeted pick: no "target", so the controller chooses at resolution (`ReturnFromGraveyardEffect.pick`).
_RETURN_PICK_FROM_GRAVEYARD_RE = _c(
    r"(?P<may>you may )?(?:"
    rf"return an? (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card"
    rf"(?: with mana value (?P<mv>\d+) or less)? from (?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard to "
    r"(?P<dest>the battlefield|your hand)(?P<tapped> tapped)?"
    r"|"
    rf"put an? (?:(?P<type2>{_GRAVEYARD_TYPE_WORD}) )?card from (?P<scope2>{_GRAVEYARD_SCOPE_WORD}) graveyard "
    r"onto the battlefield(?P<tapped2> tapped)? under your control)"
)


def _return_pick_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    groups = m.groupdict()
    put = groups.get("scope2") is not None
    kind = _graveyard_target_kind(
        groups["type2"] if put else groups.get("type"), groups["scope2"] if put else groups["scope"],
    )
    if kind is None:
        return None
    destination = "battlefield" if put or groups["dest"] == "the battlefield" else "hand"
    tapped = bool(groups.get("tapped2") if put else groups.get("tapped"))
    if tapped and destination != "battlefield":
        return None
    params: dict = {"target_kind": kind, "destination": destination, "pick": True}
    if groups.get("may"):
        params["optional"] = True
    if tapped:
        params["tapped"] = True
    if put:
        params["under_your_control"] = True
    if groups.get("mv") is not None:
        params["max_mana_value"] = int(groups["mv"])
    return [EffectSpec("return_from_graveyard", params)]


#: "exile [up to one] target [type] card from [scope] graveyard" (RULE
#: 701.5a) — the Deathrite Shaman/Scavenging Ooze/Lion Sash graveyard-hate
#: family; almost always "a graveyard" in practice, but the same scope
#: vocabulary applies. The `UP_TO_ONE` prefix (RULE 115.1a — PAR-18's own
#: "exile up to 1 target creature card from a graveyard[. create a token
#: that's a copy of that card]" antecedent, Ardyn/Anikthea-shaped) reuses
#: `_optional_param`/`target_is_optional` the same way every other
#: `{TARGET}`-bearing handler does, even though this clause hand-rolls its
#: own "target" grammar instead of embedding `TARGET` (the graveyard scope/
#: type vocabulary predates that macro and has its own word lists).
#: The determiner is ``target`` for the RULE 115 form (Deathrite Shaman) or a
#: bare ``a``/``an`` for the untargeted reanimator-cycle antecedent ("you may
#: exile a creature card from your graveyard. Create a token that's a copy of
#: that card." — God-Pharaoh's Gift/Séance); both resolve to the same
#: `graveyard_*` `EffectSpec`, the "target" nuance (redirect/"can't be
#: targeted") being immaterial for a graveyard-card pick this grammar models.
_EXILE_FROM_GRAVEYARD_RE = _c(
    rf"exile (?P<up_to_one>{UP_TO_ONE})(?:target |an? )"
    rf"(?:(?P<colors>{_COLOR_WORD_LIST_INNER}) )?"
    rf"(?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard"
)


def _exile_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind, **_optional_param(m)}
    #: "exile target red, white, or black creature card from your graveyard"
    #: (Offspring's Revenge) — `TargetSpec.colors`' OR narrowing on a
    #: graveyard-card target, the N-colour sibling of `_exile_target_two_color`.
    colors = _color_word_list(m.groupdict().get("colors"))
    if colors:
        params["colors"] = colors
    elif m.groupdict().get("colors"):
        return None  # a colour list we couldn't resolve — fail closed
    return [EffectSpec("exile", params)]


#: "Exile N cards from your graveyard." is a mandatory resolve-time choice,
#: distinct from the targeted one-card grammar above. Number words have
#: already been converted to digits by oracle normalization.
_EXILE_OWN_GRAVEYARD_CARDS_RE = _c(
    r"exile (?P<count>\d+) cards? from your graveyard"
)


def _exile_own_graveyard_cards(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile_own_graveyard_cards", {"count": int(m.group("count"))})]


#: "exile target player's graveyard." (Bojuka Bog) / "exile all cards from
#: target player's graveyard." (Tormod's Crypt) — a whole *graveyard*
#: targeted by player, not a single card from one (`_EXILE_FROM_GRAVEYARD_RE`
#: above) — the two phrasings are the same effect, so one builder claims both.
_EXILE_TARGET_GRAVEYARD_RE = _c(
    r"exile (?:all cards from )?target player'?s graveyard"
)


def _exile_target_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("exile_target_graveyard", {"target_kind": "player"})]


#: "search your library for a [<criteria>] card, [reveal it,] put it/that
#: card/them/those cards <destination>, then shuffle." (RULE 701.19, the
#: general tutor/ramp/fetch family — Demonic Tutor/Rampant Growth/Farseek/
#: Nature's Lore/Crop Rotation/Eladamri's Call/Buried Alive/Sylvan
#: Scrying-shaped) and its reordered sibling "..., [reveal it,] then shuffle
#: and put it/that card/the card on top." (Vampiric/Mystical/Enlightened/
#: Worldly Tutor-shaped). Both map onto the engine's existing `"search"`
#: `EffectSpec` (`game/effects/core.py`'s `SearchLibraryEffect`, already
#: parameterized on criteria/destination/count — `tests/
#: test_search_popular_tutors.py` proves it against 15 real popular tutors)
#: — no new effect type needed, just recognition. Three siblings below
#: extend the same `"search"` `EffectSpec` onto its ``zones``/
#: ``destinations``/``exile_rest`` params (`RulesEngine._request_search`):
#: "library and/or graveyard" combined search (`_search_zone_put`, ~50 real
#: cards — the backgrounds/planeswalker-tutor family), a split destination
#: per found card (`_search_split_destination` — Cultivate/Kodama's Reach),
#: and "search for N cards and exile the rest" (`_search_exile_rest` —
#: Doomsday). Deliberately still NOT attempted here (fail-closed, real cards
#: found but left unclaimed): any qualifier after the noun phrase such as
#: "with mana value X or less" (Green Sun's Zenith/Chord of Calling/Finale
#: of Devastation — X is a spell's own cast-time choice, not a static
#: criterion this grammar can express), a name criterion whose own name
#: contains a comma ("a card named Angrath, Minotaur Pirate" —
#: indistinguishable from the following put-clause's own comma without a
#: name dictionary), and a searched-for subtype not in `_SEARCH_TYPE_WORD`'s
#: vocabulary ("a Shrine card"/"an Ally creature card").
#:
#: The type-word vocabulary intentionally also carries the five basic land
#: names (a card can be searched for by name, "a Forest card"/"a Plains,
#: Island, Swamp, or Mountain card" — Nature's Lore/Farseek), separate from
#: "basic land" (Rampant Growth) which sets `criteria["basic"]` instead of a
#: `type` filter — the two are mutually exclusive alternatives tried in that
#: order (longest/most-specific first), never combined.
#: "Equipment" is a subtype, not a main card type, but `models.cards.card_query.
#: _type_matches` does a plain substring check against the whole printed
#: type line ("Artifact — Equipment") rather than only the pre-em-dash main
#: types — the same reason "Forest"/"Island" already work as entries here
#: despite being land subtypes too. Adding it costs nothing engine-side,
#: purely a missing vocabulary word (Steelshaper's Gift/Stoneforge
#: Mystic-shaped).
_SEARCH_TYPE_WORD = (
    r"artifact|creature|enchantment|instant|planeswalker|sorcery|land|"
    r"plains|island|swamp|mountain|forest|equipment"
)
#: An "or"/comma-separated list of 1+ type words, same shape as
#: `subgrammars._SPELL_TYPE_LIST` (kept separate/local since this vocabulary
#: — land + basic land names — is specific to a library search, not a spell
#: target filter).
_SEARCH_TYPE_LIST = (
    rf"(?:{_SEARCH_TYPE_WORD})(?:,\s*(?:{_SEARCH_TYPE_WORD}))*"
    rf"(?:,?\s+or\s+(?:{_SEARCH_TYPE_WORD}))?"
)
#: A colour word ahead of the type list — "search your library for a
#: **blue** instant card" (Merchant Scroll), "a **green** creature card"
#: (Green Sun's Zenith/Magus of the Order/Natural Order/Shadow-Rite
#: Priest) — captured and mapped onto `models.cards.card_query`'s own ``color``
#: key (matched against the card's colour identity), the same key/matcher
#: `_destroy_color_adj` already reuses via `resolve_color_word` — not
#: dropped, despite this module's older docstrings elsewhere describing it
#: that way (that was a real gap until `SearchLibraryEffect.criteria`
#: started reaching `card_query.matches`, not a documented permanent
#: choice). ``colorless`` (Eye of Ugin's "a colorless creature card") is
#: kept local to this search vocabulary rather than added to the shared
#: `subgrammars.COLOR_WORD_ALT`/`resolve_color_word` every other colour-word
#: consumer (target filters, "if it's `<color>`" suffixes, …) reuses — those
#: are genuinely WUBRG-only templates, "colorless" isn't a valid substitute
#: for any of them today, so widening that shared vocabulary would risk
#: silently claiming a clause it shouldn't. `_search_criteria_from_match`/
#: `_search_zone_criteria_from_match` handle it directly rather than through
#: `resolve_color_word`, which only maps WUBRG letters.
_SEARCH_COLOR_WORD = r"white|blue|black|red|green|colorless"
#: "…with mana value X or less" (Green Sun's Zenith/Chord of Calling) — X
#: is this spell's own announced {X}, so the captured magnitude is the
#: literal ``"x"``/``"-x"`` sentinel `RulesEngine._substitute_x` rewrites
#: once the spell actually resolves, exactly like every other X-scaled
#: one-shot effect; a literal digit bound ("…with mana value 3 or less")
#: is accepted the same way but has no known real card on this exact
#: search-noun-phrase shape yet.
_SEARCH_MV_QUALIFIER = (
    r"(?: with mana value (?P<mv>\d+|x) or (?P<mv_cmp>greater|less))?"
)
#: PAR-70: "a **rebel**/**mercenary** permanent card" (Mercadian Masques'
#: recruiter cycle — Ramosian Sergeant/Captain/Commander/Sky Marshal,
#: Cateran Persuader/Brute/Kidnappers/Enforcer/Slaver/Overlord, Amrou Scout/
#: Blightspeaker/Defiant Falcon, Bog Glider, Rathi Fiend/Intimidator). Unlike
#: `_SEARCH_TYPE_WORD` (card *types*, OR-combined in a comma list),
#: "permanent" here isn't itself a type-line word — no real card's type line
#: ever literally reads "Permanent" — it's the block's own way of saying
#: "any card type", so the pair is really one compound qualifier: "a card of
#: subtype `<word>`, no card-type restriction beyond being a permanent".
#: Rebel/Mercenary are exclusively creature subtypes in paper Magic, so
#: `crit["type"] = "<word>"` alone (a type-line substring match) already
#: narrows correctly without a separate "permanent" key. Kept as a small
#: fixed enum rather than a full creature-subtype vocabulary — this
#: codebase has no such list (`_SEARCH_COLOR_WORD` is the same shape) — and
#: extending it to a new subtype is a one-word change if another "<subtype>
#: permanent card" tutor cycle turns up.
_SEARCH_SUBTYPE_WORD = r"rebel|mercenary"
#: The noun phrase after "search your library for": a determiner ("a"/"an"/
#: "up to N"), an optional "basic" qualifier (sets `basic`), an optional
#: "<subtype> permanent" qualifier (sets `subtype` — see
#: `_SEARCH_SUBTYPE_WORD` above), then either a `_SEARCH_TYPE_LIST` (sets
#: `types` — "land" is itself one of that list's words, so bare "basic land"
#: still resolves to ``{"basic": True}`` with no separate case) or neither
#: (a bare "a card"), then "card(s)", then an optional trailing mana-value
#: qualifier. "Basic" and a type list combine freely — "a basic Forest,
#: Plains, or Island card" (the Panorama/Landscape/Monument tri-land fetch
#: cycles, Bant Panorama-shaped: ~40 real cards on this exact combined
#: shape) narrows the search to *basic* lands of *those* named types, not
#: "basic land" (any basic) or a bare type list (any card of that type, not
#: necessarily basic) alone.
#: PAR-74: "an **Aura** card **with enchant creature**" (Tallowisp). Unlike
#: `_SEARCH_SUBTYPE_WORD`'s "`<subtype>` permanent" shape, "Aura" is an
#: *enchantment* subtype (not a creature one) named directly before "card",
#: with a trailing "with enchant creature" qualifier restricting *which*
#: Auras. `card_query.matches`'s ``type`` key is already a type-line
#: substring test, so ``{"type": "Aura"}`` alone correctly narrows to Auras
#: — the "with enchant creature" tail is consumed and dropped, the same
#: documented simplification `_SEARCH_REVEAL` uses for pure flavor text:
#: `card_query` has no "Enchant `<type>`" predicate, and every real card on
#: this template only ever wants a creature-enchanting Aura anyway (no
#: printed Aura enchants two different permanent types at once), so the
#: dropped qualifier can never cause a wrong pick in practice.
_SEARCH_AURA_ENCHANT_CREATURE_TAIL = r"(?:\s+with enchant creature)?"
_SEARCH_CRITERIA = (
    r"(?:up to (?P<count>\d+)|an?)\s+"
    rf"(?:(?P<color>{_SEARCH_COLOR_WORD})\s+)?"
    r"(?:(?P<basic>basic)\s+)?"
    rf"(?:(?P<subtype>{_SEARCH_SUBTYPE_WORD})\s+permanent\s+)?"
    rf"(?:(?P<aura>aura)\s+)?"
    rf"(?P<types>{_SEARCH_TYPE_LIST})?\s*"
    r"cards?"
    + _SEARCH_AURA_ENCHANT_CREATURE_TAIL
    + _SEARCH_MV_QUALIFIER
)
#: Whichever pronoun/noun-phrase a card's "reveal ~"/"put ~ <dest>" clause
#: uses for the found card — every variant found in the popular-tutor cache
#: scan (Wishclaw Talisman's "it", most tutors' "that card", Buried Alive's
#: plural "them", Worldly Tutor's "the card").
_SEARCH_PRONOUN = r"(?:it|that card|them|those cards|the card)"
#: An optional "reveal <pronoun>," clause between the criteria and the
#: put/shuffle tail (Eladamri's Call/Mystical/Enlightened/Worldly Tutor) —
#: purely descriptive text at this engine's fidelity (no separate game-state
#: effect: the found card is already known to both players via the search
#: choice), so it's consumed and dropped, not modeled as its own effect.
_SEARCH_REVEAL = rf"(?:reveal {_SEARCH_PRONOUN},?\s*)?"
#: Where the found card goes — order matters ("battlefield tapped" must be
#: tried before the bare "battlefield" row so it isn't left partially
#: unconsumed).
_SEARCH_DESTINATION_ROWS: list[tuple[str, str]] = [
    (r"onto the battlefield tapped", "battlefield_tapped"),
    (r"onto the battlefield", "battlefield"),
    (r"into your hand", "hand"),
    (r"into your graveyard", "graveyard"),
]
_SEARCH_DESTINATION_ALT = "|".join(f"(?:{frag})" for frag, _ in _SEARCH_DESTINATION_ROWS)


def _search_destination_kind(phrase: str) -> Optional[str]:
    text = phrase.strip()
    for frag, kind in _SEARCH_DESTINATION_ROWS:
        if re.fullmatch(frag, text, re.IGNORECASE):
            return kind
    return None

#: "Its controller may search their library for a basic land card, put it
#: onto the battlefield, then shuffle." (Assassin's Trophy/Geomancer's
#: Gambit/Ghost Quarter-shaped — always the trailing sentence after a
#: "Destroy target land/permanent an opponent controls." clause the
#: ordinary `destroy` handler already claims on its own) — `SearchLibraryEffect`'s
#: ``player="previous_target_controller"`` sentinel (the same one
#: `PayCostThenEffect`'s own ``payer`` param already uses for Chain of
#: Vapor's "that permanent's controller may sacrifice a land"), since the
#: acting player here is whoever just lost the destroyed permanent, not
#: this spell's own caster.
_DESTROY_CONTROLLER_SEARCH_BASIC_LAND_RE = _c(
    r"its controller may search (?:its|their) library for a basic land card, "
    r"put it onto the battlefield(?P<tapped> tapped)?, then shuffle"
)


def _destroy_controller_search_basic_land(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec(
            "search",
            {
                "criteria": {"basic": True},
                # "…put it onto the battlefield **tapped**" (White Orchid
                # Phantom) — the same optional-tapped tail Ghost Quarter's
                # untapped form doesn't carry.
                "destination": "battlefield_tapped" if m.group("tapped") else "battlefield",
                "optional": True,
                "player": "previous_target_controller",
            },
        )
    ]


#: "search your library for <criteria>, [reveal <pronoun>,] put <pronoun>
#: <destination>, then shuffle." — the common put-then-shuffle order.
_SEARCH_PUT_THEN_SHUFFLE_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)
#: Search criteria the plain grammar above has no slot for, each a whole phrase of its own: "an instant card or a
#: card with flash" (Mystical Teachings — an OR of two criteria) and "a land card with a basic land type"
#: (Sprouting Goblin — a land whose type line carries any of RULE 305.6's five basic types).
_SEARCH_NAMED_CRITERIA: dict[str, dict] = {
    "an instant card or a card with flash": {"or": [{"type": "instant"}, {"has_keyword": "Flash"}]},
    "a land card with a basic land type": {
        "all_types": ["land"], "type": ["plains", "island", "swamp", "mountain", "forest"],
    },
}
_SEARCH_NAMED_CRITERIA_RE = _c(
    rf"search your library for (?P<crit>{'|'.join(re.escape(k) for k in _SEARCH_NAMED_CRITERIA)}),?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_named_criteria(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    return [EffectSpec("search", {
        "criteria": dict(_SEARCH_NAMED_CRITERIA[m.group("crit").lower()]), "destination": destination,
    })]


#: "search your library for <criteria> that share a land type, [reveal
#: <pronoun>,] put <pronoun> <destination>, then shuffle." (Myriad
#: Landscape, MEC-43 round 3) — the same put-then-shuffle order as
#: `_SEARCH_PUT_THEN_SHUFFLE_RE` just above, plus the cross-pick "that share
#: a land type" qualifier (RULE 305.6) between the criteria and the
#: put-clause; a separate regex rather than an optional group spliced into
#: the shared one, since only this one shape maps onto `"search"`'s new
#: ``share_land_type`` param (`SearchLibraryEffect`/`RulesEngine.
#: _request_search`).
_SEARCH_PUT_THEN_SHUFFLE_SHARE_TYPE_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA} that share a land type,?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)
#: "search your library for <criteria>, [reveal <pronoun>,] then shuffle and
#: put <pronoun> on top [of your library]." — the reordered shuffle-then-put
#: order, always to the top of the library (Vampiric/Mystical/Enlightened/
#: Worldly Tutor).
_SEARCH_SHUFFLE_THEN_PUT_TOP_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"then shuffle and put {_SEARCH_PRONOUN} "
    # Long-Term Plans' "third from the top" (RULE 401.7) — the same shuffle-then-place order.
    r"(?:on top(?: of your library)?|(?P<third>third from the top))"
)


def _search_mv_qualifier_from_match(m: re.Match[str]) -> dict:
    """The trailing "with mana value X or less/greater" qualifier, if
    present — shared by `_SEARCH_CRITERIA` and `_SEARCH_ZONE_CRITERIA`,
    both of which name their groups ``mv``/``mv_cmp`` identically."""
    mv = m.groupdict().get("mv")
    if not mv:
        return {}
    n: Any = int(mv) if mv != "x" else "x"
    key = "max_mana_value" if m.groupdict().get("mv_cmp") == "less" else "min_mana_value"
    return {key: n}


def _search_color_from_match(m: re.Match[str]) -> Optional[str]:
    """The captured ``color`` group → a WUBRG letter, ``"colorless"``
    (`_SEARCH_COLOR_WORD`'s own local addition — see its docstring for why
    this isn't `resolve_color_word`), or ``None``."""
    word = (m.groupdict().get("color") or "").strip().lower()
    if word == "colorless":
        return "colorless"
    return resolve_color_word(word)


def _search_criteria_from_match(m: re.Match[str]) -> dict:
    crit: dict = {}
    basic = bool(m.groupdict().get("basic"))
    if basic:
        crit["basic"] = True
    subtype = m.groupdict().get("subtype")
    if subtype:
        crit["type"] = subtype.strip().lower()
    if m.groupdict().get("aura"):
        crit["type"] = "Aura"
    types = m.groupdict().get("types")
    if types:
        words = [t.strip() for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", types) if t.strip()]
        # Bare "basic land" stays `{"basic": True}` alone (pre-existing
        # shape, Rampant Growth) — "land" is redundant once `basic` is set
        # (every basic card is a land), so it's only kept as a `type` filter
        # when it names something *besides* plain "land" ("a basic Forest,
        # Plains, or Island card" — the Panorama/Landscape/Monument tri-land
        # cycles, `_SEARCH_CRITERIA`'s combined basic+type-list shape).
        if not (basic and words == ["land"]):
            crit["type"] = words if len(words) > 1 else words[0]
    color = _search_color_from_match(m)
    if color:
        crit["color"] = color
    crit.update(_search_mv_qualifier_from_match(m))
    return crit


def _search_count_from_match(m: re.Match[str]) -> Optional[int]:
    count = m.groupdict().get("count")
    return int(count) if count is not None else None


def _search_put_then_shuffle(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    params: dict = {"criteria": _search_criteria_from_match(m), "destination": destination}
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: Elfhame Sanctuary's optional basic-land search has a reflexive "If you
#: do" tail.  Keep the tail on the asynchronous search itself so it resolves
#: after the player accepts the search, rather than immediately beside the
#: choice-opening effect.
_ELFHAME_SANCTUARY_RE = _c(
    r"(?:you may )?search your library for a basic land card, reveal it, put it into your hand, "
    r"then shuffle\. if you do, you skip your draw step this turn\.?"
)


def _elfhame_sanctuary(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("search", {
        "criteria": {"basic": True, "types": ["land"]},
        "destination": "hand",
        "then_specs": [{"type": "skip_next_step", "params": {"step": "draw"}}],
    })]


def _search_put_then_shuffle_share_type(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    params: dict = {
        "criteria": _search_criteria_from_match(m),
        "destination": destination,
        "share_land_type": True,
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library for a card with mana value less than or equal to the
#: number of lands you control, [reveal <pronoun>,] put <pronoun>
#: <destination>, then shuffle." (Beseech the Queen, MEC-43 round 3) — a
#: board-count mana-value bound instead of `_SEARCH_CRITERIA`'s own literal
#: digit/``x`` (`_SEARCH_MV_QUALIFIER`), so it's its own regex rather than a
#: fourth `_SEARCH_MV_QUALIFIER` alternative; maps onto `"search"`'s
#: ``mana_value_from`` param with the new ``"count_selector"`` source
#: (`SearchLibraryEffect._resolved_criteria`, `continuous.count_selector`'s
#: existing ``"lands_you_control"`` entry).
_SEARCH_MV_LANDS_QUALIFIER_RE = _c(
    r"search your library for a card with mana value less than or equal to "
    r"the number of lands you control,?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_mv_lands_qualifier(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    return [
        EffectSpec(
            "search",
            {
                "criteria": {},
                "mana_value_from": {"source": "count_selector", "count_selector": "lands_you_control"},
                "destination": destination,
            },
        )
    ]


#: "search your library for a snow permanent card, a legendary card, or a
#: Saga card, [reveal <pronoun>,] put <pronoun> <destination>, then
#: shuffle." (Search for Glory, MEC-43 round 3) — a three-way OR across
#: disjoint criteria shapes (a "snow" supertype card that's also a
#: *permanent*, vs. two plain type-line substrings) `_SEARCH_CRITERIA`'s own
#: single type-list grammar can't express, so it's its own regex mapped
#: straight onto `models.cards.card_query`'s already-general ``"or"`` combinator —
#: "snow permanent" is ``{"type": "Snow", "without_type": ["Instant",
#: "Sorcery"]}`` (RULE 205.4g's supertype, minus the two non-permanent card
#: types). This card's own trailing life-gain sentence is a wholly separate
#: clause (`_GAIN_LIFE_PER_SNOW_SPENT_RE` below), reached independently by
#: the segmenter's own period-connector split, not by this regex.
_SEARCH_SNOW_LEGENDARY_SAGA_RE = _c(
    r"search your library for a snow permanent card, a legendary card, or a saga card,?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_snow_legendary_saga(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    criteria = {
        "or": [
            {"type": "Snow", "without_type": ["Instant", "Sorcery"]},
            {"type": "Legendary"},
            {"type": "Saga"},
        ]
    }
    return [EffectSpec("search", {"criteria": criteria, "destination": destination})]


#: "You gain 1 life for each {S} spent to cast this spell." (Search for
#: Glory's own trailing sentence) — reads `GameObject.mana_spent_to_cast_
#: snow` (MEC-43 round 3, `ManaPool.snow_pool`) via the already-general
#: ``"gain_life"`` `count_selector` hook (`continuous.count_selector`'s new
#: ``"snow_mana_spent_to_cast"`` entry), the same self-referential idiom
#: `sacrificed_cost_mana_value`/`sacrificed_cost_power` already use. Scoped
#: to the literal "1 life" this card prints — no known card scales the
#: amount, so a multiplier is left unbuilt rather than guessed at.
_GAIN_LIFE_PER_SNOW_SPENT_RE = _c(r"you gain 1 life for each \{s\} spent to cast this spell")


def _gain_life_per_snow_spent(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"count_selector": "snow_mana_spent_to_cast"})]


#: "search your library for <criteria>, put <pronoun> onto the battlefield,
#: attach it to a creature you control, then shuffle." (Stonehewer Giant/
#: Quest for the Holy Relic-shaped combined search-then-attach — MEC-12
#: sixth pass) — a strict superset of `_SEARCH_PUT_THEN_SHUFFLE_RE`'s own
#: "put <pronoun> onto the battlefield, then shuffle" shape with the attach
#: clause spliced in, mapped onto `"search"`'s new
#: ``attach_to_creature_you_control`` param (`SearchLibraryEffect`).
#: Destination is always the battlefield (the attach clause presupposes
#: it), so unlike the plain family this doesn't need a `dest` capture group.
_SEARCH_PUT_ATTACH_THEN_SHUFFLE_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} onto the battlefield,?\s*"
    r"attach it to a creature you control,?\s*"
    r"then shuffle"
)


def _search_put_attach_then_shuffle(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "criteria": _search_criteria_from_match(m),
        "destination": "battlefield",
        "attach_to_creature_you_control": True,
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


def _search_shuffle_then_put_top(m: re.Match[str]) -> list[EffectSpec]:
    destination = "library_third" if m.groupdict().get("third") else "library_top"
    params: dict = {"criteria": _search_criteria_from_match(m), "destination": destination}
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library for up to N basic land cards, reveal those cards,
#: put one <destA> and the other <destB>, then shuffle." (Cultivate/Kodama's
#: Reach-shaped split destination — RULE 701.19 same as the plain family
#: above, just two different destinations for the two picks instead of one
#: shared `destination`; maps onto `"search"`'s `destinations` param,
#: positional against the picks).
_SEARCH_SPLIT_DESTINATION_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    # "one" is folded to "1" by `normalize`'s spelled-number pass (it can't
    # tell this "one" is a pronoun, not a count) — match the folded form.
    rf"put 1 (?P<dest1>{_SEARCH_DESTINATION_ALT}) and the other "
    rf"(?P<dest2>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_split_destination(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dest1 = _search_destination_kind(m.group("dest1"))
    dest2 = _search_destination_kind(m.group("dest2"))
    if dest1 is None or dest2 is None:
        return None
    params: dict = {
        "criteria": _search_criteria_from_match(m),
        "destination": dest1,
        "destinations": [dest1, dest2],
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library for N cards. Put 1 <destA> and the other <destB>.
#: Then shuffle." (Final Parting, MEC-43 round 3) — the same split
#: destination as `_SEARCH_SPLIT_DESTINATION_RE` just above, but printed as
#: three plain sentences (bare "N cards", no criteria/reveal clause) instead
#: of one comma-joined one, so it needs its own literal ``\.\s*`` sentence
#: boundaries rather than reusing `_SEARCH_CRITERIA`/`_SEARCH_REVEAL` (same
#: idiom `_SEARCH_EXILE_REST_RE` below already uses for its own two-sentence
#: Doomsday shape).
_SEARCH_TWO_CARDS_SPLIT_RE = _c(
    r"search your library for (?P<count>\d+) cards?\.\s*"
    rf"put 1 (?P<dest1>{_SEARCH_DESTINATION_ALT}) and the other "
    rf"(?P<dest2>{_SEARCH_DESTINATION_ALT})\.\s*"
    r"then shuffle"
)


def _search_two_cards_split(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dest1 = _search_destination_kind(m.group("dest1"))
    dest2 = _search_destination_kind(m.group("dest2"))
    if dest1 is None or dest2 is None:
        return None
    return [
        EffectSpec(
            "search",
            {
                "criteria": {},
                "destination": dest1,
                "destinations": [dest1, dest2],
                "count": int(m.group("count")),
            },
        )
    ]


#: The criteria noun phrase for a "library and/or graveyard" search — same
#: basic-land/type-list alternatives as `_SEARCH_CRITERIA`, plus a bare-name
#: alternative ("a card named <Name>") this family's real cards lean on
#: heavily (planeswalker/background tutors); restricted to a name with no
#: internal comma (see the module docstring above for why).
_SEARCH_ZONE_CRITERIA = (
    r"(?:up to (?P<count>\d+)|an?)\s+"
    rf"(?:(?P<color>{_SEARCH_COLOR_WORD})\s+)?"
    r"(?:"
    r"(?P<basic>basic land) cards?"
    rf"|card named (?P<name>[a-z][a-z' -]*?)"
    rf"|(?P<types>{_SEARCH_TYPE_LIST}) cards?"
    r"|cards?"
    r")"
    + _SEARCH_MV_QUALIFIER
)
#: "search your library and/or graveyard for <criteria>, [reveal <pronoun>,]
#: [and] put <pronoun> <destination>. If you search[ed] your library this
#: way, shuffle." (RULE 701.19 "and/or" combined-zone search — the
#: backgrounds/planeswalker-tutor family: Delivery Moogle/Tale of Momo/
#: Elspeth Undaunted Hero/Tower Winder/…). Unlike the library-only family's
#: "then shuffle" tail, the shuffle here is conditional on *which* zone hit
#: — engine-side this maps onto `RulesEngine._finish_search` always
#: shuffling whenever ``"library"`` is among ``zones`` (a documented
#: simplification: it doesn't track which specific zone the chosen card(s)
#: actually came from).
_SEARCH_ZONE_PUT_RE = _c(
    rf"search your library and/or graveyard for {_SEARCH_ZONE_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"(?:and\s+)?put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT})\.\s*"
    r"if you search(?:ed)? your library this way,?\s*shuffle"
)


def _search_zone_criteria_from_match(m: re.Match[str]) -> dict:
    if m.groupdict().get("basic"):
        crit: dict = {"basic": True}
    else:
        name = m.groupdict().get("name")
        if name:
            return {"name": name.strip()}  # a named-card search ignores colour/mv qualifiers
        crit = {}
        types = m.groupdict().get("types")
        if types:
            words = [t.strip() for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", types) if t.strip()]
            crit["type"] = words if len(words) > 1 else words[0]
    color = _search_color_from_match(m)
    if color:
        crit["color"] = color
    crit.update(_search_mv_qualifier_from_match(m))
    return crit


def _search_zone_put(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    params: dict = {
        "criteria": _search_zone_criteria_from_match(m),
        "destination": destination,
        "zones": ["library", "graveyard"],
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library [and graveyard] for N cards and exile the rest. Put
#: the chosen cards on top of your library in any order." (Doomsday-shaped —
#: no "then shuffle" at all: RULE 701.19e's shuffle is for an *ordinary*
#: search, and this one's own text never calls for one). Maps onto
#: `"search"`'s ``exile_rest``/``count``/``destination="library_top"``.
_SEARCH_EXILE_REST_RE = _c(
    r"search your library(?P<gy> and (?:your )?graveyard)? for "
    r"(?P<count>\d+) cards? and exile the rest\.\s*"
    r"put the chosen cards? on top of your library in any order"
)


def _search_exile_rest(m: re.Match[str]) -> list[EffectSpec]:
    zones = ["library", "graveyard"] if m.group("gy") else ["library"]
    return [
        EffectSpec(
            "search",
            {
                "criteria": {},
                "destination": "library_top",
                "count": int(m.group("count")),
                "exile_rest": True,
                "zones": zones,
            },
        )
    ]


#: "An opponent gains control of ~." (Wishclaw Talisman-shaped — RULE
#: 701.10-adjacent; `game/effects/core.py`'s `GainControlBySourceEffect`).
_GAIN_CONTROL_BY_OPPONENT_RE = _c(
    rf"an opponent gains control of {_SELF_SUBJECT}"
)


def _gain_control_by_opponent(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_control_by_source", {"recipient": "opponent"})]


#: RULE 108.4-adjacent "threaten" effect — "Gain control of target creature
#: until end of turn." (Act of Treason/Act of Aggression/Claim the
#: Firstborn-shaped — the single most-repeated effect template in the whole
#: cache, ~90 real cards). `effects.GainControlUntilEndOfTurnEffect` already
#: bundles the control change, untap, and haste grant into one atomic effect
#: (built for the hand-authored Zealous Conscripts); this only teaches the
#: parser the oracle-text shape, including its optional "with mana value N
#: or less" cap (Claim the Firstborn, `TargetSpec.max_mana_value`, the same
#: param `destroy_mv` uses). The trailing "Untap that creature[.] It gains
#: haste until end of turn." pair is recognized separately, in `segmenter.
#: parse_effect_body` (`_GAIN_CONTROL_HASTE_TAIL_RE`) — it's not a second
#: effect, just the card restating in words what this one already does, so
#: it's absorbed there rather than re-parsed into a second (redundant, and
#: RULE-115-target-doubling-risky) untap/haste effect here.
_GAIN_CONTROL_EOT_RE = _c(
    rf"gain control of (?P<another>another )?{TARGET}"
    r"(?: with power (?P<pn>\d+) or (?P<pcmp>less|greater))?"
    r"(?: with mana value (?P<mv>\d+) or less"
    # PAR-74: "…with **that spell's** mana value." (Skyfire Kirin) — the
    # exact-match sibling of the literal-digit ceiling just above,
    # `TargetSpec.exact_mana_value`'s own sentinel resolution.
    r"|(?P<trigger_mv> with that spell'?s mana value))? until end of turn"
)


def _gain_control_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, (
        "creature", "creature_you_dont_control", "permanent", "artifact",
    )):
        return None
    params: dict = {"target_kind": kind, **_optional_param(m)}
    if m.group("mv"):
        params["max_mana_value"] = int(m.group("mv"))
    if m.groupdict().get("trigger_mv"):
        params["exact_mana_value"] = "trigger_spell_mana_value"
    # "gain control of target creature an opponent controls **with power N
    # or less/greater**" (Enthralling Victor) — a target-offer-time filter,
    # RULE 115.1c. "another" (Akroan Conscriptor) is accepted but its RULE
    # 601.2c self-exclusion isn't enforced (documented simplification —
    # these are all trigger/ETB bodies with no reason to grab the source).
    if m.group("pn"):
        key = "max_power" if m.group("pcmp") == "less" else "min_power"
        params["creature_filter"] = {key: int(m.group("pn"))}
    return [EffectSpec("gain_control_until_eot", params)]


#: PAR-130: the **no-duration** steal — "gain control of target artifact"
#: (Keiga, Ritual of the Machine, Souvenir Snatcher), "for each opponent, gain
#: control of target permanent that player controls" (Blatant Thievery) —
#: RULE 611.2's indefinite control change, the ``duration="permanent"`` mode of
#: the same effect (untap/haste off; built for Entrancing Melody). An "Untap
#: it." restatement right after it turns the untap on (Invoke the Winds). A
#: duration ("until end of turn", "for as long as …") never reaches this row:
#: the full match leaves it unclaimed for its own row.
_GAIN_CONTROL_PERMANENT_RE = _c(
    rf"gain control of (?P<another>another )?{TARGET}"
    r"(?: with power (?P<pn>\d+) or (?P<pcmp>less|greater))?"
    r"(?: with mana value (?P<mv>\d+) or less)?"
    r"(?P<untap>\.\s*untap (?:it|that (?:creature|permanent|artifact|land)))?"
)
#: What a permanent steal may take — permanents only (a spell is
#: `gain_control_of_spell`'s), incl. any controller-scoped narrowing.
_GAIN_CONTROL_PERMANENT_KINDS = (
    "permanent", "nonland_permanent", "creature", "creature_or_planeswalker", "artifact",
    "enchantment", "land", "artifact_or_creature", "artifact_or_enchantment",
)


def _gain_control_permanent(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _GAIN_CONTROL_PERMANENT_KINDS):
        return None
    params: dict = {
        "target_kind": kind, **_optional_param(m),
        "duration": "permanent", "haste": False, "untap": bool(m.group("untap")),
    }
    if m.group("mv"):
        params["max_mana_value"] = int(m.group("mv"))
    if m.group("pn"):
        key = "max_power" if m.group("pcmp") == "less" else "min_power"
        params["creature_filter"] = {key: int(m.group("pn"))}
    return [EffectSpec("gain_control_until_eot", params)]


#: The untargeted mass sibling — "Untap all creatures and gain control of
#: them until end of turn. They gain haste until end of turn." (Insurrection)
#: — RULE 601.2c's "all creatures" over the same `GainControlUntilEndOfTurnEffect`,
#: `selector="all_creatures"` (`effects._mass_selector_objects`). A whole-body
#: match (both sentences, like `_DESTROY_ALL_NO_REGEN_RE`) rather than the
#: `_GAIN_CONTROL_HASTE_TAIL_RE` two-step above, since the only real card
#: printing this exact mass shape has nothing before or after it to split on.
_GAIN_CONTROL_ALL_RE = _c(
    r"untap all creatures and gain control of them until end of turn\."
    r"\s*they gain haste until end of turn"
)


def _gain_control_all(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_control_until_eot", {"selector": "all_creatures"})]


#: "For each opponent, gain control of up to 1 target creature that player
#: controls until end of turn. Untap those creatures. They gain haste until
#: end of turn." (Mass Mutiny / Molten Primordial / Mob Rule-shaped) — the
#: one-requirement-per-opponent RULE 601.2c count, the same `count_selector`
#: shape `_goad_per_opponent` uses, over the multi-target
#: `GainControlUntilEndOfTurnEffect` (its `apply` now iterates every chosen
#: target, not just the first). A whole-body match like `_GAIN_CONTROL_ALL_
#: RE` — the untap/haste restatement is the same "the effect already does
#: this" tail `_GAIN_CONTROL_HASTE_TAIL_RE` absorbs.
_GAIN_CONTROL_EOT_PER_OPPONENT_RE = _c(
    r"for each opponent, gain control of up to (?:one|1) target creature "
    r"that player controls until end of turn\.\s*"
    r"untap (?:those creatures|them)\.\s*they gain haste until end of turn"
)


def _gain_control_eot_per_opponent(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_control_until_eot", {
        "target_kind": "creature_you_dont_control",
        "optional": True,
        "count_selector": "opponents",
    })]


#: PAR-30 "Threaten … tails residue" — the *opponent-scoped mass* threaten,
#: the other end from `_GAIN_CONTROL_ALL_RE`'s "all creatures": "Gain
#: control of all <type> [your opponents / target opponent] control[s] until
#: end of turn. Untap them. They gain haste until end of turn." (Broadcast
#: Takeover — artifacts, all opponents; Call for Aid — creatures, one
#: targeted opponent, + the two anti-abuse riders below). A whole-body
#: match like its siblings above; the untap/haste restatement is the same
#: "the effect already does this" tail.
_GAIN_CONTROL_MASS_EOT_RE = _c(
    r"gain control of all (?P<mtype>creatures|artifacts|nonland permanents|permanents) "
    r"(?P<who>your opponents control|target opponent controls) until end of turn\.\s*"
    r"untap (?:them|those creatures|those permanents|those artifacts)\.\s*"
    r"they gain haste until end of turn"
    r"(?P<riders>(?:\.\s*you can'?t [^.]+)*)\.?"
)

_MASS_OPPONENT_SELECTORS: dict[str, str] = {
    "creatures": "opponents_creatures",
    "artifacts": "opponents_artifacts",
}
_MASS_NO_SAC_RE = re.compile(
    r"you can'?t sacrifice (?:those creatures|them) this turn", re.IGNORECASE
)
_MASS_NO_ATTACK_RE = re.compile(
    r"you can'?t attack that player this turn", re.IGNORECASE
)


def _gain_control_mass_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    mtype = m.group("mtype")
    riders = (m.groupdict().get("riders") or "").strip()
    no_sac = bool(_MASS_NO_SAC_RE.search(riders))
    no_attack = bool(_MASS_NO_ATTACK_RE.search(riders))
    # Fail closed if a rider sentence is present that isn't one of the two
    # we model (RULE never-half-model).
    leftover = _MASS_NO_SAC_RE.sub("", _MASS_NO_ATTACK_RE.sub("", riders))
    if re.sub(r"[.\s]", "", leftover):
        return None

    if m.group("who") == "target opponent controls":
        # One RULE 115 opponent target, then every creature/artifact that
        # player controls (`GainControlUntilEndOfTurnEffect.mass_of_target_
        # player`). Only the two real printed type words.
        if mtype not in ("creatures", "artifacts"):
            return None
        params: dict = {"target_kind": "opponent", "mass_of_target_player": mtype[:-1]}
        if no_sac:
            params["mark_no_sacrifice"] = True
        out = [EffectSpec("gain_control_until_eot", params)]
        if no_attack:
            out.append(EffectSpec("prevent_attacking_player_this_turn", {}))
        return out

    if no_sac or no_attack:
        return None  # the riders name "that player" — only the targeted form
    sel = _MASS_OPPONENT_SELECTORS.get(mtype)
    if sel is None:
        return None  # "permanents" — no `opponents_permanents` selector, fail closed
    return [EffectSpec("gain_control_until_eot", {"selector": sel})]


#: "Whenever a player casts an instant or sorcery spell, that player
#: copies it and may choose new targets for the copy [until end of turn]."
#: (Bonus Round) — RULE 603.1's "it"/"that player" both name the *firing
#: trigger event* rather than a RULE 601.2c target choice, unlike every
#: other `copy_spell` card in scope (Dualcaster Mage-shaped, which really
#: does target). `CopySpellEffect.spell_from_trigger_event`/
#: `controller_from_trigger_event` read the SPELL_CAST event's own
#: ``instance_id``/``player_id`` instead of a target list — the same
#: "resolve off the firing event" idiom `DestroyEffect.
#: target_from_trigger_event` already established (Mikaeus, the
#: Unhallowed). "may choose new targets" is the same accepted
#: simplification `CopySpellEffect`'s own docstring already documents for
#: every card in this family (the copy keeps the original's targets, no
#: retarget prompt) — not a new gap this card introduces.
_TRIGGER_COPY_SPELL_RE = _c(
    r"that player copies it and may choose new targets for the copy(?: until end of turn)?"
)

#: "Copy target instant or sorcery spell you control. You may choose new
#: targets for the copy." (Dual Casting).  The controller qualifier is a
#: target-legality restriction, not merely a note about who controls the
#: resulting copy, so it uses the dedicated ``spell_you_control`` target
#: kind rather than the broader `copy_spell` default.
_COPY_YOUR_INSTANT_OR_SORCERY_RE = _c(
    r"copy target instant or sorcery spell you control\.?"
    r"(?:\s*you may choose new targets for the copy\.?)?"
)


def _copy_your_instant_or_sorcery(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("copy_spell", {
        "card_types": ["instant", "sorcery"], "target_kind": "spell_you_control",
    })]


#: "Each instant and sorcery card in your graveyard gains flashback until
#: end of turn. The flashback cost is equal to its mana cost." (Past in
#: Flames/Will of the Jeskai-shaped — the untargeted "each" sibling of
#: `_GRANT_FLASHBACK_TARGET_RE` below). `GrantGraveyardCastPermissionThisTurnEffect`
#: already exists (built for Backdraft Hellkite's identical wording) — this
#: is purely the missing oracle-text recognizer for a *second* card using
#: the same primitive, per the project's "sweep for what else a new
#: primitive closes" discipline.
_GRANT_FLASHBACK_EACH_RE = _c(
    r"each instant and sorcery card in your graveyard gains flashback until end of turn\.\s*"
    r"the flashback cost is equal to its mana cost"
)


def _grant_flashback_each(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_graveyard_cast_permission_this_turn", {})]


#: "Target instant or sorcery card in your graveyard gains flashback until
#: end of turn. The flashback cost is equal to its mana cost." (MEC-24 —
#: Recoup/Snapcaster Mage/Slickshot Lockpicker/Sphinx of Forgotten Lore/
#: Katilda and Lier-shaped) — the *targeted*, single-card sibling of
#: `_GRANT_FLASHBACK_EACH_RE` above, needing a genuinely different
#: primitive (`grant_flashback_to_target`/`GameState.temp_flashback_grants`
#: — see that effect's own docstring for why the untargeted marker doesn't
#: fit) rather than reusing `grant_graveyard_cast_permission_this_turn`.
#: Reuses the graveyard-recursion family's own `_GRAVEYARD_TYPE_WORD`/
#: `_GRAVEYARD_SCOPE_WORD`/`_graveyard_target_kind` vocabulary (word order
#: is "target ... card **in** ... graveyard", not "**from** ... graveyard"
#: like the recursion family, so this is its own regex rather than a shared
#: one). The trailing "the flashback cost is equal to [that card's/its]
#: mana cost" sentence is optional and dropped once matched — it's not a
#: second effect, just prose restating what "gains flashback" (with no
#: literal cost) already means; when a literal cost **is** given inline
#: instead (The Fugitive Doctor's "gains flashback {2}{R}{G} until end of
#: turn", no such sentence at all), ``cost`` carries it and overrides the
#: "equal to its mana cost" default `GrantFlashbackToTargetEffect` falls
#: back to.
_GRANT_FLASHBACK_TARGET_RE = _c(
    rf"target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card in "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard gains flashback"
    r"(?: (?P<cost>(?:\{[^}]+\})+))? until end of turn\.?"
    r"(?:\s*the flashback cost is equal to (?:that card'?s|its) mana cost\.?)?"
)


def _grant_flashback_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind}
    if m.groupdict().get("cost"):
        params["cost"] = m.group("cost")
    return [EffectSpec("grant_flashback_to_target", params)]


#: "The next [creature] spell you cast this turn can't be countered." (Mistrise Village,
#: Insist, Overmaster) and "[Creature] spells you control|cast [this turn] can't be
#: countered [this turn]." (Veil of Summer, Domri, Anarch of Bolas) — a continuous effect
#: for the rest of the turn (`cant_be_countered_this_turn`, an `UncounterableGrant`), not a
#: trigger on the cast: it also protects a spell already on the stack, and an opponent gets
#: no window to respond to it. A bare "spells you control can't be countered." with no "this
#: turn" is a static ability and stays out of this row.
_UNCOUNTERABLE_TYPE_WORD = r"(?:creature|artifact|enchantment|instant|sorcery|planeswalker|land)"
_UNCOUNTERABLE_TYPES = (
    rf"{_UNCOUNTERABLE_TYPE_WORD}(?:(?:, | or | and |, or |, and ){_UNCOUNTERABLE_TYPE_WORD})*"
)
_UNCOUNTERABLE_THIS_TURN_RE = _c(
    rf"(?:the next (?:(?P<next_types>{_UNCOUNTERABLE_TYPES}) )?spell you cast this turn"
    rf"|(?:(?P<types_a>{_UNCOUNTERABLE_TYPES}) )?spells you control"
    rf"|(?:(?P<types_b>{_UNCOUNTERABLE_TYPES}) )?spells you cast this turn)"
    r"(?P<tail> this turn)? can'?t be countered(?: this turn)?"
)


def _cant_be_countered_this_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    next_only = m.group("next_types") is not None or m.group(0).lower().startswith("the next")
    if not next_only and "this turn" not in m.group(0).lower():
        return None
    words = m.group("next_types") or m.group("types_a") or m.group("types_b")
    params: dict = {}
    if words:
        params["card_types"] = re.findall(_UNCOUNTERABLE_TYPE_WORD, words.lower())
    if next_only:
        params["next_only"] = True
    return [EffectSpec("cant_be_countered_this_turn", params)]


#: "Look at the top card of target player's library." (Mishra's Bauble) /
#: "Look at a card at random in target player's hand." (Urza's Bauble) — a
#: genuine RULE 115 target with no other game-state consequence, see
#: `LookAtCardsEffect`'s own docstring for why. Two narrow, closed phrasings
#: (not "look at *any* card X") rather than a general "look at" grammar —
#: the only two real cards printing this in the cache.
_LOOK_AT_TARGET_RE = _c(
    r"look at (?:the top card of target player's library"
    r"|a card at random in target player's hand)"
)


def _look_at_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("look_at_cards", {"target_kind": "player"})]


#: PAR-124: "When you next cast an instant or sorcery spell this turn,
#: **conjure a duplicate of that spell into your hand**." (Spellchain
#: Scatter) — the hand-zone sibling of `_COPY_THAT_SPELL_RE` just below:
#: "that spell" is the identical RULE 603.1 firing-event referent
#: (`ConjureDuplicateIntoHandEffect.spell_from_trigger_event`), just landing
#: in hand rather than being copied onto the stack.
_CONJURE_DUPLICATE_INTO_HAND_RE = _c(r"conjure a duplicate of that spell into your hand")


def _conjure_duplicate_into_hand(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("conjure_duplicate_into_hand", {"spell_from_trigger_event": "instance_id"})]


#: "When you next cast an instant or sorcery spell this turn, **copy that spell**. You may
#: choose new targets for the copy." (Doublecast, Galvanic Iteration, Teach by Example, Dual
#: Strike) — the copier is the trigger's controller and "that spell" is the one that fired it
#: (`CopySpellEffect.spell_from_trigger_event`). "twice"/"N times" is the copy count; "X times"
#: (Storm King's Thunder) is this ability's *own* announced {X} — a literal string here, not yet
#: a number, since the value isn't known until the spell that carries this ability is cast, well
#: before it fires (`_substitute_x`'s nested walk into `CreateTurnTriggerEffect.inner_specs`
#: resolves the sentinel at that earlier point). "an additional time" (Howl of the Horde's own
#: Raid-gated second ability) makes one more copy on top of whatever an unconditional sibling
#: instance of this same trigger already grants — from this instance's own perspective that is
#: just an ordinary single copy, same as no suffix at all.
_COPY_THAT_SPELL_RE = _c(
    r"copy (?:that spell|it)(?: (?P<n>twice|x times|an additional time|\d+ times))?\.\s*"
    r"you may choose new targets for the cop(?:y|ies)"
)


def _copy_that_spell(m: re.Match[str]) -> list[EffectSpec]:
    word = m.group("n")
    params: dict = {"spell_from_trigger_event": "instance_id"}
    if word == "x times":
        params["count"] = "x"
    elif word not in (None, "an additional time"):
        count = 2 if word == "twice" else int(word.split()[0])
        if count != 1:
            params["count"] = count
    return [EffectSpec("copy_spell", params)]


def _trigger_copy_spell(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec(
            "copy_spell",
            {
                "spell_from_trigger_event": "instance_id",
                "controller_from_trigger_event": "player_id",
            },
        )
    ]


#: "Shuffle ~ into its owner's library." (RULE 701.20 — Green Sun's Zenith's
#: own trailing sentence, overriding the spell's default RULE 608.2m
#: "goes to the graveyard as it resolves" routing; `game/effects/core.py`'s
#: `ShuffleSelfIntoLibraryEffect`).
_SHUFFLE_SELF_INTO_LIBRARY_RE = _c(
    rf"shuffle {_SELF_SUBJECT} into its owner'?s library"
)
#: ENG-32 (Watery Grasp) — the Aura-host form: "Enchanted creature's owner
#: shuffles it into their library."
_SHUFFLE_ENCHANTED_INTO_LIBRARY_RE = _c(
    r"enchanted creature'?s owner shuffles it into (?:their|its owner'?s) library"
)


def _shuffle_self_into_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("shuffle_self_into_library", {})]


def _shuffle_enchanted_into_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("shuffle_self_into_library", {"subject": "attached_permanent"})]


#: "attach it to target creature you control" / "attach ~ to target creature
#: you control" (an Equipment's own ETB self-attach, RULE 303.4f-adjacent —
#: `AttachEffect` already exists for Equip's activated ability, reused here).
def _attach(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("permanent", "creature", "creature_you_control")):
        return None
    params: dict = {"target_kind": kind}
    # "attach it to target legendary creature you control" (Mithril Coat, Mjölnir): the destination's qualifier
    # rides as the same `creature_filter` the Equip-restricted-to-commanders form uses.
    filt = resolve_target_creature_state_filter(m.group("target"))
    if filt:
        params["creature_filter"] = filt
    return [EffectSpec("attach", params)]


#: PAR-135: "attach target Equipment [you control] to target creature [you control]" (Magnetic Theft,
#: Auriok Windwalker, Kor Outfitter) and its variants — `AttachChosenEffect`, the two-requirement
#: effect Brass Squire and Halvar were hand-authored onto. The *moved* half is "[up to one |any number of]
#: target Equipment"; the destination is a second target ("to up to one target creature you control",
#: "to target attacking creature") or not a target at all ("to ~", "to it" under a self/group/attached
#: subject, "to that creature" after an earlier pick) — `to_subject`, the vocabulary `FightEffect` reads.
_ATTACH_WHAT = rf"(?:(?P<any_number>any number of )(?P<multi>target equipment(?: you control)?)|{TARGET})"
_ATTACH_TO_TARGET_KINDS: frozenset[str] = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control", "other_creature_you_control"}
)
_ATTACH_WHAT_KINDS: frozenset[str] = frozenset({
    "equipment", "equipment_you_control", "equipment_you_dont_control", "equipment_that_player_controls",
})


def _attach_what_params(m: re.Match[str]) -> Optional[dict]:
    """The moved Equipment's half of an `attach_chosen` clause."""
    if m.group("multi"):
        kind = resolve_target_kind(m.group("multi"))
        params: dict = {"what_count": _ANY_NUMBER_TARGET_CAP, "what_optional": True}
    else:
        kind = resolve_target_kind(m.group("target"))
        params = {"what_optional": True} if target_is_optional(m) else {}
    if kind not in _ATTACH_WHAT_KINDS:
        return None
    return {"what_kind": kind, **params}


def _attach_chosen_to_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _attach_what_params(m)
    to_kind = resolve_target_kind(m.group("target_b"))
    if params is None or not target_kind_allowed(to_kind, _ATTACH_TO_TARGET_KINDS):
        return None
    params["to_kind"] = to_kind
    if target_is_optional(m, "_b"):
        params["to_optional"] = True
    filt = resolve_target_creature_state_filter(m.group("target_b"))
    if filt:
        params["creature_filter"] = filt
    return [EffectSpec("attach_chosen", params)]


def _attach_chosen_to_subject(subject: str):
    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        params = _attach_what_params(m)
        if params is None:
            return None
        return [EffectSpec("attach_chosen", {**params, "to_subject": subject})]

    return build


_ATTACH_CHOSEN_TO_TARGET_RE = _c(rf"attach {_ATTACH_WHAT} to {target_macro('_b')}")
_ATTACH_CHOSEN_TO_SOURCE_RE = _c(rf"attach {_ATTACH_WHAT} to ~")
_ATTACH_CHOSEN_TO_PRONOUN_RE = _c(rf"attach {_ATTACH_WHAT} to (?:it|her|him)")
_ATTACH_CHOSEN_TO_THAT_RE = _c(rf"attach {_ATTACH_WHAT} to (?:it|that creature)")
_ATTACH_CHOSEN_TO_IT_RE = _c(rf"attach {_ATTACH_WHAT} to it")


# --- RULE 701.14 fight ------------------------------------------------------
# "Target creature you control fights target creature you don't control."
# (Prey Upon), "it fights up to one target creature you don't control."
# (Kogla's ETB), "when this Aura enters, enchanted creature fights …" — one
# `fight` effect (`game/effects/core.py`'s `FightEffect`) in all three, differing
# only in who the *fighter* is.

#: The target kinds a fight clause may name. Both fighters must be creatures
#: (RULE 701.14a), so a `TARGET` row resolving to anything else — "any
#: target", "target permanent" — leaves the clause unclaimed rather than
#: widening the fight to a non-creature.
_FIGHT_TARGET_KINDS: frozenset[str] = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control"}
)

#: The second requirement's `TARGET`, group-renamed so both fit one regex.
_TARGET_B = target_macro("_b")

#: RULE 109.5's "**another** target creature", which means one of two
#: different things depending on who the *other* fighter is:
#:
#: * against an **implicit** fighter (the source, an Aura's host) it excludes
#:   that permanent — already what the engine's plain ``creature`` kind means
#:   (`targeting.legal_targets` unconditionally drops the ability's own
#:   source), and `_another_kind` narrows a "…you control" phrase to the
#:   dedicated `other_creature_you_control` kind for the same reason;
#: * against a **chosen** fighter (the two-target form, or a pronoun pointing
#:   back at the previous clause's pick) it excludes *that target*, which is
#:   `TargetSpec.distinct_from_others` — an across-requirements constraint,
#:   enforced at offer time by the board and backstopped in `FightEffect`.
_ANOTHER = r"(?P<another>another )?"

#: The same phrase in the second slot of a two-target clause ("target
#: creature you control fights **another** target creature"), where the
#: group has to carry its own name.
_ANOTHER_B = r"(?P<another_b>another )?"


def _fight_kind(phrase: str) -> Optional[str]:
    kind = resolve_target_kind(phrase)
    return kind if target_kind_allowed(kind, _FIGHT_TARGET_KINDS) else None


def _another_kind(kind: str) -> str:
    """RULE 109.5 against an implicit fighter: "another target creature you
    control" is the `other_creature_you_control` kind; a bare "another target
    creature" needs no narrowing (``creature`` already excludes the source)."""
    return "other_creature_you_control" if kind == "creature_you_control" else kind


def _fight(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    fighter = _fight_kind(m.group("target"))
    other = _fight_kind(m.group("target_b"))
    if fighter is None or other is None:
        return None
    params: dict = {"fighter_kind": fighter, "other_kind": other}
    if target_is_optional(m):
        params["fighter_optional"] = True
    if target_is_optional(m, "_b"):
        params["optional"] = True
    if m.groupdict().get("another_b"):
        params["distinct"] = True
    return [EffectSpec("fight", params)]


def _fight_implicit(fighter_kind: Optional[str]):
    """Builder for the three clauses whose fighter isn't chosen: the source
    (``None``), an Aura's host (``"attached_permanent"``), or the previous
    clause's target (``"previous_target"``). Only the *other* creature is a
    RULE 115 requirement, so the whole clause is one target wide."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        other = _fight_kind(m.group("target"))
        if other is None:
            return None
        params: dict = {"other_kind": other, **_optional_param(m)}
        if m.groupdict().get("same_mv"):
            # "…with the same mana value" as the group trigger's firing object (Boxing Ring): a
            # target filter read off the trigger's event, so only under a group trigger.
            if not _GROUP_CLAUSE.get():
                return None
            params["other_exact_mana_value"] = "trigger_subject_mana_value"
        if fighter_kind is not None:
            params["fighter_kind"] = fighter_kind
        if m.groupdict().get("another"):
            # "Another" than a *chosen* previous target is a cross-requirement
            # exclusion; than the source/host it's just the narrower kind.
            if fighter_kind == "previous_target":
                params["distinct"] = True
            else:
                params["other_kind"] = _another_kind(other)
        return [EffectSpec("fight", params)]

    return build


def _fight_previous_pair(m: re.Match[str]) -> list[EffectSpec]:
    """"Then those creatures fight each other." — both fighters come from the
    preceding "choose target … and target …" clause, so this clause announces
    no requirement of its own at all."""
    return [
        EffectSpec(
            "fight",
            {"fighter_kind": "previous_target", "other_kind": "previous_target_2"},
        )
    ]


def _choose_targets(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Choose target creature you control and target creature you don't
    control." (RULE 601.2c) — announces the pair the following clauses act on
    by pronoun; see `effects.ChooseTargetsEffect`."""
    first = _fight_kind(m.group("target"))
    second = _fight_kind(m.group("target_b"))
    if first is None or second is None:
        return None
    return [EffectSpec("choose_targets", {"kinds": [first, second]})]


def _choose_targets_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Choose two target creatures controlled by different players." (PAR-1,
    Run Away Together) — the quantified-*group* sibling of `_choose_targets`
    just above: one requirement picking N objects of the *same* kind (the
    `_multi_target_params` shape `destroy`/`exile`'s own multi-target rows
    already use) rather than two independently-kinded single picks. Still an
    announcement only — see `effects.ChooseTargetsEffect`'s ``count``/
    ``distinct_controllers`` widening and `_return_previous_group`, the
    "Return those creatures…" clause that reads the group back.
    """
    params = _multi_target_params(m)
    if params is None:
        return None
    kind = params.pop("target_kind")
    return [EffectSpec("choose_targets", {"kinds": [kind], **params})]


def _choose_target_single(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """A bare target announcement consumed by a following pronoun clause.

    PAR-130's per-player bodies print this as "choose [up to one] target X
    that player controls"; the per-player wrapper stamps the resulting
    requirement exactly like it does an ordinary destroy/exile effect.
    """
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("choose_targets", {
        "kinds": [kind], "optional": target_is_optional(m),
    })]


# RULE 701.10 "exchange control of `<X>` and `<Y>`" (PAR-29) — three
# distinct printed shapes, each onto `effects.ExchangeControlEffect`'s own
# matching mode: this permanent plus one target (`_exchange_control_self`,
# Avarice Totem/Phyrexian Infiltrator-shaped — the mandatory sibling of the
# already-hand-authored Gilded Drake "up to one"); two independently-typed
# targets named in full (`_exchange_control_two_explicit`, Chromeshell
# Crab's "target creature you control and target creature an opponent
# controls"); and "N target `<same kind>`[ controlled by different
# players]" (`_exchange_control_multi`, Shifting Borders/Modify Memory —
# reusing `_multi_target_params`'s own quantifier/`distinct_controllers`
# grammar rather than a new one, same as `_choose_targets_group` just
# above). "Controlled by different players" only ever reaches
# `_exchange_control_multi`'s `distinct_controllers` as an *offer-time*
# constraint (`targeting.TargetSpec`'s own docstring — it has no
# equivalent for the two-explicit-target shape's independent specs); a
# same-controller pick there still can't actually exchange anything
# (`ExchangeControlEffect.apply`'s own runtime `mine.controller_id !=
# theirs.controller_id` check), so nothing incorrect resolves either way.
_EXCHANGE_CONTROL_TARGET_KINDS = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control",
     "permanent", "permanent_you_control", "permanent_you_dont_control",
     "nonland_permanent", "nonland_permanent_you_control",
     "nonland_permanent_you_dont_control", "artifact", "land",
     "land_you_control", "land_you_dont_control"}
)


def _exchange_control_self(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _EXCHANGE_CONTROL_TARGET_KINDS):
        return None
    return [EffectSpec("exchange_control", {
        "target_kind": kind, **_optional_param(m),
    })]


#: PAR-30 RULE 701.10 residue — the optional trailing cross-target predicate
#: on an "exchange control of X and Y" clause, checked at resolution by
#: `effects.ExchangeControlEffect._cross_target_ok`:
#:   * "…that share[s] {a card type | a permanent type | 1 of those types}
#:     [with it]" (Daring Thief / Legerdemain / Role Reversal / Shifting
#:     Loyalties / Trickster-God's Heist) — all fold to ``shares_type="card"``
#:     (RULE 205.2: two battlefield permanents sharing a permanent type ⇔
#:     sharing a card type);
#:   * "…with equal or lesser mana value" (Puca's Mischief).
_EXCHANGE_XTARGET_TAIL = (
    r"(?:,? (?P<xt_share>that shares? (?:a (?:card|permanent) type|1 of those types)"
    r"(?: with it)?)"
    r"|,? with (?P<xt_mv>equal or lesser mana value))?"
)


def _exchange_xtarget_params(m: re.Match[str]) -> dict:
    gd = m.groupdict()
    params: dict = {}
    if gd.get("xt_share"):
        params["shares_type"] = "card"
    if gd.get("xt_mv"):
        params["second_not_greater"] = "mana_value"
    return params


def _exchange_control_two_explicit(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    first = resolve_target_kind(m.group("target"))
    second = resolve_target_kind(m.group("target_b"))
    if not (target_kind_allowed(first, _EXCHANGE_CONTROL_TARGET_KINDS)
            and target_kind_allowed(second, _EXCHANGE_CONTROL_TARGET_KINDS)):
        return None
    return [EffectSpec("exchange_control", {
        "first_target_kind": first, "target_kind": second,
        **_exchange_xtarget_params(m),
    })]


def _exchange_control_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None:
        return None
    params.update(_exchange_xtarget_params(m))
    return [EffectSpec("exchange_control", params)]


#: Spawnbroker — "target creature you control and target creature **with
#: power less than or equal to that creature's power** an opponent controls".
#: The comparison sits *inside* the second target phrase (before "an opponent
#: controls"), so `_TARGET_B` can't consume it; its own row.
_EXCHANGE_CONTROL_SPAWNBROKER_RE = _c(
    r"exchange control of target creature you control and target creature "
    r"with power less than or equal to that creature'?s power an opponent controls"
)


def _exchange_control_spawnbroker(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exchange_control", {
        "first_target_kind": "creature_you_control",
        "target_kind": "creature_you_dont_control",
        "second_not_greater": "power",
    })]


# RULE 701.10's life-total half — "exchange life totals with target
# opponent/player" (this effect's own controller + one target, Magus of the
# Mirror/Mirror Universe-shaped) and "N target players exchange life
# totals" (two independent targets, Soul Conduit/Axis of Mortality's own
# "have" phrasing — the same causative verb `_THEN`'s neighborhood already
# tolerates for "have it fight").
def _exchange_life_totals_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exchange_life_totals", {"target_kind": "player"})]


def _exchange_life_totals_two_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exchange_life_totals", {})]


#: "you may **have** it fight …" — `_peel_optional` strips the "you may",
#: leaving the causative "have <subject> fight" (uninflected verb), so both
#: inflections are accepted in one row. A leading "then " survives the
#: segmenter's split on ". " (its own "then" connector only strips the
#: comma-less mid-sentence form), so every pronoun row tolerates it.
_THEN = r"(?:then )?"
#: The pronouns a later clause uses for the creature an earlier one chose.
_PREVIOUS_SUBJECT = r"(?:it|that creature|the chosen creature)"
_FIGHT_TWO_TARGETS_RE = _c(rf"{TARGET} fights {_ANOTHER_B}{_TARGET_B}")
_FIGHT_SELF_RE = _c(rf"(?:have )?{re.escape(SELF)} fights? {_ANOTHER}{TARGET}")
# "it" / a personified legendary's "he"/"she"/"they" — all name the source
# creature (RULE 109.5), never a player (MTG writes "they" for players only
# as a *subject of a player action*, never "they fight"). Wolverine, Fierce
# Fighter: "When Wolverine enters, he fights up to one other target creature."
_FIGHT_PRONOUN_RE = _c(rf"(?:have )?(?:it|he|she|they) fights? {_ANOTHER}{TARGET}")
_FIGHT_ATTACHED_RE = _c(rf"(?:have )?{_ATTACHED_SUBJECT} fights? {_ANOTHER}{TARGET}")
_FIGHT_PREVIOUS_RE = _c(
    rf"{_THEN}(?:have )?{_PREVIOUS_SUBJECT} fights? {_ANOTHER}{TARGET}(?P<same_mv> with the same mana value)?"
)

#: Predatory Urge's pre-keyword-action wording for a fight.  The two damage
#: sentences have RULE 701.14a's exact simultaneous semantics, so they must
#: become one atomic `fight`, not two `damage_equal_to_power` effects.
_FIGHT_DAMAGE_EQUIVALENT_RE = _c(
    rf"(?:{re.escape(SELF)}|this creature|it) deals? damage equal to its power to target creature\.\s*"
    rf"that creature deals? damage equal to its power to (?:{re.escape(SELF)}|this creature|it)"
)

#: RULE 701.14 fight, in its four printed subjects: two chosen creatures
#: ("target creature you control fights target creature you don't
#: control"), the source itself written as ``~`` or as "it", and an Aura's
#: host ("enchanted creature fights …"), plus the fifth "pronoun pointing
#: back at an earlier clause" form ("… gets +1/+2 until end of turn. **It**
#: fights target creature you don't control.", offered only when the caller
#: says an earlier clause in this same body actually chose a creature —
#: `EffectHandler.previous_subject_only`). The "it" row is
#: `self_subject_only` — see `EffectHandler`. Grammar/builders differ enough
#: per row (the "have"/"another" wording, which kind-resolver applies) that
#: only the repetitive `EffectHandler(...)` registration itself is factored
#: into this row table, not the regexes/builders behind it.
_FIGHT_ROW_SPECS: list[tuple[str, "re.Pattern[str]", Any, dict]] = [
    (
        "fight_damage_equivalent", _FIGHT_DAMAGE_EQUIVALENT_RE,
        lambda m: [EffectSpec("fight", {"other_kind": "creature"})],
        {},
    ),
    ("fight", _FIGHT_TWO_TARGETS_RE, _fight, {}),
    ("fight_self", _FIGHT_SELF_RE, _fight_implicit(None), {}),
    ("fight_pronoun", _FIGHT_PRONOUN_RE, _fight_implicit(None), {"self_subject_only": True}),
    ("fight_attached", _FIGHT_ATTACHED_RE, _fight_implicit("attached_permanent"), {}),
    (
        "fight_previous", _FIGHT_PREVIOUS_RE, _fight_implicit("previous_target"),
        {"previous_subject_only": True},
    ),
]

_FIGHT_PREVIOUS_PAIR_RE = _c(
    rf"{_THEN}(?:those|the chosen) creatures fight each other"
)
#: "Put a +1/+1 counter on target creature. **It** phases out." (Slip Out
#: the Back) — the same previous-clause pronoun `_FIGHT_PREVIOUS_RE` uses,
#: for `PhaseOutEffect.previous_subject` instead of a fight.
_PHASE_OUT_PREVIOUS_RE = _c(rf"{_THEN}{_PREVIOUS_SUBJECT} phases? out")


def _phase_out_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("phase_out", {"previous_subject": True})]


#: RULE 702.26 "~ phases out." (Blink Dog/Vaporous Djinn/Crystal Golem-
#: shaped — the source phasing out *itself*) — `PhaseOutEffect.self_target`,
#: distinct from the plain untargeted default below (Robe of Stars' own
#: Equipment-hosted "equipped creature phases out", reached by
#: `_phase_out_attached` instead).
_PHASE_OUT_SELF_RE = _c(r"~ phases? out")
#: "Enchanted/equipped creature phases out." (Vanishing) — the untargeted
#: default `PhaseOutEffect` already had (Robe of Stars' own hand-authored
#: shape, `EffectSpec("phase_out", {})`), just reached from oracle text now.
_PHASE_OUT_ATTACHED_RE = _c(rf"{_ATTACHED_SUBJECT} phases? out")
#: "Target creature phases out." / "Target artifact, creature, or land
#: phases out." / "Target creature you control phases out." / "Target
#: creature or planeswalker an opponent controls phases out." (Reality
#: Ripple/Vodalian Illusionist/Haystack/Divine Smite-shaped) — a genuine
#: RULE 115 target, so an opponent's own permanent is exactly as legal a
#: target as your own whenever the printed phrase says so (no engine
#: restriction ever scoped this to "your own permanents" — `PhaseOutEffect`
#: just forwards whatever `target_kind` `resolve_target_kind` resolves).
_PHASE_OUT_TARGET_RE = _c(rf"{TARGET} phases? out")


def _phase_out_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("phase_out", {"self_target": True})]


def _phase_out_attached(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("phase_out", {})]


def _phase_out_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind}
    if target_is_optional(m):
        params["optional"] = True
    return [EffectSpec("phase_out", params)]


#: RULE 500.4-adjacent "after this phase, there is an additional combat
#: phase." (Combat Celebrant/Godo/Aurelia-shaped, `normalize` folds "this
#: combat phase" to the bare "this phase" self-reference every printing of
#: this clause uses) / World at War/Aggravated Assault's own longer
#: "after this main phase, there is an additional combat phase followed by
#: an additional main phase." — `ExtraCombatPhaseEffect`'s `main_phase_too`
#: flag is what tells the two apart. The subject-first word order ("there
#: is an additional combat phase after this phase.", A-Raiyuu, Storm's
#: Edge/Raiyuu-shaped, MEC-28) is the same clause with its two halves
#: swapped — real cache cards print both orderings.
_EXTRA_COMBAT_PHASE_RE = _c(
    r"after this phase, there is an additional combat phase"
    r"|there is an additional combat phase after this phase"
)
_EXTRA_COMBAT_AND_MAIN_PHASE_RE = _c(
    r"after this main phase, there is an additional combat phase followed by an additional main phase"
)


def _extra_combat_phase(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("extra_combat_phase", {})]


def _extra_combat_and_main_phase(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("extra_combat_phase", {"main_phase_too": True})]


_CHOOSE_TARGETS_RE = _c(rf"choose {TARGET} and {_TARGET_B}")
#: "choose two target creatures [controlled by different players]." (PAR-1)
#: — the `_MULTI_TARGET_QUANTIFIER`/`_MULTI_TARGET_ALT`/`_MULTI_TARGET_
#: DISTINCT_CONTROLLERS` grammar `destroy`/`exile`'s own multi-target rows
#: use, repurposed as a bare announcement (see `_choose_targets_group`).
_CHOOSE_TARGETS_GROUP_RE = _c(
    rf"choose {_MULTI_TARGET_QUANTIFIER}(?P<target>{_MULTI_TARGET_ALT})"
    rf"{_MULTI_TARGET_DISTINCT_CONTROLLERS}"
)
_CHOOSE_TARGET_SINGLE_RE = _c(rf"choose {TARGET}")


# --- The one-sided fight ("deals damage equal to its power") ----------------
# Same subject vocabulary as a fight, half the damage: "target creature you
# control deals damage equal to its power to target creature you don't
# control." (Rabid Bite), "when ~ dies, it deals damage equal to its power to
# any target." — `effects.DamageEqualToPowerEffect`.

#: Kinds that can *take* this damage (RULE 115.4-ish) — deliberately narrower
#: than the whole `TARGET` table: "target permanent"/"target artifact" as a
#: damage recipient would be a mis-model, since damage means nothing to a
#: land or an enchantment in this engine.
_DAMAGE_RECIPIENT_KINDS: frozenset[str] = frozenset(
    {
        "any", "creature", "creature_you_control", "creature_you_dont_control", "player",
        # Sinstriker's Will: the combat-qualified creature is still a
        # creature recipient, with its legality supplied by TargetFrame.
        "attacking_or_blocking_creature",
        # PAR-127: "… to target creature or planeswalker [you don't control]"
        # (Bite Down, Domri's Ambush) — damage to a planeswalker removes
        # loyalty (RULE 120.3c) through the same `deal_damage`.
        "creature_or_planeswalker",
    }
)
_DEALS_POWER = r"deals? damage equal to its power to"


def _power_recipient(phrase: str) -> Optional[str]:
    kind = resolve_target_kind(phrase)
    return kind if target_kind_allowed(kind, _DAMAGE_RECIPIENT_KINDS) else None


def _damage_equal_to_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dealer = _fight_kind(m.group("target"))
    recipient = _power_recipient(m.group("target_b"))
    if dealer is None or recipient is None:
        return None
    params: dict = {"dealer_kind": dealer, "target_kind": recipient}
    if target_is_optional(m):
        params["dealer_optional"] = True
    if target_is_optional(m, "_b"):
        params["optional"] = True
    return [EffectSpec("damage_equal_to_power", params)]


def _damage_equal_to_power_implicit(dealer_kind: Optional[str]):
    """The self/host/previous-target dealer forms — one requirement wide."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        recipient = _power_recipient(m.group("target"))
        if recipient is None:
            return None
        params: dict = {"target_kind": recipient, **_optional_param(m)}
        if dealer_kind is not None:
            params["dealer_kind"] = dealer_kind
        return [EffectSpec("damage_equal_to_power", params)]

    return build


def _damage_equal_to_power_selector(dealer_kind: Optional[str]):
    """"… to each opponent." — an untargeted recipient group (RULE 601.2c),
    the same closed vocabulary `_damage_selector` uses."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        selector = _SELECTOR_WORD_MAP.get(m.group("selector").lower())
        if selector is None:
            return None
        params: dict = {"selector": selector, "target_kind": None}
        if dealer_kind is not None:
            params["dealer_kind"] = dealer_kind
        return [EffectSpec("damage_equal_to_power", params)]

    return build


# "<creature> deals damage to itself equal to its power." — the dealer *is*
# the recipient (Justice Strike / Inner Struggle / Wrack with Madness on a
# target, Wave of Reckoning / Solar Blaze as an "each creature" mass form).
# `damage_equal_to_power` with `to_self`; the "each" form is `each_creature`
# selector + no dealer target, each creature reading its own power.
_SELF_DAMAGE_POWER = r"deals? damage to itself equal to its power"
_POWER_DAMAGE_TO_SELF_TARGET_RE = _c(rf"{TARGET} {_SELF_DAMAGE_POWER}")
_POWER_DAMAGE_TO_SELF_EACH_RE = _c(rf"each creature {_SELF_DAMAGE_POWER}")


def _damage_to_self_equal_to_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dealer = _fight_kind(m.group("target"))
    if dealer is None:
        return None
    return [EffectSpec("damage_equal_to_power", {
        "dealer_kind": dealer, "target_kind": None, "to_self": True,
        **_optional_param(m),
    })]


def _damage_to_self_equal_to_power_each(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage_equal_to_power", {
        "selector": "each_creature", "target_kind": None, "to_self": True,
    })]


#: The subset of `_SELECTOR_WORD_MAP` a *damage* clause can legally match —
#: "each other player" is a lose_life/rad-counter-only phrasing (no card
#: prints "deals damage to each other player"), so these selector rows must
#: not inherit it just because the lookup dict is shared with lose_life's.
_DAMAGE_SELECTOR_KEYS = ("each creature", "each player", "each opponent", "that player")
_DAMAGE_SELECTOR_ALT = "|".join(_DAMAGE_SELECTOR_KEYS)
_POWER_DAMAGE_TWO_TARGETS_RE = _c(rf"{TARGET} {_DEALS_POWER} {_TARGET_B}")
_POWER_DAMAGE_SELF_RE = _c(rf"{re.escape(SELF)} {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_PRONOUN_RE = _c(rf"it {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_ATTACHED_RE = _c(rf"{_ATTACHED_SUBJECT} {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_PREVIOUS_RE = _c(rf"{_THEN}{_PREVIOUS_SUBJECT} {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_SELF_SELECTOR_RE = _c(
    rf"{re.escape(SELF)} {_DEALS_POWER} (?P<selector>{_DAMAGE_SELECTOR_ALT})"
)
_POWER_DAMAGE_PRONOUN_SELECTOR_RE = _c(
    rf"it {_DEALS_POWER} (?P<selector>{_DAMAGE_SELECTOR_ALT})"
)
#: PAR-30: "<subject> deals damage equal to its power to each opponent." as
#: a *triggered-ability body* where the damage source and its amount are the
#: same object — the trigger's own subject (Champion of the Path's
#: just-entered Elemental / Pyrotechnic Performer's turned-face-up creature
#: → `group_subject_only`) or "~" itself (Giggling Skitterspike / Gau, Feral
#: Youth → `self_subject_only`). Routed to the dedicated
#: `subject_damages_each_opponent_equal_to_power` effect, which resolves the
#: subject from `GameContext.trigger_event` at resolution — the plain
#: `damage_equal_to_power` selector rows source from ``self.source``, which
#: is wrong when "it" is a *different* creature every firing.
_SUBJECT_POWER_DAMAGE_EACH_OPPONENT_RE = _c(
    r"(?:it|that creature) deals? damage equal to its power to each opponent"
)


def _subject_damages_each_opponent_equal_to_power(
    m: "re.Match[str]",
) -> list[EffectSpec]:
    return [EffectSpec("subject_damages_each_opponent_equal_to_power", {})]

#: The one-sided fight's own registration table (see `_FIGHT_ROW_SPECS`'s
#: matching note) — two rows wider than fight's, since a creature can deal
#: damage to a mass selector ("… to each opponent") but can't "fight" one,
#: so `damage_equal_to_power` alone gets the `_self_selector`/
#: `_pronoun_selector` rows.
_POWER_DAMAGE_ROW_SPECS: list[tuple[str, "re.Pattern[str]", Any, dict]] = [
    ("damage_equal_to_power", _POWER_DAMAGE_TWO_TARGETS_RE, _damage_equal_to_power, {}),
    # "it/that creature deals damage equal to its power to each opponent."
    # — before the generic pronoun/self selector rows so the dedicated
    # trigger-subject effect wins for the "each opponent" recipient (PAR-30).
    (
        "subject_damage_each_opponent_power_group",
        _SUBJECT_POWER_DAMAGE_EACH_OPPONENT_RE,
        _subject_damages_each_opponent_equal_to_power, {"group_subject_only": True},
    ),
    (
        "subject_damage_each_opponent_power_self",
        _SUBJECT_POWER_DAMAGE_EACH_OPPONENT_RE,
        _subject_damages_each_opponent_equal_to_power, {"self_subject_only": True},
    ),
    (
        "damage_equal_to_power_self", _POWER_DAMAGE_SELF_RE,
        _damage_equal_to_power_implicit(None), {},
    ),
    (
        "damage_equal_to_power_self_selector", _POWER_DAMAGE_SELF_SELECTOR_RE,
        _damage_equal_to_power_selector(None), {},
    ),
    (
        "damage_equal_to_power_pronoun", _POWER_DAMAGE_PRONOUN_RE,
        _damage_equal_to_power_implicit(None), {"self_subject_only": True},
    ),
    (
        "damage_equal_to_power_pronoun_selector", _POWER_DAMAGE_PRONOUN_SELECTOR_RE,
        _damage_equal_to_power_selector(None), {"self_subject_only": True},
    ),
    # PAR-123: under a RULE 603.1 group trigger "it" is the firing creature, not the
    # source (Stalking Vengeance, Warstorm Surge) — the same `trigger_subject`
    # dealer `fight` already reads (MEC-99).
    (
        "damage_equal_to_power_group_pronoun", _POWER_DAMAGE_PRONOUN_RE,
        _damage_equal_to_power_implicit("trigger_subject"), {"group_subject_only": True},
    ),
    (
        "damage_equal_to_power_group_pronoun_selector", _POWER_DAMAGE_PRONOUN_SELECTOR_RE,
        _damage_equal_to_power_selector("trigger_subject"), {"group_subject_only": True},
    ),
    (
        "damage_equal_to_power_attached", _POWER_DAMAGE_ATTACHED_RE,
        _damage_equal_to_power_implicit("attached_permanent"), {},
    ),
    (
        "damage_equal_to_power_previous", _POWER_DAMAGE_PREVIOUS_RE,
        _damage_equal_to_power_implicit("previous_target"), {"previous_subject_only": True},
    ),
    # "… deals damage to itself equal to its power." — dealer == recipient.
    (
        "damage_to_self_equal_to_power", _POWER_DAMAGE_TO_SELF_TARGET_RE,
        _damage_to_self_equal_to_power, {},
    ),
    (
        "damage_to_self_equal_to_power_each", _POWER_DAMAGE_TO_SELF_EACH_RE,
        _damage_to_self_equal_to_power_each, {},
    ),
]


#: A single mana symbol run — "add {b}{b}{b}." (Dark Ritual-shaped). Only a
#: *pure* run of colour/colourless symbols claims (fail-closed): "add 1 mana
#: of any color" has no ``{…}`` symbols to capture, so it's left unclaimed
#: rather than guessed at (that's a player choice, not modeled yet).
_MANA_SYMBOL = r"\{[wubrgc]\}"
#: "add an additional {g}" (a triggered mana ability's bonus mana — Badgermole Cub, Leyline of Abundance) adds exactly
#: what "add {g}" does; "additional" only says it comes on top of what the tap produced.
_ADD_MANA_RE = _c(rf"add (?:an additional )?(?P<syms>(?:{_MANA_SYMBOL}){{1,20}})")
#: "add 1 mana of any color" (number words already folded to digits by
#: `normalize`) — a genuine resolve-time player choice (RULE 106.4), unlike
#: the fixed pip run above. Deliberately narrow: real cards only print this
#: singular form (a multi-mana "any color" clause is always templated "any
#: *one* color" instead, a different, not-yet-modeled shape — guessing it
#: means the same thing here would be wrong).
_ADD_MANA_ANY_COLOR_RE = _c(r"add (?:an additional )?1 mana of any colou?r")


def _add_mana(m: re.Match[str]) -> list[EffectSpec]:
    colors = [s.upper() for s in re.findall(r"\{([wubrgc])\}", m.group("syms"))]
    return [EffectSpec("add_mana", {"colors": colors})]


#: "add 6 {R}." (Avatar Roku, Firebender), "add 8 {C}." (Su-Chi Cave Guard) — a count in front of one symbol — and
#: "add 2 mana of any 1 color." (Branch of Vitu-Ghazi: one colour pick, that many mana). The count form is
#: `AddManaEffect`'s variable-count ``amount``/``color``; the any-colour form its ``any_amount``.
_ADD_MANA_COUNTED_RE = _c(
    r"add (?:(?P<n>\d+) (?P<sym>" + _MANA_SYMBOL + r")|(?P<k>\d+) mana of any (?:1|one) colou?r)"
)


#: "add that much {G}." (Sakiko, Mother of Summer; Raphael, Ninja Destroyer) — the firing damage event's own amount,
#: `AddManaEffect.amount_from_trigger_event`.
_ADD_MANA_THAT_MUCH_RE = _c(r"add that much (?P<sym>" + _MANA_SYMBOL + r")")


def _add_mana_that_much(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_mana", {
        "color": m.group("sym").strip("{}").upper(), "amount_from_trigger_event": "amount",
    })]


#: "add X mana in any combination of colors" / "add that much mana in any combination of {R} and/or {G}" (Grand Warlord
#: Radha, Klauth) and "add that much mana of any 1 color" (Photon), and the two-colour choice "add {R} or {G}" (Kessig
#: Naturalist): `AddManaEffect`'s ``"ANY"`` offer, narrowed to the named colours. A fixed count is that many single picks;
#: **documented simplification** for a variable amount (as for Culling Ritual): one colour pick covers the whole amount
#: instead of splitting it mana by mana.
_ADD_MANA_ANY_COMBINATION_RE = _c(
    r"add (?:(?P<amount>x|that much|\d+) mana (?:in any combination of (?P<cols>colou?rs|"
    r"\{[wubrg]\}(?:(?:, | and/or |, and/or )\{[wubrg]\})*)|of any (?:1|one) colou?r)"
    r"|(?P<first>\{[wubrg]\}) or (?P<second>\{[wubrg]\}))"
)


def _add_mana_any_combination(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("first"):
        return [EffectSpec("add_mana", {
            "colors": ["ANY"], "any_color_choices": [m.group("first").strip("{}").upper(), m.group("second").strip("{}").upper()],
        })]
    params: dict = {"colors": ["ANY"]}
    cols = m.group("cols")
    if cols and cols not in ("color", "colors", "colour", "colours"):
        params["any_color_choices"] = [c.upper() for c in re.findall(r"\{([wubrg])\}", cols)]
    amount = m.group("amount")
    if amount == "that much":
        params["any_amount_from_trigger_event"] = "amount"
    elif amount == "x":
        params["any_amount"] = "x"
    elif amount.isdigit() and int(amount) > 1:
        # A fixed "N mana in any combination" is exactly N independent single picks (RULE 106.1) — no simplification.
        return [EffectSpec("add_mana", dict(params)) for _ in range(int(amount))]
    return [EffectSpec("add_mana", params)]


def _add_mana_counted(m: re.Match[str]) -> list[EffectSpec]:
    if m.group("k"):
        return [EffectSpec("add_mana", {"colors": ["any"], "any_amount": int(m.group("k"))})]
    return [EffectSpec("add_mana", {"color": m.group("sym").strip("{}").upper(), "amount": int(m.group("n"))})]


def _add_mana_any_color(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_mana", {"colors": ["any"]})]


#: PAR-124: "…, that player adds an additional {b}." (Bubbling Muck/High
#: Tide's own "whenever a player taps a `<land>` for mana" body) — "that
#: player" is RULE 605.1's tapper, not this ability's own controller,
#: reading `GameContext.trigger_event["controller_id"]` via `AddManaEffect.
#: recipient="event_controller"` (already built for Wild Growth's
#: identical "its controller adds…" shape).
_ADD_MANA_ADDITIONAL_EVENT_PLAYER_RE = _c(
    rf"that player adds an additional (?P<syms>(?:{_MANA_SYMBOL}){{1,20}})"
)
#: "…its controller adds an additional `<mana>`" under "whenever enchanted land is tapped for mana" (Wild Growth,
#: Overgrowth, Dawn's Reflection, Market Festival) — the land's controller, who need not be the Aura's. The mana is
#: a symbol run, "1 mana of any color", or "2 mana in any combination of colors" — which is exactly two single
#: any-colour mana, each picked on its own (RULE 106.1), so no combination chooser is needed.
_ADD_MANA_ADDITIONAL_ITS_CONTROLLER_RE = _c(
    r"its controller adds an additional (?:(?P<syms>(?:" + _MANA_SYMBOL + r"){1,20})|(?P<any>1 mana of any colou?r)"
    r"|(?P<combo>2 mana in any combination of colou?rs))"
)


def _add_mana_additional_event_player(m: re.Match[str]) -> list[EffectSpec]:
    groups = m.groupdict()
    if groups.get("any") or groups.get("combo"):
        return [
            EffectSpec("add_mana", {"colors": ["any"], "recipient": "event_controller"})
            for _ in range(2 if groups.get("combo") else 1)
        ]
    colors = [s.upper() for s in re.findall(r"\{([wubrgc])\}", m.group("syms"))]
    return [EffectSpec("add_mana", {"colors": colors, "recipient": "event_controller"})]


#: "Add `<sym>` / 1 mana of any color for each `<kind>` counter removed this
#: way." (Coalition Relic/Ventifact Bottle, PAR-66) — `GameContext.
#: counters_removed_this_way`'s own accumulator (bumped by a preceding
#: `remove_counters` clause in the same resolution), read through
#: `AddManaEffect.amount_from_context`/``any_amount_from_context`` exactly
#: like `permanents_destroyed_this_way` already feeds Culling Ritual's
#: hand-authored entry — this is the oracle-text route to the same
#: primitive. The counter *kind* word itself isn't re-checked here (a
#: single `remove_counters` clause only ever strips one named kind per
#: card today), so any kind word claims.
_ADD_MANA_PER_COUNTER_REMOVED_RE = _c(
    r"add (?:(?P<any>1 mana of any colou?r)|(?P<sym>\{[wubrgc]\}))"
    r" for each [a-z]+ counters? removed this way"
)


def _add_mana_per_counter_removed(m: re.Match[str]) -> list[EffectSpec]:
    if m.group("any"):
        return [EffectSpec("add_mana", {
            "colors": ["any"], "any_amount_from_context": "counters_removed_this_way",
        })]
    color = m.group("sym").strip("{}").upper()
    return [EffectSpec("add_mana", {
        "color": color, "amount_from_context": "counters_removed_this_way",
    })]


#: "you may pay {E}{E}. If/When you do, <effect>." (RULE 122, Aether Chaser/
#: Herder/Inspector/Swooper) — a resolve-time optional energy payment gating
#: a follow-up. The follow-up is recursively parsed; a follow-up the parser
#: can't model (e.g. a *targeted* one — Guide of Souls) leaves the whole
#: clause unclaimed (fail-closed).
_PAY_ENERGY_THEN_RE = _c(
    r"you may pay (?P<pips>(?:\{e\})+)\.\s*(?:if|when) you do,?\s*(?P<effect>.+)"
)


def _pay_energy_then(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    amount = m.group("pips").count("{e}")
    sub = parse_effect_body(m.group("effect").strip())
    if not sub:
        return None  # follow-up not modeled → whole clause unclaimed
    if any(s.params.get("target_kind") for s in sub):
        # A *targeted* follow-up (Guide of Souls' "put counters on target
        # attacking creature") isn't resolvable through `PayEnergyThen
        # Effect`'s no-target resolution — fail-closed rather than model it
        # half-way (the resolve handler runs each sub-effect untargeted).
        return None
    return [EffectSpec("pay_energy_then", {"amount": amount, "effects": [s.to_dict() for s in sub]})]


#: MEC-18/RULE 603.5's general "You may `<cost-shaped action>`. When/If you
#: do, `<effect>`." — generalizes `_pay_cost_then_draw`/`_pay_energy_then`
#: from one hardcoded antecedent (a bare mana cost / `{E}` pips) and, for
#: the first, one hardcoded consequence (draw a card) to the *whole*
#: `ActivationCost` vocabulary `pay_cost_then`/`RulesEngine.
#: _request_pay_cost_then` already supports server-side (mana, sacrifice,
#: discard, life — see that method's own docstring) plus an arbitrary
#: recursively-parsed follow-up. No new engine primitive: `pay_cost_then`
#: was already general, just never had an oracle-text recognizer past the
#: two narrow shapes above.
#:
#: `<cost>` is matched against a **closed** whitelist of atomic clause
#: shapes rather than run through `costs.py`'s lenient substring search —
#: that search only *finds* a cost fragment inside arbitrary text, it
#: doesn't confirm the fragment is the *entire* clause, so a compound
#: antecedent ("discard your hand and draw two cards") could otherwise have
#: its un-matched tail silently dropped. The mana alternative excludes the
#: `{E}` symbol on purpose — `_can_pay_player_cost`/`_pay_player_cost` don't
#: charge `ActivationCost.pay_energy` at all (that's `pay_energy_then`'s own
#: job, tried above and first-match-wins), so letting it through here would
#: silently make an energy antecedent free. A targeted "If you do" payoff
#: announces targets with the enclosing spell/ability (RULE 601.2c);
#: "When you do" instead creates a reflexive trigger (RULE 603.12).
#:
#: Exported (not module-private in spirit, just in naming convention) so
#: `segmenter._PAY_ENERGY_THEN_PEEL_GUARD_RE` can protect the exact same
#: shapes from its own generic "you may " stripping — that peel is a
#: *different*, outer RULE 601.2c optionality (the whole ability, not this
#: sub-clause's cost), and the two must never drift apart or a clause this
#: handler recognizes would get its "you may" eaten before reaching here.
#:
#: The sacrifice alternative deliberately excludes the bare **self**-
#: sacrifice forms ("sacrifice it"/"this `<type>`"/"~") that `segmenter.
#: _SACRIFICE_THEN_WHEN_YOU_DO_RE` already claims (a plain, unconditional
#: sequence — sacrificing yourself is always legal once declared, so RULE
#: 603.5's antecedent can never fail, and that older path is strictly more
#: permissive than this one since it allows a *targeted* follow-up).
#: Routing self-sacrifice through here too would only lose coverage: this
#: handler's `_can_pay_player_cost` gate can genuinely fail an antecedent
#: (no legal permanent of the named type/no cards in hand), which is real
#: and worth being interactive about for a *typed* sacrifice/discard/life
#: payment. Self-sacrifice is handled by that separate antecedent path.
_MAY_COST_THEN_CLAUSE = (
    r"pay (?:\{[wubrgcx0-9/]+\})+"
    r"|sacrifice an? \w+"
    r"|sacrifice another \w+"
    r"|discard (?:your hand|a card|\d+ cards?|[a-z]+ cards?)"
    r"|pay \d+ life"
    # RULE 701.59a — a non-mana graveyard cost sized by total mana value;
    # `costs.parse_activation_cost` recognises it and `_can/_pay_player_cost`
    # charge it (`RulesEngine.collect_evidence`, PAR-29).
    r"|collect evidence \d+"
    # RULE 701.61a — "exile three graveyard cards or sacrifice a Food"
    # (`ActivationCost.forage`; `RulesEngine.forage`, PAR-29).
    r"|forage"
    # RULE 701.68 — "put N -1/-1 counters on a creature you control"
    # (`ActivationCost.blight`; `RulesEngine.blight(interactive=False)`, PAR-29).
    r"|blight \d+"
    # PAR-140 — "you may remove a menace counter from ~/it. When you do, …" (Biting-Palm Ninja,
    # Kappa Tech-Wrecker, Slumbering Walker's kindless form): charged off the ability's own source
    # (`RulesEngine._source_counter_removal`). "it" is only the source under a self trigger —
    # `_pay_cost_then_general` refuses it under a group trigger.
    r"|remove (?:a|an|\d+) (?:[+\-]\d/[+\-]\d |[a-z]+(?: strike)? )?counters? from (?:~|it|this [a-z]+)"
)
_PAY_COST_THEN_GENERAL_RE = _c(
    r"you may (?P<cost>" + _MAY_COST_THEN_CLAUSE + r")\.\s*(?P<link>if|when) you do,?\s*(?P<effect>.+)"
)
#: RULE 603.5's *negative* antecedent: "you may `<cost>`. If you don't,
#: `<effect>`." (Chaos Spewer, Gutsplitter Gang, Scuzzback Scrounger — the
#: PAR-29 Blight batch's "if you don't" shape). The mirror of
#: `_PAY_COST_THEN_GENERAL_RE`: the effect goes in `pay_cost_then`'s
#: ``else_effects`` branch (`game/effects/core.py`'s `PayCostThenEffect`), which
#: fires only when the optional cost is *declined* or unpayable.
_PAY_COST_THEN_OR_ELSE_RE = _c(
    r"you may (?P<cost>" + _MAY_COST_THEN_CLAUSE + r")\.\s*if you don't,?\s*(?P<effect>.+)"
)


#: Spellings of "read this from the trigger's event", which is gone once a payment has been made.
_LIVE_EVENT_MARKERS = (
    '"trigger_subject": true', '"target_kind": "trigger_subject"', '"dealer_event_key"',
    '"trigger_event_key"', '"referent": "trigger_event"', '"amount_from_trigger_event"',
    '"count_from_trigger_event"',
)


def _remembered_group_referent(specs: "list[EffectSpec]") -> Optional[list[EffectSpec]]:
    """PAR-123: a payment's "if you do" body runs after the trigger's event window has closed, so a
    group-trigger pronoun inside it must read the subject `PayCostThenEffect` remembers rather than
    the event. Rewrites the firing-object sentinel to ``remembered``; ``None`` if anything else still
    needs the live event (it would resolve to nothing)."""
    def rewrite(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: rewrite(v) for k, v in node.items()}
            params = out.get("params") or {}
            if out.get("type") == "trigger_subject_referent" and params.get("event_key") == GROUP_SUBJECT_KEY_SENTINEL:
                out["params"] = {**params, "event_key": "remembered"}
            elif out.get("type") == "copy_permanent" and params.get("referent") == "trigger_event":
                # "create a token that's a copy of it": the copy reads the remembered object as the
                # referent instead of the event that is no longer live.
                return {"type": "trigger_subject_referent", "params": {
                    "event_key": "remembered",
                    "effects": [{**out, "params": {**params, "referent": "previous"}}],
                }}
            elif out.get("type") == "grant_keyword_to_trigger_subject" and params.get("event_key") == GROUP_SUBJECT_KEY_SENTINEL:
                # "…it gains haste until end of turn" after a payment (Olivia): the remembered
                # object, granted through the ordinary previous-pick pump.
                return {"type": "trigger_subject_referent", "params": {
                    "event_key": "remembered",
                    "effects": [{"type": "pump", "params": {
                        "keywords": [params.get("keyword", "haste")], "previous_subject": True,
                    }}],
                }}
            if out.get("trigger_subject_key") == GROUP_SUBJECT_KEY_SENTINEL:
                out["trigger_subject_key"] = "remembered"
            return out
        if isinstance(node, list):
            return [rewrite(v) for v in node]
        return node

    rewritten = [rewrite(spec.to_dict()) for spec in specs]
    text = json.dumps(rewritten, default=str)
    if GROUP_SUBJECT_KEY_SENTINEL in text or any(marker in text for marker in _LIVE_EVENT_MARKERS):
        return None
    return [EffectSpec(d["type"], d.get("params") or {}, condition=d.get("condition")) for d in rewritten]


def _pay_cost_then_general(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from ..segmenter import parse_effect_body, _announces_creature_target

    group = _GROUP_CLAUSE.get()
    if group and re.match(r"remove .* from it$", m.group("cost")):
        return None  # under a group trigger "it" is the firing object, not the source that pays
    parts = re.split(r"\.\s*otherwise,?\s+", m.group("effect").strip(), maxsplit=1)
    if group:
        # The branch runs once the payment is made, after the trigger's event window has closed, so
        # a pronoun in it names the object `remember_trigger_subject` stamped on the source: read as
        # the previous pick, behind a seed of that remembered object.
        sub = parse_effect_body(parts[0], previous_subject=True)
        if sub:
            sub = [EffectSpec("trigger_subject_referent", {"event_key": "remembered"}), *sub]
        else:
            grouped = parse_effect_body(parts[0], group_subject=True)
            sub = _remembered_group_referent(grouped) if grouped else None
    else:
        sub = parse_effect_body(parts[0], self_subject=True)
    if not sub:
        return None  # follow-up not modeled → whole clause unclaimed
    if m.group("link") == "when" and any(s.params.get("target_kind") for s in sub):
        # RULE 603.12: only "When you do" creates a reflexive trigger.
        # "If you do" uses the enclosing spell/ability's announced targets.
        if len(parts) > 1:
            return None  # an otherwise rider on a reflexive trigger is ambiguous
        return [EffectSpec("pay_cost_then", {
            "cost": m.group("cost"),
            "then_trigger": [s.to_dict() for s in sub],
            **({"remember_trigger_subject": True} if group else {}),
        })]
    params: dict = {"cost": m.group("cost"), "effects": [s.to_dict() for s in sub]}
    if len(parts) > 1:
        otherwise = parse_effect_body(
            parts[1], self_subject=True, previous_subject=_announces_creature_target(sub),
        )
        if not otherwise or any(s.params.get("target_kind") for s in otherwise):
            return None
        params["else_effects"] = [s.to_dict() for s in otherwise]
    if group or any(s.params.get("trigger_subject_key") == "remembered" for s in sub):
        params["remember_trigger_subject"] = True
    return [EffectSpec("pay_cost_then", params)]


#: MEC-103 (RULE 701.21, 603.12): "[you may] sacrifice any number of / up to N
#: `<type>`. When you sacrifice one or more `<type>` this way, `<payoff>`" — the
#: payoff reads "that many", the count actually sacrificed (Ravenous Rotbelly,
#: Nyssa of Traken). Kept apart from `pay_cost_then_general`, whose cost is a
#: fixed "sacrifice a `<type>`": here the *number* is the player's choice.
#: `<what>` is one bare (plural) type/subtype word, singularized below.
_SACRIFICE_CHOSEN_THEN_RE = _c(
    r"(?:you may )?sacrifice (?:any number of|up to (?P<n>\d+)) (?P<what>[a-z]+?)s?\.\s*"
    r"when you sacrifice (?:1|one) or more [a-z]+ this way,?\s*(?P<effect>[^.]+\.?)"
)
#: "that many" bound to a placeholder count the parsed body is rewritten from.
_THAT_MANY_PLACEHOLDER = 2
_THAT_MANY_COUNT_KEYS = ("count", "count_max", "amount")


def _bind_that_many(value: Any) -> Any:
    """Turn the placeholder count back into the ``"x"`` sentinel (bound to the
    sacrificed count at resolve time, `RulesEngine._apply_choose_objects_tail`)."""
    if isinstance(value, dict):
        return {
            k: ("x" if k in _THAT_MANY_COUNT_KEYS and v == _THAT_MANY_PLACEHOLDER else _bind_that_many(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_bind_that_many(v) for v in value]
    return value


def _sacrifice_chosen_then(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    effect = m.group("effect").strip()
    if "that many" not in effect or re.search(r"\d", effect):
        return None  # only the "that many" payoff; any other number would be rewritten wrongly
    sub = parse_effect_body(
        effect.replace("that many", str(_THAT_MANY_PLACEHOLDER)), self_subject=True,
    )
    if not sub:
        return None
    params: dict = {
        "what": m.group("what"),
        "count": int(m.group("n")) if m.group("n") else "any",
        "trigger": [_bind_that_many(s.to_dict()) for s in sub],
    }
    return [EffectSpec("sacrifice_chosen_then", params)]


#: MEC-104: "draw cards equal to the number of opponents dealt damage this way. If you do,
#: discard that many cards." (Hordewing Skaab) — the count is the trigger's own
#: ``matching_opponents`` (`binding.core`'s contributor capture); the "you may" is the ability's.
_DRAW_OPPONENTS_DAMAGED_DISCARD_RE = _c(
    r"draw cards equal to the number of opponents dealt damage this way\.\s*"
    r"if you do,? discard that many cards\.?"
)


def _draw_opponents_damaged_discard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    field = "matching_opponents"
    return [
        EffectSpec("draw", {"count_from_trigger_event": field}),
        EffectSpec("discard", {"count_from_trigger_event": field}),
    ]


def _pay_cost_then_or_else(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"you may `<cost>`. If you don't, `<effect>`." — the else-branch
    sibling of `_pay_cost_then_general` (PAR-29 Blight batch)."""
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    sub = parse_effect_body(m.group("effect").strip(), self_subject=True)
    if not sub:
        return None
    if any(s.params.get("target_kind") for s in sub):
        return None  # a targeted else-branch can't resolve off-stack either
    return [EffectSpec("pay_cost_then", {
        "cost": m.group("cost"),
        "effects": [],
        "else_effects": [s.to_dict() for s in sub],
    })]


#: PAR-79 seventh increment: "return another/`<N>` other `<type>`[s] you
#: control to its/their owner's/owners' hand" (Biblioplex Kraken) and "tap
#: another/`<N>` other untapped `<type>`[s] you control" (Gravelgill
#: Scoundrel/Tidal Terror) as ordinary resolve-time effect bodies — RULE
#: 608.2c's "the resolving effect itself makes this choice", not a RULE 115
#: target (neither clause has the word "target", so there's no announced
#: target to fizzle if the chosen creature becomes illegal between trigger
#: and resolution, unlike modeling this as a `target_kind` pick would risk).
#: No new engine primitive: `ChooseObjectsEffect`/`"choose_objects"`
#: (`RulesEngine._request_choose_objects`, ``action="tap"``/
#: ``"return_to_hand"``) already is this project's general "which one of my
#: own permanents" chooser (Tevesh Szat's "sacrifice another creature or
#: planeswalker", Cloudstone Curio's bounce) — ``exclude_self`` already
#: existed for the "another"/"other" exclusion, and only
#: ``require_untapped`` (this increment) was missing, for the "untapped"
#: qualifier "tap another untapped creature" needs. Once these parse as an
#: ordinary (non-targeted) effect body, `_may_effect_then` right below
#: (the sixth increment's "You may `<effect>`. If you do, `<effect2>`."
#: wrapper) picks them up with no changes of its own — it already rejects
#: only a *targeted* antecedent, and neither of these is one.
_RETURN_ANOTHER_YOU_CONTROL_RE = _c(
    r"return (?:another|(?P<n>\d+) other) (?P<type>[a-z]+?)s? you control "
    r"to (?:its owner's|their owners') hand"
)


def _return_another_you_control(m: re.Match[str]) -> list[EffectSpec]:
    count = int(m.group("n")) if m.group("n") else 1
    return [EffectSpec("choose_objects", {
        "action": "return_to_hand", "what": m.group("type"),
        "count": count, "exclude_self": True,
    })]


_TAP_ANOTHER_UNTAPPED_YOU_CONTROL_RE = _c(
    r"tap (?:another|(?P<n>\d+) other) untapped (?P<type>[a-z]+?)s? you control"
)


def _tap_another_untapped_you_control(m: re.Match[str]) -> list[EffectSpec]:
    count = int(m.group("n")) if m.group("n") else 1
    return [EffectSpec("choose_objects", {
        "action": "tap", "what": m.group("type"),
        "count": count, "exclude_self": True, "require_untapped": True,
    })]


#: Exported so `segmenter._PAY_ENERGY_THEN_PEEL_GUARD_RE` can protect these
#: antecedent shapes from `_peel_optional` the same way it already
#: protects `_MAY_COST_THEN_CLAUSE` (same "so this guard can never drift
#: out of sync" reasoning that constant's own docstring gives). A plain
#: (non-capturing) mirror of `_RETURN_ANOTHER_YOU_CONTROL_RE`/
#: `_TAP_ANOTHER_UNTAPPED_YOU_CONTROL_RE` rather than their own
#: ``.pattern`` — both use the same group names (``n``/``type``), and the
#: guard embeds this alongside `_MAY_COST_THEN_CLAUSE` in one compiled
#: regex, where a repeated group name is a `re.error`, not just a style
#: nit.
_MAY_EFFECT_THEN_ANTECEDENT_PHRASES = (
    r"return (?:another|\d+ other) [a-z]+?s? you control to (?:its owner's|their owners') hand"
    r"|tap (?:another|\d+ other) untapped [a-z]+?s? you control"
    # PAR-124 (Magitek Scythe): "you may attach it to target creature you
    # control. if you do, `<effect>`." — see `_MAY_ATTACH_IF_YOU_DO_RE`'s
    # own docstring for why this one *keeps* its RULE 115 target (unlike
    # every other antecedent above, which are all targetless) instead of
    # going through `_may_effect_then`'s target-rejecting composition.
    r"|attach it to target creature you control"
    # MEC-99 (Gaze of Pain): "you may choose to have it deal damage equal to
    # its power to a target creature. if you do, `<effect>`." — a plain
    # (non-capturing) mirror of `_MAY_HAVE_IT_DEAL_DAMAGE_EQUAL_TO_POWER_RE`'s
    # own target phrase, for the same reason the Magitek Scythe row above
    # keeps its RULE 115 target un-peeled instead of going through `_may_
    # effect_then`'s target-rejecting composition.
    r"|choose to have it deal damage equal to its power to (?:a |up to (?:one|1) )?target [a-z]+"
)


#: PAR-79 sixth increment: "You may `<effect>`. If you do, `<effect2>`."
#: (Biblioplex Kraken/Gravelgill Scoundrel/Tidal Terror/Saprazzan Breaker-
#: shaped) — `_PAY_COST_THEN_GENERAL_RE`'s antecedent is cost-shaped only
#: (`_MAY_COST_THEN_CLAUSE`'s closed vocabulary); these cards' antecedent is
#: itself an ordinary *resolving effect* ("return another creature you
#: control to its owner's hand", "tap another untapped creature you
#: control", "mill a card"), not a cost payment at all — a genuinely
#: different shape, not a wider cost vocabulary. No new engine primitive,
#: though: `OptionalEffect`'s own docstring already spells out exactly this
#: composition — "'You may sacrifice a creature. If you do, draw two
#: cards.' is this node around a seq, not a new fused type" — RULE 603.5's
#: "if you do" is automatically satisfied by sequencing both effects inside
#: one `optional` wrapper, since the whole body (including the "if you do"
#: half) simply never runs at all when the player declines. Tried *after*
#: `pay_cost_then_general`/`pay_cost_then_or_else` (first-match-wins) so a
#: genuinely cost-shaped antecedent still gets the more faithful
#: interactive-affordability handling those give it, not this cruder wrap.
_MAY_EFFECT_THEN_RE = _c(
    r"you may (?P<effect1>.+?)\.\s*if you do,\s*(?P<effect2>.+)"
)


#: PAR-124: "you may attach it to target creature you control. if you do,
#: `<effect>`." (Magitek Scythe's own ETB) — unlike every `_may_effect_
#: then` antecedent, this one keeps a real RULE 115 target: `AttachEffect`'s
#: `target_kind="creature_you_control"` is announced normally when this
#: triggered ability goes on the stack (RULE 601.2c), same as any other
#: printed target — `_may_effect_then`'s own "no way to announce a target
#: mid-resolution" reasoning doesn't apply here at all, since nothing is
#: announced mid-resolution; only *whether* the optional body runs is
#: decided at resolution (RULE 601.2b), which `OptionalEffect.target_specs`
#: is explicitly built to support (its own docstring's Choking Tethers
#: precedent — "you may tap target creature"). The follow-up's own "that
#: creature" is the ordinary `previous_subject` referent onto the same
#: chosen target (`_apply_effects_partitioned`'s shared "who did the
#: previous clause act on" tracking, threaded through `OptionalEffect`'s own
#: `_run`), exactly as if "attach" were any other targeted antecedent
#: clause in an ordinary (non-optional) body.
_MAY_ATTACH_IF_YOU_DO_RE = _c(
    r"you may attach it to target creature you control\.\s*if you do,\s*(?P<effect2>.+)"
)


def _may_attach_if_you_do(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    second = parse_effect_body(m.group("effect2").strip(), previous_subject=True)
    if not second:
        return None
    if any(s.params.get("target_kind") for s in second):
        return None  # a second RULE 115 target has nowhere to be announced from
    attach_spec = EffectSpec("attach", {"target_kind": "creature_you_control"})
    return [EffectSpec("optional", {
        "effects": [attach_spec.to_dict()] + [s.to_dict() for s in second],
    })]


#: MEC-99: "you may choose to have it deal damage equal to its power to
#: `<target>`. if you do, it assigns no combat damage this turn." (Gaze of
#: Pain's own turn-scoped trigger body, RULE 510.1e) — a `damage_equal_to_
#: power` dealer plus a `prevent_combat_damage_dealt` flag, both wrapped in
#: one `optional`, and both reading "it" as the RULE 603.1 group-subject
#: creature that fired this trigger (``dealer_kind="trigger_subject"``/
#: ``subject="trigger_subject"``) rather than the ability's own source — a
#: temporary triggered ability granted by a sorcery has no combat-relevant
#: source of its own to flag. Narrowly matched rather than routed through
#: the generic `_may_effect_then`/`_MAY_EFFECT_THEN_RE` composition: that
#: recursion parses each half with ``self_subject=True``, never ``group_
#: subject=True``, so it can reach neither the group-subject dealer nor the
#: group-subject "it assigns no combat damage" clause — both primitives
#: already exist (`effects.DamageEqualToPowerEffect`/`PreventCombatDamage
#: DealtEffect`), this is only the recognition.
_MAY_HAVE_IT_DEAL_DAMAGE_EQUAL_TO_POWER_RE = _c(
    rf"you may choose to have it deal damage equal to its power to (?:a )?{TARGET}\.\s*"
    r"if you do,\s*it assigns no combat damage this turn\.?"
)


def _may_have_it_deal_damage_equal_to_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    recipient = _power_recipient(m.group("target"))
    if recipient is None:
        return None
    return [EffectSpec("optional", {
        "effects": [
            EffectSpec("damage_equal_to_power", {
                "dealer_kind": "trigger_subject", "target_kind": recipient,
                **_optional_param(m),
            }).to_dict(),
            EffectSpec("prevent_combat_damage_dealt", {"subject": "trigger_subject"}).to_dict(),
        ],
    })]


#: PAR-111: "whenever a creature an opponent controls enters, you may **have that player lose N life**."
#: (Blood Seeker, Suture Priest) — the controller of the firing object loses the life, while the ability's own
#: controller is the one asked: `segmenter._peel_optional` has already taken the "you may" off the body (the
#: trigger is optional), so this is the group-subject `lose_life` row with the entering creature's controller
#: (`_ENTERING_CONTROLLER`) as the player.
_HAVE_THAT_PLAYER_LOSE_LIFE_RE = _c(rf"have that player lose {NUMBER} life")


def _have_that_player_lose_life(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {"amount": int(m.group("n")), "player": _ENTERING_CONTROLLER})]


def _may_effect_then(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    first = parse_effect_body(m.group("effect1").strip(), self_subject=True)
    if not first:
        return None
    # A *targeted* (RULE 115) antecedent needs its own announced-target
    # step this off-stack wrapper has no way to give it (same reasoning
    # `_pay_cost_then_general`/`_pay_cost_then_or_else` already apply to a
    # targeted follow-up) — fail closed rather than silently drop the target.
    if any(s.params.get("target_kind") for s in first):
        return None
    second = parse_effect_body(m.group("effect2").strip(), self_subject=True)
    if not second:
        return None
    if any(s.params.get("target_kind") for s in second):
        return None
    return [EffectSpec("optional", {
        "effects": [s.to_dict() for s in first] + [s.to_dict() for s in second],
    })]


#: MEC-19's "counter it/that spell[or ability] unless that player/its
#: controller pays `<cost>`." — a `_BECOMES_TARGET_TRIGGER_RE`-anchored
#: triggered ability's own resolution body, the un-keyworded-Ward-shaped
#: cycle's single most common effect (~90 real cards). The captured cost is
#: normalized to its imperative form ("pays"→"pay", "discards"→"discard")
#: before being handed to `costs.parse_activation_cost` at resolve time —
#: that parser's regexes anchor on the imperative ("pay\s+", "discard\s+"),
#: so the printed "pays"/"discards" would otherwise silently fail to match
#: and the cost would resolve as free.
_COUNTER_UNLESS_PAY_RE = _c(
    r"counter (?:it|that spell or ability|that spell|that ability) unless "
    r"(?:that player|its controller) (?P<verb>pays|discards) "
    r"(?P<amount>(?:\{[wubrgcx0-9/]+\})+|\d+ life|a card)"
)


def _counter_unless_pay(m: re.Match[str]) -> list[EffectSpec]:
    verb = "pay" if m.group("verb") == "pays" else "discard"
    return [EffectSpec("counter_unless_pay", {"cost": f"{verb} {m.group('amount')}"})]


#: Perplex — unlike the BECOMES_TARGET family above, this has a normal RULE
#: 115 spell target and a non-mana "unless" cost.
_COUNTER_TARGET_SPELL_UNLESS_DISCARD_HAND_RE = _c(
    r"counter target spell unless its controller discards their hand"
)


def _counter_target_spell_unless_discard_hand(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("counter_unless_pay", {
        "cost": "discard your hand",
        "target_kind": "spell",
    })]


#: "you get {E}{E}" (RULE 122 energy production, the reminder-text
#: parenthetical already stripped by `normalize`) — N energy counters to the
#: effect's controller, the resolve-time sibling of the "Pay {E}" cost. Uses
#: the same generic `add_player_counters` primitive `rad`/`poison` do.
_GET_ENERGY_RE = _c(r"you get (?P<pips>(?:\{e\})+)")


def _get_energy(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_player_counters", {"amount": m.group("pips").count("{e}"), "kind": "energy"})]


#: "you get that many {E}." (Empyreal Voyager, Aurora Shifter, Peema Trailblazer) — the combat damage just dealt.
_GET_THAT_MANY_ENERGY_RE = _c(r"you get that many \{e\}")


def _get_that_many_energy(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_player_counters", {"kind": "energy", "amount_from_trigger_event": "amount"})]


def _transform(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("transform", {})]


#: "exile ~/this saga, then return it/him/her to the battlefield transformed
#: under your/its/his/her owner's control" (RULE 400.7 + RULE 712.8 combined)
#: — distinct from a plain in-place `transform`: this is a Batch 9 shape
#: where the permanent actually leaves and re-enters the battlefield already
#: on its back face (a transforming Saga's own final chapter, Fable of the
#: Mirror-Breaker-shaped; or a transform-flip permanent's activated ability
#: that phrases its own flip this way instead of a bare "transform ~",
#: Ayara/Clive/Jin-Gitaxias-shaped). "this saga" is matched literally since
#: `normalize._SELF_REFERENCE_RE` deliberately excludes it (Saga gets its own
#: dedicated grammar, `catalogue/saga.py`); every other self-reference
#: (including "this equipment") already folds to ``~`` before this runs.
_EXILE_RETURN_TRANSFORMED_RE = _c(
    rf"exile (?:{re.escape(SELF)}|this saga),? then return (?:it|him|her) to "
    r"the battlefield transformed under (?:your control|(?:its|his|her) owner's control)"
)


def _exile_return_transformed(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile_return_transformed", {})]


#: The O-Ring / Banisher Priest / Fiend Hunter family — modern one-sentence
#: templating: "exile `<TARGET>` [an opponent controls] until ~ leaves the
#: battlefield." (~47 SOLO cache cards). `ExileEffect(remember=True)` stamps
#: the exiled card's id onto `GameObject.linked_exile_id`; the companion
#: `LEAVES_BATTLEFIELD` → `return_linked_exile` ability is synthesized by
#: the segmenter (`_EXILE_UNTIL_LEAVES_LTB`), since a body handler emits
#: one ability's effects and the return is a *second* ability. The
#: ``until_source_leaves`` param is that signal. Old two-sentence O-Ring
#: templating ("…exile another target nonland permanent." + a separate
#: "When ~ leaves the battlefield, return the exiled card…") is a
#: different, still-unmodeled shape.
_EXILE_UNTIL_LEAVES_RE = _c(
    rf"exile {TARGET}(?P<opp_ctrl> an opponent controls| defending player controls)? "
    r"until ~ leaves the battlefield"
)
_EXILE_UNTIL_LEAVES_OPP_KINDS: dict[str, str] = {
    "creature": "creature_you_dont_control",
    "permanent": "permanent_you_dont_control",
    "artifact": "artifact_you_dont_control",
    "nonland_permanent": "nonland_permanent_you_dont_control",
    "artifact_creature_or_enchantment": "artifact_creature_or_enchantment_you_dont_control",
}


def _exile_until_leaves(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    if (m.group("opp_ctrl") or "").strip() == "an opponent controls":
        kind = _EXILE_UNTIL_LEAVES_OPP_KINDS.get(kind, kind)
    params: dict = {
        "target_kind": kind,
        "remember": True,
        "until_source_leaves": True,
        **_optional_param(m),
    }
    # See `_destroy`'s own comment: "exile target tapped creature an
    # opponent controls until ~ leaves" (Seal Away-shaped) needs it too.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("exile", params)]


#: "exile all creatures with power 5 or greater until ~ leaves the battlefield." / "exile each nonland permanent with mana
#: value 2 or less until ~ leaves …" (Aligned Hedron Network, Consulate Crackdown, Temporary Lockdown): the plain mass
#: exile, read by the shared "exile all/each" rows, with the linked-return flags the targeted form carries.
_EXILE_ALL_UNTIL_LEAVES_RE = _c(r"(?P<head>exile (?:all|each) .+?) until ~ leaves the battlefield")


def _exile_all_until_leaves(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    specs = match_clause(m.group("head"))
    if not specs or len(specs) != 1 or specs[0].type != "exile":
        return None
    params = specs[0].params
    if params.get("selector") is None and params.get("group") is None:
        return None  # only the untargeted mass exile has a linked set to return
    return [EffectSpec("exile", {**params, "remember": True, "until_source_leaves": True})]


#: PAR-30 "Threaten … tails residue" — the *old two-sentence* O-Ring
#: templating's return half, printed as its own `LEAVES_BATTLEFIELD`
#: trigger line rather than folded into an "exile … until ~ leaves" clause
#: (Journey to Nowhere, Petravark, Slithery Stalker, Faceless Butcher &c.):
#: "return the exiled card[s] to the battlefield under its/their owner's
#: control." → `ReturnLinkedExileEffect`. `gate.parse_oracle`'s own
#: cross-line pass stamps ``remember=True`` onto the companion ETB exile so
#: `GameObject.linked_exile_id` is populated for this to read back.
#:
#: PAR-30: "return the exiled card to its owner's **hand**." is the Lorwyn
#: "Champion" cycle's return half (Champion of the Clachan &c.), paired with
#: a ``behold_exile`` additional cast cost (`segmenter.
#: _ADDITIONAL_COST_BEHOLD_EXILE_RE`) that stamps `linked_exile_id` itself —
#: `ReturnLinkedExileEffect(destination="hand")`.
_RETURN_EXILED_CARD_RE = _c(
    r"return the exiled cards? to (?:"
    r"the battlefield under (?:its owner'?s|their owners'?) control"
    r"|(?P<hand>its owner'?s hand)"
    r")"
)


def _return_exiled_card(m: re.Match[str]) -> list[EffectSpec]:
    if m.groupdict().get("hand"):
        return [EffectSpec("return_linked_exile", {"destination": "hand"})]
    return [EffectSpec("return_linked_exile", {})]


#: PAR-30 "Threaten … tails residue" — Driftgloom Coyote's own O-Ring
#: after-tail: "if that creature had power N or less, put a +1/+1 counter
#: on ~." — the exiled creature (`GameContext.previous_targets`, read at a
#: documented simplification: its last-known power, the object is off the
#: battlefield by now) gates a self-counter (`ConditionalEffect`'s
#: `previous_target_power_at_most`).
_IF_PREV_POWER_SELF_COUNTER_RE = _c(
    r"if (?:that creature|it) had power (?P<n>\d+) or less, "
    r"put a (?P<ck>\+1/\+1|-1/-1|−1/−1) counter on ~"
)


def _if_prev_power_self_counter(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": 1, "kind": _counter_sign(m.group("ck")),
    }, condition={"previous_target_power_at_most": int(m.group("n"))})]


#: "return it/~ to the battlefield transformed under its owner's control"
#: (RULE 400.7 + RULE 712.8, Bruce Banner-shaped) — the graveyard-sourced
#: sibling of `_EXILE_RETURN_TRANSFORMED_RE` above: a dies trigger's own
#: "return it..." (no "exile ~, then" prefix — dying already put it in the
#: graveyard, so this clause returns straight from there) rather than an
#: exile-and-blink. Always self/untargeted, same as that sibling.
_RETURN_FROM_GRAVEYARD_TRANSFORMED_RE = _c(
    rf"return (?:{re.escape(SELF)}|it) to the battlefield transformed under "
    r"(?:your control|(?:its|his|her) owner'?s control)"
)


def _return_from_graveyard_transformed(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_from_graveyard_transformed", {})]


# "Return this card from your graveyard to the battlefield[, tapped]."/"…to
# your hand." — an activated/triggered ability's own untargeted self-
# reanimation (Dread Wanderer/Bloodsoaked Champion/Drownyard Temple, PAR-10's
# discovery: 69+ cache cards) or self-recursion (Abzan Devotee/Aurora
# Eidolon/Chandra's Phoenix, PAR-16: 70+ more). Unlike
# `_RETURN_FROM_GRAVEYARD_TRANSFORMED_RE` above, real printed text says
# "this card" here, not "it"/"~" — there's no antecedent pronoun to fold
# onto, since this is the clause's own opening subject rather than a
# dies-trigger's continuation of "When ~ dies, …". One regex, two
# destinations (a named ``hand`` group rather than two near-duplicate
# regex/handler pairs) since only the tail differs.
#: PAR-143: the card's own name folds to ``~`` ("return ~ from your graveyard …", Narfi, Llanowar
#: Greenwidow), and a battlefield entry may also be "tapped and attacking" (Interceptor).
_RETURN_SELF_FROM_GRAVEYARD_RE = _c(
    r"return (?:this card|~) from your graveyard to "
    r"(?:the battlefield(?P<tapped> tapped)?(?P<atk> and attacking)?"
    # "…with 2 +1/+1 counters on it" (Retrofitted Transmogrant, Phoenix Chick) — the enters-with rider
    # the targeted row already reads, same counter vocabulary.
    rf"(?: with (?P<ewc_n>a|an|\d+) (?P<ewc_kind>-1/-1|\+1/\+1|{'|'.join(KEYWORD_COUNTER_KINDS)}) counters? on it)?"
    r"|(?P<hand>your hand))"
)


def _return_self_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("hand"):
        return [EffectSpec("return_self_from_graveyard_to_hand", {})]
    if m.group("atk") and not m.group("tapped"):
        return None
    params: dict = {"tapped": bool(m.group("tapped"))}
    if m.group("atk"):
        params["attacking"] = True
    if m.group("ewc_kind"):
        params["extra_counters"] = {"kind": m.group("ewc_kind"), "count": count_of(m.group("ewc_n"))}
    return [EffectSpec("return_self_from_graveyard", params)]


#: "When ~ dies, return it to the battlefield [tapped] under its owner's/
#: your control[ with a +1/+1 counter on it]." (RULE 400.7 self-recursion,
#: the "it"-pronoun continuation of a dies trigger — the Feign Death /
#: Demonic Gifts / Ashcloud Phoenix-adjacent cycle). `_SELF_SUBJECT`'s bare
#: "it" the same ungated way `_tap_self` reads it — this row only ever
#: fires when the clause literally opens "return it/~/this creature …".
_RETURN_SELF_TO_BATTLEFIELD_RE = _c(
    rf"return (?:{_SELF_SUBJECT}|this card) to the battlefield(?P<tapped> tapped)? under "
    r"(?P<whose>its owner'?s|your) control"
    # "…with 2 +1/+1 counters on it" (Infernal Vessel, PAR-142) — an amount and the same counter
    # vocabulary the targeted graveyard row reads (a +N/+N with N > 1 is no counter kind: it is N of +1/+1).
    rf"(?: with (?P<cn_n>a|an|\d+) (?P<cn_kind>-1/-1|\+1/\+1|{'|'.join(KEYWORD_COUNTER_KINDS)}) counters? on it)?"
)


#: "If it was a creature, return it to the battlefield under its owner's control. It's an
#: enchantment." (Enduring Courage / Curiosity / Innocence / Tenacity / Friendship; Enduring
#: Vitality is the hand-authored original) — `DiesReturnAsEnchantmentEffect`.
_DIES_RETURN_AS_ENCHANTMENT_RE = _c(
    rf"(?:if it was a creature, )?return (?:{_SELF_SUBJECT}) to the battlefield under its owner'?s "
    r"control\. it'?s an enchantment\.?"
)


def _return_self_to_battlefield(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"tapped": bool(m.group("tapped"))}
    if m.group("whose").lower() == "your":
        params["under_your_control"] = True
    if m.groupdict().get("cn_kind"):
        params["extra_counters"] = {"kind": m.group("cn_kind"), "count": count_of(m.group("cn_n"))}
    return [EffectSpec("return_self_to_battlefield", params)]


#: PAR-124/PAR-125: "When target creature dies this turn, return **that
#: card** to the battlefield under its owner's control." (Graceful
#: Reprieve) — `CreateTurnTriggerEffect.target_kind` keeps the ability
#: bound to its own source (the spell, PAR-125's own fix), so "that card"
#: is read live off the firing DIES event instead
#: (`ReturnSelfToBattlefieldEffect.target_kind="trigger_subject"`, the
#: same live-event-reference idiom `TapEffect`'s own group-subject
#: pronoun already uses) rather than via `self.source` identity. Kept as
#: its own, `self_subject_only`-gated row rather than folded into
#: `_RETURN_SELF_TO_BATTLEFIELD_RE`: "that card" already means something
#: *else* (PAR-18/30's own previous-clause pronoun) everywhere this
#: dispatch isn't the target-bound-as-source shape, so it must only be
#: offered when the caller has actually rewritten "target creature
#: `<verb>`" into this self-subject form.
_RETURN_TARGET_TO_BATTLEFIELD_SELF_RE = _c(
    r"return that card to the battlefield(?P<tapped> tapped)? under "
    r"(?P<whose>its owner'?s|your) control"
)


def _return_target_to_battlefield_self(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {"tapped": bool(m.group("tapped")), "target_kind": "trigger_subject"}
    if m.group("whose").lower() == "your":
        params["under_your_control"] = True
    return [EffectSpec("return_self_to_battlefield", params)]


_RETURN_TRIGGER_CARD_TO_HAND_RE = _c(r"return that card to your hand")


def _return_trigger_card_to_hand(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_from_graveyard", {
        "destination": "hand", "trigger_subject_key": "remembered",
    })]


def _become_prepared(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("become_prepared", {})]


#: "if your library has no cards in it, you win the game" (Jace, Wielder of
#: Mysteries' "-8: Draw seven cards. Then if your library has no cards in
#: it, you win the game." tail, RULE 104.2) — a plain conditional one-shot,
#: not the standing replacement `catalogue.replacements`' sibling clause
#: covers (that one gates a *draw*, this one gates an already-resolved
#: loyalty ability's own follow-up sentence).
def _win_if_empty_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("win_game", {"if_empty_library": True})]


#: RULE 602.1-adjacent per-instance activation cap: "Activate only once each
#: turn." (Quirion Ranger/Scryb Ranger-shaped) — a plain trailing sentence in
#: an activated ability's own body (after the cost's colon), sitting
#: alongside its real effect ("Untap target creature. Activate only once
#: each turn." — two sentences `parse_effect_body`'s connector-splitting
#: already tries independently). Not a real one-shot effect: this handler
#: claims the clause but emits a *marker* `EffectSpec` `effect_binder.
#: bind_ability`'s "activated" branch recognizes and strips before binding,
#: turning it into `ActivatedAbility.once_per_turn` instead of a `GameEffect`
#: (mirroring `TriggeredAbility.once_per_turn`'s own RULE 603.2 stamp).
ONCE_PER_TURN_MARKER = "once_per_turn_marker"
_ONCE_PER_TURN_RE = _c(r"activate (?:this ability )?only once each turn")


def _once_per_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(ONCE_PER_TURN_MARKER, {})]


#: RULE 603.2's own once-per-turn limiter, PAR-14 — "This ability triggers
#: only once each turn." (Chance-Met Elves/Prudent Fateseer-shaped) — a
#: trailing sentence in a *triggered* ability's own body, the exact same
#: "claim the clause, emit a marker, let the binder fold it into a flag"
#: shape `ONCE_PER_TURN_MARKER` above uses for an *activated* ability, but
#: textually distinct ("this ability triggers", not "activate"), so its own
#: row rather than widening that one. `segmenter.segment_line`'s "triggered"
#: dispatch strips this marker from the parsed body and folds it into
#: `AbilitySpec.trigger["limit"]`, consumed by `effect_binder.bind_ability`
#: as `TriggeredAbility.once_per_turn` — a primitive that already existed
#: (built for Dionus, Elvish Archdruid's *granted* ability) but no
#: oracle-text recognizer had ever reached from an ordinary printed card.
TRIGGER_ONCE_PER_TURN_MARKER = "trigger_once_per_turn_marker"
_TRIGGER_ONCE_PER_TURN_RE = _c(r"this ability triggers only once each turn")


def _trigger_once_per_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(TRIGGER_ONCE_PER_TURN_MARKER, {})]


#: PAR-135: "…, you may draw a card. **Do this only once each turn.**" — the once-per-turn limit on the
#: *action* a trigger offers, not on the trigger: it still triggers every time, the controller just can't
#: perform the optional action a second time this turn, and declining the first doesn't use it up. So it is
#: not `TRIGGER_ONCE_PER_TURN_MARKER` (Ondu Spiritdancer, Irreverent Gremlin). The binder strips the marker
#: into `TriggeredAbility.action_once_per_turn`; `gate._action_limit_ok` refuses it anywhere else.
ACTION_ONCE_PER_TURN_MARKER = "action_once_per_turn_marker"
_ACTION_ONCE_PER_TURN_RE = _c(r"do this only once each turn")


def _action_once_per_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(ACTION_ONCE_PER_TURN_MARKER, {})]


#: RULE 602.5d timing restriction: "Activate only as a sorcery." (older
#: template) / "Activate this ability only any time you could cast a sorcery."
#: (current) — like `ONCE_PER_TURN_MARKER`, a trailing sentence in the
#: activated ability's own body, not a real one-shot effect. Claimed as a
#: marker `EffectSpec` that `effect_binder.bind_ability`'s "activated" branch
#: strips and folds into `ActivationCost.sorcery_speed_only` (already enforced
#: by `game_engine.can_activate` via `_sorcery_speed_ok`), the same lever the
#: engine already uses for level-up / Class-level sorcery-speed abilities.
#: Only the two canonical *sorcery-speed* phrasings (RULE 605.3b / "any time
#: you could cast a sorcery"). Deliberately not "only during your turn"
#: (its own, wider `ONLY_DURING_YOUR_TURN_MARKER` below — folding it in
#: here would be *wrong*, since a non-empty stack is still legal for that
#: one) or "before attackers are declared" (still unclaimed, fail-closed,
#: until modeled precisely).
SORCERY_SPEED_MARKER = "sorcery_speed_marker"
_SORCERY_SPEED_RE = _c(
    r"activate (?:this ability )?only "
    r"(?:as a sorcery|any time you could cast a sorcery)"
)


def _sorcery_speed(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(SORCERY_SPEED_MARKER, {})]


#: PAR-109, RULE 605.3a: "Spend only black mana on X." (Crypt Rats, Crimson Hellkite) — a trailing sentence of an
#: activated ability's body, folded by `effect_binder.bind_ability` into `ActivationCost.x_spend_color` (the
#: `SORCERY_SPEED_MARKER` shape).
X_SPEND_COLOR_MARKER = "x_spend_color_marker"
_X_SPEND_COLOR_RE = _c(r"spend only (?P<color>white|blue|black|red|green) mana on x")


def _x_spend_color(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(X_SPEND_COLOR_MARKER, {"color": _COLOR_WORDS[m.group("color").lower()]})]


#: RULE 602.5d's *other* timing restriction: "Activate only during your
#: turn." (Wishclaw Talisman-shaped) — deliberately left unclaimed above
#: (see `SORCERY_SPEED_MARKER`'s own docstring) since it's a genuinely
#: different, wider window than sorcery-speed (still legal at instant
#: speed with a non-empty stack — just not outside the controller's own
#: turn). Same marker-then-strip shape, folded by `effect_binder.
#: bind_ability` into `ActivationCost.only_during_your_turn`
#: (`GameEngine._only_during_your_turn_ok`) instead of `sorcery_speed_only`.
ONLY_DURING_YOUR_TURN_MARKER = "only_during_your_turn_marker"
_ONLY_DURING_YOUR_TURN_RE = _c(r"activate (?:this ability )?only during your turn")


def _only_during_your_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(ONLY_DURING_YOUR_TURN_MARKER, {})]


# PAR-28: marker `EffectSpec`s synthesized by `segmenter._segment_keyword_
# labeled_ability` for the "Keyword — [ability]" families (Boast/Exhaust/
# Power-up/Forecast — RULE 702.142/702.177/702.57). They carry no oracle
# text of their own (there is no regex row here — the keyword name *is* the
# recognition), and `effect_binder.bind_ability`'s "activated" branch strips
# and folds each into an `ActivatedAbility`/`ActivationCost` flag exactly
# like `ONCE_PER_TURN_MARKER` above.
#: RULE 702.177a / Power-up — "Activate only once." (per game, per ability).
ACTIVATE_ONLY_ONCE_MARKER = "activate_only_once_marker"
#: Power-up — "Reduce the cost by its mana cost if it entered this turn."
POWERUP_COST_REDUCTION_MARKER = "powerup_cost_reduction_marker"
#: RULE 702.57a — a forecast ability is activated from the card's hand.
FROM_HAND_MARKER = "from_hand_marker"


# PAR-10: "Activate only as a sorcery and only if `<condition>`." (Cabal
# Inquisitor/Dread Wanderer/Hall of Oracles/Jin-Gitaxias // The Great
# Synthesis) and its bare sibling "Activate only if `<condition>`."
# (Potioner's Trove) — RULE 602.5d timing stacked with (or standing in for)
# an activation-legality board condition, a second marker `effect_binder.
# bind_ability`'s "activated" branch folds into `ActivationCost.
# activation_condition`, checked by `GameEngine.can_activate` via
# `game/static_conditions.condition_holds` — the same RULE 613.6 whitelist a
# permanent's own "as long as `<condition>`" static already uses, so a
# condition recognized for one is recognized (and evaluated identically) for
# both.
#
# `game/static_conditions.py`'s full vocabulary lives behind
# `catalogue.static_handlers.static_condition` — which this module can't
# import (`static_handlers` already imports `SORCERY_SPEED_MARKER` from
# *here*, so the reverse import would cycle). This is deliberately a small,
# independent subset covering only the phrasings real cards actually pair
# with an activation condition today: hand/graveyard card counts and "cast
# an instant or sorcery spell this turn" (`cast_instant_or_sorcery_this_
# turn` is new — see `static_conditions.py` and `static_handlers.py`'s own
# `_STATIC_CONDITION_RES` row, which picks up the same phrase for free for
# the "created" ~250-clause "as long as" family: Haunting Figment/Leapfrog/
# Piston-Fist Cyclops). Every one of the ~150 *other* "Activate only if …"
# phrasings in the cache (`you control a Plains`, `this creature is
# attacking`, `a creature died this turn`, …) is real, standing PAR-12 tail
# work, not part of this ticket — fail-closed here, same as everywhere else.
ACTIVATION_CONDITION_MARKER = "activation_condition_marker"
_ACTIVATION_CONDITION_RES: list[tuple[re.Pattern[str], Callable[[re.Match[str]], dict]]] = [
    # PAR-98: the legendary-matters activation gate shared by Rivendell and
    # Haunt of the Dead Marshes.  It is a live board count, not a spell-cast
    # history condition.
    (re.compile(r"you control a legendary creature", re.I),
     lambda m: {"kind": "control_count", "selector": "legendary_creatures_you_control", "min": 1}),
    # PAR-64 / Raid: player-scoped declaration history, deliberately unlike
    # Boast's source_attacked_this_turn condition.
    (re.compile(r"you attacked this turn", re.I),
     lambda m: {"kind": "you_attacked_this_turn"}),
    (re.compile(r"you have (?P<n>\d+) or more cards in hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_least", "amount": int(m.group("n"))}),
    (re.compile(r"you have (?P<n>\d+) or fewer cards in hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_most", "amount": int(m.group("n"))}),
    (re.compile(r"there are (?P<n>\d+) or more cards in your graveyard", re.I),
     lambda m: {"kind": "control_count", "selector": "cards_in_your_graveyard",
                "min": int(m.group("n"))}),
    (re.compile(r"an opponent has (?P<n>\d+) or more cards in (?:their|his or her) graveyard", re.I),
     lambda m: {"kind": "opponent_count", "selector": "cards_in_your_graveyard",
                "min": int(m.group("n"))}),
    (re.compile(r"you'?ve cast an instant or sorcery spell this turn", re.I),
     lambda m: {"kind": "cast_instant_or_sorcery_this_turn"}),
    # PAR-98 (Seeker of Insight, Tapestry of the Ages): the same shared
    # `static_conditions` predicate the "beginning of combat … if you've cast a
    # noncreature spell this turn" triggers (Franklin Richards) already read.
    (re.compile(r"you'?ve cast a noncreature spell this turn", re.I),
     lambda m: {"kind": "cast_noncreature_spell_this_turn"}),
    # PAR-120: "creatures you control have total power N or greater/less"
    # (Atarka Beastbreaker/Crater Elemental/Glade Watcher-shaped Formidable
    # activation gates) — the same `total_power_creatures_you_control`
    # `count_selector` reading, and the same `control_count` condition kind,
    # `static_handlers._STATIC_CONDITION_RES` already carries for this
    # phrase's other three surfaces (leading "if", trigger "while", RULE
    # 613.6 "as long as"); this table's own entries above already duplicate
    # a few of that one's rows by hand rather than falling back to it, so
    # this row does the same rather than reopening that separate question.
    (re.compile(r"creatures you control have total power (?P<n>\d+) or (?P<cmp>greater|less)", re.I),
     lambda m: {
         "kind": "control_count", "selector": "total_power_creatures_you_control",
         ("min" if m.group("cmp") == "greater" else "max"): int(m.group("n")),
     }),
    # PAR-120: "you control a desert or there is a desert card in your
    # graveyard" (Wall of Forgotten Pharaohs) — the same `any`-combined
    # compound `static_handlers.static_condition`'s own generic "`<A>` or
    # `<B>`" fallback already builds for the other three surfaces this
    # phrase reaches; this table doesn't share that fallback (see the
    # module-level note on `_ACTIVATION_CONDITION_RES` duplicating
    # `_STATIC_CONDITION_RES` by hand), so it gets its own matching row.
    (re.compile(r"you control a desert or there is a desert card in your graveyard", re.I),
     lambda m: {"kind": "any", "conditions": [
         {"kind": "control_count",
          "selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "desert"}}, "min": 1},
         {"kind": "subtype_in_graveyard", "subtype": "desert"},
     ]}),
]


def _activation_condition_dict(text: str) -> Optional[dict[str, Any]]:
    stripped = text.strip().rstrip(".").strip()
    for pattern, build in _ACTIVATION_CONDITION_RES:
        match = pattern.fullmatch(stripped)
        if match is not None:
            return build(match)
    # PAR-120: every row above is a hand-copied duplicate of a phrase
    # `static_handlers._STATIC_CONDITION_RES`/`static_condition()` already
    # recognizes for this same condition's other three surfaces (leading
    # "if", trigger "while", "as long as") — this table's own module note
    # has said so at each of this session's four additions to it (commander,
    # total power twice, the desert compound) without ever taking the actual
    # architectural step. Tried only once every row above has declined, so
    # an existing row's own kind spelling (`control_legendary_subtype` vs.
    # `control_count`/`legendary_creatures_you_control`, the dedicated
    # `cast_noncreature_spell_this_turn` flag vs. the newer generic
    # `event_this_turn` reading) is preserved exactly for any phrase this
    # table already recognized — zero behaviour change for an already-
    # shipped card — and only a phrase genuinely new to *both* tables reaches
    # the shared vocabulary for the first time.
    from .static_handlers import static_condition

    return static_condition(stripped)


_SORCERY_SPEED_AND_CONDITION_RE = _c(
    r"activate (?:this ability )?only as a sorcery and only if (?P<cond>.+)"
)


def _sorcery_speed_and_condition(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    condition = _activation_condition_dict(m.group("cond"))
    if condition is None:
        return None
    return [
        EffectSpec(SORCERY_SPEED_MARKER, {}),
        EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": condition}),
    ]


_ACTIVATE_ONLY_IF_RE = _c(r"activate (?:this ability )?only if (?P<cond>.+)")
_ACTIVATE_DURING_YOUR_TURN_AND_IF_RE = _c(
    r"activate (?:this ability )?only during your turn and only if (?P<cond>.+)"
)


def _activate_during_your_turn_and_if(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    condition = _activation_condition_dict(m.group("cond"))
    if condition is None:
        return None
    return [EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": {
        "kind": "all", "conditions": [{"kind": "your_turn"}, condition],
    }})]


def _activate_only_if(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    condition = _activation_condition_dict(m.group("cond"))
    if condition is None:
        return None
    return [EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": condition})]


def _token_keywords(text: str) -> Optional[list[str]]:
    """Validate a token's "with <keywords>" clause → flag-keyword slugs, or None.

    Fail-closed: if any listed ability isn't a parameterless (flag) keyword, the
    whole token clause is left unclaimed rather than dropping the ability
    (a token that silently lacks "flying" would be a wrong game state). The
    one parametric exception is a *bare* "hexproof" — RULE 702.11b's
    QUALITY shape (PAR-5) exists for the scoped "hexproof from <colour>"
    variant, but plain "hexproof" with no "from" is still its own complete,
    unscoped keyword (the shape it had before PAR-5), so it's granted here
    exactly like a FLAG keyword. A scoped "hexproof from black" never
    reaches this branch: `keyword_slug` only resolves the bare "hexproof"/
    "hexproof from" spellings, so a real quality suffix keeps `kdef` ``None``
    and still fails closed below. A landwalk variant ("forestwalk") is the
    same kind of exception, same reasoning as `static_handlers._flag_
    keywords`' own — RULE 702.14's land type lives in the slug itself, so
    the grant needs no separate quality param.
    """
    slugs: list[str] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        slug = _grantable_flag_slug(part)
        if slug is None:
            return None
        slugs.append(slug)
    return slugs


def _grantable_flag_slug(part: str) -> Optional[str]:
    """A single keyword token → its grantable slug, or ``None`` if it isn't a
    FLAG keyword, bare "hexproof", or a landwalk variant (PAR-74) — the three
    shapes `_token_keywords`/`_split_keywords_with_parametric` can grant
    without a separate quality param. Shared so the two callers (a token's
    "with <keywords>" clause and a temporary "gains <keywords> until end of
    turn" pump) stay in lockstep."""
    slug = keyword_slug(part)
    kdef = KEYWORDS.get(slug)
    if kdef is not None and kdef.slug in UNGRANTABLE_FLAG_KEYWORDS:
        return None
    if kdef is not None and (kdef.shape is KeywordShape.FLAG or kdef.slug == "hexproof"):
        return kdef.slug
    resolved = resolve_keyword(slug)
    if resolved is not None and resolved.slug == "landwalk" and slug != "landwalk":
        return slug
    return None


#: ENG-31: the parametric keywords a *grant* ("gains firebending N until end
#: of turn", "has firebending N as long as …", a token "with firebending N")
#: can model — the ones whose RULE 702 text is a triggered ability
#: `effect_binder._KEYWORD_TRIGGERED_BUILDERS` re-synthesizes off the granted
#: N, plus toxic (PAR-102), which no builder needs: `combat.toxic_value` reads the granted N live at
#: damage time. Every other NUMBER-shape keyword (renown, …) stays fail-closed for a grant.
_GRANTABLE_PARAMETRIC_KEYWORDS: frozenset[str] = frozenset(
    {"firebending", "annihilator", "afflict", "bushido", "toxic"}
)


#: PAR-98 (Riftmarked Knight): "…token with flanking, protection from white,
#: and haste" — RULE 702.16's protection is a *quality*, not a flag keyword, so
#: it can't ride the keyword list. It is carried as the token's own oracle text
#: instead (`combat.protections_of_text` reads exactly that off a synthesized
#: token, `CreateTokenEffect.oracle_text`), and the remaining flag keywords keep
#: their usual route.
_TOKEN_PROTECTION_PART_RE = re.compile(r"protection from (white|blue|black|red|green)")


def _split_token_protection(text: str) -> tuple[str, str]:
    """A token's "with …" list → ``(keywords-without-protection, oracle text)``."""
    kept: list[str] = []
    protections: list[str] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        pm = _TOKEN_PROTECTION_PART_RE.fullmatch(part)
        if pm:
            protections.append(f"Protection from {pm.group(1)}")
        else:
            kept.append(part)
    return ", ".join(kept), "\n".join(protections)


def _split_keywords_with_parametric(
    text: str,
) -> Optional[tuple[list[str], list[dict[str, object]]]]:
    """A "<kw>[, <kw> and firebending N …]" list → ``(flag_slugs,
    [{"name", "n"}, ...])``, or ``None`` if any entry is neither a FLAG
    keyword nor a grantable parametric one (fail-closed, like
    `_token_keywords`). ``"firebending 2"`` / ``"annihilator 1"`` entries go
    to the parametric list; everything else must be a plain flag."""
    flags: list[str] = []
    parametric: list[dict[str, object]] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        pm = re.fullmatch(r"([a-z]+)\s+(\d+)", part)
        if pm and pm.group(1) in _GRANTABLE_PARAMETRIC_KEYWORDS:
            parametric.append({"name": pm.group(1), "n": int(pm.group(2))})
            continue
        slug = _grantable_flag_slug(part)
        if slug is None:
            return None
        flags.append(slug)
    return flags, parametric


#: "…token that's tapped and attacking" / "…tokens that are tapped and
#: attacking" (RULE 508.4 — Captain's Claws, Basri Ket, Anim Pakal, the
#: whole "whenever ~ attacks, make a token" family). An optional suffix on
#: the inline-token regexes; `CreateTokenEffect` handles the tap + the
#: `RulesEngine.put_onto_battlefield_attacking` call.
_TOKEN_TAPPED_ATTACKING = (
    r"(?P<tapped_attacking> that'?s tapped and attacking| that are tapped and attacking)?"
    # RULE 508.4: a trailing "that player"/"that opponent" names the defender
    # the source is already attacking (Seraphic Greatsword, Soaring
    # Lightbringer) — `put_onto_battlefield_attacking` derives it from the
    # other attackers, so this is consumed rather than re-modeled. The
    # per-opponent distributive form ("for each opponent, create … attacking
    # that player") isn't reached here — the connector loop leaves that
    # "for each opponent, " prefix on the clause and the create-token rows
    # never fullmatch it.
    r"(?P<atk_defender> that (?:player|opponent))?"
)


#: RULE 105.1: the five colors, in WUBRG order — a token that is "all colors".
_ALL_COLORS = ("W", "U", "B", "R", "G")


def _inline_create_token_params(m: re.Match[str]) -> Optional[dict]:
    """The shared ``create_token`` params for the inline-stats creature-token
    grammar (``p``/``t``/``mid``/``kw``/``n``/``tapped``/``legendary``/``who``
    groups) — factored out of `_create_token` so `_create_token_and_attach`
    can build the same params for its own, differently-wrapped clause."""
    colors, subtypes, is_artifact = _split_token_mid_words(m.group("mid") or "")
    keywords: list[str] = []
    parametric_keywords: list[dict[str, object]] = []
    protection_text = ""
    if m.groupdict().get("kw"):
        kw_text, protection_text = _split_token_protection(m.group("kw"))
        split = _split_keywords_with_parametric(kw_text)
        if split is None:
            return None  # unrecognised "with …" ability → fail-closed
        keywords, parametric_keywords = split
    params: dict = {
        # PAR-124: "create **X** 2/2 red Human Knight creature tokens with
        # trample and haste." (Forth Eorlingas!) — `count_or_x_of`'s ``"x"``
        # sentinel, resolved by the generic `_substitute_x` per-attr loop
        # (`CreateTokenEffect.count`) the same way any other effect's own
        # ``count``/``amount`` already is; every existing caller's own
        # ``n`` group only ever captures a plain number/"a"/"an", so this is
        # a no-op widening for them.
        "count": count_or_x_of(m.group("n")),
        "power": int(m.group("p")),
        "toughness": int(m.group("t")),
        "colors": colors,
        "subtypes": subtypes,
        "keywords": keywords,
    }
    if parametric_keywords:  # ENG-31: "… token with firebending N"
        params["parametric_keywords"] = parametric_keywords
    if protection_text:
        params["oracle_text"] = protection_text
    quoted_cda = m.groupdict().get("quoted_cda")
    if quoted_cda:
        # RULE 604.3: a token owns its quoted CDA. Validate the whole ability
        # before preserving it as the new card's oracle text.
        from .static_handlers import static_effect_specs  # function-scoped: static_handlers imports this module

        normalized = re.sub(r"^(?:this token|this creature)'s", "~'s", quoted_cda, flags=re.I)
        parsed = static_effect_specs(normalized)
        if not parsed or len(parsed) != 1 or parsed[0].type != "pt_cda":
            return None
        params["oracle_text"] = "\n".join(filter(None, (protection_text, quoted_cda)))
    if m.groupdict().get("dies_life"):
        # STX Pest — "with \"when ~ dies, you gain N life.\""
        params["token_dies_gain_life"] = int(m.group("dies_life"))
    if m.groupdict().get("all_colors"):
        params["colors"] = list(_ALL_COLORS)
    if is_artifact:
        params["is_artifact"] = True
    if subtypes:
        params["token_name"] = " ".join(subtypes)
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    # "**Each player** creates …" / "**each opponent** creates …" — everyone
    # gets their own ``count`` tokens under their own control, rather than
    # the effect's controller getting them all.
    who = (m.groupdict().get("who") or "").strip().lower()
    if "each" in who:
        # "**Each player** / **each opponent** creates …" — only the "each …"
        # phrasings mean everyone; a captured "you" is the ordinary
        # controller-scoped default, not a `creators` override.
        params["creators"] = "each_opponent" if "opponent" in who else "each_player"
    elif who.startswith("target "):
        # "**Target opponent** creates …" (the Hunted cycle) — the chosen
        # player makes the tokens under their own control.
        params["creators"] = "target"
        params["target_kind"] = "opponent" if who == "target opponent" else "player"
    if m.groupdict().get("per_opp"):
        # "**For each opponent**, [you] create a … token[ that's tapped and
        # attacking that opponent]." (Endless Foot Assault, Stampede Surfer)
        # — the controller makes one token per opponent; with `attacking`
        # each is put into combat against a distinct opponent.
        params["per_opponent"] = True
    if m.groupdict().get("tapped"):  # RULE 110.5a — enters tapped, not tapped after
        params["tapped"] = True
    if m.groupdict().get("tapped_attacking"):  # RULE 508.4 — enters tapped and attacking
        params["tapped"] = True
        params["attacking"] = True
    return params


def _create_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    return [EffectSpec("create_token", params)]


_CREATE_TOKEN_QUOTED_CDA_RE = _c(
    rf"(?P<who>each player |each opponent )?creates? {COUNT} "
    r"(?P<mid>[a-z ]*?)creature tokens? with (?:(?P<kw>[a-z ]+?) and )?"
    r'"(?P<cda>(?:this token|this creature|~)\'?s power[^\"]+)"'
)


def _create_token_quoted_cda(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # A */* token prints its P/T only in the quoted characteristic-defining
    # ability. Zero is a placeholder; the bound CDA defines both values in
    # layer 7a as soon as the token enters (RULE 604.3/613.7).
    from .static_handlers import static_effect_specs  # function-scoped: static_handlers imports this module

    oracle = m.group("cda")
    normalized = re.sub(r"^(?:this token|this creature)'s", "~'s", oracle, flags=re.I)
    parsed = static_effect_specs(normalized)
    if not parsed or len(parsed) != 1 or parsed[0].type != "pt_cda":
        return None
    colors, subtypes, is_artifact = _split_token_mid_words(m.group("mid"))
    if not subtypes:
        return None
    params: dict[str, Any] = {
        "count": count_of(m.group("n")), "power": 0, "toughness": 0,
        "colors": colors, "subtypes": subtypes,
        "token_name": " ".join(subtypes), "oracle_text": oracle,
    }
    if m.group("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    if is_artifact:
        params["is_artifact"] = True
    who = m.group("who") or ""
    if who:
        params["creators"] = "each_opponent" if "opponent" in who else "each_player"
    return [EffectSpec("create_token", params)]


_CREATE_NAMED_TOKEN_QUOTED_CDA_RE = _c(
    r"create (?P<name>[a-z][a-z' -]*), a legendary (?P<mid>[a-z ]*?)"
    r'creature token with "(?P<cda>[^\"]+)"'
)


def _create_named_token_quoted_cda(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .static_handlers import static_effect_specs  # function-scoped: static_handlers imports this module

    name, oracle = m.group("name").strip(), m.group("cda")
    normalized = re.sub(rf"^{re.escape(name)}'s", "~'s", oracle, flags=re.I)
    parsed = static_effect_specs(normalized)
    if not parsed or len(parsed) != 1 or parsed[0].type != "pt_cda":
        return None
    colors, subtypes, is_artifact = _split_token_mid_words(m.group("mid"))
    if not subtypes:
        return None
    return [EffectSpec("create_token", {
        "count": 1, "power": 0, "toughness": 0,
        "colors": colors, "subtypes": subtypes, "token_name": name,
        "oracle_text": oracle, "legendary": True,
        **({"is_artifact": True} if is_artifact else {}),
    })]


#: "Create that many 1/1 green Elf Warrior creature tokens." (Lathril,
#: Blade of the Elves-shaped "whenever ~ deals combat damage to a player"
#: payoff, ~38 real cards) — "that many" always refers back to the firing
#: event's own ``amount`` (RULE 603.1), read fresh at resolve time
#: (`CreateTokenEffect.count_from_trigger_event`) rather than a literal
#: count. Reuses `_xx_token_mid_params` for the "<mid> token[s][ with
#: <kw>]" tail (a fixed literal count needs none of `_inline_create_token_
#: params`'s ``n``/``who`` groups).
_CREATE_TOKEN_THAT_MANY_RE = _c(
    r"creates? that many "
    r"(?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z, ]+))?"
    + _TOKEN_TAPPED_ATTACKING
)


def _create_token_that_many(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    params.update({
        "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_from_trigger_event": "amount",
    })
    if m.groupdict().get("tapped"):
        params["tapped"] = True
    if m.groupdict().get("tapped_attacking"):  # RULE 508.4
        params["tapped"] = True
        params["attacking"] = True
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    return [EffectSpec("create_token", params)]


#: A dynamic token *count* (RULE 601.2c, `CreateTokenEffect.count_selector`
#: — `continuous.count_selector`'s own vocabulary), for the two real
#: phrasings found so far: "…for each `<subtype>` you control" (Elvish
#: Promenade-shaped) and "…for each attacking creature" (Embercleave's own
#: cost-reduction wording, reused here for a token count). A count-selector
#: word not in this table stays unclaimed rather than guessed at.
def _count_selector_for_phrase(
    subtype: Optional[str], attacking: Optional[str],
) -> "Optional[str | dict[str, Any]]":
    if attacking:
        return "attacking_creatures"
    if subtype:
        # "for each Forest / land / creature / Elf you control" — the shared
        # count grammar, so a land or card type isn't read as a creature type.
        return subtype_count_selector(subtype)
    return None


#: "Create a 1/1 green Elf Warrior creature token for each Elf you control."
#: (Elvish Promenade-shaped) — the trailing-count-selector sibling of the
#: plain `create_token` row above.
_CREATE_TOKEN_FOR_EACH_RE = _c(
    rf"(?:(?P<who>you|each player|each opponent|target player|target opponent) )?creates? {COUNT} "
    rf"(?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    rf"(?P<mid>[a-z ]*?)creature tokens?"
    rf"(?: with (?P<kw>[a-z, ]+))?"
    r" for each (?:(?P<subtype>[a-z]+) you control|(?P<attacking>attacking creature))"
)


def _create_token_for_each(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    selector = _count_selector_for_phrase(m.groupdict().get("subtype"), m.groupdict().get("attacking"))
    if selector is None:
        return None
    params.pop("count", None)
    params["count_selector"] = selector
    return [EffectSpec("create_token", params)]


#: "Create X 1/1 green Elf Warrior creature tokens, where X is the number
#: of attacking creatures." (Galadhrim Ambush-shaped) — the "announce X,
#: then explain it" sibling of the "for each" row above. MEC-27: widened
#: from its own narrow subtype/attacking-only tail to the full
#: `subgrammars.DEVOTION` vocabulary (bare "creatures/permanents/artifacts/
#: lands/enchantments/planeswalkers you control", the two-word compounds,
#: devotion-to-colour) — the same reading `_CREATE_TOKEN_NUMBER_EQUAL_
#: DEVOTION_RE` already uses for the "equal to" phrasing, just for this
#: row's "where x is" surface wording instead.
_CREATE_TOKEN_XX_WHERE_RE = _c(
    r"create x (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    rf"(?: with (?P<kw>[a-z, ]+))?" + _TOKEN_TAPPED_ATTACKING + rf", where x is {DEVOTION}"
)

#: "Create X 1/1 red Elemental creature tokens with haste, where X is ~'s
#: power." (Elemental Mastery) — source power is a live selector, so a pump
#: before resolution changes how many tokens are made.
_CREATE_TOKEN_XX_SOURCE_POWER_RE = _c(
    r"create x (?P<p>\d+)/(?P<t>\d+) (?P<mid>[a-z ]*?)creature tokens?"
    r" with (?P<kw>[a-z, ]+), where x is ~'?s power"
)


def _create_token_xx_source_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.group("kw"))
    if params is None:
        return None
    return [EffectSpec("create_token", {
        **params, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_selector": "source_power",
    })]


def _create_token_xx_where(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    selector = devotion_selector(m)
    if selector is None:
        return None
    if m.groupdict().get("tapped_attacking"):  # RULE 508.4
        params["tapped"] = True
        params["attacking"] = True
    return [EffectSpec("create_token", {
        **params, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_selector": selector,
    })]


#: RULE 202.2f/700.6 "create a number of 1/1 white Soldier creature tokens
#: equal to your devotion to white." (Evangel of Heliod/Master of Waves-
#: shaped) — a third surface wording for the same dynamic-count shape
#: `_CREATE_TOKEN_FOR_EACH_RE`/`_CREATE_TOKEN_XX_WHERE_RE` already cover,
#: this time keyed to `DEVOTION` instead of a `count_selector` subtype word.
_CREATE_TOKEN_NUMBER_EQUAL_DEVOTION_RE = _c(
    r"creates? a number of (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    rf"(?: with (?P<kw>[a-z, ]+))? equal to {DEVOTION}"
)


def _create_token_number_equal_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    selector = devotion_selector(m)
    if not selector:
        return None
    if m.groupdict().get("tapped"):
        params["tapped"] = True
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    return [EffectSpec("create_token", {
        **params, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_selector": selector,
    })]


#: The inline-stats creature-token grammar `_create_token`'s own `EffectHandler`
#: row wraps, reused bare here (no leading "creates?") so it can be embedded
#: inside a bigger clause — "create **a 1/1 white Halfling creature token**
#: and attach ~ to it." (Auxiliary Boosters/Field-Tested Frying Pan's own
#: second sentence) needs the token description without also consuming the
#: "and attach …" tail the way the top-level row's fullmatch would demand.
_CREATE_TOKEN_INLINE = (
    rf"{COUNT} (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    # ``0-9`` in the keyword capture is ENG-31's "… token with firebending
    # N" — `_inline_create_token_params` splits a "<name> <N>" entry into
    # ``parametric_keywords`` and fail-closes on any other numbered ability.
    rf"(?P<mid>[a-z ]*?)creature tokens?(?: with (?P<kw>[a-z0-9, ]+))?"
)

#: "create a 1/1 white Halfling creature token and attach ~ to it." (Living
#: Weapon-adjacent, but printed as ordinary oracle text rather than the
#: keyword — Auxiliary Boosters) / "…**then** attach **this** to it." (the
#: "For Mirrodin!" ability word's own reminder-text wording, MEC-28 — see
#: `gate.py`'s ``_FOR_MIRRODIN_RE`` for why this specific card's real rules
#: text lives in reminder text at all) — one clause, two effects: the
#: token, then `AttachEffect`'s ``target_kind="created"`` mode onto
#: whatever that just made (RULE 608.2's "it").
_CREATE_TOKEN_AND_ATTACH_RE = _c(
    rf"creates? {_CREATE_TOKEN_INLINE}(?:,)? (?:and|then) attach (?:~|this) to it"
)


def _create_token_and_attach(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    return [EffectSpec("create_token", params), EffectSpec("attach", {"target_kind": "created"})]


#: "Create <Name>, a legendary N/N ... creature token [with <keywords>]."
#: (PAR-13, Dungeon of the Mad Mage's "Cradle of the Death God" — "Create
#: The Atropal, a legendary 4/4 black God Horror creature token with
#: deathtouch.") — the named-legendary sibling of `_create_token`'s bare
#: inline-stats grammar: a real proper name up front (unlike `_create_
#: named_token`'s closed Treasure/Clue/Food vocabulary, this name is
#: whatever the clause prints, always legendary, always with inline stats)
#: rather than a curated `TokenDatabase` lookup, since a card's own unique
#: token needs no shared ability the database would otherwise supply.
_CREATE_NAMED_LEGENDARY_TOKEN_RE = _c(
    r"create (?P<name>[a-z][a-z' ]*), a legendary (?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z, ]+))?"
)


def _create_named_legendary_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors, subtypes, is_artifact = _split_token_mid_words(m.group("mid") or "")
    keywords: list[str] = []
    if m.groupdict().get("kw"):
        parsed = _token_keywords(m.group("kw"))
        if parsed is None:
            return None
        keywords = parsed
    return [EffectSpec("create_token", {
        "count": 1, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "colors": colors, "subtypes": subtypes, "keywords": keywords,
        **({"is_artifact": True} if is_artifact else {}),
        "token_name": m.group("name").strip().title(), "legendary": True,
    })]


#: A closed vocabulary of the popular colourless "named" artifact tokens
#: (no inline P/T, no "creature" word — Treasure/Clue/Food-shaped) that
#: `services/token_database.py`'s `data/tokens.json` actually defines with
#: their own real abilities (a Treasure's mana ability, a Clue's sacrifice-
#: to-draw, a Food's sacrifice-to-gain-life, a Blood's discard-and-draw).
#: Deliberately **not** every name real cards print (Map/Gold/Incubator/
#: Powerstone aren't in that JSON yet) — claiming one of those here would silently synthesize a
#: blank token missing its real ability (`CreateTokenEffect.apply`'s
#: fallback), the exact half-resolved outcome docs/09's fail-closed
#: discipline forbids. Keep this dict in sync with `data/tokens.json`
#: whenever a new named token is added there.
_NAMED_TOKEN_WORDS: dict[str, str] = {
    "treasure": "Treasure", "clue": "Clue", "food": "Food", "blood": "Blood", "mutagen": "Mutagen",
}


#: "create a Treasure token" / "create two Clue tokens" — the named-token
#: sibling of `_create_token`'s inline-stats creature grammar: no P/T, no
#: "creature" word, just a bare recognised token name. Looked up in the
#: curated `TokenDatabase` at resolve time (`CreateTokenEffect.apply`), so
#: the created object keeps its real activated ability, not a blank card.
#: The subject prefix on a named-token create — "you"/nothing, or a targeted/
#: mass player ("target player creates a Treasure token." — Prismari Command;
#: "each opponent creates a Clue token." — Tamiyo's Safekeeping-adjacent).
_NAMED_TOKEN_CREATOR: dict[str, str] = {
    "": "you", "you ": "you",
    "each opponent ": "each_opponent", "each player ": "each_player",
    "target player ": "target", "target opponent ": "target",
}


def _create_named_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    name = _NAMED_TOKEN_WORDS[m.group("name")]
    params: dict = {"count": count_of(m.group("n")), "token_name": name}
    if m.groupdict().get("tapped"):  # "create a tapped Treasure token" (Village Pillagers)
        params["tapped"] = True
    who = (m.groupdict().get("who") or "").lower()
    creator = _NAMED_TOKEN_CREATOR.get(who)
    if creator is None:
        return None
    if creator != "you":
        params["creators"] = creator
    if creator == "target":
        params["target_kind"] = "opponent" if who == "target opponent " else "player"
    return [EffectSpec("create_token", params)]


#: PAR-104: "whenever a creature you control with a +1/+1 counter on it leaves the battlefield, create a Mutagen
#: token for each +1/+1 counter on it." (The Ooze) — under a group trigger "it" is the firing creature, and the
#: `counters` amount reads its counters live, or from the leave event's RULE 603.10a snapshot once it is gone.
_CREATE_NAMED_TOKEN_PER_COUNTER_ON_IT_RE = _c(
    rf"create an? (?P<name>{'|'.join(_NAMED_TOKEN_WORDS)}) token for each (?P<kind>\+1/\+1|-1/-1|[a-z]+) counter on it"
)


def _create_named_token_per_counter_on_it(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_token", {
        "token_name": _NAMED_TOKEN_WORDS[m.group("name")],
        "count": {"kind": "counters", "of": "trigger_subject", "counter": m.group("kind")},
    })]


#: "Whenever this creature deals combat damage to a player or planeswalker,
#: create that many Treasure tokens." (The Reaver Cleaver) — RULE 603.1's
#: event amount, using the same runtime counter as the creature-token sibling
#: below but for a named noncreature token.
_CREATE_NAMED_TOKEN_THAT_MANY_RE = _c(
    rf"creates? that many (?P<name>{'|'.join(_NAMED_TOKEN_WORDS)}) tokens?"
)


def _create_named_token_that_many(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_token", {
        "token_name": _NAMED_TOKEN_WORDS[m.group("name")],
        "count_from_trigger_event": "amount",
    })]


#: "When ~ dies, create a number of tapped Treasure tokens equal to its
#: power." (Goldvein Hydra) — the named-token count-from-power sibling;
#: `CreateTokenEffect.count_from_subject` reads the DIES event's RULE 400.7
#: power/toughness snapshot (`_characteristic_of_subject`). `self_subject_
#: only` — "its" is the trigger's own subject.
_CREATE_NAMED_TOKEN_EQ_ITS_RE = _c(
    rf"creates? a number of (?P<tapped>tapped )?(?P<name>{'|'.join(_NAMED_TOKEN_WORDS)}) tokens? "
    r"equal to its (?P<char>power|toughness)"
)


def _create_named_token_eq_its_self(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "token_name": _NAMED_TOKEN_WORDS[m.group("name")],
        "count_from_subject": f"trigger_subject_{m.group('char')}",
    }
    if m.groupdict().get("tapped"):
        params["tapped"] = True
    return [EffectSpec("create_token", params)]


#: The compound sibling of `_create_token_and_attach` — "create a Food
#: token, then create a 1/1 white Halfling creature token and attach ~ to
#: it." (Field-Tested Frying Pan): a named artifact token
#: (`_NAMED_TOKEN_WORDS`) first, *then* the create+attach shape onto the
#: second, inline-stats token — `AttachEffect`'s ``created_objects[-1]``
#: read picks the Halfling, not the Food, since it's whichever effect ran
#: last. Deliberately hard-codes the singular "a `<named>` token" (rather
#: than reusing `COUNT`) — the real card this closes only ever prints one,
#: and `COUNT`'s own capture group is named ``n``, the same name
#: `_CREATE_TOKEN_INLINE` already binds for the *second* token's count, so a
#: shared `COUNT` here would collide.
_CREATE_NAMED_THEN_CREATE_TOKEN_AND_ATTACH_RE = _c(
    rf"creates? an? (?P<named>{'|'.join(_NAMED_TOKEN_WORDS)}) token, then "
    rf"creates? {_CREATE_TOKEN_INLINE} and attach ~ to it"
)


def _create_named_then_create_token_and_attach(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    named_name = _NAMED_TOKEN_WORDS[m.group("named")]
    return [
        EffectSpec("create_token", {"count": 1, "token_name": named_name}),
        EffectSpec("create_token", params),
        EffectSpec("attach", {"target_kind": "created"}),
    ]


#: RULE 701.19a's keyword action — "Investigate" (Shadows over Innistrad-
#: introduced, but reused across many later sets — the widest single
#: template found in this batch's ranking, 87 SOLO cache-wide). Purely "the
#: player creates a Clue token" (`"Clue"` is already in `_NAMED_TOKEN_WORDS`,
#: so the *token* itself needed no new work — only this keyword-action
#: recognition), so it's modeled as a direct alias onto the same
#: `create_token` shape `_create_named_token` already emits rather than a
#: dedicated `investigate` effect type. "Investigate twice" is `normalize`'s
#: one gap in its own spelled-number folding (it rewrites "three times" to
#: "3 times" but "twice" isn't a `_NUMBER_WORDS` entry — it's a distinct
#: word, not "two times") — handled here as its own literal alternative
#: rather than widening `normalize` for a single irregular word no other
#: family needs. "Investigate X times" (Disorder in the Court) is the announced-X
#: ``"x"`` count sentinel; "...for each `<count>`" (a dynamic count) stays
#: unclaimed — `COUNT` only ever resolves a literal int.
_INVESTIGATE_RE = _c(r"investigate(?: (?P<times>twice|x times|\d+ times?))?")


def _investigate(m: re.Match[str]) -> list[EffectSpec]:
    times = m.group("times")
    if times == "x times":
        return [EffectSpec("create_token", {"count": "x", "token_name": "Clue"})]
    count = 2 if times == "twice" else (int(times.split()[0]) if times else 1)
    return [EffectSpec("create_token", {"count": count, "token_name": "Clue"})]


#: RULE 701.51a's keyword action — "The Ring tempts you." (Tales of
#: Middle-earth-shaped, "Lord of the Rings" set-specific — see
#: PARSER_LONG_TAIL.md's set-specific-mechanics table). The engine
#: primitive and the `"the_ring_tempts_you"` `EffectSpec` type already
#: existed (`RulesEngine.the_ring_tempts_you`, `effects.
#: TheRingTemptsYouEffect`, both built for one hand-authored card,
#: `game/card_catalogue`'s "One Ring to Rule Them All") — only this
#: general oracle-text recognition was missing, the single widest gap this
#: set's own precon deck has (36 SOLO cache-wide).
_RING_TEMPTS_YOU_RE = _c(r"the ring tempts you")


def _ring_tempts_you(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("the_ring_tempts_you", {})]


def _signed_int(token: str) -> int:
    """A signed integer literal, tolerating the unicode minus ``−`` (U+2212)."""
    return int(token.replace("−", "-"))


def _counter_sign(token: str) -> str:
    """"+1/+1" (default) or "-1/-1" from a captured counter-kind sign, tolerating
    the unicode minus ``−`` (U+2212) — both shift net P/T through the same
    machinery (RULE 122)."""
    return "-1/-1" if token.lstrip()[0] in "-−" else "+1/+1"


#: A "±N/±M" P/T counter token (RULE 122.1a). The engine keeps P/T counters as plain kind
#: strings: "+1/+1" and "-1/-1" are the net `GameObject.plus_one_counters` pair, and any other
#: "+a/+b" is an ordinary counter kind that layer 7c adds its own delta for
#: (`continuous._apply_pt_counters`) — so "+0/+1" (Coral Reef, Shield Sphere) is exactly that,
#: not a +1/+1 counter that would have handed the creature power it never had.
_PT_COUNTER_TOKEN = r"[+\-−]\d+/[+\-−]\d+"


def _counter_kind_and_multiplier(token: str) -> tuple[str, int]:
    """A "±N/±M" counter token → ``(kind, count multiplier)``. **Documented simplification:**
    a symmetric "+2/+2 counter" (Baron Sengir, RULE 122.1c — one counter worth +2/+2) is
    modeled as *two* +1/+1 counters — identical for net P/T, differing only for a later
    "remove a +1/+1 counter" / "has a +1/+1 counter" reading. An asymmetric one is its own
    counter kind, spelled with an ASCII sign ("+0/+1"), one counter each."""
    sign = _counter_sign(token)
    m = re.match(r"\s*[+\-−](\d+)/[+\-−](\d+)", token)
    if m and m.group(1) == m.group(2):
        return sign, max(1, int(m.group(1)))
    return token.strip().replace("−", "-"), 1


def _add_counters_target_params(
    m: re.Match[str], params: dict, include_optional: bool = True
) -> Optional[list[EffectSpec]]:
    """The shared selfref-or-target tail every ``add_counters`` builder below
    shares: "on ~" buffs the source untargeted; otherwise the target phrase
    must resolve to a permanent-ish kind (RULE 122.1a — +1/+1 counters can sit
    on *any* permanent, incl. the controller-restricted "target creature you
    control" pick, Archdruid's Charm-shaped) or the clause is unclaimed.
    ``include_optional`` is ``False`` for the one caller
    (`_add_counters_from_trigger_amount`) whose regex has no "up to" group to
    read."""
    if m.groupdict().get("selfref"):
        if _GROUP_CLAUSE.get() and m.group("selfref").lower() == "it":
            # Under a group trigger a bare "it" is the firing object, not the ability's source
            # (PAR-123) — the group readings own it; the source is only ever named ("~").
            return None
        return [EffectSpec("add_counters", params)]
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, (
        "creature", "permanent", "creature_you_control", "other_creature_you_control",
        *_SINGLE_TYPE_PERMANENT_KINDS,
    )):
        return None
    params["target_kind"] = kind
    if include_optional:
        params.update(_optional_param(m))
    # See `_destroy`'s own comment: "put a counter on target attacking
    # creature" (Sparring Regimen's Lesson-shaped) needs it too.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("add_counters", params)]


#: PAR-71: "put X +1/+1 counters on target creature [you control], where X is
#: that spell's mana value." (Dancing from Dark to Dawn's cast trigger) — the
#: ``mana_value`` sibling of `_add_counters_from_trigger_amount`'s ``"amount"``
#: field. Deliberately **target-only**, no self ("~") alternative: Draining
#: Whelk prints the identical "put X +1/+1 counters on ~, where X is that
#: spell's mana value" tail after "counter target spell" rather than a cast
#: trigger, where "that spell" is the *countered* target
#: (`GameContext.previous_targets`), not a `SPELL_CAST` event — reading
#: `context.trigger_event` there would silently measure 0 (see
#: `_lose_life_spell_mv_that_player`'s docstring for the same trap); it's
#: handled by its own dedicated two-clause row instead.
_ADD_COUNTERS_SPELL_MV_RE = _c(
    rf"put x \+1/\+1 counters? on {TARGET}, where x is that spell'?s mana value"
)


def _add_counters_spell_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent", "creature_you_control", *_SINGLE_TYPE_PERMANENT_KINDS)):
        return None
    return [EffectSpec("add_counters", {
        "kind": "+1/+1", "target_kind": kind, "amount_from_trigger_event": "mana_value",
    })]


def _add_counters(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind, mag = _counter_kind_and_multiplier(m.group("ckind"))
    count = count_or_x_of(m.group("n"))
    if count == "x":
        if mag != 1:
            return None  # "X +2/+2 counters" — no printed card; don't guess the product
        params: dict = {"count": "x", "kind": kind}
    else:
        params = {"count": count * mag, "kind": kind}
    return _add_counters_target_params(m, params)


_TRANSFER_EVENT_COUNTERS_RE = _c(
    r"put (?:those|its) counters on (?P<optional>up to 1 )?target creature(?P<you> you control)?"
)


def _transfer_event_counters(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("transfer_event_counters", {
        "target_kind": "creature_you_control" if m.group("you") else "creature",
        "optional": bool(m.group("optional")),
    })]


#: PAR-117: "whenever a `<type>` [you control] deals damage, put a `<kind>`
#: counter on **it**." (Rakish Heir/Stensia Masquerade) — "it" is RULE
#: 603.1's group-subject firing object, not this ability's own source, so it
#: needs its own row rather than falling into `_add_counters`'s shared
#: `_SELF_SUBJECT` alternation: that macro folds "it" in with "~"/"this
#: creature"/a card's own name as one undifferentiated self-reference, which
#: is correct for every other caller (a self-damage "Enrage"-shaped trigger's
#: bare "it" really does mean the ability's own source) but wrong here — a
#: card naming *itself* under a group condition ("…dies, put a +1/+1 counter
#: on Malakir Cullblade.") must still buff its own source, not the object
#: that triggered it, so that reading has to stay reachable too. Splitting
#: this into its own `group_subject_only`-gated row, tried *before* the
#: generic one below, keeps both readings: an explicit "~"/name still falls
#: through unclaimed here to the generic row's self-buff, while a bare "it"
#: is claimed here first. The ``"__group_subject__"`` sentinel is resolved
#: to the real event field by `effect_binder._retarget_implicit_subject_
#: effects` (the same pass `TapEffect`'s "untap it" retarget uses) — this
#: handler can't know the field name itself (``instance_id`` vs. `DAMAGE`'s
#: own ``source_id``), only that the clause is a group-subject "it".
_ADD_COUNTERS_GROUP_SUBJECT_IT_RE = _c(
    rf"put {COUNT} (?P<ckind>{_PT_COUNTER_TOKEN}) counters? on it"
)


def _add_counters_group_subject_it(m: re.Match[str]) -> list[EffectSpec]:
    kind, mag = _counter_kind_and_multiplier(m.group("ckind"))
    return [EffectSpec("add_counters", {
        "count": count_of(m.group("n")) * mag, "kind": kind,
        "trigger_subject_key": GROUP_SUBJECT_KEY_SENTINEL,
    })]


#: "Put a -1/-1 counter on target creature, two -1/-1 counters on another
#: target creature, and three -1/-1 counters on a third target creature."
#: (Incremental Blight; the +1/+1 sibling is Incremental Growth) — three
#: escalating RULE 115 targets in one clause, each getting a different
#: number of counters, so it can't be one ``add_counters`` with a target
#: ``count``. Emitted as three ``add_counters`` `EffectSpec`s (the spell-
#: resolution loop partitions its targets per effect); the 2nd/3rd carry
#: ``distinct_from_others`` for RULE 109.5's "another"/"a third".
_INCREMENTAL_COUNTERS_RE = _c(
    r"put a (?P<k1>[+\-−]1/[+\-−]1) counter on target creature, "
    r"(?P<n2>\d+) (?P<k2>[+\-−]1/[+\-−]1) counters on another target creature, "
    r"and (?P<n3>\d+) (?P<k3>[+\-−]1/[+\-−]1) counters on a third target creature"
)


def _incremental_counters(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kinds = {_counter_sign(m.group("k1")), _counter_sign(m.group("k2")), _counter_sign(m.group("k3"))}
    if len(kinds) != 1:
        return None  # all three clauses use the same counter kind on every real card
    kind = kinds.pop()
    n2, n3 = int(m.group("n2")), int(m.group("n3"))
    return [
        EffectSpec("add_counters", {"count": 1, "kind": kind, "target_kind": "creature"}),
        EffectSpec("add_counters", {
            "count": n2, "kind": kind, "target_kind": "creature", "distinct_from_others": True,
        }),
        EffectSpec("add_counters", {
            "count": n3, "kind": kind, "target_kind": "creature", "distinct_from_others": True,
        }),
    ]


# MEC-46 (Galadriel, Elven-Queen) — "[you ]put a +1/+1 counter on your
# Ring-bearer": no RULE 115 target, resolved against `continuous.
# ring_bearer_of` at resolution (`AddCountersEffect.ring_bearer`).
_ADD_COUNTERS_RING_BEARER_RE = _c(
    rf"(?:you )?put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on your ring-bearer"
)


def _add_counters_ring_bearer(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": count_of(m.group("n")),
        "kind": _counter_sign(m.group("ckind")),
        "ring_bearer": True,
    })]


# "put a +1/+1 counter on target suspected creature you control" (RULE
# 701.60, PAR-29 — Deadly Complication) — the one adjective-qualified TARGET
# phrase `subgrammars.TARGET`'s own alternation doesn't carry (unlike
# "target attacking/tapped creature", it isn't worth widening that shared
# macro for a single-card phrase), so its own small row feeding
# `combat.matches_object_filter`'s new ``is_suspected`` key.
def _add_counters_suspected_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": count_of(m.group("n")), "kind": _counter_sign(m.group("ckind")),
        "target_kind": "creature_you_control", "creature_filter": {"is_suspected": True},
    })]


#: MEC-27: "put x +1/+1 counters on ~/target creature, where x is the number
#: of `<noun phrase>` you control." (Domain-shaped triggers, "the number of
#: Elves you control", etc.) — `subgrammars.DEVOTION`'s wider RULE 613.7c
#: reading, previously wired into `damage`/`lose_life` only
#: (`_damage_selector_devotion`/`_lose_life_selector_devotion`); this is
#: that same reading applied to the counter family via `AddCountersEffect`'s
#: new `amount_from_count_selector`. Requires the literal "x" (not `{COUNT}`
#: — a plain digit/"a"/"an" amount has no "where x is" tail to resolve
#: against), so it's a genuinely separate row from `_add_counters` above,
#: not a widening of its ``{COUNT}`` group.
_ADD_COUNTERS_DEVOTION_RE = _c(
    rf"put x (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
    rf"(?:{TARGET}|(?P<selfref>{_SELF_SUBJECT})), where x is {DEVOTION}"
)


def _add_counters_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    params: dict = {"amount_from_count_selector": dsel, "kind": _counter_sign(m.group("ckind"))}
    return _add_counters_target_params(m, params, include_optional=False)


#: RULE 122.1's *named* (non-P/T) counter kinds: the plain "put a `<kind>` counter on X"
#: shape and every row that shares its kind vocabulary. `AddCountersEffect.kind` is a free
#: string (RULE 122.1a — any permanent, any named counter type), so a pure card-text tracker
#: ("spore", "feather", "bloodstain") needs no engine change and **the kind is an open axis**
#: (PAR-135) — a closed list of the tracker words printed so far kept missing the next set's.
#:
#: What is *not* open is the small set whose name the engine itself keys off, where a generic
#: `obj.counters[kind]` bump would half-model: the subsystem counters (`time` vanishing/
#: suspend, `age` cumulative upkeep, `fade` fading, `level` leveler, `loyalty` planeswalker,
#: `lore` Saga, `defense` battle), the player counters (`rad`, `energy`, `experience`,
#: `poison`) and the RULE 122.1b keyword counters no layer reader exists for (`decayed`,
#: `exalted`). `stun` (RULE 122.1c, `set_tapped`) and `shield` (RULE 122.1c,
#: `deal_damage`/`destroy`) carry replacement effects, and both are engine-enforced now, so
#: they are ordinary members. A test (`test_par135_named_counters.py`) scans `game/` for
#: counter-kind literals so a *new* reader can't slip in unreserved.
_RESERVED_COUNTER_KINDS: tuple[str, ...] = (
    "time", "age", "fade", "level", "loyalty", "lore", "defense",
    "rad", "energy", "experience", "poison", "decayed", "exalted", "finality", "ticket",
)
#: Multi-word RULE 122.1b keyword kinds first, so "first strike" isn't read as kind "first".
_NAMED_COUNTER_KIND = (
    rf"(?!(?:{'|'.join(_RESERVED_COUNTER_KINDS)})\b)"
    rf"(?:{'|'.join(sorted(KEYWORD_COUNTER_KINDS, key=len, reverse=True))}|[a-z]+)"
)
#: `COUNT_X` (not the plain `COUNT`) so an {X}-costed activated ability's
#: own "put X charge counters on ~" (Blast Zone, Ventifact Bottle — PAR-47)
#: is recognized too: the "x" token becomes `EffectSpec`'s literal ``"x"``
#: sentinel via `count_or_x_of`, which `AddCountersEffect.amount` carries
#: unresolved until `RulesEngine._substitute_x` rewrites it against the
#: ability's actually-announced {X} at resolve time — the exact mechanism
#: `_pump_x` already relies on for "gets +x/+x", not a new one.
_ADD_NAMED_COUNTER_RE = _c(
    rf"put {COUNT_X} (?P<ckind>{_NAMED_COUNTER_KIND}) counters? on "
    rf"(?:{TARGET}|(?P<selfref>{_SELF_SUBJECT}))"
)


#: "put an impostor counter on each creature you control" (Illicit
#: Masquerade) / "put a hone counter on each Equipment you control" (Dwalin) —
#: a named counter on a mass group (`AddCountersEffect.group`, the group read
#: through the shared `parse_count_phrase` grammar).
_ADD_NAMED_COUNTER_GROUP_RE = _c(
    rf"put {COUNT_X} (?P<ckind>{_NAMED_COUNTER_KIND}) counters? on each (?P<other>other )?(?P<group>[a-z' -]+?)"
)

#: Batch 5: the +1/+1 / -1/-1 sibling over the same group grammar — "put a +1/+1 counter on each creature you
#: control with a +1/+1 counter on it" (Dueling Coach, Oran-Rief, Edgar), "…on each other Dragon you control"
#: (Acid-Spewer Dragon, Belltoll Dragon), "…on each Ooze you control" (Biogenic Ooze). Registered *after* the
#: closed `add_counters_selector` row, which keeps the named selectors it always read.
_ADD_PT_COUNTER_GROUP_RE = _c(
    rf"put {COUNT_X} (?P<ckind>[+\-−]1/[+\-−]1) counters? on each (?P<other>other )?(?P<group>[a-z0-9' +/\-−]+?)"
)


def _add_counter_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .count_phrase import parse_count_phrase

    phrase = m.group("group")
    group = parse_count_phrase(phrase)
    if group is None or group.get("zone") != "battlefield" or "target" in phrase:
        return None
    ckind = m.group("ckind")
    kind = _counter_sign(ckind) if ckind[0] in "+-−" else ckind
    params: dict = {"count": count_or_x_of(m.group("n")), "kind": kind, "group": group}
    if m.group("other"):
        params["group_other"] = True
    return [EffectSpec("add_counters", params)]


def _add_named_counter_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _add_counter_group(m)


def _add_named_counter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"count": count_or_x_of(m.group("n")), "kind": m.group("ckind")}
    return _add_counters_target_params(m, params)


#: MEC-108: "put a +1/+1 counter and a lifelink counter on target creature" /
#: "put a flying counter, a first strike counter, and a lifelink counter on ~" —
#: a fixed list of two or more counter kinds onto one recipient. One
#: `add_counters` per kind: the first carries the recipient (target or self),
#: the rest re-read it (`previous_subject`, the RULE 608.2 referent the first
#: one's target seeds) so a single RULE 115 target serves the whole list.
_COUNTER_LIST_KIND = rf"{_PT_COUNTER_TOKEN}|{_NAMED_COUNTER_KIND}"
_COUNTER_LIST_ITEM = rf"(?:a|an|\d+) (?:{_COUNTER_LIST_KIND}) counters?"
_COUNTER_LIST_PART_RE = re.compile(rf"(?P<n>a|an|\d+) (?P<ckind>{_COUNTER_LIST_KIND}) counters?")
_ADD_COUNTER_LIST_RE = _c(
    rf"put (?P<items>{_COUNTER_LIST_ITEM}(?:, {_COUNTER_LIST_ITEM})*,? and {_COUNTER_LIST_ITEM}) on "
    rf"(?:{TARGET}|(?P<selfref>{_SELF_SUBJECT}))"
)


def _add_counter_list(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    parts = list(_COUNTER_LIST_PART_RE.finditer(m.group("items")))
    if len(parts) < 2:
        return None
    specs: list[EffectSpec] = []
    for index, part in enumerate(parts):
        token = part.group("ckind")
        kind, mag = _counter_kind_and_multiplier(token) if token[0] in "+-−" else (token, 1)
        params: dict = {"count": count_or_x_of(part.group("n")) * mag, "kind": kind}
        if index == 0:
            built = _add_counters_target_params(m, params)
            if built is None:
                return None
            specs.extend(built)
        else:
            if specs[0].params.get("target_kind"):
                params["previous_subject"] = True
            specs.append(EffectSpec("add_counters", params))
    return specs


#: PAR-140: "put a menace counter on **a creature you control**" / "…on another artifact you control" — a
#: counter on one permanent the controller picks at resolution, no "target" (RULE 122.1, not 115).
#: `AddCountersEffect.choose_one` over the structured group selector the shared count-phrase grammar
#: already reads; "another" is that grammar's "other" (excludes the source).
_ADD_COUNTER_PICK_RE = _c(
    rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1|{_NAMED_COUNTER_KIND}) counters? on "
    r"(?:an? |(?P<other>another|other) )(?P<group>[a-z' -]+? you control)"
)


def _add_counter_pick(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .count_phrase import parse_count_phrase

    group = parse_count_phrase(("other " if m.group("other") else "") + m.group("group"))
    if group is None or group.get("zone") != "battlefield" or group.get("of") != "you":
        return None
    token = m.group("ckind")
    kind, mag = _counter_kind_and_multiplier(token) if token[0] in "+-−" else (token, 1)
    return [EffectSpec("add_counters", {
        "count": count_or_x_of(m.group("n")) * mag, "kind": kind, "group": group, "choose_one": True,
    })]


#: MEC-108: "put your choice of a +1/+1, first strike, or trample counter on
#: that creature" (Assaultron Dominator) / "…your choice of a menace, trample,
#: reach, or haste counter on ~" / "…a +1/+1 counter or 2 charge counters on
#: up to 1 other target artifact" (Inspirit) — one `add_counters` whose
#: ``kind_options`` the controller picks from at resolution.
_ADD_COUNTER_CHOICE_RE = _c(
    r"put your choice of " + counter_choice_list(_NAMED_COUNTER_KIND)
    + rf" on (?:{TARGET}|(?P<selfref>{_SELF_SUBJECT}))"
)


def _add_counter_choice(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    options = parse_counter_choice_items(m.group("items"))
    if options is None:
        return None
    return _add_counters_target_params(m, {"kind_options": options})


#: MEC-108: "remove a menace counter from ~" / "remove 2 charge counters from
#: this creature" — the effect-side sibling of the `remove N <kind> counters`
#: *cost* (`cost_text._REMOVE_COUNTERS_RE`); untargeted, the source's own
#: counters, exactly ``count`` of one kind (none on it: nothing happens).
_REMOVE_NAMED_COUNTER_SELF_RE = _c(
    rf"remove {COUNT} (?P<ckind>{_NAMED_COUNTER_KIND}|[+\-−]1/[+\-−]1) "
    rf"counters? from (?P<selfref>{_SELF_SUBJECT})"
)


def _remove_named_counter_self(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if _GROUP_CLAUSE.get() and m.group("selfref").lower() == "it":
        return None  # under a group trigger a bare "it" is the firing object, not the source
    ckind = m.group("ckind")
    kind = "+1/+1" if ckind[0] == "+" else ("-1/-1" if ckind[0] in "-−" else ckind)
    return [EffectSpec("remove_counters", {
        "self_only": True, "kind": kind, "count": count_or_x_of(m.group("n")),
    })]


#: RULE 603.1's "Whenever you gain life, …" lifegain-payoff family (RULE
#: 119.3, Ajani's Pridemate-shaped — `_PLAYER_TRIGGER_CONDITIONS`'s
#: ``"you gain life"`` row already claims the *condition*; this is the
#: matching *body* grammar for the two forms real cards actually print:
#: "target opponent loses that much life" (Sanguine Bond/Defiant Bloodlord)
#: and "put that many +1/+1 counters on ~/target creature" (Ageless
#: Entity/Karlov-adjacent). ``amount_from_trigger_event`` reads the firing
#: LIFE_GAINED event's own ``amount`` (`GameContext.trigger_event`,
#: `LoseLifeEffect`/`AddCountersEffect`'s new param) rather than a literal
#: int — the same "that much"/"that many" idiom `AddManaEffect.
#: amount_from_trigger_event` already models for Raphael, Ninja Destroyer's
#: "add that much {R}". Not wired into every trigger family generally
#: (only this one prints "that much"/"that many" this way), so it's a
#: narrow pair of rows rather than a generic COUNT alternative.
def _lose_life_from_trigger_amount(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind != "player":
        return None
    return [EffectSpec("lose_life", {"target_kind": "player", "amount_from_trigger_event": "amount"})]


#: "Whenever ~ deals damage, **you gain that much life**." (El-Hajjâj /
#: Exalted Angel / Horned Cheetah / Whip of Erebos-shaped — the pre-lifelink
#: template, PAR-36). The `_DAMAGE_TRIGGER_RE` condition already parses; only
#: this body was blocked. "That much" is the firing DAMAGE event's own
#: ``amount`` (`GainLifeEffect.amount_from_trigger_event`, the gain sibling
#: of `_lose_life_from_trigger_amount` just above). Untargeted — "you" is
#: the ability's controller, no RULE 115 target.
def _gain_life_from_trigger_amount(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount_from_trigger_event": "amount"})]


#: PAR-71: "[you may] gain life equal to that spell's mana value." (Bounteous
#: Kirin's spirit-or-arcane cast trigger) — the ``mana_value`` sibling of
#: `_gain_life_from_trigger_amount`'s ``"amount"`` field, same firing
#: `SPELL_CAST` event `_damage_spell_mv`/`_pump_mana_value` already read.
#: Untargeted (gaining life is never a RULE 115 target); the segmenter peels
#: a triggered ability's own leading "you may" before this ever runs.
def _gain_life_spell_mv(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount_from_trigger_event": "mana_value"})]


#: The lose-life sibling — "that player loses life equal to that spell's
#: mana value." (The Frightful Four) — "that player" is whoever the firing
#: SPELL_CAST event names as the caster, `LoseLifeEffect.
#: selector="event_player"`, the same "that player" idiom `MillEffect.
#: selector="event_controller"` already uses for an analogous event-named
#: subject. Deliberately no bare self-referential "you lose life equal to
#: that spell's mana value" sibling: the only real card on that exact
#: wording is Imp's Mischief ("Change the target of target spell with a
#: single target. You lose life equal to that spell's mana value.") —
#: there "that spell" is the *targeted* spell (`GameContext.
#: previous_targets`), not a `SPELL_CAST` trigger event (this ability has
#: no cast trigger at all — `context.trigger_event` is `None` here, so an
#: `amount_from_trigger_event` read would silently resolve to 0 life lost,
#: exactly the "half-modeled" failure mode the coverage gate exists to
#: prevent). Left unclaimed rather than guessed.
def _lose_life_spell_mv_that_player(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {
        "selector": "event_player", "amount_from_trigger_event": "mana_value",
    })]


def _add_counters_from_trigger_amount(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"kind": _counter_sign(m.group("ckind")), "amount_from_trigger_event": "amount"}
    return _add_counters_target_params(m, params, include_optional=False)


#: "~ gets +X/+X until end of turn, where X is the amount of life you
#: gained." (Field-Tested Frying Pan's granted Equipment ability) — the
#: dynamic-magnitude sibling of `_pump`'s literal-int "+N/+N until end of
#: turn"; only ever seen self-referential (a granted quoted ability's own
#: "~" resolves to whatever object received the grant — the equipped
#: creature — at bind time, see `continuous._apply_layer_6_ability`'s
#: ``source=obj``), so no target form is needed.
_PUMP_SELF_FROM_LIFE_GAINED_RE = _c(
    rf"{_SELF_SUBJECT} gets \+x/\+x until end of turn, "
    r"where x is the amount of life you gained"
)


def _pump_self_from_life_gained(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {"amount_from_trigger_event": "amount"})]


#: ENG-32 (Flexible Waterbender / Katara, Water Tribe's Hope) — "~ / creatures
#: you control ha[s|ve] base power and toughness N/M until end of turn"
#: (a resolve-time layer-7b `pt_set`, parked in `GameState.floating_statics`
#: via `grant_until` so it ends at cleanup like any RULE 611 duration).
#: Literal digits or the `{X}` form (Katara — "X can't be 0", a documented
#: simplification: X is announced, and 0 is already meaningless for it).
_BASE_PT_UNTIL_EOT_RE = _c(
    rf"(?:{_SELF_SUBJECT}|(?P<group>creatures you control)"
    # "target creature [you control] has base power and toughness N/N until
    # end of turn" (Quandrix Charm / Turn to Frog / Snakeform / Creeperhulk
    # / Ovinize — 59 SOLO). `grant_until` already resolves a RULE 115 target
    # and scopes the parked `pt_set` to those ids.
    rf"|(?P<tgt>target creature(?: you control)?)) "
    rf"(?:has|have) base power and toughness (?P<p>\d+|x)/(?P<t>\d+|x) until end of turn"
    rf"(?:\. x can'?t be 0)?(?:\. activate only during your turn)?"
)


def _base_pt_until_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    def _v(g: str) -> "int | str":
        return "x" if g.lower() == "x" else int(g)

    tgt = (m.groupdict().get("tgt") or "").strip()
    params: dict = {
        "power": _v(m.group("p")), "toughness": _v(m.group("t")),
        "affects": "creatures_you_control" if m.groupdict().get("group") else "self",
    }
    target_kind = None
    if tgt:
        target_kind = "creature_you_control" if "you control" in tgt else "creature"
    return [EffectSpec("grant_until", {
        "static": {"type": "pt_set", "params": params},
        "duration": "end_of_turn",
        "target_kind": target_kind,
    })]


#: PAR-49 / RULE 205.3d + 613.4a: Mistform Dreamer's ``{1}: ~ becomes
#: the creature type of your choice until end of turn.`` This *replaces*
#: the source's existing creature subtypes, unlike "in addition" forms.
_CHOOSE_CREATURE_TYPE_UNTIL_EOT_RE = _c(
    rf"{_SELF_SUBJECT} becomes the creature type of your choice until end of turn"
)


def _choose_creature_type_until_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("_request_choose_creature_type_grant", {
        "then_specs": [{
            "type": "grant_until",
            "params": {
                "static": {"type": "type_change", "params": {
                    "set_subtypes_from_source": True,
                }},
                "duration": "end_of_turn",
                "target_kind": None,
                "self_subject": True,
            },
        }],
    })]


#: "put a +1/+1 counter on each of up to two target creatures" (RULE 115.1a
#: generalized to N>=2 — the Support-keyword-shaped family; a live query
#: against the cached Oracle DB found 100+ real cards spelling this out,
#: e.g. Ajani, Adversary of Tyrants/Arcade Cabinet/Basri's Aegis/Bretagard
#: Stronghold). Two numbers in one clause (counter amount vs. target count,
#: the same shape `_damage_each_multi_target` already handles for damage) —
#: ``target_count`` is a deliberately distinct `EffectSpec` key from
#: ``count``/``amount`` (both already mean the *counter* amount here).
def _add_counters_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    mt = _multi_target_params(m)
    if mt is None or not target_kind_allowed(
        mt["target_kind"], ("creature", "permanent", *_SINGLE_TYPE_PERMANENT_KINDS),
    ):
        return None
    params: dict = {
        "count": count_of(m.group("n")),
        "kind": _counter_sign(m.group("ckind")),
        "target_kind": mt["target_kind"],
        "target_count": mt["count"],
    }
    if mt.get("count_selector"):
        # "put a +1/+1 counter on each of X target creatures": the announced X, not a fixed count.
        params.pop("target_count")
        params["target_count_selector"] = mt["count_selector"]
    if mt.get("optional"):
        params["optional"] = True
    if mt.get("count_max") is not None:
        # ENG-30: "put a +1/+1 counter on each of 1 or 2 target creatures" —
        # `target_count`/`target_count_max` is the *target* range, distinct
        # from `count`/`amount` (both already the counter amount per card).
        params["target_count_max"] = mt["count_max"]
    return [EffectSpec("add_counters", params)]


#: PAR-15's "distribute N +1/+1 counters among any number of target
#: creatures[ you control]" (Blessings of Nature/Jugan, the Rising Star/
#: Verdurous Gearhulk) — the *divided pool* sibling of `_add_counters_
#: multi_target`'s "each of up to N" full-amount-per-target shape, mirroring
#: `_divided_damage`'s relationship to `_damage_each_multi_target`
#: (`AddCountersEffect.divided`).
_DISTRIBUTE_COUNTERS_RE = _c(
    r"distribute (?P<n>\d+) (?P<ckind>\+1/\+1|-1/-1|−1/−1) counters among any number "
    r"of target creatures(?P<yc> you control)?"
)


def _distribute_counters(m: re.Match[str]) -> list[EffectSpec]:
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("add_counters", {
        "count": int(m.group("n")), "kind": _counter_sign(m.group("ckind")), "target_kind": kind,
        "target_count": _ANY_NUMBER_TARGET_CAP, "optional": True, "divided": True,
    })]


#: ENG-30: "distribute N +1/+1 counters among 1 or 2 target creatures[ you
#: control]" (Armament Corps/Contagion/Elven Rite/Splendid Agony-shaped) —
#: the *fixed range* sibling of `_DISTRIBUTE_COUNTERS_RE`'s "any number of":
#: a genuine RULE 601.2c minimum of one, not 0..cap.
_DISTRIBUTE_COUNTERS_RANGE_RE = _c(
    r"distribute (?P<n>\d+) (?P<ckind>\+1/\+1|-1/-1|−1/−1) counters among "
    r"(?P<range_min>\d+)(?:, \d+,)? or (?P<range_max>\d+) target creatures(?P<yc> you control)?"
)
#: "distribute N +1/+1 counters among **up to M** target creatures[ you control]" (Court of Garenbrig,
#: Storm the Seedcore) — the divided pool over a RULE 601.2c "up to" target count.
_DISTRIBUTE_COUNTERS_UP_TO_RE = _c(
    r"distribute (?P<n>\d+) (?P<ckind>\+1/\+1|-1/-1|−1/−1) counters among "
    r"up to (?P<up_to>\d+) target creatures(?P<yc> you control)?"
)


def _distribute_counters_up_to(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    up_to = int(m.group("up_to"))
    if up_to < 2:
        return None
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("add_counters", {
        "count": int(m.group("n")), "kind": _counter_sign(m.group("ckind")), "target_kind": kind,
        "target_count": up_to, "optional": True, "divided": True,
    })]


def _distribute_counters_range(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
    if range_min < 1 or range_max <= range_min:
        return None
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("add_counters", {
        "count": int(m.group("n")), "kind": _counter_sign(m.group("ckind")), "target_kind": kind,
        "target_count": range_min, "target_count_max": range_max, "divided": True,
    })]


#: "put N +1/+1 counters on each creature you control" (RULE 601.2c mass
#: effect, Vastwood Surge-shaped) — a genuinely different shape from
#: `_add_counters`'s RULE 115 target/self forms, so its own handler row
#: rather than folding "each creature you control" into `TARGET` (that
#: grammar deliberately keeps "each ..." selectors out, see
#: `subgrammars._TARGET_ROWS`'s note).
def _add_counters_selector(m: re.Match[str]) -> list[EffectSpec]:
    selector = {
        "each creature you control": "each_creature_you_control",
        "each other creature you control": "each_other_creature_you_control",
        "each other planeswalker you control": "each_other_planeswalker_you_control",
        "each creature": "each_creature",
        "each other creature": "each_other_creature",
        "each creature your opponents control": "each_creature_opponents_control",
    }[m.group("selector")]
    amount = count_or_x_of(m.group("n"))
    params: dict = {"kind": _counter_sign(m.group("ckind")), "selector": selector}
    if m.groupdict().get("has_counter"):
        params["creature_filter"] = {"has_counter_kind": "+1/+1"}
    if amount == "x":
        # RULE 107.3c: an X in a resolving spell reads that spell's announced X.
        params["x_multiplier"] = 1
    else:
        params["count"] = amount
    return [EffectSpec("add_counters", params)]


#: "…tap up to 2 target creatures. Put a stun counter on **each of them**."
#: (Out Cold, Homesickness, Donatello — PAR-128) — the plural pronoun of
#: `tap_and_stun`'s "on it": every object the preceding clause chose
#: (`AddCountersEffect.previous_group`). Only the counter kinds whose engine
#: reader is known (+1/+1, -1/-1, stun — RULE 122.1c).
_ADD_COUNTERS_PREVIOUS_GROUP_RE = _c(
    r"put (?P<n>an?|\d+) (?P<ckind>\+1/\+1|-1/-1|−1/−1|stun) counters? on "
    r"(?:each of them|each of those creatures|those creatures)(?P<scope> you don't control)?"
)


def _add_counters_previous_group(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "kind": _counter_sign(m.group("ckind")) if m.group("ckind") != "stun" else "stun",
        "count": count_of(m.group("n")), "previous_subject": True, "previous_group": True,
    }
    if m.group("scope"):
        # "tap X target creatures. Put a stun counter on each of those creatures you don't
        # control." (Lost in the Maze) — the earlier clause's targets, narrowed by controller.
        params["previous_group_scope"] = "not_you"
    return [EffectSpec("add_counters", params)]


def _add_counters_previous_selector(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """`_add_counters_previous_group`'s sibling for a preceding *mass selector*
    ("tap all creatures your opponents control, then put a stun counter on each of
    those creatures" — Monstrosity of the Lake)."""
    if m.group("scope"):
        return None  # a mass selector is replayed by name; it can't carry a controller narrowing
    [spec] = _add_counters_previous_group(m)
    params = {k: v for k, v in spec.params.items() if k not in ("previous_subject", "previous_group")}
    return [EffectSpec("add_counters", {**params, "previous_selector": True})]


def _pump_target(m: re.Match[str]) -> Optional[tuple[Optional[str], Optional[str]]]:
    """The pump's ``(target_kind, selector)`` — or ``None`` to signal fail-closed.

    Exactly one of the pair is set for a targeted or group subject; both are
    ``None`` for a self-pump ("~ gets …", untargeted single object) so the
    caller can tell it apart from an unrecognised target (real ``None``
    overall).
    """
    groupdict = m.groupdict()
    if groupdict.get("selfref"):
        return (None, None)  # untargeted self-pump (an activated "~ gets +1/+0 …")
    if groupdict.get("group"):
        selector = _group_selector(re.sub(r"'", "", groupdict["group"]))
        return None if selector is None else (None, selector)
    if groupdict.get("attached"):
        return ("attached_permanent", None)  # "enchanted creature gains …" (Aura activated ability)
    kind = resolve_target_kind(m.group("target"))
    # The controller-scoped creature kinds are as pumpable as a bare
    # "target creature" — `targeting.legal_targets` resolves them all, and a
    # pump doesn't care *whose* creature it lands on (`other_creature_you_
    # control` is RULE 109.5 "another target creature you control", source
    # excluded). Anything else (a player, a spell) has no P/T to modify, so
    # it stays fail-closed.
    if not target_kind_allowed(kind, (
        "creature", "permanent", "creature_you_control", "creature_you_dont_control",
        "other_creature_you_control", "attacking_or_blocking_creature",
    )):
        return None
    return (kind, None)


def _pump_target_creature_filter(m: re.Match[str]) -> Optional[dict]:
    """The RULE 508/509 board-state qualifier (attacking/blocking/tapped/
    untapped) `_pump_target`'s own ``(target_kind, selector)`` pair
    discards — see `subgrammars.resolve_target_creature_state_filter` and
    `_destroy`'s own comment on the same fix. Every `_pump_target(m)` caller
    that threads its ``target_kind`` straight into an `EffectSpec` should
    also merge this into its own ``creature_filter``, or "target tapped
    creature gets -1/-1" (etc.) silently pumps *any* creature. A no-op for
    every match whose ``target`` group didn't come from a qualified phrase
    (``None`` — most callers).
    """
    target_text = m.groupdict().get("target")
    if not target_text:
        return None
    return resolve_target_creature_state_filter(target_text)


#: "Creatures **target player controls** get -2/-2 until end of turn" — the group scoped to the player the spell
#: targets (`PumpEffect.group_player`): written for "you", evaluated for that player.
_TARGET_PLAYER_GROUP_RE = re.compile(r"creatures target (player|opponent) controls")


def _pump(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    scoped = _TARGET_PLAYER_GROUP_RE.fullmatch(m.groupdict().get("group") or "")
    subject = (None, {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}}) if scoped else (
        _pump_target(m))
    if subject is None:
        return None
    target_kind, selector = subject
    params: dict = {
        "power": _signed_int(m.group("p")),
        "toughness": _signed_int(m.group("t")),
    }
    if scoped:
        params["group_player"] = scoped.group(1)
    keywords: list[str] = []
    parametric: list[dict[str, object]] = []
    if m.groupdict().get("kw"):
        # PAR-102: "gains flying and toxic 1" — a grantable parametric keyword rides beside the flags.
        split = _split_keywords_with_parametric(m.group("kw"))
        if split is None:
            return None  # unmodeled granted ability → fail-closed
        keywords.extend(split[0])
        parametric.extend(split[1])
    if m.groupdict().get("must_blocked"):
        # PAR-124: "…until end of turn and must be blocked this turn if
        # able." (Compelled Duel/Emergent Growth/Joraga Invocation) — a
        # plain flag keyword (RULE 509.1c), same as any other granted one.
        keywords.append("must_be_blocked")
    if keywords:
        params["keywords"] = keywords
    if parametric:
        params["parametric_keywords"] = parametric
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: "Target Sliver creature gets +2/+2 until end of turn." (Firewake
#: Sliver) — a subtype-filtered creature target, using the same target
#: filter that regenerate/destroy/exile already carry.
_PUMP_SUBTYPE_TARGET_RE = _c(
    r"target (?P<subtype>[a-z]+) creature gets? (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+) until end of turn"
)


def _pump_subtype_target(m: re.Match[str]) -> list[EffectSpec]:
    # "Target attacking/blocking/tapped/untapped creature gets +N/+M…" is
    # RULE 508/509's board-state qualifier, not a real creature subtype —
    # this regex's bare `[a-z]+` capture doesn't know the difference and
    # would otherwise stamp a `creature_filter` naming a subtype
    # ("Attacking") no real creature ever has, making the target
    # unsatisfiable rather than just imprecise (found auditing the same
    # `resolve_target_kind` collapse this file's `_destroy`/`_pump_target`
    # fix addresses one layer down).
    state_filter = resolve_target_creature_state_filter(f"target {m.group('subtype')} creature")
    creature_filter = state_filter or {"subtype": m.group("subtype").capitalize()}
    return [EffectSpec("pump", {
        "power": _signed_int(m.group("p")),
        "toughness": _signed_int(m.group("t")),
        "target_kind": "creature",
        "creature_filter": creature_filter,
    })]


#: MEC-88's keyword-only sibling of the row above — "Target Bird creature
#: gains banding until end of turn." (Soraya the Falconer) — no P/T delta
#: at all, just a subtype-filtered keyword grant.
_GRANT_SUBTYPE_TARGET_RE = _c(
    r"target (?P<subtype>[a-z]+) creature gains? (?P<kw>[a-z, ]+?) until end of turn"
)


def _grant_subtype_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    # See `_pump_subtype_target`'s own comment: the bare `[a-z]+` capture
    # can't tell a real subtype from a combat-state qualifier.
    state_filter = resolve_target_creature_state_filter(f"target {m.group('subtype')} creature")
    creature_filter = state_filter or {"subtype": m.group("subtype").capitalize()}
    return [EffectSpec("pump", {
        "keywords": keywords,
        "target_kind": "creature",
        "creature_filter": creature_filter,
    })]


#: "Target Sliver creature gets +X/+0 …, where X is the number of Slivers
#: on the battlefield." (Magma Sliver) — an unscoped subtype count, distinct
#: from the controller-relative tribal selectors.
_PUMP_SUBTYPE_TARGET_GLOBAL_COUNT_RE = _c(
    r"target (?P<subtype>[a-z]+) creature gets? \+x/\+0 until end of turn, "
    r"where x is the number of (?P<count_subtype>[a-z]+)s on the battlefield"
)


def _pump_subtype_target_global_count(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subtype = m.group("subtype").lower()
    count_subtype = m.group("count_subtype").lower()
    if subtype != count_subtype:
        return None
    return [EffectSpec("pump", {
        "target_kind": "creature", "creature_filter": {"subtype": subtype.capitalize()},
        "amount_from_count_selector": f"creatures_of_type_{count_subtype}",
        "amount_from_count_selector_axis": "power",
    })]


def _pump_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"<subject> gets +x/+x [and gains <kw>] until end of turn" — an
    {X}-cost spell/ability's own announced {X} scaling the pump (Tyvar's
    Stand, Untamed Might, Primal Might's first clause). Emits the ``"x"``
    power/toughness sentinel that `RulesEngine._substitute_x` already
    rewrites to `GameObject.x_paid` at resolution; `PumpEffect.
    target_polarity` already tolerates the bare string. Only the symmetric
    "+x/+x"/"-x/-x" forms (no "where X is …" tail — that's a *dynamic board
    count*, a different family). "-x/-x" (Death Wind/Chill Haunting-shaped
    X-cost removal, and PAR-47's "remove X `<kind>` counters from ~: target
    creature gets -x/-x" spend clause — Infused Arrows) reuses the exact
    same ``x_paid``/`StackItem.x` mechanism regardless of whether the
    announced X paid a mana cost or a non-mana one like counters removed
    (`ActivationMixin._pay_activation_cost` stamps ``source.x_paid`` either
    way); `_substitute_x` already resolves the literal ``"-x"`` sentinel on
    a ``power``/``toughness`` attribute (Toxic Deluge's own "-X/-X" needed
    it first)."""
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    sign = m.group("sign")
    magnitude = "-x" if sign in ("-", "−") else "x"
    params: dict = {"power": magnitude, "toughness": magnitude}
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None  # unmodeled granted ability → fail-closed
        params["keywords"] = keywords
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


_PUMP_X_NONLAND_PERMANENTS_RE = _c(
    r"(?:~|it|this creature) gets? \+x/\+x until end of turn, where x is the number of nonland permanents you control"
)


def _pump_x_nonland_permanents(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "power": 0, "toughness": 0,
        "amount_from_count_selector": "nonland_permanents_you_control",
    })]


#: PAR-102(b): "[Until end of turn, ]target creature gets +2/+0 and gains [<keywords> and ]"<quoted
#: ability>"[ until end of turn]." (Abnormal Endurance, Hunter's Prowess, Supernatural Stamina, Unnatural
#: Moonrise …) — a pump that also hands out a whole quoted triggered/activated ability. Two specs share
#: one choice of recipient: the `pump` (P/T + any flag keywords) picks it, and the quoted grant — a
#: `grant_until` over the same `static_handlers._quoted_ability_grant_effects` the Aura/Equipment and
#: "gains "…" until end of turn" rows use — replays it (`previous_subject`; a group subject re-states its
#: selector as the static's ``affects``, a self subject its own source). The duration must be written
#: (prefix or suffix) — without one the grant would be permanent, a different card.


def _pump_and_quoted_grant(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .static_handlers import _quoted_ability_grant_effects  # local: avoid a module cycle

    if bool(m.group("dur_pre")) == bool(m.group("dur_post")):
        return None  # no duration (permanent) or two of them
    inner = _quoted_ability_grant_effects(m.group("inner"))
    if inner is None:
        return None
    return _pump_then_grant(m, {"type": inner.type, "params": dict(inner.params)})


def _pump_then_grant(m: re.Match[str], static: dict) -> Optional[list[EffectSpec]]:
    """A `pump` for ``m``'s subject and P/T (+ flag keywords) followed by a `grant_until` of ``static`` on
    that same subject until end of turn — the shared tail of the "pump and also grant …" rows."""
    if m.groupdict().get("attached"):
        return None  # "enchanted creature gets … and has …" is a standing static, not a resolving effect
    pump = _pump(m)
    if pump is None:
        return None
    target_kind, selector = _pump_target(m) or (None, None)
    grant: dict = {"static": static, "duration": "end_of_turn", "target_kind": None}
    if target_kind:
        grant["previous_subject"] = True
    elif selector:
        grant["static"]["params"]["affects"] = selector
        grant["lock_group"] = True  # RULE 611.2c: the set is fixed when the spell resolves
    else:
        grant["self_subject"] = True
    return [*pump, EffectSpec("grant_until", grant)]


#: "…gets +0/+1 and gains all creature types until end of turn" (Shields of Velis Vel-shaped) — RULE
#: 702.73a, as a layer-4 `ALL_CREATURE_TYPES` marker like the "is every creature type" static.
def _pump_and_all_creature_types(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _pump_then_grant(m, {"type": "type_change", "params": {"add_subtypes": ["Changeling"]}})


#: PAR-102: "[Until end of turn, ]<subject> [gets +N/+N and ]gains your choice of flying, vigilance, deathtouch,
#: or haste[ until end of turn]." (Alchemist's Gift, Argivian Avenger, the Avenger/Courier abilities, Manifold
#: Mouse, Gideon Blackblade's +1 …) — one `pump` whose ``keyword_options`` the controller picks from when it
#: resolves (RULE 608.2d). Only flag keywords: a parametric or quality option ("protection from red") leaves
#: the clause unclaimed rather than dropping a choice.
def _pump_keyword_choice(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if bool(m.group("dur_pre")) == bool(m.group("dur_post")):
        return None  # a missing duration is a permanent grant; two are a typo
    options: list[str] = []
    for part in re.split(r",\s*or\s+|\s+or\s+|,\s*", m.group("opts")):
        slug = _grantable_flag_slug(part.strip())
        if slug is None or slug in options:
            return None
        options.append(slug)
    if len(options) < 2:
        return None
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    if selector:
        return None  # "creatures you control gain your choice of …" — one pick for the group is a different clause
    params: dict = {"keyword_options": options}
    if m.groupdict().get("p") is not None:
        params["power"] = _signed_int(m.group("p"))
        params["toughness"] = _signed_int(m.group("t"))
    if target_kind:
        params["target_kind"] = target_kind
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("pump", params)]


def _pump_keywords(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    split = _split_keywords_with_parametric(m.group("kw"))
    if split is None:
        return None
    flags, parametric = split
    if not flags and not parametric:
        return None
    if m.groupdict().get("must_blocked"):
        # PAR-124: "…gains deathtouch until end of turn and must be blocked
        # this turn if able." (Deadly Allure) — same flag-keyword tail
        # `_pump`'s own "and must be blocked…" suffix already grants.
        flags = [*flags, "must_be_blocked"]
    params: dict = {}
    if flags:
        params["keywords"] = flags
    if parametric:  # ENG-31: "gains firebending N until end of turn"
        params["parametric_keywords"] = parametric
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _temporary_keyword_change(
    m: re.Match[str], *, previous_subject: bool = False,
) -> Optional[list[EffectSpec]]:
    """Layer-6 keyword gains/removals that last until cleanup (MEC-105).

    A single ``pump`` spec carries both halves so a compound "gains X and
    loses Y" sentence chooses/resolves its recipient only once. The same
    effect already owns targeted, self, group and previous-subject routing;
    ``removed_keywords`` is its ability-removing mirror of ``keywords``.
    """
    params: dict = {}
    if m.groupdict().get("p") is not None:
        params["power"] = _signed_int(m.group("p"))
        params["toughness"] = _signed_int(m.group("t"))
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    removed = _token_keywords(m.group("lost"))
    if removed is None:
        return None
    params["removed_keywords"] = removed
    if previous_subject:
        params["previous_subject"] = True
        return [EffectSpec("pump", params)]
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("pump", params)]


def _temporary_keyword_change_implicit(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """Self-subject "it loses …"; other pronouns use their gated row."""
    removed = _token_keywords(m.group("lost"))
    if removed is None:
        return None
    params: dict = {"removed_keywords": removed}
    if m.groupdict().get("p") is not None:
        params["power"] = _signed_int(m.group("p"))
        params["toughness"] = _signed_int(m.group("t"))
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    return [EffectSpec("pump", params)]


#: "Another target attacking creature gains indestructible until end of
#: turn" (Iconic Shield). This is a combat-state target restriction, not a
#: subtype quality the ordinary `_SUBJECT` grammar can represent.
_PUMP_OTHER_ATTACKING_CREATURE_RE = _c(
    r"another target attacking creature gains? (?P<kw>[a-z, ]+?) until end of turn"
)


def _pump_other_attacking_creature(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "target_kind": "creature", "creature_filter": {"attacking": True}, "keywords": keywords,
    })]


#: "target `<c1>` or `<c2>` creature gets +N/+M [and gains `<kw>`] / gains
#: `<kw>` until end of turn" — the Weaver cycle (Hate/Rage/Sky/Might/
#: Spirit Weaver, Sootstoke Kindler, Wilderness Hypnotist). `TargetSpec.
#: colors`' OR narrowing (`_DAMAGE_TARGET_TWO_COLOR_RE`'s pump sibling);
#: the shared `TARGET` macro's fixed rows carry no colour slot, so a
#: dedicated row like Rending Volley's. Only ever two colours on a real
#: card in this shape.
#: P/T delta ("+1/+0" / "-2/-0", ASCII or unicode minus) — inlined rather
#: than `_PT_DELTA` (defined later in this file).
_PUMP_TARGET_TWO_COLOR_RE = _c(
    rf"target (?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) creature "
    r"(?:gets? (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)(?: and gains? (?P<kw>[a-z, ]+?))?"
    r"|gains? (?P<kw2>[a-z, ]+?))"
    r" until end of turn"
)


def _pump_target_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = [resolve_color_word(m.group("c1")), resolve_color_word(m.group("c2"))]
    if not all(colors) or colors[0] == colors[1]:
        return None
    params: dict = {"target_kind": "creature", "colors": colors}
    if m.groupdict().get("p") is not None:
        params["power"] = _signed_int(m.group("p"))
        params["toughness"] = _signed_int(m.group("t"))
    kw = m.groupdict().get("kw") or m.groupdict().get("kw2")
    if kw:
        kws = _token_keywords(kw)
        if kws is None:
            return None  # a non-flag granted ability → fail-closed
        params["keywords"] = kws
    if "power" not in params and "keywords" not in params:
        return None
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


# RULE 701.10/11 "double"/"triple `<creature>`'s power and toughness [until
# end of turn]" — a `PumpEffect.self_multiplier` recipient-relative pump
# (each recipient's own current power/toughness, not a flat/shared amount),
# PAR-29. Three surface shapes on real cards, each its own row: "double the
# power and toughness of `<TARGET>`/each creature you control" (Dragonclaw
# Strike/Roar of Endless Song), the possessive "double `<TARGET>`'s/~'s
# power and toughness" (Nylea's Colossus/Reckless Amplimancer/Tifa's Limit
# Break's own "triple"), and the bare pronoun "double its power and
# toughness" — offered both `self_subject_only` (Grunn's "whenever ~
# attacks alone, double its power and toughness") and `previous_subject_
# only` (World War Hulk's "choose target creature you control. … double its
# power and toughness.").
_DOUBLE_PT_MULTIPLIERS: dict[str, int] = {"double": 2, "triple": 3}
_DOUBLE_PT_TARGET_KINDS = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control"}
)
#: PAR-135: which half of the stats "double"/"triple" scales — a slot of the four rows below, not a row per
#: wording ("double target creature's power", Bulk Up; "double its power", Death Kiss — 11 cards).
_DOUBLE_STAT = r"(?P<stat>power and toughness|power|toughness)"
_DOUBLE_STAT_PARAM: dict[str, str] = {"power and toughness": "both", "power": "power", "toughness": "toughness"}


def _double_pump(m: re.Match[str], params: dict) -> Optional[list[EffectSpec]]:
    """The one `pump` every double/triple row emits: its multiplier, plus the stat slot."""
    mult = _DOUBLE_PT_MULTIPLIERS.get(m.group("mult"))
    if mult is None:
        return None
    params = {**params, "self_multiplier": mult}
    stat = _DOUBLE_STAT_PARAM[m.group("stat").lower()]
    if stat != "both":
        params["self_multiplier_stat"] = stat
    return [EffectSpec("pump", params)]


_DOUBLE_PRONOUN_RE = _c(rf"(?P<mult>double|triple) its {_DOUBLE_STAT} until end of turn")


def _double_pt_of(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.groupdict().get("each_group"):
        return _double_pump(m, {"selector": "creatures_you_control"})
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _DOUBLE_PT_TARGET_KINDS):
        return None
    return _double_pump(m, {"target_kind": kind, **_optional_param(m)})


def _double_pt_possessive(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.groupdict().get("selfposs"):
        return _double_pump(m, {})
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _DOUBLE_PT_TARGET_KINDS):
        return None
    return _double_pump(m, {"target_kind": kind, **_optional_param(m)})


def _double_pt_pronoun(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _double_pump(m, {})


def _double_pt_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return _double_pump(m, {"previous_subject": True})


def _double_pt_attached(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Whenever equipped creature attacks, double **its** power" — RULE 301.5/303.4 the host
    (`PumpEffect`'s ``attached_permanent`` mode, the one "enchanted creature gains …" already uses)."""
    return _double_pump(m, {"target_kind": "attached_permanent"})


def _double_pt_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Whenever a creature … attacks, double **its** power" — the creature that fired the group trigger,
    read live off the event (`PumpEffect.trigger_subject`, the same route `_pump_group_subject` takes)."""
    return _double_pump(m, {"trigger_subject": True, "trigger_event_key": GROUP_SUBJECT_KEY_SENTINEL})


#: "Target attacking Elf you control gains deathtouch until end of turn."
#: (Gnarlroot Trapper-shaped) — RULE 506.4's attacker status composed with
#: a creature-subtype filter (`combat.matches_object_filter`'s new
#: ``"attacking"`` key), a target phrase the shared `TARGET` macro has no
#: row for.
_PUMP_ATTACKING_SUBTYPE_TARGET_RE = _c(
    r"target attacking (?P<subtype>[a-z]+) you control gains? (?P<kw>[a-z, ]+?) until end of turn"
)


def _pump_attacking_subtype_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "keywords": keywords, "target_kind": "creature_you_control",
        "creature_filter": {"attacking": True, "subtype": m.group("subtype").capitalize()},
    })]


#: "Up to two target creatures each get +N/+N [and gain `<keywords>`] until
#: end of turn." (Dauntless Onslaught-shaped — the single biggest pump
#: template found in the cache, 19 SOLO cards, `parser_probe.py blocked`) /
#: "One or two target creatures…" (Opera Love Song/Heroic Teamwork-shaped) —
#: ENG-30: these are no longer the same shape. "Up to two" is RULE 115.1a's
#: 0..2 `optional` idiom; "one or two" is a genuine RULE 601.2c *range*
#: (`TargetSpec.count_max`, at least one) — previously both were folded to
#: `count=2, optional=True` as a documented simplification (declining below
#: the "one or two" minimum was never a choice a real player would make
#: differently); now that the engine has a real range primitive, the two
#: wordings get their real, distinct shapes instead.
_PUMP_UP_TO_TWO_RE = _c(
    r"up to 2 target creatures each gets? "
    r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)
_PUMP_ONE_OR_TWO_RE = _c(
    r"1 or 2 target creatures each gets? "
    r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)


def _pump_up_to_two(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        # `EffectRegistry`'s "pump" factory reads the *target* count as
        # "target_count" (distinct from a magnitude key also spelled
        # "count" elsewhere in this file) — a bare "count" here was a
        # dormant bug: every "up to two target creatures" pump spell (19
        # SOLO cards, Dauntless Onslaught-shaped) silently only ever
        # offered *one* target, since `PumpEffect`'s own `count` defaulted
        # to 1 and this key was never read. Found while building ENG-30's
        # neighboring "one or two" range shape just below.
        "target_kind": "creature", "target_count": 2, "optional": True,
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _pump_one_or_two(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "target_kind": "creature", "target_count": 1, "target_count_max": 2,
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: ENG-30: "1 or 2 target creatures gain `<kw>` until end of turn." (Wind
#: Sail) — the keyword-only sibling of `_PUMP_ONE_OR_TWO_RE` (no P/T delta
#: at all, unlike every other row in this family).
#: PAR-98: the optional "each" (Run for Your Life's "1 or 2 target creatures
#: **each** gain haste until end of turn").
_PUMP_ONE_OR_TWO_KW_RE = _c(
    r"1 or 2 target creatures (?:each )?gains? (?P<kw>[a-z][a-z, ]*?) until end of turn"
)


def _pump_one_or_two_kw(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "target_kind": "creature", "target_count": 1, "target_count_max": 2, "keywords": keywords,
    })]


#: "Each creature your opponents control gets -1/-1 until end of turn for
#: each poison counter its controller has." (Phyresis Outbreak-shaped) —
#: `PumpEffect.per_recipient_controller_counter`'s own dedicated grammar:
#: unlike every other group-pump row, each recipient's boost scales
#: independently by *its own controller's* count of a player counter kind,
#: not one shared magnitude. Deliberately narrow to "poison" (a direct
#: `Player.poison` attribute) — a "rad"/"energy" variant would read
#: `Player.counters` instead, unneeded by any real card yet.
_PUMP_PER_CONTROLLER_COUNTER_RE = _c(
    r"each creature your opponents control "
    r"gets? (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+) until end of turn "
    r"for each (?P<kind>poison) counter its controller has"
)


def _pump_per_controller_counter(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "selector": "creatures_opponents_control",
        "per_recipient_controller_counter": m.group("kind"),
    })]


#: "Creatures you control gain trample and get +X/+X until end of turn,
#: where X is the number of creatures you control." (Craterhoof Behemoth-
#: shaped) — `PumpEffect.amount_from_count_selector`'s own dedicated
#: grammar: one shared magnitude for the whole "creatures you control"
#: group, computed live from the board rather than a fixed int. The
#: keyword-list-*then*-P/T word order ("gain `<kw>` and get +X/+X") is the
#: opposite of `_pump`'s own "+N/+N and gain `<kw>`", so this needs its
#: own row rather than widening that one.
_GROUP_PUMP_COUNT_SELECTOR_RE = _c(
    r"creatures you control gain (?P<kw>[a-z, ]+?) and get \+x/\+x until end of turn, "
    r"where x is the number of creatures you control"
)


def _group_pump_count_selector(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "keywords": keywords, "selector": "creatures_you_control",
        "amount_from_count_selector": "creatures_you_control",
    })]


#: "Other creatures you control gain trample and get +X/+X until end of
#: turn, where X is this creature's power." (Dragon Throne of Tarkir) — the
#: source-power sibling of the ordinary group pump.  ``other`` is important:
#: the granted ability lives on the equipped creature and must not buff that
#: creature itself (RULE 109.5).
_GROUP_PUMP_OTHER_SOURCE_POWER_RE = _c(
    r"other creatures you control gain (?P<kw>[a-z, ]+?) and get \+x/\+x until end of turn, "
    r"where x is ~'?s power"
)


def _group_pump_other_source_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "keywords": keywords,
        "selector": "other_creatures_you_control",
        "amount_from_count_selector": "source_power",
    })]


#: "Target creature gets +1/+1 until end of turn for each creature you
#: control" (Friendly Neighborhood) / "…gets +1/+1 for each creature you
#: control and gains trample. It must be blocked this turn if able."
#: (King Harald's Revenge, PAR-124 — the "for each" clause sits *before*
#: an "and gains `<kw>`" tail instead of after "until end of turn", and the
#: duration word can trail either the P/T delta or the whole sentence).
#: The target and the count source are independent: the selected creature
#: need not be controlled by the player.
_PUMP_TARGET_PER_CREATURE_YOU_CONTROL_RE = _c(
    r"(?:until end of turn, )?target creature gets? \+1/\+1"
    r"(?: until end of turn)? for each creature you control"
    r"(?: and gains? (?P<kw>[a-z, ]+?))?"
    r"(?: until end of turn)?"
)


def _pump_target_per_creature_you_control(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "target_kind": "creature", "amount_from_count_selector": "creatures_you_control",
    }
    kw = m.groupdict().get("kw")
    if kw:
        keywords = _token_keywords(kw)
        if keywords is None:
            return None
        params["keywords"] = keywords
    return [EffectSpec("pump", params)]


#: RULE 202.2f/700.6 "target creature gets +X/+X until end of turn, where X
#: is your devotion to `<colour(s)/wedge>`." (Aspect of Hydra/Devoted Temur-
#: shaped) — the `DEVOTION` fragment feeding `PumpEffect.amount_from_count_
#: selector` via `continuous.count_selector`'s existing `devotion_to_<key>`
#: vocabulary, same shape `_GROUP_PUMP_COUNT_SELECTOR_RE` uses for a board
#: count instead of a mana-symbol one.
_PUMP_DEVOTION_TARGET_RE = _c(rf"{TARGET} gets? \+x/\+x until end of turn, where x is {DEVOTION}")
#: The mass sibling — "creatures you control get +X/+X …" (Klothys's
#: Design) — same amount grammar, group subject instead of a RULE 115
#: target.
_GROUP_PUMP_DEVOTION_RE = _c(
    rf"creatures you control gets? \+x/\+x until end of turn, where x is {DEVOTION}"
)
#: The debuff sibling — "target creature [an opponent controls] gets -X/-X
#: until end of turn, where X is your devotion to `<colour>`." (Blight-
#: Breath Catoblepas) — `PumpEffect.amount_from_count_selector_negative`
#: flips the always-nonnegative devotion count into the printed "-X/-X".
_PUMP_DEVOTION_NEGATIVE_TARGET_RE = _c(
    rf"{TARGET} gets? -x/-x until end of turn, where x is {DEVOTION}"
)
#: "Another target creature you control gets +X/+X until end of turn, where
#: X is ~'s power." (Hardy Outlander's granted attack trigger, PAR-32) —
#: `continuous.count_selector`'s `source_power`, its own row rather than a
#: `{DEVOTION}` addition (that subgrammar is reused far too widely).
_PUMP_TARGET_SOURCE_POWER_RE = _c(
    rf"{TARGET} (?:gets? \+x/\+x(?: and gains? (?P<kw>[a-z, ]+?))?"
    r"|gains? (?P<kw2>[a-z, ]+?) and gets? \+x/\+x)"
    r" until end of turn, where x is ~'?s power"
)


def _pump_target_source_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector_subject = subject
    params: dict = {"amount_from_count_selector": "source_power"}
    granted = m.group("kw") or m.group("kw2")
    if granted:
        # "gains trample and gets +X/+X …" (Ashroot Animist): the keyword rides the same pump.
        keywords = _token_keywords(granted)
        if keywords is None:
            return None
        params["keywords"] = keywords
    if target_kind is not None:
        params["target_kind"] = target_kind
    if selector_subject is not None:
        params["selector"] = selector_subject
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: PAR-71: "<subject> gets +X/+X [or +X/+0] until end of turn, where X is
#: that spell's mana value." (Manaplasm/Jamie McCrimmon's symmetric form;
#: Erratic Cyclops/Livaan's power-only form) — the `PumpEffect.
#: amount_from_trigger_event` sibling of the `DEVOTION`-scaled pump rows
#: above, reading the firing `SPELL_CAST` event's own ``mana_value`` field
#: (already stamped on every such event by `casting_mixin.cast_spell` —
#: see its own "Shark Typhoon-shaped spell-cast payoffs" comment — so this
#: is pure recognition, no new engine work).
_PUMP_MANA_VALUE_RE = _c(
    rf"(?:{TARGET}|(?P<selfref>{re.escape(SELF)})) gets? \+x/\+(?P<taxis>x|0) until end of turn, "
    r"where x is that spell'?s mana value"
)


def _pump_mana_value(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    params: dict = {"amount_from_trigger_event": "mana_value"}
    if m.group("taxis") == "0":
        params["amount_from_count_selector_axis"] = "power"
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: PAR-80: "target creature gets +X/+0[/+X] until end of turn." — the
#: base X-spell/X-ability pump, no "where X is…" tail at all (Bloodcurdling
#: Scream/Enrage/Hatred/Howl from Beyond, all bare instants with an
#: announced ``{X}`` cost; Cackling Witch/Kessig Wolf Run/Secluded
#: Starforge, the identical body on an ``{X}…`` activated ability instead).
#: X here is simply RULE 107.3c's announced {X} — `RulesEngine._substitute_x`
#: already walks any bound effect's own ``power``/``toughness`` for the
#: literal ``"x"``/``"-x"`` sentinel (Bring to Light/Toxic Deluge's own
#: precedent, `game/card_registry/competitive_interaction.py`'s "x"/"x"
#: pump), so this is pure recognition — no new engine primitive.
#: An optional trailing "and gains `<keyword list>`" (Kessig Wolf Run's
#: "…and gains trample"; Pedal to the Metal's "…and gains first strike") —
#: `_pump`'s own tail grammar, mirrored here since this row's magnitude
#: (``"x"``) is what keeps it from just widening that row directly.
_PUMP_TARGET_X_RE = _c(
    rf"{TARGET} gets? \+x/(?P<taxis>\+x|\+0)"
    r"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
)


def _pump_target_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    params: dict = {"power": "x", "toughness": "x" if m.group("taxis") == "+x" else 0}
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: PAR-80: "target creature gets +X/+0[/+X] until end of turn, where X is
#: `<quantity>`." — ENG-37's general `bind`/`effect_amounts` measurement,
#: not a `PumpEffect` ``amount_from_*`` parameter per referent. PAR-120: a
#: count or aggregate ("the number of Mountains you control", "the greatest
#: power among creatures you control", "the amount of life you gained this
#: turn", "3 plus the number of cards named ~ in all graveyards") is read by
#: the shared amount vocabulary (`count_phrase.parse_amount_phrase`); only
#: the referents that aren't a quantity of the board stay a table — the
#: target's *own* current power (``of: "target"``, read before this same
#: effect's pump applies, Drain Life's proven `bind` pattern) and the most
#: recent `RollDieEffect` total.
_PUMP_X_REFERENT_AMOUNTS: dict[str, dict] = {
    "its power": {"kind": "characteristic", "characteristic": "power", "of": "target"},
    "that creature's power": {"kind": "characteristic", "characteristic": "power", "of": "target"},
    "the result": {"kind": "die_result"},
}
_PUMP_TARGET_X_AMOUNT_RE = _c(
    rf"{TARGET} gets? \+x/(?P<taxis>\+x|\+0) until end of turn, "
    r"where x is (?P<phrase>.+)"
)


def _pump_target_x_amount(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    phrase = m.group("phrase")
    referent = _PUMP_X_REFERENT_AMOUNTS.get(phrase)
    if referent is not None:
        amount_spec = dict(referent)
    else:
        from .count_phrase import parse_amount_phrase

        counted = parse_amount_phrase(phrase)
        if counted is None:
            return None
        amount_spec = {"kind": "count_selector", "selector": counted}
    pump_params: dict = {
        "power": "$px", "toughness": "$px" if m.group("taxis") == "+x" else 0,
    }
    if target_kind:
        pump_params["target_kind"] = target_kind
    if selector:
        pump_params["selector"] = selector
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        pump_params["creature_filter"] = state_filter
    return [EffectSpec("bind", {
        "name": "px", "amount": amount_spec,
        "effects": [{"type": "pump", "params": pump_params}],
    })]


#: MEC-90 / RULE 706: these ordinary effect bodies consume the prior die
#: result through ENG-37's generic ``bind`` node, instead of each effect
#: class gaining its own ``amount_from_die_result`` parameter. The same inner
#: specs work after a roll and in its RULE 603.11 ``then_trigger`` body.
_DIE_RESULT_AMOUNT = {"kind": "die_result"}


def _bind_die_result(effect_type: str, params: dict) -> list[EffectSpec]:
    return [EffectSpec("bind", {
        "name": "die", "amount": dict(_DIE_RESULT_AMOUNT),
        "effects": [{"type": effect_type, "params": params}],
    })]


_GAIN_LIFE_DIE_RESULT_RE = _c(r"you gain life equal to the result")


def _gain_life_die_result(m: re.Match[str]) -> list[EffectSpec]:
    return _bind_die_result("gain_life", {"amount": "$die"})


_DRAW_DIE_RESULT_RE = _c(r"(?:you )?draw cards equal to the result")


def _draw_die_result(m: re.Match[str]) -> list[EffectSpec]:
    return _bind_die_result("draw", {"count": "$die"})


_NO_MAX_HAND_SIZE_REST_OF_GAME_RE = _c(
    r"you have no maximum hand size for the rest of the game"
)


def _no_max_hand_size_rest_of_game(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("no_max_hand_size_rest_of_game", {})]


_CREATE_NAMED_TOKEN_DIE_RESULT_RE = _c(
    r"you create a number of (?P<name>[a-z]+) tokens equal to the result"
)


def _create_named_token_die_result(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    name = m.group("name")
    if name not in _NAMED_TOKEN_WORDS:
        return None
    return _bind_die_result("create_token", {
        "count": "$die", "token_name": _NAMED_TOKEN_WORDS[name],
    })


_CREATE_CREATURE_TOKEN_DIE_RESULT_RE = _c(
    r"you create a number of (?P<p>\d+)/(?P<t>\d+) (?P<mid>[a-z ]*?)"
    r"creature tokens?(?: with (?P<kw>[a-z, ]+))? equal to the result"
)


def _create_creature_token_die_result(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    return _bind_die_result("create_token", {
        **params, "count": "$die", "power": int(m.group("p")), "toughness": int(m.group("t")),
    })


_ADD_COUNTERS_DIE_RESULT_RE = _c(
    r"put x (?P<kind>\+1/\+1|-1/-1|−1/−1) counters on each of up to "
    r"(?P<targets>\d+) target creatures, where x is the result"
)


def _add_counters_die_result(m: re.Match[str]) -> list[EffectSpec]:
    return _bind_die_result("add_counters", {
        "count": "$die", "kind": _counter_sign(m.group("kind")),
        "target_kind": "creature", "target_count": int(m.group("targets")), "optional": True,
    })


_RETURN_CREATURES_DIE_RESULT_RE = _c(
    r"put any number of target creature cards with total mana value x or less from "
    r"graveyards onto the battlefield under your control, where x is the result"
)


def _return_creatures_die_result(m: re.Match[str]) -> list[EffectSpec]:
    return _bind_die_result("return_creatures_total_mana_value", {"budget": "$die"})


#: PAR-80: "Roll a `<n>`-sided die. Target creature gets +X/+X until end of
#: turn, where X is the result." (Growth Spurt) needs no dedicated handler
#: of its own for the first sentence — "Roll a `<n>`-sided die." already
#: parses standalone (``roll_die``) — only the second sentence's "the
#: result" referent, in `_PUMP_X_REFERENT_AMOUNTS` above.
#:
#: "target creature gets +X/+<N> until end of turn, where X is a number
#: from A to B chosen at random." (Hapato's Might) is a *different*
#: primitive from the die roll above (RULE 706.11 only treats literal "roll
#: a die" text as subject to dice-replacement effects), so it gets its own
#: small effect (`RandomNumberEffect`/``"random_number"``) and amount kind
#: (``"random_result"``) rather than being folded into ``die_result``.
#: ``A``/``B`` are captured, not hardcoded to 0/6, so a future card with a
#: different range reuses this same row.
_PUMP_TARGET_X_RANDOM_RE = _c(
    rf"{TARGET} gets? \+x/(?P<taxis>\+x|\+0) until end of turn, "
    r"where x is a number from (?P<lo>\d+) to (?P<hi>\d+) chosen at random"
)


def _pump_target_x_random(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    pump_params: dict = {
        "power": "$px", "toughness": "$px" if m.group("taxis") == "+x" else 0,
    }
    if target_kind:
        pump_params["target_kind"] = target_kind
    if selector:
        pump_params["selector"] = selector
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        pump_params["creature_filter"] = state_filter
    return [
        EffectSpec("random_number", {"min": int(m.group("lo")), "max": int(m.group("hi"))}),
        EffectSpec("bind", {
            "name": "px", "amount": {"kind": "random_result"},
            "effects": [{"type": "pump", "params": pump_params}],
        }),
    ]


#: PAR-80: "Target opponent reveals a card at random from their hand.
#: Target creature gets +X/+<N> until end of turn, where X is the revealed
#: card's mana value." (Planeswalker's Favor) — a genuinely singleton
#: two-target compound (the reveal's own "target opponent" plus the pump's
#: "target creature"), built the same `bind`-over-`pump` way as the
#: phrase-table family above, just with its own leading reveal clause
#: instead of a board count.
_REVEAL_RANDOM_HAND_CARD_PUMP_MV_RE = _c(
    r"target opponent reveals a card at random from their hand\. "
    rf"{TARGET} gets? \+x/(?P<taxis>\+x|\+0) until end of turn, "
    r"where x is the revealed card'?s mana value"
)


def _reveal_random_hand_card_pump_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    pump_params: dict = {
        "power": "$px", "toughness": "$px" if m.group("taxis") == "+x" else 0,
    }
    if target_kind:
        pump_params["target_kind"] = target_kind
    if selector:
        pump_params["selector"] = selector
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        pump_params["creature_filter"] = state_filter
    return [
        EffectSpec("reveal_random_hand_card", {"target_kind": "opponent"}),
        EffectSpec("bind", {
            "name": "px",
            "amount": {"kind": "characteristic", "characteristic": "mana_value", "of": "revealed"},
            "effects": [{"type": "pump", "params": pump_params}],
        }),
    ]


#: PAR-80: "Reveal any number of green cards in your hand. Target creature
#: gets +X/+X until end of turn, where X is the number of cards revealed
#: this way." (Ivy Seer, Scent of Ivy — the identical body under an
#: activated-ability cost and a bare sorcery respectively; the cost prefix
#: is split off before this handler ever sees the text, same as every other
#: ``<cost>: <effect>`` row in this file). Only "green" is in this closed
#: table today — widen ``_REVEAL_ANY_NUMBER_COLOR_WORDS`` the day a second
#: color shows up rather than guessing an open vocabulary now.
_REVEAL_ANY_NUMBER_COLOR_WORDS: dict[str, str] = {"green": "G"}
_REVEAL_ANY_NUMBER_COLOR_ALT = "|".join(_REVEAL_ANY_NUMBER_COLOR_WORDS)
_REVEAL_ANY_NUMBER_PUMP_RE = _c(
    rf"reveal any number of (?P<color>{_REVEAL_ANY_NUMBER_COLOR_ALT}) cards in your hand\. "
    rf"{TARGET} gets? \+x/(?P<taxis>\+x|\+0) until end of turn, "
    r"where x is the number of cards revealed this way"
)


def _reveal_any_number_pump(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    color = _REVEAL_ANY_NUMBER_COLOR_WORDS.get(m.group("color"))
    if color is None:
        return None
    pump_params: dict = {
        "power": "$px", "toughness": "$px" if m.group("taxis") == "+x" else 0,
    }
    if target_kind:
        pump_params["target_kind"] = target_kind
    if selector:
        pump_params["selector"] = selector
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        pump_params["creature_filter"] = state_filter
    return [
        EffectSpec("reveal_any_number_hand_cards", {"colors": [color]}),
        EffectSpec("bind", {
            "name": "px",
            "amount": {"kind": "count_selector", "selector": "revealed_with_count"},
            "effects": [{"type": "pump", "params": pump_params}],
        }),
    ]


def _pump_devotion_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector_subject = subject
    selector = devotion_selector(m)
    if not selector:
        return None
    params: dict = {"amount_from_count_selector": selector}
    if target_kind:
        params["target_kind"] = target_kind
    if selector_subject:
        params["selector"] = selector_subject
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _pump_devotion_negative_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector_subject = subject
    selector = devotion_selector(m)
    if not selector:
        return None
    params: dict = {"amount_from_count_selector": selector, "amount_from_count_selector_negative": True}
    if target_kind:
        params["target_kind"] = target_kind
    if selector_subject:
        params["selector"] = selector_subject
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _group_pump_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector = devotion_selector(m)
    if not selector:
        return None
    return [EffectSpec("pump", {"selector": "creatures_you_control", "amount_from_count_selector": selector})]


# ---------------------------------------------------------------------------
# PAR-81: "Switch target creature's power and toughness until end of turn."
# — the resolving one-shot form (Twisted Image-shaped). `"pt_switch"`
# already existed as a `StaticAbility` layer 7e type for a granted/printed
# standing ability; this is its `"switch_power_toughness"` one-shot sibling
# (`SwitchPowerToughnessEffect`, `game/effects/counters_tokens.py`).
# ---------------------------------------------------------------------------

#: The RULE 115 targeted form — "switch target creature's power and
#: toughness until end of turn." (About Face/Twisted Image and siblings).
_SWITCH_PT_TARGET_RE = _c(
    rf"switch {TARGET}'?s power and toughness until end of turn"
)


def _switch_pt_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent")):
        return None
    return [EffectSpec("switch_power_toughness", {"target_kind": kind})]


#: The self-referential form — "switch ~'s power and toughness until end
#: of turn." (Aeromoeba/Aquamoeba's own activated ability) / "switch its
#: power and toughness until end of turn." (Valakut Fireboar's own attack
#: trigger — "its" naming the ability's own source, RULE 603.1 subject
#: scoping already strips the trigger condition before this clause is
#: reached). No target at all — acts on the effect's own bound `source`.
_SWITCH_PT_SELF_RE = _c(r"switch (?:~'s|its) power and toughness until end of turn")


def _switch_pt_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("switch_power_toughness", {})]


#: The mass, untargeted form — "switch each creature's power and toughness
#: until end of turn." (Mannichi, the Fevered Dream) — RULE 601.2c, no
#: RULE 115 target at all, reusing `continuous.group_selector_objects`'s
#: existing ``"all_creatures"`` selector the same way `_cant_block_turn_
#: group`'s own mass form does.
_SWITCH_PT_MASS_RE = _c(r"switch each creature'?s power and toughness until end of turn")


def _switch_pt_mass(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("switch_power_toughness", {"selector": "all_creatures"})]


#: The multi-target form — "switch the power and toughness of each of
#: `<up to N|any number of>` target creatures until end of turn." (Invert
#: // Invent's "up to 2"; Inversion Behemoth's "any number of") — RULE
#: 115.1a generalized to N>=2, the identical "any number of"/"up to N"
#: quantifier pair `_MULTI_TARGET_QUANTIFIER` uses elsewhere, but this
#: phrase wraps the quantifier+target *inside* "each of…" rather than
#: leading with it, so it gets its own small regex instead of that shared
#: macro.
_SWITCH_PT_MULTI_RE = _c(
    r"switch the power and toughness of each of "
    r"(?:up to (?P<n>\d+)|(?P<any>any number of)) target creatures until end of turn"
)


def _switch_pt_multi(m: re.Match[str]) -> list[EffectSpec]:
    count = _ANY_NUMBER_TARGET_CAP if m.group("any") else int(m.group("n"))
    return [EffectSpec("switch_power_toughness", {
        "target_kind": "creature", "count": count, "optional": True,
    })]


#: The devotion/count-scaled sibling of `_pump_self_subject`'s fixed-int
#: form — "it gets +X/+X until end of turn, where X is `{DEVOTION}`"
#: (Angelic Exaltation/Akroan Hoplite-adjacent self-buff-on-attack — see
#: `{DEVOTION}`'s own docstring for the wider "the number of `<noun
#: phrase>` you control" reading this also picks up). Symmetric only
#: (``+x/+x``/``-x/-x``): `PumpEffect.amount_from_count_selector` always
#: sets power and toughness to the *same* resolved amount, so an
#: asymmetric "+X/+0" (Akroan Hoplite's own real printing) has no way to
#: express "only power scales" yet and stays unclaimed — a smaller,
#: separate gap from the amount-resolver this row closes.
_PUMP_SELF_SUBJECT_DEVOTION_RE = _c(
    rf"it gets? (?P<sign>\+|-)x/(?P=sign)x until end of turn, where x is {DEVOTION}"
)


def _pump_self_subject_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector = devotion_selector(m)
    if not selector:
        return None
    params: dict = {"amount_from_count_selector": selector}
    if m.group("sign") == "-":
        params["amount_from_count_selector_negative"] = True
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _pump_self_subject(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """The bare-pronoun sibling of `_pump`'s untargeted self form —
    "it gets +N/+N [and gains <keyword>] until end of turn" (Akroan Hoplite/
    Aurochs-shaped: an attack/enters trigger whose own body refers back to
    the source as "it" rather than "~", `self_subject_only`-gated)."""
    params: dict = {
        "power": _signed_int(m.group("p")),
        "toughness": _signed_int(m.group("t")),
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None  # unmodeled granted ability → fail-closed
        params["keywords"] = keywords
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _grant_self_subject_kw(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Whenever ~ attacks, it gains double strike until end of turn."
    (Flaming Fist) — a keyword-only self-pump (no P/T delta), `it` bound to
    the ability's own source (`self_subject_only`)."""
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None  # unmodeled granted ability → fail-closed
    return [EffectSpec("pump", {"keywords": keywords})]


def _grant_group_subject_kw(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Whenever a creature … attacks, it gains skulk until end of turn
    [and must be blocked this turn if able]."

    Here ``it`` is neither this ability's source nor a preceding RULE 115
    target: it is the particular RULE 603.1 group object that fired the
    trigger. `GrantKeywordToTriggerSubjectEffect` already owns that live
    event-reference behaviour (Tyvar Kell's emblem); this parser row merely
    routes the ordinary creature-event spelling to it. PAR-124's own
    "and must be blocked this turn if able" tail (Descend on the Prey) is
    a second, independent flag keyword on the same trigger subject — this
    effect type only ever carries one ``keyword``, so it's a second spec
    rather than a list, both reading the identical event at resolution.
    """
    keywords = _token_keywords(m.group("kw"))
    if keywords is None or len(keywords) != 1:
        return None
    specs = [EffectSpec("grant_keyword_to_trigger_subject", {
        "keyword": keywords[0], "event_key": GROUP_SUBJECT_KEY_SENTINEL,
    })]
    if m.groupdict().get("must_blocked"):
        specs.append(EffectSpec("grant_keyword_to_trigger_subject", {
            "keyword": "must_be_blocked", "event_key": GROUP_SUBJECT_KEY_SENTINEL,
        }))
    return specs


#: "it gets +X/+X until end of turn" (PAR-123) — the pronoun subject with the
#: symmetric X magnitude, whose X a trailing ", where X is the number of …"
#: binds (`segmenter._where_x_specs`: Angelic Exaltation, Thoughtweft Imbuer,
#: Altar of the Goyf). One regex, three subject flavours (source / group
#: trigger's firing object / a preceding clause's target).
_PUMP_IT_X_RE = _c(
    r"it gets? \+x/\+x(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
)


def _pump_it_x(m: re.Match[str], *, subject: str) -> Optional[list[EffectSpec]]:
    params: dict = {"power": "x", "toughness": "x"}
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    if subject == "group":
        params["trigger_subject"] = True
        params["trigger_event_key"] = GROUP_SUBJECT_KEY_SENTINEL
    elif subject == "previous":
        params["previous_subject"] = True
    return [EffectSpec("pump", params)]


def _pump_group_subject(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Whenever a creature … attacks, **it** gets +N/+N [and gains `<keyword>`] until end of
    turn." — the object that fired the group trigger, read live off the event
    (`PumpEffect.trigger_subject`, the mechanism Exalted uses)."""
    specs = _pump_self_subject(m)
    if specs is None:
        return None
    params = dict(specs[0].params)
    params["trigger_subject"] = True
    params["trigger_event_key"] = GROUP_SUBJECT_KEY_SENTINEL
    return [EffectSpec("pump", params)]


#: The durations a grant may carry beyond "until end of turn", as printed →
#: `game/durations.py`'s vocabulary. "Until end of turn" is deliberately
#: absent: that is exactly what the `pump` family's ``temp_*`` fields already
#: are (cleared at RULE 514.2 cleanup), and routing it here too would give one
#: phrasing two implementations. These are the ones ``temp_*`` *cannot*
#: express, because it has nowhere to record any other ending.
_GRANT_DURATIONS: dict[str, str] = {
    "until your next turn": "your_next_turn",
    "until end of combat": "end_of_combat",
    "until the end of combat": "end_of_combat",
    "until the beginning of the next end step": "next_end_step",
}


def _grant_until(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Target creature gains flying until your next turn." (RULE 611)

    The keyword-pump handler's sibling for every duration other than end of
    turn — same subjects, same keyword vocabulary, but the grant becomes a
    real continuous effect on `GameState.floating_statics` rather than a
    turn-scoped ``temp_*`` stamp.
    """
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    duration = _GRANT_DURATIONS.get(m.group("dur").strip().lower())
    if duration is None:
        return None
    static: dict = {"type": "grant_keyword", "params": {"keywords": keywords}}
    params: dict = {"static": static, "duration": duration}
    if target_kind:
        params["target_kind"] = target_kind
    else:
        # A group grant ("creatures you control gain flying until your next
        # turn") has no target: the static keeps the selector as its own
        # ``affects``, so the floating effect covers whatever matches it at
        # each recompute (RULE 611.2c).
        params["target_kind"] = None
        static["params"]["affects"] = selector
    return [EffectSpec("grant_until", params)]


#: MEC-88's temporary-removal sibling of `_grant_until` — "target creature
#: loses banding and all "bands with other" abilities until end of turn."
#: (Tolaria's own body, minus its separate "activate only during any
#: upkeep step" timing-restriction sentence — a genuinely new activation-
#: window marker this batch doesn't build, so Tolaria itself stays
#: UNMODELED) / "target creature loses all "bands with other" abilities
#: until end of turn." (Shelkin Brownie). RULE 613.7f ability-removal via
#: a `grant_until`-parked `remove_keyword` static (`game/effects/
#: registry.py`'s `remove_keyword`, built for Colossus Hammer's own
#: standing version of the same removal) rather than the standing
#: layer-6 grant family — collapses to plain Banding removal, the same
#: "bands with other `<quality>` == banding" simplification the grant
#: side (`static_handlers._quoted_ability_grant_effects_list`) already
#: uses.
_LOSE_BANDING_RE = _c(
    r'target creature loses (?:banding and )?all "bands with other" abilities until end of turn'
)


def _lose_banding(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_until", {
        "static": {"type": "remove_keyword", "params": {"keywords": ["banding"]}},
        "duration": "end_of_turn",
        "target_kind": "creature",
    })]


#: PAR-13's P/T sibling of `_grant_until` — "target creature gets -4/-0
#: until your next turn" (Fungi Cavern/A-Binding Geist/Hag of Inner
#: Weakness/Wasp, Shrinking Savior-shaped; "creatures your opponents
#: control get -3/-0 until your next turn" — Mouth of the Storm — via the
#: same widened `_GROUP`). The `anthem` static (layer 7c) is already the
#: general P/T-delta static every plain pump uses; this is the first
#: oracle-text route to it with a non-end-of-turn duration.
def _pump_until(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    duration = _GRANT_DURATIONS.get(m.group("dur").strip().lower())
    if duration is None:
        return None
    static: dict = {
        "type": "anthem",
        "params": {"power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t"))},
    }
    params: dict = {"static": static, "duration": duration}
    if target_kind:
        params["target_kind"] = target_kind
    else:
        params["target_kind"] = None
        static["params"]["affects"] = selector
    return [EffectSpec("grant_until", params)]


#: MEC-87's permanent sibling of `_pump_until`/`_grant_until` combined —
#: "Target creature gets +2/+2 and gains horsemanship." (Riding the Dilu
#: Horse-shaped, Portal Three Kingdoms' own "This effect lasts
#: indefinitely." reminder text, stripped by `normalize`). No "until …" tail
#: at all: RULE 611.2c's own omitted-duration default is `game/durations.py`'s
#: ``rest_of_game``, not something read off the text — so this is a fixed
#: duration rather than a row in `_GRANT_DURATIONS`. Plain `TARGET` only
#: (not the fuller `_SUBJECT`): no printed card needs the self/group/attached
#: variants of a *permanent* pump-and-grant, and guessing an ``affects``
#: selector for those would be wrong more often than right.
def _pump_and_grant_indefinite(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent")):
        return None
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("grant_until", {
        "static": {
            "type": "anthem",
            "params": {"power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t"))},
        },
        "extra_statics": [{"type": "grant_keyword", "params": {"keywords": keywords}}],
        "duration": "rest_of_game",
        "target_kind": kind,
    })]


#: "{2}{G}, {T}: Target Elf creature gets +2/+2 and has trample for as long as ~ remains tapped." (the
#: Mirage/Alliances tap-to-bestow creatures — Elven/Goblin/Zombie/Wizard/Soldier Cohort-shaped). One
#: `grant_until` carries both statics (the P/T `anthem` and the keyword) on the chosen creature for a
#: RULE 611.2b condition-bounded duration — `_LOCKDOWN_CONDITIONS`' own ``source_tapped``.


def _pump_grant_while_tapped(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    # See `_pump_subtype_target`: the bare `[a-z]+` capture can't tell a subtype from a state word.
    target_text = f"target {m.group('subtype')} creature"
    creature_filter = resolve_target_creature_state_filter(target_text) or {
        "subtype": m.group("subtype").capitalize(),
    }
    return [EffectSpec("grant_until", {
        "static": {
            "type": "anthem",
            "params": {"power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t"))},
        },
        "extra_statics": [{"type": "grant_keyword", "params": {"keywords": keywords}}],
        "duration": "for_as_long_as",
        "condition": {"kind": "source_tapped"},
        "target_kind": "creature",
        "creature_filter": creature_filter,
    })]


#: PAR-13's "can't attack"/"can't block" sibling — "target creature can't
#: attack until your next turn" (Dungeon of the Mad Mage's own Twisted
#: Caverns). The plain, unqualified restriction rides the same synthetic
#: `grant_keyword` flag (`cant_attack`/`cant_block`) its permanent-static
#: cousin uses (`combat_restriction`'s own docstring) — not `_token_
#: keywords`, since these verbs aren't real RULE 702 keyword names.
_CANT_ATTACK_OR_BLOCK_UNTIL_RE = _c(
    rf"{TARGET} can'?t (?P<verb>attack|block) "
    r"(?P<dur>until (?:your next turn|the end of combat|end of combat|"
    r"the beginning of the next end step))"
)


def _cant_attack_or_block_until(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "permanent")):
        return None
    duration = _GRANT_DURATIONS.get(m.group("dur").strip().lower())
    if duration is None:
        return None
    flag = "cant_attack" if m.group("verb") == "attack" else "cant_block"
    return [EffectSpec("grant_until", {
        "static": {"type": "grant_keyword", "params": {"keywords": [flag]}},
        "duration": duration, "target_kind": kind,
    })]


#: "It gains haste until your next turn." (Offspring's Revenge) — the
#: previous-subject sibling of the `_SUBJECT`-anchored `grant_until` row
#: below: the "it" is whatever the preceding clause created/targeted (here,
#: the just-made token copy), so it rides `EffectHandler.previous_subject_
#: only` + `previous_subject: True` exactly like `_lockdown` /
#: `_return_to_hand_previous`, not a fresh `TargetSpec`.
_GRANT_UNTIL_PREVIOUS_RE = _c(
    rf"{_THEN}{_PREVIOUS_SUBJECT} gains? (?P<kw>[a-z, ]+?) "
    r"(?P<dur>until (?:your next turn|the end of combat|end of combat|"
    r"the beginning of the next end step))"
)


def _grant_until_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    duration = _GRANT_DURATIONS.get(m.group("dur").strip().lower())
    if duration is None:
        return None
    return [EffectSpec("grant_until", {
        "static": {"type": "grant_keyword", "params": {"keywords": keywords}},
        "duration": duration,
        "previous_subject": True,
        "target_kind": None,
    })]


#: The lock-down family's own "for as long as <cond>" durations (PAR-11),
#: matched against `game/static_conditions.py`'s vocabulary.
_LOCKDOWN_CONDITIONS: list[tuple[re.Pattern[str], dict]] = [
    (re.compile(r"~ remains tapped", re.I), {"kind": "source_tapped"}),
    (re.compile(r"you control ~", re.I), {"kind": "source_on_battlefield"}),
    (re.compile(r"~ remains on the battlefield", re.I), {"kind": "source_on_battlefield"}),
]


#: "It doesn't untap during its controller's untap step" with no duration of its own — the body of a
#: "for as long as it has a `<counter>` counter on it" lock (`segmenter._for_as_long_as_counter_specs`
#: re-times it). Offered only after a clause that chose the permanent (`previous_subject_only`).
_LOCKDOWN_BARE_RE = _c(r"it doesn'?t untap during its controller'?s untap step")


def _lockdown_bare(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_until", {
        "static": {"type": "no_untap", "params": {}}, "previous_subject": True, "target_kind": None,
    })]


def _lockdown(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"It doesn't untap during its controller's untap step for as long as ~
    remains tapped." (RULE 502.1 + RULE 611.2b — Sand Squid/Ice Floe-shaped.)

    The second sentence of a tap-then-lock ability, so its subject is the
    *previous* clause's target. Composes three pieces that already existed
    separately and had never met: the `previous_subject_only` pronoun, the
    ``no_untap`` static, and this batch's condition-bounded duration — which
    is what made this family unreachable until now (PAR-11).
    """
    condition = next(
        (cond for pattern, cond in _LOCKDOWN_CONDITIONS if pattern.fullmatch(m.group("cond").strip())),
        None,
    )
    if condition is None:
        return None
    return [
        EffectSpec(
            "grant_until",
            {
                "static": {"type": "no_untap", "params": {}},
                "duration": "for_as_long_as",
                "condition": dict(condition),
                "previous_subject": True,
                "target_kind": None,
            },
        )
    ]


# "fateseal N" (RULE 701.29a) — scry on an *opponent's* library. `FateSeal
# Effect` (registered `fateseal`) auto-picks the opponent (first living one,
# a documented simplification like Clash's). The optional leading "you " is
# the redundant subject a trigger body spells out; "you may fateseal N"
# (Mesmeric Sliver's quoted grant) reaches this after `_peel_optional`
# strips the "you may", the ability itself carrying `optional=True`.
def _fateseal(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("fateseal", {"count": int(m.group("n"))})]


# RULE 701.69a "heal all damage from <permanent>" / "damage … dealt to
# <permanent> is healed" — remove all marked damage (`HealEffect` /
# `RulesEngine.heal`). Only ever prints for "all" damage, never "heal N".
# The Wolverine, Fierce Fighter "…is healed" *replacement* clause is a
# separate recognizer (`replacements._HEAL_OTHERS_ON_DAMAGE_RE`).
_HEAL_GROUP_SELECTOR = {
    "each creature you control": "creatures_you_control",
    "creatures you control": "creatures_you_control",
    "each creature": "all_creatures",
    "all creatures": "all_creatures",
}
_HEAL_RE = _c(
    r"(?:heal all damage (?:from|dealt to|marked on)|(?:all )?damage (?:already )?dealt to) "
    r"(?P<who>~|it|this creature|each creature you control|"
    r"creatures you control|each creature|all creatures)"
    r"(?: is healed)?"
)


def _heal(m: re.Match[str]) -> list[EffectSpec]:
    # ~/it/this creature → self (no selector); group phrases → a
    # `group_selector_objects` name. No "target creature" form: no card
    # prints one, and emitting a target-less `heal` would silently claim
    # nothing.
    selector = _HEAL_GROUP_SELECTOR.get(m.group("who").lower())
    return [EffectSpec("heal", {"selector": selector} if selector else {})]


# RULE 701.42a "if you both own and control ~ and a[n] <type> named <X>,
# exile them, then meld them into <Y>." — the body of a meld card's own
# activated ability ({cost}: … , Hanweir Battlements / Urza, Lord Protector)
# or a phase trigger (`segmenter._MELD_TRIGGER_RE` reaches the same builder).
# The leading "if you both own and control" RULE 603.4 gate is dropped:
# `MeldEffect` re-checks own+control of the named partner at resolution and
# fails closed (nothing exiled) if it isn't there, so the outcome is
# identical. Partner/result names carry commas ("Bruna, the Fading Light"),
# so the two are pinned by the fixed ", exile them, then meld them into "
# and end-of-clause anchors.
_MELD_BODY_RE = _c(
    r"if you both own and control ~ and (?:an?|the) [a-z ]*?named (?P<partner>.+?), "
    r"exile them, then meld them into (?P<result>.+?)"
)


def _meld(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("meld", {
        "partner_name": m.group("partner").strip(),
        "result_name": m.group("result").strip(),
    })]


def _scry_or_surveil(m: re.Match[str]) -> list[EffectSpec]:
    # "[you] scry N" (RULE 701.18) / "[you] surveil N" (RULE 701.31) —
    # identical grammar and params, differing only in which verb was
    # matched; the matched word is itself the EffectSpec type string. The
    # optional leading "you " is the redundant subject a trigger body
    # spells out ("whenever enchanted creature attacks, you scry 2" —
    # Psychic Impetus; "then you scry 2" — Overwhelmed Apprentice): scry is
    # always the controller's, so it drops to the same self effect.
    return [EffectSpec(m.group("verb"), {"count": count_or_x_of(m.group("n"))})]


#: "Look at the top N cards of your library, then put them back in any
#: order." (Sensei's Divining Top/Sylvan Library-shaped, RULE 701.18's own
#: unabbreviated old-templating spelling — ~27 cache-wide cards) — this
#: engine's non-interactive `scry(N)` resolution already covers every
#: legal outcome of "put them back in any order" (Ponder's own existing
#: entry documents why), so it's the same `"scry"` EffectSpec, just a
#: different printed phrasing reaching it.
#: Since the target form ("look at the top 3 cards of target player's library", Elemental Augury /
#: Architects of Will) arrived, both are `LookReorderTopEffect` — scry minus the bottom option, which
#: the printed text never offered. ``x`` takes its value from a "where x is …" tail like any X clause.
_LOOK_TOP_REORDER_RE = _c(
    rf"look at the top (?P<n>\d+|x) cards? of (?:(?P<owner>your)|target player's) library, "
    r"then put (?:it|them) back in any order"
    # "You may shuffle." / "You may have that player shuffle." (Omen, Pondering Mage, Natural Selection, Portent).
    r"(?:\.\s*you may (?P<shuffle>shuffle|have that player shuffle))?"
)


def _look_top_reorder(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    count: object = "x" if m.group("n") == "x" else int(m.group("n"))
    params: dict = {"count": count}
    if not m.group("owner"):
        params["target_kind"] = "player"
    if m.group("shuffle"):
        # "shuffle" is the looker's own library, "have that player shuffle" the target's: each must name its owner.
        if (m.group("shuffle") == "shuffle") != bool(m.group("owner")):
            return None
        params["may_shuffle"] = True
    return [EffectSpec("look_reorder_top", params)]


def _proliferate(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("proliferate", {})]


#: "double the number of [+1/+1 / each kind of] counter(s) on <object>."
#: (RULE 701.19-adjacent — Primordial Hydra / Tanazir Quandrix / Kalonian
#: Hydra / Bristly Bill / Growth Curve / Dragonsguard Elite / Vorel). Four
#: subject shapes, each its own `DoubleCountersOnTargetEffect.mode`:
#:   * "~"                                    → ``mode="self"``
#:   * "target creature [you control]"        → ``mode="target"`` (RULE 115)
#:   * "each creature you control"             → ``mode="each_you_control"``
#:   * "it" / "that creature"                  → ``mode="previous_subject"``
#: A "+1/+1" (or other named kind) narrows the doubling; bare "each kind
#: of" / "the" doubles every kind (Vorel).
_DOUBLE_COUNTERS_RE = _c(
    r"double the number of (?:each kind of |(?P<kind>\+1/\+1|-1/-1|[a-z]+) )?counters? on "
    r"(?P<subject>~|it|that creature|target creature(?: you control)?|"
    r"each creature you control|each of those creatures)"
)


def _double_counters(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subj = m.group("subject").strip()
    params: dict = {}
    if m.group("kind"):
        params["kind"] = m.group("kind")
    if subj == "~":
        params["mode"] = "self"
    elif subj in ("it", "that creature", "each of those creatures"):
        params["mode"] = "previous_subject"
    elif subj == "each creature you control":
        params["mode"] = "each_you_control"
    elif subj.startswith("target creature"):
        params["mode"] = "target"
        params["target_kind"] = "creature_you_control" if "you control" in subj else "creature"
    else:
        return None
    return [EffectSpec("double_counters_on_target", params)]


#: "Damage can't be prevented this turn." (RULE 615.6 — Flaring Pain, the
#: back half of Insult // Injury, Fear Fire Foes) — untargeted, turn-scoped;
#: `DisableDamagePreventionEffect` / `RulesEngine.disable_damage_prevention_
#: this_turn` already existed for hand-authored cards, this is the first
#: oracle-text route to it. The bare word "damage" only (a leading "combat"
#: is a narrower, static, combat-only shape this effect doesn't model).
_DISABLE_DAMAGE_PREVENTION_RE = _c(r"damage can'?t be prevented this turn")


def _disable_damage_prevention(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("disable_damage_prevention", {})]


#: "proliferate twice" (Contagion Engine/Agent Frank Horrigan/Ezuri, Stalker
#: of Spheres) / "proliferate N times" (War of the Spark's Saga chapter —
#: normalize.py folds spelled-out numbers to digits, but not "twice", so
#: that's matched as its own literal word). A bare "proliferate x times"
#: (Expansion Algorithm's spell-announced-X, Tromell's dynamic
#: count-selector) stays unclaimed — a different shape (`ProliferateEffect`
#: has no "x"/count-selector support), not this literal-count one.
def _proliferate_n_times(m: re.Match[str]) -> list[EffectSpec]:
    times = 2 if m.group("n") is None else int(m.group("n"))
    return [EffectSpec("proliferate", {"times": times})]


#: "remove all counters from all permanents" (RULE 122 — Oblivion Stone/
#: Aether Snap/Thief of Blood-shaped, untargeted board wipe of counters).
def _remove_counters_all_permanents(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_counters", {})]


#: "remove all counters from target permanent" (Vampire Hexmage-shaped).
def _remove_counters_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_counters", {"target_kind": "permanent"})]


#: "Remove all `<kind>` counters from ~." (Coalition Relic/Ventifact
#: Bottle, PAR-66) — untargeted (the ability names its own source, RULE
#: 115 never applies), and restricted to one named counter kind so an
#: unrelated counter type on the same permanent survives. Reuses
#: `_NAMED_COUNTER_KIND` (the same open-minus-reserved kind axis `_add_named_
#: counter` uses) plus the `+1/+1`/`-1/-1` P/T shape.
_REMOVE_ALL_NAMED_COUNTERS_SELF_RE = _c(
    rf"remove all (?P<ckind>{_NAMED_COUNTER_KIND}|[+\-−]1/[+\-−]1) "
    rf"counters? from {_SELF_SUBJECT}"
)


def _remove_all_named_counters_self(m: re.Match[str]) -> list[EffectSpec]:
    ckind = m.group("ckind")
    kind = "+1/+1" if ckind[0] in "+" else ("-1/-1" if ckind[0] in "-−" else ckind)
    return [EffectSpec("remove_counters", {"self_only": True, "kind": kind})]


#: "remove up to N counters from target permanent/creature/…" (Glissa
#: Sunslayer/Heartless Act/Render Inert-shaped) — a genuinely different,
#: interactive chosen-*amount* shape from the bare "remove all counters"
#: above (`RemoveCountersEffect`'s ``max_count``). Digits only —
#: `normalize.py` already folds spelled-out numbers ("up to three" → "up to
#: 3"). Embeds the shared `TARGET` sub-grammar (PAR-2) rather than a
#: hand-rolled "permanent|creature" alternation, so Price of Betrayal's
#: "target artifact, creature, planeswalker, or opponent" — a player
#: alongside three permanent types, `targeting.
#: artifact_creature_planeswalker_or_opponent` — is claimed the same way
#: any other TARGET-shaped clause is.
_REMOVE_COUNTERS_CHOICE_RE = _c(
    rf"remove up to (?P<n>\d+) counters? from {TARGET}"
)


def _remove_counters_choice(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec(
        "remove_counters", {"target_kind": kind, "max_count": int(m.group("n"))},
    )]


# "You may play [up to] N additional land(s) this turn."  (RULE 305.2
# one-turn permission, Explore/Escape to the Wilds/Kiora's -1-shaped) — the
# resolve-time, single-turn sibling of the standing `extra_land_drop` static
# `catalogue.static_handlers` recognises for a permanent's own printed
# ability ("…on each of your turns"); this shape only ever appears as a
# clause in a spell/ability's effect body, never a permanent's standing text.
# "You may " is optional here: when this is the *only* clause in the body,
# `segmenter.segment_line`'s `_peel_optional` already stripped a leading
# "you may " before this ever runs (Summer Bloom-shaped); when it trails an
# earlier clause ("Draw a card. You may play …", Explore/Urban Evolution-
# shaped) it's still there in the text this handler sees.
_EXTRA_LAND_PLAY_RE = _c(rf"(?:you may )?play (?:up to )?{COUNT} additional lands? this turn")


def _extra_land_play(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("extra_land_play", {"count": count_of(m.group("n"))})]


# RULE 701.40a manifest / RULE 701.58a cloak — "manifest the top card of your
# library" and its "the top N cards" plural, plus cloak's identical shape
# (the only difference is ward {2} on the resulting permanent, carried as the
# effect's ``kind``). "Manifest dread" (RULE 701.40a plus a look-at-two
# chooser) is a separate handler since it isn't a count at all.
def _manifest(m: re.Match[str]) -> list[EffectSpec]:
    kind = "cloak" if m.group("verb").lower() == "cloak" else "manifest"
    return [EffectSpec("manifest", {"count": count_of(m.group("n") or "a"), "kind": kind})]


def _manifest_dread(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("manifest_dread", {})]


#: PAR-111: "manifest dread, then attach ~ to that creature." (the Duskmourn Equipment cycle — Conductive Machete,
#: Cursed Windbreaker, Dissection Tools, Killer's Mask) — the manifested permanent is "that creature", handed to
#: `AttachEffect`'s ``created`` mode through `GameContext.created_objects` (`ManifestDreadEffect`, and the
#: suspended remainder when the look-at-two choice pauses the resolution).
_MANIFEST_DREAD_THEN_ATTACH_RE = _c(r"manifest dread, then attach (?:~|it|this [a-z]+) to that creature")


def _manifest_dread_then_attach(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("manifest_dread", {}), EffectSpec("attach", {"target_kind": "created"})]


#: RULE 601.2f for the rest of the turn: "spells you cast this turn that are
#: black and/or red cost {X} less to cast, where X is …" (Rowan/Will, Scion
#: of …) and "the next instant or sorcery spell you cast this turn costs {1}
#: less to cast" (Hardened Berserker, Kaza, Spellbinding Soprano).
_REDUCE_COSTS_COLORS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
_REDUCE_COSTS_THIS_TURN_RE = _c(
    r"(?P<next>the next )?(?P<types>instant or sorcery |instant and sorcery |face-down |)"
    r"spells? you cast this turn(?: that (?:is|are) (?P<c1>white|blue|black|red|green)"
    r"(?: and/or (?P<c2>white|blue|black|red|green))?)? costs? \{(?P<n>\d+|x)\} less to cast"
    r"(?:, where x is (?P<x>.+?)(?: as this ability resolves)?)?"
)


def _reduce_costs_this_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .count_phrase import parse_amount_phrase  # function-scoped, as elsewhere here

    params: dict[str, Any] = {"next_only": bool(m.group("next"))}
    types = m.group("types").strip()
    if types == "face-down":
        params["face_down"] = True
    elif types:
        params["spell_type"] = ["instant", "sorcery"]
    colors = [_REDUCE_COSTS_COLORS[c] for c in (m.group("c1"), m.group("c2")) if c]
    if colors:
        params["spell_colors"] = colors
    if m.group("n") != "x":
        if m.group("x"):
            return None
        return [EffectSpec("reduce_spell_costs_this_turn", {**params, "amount": int(m.group("n"))})]
    phrase = (m.group("x") or "").strip()
    if phrase == "~'s power":
        amount: dict[str, Any] = {"kind": "characteristic", "characteristic": "power", "of": "source"}
    else:
        selector = parse_amount_phrase(phrase)
        if selector is None:
            return None
        amount = {"kind": "count_selector", "selector": selector}
    return [EffectSpec("bind", {"name": "n", "amount": amount, "effects": [
        EffectSpec("reduce_spell_costs_this_turn", {**params, "amount": "$n"}).to_dict(),
    ]})]


# RULE 708.8 by an effect, untargeted: "you may turn a permanent you control
# face up" (Zimone) / "… a face-down creature you control face up".
def _turn_face_up_chosen(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("turn_face_up_chosen", {
        "optional": bool(m.group("may")),
        "creature_only": m.group("what") == "face-down creature",
    })]


# "Venture into the dungeon." (RULE 701.49) and its RULE 701.49d "venture
# into [quality]" variant ("venture into Undercity") — the named form keeps
# the dungeon's name as a param, which is what `RulesEngine.
# venture_into_the_dungeon` uses to skip the RULE 309.2a choice.
def _venture(m: re.Match[str]) -> list[EffectSpec]:
    named = (m.groupdict().get("dungeon") or "").strip()
    params: dict = {}
    if named and named != "the dungeon":
        # `normalize` lowercases, so the catalogue lookup is case-folded too.
        params["dungeon"] = named
    return [EffectSpec("venture", params)]


# "Monstrosity 3." (RULE 701.37a) and "Monstrosity X." — always the body of
# the permanent's own activated ability, so there is nothing to target and
# nothing to scope; the whole clause is its amount. "X" is passed through as
# the ``"x"`` sentinel `RulesEngine._substitute_x` rewrites with the announced
# {X} at resolution, which is also what RULE 701.37c's "other abilities may
# refer to that X" reads back.
def _monstrosity(m: re.Match[str]) -> list[EffectSpec]:
    raw = m.group("n")
    return [EffectSpec("monstrosity", {"amount": "x" if raw == "x" else int(raw)})]


# "Adapt 2." (RULE 701.46a) — monstrosity's sibling, gated on the creature's
# own +1/+1 counters rather than a designation. No real adapt card prints
# "adapt X", so this stays a literal (fail-closed: an "adapt X" would leave
# its card UNMODELED rather than silently adapting 0).
def _adapt(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("adapt", {"amount": int(m.group("n"))})]


# "Harness ~." (MEC-79 / RULE 701.64a) — the Marvel Infinity Stones' activated
# body. 701.64a only ever spells the self form ("[this permanent]"), and every
# printing names itself, so after `normalize` folds the card name this is just
# "harness ~" (or the rules-literal "harness this permanent"). No params — the
# designation flip is the whole effect.
def _harness(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("harness", {})]


# RULE 701.50d's optional "connives X, where X is …" tail, embedded at the
# end of every connive verb form below. Two readings: a firing trigger's own
# event field ("the amount of damage it dealt to that player", Mask of the
# Schemer — `GameContext.trigger_event`, the `DealDamageEffect.
# amount_from_trigger_event` idiom) or a live board count (`{DEVOTION}`'s
# "the number of attacking creatures"/"creatures that died this turn").
_CONNIVE_AMOUNT = (
    r"(?: x, where x is (?:"
    r"(?P<connive_damage>the amount of damage it dealt to that player)"
    rf"|{DEVOTION}"
    r"))?"
)


# "~ connives[ X]." / "it connives[ X]." (RULE 701.50a/d, PAR-29) — the
# conniving permanent is the ability's own source (`self.source`, including
# a triggered ability whose subject was retargeted onto e.g. an attached
# permanent before this builder ever sees it). Two subjects: the explicit
# self ("~ connives", an activated ability's body or a self-subject trigger
# where `normalize` kept the card name) and the "it/he/she" pronoun of a
# self-subject trigger ("when ~ enters, it connives", `self_subject_only`).
# A pronoun bound to an *earlier clause's* target ("target Villain you
# control gains menace. It connives.", Doctor Doom) is deliberately left
# unclaimed — the bare-self row would connive the wrong permanent; that
# needs `_connive_previous` below instead, and no real card in the cache
# pairs that exact pronoun shape with a *target* antecedent yet.
# "connives X, where X is …" (RULE 701.50d) is `_CONNIVE_AMOUNT`'s optional
# tail, shared by every connive row in this family — a literal repeat count
# never appears on a real card (only "connives" or "connives X"), so there
# is no plain-integer form to parse.
def _connive_amount_params(m: re.Match[str]) -> dict:
    if m.groupdict().get("connive_damage"):
        return {"times_from_trigger_event": "amount"}
    selector = devotion_selector(m)
    if selector:
        return {"times_from_count_selector": selector}
    return {}


def _connive(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("connive", _connive_amount_params(m))]


# "target creature [you control/an opponent controls] connives[ X]" (RULE
# 601.2c targeting on 701.50a) and "that creature connives" — the two
# subject shapes `_goad`/`_explore` already established, adapted for
# connive. Only a creature-shaped target row is meaningful (RULE 701.47's
# "permanent" is narrowed to creatures by every printed connive card);
# anything else leaves the clause unclaimed rather than conniving the wrong
# kind of object.
_CONNIVE_TARGET_KINDS = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control"}
)


def _connive_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _CONNIVE_TARGET_KINDS):
        return None
    params: dict = {"target_kind": kind, **_optional_param(m), **_connive_amount_params(m)}
    # "target attacking creature connives X" (Raffine, Scheming Seer) — see
    # `_destroy`'s own comment: `resolve_target_kind` alone drops the
    # qualifier. `ConniveEffect.creature_filter` is new alongside this fix.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("connive", params)]


def _connive_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("connive", {"previous_subject": True, **_connive_amount_params(m)})]


# "Each of X target creatures you control connive." (Change of Plans) — the
# spell's own announced {X} (`GameObject.x_paid`), the same
# `count_selector="source_x_paid"` reading March of Swirling Mist's "up to X
# target creatures phase out" already uses.
def _connive_each_x(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("connive", {
        "target_kind": "creature_you_control", "count_selector": "source_x_paid", "optional": True,
    })]


# "Recruit." (RULE 701.70a — Tales of Middle-earth: "draw a card, then
# discard a card. If you discarded a nonland card, create a 1/1 white
# Human Soldier creature token."). Bare word only — every real card says
# just "recruit" (as an ETB or attack trigger's whole body).
# `RulesEngine.recruit` / `effects.RecruitEffect` (registered as ``recruit``).
def _recruit(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("recruit", {})]


# "Learn." (RULE 701.48a — Strixhaven). Bare word only — every real card
# says just "learn." (as a spell effect, or an ETB/dies/activated-ability
# body). `RulesEngine.learn` / `effects.LearnEffect` (registered as
# ``learn``) — the "Lesson from outside the game" branch is dropped (no
# sideboard), so it collapses to an optional discard-a-card-then-draw.
def _learn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("learn", {})]


# "You may collect evidence N." (RULE 701.59a, PAR-29) with no "if you do"
# rider — Corpseberry Cultivator / Evidence Examiner / Surveillance Monitor
# each print it as a bare optional cost whose *only* payoff is the separate
# "whenever you collect evidence, …" trigger firing. Modeled as
# `pay_cost_then` with an empty effect list (an optional cost payment,
# nothing else); `RulesEngine.collect_evidence` fires
# `EventType.COLLECTED_EVIDENCE` when paid.
def _collect_evidence_bare(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pay_cost_then", {
        "cost": f"collect evidence {m.group('n')}",
        "effects": [],
    })]


# Bare "collect evidence N" (RULE 701.59a) — what's left after the segmenter
# peels a triggered ability's outer "you may " (`AbilitySpec.optional`).
# `CollectEvidenceEffect` (registered as ``collect_evidence``) does the
# exile + `EventType.COLLECTED_EVIDENCE`; the peeled "you may" carries the
# optionality.
def _collect_evidence(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("collect_evidence", {"amount": int(m.group("n"))})]


# "You may forage." (RULE 701.61a, PAR-29) with no "if you do" rider —
# Corpseberry Cultivator: a bare optional cost whose only payoff is the
# separate "whenever you forage, …" trigger. `pay_cost_then` with an empty
# effect list, same shape as `_collect_evidence_bare`.
def _forage_bare(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pay_cost_then", {"cost": "forage", "effects": []})]


# Bare "forage" — what's left after the segmenter peels a triggered
# ability's outer "you may ". `ForageEffect` (registered as ``forage``).
def _forage(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("forage", {})]


# "Discover N." (RULE 701.57a) — exile from the top of your library until a
# nonland card with mana value N or less, free-cast it or put it in hand,
# rest to the bottom. `effects.DiscoverEffect` (registered as ``discover``,
# a sibling of Cascade) already does all of it; only the parser row was
# missing. Literal N only: "discover X, where X is <count-selector>"
# (Pantlaza/Aloy/…) is a dynamic amount `DiscoverEffect` can't take yet, so
# it stays UNMODELED (fail-closed) rather than discovering 0.
def _discover(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discover", {"mana_value": int(m.group("n"))})]


#: PAR-71: "discover X, where X is that spell's mana value." (Monstrous
#: Vortex's cast trigger) — `DiscoverEffect.mana_value_from_trigger_event`,
#: the discover-cap sibling of `_pump_mana_value`/`_mill_spell_mv`. "Counter
#: target artifact or creature spell. Discover X, where X is that spell's
#: mana value." (Hurl into History) prints the identical tail but "that
#: spell" there is the *countered* target, not a cast-trigger event —
#: `context.trigger_event` is `None` for a plain resolving spell, so this
#: row alone would silently discover 0; its own `previous_subject_only`
#: sibling right below (offered only when `segmenter.
#: _announces_creature_target` sees a preceding ``counter`` spec, widened
#: for exactly this shape) claims that case correctly instead.
def _discover_spell_mv(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discover", {"mana_value_from_trigger_event": "mana_value"})]


#: The "counter target spell. `<effect>`, where X is that spell's mana
#: value" cluster's shapes (Hurl into History/Access Denied/Spell Swindle/
#: Overwhelming Intellect) — "that spell" is the countered RULE 115 target,
#: read via `GameContext.previous_targets`/`_characteristic_of_subject`'s
#: ``"previous_subject_mana_value"`` (RULE 608.2h last-known information:
#: the countered spell is in a graveyard, with no controller, by the time
#: this clause resolves) rather than a `SPELL_CAST` trigger event, since
#: there isn't one. Each row below is ``previous_subject_only`` for exactly
#: the reason `_discover_spell_mv`'s own docstring documents: the identical
#: printed tail also appears after a genuine cast trigger, where this
#: referent would be wrong.
def _discover_spell_mv_previous_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discover", {"mana_value_from_subject": "previous_subject_mana_value"})]


#: "Draw cards equal to that spell's mana value." (Overwhelming Intellect) —
#: the `draw`-spec sibling, `DrawCardEffect.amount_from_subject` (the same
#: field `_draw_eq_its_self` already reads for other referents).
def _draw_spell_mv_previous_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {"amount_from_subject": "previous_subject_mana_value"})]


#: "Create X 1/1 colorless Thopter artifact creature tokens with flying,
#: where X is that spell's mana value." (Access Denied) — the inline-stats
#: token count, `CreateTokenEffect.count_from_subject` (the same field
#: `AddCountersEffect`/`CreateTokenEffect` already read for other
#: ``"<who>_<char>"`` referents), reusing `_xx_token_mid_params`'s shared
#: colour/subtype/keyword-word splitting.
_CREATE_TOKEN_XX_SPELL_MV_PREVIOUS_TARGET_RE = _c(
    r"create x (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z, ]+))?, where x is that spell'?s mana value"
)


def _create_token_xx_spell_mv_previous_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    params.update({
        "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_from_subject": "previous_subject_mana_value",
    })
    if m.groupdict().get("tapped"):
        params["tapped"] = True
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    return [EffectSpec("create_token", params)]


#: "Create X Treasure tokens, where X is that spell's mana value." (Spell
#: Swindle) — the named-token sibling of the row just above.
_CREATE_NAMED_TOKEN_XX_SPELL_MV_PREVIOUS_TARGET_RE = _c(
    rf"create x (?P<name>{'|'.join(_NAMED_TOKEN_WORDS)}) tokens?, "
    r"where x is that spell'?s mana value"
)


def _create_named_token_xx_spell_mv_previous_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_token", {
        "token_name": _NAMED_TOKEN_WORDS[m.group("name")],
        "count_from_subject": "previous_subject_mana_value",
    })]


# "<permanent> explores." (RULE 701.44) — `RulesEngine.explore` owns the
# whole procedure (reveal top card; land → hand, else +1/+1 counter + a
# "may bin it" choice). Same three subject shapes as `_goad`/`_connive`:
#   • "~ explores" / "it/he/she explores" — the ability's own source, i.e.
#     "when ~ enters, it explores" (the 15-card bulk of the mechanic);
#   • "that creature explores" — a creature an earlier clause chose
#     (`previous_subject_only`, e.g. "return target creature card … that
#     creature explores");
#   • "target creature [you control] explores" — off the shared TARGET rows.
# "explores, then it explores again" (Defossilize) and "each Merfolk you
# control explores" (a mass selector) stay unclaimed — different shapes.
def _explore_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("explore", {})]


def _explore_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("explore", {"previous_subject": True})]


def _explore_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None  # only a creature explores on a real card (RULE 701.44)
    return [EffectSpec("explore", {"target_kind": kind, **_optional_param(m)})]


# "<permanent> endures N." (RULE 701.63a — Bloomburrow): its controller
# either puts N +1/+1 counters on it or creates an N/N white Spirit token.
# `RulesEngine.endure` / `effects.EndureEffect` (registered as ``endure``)
# own the modal choice. Same subject shapes as `_explore`:
#   • "~ endures N" / "it endures N" — the ability's own source (the bulk:
#     "when ~ enters, it endures 3");
#   • "that creature endures N" — a previous clause's pick;
#   • "target creature you control endures N" — off the shared TARGET rows.
# The "you may pay {cost}. If you do, it endures N" wrapper (Descendant of
# Storms) is a separate pay-cost-then build. Literal N only.
def _endure_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("endure", {"amount": int(m.group("n"))})]


# "~ endures x" (PAR-29, Krumar Initiate) — X is the activated ability's own
# announced/paid {X}, the plain ``"x"`` sentinel `RulesEngine._substitute_x`
# already resolves generically on any effect's ``amount`` attribute.
def _endure_self_x(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("endure", {"amount": "x"})]


def _endure_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("endure", {"amount": int(m.group("n")), "previous_subject": True})]


def _endure_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None
    return [EffectSpec("endure", {
        "amount": int(m.group("n")), "target_kind": kind, **_optional_param(m),
    })]


# "Populate[ X times]." (RULE 701.36a, PAR-29) — put a token onto the
# battlefield that's a copy of a creature token you control. `RulesEngine.
# populate` owns the procedure (and the "which token?" choice);
# `effects.PopulateEffect` is registered as ``populate``. Never a target or
# a pronoun subject. "X times" (Full Flowering) rides the plain ``"x"``
# sentinel `RulesEngine._substitute_x` already resolves generically on any
# effect's ``count`` — no dynamic-amount plumbing needed here.
def _populate(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("populate", {})]


def _populate_x_times(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("populate", {"count": "x"})]


# "You control target opponent during that player's next turn." (RULE 720,
# MEC-51) — Mindslaver / Worst Fears / Sorin Markov's −7 / Emrakul the
# Promised End's cast trigger; "…during their next combat phase." (Secret
# of Bloodbending) is the ``scope="combat"`` form. `effects.
# ControlPlayerEffect` installs a `GameState.TurnControl` and `services/
# game_session.py` routes the controlled seat's decisions/priority to the
# controller for the window. "you gain control of" is an equivalent
# wording. Riders the segmenter splits off stay UNMODELED, fail-closed
# (Emrakul's own "after that turn, that player takes an extra turn" tail is
# hand-authored on the card, not reached here).
_CONTROL_PLAYER_RE = _c(
    r"you (?:gain )?control(?: of)? target (?P<who>opponent|player) during "
    r"(?:that player's|their) next (?P<scope>turn|combat phase)"
)


def _control_player(m: re.Match[str]) -> list[EffectSpec]:
    scope = "combat" if m.group("scope") == "combat phase" else "turn"
    return [EffectSpec("control_player", {
        "scope": scope,
        "target_kind": "opponent" if m.group("who") == "opponent" else "player",
    })]


# "Take an extra turn after this one." (RULE 500.7, PAR-30) — the plain
# Time Walk / Temporal Manipulation / Capture of Jingzhou body, and the
# modelable half of Plea for Power's vote outcome. `effects.TakeExtraTurn
# Effect` (registered ``take_extra_turn``) queues the effect's controller
# onto `GameState.extra_turns`; `GameEngine.begin_turn` takes it right
# after the current turn. No target, no pronoun subject. "one" normalises
# to "1"; a leading "you " (Mu Yanling) is the same controller-scoped
# action. Riders the segmenter splits off stay UNMODELED, fail-closed:
# "skip the untap step of that turn" (Savor the Moment), "during that
# turn, damage can't be prevented" (Alchemist's Gambit), "at the beginning
# of that turn's end step, you lose the game" (Last Chance). "…for each
# coin that comes up heads" / "…if an opponent cast a blue spell this
# turn" don't fullmatch this row either — those keep their own count /
# condition and are their own tickets.
_TAKE_EXTRA_TURN_RE = _c(r"(?:you )?take an extra turn after this 1")


def _take_extra_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("take_extra_turn", {})]


# "Incubate N." (RULE 701.53, PAR-29) — create an Incubator token (a
# power/toughness-less colourless artifact token) with N +1/+1 counters on
# it. No new engine primitive: the `Incubator` catalogue entry
# (`card_registry/red_spells.py`) already binds "{2}: Transform this
# token" (→ a 0/0 Phyrexian artifact creature) onto every token so named,
# and `create_token`'s `extra_counters` places the counters — the exact
# spec shape Glissa, Herald of Predation's hand-authored entry already
# emits. "You incubate N" (a "when you do" continuation) is the same
# action, "you" subject and all. The dynamic "incubate X, where X is …"
# form needs `extra_counters` to take a count-selector/`"x"` sentinel — a
# follow-up, tracked in BACKLOG.
def _incubate(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_token", {
        "count": 1,
        "token_name": "Incubator",
        "extra_counters": {"kind": "+1/+1", "count": int(m.group("n"))},
    })]


#: "Incubate X, where X is `<count>`." / "Incubate X twice, where X is
#: `<count>`." (PAR-30) — the dynamic-amount sibling of `_incubate`. "Twice"
#: makes two Incubator tokens (each with X counters), which is exactly
#: `create_token`'s own ``count`` — one Incubator per repetition. The X
#: vocabulary is a small closed map onto `continuous.count_selector` plus
#: the firing spell's mana value (`CreateTokenEffect.extra_counters`'
#: new ``count_from_count_selector`` / ``count_from_trigger_event`` keys).
#: "…where X is **its power**" (Bloated Processor, Furnace Gremlin — a
#: "when ~ dies" trigger) reads the dying creature's own last-known power
#: off the DIES event's snapshotted ``power`` field (RULE 400.7 / 603.6e),
#: the same firing-event idiom `EarthbendEffect.amount_from_trigger_event`
#: uses for "earthbend X, where X is that creature's power".
#:
#: "**Its controller** incubates X, where X is **its mana value**" (Excise
#: the Imperfect — the "its" is the just-exiled previous target, already
#: gone: RULE 608.2h last-known info) → `create_token`'s
#: ``creators="previous_target_controller"`` + ``extra_counters``'
#: ``count_from_subject="previous_subject_mana_value"``.
#:
#: "…where X is the number of creatures **exiled this way**" (Sunfall) →
#: ``extra_counters``' ``count_from_context="objects_exiled_this_way"``
#: (`GameContext`'s exile-count accumulator, sibling of
#: `permanents_destroyed_this_way`).
#:
#: Still UNMODELED, fail-closed: "incubate N **that many times**"
#: (Phyrexian Incubator — a search-result count across a `pending_choice`
#: suspension) and "incubate N **X times**" reading a source's own
#: ``x_paid`` (Progenitor Exarch, an {X}{X} creature — also blocked on its
#: "transform target Incubator token" ability).
_INCUBATE_X_SELECTORS: dict[str, str] = {
    "the number of lands you control": "lands_you_control",
    "the number of creature cards in your graveyard": "creature_cards_in_your_graveyard",
}
_INCUBATE_X_ALT = "|".join(re.escape(p) for p in _INCUBATE_X_SELECTORS)
_INCUBATE_X_RE = _c(
    r"(?:you |(?P<prev_ctrl>its controller ))?incubates? x(?: (?P<twice>twice))?, where x is "
    r"(?:(?P<selector>" + _INCUBATE_X_ALT + r")"
    r"|(?P<spell_mv>that spell'?s mana value)"
    r"|(?P<its_power>its power)"
    r"|(?P<its_mv>its mana value)"
    r"|(?P<exiled_this_way>the number of creatures exiled this way))"
)


def _incubate_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    extra: dict[str, Any] = {"kind": "+1/+1"}
    params: dict[str, Any] = {
        "count": 2 if m.group("twice") else 1,
        "token_name": "Incubator",
    }
    if m.group("its_power"):
        # "when ~ dies, incubate X, where X is its power" — the DIES event
        # carries the dying object's ``power`` snapshotted before the move
        # (RULE 400.7); read it fresh at resolve time exactly like the
        # "that spell's mana value" branch reads the firing event.
        extra["count_from_trigger_event"] = "power"
    elif m.group("its_mv"):
        # "its controller incubates X, where X is its mana value" (Excise
        # the Imperfect) — "its" = the just-exiled previous target (RULE
        # 608.2h last-known info).
        extra["count_from_subject"] = "previous_subject_mana_value"
    elif m.group("exiled_this_way"):
        extra["count_from_context"] = "objects_exiled_this_way"
    elif m.group("spell_mv"):
        extra["count_from_trigger_event"] = "mana_value"
    else:
        selector = _INCUBATE_X_SELECTORS.get(m.group("selector"))
        if selector is None:
            return None  # fail closed — an X phrasing we don't model
        extra["count_from_count_selector"] = selector
    if m.group("prev_ctrl"):
        params["creators"] = "previous_target_controller"
    params["extra_counters"] = extra
    return [EffectSpec("create_token", params)]


# "Clash with an opponent." / "Clash with defending player." (RULE 701.30,
# PAR-29) — reveal the top card of your (and one opponent's) library;
# `RulesEngine.clash` / `effects.ClashEffect` (registered as ``clash``) own
# the procedure and RULE 701.30d win check. The "if you win, `<effect>`. /
# otherwise, `<effect>`." branch is a *separate* condition-gated spec
# (`segmenter._IF_YOU_WIN_CLASH_RE` / `_OTHERWISE_CLASH_RE`), so this
# handler is only the clash itself — a bare "clash with defending player."
# (Marvo, Deep Operative) with no branch at all is the whole clause.
def _clash(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("clash", {})]


# RULE 706.1: "Roll a d20." / "Roll a six-sided die." / "Roll two d6." —
# `RulesEngine.roll_die` / `effects.RollDieEffect` (registered as
# ``roll_die``) own the roll, the `EventType.DICE_ROLLED` firing and RULE
# 706.3a's optional results table (attached by `gate._split_dice_table_
# block`, never by this bare-clause handler). This handler is only the roll
# itself — the whole clause for a card that rolls and then reads the result
# in a *separate* sentence (Barbarian Class' "+2/+0" tail is its own
# `whenever you roll` trigger), or as an activated/ETB body the ordinary
# `<cost>:`/`when ~ enters,` wrappers pick up once the roll parses.
_DICE_COUNT_WORDS = {"a": 1, "two": 2, "three": 3, "2": 2, "3": 3}
_ROLL_DIE_RE = _c(
    r"roll (?:a|(?P<c>two|three|\d+)) "
    r"(?:d(?P<sides_d>\d+)|(?P<sides_s>\d+)-sided (?:die|dice))"
)


def _roll_die(m: re.Match[str]) -> list[EffectSpec]:
    sides = int(m.group("sides_d") or m.group("sides_s"))
    count = _DICE_COUNT_WORDS.get((m.group("c") or "a").lower())
    if count is None:  # a spelled count outside the small known set — fail closed
        return None
    params: dict = {"sides": sides}
    if count != 1:
        params["count"] = count
    return [EffectSpec("roll_die", params)]


# --- MEC-50: Clash (RULE 701.30) win/otherwise-branch bodies. Each is the
# `<rest>` a `segmenter._IF_YOU_WIN_CLASH_RE` / `_OTHERWISE_CLASH_RE` peel
# hands to `parse_effect_body`; the segmenter re-wraps the result with
# `condition={"clash_won": True/False}`, so these builders emit the bare
# effect only. -----------------------------------------------------------------

#: "…If you win, **that spell's controller** mills four cards." (Broken
#: Ambitions) — "that spell" is the countered spell an earlier clause of
#: this same resolution targeted (`GameContext.previous_targets[0]`, now in
#: a graveyard, RULE 608.2h last-known — `MillEffect.selector=
#: "previous_subject_controller"` reads its `owner_id`).
_MILL_PREV_SPELL_CONTROLLER_RE = _c(
    r"that spell'?s controller mills (?P<n>\d+) cards?"
)


def _mill_prev_spell_controller(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {
        "count": int(m.group("n")), "selector": "previous_subject_controller",
    })]


#: "Otherwise, **that player** discards a card." (Pulling Teeth) — "that
#: player" is the same player an earlier clause RULE 115-targeted
#: (`DiscardEffect.previous_subject`, reads `GameContext.previous_targets[0]`,
#: a `Player`).
_THAT_PLAYER_DISCARDS_RE = _c(
    r"that player discards (?P<n>a|\d+) cards?(?P<at_random> at random)?"
)


def _that_player_discards(m: re.Match[str]) -> list[EffectSpec]:
    n = m.group("n")
    params: dict = {"count": 1 if n == "a" else int(n), "previous_subject": True}
    if m.groupdict().get("at_random"):
        params["random"] = True
    return [EffectSpec("discard", params)]


#: "If you win, **gain control of enchanted creature**. Otherwise, **that
#: player gains control of enchanted creature**." (Captivating Glance) — an
#: indefinite control change of this Aura's host
#: (`GainControlAttachedEffect`); recipient is the ability's controller
#: (win) or `GameContext.clashed_opponent` (otherwise).
_GAIN_CONTROL_ATTACHED_RE = _c(
    r"(?P<who>you gain|gain|that player gains) control of enchanted creature"
)


def _gain_control_attached(m: re.Match[str]) -> list[EffectSpec]:
    recipient = "clashed_opponent" if m.group("who") == "that player gains" else "controller"
    return [EffectSpec("gain_control_attached", {"recipient": recipient})]


#: "If you win, **creatures that player controls don't untap during the
#: player's next untap step**." (Pollen Lullaby) — "that player" is
#: `GameContext.clashed_opponent`; `SkipNextUntapEffect.subject=
#: "clashed_opponent"` flags every creature that player currently controls.
_CLASHED_OPP_CREATURES_NO_UNTAP_RE = _c(
    r"creatures that player controls don'?t untap during (?:the player'?s|their) next untap step"
)


def _clashed_opp_creatures_no_untap(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_untap", {"subject": "clashed_opponent"})]


# "Planeswalk." (RULE 901.10) / "Chaos ensues." (RULE 901.13) — the two
# outcome bodies of Path of the Animist / Path of the Enigma's "each
# player votes for planeswalk or chaos" vote (reached through
# `_vote_majority`'s `parse_effect_body`), and "planeswalk" as a
# standalone body (Plain Walker). `effects.PlaneswalkEffect` /
# `ChaosEnsuesEffect` wrap `RulesEngine.planeswalk` / `trigger_chaos`;
# both no-op outside a Planechase game. Fullmatch-only, so "planeswalk to
# <plane>" (Seek Bolas's Counsel) and "you may planeswalk" (TARDIS) stay
# UNMODELED, fail-closed — those cards are blocked on other clauses too.
def _planeswalk(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("planeswalk", {})]


def _chaos_ensues(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("chaos_ensues", {})]


# "Starting with you, each player votes for `<A>` or `<B>`. If `<A>` gets
# more votes, `<X>`. If `<B>` gets more votes or the vote is tied, `<Y>`."
# (RULE 701.38, PAR-29). `RulesEngine._request_vote` / `effects.VoteEffect`
# own the APNAP sweep and outcome. Two shapes: a majority branch (this
# handler) and per-vote scaling ("… for each `<A>` vote", `_vote_per_vote`
# below). Only the 2-option majority form here — 3+-option votes
# (Council Guardian) and "vote for a permanent/card" (Council's Judgment)
# stay UNMODELED, fail-closed.
_VOTE_HEADER_RE = _c(
    r"starting with you, each player votes for (?P<opts>[a-z][a-z, /'-]+?)\.\s+(?P<rest>.+)"
)
_VOTE_MAJORITY_BODY_RE = re.compile(
    r"^if (?P<a>[a-z'-]+) gets more votes, (?P<x>.+?)\.\s*"
    r"if (?P<b>[a-z'-]+) gets more votes or the vote is tied, (?P<y>.+?)\.?$",
    re.IGNORECASE,
)


def _split_vote_options(raw: str) -> list[str]:
    parts = re.split(r",?\s+or\s+|,\s+", raw.strip())
    return [p.strip() for p in parts if p.strip()]


def _vote_majority(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    options = _split_vote_options(m.group("opts"))
    if len(options) != 2:
        return None
    mm = _VOTE_MAJORITY_BODY_RE.match(m.group("rest").strip())
    if mm is None:
        return None
    a, b = mm.group("a").lower(), mm.group("b").lower()
    if {a, b} != {o.lower() for o in options}:
        return None
    x_specs = parse_effect_body(mm.group("x").strip())
    y_specs = parse_effect_body(mm.group("y").strip())
    if not x_specs or not y_specs:
        return None
    if any(
        s.params.get("target_kind") and not s.params.get("players")
        for s in (*x_specs, *y_specs)
    ):
        # A *targeted* branch can't resolve off-stack (see
        # `_pay_cost_then_general`); a mass `players`-scoped return
        # (`target_kind` there is just the card filter, not a RULE 115
        # choice) is fine.
        return None
    lowered = [o.lower() for o in options]
    idx_a = lowered.index(a)
    majority: list[Optional[list[dict]]] = [None, None]
    majority[idx_a] = [s.to_dict() for s in x_specs]
    majority[1 - idx_a] = [s.to_dict() for s in y_specs]
    return [EffectSpec("vote", {
        "options": options,
        "majority_specs": majority,
        "tie_index": lowered.index(b),
    })]


#: "… for each `<option>` vote" — the per-vote-scaling outcome shape
#: (Lieutenants of the Guard / Orchard Elemental / Messenger Jays). Each
#: segment's body parses as a *unit* effect (`add_counters` count 1/2,
#: `create_token` count 1, `gain_life` amount 3, `draw` count 1); `Vote
#: Effect`'s `per_vote_specs` then multiplies that ``count``/``amount`` by
#: the option's vote total at resolve time.
_VOTE_PER_VOTE_SEG_RE = re.compile(
    r"(?P<body>.+?)\s+for each (?P<opt>[a-z'-]+) votes?"
    r"(?:\s*\.\s*|\s*,\s*(?:and\s+)?|\s+and\s+|\s*$)",
    re.IGNORECASE,
)


def _vote_per_vote(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    options = _split_vote_options(m.group("opts"))
    if len(options) != 2:
        return None
    lowered = [o.lower() for o in options]
    rest = m.group("rest").strip()
    segments = list(_VOTE_PER_VOTE_SEG_RE.finditer(rest))
    if not segments:
        return None
    # every segment must be consumed — a trailing non-"for each" clause
    # (Messenger Jays' "for each card drawn this way, discard a card") is
    # not modeled, fail-closed.
    if segments[-1].end() != len(rest):
        return None
    # A later segment split on a bare "and" can silently lose a per-player
    # subject carried from the first ("each opponent sacrifices … *and*
    # discards a card for each taxes vote" — the "discards" clause is still
    # each opponent's, Capital Punishment). Lift the leading "each player /
    # each opponent" off segment 0 and prepend it to any subject-less
    # later segment so both scope the same way.
    #: the leading "each player / each opponent" of segment 0, to carry
    #: onto a subject-less later segment (Capital Punishment)
    _CARRY_SUBJ_RE = re.compile(r"^(each (?:player|opponent))\s+", re.IGNORECASE)
    #: any explicit subject a later segment might already carry — "you" is
    #: always the caster and resolves fine on its own, so it's included
    #: here only to *stop* the carry, not to trip the fail-closed guard
    _HAS_SUBJ_RE = re.compile(
        r"^(?:you|each (?:player|opponent)|target|that player)\b", re.IGNORECASE
    )
    #: a later segment's own *scoped* per-player subject (not "you")
    _SCOPED_SUBJ_RE = re.compile(
        r"^(?:each (?:player|opponent)|target|that player)\b", re.IGNORECASE
    )
    _first_subj = _CARRY_SUBJ_RE.match(segments[0].group("body").strip())
    carried_subject = _first_subj.group(1) if _first_subj else None

    per_vote: list[dict] = []
    for i, seg in enumerate(segments):
        opt = seg.group("opt").lower()
        if opt not in lowered:
            return None
        body = seg.group("body").strip()
        if i > 0 and carried_subject and not _HAS_SUBJ_RE.match(body):
            body = f"{carried_subject} {body}"
        # A later segment naming its own scoped per-player subject other
        # than the carried one isn't a shared-subject shape — fail-closed.
        if i > 0 and _SCOPED_SUBJ_RE.match(body) and not (
            carried_subject and body.lower().startswith(carried_subject.lower())
        ):
            return None
        body_specs = parse_effect_body(body)
        if not body_specs:
            return None
        if any(s.params.get("target_kind") for s in body_specs):
            return None
        # `_tally_and_apply_vote`'s per-vote branch scales an int
        # ``count``/``amount`` by the option's vote total. An effect with
        # no such param can't scale — "take an extra turn … for each time
        # vote" (Expropriate) would resolve once, not N times — so
        # fail-closed rather than half-model it.
        if any(s.type == "take_extra_turn" for s in body_specs):
            return None
        per_vote.append({
            "option": lowered.index(opt),
            "effects": [s.to_dict() for s in body_specs],
            "scale": 1,
        })
    return [EffectSpec("vote", {"options": options, "per_vote_specs": per_vote})]


# MEC-46 — "each player votes for `<colours>`. This creature gains
# protection from each color with the most votes or tied for most votes."
# (Council Guardian). Each option that ties for most votes contributes an
# indefinite (RULE 611, no duration) self-scoped "protection from
# `<colour>`" grant, carried in the vote's `winner_specs`.
_VOTE_WINNER_PROTECTION_BODY_RE = re.compile(
    r"^(?:this creature|~|it) gains protection from each color "
    r"with the most votes or tied for most votes\.?$",
    re.IGNORECASE,
)
_VOTE_COLOUR_WORDS = {"white", "blue", "black", "red", "green"}


def _vote_winner_protection(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    options = _split_vote_options(m.group("opts"))
    if len(options) < 2 or not all(o.lower() in _VOTE_COLOUR_WORDS for o in options):
        return None
    if _VOTE_WINNER_PROTECTION_BODY_RE.match(m.group("rest").strip()) is None:
        return None
    winner_specs = [
        [{
            "type": "grant_until",
            "params": {
                "static": {
                    "type": "grant_protection_static",
                    "params": {"protections": [opt.lower()]},
                },
                "duration": "rest_of_game",
                "self_subject": True,
            },
        }]
        for opt in options
    ]
    return [EffectSpec("vote", {"options": options, "winner_specs": winner_specs})]


# PAR-98: Niambi's "If you do" tail measures the bounced target's last
# known mana value.  The enclosing ReturnToHandEffect preserves that target
# as the nested resolution's previous subject before applying this bind.
_YOU_GAIN_LIFE_EQ_THAT_CREATURE_MV_RE = _c(
    r"you gain life equal to that creature'?s mana value"
)


def _you_gain_life_eq_that_creature_mv(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bind", {
        "name": "mv",
        "amount": {"kind": "characteristic", "characteristic": "mana_value", "of": "previous_target"},
        "effects": [{"type": "gain_life", "params": {"amount": "$mv"}}],
    })]


# MEC-46 — the tally-over-objects vote (`ObjectVoteEffect` /
# `RulesEngine._request_object_vote`): "each player votes for a nonland
# permanent you don't control. Exile each permanent with the most votes or
# tied for most votes." (Council's Judgment) / "…an artifact, creature, or
# enchantment card in your graveyard. Return each card … to your hand."
# (Custodi Squire). The vote is over board / graveyard *objects*, not
# named options.
_VOTE_OBJECT_PERMANENT_RE = re.compile(
    r"^a nonland permanent you don't control\.\s+"
    r"exile each permanent with the most votes or tied for most votes\.?$",
    re.IGNORECASE,
)
_VOTE_OBJECT_GRAVEYARD_RE = re.compile(
    r"^an? (?P<types>[a-z, ]+?) card in your graveyard\.\s+"
    r"return each card with the most votes or tied for most votes to your hand\.?$",
    re.IGNORECASE,
)
_VOTE_OBJECT_CARD_TYPES = {"artifact", "creature", "enchantment", "land", "planeswalker"}


def _vote_object(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    full = f"{m.group('opts').strip()}. {m.group('rest').strip()}"
    if _VOTE_OBJECT_PERMANENT_RE.match(full) is not None:
        return [EffectSpec("vote_object", {
            "pool": "nonland_permanents_opponents", "outcome": "exile",
        })]
    grave = _VOTE_OBJECT_GRAVEYARD_RE.match(full)
    if grave is not None:
        raw = re.split(r",\s*(?:or\s+)?|\s+or\s+", grave.group("types").strip())
        types = [t.strip().lower() for t in raw if t.strip()]
        if not types or any(t not in _VOTE_OBJECT_CARD_TYPES for t in types):
            return None
        return [EffectSpec("vote_object", {
            "pool": "graveyard_cards", "outcome": "return_to_hand", "card_types": types,
        })]
    return None


# MEC-46 — Expropriate's "For each time vote, take an extra turn after this
# one. For each money vote, choose a permanent owned by the voter and gain
# control of it. Exile Expropriate." The time body scales `take_extra_turn`
# by the number of time votes; the money body is a per-*ballot* gain-control
# (`VoteEffect.per_vote_specs`' ``per_voter_gain_control`` shape). The
# normalizer has already turned "one" → "1" and the card name → "~".
_VOTE_EXPROPRIATE_RE = re.compile(
    r"^for each (?P<a>time|money) vote, take an extra turn after this (?:one|1)\.\s+"
    r"for each (?P<b>time|money) vote, choose a permanent owned by the voter "
    r"and gain control of it\.\s+exile ~\.?$",
    re.IGNORECASE,
)


def _vote_expropriate(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    options = _split_vote_options(m.group("opts"))
    if {o.lower() for o in options} != {"time", "money"}:
        return None
    mm = _VOTE_EXPROPRIATE_RE.match(m.group("rest").strip())
    if mm is None or mm.group("a").lower() != "time" or mm.group("b").lower() != "money":
        return None
    lowered = [o.lower() for o in options]
    return [
        EffectSpec("vote", {
            "options": options,
            "per_vote_specs": [
                {
                    "option": lowered.index("time"),
                    "effects": [{"type": "take_extra_turn", "params": {"count": 1}}],
                    "scale": 1,
                },
                {"option": lowered.index("money"), "per_voter_gain_control": True},
            ],
        }),
        EffectSpec("exile", {"target_kind": None}),
    ]


# MEC-46 (RULE 701.38f) — "You choose how each player votes this turn."
# (Illusion of Choice). `SetForcedVoterEffect` marks the caster as the
# answerer of every seat's ballot for the rest of the turn.
def _forced_vote(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("set_forced_voter", {})]


# "`<player>` faces a villainous choice — `<A>`, or `<B>`." (RULE 701.55,
# PAR-29). `RulesEngine._request_villainous_choice` / `effects.FaceVillainous
# ChoiceEffect` own the APNAP sweep (each facing player applies their own
# pick). Each option is mini-parsed with the facing player as the target:
# "they/that player `<verb>`" → a player-targeted `sacrifice`/`discard`/
# `lose_life`, "you `<verb>`" stays controller-scoped. Only the options
# both parse — cards whose option is "cast a spell without paying", "put a
# permanent from hand", "create a copy of that card", "exile until …" &c.
# stay UNMODELED (tracked in PAR-30).
_VILLAINOUS_HEADER_RE = _c(
    r"(?P<subj>each opponent(?: who lost (?P<mll>\d+) or more life this turn)?"
    r"|that player|that opponent|target opponent|target player|defending player) "
    r"faces a villainous choice\s*[—-]\s*(?P<opts>.+)"
)
_VILLAINOUS_SUBJECTS: dict[str, str] = {
    "each opponent": "each_opponent",
    "target opponent": "target",
    "target player": "target",
    "that player": "trigger_target_player",
    "that opponent": "trigger_target_player",
    "defending player": "trigger_target_player",
}
_VILLAINOUS_SAC_WHAT: dict[str, str] = {
    "creature": "creature", "nontoken creature": "nontoken_creature",
    "artifact": "artifact", "permanent": "permanent", "land": "land",
}
_VILLAINOUS_SAC_RE = re.compile(
    r"^(?:they|that player|that opponent) sacrifices? an? (?P<what>[a-z ]+?)"
    r"(?: of their choice)?$",
    re.IGNORECASE,
)


def _villainous_option_specs(body: str):
    """One villainous-choice option → serialized specs, or ``None``.

    A "you …" clause parses controller-scoped as-is. A "they/that player
    `<verb>`" clause is retried as "target player `<verb>`" (the facing
    player is the effect's target — `_request_villainous_choice` applies
    each option with ``targets=[facing]``); a bare edict ("they sacrifice
    a creature of their choice") maps straight to a player-less
    `sacrifice` spec.
    """
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    body = body.strip().rstrip(".")
    sac = _VILLAINOUS_SAC_RE.match(body)
    if sac is not None:
        what = _VILLAINOUS_SAC_WHAT.get(sac.group("what").strip().lower())
        if what is None:
            return None
        return [{"type": "sacrifice", "params": {"what": what, "count": 1}}]
    lowered = body.lower()
    candidates: list[str] = []
    if lowered.startswith("they "):
        # "they lose 2 life" → "target player loses 2 life" (3rd-person-
        # singular verb), tried *first* so the resolution binds to this
        # effect's own `targets=[facing]` rather than a `selector=
        # "event_player"` that won't be live once the choice is answered.
        candidates.append(re.sub(
            r"^they (lose|discard|exile|mill|shuffle|draw|gain)\b",
            lambda mm: "target player " + mm.group(1) + "s",
            body, count=1, flags=re.IGNORECASE,
        ))
    elif lowered.startswith(("that player ", "that opponent ")):
        candidates.append(re.sub(
            r"^that (?:player|opponent) ", "target player ", body, count=1,
            flags=re.IGNORECASE,
        ))
    candidates.append(body)
    _TRIGGER_SELECTORS = {"event_player", "event_controller", "defending_player", "triggering_player"}
    for cand in candidates:
        specs = parse_effect_body(cand)
        if not specs:
            continue
        if any(s.params.get("selector") in _TRIGGER_SELECTORS for s in specs):
            continue  # depends on a trigger event that won't be live at resolve time
        if all(s.params.get("target_kind") in (None, "player") for s in specs):
            return [s.to_dict() for s in specs]
    return None


def _face_villainous_choice(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    min_life_lost = m.groupdict().get("mll")
    if min_life_lost is not None:
        # "each opponent **who lost N or more life this turn**" (Davros) —
        # an `each_opponent` sweep narrowed by `subject_min_life_lost`.
        subject = "each_opponent"
    else:
        subject = _VILLAINOUS_SUBJECTS.get(m.group("subj").lower())
    if subject is None:
        return None
    opts = m.group("opts").strip()
    # Split on ", or " — try each occurrence, accept the partition where
    # both halves are modelable (option bodies can carry internal commas).
    parts = [i for i in range(len(opts)) if opts[i:i + 5].lower() == ", or "]
    for cut in parts:
        a_specs = _villainous_option_specs(opts[:cut])
        b_specs = _villainous_option_specs(opts[cut + 5:])
        if a_specs and b_specs:
            params: dict = {
                "subject": subject,
                "option_a": a_specs,
                "option_b": b_specs,
            }
            if min_life_lost is not None:
                params["subject_min_life_lost"] = int(min_life_lost)
            return [EffectSpec("face_villainous_choice", params)]
    return None


# "Bolster N." (RULE 701.39a) — put N +1/+1 counters on a least-toughness
# creature you control (your choice on a tie). `RulesEngine.bolster` /
# `effects.BolsterEffect` (registered as ``bolster``) own the procedure and
# the tie-break choice.
def _bolster(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bolster", {"amount": int(m.group("n"))})]


# "Bolster X, where X is `<quantity>`." (PAR-29) — PAR-120: the quantity is
# read by the shared amount vocabulary (`count_phrase.parse_amount_phrase`).
def _bolster_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .count_phrase import parse_amount_phrase

    selector = parse_amount_phrase(m.group("selector"))
    if selector is None:
        return None
    return [EffectSpec("bolster", {"amount_from_count_selector": selector})]


# "Blight N." (Bloomburrow — "put N -1/-1 counters on a creature you
# control"). `RulesEngine.blight` / `effects.BlightEffect` (registered as
# ``blight``). Only the standalone-verb form ("whenever ~ attacks, blight
# 1", "draw a card and blight 1"). The *cost* forms — "{cost}, Blight N:
# <effect>" and "as an additional cost … blight N" — and the "you may
# blight N. If you do, <effect>" pay-cost-then wrapper stay UNMODELED
# (they need `ActivationCost`/cast-cost integration, not an effect). "blight
# X" (Soul Immolation, a dynamic amount) also stays UNMODELED, fail-closed.
def _blight(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("blight", {"amount": int(m.group("n"))})]


# "Airbend [up to N] [other] target `<X>` [you control]." (RULE 701.65,
# Avatar: The Last Airbender — "Exile it. While it's exiled, its owner may
# cast it for {2} rather than its mana cost."). Reuses `ExileEffect`'s
# existing `grant_owner_play_permission` (→ `GameState.exile_cast_
# condition`) plus `owner_play_permission_cost` ("{2}" → `GameState.exile_
# cast_cost_override`, consulted by `GameEngine.effective_cast_cost`).
# "airbend that creature" (a trigger-subject pronoun — Monk Gyatso) is the
# sibling `_AIRBEND_TRIGGER_SUBJECT_RE` below; "airbend … creature or spell"
# (exile off the stack — Aang, Swift Savior) stays UNMODELED, fail-closed.
_AIRBEND_TARGET_CAP = 10  # "any number of" — the shared `_ANY_NUMBER_TARGET_CAP` sentinel
_AIRBEND_RE = _c(
    r"airbend "
    r"(?:(?:up to |exactly )?(?P<n>\d+) |(?P<any>any number of )?)"
    r"(?:(?P<other>other|another) )?"
    r"target (?P<what>nonland permanent|creature)s?"
    r"(?P<yc> you control)?"
    r"(?P<orspell> or spell)?"
)


def _airbend(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    base = "nonland_permanent" if m.group("what") == "nonland permanent" else "creature"
    params: dict[str, Any] = {
        "grant_owner_play_permission": True,
        "owner_play_permission_cost": "{2}",
        # RULE 701.6x: mark this exile as an airbend so `ExileEffect` fires
        # `EventType.BENT` (Avatar Aang's "whenever you … airbend" trigger).
        "bend_kind": "airbend",
    }
    if m.group("orspell"):
        # "airbend up to one other target creature or spell" (Aang, Swift
        # Savior) — airbending a *spell* exiles it off the stack (RULE
        # 400.1, `RulesEngine.move_spell_off_stack`) and grants the same
        # owner-recast-for-{2} permission. Reuses the MEC-43 `spell_or_
        # creature` targeting union; `spell_or_permanent` tells `ExileEffect`
        # to take the stack path when the chosen target is a live spell.
        if base != "creature":
            return None  # fail closed — only "creature or spell" is a real template
        params["target_kind"] = "spell_or_creature"
        params["spell_or_permanent"] = True
    elif m.group("yc"):
        # "another target creature you control" → the source-excluding kind;
        # "target creature you control" → the plain one (which now *includes*
        # the source, per the cEDH-cube fix).
        params["target_kind"] = (
            "other_creature_you_control"
            if (base == "creature" and m.group("other"))
            else f"{base}_you_control"
        )
    else:
        # "another target creature" (no "you control") ≈ "target creature":
        # this engine's `targeting.py` already excludes the effect's own
        # source from a plain creature/permanent pick, and airbend's source
        # is usually a spell or an ETB'ing creature anyway.
        params["target_kind"] = base
    if m.group("any"):
        params["count"] = _AIRBEND_TARGET_CAP
        params["optional"] = True
    elif m.group("n") is not None:
        params["count"] = int(m.group("n"))
        params["optional"] = True  # "up to N" / "exactly N" both read as N here
    return [EffectSpec("exile", params)]


#: "airbend that creature / that permanent / it" — a trigger-subject
#: pronoun (Monk Gyatso: "Whenever another creature you control becomes the
#: target of a spell or ability, you may airbend that creature."). Reuses
#: `ExileEffect`'s `target_kind="trigger_subject"` (MEC-38), which reads
#: the firing event's own `instance_id`; the airbend permission params ride
#: along unchanged. The "you may" is peeled by the BECOMES_TARGET dispatch
#: (`_peel_optional`), so this only claims the bare verb.
_AIRBEND_TRIGGER_SUBJECT_RE = _c(
    r"airbend (?:that creature|that permanent|it)"
)


def _airbend_trigger_subject(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile", {
        "target_kind": "trigger_subject",
        "grant_owner_play_permission": True,
        "owner_play_permission_cost": "{2}",
        "bend_kind": "airbend",  # RULE 701.6x — see `_airbend`
    })]


# "Earthbend N." (RULE 701.66, Avatar: The Last Airbender — "target land you
# control becomes a 0/0 creature with haste that's still a land. Put N +1/+1
# counters on it."). `RulesEngine.earthbend` / `effects.EarthbendEffect`
# (registered as ``earthbend``). Only the literal ``earthbend N`` form; the
# "then untap that land" pronoun tail stays UNMODELED, fail-closed.
def _earthbend(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("earthbend", {"amount": int(m.group("n"))})]


#: "Earthbend X, where X is **that creature's power**." (PAR-30 — Beifong's
#: Bounty Hunters, on a "whenever a nonland creature you control dies"
#: trigger). "that creature" is the dying creature; `EarthbendEffect.
#: amount_from_trigger_event="power"` reads the DIES event's RULE 400.7
#: last-known-power snapshot (`damage_death_mixin`). Deliberately anchored
#: on "that creature's power" so it only claims the dying-subject shape;
#: "its power" / "that creature's toughness" / other reads stay UNMODELED.
_EARTHBEND_THAT_CREATURES_POWER_RE = _c(
    r"(?:you )?earthbend x, where x is that creature's power"
)


def _earthbend_that_creatures_power(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("earthbend", {"amount_from_trigger_event": "power"})]


#: "Earthbend X, where X is [twice] the number of `<count>`." (PAR-30 —
#: Rockalanche "forests you control", The Boulder, Ready to Rumble
#: "creatures you control with power 4 or greater", Bumi's Feast Lecture
#: "twice the number of Foods you control"). A small self-contained count
#: vocabulary (rather than reusing `subgrammars.DEVOTION`, whose
#: `count_subtype` group would mis-read a *land* subtype like "forests" as
#: a creature type) onto `continuous.count_selector`'s existing entries.
_EARTHBEND_X_SUBTYPE_SELECTORS: dict[str, str] = {
    "forests": "lands_you_control_of_type_forest",
    "islands": "lands_you_control_of_type_island",
    "swamps": "lands_you_control_of_type_swamp",
    "mountains": "lands_you_control_of_type_mountain",
    "plains": "lands_you_control_of_type_plains",
    "foods": "foods_you_control",
}
_EARTHBEND_X_RE = _c(
    r"(?:you )?earthbend x, where x is (?P<mult>twice )?the number of (?:"
    r"(?P<ebsub>" + "|".join(_EARTHBEND_X_SUBTYPE_SELECTORS) + r") you control"
    r"|creatures you control with power (?P<ebpow_n>\d+) or (?P<ebpow_cmp>less|greater)"
    r"|(?P<ebbare>creatures|permanents|artifacts|lands|enchantments) you control"
    r")"
)


def _earthbend_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    sub = m.groupdict().get("ebsub")
    if sub:
        selector = _EARTHBEND_X_SUBTYPE_SELECTORS[sub]
    elif m.groupdict().get("ebpow_n"):
        op = "le" if m.group("ebpow_cmp") == "less" else "ge"
        selector = f"creatures_you_control_with_power_{op}_{m.group('ebpow_n')}"
    elif m.groupdict().get("ebbare"):
        selector = f"{m.group('ebbare')}_you_control"
    else:
        return None  # fail closed — an X phrasing we don't model
    params: dict[str, Any] = {"amount_from_count_selector": selector}
    if m.groupdict().get("mult"):
        params["amount_multiplier"] = 2
    return [EffectSpec("earthbend", params)]


# "Support N." (RULE 701.41a) — put a +1/+1 counter on each of up to N
# target creatures. Needs no effect of its own: it's the exact spec shape
# `_add_counters_multi_target` already emits for "put a +1/+1 counter on
# each of up to two target creatures", so it rides the existing
# `add_counters` multi-target path. RULE 701.41c ("a creature's own support
# can't put a counter on itself") falls out for free — `targeting`'s plain
# ``"creature"`` kind already excludes the ability's source. Literal N only.
def _support(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": 1, "kind": "+1/+1", "target_kind": "creature",
        "target_count": int(m.group("n")), "optional": True,
    })]


# "Support X." (PAR-29, Blitzball Stadium/The Crowd Goes Wild) — the same
# alias, X read off the spell/ability's own announced {X}
# (`TargetSpec.count_selector="source_x_paid"`) rather than a literal N.
def _support_x(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": 1, "kind": "+1/+1", "target_kind": "creature",
        "target_count_selector": "source_x_paid", "optional": True,
    })]


# "Suspect <creature>." (RULE 701.60a — Murders at Karlov Manor): the
# creature gains the suspected designation (menace + can't block, 701.60b).
# `RulesEngine.suspect` / `effects.SuspectEffect` (registered as
# ``suspect``). Same subject shapes as `_goad`/`_explore`:
#   • "suspect it" — the ability's own source ("when ~ enters, suspect it");
#   • "suspect it"/"suspect that creature" after a targeting clause — the
#     previous target (`previous_subject_only`, Caught Red-Handed);
#   • "suspect enchanted creature" — this Aura's host (`attached`);
#   • "suspect [up to N] target creature[ an opponent controls / other
#     target creature you control]" — off the shared TARGET rows.
_SUSPECT_TARGET_KINDS = (
    "creature", "creature_you_control", "creature_you_dont_control",
    "other_creature_you_control",
)


def _suspect_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("suspect", {})]


def _suspected_self_counter_or_suspect(m: re.Match[str]) -> list[EffectSpec]:
    """Repeat Offender: mutually exclusive self-suspect branches."""
    return [
        EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "self": True},
                   condition={"source_is_suspected": True}),
        EffectSpec("suspect", {}, condition={"source_is_suspected": False}),
    ]


def _suspect_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("suspect", {"previous_subject": True})]


def _suspect_attached(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("suspect", {"attached": True})]


def _suspect_other_then_remove_self(m: re.Match[str]) -> list[EffectSpec]:
    """Frantic Scapegoat's optional non-target choice and reflexive tail."""
    return [EffectSpec("suspect", {
        "selection_kind": "other_creature_you_control", "optional": True,
        "then_specs": [{"type": "remove_suspected", "params": {"self_subject": True}}],
    })]


def _suspect_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _SUSPECT_TARGET_KINDS):
        return None  # only a creature can be suspected (RULE 701.60a)
    return [EffectSpec("suspect", {"target_kind": kind, **_optional_param(m)})]


# "All suspected creatures are no longer suspected." (RULE 701.60a's
# reverse — Absolving Lammasu). Only the mass standalone shape; the
# conditional single-creature "if it's suspected, it's no longer suspected"
# stays unclaimed, fail-closed.
def _remove_suspected_all(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_suspected", {})]


# PAR-30 Suspect one-off shapes — "You may have it become no longer
# suspected." (Deadly Complication's second mode, after "put a +1/+1 counter
# on target suspected creature you control"). "it" is the previous clause's
# target; the "you may" routes through `_request_choose_objects` so declining
# keeps the menace a suspected creature has (`RemoveSuspectedEffect.optional`).
def _remove_suspected_may_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_suspected", {"previous_subject": True, "optional": True})]


def _remove_suspected_previous_selector(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_suspected", {"previous_selector": True})]


# "Detain [up to N] target <permanent> an opponent controls." (RULE 701.35a
# — Return to Ravnica). `RulesEngine.detain` / `effects.DetainEffect`
# (registered as ``detain``). Only an opponent-controlled creature or
# nonland permanent (every real detain card); a plain "target creature"
# with no controller qualifier isn't a real printing, so leave it
# unclaimed. "detain each nonland permanent … with mana value N or less"
# (Lavinia) and a "with backup or vehicle" filter (Azorius Traffic
# Enforcement) stay UNMODELED — a selector + filter this doesn't build yet.
_DETAIN_TARGET_KINDS = (
    "creature_you_dont_control", "nonland_permanent_you_dont_control",
    "permanent_you_dont_control",
)
_DETAIN_MULTI_RE = _c(
    r"detain up to (?P<n>2|3|two|three) target "
    r"(?P<what>creatures|nonland permanents) "
    r"(?:your opponents control|an opponent controls)"
)
_DETAIN_WORD_N = {"two": 2, "three": 3, "2": 2, "3": 3}


def _detain(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _DETAIN_TARGET_KINDS):
        return None
    return [EffectSpec("detain", {"target_kind": kind, **_optional_param(m)})]


def _detain_multi(m: re.Match[str]) -> list[EffectSpec]:
    kind = ("nonland_permanent_you_dont_control"
            if m.group("what") == "nonland permanents" else "creature_you_dont_control")
    return [EffectSpec("detain", {
        "target_kind": kind, "count": _DETAIN_WORD_N[m.group("n")], "optional": True,
    })]


# "Goad target creature." (RULE 701.15a) and its controller-scoped variants
# ("…target creature an opponent controls"), off the shared `TARGET` rows.
def _goad(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        # Goaded is only ever a creature designation (RULE 701.15b) — a
        # non-creature target row here means the clause isn't what it looks
        # like, so leave it unclaimed.
        return None
    return [EffectSpec("goad", {"target_kind": kind, **_optional_param(m)})]


# "Goad it." / "Goad that creature." — the pronoun form, pointing at whatever
# the *previous* clause of this same ability targeted ("~ deals 2 damage to
# target creature. Goad that creature.", Hellrider-shaped). Offered only when
# such a clause really preceded it (`EffectHandler.previous_subject_only`),
# never as a blind claim.
def _goad_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("goad", {"target_kind": None})]


# "Goad all creatures your opponents control." / "…you don't control." — the
# untargeted mass form (RULE 601.2c), the same selector shape
# `_tap_selector`/`_add_counters_selector` use.
def _goad_selector(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("goad", {"selector": "creatures_opponents_control"})]


# "For each opponent, goad up to one target creature that player controls."
# (RULE 601.2c — 4 cards: Sontaran General, Havoc Eater, Baldur's Gate
# Wilderness, and the same clause inside Dungeon room text). One requirement
# whose *count* is the number of opponents, not N separate requirements: the
# "that player" half is RULE 115's already-modeled `distinct_controllers`
# constraint, applied by `GoadEffect` when it sees this selector.
def _goad_per_opponent(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec(
            "goad",
            {
                "target_kind": "creature_you_dont_control",
                "optional": True,
                "count_selector": "opponents",
            },
        )
    ]


# "Goad up to X target creatures your opponents control." (Death Kiss) — the
# other dynamic count: X is the monstrosity this same permanent just
# announced (RULE 701.37c lets another ability refer to it), which
# `GameObject.monstrosity_x` records for exactly this.
def _goad_up_to_x(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec(
            "goad",
            {
                "target_kind": "creature_you_dont_control",
                "optional": True,
                "count_selector": "source_monstrosity_x",
            },
        )
    ]


# "The tokens are goaded for the rest of the game." (Rendmaw, The War Games,
# Life of the Party) — the subject is what an *earlier clause of this same
# ability* just created, which is `GameContext.created_objects`; "for the
# rest of the game" is the no-expiry variant of RULE 701.15a's default
# "until your next turn".
def _goad_created(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("goad", {"target_kind": None, "referent": "created", "permanent": True})]


# "It's goaded for the rest of the game." (Jon Irenicus) — the same no-expiry
# designation aimed at the previous clause's *target* instead.
def _goad_previous_permanent(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("goad", {"target_kind": None, "permanent": True})]


# "You become the monarch." / "Target player becomes the monarch." (RULE
# 725.1) and "You take the initiative." / "Target player takes the
# initiative." (RULE 726.1) — plain designation grants, the same untargeted-
# vs-targeted "who" split `_gain_life`/`_lose_life` use.
def _become_monarch(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("become_monarch", params)]


def _take_initiative(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("take_initiative", params)]


# "[You/Target player] get[s] an emblem with '<ability>'." (RULE 114.2) —
# the quoted ability is itself an ordinary ability line, recursively parsed
# the same way `static_handlers._quoted_ability_grant_effects` parses an
# Aura/Equipment's quoted grant (`segmenter.segment_line`, imported lazily in
# `_emblem_ability_spec` below — `segmenter` imports *this* module, so a
# module-level import would cycle). Unlike that grant (which flattens to a
# `grant_triggered_ability`'s bare effects list), the *whole* nested
# `AbilitySpec` is kept, since `game/rules_engine.py`'s `create_emblem` binds
# it fresh at resolve time against a synthetic `Emblem` source (RULE 114.4) —
# there's no host permanent to flatten onto in the first place.
_EMBLEM_RE = re.compile(
    r'(?P<who>you |target player )?gets? an emblem with "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)

#: Subject/selector shapes that only mean something relative to a *source
#: permanent* ("this creature", "equipped/enchanted creature", "other
#: creatures you control") — meaningless for an emblem's synthetic source,
#: so a nested spec using one is rejected (fail-closed) rather than silently
#: binding an ability that can never fire, or that resolves a selector that
#: always comes back empty.
_EMBLEM_UNSUPPORTED_SUBJECTS: frozenset[str] = frozenset(
    {"self", "attached_permanent", "self_or_attached_permanent"}
)
_EMBLEM_UNSUPPORTED_AFFECTS: frozenset[str] = frozenset(
    {"self", "attached_permanent", "other_creatures_you_control"}
)


def _emblem_ability_spec(inner: str) -> Optional[dict]:
    from ..segmenter import segment_line  # lazy: segmenter imports this module

    segment = segment_line(
        inner.strip(),
        allow_spell_effect=False,
        provenance=ParserProvenance(version="nested", source="rule:oracle"),
    )
    spec = segment.spec
    if spec is None or spec.modes:
        return None
    if spec.ability_kind == "triggered":
        condition = (spec.trigger or {}).get("condition") or {}
        if condition.get("subject") in _EMBLEM_UNSUPPORTED_SUBJECTS:
            return None
        if condition.get("subject") == "group" and condition.get("other"):
            return None
    elif spec.ability_kind == "static":
        if any(e.params.get("affects") in _EMBLEM_UNSUPPORTED_AFFECTS for e in spec.effects):
            return None
    elif spec.ability_kind == "activated":
        # RULE 114.4 also permits an emblem's own activated ability (MEC-8) —
        # `RulesEngine.create_emblem` binds it fresh against the synthetic
        # `Emblem` source exactly like the triggered/static cases, so the
        # same fail-closed self-referential guard applies: no real emblem
        # prints one yet, but "sacrifice this"/"equipped creature…"-shaped
        # effects would be meaningless with no host permanent.
        if any(
            e.params.get("target_kind") in _EMBLEM_UNSUPPORTED_SUBJECTS
            or e.params.get("selector") in _EMBLEM_UNSUPPORTED_SUBJECTS
            or e.params.get("affects") in _EMBLEM_UNSUPPORTED_AFFECTS
            for e in spec.effects
        ):
            return None
    else:
        return None  # only a static/triggered/activated ability can live in an emblem
    try:
        spec.validate()
    except Exception:
        return None
    return spec.to_dict()


def _create_emblem(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    ability = _emblem_ability_spec(m.group("inner"))
    if ability is None:
        return None
    params: dict = {"ability": ability}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("create_emblem", params)]


# A pump's subject: a targeted creature/permanent, the self-reference ``~``
# (a creature's own activated "~ gets +1/+0 …"), or an untargeted *group*
# ("creatures you control get +2/+1 …" — RULE 601.2c, not a target at all;
# the common Saga-chapter/anthem-spell shape, or the board-wide "all
# creatures get -N/-N until end of turn" mass-removal shape, Infest/Blight
# Grenade-shaped). Shared by the pump handlers.
#: PAR-13's own two additions — "creatures your opponents control"/
#: "creatures you don't control" (Mouth of the Storm/Behold the
#: Unspeakable-shaped mass debuffs) — both the same `continuous.
#: group_selector_objects` selector as each other (every creature not
#: yours, the plain-English reading of either phrasing).
_GROUP = (
    r"(?P<group>other creatures you control"
    # PAR-128: the unscoped "other" (RULE 109.5) — Shefet Archfiend's "all other
    # creatures", Honored Crop-Captain's "other attacking creatures"; the
    # count-phrase grammar already reads "other" as ``not_reference``.
    r"|all other creatures|other attacking creatures"
    # "Each creature you control with a counter on it gains firebending N …"
    # (Iroh, Dragon of the West) — a counter-presence filter on the
    # controller-scoped creature set; tried before the bare
    # "each creature you control" alternative below.
    r"|each creature you control with a counter on it"
    # PAR-74: "each other creature you control gets …" (Kodama of the South
    # Tree) — the distributive-singular phrasing of "other creatures you
    # control" just above, same `other_creatures_you_control` selector, the
    # same relationship "each creature you control" already has to
    # "creatures you control". Tried before the bare "each creature you
    # control" row below so "other" isn't swallowed by it.
    r"|each other creature you control"
    r"|each other creature"
    r"|each creature you control"
    # "all creatures you control gain deathtouch until end of turn" (Venom
    # Connoisseur) — the same group as "creatures you control", with the
    # emphatic "all"; tried before the unscoped "all creatures" below.
    r"|all creatures you control"
    r"|creatures you control|all creatures"
    r"|creatures your opponents control|creatures you don'?t control|permanents your opponents control"
    r"|creatures target (?:player|opponent) controls"
    r"|permanents you control|elves you control|elf creatures you control"
    # PAR-109: "Dragons you control get +1/+0 until end of turn" (Lathliss, Ran and Shaw) — any plural subtype
    # or "<adjective> creatures" group; `_group_selector` (the count-phrase grammar) fails closed on a word that
    # is none of its vocabulary.
    r"|other [a-z]+s you control|[a-z]+ creatures you control|[a-z]+s you control"
    # PAR-19: "Attacking creatures get -3/-0 until end of turn." (Lethargy
    # Trap-shaped) — unscoped by controller, the same `group_selector_
    # objects` "attacking_creatures" branch Motivated Pony's anthem and
    # `TapEffect.selector` (MEC-28) already reuse.
    r"|attacking creatures)"
)
_SUBJECT = (
    rf"(?:{TARGET}|(?P<selfref>{re.escape(SELF)})|{_GROUP}|(?P<attached>{_ATTACHED_SUBJECT}))"
)
#: A matched ``group`` phrase → its `continuous.group_selector_objects`
#: selector, for the phrases `parse_count_phrase` doesn't reach (checked
#: individually, not assumed — PAR-120, PARSER_VERSION 474): "other"/"each
#: other" (`not_reference` isn't reachable through this entry point —
#: confirmed directly, the same gap found retiring `_CONTROL_COUNT_
#: SELECTORS`/`_SELF_ANTHEM_FOR_EACH_SELECTORS`), "all creatures" (no "you
#: control"/"in your graveyard" tail for the grammar to anchor on), and the
#: negated "you don't control" phrasing (the grammar has no negation
#: reading — RULE-equivalent to "your opponents control", already covered,
#: but not worth building an alias mechanism for the one phrase that needs
#: it). "Each creature you control **with a counter on it**" turned out to
#: already be covered too (the grammar's own `has_counter` filter key,
#: proven equivalent to the old `creatures_you_control_with_a_counter`
#: string on a real board) — no residual entry needed for it at all.
_GROUP_SELECTORS: dict[str, "str | dict"] = {
    "other creatures you control": "other_creatures_you_control",
    "each other creature you control": "other_creatures_you_control",
    "all creatures": "all_creatures",
    "creatures you dont control": "creatures_opponents_control",
    # PAR-128: the unscoped "each other creature" (singular, so `parse_count_phrase`
    # can't read it) — every creature but the effect's source.
    "each other creature": {
        "zone": "battlefield", "of": "any",
        "filter": {"card_type": "creature", "not_reference": True},
    },
}


def _group_selector(phrase: str) -> "Optional[str | dict]":
    """A matched ``group`` phrase (`_GROUP`) → a `group_selector_objects`
    argument, structured or named. Tried before the residual table above;
    "each `<X>`" is the distributive-singular of plain "`<X>`" ("each
    creature you control gains …" reads the identical group as "creatures
    you control" — Avacyn/Griselbrand), so it's retried with that prefix
    stripped — but only a bare "each ", never "each other ", since that
    "other" is a real exclusion the grammar doesn't express (residual
    table, above).
    """
    from .count_phrase import parse_count_phrase

    structured = parse_count_phrase(phrase)
    if structured is not None:
        return structured
    if phrase.startswith("each ") and not phrase.startswith("each other "):
        structured = parse_count_phrase(phrase[len("each "):])
        if structured is not None:
            return structured
    if phrase == "all other creatures":
        return parse_count_phrase(phrase[len("all "):])
    if phrase == "all creatures you control":
        # The emphatic "all" names the same group; bare "all creatures" (no
        # controller tail) stays the residual table's unscoped selector.
        return parse_count_phrase(phrase[len("all "):])
    return _GROUP_SELECTORS.get(phrase)
#: A signed P/T delta, "+3/+3" / "-2/-2" / "+0/-1" (ASCII or unicode minus).
_PT_DELTA = r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"

_PUMP_GRANT_WHILE_TAPPED_RE = _c(
    rf"target (?P<subtype>[a-z]+) creature gets? {_PT_DELTA} and has (?P<kw>[a-z, ]+?) "
    r"for as long as ~ remains tapped"
)

_PUMP_AND_QUOTED_GRANT_RE = _c(
    rf"(?P<dur_pre>until end of turn, )?{_SUBJECT} gets? {_PT_DELTA} and gains? "
    r"(?:(?P<kw>[a-z, ]+?),? and )?\"(?P<inner>[^\"]+)\"(?P<dur_post> until end of turn)?"
)
_PUMP_AND_ALL_TYPES_RE = _c(
    rf"{_SUBJECT} gets? {_PT_DELTA} and gains? all creature types until end of turn"
)
_PUMP_KEYWORD_CHOICE_RE = _c(
    rf"(?P<dur_pre>until end of turn, )?{_SUBJECT} (?:gets? {_PT_DELTA} and )?gains? your choice of "
    r"(?P<opts>[a-z, ]+?)(?P<dur_post> until end of turn)?"
)

#: "Nonblack creatures get -2/-2 until end of turn." — a normal
#: untargeted group pump with the existing negated-colour object filter.
#: Keep the colour captured so the same catalogue row covers every colour.
_NONCOLOR_CREATURES_PUMP_RE = _c(
    rf"non(?P<color>white|blue|black|red|green) creatures gets? {_PT_DELTA} until end of turn"
)


def _noncolor_creatures_pump(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "selector": "all_creatures",
        "creature_filter": {"without_color": _COLOR_WORDS[m.group("color").lower()]},
    })]

#: PAR-15's "any number of target creatures each get +N/+N [and gain
#: `<keyword>`] until end of turn" (Aerial Formation/Ajani's Presence/Cruel
#: Feeding/Desperate Stand/Rouse the Mob-shaped) — the pump-family sibling of
#: `_add_counters_multi_target`'s "each of up to N" shape: every chosen
#: creature gets the *full* stated boost (`PumpEffect`'s ``target_count``,
#: not a divided pool).
_PUMP_MULTI_TARGET_RE = _c(
    rf"any number of target creatures each get {_PT_DELTA}"
    rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
)


def _pump_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "target_kind": "creature", "target_count": _ANY_NUMBER_TARGET_CAP, "optional": True,
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None  # unmodeled granted ability → fail-closed
        params["keywords"] = keywords
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: "Untap those creatures." (Colossal Heroics' own trailing sentence,
#: following "Any number of target creatures each get +2/+2 until end of
#: turn.") — the tap-family sibling of `_return_previous_group`: no target
#: of its own, only offered when a preceding multi-target clause actually
#: chose a group (`EffectHandler.previous_subject_only`).
_UNTAP_PREVIOUS_GROUP_RE = _c(r"(?:then )?untap (?:those creatures|them)")


def _untap_previous_group(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("tap", {"previous_subject": True, "untap": True})]


#: "Creatures you control get +2/+1 until end of turn. **Untap those
#: creatures.**" (War Flare, PAR-128) — the mass-selector sibling of
#: `_untap_previous_group`: offered only when the preceding clause acted on a
#: replayable group (`EffectHandler.previous_selector_only`), read back off
#: `GameContext.previous_selector` at resolution.
_TAP_PREVIOUS_SELECTOR_RE = _c(r"(?:then )?(?P<verb>tap|untap) (?:those creatures|them)")


def _tap_previous_selector(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("tap", {"selector": "previous_selector", "untap": m.group("verb").lower() == "untap"})]


#: "…, then untap **that land**." (Avatar Kyoshi — PAR-30, following
#: "earthbend N") / "…, then tap **that permanent**." — the singular
#: `previous_subject` sibling of `_UNTAP_PREVIOUS_GROUP_RE`: "that
#: `<permanent-word>`" names the single object the preceding clause chose
#: (`EffectHandler.previous_subject_only`, `GameContext.previous_targets`).
#: Distinct from `_TAP_GROUP_SUBJECT_RE` ("that creature", `group_subject_
#: only`) and `_tap_self` ("it"/"this ~", the ability's own source).
_TAP_PREVIOUS_SUBJECT_RE = _c(
    r"(?:then )?(?P<verb>tap|untap) that (?:land|permanent|artifact|creature)"
)


def _tap_previous_subject(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("tap", {"previous_subject": True, "untap": m.group("verb").lower() == "untap"})]


#: "[That / target / ~] `<permanent>` doesn't untap during
#: [its controller's / your / the player's] next untap step." — Barl's Cage
#: and the ~95-card "Tap X. It doesn't untap …" tempo family (Chillbringer,
#: Berg Strider, the Frost Lynx cycle, Entangling Trap / Pollen Lullaby
#: clash payoffs, …). `SkipNextUntapEffect` sets `GameObject.
#: skip_next_untap`, RULE 702.19b's own one-time flag. Three subject shapes,
#: routed by the same `_PERMANENT_NOUN`/`~`/pronoun split every other
#: family here uses.
_DONT_UNTAP_SUFFIX = (
    r" do(?:es)?n'?t untap during (?:its controller'?s|their controller'?s|your|the player'?s) next untap step"
)
_SKIP_UNTAP_TARGET_RE = _c(
    rf"target (?P<what>creature|artifact|land|permanent)(?P<scope>{NOT_YOU_TAIL})?{_DONT_UNTAP_SUFFIX}"
)
_SKIP_UNTAP_PREV_RE = _c(
    rf"(?:it|that (?:creature|artifact|land|permanent)|those creatures){_DONT_UNTAP_SUFFIX}"
)
_SKIP_UNTAP_SELF_RE = _c(rf"(?:~|this (?:creature|artifact|permanent)){_DONT_UNTAP_SUFFIX}")


def _skip_untap_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = m.group("what")
    if m.group("scope"):
        # PAR-128: "target creature an opponent controls doesn't untap …" (Fogwalker).
        kind = NOT_YOU_TARGET_KINDS.get(kind)
        if kind is None:
            return None
    return [EffectSpec("skip_next_untap", {"target_kind": kind})]


def _skip_untap_prev(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_untap", {"previous_subject": True})]


#: PAR-128: "…tap all attacking creatures. **Those creatures** don't untap
#: during their controller's next untap step." (Clinging Mists) — the
#: mass-selector sibling of `_SKIP_UNTAP_PREV_RE`, plural wording included
#: ("their controllers' next untap steps").
_SKIP_UNTAP_PREV_SELECTOR_RE = _c(
    r"(?:they|those creatures) don'?t untap during "
    r"(?:their controller'?s next untap step|their controllers'? next untap steps|"
    # Sleep: the chosen player's own creatures, so "that player's" is their controller's.
    r"that player'?s next untap step)"
)


def _skip_untap_prev_selector(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_untap", {"target_kind": None, "subject": "previous_selector"})]


def _skip_untap_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_untap", {"target_kind": None})]


#: "Whenever ~ deals combat damage to a creature, tap that creature and it
#: doesn't untap during its controller's next untap step." (PAR-84 —
#: Kashi-Tribe Reaver and siblings).  Both pronouns name the DAMAGE event's
#: *recipient*, rather than the source that dealt it; `target_operand` keeps
#: this distinct from a normal RULE 115 target and reads that event payload at
#: resolution time.
_TAP_DAMAGE_RECIPIENT_AND_SKIP_UNTAP_RE = _c(
    rf"tap that creature and it{_DONT_UNTAP_SUFFIX}"
)


def _tap_damage_recipient_and_skip_untap(m: re.Match[str]) -> list[EffectSpec]:
    params = {"target_operand": "damage_recipient"}
    return [EffectSpec("tap", params), EffectSpec("skip_next_untap", params)]


#: "The next N damage that would be dealt to ~ this turn is dealt to target
#: creature you control instead." (PAR-85 — en-Kor).  This watches damage's
#: recipient, unlike the existing chosen-*source* redirect family.
_REDIRECT_DAMAGE_TO_SELF_RE = _c(
    rf"the next (?P<n>\d+) damage that would be dealt to ~ this turn is dealt to target creature you control instead"
)


def _redirect_damage_to_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("redirect_damage_to_target_creature", {"amount": int(m.group("n"))})]


#: "[`<TARGET>` / ~ / it] gains protection from the color of your choice
#: until end of turn." (Gods Willing / Emerge Unscathed / Jareth / Feat of
#: Resistance — RULE 702.16, ~27 SOLO). The engine primitive
#: (`effects.GrantProtectionEffect` / `RulesEngine.grant_protection_choice`
#: — the interactive `grant_protection_color` pick, `temp_protections`,
#: cleared at cleanup) is Mother of Runes'; only the parser recognition of
#: this exact phrasing was missing.
_PROT_CHOICE_SUFFIX = r" gains? protection from the colou?r of your choice until end of turn"
_GRANT_PROT_CHOICE_TARGET_RE = _c(rf"{TARGET}{_PROT_CHOICE_SUFFIX}")
_GRANT_PROT_CHOICE_SELF_RE = _c(rf"{_SELF_SUBJECT}{_PROT_CHOICE_SUFFIX}")
_GRANT_PROT_CHOICE_PREV_RE = _c(rf"it{_PROT_CHOICE_SUFFIX}")
_GRANT_PROT_CHOICE_KINDS = frozenset({"creature", "creature_you_control", "permanent_you_control"})


def _grant_prot_choice_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _GRANT_PROT_CHOICE_KINDS):
        return None
    return [EffectSpec("grant_protection", {"target_kind": kind})]


def _grant_prot_choice_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_protection", {"target_kind": None})]


def _grant_prot_choice_prev(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_protection", {"previous_subject": True})]


_GROUP_FIXED_PROTECTION_RE = _c(
    r"(?P<group>creatures you control|all creatures|creatures your opponents control) "
    r"gain protection from (?P<color>white|blue|black|red|green) until end of turn"
)
_GROUP_FIXED_PROTECTION_SELECTORS = {
    "creatures you control": "creatures_you_control",
    "all creatures": "all_creatures",
    "creatures your opponents control": "creatures_opponents_control",
}


def _group_fixed_protection(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_fixed_protection_group", {
        "selector": _GROUP_FIXED_PROTECTION_SELECTORS[m.group("group")],
        "color": _COLOR_WORDS[m.group("color")],
    })]


#: "Reveal cards from the top of your library until you reveal a `<land /
#: creature / artifact / enchantment / nonland / basic land>` card. Put that
#: card `<onto the battlefield / into your hand>` and the rest `<on the
#: bottom of your library in a random order / into your graveyard / shuffle
#: into your library>`." (Recross the Paths, Clifftop Lookout, Atla Palani,
#: Bloodline Pretender-cycle, ~40 real cards.) `RulesEngine.dig_until` /
#: `effects.DigUntilEffect` — the generalized cascade dig — is the engine
#: primitive; this is its "reveal until a *type* predicate" recognition.
#: **Documented simplification**: "in any order" is modeled as the engine's
#: only bottoming mode, a *random* order — the player doesn't get to choose
#: the sequence of the bottomed cards.
_DIG_UNTIL_PRED = {
    "a land": {"type": "land"},
    "a basic land": {"type": "land", "basic": True},
    "a creature": {"type": "creature"},
    "an artifact": {"type": "artifact"},
    "an enchantment": {"type": "enchantment"},
    "a nonland": {"without_type": "land"},
    "a nonartifact, nonland": {"without_type": ["artifact", "land"]},
}
_DIG_UNTIL_HIT = {
    "onto the battlefield": "battlefield",
    "into your hand": "hand",
}
#: The "…and the rest `<somewhere>`" tail — matched as a whole phrase
#: (`re.search` inside the leftover) so the many "put all other cards
#: revealed this way" / "the rest" / ", then shuffle" connector spellings
#: don't each need a row.
_DIG_UNTIL_REST_RES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"bottom of your library in (?:a random|any) order", re.I), "library_bottom_random"),
    (re.compile(r"shuffle .*?into your library", re.I), "library_shuffled"),
    (re.compile(r"(?:cards? .*?)?into your graveyard", re.I), "graveyard"),
]
_REVEAL_UNTIL_TYPE_RE = _c(
    r"reveal cards from the top of your library until you reveal "
    rf"(?P<pred>{'|'.join(map(re.escape, _DIG_UNTIL_PRED))}) card\. "
    rf"put that card (?P<hit>{'|'.join(map(re.escape, _DIG_UNTIL_HIT))})"
    r"(?P<rest>.+)"
)


#: PAR-75: "Reveal cards from the top of your library until you reveal a
#: Doctor card, a card with doctor's companion, or a Vehicle card. Put that
#: card into your hand and the rest on the bottom of your library in a
#: random order." (An Unearthly Child) — a three-way OR predicate
#: `_DIG_UNTIL_PRED`'s single-bare-type grammar can't express (one of its
#: three arms is a printed-keyword check, not a card type/subtype at all).
#: `card_query.matches`'s existing `"or"` key composes the three arms
#: directly, so this is a fixed singleton row rather than a new compositional
#: OR grammar — no other cached card shares this exact three-way shape.
_DIG_UNTIL_DOCTOR_COMPANION_VEHICLE_RE = _c(
    r"reveal cards from the top of your library until you reveal a doctor card, "
    r"a card with doctor'?s companion, or a vehicle card\. "
    r"put that card into your hand and the rest on the bottom of your library "
    r"in a random order"
)


def _dig_until_doctor_companion_vehicle(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("dig_until", {
        "criteria": {"or": [
            {"type": "Doctor"},
            {"has_keyword": "Doctor's Companion"},
            {"type": "Vehicle"},
        ]},
        "hit_destination": "hand",
        "rest_destination": "library_bottom_random",
    })]


#: PAR-76: "`<base effect>`. If you have a full party, `<bigger effect>`
#: instead." (RULE 700.8/702.129) — a resolve-time magnitude override, the
#: same "if `<card-specific condition>`, `<bigger effect>` instead" shape
#: `DealDamageEffect.amount_if_kicked`/`amount_if_raid` already establish
#: for Kicker/Raid, generalized to a new `amount_if_full_party` field on
#: both `DealDamageEffect` and `AddCountersEffect` (RULE 700.8's "full
#: party" is exactly 4 — one each of Cleric/Rogue/Warrior/Wizard — the
#: `"creatures_in_your_party"` count selector's own cap, checked live at
#: resolution as a threshold rather than read as a magnitude the way
#: PAR-72's `count_selector_multiplier` family does). Two fixed singleton
#: rows (matched as one whole two-sentence clause, before the connector
#: split ever runs) rather than a general "if `<condition>`, `<bigger
#: effect>` instead" grammar — no other cached card pairs "full party" with
#: a magnitude override on a *third* effect shape yet.
_DAMAGE_EACH_OPPONENT_FULL_PARTY_RE = _c(
    r"~ deals (?P<n>\d+) damage to each opponent\. "
    r"if you have a full party, it deals (?P<n2>\d+) damage to each opponent instead"
)


def _damage_each_opponent_full_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "selector": "each_opponent",
        "amount_if_full_party": int(m.group("n2")),
    })]


_ADD_COUNTER_TARGET_FULL_PARTY_RE = _c(
    r"put an? \+1/\+1 counter on target creature you control\. "
    r"if you have a full party, put (?P<n2>\d+) \+1/\+1 counters on that creature instead"
)


def _add_counter_target_full_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "kind": "+1/+1", "target_kind": "creature_you_control",
        "amount_if_full_party": int(m.group("n2")),
    })]


def _reveal_until_type(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    tail = m.group("rest")
    # "put that card onto the battlefield **tapped**" (Clifftop Lookout) —
    # `dig_until`'s `_place_dig_hit` has no tapped-entry mode, and a land
    # entering tapped vs untapped is a real difference; fail closed.
    if re.match(r"(?i)^\s*tapped\b", tail):
        return None
    rest_dest = next((d for rx, d in _DIG_UNTIL_REST_RES if rx.search(tail)), None)
    if rest_dest is None:
        return None
    return [EffectSpec("dig_until", {
        "criteria": dict(_DIG_UNTIL_PRED[m.group("pred")]),
        "hit_destination": _DIG_UNTIL_HIT[m.group("hit")],
        "rest_destination": rest_dest,
    })]


#: PAR-30 — the single biggest RULE 701-trail sub-cluster (~100 SOLO cache
#: cards): a trailing "[Then] sacrifice / exile <it / that creature / that
#: token / them / those tokens> at the beginning of [the/your] next end
#: step." (Kiki-Jiki / Twinflame / every "create a token …, exile it" and
#: "reanimate …, sacrifice it" card). RULE 603.7 delayed trigger over
#: `create_delayed_trigger` — the same primitive the hand-authored
#: Kiki-Jiki/Twinflame entries use, with a new ``capture="previous_or_
#: self"`` that bakes in whatever the *earlier clause of this same
#: resolution* chose (RULE 115 target — `GameContext.previous_targets`) or
#: created (RULE 608.2 — `created_objects`), falling back to the ability's
#: own source for a bare self-subject "sacrifice it" (Brackwater Elemental /
#: Deathknell Kami). Deliberately **not** `previous_subject_only`: the
#: capture no-ops cleanly on an empty referent chain (same safety the
#: exile→copy connector relies on), and a create-token antecedent never
#: sets the segmenter's `previous_subject` flag, so gating would miss the
#: majority of the cluster.
#: PAR-80: "~" (Wine of Blood and Iron's "Sacrifice ~ at the beginning of
#: the next end step.") is an *explicit* self-reference, unlike "it"/"that
#: creature"'s `previous_or_self` chain — it never means whatever an
#: earlier clause of the same resolution targeted/created (Wine of Blood
#: and Iron's own earlier clause targets the creature it *pumps*, not
#: itself), so it gets its own unconditional ``capture="self"`` rather than
#: joining the ``obj`` alternation's `previous_or_self` group.
#: PAR-117 (residue): an optional "**its controller** sacrifices/exiles/
#: destroys `<it>` …" subject (Celestial Sword/Goblin Ski Patrol — "Its
#: controller sacrifices it at the beginning of the next end step.") is
#: *not* a fourth referent needing its own plumbing: RULE 701.17a already
#: means "sacrifice" is inherently self-directed — a permanent's sacrifice
#: always comes from **its own** controller, never another player's — so
#: `SacrificeSpecificEffect.apply` (`context.engine.put_into_graveyard
#: (obj)`) never reads a player at all, only the object. "Its controller
#: sacrifices it" and a bare "sacrifice it" therefore compile to the
#: identical spec; only the recognition needed widening, not `capture`/the
#: effect type. Third-person "sacrifices"/"exiles"/"destroys" only ever
#: appears with this explicit subject present (an unprefixed clause is
#: always the imperative "sacrifice"/"exile"/"destroy"), so the two forms
#: don't need disambiguating beyond the verb conjugation itself.
_DELAYED_SAC_EXILE_TAIL_RE = _c(
    r"(?:then )?(?:"
    # PAR-98: Goblin Sappers destroys the earlier target *and* itself at
    # end of combat.  These become two delayed triggers because each has a
    # different captured referent.
    r"(?P<verb_double>destroy) (?P<obj_double>it) and (?P<obj_double_self>~)"
    r"|"
    r"(?:its controller (?P<verb_ctrl>sacrifices|exiles|destroys)"
    r"|(?P<verb>sacrifice|exile|destroy|discard)) "
    r"(?:(?P<obj>it|that creature|that token|the tokens?|that permanent|that artifact|those tokens|them|all tokens created this way|the duplicate)|(?P<obj_self>~))"
    # "Return that creature to its owner's hand" (Ilharg, Zara, Alora) — a
    # loan bounced end of turn; the object is the same `previous_or_self`
    # referent the sacrifice/exile forms use.
    r"|(?P<verb_return>return) (?:it|that creature|that token|that permanent) to (?:your|its owner'?s) hand"
    # "It phases out at end of combat" (Teferi's Veil, PAR-123) — the subject leads the verb.
    r"|(?P<phase_subject>it|that creature|that permanent) phases? out"
    r") "
    # "at end of combat" (Kari Zev, Calamity, every "tapped and attacking"
    # token) fires at the `end_combat` step, "the/your next end step" at the
    # ordinary `end` step (RULE 603.7).
    r"(?P<when>at the beginning of (?:the|your) next end step|at end of combat)"
)
#: "~ becomes a copy of [another] target `<creature|permanent>`[ until end of turn][, except `<tail>`]" (Cursed
#: Mirror, Shameless Charlatan, Cryptoplasm — "…you may have ~ become…" after `_peel_optional`). PAR-142 added the
#: copy's own "except …" clause: "it has this ability" keeps the object's own abilities; the rest is the same
#: type/keyword/legendary vocabulary an enter-as-copy replacement reads (`static_handlers._enter_as_copy_tail`).
_BECOME_COPY_RE = _c(
    r"(?:(?:you may )?have )?~ becomes? a copy of (?:another )?target (?P<what>creature|permanent)"
    r"(?P<eot> until end of turn)?(?:,? except (?P<tail>.+))?"
)


def _become_copy_of_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .static_handlers import _enter_as_copy_tail  # local: imports handlers

    params: dict = {"target_kind": m.group("what").lower()}
    tail = m.group("tail")
    if tail:
        keep_own = re.search(r"(?:,\s*(?:and\s+)?|\s+and\s+)?\bit has this ability\b", tail)
        if keep_own is not None:
            params["keep_own_abilities"] = True
            tail = (tail[: keep_own.start()] + tail[keep_own.end():]).strip(" ,.")
        if tail:
            extra = _enter_as_copy_tail(tail)
            if extra is None or "extra_counters_from_x" in extra:
                return None
            params.update(extra)
    return [EffectSpec(
        "become_copy_until_eot" if m.group("eot") else "become_copy_permanent", params,
    )]


_DELAYED_TAIL_INNER = {
    "sacrifice": "sacrifice_specific",
    "exile": "exile_specific",
    "destroy": "destroy_specific",  # Old Hob, Alleycat Blues
    "return": "return_specific_to_hand",  # Ilharg, Zara, Alora
    "discard": "discard_specific",  # Spellchain Scatter
}


def _delayed_sac_exile_tail(m: re.Match[str]) -> list[EffectSpec]:
    if m.groupdict().get("verb_double"):
        step = "end_combat" if m.group("when").lower() == "at end of combat" else "end"
        return [
            EffectSpec("create_delayed_trigger", {
                "step": step, "scope": "any", "capture": "previous_or_self",
                "effects": [{"type": "destroy_specific", "params": {}}],
            }),
            EffectSpec("create_delayed_trigger", {
                "step": step, "scope": "any", "capture": "self",
                "effects": [{"type": "destroy_specific", "params": {}}],
            }),
        ]
    if m.groupdict().get("phase_subject"):
        step = "end_combat" if m.group("when").lower() == "at end of combat" else "end"
        return [EffectSpec("create_delayed_trigger", {
            "step": step, "scope": "any", "capture": "previous_or_self",
            "effects": [{"type": "phase_out", "params": {}}],
        })]
    verb_ctrl = m.groupdict().get("verb_ctrl")
    verb = (
        m.groupdict().get("verb") or m.groupdict().get("verb_return")
        or (verb_ctrl.rstrip("s") if verb_ctrl else "")
    ).lower()
    inner = _DELAYED_TAIL_INNER[verb]
    step = "end_combat" if m.group("when").lower() == "at end of combat" else "end"
    obj = (m.groupdict().get("obj") or "").lower()
    if m.groupdict().get("obj_self"):
        capture = "self"
    elif obj in _DELAYED_TAIL_TOKEN_SUBJECTS:
        capture = "created_objects"
    else:
        capture = "previous_or_self"
    return [EffectSpec("create_delayed_trigger", {
        "step": step,
        "scope": "any",
        "capture": capture,
        "effects": [{"type": inner, "params": {}}],
    })]


#: PAR-139: "If that creature would leave the battlefield, exile it instead of putting it anywhere else." — the
#: tail of a corpse-counter reanimation (From the Catacombs, Isareth the Awakener). "That creature" is the card
#: the earlier clause returned, so the row is gated on that clause having chosen one (`previous_subject_only`).
_EXILE_INSTEAD_OF_LEAVING_RE = _c(
    r"if that creature would leave the battlefield, exile it instead of putting it anywhere else"
)


def _exile_instead_of_leaving(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile_instead_of_leaving", {})]


#: PAR-139: "its owner shuffles their graveyard into their library" — the tail of "When ~ is put into a graveyard
#: from anywhere, …" (Emrakul, the Aeons Torn; Ulamog, the Infinite Gyre). "Its" is the ability's own source.
_OWNER_SHUFFLES_GRAVEYARD_RE = _c(r"its owner shuffles their graveyard into their library")


def _owner_shuffles_graveyard(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("shuffle_graveyard_into_library", {"owner_of_source": True})]


#: PAR-136: "Return that card to the battlefield under its owner's control at the beginning of the next end
#: step." — the delayed half of a flicker (Flickerwisp, Turn to Mist, Aetherling's self-blink, Ghostway).
#: A separate, *gated* row rather than a verb of `_DELAYED_SAC_EXILE_TAIL_RE`: "it" must name a card an
#: earlier clause of the same ability just **exiled** (`previous_subject_only`, or the ability's own source
#: for "exile ~. Return it …", `self_subject_only`). Ungated it also claimed a *dies* trigger's
#: "return it to the battlefield …" (Resurrection Orb), where nothing is in exile and the effect would
#: silently do nothing.
_DELAYED_RETURN_BATTLEFIELD_RE = _c(
    r"return (?:it|that card|that creature|that permanent|them|those cards|the exiled cards?) to the "
    r"battlefield(?P<tapped> tapped)? under (?:its|their) (?:owner'?s|owners') control at the beginning of the next end step"
)


def _delayed_return_battlefield(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_delayed_trigger", {
        "step": "end", "scope": "any", "capture": "previous_or_self",
        "effects": [{"type": "return_specific_to_battlefield", "params": {"tapped": True} if m.group("tapped") else {}}],
    })]


#: The *when-first* sibling of `_DELAYED_SAC_EXILE_TAIL_RE` — "At the
#: beginning of the next end step, sacrifice/exile/return `<it>`[ unless
#: `<X>`][. If you do, `<effect>`.]" (Apprentice Necromancer, Momo's Heist,
#: Skirk Alarmist, The Beamtown Bullies, Sauron the Necromancer — MEC-52;
#: the "return" branch and the trailing "if you do" — PAR-79 eighth
#: increment — add the Alora cycle, Ilharg/Zara's own "when-first" phrasing
#: sibling). Same `previous_or_self` capture and inner effect as the tail
#: form; the optional trailing "unless ~ is your Ring-bearer" rider (RULE
#: 603.4 intervening-if — Sauron only) is threaded as `create_delayed_
#: trigger`'s new whitelisted ``condition`` param
#: (`_ALLOWED_CONDITION_KEYS["is_ring_bearer"]`, ``False`` = "…unless").
#: Other "unless" riders on this shape (Satya "unless you pay {E}…",
#: Tilonalli's Summoner "unless you have the city's blessing") are a
#: pay-cost / designation check this doesn't model — they stay fail-closed.
#:
#: RULE 603.3's "if you do" here is the *delayed ability's own* reflexive
#: trigger, not `_may_effect_then`'s "you may" gate — nothing about this
#: shape makes the antecedent optional at all (there's no "may"; sacrifice/
#: exile/return happens unconditionally once the delayed ability fires), so
#: unlike `_SACRIFICE_THEN_WHEN_YOU_DO_RE`'s "certain, so collapse" idiom
#: this isn't a simplification — RULE 603.3's "if you do" is trivially true
#: whenever the antecedent could apply at all (`ReturnSpecificToHandEffect`/
#: `SacrificeSpecificEffect`'s own "skip if it already left the battlefield"
#: no-op is the one case it doesn't, and this ability then correctly does
#: nothing further either). The recursively-parsed "after" tail is appended
#: to the *same* delayed trigger's ``effects`` list rather than opened as a
#: second delayed trigger of its own, so both run off the one `DelayedTrigger`
#: this ability arms — correct RULE 608.2/603.7 sequencing (the follow-up
#: never fires as a separate, independently-timed trigger). No `previous_
#: subject` propagation into the "after" parse: `CreateDelayedTriggerEffect`'s
#: own ``capture="previous_or_self"`` bakes the referent directly onto every
#: inner effect exposing ``.objects``/``.target`` *at arm time* (this
#: resolution's `GameContext.previous_targets`), not read again when the
#: delayed ability fires — by then `previous_targets` could hold anything
#: (a wholly unrelated later resolution's targets) or nothing, so an "if you
#: do" tail naming "it" again (Alora, Cheerful Scout's "it perpetually gets
#: +1/+1") isn't reachable through this recursive parse and stays fail-closed
#: (a `.target`-bearing effect built with no target set is worse than
#: UNMODELED) — real, separately-scoped residue, not attempted here.
_DELAYED_SAC_EXILE_WHEN_FIRST_RE = _c(
    r"at the beginning of (?:the|your) next end step, "
    r"(?:"
    r"(?P<verb>sacrifice|exile) "
    r"(?P<obj>it|that creature|that token|that permanent|that artifact|that vehicle|those tokens|the tokens?)"
    r"|(?P<verb_return>return) "
    r"(?P<obj_return>it|that creature|that token|that permanent) to "
    r"(?:your|its owner'?s) hand"
    r")"
    r"(?P<unless> unless ~ is your ring-bearer)?"
    r"(?:\.\s*(?:if|when) you do,\s*(?P<after>.+))?"
)

#: Object phrases that can only mean "the token(s) an earlier clause of this
#: same resolution *created*" (RULE 608.2) — never a RULE 115 target it also
#: chose. For these the delayed trigger must capture `GameContext.created_
#: objects` directly; "it"/"that creature"/"that permanent" stay on
#: `previous_or_self` (target first, then created, then the source).
_DELAYED_TAIL_TOKEN_SUBJECTS: frozenset[str] = frozenset(
    {"that token", "those tokens", "the token", "the tokens", "all tokens created this way",
     # PAR-124: "conjure a duplicate of that spell into your hand. …
     # Discard the duplicate …" (Spellchain Scatter) — the same "this
     # resolution's own created referent" idiom as the token subjects
     # above, just not a permanent token.
     "the duplicate"}
)


def _delayed_sac_exile_when_first(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    verb = (m.groupdict().get("verb") or m.groupdict().get("verb_return") or "").lower()
    inner = _DELAYED_TAIL_INNER[verb]
    obj = (m.groupdict().get("obj") or m.groupdict().get("obj_return") or "").strip().lower()
    effects_list: list[dict] = [{"type": inner, "params": {}}]
    after = (m.groupdict().get("after") or "").strip()
    if after:
        # No `previous_subject`/`self_subject` here on purpose — see this
        # regex's own docstring on why a pronoun naming "it"/"that creature"
        # again can't be resolved through this recursive parse and must
        # fail closed instead of guessing.
        after_specs = parse_effect_body(after)
        if after_specs is None:
            return None  # fail closed — the "if you do" follow-up isn't modeled
        if any(s.params.get("target_kind") for s in after_specs):
            # A genuine RULE 115 target needs its own announced-target step
            # (same reasoning `_may_effect_then` rejects one for) — this
            # delayed trigger's effects resolve off-stack with no
            # target-gathering of their own.
            return None
        effects_list.extend(s.to_dict() for s in after_specs)
    params: dict = {
        "step": "end",
        "scope": "any",
        "capture": (
            "created_objects" if obj in _DELAYED_TAIL_TOKEN_SUBJECTS
            else "previous_or_self"
        ),
        "effects": effects_list,
    }
    if m.groupdict().get("unless"):
        # "…unless ~ is your Ring-bearer" — the delayed ability doesn't
        # trigger at all while ~ is the Ring-bearer (so the token stays).
        params["condition"] = {"is_ring_bearer": False}
    return [EffectSpec("create_delayed_trigger", params)]


#: ENG-30: "They [each] get +N/+N [and gain `<kw>`]/gain `<kw>` until end of
#: turn." (A-Bretagard Stronghold/Fancy Footwork-shaped, following "…1 or 2
#: target creatures…") — the pump-family sibling of `_UNTAP_PREVIOUS_GROUP_
#: RE` just above: "they" is the RULE 115 target *group* the preceding
#: clause chose (`PumpEffect.previous_subject`/`GameContext.
#: previous_targets`), not a mass selector — that's `_PUMP_PREVIOUS_
#: SELECTOR_RE`'s own, separately-gated (`previous_selector_only`) row,
#: which this can't collide with since `match_clause` only ever tries the
#: one whose gate the actual preceding clause satisfied. Two rows (P/T vs.
#: keyword-only) rather than one combined regex, mirroring `_pump`/`_pump_
#: keyword`'s own split for the ordinary targeted form.
#: "they"/"those creatures"/"each of those creatures" — all name the RULE
#: 115 target group the preceding clause chose (`GameContext.
#: previous_targets`); the wordier forms are what most real cards actually
#: print ("Arm the Cathars", "Cauldron Haze", …).
_PREV_GROUP_SUBJECT = r"(?:they|those creatures|each of those creatures)"
_PUMP_PREVIOUS_TARGETS_PT_RE = _c(
    rf"{_PREV_GROUP_SUBJECT}(?: each)? gets? (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"
    r"(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)
_PUMP_PREVIOUS_TARGETS_KW_RE = _c(
    rf"{_PREV_GROUP_SUBJECT}(?: each)? gains? (?P<kw>[a-z][a-z, ]*?) until end of turn"
)


def _pump_previous_targets_pt(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "previous_subject": True,
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def _pump_previous_targets_kw(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    if m.groupdict().get("must_blocked"):
        keywords = [*keywords, "must_be_blocked"]
    return [EffectSpec("pump", {"keywords": keywords, "previous_subject": True})]


#: PAR-30: the singular-pronoun sibling of `_PUMP_PREVIOUS_TARGETS_*_RE` —
#: "it [also] gets +N/+N [and gains `<kw>`] until end of turn" / "it [also]
#: gains `<kw>` until end of turn", where "it"/"that creature"/"that
#: permanent" is the single RULE 115 target the preceding split clause chose
#: (`GameContext.previous_targets`, `PumpEffect.previous_subject`). Real
#: cards run this off a threaten clause's own restatement tail ("gain
#: control of target creature until end of turn. untap that creature. **it**
#: gains haste …") when a further sentence keeps `segmenter.
#: _GAIN_CONTROL_HASTE_TAIL_RE` from absorbing the pair whole, and off clash
#: "if you win, **that creature** gets +2/+2 …" payoffs (RULE 701.30d).
#: Gated `previous_subject_only`, so it only competes once the preceding
#: clause actually bound the pronoun.
_PREV_SUBJECT_SINGULAR = r"(?:it|that creature|that permanent|that artifact|that token|the token)"
_PUMP_PREV_SINGULAR_PT_RE = _c(
    rf"{_PREV_SUBJECT_SINGULAR}(?: also)? gets? (?:an additional )?(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"
    r"(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)
_PUMP_PREV_SINGULAR_KW_RE = _c(
    rf"{_PREV_SUBJECT_SINGULAR}(?: also)? gains? (?P<kw>[a-z][a-z, ]*?) until end of turn"
    # PAR-124: "…and must be blocked this turn if able." (Magitek Scythe).
    rf"(?P<must_blocked> and must be blocked this turn if able)?"
)

#: Batch 4: the bare "It gains haste." / "That token gains haste." a token- or copy-making (or reanimating)
#: clause is followed by — no duration is printed, so the grant is what it says: indefinite (RULE 611.2c's
#: omitted-duration default, `rest_of_game`). Haste only: any other bare grant stays unclaimed.
_PUMP_PREV_HASTE_BARE_RE = _c(rf"{_PREV_SUBJECT_SINGULAR} gains haste")


def _pump_prev_haste_bare(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_until", {
        "static": {"type": "grant_keyword", "params": {"keywords": ["haste"]}},
        "duration": "rest_of_game", "previous_subject": True, "target_kind": None,
    })]


#: PAR-30 "Threaten / 'it gains haste' tails residue" — the *rich* leading-
#: "until end of turn, it …" restatement a threaten clause pairs with,
#: beyond a bare keyword grant (`segmenter._GAIN_CONTROL_HASTE_TAIL_RE`
#: recurses this whole sentence here with ``previous_subject`` on):
#:   * "…it gains haste and '<quoted ability>'" (Furnace Reins, Shackles of
#:     Treachery) — reuses `static_handlers._quoted_ability_grant_effects`
#:     wrapped in `grant_until(previous_subject=True)`;
#:   * "…it becomes a <subtype> in addition to its other types and gains
#:     haste" (Loki's Scepter) — a layer-4 `type_change` add-subtype grant;
#:   * "…it has base power and toughness N/N and gains <kws>" (Flayer of
#:     Loyalties) — a layer-7b `pt_set` grant + the residual keyword list.
#: The redundant "haste" is dropped (the `gain_control_until_eot` effect
#: already grants it as part of the control change).
_GAIN_CONTROL_RICH_PREV_GRANT_RE = _c(
    r"until end of turn, (?:it|they) (?:"
    r"gains? haste and \"(?P<quoted>.+)\""
    r"|becomes? an? (?P<subtype>[a-z][a-z]+) in addition to its other types and gains? haste"
    r"|has base power and toughness (?P<bp>\d+)/(?P<bt>\d+) and gains? (?P<kw>[a-z0-9, ]+)"
    r")"
)


def _gain_control_rich_prev_grant(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("quoted"):
        from .static_handlers import _quoted_ability_grant_effects  # local: module cycle

        grant = _quoted_ability_grant_effects(m.group("quoted"))
        if grant is None:
            return None
        params = {k: v for k, v in grant.params.items() if k != "affects"}
        return [EffectSpec("grant_until", {
            "static": {"type": grant.type, "params": params},
            "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
        })]
    if m.group("subtype"):
        return [EffectSpec("grant_until", {
            "static": {"type": "type_change",
                       "params": {"add_subtypes": [m.group("subtype").capitalize()]}},
            "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
        })]
    split = _split_keywords_with_parametric(m.group("kw"))
    if split is None:
        return None
    flags, parametric = split
    flags = [f for f in flags if f != "haste"]
    out: list[EffectSpec] = [EffectSpec("grant_until", {
        "static": {"type": "pt_set",
                   "params": {"power": int(m.group("bp")), "toughness": int(m.group("bt"))}},
        "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
    })]
    if flags or parametric:
        pump_params: dict = {"previous_subject": True}
        if flags:
            pump_params["keywords"] = flags
        if parametric:
            pump_params["parametric_keywords"] = parametric
        out.append(EffectSpec("pump", pump_params))
    return out


#: PAR-30 "Threaten … tails residue" — the two card-specific conditional
#: after-tails a threaten clause carries, each gated on the creature the
#: threaten just chose (`ConditionalEffect`'s `previous_target_*` keys,
#: reading `GameContext.previous_targets`):
#:   * "if that creature is a <subtype>, it also gets +N/+M until end of
#:     turn" (Goatnap — "if that creature is a Goat, it also gets +3/+0");
#:   * "if it's equipped, you may destroy all Equipment attached to that
#:     creature" (Awaken the Sleeper — the "you may" isn't offered as an
#:     interactive choice, see `_MASS_DESTROY_SELECTORS`).
_IF_PREV_SUBTYPE_PUMP_RE = _c(
    r"if (?:that creature|it) is an? (?P<sub>[a-z][a-z-]+), "
    r"(?:it|that creature) (?:also )?gets (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+) until end of turn"
)


def _if_prev_subtype_pump(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "previous_subject": True,
    }, condition={"previous_target_has_subtype": m.group("sub")})]


_IF_PREV_EQUIPPED_DESTROY_RE = _c(
    r"if (?:it'?s|that creature is) equipped, (?:you may )?destroy all equipment "
    r"attached to (?:it|that creature)"
)


def _if_prev_equipped_destroy(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("destroy", {
        "selector": "equipment_attached_to_previous",
    }, condition={"previous_target_is_equipped": True})]


#: MEC-28: "They gain first strike until end of turn." (Karlach, Fury of
#: Avernus's own trailing sentence, following "untap all attacking
#: creatures.") — the *mass-selector* sibling of the row above: "they" isn't
#: a RULE 115 targeted group at all (`_UNTAP_PREVIOUS_GROUP_RE`'s own
#: `previous_subject`/`GameContext.previous_targets` idiom), it's whichever
#: group the *previous clause's own selector* (RULE 601.2c, untargeted) just
#: acted on — `PumpEffect`'s new ``selector="previous_selector"`` sentinel,
#: resolved at apply time off the new `GameContext.previous_selector` field
#: `_apply_effects_partitioned` now tracks alongside `previous_targets`.
#: Only offered when the preceding split clause's own spec really used a
#: recognised group selector (`segmenter._announces_group_selector`,
#: `EffectHandler.previous_selector_only`) — never reused for
#: `previous_subject_only`'s existing meaning, a deliberately separate gate.
_PUMP_PREVIOUS_SELECTOR_RE = _c(
    rf"{_PREV_GROUP_SUBJECT} gains? (?P<kw>[a-z, ]+?) until end of turn"
)


def _pump_previous_selector(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {"keywords": keywords, "selector": "previous_selector"})]


#: "target creature gets +1/+0 until end of turn and can't be blocked this
#: turn" (You Come to a River-shaped) — the P/T-then-unblockable ordering
#: (unlike `_pump`'s "and gains <kw> until end of turn", the keyword clause
#: sits *before* "until end of turn"; here "can't be blocked this turn"
#: trails it instead). Widened to the broader `_SUBJECT` (PAR-72, Seafloor
#: Stalker's own activated-ability self-pump "~ gets +1/+0 … and can't be
#: blocked this turn") rather than `TARGET` alone.
_PUMP_UNBLOCKABLE_RE = _c(
    rf"{_SUBJECT} gets? {_PT_DELTA} until end of turn and can'?t be blocked this turn"
)


def _pump_unblockable(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    # PAR-79: "target creature you control gets +1/+0 … and can't be
    # blocked this turn" (Teleportal) — this row's own allowed set had
    # fallen behind its keyword-grant sibling `_pump_keyword_unblockable`
    # (which already allows the controller-scoped kinds, Apocalypse
    # Runner) and the bare `_cant_be_blocked_turn` row, both of which
    # treat "you control"/"you don't control" as ordinary legal unblockable
    # subjects; this row had simply never been widened to match.
    if target_kind is not None and not target_kind_allowed(target_kind, (
        "creature", "permanent", "creature_you_control", "creature_you_dont_control",
    )):
        return None
    params: dict = {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "unblockable": True,
    }
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: ENG-32: a bare "~ / target creature can't be blocked this turn" (Giant
#: Koi's own activated ability / Waterbender Ascension) — the standalone
#: `UnblockableEffect`, no P/T delta (that's `_PUMP_UNBLOCKABLE_RE` above).
#: PAR-79 widened it with the same optional "with power N or less/greater"
#: suffix as `_PUMP_KEYWORD_UNBLOCKABLE_RE` (Crafty Pathmage-shaped).
#: PAR-79: an optional "except by `<filter>`" tail (Departed Deckhand/
#: Gingerbrute/Joven's Tools/Resilient Roadrunner/Tin Street Dodger/
#: Varchild's Crusader) — RULE 509.1b's *permitted*-set restriction
#: (`combat.blocker_allowed`'s existing `"only_blocked_by"` arm, already
#: shipped for the standing static — `static_handlers.py`'s own "~ can
#: only be blocked by `<filter>`" row), reusing `object_filter`'s existing
#: vocabulary rather than a new one. Routes to a different `EffectSpec`
#: type (`combat_restriction_this_turn`) than the bare form, so this stays
#: in `_cant_be_blocked_turn` rather than becoming a second regex.
#: PAR-98 widened the target qualifier from "with power N or less/greater" to
#: the shared `_CREATURE_FILTER_SUFFIX` vocabulary (power/toughness/keyword/
#: counter), so Speed, Young Avenger's "target creature **with haste** can't be
#: blocked this turn except by creatures with haste" parses alongside it.
_CANT_BE_BLOCKED_TURN_RE = _c(
    rf"(?:(?P<selfref>{_SELF_SUBJECT})|{TARGET})"
    rf"(?: {_CREATURE_FILTER_SUFFIX})? can'?t be blocked this turn"
    r"(?: except by (?P<filter>.+))?"
)

#: PAR-79 sixth increment: "…except by N or more creatures" (Unquenchable
#: Fury) — a blocker-*count* requirement (RULE 509.1c), not a characteristic
#: filter, so it routes to `combat.min_blockers` (the same ``"min_blockers"``
#: restriction kind `static_handlers._TAIL_RES` already uses for the
#: standing-static "can't be blocked except by N or more creatures" form)
#: rather than through `object_filter` — which would otherwise mis-read "2"
#: as a bogus subtype word before `_scope`'s own digit guard (PAR-79 third
#: increment) correctly failed it closed. Checked before the general filter
#: route in `_cant_be_blocked_turn` below.
_CANT_BE_BLOCKED_TURN_MIN_BLOCKERS_RE = re.compile(
    r"^(?P<n>\d+) or more creatures\.?$", re.IGNORECASE
)


def _except_by_restriction(text: str) -> Optional[dict]:
    """The RULE 509.1b restriction dict for an "…except by `<filter>`" tail:
    a blocker-count requirement (RULE 509.1c) or a permitted-blocker filter."""
    min_blockers = _CANT_BE_BLOCKED_TURN_MIN_BLOCKERS_RE.fullmatch(text.strip())
    if min_blockers is not None:
        return {"kind": "min_blockers", "count": int(min_blockers.group("n"))}
    from .static_handlers import object_filter

    filt = object_filter(text)
    if filt is None:
        return None
    return {"kind": "only_blocked_by", "filter": filt}


def _cant_be_blocked_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {}
    if m.groupdict().get("selfref"):
        params["target_kind"] = None
    else:
        kind = resolve_target_kind(m.group("target"))
        # "another target creature you control can't be blocked this turn
        # except by spirits." (Departed Deckhand, PAR-79) — RULE 109.5's
        # "another … you control" resolves to `other_creature_you_control`
        # (`subgrammars.py`), the same kind `_pump_target`'s own broader
        # allowed set already accepts.
        if not target_kind_allowed(kind, (
            "creature", "permanent", "creature_you_control", "creature_you_dont_control",
            "other_creature_you_control",
        )):
            return None
        params["target_kind"] = kind
    quality_filter = _creature_quality_filter(m)
    if quality_filter is not None and params["target_kind"] is None:
        return None  # a target-quality qualifier needs a real RULE 115 target, not the bare self form
    if m.groupdict().get("filter"):
        restriction_params: dict = {}
        restriction = _except_by_restriction(m.group("filter"))
        if restriction is None:
            return None
        restriction_params["restriction"] = restriction
        if params["target_kind"] is not None:
            restriction_params["target_kind"] = params["target_kind"]
        if quality_filter is not None:
            restriction_params["creature_filter"] = quality_filter
        return [EffectSpec("combat_restriction_this_turn", restriction_params)]
    if quality_filter is not None:
        params["creature_filter"] = quality_filter
    # "up to one target attacking creature can't be blocked this turn"
    # (Alora, Merry Thief) / "…with power 3 or less…" (Gossip's Talent) —
    # see `_destroy`'s own comment: `resolve_target_kind` alone drops the
    # qualifier, same bug in this effect family.
    if not m.groupdict().get("selfref"):
        state_filter = resolve_target_creature_state_filter(m.group("target"))
        if state_filter:
            params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("unblockable", params)]


#: PAR-79 sixth increment: "Put 2 +1/+1 counters on target creature you
#: control. **That creature** can't be blocked this turn." (Stealth
#: Mission/Trygon Prime-shaped) — the same previous-clause pronoun idiom
#: `_PHASE_OUT_PREVIOUS_RE`/`_FIGHT_PREVIOUS_RE` already use, for
#: `UnblockableEffect.previous_subject` instead.
_CANT_BE_BLOCKED_TURN_PREVIOUS_RE = _c(rf"{_THEN}{_PREVIOUS_SUBJECT} can'?t be blocked this turn")


def _equipped_creature_unblockable(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("unblockable", {"target_kind": "attached_permanent"})]


# PAR-98: Martha Jones' source plus an independently optional second target
# are two effects, not a two-target RULE 115 declaration (the source is
# always affected even when no other creature is chosen).
_SELF_AND_OTHER_UNBLOCKABLE_RE = _c(
    r"~ and up to 1 other target creature(?: you control)? can'?t be blocked this turn"
)


def _self_and_other_unblockable(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("unblockable", {"target_kind": None}),
        EffectSpec("unblockable", {"target_kind": "other_creature", "optional": True}),
    ]


_COLOR_CREATURES_UNBLOCKABLE_RE = _c(
    r"(?P<color>white|blue|black|red|green) creatures you control can'?t be blocked this turn "
    r"except by (?P=color) creatures"
)


def _color_creatures_unblockable(m: re.Match[str]) -> list[EffectSpec]:
    color = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[m.group("color").lower()]
    return [EffectSpec("combat_restriction_this_turn", {
        "selector": "creatures_you_control", "selector_params": {"color": [color]},
        "restriction": {"kind": "only_blocked_by", "filter": {"color": color}},
    })]


_X_POWER_UNBLOCKABLE_RE = _c(
    r"target creature with power x or less can'?t be blocked this turn"
)
_X_TARGETS_UNBLOCKABLE_RE = _c(
    r"x target creatures with power (?P<p>\d+) or less can'?t be blocked this turn"
)


def _x_power_unblockable(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("unblockable", {
        "target_kind": "creature", "creature_filter": {"max_power_from_source_x": True},
    })]


def _x_targets_unblockable(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("unblockable", {
        "target_kind": "creature", "count_selector": "source_x_paid",
        "creature_filter": {"max_power": int(m.group("p"))},
    })]


def _cant_be_blocked_turn_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("unblockable", {"previous_subject": True})]


#: PAR-124: "`<earlier clause targeted/animated a creature>`. **It** must be
#: blocked this turn if able." (Enlarge, King Harald's Revenge, Disturbed
#: Slumber/Elemental Uprising/Vengeant Earth's animate-land family) — the
#: "must" mirror of `_CANT_BE_BLOCKED_TURN_PREVIOUS_RE` just above.
#: "must_be_blocked" is a plain flag keyword (`combat.has`, RULE 509.1c),
#: so the same `PumpEffect.previous_subject`/``keywords`` idiom that already
#: grants it via a standing static (Raphael, Ninja Destroyer) grants it here
#: as a resolve-time temporary keyword instead — no new primitive.
_MUST_BE_BLOCKED_TURN_PREVIOUS_RE = _c(rf"{_THEN}{_PREVIOUS_SUBJECT} must be blocked this turn if able")


def _must_be_blocked_turn_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {"previous_subject": True, "keywords": ["must_be_blocked"]})]


#: PAR-98: "`<earlier clause targeted creatures>`. **They** can't be blocked
#: this turn except by creatures with haste." (Run for Your Life) — the
#: plural-referent, "except by" sibling of `_CANT_BE_BLOCKED_TURN_PREVIOUS_RE`
#: above. Reads `GameContext.previous_targets` for *every* creature the
#: previous clause chose (RULE 608.2), through `GrantCombatRestrictionEffect`'s
#: new ``previous_subject`` mode.
_CANT_BE_BLOCKED_EXCEPT_PREVIOUS_RE = _c(
    rf"{_THEN}(?:{_PREVIOUS_SUBJECT}|they|those creatures) can'?t be blocked this turn "
    r"except by (?P<filter>.+)"
)


def _cant_be_blocked_except_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    restriction = _except_by_restriction(m.group("filter"))
    if restriction is None:
        return None
    return [EffectSpec("combat_restriction_this_turn", {
        "restriction": restriction, "previous_subject": True,
    })]


#: PAR-98: Agility Bobblehead's "up to X target creatures you control each
#: gain `<keywords>` until end of turn and can't be blocked this turn except by
#: `<filter>`, where X is the number of `<subtype>`s you control as you
#: activate this ability." — one sentence, two effects: a multi-target keyword
#: grant plus the previous-subject "except by" restriction. X is read when the
#: targets are announced (RULE 601.2c — "as you activate"), which is exactly
#: when `TargetSpec.count_selector` is evaluated.
_KW_GRANT_UNBLOCKABLE_EXCEPT_X_RE = _c(
    r"up to x target creatures you control each gains? (?P<kw>[a-z][a-z, ]*?) until end of turn "
    r"and can'?t be blocked this turn except by (?P<filter>.+?), "
    r"where x is the number of (?P<what>[a-z]+?)s you control as you activate this ability"
)


def _kw_grant_unblockable_except_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    restriction = _except_by_restriction(m.group("filter"))
    if keywords is None or restriction is None:
        return None
    return [
        EffectSpec("pump", {
            "keywords": keywords, "target_kind": "creature_you_control", "optional": True,
            "count_selector": f"permanents_you_control_of_type_{m.group('what')}",
        }),
        EffectSpec("combat_restriction_this_turn", {
            "restriction": restriction, "previous_subject": True,
        }),
    ]


#: PAR-79: the multi-target form — "up to 2 target creatures can't be
#: blocked this turn." (Ghostform) — RULE 115.1a generalized to N>=2, the
#: shared `_MULTI_TARGET_QUANTIFIER`/`_multi_target_params` machinery
#: every other multi-target row in this file already uses.
_CANT_BE_BLOCKED_TURN_MULTI_RE = _c(
    rf"{_MULTI_TARGET_QUANTIFIER}(?P<target>target creatures) can'?t be blocked this turn"
)


def _cant_be_blocked_turn_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None or params["target_kind"] != "creature":
        return None
    out: dict = {"target_kind": "creature", "count": params["count"]}
    if "count_max" in params:
        out["count_max"] = params["count_max"]
    if params.get("optional"):
        out["optional"] = True
    return [EffectSpec("unblockable", out)]


#: PAR-79: the untargeted mass form — "creatures [you control] can't be
#: blocked this turn." (Jace, Arcane Strategist/Keeper of Keys/Veiling
#: Oddity) — RULE 601.2c, no RULE 115 target at all, `UnblockableEffect`'s
#: new `selector` param (mirroring `CantBlockEffect`'s own mass form).
_CANT_BE_BLOCKED_TURN_MASS_RE = _c(
    r"(?P<group>creatures you control|creatures) can'?t be blocked this turn"
)


def _cant_be_blocked_turn_mass(m: re.Match[str]) -> list[EffectSpec]:
    selector = "creatures_you_control" if m.group("group") == "creatures you control" else "all_creatures"
    return [EffectSpec("unblockable", {"selector": selector})]


#: PAR-79: "~ gains lifelink until end of turn and can't be blocked this
#: turn." (Apocalypse Runner/Break Through the Line/Cephalid Inkshrouder-
#: shaped) — the keyword-grant sibling of `_PUMP_UNBLOCKABLE_RE` above (that
#: one is a P/T delta plus unblockable; this is a keyword list plus
#: unblockable, no P/T change). `PumpEffect` already accepts `keywords` and
#: `unblockable` together (see `_pump_keywords`/`_pump_unblockable`) — this
#: is a parser-recognition gap only, not a new primitive. The optional
#: "with power N or less/greater" suffix (Apocalypse Runner/Break Through
#: the Line) mirrors `_GAIN_CONTROL_EOT_RE`'s own identical suffix —
#: `creature_filter`'s `min_power`/`max_power` keys (`targeting.py`), not a
#: new filter shape.
_PUMP_KEYWORD_UNBLOCKABLE_RE = _c(
    rf"{_SUBJECT}(?: with power (?P<pn>\d+) or (?P<pcmp>less|greater))?"
    r" gains? (?P<kw>[a-z0-9, ]+?) until end of turn and can'?t be blocked this turn"
)


def _pump_keyword_unblockable(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    # Same allowed set as `_cant_be_blocked_turn` above — "creature you
    # control"/"…don't control" are legal unblockable-grant subjects too
    # (Apocalypse Runner); unlike `_pump_unblockable`, this handler has no
    # P/T delta to worry about conflicting with a non-creature target.
    if target_kind is not None and not target_kind_allowed(target_kind, (
        "creature", "permanent", "creature_you_control", "creature_you_dont_control",
    )):
        return None
    split = _split_keywords_with_parametric(m.group("kw"))
    if split is None:
        return None
    flags, parametric = split
    if not flags and not parametric:
        return None
    params: dict = {"unblockable": True}
    if flags:
        params["keywords"] = flags
    if parametric:
        params["parametric_keywords"] = parametric
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    if m.group("pn"):
        key = "max_power" if m.group("pcmp") == "less" else "min_power"
        params["creature_filter"] = {key: int(m.group("pn"))}
    state_filter = _pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


#: PAR-79: "[another ]target `<object-filter phrase>` can't be blocked this
#: turn." (Merfolk Sovereign's "target Merfolk creature"; Aquatic Incursion's
#: bare "target merfolk"; Corsairs of Umbar's "target goblin, orc, or
#: pirate"; Private Eye's "target detective"; Bessie, the Doctor's Roadster's
#: "another target attacking creature"/"another target legendary creature";
#: K-9, Mark I's bare "target legendary creature") — one row over the
#: *shared* `static_handlers.object_filter` vocabulary instead of a
#: hand-rolled, ever-growing word list per adjective: that function
#: resolves a bare subtype, a "`<subtype>` creature[s]" noun phrase, an "A,
#: B, or C"/"A or B" list, and — since `object_filter`'s own
#: `_OBJECT_FILTER_FLAG_WORDS` step — a leading "tapped"/"attacking"/
#: "blocking"/"legendary" flag word too, uniformly (all widenings made to
#: `object_filter` itself, so every other caller — the "except by"
#: restriction, the standing static equivalents — benefits too, not just
#: this one search phrase). This row used to sit *after* two now-deleted
#: dedicated regexes for "attacking"/"legendary" specifically, tried first
#: so `object_filter` never saw those words and mis-guessed them as a bogus
#: subtype (`_scope` doesn't know either word); now that `object_filter`
#: strips them itself, this one row is a strict superset of both and they
#: were removed rather than kept as now-dead duplicates. "another " is a
#: no-op beyond widening the match: plain "creature" target kind already
#: defaults `exclude_source=True` (`targeting.py`), same as
#: `_pump_other_attacking_creature`.
_CANT_BE_BLOCKED_TURN_OBJECT_FILTER_RE = _c(
    r"(?:another )?target (?P<filter>[a-z][a-z, ]*?) can'?t be blocked this turn"
)


def _cant_be_blocked_turn_object_filter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .static_handlers import object_filter

    filt = object_filter(m.group("filter"))
    if filt is None:
        return None
    return [EffectSpec("unblockable", {"target_kind": "creature", "creature_filter": filt})]


#: "Target creature can't block this turn" (Falter/Ahn-Crop Crasher/Abandon
#: the Post) — the *resolve-time* half of the combat-restriction family, and
#: by far its largest: an ordinary one-shot effect (`game/effects/core.py`'s
#: `CantBlockEffect` → `GameObject.temp_cant_block`, cleared at cleanup),
#: not the standing `combat_restriction` static that
#: `catalogue/static_handlers.py` binds. Three shapes, in the order tried
#: below: N targets ("up to two target creatures"), one target, and the
#: untargeted mass form.
_CANT_BLOCK_TURN_MULTI_RE = _c(
    rf"{_MULTI_TARGET_QUANTIFIER}(?P<target>{_MULTI_TARGET_ALT}) can'?t block this turn"
)
_CANT_BLOCK_TURN_RE = _c(rf"{TARGET} can'?t block this turn")

#: The untargeted mass form's own subject vocabulary (RULE 601.2c) — a
#: `continuous.group_selector_objects` selector plus an optional
#: characteristic narrowing (`combat.matches_object_filter`), since
#: "creatures **without flying**" is a real printed scope no selector name
#: covers. Bare "creatures" is every creature on the battlefield.
_CANT_BLOCK_TURN_GROUPS: dict[str, tuple[str, dict]] = {
    "creatures": ("all_creatures", {}),
    "all creatures": ("all_creatures", {}),
    "creatures without flying": ("all_creatures", {"without_keyword": "flying"}),
    "creatures with flying": ("all_creatures", {"keyword": "flying"}),
    "creatures your opponents control": ("opponents_permanents", {}),
    # PAR-128: the controller scope written after the quality filter
    # (Stoneshock Giant's "creatures without flying your opponents control").
    "creatures without flying your opponents control": (
        "opponents_permanents", {"without_keyword": "flying"}),
    "creatures with flying your opponents control": ("opponents_permanents", {"keyword": "flying"}),
    "creatures you control": ("creatures_you_control", {}),
    "creatures you don't control": ("opponents_permanents", {}),
}
_CANT_BLOCK_TURN_GROUP_RE = _c(
    r"(?P<group>" + "|".join(re.escape(g) for g in _CANT_BLOCK_TURN_GROUPS)
    + r") can'?t block this turn"
)


#: "Target creature can't be regenerated this turn." (Gravebind, Hurr Jackal, Furnace
#: Brood) / "It can't be regenerated this turn." (Engulfing Flames, Rage of Purphoros) /
#: "A creature dealt damage this way can't be regenerated this turn." (Incinerate,
#: Flamebreak) — `CantBeRegeneratedEffect`, RULE 701.16. The pronoun and "dealt damage
#: this way" forms only compete once a preceding clause supplied the referent.
_CANT_BE_REGENERATED_TARGET_RE = _c(rf"{TARGET} can'?t be regenerated this turn")
_CANT_BE_REGENERATED_PREV_RE = _c(r"(?:it|that creature) can'?t be regenerated this turn")
_CANT_BE_REGENERATED_HIT_RE = _c(
    r"(?:an?|each) creatures? dealt damage this way can'?t be regenerated this turn"
    r"|creatures dealt damage this way can'?t be regenerated this turn"
)


def _cant_be_regenerated_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or not target_kind_allowed(
        kind, ("creature", "creature_you_control", "creature_you_dont_control")
    ):
        return None
    return [EffectSpec("cant_be_regenerated", {"target_kind": kind})]


def _cant_be_regenerated_prev(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("cant_be_regenerated", {"previous_subject": True})]


def _cant_be_regenerated_hit(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("cant_be_regenerated", {"damaged_this_way": True})]


def _cant_block_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None
    return [EffectSpec("cant_block_this_turn", {"target_kind": kind, **_optional_param(m)})]


def _cant_block_turn_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None or params["target_kind"] != "creature":
        return None
    return [EffectSpec("cant_block_this_turn", params)]


#: "If it's a creature, it can't block this turn." (Searing Barb's own
#: damage-rider tail — "~ deals 2 damage to any target." precedes it; the
#: "any target" can resolve onto a player/planeswalker/battle, so the
#: restriction is gated on the previous clause's target actually being a
#: creature). `CantBlockEffect.previous_subject` acts on
#: `GameContext.previous_targets`; the `ConditionalEffect` gate then
#: short-circuits a non-creature target (`previous_target_is_creature`).
_IF_PREV_CREATURE_CANT_BLOCK_RE = _c(
    r"if it'?s a creature, (?:it|that creature) can'?t block this turn"
)


def _if_prev_creature_cant_block(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(
        "cant_block_this_turn",
        {"previous_subject": True},
        condition={"previous_target_is_creature": True},
    )]


#: "~ can't be blocked by creatures with power 2 or less this turn" (Cavern
#: Stomper) / "target creature can't be blocked by Walls this turn" (Tower of
#: Coireall) — the resolve-time sibling of the standing static that
#: `catalogue/static_handlers.py` claims. Reuses that module's own
#: `_object_filter` so the blocker vocabulary is literally the same one, and
#: only the two subjects real cards print here (``~`` and a single target).
_CANT_BE_BLOCKED_BY_TURN_RE = _c(
    rf"(?:(?P<selfref>~)|{TARGET}) can'?t be blocked by (?P<filter>.+) this turn"
)


def _cant_be_blocked_by_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .static_handlers import object_filter

    filt = object_filter(m.group("filter"))
    if filt is None:
        return None
    params: dict = {"restriction": {"kind": "cant_be_blocked_by", "filter": filt}}
    if not m.group("selfref"):
        kind = resolve_target_kind(m.group("target"))
        if not target_kind_allowed(kind, ("creature", "creature_you_control")):
            return None
        params["target_kind"] = kind
    return [EffectSpec("combat_restriction_this_turn", params)]


def _cant_block_turn_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector, filt = _CANT_BLOCK_TURN_GROUPS[m.group("group").lower()]
    params: dict = {"selector": selector}
    if filt:
        params["filter"] = dict(filt)
    return [EffectSpec("cant_block_this_turn", params)]


#: "Target creature can't block ~ this turn." (RULE 509.1a, Provoke-adjacent
#: but without the untap half) — the *pairwise* sibling of `_cant_block_turn`
#: above: that one bars the target from blocking anything, this one bars it
#: from blocking only this ability's own source. Can't be told apart from a
#: standing static's own filter at parse time (the source's instance id
#: doesn't exist yet), so it rides `GrantCombatRestrictionEffect`'s
#: ``restrict_to_source`` instead — see its docstring.
_CANT_BLOCK_SOURCE_TURN_RE = _c(rf"{TARGET} can'?t block (?:~|it|this creature) this turn")

#: "Target creature blocks ~ this turn if able." — the resolve-time,
#: targeted sibling of the standing "~ must be blocked if able." static:
#: forces one specific (usually opposing) creature to block this ability's
#: own source, checked by `GameEngine._enforce_block_requirements` via the
#: `must_block_target` restriction kind.
_BLOCKS_SOURCE_TURN_IF_ABLE_RE = _c(rf"{TARGET} blocks (?:~|it|this creature) this turn if able")


def _cant_block_source_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None
    return [EffectSpec("combat_restriction_this_turn", {
        "target_kind": kind,
        "restriction": {"kind": "cant_block_filtered"},
        "restrict_to_source": True,
    })]


def _blocks_source_turn_if_able(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None
    return [EffectSpec("combat_restriction_this_turn", {
        "target_kind": kind,
        "restriction": {"kind": "must_block_target"},
        "restrict_to_source": True,
    })]


#: "Target creature attacks this turn if able." — the resolve-time, targeted
#: sibling of the standing "~ attacks each combat if able." static (RULE
#: 508.1a): a plain temporary keyword grant (`PumpEffect`'s ``keywords``),
#: since `GameEngine._enforce_attacks_if_able` already reads `combat.has()`,
#: which unions in a `temp_keywords` grant the same as a printed one — no new
#: engine code needed, unlike the pairwise "blocks ~"/"can't block ~" shapes
#: above (which name a *specific* attacker no bare flag can carry).
_ATTACKS_TURN_IF_ABLE_RE = _c(rf"{TARGET} attacks this turn if able")


def _attacks_turn_if_able(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None
    return [EffectSpec("pump", {"keywords": ["attacks_if_able"], "target_kind": kind})]


#: "Target creature must be blocked this turn if able." (Irresistible Prey/
#: Goldenhide Ox/Head Banger/Satyr Piper) / "~ must be blocked this turn if
#: able." (Loathsome Catoblepas) — the bare (no P/T delta, no "and gains …"
#: suffix) sibling of `_ATTACKS_TURN_IF_ABLE_RE` just above, same "flag
#: keyword, no new engine code" reasoning (RULE 509.1c, `combat.has`).
#: `_SUBJECT`/`_pump_target` resolve the same self/target shapes `_pump`/
#: `_pump_keywords` already do.
_MUST_BE_BLOCKED_TURN_RE = _c(rf"{_SUBJECT} must be blocked this turn if able")


def _must_be_blocked_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    params: dict = {"keywords": ["must_be_blocked"]}
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    return [EffectSpec("pump", params)]


#: RULE 701.47/48 Amass "<Type> N" ("amass Orcs 1"/"amass Zombies 2" — this
#: repo's existing `game/effects/core.py` `AmassEffect` and its one proven
#: consumer, Orcish Bowmasters (`card_registry/value.py`), both
#: cite it as 701.48; the current `docs/Reference/rules_wiki` text has it
#: renumbered to 701.47 since Learn moved to take 701.48 — same mechanic
#: either way). The printed type word is always a regular "+s" plural in
#: real Oracle text (confirmed against every cached Amass card via
#: `parser_probe.py blocked "amass"` — Orcs/Zombies/Goblins/Birds/Slivers),
#: so it's singularized (`_singularize_amass_subtype`, the same bare
#: trailing-"s" strip `subgrammars._singularize` already uses for the
#: unrelated "N `<type>` you control" count phrase) and capitalized to
#: match `AmassEffect`'s own singular `subtype` param convention ("Orc",
#: not "Orcs" — the exact shape Orcish Bowmasters' hand-authored
#: ``EffectSpec("amass", {"subtype": "Orc", "count": 1})`` uses).
#:
#: Deliberately digit-only counts (`NUMBER`, not `COUNT_X`):
#: `EffectRegistry.register("amass", ...)` forces ``int(p.get("count", 1))``
#: on bind, so a literal "x" sentinel (RULE 107.3c's announced {X} — "amass
#: Orcs X", Assault on Osgiliath/Barad-dûr) would raise at bind time rather
#: than resolve through the ordinary `_substitute_x` machinery every other
#: count-bearing effect gets for free — `AmassEffect`/its registry factory
#: were never actually built to accept the sentinel. Left unclaimed rather
#: than risk that crash; teaching them the "x" sentinel is separate engine
#: work, out of this parser-only change's scope.
def _singularize_amass_subtype(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 1 else word


def _amass(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subtype = _singularize_amass_subtype(m.group("subtype")).capitalize()
    return [EffectSpec("amass", {"subtype": subtype, "count": int(m.group("n"))})]


_AMASS_RE = _c(rf"amass (?P<subtype>[a-z]+) {NUMBER}")


#: RULE 701.47d: pre-errata "amass N" with no subtype at all — Oracle text
#: has since been errata'd to always spell out "amass Zombies N" instead, so
#: no card in today's cache reaches this row (confirmed: none of the 73
#: cached Amass-mentioning cards omit a type word) — kept for a
#: differently-worded future import rather than as a real current unlock.
#: Defaults to Zombie (matching the errata'd wording and `AmassEffect`'s own
#: default subtype), spelled out explicitly and singular here rather than
#: relying on that default, which is itself stored plural ("Zombies") and
#: would otherwise produce a grammatically-wrong "Army Zombies" token type
#: line if this row were ever actually hit.
def _amass_untyped(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("amass", {"subtype": "Zombie", "count": int(m.group("n"))})]


_AMASS_UNTYPED_RE = _c(rf"amass {NUMBER}")


# --- PAR-72: Party (RULE 700.8) generalized into a resolve-time amount -----
# `continuous.count_selector`'s ``"creatures_in_your_party"`` branch (PAR-53)
# was previously wired only into the cost-reduction/"full party" static
# forms. This section widens the already-generic `amount_from_count_
# selector`/`count_selector` family (PAR-32/36/43 &c.) to also recognize the
# fixed phrase "for each creature in your party"/"the number of creatures
# in your party" across the one-shot effect verbs real cards print it on —
# one handler per distinct verb/template, this codebase's established
# convention (no single "for each X" grammar spans every effect type).

#: "Add `<sym>` for each creature in your party." (Ardent Electromancer) —
#: `AddManaEffect.amount_selector` (Burnt Offering's own hand-authored
#: field, MEC-43) is the oracle-text route: additive with ``colors``, so
#: this sets only ``color``, leaving ``colors`` empty (no unconditional
#: pip of its own — the whole amount comes from the party count).
_ADD_MANA_PARTY_RE = _c(r"add (?P<sym>\{[wubrgc]\}) for each creature in your party")


def _add_mana_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_mana", {
        "color": m.group("sym").strip("{}").upper(),
        "amount_selector": "creatures_in_your_party",
    })]


#: "When ~ enters, put a +1/+1 counter on it for each creature in your
#: party." (Emeria Captain) — the self-ETB sibling of
#: `_choose_target_add_counters_party` below, both reusing `AddCountersEffect.
#: amount_from_count_selector`.
_ADD_COUNTERS_SELF_PARTY_RE = _c(
    r"put a \+1/\+1 counter on it for each creature in your party"
)


def _add_counters_self_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {"amount_from_count_selector": "creatures_in_your_party"})]


#: "Choose target creature you control. Put a +1/+1 counter on it for each
#: creature in your party." (Strength of Solidarity) — a sorcery with no
#: trigger wrapper, so the whole two-sentence body is one clause; modeled
#: directly as a single targeted `add_counters` rather than a separate
#: "choose"/previous-subject pair (the target IS the thing counters land on,
#: nothing else in the body reads it).
_CHOOSE_TARGET_ADD_COUNTERS_PARTY_RE = _c(
    r"choose target creature you control\. put a \+1/\+1 counter on it for each creature in your party"
)


def _choose_target_add_counters_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "target_kind": "creature_you_control",
        "amount_from_count_selector": "creatures_in_your_party",
    })]


#: "Whenever ~ attacks, it gets +1/+0 until end of turn for each creature in
#: your party." (Grotag Bug-Catcher) — a self, power-only
#: `PumpEffect.amount_from_count_selector` (the count *is* the pump amount;
#: no separate per-unit multiplier, matching every "+1/+X for each" shape
#: in this family — the printed magnitude is always exactly 1 per unit).
_PUMP_SELF_POWER_PARTY_RE = _c(r"it gets \+1/\+0 until end of turn for each creature in your party")


def _pump_self_power_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "amount_from_count_selector": "creatures_in_your_party",
        "amount_from_count_selector_axis": "power",
    })]


#: "When ~ enters, target creature gets +1/+1 until end of turn for each
#: creature in your party." (Kabira Outrider) — the targeted, both-axis
#: sibling of `_pump_self_power_party` above.
_PUMP_TARGET_BOTH_PARTY_RE = _c(
    r"target creature gets \+1/\+1 until end of turn for each creature in your party"
)


def _pump_target_both_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "target_kind": "creature", "amount_from_count_selector": "creatures_in_your_party",
    })]


#: "Up to two target creatures each get +X/+X until end of turn, where X is
#: the number of creatures in your party." (Allied Assault) — the multi-
#: target sibling of `_pump_up_to_two`, scaled instead of a fixed digit.
_PUMP_UP_TO_TWO_PARTY_RE = _c(
    r"up to 2 target creatures each get \+x/\+x until end of turn, "
    r"where x is the number of creatures in your party"
)


def _pump_up_to_two_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "target_kind": "creature", "target_count": 2, "optional": True,
        "amount_from_count_selector": "creatures_in_your_party",
    })]


#: "When ~ enters, target creature an opponent controls gets -X/-X until
#: end of turn, where X is the number of creatures in your party." (Drana's
#: Silencer) — the negative-both-axis sibling, `amount_from_count_selector_
#: negative` flips the sign the same way every other "-X/-X, where X is …"
#: row in this file does.
_PUMP_TARGET_OPPONENT_NEGATIVE_PARTY_RE = _c(
    r"target creature an opponent controls gets -x/-x until end of turn, "
    r"where x is the number of creatures in your party"
)


def _pump_target_opponent_negative_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "target_kind": "creature_you_dont_control",
        "amount_from_count_selector": "creatures_in_your_party",
        "amount_from_count_selector_negative": True,
    })]


#: "You gain 2 life for each creature in your party." (Shepherd of Heroes)
#: — the 2-life-per-unit sibling of every other 1-per-unit ``count_
#: selector`` gain_life row, using `GainLifeEffect.count_selector_
#: multiplier` (PAR-72's own new field — every existing ``count_selector``
#: gain_life shape prints exactly 1 life per unit, so no prior card needed
#: a multiplier).
_GAIN_LIFE_PARTY_RE = _c(r"you gains? 2 life for each creature in your party")


def _gain_life_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {
        "count_selector": "creatures_in_your_party", "count_selector_multiplier": 2,
    })]


#: "Create a 1/1 white Kor Warrior creature token for each creature in your
#: party." (Squad Commander) — `CreateTokenEffect.count_selector` directly
#: (the count *is* the token count, no multiplier); ``<mid>`` (colors +
#: subtypes) reuses `_split_token_mid_words`, the same word-splitter every
#: other inline-stat token handler in this file shares.
_CREATE_TOKEN_PARTY_RE = _c(
    r"create a (?P<p>\d+)/(?P<t>\d+) (?P<mid>[a-z ]+) creature tokens? "
    r"for each creature in your party"
)


def _create_token_party(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors, subtypes, is_artifact = _split_token_mid_words(m.group("mid"))
    if not subtypes:
        return None
    params: dict = {
        "power": int(m.group("p")), "toughness": int(m.group("t")),
        "colors": colors, "subtypes": subtypes,
        "count_selector": "creatures_in_your_party",
    }
    if is_artifact:
        params["is_artifact"] = True
    return [EffectSpec("create_token", params)]


#: "Scry X, where X is the number of creatures in your party." (Cascade
#: Seer) — `ScryEffect.count_from_count_selector` (PAR-72's own new field).
_SCRY_PARTY_RE = _c(r"scry x, where x is the number of creatures in your party")


def _scry_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("scry", {"count_from_count_selector": "creatures_in_your_party"})]


#: "Each opponent loses X life and you gain X life, where X is the number
#: of creatures in your party." (Malakir Blood-Priest) — the party-count
#: sibling of `_lose_life_and_gain_life_devotion`; must stay one clause for
#: the same reason that row does (the generic " and " connector split would
#: otherwise hand the first half's bare "x" to `_lose_life_selector`'s
#: RULE-107.3c announced-X reading, which crashes with no X to substitute).
_LOSE_LIFE_AND_GAIN_LIFE_PARTY_RE = _c(
    r"each opponent loses x life and you gains? x life, where x is the number of creatures in your party"
)


def _lose_life_and_gain_life_party(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("lose_life", {
            "amount_from_count_selector": "creatures_in_your_party", "selector": "each_opponent",
        }),
        EffectSpec("gain_life", {"count_selector": "creatures_in_your_party"}),
    ]


#: "Choose target attacking or blocking creature. ~ deals damage to that
#: creature equal to twice the number of creatures in your party."
#: (Practiced Tactics) — folded into one targeted `damage` effect
#: (`DealDamageEffect.amount_multiplier`, "twice" = 2) the same way
#: `_choose_target_add_counters_party` folds its own "choose … put …" body.
_DAMAGE_ATTACKING_OR_BLOCKING_TWICE_PARTY_RE = _c(
    r"choose target attacking or blocking creature\. ~ deals damage to that creature "
    r"equal to twice the number of creatures in your party"
)


def _damage_attacking_or_blocking_twice_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "target_kind": "attacking_or_blocking_creature",
        "amount_from_count_selector": "creatures_in_your_party", "amount_multiplier": 2,
    })]


#: "Look at the top X cards of your library, where X is 3 plus the number
#: of creatures in your party. Put 3 of those cards into your hand and the
#: rest on the bottom of your library in a random order." (Skyclave
#: Plunder) — `InspectTopChooseEffect.count_from_count_selector`/
#: ``count_plus`` (PAR-72's own new fields); ``max_picks=3`` is a forced
#: (not "up to") pick since the party-scaled X is always >= 3.
_LOOK_TOP_PUT_THREE_PARTY_RE = _c(
    r"look at the top x cards of your library, where x is 3 plus the number of creatures in your party\. "
    r"put 3 of those cards into your hand and the rest on the bottom of your library in a random order"
)


def _look_top_put_three_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("inspect_top_choose", {
        "count_from_count_selector": "creatures_in_your_party", "count_plus": 3,
        "action": "library_to_hand", "max_picks": 3, "rest_destination": "library_bottom_random",
    })]


#: PAR-74: "Reveal the top N cards of your library. Put all land cards
#: revealed this way into your hand and the rest on the bottom of your
#: library in any order." (Elder Pine of Jukai). Not a real choice — RULE
#: 601.2c's "all" leaves nothing to pick between — so it's `InspectTopChoose
#: Effect` with ``max_picks`` set to the full inspected count: whenever
#: every land-filtered candidate is within that cap (always true here, since
#: candidates are a subset of the N inspected), `_request_choose_objects`
#: auto-resolves with no prompt (see its own docstring), which *is* "put all
#: of them" for a filter this narrow. ``rest_destination="library_bottom_
#: random"`` is the existing "in any order" stand-in `_LOOK_TOP_PUT_THREE_
#: PARTY_RE` above already uses. Only "land" is in this family's filter
#: vocabulary — extend `_REVEAL_TOP_ALL_FILTER_RE` the day another type word
#: needs it.
_REVEAL_TOP_ALL_FILTER_RE = _c(
    r"reveal the top (?P<n>\d+) cards of your library\. "
    r"put all (?P<filter>land) cards revealed this way into your hand and "
    r"the rest on the bottom of your library in any order"
)


def _reveal_top_all_filter(m: re.Match[str]) -> list[EffectSpec]:
    n = int(m.group("n"))
    return [EffectSpec("inspect_top_choose", {
        "count": n, "action": "library_to_hand", "filter": {"is_land": True},
        "max_picks": n, "rest_destination": "library_bottom_random",
    })]


#: PAR-144: the general dig — "Look at/Reveal the top N cards of your library. You may reveal a
#: `<kind>` card from among them and put it into your hand/onto the battlefield. Put the rest on
#: the bottom of your library / into your graveyard." (`dig.py` parses everything after the first
#: sentence; this row only owns that sentence, so a body the dig grammar can't read returns None
#: and falls through to the rows below.)
#: An ``x`` count is the spell's / ability's announced {X}; `gate._dig_x_ok` refuses it under a trigger,
#: where no X was announced.
_DIG_RE = _c(r"(?:look at|reveal) the top (?P<n>\d+|x) cards of your library\.\s+(?P<rest>.+)")


def _dig(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    count = m.group("n").lower()
    return parse_dig("x" if count == "x" else int(count), m.group("rest"), match_clause)


#: "~ deals 4 damage to target creature and X damage to that creature's
#: controller, where X is the number of creatures in your party."
#: (Synchronized Spellcraft) — two `damage` effects sharing one RULE 115
#: target: the first's own target (`_apply_effects_partitioned` records it
#: into `GameContext.previous_targets`), the second reads its controller via
#: `DealDamageEffect.recipient_subject="previous_subject_controller"`
#: (`_DAMAGE_TO_SUBJECT_CONTROLLER_RE`'s own idiom) — found and fixed a
#: latent gap while building this: that recipient path read raw
#: `self.amount` instead of `_amount_for`, so `amount_from_count_selector`/
#: `amount_from_trigger_event` were silently dropped whenever combined with
#: `recipient_subject` (no shipped card had combined them before now).
_DAMAGE_TARGET_AND_CONTROLLER_PARTY_RE = _c(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to target creature and x damage to "
    r"that creature'?s controller, where x is the number of creatures in your party"
)


def _damage_target_and_controller_party(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("damage", {"amount": int(m.group("n")), "target_kind": "creature"}),
        EffectSpec("damage", {
            "recipient_subject": "previous_subject_controller",
            "amount_from_count_selector": "creatures_in_your_party",
        }),
    ]


#: "When ~ enters, it deals X damage to target creature or planeswalker,
#: where X is the number of creatures in your party." (Thundering
#: Sparkmage) — `resolve_target_kind`'s existing "target creature or
#: planeswalker" → ``"creature"`` row (a project-wide documented
#: simplification — this engine's ``creature`` kinds are creature-only) is
#: reused as-is, unchanged by this ticket.
_DAMAGE_TARGET_PARTY_RE = _c(
    rf"it deals x damage to {TARGET}, where x is the number of creatures in your party"
)


def _damage_target_party(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("damage", {
        "target_kind": kind, "amount_from_count_selector": "creatures_in_your_party",
    })]


#: "Whenever ~ attacks, defending player loses X life and you create X
#: Treasure tokens, where X is the number of creatures in your party."
#: (Burakos, Party Leader's attack trigger — the card's own static "~ is
#: also a Cleric, Rogue, Warrior, and Wizard" makes it count toward its own
#: party) — `LoseLifeEffect.selector="defending_player"` (afflict's own
#: idiom) combined with `amount_from_count_selector`, plus a plain
#: `CreateTokenEffect.count_selector` Treasure.
_BURAKOS_ATTACK_PARTY_RE = _c(
    r"defending player loses x life and you create x treasure tokens, "
    r"where x is the number of creatures in your party"
)


def _burakos_attack_party(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("lose_life", {
            "selector": "defending_player", "amount_from_count_selector": "creatures_in_your_party",
        }),
        EffectSpec("create_token", {
            "token_name": "Treasure", "count_selector": "creatures_in_your_party",
        }),
    ]


#: PAR-74: "~ becomes a N/M [`<qualifiers>`] creature[ with `<keyword>`]
#: until end of turn." (Jade Idol) / "target `<permanent kind>` becomes a
#: N/M creature until end of turn[. it's still a `<kind>`.]" (Soilshaper) —
#: RULE 613.4d's temporary type-change animation, already a shipped
#: resolve-time primitive (`GrantUntilEffect` wrapping a layer-4
#: `type_change` static at ``duration="end_of_turn"`` — Incubator's own
#: self-animate shape, Hedge Whisperer's own target-a-land shape, see
#: `card_registry.red_spells`), with only the parser recognition
#: missing. ``<qualifiers>`` is a curated whitelist, not an open word
#: class (fail-closed, same reasoning as `_CAST_SPELL_SUBTYPE_WORDS`):
#: re-stating a permanent's own main type ("spirit **artifact** creature")
#: is a harmless idempotent `add_types` entry, and a genuine new creature
#: subtype ("**spirit** artifact creature") is `add_subtypes`. No colour
#: word is in this list — no real card in this shape has needed one yet;
#: extend it the day one does, don't guess a `colors`-setting layer-5
#: param this primitive doesn't carry.
_ANIMATE_QUALIFIER_TYPES: frozenset[str] = frozenset({"artifact", "enchantment", "land", "planeswalker"})
#: PAR-79 sixth increment widened this from a 7-word set (spirit/elemental/
#: plant/horror/shade/boar/wall) that only covered the one card this row was
#: first written against — the Ravnica guild Keyrune cycle alone prints ten
#: different creature types ("2/2 `<colors>` Bird artifact creature",
#: "1/1 `<colors>` Soldier artifact creature", …). Union with `segmenter.
#: _CAST_SPELL_SUBTYPE_WORDS`'s own curated real-creature-type vocabulary
#: rather than guessing a fresh list — same words, duplicated here rather
#: than imported, since `segmenter.py` imports *from* this module (a
#: reverse import would close a cycle).
_ANIMATE_QUALIFIER_SUBTYPES: frozenset[str] = frozenset({
    "spirit", "elemental", "plant", "horror", "shade", "boar", "wall",
    "elf", "goblin", "zombie", "human", "wizard", "merfolk", "vampire",
    "dragon", "angel", "demon", "soldier", "knight", "warrior", "giant",
    "dwarf", "faerie", "sliver", "rogue", "cleric", "shaman", "druid", "construct",
    "beast", "bird", "cat", "dog", "insect", "snake", "treefolk", "wolf",
    # PAR-124: Disturbed Slumber's own animate-land target ("4/4 dinosaur
    # creature").
    "dinosaur", "bear",
})
#: PAR-79 sixth increment: "~ becomes a 2/2 **blue and black** horror
#: artifact creature …" (Dimir/Azorius/Boros/… Keyrune, Atarka/Dromoka
#: Monument-shaped — the single biggest blocker on this whole animation
#: shape, 44 SOLO cache cards on the raw "becomes a N/M `<color>` creature"
#: phrase, PAR-79's own share being Dimir Keyrune). `continuous.
#: _apply_layer_5_color`'s ``"color"``-kind static already exists and is
#: already reachable through `extra_statics` (the exact mechanism the
#: keyword-grant branch just below already uses) — only the colour-word
#: recognition itself was missing, the same "primitive already exists, only
#: the parser row doesn't reach it" shape this whole increment keeps
#: finding. A leading, "and"-joined run of colour words right before the
#: type/subtype qualifiers — real cards print one or two, never more.
_ANIMATE_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}
_ANIMATE_COLOR_PREFIX_RE = re.compile(
    r"^(?P<colors>(?:white|blue|black|red|green)"
    r"(?:\s+and\s+(?:white|blue|black|red|green))*)\s+", re.IGNORECASE,
)


def _split_animate_qualifiers(text: str) -> Optional[tuple[list[str], list[str], list[str]]]:
    """A "[`<colors>`] `<word>` `<word>` …" blob right before "creature" →
    ``(colors, add_types, add_subtypes)``, or ``None`` if any non-colour
    word isn't in the curated whitelist above (fail-closed)."""
    colors: list[str] = []
    color_m = _ANIMATE_COLOR_PREFIX_RE.match(text)
    if color_m is not None:
        colors = [
            _ANIMATE_COLOR_WORDS[w.lower()]
            for w in re.split(r"\s+and\s+", color_m.group("colors"))
        ]
        text = text[color_m.end():]
    add_types: list[str] = []
    add_subtypes: list[str] = []
    for word in text.split():
        word = word.strip().lower()
        if not word:
            continue
        if word in _ANIMATE_QUALIFIER_TYPES:
            add_types.append(word)
        elif word in _ANIMATE_QUALIFIER_SUBTYPES:
            add_subtypes.append(word.capitalize())
        else:
            return None
    return colors, add_types, add_subtypes


_ANIMATE_SELF_RE = _c(
    r"~ becomes an? (?P<p>\d+)/(?P<t>\d+) (?P<quals>(?:[a-z]+ )*?)creature"
    r"(?: with (?P<kw>[a-z, ]+?))? until end of turn"
    # PAR-79 sixth increment: "… until end of turn and can't be blocked
    # this turn." (Dimir Keyrune-shaped) — the same one-sentence pump-and-
    # unblockable tail `_pump_unblockable`/`_pump_keyword_unblockable`
    # already accept, on this animation primitive's own bare-self form.
    r"(?P<unblockable> and can'?t be blocked this turn)?"
)

# PAR-98: Creeping Tar Pit puts the duration first and uses full stops for
# the land reminder and unblockable rider, rather than the normal one-sentence
# "becomes … until end of turn and can't …" ordering.
_ANIMATE_SELF_LEADING_EOT_RE = _c(
    r"until end of turn, ~ becomes an? (?P<p>\d+)/(?P<t>\d+) "
    r"(?P<quals>(?:[a-z]+ )*?)creature"
    r"(?:\. it'?s still a land)?(?:\. it can'?t be blocked this turn)?"
)


def _animate_self(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    quals = _split_animate_qualifiers(m.group("quals"))
    if quals is None:
        return None
    colors, add_types, add_subtypes = quals
    static: dict[str, Any] = {
        "type": "type_change",
        "params": {
            "add_types": ["creature"] + add_types,
            "power": int(m.group("p")), "toughness": int(m.group("t")),
            **({"add_subtypes": add_subtypes} if add_subtypes else {}),
        },
    }
    extra_statics = []
    if colors:
        extra_statics.append({"type": "color", "params": {"colors": colors, "set": True}})
    kw = m.groupdict().get("kw")
    if kw:
        keywords = _token_keywords(kw)
        if keywords is None:
            return None
        extra_statics.append({"type": "grant_keyword", "params": {"keywords": keywords}})
    specs = [EffectSpec("grant_until", {
        "duration": "end_of_turn", "target_kind": None, "static": static,
        **({"extra_statics": extra_statics} if extra_statics else {}),
    })]
    if m.groupdict().get("unblockable"):
        specs.append(EffectSpec("unblockable", {"target_kind": None}))
    return specs


def _animate_self_leading_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    quals = _split_animate_qualifiers(m.group("quals"))
    if quals is None:
        return None
    colors, add_types, add_subtypes = quals
    static: dict[str, Any] = {
        "type": "type_change",
        "params": {
            "add_types": ["creature"] + add_types,
            "power": int(m.group("p")), "toughness": int(m.group("t")),
            **({"add_subtypes": add_subtypes} if add_subtypes else {}),
        },
    }
    extra_statics = []
    if colors:
        extra_statics.append({"type": "color", "params": {"colors": colors, "set": True}})
    specs = [EffectSpec("grant_until", {
        "duration": "end_of_turn", "target_kind": None, "static": static,
        **({"extra_statics": extra_statics} if extra_statics else {}),
    })]
    if m.group(0).lower().endswith("can't be blocked this turn"):
        specs.append(EffectSpec("unblockable", {"target_kind": None}))
    return specs


#: PAR-140: "it becomes a Rogue in addition to its other types" / "~ becomes a Vampire and a Zombie …" /
#: "target creature becomes an artifact in addition to its other types until end of turn" — a type
#: addition with no new P/T or abilities (RULE 205.1b: *in addition* keeps the rest), riding a put/return
#: clause (Butch DeLoria, Beorn the Fierce, Origin of Spider-Man). One `grant_until` over a layer-4
#: `type_change`: "until end of turn" ends at cleanup, otherwise it is a permanent effect
#: (`rest_of_game`, RULE 611.2a). A word that is neither a card type, "legendary" nor a known subtype
#: fails the clause closed.
_BECOMES_IN_ADDITION_TYPES: frozenset[str] = frozenset({"artifact", "creature", "enchantment", "land"})
#: PAR-141/142: the body after the verb — "a `<N/N>` `<subtype/type words>` [with `<keywords>`] in
#: addition to its other types [and gains `<keyword>`] [until end of turn]" (Archangel Elspeth's "and gains
#: flying", Answered Prayers' "a 3/3 Angel creature with flying", Call a Surprise Witness' "it's a Spirit").
#: Keywords come through the same vocabulary the "with `<keyword>`" tails read. A base P/T needs the word
#: "creature" (a non-creature has none) and rides the same layer-4 static, exactly as the animate rows do.
_BIA_KEYWORD = "|".join(sorted(_CREATURE_FILTER_KEYWORD_WORDS, key=len, reverse=True))
_BIA_KEYWORD_LIST = rf"(?:{_BIA_KEYWORD})(?:(?:, and |, | and )(?:{_BIA_KEYWORD}))*"
#: "that creature has base power and toughness 3/1 and has flying" (Aven Mimeomancer) — a layer-7b base P/T
#: (the same `type_change` ``power``/``toughness`` the animate rows set) plus an optional keyword list, on the
#: pick an earlier clause made. Duration-less here: "for as long as it has a feather counter on it" re-times it.
_BASE_PT_PREVIOUS_RE = _c(
    r"(?:it|that (?:creature|permanent|land|artifact)) has base power and toughness (?P<p>\d+)/(?P<t>\d+)"
    rf"(?: and has (?P<kws>{_BIA_KEYWORD_LIST}))?"
)


def _base_pt_previous(m: re.Match[str]) -> list[EffectSpec]:
    params: dict[str, Any] = {
        "static": {"type": "type_change", "params": {"power": int(m.group("p")), "toughness": int(m.group("t"))}},
        "previous_subject": True, "target_kind": None,
    }
    if m.group("kws"):
        keywords = [_CREATURE_FILTER_KEYWORD_WORDS[w] for w in re.split(r", and |, | and ", m.group("kws")) if w]
        params["extra_statics"] = [{"type": "grant_keyword", "params": {"keywords": keywords}}]
    return [EffectSpec("grant_until", params)]


#: PAR-135: "…a black Zombie in addition to its other **colors and** types" (Liliana, Death's Majesty, Dread
#: Slaver, Ever After) / "becomes blue in addition to its other **colors**" (Indigo Faerie) — the colour is an
#: *added* colour (a layer-5 `color` static with ``set: False``), where a colour word without that tail means
#: "is exactly that colour" and stays unmodeled. The article is optional only for the colour-only spelling.
_BECOMES_IN_ADDITION_BODY = (
    r" (?:an? )?(?:(?P<bp>\d+)/(?P<bt>\d+) )?(?P<words>[a-z]+(?: [a-z]+)*?)"
    # "…a green Bear creature **with base power and toughness 4/4** in addition to …" (Halsin) — the other
    # spelling of the same base P/T a leading "4/4" gives.
    r"(?: with base power and toughness (?P<bp2>\d+)/(?P<bt2>\d+))?"
    rf"(?: with (?P<kws>{_BIA_KEYWORD_LIST}))?"
    r" in addition to its other (?P<scope>colors and types|colors|types)"
    rf"(?: and gains (?P<kw>{_BIA_KEYWORD}))?"
    r"(?P<eot> until end of turn)?"
)
#: "it"/"that creature" — only offered once the previous clause announced a pick. "it's a …" is the
#: rider spelling after a put/return ("put a flying counter on it. It's a Spirit in addition …").
_BECOMES_IN_ADDITION_PREVIOUS_RE = _c(
    rf"(?:(?P<prev>it)(?: becomes|'s)|(?P<prev2>that (?:creature|permanent|land|artifact)|each of those creatures)"
    rf"(?: becomes| is))"
    rf"{_BECOMES_IN_ADDITION_BODY}"
)
#: "it" after a counter put on the source (Phantom Train) — the source itself, see
#: `segmenter._puts_counter_on_source`.
_BECOMES_IN_ADDITION_SELF_PRONOUN_RE = _c(rf"(?P<self>it)(?: becomes|'s){_BECOMES_IN_ADDITION_BODY}")
#: "~" / "target creature" name their subject outright.
_BECOMES_IN_ADDITION_RE = _c(rf"(?:(?P<self>~)|{TARGET}) becomes{_BECOMES_IN_ADDITION_BODY}")


def _becomes_in_addition(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .static_handlers import type_addition_params  # local: imports handlers

    words = m.group("words").lower().split()
    scope = m.group("scope")
    added_colors: list[str] = []
    if scope == "types":
        if any(w in COLOR_LETTERS for w in words):
            return None  # "becomes a black Zombie in addition to its other types" replaces the colour
    else:
        while words and words[0] in COLOR_LETTERS and words[0] != "colorless":
            added_colors.append(COLOR_LETTERS[words.pop(0)])
        if not added_colors or (scope == "colors" and words):
            return None
    type_params = type_addition_params(" ".join(words)) if words else {}
    if type_params is None:
        return None
    base_pt = (m.group("bp"), m.group("bt")) if m.group("bp") is not None else (m.group("bp2"), m.group("bt2"))
    if base_pt[0] is not None:
        if "creature" not in type_params.get("add_types", []):
            return None
        type_params = {**type_params, "power": int(base_pt[0]), "toughness": int(base_pt[1])}
    statics: list[dict[str, Any]] = []
    if type_params:
        statics.append({"type": "type_change", "params": type_params})
    if added_colors:
        statics.append({"type": "color", "params": {"colors": added_colors, "set": False}})
    params: dict[str, Any] = {
        "duration": "end_of_turn" if m.group("eot") else "rest_of_game",
        "static": statics[0],
    }
    if len(statics) > 1:
        params["extra_statics"] = statics[1:]
    keywords = [
        _CREATURE_FILTER_KEYWORD_WORDS[w]
        for w in re.split(r", and |, | and ", m.group("kws") or "") if w
    ]
    if m.group("kw"):
        keywords.append(_CREATURE_FILTER_KEYWORD_WORDS[m.group("kw")])
    if keywords:
        params["extra_statics"] = [*params.get("extra_statics", []),
                                   {"type": "grant_keyword", "params": {"keywords": keywords}}]
    groups = m.groupdict()
    if groups.get("prev") or groups.get("prev2"):
        params["previous_subject"] = True
        params["target_kind"] = None
    elif groups.get("self"):
        params["self_subject"] = True
        params["target_kind"] = None
    else:
        kind = resolve_target_kind(groups["target"])
        if not target_kind_allowed(kind, ("creature", "permanent", "creature_you_control", "land", "artifact")):
            return None
        params["target_kind"] = kind
        params.update(_optional_param(m))
    return [EffectSpec("grant_until", params)]


_ANIMATE_QUOTED_CDA_RE = _c(
    r"(?:(?P<eot>until end of turn), )?"
    r"(?P<subject>~|target land you control|the goblin sparring grounds) becomes a "
    r"(?P<quals>[a-z ]*?)creature "
    r"(?:with|in addition to its other types and gains) "
    r"(?:(?P<kw>haste) and )?"
    r'"(?P<cda>~\'s power and toughness are each equal to [^\"]+)"'
    r"(?: it'?s still a land)?"
)


def _animate_quoted_cda(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """Animate once, granting the quoted P/T definition to that object."""
    from .static_handlers import static_effect_specs  # local: imports handlers

    parsed = static_effect_specs(m.group("cda"))
    if not parsed or len(parsed) != 1 or parsed[0].type != "pt_cda":
        return None
    quals = _split_animate_qualifiers(m.group("quals"))
    if quals is None:
        return None
    colors, add_types, add_subtypes = quals
    extra = [parsed[0].to_dict()]
    if colors:
        extra.append({"type": "color", "params": {"colors": colors, "set": True}})
    if m.group("kw"):
        extra.append({"type": "grant_keyword", "params": {"keywords": ["haste"]}})
    subject = m.group("subject").lower()
    return [EffectSpec("grant_until", {
        "duration": "end_of_turn" if m.group("eot") else "rest_of_game",
        "target_kind": "land_you_control" if subject == "target land you control" else None,
        "self_subject": subject != "target land you control",
        "static": {"type": "type_change", "params": {
            "add_types": ["creature", *add_types],
            **({"add_subtypes": add_subtypes} if add_subtypes else {}),
        }},
        "extra_statics": extra,
    })]


#: The TARGET sibling — "target land becomes a 3/3 creature until end of
#: turn. It's still a land." (Soilshaper). The trailing "it's still a
#: `<kind>`" sentence is pure reminder text (`type_change`'s ``add_types``
#: only *adds*, RULE 613.4d — the printed type is never lost), so it's
#: matched and discarded rather than parsed into anything; the ``(?P=kind)``
#: backreference keeps that discard honest (never swallows a mismatched
#: reminder sentence). Optional because not every real card bothers to
#: print the reminder.
#: PAR-79 sixth increment: ``snow `` before the target kind ("target snow
#: land becomes a 2/2 blue elemental creature…", Balduvian Frostwaker) and
#: the same colour-word qualifier support `_animate_self` gained just
#: above — reusing the identical `_split_animate_qualifiers`/`extra_statics`
#: machinery rather than a second copy.
_ANIMATE_TARGET_RE = _c(
    r"target (?:snow )?(?P<kind>land|mountain|forest|artifact|creature|enchantment|creature or land)"
    # PAR-124: "target creature or land you control becomes …" (Vengeant
    # Earth) — the controller-scoped qualifier `resolve_target_kind` already
    # resolves for every kind word here (``land_you_control``/
    # ``creature_or_land_you_control``, …), just never threaded through this
    # regex before.
    r"(?P<you_control> you control)? becomes "
    r"an? (?P<p>\d+)/(?P<t>\d+) (?P<quals>(?:[a-z]+ )*?)creature"
    r"(?: with (?P<kw>[a-z, ]+?))?"
    # "…in addition to its other types until end of turn." (Vengeant
    # Earth) — the same "printed type is never lost" reminder `_split_
    # animate_qualifiers`'s ``add_types`` already encodes, just spelled as
    # its own clause instead of the plain "it's still a `<kind>`" sentence.
    r"(?: in addition to its other types)?(?P<eot> until end of turn)?"
    # A basic-land-subtype target (Mountain/Forest) still says merely
    # "it's still a land" in its reminder sentence.
    r"(?:\. it'?s still an? (?:snow )?(?:(?P=kind)|land))?"
    # PAR-124: "…it's still a land. **it must be blocked this turn if
    # able**." (Disturbed Slumber/Elemental Uprising) — folded in here
    # rather than left to the generic `previous_subject` connector-split
    # pipeline: that split would hand the *pure-reminder* "it's still a
    # land" sentence its own unclaimed part first (nothing builds an
    # `EffectSpec` for it alone), failing the whole body closed before this
    # tail is ever reached.
    r"(?P<must_blocked>\. it must be blocked this turn if able)?"
)


def _animate_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    quals = _split_animate_qualifiers(m.group("quals"))
    if quals is None:
        return None
    colors, add_types, add_subtypes = quals
    kind = resolve_target_kind(
        "target " + m.group("kind") + (m.group("you_control") or "")
    )
    if kind is None:
        return None
    static: dict[str, Any] = {
        "type": "type_change",
        "params": {
            "add_types": ["creature"] + add_types,
            "power": int(m.group("p")), "toughness": int(m.group("t")),
            **({"add_subtypes": add_subtypes} if add_subtypes else {}),
        },
    }
    extra_statics = []
    if colors:
        extra_statics.append({"type": "color", "params": {"colors": colors, "set": True}})
    kw = m.groupdict().get("kw")
    if kw:
        keywords = _token_keywords(kw)
        if keywords is None:
            return None
        extra_statics.append({"type": "grant_keyword", "params": {"keywords": keywords}})
    specs = [EffectSpec("grant_until", {
        "duration": "end_of_turn" if m.group("eot") else "rest_of_game",
        "target_kind": kind, "static": static,
        **({"extra_statics": extra_statics} if extra_statics else {}),
    })]
    if m.groupdict().get("must_blocked"):
        specs.append(EffectSpec("pump", {"previous_subject": True, "keywords": ["must_be_blocked"]}))
    return specs


#: PAR-124: the TARGET sibling of `_ANIMATE_SELF_LEADING_EOT_RE` — "Until
#: end of turn, target land you control becomes a 4/4 dinosaur creature
#: with reach and haste. It's still a land." (Disturbed Slumber/Elemental
#: Uprising) puts the duration in front of "target …", unlike
#: `_ANIMATE_TARGET_RE`'s trailing-``eot`` ordering. A trailing "it must be
#: blocked this turn if able." sentence, when present, is folded into this
#: same regex rather than left to the generic `previous_subject`
#: connector-split pipeline — that split would hand the *pure-reminder*
#: "it's still a land" sentence its own unclaimed part first (nothing
#: builds an `EffectSpec` for it alone), failing the whole body closed
#: before the tail is ever reached (see `_ANIMATE_TARGET_RE`'s identical
#: reasoning).
_ANIMATE_TARGET_LEADING_EOT_RE = _c(
    r"until end of turn, target (?:snow )?"
    r"(?P<kind>land|mountain|forest|artifact|creature|enchantment|creature or land)"
    r"(?P<you_control> you control)? becomes "
    r"an? (?P<p>\d+)/(?P<t>\d+) (?P<quals>(?:[a-z]+ )*?)creature"
    r"(?: with (?P<kw>[a-z, ]+?))?"
    r"(?:\. it'?s still an? (?:snow )?(?:(?P=kind)|land))?"
    r"(?P<must_blocked>\. it must be blocked this turn if able)?"
)


def _animate_target_leading_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    quals = _split_animate_qualifiers(m.group("quals"))
    if quals is None:
        return None
    colors, add_types, add_subtypes = quals
    kind = resolve_target_kind(
        "target " + m.group("kind") + (m.group("you_control") or "")
    )
    if kind is None:
        return None
    static: dict[str, Any] = {
        "type": "type_change",
        "params": {
            "add_types": ["creature"] + add_types,
            "power": int(m.group("p")), "toughness": int(m.group("t")),
            **({"add_subtypes": add_subtypes} if add_subtypes else {}),
        },
    }
    extra_statics = []
    if colors:
        extra_statics.append({"type": "color", "params": {"colors": colors, "set": True}})
    kw = m.groupdict().get("kw")
    if kw:
        keywords = _token_keywords(kw)
        if keywords is None:
            return None
        extra_statics.append({"type": "grant_keyword", "params": {"keywords": keywords}})
    specs = [EffectSpec("grant_until", {
        "duration": "end_of_turn", "target_kind": kind, "static": static,
        **({"extra_statics": extra_statics} if extra_statics else {}),
    })]
    if m.groupdict().get("must_blocked"):
        specs.append(EffectSpec("pump", {"previous_subject": True, "keywords": ["must_be_blocked"]}))
    return specs


# --- The table --------------------------------------------------------------
# Order matters only for reporting; a clause is claimed by the first handler
# whose full-clause regex matches. Every pattern is anchored to the whole
# clause by `EffectHandler.match`'s `fullmatch`, so no partial claims.

#: PAR-121: the subject-scope slot of a verb. A clause whose subject is a bare pronoun ("it"/"that creature") means
#: a different object under each kind of ability — the source (``self``), an earlier clause's pick (``previous``),
#: the creature a group trigger fired for (``group``), an Aura/Equipment's host (``attached``) — and
#: `EffectHandler` gates each reading with its own flag. A verb used to register one near-identical row per
#: reading; `_subject_handlers` declares it once: ``(row name, subject, regex, builder)`` per reading.
_SUBJECT_FLAGS: dict[str, dict[str, bool]] = {
    "any": {},
    "self": {"self_subject_only": True},
    "previous": {"previous_subject_only": True},
    "group": {"group_subject_only": True},
    "attached": {"attached_subject_only": True},
}


def _subject_handlers(
    rows: "list[tuple[str, str, re.Pattern[str], Callable[[re.Match[str]], Optional[list[EffectSpec]]]]]",
) -> list[EffectHandler]:
    return [EffectHandler(name, regex, build, **_SUBJECT_FLAGS[subject]) for name, subject, regex, build in rows]


HANDLERS: list[EffectHandler] = [
    # RULE 701.47/48 Amass "<Type> N" — "amass Orcs 1"/"amass Zombies 2".
    # Tried before the untyped row below since a real type word always
    # parses here first (the untyped row's bare NUMBER can never see it —
    # a type word isn't a digit — so the ordering is purely cosmetic).
    EffectHandler("amass", _AMASS_RE, _amass),
    # RULE 701.47d's pre-errata bare "amass N" (no subtype) — see the
    # builder's own docstring; not expected to match any card in today's
    # already-errata'd cache.
    EffectHandler("amass_untyped", _AMASS_UNTYPED_RE, _amass_untyped),
    # "~ deals 2 damage to any target. If this spell was kicked, it deals 4
    # damage instead." — the two-sentence override form, tried before the
    # single-sentence `_damage` row below since only this one's regex spans
    # the whole clause.
    EffectHandler(
        "damage_kicked_override",
        _DAMAGE_KICKED_OVERRIDE_RE,
        _damage_kicked_override,
    ),
    # "Create a token that's a copy of target creature. If this spell was
    # kicked, create five of those tokens instead." (Rite of Replication) —
    # tried before the bare `copy_permanent` row for the same two-sentence-
    # spans-the-whole-clause reason as the damage row above.
    EffectHandler(
        "copy_permanent_kicked_override",
        _COPY_PERMANENT_KICKED_OVERRIDE_RE,
        _copy_permanent_kicked_override,
    ),
    # "Create a token that's a copy of target creature[, except <modifier(s)>]."
    # (RULE 707/706.2, Cackling Counterpart/Multiversal Recruitment/Impostor
    # Syndrome-shaped) — the bare form and every safely-generalizable
    # compound "except" tail in one row (`_parse_copy_except_tail`).
    EffectHandler(
        "copy_permanent",
        _COPY_PERMANENT_RE,
        _copy_permanent,
    ),
    EffectHandler(
        "copy_self",
        _COPY_SELF_RE,
        _copy_self,
    ),

    # PAR-18: "exile up to 1 target creature card from a graveyard. Create a
    # token that's a copy of it/that card[, except <modifier(s)>]." — the
    # pronoun sibling of the row above, offered only once an earlier clause
    # of the same ability actually chose something (`GameContext.
    # previous_targets`).
    EffectHandler(
        "copy_permanent_previous",
        _COPY_PERMANENT_PREVIOUS_RE,
        _copy_permanent_previous,
        previous_subject_only=True,
    ),
    # PAR-124: "whenever a nontoken creature an opponent controls enters,
    # create a token that's a copy of that creature." (Theoretical
    # Duplication) — the RULE 603.1 group-subject sibling of the row above.
    EffectHandler(
        "copy_permanent_group",
        _COPY_PERMANENT_GROUP_RE,
        _copy_permanent_group,
        group_subject_only=True,
    ),
    # "create a token that's a [tapped and attacking] copy of <named real
    # card>" (The Joiner of Cats' Lurrus else-branch) — after the target /
    # pronoun rows so those keep their forms; the name group already
    # excludes their leading words.
    EffectHandler(
        "create_token_copy_of_named",
        _CREATE_NAMED_CARD_TOKEN_RE,
        _create_named_card_token,
    ),
    # "for each card you've discarded this turn, create a token that's a
    # copy of ~[, except the token isn't legendary]" (Living Laser) — a
    # self-copy scaled by a `continuous.count_selector`.
    EffectHandler(
        "copy_self_for_each",
        _COPY_SELF_FOR_EACH_RE,
        _copy_self_for_each,
    ),
    # "Exile a permanent card from your graveyard at random, then create a
    # tapped token that's a copy of that card. If the exiled card is a land
    # card, repeat this process." (Sin, Spira's Punishment)
    EffectHandler(
        "random_graveyard_exile_copy_loop",
        _RANDOM_GY_EXILE_COPY_LOOP_RE,
        _random_gy_exile_copy_loop,
    ),
    # Tried before the plain `damage` row below, whose `TARGET` alternation
    # has no two-colour-OR creature filter of its own.
    EffectHandler(
        "damage_target_two_color",
        _DAMAGE_TARGET_TWO_COLOR_RE,
        _damage_target_two_color,
    ),
    # "~ deals 3 damage to target creature with flying" / "…with power 4 or
    # greater" (RULE 115/601.2c quality filter) — before the plain `damage`
    # row for the same "strict superset of 'target creature'" reason
    # `destroy_creature_filter` precedes `destroy`.
    EffectHandler(
        "damage_creature_filter",
        _DAMAGE_CREATURE_FILTER_RE,
        _damage_creature_filter,
    ),
    EffectHandler(
        "damage_target_and_selector",
        _DAMAGE_TARGET_AND_SELECTOR_RE,
        _damage_target_and_selector,
    ),
    # "This creature deals 1 damage to target player or planeswalker. If
    # this creature is a Wizard, it deals 2 damage instead." (Sorcerer's
    # Wand) — type-sensitive amount override, before plain damage whose
    # fullmatch deliberately rejects the conditional tail.
    EffectHandler(
        "damage_if_source_subtype",
        _c(
            rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to target player or planeswalker\. "
            rf"if (?:~|this creature) is an? (?P<subtype>[a-z]+), it deals? (?P<n2>\d+) damage instead"
        ),
        lambda m: [EffectSpec("damage", {
            "amount": int(m.group("n")), "target_kind": "player",
            "amount_if_source_subtype": {"subtype": m.group("subtype"), "amount": int(m.group("n2"))},
        })],
    ),
    # "This creature deals 1 damage to target creature. If a colorless
    # creature is dealt damage this way, tap it." (Pathway Arrows) — a
    # rider on the same target, before the plain-damage fallback.
    EffectHandler(
        "damage_tap_target_if_colorless",
        _c(
            rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to target creature\. "
            r"if a colorless creature is dealt damage this way, tap it"
        ),
        lambda m: [EffectSpec("damage", {
            "amount": int(m.group("n")), "target_kind": "creature", "tap_target_if_colorless": True,
        })],
    ),
    # "This creature deals N damage to target creature that's blocking it"
    # (Arc Spitter). The qualifier is a combat-assignment target restriction,
    # not a generic creature quality filter.
    EffectHandler(
        "damage_creature_blocking_source",
        _c(rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to target creature that'?s blocking (?:it|~)"),
        lambda m: [EffectSpec("damage", {
            "amount": int(m.group("n")), "target_kind": "creature_blocking_source",
        })],
    ),
    # "Whenever ~ is dealt damage, it deals **that much** damage to any
    # target." (Boros Reckoner and the wider reflection family). The amount
    # is antecedent-dependent, so the gate validates and resolves the
    # ``that_much`` sentinel against the enclosing trigger before a card may
    # become MODELED; a spell/activation with the same words stays refused.
    EffectHandler(
        "damage_that_much",
        _c(rf"{SELF_SUBJECT_PREFIX}deals? that much damage to {TARGET}"),
        _damage_that_much,
    ),
    # "~ deals 3 damage to any target" / "deal 2 damage to target creature" /
    # "it deals 2 damage to target opponent" (a triggered-ability body's own
    # "it"/"this creature"/"this land"/"this permanent" subject — cosmetic,
    # since the source is already bound at bind time regardless of wording).
    EffectHandler(
        "damage",
        _c(rf"{SELF_SUBJECT_PREFIX}deals? {NUMBER} damage to {TARGET}"),
        _damage,
    ),
    # "~ deals X damage to any target." (Blaze/Devil's Play/Fanning the
    # Flames, and every "{X}{R}, {T}, Sacrifice ~: it deals X damage …"
    # activated ability) — the {X}-scaled sibling, emitting the ``"x"``
    # sentinel `RulesEngine._substitute_x` rewrites off the spell/ability's
    # announced {X}. Digit-free, so no overlap with the `NUMBER` row above.
    EffectHandler(
        "damage_x_source_counters",
        _DAMAGE_X_SOURCE_COUNTERS_RE,
        _damage_x_source_counters,
    ),
    EffectHandler(
        "damage_x_defending_player_hand",
        _DAMAGE_X_DEFENDING_PLAYER_HAND_RE,
        _damage_x_defending_player_hand,
        self_subject_only=True,
    ),
    EffectHandler(
        "damage_x",
        _c(rf"{SELF_SUBJECT_PREFIX}deals? (?P<twice>twice )?x damage to {TARGET}"),
        _damage_x,
    ),
    # "~ deals damage equal to that spell's mana value to target opponent."
    # (Passionate Archaeologist's granted cast trigger, PAR-32) — the
    # amount is the firing `SPELL_CAST` event's own ``mana_value`` field,
    # the same "read that spell's MV off the event" idiom `_incubate_x`'s
    # ``spell_mv`` branch uses (`DealDamageEffect.amount_from_trigger_event`).
    EffectHandler(
        "damage_spell_mv",
        _c(
            rf"(?:(?:~|it|this creature) )?deals? damage equal to that spell'?s "
            rf"mana value to {TARGET}"
        ),
        _damage_spell_mv,
    ),
    # "~ deals N damage to each creature blocking it" (Fire Juggler-shaped,
    # 4 cards) — `DealDamageEffect`'s `each_creature_blocking_source`
    # selector; "it" is the attacker (this ability's own source).
    EffectHandler(
        "damage_each_blocker",
        _c(r"(?:~ )?deals? (?P<n>\d+) damage to each creature blocking (?:it|~)"),
        lambda m: [EffectSpec("damage", {
            "amount": int(m.group("n")), "selector": "each_creature_blocking_source",
        })],
    ),
    # PAR-128: "each of those creatures deals damage equal to its power to ~." (Polukranos,
    # World Eater) — the earlier clause's targets are the dealers; the recipient is the source.
    EffectHandler(
        "damage_equal_to_power_previous_group_to_source",
        _c(r"each of those creatures deals damage equal to its power to (?:~|this creature)"),
        lambda m: [EffectSpec("damage_equal_to_power", {"dealer_group": "previous_targets"})],
        previous_subject_only=True,
    ),
    EffectHandler(
        "damage_to_attacked_defender", _DAMAGE_TO_ATTACKED_RE, _damage_to_attacked,
        group_subject_only=True,
    ),
    EffectHandler(
        "group_deals_to_damaged_controller", _GROUP_DEALS_TO_DAMAGED_CONTROLLER_RE,
        _group_deals_to_damaged_controller, group_subject_only=True,
    ),
    EffectHandler(
        "group_deals_to_its_controller", _GROUP_DEALS_TO_ITS_CONTROLLER_RE,
        _group_deals_to_its_controller, group_subject_only=True,
    ),
    # "~ [also] deals N damage to that creature's controller" (~22 SOLO —
    # Consign to the Pit / Battle Strain / Dingus Staff / …).
    EffectHandler(
        "damage_to_prev_subject_controller",
        _DAMAGE_TO_SUBJECT_CONTROLLER_RE, _damage_to_prev_subject_controller,
        previous_subject_only=True,
    ),
    EffectHandler(
        "damage_to_trigger_subject_controller",
        _DAMAGE_TO_SUBJECT_CONTROLLER_RE, _damage_to_trigger_subject_controller,
        group_subject_only=True,
    ),
    # "~ deals 6 damage to each of up to two target creatures and/or
    # planeswalkers" (RULE 115.1a generalized to N>=2) — the full amount
    # applies to *every* chosen target, not divided among them.
    EffectHandler(
        "damage_each_multi_target",
        _c(
            rf"{SELF_SUBJECT_PREFIX}"
            rf"deals? (?P<amount>\d+) damage to each of {_MULTI_TARGET_QUANTIFIER}"
            rf"(?P<target>{_MULTI_TARGET_ALT})"
        ),
        _damage_each_multi_target,
    ),
    # ENG-30: "deals N damage to each of 1 or 2 targets" (Storm of Steel) —
    # tried before the row above since that row's `_MULTI_TARGET_ALT` has no
    # bare "targets" option (RULE 115.4 "any target" is specific to
    # damage/prevention, unlike destroy/exile/tap's typed object phrasing —
    # see `_DAMAGE_EACH_RANGE_RE`'s own comment for why this stays a local
    # alternation instead of widening the shared table).
    EffectHandler(
        "damage_each_range",
        _DAMAGE_EACH_RANGE_RE,
        _damage_each_range,
    ),
    # RULE 601.2d "divided as you choose among any number of target(s)"
    # (PAR-15) — a split total, not the "each of N" full-amount shape above.
    EffectHandler(
        "divided_damage",
        _DIVIDED_DAMAGE_RE,
        _divided_damage,
    ),
    # ENG-30: "deals N damage divided as you choose among 1 or 2 targets"
    # (Arc Mage/Chandra's Pyrohelix/Electrolyze/Fire // Ice/Forked Bolt/
    # Skarrgan Hellkite) — tried before the row above for the same reason.
    EffectHandler(
        "divided_damage_range",
        _DIVIDED_DAMAGE_RANGE_RE,
        _divided_damage_range,
    ),
    # RULE 615's divided-prevention sibling (PAR-15) — Embolden/Remedy/
    # Angel of Salvation.
    EffectHandler(
        "prevent_divided_damage",
        _PREVENT_DIVIDED_DAMAGE_RE,
        _prevent_divided_damage,
    ),
    # RULE 615's plain single-target sibling — Alabaster Wall/Amulet of
    # Kroog/Aven Redeemer-shaped.
    EffectHandler(
        "prevent_damage_single_target",
        _PREVENT_DAMAGE_SINGLE_TARGET_RE,
        _prevent_damage_single_target,
    ),
    EffectHandler(
        "prevent_next_damage_target_creature",
        _PREVENT_NEXT_DAMAGE_TARGET_CREATURE_RE,
        _prevent_next_damage_target_creature,
    ),
    EffectHandler(
        "prevent_shield_then_rider",
        _PREVENT_SHIELD_THEN_RIDER_RE,
        _prevent_shield_then_rider,
    ),
    EffectHandler(
        "prevent_damage_player_planeswalker_or_subtype",
        _PREVENT_DAMAGE_PLAYER_PLANESWALKER_OR_SUBTYPE_RE,
        _prevent_damage_player_planeswalker_or_subtype,
    ),
    EffectHandler(
        "prevent_next_damage_to_you",
        _PREVENT_NEXT_DAMAGE_TO_YOU_RE,
        _prevent_next_damage_to_you,
    ),
    # RULE 615's unscoped Fog-shaped form — no recipient at all.
    EffectHandler(
        "prevent_all_combat_damage_dealt_self",
        _PREVENT_ALL_COMBAT_DAMAGE_DEALT_SELF_RE,
        _prevent_all_combat_damage_dealt_self,
    ),
    EffectHandler(
        "prevent_all_combat_damage",
        _PREVENT_ALL_COMBAT_DAMAGE_RE,
        _prevent_all_combat_damage,
    ),
    EffectHandler(
        "prevent_all_combat_damage_to_self",
        _PREVENT_ALL_COMBAT_DAMAGE_TO_SELF_RE,
        _prevent_all_combat_damage_to_self,
    ),
    # PAR-78: "Prevent all damage that would be dealt to <recipient>[ by
    # <source filter>]." — five recipient shapes, tried target/enchanted
    # first (most specific) so the bare-self/you/creatures rows below don't
    # need to actively exclude "target"/"enchanted creature" themselves.
    EffectHandler(
        "prevent_all_damage_target",
        _PREVENT_ALL_DAMAGE_TARGET_RE,
        _prevent_all_damage_target,
    ),
    EffectHandler(
        "prevent_all_damage_previous",
        _PREVENT_ALL_DAMAGE_PREVIOUS_RE,
        _prevent_all_damage_previous,
        previous_subject_only=True,
    ),
    EffectHandler(
        "prevent_all_damage_self_pronoun",
        _PREVENT_ALL_DAMAGE_SELF_PRONOUN_RE,
        _prevent_all_damage_self_pronoun,
        self_subject_only=True,
    ),
    EffectHandler(
        "prevent_all_damage_enchanted",
        _PREVENT_ALL_DAMAGE_ENCHANTED_RE,
        _prevent_all_damage_enchanted,
    ),
    EffectHandler(
        "prevent_all_damage_creatures",
        _PREVENT_ALL_DAMAGE_CREATURES_RE,
        _prevent_all_damage_creatures,
    ),
    EffectHandler(
        "prevent_all_damage_you",
        _PREVENT_ALL_DAMAGE_YOU_RE,
        _prevent_all_damage_you,
    ),
    EffectHandler(
        "prevent_all_damage_self",
        _PREVENT_ALL_DAMAGE_SELF_RE,
        _prevent_all_damage_self,
    ),
    EffectHandler(
        "damage_per_noncreature_spell_cast_this_turn",
        _DAMAGE_PER_NONCREATURE_SPELL_CAST_THIS_TURN_RE,
        _damage_per_noncreature_spell_cast_this_turn,
    ),
    # Tried before the single-sentence row below (a strict superset of its
    # own opening clause, so it must win the race or never get a turn).
    EffectHandler(
        "damage_each_opponent_and_creatures_exile",
        _DAMAGE_EACH_OPPONENT_AND_CREATURES_EXILE_RE,
        _damage_each_opponent_and_creatures_exile,
    ),
    # Tried before the plain `damage_selector` row below (its own "each
    # opponent" alternative would otherwise match first and leave "and each
    # creature they control" unconsumed, failing the clause closed).
    EffectHandler(
        "damage_each_opponent_and_creatures",
        _DAMAGE_EACH_OPPONENT_AND_CREATURES_RE,
        _damage_each_opponent_and_creatures,
    ),
    # "~ deals 2 damage to each creature" / "… to each player" / "… to each
    # opponent" / "… to each creature and each player" / "… to each creature
    # and each planeswalker" / "… to you" (RULE 109.5 self, the upkeep-bleed
    # shape) — a mass/self effect (RULE 601.2c), not RULE 115 targeting. The
    # two "and each …" unions come first in the alternation so the bare
    # "each creature" branch can't consume a prefix and then fail the
    # fullmatch on the trailing "and each …".
    # "~ deals N damage to each creature without flying [and each player]"
    # (Earthquake / Fault Line) / "…with/without horsemanship…" (MEC-87,
    # Borrowing the East Wind / Rolling Earthquake) — before the plain
    # `damage_selector` row, whose bare "each creature" alternative would
    # otherwise consume the prefix and fail the fullmatch on the filter tail.
    EffectHandler(
        "damage_each_creature_keyword",
        _DAMAGE_EACH_CREATURE_KEYWORD_RE,
        _damage_each_creature_keyword,
    ),
    EffectHandler("damage_each_damaged_creature", _DAMAGE_EACH_DAMAGED_CREATURE_RE, _damage_each_damaged_creature),
    EffectHandler("damage_each_creature_kicked", _DAMAGE_EACH_CREATURE_KICKED_RE, _damage_each_creature_kicked),
    EffectHandler(
        "damage_to_you_per_treasure",
        _DAMAGE_TO_YOU_PER_TREASURE_RE,
        _damage_to_you_per_treasure,
    ),
    EffectHandler(
        "damage_to_you_unless_pay",
        _DAMAGE_TO_YOU_UNLESS_PAY_RE,
        _damage_to_you_unless_pay,
    ),
    # The mass/self recipient sibling of ``damage_that_much`` above:
    # Amarant Coral/Hydra Omnivore (each other opponent), Coalhauler Swine
    # (each player), and Firedrinker Satyr/Jackal Pup (you). The same gate
    # resolves/refuses the antecedent amount.
    EffectHandler(
        "damage_that_much_selector",
        _c(
            rf"{SELF_SUBJECT_PREFIX}deals? that much damage to "
            r"(?P<selector>each creature and each player|each creature and each planeswalker|"
            r"each creature|each player|each opponent|each other opponent|you)"
        ),
        _damage_that_much_selector,
    ),
    # "that player" is the firing event's player only under the source's own trigger ("whenever ~ deals combat damage
    # to a player, that player skips …"); after a clause that chose a player it is that pick, which this does not read.
    EffectHandler("skip_their_next", _SKIP_THEIR_NEXT_RE, lambda m: None if m.group("who") == "that player" else _skip_their_next(m)),
    EffectHandler(
        "skip_their_next_event_player", _SKIP_THEIR_NEXT_RE,
        lambda m: _skip_their_next(m) if m.group("who") == "that player" else None, self_subject_only=True,
    ),
    EffectHandler(
        "skip_your_draw_step_this_turn",
        _SKIP_YOUR_DRAW_STEP_THIS_TURN_RE,
        _skip_your_draw_step_this_turn,
    ),
    EffectHandler(
        "damage_selector",
        _c(
            rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+|x) damage to "
            rf"(?P<selector>each creature and each player|each creature and each planeswalker"
            rf"|each creature your opponents control|each creature an opponent controls"
            rf"|each other creature|each creature|each player|each of your opponents|each opponent|that player|them|you)"
        ),
        _damage_selector,
    ),
    # "…to each other creature **that player** controls" after a clause that chose a
    # creature (Flames of the Raze-Boar): that clause's target's controller, offered only
    # once a previous clause supplied one; otherwise `damage_group` reads a trigger's player.
    EffectHandler(
        "damage_group_previous_controller", _DAMAGE_GROUP_RE,
        lambda m: _damage_group(m, that_player="previous_controller")
        if m.group("group").endswith(" that player controls") else None,
        previous_subject_only=True,
    ),
    EffectHandler("damage_plus_additional", _DAMAGE_PLUS_ADDITIONAL_RE, _damage_plus_additional),
    EffectHandler("damage_group", _DAMAGE_GROUP_RE, _damage_group),
    # RULE 202.2f/700.6 "it deals damage to each opponent equal to your
    # devotion to <colour>." (Fanatic of Mogis) — tried before the plain
    # `damage_selector` row above since "equal to …" has no digit `NUMBER`
    # for that row to match.
    EffectHandler("damage_selector_devotion", _DAMAGE_SELECTOR_DEVOTION_RE, _damage_selector_devotion),
    # MEC-27: the draw/gain-life/lose-life verb families `{DEVOTION}` had
    # never reached — always the ability's own controller, unlike the mass
    # "each player/opponent loses life" row below.
    EffectHandler("draw_devotion", _DRAW_DEVOTION_RE, _draw_devotion),
    EffectHandler("gain_life_devotion", _GAIN_LIFE_DEVOTION_RE, _gain_life_devotion),
    EffectHandler("lose_life_self_devotion", _LOSE_LIFE_SELF_DEVOTION_RE, _lose_life_self_devotion),
    EffectHandler(
        "draw_and_lose_life_devotion", _DRAW_AND_LOSE_LIFE_DEVOTION_RE, _draw_and_lose_life_devotion
    ),
    EffectHandler(
        "gain_life_and_draw_devotion", _GAIN_LIFE_AND_DRAW_DEVOTION_RE, _gain_life_and_draw_devotion
    ),
    EffectHandler(
        "gain_life_and_draw_sac_power",
        _GAIN_LIFE_AND_DRAW_SAC_POWER_RE,
        _gain_life_and_draw_sac_power,
    ),
    EffectHandler(
        "draw_and_gain_life_devotion", _DRAW_AND_GAIN_LIFE_DEVOTION_RE, _draw_and_gain_life_devotion
    ),
    EffectHandler(
        "lose_life_and_gain_life_devotion",
        _LOSE_LIFE_AND_GAIN_LIFE_DEVOTION_RE,
        _lose_life_and_gain_life_devotion,
    ),
    # "Each creature deals 1 damage to its controller." (Rakdos Charm).
    EffectHandler(
        "damage_each_creature_to_controller",
        _DAMAGE_EACH_CREATURE_TO_CONTROLLER_RE,
        _damage_each_creature_to_controller,
    ),
    # "You may pay <cost>. If you do, draw a card." (RULE 118.3).
    EffectHandler(
        "pay_cost_then_draw",
        _PAY_COST_THEN_DRAW_RE,
        _pay_cost_then_draw,
    ),
    # "draw that many cards" (Vilis, Broker of Blood-shaped "that many"
    # trigger-event payoff) — tried before the plain row below since it's a
    # strict superset match on that specific phrase.
    EffectHandler(
        "draw_that_many",
        _DRAW_THAT_MANY_RE,
        _draw_that_many,
    ),
    EffectHandler("sacrifice_greatest_power", _SACRIFICE_GREATEST_POWER_RE, _sacrifice_greatest_power),
    EffectHandler(
        "tokens_per_target_player_creature", _TOKENS_PER_TARGET_PLAYER_CREATURE_RE,
        _tokens_per_target_player_creature,
    ),
    EffectHandler(
        "any_opponents_sacrifice_lose", _ANY_OPPONENTS_SACRIFICE_LOSE_RE, _any_opponents_sacrifice_lose,
    ),
    EffectHandler("wheel", _WHEEL_RE, _wheel),
    EffectHandler("may_wheel", _MAY_WHEEL_RE, _may_wheel),
    EffectHandler(
        "draw_additional",
        _DRAW_ADDITIONAL_RE,
        lambda m: [EffectSpec("draw", {"count": 1})],
    ),
    # "Target player draws N cards, then discards M cards." (Prismari
    # Command) — tried before the plain `draw` row, whose bare match would
    # leave the trailing "then discards …" dangling with no subject link.
    EffectHandler(
        "target_player_loot",
        _TARGET_PLAYER_LOOT_RE,
        _target_player_loot,
    ),
    # "you and target opponent each draw N cards." — before the generic
    # `draw` row (whose optional `who` group would otherwise claim just the
    # "you" prefix and choke on the "and target opponent" tail).
    EffectHandler(
        "you_and_target_opponent_draw",
        _YOU_AND_TARGET_OPP_DRAW_RE,
        _you_and_target_opponent_draw,
    ),
    # "draw a card" / "draw 3 cards" / "you draw two cards" / "draw X cards" /
    # "target player draws a card" / "each opponent draws a card"
    EffectHandler(
        "draw",
        _c(
            r"(?P<who>you|target player|target opponent|each player|each opponent)?\s*"
            rf"draws? {COUNT_X} cards?"
        ),
        _draw,
    ),
    # "draw a card at the beginning of the next turn's upkeep" (RULE 603.7
    # delayed trigger) — Clairvoyance/Balduvian Rage/Carrier Pigeons-shaped.
    EffectHandler(
        "draw_next_upkeep",
        _c(rf"(?:you )?draws? {COUNT} cards? at the beginning of the next turn's upkeep"),
        _draw_next_upkeep,
    ),
    # PAR-13: "exile the top N cards of your library. you may play them
    # [this turn/until the end of your next turn]." — RULE 601.3b impulsive
    # draw (Runestone Caverns/Bonehoard Dracosaur/Painter's Studio-shaped).
    EffectHandler(
        "exile_top_play",
        _EXILE_TOP_PLAY_RE,
        _exile_top_play,
    ),
    # PAR-13: "draw N cards and reveal them. you may cast one of them
    # without paying its mana cost." — Mad Wizard's Lair's own room.
    EffectHandler(
        "draw_reveal_cast_free",
        _DRAW_REVEAL_CAST_FREE_RE,
        _draw_reveal_cast_free,
    ),
    # MEC-20: RULE 601.2f "Expertise" cycle — "you may cast a spell with
    # mana value N/X or less from your hand without paying its mana cost
    # [, where x is the number of attacking creatures]".
    EffectHandler(
        "free_cast_from_hand",
        _FREE_CAST_FROM_HAND_RE,
        _free_cast_from_hand,
    ),
    EffectHandler(
        "cheat_creature_from_hand",
        _CHEAT_CREATURE_FROM_HAND_RE,
        _cheat_creature_from_hand,
    ),
    # ENG-33: "you may put a <type> card from your hand onto the
    # battlefield" (Dr. Eggman — a villainous-choice option body).
    EffectHandler(
        "put_from_hand",
        _PUT_FROM_HAND_RE,
        _put_from_hand,
    ),
    # "Target opponent reveals their hand. You choose a nonland card from
    # it. That player discards that card." (Duress/Thoughtseize-shaped) —
    # tried before the plain `discard` row below (unrelated shapes, but
    # this one's much longer clause should never partially match that
    # row's short one anyway).
    EffectHandler(
        "hand_disruption_discard",
        _HAND_DISRUPTION_RE,
        _hand_disruption_discard,
    ),
    EffectHandler("hand_pick", _HAND_PICK_RE, _hand_pick),
    # "exile target non-Angel creature you control, then return that card
    # to the battlefield under your control." (Restoration Angel-shaped).
    EffectHandler(
        "blink_non_subtype",
        _BLINK_NON_SUBTYPE_RE,
        _blink_non_subtype,
    ),
    # "exile [up to N] [another] target creature/[nonland] permanent you
    # control, then return that card/it to the battlefield under your/its
    # owner's control." (Felidar Guardian/Emiel the Blessed/Displacer
    # Kitten-shaped) — tried after the subtype-exclusion row above so a
    # Restoration Angel-shaped clause still matches that narrower row first.
    EffectHandler(
        "blink_plain",
        _BLINK_PLAIN_RE,
        _blink_plain,
    ),
    # "defending player reveals the top card of their library. If it's a
    # land card, that player puts it into their hand." (Goblin Guide-shaped).
    EffectHandler(
        "reveal_top_conditional",
        _REVEAL_TOP_CONDITIONAL_RE,
        _reveal_top_conditional,
    ),
    # "create an X/X blue Shark creature token with flying, where X is that
    # spell's mana value." (Shark Typhoon-shaped spell-cast payoff). Note
    # `_cycling_xx_token`/`_CYCLING_XX_TOKEN_RE` (this row's sibling for
    # RULE 702.28c's Cycling-cost X) is deliberately NOT registered here —
    # a bare "create an X/X ... token." with no trailing explanation is
    # ambiguous outside a "when you cycle this card" wrapper (Wurmcalling/
    # Slime Molding's X is their own {X} mana cost, not a Cycling cost) —
    # `segmenter.py`'s cycle-trigger dispatch calls it directly instead,
    # scoped to exactly that context.
    EffectHandler(
        "mana_value_xx_token",
        _MANA_VALUE_XX_TOKEN_RE,
        _mana_value_xx_token,
    ),
    # "you discard a card" / "discard 2 cards" / "target player discards a
    # card" / "…discards a card at random" (RULE 701.8d — Black Cat /
    # Hypnotic Specter / Bottomless Pit's "that player" via the
    # `that_player_discards` row).
    EffectHandler(
        "that_player_discards_that_many",
        _c(r"that player discards that many cards?"),
        _that_many_player_discards,
    ),
    EffectHandler("discard_unless", _DISCARD_UNLESS_RE, _discard_unless),
    # "Untap up to three lands." (Frantic Search, Cloud of Faeries, Palinchron, Peregrine Drake) — an untargeted pick
    # (`choose_objects` with the ``untap`` action), unlike "untap up to two **target** lands" (RULE 115).
    EffectHandler(
        "untap_up_to_lands",
        _c(r"untap up to (?P<n>\d+) lands"),
        lambda m: [EffectSpec("choose_objects", {
            "action": "untap", "what": "land", "count": int(m.group("n")), "optional": True,
            "prompt": "Wähle bis zu %d Länder zum Enttappen" % int(m.group("n")),
        })],
    ),
    EffectHandler(
        "discard",
        _c(
            r"(?P<who>you|target player|target opponent|each player|each opponent)?\s*"
            rf"discards? {COUNT} cards?(?P<at_random> at random)?"
        ),
        _discard,
    ),
    # "look at target player's hand." (Clairvoyance, Peek, Glasses of Urza) — an informational pick, see
    # `RulesEngine.look_at_hand`; "that player's hand" follows an earlier clause that chose the player.
    EffectHandler(
        "look_at_hand",
        _c(r"look at target (?P<who>player|opponent)'s hand"),
        lambda m: [EffectSpec("look_at_hand", {
            "target_kind": "opponent" if m.group("who") == "opponent" else "player"})],
    ),
    # PAR-74: "target opponent exiles a card from their hand." (Kyoki,
    # Sanity's Eclipse) — the exile-zone sibling of the plain ``discard``
    # row above; RULE 701.5a's interactive "that player chooses" (the
    # `ExileHandCardEffect`/`exile_hand_choice` chooser, not an auto-pick).
    EffectHandler(
        "exile_hand_card",
        _c(
            rf"(?P<who>you|target player|target opponent) exiles? {COUNT} "
            r"cards? from (?:your|their) (?P<zone>hand|graveyard)"
        ),
        lambda m: [EffectSpec("exile_hand_card", {
            "count": count_of(m.group("n")),
            **({"zone": "graveyard"} if m.group("zone") == "graveyard" else {}),
            **(
                {"target_kind": "player"}
                if m.group("who") in ("target player", "target opponent")
                else {}
            ),
        })],
    ),
    # PAR-74: "target player reveals their hand and discards all cards with
    # that spell's mana value." (Infernal Kirin) — "reveals their hand" is
    # pure flavor at this engine's fidelity (same treatment `_SEARCH_REVEAL`
    # gives a tutor's own "reveal it," — nothing else reads the reveal), so
    # only the discard half becomes an effect: RULE 601.2c's non-interactive
    # "all `<X>`" mass discard (`DiscardEffect.filter`'s new
    # ``mana_value_from_trigger_event`` key, `DestroyEffect.filter`'s
    # identical key/referent).
    EffectHandler(
        "reveal_hand_discard_matching_mv",
        _c(
            r"(?P<who>target player|target opponent) reveals? (?:their|its) hand "
            r"and discards? all cards with that spell'?s mana value"
        ),
        lambda m: [EffectSpec("discard", {
            "target_kind": "player", "filter": {"mana_value_from_trigger_event": True},
        })],
    ),
    # PAR-13: "each player loses N life unless they discard a card/sacrifice
    # a creature, artifact, or land of their choice." — Veils of Fear/
    # Sandfall Cell's own APNAP mass "unless".
    EffectHandler(
        "each_player_lose_life_unless",
        _EACH_PLAYER_LOSE_LIFE_UNLESS_RE,
        _each_player_lose_life_unless,
    ),
    # "each player/opponent sacrifices a[n] [nontoken] creature/artifact/
    # land/permanent of their choice" (Accursed Marauder/Liliana, Dreadhorde
    # General's -4 mass edict).
    EffectHandler(
        "sacrifice_edict",
        _SACRIFICE_EDICT_RE,
        _sacrifice_edict,
    ),
    # ENG-33: "target player/opponent sacrifices a <what> of their choice"
    # (Diabolic Edict-shaped, and villainous/vote's *other* option).
    EffectHandler(
        "target_player_edict",
        _TARGET_PLAYER_EDICT_RE,
        _target_player_edict,
    ),
    EffectHandler(
        "sacrifice_controller",
        _SACRIFICE_CONTROLLER_RE,
        _sacrifice_controller,
    ),
    # PAR-13: "discard a card and sacrifice a creature, an artifact, and a
    # land." — Oubliette's own compound mandatory punishment.
    EffectHandler(
        "discard_and_sacrifice_triple",
        _DISCARD_AND_SACRIFICE_TRIPLE_RE,
        _discard_and_sacrifice_triple,
    ),
    # "you gain 3 life" / "gain 5 life" / "target player gains 3 life" /
    # "you gain x life" (an {X}-cost spell/ability's own announced X).
    EffectHandler(
        "gain_life",
        _c(rf"(?P<who>you |target player )?gains? (?P<n>x|twice x|\d+) life"),
        _gain_life,
    ),
    # Elemental Spectacle / Luminollusk-shaped count-based life gain.
    EffectHandler("gain_life_equal_devotion", _GAIN_LIFE_EQUAL_DEVOTION_RE, _gain_life_equal_devotion),
    # RULE 119's "drain" idiom trailing sentence — "You gain life equal to
    # the life lost this way." (Gray Merchant of Asphodel-shaped).
    EffectHandler("gain_life_lost_this_way", _GAIN_LIFE_LOST_THIS_WAY_RE, _gain_life_lost_this_way),
    EffectHandler(
        "gain_life_sacrificed_toughness", _GAIN_LIFE_SACRIFICED_TOUGHNESS_RE,
        _gain_life_sacrificed_toughness,
    ),
    # "You gain life equal to <its / that creature's> <power / toughness>"
    # (~36 SOLO — Bottle Golems / Angelic Chorus / Weed Strangle [clash] / …).
    # MEC-49: "that creature's <char>" on a *group* trigger — "Whenever a creature dealt damage by ~ this turn
    # dies, you gain life equal to **that creature's toughness**." (Abattoir Ghoul) reads the same firing-event
    # subject as the `its`-pronoun row, so the wordier form is the same builder.
    *_subject_handlers([
        ("gain_life_eq_its_self", "self", _GAIN_LIFE_EQ_ITS_RE, _gain_life_eq_its_self),
        ("gain_life_eq_its_group", "group", _GAIN_LIFE_EQ_ITS_RE, _gain_life_eq_its_group),
        ("gain_life_eq_that_prev", "previous", _GAIN_LIFE_EQ_THAT_RE, _gain_life_eq_that_prev),
        ("gain_life_eq_that_group", "group", _GAIN_LIFE_EQ_THAT_RE, _gain_life_eq_its_group),
    ]),
    # "When ~ dies, [you gain life and] draw cards equal to its power."
    # (Lifeblood Hydra) — the combined row tried first so its "you gain
    # life and " prefix isn't left dangling by the bare draw row.
    EffectHandler(
        "gain_life_and_draw_eq_its_self", _GAIN_LIFE_AND_DRAW_EQ_ITS_RE,
        _gain_life_and_draw_eq_its_self, self_subject_only=True,
    ),
    EffectHandler(
        "draw_eq_its_self", _DRAW_EQ_ITS_RE, _draw_eq_its_self, self_subject_only=True,
    ),
    # PAR-115: "destroy/exile/counter/return/tap `<X>`. its controller
    # `<verb>` …" — the previous clause's own controller, gated on
    # `previous_subject_only` exactly like `gain_life_eq_that_prev` above.
    EffectHandler(
        "its_controller_loses_life_unless_sac_or_discard",
        _ITS_CONTROLLER_LOSES_LIFE_UNLESS_SAC_OR_DISCARD_RE,
        _its_controller_loses_life_unless_sac_or_discard,
        previous_subject_only=True,
    ),
    EffectHandler(
        "its_controller_loses_life", _ITS_CONTROLLER_LOSES_LIFE_RE,
        _its_controller_loses_life, previous_subject_only=True,
    ),
    EffectHandler(
        "its_controller_gains_life", _ITS_CONTROLLER_GAINS_LIFE_RE,
        _its_controller_gains_life, previous_subject_only=True,
    ),
    EffectHandler(
        "its_controller_gains_life_eq_mv", _ITS_CONTROLLER_GAINS_LIFE_EQ_MV_RE,
        _its_controller_gains_life_eq_mv, previous_subject_only=True,
    ),
    EffectHandler(
        "its_controller_draws", _ITS_CONTROLLER_DRAWS_RE,
        _its_controller_draws, previous_subject_only=True,
    ),
    EffectHandler(
        "its_controller_discards", _ITS_CONTROLLER_DISCARDS_RE,
        _its_controller_discards, previous_subject_only=True,
    ),
    EffectHandler(
        "its_controller_mills", _ITS_CONTROLLER_MILLS_RE,
        _its_controller_mills, previous_subject_only=True,
    ),
    EffectHandler(
        "its_controller_mills_eq_power", _ITS_CONTROLLER_MILLS_EQ_POWER_RE,
        _its_controller_mills_eq_power, previous_subject_only=True,
    ),
    # PAR-117: the same four clauses, reusing the same regexes, gated on
    # `group_subject_only` instead — "its" is a RULE 603.1 group-subject
    # trigger's own per-firing object (Poisonbelly Ogre-shaped), not a
    # creature this same body's earlier clause targeted.
    *_its_controller_handlers(),
    # Tried before the plain `lose_life` row below (its own bare
    # `{NUMBER} life` would otherwise stop right after the digit, leaving
    # "for each spell they've cast this turn" unconsumed).
    EffectHandler(
        "lose_life_per_spell_cast_this_turn",
        _LOSE_LIFE_PER_SPELL_CAST_THIS_TURN_RE,
        _lose_life_per_spell_cast_this_turn,
    ),
    # "that player loses N life for each 1 life they gained." (False Cure).
    EffectHandler(
        "lose_life_per_life_gained",
        _LOSE_LIFE_PER_LIFE_GAINED_RE,
        _lose_life_per_life_gained,
    ),
    # "you lose 2 life" / "target player loses 2 life" / "target opponent
    # loses 2 life" / "they lose 2 life" (the group-subject event's own
    # player — see `_lose_life`'s docstring).
    EffectHandler(
        "lose_life",
        _c(r"(?P<who>you |target player |target opponent |they )?loses? (?P<n>\d+|x) life"),
        _lose_life,
    ),
    # RULE 202.2f/700.6 "each opponent loses X life, where X is your
    # devotion to <colour>." (Gray Merchant of Asphodel) — tried before the
    # plain digit-amount row below since "x" never matches its `NUMBER`.
    EffectHandler(
        "lose_life_selector_devotion", _LOSE_LIFE_SELECTOR_DEVOTION_RE, _lose_life_selector_devotion
    ),
    # "Each opponent loses life equal to the number of Vampires you
    # control." (Malakir Bloodwitch) — tried before the plain digit-amount
    # row below.
    EffectHandler(
        "lose_life_selector_subtype", _LOSE_LIFE_SELECTOR_SUBTYPE_RE, _lose_life_selector_subtype
    ),
    # "each opponent loses 2 life" / "each player loses 2 life" (RULE
    # 601.2c mass effect, Deathrite Shaman-shaped).
    EffectHandler(
        "lose_life_selector",
        _c(rf"(?P<selector>each other player|each player|each opponent) loses? {COUNT_X} life"),
        _lose_life_selector,
    ),
    # "whenever you gain life, target opponent loses that much life."
    # (Sanguine Bond/Defiant Bloodlord-shaped) — tried before the plain
    # `lose_life` row above so "that much" wins over that row's literal
    # `NUMBER`.
    EffectHandler(
        "lose_life_from_trigger_amount",
        _c(rf"{TARGET} loses that much life"),
        _lose_life_from_trigger_amount,
    ),
    # "Whenever ~ deals damage, you gain that much life." (El-Hajjâj /
    # Exalted Angel-shaped, PAR-36) — before the plain `gain_life` row so
    # "that much" wins over its literal `NUMBER`.
    EffectHandler(
        "gain_life_from_trigger_amount",
        _c(r"you gain that much life"),
        _gain_life_from_trigger_amount,
    ),
    EffectHandler(
        "gain_life_spell_mv",
        _c(r"gains? life equal to that spell'?s mana value"),
        _gain_life_spell_mv,
    ),
    EffectHandler(
        "lose_life_spell_mv_that_player",
        _c(r"that player loses life equal to that spell'?s mana value"),
        _lose_life_spell_mv_that_player,
    ),
    # "you get half X rad counters, rounded up/down" (Contaminated Drink) —
    # tried before the plain shape below since its own ``n`` group would
    # otherwise never match "half x" anyway (no overlap risk either way).
    EffectHandler(
        "add_player_counters_half_x",
        _c(rf"(?P<who>you |target player |defending player )?gets? half x rad counters?, "
           rf"rounded (?P<round>up|down)"),
        _add_rad_counters_half_x,
    ),
    # "you get two rad counters" / "target player gets four rad counters" /
    # "defending player gets two rad counters" / bare "get two rad
    # counters" (a "you may" prefix already peeled) — RULE 728 player
    # counters.
    EffectHandler(
        "add_player_counters",
        _c(rf"(?P<who>you |target player |target opponent |defending player )?gets? (?P<n>a|an|x|\d+) (?P<kind>rad|poison) counters?"),
        _add_rad_counters,
    ),
    # "each player gets three rad counters" / "each opponent gets a poison
    # counter" (RULE 601.2c mass effect).
    EffectHandler(
        "add_player_counters_selector",
        _c(rf"(?P<selector>each player|each opponent) gets? (?P<n>a|an|x|\d+) (?P<kind>rad|poison) counters?"),
        _add_rad_counters_selector,
    ),
    # "target player loses all rad counters" (Survivor's Med Kit).
    EffectHandler(
        "lose_all_player_counters",
        _c(r"target player loses all rad counters"),
        _lose_all_rad_counters,
    ),
    # "each opponent gets a number of rad counters equal to its power"
    # (Feral Ghoul's dies trigger) — ENG-37: emits a `bind` node, not the
    # retired `dies_grants_rad_counters_equal_power` fused type.
    EffectHandler(
        "rad_counters_equal_dying_power",
        _c(r"each opponent gets a number of rad counters equal to its power"),
        _dies_rad_counters_equal_power,
    ),
    # "destroy target [color] creature/permanent/artifact/enchantment/land"
    # (RULE 105 colour-hoser adjective, Red Elemental Blast-shaped) — tried
    # before the plain `destroy` handler below (see `_DESTROY_COLOR_ADJ_RE`'s
    # docstring for why it's safe to try first).
    EffectHandler(
        "destroy_color_adj",
        _DESTROY_COLOR_ADJ_RE,
        _destroy_color_adj,
    ),
    # "destroy target nonland permanent with mana value 3 or less"
    # (Abrupt Decay-shaped) — tried before the plain `destroy` handler
    # below (see `_destroy_mv`'s docstring for why it's safe to try first).
    EffectHandler(
        "destroy_mv",
        _c(rf"destroy {TARGET} with mana value (?P<mv>\d+) or (?P<cmp>less|greater)"),
        _destroy_mv,
    ),
    # "exile target permanent with mana value 4 or greater" — the exile sibling of `destroy_mv`.
    EffectHandler(
        "exile_mv",
        _c(rf"exile {TARGET} with mana value (?P<mv>\d+) or (?P<cmp>less|greater)"),
        _exile_mv,
    ),
    # "destroy target creature with power 4 or greater" / "…with flying"
    # (RULE 115/601.2c power/toughness/keyword quality filter) — tried
    # before the plain `destroy` handler below for the same reason as
    # `destroy_mv` (a strict superset of the bare "target creature" shape).
    EffectHandler(
        "destroy_creature_filter",
        _c(rf"destroy target creature{_CREATURE_FILTER_SCOPED}"),
        _destroy_creature_filter,
    ),
    EffectHandler(
        "artifact_enchantment_or_creature_filter",
        _ARTIFACT_ENCHANTMENT_OR_CREATURE_FILTER_RE,
        _artifact_enchantment_or_creature_filter,
    ),
    # "destroy target nonblack creature[. It can't be regenerated.]"
    # (Doom Blade-shaped) — tried before the plain `destroy` handler for
    # the same "strict superset" reason as `destroy_mv`/
    # `destroy_creature_filter` just above.
    EffectHandler(
        "destroy_non_creature",
        _DESTROY_NON_CREATURE_RE,
        _destroy_non_creature,
    ),
    # "destroy target creature" / "destroy target artifact" / "destroy
    # target permanent if it's blue" (the trailing-clause old-templating
    # colour variant, Pyroblast-shaped — see `IF_COLOR_SUFFIX`).
    EffectHandler(
        "destroy",
        _c(rf"destroy {TARGET}" + IF_COLOR_SUFFIX),
        _destroy,
    ),
    # "destroy target Equipment attached to it" (Shackles of Treachery's
    # granted quoted trigger — "it" is the ability's own source).
    EffectHandler(
        "destroy_equipment_attached_to_it",
        _DESTROY_EQUIPMENT_ATTACHED_TO_IT_RE,
        _destroy_equipment_attached_to_it,
    ),
    EffectHandler(
        "destroy_equipment",
        _DESTROY_EQUIPMENT_RE,
        _destroy_equipment,
    ),
    # "destroy two target creatures" / "destroy up to two target artifacts
    # and/or enchantments" (RULE 115.1a generalized to N>=2 — Curtains'
    # Call/Force of Vigor-shaped), optionally "… controlled by different
    # players" (Cloud's Limit Break-adjacent cross-target constraint —
    # `_MULTI_TARGET_DISTINCT_CONTROLLERS`).
    EffectHandler(
        "destroy_multi_target",
        _c(
            rf"destroy {_MULTI_TARGET_QUANTIFIER_X}(?P<target>{_MULTI_TARGET_ALT})"
            rf"{_MULTI_TARGET_DISTINCT_CONTROLLERS}"
        ),
        _destroy_multi_target,
    ),
    # "destroy all creatures. they can't be regenerated." (Wrath of God-
    # shaped) — tried before the plain `destroy_all` below since it's a
    # strict superset (see `_DESTROY_ALL_NO_REGEN_RE`'s docstring).
    EffectHandler(
        "destroy_all_no_regen",
        _DESTROY_ALL_NO_REGEN_RE,
        _destroy_all_no_regen,
    ),
    # "destroy all other creatures[ you control]" / "…creatures other than
    # ~" — the self-excluding wipe, before the plain `destroy_all` (whose
    # ``all creatures`` noun row would otherwise consume the prefix and
    # then fail the fullmatch on the trailing "other than ~").
    EffectHandler(
        "destroy_all_other",
        _DESTROY_ALL_OTHER_RE,
        _destroy_all_other,
    ),
    # "destroy all creatures[.]" / "destroy all artifacts with mana value 3
    # or less." (RULE 601.2c untargeted mass board wipe — Damnation/Citywide
    # Bust-shaped; Wrath of God itself is hand-authored in
    # `card_catalogue`, this is the general oracle-text form).
    EffectHandler(
        "destroy_all",
        _DESTROY_ALL_RE,
        _destroy_all,
    ),
    # "Regenerate another target Elf." (Ezuri, Renegade Leader/Mad Auntie/
    # Baron Sengir-shaped) — tried before the plain `regenerate` row below
    # since it's a strict superset of that shape.
    EffectHandler(
        "regenerate_another_target",
        _REGENERATE_ANOTHER_TARGET_RE,
        _regenerate_another_target,
    ),
    # "Regenerate target Sliver." (Crypt Sliver / Poultice Sliver) — the
    # same subtype-filtered target primitive as the "another target" form.
    EffectHandler(
        "regenerate_target_subtype",
        _REGENERATE_TARGET_SUBTYPE_RE,
        _regenerate_target_subtype,
    ),
    # "regenerate enchanted/equipped creature" — an Aura/Equipment's own
    # activated ability on its host (RULE 303), tried before the plain
    # `regenerate` row (whose `TARGET` grammar has no "enchanted creature"
    # entry anyway, so no overlap — ordered here for locality).
    EffectHandler(
        "regenerate_attached",
        _REGENERATE_ATTACHED_RE,
        _regenerate_attached,
    ),
    # "regenerate target creature" (RULE 701.16).
    EffectHandler(
        "regenerate",
        _c(rf"regenerate {TARGET}"),
        _regenerate,
    ),
    # "regenerate ~" / "regenerate it" / "regenerate this creature" — the
    # *self* form (Broodhatch Nantuko/Thorn Elemental-shaped "{cost}:
    # Regenerate ~."), mirroring `tap_self`'s no-RULE-115-target shape.
    EffectHandler(
        "regenerate_self",
        _c(rf"regenerate {_SELF_SUBJECT}"),
        _regenerate_self,
    ),
    # "counter target spell" / "counter target noncreature spell" / "counter
    # target instant or sorcery spell" / "counter target spell with mana
    # value N" / "counter target creature or battle spell" / "counter target
    # blue spell" (RULE 105 colour-hoser adjective, inline via
    # `SPELL_TARGET`'s own ``color`` group) / any of those "… unless its
    # controller pays {N}" (the "Mana Leak" unless-pay template) — with an
    # optional reflexive "… If they do, `<effect>`." on the pay branch
    # (Assimilate Essence) — and/or "… if it's blue" (the trailing-clause
    # old-templating colour variant, Red Elemental Blast/Pyroblast-shaped).
    EffectHandler(
        "counter",
        _c(
            rf"counter {SPELL_TARGET}"
            + r"(?: unless (?:its controller pays|they pay) (?P<cost>\{[^}]+\}|twice \{x\})"
            + r"(?P<party_tax> plus an additional \{1\} for each creature in your party)?"
            + r"(?P<graveyard_tax> for each card in your graveyard)?)?"
            + r"(?:\. if they do, (?P<reflexive>.+?))?\.?"
            + IF_COLOR_SUFFIX
        ),
        _counter,
    ),
    # "counter target spell, activated ability, or triggered ability." (Disallow, Voidslime, Deny the Witch) —
    # `TargetSpec` kind ``spell_or_ability`` (Deflecting Swat's union of the stack's spells and abilities).
    EffectHandler(
        "counter_spell_or_ability",
        _c(r"counter target spell, activated ability, or triggered ability"),
        lambda m: [EffectSpec("counter", {"target_kind": "spell_or_ability"})],
    ),
    # "counter target instant spell, sorcery spell, activated ability, or triggered ability." (Sister of Silence) — the
    # same union with the spell half narrowed to the two card types.
    EffectHandler(
        "counter_typed_spell_or_ability",
        _c(r"counter target instant spell, sorcery spell, activated ability, or triggered ability"),
        lambda m: [EffectSpec("counter", {"target_kind": "spell_or_ability", "card_types": ["instant", "sorcery"]})],
    ),
    # "this spell can't be countered." / "~ can't be countered." (RULE
    # 118-area) — a spell's own property, docked as a marker the counter
    # effect refuses to act on (`RulesEngine._is_cant_be_countered`).
    EffectHandler(
        "cant_be_countered",
        CANT_BE_COUNTERED_RE,
        _cant_be_countered,
    ),
    EffectHandler(
        "grant_quoted_ability_until_eot",
        _GRANT_QUOTED_ABILITY_UNTIL_EOT_RE,
        _grant_quoted_ability_until_eot,
    ),
    # RULE 119.3: "Your opponents can't gain life this turn." (Roiling
    # Vortex's activated-ability rider).
    EffectHandler(
        "cant_gain_life",
        _CANT_GAIN_LIFE_RE,
        _cant_gain_life,
    ),
    # "Change the target of target spell with a single target." (Deflection/
    # Shunt/Swerve-shaped) / "…target spell or ability with a single
    # target." (Bolt Bend/Redirect Lightning/Untimely Malfunction/
    # Willbender-shaped) — RULE 115.4/601.2c, the oracle-text front-end for
    # `ChangeTargetEffect`, previously only reachable by hand-authoring
    # (Misdirection/Deflecting Swat, `card_catalogue`) since no
    # generic handler had claimed the phrase.
    EffectHandler(
        "change_target",
        _c(r"change the target of target (?P<kind>spell or ability|spell) with a single target"),
        _change_target,
    ),
    # "mill 3 cards" / "you mill 3 cards" / "target player mills a card"
    EffectHandler(
        "mill",
        _c(r"(?:(?P<who>you|target player|target opponent) )?mills? (?P<n>\d+|a|twice x) cards?"),
        _mill,
    ),
    EffectHandler("mill_half", _MILL_HALF_RE, _mill_half),
    EffectHandler("mill_half_defending", _MILL_HALF_DEFENDING_RE, _mill_half_defending),
    EffectHandler("mill_spell_mv", _MILL_SPELL_MV_RE, _mill_spell_mv),
    EffectHandler("mill_source_pt", _MILL_SOURCE_PT_RE, _mill_source_pt),
    # "exile target creature with power 4 or greater" / "…with flying" —
    # tried before the plain `exile` handler below, same reasoning as
    # `destroy_creature_filter`.
    EffectHandler(
        "exile_creature_filter",
        _c(rf"exile target creature{_CREATURE_FILTER_SCOPED}"),
        _exile_creature_filter,
    ),
    # "exile target creature" / "exile target artifact"
    # "exile target <c1> or <c2> creature/permanent[ you don't control]"
    # (Celestial Purge) — `TargetSpec.colors` OR narrowing; a dedicated
    # row since the shared `TARGET` macro carries no colour slot. Tried
    # before the plain `exile` row (which its "<c> or <c>" prefix would
    # otherwise leave unclaimed).
    EffectHandler(
        "exile_target_two_color",
        _EXILE_TARGET_TWO_COLOR_RE,
        _exile_target_two_color,
    ),
    EffectHandler(
        "exile",
        _c(rf"exile {TARGET}"),
        _exile,
    ),
    EffectHandler("exile_self_and_target", _EXILE_SELF_AND_TARGET_RE, _exile_self_and_target),
    # "exile another target creature/nonland permanent" (Faceless Butcher / old two-sentence O-Ring ETB) is
    # the plain `exile` row above: `TARGET` carries the "another" prefix itself (PAR-128), so a dedicated row
    # is a strict subset (PAR-121 audit) and was deleted.
    # "return the exiled card[s] to the battlefield under its/their owner's
    # control." — old two-sentence O-Ring's own LEAVES_BATTLEFIELD line
    # (Journey to Nowhere, Petravark, Faceless Butcher …).
    EffectHandler(
        "return_exiled_card",
        _RETURN_EXILED_CARD_RE,
        _return_exiled_card,
    ),
    # Driftgloom Coyote: "if that creature had power N or less, put a +1/+1
    # counter on ~." — an O-Ring exile clause's own conditional after-tail.
    EffectHandler(
        "if_prev_power_self_counter",
        _IF_PREV_POWER_SELF_COUNTER_RE,
        _if_prev_power_self_counter,
        previous_subject_only=True,
    ),
    # "exile two target creatures" / "exile up to two target artifacts" /
    # "exile any number of target spells" (Mindbreak Trap — the one row
    # `_MULTI_TARGET_ALT_WITH_SPELL` adds on top of the shared alternation)
    # (RULE 115.1a generalized to N>=2), optionally "… controlled by
    # different players" (Protector of the Wastes-shaped cross-target
    # constraint — `_MULTI_TARGET_DISTINCT_CONTROLLERS`).
    EffectHandler(
        "exile_multi_target",
        _c(
            rf"exile {_MULTI_TARGET_QUANTIFIER_X}(?P<target>{_MULTI_TARGET_ALT_WITH_SPELL})"
            rf"{_MULTI_TARGET_DISTINCT_CONTROLLERS}"
        ),
        _exile_multi_target,
    ),
    # "exile all creatures[.]" / "exile all lands." (RULE 601.2c untargeted
    # mass form, Farewell-shaped) — the `exile` sibling of `destroy_all`.
    EffectHandler(
        "exile_all",
        _EXILE_ALL_RE,
        _exile_all,
    ),
    # PAR-128: "destroy all white permanents" / "exile all artifacts and enchantments your
    # opponents control" — after `destroy_all`/`exile_all`, whose named selectors keep winning.
    EffectHandler("mass_group", _MASS_GROUP_RE, _mass_group),
    # "sacrifice/destroy/tap/exile ~ unless you pay <cost>" — one row over the
    # verb (PAR-121), registered *before* the plain `tap_self`/`exile_self`/
    # `sacrifice_self` handlers (whose regexes are a prefix of this one) so the
    # "unless you pay" half isn't silently dropped.
    EffectHandler(
        "self_unless_pay",
        _SELF_UNLESS_PAY_RE,
        _self_unless_pay,
    ),
    # "exile ~" / "exile this card" — the self form (Teferi's Protection/
    # Mnemonic Betrayal's trailing self-exile).
    EffectHandler(
        "exile_self",
        _c(rf"exile {_SELF_SUBJECT}"),
        _exile_self,
    ),
    EffectHandler(
        "each_creature_sacrifices_unless",
        _EACH_CREATURE_SACRIFICES_UNLESS_RE,
        _each_creature_sacrifices_unless,
    ),
    EffectHandler(
        "sacrifice_unless_attacked",
        _SACRIFICE_UNLESS_ATTACKED_RE,
        lambda m: [EffectSpec("sacrifice_unless_attacked", {})],
    ),
    # "sacrifice ~" / "sacrifice this enchantment" — the self form (Dress
    # Down/Underworld Breach's standing end-step self-sac).
    EffectHandler(
        "sacrifice_self",
        _c(rf"sacrifice {_SELF_SUBJECT}"),
        _sacrifice_self,
    ),
    # "tap target <c1> or <c2> creature[ an opponent controls]" (Tidebinder
    # Mage) — colour-list tap; tried before the plain `tap` row (its
    # "<c> or <c>" prefix isn't a TARGET row).
    EffectHandler(
        "tap_two_color",
        _TAP_TWO_COLOR_RE,
        _tap_two_color,
    ),
    # "you may tap or untap target permanent/creature" (Derevi, Empyrial
    # Tactician; Ghostly Touch's quoted attached-creature grant; Teller of
    # Tales' "creature"-scoped sibling, PAR-74). This is one target chosen
    # under RULE 115, followed by the resolution-time tap/untap choice
    # represented by TapEffect.choose_tap_or_untap -- not two independently
    # optional effects.
    EffectHandler(
        "tap_or_untap",
        _c(r"(?:you may )?tap or untap target (?P<kind>permanent|creature)"),
        lambda m: [EffectSpec("tap", {
            "target_kind": m.group("kind"),
            "choose_tap_or_untap": True,
        })],
    ),
    # "…then put a stun counter on each of those creatures." after a mass selector.
    EffectHandler(
        "add_counters_previous_selector",
        _ADD_COUNTERS_PREVIOUS_GROUP_RE,
        _add_counters_previous_selector,
        previous_selector_only=True,
    ),
    # "Put a stun counter on each of them." after a multi-target clause.
    EffectHandler(
        "add_counters_previous_group",
        _ADD_COUNTERS_PREVIOUS_GROUP_RE,
        _add_counters_previous_group,
        previous_subject_only=True,
    ),
    # "tap [up to one] target creature[ an opponent controls] and put a stun
    # counter on it." (Champions of the Shoal, Alchemax Slayer-Bots,
    # Constrictor Sage &c. — PAR-30, a ~30-card SOLO cluster). One clause,
    # two effects: the tap, then a stun counter on the same creature
    # (`AddCountersEffect.previous_subject`). RULE 122.1c's skip-untap
    # replacement is enforced engine-side in `RulesEngine.set_tapped`.
    # Above the plain `tap` row so the trailing "and put a stun counter…"
    # isn't dropped.
    EffectHandler(
        "tap_and_stun",
        _c(
            r"(?P<verb>tap) (?:up to (?:one|1) )?target creature"
            r"(?P<yc> an opponent controls| you don't control)? "
            r"and put a stun counter on it"
        ),
        lambda m: [
            EffectSpec("tap", {
                "target_kind": (
                    "creature_you_dont_control" if m.group("yc") else "creature"
                ),
                "optional": bool(re.search(r"up to (?:one|1)", m.group(0))),
            }),
            EffectSpec("add_counters", {
                "kind": "stun", "amount": 1, "previous_subject": True,
            }),
        ],
    ),
    EffectHandler(
        "exile_trigger_referent",
        _EXILE_TRIGGER_REFERENT_RE,
        _exile_trigger_referent,
        self_subject_only=True,
    ),
    # "tap target creature" / "untap target permanent"
    EffectHandler(
        "tap",
        _c(rf"(?P<verb>tap|untap) {TARGET}"),
        _tap,
    ),
    # "tap two target creatures" / "untap up to two target lands" (RULE
    # 115.1a generalized to N>=2, Snap-shaped).
    EffectHandler(
        "tap_multi_target",
        _c(rf"(?P<verb>tap|untap) {_MULTI_TARGET_QUANTIFIER_X}(?:other )?(?P<target>{_MULTI_TARGET_ALT})"),
        _tap_multi_target,
    ),
    # "tap 1 or 2 target creatures without horsemanship." (MEC-87, Broken
    # Dam-shaped).
    EffectHandler(
        "tap_multi_target_keyword_filter",
        _TAP_MULTI_TARGET_KEYWORD_FILTER_RE,
        _tap_multi_target_keyword_filter,
    ),
    # "untap all creatures you control" (Village Bell-Ringer) / "untap all
    # other creatures you control" (Ahn-Crop Champion/Combat Celebrant's
    # own exert rider) / "untap each other creature you control" (Copperhorn
    # Scout) — must sit above `tap_self`/the bare `_SELF_SUBJECT` row so
    # "all [other] creatures you control" (not a self-reference) is
    # recognised on its own.
    EffectHandler(
        "tap_selector",
        _c(
            r"(?P<verb>tap|untap) (?:all (?P<other_all>other )?creatures you control"
            r"|each (?P<other_each>other) creature you control)"
        ),
        _tap_selector,
    ),
    # "untap all Forests you control" (Woodland Guidance — RULE 205.3i land
    # subtype), the land sibling of `tap_selector`. `continuous.group_
    # selector_objects`' `lands_you_control_of_type_<x>` branch does the work.
    EffectHandler(
        "tap_lands_of_type",
        _c(r"(?P<verb>tap|untap) all (?P<sub>forests|mountains|islands|swamps|plains) you control"),
        lambda m: [EffectSpec("tap", {
            "selector": "lands_you_control_of_type_" + {
                "forests": "forest", "mountains": "mountain", "islands": "island",
                "swamps": "swamp", "plains": "plains",
            }[m.group("sub").lower()],
            "untap": m.group("verb").lower() == "untap",
        })],
    ),
    # "Untap all lands you control." (Bear Umbra) — the unqualified sibling
    # of the basic-land subtype row above.  It is a non-targeting selector,
    # so it also works when the ability was quoted and regranted to an Aura's
    # enchanted creature.
    EffectHandler(
        "tap_lands_you_control",
        _c(r"(?P<verb>tap|untap) all lands you control"),
        lambda m: [EffectSpec("tap", {
            "selector": "lands_you_control",
            "untap": m.group("verb").lower() == "untap",
        })],
    ),
    # "Untap all white creatures you control." (Battle Cry, PAR-124) — the
    # colour-scoped sibling of `tap_selector`, mirroring `tap_lands_of_type`'s
    # own "all `<qualifier>` you control" shape; `_ANIMATE_COLOR_WORDS`
    # (already built for the animate-target family) supplies the WUBRG letter.
    EffectHandler(
        "tap_creatures_of_color",
        _c(rf"(?P<verb>tap|untap) all (?P<color>white|blue|black|red|green) creatures you control"),
        lambda m: [EffectSpec("tap", {
            "selector": "creatures_you_control_of_color_" + _ANIMATE_COLOR_WORDS[m.group("color").lower()],
            "untap": m.group("verb").lower() == "untap",
        })],
    ),
    # "untap all attacking creatures" / "untap each attacking creature"
    # (Karlach, Fury of Avernus/Hexplate Wallbreaker) — tried above `tap_self`
    # too, same "specific mass phrase before the bare pronoun row" ordering.
    EffectHandler(
        "tap_attacking_creatures",
        _c(r"(?P<verb>tap|untap) (?:all attacking creatures|each attacking creature)"),
        _tap_attacking_creatures,
    ),
    EffectHandler("tap_all_player_group", _TAP_ALL_PLAYER_GROUP_RE, _tap_all_player_group),
    # "tap all creatures your opponents control" / "tap all nonwhite creatures" /
    # "tap all artifacts" (Bond of Discipline, Blinding Light, Metal Fatigue —
    # PAR-128) — the general mass form: the group is whatever the shared noun-
    # phrase grammar reads (`parse_count_phrase`), carried as a structured
    # selector `TapEffect` resolves through `group_selector_objects`. After the
    # dedicated rows above so their named selectors keep winning.
    EffectHandler(
        "tap_all_group",
        _c(r"(?P<verb>tap|untap) all (?P<group>[a-z' -]+?)"),
        _tap_all_group,
    ),
    # "Untap it and all Samurai you control." (Godo, Bandit Warlord) — tried
    # before `tap_self` since that row's bare `_SELF_SUBJECT` would consume
    # only "it" and leave "and all Samurai you control" unclaimed.
    EffectHandler("tap_self_and_subtype", _TAP_SELF_AND_SUBTYPE_RE, _tap_self_and_subtype),
    # "untap this creature" / "untap ~" / "tap it" — the self form (Devoted
    # Druid's "Put a -1/-1 counter on this creature: Untap this creature.").
    EffectHandler(
        "tap_self",
        _c(rf"(?P<verb>tap|untap) {_SELF_SUBJECT}"),
        _tap_self,
    ),
    # "untap that creature" (Finest Hour, MEC-28) — only offered from a
    # group-subject trigger body, where "that creature" unambiguously means
    # whichever creature matched the trigger.
    EffectHandler(
        "tap_group_subject",
        _TAP_GROUP_SUBJECT_RE,
        _tap_self,
        group_subject_only=True,
    ),
    # "tap enchanted creature" / "untap enchanted creature" (Freed from the
    # Real/Pemmin's Aura-shaped Aura activated abilities).
    EffectHandler(
        "tap_attached",
        _c(rf"(?P<verb>tap|untap) {_ATTACHED_SUBJECT}"),
        _tap_attached,
    ),
    # "Exile enchanted creature." (Spiral into Solitude — an Aura's own
    # `{cost}, Blight N, Sacrifice ~:` removal body). `ExileEffect`'s
    # ``attached_permanent`` self-acting mode, no RULE 115 target.
    EffectHandler(
        "exile_attached",
        _c(rf"exile {_ATTACHED_SUBJECT}"),
        lambda m: [EffectSpec("exile", {"target_kind": "attached_permanent"})],
    ),
    # "Return ~ to its owner's hand." (RULE 701.3, self form) — before the
    # targeted sibling below, whose `TARGET` grammar has no ``~``
    # alternative to compete with but would otherwise have first claim on
    # the surrounding phrase.
    EffectHandler(
        # "return **this card** to its owner's hand" (Ringskipper — a
        # "when ~ dies" clash-win body, so the source is in the graveyard;
        # `RulesEngine.return_to_hand` moves it from whatever zone it's in).
        # Scoped here rather than widening the shared `_SELF_SUBJECT` macro.
        "return_self_to_hand",
        _c(rf"return (?:{_SELF_SUBJECT}|this card) to its owner's hand"),
        _return_self_to_hand,
    ),
    # "return ~ and target <c1> or <c2> creature[ you control] to their
    # owner's hand" (Snow Hound) — compound self+target bounce; before the
    # colour-list and plain rows (its "return ~ and target …" would else be
    # left unclaimed).
    EffectHandler(
        "return_self_and_two_color",
        _RETURN_SELF_AND_TWO_COLOR_RE,
        _return_self_and_two_color,
    ),
    # "return target <c1> or <c2> creature[ you control] to its owner's
    # hand" (Escape Routes) — colour-list bounce; tried before the plain
    # `return_to_hand` row (its "<c> or <c>" prefix isn't a TARGET row).
    EffectHandler(
        "return_to_hand_two_color",
        _RETURN_TO_HAND_TWO_COLOR_RE,
        _return_to_hand_two_color,
    ),
    # "return target creature to its owner's hand" / "return a land you
    # control to its owner's hand" (RULE 701.3 — the bounce family).
    EffectHandler(
        "return_to_hand",
        _c(rf"return {TARGET} to its owner's hand"),
        _return_to_hand,
    ),
    # "put target <c1> or <c2> creature on top of its owner's library"
    # (Hunting Drake) — colour-list tempo bounce.
    EffectHandler(
        "return_to_library_two_color",
        _RETURN_TO_LIBRARY_TWO_COLOR_RE,
        _return_to_library_two_color,
    ),
    # "put target creature on top/the bottom of its owner's library" (RULE
    # 701.3 — Time Ebb/Griptide-shaped tempo bounce).
    EffectHandler(
        "return_to_library",
        _c(rf"put {TARGET} {_LIBRARY_PLACEMENT}"),
        _return_to_library,
    ),
    # "put ~ / it … on the bottom of / third from the top of its owner's library" (self form).
    EffectHandler("return_self_to_library", _RETURN_SELF_TO_LIBRARY_RE, _return_self_to_library),
    EffectHandler("return_attached_to_library", _RETURN_ATTACHED_TO_LIBRARY_RE, _return_attached_to_library),
    EffectHandler("exile_all_until_leaves", _EXILE_ALL_UNTIL_LEAVES_RE, _exile_all_until_leaves),
    EffectHandler(
        "return_it_to_library", _RETURN_IT_TO_LIBRARY_RE, _return_self_to_library, self_subject_only=True,
    ),
    # "Put target card from a graveyard on the bottom of its owner's
    # library." (PAR-83 — Junktroller/Chrome Companion).  Its target is a
    # card in any graveyard, not the battlefield target the generic tempo-
    # bounce row directly above accepts.
    EffectHandler(
        "graveyard_card_to_library_bottom",
        _GRAVEYARD_CARD_TO_LIBRARY_BOTTOM_RE,
        _graveyard_card_to_library_bottom,
    ),
    # "return all nonland permanents with mana value X or less to their
    # owners' hands." (Displacement Wave).
    EffectHandler(
        "return_all_nonland",
        _RETURN_ALL_NONLAND_RE,
        _return_all_nonland,
    ),
    # PAR-128: "return all creatures to their owners' hands" — after `return_all_nonland`.
    EffectHandler("return_group", _RETURN_GROUP_RE, _return_group),
    EffectHandler("put_group_on_bottom", _PUT_GROUP_ON_BOTTOM_RE, _put_group_on_bottom),
    # "return two target creatures to their owners' hands" (RULE 115.1a
    # generalized to N>=2) — the plural sibling of `return_to_hand`.
    EffectHandler(
        "return_to_hand_multi_target",
        _c(rf"return {_MULTI_TARGET_QUANTIFIER_X}(?:other )?(?P<target>{_MULTI_TARGET_ALT}) to their owners'? hands?"),
        _return_to_hand_multi_target,
    ),
    # "Return those creatures to their owners' hands." (PAR-1, Run Away
    # Together) — the indirect-referent sibling of `return_to_hand_multi_
    # target`; only offered when a preceding "choose N target creatures …"
    # clause actually announced the group (`EffectHandler.
    # previous_subject_only`, `_choose_targets_group`).
    EffectHandler(
        "return_previous_group", _RETURN_PREVIOUS_GROUP_RE, _return_previous_group,
        previous_subject_only=True,
    ),
    # "return target <c1> or <c2> creature card from [scope] graveyard to
    # [dest]" (Crypt Angel) — colour-list graveyard recursion; tried
    # before the plain row (its "<c> or <c>" prefix isn't a TARGET row).
    EffectHandler(
        "return_from_graveyard_two_color",
        _RETURN_FROM_GRAVEYARD_TWO_COLOR_RE,
        _return_from_graveyard_two_color,
    ),
    # "return target [type] card from [scope] graveyard to the
    # battlefield/your hand/its owner's hand" / "put target [type] card
    # from [scope] graveyard onto the battlefield under its owner's
    # control" (RULE 701.3, the Regrowth/Reanimate/Deathrite-adjacent
    # recursion family — own/any/opponent graveyard scope).
    EffectHandler(
        "return_from_graveyard",
        _RETURN_FROM_GRAVEYARD_RE,
        _return_from_graveyard,
    ),
    # Living Death family — "each player returns / you return all creature
    # cards from [their/your] graveyard to the battlefield / hand" — a
    # mass, untargeted recursion (`ReturnFromGraveyardEffect.players`).
    EffectHandler(
        "mass_return_graveyard",
        _MASS_RETURN_GRAVEYARD_RE,
        _mass_return_graveyard,
    ),
    EffectHandler(
        "return_pick_from_graveyard",
        _RETURN_PICK_FROM_GRAVEYARD_RE,
        _return_pick_from_graveyard,
    ),
    EffectHandler(
        "return_from_graveyard_owner_control",
        _PUT_FROM_GRAVEYARD_OWNER_CONTROL_RE,
        _return_from_graveyard,
    ),
    # "return up to two target creature cards from your graveyard to your
    # hand"/"...to the battlefield" (RULE 115.1a generalized to N>=2) — the
    # plural sibling of `return_from_graveyard`.
    # "return [up to] X target creature cards from your graveyard to your
    # hand / the battlefield" — the count is the spell's announced {X}
    # (`count_selector="source_x_paid"`). Tried before the numeric-N
    # plural handler (its `\d+` count can't match the "x" token anyway).
    EffectHandler(
        "return_from_graveyard_x",
        _RETURN_FROM_GRAVEYARD_X_RE,
        _return_from_graveyard_x,
    ),
    EffectHandler(
        "return_from_graveyard_multi_target",
        _RETURN_FROM_GRAVEYARD_MULTI_RE,
        _return_from_graveyard_multi_target,
    ),
    # "put target [type] card from [scope] graveyard onto the battlefield
    # under your control" (Reanimate/Rise from the Grave/Virtue of
    # Persistence) — a genuinely different effect from the two above: the
    # activating player takes control, not the card's owner.
    EffectHandler(
        "reanimate_under_your_control",
        _REANIMATE_UNDER_YOUR_CONTROL_RE,
        _reanimate_under_your_control,
    ),
    # "put 1, 2, or 3 target creature cards from graveyards onto the
    # battlefield under your control. each of them enters with an
    # additional -1/-1 counter on it." (Aberrant Return) — enumerated
    # RULE 601.2c range + whole-body enters-with rider.
    EffectHandler(
        "reanimate_multi_under_your_control",
        _REANIMATE_MULTI_UNDER_YOUR_CONTROL_RE,
        _reanimate_multi_under_your_control,
    ),
    # PAR-15's "any number of" graveyard-recursion siblings — new
    # destinations (library top / shuffle into library) rather than a new
    # targeting primitive.
    EffectHandler(
        "return_from_graveyard_top_any",
        _RETURN_FROM_GRAVEYARD_TOP_ANY_RE,
        _return_from_graveyard_top_any,
    ),
    EffectHandler(
        "return_from_graveyard_shuffle_any",
        _RETURN_FROM_GRAVEYARD_SHUFFLE_ANY_RE,
        _return_from_graveyard_shuffle_any,
    ),
    EffectHandler(
        "shuffle_target_graveyard_cards",
        _SHUFFLE_TARGET_GRAVEYARD_CARDS_RE,
        _shuffle_target_graveyard_cards,
    ),
    # "exile target [type] card from [scope] graveyard" (RULE 701.5a,
    # Deathrite Shaman/Scavenging Ooze/Lion Sash-shaped graveyard hate).
    EffectHandler(
        "exile_from_graveyard",
        _EXILE_FROM_GRAVEYARD_RE,
        _exile_from_graveyard,
    ),
    EffectHandler(
        "exile_graveyard_cards_multi",
        _EXILE_GRAVEYARD_CARDS_MULTI_RE,
        _exile_graveyard_cards_multi,
    ),
    EffectHandler(
        "exile_own_graveyard_cards",
        _EXILE_OWN_GRAVEYARD_CARDS_RE,
        _exile_own_graveyard_cards,
    ),
    # "exile target player's graveyard."/"exile all cards from target
    # player's graveyard." (Bojuka Bog/Tormod's Crypt-shaped whole-graveyard
    # hate, as opposed to a single card from one above).
    EffectHandler(
        "exile_target_graveyard",
        _EXILE_TARGET_GRAVEYARD_RE,
        _exile_target_graveyard,
    ),
    # "Its controller may search their library for a basic land card, put
    # it onto the battlefield, then shuffle." (Assassin's Trophy/
    # Geomancer's Gambit/Ghost Quarter — the destroyed permanent's
    # controller, not the caster, gets the ramp).
    EffectHandler(
        "destroy_controller_search_basic_land",
        _DESTROY_CONTROLLER_SEARCH_BASIC_LAND_RE,
        _destroy_controller_search_basic_land,
    ),
    # "search your library for <criteria>, [reveal <pronoun>,] put <pronoun>
    # <destination>, then shuffle." (RULE 701.19 — the general tutor/ramp/
    # fetch family: unrestricted tutors, basic-land fetches, criteria-
    # filtered tutors, "reveal" variants).
    # "search your library for <criteria> that share a land type, ... then
    # shuffle." (Myriad Landscape-shaped cross-pick constraint) — tried
    # before the plain row below since it's a strict superset of it.
    EffectHandler(
        "search_put_then_shuffle_share_type",
        _SEARCH_PUT_THEN_SHUFFLE_SHARE_TYPE_RE,
        _search_put_then_shuffle_share_type,
    ),
    EffectHandler("elfhame_sanctuary", _ELFHAME_SANCTUARY_RE, _elfhame_sanctuary),
    EffectHandler("search_named_criteria", _SEARCH_NAMED_CRITERIA_RE, _search_named_criteria),
    EffectHandler(
        "search_put_then_shuffle",
        _SEARCH_PUT_THEN_SHUFFLE_RE,
        _search_put_then_shuffle,
    ),
    # "search your library for <criteria>, put it onto the battlefield,
    # attach it to a creature you control, then shuffle." (Stonehewer
    # Giant/Quest for the Holy Relic-shaped combined search-then-attach) —
    # tried before the plain row above since it's a strict superset of it.
    EffectHandler(
        "search_put_attach_then_shuffle",
        _SEARCH_PUT_ATTACH_THEN_SHUFFLE_RE,
        _search_put_attach_then_shuffle,
    ),
    # "search your library for a card with mana value less than or equal to
    # the number of lands you control, ... then shuffle." (Beseech the
    # Queen-shaped board-count mana-value bound).
    EffectHandler(
        "search_mv_lands_qualifier",
        _SEARCH_MV_LANDS_QUALIFIER_RE,
        _search_mv_lands_qualifier,
    ),
    # "search your library for a snow permanent card, a legendary card, or
    # a Saga card, ... then shuffle." (Search for Glory's own three-way OR
    # criteria).
    EffectHandler(
        "search_snow_legendary_saga",
        _SEARCH_SNOW_LEGENDARY_SAGA_RE,
        _search_snow_legendary_saga,
    ),
    # "You gain 1 life for each {S} spent to cast this spell." (Search for
    # Glory's own trailing sentence).
    EffectHandler(
        "gain_life_per_snow_spent",
        _GAIN_LIFE_PER_SNOW_SPENT_RE,
        _gain_life_per_snow_spent,
    ),
    # "search your library for <criteria>, [reveal <pronoun>,] then shuffle
    # and put <pronoun> on top." (the reordered shuffle-then-put-on-top
    # tutors — Vampiric/Mystical/Enlightened/Worldly Tutor).
    EffectHandler(
        "search_shuffle_then_put_top",
        _SEARCH_SHUFFLE_THEN_PUT_TOP_RE,
        _search_shuffle_then_put_top,
    ),
    # "search your library for up to N basic land cards, reveal those cards,
    # put one <destA> and the other <destB>, then shuffle." (Cultivate/
    # Kodama's Reach-shaped split destination).
    EffectHandler(
        "search_split_destination",
        _SEARCH_SPLIT_DESTINATION_RE,
        _search_split_destination,
    ),
    # "search your library for N cards. Put 1 <destA> and the other
    # <destB>. Then shuffle." (Final Parting-shaped three-sentence split
    # destination, no criteria).
    EffectHandler(
        "search_two_cards_split",
        _SEARCH_TWO_CARDS_SPLIT_RE,
        _search_two_cards_split,
    ),
    # "search your library and/or graveyard for <criteria>, [reveal
    # <pronoun>,] put <pronoun> <destination>. If you search[ed] your
    # library this way, shuffle." (the backgrounds/planeswalker-tutor
    # combined-zone family).
    EffectHandler(
        "search_zone_put",
        _SEARCH_ZONE_PUT_RE,
        _search_zone_put,
    ),
    # "search your library [and graveyard] for N cards and exile the rest.
    # Put the chosen cards on top of your library in any order."
    # (Doomsday-shaped).
    EffectHandler(
        "search_exile_rest",
        _SEARCH_EXILE_REST_RE,
        _search_exile_rest,
    ),
    # "Shuffle ~ into its owner's library." (Green Sun's Zenith's own
    # trailing sentence, overriding the spell's default graveyard routing).
    EffectHandler(
        "shuffle_self_into_library",
        _SHUFFLE_SELF_INTO_LIBRARY_RE,
        _shuffle_self_into_library,
    ),
    # ENG-32 (Watery Grasp): "Enchanted creature's owner shuffles it into
    # their library."
    EffectHandler(
        "shuffle_enchanted_into_library",
        _SHUFFLE_ENCHANTED_INTO_LIBRARY_RE,
        _shuffle_enchanted_into_library,
    ),
    # "An opponent gains control of ~." (Wishclaw Talisman's own drawback
    # clause).
    EffectHandler(
        "gain_control_by_opponent",
        _GAIN_CONTROL_BY_OPPONENT_RE,
        _gain_control_by_opponent,
    ),
    # "gain control of target creature [with mana value N or less] until
    # end of turn" (Act of Treason/Claim the Firstborn-shaped threaten
    # effect).
    EffectHandler(
        "gain_control_eot",
        _GAIN_CONTROL_EOT_RE,
        _gain_control_eot,
    ),
    # "gain control of target <permanent> [. untap it]" with no duration —
    # the RULE 611.2 indefinite steal (Keiga, Blatant Thievery; PAR-130).
    EffectHandler(
        "gain_control_permanent",
        _GAIN_CONTROL_PERMANENT_RE,
        _gain_control_permanent,
    ),
    # "Untap all creatures and gain control of them until end of turn. They
    # gain haste until end of turn." (Insurrection's own mass threaten).
    EffectHandler(
        "gain_control_all",
        _GAIN_CONTROL_ALL_RE,
        _gain_control_all,
    ),
    # "For each opponent, gain control of up to 1 target creature that player
    # controls until end of turn. Untap those creatures. They gain haste …"
    # (Mass Mutiny / Molten Primordial) — one requirement per opponent.
    EffectHandler(
        "gain_control_eot_per_opponent",
        _GAIN_CONTROL_EOT_PER_OPPONENT_RE,
        _gain_control_eot_per_opponent,
    ),
    # "Gain control of all <type> [your opponents / target opponent]
    # control[s] until end of turn. Untap them. They gain haste …"
    # (Broadcast Takeover, Call for Aid) — the opponent-scoped mass threaten.
    EffectHandler(
        "gain_control_mass_eot",
        _GAIN_CONTROL_MASS_EOT_RE,
        _gain_control_mass_eot,
    ),
    # "that player copies it and may choose new targets for the copy [until
    # end of turn]" (Bonus Round's own trigger body).
    EffectHandler(
        "trigger_copy_spell",
        _TRIGGER_COPY_SPELL_RE,
        _trigger_copy_spell,
    ),
    EffectHandler(
        "copy_your_instant_or_sorcery",
        _COPY_YOUR_INSTANT_OR_SORCERY_RE,
        _copy_your_instant_or_sorcery,
    ),
    # "Each instant and sorcery card in your graveyard gains flashback until
    # end of turn. The flashback cost is equal to its mana cost." (Past in
    # Flames-shaped).
    EffectHandler(
        "grant_flashback_each",
        _GRANT_FLASHBACK_EACH_RE,
        _grant_flashback_each,
    ),
    # "Target instant or sorcery card in your graveyard gains flashback
    # [<cost>] until end of turn[. The flashback cost is equal to its mana
    # cost.]" (MEC-24, Recoup/Snapcaster Mage-shaped).
    EffectHandler(
        "grant_flashback_target",
        _GRANT_FLASHBACK_TARGET_RE,
        _grant_flashback_target,
    ),
    # "The next [creature] spell you cast this turn can't be countered." (Mistrise Village,
    # Insist, Overmaster) / "Spells you control can't be countered this turn." (Veil of Summer).
    EffectHandler(
        "cant_be_countered_this_turn",
        _UNCOUNTERABLE_THIS_TURN_RE,
        _cant_be_countered_this_turn,
    ),
    # "Look at the top card of target player's library."/"Look at a card at
    # random in target player's hand." (Mishra's/Urza's Bauble).
    EffectHandler(
        "look_at_target",
        _LOOK_AT_TARGET_RE,
        _look_at_target,
    ),
    # "attach it to target creature you control" / "attach ~ to target
    # creature you control" (an Equipment's own ETB self-attach).
    EffectHandler(
        "attach",
        _c(rf"attach (?:it|{re.escape(SELF)}) to {TARGET}"),
        _attach,
    ),
    # PAR-135: a *chosen* Equipment onto a chosen creature, or onto a non-target subject.
    EffectHandler("attach_chosen_to_target", _ATTACH_CHOSEN_TO_TARGET_RE, _attach_chosen_to_target),
    EffectHandler(
        "attach_chosen_to_source", _ATTACH_CHOSEN_TO_SOURCE_RE, _attach_chosen_to_subject("source"),
    ),
    *_subject_handlers([
        ("attach_chosen_to_self_pronoun", "self", _ATTACH_CHOSEN_TO_PRONOUN_RE, _attach_chosen_to_subject("source")),
        ("attach_chosen_to_group_subject", "group", _ATTACH_CHOSEN_TO_THAT_RE,
         _attach_chosen_to_subject("trigger_subject")),
        ("attach_chosen_to_previous", "previous", _ATTACH_CHOSEN_TO_THAT_RE,
         _attach_chosen_to_subject("previous_target")),
        ("attach_chosen_to_attached_host", "attached", _ATTACH_CHOSEN_TO_IT_RE,
         _attach_chosen_to_subject("attached_permanent")),
    ]),
    # RULE 701.14 fight, in its four printed subjects: two chosen creatures
    # ("target creature you control fights target creature you don't
    # control"), the source itself written as ``~`` or as "it", and an Aura's
    # host ("enchanted creature fights …"). The "it" row is
    # `self_subject_only` — see `EffectHandler`.
    # (grammar/builder logic unchanged — only the repetitive EffectHandler(...)
    # calls below were collapsed into one row table, see `_FIGHT_ROW_SPECS`).
    *(
        EffectHandler(name, regex, build, **flags)
        for name, regex, build, flags in _FIGHT_ROW_SPECS
    ),
    EffectHandler(
        "fight_previous_pair", _FIGHT_PREVIOUS_PAIR_RE, _fight_previous_pair,
        previous_subject_only=True,
    ),
    # "Put a +1/+1 counter on target creature. It phases out." (Slip Out
    # the Back) — the same previous-clause pronoun idiom as the fight
    # family just above, for a phase-out instead.
    EffectHandler(
        "phase_out_previous", _PHASE_OUT_PREVIOUS_RE, _phase_out_previous,
        previous_subject_only=True,
    ),
    # PAR-79 sixth increment: "…target creature… **that creature** can't be
    # blocked this turn." (Stealth Mission/Trygon Prime-shaped).
    EffectHandler(
        "cant_be_blocked_turn_previous", _CANT_BE_BLOCKED_TURN_PREVIOUS_RE,
        _cant_be_blocked_turn_previous, previous_subject_only=True,
    ),
    EffectHandler(
        "must_be_blocked_turn_previous", _MUST_BE_BLOCKED_TURN_PREVIOUS_RE,
        _must_be_blocked_turn_previous, previous_subject_only=True,
    ),
    EffectHandler(
        "cant_be_blocked_except_previous", _CANT_BE_BLOCKED_EXCEPT_PREVIOUS_RE,
        _cant_be_blocked_except_previous, previous_subject_only=True,
    ),
    EffectHandler(
        "kw_grant_unblockable_except_x", _KW_GRANT_UNBLOCKABLE_EXCEPT_X_RE,
        _kw_grant_unblockable_except_x,
    ),
    # RULE 702.26 "~ phases out." (Blink Dog/Vaporous Djinn-shaped) / the
    # attached-permanent sibling "enchanted/equipped creature phases out."
    # (Vanishing) / a genuine RULE 115 target (Reality Ripple/Divine Smite,
    # including an opponent-controlled one) — tried in "most specific
    # subject first" order like every other family here.
    EffectHandler("phase_out_self", _PHASE_OUT_SELF_RE, _phase_out_self),
    EffectHandler("phase_out_attached", _PHASE_OUT_ATTACHED_RE, _phase_out_attached),
    EffectHandler("phase_out_target", _PHASE_OUT_TARGET_RE, _phase_out_target),
    # RULE 500.4-adjacent "after this [main] phase, there is an additional
    # combat phase[ followed by an additional main phase]." (Combat
    # Celebrant/Godo/Aurelia-shaped; World at War/Aggravated Assault's own
    # longer form) — tried longer-form-first, same "most specific first"
    # convention as everywhere else in this table.
    EffectHandler(
        "extra_combat_and_main_phase", _EXTRA_COMBAT_AND_MAIN_PHASE_RE, _extra_combat_and_main_phase
    ),
    EffectHandler("extra_combat_phase", _EXTRA_COMBAT_PHASE_RE, _extra_combat_phase),
    # "Choose target creature you control and target creature you don't
    # control." — the target announcement those pair clauses read back.
    EffectHandler("choose_targets", _CHOOSE_TARGETS_RE, _choose_targets),
    # "Choose two target creatures controlled by different players." (PAR-1)
    # — the quantified-group announcement `_return_previous_group` (below)
    # reads back via "those creatures".
    EffectHandler("choose_targets_group", _CHOOSE_TARGETS_GROUP_RE, _choose_targets_group),
    EffectHandler("choose_target_single", _CHOOSE_TARGET_SINGLE_RE, _choose_target_single),
    # RULE 701.10 "exchange control of `<X>` and `<Y>`" (PAR-29) — three
    # printed shapes, longest/most-specific first (the file's usual
    # convention): two fully-named independent targets, then "N target
    # `<kind>`[ controlled by different players]", then this permanent plus
    # one target.
    EffectHandler(
        "exchange_control_spawnbroker",
        _EXCHANGE_CONTROL_SPAWNBROKER_RE,
        _exchange_control_spawnbroker,
    ),
    EffectHandler(
        "exchange_control_two_explicit",
        _c(rf"exchange control of {TARGET} and {_TARGET_B}{_EXCHANGE_XTARGET_TAIL}"),
        _exchange_control_two_explicit,
    ),
    EffectHandler(
        "exchange_control_multi",
        _c(
            rf"exchange control of {_MULTI_TARGET_QUANTIFIER}(?:other )?"
            rf"(?P<target>{_MULTI_TARGET_ALT}){_MULTI_TARGET_DISTINCT_CONTROLLERS}"
            rf"{_EXCHANGE_XTARGET_TAIL}"
        ),
        _exchange_control_multi,
    ),
    EffectHandler(
        "exchange_control_self",
        _c(rf"exchange control of ~ and {TARGET}"),
        _exchange_control_self,
    ),
    # RULE 701.10's life-total half.
    EffectHandler(
        "exchange_life_totals_self",
        _c(r"exchange life totals with (?:target opponent|target player)"),
        _exchange_life_totals_self,
    ),
    EffectHandler(
        "exchange_life_totals_two_target",
        _c(r"(?:have )?2 target players exchange life totals"),
        _exchange_life_totals_two_target,
    ),
    # The one-sided fight (RULE 701.14's shape minus the damage back):
    # "target creature you control deals damage equal to its power to target
    # creature you don't control" and its six implicit-dealer/selector
    # siblings — same subject vocabulary as the fight family above, half the
    # damage (see `_POWER_DAMAGE_ROW_SPECS`'s own note on why only the
    # registration, not the grammar/builders, is factored here too).
    *(
        EffectHandler(name, regex, build, **flags)
        for name, regex, build, flags in _POWER_DAMAGE_ROW_SPECS
    ),
    # "you may pay {E}{E}. If you do, <effect>." (Aether Chaser) — tried
    # before the bare mana/effect handlers since it wraps a whole clause.
    EffectHandler(
        "pay_energy_then",
        _PAY_ENERGY_THEN_RE,
        _pay_energy_then,
    ),
    # MEC-18: "you may <sacrifice/discard/pay-mana/pay-life>. when/if you
    # do, <effect>." — the general RULE 603.5 optional-antecedent family.
    # Tried after `pay_energy_then`/`pay_cost_then_draw` (both narrower,
    # both correct) so first-match-wins never lets this one preempt them.
    EffectHandler(
        "pay_cost_then_general",
        _PAY_COST_THEN_GENERAL_RE,
        _pay_cost_then_general,
    ),
    # MEC-103: "sacrifice up to N / any number of <type>. When you sacrifice
    # one or more this way, <payoff with "that many">."
    EffectHandler(
        "sacrifice_chosen_then",
        _SACRIFICE_CHOSEN_THEN_RE,
        _sacrifice_chosen_then,
    ),
    # MEC-104: Hordewing Skaab's "draw cards equal to the number of opponents dealt damage this
    # way. If you do, discard that many cards."
    EffectHandler(
        "draw_opponents_damaged_discard",
        _DRAW_OPPONENTS_DAMAGED_DISCARD_RE,
        _draw_opponents_damaged_discard,
    ),
    # PAR-29 (Blight batch): the "If you don't, <effect>." else-branch
    # sibling — same clause shape, opposite antecedent, into
    # `pay_cost_then`'s `else_effects`.
    EffectHandler(
        "pay_cost_then_or_else",
        _PAY_COST_THEN_OR_ELSE_RE,
        _pay_cost_then_or_else,
    ),
    # PAR-79 seventh increment: "return another/<N> other <type>[s] you
    # control to its/their owner's/owners' hand" / "tap another/<N> other
    # untapped <type>[s] you control" as ordinary resolve-time effect
    # bodies — feeds `may_effect_then` right below automatically.
    EffectHandler(
        "return_another_you_control",
        _RETURN_ANOTHER_YOU_CONTROL_RE,
        _return_another_you_control,
    ),
    EffectHandler(
        "tap_another_untapped_you_control",
        _TAP_ANOTHER_UNTAPPED_YOU_CONTROL_RE,
        _tap_another_untapped_you_control,
    ),
    # PAR-124: "you may attach it to target creature you control. if you
    # do, <effect>." — tried before the generic `may_effect_then` row
    # below, whose own builder explicitly rejects a targeted antecedent.
    EffectHandler(
        "may_attach_if_you_do",
        _MAY_ATTACH_IF_YOU_DO_RE,
        _may_attach_if_you_do,
    ),
    # MEC-99: "you may choose to have it deal damage equal to its power to
    # <target>. if you do, it assigns no combat damage this turn." (Gaze of
    # Pain) — tried before the generic `may_effect_then` row below for the
    # same reason `may_attach_if_you_do` is: only reachable under a RULE
    # 603.1 group-subject trigger, which that generic row's own recursive
    # `self_subject=True` parse can never unlock.
    EffectHandler(
        "may_have_it_deal_damage_equal_to_power",
        _MAY_HAVE_IT_DEAL_DAMAGE_EQUAL_TO_POWER_RE,
        _may_have_it_deal_damage_equal_to_power,
        group_subject_only=True,
    ),
    EffectHandler(
        "have_that_player_lose_life",
        _HAVE_THAT_PLAYER_LOSE_LIFE_RE,
        _have_that_player_lose_life,
        group_subject_only=True,
    ),
    # PAR-79 sixth increment: "You may <effect>. If you do, <effect2>." with
    # a resolving-effect antecedent rather than a cost — tried after both
    # cost-shaped rows above so a genuine cost antecedent keeps the more
    # faithful `pay_cost_then` handling.
    EffectHandler(
        "may_effect_then",
        _MAY_EFFECT_THEN_RE,
        _may_effect_then,
    ),
    # MEC-19: "counter it unless that player pays <cost>" — the
    # un-keyworded-Ward-shaped `BECOMES_TARGET` trigger's own resolution.
    EffectHandler(
        "counter_unless_pay",
        _COUNTER_UNLESS_PAY_RE,
        _counter_unless_pay,
    ),
    EffectHandler(
        "counter_target_spell_unless_discard_hand",
        _COUNTER_TARGET_SPELL_UNLESS_DISCARD_HAND_RE,
        _counter_target_spell_unless_discard_hand,
    ),
    # "you get {E}{E}" — energy-counter production (RULE 122).
    EffectHandler(
        "get_energy",
        _GET_ENERGY_RE,
        _get_energy,
    ),
    EffectHandler("get_that_many_energy", _GET_THAT_MANY_ENERGY_RE, _get_that_many_energy),
    # "add `<sym>`/1 mana of any color for each `<kind>` counter removed
    # this way" — tried before both rows below since either would otherwise
    # (fail to) match only the leading "add …" fragment.
    EffectHandler(
        "add_mana_per_counter_removed",
        _ADD_MANA_PER_COUNTER_REMOVED_RE,
        _add_mana_per_counter_removed,
    ),
    # "add 1 mana of any color" — a genuine resolve-time colour choice,
    # tried before the fixed-pip pattern below since it has no {…} symbols
    # for that one to (fail to) match anyway.
    EffectHandler(
        "add_mana_any_color",
        _ADD_MANA_ANY_COLOR_RE,
        _add_mana_any_color,
    ),
    # "add {b}{b}{b}." (Dark Ritual-shaped bare mana-symbol spell body).
    EffectHandler(
        "add_mana",
        _ADD_MANA_RE,
        _add_mana,
    ),
    EffectHandler("add_mana_counted", _ADD_MANA_COUNTED_RE, _add_mana_counted),
    EffectHandler("add_mana_that_much", _ADD_MANA_THAT_MUCH_RE, _add_mana_that_much),
    EffectHandler("add_mana_any_combination", _ADD_MANA_ANY_COMBINATION_RE, _add_mana_any_combination),
    # "that player adds an additional {b}." (Bubbling Muck/High Tide).
    EffectHandler(
        "add_mana_additional_event_player",
        _ADD_MANA_ADDITIONAL_EVENT_PLAYER_RE,
        _add_mana_additional_event_player,
    ),
    # "…its controller adds an additional {g}" (Wild Growth/Overgrowth/Dawn's Reflection) — the host's controller.
    EffectHandler(
        "add_mana_additional_its_controller",
        _ADD_MANA_ADDITIONAL_ITS_CONTROLLER_RE,
        _add_mana_additional_event_player,
        attached_subject_only=True,
    ),
    # "transform ~" / "transform it" / "transform this permanent"/"creature"
    # (RULE 712.8) — the self-transform shape a loyalty "[0]: Transform ~."
    # or a "whenever ~ attacks, transform it" trigger uses.
    EffectHandler(
        "transform",
        _c(rf"transform (?:{re.escape(SELF)}|it|this permanent|this creature)"),
        _transform,
    ),
    # "exile ~/this saga, then return it/him/her to the battlefield
    # transformed under your/its/his/her owner's control" (RULE 400.7 +
    # RULE 712.8) — a transforming Saga's chapter III, or an activated
    # ability's own flip phrased this way instead of a bare "transform ~".
    EffectHandler(
        "exile_return_transformed",
        _EXILE_RETURN_TRANSFORMED_RE,
        _exile_return_transformed,
    ),
    # "exile <TARGET> [an opponent controls] until ~ leaves the
    # battlefield." (O-Ring / Banisher Priest / Fiend Hunter) — the
    # companion LEAVES_BATTLEFIELD return ability is synthesized by the
    # segmenter off the ``until_source_leaves`` param.
    EffectHandler(
        "exile_until_leaves",
        _EXILE_UNTIL_LEAVES_RE,
        _exile_until_leaves,
    ),
    # "return it/~ to the battlefield transformed under its owner's
    # control" (RULE 400.7 + RULE 712.8, Bruce Banner-shaped) — a dies
    # trigger's own graveyard-sourced sibling of the exile-and-blink shape
    # just above (no "exile ~, then" prefix: dying already put it there).
    EffectHandler(
        "return_from_graveyard_transformed",
        _RETURN_FROM_GRAVEYARD_TRANSFORMED_RE,
        _return_from_graveyard_transformed,
    ),
    # "Return this card from your graveyard to the battlefield[, tapped]."
    # (PAR-10 discovery) — the plain, non-transforming sibling just above.
    EffectHandler(
        "return_self_from_graveyard",
        _RETURN_SELF_FROM_GRAVEYARD_RE,
        _return_self_from_graveyard,
    ),
    # "When ~ dies, return it to the battlefield [tapped] under its
    # owner's/your control[ with a +1/+1 counter on it]." (Demonic Gifts /
    # Feign Death / Abnormal Endurance cycle).
    EffectHandler(
        "return_self_to_battlefield",
        _RETURN_SELF_TO_BATTLEFIELD_RE,
        _return_self_to_battlefield,
    ),
    # "When ~ dies, if it was a creature, return it to the battlefield under its owner's control.
    # It's an enchantment." (Enduring cycle) — the effect reads "if it was a creature" off the DIES
    # event itself (RULE 400.7), so the intervening-if is part of the claimed text, not a gate.
    EffectHandler(
        "dies_return_as_enchantment",
        _DIES_RETURN_AS_ENCHANTMENT_RE,
        lambda m: [EffectSpec("dies_return_as_enchantment", {})],
        self_subject_only=True,
    ),
    # "return that card to the battlefield under its owner's control"
    # (Graceful Reprieve) — the self-subject-bound-target spelling.
    EffectHandler(
        "return_target_to_battlefield_self",
        _RETURN_TARGET_TO_BATTLEFIELD_SELF_RE,
        _return_target_to_battlefield_self,
        self_subject_only=True,
    ),
    EffectHandler(
        "return_trigger_card_to_hand",
        _RETURN_TRIGGER_CARD_TO_HAND_RE,
        _return_trigger_card_to_hand,
    ),
    # "~ becomes prepared" / "it becomes prepared" / "this permanent"/
    # "this creature becomes prepared" (RULE 722.3a) — a preparation card's
    # own "whenever X, ~ becomes prepared" trigger; the self-only shape
    # mirrors "transform" above (RULE 722.3a has no targeted form).
    EffectHandler(
        "become_prepared",
        _c(rf"(?:{re.escape(SELF)}|it|this permanent|this creature) becomes prepared"),
        _become_prepared,
    ),
    # "Activate only once each turn." (Quirion Ranger/Scryb Ranger-shaped) —
    # a per-instance activation cap, not a real effect; see
    # `ONCE_PER_TURN_MARKER`'s docstring for how the binder strips it.
    EffectHandler(
        "once_per_turn",
        _ONCE_PER_TURN_RE,
        _once_per_turn,
    ),
    # "This ability triggers only once each turn." (PAR-14) — a triggered
    # ability's own once-per-turn cap, not a real effect; see
    # `TRIGGER_ONCE_PER_TURN_MARKER`'s docstring for how `segment_line`
    # strips it into `AbilitySpec.trigger["limit"]`.
    EffectHandler(
        "trigger_once_per_turn",
        _TRIGGER_ONCE_PER_TURN_RE,
        _trigger_once_per_turn,
    ),
    # "Do this only once each turn." (PAR-135) — the optional action's own cap; see
    # `ACTION_ONCE_PER_TURN_MARKER`.
    EffectHandler(
        "action_once_per_turn",
        _ACTION_ONCE_PER_TURN_RE,
        _action_once_per_turn,
    ),
    # "Activate only as a sorcery." / "… only any time you could cast a
    # sorcery." — a RULE 602.5d timing restriction, not a real effect; see
    # `SORCERY_SPEED_MARKER`'s docstring for how the binder folds it into the
    # cost's `sorcery_speed_only` flag.
    EffectHandler(
        "sorcery_speed",
        _SORCERY_SPEED_RE,
        _sorcery_speed,
    ),
    EffectHandler("x_spend_color", _X_SPEND_COLOR_RE, _x_spend_color),
    # "Activate only during your turn." — RULE 602.5d's wider sibling
    # (Wishclaw Talisman); see `ONLY_DURING_YOUR_TURN_MARKER`'s docstring.
    EffectHandler(
        "only_during_your_turn",
        _ONLY_DURING_YOUR_TURN_RE,
        _only_during_your_turn,
    ),
    # PAR-10: "Activate only as a sorcery and only if `<condition>`." — tried
    # before the bare `_SORCERY_SPEED_RE`/`_ACTIVATE_ONLY_IF_RE` rows since a
    # `fullmatch` against the *whole* compound sentence is what makes this
    # one, not either of them, the actual match.
    EffectHandler(
        "sorcery_speed_and_condition",
        _SORCERY_SPEED_AND_CONDITION_RE,
        _sorcery_speed_and_condition,
    ),
    # "Activate only if `<condition>`." (no sorcery-speed restriction) —
    # Potioner's Trove-shaped.
    EffectHandler(
        "activate_during_your_turn_and_if",
        _ACTIVATE_DURING_YOUR_TURN_AND_IF_RE,
        _activate_during_your_turn_and_if,
    ),
    EffectHandler(
        "activate_only_if",
        _ACTIVATE_ONLY_IF_RE,
        _activate_only_if,
    ),
    # "you win the game." (RULE 104.2 — Felidar Sovereign, Test of Endurance: the upkeep trigger's body after its
    # intervening "if you have 40 or more life"). The conditional library-empty form is the row below.
    EffectHandler("win_game", _c(r"you win the game"), lambda m: [EffectSpec("win_game", {})]),
    # "if your library has no cards in it, you win the game" (Jace, Wielder
    # of Mysteries' -8 tail).
    EffectHandler(
        "win_if_empty_library",
        _c(r"(?:then )?if your library has no cards? in it, you win the game"),
        _win_if_empty_library,
    ),
    # MEC-27: "put x +1/+1 counters on target creature, where x is the
    # number of Elves you control." — tried before the plain `add_counters`
    # row below since "x" never matches that row's `{COUNT}` (digit/"a"/"an"
    # only).
    EffectHandler("add_counters_devotion", _ADD_COUNTERS_DEVOTION_RE, _add_counters_devotion),
    # "put a +1/+1 counter on target suspected creature you control" (PAR-29)
    # — tried before the plain `add_counters` row below, whose `TARGET`
    # alternation has no "suspected" adjective row.
    EffectHandler(
        "add_counters_suspected_target",
        _c(rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on target suspected creature you control"),
        _add_counters_suspected_target,
    ),
    # MEC-46 (Galadriel) — "put a +1/+1 counter on your Ring-bearer" —
    # before the plain `add_counters` row (whose `TARGET` alternation has
    # no "your ring-bearer" phrase).
    EffectHandler(
        "add_counters_ring_bearer",
        _ADD_COUNTERS_RING_BEARER_RE,
        _add_counters_ring_bearer,
    ),
    # "put a -1/-1 counter on target creature, two -1/-1 counters on another
    # target creature, and three -1/-1 counters on a third target creature."
    # (Incremental Blight / Incremental Growth) — three escalating targets,
    # tried before the plain `add_counters` row.
    EffectHandler(
        "incremental_counters",
        _INCREMENTAL_COUNTERS_RE,
        _incremental_counters,
    ),
    # PAR-117: the group-subject "it" reading, tried *before* the generic
    # row below so a bare "it" is claimed here while an explicit "~"/name
    # still falls through to that row's self-buff — see
    # `_add_counters_group_subject_it`'s own docstring.
    EffectHandler(
        "add_counters_group_subject_it",
        _ADD_COUNTERS_GROUP_SUBJECT_IT_RE,
        _add_counters_group_subject_it,
        group_subject_only=True,
    ),
    # Longstalk Brawl: a preceding "choose target creature you control and
    # target creature you don't control" already announced the pair.  "The
    # creature you control" is the first member, not a new target.
    EffectHandler(
        "add_counters_chosen_creature_you_control",
        _c(
            rf"put {COUNT} (?P<ckind>{_PT_COUNTER_TOKEN}) counters? "
            r"on the creature you control"
        ),
        lambda m: [EffectSpec("add_counters", {
            "count": count_of(m.group("n")) * _counter_kind_and_multiplier(m.group("ckind"))[1],
            "kind": _counter_kind_and_multiplier(m.group("ckind"))[0],
            "previous_subject": True,
        })],
        previous_subject_only=True,
    ),
    # "put a +1/+1 counter on target creature" / "put a -1/-1 counter on …" /
    # "… on ~"/"this creature" (Walking Ballista's "{4}: Put a +1/+1 counter
    # on this creature." — `_SELF_SUBJECT`, the same self-reference
    # vocabulary `_tap_self` already uses, not just the literal ``~`` a
    # card's own name folds to).
    EffectHandler(
        "add_counters",
        _c(
            # "+1/+1" / "-1/-1" — and "+N/+N" for N>1 (Baron Sengir's
            # "+2/+2 counter"), modeled as N +1/+1 counters (see
            # `_counter_kind_and_multiplier`).
            rf"put {COUNT_X} (?P<ckind>{_PT_COUNTER_TOKEN}) counters? on "
            rf"(?:{TARGET}|(?P<selfref>{_SELF_SUBJECT}))"
        ),
        _add_counters,
    ),
    EffectHandler("transfer_event_counters", _TRANSFER_EVENT_COUNTERS_RE,
                  _transfer_event_counters),
    # "put a spore counter on ~" (Deathspore Thallid/Elvish Farmer-shaped)
    # / "…on target fungus" (Fungal Bloom) — the named-counter sibling of
    # the P/T-only row just above.
    EffectHandler(
        "add_named_counter",
        _ADD_NAMED_COUNTER_RE,
        _add_named_counter,
    ),
    EffectHandler("add_named_counter_group", _ADD_NAMED_COUNTER_GROUP_RE, _add_named_counter_group),
    EffectHandler("add_counter_pick", _ADD_COUNTER_PICK_RE, _add_counter_pick),
    EffectHandler("add_counter_list", _ADD_COUNTER_LIST_RE, _add_counter_list),
    EffectHandler("add_counter_choice", _ADD_COUNTER_CHOICE_RE, _add_counter_choice),
    EffectHandler("remove_named_counter_self", _REMOVE_NAMED_COUNTER_SELF_RE, _remove_named_counter_self),
    # "whenever you gain life, put that many +1/+1 counters on ~/target
    # creature" (Ageless Entity/Karlov-adjacent lifegain payoffs) — tried
    # before the plain `add_counters` row above so its "that many" wins
    # over that row's literal-`COUNT` alternation. `self_subject_only`:
    # its ``(?P<selfref>{_SELF_SUBJECT})`` branch includes the bare pronoun
    # "it", which under a *group*-subject trigger ("whenever a creature you
    # control deals combat damage to a player, put that many +1/+1 counters
    # on it" — Necropolis Regent) means whichever group member fired it,
    # not this ability's own source — claiming it blind would silently
    # buff the wrong object. A player-subject trigger ("whenever you gain
    # life") introduces no such group, so `segmenter.segment_line`'s player-
    # event branch passes ``self_subject=True`` and this row is offered.
    EffectHandler(
        "add_counters_from_trigger_amount",
        _c(
            rf"put that many (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
            rf"(?:{TARGET}|(?P<selfref>{_SELF_SUBJECT}))"
        ),
        _add_counters_from_trigger_amount,
        self_subject_only=True,
    ),
    EffectHandler(
        "add_counters_spell_mv", _ADD_COUNTERS_SPELL_MV_RE, _add_counters_spell_mv,
    ),
    # "~ gets +x/+x until end of turn, where x is the amount of life you
    # gained." (Field-Tested Frying Pan's granted ability) — same pronoun-
    # ambiguity gate as the row above.
    EffectHandler(
        "pump_self_from_life_gained",
        _PUMP_SELF_FROM_LIFE_GAINED_RE,
        _pump_self_from_life_gained,
        self_subject_only=True,
    ),
    # ENG-32: "~ / creatures you control ha[s|ve] base power and toughness
    # N/M until end of turn" (Flexible Waterbender / Katara, Water Tribe's
    # Hope) — a resolve-time layer-7b `pt_set` via `grant_until`.
    EffectHandler(
        "base_pt_until_eot",
        _BASE_PT_UNTIL_EOT_RE,
        _base_pt_until_eot,
    ),
    EffectHandler(
        "choose_creature_type_until_eot",
        _CHOOSE_CREATURE_TYPE_UNTIL_EOT_RE,
        _choose_creature_type_until_eot,
    ),
    # "put a +1/+1 counter on each of up to two target creatures" (RULE
    # 115.1a generalized to N>=2 — the Support-keyword-shaped family).
    EffectHandler(
        "add_counters_multi_target",
        _c(
            rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on each of "
            rf"{_MULTI_TARGET_QUANTIFIER_X}(?:other )?(?P<target>{_MULTI_TARGET_ALT})"
        ),
        _add_counters_multi_target,
    ),
    # PAR-15: "distribute N +1/+1 counters among any number of target
    # creatures[ you control]" — a divided pool, not "each of N" full-amount.
    EffectHandler(
        "distribute_counters",
        _DISTRIBUTE_COUNTERS_RE,
        _distribute_counters,
    ),
    # ENG-30: "distribute N +1/+1 counters among 1 or 2 target creatures
    # [you control]" — a genuine RULE 601.2c range, tried before the plain
    # `distribute_counters` row since "1 or 2" would otherwise also satisfy
    # that row's own `\d+` (it doesn't — that row requires "any number of"
    # literally — but keeping the more specific row first matches this
    # file's usual ordering convention for overlapping shapes).
    EffectHandler(
        "distribute_counters_range",
        _DISTRIBUTE_COUNTERS_RANGE_RE,
        _distribute_counters_range,
    ),
    EffectHandler(
        "distribute_counters_up_to", _DISTRIBUTE_COUNTERS_UP_TO_RE, _distribute_counters_up_to,
    ),
    # "put N +1/+1 counters on each creature you control" (RULE 601.2c mass
    # effect, Vastwood Surge-shaped).
    EffectHandler(
        "add_counters_selector",
        _c(
            rf"put {COUNT_X} (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
            r"(?P<selector>each other planeswalker you control|each other creature you control"
            r"|each creature your opponents control|each other creature|each creature you control|each creature)"
            r"(?P<has_counter> that has a \+1/\+1 counter on it)?"
        ),
        _add_counters_selector,
    ),
    EffectHandler("add_pt_counter_group", _ADD_PT_COUNTER_GROUP_RE, _add_counter_group),
    # "target creature gets +1/+0 until end of turn and can't be blocked
    # this turn" (You Come to a River-shaped) — tried before the plain
    # `pump` handler below since it's a strict superset of that shape (a
    # trailing unblockable clause `_pump`'s own grammar doesn't recognise).
    EffectHandler(
        "pump_unblockable",
        _PUMP_UNBLOCKABLE_RE,
        _pump_unblockable,
    ),
    # ENG-32: bare "~ / target creature can't be blocked this turn" (Giant
    # Koi / Waterbender Ascension) — no P/T delta.
    # PAR-79: "up to 2 target creatures can't be blocked this turn." —
    # tried before the singular `cant_be_blocked_this_turn` row below,
    # whose `TARGET` alternation has no multi-target quantifier of its own.
    EffectHandler(
        "cant_be_blocked_this_turn_multi",
        _CANT_BE_BLOCKED_TURN_MULTI_RE,
        _cant_be_blocked_turn_multi,
    ),
    EffectHandler(
        "cant_be_blocked_this_turn",
        _CANT_BE_BLOCKED_TURN_RE,
        _cant_be_blocked_turn,
    ),
    # PAR-79: the untargeted mass form — "creatures [you control] can't be
    # blocked this turn."
    EffectHandler(
        "cant_be_blocked_this_turn_mass",
        _CANT_BE_BLOCKED_TURN_MASS_RE,
        _cant_be_blocked_turn_mass,
    ),
    # PAR-79: "~ gains lifelink until end of turn and can't be blocked this
    # turn" — a strict superset of the plain `pump_keyword` row's shape (a
    # trailing unblockable clause `pump_keyword`'s own grammar doesn't
    # recognise); fullmatch means the two can never both match the same
    # clause, so order between them doesn't matter for correctness.
    EffectHandler(
        "pump_keyword_unblockable",
        _PUMP_KEYWORD_UNBLOCKABLE_RE,
        _pump_keyword_unblockable,
    ),
    # PAR-79: "[another ]target `<object-filter phrase>` can't be blocked
    # this turn" (Merfolk Sovereign's "target Merfolk creature", Corsairs of
    # Umbar's "target goblin, orc, or pirate", Bessie/Clammy Prowler's
    # "another target attacking/legendary creature", K-9, Mark I's bare
    # "target legendary creature") — one general row over
    # `static_handlers.object_filter`, which now strips a leading
    # "attacking"/"legendary"/"blocking"/"tapped" flag word itself before
    # falling through to subtype/colour parsing, so it no longer needs two
    # dedicated fixed-phrase rows tried ahead of it for exactly those words.
    EffectHandler(
        "cant_be_blocked_this_turn_object_filter",
        _CANT_BE_BLOCKED_TURN_OBJECT_FILTER_RE,
        _cant_be_blocked_turn_object_filter,
    ),
    # "Up to two target creatures can't block this turn" / "target creature
    # can't block this turn" / "creatures without flying can't block this
    # turn" — the multi form first, since its "up to two target creatures"
    # phrase is not something the singular `TARGET` alternation can claim.
    EffectHandler("cant_be_regenerated_target", _CANT_BE_REGENERATED_TARGET_RE, _cant_be_regenerated_target),
    EffectHandler(
        "cant_be_regenerated_prev", _CANT_BE_REGENERATED_PREV_RE, _cant_be_regenerated_prev,
        previous_subject_only=True,
    ),
    EffectHandler("cant_be_regenerated_hit", _CANT_BE_REGENERATED_HIT_RE, _cant_be_regenerated_hit),
    EffectHandler(
        "cant_block_this_turn_multi",
        _CANT_BLOCK_TURN_MULTI_RE,
        _cant_block_turn_multi,
    ),
    EffectHandler(
        "cant_block_this_turn",
        _CANT_BLOCK_TURN_RE,
        _cant_block_turn,
    ),
    EffectHandler(
        "cant_block_this_turn_group",
        _CANT_BLOCK_TURN_GROUP_RE,
        _cant_block_turn_group,
    ),
    # "If it's a creature, it can't block this turn." (Searing Barb's
    # damage-rider tail) — acts on the previous clause's target.
    EffectHandler(
        "if_prev_creature_cant_block",
        _IF_PREV_CREATURE_CANT_BLOCK_RE,
        _if_prev_creature_cant_block,
    ),
    # "~ can't be blocked by creatures with power 2 or less this turn" — the
    # resolve-time sibling of the standing combat-restriction static.
    EffectHandler(
        "cant_be_blocked_by_this_turn",
        _CANT_BE_BLOCKED_BY_TURN_RE,
        _cant_be_blocked_by_turn,
    ),
    # "Target creature can't block ~ this turn." — the pairwise sibling of
    # `cant_block_this_turn` above (bars blocking *this* source specifically,
    # not every attacker).
    EffectHandler(
        "cant_block_source_this_turn",
        _CANT_BLOCK_SOURCE_TURN_RE,
        _cant_block_source_turn,
    ),
    # "Target creature blocks ~ this turn if able." (RULE 509.1c, resolve-time)
    EffectHandler(
        "blocks_source_this_turn_if_able",
        _BLOCKS_SOURCE_TURN_IF_ABLE_RE,
        _blocks_source_turn_if_able,
    ),
    # "Target creature attacks this turn if able." (RULE 508.1a, resolve-time)
    EffectHandler(
        "attacks_this_turn_if_able",
        _ATTACKS_TURN_IF_ABLE_RE,
        _attacks_turn_if_able,
    ),
    # "Target creature must be blocked this turn if able."/"~ must be
    # blocked this turn if able." (RULE 509.1c, resolve-time, PAR-124).
    EffectHandler(
        "must_be_blocked_this_turn_if_able",
        _MUST_BE_BLOCKED_TURN_RE,
        _must_be_blocked_turn,
    ),
    # "target <c1> or <c2> creature gets +N/+M / gains <kw> until end of
    # turn" (the Weaver cycle) — `TargetSpec.colors` OR narrowing; a
    # dedicated row since the shared `TARGET` macro has no colour slot.
    EffectHandler(
        "pump_target_two_color",
        _PUMP_TARGET_TWO_COLOR_RE,
        _pump_target_two_color,
    ),
    # "<subject> gets +x/+x [and gains <kw>] until end of turn" — the
    # {X}-cost-spell pump (Tyvar's Stand, Untamed Might). Tried before the
    # plain `pump` row below, whose `_PT_DELTA` only matches digits anyway.
    EffectHandler(
        "pump_x_nonland_permanents",
        _PUMP_X_NONLAND_PERMANENTS_RE,
        _pump_x_nonland_permanents,
    ),
    # "<subject> gets +x/+x …" / "<subject> gets -x/-x …" — same X-scaled
    # pump, either polarity. A backreference on `sign` (not a bare `[+\-−]`
    # each side) keeps a nonsensical "+x/-x" split unclaimed rather than
    # silently accepted — no real card mixes the sign within one X-pump.
    EffectHandler(
        "pump_x",
        _c(
            rf"{_SUBJECT} gets? (?P<sign>[+\-−])x/(?P=sign)x"
            rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _pump_x,
    ),
    EffectHandler(
        "pump_subtype_target",
        _PUMP_SUBTYPE_TARGET_RE,
        _pump_subtype_target,
    ),
    EffectHandler(
        "pump_subtype_target_global_count",
        _PUMP_SUBTYPE_TARGET_GLOBAL_COUNT_RE,
        _pump_subtype_target_global_count,
    ),
    EffectHandler(
        "grant_subtype_target",
        _GRANT_SUBTYPE_TARGET_RE,
        _grant_subtype_target,
    ),
    # "target creature gets +3/+3 until end of turn" / "gets -2/-2 …" /
    # "gets +1/+1 and gains trample until end of turn" / "~ gets +1/+0 …" /
    # "creatures you control get +2/+1 until end of turn" (plural "get").
    EffectHandler(
        "noncolor_creatures_pump",
        _NONCOLOR_CREATURES_PUMP_RE,
        _noncolor_creatures_pump,
    ),
    EffectHandler(
        "pump",
        _c(
            rf"{_SUBJECT} gets? {_PT_DELTA}"
            rf"(?: and gains? (?P<kw>[a-z0-9, ]+?))? until end of turn"
            # PAR-124: "…and must be blocked this turn if able." (Compelled
            # Duel/Emergent Growth/Joraga Invocation).
            rf"(?P<must_blocked> and must be blocked this turn if able)?"
        ),
        _pump,
    ),
    # RULE 701.10/11 "double"/"triple the power and toughness of <target
    # creature[ you control]>/each creature you control until end of turn"
    # (Dragonclaw Strike/Roar of Endless Song).
    EffectHandler(
        "double_pt_of",
        _c(
            rf"(?P<mult>double|triple) the {_DOUBLE_STAT} of "
            rf"(?:{TARGET}|(?P<each_group>each creature you control)) until end of turn"
        ),
        _double_pt_of,
    ),
    # The possessive phrasing — "double/triple <target creature>'s/~'s
    # power and toughness until end of turn" (Nylea's Colossus/Reckless
    # Amplimancer/Tifa's Limit Break's own "triple"), or just "power" (Bulk Up).
    EffectHandler(
        "double_pt_possessive",
        _c(
            rf"(?P<mult>double|triple) (?:(?P<selfposs>~)|{TARGET})'s "
            rf"{_DOUBLE_STAT} until end of turn"
        ),
        _double_pt_possessive,
    ),
    # The bare pronoun — "double its power and toughness until end of
    # turn." Self-subject (Grunn's "whenever ~ attacks alone, double its
    # power and toughness"), the previous-clause pronoun (World War
    # Hulk's "choose target creature you control. … double its power and
    # toughness.") and the group trigger's firing creature (Death Kiss) are
    # genuinely different referents, so three rows.
    *_subject_handlers([
        ("double_pt_self_pronoun", "self", _DOUBLE_PRONOUN_RE, _double_pt_pronoun),
        ("double_pt_previous", "previous", _DOUBLE_PRONOUN_RE, _double_pt_previous),
        ("double_pt_group_pronoun", "group", _DOUBLE_PRONOUN_RE, _double_pt_group),
        ("double_pt_attached_pronoun", "attached", _DOUBLE_PRONOUN_RE, _double_pt_attached),
    ]),
    # PAR-15: "any number of target creatures each get +N/+N [and gain
    # `<keyword>`] until end of turn" — every chosen creature gets the full
    # boost, not a divided pool.
    EffectHandler(
        "pump_multi_target",
        _PUMP_MULTI_TARGET_RE,
        _pump_multi_target,
    ),
    # "Untap those creatures." (Colossal Heroics) — the previous clause's own
    # multi-target group, read back the same way `return_previous_group` does.
    EffectHandler(
        "untap_previous_group",
        _UNTAP_PREVIOUS_GROUP_RE,
        _untap_previous_group,
        previous_subject_only=True,
    ),
    # "Those creatures don't untap …" after a mass selector (Clinging Mists).
    EffectHandler(
        "skip_untap_previous_selector",
        _SKIP_UNTAP_PREV_SELECTOR_RE,
        _skip_untap_prev_selector,
        previous_selector_only=True,
    ),
    # "Untap those creatures." after a mass selector (War Flare, PAR-128).
    EffectHandler(
        "tap_previous_selector",
        _TAP_PREVIOUS_SELECTOR_RE,
        _tap_previous_selector,
        previous_selector_only=True,
    ),
    # "…, then untap that land." (Avatar Kyoshi, following "earthbend N") —
    # the singular previous-subject sibling of the row just above.
    EffectHandler(
        "tap_previous_subject",
        _TAP_PREVIOUS_SUBJECT_RE,
        _tap_previous_subject,
        previous_subject_only=True,
    ),
    # "target/that/~ <permanent> doesn't untap during … next untap step"
    # (Barl's Cage + the ~95-card "Tap X. It doesn't untap …" family).
    EffectHandler("skip_next_untap_target", _SKIP_UNTAP_TARGET_RE, _skip_untap_target),
    EffectHandler(
        "skip_next_untap_prev", _SKIP_UNTAP_PREV_RE, _skip_untap_prev,
        previous_subject_only=True,
    ),
    # With no earlier clause to refer back to, "that land" is the object the firing
    # event names (Vorinclex's "whenever an opponent taps a land for mana, that land
    # doesn't untap …", PAR-119) — nothing outside a trigger.
    EffectHandler(
        "skip_next_untap_event_object",
        _c(rf"that (?:land|permanent){_DONT_UNTAP_SUFFIX}"),
        lambda m: [EffectSpec("skip_next_untap", {"target_operand": {"of": "entering"}})],
    ),
    EffectHandler(
        "skip_next_untap_self", _SKIP_UNTAP_SELF_RE, _skip_untap_self,
        self_subject_only=True,
    ),
    # "Whenever ~ deals combat damage to a creature, tap that creature and
    # it doesn't untap …" (PAR-84 — Kashi-Tribe Reaver/Warriors).  The
    # DAMAGE recipient is neither a normal target nor the trigger source;
    # this tightly scoped row reads it from the firing event.
    EffectHandler(
        "tap_damage_recipient_and_skip_untap",
        _TAP_DAMAGE_RECIPIENT_AND_SKIP_UNTAP_RE,
        _tap_damage_recipient_and_skip_untap,
        self_subject_only=True,
    ),
    EffectHandler(
        "redirect_damage_to_self",
        _REDIRECT_DAMAGE_TO_SELF_RE,
        _redirect_damage_to_self,
    ),
    # "[TARGET / ~ / it] gains protection from the color of your choice
    # until end of turn" (RULE 702.16 — Gods Willing, Jareth, Feat of
    # Resistance &c.; the engine primitive is Mother of Runes').
    EffectHandler(
        "grant_prot_choice_target", _GRANT_PROT_CHOICE_TARGET_RE, _grant_prot_choice_target,
    ),
    EffectHandler(
        "grant_prot_choice_self", _GRANT_PROT_CHOICE_SELF_RE, _grant_prot_choice_self,
        self_subject_only=True,
    ),
    EffectHandler(
        "grant_prot_choice_prev", _GRANT_PROT_CHOICE_PREV_RE, _grant_prot_choice_prev,
        previous_subject_only=True,
    ),
    EffectHandler(
        "group_fixed_protection", _GROUP_FIXED_PROTECTION_RE, _group_fixed_protection,
    ),
    # "Reveal cards from the top of your library until you reveal a <type>
    # card. Put that card <onto the battlefield / into your hand> and the
    # rest <bottom / graveyard / shuffle>." (Recross the Paths, Clifftop
    # Lookout, Atla Palani, … — `RulesEngine.dig_until`).
    EffectHandler("reveal_until_type", _REVEAL_UNTIL_TYPE_RE, _reveal_until_type),
    EffectHandler(
        "dig_until_doctor_companion_vehicle",
        _DIG_UNTIL_DOCTOR_COMPANION_VEHICLE_RE,
        _dig_until_doctor_companion_vehicle,
    ),
    EffectHandler(
        "damage_each_opponent_full_party",
        _DAMAGE_EACH_OPPONENT_FULL_PARTY_RE,
        _damage_each_opponent_full_party,
    ),
    EffectHandler(
        "add_counter_target_full_party",
        _ADD_COUNTER_TARGET_FULL_PARTY_RE,
        _add_counter_target_full_party,
    ),
    # PAR-30: "[Then] sacrifice/exile <it/that creature/that token/them/
    # those tokens> at the beginning of [the/your] next end step." — the
    # RULE 603.7 delayed-trigger tail on every "create a token …, exile it"
    # / "reanimate …, sacrifice it" card (~100 SOLO). Ungated: `capture=
    # "previous_or_self"` resolves the referent (prev target → created
    # object → the source) at arm time and no-ops on an empty chain.
    EffectHandler(
        "delayed_sac_exile_tail",
        _DELAYED_SAC_EXILE_TAIL_RE,
        _delayed_sac_exile_tail,
    ),
    # The when-first sibling — "At the beginning of the next end step,
    # sacrifice/exile <it>[ unless ~ is your Ring-bearer]." (MEC-52).
    EffectHandler(
        "exile_instead_of_leaving", _EXILE_INSTEAD_OF_LEAVING_RE, _exile_instead_of_leaving,
        previous_subject_only=True,
    ),
    EffectHandler(
        "owner_shuffles_graveyard", _OWNER_SHUFFLES_GRAVEYARD_RE, _owner_shuffles_graveyard,
        self_subject_only=True,
    ),
    EffectHandler(
        "delayed_return_battlefield_previous", _DELAYED_RETURN_BATTLEFIELD_RE,
        _delayed_return_battlefield, previous_subject_only=True,
    ),
    EffectHandler(
        "delayed_return_battlefield_self", _DELAYED_RETURN_BATTLEFIELD_RE,
        _delayed_return_battlefield, self_subject_only=True,
    ),
    # "Exile each creature you control. Return those cards …" (Ghostway) — a mass selector's own referent.
    EffectHandler(
        "delayed_return_battlefield_selector", _DELAYED_RETURN_BATTLEFIELD_RE,
        _delayed_return_battlefield, previous_selector_only=True,
    ),
    EffectHandler(
        "delayed_sac_exile_when_first",
        _DELAYED_SAC_EXILE_WHEN_FIRST_RE,
        _delayed_sac_exile_when_first,
    ),
    # ENG-30: "They [each] get +N/+N [and gain <kw>] until end of turn."
    # (A-Bretagard Stronghold/Fancy Footwork) — the pump-family sibling of
    # `untap_previous_group`, same previous-target-group gate.
    EffectHandler(
        "pump_previous_targets_pt",
        _PUMP_PREVIOUS_TARGETS_PT_RE,
        _pump_previous_targets_pt,
        previous_subject_only=True,
    ),
    # ENG-30: "They [each] gain <kw> until end of turn." — the keyword-only
    # sibling of the row above (tried after it since a P/T delta present
    # would otherwise be swallowed by this row's own bare-keyword capture).
    EffectHandler(
        "pump_previous_targets_kw",
        _PUMP_PREVIOUS_TARGETS_KW_RE,
        _pump_previous_targets_kw,
        previous_subject_only=True,
    ),
    # PAR-30 "Threaten … tails residue" — the *rich* leading-"until end of
    # turn, it …" restatement (quoted ability / becomes-subtype / base P/T),
    # tried before the plain pronoun-pump rows so its longer shape wins.
    EffectHandler(
        "gain_control_rich_prev_grant",
        _GAIN_CONTROL_RICH_PREV_GRANT_RE,
        _gain_control_rich_prev_grant,
        previous_subject_only=True,
    ),
    # PAR-30 "Threaten … tails residue" — card-specific conditional
    # after-tails gated on the just-controlled creature (Goatnap "if that
    # creature is a Goat …", Awaken the Sleeper "if it's equipped …").
    EffectHandler(
        "if_prev_subtype_pump",
        _IF_PREV_SUBTYPE_PUMP_RE,
        _if_prev_subtype_pump,
        previous_subject_only=True,
    ),
    EffectHandler(
        "if_prev_equipped_destroy",
        _IF_PREV_EQUIPPED_DESTROY_RE,
        _if_prev_equipped_destroy,
        previous_subject_only=True,
    ),
    # PAR-30: the singular-pronoun siblings — "it [also] gets +N/+N …" /
    # "it [also] gains <kw> until end of turn" (threaten restatement tails,
    # clash "if you win, that creature …" payoffs). P/T row first so a
    # delta isn't swallowed by the keyword row's bare capture.
    EffectHandler(
        "pump_prev_singular_pt",
        _PUMP_PREV_SINGULAR_PT_RE,
        _pump_previous_targets_pt,
        previous_subject_only=True,
    ),
    EffectHandler(
        "pump_prev_singular_kw",
        _PUMP_PREV_SINGULAR_KW_RE,
        _pump_previous_targets_kw,
        previous_subject_only=True,
    ),
    EffectHandler(
        "pump_prev_haste_bare", _PUMP_PREV_HASTE_BARE_RE, _pump_prev_haste_bare, previous_subject_only=True,
    ),
    # "They gain first strike until end of turn." (Karlach, Fury of
    # Avernus, MEC-28) — the mass-selector sibling: only offered when the
    # preceding clause's own spec used a real group selector.
    EffectHandler(
        "pump_previous_selector",
        _PUMP_PREVIOUS_SELECTOR_RE,
        _pump_previous_selector,
        previous_selector_only=True,
    ),
    # "Target attacking Elf you control gains deathtouch until end of
    # turn." (Gnarlroot Trapper-shaped) — tried before the plain
    # `pump_keyword` row below since the shared `TARGET` macro has no
    # "attacking `<subtype>` you control" row for that one to match.
    EffectHandler(
        "pump_attacking_subtype_target",
        _PUMP_ATTACKING_SUBTYPE_TARGET_RE,
        _pump_attacking_subtype_target,
    ),
    EffectHandler(
        "pump_other_attacking_creature",
        _PUMP_OTHER_ATTACKING_CREATURE_RE,
        _pump_other_attacking_creature,
    ),
    # MEC-105 / RULE 613.1f: temporary ability removal. Compound rows come
    # first and remain one effect, so "gains flying and loses trample" (or a
    # P/T change plus a loss) shares one recipient and one duration.
    EffectHandler(
        "pump_and_lose_keyword",
        _c(
            rf"{_SUBJECT} gets? {_PT_DELTA} and loses? "
            r"(?P<lost>[a-z, ]+?) until end of turn"
        ),
        _temporary_keyword_change,
    ),
    EffectHandler(
        "gain_and_lose_keyword",
        _c(
            rf"{_SUBJECT} gains? (?P<kw>[a-z, ]+?) and loses? "
            r"(?P<lost>[a-z, ]+?) until end of turn"
        ),
        _temporary_keyword_change,
    ),
    EffectHandler(
        "lose_and_gain_keyword",
        _c(
            rf"{_SUBJECT} loses? (?P<lost>[a-z, ]+?) and gains? "
            r"(?P<kw>[a-z, ]+?) until end of turn"
        ),
        _temporary_keyword_change,
    ),
    EffectHandler(
        "lose_keyword_until_eot",
        _c(rf"{_SUBJECT} loses? (?P<lost>[a-z, ]+?) until end of turn"),
        _temporary_keyword_change,
    ),
    # "target creature gains flying until end of turn" (keyword-only pump) /
    # "creatures you control gain flying until end of turn".
    EffectHandler(
        "pump_keyword",
        # ``0-9`` in the keyword capture is ENG-31's parametric grant
        # ("gains firebending 4 until end of turn"); `_pump_keywords` splits
        # a "<name> <N>" entry off into ``parametric_keywords`` and
        # fail-closes on anything that isn't a FLAG or a grantable
        # parametric keyword.
        _c(
            rf"{_SUBJECT} gains? (?P<kw>[a-z0-9, ]+?) until end of turn"
            # PAR-124: "…gains deathtouch until end of turn and must be
            # blocked this turn if able." (Deadly Allure).
            rf"(?P<must_blocked> and must be blocked this turn if able)?"
        ),
        _pump_keywords,
    ),
    # PAR-102(b): the pump that also grants a quoted ability.
    EffectHandler("pump_and_quoted_grant", _PUMP_AND_QUOTED_GRANT_RE, _pump_and_quoted_grant),
    EffectHandler("pump_and_all_creature_types", _PUMP_AND_ALL_TYPES_RE, _pump_and_all_creature_types),
    EffectHandler("pump_keyword_choice", _PUMP_KEYWORD_CHOICE_RE, _pump_keyword_choice),
    # "Each creature your opponents control gets -1/-1 until end of turn
    # for each poison counter its controller has." (Phyresis Outbreak).
    EffectHandler(
        "pump_per_controller_counter",
        _PUMP_PER_CONTROLLER_COUNTER_RE,
        _pump_per_controller_counter,
    ),
    # "Up to two target creatures each get +N/+N [and gain <keywords>]
    # until end of turn." (Dauntless Onslaught-shaped).
    EffectHandler(
        "pump_up_to_two",
        _PUMP_UP_TO_TWO_RE,
        _pump_up_to_two,
    ),
    # ENG-30: "One or two target creatures…" (Opera Love Song/Heroic
    # Teamwork-shaped) — a genuine RULE 601.2c range, not "up to two"; see
    # `_PUMP_ONE_OR_TWO_RE`'s own comment for why this is now split out.
    EffectHandler(
        "pump_one_or_two",
        _PUMP_ONE_OR_TWO_RE,
        _pump_one_or_two,
    ),
    # ENG-30: "1 or 2 target creatures gain <kw> until end of turn." (Wind
    # Sail) — the keyword-only sibling of the row above.
    EffectHandler(
        "pump_one_or_two_kw",
        _PUMP_ONE_OR_TWO_KW_RE,
        _pump_one_or_two_kw,
    ),
    # "Creatures you control gain trample and get +X/+X until end of turn,
    # where X is the number of creatures you control." (Craterhoof
    # Behemoth-shaped) — tried before the plain `pump_keyword` row above
    # since it's a strict superset of that shape.
    EffectHandler(
        "group_pump_count_selector",
        _GROUP_PUMP_COUNT_SELECTOR_RE,
        _group_pump_count_selector,
    ),
    EffectHandler(
        "group_pump_other_source_power",
        _GROUP_PUMP_OTHER_SOURCE_POWER_RE,
        _group_pump_other_source_power,
    ),
    EffectHandler(
        "pump_target_per_creature_you_control",
        _PUMP_TARGET_PER_CREATURE_YOU_CONTROL_RE,
        _pump_target_per_creature_you_control,
    ),
    # RULE 202.2f/700.6 "target creature gets +X/+X until end of turn, where
    # X is your devotion to <colour(s)/wedge>." (Aspect of Hydra/Devoted
    # Temur-shaped) and its "-X/-X" debuff sibling (Blight-Breath
    # Catoblepas) / mass "creatures you control get +X/+X …" sibling
    # (Klothys's Design) — tried before the plain digit-amount `pump` row
    # below since "x" would otherwise never match that row's `\d+`.
    EffectHandler("pump_devotion_target", _PUMP_DEVOTION_TARGET_RE, _pump_devotion_target),
    EffectHandler("pump_mana_value", _PUMP_MANA_VALUE_RE, _pump_mana_value),
    EffectHandler(
        "pump_target_source_power", _PUMP_TARGET_SOURCE_POWER_RE, _pump_target_source_power
    ),
    # PAR-80: "target creature gets +X/+0[/+X] until end of turn, where X
    # is <quantity>." — kept before the bare `pump_target_x` row below by
    # this file's more-specific-first convention.
    EffectHandler(
        "pump_target_x_amount", _PUMP_TARGET_X_AMOUNT_RE, _pump_target_x_amount
    ),
    EffectHandler(
        "pump_target_x_random", _PUMP_TARGET_X_RANDOM_RE, _pump_target_x_random
    ),
    EffectHandler(
        "reveal_random_hand_card_pump_mv",
        _REVEAL_RANDOM_HAND_CARD_PUMP_MV_RE, _reveal_random_hand_card_pump_mv,
    ),
    EffectHandler(
        "reveal_any_number_pump", _REVEAL_ANY_NUMBER_PUMP_RE, _reveal_any_number_pump
    ),
    # PAR-80: the base X-spell/X-ability pump, no "where X is…" tail —
    # RULE 107.3c's announced {X}, substituted generically at resolve time
    # by `RulesEngine._substitute_x` (no new primitive).
    EffectHandler("pump_target_x", _PUMP_TARGET_X_RE, _pump_target_x),
    EffectHandler(
        "pump_devotion_negative_target", _PUMP_DEVOTION_NEGATIVE_TARGET_RE, _pump_devotion_negative_target
    ),
    EffectHandler("group_pump_devotion", _GROUP_PUMP_DEVOTION_RE, _group_pump_devotion),
    # PAR-81: "Switch target creature's power and toughness until end of
    # turn." and siblings — tried as a block, most-specific (multi-target)
    # first so a shorter row never shadows it.
    EffectHandler("switch_pt_multi", _SWITCH_PT_MULTI_RE, _switch_pt_multi),
    EffectHandler("switch_pt_mass", _SWITCH_PT_MASS_RE, _switch_pt_mass),
    EffectHandler("switch_pt_target", _SWITCH_PT_TARGET_RE, _switch_pt_target),
    EffectHandler("switch_pt_self", _SWITCH_PT_SELF_RE, _switch_pt_self),
    # "Whenever ~ attacks, it gets +X/+X until end of turn, where X is …"
    # (Angelic Exaltation-adjacent self-buff-on-attack) — tried before the
    # flat-amount row below, whose `\d+` would never match a bare "x".
    EffectHandler(
        "pump_self_subject_devotion",
        _PUMP_SELF_SUBJECT_DEVOTION_RE,
        _pump_self_subject_devotion,
        self_subject_only=True,
    ),
    # "Whenever ~ attacks, it gets +1/+0 until end of turn." (Akroan Hoplite-
    # adjacent self-buff-on-attack, `it` bound to the ability's own source —
    # `self_subject_only`, only ever offered from a self-subject trigger
    # body).
    EffectHandler(
        "pump_self_subject",
        _c(
            rf"it gets? {_PT_DELTA}"
            rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _pump_self_subject,
        self_subject_only=True,
    ),
    # "Whenever ~ attacks, it gains double strike until end of turn."
    # (Flaming Fist) — the keyword-only sibling of `pump_self_subject`
    # above (no P/T delta), `it` bound to the ability's own source.
    EffectHandler(
        "grant_self_subject_kw",
        _c(r"it gains? (?P<kw>[a-z, ]+?) until end of turn"),
        _grant_self_subject_kw,
        self_subject_only=True,
    ),
    EffectHandler(
        "gain_and_lose_self_subject_kw",
        _c(
            r"(?:it|this creature) gains? (?P<kw>[a-z, ]+?) and loses? "
            r"(?P<lost>[a-z, ]+?) until end of turn"
        ),
        _temporary_keyword_change_implicit,
        self_subject_only=True,
    ),
    EffectHandler(
        "pump_and_lose_self_subject_kw",
        _c(
            rf"(?:it|this creature) gets? {_PT_DELTA} and loses? "
            r"(?P<lost>[a-z, ]+?) until end of turn"
        ),
        _temporary_keyword_change_implicit,
        self_subject_only=True,
    ),
    EffectHandler(
        "lose_self_subject_kw",
        _c(
            r"(?:it|this creature) loses? (?P<lost>[a-z, ]+?)"
            r"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _temporary_keyword_change_implicit,
        self_subject_only=True,
    ),
    EffectHandler(
        "lose_previous_subject_kw",
        _c(
            rf"{_PREV_SUBJECT_SINGULAR}(?: also)? loses? (?P<lost>[a-z, ]+?)"
            r"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        lambda m: _temporary_keyword_change(m, previous_subject=True),
        previous_subject_only=True,
    ),
    EffectHandler("copy_that_spell", _COPY_THAT_SPELL_RE, _copy_that_spell),
    EffectHandler(
        "conjure_duplicate_into_hand",
        _CONJURE_DUPLICATE_INTO_HAND_RE,
        _conjure_duplicate_into_hand,
    ),
    EffectHandler(
        "pump_group_subject",
        _c(
            rf"it gets? {_PT_DELTA}"
            rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _pump_group_subject,
        group_subject_only=True,
    ),
    *_subject_handlers([
        ("pump_group_subject_x", "group", _PUMP_IT_X_RE, lambda m: _pump_it_x(m, subject="group")),
        ("pump_self_subject_x", "self", _PUMP_IT_X_RE, lambda m: _pump_it_x(m, subject="self")),
        ("pump_previous_subject_x", "previous", _PUMP_IT_X_RE, lambda m: _pump_it_x(m, subject="previous")),
    ]),
    EffectHandler(
        "grant_group_subject_kw",
        _c(
            r"it gains? (?P<kw>[a-z, ]+?) until end of turn"
            # PAR-124: "…and must be blocked this turn if able." (Descend
            # on the Prey).
            r"(?P<must_blocked> and must be blocked this turn if able)?"
        ),
        _grant_group_subject_kw,
        group_subject_only=True,
    ),
    # "It doesn't untap during its controller's untap step for as long as ~
    # remains tapped." — the tap-then-lock family (PAR-11), whose subject is
    # the previous clause's target.
    EffectHandler(
        "lockdown_no_untap",
        _c(
            r"(?:it|that creature|that permanent|that land|that artifact) doesn'?t untap "
            r"during its controller'?s untap step for as long as (?P<cond>.+)"
        ),
        _lockdown,
        previous_subject_only=True,
    ),
    EffectHandler("lockdown_no_untap_bare", _LOCKDOWN_BARE_RE, _lockdown_bare, previous_subject_only=True),
    EffectHandler("base_pt_previous", _BASE_PT_PREVIOUS_RE, _base_pt_previous, previous_subject_only=True),
    # The same grant with any *other* duration (RULE 611) — "…until your next
    # turn", "…until end of combat". Ordered after the end-of-turn row above,
    # which it can't collide with (that duration isn't in `_GRANT_DURATIONS`).
    EffectHandler(
        "grant_until",
        _c(
            rf"{_SUBJECT} gains? (?P<kw>[a-z, ]+?) "
            r"(?P<dur>until (?:your next turn|the end of combat|end of combat|"
            r"the beginning of the next end step))"
        ),
        _grant_until,
    ),
    # MEC-88: "target creature loses banding and all 'bands with other'
    # abilities until end of turn." (Tolaria's body) / "…loses all 'bands
    # with other' abilities until end of turn." (Shelkin Brownie).
    EffectHandler(
        "lose_banding",
        _LOSE_BANDING_RE,
        _lose_banding,
    ),
    # The same grant on a *previous* clause's subject ("It gains haste until
    # your next turn." — Offspring's Revenge). Ordered after the `_SUBJECT`
    # row: that one's `_SUBJECT` never matches a bare "it", so no collision.
    EffectHandler(
        "grant_until_previous",
        _GRANT_UNTIL_PREVIOUS_RE,
        _grant_until_previous,
        previous_subject_only=True,
    ),
    # PAR-13: the P/T sibling of the row above — "target creature gets
    # -4/-0 until your next turn"/"creatures your opponents control get
    # -3/-0 until your next turn".
    EffectHandler(
        "pump_until",
        _c(
            rf"{_SUBJECT} gets? {_PT_DELTA} "
            r"(?P<dur>until (?:your next turn|the end of combat|end of combat|"
            r"the beginning of the next end step))"
        ),
        _pump_until,
    ),
    # MEC-87: the permanent (no "until …" tail at all) sibling of the row
    # above — "target creature gets +2/+2 and gains horsemanship."
    EffectHandler(
        "pump_and_grant_indefinite",
        _c(rf"{TARGET} gets {_PT_DELTA} and gains? (?P<kw>[a-z, ]+)"),
        _pump_and_grant_indefinite,
    ),
    EffectHandler("pump_grant_while_tapped", _PUMP_GRANT_WHILE_TAPPED_RE, _pump_grant_while_tapped),
    # PAR-13: "target creature can't attack/block until <duration>" — the
    # resolve-time-grant sibling of the permanent-static "~ can't attack."
    EffectHandler(
        "cant_attack_or_block_until",
        _CANT_ATTACK_OR_BLOCK_UNTIL_RE,
        _cant_attack_or_block_until,
    ),
    # "scry 2" (RULE 701.18) / "surveil 2" (RULE 701.31) — both a self effect
    # (the controller scries/surveils), same grammar, one handler.
    EffectHandler(
        "scry_or_surveil",
        _c(r"(?:you )?(?P<verb>scry|surveil) (?P<n>\d+|x)"),
        _scry_or_surveil,
    ),
    # "fateseal N" (RULE 701.29a) — scry aimed at an opponent's library.
    EffectHandler(
        "fateseal",
        _c(rf"(?:you )?fateseal {NUMBER}"),
        _fateseal,
    ),
    # "heal all damage from ~ / each creature you control" (RULE 701.69a).
    EffectHandler(
        "heal",
        _HEAL_RE,
        _heal,
    ),
    # "if you both own and control ~ and a … named X, exile them, then meld
    # them into Y" (RULE 701.42a) — a meld card's activated-ability body.
    EffectHandler(
        "meld",
        _MELD_BODY_RE,
        _meld,
    ),
    EffectHandler(
        "look_top_reorder",
        _LOOK_TOP_REORDER_RE,
        _look_top_reorder,
    ),
    # "venture into the dungeon" (RULE 701.49) / "venture into Undercity"
    # (RULE 701.49d).
    EffectHandler(
        "venture",
        _c(r"venture into (?P<dungeon>the dungeon|undercity)"),
        _venture,
    ),
    # "monstrosity 3" / "monstrosity x" (RULE 701.37a).
    EffectHandler(
        "monstrosity",
        _c(r"monstrosity (?P<n>x|\d+)"),
        _monstrosity,
    ),
    # "adapt 2" (RULE 701.46a).
    EffectHandler(
        "adapt",
        _c(rf"adapt {NUMBER}"),
        _adapt,
    ),
    # "harness ~" (MEC-79 / RULE 701.64a) — designation flip, no amount.
    EffectHandler(
        "harness",
        _c(r"harness (?:~|this permanent)"),
        _harness,
    ),
    # "~ connives[ X]" (RULE 701.50a/d) — explicit self reference
    # (activated-ability body / self-subject trigger with the name kept).
    EffectHandler(
        "connive_self_named",
        _c(rf"~ connives?{_CONNIVE_AMOUNT}"),
        _connive,
    ),
    # "it connives[ X]" / "he connives" / "she connives" — the self-subject
    # trigger pronoun; only offered when the body's "it" really is the source
    # (`self_subject_only`), never an earlier clause's pick.
    EffectHandler(
        "connive_self_pronoun",
        _c(rf"(?:it|he|she) connives?{_CONNIVE_AMOUNT}"),
        _connive,
        self_subject_only=True,
    ),
    # "that creature connives" — the previous-clause pronoun ("target
    # creature you control gains menace. That creature connives.").
    EffectHandler(
        "connive_previous",
        _c(rf"(?:it|that creature) connives?{_CONNIVE_AMOUNT}"),
        _connive_previous,
        previous_subject_only=True,
    ),
    # "each of x target creatures you control connive" (Change of Plans).
    EffectHandler(
        "connive_each_x",
        _c(r"each of x target creatures you control connive"),
        _connive_each_x,
    ),
    # "target creature [you control/an opponent controls] connives[ X]"
    # (RULE 601.2c targeting on 701.50a/d).
    EffectHandler(
        "connive_target",
        _c(rf"{TARGET} connives?{_CONNIVE_AMOUNT}"),
        _connive_target,
    ),
    # "recruit" (RULE 701.70a) — bare word (an ETB/attack trigger's whole body).
    EffectHandler(
        "recruit",
        _c(r"recruit"),
        _recruit,
    ),
    # "learn" (RULE 701.48a) — bare word (spell effect / ETB / dies / cost body).
    EffectHandler(
        "learn",
        _c(r"learn"),
        _learn,
    ),
    # "you may collect evidence N" (RULE 701.59a) — bare, no "if you do" rider.
    EffectHandler(
        "collect_evidence_bare",
        _c(r"you may collect evidence (?P<n>\d+)"),
        _collect_evidence_bare,
    ),
    # bare "collect evidence N" — the segmenter-peeled triggered-ability body.
    EffectHandler(
        "collect_evidence",
        _c(r"collect evidence (?P<n>\d+)"),
        _collect_evidence,
    ),
    # "you may forage" (RULE 701.61a) — bare, no "if you do" rider.
    EffectHandler(
        "forage_bare",
        _c(r"you may forage"),
        _forage_bare,
    ),
    # bare "forage" — the segmenter-peeled triggered-ability body.
    EffectHandler(
        "forage",
        _c(r"forage"),
        _forage,
    ),
    # "discover 3" (RULE 701.57a) — literal mana value only.
    EffectHandler(
        "discover",
        _c(r"discover (?P<n>\d+)"),
        _discover,
    ),
    # Tried before `discover_spell_mv` below: when the preceding clause
    # countered a spell, this reads the right referent; when it didn't
    # (a genuine cast trigger), the gate skips this row and falls through.
    EffectHandler(
        "discover_spell_mv_previous_target",
        _c(r"discover x, where x is that spell'?s mana value"),
        _discover_spell_mv_previous_target,
        previous_subject_only=True,
    ),
    EffectHandler(
        "discover_spell_mv",
        _c(r"discover x, where x is that spell'?s mana value"),
        _discover_spell_mv,
    ),
    EffectHandler(
        "draw_spell_mv_previous_target",
        _c(r"draws? cards? equal to that spell'?s mana value"),
        _draw_spell_mv_previous_target,
        previous_subject_only=True,
    ),
    EffectHandler(
        "create_token_xx_spell_mv_previous_target",
        _CREATE_TOKEN_XX_SPELL_MV_PREVIOUS_TARGET_RE,
        _create_token_xx_spell_mv_previous_target,
        previous_subject_only=True,
    ),
    EffectHandler(
        "create_named_token_xx_spell_mv_previous_target",
        _CREATE_NAMED_TOKEN_XX_SPELL_MV_PREVIOUS_TARGET_RE,
        _create_named_token_xx_spell_mv_previous_target,
        previous_subject_only=True,
    ),
    # "target creature [you control] explores" (RULE 701.44) — before the
    # bare/pronoun rows so its TARGET isn't stolen by a looser match.
    EffectHandler(
        "explore_target",
        _c(rf"{TARGET} explores"),
        _explore_target,
    ),
    # "~ explores" — explicit self (activated body / self-subject trigger
    # with the name kept, "when ~ enters, ~ explores").
    EffectHandler(
        "explore_self_named",
        _c(r"~ explores"),
        _explore_self,
    ),
    # "it explores" / "he explores" / "she explores" — self-subject trigger
    # pronoun ("when ~ enters, it explores").
    EffectHandler(
        "explore_self_pronoun",
        _c(r"(?:it|he|she) explores"),
        _explore_self,
        self_subject_only=True,
    ),
    # "that creature explores" — a creature an earlier clause of this same
    # resolution chose ("return target creature card … that creature
    # explores", Defossilize's first half).
    EffectHandler(
        "explore_previous",
        _c(r"(?:it|that creature) explores"),
        _explore_previous,
        previous_subject_only=True,
    ),
    # "target creature you control endures N" (RULE 701.63a) — before the
    # bare/pronoun rows so its TARGET isn't stolen.
    EffectHandler(
        "endure_target",
        _c(rf"{TARGET} endures (?P<n>\d+)"),
        _endure_target,
    ),
    # "~ endures N" — explicit self ("when ~ enters, ~ endures 3").
    EffectHandler(
        "endure_self_named",
        _c(r"~ endures (?P<n>\d+)"),
        _endure_self,
    ),
    # "~ endures x" (PAR-29, Krumar Initiate) — X is this activated
    # ability's own announced {X}.
    EffectHandler(
        "endure_self_named_x",
        _c(r"~ endures x"),
        _endure_self_x,
    ),
    # "it endures N" / "he/she endures N" — self-subject trigger pronoun.
    EffectHandler(
        "endure_self_pronoun",
        _c(r"(?:it|he|she) endures (?P<n>\d+)"),
        _endure_self,
        self_subject_only=True,
    ),
    # "it endures N" / "that creature endures N" — a previous clause's pick.
    EffectHandler(
        "endure_previous",
        _c(r"(?:it|that creature) endures (?P<n>\d+)"),
        _endure_previous,
        previous_subject_only=True,
    ),
    # "populate" (RULE 701.36a) — copy a creature token you control.
    EffectHandler(
        "populate",
        _c(r"populate"),
        _populate,
    ),
    # "populate x times" (RULE 701.36a, Full Flowering).
    EffectHandler(
        "populate_x_times",
        _c(r"populate x times"),
        _populate_x_times,
    ),
    # "clash with an opponent" / "clash with defending player" (RULE 701.30).
    EffectHandler(
        "clash",
        _c(r"clash with (?:an opponent|defending player)"),
        _clash,
    ),
    # "roll a d20" / "roll a six-sided die" / "roll two d6" (RULE 706.1).
    EffectHandler(
        "roll_die",
        _ROLL_DIE_RE,
        _roll_die,
    ),
    # MEC-90: non-pump bodies whose amount is a preceding die-roll result.
    EffectHandler("gain_life_die_result", _GAIN_LIFE_DIE_RESULT_RE, _gain_life_die_result),
    EffectHandler("draw_die_result", _DRAW_DIE_RESULT_RE, _draw_die_result),
    EffectHandler(
        "no_max_hand_size_rest_of_game", _NO_MAX_HAND_SIZE_REST_OF_GAME_RE,
        _no_max_hand_size_rest_of_game,
    ),
    EffectHandler(
        "create_named_token_die_result", _CREATE_NAMED_TOKEN_DIE_RESULT_RE,
        _create_named_token_die_result,
    ),
    EffectHandler(
        "create_creature_token_die_result", _CREATE_CREATURE_TOKEN_DIE_RESULT_RE,
        _create_creature_token_die_result,
    ),
    EffectHandler("add_counters_die_result", _ADD_COUNTERS_DIE_RESULT_RE, _add_counters_die_result),
    EffectHandler(
        "return_creatures_die_result", _RETURN_CREATURES_DIE_RESULT_RE,
        _return_creatures_die_result,
    ),
    # MEC-50: Clash win/otherwise-branch bodies (RULE 701.30d).
    EffectHandler(
        "mill_prev_spell_controller",
        _MILL_PREV_SPELL_CONTROLLER_RE,
        _mill_prev_spell_controller,
    ),
    EffectHandler(
        "that_player_discards",
        _THAT_PLAYER_DISCARDS_RE,
        _that_player_discards,
    ),
    EffectHandler(
        "gain_control_attached",
        _GAIN_CONTROL_ATTACHED_RE,
        _gain_control_attached,
    ),
    EffectHandler(
        "clashed_opp_creatures_no_untap",
        _CLASHED_OPP_CREATURES_NO_UNTAP_RE,
        _clashed_opp_creatures_no_untap,
    ),
    # "planeswalk" / "chaos ensues" (RULE 901.10 / 901.13) — Planechase
    # vote outcome bodies (Path of the Animist/Enigma) + standalone.
    EffectHandler("planeswalk", _c(r"planeswalk"), _planeswalk),
    EffectHandler("chaos_ensues", _c(r"chaos ensues"), _chaos_ensues),
    # "take an extra turn after this one" (RULE 500.7) — plain Time Walk body.
    EffectHandler(
        "take_extra_turn",
        _TAKE_EXTRA_TURN_RE,
        _take_extra_turn,
    ),
    # "you control target opponent/player during that player's next
    # turn / combat phase" (RULE 720, MEC-51).
    EffectHandler("control_player", _CONTROL_PLAYER_RE, _control_player),
    # "starting with you, each player votes for A or B. if A gets more
    # votes, X. if B gets more votes or the vote is tied, Y." (RULE 701.38,
    # PAR-29) — the 2-option majority form. Tried before the per-vote form
    # below since its "if … gets more votes" tail is more specific.
    EffectHandler(
        "vote_majority",
        _VOTE_HEADER_RE,
        _vote_majority,
    ),
    # MEC-46 — "each player votes for <colours>. ~ gains protection from
    # each color with the most votes or tied for most votes." (Council
    # Guardian). Before the per-vote form since that one fail-closes on a
    # 3+-option vote anyway.
    EffectHandler(
        "vote_winner_protection",
        _VOTE_HEADER_RE,
        _vote_winner_protection,
    ),
    # MEC-46 — "each player votes for a nonland permanent you don't control
    # / a card in your graveyard. Exile / return each <object> …" (Council's
    # Judgment, Custodi Squire) — a tally over objects.
    EffectHandler(
        "vote_object",
        _VOTE_HEADER_RE,
        _vote_object,
    ),
    # MEC-46 — Expropriate: "For each time vote, take an extra turn … . For
    # each money vote, choose a permanent owned by the voter and gain
    # control of it. Exile ~." Before the generic per-vote form (whose
    # "<body> for each <opt> vote" order is the reverse of Expropriate's).
    EffectHandler(
        "vote_expropriate",
        _VOTE_HEADER_RE,
        _vote_expropriate,
    ),
    # "starting with you, each player votes for A or B. <body1> for each A
    # vote[ and <body2> for each B vote]." (RULE 701.38, PAR-29) — the
    # per-vote scaling form.
    EffectHandler(
        "vote_per_vote",
        _VOTE_HEADER_RE,
        _vote_per_vote,
    ),
    # MEC-46 (RULE 701.38f) — "You choose how each player votes this turn."
    # (Illusion of Choice).
    EffectHandler(
        "forced_vote",
        _c(r"you choose how each player votes this turn"),
        _forced_vote,
    ),
    # "<player> faces a villainous choice — <A>, or <B>." (RULE 701.55,
    # PAR-29) — each facing player applies their own pick.
    EffectHandler(
        "face_villainous_choice",
        _VILLAINOUS_HEADER_RE,
        _face_villainous_choice,
    ),
    # "incubate X, where X is <count>" / "incubate X twice, where X is …"
    # (PAR-30) — tried before the plain-N row below (its regex would not
    # match "incubate x" anyway, but keep the dynamic form first by
    # convention).
    EffectHandler(
        "incubate_x",
        _INCUBATE_X_RE,
        _incubate_x,
    ),
    # "incubate N" / "you incubate N" (RULE 701.53).
    EffectHandler(
        "incubate",
        _c(r"(?:you )?incubate (?P<n>\d+)"),
        _incubate,
    ),
    # "time travel" (RULE 701.56, Doctor Who) — remove a time counter from
    # each suspended card you own / add one to each Vanishing-style
    # permanent you control. "time travel, then time travel" is two of
    # these from `parse_effect_body`'s ", then" split.
    EffectHandler(
        "time_travel",
        _c(r"(?:you )?time travel"),
        lambda _m: [EffectSpec("time_travel", {})],
    ),
    # "bolster N" (RULE 701.39a) — N +1/+1 counters on a least-toughness
    # creature you control.
    EffectHandler(
        "bolster",
        _c(r"bolster (?P<n>\d+)"),
        _bolster,
    ),
    # "bolster x, where x is <board count>" (PAR-29).
    EffectHandler(
        "bolster_x",
        _c(r"bolster x, where x is (?P<selector>.+)"),
        _bolster_x,
    ),
    # "blight N" (Bloomburrow) — N -1/-1 counters on a creature you control.
    EffectHandler(
        "blight",
        _c(r"blight (?P<n>\d+)"),
        _blight,
    ),
    # "earthbend X, where X is [twice] the number of <count>" (PAR-30) —
    # tried before the plain-N row (its regex needs a digit, so no overlap).
    EffectHandler(
        "earthbend_x",
        _EARTHBEND_X_RE,
        _earthbend_x,
    ),
    # "earthbend X, where X is that creature's power" (PAR-30, Beifong's
    # Bounty Hunters) — the dying-subject read; also digit-free, no overlap.
    EffectHandler(
        "earthbend_that_creatures_power",
        _EARTHBEND_THAT_CREATURES_POWER_RE,
        _earthbend_that_creatures_power,
    ),
    # "earthbend N" (RULE 701.66, Avatar: TLA) — target land you control
    # becomes a 0/0 haste creature that's still a land + N +1/+1 counters.
    EffectHandler(
        "earthbend",
        _c(r"earthbend (?P<n>\d+)"),
        _earthbend,
    ),
    # "airbend that creature / it" (RULE 701.65) — a trigger-subject pronoun
    # (Monk Gyatso). Before the targeted row: "that creature" has no "target".
    EffectHandler(
        "airbend_trigger_subject",
        _AIRBEND_TRIGGER_SUBJECT_RE,
        _airbend_trigger_subject,
    ),
    # "airbend [up to N] [other] target <X> [you control]" (RULE 701.65,
    # Avatar: TLA) — exile it, its owner may cast it from exile for {2}.
    EffectHandler(
        "airbend",
        _AIRBEND_RE,
        _airbend,
    ),
    # "support N" (RULE 701.41a) — +1/+1 counter on each of up to N target
    # creatures (rides the existing `add_counters` multi-target path).
    EffectHandler(
        "support",
        _c(r"support (?P<n>\d+)"),
        _support,
    ),
    # "support x" (PAR-29) — X is the spell/ability's own announced {X}.
    EffectHandler(
        "support_x",
        _c(r"support x"),
        _support_x,
    ),
    # "goad all creatures your opponents control" (RULE 701.15a) — the mass
    # form first: the targeted row below can't match it (no "target"), but
    # the mass one is the more specific phrase and reads better up here.
    EffectHandler(
        "goad_selector",
        _c(r"goad all creatures (?:your opponents control|you don't control)"),
        _goad_selector,
    ),
    # "for each opponent, goad up to one target creature that player
    # controls" — a per-opponent requirement (RULE 601.2c). Before the plain
    # `goad` row, whose `TARGET` would otherwise claim the tail and silently
    # goad exactly one creature.
    EffectHandler(
        "goad_per_opponent",
        _c(
            r"for each opponent, goad up to 1 target creature "
            r"that (?:player|opponent) controls"
        ),
        _goad_per_opponent,
    ),
    # "goad up to X target creatures your opponents control" (Death Kiss).
    EffectHandler(
        "goad_up_to_x",
        _c(r"goad up to x target creatures (?:your opponents control|you don't control)"),
        _goad_up_to_x,
    ),
    # "goad target creature **that player** controls" (Popular Entertainer's
    # granted trigger, PAR-32 — "that player" = whoever the firing
    # `CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` event named). Tried before
    # the generic `goad {TARGET}` row, whose `resolve_target_kind` doesn't
    # know this event-scoped phrase.
    EffectHandler(
        "goad_that_player",
        _c(r"goad target creature that player controls"),
        lambda m: [EffectSpec("goad", {"target_kind": "creature_that_player_controls"})],
    ),
    # RULE 605.1b: "[that player] add(s) one mana of any type that land produced" (Mana
    # Flare, Mirari's Wake, PAR-119) — the type is read off the firing `TAPPED_FOR_MANA`
    # event's ``produced``; "that player" is whoever tapped the land.
    EffectHandler(
        "mirror_produced_mana",
        _c(r"(?P<that>that player adds|add) 1 mana of any type that (?:land|permanent) produced"),
        lambda m: [EffectSpec("mirror_produced_mana", {
            "count": 1,
            **({"player": {"of": "event_player", "as": "controller"}}
               if m.group("that").startswith("that") else {}),
        })],
    ),
    # "~ becomes a copy of [another] target creature[ until end of turn]."
    # (Cursed Mirror's EOT form; Shameless Charlatan's granted permanent
    # form, PAR-32) — the "another" is enforced by the effect's own
    # `target is self.source` guard, so no distinct target kind is needed.
    EffectHandler(
        "become_copy_of_target",
        _BECOME_COPY_RE,
        _become_copy_of_target,
    ),
    EffectHandler(
        "you_gain_life_eq_that_creature_mv",
        _YOU_GAIN_LIFE_EQ_THAT_CREATURE_MV_RE,
        _you_gain_life_eq_that_creature_mv,
    ),
    EffectHandler(
        "equipped_creature_unblockable",
        _c(r"equipped creature can'?t be blocked this turn"),
        _equipped_creature_unblockable,
    ),
    EffectHandler(
        "self_and_other_unblockable",
        _SELF_AND_OTHER_UNBLOCKABLE_RE,
        _self_and_other_unblockable,
    ),
    EffectHandler(
        "color_creatures_unblockable",
        _COLOR_CREATURES_UNBLOCKABLE_RE,
        _color_creatures_unblockable,
    ),
    EffectHandler("x_power_unblockable", _X_POWER_UNBLOCKABLE_RE, _x_power_unblockable),
    EffectHandler("x_targets_unblockable", _X_TARGETS_UNBLOCKABLE_RE, _x_targets_unblockable),
    # PAR-140: "it becomes a Rogue in addition to its other types" — "it" is the previous clause's pick,
    # so the row is only offered when that clause announced one (`previous_subject_only`).
    EffectHandler(
        "becomes_in_addition_previous", _BECOMES_IN_ADDITION_PREVIOUS_RE, _becomes_in_addition,
        previous_subject_only=True,
    ),
    EffectHandler(
        "becomes_in_addition_self_pronoun", _BECOMES_IN_ADDITION_SELF_PRONOUN_RE, _becomes_in_addition,
        self_subject_only=True,
    ),
    EffectHandler("becomes_in_addition", _BECOMES_IN_ADDITION_RE, _becomes_in_addition),
    EffectHandler(
        "animate_quoted_cda",
        _ANIMATE_QUOTED_CDA_RE,
        _animate_quoted_cda,
    ),
    EffectHandler(
        "animate_self",
        _ANIMATE_SELF_RE,
        _animate_self,
    ),
    EffectHandler(
        "animate_self_leading_eot",
        _ANIMATE_SELF_LEADING_EOT_RE,
        _animate_self_leading_eot,
    ),
    EffectHandler(
        "animate_target",
        _ANIMATE_TARGET_RE,
        _animate_target,
    ),
    EffectHandler(
        "animate_target_leading_eot",
        _ANIMATE_TARGET_LEADING_EOT_RE,
        _animate_target_leading_eot,
    ),
    # "goad target creature [an opponent controls]" (RULE 701.15a).
    EffectHandler(
        "goad",
        _c(rf"goad {TARGET}"),
        _goad,
    ),
    # "the tokens are goaded for the rest of the game" — the tokens an
    # earlier clause of this same ability created (`created_objects`).
    EffectHandler(
        "goad_created",
        _c(r"the tokens? (?:is|are) goaded for the rest of the game"),
        _goad_created,
    ),
    # "it's goaded for the rest of the game" — same duration, previous target.
    EffectHandler(
        "goad_previous_permanent",
        _c(r"(?:it's|that creature is) goaded for the rest of the game"),
        _goad_previous_permanent,
        previous_subject_only=True,
    ),
    # "goad it" / "goad that creature" — the previous clause's target.
    EffectHandler(
        "goad_previous",
        _c(r"goad (?:it|that creature)"),
        _goad_previous,
        previous_subject_only=True,
    ),
    # "all suspected creatures are no longer suspected" (RULE 701.60a's
    # reverse) — before the `suspect {TARGET}` row, which can't match it
    # (no "target") but reads better kept together.
    EffectHandler(
        "remove_suspected_all",
        _c(r"all suspected creatures are no longer suspected"),
        _remove_suspected_all,
    ),
    EffectHandler(
        "suspected_self_counter_or_suspect",
        _c(r"if ~ is suspected, put a \+1/\+1 counter on it\. otherwise, suspect it"),
        _suspected_self_counter_or_suspect,
        self_subject_only=True,
    ),
    # "you may have it become no longer suspected" (RULE 701.60a's reverse,
    # PAR-30 — Deadly Complication) — "it" = the previous clause's target.
    EffectHandler(
        "remove_suspected_may_previous",
        _c(r"you may have it become no longer suspected"),
        _remove_suspected_may_previous,
        previous_subject_only=True,
    ),
    EffectHandler(
        "remove_suspected_previous_selector",
        _c(r"if any of them are suspected, (?:they'?re|they are) no longer suspected"),
        _remove_suspected_previous_selector,
        previous_selector_only=True,
    ),
    # "suspect enchanted creature" (RULE 701.60a) — an Aura's host.
    EffectHandler(
        "suspect_attached",
        _c(r"suspect enchanted creature"),
        _suspect_attached,
    ),
    # Frantic Scapegoat: "the other creatures" are the ones its batch trigger counted
    # (PAR-119, `SuspectEffect` reads the event's ``matching_ids``); "~" is explicit.
    EffectHandler(
        "suspect_other_then_remove_self",
        _c(r"you may suspect 1 of the other creatures\. if you do, ~ is no longer suspected"),
        _suspect_other_then_remove_self,
    ),
    # "suspect [up to N] target creature [an opponent controls]" (RULE 701.60a).
    EffectHandler(
        "suspect_target",
        _c(rf"suspect {TARGET}"),
        _suspect_target,
    ),
    # "suspect it" — explicit self ("when ~ enters, suspect it").
    EffectHandler(
        "suspect_self",
        _c(r"suspect (?:it|~)"),
        _suspect_self,
        self_subject_only=True,
    ),
    # "suspect it" / "suspect that creature" — the previous clause's target
    # ("gain control of target creature … suspect it", Caught Red-Handed).
    EffectHandler(
        "suspect_previous",
        _c(r"suspect (?:it|that creature)"),
        _suspect_previous,
        previous_subject_only=True,
    ),
    # "detain up to two target creatures your opponents control" (RULE
    # 701.35a) — before the singular row, which its `TARGET` can't match
    # (plural) but reads better kept together.
    EffectHandler(
        "detain_multi",
        _DETAIN_MULTI_RE,
        _detain_multi,
    ),
    # "detain [up to one] target creature/nonland permanent an opponent
    # controls" (RULE 701.35a).
    EffectHandler(
        "detain",
        _c(rf"detain {TARGET}"),
        _detain,
    ),
    EffectHandler("manifest_dread_then_attach", _MANIFEST_DREAD_THEN_ATTACH_RE, _manifest_dread_then_attach),
    # "manifest dread" (RULE 701.40a) — tried before the plain manifest row
    # below, which would otherwise not match it at all but reads more
    # naturally kept in this order alongside its sibling.
    EffectHandler(
        "manifest_dread",
        _c(r"manifest dread"),
        _manifest_dread,
    ),
    EffectHandler(
        "reduce_spell_costs_this_turn",
        _REDUCE_COSTS_THIS_TURN_RE,
        _reduce_costs_this_turn,
    ),
    EffectHandler(
        "turn_face_up_chosen",
        _c(r"(?P<may>you may )?turn a (?P<what>permanent|face-down permanent|face-down creature)"
           r" you control face up"),
        _turn_face_up_chosen,
    ),
    # "manifest the top card of your library" / "…the top two cards…" and
    # cloak's identical shape (RULE 701.40a/701.58a).
    EffectHandler(
        "manifest",
        _c(rf"(?P<verb>manifest|cloak) the top (?:{COUNT} )?cards? of your library"),
        _manifest,
    ),
    # "proliferate twice" / "proliferate N times" (RULE 701.30) — tried
    # before the bare `proliferate` row below since it's a strict superset.
    EffectHandler(
        "proliferate_n_times",
        _c(r"proliferate (?:(?P<twice>twice)|(?P<n>\d+) times)"),
        _proliferate_n_times,
    ),
    # "proliferate" (RULE 701.30) — bare.
    EffectHandler(
        "proliferate",
        _c(r"proliferate"),
        _proliferate,
    ),
    # "double the number of [+1/+1] counters on <~ / target creature / each
    # creature you control / it>." (Primordial Hydra / Tanazir Quandrix /
    # Kalonian Hydra / Growth Curve — 27 SOLO).
    EffectHandler(
        "double_counters",
        _DOUBLE_COUNTERS_RE,
        _double_counters,
    ),
    # "Damage can't be prevented this turn." (RULE 615.6)
    EffectHandler(
        "disable_damage_prevention",
        _DISABLE_DAMAGE_PREVENTION_RE,
        _disable_damage_prevention,
    ),
    # "remove all counters from all permanents" (RULE 122 — Oblivion Stone/
    # Aether Snap/Thief of Blood-shaped).
    EffectHandler(
        "remove_counters_all_permanents",
        _c(r"remove all counters from all permanents"),
        _remove_counters_all_permanents,
    ),
    # "remove all counters from target permanent" (Vampire Hexmage-shaped).
    EffectHandler(
        "remove_counters_target",
        _c(r"remove all counters from target permanent"),
        _remove_counters_target,
    ),
    # "remove all `<kind>` counters from ~." (Coalition Relic/Ventifact
    # Bottle) — see `_REMOVE_ALL_NAMED_COUNTERS_SELF_RE`.
    EffectHandler(
        "remove_all_named_counters_self",
        _REMOVE_ALL_NAMED_COUNTERS_SELF_RE,
        _remove_all_named_counters_self,
    ),
    # "remove up to N counters from target permanent/creature" (Glissa
    # Sunslayer/Heartless Act/Render Inert-shaped) — see
    # `_REMOVE_COUNTERS_CHOICE_RE`.
    EffectHandler(
        "remove_counters_choice",
        _REMOVE_COUNTERS_CHOICE_RE,
        _remove_counters_choice,
    ),
    # "You may play an additional land this turn." / "You may play up to
    # two additional lands this turn." (RULE 305.2 one-turn permission) —
    # see `_EXTRA_LAND_PLAY_RE` above; the standing per-turn static sibling
    # is `catalogue.static_handlers`' `extra_land_drop`.
    EffectHandler(
        "extra_land_play",
        _EXTRA_LAND_PLAY_RE,
        _extra_land_play,
    ),
    # "You become the monarch." / "Target player becomes the monarch."
    # (RULE 725.1).
    EffectHandler(
        "become_monarch",
        _c(r"(?P<who>you |target player )?becomes? the monarch"),
        _become_monarch,
    ),
    # "You take the initiative." / "Target player takes the initiative."
    # (RULE 726.1) — RULE 726.2's "venture into the dungeon" companion isn't
    # modeled (dungeons/RULE 309 aren't built yet); see
    # `game/effects/core.py`'s `TakeInitiativeEffect`.
    EffectHandler(
        "take_initiative",
        _c(r"(?P<who>you |target player )?takes? the initiative"),
        _take_initiative,
    ),
    # "You get an emblem with '<ability>'." (RULE 114.2) — see
    # `_emblem_ability_spec` above.
    EffectHandler(
        "create_emblem",
        _EMBLEM_RE,
        _create_emblem,
    ),
    # "Create that many 1/1 green Elf Warrior creature tokens." (Lathril,
    # Blade of the Elves-shaped) — tried before the plain `create_token`
    # row below, same "strict superset" reasoning.
    EffectHandler(
        "create_token_that_many",
        _CREATE_TOKEN_THAT_MANY_RE,
        _create_token_that_many,
    ),
    # "Create a 1/1 green Elf Warrior creature token for each Elf you
    # control." (Elvish Promenade-shaped) — tried before the plain
    # `create_token` row below since it's a strict superset of that shape.
    EffectHandler(
        "create_token_for_each",
        _CREATE_TOKEN_FOR_EACH_RE,
        _create_token_for_each,
    ),
    # "Create X 1/1 green Elf Warrior creature tokens, where X is the
    # number of attacking creatures." (Galadhrim Ambush-shaped).
    EffectHandler(
        "create_token_xx_source_power",
        _CREATE_TOKEN_XX_SOURCE_POWER_RE,
        _create_token_xx_source_power,
    ),
    EffectHandler(
        "create_token_xx_where",
        _CREATE_TOKEN_XX_WHERE_RE,
        _create_token_xx_where,
    ),
    # RULE 202.2f/700.6 "create a number of 1/1 white Soldier creature
    # tokens equal to your devotion to white." (Evangel of Heliod/Master of
    # Waves-shaped) — tried before the plain `create_token` row below, same
    # "strict superset" reasoning as the two rows above.
    EffectHandler(
        "create_token_number_equal_devotion",
        _CREATE_TOKEN_NUMBER_EQUAL_DEVOTION_RE,
        _create_token_number_equal_devotion,
    ),
    # "create a 1/1 white Soldier creature token" / "create two 2/2 green Bear
    # creature tokens with trample" — inline creature tokens (fully modeled).
    EffectHandler(
        "create_token_quoted_cda",
        _CREATE_TOKEN_QUOTED_CDA_RE,
        _create_token_quoted_cda,
    ),
    EffectHandler(
        "create_token",
        _c(
            rf"(?P<per_opp>for each opponent, )?(?:(?P<who>you|each player|each opponent|target player|target opponent) )?creates? {COUNT_X} "
            rf"(?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
            rf"(?P<mid>[a-z ]*?)creature tokens?"
            # ``0-9`` in the keyword capture is ENG-31's "… token with
            # firebending N" (Fire Nation Attacks/Occupation).
            rf"(?: with (?P<kw>[a-z0-9, ]+))?"
            # "…creature token with \"when ~ dies, you gain N life.\"" — the
            # STX Pest token's own printed death trigger (Blight Mound,
            # Feral Appetite, Pest Rescuer, Hunt for Specimens, …). Baked
            # onto each token via `CreateTokenEffect.token_dies_gain_life`.
            rf'(?: with "when (?:~|it) dies, you gain (?P<dies_life>\d+) life\.?")?'
            + rf'(?: (?:with|and) "(?P<quoted_cda>(?:this token|this creature|~)\'?s power[^\"]+)")?'
            # PAR-122: "…token that's all colors" (The Fish Brewer) — RULE 105.1's five colors.
            + r"(?P<all_colors> that'?s all colors| that are all colors)?"
            + _TOKEN_TAPPED_ATTACKING
        ),
        _create_token,
    ),
    EffectHandler(
        "create_named_token_quoted_cda",
        _CREATE_NAMED_TOKEN_QUOTED_CDA_RE,
        _create_named_token_quoted_cda,
    ),
    # PAR-13: "Create <Name>, a legendary N/N ... creature token [with
    # <keywords>]." — Cradle of the Death God's own unique Atropal token.
    EffectHandler(
        "create_named_legendary_token",
        _CREATE_NAMED_LEGENDARY_TOKEN_RE,
        _create_named_legendary_token,
    ),
    # "create a Food token, then create a 1/1 white Halfling creature token
    # and attach ~ to it." (Field-Tested Frying Pan) — tried before the
    # plain create-and-attach row below since it's a strict superset (a
    # leading named-token sentence that row's grammar doesn't expect).
    EffectHandler(
        "create_named_then_create_token_and_attach",
        _CREATE_NAMED_THEN_CREATE_TOKEN_AND_ATTACH_RE,
        _create_named_then_create_token_and_attach,
    ),
    # "create a 1/1 white Halfling creature token and attach ~ to it."
    # (Auxiliary Boosters, Living Weapon-adjacent) — the token, then attach
    # the ability's own source onto whatever that just made.
    EffectHandler(
        "create_token_and_attach",
        _CREATE_TOKEN_AND_ATTACH_RE,
        _create_token_and_attach,
    ),
    # "create a Treasure token" / "create two Clue tokens" — named,
    # non-creature artifact tokens (`_NAMED_TOKEN_WORDS`, kept in sync with
    # `data/tokens.json`).
    EffectHandler(
        "create_named_token_that_many",
        _CREATE_NAMED_TOKEN_THAT_MANY_RE,
        _create_named_token_that_many,
    ),
    EffectHandler(
        "create_named_token_per_counter_on_it",
        _CREATE_NAMED_TOKEN_PER_COUNTER_ON_IT_RE,
        _create_named_token_per_counter_on_it,
        group_subject_only=True,
    ),
    EffectHandler(
        "create_named_token",
        _c(rf"(?P<who>you |target player |each opponent |each player )?"
           rf"creates? {COUNT} (?P<tapped>tapped )?(?P<name>{'|'.join(_NAMED_TOKEN_WORDS)}) tokens?"),
        _create_named_token,
    ),
    # "create a number of tapped Treasure tokens equal to its power."
    # (Goldvein Hydra) — tried before the flat-count row above (its `COUNT`
    # can't match "a number of … equal to …").
    EffectHandler(
        "create_named_token_eq_its_self",
        _CREATE_NAMED_TOKEN_EQ_ITS_RE,
        _create_named_token_eq_its_self,
        self_subject_only=True,
    ),
    # "Investigate." / "Investigate twice." / "Investigate 3 times." (RULE
    # 701.19a) — a Clue-token-creation alias.
    EffectHandler(
        "investigate",
        _INVESTIGATE_RE,
        _investigate,
    ),
    # "The Ring tempts you." (RULE 701.51a) — Tales of Middle-earth.
    EffectHandler(
        "ring_tempts_you",
        _RING_TEMPTS_YOU_RE,
        _ring_tempts_you,
    ),
    # "[You may c]ast [sorcery/creature ]spells this turn as though they had
    # flash." (Emergence Zone-shaped, MEC-12; Complete the Circuit's own
    # "sorcery spells" narrowing, PAR-124 — the leading "you may" is already
    # peeled off by `segmenter._peel_optional` before a clause ever reaches
    # this table) — `effects.GrantFlashUntilEndOfTurnEffect.card_types` now
    # carries the optional type-word filter through to `GameState.temp_
    # flash_until_turn_types`.
    EffectHandler(
        "grant_flash_until_eot",
        _c(r"cast (?:(?P<kind>sorcery|creature) )?spells this turn as though they had flash"),
        lambda m: [EffectSpec("grant_flash_until_eot", (
            {"card_types": [m.group("kind")]} if m.group("kind") else {}
        ))],
    ),
    # PAR-72: Party generalized into a resolve-time amount (see the
    # dedicated section above `HANDLERS`) — one row per distinct verb the
    # fixed "for each creature in your party"/"the number of creatures in
    # your party" phrase appears on.
    EffectHandler("add_mana_party", _ADD_MANA_PARTY_RE, _add_mana_party),
    EffectHandler("add_counters_self_party", _ADD_COUNTERS_SELF_PARTY_RE, _add_counters_self_party),
    EffectHandler(
        "choose_target_add_counters_party",
        _CHOOSE_TARGET_ADD_COUNTERS_PARTY_RE, _choose_target_add_counters_party,
    ),
    EffectHandler("pump_self_power_party", _PUMP_SELF_POWER_PARTY_RE, _pump_self_power_party),
    EffectHandler("pump_target_both_party", _PUMP_TARGET_BOTH_PARTY_RE, _pump_target_both_party),
    EffectHandler("pump_up_to_two_party", _PUMP_UP_TO_TWO_PARTY_RE, _pump_up_to_two_party),
    EffectHandler(
        "pump_target_opponent_negative_party",
        _PUMP_TARGET_OPPONENT_NEGATIVE_PARTY_RE, _pump_target_opponent_negative_party,
    ),
    EffectHandler("gain_life_party", _GAIN_LIFE_PARTY_RE, _gain_life_party),
    EffectHandler("create_token_party", _CREATE_TOKEN_PARTY_RE, _create_token_party),
    EffectHandler("scry_party", _SCRY_PARTY_RE, _scry_party),
    EffectHandler(
        "lose_life_and_gain_life_party",
        _LOSE_LIFE_AND_GAIN_LIFE_PARTY_RE, _lose_life_and_gain_life_party,
    ),
    EffectHandler(
        "damage_attacking_or_blocking_twice_party",
        _DAMAGE_ATTACKING_OR_BLOCKING_TWICE_PARTY_RE, _damage_attacking_or_blocking_twice_party,
    ),
    EffectHandler("look_top_put_three_party", _LOOK_TOP_PUT_THREE_PARTY_RE, _look_top_put_three_party),
    EffectHandler("reveal_top_all_filter", _REVEAL_TOP_ALL_FILTER_RE, _reveal_top_all_filter),
    EffectHandler("dig_top_choose", _DIG_RE, _dig),
    EffectHandler(
        "damage_target_and_controller_party",
        _DAMAGE_TARGET_AND_CONTROLLER_PARTY_RE, _damage_target_and_controller_party,
    ),
    EffectHandler("damage_target_party", _DAMAGE_TARGET_PARTY_RE, _damage_target_party),
    EffectHandler("burakos_attack_party", _BURAKOS_ATTACK_PARTY_RE, _burakos_attack_party),
]


#: "that creature's controller" / "that land's power" — under a group trigger the same possessive
#: as "its", so every "its …" row serves both spellings.
_THAT_OBJECTS_POSSESSIVE_RE = re.compile(rf"\bthat {PRONOUN_NOUN_ALT}'s\b")

#: "that hero" / "that sliver" — a creature subtype naming the firing object.
_THAT_SUBTYPE_RE = re.compile(rf"\bthat (?!creature\b|permanent\b|artifact\b|land\b|token\b){PRONOUN_NOUN_ALT}\b")

_THAT_CREATURE_RE = re.compile(r"\bthat creature\b")

#: "…target creature you control **other than that creature**" — the group trigger's firing object.
_OTHER_THAN_THAT_RE = re.compile(rf"\s+other than (?:it|that {PRONOUN_NOUN_ALT})$")

#: A plural referent ("put a counter on each of **those** creatures") names a group, which the
#: one object a group trigger fired for cannot stand for.
_PLURAL_PRONOUN_RE = re.compile(r"\b(?:those|them|they|these|each of)\b")


#: Whether the clause `match_clause` is reading right now sits under a group trigger — for the
#: builders (`_pay_cost_then_general`) that parse a sub-clause of their own and must give it the
#: same reading, and are handed only a regex match.
_GROUP_CLAUSE: contextvars.ContextVar[bool] = contextvars.ContextVar("par123_group_clause", default=False)


def match_clause(
    clause: str, *, self_subject: bool = False, previous_subject: bool = False,
    group_subject: bool = False, previous_selector: bool = False,
    attached_subject: bool = False,
) -> Optional[list[EffectSpec]]:
    """The `EffectSpec`s for one normalised effect ``clause``, or ``None``.

    Runs the handler table; the first handler to claim the whole clause wins.
    ``None`` means no handler modeled it — the clause is unclaimed and its card
    will fail the coverage gate (docs/09 fail-closed).

    ``self_subject`` says the clause's bare "it" is the ability's own source;
    ``previous_subject`` says it is the creature the *preceding* clause of
    the same body chose; ``group_subject`` says it is whichever object
    matched this ability's own RULE 603.1 group-subject trigger condition;
    ``previous_selector`` says "they" is the group a mass selector in the
    preceding clause acted on; ``attached_subject`` (PAR-117) says "its" is
    RULE 303.4/301.5's attached host — this ability's own trigger condition
    is ``{"subject": "attached_permanent"}``. Each unlocks its own gated rows
    (see `EffectHandler.self_subject_only`/``previous_subject_only``/
    ``group_subject_only``/``previous_selector_only``/``attached_subject_
    only``); with none set — the default, and the only reading available to a
    clause standing alone — a pronoun claims nothing at all.

    PAR-123: a group-subject clause no row claims outright is tried once more as though
    its pronoun named an earlier clause's pick, and the firing object is then made that
    pick (`trigger_subject_referent`) — "it"/"that creature" under a RULE 603.1 group
    trigger *is* an object nothing chose, and every effect with a previous-subject reading
    ("it explores", "it fights …", "that creature endures N") already reads the pick from
    `GameContext.previous_targets`. Rows written for the group subject itself win first, so
    nothing they claim changes reading.
    """
    token = _GROUP_CLAUSE.set(group_subject and not previous_subject and not self_subject)
    try:
        return _match_clause_reading(
            clause, self_subject=self_subject, previous_subject=previous_subject,
            group_subject=group_subject, previous_selector=previous_selector,
            attached_subject=attached_subject,
        )
    finally:
        _GROUP_CLAUSE.reset(token)


def _match_clause_reading(
    clause: str, *, self_subject: bool, previous_subject: bool, group_subject: bool,
    previous_selector: bool, attached_subject: bool,
) -> Optional[list[EffectSpec]]:
    other_than = _OTHER_THAN_THAT_RE.search(clause) if group_subject else None
    if other_than is not None:
        # "put a +1/+1 counter on target creature you control **other than that creature**": the
        # firing object is excluded from the choice, whatever verb the clause has.
        effects = _match_clause_reading(
            clause[:other_than.start()], self_subject=self_subject, previous_subject=previous_subject,
            group_subject=group_subject, previous_selector=previous_selector,
            attached_subject=attached_subject,
        )
        if effects is None or not any(e.params.get("target_kind") for e in effects):
            return None
        return [
            EffectSpec(e.type, {**e.params, "excluding_trigger_subject": True}, condition=e.condition)
            if e.params.get("target_kind") else e
            for e in effects
        ]
    if group_subject and _THAT_CREATURE_RE.search(clause) is None:
        # "that hero"/"that sliver" under a group trigger for that subtype is "that creature" —
        # unless the clause also says "that creature", which would then be a *second* object
        # ("that archer deals that much damage to that creature's controller").
        clause = _THAT_SUBTYPE_RE.sub("that creature", clause)
    effects = _match_clause_once(
        clause, self_subject=self_subject, previous_subject=previous_subject,
        group_subject=group_subject, previous_selector=previous_selector,
        attached_subject=attached_subject,
    )
    if effects is None and group_subject and _THAT_OBJECTS_POSSESSIVE_RE.search(clause):
        clause = _THAT_OBJECTS_POSSESSIVE_RE.sub("its", clause)
        effects = _match_clause_once(clause, group_subject=True)
    if effects is None and group_subject and not previous_subject and _PLURAL_PRONOUN_RE.search(clause) is None:
        effects = _match_clause_once(clause, previous_subject=True)
        if effects is not None:
            return [EffectSpec("trigger_subject_referent", {"event_key": GROUP_SUBJECT_KEY_SENTINEL}), *effects]
        return _group_pronoun_as_target(clause) or _group_controller_as_you(clause)
    return effects


#: The object pronoun of a group-trigger clause ("destroy **it**", "put a counter on **that
#: creature**") — not the possessive "its"/"it's".
_OBJECT_PRONOUN_RE = re.compile(rf"\b(?:it|that {PRONOUN_NOUN_ALT})\b(?!')")


#: Nested effect bodies that hand their ``targets`` on to what they contain. Any other body
#: (a payment's "if you do", a "you may", a delayed trigger) runs later or elsewhere, without
#: the firing object the wrapper supplies.
_TARGET_PASSING_NODES = frozenset({"bind", "seq", "if_else"})


def _runs_against_targets(spec: Any) -> bool:
    """Whether every effect nested in ``spec`` is run with the ``targets`` its parent got."""
    if isinstance(spec, dict):
        nested = isinstance(spec.get("type"), str) and "params" in spec
        if nested and any(_has_nested_spec(v) for v in spec["params"].values()) and (
            spec["type"] not in _TARGET_PASSING_NODES
        ):
            return False
        return all(_runs_against_targets(v) for v in spec.values())
    if isinstance(spec, list):
        return all(_runs_against_targets(v) for v in spec)
    return True


def _has_nested_spec(value: Any) -> bool:
    if isinstance(value, dict):
        return (isinstance(value.get("type"), str) and "params" in value) or any(
            _has_nested_spec(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_nested_spec(v) for v in value)
    return False


#: "**its controller**" / "**that creature's controller**" — the player who controls the object a
#: group trigger fired for — with the verb that follows it, if any.
_CONTROLLER_PRONOUN_RE = re.compile(
    rf"\b(?:its|that {PRONOUN_NOUN_ALT}'s) controller(?P<poss>'s)?(?: (?P<verb>[a-z]+))?"
)

#: Third-person verbs that do not just drop their "s"/"es" to reach the base form.
_IRREGULAR_BASE_VERBS = {"has": "have", "does": "do"}


def _base_verb(word: str) -> str:
    if word in _IRREGULAR_BASE_VERBS:
        return _IRREGULAR_BASE_VERBS[word]
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    return word[:-1] if word.endswith("s") else word


#: The effect types that read "you" through `GameContext.acting_player_id` (`_controller_of`,
#: `effect_conditions._controller_id`, or directly), each pinned by `test_par123_referent.py`. An
#: effect that resolves "you" some other way would quietly act for the wrong player, so the rewrite
#: is offered only for these.
_ACTING_AS_CONTROLLER_TYPES: frozenset[str] = frozenset({
    "damage", "create_token", "tap", "add_player_counters", "draw", "lose_life", "gain_life",
})


def _group_controller_as_you(clause: str) -> Optional[list[EffectSpec]]:
    """PAR-123: "its controller creates a 1/1 Snake token" is "you create a 1/1 Snake token"
    done by the firing object's controller (RULE 109.5). The clause is read as its second-person
    form and run acting as that player (`trigger_subject_referent` ``acting``), so every effect
    with a "you" reading gains the "its controller" one — creating, sacrificing, drawing, tapping
    "lands you control" — without a row of its own.

    Refused when the clause names another player or carries a second pronoun (the two would
    need to be told apart), and when the effect would run later than this resolution."""
    found = list(_CONTROLLER_PRONOUN_RE.finditer(clause))
    if len(found) != 1 or _OBJECT_PRONOUN_RE.search(clause) or re.search(r"\b(?:you|your|target)\b", clause):
        return None
    hit = found[0]
    verb = hit.group("verb")
    if hit.group("poss"):
        replacement = "your" + (f" {verb}" if verb else "")
    elif verb == "may":
        replacement = "you may"
    elif verb:
        replacement = f"you {_base_verb(verb)}"
    else:
        replacement = "you"
    rewritten = clause[:hit.start()] + replacement + clause[hit.end():]
    rewritten = re.sub(r"\bof their choice\b", "of your choice", rewritten)
    rewritten = re.sub(r"\btheir\b", "your", rewritten)
    effects = _match_clause_once(rewritten)
    if (
        effects is None or not all(_runs_against_targets(e.to_dict()) for e in effects)
        or not all(e.type in _ACTING_AS_CONTROLLER_TYPES for e in effects)
    ):
        return None
    return [EffectSpec("trigger_subject_referent", {
        "event_key": GROUP_SUBJECT_KEY_SENTINEL, "acting": "controller",
        "effects": [e.to_dict() for e in effects],
    })]


def _group_pronoun_as_target(clause: str) -> Optional[list[EffectSpec]]:
    """PAR-123: a group trigger's bare "it"/"that creature" read through the *targeted* form of
    the same clause. "destroy it" is "destroy target permanent" whose one target the trigger
    already fixed, so any effect that has a targeted row gains the firing-object reading with no
    row of its own: the clause is parsed with the pronoun spelled as a target, and the result
    runs against the firing object (`trigger_subject_referent`'s body) instead of a chosen one.

    Refused unless the pronoun is the clause's *only* possible target — a second "target"
    ("it fights target creature you don't control") would be hidden by the wrapper, which
    announces none — and only for the creature/permanent spellings, the objects a group
    trigger fires for."""
    pronouns = _OBJECT_PRONOUN_RE.findall(clause)
    if len(pronouns) != 1 or "target" in clause:
        return None
    noun = re.match(r"that (creature|permanent|artifact|land|token)$", pronouns[0])
    # A creature that died is a card in a graveyard by the time the trigger resolves (RULE 603.10a).
    for kind in dict.fromkeys(
        ((noun.group(1) if noun else "creature"), "creature", "permanent", "card from a graveyard")
    ):
        rewritten = _OBJECT_PRONOUN_RE.sub(f"target {kind}", clause)
        effects = _match_clause_once(rewritten)
        if effects is not None and all(_runs_against_targets(e.to_dict()) for e in effects):
            return [EffectSpec("trigger_subject_referent", {
                "event_key": GROUP_SUBJECT_KEY_SENTINEL,
                "effects": [e.to_dict() for e in effects],
            })]
    return None


def _match_clause_once(
    clause: str, *, self_subject: bool = False, previous_subject: bool = False,
    group_subject: bool = False, previous_selector: bool = False,
    attached_subject: bool = False,
) -> Optional[list[EffectSpec]]:
    for handler in HANDLERS:
        if handler.self_subject_only and not self_subject:
            continue
        if handler.previous_subject_only and not previous_subject:
            continue
        if handler.group_subject_only and not group_subject:
            continue
        if handler.previous_selector_only and not previous_selector:
            continue
        if handler.attached_subject_only and not attached_subject:
            continue
        effects = handler.match(clause)
        if effects is not None:
            return effects
    flags = dict(
        self_subject=self_subject, previous_subject=previous_subject,
        group_subject=group_subject, previous_selector=previous_selector,
        attached_subject=attached_subject,
    )
    return _perpetual_pump_specs(clause, **flags) or _per_player_target_specs(clause, **flags)


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


def _per_player_target_specs(clause: str, **flags: bool) -> Optional[list[EffectSpec]]:
    m = _PER_PLAYER_RE.fullmatch(clause.strip())
    if m is None:
        return None
    body = m.group("body")
    if _PER_PLAYER_BODY_RIVAL_RE.search(body.split("that player", 1)[0]):
        return None
    specs = match_clause(body, **flags)
    if not specs:
        return None
    specs = copy.deepcopy(specs)
    if not _stamp_per_player(specs, _PER_PLAYER_SCOPE[m.group("who")]):
        return None
    return specs


# -- MEC-98: Alchemy "perpetually" P/T + keyword changes ---------------------
#
# "<subject> perpetually gets +N/+N [and gains <kw>]" / "… perpetually gains
# <kw>" is an until-end-of-turn pump in every respect but its duration, so
# rather than duplicating the ~40 pump rows' subject/amount/keyword grammar
# this rewrites the clause into its "… until end of turn" form, runs the
# ordinary table on that, and flips the resulting `pump` specs to
# ``perpetual``. Fail-closed: only a result made purely of plain pumps is
# accepted (an "and can't be blocked this turn" rider has no perpetual
# meaning). The off-battlefield subjects ("creature cards in your hand,
# library, and graveyard") no pump row knows get their own grammar below,
# borrowing only the amount/keyword half from the same rewrite.

_PERPETUAL_RE = re.compile(
    r"(?P<subj>.+?) perpetually (?P<verb>gets?|gains?) (?P<rest>.+?)\.?"
)
#: A trailing "where x is …" has to stay *after* the inserted duration.
_PERPETUAL_WHERE_RE = re.compile(r"(?P<head>.+?)(?P<tail>,? where x is .+)")
#: Pump params that have no perpetual reading — a spec carrying one is refused.
_PERPETUAL_REFUSED_PARAMS = (
    "unblockable",
    "parametric_keywords",
    "removed_keywords",
)
#: "creatures you control and creature cards in your hand, library, and
#: graveyard" / "creature cards in your hand" / "each creature card in your
#: graveyard".
_PERPETUAL_ZONE_SUBJECT_RE = re.compile(
    r"(?:(?P<bf>creatures you control) and )?(?:each )?creature cards? in your "
    r"(?P<zones>(?:hand|library|graveyard)(?:(?:,| and|, and) (?:hand|library|graveyard))*)"
)
_PERPETUAL_ZONE_WORDS = ("hand", "library", "graveyard")


def _perpetual_pump_specs(clause: str, **flags: bool) -> Optional[list[EffectSpec]]:
    m = _PERPETUAL_RE.fullmatch(clause.strip())
    if m is None:
        return None
    verb = m.group("verb")
    if not verb.endswith("s"):
        verb += "s"  # plural subject ("… cards perpetually get") → singular pump row
    rest = m.group("rest")
    where = _PERPETUAL_WHERE_RE.fullmatch(rest)
    if where is not None:
        rest_eot = f"{where.group('head')} until end of turn{where.group('tail')}"
    else:
        rest_eot = f"{rest} until end of turn"

    zone = _PERPETUAL_ZONE_SUBJECT_RE.fullmatch(m.group("subj"))
    if zone is not None:
        body = match_clause(f"target creature {verb} {rest_eot}")
        base = _perpetual_flip(body)
        if base is None or len(base) != 1 or where is not None:
            return None
        params = {
            k: v for k, v in base[0].params.items()
            if k in ("power", "toughness", "keywords", "perpetual")
        }
        params["card_zones"] = [
            w for w in _PERPETUAL_ZONE_WORDS if w in zone.group("zones")
        ]
        params["card_type"] = "creature"
        if zone.group("bf"):
            params["selector"] = "creatures_you_control"
        return [EffectSpec("pump", params)]

    subj = m.group("subj")
    plural_verb = m.group("verb") in ("get", "gain")
    rewritten = f"{subj} {m.group('verb') if plural_verb else verb} {rest_eot}"
    return _perpetual_flip(match_clause(rewritten, **flags))


def _perpetual_flip(specs: Optional[list[EffectSpec]]) -> Optional[list[EffectSpec]]:
    if not specs:
        return None
    out: list[EffectSpec] = []
    for spec in specs:
        if spec.type != "pump" or any(spec.params.get(k) for k in _PERPETUAL_REFUSED_PARAMS):
            return None
        out.append(EffectSpec("pump", {**spec.params, "perpetual": True}))
    return out
