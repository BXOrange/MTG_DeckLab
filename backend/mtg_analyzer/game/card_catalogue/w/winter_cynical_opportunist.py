from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The printed "four or more card types among them" (RULE 702.150-style Delirium threshold).
_MIN_CARD_TYPES = 4
#: "any number of cards" — the chooser's ceiling (a graveyard never approaches it).
_ANY_NUMBER = "all"


def _winter_cynical_opportunist() -> list[AbilitySpec]:
    """Deathtouch
    Whenever Winter attacks, mill three cards.
    Delirium — At the beginning of your end step, you may exile any number of cards from your graveyard with four or more card types among them. If you do, put a permanent card from among them onto the battlefield with a finality counter on it.

    — PLAY-ALL (Death Toll). Deathtouch and the attack mill are the parser's. The end step is a `choose_objects` over your graveyard that only *selects*
    (``select_only``: the set's legality depends on all of its members, so nothing is applied pick by pick; declining ends the selection),
    then `exile_selected_then_return_one` judges the set — fewer than four card types does nothing — exiles it and lets you pick a permanent card
    to enter with a finality counter (the new RULE 122.1h replacement in `_move_to_graveyard`: it is exiled instead of going to the graveyard).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mill", {"count": 3})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_objects", {
                "action": "select_only", "what": "permanent", "pool_zone": "graveyard", "count": _ANY_NUMBER, "optional": True,
                "prompt": "Karten aus dem Friedhof wählen (mindestens vier Kartentypen)",
                "then": [{"type": "exile_selected_then_return_one", "params": {
                    "instance_ids": {"kind": "chosen_instance_ids"}, "min_card_types": _MIN_CARD_TYPES,
                }}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Winter, Cynical Opportunist", _winter_cynical_opportunist)
