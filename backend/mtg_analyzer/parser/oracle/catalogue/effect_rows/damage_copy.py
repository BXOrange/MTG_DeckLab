"""Amass, copy-permanent, damage and damage-prevention rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import copy
import re

from typing import Any, Optional
from ..count_phrase import parse_count_phrase
from ..quantifier_scope import object_set
from ..characteristic_phrase import parse_object_phrase
from ..referent_condition import PRONOUN_NOUN_ALT
from ..static_handlers import type_addition_params
from ..subgrammars import (
    COLOR_WORD_ALT,
    count_or_x_of,
    COUNT_X,
    DEVOTION,
    NOT_YOU_TARGET_KINDS,
    NUMBER,
    resolve_color_word,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    SELF_SUBJECT_PREFIX,
    TARGET,
    target_adjective_filter,
    target_is_optional,
    target_kind_allowed,
)
from ..subtype_vocabulary import SUBTYPES
from ...spec import EffectSpec
from ..clause_hooks import match_clause, match_clause_once
from ..clause_reading import ClauseReading
from .shared import (
    ANY_NUMBER_TARGET_CAP,
    BECOMES_TARGET_EVENT,
    compile_clause,
    CREATURE_FILTER_SCOPED,
    creature_quality_filter,
    DAMAGE_GROUP_PLAYER_TAILS,
    damaged_creature_kind,
    DAMAGED_THIS_TURN_TAIL,
    DELAYED_TAIL_INNER,
    EffectHandler,
    EVENT_PLAYER_EVENTS_KEY,
    MULTI_TARGET_ALT,
    multi_target_params,
    MULTI_TARGET_QUANTIFIER,
    MULTI_TARGET_SCOPE_TAIL,
    MULTI_TARGET_YOU_KINDS,
    NONCREATURE_SUBTYPE_WORDS,
    optional_param,
    scoped_creature_kind,
    selector_devotion_builder,
    SELECTOR_WORD_MAP,
    SINGULAR_GROUP_HEADS,
    split_token_mid_words,
    token_keywords,
    UNLESS_COST,
)


def _targeted_damage(m: re.Match[str], **amount: Any) -> Optional[list[EffectSpec]]:
    """The one `damage` spec every "deals `<amount>` damage to `<target>`" row emits (PAR-121): the amount
    it names, the resolved target kind, "up to one", and the creature qualifier `resolve_target_kind`
    discards ("deals N damage to target **tapped** creature", "…to any target **that isn't a Dinosaur**"),
    merged here once instead of in a copy per amount spelling."""
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    params: dict = {**amount, "target_kind": kind, **optional_param(m)}
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


_DAMAGE_X_SOURCE_COUNTERS_RE = compile_clause(
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
_DAMAGE_X_DEFENDING_PLAYER_HAND_RE = compile_clause(
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
_DAMAGE_TO_SUBJECT_CONTROLLER_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}(?:also )?deals? "
    r"(?P<n>\d+|x) damage to (?:that|the) (?:creature|permanent|artifact|land|enchantment)'?s controller"
)


#: "~ deals N damage to **the player or planeswalker it's attacking**" (Hellrider, Cavalcade of Calamity,
#: Raid Bombardment) — what the attacker that fired the trigger was declared against. A group-subject
#: row: "it"/"that creature" is the attacker (`DealDamageEffect.recipient_subject`).
_DAMAGE_TO_ATTACKED_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to the player or planeswalker "
    r"(?:it'?s|that creature is|that creature'?s) attacking"
)


#: "**it** deals N damage to its controller" / "**that archer** deals that much damage to that
#: creature's controller" (Vengeful Ancestor, Greatbow Doyen) — the firing object is the *dealer*
#: (`segmenter._stamp_damage_dealer` names it from the sentinel) and its controller the recipient.
_GROUP_DEALS_TO_ITS_CONTROLLER_RE = compile_clause(
    r"(?:it|that creature) deals? (?:(?P<n>\d+)|(?P<much>that much)) damage to "
    r"(?:its|that creature'?s) controller"
)


#: "**that archer** deals that much damage to **that creature's** controller" (Greatbow Doyen) — two
#: different objects: the dealer is the firing creature, "that creature" the one the damage went to.
_GROUP_DEALS_TO_DAMAGED_CONTROLLER_RE = compile_clause(
    rf"that (?!creature\b){PRONOUN_NOUN_ALT} deals? that much damage to that creature'?s controller"
)


#: PAR-132: an Aura's own damage-echo trigger. "whenever enchanted creature is dealt / deals damage, ~ deals that much
#: damage to that creature['s controller]" (Binding Agony, Backfire, Guilty Conscience) and "... it deals that much
#: damage to its controller" (Spiteful Shadows): "that creature" / "it" is the Aura's host (RULE 303.4), "that much" the
#: firing event's own damage ``amount``. The Aura (or, for "it deals", the host) is the damage's source.
_ATTACHED_DEALS_THAT_MUCH_RE = compile_clause(
    r"(?:~|this [a-z]+) deals that much damage to (?P<who>that creature'?s controller|that creature)"
)
_ATTACHED_IT_DEALS_THAT_MUCH_RE = compile_clause(r"it deals that much damage to its controller")


def _attached_deals_that_much(m: re.Match[str]) -> list[EffectSpec]:
    recipient = "attached_permanent_object" if m.group("who") == "that creature" else "attached_permanent_controller"
    return [EffectSpec("damage", {"recipient_subject": recipient, "amount_from_trigger_event": "amount"})]


def _attached_it_deals_that_much(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "recipient_subject": "attached_permanent_controller", "dealer_subject": "attached_permanent",
        "amount_from_trigger_event": "amount",
    })]


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
        "amount": count_or_x_of(m.group("n")), "recipient_subject": "previous_subject_controller",
    })]


#: PAR-147: "~ deals N damage to **that creature**" - the creature an earlier clause (or a results table's
#: "choose target creature, then roll" header) chose, not its controller. Offered only after such a clause
#: (`previous_subject_only`); `DealDamageEffect.recipient_subject="previous_subject_object"` damages it only while
#: it is still a battlefield permanent.
_DAMAGE_TO_PREV_OBJECT_RE = compile_clause(
    r"(?:~|this [a-z]+) deals? (?P<n>\d+) damage to (?:that (?:creature|permanent|planeswalker)|it)"
)


def _damage_to_prev_object(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {"amount": int(m.group("n")), "recipient_subject": "previous_subject_object"})]


def _damage_to_trigger_subject_controller(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": count_or_x_of(m.group("n")), "recipient_subject": "trigger_subject_controller",
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

_DAMAGE_KICKED_OVERRIDE_RE = compile_clause(
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
        "target_kind": kind, **optional_param(m),
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
        colors, subtypes, is_artifact = split_token_mid_words(mid)
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
            keywords = token_keywords(pt.group("kw"))
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
def parse_copy_except_tail(tail: str) -> Optional[dict]:
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


#: The trailing state of a copy that is put onto the battlefield attacking (RULE 508.4): "…a copy of that card
#: **and that's tapped and attacking**" (Gyrus), "…copies of it **and that are tapped and attacking**" (Nacatl
#: War-Pride); the leading "create a tapped and attacking token" spelling is `_COPY_HEAD`'s own ``ta``/``tb``.
_COPY_AND_TA = r"(?P<and_ta> and that(?:'s| are) tapped and attacking)?"


#: RULE 707/706.2's "create a token that's a copy of target X[, except
#: <modifier>[, <modifier>...][ and <modifier>]]" (Cackling Counterpart/
#: Rite of Replication/Multiversal Recruitment/Impostor Syndrome-shaped) —
#: the bare form and every safely-generalizable "except" tail
#: (`_parse_copy_except_tail`) share one row; an "except" tail with even one
#: unrecognised modifier still fails the whole clause closed rather than
#: silently dropping it.
_COPY_PERMANENT_RE = compile_clause(
    # The comma before "except" is optional: "a copy of that creature except it's an artifact" (Faerie Artisans).
    # PAR-148: "…a copy of another target attacking creature **and that's tapped and attacking**" (Flamerush Rider).
    rf"{_COPY_HEAD}{TARGET}{_COPY_AND_TA}(?:,?\s+except (?P<except_tail>.+))?"
)

#: PAR-142: the granted end-step clause of a temporary copy — "…except it has haste and \"at the beginning of the
#: end step, sacrifice ~.\"" (Minion Reflector, Kindle the Inner Flame, Electroduplicate; "exile ~" on Heat
#: Shimmer). The same delayed trigger the sentence form "sacrifice it at the beginning of the next end step"
#: (Kiki-Jiki) emits, on the object the copy made — so the grant is modelled as that delayed trigger, not a
#: granted ability on the token.
#: PAR-153 (Delina, Wild Mage): the same grant timed "at end of combat" (RULE 511.2) -- ``when`` tells them apart.
_COPY_END_STEP_GRANT_RE = re.compile(
    r'(?:,? and |, )(?:it has )?"at (?P<when>the beginning of the end step|end of combat), (?P<verb>sacrifice|exile) ~\.?"\s*$',
    re.IGNORECASE,
)


def _copy_with_tail(params: dict, tail: Optional[str]) -> Optional[list[EffectSpec]]:
    """The `copy_permanent` spec for ``params`` with a copy-"except" ``tail`` folded in (PAR-142): the parsed
    modifiers, and — for a granted end-step clause — the delayed trigger that ends the copy. ``None`` (fail
    closed) when any piece of the tail is unrecognised."""
    delayed: Optional[str] = None
    step = "end"
    if tail:
        grant = _COPY_END_STEP_GRANT_RE.search(tail)
        if grant is not None:
            delayed = grant.group("verb").lower()
            if grant.group("when").lower() == "end of combat":
                step = "end_combat"
            tail = tail[: grant.start()]
        extra = parse_copy_except_tail(tail) if tail.strip() else {}
        if extra is None:
            return None
        params.update(extra)
    specs = [EffectSpec("copy_permanent", params)]
    if delayed is not None:
        specs.append(EffectSpec("create_delayed_trigger", {
            "step": step, "scope": "any",
            # An end-of-combat grant ends the copy this clause made, never the creature it copied.
            "capture": "created_objects" if step == "end_combat" else "previous_or_self",
            "effects": [{"type": DELAYED_TAIL_INNER[delayed], "params": {}}],
        }))
    return specs


def _copy_permanent(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    head = _copy_head_params(m)
    if head is None:
        return None
    params: dict = {"target_kind": kind, **optional_param(m), **head}
    if m.groupdict().get("and_ta"):
        params["tapped"] = True
        params["attacking"] = True
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter  # "target nonlegendary creature" (Kiki-Jiki)
    return _copy_with_tail(params, m.groupdict().get("except_tail"))


#: PAR-153: the noun-phrase axis of a copy's target that `TARGET` has no row for — a creature **subtype** as the noun
#: ("another target villain you control", Loki, the Deceiver) and/or **several adjectives** ("target attacking
#: legendary creature you control other than ~", Shaun, Father of Synths). Each adjective is one filter fragment
#: (a combat state, or `target_adjective_filter`'s supertype/colour/"nontoken"/subtype vocabulary), merged into the
#: ``creature_filter`` the plain target row carries; a word outside that vocabulary fails the clause closed. Only
#: reached when `_COPY_PERMANENT_RE` (every phrase `TARGET` knows) did not claim the clause.
_COPY_NP_RE = compile_clause(
    rf"{_COPY_HEAD}(?P<up_to_one>up to (?:1|one) )?(?P<other>(?:another|other) )?target "
    r"(?P<adjs>(?:[a-z-]+ )*?)(?P<noun>[a-z-]+) you control(?P<excl> other than ~)?"
    rf"{_COPY_AND_TA}(?:,?\s+except (?P<except_tail>.+))?"
)

#: A combat-state adjective of a target phrase → its `combat.matches_object_filter` fragment.
_COPY_NP_STATE_WORDS: dict[str, dict] = {
    "attacking": {"attacking": True}, "blocking": {"blocking": True},
    "tapped": {"tapped": True}, "untapped": {"tapped": False},
}


def _copy_np_filter(adjs: str, noun: str) -> Optional[dict]:
    """The ``creature_filter`` of ``<adjectives> <noun>`` (``None`` = a word outside the vocabulary)."""

    fragment: dict = {}
    for word in adjs.split():
        piece = _COPY_NP_STATE_WORDS.get(word.lower())
        if piece is None:
            piece = target_adjective_filter(word)
        if piece is None:
            return None
        fragment.update(piece)
    noun = noun.lower()
    if noun != "creature":
        if noun not in SUBTYPES or noun in NONCREATURE_SUBTYPE_WORDS or "subtype" in fragment:
            return None
        fragment["subtype"] = noun.capitalize()
    return fragment


def _copy_permanent_np(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    fragment = _copy_np_filter(m.group("adjs"), m.group("noun"))
    head = _copy_head_params(m)
    if fragment is None or head is None:
        return None
    other = bool(m.group("other") or m.group("excl"))
    params: dict = {
        "target_kind": "other_creature_you_control" if other else "creature_you_control", **head,
    }
    if m.group("up_to_one"):
        params["optional"] = True
    if fragment:
        params["creature_filter"] = fragment
    if m.groupdict().get("and_ta"):
        params["tapped"] = True
        params["attacking"] = True
    return _copy_with_tail(params, m.groupdict().get("except_tail"))


#: PAR-153: "…a copy of **the exiled card**, except it's an Illusion in addition to its other types" (Phantom Steed)
#: — the card this permanent's own "exile … until ~ leaves the battlefield" took (RULE 610.3): neither a fresh target
#: nor a pronoun for an earlier clause, so its own referent (`CopyPermanentEffect`'s ``"exiled_by_source"``).
_COPY_EXILED_CARD_RE = compile_clause(
    rf"{_COPY_HEAD}the exiled card{_COPY_AND_TA}(?:,?\s+except (?P<except_tail>.+))?"
)


def _copy_exiled_card(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    head = _copy_head_params(m)
    if head is None:
        return None
    params: dict = {"target_kind": None, "referent": "exiled_by_source", **head}
    if m.groupdict().get("and_ta"):
        params["tapped"] = True
        params["attacking"] = True
    return _copy_with_tail(params, m.groupdict().get("except_tail"))


#: PAR-153: "create X tokens that are copies of **it** and that are tapped and attacking" in a "whenever ~ …"
#: ability (Nacatl War-Pride) — the pronoun is the ability's own source, which only a self-subject trigger body
#: guarantees (an earlier clause's target would read the same), so the row is `self_subject_only`.
_COPY_SELF_IT_RE = compile_clause(
    rf"{_COPY_HEAD}it{_COPY_AND_TA}(?:,?\s+except (?P<except_tail>.+))?"
)


def _copy_self_it(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    head = _copy_head_params(m)
    if head is None:
        return None
    if not (m.groupdict().get("and_ta") or m.groupdict().get("ta") or m.groupdict().get("tb")):
        # Only the attack-time shape: a bare "create a token that's a copy of it" is a cast trigger's copy of the
        # *spell* ("When you cast this spell …", Osgood) and a counted "two tokens that are copies of it" copies a
        # prototyped permanent (Skitterbeam Battalion) -- neither is this row's reading.
        return None
    params: dict = {"target_kind": None, "referent": "source", **head}
    if m.groupdict().get("and_ta"):
        params["tapped"] = True
        params["attacking"] = True
    return _copy_with_tail(params, m.groupdict().get("except_tail"))


#: PAR-153 (Calamity, Galloping Inferno): "choose a nonlegendary creature that saddled it this turn and create a tapped
#: and attacking token that's a copy of it. Sacrifice that token at the beginning of the next end step. Repeat this
#: process once." — RULE 702.171 saddlers (`GameObject.saddled_by_ids`) are the pool of a `choose_objects` pick, whose
#: ``then`` copies the pick (RULE 508.4, tapped and attacking) and arms its end-step sacrifice. "Repeat this process
#: once" runs the whole choose-copy-sacrifice again (the same creature may be chosen twice, per the rulings), so the
#: pair is emitted twice. The three sentences are one row because the sacrifice names a token only the pick's own
#: ``then`` creates.
_CHOOSE_SADDLER_COPY_RE = compile_clause(
    r"choose an? (?P<adj>nonlegendary )?creature that saddled it this turn and create a tapped and attacking token "
    r"that'?s a copy of it\.? sacrifice that token at the beginning of the next end step"
    r"(?P<repeat>\.? repeat this process once)?"
)


def _choose_saddler_copy(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    pick: dict = {
        "action": "select_referent", "what": "creature", "count": 1, "saddlers_only": True,
        "then": [
            {"type": "copy_permanent", "params": {
                "target_kind": None, "referent": "previous", "tapped": True, "attacking": True,
            }},
            {"type": "create_delayed_trigger", "params": {
                "step": "end", "scope": "any", "capture": "created_objects",
                "effects": [{"type": "sacrifice_specific", "params": {}}],
            }},
        ],
    }
    if m.group("adj"):
        pick["permanent_filter"] = {"nonlegendary": True}
    rounds = 2 if m.group("repeat") else 1
    return [EffectSpec("choose_objects", dict(pick)) for _ in range(rounds)]


#: "Create a token that's a copy of ~, except it has haste." (Splinter
#: Twin/Kiki-Jiki-shaped).  This is intentionally separate from TARGET:
#: ``~`` is not a RULE 115 target, so the copied permanent is the ability's
#: source and must remain stable when the ability was granted by an Aura.
_COPY_SELF_RE = compile_clause(
    rf"{_COPY_HEAD}~(?:, except (?P<except_tail>[^.]+))?"
)

def _copy_self(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    head = _copy_head_params(m)
    if head is None:
        return None
    params: dict = {"target_kind": None, "referent": "source", **head}
    tail = m.groupdict().get("except_tail")
    if tail:
        extra = parse_copy_except_tail(tail)
        if extra is None:
            return None
        params.update(extra)
    return [EffectSpec("copy_permanent", params)]


#: The RULE 702.33b kicked-override sibling — "Create a token that's a copy
#: of target creature. If this spell was kicked, create five of those
#: tokens instead." (Rite of Replication) — same override shape as
#: `_damage_kicked_override`, just replacing ``count`` instead of ``amount``
#: (`CopyPermanentEffect.count_if_kicked`).
_COPY_PERMANENT_KICKED_OVERRIDE_RE = compile_clause(
    rf"create a token that'?s a copy of {TARGET}"
    rf"{_KICKED_OVERRIDE_PREFIX}create (?P<n2>\d+) of those tokens instead"
)


def _copy_permanent_kicked_override(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("copy_permanent", {
        "target_kind": kind, "count_if_kicked": int(m.group("n2")), **optional_param(m),
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
_COPY_PERMANENT_PREVIOUS_RE = compile_clause(
    rf"{_COPY_HEAD}(?:it|that (?:card|creature|permanent|artifact|enchantment|land)){_COPY_AND_TA}"
    r"(?:,?\s+except (?P<except_tail>.+))?"
)


def _copy_permanent_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    head = _copy_head_params(m)
    if head is None:
        return None
    # "create a **tapped and attacking** token that's a copy of that card…" (RULE 508.4 — Sauron, the
    # Necromancer). `CopyPermanentEffect` already takes ``tapped``/``attacking``.
    params: dict = {"target_kind": None, "referent": "previous", **head}
    if m.groupdict().get("and_ta"):
        params["tapped"] = True
        params["attacking"] = True
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
_COPY_PERMANENT_GROUP_RE = compile_clause(
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
_CREATE_NAMED_CARD_TOKEN_RE = compile_clause(
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
_COPY_SELF_FOR_EACH_RE = compile_clause(
    r"for each (?P<sel>card you'?ve discarded this turn), "
    r"create a token that'?s a copy of ~"
    r"(?:, except (?:the token|it) (?P<not_legendary>isn'?t legendary))?"
)


#: "Exile a permanent card from your graveyard at random, then create a
#: tapped token that's a copy of that card. If the exiled card is a land
#: card, repeat this process." (Sin, Spira's Punishment) — one fixed
#: phrasing → the self-contained `random_graveyard_exile_copy_loop` effect
#: (RULE 706 randomization + RULE 707.2 copy in a land-keyed loop).
_RANDOM_GY_EXILE_COPY_LOOP_RE = compile_clause(
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
    params = multi_target_params(m)
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
# Plural target phrases for divided damage. Qualifiers stay attached to
# the target pool, both while choosing targets and when resolving damage.
_DIVIDED_DAMAGE_TARGETS = {
    "targets": {"target_kind": "any"},
    "target creatures and/or planeswalkers": {"target_kind": "creature_or_planeswalker"},
    "target creatures": {"target_kind": "creature"},
    "target attacking creatures": {"target_kind": "creature", "creature_filter": {"attacking": True}},
    "target attacking or blocking creatures": {"target_kind": "attacking_or_blocking_creature"},
    "target creatures with flying": {"target_kind": "creature", "creature_filter": {"keyword": "flying"}},
}
_DIVIDED_DAMAGE_TARGET_ALT = "|".join(re.escape(t) for t in _DIVIDED_DAMAGE_TARGETS)
_DIVIDED_DAMAGE_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}"
    rf"deals? {COUNT_X} damage divided as you choose among any number of "
    rf"(?P<target>{_DIVIDED_DAMAGE_TARGET_ALT})"
    # PAR-128: "… your opponents control" (Dragonlord Atarka, Polukranos).
    rf"(?P<scope>{MULTI_TARGET_SCOPE_TAIL})?"
)


def _divided_damage_target(m: re.Match[str]) -> Optional[dict[str, Any]]:
    params = copy.deepcopy(_DIVIDED_DAMAGE_TARGETS[m.group("target")])
    scope = m.groupdict().get("scope")
    if scope:
        kind = params["target_kind"]
        kind = (MULTI_TARGET_YOU_KINDS if scope.strip() == "you control" else NOT_YOU_TARGET_KINDS).get(kind)
        if kind is None:
            return None
        params["target_kind"] = kind
    return params


def _divided_damage(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _divided_damage_target(m)
    if params is None:
        return None
    return [EffectSpec("damage", {
        "amount": count_or_x_of(m.group("n")), **params,
        "count": ANY_NUMBER_TARGET_CAP, "optional": True, "divided": True,
    })]


# RULE 601.2c/d: a range of target counts, including an enumerated contiguous
# range ("one, two, or three targets"). Noncontiguous lists must fail closed:
# count/count_max cannot express a forbidden count inside the interval.
_DIVIDED_DAMAGE_RANGE_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}"
    rf"deals? {COUNT_X} damage divided as you choose among "
    r"(?P<range_min>\d+)(?:,\s*(?P<range_middle>\d+(?:,\s*\d+)*),?)? or (?P<range_max>\d+) "
    rf"(?P<target>{_DIVIDED_DAMAGE_TARGET_ALT})"
    rf"(?P<scope>{MULTI_TARGET_SCOPE_TAIL})?"
)


def _divided_damage_range(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
    middle = m.group("range_middle")
    if range_min < 1 or range_max <= range_min:
        return None
    if middle is not None:
        counts = [range_min, *(int(n.strip()) for n in middle.split(",")), range_max]
        if counts != list(range(range_min, range_max + 1)):
            return None
    params = _divided_damage_target(m)
    if params is None:
        return None
    return [EffectSpec("damage", {
        "amount": count_or_x_of(m.group("n")), **params,
        "count": range_min, "count_max": range_max, "divided": True,
    })]


#: ENG-30: "deals N damage to each of 1 or 2 targets" (Storm of Steel) — the
#: full-amount-to-each sibling of `_divided_damage_range` (mirrors how
#: `_damage_each_multi_target` relates to `_divided_damage` for the "any
#: number of"/"up to N" shapes), same local bare-``targets`` alternation.
_DAMAGE_EACH_RANGE_RE = compile_clause(
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
_PREVENT_DIVIDED_DAMAGE_RE = compile_clause(
    r"prevent the next (?P<n>\d+) damage that would be dealt this turn to "
    r"any number of targets, divided as you choose"
    rf"(?:{_KICKED_OVERRIDE_PREFIX}prevent the next (?P<n2>\d+) damage this way instead)?"
)


def _prevent_divided_damage(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "amount": int(m.group("n")), "target_kind": "any",
        "count": ANY_NUMBER_TARGET_CAP, "optional": True, "divided": True,
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
_PREVENT_DAMAGE_SINGLE_TARGET_RE = compile_clause(
    rf"prevent the next {COUNT_X} damage that would be dealt to {TARGET} this turn"
)


def _prevent_damage_single_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m["target"])
    if not target_kind_allowed(kind, ("any", "creature", "player", "opponent", "planeswalker", "permanent")):
        return None
    return [EffectSpec("prevent_damage_shield", {
        "amount": count_or_x_of(m["n"]), "target_kind": kind,
        **({"optional": True} if target_is_optional(m) else {}),
        **({"creature_filter": resolve_target_creature_state_filter(m["target"])}
           if resolve_target_creature_state_filter(m["target"]) else {}),
    })]


#: PAR-139: "prevent the next N damage that would be dealt to target creature this turn" (Test of Faith, Temper's
#: X) — the creature sibling of the any-target row above; ``x`` is the spell's announced X.
_PREVENT_NEXT_DAMAGE_TARGET_CREATURE_RE = compile_clause(
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
_PREVENT_SHIELD_THEN_RIDER_RE = compile_clause(
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


_PREVENT_DAMAGE_PLAYER_PLANESWALKER_OR_SUBTYPE_RE = compile_clause(
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
_PREVENT_NEXT_DAMAGE_TO_YOU_RE = compile_clause(
    # PAR-215: "the next X damage" and the "you and/or permanents you control" recipient union (Divine Deflection).
    r"prevent the next (?P<n>\d+|x) damage that would be dealt to you"
    r"(?: and/or (?P<scope>creatures|permanents) you control)? this turn"
)


def _prevent_next_damage_to_you(m: re.Match[str]) -> list[EffectSpec]:
    n = m.group("n").lower()
    params: dict = {"amount": "x" if n == "x" else int(n)}
    if m.group("scope"):
        params["recipient_scope"] = m.group("scope")
    return [EffectSpec("prevent_damage_shield", params)]


#: PAR-215: a shield followed by "If damage is prevented this way, ~ deals that much damage to <target>." (Divine
#: Deflection, Vengeful Archon, Channel Harm) -- the amount actually prevented is the damage dealt, through the
#: `reflexive_damage` rider (`RulesEngine.apply_prevent_rider`, RULE 603.12): a fresh triggered ability whose target is
#: chosen when it is put on the stack. "you may have" makes the target optional.
_PREVENT_REFLEXIVE_TARGETS: dict[str, str] = {
    "any target": "any", "target player or planeswalker": "player_or_planeswalker", "target creature": "creature",
}
_PREVENT_SHIELD_THEN_REFLEXIVE_RE = compile_clause(
    r"(?P<shield>prevent (?:the next (?:\d+|x)|all) damage that would be dealt to [^.]+?(?: this turn)?(?: by [^.]+?)?)\.\s+"
    r"if damage is prevented this way, (?P<may>you may have )?~ (?:deals|deal) that much damage to "
    rf"(?P<tgt>{'|'.join(_PREVENT_REFLEXIVE_TARGETS)})"
)


def _prevent_shield_then_reflexive(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    shield = match_clause(m.group("shield"))
    if shield is None or len(shield) != 1 or shield[0].type != "prevent_damage_shield" or "rider" in shield[0].params:
        return None
    rider: dict = {"kind": "reflexive_damage", "target_kind": _PREVENT_REFLEXIVE_TARGETS[m.group("tgt")]}
    if m.group("may"):
        rider["optional"] = True
    return [EffectSpec("prevent_damage_shield", {**shield[0].params, "rider": rider})]


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
_PREVENT_ALL_COMBAT_DAMAGE_RE = compile_clause(r"prevent all combat damage that would be dealt this turn")


def _prevent_all_combat_damage(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_all_combat_damage", {})]


#: "Prevent all combat damage that would be dealt to this creature this turn"
#: (Blinding Powder).  This is a personal, one-turn shield, not the global
#: Fog form above; `PreventDamageEffect.self_only` already supplies its
#: replacement-effect semantics.
_PREVENT_ALL_COMBAT_DAMAGE_TO_SELF_RE = compile_clause(
    r"prevent all combat damage that would be dealt to (?:this creature|this permanent|~) this turn"
)


def _prevent_all_combat_damage_to_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_damage_shield", {
        "amount": "all", "self_only": True, "combat_only": True,
    })]


_PREVENT_ALL_COMBAT_DAMAGE_DEALT_SELF_RE = compile_clause(
    rf"prevent all combat damage (?P<by>that would be dealt by )?(?:{TARGET}|this creature|this permanent|~)(?(by)| would deal) this turn"
)


def _prevent_all_combat_damage_dealt_self(m: re.Match[str]) -> list[EffectSpec]:
    if m.groupdict().get('target'):
        kind = resolve_target_kind(m['target'])
        if not target_kind_allowed(kind, ('creature', 'attacking_or_blocking_creature')):
            return None
        return [EffectSpec('prevent_combat_damage_dealt', {
            'target_kind': kind, 'creature_filter': resolve_target_creature_state_filter(m['target']),
            **optional_param(m),
        })]
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
# The shared object grammar validates this slot completely in the builder.
_PREVENT_SOURCE_FILTER_ALT = r"[a-z][a-z0-9 '/+-]*"



def _parse_prevent_source_filter(phrase: str) -> Optional[dict]:
    """A matched `_PREVENT_SOURCE_FILTER_ALT` phrase → its `source_filter`
    dict, or ``None`` if unrecognized (fail-closed)."""
    text = phrase.strip().lower()
    for pattern, filt in _PREVENT_SOURCE_FILTER_PHRASES.items():
        if re.fullmatch(pattern, text):
            return dict(filt)
    parsed = parse_object_phrase(text, plural=True)
    if parsed is None:
        return None
    filt, controller = parsed
    if controller not in (None, 'you', 'not_you'):
        return None
    return {'object_filter': filt, **({'controller': controller} if controller else {})}


#: PAR-216: the damage-source phrase grammar, shared with `effect_rows.damage_prevention`.
parse_prevent_source_filter = _parse_prevent_source_filter


#: PAR-78: bare self — "Prevent all damage that would be dealt to
#: `<~/this creature/this permanent>`[ this turn][ **by** `<source
#: filter>`]." (Cho-Manno, Revolutionary/Dawn Elemental/Argothian Pixies/
#: Champion Lancer/Wall of Putrid Flesh/…).
_PREVENT_ALL_DAMAGE_SELF_RE = compile_clause(
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


#: PAR-215: "Prevent all damage that would be dealt **by creatures** this turn. You gain life equal to the damage
#: prevented this way." (Chant of Vitu-Ghazi) -- a recipient-less shield on a source class
#: (`RulesEngine._prevent_damage_by_sources`), with the optional gain-life tally rider.
_PREVENT_ALL_DAMAGE_BY_SOURCES_RE = compile_clause(
    rf"prevent all damage that would be dealt by (?P<filter>{_PREVENT_SOURCE_FILTER_ALT}) this turn"
    r"(?:\.\s+(?P<life>you gain life equal to the damage prevented this way))?"
)


def _prevent_all_damage_by_sources(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    source_filter = _parse_prevent_source_filter(m.group("filter"))
    if source_filter is None:
        return None
    params: dict = {"amount": "all", "by_sources_only": True, "source_filter": source_filter}
    if m.group("life"):
        params["rider"] = {"kind": "gain_life", "recipient": "you"}
    return [EffectSpec("prevent_damage_shield", params)]


#: PAR-78: the untargeted "you" shield — "Prevent all damage that would be
#: dealt to you[ **and** creatures/permanents you control][ this turn][
#: **by** `<source filter>`]." (Solitary Confinement/Endure/Safe Passage/
#: Deep Wood/Scarecrow/Eerie Interference/…).
_PREVENT_ALL_DAMAGE_YOU_RE = compile_clause(
    r"prevent all damage that would be dealt to you"
    r"(?: and (?P<scope>creatures|permanents|planeswalkers) you control)?"
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
_PREVENT_ALL_DAMAGE_CREATURES_RE = compile_clause(
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
_PREVENT_ALL_DAMAGE_TARGET_RE = compile_clause(
    rf"prevent all (?P<combat>combat )?damage that would be dealt to (?:{TARGET}|target "
    r"(?:(?P<tapped>tapped) )?(?:(?P<legendary>legendary) )?"
    r"(?:(?P<subtype1>[a-z]+)(?: or (?P<subtype2>[a-z]+))? )?creature"
    r"(?: with power (?P<minpower>\d+) or greater)?"
    r") this turn"
    rf"(?: by (?P<filter>{_PREVENT_SOURCE_FILTER_ALT}))?"
)


def _prevent_all_damage_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    target = m.groupdict().get("target")
    kind = resolve_target_kind(target) if target else "creature"
    if not target_kind_allowed(kind, ("any", "creature", "player", "opponent", "planeswalker", "permanent")):
        return None
    params: dict = {"amount": "all", "target_kind": kind}
    if m["combat"]:
        params["combat_only"] = True
    if target and target_is_optional(m):
        params["optional"] = True
    creature_filter: dict = resolve_target_creature_state_filter(target) or {} if target else {}
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
_PREVENT_ALL_DAMAGE_PREVIOUS_RE = compile_clause(
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
_PREVENT_ALL_DAMAGE_SELF_PRONOUN_RE = compile_clause(
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


#: "~ deals N damage to target `<color>` or `<color>` creature." (Rending
#: Volley-shaped) — `TargetSpec.colors`' own OR narrowing (`_destroy`'s
#: single-``color`` sibling; only ever two colours on a real card so far).
_DAMAGE_TARGET_TWO_COLOR_RE = compile_clause(
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
    selector = SELECTOR_WORD_MAP[m.group("selector")]
    n = m.group("n").lower()
    params: dict[str, Any] = {"amount": "x" if n == "x" else int(n), "selector": selector}
    if m.group("selector") == _SPELL_CONTROLLER_PHRASE:
        params[EVENT_PLAYER_EVENTS_KEY] = [BECOMES_TARGET_EVENT]
    # PAR-128: an X amount ("deals x damage to each creature and each player" — Crypt Rats).
    return [EffectSpec("damage", params)]


#: "~ deals N damage to any target and M damage to each creature" (Wildfire
#: Howl) — the second conjunct elides the repeated subject and verb.  Keep it
#: as two ordinary damage effects so the first announces its RULE 115 target
#: while the mass half remains untargeted (RULE 601.2c).
_DAMAGE_TARGET_AND_SELECTOR_RE = compile_clause(
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
            "selector": SELECTOR_WORD_MAP[m.group("selector")],
        }),
    ]


#: "~ deals 1 damage to each creature you don't control" / "…to each other creature
#: you control" / "…to each other creature without flying" (Barrage of Boulders, Cinder
#: Giant, Fire Ants — PAR-128) — the general mass form: the group is whatever the shared
#: noun-phrase grammar reads (`parse_count_phrase`, singular head pluralized), carried as
#: `DealDamageEffect.group`. Primary over `damage_selector`/`damage_each_creature_keyword` (PAR-169), which keep only what it declines.
_DAMAGE_GROUP_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+|x) damage to each (?P<group>[a-z' -]+?)"
)


def _damage_group(m: re.Match[str], *, that_player: str = "event_player") -> Optional[list[EffectSpec]]:

    text = m.group("group")
    and_players = None
    for tail, scope in ((" and each player", "each_player"), (" and each opponent", "each_opponent")):
        if text.endswith(tail):
            text, and_players = text[: -len(tail)], scope
            break
    group_player = None
    for tail, who in DAMAGE_GROUP_PLAYER_TAILS.items():
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
    group = parse_count_phrase(SINGULAR_GROUP_HEADS.sub(r"\1s", text))
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


#: RULE 115 / 120.3: "~ deals N damage to target player and each creature that player controls." (Chandra, Flame's
#: Fury) -- the announced player AND that player's creature group (Urabrask's shape). Read as the ordinary
#: "each creature target player controls" mass hit plus the player themself as a scoped recipient.
_DAMAGE_TARGET_PLAYER_AND_GROUP_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+|x) damage to (?P<who>target (?:player|opponent)(?: or planeswalker)?) "
    r"and (?:(?P<group_n>\d+|x) damage to )?each (?P<group>[a-z' -]+?) "
    r"(?P<controller>that player or that planeswalker's controller|that player|they) controls?"
)


def _damage_target_player_and_group(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    if 'planeswalker' in m['who'] or m['group_n']:
        if ('planeswalker' in m['who']) != ('planeswalker' in m['controller']):
            return None
        group = object_set(m['group'], reading.only())
        if group is None or group.get('of') != 'any':
            return None
        n = m['n']
        params = {'amount': 'x' if n == 'x' else int(n), 'group': {**group, 'of': 'you'},
                  'group_player': resolve_target_kind(m['who']), 'group_and_players': 'scoped_player'}
        if m['group_n']:
            params['group_amount'] = 'x' if m['group_n'] == 'x' else int(m['group_n'])
        return [EffectSpec('damage', params)]
    inner = match_clause_once(
        f"~ deals {m.group('n')} damage to each {m.group('group')} {m.group('who')} controls",
        reading=reading.only(),
    )
    if not inner or len(inner) != 1 or inner[0].type != "damage" or inner[0].params.get("group_player") not in ("player", "opponent"):
        return None
    return [EffectSpec("damage", {**inner[0].params, "group_and_players": "scoped_player"})]


#: "~ deals 1 damage to each nonblack creature **and an additional 1 damage to each green creature**." (Kaervek's
#: Hex) / "…to each creature with flying and 1 additional damage to each blue creature." (Tropical Storm) — two
#: mass hits by the same source in one resolution, each read by the ordinary mass-damage rows.
_DAMAGE_PLUS_ADDITIONAL_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+|x) damage to (?P<first>each [a-z' -]+?) "
    r"and (?:an additional (?P<n2>\d+|x)|(?P<n3>\d+|x) additional) damage to (?P<second>each [a-z' -]+)"
)


def _damage_plus_additional(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    n2 = m.group("n2") or m.group("n3")
    first = match_clause_once(f"~ deals {m.group('n')} damage to {m.group('first')}", reading=reading.only())
    second = match_clause_once(f"~ deals {n2} damage to {m.group('second')}", reading=reading.only())
    if not first or not second or any(e.type != "damage" for e in (*first, *second)):
        return None
    return [*first, *second]


def _damage_that_much_selector(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount_from_trigger_event": "that_much",
        "selector": SELECTOR_WORD_MAP[m.group("selector")],
    })]


#: "~ deals 2 damage to itself." (Goblin Bangchuckers / Kaboomist, Stuffy Doll) - the source
#: damages itself (`DealDamageEffect`'s ``self`` selector). Only the explicit "~" subject: a bare
#: "it deals N damage to itself" names whatever the previous clause chose.
_DAMAGE_TO_ITSELF_RE = compile_clause(rf"~ deals? {NUMBER} damage to itself")


def _damage_to_itself(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {"amount": int(m.group("n")), "selector": "self"})]


#: "This creature deals 2 damage to you for each Treasure you control."
#: (Black Market Tycoon) — the exact self-damage/count template; ``for each``
#: is a multiplier, not the existing additive count-selector form.
_DAMAGE_TO_YOU_PER_TREASURE_RE = compile_clause(
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
_DAMAGE_EACH_CREATURE_KEYWORD_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+|x|twice x) damage to "
    rf"each creature (?P<neg>with|without) (?P<kw>flying|horsemanship)"
    # "…without flying and each planeswalker" (Magmaquake): the keyword filter narrows the creatures only.
    rf"(?:(?P<and_player> and each player)|(?P<and_pw> and each planeswalker)|(?P<opp>{MULTI_TARGET_SCOPE_TAIL}))?"
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
_DAMAGE_EACH_DAMAGED_CREATURE_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to each creature dealt damage this turn"
)
_DAMAGE_EACH_CREATURE_KICKED_RE = compile_clause(
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
_DAMAGE_PER_NONCREATURE_SPELL_CAST_THIS_TURN_RE = compile_clause(
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
_DAMAGE_EACH_OPPONENT_AND_CREATURES_RE = compile_clause(
    rf"(?:(?:~|it) )?deals? {NUMBER} damage to each opponent and each creature"
    rf"(?P<pw> and planeswalker)? they control"
)


#: "~ deals N damage to each opponent and each creature they control. If
#: this spell was cast from exile, it deals M damage to each opponent and
#: each creature they control instead." (Delayed Blast Fireball) —
#: `DealDamageEffect.amount_if_cast_from_exile`'s own override, the same
#: shape `amount_if_kicked`/`amount_if_bargained` already use.
_DAMAGE_EACH_OPPONENT_AND_CREATURES_EXILE_RE = compile_clause(
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
_DAMAGE_SELECTOR_DEVOTION_RE = compile_clause(
    rf"it deals damage to (?P<selector>each opponent|each player) equal to {DEVOTION}"
)


_damage_selector_devotion = selector_devotion_builder("damage")


#: PAR-132: "that spell or ability's controller" is only the firing event's ``player_id`` under a
#: becomes-the-target head; `gate._event_player_antecedent_ok` checks the marker and strips it.
_SPELL_CONTROLLER_PHRASE = "that spell or ability's controller"


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
_DAMAGE_CREATURE_FILTER_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}"
    rf"deals? {NUMBER} damage to target creature{CREATURE_FILTER_SCOPED}"
)


def _damage_creature_filter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    filt = creature_quality_filter(m)
    kind = scoped_creature_kind(m)
    if filt is None or kind is None:
        return None
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "target_kind": kind, "creature_filter": filt,
    })]
_DAMAGE_DAMAGED_CREATURE_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}deals? {NUMBER} damage to target creature{DAMAGED_THIS_TURN_TAIL}"
)


def _damage_damaged_creature(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "target_kind": damaged_creature_kind(m),
        "creature_filter": {"damaged_this_turn": True},
    })]


#: "This creature deals 8 damage to you unless you pay {G}{G}{G}{G}."
#: (Force of Nature / Minion of Tevesh Szat) — payment is optional at
#: resolution; declining is what performs the self-damage.
_DAMAGE_TO_YOU_UNLESS_PAY_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}deals? {NUMBER} damage to you unless you (?P<cost>{UNLESS_COST})"
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
_SKIP_YOUR_DRAW_STEP_THIS_TURN_RE = compile_clause(r"you skip your draw step this turn")


def _skip_your_draw_step_this_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_step", {"step": "draw"})]


#: "`<player>` skips their next `<untap step | draw step | combat phase>`" (Fatigue, Yosei, Brine Elemental, Blinding
#: Angel, Stonehorn Dignitary, Moment of Silence): a one-shot skip installed on someone else
#: (`SkipNextStepEffect` ``target_kind`` / ``selector``). "…this turn" (Moment of Silence) is the same skip — it
#: is consumed by the first matching step still to come.
_SKIP_THEIR_NEXT_RE = compile_clause(
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


_AMASS_RE = compile_clause(rf"amass (?P<subtype>[a-z]+) {NUMBER}")


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


_AMASS_UNTYPED_RE = compile_clause(rf"amass {NUMBER}")


# RULE 510.1: this is an assignment prohibition, not damage prevention.
_ASSIGN_NO_COMBAT_DAMAGE_RE = compile_clause(
    r"(?P<subject>~|it|that creature|the first creature|the attacking creature) assigns no combat damage this turn"
)


def _assign_no_combat_damage(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    subject = m.group("subject")
    params = {}
    if subject != "~":
        if reading.group_subject:
            params["subject"] = "trigger_subject"
        elif reading.attached_subject:
            # The trigger names the firing host, including after detachment.
            params["subject"] = "trigger_subject"
        elif reading.previous_subject:
            params["subject"] = "previous_target"
        elif not reading.self_subject or subject not in {"it", "that creature"}:
            return None
    return [EffectSpec("assign_no_combat_damage", params)]


ROWS: list[EffectHandler] = [
    EffectHandler("assign_no_combat_damage", _ASSIGN_NO_COMBAT_DAMAGE_RE, _assign_no_combat_damage, reading_aware=True),
    # RULE 701.47/48 Amass "<Type> N" — "amass Orcs 1"/"amass Zombies 2".
    # Tried before the untyped row below since a real type word always
    # parses here first (the untyped row's bare NUMBER can never see it —
    # a type word isn't a digit — so the ordering is purely cosmetic).
    EffectHandler("amass", _AMASS_RE, _amass),
    EffectHandler("empower_jace", compile_clause(rf"empower jace {COUNT_X}"),
                  lambda m: [EffectSpec("empower_jace", {"count": count_or_x_of(m.group("n"))})]),
    # RULE 701.47d's pre-errata bare "amass N" (no subtype) — see the
    # builder's own docstring; not expected to match any card in today's
    # already-errata'd cache.
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_amass_family.py (the bare 'amass N' reminder form).
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
    # PAR-153: the noun-phrase axis `TARGET` lacks (creature-subtype noun, stacked adjectives, "other than ~").
    EffectHandler("copy_permanent_np", _COPY_NP_RE, _copy_permanent_np),
    EffectHandler("copy_exiled_card", _COPY_EXILED_CARD_RE, _copy_exiled_card),
    EffectHandler("choose_saddler_copy", _CHOOSE_SADDLER_COPY_RE, _choose_saddler_copy),
    EffectHandler("copy_self_it", _COPY_SELF_IT_RE, _copy_self_it, requires=ClauseReading(self_subject=True)),

    # PAR-18: "exile up to 1 target creature card from a graveyard. Create a
    # token that's a copy of it/that card[, except <modifier(s)>]." — the
    # pronoun sibling of the row above, offered only once an earlier clause
    # of the same ability actually chose something (`GameContext.
    # previous_targets`).
    EffectHandler(
        "copy_permanent_previous",
        _COPY_PERMANENT_PREVIOUS_RE,
        _copy_permanent_previous,
        requires=ClauseReading(previous_subject=True),
    ),
    # PAR-124: "whenever a nontoken creature an opponent controls enters,
    # create a token that's a copy of that creature." (Theoretical
    # Duplication) — the RULE 603.1 group-subject sibling of the row above.
    EffectHandler(
        "copy_permanent_group",
        _COPY_PERMANENT_GROUP_RE,
        _copy_permanent_group,
        requires=ClauseReading(group_subject=True),
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
    EffectHandler("damage_damaged_creature", _DAMAGE_DAMAGED_CREATURE_RE, _damage_damaged_creature),
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
        compile_clause(
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
        compile_clause(
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
        compile_clause(rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to target creature that'?s blocking (?:it|~)"),
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
        compile_clause(rf"{SELF_SUBJECT_PREFIX}deals? that much damage to {TARGET}"),
        _damage_that_much,
    ),
    # "~ deals 3 damage to any target" / "deal 2 damage to target creature" /
    # "it deals 2 damage to target opponent" (a triggered-ability body's own
    # "it"/"this creature"/"this land"/"this permanent" subject — cosmetic,
    # since the source is already bound at bind time regardless of wording).
    EffectHandler(
        "damage",
        compile_clause(rf"{SELF_SUBJECT_PREFIX}deals? {NUMBER} damage to {TARGET}"),
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
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par33_regenerate_attached.py (quoted granted attack trigger).
    EffectHandler(
        "damage_x_defending_player_hand",
        _DAMAGE_X_DEFENDING_PLAYER_HAND_RE,
        _damage_x_defending_player_hand,
        requires=ClauseReading(self_subject=True),
    ),
    EffectHandler(
        "damage_x",
        compile_clause(rf"{SELF_SUBJECT_PREFIX}deals? (?P<twice>twice )?x damage to {TARGET}"),
        _damage_x,
    ),
    # "~ deals damage equal to that spell's mana value to target opponent."
    # (Passionate Archaeologist's granted cast trigger, PAR-32) — the
    # amount is the firing `SPELL_CAST` event's own ``mana_value`` field,
    # the same "read that spell's MV off the event" idiom `_incubate_x`'s
    # ``spell_mv`` branch uses (`DealDamageEffect.amount_from_trigger_event`).
    EffectHandler(
        "damage_spell_mv",
        compile_clause(
            rf"(?:(?:~|it|this creature) )?deals? damage equal to that spell'?s "
            rf"mana value to {TARGET}"
        ),
        _damage_spell_mv,
    ),
    # PAR-128: "each of those creatures deals damage equal to its power to ~." (Polukranos,
    # World Eater) — the earlier clause's targets are the dealers; the recipient is the source.
    EffectHandler(
        "damage_equal_to_power_previous_group_to_source",
        compile_clause(r"each of those creatures deals damage equal to its power to (?:~|this creature)"),
        lambda m: [EffectSpec("damage_equal_to_power", {"dealer_group": "previous_targets"})],
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "damage_to_attacked_defender", _DAMAGE_TO_ATTACKED_RE, _damage_to_attacked,
        requires=ClauseReading(group_subject=True),
    ),
    EffectHandler("attached_deals_that_much", _ATTACHED_DEALS_THAT_MUCH_RE, _attached_deals_that_much,
                  requires=ClauseReading(attached_subject=True)),
    EffectHandler("attached_it_deals_that_much", _ATTACHED_IT_DEALS_THAT_MUCH_RE, _attached_it_deals_that_much,
                  requires=ClauseReading(attached_subject=True)),
    EffectHandler(
        "group_deals_to_damaged_controller", _GROUP_DEALS_TO_DAMAGED_CONTROLLER_RE,
        _group_deals_to_damaged_controller, requires=ClauseReading(group_subject=True),
    ),
    EffectHandler(
        "group_deals_to_its_controller", _GROUP_DEALS_TO_ITS_CONTROLLER_RE,
        _group_deals_to_its_controller, requires=ClauseReading(group_subject=True),
    ),
    # "~ [also] deals N damage to that creature's controller" (~22 SOLO —
    # Consign to the Pit / Battle Strain / Dingus Staff / …).
    EffectHandler(
        "damage_to_prev_subject_controller",
        _DAMAGE_TO_SUBJECT_CONTROLLER_RE, _damage_to_prev_subject_controller,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "damage_to_prev_object", _DAMAGE_TO_PREV_OBJECT_RE, _damage_to_prev_object, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "damage_to_trigger_subject_controller",
        _DAMAGE_TO_SUBJECT_CONTROLLER_RE, _damage_to_trigger_subject_controller,
        requires=ClauseReading(group_subject=True),
    ),
    # "~ deals 6 damage to each of up to two target creatures and/or
    # planeswalkers" (RULE 115.1a generalized to N>=2) — the full amount
    # applies to *every* chosen target, not divided among them.
    EffectHandler(
        "damage_each_multi_target",
        compile_clause(
            rf"{SELF_SUBJECT_PREFIX}"
            rf"deals? (?P<amount>\d+) damage to each of {MULTI_TARGET_QUANTIFIER}"
            rf"(?P<target>{MULTI_TARGET_ALT})"
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
        "prevent_all_damage_by_sources",
        _PREVENT_ALL_DAMAGE_BY_SOURCES_RE,
        _prevent_all_damage_by_sources,
    ),
    EffectHandler(
        "prevent_shield_then_reflexive",
        _PREVENT_SHIELD_THEN_REFLEXIVE_RE,
        _prevent_shield_then_reflexive,
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
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "prevent_all_damage_self_pronoun",
        _PREVENT_ALL_DAMAGE_SELF_PRONOUN_RE,
        _prevent_all_damage_self_pronoun,
        requires=ClauseReading(self_subject=True),
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
    EffectHandler("damage_each_damaged_creature", _DAMAGE_EACH_DAMAGED_CREATURE_RE, _damage_each_damaged_creature),
    EffectHandler("damage_each_creature_kicked", _DAMAGE_EACH_CREATURE_KICKED_RE, _damage_each_creature_kicked),
    EffectHandler("damage_to_itself", _DAMAGE_TO_ITSELF_RE, _damage_to_itself),
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
        compile_clause(
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
        lambda m: _skip_their_next(m) if m.group("who") == "that player" else None, requires=ClauseReading(self_subject=True),
    ),
    EffectHandler(
        "skip_your_draw_step_this_turn",
        _SKIP_YOUR_DRAW_STEP_THIS_TURN_RE,
        _skip_your_draw_step_this_turn,
    ),
    # "…to each other creature **that player** controls" after a clause that chose a
    # creature (Flames of the Raze-Boar): that clause's target's controller, offered only
    # once a previous clause supplied one; otherwise `damage_group` reads a trigger's player.
    EffectHandler(
        "damage_group_previous_controller", _DAMAGE_GROUP_RE,
        lambda m: _damage_group(m, that_player="previous_controller")
        if m.group("group").endswith(" that player controls") else None,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "damage_plus_additional", _DAMAGE_PLUS_ADDITIONAL_RE, _damage_plus_additional, reading_aware=True,
    ),
    EffectHandler("damage_group", _DAMAGE_GROUP_RE, _damage_group),
    EffectHandler(
        "damage_selector",
        compile_clause(
            rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+|x) damage to "
            rf"(?P<selector>each creature and each player|each creature and each planeswalker"
            rf"|each creature your opponents control|each creature an opponent controls"
            rf"|each other creature|each creature|each player|each of your opponents|each opponent|that player|that spell or ability's controller|them|you)"
        ),
        _damage_selector,
        fallback_for=("damage_group",),
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
        fallback_for=("damage_group",),
    ),
    EffectHandler(
        "damage_target_player_and_group", _DAMAGE_TARGET_PLAYER_AND_GROUP_RE, _damage_target_player_and_group,
        reading_aware=True,
    ),
    # RULE 202.2f/700.6 "it deals damage to each opponent equal to your
    # devotion to <colour>." (Fanatic of Mogis) — tried before the plain
    # `damage_selector` row above since "equal to …" has no digit `NUMBER`
    # for that row to match.
    EffectHandler("damage_selector_devotion", _DAMAGE_SELECTOR_DEVOTION_RE, _damage_selector_devotion),
]
