"""Step 1 of the front-end pipeline: normalize oracle text (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE FRONT-END PIPELINE",
step 1 NORMALIZE). Turns a card's printed rules text into a canonical form
the segmenter and handler regexes can match against without each pattern
having to re-handle reminder text, capitalisation, spelled-out numbers, or
the card referring to itself by name.

Pure text→text; **no `game/` imports** (the front-end is the security
boundary — docs/09). Deliberately conservative: it only folds forms that are
unambiguous, so a handler that fails to match falls through to the coverage
gate rather than matching a mis-normalized string.
"""

from __future__ import annotations

import re
from typing import Optional

#: Reminder text is always fully parenthesised (RULE 207.2) and never nests, so
#: repeatedly peeling the innermost parens removes it without a real grammar.
_REMINDER = re.compile(r"\s*\([^()]*\)")

#: Spelled-out small numbers → digits. Capped at twelve — larger counts are
#: printed as digits on real cards, and "a"/"an" stay words (a handler that
#: wants "a card" == "1 card" folds that itself, so we don't corrupt the many
#: non-numeric "a"/"an" occurrences here).
_NUMBER_WORDS: dict[str, str] = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12",
}
_NUMBER_WORD_RE = re.compile(
    r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE
)

#: The self-reference placeholder a card's own name folds to, so one handler
#: matches every card ("~ deals 3 damage" regardless of the printed name).
SELF = "~"

#: Type-worded self-references — modern templating writes an ability's own
#: source as "this creature"/"this permanent"/… rather than repeating the
#: printed name (RULE 602/604). Folding them to ``~`` too lets the same
#: handlers that already accept ``~`` cover the "this <type>" phrasing without
#: each regex re-listing every noun (many already list a subset as literal
#: alternatives — this makes the canonicalisation uniform). Deliberately
#: **excludes** references that are *not* the resolving source-permanent:
#: "this spell" (the object on the stack), "this card" (often a zone-scoped
#: reference), "this ability", and the structured card types with their own
#: dedicated parsing ("this Saga"/"this Class"). Runs after lowercasing.
#:
#: "this battle"/"this Siege" (RULE 310) *are* included: unlike a Saga's
#: chapters, a battle's own text has no positional structure a dedicated
#: parse would need, so its clauses are ordinary triggers/effects about the
#: resolving permanent — which is exactly what ``~`` means. Every real
#: battle writes its ETB as "when this Siege enters, …", so without this
#: fold the whole card type is UNMODELED on its first line.
#:
#: "this Spacecraft"/"this Planet" (RULE 702.184/721 Station) are the same
#: shape as battle/Siege above, for the same reason: a Station permanent's
#: bracket-less lines (RULE 721.4 — "When this Spacecraft enters, …",
#: "Whenever this Spacecraft attacks, …", "{cost}: This Spacecraft gets
#: …") are ordinary ETB/attack/pump abilities about the resolving
#: permanent, and the vast majority of cached Station Spacecraft print at
#: least one of them this way — without this fold, almost no Station
#: Spacecraft could ever reach `MODELED` regardless of `catalogue.station`'s
#: own bracket-splitting grammar. "Planet" (the Station land subtype) is
#: included too even though no cached card's *body* text needs it yet (only
#: its own Station reminder clause, already stripped by `normalize`'s
#: generic parenthetical removal before this ever runs) — same reasoning,
#: cheap to cover pre-emptively.
#: "this Case" (RULE 719, PAR-28) is the same shape as battle/Siege above:
#: a Case's clauses ("When this Case enters, …", "To solve — …", "Solved —
#: Sacrifice this Case: …") are ordinary triggers/effects/costs about the
#: resolving permanent, with no positional structure a dedicated parse
#: would need — so ``~`` is exactly right, and every real Case writes its
#: ETB as "When this Case enters, …".
_SELF_REFERENCE_RE = re.compile(
    r"\bthis (?:creature|permanent|artifact|enchantment|land|planeswalker"
    r"|vehicle|equipment|aura|token|battle|siege|spacecraft|planet|case)\b"
)


def _fold_self_reference(text: str) -> str:
    """Fold type-worded self-references ("this creature", …) to ``~``."""
    return _SELF_REFERENCE_RE.sub(SELF, text)


