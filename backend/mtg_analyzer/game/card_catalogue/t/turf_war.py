from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _turf_war() -> list[AbilitySpec]:
    """When this enchantment enters, for each player, put a contested counter on
    target land that player controls.
    Whenever a creature deals combat damage to a player, if that player controls one
    or more lands with contested counters on them, that creature's controller gains
    control of one of those lands of their choice and untaps it.

    — Riveteer Rampage deck batch. The ETB is the parser's own claim, copied verbatim
    (`reuse`). The damage trigger is the unscoped group "a creature deals combat damage
    to a player" shape (no ``controller`` key — any creature); its body is
    `take_contested_land` (`ContestedLandControlEffect`), where the dealing creature's
    controller picks among the damaged player's contested lands
    (``gain_control_and_untap`` choose-object action). The intervening-if is checked at
    resolution only — see that effect's docstring.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "contested", "target_kind": "land_that_player_controls",
                "per_player": "players",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="when ~ enters, for each player, put a contested counter on target land that player controls.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("take_contested_land", {})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "type": "creature", "other": False},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Turf War", _turf_war)
