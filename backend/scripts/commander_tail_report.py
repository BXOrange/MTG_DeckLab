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
`docs/implementation-state/BACKLOG.md` (see
`.claude/plans/*commander*` / `PARSER_LONG_TAIL.md`).

Buckets (each UNMODELED Commander-legal card lands in exactly one, tested in
this order):

  F  never-supported  — RULE 123 Stickers &c. Out of the denominator.
  A  block-wrapper / re-measure — every unclaimed clause is either a
     modal/Spree/Leveler *wrapper header* or a mode body that DOES claim on
     its own (`match_clause`). The card is one segmenter/wrapper fix or one
     sibling-clause ticket away; no ticket of its own.
  D  primitive-blocked — an unclaimed clause matches a known missing-engine-
     primitive signature (the PAR-30 clusters + Licid + the damage-source
     tracker). -> MEC-* (primitive + handler + PARSER_VERSION bump in one batch).
  C  set-specific mechanic — an unclaimed clause names a keyword mechanic the
     `PARSER_LONG_TAIL.md` "Two tracks" table lists as Not done (Doctor's
     companion, Party, Rebel/Mercenary, Ki/Spirit-or-Arcane, ...). -> PAR-*,
     worked deck-first.
  B  recurring template — some unclaimed template blocks >= --min-cluster
     Commander-legal cards. -> PAR-* (one ticket per template cluster),
     `extend-parser` loop.
  E  bespoke tail — the rest: only rare templates, no primitive gap, no
     near-miss handler. -> PAR-* hand-authoring batches / the PAR-12 pointer.

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

from mtg_analyzer.game.ability_catalogue import is_registered  # noqa: E402
from mtg_analyzer.parser.oracle import (  # noqa: E402
    NEVER_SUPPORTED,
    PARSER_VERSION,
    abstract_clause,
    parse_oracle,
)
from mtg_analyzer.parser.oracle.normalize import normalize  # noqa: E402
from mtg_analyzer.parser.oracle.segmenter import segment_line  # noqa: E402
from mtg_analyzer.parser.oracle.spec import ParserProvenance  # noqa: E402
from mtg_analyzer.services import coverage_db as cov  # noqa: E402
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

#: Known missing-engine-primitive signatures -> Bucket D (MEC-*). Matched
#: case-insensitively against the RAW unclaimed clause (keeps `~`, `{2}`, digits).
#: The PAR-30 clusters that BACKLOG.md already enumerates, plus the two new
#: ones this plan adds (Licid, the per-turn damage-source tracker).
_PRIMITIVE_GAP_SIGNATURES: dict[str, re.Pattern[str]] = {
    "Licid — creature becomes an Aura (MEC-47)":
        re.compile(r"loses this ability and becomes an aura enchantment", re.I),
    "Specialize (Duskmourn) (MEC-48)":
        re.compile(r"\bspecial(?:ize|izes|ized)\b", re.I),
    "damage-source-this-turn tracker (MEC-49)":
        re.compile(r"dealt damage by ~ this turn\b", re.I),
    "PAR-30: Waterbend residue":
        re.compile(r"\bwaterbend(?:s|ing)?\b", re.I),
    "PAR-30: bending-verb trigger":
        re.compile(r"whenever you (?:waterbend|earthbend|firebend|airbend)", re.I),
    "PAR-30: Clash win-branch":
        re.compile(r"\bclash(?:es|ed)?\b", re.I),
    "PAR-30: Suspect one-offs":
        re.compile(r"\bsuspect(?:ed|s)?\b", re.I),
    "PAR-30: Incubate primitives":
        re.compile(r"\bincubate[sd]?\b", re.I),
    "PAR-30: Collect Evidence / Forage / Behold bodies":
        re.compile(r"\bcollect evidence\b|\bforage[sd]?\b|\bbehold[s]?\b", re.I),
    "PAR-30: Face a Villainous Choice residue":
        re.compile(r"villainous choice|face a villainous", re.I),
    "PAR-30: Exchange control / life totals":
        re.compile(r"\bexchange control of\b|exchange the control|exchange life totals|"
                   r"exchange (?:your |)life totals", re.I),
    "PAR-30: tapped-and-attacking put-from-zone residue":
        re.compile(r"tapped and attacking", re.I),
}

