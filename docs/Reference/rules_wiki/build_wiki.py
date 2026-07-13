#!/usr/bin/env python3
"""Generate an LLM-navigable wiki/index for the Magic Comprehensive Rules.

The Comprehensive Rules text (``Reference/MagicCompRules <date>.txt``) is ~975 KB /
9k+ lines — far too large to load into an LLM context in one go. The codebase
references rules everywhere as ``RULE <n>`` (e.g. ``RULE 613.7``). This script does
**not** duplicate the rules text; it builds a compact navigation layer that maps
every rule/subrule number and every glossary term to its exact line in the source
file, so an agent can ``Read(source, offset=line, limit=...)`` precisely.

Regenerate after dropping in a newer rules file (they update ~quarterly):

    python3 docs/Reference/rules_wiki/build_wiki.py

It auto-detects the newest ``MagicCompRules*.txt`` in ``Reference/``.

Outputs (all in ``docs/Reference/rules_wiki/``):
    rule_line_index.json  machine-readable: parts, sections, subrules, glossary -> line
    RULES_WIKI.md         master index: parts -> sections, each with source line
    glossary_index.md     glossary term -> source line + cross-referenced rule
    README.md             how to use the wiki + engine concept -> rule map
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCE_DIR = os.path.dirname(HERE)

PART_RE = re.compile(r"^([1-9])\.\s+(.+?)\s*$")
SECTION_RE = re.compile(r"^(\d{3})\.\s+(.+?)\s*$")
# subrules: "100.1.", "704.5k", "702.64a" — capture the id token up to first space
SUBRULE_RE = re.compile(r"^(\d{3}\.\d+[a-z]?)\.?(?:\s|$)")
# a "See rule 701.33" cross-reference inside a glossary definition
XREF_RE = re.compile(r"[Ss]ee rule (\d{3}(?:\.\d+[a-z]?)?)")


def find_source() -> str:
    matches = sorted(glob.glob(os.path.join(REFERENCE_DIR, "MagicCompRules*.txt")))
    if not matches:
        raise SystemExit("No MagicCompRules*.txt found in Reference/")
    return matches[-1]


def parse(lines: list[str]) -> dict:
    """Walk the rules body once and record line numbers (1-indexed)."""
    # Locate the body: the second occurrence of the part-1 header ("1. Game
    # Concepts") — the first is the table of contents.
    body_start = None
    seen_toc = False
    for i, ln in enumerate(lines):
        if ln.strip() == "1. Game Concepts":
            if seen_toc:
                body_start = i
                break
            seen_toc = True
    if body_start is None:
        raise SystemExit("Could not locate rules body (part 1 header).")

    # Glossary header is the second "Glossary" line (first is in the TOC).
    glossary_start = None
    seen = 0
    for i, ln in enumerate(lines):
        if ln.strip() == "Glossary":
            seen += 1
            if seen == 2:
                glossary_start = i
                break

    credits_start = len(lines)
    for i in range(glossary_start or body_start, len(lines)):
        if lines[i].strip() == "Credits":
            credits_start = i

    rules_end = glossary_start if glossary_start is not None else credits_start

    parts: list[dict] = []
    sections: list[dict] = []
    subrules: dict[str, int] = {}
    current_part = None
    current_section = None

    for i in range(body_start, rules_end):
        raw = lines[i]
        line_no = i + 1  # 1-indexed to match Read's offset
        m = PART_RE.match(raw)
        if m:
            current_part = {"number": m.group(1), "title": m.group(2),
                            "line": line_no, "sections": []}
            parts.append(current_part)
            continue
        m = SECTION_RE.match(raw)
        if m:
            current_section = {"number": m.group(1), "title": m.group(2),
                               "line": line_no, "subrules": []}
            sections.append(current_section)
            if current_part is not None:
                current_part["sections"].append(current_section)
            continue
        m = SUBRULE_RE.match(raw)
        if m:
            rid = m.group(1)
            if rid not in subrules:  # keep the first (canonical) occurrence
                subrules[rid] = line_no
                if current_section is not None:
                    current_section["subrules"].append({"number": rid, "line": line_no})

    glossary = parse_glossary(lines, glossary_start, credits_start)
    return {
        "parts": parts,
        "sections": sections,
        "subrules": subrules,
        "glossary": glossary,
        "glossary_line": (glossary_start + 1) if glossary_start is not None else None,
    }


def parse_glossary(lines, start, end) -> list[dict]:
    if start is None:
        return []
    terms: list[dict] = []
    prev_blank = True
    for i in range(start + 1, end):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped:
            prev_blank = True
            continue
        is_term = (
            prev_blank
            and not re.match(r"^\d+\.", stripped)      # "1." numbered sense line
            and not stripped.startswith("See rule")
            and not stripped.startswith("See ")
        )
        if is_term:
            terms.append({"term": stripped, "line": i + 1, "xref": None})
        else:
            # attach the first rule cross-reference we see to the open term
            if terms and terms[-1]["xref"] is None:
                xm = XREF_RE.search(stripped)
                if xm:
                    terms[-1]["xref"] = xm.group(1)
        prev_blank = False
    return terms


# --- concept map: how THIS engine's subsystems map to the rules -----------------
# Hand-maintained bridge between the code (game/*.py) and the CR sections it
# implements. Keep in sync with CLAUDE.md "Where to look first".
CONCEPT_MAP = [
    ("Turn / phase / step loop", ["500", "501", "502", "503", "504", "505", "506",
                                  "512", "513", "514"], "game/game_engine.py"),
    ("Combat & combat keywords", ["506", "507", "508", "509", "510", "511", "702"],
     "game/combat.py, game/game_engine.py (_step_combat_damage)"),
    ("Casting spells / the stack", ["601", "608", "112", "405"],
     "game/rules_engine.py, services/game_session.py"),
    ("Activated abilities & costs", ["602", "118", "606"],
     "game/costs.py, game/game_engine.py (activate_ability)"),
    ("Triggered abilities", ["603"], "game/effects.py, game/effect_binder.py"),
    ("Static abilities / layers (P/T, anthems)", ["604", "611", "613"],
     "game/continuous.py, models/game_object.py"),
    ("Replacement & prevention effects", ["614", "615", "616"], "game/effects.py"),
    ("Mana", ["106", "107", "202", "605"],
     "game/mana_abilities.py, models/mana_cost.py, models/mana_pool.py"),
    ("Targeting", ["115", "601"], "game/targeting.py"),
    ("State-based actions", ["704"], "game/rules_engine.py (SBAs)"),
    ("Damage / life", ["119", "120"], "game/rules_engine.py"),
    ("Counters", ["122"], "game/rules_engine.py"),
    ("Zones", ["400", "401", "402", "403", "404", "405", "406"], "models/game_state.py"),
    ("Keyword actions & abilities", ["701", "702"], "game/combat.py, game/effects.py"),
    ("Commander", ["903"], "services/game_session.py"),
    ("Mulligan / starting the game", ["103"], "game/game_engine.py"),
]


def write_json(data: dict, src_name: str, out_path: str):
    payload = {
        "source_file": src_name,
        "generated": date.today().isoformat(),
        "how_to_use": (
            "Line numbers are 1-indexed into source_file and match the Read tool's "
            "'offset'. To read rule 613.7, look up '613.7' in 'subrules', then "
            "Read(source_file, offset=<line>, limit=~40)."
        ),
        "glossary_line": data["glossary_line"],
        "parts": [
            {"number": p["number"], "title": p["title"], "line": p["line"],
             "sections": [s["number"] for s in p["sections"]]}
            for p in data["parts"]
        ],
        "sections": {
            s["number"]: {"title": s["title"], "line": s["line"],
                          "subrules": {sr["number"]: sr["line"] for sr in s["subrules"]}}
            for s in data["sections"]
        },
        "subrules": data["subrules"],
        "glossary": {t["term"]: {"line": t["line"], "xref": t["xref"]}
                     for t in data["glossary"]},
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)


def src_link(src_name: str) -> str:
    """Relative markdown link target for the source txt (spaces url-encoded)."""
    return "../" + src_name.replace(" ", "%20")


def write_master(data: dict, src_name: str, out_path: str):
    src_rel = src_link(src_name)
    lines = [
        "# Comprehensive Rules — Master Index",
        "",
        f"> Auto-generated from `{src_name}` — do not edit by hand.",
        "> Regenerate with `python3 docs/Reference/rules_wiki/build_wiki.py`.",
        "",
        "Line numbers point into the source rules file and equal the `Read` tool's",
        "`offset`. Sections are short (~10–60 lines); read a whole section by its line.",
        "For a specific subrule, use `rule_line_index.json`.",
        "",
        f"**Source:** [`{src_name}`]({src_rel}) · "
        f"**Glossary starts at line {data['glossary_line']}** "
        "(see [glossary_index.md](glossary_index.md))",
        "",
        "| How to jump | Example |",
        "| --- | --- |",
        "| Whole section | look up `613` below → `Read(source, offset=<line>, limit=60)` |",
        "| One subrule | `rule_line_index.json` → `subrules[\"613.7\"]` → `Read(...)` |",
        "| A defined term | [glossary_index.md](glossary_index.md) → term → line |",
        "",
    ]
    for p in data["parts"]:
        lines.append(f"## {p['number']}. {p['title']}  ·  _line {p['line']}_")
        lines.append("")
        lines.append("| Rule | Title | Line | Subrules |")
        lines.append("| --- | --- | --- | --- |")
        for s in p["sections"]:
            n_sub = len(s["subrules"])
            lines.append(f"| **{s['number']}** | {s['title']} | {s['line']} | {n_sub} |")
        lines.append("")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_glossary(data: dict, src_name: str, out_path: str):
    src_rel = src_link(src_name)
    terms = data["glossary"]
    lines = [
        "# Comprehensive Rules — Glossary Index",
        "",
        f"> Auto-generated from `{src_name}`. {len(terms)} terms.",
        f"> Each line points into [`{src_name}`]({src_rel}) (= `Read` `offset`).",
        "",
        "| Term | Line | Rule |",
        "| --- | --- | --- |",
    ]
    for t in sorted(terms, key=lambda x: x["term"].lower()):
        xref = t["xref"] or ""
        term = t["term"].replace("|", "\\|")
        lines.append(f"| {term} | {t['line']} | {xref} |")
    lines.append("")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_readme(data: dict, src_name: str, out_path: str):
    section_title = {s["number"]: s["title"] for s in data["sections"]}
    lines = [
        "# Rules Wiki — LLM navigation layer for the Comprehensive Rules",
        "",
        f"The Magic Comprehensive Rules (`{src_name}`, ~975 KB) are too large to load",
        "whole. This directory is a **navigation layer**: it maps every rule number and",
        "glossary term to a line in that source file so an agent can read exactly the",
        "passage it needs. **The rules text is not copied here** — the source `.txt`",
        "stays the single source of truth.",
        "",
        "## Files",
        "",
        "| File | Use it to |",
        "| --- | --- |",
        "| [RULES_WIKI.md](RULES_WIKI.md) | Browse parts → sections; get a section's line. |",
        "| [glossary_index.md](glossary_index.md) | Look up a defined term → line + rule. |",
        "| `rule_line_index.json` | Machine-readable rule#/subrule#/term → line. |",
        "| `build_wiki.py` | Regenerate everything after a rules update. |",
        "",
        "## How an agent uses it",
        "",
        "1. Have a `RULE <n>` reference (e.g. from code)? Look it up:",
        "   - section like `613` → find its line in `RULES_WIKI.md`.",
        "   - subrule like `613.7` → `rule_line_index.json` → `subrules[\"613.7\"]`.",
        f"2. `Read(\"Reference/{src_name}\", offset=<line>, limit=~40)` — read just that rule.",
        "3. Unknown term? `glossary_index.md` gives its line **and** the rule that defines it.",
        "",
        "## Engine concept → rules map",
        "",
        "Bridges this repo's subsystems to the CR sections they implement",
        "(mirrors CLAUDE.md's \"Where to look first\").",
        "",
        "| Subsystem | Rules | Code |",
        "| --- | --- | --- |",
    ]
    for concept, rules, code in CONCEPT_MAP:
        rule_cells = ", ".join(
            f"{r} {section_title.get(r, '').split('(')[0]}".strip() for r in rules
        )
        lines.append(f"| {concept} | {rule_cells} | `{code}` |")
    lines += [
        "",
        "## Regenerating",
        "",
        "Drop the newer `MagicCompRules <date>.txt` into `Reference/` and run:",
        "",
        "```bash",
        "python3 docs/Reference/rules_wiki/build_wiki.py",
        "```",
        "",
        "It picks the newest `MagicCompRules*.txt` automatically. The concept map at",
        "the top of `build_wiki.py` is hand-maintained — update it when subsystems move.",
    ]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    src = find_source()
    src_name = os.path.basename(src)
    with open(src, encoding="utf-8") as f:
        lines = f.read().split("\n")
    data = parse(lines)

    write_json(data, src_name, os.path.join(HERE, "rule_line_index.json"))
    write_master(data, src_name, os.path.join(HERE, "RULES_WIKI.md"))
    write_glossary(data, src_name, os.path.join(HERE, "glossary_index.md"))
    write_readme(data, src_name, os.path.join(HERE, "README.md"))

    print(f"Source: {src_name}")
    print(f"  parts     : {len(data['parts'])}")
    print(f"  sections  : {len(data['sections'])}")
    print(f"  subrules  : {len(data['subrules'])}")
    print(f"  glossary  : {len(data['glossary'])} terms")
    print(f"Wrote wiki to {HERE}")


if __name__ == "__main__":
    main()
