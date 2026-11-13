"""Guile's complete Incarnation abilities."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _guile():
    """This creature can't be blocked except by three or more creatures.
If a spell or ability you control would counter a spell, instead exile that spell and you may play that card without paying its mana cost.
When Guile is put into a graveyard from anywhere, shuffle it into its owner's library."""
    return [
        AbilitySpec("static", [EffectSpec("combat_restriction", {"kind": "min_blockers", "count": 3, "affects": "self"})]),
        AbilitySpec("replacement", [EffectSpec("guile_counter", {})]),
        AbilitySpec("triggered", [EffectSpec("guile_shuffle", {})],
            trigger={"event": EventType.PUT_INTO_GRAVEYARD, "condition": {"subject": "self"}}),
    ]


register("Guile", _guile)
