from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Unbound Flourishing (double X on permanent spell + copy {X}
# instant/sorcery) — PAR-60
# ===========================================================================
# Clause 2 is Owlin Spiralmancer's shape (SPELL_CAST + ``spell_has_x`` +
# `copy_spell` from the trigger event). Clause 1 is a new `double_cast_x`
# effect that doubles the announced X on the stack item.


def _unbound_flourishing() -> list[AbilitySpec]:
    """Whenever you cast a permanent spell with a mana cost that contains
    {X}, double the value of X.
    Whenever you cast an instant or sorcery spell or activate an ability, if
    that spell's mana cost or that ability's activation cost contains {X},
    copy that spell or ability. You may choose new targets for the copy.

    Spell and activation events carry whether their mana portions contain {X},
    independently of X's announced value. The permanent trigger is restricted
    to permanent spells; copied abilities retain their source and chosen X.
    Remaining requirement: retain a copiable firing snapshot when the original
    spell/ability leaves the stack before this trigger resolves."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("double_cast_x", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_has_x": True,
                "spell_card_types": ["artifact", "creature", "enchantment", "planeswalker", "battle"],
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_spell", {"spell_from_trigger_event": "instance_id"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_has_x": True,
                "spell_card_types": ["instant", "sorcery"],
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_ability", {"ability_from_trigger_event": "stack_id"})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "you"},
                "spell_has_x": True,
            },
        ),
    ]


register("Unbound Flourishing", _unbound_flourishing)
