from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cloud_key() -> list[AbilitySpec]:
    """As this artifact enters, choose artifact, creature, enchantment,
    instant, or sorcery.
    Spells you cast of the chosen type cost {1} less to cast.

    — PLAY-ALL Step 2 (Counter Intelligence). The pick is Archon of Valor's
    Reach's `choose_named_mode` (its options slug to the card-type words, kept in
    `GameObject.chosen_mode`); the discount is a plain `cost_reduction` whose
    ``spell_type`` is read from that pick (`spell_type_from_source_mode`,
    mirroring `cast_prohibition`'s ``type_from_source_mode``) instead of being
    printed on the static.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_named_mode", {
                "options": ["Artifact", "Creature", "Enchantment", "Instant", "Sorcery"],
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "spell_type_from_source_mode": True})],
        ),
    ]


register("Cloud Key", _cloud_key)
