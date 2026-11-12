"""The Crimson Avenger."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_crimson_avenger():
    """Flash
When The Crimson Avenger enters the battlefield, choose target spell an opponent controls. Reveal cards from the top of your library until you reveal a card that shares a mana value with it. Cast that card without paying its mana cost. Then shuffle your library.
"""
    return [AbilitySpec(
        "triggered", [EffectSpec("reveal_matching_spell_value", {})],
        trigger={"event": EventType.ENTERS_BATTLEFIELD},
    )]


register("The Crimson Avenger", _the_crimson_avenger)
