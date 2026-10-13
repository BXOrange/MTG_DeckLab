#!/usr/bin/env python3
"""Pick the smallest sensible test set for the current git diff.

Tier 1 is always the domain of the change (see tests/domains.py): a new card
runs the card/catalogue tests that mention it, never websocket or lobby tests.
Wider tiers are explicit (`--tier`) or forced by wide-reach sources.

  T1  tests of the changed domain(s), refined to the changed module/card
  T2  T1 plus the domains that consume the changed one (DEPENDENTS)
  T3  everything except the bot tests ("all without bots"; the default wide tier)
  T4  everything including the bot tests (they play whole games: ~45% of the suite's time)
  --full-cache  orthogonal: add the full-card-cache tier to T3/T4 (required before
                closing engine/parser work)

Bot tests (domain `bots`) run only when bot code (services/bots*, bot_policies,
api/solo) or a bot test file changed, or with T4.

Usage (from backend/):
  python scripts/select_tests.py                 # print the plan as JSON
  python scripts/select_tests.py --run [-n 8]    # run it via scripts/run_tests.py
  python scripts/select_tests.py --tier 2 --run
  python scripts/select_tests.py --base main     # diff against another base
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from tests import domains as D  # noqa: E402

# File lists go through a pytest `@argsfile`: Windows caps a command line at
# ~32k characters and a refined slice can name a hundred test files.
ARGS_FILE = BACKEND_ROOT / "cache" / "select_tests.args"
# Below this many selected files parallelism costs more (worker start-up,
# per-worker collection) than it saves.
PARALLEL_MIN_FILES = 25
# Measured here: -n 4 ~145 s, -n 8 ~195 s, -n 12 ~180 s versus ~310 s serial. Past 4
# workers the per-worker import (~10 s) and disk contention eat the gain.
PARALLEL_WORKERS = 4
# Paths whose change cannot alter product behaviour: no tests for them.
# (`backend/scripts/` are dev tools; test infrastructure such as conftest.py
# is deliberately NOT here and escalates to T3.)
NON_CODE_PREFIXES = ("docs/", "user-docs/", ".claude/", "bug-reports/", "backend/scripts/", "backend/requirements")
NON_CODE_SUFFIXES = (".md", ".txt", ".lock", ".json", ".png", ".svg")


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


def changed_files(base: str | None) -> list[str]:
    """Working-tree changes plus (when on a branch) commits since the merge-base."""
    files = set(_git("diff", "--name-only", "HEAD"))
    files.update(_git("ls-files", "--others", "--exclude-standard"))
    if base:
        merge_base = _git("merge-base", base, "HEAD")
        if merge_base:
            files.update(_git("diff", "--name-only", merge_base[0], "HEAD"))
    return sorted(files)


def all_test_files() -> list[Path]:
    return sorted(p for p in (BACKEND_ROOT / "tests").rglob("test_*.py"))


def _rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def _module_of(rel: str) -> str:
    """backend/mtg_analyzer/game/combat.py -> mtg_analyzer.game.combat"""
    mod = rel.removeprefix("backend/").removesuffix(".py").replace("/", ".")
    return mod.removesuffix(".__init__")


def refine(changed_src: str, domain: str, tests: list[Path], domain_of: dict[str, tuple[str, ...]]) -> list[Path]:
    """Narrow a domain's tests to those plausibly tied to one changed source file."""
    module = _module_of(changed_src)
    stem = Path(changed_src).stem
    hits: list[Path] = []
    for t in tests:
        if domain not in domain_of[_rel(t)]:
            continue
        text = t.read_text(encoding="utf8", errors="replace")
        imports = D._imported_modules(t)
        mentions_module = any(m == module or m.startswith(module + ".") for m in imports)
        # card names read "Abdel Adrian, Gorion's Ward" in tests, `abdel_adrian_gorion_s_ward` in the filename
        normalized = re.sub(r"[^a-z0-9]+", "_", text.lower())
        mentions_stem = len(stem) > 3 and f"_{stem}_" in f"_{normalized}_"
        same_dir = domain == "engine" and stem in t.parent.name
        if mentions_module or mentions_stem or same_dir:
            hits.append(t)
    if domain == "card":
        # catalogue-wide consistency tests always run for a catalogue change
        # (top level only: tests/game/catalogue/cards/ holds the slow deck simulations)
        hits.extend(
            t for t in tests
            if t.parent.name == "catalogue" and t.parent.parent.name == "game" and t not in hits
        )
    return hits


