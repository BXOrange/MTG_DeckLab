"""The Battle of Dragon Brothers and its Fate Reforged Saga face."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_battle_of_dragon_brothers():
    """(As a Siege enters, choose an opponent to protect it. You and others can attack it. When it's defeated, exile it, then cast it transformed.)
When The Battle of Dragon Brothers Enters, choose Bolas or Ugin.
• Bolas — Destroy all creatures.
• Ugin — Manifest the top three cards of your library."""
    return [
        AbilitySpec("static", [EffectSpec("dragon_brothers_memory", {})]),
        AbilitySpec("triggered", [EffectSpec("dragon_brothers_choose", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}}),
    ]


def _fate_reforged():
    """I — (Bolas) Each opponent discards their hand. You draw seven cards.
I — (Ugin) Manifest your hand, then draw seven cards.
II — (Both) Create a token that's a copy of any Elder Dragon from the Legends expansion.
III — (Both) Exile Fate Reforged, then return it to the battlefield (Front face up)."""
    return [
        AbilitySpec("triggered", [EffectSpec("discard", {"scope": "each_opponent", "whole_hand": True}),
                                 EffectSpec("draw", {"count": 7})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1], "named_mode": "bolas"}),
        AbilitySpec("triggered", [EffectSpec("dragon_brothers_manifest_hand", {}), EffectSpec("draw", {"count": 7})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1], "named_mode": "ugin"}),
        AbilitySpec("triggered", [EffectSpec("dragon_brothers_elder", {})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2]}),
        AbilitySpec("triggered", [EffectSpec("blink", {"subject": "source"})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [3]}),
    ]


register("The Battle of Dragon Brothers", _the_battle_of_dragon_brothers)
register("The Battle of Dragon Brothers // Fate Reforged", _the_battle_of_dragon_brothers)
register("Fate Reforged", _fate_reforged)
