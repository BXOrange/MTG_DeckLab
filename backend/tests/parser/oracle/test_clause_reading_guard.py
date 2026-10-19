"""Guards PAR-173: a clause is read under one `ClauseReading`, not five threaded flags and a ContextVar.

AST check over `parser/` with an empty allowlist: no function declares one of the five subject-flag parameters,
no call passes one as a keyword except to build/derive a `ClauseReading`, no `EffectHandler` gate field survives,
and no `contextvars` import remains.
"""

import ast
from pathlib import Path

_PARSER = Path(__file__).resolve().parents[3] / "mtg_analyzer" / "parser"
_FLAGS = {"self_subject", "previous_subject", "group_subject", "previous_selector", "attached_subject"}
_GATE_FIELDS = {f"{flag}_only" for flag in _FLAGS}
#: The only callables that take the flag names as keywords: they construct / derive a reading.
_READING_BUILDERS = {"ClauseReading", "but", "only"}


def _trees():
    for path in sorted(_PARSER.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path.relative_to(_PARSER), ast.parse(path.read_text(encoding="utf-8"))


def _callee(node: ast.Call):
    func = node.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None


def test_no_parser_function_declares_a_subject_flag_parameter():
    offenders = [
        f"{rel}:{node.lineno} {node.arg}"
        for rel, tree in _trees()
        for node in ast.walk(tree)
        if isinstance(node, ast.arg) and node.arg in _FLAGS
    ]
    assert not offenders, "take a `reading: ClauseReading` instead:\n" + "\n".join(offenders)


def test_no_call_passes_a_subject_flag_except_to_build_a_reading():
    offenders = [
        f"{rel}:{node.lineno} {_callee(node)}({kw.arg}=…)"
        for rel, tree in _trees()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee(node) not in _READING_BUILDERS
        for kw in node.keywords
        if kw.arg in _FLAGS
    ]
    assert not offenders, "pass `reading=ClauseReading(...)`:\n" + "\n".join(offenders)


def test_no_gate_field_or_context_variable_survives():
    offenders = []
    for rel, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in _GATE_FIELDS:
                offenders.append(f"{rel}:{node.lineno} gate field {node.target.id}")
            if isinstance(node, ast.keyword) and node.arg in _GATE_FIELDS:
                offenders.append(f"{rel}:{node.value.lineno} gate keyword {node.arg}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
                if any(n == "contextvars" or n == "ContextVar" for n in names):
                    offenders.append(f"{rel}:{node.lineno} contextvars")
    assert not offenders, "\n".join(offenders)
