#!/usr/bin/env python3
"""Where does the test time go? Per-file and per-domain durations from a JUnit XML.

Usage (from backend/):
  python scripts/test_profile.py --run [-n auto]   # run the suite, then report
  python scripts/test_profile.py report.xml        # report on an existing run

Summed test time is CPU-ish time, not wall-clock: under `-n` it exceeds the
elapsed time by roughly the worker count. Use it to rank, not to predict.
"""
from __future__ import annotations

import argparse
import collections
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from tests import domains as D  # noqa: E402

TOP_FILES = 30


def load(xml_path: Path) -> dict[str, tuple[float, int]]:
    """test file (repo-relative) -> (seconds, test count)."""
    per_file: dict[str, list[float]] = collections.defaultdict(lambda: [0.0, 0])
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        module = case.get("classname", "").split(".")
        # classname is dotted path to the module, possibly plus a class name
        parts = [p for p in module if p]
        for i in range(len(parts), 0, -1):
            candidate = BACKEND_ROOT / Path(*parts[:i]).with_suffix(".py")
            if candidate.exists():
                key = candidate.relative_to(BACKEND_ROOT.parent).as_posix()
                per_file[key][0] += float(case.get("time", 0))
                per_file[key][1] += 1
                break
    return {k: (v[0], int(v[1])) for k, v in per_file.items()}


def report(per_file: dict[str, tuple[float, int]]) -> None:
    domain_of = D.domain_map_for([BACKEND_ROOT.parent / k for k in per_file])
    by_domain: dict[str, list[float]] = collections.defaultdict(lambda: [0.0, 0, 0])
    for key, (sec, n) in per_file.items():
        for d in domain_of.get(key, ("?",)):
            by_domain[d][0] += sec
            by_domain[d][1] += n
            by_domain[d][2] += 1
    total = sum(s for s, _ in per_file.values())
    print(f"total summed test time {total:.0f}s over {sum(n for _, n in per_file.values())} tests "
          f"in {len(per_file)} files\n")
    print(f"{'domain':<14}{'seconds':>9}{'tests':>8}{'files':>7}{'ms/test':>9}")
    for d, (sec, n, files) in sorted(by_domain.items(), key=lambda kv: -kv[1][0]):
        print(f"{d:<14}{sec:>9.0f}{n:>8}{files:>7}{1000 * sec / max(n, 1):>9.0f}")
    print(f"\nTop {TOP_FILES} files by time:")
    for key, (sec, n) in sorted(per_file.items(), key=lambda kv: -kv[1][0])[:TOP_FILES]:
        print(f"{sec:>8.1f}s {n:>5}  {key}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xml", nargs="?", type=Path)
    ap.add_argument("--run", action="store_true")
    args, extra = ap.parse_known_args()
    xml_path = args.xml or BACKEND_ROOT / "cache" / "test_profile.xml"
    if args.run:
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.call([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                         f"--junitxml={xml_path}", *extra], cwd=BACKEND_ROOT)
    report(load(xml_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
