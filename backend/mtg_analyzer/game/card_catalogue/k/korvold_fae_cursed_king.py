from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _korvold_fae_cursed_king() -> list[AbilitySpec]:
    """Flying
    Whenever Korvold enters or attacks, sacrifice another permanent.
    Whenever you sacrifice a permanent, put a +1/+1 counter on Korvold and
    draw a card.

    — MEC-43 round 4B. Flying folds in via the ordinary keyword catalogue.
    The first trigger is the shipped "~ enters or attacks" multi-event
    trigger (The Wise Mothman) paired with `ChooseObjectsEffect`'s
    mandatory (``optional=False`` default) form — the same "player picks
    which" shape Vraska, Golgari Queen's own sacrifice already uses, just
    forced rather than "you may," with ``exclude_self=True`` for
    "another." The second is Mayhem Devil's `EventType.SACRIFICE` (RULE
    701.17) scoped to ``{"subject": "you"}`` (Rapacious Guest/Mirkwood
    Bats's own precedent for "whenever you sacrifice a permanent/token"),
    pairing `AddCountersEffect`'s default (self, +1/+1, amount 1) with a
    plain draw.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_objects", {"action": "sacrifice", "what": "permanent", "exclude_self": True})],
            trigger={
                "event": [EventType.ENTERS_BATTLEFIELD, EventType.ATTACKS],
                "condition": {"subject": "self"},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {}), EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.SACRIFICE, "condition": {"subject": "you"}},
        ),
    ]


register("Korvold, Fae-Cursed King", _korvold_fae_cursed_king)
