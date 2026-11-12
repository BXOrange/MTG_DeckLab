"""Invasion of Alara and Awaken the Maelstrom."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_alara():
    """When this Siege enters, exile cards from the top of your library until you exile two nonland cards with mana value 4 or less. You may cast one of those two cards without paying its mana cost. Put one of them into your hand. Then put the other cards exiled this way on the bottom of your library in a random order."""
    return [AbilitySpec("triggered", [EffectSpec("alara_exile", {}), EffectSpec("alara_take_hand", {}),
                                     EffectSpec("alara_bottom_rest", {})],
        trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}})]


def _awaken_the_maelstrom():
    """Awaken the Maelstrom is all colors.
Target player draws two cards. You may put an artifact card from your hand onto the battlefield. Create a token that's a copy of a permanent you control. Distribute three +1/+1 counters among one, two, or three creatures you control. Destroy target permanent an opponent controls."""
    # The all-colors CDA is read by printed_colors in every zone.
    return [AbilitySpec("spell_effect", [
        EffectSpec("draw", {"count": 2, "target_kind": "player"}),
        EffectSpec("maelstrom_artifact", {}), EffectSpec("maelstrom_copy", {}),
        EffectSpec("maelstrom_counters", {}),
        EffectSpec("destroy", {"target_kind": "permanent_you_dont_control"}),
    ])]


register("Invasion of Alara", _invasion_of_alara)
register("Invasion of Alara // Awaken the Maelstrom", _invasion_of_alara)
register("Awaken the Maelstrom", _awaken_the_maelstrom)
