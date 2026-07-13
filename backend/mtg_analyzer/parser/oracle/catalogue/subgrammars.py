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
from typing import Optional

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
    (r"target creature", "creature"),
    (r"target permanent", "permanent"),
    (r"target artifact or enchantment", "permanent"),
    (r"target artifact", "permanent"),
    (r"target enchantment", "permanent"),
    (r"target land", "permanent"),
    (r"target nonland permanent", "permanent"),
    (r"target spell", "spell"),
    (r"target player or planeswalker", "player"),
    (r"target opponent", "player"),
    (r"target player", "player"),
    (r"each opponent", "player"),
    (r"each player", "player"),
]

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
