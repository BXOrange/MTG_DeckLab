from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _possibility_storm() -> list[AbilitySpec]:
    """Whenever a player casts a spell from their hand, that player exiles
    it, then exiles cards from the top of their library until they exile a
    card that shares a card type with it. That player may cast that card
    without paying its mana cost. Then they put all cards exiled with this
    enchantment on the bottom of their library in a random order.

    — Possibility Storm. Three things had to exist for this:

    * "casts a spell **from their hand**" — the `SPELL_CAST` event now
      carries ``from_hand``, snapshotted before the card leaves its zone
      (by the time the event fires it already sits on the stack).
    * "**that** spell" is the RULE 603.3d ``reflexive`` trigger shape, so
      the exile acts on the exact spell that fired the trigger.
    * "shares a card type **with it**" (RULE 205.2) is read off the
      answered spell's own types, snapshotted before it leaves the stack.

    Note "that player **exiles** it" is a zone change, not a counter
    (`RulesEngine.move_spell_off_stack`) — which is why Possibility Storm
    also gets around "can't be countered". The whole tail runs against the
    *casting* player, who may be an opponent: Possibility Storm scrambles
    everyone's spells, which is the point.

    **Documented simplification**: "they may cast that card" is taken
    automatically, the same MVP choice the cascade family's own free cast
    documents.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("scramble_spell", {
                "answer": "exile",
                "match": "shares_card_type",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "filter": {"from_hand": True},
                "reflexive": True,
            },
        ),
    ]


register("Possibility Storm", _possibility_storm)
