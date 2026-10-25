"""Library search, gain-control, flashback, attach, phase and extra-turn rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import re

from ..clause_reading import ClauseReading
from typing import Any, Optional
from ..characteristic_phrase import PERMANENT_CARD_TYPES
from ..clause_primitives import split_keywords_with_parametric
from ..subgrammars import (
    SPELL_TARGET,
    resolve_spell_filter,
    resolve_color_word,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    TARGET,
    target_is_optional,
    target_kind_allowed,
    target_macro,
    target_quality_filter,
)
from ..subtype_vocabulary import SUBTYPES
from ...normalize import SELF
from ...spec import EffectSpec
from .shared import (
    ANY_NUMBER_TARGET_CAP,
    ATTACHED_SUBJECT,
    CAST_WINDOW_COLORS,
    compile_clause,
    EffectHandler,
    except_by_restriction,
    fight_kind,
    GRAVEYARD_SCOPE_WORD,
    graveyard_target_kind,
    GRAVEYARD_TYPE_WORD,
    mass_group_params,
    MULTI_TARGET_ALT,
    multi_target_params,
    MULTI_TARGET_QUANTIFIER,
    optional_param,
    PREVIOUS_SUBJECT,
    renamed_target_count,
    SELF_SUBJECT,
    subject_handlers,
    TARGET_B,
    THEN,
    token_keywords,
)


#: "search your library for a [<criteria>] card, [reveal it,] put it/that
#: card/them/those cards <destination>, then shuffle." (RULE 701.19, the
#: general tutor/ramp/fetch family — Demonic Tutor/Rampant Growth/Farseek/
#: Nature's Lore/Crop Rotation/Eladamri's Call/Buried Alive/Sylvan
#: Scrying-shaped) and its reordered sibling "..., [reveal it,] then shuffle
#: and put it/that card/the card on top." (Vampiric/Mystical/Enlightened/
#: Worldly Tutor-shaped). Both map onto the engine's existing `"search"`
#: `EffectSpec` (`game/effects/core.py`'s `SearchLibraryEffect`, already
#: parameterized on criteria/destination/count — `tests/
#: test_search_popular_tutors.py` proves it against 15 real popular tutors)
#: — no new effect type needed, just recognition. Three siblings below
#: extend the same `"search"` `EffectSpec` onto its ``zones``/
#: ``destinations``/``exile_rest`` params (`RulesEngine._request_search`):
#: "library and/or graveyard" combined search (`_search_zone_put`, ~50 real
#: cards — the backgrounds/planeswalker-tutor family), a split destination
#: per found card (`_search_split_destination` — Cultivate/Kodama's Reach),
#: and "search for N cards and exile the rest" (`_search_exile_rest` —
#: Doomsday). Deliberately still NOT attempted here (fail-closed, real cards
#: found but left unclaimed): any qualifier after the noun phrase such as
#: "with mana value X or less" (Green Sun's Zenith/Chord of Calling/Finale
#: of Devastation — X is a spell's own cast-time choice, not a static
#: criterion this grammar can express), a name criterion whose own name
#: contains a comma ("a card named Angrath, Minotaur Pirate" —
#: indistinguishable from the following put-clause's own comma without a
#: name dictionary), and a searched-for subtype not in `_SEARCH_TYPE_WORD`'s
#: vocabulary ("a Shrine card"/"an Ally creature card").
#:
#: The type-word vocabulary intentionally also carries the five basic land
#: names (a card can be searched for by name, "a Forest card"/"a Plains,
#: Island, Swamp, or Mountain card" — Nature's Lore/Farseek), separate from
#: "basic land" (Rampant Growth) which sets `criteria["basic"]` instead of a
#: `type` filter — the two are mutually exclusive alternatives tried in that
#: order (longest/most-specific first), never combined.
#: "Equipment" is a subtype, not a main card type, but `models.cards.card_query.
#: _type_matches` does a plain substring check against the whole printed
#: type line ("Artifact — Equipment") rather than only the pre-em-dash main
#: types — the same reason "Forest"/"Island" already work as entries here
#: despite being land subtypes too. Adding it costs nothing engine-side,
#: purely a missing vocabulary word (Steelshaper's Gift/Stoneforge
#: Mystic-shaped).
_SEARCH_TYPE_WORD = (
    r"artifact|creature|enchantment|instant|planeswalker|sorcery|land|"
    r"plains|island|swamp|mountain|forest|equipment"
)
#: An "or"/comma-separated list of 1+ type words, same shape as
#: `subgrammars._SPELL_TYPE_LIST` (kept separate/local since this vocabulary
#: — land + basic land names — is specific to a library search, not a spell
#: target filter).
_SEARCH_TYPE_LIST = (
    rf"(?:{_SEARCH_TYPE_WORD})(?:,\s*(?:{_SEARCH_TYPE_WORD}))*"
    rf"(?:,?\s+or\s+(?:{_SEARCH_TYPE_WORD}))?"
)
#: A colour word ahead of the type list — "search your library for a
#: **blue** instant card" (Merchant Scroll), "a **green** creature card"
#: (Green Sun's Zenith/Magus of the Order/Natural Order/Shadow-Rite
#: Priest) — captured and mapped onto `models.cards.card_query`'s own ``color``
#: key (matched against the card's colour identity), the same key/matcher
#: `_destroy_color_adj` already reuses via `resolve_color_word` — not
#: dropped, despite this module's older docstrings elsewhere describing it
#: that way (that was a real gap until `SearchLibraryEffect.criteria`
#: started reaching `card_query.matches`, not a documented permanent
#: choice). ``colorless`` (Eye of Ugin's "a colorless creature card") is
#: kept local to this search vocabulary rather than added to the shared
#: `subgrammars.COLOR_WORD_ALT`/`resolve_color_word` every other colour-word
#: consumer (target filters, "if it's `<color>`" suffixes, …) reuses — those
#: are genuinely WUBRG-only templates, "colorless" isn't a valid substitute
#: for any of them today, so widening that shared vocabulary would risk
#: silently claiming a clause it shouldn't. `_search_criteria_from_match`/
#: `_search_zone_criteria_from_match` handle it directly rather than through
#: `resolve_color_word`, which only maps WUBRG letters.
_SEARCH_COLOR_WORD = r"white|blue|black|red|green|colorless"
#: "…with mana value X or less" (Green Sun's Zenith/Chord of Calling) — X
#: is this spell's own announced {X}, so the captured magnitude is the
#: literal ``"x"``/``"-x"`` sentinel `RulesEngine._substitute_x` rewrites
#: once the spell actually resolves, exactly like every other X-scaled
#: one-shot effect; a literal digit bound ("…with mana value 3 or less")
#: is accepted the same way but has no known real card on this exact
#: search-noun-phrase shape yet.
_SEARCH_MV_QUALIFIER = (
    r"(?: with mana value (?P<mv>\d+|x) or (?P<mv_cmp>greater|less))?"
)
#: PAR-70: "a **rebel**/**mercenary** permanent card" (Mercadian Masques'
#: recruiter cycle — Ramosian Sergeant/Captain/Commander/Sky Marshal,
#: Cateran Persuader/Brute/Kidnappers/Enforcer/Slaver/Overlord, Amrou Scout/
#: Blightspeaker/Defiant Falcon, Bog Glider, Rathi Fiend/Intimidator).
#: Search subtypes share the generated, rules-backed vocabulary with other
#: card filters; both "a Dinosaur card" and "a Rebel permanent card" use it.
_SEARCH_SUBTYPE_WORD = '|'.join(
    re.escape(word) for word in sorted(SUBTYPES, key=lambda word: (-len(word), word))
    if word != 'aura'  # Keep the existing Aura/enchant-quality branch below.
)
#: The noun phrase after "search your library for": a determiner ("a"/"an"/
#: "up to N"), an optional "basic" qualifier (sets `basic`), an optional
#: "<subtype> [permanent]" qualifier (sets `subtype` — see
#: `_SEARCH_SUBTYPE_WORD` above), then either a `_SEARCH_TYPE_LIST` (sets
#: `types` — "land" is itself one of that list's words, so bare "basic land"
#: still resolves to ``{"basic": True}`` with no separate case) or neither
#: (a bare "a card"), then "card(s)", then an optional trailing mana-value
#: qualifier. "Basic" and a type list combine freely — "a basic Forest,
#: Plains, or Island card" (the Panorama/Landscape/Monument tri-land fetch
#: cycles, Bant Panorama-shaped: ~40 real cards on this exact combined
#: shape) narrows the search to *basic* lands of *those* named types, not
#: "basic land" (any basic) or a bare type list (any card of that type, not
#: necessarily basic) alone.
#: PAR-74: "an **Aura** card **with enchant creature**" (Tallowisp). Unlike
#: `_SEARCH_SUBTYPE_WORD`'s "`<subtype>` permanent" shape, "Aura" is an
#: *enchantment* subtype (not a creature one) named directly before "card",
#: with a trailing "with enchant creature" qualifier restricting *which*
#: Auras. `card_query.matches`'s ``type`` key is already a type-line
#: substring test, so ``{"type": "Aura"}`` alone correctly narrows to Auras
#: — the "with enchant creature" tail is consumed and dropped, the same
#: documented simplification `_SEARCH_REVEAL` uses for pure flavor text:
#: `card_query` has no "Enchant `<type>`" predicate, and every real card on
#: this template only ever wants a creature-enchanting Aura anyway (no
#: printed Aura enchants two different permanent types at once), so the
#: dropped qualifier can never cause a wrong pick in practice.
_SEARCH_AURA_ENCHANT_CREATURE_TAIL = r"(?:\s+with enchant creature)?"
_SEARCH_CRITERIA = (
    # RULE 701.19: an unrevealed zone, so "N cards" finds up to N — "for 2 basic land cards" is "for up to 2"; X is
    # the announced {X} or a measured amount bound by a "where X is" / die-result clause.
    r"(?:(?:up to )?(?P<count>\d+|x)|an?)\s+"
    rf"(?:(?P<color>(?:{_SEARCH_COLOR_WORD})(?: or (?:{_SEARCH_COLOR_WORD}))*)\s+)?"
    r"(?:(?P<basic>basic)\s+)?"
    rf"(?:(?P<subtype>{_SEARCH_SUBTYPE_WORD})\s+(?:(?P<subtype_permanent>permanent)\s+)?)?"
    rf"(?:(?P<aura>aura)\s+)?"
    r"(?P<permanent>permanent )?"
    rf"(?P<types>{_SEARCH_TYPE_LIST})?\s*"
    r"cards?"
    r"(?: named (?P<name>~|[a-z][a-z' -]*?))?"
    + _SEARCH_AURA_ENCHANT_CREATURE_TAIL
    + _SEARCH_MV_QUALIFIER
)
#: Whichever pronoun/noun-phrase a card's "reveal ~"/"put ~ <dest>" clause
#: uses for the found card — every variant found in the popular-tutor cache
#: scan (Wishclaw Talisman's "it", most tutors' "that card", Buried Alive's
#: plural "them", Worldly Tutor's "the card").
_SEARCH_PRONOUN = r"(?:it|that card|them|those cards|the card)"
#: An optional "reveal <pronoun>," clause between the criteria and the
#: put/shuffle tail (Eladamri's Call/Mystical/Enlightened/Worldly Tutor) —
#: purely descriptive text at this engine's fidelity (no separate game-state
#: effect: the found card is already known to both players via the search
#: choice), so it's consumed and dropped, not modeled as its own effect.
_SEARCH_REVEAL = rf"(?:reveal {_SEARCH_PRONOUN},?\s*)?"
#: Where the found card goes — order matters ("battlefield tapped" must be
#: tried before the bare "battlefield" row so it isn't left partially
#: unconsumed).
_SEARCH_DESTINATION_ROWS: list[tuple[str, str]] = [
    (r"onto the battlefield tapped", "battlefield_tapped"),
    (r"onto the battlefield", "battlefield"),
    (r"into your hand", "hand"),
    (r"into your graveyard", "graveyard"),
]
_SEARCH_DESTINATION_ALT = "|".join(f"(?:{frag})" for frag, _ in _SEARCH_DESTINATION_ROWS)


def _search_destination_kind(phrase: str) -> Optional[str]:
    text = phrase.strip()
    for frag, kind in _SEARCH_DESTINATION_ROWS:
        if re.fullmatch(frag, text, re.IGNORECASE):
            return kind
    return None

#: "Its controller may search their library for a basic land card, put it
#: onto the battlefield, then shuffle." (Assassin's Trophy/Geomancer's
#: Gambit/Ghost Quarter-shaped — always the trailing sentence after a
#: "Destroy target land/permanent an opponent controls." clause the
#: ordinary `destroy` handler already claims on its own) — `SearchLibraryEffect`'s
#: ``player="previous_target_controller"`` sentinel (the same one
#: `PayCostThenEffect`'s own ``payer`` param already uses for Chain of
#: Vapor's "that permanent's controller may sacrifice a land"), since the
#: acting player here is whoever just lost the destroyed permanent, not
#: this spell's own caster.
_DESTROY_CONTROLLER_SEARCH_BASIC_LAND_RE = compile_clause(
    r"its controller may search (?:its|their) library for a basic land card, "
    r"put it onto the battlefield(?P<tapped> tapped)?, then shuffle"
)


def _destroy_controller_search_basic_land(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec(
            "search",
            {
                "criteria": {"basic": True},
                # "…put it onto the battlefield **tapped**" (White Orchid
                # Phantom) — the same optional-tapped tail Ghost Quarter's
                # untapped form doesn't carry.
                "destination": "battlefield_tapped" if m.group("tapped") else "battlefield",
                "optional": True,
                "player": "previous_target_controller",
            },
        )
    ]


#: "search your library for <criteria>, [reveal <pronoun>,] put <pronoun>
#: <destination>, then shuffle." — the common put-then-shuffle order.
_SEARCH_PUT_THEN_SHUFFLE_RE = compile_clause(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)
#: Search criteria the plain grammar above has no slot for, each a whole phrase of its own: "an instant card or a
#: card with flash" (Mystical Teachings — an OR of two criteria) and "a land card with a basic land type"
#: (Sprouting Goblin — a land whose type line carries any of RULE 305.6's five basic types).
_SEARCH_NAMED_CRITERIA: dict[str, dict] = {
    "an instant card or a card with flash": {"or": [{"type": "instant"}, {"has_keyword": "Flash"}]},
    "a land card with a basic land type": {
        "all_types": ["land"], "type": ["plains", "island", "swamp", "mountain", "forest"],
    },
}
_SEARCH_NAMED_CRITERIA_RE = compile_clause(
    rf"search your library for (?P<crit>{'|'.join(re.escape(k) for k in _SEARCH_NAMED_CRITERIA)}),?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_named_criteria(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    return [EffectSpec("search", {
        "criteria": dict(_SEARCH_NAMED_CRITERIA[m.group("crit").lower()]), "destination": destination,
    })]


#: "search your library for <criteria> that share a land type, [reveal
#: <pronoun>,] put <pronoun> <destination>, then shuffle." (Myriad
#: Landscape, MEC-43 round 3) — the same put-then-shuffle order as
#: `_SEARCH_PUT_THEN_SHUFFLE_RE` just above, plus the cross-pick "that share
#: a land type" qualifier (RULE 305.6) between the criteria and the
#: put-clause; a separate regex rather than an optional group spliced into
#: the shared one, since only this one shape maps onto `"search"`'s new
#: ``share_land_type`` param (`SearchLibraryEffect`/`RulesEngine.
#: _request_search`).
_SEARCH_PUT_THEN_SHUFFLE_SHARE_TYPE_RE = compile_clause(
    rf"search your library for {_SEARCH_CRITERIA} that share a land type,?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)
#: "search your library for <criteria>, [reveal <pronoun>,] then shuffle and
#: put <pronoun> on top [of your library]." — the reordered shuffle-then-put
#: order, always to the top of the library (Vampiric/Mystical/Enlightened/
#: Worldly Tutor).
_SEARCH_SHUFFLE_THEN_PUT_TOP_RE = compile_clause(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"then shuffle and put {_SEARCH_PRONOUN} "
    # Long-Term Plans' "third from the top" (RULE 401.7) — the same shuffle-then-place order.
    r"(?:on top(?: of your library)?|(?P<third>third from the top))"
)


def _search_mv_qualifier_from_match(m: re.Match[str]) -> dict:
    """The trailing "with mana value X or less/greater" qualifier, if
    present — shared by `_SEARCH_CRITERIA` and `_SEARCH_ZONE_CRITERIA`,
    both of which name their groups ``mv``/``mv_cmp`` identically."""
    mv = m.groupdict().get("mv")
    if not mv:
        return {}
    n: Any = int(mv) if mv != "x" else "x"
    key = "max_mana_value" if m.groupdict().get("mv_cmp") == "less" else "min_mana_value"
    return {key: n}


def _search_color_from_match(m: re.Match[str]) -> Optional[str]:
    """The captured ``color`` group → a WUBRG letter, ``"colorless"``
    (`_SEARCH_COLOR_WORD`'s own local addition — see its docstring for why
    this isn't `resolve_color_word`), or ``None``."""
    word = (m.groupdict().get("color") or "").strip().lower()
    if " or " in word:
        return ["colorless" if part == "colorless" else resolve_color_word(part)
                for part in word.split(" or ")]
    if word == "colorless":
        return "colorless"
    return resolve_color_word(word)


def _search_criteria_from_match(m: re.Match[str]) -> dict:
    crit: dict = {}
    if m.groupdict().get("name"):
        crit["name"] = m.group("name").strip()
    if m.groupdict().get("permanent"):
        # RULE 110.4: permanent cards have at least one permanent card type.
        crit["type"] = list(PERMANENT_CARD_TYPES)
    basic = bool(m.groupdict().get("basic"))
    if basic:
        crit["basic"] = True
    subtype = m.groupdict().get("subtype")
    if subtype:
        crit["type"] = subtype.strip().lower()
        if m.groupdict().get('subtype_permanent'):
            # The subtype and permanent-card restriction are independent.
            crit['or'] = [{'type': list(PERMANENT_CARD_TYPES)}]
    if m.groupdict().get("aura"):
        crit["type"] = "Aura"
    types = m.groupdict().get("types")
    if types:
        words = [t.strip() for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", types) if t.strip()]
        # Bare "basic land" stays `{"basic": True}` alone (pre-existing
        # shape, Rampant Growth) — "land" is redundant once `basic` is set
        # (every basic card is a land), so it's only kept as a `type` filter
        # when it names something *besides* plain "land" ("a basic Forest,
        # Plains, or Island card" — the Panorama/Landscape/Monument tri-land
        # cycles, `_SEARCH_CRITERIA`'s combined basic+type-list shape).
        if not (basic and words == ["land"]):
            if subtype:
                crit['all_types'] = [subtype.strip().lower()]
            crit["type"] = words if len(words) > 1 else words[0]
    color = _search_color_from_match(m)
    if color:
        crit["color"] = color
    crit.update(_search_mv_qualifier_from_match(m))
    name = crit.get("name")
    if name and " or " in name:
        # RULE 201.2: each alternative is a literal English name. Reuse
        # criteria OR and retain every other restriction on each branch.
        return {"or": [{**crit, "name": part.strip()} for part in name.split(" or ")]}
    return crit


def _search_count_from_match(m: re.Match[str]) -> "Optional[int | str]":
    count = m.groupdict().get("count")
    if count == "x":
        return "x"
    return int(count) if count is not None else None


def _search_put_then_shuffle(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    params: dict = {"criteria": _search_criteria_from_match(m), "destination": destination}
    # RULE 701.20: revealing a named find is public information before it
    # enters the hand; the search continuation owns that complete move.
    if m.groupdict().get("name"):
        params["reveal"] = bool(re.search(r"\breveal\b", m.group(0)))
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: Elfhame Sanctuary's optional basic-land search has a reflexive "If you
#: do" tail.  Keep the tail on the asynchronous search itself so it resolves
#: after the player accepts the search, rather than immediately beside the
#: choice-opening effect.
_ELFHAME_SANCTUARY_RE = compile_clause(
    r"(?:you may )?search your library for a basic land card, reveal it, put it into your hand, "
    r"then shuffle\. if you do, you skip your draw step this turn\.?"
)


def _elfhame_sanctuary(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("search", {
        "criteria": {"basic": True, "types": ["land"]},
        "destination": "hand",
        "then_specs": [{"type": "skip_next_step", "params": {"step": "draw"}}],
    })]


def _search_put_then_shuffle_share_type(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    params: dict = {
        "criteria": _search_criteria_from_match(m),
        "destination": destination,
        "share_land_type": True,
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library for a card with mana value less than or equal to the
#: number of lands you control, [reveal <pronoun>,] put <pronoun>
#: <destination>, then shuffle." (Beseech the Queen, MEC-43 round 3) — a
#: board-count mana-value bound instead of `_SEARCH_CRITERIA`'s own literal
#: digit/``x`` (`_SEARCH_MV_QUALIFIER`), so it's its own regex rather than a
#: fourth `_SEARCH_MV_QUALIFIER` alternative; maps onto `"search"`'s
#: ``mana_value_from`` param with the new ``"count_selector"`` source
#: (`SearchLibraryEffect._resolved_criteria`, `continuous.count_selector`'s
#: existing ``"lands_you_control"`` entry).
_SEARCH_MV_LANDS_QUALIFIER_RE = compile_clause(
    r"search your library for a card with mana value less than or equal to "
    r"the number of lands you control,?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_mv_lands_qualifier(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    return [
        EffectSpec(
            "search",
            {
                "criteria": {},
                "mana_value_from": {"source": "count_selector", "count_selector": "lands_you_control"},
                "destination": destination,
            },
        )
    ]


#: "return a creature card from its owner's graveyard to the battlefield under the control of that creature's owner"
#: (Reincarnation, PAR-154) — "its/that creature's owner" is the owner of the object the enclosing DIES trigger fired
#: for, so the handler is only meaningful under such a trigger (it reads the firing event's ``owner_id``).
_RETURN_CREATURE_TO_DEAD_OWNER_RE = compile_clause(
    r"return a creature card from its owner's graveyard to the battlefield under the control of that creature's owner"
)


#: "search your library for a creature card with **lesser mana value**, put it onto the battlefield tapped, then
#: shuffle." (Rushed Rebirth, PAR-154) — "lesser" than the object the enclosing trigger fired for (the creature that
#: died, last-known, RULE 608.2h), so it maps onto `mana_value_from`'s ``trigger_subject`` source with a one-below
#: ``plus``; outside a trigger there is no such object and the search fails closed at resolution.
_SEARCH_LESSER_MV_RE = compile_clause(
    rf"search your library for an? (?P<types>{_SEARCH_TYPE_LIST}) card with lesser mana value,?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_lesser_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    return [EffectSpec("search", {
        "criteria": _search_criteria_from_match(m),
        "mana_value_from": {"source": "trigger_subject", "plus": -1, "cmp": "le"},
        "destination": destination,
    })]


#: "search your library for a snow permanent card, a legendary card, or a
#: Saga card, [reveal <pronoun>,] put <pronoun> <destination>, then
#: shuffle." (Search for Glory, MEC-43 round 3) — a three-way OR across
#: disjoint criteria shapes (a "snow" supertype card that's also a
#: *permanent*, vs. two plain type-line substrings) `_SEARCH_CRITERIA`'s own
#: single type-list grammar can't express, so it's its own regex mapped
#: straight onto `models.cards.card_query`'s already-general ``"or"`` combinator —
#: "snow permanent" is ``{"type": "Snow", "without_type": ["Instant",
#: "Sorcery"]}`` (RULE 205.4g's supertype, minus the two non-permanent card
#: types). This card's own trailing life-gain sentence is a wholly separate
#: clause (`_GAIN_LIFE_PER_SNOW_SPENT_RE` below), reached independently by
#: the segmenter's own period-connector split, not by this regex.
_SEARCH_SNOW_LEGENDARY_SAGA_RE = compile_clause(
    r"search your library for a snow permanent card, a legendary card, or a saga card,?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_snow_legendary_saga(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    criteria = {
        "or": [
            {"type": "Snow", "without_type": ["Instant", "Sorcery"]},
            {"type": "Legendary"},
            {"type": "Saga"},
        ]
    }
    return [EffectSpec("search", {"criteria": criteria, "destination": destination})]


#: "You gain 1 life for each {S} spent to cast this spell." (Search for
#: Glory's own trailing sentence) — reads `GameObject.mana_spent_to_cast_
#: snow` (MEC-43 round 3, `ManaPool.snow_pool`) via the already-general
#: ``"gain_life"`` `count_selector` hook (`continuous.count_selector`'s new
#: ``"snow_mana_spent_to_cast"`` entry), the same self-referential idiom
#: `sacrificed_cost_mana_value`/`sacrificed_cost_power` already use. Scoped
#: to the literal "1 life" this card prints — no known card scales the
#: amount, so a multiplier is left unbuilt rather than guessed at.
_GAIN_LIFE_PER_SNOW_SPENT_RE = compile_clause(r"you gain 1 life for each \{s\} spent to cast this spell")


def _gain_life_per_snow_spent(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"count_selector": "snow_mana_spent_to_cast"})]


#: "search your library for <criteria>, put <pronoun> onto the battlefield,
#: attach it to a creature you control, then shuffle." (Stonehewer Giant/
#: Quest for the Holy Relic-shaped combined search-then-attach — MEC-12
#: sixth pass) — a strict superset of `_SEARCH_PUT_THEN_SHUFFLE_RE`'s own
#: "put <pronoun> onto the battlefield, then shuffle" shape with the attach
#: clause spliced in, mapped onto `"search"`'s new
#: ``attach_to_creature_you_control`` param (`SearchLibraryEffect`).
#: Destination is always the battlefield (the attach clause presupposes
#: it), so unlike the plain family this doesn't need a `dest` capture group.
_SEARCH_PUT_ATTACH_THEN_SHUFFLE_RE = compile_clause(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} onto the battlefield,?\s*"
    r"attach it to a creature you control,?\s*"
    r"then shuffle"
)


