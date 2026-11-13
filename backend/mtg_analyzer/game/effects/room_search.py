"""Search for a Room sharing no name with an unlocked controlled Room door."""
from .core import GameEffect, _controller_of
from .library import SearchLibraryEffect
from .. import rooms


class SearchDifferentRoomNameEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        names = [name for obj in context.state.permanents_controlled_by(player.id)
                 if obj.has_subtype("Room") for name in
                 (rooms.unlocked_door_names(obj) if rooms.has_doors(obj.card) else [obj.name])]
        SearchLibraryEffect(criteria={"type": "Room", "not_names": names},
                            player=player, reveal=True, source=self.source).apply(context)
