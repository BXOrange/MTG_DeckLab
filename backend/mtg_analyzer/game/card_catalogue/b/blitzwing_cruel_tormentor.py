"""Both physical faces of Blitzwing."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cruel_tormentor():
    """More Than Meets the Eye {3}{B} (You may cast this card converted for {3}{B}.)
At the beginning of your end step, target opponent loses life equal to the life that player lost this turn. If no life is lost this way, convert Blitzwing."""
    return [AbilitySpec("triggered", [EffectSpec("blitzwing_life_echo", {})],
                        trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"})]


def _adaptive_assailant():
    """Living metal (During your turn, this Vehicle is also a creature.)
At the beginning of combat on your turn, choose flying or indestructible at random. Blitzwing gains that ability until end of turn.
Whenever Blitzwing deals combat damage to a player, convert it."""
    return [
        AbilitySpec("keyword", [], keyword={"name": "living_metal"}),
        AbilitySpec("triggered", [EffectSpec("blitzwing_random_ability", {})],
                    trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"}),
        AbilitySpec("triggered", [EffectSpec("blitzwing_convert", {})],
                    trigger={"event": EventType.DAMAGE, "condition": {"subject": "self"},
                             "filter": {"combat": True, "is_player": True}}),
    ]


register("Blitzwing, Cruel Tormentor", _cruel_tormentor)
register("Blitzwing, Cruel Tormentor // Blitzwing, Adaptive Assailant", _cruel_tormentor)
register("Blitzwing, Adaptive Assailant", _adaptive_assailant)