#: RULE 207.2c "ability words" — italicized labels with no rules meaning of
#: their own, printed as "<Word> — <ability text>" purely for flavor/cross-
#: referencing (unlike a keyword ability, whose label *does* carry meaning).
#: Stripping the label here lets the ordinary trigger/static grammar that
#: follows it recognize the body the same as an unlabeled card would — no
#: bespoke whole-line handler needed per label, the way `segmenter._MAGECRAFT_RE`
#: needs one (its body has a two-verb "cast or copy" shape no ordinary
#: trigger expresses, so stripping alone wouldn't be enough there). A small,
#: deliberately conservative list — only ability words confirmed to precede
#: an otherwise-already-modeled body; safe to extend as more are checked
#: (RULE 207.2c guarantees the label itself never changes what follows).
#: Runs after lowercasing, per-line (``^`` anchored with MULTILINE) since the
#: label only ever opens a line, never appears mid-sentence.
_ABILITY_WORD_RE = re.compile(
    r"^(?:landfall|constellation|battalion|enrage|delirium|veil of time|avoidance"
    # "Threshold — As long as seven or more cards are in your graveyard, …"
    # (Odyssey block) — the label carries no rules meaning of its own
    # (RULE 207.2c); the "as long as …" body it precedes is an ordinary
    # RULE 613.6 conditional static once the label is gone.
    r"|threshold)\s*—\s*",
    re.MULTILINE,
)


def _strip_ability_words(text: str) -> str:
    return _ABILITY_WORD_RE.sub("", text)


#: The RULE 207.2c ability-word template ("Word — <effect>") isn't limited
#: to the fixed, evergreen vocabulary `_ABILITY_WORD_RE` enumerates — every
#: new Universes Beyond-flavored set (Final Fantasy, Marvel, Warhammer
#: 40,000, Doctor Who, Fallout, …) mints one-off, card-specific *flavor*
#: labels using the exact same "Name — <effect>" shape ("10,000 Needles —
#: Whenever this creature attacks, it gets +9999/+0 until end of turn.",
#: Jumbo Cactuar) — Scryfall's own keyword-extraction heuristic dutifully
#: lists these in the card's ``keywords`` array right alongside real
#: keywords, even though they carry no rules meaning of their own and will
#: never recur on a second card. A hand-maintained whitelist the way
#: `_ABILITY_WORD_RE` works can't scale to an open-ended, one-off
#: vocabulary — but Scryfall's own per-card ``keywords`` array is exactly
#: the signal needed to strip these safely and generically: if a string in
#: it does **not** match any real, registered RULE 701/702 keyword (checked
#: against `catalogue.keywords.KEYWORDS`, so a genuine flag/parametric
#: keyword's own line is never touched) and it appears verbatim as a
#: line-leading "``<label>`` <dash>" prefix, the label is discarded and the
#: (already fully self-contained) sentence after it is left for ordinary
#: parsing — the same reasoning `_ABILITY_WORD_RE`'s own docstring gives
#: for the evergreen list: RULE 207.2c guarantees a label never changes
#: what follows, so stripping it can only ever help, not hide a real
#: rules distinction. (A registered *keyword ability* that happens to
#: print its own full behaviour inline this way too, e.g. Heroic — "Heroic
#: — Whenever you cast a spell that targets this creature, …" — is safe to
#: strip the same way: the trailing sentence is already the complete
#: templated rule, and `keywords.py`'s own separate keyword-line binding
#: path is what actually recognizes Heroic as a keyword, unaffected since
#: it reads `card.keywords` directly rather than this stripped text.)
def _strip_unregistered_keyword_labels(text: str, keywords: Optional[list[str]]) -> str:
    if not keywords:
        return text
    from .catalogue.keywords import KEYWORDS  # avoid importing the whole catalogue at module load

    for kw in keywords:
        kw = (kw or "").strip()
        if not kw:
            continue
        slug = kw.lower().replace(" ", "_").replace("-", "_")
        if slug in KEYWORDS:
            continue
        # A plain hyphen is only an ability-word separator when separated
        # from its label by whitespace.  Scryfall also reports the spurious
        # prefix ``Jump`` alongside the real ``Jump-start`` keyword; allowing
        # ``Jump-`` here used to strip that prefix and leave a phantom
        # unclaimed ``start`` line behind.
        pattern = re.compile(
            r"^" + re.escape(kw.lower()) + r"(?:\s+[—–-]|[—–])\s*", re.MULTILINE
        )
        text = pattern.sub("", text)
    return text


#: MEC-79 / RULE 701.64b — the Marvel Infinity Stones print their ultimate
#: ability behind an "``∞ —``" marker line, with reminder text "(Once
#: harnessed, its ∞ ability is active.)". The marker *is* the rules device:
#: an ``∞`` ability functions only while the permanent is harnessed. Every
#: printed one is a phase-triggered ability, so rewrite the marker line into
#: an ordinary phase trigger carrying a RULE 603.4 intervening-if — the
#: segmenter's generic phase-trigger `active_if` path (backed by
#: `static_conditions`' ``source_harnessed``) then covers it with no bespoke
#: whole-line handler. Runs after lowercasing; the ``∞`` glyph and em/en/‐
#: dash both survive `_fold_self_reference` untouched.
_INFINITY_ABILITY_RE = re.compile(
    r"^∞\s*[—–-]\s*(?P<lead>at the beginning of [^,\n]+,)\s*(?P<rest>.+)$",
    re.MULTILINE,
)


