from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _curse_of_opulence() -> list[AbilitySpec]:
    """Enchant player
    Whenever enchanted player is attacked, create a Gold token. Each opponent attacking that
    player does the same. (A Gold token is an artifact with "Sacrifice this token: Add one mana
    of any color.")

    — Jeskai Striker deck batch. "Enchant player" is the Aura's cast-time keyword. The trigger is
    `PLAYER_ATTACKED` (one event per attacking player) scoped by the existing
    ``attacks_enchanted_player`` condition (the defender is the player this Aura is attached to);
    the body is `attacked_curse_gold` (`AttackedCurseGoldEffect`) — the Curse's controller's Gold
    once per turn, plus one for the attacking opponent of each event.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("attacked_curse_gold", {})],
            trigger={
                "event": EventType.PLAYER_ATTACKED,
                "condition": {"subject": "group", "attacks_enchanted_player": True},
            },
        ),
    ]


register("Curse of Opulence", _curse_of_opulence)
