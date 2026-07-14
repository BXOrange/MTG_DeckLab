"""Shared sub-grammars — the rule that stops the handler set exploding (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("Factor shared sub-grammars").
"deal 3 damage **to any target**" / "**to target creature**" / "**to target
player**" are *one* damage handler with a reusable TARGET matcher, not three
regexes. This module owns those reusable fragments so every handler shares
them: the TARGET phrase → an engine ``target_kind``, and NUMBER.

Pure regex + data — **no `game/` imports** (front-end security boundary).
The ``target_kind`` strings here mirror `game/targeting.ALLOWED_TARGET_KINDS`
(kept in sync by `tests/test_oracle_handlers.py`), so a handler can drop the
resolved kind straight into an effect's params.
"""

from __future__ import annotations

import re
from typing import Any, Optional

#: Ordered (regex-fragment, target_kind) rows. **Longest / most specific
#: first** — "target creature or player" must win over "target creature".
#: Each fragment is a self-contained alternative that the TARGET matcher ORs
#: together; the resolved ``kind`` is one of `targeting.ALLOWED_TARGET_KINDS`.
_TARGET_ROWS: list[tuple[str, str]] = [
    (r"any target", "any"),
    (r"target creature or player", "any"),
    (r"target creature, player,? or planeswalker", "any"),
    (r"target creature or planeswalker", "creature"),
    (r"target attacking or blocking creature", "creature"),
    (r"target (?:attacking|blocking|tapped|untapped) creature", "creature"),
    # "target creature you control" (RULE 115/603.3c controller-restricted
    # pick, e.g. an Equipment's ETB "attach it to target creature you
    # control") — must sit above the bare "target creature" row below.
    (r"target creature you control", "creature_you_control"),
    (r"target creature", "creature"),
    (r"target permanent", "permanent"),
    (r"target artifact or enchantment", "permanent"),
    (r"target artifact", "permanent"),
    (r"target enchantment", "permanent"),
    (r"target land", "permanent"),
    # "a land you control" (a bounce-land's "return a land you control to
    # its owner's hand") isn't RULE 115 targeting at all — no "target" word —
    # but is modeled the same controller-restricted way: a choice among the
    # controller's own permanents, narrowed to lands at resolution.
    (r"a land you control", "land_you_control"),
    (r"target nonland permanent", "permanent"),
    (r"target spell", "spell"),
    (r"target player or planeswalker", "player"),
    (r"target opponent", "player"),
    (r"target player", "player"),
]
#: Deliberately no "each opponent"/"each player" row: RULE 115 targeting
#: always uses the word "target" — "each opponent"/"each player" is a mass
#: *selector* effect, not a target choice, and modeling it as a single
#: chosen "player" target would be wrong (it should hit everyone, not one
#: chosen player). `catalogue.handlers`'s selector-based damage handler
#: (``each_creature``/``each_player``/``each_opponent``) claims those
#: phrases on its own, bypassing TARGET entirely.

#: The TARGET fragment, as an alternation with a named ``target`` group. Used
#: *inside* a handler regex ("deal (\\d+) damage to <TARGET>"), so it is not
#: anchored itself.
TARGET = r"(?P<target>" + "|".join(f"(?:{frag})" for frag, _ in _TARGET_ROWS) + r")"

#: Each row's fragment compiled with a full-match anchor, in order, so
#: `resolve_target_kind` can classify a matched target phrase deterministically.
_TARGET_LOOKUP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(frag + r"\Z", re.IGNORECASE), kind) for frag, kind in _TARGET_ROWS
]

#: A small integer literal — after normalisation, spelled-out numbers are
#: already digits (`normalize`), so the grammar only needs to see digits.
NUMBER = r"(?P<n>\d+)"

#: "a"/"an" or a digit, for counts printed either way ("draw a card" /
#: "draw 2 cards"). `count_of` maps a captured group to an int.
COUNT = r"(?P<n>a|an|\d+)"


def resolve_target_kind(phrase: str) -> Optional[str]:
    """Classify a matched TARGET ``phrase`` into an engine ``target_kind``.

    Returns ``None`` if it matches no row (fail-closed: an unrecognised target
    leaves the clause unclaimed rather than guessing ``"any"``).
    """
    text = phrase.strip()
    for pattern, kind in _TARGET_LOOKUP:
        if pattern.match(text):
            return kind
    return None


