
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chronomantic_escape() -> list[AbilitySpec]:
    "Until your next turn, creatures can't attack you. Exile Chronomantic Escape with three time counters on it.\nSuspend 3—{2}{W} (Rather than cast this card from your hand, you may pay {2}{W} and exile it with three time counters on it. At the beginning of your upkeep, remove a time counter. When the last is removed, you may cast it without paying its mana cost.)"
    return [
        # RULE 508.1 / 611.2b: a floating "can't attack you" bar for its controller, ending as their next turn
        # begins; then the resolving spell exiles itself with three time counters (Suspend is the engine-backed keyword).
        AbilitySpec("spell_effect", [
            EffectSpec("grant_until", {
                "static": {"type": "cant_attack_defender", "params": {}},
                "duration": "your_next_turn", "target_kind": None,
            }),
            EffectSpec("exile_self_with_counters", {"kind": "time", "count": 3}),
        ]),
    ]


register('Chronomantic Escape', _chronomantic_escape)
