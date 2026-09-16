from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _quintorius_loremaster() -> list[AbilitySpec]:
    """Vigilance
    At the beginning of your end step, exile target noncreature, nonland card
    from your graveyard. Create a 3/2 red and white Spirit creature token.
    {1}{R}{W}, {T}, Sacrifice a Spirit: Choose target card exiled with
    Quintorius. You may cast that card this turn without paying its mana
    cost. …

    Documented simplifications: the end-step exile target is modeled as any
    graveyard card (the "noncreature, nonland" narrowing isn't on the
    kind); the "cast a card exiled with Quintorius" activated ability is not
    modeled."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_target_graveyard", {"target_kind": "graveyard_card"}),
                EffectSpec("create_token", {
                    "count": 1, "token_name": "Spirit", "power": 3, "toughness": 2,
                    "colors": ["R", "W"], "subtypes": ["Spirit"],
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
        ),
    ]


register("Quintorius, Loremaster", _quintorius_loremaster)
