"""Shared count selector for the Federation ability word (RULE 205.3m creature types, RULE 702.73a Changeling).

"The number of creature types among non-Borg creatures you control": each creature type counts once however many
creatures share it, and a Borg creature -- including every changeling, which has every creature type -- contributes
nothing, so a type it shares with a non-Borg creature is counted only through that other creature. The count is read
through the derived creature types (`continuous.creature_types_of`), so layer-4 type changes (RULE 613) apply.
"""
from __future__ import annotations

from typing import Any

#: The structured count selector (`continuous.count_selector`) the parser also emits for the same phrase.
CREATURE_TYPES_AMONG_NON_BORG_CREATURES_YOU_CONTROL: dict[str, Any] = {
    "zone": "battlefield", "of": "you",
    "filter": {"without_subtype": "borg", "card_type": "creature"},
    "distinct": "creature_type",
}
