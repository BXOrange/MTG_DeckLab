from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _padeem_consul_of_innovation() -> list[AbilitySpec]:
    """Artifacts you control have hexproof.
    At the beginning of your upkeep, if you control the artifact with the greatest mana value or tied
    for the greatest mana value, draw a card.

    — Keen Engineering deck batch. The hexproof grant is the parser's own claim; the upkeep draw is a
    phase trigger gated (trigger and effect, RULE 603.4) by the new
    ``controls_greatest_mana_value_artifact`` condition.
    """
    gate = {"kind": "controls_greatest_mana_value_artifact"}
    return [
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": "artifacts_you_control", "keywords": ["hexproof"],
        })]),
        AbilitySpec(
            "triggered", [EffectSpec("draw", {"count": 1}, condition=gate)],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you", "active_if": gate},
        ),
    ]


register("Padeem, Consul of Innovation", _padeem_consul_of_innovation)
