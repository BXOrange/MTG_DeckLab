from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 20 (new core primitive: the "tapped for mana"
# event, RULE 605.1 — `EventType.TAPPED_FOR_MANA`)
# ---------------------------------------------------------------------------


def _price_of_glory() -> list[AbilitySpec]:
    """Whenever a player taps a land for mana, if it's not that player's
    turn, destroy that land.

    — Price of Glory. First consumer of the new `EventType.TAPPED_FOR_MANA`
    occurrence (`GameEngine.tap_for_mana`, RULE 605.1). Three primitives
    compose here, no bespoke code: the ``"group"`` subject scopes it to a
    *land* being tapped (`condition.type == "land"`, any player — no
    ``controller`` scoping); ``not_controllers_turn`` is the RULE 603.4
    intervening-if ("if it's not that player's turn", checked against the
    live active player, `effect_binder._trigger_condition`); and
    ``reflexive`` bakes in *that* land as the destroy target from the
    event's ``instance_id`` (RULE 603.3d, batch 16) — no target choice, and
    the trigger drops if the land somehow already left. Destroying a land is
    an ordinary stack trigger (not a mana ability), so normal resolution is
    correct.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy", {"target_kind": "land"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land"},
                "not_controllers_turn": True,
                "reflexive": True,
            },
        )
    ]


register("Price of Glory", _price_of_glory)
