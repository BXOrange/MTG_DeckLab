#!/usr/bin/env python3
"""ENG-34 — re-derive the atom inventory's two measurements, read-only.

Design: [docs/concepts/14_PARSER_GRAMMAR_DESIGN.md] S0. This script is the
measuring half of `mtg_analyzer/game/isa.py`; the module holds the
classification, this holds the evidence that the classification is against
the right instruction set.

Two reports:

**`--corpus`** reproduces `13_` §5.6(b): decompose every unclaimed clause in
the coverage ledger on its connectives into atoms, take each atom's leading
operation verb, and rank the operations by how much corpus mass they carry.
`13_` measured 130 distinct operations with the top 50 covering 94.9%. The
point of re-deriving it here is ENG-34's exit criterion — *every top-50
corpus operation has a named instruction with a frame* — which this prints
as a pass/fail table rather than leaving as an assertion in prose.

**`--registry`** reports the classification itself: how the registered
effect types distribute across instruction / continuation / fusion / alias /
special (plus the two out-of-stream labels `14_` §1.1 carves out), which
instructions the aliases pile onto, and — for ENG-37 — which fusions each
composition operator retires.

Read-only: opens the ledger with ``mode=ro`` and writes nothing.

Usage (from backend/, venv interpreter required — `httpx2` is a real pinned
dependency absent from system Python; `PYTHONIOENCODING=utf-8` on Windows):

    ./venv_win/Scripts/python.exe scripts/isa_report.py --registry
    ./venv_win/Scripts/python.exe scripts/isa_report.py --corpus --top 50
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from mtg_analyzer.game import isa  # noqa: E402 (path must be set first)

#: The parser version `13_` measured and `14_`'s figures are quoted against.
#: Overridable with --parser-version when the ledger has moved on.
DEFAULT_PARSER_VERSION = "298"

#: Connectives an atom-level decomposition splits on — `13_` §5.2's measured
#: list. Splitting here is what turns a whole clause into the atoms whose
#: operation verb is being counted.
_CONNECTIVE_RE = re.compile(
    r"\s*(?:,\s*then\b|\bthen\b|\band then\b|\.\s+|;\s*|\band\b|\bor\b)\s*",
    re.I,
)

#: Surface verb -> ISA instruction. Hand-written from the Comprehensive
#: Rules the same way `13_` §5.6(b)'s 149-word vocabulary was — *not* read
#: off the corpus, so "does this operation exist in the ISA" stays an
#: honest question rather than a tautology. Inflections are generated
#: (`_verb_forms`), so each row is the bare stem.
_VERB_TO_INSTRUCTION: dict[str, str] = {
    # RULE 701 keyword actions
    "activate": "activate", "attach": "attach", "behold": "behold",
    "cast": "cast", "counter": "counter", "create": "create",
    "destroy": "destroy", "discard": "discard", "double": "double",
    "triple": "triple", "exchange": "exchange", "exile": "exile",
    "fight": "fight", "goad": "goad", "investigate": "investigate",
    "mill": "mill", "play": "play", "regenerate": "regenerate",
    "reveal": "reveal", "sacrifice": "sacrifice", "scry": "scry",
    "search": "search", "shuffle": "shuffle", "surveil": "surveil",
    "tap": "tap", "untap": "untap", "transform": "transform",
    "convert": "convert", "fateseal": "fateseal", "clash": "clash",
    "planeswalk": "planeswalk", "abandon": "abandon",
    "proliferate": "proliferate", "detain": "detain", "populate": "populate",
    "vote": "vote", "bolster": "bolster", "manifest": "manifest",
    "support": "support", "meld": "meld", "exert": "exert",
    "explore": "explore", "assemble": "assemble", "adapt": "adapt",
    "amass": "amass", "learn": "learn", "venture": "venture",
    "connive": "connive", "incubate": "incubate", "discover": "discover",
    "cloak": "cloak", "suspect": "suspect", "forage": "forage",
    "endure": "endure", "harness": "harness", "airbend": "airbend",
    "earthbend": "earthbend", "waterbend": "waterbend", "blight": "blight",
    "heal": "heal", "recruit": "recruit", "monstrosity": "monstrosity",
    # the operations the rules use without naming as keyword actions
    "draw": "draw", "gain": "gain_life", "lose": "lose_life",
    "put": "put_counter", "remove": "remove_counter", "move": "move_counter",
    "add": "add_mana", "pay": "pay_cost", "return": "move_object",
    "copy": "copy_object", "flip": "flip_coin", "roll": "roll_die",
    "win": "win_game", "take": "take_extra_turn", "skip": "skip_step",
    "choose": "choose", "prevent": "prevent_damage",
    "redirect": "redirect_damage", "set": "set_life",
    "deal": "deal_damage", "damage": "deal_damage",
    "gains": "create_continuous_effect", "get": "create_continuous_effect",
    "become": "create_continuous_effect", "have": "create_continuous_effect",
    "target": "choose", "look": "reveal", "phase": "phase_out",
    "mutate": "mutate", "imprint": "imprint", "end": "end_the_turn",
    "control": "gain_control", "untaps": "untap",
}


def _verb_forms(stem: str) -> tuple[str, ...]:
    """The surface inflections a clause writes a bare verb stem as.

    Oracle text is written in second person present ("draw a card") and
    third person ("that player draws a card"), so a stem has to match both,
    plus the -es/-ies spellings.
    """
    forms = {stem, stem + "s", stem + "es", stem + "ed", stem + "ing"}
    if stem.endswith("y"):
        forms.add(stem[:-1] + "ies")
    if stem.endswith("e"):
        forms.add(stem + "d")
        forms.add(stem[:-1] + "ing")
    return tuple(sorted(forms))


#: Inflected surface form -> instruction, built once from the stem table.
_FORM_TO_INSTRUCTION: dict[str, str] = {
    form: instruction
    for stem, instruction in _VERB_TO_INSTRUCTION.items()
    for form in _verb_forms(stem)
}

_WORD_RE = re.compile(r"[a-z']+")


def _operation_of(atom: str) -> str | None:
    """The ISA instruction an atom invokes, by its leading known verb.

    Scans left to right and takes the first word that is a known operation
    form, which skips the subject ("target player draws") without needing
    to parse it.
    """
    for word in _WORD_RE.findall(atom.lower()):
        instruction = _FORM_TO_INSTRUCTION.get(word)
        if instruction:
            return instruction
    return None


def _unclaimed_clauses(db_path: Path, parser_version: str) -> list[str]:
    """Every unclaimed clause the ledger recorded at ``parser_version``."""
    import json

    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = db.execute(
            "SELECT unclaimed FROM card_coverage WHERE parser_version = ?",
            (parser_version,),
        ).fetchall()
    finally:
        db.close()
    clauses: list[str] = []
    for (raw,) in rows:
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            clauses.extend(str(c) for c in parsed if c)
    return clauses


def report_corpus(parser_version: str, top: int) -> int:
    """`13_` §5.6(b), re-derived, checked against the ISA. Returns exit code."""
    from mtg_analyzer.services.coverage_db import DEFAULT_COVERAGE_DB_PATH

    db_path = Path(DEFAULT_COVERAGE_DB_PATH)
    if not db_path.exists():
        print(f"coverage ledger not found at {db_path}", file=sys.stderr)
        return 2

    clauses = _unclaimed_clauses(db_path, parser_version)
    if not clauses:
        print(
            f"no unclaimed clauses recorded at parser_version={parser_version!r}; "
            f"re-run scripts/coverage_report.py or pass --parser-version",
            file=sys.stderr,
        )
        return 2

    atoms: list[str] = []
    for clause in clauses:
        atoms.extend(a for a in _CONNECTIVE_RE.split(clause) if a and a.strip())

    counts: Counter[str] = Counter()
    uncovered = 0
    for atom in atoms:
        operation = _operation_of(atom)
        if operation is None:
            uncovered += 1
        else:
            counts[operation] += 1

    covered = sum(counts.values())
    ranked = counts.most_common()
    head = ranked[:top]
    head_mass = sum(n for _, n in head)

    print(f"corpus atoms      : {len(atoms):,} (from {len(clauses):,} unclaimed clauses)")
    print(f"atoms invoking a known operation: {covered:,} ({covered / len(atoms):.1%})")
    print(f"distinct operations occurring   : {len(ranked)}")
    if covered:
        print(f"top {top} share of covered atoms : {head_mass / covered:.1%}")
    print()
    print(f"{'#':>3}  {'operation':<28} {'atoms':>8}  {'share':>7}  ISA")
    missing: list[str] = []
    for index, (operation, n) in enumerate(head, start=1):
        instruction = isa.INSTRUCTIONS.get(operation)
        if instruction is None:
            verdict = "MISSING"
            missing.append(operation)
        elif not instruction.frame:
            verdict = "no frame"
            missing.append(operation)
        else:
            verdict = f"RULE {instruction.rule}  ({', '.join(instruction.frame)})"
        print(f"{index:>3}  {operation:<28} {n:>8,}  {n / covered:>6.1%}  {verdict}")

    print()
    if missing:
        print(f"FAIL — {len(missing)} of the top {top} operations lack a framed "
              f"instruction: {', '.join(missing)}")
        return 1
    print(f"PASS — all {len(head)} top operations have a named instruction with a frame.")
    return 0


def report_registry() -> int:
    """The classification itself: totals, alias pile-up, per-operator fusions."""
    from mtg_analyzer.game.effects import EffectRegistry

    registered = set(EffectRegistry._factories)
    classified = set(isa.EFFECT_TYPES)

    print(f"registered effect types : {len(registered)}")
    print(f"classified              : {len(classified)}")
    unclassified = sorted(registered - classified)
    stale = sorted(classified - registered)
    if unclassified:
        print(f"  UNCLASSIFIED ({len(unclassified)}): {', '.join(unclassified)}")
    if stale:
        print(f"  STALE ({len(stale)}): {', '.join(stale)}")
    print()

    counts = Counter(e.classification.value for e in isa.EFFECT_TYPES.values())
    width = max(len(k) for k in counts)
    for label, n in counts.most_common():
        print(f"  {label:<{width}}  {n:>4}  ({n / len(classified):>5.1%})")
    print()

    print(f"ISA instructions declared: {len(isa.INSTRUCTIONS)}")
    print()
    print("types collapsing onto each instruction (top 20) — axis 1 x axis 2:")
    for name, n in list(isa.instruction_histogram().items())[:20]:
        print(f"  {name:<28} {n:>4}")
    print()

    print("ENG-37 — fusions each composition operator retires:")
    for operator in isa.OPERATORS:
        retired = isa.fusions_retired_by(operator)
        print(f"  {operator:<10} {len(retired):>3}")
        if not retired:
            print(f"    ^ UNJUSTIFIED: 14_ S0c requires an operator to name "
                  f"the fusions it retires")
    print()
    print(f"ENG-35 — continuation types to retire onto one primitive: "
          f"{len(isa.types_classified(isa.Classification.CONTINUATION))}")
    print(f"ENG-37 — fusion types to delete: "
          f"{len(isa.types_classified(isa.Classification.FUSION))}")
    print(f"residue — one-card specials: "
          f"{len(isa.types_classified(isa.Classification.SPECIAL))}")
    return 0 if not unclassified and not stale else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", action="store_true",
                        help="re-derive 13_ 5.6(b)'s operation ranking and "
                             "check the top N against the ISA")
    parser.add_argument("--registry", action="store_true",
                        help="report the effect-type classification")
    parser.add_argument("--top", type=int, default=50,
                        help="how many operations the corpus check covers "
                             "(default 50, ENG-34's exit criterion)")
    parser.add_argument("--parser-version", default=DEFAULT_PARSER_VERSION,
                        help=f"ledger parser_version to read "
                             f"(default {DEFAULT_PARSER_VERSION})")
    args = parser.parse_args()

    if not args.corpus and not args.registry:
        args.registry = True

    status = 0
    if args.registry:
        status |= report_registry()
    if args.corpus:
        if args.registry:
            print("\n" + "=" * 70 + "\n")
        status |= report_corpus(args.parser_version, args.top)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
