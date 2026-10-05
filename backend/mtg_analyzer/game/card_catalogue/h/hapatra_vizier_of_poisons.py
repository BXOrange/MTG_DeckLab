from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hapatra_vizier_of_poisons() -> list[AbilitySpec]:
    """Whenever Hapatra deals combat damage to a player, you may put a
    -1/-1 counter on target creature.
    Whenever you put one or more -1/-1 counters on a creature, create a
    1/1 green Snake creature token with deathtouch.

    Registered wholesale, so both clauses are authored. The second is the
    Flourishing Defenses `EventType.COUNTER` shape (``kind``/
    ``recipient_is_creature``) plus the new causer-scoped ``by_you`` filter
    key (`effect_binder` — "whenever **you** put …", `COUNTER`'s
    ``source_controller_id``). "One or more" is the event itself: the
    engine fires one `COUNTER` per `add_counters` call regardless of amount.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "-1/-1", "target_kind": "creature"})],
            trigger={"event": "DAMAGE", "filter": {"combat": True, "is_player": True}},
            optional=True,
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Snake"], "keywords": ["deathtouch"], "token_name": "Snake",
            })],
            trigger={
                "event": "COUNTER",
                "filter": {"kind": "-1/-1", "recipient_is_creature": True, "by_you": True},
            },
        ),
    ]


register("Hapatra, Vizier of Poisons", _hapatra_vizier_of_poisons)
