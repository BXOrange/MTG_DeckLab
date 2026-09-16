from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _virtue_of_courage() -> list[AbilitySpec]:
    """Whenever a source you control deals noncombat damage to an
    opponent, you may exile that many cards from the top of your library.
    You may play those cards this turn.

    — Imodane deck batch. `ImpulsiveDrawEffect`'s new `count_from_trigger_
    event` (the firing `DAMAGE` event's own ``amount``), ``same_turn_
    only=True`` for "this turn" rather than "until your next turn". Fixed
    (bug report, 2026-09-04): the recipient half of "you control … to an
    opponent" isn't covered by ``condition``'s ``"group"``/``"controller":
    "you"`` (that only scopes the *source*, not who was hit) — it needs the
    same `requires_damage_to_opponent` predicate (the DAMAGE event's player
    target must be someone other than this ability's own controller) that
    Chandra's Incinerator already established, combined with the DAMAGE
    event's own ``"filter": {"combat": False}`` for "noncombat". The old
    ``"filter": {"is_player": True}`` alone (no opponent check at all)
    let the ability fire — and, via `ImpulsiveDrawEffect`'s own now-fixed
    default-player bug, exile from and grant play permission to a
    *different* player — off the controller's own source dealing combat
    damage, or dealing any damage to themselves.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("impulsive_draw", {
                "count_from_trigger_event": "amount", "same_turn_only": True,
            })],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "controller": "you"},
                "filter": {"combat": False},
                "requires_damage_to_opponent": True,
            },
        ),
    ]


register("Virtue of Courage", _virtue_of_courage)
register("Virtue of Courage // Embereth Blaze", _virtue_of_courage)
