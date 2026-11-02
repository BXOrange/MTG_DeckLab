"""Per-card-type picks from a revealed group (Hurkyl, Master Wizard).

"Reveal the top five cards of your library. For each card type among noncreature spells you've cast this turn, you may
put a card of that type from among the revealed cards into your hand. Put the rest on the bottom of your library in a
random order."

Atraxa, Grand Unifier's `distinct_card_types` pick lets *any* card type count; here only a fixed set of types may be
used, and each type is its own optional decision, asked in turn (RULE 608.2c: instructions are followed in order). A
card put into the hand by one type's pick is no longer among the revealed cards for the next, so a multi-type card
cannot be taken twice. The choice carries only ids and strings, so clone/undo keeps it intact.
"""

from __future__ import annotations

from typing import Any, Optional

from ...models.game.game_object import GameObject, Zone
from ...models.game.player import Player
from .. import continuations
from .misc_helpers import _card_type_words

#: Where the unpicked revealed cards go ("on the bottom of your library in a random order").
REST_DESTINATION = "library_bottom_random"
#: The pick's action: a library card put into its owner's hand.
PICK_ACTION = "library_to_hand"


class TypePicksRulesMixin:
    def _open_type_pick(
        self, player: Player, revealed_ids: list[int], types_left: list[str], source: Optional[GameObject],
    ) -> None:
        """Ask for the next card type that still has an eligible revealed card; with none left, bottom the rest."""
        revealed = [obj for obj in (self._object_by_instance_id(i) for i in revealed_ids)
                    if obj is not None and obj.zone == Zone.LIBRARY]
        types = list(types_left)
        while types:
            card_type = types[0]
            eligible = [obj for obj in revealed if card_type in _card_type_words(obj)]
            if eligible:
                self.open_choice({
                    "kind": "type_pick",
                    "player_id": player.id,
                    "source_id": source.instance_id if source is not None else None,
                    "card_type": card_type,
                    "types_left": types[1:],
                    "revealed_ids": [obj.instance_id for obj in revealed],
                    "prompt": f"Karte vom Typ {card_type} auf die Hand nehmen?",
                    "options": [
                        *({"id": str(obj.instance_id), "label": obj.name, "instance_id": obj.instance_id}
                          for obj in eligible),
                        {"id": "decline", "label": "Nichts wählen"},
                    ],
                })
                return
            types.pop(0)  # RULE 608.2d: nothing of this type was revealed, so there is nothing to decide
        self._handle_rest_inspected(player, [obj.instance_id for obj in revealed], REST_DESTINATION)

    @continuations.choice("type_pick", answer=continuations.ANSWER_STR, rule="608.2c")
    def _resume_type_pick(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Take the chosen card (if any) into the hand, then move on to the next card type."""
        player = self.state.player_by_id(choice["player_id"])
        source = self._object_by_instance_id(choice.get("source_id"))
        revealed_ids = list(choice["revealed_ids"])
        offered = {str(option["id"]) for option in choice["options"] if "instance_id" in option}
        if answer in offered:  # anything else is a decline: the pick is a "may"
            picked = self._object_by_instance_id(int(answer))
            if picked is not None and picked.zone == Zone.LIBRARY:
                self._apply_chosen_object(player, picked, PICK_ACTION, source)
                revealed_ids.remove(picked.instance_id)
        self._open_type_pick(player, revealed_ids, choice["types_left"], source)
