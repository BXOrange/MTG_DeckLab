"""Unblockable, becomes/animate, suspect, manifest, proliferate and token-creation rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import json
import re

from typing import Any, Optional
from ..duration_phrase import FIXED_DURATIONS, FIXED_DURATION_PATTERN
from ..clause_hooks import segment_line
from ..clause_reading import ClauseReading
from ..clause_primitives import split_keywords_with_parametric
from ..count_phrase import parse_amount_phrase, parse_count_phrase
from ..emblem_bodies import emblem_body_spec
from ..emblem_statics import emblem_static_effect_specs
from ..static_handlers import static_effect_specs, type_addition_params, quoted_ability_grant_effects_list, flag_keywords_and_ward
from ..subgrammars import (
    COLOR_LETTERS,
    COUNT,
    count_of,
    count_or_x_of,
    COUNT_X,
    DEVOTION,
    devotion_selector,
    resolve_target_kind,
    subtype_count_selector,
    TARGET,
    target_kind_allowed,
)
from .....models.cards.creature_types import CREATURE_SUBTYPES
from ...normalize import SELF
from ...spec import AbilitySpec, EffectSpec, ParserProvenance
from ..clause_hooks import match_clause, match_clause_once
from .shared import (
    BIA_KEYWORD,
    BIA_KEYWORD_LIST,
    compile_clause,
    CREATURE_FILTER_KEYWORD_WORDS,
    EffectHandler,
    MULTI_TARGET_ALT,
    multi_target_params,
    MULTI_TARGET_QUANTIFIER,
    NAMED_COUNTER_KIND,
    NAMED_TOKEN_WORDS,
    optional_param,
    SELF_SUBJECT,
    split_token_mid_words,
    token_keywords,
    xx_token_mid_params,
)


#: PAR-98 (Riftmarked Knight): "…token with flanking, protection from white,
#: and haste" — RULE 702.16's protection is a *quality*, not a flag keyword, so
#: it can't ride the keyword list. It is carried as the token's own oracle text
#: instead (`combat.protections_of_text` reads exactly that off a synthesized
#: token, `CreateTokenEffect.oracle_text`), and the remaining flag keywords keep
#: their usual route.
_TOKEN_PROTECTION_PART_RE = re.compile(r"protection from (white|blue|black|red|green)")


def _split_token_protection(text: str) -> tuple[str, str]:
    """A token's "with …" list → ``(keywords-without-protection, oracle text)``."""
    kept: list[str] = []
    protections: list[str] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        pm = _TOKEN_PROTECTION_PART_RE.fullmatch(part)
        if pm:
            protections.append(f"Protection from {pm.group(1)}")
        else:
            kept.append(part)
    return ", ".join(kept), "\n".join(protections)


#: "…token that's tapped and attacking" / "…tokens that are tapped and
#: attacking" (RULE 508.4 — Captain's Claws, Basri Ket, Anim Pakal, the
#: whole "whenever ~ attacks, make a token" family). An optional suffix on
#: the inline-token regexes; `CreateTokenEffect` handles the tap + the
#: `RulesEngine.put_onto_battlefield_attacking` call.
_TOKEN_TAPPED_ATTACKING = (
    r"(?P<tapped_attacking> that'?s tapped and attacking| that are tapped and attacking)?"
    # RULE 508.4: a trailing "that player"/"that opponent" names the defender
    # the source is already attacking (Seraphic Greatsword, Soaring
    # Lightbringer) — `put_onto_battlefield_attacking` derives it from the
    # other attackers, so this is consumed rather than re-modeled. The
    # per-opponent distributive form ("for each opponent, create … attacking
    # that player") isn't reached here — the connector loop leaves that
    # "for each opponent, " prefix on the clause and the create-token rows
    # never fullmatch it.
    r"(?P<atk_defender> that (?:player|opponent))?"
    # PAR-148 (RULE 508.4a): "…that player or a planeswalker they control" (Adeline) — the controller may
    # pick a planeswalker of the player the creature was put in against.
    r"(?P<atk_walker> that (?:player|opponent) or a planeswalker they control)?"
)


#: RULE 105.1: the five colors, in WUBRG order — a token that is "all colors".
_ALL_COLORS = ("W", "U", "B", "R", "G")


#: Words that cannot be part of a printed token name: the lazy ``tname`` capture swallowing a trailing
#: timing/duration/measure clause means the clause is some other shape, which stays unclaimed.
_TOKEN_NAME_TAIL_WORDS_RE = re.compile(
    r"\b(?:at|until|that|where|for|equal|with|has|it|and|then|if)\b", re.IGNORECASE,
)


def _inline_create_token_params(m: re.Match[str]) -> Optional[dict]:
    """The shared ``create_token`` params for the inline-stats creature-token
    grammar (``p``/``t``/``mid``/``kw``/``n``/``tapped``/``legendary``/``who``
    groups) — factored out of `_create_token` so `_create_token_and_attach`
    can build the same params for its own, differently-wrapped clause."""
    colors, subtypes, is_artifact = split_token_mid_words(m.group("mid") or "")
    keywords: list[str] = []
    parametric_keywords: list[dict[str, object]] = []
    protection_text = ""
    if m.groupdict().get("kw"):
        kw_text, protection_text = _split_token_protection(m.group("kw"))
        split = split_keywords_with_parametric(kw_text)
        if split is None:
            return None  # unrecognised "with …" ability → fail-closed
        keywords, parametric_keywords = split
    params: dict = {
        # PAR-124: "create **X** 2/2 red Human Knight creature tokens with
        # trample and haste." (Forth Eorlingas!) — `count_or_x_of`'s ``"x"``
        # sentinel, resolved by the generic `_substitute_x` per-attr loop
        # (`CreateTokenEffect.count`) the same way any other effect's own
        # ``count``/``amount`` already is; every existing caller's own
        # ``n`` group only ever captures a plain number/"a"/"an", so this is
        # a no-op widening for them.
        "count": count_or_x_of(m.group("n")),
        "power": int(m.group("p")),
        "toughness": int(m.group("t")),
        "colors": colors,
        "subtypes": subtypes,
        "keywords": keywords,
    }
    if parametric_keywords:  # ENG-31: "… token with firebending N"
        params["parametric_keywords"] = parametric_keywords
    if protection_text:
        params["oracle_text"] = protection_text
    quoted_cda = m.groupdict().get("quoted_cda")
    if quoted_cda:
        # RULE 604.3: a token owns its quoted CDA. Validate the whole ability
        # before preserving it as the new card's oracle text.

        normalized = re.sub(r"^(?:this token|this creature)'s", "~'s", quoted_cda, flags=re.I)
        parsed = static_effect_specs(normalized)
        if not parsed or len(parsed) != 1 or parsed[0].type != "pt_cda":
            return None
        params["oracle_text"] = "\n".join(filter(None, (protection_text, quoted_cda)))
    if m.groupdict().get("dies_life"):
        # STX Pest — "with \"when ~ dies, you gain N life.\""
        params["token_dies_gain_life"] = int(m.group("dies_life"))
    if m.groupdict().get("all_colors"):
        params["colors"] = list(_ALL_COLORS)
    if is_artifact:
        params["is_artifact"] = True
    if subtypes:
        params["token_name"] = " ".join(subtypes)
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    # "**Each player** creates …" / "**each opponent** creates …" — everyone
    # gets their own ``count`` tokens under their own control, rather than
    # the effect's controller getting them all.
    who = (m.groupdict().get("who") or "").strip().lower()
    if "each" in who:
        # "**Each player** / **each opponent** creates …" — only the "each …"
        # phrasings mean everyone; a captured "you" is the ordinary
        # controller-scoped default, not a `creators` override.
        params["creators"] = "each_opponent" if "opponent" in who else "each_player"
    elif who.startswith("target "):
        # "**Target opponent** creates …" (the Hunted cycle) — the chosen
        # player makes the tokens under their own control.
        params["creators"] = "target"
        params["target_kind"] = "opponent" if who == "target opponent" else "player"
    if m.groupdict().get("per_opp"):
        # "**For each opponent**, [you] create a … token[ that's tapped and
        # attacking that opponent]." (Endless Foot Assault, Stampede Surfer)
        # — the controller makes one token per opponent; with `attacking`
        # each is put into combat against a distinct opponent.
        params["per_opponent"] = True
    if m.groupdict().get("tapped"):  # RULE 110.5a — enters tapped, not tapped after
        params["tapped"] = True
    if m.groupdict().get("tapped_attacking") or m.groupdict().get("pre_ta"):  # RULE 508.4 — enters tapped and attacking
        params["tapped"] = True
        params["attacking"] = True
    if m.groupdict().get("atk_walker"):
        params["defender_planeswalker"] = True
    tname = m.groupdict().get("tname")
    if tname:  # PAR-148: the printed name replaces the subtype-derived one (RULE 111.4)
        if _TOKEN_NAME_TAIL_WORDS_RE.search(tname):
            return None  # "named Butterfly at the beginning of the next end step": the name stops before the timing
        params["token_name"] = tname.strip().title()
    token_ab = m.groupdict().get("token_ab")
    if token_ab:
        # RULE 201.5: a creating card's folded name is not the token's name.
        if re.search(r"\bnamed ~", token_ab, re.I):
            return None

        # RULE 111.3: this is the token's own printed ability, not an
        # ability re-granted to another object. Validate its native scope.
        ability = segment_line(token_ab.rstrip(" ,.;"), allow_spell_effect=False,
                               provenance=ParserProvenance())
        if not ability.claimed or (ability.spec is None and not ability.mana_ability):
            return None  # an ability nothing models would leave the token silently without it
        params["oracle_text"] = "\n".join(filter(None, (params.get("oracle_text"), ability.native_oracle_text)))
    return params


def _create_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    return [EffectSpec("create_token", params)]