def plan(files: list[str], forced_tier: int | None, full_cache: bool = False) -> dict:
    tests = all_test_files()
    domain_of = D.domain_map_for(tests)
    reasons: list[str] = []
    touched: set[str] = set()
    direct_tests: set[Path] = set()
    refined: dict[str, set[Path]] = {}
    tier = 1
    unknown = False

    for rel in files:
        if rel.startswith(NON_CODE_PREFIXES) or rel.endswith(NON_CODE_SUFFIXES):
            continue
        backend_rel = rel.removeprefix("backend/")
        if backend_rel.startswith("tests/") and Path(rel).name.startswith("test_"):
            direct_tests.add(REPO_ROOT / rel)
            continue
        domain = D.source_domain(rel)
        if domain is None:
            unknown = True
            reasons.append(f"{rel}: in no domain -> escalate to T3")
            continue
        touched.add(domain)
        if backend_rel in D.WIDE_REACH_SOURCES or rel in D.WIDE_REACH_SOURCES:
            tier = max(tier, 3)
            reasons.append(f"{rel}: wide-reach source -> T3")
        elif domain in ("card", "engine") and backend_rel.endswith(".py"):
            hits = refine(rel, domain, tests, domain_of)
            if hits:
                refined.setdefault(domain, set()).update(hits)
                reasons.append(f"{rel}: {domain} domain, {len(hits)} related test file(s)")
            else:
                refined.setdefault(domain, set()).update(
                    t for t in tests if domain in domain_of[_rel(t)])
                reasons.append(f"{rel}: {domain} domain, no narrower match -> whole domain")
        else:
            reasons.append(f"{rel}: {domain} domain")

    if unknown:
        tier = max(tier, 3)
    if forced_tier:
        tier = forced_tier
        reasons.append(f"tier forced to T{forced_tier}")
    if not files or (not touched and not direct_tests and not unknown):
        reasons.append("no code change -> nothing to test" if files else "empty diff -> T3 smoke of all domains")
        if not files:
            tier = max(tier, 3)

    pytest_args: list[str] = []
    selected: list[Path] = []
    run_frontend_checks = "frontend" in touched
    is_bot_file = lambda t: "bots" in domain_of[_rel(t)]  # noqa: E731
    include_bots = tier >= 4 or "bots" in touched or any(is_bot_file(t) for t in direct_tests)
    if tier >= 3:
        selected = tests if include_bots else [t for t in tests if not is_bot_file(t)]
        if not include_bots:
            pytest_args += ["-m", "not domain_bots"]
            reasons.append("bot tests excluded (T4 or a bot change includes them)")
        if full_cache:
            pytest_args.append("--full-cache")
    else:
        domains = set(touched) - {"frontend"}
        if tier == 2:
            for d in list(domains):
                domains.update(D.DEPENDENTS.get(d, ()))
            reasons.append(f"T2 adds consumers: {sorted(domains - touched)}")
        picked: set[Path] = set(direct_tests)
        for d in domains:
            if tier == 1 and d in refined:
                picked.update(refined[d])
            else:
                picked.update(t for t in tests if d in domain_of[_rel(t)])
        selected = sorted(picked if include_bots else {t for t in picked if not is_bot_file(t) or t in direct_tests})

    if tier >= 3:
        pass  # whole backend suite, no file list needed
    elif selected:
        ARGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines = [_rel(t).removeprefix("backend/") for t in selected]
        ARGS_FILE.write_text("\n".join(lines) + "\n", encoding="utf8")
        pytest_args.append(f"@{ARGS_FILE.relative_to(BACKEND_ROOT).as_posix()}")
    count = len(selected)
    if count >= PARALLEL_MIN_FILES:
        pytest_args += ["-n", str(PARALLEL_WORKERS)]

    return {
        "tier": tier,
        "domains": sorted(touched),
        "run_backend": bool(selected) or tier >= 3,
        "files_selected": count,
        "files_total": len(tests),
        "pytest_args": pytest_args,
        "frontend_checks": run_frontend_checks,
        "frontend_only": touched == {"frontend"} and not direct_tests and not unknown,
        "reasons": reasons,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=None, help="also include commits since merge-base with this ref (e.g. main)")
    ap.add_argument("--tier", type=int, choices=(1, 2, 3, 4), help="force a tier")
    ap.add_argument("--full-cache", action="store_true", help="also run the full-card-cache tier (T3/T4)")
    ap.add_argument("--files", nargs="+", help="plan for these repo-relative files instead of the git diff")
    ap.add_argument("--run", action="store_true", help="execute the plan through scripts/run_tests.py")
    ap.add_argument("--hard-timeout", type=float, default=None)
    args, extra = ap.parse_known_args()

    result = plan(args.files or changed_files(args.base), args.tier, args.full_cache)
    print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr if args.run else sys.stdout)
    if not args.run:
        return 0
    if not result["run_backend"]:
        print("Nothing to run for the backend.", file=sys.stderr)
        return 0
    timeout = args.hard_timeout or {1: 300, 2: 900, 3: 1800, 4: 3600}[result["tier"]] * (2 if args.full_cache else 1)
    cmd = [sys.executable, str(BACKEND_ROOT / "scripts" / "run_tests.py"),
           "--hard-timeout", str(timeout), *result["pytest_args"], *extra]
    return subprocess.call(cmd, cwd=BACKEND_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
