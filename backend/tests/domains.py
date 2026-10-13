"""Test-domain model: which part of the product a source file / a test belongs to.

One data table drives three things, so they cannot drift apart:

* `tests/conftest.py` tags every collected test with `domain_<name>` markers,
* `scripts/select_tests.py` maps a git diff to the domains (and test files) it touches,
* the `run-tests` skill escalates from the changed domain outward (tier T1 -> T4).

The idea: a new card must not trigger websocket, lobby or deck-database tests.
Tier 1 of a change is always the domain it lives in; wider tiers are opt-in
or triggered by `WIDE_REACH_SOURCES`.
"""
from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
PACKAGE = "mtg_analyzer"

DOMAINS = (
    "parser",        # oracle text -> AbilitySpec IR
    "card",          # hand-authored catalogue entries and per-card regressions
    "engine",        # rules engine, combat, effects, continuous layers
    "session_bots",  # GameSession, undo, replay, bots
    "multiplayer",   # lobby, websockets, table feed, priority yield
    "api",           # HTTP routes and schemas
    "db",            # SQLite stores and lookup layers
    "external",      # Scryfall, Archidekt, LLM, image cache
    "analysis",      # archetype / dynamic / narrative analysis
    "config_ops",    # config, setup, startup
    "models",        # Card / Deck / GameObject data models
    "frontend",      # static ES modules
)

# Source path (relative to `backend/` or repo root) -> domain. Longest prefix wins.
SOURCE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("frontend/", "frontend"),
    ("mtg_analyzer/parser/", "parser"),
    ("mtg_analyzer/game/card_catalogue/", "card"),
    ("mtg_analyzer/game/card_registry/", "card"),
    ("mtg_analyzer/game/ability_catalogue/", "card"),
    ("mtg_analyzer/game/", "engine"),
    ("mtg_analyzer/models/", "models"),
    ("mtg_analyzer/config", "config_ops"),
    ("mtg_analyzer/api/multiplayer", "multiplayer"),
    ("mtg_analyzer/api/game_ws", "multiplayer"),
    ("mtg_analyzer/services/lobby", "multiplayer"),
    ("mtg_analyzer/services/table_feed", "multiplayer"),
    ("mtg_analyzer/services/game_session", "session_bots"),
    ("mtg_analyzer/services/replay", "session_bots"),
    ("mtg_analyzer/services/bot", "session_bots"),
    ("mtg_analyzer/services/scryfall_client", "external"),
    ("mtg_analyzer/services/archidekt_client", "external"),
    ("mtg_analyzer/services/llm_", "external"),
    ("mtg_analyzer/services/image_cache", "external"),
    ("mtg_analyzer/services/commander_spellbook", "external"),
    ("mtg_analyzer/api/images", "external"),
    ("mtg_analyzer/api/llm", "external"),
    ("mtg_analyzer/api/import_external", "external"),
    ("mtg_analyzer/services/archetype_", "analysis"),
    ("mtg_analyzer/services/dynamic_analysis", "analysis"),
    ("mtg_analyzer/services/narrative_analysis", "analysis"),
    ("mtg_analyzer/api/archetypes", "analysis"),
    ("mtg_analyzer/api/dynamic_analysis", "analysis"),
    ("mtg_analyzer/api/narrative_analysis", "analysis"),
    ("mtg_analyzer/api/stats", "analysis"),
    ("mtg_analyzer/api/combos", "analysis"),
    ("mtg_analyzer/services/", "db"),
    ("mtg_analyzer/api/", "api"),
)

# Tests living here take their domain from the directory, not from imports.
TEST_DIR_DOMAINS: tuple[tuple[str, str], ...] = (
    ("tests/parser/", "parser"),
    ("tests/models/", "models"),
    ("tests/game/catalogue/", "card"),
    ("tests/game/", "engine"),
    ("frontend/tests/", "frontend"),
)

# Test-file name patterns, checked when imports give no specific domain.
TEST_NAME_RULES: tuple[tuple[str, str], ...] = (
    (r"test_(config|setup)", "config_ops"),
    (r"(multiplayer|lobby|game_ws|table_|priority_yield)", "multiplayer"),
    (r"(frontend_proxy|test_api_)", "api"),
)

# Imports every engine test needs. They say nothing about what is under test,
# so they are ignored when inferring a test's domain from its imports.
UBIQUITOUS_IMPORTS: tuple[str, ...] = (
    "mtg_analyzer.models",
    "mtg_analyzer.parser",
    "mtg_analyzer.config",
    "mtg_analyzer.game.binding",
    "mtg_analyzer.game.game_engine",
    "mtg_analyzer.game.rules_engine",
    "mtg_analyzer.api.app",
    "mtg_analyzer.api.dependencies",
)

