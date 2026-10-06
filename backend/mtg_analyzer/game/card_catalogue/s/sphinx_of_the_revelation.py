from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sphinx_of_the_revelation() -> list[AbilitySpec]:
    """Flying, lifelink
    Whenever you gain life, you get that many {E} (energy counters).
    {W}{U}{U}, {T}, Pay X {E}: Draw X cards.

    — PLAY-ALL (Hope to the last). Keywords and the life-gain trigger are the parser's. **Simplification:** X energy is
    chosen as the ability resolves (the variable `pay_energy_then`, minimum 0) rather than paid as an announced cost.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"kind": "energy", "amount_from_trigger_event": "amount"})],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pay_energy_then", {"amount": 0, "variable": True, "effects": [
                {"type": "draw", "params": {"count": "x"}},
            ]})],
            cost={"text": "{w}{u}{u}, {t}"},
        ),
    ]


register("Sphinx of the Revelation", _sphinx_of_the_revelation)
