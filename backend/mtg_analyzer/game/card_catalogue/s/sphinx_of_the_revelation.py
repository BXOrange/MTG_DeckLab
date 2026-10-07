from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from ...costs import PAY_ENERGY_X


def _sphinx_of_the_revelation() -> list[AbilitySpec]:
    """Flying, lifelink
    Whenever you gain life, you get that many {E} (energy counters).
    {W}{U}{U}, {T}, Pay X {E}: Draw X cards.

    — PLAY-ALL (Hope to the last). Life gain supplies energy. The draw
    ability announces X and pays that energy as part of activation before
    opponents can respond; zero is legal and draw uses the announced X.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"kind": "energy", "amount_from_trigger_event": "amount"})],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": "x"})],
            cost={"text": "{w}{u}{u}, {t}", "pay_energy": PAY_ENERGY_X},
        ),
    ]


register("Sphinx of the Revelation", _sphinx_of_the_revelation)
