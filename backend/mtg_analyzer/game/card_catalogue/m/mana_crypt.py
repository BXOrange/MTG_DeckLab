from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mana_crypt() -> list[AbilitySpec]:
    """At the beginning of your upkeep, flip a coin. If you lose the flip,
    this artifact deals 3 damage to you.
    {T}: Add {C}{C}.

    — MEC-42. `CoinFlipEffect`'s already-established "damage with
    ``selector='controller'``" shape (Mana Vault's own "deals 1 damage to
    you", Vivi B4 batch) at Mana Crypt's own printed amount; no win
    branch (losing the flip is the only outcome with a consequence). The
    mana ability needs no catalogue entry at all — `game/mana_abilities.py`
    reads a card's plain "{T}: Add …" text unconditionally, independent of
    catalogue registration (confirmed by Lazotep Quarry, MEC-41).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("coin_flip", {
                "lose_effects": [{"type": "damage", "params": {"selector": "controller", "amount": 3}}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Mana Crypt", _mana_crypt)
