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
    COLOR_WORD_ALT,
    COUNT,
    IF_COLOR_SUFFIX,
    NUMBER,
    SPELL_TARGET,
    TARGET,
    UP_TO_ONE,
    count_of,
    resolve_color_word,
    resolve_spell_filter,
    resolve_target_kind,
    target_is_optional,
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


#: RULE 115.1a "up to one" (`subgrammars.target_is_optional`) → the
#: `{"optional": True}` param sliver every `{TARGET}`-based builder below
#: merges in, or ``{}`` for a bare "target X" (still required, unchanged).
def _optional_param(m: re.Match[str]) -> dict:
    return {"optional": True} if target_is_optional(m) else {}


#: RULE 115.1a generalized to N>=2 — "destroy **two** target creatures",
#: "destroy **up to two** target artifacts and/or enchantments", "deals N
#: damage to each of **up to two** target creatures and/or planeswalkers".
#: A deliberately separate, self-contained grammar from the shared `TARGET`
#: macro above (`_TARGET_ROWS` is singular-only and reused by many other
#: handler families — return_to_hand/tap/attach/… — that this feature
#: doesn't touch): a plural noun phrase never collides with `TARGET`'s bare
#: "target X"/"up to one target X" shapes, so there's no dispatch ambiguity
#: registering both. Only wired up for `destroy`/`exile`/`damage` — the
#: three effect classes `game/effects.py` actually loops a `count` over
#: (`DestroyEffect`/`ExileEffect`/`DealDamageEffect`); every other targeting
#: effect stays N=1-only until a real card drives extending it too.
_MULTI_TARGET_ROWS: list[tuple[str, str]] = [
    (r"target creatures and/or planeswalkers", "any"),
    (r"target artifacts and/or enchantments", "permanent"),
    (r"target creatures", "creature"),
    (r"target permanents", "permanent"),
    (r"target artifacts", "permanent"),
    (r"target enchantments", "permanent"),
    (r"target lands", "permanent"),
    (r"target players", "player"),
]
_MULTI_TARGET_ALT = "|".join(f"(?:{frag})" for frag, _ in _MULTI_TARGET_ROWS)


def _multi_target_kind(phrase: str) -> Optional[str]:
    text = phrase.strip()
    for frag, kind in _MULTI_TARGET_ROWS:
        if re.fullmatch(frag, text, re.IGNORECASE):
            return kind
    return None


#: A numeric quantifier before a plural TARGET phrase: "two "/"three " (a
#: mandatory count — RULE 601.2c needs that many legal targets to even be
#: castable) or "up to two "/"up to three " (optional, 0..N — never locks
#: casting, same as "up to one"). Digits only — `normalize.py` already
#: folds spelled-out numbers up to twelve.
_MULTI_TARGET_QUANTIFIER = r"(?P<up_to>up to )?(?P<count>\d+) "


def _multi_target_params(m: re.Match[str]) -> Optional[dict]:
    """The shared ``{target_kind, count, optional?}`` params for a
    `_MULTI_TARGET_QUANTIFIER` + `_MULTI_TARGET_ALT` match, or ``None`` if
    the target phrase isn't recognized or the count is < 2 (the N=1 "up to
    one"/bare-target case is the existing singular handler's job, not this
    one's — a count of exactly 1 here would just be a confusing duplicate
    route to the same effect)."""
    kind = _multi_target_kind(m.group("target"))
    if kind is None:
        return None
    count = int(m.group("count"))
    if count < 2:
        return None
    params: dict = {"target_kind": kind, "count": count}
    if m.groupdict().get("up_to"):
        params["optional"] = True
    return params


def _damage(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("damage", {"amount": int(m.group("n")), "target_kind": kind, **_optional_param(m)})]


def _damage_each_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None:
        return None
    return [EffectSpec("damage", {"amount": int(m.group("amount")), **params})]


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
    color = resolve_color_word(m.groupdict().get("cond_color"))
    params: dict = {"target_kind": kind, **_optional_param(m)}
    if color:
        params["color"] = color
    return [EffectSpec("destroy", params)]


