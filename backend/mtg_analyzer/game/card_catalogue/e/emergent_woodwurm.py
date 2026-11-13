from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _emergent_woodwurm() -> list[AbilitySpec]:
    """Backup 3 (When this creature enters, put three +1/+1 counters on target creature. If that's another creature, it gains the following ability until end of turn.)
    Whenever this creature attacks, look at the top X cards of your library, where X is its power. You may put a permanent card with mana value X or less from among them onto the battlefield. Put the rest on the bottom of your library in a random order.
    """
    return [AbilitySpec("triggered", [EffectSpec("bind", {
        "name": "power", "amount": {"kind": "characteristic", "of": "source", "characteristic": "power"},
        "effects": [{"type": "inspect_top_choose", "params": {
            "count": "$power", "action": "library_to_battlefield", "optional": True,
            "criteria": {"type": ["artifact", "battle", "creature", "enchantment", "land", "planeswalker"],
                         "max_mana_value": "$power"},
            "rest_destination": "library_bottom_random",
        }}],
    })], trigger={"event": "ATTACKS", "condition": {"subject": "self"}})]


register("Emergent Woodwurm", _emergent_woodwurm)
