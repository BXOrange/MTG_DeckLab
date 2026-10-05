from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _giada_font_of_hope() -> list[AbilitySpec]:
    """Flying, vigilance
    Each other Angel you control enters with an additional +1/+1 counter on it for each Angel you already control.
    {T}: Add {W}. Spend this mana only to cast an Angel spell.

    — PLAY-ALL (Calling All Angels). Keywords and the restricted mana ability come from the card text. The counters are
    the `extra_etb_counter` static (Metallic Mimic's/Master Chef's entry-counter grant) filtered to Angels, counted off a
    structured "Angels you control" selector — read as the Angel enters, so it is not yet counted ("already control").
    """
    return [
        AbilitySpec("static", [EffectSpec("extra_etb_counter", {
            "kind": "+1/+1", "filter": {"subtype": "angel"}, "other": True,
            "count_selector": {
                "zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "subtype": "angel"},
            },
        })]),
    ]


register("Giada, Font of Hope", _giada_font_of_hope)
