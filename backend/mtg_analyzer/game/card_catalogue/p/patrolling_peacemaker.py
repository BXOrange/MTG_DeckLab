from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _patrolling_peacemaker() -> list[AbilitySpec]:
    """This creature enters with two +1/+1 counters on it.
    Whenever an opponent commits a crime, proliferate. (They commit a crime if
    they target an opponent, anything an opponent controls, and/or cards in an
    opponent's graveyard. To proliferate, you choose any number of permanents
    and/or players, then give each another counter of each kind already there.)

    — PLAY-ALL Step 2 (Counter Intelligence). Enters-with-two-counters is read
    off the card's text. The trigger is the `CRIME_COMMITTED` event (RULE 700.13,
    `RulesEngine._note_crime`, fired once per spell/ability that targets an
    opponent-side object) with the group subject ``controller: not_you`` the
    parser already uses for "whenever an opponent casts a spell" — the event's
    ``player_id`` is the player who committed it. (The parser has no head for
    "commits a crime" itself, hence hand-authored.) Proliferate is the engine's
    `proliferate`, which auto-applies to every counter-bearing permanent/player
    (no chooser) — the documented MVP simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("proliferate", {})],
            trigger={
                "event": EventType.CRIME_COMMITTED,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        ),
    ]


register("Patrolling Peacemaker", _patrolling_peacemaker)
