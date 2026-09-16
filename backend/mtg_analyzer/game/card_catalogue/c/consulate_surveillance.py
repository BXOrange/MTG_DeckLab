from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _consulate_surveillance() -> list[AbilitySpec]:
    """When this enchantment enters, you get {E}{E}{E}{E} (four energy
    counters).
    Pay {E}{E}: Prevent all damage that would be dealt to you this turn by
    a source of your choice.

    — The ETB energy grant already parses on its own (``"add_player_
    counters"``); repeated here since a hand-authored registration replaces
    the parser's output wholesale rather than merging with it. The shield
    is the ordinary Circle of Protection-shaped chooser
    (`RequestPreventDamageSourceEffect`), paid with energy instead of mana
    — "Pay {E}{E}" is an ordinary `ActivationCost` energy-pip cost text,
    already generic (Guide of Souls' own precedent).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 4, "kind": "energy"})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"text": "Pay {E}{E}"},
        ),
    ]


register("Consulate Surveillance", _consulate_surveillance)
