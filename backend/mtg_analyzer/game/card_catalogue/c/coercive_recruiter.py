from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _coercive_recruiter() -> list[AbilitySpec]:
    """Whenever this creature or another Pirate you control enters, gain
    control of target creature until end of turn. Untap that creature.
    Until end of turn, it gains haste and becomes a Pirate in addition to
    its other types.

    — Coercive Recruiter. Simplified in two ways, documented rather than
    guessed at: the trigger only fires on this creature's *own* entry
    (dropping "or another Pirate you control enters" — `GameObject.
    type_words`, the only vocabulary a "group" trigger subject's ``type``
    filter reads, is main card types only, never subtypes, so "Pirate"
    can't be recognized there without a new subtype-aware ENTERS_
    BATTLEFIELD trigger scope, out of this batch's size); and the granted
    "...becomes a Pirate in addition to its other types" tail is dropped
    (no layer-6 temporary-type-grant-on-a-temporarily-controlled-permanent
    primitive exists). Both per the Sword of Forge and Frontier precedent
    (a genuinely partial model, documented, rather than skipping the whole
    card) — the control-change/untap/haste half is the same
    `GainControlUntilEndOfTurnEffect` Zealous Conscripts uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_control_until_eot", {"target_kind": "creature"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Coercive Recruiter", _coercive_recruiter)
