from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _austere_command() -> list[AbilitySpec]:
    """Choose two —
    • Destroy all artifacts.
    • Destroy all enchantments.
    • Destroy all creatures with mana value 3 or less.
    • Destroy all creatures with mana value 4 or greater.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 2,
                "options": [
                    [EffectSpec("destroy", {"group": {"zone": "battlefield", "of": "any", "filter": {"card_type": "artifact"}}})],
                    [EffectSpec("destroy", {"group": {"zone": "battlefield", "of": "any", "filter": {"card_type": "enchantment"}}})],
                    [EffectSpec("destroy", {"group": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature"}}, "filter": {"max_mana_value": 3}})],
                    [EffectSpec("destroy", {"group": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature"}}, "filter": {"min_mana_value": 4}})],
                ],
                "descriptions": [
                    "Zerstöre alle Artefakte.",
                    "Zerstöre alle Verzauberungen.",
                    "Zerstöre alle Kreaturen mit Manawert 3 oder weniger.",
                    "Zerstöre alle Kreaturen mit Manawert 4 oder mehr.",
                ],
            },
        )
    ]


register("Austere Command", _austere_command)
