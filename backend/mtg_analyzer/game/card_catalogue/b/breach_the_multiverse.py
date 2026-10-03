from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _breach_the_multiverse() -> list[AbilitySpec]:
    """Each player mills ten cards. For each player, choose a creature or
    planeswalker card in that player's graveyard. Put those cards onto the
    battlefield under your control. Then each creature you control becomes a
    Phyrexian in addition to its other types.

    The existing per-player chooser includes old graveyard cards. The type
    change locks the resolving group, so later creatures are unaffected.
    """
    return [AbilitySpec("spell_effect", [
        EffectSpec("for_each", {"over": {"players": "each_player"}, "effects": [
            {"type": "mill", "params": {"count": 10, "target_kind": "player"}},
        ]}),
        EffectSpec("return_from_graveyard", {
            "target_kind": "graveyard_creature_or_planeswalker", "each_player_pick": True,
            "under_your_control": True,
        }),
        EffectSpec("grant_until", {
            "target_kind": None, "duration": "rest_of_game", "lock_group": True,
            "static": {"type": "type_change", "params": {
                "affects": "creatures_you_control", "add_subtypes": ["Phyrexian"],
            }},
        }),
    ])]


register("Breach the Multiverse", _breach_the_multiverse)
