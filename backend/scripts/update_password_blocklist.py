#!/usr/bin/env python3
"""Merge a compromised-password list into the shipped blocklist (PLR-9a, plan §3).

  python scripts/update_password_blocklist.py path/to/list.txt [more.txt ...]

Only entries at least `PASSWORD_MIN_LENGTH` characters long are kept: shorter ones are
refused by the length rule anyway, so they would only bloat the file. Entries are
lower-cased (the check is case-insensitive), deduplicated and sorted into
`mtg_analyzer/data/common_passwords.txt`. Offline by design: download a list yourself,
e.g. a "top N" file from the MIT-licensed SecLists project (Passwords/Common-Credentials),
and pass it in. Keep the licence notice of your source with the repository when committing it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mtg_analyzer import config  # noqa: E402

BLOCKLIST = Path(__file__).resolve().parent.parent / "mtg_analyzer" / "data" / "common_passwords.txt"


def merge(sources: list[Path]) -> tuple[int, int]:
    entries = set(BLOCKLIST.read_text(encoding="utf-8").split()) if BLOCKLIST.exists() else set()
    before = len(entries)
    for source in sources:
        for line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
            word = line.strip().lower()
            if len(word) >= config.PASSWORD_MIN_LENGTH and len(word) <= config.PASSWORD_MAX_LENGTH:
                entries.add(word)
    BLOCKLIST.write_text("\n".join(sorted(entries)) + "\n", encoding="utf-8")
    return before, len(entries)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    before, after = merge([Path(a) for a in argv])
    print(f"Blocklist: {before} -> {after} entries ({BLOCKLIST})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
