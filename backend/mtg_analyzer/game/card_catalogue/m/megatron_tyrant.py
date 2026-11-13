"""Both physical faces of Megatron."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tyrant():
    """More Than Meets the Eye {1}{R}{W}{B} (You may cast this card converted for {1}{R}{W}{B}.)
Your opponents can't cast spells during combat.
At the beginning of each of your postcombat main phases, you may convert Megatron. If you do, add {C} for each 1 life your opponents have lost this turn."""
    return [
        AbilitySpec("static", [EffectSpec("cast_prohibition", {
            "scope": "opponents", "active_if": {"kind": "during_phase", "phase": "combat"},
        })]),
        AbilitySpec("triggered", [EffectSpec("megatron_convert_mana", {})],
                    trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "main2"}, "phase_relation": "you"}),
    ]


def _destructive_force():
    """Living metal (During your turn, this Vehicle is also a creature.)
Whenever Megatron attacks, you may sacrifice another artifact. When you do, Megatron deals damage equal to the sacrificed artifact's mana value to target creature. If excess damage would be dealt to that creature this way, instead that damage is dealt to that creature's controller and you convert Megatron."""
    return [
        AbilitySpec("keyword", [], keyword={"name": "living_metal"}),
        AbilitySpec("triggered", [EffectSpec("megatron_sacrifice", {})],
                    trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}}),
    ]


register("Megatron, Tyrant", _tyrant)
register("Megatron, Tyrant // Megatron, Destructive Force", _tyrant)
register("Megatron, Destructive Force", _destructive_force)
