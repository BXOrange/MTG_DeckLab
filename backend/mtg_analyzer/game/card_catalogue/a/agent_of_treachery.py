from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "three or more permanents you don't own" — the printed threshold.
_FOREIGN_PERMANENTS = 3
_PERMANENTS_YOU_DONT_OWN = {"zone": "battlefield", "of": "you", "filter": {"not_owned_by_you": True}}


def _agent_of_treachery() -> list[AbilitySpec]:
    """When this creature enters, gain control of target permanent.
    At the beginning of your end step, if you control three or more permanents
    you don't own, draw three cards.

    — PLAY-ALL Step 2 (Oops! All Night's Whispers). The ETB steal is the parser's
    own claim, reproduced. The end-step draw is a `STEP_BEGIN` (end, your turn)
    trigger whose `draw 3` is gated on a `control_count` over a structured
    selector — permanents on the battlefield under your control that
    ``not_owned_by_you`` — as RULE 603.4's intervening "if" (re-checked as it
    resolves).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_control_until_eot", {
                "target_kind": "permanent", "duration": "permanent", "haste": False, "untap": False,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 3}, condition={
                "kind": "control_count", "selector": dict(_PERMANENTS_YOU_DONT_OWN), "min": _FOREIGN_PERMANENTS,
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Agent of Treachery", _agent_of_treachery)
