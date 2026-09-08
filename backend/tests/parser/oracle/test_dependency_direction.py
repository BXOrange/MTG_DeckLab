"""Parser architecture boundaries."""

import ast
from pathlib import Path


PARSER_ROOT = Path(__file__).parents[3] / "mtg_analyzer" / "parser"


def test_oracle_parser_does_not_import_runtime_game_code():
    violations: list[str] = []
    for path in PARSER_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names = (node.module or "",)
            else:
                continue
            if any(name == "mtg_analyzer.game" or name.startswith("mtg_analyzer.game.") for name in names):
                violations.append(str(path.relative_to(PARSER_ROOT)))
    assert not violations, f"parser imports runtime game code: {violations}"
