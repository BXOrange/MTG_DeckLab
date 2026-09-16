from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _memory_vampire() -> list[AbilitySpec]:
    """Flying
    Whenever this creature deals combat damage to a player, any number of
    target players each mill that many cards. Then you may collect evidence
    9. When you do, you may cast target nonland card from defending player's
    graveyard without paying its mana cost.

    — PAR-30 (Collect Evidence / Forage / Blight residue). Flying parses;
    the combat-damage trigger is hand-authored (`MemoryVampireCombatEffect`
    — see its docstring for the multi-target-mill / collect-9 / free-cast
    auto-pick simplifications).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec(
            "triggered",
            [EffectSpec("memory_vampire_combat", {})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Memory Vampire", _memory_vampire)