# A test importing the card database / registry resolves real cards by name.
CARD_TEST_IMPORTS: tuple[str, ...] = (
    "mtg_analyzer.services.card_database",
    "mtg_analyzer.game.card_registry",
    "mtg_analyzer.game.card_catalogue",
)

# Source domain -> domains that consume it (tier T2). A card or API change has
# no consumers, so its widening stops at the domain itself.
DEPENDENTS: dict[str, tuple[str, ...]] = {
    "models": ("parser", "engine", "card", "db"),
    "parser": ("card",),
    "engine": ("card", "session_bots"),
    "session_bots": ("multiplayer", "api"),
    "db": ("api", "session_bots"),
    "external": ("api",),
    "config_ops": ("api",),
}

# Sources whose behaviour reaches nearly every test: a change escalates past T1.
WIDE_REACH_SOURCES: tuple[str, ...] = (
    "mtg_analyzer/models/game/game_state.py",
    "mtg_analyzer/models/game/game_object.py",
    "mtg_analyzer/models/cards/card.py",
    "mtg_analyzer/game/continuous.py",
    "mtg_analyzer/game/effects/registry.py",
    "mtg_analyzer/game/binding/core.py",
    "mtg_analyzer/game/game_engine.py",
    "mtg_analyzer/parser/oracle/gate.py",
    "mtg_analyzer/parser/oracle/spec.py",
    "conftest.py",
    "tests/conftest.py",
)

_CACHE_FILE = BACKEND_ROOT / "cache" / "test_domains.json"  # backend/cache/ is git-ignored


def source_domain(rel_path: str) -> str | None:
    """Domain of a repo/backend-relative source path; None if it is in no domain."""
    rel = rel_path.replace("\\", "/")
    for prefix in ("backend/",):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
    best: tuple[int, str] | None = None
    for prefix, domain in SOURCE_PREFIXES:
        if rel.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), domain)
    return best[1] if best else None


def _imported_modules(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module)
            mods.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
    return {m for m in mods if m.startswith(PACKAGE)}


def _module_domain(module: str) -> str | None:
    return source_domain(module.replace(".", "/") + "/")


def _is_under(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def classify_test(path: Path) -> tuple[str, ...]:
    """Domains a test file belongs to (first entry is the primary domain)."""
    rel = path.resolve().relative_to(REPO_ROOT).as_posix()
    rel_backend = rel[len("backend/"):] if rel.startswith("backend/") else rel
    for prefix, domain in TEST_DIR_DOMAINS:
        if rel_backend.startswith(prefix) or rel.startswith(prefix):
            return (domain,)
    imports = _imported_modules(path)
    specific = {
        d for m in imports
        if not _is_under(m, UBIQUITOUS_IMPORTS)
        and (d := _module_domain(m)) is not None
        and d not in ("engine", "models", "parser", "db")  # handled below
    }
    uses_db_for_cards = any(_is_under(m, CARD_TEST_IMPORTS) for m in imports)
    db_specific = {
        d for m in imports
        if not _is_under(m, UBIQUITOUS_IMPORTS + CARD_TEST_IMPORTS)
        and _module_domain(m) == "db"
    }
    for pattern, domain in TEST_NAME_RULES:
        if re.search(pattern, path.name):
            specific.add(domain)
    domains = sorted(specific | db_specific)
    if not domains:
        engine_import = any(_is_under(m, ("mtg_analyzer.game",)) for m in imports)
        if uses_db_for_cards:
            domains = ["card"]
        elif engine_import:
            domains = ["engine"]
        else:
            domains = ["models"]
    elif uses_db_for_cards and "card" not in domains:
        domains.append("card")
    return tuple(domains)


def domain_map_for(test_files: list[Path]) -> dict[str, tuple[str, ...]]:
    """rel path -> domains, cached on mtime so repeat collection stays cheap."""
    try:
        cache = json.loads(_CACHE_FILE.read_text(encoding="utf8"))
    except (OSError, ValueError):
        cache = {}
    out: dict[str, tuple[str, ...]] = {}
    fresh: dict[str, dict] = {}
    for f in test_files:
        key = f.resolve().relative_to(REPO_ROOT).as_posix()
        mtime = f.stat().st_mtime_ns
        hit = cache.get(key)
        if hit and hit["mtime"] == mtime:
            domains = tuple(hit["domains"])
        else:
            domains = classify_test(f)
        out[key] = domains
        fresh[key] = {"mtime": mtime, "domains": list(domains)}
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return out  # the controller already refreshed the cache; avoid concurrent writes
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(fresh), encoding="utf8")
    except OSError:
        pass
    return out
