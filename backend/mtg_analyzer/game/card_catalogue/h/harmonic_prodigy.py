from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _harmonic_prodigy() -> list[AbilitySpec]:
    """Prowess.
    If a triggered ability of a Shaman or another Wizard you control
    triggers, that ability triggers an additional time.

    Prowess folds in from the RULE 702 keyword catalogue even for a
    registered card; only the trigger-doubler clause needs authoring."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {
                "subject": {"filter": {"subtype_any": ["shaman", "wizard"]}, "other": True},
            })],
        ),
    ]


register("Harmonic Prodigy", _harmonic_prodigy)
