"""Replacement-clause recognition (RULE 614/616) — a permanent's standing

"if X would Y, Z instead" sentence, docs/09's Phase 1 "static-shaped"
family. The binder side (`game/effects.py`'s `ReplacementRegistry`) has
long supported `prevent_damage`/`double_damage`/`additional_damage`/
`double_counters`/`double_tokens`; this module supplies the *recognition*
half for four of those five — the ones with a single, fixed real-card
phrasing (Doubling Season/Anointed Procession's token- and
counter-doubling lines, Torbran/Mechanized Warfare's "plus N damage" line,
and Furnace of Rath/Dictate of the Twin Gods/Gratuitous Violence/Fiery
Emancipation's damage-multiplying lines below). `prevent_damage`'s real
cards (Riot Control/Thought Lash) are a different, *one-shot spell effect*
shape ("Prevent all/the next N damage that would be dealt to you this
turn" grants a temporary shield, it isn't itself a standing permanent
ability) and aren't covered here.

RULE 616.1's full "if X would Y, Z instead" grammar has many more real
formulations (further target/duration variants) than the ones covered so
far — deliberately not attempted exhaustively here; see
`backend/ToDo_Backend.md` "Rules Engine" for the remaining open scope.

Pure regex + data — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import re
from typing import Optional

from ..spec import EffectSpec

#: Colour words → their WUBRG symbol (`additional_damage`'s single-colour filter).
_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

#: Doubling Season's/Anointed Procession's token-doubling line — identical
#: phrasing on every real card that prints it.
_DOUBLE_TOKENS_RE = re.compile(
    r"if an effect would create 1 or more tokens under your control, "
    r"it creates twice that many of those tokens instead",
    re.IGNORECASE,
)
#: Doubling Season's counter-doubling line ("a permanent you control" —
#: the real card's own wording; engine-side unscoped by ``kind``, but this
#: specific sentence is target-controller-scoped in its own text).
_DOUBLE_COUNTERS_RE = re.compile(
    r"if an effect would put 1 or more counters on a permanent you control, "
    r"it puts twice that many of those counters on that permanent instead",
    re.IGNORECASE,
)
#: Innkeeper's Talent's differently-scoped counter-doubling line: "if
#: **you** would put counters on a permanent or player" — a *causer*-scoped
#: sentence (whoever's effect places the counters), not Doubling Season's
#: *recipient*-scoped "on a permanent you control" — see
#: `_double_counters_replacement`'s ``your_effects_only`` docstring for the
#: distinction. Its "or player" half needs no special-casing here: the
#: engine's `EventType.COUNTER` handling is already recipient-agnostic
#: (`RulesEngine.add_player_counters` fires the same event shape for a
#: player recipient as `add_counters` does for a permanent).
_DOUBLE_COUNTERS_YOUR_EFFECTS_RE = re.compile(
    r"if you would put 1 or more counters on a permanent or player, "
    r"put twice that many of each of those kinds of counters on that "
    r"permanent or player instead",
    re.IGNORECASE,
)
#: Torbran, Thane of Red Fell's "plus N damage" line — one or two source
#: qualifiers joined by "or", each either a WUBRG colour word or a type word
#: (currently only "artifact" — Mechanized Warfare's "a red or artifact
#: source"; extend the word list as a real card needs another, mirroring
#: `_additional_damage_replacement`'s own "extend as needed" note).
_SOURCE_QUALIFIER_WORD = r"white|blue|black|red|green|artifact"
_ADDITIONAL_DAMAGE_RE = re.compile(
    rf"if a (?P<q1>{_SOURCE_QUALIFIER_WORD})(?: or (?P<q2>{_SOURCE_QUALIFIER_WORD}))? "
    r"source you control would deal damage to "
    r"an opponent or a permanent an opponent controls, it deals that much damage plus "
    r"(?P<n>\d+) instead",
    re.IGNORECASE,
)


#: Furnace of Rath/Dictate of the Twin Gods's unscoped damage-doubling line
#: ("a source" — no controller restriction at all).
_DOUBLE_DAMAGE_ANY_SOURCE_RE = re.compile(
    r"if a source would deal damage to a permanent or player, "
    r"it deals double that damage to that permanent or player instead",
    re.IGNORECASE,
)
#: Gratuitous Violence's own, narrower line: "a *creature* you control" —
#: no "combat" qualifier despite the card's own flavor, and note the tail
#: doesn't repeat "to that permanent or player" the way the two above do.
_DOUBLE_DAMAGE_YOUR_CREATURE_RE = re.compile(
    r"if a creature you control would deal damage to a permanent or player, "
    r"it deals double that damage instead",
    re.IGNORECASE,
)
#: Fiery Emancipation's "triple" sibling of the unscoped line above, scoped
#: to "a source *you control*" (any permanent, not creature-only).
_TRIPLE_DAMAGE_YOUR_SOURCE_RE = re.compile(
    r"if a source you control would deal damage to a permanent or player, "
    r"it deals triple that damage to that permanent or player instead",
    re.IGNORECASE,
)


#: Life-gain replacement, "if you would gain life, ... instead" (RULE
#: 119.3/616.1). Two real shapes: additive "that much life plus N" (Angel of
#: Vitality) and multiplicative "twice that much life" (Boon Reflection/
#: Alhammarret's Archive/Rhox Faithmender). Always self-scoped ("if **you**
#: would gain life") — every real card is a permanent whose controller is
#: the gaining player, so the engine's `_gain_life_replacement` reads the
#: `LIFE_GAIN` event's `player_id` against the effect's own controller.
_GAIN_LIFE_PLUS_RE = re.compile(
    r"if you would gain life, you gain that much life plus (?P<n>\d+) instead",
    re.IGNORECASE,
)
_GAIN_LIFE_DOUBLE_RE = re.compile(
    r"if you would gain life, you gain twice that much life instead",
    re.IGNORECASE,
)

#: "+1/+1 counters on a creature/permanent you control" replacement (RULE
#: 616.1) — the recipient-scoped counter family, distinct from Doubling
#: Season's unscoped `_DOUBLE_COUNTERS_RE` above. Additive "that many plus N"
#: (Hardened Scales/Conclave Mentor for a creature, Kami of Whispered Hopes
#: for any permanent) or multiplicative "twice that many" (Branching
#: Evolution/Corpsejack Menace). The recipient noun in the tail
#: ("it"/"that creature"/"that permanent") is along for the ride.
_COUNTERS_YOU_CONTROL_PLUS_RE = re.compile(
    r"if 1 or more \+1/\+1 counters would be put on a (?P<who>creature|permanent) you control, "
    r"that many plus (?P<n>\d+) \+1/\+1 counters are put on (?:it|that (?:creature|permanent)) instead",
    re.IGNORECASE,
)
_COUNTERS_YOU_CONTROL_DOUBLE_RE = re.compile(
    r"if 1 or more \+1/\+1 counters would be put on a (?P<who>creature|permanent) you control, "
    r"twice that many \+1/\+1 counters are put on (?:it|that (?:creature|permanent)) instead",
    re.IGNORECASE,
)

#: "If ~ would die, exile it instead" (RULE 616.1) — a creature's
#: battlefield→graveyard move redirected to exile. ``subject`` scopes it:
#: "this creature"/"~" (Gloomshrieker — self), "a creature you control", "a
#: creature an opponent controls" (Corpseweaver Prodigy), or a bare "a
#: creature" (any). The trailing referent ("it") is along for the ride.
_DIE_TO_EXILE_RE = re.compile(
    r"if (?P<subject>this creature|~|a creature you control|"
    r"a creature an opponent controls|a creature) would die, exile it instead",
    re.IGNORECASE,
)
_DIE_SUBJECT_MAP = {
    "this creature": "self",
    "~": "self",
    "a creature you control": "you_control",
    "a creature an opponent controls": "opponents_control",
    "a creature": "any",
}

#: The alternative-win-condition family (Jace, Wielder of Mysteries/
#: Laboratory Maniac-shaped, RULE 104.3a/120-adjacent) — "If you would draw
#: a card while your library has no cards in it, you win the game instead."
#: A recurring exact phrasing across several real cards (Elixir of
#: Immortality-adjacent effects use a different shape, not this one).
_WIN_INSTEAD_OF_EMPTY_DRAW_RE = re.compile(
    r"if you would draw a card while your library has no cards? in it, "
    r"you win the game instead",
    re.IGNORECASE,
)


def replacement_clause_specs(clause: str) -> Optional[list[EffectSpec]]:
    """`EffectSpec`s for a standing replacement-effect ``clause``, or ``None``.

    Full-matches the clause, mirroring `static_handlers.static_effect_specs`
    (its sibling in `segmenter.segment_line`'s permanent-only fallback) —
    a partial/differently-worded match stays unclaimed rather than guessed.
    """
    text = clause.strip().rstrip(".").strip()

    if _DOUBLE_TOKENS_RE.fullmatch(text):
        return [EffectSpec("double_tokens", {})]

    if _DOUBLE_COUNTERS_RE.fullmatch(text):
        return [EffectSpec("double_counters", {})]

    if _DOUBLE_COUNTERS_YOUR_EFFECTS_RE.fullmatch(text):
        return [EffectSpec("double_counters", {"your_effects_only": True})]

    m = _ADDITIONAL_DAMAGE_RE.fullmatch(text)
    if m is not None:
        quals = [m.group("q1")] + ([m.group("q2")] if m.group("q2") else [])
        colors = sorted({_COLOR_WORDS[q.lower()] for q in quals if q.lower() in _COLOR_WORDS})
        types = sorted({q.lower() for q in quals if q.lower() not in _COLOR_WORDS})
        params: dict = {
            "amount": int(m.group("n")), "your_sources_only": True, "to_opponent_only": True,
        }
        if len(colors) == 1 and not types:
            # The single-colour shape (Torbran) — kept as the pre-existing
            # ``color`` singular param for backward compatibility.
            params["color"] = colors[0]
        else:
            if colors:
                params["colors"] = colors
            if types:
                params["types"] = types
        return [EffectSpec("additional_damage", params)]

    if _WIN_INSTEAD_OF_EMPTY_DRAW_RE.fullmatch(text):
        return [EffectSpec("win_instead_of_empty_draw", {})]

    if _DOUBLE_DAMAGE_ANY_SOURCE_RE.fullmatch(text):
        return [EffectSpec("double_damage", {})]

    if _DOUBLE_DAMAGE_YOUR_CREATURE_RE.fullmatch(text):
        return [EffectSpec("double_damage", {"creature_only": True, "your_sources_only": True})]

    if _TRIPLE_DAMAGE_YOUR_SOURCE_RE.fullmatch(text):
        return [EffectSpec("double_damage", {"multiplier": 3, "your_sources_only": True})]

    m = _GAIN_LIFE_PLUS_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("gain_life_replacement", {"plus": int(m.group("n"))})]

    if _GAIN_LIFE_DOUBLE_RE.fullmatch(text):
        return [EffectSpec("gain_life_replacement", {})]  # multiplier defaults to 2

    m = _COUNTERS_YOU_CONTROL_PLUS_RE.fullmatch(text)
    if m is not None:
        recipient = "creature_you_control" if m.group("who") == "creature" else "permanent_you_control"
        return [EffectSpec("double_counters", {
            "kind": "+1/+1", "plus": int(m.group("n")), "recipient": recipient,
        })]

    m = _COUNTERS_YOU_CONTROL_DOUBLE_RE.fullmatch(text)
    if m is not None:
        recipient = "creature_you_control" if m.group("who") == "creature" else "permanent_you_control"
        return [EffectSpec("double_counters", {"kind": "+1/+1", "recipient": recipient})]

    m = _DIE_TO_EXILE_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("die_to_exile", {"subject": _DIE_SUBJECT_MAP[m.group("subject").lower()]})]

    return None
