from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bring_to_light() -> list[AbilitySpec]:
    """Converge — Search your library for a creature, instant, or sorcery
    card with mana value less than or equal to the number of colors of
    mana spent to cast this spell, exile that card, then shuffle. You may
    cast that card without paying its mana cost.

    — MEC-41. RULE 702.108a Converge's own count (`GameObject.colors_
    spent_to_cast`, diffed off the payer's `ManaPool` before vs. after
    payment at `RulesEngine.cast_spell`) reaches `SearchLibraryEffect`'s
    criteria the same way the existing ``"x"``/``"source_x_paid"``
    sentinels do — `RulesEngine._substitute_x`'s own criteria-walking pass
    gained a third sentinel, ``"colors_spent_to_cast"``. The exile-then-
    standing-free-cast destination (``"exile_free_cast"``) is also new
    (see `SearchLibraryEffect`'s own docstring) — distinct from the
    already-shipped ``"cast_free"`` (which casts immediately, Sunforger-
    shaped): here the found card sits in exile with a standing permission
    until the caster chooses to use it, exactly as printed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": {
                    "type": ["Creature", "Instant", "Sorcery"],
                    "max_mana_value": "colors_spent_to_cast",
                },
                "destination": "exile_free_cast",
                "zones": ["library"],
            })],
        ),
    ]


register("Bring to Light", _bring_to_light)
