from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-43 round 4D — control / zone changes / entry-choice statics
# ---------------------------------------------------------------------------


def _homeward_path() -> list[AbilitySpec]:
    """Land
    {T}: Add {C}.
    {T}: Each player gains control of all creatures they own.

    — MEC-43 round 4D. The mana ability needs no catalogue entry (a plain
    "{T}: Add {C}." is recognized generically by `mana_abilities_for`).
    The second ability is the new `RegainControlOfOwnedCreaturesEffect`
    (RULE 108.4/110.2) — a straight `GameObject.controller_id` write back
    to each creature's own owner, the untargeted "every player at once"
    sibling of `ExchangeControlEffect`'s single-pair swap.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("regain_control_of_owned_creatures", {})],
            cost={"text": "{T}"},
        ),
    ]


register("Homeward Path", _homeward_path)