def _rewrite_infinity_ability(text: str) -> str:
    return _INFINITY_ABILITY_RE.sub(
        lambda m: f"{m.group('lead')} if ~ is harnessed, {m.group('rest')}", text
    )


#: RULE 700.4 — "the term *dies* means 'is put into a graveyard from the
#: battlefield'". An exact definitional synonym, so folding the long
#: (pre-2011) phrasing to the modern one-word verb lets every existing
#: "dies" grammar — `segmenter._SELF_SUBJECT_RE`/`_GROUP_SUBJECT_RE`/
#: `_ATTACHED_SUBJECT_RE`, the tribal subject shapes, the quoted-grant
#: recursion — cover it with no new recognition at all (Rancor/Launch/
#: Aspect of Mongoose's "When this Aura is put into a graveyard from the
#: battlefield, return it to its owner's hand.", Ashiok's Reaper's
#: "Whenever an enchantment you control is put into a graveyard from the
#: battlefield, …").
#:
#: Deliberately **not** folded: "is put into **your** graveyard from the
#: battlefield" (Angelic Renewal). That names a specific player's
#: graveyard rather than "a graveyard", which "dies" doesn't express — a
#: genuinely narrower condition, so it stays unclaimed (fail-closed)
#: instead of being widened by a rewrite. Same for the plural "are put
#: into a graveyard" (a mass/batched shape with no "die" grammar behind
#: it). Runs after lowercasing.
_DIES_LONG_FORM_RE = re.compile(
    r"\bis put into (?:a|its owner's) graveyard from the battlefield\b"
)


def _fold_dies_long_form(text: str) -> str:
    """RULE 700.4: fold "is put into a graveyard from the battlefield" → "dies"."""
    return _DIES_LONG_FORM_RE.sub("dies", text)


#: A sentence-*leading* "Until end of turn, <body>." (Triumph of the Hordes:
#: "Until end of turn, creatures you control get +1/+1 and gain trample and
#: infect.") means exactly the same thing as the far more common trailing
#: "<body> until end of turn." every handler's grammar already expects —
#: folding the former into the latter lets one grammar cover both spellings
#: instead of duplicating every trailing-duration handler for a leading
#: variant. Deliberately restricted to a *single-sentence* line (``body`` may
#: contain no further period) rather than "everything up to the first
#: period": a line like Bail Out's "Until end of turn, target creature you
#: control gains "when ~ dies, ... its owner's control. It deals 1 damage to
#: each opponent."" has its first period *inside* a quoted granted ability,
#: so a naive "up to the first period" cut would relocate the duration to
#: the middle of that quote instead of the sentence's real end. Runs after
#: lowercasing, per-line since the duration only ever opens a line (never
#: appears mid-sentence).
_LEADING_UNTIL_EOT_RE = re.compile(
    r"^until end of turn, (?P<body>[^.\n]+)\.$", re.MULTILINE
)


def _fold_leading_until_end_of_turn(text: str) -> str:
    return _LEADING_UNTIL_EOT_RE.sub(
        lambda m: f"{m.group('body')} until end of turn.", text
    )


def strip_reminder_text(text: str) -> str:
    """Remove all parenthesised reminder text (RULE 207.2), innermost-first."""
    prev = None
    while prev != text:
        prev = text
        text = _REMINDER.sub("", text)
    return text


def _fold_self_name(text: str, name: Optional[str]) -> str:
    """Replace the card's own name (and its short/front-face form) with `SELF`.

    A card refers to itself by full name in oracle text; folding it to ``~``
    (the same token real cards use) lets one handler match any card. The
    front face before a comma or ``//`` is also folded, since cards self-refer
    by first name ("Nissa" for "Nissa, Who Shakes the World").

    An MTG Arena "Alchemy" rebalance is named with Scryfall's own ``"A-"``
    prefix (``"A-Thran Portal"``), but its oracle text keeps self-referring
    by the un-prefixed base name (PAR-4 — "As A-Thran Portal enters, choose
    a basic land type. **Thran Portal** is the chosen type…") — every form
    above gets an ``"A-"``-stripped sibling too, so the un-prefixed spelling
    folds to ``~`` right alongside the printed one.
    """
    if not name:
        return text
    forms = {name}
    forms.add(name.split("//")[0].strip())
    forms.add(name.split(",")[0].strip())
    for form in list(forms):
        if form.startswith("A-") and len(form) > 2 and form[2].isalpha():
            forms.add(form[2:])
    for form in sorted(forms, key=len, reverse=True):  # longest first
        if form:
            text = re.sub(r"\b" + re.escape(form) + r"\b", SELF, text)
    text = _fold_given_name_prefix(text, name)
    return text


