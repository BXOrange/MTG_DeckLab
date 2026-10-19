#!/usr/bin/env python3
"""Segment the still-UNMODELED **Commander-legal** card pool by *why* each card
fails the coverage gate, and emit a ticket-shaped worklist.

`scripts/coverage_report.py --commander-legal-only` already sizes the
Commander-legal slice and ranks the backlog *templates*. What it does not do is
say, per card, which **kind** of gap is in the way — a modal/Saga wrapper that
fail-closes over otherwise-claimable bodies, a recurring effect-body template
that wants one parser handler, a set-specific keyword mechanic, a genuine
missing engine primitive, or a true one-of that only hand-authoring will close.
That segmentation is the input to the PAR-*/MEC-* ticket pipeline in
`docs/implementation-state/BACKLOG.md` (method: `PARSER_LONG_TAIL.md`).

Buckets (each UNMODELED Commander-legal card lands in exactly one, tested in
this order):

  F  non-goals — RULE 123 Stickers by type/text, Attractions and Conspiracy
     draft mechanics. Excluded from actionable work, with raw coverage totals
     preserved (report-only non-goals are counted separately).
  A  block-wrapper / re-measure — every unclaimed clause is either a
     modal/Spree/Leveler *wrapper header* or a mode body that DOES claim on
     its own (`segment_line`). The card is one segmenter/wrapper fix or one
     sibling-clause ticket away; no ticket of its own.
  D  primitive-blocked — an unclaimed clause matches a known missing-engine-
     primitive signature. -> MEC-* (primitive + handler + PARSER_VERSION
     bump in one batch). NOTE: these labels name the *gap*, not a ticket -
     file a fresh MEC-* when starting one (see BACKLOG.md's MEC section).
  C  set-specific parser residue — an unclaimed clause mentions a set
     mechanic (Party, Rebel/Mercenary, Ki/Spirit-or-Arcane, ...). -> PAR-*,
     worked deck-first; this does not imply its runtime is absent.
  B  recurring template — some unclaimed template blocks >= --min-cluster
     Commander-legal cards. -> PAR-* (one ticket per template cluster),
     `extend-parser` loop.
  E  remaining rare clauses, diagnosed by shared trigger/cost head, effect
     body and repairable modifier axes. Rarity alone does not imply bespoke
     behavior or justify hand-authoring.

READ-ONLY. Never writes `coverage.db` — that is `coverage_report.py`'s job.

Usage (from backend/, venv active):
  python scripts/commander_tail_report.py [--min-cluster 5] [--samples 5]
      [--top-b 60] [--json OUT] [--card-db PATH] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mtg_analyzer.game.card_registry import is_registered  # noqa: E402
from mtg_analyzer.parser.oracle import (  # noqa: E402
    NEVER_SUPPORTED,
    PARSER_VERSION,
    abstract_clause,
    parse_oracle,
)
from mtg_analyzer.parser.oracle.normalize import normalize  # noqa: E402
from mtg_analyzer.parser.oracle.segmenter import segment_line  # noqa: E402
from mtg_analyzer.parser.oracle.spec import ParserProvenance  # noqa: E402
from mtg_analyzer.parser.composition_diagnostics import CompositionProbe  # noqa: E402
from mtg_analyzer.services.coverage_db import commander_legal_names as cov_commander_legal_names  # noqa: E402
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH  # noqa: E402
from mtg_analyzer.services.raw_card_store import RawCardStore  # noqa: E402

_PROV = ParserProvenance(version=PARSER_VERSION, source="commander_tail_report")

# --- bucket signatures -----------------------------------------------------

#: Abstracted templates that are pure block *wrappers* (docs/09: the gate
#: fail-closes a whole modal/Spree/Leveler block and appends every mode body
#: to `unclaimed`, so the header is a proxy for "some sibling clause failed").
#: Deliberately strict — `^choose <n> —` / `^choose <n>.` only, NOT
#: `choose <n> target …` / `choose <n> permanents …`, which are ordinary
#: spell effects that select N things, not modal headers.
_WRAPPER_TEMPLATE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^choose <n>(?: or (?:both|more))? —$"),   # RULE 700.2 modal header
    re.compile(r"^choose <n>\. "),                         # "Choose N. <rider sentence>" (Confluence / kicked-override)
    re.compile(r"^(?:when|whenever|at)\b[^—]*,\s*choose <n>"
               r"(?: that hasn't been chosen[^—]*)? —$"),  # triggered-modal header
    re.compile(r"^spree$"),
)

#: A unclaimed clause that begins with one of these is a modal mode *body*
#: the gate prefixed while fail-closing its block (gate.py `f"• {b}"` /
#: `f"+ {c} — {b}"`). Strip the prefix, then classify the body by its content.
_MODE_BODY_PREFIX_RE = re.compile(r"^(?:•\s+|\+\s+.*?\s+—\s+)")

#: Known *absent* runtime signatures only. PAR-146 rechecked all 18 former
#: entries against live primitives: dice, exchange, meld, Haunt-era damage
#: tracking, suspect, incubate, etc. already exist. Residual grammar mentioning
#: those actions belongs in B/E, never in a fabricated MEC queue. Add a row
#: only after establishing that an actual runtime primitive is absent.
_PRIMITIVE_GAP_SIGNATURES: dict[str, re.Pattern[str]] = {}

#: Report-only permanent non-goals (DEFERRED.md). Unlike parser
#: NEVER_SUPPORTED, these do not change raw coverage totals/denominators.
_REPORT_NON_GOAL_SIGNATURES = {
    "Attractions (RULE 717; permanent non-goal)":
        re.compile(r"\bopen an attraction\b|\ban attraction\b", re.I),
    "Conspiracy draft-matters (permanent non-goal)":
        re.compile(r"draft this card face up|reveal the top card of your draft", re.I),
}

#: Set-specific keyword mechanics the PARSER_LONG_TAIL.md "Two tracks" table
#: identifies as set-specific -> Bucket C (PAR-*, deck-first). These are
#: parser-residue tags, not claims that a named mechanic is unimplemented.
#: NOTE: labels deliberately carry no ticket-id guess. A card landing in one
#: of these buckets does not mean the named mechanic is unshipped — Party and
#: Ki-counter/Spirit-or-Arcane both already have closed tickets, and the
#: residue tagged here is a *different*, more general gap that happens to
#: co-occur with the keyword. Ticket ids are assigned live in BACKLOG.md when
#: a cluster's real cause is actually traced (`parser_probe.py card`); do not
#: hardcode one here, it will drift the moment BACKLOG.md's numbering moves on
#: (see BACKLOG.md's PAR-31…53 ticket-id note for the drift this caused once).
_SET_SPECIFIC_SIGNATURES: dict[str, re.Pattern[str]] = {
    "Doctor's companion (Doctor Who)":
        re.compile(r"doctor's companion", re.I),
    "Party (Zendikar Rising)":
        re.compile(r"\b(?:creature|creatures) in your party\b|\bfull party\b", re.I),
    "Rebel / Mercenary recruiters (Mercadian Masques)":
        re.compile(r"\b(?:rebel|mercenary) permanent card\b", re.I),
    "Ki counter / Spirit-or-Arcane (Kamigawa)":
        re.compile(r"\bki counter\b|\bspirit or arcane spell\b", re.I),
    "Prepared / 'enters prepared'":
        re.compile(r"\benters prepared\b", re.I),
    "'storied' — investigate":
        re.compile(r"^storied\b|\bstoried\b", re.I),
}


# --- classification ------------------------------------------------------------


def _strip_mode_prefix(clause: str) -> str:
    return _MODE_BODY_PREFIX_RE.sub("", clause, count=1).strip()


def _is_wrapper_template(template: str) -> bool:
    return any(rx.search(template) for rx in _WRAPPER_TEMPLATE_RES)


def _claims_alone(body: str, card) -> bool:
    """True if the segmenter (the same path the gate uses for a spell-effect
    line) claims every line of `body` on its own — i.e. `body` is not itself a
    real gap; the block just fail-closed around it for a wrapper/segmenter
    reason. Uses `segment_line`, not the stricter `match_clause` table, so a
    trailing period or a keyword line doesn't read as a false gap."""
    norm = normalize(body, getattr(card, "name", "") or "", getattr(card, "keywords", None) or [])
    lines = [ln for ln in norm.split("\n") if ln.strip()]
    if not lines:
        return False
    return all(
        segment_line(line, allow_spell_effect=True, provenance=_PROV).claimed
        for line in lines
    )


