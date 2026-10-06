from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shadow_mysterious_assassin() -> list[AbilitySpec]:
    """Deathtouch
    Throw — Whenever this creature deals combat damage to a player, you may sacrifice another nonland permanent. If you do, draw two cards and each opponent loses life equal to the mana value of the sacrificed permanent.

    — PLAY-ALL (Revival Trance). Deathtouch is a keyword. A damage-to-a-player trigger over `sacrifice_chosen_then`
    (``exclude_self``, one nonland permanent, ``measure="mana_value"`` binding the follow-up's ``x`` to the sacrificed
    permanent's mana value): draw two, each opponent loses X.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_chosen_then", {
                "what": "nonland", "count": 1, "exclude_self": True, "measure": "mana_value",
                "effects": [
                    {"type": "draw", "params": {"count": 2}},
                    {"type": "lose_life", "params": {"amount": "x", "selector": "each_opponent"}},
                ],
            })],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self"}, "filter": {"combat": True, "is_player": True}},
        ),
    ]


register("Shadow, Mysterious Assassin", _shadow_mysterious_assassin)
