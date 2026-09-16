from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# PAR-68: Teamwork (RULE 702.194)-adjacent one-offs beyond the rider
# condition PAR-56 already closed. "Teamwork N" itself is a plain printed
# parametric keyword (`GameObject.parametric_keywords`, bound from the raw
# card text independent of catalogue registration — the same "bound once,
# regardless of registration" mechanism `entry_counters`/`enters_tapped`
# use), so none of these four entries need to reproduce it.
# ---------------------------------------------------------------------------


def _agent_maria_hill() -> list[AbilitySpec]:
    """Whenever Agent Maria Hill becomes tapped to pay a teamwork cost, put
    a +1/+1 counter on her and draw a card.

    — PAR-68. `TAPPED` already fires generically for every genuine tap
    transition; the new `reason="teamwork"` tag on Teamwork's own tap-to-pay
    loop (`casting_mixin`) plus the new `requires_tap_reason` trigger
    predicate (`binding/core.py`) are what let this trigger tell that apart
    from an ordinary attack/tap-ability transition, which fires the same
    event with no reason at all.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"}),
             EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.TAPPED, "condition": {"subject": "self"},
                "requires_tap_reason": "teamwork",
            },
        ),
    ]


register("Agent Maria Hill", _agent_maria_hill)
