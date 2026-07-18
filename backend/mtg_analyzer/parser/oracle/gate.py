"""Step 4: the coverage gate + the front-end entry point (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE COVERAGE GATE: FAIL-CLOSED,
ALL-OR-NOTHING" and "THE FRONT-END PIPELINE"). This is where the pipeline
comes together: `parse_oracle(card)` runs normalise → segment → match over a
card's oracle text and returns the parsed `AbilitySpec`s **plus a coverage
verdict**.

The gate is all-or-nothing: a card is `MODELED` only if *every* ability line
is claimed — a keyword line (accounted for by the keyword catalogue, anchored
on Scryfall's array), a triggered ability, or a resolve-time effect. Any
unclaimed line makes the whole card `UNMODELED`, and its unclaimed lines are
surfaced (the seed of docs/09's processing list). A half-modeled card that
silently resolves *some* of its text is worse than one honestly not modeled,
so the binder only trusts effect specs from a `MODELED` card.

Pure — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Optional

from .catalogue.counters import entry_counters_condition
from .catalogue.keywords import parse_keywords
from .catalogue.lands import tap_clause_condition
from .catalogue.levels import (
    LEVEL_UP_LINE_RE,
    PT_LINE_RE,
    split_class_blocks,
    split_leveler_blocks,
)
from .catalogue.modal import MODAL_HEADER_RE, collect_mode_bodies, split_modal_block
from .catalogue.static_handlers import commander_eligibility_line
from .normalize import normalize
from .segmenter import (
    Segment,
    _TRIGGER_RE,
    _trigger_condition,
    _trigger_event,
    parse_effect_body,
    segment_line,
)
from .spec import AbilitySpec, EffectSpec, ParserProvenance

MODELED = "MODELED"
UNMODELED = "UNMODELED"

#: Bumped when the catalogue/pipeline changes shape; stamped on every spec's
#: provenance so a cached parse can be invalidated (docs/09 "Versioning").
PARSER_VERSION = "2"


@dataclass
class ParseResult:
    """The front-end's output for one card: specs + a fail-closed coverage verdict."""

    specs: list[AbilitySpec] = field(default_factory=list)
    coverage: str = MODELED
    #: Unclaimed ability lines (template seeds for the processing list, docs/09).
    unclaimed: list[str] = field(default_factory=list)

    @property
    def modeled(self) -> bool:
        return self.coverage == MODELED

    #: The effect-bearing specs (triggered / spell_effect / activated /
    #: static / replacement) parsed from text — as opposed to the keyword
    #: specs, which are safe individually. The binder only trusts these when
    #: the whole card is `MODELED`.
    @property
    def effect_specs(self) -> list[AbilitySpec]:
        return [
            s for s in self.specs
            if s.ability_kind in ("triggered", "spell_effect", "activated", "static", "replacement")
        ]


def _is_spell(card: Any) -> bool:
    return bool(getattr(card, "is_instant", False) or getattr(card, "is_sorcery", False))


def _split_triggered_modal_block(
    lines: list[str], start: int
) -> Optional[tuple[str, dict[str, Any], bool, int, list[str], int]]:
    """A permanent's modal *triggered* ability: "When ~ enters, choose 1 —"
    on one line, then two or more "• " mode lines (RULE 700.2 wrapped in a
    RULE 603.1 trigger) — the trigger-wrapped sibling of `split_modal_block`
    (a modal *spell*'s bare header). Both a recognised trigger event/subject
    scope (`_trigger_event`/`_trigger_condition`, the same grammar
    `segment_line` uses for an ordinary triggered ability) and a modal
    header are required; unlike a plain triggered ability's body, the modal
    header's "effect" is the whole bullet block, not `trig.group("body")`
    itself.

    Returns ``(event, condition, or_both, or_more, choose, mode_bodies,
    next_index)``, or ``None`` if ``lines[start]`` isn't this shape at all,
    or ``choose`` exceeds the number of mode lines actually printed —
    fail-closed, the caller falls back to ordinary per-line segmentation.
    """
    trig = _TRIGGER_RE.match(lines[start].strip())
    if trig is None:
        return None
    header = MODAL_HEADER_RE.match(trig.group("body").strip())
    if header is None:
        return None
    event = _trigger_event(trig.group("cond"))
    if event is None:
        return None
    condition = _trigger_condition(trig.group("cond"))
    if condition is None:
        return None
    collected = collect_mode_bodies(lines, start + 1)
    if collected is None:
        return None
    mode_bodies, next_i = collected
    choose = int(header.group("n"))
    if choose < 1 or choose > len(mode_bodies):
        return None
    return (
        event,
        condition,
        bool(header.group("or_both")),
        bool(header.group("or_more")),
        choose,
        mode_bodies,
        next_i,
    )


