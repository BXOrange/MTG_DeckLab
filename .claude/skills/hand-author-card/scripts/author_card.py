#!/usr/bin/env python3
"""Speed up hand-authoring a card into `game/ability_catalogue/`.

The slow parts of hand-authoring aren't the rules — they're mechanical:
finding the card's real oracle text with real line breaks, checking whether
it's already registered, discovering that the parser already claims half the
card's clauses (so that half needs no hand-authoring at all, just copying),
and finding an existing catalogue entry with the same shape to adapt instead
of starting from a blank function (searched across every module in the
package, not just one file). This script does all four in one command each,
then a `scaffold` that assembles the result into a paste-ready factory
function + register() call + test skeleton.

It does NOT decide what a card's abilities mean, and it does not touch
ability_catalogue/ — every command only reads and prints. You still write
(or fix) the EffectSpec for whatever the parser didn't already claim; see
docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md for the field reference.

For "does this EffectSpec/replacement/static type already exist" and "does
the bound ability actually behave", use the game-engine skill's
engine_bench.py (`primitives`, `inspect`, `play`) instead of reinventing that
here — this script is scoped to the catalogue-entry workflow only.

Subcommands
  text        real oracle text (line breaks preserved) + parse verdict +
              unclaimed clauses + already-registered check
  reuse       print the parser's already-claimed specs as paste-ready
              AbilitySpec(...) Python source — copy instead of re-deriving
  scaffold    text + reuse + TODOs for unclaimed clauses + register() call +
              a matching pytest skeleton, all in one paste-ready block
  check       is this card already registered? print its existing source
              and every alias name it's registered under
  similar     find existing catalogue entries with the closest shape to a
              card or a raw text snippet, to adapt instead of write fresh

Usage (from backend/, venv active):
  AUTHOR=../.claude/skills/hand-author-card/scripts/author_card.py
  python $AUTHOR text "Fog"
  python $AUTHOR reuse "Bruna, the Fading Light"
  python $AUTHOR scaffold "Bruna, the Fading Light"
  python $AUTHOR check "Evolving Wilds"
  python $AUTHOR similar "Prevent all damage that would be dealt to ~ this turn."
"""

from __future__ import annotations

import argparse
import ast
import difflib
import inspect
import os
import re
import sys
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
sys.path.insert(0, str(BACKEND))

from mtg_analyzer.game import ability_catalogue as catalogue  # noqa: E402
from mtg_analyzer.models import Card, EventType  # noqa: E402
from mtg_analyzer.parser.oracle.gate import parse_oracle  # noqa: E402
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec  # noqa: E402
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH  # noqa: E402


# --- card lookup -------------------------------------------------------


def load_card(db: CardDatabase, name: str) -> Card:
    card = db.get_card(name)
    if card is not None:
        return card
    matches = db.search_cards(name, limit=10)
    print(f"no exact cache hit for {name!r}.", file=sys.stderr)
    if matches:
        print("did you mean:", file=sys.stderr)
        for c in matches:
            print(f"  {c.name}", file=sys.stderr)
    sys.exit(1)


def is_registered(name: str) -> bool:
    return catalogue.is_registered(name)


def _existing_factory(name: str):
    lowered = name.strip().lower()
    factory = catalogue._REGISTRY.get(lowered)  # noqa: SLF001 — dev tool, read-only
    if factory is None and "//" in lowered:
        factory = catalogue._REGISTRY.get(lowered.split("//")[0].strip())
    return factory


# --- Python-source rendering of AbilitySpec/EffectSpec ------------------

#: value -> symbolic name, so a trigger's "event" renders as EventType.X
#: (matching every hand-authored entry's own style) instead of a bare string.
_EVENT_NAMES = {
    value: attr
    for attr, value in vars(EventType).items()
    if not attr.startswith("_") and isinstance(value, str)
}


def _render_scalar(value, *, event_aware: bool = False) -> str:
    if event_aware and isinstance(value, str) and value in _EVENT_NAMES:
        return f"EventType.{_EVENT_NAMES[value]}"
    if event_aware and isinstance(value, list):
        return "[" + ", ".join(_render_scalar(v, event_aware=True) for v in value) + "]"
    return repr(value)


