from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _legolass_quick_reflexes() -> list[AbilitySpec]:
    """Split second (As long as this spell is on the stack, players can't
    cast spells or activate abilities that aren't mana abilities.)
    Untap target creature. Until end of turn, it gains hexproof, reach,
    and "Whenever this creature becomes tapped, it deals damage equal to
    its power to up to one target creature."

    — MEC-43 round 4A. Split Second was already parser-recognized (RULE
    702.61, a flag keyword) but genuinely inert — no card had ever needed
    its actual restriction enforced before. Built as
    `continuous.split_second_active` (any spell with the keyword on
    `GameState.stack`), checked at the very top of both `GameEngine.
    can_cast`/`can_activate` — mana abilities never call either (RULE
    605.3b keeps them off the stack), so neither gate needs an exemption.
    The untap+grant clause chains three effects off one real target
    (`TapEffect.untap`) via `PumpEffect`/`GrantUntilEffect`'s existing
    ``previous_subject`` pronoun mode (`GameContext.previous_targets`):
    the temporary keywords ride the ordinary "until end of turn" `temp_*`
    path, and the granted triggered ability is `grant_triggered_ability`'s
    already-general layer-6 machinery (Dionus, Elvish Archdruid's own
    shape) wrapped in `GrantUntilEffect` for its "until end of turn"
    lifespan — `damage_equal_to_power`'s ``dealer_kind=None`` reads
    whichever creature the grant actually landed on (late-bound
    `effect.source`, `_apply_effects_partitioned`'s existing mechanism),
    not the spell itself.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("tap", {"untap": True, "target_kind": "creature"}),
                EffectSpec("pump", {"keywords": ["hexproof", "reach"], "previous_subject": True}),
                EffectSpec("grant_until", {
                    "target_kind": None, "previous_subject": True, "duration": "end_of_turn",
                    "static": {
                        "type": "grant_triggered_ability",
                        "params": {
                            "trigger_event": "TAPPED",
                            "grant_effects": [
                                {"type": "damage_equal_to_power", "params": {
                                    "target_kind": "creature", "optional": True,
                                }},
                            ],
                        },
                    },
                }),
            ],
        ),
    ]


register("Legolas's Quick Reflexes", _legolass_quick_reflexes)
