from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _contamination() -> list[AbilitySpec]:
    """At the beginning of your upkeep, sacrifice this enchantment unless
    you sacrifice a creature.
    If a land is tapped for mana, it produces {B} instead of any other
    type and amount.

    — MEC-43. The upkeep clause is already fully `MODELED` by the
    oracle-text parser (`sacrifice_unless_pay`); reused as-is. The second
    clause is an exact param match for `mana_type_override` (built for
    Damping Sphere's "if a land is tapped for 2 or more mana, {C}
    instead") — unscoped (``affects="all_lands"``, matching Damping
    Sphere's own unqualified reach) with ``min_amount=1`` instead of 2
    and ``to="B"`` instead of ``"C"``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_unless_pay", {"cost": "sacrifice a creature"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("mana_type_override", {"min_amount": 1, "to": "B"})],
        ),
    ]


register("Contamination", _contamination)
