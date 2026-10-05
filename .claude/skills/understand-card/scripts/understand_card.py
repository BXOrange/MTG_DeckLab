#!/usr/bin/env python3
"""Read a card the way the rules engine has to — in one command.

Parser work, engine work and mechanic validation all start the same way: take
a card's oracle text apart, decide which Comprehensive Rules govern each
clause, and check what (if anything) the pipeline already does with it. Done
by hand that means: find the real text, run it through `normalize`, eyeball
the segmenter's verdict, then chase every `RULE <n>` and glossary term through
the two-hop `docs/Reference/rules_wiki/` lookup — and, for the subtle cards,
read Scryfall's "Notes and Rules Information" (the official rulings) and chase
*their* rule references too. This script collapses that into `card` / `clause`
/ `check` / `term` / `rulings`.

It only ever reads game state. It does not decide what a clause *means* and it
is not a runtime check — for "does the bound ability actually behave", hand off
to the game-engine skill's `engine_bench.py` (`inspect` / `play`). For "which
real cards would a handler unlock" use the extend-parser skill's
`parser_probe.py`. This one answers the question that comes first: *what is
this card, in rules terms, and how far does the pipeline already get?*

Rulings ("Notes and Rules Information") are fetched once from Scryfall's public
API (honouring the project User-Agent + rate limit from `config.py`) and
cached under `<CACHE_DIR>/rulings/<id>.json`, so every later read is offline.
Offline with no cache, rulings are simply skipped with a one-line note — the
rest of the output is unaffected.

Subcommands
  card    full reading: identity, raw vs normalized text, per-clause parser
          verdict, every keyword + the CR passage that defines it, and a
          governing-rules roll-up (glossary terms -> rule + line, common/
          structural terms sorted to the bottom). --rulings folds in the
          cached/fetched rulings + the rules they cite. Takes multiple names
          (scan a whole parser_probe.py list in one call); --brief prints one
          triage line per card instead of the full reading
  clause  the same rules/glossary mapping for an arbitrary template string,
          for planning a parser handler before a card exists to test against
  check   validation triage: one table of clause -> governing RULE -> parser
          claimed? -> binder produced an effect? -> PASS/GAP, and any rulings
          that mention timing/layer subtleties worth verifying at runtime.
          Also takes multiple names
  term    two-hop glossary lookup done in one shot (term -> line -> passage)
  rulings Scryfall's rulings for the card, each with the CR rules + glossary
          terms it cites resolved to passages; flags rulings that look like
          they explain an UNCLAIMED clause

Usage (from backend/, venv active):
  UC=../.claude/skills/understand-card/scripts/understand_card.py
  python $UC card "Questing Beast" --rulings
  python $UC card "Wrenn and Six" --rules        # inline every CR passage
  python $UC card --brief "Card A" "Card B" "Card C"   # skim a batch fast
  python $UC clause "Whenever a creature you control dies, draw a card."
  python $UC check "Grist, the Hunger Tide"
  python $UC term "Deathtouch"
  python $UC rulings "Humility" --rules
  python $UC rulings "Opalescence" --no-fetch    # cache only, never touch the network
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path


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


BACKEND = _find_backend()
REPO = BACKEND.parent if BACKEND.name == "backend" else BACKEND
sys.path.insert(0, str(BACKEND))

from mtg_analyzer.game.binding.core import bind_from_catalogue  # noqa: E402
from mtg_analyzer.game.card_registry import is_registered  # noqa: E402
from mtg_analyzer.game.mana_abilities import parse_mana_abilities  # noqa: E402
from mtg_analyzer.models import Card, GameObject, Zone  # noqa: E402
from mtg_analyzer.parser.oracle.catalogue.keywords import (  # noqa: E402
    keyword_slug,
    resolve_keyword,
)
from mtg_analyzer.parser.oracle.gate import parse_oracle  # noqa: E402
from mtg_analyzer.parser.oracle.normalize import normalize  # noqa: E402
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH  # noqa: E402

try:  # config is optional only so `--help` still works on a broken checkout
    from mtg_analyzer import config as _config  # noqa: E402

    CACHE_DIR = Path(_config.CACHE_DIR)
    DATA_DIR = Path(_config.DATA_DIR)
    _UA = _config.USER_AGENT
    _MIN_INTERVAL = _config.SCRYFALL_MIN_REQUEST_INTERVAL_SECONDS
except Exception:  # pragma: no cover - defensive
    CACHE_DIR = BACKEND / "cache"
    DATA_DIR = BACKEND / "data"
    _UA = "MTG-Deck-Analyzer/0.1"
    _MIN_INTERVAL = 0.1

WIKI = REPO / "docs" / "Reference" / "rules_wiki"
RULINGS_CACHE = CACHE_DIR / "rulings"

#: "rule 509.1a", "504.1", "layer 4" — the shapes a ruling's prose uses to
#: cite the Comprehensive Rules. Bare 3-digit-plus-dot numbers are only taken
#: as a rule ref when they look like one (NNN or NNN.NN[a]) to avoid eating
#: "2019-10-04" style dates and P/T values.
_RULE_REF_RE = re.compile(r"\b(?:rule\s+)?(\d{3}(?:\.\d+[a-z]?)?)\b", re.IGNORECASE)
_LAYER_RE = re.compile(r"\blayer\s+\d\b", re.IGNORECASE)


# --- rules_wiki: the two-hop lookup, done for you -------------------------


class Wiki:
    """`rule_line_index.json` + the CR source, wrapped so a `RULE <n>` or a
    glossary term resolves to real passage text in one call (see the wiki's
    own README for the manual version)."""

    def __init__(self) -> None:
        index_path = WIKI / "rule_line_index.json"
        if not index_path.exists():
            sys.exit(f"no rules index at {index_path} — regenerate with build_wiki.py")
        self.index = json.loads(index_path.read_text(encoding="utf-8"))
        sources = sorted((REPO / "docs" / "Reference").glob("MagicCompRules*.txt"))
        if not sources:
            sys.exit("Comprehensive Rules .txt not found under docs/Reference/")
        self.lines = sources[-1].read_text(encoding="utf-8", errors="replace").split("\n")
        self._glossary = {k.lower(): v for k, v in self.index.get("glossary", {}).items()}

    def rule_line(self, ref: str) -> int | None:
        ref = ref.strip()
        subrules = self.index.get("subrules") or {}
        if ref in subrules:
            return subrules[ref]
        sections = self.index.get("sections") or {}
        if ref in sections:
            return sections[ref].get("line")
        # a subrule under a section (e.g. "702.9" lives in section 702's own map)
        head = ref.split(".")[0]
        if head in sections:
            return sections[head].get("subrules", {}).get(ref) or sections[head].get("line")
        return None

    def passage(self, ref: str, n: int = 8) -> str:
        line = self.rule_line(ref)
        if line is None:
            return f"    (RULE {ref} not in the index)"
        start = max(0, line - 1)
        body = [row.rstrip() for row in self.lines[start : start + n]]
        while body and not body[-1].strip():
            body.pop()
        return "\n".join("    " + row for row in body)

    def term(self, name: str) -> tuple[int, str] | None:
        hit = self._glossary.get(name.strip().lower())
        if not hit:
            return None
        return hit["line"], hit.get("xref") or ""

    def glossary_terms_in(self, text: str) -> list[tuple[str, str, int]]:
        """Every defined term whose whole-word form appears in `text`.

        Returns (Term, xref-rule, line), longest term first so a match on
        "First Strike" isn't also reported as "Strike"."""
        low = text.lower()
        out: list[tuple[str, str, int]] = []
        for term_l, hit in self._glossary.items():
            if len(term_l) < 4:  # 'tap', 'end' etc. — too noisy to whole-word scan
                continue
            if re.search(rf"\b{re.escape(term_l)}\b", low):
                display = " ".join(w.capitalize() for w in term_l.split())
                out.append((display, hit.get("xref") or "", hit["line"]))
        out.sort(key=lambda t: (-len(t[0]), t[0]))
        return out


