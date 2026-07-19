"""Static continuous-ability handlers — anthems and keyword grants (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md (effect-family handlers), RULE 613
(the layer system these feed). A *permanent's* standing sentence like "Other
creatures you control get +1/+1" or "Goblins you control have haste" is a
**static** ability, not a one-shot effect — it reshapes other permanents
continuously while its source is in play. This module recognises those two
families and emits `EffectSpec`s the binder turns into `StaticAbility`s
(`anthem` → layer 7c, `grant_keyword` → layer 6), with a tribal **subtype**
filter for lords (Goblin King, Lord of Atlantis).

Only creature scopes are claimed — "creatures you control", a plural creature
type ("goblins you control"), or "<type> creatures you control" — with a small
block-list keeping non-creature scopes ("artifacts you control …") from being
mis-read as anthems (fail-closed). Anything with an "until end of turn" tail is
a *temporary* effect an instant grants, not a static ability, and won't
full-match here.

A second, closed family recognises an Aura/Equipment/Fortification's own
attached-permanent buff — "equipped creature gets +2/+2", "enchanted creature
has trample" (RULE 303.4/301.5, docs/11 §6 "attached_permanent"). Unlike the
"you control" scopes above, these five printed subject phrases
(`_ATTACHED_SUBJECTS`) always resolve off the ability's own source's
`attached_to`, so they emit `affects="attached_permanent"` rather than any
controller-scoped selector; `game/continuous.py`'s `group_selector_objects`
already honours that selector for both `anthem` and `grant_keyword` (it's the
same code path the hand-authored Armadillo Cloak entry in
`game/ability_catalogue.py` uses) — only the parser recognition was missing.

Pure regex + data — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import re
from typing import NamedTuple, Optional

from ..spec import EffectSpec, ParserProvenance
from .keywords import KEYWORDS, KeywordShape, keyword_slug
from .subgrammars import CANT_BE_COUNTERED_RE

#: Trigger events a granted triggered ability can be safely re-scoped to a
#: *different* object each time it's granted (`continuous.
#: _granted_trigger_condition` matches by the event's own ``instance_id`` —
#: every one of these four carries it; RULE 603.1's object-subject family).
#: Deliberately excludes ``DAMAGE`` (scoped by ``source_id``, a different
#: key `_granted_trigger_condition` doesn't check yet) and any phase/upkeep
#: event (``STEP_BEGIN`` — "at the beginning of your upkeep" is a
#: pre-existing controller-scoping gap for even a top-level card's own
#: printed ability, `segmenter.py`'s ``_PHASE_TRIGGER_RE`` docstring).
_GRANTABLE_TRIGGER_EVENTS = frozenset({"ENTERS_BATTLEFIELD", "DIES", "ATTACKS", "BLOCKS"})

#: Type words that are *not* creature subtypes — a scope built on one of these
#: isn't a creature anthem/grant, so we don't claim it.
_NONCREATURE_TYPES: frozenset[str] = frozenset(
    {"creature", "artifact", "enchantment", "land", "permanent", "planeswalker", "token"}
)

#: Colour words → their WUBRG/C symbol, for a colour-scoped anthem.
_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G", "colorless": "C",
}

# "[Other] <scope> [you control] get +N/+N [and have <keywords>]"  (anthem, +grant)
_ANTHEM_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ]*?)(?P<yours> you control)? "
    r"get (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    r"(?: and have (?P<kw>[a-z][a-z, ]*))?",
    re.IGNORECASE,
)
# "[Other] <scope> [you control] have <keywords>"  (keyword grant, layer 6)
_GRANT_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ]*?)(?P<yours> you control)? "
    r"have (?P<kw>[a-z][a-z, ]*)",
    re.IGNORECASE,
)

#: Card-type words the "opponent-scoped"/"prohibition"/"type-overwrite"
#: families below recognise as a `card_type` selector (`continuous.
#: _has_card_type` reads the matching `Card.is_<word>` flag) — deliberately
#: small: only the categories that actually appear in this shape on real
#: cards (a spell-only type like "instant" never does, since none of these
#: clauses talk about spells).
_CARD_TYPE_WORDS: frozenset[str] = frozenset(
    {"artifact", "creature", "enchantment", "land", "planeswalker", "permanent"}
)

# "Activated abilities of <type>[s] can't be activated."  (RULE 602 prohibition,
# Collector Ouphe/Stony Silence/Null Rod) — global, not "you control"-scoped:
# it silences *every* qualifying permanent's activated abilities, including
# the prohibiting permanent's own if it itself qualifies (Null Rod is an
# Artifact and its printed text carries no self-exemption).
_ACTIVATION_PROHIBITION_RE = re.compile(
    r"activated abilities of (?P<word>[a-z]+) can'?t be activated", re.IGNORECASE
)

# "<Type> spells cost {N} more/less to cast."  (RULE 601.2f tax/discount,
# Thalia/Thorn of Amethyst/Vryn Wingmare-shaped) — unlike "Spells you cast
# cost {N} less" (self-scoped, already covered by the hand-authored
# `cost_reduction` shape), the bare "<type> spells cost …" phrasing with no
# "you cast"/"your opponents cast" qualifier taxes *everyone*, the caster's
# own controller included.
_SPELL_TYPE_WORDS: frozenset[str] = frozenset(
    {"noncreature", "creature", "artifact", "instant", "sorcery", "enchantment", "planeswalker"}
)
_SPELL_COST_TAX_RE = re.compile(
    r"(?:(?P<word>[a-z]+) )?spells cost \{(?P<n>\d+)\} (?P<dir>more|less) to cast", re.IGNORECASE
)

# "Each player can't cast more than N spell(s) each turn."  (RULE 601-area
# prohibition, Eidolon of Rhetoric/Rule of Law/Archon of Emeria) — a flat,
# unscoped per-player-per-turn cast cap; ``normalize`` already folds a
# spelled-out "one" to "1" before this ever runs.
_CAST_LIMIT_RE = re.compile(
    r"each player can'?t cast more than (?P<n>\d+) spells? each turn", re.IGNORECASE
)

# "~ doesn't untap during your untap step."  (RULE 502.3-adjacent
# self-restriction, Basalt Monolith/Grim Monolith/Mana Vault) — `~` is the
# self-reference token `normalize._fold_self_reference`/`_fold_self_name`
# folds "this artifact"/the card's own printed name to (Card-pool Batch 1),
# so this must match the folded form, not the literal "this <type>" text
# that normalize never leaves in place.
_NO_UNTAP_RE = re.compile(
    r"~ doesn'?t untap during your untap step", re.IGNORECASE
)

# "Creatures entering don't cause abilities to trigger."  (RULE 603
# prohibition, Tocatli Honor Guard/Hushwing Gryff/Torpor Orb) — global: it
# silences *every* triggered ability (including the entering creature's own)
# that would otherwise fire off a matching battlefield-entry event, for as
# long as this static is in play, regardless of whose creature it is.
_TRIGGER_PROHIBITION_RE = re.compile(
    r"(?P<word>[a-z]+) entering don'?t cause abilities to trigger", re.IGNORECASE
)

# "[Nonbasic] <type>[s] [and <type>[s]] your opponents control enter
# tapped."  (RULE 614.1, board-wide — Manglehorn/Dauntless Dismantler's
# "artifacts", Archon of Emeria's "nonbasic lands", Blind Obedience's
# "artifacts and creatures") — distinct from `ability_catalogue.
# enters_tapped` (a card's own printed tapped-entry clause about *itself*):
# this is a standing effect from a *different* permanent, scoped to "your
# opponents" and optionally narrowed to nonbasic. ``words`` may name two
# card types joined by "and" (Blind Obedience), emitting one spec per type.
_OPPONENTS_ENTER_TAPPED_RE = re.compile(
    r"(?:(?P<nonbasic>nonbasic) )?(?P<words>[a-z]+(?: and [a-z]+)?) your opponents control enter tapped",
    re.IGNORECASE,
)

# "[Nonbasic] <type>[s] [and <type>[s]] enter tapped."  (RULE 614.1,
# board-wide, Root Maze-shaped) — the *unscoped* sibling of
# `_OPPONENTS_ENTER_TAPPED_RE`: no "your opponents control" qualifier at
# all, so it applies to every player's matching permanents, including the
# static's own controller's.
_ALL_ENTER_TAPPED_RE = re.compile(
    r"(?:(?P<nonbasic>nonbasic) )?(?P<words>[a-z]+(?: and [a-z]+)?) enter tapped",
    re.IGNORECASE,
)

#: WUBRG basic-land-type word → the mana colour it taps for (RULE 305.6) —
#: a small local copy of `game/mana_abilities.BASIC_LAND_MANA`'s data (the
#: front-end can't import `game/`, and it's five literal pairs, not worth a
#: shared-data indirection).
_BASIC_LAND_COLOR: dict[str, str] = {
    "plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G",
}
#: Singular/plural basic-land-type word → its canonical (capitalised) name.
_BASIC_LAND_WORDS: dict[str, str] = {}
for _name in _BASIC_LAND_COLOR:
    _BASIC_LAND_WORDS[_name] = _name.capitalize()
    _BASIC_LAND_WORDS[_name + "s"] = _name.capitalize()
del _name

# "Nonbasic lands are <BasicType>."  (RULE 613.5 full layer-4 type overwrite,
# board-wide — Magus of the Moon/Blood Moon) — unlike `type_change`'s ordinary
# "are also creatures" shape (which only *adds* a type), this *replaces* the
# land's subtypes outright (RULE 613.5's "loses all other types") and grants
# the corresponding basic land's mana ability (RULE 305.6), so the clause
# emits two specs together: a `type_change` carrying `set_subtypes`, and a
# `grant_mana_ability` for the matching colour.
_TYPE_OVERWRITE_RE = re.compile(r"nonbasic lands are (?P<word>[a-z]+)", re.IGNORECASE)

# "~ can be your commander."  (RULE 903.3 deck-legality permission,
# Jeska/Tevesh Szat-shaped) — a plain-text line with **no in-game behavioral
# effect** (nothing about the battlefield/stack/turn structure changes), so
# unlike every family above this claims the line and emits *nothing* at all —
# the same "claim it, contribute no spec" treatment RULE 614.1 tapped-entry/
# entry-counter clauses get in `gate._process_line`. A generic self-reference
# match (``~``, folded from the card's own name by `normalize`), not
# hardcoded to any one card name.
_COMMANDER_ELIGIBLE_RE = re.compile(r"~ can be your commander", re.IGNORECASE)


def commander_eligibility_line(line: str) -> bool:
    """Whether ``line`` is a RULE 903.3 "~ can be your commander." sentence —
    see `_COMMANDER_ELIGIBLE_RE`. Claimed at the `gate._process_line` level
    (before this module's `static_effect_specs` even runs), not through an
    `EffectSpec`, since it carries no behaviour to bind."""
    return bool(_COMMANDER_ELIGIBLE_RE.fullmatch(line.strip().rstrip(".").strip()))


#: The subject phrases an Aura/Equipment/Fortification's own buff clause is
#: printed with — a closed list (not a general noun-phrase parse like
#: `_scope`, since only these five shapes actually appear on cards) rather
#: than any combination of "equipped/enchanted/fortified" x
#: "creature/land/permanent" ("equipped land"/"fortified creature" don't
#: exist and stay unclaimed).
_ATTACHED_SUBJECTS = (
    "equipped creature",
    "enchanted creature",
    "fortified land",
    "enchanted permanent",
    "enchanted land",
)
_ATTACHED_SUBJECT_PATTERN = "|".join(re.escape(s) for s in _ATTACHED_SUBJECTS)

# "Enchanted/equipped <subject> doesn't untap during its controller's untap
# step."  (RULE 502.3-adjacent, attached-permanent form — e.g. Paralyzing
# Grasp) — the Aura/Equipment-grant sibling of `_NO_UNTAP_RE` above.
_NO_UNTAP_ATTACHED_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) doesn'?t untap during its "
    r"controller'?s untap step",
    re.IGNORECASE,
)

# "~"/an attached-permanent subject can't attack, can't block, can't be
# blocked, or must attack each combat (RULE 508.1a/509.1a self-restrictions)
# — modeled as synthetic layer-6 "keyword" flags (`"cant_attack"`/
# `"cant_block"`/`"cant_be_blocked"`/`"attacks_if_able"`; *not* real RULE 702
# keywords, just internal markers `game/combat.py`'s `has()` and the engine's
# `_can_attack`/`can_block`/attack-declaration enforcement check alongside
# the real keyword union) reusing the exact same `grant_keyword` StaticAbility
# / layer-6 plumbing — zero new engine code for the restriction half. The
# "…and its activated abilities can't be activated" tail reuses the existing
# board-wide `activation_prohibition` family (RULE 602) scoped to just this
# one object instead of a card-type filter — the selector vocabulary
# (``affects="self"``/``"attached_permanent"``) already supports that.
# Deliberately excludes every qualified/conditional variant ("except by…",
# "unless…", "…alone", "…unless they're mana abilities") — `fullmatch` leaves
# the trailing clause unconsumed so those stay unclaimed (fail-closed) rather
# than guess at a different rule.
_COMBAT_RESTRICTION_SUBJECT_PATTERN = rf"~|{_ATTACHED_SUBJECT_PATTERN}"
_CANT_ATTACK_OR_BLOCK_LOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack or "
    r"block, and its activated abilities can'?t be activated",
    re.IGNORECASE,
)
_CANT_ATTACK_OR_BLOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack or block",
    re.IGNORECASE,
)
_CANT_BLOCK_AND_CANT_BE_BLOCKED_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t block and "
    r"can'?t be blocked",
    re.IGNORECASE,
)
_CANT_ATTACK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t attack", re.IGNORECASE
)
_CANT_BLOCK_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t block", re.IGNORECASE
)
_CANT_BE_BLOCKED_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) can'?t be blocked",
    re.IGNORECASE,
)
_ATTACKS_IF_ABLE_RE = re.compile(
    rf"(?P<subject>{_COMBAT_RESTRICTION_SUBJECT_PATTERN}) attacks each combat if able",
    re.IGNORECASE,
)


def _combat_restriction_affects(subject: str) -> str:
    return "self" if subject == "~" else "attached_permanent"


def _combat_restriction_specs(
    subject: str, flags: list[str], lock: bool = False
) -> list[EffectSpec]:
    affects = _combat_restriction_affects(subject)
    specs = [EffectSpec("grant_keyword", {"keywords": flags, "affects": affects})]
    if lock:
        specs.append(EffectSpec("activation_prohibition", {"affects": affects}))
    return specs


# "You control enchanted creature/permanent." (Mind Control/Control Magic-
# shaped, RULE 613.2 layer-2 control-grant) — the existing `control_change`
# `StaticAbility` already defaults to ``affects="attached_permanent"`` and a
# controller of "the source's own controller" (exactly "you"), so this needed
# no new engine code, only the parser recognition.
_CONTROL_GRANT_RE = re.compile(
    r"you control (?:enchanted creature|enchanted permanent)", re.IGNORECASE
)

# "<equipped/enchanted/fortified subject> [gets +N/+N and] has \"<ability>\""
# (Sword-of-X-and-Y/Assassin Gauntlet/Caustic Tar-shaped) — an Aura/Equipment
# granting its host a *full* ability rather than a flag keyword. The quoted
# text is itself an ordinary ability line, so it's parsed the same way any
# top-level card's own line would be (`segmenter.segment_line`, imported
# lazily in `_quoted_ability_grant_specs` below — `segmenter` imports *this*
# module, so a module-level import would cycle) and only wrapped as a
# `grant_triggered_ability` when that recursive parse comes back a plain,
# unconditional, self-scoped trigger on one of `_GRANTABLE_TRIGGER_EVENTS`
# (fail-closed on everything else: an activated-ability grant needs a real
# "grant an activated ability" engine primitive that doesn't exist yet —
# ToDo_EdgeCases #35/Umbral Mantle — and a controller-scoped phase trigger
# like "at the beginning of your upkeep" is a pre-existing gap, not special
# to grants; see `_GRANTABLE_TRIGGER_EVENTS`).
_ATTACHED_QUOTED_ANTHEM_GRANT_RE = re.compile(
    rf'(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) '
    r'and has "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)
_ATTACHED_QUOTED_GRANT_RE = re.compile(
    rf'(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) has "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)


def _quoted_ability_grant_effects(inner: str) -> Optional[EffectSpec]:
    """Recursively parse a quoted granted-ability body into a
    `grant_triggered_ability` `EffectSpec`, or ``None`` if it isn't a plain
    self-scoped trigger on a `_GRANTABLE_TRIGGER_EVENTS` event (see the
    module comment above `_ATTACHED_QUOTED_GRANT_RE`)."""
    from ..segmenter import segment_line  # lazy: segmenter imports this module

    segment = segment_line(
        inner.strip(),
        allow_spell_effect=False,
        provenance=ParserProvenance(version="nested", source="rule:oracle"),
    )
    spec = segment.spec
    if spec is None or spec.ability_kind != "triggered" or spec.modes:
        return None
    trigger = spec.trigger or {}
    if trigger.get("event") not in _GRANTABLE_TRIGGER_EVENTS:
        return None
    if trigger.get("condition") != {"subject": "self"}:
        return None  # a "group"/other subject wouldn't mean the same thing once regranted
    return EffectSpec(
        "grant_triggered_ability",
        {
            "trigger_event": trigger["event"],
            "grant_effects": [{"type": e.type, "params": e.params} for e in spec.effects],
            "optional": spec.optional,
            "affects": "attached_permanent",
        },
    )


# "<equipped/enchanted/fortified subject> gets +N/+N [and has <keywords>]"
# (attached-permanent anthem, +grant) — singular "gets"/"has", unlike the
# plural "get"/"have" of `_ANTHEM_RE`/`_GRANT_RE` above (those two families
# never collide on the same clause text).
_ATTACHED_ANTHEM_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) "
    r"gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    r"(?: and has (?P<kw>[a-z][a-z, ]*))?",
    re.IGNORECASE,
)
# "<equipped/enchanted/fortified subject> has <keywords>"  (keyword-only grant)
_ATTACHED_GRANT_RE = re.compile(
    rf"(?P<subject>{_ATTACHED_SUBJECT_PATTERN}) has (?P<kw>[a-z][a-z, ]*)",
    re.IGNORECASE,
)


class _Scope(NamedTuple):
    subtype: Optional[str]  # a creature type ("Goblin"), or None for "creatures"
    tokens: bool  # True for "<…> tokens" (Intangible Virtue)
    colors: list  # WUBRG/C symbols; empty = no colour restriction (Bad Moon)


def _singularize(word: str) -> str:
    """A plural creature type → singular ("goblins"→"goblin", "elves"→"elf")."""
    if word.endswith("ves"):
        return word[:-3] + "f"
    if word.endswith("s"):
        return word[:-1]
    return word


def _scope(body: str) -> Optional[_Scope]:
    """Parse a scope phrase into a `_Scope`, or ``None`` for a non-creature scope.

    Handles a leading global marker ("all"/"each"), leading colour words
    ("black", "white and blue"), "creatures", a plural type ("goblins"),
    "<type> creatures", and the "<…> tokens" variants — always fail-closed
    (returns ``None`` rather than guess a scope it doesn't recognise).
    """
    words = body.split()
    while words and words[0] in ("all", "each"):  # global emphasis, no scope change
        words = words[1:]

    colors: list = []
    while words:
        if words[0] in _COLOR_WORDS:
            colors.append(_COLOR_WORDS[words[0]])
            words = words[1:]
        elif words[0] in ("and", "or") and len(words) > 1 and words[1] in _COLOR_WORDS:
            words = words[1:]  # skip a colour connector ("white and blue")
        else:
            break

    tokens = False
    if words and words[-1] == "tokens":
        tokens = True
        words = words[:-1]
        if not words:  # bare "tokens" (creature tokens implied)
            return _Scope(None, True, colors)

    if words in (["creature"], ["creatures"]):
        return _Scope(None, tokens, colors)
    if not words:
        return None
    if words[-1] == "creatures":
        sub = _singularize(" ".join(words[:-1]))
    elif len(words) == 1:
        sub = _singularize(words[0])
    else:
        return None  # multi-word non-"creatures" scope — don't guess
    if not sub or sub in _NONCREATURE_TYPES:
        return None
    return _Scope(sub.capitalize(), tokens, colors)


def _scope_params(scope: _Scope, m: "re.Match[str]") -> dict:
    """Build the `affects` + filter params from a scope and the clause match.

    ``affects`` is the base set; "you control" scopes it to the controller (and
    "other" excludes the source), while its absence makes the anthem global
    (RULE 613 — all creatures). Subtype/colour/tokens narrow the set further.
    """
    other = bool(m.group("scope"))
    yours = bool(m.group("yours"))
    if yours:
        params: dict = {"affects": "other_creatures_you_control" if other
                        else "creatures_you_control"}
    else:
        params = {"affects": "all_creatures"}
        if other:  # a global "Other creatures …" excludes just the source
            params["exclude_self"] = True
    if scope.subtype:
        params["subtype"] = scope.subtype
    if scope.tokens:
        params["tokens"] = True
    if scope.colors:
        params["color"] = scope.colors
    return params


def _flag_keywords(text: str) -> Optional[list[str]]:
    """A "have <keywords>" list → flag-keyword slugs, or ``None`` if any isn't a
    parameterless keyword (fail-closed — a granted parametric keyword like
    "ward {2}" or landwalk needs behaviour the grant can't express yet)."""
    slugs: list[str] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        kdef = KEYWORDS.get(keyword_slug(part))
        if kdef is None or kdef.shape is not KeywordShape.FLAG:
            return None
        slugs.append(kdef.slug)
    return slugs or None


def static_effect_specs(clause: str) -> Optional[list[EffectSpec]]:
    """`EffectSpec`s for a static anthem/keyword-grant ``clause``, or ``None``.

    Full-matches the clause (like the one-shot handler table) so a partial or
    "until end of turn" phrasing isn't claimed. A compound "get +N/+N and have
    <keywords>" emits both an ``anthem`` and a ``grant_keyword`` spec. The specs
    carry ``affects`` + optional ``subtype``/``tokens`` for the layer engine.
    Also claims the attached-permanent shape ("equipped/enchanted creature
    gets +N/+N [and has <keywords>]", "equipped/enchanted creature has
    <keywords>") with ``affects="attached_permanent"`` — see
    `_ATTACHED_SUBJECTS` above.
    """
    text = clause.strip().rstrip(".").strip()

    # "This spell can't be countered." (RULE 118-area) — printed on a
    # permanent as a standing line even though it only matters while the
    # object is still a spell on the stack; `catalogue.handlers` claims the
    # identical phrase for the instant/sorcery spell_effect path, see
    # `CANT_BE_COUNTERED_RE`'s docstring for why both need it.
    if CANT_BE_COUNTERED_RE.fullmatch(text):
        return [EffectSpec("cant_be_countered", {})]

    m = _ACTIVATION_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        card_type = _singularize(m.group("word"))
        if card_type not in _CARD_TYPE_WORDS:
            return None  # fail-closed — an unrecognised type-scope
        return [EffectSpec("activation_prohibition", {"card_type": card_type})]

    m = _SPELL_COST_TAX_RE.fullmatch(text)
    if m is not None:
        word = (m.group("word") or "").lower()
        # A bare "spells cost {N} more/less to cast" (no type word — Sphere of
        # Resistance) taxes *every* spell: a falsy ``spell_type`` means "no
        # type filter" in `continuous.cost_reduction_for`. A typed variant
        # must name a recognised card type (fail-closed).
        if word and word not in _SPELL_TYPE_WORDS:
            return None
        params: dict = {
            "affects": "all_spells",
            "generic": int(m.group("n")),
            "increase": m.group("dir") == "more",
        }
        if word:
            params["spell_type"] = word
        return [EffectSpec("cost_reduction", params)]

    m = _CAST_LIMIT_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("cast_limit", {"max_per_turn": int(m.group("n"))})]

    if _NO_UNTAP_RE.fullmatch(text):
        return [EffectSpec("no_untap", {"affects": "self"})]

    m = _NO_UNTAP_ATTACHED_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("no_untap", {"affects": "attached_permanent"})]

    m = _TRIGGER_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        subject_type = _singularize(m.group("word"))
        if subject_type not in _CARD_TYPE_WORDS:
            return None
        return [
            EffectSpec(
                "trigger_prohibition",
                {"event": "ENTERS_BATTLEFIELD", "subject_type": subject_type},
            )
        ]

    m = _OPPONENTS_ENTER_TAPPED_RE.fullmatch(text)
    if m is not None:
        card_types = [_singularize(w) for w in m.group("words").split(" and ")]
        if any(t not in _CARD_TYPE_WORDS for t in card_types):
            return None
        specs = []
        for card_type in card_types:
            params: dict = {"affects": "opponents_permanents", "card_type": card_type}
            if m.group("nonbasic"):
                params["nonbasic"] = True
            specs.append(EffectSpec("enters_tapped_static", params))
        return specs

    m = _ALL_ENTER_TAPPED_RE.fullmatch(text)
    if m is not None:
        card_types = [_singularize(w) for w in m.group("words").split(" and ")]
        if any(t not in _CARD_TYPE_WORDS for t in card_types):
            return None
        specs = []
        for card_type in card_types:
            params = {"affects": "all_permanents", "card_type": card_type}
            if m.group("nonbasic"):
                params["nonbasic"] = True
            specs.append(EffectSpec("enters_tapped_static", params))
        return specs

    m = _TYPE_OVERWRITE_RE.fullmatch(text)
    if m is not None:
        basic_type = _BASIC_LAND_WORDS.get(m.group("word").lower())
        if basic_type is None:
            return None  # fail-closed — an unrecognised "are <X>" overwrite
        color = _BASIC_LAND_COLOR[basic_type.lower()]
        shared = {"affects": "all_lands", "nonbasic": True}
        return [
            EffectSpec("type_change", {**shared, "set_subtypes": [basic_type]}),
            EffectSpec("grant_mana_ability", {**shared, "mana": [{color: 1}]}),
        ]

    # Attached-permanent shape first ("equipped creature gets +2/+2 [and has
    # <keywords>]") — a closed subject list, so this never competes with the
    # "you control" scopes below (singular "gets"/"has" vs. their plural
    # "get"/"have"). `affects="attached_permanent"` is honoured by both
    # `anthem` (layer 7c) and `grant_keyword` (layer 6) in `game/continuous.py`.
    m = _ATTACHED_ANTHEM_RE.fullmatch(text)
    if m is not None:
        specs = [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"})
        ]
        if m.group("kw"):  # "… and has <keywords>" tail
            keywords = _flag_keywords(m.group("kw"))
            if keywords is None:
                return None  # e.g. a granted landwalk — fail-closed, whole clause
            specs.append(EffectSpec("grant_keyword", {"keywords": keywords,
                                                        "affects": "attached_permanent"}))
        return specs

    # Attached-permanent keyword-only grant ("equipped creature has trample").
    m = _ATTACHED_GRANT_RE.fullmatch(text)
    if m is not None:
        keywords = _flag_keywords(m.group("kw"))
        if keywords is None:
            return None
        return [EffectSpec("grant_keyword", {"keywords": keywords, "affects": "attached_permanent"})]

    # Combat-restriction family ("~ can't attack.", "enchanted creature can't
    # be blocked.", "~ attacks each combat if able.", …) — see
    # `_combat_restriction_specs` above. Ordered most-specific-first so a
    # combined clause matches its own row rather than a shorter prefix; since
    # every branch uses `fullmatch`, a shorter regex simply fails on any
    # unconsumed trailing text (fail-closed), so the ordering is for clarity
    # rather than correctness.
    m = _CANT_ATTACK_OR_BLOCK_LOCK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_attack", "cant_block"], lock=True)

    m = _CANT_ATTACK_OR_BLOCK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_attack", "cant_block"])

    m = _CANT_BLOCK_AND_CANT_BE_BLOCKED_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_block", "cant_be_blocked"])

    m = _CANT_ATTACK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_attack"])

    m = _CANT_BLOCK_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_block"])

    m = _CANT_BE_BLOCKED_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["cant_be_blocked"])

    m = _ATTACKS_IF_ABLE_RE.fullmatch(text)
    if m is not None:
        return _combat_restriction_specs(m.group("subject"), ["attacks_if_able"])

    if _CONTROL_GRANT_RE.fullmatch(text):
        return [EffectSpec("control_change", {})]

    m = _ATTACHED_QUOTED_ANTHEM_GRANT_RE.fullmatch(text)
    if m is not None:
        grant = _quoted_ability_grant_effects(m.group("inner"))
        if grant is None:
            return None
        return [
            EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")),
                                   "affects": "attached_permanent"}),
            grant,
        ]

    m = _ATTACHED_QUOTED_GRANT_RE.fullmatch(text)
    if m is not None:
        grant = _quoted_ability_grant_effects(m.group("inner"))
        if grant is None:
            return None
        return [grant]

    m = _ANTHEM_RE.fullmatch(text)
    if m is not None:
        scope = _scope(m.group("body"))
        if scope is None:
            return None
        params = _scope_params(scope, m)
        specs = [
            EffectSpec("anthem",
                       {"power": int(m.group("p")), "toughness": int(m.group("t")), **params})
        ]
        if m.group("kw"):  # "… and have <keywords>" tail
            keywords = _flag_keywords(m.group("kw"))
            if keywords is None:
                return None  # e.g. a granted landwalk — fail-closed, whole clause
            specs.append(EffectSpec("grant_keyword", {"keywords": keywords, **params}))
        return specs

    m = _GRANT_RE.fullmatch(text)
    if m is not None:
        scope = _scope(m.group("body"))
        if scope is None:
            return None
        keywords = _flag_keywords(m.group("kw"))
        if keywords is None:
            return None
        return [EffectSpec("grant_keyword", {"keywords": keywords, **_scope_params(scope, m)})]

    return None
