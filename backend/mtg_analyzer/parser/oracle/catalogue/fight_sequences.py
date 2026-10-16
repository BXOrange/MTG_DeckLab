"""Counter/pump before fighting, with one announcement for each real target.

The conditional instruction changes only the friendly fighter; it never gates
fighting or the opposing target requirement.
"""
from __future__ import annotations

import re
from ..spec import EffectSpec
from .subgrammars import resolve_target_kind

_ENEMY = r"creature (?:you don't control|an opponent controls)"
_PAIR = re.compile(rf"choose target creature you control and target (?P<enemy>{_ENEMY})\. (?P<buff>.+?)\. then (?:the chosen creatures|those creatures) fight each other\.?")
_SINGLE = re.compile(rf"(?P<buff>.+?)\. (?:then )?(?:it|that creature)(?P<extra> gets \+1/\+1 until end of turn and)? fights target (?P<enemy>(?:green )?{_ENEMY})\.?")


def _pump(power, toughness, condition=None, **params):
    return EffectSpec('pump', {'power': power, 'toughness': toughness, **params}, condition=condition)


def _condition(text):
    conditions = {
        "you control 3 or more snow permanents": {'kind':'control_count','selector':{'zone':'battlefield','of':'you','filter':{'snow':True}},'min':3},
        "you control 3 or more creatures with different powers": {'kind':'control_count','selector':{'zone':'battlefield','of':'you','filter':{'type':'creature'},'distinct':'power'},'min':3},
        "the creature you control entered this turn": {'kind':'entered_this_turn','of':'previous_target'},
        "you cast this spell during your main phase": {'cast_during_your_main_phase':True},
        "it has power 4 or greater": {'kind':'power','of':'previous_target','min':4},
        "its power is 4 or greater": {'kind':'power','of':'target','min':4},
        "its power is 2": {'kind':'power','of':'target','min':2,'max':2},
        "it's a knight": {'kind':'is_subtype','of':'previous_target','subtype':'knight'},
        "it's legendary": {'kind':'is_legendary','of':'target'},
        "it's a host or has augment": {'kind':'any','conditions':[{'kind':'is_supertype','of':'target','card_type':'host'},{'kind':'has_printed_keyword','of':'target','keyword':'augment'},{'kind':'has_keyword','of':'target','keyword':'augment'}]},
    }
    power = re.fullmatch(r"you control a creature with power (\d+) or greater",text)
    if power:
        return {"kind":"control_count","selector":"creatures_you_control","min_power":int(power[1]),"min":1}
    return conditions.get(text)


