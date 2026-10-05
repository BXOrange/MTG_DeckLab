from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-11 — the Enrage stragglers: real cards left UNMODELED after the
# parser's own general "whenever ~ is dealt damage" recognition
# (`parser/oracle/segmenter.py`'s `_DAMAGE_RECIPIENT_TRIGGER_RE`) closed the
# trigger side. Each of these fails on its *effect body*, not the Enrage
# trigger itself — a second, narrower gap per card. Several needed a small
# new primitive (`damage_equal_to_counters`, `AddManaEffect.
# amount_from_trigger_event`, `AddCountersEffect`/`DealDamageEffect`'s
# widened selector vocabulary, the `opponent`/`opponent_or_planeswalker`
# target kinds) rather than being purely bespoke — each documented at its
# own definition in `game/effects/core.py`/`game/targeting.py`. Every entry below
# also documents its own simplifications inline; none silently drops a
# clause without saying so.
# ---------------------------------------------------------------------------


def _bellowing_aegisaur() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, put a +1/+1 counter
    on each other creature you control.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"selector": "each_other_creature_you_control"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
        ),
    ]


register("Bellowing Aegisaur", _bellowing_aegisaur)
