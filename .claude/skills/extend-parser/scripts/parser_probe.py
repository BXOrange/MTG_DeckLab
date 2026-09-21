#!/usr/bin/env python3
"""Probe the oracle parser against the real card cache — the research half of
extending `parser/oracle/`.

A full re-parse of all ~34k cached cards takes ~4s (`parse_oracle` is pure and
memoized), so every question below is answered live, from scratch, with no
ledger involved. That is deliberate: `scripts/coverage_report.py` is the
*ledger-backed, authoritative* measurement you run once per batch and sync the
docs to; this is the throwaway inner-loop tool you run twenty times while
writing one handler, and it must never write to the coverage DB.

Subcommands
  rank      the live processing list (templates ranked by cards blocked)
  blocked   which real cards a template blocks — split into cards this is the
            ONLY blocker for (a handler would actually unlock them) vs cards
            that stay UNMODELED anyway because other clauses are unclaimed too
  clause    run one clause through normalize + the handler table; say where it
            falls over
  card      full per-line parse trace for one cached card
  composition  which HALF of an unclaimed trigger/activated clause is missing
            (trigger head vs effect body), ranked by shared axis — the tool
            for finding a generalization instead of another per-phrase row
  snapshot  write a baseline of which cards are currently covered
  diff      compare current parse against a snapshot: newly covered AND newly
            broken (over-matching regressions)

Usage (from backend/, venv active — or via the wrapper paths in SKILL.md):
  python <this> rank --top 40
  python <this> rank --grep 'fights'
  python <this> blocked 'you may pay .*if you do'
  python <this> clause "target creature gets +2/+2 until end of turn"
  python <this> card "Invasion of Ergamon"
  python <this> snapshot /tmp/base.json
  python <this> diff /tmp/base.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# backend/ on the path — this script lives under .claude/skills/, outside the
# package tree, so walk up to the repo root and take `backend/` from there
# (also honouring an explicit MTG_BACKEND_DIR for an out-of-tree checkout).
def _find_backend() -> Path:
    env = os.environ.get("MTG_BACKEND_DIR")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in [Path.cwd().resolve(), *Path.cwd().resolve().parents, *here.parents]:
        if (parent / "mtg_analyzer").is_dir():
            return parent
        if (parent / "backend" / "mtg_analyzer").is_dir():
            return parent / "backend"
    sys.exit("could not locate backend/ — run from the repo, or set MTG_BACKEND_DIR")


sys.path.insert(0, str(_find_backend()))

from mtg_analyzer.game.card_registry import is_registered  # noqa: E402
from mtg_analyzer.parser.oracle import (  # noqa: E402
    NEVER_SUPPORTED,
    PARSER_VERSION,
    abstract_clause,
    parse_oracle,
)
from mtg_analyzer.parser.oracle.catalogue.handlers import HANDLERS, match_clause  # noqa: E402
from mtg_analyzer.parser.oracle.normalize import normalize  # noqa: E402
from mtg_analyzer.parser.oracle.segmenter import segment_line  # noqa: E402
from mtg_analyzer.parser.oracle.spec import ParserProvenance  # noqa: E402
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH  # noqa: E402


# --- shared -----------------------------------------------------------------


def load_cards(db_path: Path, limit: int | None = None):
    cards = CardDatabase(db_path).list_cards()
    return cards[:limit] if limit else cards


def scan(cards):
    """Parse every card once. Returns (rows, counts).

    A row is (name, covered, unclaimed_clauses). "Covered" matches
    `scripts/coverage_report.py`: parser-MODELED **or** hand-AUTHORED in
    `game/card_catalogue/`, so a probe never credits a handler for a card
    that was already behaving via the hand-authored escape valve.
    """
    rows = []
    counts = Counter()
    for card in cards:
        name = getattr(card, "name", "") or ""
        result = parse_oracle(card)
        if result.coverage == NEVER_SUPPORTED:
            # RULE 123 Stickers &c: a permanent non-goal. Neither covered nor
            # backlog — no unclaimed clauses, so it contributes to no ranking
            # and never appears in a snapshot's covered set.
            counts["never_supported"] += 1
            rows.append((name, False, []))
            continue
        covered = result.modeled or is_registered(name)
        counts["covered" if covered else "uncovered"] += 1
        rows.append((name, covered, [] if covered else list(result.unclaimed)))
    counts["total"] = len(cards)
    return rows, counts


def _print_coverage(counts):
    total = counts["total"] or 1
    print(
        f"coverage {counts['covered']}/{counts['total']} = "
        f"{counts['covered'] / total:.2%}  "
        f"({counts['never_supported']} never-supported)  "
        f"PARSER_VERSION={PARSER_VERSION}"
    )


# --- rank -------------------------------------------------------------------


def cmd_rank(args):
    rows, counts = scan(load_cards(args.card_db, args.limit))
    _print_coverage(counts)

    pattern = re.compile(args.grep, re.IGNORECASE) if args.grep else None
    template_cards: Counter[str] = Counter()
    for _name, covered, unclaimed in rows:
        if covered:
            continue
        for template in {abstract_clause(c) for c in unclaimed if c.strip()}:
            if pattern is None or pattern.search(template):
                template_cards[template] += 1

    ranked = sorted(template_cards.items(), key=lambda kv: (-kv[1], kv[0]))
    label = f" matching /{args.grep}/" if args.grep else ""
    print(f"\ntop {args.top} unclaimed templates{label} (cards blocked → template):")
    for template, n in ranked[: args.top]:
        print(f"  {n:5d}  {template}")
    if not ranked:
        print("  (none)")


# --- blocked ----------------------------------------------------------------


def cmd_blocked(args):
    """The overcount killer.

    A card is only unlocked when *every* one of its clauses is claimed (the
    gate is fail-closed), so the ranking's card count is an upper bound, often
    a wild one. This splits the matching cards into the ones a handler for this
    template would genuinely finish (SOLO) and the ones that would still be
    UNMODELED afterwards (ALSO BLOCKED, with the other clauses shown so you can
    see whether one more small handler would sweep the cluster).
    """
    pattern = re.compile(args.pattern, re.IGNORECASE)
    rows, counts = scan(load_cards(args.card_db, args.limit))
    _print_coverage(counts)

    solo, also = [], []
    for name, covered, unclaimed in rows:
        if covered:
            continue
        hits = [c for c in unclaimed if pattern.search(c)]
        if not hits:
            continue
        rest = [c for c in unclaimed if not pattern.search(c)]
        (solo if not rest else also).append((name, hits, rest))

    print(f"\n/{args.pattern}/ appears in an unclaimed clause of {len(solo) + len(also)} cards")
    print(f"  SOLO BLOCKER on {len(solo)} — a handler for this makes these MODELED")
    print(f"  also blocked on {len(also)} — these need more than this handler\n")

    print(f"--- SOLO ({len(solo)}), showing {min(len(solo), args.show)} ---")
    for name, hits, _rest in solo[: args.show]:
        print(f"  {name}")
        for clause in hits:
            print(f"      {clause}")

    print(f"\n--- ALSO BLOCKED ({len(also)}), showing {min(len(also), args.show)} ---")
    print("    (indented lines are the OTHER unclaimed clauses — the real remaining work)")
    for name, hits, rest in also[: args.show]:
        print(f"  {name}")
        for clause in hits:
            print(f"    match: {clause}")
        for clause in rest:
            print(f"    else : {clause}")

    # What else stands between the ALSO cards and coverage, ranked — this is
    # usually where the next handler after this one comes from.
    residue: Counter[str] = Counter()
    for _name, _hits, rest in also:
        for template in {abstract_clause(c) for c in rest if c.strip()}:
            residue[template] += 1
    if residue:
        print("\n--- what else blocks those cards (ranked) ---")
        for template, n in sorted(residue.items(), key=lambda kv: (-kv[1], kv[0]))[: args.top]:
            print(f"  {n:5d}  {template}")


# --- clause -----------------------------------------------------------------


def cmd_clause(args):
    """Diagnose one clause without hunting for a card that prints it."""
    raw = args.text
    norm = normalize(raw, args.name)
    print(f"raw        : {raw}")
    print(f"normalized : {norm!r}")
    if norm != raw.lower().strip():
        print("             (normalize rewrote it — write your regex against THIS)")

    for label, kwargs in (
        ("plain", {}),
        ("self_subject", {"self_subject": True}),
        ("previous_subject", {"previous_subject": True}),
    ):
        for line in [line for line in norm.split("\n") if line.strip()]:
            specs = match_clause(line, **kwargs)
            verdict = "CLAIMED" if specs is not None else "unclaimed"
            print(f"\n[{label}] {verdict}: {line}")
            if specs is not None:
                for spec in specs:
                    print(f"    {spec.type} {spec.params}")
                break
        else:
            continue
        break

    # Which handlers *almost* match — the fastest way to find the row to widen
    # instead of adding a near-duplicate one.
    print("\nhandlers whose regex matches a PREFIX of the clause (candidates to widen):")
    near = []
    for handler in HANDLERS:
        for line in [line for line in norm.split("\n") if line.strip()]:
            m = handler.regex.match(line)
            if m and m.end() > len(line) * 0.4:
                near.append((handler.name, m.end(), len(line), line[m.end():]))
    for name, end, total, tail in sorted(near, key=lambda t: -t[1])[:8]:
        print(f"  {name:34s} consumed {end}/{total}, left: {tail!r}")
    if not near:
        print("  (none — this is a genuinely new family, not a widening)")

    # And the segmenter's own verdict, which is what the gate actually reads:
    # a clause can be fine while its trigger/cost wrapper is what fails.
    prov = ParserProvenance(version=PARSER_VERSION, source="probe")
    for line in [line for line in norm.split("\n") if line.strip()]:
        seg = segment_line(line, allow_spell_effect=True, provenance=prov)
        print(f"\nsegmenter: claimed={seg.claimed} keyword_line={seg.keyword_line} :: {line}")
        if seg.spec is not None:
            print(f"    kind={seg.spec.ability_kind} effects={[e.type for e in seg.spec.effects]}")


# --- card -------------------------------------------------------------------


def cmd_card(args):
    db = CardDatabase(args.card_db)
    card = db.get_card(args.name)
    if card is None:
        matches = db.search_cards(args.name, limit=10)
        print(f"no exact cache hit for {args.name!r}. did you mean:")
        for c in matches:
            print(f"  {c.name}")
        return

    result = parse_oracle(card)
    authored = is_registered(card.name)
    print(f"{card.name}")
    print(f"  coverage={result.coverage} modeled={result.modeled} hand-authored={authored}")
    print(f"\n  raw oracle_text:\n{card.oracle_text}")
    print(f"\n  normalized:\n{normalize(card.oracle_text or '', card.name, card.keywords)}")

    print("\n  specs:")
    for spec in result.specs:
        print(f"    [{spec.ability_kind}] {[e.type for e in spec.effects]}")
        for effect in spec.effects:
            print(f"        {effect.type} {effect.params}")
    if not result.specs:
        print("    (none)")

    print("\n  UNCLAIMED (this is the work):")
    for clause in result.unclaimed:
        print(f"    {clause}")
        print(f"      template: {abstract_clause(clause)}")
    if not result.unclaimed:
        print("    (none)")


# --- snapshot / diff --------------------------------------------------------


def cmd_snapshot(args):
    rows, counts = scan(load_cards(args.card_db, args.limit))
    _print_coverage(counts)
    args.path.write_text(
        json.dumps(
            {
                "parser_version": PARSER_VERSION,
                "counts": dict(counts),
                "covered": sorted(n for n, cov, _ in rows if cov),
            },
            indent=0,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote baseline to {args.path} ({counts['covered']} covered card names)")


def cmd_diff(args):
    base = json.loads(args.path.read_text(encoding="utf-8"))
    before = set(base["covered"])
    rows, counts = scan(load_cards(args.card_db, args.limit))
    after = {n for n, cov, _ in rows if cov}

    gained = sorted(after - before)
    lost = sorted(before - after)

    print(f"baseline: {len(before)} covered (PARSER_VERSION={base.get('parser_version')})")
    _print_coverage(counts)
    print(f"\n+{len(gained)} newly covered / -{len(lost)} REGRESSED\n")

    print(f"--- newly covered ({len(gained)}), showing {min(len(gained), args.show)} ---")
    for name in gained[: args.show]:
        print(f"  + {name}")

    print(f"\n--- REGRESSED ({len(lost)}) — a widened regex over-matched; fix before shipping ---")
    for name in lost[: args.show]:
        print(f"  - {name}")
    if not lost:
        print("  (none)")


# --- composition ------------------------------------------------------------

#: A trigger clause is "<when/whenever/at cond>, <body>"; an activated one is
#: "<cost>: <body>". The head/body split is what `composition` probes.
_TRIGGER_SPLIT = re.compile(r"^(?P<head>(?:when|whenever|at)\b[^,]*),\s*(?P<body>.+)$", re.S)
_ACTIVATED_SPLIT = re.compile(
    r"^(?P<head>[^:\"]{1,80}(?:\{[^}]+\}|sacrifice|discard|pay|exile|tap|untap|remove|return)[^:\"]{0,80}):\s*(?P<body>.+)$",
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


def cmd_composition(args):
    """Which half of an unclaimed trigger/activated clause is the missing part?

    The gate is all-or-nothing, so "the trigger head is unparsed" and "the
    effect body is unparsed" look identical in `blocked`. This splits every
    unclaimed clause into head/body and tests each against a known-good
    partner (head + "draw a card"; "when ~ enters," + body), so a *shared*
    axis — the same trigger condition fronting many bodies the parser already
    handles — shows up as one row instead of hundreds. Views:

      summary   H±/B± table (H- B+ = trigger head is the ONLY gap)
      heads     ranked unparsed trigger heads whose body parses alone
      families  the same, grouped by event family, with the cast/enter/attack
                sub-axes visible (`--family cast` lists that family's heads)
      mods      which modifier axis (leading "if", "for each", …) repairs how
                many failing effect sentences
      conds     the leading-"if" conditions among those, grouped by shape
    """
    provenance = ParserProvenance(version=PARSER_VERSION, source="probe")
    rows, _counts = scan(load_cards(args.card_db, args.limit))

    clauses: dict[str, dict[str, set[str]]] = {}
    for name, covered, unclaimed in rows:
        if covered:
            continue
        for clause in unclaimed:
            info = clauses.setdefault(clause, {"cards": set(), "solo": set()})
            info["cards"].add(name)
            if len(unclaimed) == 1:
                info["solo"].add(name)

    head_cache: dict[str, bool] = {}
    body_cache: dict[str, bool] = {}
    split = []
    for text, info in clauses.items():
        kind = "trigger"
        m = _TRIGGER_SPLIT.match(text)
        if not m:
            kind, m = "activated", _ACTIVATED_SPLIT.match(text)
        if not m:
            continue
        head, body = m.group("head").strip(), m.group("body").strip()
        hprobe = f"{head}, draw a card." if kind == "trigger" else f"{head}: draw a card."
        bprobe = f"when ~ enters, {body}" if kind == "trigger" else f"{{t}}: {body}"
        head_ok = head_cache.setdefault(hprobe, _claims(hprobe, provenance))
        body_ok = body_cache.setdefault(bprobe, _claims(bprobe, provenance))
        split.append((text, kind, head, body, head_ok, body_ok, info))

    def label(head_ok: bool, body_ok: bool) -> str:
        return ("H+" if head_ok else "H-") + ("B+" if body_ok else "B-")

    if args.view == "summary":
        for kind in ("trigger", "activated"):
            part = [r for r in split if r[1] == kind]
            print(f"\n{kind}: {len(part)} unclaimed clauses")
            for lab in ("H+B+", "H-B+", "H+B-", "H-B-"):
                sel = [r for r in part if label(r[4], r[5]) == lab]
                cards = set().union(*[r[6]["cards"] for r in sel]) if sel else set()
                solo = set().union(*[r[6]["solo"] for r in sel]) if sel else set()
                print(f"  {lab}: {len(sel):5d} clauses  {len(cards):5d} cards  {len(solo):5d} cards where it is the ONLY gap")
        return

    if args.view in ("heads", "families"):
        heads: dict[str, dict[str, set[str]]] = {}
        for text, kind, head, _body, head_ok, body_ok, info in split:
            if kind != "trigger" or head_ok or not body_ok:
                continue
            slot = heads.setdefault(abstract_clause(head), {"cards": set(), "solo": set()})
            slot["cards"] |= info["cards"]
            slot["solo"] |= info["solo"]
        if args.view == "heads":
            pattern = re.compile(args.family, re.IGNORECASE) if args.family else None
            ranked = sorted(heads.items(), key=lambda kv: (-len(kv[1]["solo"]), -len(kv[1]["cards"])))
            print(f"{len(heads)} distinct unparsed trigger heads whose effect parses alone")
            shown = 0
            for head, v in ranked:
                if pattern and not pattern.search(head):
                    continue
                print(f"  {len(v['solo']):4d} solo / {len(v['cards']):4d} cards  {head}")
                shown += 1
                if shown >= args.top:
                    break
            return
        fam: dict[str, dict] = {}
        for head, v in heads.items():
            name = next((n for n, rx in _HEAD_FAMILIES if re.search(rx, head)), "other")
            slot = fam.setdefault(name, {"heads": 0, "cards": set(), "solo": set()})
            slot["heads"] += 1
            slot["cards"] |= v["cards"]
            slot["solo"] |= v["solo"]
        print("event family of the unparsed trigger head (effect parses alone):")
        for name, v in sorted(fam.items(), key=lambda kv: -len(kv[1]["solo"])):
            print(f"  {name:18s} {v['heads']:4d} heads  {len(v['solo']):4d} cards blocked ONLY by the head  ({len(v['cards'])} total)")
        return

    # mods / conds: single effect sentences of trigger bodies whose head is fine
    sentences: dict[str, dict[str, set[str]]] = {}
    for text, kind, _head, body, head_ok, body_ok, info in split:
        if kind != "trigger" or not head_ok or body_ok:
            continue
        for sentence in (s.strip() for s in _SENTENCE_SPLIT.split(body) if s.strip()):
            slot = sentences.setdefault(sentence, {"cards": set(), "solo": set()})
            slot["cards"] |= info["cards"]
            slot["solo"] |= info["solo"]
    sentence_cache: dict[str, bool] = {}

    def sentence_ok(s: str) -> bool:
        return sentence_cache.setdefault(s, _claims(f"when ~ enters, {s}", provenance))

    if args.view == "mods":
        present: Counter[str] = Counter()
        repaired: dict[str, dict] = {}
        for sentence, info in sentences.items():
            for axis, rx in _MODIFIER_AXES.items():
                if not re.search(rx, sentence):
                    continue
                present[axis] += 1
                shorter = re.sub(rx, "", sentence, count=1).strip(" ,.")
                if shorter and shorter != sentence and sentence_ok(shorter):
                    slot = repaired.setdefault(axis, {"n": 0, "solo": set(), "ex": sentence[:110]})
                    slot["n"] += 1
                    slot["solo"] |= info["solo"]
        print(f"{len(sentences)} distinct failing effect sentences (trigger bodies, head parses)")
        print(f"{'modifier axis':46s} present  repaired  solo-cards")
        for axis, v in sorted(repaired.items(), key=lambda kv: -len(kv[1]["solo"])):
            print(f"{axis:46s} {present[axis]:6d}  {v['n']:8d}  {len(v['solo']):5d}   e.g. {v['ex']}")
        return

    # conds: leading "if <cond>," whose remaining effect parses
    reflexive = re.compile(r"^(you do|you don't|you can't|they do|they don't|a player does|that player does)$")
    conds: dict[str, dict] = {}
    for sentence, info in sentences.items():
        m = re.match(r"^if ([^,]+), (.+)$", sentence)
        if not m or reflexive.match(m.group(1)) or not sentence_ok(m.group(2).strip(" .")):
            continue
        slot = conds.setdefault(abstract_clause(m.group(1)), {"n": 0, "solo": set()})
        slot["n"] += 1
        slot["solo"] |= info["solo"]
    print(f"{len(conds)} distinct leading-if conditions (reflexive 'if you do' excluded)")
    for cond, v in sorted(conds.items(), key=lambda kv: -len(kv[1]["solo"]))[: args.top]:
        print(f"  {len(v['solo']):4d} solo  if {cond}")


# --- cli --------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)
    ap.add_argument("--limit", type=int, default=None, help="only the first N cached cards (quick test)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("rank", help="live processing list")
    p.add_argument("--top", type=int, default=40)
    p.add_argument("--grep", default=None, help="only templates matching this regex")
    p.set_defaults(func=cmd_rank)

    p = sub.add_parser("blocked", help="cards a template blocks, split solo vs also-blocked")
    p.add_argument("pattern", help="regex matched against unclaimed clauses")
    p.add_argument("--show", type=int, default=25, help="cards to list per section")
    p.add_argument("--top", type=int, default=20, help="residue templates to rank")
    p.set_defaults(func=cmd_blocked)

    p = sub.add_parser("clause", help="diagnose one clause")
    p.add_argument("text")
    p.add_argument("--name", default=None, help="card name, so normalize can fold it to ~")
    p.set_defaults(func=cmd_clause)

    p = sub.add_parser("card", help="full parse trace for one cached card")
    p.add_argument("name")
    p.set_defaults(func=cmd_card)

    p = sub.add_parser("composition", help="head-vs-body split of unclaimed trigger/activated clauses")
    p.add_argument("view", choices=["summary", "heads", "families", "mods", "conds"], nargs="?", default="summary")
    p.add_argument("--family", default=None, help="heads view: only heads matching this regex")
    p.add_argument("--top", type=int, default=40)
    p.set_defaults(func=cmd_composition)

    p = sub.add_parser("snapshot", help="write a covered-cards baseline")
    p.add_argument("path", type=Path)
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("diff", help="compare current parse to a baseline")
    p.add_argument("path", type=Path)
    p.add_argument("--show", type=int, default=40)
    p.set_defaults(func=cmd_diff)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
