from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pilgrim_of_justice() -> list[AbilitySpec]:
    """Protection from red
    {W}, Sacrifice this creature: The next time a red source of your choice
    would deal damage this turn, prevent that damage.

    — Protection is the ordinary RULE 702 keyword fold-in (unaffected by
    this registration). The card's own text omits "to you" (an older,
    pre-templating-standardization printing) — read the same way this
    repo's Penance/Seasoned Tactician entries do, as protecting the
    activating player.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "R"}, "amount": "all",
            })],
            cost={"text": "{W}, Sacrifice ~"},
        ),
    ]


register("Pilgrim of Justice", _pilgrim_of_justice)
