from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _story_circle() -> list[AbilitySpec]:
    """As this enchantment enters, choose a color.
    {W}: The next time a source of your choice of the chosen color would
    deal damage to you this turn, prevent that damage.

    — The ETB colour choice is the ordinary ``choose_color_on_enter``
    replacement (Utopia Sprawl's own precedent, stamping `GameObject.
    chosen_color`); the shield reads it back dynamically via MEC-30's new
    ``source_filter={"color_from_source": True}`` key rather than a literal
    colour baked in at parse time — `RequestPreventDamageSourceEffect.apply`
    passes its own source as `matches_object_filter`'s ``reference``
    specifically so this (and Prismatic Circle's identical shape) can read
    it.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_color_on_enter", {})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_from_source": True}, "amount": "all",
            })],
            cost={"mana": "{W}"},
        ),
    ]


register("Story Circle", _story_circle)
