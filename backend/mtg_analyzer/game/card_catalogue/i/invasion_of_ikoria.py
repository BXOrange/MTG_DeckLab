from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_ikoria() -> list[AbilitySpec]:
    """(As a Siege enters, choose an opponent to protect it. You and
    others can attack it. When it's defeated, exile it, then cast it
    transformed.)
    When this Siege enters, search your library and/or graveyard for a
    non-Human creature card with mana value X or less and put it onto
    the battlefield. If you search your library this way, shuffle.

    — MEC-12 (cEDH Kinnan). The Siege reminder text is the existing
    generic RULE 310 battle machinery, not modeled here. The search
    itself already fully supports "library and/or graveyard"
    (`SearchLibraryEffect`'s existing ``zones`` param — always shuffles
    when "library" is among them, RULE 701.19e, matching "if you search
    your library this way, shuffle" for the common case of always
    searching both). The only new piece is the ``"source_x_paid"``
    criteria sentinel: this ETB fires well after the original casting
    resolution ends, so the existing bare ``"x"`` sentinel (tied to
    *this* stack item's own announced X, which is 0 for a trigger) can't
    reach the permanent's announced X the way it does for a spell's own
    effects — `GameObject.x_paid`, stamped once at cast time, is read
    instead.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {
                    "type": "Creature", "without_type": "human",
                    "max_mana_value": "source_x_paid",
                },
                "destination": "battlefield",
                "zones": ["library", "graveyard"],
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
    ]


register("Invasion of Ikoria", _invasion_of_ikoria)
register("Invasion of Ikoria // Zilortha, Apex of Ikoria", _invasion_of_ikoria)
