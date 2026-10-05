from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _deathmist_raptor() -> list[AbilitySpec]:
    """Deathtouch
    Whenever a permanent you control is turned face up, you may return this card from your graveyard to the battlefield face up or face down.
    Megamorph {4}{G} (You may cast this card face down as a 2/2 creature for {3}. Turn it face up any time for its megamorph cost and put a +1/+1 counter on it.)

    — PLAY-ALL (Jump Scare!). Deathtouch and Megamorph are keywords. A graveyard-functioning optional trigger (the
    `return_self_from_graveyard` binder flag, Bloodghast's) on `TURNED_FACE_UP` for any permanent you control, whose
    ``face_choice`` asks face up or face down (RULE 708.4; `RulesEngine._request_return_face_choice`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_self_from_graveyard", {"tapped": False, "face_choice": True})],
            trigger={"event": EventType.TURNED_FACE_UP, "condition": {"subject": "group", "controller": "you", "other": False}},
            optional=True,
        ),
    ]


register("Deathmist Raptor", _deathmist_raptor)
