from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "thirty or more counters" (the printed threshold).
COUNTER_THRESHOLD = 30
#: The damage dealt to each opponent when the threshold is met (printed).
ARTILLERY_DAMAGE = 10


def _lux_artillery() -> list[AbilitySpec]:
    """Whenever you cast an artifact creature spell, it gains sunburst. (It
    enters with a +1/+1 counter on it for each color of mana spent to cast it.)
    At the beginning of your end step, if there are thirty or more counters
    among artifacts and creatures you control, this artifact deals 10 damage to
    each opponent.

    — PLAY-ALL Step 2 (Counter Intelligence). The cast trigger is the parser's
    own head (``spell_filter: card_type_all [artifact, creature]``) over the new
    `grant_sunburst_to_triggering_spell` (marks the spell on the stack; the
    entry-counter hook turns it into counters per colour of mana spent, RULE
    702.43a). The end step is an `amount_compare` gate (RULE 603.4's intervening
    "if", checked as the trigger fires and again on resolution) over
    the new `counters_among_permanents` amount (scope ``artifacts_and_creatures_you_control``)
    — an artifact creature counts once.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_sunburst_to_triggering_spell", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "you"},
                "spell_filter": {"card_type_all": ["artifact", "creature"]},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": ARTILLERY_DAMAGE, "selector": "each_opponent"}, condition={
                "kind": "amount_compare", "op": "ge",
                "left": {"kind": "counters_among_permanents", "scope": "artifacts_and_creatures_you_control"},
                "right": {"kind": "fixed", "amount": COUNTER_THRESHOLD},
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Lux Artillery", _lux_artillery)