def _destroy_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "destroy target nonland permanent with mana value 3 or less"
    # (Abrupt Decay-shaped) — a target-offer-time mana-value cap
    # (`targeting.TargetSpec.max_mana_value`), tried before the plain
    # `_destroy` handler since it's a strict superset of that shape (the
    # trailing "with mana value N or less" clause `_destroy`'s own grammar
    # doesn't recognise).
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent"):
        return None
    return [EffectSpec("destroy", {"target_kind": kind, "max_mana_value": int(m.group("mv"))})]


#: "destroy target [color] creature/permanent/artifact/enchantment/land"
#: (RULE 105's colour-hoser adjective form, Red Elemental Blast-shaped) — a
#: small dedicated noun list rather than a color slot spliced into the
#: shared `TARGET` macro's fixed rows (which many other handlers reuse
#: as-is); covers the same nouns `_destroy`'s plain `TARGET`-based match
#: already accepts. Tried before the plain `destroy` handler below — with
#: no colour word present it matches identically (same `target_kind`
#: mapping), so it never changes behaviour for an uncoloured clause.
_DESTROY_COLOR_NOUN_KINDS: dict[str, str] = {
    "creature": "creature", "permanent": "permanent", "artifact": "permanent",
    "enchantment": "permanent", "land": "permanent",
}
_DESTROY_COLOR_ADJ_RE = _c(
    rf"destroy target (?:(?P<color>{COLOR_WORD_ALT}) )?"
    rf"(?P<noun>{'|'.join(_DESTROY_COLOR_NOUN_KINDS)})"
    + IF_COLOR_SUFFIX
)


def _destroy_color_adj(m: re.Match[str]) -> list[EffectSpec]:
    color = resolve_color_word(m.groupdict().get("color")) or resolve_color_word(m.groupdict().get("cond_color"))
    params: dict = {"target_kind": _DESTROY_COLOR_NOUN_KINDS[m.group("noun")]}
    if color:
        params["color"] = color
    return [EffectSpec("destroy", params)]


def _destroy_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None:
        return None
    return [EffectSpec("destroy", params)]


def _regenerate(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent"):
        return None
    return [EffectSpec("regenerate", {"target_kind": kind})]


def _regenerate_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("regenerate", {"target_kind": None})]


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
    cond_color = resolve_color_word(m.groupdict().get("cond_color"))
    if cond_color:
        params["color"] = cond_color
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
    return [EffectSpec("exile", {"target_kind": kind, **_optional_param(m)})]


def _exile_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None:
        return None
    return [EffectSpec("exile", params)]


def _tap(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent", "legendary_permanent", "forest"):
        return None
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": kind, "untap": untap, **_optional_param(m)})]


def _tap_selector(m: re.Match[str]) -> list[EffectSpec]:
    # "untap all creatures you control" (Village Bell-Ringer's ETB) — an
    # untargeted mass effect, `game/effects.py`'s `TapEffect.selector`, the
    # same shape `_add_counters_selector` uses for a mass counter effect.
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"selector": "creatures_you_control", "untap": untap})]


#: "Untap this creature" (Devoted Druid's counter-cost untap ability) / "tap
#: ~" — the *self* form, no RULE 115 target at all (`target_kind=None` makes
#: `TapEffect` act on its own source, mirroring `AttachEffect`'s ``~``/"it"
#: self-reference).
_SELF_SUBJECT = (
    r"(?:~|it|this permanent|this creature|this artifact|this land|this enchantment)"
)


def _tap_self(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": None, "untap": untap})]


#: "enchanted creature"/"equipped creature"/"fortified land" — an Aura/
#: Equipment/Fortify's own activated-ability body implicitly acting on
#: whatever it's attached to (RULE 303.4/301.5), no player choice at all
#: (`TapEffect`/`PumpEffect`'s ``"attached_permanent"`` mode) — the
#: activated-ability sibling of `effect_binder._subject_condition`'s
#: ``"attached_permanent"`` *trigger*-subject concept.
_ATTACHED_SUBJECT = r"(?:enchanted creature|equipped creature|fortified land)"


#: "{U}: Tap enchanted creature."/"{U}: Untap enchanted creature." (Freed
#: from the Real/Pemmin's Aura-shaped Aura activated abilities).
def _tap_attached(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": "attached_permanent", "untap": untap})]


#: "Sacrifice ~."/"Sacrifice this enchantment." (Dress Down/Underworld
#: Breach-shaped standing end-step self-sac) — the self form, no player
#: choice or RULE 115 target (RULE 701.17).
def _sacrifice_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("sacrifice_self", {})]


#: "Exile ~."/"Exile this card." (Teferi's Protection/Mnemonic Betrayal's
#: trailing self-exile) — the self form, `ExileEffect`'s `target_kind=None`.
def _exile_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile", {"target_kind": None})]


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
    return [EffectSpec("return_to_hand", {"target_kind": kind, **_optional_param(m)})]


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
    rf"return (?P<up_to_one>{UP_TO_ONE})target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard to "
    r"(?P<dest>the battlefield|your hand|its owner'?s hand)"
)
_PUT_FROM_GRAVEYARD_OWNER_CONTROL_RE = _c(
    rf"put (?P<up_to_one>{UP_TO_ONE})target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard onto the battlefield under its owner'?s control"
)


