from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from .._shared.pilot import pilot_token
from ...card_registry.core import register

_CREATURES_AND_VEHICLES = {"zone": "battlefield", "of": "you", "filter": {"any_of": [{"card_type": "creature"}, {"subtype": "vehicle"}]}}


def _born_to_drive() -> list[AbilitySpec]:
    """Enchant artifact or creature
    As long as enchanted permanent is a creature, it gets +1/+1 for each creature and/or Vehicle you control.
    Channel — {2}{W}, Discard this card: Create two 1/1 colorless Pilot creature tokens with "This token crews Vehicles as though its power were 2 greater."

    — PLAY-ALL (Shorikai Vehicles). "Enchant" is the keyword catalogue's and the static is the parser's anthem (an ``active_if`` gate on the host being a
    creature, counting creatures and Vehicles you control through an ``any_of`` filter). The Channel ability is the discard-self activation from hand
    (``channel`` cost text) creating two of the shared Pilot token.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": dict(_CREATURES_AND_VEHICLES), "toughness_count": dict(_CREATURES_AND_VEHICLES),
                "active_if": {"kind": "is_card_type", "card_type": "creature", "of": "attached"},
            })],
        ),
        AbilitySpec("activated", [pilot_token(2)], cost={"text": "channel — {2}{w}, discard this card"}),
    ]


register("Born to Drive", _born_to_drive)
