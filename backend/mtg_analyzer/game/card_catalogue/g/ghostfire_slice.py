from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ghostfire_slice() -> list[AbilitySpec]:
    """Devoid (This card has no color.)
    This spell costs {2} less to cast if an opponent controls a
    multicolored permanent.
    Ghostfire Slice deals 4 damage to any target.

    — MEC-12 (fifth pass): a genuine gap, not just a missing handler —
    `game/continuous.self_cost_reduction_for`/`EffectRegistry`'s
    ``"cost_reduction"`` factory both already support an `active_if` gate
    (this pass's own primitive, alongside `multicolored_permanents_you_
    control`'s new `count_selector`), but the oracle-text *parser* only
    ever reaches that static path for a **permanent** — `parser/oracle/
    segmenter.py`'s `allow_spell_effect` gate routes every clause on a
    true instant/sorcery through the one-shot `spell_effect` dispatch
    instead, which has no static-ability shape to emit at all. Hand-
    authored as two independent `AbilitySpec`s instead of widening that
    routing (a real but separate architectural gap — `attach_to_object`'s
    `spell_effect` branch would need to split a `StaticAbility` out of its
    bound effects into `obj.static_effects`, which no other card needs
    yet): ``"static"`` doesn't care what kind of card its owner is, so a
    hand-authored `AbilitySpec("static", …)` on an Instant reaches
    `self_cost_reduction_for` exactly like Embercleave's parsed one does
    on an Equipment.

    Simplified: Devoid (a purely cosmetic colour-identity keyword with no
    gameplay effect this engine's card model can't already represent via
    printed colourless mana cost) isn't separately modeled.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 2,
                "active_if": {
                    "kind": "opponent_count",
                    "selector": "multicolored_permanents_you_control",
                    "min": 1,
                },
            })],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"target_kind": "any", "amount": 4})],
        ),
    ]


register("Ghostfire Slice", _ghostfire_slice)