def _return_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    dest = m.groupdict().get("dest")
    destination = "battlefield" if dest is None or dest == "the battlefield" else "hand"
    params: dict = {"target_kind": kind, "destination": destination}
    if m.groupdict().get("up_to_one"):
        params["optional"] = True
    return [EffectSpec("return_from_graveyard", params)]


#: "put target [type] card from [scope] graveyard onto the battlefield
#: under your control" (Reanimate/Rise from the Grave/Virtue of Persistence)
#: — unlike the two shapes above, this one *steals* the card for the
#: activating/casting player regardless of whose graveyard it came from.
_REANIMATE_UNDER_YOUR_CONTROL_RE = _c(
    rf"put (?P<up_to_one>{UP_TO_ONE})target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard onto the battlefield under your control"
)


def _reanimate_under_your_control(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind, "destination": "battlefield", "under_your_control": True}
    if m.groupdict().get("up_to_one"):
        params["optional"] = True
    return [EffectSpec("return_from_graveyard", params)]


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


#: "search your library for a [<criteria>] card, [reveal it,] put it/that
#: card/them/those cards <destination>, then shuffle." (RULE 701.19, the
#: general tutor/ramp/fetch family — Demonic Tutor/Rampant Growth/Farseek/
#: Nature's Lore/Crop Rotation/Eladamri's Call/Buried Alive/Sylvan
#: Scrying-shaped) and its reordered sibling "..., [reveal it,] then shuffle
#: and put it/that card/the card on top." (Vampiric/Mystical/Enlightened/
#: Worldly Tutor-shaped). Both map onto the engine's existing `"search"`
#: `EffectSpec` (`game/effects.py`'s `SearchLibraryEffect`, already
#: parameterized on criteria/destination/count — `tests/
#: test_search_popular_tutors.py` proves it against 15 real popular tutors)
#: — no new effect type needed, just recognition. Deliberately NOT attempted
#: here (fail-closed, real cards found but left unclaimed): "library and/or
#: graveyard" combined search (Doomsday/Finale of Devastation — `request_
#: search` only reads `player.library`), a split destination per found card
#: (Cultivate/Kodama's Reach — a single search always has one destination),
#: "search for N cards and exile the rest" (Doomsday), and any qualifier
#: after the noun phrase such as "with mana value X or less" (Green Sun's
#: Zenith/Chord of Calling — X is a spell's own cast-time choice, not a
#: static criterion this grammar can express).
#:
#: The type-word vocabulary intentionally also carries the five basic land
#: names (a card can be searched for by name, "a Forest card"/"a Plains,
#: Island, Swamp, or Mountain card" — Nature's Lore/Farseek), separate from
#: "basic land" (Rampant Growth) which sets `criteria["basic"]` instead of a
#: `type` filter — the two are mutually exclusive alternatives tried in that
#: order (longest/most-specific first), never combined.
_SEARCH_TYPE_WORD = (
    r"artifact|creature|enchantment|instant|planeswalker|sorcery|land|"
    r"plains|island|swamp|mountain|forest"
)
#: An "or"/comma-separated list of 1+ type words, same shape as
#: `subgrammars._SPELL_TYPE_LIST` (kept separate/local since this vocabulary
#: — land + basic land names — is specific to a library search, not a spell
#: target filter).
_SEARCH_TYPE_LIST = (
    rf"(?:{_SEARCH_TYPE_WORD})(?:,\s*(?:{_SEARCH_TYPE_WORD}))*"
    rf"(?:,?\s+or\s+(?:{_SEARCH_TYPE_WORD}))?"
)
#: The noun phrase after "search your library for": a determiner ("a"/"an"/
#: "up to N"), then either "basic land" (sets `basic`) or a `_SEARCH_TYPE_
#: LIST` (sets `types`) or neither (a bare "a card"), then "card(s)".
_SEARCH_CRITERIA = (
    r"(?:up to (?P<count>\d+)|an?)\s+"
    rf"(?:(?P<basic>basic land)|(?P<types>{_SEARCH_TYPE_LIST}))?\s*"
    r"cards?"
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

#: "search your library for <criteria>, [reveal <pronoun>,] put <pronoun>
#: <destination>, then shuffle." — the common put-then-shuffle order.
_SEARCH_PUT_THEN_SHUFFLE_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)
#: "search your library for <criteria>, [reveal <pronoun>,] then shuffle and
#: put <pronoun> on top [of your library]." — the reordered shuffle-then-put
#: order, always to the top of the library (Vampiric/Mystical/Enlightened/
#: Worldly Tutor).
_SEARCH_SHUFFLE_THEN_PUT_TOP_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"then shuffle and put {_SEARCH_PRONOUN} on top(?: of your library)?"
)


