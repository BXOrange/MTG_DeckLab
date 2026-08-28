"""Station (RULE 702.184a / RULE 721 "Station Cards") block grammar — pure
text splitting, mirroring `levels.py`'s Leveler/Class shape for a third
"striated text box" card structure.

RULE 721.1-721.2a: a Station permanent's text box is split into a fixed
Station reminder line (the real activated ability — RULE 702.184a, bound
directly off Scryfall's own ``keywords: ["Station"]`` entry by
`effect_binder._station_activated_ability`, so this module never needs to
emit that ability itself) plus one or more ``"N+ | <ability>"`` bracket
lines: "as long as this permanent has N or more charge counters on it, it
has `<ability>`" — **cumulative** (>= comparison), not the mutually-
exclusive tier ranges Leveler uses.

Unlike Leveler/Class's own strict "preamble, then only blocks" shape, RULE
721.4 explicitly allows an ordinary (bracket-less) line **both before and
after** the brackets — confirmed against the real cached data (Entropic
Battlecruiser's own trailing "Whenever this Spacecraft attacks, ..." trigger
prints *after* its "8+ |" bracket) — so `split_station_blocks` classifies
every line by shape in its own printed order, rather than assuming
everything bracket-less is a leading preamble.

RULE 721.2b's per-bracket "and is a creature with base power/toughness
[P/T]" clause turns out not to be textually present in Scryfall's own
oracle-text linearization at all (confirmed against all 30 cached Station
cards): the P/T box the physical card prints inline in a bracket is dropped
from ``oracle_text`` entirely, and the *only* surviving trace of RULE
721.2b is the reminder line's own trailing "It's an artifact creature at
N+." sentence — which itself is inside the reminder line's parentheses, so
`normalize()`'s generic ``\\s*\\([^()]*\\)`` reminder-stripping erases it
before any line-based splitting ever sees it. `station_creature_threshold`
therefore reads the **raw** (pre-`normalize`) oracle text directly, the
same way `levels.leveler_base_text` reads raw text for its own cross-check
— this is a real, confirmed departure from a naive reading of RULE 721.2b's
wording, not a design choice made for convenience.
"""

from __future__ import annotations

import re
from typing import Optional

#: A Station tier-bracket line, its own printed line: "8+ | Flying,
#: deathtouch". Verified against `normalize()`'s output on real cached
#: cards — the ``"N+ | "`` prefix survives normalization unchanged (only
#: lowercased), the same way `levels.LEVEL_TIER_RE` verified its own shape.
STATION_TIER_RE = re.compile(r"^(?P<n>\d+)\+\s*\|\s*(?P<body>.+)$")

#: The fixed Station reminder clause, read from **raw** (pre-`normalize`)
#: oracle text — see the module docstring for why this can't be read off
#: the normalized/segmented text the way every other grammar in this
#: package works. The permanent-type noun ("Spacecraft"/"Planet", so far)
#: is matched generically (``\\w+``) rather than enumerated, since RULE 721
#: doesn't restrict which card type can print Station. The trailing "It's
#: a[n] [artifact] creature at N+." sentence is optional — a Station
#: *land* (Planet) never becomes a creature at all (e.g. Adagia, Windswept
#: Bastion), and one cached Spacecraft (The Eternity Elevator) never does
#: either.
STATION_REMINDER_RE = re.compile(
    r"station\s*\(\s*tap another creature you control:\s*put charge counters equal to its "
    r"power on this \w+\.\s*station only as a sorcery\."
    r"(?:\s*it.s an?(?:\s+\w+)? creature at (?P<n>\d+)\+\.)?\s*\)",
    re.IGNORECASE,
)


def split_station_blocks(text: str) -> tuple[list[str], list[tuple[int, str]]]:
    """Split normalised Station text into its ordinary (bracket-less) lines
    plus its ``N+`` tier blocks (RULE 721.1's own "striated" text-box shape).

    Returns ``(ordinary_lines, blocks)`` — ``ordinary_lines`` in their real
    printed relative order (may include lines from both before *and* after
    the brackets, per RULE 721.4 — see the module docstring), each handed to
    the same ordinary per-line dispatch any other card's preamble/trailing
    text goes through; ``blocks`` as ``(n, body)`` pairs, one per printed
    bracket *line* (a single threshold can carry 2+ printed lines if a real
    card ever prints them, each becoming its own block entry — RULE 721.2a's
    cumulative semantics make that safe: every satisfied bracket's abilities
    stay active together, so nothing depends on grouping same-``n`` lines).

    The bare "station" keyword word normalize() leaves behind (see the
    module docstring) is deliberately *not* special-cased here — it's just
    another ordinary line, already claimed for free by the segmenter's
    generic ``is_keyword_line`` check (a lone recognized keyword word), the
    same way any other bare-keyword line is.
    """
    ordinary: list[str] = []
    blocks: list[tuple[int, str]] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        match = STATION_TIER_RE.match(line.strip())
        if match is not None:
            blocks.append((int(match.group("n")), match.group("body")))
        else:
            ordinary.append(line)
    return ordinary, blocks


#: Raw-text sibling of `STATION_TIER_RE`, for stripping bracket lines out of
#: **un-normalized** oracle text (`station_base_text` below) — normalize()
#: hasn't lowercased/substituted `~` yet at this point, so this can't just
#: reuse `STATION_TIER_RE` against raw lines the way `split_station_blocks`
#: does against already-normalized ones.
_STATION_TIER_RE_RAW = re.compile(r"^\d+\+\s*\|")


def station_base_text(oracle_text: str) -> str:
    """``oracle_text`` with every ``N+ |`` bracket *line* removed — the
    Station sibling of `levels.leveler_base_text`, built the same way for
    the same reason: `combat.keywords_of`'s oracle-text regex fallback
    (`_ORACLE_PATTERNS`) has no concept of "only active at N+ counters", so
    scanning the full raw text lets a bracket-only keyword (e.g. "8+ |
    Flying, deathtouch") leak in as unconditionally active — confirmed live
    (Entropic Battlecruiser: `deathtouch` shows up in `keywords_of` at 0
    charge counters, comma-anchored right after the "8+ | " prefix; `flying`
    coincidentally doesn't, only because nothing precedes it that
    `_ORACLE_PATTERNS`' own clause-anchoring recognizes — not something to
    rely on for other cards' bracket wording).

    Unlike `leveler_base_text`'s truncate-at-first-tier shape (Leveler's own
    strict "preamble, then only blocks" structure), this **filters out**
    just the bracket lines rather than truncating — RULE 721.4 explicitly
    allows an ordinary bracket-less line both before *and* after the
    brackets (see this module's own docstring), and a trailing one's
    keywords, if any, are genuinely unconditional and must still be found.
    """
    lines = [
        line for line in (oracle_text or "").split("\n")
        if not _STATION_TIER_RE_RAW.match(line.strip())
    ]
    return "\n".join(lines)


def station_creature_threshold(oracle_text: str) -> Optional[int]:
    """The charge-counter threshold at which this Station permanent becomes
    a creature (RULE 721.2b), or ``None`` if it never does (every cached
    Station *land* — subtype Planet — plus at least one Spacecraft, The
    Eternity Elevator, a pure mana rock).

    Reads **raw** ``oracle_text`` directly — see `STATION_REMINDER_RE` and
    the module docstring for why the number can't survive to the normalized/
    segmented text `split_station_blocks` otherwise works on.
    """
    match = STATION_REMINDER_RE.search(oracle_text or "")
    if match is None or match.group("n") is None:
        return None
    return int(match.group("n"))
