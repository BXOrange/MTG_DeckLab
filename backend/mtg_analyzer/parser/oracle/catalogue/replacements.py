"""Replacement-clause recognition (RULE 614/616) — a permanent's standing

"if X would Y, Z instead" sentence, docs/09's Phase 1 "static-shaped"
family. The binder side (`game/effects.py`'s `ReplacementRegistry`) has
long supported `prevent_damage`/`double_damage`/`additional_damage`/
`double_counters`/`double_tokens`; this module supplies the *recognition*
half for all five — the ones with a single, fixed real-card
phrasing (Doubling Season/Anointed Procession's token- and
counter-doubling lines, Torbran/Mechanized Warfare's "plus N damage" line,
Furnace of Rath/Dictate of the Twin Gods/Gratuitous Violence/Fiery
Emancipation's damage-multiplying lines, and — MEC-30 — the Sphere cycle/
Urza's Armor/Shield of the Realm family's "if a `<source qualifier>` would
deal damage to `<recipient>`, prevent `<amount>` of that damage" line below).
`prevent_damage_shield`'s real cards (Riot Control/Thought Lash) are a
different, *one-shot spell effect* shape ("Prevent all/the next N damage
that would be dealt to you this turn" grants a temporary shield, it isn't
itself a standing permanent ability) and aren't covered here — nor is the
"a source **of your choice**" one-shot family (Circle of Protection/Rune of
Protection and ~25 siblings): a *choice* isn't a plain replacement clause,
and the family's real per-card variety (ETB-chosen colours/artists,
sacrifice costs, "if damage is prevented this way" riders) is hand-authored
in `game/ability_catalogue.py` instead (MEC-30's own documented choice,
not a gap — see that batch's `Done_Backend.md` entry).

RULE 616.1's full "if X would Y, Z instead" grammar has many more real
formulations (further target/duration variants) than the ones covered so
far — deliberately not attempted exhaustively here; see
`docs/implementation-state/BACKLOG.md` (PAR tickets) for the remaining open scope.

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


#: The damage-multiplying family (RULE 616.1) — Furnace of Rath/Dictate of
#: the Twin Gods's unscoped "a source" line, Gratuitous Violence's narrower
#: "a *creature* you control" line (no "combat" qualifier despite the
#: card's own flavor — note its tail doesn't repeat "to that permanent or
#: player" the way the other two do, hence the trailing phrase below is
#: optional rather than assumed present), and Fiery Emancipation's "triple"
#: sibling of the unscoped line, scoped to "a source *you control*" (any
#: permanent, not creature-only). One regex parameterized over
#: {scope, multiplier} rather than three near-identical literals.
_DAMAGE_MULTIPLIER_RE = re.compile(
    r"if a (?P<scope>source|creature you control|source you control) would deal damage to a "
    r"permanent or player, it deals (?P<mult>double|triple) that damage"
    r"(?P<tail> to that permanent or player)? instead",
    re.IGNORECASE,
)

#: The exact three (scope, multiplier, has-trailing-phrase) combinations the
#: three original literals covered — kept as an explicit whitelist rather
#: than accepting the regex's full cross product, since e.g. "a source you
#: control ... double ... to that permanent or player instead" (Angrath's
#: Marauders) is a real, un-modeled printed shape the original three
#: literals never happened to cover; recognizing it is real new coverage,
#: not a side effect of this refactor, so it's deliberately left out here.
_DAMAGE_MULTIPLIER_SHAPES: dict[tuple[str, str, bool], dict] = {
    ("source", "double", True): {},
    ("creature you control", "double", False): {"creature_only": True, "your_sources_only": True},
    ("source you control", "triple", True): {"your_sources_only": True, "multiplier": 3},
}


def _damage_multiplier_spec(m: re.Match[str]) -> Optional[EffectSpec]:
    key = (m.group("scope"), m.group("mult"), m.group("tail") is not None)
    params = _DAMAGE_MULTIPLIER_SHAPES.get(key)
    if params is None:
        return None
    return EffectSpec("double_damage", dict(params))


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
    r"a creature an opponent controls|"
    # MEC-49: "a creature/permanent dealt damage by ~ / enchanted creature
    # this turn" (Kumano, Master Yamabushi / Kumano's Blessing) — scoped by
    # damage history, checked against
    # `GameState.creatures_damaged_by_source_this_turn`.
    r"a (?:creature|permanent) dealt damage by (?:~|enchanted creature) this turn|"
    r"a creature) would die(?: this turn)?, exile (?:it|that creature|that permanent) instead",
    re.IGNORECASE,
)
_DIE_SUBJECT_MAP = {
    "this creature": "self",
    "~": "self",
    "a creature you control": "you_control",
    "a creature an opponent controls": "opponents_control",
    "a creature dealt damage by ~ this turn": "damaged_by_source_this_turn",
    "a permanent dealt damage by ~ this turn": "damaged_by_source_this_turn",
    "a creature dealt damage by enchanted creature this turn": "damaged_by_attached_this_turn",
    "a permanent dealt damage by enchanted creature this turn": "damaged_by_attached_this_turn",
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

#: MEC-30: the standing "if a `<source qualifier>` would deal damage to
#: `<recipient>`, prevent `<amount>` of that damage" family — the Sphere
#: cycle (Duty/Grace/Law/Purity/Reason/Truth), Urza's Armor/Orbs of
#: Warding/Protection of the Hekma/Heart-Shaped Herb/Guardian Seraph,
#: Daunting Defender/Djeru, With Eyes Open/Temple Altisaur, and Shield of
#: the Realm/Avatar. Two regexes (a literal ``\d+``/"all but N" amount, and
#: Shield of the Avatar's own "X … where X is the number of creatures you
#: control" count-selector amount) rather than one, since the trailing
#: "where X is …" clause changes the sentence shape rather than just one
#: word within it — the same "don't force one regex to swallow a
#: structurally different tail" call `_DAMAGE_MULTIPLIER_RE`'s own
#: ``tail`` group already makes.
_PREVENT_QUALIFIER_ALT = (
    r"a white source|a blue source|a black source|a red source|a green source|"
    r"an artifact|a creature|a source an opponent controls|a source"
)
#: The qualifier text (lower-cased) → `_prevent_damage_replacement`'s own
#: ``source_filter`` shape, or ``None`` for the unqualified "a source".
_PREVENT_QUALIFIER_MAP: dict[str, Optional[dict]] = {
    "a white source": {"color": "W"},
    "a blue source": {"color": "U"},
    "a black source": {"color": "B"},
    "a red source": {"color": "R"},
    "a green source": {"color": "G"},
    "an artifact": {"card_type": "artifact"},
    "a creature": {"is_creature": True},
    "a source an opponent controls": {"controller": "opponent"},
    "a source": None,
}
_PREVENT_RECIPIENT_ALT = (
    r"you|equipped creature|a planeswalker you control|"
    r"a \w+ creature you control|another \w+ you control"
)
_STANDING_PREVENT_RE = re.compile(
    rf"if (?P<qualifier>{_PREVENT_QUALIFIER_ALT}) would deal damage to "
    rf"(?P<recipient>{_PREVENT_RECIPIENT_ALT}), "
    r"prevent (?P<amount>\d+|all but \d+) of that damage",
    re.IGNORECASE,
)
_STANDING_PREVENT_COUNT_RE = re.compile(
    rf"if (?P<qualifier>{_PREVENT_QUALIFIER_ALT}) would deal damage to "
    rf"(?P<recipient>{_PREVENT_RECIPIENT_ALT}), "
    r"prevent x of that damage, where x is the number of creatures you control",
    re.IGNORECASE,
)


#: The Phantom cycle (Phantom Centaur / Phantom Flock / Phantom Nantuko /
#: Phantom Nishoba / Phantom Nomad / Phantom Tiger / Phantom Wurm): "If
#: damage would be dealt to ~, prevent that damage. Remove a +1/+1 counter
#: from ~." — a self-shield that pays one +1/+1 counter per damage event
#: rather than a numeric budget. `_prevent_damage_replacement`'s ``rider``
#: with the new ``remove_self_counter`` kind (`RulesEngine.
#: apply_prevent_rider`); these creatures are printed 0/0, so once the last
#: counter goes the RULE 704.5g SBA finishes them.
_PHANTOM_PREVENT_RE = re.compile(
    r"if damage would be dealt to ~, prevent that damage\.\s*"
    r"remove a (?P<counter>\+1/\+1|-1/-1) counter from ~\.?",
    re.IGNORECASE,
)


def _prevent_recipient_params(recipient: str) -> Optional[dict]:
    """``recipient`` (already lower-cased) → `_prevent_damage_replacement`'s
    own ``to``/``recipient_filter`` params, or ``None`` if unrecognized."""
    if recipient == "you":
        return {"to": "controller"}
    if recipient == "equipped creature":
        return {"to": "attached_permanent"}
    if recipient == "a planeswalker you control":
        return {"to": "controlled_permanent", "recipient_filter": {"card_type": "planeswalker"}}
    if recipient.startswith("a ") and recipient.endswith(" creature you control"):
        subtype = recipient[len("a "):-len(" creature you control")]
        return {"to": "controlled_permanent", "recipient_filter": {"subtype": subtype}}
    if recipient.startswith("another ") and recipient.endswith(" you control"):
        subtype = recipient[len("another "):-len(" you control")]
        return {
            "to": "controlled_permanent",
            "recipient_filter": {"subtype": subtype, "exclude_self": True},
        }
    return None


def _standing_prevent_spec(m: "re.Match[str]") -> Optional[EffectSpec]:
    qualifier = m.group("qualifier").lower()
    if qualifier not in _PREVENT_QUALIFIER_MAP:
        return None
    recipient_params = _prevent_recipient_params(m.group("recipient").lower())
    if recipient_params is None:
        return None
    params: dict = dict(recipient_params)
    source_filter = _PREVENT_QUALIFIER_MAP[qualifier]
    if source_filter is not None:
        params["source_filter"] = source_filter
    amount = m.group("amount").lower()
    if amount.startswith("all but "):
        params["amount"] = {"all_but": int(amount[len("all but "):])}
    else:
        params["amount"] = int(amount)
    return EffectSpec("prevent_damage", params)


def _standing_prevent_count_spec(m: "re.Match[str]") -> Optional[EffectSpec]:
    qualifier = m.group("qualifier").lower()
    if qualifier not in _PREVENT_QUALIFIER_MAP:
        return None
    recipient_params = _prevent_recipient_params(m.group("recipient").lower())
    if recipient_params is None:
        return None
    params: dict = dict(recipient_params)
    source_filter = _PREVENT_QUALIFIER_MAP[qualifier]
    if source_filter is not None:
        params["source_filter"] = source_filter
    params["amount_count_selector"] = "creatures_you_control"
    return EffectSpec("prevent_damage", params)


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

    m = _DAMAGE_MULTIPLIER_RE.fullmatch(text)
    if m is not None:
        spec = _damage_multiplier_spec(m)
        if spec is not None:
            return [spec]

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

    m = _PHANTOM_PREVENT_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("prevent_damage", {
            "to": "self",
            "amount": "all",
            "rider": {"kind": "remove_self_counter", "counter": m.group("counter"), "count": 1},
        })]

    m = _STANDING_PREVENT_COUNT_RE.fullmatch(text)
    if m is not None:
        spec = _standing_prevent_count_spec(m)
        if spec is not None:
            return [spec]

    m = _STANDING_PREVENT_RE.fullmatch(text)
    if m is not None:
        spec = _standing_prevent_spec(m)
        if spec is not None:
            return [spec]

    return None
