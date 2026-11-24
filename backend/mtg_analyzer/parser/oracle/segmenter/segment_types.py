"""Segmenter: segment types (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from ..spec import AbilitySpec

@dataclass
class Segment:
    """One ability's parse: either a spec (claimed) or the unclaimed raw text."""

    raw: str
    spec: Optional[AbilitySpec] = None
    claimed: bool = False
    #: True when the line is a pure keyword line (claimed elsewhere, by the
    #: keyword catalogue) — it contributes no effect spec here but *is* covered.
    keyword_line: bool = False
    #: RULE 605: native mana abilities are auto-bound from oracle text, without IR.
    mana_ability: bool = False
    #: Further abilities the same printed line produces. Empty for almost
    #: every line: one printed line is one ability. The exception is RULE
    #: 700.2's *compact* inline modal on an activated ability ("Enchanted
    #: creature gets +1/-1 **or** -1/+1 until end of turn." — Pemmin's
    #: Aura), which is faithfully modeled as two separately-activatable
    #: abilities sharing a cost: choosing which one to activate **is** the
    #: printed choice, so no mode-selection machinery is needed for it.
    extra_specs: list[AbilitySpec] = field(default_factory=list)

    @property
    def native_oracle_text(self) -> str:
        """RULE 111.3: reconstruct native mana text for the raw-text binder.

        The mana model reads printed ``Add {C}.`` with its original casing
        and period; token creation starts from normalized, lower-case text.
        """
        if not self.mana_ability:
            return self.raw
        text = re.sub(r"\badd\b", "Add", self.raw, flags=re.I)
        text = re.sub(r"\{[wubrgc]\}", lambda match: match.group().upper(), text, flags=re.I)
        return text.rstrip(" .") + "."
