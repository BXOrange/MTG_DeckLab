from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aetherworks_marvel() -> list[AbilitySpec]:
    """Whenever a permanent you control is put into a graveyard, you get {E} (an energy counter).
    {T}, Pay six {E}: Look at the top six cards of your library. You may cast a spell from among them without paying its mana cost. Put the rest on the bottom of your library in a random order.

    — PLAY-ALL (Living Energy). The trigger is the PUT_INTO_GRAVEYARD group form restricted to arrivals from the
    battlefield. The activated ability is `look_top_cast_free` (Velomachus Lorehold's resolution-play path) with no
    type or mana-value filter — lands are never cast, so they stay in the rest that goes to the bottom.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 1, "kind": "energy"})],
            trigger={
                "event": EventType.PUT_INTO_GRAVEYARD,
                "condition": {"subject": "group", "controller": "you", "other": False},
                "filter": {"from_zone": "battlefield"},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("look_top_cast_free", {"count": 6, "prompt": "Zauber kostenlos wirken?"})],
            cost={"text": "{t}, pay 6 {e}"},
        ),
    ]


register("Aetherworks Marvel", _aetherworks_marvel)