def _render_dict(d: dict | None, *, event_key: str | None = None) -> str:
    if not d:
        return "{}"
    parts = []
    for k, v in d.items():
        rendered_v = _render_scalar(v, event_aware=(event_key is not None and k == event_key))
        parts.append(f'"{k}": {rendered_v}')
    return "{" + ", ".join(parts) + "}"


def _render_effect(effect: EffectSpec) -> str:
    src = f"EffectSpec({effect.type!r}, {_render_dict(effect.params)}"
    if effect.condition:
        src += f", condition={_render_dict(effect.condition)}"
    return src + ")"


def _render_modes(modes: dict) -> str:
    options_src = ", ".join(
        "[" + ", ".join(_render_effect(e) for e in opt) + "]" for opt in modes.get("options", [])
    )
    parts = [
        f'"or_both": {bool(modes.get("or_both", False))!r}',
        f'"at_least": {bool(modes.get("at_least", False))!r}',
        f'"choose": {int(modes.get("choose", 1))!r}',
        f'"options": [{options_src}]',
    ]
    if modes.get("descriptions"):
        parts.append(f'"descriptions": {list(modes["descriptions"])!r}')
    if modes.get("entwine"):
        parts.append(f'"entwine": {modes["entwine"]!r}')
    return "{" + ", ".join(parts) + "}"


def render_ability(spec: AbilitySpec, indent: str = "    ") -> str:
    """Reconstruct `spec` as paste-ready Python source (an `AbilitySpec(...)` call).

    Only fields the parser front-end actually ever populates need rendering
    here (see spec.py — alt_cost/strive_cost/rebound/etc. are hand-authored-
    only and never come from `parse_oracle`), but every field is covered so
    this also works on a spec a previous scaffold run already hand-edited.
    """
    lines = ["AbilitySpec("]
    lines.append(f"{indent}{spec.ability_kind!r},")
    if spec.effects:
        lines.append(f"{indent}[{', '.join(_render_effect(e) for e in spec.effects)}],")
    else:
        lines.append(f"{indent}[],")
    if spec.trigger:
        lines.append(f"{indent}trigger={_render_dict(spec.trigger, event_key='event')},")
    if spec.cost:
        lines.append(f"{indent}cost={_render_dict(spec.cost)},")
    if spec.keyword:
        lines.append(f"{indent}keyword={_render_dict(spec.keyword)},")
    if spec.modes:
        lines.append(f"{indent}modes={_render_modes(spec.modes)},")
    if spec.additional_cost:
        lines.append(f"{indent}additional_cost={_render_dict(spec.additional_cost)},")
    if spec.conditional_flash:
        lines.append(f"{indent}conditional_flash={_render_dict(spec.conditional_flash)},")
    if spec.free_cast_condition:
        lines.append(f"{indent}free_cast_condition={_render_dict(spec.free_cast_condition)},")
    if spec.alt_cost:
        lines.append(f"{indent}alt_cost={_render_dict(spec.alt_cost)},")
    if spec.strive_cost:
        lines.append(f"{indent}strive_cost={spec.strive_cost!r},")
    if spec.optional:
        lines.append(f"{indent}optional=True,")
    lines.append(f"{indent}raw_text={spec.raw_text!r},")
    lines.append(")")
    return "\n".join(lines)


def _reindent(src: str, indent: str) -> str:
    body = src.split("\n")
    return "\n".join([indent + body[0]] + [indent + line for line in body[1:]])


