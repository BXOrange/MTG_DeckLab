from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mezzio_mugger() -> list[AbilitySpec]:
    """Whenever this creature attacks, exile the top card of each player's library.
    You may play those cards this turn, and you may spend mana as though it were
    mana of any color to cast those spells.
    Blitz {2}{R} (If you cast this spell for its blitz cost, it gains haste and
    "When this creature dies, draw a card." Sacrifice it at the beginning of the
    next end step.)

    — Riveteer Rampage deck batch. `impulsive_draw` widened with ``each_player``
    (one exile per living player, every permission held by the Mugger's controller)
    and ``mana_wildcard="color"`` (RULE 605.1a, `GameState.mana_wildcard_permission`);
    lands are playable through the same temp-play permission Ragavan's exile uses.
    Blitz is a keyword (RULE 702.152), bound from the printed cost.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("impulsive_draw", {
                "count": 1, "same_turn_only": True, "each_player": True, "mana_wildcard": "color",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Mezzio Mugger", _mezzio_mugger)
