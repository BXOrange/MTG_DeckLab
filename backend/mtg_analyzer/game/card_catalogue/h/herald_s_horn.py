from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _herald_s_horn() -> list[AbilitySpec]:
    """As this artifact enters, choose a creature type.
    Creature spells you cast of the chosen type cost {1} less to cast.
    At the beginning of your upkeep, look at the top card of your library. If it's a creature card of the
    chosen type, you may reveal it and put it into your hand.

    — Reign of Dragons deck batch. The choice is the parser's own claim (`choose_creature_type_on_enter`,
    stamping `GameObject.chosen_type`). The discount is `cost_reduction` with the new
    ``spell_subtype_from_source``; the upkeep trigger is the PAR-144 dig `inspect_top_choose` over one
    card with a ``chosen_type`` criteria sentinel (a creature card of the chosen type), an optional pick
    to hand, the rest staying put (``decline_leaves_untouched``).
    """
    return [
        AbilitySpec("enter_replacement", [EffectSpec("choose_creature_type_on_enter", {})]),
        AbilitySpec("static", [EffectSpec("cost_reduction", {
            "affects": "your_spells", "generic": 1, "spell_type": "creature", "spell_subtype_from_source": True,
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("inspect_top_choose", {
                "count": 1, "action": "library_to_hand", "max_picks": 1, "optional": True,
                "decline_leaves_untouched": True, "rest_destination": "library_top",
                "criteria": {"all_types": ["Creature", "chosen_type"]},
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Herald's Horn", _herald_s_horn)
