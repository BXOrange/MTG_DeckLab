from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _foggy_swamp_visions() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, waterbend {X}.
    Exile X target creature cards from graveyards. For each creature card
    exiled this way, create a token that's a copy of it. At the beginning
    of your next end step, sacrifice those tokens.

    — `exile` X graveyard creature cards → `copy_permanent` with the new
    ``referent="previous_each"`` (one token copy of *each* card an earlier
    clause of this resolution exiled, `GameContext.previous_targets`) → a
    RULE 603.7 `create_delayed_trigger` at the next end step sacrificing
    the captured tokens (``capture="created_objects"``).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {
                    "target_kind": "any_graveyard_creature",
                    "count_selector": "source_x_paid",
                }),
                EffectSpec("copy_permanent", {
                    "referent": "previous_each", "target_kind": None,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "controller", "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "description": "Opfere diese Marker am Anfang deines nächsten "
                                   "Endsegments.",
                }),
            ],
            additional_cost={"waterbend": "x"},
        ),
    ]


register("Foggy Swamp Visions", _foggy_swamp_visions)