# --- rulings ("Notes and Rules Information") ---------------------------


def _raw_store_row(name: str) -> dict | None:
    """The untouched Scryfall object for `name` from `data/scryfall_raw.db`
    (RawCardStore), for its `id` / `rulings_uri` — read-only, no service import."""
    path = DATA_DIR / "scryfall_raw.db"
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = con.execute(
            "SELECT json FROM raw_cards WHERE name = ? COLLATE NOCASE LIMIT 1", (name,)
        ).fetchone()
        con.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return None


def _fetch_rulings(url: str) -> list[dict]:
    """One throttled GET against Scryfall's rulings endpoint. Raises on failure."""
    import httpx2 as httpx  # local: only needed when actually fetching

    time.sleep(_MIN_INTERVAL)  # honour config.SCRYFALL_MIN_REQUEST_INTERVAL_SECONDS
    resp = httpx.get(
        url, headers={"User-Agent": _UA, "Accept": "application/json"}, timeout=10.0
    )
    resp.raise_for_status()
    return list(resp.json().get("data", []))


def get_rulings(card: Card, *, allow_fetch: bool) -> tuple[list[dict] | None, str]:
    """(rulings, source-note). Cache-first; fetch once if allowed; None if
    unavailable offline. Cache key is the Scryfall printing id."""
    raw = _raw_store_row(card.name)
    scry_id = (raw or {}).get("id") or (card.id if card.id not in ("UC", "BENCH") else None)
    rulings_uri = (raw or {}).get("rulings_uri") or (
        f"https://api.scryfall.com/cards/{scry_id}/rulings" if scry_id else None
    )
    cache_path = RULINGS_CACHE / f"{scry_id}.json" if scry_id else None

    if cache_path and cache_path.exists():
        try:
            blob = json.loads(cache_path.read_text(encoding="utf-8"))
            return blob.get("data", []), f"cached {cache_path.relative_to(REPO)}"
        except (ValueError, OSError):
            pass

    if not allow_fetch:
        return None, "not cached; --no-fetch set (run without it to fetch from Scryfall)"
    if not rulings_uri:
        return None, "no Scryfall id known for this card (not in data/scryfall_raw.db)"

    try:
        data = _fetch_rulings(rulings_uri)
    except Exception as exc:  # network down, rate limited, 4xx/5xx
        return None, f"fetch failed ({type(exc).__name__}: {exc}); offline? try again later"

    if cache_path:
        try:
            RULINGS_CACHE.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"source_uri": rulings_uri, "data": data}, indent=1),
                encoding="utf-8",
            )
        except OSError:
            pass
    return data, f"fetched from Scryfall ({len(data)} ruling(s)), cached"