def _create_tokens_count_plus(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    group = parse_count_phrase(m.group("group"))
    if group is None:
        return None
    # Reuse the ordinary token grammar for all independent token axes.
    tokens = match_clause(m.group("create").replace("create x ", "create 1 ", 1))
    if tokens is None or len(tokens) != 1 or tokens[0].type != "create_token":
        return None
    return [EffectSpec("bind", {
        "name": "tokens", "amount": {"kind": "count_selector", "selector": group,
                                      "plus": int(m.group("plus"))},
        "effects": [{"type": "create_token", "params": {**tokens[0].params, "count": "$tokens"}}],
    })]


_CREATE_TOKEN_QUOTED_CDA_RE = compile_clause(
    rf"(?P<who>each player |each opponent )?creates? {COUNT} "
    r"(?P<mid>[a-z ]*?)creature tokens? with (?:(?P<kw>[a-z ]+?) and )?"
    r'"(?P<cda>(?:this token|this creature|~)\'?s power[^\"]+)"'
)


def _create_token_quoted_cda(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # A */* token prints its P/T only in the quoted characteristic-defining
    # ability. Zero is a placeholder; the bound CDA defines both values in
    # layer 7a as soon as the token enters (RULE 604.3/613.7).

    oracle = m.group("cda")
    normalized = re.sub(r"^(?:this token|this creature)'s", "~'s", oracle, flags=re.I)
    parsed = static_effect_specs(normalized)
    if not parsed or len(parsed) != 1 or parsed[0].type != "pt_cda":
        return None
    colors, subtypes, is_artifact = split_token_mid_words(m.group("mid"))
    if not subtypes:
        return None
    params: dict[str, Any] = {
        "count": count_of(m.group("n")), "power": 0, "toughness": 0,
        "colors": colors, "subtypes": subtypes,
        "token_name": " ".join(subtypes), "oracle_text": oracle,
    }
    if m.group("kw"):
        keywords = token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    if is_artifact:
        params["is_artifact"] = True
    who = m.group("who") or ""
    if who:
        params["creators"] = "each_opponent" if "opponent" in who else "each_player"
    return [EffectSpec("create_token", params)]


_CREATE_NAMED_TOKEN_QUOTED_CDA_RE = compile_clause(
    r"create (?P<name>[a-z][a-z' -]*), a legendary (?P<mid>[a-z ]*?)"
    r'creature token with "(?P<cda>[^\"]+)"'
)


def _create_named_token_quoted_cda(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    name, oracle = m.group("name").strip(), m.group("cda")
    normalized = re.sub(rf"^{re.escape(name)}'s", "~'s", oracle, flags=re.I)
    parsed = static_effect_specs(normalized)
    if not parsed or len(parsed) != 1 or parsed[0].type != "pt_cda":
        return None
    colors, subtypes, is_artifact = split_token_mid_words(m.group("mid"))
    if not subtypes:
        return None
    return [EffectSpec("create_token", {
        "count": 1, "power": 0, "toughness": 0,
        "colors": colors, "subtypes": subtypes, "token_name": name,
        "oracle_text": oracle, "legendary": True,
        **({"is_artifact": True} if is_artifact else {}),
    })]


#: "Create that many 1/1 green Elf Warrior creature tokens." (Lathril,
#: Blade of the Elves-shaped "whenever ~ deals combat damage to a player"
#: payoff, ~38 real cards) — "that many" always refers back to the firing
#: event's own ``amount`` (RULE 603.1), read fresh at resolve time
#: (`CreateTokenEffect.count_from_trigger_event`) rather than a literal
#: count. Reuses `_xx_token_mid_params` for the "<mid> token[s][ with
#: <kw>]" tail (a fixed literal count needs none of `_inline_create_token_
#: params`'s ``n``/``who`` groups).
_CREATE_TOKEN_THAT_MANY_RE = compile_clause(
    r"creates? that many "
    r"(?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z, ]+))?"
    + _TOKEN_TAPPED_ATTACKING
)


def _create_token_that_many(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    params.update({
        "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_from_trigger_event": "amount",
    })
    if m.groupdict().get("tapped"):
        params["tapped"] = True
    if m.groupdict().get("tapped_attacking"):  # RULE 508.4
        params["tapped"] = True
        params["attacking"] = True
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    return [EffectSpec("create_token", params)]


#: A dynamic token *count* (RULE 601.2c, `CreateTokenEffect.count_selector`
#: — `continuous.count_selector`'s own vocabulary), for the two real
#: phrasings found so far: "…for each `<subtype>` you control" (Elvish
#: Promenade-shaped) and "…for each attacking creature" (Embercleave's own
#: cost-reduction wording, reused here for a token count). A count-selector
#: word not in this table stays unclaimed rather than guessed at.
def _count_selector_for_phrase(
    subtype: Optional[str], attacking: Optional[str],
) -> "Optional[str | dict[str, Any]]":
    if attacking:
        return "attacking_creatures"
    if subtype:
        # "for each Forest / land / creature / Elf you control" — the shared
        # count grammar, so a land or card type isn't read as a creature type.
        return subtype_count_selector(subtype)
    return None


#: "Create a 1/1 green Elf Warrior creature token for each Elf you control."
#: (Elvish Promenade-shaped) — the trailing-count-selector sibling of the
#: plain `create_token` row above.
_CREATE_TOKEN_FOR_EACH_RE = compile_clause(
    rf"(?:(?P<who>you|each player|each opponent|target player|target opponent) )?creates? {COUNT} "
    rf"(?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    rf"(?P<mid>[a-z ]*?)creature tokens?"
    rf"(?: with (?P<kw>[a-z, ]+?))?" + _TOKEN_TAPPED_ATTACKING +
    # PAR-148: "…tapped and attacking for each experience counter you have" (Otharri, Suns' Glory; Aang, Airbending Master).
    r" for each (?:(?P<subtype>[a-z]+) you control|(?P<attacking>attacking creature)|(?P<exp>experience counter you have))"
)


def _create_token_for_each(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    selector = (
        "experience_counters_you_have" if m.groupdict().get("exp")
        else _count_selector_for_phrase(m.groupdict().get("subtype"), m.groupdict().get("attacking"))
    )
    if selector is None:
        return None
    params.pop("count", None)
    params["count_selector"] = selector
    return [EffectSpec("create_token", params)]


#: "Create X 1/1 green Elf Warrior creature tokens, where X is the number
#: of attacking creatures." (Galadhrim Ambush-shaped) — the "announce X,
#: then explain it" sibling of the "for each" row above. MEC-27: widened
#: from its own narrow subtype/attacking-only tail to the full
#: `subgrammars.DEVOTION` vocabulary (bare "creatures/permanents/artifacts/
#: lands/enchantments/planeswalkers you control", the two-word compounds,
#: devotion-to-colour) — the same reading `_CREATE_TOKEN_NUMBER_EQUAL_
#: DEVOTION_RE` already uses for the "equal to" phrasing, just for this
#: row's "where x is" surface wording instead.
_CREATE_TOKEN_XX_WHERE_RE = compile_clause(
    r"create x (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    rf"(?: with (?P<kw>[a-z, ]+))?" + _TOKEN_TAPPED_ATTACKING + rf", where x is {DEVOTION}"
)

#: "Create X 1/1 red Elemental creature tokens with haste, where X is ~'s
#: power." (Elemental Mastery) — source power is a live selector, so a pump
#: before resolution changes how many tokens are made.
_CREATE_TOKEN_XX_SOURCE_POWER_RE = compile_clause(
    r"create x (?P<p>\d+)/(?P<t>\d+) (?P<mid>[a-z ]*?)creature tokens?"
    r" with (?P<kw>[a-z, ]+), where x is ~'?s power"
)


def _create_token_xx_source_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = xx_token_mid_params(m.group("mid"), m.group("kw"))
    if params is None:
        return None
    return [EffectSpec("create_token", {
        **params, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_selector": "source_power",
    })]


def _create_token_xx_where(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    selector = devotion_selector(m)
    if selector is None:
        return None
    if m.groupdict().get("tapped_attacking"):  # RULE 508.4
        params["tapped"] = True
        params["attacking"] = True
    return [EffectSpec("create_token", {
        **params, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_selector": selector,
    })]


#: RULE 202.2f/700.6 "create a number of 1/1 white Soldier creature tokens
#: equal to your devotion to white." (Evangel of Heliod/Master of Waves-
#: shaped) — a third surface wording for the same dynamic-count shape
#: `_CREATE_TOKEN_FOR_EACH_RE`/`_CREATE_TOKEN_XX_WHERE_RE` already cover,
#: this time keyed to `DEVOTION` instead of a `count_selector` subtype word.
_CREATE_TOKEN_NUMBER_EQUAL_DEVOTION_RE = compile_clause(
    r"creates? a number of (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    rf"(?: with (?P<kw>[a-z, ]+))? equal to {DEVOTION}"
)


def _create_token_number_equal_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    selector = devotion_selector(m)
    if not selector:
        return None
    if m.groupdict().get("tapped"):
        params["tapped"] = True
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    return [EffectSpec("create_token", {
        **params, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_selector": selector,
    })]


#: The inline-stats creature-token grammar `_create_token`'s own `EffectHandler`
#: row wraps, reused bare here (no leading "creates?") so it can be embedded
#: inside a bigger clause — "create **a 1/1 white Halfling creature token**
#: and attach ~ to it." (Auxiliary Boosters/Field-Tested Frying Pan's own
#: second sentence) needs the token description without also consuming the
#: "and attach …" tail the way the top-level row's fullmatch would demand.
_CREATE_TOKEN_INLINE = (
    rf"{COUNT} (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    # ``0-9`` in the keyword capture is ENG-31's "… token with firebending
    # N" — `_inline_create_token_params` splits a "<name> <N>" entry into
    # ``parametric_keywords`` and fail-closes on any other numbered ability.
    rf"(?P<mid>[a-z ]*?)creature tokens?(?: with (?P<kw>[a-z0-9, ]+))?"
)

#: "create a 1/1 white Halfling creature token and attach ~ to it." (Living
#: Weapon-adjacent, but printed as ordinary oracle text rather than the
#: keyword — Auxiliary Boosters) / "…**then** attach **this** to it." (the
#: "For Mirrodin!" ability word's own reminder-text wording, MEC-28 — see
#: `gate.py`'s ``_FOR_MIRRODIN_RE`` for why this specific card's real rules
#: text lives in reminder text at all) — one clause, two effects: the
#: token, then `AttachEffect`'s ``target_kind="created"`` mode onto
#: whatever that just made (RULE 608.2's "it").
_CREATE_TOKEN_AND_ATTACH_RE = compile_clause(
    rf"creates? {_CREATE_TOKEN_INLINE}(?:,)? (?:and|then) attach (?:~|this) to it"
)


def _create_token_and_attach(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    return [EffectSpec("create_token", params), EffectSpec("attach", {"target_kind": "created"})]


#: "Create <Name>, a legendary N/N ... creature token [with <keywords>]."
#: (PAR-13, Dungeon of the Mad Mage's "Cradle of the Death God" — "Create
#: The Atropal, a legendary 4/4 black God Horror creature token with
#: deathtouch.") — the named-legendary sibling of `_create_token`'s bare
#: inline-stats grammar: a real proper name up front (unlike `_create_
#: named_token`'s closed Treasure/Clue/Food vocabulary, this name is
#: whatever the clause prints, always legendary, always with inline stats)
#: rather than a curated `TokenDatabase` lookup, since a card's own unique
#: token needs no shared ability the database would otherwise supply.
_CREATE_NAMED_LEGENDARY_TOKEN_RE = compile_clause(
    r"create (?P<name>[a-z][a-z' -]*(?:, [a-z][a-z' -]*)*), a legendary (?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z, ]+))?"
)


def _create_named_legendary_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors, subtypes, is_artifact = split_token_mid_words(m.group("mid") or "")
    keywords: list[str] = []
    if m.groupdict().get("kw"):
        parsed = token_keywords(m.group("kw"))
        if parsed is None:
            return None
        keywords = parsed
    return [EffectSpec("create_token", {
        "count": 1, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "colors": colors, "subtypes": subtypes, "keywords": keywords,
        **({"is_artifact": True} if is_artifact else {}),
        "token_name": m.group("name").strip().title(), "legendary": True,
    })]


#: "create a Treasure token" / "create two Clue tokens" — the named-token
#: sibling of `_create_token`'s inline-stats creature grammar: no P/T, no
#: "creature" word, just a bare recognised token name. Looked up in the
#: curated `TokenDatabase` at resolve time (`CreateTokenEffect.apply`), so
#: the created object keeps its real activated ability, not a blank card.
#: The subject prefix on a named-token create — "you"/nothing, or a targeted/
#: mass player ("target player creates a Treasure token." — Prismari Command;
#: "each opponent creates a Clue token." — Tamiyo's Safekeeping-adjacent).
_NAMED_TOKEN_CREATOR: dict[str, str] = {
    "": "you", "you ": "you",
    "each opponent ": "each_opponent", "each player ": "each_player",
    "target player ": "target", "target opponent ": "target",
}


def _create_named_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    name = NAMED_TOKEN_WORDS[m.group("name")]
    params: dict = {"count": count_of(m.group("n")), "token_name": name}
    if m.groupdict().get("tapped"):  # "create a tapped Treasure token" (Village Pillagers)
        params["tapped"] = True
    who = (m.groupdict().get("who") or "").lower()
    creator = _NAMED_TOKEN_CREATOR.get(who)
    if creator is None:
        return None
    if creator != "you":
        params["creators"] = creator
    if creator == "target":
        params["target_kind"] = "opponent" if who == "target opponent " else "player"
    return [EffectSpec("create_token", params)]


#: PAR-147: "<destroy/exile/choose> target <permanent>. **Its controller creates** a <token>." (Contraband Livestock's
#: results rows, Buy Your Silence, Ravenform, Afterlife, ...). The "its" is the permanent an earlier clause of the
#: same ability targeted (RULE 608.2h last-known information: it is usually gone by now), so the row is offered only
#: after such a clause (`previous_subject_only`) and reads the create as its second-person form run by
#: `CreateTokenEffect.creators="previous_target_controller"`. Anything the plain create rows do not claim as one
#: ordinary token creation stays unclaimed.
_PREVIOUS_CONTROLLER_CREATES_RE = compile_clause(r"its controller (?P<rest>creates? .+)")


def _previous_controller_creates(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    effects = match_clause_once(m.group("rest"), reading=reading.only())
    if (
        effects is None or len(effects) != 1 or effects[0].type != "create_token"
        or effects[0].params.get("creators") is not None or effects[0].params.get("target_kind") is not None
        or effects[0].params.get("per_opponent") or effects[0].params.get("attacking")
    ):
        return None
    return [EffectSpec("create_token", {**effects[0].params, "creators": "previous_target_controller"})]


#: PAR-132: "<destroy/exile …>. **For each [nontoken] creature destroyed/exiled this way, <body>**" (Hour of Need,
#: Descent of the Dragons, Blood Money, Canoptek Scarab Swarm). RULE 608.2c: the loop runs over the objects an
#: earlier instruction of *this resolution* actually destroyed or exiled (`GameContext.destroyed_objects` /
#: `exiled_objects`), one pass per object. "Its controller creates …" is the loop item's last-known controller
#: (RULE 608.2h, `CreateTokenEffect.creators="iteration_item_controller"`); any other body is an item-independent
#: ordinary clause ("you create a Treasure token", "you draw a card") run once per object. A body that names a
#: target or a pronoun (it/that/them) would read the wrong referent, so it is refused.
_THIS_WAY_TYPE_WORDS = {
    "creature": "Creature", "artifact": "Artifact", "land": "Land", "enchantment": "Enchantment",
    "planeswalker": "Planeswalker",
}
_THIS_WAY_TYPE_ALT = "|".join(_THIS_WAY_TYPE_WORDS)
_FOR_EACH_THIS_WAY_RE = compile_clause(
    rf"for each (?P<nontoken>nontoken )?(?P<types>(?:{_THIS_WAY_TYPE_ALT})(?: or (?:{_THIS_WAY_TYPE_ALT}))*|permanent|card)"
    r"(?P<is_card> card)? (?P<verb>destroyed|exiled) this way, (?P<body>.+)"
)
_THIS_WAY_BODY_PRONOUN_RE = re.compile(r"\b(?:it|its|that|them|those|their|they)\b")


def _for_each_this_way(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    body = m.group("body")
    its_controller = body.startswith("its controller ")
    if its_controller:
        body = body[len("its controller "):]
    elif _THIS_WAY_BODY_PRONOUN_RE.search(body):
        return None
    effects = match_clause_once(body, reading=reading.only())
    if not effects:
        return None
    if '"target_kind"' in json.dumps([e.to_dict() for e in effects], default=str):
        return None
    if its_controller:
        if (
            len(effects) != 1 or effects[0].type != "create_token"
            or effects[0].params.get("creators") is not None
            or effects[0].params.get("per_opponent") or effects[0].params.get("attacking")
        ):
            return None
        effects = [EffectSpec("create_token", {**effects[0].params, "creators": "iteration_item_controller"})]
    over: dict[str, Any] = {"this_way": m.group("verb")}
    if m.group("nontoken"):
        over["this_way_nontoken"] = True
    types = m.group("types")
    if types != "permanent" and types != "card":
        over["this_way_type"] = [_THIS_WAY_TYPE_WORDS[w] for w in types.split(" or ")]
    return [EffectSpec("for_each", {"over": over, "effects": [e.to_dict() for e in effects]})]


#: PAR-104: "whenever a creature you control with a +1/+1 counter on it leaves the battlefield, create a Mutagen
#: token for each +1/+1 counter on it." (The Ooze) — under a group trigger "it" is the firing creature, and the
#: `counters` amount reads its counters live, or from the leave event's RULE 603.10a snapshot once it is gone.
_CREATE_NAMED_TOKEN_PER_COUNTER_ON_IT_RE = compile_clause(
    rf"create an? (?P<name>{'|'.join(NAMED_TOKEN_WORDS)}) token for each (?P<kind>\+1/\+1|-1/-1|[a-z]+) counter on it"
)


def _create_named_token_per_counter_on_it(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_token", {
        "token_name": NAMED_TOKEN_WORDS[m.group("name")],
        "count": {"kind": "counters", "of": "trigger_subject", "counter": m.group("kind")},
    })]


#: "Whenever this creature deals combat damage to a player or planeswalker,
#: create that many Treasure tokens." (The Reaver Cleaver) — RULE 603.1's
#: event amount, using the same runtime counter as the creature-token sibling
#: below but for a named noncreature token.
_CREATE_NAMED_TOKEN_THAT_MANY_RE = compile_clause(
    rf"creates? that many (?P<name>{'|'.join(NAMED_TOKEN_WORDS)}) tokens?"
)


def _create_named_token_that_many(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_token", {
        "token_name": NAMED_TOKEN_WORDS[m.group("name")],
        "count_from_trigger_event": "amount",
    })]


#: "When ~ dies, create a number of tapped Treasure tokens equal to its
#: power." (Goldvein Hydra) — the named-token count-from-power sibling;
#: `CreateTokenEffect.count_from_subject` reads the DIES event's RULE 400.7
#: power/toughness snapshot (`_characteristic_of_subject`). `self_subject_
#: only` — "its" is the trigger's own subject.
_CREATE_NAMED_TOKEN_EQ_ITS_RE = compile_clause(
    rf"creates? a number of (?P<tapped>tapped )?(?P<name>{'|'.join(NAMED_TOKEN_WORDS)}) tokens? "
    r"equal to its (?P<char>power|toughness)"
)


def _create_named_token_eq_its_self(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "token_name": NAMED_TOKEN_WORDS[m.group("name")],
        "count_from_subject": f"trigger_subject_{m.group('char')}",
    }
    if m.groupdict().get("tapped"):
        params["tapped"] = True
    return [EffectSpec("create_token", params)]


#: The compound sibling of `_create_token_and_attach` — "create a Food
#: token, then create a 1/1 white Halfling creature token and attach ~ to
#: it." (Field-Tested Frying Pan): a named artifact token
#: (`_NAMED_TOKEN_WORDS`) first, *then* the create+attach shape onto the
#: second, inline-stats token — `AttachEffect`'s ``created_objects[-1]``
#: read picks the Halfling, not the Food, since it's whichever effect ran
#: last. Deliberately hard-codes the singular "a `<named>` token" (rather
#: than reusing `COUNT`) — the real card this closes only ever prints one,
#: and `COUNT`'s own capture group is named ``n``, the same name
#: `_CREATE_TOKEN_INLINE` already binds for the *second* token's count, so a
#: shared `COUNT` here would collide.
_CREATE_NAMED_THEN_CREATE_TOKEN_AND_ATTACH_RE = compile_clause(
    rf"creates? an? (?P<named>{'|'.join(NAMED_TOKEN_WORDS)}) token, then "
    rf"creates? {_CREATE_TOKEN_INLINE} and attach ~ to it"
)


def _create_named_then_create_token_and_attach(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    named_name = NAMED_TOKEN_WORDS[m.group("named")]
    return [
        EffectSpec("create_token", {"count": 1, "token_name": named_name}),
        EffectSpec("create_token", params),
        EffectSpec("attach", {"target_kind": "created"}),
    ]


#: RULE 701.19a's keyword action — "Investigate" (Shadows over Innistrad-
#: introduced, but reused across many later sets — the widest single
#: template found in this batch's ranking, 87 SOLO cache-wide). Purely "the
#: player creates a Clue token" (`"Clue"` is already in `_NAMED_TOKEN_WORDS`,
#: so the *token* itself needed no new work — only this keyword-action
#: recognition), so it's modeled as a direct alias onto the same
#: `create_token` shape `_create_named_token` already emits rather than a
#: dedicated `investigate` effect type. "Investigate twice" is `normalize`'s
#: one gap in its own spelled-number folding (it rewrites "three times" to
#: "3 times" but "twice" isn't a `_NUMBER_WORDS` entry — it's a distinct
#: word, not "two times") — handled here as its own literal alternative
#: rather than widening `normalize` for a single irregular word no other
#: family needs. "Investigate X times" (Disorder in the Court) is the announced-X
#: ``"x"`` count sentinel; "...for each `<count>`" (a dynamic count) stays
#: unclaimed — `COUNT` only ever resolves a literal int.
_INVESTIGATE_RE = compile_clause(r"investigate(?: (?P<times>twice|x times|\d+ times?))?")


def _investigate(m: re.Match[str]) -> list[EffectSpec]:
    times = m.group("times")
    if times == "x times":
        return [EffectSpec("create_token", {"count": "x", "token_name": "Clue"})]
    count = 2 if times == "twice" else (int(times.split()[0]) if times else 1)
    return [EffectSpec("create_token", {"count": count, "token_name": "Clue"})]


#: RULE 701.51a's keyword action — "The Ring tempts you." (Tales of
#: Middle-earth-shaped, "Lord of the Rings" set-specific — see
#: PARSER_LONG_TAIL.md's set-specific-mechanics table). The engine
#: primitive and the `"the_ring_tempts_you"` `EffectSpec` type already
#: existed (`RulesEngine.the_ring_tempts_you`, `effects.
#: TheRingTemptsYouEffect`, both built for one hand-authored card,
#: `game/card_catalogue`'s "One Ring to Rule Them All") — only this
#: general oracle-text recognition was missing, the single widest gap this
#: set's own precon deck has (36 SOLO cache-wide).
_RING_TEMPTS_YOU_RE = compile_clause(r"the ring tempts you")


def _ring_tempts_you(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("the_ring_tempts_you", {})]


def _proliferate(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("proliferate", {})]


#: "double the number of [+1/+1 / each kind of] counter(s) on <object>."
#: (RULE 701.19-adjacent — Primordial Hydra / Tanazir Quandrix / Kalonian
#: Hydra / Bristly Bill / Growth Curve / Dragonsguard Elite / Vorel). Four
#: subject shapes, each its own `DoubleCountersOnTargetEffect.mode`:
#:   * "~"                                    → ``mode="self"``
#:   * "target creature [you control]"        → ``mode="target"`` (RULE 115)
#:   * "each creature you control"             → ``mode="each_you_control"``
#:   * "it" / "that creature"                  → ``mode="previous_subject"``
#: A "+1/+1" (or other named kind) narrows the doubling; bare "each kind
#: of" / "the" doubles every kind (Vorel).
_DOUBLE_COUNTERS_RE = compile_clause(
    r"double the number of (?:each kind of |(?P<kind>\+1/\+1|-1/-1|[a-z]+) )?counters? on "
    r"(?P<subject>~|it|that creature|target creature(?: you control)?|"
    r"each creature you control|each of those creatures)"
)


def _double_counters(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subj = m.group("subject").strip()
    params: dict = {}
    if m.group("kind"):
        params["kind"] = m.group("kind")
    if subj == "~":
        params["mode"] = "self"
    elif subj in ("it", "that creature", "each of those creatures"):
        params["mode"] = "previous_subject"
    elif subj == "each creature you control":
        params["mode"] = "each_you_control"
    elif subj.startswith("target creature"):
        params["mode"] = "target"
        params["target_kind"] = "creature_you_control" if "you control" in subj else "creature"
    else:
        return None
    return [EffectSpec("double_counters_on_target", params)]


#: "Damage can't be prevented this turn." (RULE 615.6 — Flaring Pain, the
#: back half of Insult // Injury, Fear Fire Foes) — untargeted, turn-scoped;
#: `DisableDamagePreventionEffect` / `RulesEngine.disable_damage_prevention_
#: this_turn` already existed for hand-authored cards, this is the first
#: oracle-text route to it. The bare word "damage" only (a leading "combat"
#: is a narrower, static, combat-only shape this effect doesn't model).
_DISABLE_DAMAGE_PREVENTION_RE = compile_clause(r"damage can'?t be prevented this turn")


def _disable_damage_prevention(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("disable_damage_prevention", {})]


#: "proliferate twice" (Contagion Engine/Agent Frank Horrigan/Ezuri, Stalker
#: of Spheres) / "proliferate N times" (War of the Spark's Saga chapter —
#: normalize.py folds spelled-out numbers to digits, but not "twice", so
#: that's matched as its own literal word). A bare "proliferate x times"
#: (Expansion Algorithm's spell-announced-X, Tromell's dynamic
#: count-selector) stays unclaimed — a different shape (`ProliferateEffect`
#: has no "x"/count-selector support), not this literal-count one.
def _proliferate_n_times(m: re.Match[str]) -> list[EffectSpec]:
    times = 2 if m.group("n") is None else int(m.group("n"))
    return [EffectSpec("proliferate", {"times": times})]


#: "remove all counters from all permanents" (RULE 122 — Oblivion Stone/
#: Aether Snap/Thief of Blood-shaped, untargeted board wipe of counters).
def _remove_counters_all_permanents(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_counters", {})]


#: "remove all counters from target permanent" (Vampire Hexmage-shaped).
def _remove_counters_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_counters", {"target_kind": "permanent"})]


#: "Remove all `<kind>` counters from ~." (Coalition Relic/Ventifact
#: Bottle, PAR-66) — untargeted (the ability names its own source, RULE
#: 115 never applies), and restricted to one named counter kind so an
#: unrelated counter type on the same permanent survives. Reuses
#: `_NAMED_COUNTER_KIND` (the same open-minus-reserved kind axis `_add_named_
#: counter` uses) plus the `+1/+1`/`-1/-1` P/T shape.
_REMOVE_ALL_NAMED_COUNTERS_SELF_RE = compile_clause(
    rf"remove all (?P<ckind>{NAMED_COUNTER_KIND}|[+\-−]1/[+\-−]1) "
    rf"counters? from {SELF_SUBJECT}"
)


def _remove_all_named_counters_self(m: re.Match[str]) -> list[EffectSpec]:
    ckind = m.group("ckind")
    kind = "+1/+1" if ckind[0] in "+" else ("-1/-1" if ckind[0] in "-−" else ckind)
    return [EffectSpec("remove_counters", {"self_only": True, "kind": kind})]


#: "remove up to N counters from target permanent/creature/…" (Glissa
#: Sunslayer/Heartless Act/Render Inert-shaped) — a genuinely different,
#: interactive chosen-*amount* shape from the bare "remove all counters"
#: above (`RemoveCountersEffect`'s ``max_count``). Digits only —
#: `normalize.py` already folds spelled-out numbers ("up to three" → "up to
#: 3"). Embeds the shared `TARGET` sub-grammar (PAR-2) rather than a
#: hand-rolled "permanent|creature" alternation, so Price of Betrayal's
#: "target artifact, creature, planeswalker, or opponent" — a player
#: alongside three permanent types, `targeting.
#: artifact_creature_planeswalker_or_opponent` — is claimed the same way
#: any other TARGET-shaped clause is.
_REMOVE_COUNTERS_CHOICE_RE = compile_clause(
    rf"remove up to (?P<n>\d+) counters? from {TARGET}"
)


def _remove_counters_choice(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec(
        "remove_counters", {"target_kind": kind, "max_count": int(m.group("n"))},
    )]


# "You may play [up to] N additional land(s) this turn."  (RULE 305.2
# one-turn permission, Explore/Escape to the Wilds/Kiora's -1-shaped) — the
# resolve-time, single-turn sibling of the standing `extra_land_drop` static
# `catalogue.static_handlers` recognises for a permanent's own printed
# ability ("…on each of your turns"); this shape only ever appears as a
# clause in a spell/ability's effect body, never a permanent's standing text.
# "You may " is optional here: when this is the *only* clause in the body,
# `segmenter.segment_line`'s `peel_optional` already stripped a leading
# "you may " before this ever runs (Summer Bloom-shaped); when it trails an
# earlier clause ("Draw a card. You may play …", Explore/Urban Evolution-
# shaped) it's still there in the text this handler sees.
_EXTRA_LAND_PLAY_RE = compile_clause(rf"(?:you may )?play (?:up to )?{COUNT} additional lands? this turn")


def _extra_land_play(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("extra_land_play", {"count": count_of(m.group("n"))})]


# RULE 701.40a manifest / RULE 701.58a cloak — "manifest the top card of your
# library" and its "the top N cards" plural, plus cloak's identical shape
# (the only difference is ward {2} on the resulting permanent, carried as the
# effect's ``kind``). "Manifest dread" (RULE 701.40a plus a look-at-two
# chooser) is a separate handler since it isn't a count at all.
def _manifest(m: re.Match[str]) -> list[EffectSpec]:
    kind = "cloak" if m.group("verb").lower() == "cloak" else "manifest"
    return [EffectSpec("manifest", {"count": count_of(m.group("n") or "a"), "kind": kind})]


def _manifest_dread(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("manifest_dread", {})]


#: PAR-111: "manifest dread, then attach ~ to that creature." (the Duskmourn Equipment cycle — Conductive Machete,
#: Cursed Windbreaker, Dissection Tools, Killer's Mask) — the manifested permanent is "that creature", handed to
#: `AttachEffect`'s ``created`` mode through `GameContext.created_objects` (`ManifestDreadEffect`, and the
#: suspended remainder when the look-at-two choice pauses the resolution).
_MANIFEST_DREAD_THEN_ATTACH_RE = compile_clause(r"manifest dread, then attach (?:~|it|this [a-z]+) to that creature")


def _manifest_dread_then_attach(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("manifest_dread", {}), EffectSpec("attach", {"target_kind": "created"})]


#: RULE 601.2f for the rest of the turn: "spells you cast this turn that are
#: black and/or red cost {X} less to cast, where X is …" (Rowan/Will, Scion
#: of …) and "the next instant or sorcery spell you cast this turn costs {1}
#: less to cast" (Hardened Berserker, Kaza, Spellbinding Soprano).
_REDUCE_COSTS_COLORS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
_REDUCE_COSTS_THIS_TURN_RE = compile_clause(
    r"(?P<next>the next )?(?P<types>instant or sorcery |instant and sorcery |face-down |)"
    r"spells? you cast this turn(?: that (?:is|are) (?P<c1>white|blue|black|red|green)"
    r"(?: and/or (?P<c2>white|blue|black|red|green))?)? costs? \{(?P<n>\d+|x)\} (?P<direction>less|more) to cast"
    r"(?:, where x is (?P<x>.+?)(?: as this ability resolves)?)?"
)


def _reduce_costs_this_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    params: dict[str, Any] = {"next_only": bool(m.group("next"))}
    if m.group("direction") == "more":
        params["increase"] = True
    types = m.group("types").strip()
    if types == "face-down":
        params["face_down"] = True
    elif types:
        params["spell_type"] = ["instant", "sorcery"]
    colors = [_REDUCE_COSTS_COLORS[c] for c in (m.group("c1"), m.group("c2")) if c]
    if colors:
        params["spell_colors"] = colors
    if m.group("n") != "x":
        if m.group("x"):
            return None
        return [EffectSpec("reduce_spell_costs_this_turn", {**params, "amount": int(m.group("n"))})]
    phrase = (m.group("x") or "").strip()
    if phrase == "~'s power":
        amount: dict[str, Any] = {"kind": "characteristic", "characteristic": "power", "of": "source"}
    else:
        selector = parse_amount_phrase(phrase)
        if selector is None:
            return None
        amount = {"kind": "count_selector", "selector": selector}
    return [EffectSpec("bind", {"name": "n", "amount": amount, "effects": [
        EffectSpec("reduce_spell_costs_this_turn", {**params, "amount": "$n"}).to_dict(),
    ]})]


# RULE 708.8 by an effect, untargeted: "you may turn a permanent you control
# face up" (Zimone) / "… a face-down creature you control face up".
def _turn_face_up_chosen(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("turn_face_up_chosen", {
        "optional": bool(m.group("may")),
        "creature_only": m.group("what") == "face-down creature",
    })]


# PAR-98: Niambi's "If you do" tail measures the bounced target's last
# known mana value.  The enclosing ReturnToHandEffect preserves that target
# as the nested resolution's previous subject before applying this bind.
_YOU_GAIN_LIFE_EQ_THAT_CREATURE_MV_RE = compile_clause(
    r"you gain life equal to that creature'?s mana value"
)


def _you_gain_life_eq_that_creature_mv(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bind", {
        "name": "mv",
        "amount": {"kind": "characteristic", "characteristic": "mana_value", "of": "previous_target"},
        "effects": [{"type": "gain_life", "params": {"amount": "$mv"}}],
    })]


# "Suspect <creature>." (RULE 701.60a — Murders at Karlov Manor): the
# creature gains the suspected designation (menace + can't block, 701.60b).
# `RulesEngine.suspect` / `effects.SuspectEffect` (registered as
# ``suspect``). Same subject shapes as `_goad`/`_explore`:
#   • "suspect it" — the ability's own source ("when ~ enters, suspect it");
#   • "suspect it"/"suspect that creature" after a targeting clause — the
#     previous target (`previous_subject_only`, Caught Red-Handed);
#   • "suspect enchanted creature" — this Aura's host (`attached`);
#   • "suspect [up to N] target creature[ an opponent controls / other
#     target creature you control]" — off the shared TARGET rows.
_SUSPECT_TARGET_KINDS = (
    "creature", "creature_you_control", "creature_you_dont_control",
    "other_creature_you_control",
)


def _suspect_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("suspect", {})]


def _suspected_self_counter_or_suspect(m: re.Match[str]) -> list[EffectSpec]:
    """Repeat Offender: mutually exclusive self-suspect branches."""
    return [
        EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "self": True},
                   condition={"source_is_suspected": True}),
        EffectSpec("suspect", {}, condition={"source_is_suspected": False}),
    ]


def _suspect_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("suspect", {"previous_subject": True})]


def _suspect_attached(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("suspect", {"attached": True})]


def _suspect_other_then_remove_self(m: re.Match[str]) -> list[EffectSpec]:
    """Frantic Scapegoat's optional non-target choice and reflexive tail."""
    return [EffectSpec("suspect", {
        "selection_kind": "other_creature_you_control", "optional": True,
        "then_specs": [{"type": "remove_suspected", "params": {"self_subject": True}}],
    })]


def _suspect_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _SUSPECT_TARGET_KINDS):
        return None  # only a creature can be suspected (RULE 701.60a)
    return [EffectSpec("suspect", {"target_kind": kind, **optional_param(m)})]


# "All suspected creatures are no longer suspected." (RULE 701.60a's
# reverse — Absolving Lammasu). Only the mass standalone shape; the
# conditional single-creature "if it's suspected, it's no longer suspected"
# stays unclaimed, fail-closed.
def _remove_suspected_all(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_suspected", {})]


# PAR-30 Suspect one-off shapes — "You may have it become no longer
# suspected." (Deadly Complication's second mode, after "put a +1/+1 counter
# on target suspected creature you control"). "it" is the previous clause's
# target; the "you may" routes through `_request_choose_objects` so declining
# keeps the menace a suspected creature has (`RemoveSuspectedEffect.optional`).
def _remove_suspected_may_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_suspected", {"previous_subject": True, "optional": True})]


def _remove_suspected_previous_selector(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_suspected", {"previous_selector": True})]


# "Detain [up to N] target <permanent> an opponent controls." (RULE 701.35a
# — Return to Ravnica). `RulesEngine.detain` / `effects.DetainEffect`
# (registered as ``detain``). Only an opponent-controlled creature or
# nonland permanent (every real detain card); a plain "target creature"
# with no controller qualifier isn't a real printing, so leave it
# unclaimed. "detain each nonland permanent … with mana value N or less"
# (Lavinia) and a "with backup or vehicle" filter (Azorius Traffic
# Enforcement) stay UNMODELED — a selector + filter this doesn't build yet.
_DETAIN_TARGET_KINDS = (
    "creature_you_dont_control", "nonland_permanent_you_dont_control",
    "permanent_you_dont_control",
)
_DETAIN_MULTI_RE = compile_clause(
    r"detain up to (?P<n>2|3|two|three) target "
    r"(?P<what>creatures|nonland permanents) "
    r"(?:your opponents control|an opponent controls)"
)
_DETAIN_WORD_N = {"two": 2, "three": 3, "2": 2, "3": 3}


def _detain(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _DETAIN_TARGET_KINDS):
        return None
    return [EffectSpec("detain", {"target_kind": kind, **optional_param(m)})]


def _detain_multi(m: re.Match[str]) -> list[EffectSpec]:
    kind = ("nonland_permanent_you_dont_control"
            if m.group("what") == "nonland permanents" else "creature_you_dont_control")
    return [EffectSpec("detain", {
        "target_kind": kind, "count": _DETAIN_WORD_N[m.group("n")], "optional": True,
    })]


# "Goad target creature." (RULE 701.15a) and its controller-scoped variants
# ("…target creature an opponent controls"), off the shared `TARGET` rows.
def _goad(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        # Goaded is only ever a creature designation (RULE 701.15b) — a
        # non-creature target row here means the clause isn't what it looks
        # like, so leave it unclaimed.
        return None
    return [EffectSpec("goad", {"target_kind": kind, **optional_param(m)})]


# "Goad it." / "Goad that creature." — the pronoun form, pointing at whatever
# the *previous* clause of this same ability targeted ("~ deals 2 damage to
# target creature. Goad that creature.", Hellrider-shaped). Offered only when
# such a clause really preceded it (`EffectHandler.previous_subject_only`),
# never as a blind claim.
def _goad_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("goad", {"target_kind": None})]


#: "goad up to two target creatures." (Sifa Grent) -- RULE 701.15a over `GoadEffect`'s ``count``.
_GOAD_MULTI_RE = compile_clause(rf"goad {MULTI_TARGET_QUANTIFIER}(?P<target>{MULTI_TARGET_ALT})")


def _goad_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = multi_target_params(m)
    # Goaded is only ever a creature designation (RULE 701.15b); `GoadEffect` has no count range.
    if params is None or "count_max" in params or params["target_kind"] not in (
        "creature", "creature_you_control", "creature_you_dont_control",
    ):
        return None
    return [EffectSpec("goad", params)]


# "The tokens are goaded for the rest of the game." (Rendmaw, The War Games,
# Life of the Party) — the subject is what an *earlier clause of this same
# ability* just created, which is `GameContext.created_objects`; "for the
# rest of the game" is the no-expiry variant of RULE 701.15a's default
# "until your next turn".
def _goad_created(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("goad", {"target_kind": None, "referent": "created", "permanent": True})]


# "You become the monarch." / "Target player becomes the monarch." (RULE
# 725.1) and "You take the initiative." / "Target player takes the
# initiative." (RULE 726.1) — plain designation grants, the same untargeted-
# vs-targeted "who" split `_gain_life`/`_lose_life` use.
def _become_monarch(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("become_monarch", params)]


def _take_initiative(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("take_initiative", params)]


# "[You/Target player] get[s] an emblem with '<ability>'." (RULE 114.2) —
# the quoted ability is itself an ordinary ability line, recursively parsed
# the same way `static_handlers.quoted_ability_grant_effects` parses an
# Aura/Equipment's quoted grant (`segmenter.segment_line`, imported lazily in
# `_emblem_ability_spec` below — `segmenter` imports *this* module, so a
# module-level import would cycle). Unlike that grant (which flattens to a
# `grant_triggered_ability`'s bare effects list), the *whole* nested
# `AbilitySpec` is kept, since `game/rules_engine.py`'s `create_emblem` binds
# it fresh at resolve time against a synthetic `Emblem` source (RULE 114.4) —
# there's no host permanent to flatten onto in the first place.
_EMBLEM_RE = re.compile(
    r'(?P<who>you |target player |each opponent )?gets? an emblem with,? "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)

#: Subject/selector shapes that only mean something relative to a *source
#: permanent* ("this creature", "equipped/enchanted creature", "other
#: creatures you control") — meaningless for an emblem's synthetic source,
#: so a nested spec using one is rejected (fail-closed) rather than silently
#: binding an ability that can never fire, or that resolves a selector that
#: always comes back empty.
_EMBLEM_UNSUPPORTED_SUBJECTS: frozenset[str] = frozenset(
    {"self", "attached_permanent", "self_or_attached_permanent"}
)
_EMBLEM_UNSUPPORTED_AFFECTS: frozenset[str] = frozenset(
    {"self", "attached_permanent", "other_creatures_you_control"}
)


def emblem_ability_spec(inner: str) -> Optional[dict]:

    # RULE 114.4: "this emblem" is the ability's source. Inside an outer
    # quotation, Oracle uses single quotes for a granted ability.
    inner = inner.strip().replace("this emblem", SELF)
    inner = re.sub(
        r"(\b(?:have|has|gains?) )'(.+)'(?=[., ]*$)",
        lambda match: match.group(1) + '"' + match.group(2) + '"', inner,
    )
    segment = segment_line(
        inner,
        allow_spell_effect=False,
        provenance=ParserProvenance(version="nested", source="rule:oracle"),
    )
    spec = segment.spec
    if spec is None:
        spec = emblem_body_spec(inner)
    if spec is None:
        static_effects = emblem_static_effect_specs(inner)
        if static_effects:
            spec = AbilitySpec("static", effects=static_effects, raw_text=inner)
    if spec is None or spec.modes:
        return None
    if spec.ability_kind == "triggered":
        condition = (spec.trigger or {}).get("condition") or {}
        if condition.get("subject") in _EMBLEM_UNSUPPORTED_SUBJECTS:
            return None
        if condition.get("subject") == "group" and condition.get("other"):
            return None
    elif spec.ability_kind == "static":
        if any(e.params.get("affects") in _EMBLEM_UNSUPPORTED_AFFECTS for e in spec.effects):
            return None
    elif spec.ability_kind == "activated":
        # RULE 114.4 also permits an emblem's own activated ability (MEC-8) —
        # `RulesEngine.create_emblem` binds it fresh against the synthetic
        # `Emblem` source exactly like the triggered/static cases, so the
        # same fail-closed self-referential guard applies: no real emblem
        # prints one yet, but "sacrifice this"/"equipped creature…"-shaped
        # effects would be meaningless with no host permanent.
        if any(
            e.params.get("target_kind") in _EMBLEM_UNSUPPORTED_SUBJECTS
            or e.params.get("selector") in _EMBLEM_UNSUPPORTED_SUBJECTS
            or e.params.get("affects") in _EMBLEM_UNSUPPORTED_AFFECTS
            for e in spec.effects
        ):
            return None
    else:
        return None  # only a static/triggered/activated ability can live in an emblem
    try:
        spec.validate()
    except Exception:
        return None
    return spec.to_dict()


def _create_emblem(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # RULE 114.2: quoted abilities joined by "and" belong to ONE emblem.
    # Split only at an outer quotation boundary, never inside an ability.
    bodies = re.split(r'"\s+and\s+"', m.group("inner"))
    abilities = [emblem_ability_spec(body) for body in bodies]
    if any(ability is None for ability in abilities):
        return None
    params: dict = {"ability": abilities[0]} if len(abilities) == 1 else {"abilities": abilities}
    who = (m.groupdict().get("who") or "").strip()
    if who == "target player":
        params["target_kind"] = "player"
    elif who == "each opponent":
        params["each_opponent"] = True
    return [EffectSpec("create_emblem", params)]


def _equipped_creature_unblockable(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("unblockable", {"target_kind": "attached_permanent"})]


# PAR-98: Martha Jones' source plus an independently optional second target
# are two effects, not a two-target RULE 115 declaration (the source is
# always affected even when no other creature is chosen).
_SELF_AND_OTHER_UNBLOCKABLE_RE = compile_clause(
    r"~ and up to 1 other target creature(?: you control)? can'?t be blocked this turn"
)


def _self_and_other_unblockable(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("unblockable", {"target_kind": None}),
        EffectSpec("unblockable", {"target_kind": "other_creature", "optional": True}),
    ]


_COLOR_CREATURES_UNBLOCKABLE_RE = compile_clause(
    r"(?P<color>white|blue|black|red|green) creatures you control can'?t be blocked this turn "
    r"except by (?P=color) creatures"
)


def _color_creatures_unblockable(m: re.Match[str]) -> list[EffectSpec]:
    color = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[m.group("color").lower()]
    return [EffectSpec("combat_restriction_this_turn", {
        "selector": "creatures_you_control", "selector_params": {"color": [color]},
        "restriction": {"kind": "only_blocked_by", "filter": {"color": color}},
    })]


_X_POWER_UNBLOCKABLE_RE = compile_clause(
    r"target creature with power x or less can'?t be blocked this turn"
)
_X_TARGETS_UNBLOCKABLE_RE = compile_clause(
    r"x target creatures with power (?P<p>\d+) or less can'?t be blocked this turn"
)


def _x_power_unblockable(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("unblockable", {
        "target_kind": "creature", "creature_filter": {"max_power_from_source_x": True},
    })]


def _x_targets_unblockable(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("unblockable", {
        "target_kind": "creature", "count_selector": "source_x_paid",
        "creature_filter": {"max_power": int(m.group("p"))},
    })]


#: PAR-74: "~ becomes a N/M [`<qualifiers>`] creature[ with `<keyword>`]
#: until end of turn." (Jade Idol) / "target `<permanent kind>` becomes a
#: N/M creature until end of turn[. it's still a `<kind>`.]" (Soilshaper) —
#: RULE 613.4d's temporary type-change animation, already a shipped
#: resolve-time primitive (`GrantUntilEffect` wrapping a layer-4
#: `type_change` static at ``duration="end_of_turn"`` — Incubator's own
#: self-animate shape, Hedge Whisperer's own target-a-land shape, see
#: `card_registry.red_spells`), with only the parser recognition
#: missing. ``<qualifiers>`` is a curated whitelist, not an open word
#: class (fail-closed, same reasoning as `_CAST_SPELL_SUBTYPE_WORDS`):
#: re-stating a permanent's own main type ("spirit **artifact** creature")
#: is a harmless idempotent `add_types` entry, and a genuine new creature
#: subtype ("**spirit** artifact creature") is `add_subtypes`. No colour
#: word is in this list — no real card in this shape has needed one yet;
#: extend it the day one does, don't guess a `colors`-setting layer-5
#: param this primitive doesn't carry.
_ANIMATE_QUALIFIER_TYPES: frozenset[str] = frozenset({"artifact", "enchantment", "land", "planeswalker"})
#: PAR-79 sixth increment widened this from a 7-word set (spirit/elemental/
#: plant/horror/shade/boar/wall) that only covered the one card this row was
#: first written against — the Ravnica guild Keyrune cycle alone prints ten
#: different creature types ("2/2 `<colors>` Bird artifact creature",
#: "1/1 `<colors>` Soldier artifact creature", …). Union with `segmenter.
#: _CAST_SPELL_SUBTYPE_WORDS`'s own curated real-creature-type vocabulary
#: rather than guessing a fresh list — same words, duplicated here rather
#: than imported, since `segmenter.py` imports *from* this module (a
#: reverse import would close a cycle).
_ANIMATE_QUALIFIER_SUBTYPES: frozenset[str] = frozenset({
    "spirit", "elemental", "plant", "horror", "shade", "boar", "wall",
    "elf", "goblin", "zombie", "human", "wizard", "merfolk", "vampire",
    "dragon", "angel", "demon", "soldier", "knight", "warrior", "giant",
    "dwarf", "faerie", "sliver", "rogue", "cleric", "shaman", "druid", "construct",
    "beast", "bird", "cat", "dog", "insect", "snake", "treefolk", "wolf",
    # PAR-124: Disturbed Slumber's own animate-land target ("4/4 dinosaur
    # creature").
    "dinosaur", "bear",
})
#: PAR-79 sixth increment: "~ becomes a 2/2 **blue and black** horror
#: artifact creature …" (Dimir/Azorius/Boros/… Keyrune, Atarka/Dromoka
#: Monument-shaped — the single biggest blocker on this whole animation
#: shape, 44 SOLO cache cards on the raw "becomes a N/M `<color>` creature"
#: phrase, PAR-79's own share being Dimir Keyrune). `continuous.
#: _apply_layer_5_color`'s ``"color"``-kind static already exists and is
#: already reachable through `extra_statics` (the exact mechanism the
#: keyword-grant branch just below already uses) — only the colour-word
#: recognition itself was missing, the same "primitive already exists, only
#: the parser row doesn't reach it" shape this whole increment keeps
#: finding. A leading, "and"-joined run of colour words right before the
#: type/subtype qualifiers — real cards print one or two, never more.
_ANIMATE_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}
_ANIMATE_COLOR_PREFIX_RE = re.compile(
    r"^(?P<colors>(?:white|blue|black|red|green)"
    r"(?:\s+and\s+(?:white|blue|black|red|green))*)\s+", re.IGNORECASE,
)


def _split_animate_qualifiers(text: str) -> Optional[tuple[list[str], list[str], list[str]]]:
    """A "[`<colors>`] `<word>` `<word>` …" blob right before "creature" →
    ``(colors, add_types, add_subtypes)``, or ``None`` if any non-colour
    word isn't in the curated whitelist above (fail-closed)."""
    colors: list[str] = []
    color_m = _ANIMATE_COLOR_PREFIX_RE.match(text)
    if color_m is not None:
        colors = [
            _ANIMATE_COLOR_WORDS[w.lower()]
            for w in re.split(r"\s+and\s+", color_m.group("colors"))
        ]
        text = text[color_m.end():]
    add_types: list[str] = []
    add_subtypes: list[str] = []
    for word in text.split():
        word = word.strip().lower()
        if not word:
            continue
        if word == "legendary":
            continue  # RULE 205.4: carried separately as a supertype flag.
        if word in _ANIMATE_QUALIFIER_TYPES:
            add_types.append(word)
        elif word in _ANIMATE_QUALIFIER_SUBTYPES or word in CREATURE_SUBTYPES:
            # PAR-185: RULE 205.3m's full vocabulary (Blinkmoth, Ooze, Golem, Phyrexian, …), not a per-card word list.
            add_subtypes.append("-".join(part.capitalize() for part in word.split("-")))
        else:
            return None
    return colors, add_types, add_subtypes


_ANIMATE_WITH = (
    r'(?: with (?=[a-z"])(?:(?P<kw>[a-z0-9{}, ]+?)(?: and )?)?(?:"(?P<ability>[^\"]+)")?)?'
)


def _animate_grants(m: re.Match[str]) -> Optional[list[dict[str, Any]]]:
    """Validate keyword and quoted-ability axes through the shared grant parsers."""
    extra: list[dict[str, Any]] = []
    kw = m.groupdict().get("kw")
    if kw:
        if kw.endswith("all creature types"):
            extra.append({"type": "type_change", "params": {"add_subtypes": ["Changeling"]}})
            kw = re.sub(r"(?: and )?all creature types$", "", kw).strip()
        if kw:
            resolved = flag_keywords_and_ward(kw)
            if resolved is None:
                return None
            keywords, ward_cost = resolved
            extra.append({"type": "grant_keyword", "params": {"keywords": keywords,
                          **({"ward_cost": ward_cost} if ward_cost else {})}})
    ability = m.groupdict().get("ability")
    if ability:
        grants = quoted_ability_grant_effects_list(ability)
        if not grants:
            return None
        extra.extend(g.to_dict() for g in grants)
    return extra



_ANIMATE_DURATION_WORDS = FIXED_DURATION_PATTERN
_ANIMATE_DURATION = rf"(?: (?P<duration>{_ANIMATE_DURATION_WORDS}))?"
_ANIMATE_DURATIONS = FIXED_DURATIONS


def _animation_duration(m: re.Match[str]) -> str:
    words = m.groupdict().get("leading_duration") or m.groupdict().get("duration")
    return _ANIMATE_DURATIONS.get(words, "rest_of_game")


def _new_animation_retention_is_supported(m: re.Match[str], *, require_retention: bool = False) -> bool:
    """Keep newly widened forms fail-closed when addition is not retention.

    RULE 205.1a normally replaces types; RULE 205.1b's artifact-creature
    exception also replaces existing creature types when new ones are named.
    The legacy fixed temporary rows stay unchanged; the new permanent/X/
    legendary axes require an explicit retention rider or a safe artifact
    creature form without a creature-subtype overwrite.
    """
    text = re.sub(r'"[^\"]*"', "", m.group(0))
    if re.search(r"\bstill (?:an? )?(?:snow )?(?:land|artifact|enchantment|creature|planeswalker|battle)s?\b"
                 r"|in addition to (?:its|their) other types", text):
        return True
    newly_widened = (require_retention or m.groupdict().get("legendary") or "legendary" in m.group("quals").split()
                     or m.group("p") == "x" or m.group("t") == "x"
                     or _animation_duration(m) != "end_of_turn")
    if not newly_widened:
        return True
    qualifiers = _split_animate_qualifiers(m.group("quals"))
    return bool(qualifiers and "artifact" in qualifiers[1] and not qualifiers[2])


_ANIMATE_SELF_RE = compile_clause(
    r"~ becomes an? (?P<legendary>legendary )?(?P<p>\d+|x)/(?P<t>\d+|x) (?P<quals>(?:[a-z-]+ )*?)creature"
    + _ANIMATE_WITH + r"(?: that'?s still a land)?" + _ANIMATE_DURATION
    # PAR-79 sixth increment: "… until end of turn and can't be blocked
    # this turn." (Dimir Keyrune-shaped) — the same one-sentence pump-and-
    # unblockable tail `_pump_unblockable`/`_pump_keyword_unblockable`
    # already accept, on this animation primitive's own bare-self form.
    + r"(?P<unblockable> and can'?t be blocked this turn)?"
    # PAR-185: the printed-type reminder ("it's still a land") is pure reminder text, RULE 205.1b retains prior types.
    r"(?:\. it'?s still a land)?"
)

# PAR-98: Creeping Tar Pit puts the duration first and uses full stops for
# the land reminder and unblockable rider, rather than the normal one-sentence
# "becomes … until end of turn and can't …" ordering.
_ANIMATE_SELF_LEADING_EOT_RE = compile_clause(
    rf"(?P<leading_duration>{_ANIMATE_DURATION_WORDS}), ~ becomes an? (?P<legendary>legendary )?(?P<p>\d+|x)/(?P<t>\d+|x) "
    r"(?P<quals>(?:[a-z-]+ )*?)creature"
    + _ANIMATE_WITH +
    r"(?:\. it'?s still a land)?(?:\. it can'?t be blocked this turn)?"
)


def _animate_self(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if not _new_animation_retention_is_supported(m):
        return None
    quals = _split_animate_qualifiers(m.group("quals"))
    if quals is None:
        return None
    colors, add_types, add_subtypes = quals
    static: dict[str, Any] = {
        "type": "type_change",
        "params": {
            "add_types": ["creature"] + add_types,
            **({"legendary": True} if m.groupdict().get("legendary") or "legendary" in m.group("quals").split() else {}),
            "power": count_or_x_of(m.group("p")), "toughness": count_or_x_of(m.group("t")),
            **({"add_subtypes": add_subtypes} if add_subtypes else {}),
        },
    }
    extra_statics = []
    if colors:
        extra_statics.append({"type": "color", "params": {"colors": colors, "set": True}})
    grants = _animate_grants(m)
    if grants is None:
        return None
    extra_statics.extend(grants)
    specs = [EffectSpec("grant_until", {
        "duration": _animation_duration(m), "target_kind": None, "self_subject": True, "static": static,
        **({"extra_statics": extra_statics} if extra_statics else {}),
    })]
    if m.groupdict().get("unblockable"):
        specs.append(EffectSpec("unblockable", {"target_kind": None}))
    return specs


def _animate_self_leading_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if not _new_animation_retention_is_supported(m):
        return None
    quals = _split_animate_qualifiers(m.group("quals"))
    if quals is None:
        return None
    colors, add_types, add_subtypes = quals
    static: dict[str, Any] = {
        "type": "type_change",
        "params": {
            "add_types": ["creature"] + add_types,
            **({"legendary": True} if m.groupdict().get("legendary") or "legendary" in m.group("quals").split() else {}),
            "power": count_or_x_of(m.group("p")), "toughness": count_or_x_of(m.group("t")),
            **({"add_subtypes": add_subtypes} if add_subtypes else {}),
        },
    }
    extra_statics = []
    if colors:
        extra_statics.append({"type": "color", "params": {"colors": colors, "set": True}})
    grants = _animate_grants(m)
    if grants is None:
        return None
    extra_statics.extend(grants)
    specs = [EffectSpec("grant_until", {
        "duration": _animation_duration(m), "target_kind": None, "self_subject": True, "static": static,
        **({"extra_statics": extra_statics} if extra_statics else {}),
    })]
    if m.group(0).lower().endswith("can't be blocked this turn"):
        specs.append(EffectSpec("unblockable", {"target_kind": None}))
    return specs


#: PAR-135: "…a black Zombie in addition to its other **colors and** types" (Liliana, Death's Majesty, Dread
#: Slaver, Ever After) / "becomes blue in addition to its other **colors**" (Indigo Faerie) — the colour is an
#: *added* colour (a layer-5 `color` static with ``set: False``), where a colour word without that tail means
#: "is exactly that colour" and stays unmodeled. The article is optional only for the colour-only spelling.
_BECOMES_IN_ADDITION_BODY = (
    r" (?:an? )?(?:(?P<bp>\d+)/(?P<bt>\d+) )?(?P<words>[a-z]+(?: [a-z]+)*?)"
    # "…a green Bear creature **with base power and toughness 4/4** in addition to …" (Halsin) — the other
    # spelling of the same base P/T a leading "4/4" gives.
    r"(?: with base power and toughness (?P<bp2>\d+)/(?P<bt2>\d+))?"
    rf"(?: with (?P<kws>{BIA_KEYWORD_LIST}))?"
    r" in addition to its other (?P<scope>colors and types|colors|types)"
    rf"(?: and gains (?P<kw>{BIA_KEYWORD}))?"
    r"(?P<eot> until end of turn)?"
)
#: "it"/"that creature" — only offered once the previous clause announced a pick. "it's a …" is the
#: rider spelling after a put/return ("put a flying counter on it. It's a Spirit in addition …").
_BECOMES_IN_ADDITION_PREVIOUS_RE = compile_clause(
    rf"(?:(?P<prev>it)(?: becomes|'s)|(?P<prev2>that (?:creature|permanent|land|artifact)|each of those creatures)"
    rf"(?: becomes| is))"
    rf"{_BECOMES_IN_ADDITION_BODY}"
)
#: "it" after a counter put on the source (Phantom Train) — the source itself, see
#: `segmenter._puts_counter_on_source`.
_BECOMES_IN_ADDITION_SELF_PRONOUN_RE = compile_clause(rf"(?P<self>it)(?: becomes|'s){_BECOMES_IN_ADDITION_BODY}")
#: "~" / "target creature" name their subject outright.
_BECOMES_IN_ADDITION_RE = compile_clause(rf"(?:(?P<self>~)|{TARGET}) becomes{_BECOMES_IN_ADDITION_BODY}")


def _becomes_in_addition(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    words = m.group("words").lower().split()
    scope = m.group("scope")
    added_colors: list[str] = []
    if scope == "types":
        if any(w in COLOR_LETTERS for w in words):
            return None  # "becomes a black Zombie in addition to its other types" replaces the colour
    else:
        while words and words[0] in COLOR_LETTERS and words[0] != "colorless":
            added_colors.append(COLOR_LETTERS[words.pop(0)])
        if not added_colors or (scope == "colors" and words):
            return None
    type_params = type_addition_params(" ".join(words)) if words else {}
    if type_params is None:
        return None
    base_pt = (m.group("bp"), m.group("bt")) if m.group("bp") is not None else (m.group("bp2"), m.group("bt2"))
    if base_pt[0] is not None:
        if "creature" not in type_params.get("add_types", []):
            return None
        type_params = {**type_params, "power": int(base_pt[0]), "toughness": int(base_pt[1])}
    statics: list[dict[str, Any]] = []
    if type_params:
        statics.append({"type": "type_change", "params": type_params})
    if added_colors:
        statics.append({"type": "color", "params": {"colors": added_colors, "set": False}})
    params: dict[str, Any] = {
        "duration": "end_of_turn" if m.group("eot") else "rest_of_game",
        "static": statics[0],
    }
    if len(statics) > 1:
        params["extra_statics"] = statics[1:]
    keywords = [
        CREATURE_FILTER_KEYWORD_WORDS[w]
        for w in re.split(r", and |, | and ", m.group("kws") or "") if w
    ]
    if m.group("kw"):
        keywords.append(CREATURE_FILTER_KEYWORD_WORDS[m.group("kw")])
    if keywords:
        params["extra_statics"] = [*params.get("extra_statics", []),
                                   {"type": "grant_keyword", "params": {"keywords": keywords}}]
    groups = m.groupdict()
    if groups.get("prev") or groups.get("prev2"):
        params["previous_subject"] = True
        params["target_kind"] = None
    elif groups.get("self"):
        params["self_subject"] = True
        params["target_kind"] = None
    else:
        kind = resolve_target_kind(groups["target"])
        if not target_kind_allowed(kind, ("creature", "permanent", "creature_you_control", "land", "artifact")):
            return None
        params["target_kind"] = kind
        params.update(optional_param(m))
    return [EffectSpec("grant_until", params)]


_ANIMATE_QUOTED_CDA_RE = compile_clause(
    r"(?:(?P<eot>until end of turn), )?"
    r"(?P<subject>~|target land you control|the goblin sparring grounds) becomes a "
    r"(?P<quals>[a-z ]*?)creature "
    r"(?:with|in addition to its other types and gains) "
    r"(?:(?P<kw>haste) and )?"
    r'"(?P<cda>~\'s power and toughness are each equal to [^\"]+)"'
    r"(?: it'?s still a land)?"
)


def _animate_quoted_cda(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """Animate once, granting the quoted P/T definition to that object."""

    parsed = static_effect_specs(m.group("cda"))
    if not parsed or len(parsed) != 1 or parsed[0].type != "pt_cda":
        return None
    quals = _split_animate_qualifiers(m.group("quals"))
    if quals is None:
        return None
    colors, add_types, add_subtypes = quals
    extra = [parsed[0].to_dict()]
    if colors:
        extra.append({"type": "color", "params": {"colors": colors, "set": True}})
    if m.group("kw"):
        extra.append({"type": "grant_keyword", "params": {"keywords": ["haste"]}})
    subject = m.group("subject").lower()
    return [EffectSpec("grant_until", {
        "duration": "end_of_turn" if m.group("eot") else "rest_of_game",
        "target_kind": "land_you_control" if subject == "target land you control" else None,
        "self_subject": subject != "target land you control",
        "static": {"type": "type_change", "params": {
            "add_types": ["creature", *add_types],
            **({"add_subtypes": add_subtypes} if add_subtypes else {}),
        }},
        "extra_statics": extra,
    })]


#: The TARGET sibling — "target land becomes a 3/3 creature until end of
#: turn. It's still a land." (Soilshaper). The trailing "it's still a
#: `<kind>`" sentence is pure reminder text (`type_change`'s ``add_types``
#: only *adds*, RULE 205.1b — prior types are retained), so it's
#: matched and discarded rather than parsed into anything; the ``(?P=kind)``
#: backreference keeps that discard honest (never swallows a mismatched
#: reminder sentence). Optional because not every real card bothers to
#: print the reminder.
#: PAR-79 sixth increment: ``snow `` before the target kind ("target snow
#: land becomes a 2/2 blue elemental creature…", Balduvian Frostwaker) and
#: the same colour-word qualifier support `_animate_self` gained just
#: above — reusing the identical `_split_animate_qualifiers`/`extra_statics`
#: machinery rather than a second copy.
# Shared animation body: subject selection, colors/types/keywords, duration
# and printed type-retention reminders are independent axes.
_ANIMATE_CREATURE_BODY = (
    r"(?P<legendary>legendary )?(?P<p>\d+|x)/(?P<t>\d+|x) (?P<quals>(?:[a-z-]+ )*?)creatures?"
    + _ANIMATE_WITH +
    r"(?: in addition to (?:its|their) other types)?"
    # PAR-185: "… creature that's still a land until end of turn" — reminder text, see `_ANIMATE_SELF_RE`.
    r"(?: (?:that'?s still an? (?:snow )?(?P<retained_kind>land|artifact|enchantment|creature)|that are still lands))?"
    + _ANIMATE_DURATION
    + r"(?P<source_duration> for as long as ~ remains on the battlefield)?"
    rf"(?: for as long as it has an? (?P<duration_counter>{NAMED_COUNTER_KIND}) counter on it)?"
)
_ANIMATE_TARGET_RE = compile_clause(
    r"(?P<up_to_one>up to 1 )?(?P<attached>enchanted |target )(?:snow )?(?P<kind>land|plains|island|swamp|mountain|forest|artifact|creature|enchantment|creature or land)"
    r"(?P<you_control> you control)? becomes an? "
    + _ANIMATE_CREATURE_BODY +
    r"(?:\. it'?s still an? (?:snow )?(?P<retained_sentence>(?P=kind)|land))?"
    r"(?P<must_blocked>\. it must be blocked this turn if able)?"
)
_ANIMATE_PREVIOUS_RE = compile_clause(
    r"(?P<previous>it|they|that (?:creature|permanent|land|artifact)|"
    r"(?:each of )?those (?:creatures|permanents|lands|artifacts)) (?:becomes?|is|are) (?:an? )?"
    + _ANIMATE_CREATURE_BODY +
    r"(?:\. (?:it'?s|they'?re) still (?:an? )?(?:snow )?"
    r"(?:land|artifact|enchantment|creature|planeswalker|battle)s?)?"
    r"(?P<must_blocked>\. (?:it|they) must be blocked this turn if able)?"
)
_ANIMATE_SELF_PRONOUN_RE = compile_clause(
    r"(?P<self>it) becomes an? " + _ANIMATE_CREATURE_BODY + r"(?:\. it'?s still a land)?"
)
_ANIMATE_MULTI_RE = compile_clause(
    rf"(?:(?P<leading_duration>{_ANIMATE_DURATION_WORDS}), )?{MULTI_TARGET_QUANTIFIER}(?P<target>{MULTI_TARGET_ALT}) "
    r"(?:each )?become " + _ANIMATE_CREATURE_BODY + r"(?:\. they'?re still lands)?"
)


def _animate_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    target = multi_target_params(m)
    if target is None or target["target_kind"] not in {"land", "land_you_control"}:
        return None
    inner = match_clause(
        "it becomes a " + m.group(0)[m.start("legendary") if m.groupdict().get("legendary") else m.start("p"): ], reading=ClauseReading(previous_subject=True),
    )
    if not inner:
        return None
    params = dict(inner[0].params)
    params.pop("previous_subject", None)
    params.update(target)
    params["duration"] = _animation_duration(m)
    return [EffectSpec("grant_until", params)]


def _animate_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    new_dimensions_or_supertype = (m.group("p") == "x" or m.group("t") == "x"
                                   or m.groupdict().get("legendary")
                                   or "legendary" in m.group("quals").split())
    source_pronoun = bool(m.groupdict().get("self"))
    if (new_dimensions_or_supertype or source_pronoun) and not _new_animation_retention_is_supported(
        m, require_retention=source_pronoun,
    ):
        return None
    quals = _split_animate_qualifiers(m.group("quals"))
    if quals is None:
        return None
    colors, add_types, add_subtypes = quals
    previous = bool(m.groupdict().get("previous"))
    self_subject = bool(m.groupdict().get("self"))
    attached = m.groupdict().get("attached") == "enchanted "
    retained = m.groupdict().get("retained_kind") or m.groupdict().get("retained_sentence")
    if not (previous or self_subject) and retained:
        expected = m.group("kind")
        if retained != expected and not (retained == "land" and expected in {"plains", "island", "swamp", "mountain", "forest", "creature or land"}):
            return None
    kind = None if previous or self_subject or attached else resolve_target_kind(
        "target " + m.group("kind") + (m.group("you_control") or "")
    )
    if kind is None and not (previous or self_subject or attached):
        return None
    static: dict[str, Any] = {
        "type": "type_change",
        "params": {
            "add_types": ["creature"] + add_types,
            **({"legendary": True} if m.groupdict().get("legendary") or "legendary" in m.group("quals").split() else {}),
            "power": count_or_x_of(m.group("p")), "toughness": count_or_x_of(m.group("t")),
            **({"add_subtypes": add_subtypes} if add_subtypes else {}),
            **({"affects": "attached_permanent"} if attached else {}),
        },
    }
    extra_statics = []
    if colors:
        extra_statics.append({"type": "color", "params": {"colors": colors, "set": True}})
    grants = _animate_grants(m)
    if grants is None:
        return None
    extra_statics.extend(grants)
    specs = [EffectSpec("grant_until", {
        "duration": _animation_duration(m),
        "target_kind": kind, "static": static,
        **({"optional": True} if m.groupdict().get("up_to_one") else {}),
        **({"previous_subject": True} if previous else {}),
        **({"self_subject": True} if self_subject else {}),
        **({"lock_group": True} if attached else {}),
        **({"duration": "for_as_long_as", "condition": {"kind": "source_on_battlefield"}}
           if m.groupdict().get("source_duration") else {}),
        **({"duration": "for_as_long_as", "condition": {"kind": "source_counters", "of": "affected",
             "counter": m.group("duration_counter"), "min": 1}}
           if m.groupdict().get("duration_counter") else {}),
        **({"extra_statics": extra_statics} if extra_statics else {}),
    })]
    if m.groupdict().get("must_blocked"):
        specs.append(EffectSpec("pump", {"previous_subject": True, "keywords": ["must_be_blocked"]}))
    return specs


#: PAR-124: the TARGET sibling of `_ANIMATE_SELF_LEADING_EOT_RE` — "Until
#: end of turn, target land you control becomes a 4/4 dinosaur creature
#: with reach and haste. It's still a land." (Disturbed Slumber/Elemental
#: Uprising) puts the duration in front of "target …", unlike
#: `_ANIMATE_TARGET_RE`'s trailing-``eot`` ordering. A trailing "it must be
#: blocked this turn if able." sentence, when present, is folded into this
#: same regex rather than left to the generic `previous_subject`
#: connector-split pipeline — that split would hand the *pure-reminder*
#: "it's still a land" sentence its own unclaimed part first (nothing
#: builds an `EffectSpec` for it alone), failing the whole body closed
#: before the tail is ever reached (see `_ANIMATE_TARGET_RE`'s identical
#: reasoning).
_ANIMATE_TARGET_LEADING_EOT_RE = compile_clause(
    rf"(?P<leading_duration>{_ANIMATE_DURATION_WORDS}), (?P<up_to_one>up to 1 )?(?P<attached>enchanted |target )(?:snow )?"
    r"(?P<kind>land|plains|island|swamp|mountain|forest|artifact|creature|enchantment|creature or land)"
    r"(?P<you_control> you control)? becomes "
    r"an? " + _ANIMATE_CREATURE_BODY +
    r"(?:\. it'?s still an? (?:snow )?(?P<retained_sentence>(?P=kind)|land))?"
    r"(?P<must_blocked>\. it must be blocked this turn if able)?"
)


def _animate_target_leading_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    specs = _animate_target(m)
    if specs is None:
        return None
    return specs


#: PAR-185: "all lands you control become 1/1 creatures until end of turn. They're still lands." (Life // Death) —
#: the mass sibling of `_ANIMATE_TARGET_RE`. RULE 611.2c: the group is fixed when the spell resolves (``lock_group``),
#: so a land that enters later is not animated; the reminder sentence is discarded (RULE 205.1b retains prior types).
_ANIMATE_ALL_LANDS_RE = compile_clause(
    rf"(?:(?P<leading_duration>{_ANIMATE_DURATION_WORDS}), )?"
    r"(?:all )?(?P<lands>lands|plains|islands|swamps|mountains|forests)"
    r"(?P<controller> you control| target player controls)? become "
    + _ANIMATE_CREATURE_BODY + r"(?:\. they'?re still lands)?"
)


def _animate_all_lands(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # Reuse the same characteristic and ability body as a single animation;
    # only its subject changes to a resolve-time captured group.
    inner = match_clause("it becomes a " + m.group(0)[m.start("legendary") if m.groupdict().get("legendary") else m.start("p"): ],
                         reading=ClauseReading(previous_subject=True))
    if not inner:
        return None
    params = dict(inner[0].params)
    params.pop("previous_subject", None)
    controller = m.group("controller")
    subject = m.group("lands")
    of = "you" if controller else "any"
    subtype = {"plains": "plains", "islands": "island", "swamps": "swamp",
               "mountains": "mountain", "forests": "forest"}.get(subject)
    affects = ({"zone": "battlefield", "of": of, "filter": {"card_type": "land", "subtype": subtype}}
               if subtype else "lands_you_control" if controller else "all_lands")
    params["static"] = {**params["static"], "params": {**params["static"]["params"], "affects": affects}}
    params.update({"duration": _animation_duration(m), "lock_group": True,
                   "target_kind": "player" if controller == " target player controls" else None})
    if controller == " target player controls":
        params["group_controller"] = "target_player"
    return [EffectSpec("grant_until", params)]


ROWS: list[EffectHandler] = [
    EffectHandler(
        "you_gain_life_eq_that_creature_mv",
        _YOU_GAIN_LIFE_EQ_THAT_CREATURE_MV_RE,
        _you_gain_life_eq_that_creature_mv,
    ),
    EffectHandler(
        "equipped_creature_unblockable",
        compile_clause(r"equipped creature can'?t be blocked this turn"),
        _equipped_creature_unblockable,
    ),
    EffectHandler(
        "self_and_other_unblockable",
        _SELF_AND_OTHER_UNBLOCKABLE_RE,
        _self_and_other_unblockable,
    ),
    EffectHandler(
        "color_creatures_unblockable",
        _COLOR_CREATURES_UNBLOCKABLE_RE,
        _color_creatures_unblockable,
    ),
    EffectHandler("x_power_unblockable", _X_POWER_UNBLOCKABLE_RE, _x_power_unblockable),
    EffectHandler("x_targets_unblockable", _X_TARGETS_UNBLOCKABLE_RE, _x_targets_unblockable),
    # PAR-140: "it becomes a Rogue in addition to its other types" — "it" is the previous clause's pick,
    # so the row is only offered when that clause announced one (`previous_subject_only`).
    EffectHandler(
        "becomes_in_addition_previous", _BECOMES_IN_ADDITION_PREVIOUS_RE, _becomes_in_addition,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "becomes_in_addition_self_pronoun", _BECOMES_IN_ADDITION_SELF_PRONOUN_RE, _becomes_in_addition,
        requires=ClauseReading(self_subject=True),
        # A self trigger whose earlier clause chose a target ("…put a counter on target Food. If you do, it
        # becomes…", Cinnamon): "it" is the nearer antecedent, the target, so the previous-target row wins.
        fallback_for=("becomes_in_addition_previous",),
    ),
    EffectHandler("becomes_in_addition", _BECOMES_IN_ADDITION_RE, _becomes_in_addition),
    EffectHandler(
        "animate_quoted_cda",
        _ANIMATE_QUOTED_CDA_RE,
        _animate_quoted_cda,
    ),
    EffectHandler(
        "animate_self",
        _ANIMATE_SELF_RE,
        _animate_self,
    ),
    EffectHandler(
        "animate_self_leading_eot",
        _ANIMATE_SELF_LEADING_EOT_RE,
        _animate_self_leading_eot,
    ),
    EffectHandler(
        "animate_previous", _ANIMATE_PREVIOUS_RE, _animate_target,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "animate_self_pronoun", _ANIMATE_SELF_PRONOUN_RE, _animate_target,
        requires=ClauseReading(self_subject=True),
        fallback_for=("becomes_in_addition_previous",),
    ),
    EffectHandler("animate_multi", _ANIMATE_MULTI_RE, _animate_multi),
    EffectHandler(
        "animate_target",
        _ANIMATE_TARGET_RE,
        _animate_target,
    ),
    # RULE 613.1d/613.4b: the alternative noun order says the same type
    # and base-P/T change (Tezzeret the Schemer's emblem).
    EffectHandler(
        "animate_target_base_pt_order",
        compile_clause(rf"{TARGET} becomes an? (?P<quals>[a-z ]*?)creature with base power and toughness "
           r"(?P<p>\d+)/(?P<t>\d+)(?P<duration> until end of turn)?"),
        lambda m: match_clause(f"{m.group('target')} becomes a {m.group('p')}/{m.group('t')} "
                               f"{m.group('quals')}creature{m.group('duration') or ''}"),
    ),
    EffectHandler("animate_all_lands", _ANIMATE_ALL_LANDS_RE, _animate_all_lands),
    EffectHandler(
        "animate_target_leading_eot",
        _ANIMATE_TARGET_LEADING_EOT_RE,
        _animate_target_leading_eot,
    ),
    # "goad target creature [an opponent controls]" (RULE 701.15a).
    EffectHandler(
        "goad",
        compile_clause(rf"goad {TARGET}"),
        _goad,
    ),
    # PAR-150: "goad up to two target creatures" (RULE 115.1a plural of the row above).
    EffectHandler("goad_multi_target", _GOAD_MULTI_RE, _goad_multi),
    # "the tokens are goaded for the rest of the game" — the tokens an
    # earlier clause of this same ability created (`created_objects`).
    EffectHandler(
        "goad_created",
        compile_clause(r"the tokens? (?:is|are) goaded for the rest of the game"),
        _goad_created,
    ),
    # "goad it" / "goad that creature" — the previous clause's target.
    EffectHandler(
        "goad_previous",
        compile_clause(r"goad (?:it|that creature|them|those creatures)"),  # PAR-150: the plural pronoun (Coronation of Chaos)
        _goad_previous,
        requires=ClauseReading(previous_subject=True),
    ),
    # "all suspected creatures are no longer suspected" (RULE 701.60a's
    # reverse) — before the `suspect {TARGET}` row, which can't match it
    # (no "target") but reads better kept together.
    EffectHandler(
        "remove_suspected_all",
        compile_clause(r"all suspected creatures are no longer suspected"),
        _remove_suspected_all,
    ),
    EffectHandler(
        "suspected_self_counter_or_suspect",
        compile_clause(r"if ~ is suspected, put a \+1/\+1 counter on it\. otherwise, suspect it"),
        _suspected_self_counter_or_suspect,
        requires=ClauseReading(self_subject=True),
    ),
    # "you may have it become no longer suspected" (RULE 701.60a's reverse,
    # PAR-30 — Deadly Complication) — "it" = the previous clause's target.
    EffectHandler(
        "remove_suspected_may_previous",
        compile_clause(r"you may have it become no longer suspected"),
        _remove_suspected_may_previous,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler(
        "remove_suspected_previous_selector",
        compile_clause(r"if any of them are suspected, (?:they'?re|they are) no longer suspected"),
        _remove_suspected_previous_selector,
        requires=ClauseReading(previous_selector=True),
    ),
    # "suspect enchanted creature" (RULE 701.60a) — an Aura's host.
    EffectHandler(
        "suspect_attached",
        compile_clause(r"suspect enchanted creature"),
        _suspect_attached,
    ),
    # Frantic Scapegoat: "the other creatures" are the ones its batch trigger counted
    # (PAR-119, `SuspectEffect` reads the event's ``matching_ids``); "~" is explicit.
    EffectHandler(
        "suspect_other_then_remove_self",
        compile_clause(r"you may suspect 1 of the other creatures\. if you do, ~ is no longer suspected"),
        _suspect_other_then_remove_self,
    ),
    # "suspect [up to N] target creature [an opponent controls]" (RULE 701.60a).
    EffectHandler(
        "suspect_target",
        compile_clause(rf"suspect {TARGET}"),
        _suspect_target,
    ),
    # "suspect it" — explicit self ("when ~ enters, suspect it").
    EffectHandler(
        "suspect_self",
        compile_clause(r"suspect (?:it|~)"),
        _suspect_self,
        requires=ClauseReading(self_subject=True),
    ),
    # "suspect it" / "suspect that creature" — the previous clause's target
    # ("gain control of target creature … suspect it", Caught Red-Handed).
    EffectHandler(
        "suspect_previous",
        compile_clause(r"suspect (?:it|that creature)"),
        _suspect_previous,
        requires=ClauseReading(previous_subject=True),
    ),
    # "detain up to two target creatures your opponents control" (RULE
    # 701.35a) — before the singular row, which its `TARGET` can't match
    # (plural) but reads better kept together.
    EffectHandler(
        "detain_multi",
        _DETAIN_MULTI_RE,
        _detain_multi,
    ),
    # "detain [up to one] target creature/nonland permanent an opponent
    # controls" (RULE 701.35a).
    EffectHandler(
        "detain",
        compile_clause(rf"detain {TARGET}"),
        _detain,
    ),
    EffectHandler("manifest_dread_then_attach", _MANIFEST_DREAD_THEN_ATTACH_RE, _manifest_dread_then_attach),
    # "manifest dread" (RULE 701.40a) — tried before the plain manifest row
    # below, which would otherwise not match it at all but reads more
    # naturally kept in this order alongside its sibling.
    EffectHandler(
        "manifest_dread",
        compile_clause(r"manifest dread"),
        _manifest_dread,
    ),
    EffectHandler(
        "reduce_spell_costs_this_turn",
        _REDUCE_COSTS_THIS_TURN_RE,
        _reduce_costs_this_turn,
    ),
    EffectHandler(
        "turn_face_up_chosen",
        compile_clause(r"(?P<may>you may )?turn a (?P<what>permanent|face-down permanent|face-down creature)"
           r" you control face up"),
        _turn_face_up_chosen,
    ),
    # "manifest the top card of your library" / "…the top two cards…" and
    # cloak's identical shape (RULE 701.40a/701.58a).
    EffectHandler(
        "manifest",
        compile_clause(rf"(?P<verb>manifest|cloak) the top (?:{COUNT} )?cards? of your library"),
        _manifest,
    ),
    # "proliferate twice" / "proliferate N times" (RULE 701.30) — tried
    # before the bare `proliferate` row below since it's a strict superset.
    EffectHandler(
        "proliferate_n_times",
        compile_clause(r"proliferate (?:(?P<twice>twice)|(?P<n>\d+) times)"),
        _proliferate_n_times,
    ),
    # "proliferate" (RULE 701.30) — bare.
    EffectHandler(
        "proliferate",
        compile_clause(r"proliferate"),
        _proliferate,
    ),
    # "double the number of [+1/+1] counters on <~ / target creature / each
    # creature you control / it>." (Primordial Hydra / Tanazir Quandrix /
    # Kalonian Hydra / Growth Curve — 27 SOLO).
    EffectHandler(
        "double_counters",
        _DOUBLE_COUNTERS_RE,
        _double_counters,
    ),
    # "Damage can't be prevented this turn." (RULE 615.6)
    EffectHandler(
        "disable_damage_prevention",
        _DISABLE_DAMAGE_PREVENTION_RE,
        _disable_damage_prevention,
    ),
    # "remove all counters from all permanents" (RULE 122 — Oblivion Stone/
    # Aether Snap/Thief of Blood-shaped).
    EffectHandler(
        "remove_counters_all_permanents",
        compile_clause(r"remove all counters from all permanents"),
        _remove_counters_all_permanents,
    ),
    # "remove all counters from target permanent" (Vampire Hexmage-shaped).
    EffectHandler(
        "remove_counters_target",
        compile_clause(r"remove all counters from target permanent"),
        _remove_counters_target,
    ),
    # "remove all `<kind>` counters from ~." (Coalition Relic/Ventifact
    # Bottle) — see `_REMOVE_ALL_NAMED_COUNTERS_SELF_RE`.
    EffectHandler(
        "remove_all_named_counters_self",
        _REMOVE_ALL_NAMED_COUNTERS_SELF_RE,
        _remove_all_named_counters_self,
    ),
    # "remove up to N counters from target permanent/creature" (Glissa
    # Sunslayer/Heartless Act/Render Inert-shaped) — see
    # `_REMOVE_COUNTERS_CHOICE_RE`.
    EffectHandler(
        "remove_counters_choice",
        _REMOVE_COUNTERS_CHOICE_RE,
        _remove_counters_choice,
    ),
    # "You may play an additional land this turn." / "You may play up to
    # two additional lands this turn." (RULE 305.2 one-turn permission) —
    # see `_EXTRA_LAND_PLAY_RE` above; the standing per-turn static sibling
    # is `catalogue.static_handlers`' `extra_land_drop`.
    EffectHandler(
        "extra_land_play",
        _EXTRA_LAND_PLAY_RE,
        _extra_land_play,
    ),
    # "You become the monarch." / "Target player becomes the monarch."
    # (RULE 725.1).
    EffectHandler(
        "become_monarch",
        compile_clause(r"(?P<who>you |target player )?becomes? the monarch"),
        _become_monarch,
    ),
    # "You take the initiative." / "Target player takes the initiative."
    # (RULE 726.1) — RULE 726.2's "venture into the dungeon" companion isn't
    # modeled (dungeons/RULE 309 aren't built yet); see
    # `game/effects/core.py`'s `TakeInitiativeEffect`.
    EffectHandler(
        "take_initiative",
        compile_clause(r"(?P<who>you |target player )?takes? the initiative"),
        _take_initiative,
    ),
    # "You get an emblem with '<ability>'." (RULE 114.2) — see
    # `_emblem_ability_spec` above.
    EffectHandler(
        "create_emblem",
        _EMBLEM_RE,
        _create_emblem,
    ),
    # RULE 603.2: use the cast event's payment snapshot, even after that
    # spell has left the stack (Chandra, Dressed to Kill).
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par149_emblem_bodies.py (emblem body, parsed outside a card's own ability lines).
    EffectHandler(
        "damage_cast_mana_spent",
        compile_clause(rf"{re.escape(SELF)} deals x damage to {TARGET}, where x is the amount of mana spent to cast that spell"),
        lambda m: [EffectSpec("damage", {"target_kind": resolve_target_kind(m.group("target")),
                                         "amount_from_trigger_event": "mana_spent"})]
        if resolve_target_kind(m.group("target")) is not None else None,
    ),
    # RULE 701.8: discarding the entire hand is mandatory, with no subset
    # choice (Sarkhan's emblem, and the same ordinary spell/trigger body).
    EffectHandler(
        "discard_whole_hand",
        compile_clause(r"(?:you )?discard (?:your hand|all (?:the )?cards in your hand)"),
        lambda m: [EffectSpec("discard", {"whole_hand": True})],
    ),
    # "Create that many 1/1 green Elf Warrior creature tokens." (Lathril,
    # Blade of the Elves-shaped) — tried before the plain `create_token`
    # row below, same "strict superset" reasoning.
    EffectHandler(
        "create_token_that_many",
        _CREATE_TOKEN_THAT_MANY_RE,
        _create_token_that_many,
    ),
    # "Create a 1/1 green Elf Warrior creature token for each Elf you
    # control." (Elvish Promenade-shaped) — tried before the plain
    # `create_token` row below since it's a strict superset of that shape.
    EffectHandler(
        "create_token_for_each",
        _CREATE_TOKEN_FOR_EACH_RE,
        _create_token_for_each,
    ),
    # "Create X 1/1 green Elf Warrior creature tokens, where X is the
    # number of attacking creatures." (Galadhrim Ambush-shaped).
    EffectHandler(
        "create_token_xx_source_power",
        _CREATE_TOKEN_XX_SOURCE_POWER_RE,
        _create_token_xx_source_power,
    ),
    EffectHandler(
        "create_token_xx_where",
        _CREATE_TOKEN_XX_WHERE_RE,
        _create_token_xx_where,
    ),
    # RULE 608.2: resolve-time count plus a fixed addend (Liliana's emblem).
    EffectHandler(
        "create_tokens_count_plus",
        compile_clause(r"(?P<create>create x .+), where x is (?P<plus>\d+) plus the number of (?P<group>.+)"),
        _create_tokens_count_plus,
    ),
    # RULE 202.2f/700.6 "create a number of 1/1 white Soldier creature
    # tokens equal to your devotion to white." (Evangel of Heliod/Master of
    # Waves-shaped) — tried before the plain `create_token` row below, same
    # "strict superset" reasoning as the two rows above.
    EffectHandler(
        "create_token_number_equal_devotion",
        _CREATE_TOKEN_NUMBER_EQUAL_DEVOTION_RE,
        _create_token_number_equal_devotion,
    ),
    # "create a 1/1 white Soldier creature token" / "create two 2/2 green Bear
    # creature tokens with trample" — inline creature tokens (fully modeled).
    EffectHandler(
        "create_token_quoted_cda",
        _CREATE_TOKEN_QUOTED_CDA_RE,
        _create_token_quoted_cda,
    ),
    EffectHandler(
        "create_token",
        compile_clause(
            rf"(?P<per_opp>for each opponent, )?(?:(?P<who>you|each player|each opponent|target player|target opponent) )?creates? {COUNT_X} "
            # PAR-148: "create a **tapped and attacking** 1/1 red Devil creature token" (RULE 508.4).
            rf"(?P<pre_ta>tapped and attacking )?(?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
            rf"(?P<mid>[a-z ]*?)creature tokens?"
            # ``0-9`` in the keyword capture is ENG-31's "… token with
            # firebending N" (Fire Nation Attacks/Occupation).
            rf"(?: with (?P<kw>[a-z0-9, ]+?))?"
            # PAR-148: "… token [with flying] **named ballistic boulder**" (Fire Navy Trebuchet, Boulder Jockey).
            rf"(?: named (?P<tname>[a-z][a-z' -]*?))?"
            # "…creature token with \"when ~ dies, you gain N life.\"" — the
            # STX Pest token's own printed death trigger (Blight Mound,
            # Feral Appetite, Pest Rescuer, Hunt for Specimens, …). Baked
            # onto each token via `CreateTokenEffect.token_dies_gain_life`.
            rf'(?: with "when (?:~|it) dies, you gain (?P<dies_life>\d+) life\.?")?'
            # A token owns its quoted ability; validate the entire native
            # ability rather than limiting it to trigger heads. Leave the
            # measured P/T CDA form to its existing branch below.
            rf'(?: with "(?P<token_ab>(?!(?:this token|this creature|~)\x27s power)[^"]+)")?'
            + rf'(?: (?:with|and) "(?P<quoted_cda>(?:this token|this creature|~)\'?s power[^\"]+)")?'
            # PAR-122: "…token that's all colors" (The Fish Brewer) — RULE 105.1's five colors.
            + r"(?P<all_colors> that'?s all colors| that are all colors)?"
            + _TOKEN_TAPPED_ATTACKING
        ),
        _create_token,
    ),
    EffectHandler(
        "create_named_token_quoted_cda",
        _CREATE_NAMED_TOKEN_QUOTED_CDA_RE,
        _create_named_token_quoted_cda,
    ),
    # PAR-13: "Create <Name>, a legendary N/N ... creature token [with
    # <keywords>]." — Cradle of the Death God's own unique Atropal token.
    EffectHandler(
        "create_named_legendary_token",
        _CREATE_NAMED_LEGENDARY_TOKEN_RE,
        _create_named_legendary_token,
    ),
    # "create a Food token, then create a 1/1 white Halfling creature token
    # and attach ~ to it." (Field-Tested Frying Pan) — tried before the
    # plain create-and-attach row below since it's a strict superset (a
    # leading named-token sentence that row's grammar doesn't expect).
    EffectHandler(
        "create_named_then_create_token_and_attach",
        _CREATE_NAMED_THEN_CREATE_TOKEN_AND_ATTACH_RE,
        _create_named_then_create_token_and_attach,
    ),
    # "create a 1/1 white Halfling creature token and attach ~ to it."
    # (Auxiliary Boosters, Living Weapon-adjacent) — the token, then attach
    # the ability's own source onto whatever that just made.
    EffectHandler(
        "create_token_and_attach",
        _CREATE_TOKEN_AND_ATTACH_RE,
        _create_token_and_attach,
    ),
    # "create a Treasure token" / "create two Clue tokens" — named,
    # non-creature artifact tokens (`_NAMED_TOKEN_WORDS`, kept in sync with
    # `data/tokens.json`).
    EffectHandler(
        "create_named_token_that_many",
        _CREATE_NAMED_TOKEN_THAT_MANY_RE,
        _create_named_token_that_many,
    ),
    EffectHandler(
        "create_named_token_per_counter_on_it",
        _CREATE_NAMED_TOKEN_PER_COUNTER_ON_IT_RE,
        _create_named_token_per_counter_on_it,
        requires=ClauseReading(group_subject=True),
    ),
    # "create X Treasure tokens" — X the announced {X}, or a ``bind``-measured one ("…a number of Treasure tokens
    # equal to the result", PAR-147).
    # PAR-152 (Strefan): "create a Blood token for each player who lost life this turn." — RULE 119.3, the
    # event-derived `players_who_lost_life_this_turn` count (Reaper's Scythe's selector).
    EffectHandler(
        "create_named_token_per_player_who_lost_life",
        compile_clause(rf"create an? (?P<name>{'|'.join(NAMED_TOKEN_WORDS)}) token for each player who lost life this turn"),
        lambda m: [EffectSpec("create_token", {
            "count": 1, "token_name": NAMED_TOKEN_WORDS[m.group("name")],
            "count_selector": "players_who_lost_life_this_turn",
        })],
    ),
    EffectHandler(
        "create_named_token_x",
        compile_clause(rf"(?:you )?creates? x (?P<tapped>tapped )?(?P<name>{'|'.join(NAMED_TOKEN_WORDS)}) tokens?"),
        lambda m: [EffectSpec("create_token", {
            "count": "x", "token_name": NAMED_TOKEN_WORDS[m.group("name")],
            **({"tapped": True} if m.group("tapped") else {}),
        })],
    ),
    EffectHandler(
        "create_named_token",
        compile_clause(rf"(?P<who>you |target player |each opponent |each player )?"
           rf"creates? {COUNT} (?P<tapped>tapped )?(?P<name>{'|'.join(NAMED_TOKEN_WORDS)}) tokens?"),
        _create_named_token,
    ),
    # "create a number of tapped Treasure tokens equal to its power."
    # (Goldvein Hydra) — tried before the flat-count row above (its `COUNT`
    # can't match "a number of … equal to …").
    EffectHandler(
        "previous_controller_creates", _PREVIOUS_CONTROLLER_CREATES_RE, _previous_controller_creates,
        reading_aware=True,
        requires=ClauseReading(previous_subject=True),
    ),
    EffectHandler("for_each_this_way", _FOR_EACH_THIS_WAY_RE, _for_each_this_way, reading_aware=True),
    EffectHandler(
        "create_named_token_eq_its_self",
        _CREATE_NAMED_TOKEN_EQ_ITS_RE,
        _create_named_token_eq_its_self,
        requires=ClauseReading(self_subject=True),
    ),
    # "Investigate." / "Investigate twice." / "Investigate 3 times." (RULE
    # 701.19a) — a Clue-token-creation alias.
    EffectHandler(
        "investigate",
        _INVESTIGATE_RE,
        _investigate,
    ),
    # "The Ring tempts you." (RULE 701.51a) — Tales of Middle-earth.
    EffectHandler(
        "ring_tempts_you",
        _RING_TEMPTS_YOU_RE,
        _ring_tempts_you,
    ),
    # "[You may c]ast [sorcery/creature ]spells this turn as though they had
    # flash." (Emergence Zone-shaped, MEC-12; Complete the Circuit's own
    # "sorcery spells" narrowing, PAR-124 — the leading "you may" is already
    # peeled off by `segmenter.peel_optional` before a clause ever reaches
    # this table) — `effects.GrantFlashUntilEndOfTurnEffect.card_types` now
    # carries the optional type-word filter through to `GameState.temp_
    # flash_until_turn_types`.
    EffectHandler(
        "grant_flash_until_eot",
        compile_clause(r"cast (?:(?P<kind>sorcery|creature) )?spells this turn as though they had flash"),
        lambda m: [EffectSpec("grant_flash_until_eot", (
            {"card_types": [m.group("kind")]} if m.group("kind") else {}
        ))],
    ),
]
