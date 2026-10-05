from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _immolation_shaman() -> list[AbilitySpec]:
    """Whenever an opponent activates an ability of an artifact, creature,
    or land that isn't a mana ability, this creature deals 1 damage to
    that player.
    {3}{R}{R}: This creature gets +3/+3 and gains menace until end of turn.

    — Immolation Shaman. Harsh Mentor's own 1-damage sibling; its pump
    ability is already parser-claimed (`author_card.py reuse`) and just
    copied here verbatim, since registering a card replaces the parser's
    specs wholesale rather than merging with them.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"power": 3, "toughness": 3, "keywords": ["menace"]})],
            cost={"text": "{3}{r}{r}"},
        ),
    ]


register("Immolation Shaman", _immolation_shaman)
