"""Read-only head/body and modifier probes shared by parser research tools.

These are diagnostic transformations, never grammar rules or proof that the
original clause executes. This module has no engine imports or storage writes.
"""
from __future__ import annotations

import re
from .oracle.segmenter import segment_line

_TRIGGER_SPLIT = re.compile(r"^(?P<head>(?:when|whenever|at)\b[^,]*),\s*(?P<body>.+)$", re.S)
_ACTIVATED_SPLIT = re.compile(
    r"^(?P<head>[^:\"]{0,80}(?:\{[^}]+\}|sacrifice|discard|pay|exile|tap|untap|remove|return)[^:\"]{0,80}):\s*(?P<body>.+)$",
    re.S,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[a-z\)\"'])\.\s+(?=[a-z])")

#: Trigger-head event families, first match wins (a head is filed under one).
_HEAD_FAMILIES = [
    ("cast", r"\byou cast\b|\bcasts? (a|an|your|their|another)\b|\bplayer casts\b|\bis cast\b"),
    ("sacrifice", r"\bsacrifices?\b"),
    ("discard", r"\bdiscards?\b"),
    ("cycle", r"\bcycles?\b"),
    ("attack/block", r"\battacks?\b|\battack with\b|\bbecomes blocked\b|\bisn't blocked\b|\bblocks?\b"),
    ("enter/leave/die", r"\benters?\b|\bleaves?\b|\bdies\b|\bdie\b|\bexiled\b|\bput into\b"),
    ("damage/life", r"\bdeals?\b.*\bdamage\b|\bdealt damage\b|\blos(?:e|es) life\b|\bgains? life\b"),
    ("draw/mill/counter", r"\bdraws?\b|\bmilled?\b|\bcounters?\b"),
    ("phase/step", r"^at\b"),
]

#: Modifier phrases removed one at a time from a failing effect sentence: if the
#: shortened sentence parses, that modifier axis is what the parser lacks.
_MODIFIER_AXES = {
    "leading 'if <cond>,'": r"^if [^,]+, ",
    "for each <count>": r",? for each [^.,]+",
    "where X is / equal to <amount>": r",? where x is [^.]+|,? equal to [^.,]+",
    "trailing 'if <cond>'": r",? if [^.]+$",
    "trailing 'unless <cond>'": r",? unless [^.]+$",
    "'you may' optional": r"^you may ",
    "scope word (each opponent / target player)": r"^(each opponent|each player|target opponent|target player) ",
    "'you don't control / an opponent controls'": r" (you don't control|an opponent controls|your opponents control)",
    "'another / other'": r"\b(another|other) ",
    "'up to N'": r"up to \d+ ",
    "'then <clause>'": r",? then [^.]+$",
    "duration (until / this turn)": r",? (until [^.,]+|this turn)",
    "'tapped'": r" tapped\b",
    "'instead'": r",? instead",
}


def _claims(line: str, provenance) -> bool:
    try:
        return segment_line(line, allow_spell_effect=True, provenance=provenance).claimed
    except Exception:  # a probe must never die on one odd clause
        return False



class CompositionProbe:
    """Memoize the canonical known-good-partner probes across a card pool."""

    def __init__(self, provenance):
        self.provenance = provenance
        self._cache: dict[str, bool] = {}

    def claims(self, text: str) -> bool:
        if text not in self._cache:
            self._cache[text] = _claims(text, self.provenance)
        return self._cache[text]

    def split(self, text: str):
        kind = 'trigger'
        match = _TRIGGER_SPLIT.match(text)
        if match is None:
            kind, match = 'activated', _ACTIVATED_SPLIT.match(text)
        if match is None:
            return None
        head, body = match.group('head').strip(), match.group('body').strip()
        head_probe = f'{head}, draw a card.' if kind == 'trigger' else f'{head}: draw a card.'
        body_probe = f'when ~ enters, {body}' if kind == 'trigger' else f'{{t}}: {body}'
        return kind, head, body, self.claims(head_probe), self.claims(body_probe)

    def modifier_repairs(self, body: str):
        """Return single-axis deletions that repair failing trigger-body sentences."""
        repairs = []
        for sentence in (s.strip() for s in _SENTENCE_SPLIT.split(body) if s.strip()):
            if self.claims(f'when ~ enters, {sentence.strip(" .")}'):
                continue
            for axis, pattern in _MODIFIER_AXES.items():
                if not re.search(pattern, sentence):
                    continue
                shorter = re.sub(pattern, '', sentence, count=1).strip(' ,.')
                if shorter and shorter != sentence and self.claims(f'when ~ enters, {shorter}'):
                    repairs.append((axis, sentence, shorter))
        return repairs
