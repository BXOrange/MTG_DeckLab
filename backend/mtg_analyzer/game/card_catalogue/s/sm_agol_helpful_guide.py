from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _smeagol_helpful_guide() -> list[AbilitySpec]:
    """At the beginning of your end step, if a creature died under your
    control this turn, the Ring tempts you.
    Whenever the Ring tempts you, target opponent reveals cards from the
    top of their library until they reveal a land card. Put that card
    onto the battlefield tapped under your control and the rest into
    their graveyard.

    Simplified: the ring-tempted payoff is narrowed to *your own* library
    instead of a chosen opponent's (`RulesEngine.dig_until` always digs
    the ability's own controller — no "dig a chosen player's library"
    variant exists), the found land enters untapped (`dig_until`'s
    "battlefield" hit destination doesn't apply RULE 614.1 tapped-entry),
    and the rest goes to exile rather than graveyard (`dig_until`'s own
    "exile" default `rest_destination`, the only one it supports besides
    a random bottom-of-library shuffle).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec(
                "the_ring_tempts_you", {},
                condition={"creatures_died_this_turn_at_least": 1},
            )],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": {"type": "Land"}, "hit_destination": "battlefield", "rest_destination": "exile",
            })],
            trigger={"event": EventType.RING_TEMPTED, "condition": {"subject": "you"}},
        ),
    ]


register("Sméagol, Helpful Guide", _smeagol_helpful_guide)
