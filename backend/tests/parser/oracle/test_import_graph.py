"""Guards PAR-172: the parser's modules form an acyclic import graph with no private-name sharing.

The segmenter, the effect handlers and the static handlers used to import each other through
function-scoped imports and `_private` names. The shared primitives now live in the leaf modules
`catalogue/clause_primitives.py` and `catalogue/clause_hooks.py`; this test keeps it that way.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ORACLE = Path(__file__).resolve().parents[3] / "mtg_analyzer" / "parser" / "oracle"
_PACKAGE = "mtg_analyzer.parser.oracle"

#: The leaf modules: they may import the spec and the vocabulary modules, never the big three.
_LEAVES = ("catalogue.clause_primitives", "catalogue.clause_hooks")
_BIG_THREE = ("segmenter", "catalogue.handlers", "catalogue.static_handlers")
#: The effect-row modules (PAR-172 M2) sit below `handlers` and the segmenter: they re-enter those only via `clause_hooks`.
_ROW_FORBIDDEN = ("segmenter", "catalogue.handlers")

#: A function-scoped or private import between parser modules needs a one-line justification here.
#: Empty on purpose: the cycle is broken by `clause_hooks`, not by deferred imports.
_ALLOWED_FUNCTION_SCOPED: dict[tuple[str, str], str] = {}
_ALLOWED_PRIVATE: dict[tuple[str, str, str], str] = {}


def _module_name(path: Path) -> str:
    rel = path.relative_to(_ORACLE).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _modules() -> dict[str, Path]:
    return {
        _module_name(p): p
        for p in sorted(_ORACLE.rglob("*.py"))
        if "__pycache__" not in p.parts
    }


def _resolve(importer: str, node: ast.ImportFrom, known: set[str]) -> str | None:
    """The parser/oracle module an ImportFrom points at (None for anything outside it)."""
    if node.level:
        is_pkg = importer in known and (_ORACLE / importer.replace(".", "/") / "__init__.py").exists()
        base = importer.split(".") if is_pkg else importer.split(".")[:-1]
        base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
        target = ".".join(base + ([node.module] if node.module else []))
    elif node.module and node.module.startswith(_PACKAGE):
        target = node.module[len(_PACKAGE):].lstrip(".")
    else:
        return None
    return target if target in known else None


def _import_edges() -> list[tuple[str, str, ast.ImportFrom, bool]]:
    """(importer, imported module, node, is_function_scoped) for every intra-parser import."""
    mods = _modules()
    known = set(mods)
    edges = []
    for name, path in mods.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scoped = {
            id(n)
            for fn in ast.walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            for n in ast.walk(fn)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            target = _resolve(name, node, known)
            if target is not None and target != name:
                edges.append((name, target, node, id(node) in scoped))
    return edges


def test_leaf_modules_import_none_of_the_big_three():
    offenders = [
        (src, dst) for src, dst, _, _ in _import_edges() if src in _LEAVES and dst in _BIG_THREE
    ]
    assert not offenders, f"leaf modules must not import the cycle members: {offenders}"


def test_effect_row_modules_do_not_import_handlers_or_the_segmenter():
    offenders = [
        (src, dst)
        for src, dst, _, _ in _import_edges()
        if src.startswith("catalogue.effect_rows.") and dst in _ROW_FORBIDDEN
    ]
    assert not offenders, f"effect rows must reach the table/segmenter through clause_hooks: {offenders}"


def test_module_level_import_graph_is_acyclic():
    graph: dict[str, set[str]] = {m: set() for m in _modules()}
    for src, dst, _, scoped in _import_edges():
        if not scoped:
            graph[src].add(dst)
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in sorted(graph[node]):
            if state.get(nxt) == 1:
                cycle = stack[stack.index(nxt):] + [nxt]
                pytest.fail("import cycle: " + " -> ".join(cycle))
            if nxt not in state:
                visit(nxt)
        stack.pop()
        state[node] = 2

    for module in sorted(graph):
        if module not in state:
            visit(module)


def test_no_function_scoped_imports_between_parser_modules():
    offenders = sorted(
        f"{src} -> {dst} (line {node.lineno})"
        for src, dst, node, scoped in _import_edges()
        if scoped and (src, dst) not in _ALLOWED_FUNCTION_SCOPED
    )
    assert not offenders, "function-scoped parser-module imports need a justified allowlist entry:\n" + "\n".join(offenders)


def test_no_private_names_imported_across_parser_modules():
    offenders = []
    for src, dst, node, _ in _import_edges():
        for alias in node.names:
            name = alias.name
            if name.startswith("_") and not name.startswith("__") and (src, dst, name) not in _ALLOWED_PRIVATE:
                offenders.append(f"{src} imports {dst}.{name} (line {node.lineno})")
    assert not offenders, "share it under a public name (or move it to clause_primitives):\n" + "\n".join(sorted(offenders))


def test_clause_hooks_are_registered_once_the_parser_is_imported():
    from mtg_analyzer.parser.oracle import parse_oracle  # noqa: F401  (importing the package registers the hooks)
    from mtg_analyzer.parser.oracle.catalogue import clause_hooks

    assert clause_hooks.parse_effect_body("draw a card") is not None
    assert clause_hooks._static_condition is not None
    assert clause_hooks._segment_line is not None and clause_hooks._trigger_condition_dict is not None
