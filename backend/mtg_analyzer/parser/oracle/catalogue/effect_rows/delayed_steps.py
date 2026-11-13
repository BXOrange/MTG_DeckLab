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
    "the next combat": ("begin_combat", "any"),
    "the next combat this turn": ("begin_combat", "any"),
    "your next end step": ("end", "controller"),
    "the next upkeep": ("upkeep", "any"),
    "your next upkeep": ("upkeep", "controller"),
}

_DELAYED_STEP_RE = compile_clause(
    rf"at the beginning of (?P<when>{'|'.join(map(re.escape, DELAYED_TIMINGS))}), (?P<body>.+)"
)
#: PAR-276: the suffix word order of the same grammar for the player's own bounce pick (Erica Ortegas: "return a land
#: you control to its owner's hand at the beginning of the next end step"). Deliberately not general: other suffix
#: forms ("draw a card at the beginning of ...", "flip a coin at ...", a token named "... at the beginning ...") stay
#: unclaimed on purpose (see test_par30_delayed_sac_exile_tail / test_par151_coin_flips / test_par148).
_DELAYED_STEP_SUFFIX_RE = compile_clause(
    rf"(?P<body>return an? [a-z]+ you control to its owner's hand) at the beginning of (?P<when>{'|'.join(map(re.escape, DELAYED_TIMINGS))})"
)
#: A body naming something an earlier sentence chose (or the group a trigger matched) is not this row's.
_REFERENT_WORDS_RE = re.compile(
    r"\b(?:it|its|they|them|their|those|these|he|she|that [a-z]+|the (?:exiled|chosen|revealed|returned|milled) [a-z]+)\b",
    re.IGNORECASE,
)


_OWNERS_RE = re.compile(r"\bits owner'?s\b", re.IGNORECASE)


def _delayed_step(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    body = m.group("body").strip()
    capture = None
    # "its owner's hand" names the owner of the chosen permanent (RULE 108.3), not an earlier-chosen referent.
    if _REFERENT_WORDS_RE.search(_OWNERS_RE.sub("the owner's", body)):
        # RULE 603.7c: the previously chosen permanent is fixed now,
        # rather than announced as a new target at the future combat.
        bound = re.match(r"gain control of (?:it|that creature|that permanent) until end of turn", body)
        if bound is None or not reading.previous_subject:
            return None
        rewritten = "gain control of target creature until end of turn" + body[bound.end():]
        effects = parse_effect_body(rewritten)
        if not effects or len(effects) != 1 or effects[0].type != "gain_control_until_eot":
            return None
        effects[0].params["target_kind"] = None
        capture = "previous_targets"
    else:
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if not effects or any(effect.params.get("target_kind") for effect in effects):
            return None
    step, scope = DELAYED_TIMINGS[m.group("when").lower()]
    params = {"step": step, "scope": scope, "effects": [effect.to_dict() for effect in effects]}
    if capture:
        params["capture"] = capture
    if m.group("when").endswith(" this turn"):
        params["this_turn_only"] = True
    return [EffectSpec("create_delayed_trigger", params)]



def _delayed_step_suffix(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    # Reuse the prefix reader on the reordered clause so both word orders share one set of safety checks.
    head = _DELAYED_STEP_RE.fullmatch(f"at the beginning of {m.group('when')}, {m.group('body')}")
    return None if head is None else _delayed_step(head, reading)


#: PAR-276: a captured permanent put on the bottom of its owner's library at a later step, with the reflexive draw
#: (RULE 603.12) -- "At the beginning of the next end step, put it on the bottom of your library. When you do, draw a
#: card." (U.S.S. Farragut). "It" is the card an earlier clause placed (``previous_or_self``), baked at creation.
_DELAYED_BOTTOM_RE = compile_clause(
    rf"at the beginning of (?P<when>{'|'.join(map(re.escape, DELAYED_TIMINGS))}), "
    r"put (?:it|that creature|that card) on the bottom of (?:your|its owner'?s) library"
    r"(?:\. when you do, (?P<draw>draw a card))?"
)


def _delayed_bottom(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    if not reading.previous_subject:
        return None  # "it" must name a card an earlier clause picked (RULE 608.2c)
    step, scope = DELAYED_TIMINGS[m.group("when").lower()]
    inner = {"type": "put_specific_on_library_bottom", "params": {"then_draw": 1 if m.group("draw") else 0}}
    return [EffectSpec("create_delayed_trigger", {
        "step": step, "scope": scope, "capture": "previous_or_self", "effects": [inner],
    })]


ROWS: list[EffectHandler] = [
    EffectHandler("delayed_bottom_put", _DELAYED_BOTTOM_RE, _delayed_bottom, reading_aware=True),
    EffectHandler("delayed_step_body", _DELAYED_STEP_RE, _delayed_step, reading_aware=True),
    EffectHandler("delayed_step_suffix_body", _DELAYED_STEP_SUFFIX_RE, _delayed_step_suffix, reading_aware=True),
]
