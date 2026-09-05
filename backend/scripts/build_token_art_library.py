#!/usr/bin/env python3
"""Build the vanilla-token art library from Scryfall's `default_cards` bulk dump.

Reference: `services/token_database.py` (the curated, *ability*-carrying token
catalogue this file deliberately doesn't touch) and its `synthesize_token_card`
(the inline "create a 2/2 blue Shapeshifter token" path this file's output
feeds art into).

Why a separate dataset from `data/tokens.json`: that file holds the small set
of tokens with a real activated ability (Treasure, Clue, Food, …) — few enough
to hand-curate, each needing real oracle text. The vast majority of tokens an
effect creates instead have *no* ability of their own (a vanilla "1/1 white
Soldier", a "2/2 blue Shapeshifter") — `synthesize_token_card` builds their
`Card` straight from the clause's own power/toughness/colors/subtypes, with no
Scryfall id to hang art on. This script builds the missing lookup: every
distinct (name, power, toughness, colors) combination Scryfall has ever
printed a vanilla token for, resolved to one representative printing's art.
The (name, power, toughness, colors) key is the point — Magic reuses a token
name across many different stat lines (e.g. "Shapeshifter" tokens exist as
1/1, 2/2, 3/2 and */* in various colors), so name alone would show the wrong
picture for whichever variant didn't win the lookup.

Scryfall's `oracle_cards` bulk dump (`scripts/import_bulk.py`) explicitly
excludes token layouts — tokens aren't Oracle cards. `default_cards` (one
printing per unique card object, ~90k rows) is the smallest bulk dataset that
still has them, so this script downloads that one instead, filters to
`layout in {"token", "double_faced_token"}`, and discards everything else
without ever writing the full ~300MB dump to disk. A `double_faced_token`
(e.g. a transforming Werewolf token) is indexed by its front face only —
nothing downstream resolves a synthesized token's back face today.

One-shot curation, not part of any startup path (CLAUDE.md "starting is
offline-safe, and must stay that way" — this script is the explicit opposite
of that, same as `update_card_pool.py`). Re-run after a new set prints new
token variants; safe to re-run any time, it fully replaces its output file.

Usage (from backend/, venv active):
  python scripts/build_token_art_library.py [--out PATH] [--dump-cache PATH]
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx2 as httpx  # noqa: E402  (after sys.path bootstrap)

from mtg_analyzer.config import USER_AGENT  # noqa: E402

_BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"
_DATASET = "default_cards"
_TOKEN_LAYOUTS = frozenset({"token", "double_faced_token"})
_DEFAULT_OUT = Path(__file__).resolve().parent.parent / "mtg_analyzer" / "data" / "token_art.json"


def _download_filtered(dump_cache: Optional[Path]) -> Iterator[dict[str, Any]]:
    """Stream Scryfall's `default_cards` JSONL/gzip dump, yielding only token rows.

    Never materializes the full ~90k-card dataset in memory or on disk — each
    line is parsed, checked, and dropped immediately unless it's a token. When
    `dump_cache` is given and already exists, re-reads it instead of hitting
    the network (a `--dump-cache` re-run after tweaking the filter below).
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if dump_cache is not None and dump_cache.exists():
        print(f"Using cached dump {dump_cache} (delete it to force a re-download).")
        with gzip.open(dump_cache, "rt", encoding="utf-8") as gz:
            yield from _filter_lines(gz)
        return

    with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True) as client:
        index = client.get(_BULK_INDEX_URL)
        index.raise_for_status()
        entry = next(e for e in index.json()["data"] if e["type"] == _DATASET)
        uri = entry["jsonl_download_uri"]
        size_mb = entry.get("compressed_size", 0) / 1_000_000
        print(f"Downloading {_DATASET} dump (~{size_mb:.0f} MB compressed) from {uri} ...")

        dest = dump_cache
        tmp_path: Optional[Path] = None
        if dest is None:
            tmp = tempfile.NamedTemporaryFile(suffix=".jsonl.gz", delete=False)
            tmp.close()
            tmp_path = Path(tmp.name)
            dest = tmp_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        with client.stream("GET", uri) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1 << 20):
                    fh.write(chunk)
        try:
            with gzip.open(dest, "rt", encoding="utf-8") as gz:
                yield from _filter_lines(gz)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)


