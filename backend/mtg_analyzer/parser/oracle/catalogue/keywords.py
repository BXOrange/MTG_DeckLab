"""The keyword-ability catalogue — RULE 702, the privileged fast-path handler.

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("Keyword abilities: the
privileged fast-path handler class"); the vocabulary itself is RULE 702
(``docs/Reference/rules_wiki/`` maps ``702.<n>`` → its line in the CR source).

Keyword abilities are a **closed, named vocabulary** — the cheapest,
highest-confidence, most frequent clauses in the game — so we treat them as
a first-class handler class rather than free-text regex. Every keyword here
is one row: its canonical slug, display name, the CR rule that defines it,
and its **shape**:

* ``FLAG``        — no parameter (``Flying``, ``Deathtouch``) → a bare
  ``keyword`` `AbilitySpec`.
* ``NUMBER``      — ``Keyword N`` (``Annihilator 2``, ``Toxic 1``).
* ``COST``        — ``Keyword {cost}`` (``Kicker {2}{R}``, ``Ward {2}``),
  possibly after a dash or a short qualifier (``Equip Bird {2}``,
  ``Escape—{2}{B}{B}``).
* ``NUMBER_COST`` — ``Keyword N—{cost}`` (``Suspend 4—{1}{U}``,
  ``Reinforce 2—{1}{G}``).
* ``QUALITY``     — a word/phrase parameter that is neither a number nor a
  mana cost (``Protection from red``, ``Islandwalk``, ``Enchant creature``).

Parametric shapes carry a compiled **regex** that pulls the one parameter
out of the card's oracle line; the flag shapes need none. The regex for the
regular shapes is generated from the display name; the handful of irregular
`QUALITY` keywords get a hand-written pattern (below).

Pure data + regex only — **no `game/` imports** (docs/09: the front-end is
the security boundary; it emits whitelisted `{name, param}` data, never
behaviour). Binding a keyword spec to engine behaviour is the back-end's
job and is deliberately still out of scope here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from ..spec import AbilitySpec, ParserProvenance

if TYPE_CHECKING:  # pragma: no cover - typing only; keeps the front-end pure
    from ....models.card import Card


class KeywordShape(Enum):
    """How a keyword carries its parameter (docs/09 "Two shapes")."""

    FLAG = "flag"
    NUMBER = "number"
    COST = "cost"
    NUMBER_COST = "number_cost"
    QUALITY = "quality"


_PARAMETRIC: frozenset[KeywordShape] = frozenset(
    {KeywordShape.NUMBER, KeywordShape.COST, KeywordShape.NUMBER_COST, KeywordShape.QUALITY}
)

#: A run of one or more mana/cost symbols — ``{2}{R}``, ``{W/U}``, ``{X}`` —
#: allowing whitespace between pips. ``[^}]+`` keeps each pip opaque so hybrid
#: and Phyrexian symbols pass through untouched.
_COST_RUN = r"\{[^}]+\}(?:\s*\{[^}]+\})*"

#: The gap the cost extractor may skip between the keyword name and the cost:
#: a short qualifier ("Equip Bird ", "Craft with three artifacts ") or a dash,
#: but never across a sentence end or into the braces themselves.
_GAP = r"[^.\n{]*?"


def _slug(name: str) -> str:
    """A display/Scryfall keyword name → its canonical catalogue slug.

    ``"First Strike"`` → ``"first_strike"``, ``"Jump-Start"`` →
    ``"jump_start"``, ``"For Mirrodin!"`` → ``"for_mirrodin"``, ``"∞"`` →
    ``"infinity"``. Matches how Scryfall's ``keywords`` array normalizes once
    lowercased, so the array can anchor the pass by slug.
    """
    s = name.strip().lower().replace("∞", "infinity")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


# --- The irregular QUALITY keywords: one hand-written extractor each --------
# Their parameter is a word/phrase, not a number or a cost, so each needs its
# own small anchored regex (the shared cost/number builders don't apply).

_SPECIAL_REGEX: dict[str, re.Pattern[str]] = {
    # RULE 702.16 — "protection from <quality>" up to the clause end.
    "protection": re.compile(
        r"protection from (?P<quality>[a-z][a-z ]*?)(?=[.,;\n)]|$| and )", re.I
    ),
    # RULE 702.5 — "Enchant <what it can be attached to>". Stops before a
    # trailing controller clause ("... you control" / "... an opponent
    # controls") so ``quality`` is the bare type ("creature"), not the whole
    # clause — the attachment-legality checks match on that type alone.
    "enchant": re.compile(
        r"\benchant\s+(?P<quality>[a-z][a-z ]*?)"
        r"(?=\s+(?:you|an opponent)\b|[.\n(]|$)",
        re.I,
    ),
    # RULE 702.14 — "<type>walk"; also matched by slug prefix in parse_keywords.
    "landwalk": re.compile(r"\b(?P<quality>[a-z]+)walk\b", re.I),
    # RULE 702.41 — "affinity for <type>".
    "affinity": re.compile(r"affinity for (?P<quality>[a-z][a-z ]*?)(?=[.\n(]|$)", re.I),
    # RULE 702.48 — "<type> offering".
    "offering": re.compile(r"(?P<quality>[a-z]+) offering", re.I),
    # RULE 702.72 — "Champion a/an <type>".
    "champion": re.compile(r"champion an? (?P<quality>[a-z][a-z ]*?)(?=[.\n(]|$)", re.I),
    # RULE 702.174 — "Gift a/an <something>".
    "gift": re.compile(r"gift an? (?P<quality>[a-z][a-z ]*?)(?=[.\n(]|$)", re.I),
}

#: Ward's cost line may be a non-mana clause ("Ward—Discard a card.",
#: "Ward—Pay 3 life.", "Ward—Sacrifice a creature.") that the mana-only
#: ``_auto_regex`` COST pattern above can't see (RULE 702.21 puts no
#: constraint on the cost's shape, unlike most other COST-shaped keywords in
#: this table, which are mana-only on every real card). Captured as free
#: text — not whitespace-collapsed like a mana run — so
#: `game/costs.parse_activation_cost` (the same grammar a "<cost>: <effect>"
#: activated ability's cost already goes through, RULE 602.1) can recognize
#: it downstream. Only consulted as a fallback when the mana regex above
#: finds nothing.
_WARD_TEXT_COST_RE = re.compile(
    r"\bward\b[\s—-]*(?P<cost>[a-zA-Z][^.\n(]*?)\s*(?=[.\n(]|$)", re.I
)

#: Escape's cost line is a comma-joined "{mana}, Exile N other cards from
#: your graveyard" (RULE 702.138b) — the mana-only ``_auto_regex`` COST
#: pattern above only ever sees the ``{...}`` pips, silently dropping the
#: exile-count clause. Unlike Ward's fallback (only consulted when the mana
#: regex finds nothing), this one always wins for Escape: the full clause is
#: needed downstream, not just the mana portion, so `game/costs.
#: parse_activation_cost` can recognize both components together.
_ESCAPE_TEXT_COST_RE = re.compile(
    r"\bescape\b[\s—-]*(?P<cost>[^.\n(]*?)\s*(?=[.\n(]|$)", re.I
)


def _auto_regex(display: str, shape: KeywordShape) -> Optional[re.Pattern[str]]:
    """The parameter extractor for a *regular* parametric keyword.

    Built from the display name, so ``Annihilator`` → ``Annihilator (\\d+)``
    and ``Kicker`` → ``Kicker … {cost}``. Returns ``None`` for ``FLAG`` (no
    parameter) and ``QUALITY`` (which uses a hand-written ``_SPECIAL_REGEX``).
    """
    name = re.escape(display)
    if shape is KeywordShape.NUMBER:
        return re.compile(rf"{name}\s+(?P<n>\d+)", re.I)
    if shape is KeywordShape.COST:
        return re.compile(rf"{name}{_GAP}(?P<cost>{_COST_RUN})", re.I)
    if shape is KeywordShape.NUMBER_COST:
        return re.compile(rf"{name}\s+(?P<n>\d+){_GAP}(?P<cost>{_COST_RUN})", re.I)
    return None


@dataclass(frozen=True)
class KeywordDef:
    """One catalogue row: a keyword's identity, shape, and param extractor."""

    slug: str
    display: str
    shape: KeywordShape
    rule: str
    regex: Optional[re.Pattern[str]] = None

    @property
    def is_parametric(self) -> bool:
        return self.shape in _PARAMETRIC


