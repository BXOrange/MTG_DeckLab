from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _containment_priest() -> list[AbilitySpec]:
    """Flash
    If a nontoken creature would enter and it wasn't cast, exile it instead.

    — MEC-43 round 4D. Flash is a plain flag keyword (Scryfall-recognized,
    no catalogue entry needed). The replacement effect is the new
    `"uncast_creature_entry_exile"` static (`continuous.
    uncast_creature_entry_exiled`), checked at the same two graveyard/
    library-to-battlefield choke points `graveyard_library_entry_
    prohibited` (Grafdigger's Cage) already uses — reanimation
    (`ReturnFromGraveyardEffect._apply_one`) and a tutor whose destination
    is the battlefield (`RulesEngine._finish_search`) — redirecting to
    exile instead of the plain no-op that prohibition static gives. Same
    documented "not a universal `add_to_battlefield` hook" scope as its
    sibling: a rarer uncast-entry route (cheating a commander out of the
    command zone, a bespoke delayed "return to the battlefield" trigger)
    is left uncovered rather than reworking a foundational engine method.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("uncast_creature_entry_exile", {})],
        ),
    ]


register("Containment Priest", _containment_priest)