def _filter_lines(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    for line in lines:
        line = line.strip().rstrip(",")
        if not line or line in "[]":
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        # `set_type == "token"` is Scryfall's own marker for a real
        # companion token sheet (paired with a real expansion). Layout
        # "token" alone also catches ad cards, checklists and boxed
        # multiplayer-game products ("Battle the Horde", World Championship
        # ads, …) filed as set_type "memorabilia"/"minigame" — never
        # something a card's own `create_token` effect could produce.
        if data.get("layout") in _TOKEN_LAYOUTS and data.get("set_type") == "token":
            yield data


def _face_view(data: dict[str, Any]) -> dict[str, Any]:
    """The gameplay-relevant fields, taking the front face of a DFC token."""
    if data.get("layout") == "double_faced_token":
        faces = data.get("card_faces") or []
        if not faces:
            return data
        face = dict(faces[0])
        # Everything else (id, set, released_at) stays on the parent object.
        merged = {**data, **face}
        return merged
    return data


def _subtypes_from_type_line(type_line: str) -> list[str]:
    if " — " not in type_line:
        return []
    return type_line.split(" — ", 1)[1].split()


def _extract(data: dict[str, Any]) -> Optional[dict[str, Any]]:
    face = _face_view(data)
    name = (face.get("name") or "").strip()
    if not name:
        return None
    power_raw, toughness_raw = face.get("power"), face.get("toughness")
    # "*"/"1+*"-shaped variable stats can't match a synthesized token's
    # always-concrete int power/toughness — skip rather than mis-key them.
    power = _as_int(power_raw)
    toughness = _as_int(toughness_raw)
    if (power_raw is not None and power is None) or (toughness_raw is not None and toughness is None):
        return None
    colors = sorted(face.get("colors") or [])
    type_line = face.get("type_line") or ""
    image_uris = face.get("image_uris") or {}
    if not image_uris.get("small"):
        return None
    # A real companion token sheet (set_type "token") still mixes in
    # non-permanent reference cards — checklists, "The Monarch"/"City's
    # Blessing" reminders, Universes Beyond "Boss"/"Event" bonus-sheet
    # cards — none of which a `create_token` effect could ever ask for by
    # name. Most real tokens' type_line starts with "Token"; the handful
    # that don't (a flavor-named token like "Ecstatic Piper" or the
    # generic "Morph"/"Manifest" face-down token) always still say
    # "Creature" somewhere in it, which no reference card's type_line does.
    if not type_line.startswith("Token") and "Creature" not in type_line:
        return None
    return {
        "name": name,
        "power": power,
        "toughness": toughness,
        "colors": colors,
        "subtypes": _subtypes_from_type_line(type_line),
        "type_line": type_line,
        "is_artifact": "Artifact" in type_line,
        "legendary": "Legendary" in type_line,
        "id": data.get("id"),
        "set_code": data.get("set"),
        "released_at": data.get("released_at") or "",
        "image_uri_small": image_uris.get("small", ""),
        "image_uri_normal": image_uris.get("normal", ""),
        "image_uri_large": image_uris.get("large", ""),
        "image_uri_png": image_uris.get("png", ""),
    }


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _match_key(entry: dict[str, Any]) -> tuple[str, Optional[int], Optional[int], tuple[str, ...]]:
    return (entry["name"].casefold(), entry["power"], entry["toughness"], tuple(entry["colors"]))


def build_library(rows: Iterator[dict[str, Any]]) -> list[dict[str, Any]]:
    """One representative entry per (name, power, toughness, colors) combo.

    Prefers the earliest `released_at` printing — the original, most
    "canonical" art for that token rather than whichever reprint happened to
    sort last, with the set code as a stable tie-break for same-day prints.
    """
    best: dict[tuple, dict[str, Any]] = {}
    seen = 0
    for data in rows:
        entry = _extract(data)
        if entry is None:
            continue
        seen += 1
        key = _match_key(entry)
        current = best.get(key)
        if current is None:
            best[key] = entry
            continue
        current_sort = (current["released_at"] or "9999-99-99", current["set_code"] or "")
        new_sort = (entry["released_at"] or "9999-99-99", entry["set_code"] or "")
        if new_sort < current_sort:
            best[key] = entry
    print(f"Scanned {seen} token printings, {len(best)} distinct (name, P/T, colors) combos.")
    return sorted(best.values(), key=lambda e: (e["name"].casefold(), e["power"] or 0, e["toughness"] or 0))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="output JSON path")
    parser.add_argument(
        "--dump-cache", type=Path, default=None,
        help="persist/reuse the raw gzip dump at this path instead of a throwaway temp file",
    )
    args = parser.parse_args()

    rows = _download_filtered(args.dump_cache)
    library = build_library(rows)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        json.dump(library, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {len(library)} token art entries to {args.out}")


if __name__ == "__main__":
    main()
