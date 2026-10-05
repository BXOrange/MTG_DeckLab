from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _evercoat_ursine() -> list[AbilitySpec]:
    """Trample
    Hideaway 3, hideaway 3 (When this creature enters, look at the top three cards of your library,
    exile one face down, then put the rest on the bottom in a random order. Then do it again.)
    Whenever this creature deals combat damage to a player, if there are cards exiled with it, you
    may play one of them without paying its mana cost.

    — Animated Army deck batch. Trample is a keyword; hideaway is printed twice, so a second
    ``keyword`` spec adds the second ETB trigger (an authored keyword replaces the parsed one, so both
    instances are authored here). The damage
    trigger is Mosswort Bridge's `play_hideaway_card` (RULE 608.2g resolution play, ``repeat=False`` is
    per offered card list), reading the links off the source because a trigger has no activation
    event. The "if there are cards exiled with it" intervening-if is the effect finding nothing to
    offer — a trigger with no linked cards still reaches the stack and does nothing.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "hideaway", "n": 3}),
        AbilitySpec("keyword", [], keyword={"name": "hideaway", "n": 3}),
        AbilitySpec(
            "triggered",
            [EffectSpec("play_hideaway_card", {})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Evercoat Ursine", _evercoat_ursine)
