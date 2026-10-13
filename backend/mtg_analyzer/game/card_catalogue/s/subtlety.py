from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _subtlety() -> list[AbilitySpec]:
    """Flash
    Flying
    When this creature enters, choose up to one target creature spell or planeswalker spell. Its owner puts it on their choice of the top
    or bottom of their library.

    — PAR-161. Flash/Flying are keywords. The trigger is `owner_puts_on_top_or_bottom` (RULE 401.4: the spell's owner picks the end) over
    the ``spell`` kind, whose ``spell_filter`` card types are an OR (creature / planeswalker); "up to one" is ``optional``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("owner_puts_on_top_or_bottom", {
                "target_kind": "spell", "optional": True,
                "spell_filter": {"card_types": ["creature", "planeswalker"]},
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Subtlety", _subtlety)