def analyse_card(card, unclaimed: list[str], coverage: str):
    """One-time per-card breakdown. Returns (real_gap_templates, gap_raw_clauses,
    is_bucket_A). A *real gap* clause is one that, after stripping any mode-body
    bullet, is neither a wrapper header nor claimed stand-alone."""
    if coverage == NEVER_SUPPORTED:
        return [], [], False

    real_templates: list[str] = []
    real_raw: list[str] = []
    for clause in (c.strip() for c in unclaimed if c.strip()):
        body = _strip_mode_prefix(clause)
        tmpl = abstract_clause(body)
        if _is_wrapper_template(tmpl):
            continue
        if body != clause and _claims_alone(body, card):
            continue  # a modal mode body that a handler already models
        real_templates.append(tmpl)
        real_raw.append(body.lower())
    is_a = not real_templates and bool(unclaimed)
    return real_templates, real_raw, is_a


def _match_signature(clauses: list[str], table: dict[str, re.Pattern[str]]) -> str | None:
    for clause in clauses:
        for label, rx in table.items():
            if rx.search(clause):
                return label
    return None


def classify(real_templates: list[str], real_raw: list[str], is_a: bool,
             coverage: str, template_freq: Counter[str], min_cluster: int,
             type_line: str = "") -> tuple[str, str]:
    """Return (bucket_letter, detail) from a card's `analyse_card` breakdown."""
    if coverage == NEVER_SUPPORTED or type_line.strip().casefold() == "stickers":
        return "F", "permanent product exclusion"
    non_goal = _match_signature(real_raw, _REPORT_NON_GOAL_SIGNATURES)
    if non_goal:
        return "F", non_goal
    if is_a:
        return "A", "wrapper/segmenter fail-close over otherwise-claimed bodies"
    if not real_templates:
        return "E", "no unclaimed clause recorded"

    hit = _match_signature(real_raw, _PRIMITIVE_GAP_SIGNATURES)
    if hit:
        return "D", hit
    hit = _match_signature(real_raw, _SET_SPECIFIC_SIGNATURES)
    if hit:
        return "C", hit

    best_tmpl, best_n = None, 0
    for tmpl in real_templates:
        n = template_freq.get(tmpl, 0)
        if n > best_n:
            best_tmpl, best_n = tmpl, n
    if best_tmpl is not None and best_n >= min_cluster:
        return "B", best_tmpl

    rarest = min(real_templates, key=lambda t: template_freq.get(t, 0))
    return "E", rarest


