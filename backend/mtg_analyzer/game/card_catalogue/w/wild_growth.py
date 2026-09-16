from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 2: mana primitives
#
# The headline new mechanism is the **triggered mana ability** (RULE
# 605.1b/605.4, `TriggeredAbility.mana_ability`): an ability that triggers
# off a mana ability and only produces mana never uses the stack at all — it
# resolves on the spot, so its mana is in the pool in time for the very
# payment that triggered it. Queueing it like an ordinary trigger would put
# the extra mana one full stack resolution too late to spend, which is the
# entire reason both Wild Growth and Kinnan are played.
#
# Alongside it: `GameContext.trigger_event` (RULE 603.1 — the firing event,
# exposed for exactly the resolution window, so an effect can depend on
# *which* firing without every `apply()` growing an event parameter) and the
# generalized `pay_cost_then` optional payment (RULE 118.3).
# ---------------------------------------------------------------------------


def _wild_growth() -> list[AbilitySpec]:
    """Enchant land
    Whenever enchanted land is tapped for mana, its controller adds an
    additional {G}.

    — Wild Growth. A **triggered mana ability** (RULE 605.1b): it triggers
    off a mana ability and produces only mana, so RULE 605.4 keeps it off
    the stack entirely and `RulesEngine._collect_triggers` resolves it
    immediately. That timing is the card — an extra {G} that arrived after a
    stack resolution would be useless for the spell you tapped the land to
    cast.

    The recipient is ``event_controller``, not the Aura's own controller:
    the text says "**its** controller", and RULE 110.2 lets those diverge
    under a control-change effect.

    Enchant land comes from the RULE 702 keyword catalogue; the trigger's
    subject is the shipped ``attached_permanent`` scoping (RULE 603.1), so
    it stops firing the instant the Aura is unattached, with no teardown.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["G"], "recipient": "event_controller"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "attached_permanent"},
                "mana_ability": True,
            },
        ),
    ]


register("Wild Growth", _wild_growth)
