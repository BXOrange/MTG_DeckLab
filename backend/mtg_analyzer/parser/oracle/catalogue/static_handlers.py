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

from ..spec import EffectSpec
from .keywords import KEYWORDS, KeywordShape, keyword_slug
from .subgrammars import CANT_BE_COUNTERED_RE

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
