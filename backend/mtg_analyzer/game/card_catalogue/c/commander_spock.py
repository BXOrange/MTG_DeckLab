from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _commander_spock() -> list[AbilitySpec]:
    """Strange new worlds — Whenever Commander Spock enters or attacks, reveal the top card of your library. You may cast that card without paying its mana cost if that spell's mana value is equal to or less than the number of differently named lands you control. If it's a land card, you may put it onto the battlefield tapped. If that card is still on top of your library, draw a card."""
    def effects():
        return [
            EffectSpec("reveal_top", {}),
            EffectSpec("cast_window_exiled_pool", {"pool_zone": "library", "resolution_local": True,
                "only_spells": True, "free": True, "card_filter": {"max_mana_value": {
                    "kind": "count_selector", "selector": {"zone": "battlefield", "of": "you",
                    "filter": {"card_type": "land"}, "distinct": "name"}}}}),
            EffectSpec("optional", {"effects": [{"type": "put_revealed_card", "params": {
                "destination": "battlefield_tapped"}}]}, condition={
                    "kind": "is_card_type", "of": "revealed", "card_type": "land"}),
            EffectSpec("draw", {"count": 1}, condition={"kind": "revealed_card_on_library_top"}),
        ]
    return [AbilitySpec("triggered", effects(), trigger={"event": event, "condition": {"subject": "self"}})
            for event in (EventType.ENTERS_BATTLEFIELD, EventType.ATTACKS)]


register("Commander Spock", _commander_spock)
