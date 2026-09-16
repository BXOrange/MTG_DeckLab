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

    "That spell" is the RULE 603.3d ``reflexive`` trigger shape, so the copy
    acts on the exact spell that fired the trigger rather than a freshly
    chosen target — the same mechanism Lavinia's "counter that spell" uses.
    An opponent who can't afford {2} is never asked (the shortcut ward and
    `counter_unless_pays` already take), and the else-branch fires straight
    away.

    **Documented simplification**: "you *may* copy" is taken (the copy is
    the only reason the trigger exists), and new targets aren't chosen — the
    same `CopySpellEffect` MVP the whole copy family shares. The back face
    "Explore the Vastlands" is a modal-DFC land half, covered by the shipped
    MDFC machinery independently of this registration.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{2}",
                "payer": "event_player",
                "effects": [],
                "else_effects": [
                    {"type": "copy_spell", "params": {"card_types": ["instant", "sorcery"]}},
                ],
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_card_types": ["instant", "sorcery"],
                "reflexive": True,
            },
        ),
    ]


register("Wandering Archaic", _wandering_archaic)