#: Set-specific keyword mechanics the PARSER_LONG_TAIL.md "Two tracks" table
#: lists as Not done -> Bucket C (PAR-*, deck-first). Value is (label, regex).
_SET_SPECIFIC_SIGNATURES: dict[str, re.Pattern[str]] = {
    "Doctor's companion (Doctor Who) (PAR-49)":
        re.compile(r"doctor's companion", re.I),
    "Party (Zendikar Rising) (PAR-50)":
        re.compile(r"\b(?:creature|creatures) in your party\b|\bfull party\b", re.I),
    "Rebel / Mercenary recruiters (Mercadian Masques) (PAR-51)":
        re.compile(r"\b(?:rebel|mercenary) permanent card\b", re.I),
    "Ki counter / Spirit-or-Arcane (Kamigawa) (PAR-52)":
        re.compile(r"\bki counter\b|\bspirit or arcane spell\b", re.I),
    "Prepared / 'enters prepared' (PAR-53)":
        re.compile(r"\benters prepared\b", re.I),
    "'storied' (PAR-53 — investigate)":
        re.compile(r"^storied\b|\bstoried\b", re.I),
    "Conspiracy draft-matters (non-goal candidate)":
        re.compile(r"draft this card face up|reveal the top card of your draft", re.I),
    "Attractions (RULE 717 — permanent non-goal)":
        re.compile(r"\bopen an attraction\b|\ban attraction\b", re.I),
    "Horsemanship (dead pool)":
        re.compile(r"\bhorsemanship\b", re.I),
    "Banding (dead pool)":
        re.compile(r"\bbands? with other\b|\bbanding\b", re.I),
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
             coverage: str, template_freq: Counter[str], min_cluster: int) -> tuple[str, str]:
    """Return (bucket_letter, detail) from a card's `analyse_card` breakdown."""
    if coverage == NEVER_SUPPORTED:
        return "F", "never-supported (RULE 123)"
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


