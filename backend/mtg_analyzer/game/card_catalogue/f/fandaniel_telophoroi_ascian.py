from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fandaniel_telophoroi_ascian() -> list[AbilitySpec]:
    """Whenever you cast an instant or sorcery spell, surveil 1.
    At the beginning of your end step, each opponent may sacrifice a
    nontoken creature of their choice. Each opponent who doesn't loses 2
    life for each instant and sorcery card in your graveyard.

    — PLAY-ALL Step 2 (yshtola). The surveil trigger is the parser's own
    claim, reproduced verbatim. The end step is `for_each` over
    ``each_opponent`` (APNAP) whose body asks that player — handed to the body
    as its target, hence ``payer="target"`` — to pay "Sacrifice a nontoken
    creature", with the 2-life loss as the "if you don't" branch, the
    Tergrid's Lantern shape. The loss is measured on *this card's*
    controller's graveyard (`count_selector` ``instant_or_sorcery_cards_in_your_graveyard``
    is read as the source's controller), times 2.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("surveil", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_filter": {"card_type_any": ["instant", "sorcery"]},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("for_each", {
                "over": {"players": "each_opponent"},
                "effects": [{"type": "pay_cost_then", "params": {
                    "cost": "Sacrifice a nontoken creature", "payer": "target",
                    "else_effects": [{"type": "lose_life", "params": {
                        "target_kind": "player",
                        "amount": {
                            "kind": "count_selector",
                            "selector": "instant_or_sorcery_cards_in_your_graveyard",
                            "multiply": 2,
                        },
                    }}],
                }}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Fandaniel, Telophoroi Ascian", _fandaniel_telophoroi_ascian)