def rule_refs_in(text: str) -> list[str]:
    """CR rule numbers a ruling's prose cites ("rule 509.1a", "704", "layer 4")."""
    refs = {m.group(1) for m in _RULE_REF_RE.finditer(text)}
    if _LAYER_RE.search(text):  # "layer 4" etc. → RULE 613 governs layer order
        refs.add("613")
    return sorted(refs, key=lambda r: (int(r.split(".")[0]), r))


# --- card lookup --------------------------------------------------------


def load_card(db: CardDatabase, name: str) -> Card:
    card = db.get_card(name)
    if card is not None:
        return card
    print(f"no exact cache hit for {name!r}.", file=sys.stderr)
    for c in db.search_cards(name, limit=10):
        print(f"  {c.name}", file=sys.stderr)
    sys.exit(1)


def _synthetic_card(text: str) -> Card:
    return Card(
        id="UC",
        name="Understand Card",
        type_line="Creature — Human",
        mana_cost_string="{1}",
        converted_mana_cost=1,
        is_creature=True,
        power=1,
        toughness=1,
        oracle_text=text,
        keywords=[],
    )


# --- shared rendering --------------------------------------------------


def _keyword_rows(card: Card) -> list[tuple[str, str, str]]:
    """(display, RULE, shape) for each keyword on the card, via the catalogue."""
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for raw in getattr(card, "keywords", None) or []:
        kdef = resolve_keyword(keyword_slug(str(raw)))
        if kdef is None or kdef.rule in seen:
            continue
        seen.add(kdef.rule)
        shape = getattr(kdef.shape, "value", str(kdef.shape))
        label = str(raw) if str(raw).lower() != kdef.display.lower() else kdef.display
        rows.append((label, kdef.rule, shape))
    return rows


