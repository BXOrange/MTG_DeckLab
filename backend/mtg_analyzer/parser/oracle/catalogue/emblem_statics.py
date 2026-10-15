"""Shared permission/restriction sentences usable inside quoted emblems."""
import re
from ..spec import EffectSpec


def emblem_static_effect_specs(text):
    text = text.lower().strip().rstrip('.')
    if text == "you can cast nonland cards from your sideboard":
        return [EffectSpec("sideboard_cast_permission", {})]
    if text == ("if you would lose the game, instead your life total becomes 20, "
                "shuffle your graveyard into your library, you lose all poison counters, and you lose ~"):
        return [EffectSpec('recover_instead_of_losing', {})]
    if text == "your opponents can't cast noncreature spells":
        return [EffectSpec('cast_prohibition', {'scope':'opponents','noncreature':True})]
    if text == "you may activate loyalty abilities of planeswalkers you control on any player's turn any time you could cast an instant":
        return [EffectSpec('loyalty_instant_timing', {})]
    match = re.fullmatch(r"your opponents can't untap more than (?P<count>[0-9]+) permanents during their untap steps", text)
    if match:
        return [EffectSpec('untap_cap', {'count':int(match.group('count')),'card_type':'permanent','scope':'opponents'})]
    if text == "your opponents play with their hands revealed":
        return [EffectSpec('reveal_opponents_hands', {})]
    if text == "if you control a creature, damage that would reduce your life total to less than 1 reduces it to 1 instead":
        return [EffectSpec('creature_damage_life_floor', {})]
    if text == "you may play lands and cast permanent spells from your graveyard":
        return [EffectSpec('graveyard_cast_permission', {'permanent_only': True, 'once_per_turn': False, 'plays_lands': True})]
    if text == "creatures you control have trample and haste and get +2/+2 for each differently named dungeon you've completed":
        return [EffectSpec('grant_keyword', {'keywords': ['trample', 'haste'], 'affects': 'creatures_you_control'}),
                EffectSpec('anthem', {'power': 2, 'toughness': 2, 'affects': 'creatures_you_control',
                    'power_count': 'differently_named_completed_dungeons', 'toughness_count': 'differently_named_completed_dungeons'})]
    return None
