from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kitesail_larcenist():
    """Flying, ward {1}
    When this creature enters, for each player, choose up to one other target artifact or creature that player controls. For as long as this creature remains on the battlefield, the chosen permanents become Treasure artifacts with "{T}, Sacrifice this artifact: Add one mana of any color" and lose all other abilities.
    """
    return [AbilitySpec("triggered", [EffectSpec("treasure_transformation_until_source_leaves", {"excludes_source": True})],
        trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}})]


register("Kitesail Larcenist", _kitesail_larcenist)
