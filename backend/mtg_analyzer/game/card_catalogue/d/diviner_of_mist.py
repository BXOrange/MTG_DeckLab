from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "an instant or sorcery spell … with mana value 4 or less" — the printed cap on the free cast.
_MAX_MANA_VALUE = 4


def _diviner_of_mist() -> list[AbilitySpec]:
    """Flying
    Whenever this creature attacks, mill four cards. You may cast an instant or sorcery spell from your graveyard
    with mana value 4 or less without paying its mana cost. If that spell would be put into your graveyard, exile it
    instead.

    — PLAY-ALL Step 2 (Sultai Arisen). Flying is a keyword fold-in. After the `mill` (so the milled cards are
    eligible), `cast_graveyard_instant_sorcery_free_exile` with ``pick`` offers the controller's own graveyard
    instants/sorceries up to the mana-value cap; the pick is exiled with the exile-instead rider and its free cast
    window opens through the ordinary cast flow (targets/modes chosen there). Documented simplification shared with
    Impulsivity/Rebound: the window lasts the rest of the turn rather than only during the resolution.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "mill", "params": {"count": 4}},
                {"type": "cast_graveyard_instant_sorcery_free_exile", "params": {
                    "pick": True, "max_mana_value": _MAX_MANA_VALUE,
                }},
            ]})],
            trigger={"event": "ATTACKS", "condition": {"subject": "self"}},
        ),
    ]


register("Diviner of Mist", _diviner_of_mist)
