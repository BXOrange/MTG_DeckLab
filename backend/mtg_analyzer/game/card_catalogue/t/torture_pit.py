from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _torture_pit() -> list[AbilitySpec]:
    """If a source you control would deal noncombat damage to an opponent, it deals that much damage plus 2 instead.
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — MEC-111, the right door of Spiked Corridor // Torture Pit. Torbran's `additional_damage`, any colour of source, narrowed to
    ``noncombat_only`` and ``players_only`` (the opponent itself, not a permanent they control).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("additional_damage", {
                "amount": 2, "your_sources_only": True, "to_opponent_only": True,
                "noncombat_only": True, "players_only": True,
            })],
        ),
    ]


register("Torture Pit", _torture_pit)
