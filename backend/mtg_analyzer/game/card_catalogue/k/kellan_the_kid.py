from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kellan_the_kid() -> list[AbilitySpec]:
    """Flying, lifelink
    Whenever you cast a spell from anywhere other than your hand, you may cast a
    permanent spell with equal or lesser mana value from your hand without
    paying its mana cost. If you don't, you may put a land card from your hand
    onto the battlefield.

    — PLAY-ALL Step 2 (SpongeBob). Flying and lifelink are read from the card.
    The trigger is ``SPELL_CAST`` by you with ``spell_not_cast_from_hand``
    (the binder's own cast-origin predicate). The body is the Expertise cycle's
    `free_cast_from_hand` with three new parameters: ``mana_value_from_trigger``
    (the cap is the cast spell's mana value, read off the firing event),
    ``permanent_only`` (no instants/sorceries) and ``else_effects`` — "if you
    don't" — a `put_from_hand_onto_battlefield` for a land card, which runs when
    nothing was cast for free (declined, or no eligible card).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("free_cast_from_hand", {
                "mana_value_from_trigger": True, "permanent_only": True,
                "else_effects": [{"type": "put_from_hand_onto_battlefield", "params": {"criteria": "Land", "count": 1}}],
            })],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_not_cast_from_hand": True,
            },
        ),
    ]


register("Kellan, the Kid", _kellan_the_kid)
