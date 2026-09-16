from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# triggered-ability doubling generalized (PAR-60)
# ===========================================================================
# `TriggerDoublerEffect` (Roaming Throne / Elesh Norn / Delney) gained two
# scoping axes: ``subject_subtype_any`` (a fixed subtype list on the doubled
# permanent — Harmonic Prodigy) and ``cause_spell_type_any`` (narrows a
# ``cause_filter`` match to the firing spell's card types — Veyran).


def _veyran_voice_of_duality() -> list[AbilitySpec]:
    """Magecraft — Whenever you cast or copy an instant or sorcery spell,
    Veyran gets +1/+1 until end of turn.
    If you casting or copying an instant or sorcery spell causes a triggered
    ability of a permanent you control to trigger, that ability triggers an
    additional time.

    The magecraft pump folds in from the parser (it fully claims that line);
    only the trigger-doubler clause needs authoring — an Elesh Norn-shaped
    ``cause_filter`` doubler narrowed to instant/sorcery casts."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"power": 1, "toughness": 1})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                     "spell_card_types": ["instant", "sorcery"]},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {
                "cause_filter": [EventType.SPELL_CAST],
                "cause_spell_type_any": ["instant", "sorcery"]})],
        ),
    ]


register("Veyran, Voice of Duality", _veyran_voice_of_duality)