# --- aggregation / driver ----------------------------------------------------


def build_report(cards, min_cluster: int = 5) -> dict:
    """Pure report over supplied Commander-legal cards; never touches a ledger."""
    cards = list(cards)
    covered = 0
    never_supported = 0
    breakdowns = []
    template_freq: Counter[str] = Counter()
    for card in cards:
        name = getattr(card, "name", "") or ""
        result = parse_oracle(card)
        # RULE 123.2: Sticker inserts are not playable cards, even when their
        # empty/ordinary text would otherwise parse or a name is registered.
        sticker = (getattr(card, "type_line", "") or "").strip().casefold() == "stickers"
        coverage = NEVER_SUPPORTED if sticker else result.coverage
        if coverage != NEVER_SUPPORTED and (result.modeled or is_registered(name)):
            covered += 1
            continue
        never_supported += int(coverage == NEVER_SUPPORTED)
        clauses = [] if coverage == NEVER_SUPPORTED else list(result.unclaimed)
        templates, raw, is_a = analyse_card(card, clauses, coverage)
        breakdowns.append((name, templates, raw, is_a, coverage, getattr(card, "type_line", "") or ""))
        template_freq.update(set(templates))

    bucket_names: dict[str, list[str]] = defaultdict(list)
    clusters = {letter: defaultdict(list) for letter in "BCD"}
    e_rows = []
    excluded_reasons: dict[str, list[str]] = defaultdict(list)
    axes = defaultdict(lambda: {"clauses": set(), "cards": set(), "examples": set()})
    modifiers = defaultdict(lambda: {"clauses": set(), "cards": set(), "examples": set()})
    probe = CompositionProbe(_PROV)
    for name, templates, raw, is_a, coverage, type_line in breakdowns:
        bucket, detail = classify(templates, raw, is_a, coverage, template_freq, min_cluster, type_line)
        bucket_names[bucket].append(name)
        if bucket in clusters:
            clusters[bucket][detail].append(name)
        elif bucket == "F":
            excluded_reasons[detail].append(name)
        elif bucket == "E":
            card_axes = set()
            for clause in raw:
                diagnosis = probe.split(clause)
                if diagnosis is None:
                    axis = "other/static/non-split"
                else:
                    kind, _head, body, head_ok, body_ok = diagnosis
                    axis = f"{kind} H{'+' if head_ok else '-'}B{'+' if body_ok else '-'}"
                    if kind == "trigger" and head_ok and not body_ok:
                        for modifier, sentence, _shorter in probe.modifier_repairs(body):
                            slot = modifiers[modifier]
                            slot["clauses"].add(sentence)
                            slot["cards"].add(name)
                            slot["examples"].add(sentence)
                slot = axes[axis]
                slot["clauses"].add(clause)
                slot["cards"].add(name)
                slot["examples"].add(clause)
                card_axes.add(axis)
            if not raw:
                axis = "no recorded clause"
                axes[axis]["cards"].add(name)
                card_axes.add(axis)
            e_rows.append({"card": name, "template": detail, "axes": sorted(card_axes)})

    def ranked(table, key):
        return [{key: label, "cards": sorted(names)}
                for label, names in sorted(table.items(), key=lambda kv: (-len(kv[1]), kv[0]))]

    def diagnostic_rows(table):
        return [{"axis": label, "clause_count": len(info["clauses"]),
                 "cards": sorted(info["cards"]), "examples": sorted(info["examples"])[:5]}
                for label, info in sorted(table.items(), key=lambda kv: (-len(kv[1]["cards"]), kv[0]))]

    total = len(cards)
    return {
        "parser_version": PARSER_VERSION,
        "totals": {"commander_legal": total, "covered": covered,
                   "unmodeled": total - covered - never_supported,
                   "never_supported": never_supported,
                   "report_only_non_goals": len(bucket_names["F"]) - never_supported,
                   "fraction": round(covered / total if total else 1.0, 4)},
        "buckets": {"A": sorted(bucket_names["A"]),
                    "B": ranked(clusters["B"], "template"),
                    "C": ranked(clusters["C"], "mechanic"),
                    "D": ranked(clusters["D"], "cluster"),
                    "E": sorted(e_rows, key=lambda row: row["card"]),
                    "F": sorted(bucket_names["F"])},
        "excluded_reasons": ranked(excluded_reasons, "reason"),
        "E_axes": diagnostic_rows(axes),
        "E_modifier_axes": diagnostic_rows(modifiers),
    }


