from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nullhide_ferox() -> list[AbilitySpec]:
    """Hexproof
    You can't cast noncreature spells.
    {2}: This creature loses all abilities until end of turn. Any player may
    activate this ability.
    If a spell or ability an opponent controls causes you to discard this
    card, put it onto the battlefield instead of putting it into your
    graveyard.

    MEC-102 — the discard-destination half of the "caused you to discard"
    cycle; see `loxodon_smiter.py`'s docstring for the shared mechanism.
    Registering this card for its own replacement means every other clause
    has to be authored too (hand authoring is all-or-nothing per card,
    `card_registry.specs_for`), all three already-general primitives:
    Hexproof folds in automatically (the keyword catalogue always merges,
    win or lose); "can't cast noncreature spells" is the existing
    `player_cast_restriction`; the pressure-valve activated ability is an
    ordinary self-targeted `grant_until` of the same `remove_all_abilities`
    static Humility/Dress Down already use (RULE 613.7f, `GameObject.
    loses_all_abilities`) — Temur Sabertooth's own `grant_until(self_
    subject=True, …)` composition, just with a different inner static —
    plus `ActivationCost.any_player_may_activate` (MEC-30, Mercenaries).
    """
    return [
        AbilitySpec("static", [EffectSpec("player_cast_restriction", {"noncreature": True})]),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "self_subject": True, "duration": "end_of_turn",
                "static": {"type": "remove_all_abilities", "params": {}},
            })],
            cost={"mana": "{2}", "any_player_may_activate": True},
        ),
        AbilitySpec("replacement", [EffectSpec("discard_to_battlefield", {})]),
    ]


register("Nullhide Ferox", _nullhide_ferox)