# --- driver ------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-cluster", type=int, default=5,
                    help="Bucket B threshold: a template must block >= this many "
                         "Commander-legal cards to seed a PAR-* ticket (default 5)")
    ap.add_argument("--samples", type=int, default=5, help="example card names per cluster")
    ap.add_argument("--top-b", type=int, default=60, help="how many Bucket B clusters to print")
    ap.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)
    ap.add_argument("--limit", type=int, default=None, help="only the first N cached cards (quick test)")
    ap.add_argument("--json", type=Path, default=None, help="also write the full breakdown as JSON here")
    args = ap.parse_args()

    cards = CardDatabase(args.card_db).list_cards()
    if args.limit is not None:
        cards = cards[: args.limit]

    with RawCardStore() as raw_store:
        legal_names = cov.commander_legal_names(raw_store)
    cards = [c for c in cards if getattr(c, "name", None) in legal_names]

    # Pass 1: parse + per-card breakdown; tally real-gap template frequency
    # (deduped per card) over all Commander-legal UNMODELED cards.
    total = len(cards)
    covered = 0
    breakdowns: list[tuple[str, list[str], list[str], bool, str]] = []
    template_freq: Counter[str] = Counter()
    for card in cards:
        name = getattr(card, "name", "") or ""
        result = parse_oracle(card)
        if result.coverage != NEVER_SUPPORTED and (result.modeled or is_registered(name)):
            covered += 1
            continue
        clauses = [] if result.coverage == NEVER_SUPPORTED else list(result.unclaimed)
        real_templates, real_raw, is_a = analyse_card(card, clauses, result.coverage)
        breakdowns.append((name, real_templates, real_raw, is_a, result.coverage))
        for tmpl in set(real_templates):
            template_freq[tmpl] += 1

    # Pass 2: classify from the stored breakdowns.
    bucket_names: dict[str, list[str]] = defaultdict(list)
    b_clusters: dict[str, list[str]] = defaultdict(list)
    c_clusters: dict[str, list[str]] = defaultdict(list)
    d_clusters: dict[str, list[str]] = defaultdict(list)
    e_rows: list[tuple[str, str]] = []
    for name, real_templates, real_raw, is_a, coverage in breakdowns:
        bucket, detail = classify(real_templates, real_raw, is_a, coverage,
                                  template_freq, args.min_cluster)
        bucket_names[bucket].append(name)
        if bucket == "B":
            b_clusters[detail].append(name)
        elif bucket == "C":
            c_clusters[detail].append(name)
        elif bucket == "D":
            d_clusters[detail].append(name)
        elif bucket == "E":
            e_rows.append((name, detail))

    never_supported = len(bucket_names["F"])
    frac = covered / total if total else 1.0

    # --- report ---
    print(f"\nCommander-legal tail report — PARSER_VERSION {cov.PARSER_VERSION}")
    print(f"  commander-legal: {total}   covered: {covered} ({frac:.1%})   "
          f"UNMODELED: {total - covered - never_supported}   never-supported: {never_supported}")
    print(f"\nBucket histogram (UNMODELED Commander-legal cards by cause):")
    _LABELS = {
        "A": "block-wrapper / re-measure   (no ticket)",
        "B": "recurring template           -> PAR-*",
        "C": "set-specific mechanic        -> PAR-* (deck-first)",
        "D": "primitive-blocked            -> MEC-*",
        "E": "bespoke tail                 -> PAR-* hand-authoring / PAR-12",
        "F": "never-supported              (out of denominator)",
    }
    for letter in "ABCDEF":
        print(f"  {letter}  {_LABELS[letter]:<44s} {len(bucket_names[letter]):6d}")

    def _dump_clusters(title: str, clusters: dict[str, list[str]], limit: int | None = None) -> None:
        print(f"\n{'─' * 3} {title} {'─' * 3}")
        ranked = sorted(clusters.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for detail, names in (ranked[:limit] if limit else ranked):
            print(f"  N={len(names):<4d} {detail}")
            print(f"           e.g. {', '.join(sorted(names)[: args.samples])}")

    _dump_clusters(f"Bucket D — primitive-blocked clusters -> MEC-*", d_clusters)
    _dump_clusters(f"Bucket C — set-specific mechanics -> PAR-* (deck-first)", c_clusters)
    _dump_clusters(f"Bucket B — recurring templates (>= {args.min_cluster} cards) -> PAR-*",
                   b_clusters, limit=args.top_b)

    print(f"\n{'─' * 3} Bucket E — bespoke tail (hand-authoring), sample {min(len(e_rows), 40)} of {len(e_rows)} {'─' * 3}")
    for name, tmpl in sorted(e_rows)[:40]:
        print(f"  {name}   | {tmpl}")

    if args.json:
        payload = {
            "parser_version": cov.PARSER_VERSION,
            "totals": {"commander_legal": total, "covered": covered,
                       "unmodeled": total - covered - never_supported,
                       "never_supported": never_supported, "fraction": round(frac, 4)},
            "buckets": {
                "A": sorted(bucket_names["A"]),
                "B": [{"template": t, "cards": sorted(n)}
                      for t, n in sorted(b_clusters.items(), key=lambda kv: -len(kv[1]))],
                "C": [{"mechanic": t, "cards": sorted(n)}
                      for t, n in sorted(c_clusters.items(), key=lambda kv: -len(kv[1]))],
                "D": [{"cluster": t, "cards": sorted(n)}
                      for t, n in sorted(d_clusters.items(), key=lambda kv: -len(kv[1]))],
                "E": [{"card": n, "template": t} for n, t in sorted(e_rows)],
                "F": sorted(bucket_names["F"]),
            },
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote JSON breakdown to {args.json}")


if __name__ == "__main__":
    main()
