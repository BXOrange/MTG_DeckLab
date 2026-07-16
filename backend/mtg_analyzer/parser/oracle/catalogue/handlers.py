"""The effect-clause handler table (docs/09 "THE CATALOGUE").

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE CATALOGUE", step 3 MATCH).
A **handler** is a regex that identifies + extracts an effect clause paired
with a builder that emits `EffectSpec`s (pure data → the `EffectRegistry`,
never executed behaviour). The set covers exactly what the engine already
supports as one-shot effects — damage / draw / discard / destroy / gain_life /
counter — each factored over the shared TARGET / NUMBER sub-grammars so the
table stays small (docs/09 "Factor shared sub-grammars").

Handlers match a single **normalised effect clause** (the segmenter has
already peeled trigger/cost wrappers and split on sentence boundaries), and
they **full-match** it: a clause is claimed only if a handler consumes it
end to end, which is what makes the coverage gate fail-closed (a half-matched
clause is *not* claimed, so its card stays `UNMODELED`).

Pure regex + data — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from ..normalize import SELF
from ..spec import EffectSpec
from .keywords import KEYWORDS, KeywordShape, keyword_slug
from .subgrammars import (
    CANT_BE_COUNTERED_RE,
    COUNT,
    NUMBER,
    SPELL_TARGET,
    TARGET,
    count_of,
    resolve_spell_filter,
    resolve_target_kind,
)

#: Colour words → their WUBRG symbol (for a created token's colours).
_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}
#: Words in a token's description that are supertypes/joiners, not its subtype.
_TOKEN_NOISE_WORDS: frozenset[str] = frozenset(
    {"artifact", "enchantment", "legendary", "snow", "colorless", "and", "or"}
)


@dataclass(frozen=True)
class EffectHandler:
    """One catalogue row: a full-clause regex + a builder emitting `EffectSpec`s."""

    name: str
    regex: re.Pattern[str]
    build: Callable[[re.Match[str]], Optional[list[EffectSpec]]]

    def match(self, clause: str) -> Optional[list[EffectSpec]]:
        """Effects for ``clause`` if this handler claims it whole, else ``None``.

        A builder may still return ``None`` after a regex match (e.g. an
        unrecognised target phrase) — that also means "not claimed", keeping
        the gate fail-closed.
        """
        m = self.regex.fullmatch(clause.strip())
        return self.build(m) if m is not None else None


def _c(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# --- Builders ---------------------------------------------------------------
# Each returns the effect list, or None when the clause can't be safely modeled
# (an unknown target phrase → fail-closed, don't guess).


def _damage(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("damage", {"amount": int(m.group("n")), "target_kind": kind})]


#: "~ deals N damage to each creature/player/opponent" — a *mass* effect
#: (RULE 601.2c), not RULE 115 targeting, so it's a dedicated regex rather
#: than a `TARGET` row (see `subgrammars._TARGET_ROWS`'s note on why "each
#: opponent"/"each player" were deliberately kept out of that grammar).
_DAMAGE_SELECTOR_WORDS: dict[str, str] = {
    "each creature": "each_creature",
    "each player": "each_player",
    "each opponent": "each_opponent",
}


def _damage_selector(m: re.Match[str]) -> list[EffectSpec]:
    selector = _DAMAGE_SELECTOR_WORDS[m.group("selector")]
    return [EffectSpec("damage", {"amount": int(m.group("n")), "selector": selector})]


def _draw(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {"count": count_of(m.group("n"))})]


def _discard(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discard", {"count": count_of(m.group("n"))})]


def _gain_life(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount": int(m.group("n"))})]


def _lose_life(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {"amount": int(m.group("n"))})]


#: "each opponent loses N life" / "each player loses N life" — the same
#: mass/untargeted-selector shape `_DAMAGE_SELECTOR_WORDS` uses (RULE
#: 601.2c, not RULE 115 targeting — see that constant's note on why "each
#: opponent"/"each player" stay out of the `TARGET` grammar).
_LOSE_LIFE_SELECTOR_WORDS: dict[str, str] = {
    "each player": "each_player", "each opponent": "each_opponent",
}


def _lose_life_selector(m: re.Match[str]) -> list[EffectSpec]:
    selector = _LOSE_LIFE_SELECTOR_WORDS[m.group("selector")]
    return [EffectSpec("lose_life", {"amount": int(m.group("n")), "selector": selector})]


def _destroy(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent"):
        return None
    return [EffectSpec("destroy", {"target_kind": kind})]


def _counter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "counter target spell" / "… target noncreature spell" / "… target
    # instant or sorcery spell" / "… target spell with mana value N" — the
    # filter is extracted by the dedicated `SPELL_TARGET` companion grammar
    # (RULE 601.2c/115), not the generic TARGET rows (a countered spell's
    # "kind" is always "spell"; only *which* spells vary). "unless its
    # controller pays <cost>" (RULE 601 "Mana Leak" template) is an optional
    # tail on the same clause, independent of the filter.
    filt = resolve_spell_filter(m.group("target"))
    if filt is None:
        return None
    params: dict = dict(filt)
    if m.groupdict().get("cost"):
        params["unless_pays"] = m.group("cost")
    return [EffectSpec("counter", params)]


def _cant_be_countered(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("cant_be_countered", {})]


def _mill(m: re.Match[str]) -> list[EffectSpec]:
    # "you mill N" / bare "mill N" → self; "target player/opponent mills N" → targeted.
    who = (m.groupdict().get("who") or "").strip()
    params: dict = {"count": int(m.group("n"))}
    if who in ("target player", "target opponent"):
        params["target_kind"] = "player"
    return [EffectSpec("mill", params)]


def _exile(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent"):
        return None
    return [EffectSpec("exile", {"target_kind": kind})]


def _tap(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent"):
        return None
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": kind, "untap": untap})]


#: "Untap this creature" (Devoted Druid's counter-cost untap ability) / "tap
#: ~" — the *self* form, no RULE 115 target at all (`target_kind=None` makes
#: `TapEffect` act on its own source, mirroring `AttachEffect`'s ``~``/"it"
#: self-reference).
_SELF_SUBJECT = r"(?:~|it|this permanent|this creature|this artifact|this land)"


def _tap_self(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": None, "untap": untap})]


#: "return target creature to its owner's hand" / "return a land you control
#: to its owner's hand" (RULE 701.3) — the bounce family. ``target_kind``
#: reuses the shared `TARGET` grammar, so this claims both a genuine RULE 115
#: target and the "a land you control" controller-restricted choice the same
#: way; restricted to the shapes real bounce cards actually use.
_RETURN_TO_HAND_KINDS: frozenset[str] = frozenset(
    {"creature", "permanent", "any", "creature_you_control", "land_you_control"}
)


def _return_to_hand(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in _RETURN_TO_HAND_KINDS:
        return None
    return [EffectSpec("return_to_hand", {"target_kind": kind})]


#: A graveyard clause's card-*type* word, right before "card" — "target
#: [instant or sorcery/nonland permanent/creature/artifact/enchantment/
#: land/permanent] card", or no word at all for a bare "target card"
#: (longest-alternative-first so "nonland permanent" wins over "permanent").
_GRAVEYARD_TYPE_WORD = (
    r"instant or sorcery|nonland permanent|creature|artifact|enchantment|land|permanent"
)
#: A graveyard clause's *scope* — whose graveyard — "your"/"a" (any single
#: graveyard)/"an opponent's" (longest-alternative-first, same reason).
_GRAVEYARD_SCOPE_WORD = r"an opponent'?s|your|a"
#: Scope word → `targeting._GRAVEYARD_SCOPE_PREFIXES` key.
_GRAVEYARD_SCOPE_KIND: dict[str, str] = {
    "your": "graveyard", "a": "any_graveyard", "an opponents": "opponent_graveyard",
}


def _graveyard_target_kind(type_word: Optional[str], scope_word: str) -> Optional[str]:
    """A graveyard clause's ``(type_word, scope_word)`` → engine
    ``target_kind`` string (`game/targeting.py`'s `_GRAVEYARD_TARGET_KINDS`),
    or ``None`` if either half isn't one of the recognised shapes."""
    scope_key = _GRAVEYARD_SCOPE_KIND.get(re.sub(r"'", "", scope_word.strip().lower()))
    if scope_key is None:
        return None
    type_key = {
        "": "card", "instant or sorcery": "instant_or_sorcery",
        "nonland permanent": "nonland_permanent",
    }.get((type_word or "").strip().lower(), (type_word or "").strip().lower() or "card")
    return f"{scope_key}_{type_key}"


#: "return target [type] card from [scope] graveyard to the battlefield/
#: your hand/its owner's hand" / "put target [type] card from [scope]
#: graveyard onto the battlefield under its owner's control" (RULE 701.3,
#: the Regrowth/Reanimate/Deathrite-adjacent recursion family — see
#: `game/targeting.py`'s `_GRAVEYARD_TARGET_KINDS` for the scope × type
#: vocabulary this claims). Both verb shapes land the object under its own
#: *owner*'s control — the "steal it for yourself" shape is
#: `_reanimate_under_your_control` below, a genuinely different effect.
_RETURN_FROM_GRAVEYARD_RE = _c(
    rf"return target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard to "
    r"(?P<dest>the battlefield|your hand|its owner'?s hand)"
)
_PUT_FROM_GRAVEYARD_OWNER_CONTROL_RE = _c(
    rf"put target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard onto the battlefield under its owner'?s control"
)


def _return_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    dest = m.groupdict().get("dest")
    destination = "battlefield" if dest is None or dest == "the battlefield" else "hand"
    return [EffectSpec(
        "return_from_graveyard", {"target_kind": kind, "destination": destination},
    )]


#: "put target [type] card from [scope] graveyard onto the battlefield
#: under your control" (Reanimate/Rise from the Grave/Virtue of Persistence)
#: — unlike the two shapes above, this one *steals* the card for the
#: activating/casting player regardless of whose graveyard it came from.
_REANIMATE_UNDER_YOUR_CONTROL_RE = _c(
    rf"put target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard onto the battlefield under your control"
)


def _reanimate_under_your_control(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    return [EffectSpec(
        "return_from_graveyard",
        {"target_kind": kind, "destination": "battlefield", "under_your_control": True},
    )]


#: "exile target [type] card from [scope] graveyard" (RULE 701.5a) — the
#: Deathrite Shaman/Scavenging Ooze/Lion Sash graveyard-hate family; almost
#: always "a graveyard" in practice, but the same scope vocabulary applies.
_EXILE_FROM_GRAVEYARD_RE = _c(
    rf"exile target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard"
)


def _exile_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    return [EffectSpec("exile", {"target_kind": kind})]


#: "search your library for a card, put that card into your hand, then
#: shuffle." (RULE 701.19, an unrestricted tutor) / "search your library for
#: a basic land card, put it onto the battlefield tapped, then shuffle."
#: (a fetch land's activated-ability body — mirrors Evolving Wilds'
#: hand-authored `ability_catalogue.py` entry, just reached via the oracle-
#: text front-end instead). Both map onto the engine's existing `"search"`
#: `EffectSpec` (`game/effects.py`'s `SearchLibraryEffect`) — no new effect
#: type needed, just recognition.
_SEARCH_TO_HAND_RE = _c(
    r"search your library for a card,? put that card into your hand,? then shuffle"
)
_SEARCH_BASIC_LAND_TAPPED_RE = _c(
    r"search your library for a basic land card,? put it onto the battlefield tapped,? then shuffle"
)


def _search_to_hand(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("search", {"criteria": {}, "destination": "hand"})]


def _search_basic_land_tapped(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(
        "search", {"criteria": {"basic": True}, "destination": "battlefield_tapped"}
    )]


#: "attach it to target creature you control" / "attach ~ to target creature
#: you control" (an Equipment's own ETB self-attach, RULE 303.4f-adjacent —
#: `AttachEffect` already exists for Equip's activated ability, reused here).
def _attach(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("permanent", "creature", "creature_you_control"):
        return None
    return [EffectSpec("attach", {"target_kind": kind})]


#: A single mana symbol run — "add {b}{b}{b}." (Dark Ritual-shaped). Only a
#: *pure* run of colour/colourless symbols claims (fail-closed): "add 1 mana
#: of any color" has no ``{…}`` symbols to capture, so it's left unclaimed
#: rather than guessed at (that's a player choice, not modeled yet).
_MANA_SYMBOL = r"\{[wubrgc]\}"
_ADD_MANA_RE = _c(rf"add (?P<syms>(?:{_MANA_SYMBOL}){{1,20}})")
#: "add 1 mana of any color" (number words already folded to digits by
#: `normalize`) — a genuine resolve-time player choice (RULE 106.4), unlike
#: the fixed pip run above. Deliberately narrow: real cards only print this
#: singular form (a multi-mana "any color" clause is always templated "any
#: *one* color" instead, a different, not-yet-modeled shape — guessing it
#: means the same thing here would be wrong).
_ADD_MANA_ANY_COLOR_RE = _c(r"add 1 mana of any colou?r")


def _add_mana(m: re.Match[str]) -> list[EffectSpec]:
    colors = [s.upper() for s in re.findall(r"\{([wubrgc])\}", m.group("syms"))]
    return [EffectSpec("add_mana", {"colors": colors})]


def _add_mana_any_color(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_mana", {"colors": ["any"]})]


def _transform(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("transform", {})]


def _become_prepared(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("become_prepared", {})]


def _token_keywords(text: str) -> Optional[list[str]]:
    """Validate a token's "with <keywords>" clause → flag-keyword slugs, or None.

    Fail-closed: if any listed ability isn't a parameterless (flag) keyword, the
    whole token clause is left unclaimed rather than dropping the ability
    (a token that silently lacks "flying" would be a wrong game state).
    """
    slugs: list[str] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        kdef = KEYWORDS.get(keyword_slug(part))
        if kdef is None or kdef.shape is not KeywordShape.FLAG:
            return None
        slugs.append(kdef.slug)
    return slugs


def _create_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors: list[str] = []
    subtypes: list[str] = []
    for word in (m.group("mid") or "").split():
        if word in _COLOR_WORDS:
            colors.append(_COLOR_WORDS[word])
        elif word in _TOKEN_NOISE_WORDS:
            continue
        else:
            subtypes.append(word.capitalize())
    keywords: list[str] = []
    if m.groupdict().get("kw"):
        parsed = _token_keywords(m.group("kw"))
        if parsed is None:
            return None  # unrecognised "with …" ability → fail-closed
        keywords = parsed
    params: dict = {
        "count": count_of(m.group("n")),
        "power": int(m.group("p")),
        "toughness": int(m.group("t")),
        "colors": colors,
        "subtypes": subtypes,
        "keywords": keywords,
    }
    if subtypes:
        params["token_name"] = " ".join(subtypes)
    return [EffectSpec("create_token", params)]


def _signed_int(token: str) -> int:
    """A signed integer literal, tolerating the unicode minus ``−`` (U+2212)."""
    return int(token.replace("−", "-"))


def _add_counters(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "+1/+1" (default) or "-1/-1" — the sign of the captured counter kind picks
    # which; both shift net P/T through the same machinery (RULE 122).
    ckind = "-1/-1" if m.group("ckind").lstrip()[0] in "-−" else "+1/+1"
    params: dict = {"count": count_of(m.group("n")), "kind": ckind}
    if m.groupdict().get("selfref"):  # "on ~" — buffs the source, untargeted
        return [EffectSpec("add_counters", params)]
    kind = resolve_target_kind(m.group("target"))
    # +1/+1 counters can sit on *any* permanent (RULE 122.1a) — a land that
    # enters with counters and later becomes a creature uses them. So we honour
    # whatever the text targets (creature or permanent); only the target phrase
    # constrains it, not the counter itself.
    if kind not in ("creature", "permanent"):
        return None
    params["target_kind"] = kind
    return [EffectSpec("add_counters", params)]


def _pump_target(m: re.Match[str]) -> Optional[tuple[Optional[str], Optional[str]]]:
    """The pump's ``(target_kind, selector)`` — or ``None`` to signal fail-closed.

    Exactly one of the pair is set for a targeted or group subject; both are
    ``None`` for a self-pump ("~ gets …", untargeted single object) so the
    caller can tell it apart from an unrecognised target (real ``None``
    overall).
    """
    groupdict = m.groupdict()
    if groupdict.get("selfref"):
        return (None, None)  # untargeted self-pump (an activated "~ gets +1/+0 …")
    if groupdict.get("group"):
        return (None, _GROUP_SELECTORS[groupdict["group"]])
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "permanent"):
        return None
    return (kind, None)


def _pump(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    params: dict = {
        "power": _signed_int(m.group("p")),
        "toughness": _signed_int(m.group("t")),
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None  # unmodeled granted ability → fail-closed
        params["keywords"] = keywords
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    return [EffectSpec("pump", params)]


def _pump_keywords(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    params: dict = {"keywords": keywords}
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    return [EffectSpec("pump", params)]


def _scry(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("scry", {"count": int(m.group("n"))})]


# A pump's subject: a targeted creature/permanent, the self-reference ``~``
# (a creature's own activated "~ gets +1/+0 …"), or an untargeted *group*
# ("creatures you control get +2/+1 …" — RULE 601.2c, not a target at all;
# the common Saga-chapter/anthem-spell shape). Shared by the pump handlers.
_GROUP = r"(?P<group>other creatures you control|creatures you control)"
_SUBJECT = rf"(?:{TARGET}|(?P<selfref>{re.escape(SELF)})|{_GROUP})"
#: A matched ``group`` phrase → its `continuous.group_selector_objects` selector.
_GROUP_SELECTORS: dict[str, str] = {
    "creatures you control": "creatures_you_control",
    "other creatures you control": "other_creatures_you_control",
}
#: A signed P/T delta, "+3/+3" / "-2/-2" / "+0/-1" (ASCII or unicode minus).
_PT_DELTA = r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"


# --- The table --------------------------------------------------------------
# Order matters only for reporting; a clause is claimed by the first handler
# whose full-clause regex matches. Every pattern is anchored to the whole
# clause by `EffectHandler.match`'s `fullmatch`, so no partial claims.

HANDLERS: list[EffectHandler] = [
    # "~ deals 3 damage to any target" / "deal 2 damage to target creature" /
    # "it deals 2 damage to target opponent" (a triggered-ability body's own
    # "it"/"this creature"/"this land"/"this permanent" subject — cosmetic,
    # since the source is already bound at bind time regardless of wording).
    EffectHandler(
        "damage",
        _c(rf"(?:(?:~|it|this creature|this land|this permanent) )?deals? {NUMBER} damage to {TARGET}"),
        _damage,
    ),
    # "~ deals 2 damage to each creature" / "… to each player" / "… to each
    # opponent" — a mass effect (RULE 601.2c), not RULE 115 targeting.
    EffectHandler(
        "damage_selector",
        _c(
            rf"(?:(?:~|it|this creature|this land|this permanent) )?deals? {NUMBER} damage to "
            rf"(?P<selector>each creature|each player|each opponent)"
        ),
        _damage_selector,
    ),
    # "draw a card" / "draw 3 cards" / "you draw two cards"
    EffectHandler(
        "draw",
        _c(rf"(?:you )?draws? {COUNT} cards?"),
        _draw,
    ),
    # "you discard a card" / "discard 2 cards" / "target player discards a card"
    EffectHandler(
        "discard",
        _c(rf"(?:you |target player |each player )?discards? {COUNT} cards?"),
        _discard,
    ),
    # "you gain 3 life" / "gain 5 life"
    EffectHandler(
        "gain_life",
        _c(rf"(?:you )?gains? {NUMBER} life"),
        _gain_life,
    ),
    # "you lose 2 life" / "target player loses 2 life"
    EffectHandler(
        "lose_life",
        _c(rf"(?:you |target player )?loses? {NUMBER} life"),
        _lose_life,
    ),
    # "each opponent loses 2 life" / "each player loses 2 life" (RULE
    # 601.2c mass effect, Deathrite Shaman-shaped).
    EffectHandler(
        "lose_life_selector",
        _c(rf"(?P<selector>each player|each opponent) loses? {NUMBER} life"),
        _lose_life_selector,
    ),
    # "destroy target creature" / "destroy target artifact"
    EffectHandler(
        "destroy",
        _c(rf"destroy {TARGET}"),
        _destroy,
    ),
    # "counter target spell" / "counter target noncreature spell" / "counter
    # target instant or sorcery spell" / "counter target spell with mana
    # value N" / any of those "… unless its controller pays {N}" (RULE 601.2c
    # target filter + the "Mana Leak" unless-pay template).
    EffectHandler(
        "counter",
        _c(rf"counter {SPELL_TARGET}" + r"(?: unless its controller pays (?P<cost>\{[^}]+\}))?"),
        _counter,
    ),
    # "this spell can't be countered." / "~ can't be countered." (RULE
    # 118-area) — a spell's own property, docked as a marker the counter
    # effect refuses to act on (`RulesEngine._is_cant_be_countered`).
    EffectHandler(
        "cant_be_countered",
        CANT_BE_COUNTERED_RE,
        _cant_be_countered,
    ),
    # "mill 3 cards" / "you mill 3 cards" / "target player mills 3 cards"
    EffectHandler(
        "mill",
        _c(rf"(?:(?P<who>you|target player|target opponent) )?mills? {NUMBER} cards?"),
        _mill,
    ),
    # "exile target creature" / "exile target artifact"
    EffectHandler(
        "exile",
        _c(rf"exile {TARGET}"),
        _exile,
    ),
    # "tap target creature" / "untap target permanent"
    EffectHandler(
        "tap",
        _c(rf"(?P<verb>tap|untap) {TARGET}"),
        _tap,
    ),
    # "untap this creature" / "untap ~" / "tap it" — the self form (Devoted
    # Druid's "Put a -1/-1 counter on this creature: Untap this creature.").
    EffectHandler(
        "tap_self",
        _c(rf"(?P<verb>tap|untap) {_SELF_SUBJECT}"),
        _tap_self,
    ),
    # "return target creature to its owner's hand" / "return a land you
    # control to its owner's hand" (RULE 701.3 — the bounce family).
    EffectHandler(
        "return_to_hand",
        _c(rf"return {TARGET} to its owner's hand"),
        _return_to_hand,
    ),
    # "return target [type] card from [scope] graveyard to the
    # battlefield/your hand/its owner's hand" / "put target [type] card
    # from [scope] graveyard onto the battlefield under its owner's
    # control" (RULE 701.3, the Regrowth/Reanimate/Deathrite-adjacent
    # recursion family — own/any/opponent graveyard scope).
    EffectHandler(
        "return_from_graveyard",
        _RETURN_FROM_GRAVEYARD_RE,
        _return_from_graveyard,
    ),
    EffectHandler(
        "return_from_graveyard_owner_control",
        _PUT_FROM_GRAVEYARD_OWNER_CONTROL_RE,
        _return_from_graveyard,
    ),
    # "put target [type] card from [scope] graveyard onto the battlefield
    # under your control" (Reanimate/Rise from the Grave/Virtue of
    # Persistence) — a genuinely different effect from the two above: the
    # activating player takes control, not the card's owner.
    EffectHandler(
        "reanimate_under_your_control",
        _REANIMATE_UNDER_YOUR_CONTROL_RE,
        _reanimate_under_your_control,
    ),
    # "exile target [type] card from [scope] graveyard" (RULE 701.5a,
    # Deathrite Shaman/Scavenging Ooze/Lion Sash-shaped graveyard hate).
    EffectHandler(
        "exile_from_graveyard",
        _EXILE_FROM_GRAVEYARD_RE,
        _exile_from_graveyard,
    ),
    # "search your library for a card, put that card into your hand, then
    # shuffle." (RULE 701.19, an unrestricted tutor).
    EffectHandler(
        "search_to_hand",
        _SEARCH_TO_HAND_RE,
        _search_to_hand,
    ),
    # "search your library for a basic land card, put it onto the
    # battlefield tapped, then shuffle." (a fetch land's activated body).
    EffectHandler(
        "search_basic_land_tapped",
        _SEARCH_BASIC_LAND_TAPPED_RE,
        _search_basic_land_tapped,
    ),
    # "attach it to target creature you control" / "attach ~ to target
    # creature you control" (an Equipment's own ETB self-attach).
    EffectHandler(
        "attach",
        _c(rf"attach (?:it|{re.escape(SELF)}) to {TARGET}"),
        _attach,
    ),
    # "add 1 mana of any color" — a genuine resolve-time colour choice,
    # tried before the fixed-pip pattern below since it has no {…} symbols
    # for that one to (fail to) match anyway.
    EffectHandler(
        "add_mana_any_color",
        _ADD_MANA_ANY_COLOR_RE,
        _add_mana_any_color,
    ),
    # "add {b}{b}{b}." (Dark Ritual-shaped bare mana-symbol spell body).
    EffectHandler(
        "add_mana",
        _ADD_MANA_RE,
        _add_mana,
    ),
    # "transform ~" / "transform it" / "transform this permanent"/"creature"
    # (RULE 712.8) — the self-transform shape a loyalty "[0]: Transform ~."
    # or a "whenever ~ attacks, transform it" trigger uses.
    EffectHandler(
        "transform",
        _c(rf"transform (?:{re.escape(SELF)}|it|this permanent|this creature)"),
        _transform,
    ),
    # "~ becomes prepared" / "it becomes prepared" / "this permanent"/
    # "this creature becomes prepared" (RULE 722.3a) — a preparation card's
    # own "whenever X, ~ becomes prepared" trigger; the self-only shape
    # mirrors "transform" above (RULE 722.3a has no targeted form).
    EffectHandler(
        "become_prepared",
        _c(rf"(?:{re.escape(SELF)}|it|this permanent|this creature) becomes prepared"),
        _become_prepared,
    ),
    # "put a +1/+1 counter on target creature" / "put a -1/-1 counter on …" / "… on ~"
    EffectHandler(
        "add_counters",
        _c(
            rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
            rf"(?:{TARGET}|(?P<selfref>{re.escape(SELF)}))"
        ),
        _add_counters,
    ),
    # "target creature gets +3/+3 until end of turn" / "gets -2/-2 …" /
    # "gets +1/+1 and gains trample until end of turn" / "~ gets +1/+0 …" /
    # "creatures you control get +2/+1 until end of turn" (plural "get").
    EffectHandler(
        "pump",
        _c(
            rf"{_SUBJECT} gets? {_PT_DELTA}"
            rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _pump,
    ),
    # "target creature gains flying until end of turn" (keyword-only pump) /
    # "creatures you control gain flying until end of turn".
    EffectHandler(
        "pump_keyword",
        _c(rf"{_SUBJECT} gains? (?P<kw>[a-z, ]+?) until end of turn"),
        _pump_keywords,
    ),
    # "scry 2" (a self effect — the controller scries; RULE 701.18).
    EffectHandler(
        "scry",
        _c(rf"scry {NUMBER}"),
        _scry,
    ),
    # "create a 1/1 white Soldier creature token" / "create two 2/2 green Bear
    # creature tokens with trample" — inline creature tokens (fully modeled).
    EffectHandler(
        "create_token",
        _c(
            rf"(?:you )?creates? {COUNT} (?P<p>\d+)/(?P<t>\d+) "
            rf"(?P<mid>[a-z ]*?)creature tokens?"
            rf"(?: with (?P<kw>[a-z, ]+))?"
        ),
        _create_token,
    ),
]


def match_clause(clause: str) -> Optional[list[EffectSpec]]:
    """The `EffectSpec`s for one normalised effect ``clause``, or ``None``.

    Runs the handler table; the first handler to claim the whole clause wins.
    ``None`` means no handler modeled it — the clause is unclaimed and its card
    will fail the coverage gate (docs/09 fail-closed).
    """
    for handler in HANDLERS:
        effects = handler.match(clause)
        if effects is not None:
            return effects
    return None
