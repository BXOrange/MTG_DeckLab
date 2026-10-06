from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _summon_magus_sisters() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)
    I, II, III — Choose one at random —
    • Combine Powers! — Put three +1/+1 counters on target creature.
    • Defense! — Put a shield counter on target creature. You gain 3 life.
    • Fight! — This creature fights up to one target creature an opponent controls.
    Haste

    — PLAY-ALL (Counter Blitz). Haste is the keyword. One chapter trigger over chapters I–III with Umaro's ``random`` modal block: three `add_counters`
    (target creature), a shield `add_counters` plus `gain_life`, and Kogla's source `fight` against an optional creature an opponent controls.
    """
    return [
        AbilitySpec(
            "triggered", [],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1, 2, 3]},
            modes={"choose": 1, "random": True, "options": [
                [EffectSpec("add_counters", {"count": 3, "kind": "+1/+1", "target_kind": "creature"})],
                [
                    EffectSpec("add_counters", {"count": 1, "kind": "shield", "target_kind": "creature"}),
                    EffectSpec("gain_life", {"amount": 3}),
                ],
                [EffectSpec("fight", {"fighter_kind": None, "other_kind": "creature_you_dont_control", "optional": True})],
            ], "descriptions": ["Combine Powers!", "Defense!", "Fight!"]},
        ),
    ]


register("Summon: Magus Sisters", _summon_magus_sisters)
