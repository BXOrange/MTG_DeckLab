"""Card lookup endpoints: single/batch resolution and listing the cache.

Reference: docs/implementation-state/Done_Backend.md "HTTP API foundation"
(`GET /api/cards/search`), docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from mtg_analyzer.api.dependencies import get_card_database, get_deck_database, get_lazy_card_loader
from mtg_analyzer.api.schemas import CardResolveRequest
from mtg_analyzer.game import card_registry
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.parser.oracle.gate import ParseResult, unclaimed_spans
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.residue import split_parts
from mtg_analyzer.services.card_browse_cache import CardBrowseCache, browse_cache, coverage_key
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

router = APIRouter(prefix="/api/cards", tags=["cards"])
logger = logging.getLogger(__name__)

_CARD_POOL_UPDATE_TIMEOUT_SECONDS = 15 * 60
_CARD_POOL_UPDATE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "update_card_pool.py"


def coverage_for(card: Any) -> dict[str, object]:
    """A card's engine-coverage verdict (docs/09 "coverage is the roadmap").

    A hand-authored `card_registry` entry is trusted wholesale, same as
    `specs_for` treats it — `MODELED` with no unclaimed lines regardless of
    what the oracle parser alone would say. Otherwise this is exactly the
    verdict `specs_for` falls back to for binding, so "modeled" here means
    "the engine plays this card's abilities", not just "text parses".
    """
    from mtg_analyzer.models.cards.support_policy import unsupported_reason
    reason = unsupported_reason(card)
    if reason:
        return {"modeled": False, "unsupported": True, "unsupported_reason": reason,
                "source": "policy", "unclaimed": []}
    if card_registry.is_authored_card(card):
        return {"modeled": True, "source": "catalogue", "unclaimed": []}
    result = card_registry.card_coverage(card)  # every half the engine binds, not the front alone (BUG-86)
    return {"modeled": result.modeled, "source": "oracle", "unclaimed": result.unclaimed}


def _oracle_fragment_range(text: str, card: Any, fragment: str) -> tuple[int, int] | None:
    """Find a unique original sentence or connector part, in code points."""
    matches = []
    end = 0
    for separator, part in split_parts(text):
        start = end + len(separator)
        end = start + len(part)
        if normalize(part, card.name, card.keywords) == fragment:
            matches.append((start, end))
    return matches[0] if len(matches) == 1 else None


def _unmodeled_oracle_marks(
    card: Any, unclaimed: list[str],
) -> dict[str, dict[int, tuple[int, int] | None]]:
    """Locate each diagnostic on a unique printed line, then narrow where possible."""
    candidates = []
    for face, face_card in (("front", card), ("back", card.back_face() or card.flip_face())):
        if face_card is None:
            continue
        for index, line in enumerate(face_card.oracle_text.split("\n")):
            canonical = normalize(line, face_card.name, face_card.keywords)
            if canonical:
                candidates.append((face, index, line, canonical, face_card))

    marked: dict[str, dict[int, tuple[int, int] | None]] = {}
    for diagnostic in unclaimed:
        fragment = diagnostic.strip().removeprefix("• ").strip()
        if not fragment:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(fragment) + r"(?!\w)")
        matches = [candidate for candidate in candidates if pattern.search(candidate[3])]
        if len(matches) != 1:
            continue
        face, index, line, canonical, face_card = matches[0]
        [residue] = unclaimed_spans(face_card, ParseResult(unclaimed=[fragment]))
        bounds = None if residue.span == canonical else _oracle_fragment_range(line, face_card, residue.span)
        face_marks = marked.setdefault(face, {})
        if index in face_marks and face_marks[index] != bounds:
            bounds = None
        face_marks[index] = bounds
    return marked


def _cards_referenced_by_decks(database: CardDatabase, decks: DeckDatabase) -> list[Any]:
    """Cached cards referenced by at least one saved deck (any section).

    Only matches what's already cached — like `CardDatabase.list_cards`,
    this never triggers a Scryfall fetch for a deck's uncached cards; it's a
    "browse the cache" view, not a resolver (`GET /api/decks` already keeps
    a deck's cards resolved via `_ensure_identity`/`LazyCardLoader`).
    """
    names: set[str] = set()
    for deck in decks.list_decks():
        parsed = parse_deck_sections(
            deck.commander_text, deck.mainboard_text, deck.sideboard_text, deck.is_cube
        )
        names.update(entry.name for entry in (*parsed.all_cards, *parsed.sideboard))

    seen_ids: set[str] = set()
    cards = []
    for name in names:
        card = database.get_card(name)
        if card is not None and card.id not in seen_ids:
            seen_ids.add(card.id)
            cards.append(card)
    cards.sort(key=lambda c: c.name)
    return cards


@router.get("")
def list_cards(
    scope: str = Query("all", pattern="^(all|decks)$"),
    database: CardDatabase = Depends(get_card_database),
    decks: DeckDatabase = Depends(get_deck_database),
) -> list[dict[str, object]]:
    """Cards in the local cache — for a "browse the cache" view.

    `scope=all` (default) is every cached card, including the full bulk
    Oracle import (docs/09). `scope=decks` narrows that down to cards
    actually referenced by a saved deck, for a much smaller/more relevant
    list once the bulk cache is loaded. Unmodeled lines are zero-based
    within each face. Optional ranges are half-open code-point offsets within
    a line and narrow its highlight when the diagnostic maps to printed text.
    """
    source = _cards_referenced_by_decks(database, decks) if scope == "decks" else database.list_cards()
    cards = []
    for card in source:
        card_dict = card.to_dict()
        coverage = coverage_for(card)
        card_dict["coverage"] = _with_oracle_marks(card, coverage)
        cards.append(card_dict)
    return cards


def _with_oracle_marks(card: Any, coverage: dict, signature: str | None = None) -> dict:
    unclaimed = coverage.get("unclaimed")
    if not unclaimed:
        return coverage
    return {
        **coverage,
        **_oracle_marks_cached(card, signature or coverage_key(card), tuple(unclaimed)),
    }


_MARK_CACHE_LIMIT = 8192
_mark_cache: OrderedDict[tuple[str, tuple[str, ...]], dict] = OrderedDict()
_mark_lock = Lock()


def _oracle_marks_cached(card: Any, signature: str, unclaimed: tuple[str, ...]) -> dict:
    key = signature, unclaimed
    with _mark_lock:
        cached = _mark_cache.get(key)
        if cached is not None:
            _mark_cache.move_to_end(key)
            return cached
    marks = _unmodeled_oracle_marks(card, list(unclaimed))
    result = {
        "unmodeled_lines": {face: sorted(lines) for face, lines in marks.items()},
        "unmodeled_ranges": {
            face: {index: bounds for index, bounds in lines.items() if bounds is not None}
            for face, lines in marks.items()
        },
    }
    with _mark_lock:
        _mark_cache[key] = result
        _mark_cache.move_to_end(key)
        if len(_mark_cache) > _MARK_CACHE_LIMIT:
            _mark_cache.popitem(last=False)
    return result


_TYPE_FLAGS = ("creature", "land", "instant", "sorcery")
_TYPE_WORDS = re.compile(r"\b(planeswalker|battle|artifact|enchantment)\b", re.IGNORECASE | re.ASCII)
_COVERAGE_FILTERS = frozenset(("catalogue", "oracle", "unmodeled", "unsupported"))


def _browse_types(card: Any) -> set[str]:
    return {kind for kind in _TYPE_FLAGS if getattr(card, f"is_{kind}")} | {
        match.lower() for match in _TYPE_WORDS.findall(card.type_line)
    }


def _coverage_bucket(coverage: dict) -> str:
    if coverage.get("unsupported"):
        return "unsupported"
    return coverage["source"] if coverage["modeled"] else "unmodeled"


@lru_cache(maxsize=2)
def _browse_all(database: CardDatabase, revision: tuple[int, int]) -> list:
    return [(card, coverage_key(card), _browse_types(card)) for card in database.list_cards()]


_browse_store_lock = Lock()


@lru_cache(maxsize=4)
def _memory_browse_cache(database: CardDatabase) -> CardBrowseCache:
    return CardBrowseCache(None)


@router.get("/browse")
def browse_cards(
    scope: str = Query("all", pattern="^(all|decks)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(60, ge=1, le=100),
    types: str | None = None,
    colors: str | None = None,
    coverage: str | None = None,
    cmc_min: float | None = Query(None, allow_inf_nan=False),
    cmc_max: float | None = Query(None, allow_inf_nan=False),
    database: CardDatabase = Depends(get_card_database),
    decks: DeckDatabase = Depends(get_deck_database),
) -> dict:
    """One page of the cache browser, with counts across the selected scope."""
    if scope == "decks":
        entries = [
            (card, coverage_key(card), _browse_types(card))
            for card in _cards_referenced_by_decks(database, decks)
        ]
    else:
        entries = _browse_all(database, database.revision())
    # The store owns a work queue. Concurrent first requests must share it.
    with _browse_store_lock:
        path = database.browse_cache_path
        store = browse_cache(path) if path else _memory_browse_cache(database)
    coverage_filter = _COVERAGE_FILTERS if coverage is None else _COVERAGE_FILTERS.intersection(coverage.split(","))
    all_coverage = coverage_filter == _COVERAGE_FILTERS
    type_filter = None if types is None else set(types.split(","))
    color_filter = None if colors is None else set(colors.split(","))
    candidates = [
        (card, signature) for card, signature, card_types in entries
        if (type_filter is None or card_types & type_filter)
        and (color_filter is None or (card.color_identity or {"C"}) & color_filter)
        and (cmc_min is None or card.converted_mana_cost >= cmc_min)
        and (cmc_max is None or card.converted_mana_cost <= cmc_max)
    ]
    verdicts = store.lookup(candidates)
    missing = [entry for entry, verdict in zip(candidates, verdicts) if verdict is None]
    matched = [
        (card, signature, verdict)
        for (card, signature), verdict in zip(candidates, verdicts)
        if all_coverage or (verdict is not None and _coverage_bucket(verdict) in coverage_filter)
    ]
    # Coverage-filtered pages stay pending until their ordering and counts are exact.
    pending = bool(missing and coverage_filter)
    page = matched[offset:offset + limit] if all_coverage or not pending else []
    cards = []
    computed = []
    for card, signature, verdict in page:
        if verdict is None:
            verdict = coverage_for(card)
            computed.append((card.name, signature, verdict))
        cards.append({**card.to_dict(), "coverage": _with_oracle_marks(card, verdict, signature)})
    if computed:
        store.save(computed)
    pending = pending and len(missing) > len(computed)
    if pending:
        store.schedule(missing, coverage_for, prioritize=scope == "decks" or not all_coverage)
    modeled = None
    if not pending:
        modeled = (
            sum(bool(verdict and verdict["modeled"]) for _, _, verdict in matched)
            + sum(bool(verdict["modeled"]) for _, _, verdict in computed)
        )
    return {
        "cards": cards,
        "total": len(entries),
        "matched": len(matched) if all_coverage or not pending else None,
        "modeled": modeled,
        "pending": pending,
    }


@router.get("/coverage-by-set")
def coverage_by_set(
    database: CardDatabase = Depends(get_card_database),
) -> list[dict[str, object]]:
    """Parser/engine coverage aggregated by set, for the Engine-Status tab's
    "Abdeckung nach Set" table (`implementationStatusView.js`).

    Same per-card verdict `GET /api/cards` already computes (`coverage_for`,
    relying on `parse_oracle`'s own per-process memoization to keep repeat
    calls cheap) — just grouped by `Card.set_code` instead of listed per card.
    """
    totals: dict[str, dict[str, int]] = {}
    for card in database.list_cards():
        set_code = card.set_code or "?"
        bucket = totals.setdefault(set_code, {"total": 0, "covered": 0})
        bucket["total"] += 1
        if coverage_for(card)["modeled"]:
            bucket["covered"] += 1

    rows = [
        {
            "setCode": set_code,
            "total": stats["total"],
            "covered": stats["covered"],
            "fraction": (stats["covered"] / stats["total"]) if stats["total"] else 0.0,
        }
        for set_code, stats in totals.items()
    ]
    rows.sort(key=lambda row: row["setCode"])
    return rows


@router.get("/search")
def search_card(
    name: str = Query(..., min_length=1),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    """Resolve a single card by exact name, fetching from Scryfall on first use."""
    result = loader.load_cards([name])
    card = result.cards.get(name)
    if card is None:
        raise HTTPException(status_code=404, detail=f'No card found for "{name}"')
    return card.to_dict()


@router.post("/resolve")
def resolve_cards(
    request: CardResolveRequest,
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
) -> dict[str, object]:
    """Resolve many card names in one round trip (e.g. a whole decklist).

    Batches the underlying Scryfall lookups (LazyCardLoader ->
    ScryfallIntegration.fetch_multiple) rather than requiring one
    /search call per card.
    """
    result = loader.load_cards(request.names)
    return {
        "cards": {name: card.to_dict() for name, card in result.cards.items()},
        "notFound": result.not_found,
    }


@router.post("/update")
def update_card_pool(database: CardDatabase = Depends(get_card_database)) -> dict[str, object]:
    """Refresh the full Scryfall Oracle card pool using the existing importer."""
    try:
        result = subprocess.run(
            [sys.executable, str(_CARD_POOL_UPDATE_SCRIPT)],
            cwd=_CARD_POOL_UPDATE_SCRIPT.parent.parent,
            capture_output=True,
            check=False,
            text=True,
            timeout=_CARD_POOL_UPDATE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("Full Scryfall card-pool update exceeded its time limit.")
        raise HTTPException(
            status_code=504,
            detail="The Scryfall card-pool update timed out. Check the server log and retry.",
        ) from exc

    if result.returncode != 0:
        logger.error(
            "Full Scryfall card-pool update failed (exit %s): %s",
            result.returncode,
            (result.stderr or result.stdout)[-4000:],
        )
        raise HTTPException(
            status_code=502,
            detail="The Scryfall card-pool update failed. Check the server log for details.",
        )

    logger.info("Full Scryfall card-pool update completed: %s", result.stdout[-1000:])
    return {"updated": True, "cachedCardCount": database.count()}
