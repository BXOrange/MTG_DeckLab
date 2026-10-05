from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _command_beacon() -> list[AbilitySpec]:
    """Land
    {T}: Add {C}.
    {T}, Sacrifice this land: Put your commander into your hand from the
    command zone.

    — MEC-43 round 4D. The mana ability needs no catalogue entry. The
    second is the new `PutCommanderIntoHandEffect` (RULE 903.7) — the
    reverse direction of the far more common "return to the command
    zone" replacement family, a plain zone move for every commander
    currently sitting in this ability's own controller's command zone.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("put_commander_into_hand", {})],
            cost={"text": "{T}, Sacrifice this land"},
        ),
    ]


register("Command Beacon", _command_beacon)
