"""Session-local table conversation and public action announcements (VIS-4)."""

from mtg_analyzer.models.game.events import EventType

# Bound memory and view payloads even in long games with many mana activations.
MAX_TABLE_MESSAGES = 200
# Fixed emotes only; the table has no free-text messaging.
TABLE_EMOTES = ("👍", "👏", "GG", "🤔", "⏳")

ANNOUNCED_EVENTS = {
    EventType.LAND_PLAYED: ("play_land", "land"),
    EventType.SPELL_CAST: ("cast_spell", "spell"),
    EventType.ACTIVATED_ABILITY: ("activate_ability", "object"),
    EventType.TAPPED_FOR_MANA: ("tap_for_mana", "object"),
    EventType.MANA_ABILITY_ACTIVATED: ("activate_hand_mana", "object"),
    EventType.TURNED_FACE_UP: ("turn_face_up", "object"),
    # RULE 709.5h (MEC-111): a Room door unlocked (cast, special action or effect) — named by the half's own name.
    EventType.DOOR_UNLOCKED: ("unlock_door", "door_name"),
}


class TableFeed:
    def __init__(self):
        self.messages = []
        self.next_id = 1

    def append(self, **entry):
        self.messages.append({"id": self.next_id, **entry})
        self.next_id += 1
        del self.messages[:-MAX_TABLE_MESSAGES]

    def emote(self, actor, emote, turn):
        if not isinstance(emote, str) or emote not in TABLE_EMOTES:
            raise ValueError("unknown table emote")
        self.append(kind="emote", actor_id=actor.id, author=actor.name,
                    text=emote, turn=turn)

    def announce_events(self, state, events, move_index):
        # Engine events also capture automatic mana payments, free casts and
        # land plays completed by a resolving choice, without announcing a
        # spell copy or a permanent merely put onto the battlefield.
        for event in events:
            frame = ANNOUNCED_EVENTS.get(event.type)
            if frame is None:
                continue
            action, name_key = frame
            actor_id = event.get("player_id") or event.get("controller_id")
            source = state.find_object(event.get("instance_id"))
            item = next((i for i in state.stack if event.get("stack_id") is not None
                         and i.stack_id == event.get("stack_id")), None)
            if item is not None:
                source = item.source
            if actor_id is None and source is not None:
                actor_id = source.controller_id
            if actor_id is None:
                continue
            actor = state.player_by_id(actor_id)
            name = event.get(name_key) or (getattr(source, "name", None) if source else None)
            self.append(kind="action", action=action, actor_id=actor.id, author=actor.name,
                        card_name=name, ability_text=item.description if item else None,
                        turn=state.turn_nr, move_index=move_index)

    def trim_moves(self, move_count):
        # Conversation survives undo; announcements of undone moves do not.
        self.messages = [m for m in self.messages
                         if m.get("move_index", 0) <= move_count]

    def clear(self):
        self.messages.clear()

    def view(self):
        return [dict(m) for m in self.messages]
