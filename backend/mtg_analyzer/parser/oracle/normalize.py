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
_SELF_REFERENCE_RE = re.compile(
    r"\bthis (?:creature|permanent|artifact|enchantment|land|planeswalker"
    r"|vehicle|equipment|aura|token|battle|siege)\b"
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
    r"^(?:landfall|constellation|battalion|enrage|delirium|veil of time|avoidance)\s*—\s*",
    re.MULTILINE,
)


def _strip_ability_words(text: str) -> str:
    return _ABILITY_WORD_RE.sub("", text)


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
    return text


def normalize(text: str, name: Optional[str] = None) -> str:
    """Canonicalise ``text`` for the segmenter and handler table (docs/09).

    Strips reminder text, folds the card's own ``name`` to ``~``, lowercases,
    folds spelled-out numbers to digits, folds RULE 700.4's long "is put into
    a graveyard from the battlefield" phrasing to "dies", and collapses runs
    of spaces/tabs — while **preserving newlines**, which separate a card's
    distinct abilities and drive segmentation.
    """
    text = strip_reminder_text(text or "")
    text = _fold_self_name(text, name)
    text = text.lower()
    text = _fold_self_reference(text)
    text = _strip_ability_words(text)
    text = _fold_dies_long_form(text)
    text = _fold_leading_until_end_of_turn(text)
    text = _NUMBER_WORD_RE.sub(lambda m: _NUMBER_WORDS[m.group(1).lower()], text)
    # Collapse horizontal whitespace only; keep '\n' as the ability separator.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()
