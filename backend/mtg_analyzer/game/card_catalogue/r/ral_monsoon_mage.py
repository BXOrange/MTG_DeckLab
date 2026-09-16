from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ral_monsoon_mage() -> list[AbilitySpec]:
    """Whenever you cast an instant or sorcery spell during your turn, flip
    a coin. If you lose the flip, ~ deals 1 damage to you. If you win the
    flip, you may exile ~. If you do, return him to the battlefield
    transformed under his owner's control.

    — Vivi B4 batch. New `CoinFlipEffect`/`RulesEngine.coin_flip` (RULE
    705.1, previously built but unused by any card) branches into the loss
    (``damage`` with the existing ``selector="controller"``, Mana Vault's
    own "deals 1 damage to you" shape) and win (`exile_return_transformed`,
    RULE 400.7/712.8's existing transform-via-zone-change primitive)
    halves. "During your turn" reuses `phase_relation="you"` — built for
    RULE 500.7 "at the beginning of your `<step>`" triggers, but its
    predicate only checks whose turn it currently is, so it gates a
    SPELL_CAST trigger exactly as well. **Documented simplification**:
    "you may exile ~" is modeled as unconditional (always taken) — the
    same accepted simplification `CoinFlipEffect` itself already documents.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("coin_flip", {
                "lose_effects": [{"type": "damage", "params": {"selector": "controller", "amount": 1}}],
                "win_effects": [{"type": "exile_return_transformed", "params": {}}],
            })],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "you"},
                "spell_card_types": ["instant", "sorcery"],
                "phase_relation": "you",
            },
        ),
    ]


register("Ral, Monsoon Mage", _ral_monsoon_mage)
