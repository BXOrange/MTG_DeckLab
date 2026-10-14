from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _the_sprinkler_of_stardust() -> list[AbilitySpec]:
    """Whenever The Sprinkler of Stardust attacks, look at the top six cards of your library. You may put an instant or sorcery card from among them onto the battlefield tapped and attacking. It becomes a 2/2 creature with "Whenever this deals combat damage to an opponent, cast a copy of this card." (The 2/2 creature stays on the battlefield.) Put the rest of the cards on the bottom of your library in a random order.

    Un-card exception to RULE 304.4/307.4: the chosen spell stays as a creature.
    Its copy uses the printed card and still requires normal casting costs.
    """
    return [AbilitySpec(
        "triggered",
        [EffectSpec("inspect_top_choose", {
            "count": 6, "action": "library_to_battlefield_spell_attacking",
            "criteria": {"or": [{"type": "Instant"}, {"type": "Sorcery"}]},
            "max_picks": 1, "optional": True,
            "rest_destination": "library_bottom_random",
        })],
        trigger={"event": EventType.ATTACKS, "subject": "self"},
    )]


register("The Sprinkler of Stardust", _the_sprinkler_of_stardust)