# --- The vocabulary ---------------------------------------------------------
# (display, shape, RULE) for every keyword ability in RULE 702, in CR order.
# The slug and — for parametric shapes — the extractor regex are derived.

_F, _N, _C, _NC, _Q = (
    KeywordShape.FLAG,
    KeywordShape.NUMBER,
    KeywordShape.COST,
    KeywordShape.NUMBER_COST,
    KeywordShape.QUALITY,
)

_TABLE: list[tuple[str, KeywordShape, str]] = [
    ("Deathtouch", _F, "702.2"),
    ("Defender", _F, "702.3"),
    ("Double Strike", _F, "702.4"),
    ("Enchant", _Q, "702.5"),
    ("Equip", _C, "702.6"),
    ("First Strike", _F, "702.7"),
    ("Flash", _F, "702.8"),
    ("Flying", _F, "702.9"),
    ("Haste", _F, "702.10"),
    ("Hexproof", _F, "702.11"),
    ("Indestructible", _F, "702.12"),
    ("Intimidate", _F, "702.13"),
    ("Landwalk", _Q, "702.14"),
    ("Lifelink", _F, "702.15"),
    ("Protection", _Q, "702.16"),
    ("Reach", _F, "702.17"),
    ("Shroud", _F, "702.18"),
    ("Trample", _F, "702.19"),
    ("Vigilance", _F, "702.20"),
    ("Ward", _C, "702.21"),
    ("Banding", _F, "702.22"),
    ("Rampage", _N, "702.23"),
    ("Cumulative Upkeep", _C, "702.24"),
    ("Flanking", _F, "702.25"),
    ("Phasing", _F, "702.26"),
    ("Buyback", _C, "702.27"),
    ("Shadow", _F, "702.28"),
    ("Cycling", _C, "702.29"),
    ("Echo", _C, "702.30"),
    ("Horsemanship", _F, "702.31"),
    ("Fading", _N, "702.32"),
    ("Kicker", _C, "702.33"),
    ("Flashback", _C, "702.34"),
    ("Madness", _C, "702.35"),
    ("Fear", _F, "702.36"),
    ("Morph", _C, "702.37"),
    ("Amplify", _N, "702.38"),
    ("Provoke", _F, "702.39"),
    ("Storm", _F, "702.40"),
    ("Affinity", _Q, "702.41"),
    ("Entwine", _C, "702.42"),
    ("Modular", _N, "702.43"),
    ("Sunburst", _F, "702.44"),
    ("Bushido", _N, "702.45"),
    ("Soulshift", _N, "702.46"),
    ("Splice", _C, "702.47"),
    ("Offering", _Q, "702.48"),
    ("Ninjutsu", _C, "702.49"),
    ("Epic", _F, "702.50"),
    ("Convoke", _F, "702.51"),
    ("Dredge", _N, "702.52"),
    ("Transmute", _C, "702.53"),
    ("Bloodthirst", _N, "702.54"),
    ("Haunt", _F, "702.55"),
    ("Replicate", _C, "702.56"),
    ("Forecast", _C, "702.57"),
    ("Graft", _N, "702.58"),
    ("Recover", _C, "702.59"),
    ("Ripple", _N, "702.60"),
    ("Split Second", _F, "702.61"),
    ("Suspend", _NC, "702.62"),
    ("Vanishing", _N, "702.63"),
    ("Absorb", _N, "702.64"),
    ("Aura Swap", _C, "702.65"),
    ("Delve", _F, "702.66"),
    ("Fortify", _C, "702.67"),
    ("Frenzy", _N, "702.68"),
    ("Gravestorm", _F, "702.69"),
    ("Poisonous", _N, "702.70"),
    ("Transfigure", _C, "702.71"),
    ("Champion", _Q, "702.72"),
    ("Changeling", _F, "702.73"),
    ("Evoke", _C, "702.74"),
    ("Hideaway", _N, "702.75"),
    ("Prowl", _C, "702.76"),
    ("Reinforce", _NC, "702.77"),
    ("Conspire", _F, "702.78"),
    ("Persist", _F, "702.79"),
    ("Wither", _F, "702.80"),
    ("Retrace", _F, "702.81"),
    ("Devour", _N, "702.82"),
    ("Exalted", _F, "702.83"),
    ("Unearth", _C, "702.84"),
    ("Cascade", _F, "702.85"),
    ("Annihilator", _N, "702.86"),
    ("Level Up", _C, "702.87"),
    ("Rebound", _F, "702.88"),
    ("Umbra Armor", _F, "702.89"),
    ("Infect", _F, "702.90"),
    ("Battle Cry", _F, "702.91"),
    ("Living Weapon", _F, "702.92"),
    ("Undying", _F, "702.93"),
    ("Miracle", _C, "702.94"),
    ("Soulbond", _F, "702.95"),
    ("Overload", _C, "702.96"),
    ("Scavenge", _C, "702.97"),
    ("Unleash", _F, "702.98"),
    ("Cipher", _F, "702.99"),
    ("Evolve", _F, "702.100"),
    ("Extort", _F, "702.101"),
    ("Fuse", _F, "702.102"),
    ("Bestow", _C, "702.103"),
    ("Tribute", _N, "702.104"),
    ("Dethrone", _F, "702.105"),
    ("Hidden Agenda", _F, "702.106"),
    ("Outlast", _C, "702.107"),
    ("Prowess", _F, "702.108"),
    ("Dash", _C, "702.109"),
    ("Exploit", _F, "702.110"),
    ("Menace", _F, "702.111"),
    ("Renown", _N, "702.112"),
    ("Awaken", _NC, "702.113"),
    ("Devoid", _F, "702.114"),
    ("Ingest", _F, "702.115"),
    ("Myriad", _F, "702.116"),
    ("Surge", _C, "702.117"),
    ("Skulk", _F, "702.118"),
    ("Emerge", _C, "702.119"),
    ("Escalate", _C, "702.120"),
    ("Melee", _F, "702.121"),
    ("Crew", _N, "702.122"),
    ("Fabricate", _N, "702.123"),
    ("Partner", _F, "702.124"),
    ("Undaunted", _F, "702.125"),
    ("Improvise", _F, "702.126"),
    ("Aftermath", _F, "702.127"),
    ("Embalm", _C, "702.128"),
    ("Eternalize", _C, "702.129"),
    ("Afflict", _N, "702.130"),
    ("Ascend", _F, "702.131"),
    ("Assist", _F, "702.132"),
    ("Jump-Start", _F, "702.133"),
    ("Mentor", _F, "702.134"),
    ("Afterlife", _N, "702.135"),
    ("Riot", _F, "702.136"),
    ("Spectacle", _C, "702.137"),
    ("Escape", _C, "702.138"),
    ("Companion", _F, "702.139"),
    ("Mutate", _C, "702.140"),
    ("Encore", _C, "702.141"),
    ("Boast", _C, "702.142"),
    ("Foretell", _C, "702.143"),
    ("Demonstrate", _F, "702.144"),
    ("Daybound", _F, "702.145"),
    ("Nightbound", _F, "702.145"),
    ("Disturb", _C, "702.146"),
    ("Decayed", _F, "702.147"),
    ("Cleave", _C, "702.148"),
    ("Training", _F, "702.149"),
    ("Compleated", _F, "702.150"),
    ("Reconfigure", _C, "702.151"),
    ("Blitz", _C, "702.152"),
    ("Casualty", _N, "702.153"),
    ("Enlist", _F, "702.154"),
    ("Read Ahead", _F, "702.155"),
    ("Ravenous", _F, "702.156"),
    ("Squad", _C, "702.157"),
    ("Space Sculptor", _F, "702.158"),
    ("Visit", _F, "702.159"),
    ("Prototype", _C, "702.160"),
    ("Living Metal", _F, "702.161"),
    ("More Than Meets the Eye", _C, "702.162"),
    ("For Mirrodin!", _F, "702.163"),
    ("Toxic", _N, "702.164"),
    ("Backup", _N, "702.165"),
    ("Bargain", _F, "702.166"),
    ("Craft", _C, "702.167"),
    ("Disguise", _C, "702.168"),
    ("Solved", _F, "702.169"),
    ("Plot", _C, "702.170"),
    ("Saddle", _N, "702.171"),
    ("Spree", _F, "702.172"),
    ("Freerunning", _C, "702.173"),
    ("Gift", _Q, "702.174"),
    ("Offspring", _C, "702.175"),
    ("Impending", _NC, "702.176"),
    ("Exhaust", _F, "702.177"),
    ("Max Speed", _F, "702.178"),
    ("Start Your Engines!", _F, "702.179"),
    ("Harmonize", _C, "702.180"),
    ("Mobilize", _N, "702.181"),
    ("Job Select", _F, "702.182"),
    ("Tiered", _F, "702.183"),
    ("Station", _F, "702.184"),
    ("Warp", _C, "702.185"),
    ("Infinity", _F, "702.186"),  # the ∞ keyword
    ("Mayhem", _C, "702.187"),
    ("Web-slinging", _C, "702.188"),
    ("Firebending", _N, "702.189"),
    ("Sneak", _C, "702.190"),
    ("Increment", _F, "702.191"),
    ("Paradigm", _F, "702.192"),
    ("Power-up", _F, "702.193"),
    ("Teamwork", _N, "702.194"),
]


