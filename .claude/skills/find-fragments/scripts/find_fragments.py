#!/usr/bin/env python3
"""Per-clause fragment mining of the still-open **Commander-legal** card pool.

`commander_tail_report.py` buckets each uncovered *card*. This script goes one
level down: it records every clause the parser leaves unclaimed (one JSONL row
per card/clause), groups the clauses by shared template and by trigger-head /
body axis, and ranks the groups by how many cards they would **unlock**.

A card only counts as unlocked once *all* of its real open clauses are covered,
so the ranking is by unlockable cards, not by clause count:

  solo      cards whose every open clause shares this one template
  marginal  cards unlocked when this template is added to the templates
            already picked above it (greedy set cover, highest first)

Wrapper headers and modal bodies that already claim on their own are not
fragments (same filter as commander_tail_report.analyse_card); cards left with
only those are listed as "re-measure" and carry no fragment rows.

READ-ONLY: reads the card cache and raw store, never writes coverage.db.

Usage (from backend/, venv active):
  python ../.claude/skills/find-fragments/scripts/find_fragments.py [--out-dir DIR] [--top 80]
      [--samples 4] [--card-db PATH] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path



def _find_backend() -> Path:
    """This skill script lives outside the package tree: locate the checkout's
    backend/ (or honour MTG_BACKEND_DIR), as singleton_sweeper.py does."""
    import os

    configured = os.environ.get("MTG_BACKEND_DIR")
    if configured:
        backend = Path(configured).resolve()
        if (backend / "mtg_analyzer").is_dir():
            return backend
        sys.exit(f"MTG_BACKEND_DIR does not contain mtg_analyzer: {backend}")
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents, *Path(__file__).resolve().parents]:
        for cand in (parent, parent / "backend"):
            if (cand / "mtg_analyzer").is_dir():
                return cand
    sys.exit("backend/ not found; run from the checkout or set MTG_BACKEND_DIR")


BACKEND = _find_backend()
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))  # commander_tail_report helpers

from commander_tail_report import (  # noqa: E402
    _PROV,
    _is_wrapper_template,
    _claims_alone,
    _strip_mode_prefix,
)
from mtg_analyzer.game.card_registry import is_registered  # noqa: E402
from mtg_analyzer.parser.composition_diagnostics import CompositionProbe  # noqa: E402
from mtg_analyzer.parser.oracle.normalize import normalize  # noqa: E402
from mtg_analyzer.parser.oracle.segmenter import segment_line  # noqa: E402
from mtg_analyzer.parser.oracle import (  # noqa: E402
    NEVER_SUPPORTED,
    PARSER_VERSION,
    abstract_clause,
    parse_oracle,
)
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH  # noqa: E402
from mtg_analyzer.services.coverage_db import commander_legal_names  # noqa: E402
from mtg_analyzer.services.raw_card_store import RawCardStore  # noqa: E402

#: A template must occur on at least this many cards to enter the greedy walk.
MIN_SHARED_CARDS = 2

#: Sentence boundary inside one ability paragraph: terminal punctuation, then a
#: lowercase letter, digit, brace, sign, bullet or `~` (the normalised card
#: name). Oracle text is lowercased and name-normalised before this point, so
#: a capital never starts a sentence here; splitting only on these starts keeps
#: costs like "{t}: add {g}." and "1—9 | ..." table rows intact.
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+(?=[a-z0-9{+−•~\-])")

_CLAIM_CACHE: dict[str, bool] = {}


def split_sentences(clause: str) -> list[str]:
    return [part.strip() for part in SENTENCE_BOUNDARY_RE.split(clause.strip()) if part.strip()]


def claims_alone(text: str) -> bool:
    """True if the segmenter claims `text` as a stand-alone line."""
    text = text.strip()
    if text not in _CLAIM_CACHE:
        try:
            line = text if text.endswith((".", "!", "?")) else text + "."
            _CLAIM_CACHE[text] = bool(text) and segment_line(
                line, allow_spell_effect=True, provenance=_PROV).claimed
        except Exception:  # a probe must not abort the whole scan
            _CLAIM_CACHE[text] = False
    return _CLAIM_CACHE[text]


def sentence_fragments(clause: str) -> list[dict]:
    """The sentences of `clause` the segmenter cannot claim on their own.

    Each carries the previous sentence and whether the pair claims together:
    a gap that closes with its predecessor is a cross-sentence reference
    ("it", "the rest", "the copy"), not a missing phrase. A clause whose
    sentences all claim alone fails only as a whole and stays one fragment.
    """
    sentences = split_sentences(clause)
    if len(sentences) < 2:
        return [{"sentence": clause, "sentence_index": 0, "sentences": 1,
                 "previous_sentence": None, "claims_with_previous": None}]
    bad = []
    for index, sentence in enumerate(sentences):
        if claims_alone(sentence):
            continue
        previous = sentences[index - 1] if index else None
        bad.append({"sentence": sentence, "sentence_index": index, "sentences": len(sentences),
                    "previous_sentence": previous,
                    "claims_with_previous": (claims_alone(previous) and claims_alone(f"{previous} {sentence}"))
                    if previous else None})
    return bad or [{"sentence": clause, "sentence_index": 0, "sentences": len(sentences),
                    "previous_sentence": None, "claims_with_previous": None}]


#: n-gram window over abstracted sentence templates; shorter is noise
#: ("of the"), longer rarely repeats across cards.
NGRAM_MIN, NGRAM_MAX = 3, 7
#: A phrase needs this many open cards to be reported at all.
NGRAM_MIN_OPEN_CARDS = 8
#: Share of the cards containing a phrase that are still open. Below this the
#: phrase is common in text the parser already handles, so it is not the blocker.
NGRAM_MIN_OPEN_SHARE = 0.6
#: A longer phrase hides a shorter one it contains when it keeps this share of
#: the shorter phrase's open cards (otherwise every sub-phrase is listed too).
NGRAM_SUBSUME_SHARE = 0.9

_NGRAM_TOKEN_RE = re.compile(r"<\w+>|[\w'{}/+−-]+|[,:;—]")


def ngrams(template: str) -> set[str]:
    words = _NGRAM_TOKEN_RE.findall(template.lower())
    found: set[str] = set()
    for n in range(NGRAM_MIN, NGRAM_MAX + 1):
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            if gram[0] in ",:;—" or gram[-1] in ",:;—":
                continue
            found.add(" ".join(gram))
    return found


def rank_ngrams(rows: list[dict], pool_cards) -> list[dict]:
    """Phrases that stay mostly *open* across the whole Commander pool.

    `open_share` = open cards with the phrase / all pool cards with it. The
    pool side is normalised exactly like the parser input (`normalize`), else
    "this creature" vs `~` makes every phrase look 100% open. `only_cards` is
    an upper bound on unlocks: cards whose every open sentence has the phrase.
    """
    open_cards: dict[str, set[str]] = defaultdict(set)
    sentences: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        sentences[row["card"]].append(row["template"].lower())
        for gram in ngrams(row["template"]):
            open_cards[gram].add(row["card"])
    candidates = {g for g, cards in open_cards.items() if len(cards) >= NGRAM_MIN_OPEN_CARDS}
    pool: dict[str, set[str]] = defaultdict(set)
    for card in pool_cards:
        text = normalize(card.oracle_text or "", card.name, getattr(card, "keywords", None) or [])
        for line in text.lower().split("\n"):
            for sentence in SENTENCE_BOUNDARY_RE.split(line):
                for gram in ngrams(abstract_clause(sentence)) & candidates:
                    pool[gram].add(card.name)
    ranked = []
    for gram in candidates:
        n_open = len(open_cards[gram])
        share = n_open / max(len(pool[gram]), n_open)
        if share < NGRAM_MIN_OPEN_SHARE:
            continue
        only = sum(1 for c in open_cards[gram] if all(gram in t for t in sentences[c]))
        ranked.append({"phrase": gram, "open_cards": n_open, "open_share": round(share, 2),
                       "only_cards": only})
    ranked.sort(key=lambda r: (-r["open_cards"] * r["open_share"], -len(r["phrase"])))
    kept: list[dict] = []
    for r in ranked:
        if any(r["phrase"] in k["phrase"] and k["open_cards"] >= r["open_cards"] * NGRAM_SUBSUME_SHARE
               for k in kept):
            continue
        kept.append(r)
    return kept


#: Sentences tried per phrase in the ablation; a sample is enough to tell a
#: removable modifier (most remainders claim) from a core construct (none do).
ABLATION_SAMPLE = 40

_ABLATION_TOKENS = {
    "<n>": r"[\dxX+−-]+",
    "<name>": r"\S+",
    "<cost>": r"(?:\{[^}]+\})+",
}


def phrase_regex(phrase: str) -> re.Pattern[str]:
    """Raw-sentence regex for an abstracted n-gram (placeholders widened)."""
    parts = []
    for token in phrase.split(" "):
        parts.append(_ABLATION_TOKENS.get(token) or (rf"\b{re.escape(token)}\b" if token[0].isalnum() else re.escape(token)))
    return re.compile(r"\s*".join(parts), re.I)


def ablate(rows: list[dict], phrases: list[dict]) -> None:
    """Delete each phrase from the open sentences containing it and re-check.

    Adds `ablated` (sentences tried) and `remainder_claims` to each phrase.
    A high share means the phrase is a removable modifier that blocks the
    sentence; zero means it is a core construct that needs grammar, and
    deletion simply breaks the sentence (the probe is silent about the cause).
    """
    for entry in phrases:
        rx = phrase_regex(entry["phrase"])
        tried = claimed = 0
        for row in rows:
            if tried >= ABLATION_SAMPLE:
                break
            sentence = row["clause"]
            match = rx.search(sentence)
            if not match:
                continue
            rest = (sentence[:match.start()] + " " + sentence[match.end():]).strip(" ,;:")
            tried += 1
            claimed += int(bool(rest) and claims_alone(rest))
        entry["ablated"], entry["remainder_claims"] = tried, claimed


def write_ngrams(kept: list[dict], out_dir: Path, top: int, day: str) -> Path:
    path = out_dir / f"offene-fragmente-{day}-v{PARSER_VERSION}-phrasen.md"
    lines = [f"# Blocker-Phrasen — Parser {PARSER_VERSION} ({day})", "",
             "Phrase kommt überwiegend in offenen Karten vor (`share` = Anteil offener Karten "
             "an allen Karten mit der Phrase). `nur` = Karten, deren sämtliche offenen Sätze die "
             "Phrase enthalten (Obergrenze der Freischaltung, kein Kausalbeweis). "
             "`Rest claimt` (nur mit `--ablate`) = Sätze, die nach Entfernen der Phrase allein "
             "claimbar sind, von den geprüften: hoch = entfernbarer Modifikator-Blocker, "
             "0 = Kernkonstrukt, das eine Grammatik braucht.", "",
             "| Phrase | offen | share | nur | Rest claimt |", "| --- | ---: | ---: | ---: | ---: |"]
    lines += [f"| `{r['phrase']}` | {r['open_cards']} | {r['open_share']} | {r['only_cards']} | "
              + (f"{r['remainder_claims']}/{r['ablated']}" if "ablated" in r else "–") + " |"
              for r in kept[:top]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


DEFAULT_OUT_DIR = BACKEND / "data" / "exports"


def collect_fragments(cards) -> tuple[list[dict], list[str], dict[str, int]]:
    """Return (fragment rows, re-measure card names, totals) for open cards."""
    probe = CompositionProbe(_PROV)
    rows: list[dict] = []
    remeasure: list[str] = []
    totals = {"pool": 0, "covered": 0, "never_supported": 0, "open": 0}
    for card in cards:
        totals["pool"] += 1
        name = getattr(card, "name", "") or ""
        type_line = getattr(card, "type_line", "") or ""
        result = parse_oracle(card)
        # RULE 123.2: Sticker inserts are never playable cards.
        sticker = type_line.strip().casefold() == "stickers"
        if sticker or result.coverage == NEVER_SUPPORTED:
            totals["never_supported"] += 1
            continue
        if result.modeled or is_registered(name):
            totals["covered"] += 1
            continue
        totals["open"] += 1
        found = False
        for clause in (c.strip() for c in result.unclaimed if c.strip()):
            body = _strip_mode_prefix(clause)
            template = abstract_clause(body)
            if _is_wrapper_template(template):
                continue
            if body != clause and _claims_alone(body, card):
                continue
            found = True
            for frag in sentence_fragments(body):
                text = frag["sentence"]
                row = {"card": name, "type_line": type_line, "clause": text,
                       "parent_clause": body, "template": abstract_clause(text),
                       "kind": None, "head": None, "head_template": None, "body_template": None,
                       **{k: v for k, v in frag.items() if k != "sentence"}}
                diagnosis = probe.split(text.lower())
                if diagnosis is not None:
                    kind, head, rest, head_ok, body_ok = diagnosis
                    row.update(kind=kind, head=head, head_ok=head_ok, body_ok=body_ok,
                               head_template=abstract_clause(head) if head else None,
                               body_template=abstract_clause(rest) if rest else None)
                rows.append(row)
        if not found:
            remeasure.append(name)
    return rows, remeasure, totals


def rank_templates(rows: list[dict], key: str = "template") -> list[dict]:
    """Rank templates by solo unlocks, then greedy marginal unlocks."""
    card_keys: dict[str, set[str]] = defaultdict(set)
    key_cards: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        k = row.get(key)
        if not k:
            continue
        card_keys[row["card"]].add(k)
        key_cards[k].add(row["card"])
        if len(examples[k]) < 3 and row["clause"] not in examples[k]:
            examples[k].append(row["clause"])
    # Cards with a clause that lacks this axis can never be unlocked by it.
    all_cards: dict[str, int] = Counter(r["card"] for r in rows)
    keyed_counts: dict[str, int] = Counter()
    for r in rows:
        if r.get(key):
            keyed_counts[r["card"]] += 1
    solo = {k: sorted(c for c in cards if card_keys[c] == {k} and keyed_counts[c] == all_cards[c])
            for k, cards in key_cards.items()}

    picked: list[dict] = []
    unlocked: set[str] = set()
    chosen: set[str] = set()
    # Greedy walk only over templates shared by >= 2 cards: a one-card template
    # unlocks exactly that card and goes to the tail. Walking all ~10k
    # templates is quadratic and took >15 min on the full pool.
    remaining = {k for k, v in key_cards.items() if len(v) >= MIN_SHARED_CARDS}
    while remaining:
        def gain(k: str) -> int:
            return sum(1 for c in key_cards[k] - unlocked
                       if keyed_counts[c] == all_cards[c] and card_keys[c] <= chosen | {k})
        best = max(remaining, key=lambda k: (gain(k), len(key_cards[k]), k))
        g = gain(best)
        if g == 0:
            break
        chosen.add(best)
        remaining.discard(best)
        newly = sorted(c for c in key_cards[best] - unlocked
                       if keyed_counts[c] == all_cards[c] and card_keys[c] <= chosen)
        unlocked.update(newly)
        picked.append({"template": best, "marginal": len(newly), "solo": len(solo[best]),
                       "cards_touched": len(key_cards[best]),
                       "unlock_examples": newly[:5], "clause_examples": examples[best]})
    # Templates that unlock nothing alone or in the greedy walk: rank by reach.
    tail = [{"template": k, "marginal": 0, "solo": len(solo[k]), "cards_touched": len(v),
             "unlock_examples": [], "clause_examples": examples[k]}
            for k, v in sorted(key_cards.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            if k not in {p["template"] for p in picked}]
    return picked + tail


def write_outputs(rows, remeasure, totals, out_dir: Path, top: int, samples: int, day: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"offene-fragmente-{day}-v{PARSER_VERSION}"
    jsonl = out_dir / f"{stem}.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    by_template = rank_templates(rows, "template")
    by_body = rank_templates(rows, "body_template")
    by_head = Counter(r["head_template"] for r in rows if r.get("head_template"))
    cards_open = len({r["card"] for r in rows})
    lines = [
        f"# Offene Fragmente — Parser {PARSER_VERSION} ({day})",
        "",
        f"Pool {totals['pool']} | abgedeckt {totals['covered']} | permanent ausgeschlossen "
        f"{totals['never_supported']} | offen {totals['open']} "
        f"(davon {cards_open} mit echtem Fragment, {len(remeasure)} nur Wrapper/Re-measure).",
        f"Fragmente: {len(rows)} Sätze, {len({r['template'] for r in rows})} distinkte Templates.",
        "",
        "`marginal` = zusätzlich freigeschaltete Karten bei Greedy-Reihenfolge; "
        "`solo` = Karten, deren sämtliche offenen Klauseln nur dieses Template sind.",
        "",
        f"Sätze mit Vorgänger: {sum(1 for r in rows if r.get('claims_with_previous') is not None)}, "
        f"davon claimbar zusammen mit dem Vorgängersatz (Bezug über Satzgrenze): "
        f"{sum(1 for r in rows if r.get('claims_with_previous'))}.",
        "",
        "## Stufe 1: Templates nach Freischaltungen",
        "",
    ]
    for r in by_template[:top]:
        lines.append(f"- **{r['marginal']}** marginal / {r['solo']} solo / {r['cards_touched']} berührt — `{r['template']}`")
        for ex in r["clause_examples"][:samples]:
            lines.append(f"  - {ex}")
        if r["unlock_examples"]:
            lines.append(f"  - schaltet frei: {', '.join(r['unlock_examples'])}")
    lines += ["", "## Stufe 2a: Body-Templates (Trigger-/Kosten-Kopf abgetrennt)", ""]
    for r in by_body[:top]:
        lines.append(f"- **{r['marginal']}** marginal / {r['cards_touched']} berührt — `{r['template']}`")
        for ex in r["clause_examples"][:samples]:
            lines.append(f"  - {ex}")
    lines += ["", "## Stufe 2b: Köpfe (Trigger/Kosten), nach Häufigkeit", ""]
    for head, n in by_head.most_common(top):
        lines.append(f"- {n} — `{head}`")
    lines += ["", "## Nur Wrapper / Re-measure", "", ", ".join(sorted(remeasure)) or "(keine)"]
    md = out_dir / f"{stem}-gruppen.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonl, md


def commander_legal_names_cached() -> set[str]:
    with RawCardStore() as raw_store:
        return set(commander_legal_names(raw_store))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--top", type=int, default=80)
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ngrams", action="store_true",
                    help="also rank blocker phrases (needs the card cache for the pool baseline)")
    ap.add_argument("--ablate", action="store_true",
                    help="with --ngrams: delete each top phrase from its sentences and re-check the remainder")
    ap.add_argument("--from-jsonl", type=Path, default=None,
                    help="skip the scan; regroup an existing fragments JSONL")
    args = ap.parse_args()
    if args.from_jsonl:
        rows = [json.loads(line) for line in args.from_jsonl.read_text(encoding="utf-8").splitlines()]
        remeasure, totals = [], {"pool": 0, "covered": 0, "never_supported": 0, "open": len({r["card"] for r in rows})}
    else:
        cards = CardDatabase(args.card_db).list_cards()
        with RawCardStore() as raw_store:
            legal = commander_legal_names(raw_store)
        cards = [c for c in cards if c.name in legal]
        if args.limit is not None:
            cards = cards[:args.limit]
        rows, remeasure, totals = collect_fragments(cards)
    day = date.today().isoformat()
    if args.ngrams or args.ablate:
        legal_names = commander_legal_names_cached()
        pool = [c for c in CardDatabase(args.card_db).list_cards() if c.name in legal_names]
        phrases = rank_ngrams(rows, pool)
        if args.ablate:
            ablate(rows, phrases[:args.top])
        print(f"phrases -> {write_ngrams(phrases, args.out_dir, args.top, day)}")
    jsonl, md = write_outputs(rows, remeasure, totals, args.out_dir, args.top, args.samples, day)
    print(f"PARSER_VERSION {PARSER_VERSION}: {totals}")
    print(f"{len(rows)} fragments -> {jsonl}\nsummary -> {md}")


if __name__ == "__main__":
    main()