def _factory_name(card_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", card_name.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug) or "card"
    return f"_{slug}"


# --- commands -------------------------------------------------------


def cmd_text(args) -> None:
    db = CardDatabase(args.card_db)
    card = load_card(db, args.name)
    result = parse_oracle(card)
    print(f"{card.name}")
    print(f"  type_line: {card.type_line}")
    print(f"  mana_cost: {card.mana_cost_string!r}  cmc={card.converted_mana_cost}")
    print(f"  registered in ability_catalogue.py: {is_registered(card.name)}")
    print(f"  parser coverage: {result.coverage}")
    print()
    print("oracle_text, as a Python literal (paste this into raw_text=/the docstring —")
    print("preserves Scryfall's line breaks, CLAUDE.md/the authoring guide §3 requires this):")
    print(f"  {card.oracle_text!r}")
    print()
    print(card.oracle_text or "(no oracle text — vanilla)")
    if result.unclaimed:
        print()
        print(f"unclaimed clauses ({len(result.unclaimed)}) — parser can't claim these, hand-author them:")
        for line in result.unclaimed:
            print(f"  - {line}")


def cmd_reuse(args) -> None:
    db = CardDatabase(args.card_db)
    card = load_card(db, args.name)
    result = parse_oracle(card)
    specs = result.effect_specs
    if not specs:
        print(f"# parser claimed no effect-bearing specs for {card.name!r} (coverage={result.coverage})")
    else:
        print(f"# parser-claimed specs for {card.name!r} (coverage={result.coverage}) — paste as-is")
        for spec in specs:
            print(render_ability(spec))
            print()
    if result.unclaimed:
        print(f"# still unclaimed ({len(result.unclaimed)}) — these need a hand-written AbilitySpec:")
        for line in result.unclaimed:
            print(f"#   - {line}")


def cmd_scaffold(args) -> None:
    db = CardDatabase(args.card_db)
    card = load_card(db, args.name)
    if is_registered(card.name):
        print(f"# {card.name!r} is already registered — not scaffolding over it. Use `check` instead.")
        _print_existing(card.name)
        return

    result = parse_oracle(card)
    fname = _factory_name(card.name)
    body_lines: list[str] = []
    for spec in result.effect_specs:
        body_lines.append(_reindent(render_ability(spec, indent="    "), "        ") + ",")
    for i, line in enumerate(result.unclaimed, 1):
        body_lines.append(f"        # TODO {i}/{len(result.unclaimed)} — parser did not claim this clause:")
        body_lines.append(f"        # {line!r}")
        body_lines.append(
            f'        # AbilitySpec("???", [EffectSpec("???", {{}})], raw_text={line!r}),'
        )
    if not body_lines:
        body_lines.append("        # TODO: no clauses at all reached here — check `text` output.")

    print(f"def {fname}() -> list[AbilitySpec]:")
    print(f"    {card.oracle_text!r}")
    print("    return [")
    for line in body_lines:
        print(line)
    print("    ]")
    print()
    print()
    print(f"register({card.name!r}, {fname})")
    print()
    print("# --- test skeleton (paste into backend/tests/game/catalogue/test_catalogue.py,")
    print("#     match its existing _card()/_object() fixture helpers) ---")
    kinds = [s.ability_kind for s in result.effect_specs]
    print(_test_skeleton(card.name, fname, kinds))
    if result.unclaimed:
        print(
            f"# {len(result.unclaimed)} clause(s) still need EffectSpecs written by hand — "
            "see docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md §5-§9 for the whitelist."
        )


#: ability_kind -> the GameObject list bind_from_catalogue/attach_to_object
#: files it onto (authoring guide §4's table).
_KIND_TO_ATTR = {
    "spell_effect": "spell_effects",
    "triggered": "triggered_abilities",
    "activated": "activated_abilities",
    "static": "static_effects",
    "replacement": "replacement_effects",
}


def _test_skeleton(card_name: str, fname: str, kinds: list[str]) -> str:
    var = re.sub(r"[^a-z0-9]+", "_", card_name.lower()).strip("_")
    attrs = sorted({_KIND_TO_ATTR[k] for k in kinds if k in _KIND_TO_ATTR})
    if attrs:
        bind_asserts = "\n    ".join(f"assert obj.{attr}  # TODO: assert the real expected content" for attr in attrs)
    else:
        bind_asserts = "assert obj.???  # TODO: no auto-detected kind — pick the right list yourself"
    kinds_literal = repr(kinds) if kinds else "[...]  # TODO: expected ability_kind(s), plus whatever you hand-add"
    return f'''
def test_{var}_specs():
    card = _card({card_name!r})  # TODO: match this file's fixture signature
    specs = ability_catalogue.specs_for(card)
    assert [s.ability_kind for s in specs] == {kinds_literal}

    other = ability_catalogue.specs_for(card)
    assert specs is not other and specs[0] is not other[0]  # fresh specs per call

    obj = _object(card)  # TODO: match this file's fixture signature
    bind_from_catalogue(obj)
    {bind_asserts}


def test_{var}_end_to_end():
    # TODO: build a real GameEngine (see engine_bench.py's `play`/`inspect` for
    # a quick look first), resolve the ability, assert the board actually
    # changed — not just "an object of the right class was constructed".
    ...
'''.strip("\n")


def cmd_check(args) -> None:
    _print_existing(args.name, must_exist=True)


def _print_existing(name: str, *, must_exist: bool = False) -> None:
    factory = _existing_factory(name)
    if factory is None:
        msg = f"{name!r} is not registered in ability_catalogue.py."
        if must_exist:
            sys.exit(msg)
        print(msg)
        return
    aliases = sorted(n for n, f in catalogue._REGISTRY.items() if f is factory)  # noqa: SLF001
    print(f"registered under: {', '.join(aliases)}")
    print()
    print(inspect.getsource(factory))


def cmd_similar(args) -> None:
    db = CardDatabase(args.card_db)
    query_text = args.query
    card = db.get_card(args.query)
    if card is not None and card.oracle_text:
        query_text = card.oracle_text
        print(f"# matching against {card.name}'s real oracle text")

    # `ability_catalogue` is a package (one module per card family, e.g.
    # black.py/commander_cards.py/...) — scan every module in it, not just
    # __init__.py, or almost every real factory function is invisible here.
    pkg_dir = Path(catalogue.__file__).parent

    docstrings: dict[str, str] = {}
    file_by_fn: dict[str, str] = {}
    names_by_fn: dict[str, list[str]] = {}
    for src_path in sorted(pkg_dir.glob("*.py")):
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
                doc = ast.get_docstring(node)
                if doc:
                    docstrings[node.name] = doc
                    file_by_fn[node.name] = src_path.name
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "register"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[1], ast.Name)
            ):
                names_by_fn.setdefault(node.args[1].id, []).append(node.args[0].value)

    # Docstring convention here is "<quoted oracle text>\n\n— Card Name. <design
    # commentary>" (see any entry `check` prints) — score against the oracle-text
    # preview only, or a long commentary tail swamps the ratio for every card
    # whose comment happens to be verbose.
    scored = []
    for fn, doc in docstrings.items():
        preview = doc.split("\n\n", 1)[0]
        ratio = difflib.SequenceMatcher(None, query_text.lower(), preview.lower()).ratio()
        scored.append((ratio, fn, preview))
    scored.sort(key=lambda t: t[0], reverse=True)

    print(f"closest existing catalogue entries to: {query_text[:90]!r}")
    for ratio, fn, preview in scored[: args.top]:
        names = names_by_fn.get(fn, [])
        label = ", ".join(names) if names else "(unregistered helper)"
        snippet = " ".join(preview.split())[:100]
        print(f"  {ratio:.2f}  {fn}  [{label}]  {file_by_fn.get(fn, '?')}")
        print(f"        {snippet}")
    print()
    print("run `check \"<one of the names above>\"` to see the full source and adapt it.")


# --- CLI -------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_name_cmd(name: str, help_text: str):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("name", help="cached card name (exact or close — near-misses are suggested)")
        p.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)
        return p

    add_name_cmd("text", "real oracle text + parse verdict + unclaimed clauses")
    add_name_cmd("reuse", "parser-claimed specs as paste-ready AbilitySpec source")
    add_name_cmd("scaffold", "full factory + register() + test skeleton")

    p_check = sub.add_parser("check", help="is this card already registered? show its source")
    p_check.add_argument("name")

    p_similar = sub.add_parser("similar", help="closest existing catalogue entries to a card or text snippet")
    p_similar.add_argument("query", help="a cached card name, or a raw oracle-text snippet")
    p_similar.add_argument("--top", type=int, default=8)
    p_similar.add_argument("--card-db", type=Path, default=DEFAULT_DB_PATH)

    args = parser.parse_args()
    {
        "text": cmd_text,
        "reuse": cmd_reuse,
        "scaffold": cmd_scaffold,
        "check": cmd_check,
        "similar": cmd_similar,
    }[args.command](args)


if __name__ == "__main__":
    main()
