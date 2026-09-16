from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _samite_ministration() -> list[AbilitySpec]:
    """Prevent all damage that would be dealt to you this turn by a source
    of your choice. Whenever damage from a black or red source is
    prevented this way this turn, you gain that much life.

    — Shadowbane/Honorable Passage's own ``rider={"if_source_color": …}``
    gate (MEC-30), widened here to ``if_source_color_any`` (PAR-78) for
    the first real "black **or** red" two-colour gate this family needed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you", "if_source_color_any": ["B", "R"]},
            })],
        ),
    ]


register("Samite Ministration", _samite_ministration)
