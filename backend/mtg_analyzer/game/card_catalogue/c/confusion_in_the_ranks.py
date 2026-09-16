from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# --- PAR-30 · RULE 701.10 exchange-control residue -------------------------
#
# The remaining ten cards the shared cross-target predicates (PARSER_VERSION
# 211) didn't reach — each its own bespoke primitive, hand-authored per
# BACKLOG.md rather than widened parser grammar (none of these shapes
# repeats across more than this one card).


def _confusion_in_the_ranks() -> list[AbilitySpec]:
    """Whenever an artifact, creature, or enchantment enters, its
    controller chooses target permanent another player controls that
    shares a card type with it. Exchange control of those permanents.

    — The chooser is the *entering permanent's* controller, not this
    Enchantment's own controller (`TriggeredAbility.controller_from_
    trigger_event`, PAR-30's own new primitive) — a RULE 603.1 group
    trigger with no controller restriction of its own (any player's
    permanent). `ExchangeControlEffect(first_target_kind="trigger_subject")`
    reads the entering permanent straight off the firing event; `shares_
    type="card"` is the ordinary cross-target predicate every other "shares
    a card type" exchange card already uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control", {
                "first_target_kind": "trigger_subject",
                "target_kind": "permanent_you_dont_control",
                "shares_type": "card",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": ["artifact", "creature", "enchantment"]},
                "chooser": "trigger_subject_controller",
            },
        ),
    ]


register("Confusion in the Ranks", _confusion_in_the_ranks)
