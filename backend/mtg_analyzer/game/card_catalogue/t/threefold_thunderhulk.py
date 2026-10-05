from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _threefold_thunderhulk() -> list[AbilitySpec]:
    """This creature enters with three +1/+1 counters on it.
    Whenever this creature enters or attacks, create a number of 1/1
    colorless Gnome artifact creature tokens equal to its power.
    {2}, Sacrifice another artifact: Put a +1/+1 counter on this creature.

    — PLAY-ALL Step 2 (Counter Intelligence). The enters-with-counters clause is
    read off the card's text (it applies before the ETB trigger, so the power
    counted already includes the three counters). The sacrifice ability is the
    parser's own claim. The token trigger is `create_token` whose ``count`` is a
    `count_selector` operand over ``source_power`` — one spec per event (enters,
    attacks), the same two-trigger shape as any "enters or attacks" ability.
    """
    token = {
        "power": 1, "toughness": 1, "subtypes": ["Gnome"], "keywords": [], "token_name": "Gnome",
        "is_artifact": True,
        "count": {"kind": "count_selector", "selector": "source_power"},
    }
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", dict(token))],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", dict(token))],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            cost={"text": "{2}, Sacrifice another artifact"},
        ),
    ]


register("Threefold Thunderhulk", _threefold_thunderhulk)
