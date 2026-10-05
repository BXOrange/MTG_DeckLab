from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lost_monarch_of_ifnir() -> list[AbilitySpec]:
    """Afflict 3
    Other Zombies you control have afflict 3.
    At the beginning of your second main phase, if a player was dealt combat damage by a Zombie this turn, mill three cards, then you may return a creature card from your graveyard to your hand.

    — PLAY-ALL Step 2 (Eternal Might). Afflict 3 is a printed keyword; the grant is a layer-6 `grant_keyword` with a
    parametric ``afflict 3`` to other Zombies you control. The second-main trigger has a RULE 603.4 intervening-if
    (`trigger["active_if"]`) on the new ``subtype_dealt_combat_damage_to_player_this_turn`` condition; its body
    mills three, then offers a creature card from the graveyard to hand (the pick is optional by construction).
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": "other_creatures_you_control", "subtype": "Zombie",
            "parametric_keywords": [{"name": "afflict", "n": 3}],
        })]),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("mill", {"count": 3}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "destination": "hand", "optional": True, "pick": True,
                }),
            ],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "main2"}, "phase_relation": "you",
                "active_if": {"kind": "subtype_dealt_combat_damage_to_player_this_turn", "subtype": "zombie"},
            },
        ),
    ]


register("Lost Monarch of Ifnir", _lost_monarch_of_ifnir)
