from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# "creatures matching FILTER can't attack you or planeswalkers you
# control" static (Eriette of the Charmed Apple, PAR-60)
# ===========================================================================
# Engine: new `cant_attack_defender` EffectRegistry static + the
# `continuous.defender_attack_prohibited` scan consulted by
# `combat_mixin._can_attack`. ``attacker_filter`` narrows which creatures the
# bar bites (``enchanted_by_controller_aura`` / ``subtype`` /
# ``has_counter_kind`` / ``has_any_counter``).


def _eriette_of_the_charmed_apple() -> list[AbilitySpec]:
    """Each creature that's enchanted by an Aura you control can't attack you
    or planeswalkers you control.
    At the beginning of your end step, each opponent loses X life and you gain
    X life, where X is the number of Auras you control.

    The end-step drain folds in from the parser (it fully claims that line);
    only the combat static needs authoring."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_attack_defender", {
                "defender_scope": "player_or_planeswalker",
                "attacker_filter": {"enchanted_by_controller_aura": True},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "amount_from_count_selector": "creatures_you_control_of_type_aura",
                "selector": "each_opponent"}),
             EffectSpec("gain_life", {
                "count_selector": "creatures_you_control_of_type_aura"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
        ),
    ]


register("Eriette of the Charmed Apple", _eriette_of_the_charmed_apple)
