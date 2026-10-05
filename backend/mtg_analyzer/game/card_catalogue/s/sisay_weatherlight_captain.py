from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sisay_weatherlight_captain() -> list[AbilitySpec]:
    """Sisay gets +1/+1 for each color among other legendary permanents you
    control.
    {W}{U}{B}{R}{G}: Search your library for a legendary permanent card with
    mana value less than Sisay's power, put that card onto the battlefield,
    then shuffle.

    — PLAY-ALL Step 2 (SpongeBob). The anthem is Conqueror's Flail's per-color
    `anthem` (``power_count``/``toughness_count``, here ``affects: self``) over
    the new ``colors_among_other_legendary_permanents_you_control`` selector
    (`continuous.count_selector`). The activated ability is a `search` whose
    mana-value bound is dynamic (``mana_value_from``, Beseech the Queen's
    shape) over the ``source_power`` count selector with ``plus: -1`` — "less
    than Sisay's power" is "at most power − 1" — evaluated as the search opens.
    "Legendary permanent card" is the type word Legendary with instants and
    sorceries excluded (``without_type``).
    """
    selector = "colors_among_other_legendary_permanents_you_control"
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "self", "power": 1, "toughness": 1,
                "power_count": selector, "toughness_count": selector,
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Legendary", "without_type": ["Instant", "Sorcery"]},
                "destination": "battlefield",
                "mana_value_from": {"source": "count_selector", "count_selector": "source_power", "plus": -1},
            })],
            cost={"text": "{W}{U}{B}{R}{G}"},
        ),
    ]


register("Sisay, Weatherlight Captain", _sisay_weatherlight_captain)
