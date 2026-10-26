#!/usr/bin/env python3
"""Verb x object-form claim matrix: where does the parser fail to generalise?

Builds one sentence per (verb template, object form) and records whether the
segmenter claims it stand-alone. A column that is empty for most verbs is an
object form the shared grammar lacks; a row that is empty for most objects is
a verb with no object grammar of its own. Some cells are not valid Magic text
("sacrifice target creature"); read the pattern, not single cells.

Usage (from backend/, venv active):
  python ../.claude/skills/find-fragments/scripts/generalization_matrix.py
"""

from __future__ import annotations

import sys
from pathlib import Path


def _find_backend() -> Path:
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents, *Path(__file__).resolve().parents]:
        for cand in (parent, parent / "backend"):
            if (cand / "mtg_analyzer").is_dir():
                return cand
    sys.exit("backend/ not found; run from the checkout")


sys.path.insert(0, str(_find_backend()))

from mtg_analyzer.parser.oracle.segmenter import segment_line  # noqa: E402
from mtg_analyzer.parser.oracle.spec import ParserProvenance  # noqa: E402
from mtg_analyzer.parser.oracle import PARSER_VERSION  # noqa: E402

_PROV = ParserProvenance(version=PARSER_VERSION, source="generalization_matrix")

OBJECT_FORMS = (
    "target creature", "target creature you control", "target creature an opponent controls",
    "up to two target creatures", "each creature", "all creatures", "each creature you control",
    "each creature your opponents control", "~", "it", "that creature", "them", "those creatures",
    "enchanted creature", "target nonland permanent", "target attacking creature",
)
VERB_TEMPLATES = (
    "destroy {}", "exile {}", "tap {}", "untap {}", "return {} to its owner's hand", "sacrifice {}",
    "gain control of {}", "{} gets +1/+1 until end of turn", "{} gains flying until end of turn",
    "{} can't block this turn", "put a +1/+1 counter on {}", "~ deals 2 damage to {}", "regenerate {}",
    "goad {}", "{} gains haste until end of turn", "{} fights target creature you don't control",
    "you may cast {} this turn", "put {} onto the battlefield", "{} loses all abilities",
    "{} becomes a 1/1 creature until end of turn", "prevent all damage that would be dealt to {} this turn",
)


def claims(text: str) -> bool:
    try:
        return segment_line(text, allow_spell_effect=True, provenance=_PROV).claimed
    except Exception:  # a probe must not abort on one odd sentence
        return False


def main() -> None:
    print(f"PARSER_VERSION {PARSER_VERSION}")
    print(f"{'':52s}" + " ".join(f"{i:2d}" for i in range(len(OBJECT_FORMS))))
    hits = cells = 0
    for verb in VERB_TEMPLATES:
        row = [claims(verb.format(obj) + ".") or claims("~ " + verb.format(obj) + ".") for obj in OBJECT_FORMS]
        hits, cells = hits + sum(row), cells + len(row)
        print(f"{verb[:50]:52s}" + " ".join(" X" if ok else " ." for ok in row))
    print()
    for i, obj in enumerate(OBJECT_FORMS):
        print(f"{i:2d} {obj}")
    print(f"\nclaimed {hits} of {cells} cells")


if __name__ == "__main__":
    main()
