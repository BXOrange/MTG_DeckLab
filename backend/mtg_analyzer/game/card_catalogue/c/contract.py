from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Scriv, the Obligator (Aura token with a quoted ability) — PAR-60
# ===========================================================================
# Composed `create_token` + `attach` effects (RULE 115); the
# token's quoted ability is authored under its token name ("Contract"),
# picked up by the `bind_from_catalogue` `create_token` already runs. The
# quoted ability reuses `LoseLifeEffect` ``selector="attached_permanent_
# controller"`` (Parasitic Impetus family).
# Documented simplification: the quoted ability's "+2/+0 if it's attacking
# one of your opponents. Otherwise, …" fork is dropped — the drain (the
# meaningful downside of an Aura forced onto an opponent's creature) is
# always applied.


def _contract_token() -> list[AbilitySpec]:
    """(Scriv's "Contract" Aura token.)
    Whenever enchanted creature attacks, its controller loses 2 life."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount": 2, "selector": "attached_permanent_controller"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Contract", _contract_token)
