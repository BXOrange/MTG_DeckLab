"""Pins `HANDLERS` row order (PAR-172 M2).

Order is semantics (the first eligible row to full-match a clause wins; see the comment above `HANDLERS`
in `catalogue/handlers.py`). The rows live in `catalogue/effect_rows/*.py` and are assembled there, so a
move between modules must not reorder them. When a row is added, removed or moved on purpose, update
`handler_row_order.txt` (one row name per line) in the same change.
"""

from pathlib import Path

from mtg_analyzer.parser.oracle.catalogue import effect_rows  # noqa: F401  (package must import cleanly)
from mtg_analyzer.parser.oracle.catalogue.handlers import HANDLERS

_PINNED = Path(__file__).with_name("handler_row_order.txt")


def test_handler_row_order_is_pinned():
    pinned = _PINNED.read_text(encoding="utf-8").split()
    assert [h.name for h in HANDLERS] == pinned


def test_every_effect_rows_module_contributes_rows_in_assembly_order():
    import importlib
    import pkgutil

    from mtg_analyzer.parser.oracle.catalogue import effect_rows as pkg

    flat = []
    modules = [m.name for m in pkgutil.iter_modules(pkg.__path__) if m.name != "shared"]
    for name in modules:
        mod = importlib.import_module(f"{pkg.__name__}.{name}")
        assert hasattr(mod, "ROWS"), f"effect_rows.{name} must export ROWS"
        flat.extend(mod.ROWS)
    assert {id(h) for h in flat} == {id(h) for h in HANDLERS}, "a row module is not assembled into HANDLERS"