def fight_sequence_specs(clause):
    """Closed atomic buff grammar inside a shared two-fighter sequence."""
    block = re.fullmatch(r"creatures with power (\d+) or less can\'t block this turn\.?",clause)
    if block:
        return [EffectSpec("cant_block_this_turn",{"selector":"all_creatures","filter":{"max_power":int(block[1])}})]
    rhino = re.fullmatch(r"(?P<base>.+?\. it fights target creature an opponent controls\.) when excess damage is dealt to the creature an opponent controls this way, destroy up to 1 target noncreature artifact with mana value 3 or less\.?",clause)
    if rhino:
        base = fight_sequence_specs(rhino['base'])
        if base is None:
            return None
        fight = base[-1]
        return [*base[:-1],EffectSpec('fight',{**fight.params,'excess_then_trigger':[{'type':'destroy','params':{'target_kind':'artifact','optional':True,'creature_filter':{'without_type':['creature'],'max_mana_value':3}}}]})]
    throne = re.fullmatch(r"(?P<base>.+?\. then it fights target creature an opponent controls\.) when the creature an opponent controls dies this turn, if you control your commander, you become the monarch\.?",clause)
    if throne:
        base = fight_sequence_specs(throne['base'])
        if base is None:
            return None
        commander = {'kind':'controls_own_commander'}
        return [*base,EffectSpec('create_turn_trigger',{'previous_subject':True,'once':True,'trigger':{'event':'DIES','condition':{'subject':'self'},'active_if':commander},'effects':[{'type':'become_monarch','params':{},'condition':commander}]})]
    pair = _PAIR.fullmatch(clause)
    single = _SINGLE.fullmatch(clause) if pair is None else None
    m = pair or single
    if m is None:
        return None
    enemy = resolve_target_kind('target '+m['enemy'])
    if enemy is None:
        return None
    buff = m['buff']
    condition = None
    prefix = re.fullmatch(r'if (.+?), (.+)', buff)
    if prefix:
        condition = _condition(prefix[1])
        if condition is None:
            return None
        buff = prefix[2]
    suffix = re.fullmatch(r"(.+?) if (.+)", buff)
    if suffix:
        condition = _condition(suffix[2])
        if condition is None:
            return None
        buff = suffix[1]
    specs = []
    if pair:
        specs.append(EffectSpec('choose_targets', {'kinds':['creature_you_control',enemy]}))
        buff = buff.replace('the chosen creature you control','the creature you control')
        counter = re.fullmatch(r'put a \+1/\+1 counter on (?:the creature you control|it)',buff)
        pump = re.fullmatch(r'the creature you control gets \+(\d+)/\+(\d+)( and gains indestructible)? until end of turn',buff)
        if counter:
            specs.append(EffectSpec('add_counters', {'count':1,'kind':'+1/+1','previous_subject':True},condition=condition))
        elif pump:
            specs.append(_pump(int(pump[1]),int(pump[2]),condition,target_operand={'of':'previous_target'},keywords=['indestructible'] if pump[3] else []))
        else:
            return None
        specs.append(EffectSpec('fight',{'fighter_kind':'previous_target','other_kind':'previous_target_2'}))
    else:
        counter = re.fullmatch(r'put a \+1/\+1 counter on target creature you control',buff)
        pump = re.fullmatch(r'target (?P<green>green )?creature you control gets \+(\d+)/\+(\d+)(?P<duration> until end of turn)?',buff)
        if counter:
            specs.append(EffectSpec('add_counters',{'count':1,'kind':'+1/+1','target_kind':'creature_you_control'},condition=condition))
        elif pump:
            friendly = resolve_target_kind('target '+('green ' if pump['green'] else '')+'creature you control')
            if pump['duration']:
                specs.append(_pump(int(pump[2]),int(pump[3]),condition,target_kind=friendly))
            else:
                # RULE 611.2a: an omitted duration lasts indefinitely, not until cleanup.
                specs.append(EffectSpec('grant_until',{'duration':'rest_of_game','target_kind':friendly,'static':{'type':'anthem','params':{'power':int(pump[2]),'toughness':int(pump[3])}}},condition=condition))
        else:
            return None
        if single['extra']:
            specs.append(_pump(1,1,target_operand={'of':'previous_target'}))
        specs.append(EffectSpec('fight',{'fighter_kind':'previous_target','other_kind':enemy}))
    return specs


def reordered_fight_text(text):
    """A printed before-fighting rider modifies the earlier instruction (608.2c)."""
    return re.sub(
        rf"target creature you control fights target (?P<enemy>{_ENEMY})\.\s+"
        r"the creature you control gets (?P<pt>\+\d+/\+\d+) until end of turn before it fights "
        r"if you control a creature with power (?P<n>\d+) or greater\.?",
        lambda m: f"choose target creature you control and target {m['enemy']}. "
                  f"if you control a creature with power {m['n']} or greater, "
                  f"the creature you control gets {m['pt']} until end of turn. then those creatures fight each other.",
        text,
    )


def source_counter_fight_specs(clause):
    """Source counters followed by a separately announced optional fight."""
    if clause.rstrip('.') == "choose up to 1 target creature you don't control with flying. ~ gets +x/+0 until end of turn, where x is the number of creature cards in your graveyard, then you may have ~ fight that creature":
        return [EffectSpec('choose_targets',{'kinds':['creature_you_dont_control'],'optional':True,'creature_filter':{'keyword':'flying'}}),EffectSpec('pump',{'dynamic_amount':{'kind':'count_selector','selector':'creature_cards_in_your_graveyard'},'amount_from_count_selector_axis':'power'}),EffectSpec('optional',{'effects':[{'type':'fight','params':{'other_kind':'previous_target'}}]})]
    m = re.fullmatch(r"put a \+1/\+1 counter on ~,? (?:then )?(?:it|~) fights up to 1 target (?P<enemy>creature (?:defending player controls|you don't control))\.?",clause)
    if m:
        return [EffectSpec('add_counters',{'count':1,'kind':'+1/+1'}),EffectSpec('fight',{'other_kind':'creature_defending_player_controls' if 'defending' in m['enemy'] else 'creature_you_dont_control','optional':True})]
    m = re.fullmatch(r"put a \+1/\+1 counter on ~\. when this ability resolves for the third time this turn, ~ fights up to 1 target creature you don't control\.?",clause)
    if m:
        return [EffectSpec('add_counters',{'count':1,'kind':'+1/+1'}),EffectSpec('reflexive_trigger',{'then_trigger':[{'type':'fight','params':{'other_kind':'creature_you_dont_control','optional':True}}]},condition={'kind':'ability_resolution_count','min':3,'max':3})]
    return None
