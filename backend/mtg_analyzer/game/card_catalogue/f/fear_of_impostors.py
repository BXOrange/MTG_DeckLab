from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fear_of_impostors() -> list[AbilitySpec]:
    """Flash
    When this creature enters, counter target spell. Its controller manifests dread. (That player looks at the top two
    cards of their library, then puts one onto the battlefield face down as a 2/2 creature and the other into their
    graveyard. If it's a creature card, it can be turned face up any time for its mana cost.)

    — Flash is the card's own keyword. The ETB is Swan Song's shape: `counter`, then a follow-up for the countered
    spell's controller (RULE 608.2h: the countered spell object keeps its ``controller_id``), here `manifest_dread`
    with the ``player="previous_target_controller"`` referent (RULE 701.62a, the manifesting player is the
    spell's controller, not Fear's).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "counter", "params": {}},
                {"type": "manifest_dread", "params": {"player": "previous_target_controller"}},
            ]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="when ~ enters, counter target spell. its controller manifests dread.",
        ),
    ]


register('Fear of Impostors', _fear_of_impostors)