def count_of(token: str) -> int:
    """A captured `COUNT`/`NUMBER` token → its integer value ("a"/"an" → 1)."""
    token = token.strip().lower()
    if token in ("a", "an"):
        return 1
    return int(token)


# --- "counter target <filter> spell" (RULE 601.2c/115) ----------------------
# The counter family's own target grammar: unlike the generic `TARGET` rows
# above (one fixed `target_kind` per row), a countered *spell* can carry a
# structured filter — "noncreature", a card-type list ("instant or sorcery"),
# and/or "with mana value N" — so this is a dedicated companion grammar
# rather than another `_TARGET_ROWS` entry (docs/09 "Factor shared
# sub-grammars"; only `catalogue.handlers`'s counter handler needs it today).

#: Card-type words a spell-target filter may name (nonland types only — a
#: land is never a spell). Kept in sync with `game/targeting._spell_matches_
#: filter`'s ``type_checks`` keys by `tests/test_counter_family.py`.
_SPELL_TYPE_WORD = r"(?:artifact|creature|enchantment|instant|planeswalker|sorcery)"
#: An "or"/comma-separated list of 1+ type words: "creature", "instant or
#: sorcery", "artifact, creature, or planeswalker".
_SPELL_TYPE_LIST = (
    rf"{_SPELL_TYPE_WORD}(?:,\s*{_SPELL_TYPE_WORD})*(?:,?\s+or\s+{_SPELL_TYPE_WORD})?"
)

#: The bare "target [noncreature|<type list>] spell [with mana value N]"
#: phrase, unanchored (embedded inside a handler's own regex via `SPELL_
#: TARGET`) — never both ``noncreature`` and ``types`` (no real card prints
#: both), so a handler only needs to check whichever group is set.
_SPELL_TARGET_BODY = (
    r"target "
    r"(?:(?P<noncreature>noncreature)\s+)?"
    rf"(?:(?P<types>{_SPELL_TYPE_LIST})\s+)?"
    r"spell"
    r"(?:\s+with mana value (?P<mv>\d+))?"
)
#: The same phrase captured under a ``target`` group, for embedding inline in
#: a handler regex the way `TARGET` is (e.g. ``counter {SPELL_TARGET}``).
SPELL_TARGET = rf"(?P<target>{_SPELL_TARGET_BODY})"
_SPELL_TARGET_LOOKUP = re.compile(_SPELL_TARGET_BODY + r"\Z", re.IGNORECASE)


def resolve_spell_filter(phrase: str) -> Optional[dict[str, Any]]:
    """Classify a matched `SPELL_TARGET` ``phrase`` into a `TargetSpec.
    spell_filter`-shaped dict, or ``None`` if it matches no recognised shape
    (fail-closed, mirroring `resolve_target_kind`).

    A bare "target spell" resolves to ``{}`` (no filter, still a legal —
    just unfiltered — countable target).
    """
    m = _SPELL_TARGET_LOOKUP.match(phrase.strip())
    if m is None:
        return None
    filt: dict[str, Any] = {}
    if m.group("noncreature"):
        filt["noncreature"] = True
    if m.group("types"):
        # ", or " (the Oxford-comma joiner before the last item) must split as
        # one separator — trying the plain "," alternative first would leave
        # a stray "or " glued onto the final type word.
        types = [t for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", m.group("types")) if t]
        filt["card_types"] = types
    if m.group("mv"):
        filt["mana_value"] = int(m.group("mv"))
    return filt


#: "This spell can't be countered." / "~ can't be countered." (RULE 118-area).
#: The literal phrasing is identical whether the clause is an instant/
#: sorcery's own resolve-time body (`catalogue.handlers`) or a permanent's
#: standing line (`catalogue.static_handlers`) — both claim it with this one
#: pattern so the two front-end paths agree on the same `EffectSpec`.
CANT_BE_COUNTERED_RE: re.Pattern[str] = re.compile(
    r"(?:this spell|~) can't be countered", re.IGNORECASE
)