def _parse_mode_body(body: str) -> Optional[list[EffectSpec]]:
    """One modal "• " line's effect body → its `EffectSpec`s, or ``None``.

    Tries the bullet as-is first; some cards print an optional mode *name*
    ahead of the effect ("Fight the Current — Return target nonland
    permanent to its owner's hand.", RULE 700.2's "mode text" convention) —
    if the whole bullet doesn't parse and it contains a dash, retry with
    just the text after it.
    """
    effects = parse_effect_body(body)
    if effects is not None:
        return effects
    if " — " in body:
        _, _, rest = body.partition(" — ")
        effects = parse_effect_body(rest.strip())
        if effects is not None:
            return effects
    return None


def _parse_mode_options(
    mode_bodies: list[str],
) -> Optional[tuple[list[list[EffectSpec]], list[str]]]:
    """Each "• " mode body → its `EffectSpec`s, or ``None`` if any one fails
    (fail-closed — a modal block is never half-claimed). Shared by a modal
    spell's and a modal triggered ability's block processing."""
    options: list[list[EffectSpec]] = []
    descriptions: list[str] = []
    for body in mode_bodies:
        effects = _parse_mode_body(body)
        if effects is None:
            return None
        options.append(effects)
        descriptions.append(body)
    return options, descriptions


#: Parse-on-load memoization (docs/09 "parse-on-load / bind-per-game
#: linking"): `parse_oracle` is a pure function of a handful of a card's
#: fields (see `_parse_cache_key`), but re-runs the full normalise →
#: segment → match pipeline from scratch on every call — and it's called
#: once per `GameObject` built (`ability_catalogue.specs_for`), so the same
#: popular card (Sol Ring, Swords to Plowshares, …) gets re-parsed on every
#: copy, every game. Cache the `ParseResult` per distinct input; unbounded
#: is fine here — the key space is the real card pool (tens of thousands),
#: each entry a handful of small dataclasses, and a process's `CardDatabase`
#: already holds every card it has ever loaded in memory anyway (docs/09
#: versioning: bump `PARSER_VERSION` and clear this alongside a pipeline
#: change if a stale entry from a previous version ever mattered — today
#: nothing persists this cache across a process restart, so it never does).
_PARSE_CACHE: dict[tuple[Any, ...], ParseResult] = {}


def _parse_cache_key(card: Any) -> tuple[Any, ...]:
    """Every field `_parse_oracle_uncached`/`parse_keywords` actually reads.

    Content-keyed rather than identity- or name-keyed on purpose: a fixture
    `Card` built fresh per test (or a real card whose row gets refetched
    with updated text) must not collide with a stale cache entry that
    merely shares a name.
    """
    return (
        getattr(card, "name", "") or "",
        getattr(card, "oracle_text", "") or "",
        tuple(getattr(card, "keywords", None) or ()),
        bool(getattr(card, "is_instant", False)),
        bool(getattr(card, "is_sorcery", False)),
        bool(getattr(card, "is_saga", False)),
        bool(getattr(card, "is_leveler", False)),
        bool(getattr(card, "is_class", False)),
    )


def parse_oracle(card: Any) -> ParseResult:
    """Memoized entry point — see `_parse_oracle_uncached` for the real work.

    Returns a deep copy of the cached `ParseResult` so a caller is always
    free to treat its `AbilitySpec`s as its own (matches
    `ability_catalogue.register`'s "factory returns fresh specs each call"
    contract for the hand-authored registry) even though the parse itself
    now runs at most once per distinct input.
    """
    key = _parse_cache_key(card)
    cached = _PARSE_CACHE.get(key)
    if cached is None:
        cached = _parse_oracle_uncached(card)
        _PARSE_CACHE[key] = cached
    return copy.deepcopy(cached)


