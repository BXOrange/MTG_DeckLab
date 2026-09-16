from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _an_offer_you_cant_refuse() -> list[AbilitySpec]:
    """Counter target noncreature spell. Its controller creates two Treasure
    tokens.

    — An Offer You Can't Refuse. ENG-37 B3: a `seq` of `counter`
    (``noncreature``) then `create_token` for two Treasures with
    ``creators="previous_target_controller"``. As a bare named token with no
    inline stats, `create_token` now pulls the **curated** Treasure from the
    token database — so its "{T}, Sacrifice this artifact: Add one mana of any
    colour" ability *is* bound, which the retired ``counter_create_token``
    synthesise path couldn't do.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "counter", "params": {"noncreature": True}},
                {"type": "create_token", "params": {
                    "token_name": "Treasure", "count": 2,
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("An Offer You Can't Refuse", _an_offer_you_cant_refuse)
