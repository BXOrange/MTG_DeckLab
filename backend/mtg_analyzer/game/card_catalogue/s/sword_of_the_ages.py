"""Sword of the Ages."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sword_of_the_ages():
    """This artifact enters tapped.
    {T}, Sacrifice this artifact and any number of creatures you control: This artifact deals X damage to any target,
    where X is the total power of the creatures sacrificed this way, then exile this artifact and those creature cards.

    MEC-169 (RULE 601.2b / 602.2b, 608.2h): the cost announces how many creatures join the Sword
    (`sacrifice_count [SACRIFICE_COUNT_ANY, "creature"]`, zero allowed) and snapshots each one's last-known power as it
    leaves; the damage reads that total (`cost_referent_sacrificed_creature_power`: the Sword itself is no creature, so
    only creatures count) and `exile_cost_sacrificed` then finds the Sword and those creature cards in the graveyard by
    their recorded graveyard visits (RULE 400.7).
    """
    return [AbilitySpec("activated", [
        EffectSpec("bind", {
            "name": "n",
            "amount": {"kind": "count_selector", "selector": "cost_referent_sacrificed_creature_power"},
            "effects": [{"type": "damage", "params": {"amount": "$n", "target_kind": "any"}}],
        }),
        EffectSpec("exile_cost_sacrificed", {"card_type": "creature", "include_source": True}),
    ], cost={"text": "{T}, Sacrifice ~ and any number of creatures you control"})]


register("Sword of the Ages", _sword_of_the_ages)
