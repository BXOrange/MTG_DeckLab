from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _liquimetal_torque() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}: Target nonland permanent becomes an artifact in addition to its other
    types until end of turn.

    — PLAY-ALL Step 2 (Oops! All Night's Whispers). The mana ability is read off
    the card's text. The second is Kamahl's `grant_until` `type_change` with
    ``add_types: [artifact]`` only (``add_types`` adds and never removes, so the
    permanent keeps its other types) on a `nonland_permanent` target until end of
    turn.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "type_change", "params": {"add_types": ["artifact"]}},
                "duration": "end_of_turn", "target_kind": "nonland_permanent",
            })],
            cost={"text": "{T}"},
        ),
    ]


register("Liquimetal Torque", _liquimetal_torque)
