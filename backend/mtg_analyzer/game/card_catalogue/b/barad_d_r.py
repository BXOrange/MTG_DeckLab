from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "Activate only if a creature died this turn" -- at least one creature death on `GameState.creatures_died_this_turn`.
_MIN_CREATURE_DEATHS = 1


def _barad_d_r() -> list[AbilitySpec]:
    """Barad-dûr enters tapped unless you control a legendary creature.
    {T}: Add {B}.
    {X}{X}{B}, {T}: Amass Orcs X. Activate only if a creature died this turn.

    The enters-tapped replacement and the mana ability come from the oracle text (as for Minas Tirith); only the
    X-cost amass is authored. ``"count": "x"`` rides the ``{X}{X}`` cost's sentinel (``RulesEngine._substitute_x``,
    RULE 107.3), and the gate is the ``creatures_died_this_turn`` tally.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("amass", {"subtype": "Orc", "count": "x"})],
            cost={"text": "{X}{X}{B}", "tap": True, "activation_condition": {
                "kind": "control_count", "selector": "creatures_died_this_turn", "min": _MIN_CREATURE_DEATHS,
            }},
        ),
    ]


register("Barad-dûr", _barad_d_r)
