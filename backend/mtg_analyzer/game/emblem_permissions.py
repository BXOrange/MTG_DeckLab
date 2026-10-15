"""Command-zone permissions and player choices for restricted untap steps."""
from . import continuous
from .continuations import choice


def loyalty_instant_timing(state, player):
    # RULE 114.4 / 606.3: a command-zone emblem grants timing to its
    # controller; the planeswalker's once-per-turn limit is unaffected.
    return any(ability.layer == 'loyalty_instant_timing'
               and ability.source.controller_id == player.id
               for ability in continuous._battlefield_static_abilities(state))


def request_untap_selection(rules, player, caps):
    selected = getattr(rules.state, '_untap_cap_selected_ids', None)
    if selected is not None:
        return False
    if not any(cap.get('scope') == 'opponents' for cap in caps):
        return False
    candidates = [obj for obj in rules.state.permanents_controlled_by(player.id)
                  if obj.tapped and not obj.skip_next_untap
                  and not continuous.has_no_untap_static(rules.state, obj)]
    if not candidates:
        return False
    if all(sum(continuous.matches_untap_cap_filter(obj, cap) for obj in candidates) <= cap['count']
           for cap in caps):
        rules.state._untap_cap_selected_ids={obj.instance_id for obj in candidates}
        return False
    frame = {'kind':'untap_cap_selection','player_id':player.id,
             'candidate_ids':[obj.instance_id for obj in candidates],
             'selected_ids':[], 'caps':caps}
    _offer_untap_selection(rules, frame)
    return rules.state.pending_choice is not None


def _offer_untap_selection(rules, frame):
    state=rules.state
    picked=[state.find_object(i) for i in frame['selected_ids']]
    counts=[sum(continuous.matches_untap_cap_filter(obj,cap) for obj in picked if obj is not None)
            for cap in frame['caps']]
    available=[]
    for instance_id in frame['candidate_ids']:
        obj=state.find_object(instance_id)
        if obj is None or instance_id in frame['selected_ids']:continue
        if all(not continuous.matches_untap_cap_filter(obj,cap) or counts[i] < cap['count']
               for i,cap in enumerate(frame['caps'])):
            available.append(obj)
    if not available:
        state._untap_cap_selected_ids=set(frame['selected_ids'])
        return
    rules.open_choice(dict(frame,prompt='Wähle eine bleibende Karte zum Enttappen.',
                           options=[{'id':str(obj.instance_id),'label':obj.name} for obj in available],
                           optional=False))


@choice('untap_cap_selection',rule='502.3')
def resolve_untap_selection(rules, frame, answer):
    valid={option['id'] for option in frame['options']}
    if answer not in valid:
        # A mandatory selection cannot be silently replaced by the first
        # permanent. Restore the choice so the controlling player can answer.
        rules.open_choice(frame)
        raise ValueError('choose an offered permanent to untap')
    frame['selected_ids'].append(int(answer))
    _offer_untap_selection(rules, frame)


def publicly_revealed_hand_ids(state):
    """RULE 400.2: revealing a hand makes its cards visible to everyone."""
    controllers = {ability.source.controller_id
                   for ability in continuous._battlefield_static_abilities(state)
                   if ability.layer == 'reveal_opponents_hands'}
    return {player.id for player in state.players
            if any(controller != player.id for controller in controllers)}


def creature_damage_life_floor(state, player):
    """RULE 614.1a: the emblem's condition is checked at the damage event."""
    return any(ability.layer == 'creature_damage_life_floor'
               and ability.source.controller_id == player.id
               for ability in continuous._battlefield_static_abilities(state)) and any(
                   obj.is_creature for obj in state.permanents_controlled_by(player.id))
