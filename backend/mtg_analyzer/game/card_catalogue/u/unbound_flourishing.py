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

    Documented simplification: clause 2's "or activate an ability" half is
    dropped (only spells are copied); clause 1 fires for every {X} spell you
    cast and no-ops unless it is a permanent spell."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("double_cast_x", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_has_x": True,
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
    ]


register("Unbound Flourishing", _unbound_flourishing)
