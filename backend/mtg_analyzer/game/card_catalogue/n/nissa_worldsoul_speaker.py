from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nissa_worldsoul_speaker() -> list[AbilitySpec]:
    """Landfall — Whenever a land you control enters, you get {E}{E} (two energy counters).
    You may pay eight {E} rather than pay the mana cost for permanent spells you cast.

    — PLAY-ALL (Living Energy). Landfall is the parser's group trigger. The alternative cost is Conspiracy Unraveler's
    `granted_alt_cast_cost`, widened with ``pay_energy`` and ``permanent_only`` (RULE 118.9).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 2, "kind": "energy"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": False, "type": "land",
            }},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("granted_alt_cast_cost", {"pay_energy": 8, "permanent_only": True})],
        ),
    ]


register("Nissa, Worldsoul Speaker", _nissa_worldsoul_speaker)
