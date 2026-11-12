"""Both physical faces of Flamewar."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _brash_veteran():
    """More Than Meets the Eye {B}{R} (You may cast this card converted for {B}{R}.)
Sacrifice another artifact: Put a +1/+1 counter on Flamewar and convert it. Activate only as a sorcery.
{1}, Discard your hand: Put all exiled cards you own with intel counters on them into your hand."""
    return [
        AbilitySpec("activated", [EffectSpec("flamewar_upgrade", {})],
                    cost={"text": "Sacrifice another artifact", "sorcery_speed_only": True}),
        AbilitySpec("activated", [EffectSpec("flamewar_recover_intel", {})],
                    cost={"text": "{1}, Discard your hand"}),
    ]


def _streetwise_operative():
    """Living metal (During your turn, this Vehicle is also a creature.)
Menace, deathtouch
Whenever Flamewar deals combat damage to a player, exile that many cards from the top of your library face down. Put an intel counter on each of them. Convert Flamewar."""
    return [
        AbilitySpec("keyword", [], keyword={"name": "living_metal"}),
        AbilitySpec("keyword", [], keyword={"name": "menace"}),
        AbilitySpec("keyword", [], keyword={"name": "deathtouch"}),
        AbilitySpec("triggered", [EffectSpec("flamewar_intel_exile", {})],
                    trigger={"event": EventType.DAMAGE, "condition": {"subject": "self"},
                             "filter": {"combat": True, "is_player": True}}),
    ]


register("Flamewar, Brash Veteran", _brash_veteran)
register("Flamewar, Brash Veteran // Flamewar, Streetwise Operative", _brash_veteran)
register("Flamewar, Streetwise Operative", _streetwise_operative)
