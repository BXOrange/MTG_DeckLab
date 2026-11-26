"""RULE 106.6: effects attached to individual produced mana units.

Descriptors are engine data, never executable Oracle text. Delayed cast riders
are independent of the mana remaining in the pool (RULE 603.7).
"""
from __future__ import annotations

from ..models.game.game_object import Zone
from ..models.game.events import EventType, GameEvent
from . import continuous
from .effects.core import GameEffect, StaticAbility, TriggeredAbility


def build_rider(rider, source):
    return dict(rider, source_id=source.instance_id,
                source_incarnation=source.zone_incarnation,
                controller_id=source.controller_id)


def arm_next_cast_rider(state, source, rider):
    pending = getattr(state, 'mana_next_cast_riders', [])
    pending.append(dict(build_rider(rider, source), turn=state.internal_turn.number, triggered=True))
    state.mana_next_cast_riders = pending


def matches(rider, spell, state=None):
    return (not rider.get('creature') or spell.is_creature) and (
        not rider.get('artifact') or 'artifact' in spell.type_words) and (
        not rider.get('subtype') or continuous.has_subtype(spell, rider['subtype'])) and (
        not rider.get('exclude_subtype') or not continuous.has_subtype(spell, rider['exclude_subtype'])) and (
        not rider.get('multicolored') or len(spell.colors) > 1) and (
        not rider.get('commander') or (spell.is_commander and spell.owner_id == rider['controller_id'])) and (
        not rider.get('legendary') or spell.is_legendary) and (
        # MEC-175: "a spell with mana value N or greater" (Gilanra) / "a spell with {X} in its mana cost" (Brass
        # Infiniscope, RULE 107.3).
        spell.mana_value >= rider.get('min_mana_value', 0)) and (
        not rider.get('has_x') or '{X}' in (getattr(spell.card, 'mana_cost_string', '') or '').upper()) and (
        not rider.get('shares_type_with_commander') or shares_type_with_commander(state, spell, rider['controller_id']))


def shares_type_with_commander(state, spell, controller_id):
    """MEC-175: "a creature spell that shares a creature type with your commander" (Path of Ancestry) -- some
    commander the payer owns (any zone, RULE 903.3) has a creature type in common with the spell (RULE 205.3m)."""
    if state is None:
        return False
    spell_types = continuous.derived_subtype_words(spell)
    commanders = [obj for zone_objects in state.player_by_id(controller_id).zones.values() for obj in zone_objects]
    commanders += [obj for obj in state.battlefield if obj.owner_id == controller_id]
    return any(
        getattr(obj, 'is_commander', False) and obj.owner_id == controller_id
        and spell_types & continuous.derived_subtype_words(obj)
        for obj in commanders
    )


def mark_entry(spell, rider, count):
    marks = getattr(spell, 'mana_rider_entry_marks', [])
    marks.append(dict(rider, count=count, spell_incarnation=spell.zone_incarnation))
    spell.mana_rider_entry_marks = marks


class ManaRiderEffect(GameEffect):
    def __init__(self, rider, spell, source=None):
        super().__init__(source)
        self.rider = dict(rider)
        self.spell_id = spell.instance_id
        self.spell_incarnation = spell.zone_incarnation

    def apply(self, context, targets=None):
        rider = self.rider
        count = int(rider.get('count', 1))
        if rider['kind'] == 'source_counters':
            source = context.state.find_object(rider['source_id'])
            if (source is not None and source.zone == Zone.BATTLEFIELD
                    and source.zone_incarnation == rider['source_incarnation']):
                context.add_counters(source, count, rider.get('counter', '+1/+1'), source=self.source)
            return
        if rider['kind'] in PLAYER_PAYOFF_KINDS:
            # MEC-175 (RULE 106.6 / 603.7): the payoff goes to the player who spent the mana, whether or not the cast
            # spell is still on the stack when the triggered ability resolves.
            self._apply_player_payoff(context, count)
            return
        spell = context.state.find_object(self.spell_id)
        if (spell is None or spell.zone != Zone.STACK
                or spell.zone_incarnation != self.spell_incarnation):
            return
        if rider['kind'] == 'sunburst':
            spell.gains_sunburst = True
        else:
            mark_entry(spell, rider, count)
            if rider.get("keyword"):
                grant_entry_keyword(context.state, spell, rider)


    def _apply_player_payoff(self, context, count):
        rider = self.rider
        player = context.state.player_by_id(rider['controller_id'])
        if rider['kind'] == 'life':
            context.gain_life(player, count)
        elif rider['kind'] == 'scry':
            context.scry(player, count, source=self.source)
        else:  # draw / draw_gain_half_x
            context.draw(player, 1)
            if rider['kind'] == 'draw_gain_half_x':
                context.gain_life(player, count)


