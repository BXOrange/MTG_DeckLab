from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _teferi_who_slows_the_sunset() -> list[AbilitySpec]:
    """+1: Choose up to one target artifact, up to one target creature, and up to one target land. Untap the chosen permanents you control. Tap the chosen permanents you don't control. You gain 2 life.
    −2: Look at the top three cards of your library. Put one of them into your hand and the rest on the bottom of your library in any order.
    −7: You get an emblem with "Untap all permanents you control during each opponent's untap step" and "You draw a card during each opponent's draw step."

    — PLAY-ALL (Hope to the last). The −2 is the parser's. The +1 is three optional single-target `tap` effects (artifact,
    creature, land — one target slot each) with the new ``untap_if_yours`` mode (untap what the controller controls, tap the
    rest), then `gain_life`. The −7 emblem holds Seedborn Muse's untap trigger and a draw trigger at each other player's draw
    step (`phase_relation` ``not_you``).
    """
    untap_all = AbilitySpec(
        "triggered",
        [EffectSpec("tap", {"untap": True, "selector": "permanents_you_control"})],
        trigger={"event": EventType.UNTAP, "condition": {"subject": "group", "controller": "not_you"}},
    )
    draw_each_opponent_draw_step = AbilitySpec(
        "triggered",
        [EffectSpec("draw", {"count": 1})],
        trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "draw"}, "phase_relation": "not_you"},
    )
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("tap", {"target_kind": "artifact", "optional": True, "untap_if_yours": True}),
                EffectSpec("tap", {"target_kind": "creature", "optional": True, "untap_if_yours": True}),
                EffectSpec("tap", {"target_kind": "land", "optional": True, "untap_if_yours": True}),
                EffectSpec("gain_life", {"amount": 2}),
            ],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("look_top_select", {
                "count": 3, "select_count": 1, "rest_destination": "library_bottom", "rest_order": "any",
            })],
            cost={"loyalty": -2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {"abilities": [untap_all.to_dict(), draw_each_opponent_draw_step.to_dict()]})],
            cost={"loyalty": -7},
        ),
    ]


register("Teferi, Who Slows the Sunset", _teferi_who_slows_the_sunset)