def _search_criteria_from_match(m: re.Match[str]) -> dict:
    if m.groupdict().get("basic"):
        return {"basic": True}
    types = m.groupdict().get("types")
    if types:
        words = [t.strip() for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", types) if t.strip()]
        return {"type": words if len(words) > 1 else words[0]}
    return {}


def _search_count_from_match(m: re.Match[str]) -> Optional[int]:
    count = m.groupdict().get("count")
    return int(count) if count is not None else None


def _search_put_then_shuffle(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    params: dict = {"criteria": _search_criteria_from_match(m), "destination": destination}
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


def _search_shuffle_then_put_top(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {"criteria": _search_criteria_from_match(m), "destination": "library_top"}
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


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


#: "if your library has no cards in it, you win the game" (Jace, Wielder of
#: Mysteries' "-8: Draw seven cards. Then if your library has no cards in
#: it, you win the game." tail, RULE 104.2) — a plain conditional one-shot,
#: not the standing replacement `catalogue.replacements`' sibling clause
#: covers (that one gates a *draw*, this one gates an already-resolved
#: loyalty ability's own follow-up sentence).
def _win_if_empty_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("win_game", {"if_empty_library": True})]


#: RULE 602.1-adjacent per-instance activation cap: "Activate only once each
#: turn." (Quirion Ranger/Scryb Ranger-shaped) — a plain trailing sentence in
#: an activated ability's own body (after the cost's colon), sitting
#: alongside its real effect ("Untap target creature. Activate only once
#: each turn." — two sentences `parse_effect_body`'s connector-splitting
#: already tries independently). Not a real one-shot effect: this handler
#: claims the clause but emits a *marker* `EffectSpec` `effect_binder.
#: bind_ability`'s "activated" branch recognizes and strips before binding,
#: turning it into `ActivatedAbility.once_per_turn` instead of a `GameEffect`
#: (mirroring `TriggeredAbility.once_per_turn`'s own RULE 603.2 stamp).
ONCE_PER_TURN_MARKER = "once_per_turn_marker"
_ONCE_PER_TURN_RE = _c(r"activate (?:this ability )?only once each turn")


def _once_per_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(ONCE_PER_TURN_MARKER, {})]


#: RULE 602.5d timing restriction: "Activate only as a sorcery." (older
#: template) / "Activate this ability only any time you could cast a sorcery."
#: (current) — like `ONCE_PER_TURN_MARKER`, a trailing sentence in the
#: activated ability's own body, not a real one-shot effect. Claimed as a
#: marker `EffectSpec` that `effect_binder.bind_ability`'s "activated" branch
#: strips and folds into `ActivationCost.sorcery_speed_only` (already enforced
#: by `game_engine.can_activate` via `_sorcery_speed_ok`), the same lever the
#: engine already uses for level-up / Class-level sorcery-speed abilities.
#: Only the two canonical *sorcery-speed* phrasings (RULE 605.3b / "any time
#: you could cast a sorcery"). Deliberately not "only during your turn" /
#: "before attackers are declared" — those are subtly different timing
#: windows (a non-empty stack / instant-speed-within-your-turn is still
#: allowed), so folding them to sorcery-speed would be *wrong*; left unclaimed
#: (fail-closed) until modeled precisely.
SORCERY_SPEED_MARKER = "sorcery_speed_marker"
_SORCERY_SPEED_RE = _c(
    r"activate (?:this ability )?only "
    r"(?:as a sorcery|any time you could cast a sorcery)"
)


def _sorcery_speed(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(SORCERY_SPEED_MARKER, {})]


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
    # whatever the text targets (creature or permanent, incl. the
    # controller-restricted "target creature you control" pick, Archdruid's
    # Charm-shaped); only the target phrase constrains it, not the counter itself.
    if kind not in ("creature", "permanent", "creature_you_control"):
        return None
    params["target_kind"] = kind
    params.update(_optional_param(m))
    return [EffectSpec("add_counters", params)]


#: "put N +1/+1 counters on each creature you control" (RULE 601.2c mass
#: effect, Vastwood Surge-shaped) — a genuinely different shape from
#: `_add_counters`'s RULE 115 target/self forms, so its own handler row
#: rather than folding "each creature you control" into `TARGET` (that
#: grammar deliberately keeps "each ..." selectors out, see
#: `subgrammars._TARGET_ROWS`'s note).
def _add_counters_selector(m: re.Match[str]) -> list[EffectSpec]:
    ckind = "-1/-1" if m.group("ckind").lstrip()[0] in "-−" else "+1/+1"
    return [EffectSpec("add_counters", {
        "count": count_of(m.group("n")), "kind": ckind, "selector": "each_creature_you_control",
    })]


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
    if groupdict.get("attached"):
        return ("attached_permanent", None)  # "enchanted creature gains …" (Aura activated ability)
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


def _surveil(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("surveil", {"count": int(m.group("n"))})]


# A pump's subject: a targeted creature/permanent, the self-reference ``~``
# (a creature's own activated "~ gets +1/+0 …"), or an untargeted *group*
# ("creatures you control get +2/+1 …" — RULE 601.2c, not a target at all;
# the common Saga-chapter/anthem-spell shape). Shared by the pump handlers.
_GROUP = r"(?P<group>other creatures you control|creatures you control)"
_SUBJECT = (
    rf"(?:{TARGET}|(?P<selfref>{re.escape(SELF)})|{_GROUP}|(?P<attached>{_ATTACHED_SUBJECT}))"
)
#: A matched ``group`` phrase → its `continuous.group_selector_objects` selector.
_GROUP_SELECTORS: dict[str, str] = {
    "creatures you control": "creatures_you_control",
    "other creatures you control": "other_creatures_you_control",
}
#: A signed P/T delta, "+3/+3" / "-2/-2" / "+0/-1" (ASCII or unicode minus).
_PT_DELTA = r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"

#: "target creature gets +1/+0 until end of turn and can't be blocked this
#: turn" (You Come to a River-shaped) — the P/T-then-unblockable ordering
#: (unlike `_pump`'s "and gains <kw> until end of turn", the keyword clause
#: sits *before* "until end of turn"; here "can't be blocked this turn"
#: trails it instead) — a targeted-only shape (real cards always name a
#: single "target creature", never a self/group subject for this combo), so
#: it uses `TARGET` directly rather than the broader `_SUBJECT`.
_PUMP_UNBLOCKABLE_RE = _c(
    rf"{TARGET} gets? {_PT_DELTA} until end of turn and can'?t be blocked this turn"
)


def _pump_unblockable(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "permanent"):
        return None
    return [EffectSpec("pump", {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "target_kind": kind, "unblockable": True,
    })]


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
    # "~ deals 6 damage to each of up to two target creatures and/or
    # planeswalkers" (RULE 115.1a generalized to N>=2) — the full amount
    # applies to *every* chosen target, not divided among them.
    EffectHandler(
        "damage_each_multi_target",
        _c(
            rf"(?:(?:~|it|this creature|this land|this permanent) )?"
            rf"deals? (?P<amount>\d+) damage to each of {_MULTI_TARGET_QUANTIFIER}"
            rf"(?P<target>{_MULTI_TARGET_ALT})"
        ),
        _damage_each_multi_target,
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
    # "destroy target [color] creature/permanent/artifact/enchantment/land"
    # (RULE 105 colour-hoser adjective, Red Elemental Blast-shaped) — tried
    # before the plain `destroy` handler below (see `_DESTROY_COLOR_ADJ_RE`'s
    # docstring for why it's safe to try first).
    EffectHandler(
        "destroy_color_adj",
        _DESTROY_COLOR_ADJ_RE,
        _destroy_color_adj,
    ),
    # "destroy target nonland permanent with mana value 3 or less"
    # (Abrupt Decay-shaped) — tried before the plain `destroy` handler
    # below (see `_destroy_mv`'s docstring for why it's safe to try first).
    EffectHandler(
        "destroy_mv",
        _c(rf"destroy {TARGET} with mana value (?P<mv>\d+) or less"),
        _destroy_mv,
    ),
    # "destroy target creature" / "destroy target artifact" / "destroy
    # target permanent if it's blue" (the trailing-clause old-templating
    # colour variant, Pyroblast-shaped — see `IF_COLOR_SUFFIX`).
    EffectHandler(
        "destroy",
        _c(rf"destroy {TARGET}" + IF_COLOR_SUFFIX),
        _destroy,
    ),
    # "destroy two target creatures" / "destroy up to two target artifacts
    # and/or enchantments" (RULE 115.1a generalized to N>=2 — Curtains'
    # Call/Force of Vigor-shaped).
    EffectHandler(
        "destroy_multi_target",
        _c(rf"destroy {_MULTI_TARGET_QUANTIFIER}(?P<target>{_MULTI_TARGET_ALT})"),
        _destroy_multi_target,
    ),
    # "regenerate target creature" (RULE 701.16, Ezuri, Renegade Leader's
    # "Regenerate another target Elf" is a genuinely different, subtype-
    # filtered target this grammar doesn't cover — fails closed, stays
    # unclaimed rather than dropping the subtype filter).
    EffectHandler(
        "regenerate",
        _c(rf"regenerate {TARGET}"),
        _regenerate,
    ),
    # "regenerate ~" / "regenerate it" / "regenerate this creature" — the
    # *self* form (Broodhatch Nantuko/Thorn Elemental-shaped "{cost}:
    # Regenerate ~."), mirroring `tap_self`'s no-RULE-115-target shape.
    EffectHandler(
        "regenerate_self",
        _c(rf"regenerate {_SELF_SUBJECT}"),
        _regenerate_self,
    ),
    # "counter target spell" / "counter target noncreature spell" / "counter
    # target instant or sorcery spell" / "counter target spell with mana
    # value N" / "counter target blue spell" (RULE 105 colour-hoser
    # adjective, inline via `SPELL_TARGET`'s own ``color`` group) / any of
    # those "… unless its controller pays {N}" (the "Mana Leak" unless-pay
    # template) and/or "… if it's blue" (the trailing-clause old-templating
    # colour variant, Red Elemental Blast/Pyroblast-shaped).
    EffectHandler(
        "counter",
        _c(
            rf"counter {SPELL_TARGET}"
            + r"(?: unless its controller pays (?P<cost>\{[^}]+\}))?"
            + IF_COLOR_SUFFIX
        ),
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
    # "exile two target creatures" / "exile up to two target artifacts"
    # (RULE 115.1a generalized to N>=2).
    EffectHandler(
        "exile_multi_target",
        _c(rf"exile {_MULTI_TARGET_QUANTIFIER}(?P<target>{_MULTI_TARGET_ALT})"),
        _exile_multi_target,
    ),
    # "exile ~" / "exile this card" — the self form (Teferi's Protection/
    # Mnemonic Betrayal's trailing self-exile).
    EffectHandler(
        "exile_self",
        _c(rf"exile {_SELF_SUBJECT}"),
        _exile_self,
    ),
    # "sacrifice ~" / "sacrifice this enchantment" — the self form (Dress
    # Down/Underworld Breach's standing end-step self-sac).
    EffectHandler(
        "sacrifice_self",
        _c(rf"sacrifice {_SELF_SUBJECT}"),
        _sacrifice_self,
    ),
    # "tap target creature" / "untap target permanent"
    EffectHandler(
        "tap",
        _c(rf"(?P<verb>tap|untap) {TARGET}"),
        _tap,
    ),
    # "untap all creatures you control" (Village Bell-Ringer) — must sit
    # above `tap_self`/the bare `_SELF_SUBJECT` row so "all creatures you
    # control" (not a self-reference) is recognised on its own.
    EffectHandler(
        "tap_selector",
        _c(r"(?P<verb>tap|untap) all creatures you control"),
        _tap_selector,
    ),
    # "untap this creature" / "untap ~" / "tap it" — the self form (Devoted
    # Druid's "Put a -1/-1 counter on this creature: Untap this creature.").
    EffectHandler(
        "tap_self",
        _c(rf"(?P<verb>tap|untap) {_SELF_SUBJECT}"),
        _tap_self,
    ),
    # "tap enchanted creature" / "untap enchanted creature" (Freed from the
    # Real/Pemmin's Aura-shaped Aura activated abilities).
    EffectHandler(
        "tap_attached",
        _c(rf"(?P<verb>tap|untap) {_ATTACHED_SUBJECT}"),
        _tap_attached,
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
    # "search your library for <criteria>, [reveal <pronoun>,] put <pronoun>
    # <destination>, then shuffle." (RULE 701.19 — the general tutor/ramp/
    # fetch family: unrestricted tutors, basic-land fetches, criteria-
    # filtered tutors, "reveal" variants).
    EffectHandler(
        "search_put_then_shuffle",
        _SEARCH_PUT_THEN_SHUFFLE_RE,
        _search_put_then_shuffle,
    ),
    # "search your library for <criteria>, [reveal <pronoun>,] then shuffle
    # and put <pronoun> on top." (the reordered shuffle-then-put-on-top
    # tutors — Vampiric/Mystical/Enlightened/Worldly Tutor).
    EffectHandler(
        "search_shuffle_then_put_top",
        _SEARCH_SHUFFLE_THEN_PUT_TOP_RE,
        _search_shuffle_then_put_top,
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
    # "Activate only once each turn." (Quirion Ranger/Scryb Ranger-shaped) —
    # a per-instance activation cap, not a real effect; see
    # `ONCE_PER_TURN_MARKER`'s docstring for how the binder strips it.
    EffectHandler(
        "once_per_turn",
        _ONCE_PER_TURN_RE,
        _once_per_turn,
    ),
    # "Activate only as a sorcery." / "… only any time you could cast a
    # sorcery." — a RULE 602.5d timing restriction, not a real effect; see
    # `SORCERY_SPEED_MARKER`'s docstring for how the binder folds it into the
    # cost's `sorcery_speed_only` flag.
    EffectHandler(
        "sorcery_speed",
        _SORCERY_SPEED_RE,
        _sorcery_speed,
    ),
    # "if your library has no cards in it, you win the game" (Jace, Wielder
    # of Mysteries' -8 tail).
    EffectHandler(
        "win_if_empty_library",
        _c(r"(?:then )?if your library has no cards? in it, you win the game"),
        _win_if_empty_library,
    ),
    # "put a +1/+1 counter on target creature" / "put a -1/-1 counter on …" /
    # "… on ~"/"this creature" (Walking Ballista's "{4}: Put a +1/+1 counter
    # on this creature." — `_SELF_SUBJECT`, the same self-reference
    # vocabulary `_tap_self` already uses, not just the literal ``~`` a
    # card's own name folds to).
    EffectHandler(
        "add_counters",
        _c(
            rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
            rf"(?:{TARGET}|(?P<selfref>{_SELF_SUBJECT}))"
        ),
        _add_counters,
    ),
    # "put N +1/+1 counters on each creature you control" (RULE 601.2c mass
    # effect, Vastwood Surge-shaped).
    EffectHandler(
        "add_counters_selector",
        _c(
            rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
            r"each creature you control"
        ),
        _add_counters_selector,
    ),
    # "target creature gets +1/+0 until end of turn and can't be blocked
    # this turn" (You Come to a River-shaped) — tried before the plain
    # `pump` handler below since it's a strict superset of that shape (a
    # trailing unblockable clause `_pump`'s own grammar doesn't recognise).
    EffectHandler(
        "pump_unblockable",
        _PUMP_UNBLOCKABLE_RE,
        _pump_unblockable,
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
    # "surveil 2" (a self effect — the controller surveils; RULE 701.31).
    EffectHandler(
        "surveil",
        _c(rf"surveil {NUMBER}"),
        _surveil,
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
