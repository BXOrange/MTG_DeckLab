"""RULE 702.125 cost reductions and paired next-spell grants."""
from ..models.cards.card_query import matches


def _matches(entry, state, player_id, card):
    if entry['player_id'] != player_id or entry['turn'] != state.internal_turn.number:
        return set()
    slots = set()
    if entry.get('artifact_creature') and card.is_artifact and card.is_creature:
        slots.add('artifact_creature')
    if entry.get('spacecraft') and matches(card, {'type': 'Spacecraft'}):
        slots.add('spacecraft')
    return slots


def reduction(state, player_id, obj, card=None):
    from . import combat
    card = card or obj.card
    instances = combat.keyword_instances(obj, 'undaunted')
    # One resolving effect grants one instance even when the same spell
    # occupies both next-spell slots. Independent effects stack (702.125c).
    instances += sum(bool(_matches(entry, state, player_id, card))
                     for entry in state.next_undaunted_grants)
    opponents = sum(player.id != player_id for player in state.living_players())
    return instances * opponents


def consume(state, player_id, obj):
    for entry in state.next_undaunted_grants:
        for slot in _matches(entry, state, player_id, obj.card):
            entry[slot] = False
    state.next_undaunted_grants = [entry for entry in state.next_undaunted_grants
                                 if entry.get('artifact_creature') or entry.get('spacecraft')]
