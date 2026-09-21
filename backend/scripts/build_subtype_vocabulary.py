"""Regenerate ``parser/oracle/catalogue/subtype_vocabulary.py``.

Every subtype the oracle-text parser may name in a trigger head or a spell phrase
("a Wizard spell", "another Elf enters") comes from two authoritative sources
instead of a hand-kept list: the printed type lines of the seeded card cache (the
words after the em dash) and the Comprehensive Rules' own lists (rules 205.3g-q),
which also carry the token-only subtypes no card prints (Blood, Powerstone, …).
Run it after ``update_card_pool.py`` brings in a new set or the rules change::

    python scripts/build_subtype_vocabulary.py            # rewrite the module
    python scripts/build_subtype_vocabulary.py --check    # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH  # noqa: E402

RULES_DIR = BACKEND.parent / "docs" / "Reference"

#: The CR rules that list a card type's subtypes (205.3n planes and 205.3p the
#: single dungeon type are omitted: no trigger names them).
SUBTYPE_RULE = re.compile(r"^205\.3[ghijkmq] .*?\btypes? (?:are|is)\b[: ]*(?P<list>.+)$")
_SEE_RULE = re.compile(r"\s*\(see rule [^)]*\)")

TARGET = BACKEND / "mtg_analyzer" / "parser" / "oracle" / "catalogue" / "subtype_vocabulary.py"

#: Words after the em dash that are not subtypes of the card ("Time Lord" is two
#: words but one subtype, which is why splitting on spaces is wrong for those).
MULTI_WORD_SUBTYPES = frozenset({"time lord"})


def collect_subtypes(db_path: Path) -> list[str]:
    found: set[str] = set()
    for card in CardDatabase(db_path).list_cards():
        # A double-faced card joins its faces' type lines with " // ".
        for face in str(card.type_line or "").split("//"):
            _, dash, tail = face.partition("—")
            if not dash:
                continue
            words = tail.strip().lower()
            for multi in MULTI_WORD_SUBTYPES:
                if multi in words:
                    found.add(multi)
                    words = words.replace(multi, " ")
            found.update(w for w in words.split() if w.isalpha())
    return sorted(found)


def rules_subtypes(rules_dir: Path = RULES_DIR) -> list[str]:
    """Every subtype named in CR 205.3g-q of the newest rules text under ``rules_dir``."""
    files = sorted(rules_dir.glob("MagicCompRules*.txt"))
    if not files:
        return []
    found: set[str] = set()
    for line in files[-1].read_text(encoding="utf-8", errors="replace").splitlines():
        m = SUBTYPE_RULE.match(line)
        if m is None:
            continue
        listing = _SEE_RULE.sub("", m.group("list")).rstrip(". ")
        listing = re.sub(r"^.*?\b(?:are|is)\b[: ]*", "", listing) if ": " in listing else listing
        for name in re.split(r",\s*(?:and\s+)?|\s+and\s+", listing):
            name = name.strip().lower()
            if name and re.fullmatch(r"[a-z]+(?:[- ][a-z]+)?", name):
                found.add(name)
    return sorted(found)


def render(subtypes: list[str]) -> str:
    lines = [
        '"""Every card subtype: those printed in the seeded card cache plus the',
        "Comprehensive Rules' own lists, rules 205.3g-q (generated).",
        "",
        "Regenerate with ``python scripts/build_subtype_vocabulary.py`` — do not edit",
        "by hand. A phrase naming a word that is not here fails closed; it is never",
        "guessed to be a subtype. Pure data — no ``game/`` imports.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "SUBTYPES: frozenset[str] = frozenset({",
    ]
    lines += [f'    "{s}",' for s in subtypes]
    lines += ["})", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--check", action="store_true", help="exit 1 if the module is out of date")
    args = parser.parse_args()
    rendered = render(sorted(set(collect_subtypes(args.card_db)) | set(rules_subtypes())))
    if args.check:
        return 0 if TARGET.exists() and TARGET.read_text() == rendered else 1
    TARGET.write_text(rendered)
    print(f"wrote {TARGET.relative_to(BACKEND)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
