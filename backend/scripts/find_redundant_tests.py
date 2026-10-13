#!/usr/bin/env python3
"""Report (never delete) test redundancy candidates.

  * duplicate bodies: test functions whose AST is identical once names,
    docstrings and constant values are blanked out -- exact copies, not merely similar tests
  * copied helpers: module-level helper functions defined with an identical
    body in several test files (candidates for tests/support/)
  * series: groups of files that differ only by a number in their name
    (wave1..wave15, batch4..batch10), candidates for `parametrize`

Usage (from backend/):
  python scripts/find_redundant_tests.py [--min-copies 2] [--top 25]

Every hit needs a human look: two tests with the same shape can guard different
cards, and a single-card regression protects behaviour even when line coverage
overlaps. This script only narrows where to look.
"""
from __future__ import annotations

import argparse
import ast
import collections
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent / "tests"


class _Blank(ast.NodeTransformer):
    """Blank everything that does not change what a test does structurally."""

    def visit_Constant(self, node: ast.Constant) -> ast.AST:  # noqa: N802
        return ast.copy_location(ast.Constant(value=type(node.value).__name__), node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:  # noqa: N802
        node.name = "_"
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
            node.body = node.body[1:] or [ast.Pass()]
        node.decorator_list = []
        self.generic_visit(node)
        return node


def _fingerprint(fn: ast.FunctionDef, blank: bool) -> str:
    copy = ast.parse(ast.unparse(fn)).body[0]
    if blank:
        copy = _Blank().visit(copy)
    return ast.dump(copy, annotate_fields=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-copies", type=int, default=2)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    tests: dict[str, list[str]] = collections.defaultdict(list)
    helpers: dict[str, list[str]] = collections.defaultdict(list)
    names: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted(TESTS.rglob("test_*.py")):
        rel = path.relative_to(TESTS).as_posix()
        names[re.sub(r"\d+", "N", path.stem)].append(rel)
        try:
            tree = ast.parse(path.read_text(encoding="utf8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name.startswith("test_"):
                tests[_fingerprint(node, blank=True)].append(f"{rel}::{node.name}")
            elif node.name.startswith("_") and len(node.body) > 2:
                helpers[_fingerprint(node, blank=False)].append(f"{rel}::{node.name}")

    def show(title: str, groups: list[list[str]]) -> None:
        groups = [g for g in groups if len(g) >= args.min_copies]
        groups.sort(key=len, reverse=True)
        print(f"\n== {title}: {len(groups)} group(s)")
        for g in groups[: args.top]:
            print(f"  x{len(g)}  {g[0]}")
            for other in g[1:4]:
                print(f"        {other}")
            if len(g) > 4:
                print(f"        ... +{len(g) - 4}")

    show("duplicate test bodies (names/constants blanked)", list(tests.values()))
    show("copied helper bodies (exact)", list(helpers.values()))
    show("numbered series", [v for k, v in names.items() if "N" in k])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
