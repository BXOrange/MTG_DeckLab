from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-40: cEDH Rocco's remaining gaps, done to completion
# ---------------------------------------------------------------------------


def _academy_rector() -> list[AbilitySpec]:
    """Academy Rector (Creature — Human Cleric, {3}{W})

    "When this creature dies, you may exile it. If you do, search your
    library for an enchantment card, put that card onto the battlefield,
    then shuffle."

    The "you may X. If you do, Y." shape collapses to the ability's own
    `optional=True` (the same idiom Ranger-Captain of Eos's ETB and
    Necromancy's reanimate already use) since there's no *further*
    decision point between the exile and the search — declining the whole
    ability leaves Academy Rector undisturbed in the graveyard.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile", {"target_kind": None}),
                EffectSpec("search", {"criteria": {"type": "enchantment"}, "destination": "battlefield"}),
            ],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            optional=True,
        ),
    ]


register("Academy Rector", _academy_rector)
