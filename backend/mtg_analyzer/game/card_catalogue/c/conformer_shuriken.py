from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _power_of(of: str) -> dict:
    return {"kind": "characteristic", "characteristic": "power", "of": of}


def _conformer_shuriken() -> list[AbilitySpec]:
    """Equipped creature has "Whenever this creature attacks, tap target creature defending player controls. If that creature has greater power than this creature, put a number of +1/+1 counters on this creature equal to the difference."
    Equip {2}

    — PLAY-ALL (Limit Break). `grant_triggered_ability` over the attached permanent (an ATTACKS trigger): `tap` a creature the defending player controls, then an
    `if_else` on ``amount_compare`` (the tapped creature's power > this creature's) over a `bind` of the ``abs_diff`` of the two powers into `add_counters`.
    Equip is the keyword's.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_triggered_ability", {
                "affects": "attached_permanent", "trigger_event": "ATTACKS", "condition": {"subject": "self"},
                "grant_effects": [
                    {"type": "tap", "params": {"target_kind": "creature_defending_player_controls"}},
                    {"type": "if_else", "params": {
                        "condition": {
                            "kind": "amount_compare", "op": "gt",
                            "left": _power_of("previous_target"), "right": _power_of("source"),
                        },
                        "then": [{"type": "bind", "params": {
                            "name": "d",
                            "amount": {"kind": "abs_diff", "left": _power_of("previous_target"), "right": _power_of("source")},
                            "effects": [{"type": "add_counters", "params": {"count": "$d", "kind": "+1/+1"}}],
                        }}],
                    }},
                ],
            })],
        ),
    ]


register("Conformer Shuriken", _conformer_shuriken)
