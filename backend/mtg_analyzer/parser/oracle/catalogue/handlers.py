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
from .subgrammars import COUNT, NUMBER, TARGET, count_of, resolve_target_kind

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


def _draw(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {"count": count_of(m.group("n"))})]


def _discard(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discard", {"count": count_of(m.group("n"))})]


def _gain_life(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"amount": int(m.group("n"))})]


def _destroy(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent"):
        return None
    return [EffectSpec("destroy", {"target_kind": kind})]


def _counter(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("counter", {})]


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


def _pump_target(m: re.Match[str]) -> Optional[str]:
    """The pump's ``target_kind`` — or ``None`` to signal fail-closed.

    Returns the sentinel ``""`` for a self-pump ("~ gets …", untargeted) so the
    caller can tell it apart from an unrecognised target (real ``None``).
    """
    if m.groupdict().get("selfref"):
        return ""  # untargeted self-pump (an activated "~ gets +1/+0 …")
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "permanent"):
        return None
    return kind


def _pump(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    target_kind = _pump_target(m)
    if target_kind is None:
        return None
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
    return [EffectSpec("pump", params)]


def _pump_keywords(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    target_kind = _pump_target(m)
    if target_kind is None:
        return None
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    params: dict = {"keywords": keywords}
    if target_kind:
        params["target_kind"] = target_kind
    return [EffectSpec("pump", params)]


def _scry(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("scry", {"count": int(m.group("n"))})]


# A pump's subject: a targeted creature/permanent or the self-reference ``~``
# (a creature's own activated "~ gets +1/+0 …"). Shared by the pump handlers.
_SUBJECT = rf"(?:{TARGET}|(?P<selfref>{re.escape(SELF)}))"
#: A signed P/T delta, "+3/+3" / "-2/-2" / "+0/-1" (ASCII or unicode minus).
_PT_DELTA = r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"


# --- The table --------------------------------------------------------------
# Order matters only for reporting; a clause is claimed by the first handler
# whose full-clause regex matches. Every pattern is anchored to the whole
# clause by `EffectHandler.match`'s `fullmatch`, so no partial claims.

HANDLERS: list[EffectHandler] = [
    # "~ deals 3 damage to any target" / "deal 2 damage to target creature"
    EffectHandler(
        "damage",
        _c(rf"(?:~ )?deals? {NUMBER} damage to {TARGET}"),
        _damage,
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
    # "destroy target creature" / "destroy target artifact"
    EffectHandler(
        "destroy",
        _c(rf"destroy {TARGET}"),
        _destroy,
    ),
    # "counter target spell"
    EffectHandler(
        "counter",
        _c(rf"counter {TARGET}"),
        _counter,
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
    # "gets +1/+1 and gains trample until end of turn" / "~ gets +1/+0 …".
    EffectHandler(
        "pump",
        _c(
            rf"{_SUBJECT} gets {_PT_DELTA}"
            rf"(?: and gains (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _pump,
    ),
    # "target creature gains flying until end of turn" (keyword-only pump).
    EffectHandler(
        "pump_keyword",
        _c(rf"{_SUBJECT} gains (?P<kw>[a-z, ]+?) until end of turn"),
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
