from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _archfiend_of_spite() -> list[AbilitySpec]:
    """Flying
    Whenever a source an opponent controls deals damage to this creature, that source's controller loses that much
    life unless they sacrifice that many permanents of their choice.
    Madness {3}{B}{B}

    Flying and Madness are RULE 702 keywords folded in by the keyword catalogue. The trigger is `DAMAGE` to self
    (``recipient``) with the new ``by_opponent`` filter; `damage_source_sacrifice_or_lose_life` reads the event's
    amount and ``source_controller_id`` (RULE 118.12 unless-cost owed by that controller).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage_source_sacrifice_or_lose_life", {})],
            trigger={
                "event": "DAMAGE", "condition": {"subject": "self", "recipient": True},
                "filter": {"by_opponent": True},
            },
        ),
    ]


register("Archfiend of Spite", _archfiend_of_spite)
