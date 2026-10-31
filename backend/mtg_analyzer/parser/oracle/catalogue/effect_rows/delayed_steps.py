"""A delayed trigger named by the step it waits for: "At the beginning of `<when>`, `<effect>`." (PAR-207).

RULE 603.7: an effect can create a delayed triggered ability that fires at a later step. The *timing* is the
head -- which step (end step, upkeep) and whose (the very next one, or the ability controller's next one) -- and the
*body* is any effect clause the table already reads, so the grammar is timing × body rather than a row per card
(Casey Jones, Teferi, False Memories, Coalstoke Gearhulk ...). Only a body with no referent of its own is read here:
a pronoun ("it", "that creature", "those tokens") names an object the earlier sentence picked, which
`create_delayed_trigger`'s ``capture`` rows (`pump_stats`, `flicker_sequences`, `damage_copy`) bind and this one
cannot. Pure -- no `game/` imports.
"""

from __future__ import annotations

import re
from typing import Optional

from ..clause_hooks import parse_effect_body
from ..clause_reading import ClauseReading
from ...spec import EffectSpec
from .shared import EffectHandler, compile_clause

#: Printed timing -> ``(create_delayed_trigger step, scope)``: RULE 500's step names as `game/phases.py` fires them;
#: ``"any"`` is the very next such step, ``"controller"`` the next one in the ability controller's turn.
DELAYED_TIMINGS: dict[str, tuple[str, str]] = {
    "the next end step": ("end", "any"),
    "your next end step": ("end", "controller"),
    "the next upkeep": ("upkeep", "any"),
    "your next upkeep": ("upkeep", "controller"),
}

_DELAYED_STEP_RE = compile_clause(
    rf"at the beginning of (?P<when>{'|'.join(map(re.escape, DELAYED_TIMINGS))}), (?P<body>.+)"
)
#: A body naming something an earlier sentence chose (or the group a trigger matched) is not this row's.
_REFERENT_WORDS_RE = re.compile(
    r"\b(?:it|its|they|them|their|those|these|he|she|that [a-z]+|the (?:exiled|chosen|revealed|returned|milled) [a-z]+)\b",
    re.IGNORECASE,
)


def _delayed_step(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    body = m.group("body").strip()
    if _REFERENT_WORDS_RE.search(body):
        return None
    effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
    # A target would have to be announced when the delayed ability goes on the stack, which the node cannot yet do.
    if not effects or any(effect.params.get("target_kind") for effect in effects):
        return None
    step, scope = DELAYED_TIMINGS[m.group("when").lower()]
    return [EffectSpec("create_delayed_trigger", {
        "step": step, "scope": scope, "effects": [effect.to_dict() for effect in effects],
    })]


ROWS: list[EffectHandler] = [
    EffectHandler("delayed_step_body", _DELAYED_STEP_RE, _delayed_step),
]
