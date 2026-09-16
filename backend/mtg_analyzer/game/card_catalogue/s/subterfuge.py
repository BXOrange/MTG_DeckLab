from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-75: Dance of the Elements — temporary parameterized trigger grants
# ---------------------------------------------------------------------------


def _subterfuge() -> list[AbilitySpec]:
    """Give the ETB target flying and its own combat-damage draw trigger.

    The quoted trigger is deliberately a second ``grant_until`` static,
    rather than a marker keyword on the target: each affected creature needs
    a real RULE 603 ability whose source is that creature, and whose draw
    amount is read from the particular DAMAGE event that made it trigger.
    ``GrantUntilEffect`` keeps both statics in the existing duration store,
    so the grant is re-derived while it lasts and disappears at cleanup.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn",
                "target_kind": "creature",
                "static": {
                    "type": "grant_keyword",
                    "params": {"keywords": ["flying"]},
                },
                "extra_statics": [{
                    "type": "grant_triggered_ability",
                    "params": {
                        "trigger_event": EventType.DAMAGE,
                        "filter": {"combat": True, "is_player": True},
                        "grant_effects": [{
                            "type": "draw",
                            "params": {"count_from_trigger_event": "amount"},
                        }],
                    },
                }],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Subterfuge", _subterfuge)
