from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gempalm_polluter() -> list[AbilitySpec]:
    """Cycling {B}{B}
    When you cycle this card, you may have target player lose life equal to the number of Zombies on the battlefield.

    — PLAY-ALL Step 2 (Eternal Might). Cycling is a printed keyword; the bonus is the parser's CYCLED self-trigger
    shape. `choose_targets` announces the player and a `bind` measures every Zombie on the battlefield (``of:
    "any"``) into `lose_life` for that player (`previous_player`). The "you may" is the trigger's own optional
    target (declining the target declines the loss).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "choose_targets", "params": {"kinds": ["player"], "optional": True}},
                {"type": "bind", "params": {
                    "name": "n",
                    "amount": {"kind": "count_selector", "selector": {
                        "zone": "battlefield", "of": "any", "filter": {"card_type": "creature", "subtype": "zombie"}}},
                    "effects": [{"type": "lose_life", "params": {"amount": "$n", "previous_subject": True}}],
                }},
            ]})],
            trigger={"event": "CYCLED", "condition": {"subject": "self"}},
        ),
    ]


register("Gempalm Polluter", _gempalm_polluter)
