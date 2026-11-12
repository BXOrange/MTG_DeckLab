"""Charred Foyer // Warped Space, bound per unlocked door."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _charred_foyer():
    """At the beginning of your upkeep, exile the top card of your library. You may play it this turn."""
    return [AbilitySpec("triggered", [
        EffectSpec("exile_top_of_library", {
            "face_down": False, "player_selector": "controller", "count": 1, "position": "top",
        }),
        EffectSpec("cast_window_exiled_pool", {"same_turn_only": True}),
    ], trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"})]


def _warped_space():
    """Once each turn, you may pay {0} rather than pay the mana cost for a spell you cast from exile."""
    return [AbilitySpec("static", [EffectSpec("granted_alt_cast_cost", {
        "from_exile": True, "zero_mana": True, "once_per_turn": True,
    })])]


register("Charred Foyer", _charred_foyer)
register("Warped Space", _warped_space)