def _build_catalogue() -> dict[str, KeywordDef]:
    catalogue: dict[str, KeywordDef] = {}
    for display, shape, rule in _TABLE:
        slug = _slug(display)
        regex = _SPECIAL_REGEX.get(slug) or _auto_regex(display, shape)
        catalogue[slug] = KeywordDef(slug, display, shape, rule, regex)
    return catalogue


#: slug → `KeywordDef` for the whole RULE 702 vocabulary.
KEYWORDS: dict[str, KeywordDef] = _build_catalogue()

#: Printed/Scryfall spellings that map onto a base keyword slug. Variants
#: (Multikicker/Kicker), reworded names (Totem armor/Umbra armor), and the
#: "<base> with/from <x>" forms all resolve to the base row.
_ALIASES: dict[str, str] = {
    "multikicker": "kicker",
    "typecycling": "cycling",
    "landcycling": "cycling",
    "megamorph": "morph",
    "totem_armor": "umbra_armor",
    "partner_with": "partner",
    "hexproof_from": "hexproof",
    "double_agenda": "hidden_agenda",
    "bands_with_other": "banding",
    "friends_forever": "partner",
}


def keyword_slug(name: str) -> str:
    """A Scryfall/display keyword name → its canonical catalogue slug.

    Applies `_slug` then resolves aliases, so ``"Multikicker"`` and
    ``"Totem armor"`` land on ``"kicker"`` / ``"umbra_armor"``.
    """
    slug = _slug(name)
    return _ALIASES.get(slug, slug)