#: A given-name-prefix occurrence *not* to fold: preceded by a tribal/scope
#: word ("another Cleric you control", "each Knight", "enchanted Angel") or
#: followed by a type tell (" creature token", " you control") — there it
#: reads as a creature-type filter that happens to share the card's given
#: name, not a self-reference. (RULE 201.4 — the card names itself, not its
#: type.) Kept deliberately small; the unconditional forms above already
#: cover every unambiguous self-reference.
_PREFIX_TYPE_BEFORE = re.compile(
    r"(?:another|other|each|target|enchanted|equipped|a|an|all|gains?|has|have|"
    r"with|grants?|lose|loses)\s+$",
    re.IGNORECASE,
)
_PREFIX_TYPE_AFTER = re.compile(
    r"^\s+(?:creature|you control|token|cards?\b|spells?\b|until end of turn|"
    # A *different* comma-less "<word> the/of <rest>" title continuing right
    # after the match (Tuktuk the Explorer creating "Tuktuk the **Returned**",
    # a differently-named token) — by the time this runs, the card's own
    # complete name was already folded to ``~`` by `_fold_self_name`'s main
    # pass, so any surviving "<prefix> the/of …" here is always someone
    # *else's* title, never a second mention of this card's own.
    r"the \S|of \S)",
    re.IGNORECASE,
)


def _fold_given_name_prefix(text: str, name: str) -> str:
    """Fold a comma-less legendary's **given name** — the single word before
    " of " in "Kaalia of the Vast", or before " the " in "Fíli the
    Pathfinder"/"Óin the Brave" (PAR-51's Hobbit-Dwarves cluster, self-
    referring by first name same as any other comma-less title) — to ``~``
    where it's a genuine self-reference. Context-gated
    (`_PREFIX_TYPE_BEFORE`/`_PREFIX_TYPE_AFTER`) so a name that doubles as a
    creature type ("Cleric of Life's Bond" → "another **Cleric** you
    control", "Knight of the New Coalition" → "a … **Knight** creature
    token") keeps its type reading, and matched **case-sensitively** against
    the not-yet-lowercased text (unlike every other fold in this module) so
    a common word that happens to share a name's spelling — "turn" inside
    "until end of turn" for "Turn the Tide", "start" inside "Jump-start" for
    "Start the TARDIS" — is left alone: a genuine self-reference is always
    printed capitalized, a mid-sentence common word never is. " of " is
    tried first (unchanged behaviour when a name has both, though no real
    card does)."""
    first = name.split(",")[0].strip()
    if " of " in first:
        prefix = first.split(" of ")[0].strip()
    elif " the " in first:
        prefix = first.split(" the ")[0].strip()
    else:
        return text
    if not prefix or " " in prefix:
        return text
    pat = re.compile(r"\b" + re.escape(prefix) + r"\b")

    def _sub(m: "re.Match[str]") -> str:
        if _PREFIX_TYPE_BEFORE.search(text[: m.start()]):
            return m.group(0)
        if _PREFIX_TYPE_AFTER.match(text[m.end():]):
            return m.group(0)
        return SELF

    # Runs inside `_fold_self_name`, before `normalize` lowercases — `pat`
    # relies on that printed case to stay case-sensitive (see the
    # docstring's "turn"/"start" collision note).
    return pat.sub(_sub, text)


def normalize(text: str, name: Optional[str] = None, keywords: Optional[list[str]] = None) -> str:
    """Canonicalise ``text`` for the segmenter and handler table (docs/09).

    Strips reminder text, folds the card's own ``name`` to ``~``, lowercases,
    folds spelled-out numbers to digits, folds RULE 700.4's long "is put into
    a graveyard from the battlefield" phrasing to "dies", and collapses runs
    of spaces/tabs — while **preserving newlines**, which separate a card's
    distinct abilities and drive segmentation.

    ``keywords`` — the card's own raw Scryfall ``keywords`` array, optional
    and unused unless passed — feeds `_strip_unregistered_keyword_labels`,
    stripping any one-off "Name — <effect>" flavor label alongside the
    fixed evergreen ability-word list.
    """
    text = strip_reminder_text(text or "")
    text = _fold_self_name(text, name)
    text = text.lower()
    text = _fold_self_reference(text)
    text = _strip_ability_words(text)
    text = _strip_unregistered_keyword_labels(text, keywords)
    text = _rewrite_infinity_ability(text)
    text = _fold_dies_long_form(text)
    text = _fold_leading_until_end_of_turn(text)
    text = _NUMBER_WORD_RE.sub(lambda m: _NUMBER_WORDS[m.group(1).lower()], text)
    # Collapse horizontal whitespace only; keep '\n' as the ability separator.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()
