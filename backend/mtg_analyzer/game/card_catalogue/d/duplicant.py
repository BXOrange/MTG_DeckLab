from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _duplicant() -> list[AbilitySpec]:
    """Imprint — When this creature enters, you may exile target nontoken creature.
    As long as a card exiled with this creature is a creature card, this creature has the power,
    toughness, and creature types of the last creature card exiled with it. It's still a
    Shapeshifter.

    — Keen Engineering deck batch. The Imprint is `exile` with ``remember`` (the O-Ring/Chrome Mox
    link, `GameObject.linked_exile_id`) over an optional nontoken-creature target. The static is the new
    ``from_linked_exile`` mode of the layer-4 `type_change`: it reads that link every recompute,
    applies only while the linked card is still exiled *and* a creature card, sets base P/T to its
    printed values and *adds* its creature types — adding rather than replacing keeps "still a
    Shapeshifter" without a special case (Duplicant has no other subtypes).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "creature", "creature_filter": {"nontoken": True},
                "optional": True, "remember": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec("static", [EffectSpec("type_change", {"affects": "self", "from_linked_exile": True})]),
    ]


register("Duplicant", _duplicant)