def _clause_verdicts(result) -> list[tuple[str, str]]:
    """(verdict, clause-text) for every clause the gate saw, claimed or not."""
    rows: list[tuple[str, str]] = []
    for spec in result.effect_specs:
        etype = ""
        if spec.effects:
            etype = "/".join(dict.fromkeys(e.type for e in spec.effects))
        elif spec.trigger:
            etype = "trigger"
        elif spec.modes:
            etype = "modal"
        rows.append((f"CLAIMED {spec.ability_kind}" + (f" [{etype}]" if etype else ""),
                     (spec.raw_text or "").strip() or "(no raw_text)"))
    for line in result.unclaimed:
        rows.append(("UNCLAIMED", line.strip()))
    return rows


#: Glossary terms that show up on almost every card regardless of what it
#: actually does — structural vocabulary (zones, the cast/damage/control
#: verbs), not usually the load-bearing rule for *this* card. Not hidden,
#: just sorted to the bottom of `governing rules` so the 2-4 terms that
#: actually matter aren't buried under `Card`/`Damage`/`Hand` on every card.
_COMMON_TERMS = frozenset({
    "Card", "Player", "Permanent", "Spell", "Ability", "Land", "Creature",
    "Hand", "Graveyard", "Battlefield", "Library", "Zone", "Cost", "Mana",
    "Cast", "Control", "Turn", "Phase", "Step", "Game", "Object", "Source",
    "Owner", "Damage", "Target", "Life", "Play", "Exile", "Stack", "Token",
})