def _search_put_attach_then_shuffle(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "criteria": _search_criteria_from_match(m),
        "destination": "battlefield",
        "attach_to_creature_you_control": True,
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


def _search_shuffle_then_put_top(m: re.Match[str]) -> list[EffectSpec]:
    destination = "library_third" if m.groupdict().get("third") else "library_top"
    params: dict = {"criteria": _search_criteria_from_match(m), "destination": destination}
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library for up to N basic land cards, reveal those cards,
#: put one <destA> and the other <destB>, then shuffle." (Cultivate/Kodama's
#: Reach-shaped split destination — RULE 701.19 same as the plain family
#: above, just two different destinations for the two picks instead of one
#: shared `destination`; maps onto `"search"`'s `destinations` param,
#: positional against the picks).
_SEARCH_SPLIT_DESTINATION_RE = compile_clause(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    # "one" is folded to "1" by `normalize`'s spelled-number pass (it can't
    # tell this "one" is a pronoun, not a count) — match the folded form.
    rf"put 1 (?P<dest1>{_SEARCH_DESTINATION_ALT}) and the other "
    rf"(?P<dest2>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_split_destination(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dest1 = _search_destination_kind(m.group("dest1"))
    dest2 = _search_destination_kind(m.group("dest2"))
    if dest1 is None or dest2 is None:
        return None
    params: dict = {
        "criteria": _search_criteria_from_match(m),
        "destination": dest1,
        "destinations": [dest1, dest2],
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library for N cards. Put 1 <destA> and the other <destB>.
#: Then shuffle." (Final Parting, MEC-43 round 3) — the same split
#: destination as `_SEARCH_SPLIT_DESTINATION_RE` just above, but printed as
#: three plain sentences (bare "N cards", no criteria/reveal clause) instead
#: of one comma-joined one, so it needs its own literal ``\.\s*`` sentence
#: boundaries rather than reusing `_SEARCH_CRITERIA`/`_SEARCH_REVEAL` (same
#: idiom `_SEARCH_EXILE_REST_RE` below already uses for its own two-sentence
#: Doomsday shape).
_SEARCH_TWO_CARDS_SPLIT_RE = compile_clause(
    r"search your library for (?P<count>\d+) cards?\.\s*"
    rf"put 1 (?P<dest1>{_SEARCH_DESTINATION_ALT}) and the other "
    rf"(?P<dest2>{_SEARCH_DESTINATION_ALT})\.\s*"
    r"then shuffle"
)


def _search_two_cards_split(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dest1 = _search_destination_kind(m.group("dest1"))
    dest2 = _search_destination_kind(m.group("dest2"))
    if dest1 is None or dest2 is None:
        return None
    return [
        EffectSpec(
            "search",
            {
                "criteria": {},
                "destination": dest1,
                "destinations": [dest1, dest2],
                "count": int(m.group("count")),
            },
        )
    ]


#: The criteria noun phrase for a "library and/or graveyard" search — same
#: basic-land/type-list alternatives as `_SEARCH_CRITERIA`, plus a bare-name
#: alternative ("a card named <Name>") this family's real cards lean on
#: heavily (planeswalker/background tutors); restricted to a name with no
#: internal comma (see the module docstring above for why).
_SEARCH_ZONE_CRITERIA = (
    r"(?:up to (?P<count>\d+)|an?)\s+"
    rf"(?:(?P<color>{_SEARCH_COLOR_WORD})\s+)?"
    r"(?:"
    r"(?P<basic>basic land) cards?"
    rf"|card named (?P<name>[a-z][a-z' -]*?)"
    rf"|(?P<types>{_SEARCH_TYPE_LIST}) cards?"
    r"|cards?"
    r")"
    + _SEARCH_MV_QUALIFIER
)
#: "search your library and/or graveyard for <criteria>, [reveal <pronoun>,]
#: [and] put <pronoun> <destination>. If you search[ed] your library this
#: way, shuffle." (RULE 701.19 "and/or" combined-zone search — the
#: backgrounds/planeswalker-tutor family: Delivery Moogle/Tale of Momo/
#: Elspeth Undaunted Hero/Tower Winder/…). Unlike the library-only family's
#: "then shuffle" tail, the shuffle here is conditional on *which* zone hit
#: — engine-side this maps onto `RulesEngine._finish_search` always
#: shuffling whenever ``"library"`` is among ``zones`` (a documented
#: simplification: it doesn't track which specific zone the chosen card(s)
#: actually came from).
_SEARCH_ZONE_PUT_RE = compile_clause(
    rf"search your library and/or graveyard for {_SEARCH_ZONE_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"(?:and\s+)?put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT})\.\s*"
    r"if you search(?:ed)? your library this way,?\s*shuffle"
)


def _search_zone_criteria_from_match(m: re.Match[str]) -> dict:
    if m.groupdict().get("basic"):
        crit: dict = {"basic": True}
    else:
        name = m.groupdict().get("name")
        if name:
            return {"name": name.strip()}  # a named-card search ignores colour/mv qualifiers
        crit = {}
        types = m.groupdict().get("types")
        if types:
            words = [t.strip() for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", types) if t.strip()]
            crit["type"] = words if len(words) > 1 else words[0]
    color = _search_color_from_match(m)
    if color:
        crit["color"] = color
    crit.update(_search_mv_qualifier_from_match(m))
    return crit


def _search_zone_put(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    params: dict = {
        "criteria": _search_zone_criteria_from_match(m),
        "destination": destination,
        "zones": ["library", "graveyard"],
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library [and graveyard] for N cards and exile the rest. Put
#: the chosen cards on top of your library in any order." (Doomsday-shaped —
#: no "then shuffle" at all: RULE 701.19e's shuffle is for an *ordinary*
#: search, and this one's own text never calls for one). Maps onto
#: `"search"`'s ``exile_rest``/``count``/``destination="library_top"``.
_SEARCH_EXILE_REST_RE = compile_clause(
    r"search your library(?P<gy> and (?:your )?graveyard)? for "
    r"(?P<count>\d+) cards? and exile the rest\.\s*"
    r"put the chosen cards? on top of your library in any order"
)


def _search_exile_rest(m: re.Match[str]) -> list[EffectSpec]:
    zones = ["library", "graveyard"] if m.group("gy") else ["library"]
    return [
        EffectSpec(
            "search",
            {
                "criteria": {},
                "destination": "library_top",
                "count": int(m.group("count")),
                "exile_rest": True,
                "zones": zones,
            },
        )
    ]


#: "An opponent gains control of ~." (Wishclaw Talisman-shaped — RULE
#: 701.10-adjacent; `game/effects/core.py`'s `GainControlBySourceEffect`).
_GAIN_CONTROL_BY_OPPONENT_RE = compile_clause(
    rf"(?P<recipient>an|target) opponent gains control of (?P<subject>{SELF_SUBJECT})"
)


def _gain_control_by_opponent(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    # RULE 608.2c: a bare "it" must refer to this ability's source, not a
    # previously selected creature or the object of a group trigger.
    if m.group("subject") == "it" and not reading.self_subject:
        return None
    recipient = "target_opponent" if m.group("recipient") == "target" else "opponent"
    return [EffectSpec("gain_control_by_source", {"recipient": recipient})]


#: RULE 108.4-adjacent "threaten" effect — "Gain control of target creature
#: until end of turn." (Act of Treason/Act of Aggression/Claim the
#: Firstborn-shaped — the single most-repeated effect template in the whole
#: cache, ~90 real cards). `effects.GainControlUntilEndOfTurnEffect` already
#: bundles the control change, untap, and haste grant into one atomic effect
#: (built for the hand-authored Zealous Conscripts); this only teaches the
#: parser the oracle-text shape, including its optional "with mana value N
#: or less" cap (Claim the Firstborn, `TargetSpec.max_mana_value`, the same
#: param `destroy_mv` uses). The trailing "Untap that creature[.] It gains
#: haste until end of turn." pair is recognized separately, in `segmenter.
#: parse_effect_body` (`_GAIN_CONTROL_HASTE_TAIL_RE`) — it's not a second
#: effect, just the card restating in words what this one already does, so
#: it's absorbed there rather than re-parsed into a second (redundant, and
#: RULE-115-target-doubling-risky) untap/haste effect here.
_GAIN_CONTROL_EOT_RE = compile_clause(
    rf"gain control of (?P<another>another )?{TARGET}"
    r"(?: with mana value (?P<mv>\d+) or less"
    # PAR-74: "…with **that spell's** mana value." (Skyfire Kirin) — the
    # exact-match sibling of the literal-digit ceiling just above,
    # `TargetSpec.exact_mana_value`'s own sentinel resolution.
    r"|(?P<trigger_mv> with that spell'?s mana value))?"
    # PAR-163: RULE 611.2 "until the end of your next turn" (Wyll, Pact-Bound Duelist) -- the thief's next-turn clock.
    r"(?: until end of turn|(?P<next_turn> until the end of your next turn))"
)


def _gain_control_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, (
        "creature", "creature_you_dont_control", "permanent", "artifact",
    )):
        return None
    params: dict = {"target_kind": kind, **optional_param(m)}
    if m.group("mv"):
        params["max_mana_value"] = int(m.group("mv"))
    if m.groupdict().get("trigger_mv"):
        params["exact_mana_value"] = "trigger_spell_mana_value"
    # "gain control of target creature an opponent controls **with power N
    # or less/greater**" (Enthralling Victor) — a target-offer-time filter,
    # RULE 115.1c. "another" (Akroan Conscriptor) is accepted but its RULE
    # 601.2c self-exclusion isn't enforced (documented simplification —
    # these are all trigger/ETB bodies with no reason to grab the source).
    # PAR-160: the power bound is now `TARGET`'s own quality slot.
    quality = target_quality_filter(m.group("target"))
    if quality:
        params["creature_filter"] = quality
    if m.groupdict().get("next_turn"):
        # No untap/haste rider belongs to this duration's printings (an explicit "untap that creature" tail is a separate clause).
        params.update({"duration": "end_of_your_next_turn", "haste": False, "untap": False})
    return [EffectSpec("gain_control_until_eot", params)]


#: PAR-130: the **no-duration** steal — "gain control of target artifact"
#: (Keiga, Ritual of the Machine, Souvenir Snatcher), "for each opponent, gain
#: control of target permanent that player controls" (Blatant Thievery) —
#: RULE 611.2's indefinite control change, the ``duration="permanent"`` mode of
#: the same effect (untap/haste off; built for Entrancing Melody). An "Untap
#: it." restatement right after it turns the untap on (Invoke the Winds). A
#: duration ("until end of turn", "for as long as …") never reaches this row:
#: the full match leaves it unclaimed for its own row.
_GAIN_CONTROL_PERMANENT_RE = compile_clause(
    rf"gain control of (?P<another>another )?{TARGET}"
    r"(?: with mana value (?P<mv>\d+) or less)?"
    r"(?P<untap>\.\s*untap (?:it|that (?:creature|permanent|artifact|land)))?"
)
#: What a permanent steal may take — permanents only (a spell is
#: `gain_control_of_spell`'s), incl. any controller-scoped narrowing.
_GAIN_CONTROL_PERMANENT_KINDS = (
    "permanent", "nonland_permanent", "creature", "creature_or_planeswalker", "artifact",
    "enchantment", "land", "artifact_or_creature", "artifact_or_enchantment",
)


def _gain_control_permanent(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _GAIN_CONTROL_PERMANENT_KINDS):
        return None
    params: dict = {
        "target_kind": kind, **optional_param(m),
        "duration": "permanent", "haste": False, "untap": bool(m.group("untap")),
    }
    if m.group("mv"):
        params["max_mana_value"] = int(m.group("mv"))
    quality = target_quality_filter(m.group("target"))  # PAR-160: "with power N or less" (TARGET's quality slot)
    if quality:
        params["creature_filter"] = quality
    return [EffectSpec("gain_control_until_eot", params)]


#: PAR-150: RULE 611.2b -- "gain control of up to one target creature with lesser power for as long as you control ~"
#: (Rangers of Ithilien) / "...for as long as this saga remains on the battlefield" (The Horus Heresy, per opponent).
#: The no-duration steal plus a source-bound end (`GainControlUntilEndOfTurnEffect.while_source`).
_GAIN_CONTROL_WHILE_SOURCE_RE = compile_clause(
    rf"(?P<per_opp>for each opponent, )?gain control of {TARGET}(?P<lesser> with lesser power)?"
    r" for as long as (?:(?P<ctl>you control (?:~|this (?:creature|saga|artifact|permanent|enchantment)))"
    r"|(?:~|this (?:creature|saga|artifact|permanent|enchantment)) remains on the battlefield)"
)


def _gain_control_while_source(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _GAIN_CONTROL_PERMANENT_KINDS):
        return None
    params: dict = {
        "target_kind": kind, **optional_param(m), "duration": "permanent", "haste": False, "untap": False,
        "while_source": "controlled" if m.group("ctl") else "on_battlefield",
    }
    quality = target_quality_filter(m.group("target"))
    if "legendary" in m.group("target").lower() and not quality:
        return None  # the scoped "that player controls" kind drops the legendary qualifier: fail closed
    if m.group("lesser"):
        quality = {**(quality or {}), "power_vs_reference": "less"}
    if quality:
        params["creature_filter"] = quality
    return [EffectSpec("gain_control_until_eot", params)]


#: MEC-118: "Tap target creature you control and target creature an opponent controls. Those creatures fight each
#: other." (Arena, Magus of the Arena) -- one `fight` over two announced targets that taps both first.
_TAP_AND_FIGHT_RE = compile_clause(
    r"tap target creature you control and target creature (?P<other>an opponent controls|you don't control)\."
    r"\s*those creatures fight each other"
)


def _tap_and_fight(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("fight", {
        "fighter_kind": "creature_you_control", "other_kind": "creature_you_dont_control", "tap_fighters": True,
    })]


#: MEC-118: RULE 611.2b -- "for as long as ~ remains tapped, gain control of target creature [an opponent controls]"
#: (Preacher): the no-duration steal that ends when the source untaps (`while_source="tapped"`).
_GAIN_CONTROL_WHILE_TAPPED_RE = compile_clause(rf"for as long as (?:~|this creature) remains tapped, gain control of {TARGET}")


def _gain_control_while_tapped(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _GAIN_CONTROL_PERMANENT_KINDS) or target_quality_filter(m.group("target")):
        return None
    return [EffectSpec("gain_control_until_eot", {
        "target_kind": kind, **optional_param(m), "duration": "permanent", "haste": False, "untap": False,
        "while_source": "tapped",
    })]


#: The untargeted mass sibling — "Untap all creatures and gain control of
#: them until end of turn. They gain haste until end of turn." (Insurrection)
#: — RULE 601.2c's "all creatures" over the same `GainControlUntilEndOfTurnEffect`,
#: `selector="all_creatures"` (`effects._mass_selector_objects`). A whole-body
#: match (both sentences, like `_DESTROY_ALL_NO_REGEN_RE`) rather than the
#: `_GAIN_CONTROL_HASTE_TAIL_RE` two-step above, since the only real card
#: printing this exact mass shape has nothing before or after it to split on.
_GAIN_CONTROL_ALL_RE = compile_clause(
    r"untap all creatures and gain control of them until end of turn\."
    r"\s*they gain haste until end of turn"
)

_GAIN_CONTROL_GROUP_RE = compile_clause(
    r'gain control of (?P<quant>all|each) (?P<group>.+?)(?P<duration> until end of turn)?'
)


def _gain_control_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = mass_group_params(m['group'], m['quant'])
    if params is None:
        return None
    params.update(duration='end_of_turn' if m['duration'] else 'permanent', haste=False, untap=False)
    return [EffectSpec('gain_control_until_eot', params)]


def _gain_control_all(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_control_until_eot", {"selector": "all_creatures"})]


#: "For each opponent, gain control of up to 1 target creature that player
#: controls until end of turn. Untap those creatures. They gain haste until
#: end of turn." (Mass Mutiny / Molten Primordial / Mob Rule-shaped) — the
#: one-requirement-per-opponent RULE 601.2c count, the same `count_selector`
#: shape `_goad_per_opponent` uses, over the multi-target
#: `GainControlUntilEndOfTurnEffect` (its `apply` now iterates every chosen
#: target, not just the first). A whole-body match like `_GAIN_CONTROL_ALL_
#: RE` — the untap/haste restatement is the same "the effect already does
#: this" tail `_GAIN_CONTROL_HASTE_TAIL_RE` absorbs.
_GAIN_CONTROL_EOT_PER_OPPONENT_RE = compile_clause(
    r"for each opponent, gain control of up to (?:one|1) target creature "
    r"that player controls until end of turn\.\s*"
    r"untap (?:those creatures|them)\.\s*they gain (?P<kw>[a-z0-9, ]+?) until end of turn"
)


def _gain_control_eot_per_opponent(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # PAR-150: the haste the effect itself grants may be listed with more keywords (Hideous Taskmaster's "trample,
    # haste, and annihilator 1"); the rest ride a `pump` over the creatures just taken (`previous_subject`).
    split = split_keywords_with_parametric(m.group("kw"))
    if split is None or "haste" not in split[0]:
        return None
    flags, parametric = split
    flags = [f for f in flags if f != "haste"]
    specs = [EffectSpec("gain_control_until_eot", {
        "target_kind": "creature_you_dont_control",
        "optional": True,
        "count_selector": "opponents",
    })]
    if flags or parametric:
        extra: dict = {"previous_subject": True}
        if flags:
            extra["keywords"] = flags
        if parametric:
            extra["parametric_keywords"] = parametric
        specs.append(EffectSpec("pump", extra))
    return specs


#: PAR-30 "Threaten … tails residue" — the *opponent-scoped mass* threaten,
#: the other end from `_GAIN_CONTROL_ALL_RE`'s "all creatures": "Gain
#: control of all <type> [your opponents / target opponent] control[s] until
#: end of turn. Untap them. They gain haste until end of turn." (Broadcast
#: Takeover — artifacts, all opponents; Call for Aid — creatures, one
#: targeted opponent, + the two anti-abuse riders below). A whole-body
#: match like its siblings above; the untap/haste restatement is the same
#: "the effect already does this" tail.
_GAIN_CONTROL_MASS_EOT_RE = compile_clause(
    r"gain control of all (?P<mtype>creatures|artifacts|nonland permanents|permanents) "
    r"(?P<who>your opponents control|target opponent controls) until end of turn\.\s*"
    r"untap (?:them|those creatures|those permanents|those artifacts)\.\s*"
    r"they gain haste until end of turn"
    r"(?P<riders>(?:\.\s*you can'?t [^.]+)*)\.?"
)

_MASS_OPPONENT_SELECTORS: dict[str, str] = {
    "creatures": "opponents_creatures",
    "artifacts": "opponents_artifacts",
}
_MASS_NO_SAC_RE = re.compile(
    r"you can'?t sacrifice (?:those creatures|them) this turn", re.IGNORECASE
)
_MASS_NO_ATTACK_RE = re.compile(
    r"you can'?t attack that player this turn", re.IGNORECASE
)


def _gain_control_mass_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    mtype = m.group("mtype")
    riders = (m.groupdict().get("riders") or "").strip()
    no_sac = bool(_MASS_NO_SAC_RE.search(riders))
    no_attack = bool(_MASS_NO_ATTACK_RE.search(riders))
    # Fail closed if a rider sentence is present that isn't one of the two
    # we model (RULE never-half-model).
    leftover = _MASS_NO_SAC_RE.sub("", _MASS_NO_ATTACK_RE.sub("", riders))
    if re.sub(r"[.\s]", "", leftover):
        return None

    if m.group("who") == "target opponent controls":
        # One RULE 115 opponent target, then every creature/artifact that
        # player controls (`GainControlUntilEndOfTurnEffect.mass_of_target_
        # player`). Only the two real printed type words.
        if mtype not in ("creatures", "artifacts"):
            return None
        params: dict = {"target_kind": "opponent", "mass_of_target_player": mtype[:-1]}
        if no_sac:
            params["mark_no_sacrifice"] = True
        out = [EffectSpec("gain_control_until_eot", params)]
        if no_attack:
            out.append(EffectSpec("prevent_attacking_player_this_turn", {}))
        return out

    if no_sac or no_attack:
        return None  # the riders name "that player" — only the targeted form
    sel = _MASS_OPPONENT_SELECTORS.get(mtype)
    if sel is None:
        return None  # "permanents" — no `opponents_permanents` selector, fail closed
    return [EffectSpec("gain_control_until_eot", {"selector": sel})]


#: "Whenever a player casts an instant or sorcery spell, that player
#: copies it and may choose new targets for the copy [until end of turn]."
#: (Bonus Round) — RULE 603.1's "it"/"that player" both name the *firing
#: trigger event* rather than a RULE 601.2c target choice, unlike every
#: other `copy_spell` card in scope (Dualcaster Mage-shaped, which really
#: does target). `CopySpellEffect.spell_from_trigger_event`/
#: `controller_from_trigger_event` read the SPELL_CAST event's own
#: ``instance_id``/``player_id`` instead of a target list — the same
#: "resolve off the firing event" idiom `DestroyEffect.
#: target_from_trigger_event` already established (Mikaeus, the
#: Unhallowed). "may choose new targets" is the same accepted
#: simplification `CopySpellEffect`'s own docstring already documents for
#: every card in this family (the copy keeps the original's targets, no
#: retarget prompt) — not a new gap this card introduces.
_TRIGGER_COPY_SPELL_RE = compile_clause(
    r"that player copies it and may choose new targets for the copy(?: until end of turn)?"
)

#: Targeted stack copies compose the shared spell-target grammar, copy
#: count and optional retargeting rider (RULE 707.10c). The sibling ability
#: target keeps stack identity; its fixed count differs from Gogo's X.
_TARGETED_STACK_COPY_RE = compile_clause(
    rf"copy (?:(?P<ability>target activated or triggered ability)(?P<ability_scope> you control)?|{SPELL_TARGET})"
    r"(?: (?P<copy_count>twice|x times|\d+ times))?\.?"
    r"(?:\s*(?P<retarget>you may choose new targets for (?:the|that) cop(?:y|ies))\.?)?"
)


def _targeted_stack_copy(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    count_text = m.group("copy_count")
    count = 1 if count_text is None else 2 if count_text == "twice" else (
        "x" if count_text == "x times" else int(count_text.split()[0])
    )
    params = {"count": count, "choose_new_targets": bool(m.group("retarget"))}
    if m.group("ability"):
        params["target_kind"] = "ability_you_control" if m.group("ability_scope") else "ability"
        return [EffectSpec("copy_target_ability", params)]
    filt = resolve_spell_filter(m.group("target"))
    if filt is None:
        return None
    params["target_kind"] = filt.pop("target_kind", "spell")
    if "card_types" in filt:
        params["card_types"] = filt.pop("card_types")
    if filt:
        params["spell_filter"] = filt
    return [EffectSpec("copy_spell", params)]


#: "Each instant and sorcery card in your graveyard gains flashback until
#: end of turn. The flashback cost is equal to its mana cost." (Past in
#: Flames/Will of the Jeskai-shaped — the untargeted "each" sibling of
#: `_GRANT_FLASHBACK_TARGET_RE` below). `GrantGraveyardCastPermissionThisTurnEffect`
#: already exists (built for Backdraft Hellkite's identical wording) — this
#: is purely the missing oracle-text recognizer for a *second* card using
#: the same primitive, per the project's "sweep for what else a new
#: primitive closes" discipline.
_GRANT_FLASHBACK_EACH_RE = compile_clause(
    r"each instant and sorcery card in your graveyard gains flashback until end of turn\.\s*"
    r"the flashback cost is equal to its mana cost"
)


def _grant_flashback_each(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_graveyard_cast_permission_this_turn", {})]


#: "Target instant or sorcery card in your graveyard gains flashback until
#: end of turn. The flashback cost is equal to its mana cost." (MEC-24 —
#: Recoup/Snapcaster Mage/Slickshot Lockpicker/Sphinx of Forgotten Lore/
#: Katilda and Lier-shaped) — the *targeted*, single-card sibling of
#: `_GRANT_FLASHBACK_EACH_RE` above, needing a genuinely different
#: primitive (`grant_flashback_to_target`/`GameState.temp_flashback_grants`
#: — see that effect's own docstring for why the untargeted marker doesn't
#: fit) rather than reusing `grant_graveyard_cast_permission_this_turn`.
#: Reuses the graveyard-recursion family's own `_GRAVEYARD_TYPE_WORD`/
#: `_GRAVEYARD_SCOPE_WORD`/`_graveyard_target_kind` vocabulary (word order
#: is "target ... card **in** ... graveyard", not "**from** ... graveyard"
#: like the recursion family, so this is its own regex rather than a shared
#: one). The trailing "the flashback cost is equal to [that card's/its]
#: mana cost" sentence is optional and dropped once matched — it's not a
#: second effect, just prose restating what "gains flashback" (with no
#: literal cost) already means; when a literal cost **is** given inline
#: instead (The Fugitive Doctor's "gains flashback {2}{R}{G} until end of
#: turn", no such sentence at all), ``cost`` carries it and overrides the
#: "equal to its mana cost" default `GrantFlashbackToTargetEffect` falls
#: back to.
_GRANT_FLASHBACK_TARGET_RE = compile_clause(
    rf"target (?:(?P<type>{GRAVEYARD_TYPE_WORD}) )?card in "
    rf"(?P<scope>{GRAVEYARD_SCOPE_WORD}) graveyard gains flashback"
    r"(?: (?P<cost>(?:\{[^}]+\})+))? until end of turn\.?"
    r"(?:\s*the flashback cost is equal to (?:that card'?s|its) mana cost\.?)?"
)


def _grant_flashback_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind}
    if m.groupdict().get("cost"):
        params["cost"] = m.group("cost")
    return [EffectSpec("grant_flashback_to_target", params)]

_CAST_WINDOW_TYPE_WORD = rf"artifact, instant, or sorcery|{GRAVEYARD_TYPE_WORD}"
_CAST_WINDOW_SOURCE_POWER = r"less than or equal to (?:~'s|his|her|its) power"
_TARGET_GRAVEYARD_CAST_RE = compile_clause(
    r"(?P<until>until end of turn, )?(?:you may )?cast target "
    rf"(?:(?P<color>{'|'.join(CAST_WINDOW_COLORS)}) )?"
    rf"(?:(?P<type>{_CAST_WINDOW_TYPE_WORD}) )?card"
    rf"(?: with mana value (?P<cap>\d+ or less|{_CAST_WINDOW_SOURCE_POWER}))? from "
    rf"(?P<scope>{GRAVEYARD_SCOPE_WORD}) graveyard"
    r"(?P<this_turn> this turn)?"
    r"(?P<free> without paying its mana cost)?\.?"
    r"(?:\s*if that spell would be put into (?:your|their|an opponent'?s|a) graveyard, exile it instead\.?)?"
)


def _target_graveyard_cast(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    type_word = m.groupdict().get("type")
    if type_word == "artifact, instant, or sorcery":
        kind = graveyard_target_kind(None, m.group("scope"))
        kind = kind.removesuffix("_card") + "_instant_sorcery_or_artifact" if kind else None
    else:
        kind = graveyard_target_kind(type_word, m.group("scope"))
    if kind is None:
        return None
    turn_long = bool(m.group("until") or m.group("this_turn"))
    params: dict = {
        "target_kind": kind, "as_permission": True,
        "exile_if_would_be_put_into_graveyard": "exile it instead" in m.group(0),
    }
    if not turn_long:
        params["during_resolution"] = True
    if m.group("free"):
        params["free"] = True
    if m.group("color"):
        params["colors"] = [CAST_WINDOW_COLORS[m.group("color")]]
    cap = m.group("cap")
    if cap:
        params["max_mana_value"] = "source_power" if "power" in cap else int(cap.split()[0])
    return [EffectSpec("grant_flashback_to_target", params)]


#: "The next [creature] spell you cast this turn can't be countered." (Mistrise Village,
#: Insist, Overmaster) and "[Creature] spells you control|cast [this turn] can't be
#: countered [this turn]." (Veil of Summer, Domri, Anarch of Bolas) — a continuous effect
#: for the rest of the turn (`cant_be_countered_this_turn`, an `UncounterableGrant`), not a
#: trigger on the cast: it also protects a spell already on the stack, and an opponent gets
#: no window to respond to it. A bare "spells you control can't be countered." with no "this
#: turn" is a static ability and stays out of this row.
_UNCOUNTERABLE_TYPE_WORD = r"(?:creature|artifact|enchantment|instant|sorcery|planeswalker|land)"
_UNCOUNTERABLE_TYPES = (
    rf"{_UNCOUNTERABLE_TYPE_WORD}(?:(?:, | or | and |, or |, and ){_UNCOUNTERABLE_TYPE_WORD})*"
)
_UNCOUNTERABLE_THIS_TURN_RE = compile_clause(
    rf"(?:the next (?:(?P<next_types>{_UNCOUNTERABLE_TYPES}) )?spell you cast this turn"
    rf"|(?:(?P<types_a>{_UNCOUNTERABLE_TYPES}) )?spells you control"
    rf"|(?:(?P<types_b>{_UNCOUNTERABLE_TYPES}) )?spells you cast this turn)"
    r"(?P<tail> this turn)? can'?t be countered(?: this turn)?"
)


def _cant_be_countered_this_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    next_only = m.group("next_types") is not None or m.group(0).lower().startswith("the next")
    if not next_only and "this turn" not in m.group(0).lower():
        return None
    words = m.group("next_types") or m.group("types_a") or m.group("types_b")
    params: dict = {}
    if words:
        params["card_types"] = re.findall(_UNCOUNTERABLE_TYPE_WORD, words.lower())
    if next_only:
        params["next_only"] = True
    return [EffectSpec("cant_be_countered_this_turn", params)]


#: "Look at the top card of target player's library." (Mishra's Bauble) /
#: "Look at a card at random in target player's hand." (Urza's Bauble) — a
#: genuine RULE 115 target with no other game-state consequence, see
#: `LookAtCardsEffect`'s own docstring for why. Two narrow, closed phrasings
#: (not "look at *any* card X") rather than a general "look at" grammar —
#: the only two real cards printing this in the cache.
_LOOK_AT_TARGET_RE = compile_clause(
    r"look at (?:the top card of target player's library"
    r"|a card at random in target player's hand)"
)


def _look_at_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("look_at_cards", {"target_kind": "player"})]


def _trigger_copy_spell(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec(
            "copy_spell",
            {
                "spell_from_trigger_event": "instance_id",
                "controller_from_trigger_event": "player_id",
            },
        )
    ]


#: "Shuffle ~ into its owner's library." (RULE 701.20 — Green Sun's Zenith's
#: own trailing sentence, overriding the spell's default RULE 608.2m
#: "goes to the graveyard as it resolves" routing; `game/effects/core.py`'s
#: `ShuffleSelfIntoLibraryEffect`).
_SHUFFLE_SELF_INTO_LIBRARY_RE = compile_clause(
    rf"shuffle {SELF_SUBJECT} into its owner'?s library"
)
#: ENG-32 (Watery Grasp) — the Aura-host form: "Enchanted creature's owner
#: shuffles it into their library."
_SHUFFLE_ENCHANTED_INTO_LIBRARY_RE = compile_clause(
    r"enchanted creature'?s owner shuffles it into (?:their|its owner'?s) library"
)


def _shuffle_self_into_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("shuffle_self_into_library", {})]


def _shuffle_enchanted_into_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("shuffle_self_into_library", {"subject": "attached_permanent"})]


#: "attach it to target creature you control" / "attach ~ to target creature
#: you control" (an Equipment's own ETB self-attach, RULE 303.4f-adjacent —
#: `AttachEffect` already exists for Equip's activated ability, reused here).
def _attach(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("permanent", "creature", "creature_you_control")):
        return None
    params: dict = {"target_kind": kind}
    # "attach it to target legendary creature you control" (Mithril Coat, Mjölnir): the destination's qualifier
    # rides as the same `creature_filter` the Equip-restricted-to-commanders form uses.
    filt = resolve_target_creature_state_filter(m.group("target"))
    if filt:
        params["creature_filter"] = filt
    return [EffectSpec("attach", params)]


#: PAR-135: "attach target Equipment [you control] to target creature [you control]" (Magnetic Theft,
#: Auriok Windwalker, Kor Outfitter) and its variants — `AttachChosenEffect`, the two-requirement
#: effect Brass Squire and Halvar were hand-authored onto. The *moved* half is "[up to one |any number of]
#: target Equipment"; the destination is a second target ("to up to one target creature you control",
#: "to target attacking creature") or not a target at all ("to ~", "to it" under a self/group/attached
#: subject, "to that creature" after an earlier pick) — `to_subject`, the vocabulary `FightEffect` reads.
_ATTACH_WHAT = rf"(?:(?P<any_number>any number of )(?P<multi>target equipment(?: you control)?)|{TARGET})"
_ATTACH_TO_TARGET_KINDS: frozenset[str] = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control", "other_creature_you_control"}
)
_ATTACH_WHAT_KINDS: frozenset[str] = frozenset({
    "equipment", "equipment_you_control", "equipment_you_dont_control", "equipment_that_player_controls",
})


def _attach_what_params(m: re.Match[str]) -> Optional[dict]:
    """The moved Equipment's half of an `attach_chosen` clause."""
    if m.group("multi"):
        kind = resolve_target_kind(m.group("multi"))
        params: dict = {"what_count": ANY_NUMBER_TARGET_CAP, "what_optional": True}
    else:
        kind = resolve_target_kind(m.group("target"))
        params = {"what_optional": True} if target_is_optional(m) else {}
    if kind not in _ATTACH_WHAT_KINDS:
        return None
    return {"what_kind": kind, **params}


def _attach_chosen_to_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _attach_what_params(m)
    to_kind = resolve_target_kind(m.group("target_b"))
    if params is None or not target_kind_allowed(to_kind, _ATTACH_TO_TARGET_KINDS):
        return None
    params["to_kind"] = to_kind
    if target_is_optional(m, "_b"):
        params["to_optional"] = True
    filt = resolve_target_creature_state_filter(m.group("target_b"))
    if filt:
        params["creature_filter"] = filt
    return [EffectSpec("attach_chosen", params)]


def _attach_chosen_to_subject(subject: str):
    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        params = _attach_what_params(m)
        if params is None:
            return None
        return [EffectSpec("attach_chosen", {**params, "to_subject": subject})]

    return build


_ATTACH_CHOSEN_TO_TARGET_RE = compile_clause(rf"attach {_ATTACH_WHAT} to {target_macro('_b')}")
_ATTACH_CHOSEN_TO_SOURCE_RE = compile_clause(rf"attach {_ATTACH_WHAT} to ~")
_ATTACH_CHOSEN_TO_PRONOUN_RE = compile_clause(rf"attach {_ATTACH_WHAT} to (?:it|her|him)")
_ATTACH_CHOSEN_TO_THAT_RE = compile_clause(rf"attach {_ATTACH_WHAT} to (?:it|that creature)")
_ATTACH_CHOSEN_TO_IT_RE = compile_clause(rf"attach {_ATTACH_WHAT} to it")

#: RULE 109.5's "**another** target creature", which means one of two
#: different things depending on who the *other* fighter is:
#:
#: * against an **implicit** fighter (the source, an Aura's host) it excludes
#:   that permanent — already what the engine's plain ``creature`` kind means
#:   (`targeting.legal_targets` unconditionally drops the ability's own
#:   source), and `_another_kind` narrows a "…you control" phrase to the
#:   dedicated `other_creature_you_control` kind for the same reason;
#: * against a **chosen** fighter (the two-target form, or a pronoun pointing
#:   back at the previous clause's pick) it excludes *that target*, which is
#:   `TargetSpec.distinct_from_others` — an across-requirements constraint,
#:   enforced at offer time by the board and backstopped in `FightEffect`.
_ANOTHER = r"(?P<another>another )?"

#: The same phrase in the second slot of a two-target clause ("target
#: creature you control fights **another** target creature"), where the
#: group has to carry its own name.
_ANOTHER_B = r"(?P<another_b>another )?"


def _another_kind(kind: str) -> str:
    """RULE 109.5 against an implicit fighter: "another target creature you
    control" is the `other_creature_you_control` kind; a bare "another target
    creature" needs no narrowing (``creature`` already excludes the source)."""
    return "other_creature_you_control" if kind == "creature_you_control" else kind


def _fight(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    fighter = fight_kind(m.group("target"))
    other = fight_kind(m.group("target_b"))
    if fighter is None or other is None:
        return None
    params: dict = {"fighter_kind": fighter, "other_kind": other}
    if target_is_optional(m):
        params["fighter_optional"] = True
    if target_is_optional(m, "_b"):
        params["optional"] = True
    if m.groupdict().get("another_b"):
        params["distinct"] = True
    return [EffectSpec("fight", params)]


def _fight_implicit(fighter_kind: Optional[str]):
    """Builder for the three clauses whose fighter isn't chosen: the source
    (``None``), an Aura's host (``"attached_permanent"``), or the previous
    clause's target (``"previous_target"``). Only the *other* creature is a
    RULE 115 requirement, so the whole clause is one target wide."""

    def build(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
        other = fight_kind(m.group("target"))
        if other is None:
            return None
        params: dict = {"other_kind": other, **optional_param(m)}
        if m.groupdict().get("same_mv"):
            # "…with the same mana value" as the group trigger's firing object (Boxing Ring): a
            # target filter read off the trigger's event, so only under a group trigger.
            if not reading.group_clause:
                return None
            params["other_exact_mana_value"] = "trigger_subject_mana_value"
        if fighter_kind is not None:
            params["fighter_kind"] = fighter_kind
        if m.groupdict().get("another"):
            # "Another" than a *chosen* previous target is a cross-requirement
            # exclusion; than the source/host it's just the narrower kind.
            if fighter_kind == "previous_target":
                params["distinct"] = True
            else:
                params["other_kind"] = _another_kind(other)
        return [EffectSpec("fight", params)]

    return build


def _fight_chosen_vs_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    fighter = fight_kind(m.group("target"))
    if fighter is None:
        return None
    return [EffectSpec("fight", {
        "fighter_kind": fighter, "other_kind": "previous_target", **optional_param(m),
    })]


def _fight_previous_pair(m: re.Match[str]) -> list[EffectSpec]:
    """"Then those creatures fight each other." — both fighters come from the
    preceding "choose target … and target …" clause, so this clause announces
    no requirement of its own at all."""
    return [
        EffectSpec(
            "fight",
            {"fighter_kind": "previous_target", "other_kind": "previous_target_2"},
        )
    ]
_FIGHT_TWO_TARGETS_RE = compile_clause(rf"{TARGET} fights {_ANOTHER_B}{TARGET_B}")
_FIGHT_SELF_RE = compile_clause(rf"(?:have )?{re.escape(SELF)} fights? {_ANOTHER}{TARGET}")
# "it" / a personified legendary's "he"/"she"/"they" — all name the source
# creature (RULE 109.5), never a player (MTG writes "they" for players only
# as a *subject of a player action*, never "they fight"). Wolverine, Fierce
# Fighter: "When Wolverine enters, he fights up to one other target creature."
_FIGHT_PRONOUN_RE = compile_clause(rf"(?:have )?(?:it|he|she|they) fights? {_ANOTHER}{TARGET}")
_FIGHT_ATTACHED_RE = compile_clause(rf"(?:have )?{ATTACHED_SUBJECT} fights? {_ANOTHER}{TARGET}")
_FIGHT_PREVIOUS_RE = compile_clause(
    rf"{THEN}(?:have )?{PREVIOUS_SUBJECT} fights? {_ANOTHER}{TARGET}(?P<same_mv> with the same mana value)?"
)

#: "Choose target creature an opponent controls. … **Target creature you control fights that creature.**" (Time to
#: Feed) — the mirror of `_FIGHT_PREVIOUS_RE`: the *fighter* is a new RULE 115 requirement and the *other* creature is
#: the earlier clause's pick, so the clause announces exactly one target of its own.
_FIGHT_CHOSEN_OTHER_PREVIOUS_RE = compile_clause(rf"{THEN}{TARGET} fights {PREVIOUS_SUBJECT}")

#: Predatory Urge's pre-keyword-action wording for a fight.  The two damage
#: sentences have RULE 701.14a's exact simultaneous semantics, so they must
#: become one atomic `fight`, not two `damage_equal_to_power` effects.
_FIGHT_DAMAGE_EQUIVALENT_RE = compile_clause(
    rf"(?:{re.escape(SELF)}|this creature|it) deals? damage equal to its power to target creature\.\s*"
    rf"that creature deals? damage equal to its power to (?:{re.escape(SELF)}|this creature|it)"
)

#: RULE 701.14 fight, in its four printed subjects: two chosen creatures
#: ("target creature you control fights target creature you don't
#: control"), the source itself written as ``~`` or as "it", and an Aura's
#: host ("enchanted creature fights …"), plus the fifth "pronoun pointing
#: back at an earlier clause" form ("… gets +1/+2 until end of turn. **It**
#: fights target creature you don't control.", offered only when the caller
#: says an earlier clause in this same body actually chose a creature —
#: `EffectHandler.previous_subject_only`). The "it" row is
#: `self_subject_only` — see `EffectHandler`. Grammar/builders differ enough
#: per row (the "have"/"another" wording, which kind-resolver applies) that
#: only the repetitive `EffectHandler(...)` registration itself is factored
#: into this row table, not the regexes/builders behind it.
_FIGHT_ROW_SPECS: list[tuple[str, "re.Pattern[str]", Any, dict]] = [
    (
        "fight_damage_equivalent", _FIGHT_DAMAGE_EQUIVALENT_RE,
        lambda m: [EffectSpec("fight", {"other_kind": "creature"})],
        {},
    ),
    ("fight", _FIGHT_TWO_TARGETS_RE, _fight, {}),
    ("fight_self", _FIGHT_SELF_RE, _fight_implicit(None), {"reading_aware": True}),
    ("fight_pronoun", _FIGHT_PRONOUN_RE, _fight_implicit(None),
     {"requires": ClauseReading(self_subject=True), "reading_aware": True}),
    ("fight_attached", _FIGHT_ATTACHED_RE, _fight_implicit("attached_permanent"), {"reading_aware": True}),
    (
        "fight_previous", _FIGHT_PREVIOUS_RE, _fight_implicit("previous_target"),
        {"requires": ClauseReading(previous_subject=True), "reading_aware": True},
    ),
    (
        "fight_chosen_vs_previous", _FIGHT_CHOSEN_OTHER_PREVIOUS_RE, _fight_chosen_vs_previous,
        {"requires": ClauseReading(previous_subject=True)},
    ),
]

_FIGHT_PREVIOUS_PAIR_RE = compile_clause(
    rf"{THEN}(?:those|the chosen) creatures fight each other"
)
#: "Put a +1/+1 counter on target creature. **It** phases out." (Slip Out
#: the Back) — the same previous-clause pronoun `_FIGHT_PREVIOUS_RE` uses,
#: for `PhaseOutEffect.previous_subject` instead of a fight.
_PHASE_OUT_PREVIOUS_RE = compile_clause(rf"{THEN}{PREVIOUS_SUBJECT} phases? out")


def _phase_out_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("phase_out", {"previous_subject": True})]


#: RULE 702.26 "~ phases out." (Blink Dog/Vaporous Djinn/Crystal Golem-
#: shaped — the source phasing out *itself*) — `PhaseOutEffect.self_target`,
#: distinct from the plain untargeted default below (Robe of Stars' own
#: Equipment-hosted "equipped creature phases out", reached by
#: `_phase_out_attached` instead).
_PHASE_OUT_SELF_RE = compile_clause(r"~ phases? out")
#: "Enchanted/equipped creature phases out." (Vanishing) — the untargeted
#: default `PhaseOutEffect` already had (Robe of Stars' own hand-authored
#: shape, `EffectSpec("phase_out", {})`), just reached from oracle text now.
_PHASE_OUT_ATTACHED_RE = compile_clause(rf"{ATTACHED_SUBJECT} phases? out")
#: "Target creature phases out." / "Target artifact, creature, or land
#: phases out." / "Target creature you control phases out." / "Target
#: creature or planeswalker an opponent controls phases out." (Reality
#: Ripple/Vodalian Illusionist/Haystack/Divine Smite-shaped) — a genuine
#: RULE 115 target, so an opponent's own permanent is exactly as legal a
#: target as your own whenever the printed phrase says so (no engine
#: restriction ever scoped this to "your own permanents" — `PhaseOutEffect`
#: just forwards whatever `target_kind` `resolve_target_kind` resolves).
_PHASE_OUT_TARGET_RE = compile_clause(rf"{TARGET} phases? out")


def _phase_out_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("phase_out", {"self_target": True})]


def _phase_out_attached(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("phase_out", {})]


def _phase_out_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind}
    if target_is_optional(m):
        params["optional"] = True
    return [EffectSpec("phase_out", params)]


#: RULE 500.4-adjacent "after this phase, there is an additional combat
#: phase." (Combat Celebrant/Godo/Aurelia-shaped, `normalize` folds "this
#: combat phase" to the bare "this phase" self-reference every printing of
#: this clause uses) / World at War/Aggravated Assault's own longer
#: "after this main phase, there is an additional combat phase followed by
#: an additional main phase." — `ExtraCombatPhaseEffect`'s `main_phase_too`
#: flag is what tells the two apart. The subject-first word order ("there
#: is an additional combat phase after this phase.", A-Raiyuu, Storm's
#: Edge/Raiyuu-shaped, MEC-28) is the same clause with its two halves
#: swapped — real cache cards print both orderings.
_EXTRA_COMBAT_PHASE_RE = compile_clause(
    r"after this phase, there is an additional combat phase"
    r"|there is an additional combat phase after this phase"
)
_EXTRA_COMBAT_AND_MAIN_PHASE_RE = compile_clause(
    r"after this main phase, there is an additional combat phase followed by an additional main phase"
)


def _extra_combat_phase(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("extra_combat_phase", {})]


def _extra_combat_and_main_phase(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("extra_combat_phase", {"main_phase_too": True})]


#: "gain control of up to three target creatures." (Jace, Ingenious Mind-Mage's -9) -- RULE 611.2 no-duration
#: control change over `GainControlUntilEndOfTurnEffect(duration="permanent")`, one pick per target.
_GAIN_CONTROL_MULTI_RE = compile_clause(rf"gain control of {MULTI_TARGET_QUANTIFIER}(?P<target>{MULTI_TARGET_ALT})")


def _gain_control_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = multi_target_params(m)
    if params is None or not target_kind_allowed(params["target_kind"], _GAIN_CONTROL_PERMANENT_KINDS):
        return None
    params = renamed_target_count(params)
    params.update({"duration": "permanent", "haste": False, "untap": False})
    return [EffectSpec("gain_control_until_eot", params)]


#: "those creatures can't block this turn." (Sontaran General, Sparkmage's Gambit) -- the plural pronoun of
#: `_IF_PREV_CREATURE_CANT_BLOCK_RE`: every creature the previous clause targeted (`CantBlockEffect.previous_subject`).
_CANT_BLOCK_PREVIOUS_PLURAL_RE = compile_clause(r"(?:those creatures|them) can'?t block this turn")


def _cant_block_previous_plural(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("cant_block_this_turn", {"previous_subject": True})]


#: PAR-79 sixth increment: "Put 2 +1/+1 counters on target creature you
#: control. **That creature** can't be blocked this turn." (Stealth
#: Mission/Trygon Prime-shaped) — the same previous-clause pronoun idiom
#: `_PHASE_OUT_PREVIOUS_RE`/`_FIGHT_PREVIOUS_RE` already use, for
#: `UnblockableEffect.previous_subject` instead.
_CANT_BE_BLOCKED_TURN_PREVIOUS_RE = compile_clause(rf"{THEN}{PREVIOUS_SUBJECT} can'?t be blocked this turn")


def _cant_be_blocked_turn_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("unblockable", {"previous_subject": True})]


#: PAR-124: "`<earlier clause targeted/animated a creature>`. **It** must be
#: blocked this turn if able." (Enlarge, King Harald's Revenge, Disturbed
#: Slumber/Elemental Uprising/Vengeant Earth's animate-land family) — the
#: "must" mirror of `_CANT_BE_BLOCKED_TURN_PREVIOUS_RE` just above.
#: "must_be_blocked" is a plain flag keyword (`combat.has`, RULE 509.1c),
#: so the same `PumpEffect.previous_subject`/``keywords`` idiom that already
#: grants it via a standing static (Raphael, Ninja Destroyer) grants it here
#: as a resolve-time temporary keyword instead — no new primitive.
_MUST_BE_BLOCKED_TURN_PREVIOUS_RE = compile_clause(rf"{THEN}{PREVIOUS_SUBJECT} must be blocked this turn if able")


def _must_be_blocked_turn_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {"previous_subject": True, "keywords": ["must_be_blocked"]})]


#: PAR-98: "`<earlier clause targeted creatures>`. **They** can't be blocked
#: this turn except by creatures with haste." (Run for Your Life) — the
#: plural-referent, "except by" sibling of `_CANT_BE_BLOCKED_TURN_PREVIOUS_RE`
#: above. Reads `GameContext.previous_targets` for *every* creature the
#: previous clause chose (RULE 608.2), through `GrantCombatRestrictionEffect`'s
#: new ``previous_subject`` mode.
_CANT_BE_BLOCKED_EXCEPT_PREVIOUS_RE = compile_clause(
    rf"{THEN}(?:{PREVIOUS_SUBJECT}|they|those creatures) can'?t be blocked this turn "
    r"except by (?P<filter>.+)"
)


def _cant_be_blocked_except_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    restriction = except_by_restriction(m.group("filter"))
    if restriction is None:
        return None
    return [EffectSpec("combat_restriction_this_turn", {
        "restriction": restriction, "previous_subject": True,
    })]


#: PAR-98: Agility Bobblehead's "up to X target creatures you control each
#: gain `<keywords>` until end of turn and can't be blocked this turn except by
#: `<filter>`, where X is the number of `<subtype>`s you control as you
#: activate this ability." — one sentence, two effects: a multi-target keyword
#: grant plus the previous-subject "except by" restriction. X is read when the
#: targets are announced (RULE 601.2c — "as you activate"), which is exactly
#: when `TargetSpec.count_selector` is evaluated.
_KW_GRANT_UNBLOCKABLE_EXCEPT_X_RE = compile_clause(
    r"up to x target creatures you control each gains? (?P<kw>[a-z][a-z, ]*?) until end of turn "
    r"and can'?t be blocked this turn except by (?P<filter>.+?), "
    r"where x is the number of (?P<what>[a-z]+?)s you control as you activate this ability"
)


def _kw_grant_unblockable_except_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = token_keywords(m.group("kw"))
    restriction = except_by_restriction(m.group("filter"))
    if keywords is None or restriction is None:
        return None
    return [
        EffectSpec("pump", {
            "keywords": keywords, "target_kind": "creature_you_control", "optional": True,
            "count_selector": f"permanents_you_control_of_type_{m.group('what')}",
        }),
        EffectSpec("combat_restriction_this_turn", {
            "restriction": restriction, "previous_subject": True,
        }),
    ]


ROWS: list[EffectHandler] = [
    # "Its controller may search their library for a basic land card, put
    # it onto the battlefield, then shuffle." (Assassin's Trophy/
    # Geomancer's Gambit/Ghost Quarter — the destroyed permanent's
    # controller, not the caster, gets the ramp).
    EffectHandler(
        "destroy_controller_search_basic_land",
        _DESTROY_CONTROLLER_SEARCH_BASIC_LAND_RE,
        _destroy_controller_search_basic_land,
    ),
    # "search your library for <criteria>, [reveal <pronoun>,] put <pronoun>
    # <destination>, then shuffle." (RULE 701.19 — the general tutor/ramp/
    # fetch family: unrestricted tutors, basic-land fetches, criteria-
    # filtered tutors, "reveal" variants).
    # "search your library for <criteria> that share a land type, ... then
    # shuffle." (Myriad Landscape-shaped cross-pick constraint) — tried
    # before the plain row below since it's a strict superset of it.
    EffectHandler(
        "search_put_then_shuffle_share_type",
        _SEARCH_PUT_THEN_SHUFFLE_SHARE_TYPE_RE,
        _search_put_then_shuffle_share_type,
    ),
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par38_residue.py (a card-specific upkeep body kept for its residue test).
    EffectHandler("elfhame_sanctuary", _ELFHAME_SANCTUARY_RE, _elfhame_sanctuary),
    EffectHandler("search_named_criteria", _SEARCH_NAMED_CRITERIA_RE, _search_named_criteria),
    EffectHandler(
        "search_put_then_shuffle",
        _SEARCH_PUT_THEN_SHUFFLE_RE,
        _search_put_then_shuffle,
    ),
    # "search your library for <criteria>, put it onto the battlefield,
    # attach it to a creature you control, then shuffle." (Stonehewer
    # Giant/Quest for the Holy Relic-shaped combined search-then-attach) —
    # tried before the plain row above since it's a strict superset of it.
    EffectHandler(
        "search_put_attach_then_shuffle",
        _SEARCH_PUT_ATTACH_THEN_SHUFFLE_RE,
        _search_put_attach_then_shuffle,
    ),
    # "search your library for a card with mana value less than or equal to
    # the number of lands you control, ... then shuffle." (Beseech the
    # Queen-shaped board-count mana-value bound).
    EffectHandler(
        "search_mv_lands_qualifier",
        _SEARCH_MV_LANDS_QUALIFIER_RE,
        _search_mv_lands_qualifier,
    ),
    # "search your library for a creature card with lesser mana value, ..." (Rushed Rebirth).
    EffectHandler("search_lesser_mv", _SEARCH_LESSER_MV_RE, _search_lesser_mv),
    # "return a creature card from its owner's graveyard to the battlefield under the control of that creature's
    # owner." (Reincarnation).
    EffectHandler(
        "return_creature_to_dead_creature_owner", _RETURN_CREATURE_TO_DEAD_OWNER_RE,
        lambda m: [EffectSpec("return_creature_to_dead_creature_owner", {})],
    ),
    # "search your library for a snow permanent card, a legendary card, or
    # a Saga card, ... then shuffle." (Search for Glory's own three-way OR
    # criteria).
    EffectHandler(
        "search_snow_legendary_saga",
        _SEARCH_SNOW_LEGENDARY_SAGA_RE,
        _search_snow_legendary_saga,
    ),
    # "You gain 1 life for each {S} spent to cast this spell." (Search for
    # Glory's own trailing sentence).
    EffectHandler(
        "gain_life_per_snow_spent",
        _GAIN_LIFE_PER_SNOW_SPENT_RE,
        _gain_life_per_snow_spent,
    ),
    # "search your library for <criteria>, [reveal <pronoun>,] then shuffle
    # and put <pronoun> on top." (the reordered shuffle-then-put-on-top
    # tutors — Vampiric/Mystical/Enlightened/Worldly Tutor).
    EffectHandler(
        "search_shuffle_then_put_top",
        _SEARCH_SHUFFLE_THEN_PUT_TOP_RE,
        _search_shuffle_then_put_top,
    ),
    # "search your library for up to N basic land cards, reveal those cards,
    # put one <destA> and the other <destB>, then shuffle." (Cultivate/
    # Kodama's Reach-shaped split destination).
    EffectHandler(
        "search_split_destination",
        _SEARCH_SPLIT_DESTINATION_RE,
        _search_split_destination,
    ),
    # "search your library for N cards. Put 1 <destA> and the other
    # <destB>. Then shuffle." (Final Parting-shaped three-sentence split
    # destination, no criteria).
    EffectHandler(
        "search_two_cards_split",
        _SEARCH_TWO_CARDS_SPLIT_RE,
        _search_two_cards_split,
    ),
    # "search your library and/or graveyard for <criteria>, [reveal
    # <pronoun>,] put <pronoun> <destination>. If you search[ed] your
    # library this way, shuffle." (the backgrounds/planeswalker-tutor
    # combined-zone family).
    EffectHandler(
        "search_zone_put",
        _SEARCH_ZONE_PUT_RE,
        _search_zone_put,
    ),
    # "search your library [and graveyard] for N cards and exile the rest.
    # Put the chosen cards on top of your library in any order."
    # (Doomsday-shaped).
    EffectHandler(
        "search_exile_rest",
        _SEARCH_EXILE_REST_RE,
        _search_exile_rest,
    ),
    # "Shuffle ~ into its owner's library." (Green Sun's Zenith's own
    # trailing sentence, overriding the spell's default graveyard routing).
    EffectHandler(
        "shuffle_self_into_library",
        _SHUFFLE_SELF_INTO_LIBRARY_RE,
        _shuffle_self_into_library,
    ),
    # ENG-32 (Watery Grasp): "Enchanted creature's owner shuffles it into
    # their library."
    EffectHandler(
        "shuffle_enchanted_into_library",
        _SHUFFLE_ENCHANTED_INTO_LIBRARY_RE,
        _shuffle_enchanted_into_library,
    ),
    # "An opponent gains control of ~." (Wishclaw Talisman's own drawback
    # clause).
    EffectHandler(
        "gain_control_by_opponent",
        _GAIN_CONTROL_BY_OPPONENT_RE,
        _gain_control_by_opponent,
        reading_aware=True,
    ),
    # "gain control of target creature [with mana value N or less] until
    # end of turn" (Act of Treason/Claim the Firstborn-shaped threaten
    # effect).
    EffectHandler(
        "gain_control_eot",
        _GAIN_CONTROL_EOT_RE,
        _gain_control_eot,
    ),
    # PAR-150: "gain control of ... for as long as you control ~" (RULE 611.2b; Rangers of Ithilien).
    EffectHandler("gain_control_while_source", _GAIN_CONTROL_WHILE_SOURCE_RE, _gain_control_while_source),
    EffectHandler("tap_and_fight", _TAP_AND_FIGHT_RE, _tap_and_fight),
    EffectHandler("gain_control_while_tapped", _GAIN_CONTROL_WHILE_TAPPED_RE, _gain_control_while_tapped),
    # PAR-150: "gain control of up to three target creatures" (no duration; Jace, Ingenious Mind-Mage).
    EffectHandler("gain_control_multi_target", _GAIN_CONTROL_MULTI_RE, _gain_control_multi),
    # "gain control of target <permanent> [. untap it]" with no duration —
    # the RULE 611.2 indefinite steal (Keiga, Blatant Thievery; PAR-130).
    EffectHandler(
        "gain_control_permanent",
        _GAIN_CONTROL_PERMANENT_RE,
        _gain_control_permanent,
    ),
    # "Untap all creatures and gain control of them until end of turn. They
    # gain haste until end of turn." (Insurrection's own mass threaten).
    EffectHandler(
        "gain_control_all",
        _GAIN_CONTROL_ALL_RE,
        _gain_control_all,
    ),
    # "For each opponent, gain control of up to 1 target creature that player
    # controls until end of turn. Untap those creatures. They gain haste …"
    # (Mass Mutiny / Molten Primordial) — one requirement per opponent.
    EffectHandler(
        "gain_control_eot_per_opponent",
        _GAIN_CONTROL_EOT_PER_OPPONENT_RE,
        _gain_control_eot_per_opponent,
    ),
    # "Gain control of all <type> [your opponents / target opponent]
    # control[s] until end of turn. Untap them. They gain haste …"
    # (Broadcast Takeover, Call for Aid) — the opponent-scoped mass threaten.
    EffectHandler(
        "gain_control_mass_eot",
        _GAIN_CONTROL_MASS_EOT_RE,
        _gain_control_mass_eot,
    ),
    EffectHandler('gain_control_group', _GAIN_CONTROL_GROUP_RE, _gain_control_group),
    # "that player copies it and may choose new targets for the copy [until
    # end of turn]" (Bonus Round's own trigger body).
    EffectHandler(
        "trigger_copy_spell",
        _TRIGGER_COPY_SPELL_RE,
        _trigger_copy_spell,
    ),
    EffectHandler(
        "targeted_stack_copy",
        _TARGETED_STACK_COPY_RE,
        _targeted_stack_copy,
    ),
    # "Each instant and sorcery card in your graveyard gains flashback until
    # end of turn. The flashback cost is equal to its mana cost." (Past in
    # Flames-shaped).
    EffectHandler(
        "grant_flashback_each",
        _GRANT_FLASHBACK_EACH_RE,
        _grant_flashback_each,
    ),
    # "Target instant or sorcery card in your graveyard gains flashback
    # [<cost>] until end of turn[. The flashback cost is equal to its mana
    # cost.]" (MEC-24, Recoup/Snapcaster Mage-shaped).
    EffectHandler(
        "target_graveyard_cast", _TARGET_GRAVEYARD_CAST_RE, _target_graveyard_cast,
    ),
    EffectHandler(
        "grant_flashback_target",
        _GRANT_FLASHBACK_TARGET_RE,
        _grant_flashback_target,
    ),
    # "The next [creature] spell you cast this turn can't be countered." (Mistrise Village,
    # Insist, Overmaster) / "Spells you control can't be countered this turn." (Veil of Summer).
    EffectHandler(
        "cant_be_countered_this_turn",
        _UNCOUNTERABLE_THIS_TURN_RE,
        _cant_be_countered_this_turn,
    ),
    # "Look at the top card of target player's library."/"Look at a card at
    # random in target player's hand." (Mishra's/Urza's Bauble).
    EffectHandler(
        "look_at_target",
        _LOOK_AT_TARGET_RE,
        _look_at_target,
    ),
    # "attach it to target creature you control" / "attach ~ to target
    # creature you control" (an Equipment's own ETB self-attach).
    EffectHandler(
        "attach",
        compile_clause(rf"attach (?:it|{re.escape(SELF)}) to {TARGET}"),
        _attach,
    ),
    # PAR-135: a *chosen* Equipment onto a chosen creature, or onto a non-target subject.
    EffectHandler("attach_chosen_to_target", _ATTACH_CHOSEN_TO_TARGET_RE, _attach_chosen_to_target),
    EffectHandler(
        "attach_chosen_to_source", _ATTACH_CHOSEN_TO_SOURCE_RE, _attach_chosen_to_subject("source"),
    ),
    *subject_handlers([
        ("attach_chosen_to_self_pronoun", "self", _ATTACH_CHOSEN_TO_PRONOUN_RE, _attach_chosen_to_subject("source")),
        ("attach_chosen_to_group_subject", "group", _ATTACH_CHOSEN_TO_THAT_RE,
         _attach_chosen_to_subject("trigger_subject")),
        ("attach_chosen_to_previous", "previous", _ATTACH_CHOSEN_TO_THAT_RE,
         _attach_chosen_to_subject("previous_target")),
        ("attach_chosen_to_attached_host", "attached", _ATTACH_CHOSEN_TO_IT_RE,
         _attach_chosen_to_subject("attached_permanent")),
    ]),
    # RULE 701.14 fight, in its four printed subjects: two chosen creatures
    # ("target creature you control fights target creature you don't
    # control"), the source itself written as ``~`` or as "it", and an Aura's
    # host ("enchanted creature fights …"). The "it" row is
    # `self_subject_only` — see `EffectHandler`.
    # (grammar/builder logic unchanged — only the repetitive EffectHandler(...)
    # calls below were collapsed into one row table, see `_FIGHT_ROW_SPECS`).
    *(
        EffectHandler(name, regex, build, **flags)
        for name, regex, build, flags in _FIGHT_ROW_SPECS
    ),
    EffectHandler(
        "fight_previous_pair", _FIGHT_PREVIOUS_PAIR_RE, _fight_previous_pair,
        requires=ClauseReading(previous_subject=True),
    ),
    # "Put a +1/+1 counter on target creature. It phases out." (Slip Out
    # the Back) — the same previous-clause pronoun idiom as the fight
    # family just above, for a phase-out instead.
    EffectHandler(
        "phase_out_previous", _PHASE_OUT_PREVIOUS_RE, _phase_out_previous,
        requires=ClauseReading(previous_subject=True),
    ),
    # PAR-79 sixth increment: "…target creature… **that creature** can't be
    # blocked this turn." (Stealth Mission/Trygon Prime-shaped).
    EffectHandler(
        "cant_block_previous_plural", _CANT_BLOCK_PREVIOUS_PLURAL_RE, _cant_block_previous_plural,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "cant_be_blocked_turn_previous", _CANT_BE_BLOCKED_TURN_PREVIOUS_RE,
        _cant_be_blocked_turn_previous, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "must_be_blocked_turn_previous", _MUST_BE_BLOCKED_TURN_PREVIOUS_RE,
        _must_be_blocked_turn_previous, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "cant_be_blocked_except_previous", _CANT_BE_BLOCKED_EXCEPT_PREVIOUS_RE,
        _cant_be_blocked_except_previous, requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "kw_grant_unblockable_except_x", _KW_GRANT_UNBLOCKABLE_EXCEPT_X_RE,
        _kw_grant_unblockable_except_x,
    ),
    # RULE 702.26 "~ phases out." (Blink Dog/Vaporous Djinn-shaped) / the
    # attached-permanent sibling "enchanted/equipped creature phases out."
    # (Vanishing) / a genuine RULE 115 target (Reality Ripple/Divine Smite,
    # including an opponent-controlled one) — tried in "most specific
    # subject first" order like every other family here.
    EffectHandler("phase_out_self", _PHASE_OUT_SELF_RE, _phase_out_self),
    EffectHandler("phase_out_attached", _PHASE_OUT_ATTACHED_RE, _phase_out_attached),
    EffectHandler("phase_out_target", _PHASE_OUT_TARGET_RE, _phase_out_target),
    # RULE 500.4-adjacent "after this [main] phase, there is an additional
    # combat phase[ followed by an additional main phase]." (Combat
    # Celebrant/Godo/Aurelia-shaped; World at War/Aggravated Assault's own
    # longer form) — tried longer-form-first, same "most specific first"
    # convention as everywhere else in this table.
    EffectHandler(
        "extra_combat_and_main_phase", _EXTRA_COMBAT_AND_MAIN_PHASE_RE, _extra_combat_and_main_phase
    ),
    EffectHandler("extra_combat_phase", _EXTRA_COMBAT_PHASE_RE, _extra_combat_phase),
    EffectHandler(
        'additional_end_step',
        compile_clause(r"(?:(?:then )?if it's the first end step of the turn, )?there is an additional end step after this step"),
        lambda m: [EffectSpec('additional_end_step', {'only_first': 'first end step' in m.group(0)})],
    ),
]