def print_report(payload: dict, samples: int = 5, top_b: int = 60, min_cluster: int = 5) -> None:
    totals, buckets = payload["totals"], payload["buckets"]
    print(f"\nCommander-legal tail report — PARSER_VERSION {payload['parser_version']}")
    print(f"  commander-legal: {totals['commander_legal']}   covered: {totals['covered']} "
          f"({totals['fraction']:.1%})   UNMODELED: {totals['unmodeled']}   "
          f"never-supported: {totals['never_supported']}")
    print(f"  Report-only non-goals: {totals['report_only_non_goals']} "
          "(raw coverage totals unchanged)")
    labels = {"A": "block-wrapper / re-measure", "B": "recurring template -> PAR-*",
              "C": "set-mechanic parser residue -> PAR-*", "D": "absent runtime primitive -> MEC-*",
              "E": "composition/rare-clause diagnostics", "F": "non-goals / never-supported (no work ticket)"}
    print("\nBucket histogram (one outer bucket per uncovered card):")
    for letter in "ABCDEF":
        rows = buckets[letter]
        count = sum(len(row["cards"]) for row in rows) if letter in "BCD" else len(rows)
        print(f"  {letter}  {labels[letter]:<48s} {count:6d}")

    for letter, key in (("D", "cluster"), ("C", "mechanic"), ("B", "template")):
        print(f"\n─── Bucket {letter} — {labels[letter]} ───")
        rows = buckets[letter][:top_b] if letter == "B" else buckets[letter]
        for row in rows:
            print(f"  N={len(row['cards']):<4d} {row[key]}")
            print(f"           e.g. {', '.join(row['cards'][:samples])}")

    print("\n─── Bucket F — excluded worklist families ───")
    for row in payload["excluded_reasons"]:
        print(f"  N={len(row['cards']):<4d} {row['reason']}")
        print(f"           e.g. {', '.join(row['cards'][:samples])}")

    print("\n─── Bucket E — head/body axes (overlapping card sets; not additive) ───")
    print("  H/B: head/body claims under a known-good partner; H+B+ is a composition gap.")
    for row in payload["E_axes"]:
        print(f"  {row['axis']:<28s} {row['clause_count']:5d} clauses  {len(row['cards']):5d} cards")
        print(f"           e.g. {', '.join(row['cards'][:samples])}")
    print("\n─── Bucket E — single-modifier deletions that repair failing trigger-body sentences ───")
    print("  Diagnostic candidates, not behavior claims; card sets overlap.")
    for row in payload["E_modifier_axes"]:
        print(f"  {row['axis']:<46s} {row['clause_count']:5d} sentences  {len(row['cards']):5d} cards")
        print(f"           e.g. {', '.join(row['cards'][:samples])}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-cluster", type=int, default=5)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--top-b", type=int, default=60)
    ap.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    cards = CardDatabase(args.card_db).list_cards()
    if args.limit is not None:
        cards = cards[:args.limit]
    with RawCardStore() as raw_store:
        legal_names = cov_commander_legal_names(raw_store)
    payload = build_report([card for card in cards if card.name in legal_names], args.min_cluster)
    print_report(payload, args.samples, args.top_b, args.min_cluster)
    if args.json:
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote JSON breakdown to {args.json}")


if __name__ == "__main__":
    main()
