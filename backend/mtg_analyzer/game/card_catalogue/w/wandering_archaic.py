from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wandering_archaic() -> list[AbilitySpec]:
    """Whenever an opponent casts an instant or sorcery spell, they may pay
    {2}. If they don't, you may copy that spell. You may choose new targets
    for the copy.

    — Wandering Archaic // Explore the Vastlands. The tax is the new
    ``pay_cost_then`` (RULE 118.3), with two features this card is what
    forced: the **payer** is the player named by the triggering event (the
    opponent who cast the spell), not the effect's own controller; and the
    "**If they don't**, …" branch is where all the action is — the
    else-branch is what copies the spell.

    The spell is an untargeted firing-event referent. Its copiable recipe
    survives countering or returning the original, the opponent's tax choice,
    and the controller's optional copy decision. Targets are chosen before
    the copy enters the stack. The MDFC land half uses the shared machinery.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{2}",
                "payer": "event_player",
                "effects": [],
                "else_effects": [
                    {"type": "optional", "params": {
                        "prompt": "Den Zauber mit Wandering Archaic kopieren?",
                        "effects": [{"type": "copy_spell", "params": {
                            "spell_from_trigger_event": "instance_id", "choose_new_targets": True,
                        }}],
                    }},
                ],
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_card_types": ["instant", "sorcery"],
            },
        ),
    ]


register("Wandering Archaic", _wandering_archaic)