def _resolve(slug: str) -> Optional[KeywordDef]:
    """Look a slug up in the catalogue, honouring the ``<type>walk`` family.

    Scryfall names landwalk by its specific variant (``"Islandwalk"``), so a
    slug ending in ``walk`` that isn't a catalogue row resolves to the generic
    ``landwalk`` row (the land-type prefix becomes its ``quality``).
    """
    kdef = KEYWORDS.get(slug)
    if kdef is not None:
        return kdef
    if slug.endswith("walk") and len(slug) > 4:
        return KEYWORDS["landwalk"]
    return None


def _clause_for(text: str, display: str) -> str:
    """The oracle line the keyword appears on, for the spec's provenance."""
    pattern = re.compile(r"\b" + re.escape(display), re.I)
    for line in text.splitlines():
        if pattern.search(line):
            return line.strip()
    return display


def _extract_param(kdef: KeywordDef, text: str, forced_quality: Optional[str]) -> dict:
    """Build the keyword's ``{name, param?}`` dict, extracting from oracle text.

    Fail-safe: if a parametric keyword's regex finds nothing, the parameter
    is simply omitted rather than guessed — a bare, still-valid keyword spec
    (docs/09 "fail-closed"). Ward (RULE 702.21) and Escape (RULE 702.138)
    are the two exceptions: their cost is genuinely modeled downstream
    (`game/costs.parse_activation_cost`), not merely carried, so each falls
    back to its own free-text regex instead of staying mana-only/bare.
    """
    param: dict = {"name": kdef.slug}
    if forced_quality:
        param["quality"] = forced_quality
        return param
    if kdef.is_parametric and kdef.regex is not None:
        match = kdef.regex.search(text)
        if match:
            groups = match.groupdict()
            if groups.get("n") is not None:
                param["n"] = int(groups["n"])
            if groups.get("cost"):
                param["cost"] = re.sub(r"\s+", "", groups["cost"])
            if groups.get("quality"):
                param["quality"] = groups["quality"].strip()
    if kdef.slug == "ward" and "cost" not in param:
        fallback = _WARD_TEXT_COST_RE.search(text)
        if fallback:
            param["cost"] = fallback.group("cost").strip()
    if kdef.slug == "escape":
        # Always prefer the full clause over the mana-only match above (if
        # any) — Escape's exile-count component only lives in this capture.
        fallback = _ESCAPE_TEXT_COST_RE.search(text)
        if fallback:
            param["cost"] = fallback.group("cost").strip()
    return param


