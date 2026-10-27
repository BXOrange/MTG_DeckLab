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
    "{} can't be regenerated this turn", "{} loses all abilities and has base power and toughness 0/1 until end of turn",
)
CAST_FOLLOW_UPS = (
    ("exile target nonland permanent.", "you may cast the exiled card this turn."),
    ("exile target card from a graveyard.", "you may cast it this turn."),
    ("exile the top card of your library.", "you may play it this turn."),
    ("exile the top card of your library.", "if it's a goblin or an artifact card, you may play it this turn."),
    ("exile the top 2 cards of your library.", "you may play them this turn."),
    ("exile the top 2 cards of your library.", "if it's a land card, you may play it this turn."),  # not valid: 2 cards
    ("mill a card.", "you may play that card this turn."),  # open: needs graveyard play window (engine)
    ("reveal the top card of your library.", "you may cast that card this turn."),  # open: needs library cast
)
#: Pronoun object forms only mean something after an antecedent sentence, so they are probed as a two-sentence body
#: (PAR-214): singular pronouns follow a one-target pick, plural ones a two-target pick.
FOLLOW_UP_FORMS = (
    ("it", "tap target creature. "), ("that creature", "tap target creature. "),
    ("them", "tap 2 target creatures. "), ("those creatures", "tap 2 target creatures. "),
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
    print("\nfollow-up pronouns (after a tap clause that picked the referent)")
    for verb in VERB_TEMPLATES:
        row = []
        for obj, lead in FOLLOW_UP_FORMS:
            plural = obj in ("them", "those creatures")
            subject_form = verb.startswith("{}")
            word = {"them": "they"}.get(obj, obj) if subject_form else obj
            text = verb.format(word)
            if plural and subject_form:  # agreement: "they gain", "those creatures lose"
                text = text.replace(" gets ", " get ").replace(" gains ", " gain ").replace(" loses ", " lose ")
                text = text.replace(" becomes ", " become ")
            row.append(claims(lead + text + "."))
        hits, cells = hits + sum(row), cells + len(row)
        print(f"{verb[:50]:52s}" + " ".join(" X" if ok else " ." for ok in row))
    print("   cols: " + ", ".join(o for o, _ in FOLLOW_UP_FORMS))
    print("\ncasting windows after an exile clause (lead sentence | window sentence)")
    for lead, body in CAST_FOLLOW_UPS:
        ok = claims(lead + " " + body)
        hits, cells = hits + ok, cells + 1
        print(f"{' X' if ok else ' .'}  {lead} | {body}")
    print()
    for i, obj in enumerate(OBJECT_FORMS):
        print(f"{i:2d} {obj}")
    print(f"\nclaimed {hits} of {cells} cells")


if __name__ == "__main__":
    main()
