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
import hashlib
import re
from .catalogue.clause_reading import ClauseReading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .catalogue.counters import entry_counters_condition
from .catalogue.cost_text import scan_cost_text
from .catalogue.keywords import parse_keywords
from .catalogue.kicker_mana import kicker_x_mana_restriction_condition
from .catalogue.lands import tap_clause_condition, tapped_entry_choice_tail
from .catalogue.levels import (
    CLASS_BECOMES_LEVEL_RE,
    LEVEL_UP_LINE_RE,
    PT_LINE_RE,
    split_class_blocks,
    split_leveler_blocks,
)
from .catalogue.modal import (
    CONDITIONAL_MODAL_HEADER_RE, MODAL_HEADER_RE, conditional_modal_override,
    collect_mode_bodies, split_modal_block, split_named_choice_block, split_spree_block,
)
from .catalogue.opening_hand import (
    opening_hand_battlefield_conditional_permission_line,
    opening_hand_battlefield_permission_line,
    opening_hand_graveyard_permission_line,
)
from .catalogue.station import split_station_blocks, station_creature_threshold
from .catalogue.clause_primitives import ACTION_ONCE_PER_TURN_MARKER
from .catalogue.effect_rows.shared import EVENT_PLAYER_EVENTS_KEY
from .catalogue.static_handlers import commander_eligibility_line, deck_any_number_line
from .normalize import normalize
from .residue import UnclaimedSpan, minimal_unclaimed_span
from .segmenter import (
    FLASHBACK_DISCOUNT_LINE_RE,
    Segment,
    peel_optional,
    TRIGGER_RE,
    parse_effect_body,
    segment_line,
)
from .spec import AbilitySpec, EffectSpec, ParserProvenance, contains_marker, fold_action_limit
from .catalogue.fight_sequences import reordered_fight_text
from ...models.cards.support_policy import unsupported_reason

MODELED = "MODELED"
UNMODELED = "UNMODELED"
#: Permanent product exclusions (including stickers, RULE 123) — see
#: `docs/implementation-state/DEFERRED.md` — not a "not yet" gap like an ordinary
#: UNMODELED card. Sticker Sheets and cards mentioning them are `NEVER_SUPPORTED`
#: instead of `UNMODELED` so its unclaimed clauses never surface in the
#: processing-list backlog ranking (they'd otherwise sit there forever,
#: since no handler will ever claim them).
NEVER_SUPPORTED = "NEVER_SUPPORTED"

#: RULE 702.6/702.67/702.151: the attach keywords whose printed cost must be captured for the ability to bind.
_ATTACH_KEYWORDS = frozenset({"equip", "fortify", "reconfigure"})

#: Bumped when the catalogue/pipeline changes shape; stamped on every spec's provenance so a cached parse
#: can be invalidated (docs/09 "Versioning"). Per-version changelog: `PARSER_VERSION_HISTORY.md` (this directory).
PARSER_VERSION = "721"


