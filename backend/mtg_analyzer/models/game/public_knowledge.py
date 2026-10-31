"""Public card observations, independent of permissions to look at hidden zones."""
from .events import EventType
from .game_object import Zone


class PublicCardKnowledge:
    """Cloneable knowledge of exact zone visits; never serialized as hidden IDs."""

    def __init__(self):
        self.cards = {}
        self.libraries = {}

    def sync(self, state, *, final=False):
        locations = {obj.instance_id: (player.id, obj) for player in state.players
                     for zone in (Zone.HAND, Zone.LIBRARY) for obj in player.zones[zone]}
        removed_safely = set()
        invalid_libraries = set()
        for player in state.players:
            order = tuple((obj.instance_id, obj.zone_incarnation) for obj in player.library)
            serial = player.library_shuffle_serial
            old_order, old_serial = self.libraries.get(player.id, (order, serial))
            # Only order-preserving removals are trackable; insertion/reordering
            # may hide which formerly revealed card occupies which position.
            remaining = set(order)
            if serial != old_serial or tuple(v for v in old_order if v in remaining) != order:
                invalid_libraries.add(player.id)
            else:
                removed_safely.update(v for v in old_order if v not in remaining)
            self.libraries[player.id] = (order, serial)
        for iid, record in list(self.cards.items()):
            location = locations.get(iid)
            if (iid, record['visit']) in removed_safely:
                record['removed_safely'] = True
            if location is None:
                # Search/reveal-until batches briefly hold cards outside zone lists.
                # Retain those references only until the next public view boundary.
                if not final and record['object'].zone == record['zone'] and record['owner'] not in invalid_libraries:
                    continue
                del self.cards[iid]
                continue
            if location[0] != record['owner']:
                del self.cards[iid]
                continue
            owner, obj = location
            if record['zone'] == Zone.LIBRARY and owner in invalid_libraries:
                # A revealed find moved to hand before the shuffle remains known.
                # The primitive shuffle serial is advanced only after the move;
                # sync at every public event normally already recorded that move.
                del self.cards[iid]
                continue
            if obj.zone == record['zone'] and obj.zone_incarnation == record['visit']:
                continue
            if (record['zone'] == Zone.LIBRARY and obj.zone == Zone.HAND
                    and obj.zone_incarnation == record['visit'] + 1
                    and record.get('removed_safely')):
                record.update(zone=Zone.HAND, visit=obj.zone_incarnation)
            else:
                del self.cards[iid]

    def forget_library_order(self, player_id, instance_ids):
        # RULE 701.20d: a private ordering choice ends knowledge of the
        # inspected cards even when the chosen order happens to be unchanged.
        for iid in instance_ids:
            record = self.cards.get(iid)
            if record and record['owner'] == player_id and record['zone'] == Zone.LIBRARY:
                del self.cards[iid]

    def observe(self, state, event):
        if not self.cards and event.type != EventType.REVEAL:
            return
        self.sync(state)
        if event.type == EventType.SHUFFLE:
            player_id = event.get('player_id')
            for iid, record in list(self.cards.items()):
                if record['zone'] == Zone.LIBRARY and (player_id is None or record['owner'] == player_id):
                    del self.cards[iid]
            return
        if event.type != EventType.REVEAL:
            return
        obj = state.find_object(event.get('instance_id'))
        if obj is None:
            return
        # RULE 701.20a: capture the publicly shown face *at reveal time*, before
        # it can change zones or disappear. The feed must not look it up later.
        event.data.update(card_id=obj.card.id, object=obj.name, revealed_card=self.face_snapshot(obj))
        if obj.zone not in (Zone.HAND, Zone.LIBRARY):
            return
        owner = next((p for p in state.players if obj in p.zones[obj.zone]), None)
        if owner is not None:
            self.cards[obj.instance_id] = {'owner': owner.id, 'zone': obj.zone,
                                           'visit': obj.zone_incarnation, 'object': obj}

    @staticmethod
    def face_snapshot(obj):
        fields = {'instance_id', 'card_id', 'name', 'zone', 'owner_id', 'controller_id',
                  'power', 'toughness', 'transformed', 'has_back_face', 'flipped', 'is_token'}
        return {key: value for key, value in obj.to_dict().items() if key in fields}

    def view(self, state):
        if not self.cards:
            return []
        self.sync(state, final=True)
        result = []
        for player in state.players:
            for zone in (Zone.HAND, Zone.LIBRARY):
                for index, obj in enumerate(player.zones[zone]):
                    if obj.instance_id not in self.cards:
                        continue
                    card = obj.to_dict()
                    if zone == Zone.LIBRARY:
                        card['library_position'] = len(player.library) - index
                    result.append(card)
        return result
