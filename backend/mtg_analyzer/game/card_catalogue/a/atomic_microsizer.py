from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

# Printed "base power and toughness 1/1".
MICROSIZER_BASE_POWER = 1
MICROSIZER_BASE_TOUGHNESS = 1


def _atomic_microsizer() -> list[AbilitySpec]:
    "Equipped creature gets +1/+0.\nWhenever equipped creature attacks, choose up to one target creature. That creature can't be blocked this turn and has base power and toughness 1/1 until end of turn.\nEquip {2}"
    # RULE 301.5 / 303.4: "equipped creature attacks" follows `attached_to` (subject `attached_permanent`).
    # RULE 115.1a: "up to one target" = an optional single target; declining leaves `previous_targets`
    # empty, so both clauses do nothing. RULE 611.2c / 613.4b: the base-P/T set is a layer-7b `pt_set`
    # parked on exactly the chosen creature by `grant_until` (`previous_subject` = the clause-1 target),
    # so the equipped creature's +1/+0 and any counters still apply on top. RULE 509.1b: `unblockable`.
    return [
        AbilitySpec(
            'static',
            [EffectSpec('anthem', {"power": 1, "toughness": 0, "affects": 'attached_permanent'})],
            raw_text='equipped creature gets +1/+0.',
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("unblockable", {"target_kind": "creature", "count": 1, "optional": True}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn",
                    "previous_subject": True,
                    "static": {"type": "pt_set", "params": {
                        "power": MICROSIZER_BASE_POWER, "toughness": MICROSIZER_BASE_TOUGHNESS,
                    }},
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
            raw_text="whenever equipped creature attacks, choose up to 1 target creature. that creature can't be blocked this turn and has base power and toughness 1/1 until end of turn.",
        ),
    ]


register('Atomic Microsizer', _atomic_microsizer)
