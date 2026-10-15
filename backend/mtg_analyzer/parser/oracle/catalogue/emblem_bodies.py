"""Composed emblem trigger bodies using ordinary engine primitives."""
from __future__ import annotations
import re
from ..spec import AbilitySpec, EffectSpec


def emblem_body_spec(inner: str):
    text=inner.strip().rstrip('.')
    haunted = re.fullmatch(
        r'at the beginning of your upkeep, (?:~ deals (?P<n>\d+) damage to the owner of target haunted creature|'
        r'(?P<control>gain control of target haunted creature for as long as it remains haunted))', text)
    if haunted:
        kind = 'control_while_haunted' if haunted.group('control') else 'haunted_owner_damage'
        return AbilitySpec('triggered', [EffectSpec(kind, {
            'amount': int(haunted.group('n') or 0),
        })], trigger={'event': 'STEP_BEGIN', 'filter': {'step': 'upkeep'},
                     'phase_relation': 'you'})
    loss_floor = re.fullmatch(
        r'whenever an opponent is dealt combat damage by 1 or more creatures you control, '
        r'if that player lost less than (?P<n>\d+) life this turn, they lose life equal to the difference', text)
    if loss_floor:
        threshold = int(loss_floor.group('n'))
        return AbilitySpec('triggered', [EffectSpec('complete_turn_life_loss', {'threshold': threshold})],
                           trigger={'event': 'CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER',
                                    'condition': {'subject': 'group', 'controller': 'you',
                                                  'recipient_is_opponent': True},
                                    'contributors': {'min': 1},
                                    'recipient_life_lost_less_than': threshold})
    if text == ('at the beginning of your upkeep, you may cast a legendary spell '
                'from your hand, from your graveyard, or from among cards you own in exile '
                'without paying its mana cost'):
        return AbilitySpec('triggered', [EffectSpec('free_cast_from_hand', {
            'zones': ['hand', 'graveyard', 'exile'], 'legendary_only': True,
            'during_resolution': True,
        })], trigger={'event': 'STEP_BEGIN', 'filter': {'step': 'upkeep'},
                     'phase_relation': 'you'})
    # RULE 603.2: the upkeep event identifies whose mandatory choice it is.
    sacrifice = re.fullmatch(
        r"at the beginning of each opponent's upkeep, that player sacrifices "
        r"an? (?P<what>creature|artifact|enchantment|land|permanent) of their choice", text)
    if sacrifice:
        return AbilitySpec('triggered', [EffectSpec('choose_objects', {
            'action': 'sacrifice', 'what': sacrifice.group('what'),
            'player_selector': 'active_player',
        })], trigger={'event': 'STEP_BEGIN', 'filter': {'step': 'upkeep'},
                     'phase_relation': 'not_you'})
    payment = re.fullmatch(
        r"at the beginning of your upkeep, pay (?P<cost>(?:\{[wubrgc0-9]+\})+)\. "
        r"if you don't, you lose the game", text)
    if payment:
        return AbilitySpec('triggered', [EffectSpec('pay_cost_then', {
            'cost': payment.group('cost'), 'effects': [],
            'else_effects': [{'type': 'lose_game', 'params': {}}],
        })], trigger={'event': 'STEP_BEGIN', 'filter': {'step': 'upkeep'},
                     'phase_relation': 'you'})
    if text == 'whenever you cast a spell that targets 1 or more permanents, gain control of those permanents':
        return AbilitySpec('triggered',[EffectSpec('gain_control_of_cast_targets',{})],
                           trigger={'event':'SPELL_CAST','condition':{'subject':'you'},
                                    'requires_spell_targets_permanent':True})
    if text == "whenever you activate an ability that isn't a mana ability, copy it. you may choose new targets for the copy":
        return AbilitySpec('triggered',[EffectSpec('copy_ability',{'ability_from_trigger_event':'stack_id','choose_new_targets':True})],
                           trigger={'event':'ACTIVATED_ABILITY','condition':{'subject':'group','controller':'you'}})
    if text == 'whenever an artifact is put into your graveyard from the battlefield, return that card to the battlefield at the beginning of the next end step':
        return AbilitySpec('triggered',[EffectSpec('delay_return_dying_subject',{})],
                           trigger={'event':'DIES','condition':{'subject':'group','type':'artifact','owner':'you'}})
    if text == 'at the end of the first combat phase on your turn, untap target creature you control. after this phase, there is an additional combat phase':
        return AbilitySpec('triggered',[
            EffectSpec('tap',{'target_kind':'creature_you_control','untap':True}),
            EffectSpec('extra_combat_phase',{'after_current_phase':True})],
            trigger={'event':'STEP_BEGIN','filter':{'step':'end_combat'},'during_your_turn':True,
                     'active_if':{'kind':'combats_this_turn','min':1,'max':1}})
    return None
