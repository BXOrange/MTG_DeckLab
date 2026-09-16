from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# MEC-41: [cEDH] Glarb Bloomsday's remaining 8 gaps, done to completion


def _ad_nauseam() -> list[AbilitySpec]:
    """Reveal the top card of your library and put that card into your
    hand. You lose life equal to its mana value. You may repeat this
    process any number of times.

    — MEC-41. New `reveal_top_hand_lose_life_loop`/`RulesEngine.request_
    reveal_top_hand_lose_life_loop` — the engine's second open-ended,
    self-re-opening loop (see its own docstring for why it's a genuinely
    distinct shape from Lim-Dûl's Vault's `look_top_pay_life_loop`, not a
    parameterization of it): life lost varies per revealed card instead of
    a flat cost, the destination is hand instead of back into the library,
    and nothing stops the loop at 0 life (RULE 118.4 doesn't apply to a
    life-*loss* effect, only to paying life as a cost) — SBAs simply
    aren't checked mid-resolution.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("reveal_top_hand_lose_life_loop", {})],
        ),
    ]


register("Ad Nauseam", _ad_nauseam)
