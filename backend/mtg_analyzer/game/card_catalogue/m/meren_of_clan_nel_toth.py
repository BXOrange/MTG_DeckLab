from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _meren_of_clan_nel_toth() -> list[AbilitySpec]:
    """Whenever another creature you control dies, you get an experience counter.
    At the beginning of your end step, choose target creature card in your graveyard. If that card's mana value is
    less than or equal to the number of experience counters you have, return it to the battlefield. Otherwise, put
    it into your hand.

    — PLAY-ALL Step 2 (Sultai Arisen). The experience counter is `add_player_counters` (RULE 122) off a group-subject
    "another creature you control dies" trigger. The end-step ability targets a creature card in your graveyard
    (RULE 601.2c) and `return_from_graveyard`'s ``destination_if`` swaps the default hand for the battlefield when
    the target's mana value is within a live ``experience_counters_you_have`` count (`mana_value`'s ``max_selector``),
    both read when the ability resolves.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 1, "kind": "experience"})],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "controller": "you", "other": True, "type": "creature"},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "hand",
                "destination_if": {
                    "condition": {"kind": "mana_value", "of": "target", "max_selector": "experience_counters_you_have"},
                    "destination": "battlefield",
                },
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Meren of Clan Nel Toth", _meren_of_clan_nel_toth)
