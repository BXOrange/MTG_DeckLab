from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tablet_of_the_guilds() -> list[AbilitySpec]:
    """As this artifact enters, choose two colors.
    Whenever you cast a spell, if it's at least one of the chosen colors, you gain 1 life for each of the chosen colors it is.

    — PLAY-ALL (Hope to the last). The pick is `choose_color_on_enter` with ``count`` 2 (two prompts, the second excluding
    the first; `GameObject.chosen_colors`). The trigger's spell filter is the new ``color_from_source_chosen_colors`` key and
    the life is the new ``chosen_colors_shared_with_trigger_spell`` amount.
    """
    return [
        AbilitySpec("enter_replacement", [EffectSpec("choose_color_on_enter", {"count": 2})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": {"kind": "chosen_colors_shared_with_trigger_spell"}})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_filter": {"color_from_source_chosen_colors": True},
            },
        ),
    ]


register("Tablet of the Guilds", _tablet_of_the_guilds)
