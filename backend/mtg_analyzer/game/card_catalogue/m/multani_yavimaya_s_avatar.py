from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "each land you control" and "each land card in your graveyard" — the two terms of Multani's count.
_LANDS_YOU_CONTROL = {"zone": "battlefield", "of": "you", "filter": {"card_type": "land"}}
_LAND_CARDS_IN_YOUR_GRAVEYARD = {"zone": "graveyard", "of": "you", "filter": {"card_type": "land"}}
_LAND_COUNT = {"terms": [_LANDS_YOU_CONTROL, _LAND_CARDS_IN_YOUR_GRAVEYARD]}


def _multani_yavimaya_s_avatar() -> list[AbilitySpec]:
    """Reach, trample
    Multani gets +1/+1 for each land you control and each land card in your
    graveyard.
    {1}{G}, Return two lands you control to their owner's hand: Return this
    card from your graveyard to your hand.

    — PLAY-ALL Step 2 (World Shaper). Reach/trample are keyword fold-ins and the
    graveyard-return ability is the parser's own claim, reproduced. The pump is
    the parser's per-land `anthem` shape (``power_count``/``toughness_count``)
    with a `terms` sum (PAR-120's count arithmetic) of the two structured
    selectors: lands on the battlefield you control plus land cards in your
    graveyard.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "self", "power": 1, "toughness": 1,
                "power_count": dict(_LAND_COUNT), "toughness_count": dict(_LAND_COUNT),
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_self_from_graveyard_to_hand", {})],
            cost={"text": "{1}{g}, return 2 lands you control to their owner's hand"},
        ),
    ]


register("Multani, Yavimaya's Avatar", _multani_yavimaya_s_avatar)
