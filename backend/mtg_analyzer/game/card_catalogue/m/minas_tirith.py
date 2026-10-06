from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "…if you attacked with two or more creatures this turn".
_MIN_ATTACKERS = 2


def _minas_tirith() -> list[AbilitySpec]:
    """Minas Tirith enters tapped unless you control a legendary creature.
    {T}: Add {W}.
    {1}{W}, {T}: Draw a card. Activate only if you attacked with two or more creatures this turn.

    — PLAY-ALL (Hope to the last). The conditional enters-tapped and the mana ability come from the oracle text (as for
    Windbrisk Heights); the draw is gated by an ``activation_condition`` on the new ``creatures_you_attacked_with_this_turn``
    count (distinct creatures the controller declared as attackers, RULE 508.1a).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{1}{w}, {t}", "activation_condition": {
                "kind": "control_count", "selector": "creatures_you_attacked_with_this_turn", "min": _MIN_ATTACKERS,
            }},
        ),
    ]


register("Minas Tirith", _minas_tirith)
