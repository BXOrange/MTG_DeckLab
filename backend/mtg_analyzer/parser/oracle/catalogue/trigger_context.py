"""Tails and scopes every trigger head shares (PAR-119).

Whose turn, and whose permanent, are properties of *any* trigger — a cast, an
enter, an attack — so they are parsed once here and read by `spell_phrase` and
`object_trigger_head` alike. Pure — no `game/` imports.
"""

from __future__ import annotations

from typing import Any, Optional

#: "during <whose> turn" → the event-agnostic ``phase_relation`` trigger gate.
PHASE_TAILS: list[tuple[str, dict[str, Any]]] = [
    ("during your turn", {"phase_relation": "you"}),
    ("during an opponent's turn", {"phase_relation": "not_you"}),
    ("during each opponent's turn", {"phase_relation": "not_you"}),
]

#: Controller phrase after a subject noun → the group condition's ``controller``
#: (`effect_binder._build_group_ok`: "you" / "not_you"). "You don't control" is
#: read as "not you" — it also covers a teammate, which no printed head needs
#: to tell apart from an opponent.
CONTROLLER_TAILS: list[tuple[str, str]] = [
    ("you don't control", "not_you"),
    ("you control", "you"),
    ("an opponent controls", "not_you"),
    ("your opponents control", "not_you"),
]


def consume(
    tail: str, table: list[tuple[str, dict[str, Any]]]
) -> tuple[Optional[dict[str, Any]], str]:
    """The keys for the table entry ``tail`` starts with, and what is left."""
    for text, keys in table:
        if tail.startswith(text):
            return keys, tail[len(text):].strip()
    return None, tail
