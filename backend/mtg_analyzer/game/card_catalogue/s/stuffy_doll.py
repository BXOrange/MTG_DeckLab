from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stuffy_doll() -> list[AbilitySpec]:
    """Indestructible
    As this creature enters, choose a player.
    Whenever this creature is dealt damage, it deals that much damage to
    the chosen player.
    {T}: This creature deals 1 damage to itself.

    — Imodane deck batch. Indestructible is a RULE 702 keyword, auto-
    bound. The player choice is the new `_request_choose_player`
    (`GameObject.chosen_player_id`); the damage-redirect trigger is the
    new `self_as_recipient` trigger subject (the "is dealt damage"
    mirror image of the ordinary source-keyed "self") paired with the
    new `deal_damage_to_chosen_player`, reading the firing event's own
    amount. The activated ability is a plain self-damage.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("_request_choose_player", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("deal_damage_to_chosen_player", {})],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self_as_recipient"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 1, "selector": "self"})],
            cost={"text": "{T}"},
        ),
    ]


register("Stuffy Doll", _stuffy_doll)
