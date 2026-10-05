from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _runic_armasaur() -> list[AbilitySpec]:
    """Whenever an opponent activates an ability of a creature or land
    that isn't a mana ability, you may draw a card.

    — MEC-43 round 2. `EventType.ACTIVATED_ABILITY` already fires for
    every non-mana activated ability (RULE 605.1a mana abilities never use
    the stack, so they never reach this event at all — "isn't a mana
    ability" needs no separate check), with `object_types`/``controller_id``
    already matching this trigger's own default group-subject keys. The
    only real gap was the group-subject ``type`` filter's shape: it only
    ever took one word before this batch, and "creature or land" needs
    two ORed together (`effect_binder._group_ok`'s new list-``type``
    support). **Documented simplification**: "may" is read as
    unconditional, the same accepted convention every other untargeted
    "you may draw"/"you may `<upside>`" trigger with no real downside to
    declining already gets in this engine (Selvala, Heart of the Wilds's
    own docstring names the same precedent).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "type": ["creature", "land"], "controller": "not_you"},
            },
        )
    ]


register("Runic Armasaur", _runic_armasaur)
