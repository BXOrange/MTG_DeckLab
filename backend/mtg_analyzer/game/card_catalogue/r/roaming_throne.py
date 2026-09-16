from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _roaming_throne() -> list[AbilitySpec]:
    """Ward {2}
    As this creature enters, choose a creature type.
    This creature is the chosen type in addition to its other types.
    If a triggered ability of another creature you control of the chosen
    type triggers, it triggers an additional time.

    — Eliferate deck batch, closing the one remaining gap the 2026-08-05
    Eliferate/Keywords Showcase batch deliberately left open (Done_Backend.md
    called out "Roaming Throne's trigger-doubling" by name). Ward, the ETB
    type choice, and the self type-grant already parse on their own —
    reproduced here verbatim (whole-card hand-authoring replaces the
    parser's own output wholesale). The doubling itself is a genuinely new
    RULE 603.3d primitive: `effects.TriggerDoublerEffect`, a continuous
    marker (no `apply()` behaviour of its own, the same
    `TopLibraryPermissionEffect`/`CantBeCounteredEffect` idiom) that
    `continuous.trigger_doubler_bonus` scans for from `game/rules/
    triggers_mixin.py`'s `_collect_triggers` — the one place every
    permanent's own triggered ability gets placed on the stack — which now
    appends `1 + bonus` copies instead of always exactly one. Placed as
    independent extra copies (not a single ability that "resolves twice")
    so 2+ pending copies are still separately orderable (RULE 603.3b) if a
    second trigger is also waiting.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {"affects": "self", "add_subtypes_from_source": True})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {})],
        ),
    ]


register("Roaming Throne", _roaming_throne)
