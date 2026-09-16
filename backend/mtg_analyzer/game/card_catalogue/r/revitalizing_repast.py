from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _revitalizing_repast() -> list[AbilitySpec]:
    """Put a +1/+1 counter on target creature. It gains indestructible
    until end of turn.

    — Eliferate deck batch. One real target (the counter effect); the
    keyword grant reuses it via `grant_until`'s `previous_subject` pronoun
    idiom rather than declaring a second target of its own.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("add_counters", {"kind": "+1/+1", "amount": 1, "target_kind": "creature"}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "previous_subject": True,
                    "static": {"type": "grant_keyword", "params": {"keywords": ["indestructible"]}},
                }),
            ],
        ),
    ]


register("Revitalizing Repast", _revitalizing_repast)
register("Revitalizing Repast // Old-Growth Grove", _revitalizing_repast)