def _split_gov(gov: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Partition `_governing_rules` output into (notable, common).

    A row is "common" only when it's purely a generic glossary hit (`why`
    starts with "term:") for a name in `_COMMON_TERMS` — a keyword-driven row
    (`why` starts with "keyword:") is always notable, even for a common-named
    keyword, since that's the card's own printed ability, not scan noise.
    """
    notable, common = [], []
    for rule, why in gov:
        term = why.split(": ", 1)[1] if why.startswith("term: ") else None
        (common if term in _COMMON_TERMS else notable).append((rule, why))
    return notable, common


def _governing_rules(wiki: Wiki, card_or_text) -> list[tuple[str, str]]:
    """Merged, de-duped (RULE, why) list from keywords + glossary xrefs."""
    pairs: dict[str, str] = {}
    if isinstance(card_or_text, Card):
        for label, rule, _shape in _keyword_rows(card_or_text):
            pairs.setdefault(rule, f"keyword: {label}")
        text = card_or_text.oracle_text or ""
    else:
        text = card_or_text
    for term, xref, _line in wiki.glossary_terms_in(text):
        if xref and xref not in pairs:
            pairs[xref] = f"term: {term}"
    # sort by CR order: section number, then subrule number (as an int, so
    # 702.9 sorts before 702.10), then any trailing letter.
    def _key(r: str) -> tuple:
        m = re.match(r"(\d+)(?:\.(\d+))?([a-z]*)", r)
        if not m:
            return (9999, 0, r)
        return (int(m.group(1)), int(m.group(2) or 0), m.group(3) or "")

    return sorted(pairs.items(), key=lambda kv: _key(kv[0]))


#: prose signals in a ruling that mean "the engine has to get an ordering /
#: timing / counting subtlety right here" — worth a runtime check even when the
#: parser claims the clause.
_SUBTLETY_MARKERS = (
    "layer", "only once", "doesn't trigger", "does not trigger", "won't trigger",
    "last known information", "state-based", "replacement effect", "intervening",
    "each combat", "timestamp", "in addition to", "instead of", "can't be",
    "isn't", "is not", "only if", "as though",
)


def _render_rulings(
    wiki: Wiki, rulings: list[dict], *, unclaimed: list[str], inline_rules: bool, lines: int
) -> None:
    if not rulings:
        print("  (Scryfall lists no rulings for this card)")
        return
    unclaimed_words = {
        w for line in unclaimed for w in re.findall(r"[a-z]{5,}", line.lower())
    }
    all_refs: dict[str, None] = {}
    for i, r in enumerate(rulings, 1):
        comment = (r.get("comment") or "").strip()
        date = r.get("published_at") or "?"
        print(f"  {i}. [{date}] {comment}")
        refs = rule_refs_in(comment)
        for ref in refs:
            all_refs.setdefault(ref, None)
        tags = []
        if refs:
            tags.append("cites RULE " + ", ".join(refs))
        if any(m in comment.lower() for m in _SUBTLETY_MARKERS):
            tags.append("timing/layer subtlety")
        hit_words = unclaimed_words & set(re.findall(r"[a-z]{5,}", comment.lower()))
        if len(hit_words) >= 2:
            tags.append(f"overlaps an UNCLAIMED clause ({', '.join(sorted(hit_words)[:4])})")
        if tags:
            print(f"       -> {'; '.join(tags)}")
    if all_refs:
        print(f"\n  rules cited across the rulings ({len(all_refs)}):")
        for ref in sorted(all_refs, key=lambda r: (int(r.split('.')[0]), r)):
            line = wiki.rule_line(ref)
            print(f"    RULE {ref:<9} {('L%s' % line) if line else 'not indexed'}")
            if inline_rules:
                print(wiki.passage(ref, n=lines))
                print()


# --- commands --------------------------------------------------------


def _card_brief(wiki: Wiki, card: Card, result) -> None:
    """One-screen triage line per card — for skimming a whole SOLO/blocked
    list from `parser_probe.py` without paging through the full reading."""
    rows = _clause_verdicts(result)
    unclaimed = [c for v, c in rows if v == "UNCLAIMED"]
    kw_rows = _keyword_rows(card)
    gov = _governing_rules(wiki, card)
    notable, common = _split_gov(gov)

    print(f"{card.name}  [{card.type_line}]  {card.mana_cost_string or ''}")
    print(f"  coverage={result.coverage}  registered={is_registered(card.name)}  "
          f"clauses={len(rows)} ({len(unclaimed)} unclaimed)")
    if kw_rows:
        print(f"  keywords: {', '.join(lbl for lbl, _, _ in kw_rows)}")
    if notable:
        print(f"  notable rules: {', '.join(r for r, _ in notable)}"
              + (f"  (+{len(common)} common)" if common else ""))
    elif common:
        print(f"  rules: only common/structural terms ({len(common)}) — nothing card-specific found")
    for line in unclaimed:
        print(f"  ! UNCLAIMED  {line}")


def cmd_card(args) -> None:
    wiki = Wiki()
    db = CardDatabase(args.card_db)
    names = args.names
    for i, name in enumerate(names):
        if len(names) > 1:
            if i:
                print("\n" + "=" * 70 + "\n")
            print(f"=== {name} ===")
        card = load_card(db, name)
        result = parse_oracle(card)
        if args.brief:
            _card_brief(wiki, card, result)
            continue
        raw = card.oracle_text or ""
        norm = normalize(raw, name=card.name, keywords=list(getattr(card, "keywords", None) or []))

        print(f"{card.name}")
        print(f"  {card.type_line}   {card.mana_cost_string or ''}  cmc={card.converted_mana_cost}")
        print(f"  registered in card_catalogue: {is_registered(card.name)}")
        print(f"  parser coverage: {result.coverage}")

        print("\n--- oracle text (raw) ---")
        print(raw or "(vanilla)")
        print("\n--- normalized (what the segmenter/handlers actually see) ---")
        print(norm or "(empty)")

        rows = _clause_verdicts(result)
        print(f"\n--- clauses ({len(rows)}) ---")
        for verdict, clause in rows:
            mark = " " if verdict.startswith("CLAIMED") else "!"
            print(f"  {mark} [{verdict}]  {clause}")

        kw_rows = _keyword_rows(card)
        if kw_rows:
            print(f"\n--- keywords ({len(kw_rows)}) ---")
            for label, rule, shape in kw_rows:
                print(f"  {label}  —  RULE {rule}  ({shape})")
                if args.rules:
                    print(wiki.passage(rule, n=args.lines))
                    print()

        gov = _governing_rules(wiki, card)
        notable, common = _split_gov(gov)
        print(f"\n--- governing rules ({len(gov)}) — keywords + every defined term in the text ---")
        for rule, why in notable:
            line = wiki.rule_line(rule)
            loc = f"L{line}" if line else "not indexed"
            print(f"  RULE {rule:<9} {loc:<12} {why}")
            if args.rules:
                print(wiki.passage(rule, n=args.lines))
                print()
        if common:
            print(f"  ({len(common)} more common/structural term(s), usually not load-bearing: "
                  + ", ".join(why.split(": ", 1)[1] for _, why in common) + ")")
        if not args.rules:
            print("  (add --rules to inline each passage; `term \"<name>\"` for one definition)")

        rulings, note = get_rulings(card, allow_fetch=args.rulings)
        if rulings is not None:
            print(f"\n--- rulings / \"Notes and Rules Information\" ({len(rulings)}, {note}) ---")
            _render_rulings(
                wiki, rulings, unclaimed=result.unclaimed,
                inline_rules=args.rules, lines=args.lines,
            )
        elif args.rulings:
            print(f"\n--- rulings ---\n  unavailable: {note}")
        else:
            print("\n  (no rulings cached — add --rulings to fetch them once from Scryfall)")

        print("\n--- where this gets modeled ---")
        print("  parser handler   backend/mtg_analyzer/parser/oracle/catalogue/handlers.py")
        print("                   (static clauses -> static_handlers.py, trigger conditions -> segmenter.py)")
        print("  hand-authored    backend/mtg_analyzer/game/card_catalogue/  (singletons / replacement effects)")
        print("  engine primitive backend/mtg_analyzer/game/effects/ + game/rules/*_mixin.py")
        print("  runtime check    game-engine skill: engine_bench.py inspect/play \"" + card.name + "\"")


def cmd_clause(args) -> None:
    wiki = Wiki()
    text = args.text
    norm = normalize(text)
    print(f"--- clause ---\n  {text}")
    print(f"--- normalized (write regex against THIS) ---\n  {norm}")

    card = _synthetic_card(text)
    result = parse_oracle(card)
    print(f"\n--- gate verdict on this clause alone: {result.coverage} ---")
    for verdict, clause in _clause_verdicts(result):
        mark = " " if verdict.startswith("CLAIMED") else "!"
        print(f"  {mark} [{verdict}]  {clause}")

    gov = _governing_rules(wiki, text)
    print(f"\n--- governing rules ({len(gov)}) ---")
    for rule, why in gov:
        line = wiki.rule_line(rule)
        print(f"  RULE {rule:<9} {('L%s' % line) if line else 'n/a':<10} {why}")
        if args.rules:
            print(wiki.passage(rule, n=args.lines))
            print()
    print("\nnext: extend-parser skill's parser_probe.py `clause`/`blocked` for the")
    print("handler-prefix diagnosis and the real cards a handler would unlock.")


def cmd_check(args) -> None:
    wiki = Wiki()
    db = CardDatabase(args.card_db)
    names = args.names
    for i, name in enumerate(names):
        if len(names) > 1:
            if i:
                print("\n" + "=" * 70 + "\n")
            print(f"=== {name} ===")
        _run_check(wiki, db, name, args)


def _run_check(wiki: Wiki, db: CardDatabase, name: str, args) -> None:
    card = load_card(db, name)
    result = parse_oracle(card)

    tl = (card.type_line or "").lower()
    zone = Zone.STACK if ("instant" in tl or "sorcery" in tl) else Zone.BATTLEFIELD
    obj = GameObject(card, owner_id="p1", zone=zone)
    bind_from_catalogue(obj)
    bound = {
        "spell_effects": list(getattr(obj, "spell_effects", []) or []),
        "triggered_abilities": list(getattr(obj, "triggered_abilities", []) or []),
        "activated_abilities": list(getattr(obj, "activated_abilities", []) or []),
        "static_effects": list(getattr(obj, "static_effects", []) or []),
        "replacement_effects": list(getattr(obj, "replacement_effects", []) or []),
    }
    bound_total = sum(len(v) for v in bound.values())

    produced = ", ".join(f"{k}={len(v)}" for k, v in bound.items() if v) or "nothing"
    print(f"{card.name}   [{card.type_line}]")
    print(f"  parser coverage : {result.coverage}   registered: {is_registered(card.name)}")
    print(f"  binder produced : {produced}")

    print("\n--- per-clause parser verdict ---")
    for verdict, clause in _clause_verdicts(result):
        claimed = verdict.startswith("CLAIMED")
        print(f"  [{'parser OK ' if claimed else 'parser GAP'}]  {clause[:100]}")
    gov = _governing_rules(wiki, card)
    notable, common = _split_gov(gov)
    gov_str = ", ".join(r for r, _ in notable) or "(none mapped)"
    if common:
        gov_str += f"  (+{len(common)} common)"
    print(f"\n  governing rules across the card: {gov_str}")
    print("  (understand_card.py card <name> --rules  prints each passage)")

    print("\n--- verdict ---")
    gaps: list[str] = []
    is_mana_only = bound_total == 0 and bool(parse_mana_abilities(card)) and not result.effect_specs
    if (
        result.coverage == "MODELED" and bound_total == 0
        and not is_registered(card.name) and not is_mana_only
    ):
        gaps.append("parser says MODELED but the binder produced no effects — "
                    "an EffectSpec.type is likely missing from EffectRegistry, or "
                    "the specs are keyword-only. Confirm with engine_bench.py inspect.")
    if is_registered(card.name) and bound_total == 0:
        gaps.append("card is hand-authored in card_catalogue but nothing bound — "
                    "broken factory or an unregistered EffectSpec.type.")
    if result.unclaimed:
        gaps.append(f"{len(result.unclaimed)} clause(s) UNCLAIMED — card is UNMODELED, "
                    "engine will silently do nothing for them.")
    kw_rows = _keyword_rows(card)
    if kw_rows:
        print(f"  keywords on card: {', '.join(lbl for lbl, _, _ in kw_rows)}  "
              f"(runtime keyword state needs a continuous.recompute — check engine_bench.py inspect)")
    if not gaps:
        note = " (mana ability only — RULE 605 abilities are parsed by " \
               "mana_abilities_for, not bound; nothing bound is expected here)" \
               if is_mana_only else ""
        print(f"  PASS — parser + binder are internally consistent.{note} "
              "Runtime behaviour still needs engine_bench.py play + a real test.")
    else:
        for g in gaps:
            print(f"  GAP  — {g}")

    rulings, note = get_rulings(card, allow_fetch=args.rulings)
    if rulings:
        subtle = [
            r for r in rulings
            if any(m in (r.get("comment") or "").lower() for m in _SUBTLETY_MARKERS)
        ]
        print(f"\n--- rulings check ({len(rulings)} total, {note}) ---")
        if subtle:
            print("  these rulings describe timing/layer/counting behaviour the engine "
                  "must match — verify each against engine_bench.py play:")
            for r in subtle:
                print(f"    - {(r.get('comment') or '').strip()}")
        else:
            print("  no ruling flags an obvious timing/layer subtlety.")
    elif args.rulings:
        print(f"\n--- rulings check ---\n  unavailable: {note}")
    else:
        print("\n  (rulings not checked — add --rulings to fetch Scryfall's 'Notes and "
              "Rules Information' and flag timing/layer subtleties)")


def cmd_term(args) -> None:
    wiki = Wiki()
    hit = wiki.term(args.name)
    if hit is None:
        low = args.name.strip().lower()
        # substring hits first (a real prefix/typo is usually one of these),
        # then the rest ranked by closeness — a plain alphabetical/contains
        # dump buries the actual near-miss in ~740 terms.
        contains = sorted(t for t in wiki._glossary if low in t)
        scored = sorted(
            (t for t in wiki._glossary if t not in contains),
            key=lambda t: difflib.SequenceMatcher(None, low, t).ratio(),
            reverse=True,
        )
        near = (contains + scored)[:12]
        sys.exit(f"{args.name!r} not a glossary term. near: {near}")
    line, xref = hit
    print(f"{args.name}  —  defined at L{line}" + (f", see RULE {xref}" if xref else ""))
    print()
    start = max(0, line - 1)
    # a glossary entry is its heading + body, ended by the blank line before
    # the next term — print exactly that, not a fixed window into the next few.
    seen_body = False
    for row in wiki.lines[start : start + args.lines]:
        if seen_body and not row.strip():
            break
        if row.strip():
            seen_body = True
        print("  " + row.rstrip())
    if xref:
        print(f"\n--- RULE {xref} ---")
        print(wiki.passage(xref, n=args.lines))


def cmd_rulings(args) -> None:
    wiki = Wiki()
    db = CardDatabase(args.card_db)
    card = load_card(db, args.name)
    result = parse_oracle(card)
    rulings, note = get_rulings(card, allow_fetch=not args.no_fetch)
    print(f"{card.name}   —  rulings / \"Notes and Rules Information\"")
    print(f"  parser coverage: {result.coverage}   ({note})")
    if rulings is None:
        print(f"\nunavailable: {note}")
        return
    print()
    _render_rulings(
        wiki, rulings, unclaimed=result.unclaimed,
        inline_rules=args.rules, lines=args.lines,
    )
    if result.unclaimed:
        print("\n  UNCLAIMED clauses on this card (a ruling flagged 'overlaps' above "
              "probably explains one):")
        for line in result.unclaimed:
            print(f"    ! {line.strip()}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="command", required=True)

    pc = sub.add_parser("card", help="full rules reading of a cached card")
    pc.add_argument("names", nargs="+", metavar="name",
                     help="one or more cached card names — scan a whole "
                          "parser_probe.py SOLO/blocked list in one call")
    pc.add_argument("--brief", "-b", action="store_true",
                     help="one-screen triage line instead of the full reading "
                          "(coverage, unclaimed clauses, notable rules) — pairs "
                          "with multiple names to skim a batch fast")
    pc.add_argument("--rules", action="store_true", help="inline every CR passage")
    pc.add_argument("--rulings", action="store_true",
                    help="also fetch Scryfall rulings (cached rulings show without it)")
    pc.add_argument("--lines", type=int, default=8, help="passage length when --rules")
    pc.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)

    pl = sub.add_parser("clause", help="rules/glossary map for an arbitrary template string")
    pl.add_argument("text")
    pl.add_argument("--rules", action="store_true")
    pl.add_argument("--lines", type=int, default=8)

    pk = sub.add_parser("check", help="validation triage: parser vs binder vs rules")
    pk.add_argument("names", nargs="+", metavar="name",
                     help="one or more cached card names")
    pk.add_argument("--rulings", action="store_true",
                    help="fetch Scryfall rulings and flag timing/layer subtleties")
    pk.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)

    pt = sub.add_parser("term", help="glossary lookup, passage inlined")
    pt.add_argument("name")
    pt.add_argument("--lines", type=int, default=10)

    pr = sub.add_parser("rulings", help="Scryfall rulings + the CR rules each cites")
    pr.add_argument("name")
    pr.add_argument("--rules", action="store_true", help="inline each cited CR passage")
    pr.add_argument("--no-fetch", action="store_true",
                    help="use the local cache only; never touch the network")
    pr.add_argument("--lines", type=int, default=8)
    pr.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)

    args = p.parse_args()
    {
        "card": cmd_card,
        "clause": cmd_clause,
        "check": cmd_check,
        "term": cmd_term,
        "rulings": cmd_rulings,
    }[args.command](args)


if __name__ == "__main__":
    main()
