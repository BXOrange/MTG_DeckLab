"""Shared fixed Oracle duration atoms; pure data at the parser boundary."""

# RULE 611.2a: consumers retain their own effect construction, sharing the clock vocabulary.
FIXED_DURATIONS = {
    "until end of turn": "end_of_turn",
    "until your next turn": "your_next_turn",
    "until the end of your next turn": "end_of_your_next_turn",
    "until end of combat": "end_of_combat",
    "until the end of combat": "end_of_combat",
    "until the beginning of the next end step": "next_end_step",
}
FIXED_DURATION_PATTERN = "|".join(sorted(FIXED_DURATIONS, key=len, reverse=True))
