"""Shared Oracle duration atoms; pure data at the parser boundary."""

import re

# RULE 611.2a: consumers retain their own effect construction, sharing the clock vocabulary.
FIXED_DURATIONS = {
    "until end of turn": "end_of_turn",
    "until your next upkeep": "your_next_upkeep",
    "until the beginning of your next upkeep": "your_next_upkeep",
    "until your next end step": "your_next_end_step",
    "until the beginning of your next end step": "your_next_end_step",
    "until your next turn": "your_next_turn",
    "until the end of your next turn": "end_of_your_next_turn",
    "until end of combat": "end_of_combat",
    "until the end of combat": "end_of_combat",
    "until the beginning of the next end step": "next_end_step",
}
FIXED_DURATION_PATTERN = "|".join(sorted(FIXED_DURATIONS, key=len, reverse=True))


_SOURCE = r'(?:~|this (?:creature|permanent|artifact|enchantment|equipment|aura|saga|vehicle))'
CONDITIONAL_DURATION_PATTERN = rf'(?:you control {_SOURCE}(?: and {_SOURCE} remains tapped)?|{_SOURCE} remains (?:tapped|on the battlefield|attached to (?:it|that creature))|(?:it|that [a-z]+) (?:has an? [a-z0-9+/\- ]+ counters? on it|is enchanted|remains tapped)|you(?: are|\x27re) the monarch|they(?: are|\x27re) the monarch)'

def condition_phrase(text):
    if re.fullmatch(rf'you control {_SOURCE} and {_SOURCE} remains tapped', text):
        return {'kind': 'all', 'conditions': [{'kind': 'source_controlled_by_you'}, {'kind': 'source_tapped'}]}
    if re.fullmatch(rf'you control {_SOURCE}', text):
        return {'kind': 'source_controlled_by_you'}
    if re.fullmatch(rf'{_SOURCE} remains on the battlefield', text):
        return {'kind': 'source_on_battlefield'}
    if re.fullmatch(rf'{_SOURCE} remains tapped', text):
        return {'kind': 'source_tapped'}
    if re.fullmatch(rf'{_SOURCE} remains attached to (?:it|that creature)', text):
        return {'kind': 'source_attached_to_affected'}
    counter = re.fullmatch(r'(?:it|that [a-z]+) has an? ([a-z0-9+/\- ]+) counters? on it', text)
    if counter:
        return {'kind': 'source_counters', 'of': 'affected', 'counter': counter[1], 'min': 1}
    if re.fullmatch(r'(?:it|that [a-z]+) is enchanted', text):
        return {'kind': 'source_enchanted', 'of': 'affected'}
    if re.fullmatch(r'(?:it|that [a-z]+) remains tapped', text):
        return {'kind': 'source_tapped', 'of': 'affected'}
    if text in ("you are the monarch", "you're the monarch"):
        return {'kind': 'is_monarch'}
    if text in ("they are the monarch", "they're the monarch"):
        return {'kind': 'captured_player_is_monarch'}
    return None
