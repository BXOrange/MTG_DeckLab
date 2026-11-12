"""Arcavios searches only the places its controller actually chooses to inspect."""
from .core import GameEffect, _controller_of
from ..continuations import choice, ANSWER_STR
from ...models.game.events import EventType, GameEvent


_PLACES = {"library": "Bibliothek", "graveyard": "Friedhof", "outside": "Außerhalb des Spiels"}


def _pool(rules, frame, place):
    player = rules.state.player_by_id(frame["player_id"])
    objects = player.sideboard if place == "outside" else rules._search_zone_objects(player, [place])
    return [obj for obj in objects if obj.owner_id == player.id and not obj.is_token
            and (obj.card.is_instant or obj.card.is_sorcery)]


def _offer(rules, frame):
    player = rules.state.player_by_id(frame["player_id"])
    visited = frame["visited"]
    options = [{"id": f"search:{place}", "label": f"{label} durchsuchen"}
               for place, label in _PLACES.items() if place not in visited
               and (place != "library" or not rules.is_search_prohibited_for(player))]
    for place in visited:
        options.extend({"id": str(obj.instance_id), "instance_id": obj.instance_id,
                        "incarnation": obj.zone_incarnation, "place": place,
                        "label": f"{obj.name} ({_PLACES[place]})"} for obj in _pool(rules, frame, place))
    # RULE 701.23b: a searched public zone cannot fail to find a match.
    if visited and not ("graveyard" in visited and _pool(rules, frame, "graveyard")):
        options.append({"id": "done", "label": "Keine Karte finden"})
    rules.open_choice({**frame, "kind": "arcavios_search", "prompt": "Spontanzauber oder Hexerei suchen",
                       "options": options})


@choice("arcavios_search", answer=ANSWER_STR, rule="701.23")
def _resume(rules, frame, answer):
    option = next((o for o in frame["options"] if o["id"] == answer), None)
    if option is None:
        rules.open_choice(frame)
        raise ValueError("Choose an offered search location or card")
    player = rules.state.player_by_id(frame["player_id"])
    if answer.startswith("search:"):
        place = answer.split(":", 1)[1]
        if place == "library":
            rules.state.fire_event(GameEvent(EventType.LIBRARY_SEARCHED, player_id=player.id))
        _offer(rules, {**frame, "visited": [*frame["visited"], place]})
        return
    if answer != "done":
        place = option["place"]
        obj = next((o for o in _pool(rules, frame, place)
                    if o.instance_id == option["instance_id"] and o.zone_incarnation == option["incarnation"]), None)
        if obj is None:
            _offer(rules, frame)
            raise ValueError("That card is no longer in the searched location")
        if place == "library":
            # Reuse the library-search destination and redirect machinery.
            rules._finish_search(player, [obj.instance_id], "hand", zones=["library"], reveal=True)
            return
        rules.state.reveal_card(obj, player.id)
        rules.return_to_hand(obj)
        obj.controller_id = player.id
    if "library" in frame["visited"]:
        rules.shuffle_library(player)


class ArcaviosSearchEffect(GameEffect):
    def apply(self, context, targets=None):
        # The MOM release notes explicitly allow inspecting another place
        # after searching the first; do not expose the library before that choice.
        player = _controller_of(self.source, context)
        _offer(context.engine, {"player_id": player.id, "visited": []})
