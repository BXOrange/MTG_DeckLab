from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _loamcrafter_faun() -> list[AbilitySpec]:
    """When this creature enters, you may discard one or more land cards. When
    you do, return up to that many target nonland permanent cards from your
    graveyard to your hand.

    — PLAY-ALL Step 2 (World Shaper). The new `discard_chosen_then`
    (`SacrificeChosenThenEffect`'s hand-zone sibling): an optional pick of any
    number of land cards from hand through the chooser, then a RULE 603.12
    reflexive trigger whose ``x`` is the number discarded — `return_from_graveyard`
    of up to that many ``graveyard_nonland_permanent`` targets to hand. The
    discarded lands are in the graveyard by then but are not nonland permanents,
    so they are never offered.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("discard_chosen_then", {
                "what": "land",
                "trigger": [{"type": "return_from_graveyard", "params": {
                    "target_kind": "graveyard_nonland_permanent", "destination": "hand",
                    "count": "x", "optional": True,
                }}],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Loamcrafter Faun", _loamcrafter_faun)
