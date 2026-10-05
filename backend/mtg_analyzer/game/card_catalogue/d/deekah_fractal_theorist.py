from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _deekah_fractal_theorist() -> list[AbilitySpec]:
    """Magecraft — Whenever you cast or copy an instant or sorcery spell,
    create a 0/0 green and blue Fractal creature token. Put X +1/+1 counters
    on it, where X is that spell's mana value.
    {3}{U}: Target creature token can't be blocked this turn.

    Documented simplification: the {3}{U} unblockable activated ability is
    not modeled; "or copy" is covered by the `SPELL_CAST` trigger (no
    separate spell-copy event bus)."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Fractal", "power": 0, "toughness": 0,
                "colors": ["G", "U"], "subtypes": ["Fractal"],
                "extra_counters": {"kind": "+1/+1", "count_from_trigger_event": "mana_value"},
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
            },
        ),
    ]


register("Deekah, Fractal Theorist", _deekah_fractal_theorist)
