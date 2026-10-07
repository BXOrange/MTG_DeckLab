from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dusty_parlor() -> list[AbilitySpec]:
    """Whenever you cast an enchantment spell, put a number of +1/+1 counters equal to that spell's mana value on up to one target creature.
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — MEC-111, the right door of Secret Arcade // Dusty Parlor. The parser's "whenever you cast an enchantment spell" head over
    `add_counters` with ``amount_from_trigger_event: mana_value`` (Dancing from Dark to Dawn's primitive) on an optional target.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "kind": "+1/+1", "target_kind": "creature", "optional": True, "amount_from_trigger_event": "mana_value",
            })],
            trigger={"event": "SPELL_CAST", "condition": {"subject": "you"}, "spell_filter": {"card_type": "enchantment"}},
        ),
    ]


register("Dusty Parlor", _dusty_parlor)
