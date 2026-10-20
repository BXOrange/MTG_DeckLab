from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _infesting_radroach() -> list[AbilitySpec]:
    """Flying
    This creature can't block.
    Whenever this creature deals combat damage to a player, they get that
    many rad counters.
    Whenever an opponent mills a nonland card, if this creature is in your
    graveyard, you may return it to your hand.

    — Infesting Radroach. "That many" ties the rad-counter amount to the
    combat damage just dealt (``amount_from_trigger_event: "amount"``). The
    graveyard-return-on-opponent-mill ability is RULE 113.6a's own family: an
    ordinary MILL_CARD trigger over `return_self_from_graveyard_to_hand`,
    which `bind_ability` marks ``functions_from_graveyard`` (scanned by
    `RulesEngine._collect_graveyard_function_triggers`). "An opponent" is the
    group-subject ``not_you`` scope, "you" being the graveyard card's owner
    (RULE 108.4).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"keywords": ["cant_block"], "affects": "self"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {
                "kind": "rad", "player": {"of": "damaged_player"},
                "amount_from_trigger_event": "amount",
            })],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_self_from_graveyard_to_hand", {})],
            trigger={"event": EventType.MILL_CARD, "condition": {"subject": "group", "controller": "not_you"}},
            optional=True,
        ),
    ]


register("Infesting Radroach", _infesting_radroach)