def _parse_oracle_uncached(card: Any) -> ParseResult:
    """Parse a card's oracle text into `AbilitySpec`s with a coverage verdict.

    Keyword specs come from the keyword catalogue (anchored on Scryfall's
    ``keywords`` array); the remaining lines are normalised, segmented, and run
    through the effect-handler table. A card with no oracle text (a vanilla
    creature) is trivially `MODELED` with no specs.

    A Leveler (RULE 711.4c) or a Class (RULE 716.3) prints a multi-line
    **block** structure ordinary per-line segmentation can't see across —
    each block's body lines only apply while the object's own level/class-
    level counter is in that block's range. `_process_line` is the ordinary
    per-line dispatch this function always used; `_process_leveler_body`/
    `_process_class_body` wrap it to also tag the resulting specs with that
    gating (consumed by `continuous.group_selector_objects` for static specs,
    `effect_binder._trigger_condition` for triggered ones — both via
    `min_level`/`max_level`/`level_counter`).
    """
    provenance = ParserProvenance(version=PARSER_VERSION, source="rule:oracle")
    keyword_specs = parse_keywords(card)

    raw = getattr(card, "oracle_text", "") or ""
    normalized = normalize(raw, getattr(card, "name", None))
    if not normalized:
        return ParseResult(specs=list(keyword_specs), coverage=MODELED)

    allow_spell_effect = _is_spell(card)
    is_saga = bool(getattr(card, "is_saga", False))
    is_leveler = bool(getattr(card, "is_leveler", False))
    is_class = bool(getattr(card, "is_class", False))
    effect_specs: list[AbilitySpec] = []
    unclaimed: list[str] = []
    all_claimed = True

    def _process_line(line: str) -> None:
        nonlocal all_claimed
        # RULE 614.1 "enters tapped" clauses are covered by the engine's own
        # tapped-entry machinery (`game/ability_catalogue.land_tap_condition`,
        # resolved by `RulesEngine.enter_land_tapped`), not through an effect
        # spec — claim the line without emitting one, the same way a mana
        # ability's "add {g}" is covered-without-spec in the segmenter.
        if tap_clause_condition(line) is not None:
            return
        # RULE 614.1-style "enters with N counters" clauses: same split as
        # tapped-entry above — covered by `game/ability_catalogue.
        # entry_counters` (`RulesEngine`'s battlefield-entry resolution),
        # not an effect spec.
        if entry_counters_condition(line) is not None:
            return
        # RULE 903.3 "~ can be your commander." — a deck-legality permission
        # with no in-game behavioral effect (see `commander_eligibility_line`'s
        # docstring): claim the line, contribute nothing, same split as the
        # two tapped-entry/counter checks above.
        if commander_eligibility_line(line):
            return
        seg: Segment = segment_line(
            line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
        )
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
        elif seg.spec is not None:
            effect_specs.append(seg.spec)

    def _tag_level_gate(
        spec: AbilitySpec, gate: dict[str, Any], default_affects: Optional[str]
    ) -> None:
        if spec.ability_kind == "static":
            for effect in spec.effects:
                if default_affects is not None:
                    effect.params.setdefault("affects", default_affects)
                effect.params.update(gate)
            effect_specs.append(spec)
        elif spec.ability_kind == "triggered":
            spec.trigger = {**(spec.trigger or {}), **gate}
            effect_specs.append(spec)
        else:
            effect_specs.append(spec)

    def _grant_keyword_line_spec(line: str, affects: str, gate: dict[str, Any]) -> AbilitySpec:
        keywords = [k.strip() for k in line.split(",") if k.strip()]
        return AbilitySpec(
            "static",
            effects=[EffectSpec("grant_keyword", {"keywords": keywords, "affects": affects, **gate})],
            raw_text=line,
            parser=provenance,
        )

    def _process_leveler_body(line: str, lo: int, hi: Optional[int]) -> None:
        nonlocal all_claimed
        gate = {"min_level": lo, "max_level": hi}
        pt = PT_LINE_RE.match(line.strip())
        if pt is not None:
            power, toughness = pt.group("power"), pt.group("toughness")
            if power == "*" or toughness == "*":
                # CDA-based Leveler P/T isn't modeled (no card in the pool
                # needs it) — fail closed rather than guess.
                all_claimed = False
                unclaimed.append(line)
                return
            effect_specs.append(AbilitySpec(
                "static",
                effects=[EffectSpec("pt_set", {
                    "power": int(power), "toughness": int(toughness), "affects": "self", **gate,
                })],
                raw_text=line, parser=provenance,
            ))
            return
        seg = segment_line(line, allow_spell_effect=False, provenance=provenance, is_saga=False)
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
            return
        if seg.keyword_line:
            # A tier-scoped keyword line ("Flying, haste" under LEVEL 7+)
            # becomes a level-gated grant, not an unconditional intrinsic
            # keyword — `parse_keywords`'s Leveler cross-check already
            # excludes these from the always-on set for exactly this reason.
            effect_specs.append(_grant_keyword_line_spec(line, "self", gate))
            return
        if seg.spec is not None:
            _tag_level_gate(seg.spec, gate, default_affects="self")

    def _process_modal_block(
        header: str, or_both: bool, or_more: bool, choose: int, mode_bodies: list[str]
    ) -> None:
        nonlocal all_claimed
        # RULE 700.2: a modal spell's own bare header. A permanent's modal
        # *triggered* ability ("When ~ enters, choose one —") is a different
        # shape (the header trails a trigger wrapper) — see
        # `_process_triggered_modal_block` below.
        parsed = _parse_mode_options(mode_bodies)
        if parsed is None:
            all_claimed = False
            unclaimed.append(header)
            unclaimed.extend(f"• {b}" for b in mode_bodies)
            return
        options, descriptions = parsed
        effect_specs.append(AbilitySpec(
            "spell_effect",
            effects=[],
            modes={
                "or_both": or_both,
                "at_least": or_more,
                "choose": choose,
                "options": options,
                "descriptions": descriptions,
            },
            raw_text=header,
            parser=provenance,
        ))

    def _process_triggered_modal_block(
        header: str,
        event: str,
        condition: dict[str, Any],
        or_both: bool,
        or_more: bool,
        choose: int,
        mode_bodies: list[str],
    ) -> None:
        nonlocal all_claimed
        # RULE 700.2 wrapped in a RULE 603.1 trigger — e.g. "When ~ enters
        # the battlefield, choose one — • Mode A. • Mode B.": the chosen
        # mode is picked interactively as the ability is put on the stack
        # (`game/rules_engine.py`'s `trigger_mode` choice), not at cast time
        # like a modal spell.
        parsed = _parse_mode_options(mode_bodies)
        if parsed is None:
            all_claimed = False
            unclaimed.append(header)
            unclaimed.extend(f"• {b}" for b in mode_bodies)
            return
        options, descriptions = parsed
        effect_specs.append(AbilitySpec(
            "triggered",
            effects=[],
            trigger={"event": event, "condition": condition},
            modes={
                "or_both": or_both,
                "at_least": or_more,
                "choose": choose,
                "options": options,
                "descriptions": descriptions,
            },
            raw_text=header,
            parser=provenance,
        ))

    def _process_class_body(line: str, level: int) -> None:
        nonlocal all_claimed
        gate = {"min_level": level, "level_counter": "class_level"}
        seg = segment_line(line, allow_spell_effect=False, provenance=provenance, is_saga=False)
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
            return
        if seg.spec is not None:
            _tag_level_gate(seg.spec, gate, default_affects=None)

    if is_leveler:
        preamble, blocks = split_leveler_blocks(normalized)
        for line in preamble:
            level_up = LEVEL_UP_LINE_RE.match(line.strip())
            if level_up is not None:
                # RULE 711.4a: the actual "put a level counter on this,
                # sorcery speed only" mechanic — see `LEVEL_UP_LINE_RE`'s
                # docstring for why this can't just fall through to the
                # generic per-line dispatch.
                effect_specs.append(AbilitySpec(
                    "activated",
                    effects=[EffectSpec("add_counters", {"amount": 1, "kind": "level"})],
                    cost={"text": level_up.group("cost"), "sorcery_speed_only": True},
                    raw_text=line, parser=provenance,
                ))
                continue
            _process_line(line)
        for lo, hi, body_lines in blocks:
            for line in body_lines:
                _process_leveler_body(line, lo, hi)
    elif is_class:
        preamble, blocks = split_class_blocks(normalized)
        for line in preamble:
            _process_line(line)
        for level, cost_text, body_lines in blocks:
            # RULE 716.3/716.4c: "<cost>: Level N" is itself a sorcery-speed
            # activated ability, legal only from the level just below it
            # (`GameEngine._can_activate_class_level`) — the header carries
            # no effect body of its own to segment (the effect is "become
            # this level", `ClassLevelEffect`), unlike an ordinary "<cost>:
            # <effect>" line.
            effect_specs.append(AbilitySpec(
                "activated",
                effects=[EffectSpec("class_level", {"level": level})],
                cost={"text": cost_text, "sorcery_speed_only": True, "class_level": level},
                raw_text=f"{cost_text}: level {level}",
                parser=provenance,
            ))
            for line in body_lines:
                _process_class_body(line, level)
    else:
        lines = [line for line in normalized.split("\n") if line.strip()]
        i = 0
        while i < len(lines):
            block = split_modal_block(lines, i) if allow_spell_effect else None
            if block is not None:
                or_both, or_more, choose, mode_bodies, next_i = block
                _process_modal_block(lines[i], or_both, or_more, choose, mode_bodies)
                i = next_i
                continue
            trig_block = _split_triggered_modal_block(lines, i)
            if trig_block is not None:
                event, condition, or_both, or_more, choose, mode_bodies, next_i = trig_block
                _process_triggered_modal_block(
                    lines[i], event, condition, or_both, or_more, choose, mode_bodies
                )
                i = next_i
                continue
            _process_line(lines[i])
            i += 1

    return ParseResult(
        specs=list(keyword_specs) + effect_specs,
        coverage=MODELED if all_claimed else UNMODELED,
        unclaimed=unclaimed,
    )
