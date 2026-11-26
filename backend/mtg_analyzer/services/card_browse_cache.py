"""Disposable, versioned coverage results for the card-cache browser."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import OrderedDict
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from threading import Lock, Thread
from typing import Callable

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.cards import support_policy
from mtg_analyzer.services.coverage_db import content_hash

logger = logging.getLogger(__name__)
_WRITE_BATCH = 128
# The parser's content hash includes the card inputs used by this policy.
# Hash the policy once so checking freshness needs no per-card classification.
_POLICY_VERSION = sha256(Path(support_policy.__file__).read_bytes()).hexdigest()


def coverage_key(card: Card) -> str:
    return f"{_POLICY_VERSION}:{content_hash(card)}"


class CardBrowseCache:
    def __init__(self, path: Path | None) -> None:
        self._db = sqlite3.connect(path or ":memory:", check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS browse_coverage "
            "(name TEXT PRIMARY KEY, signature TEXT NOT NULL, result TEXT NOT NULL)"
        )
        self._lock = Lock()
        self._rows = {
            name: (signature, json.loads(result))
            for name, signature, result in self._db.execute("SELECT * FROM browse_coverage")
        }
        self._pending: OrderedDict[tuple[str, str], Card] = OrderedDict()
        self._in_flight: set[tuple[str, str]] = set()
        self._worker: Thread | None = None

    def lookup(self, entries: list[tuple[Card, str]]) -> list[dict | None]:
        with self._lock:
            rows = [self._rows.get(card.name) for card, _ in entries]
        return [
            row[1] if row is not None and row[0] == signature else None
            for row, (_, signature) in zip(rows, entries)
        ]

    def save(self, batch: list[tuple[str, str, dict]]) -> None:
        with self._lock:
            with self._db:
                self._db.executemany(
                    "INSERT OR REPLACE INTO browse_coverage VALUES (?, ?, ?)",
                    [(name, signature, json.dumps(result)) for name, signature, result in batch],
                )
            self._rows.update((name, (signature, result)) for name, signature, result in batch)
            for name, signature, _ in batch:
                key = name, signature
                self._in_flight.discard(key)
                self._pending.pop(key, None)

    def schedule(
        self,
        entries: list[tuple[Card, str]],
        compute: Callable[[Card], dict],
        *,
        prioritize: bool = False,
    ) -> None:
        if not entries:
            return
        with self._lock:
            for card, signature in reversed(entries) if prioritize else entries:
                row = self._rows.get(card.name)
                key = card.name, signature
                if key not in self._in_flight and (row is None or row[0] != signature):
                    self._pending[key] = card
                    if prioritize:
                        self._pending.move_to_end(key, last=False)
            if self._worker is None and self._pending:
                self._worker = Thread(target=self._fill, args=(compute,), daemon=True)
                self._worker.start()

    def _fill(self, compute: Callable[[Card], dict]) -> None:
        batch = []
        try:
            while True:
                with self._lock:
                    if self._pending:
                        (name, signature), card = self._pending.popitem(last=False)
                        self._in_flight.add((name, signature))
                    else:
                        card = None
                if card is None:
                    if batch:
                        self.save(batch)
                        batch = []
                    with self._lock:
                        if not self._pending:
                            self._worker = None
                            return
                    continue
                batch.append((name, signature, compute(card)))
                if len(batch) == _WRITE_BATCH:
                    self.save(batch)
                    batch = []
        except Exception:
            logger.exception("Could not prepare card-cache coverage")
            with self._lock:
                self._in_flight.clear()
                self._worker = None


@lru_cache(maxsize=4)
def browse_cache(path: Path) -> CardBrowseCache:
    return CardBrowseCache(path)