#: RULE 107.3f: "half X, rounded down".
HALF_X_DIVISOR = 2
#: MEC-175: payoff kinds that act on the paying player, not on the cast spell.
PLAYER_PAYOFF_KINDS = frozenset({'life', 'scry', 'draw', 'draw_gain_half_x'})


def apply_cast_riders(rules, item, event):
    """Finish RULE 601.2i: apply replacement riders and queue delayed triggers."""
    spell = item.obj
    riders = list(getattr(item, 'mana_payment_riders', []))
    item.mana_payment_riders = []
    pending = []
    for rider in getattr(rules.state, 'mana_next_cast_riders', []):
        if rider['turn'] != rules.state.internal_turn.number:
            continue
        if rider['controller_id'] == item.controller_id and matches(rider, spell, rules.state):
            riders.append(rider)
        else:
            pending.append(rider)
    rules.state.mana_next_cast_riders = pending
    for rider in riders:
        if not matches(rider, spell, rules.state):
            continue
        source = rules.state.find_object(rider['source_id'])
        if rider['kind'] == 'draw_gain_half_x':
            rider = dict(rider, count=item.x // HALF_X_DIVISOR)  # RULE 107.3: the announced X, halved, rounded down
        elif rider.get('triggered') and rider.get('count') == 'commander_casts':
            rider = dict(rider, count=item.mana_rider_commander_cast_count)
        if rider['kind'] == 'grant_keyword':
            grant_entry_keyword(rules.state, spell, rider)  # RULE 611.2a: applied as the spell is cast
        elif rider.get('triggered'):
            effect = ManaRiderEffect(rider, spell, source)
            ability = TriggeredAbility(EventType.SPELL_CAST, [effect],
                                       controller_id=rider['controller_id'], source=source,
                                       description='Mana spend rider')
            # RULE 603.7: delayed abilities still trigger after their source
            # leaves; use the ordinary trigger queue for ordering and responses.
            captured = GameEvent(EventType.SPELL_CAST, **dict(event.data))
            captured.data['source_zone_incarnation'] = rider['source_incarnation']
            rules.pending_triggers.append((ability, captured))
        elif rider['kind'] == 'player_counters':
            player = rules.state.player_by_id(rider['controller_id'])
            rules.add_player_counters(player, int(rider.get('count', 1)),
                                      rider.get('counter', 'experience'), source=source)
        else:
            count = rider.get('count', 1)
            if count == 'commander_casts':
                count = item.mana_rider_commander_cast_count
            mark_entry(spell, rider, int(count))


def grant_entry_keyword(state, spell, rider):
    # RULE 611.2b / 400.7c: the resolving delayed trigger grants a duration
    # now; its effect follows only this spell's ensuing permanent incarnation.
    until_next_turn = rider.get('duration', 'until_next_turn') == 'until_next_turn'
    static = StaticAbility('ability', affects='objects',
                           params={'keywords': [rider['keyword']],
                                   'object_ids': [spell.instance_id],
                                   'object_incarnations': {spell.instance_id: spell.zone_incarnation + 1}},
                           duration='your_next_turn' if until_next_turn else rider['duration'],
                           duration_data={'player_id': rider['controller_id'],
                                          'turn': state.internal_turn.number} if until_next_turn else {})
    static.timestamp = state.next_timestamp()
    state.floating_statics.append(static)


def apply_entry_riders(rules, spell):
    marks = getattr(spell, 'mana_rider_entry_marks', [])
    spell.mana_rider_entry_marks = []
    for mark in marks:
        # RULE 400.7c: spell effects follow only that stack-to-battlefield
        # transition; a countered card reanimated later is a new object.
        if spell.zone_incarnation != mark['spell_incarnation']:
            continue
        kind = mark.get('counter', '+1/+1')
        spell.entry_bonus_counters[kind] = spell.entry_bonus_counters.get(kind, 0) + mark['count']