def parse_keywords(card: "Card") -> list[AbilitySpec]:
    """Every keyword ability on ``card`` as a validated ``keyword`` `AbilitySpec`.

    Anchored on Scryfall's machine-readable ``keywords`` array (docs/09: "use
    it to anchor the keyword pass" — a lookup, not parsing), the card's oracle
    text supplies each parametric keyword's parameter. Unknown keyword names
    are skipped (fail-closed: never a wrong guess). Order and de-duplication
    follow the ``keywords`` array.
    """
    names = list(getattr(card, "keywords", None) or [])
    text = getattr(card, "oracle_text", "") or ""
    if not any(keyword_slug(str(n)) == "enchant" for n in names) and re.search(
        r"^enchant\b", text, re.I | re.M
    ):
        # Scryfall's keyword array frequently omits "Enchant" even when the card
        # has other keywords (e.g. an Aura with Flash) — oracle text is the
        # ground truth for attachment, so always cross-check it independently.
        names.append("Enchant")
    # Daybound/Nightbound (RULE 702.145) live on opposite faces of a DFC, but
    # Scryfall's top-level ``keywords`` array isn't reliably face-scoped —
    # this card's own ``oracle_text`` (already correctly isolated per face by
    # `Card.back_face`) is the ground truth for *which* of the two applies to
    # whichever face is currently bound, so cross-check it the same way as
    # "Enchant" above rather than trusting the shared array either way.
    for kw_name in ("Daybound", "Nightbound"):
        slug = keyword_slug(kw_name)
        if not any(keyword_slug(str(n)) == slug for n in names) and re.search(
            rf"^{slug}\b", text, re.I | re.M
        ):
            names.append(kw_name)
    # A Leveler's ``LEVEL`` blocks (RULE 711.4c) print keywords that only
    # apply at that tier (e.g. Kargan Dragonlord's "Flying, haste" under
    # "LEVEL 7+"), but Scryfall's ``keywords`` array is position-blind — it
    # lists any keyword word found anywhere in the text, tier or not. Trusting
    # it unconditionally here would bind Flying/Haste as *always-on*
    # intrinsic keywords, which is wrong (RULE 613.6 — they should apply only
    # while `level` is in that tier's range). Cross-check against the base
    # text instead (the same "oracle text is ground truth" pattern as Enchant/
    # Daybound above); a tier-only keyword is dropped here and re-granted,
    # correctly level-gated, by the level-block parser (`gate.py`) instead.
    if getattr(card, "is_leveler", False):
        from .levels import leveler_base_text

        base_text = leveler_base_text(text)

        def _in_base_text(raw_name: Any) -> bool:
            kdef = _resolve(keyword_slug(str(raw_name)))
            if kdef is None:  # unknown keyword — let the main loop skip it
                return True
            return bool(re.search(rf"\b{re.escape(kdef.display)}\b", base_text, re.I))

        names = [n for n in names if _in_base_text(n)]
    specs: list[AbilitySpec] = []
    seen: set[str] = set()

    for raw_name in names:
        slug = keyword_slug(str(raw_name))
        kdef = _resolve(slug)
        if kdef is None:  # unknown keyword — skip, never guess (fail-closed)
            continue
        # A landwalk variant ("Islandwalk") carries its land type in the slug.
        forced_quality = (
            slug[:-4]
            if kdef.slug == "landwalk" and slug.endswith("walk") and slug != "landwalk"
            else None
        )
        # De-dupe on the resolved identity + a landwalk's type, so "Islandwalk"
        # and "Forestwalk" both survive but a repeated "Flying" does not.
        dedupe_key = kdef.slug + (forced_quality or "")
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        param = _extract_param(kdef, text, forced_quality)
        if _slug(str(raw_name)) == "multikicker":
            # RULE 702.34a: Multikicker is Kicker's repeatable variant — both
            # alias onto the same "kicker" slug/behaviour, but the "may pay
            # this cost any number of times" identity must survive the alias
            # collapse or a Multikicker card is indistinguishable from plain
            # Kicker post-parse.
            param["multi"] = True
        spec = AbilitySpec(
            ability_kind="keyword",
            keyword=param,
            raw_text=_clause_for(text, kdef.display),
            parser=ParserProvenance(version="1", source=f"rule:{kdef.rule}"),
        )
        specs.append(spec.validate())

    return specs
