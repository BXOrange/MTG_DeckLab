from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mercenaries() -> list[AbilitySpec]:
    """{3}: The next time this creature would deal damage to you this
    turn, prevent that damage. Any player may activate this ability.

    — Mercenaries (MEC-30, Phase 7). RULE 602.2b: whoever activates an
    ability is that ability's controller for the purposes of its
    resolution, so "you" here means the *activator* — not Mercenaries'
    own permanent controller, which is who every other card in this
    family's "prevent damage to you" shape protects. Needed two small new
    primitives together: `ActivationCost.any_player_may_activate` widens
    `GameEngine.can_activate`'s ordinary "only the permanent's controller"
    eligibility gate; `GameContext.resolving_controller_id` (RULE 602.2b's
    activator, threaded through `RulesEngine.resolve_top_of_stack` around
    a stack item's own resolution, mirroring `trigger_event`'s existing
    save/restore pattern) is what `PreventDamageEffect`'s new
    `recipient_is_activator` reads instead of the permanent's printed
    controller. `watched_source_is_self` narrows the shield to
    Mercenaries' own damage specifically — the fixed-source, no-chooser-
    needed sibling of `RequestPreventDamageSourceEffect`'s "a source of
    your choice".
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("prevent_damage_shield", {
                "amount": "all", "watched_source_is_self": True, "recipient_is_activator": True,
            })],
            cost={"mana": "{3}", "any_player_may_activate": True},
        ),
    ]


register("Mercenaries", _mercenaries)
