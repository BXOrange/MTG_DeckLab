"""Segmenter: keyword lines (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Any, Optional
from ..catalogue.clause_primitives import (
    ACTIVATE_ONLY_ONCE_MARKER,
    ACTIVATION_CONDITION_MARKER,
    FROM_HAND_MARKER,
    ONCE_PER_TURN_MARKER,
    POWERUP_COST_REDUCTION_MARKER,
)
from ..catalogue.keywords import KEYWORDS, PROTOTYPE_RE, RECOVER_LIFE_RE, SQUAD_DASH_RE
from ..catalogue.overload import OVERLOAD_LINE_RE
from ..catalogue.craft import parse_craft
from ..spec import AbilitySpec, EffectSpec, ParserProvenance
from .segment_types import Segment
from .keyword_and_trigger_conditions import (
    COMPOUND_PARAM_START_RE,
    is_compound_keyword_line,
    is_keyword_token,
    keyword_line_has_unmodeled_rider,
    names_inert_keyword,
)
from .late import segment_line



def is_keyword_line(line: str) -> bool:
    """Whether ``line`` is only keyword abilities, for the gate.

    Two or more keywords can share one line, comma-separated ("Flying,
    vigilance"). A comma-separated continuation only rejoins the token before
    it when that token starts one of the closed `COMPOUND_PARAM_START_RE`
    keywords *and* doesn't already stand as a keyword token on its own — so
    an unrelated trailing clause ("Flying, then draw a card") still fails
    instead of being swallowed by a keyword's own greedy `.*$` match.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if keyword_line_has_unmodeled_rider(stripped):
        return False
    # BUG-75: a keyword the engine does nothing with is not accounted for by the keyword catalogue.
    if names_inert_keyword(stripped):
        return False
    if stripped.lower().startswith("assist"):
        return stripped.rstrip(".").lower() == "assist"
    if stripped.lower().startswith("craft"):
        return parse_craft(stripped) is not None
    if stripped.lower().startswith("overload"):
        return OVERLOAD_LINE_RE.fullmatch(stripped) is not None
    if stripped.lower().startswith("prototype"):
        return PROTOTYPE_RE.fullmatch(stripped) is not None
    if re.match(r"squad\s*[—–-]", stripped, re.I):
        return SQUAD_DASH_RE.fullmatch(stripped) is not None
    if stripped.lower().startswith("recover"):
        return bool(RECOVER_LIFE_RE.fullmatch(stripped) or KEYWORDS["recover"].regex.fullmatch(stripped.rstrip(".")))
    if is_compound_keyword_line(stripped):
        return True
    raw_tokens = [t.strip() for t in stripped.split(",") if t.strip()]
    if not raw_tokens:
        return False
    tokens: list[str] = []
    for tok in raw_tokens:
        if tokens and not is_keyword_token(tok) and COMPOUND_PARAM_START_RE.match(tokens[-1]):
            tokens[-1] = f"{tokens[-1]}, {tok}"
        else:
            tokens.append(tok)
    return all(is_keyword_token(t) for t in tokens)


# --- PAR-28: "Keyword — [ability]" labelled abilities -----------------------
# RULE 702.142 Boast / 702.177 Exhaust / 702.57 Forecast / Power-up (Marvel) /
# 702.169 Solved / 702.178 Max Speed. Each is a real activated / triggered /
# static ability behind an em-dash label, with the keyword adding a fixed
# restriction to it (a timing/legality gate, a once-per-game cap, a
# solved/speed condition). The label is stripped, the body is parsed by the
# ordinary `segment_line` machinery, and the restriction is applied to the
# resulting spec — never claiming the body alone (which would model a
# working but unrestricted ability).
_KEYWORD_LABELED_ABILITY_RE = re.compile(
    r"^(?P<kw>boast|exhaust|power-up|forecast|solved|max speed)\s*[—-]\s*(?P<body>.+)$",
    re.IGNORECASE | re.DOTALL,
)
#: RULE 702.57b: revealing the card from hand is bookkeeping, not a cost
#: component — peeled off Forecast's cost text before the colon.
_FORECAST_REVEAL_RE = re.compile(
    r",?\s*reveal\s+.+?\s+from your hand\s*:", re.IGNORECASE | re.DOTALL
)


def _apply_keyword_restriction(spec: AbilitySpec, kw: str) -> bool:
    """Fold ``kw``'s fixed rules-restriction onto an already-parsed ability
    ``spec`` (RULE 702.142a/702.177a/702.57a/702.169b-d/702.178a). Returns
    ``False`` if the spec's shape can't carry the restriction (fail-closed)."""
    if kw == "boast":  # RULE 702.142a
        if spec.ability_kind != "activated":
            return False
        spec.effects.append(
            EffectSpec(ACTIVATION_CONDITION_MARKER,
                       {"condition": {"kind": "source_attacked_this_turn"}})
        )
        # PAR-256: the keyword rides on the marker so "boast abilities … cost {N} less" can pick this ability out.
        spec.effects.append(EffectSpec(ONCE_PER_TURN_MARKER, {"keyword": "boast"}))
        return True
    if kw in ("exhaust", "power-up"):  # RULE 702.177a / Power-up
        if spec.ability_kind != "activated":
            return False
        # PAR-207: the keyword rides on the marker, so "whenever you activate an exhaust ability" can tell an
        # Exhaust ability (RULE 702.177) from a Power-up one that is equally once-only.
        spec.effects.append(EffectSpec(ACTIVATE_ONLY_ONCE_MARKER, {"keyword": kw}))
        if kw == "power-up":
            spec.effects.append(EffectSpec(POWERUP_COST_REDUCTION_MARKER, {}))
        return True
    if kw == "forecast":  # RULE 702.57
        if spec.ability_kind != "activated":
            return False
        spec.effects.append(EffectSpec(FROM_HAND_MARKER, {}))
        spec.effects.append(
            EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": {"kind": "your_upkeep"}})
        )
        spec.effects.append(EffectSpec(ONCE_PER_TURN_MARKER, {}))
        return True
    # RULE 702.169b-d Solved / 702.178a Max Speed — the same condition on
    # whichever of the three ability shapes the body turned out to be.
    cond = {"kind": "source_solved"} if kw == "solved" else {"kind": "your_speed_is_max"}
    # A replacement is gated the same way (``binding.core.build_replacements`` reads ``active_if`` off each effect):
    # "Solved — If one or more tokens would be created under your control, …" (Case of the Pilfered Proof).
    if spec.ability_kind in ("static", "replacement"):
        for eff in spec.effects:
            eff.params.setdefault("active_if", cond)
        return True
    if spec.ability_kind == "triggered":
        spec.trigger = {**(spec.trigger or {}), "active_if": cond}
        return True
    spec.effects.append(EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": cond}))
    return True


#: RULE 720.3a: "To solve — [Condition]" means "At the beginning of your end
#: step, if [condition] and this Case is not solved, this Case becomes
#: solved." Modeled as an ordinary phase-triggered ability with the
#: condition as an intervening-if. Only the ``[condition]`` phrasings that
#: map onto the whitelisted `game/static_conditions.py` vocabulary are
#: claimed (fail-closed for the rest — a Case whose solve condition needs an
#: unbuilt per-turn tracker stays UNMODELED, exactly like a battle whose
#: body grammar isn't covered yet).
_TO_SOLVE_RE = re.compile(r"^to solve\s*[—-]\s*(?P<cond>.+?)\.?$", re.IGNORECASE | re.DOTALL)
_TO_SOLVE_CONDITION_RES: list[tuple[re.Pattern[str], Any]] = [
    (re.compile(r"you'?ve cast (?P<n>\d+) or more instant and sorcery spells this turn", re.I),
     lambda m: {"kind": "control_count",
                "selector": "instant_and_sorcery_spells_cast_this_turn", "min": int(m.group("n"))}),
    (re.compile(r"you have no cards in hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_most", "amount": 0}),
    (re.compile(r"you control (?P<n>\d+) or more (?P<what>artifacts|lands|creatures|"
                r"enchantments|detectives)", re.I),
     lambda m: {"kind": "control_count",
                "selector": f"{m.group('what')}_you_control", "min": int(m.group("n"))}),
    (re.compile(r"there are (?P<n>\d+|fifteen) or more cards in your graveyard", re.I),
     lambda m: {"kind": "control_count", "selector": "cards_in_your_graveyard",
                "min": 15 if m.group("n") == "fifteen" else int(m.group("n"))}),
]


def _to_solve_condition_dict(text: str) -> Optional[dict[str, Any]]:
    stripped = text.strip().rstrip(".").strip()
    for pattern, build in _TO_SOLVE_CONDITION_RES:
        m = pattern.fullmatch(stripped)
        if m is not None:
            return build(m)
    return None


def _segment_to_solve(raw: str, *, provenance: ParserProvenance) -> Optional["Segment"]:
    m = _TO_SOLVE_RE.match(raw)
    if m is None:
        return None
    cond = _to_solve_condition_dict(m.group("cond"))
    if cond is None:
        return Segment(raw=raw)  # fail-closed: unrecognised solve condition
    spec = AbilitySpec(
        "triggered",
        effects=[EffectSpec("become_solved", {})],
        trigger={
            "event": "STEP_BEGIN",
            "filter": {"step": "end"},
            "phase_relation": "you",
            "active_if": cond,
        },
        raw_text=raw,
        parser=provenance,
    )
    return Segment(raw=raw, spec=spec, claimed=True)


def segment_keyword_labeled_ability(
    raw: str, *, allow_spell_effect: bool, provenance: ParserProvenance, is_saga: bool
) -> Optional["Segment"]:
    to_solve = _segment_to_solve(raw, provenance=provenance)
    if to_solve is not None:
        return to_solve
    m = _KEYWORD_LABELED_ABILITY_RE.match(raw)
    if m is None:
        return None
    kw = m.group("kw").lower()
    body = m.group("body").strip()
    if kw == "forecast":
        body = _FORECAST_REVEAL_RE.sub(":", body, count=1).strip()
    inner = segment_line(
        body, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    if inner.claimed and inner.spec is None:
        # The body parsed but yields no effect spec — a mana ability
        # ("Exhaust — {G}, {T}: Add three mana of any one color." — Loot, the
        # Pathfinder, the very card RULE 702.177b's example is about) or an
        # informational-only clause. Claimed, but there's no `ActivatedAbility`
        # to fold the once-per-game cap onto — a mana ability gets its cap from
        # `game/mana_abilities.py`'s own "Exhaust —"/"Power-up —" label
        # handling (`ActivationCost.once_per_game`), which reads the same line.
        return Segment(raw=raw, claimed=True)
    if not inner.claimed or inner.spec is None or not _apply_keyword_restriction(
        inner.spec, kw
    ):
        # Body didn't fully parse, or the spec can't carry the restriction:
        # fail closed. This used to fall back to an inert keyword-line claim
        # (the pre-PAR-28 behaviour of `_KEYWORD_TOKEN_RE`'s greedy `.*$`),
        # which made the card MODELED with the whole labelled ability silently
        # missing — PAR-129, 23 cards across Exhaust/Power-up/Boast/Max speed.
        # UNMODELED is correct and recoverable (the body is an ordinary
        # unclaimed clause the ranking can see); a half-model is not.
        return Segment(raw=raw)
    inner.spec.raw_text = raw
    for extra in inner.extra_specs:
        _apply_keyword_restriction(extra, kw)
        extra.raw_text = raw
    return Segment(raw=raw, spec=inner.spec, extra_specs=inner.extra_specs, claimed=True)
