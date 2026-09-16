from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ghoulish_impetus() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +1/+1, has deathtouch, and is goaded.
    When enchanted creature dies, return this card to the battlefield at the
    beginning of the next end step.

    — Ghoulish Impetus. The return is a RULE 603.7 delayed trigger armed by
    the enchanted creature's death: at the next end step,
    `return_self_from_graveyard` puts the Aura back (its own "Enchant
    creature" ETB re-attaches it, from the keyword catalogue)."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1}),
                EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["deathtouch"]}),
                EffectSpec("goaded", {"affects": "attached_permanent"}),
            ],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "any",
                    "effects": [{"type": "return_self_from_graveyard", "params": {}}],
                    "description": "Ghoulish Impetus: Aura zurückbringen",
                }),
            ],
            trigger={"event": "DIES", "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Ghoulish Impetus", _ghoulish_impetus)
