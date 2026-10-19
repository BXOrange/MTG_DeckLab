"""Permanent product exclusions, independent of parser coverage and runtime.

A negative result means only that no permanent exclusion is known. It does
not assert that a card's rules are modeled. Printing metadata alone never
establishes that an Oracle card is digital-only.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional


@dataclass(frozen=True)
class SupportPolicyResult:
    unsupported: bool = False
    reason: Optional[str] = None


# These formats establish paper existence even when the card is banned or
# restricted there. Missing legality information is deliberately inconclusive.
SUPPORT_REASONS = frozenset({'cross_game', 'stickers', 'attractions', 'contraptions',
                             'alchemy', 'draft_matters', 'digital_only'})

_PAPER_REFERENCE_FORMATS = ('commander', 'legacy', 'vintage')
_TEXT_EXCLUSIONS = (
    ('cross_game', re.compile(r'\bnext game\b|\banother game\b|\ban un-game\b|\bsubgame\b|\brestart the game\b|\b(?:won|lost) a game this match\b|\bthis match is now worth\b', re.I)),
    ('stickers', re.compile(r'\bsticker(?:s|ed)?\b', re.I)),
    ('attractions', re.compile(r'\battractions?\b', re.I)),
    ('contraptions', re.compile(r'\bcontraptions?\b', re.I)),
    # Digital-only durations/face transitions and creation instructions. Do
    # not match incidental words such as "intensity" or a bare card name.
    ('alchemy', re.compile(r'\bperpetually\b|\bspecialize(?:s|d)?\b|\bconjure (?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|[0-9x]+)\b|\bfrom (?:its|their|your|a|the) spellbook\b|\bseek (?:a|an|two|three|[0-9x]+)\b', re.I)),
    # Rule text about the draft, not opening a booster pack during a game.
    ('draft_matters', re.compile(r'\bdraft(?:ed|ing)?\b|\b(?:hidden|double) agenda\b|\bconspiracy\b', re.I)),
)


def card_support_policy(card: Any) -> SupportPolicyResult:
    """Classify both printed faces without requiring a parser or registry.

    Vanguard's supported base modifiers and parked team variants remain
    available; neither is a whole-card permanent exclusion.
    """
    inherited = getattr(card, '_unsupported_reason', None)
    if inherited in SUPPORT_REASONS:
        return SupportPolicyResult(True, inherited)
    text = '\n'.join(str(getattr(card, field, '') or '') for field in (
        'oracle_text', 'back_oracle_text'))
    # Preserve the existing product exclusion for sticker references, including
    # digital sticker substitutes whose own name carries that reference.
    if re.search(r'\bsticker(?:s|ed)?\b', text, re.I):
        return SupportPolicyResult(True, 'stickers')
    for field in ('name', 'back_name'):
        for name in str(getattr(card, field, '') or '').split('//'):
            if name.strip():
                text = re.sub(re.escape(name.strip()), '~', text, flags=re.I)
    text += '\n' + '\n'.join(str(getattr(card, field, '') or '') for field in (
        'type_line', 'back_type_line'))
    for reason, pattern in _TEXT_EXCLUSIONS:
        if pattern.search(text):
            return SupportPolicyResult(True, reason)
    games = set(getattr(card, 'games', None) or [])
    legalities = getattr(card, 'legalities', None) or {}
    if (getattr(card, 'digital', None) is True and games == {'arena'}
            and all(legalities.get(fmt) == 'not_legal' for fmt in _PAPER_REFERENCE_FORMATS)):
        return SupportPolicyResult(True, 'digital_only')
    return SupportPolicyResult()


def unsupported_reason(card: Any) -> Optional[str]:
    """Stable machine-readable reason, or None when no exclusion applies."""
    return card_support_policy(card).reason