def parser_source_hash() -> str:
    """SHA-1 over every front-end `.py` file's path + bytes, sorted for
    determinism.

    Exists so a stale-coverage measurement (`PARSER_LONG_TAIL.md`'s own
    documented failure mode: "measuring twice within one batch... silently
    reuses the first run's rows" when `PARSER_VERSION` isn't bumped) is
    structurally detectable rather than a discipline someone has to
    remember. `test_parser_version_lock.py` pins this hash, for the current
    `PARSER_VERSION`, in the checked-in `PARSER_VERSION.lock` file — any
    front-end edit that changes this hash without a matching lock-file
    update (via `scripts/update_parser_version_lock.py`) fails that test.
    Deliberately *not* used as `PARSER_VERSION` itself: coverage-ledger rows
    are keyed on `PARSER_VERSION` (`services/coverage_db.py`), and a version
    that changes on every edit — including comment-only ones — would
    invalidate all ~34k rows for edits that never touch parse behavior.
    """
    root = Path(__file__).resolve().parent
    files = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    digest = hashlib.sha1()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        # Git's Windows checkout can use CRLF; identical source must keep the same fingerprint.
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    # This shared model policy also determines the parser verdict.
    policy_path = root.parents[1] / "models" / "cards" / "support_policy.py"
    digest.update(b"models/cards/support_policy.py")
    digest.update(policy_path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


@dataclass
class ParseResult:
    """The front-end's output for one card: specs + a fail-closed coverage verdict."""

    specs: list[AbilitySpec] = field(default_factory=list)
    unsupported_reason: Optional[str] = None
    coverage: str = MODELED
    #: Unclaimed ability lines (template seeds for the processing list, docs/09).
    unclaimed: list[str] = field(default_factory=list)

    @property
    def modeled(self) -> bool:
        return self.coverage == MODELED

    @property
    def never_supported(self) -> bool:
        """A permanent product exclusion, distinct from incomplete grammar."""
        return self.coverage == NEVER_SUPPORTED

    #: The effect-bearing specs (triggered / spell_effect / activated /
    #: static / replacement / enter_replacement) parsed from text — as
    #: opposed to the keyword specs, which are safe individually. The binder
    #: only trusts these when the whole card is `MODELED`. ``enter_
    #: replacement`` (RULE 601.2b/614.1c/614.12 "as ~ enters" — Card-pool
    #: Batch 7's "choose a creature type/color", `static_handlers.
    #: enter_choice_specs`) was added alongside the other five here so
    #: `card_registry.specs_for` actually binds it for an unregistered
    #: MODELED card, not just keeps it visible on `specs`.
    @property
    def effect_specs(self) -> list[AbilitySpec]:
        return [
            s for s in self.specs
            if s.ability_kind in (
                "triggered", "spell_effect", "activated", "static", "replacement",
                "enter_replacement",
            )
        ]


def _mentions_stickers(raw: str) -> bool:
    """RULE 123 Stickers — declared a permanent non-goal (see
    `docs/implementation-state/DEFERRED.md`), not merely deprioritized. A simple
    substring check is deliberate: real sticker cards say "sticker sheet"/
    "sticker" in their own oracle text (there is no other card-text idiom
    that uses the word), so this never needs the segmenter/normalize
    machinery to decide — it's an early exit, not a parsed clause.
    """
    return "sticker" in raw.lower()


#: RULE 207.2c: an *ability word* ("For Mirrodin!") has no rules meaning of
#: its own — the reminder text immediately following it *is* the actual
#: ability, unlike a keyword's reminder text (which merely restates a
#: standing rule the engine already knows). `normalize` unconditionally
#: strips every parenthetical as reminder text (`_REMINDER`), which would
#: silently discard this ability word's entire rules text before the
#: segmenter ever sees it — the same "read it before normalize strips
#: parentheticals" problem `game/dungeons.py`'s room-arrow parsing solves by
#: staying outside this pipeline entirely. "For Mirrodin!" instead only
#: needs its *one* fixed reminder-text body promoted to real, ordinary
#: oracle text (9 SOLO cache cards, MEC-28 — all print the identical
#: wording, RULE 207.2's ability-word reminder text is never
#: card-specific), so it's cheaper to rewrite the raw line in place than to
#: build a second raw-text-reading subsystem for one template: "when this
#: Equipment enters, create a 2/2 red Rebel creature token, then attach
#: this to it." then flows through `normalize`/`segment_line` exactly like
#: any other printed ETB trigger (`effect_rows.tokens_animate_misc._CREATE_TOKEN_AND_ATTACH_RE`
#: already covers the create-and-attach body once it's real text again).
_FOR_MIRRODIN_RE = re.compile(
    r"For Mirrodin! \((?P<reminder>[^()]*)\)", re.IGNORECASE,
)


def _expand_ability_word_reminders(raw: str) -> str:
    """Promote known ability-word reminder text to real oracle text, before
    `normalize` strips every parenthetical (see `_FOR_MIRRODIN_RE`)."""
    return _FOR_MIRRODIN_RE.sub(lambda m: m.group("reminder"), raw)


#: An ability-word paragraph that continues a spell's previous instruction
#: (see `parse_oracle`): only after a sentence end, only a leading "If".
_SPELL_RIDER_PARAGRAPH_RE = re.compile(
    r"(?<=\.)\n(?:Infusion|Addendum) — (?P<rider>If )", re.I,
)


def _is_spell(card: Any) -> bool:
    return bool(getattr(card, "is_instant", False) or getattr(card, "is_sorcery", False))


def _split_triggered_modal_block(
    lines: list[str], start: int, provenance: ParserProvenance
) -> Optional[tuple[list[dict[str, Any]], bool, bool, bool, bool, Optional[dict[str, Any]], int, list[str], int]]:
    """A permanent's modal *triggered* ability: "When ~ enters, choose 1 —"
    on one line, then two or more "• " mode lines (RULE 700.2 wrapped in a
    RULE 603.1 trigger) — the trigger-wrapped sibling of `split_modal_block`
    (a modal *spell*'s bare header). A recognised trigger wrapper and a modal
    header are both required; unlike a plain triggered ability's body, the
    modal header's "effect" is the whole bullet block, not `trig.group("body")`
    itself.

    The trigger wrapper is recognised by segmenting ``"<wrapper>, draw a
    card."`` as an ordinary triggered line and lifting its whole ``trigger``
    dict — the *same* grammar `segment_line` uses, not the narrow generic
    `_trigger_event`/`_trigger_condition` pair — so every cast-spell / damage
    / nth-event / phase-step / combined-event trigger a plain triggered
    ability would claim also drives a modal block (Elder Gargaroth, Ojutai
    Exemplars, Etherwrought Page, Cosmogrand Zenith, …).

    Returns ``(triggers, or_both, or_more, repeatable, exhausted, override, choose, mode_bodies, next_index)``,
    or ``None`` if ``lines[start]`` isn't this shape at all, its wrapper
    isn't a recognised trigger, or ``choose`` exceeds the number of mode
    lines actually printed — fail-closed, the caller falls back to ordinary
    per-line segmentation.
    """
    trig = TRIGGER_RE.match(lines[start].strip())
    if trig is None:
        return None
    modal_body = trig.group("body").strip()
    header = MODAL_HEADER_RE.match(modal_body)
    conditional = CONDITIONAL_MODAL_HEADER_RE.match(modal_body)
    if header is None and conditional is None:
        return None
    override = (
        conditional_modal_override(conditional.group("condition"), conditional.group("choice"))
        if conditional is not None else None
    )
    if conditional is not None and override is None:
        return None
    probe = segment_line(
        lines[start].strip()[: trig.start("body")] + "draw a card.",
        allow_spell_effect=False,
        provenance=provenance,
    )
    if not probe.claimed or probe.spec is None or probe.spec.ability_kind != "triggered":
        return None
    triggers = [spec.trigger for spec in [probe.spec, *probe.extra_specs]]
    if any(not trigger or trigger.get("event") is None for trigger in triggers):
        return None
    # Exhausted mode history belongs to the printed ability, while separate
    # event bindings currently have independent mode histories.
    if len(triggers) > 1 and header and header.group("exhausted"):
        return None
    collected = collect_mode_bodies(lines, start + 1)
    if collected is None:
        return None
    mode_bodies, next_i = collected
    choose = int((header or conditional).group("n"))
    if choose < 1 or choose > len(mode_bodies):
        return None
    return (
        triggers,
        bool(header and header.group("or_both")),
        bool(header and header.group("or_more")),
        "same mode more than once" in modal_body.lower(),
        bool(header and header.group("exhausted")),
        override,
        choose,
        mode_bodies,
        next_i,
    )


_REFLEXIVE_MODAL_RE = re.compile(
    r"^you may pay (?P<cost>[^.]+)\.\s*when you do,?\s*(?P<header>choose .+)$"
)


#: RULE 706.1 roll instruction inside a header line — the line a RULE 706.3a results table hangs off. The header
#: is any ordinary ability line (a trigger, a ``<cost>:`` activation, a spell, a pre-effect "choose target creature,
#: then roll a d20", an "…and add the number of cards in your hand" modifier) whose last instruction is the roll;
#: `_process_dice_table_block` parses it through `segment_line` like any other line and attaches the table.
_DICE_HEADER_ROLL_RE = re.compile(
    r"\broll (?:a|two|three|\d+) (?:d\d+|\d+-sided (?:die|dice))\b", re.IGNORECASE,
)
#: One striation of a RULE 706.3a results table: "1—9 | <effect>",
#: "20 | <effect>", "10+ | <effect>" (`N+` is the single-endpoint form).
#: The `|` separator and em/en-dash range are exactly what `normalize`
#: leaves (see `Contact Other Plane` / `Delina, Wild Mage`).
_DICE_TABLE_ROW_RE = re.compile(
    r"^(?P<lo>\d+)(?:\s*[—–-]\s*(?P<hi>\d+)|(?P<plus>\+)|\s+or\s+(?P<minus>less))?\s*\|\s*(?P<body>.+?)\.?$",
    re.IGNORECASE,
)
#: The "indicated effect" table style — "Roll a six-sided die. This ability has the indicated effect." followed by
#: "1 — <effect>" lines (Jack-in-the-Mox, Strategy, Schmategy, Urza's Science Fair Project): one face per row.
_DICE_INDICATED_TAIL_RE = re.compile(
    r"\s*(?:this ability has|~ has|~ gets) the indicated (?:effect|result)\.?$", re.IGNORECASE,
)
_DICE_INDICATED_ROW_RE = re.compile(r"^(?P<lo>\d+)\s*[—–-]\s*(?P<body>.+?)\.?$")
#: "Create a 1/1 red Goblin creature token." then, in a later row, "Create 2 of those tokens." (Swarming Goblins): the
#: later row names the earlier row's token, so it is that row's text with the count changed.
_DICE_ONE_TOKEN_ROW_RE = re.compile(r"^create an? (?P<token>.+?) tokens?$", re.IGNORECASE)
_DICE_OF_THOSE_TOKENS_RE = re.compile(r"^create (?P<n>\d+) of those tokens$", re.IGNORECASE)
_DICE_COPY_TOKEN_ROW_RE = re.compile(r"^create an? (?:tapped and attacking )?token that'?s a copy of ", re.IGNORECASE)
#: "…you may roll again" closing a results-table row (Delina, Wild Mage): the roll repeats, table and all.
_DICE_ROLL_AGAIN_TAIL_RE = re.compile(r"\.?\s*you may roll again\.?$", re.IGNORECASE)


def _expand_of_those_tokens(
    rows: list[tuple[Optional[int], Optional[int], str]],
) -> list[tuple[Optional[int], Optional[int], str]]:
    """``rows`` with each "create N of those tokens" spelled out as the token an earlier row of the table created."""
    token: Optional[str] = None
    copy_body: Optional[str] = None
    out: list[tuple[Optional[int], Optional[int], str]] = []
    for lo, hi, body in rows:
        plural = _DICE_OF_THOSE_TOKENS_RE.match(body.strip())
        if plural is not None and copy_body is not None and plural.group("n") == "1":
            # PAR-153 (Delina): "create one of those tokens" after a "create a … token that's a copy of …" row is
            # that same row again (the tokens are its copy, with its exceptions).
            body = copy_body
        elif plural is not None and token is not None:
            body = f"create {plural.group('n')} {token} tokens"
        else:
            single = _DICE_ONE_TOKEN_ROW_RE.match(body.strip())
            if single is not None and "token" not in single.group("token"):
                token = single.group("token")
            if _DICE_COPY_TOKEN_ROW_RE.match(body.strip()):
                copy_body = body.strip()
        out.append((lo, hi, body))
    return out


#: ``target_kind`` values that name a referent an earlier instruction established rather than asking for a RULE 115
#: target (a created token, the previous clause's pick, the trigger's firing object).
_REFERENT_TARGET_KINDS: frozenset[str] = frozenset({
    "created", "previous_target", "trigger_subject", "attached_permanent", "trigger_subject_controller",
})


def _announces_target(spec: EffectSpec) -> bool:
    """Whether ``spec`` asks for a RULE 115 target (which a results-table row cannot announce: the roll comes later)."""
    kind = spec.params.get("target_kind")
    if kind is not None and kind not in _REFERENT_TARGET_KINDS:
        return True
    return any(spec.params.get(key) is not None for key in ("kinds", "target_kinds"))


def _split_dice_table_block(
    lines: list[str], start: int,
) -> Optional[tuple[str, list[tuple[Optional[int], Optional[int], str]], int]]:
    """A RULE 706 roll instruction followed by one or more results-table rows (RULE 706.3a/706.3b — the roll,
    its modifiers and its table are one ability).

    Returns ``(header, rows, next_index)`` where ``rows`` is a list of ``(lo, hi_or_None, body_text)`` — ``lo`` is
    ``None`` for "N or less" (open below) and ``hi`` ``None`` is the ``N+`` open-ended endpoint — or ``None`` if
    ``lines[start]`` isn't this shape or a row is malformed (fail-closed). The "you may roll again" tail of a row is
    recognised by `_process_dice_table_block` (PAR-153, Delina).
    """
    header = lines[start].strip()
    if _DICE_HEADER_ROLL_RE.search(header) is None:
        return None
    indicated = _DICE_INDICATED_TAIL_RE.search(header)
    if indicated is not None:
        header = header[: indicated.start()].strip()
    rows: list[tuple[Optional[int], Optional[int], str]] = []
    j = start + 1
    while j < len(lines):
        text = lines[j].strip()
        if indicated is not None:
            row = _DICE_INDICATED_ROW_RE.match(text)
            if row is None:
                break
            face = int(row.group("lo"))
            rows.append((face, face, row.group("body").strip()))
        else:
            row = _DICE_TABLE_ROW_RE.match(text)
            if row is None:
                break
            if row.group("minus"):
                rows.append((None, int(row.group("lo")), row.group("body").strip()))
            else:
                lo = int(row.group("lo"))
                hi = None if row.group("plus") else int(row.group("hi") or lo)
                rows.append((lo, hi, row.group("body").strip()))
        j += 1
    if not rows:
        return None
    return (header, rows, j)


def _split_reflexive_modal_block(
    lines: list[str], start: int,
) -> Optional[tuple[Optional[dict[str, Any]], str, bool, bool, bool, int, list[str], int]]:
    """Recognise ``You may pay <cost>. When you do, choose N —`` plus bullets.

    This is intentionally a gate-level block wrapper: its payoff is a fresh
    RULE 603.11 triggered ability, so treating it as the ordinary synchronous
    ``pay_cost_then`` clause would choose targets/modes at the wrong time.
    """
    line = lines[start].strip()
    trigger: Optional[dict[str, Any]] = None
    match = _REFLEXIVE_MODAL_RE.match(line)
    if match is None:
        wrapper = TRIGGER_RE.match(line)
        if wrapper is None:
            return None
        match = _REFLEXIVE_MODAL_RE.match(wrapper.group("body").strip())
        if match is None:
            return None
        probe = segment_line(
            line[: wrapper.start("body")] + "draw a card.",
            allow_spell_effect=False,
            provenance=ParserProvenance(version=PARSER_VERSION, source="reflexive-modal", confidence=1.0),
        )
        if not probe.claimed or probe.spec is None or probe.spec.ability_kind != "triggered":
            return None
        trigger = probe.spec.trigger
    header = MODAL_HEADER_RE.match(match.group("header").strip())
    if header is None:
        return None
    collected = collect_mode_bodies(lines, start + 1)
    if collected is None:
        return None
    bodies, next_i = collected
    choose = int(header.group("n"))
    if choose < 1 or choose > len(bodies):
        return None
    return (
        trigger, match.group("cost").strip(), bool(header.group("or_both")),
        bool(header.group("or_more")), "same mode more than once" in match.group("header").lower(),
        choose, bodies, next_i,
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
#: once per `GameObject` built (`card_registry.specs_for`), so the same
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
        getattr(card, "_unsupported_reason", None),
        getattr(card, "digital", None),
        tuple(sorted(getattr(card, "games", None) or ())),
        tuple(sorted((getattr(card, "legalities", None) or {}).items())),
        getattr(card, "back_oracle_text", "") or "",
        getattr(card, "back_type_line", "") or "",
        getattr(card, "type_line", "") or "",
        getattr(card, "name", "") or "",
        getattr(card, "oracle_text", "") or "",
        tuple(getattr(card, "keywords", None) or ()),
        bool(getattr(card, "is_instant", False)),
        bool(getattr(card, "is_sorcery", False)),
        bool(getattr(card, "is_saga", False)),
        bool(getattr(card, "is_leveler", False)),
        bool(getattr(card, "is_class", False)),
        bool(getattr(card, "is_station", False)),
        # Station's `type_change` P/T (vehicle_*) and the Room split-layout test read these;
        # the back_* fields feed `back_face()`/`flip_face()`, which the Room/flip halves parse.
        getattr(card, "layout", "") or "",
        getattr(card, "vehicle_power", None),
        getattr(card, "vehicle_toughness", None),
        getattr(card, "back_name", "") or "",
        getattr(card, "back_mana_cost_string", "") or "",
        tuple(getattr(card, "back_keywords", None) or ()),
        getattr(card, "back_power", None),
        getattr(card, "back_toughness", None),
    )


#: Effect types whose static form reads ``active_if`` (`registry._SELECTOR_KEYS` -> the layer
#: engine or a permission module's own gate); a named-choice option built from anything else would
#: apply unconditionally, so the gate fails closed on it instead.
_NAMED_MODE_STATIC_EFFECTS = frozenset({
    "anthem", "grant_keyword", "trigger_doubler", "graveyard_cast_permission",
    "self_graveyard_or_exile_cast_permission", "top_library_permission", "cost_reduction",
})


def _named_mode_gated(spec: AbilitySpec, label: str) -> Optional[AbilitySpec]:
    """``spec`` live only while ``GameObject.chosen_mode`` is ``label`` (None = cannot be gated)."""
    condition = {"kind": "chosen_mode", "mode": label.strip().lower()}
    if spec.ability_kind == "triggered":
        spec.trigger = {**(spec.trigger or {}), "named_mode": condition["mode"]}
        return spec
    if spec.ability_kind == "static" and spec.effects:
        for effect in spec.effects:
            if effect.type not in _NAMED_MODE_STATIC_EFFECTS:
                return None
            existing = effect.params.get("active_if")
            effect.params["active_if"] = (
                {"kind": "all", "conditions": [existing, condition]} if existing else condition
            )
        return spec
    return None


def _effect_nodes(value):
    """Walk serialized and bound spec shapes without losing mutable params."""
    if isinstance(value, AbilitySpec):
        yield from _effect_nodes(value.effects)
        yield from _effect_nodes(value.modes)
    elif isinstance(value, EffectSpec):
        yield value.type, value.params
        yield from _effect_nodes(value.params)
    elif isinstance(value, dict):
        if isinstance(value.get("type"), str) and isinstance(value.get("params"), dict):
            yield value["type"], value["params"]
        for child in value.values():
            yield from _effect_nodes(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _effect_nodes(child)


def _restore_printed_token_names(specs: list[AbilitySpec], raw: str) -> None:
    """Keep literal proper names after case-folded grammar recognition."""
    names = {
        match.group("name").casefold(): match.group("name")
        for match in re.finditer(
            r"\bcreate (?P<name>[^.\n]+?), a legendary \d+/\d+ ", raw, re.IGNORECASE,
        )
    }
    if not names:
        return

    def restore(value):
        if isinstance(value, dict):
            name = value.get("token_name")
            if isinstance(name, str) and name.casefold() in names:
                value["token_name"] = names[name.casefold()]
            for child in value.values():
                restore(child)
        elif isinstance(value, list):
            for child in value:
                restore(child)
        elif isinstance(value, EffectSpec):
            restore(value.params)

    for spec in specs:
        restore(spec.effects)
        restore(spec.modes)


def parse_oracle(card: Any) -> ParseResult:
    """Memoized entry point — see `_parse_oracle_uncached` for the real work.

    Returns a deep copy of the cached `ParseResult` so a caller is always
    free to treat its `AbilitySpec`s as its own (matches
    `card_registry.register`'s "factory returns fresh specs each call"
    contract for the hand-authored registry) even though the parse itself
    now runs at most once per distinct input.
    """
    reason = unsupported_reason(card)
    if reason:
        return ParseResult(coverage=NEVER_SUPPORTED, unsupported_reason=reason)
    key = _parse_cache_key(card)
    cached = _PARSE_CACHE.get(key)
    if cached is None:
        halves = _room_halves(card)
        flip = _flip_halves(card)
        if halves:
            cached = _merge_room_halves([parse_oracle(half) for half in halves])
        elif flip:
            cached = _merge_flip_halves(parse_oracle(flip[0]), parse_oracle(flip[1]))
        else:
            cached = _parse_oracle_uncached(card)
        _PARSE_CACHE[key] = cached
    return copy.deepcopy(cached)


def _room_halves(card: Any) -> list[Any]:
    """The two halves of a whole Room card (RULE 709.5: a split card with a shared "Room" type line), each
    as a card of its own, or ``[]`` for anything else. The front fields of a cached `Card` are the left
    half and its ``back_*`` fields the right one; a Room's rules text is its two halves' (a locked half has
    none), so the coverage verdict must read both — never just the front, which is all ``oracle_text`` holds."""
    type_line = str(getattr(card, "type_line", "") or "").lower()
    if getattr(card, "layout", "") != "split" or "room" not in type_line.split("—")[-1].split():
        return []
    back = card.back_face() if hasattr(card, "back_face") else None
    if back is None:
        return []
    front = copy.copy(card)
    front.name = str(card.name).split("//")[0].strip()
    front.back_name = front.back_type_line = front.back_oracle_text = front.back_mana_cost_string = ""
    front.keywords = []
    return [front, back]


def _flip_halves(card: Any) -> list[Any]:
    """A Kamigawa flip card's two halves (RULE 710), each as a plain card, or ``[]`` for anything else: the normal
    half (named and typed as printed, with no second face) and the flipped half (`Card.flip_face`, which keeps the
    normal half's mana cost)."""
    flipped = card.flip_face() if hasattr(card, "flip_face") else None
    if flipped is None:
        return []
    front = copy.copy(card)
    front.name = str(card.name).split("//")[0].strip()
    front.layout = ""
    front.back_name = front.back_type_line = front.back_oracle_text = front.back_mana_cost_string = ""
    front.back_keywords = []
    return [front, flipped]


def _merge_flip_halves(front: ParseResult, flipped: ParseResult) -> ParseResult:
    """A flip card is `MODELED` only when both halves are — a flipped half nobody can play would leave the permanent
    half-working — but only the normal half's specs are bound up front: the flipped half's are bound by
    `RulesEngine._flip_permanent` when (and if) the permanent flips, so concatenating both (as for a Room, whose
    doors are all live) would hand an unflipped permanent its flipped half's abilities."""
    if front.never_supported or flipped.never_supported:
        coverage = NEVER_SUPPORTED
    else:
        coverage = MODELED if front.modeled and flipped.modeled else UNMODELED
    return ParseResult(specs=list(front.specs), coverage=coverage, unclaimed=[*front.unclaimed, *flipped.unclaimed])


def _merge_room_halves(results: list[ParseResult]) -> ParseResult:
    """A Room is `MODELED` only when both halves are; the specs are simply concatenated (the
    binder reads each half through `game/rooms.py`, which keeps them apart)."""
    if any(r.never_supported for r in results):
        coverage = NEVER_SUPPORTED
    else:
        coverage = MODELED if all(r.modeled for r in results) else UNMODELED
    return ParseResult(
        specs=[spec for r in results for spec in r.specs],
        coverage=coverage,
        unclaimed=[line for r in results for line in r.unclaimed],
    )


#: PAR-130: trigger events whose firing names the player a "that player"
#: target scope resolves to (`targeting.trigger_player_antecedent`). A
#: ``DAMAGE`` head only counts when its recipient filter is a player.
_THAT_PLAYER_EVENTS: frozenset[str] = frozenset({
    "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER", "ATTACKS", "PLAYER_ATTACKED",
    "BECOMES_TARGET", "STEP_BEGIN",
})
#: The head must name that player itself — the event alone isn't enough ("at
#: the beginning of **your** upkeep" is a `STEP_BEGIN` with no other player).
_THAT_PLAYER_HEAD_RE = re.compile(
    r"\b(?:a player|an opponent|each opponent's|each player's|defending player|"
    r"1 of your opponents|an opponent controls)\b"
)
#: …and the body mustn't name another player first, or "that player" is that
#: one instead (a prior "target opponent", a "for each opponent" iteration).
_THAT_PLAYER_BODY_RIVAL_RE = re.compile(r"\b(?:players?|opponents?)\b")


def _that_player_head_ok(event: str, filt: Any, text: str) -> bool:
    """Whether a trigger (``event`` + recipient ``filt``, printed as ``text``)
    names the player a "that player" in its body refers to."""
    before_that = text.lower().split("that player", 1)[0]
    if re.search(
        r"\btarget (?:opponent|player)\b|\btarget [^.]+? (?:an opponent controls|you don'?t control)\b",
        before_that,
    ):
        return True
    player_damage = event == "DAMAGE" and isinstance(filt, dict) and filt.get("is_player")
    if event not in _THAT_PLAYER_EVENTS and not player_damage:
        return False
    head, sep, body = text.lower().partition(", ")
    if not sep or not _THAT_PLAYER_HEAD_RE.search(head):
        return False
    return not _THAT_PLAYER_BODY_RIVAL_RE.search(body.split("that player", 1)[0])


#: `TargetSpec.per_player`'s vocabulary, mirrored here (no `game/` imports).
_PER_PLAYER_SCOPES = ("opponents", "players", "any_opponents")
#: The context a spell/activated ability's effects are walked under: no trigger
#: head names "that player", but per-player rounds and a prior target can.
_SPELL_CONTEXT: tuple[str, Any, str] = ("PRIOR_TARGET", None, "")


def _that_player_tree_ok(node: Any, context: Optional[tuple[str, Any, str]], text: str) -> bool:
    """Walk a spec tree; every ``…_that_player_controls`` kind must sit under
    a trigger whose head names that player. A granted trigger (a dict with
    ``trigger_event`` — `grant_triggered_ability`) is its own context, read
    against the quoted ability text it was parsed from."""
    if isinstance(node, EffectSpec):
        return _that_player_tree_ok(node.params, context, text)
    if isinstance(node, (list, tuple)):
        return all(_that_player_tree_ok(item, context, text) for item in node)
    if not isinstance(node, dict):
        return True
    if isinstance(node.get("trigger_event"), str):
        quoted = re.search(r'"([^"]*)"', text)
        context = (node["trigger_event"], node.get("filter"), quoted.group(1) if quoted else "")
    for key, val in node.items():
        if key.endswith("kind") and isinstance(val, str) and val.endswith("_that_player_controls"):
            if node.get("per_player") in _PER_PLAYER_SCOPES:
                # "for each opponent/player, …" is its own antecedent, but
                # only a triggered ability or a spell (`targeting.
                # spell_target_rounds`) gathers its targets per round.
                if context is None:
                    return False
            elif context is None or not _that_player_head_ok(*context):
                return False
        elif key == "kinds" and isinstance(val, list) and any(
            isinstance(kind, str) and kind.endswith("_that_player_controls") for kind in val
        ):
            if node.get("per_player") in _PER_PLAYER_SCOPES:
                if context is None:
                    return False
            elif context is None or not _that_player_head_ok(*context):
                return False
        elif not _that_player_tree_ok(val, context, text):
            return False
    return True


def _opponents_batch_ok(spec: AbilitySpec) -> bool:
    """MEC-104: "…deals damage to one or more of your opponents" is one trigger per simultaneous
    batch. The combat aggregate dedupes that itself (`binding.core._contributor_condition`); a
    plain per-hit ``DAMAGE`` trigger cannot, so it is only sound with "this ability triggers
    only once each turn" (Molten Lavamancer) — otherwise fail closed."""
    trigger = spec.trigger or {}
    if spec.ability_kind != "triggered" or not trigger.get("opponents_batch"):
        return True
    return trigger.get("event") != "DAMAGE" or bool(trigger.get("limit"))


def _action_limit_ok(spec: AbilitySpec) -> bool:
    """PAR-135: "Do this only once each turn" limits the action a *trigger* offers (`spec.fold_action_limit` turns
    it into a gated `seq` with a stamp). On any other ability kind, or where no stamp can be placed, nothing
    would honour the marker, so it fails closed rather than silently dropping the limit."""
    if spec.ability_kind != "triggered":
        return not contains_marker(spec.effects, ACTION_ONCE_PER_TURN_MARKER)
    return fold_action_limit(spec.effects, ACTION_ONCE_PER_TURN_MARKER, spec.raw_text or "") is not None


_EXILED_CARDS_COLORS_MANA_RE = re.compile(r"add 1 mana of any of the exiled cards' colou?rs")


_TAP_X_COST_RE = re.compile(r"\btap x untapped\b")


def _tap_x_cost_ok(spec: AbilitySpec) -> bool:
    """RULE 602.2b: admit X-sized tap costs only when the shared cost
    grammar recognizes the entire cost and its TAP_OTHERS_X component."""
    cost = spec.cost if isinstance(spec.cost, dict) else None
    text = str((cost or {}).get("text", "")).lower()
    if not _TAP_X_COST_RE.search(text):
        return True
    scan = scan_cost_text(text)
    tapped = scan.hits.get("tap_others")
    return scan.leftover is None and tapped is not None and tapped.group("n").lower() == "x"


_TRAILING_WINDOW_CONDITION_RE = re.compile(r"\byou may (?:play|cast)\b[^.]*\bif\b", re.IGNORECASE)


def _cast_window_ok(spec: AbilitySpec) -> bool:
    """PAR-167: two ways a casting-window effect could be claimed with the wrong meaning.

    * A trailing "... if <condition>" is peeled off a multi-sentence body and stamped on *every* effect, so an
      exile clause plus its casting window would be gated as a whole ("exile the top card ... you may play it if
      you control a Kavu" exiling only while the Kavu stands). The condition belongs to the window alone, which
      this spec shape cannot express: fail closed.
    * "... with mana value less than or equal to that damage" reads the firing damage event's amount; under any
      other ability kind "that damage" names nothing the cast could measure.
    """
    for effect in spec.effects:
        if effect.type == "cast_window_exiled_pool":
            # PAR-169: a *leading* "if <condition>, exile ... you may play it" gates the exile, so stamping it on
            # the window too is harmless (nothing exiled, nothing to play); only a condition trailing the window
            # sentence belongs to the window alone.
            if effect.condition is not None and _TRAILING_WINDOW_CONDITION_RE.search(spec.raw_text or ""):
                return False
            # RULE 107.3: a trigger has no announced X for this casting cap.
            if (spec.ability_kind == "triggered"
                    and effect.params.get("card_filter", {}).get("max_mana_value") == "x"):
                return False
        amount = effect.params.get("max_mana_value_amount") if effect.type == "free_cast_from_hand" else None
        if isinstance(amount, dict) and amount.get("kind") == "trigger_event" and not (
            spec.ability_kind == "triggered" and (spec.trigger or {}).get("event") == "DAMAGE"
        ):
            return False
    return True


def _dig_x_ok(spec: AbilitySpec) -> bool:
    """A dig's ``x`` count ("look at the top X cards") is the announced {X} of a spell or an activated
    ability. Under a trigger nothing announced an X (the word then means a measured or "where X is"
    amount), so it fails closed instead of reading 0."""
    for effect in spec.effects:
        amount = effect.params.get("count")
        if isinstance(amount, dict) and amount.get("kind") == "counters_removed_as_cost":
            counter = re.escape(str(amount.get("counter", "")))
            cost = str((spec.cost or {}).get("text", ""))
            if spec.ability_kind != "activated" or not re.search(
                rf"\bremove (?:all|\d+|x) {counter} counters? from ~(?:,|$)", cost,
            ):
                return False
    if spec.ability_kind != "triggered":
        return True
    return not any(
        effect.type in ("inspect_top_choose", "look_top_select") and effect.params.get("count") == "x"
        for effect in spec.effects
    )


def _that_player_antecedent_ok(spec: AbilitySpec) -> bool:
    """PAR-130: a ``…_that_player_controls`` target is only sound under a
    trigger head that names that player (RULE 603.2's firing event is what
    `targeting.trigger_player_antecedent` reads), or under a "for each
    opponent/player" or after an earlier player/opponent-controlled target.
    Everything else fails closed rather than resolving against the wrong
    player or none."""
    text = spec.raw_text or ""
    context = (
        (_SPELL_CONTEXT[0], _SPELL_CONTEXT[1], text)
        if spec.ability_kind in ("spell_effect", "activated") else None
    )
    if spec.ability_kind == "triggered" and spec.trigger:
        unquoted = re.sub(r'"[^"]*"', '""', text)
        context = (str(spec.trigger.get("event") or ""), spec.trigger.get("filter"), unquoted)
    return _that_player_tree_ok([spec.effects, spec.modes, spec.target], context, text)


#: Numeric payloads a printed "that much" may safely read from a firing
#: event. Keep this parser-side (no ``game/`` import across the boundary).
#: The first increment deliberately admits only event families whose emitted
#: payload is already the exact referenced quantity; sequence-local values
#: such as "counters removed this way" need their own context operand.
_THAT_MUCH_TRIGGER_FIELDS: dict[str, str] = {
    "DAMAGE": "amount",
    "DISCARD": "count",
    "LIFE_GAINED": "amount",
    "LIFE_LOST": "amount",
    "COUNTER": "amount",
}


def _resolve_that_much_tree(node: Any, field: Optional[str]) -> bool:
    """Resolve the private handler sentinel, or reject an unsafe antecedent."""
    if isinstance(node, EffectSpec):
        return _resolve_that_much_tree(node.params, field)
    if isinstance(node, (list, tuple)):
        return all(_resolve_that_much_tree(item, field) for item in node)
    if not isinstance(node, dict):
        return True
    if node.get("amount_from_trigger_event") == "that_much":
        if field is None:
            return False
        node["amount_from_trigger_event"] = field
    return all(_resolve_that_much_tree(value, field) for value in node.values())


def _that_much_antecedent_ok(spec: AbilitySpec) -> bool:
    event = str((spec.trigger or {}).get("event") or "") if spec.ability_kind == "triggered" else ""
    return _resolve_that_much_tree(
        [spec.effects, spec.modes, spec.target], _THAT_MUCH_TRIGGER_FIELDS.get(event)
    )


def _resolve_event_player_tree(node: Any, event: str) -> bool:
    """PAR-132: strip the private ``event_player_events`` marker, or reject its antecedent.

    A handler that reads the firing event's player under a phrase only some heads can satisfy
    ("that spell or ability's controller" under a becomes-the-target head) lists the events whose
    ``player_id`` is that exact player; anywhere else the clause stays unclaimed.
    """
    if isinstance(node, EffectSpec):
        return _resolve_event_player_tree(node.params, event)
    if isinstance(node, (list, tuple)):
        return all(_resolve_event_player_tree(item, event) for item in node)
    if not isinstance(node, dict):
        return True
    allowed = node.pop(EVENT_PLAYER_EVENTS_KEY, None)
    if allowed is not None and event not in allowed:
        return False
    return all(_resolve_event_player_tree(value, event) for value in node.values())


def _event_player_antecedent_ok(spec: AbilitySpec) -> bool:
    event = str((spec.trigger or {}).get("event") or "") if spec.ability_kind == "triggered" else ""
    return _resolve_event_player_tree([spec.effects, spec.modes, spec.target], event)


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
    # RULE 123.2: sheets may contain only ticket symbols/stats or no text.
    type_line = (getattr(card, "type_line", "") or "").strip().casefold()
    if _mentions_stickers(raw) or type_line == "stickers":
        # Fail-closed the same way as an ordinary UNMODELED card (the
        # binder never sees these specs' effects — there are none), but
        # tagged distinctly and with no `unclaimed` seeds so this card
        # never shows up in the processing-list backlog (see
        # `NEVER_SUPPORTED`'s docstring above).
        return ParseResult(specs=list(keyword_specs), coverage=NEVER_SUPPORTED)
    raw = _expand_ability_word_reminders(raw)
    if _is_spell(card):
        # RULE 608.2c: on an instant or sorcery an "Infusion —"/"Addendum —"
        # paragraph is the same spell ability's next instruction, so "that
        # creature"/"… instead" must see the paragraph before it.
        raw = _SPELL_RIDER_PARAGRAPH_RE.sub(r" \g<rider>", raw)
    normalized = normalize(raw, getattr(card, "name", None), getattr(card, "keywords", None))
    normalized = reordered_fight_text(normalized)
    if not normalized:
        return ParseResult(specs=list(keyword_specs), coverage=MODELED)

    allow_spell_effect = _is_spell(card)
    is_saga = bool(getattr(card, "is_saga", False))
    is_leveler = bool(getattr(card, "is_leveler", False))
    is_class = bool(getattr(card, "is_class", False))
    is_station = bool(getattr(card, "is_station", False))
    effect_specs: list[AbilitySpec] = []
    unclaimed: list[str] = []
    all_claimed = True

    def _process_line(line: str) -> None:
        nonlocal all_claimed
        # PAR-95 / Adamant — Sundering Stroke's rider changes the preceding
        # divided instruction into one full hit per already selected target.
        # It is deliberately one exact form: a general "instead" rewrite
        # would be unsound for target choice and distribution semantics.
        sundering = re.fullmatch(
            r"~ deals (?P<n>\d+) damage divided as you choose among 1, 2, or 3 targets\. "
            r"if at least (?P<threshold>\d+) red mana was spent to cast this spell, instead ~ deals "
            r"(?P<replacement>\d+) damage to each of those permanents and/or players\.?",
            line, re.I,
        )
        if sundering is not None and sundering.group("n") == sundering.group("replacement"):
            effect_specs.append(AbilitySpec("spell_effect", [EffectSpec("damage", {
                "amount": int(sundering.group("n")), "target_kind": "any", "count": 3,
                "count_max": 3, "optional": True, "divided": True,
                "each_target_if_mana_color_spent": {
                    "color": "R", "threshold": int(sundering.group("threshold")),
                },
            })], raw_text=line, parser=provenance))
            return
        # PAR-59 / RULE 702.55: Haunt cards print either the combined ETB +
        # linked-creature-death trigger or the latter alone.  The ordinary
        # ETB half stays a normal battlefield trigger; the death half is a
        # DIES trigger whose wrapper makes `triggers_mixin` scan the exiled
        # haunter linked to that exact dying creature.
        haunt = re.fullmatch(
            r"when ~ enters or the creature it haunts dies,\s*(?P<body>.+)", line, re.I
        )
        haunt_only = re.fullmatch(
            r"when the creature this card haunts dies,\s*(?P<body>.+)", line, re.I
        )
        if haunt is not None or haunt_only is not None:
            body = (haunt or haunt_only).group("body")
            effects = parse_effect_body(body)
            if effects is None:
                all_claimed = False
                unclaimed.append(line)
                return
            if haunt is not None:
                enter = segment_line(
                    "when ~ enters, " + body, allow_spell_effect=allow_spell_effect,
                    provenance=provenance, is_saga=is_saga,
                )
                if not enter.claimed or enter.spec is None:
                    all_claimed = False
                    unclaimed.append(line)
                    return
                effect_specs.append(enter.spec)
            effect_specs.append(AbilitySpec(
                "triggered",
                [EffectSpec("haunt_linked_death", {
                    "effects": [effect.to_dict() for effect in effects],
                })],
                trigger={"event": "DIES"}, raw_text=line, parser=provenance,
            ))
            return
        # PAR-45: an opponent choice and its entry-counter consequence are
        # two independent pre-entry replacements printed on one line.  Split
        # only this fully-known composition; a generic sentence split would
        # incorrectly claim arbitrary unresolved tails.
        opponent_entry = re.fullmatch(
            r"(?P<choice>as ~ enters, choose an opponent)\.\s*(?P<tail>.+)", line, re.I
        )
        # "Flashback {8}{G}{G}. This spell costs {X} less to cast this way, where X is …" (the Visions cycle): the
        # keyword half is `parse_keywords`'s; the sentence about its own cost is a graveyard-gated cost reduction.
        flashback_discount = FLASHBACK_DISCOUNT_LINE_RE.fullmatch(line)
        if flashback_discount is not None:
            line = flashback_discount.group("discount")
        if opponent_entry is not None:
            choice_seg = segment_line(
                opponent_entry.group("choice"), allow_spell_effect=allow_spell_effect,
                provenance=provenance, is_saga=is_saga,
            )
            if not choice_seg.claimed or choice_seg.spec is None:
                all_claimed = False
                unclaimed.append(line)
                return
            effect_specs.append(choice_seg.spec)
            line = opponent_entry.group("tail")
        # PAR-64 / Raid: these are amount replacements for the immediately
        # preceding damage instruction, not independent damage effects. Both
        # printed orders exist (Firecannon Blast / Arrow Storm). Keep the
        # prior target and attach the override to that same effect.
        raid_override = re.fullmatch(
            r"(?:if you attacked this turn, instead )?~ deals (?P<n>\d+) damage"
            r"(?: to that (?:permanent|player)(?: or player)?)?(?P<unpreventable> and the damage can'?t be prevented)?"
            r"(?: instead if you attacked this turn)?\.?",
            line,
            re.I,
        )
        if raid_override is not None and effect_specs:
            previous = effect_specs[-1]
            damages = [effect for effect in previous.effects if effect.type == "damage"]
            if previous.ability_kind == "spell_effect" and len(previous.effects) == len(damages) == 1:
                damages[0].params["amount_if_raid"] = int(raid_override.group("n"))
                if raid_override.group("unpreventable"):
                    damages[0].params["unpreventable"] = True
                return
        # PAR-95 / Adamant's two-line forms.  These riders refer to the
        # immediately preceding spell instruction, so append/modify that
        # same AbilitySpec and retain its target-resolution context instead
        # of creating an independent, incorrectly targeted spell effect.
        adamant = re.fullmatch(
            r"if at least (?P<threshold>\d+) (?P<color>white|blue|black|red|green|colorless) mana was spent "
            r"to cast this spell, (?P<body>.+)\.?,?", line, re.I,
        )
        if adamant is not None and effect_specs:
            previous = effect_specs[-1]
            adamant_body = adamant.group("body").strip().rstrip(".").strip()
            condition = {
                "kind": "mana_color_spent_to_cast_at_least",
                "color": {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G", "colorless": "C"}[
                    adamant.group("color").lower()
                ],
                "amount": int(adamant.group("threshold")),
            }
            # Searing Barrage: a second damage instruction to the controller
            # of the preceding creature target.
            if re.fullmatch(r"~ deals \d+ damage to that creature'?s controller", adamant_body, re.I):
                n = int(re.search(r"\d+", adamant_body).group())
                if previous.ability_kind == "spell_effect":
                    previous.effects.append(EffectSpec("damage", {
                        "amount": n, "recipient_subject": "previous_subject_controller",
                    }, condition=condition))
                    return
            # Slaying Fire: a magnitude replacement, never a second hit.
            override = re.fullmatch(r"it deals (?P<n>\d+) damage instead", adamant_body, re.I)
            if override is not None:
                damages = [effect for effect in previous.effects if effect.type == "damage"]
                if previous.ability_kind == "spell_effect" and len(previous.effects) == len(damages) == 1:
                    damages[0].params["amount_if_mana_color_spent"] = {
                        "color": condition["color"], "threshold": condition["amount"],
                        "amount": int(override.group("n")),
                    }
                    return
            # Outmuscle: its first target remains the referent after the
            # intervening fight has consumed a second target requirement.
            if re.fullmatch(r"the creature you control gains indestructible until end of turn", adamant_body, re.I):
                if previous.ability_kind == "spell_effect" and len(previous.effects) == 2 and previous.effects[-1].type == "fight":
                    previous.effects.append(EffectSpec("pump", {
                        "keywords": ["indestructible"], "target_group_index": 0,
                    }, condition=condition))
                    return
        # MEC-86 / RULE 722.3a: "~ enters prepared." states the permanent
        # gains the prepared designation as it enters — unlike the
        # tapped-entry/counters checks just below, this *is* an effect
        # (`make_prepared`/`BecomePreparedEffect`, already engine-side and
        # effect-spec-driven, not a raw-text battlefield-entry scan), so it
        # synthesizes the equivalent "when ~ enters, it becomes prepared"
        # trigger — the same idiom the Haunt ETB half above uses — rather
        # than teaching `become_prepared` a second, untriggered entry path.
        # `become_prepared`'s own handler already recognizes the synthesized
        # body verbatim ("it becomes prepared").
        enters_prepared = re.fullmatch(
            r"(?:~|this creature|this permanent) enters prepared\.?", line, re.I
        )
        if enters_prepared is not None:
            enter = segment_line(
                "when ~ enters, it becomes prepared", allow_spell_effect=allow_spell_effect,
                provenance=provenance, is_saga=is_saga,
            )
            if not enter.claimed or enter.spec is None:
                all_claimed = False
                unclaimed.append(line)
                return
            effect_specs.append(enter.spec)
            return
        # RULE 614.1 "enters tapped" clauses are covered by the engine's own
        # tapped-entry machinery (`game/card_registry.land_tap_condition`,
        # resolved by `RulesEngine.enter_land_tapped`), not through an effect
        # spec — claim the line without emitting one, the same way a mana
        # ability's "add {g}" is covered-without-spec in the segmenter.
        if tap_clause_condition(line) is not None:
            # A compound tap-land can additionally make a RULE 601.2b
            # characteristic choice as it enters (the Thriving cycle).  The
            # tapped-entry engine consumes the first sentence; continue with
            # the narrowly extracted second one so its enter replacement is
            # bound too.
            choice_tail = tapped_entry_choice_tail(line)
            if choice_tail is None:
                return
            line = choice_tail
        # RULE 614.1-style "enters with N counters" clauses: same split as
        # tapped-entry above — covered by `game/card_registry.
        # entry_counters` (`RulesEngine`'s battlefield-entry resolution),
        # not an effect spec.
        if entry_counters_condition(line) is not None:
            return
        # RULE 702.33b Kicker's own "{X}" payment restriction ("Spend only
        # colored mana on X. No more than one mana of each color may be
        # spent this way.", PAR-7): same split as the two clauses above —
        # covered by `game/card_registry.kicker_x_mana_restriction`
        # (`GameEngine.can_cast`/`cast_spell`), not an effect spec.
        if kicker_x_mana_restriction_condition(line) is not None:
            return
        # RULE 903.3 "~ can be your commander." — a deck-legality permission
        # with no in-game behavioral effect (see `commander_eligibility_line`'s
        # docstring): claim the line, contribute nothing, same split as the
        # two tapped-entry/counter checks above.
        if commander_eligibility_line(line):
            return
        if deck_any_number_line(line):
            return
        # RULE 103.6a "If this card is in your opening hand, you may begin
        # the game with it on the battlefield." (the Leyline cycle) — a
        # pregame setup permission, not an in-game behavioral effect: same
        # split as the three clauses above, covered by `game/
        # card_registry.opening_hand_battlefield_permission`
        # (`services/game_session.py`'s opening-hand handling), not an
        # effect spec.
        if opening_hand_battlefield_permission_line(line):
            return
        # Gemstone Caverns' conditional/costed/counter-bearing sibling of
        # the clause above, and Buried Ogre's graveyard-destination one —
        # same split, covered by `game/card_registry.
        # pregame_setup_permission` instead.
        if opening_hand_battlefield_conditional_permission_line(line):
            return
        if opening_hand_graveyard_permission_line(line):
            return
        seg: Segment = segment_line(
            line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
        )
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
        elif seg.spec is not None:
            effect_specs.append(seg.spec)
            # One printed line can yield 2+ abilities — see
            # `Segment.extra_specs` (RULE 700.2's compact inline modal).
            effect_specs.extend(seg.extra_specs)

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
                # A "*/*" Leveler tier would need a `pt_cda` static (the
                # engine primitive already exists — `game/continuous.py`'s
                # layer-7a pass, shared with e.g. Tarmogoyf) instead of
                # `pt_set`, gated the same `min_level`/`max_level` way. Left
                # unimplemented on purpose, not merely deferred: unlike
                # every other item this module fails closed on, there is no
                # real printed Leveler tier to derive the CDA's actual count
                # selector from (checked against the full ~34k-card Oracle
                # cache — zero matches), so wiring this now would mean
                # *guessing* the selector docs/09's fail-closed discipline
                # exists to prevent. Revisit only if a real card is printed.
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
        header: str, or_both: bool, or_more: bool, repeatable: bool, override: Optional[dict[str, Any]], choose: int, mode_bodies: list[str]
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
                "repeatable": repeatable,
                "override": override,
                "choose": choose,
                "options": options,
                "descriptions": descriptions,
            },
            raw_text=header,
            parser=provenance,
        ))

    def _process_named_choice_block(
        labels: list[str], bodies: dict[str, str], header: str
    ) -> None:
        # "As ~ enters, choose A or B. • A — <ability> • B — <ability>" (Siege cycle): the choice is
        # an as-enters replacement stamping `GameObject.chosen_mode`; each option's ability stays an
        # ordinary bound ability, live only while its own label is the stored choice.
        nonlocal all_claimed
        gated: list[AbilitySpec] = []
        unclaimed_before = len(unclaimed)
        for label in labels:
            seg = segment_line(
                bodies[label], allow_spell_effect=False, provenance=provenance, is_saga=False
            )
            option_specs = (
                [_named_mode_gated(spec, label) for spec in [seg.spec, *seg.extra_specs]]
                if seg.claimed and not seg.keyword_line and seg.spec is not None else [None]
            )
            if any(spec is None for spec in option_specs):
                all_claimed = False
                unclaimed.append(f"• {label} — {bodies[label]}")
                continue
            gated.extend(option_specs)
        if len(unclaimed) > unclaimed_before:
            unclaimed.insert(unclaimed_before, header)
            return
        effect_specs.append(AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_named_mode", {"options": [label.title() for label in labels]})],
            raw_text=header, parser=provenance,
        ))
        effect_specs.extend(gated)

    def _process_spree_block(header: str, mode_costs: list[str], mode_bodies: list[str]) -> None:
        nonlocal all_claimed
        # RULE 702.172a: Spree's own block shape — always "choose one or
        # more" (`at_least=True, choose=1`, the same combinatorial offer
        # Farewell's "choose N or more" already drives via `_modal_cast_
        # actions`), but priced per mode rather than once for the whole
        # spell (`mode_costs`, threaded through `AbilitySpec._validate_
        # modes`/`effect_binder._build_mode_entries` into each mode's own
        # `spell_modes[i]["cost"]`, read by `GameEngine._modal_extra_cost`).
        parsed = _parse_mode_options(mode_bodies)
        if parsed is None:
            all_claimed = False
            unclaimed.append(header)
            unclaimed.extend(f"+ {c} — {b}" for c, b in zip(mode_costs, mode_bodies))
            return
        options, descriptions = parsed
        effect_specs.append(AbilitySpec(
            "spell_effect",
            effects=[],
            modes={
                "at_least": True,
                "choose": 1,
                "options": options,
                "descriptions": descriptions,
                "mode_costs": mode_costs,
            },
            raw_text=header,
            parser=provenance,
        ))

    def _process_triggered_modal_block(
        header: str,
        trigger: dict[str, Any],
        or_both: bool,
        or_more: bool,
        repeatable: bool,
        exhausted: bool,
        override: Optional[dict[str, Any]],
        choose: int,
        mode_bodies: list[str],
    ) -> None:
        nonlocal all_claimed
        # RULE 700.2 wrapped in a RULE 603.1 trigger — e.g. "When ~ enters
        # the battlefield, choose one — • Mode A. • Mode B.": the chosen
        # mode is picked interactively as the ability is put on the stack
        # (`game/rules_engine.py`'s `trigger_mode` choice), not at cast time
        # like a modal spell. `trigger` is the full dict `segment_line`
        # produced for the wrapper (event may be a list, plus any
        # filter/phase_relation/spell_* keys) — the binder's triggered path
        # already spreads it (`effect_binder` ~L1583).
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
            trigger=trigger,
            modes={
                "or_both": or_both,
                "at_least": or_more,
                "repeatable": repeatable,
                "exhaust_per_turn": exhausted,
                "override": override,
                "choose": choose,
                "options": options,
                "descriptions": descriptions,
            },
            raw_text=header,
            parser=provenance,
        ))

    def _process_dice_table_block(
        header: str,
        rows: list[tuple[Optional[int], Optional[int], str]],
    ) -> None:
        """Parse ``header`` as an ordinary ability line, then attach the RULE 706.3a ``outcomes`` table to its
        final ``roll_die`` instruction. Every row body must parse (fail-closed: one unclaimed row leaves the whole
        card UNMODELED), and a row may not announce a target of its own — the roll happens after targets were
        chosen (RULE 601.2c), so only a referent an earlier instruction of the header established is usable."""
        nonlocal all_claimed

        def _fail() -> None:
            nonlocal all_claimed
            all_claimed = False
            unclaimed.append(header)
            unclaimed.extend(f"{lo if lo is not None else ''} | {b}" for lo, _, b in rows)

        seg = segment_line(
            header, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga,
        )
        spec = seg.spec if seg.claimed else None
        if spec is None or not spec.effects or spec.effects[-1].type != "roll_die" or spec.effects[-1].params.get(
                "outcomes"):
            _fail()
            return
        if any(e.type == "add_mana" for row in rows for e in (parse_effect_body(row[2]) or [])):
            # RULE 605.1a/605.3b: a roll that can add mana is a mana ability, which resolves at once without the
            # stack (Jack-in-the-Mox). The table path puts it on the stack, so the card stays unmodeled.
            _fail()
            return
        referent = any(
            any(effect.params.get(key) is not None for key in ("target_kind", "kinds", "target_kinds"))
            or effect.type in ("choose_targets", "exile", "search", "reveal_top")
            for effect in spec.effects[:-1]
        )
        self_referent = spec.ability_kind != "triggered" or (spec.trigger or {}).get("condition") == {"subject": "self"}
        outcomes: list[dict[str, Any]] = []
        roll_again_rows: set[int] = set()
        stripped_rows: list[tuple[Optional[int], Optional[int], str]] = []
        for lo, hi, body in rows:
            again = _DICE_ROLL_AGAIN_TAIL_RE.search(body)
            if again is not None:
                roll_again_rows.add(len(stripped_rows))
                body = body[: again.start()].strip()
            stripped_rows.append((lo, hi, body))
        for index, (lo, hi, body) in enumerate(_expand_of_those_tokens(stripped_rows)):
            # "it" in a row is whatever the header established: a chosen target, else the ability's own source.
            body_specs = parse_effect_body(body) or (
                parse_effect_body(body, reading=ClauseReading(previous_subject=True)) if referent
                else parse_effect_body(body, reading=ClauseReading(self_subject=True)) if self_referent else None
            )
            if body_specs is None or any(_announces_target(s) for s in body_specs):
                _fail()
                return
            row_out: dict[str, Any] = {"effects": [s.to_dict() for s in body_specs]}
            if index in roll_again_rows:
                row_out["roll_again"] = "may"
            if lo is not None:
                row_out["min"] = lo
            if hi is not None:
                row_out["max"] = hi
            outcomes.append(row_out)
        spec.effects[-1].params["outcomes"] = outcomes
        effect_specs.append(spec)

    def _process_reflexive_modal_block(
        header: str, trigger: Optional[dict[str, Any]], cost: str, or_both: bool, or_more: bool,
        repeatable: bool, choose: int, mode_bodies: list[str],
    ) -> None:
        nonlocal all_claimed
        parsed = _parse_mode_options(mode_bodies)
        if parsed is None:
            all_claimed = False
            unclaimed.append(header)
            unclaimed.extend(f"• {body}" for body in mode_bodies)
            return
        options, descriptions = parsed
        payment = EffectSpec("pay_cost_then", {
                "cost": cost,
                "then_trigger_modes": {
                    "or_both": or_both, "at_least": or_more,
                    "repeatable": repeatable, "choose": choose,
                    "options": [[spec.to_dict() for spec in option] for option in options],
                    "descriptions": descriptions,
                },
            })
        effect_specs.append(AbilitySpec(
            "triggered" if trigger is not None else "spell_effect",
            [payment],
            trigger=trigger,
            raw_text=header,
            parser=provenance,
        ))

    def _process_class_body(line: str, level: int) -> None:
        nonlocal all_claimed
        gate = {"min_level": level, "level_counter": "class_level"}
        # RULE 716.4c-adjacent one-shot: "When this Class becomes level N,
        # <effect>." isn't the ordinary "stays active once unlocked" shape
        # every other body line is — checked first since it has its own
        # trigger wrapper the generic per-line dispatch doesn't recognize
        # (`CLASS_BECOMES_LEVEL_RE`'s docstring).
        becomes = CLASS_BECOMES_LEVEL_RE.match(line.strip())
        if becomes is not None:
            n = int(becomes.group("n"))
            if n != level:
                # Printed under a different level's own block than the
                # number it names — not a shape any real card uses; fail
                # closed rather than guess which block "wins".
                all_claimed = False
                unclaimed.append(line)
                return
            body, optional = peel_optional(becomes.group("body"))
            effects = parse_effect_body(body)
            if effects is None:
                all_claimed = False
                unclaimed.append(line)
                return
            spec = AbilitySpec(
                "triggered",
                effects=effects,
                trigger={"event": "CLASS_LEVEL", "chapter": [n]},
                optional=optional,
                raw_text=line,
                parser=provenance,
            )
            _tag_level_gate(spec, gate, default_affects=None)
            return
        seg = segment_line(line, allow_spell_effect=False, provenance=provenance, is_saga=False)
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
            return
        if seg.spec is not None:
            _tag_level_gate(seg.spec, gate, default_affects=None)

    def _process_station_body(line: str, n: int) -> None:
        nonlocal all_claimed
        # RULE 721.2a: cumulative (>= comparison, not a mutually-exclusive
        # tier range the way Leveler's own `min_level`/`max_level` pair is
        # used) — a Station bracket only ever supplies `min_level`, never
        # `max_level`, so reaching a higher threshold doesn't remove a lower
        # one's grant. Reuses the exact same `min_level`/`level_counter`
        # gate mechanism Leveler/Class already established (`continuous.
        # group_selector_objects`/`effect_binder._trigger_condition`, both
        # already generic over which counter kind `level_counter` names —
        # confirmed by reading both consumers rather than assumed), just
        # pointed at ``"charge"`` counters instead of ``"level"``/
        # ``"class_level"``.
        gate = {"min_level": n, "level_counter": "charge"}
        seg = segment_line(line, allow_spell_effect=False, provenance=provenance, is_saga=False)
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
            return
        if seg.keyword_line:
            # A bracket-scoped keyword line ("Flying, deathtouch" under
            # "8+ |") becomes a charge-counter-gated grant, the same
            # `_process_leveler_body` shape.
            effect_specs.append(_grant_keyword_line_spec(line, "self", gate))
            return
        if seg.spec is not None:
            _tag_level_gate(seg.spec, gate, default_affects="self")

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
    elif is_station:
        # RULE 702.184a/721: the reminder line's own real activated ability
        # is bound directly off Scryfall's `keywords: ["Station"]` entry by
        # `effect_binder._station_activated_ability` (mirroring Crew/Saddle,
        # PAR-9/MEC-40's own "recognized but inert" fix) — not emitted here.
        # This branch only needs to split the "N+ |" bracket structure
        # (`split_station_blocks`); the bare "station" word `normalize()`
        # leaves behind, and every other bracket-less line (RULE 721.4
        # allows one both before *and* after the brackets — see `catalogue.
        # station`'s module docstring), flow through the ordinary per-line
        # dispatch below unchanged.
        ordinary, blocks = split_station_blocks(normalized)
        for line in ordinary:
            _process_line(line)
        for n, body in blocks:
            _process_station_body(body, n)
        # RULE 721.2b: "and is a creature with base power/toughness [P/T]"
        # — confirmed against all 30 cached Station cards that this never
        # appears as a per-bracket P/T box in `oracle_text` at all (Scryfall
        # drops it entirely); the only surviving trace is the reminder
        # line's own "It's an artifact creature at N+." sentence, read from
        # **raw** text since `normalize` has already erased it by now (see
        # `catalogue.station.station_creature_threshold`'s docstring). The
        # P/T itself comes from `Card.vehicle_power`/`vehicle_toughness`
        # (RULE 208.1's general "noncreature permanent's own printed P/T"
        # slot, already populated for Station the same way MEC-29 populated
        # it for Vehicle/Crew — `services/scryfall_client.py`), the same
        # `type_change` static shape `effect_binder._crew_activated_ability`
        # uses for "becomes an artifact creature", just standing (charge-
        # counter-gated) instead of "until end of turn".
        creature_n = station_creature_threshold(raw)
        if creature_n is not None:
            type_change_params: dict[str, Any] = {
                "add_types": ["creature"], "affects": "self",
                "min_level": creature_n, "level_counter": "charge",
            }
            vehicle_power = getattr(card, "vehicle_power", None)
            vehicle_toughness = getattr(card, "vehicle_toughness", None)
            if vehicle_power is not None:
                type_change_params["power"] = vehicle_power
            if vehicle_toughness is not None:
                type_change_params["toughness"] = vehicle_toughness
            effect_specs.append(AbilitySpec(
                "static",
                effects=[EffectSpec("type_change", type_change_params)],
                raw_text=f"it's an artifact creature at {creature_n}+",
                parser=provenance,
            ))
    else:
        lines = [line for line in normalized.split("\n") if line.strip()]
        i = 0
        while i < len(lines):
            reflexive_modal = _split_reflexive_modal_block(lines, i)
            if reflexive_modal is not None:
                trigger, cost, or_both, or_more, repeatable, choose, mode_bodies, next_i = reflexive_modal
                _process_reflexive_modal_block(
                    lines[i], trigger, cost, or_both, or_more, repeatable, choose, mode_bodies,
                )
                i = next_i
                continue
            spree_block = split_spree_block(lines, i) if allow_spell_effect else None
            if spree_block is not None:
                mode_costs, mode_bodies, next_i = spree_block
                _process_spree_block(lines[i], mode_costs, mode_bodies)
                i = next_i
                continue
            block = split_modal_block(lines, i) if allow_spell_effect else None
            if block is not None:
                or_both, or_more, repeatable, override, choose, mode_bodies, next_i = block
                _process_modal_block(lines[i], or_both, or_more, repeatable, override, choose, mode_bodies)
                i = next_i
                continue
            named_choice = split_named_choice_block(lines, i)
            if named_choice is not None:
                nc_labels, nc_bodies, next_i = named_choice
                _process_named_choice_block(nc_labels, nc_bodies, lines[i])
                i = next_i
                continue
            trig_block = _split_triggered_modal_block(lines, i, provenance)
            if trig_block is not None:
                triggers, or_both, or_more, repeatable, exhausted, override, choose, mode_bodies, next_i = trig_block
                for trigger in triggers:
                    _process_triggered_modal_block(
                        lines[i], trigger, or_both, or_more, repeatable, exhausted, override, choose, mode_bodies
                    )
                i = next_i
                continue
            dice_table = _split_dice_table_block(lines, i)
            if dice_table is not None:
                dt_header, dt_rows, next_i = dice_table
                _process_dice_table_block(dt_header, dt_rows)
                i = next_i
                continue
            _process_line(lines[i])
            i += 1

    # PAR-30 "Threaten … tails residue" — old two-sentence O-Ring linkage.
    # Modern templating ("exile X until ~ leaves the battlefield.") sets
    # ``remember`` on the exile at parse time; the old cycle prints the
    # return as its own separate "When ~ leaves the battlefield, return the
    # exiled card…" line (`_return_exiled_card` → `return_linked_exile`).
    # That effect reads `GameObject.linked_exile_id`, which only an
    # ``ExileEffect(remember=True)`` populates — so, seeing both halves on
    # one card, stamp ``remember`` onto the companion ETB exile here.
    nodes = list(_effect_nodes(effect_specs))
    if any(kind == "return_all_exiled_with" for kind, _ in nodes):
        for kind, params in nodes:
            if kind in {"exile", "exile_top_of_library", "search"}:
                params["track_exiled_with"] = True
    if any(kind == "return_linked_exile" for kind, _ in nodes):
        for kind, params in nodes:
            if kind == "exile" and not params.get("selector"):
                params["remember"] = True

    # Linkage also survives a conditional/composite wrapper around either
    # half (Promise of Tomorrow), rather than depending on a flat body.
    if _EXILED_CARDS_COLORS_MANA_RE.search(normalized):
        for kind, params in nodes:
            if kind == "exile" and str(params.get("target_kind", "")).startswith("any_graveyard"):
                params["remember"] = True

    for spec in effect_specs:
        # RULE 701.23a: "a card named Avarax" is a literal named quality,
        # even though normalization folded the printing's name to "~".
        # Resolve it while that printing is known, before copied abilities
        # or name-changing effects can alter their live source.
        for kind, params in _effect_nodes([spec.effects, spec.modes]):
            if kind == "search" and isinstance(params.get("criteria"), dict) and params["criteria"].get("name") == "~":
                params["criteria"] = {**params["criteria"], "name": str(card.name).split("//")[0].strip()}
        if not _that_player_antecedent_ok(spec):
            all_claimed = False
            unclaimed.append(spec.raw_text)
        if not _that_much_antecedent_ok(spec):
            all_claimed = False
            unclaimed.append(spec.raw_text)
        if not _event_player_antecedent_ok(spec):
            all_claimed = False
            unclaimed.append(spec.raw_text)
        if not _opponents_batch_ok(spec):
            all_claimed = False
            unclaimed.append(spec.raw_text)
        if not _action_limit_ok(spec):
            all_claimed = False
            unclaimed.append(spec.raw_text)
        if not _dig_x_ok(spec) or not _tap_x_cost_ok(spec) or not _cast_window_ok(spec):
            all_claimed = False
            unclaimed.append(spec.raw_text)

    # BUG-1: an attach keyword whose cost the parser could not carry binds no ability (`_keyword_activated_ability` refuses a cost-less
    # equip), so the card would be MODELED with its equip silently missing. Keep the claim and the binder in agreement.
    for kw_spec in keyword_specs:
        kw = kw_spec.keyword or {}
        # Scryfall lists a DFC's keywords across both faces; only a keyword printed on this face's own text must bind.
        if kw.get("name") in _ATTACH_KEYWORDS and not kw.get("cost") and re.search(
            rf"\b{kw['name']}\b", raw, re.IGNORECASE
        ):
            all_claimed = False
            unclaimed.append(kw_spec.raw_text)
        # RULE 702.185a: Warp cannot work without the complete alternative
        # cost. Do not claim an unsupported native cost as a bare keyword.
        if kw.get("name") == "warp" and not kw.get("cost") and re.search(
            r"^warp\b", raw, re.IGNORECASE | re.MULTILINE
        ):
            all_claimed = False
            unclaimed.append(kw_spec.raw_text)

    _restore_printed_token_names(effect_specs, raw)
    return ParseResult(
        specs=list(keyword_specs) + effect_specs,
        coverage=MODELED if all_claimed else UNMODELED,
        unclaimed=unclaimed,
    )


def unclaimed_spans(card: Any, result: ParseResult) -> list[UnclaimedSpan]:
    """PAR-175 M5: the minimal blocking part of each unclaimed line of ``result`` (report only).

    Lazy on purpose: it re-segments each failed line minus one part, which costs about 40% on top of a
    full-cache parse, so only reports (`processing_list`, `parser_probe rank`) ask for it. It never changes
    ``result``: the line stays unclaimed and the card `UNMODELED`. Lines are probed with the card's
    spell/saga context, so a Leveler/Class/Station body line may fall back to the whole line.
    """
    provenance = ParserProvenance(version=PARSER_VERSION, source="rule:oracle")
    spell = _is_spell(card)
    saga = bool(getattr(card, "is_saga", False))

    def claims(text: str) -> bool:
        return segment_line(text, allow_spell_effect=spell, provenance=provenance, is_saga=saga).claimed

    return [UnclaimedSpan(line, minimal_unclaimed_span(line, claims)) for line in result.unclaimed]
