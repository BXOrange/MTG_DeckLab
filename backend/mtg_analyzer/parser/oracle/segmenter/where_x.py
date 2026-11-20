"""Segmenter: where x (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from ..catalogue.clause_reading import (
    CHOSEN_PLAYER_NOUN,
    COUNTERED,
    CREATED,
    CREATED_GROUP_REFERENT,
    ClauseReading,
    MILLED,
    PLAYER,
    REVEALED,
    Referent,
    STANDALONE,
    TARGET,
    TARGET_REFERENT,
)
from typing import Any, Optional
from ..catalogue.count_phrase import parse_amount_phrase, parse_count_phrase
from ..catalogue.clause_primitives import CREATURE_TARGET_KINDS, TARGET_PARAM_KEYS
from ..catalogue.quantifier_scope import PLAYER_SETS, object_set, qualified_player_set, quantified_set
from ..catalogue.object_phrase import object_phrase_specs
from ..catalogue.effect_rows.shared import DEFENDING_PLAYER_COMBAT_EVENTS, base_verb
from ..catalogue.handlers import match_clause
from ..catalogue.referent_condition import PRONOUN_NOUN_ALT
from ..catalogue.named_groups import OF_ANY, battlefield_group
from ..spec import EffectSpec, GROUP_SUBJECT_KEY_SENTINEL
from .overrides_and_amounts import (
    DAMAGE_THIS_WAY_RE,
    announces_real_target,
    bound_for_each_amount,
    SAME_NAME_AS_SPELL_RE,
    count_amount,
    event_amount,
    spent_to_cast_amount,
    CAST_PAYMENT_SELECTORS,
    for_each_amount_specs,
    graveyard_arrival_amount,
    names_a_target,
)
from .pronoun_stamping import IT_DEALS_RE, deals_damage, stamp_damage_dealer
from .late import parse_effect_body
from .late import register

#: PAR-120: "`<effect with x>`, where X is the number of `<count phrase>`" and "`<you gain
#: life | draw cards | ~ deals damage>` equal to the number of `<count phrase>`" — the
#: effect parsed with a literal X (every X-capable handler already reads it) and the X
#: bound to one measured count, instead of one row per verb × per quantity.
WHERE_X_RE = re.compile(
    r"^(?P<rest>.+?),?\s+where x is the number of (?P<phrase>.+)$", re.IGNORECASE
)
_EQUAL_TO_RE = re.compile(
    r"^(?P<verb>.+?)\s+(?:a number of )?(?P<noun>life|cards?|damage) equal to the number of (?P<phrase>.+?)"
    r"(?P<tail>\s+to (?:any target|target [a-z ]+?|each opponent|each player|that player))?$",
    re.IGNORECASE,
)
#: The same quantity with the recipient *before* "equal to": "~ deals damage to target creature equal to
#: the number of lands you control." (Earth Tremor, Will of the Mardu, ~40 cards) — read as the
#: `_EQUAL_TO_RE` spelling "~ deals X damage to target creature" with X bound to the count.
_DAMAGE_TO_EQUAL_TO_RE = re.compile(
    r"^(?P<verb>.+?)\s+(?P<noun>damage)(?P<tail>\s+to (?:any target|target [a-z ]+?|each opponent|each player|that player))"
    r" equal to the number of (?P<phrase>.+)$",
    re.IGNORECASE,
)
#: "`<verb>` life/cards/damage equal to **the greatest power among creatures you control**" (Garruk,
#: Primal Hunter; ~25 cards) — an aggregate over a group rather than a count of it, read by
#: `count_phrase.parse_amount_phrase`. The recipient may sit before "equal to" or after the term.
_EQUAL_TO_AGGREGATE_RE = re.compile(
    r"^(?P<verb>.+?)\s+(?:a number of )?(?P<noun>life|cards?|damage)(?P<pre>\s+to (?:any target|target [a-z ]+?|each opponent|each player|that player))?"
    r" equal to (?P<phrase>[^.]+?)"
    r"(?P<tail>\s+to (?:any target|target [a-z ]+?|each opponent|each player|that player))?$",
    re.IGNORECASE,
)

#: The params an X can sit in once an X-capable handler has parsed the body.
_X_PARAM_KEYS: tuple[str, ...] = ("amount", "count", "power", "toughness", "max_mana_value", "exact_mana_value", "unless_pays_generic")


#: "`<effect with x>`, where x is the sacrificed creature's power" (Ghoulcaller Gisa, Atogatog) — X as an
#: amount term rather than "the number of …": read by `count_phrase.parse_amount_phrase` like the aggregates.
WHERE_X_AMOUNT_RE = re.compile(
    r"^(?P<rest>.+?),?\s+where x is (?P<phrase>[^.]+)$", re.IGNORECASE
)

#: RULE 107.2: "where x is half the number of <phrase>, rounded up/down" -- the count of `WHERE_X_RE` halved.
_HALF_DIVISOR = 2
WHERE_X_HALF_COUNT_RE = re.compile(
    r"^(?P<rest>.+?),?\s+where x is half the number of (?P<phrase>.+?), rounded (?P<round>up|down)$", re.IGNORECASE
)
#: "`<sentence>`, where x is `<phrase>`. `<more sentences>`" — the sentence defining X is not the last.
_WHERE_X_MID_BODY_RE = re.compile(
    r"^(?P<head>[^.]*?),\s*where x is (?P<phrase>[^.]+?)\.\s+(?P<tail>.+)$",
    re.IGNORECASE,
)


#: RULE 107.2 / 608.2: "`<head>`, where x is `<phrase>`. If x is `<n>` or more, `<effect>`." (The Destruction of
#: Praxis) -- the same X, a threshold on it, and a rider that needs no X of its own.
_WHERE_X_THRESHOLD_RE = re.compile(
    r"^(?P<head>[^.]*?),\s*where x is (?P<phrase>[^.]+?)\.\s+if x is (?P<n>\d+) or more,\s+(?P<tail>[^.]+)$",
    re.IGNORECASE,
)

#: "`<head>`, where x is `<phrase>`, then `<tail>`" — the definition sits between two parts of one
#: sentence ("look at the top x cards of your library, where x is the number of cards in your hand, then
#: put them back in any order", Descendant of Soramaro). Moved to the end, X is the same measurement.
_WHERE_X_THEN_RE = re.compile(
    r"^(?P<head>[^.]*?),\s*where x is (?P<phrase>[^.,]+?),\s*then (?P<tail>[^.]+)$", re.IGNORECASE,
)


_MINUS_TAIL_RE = re.compile(r"\s+minus (?P<n>\d+)$")
#: "`<N>` minus `<count>`" -- a literal minuend (The Rack: "3 minus the number of cards in their hand").
_MINUS_HEAD_RE = re.compile(r"^(?P<n>\d+) minus (?P<rest>the number of .+)$")
#: PAR-284: "`<N>` plus the number of `<count>`" -- a literal addend before one count (Thunder Salvo: "2 plus the number
#: of other spells you've cast this turn"); `effect_amounts`' ``plus`` adds it after the measurement.
_PLUS_HEAD_RE = re.compile(r"^(?P<n>\d+) plus (?P<rest>the number of .+)$")

#: RULE 706 (PAR-147): the number a die roll just produced, as the amount a sentence measures —
#: "`<effect with x>`, where x is **the result**" (Numbing Jellyfish), "`<verb>` life/cards/damage
#: equal to **the result**" (Big Boa Constrictor), "put a number of `<kind>` counters on `<where>` equal
#: to the result" and "create a number of `<tokens>` equal to the result" (Mother Kangaroo, Box of
#: Free-Range Goblins). The effect is parsed with a literal X and the X bound to the ``die_result``
#: amount (`GameContext.die_result`, the sum of the kept dice — so a kept die after "ignore one" is
#: what "the result" reads). "the total of those results" is the same sum; "minus N" floors at 0.
_DIE_PHRASE_AMOUNTS: dict[str, dict[str, Any]] = {
    "the result": {"kind": "die_result"},
    "the total of those results": {"kind": "die_result"},
    # The Endeavor cycle's "roll two dice and choose one result": the picked die and the one left over.
    "that result": {"kind": "die_choice", "which": "chosen"},
    "the other result": {"kind": "die_choice", "which": "other"},
}
_DIE_RESULT_PHRASE = "|".join(_DIE_PHRASE_AMOUNTS)
_DIE_MINUS_TAIL = r"(?: minus (?P<minus>\d+))?"
_DIE_DAMAGE_RECIPIENT = (
    r"(?:any target|target [a-z ]+?|each opponent|each player|that player|you"
    r"|each (?:creature|other creature|creature (?:you control|your opponents control|you don't control)))"
)
WHERE_X_DIE_RE = re.compile(
    rf"^(?P<rest>.+?),?\s+where x is (?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}$", re.IGNORECASE
)
_EQUAL_TO_DIE_RE = re.compile(
    rf"^(?P<verb>.+?)\s+(?P<noun>life|cards?|damage) equal to (?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}"
    rf"(?P<tail>\s+to {_DIE_DAMAGE_RECIPIENT})?$",
    re.IGNORECASE,
)
_DAMAGE_TO_EQUAL_TO_DIE_RE = re.compile(
    rf"^(?P<verb>.+?)\s+(?P<noun>damage)(?P<tail>\s+to {_DIE_DAMAGE_RECIPIENT})"
    rf" equal to (?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}$", re.IGNORECASE,
)
#: RULE 111.2 / 107.3: "create a number of <tokens> equal to <amount>" is "create X <tokens>, where X is <amount>" for
#: every measured amount the "where X is" grammar reads (Broodspinner: "equal to the number of card types among cards
#: in your graveyard"), not only the die result of `_TOKENS_EQUAL_DIE_RE` (that one is tried first).
_TOKENS_NUMBER_EQUAL_RE = re.compile(
    r"^create a number of (?P<what_token>[^.]+?(?: tokens?)(?: with [a-z, ]+?)?) equal to (?P<phrase>.+)$", re.IGNORECASE,
)
_COUNTERS_EQUAL_DIE_RE = re.compile(
    r"^put (?:a number of )?(?P<kind>[+\-]\d+/[+\-]\d+ |[a-z]+ )?counters? on (?P<where>.+?) equal to "
    rf"(?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}$", re.IGNORECASE,
)
_TOKENS_EQUAL_DIE_RE = re.compile(
    rf"^create a number of (?P<what_token>.+?) tokens?(?P<with> with [a-z, ]+?)? equal to "
    rf"(?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}$",
    re.IGNORECASE,
)


#: "search your library for a number of basic land cards equal to the other result, put them onto the battlefield
#: tapped, then shuffle" (Wild Endeavor) is "search your library for X basic land cards, …".
_SEARCH_NUMBER_DIE_RE = re.compile(
    rf"^(?P<head>search your library for) a number of (?P<what>.+?) equal to (?P<phrase>{_DIE_RESULT_PHRASE})"
    rf"{_DIE_MINUS_TAIL}(?P<tail>,.*)$", re.IGNORECASE,
)
#: "you may cast an instant or sorcery spell with mana value less than or equal to the other result from your hand
#: without paying its mana cost" (Arcane Endeavor) is "… with mana value X or less …".
_CAST_MV_DIE_RE = re.compile(
    rf"^(?P<pre>.+? with mana value) less than or equal to (?P<phrase>{_DIE_RESULT_PHRASE})"
    rf"{_DIE_MINUS_TAIL}(?P<post> from your hand.*)$", re.IGNORECASE,
)
#: "return a creature card from your graveyard to the battlefield with a number of +1/+1 counters on it equal to
#: that result" (Grave Endeavor) is "… with X +1/+1 counters on it".
_RETURN_COUNTERS_DIE_RE = re.compile(
    rf"^(?P<head>return .+? to the battlefield) with a number of (?P<kind>[+\-]\d+/[+\-]\d+|[a-z]+) counters on it"
    rf" equal to (?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}$", re.IGNORECASE,
)

_DESTROY_POWER_AT_LEAST_DIE_RE = re.compile(
    rf"destroy each creature with power greater than or equal to (?P<phrase>{_DIE_RESULT_PHRASE})", re.IGNORECASE,
)
_SCRY_NUMBER_OF_RE = re.compile(r"(?P<verb>scry|surveil) a number of", re.IGNORECASE)


#: "search your library for up to x <cards>, where x is <amount>[,.] put them onto the battlefield tapped, then shuffle".
_SEARCH_WHERE_X_MID_RE = re.compile(
    r"(?P<head>search your library for (?:up to )?x [^,]+?), where x is (?P<phrase>[^,.]+?)[,.] "
    r"(?P<tail>(?:put|then|reveal) .+)", re.IGNORECASE,
)


def _die_x_rest(text: str) -> "Optional[tuple[str, dict[str, Any]]]":
    """``(rest, amount)`` for a sentence measuring the die result, with the X written literally in
    ``rest``; ``None`` for any other sentence. See `_DIE_RESULT_PHRASE`."""
    m = WHERE_X_DIE_RE.match(text)
    if m is not None:
        rest = m.group("rest")
    else:
        m = _EQUAL_TO_DIE_RE.match(text) or _DAMAGE_TO_EQUAL_TO_DIE_RE.match(text)
        if m is not None:
            verb = m.group("verb")
            scry = _SCRY_NUMBER_OF_RE.fullmatch(verb) if m.group("noun").startswith("card") else None
            if scry is not None:  # "scry a number of cards equal to the result" is "scry X"
                rest = f"{scry.group('verb')} x"
            else:
                rest = f"{verb} x {m.group('noun')}{m.groupdict().get('tail') or ''}"
        else:
            m = _COUNTERS_EQUAL_DIE_RE.match(text)
            if m is not None:
                kind = (m.group("kind") or "").strip()
                if kind in ("a", "the", "that", "x"):  # "put a counter" / "put x counters": not a kind word
                    return None
                rest = f"put x {kind + ' ' if kind else ''}counters on {m.group('where')}"
            else:
                m = _TOKENS_EQUAL_DIE_RE.match(text)
                if m is not None:
                    rest = f"create x {m.group('what_token')} tokens{m.group('with') or ''}"
                else:
                    m = _SEARCH_NUMBER_DIE_RE.match(text)
                    if m is not None:
                        rest = f"{m.group('head')} x {m.group('what')}{m.group('tail')}"
                    else:
                        m = _CAST_MV_DIE_RE.match(text)
                        if m is not None:
                            rest = f"{m.group('pre')} x or less{m.group('post')}"
                        else:
                            m = _RETURN_COUNTERS_DIE_RE.match(text)
                            if m is None:
                                return None
                            rest = f"{m.group('head')} with x {m.group('kind')} counters on it"
    amount: dict[str, Any] = dict(_DIE_PHRASE_AMOUNTS[m.group("phrase").lower()])
    if m.group("minus"):
        # RULE 107.1b: a negative X is 0.
        amount = {**amount, "minus": int(m.group("minus")), "minimum": 0}
    return rest, amount


#: PAR-215 axis E: "destroy each nonland permanent with mana value equal to the number of charge counters on ~"
#: (Ratchet Bomb, Engineered Explosives, Powder Keg, Wave of Terror, The Moment): the mass destroy/exile verbs only --
#: a *targeted* bound has to resolve while the target is announced (RULE 601.2c), before any amount is measured.
_MANA_VALUE_AMOUNT_RE = re.compile(
    r"^(?P<head>(?:destroy|exile) (?:each|all) [^,]+? with mana value) "
    r"(?P<cmp>equal to|less than or equal to) (?P<phrase>the number of .+)$", re.IGNORECASE,
)


def _mana_value_bound_is_resolve_time(specs: "list[EffectSpec]") -> bool:
    """Whether the measured bound sits in an effect that filters at resolution (a mass group), not in a target."""
    for spec in specs:
        if spec.type != "bind":
            return False
        for effect in spec.params.get("effects", []):
            params = effect.get("params", {})
            if params.get("target_kind") not in (None, "permanent", "creature", "artifact", "nonland_permanent") and \
                    "$n" in repr(params):
                return False
            if "$n" not in repr(params):
                return False
    return True


#: PAR-215 axis E: a *targeted* mana-value bound that is a count of the controller's own permanents ("exile target
#: creature with mana value less than or equal to the number of Plains you control", Lay Down Arms; Dominating Vampire).
#: The bound is a RULE 601.2c target restriction, so it is measured while the target is offered
#: (`targeting.legal_targets`), and only a count taken as "you" -- a count relative to the target's controller
#: (Drown in the Loch) is a per-candidate comparison and stays unclaimed.
_MV_COUNT_BOUND_RE = re.compile(
    r"^(?P<head>.+? target [^,]+? with mana value) (?P<cmp>equal to|less than or equal to) "
    r"the number of (?P<phrase>[^,.]+? you control|cards in its controller's graveyard)(?P<tail>.*)$", re.IGNORECASE,
)
#: "the number of cards in **its controller's** graveyard" (Drown in the Loch): the count belongs to each candidate's
#: own controller, so the bound is compared per candidate (`targeting._candidate_mana_value_bound`).
_CANDIDATE_CONTROLLER_GRAVEYARD = "cards in its controller's graveyard"
#: The placeholder bound the existing rows parse; it never appears in printed text next to "the number of".
_MV_COUNT_PLACEHOLDER = 0


def mana_value_count_bound_specs(body: str, *, reading: ClauseReading = STANDALONE) -> "Optional[list[EffectSpec]]":
    m = _MV_COUNT_BOUND_RE.match(body.strip().rstrip(".").strip())
    if m is None:
        return None
    per_candidate = m.group("phrase").lower() == _CANDIDATE_CONTROLLER_GRAVEYARD
    selector = parse_count_phrase("cards in your graveyard" if per_candidate else m.group("phrase"))
    if not isinstance(selector, dict) or selector.get("of") != "you" \
            or selector.get("zone") != ("graveyard" if per_candidate else "battlefield") \
            or "distinct" in selector or "aggregate" in selector:
        return None
    exact = m.group("cmp").lower() == "equal to"
    if per_candidate and exact:
        return None  # only the ceiling is a printed shape
    placeholder = f"{_MV_COUNT_PLACEHOLDER}" if exact else f"{_MV_COUNT_PLACEHOLDER} or less"
    specs = parse_effect_body(f"{m.group('head')} {placeholder}{m.group('tail')}", reading=reading)
    key = "exact_mana_value" if exact else "max_mana_value"
    if not specs or len(specs) != 1 or specs[0].params.get(key) != _MV_COUNT_PLACEHOLDER \
            or isinstance(specs[0].params.get(key), bool):
        return None
    bound = {"candidate_controller_count": selector} if per_candidate else {"count_selector": selector}
    params = {**specs[0].params, key: bound}
    return [EffectSpec(specs[0].type, params, condition=specs[0].condition)]


#: Effects whose target requirement reads a `TargetSpec.max_mana_value` count-selector dict (RULE 601.2c): a
#: "mana value X or less, where X is <count>" ceiling has to be known while the target is offered, before the
#: ability resolves, so it cannot ride the resolve-time `bind` that other where-X sentences use.
_ANNOUNCE_TIME_MANA_VALUE_EFFECTS = frozenset({"return_from_graveyard"})


def _inline_announce_time_mana_value(specs: "Optional[list[EffectSpec]]") -> "Optional[list[EffectSpec]]":
    """PAR-215: ``bind(n = <amount>) { return_from_graveyard(max_mana_value=$n) }`` -> the effect with that amount as
    its own announce-time ceiling (Celestine, the Living Saint; Unforgiving One; Guardian Scalelord). An amount the
    target offer cannot measure (anything but a count selector or the source's own power) is refused: a bare
    ``$n`` left in a target bound would never resolve."""
    if not specs or len(specs) != 1 or specs[0].type != "bind":
        return specs
    bind = specs[0]
    inner = bind.params.get("effects") or []
    amount = bind.params.get("amount") or {}
    if len(inner) != 1 or bind.condition is not None:
        return specs
    effect = inner[0]
    params = effect.get("params") if isinstance(effect, dict) else None
    placeholder = f"${bind.params.get('name')}"
    if effect.get("type") not in _ANNOUNCE_TIME_MANA_VALUE_EFFECTS or not params \
            or params.get("max_mana_value") != placeholder:
        return specs
    if amount.get("kind") == "count_selector" and (
            isinstance(amount.get("selector"), str) and amount["selector"] in CAST_PAYMENT_SELECTORS):
        return None  # RULE 601.2c-h: targets are chosen before the cost is paid, so the payment is not yet known
    if amount.get("kind") == "count_selector" and set(amount) <= {"kind", "selector"}:
        bound: Any = {"count_selector": amount["selector"]}
    elif amount.get("kind") == "characteristic" and amount.get("of") == "source" \
            and amount.get("characteristic") == "power":
        bound = "source_power"  # `TargetSpec.max_mana_value`'s existing sentinel (RULE 208.1)
    else:
        return None
    return [EffectSpec(effect["type"], {**params, "max_mana_value": bound})]


#: "create x <tokens>, where x is <phrase>. the tokens have "<ability>"" (Cloudspire Coordinator, Return of the Mole Man).
_WHERE_X_TOKENS_HAVE_RE = re.compile(
    r'^(?P<head>create x [^"]+?),\s*where x is (?P<phrase>[^."]+)\.\s+the tokens have "(?P<ability>[^"]+)"$',
    re.IGNORECASE,
)


def where_x_threshold_body(text: str, *, reading: ClauseReading) -> "tuple[bool, Optional[list[EffectSpec]]]":
    """PAR-283: "…, where X is <phrase>. If X is N or more, <effect>." read whole, before any sentence-by-sentence pass.

    Returns ``(matched, specs)``. The second sentence's "If X is N or more" is the *defined* X, not the cast-time X
    (`x_paid`) the shared condition vocabulary reads for a spell that announced one, so once the shape matches a
    sentence split must never gate the rider: ``matched`` with no specs leaves the whole body unclaimed."""
    m = _WHERE_X_THRESHOLD_RE.match(text.strip().rstrip("."))
    if m is None:
        return False, None
    return True, _where_x_threshold_specs(m, reading=reading)


def where_x_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
    several: bool = False,
    divide_by: "Optional[tuple[int, bool]]" = None,
    announced: bool = False,
) -> "Optional[list[EffectSpec]]":
    specs = _where_x_specs_raw(body, reading=reading, several=several, divide_by=divide_by, announced=announced)
    if announced and not _carries_announced_count(specs):
        return None  # an early shape dropped the marker: the board would be read at resolution, not as announced
    return _inline_announce_time_mana_value(specs)


#: PAR-284 milestone 22 / RULE 601.2c, 601.2d: "..., where X is <count> as you cast this spell" -- the count is read as the
#: spell is announced (the number of targets, or the divided damage total) and never re-measured. Only the whole-clause tail.
_AS_YOU_CAST_RE = re.compile(r"^(?P<head>.+), where x is (?P<phrase>.+?) as you cast this spell$", re.S)
#: The effect params an announce-time count lands in (`spec.ANNOUNCED_COUNT_PARAMS`): a dict target count, or a divided total.
_ANNOUNCED_PARAM_KEYS: tuple[str, ...] = ("count_selector", "target_count_selector", "announced_amount")


def _carries_announced_count(specs: "Optional[list[EffectSpec]]") -> bool:
    return bool(specs) and len(specs) == 1 and any(
        isinstance(specs[0].params.get(key), dict) for key in _ANNOUNCED_PARAM_KEYS)


#: PAR-284 milestone 18 / RULE 608.2h: "`<group> you control` get +x/+x ..., where x is the number of colors among **those
#: creatures**" (General Tazri) -- the group the effect affects, measured as a count over that same group.
_AMONG_THOSE_RE = re.compile(
    r"^(?P<subject>[a-z ]+? you control) gets? (?P<middle>.+?where x is the number of [a-z ]+ among )those (?:creatures|permanents)$"
)


#: A clause whose only subject is the source ("~ deals x damage divided as you choose among any number of target
#: creatures, ...") and whose targets are all plural: a following "it" can only be the source, since no single object
#: has been announced for it to mean (Magmatic Core's "age counters on it"). A singular target keeps the pronoun open.
_SOURCE_SUBJECT_BODY_RE = re.compile(r"^~ (?!.*\btarget (?!(?:[a-z/-]+ )*?[a-z]+s\b))", re.IGNORECASE)


def _body_it_is_source(body: str) -> bool:
    """Whether "it" in this body's where-X phrase names the source (see `_SOURCE_SUBJECT_BODY_RE`)."""
    return _SOURCE_SUBJECT_BODY_RE.match(body.strip()) is not None


def _where_x_specs_raw(
    body: str, *, reading: ClauseReading = STANDALONE,
    several: bool = False,
    divide_by: "Optional[tuple[int, bool]]" = None,
    announced: bool = False,
) -> "Optional[list[EffectSpec]]":
    """See `WHERE_X_RE`; ``None`` unless the body parses to one effect holding the X — or,
    with ``several``, to several effects that share it ("~ deals X damage to target
    creature and you gain X life, where X is …" — one X for the whole sentence)."""
    text = body.strip().rstrip(".").strip()
    as_cast = _AS_YOU_CAST_RE.match(text)
    if as_cast is not None and not announced and divide_by is None and not several:
        return where_x_specs(f"{as_cast.group('head')}, where x is {as_cast.group('phrase')}", reading=reading,
                             announced=True)
    those = _AMONG_THOSE_RE.match(text)
    if those is not None:
        text = f"{those.group('subject')} get {those.group('middle')}{those.group('subject')}"
    quoted_tokens = _WHERE_X_TOKENS_HAVE_RE.match(text)
    if quoted_tokens is not None:
        # RULE 111.3: "create x <tokens>, where x is <amount>. The tokens have "<ability>"" -- the sentence is the
        # same native ability the token row reads from `<tokens> with "<ability>"`, so X is defined after it.
        head = quoted_tokens.group("head")
        joiner = "and" if " with " in head else "with"
        return where_x_specs(
            f'{head} {joiner} "{quoted_tokens.group("ability")}", where x is {quoted_tokens.group("phrase")}',
            reading=reading, several=several, divide_by=divide_by,
        )
    mana_value = _MANA_VALUE_AMOUNT_RE.match(text)
    if mana_value is not None:
        # RULE 202.3: "each permanent with mana value equal to / less than or equal to `<count>`" is the mass
        # "with mana value x [or less]" row with that count as X (measured once, when the ability resolves).
        bound = where_x_specs(
            f"{mana_value.group('head')} {'x' if mana_value.group('cmp') == 'equal to' else 'x or less'}, "
            f"where x is {mana_value.group('phrase')}", reading=reading, several=several, divide_by=divide_by,
        )
        return bound if bound is not None and _mana_value_bound_is_resolve_time(bound) else None
    inline_search = _SEARCH_WHERE_X_MID_RE.fullmatch(text)
    if inline_search is not None:
        # RULE 107.3a: "search your library for up to X <cards>, where X is <amount>, put them onto the battlefield
        # tapped, then shuffle" defines X mid-sentence (Boundless Realms); X is one measurement, so it reads the same
        # moved to the end of the sentence.
        text = f"{inline_search['head']}, {inline_search['tail']}, where x is {inline_search['phrase']}"
    inline_source = re.fullmatch(
        r"(?P<head>.+), where x is (?P<phrase>~'s (?:power|toughness|mana value)), (?P<tail>.+)", text,
    )
    if inline_source:
        text = f"{inline_source['head']}, {inline_source['tail']}, where x is {inline_source['phrase']}"
    # Keep the animation's type-retention sentence inside its own body;
    # the quantity still measures once for the whole grant (RULE 611.2d).
    retained = re.fullmatch(
        r"(?P<head>.+), where x is (?P<quantity>[^.]+)\. (?P<rider>it'?s still a land|they'?re still lands)",
        text, re.I | re.S,
    )
    if retained:
        text = f"{retained['head']}. {retained['rider']}, where x is {retained['quantity']}"
    halved = WHERE_X_HALF_COUNT_RE.match(text)
    if halved is not None and divide_by is None:
        # RULE 107.2: "where x is half the number of <phrase>, rounded up/down" is the count with a rounded halving.
        return where_x_specs(
            f"{halved.group('rest')}, where x is the number of {halved.group('phrase')}",
            reading=reading.unattached(),
            several=several,
            divide_by=(_HALF_DIVISOR, halved.group("round") == "up"),
        )
    between = _WHERE_X_THEN_RE.match(text)
    if between is not None:
        scope = reading.unattached()
        # One effect that reads "then" inside itself ("look at the top x cards …, then put them back in any order")…
        whole = where_x_specs(
            f"{between.group('head')}, then {between.group('tail')}, where x is {between.group('phrase')}",
            several=several, reading=scope,
        )
        if whole is not None:
            return whole
        # …otherwise X belongs to the first effect only and the rest follows it ("scry x, where x is …, then
        # draw 3 cards", Ugin's Insight): measured before the first effect, which nothing earlier can change.
        head = where_x_specs(f"{between.group('head')}, where x is {between.group('phrase')}", reading=scope)
        tail = parse_effect_body(between.group("tail").strip(), reading=scope) if head is not None else None
        return None if head is None or not tail else head + tail
    power_bound = _DESTROY_POWER_AT_LEAST_DIE_RE.fullmatch(text)
    if power_bound is not None:
        # "destroy each creature with power greater than or equal to that result" (Valiant Endeavor): the bound
        # is inside the mass filter, where the plain X holders of `bind_x_specs` do not reach.
        return [EffectSpec("bind", {
            "name": "n", "amount": dict(_DIE_PHRASE_AMOUNTS[power_bound.group("phrase").lower()]),
            "effects": [{"type": "destroy", "params": {"group": battlefield_group(OF_ANY), "filter": {"min_power": "$n"}}}],
        })]
    die_x = _die_x_rest(text)
    if die_x is None:
        number_equal = _TOKENS_NUMBER_EQUAL_RE.match(text)
        if number_equal is not None:
            return where_x_specs(
                f"create x {number_equal.group('what_token')}, where x is {number_equal.group('phrase')}",
                reading=reading, several=several, divide_by=divide_by,
            )
    if die_x is not None:
        return bind_x_specs(
            die_x[0], die_x[1], reading=reading.unattached(),
            several=several,
        )
    threshold = _WHERE_X_THRESHOLD_RE.match(text)
    if threshold is not None:
        return _where_x_threshold_specs(threshold, reading=reading)
    m = WHERE_X_RE.match(text)
    amount_m = WHERE_X_AMOUNT_RE.match(text) if m is None else None
    if amount_m is not None:
        m = amount_m
    elif m is None or "." in m.group("phrase"):
        # PAR-137: the definition sits mid-body — "exile the top x cards of your library, where x is
        # the number of creatures you control. You may play those cards this turn." X is one
        # measurement for the whole ability, so it reads the same moved to the end.
        mid = _WHERE_X_MID_BODY_RE.match(text)
        if mid is not None:
            return where_x_specs(
                f"{mid.group('head')}. {mid.group('tail')}, where x is {mid.group('phrase')}",
                reading=reading.unattached(),
                several=True,
            )
        if m is not None:
            return None  # a sentence break inside the phrase that is not this shape: not an X definition
    aggregate = None
    if amount_m is not None:
        aggregate, rest = m, m.group("rest")
    elif m is not None:
        rest = m.group("rest")
    else:
        m = _EQUAL_TO_RE.match(text) or _DAMAGE_TO_EQUAL_TO_RE.match(text)
        if m is None:
            m = aggregate = _EQUAL_TO_AGGREGATE_RE.match(text)
        if m is None:
            return None
        recipient = (m.groupdict().get("pre") or "") + (m.group("tail") or "")
        rest = f"{m.group('verb')} x {m.group('noun')}{recipient}"
    relative = (_count_difference_amount(m.group("phrase"), rest, reading=reading)
                or _relative_player_amount(m.group("phrase"), rest, reading))
    announce_player: "Optional[str]" = None
    if relative is None and (arrival := graveyard_arrival_amount(m.group("phrase"), reading=reading)) is not None:
        # RULE 115.1: "the number of cards put into target player's graveyard ..." names the ability's one target.
        announce_player, relative = arrival
    if relative is not None:
        amount = relative
    elif aggregate is not None:
        source_characteristic = re.fullmatch(r"~'s (power|toughness|mana value)", m.group("phrase"))
        if source_characteristic:
            amount = {"kind": "characteristic", "of": "source",
                      "characteristic": source_characteristic[1].replace(" ", "_")}
        elif m.group("phrase").endswith(" this way") and count_amount(m.group("phrase")) is not None:
            amount = count_amount(m.group("phrase"))
        elif re.fullmatch(r"the amassed army'?s (?:power|toughness)", m.group("phrase").strip().lower()):
            amount = count_amount(m.group("phrase").strip().lower())  # RULE 701.47a (MEC-145); the gate needs an `amass`
        elif DAMAGE_THIS_WAY_RE.match(m.group("phrase").strip().lower()) or SAME_NAME_AS_SPELL_RE.search(m.group("phrase")):
            amount = count_amount(m.group("phrase"))
        elif (event := event_amount(m.group("phrase"), reading=reading)) is not None:
            amount = event  # PAR-284 milestone 19: a damage / life event payload or tally ("where X is the damage dealt to ...")
        elif (spent := spent_to_cast_amount(m.group("phrase"), reading=reading)) is not None:
            amount = spent  # PAR-284 / RULE 601.2h: "where X is the amount of mana spent to cast it / that spell"
        else:
            term = parse_amount_phrase(m.group("phrase"))
            amount = None if term is None else {"kind": "count_selector", "selector": term}
            if amount is None and (plus_head := _PLUS_HEAD_RE.match(m.group("phrase"))) is not None:
                # Only after the amount grammar's own "N plus <count>" sum declined the count (a turn-history tally).
                counted = count_amount(
                    re.sub(r"^the number of ", "", plus_head.group("rest")),
                    reading=ClauseReading(self_subject=reading.self_subject),
                )
                amount = None if counted is None or "plus" in counted else {**counted, "plus": int(plus_head.group("n"))}
    else:
        phrase = m.group("phrase")
        # "…the number of cards in your hand **minus 4**" (Ivory Tower): a negative X counts as 0
        # (RULE 107.1b), so the subtraction is floored.
        minus = _MINUS_TAIL_RE.search(phrase)
        if minus is not None:
            phrase = phrase[: minus.start()]
        amount = count_amount(phrase, reading=ClauseReading(
            self_subject=reading.self_subject or _body_it_is_source(rest), referents=reading.referents_of(TARGET, PLAYER)))
        if amount is None and " plus the number of " in phrase:
            # "…the number of caves you control **plus the number of** cave cards in your graveyard" (Calamitous
            # Cave-In): a sum of counts, which the amount grammar reads as one expression.
            summed = parse_amount_phrase(f"the number of {phrase}")
            if isinstance(summed, dict) and "terms" in summed:
                amount = {"kind": "count_selector", "selector": summed}
        if amount is not None and minus is not None:
            amount = {**amount, "minus": int(minus.group("n")), "minimum": 0}
    if amount is None:
        return None
    if divide_by is not None:
        amount = {**amount, "divide": divide_by[0], **({"round_up": True} if divide_by[1] else {})}
    bound = bind_x_specs(
        rest, amount, reading=reading.unattached(),
        several=several, announced=announced,
    )
    if announce_player is not None:
        if bound is None or announces_real_target(bound) or announced:
            return None  # a body that already names a target would make this a second one
        return [EffectSpec("choose_targets", {"kinds": [announce_player]}), *bound]
    return bound


def _where_x_threshold_specs(
    match: "re.Match[str]", *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """See `_WHERE_X_THRESHOLD_RE`: the measured head, then the rider gated on that count reaching the threshold.

    The gate measures the same count again after the head ran (RULE 608.2c: instructions in order), which is the
    value X had only when the head cannot change what is counted: so only a pump head over a count of non-creatures
    (Praxis' lands) is read; anything else stays unclaimed."""
    bound = where_x_specs(
        f"{match.group('head')}, where x is {match.group('phrase')}", reading=reading.unattached(),
    )
    if not bound or len(bound) != 1 or bound[0].type != "bind":
        return None
    amount = bound[0].params["amount"]
    selector = amount.get("selector") if isinstance(amount, dict) else None
    inner = bound[0].params["effects"]
    # RULE 601.2i: a cast event's payload ("the amount of mana spent to cast that spell", Shantotto) is fixed once the
    # trigger fires, so the pump cannot change it either.
    fixed_event_amount = amount.get("kind") == "trigger_event"
    if (
        not (fixed_event_amount or (amount.get("kind") == "count_selector" and isinstance(selector, dict)
                                    and selector.get("filter", {}).get("card_type") != "creature"))
        or any(effect["type"] != "pump" for effect in inner)
    ):
        return None
    rider = parse_effect_body(match.group("tail").strip(), reading=reading.unattached())
    if not rider or any(names_a_target(spec) for spec in rider):
        return None
    gated = EffectSpec("if_else", {
        "condition": {
            "kind": "amount_compare", "left": amount, "op": "ge", "right": {"kind": "fixed", "amount": int(match.group("n"))},
        },
        "then": [spec.to_dict() for spec in rider],
    })
    return [EffectSpec("bind", {**bound[0].params, "effects": [*inner, gated.to_dict()]})]


#: PAR-215 axis D: a count taken *as another player* -- "the number of cards in **that player's** hand", "the number of
#: islands **they control**" (RULE 109.5: "they"/"that player" is the player the clause names, not "you").
_RELATIVE_PLAYER_COUNT_RE = re.compile(
    r"^(?P<twice>twice )?(?:the number of )?(?P<head>.+?)(?: (?P<control>that (?:player|opponent) controls|they control)"
    r"| in (?P<owner>their|that player's|that creature's controller's) (?P<zone>hand|graveyard))$"
)
#: PAR-284 milestone 23: the plural spelling after a group "Choose any number of target opponents." ("the total number
#: of creatures those players control").
_CHOSEN_PLURAL_COUNT_RE = re.compile(
    r"^(?:the (?:total )?number of )?(?P<head>.+?) (?P<control>those (?:players|opponents) control)$"
)
#: Placeholder for a relative count whose player is the body's own "that player" (resolved in `bind_x_specs`).
_THAT_PLAYER_HOLDER = "@that_player"
#: The damage selectors that name a trigger's own player -- also the `effect_conditions.subject_of` referents.
_TRIGGER_PLAYER_SELECTORS = frozenset({"active_player", "event_player"})
#: The player the effect body itself announces (RULE 115.1), whom a relative count is then taken as.
_BODY_TARGET_PLAYER_RE = re.compile(r"\btarget (?:player|opponent)\b")
#: PAR-284 milestone 21: the body's only target is a creature ("target creature gets -x/-x"), whose controller "that
#: creature's controller's hand" names (Flunk); `effect_amounts._as_player` reads an object subject as its controller.
_BODY_TARGET_CREATURE_RE = re.compile(r"\btarget creature\b")


#: PAR-284 milestone 21: "`<count>` minus `<count>`" -- a difference of two measured counts (Bulwark: "the number of cards
#: in your hand minus the number of cards in that player's hand").
_COUNT_DIFFERENCE_RE = re.compile(r"^(?:the number of )?(?P<left>.+?) minus (?P<right>the number of .+)$")


def _count_difference_amount(phrase: str, body: str, *, reading: ClauseReading) -> "Optional[dict[str, Any]]":
    """The minuend count with the subtrahend count as its ``minus`` amount, floored at 0 (RULE 107.1b).

    Each side is read as a count taken as another player when it names "that player's" zone
    (`_relative_player_amount`), else as the ability controller's own count. Only the minuend may carry the body's
    "that player" holder (`bind_x_specs` resolves one top-level holder); anything already carrying arithmetic is
    refused so the evaluation order stays unambiguous."""
    m = _COUNT_DIFFERENCE_RE.match(phrase.strip().lower())
    if m is None:
        return None
    sides = []
    for side in (f"the number of {m.group('left')}", m.group("right")):
        measured = _relative_player_amount(side, body)
        if measured is None:
            measured = count_amount(re.sub(r"^the number of ", "", side), reading=ClauseReading(
                self_subject=reading.self_subject, referents=reading.referents_of(TARGET, PLAYER)))
        if measured is None or measured.get("kind") != "count_selector" or {"minus", "plus"} & measured.keys():
            return None
        sides.append(measured)
    minuend, subtrahend = sides
    if subtrahend.get("of") == _THAT_PLAYER_HOLDER:
        return None
    return {**minuend, "minus": subtrahend, "minimum": 0}


#: "that player loses x life, where x is `<count difference>`": the step player's life loss measured by two counts.
_STEP_PLAYER_LOSES_DIFFERENCE_RE = re.compile(r"^that player loses x life, where x is (?P<phrase>.+?)\.?$")


def step_player_difference_specs(body: str) -> "Optional[list[EffectSpec]]":
    """RULE 107.1b / 603.2b: "that player loses X life, where X is the number of cards in that player's hand minus the
    number of cards in your hand" (Dark Suspicions) under a step trigger -- the active player's own count less the
    controller's, floored at 0. "That player" is the step's active player, so the minuend is measured ``of:
    active_player`` and the loss is read by the player acting in the step (`trigger_subject_referent` ``acting``)."""
    m = _STEP_PLAYER_LOSES_DIFFERENCE_RE.match(body.strip())
    if m is None:
        return None
    amount = _count_difference_amount(m.group("phrase"), "that player loses x life", reading=STANDALONE)
    if amount is None or amount.get("of") != _THAT_PLAYER_HOLDER:
        return None
    return [EffectSpec("bind", {"name": "n", "amount": {**amount, "of": "active_player"}, "effects": [EffectSpec(
        "trigger_subject_referent", {"acting": "active_player", "effects": [
            EffectSpec("lose_life", {"amount": "$n"}).to_dict()]}).to_dict()]})]


def _relative_player_amount(
    phrase: str, body: str, reading: ClauseReading = STANDALONE,
) -> "Optional[dict[str, Any]]":
    """"the number of `<X>` that player controls / in their hand" -> the `count_selector` amount taken as the target player.

    Only when the body announces exactly one player target ("deals x damage to target player", "target opponent loses
    x life"): that target is the player "they" / "that player" / "their" names, and ``of: target`` makes
    `effect_amounts` evaluate the count with that player as the controller. Any other antecedent (a trigger's player,
    an iteration) is refused here rather than guessed. A phrase naming its *own* "target opponent" is a second
    target the body does not announce, so only the pronoun spellings are read."""
    phrase = phrase.strip().lower()
    # "3 minus the number of cards in their hand" (The Rack, Wheel of Torture): the count is subtracted from a
    # literal, so it is the negated count plus that literal, floored at 0 (RULE 107.1b).
    head_minus = _MINUS_HEAD_RE.match(phrase)
    if head_minus is not None:
        measured = _relative_player_amount(head_minus.group("rest"), body, reading)
        if measured is None or "multiply" in measured or "minus" in measured:
            return None
        return {**measured, "multiply": -1, "plus": int(head_minus.group("n")), "minimum": 0}
    # "...the number of cards in their hand minus 4" (Iron Maiden): a negative X counts as 0 (RULE 107.1b).
    minus = _MINUS_TAIL_RE.search(phrase)
    if minus is not None:
        phrase = phrase[: minus.start()]
    chosen = next((r for r in reading.referents if r.kind == PLAYER and r.noun == CHOSEN_PLAYER_NOUN), None)
    if chosen is not None and not _BODY_TARGET_PLAYER_RE.search(body):
        # PAR-284 milestone 23 / RULE 109.5: an earlier "Choose target opponent(s)." announced the players, so "that
        # player" / "those opponents" are exactly them: measured as the chosen player (each, summed, for a group).
        plural = _CHOSEN_PLURAL_COUNT_RE.match(phrase)
        m = plural or _RELATIVE_PLAYER_COUNT_RE.match(phrase)
        if m is None or m.group("control") is None or (chosen.group != (plural is not None)):
            return None
        selector = parse_count_phrase(m.group("head") + " you control")
        if not isinstance(selector, dict) or selector.get("of") != "you" or "distinct" in selector:
            return None
        amount = {"kind": "count_selector", "selector": selector, "of": "target"}
        if plural:
            amount["each_target"] = True
        elif m.group("twice"):
            amount["multiply"] = 2
        if minus is not None:
            amount.update(minus=int(minus.group("n")), minimum=0)
        return amount
    m = _RELATIVE_PLAYER_COUNT_RE.match(phrase)
    if m is None:
        return None
    targets = len(_BODY_TARGET_PLAYER_RE.findall(body))
    if m.group("owner") == "that creature's controller's":
        # RULE 109.5: the controller of the one creature the body targets; any other body shape is refused.
        if targets or len(_BODY_TARGET_CREATURE_RE.findall(body)) != 1:
            return None
        targets = 1
    elif targets > 1 or (targets == 0 and not re.search(r"\bthat player\b", body)):
        return None
    tail = f" in your {m.group('zone')}" if m.group("zone") else " you control"
    selector = parse_count_phrase(m.group("head") + tail)
    if not isinstance(selector, dict) or selector.get("of") != "you" or "distinct" in selector:
        return None
    amount = {"kind": "count_selector", "selector": selector, "of": "target" if targets else _THAT_PLAYER_HOLDER}
    # `effect_amounts` multiplies a measured count by ``multiply`` ("twice the number of ...").
    if m.group("twice"):
        amount["multiply"] = 2
    if minus is not None:
        amount.update(minus=int(minus.group("n")), minimum=0)
    return amount


#: Named count selectors a ", where X is <count>" may bind to "up to X target <things>": RULE 601.2c has the number
#: of targets chosen as the ability is put on the stack, so `targeting.resolved_count` reads them off the board then
#: (a `bind` would measure at resolution, after the targets were chosen).
# PAR-314: ``source_kicker_count`` ("up to X target creature cards, where X is the number of times ~ was kicked",
# Marshal's Anthem) -- RULE 702.33d, recorded at cast so it is known when the targets are chosen.
_X_TARGET_COUNT_SELECTORS: frozenset[str] = frozenset({"opponents_attacked_this_turn", "source_kicker_count"})
_SOURCE_COUNTERS_SELECTOR = re.compile(r"^source_[a-z]+_counters$")
_X_TARGET_COUNT_KEYS: tuple[str, ...] = ("count_selector", "target_count_selector")


def _rebind_announced_choose(inner: "list[EffectSpec]", selector: Any) -> "Optional[list[EffectSpec]]":
    """PAR-285: the counted-target operand composes ``seq[choose_targets, for_each]`` (`object_phrase._compose`), so the
    announced-X count lives on the nested `choose_targets`; rebind exactly that one announcement's cast-{X} count to
    ``selector`` (RULE 601.2c), leaving the loop body untouched. ``None`` unless that is the single X in the body."""
    if len(inner) != 1 or inner[0].type != "seq" or inner[0].condition is not None:
        return None
    effects = [dict(e) for e in inner[0].params.get("effects", [])]
    hits = [e for e in effects if e.get("type") == "choose_targets"
            and (e.get("params") or {}).get("count_selector") == "source_x_paid"]
    if len(hits) != 1:
        return None
    body = [e for e in effects if e is not hits[0]]
    if any(v in ("x", "-x", "source_x_paid") for e in body for v in _flat_values(e)):
        return None  # the loop body reads the cast {X} too: it would need the same measurement
    hits[0]["params"] = {**hits[0]["params"], "count_selector": selector}
    return [EffectSpec("seq", {**inner[0].params, "effects": effects})]


def _flat_values(node: Any):
    if isinstance(node, dict):
        for value in node.values():
            yield from _flat_values(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _flat_values(value)
    else:
        yield node


def _bind_x_target_count(
    inner: "list[EffectSpec]", amount: "dict[str, Any]",
) -> "Optional[list[EffectSpec]]":
    """"goad up to X target creatures, where X is the number of opponents you attacked this turn" -- the single
    effect's announced-X target count rebound from the cast {X} (``source_x_paid``) to the named count; ``None``
    when the body is not exactly that shape."""
    selector = amount.get("selector") if amount.get("kind") == "count_selector" else None
    if (amount.get("kind") == "counters" and amount.get("of") == "source" and set(amount) <= {"kind", "counter", "of"}
            and re.fullmatch(r"[a-z]+", str(amount.get("counter") or ""))):
        # RULE 602.2b / 601.2c: "up to X target <things>, where X is the number of verse counters on ~" -- the source's
        # own counters of one kind, read while announcing (before a sacrifice cost removes the source).
        selector = f"source_{amount['counter']}_counters"
    if not isinstance(selector, str) or len(inner) != 1 or (
            selector not in _X_TARGET_COUNT_SELECTORS and not _SOURCE_COUNTERS_SELECTOR.match(selector)):
        return None
    if inner[0].type == "seq":
        return _rebind_announced_choose(inner, selector)
    params = dict(inner[0].params)
    keys = [k for k in _X_TARGET_COUNT_KEYS if params.get(k) == "source_x_paid"]
    if len(keys) != 1 or any(params.get(k) in ("x", "-x") for k in _X_PARAM_KEYS):
        return None
    params[keys[0]] = selector
    return [EffectSpec(inner[0].type, params, inner[0].condition)] if inner[0].condition is not None \
        else [EffectSpec(inner[0].type, params)]


def _announced_selector(amount: "dict[str, Any]") -> "Optional[dict[str, Any]]":
    """The structured count selector (or firing-event payload) an announce-time "where X is ..." amount measures, or
    ``None`` unless it is a plain measurement of the ability controller's board with no player referent, arithmetic
    beyond the selector's own, or target dependence (a count about "target opponent" needs the other target first)."""
    if amount.get("kind") == "trigger_event" and set(amount) == {"kind", "field", "event"}:
        return dict(amount)
    selector = amount.get("selector") if amount.get("kind") == "count_selector" else None
    if set(amount) != {"kind", "selector"} or not isinstance(selector, dict):
        return None
    return selector


def _bind_announced_count(inner: "list[EffectSpec]", amount: "dict[str, Any]") -> "Optional[list[EffectSpec]]":
    """RULE 601.2c / 601.2d: the single effect's cast-{X} count rebound to the count measured as it is announced --
    the number of targets (``count_selector`` / ``target_count_selector``) or a divided damage's total
    (``announced_amount``, frozen by `damage_division.prepare`). ``None`` for any other shape."""
    selector = _announced_selector(amount)
    if selector is None or len(inner) != 1 or inner[0].condition is not None:
        return None
    if inner[0].type == "seq":
        return _rebind_announced_choose(inner, selector)
    params = dict(inner[0].params)
    if inner[0].type == "damage" and params.get("divided") and params.get("amount") == "x":
        if selector.get("kind") == "trigger_event":
            return None  # a trigger has no "as you cast" moment: only a spell announces a division total
        params.update(amount=0, announced_amount=selector, division_required=True)
        return [EffectSpec("damage", params)]
    keys = [k for k in _X_TARGET_COUNT_KEYS if params.get(k) == "source_x_paid"]
    if len(keys) != 1 or any(params.get(k) in ("x", "-x") for k in _X_PARAM_KEYS):
        return None
    params[keys[0]] = selector
    return [EffectSpec(inner[0].type, params)]


#: A counter's printed unless-cost whose X the sentence defines ("pays {X}, where X is its mana value").
_UNLESS_PAYS_X = "{x}"
#: `counter_unless_pay`'s cost text for the same `{X}` unless-cost.
_COUNTER_UNLESS_PAY_X_COST = f"pay {_UNLESS_PAYS_X}"


def bind_x_specs(
    rest: str, amount: "dict[str, Any]", *, reading: ClauseReading = STANDALONE,
    several: bool = False, announced: bool = False,
) -> "Optional[list[EffectSpec]]":
    """``rest`` parsed with a literal X, the X bound to the measured ``amount`` (see `where_x_specs`)."""
    inner = parse_effect_body(
        rest.strip(), reading=reading.unattached(),
    )
    if not inner or (len(inner) != 1 and not several):
        return None
    if announced:
        return _bind_announced_count(inner, amount)
    if amount.get("kind") in ("trigger_event", "count_selector") and any(
            inner[0].params.get(key) == "source_x_paid" for key in _X_TARGET_COUNT_KEYS):
        # RULE 603.3d / 601.2c: "whenever you scry, ... up to X target creatures, where X is the number of cards looked at
        # while scrying this way" -- the firing event is known when the trigger's targets are chosen; and an ability
        # counts its board as it is put on the stack, the one moment X, a number of targets, is ever used.
        announced_count = _bind_announced_count(inner, amount)
        if announced_count is not None:
            return announced_count
    target_x = _bind_x_target_count(inner, amount)
    if target_x is not None:
        return target_x
    if amount.get("kind") == "characteristic" and amount.get("of") == "source":
        # RULE 107.1b: a measured modifier uses zero for a negative result;
        # setting base P/T is the explicit exception and keeps its sign.
        sets_pt = all(
            spec.type == "grant_until" and spec.params.get("static", {}).get("type") == "type_change"
            for spec in inner
        )
        if not sets_pt:
            amount = {**amount, "minimum": 0}
    effects: list[dict[str, Any]] = []
    bound_any = False
    for spec in inner:
        params = dict(spec.params)
        if spec.type == "counter" and params.get("unless_pays") == _UNLESS_PAYS_X:
            # RULE 107.3a / 118.12: "unless its controller pays {X}, where X is <amount>" -- X is the measured generic cost.
            del params["unless_pays"]
            params["unless_pays_generic"] = "x"
        if spec.type == "counter_unless_pay" and params.get("cost") == _COUNTER_UNLESS_PAY_X_COST:
            # The cast-trigger sibling ("counter that spell unless that player pays {X}, where X is <amount>", Cephalid Shrine).
            del params["cost"]
            params["unless_pays_generic"] = "x"
        # "-x" (a pump's -X/-X) binds as the negated measurement.
        negated = [k for k in _X_PARAM_KEYS if params.get(k) == "-x"]
        if any(v == "-x" for k, v in params.items() if k not in _X_PARAM_KEYS):
            return None
        holders = [k for k in _X_PARAM_KEYS if params.get(k) in ("x", "-x")]
        nested = False
        if spec.type == "grant_until":
            for key in ("static", "extra_statics"):
                if key in params:
                    params[key], replaced = _replace_x(params[key])
                    nested = nested or replaced
        if not holders and isinstance(params.get("then_effects"), list):
            # An X inside the effects that follow a pick ("return a creature card … with X counters on it").
            params["then_effects"], nested = _replace_x(params["then_effects"])
        if isinstance(params.get('return_effects'), list):
            params['return_effects'], return_x = _replace_x(params['return_effects'])
            nested = nested or return_x
        for group_key in ("filter", "group", "over"):
            # A mass effect's own filter ("destroy each nonland permanent with mana value x or less").
            if isinstance(params.get(group_key), dict):
                params[group_key], group_x = _replace_x(params[group_key])
                nested = nested or group_x
        if isinstance(params.get('extra_counters'), dict):
            params['extra_counters'], counter_x = _replace_x(params['extra_counters'])
            nested = nested or counter_x
        if isinstance(params.get('effects'), list):
            params['effects'], effect_x = _replace_x(params['effects'])
            nested = nested or effect_x
        if several and not bound_any and not (holders or nested):
            # "put a +1/+1 counter on ~, then create X tokens, where X is the number of
            # counters on ~" (Anim Pakal) measures *after* the first effect; a bind
            # measures once, before all of them. A non-X tail after the first
            # measured instruction is safe; an earlier non-X effect is not.
            return None
        for key in holders:
            params[key] = "-$n" if key in negated else "$n"
        bound_any = bound_any or bool(holders) or nested
        entry = {"type": spec.type, "params": params}
        if spec.condition is not None:
            entry["condition"] = dict(spec.condition)
        effects.append(entry)
    if not bound_any:
        return None
    if amount.get("of") == _THAT_PLAYER_HOLDER:
        # RULE 109.5: "that player" is whichever player the body's own recipient names (a trigger's active player,
        # the player a spell cast): read it back off the parsed body, and refuse anything else.
        holders = {e["params"].get("selector") for e in effects}
        if len(holders) != 1 or not holders <= _TRIGGER_PLAYER_SELECTORS:
            return None
        amount = {**amount, "of": next(iter(holders))}
        # Only a step trigger names its player without a target: `_phase_damage_referents` turns the body's
        # "that player" into the active player there. Under a spell-cast / damage / attack head the event's own
        # ``player_id`` is not that player, so the gate rejects the marker anywhere else (`gate._resolve_event_player_tree`).
        return [EffectSpec("bind", {
            "name": "n", "amount": amount, "effects": effects, "event_player_events": ["STEP_BEGIN"],
        })]
    return [EffectSpec("bind", {"name": "n", "amount": amount, "effects": effects})]


#: PAR-123: an amount that is a characteristic of the object a pronoun names — "put x +1/+1 counters
#: on it, where x is **its power**", "gain life equal to **that creature's toughness**", "create X
#: tokens, where X is **that creature's mana value**". The effect is parsed with a literal X and the
#: X bound to that object's characteristic (`effect_amounts`' ``characteristic``), the same shape
#: `where_x_specs` gives a counted quantity.
_REFERENT_WHAT = r"(?P<what>power|toughness|mana value)"
#: PAR-284: also the definite spellings of the same referents -- "the exiled / discarded / milled card's", "the
#: spell's" -- and the noun types `PRONOUN_NOUN_ALT` leaves out ("that enchantment's mana value", Aura Mutation).
_REFERENT_CARD_VERBS = "exiled|discarded|milled|revealed|returned"
_REFERENT_POSSESSIVE = (
    rf"(?P<possessive>its|that (?:{PRONOUN_NOUN_ALT}|enchantment|planeswalker|battle|card|spell)'s"
    rf"|the (?:{_REFERENT_CARD_VERBS}) card's|the spell's)"
)
WHERE_X_CHARACTERISTIC_RE = re.compile(
    rf"^(?P<rest>.+?),?\s+where x is {_REFERENT_POSSESSIVE} {_REFERENT_WHAT}$", re.IGNORECASE
)
_EQUAL_TO_CHARACTERISTIC_RE = re.compile(
    rf"^(?P<verb>.+?)\s+(?P<noun>life|cards?|damage) equal to {_REFERENT_POSSESSIVE} {_REFERENT_WHAT}"
    r"(?P<tail>\s+to (?:any target|(?:up to (?:one|1) )?target [a-z ]+?|each opponent|each player|that player))?$",
    re.IGNORECASE,
)
#: "~ deals damage **to that player** equal to that card's mana value" -- the recipient before "equal to".
_DAMAGE_RECIPIENT_EQUAL_CHARACTERISTIC_RE = re.compile(
    rf"^(?P<verb>.+? deals?) damage (?P<recipient>to (?:that player|that creature|you|target [a-z ]+?|each opponent)) equal to "
    rf"{_REFERENT_POSSESSIVE} {_REFERENT_WHAT}$",
    re.IGNORECASE,
)
#: "put +1/+1 counters on X equal to its power" / "put a number of +1/+1 counters on X equal to its
#: power" / "create a number of 1/1 … tokens equal to its power" — the count is the X.
_COUNTERS_EQUAL_CHARACTERISTIC_RE = re.compile(
    rf"^put (?:a number of )?(?P<kind>(?:[+\-]\d+/[+\-]\d+|[a-z]+) )?counters? on (?P<where>.+?) equal to "
    rf"{_REFERENT_POSSESSIVE} {_REFERENT_WHAT}$", re.IGNORECASE,
)
_TOKENS_EQUAL_CHARACTERISTIC_RE = re.compile(
    rf"^create a number of (?P<what_token>.+?) tokens? equal to {_REFERENT_POSSESSIVE} {_REFERENT_WHAT}$",
    re.IGNORECASE,
)
#: The effect bodies whose own subject is the target they announce (so "its" / "that creature's" is that target, never
#: the source or a player): "target creature gets +X/+X, ..." and "put X counters on target creature, ...".
_SAME_CLAUSE_TARGET_BODY_RE = re.compile(
    r"^(?:until end of turn, )?(?:another )?target [a-z ]+? (?:gets?|gains?) .+$"
    r"|^put x [^,]*? counters? on (?:another )?target [a-z ]+$", re.IGNORECASE,
)
_CHARACTERISTIC_NAMES = {"power": "power", "toughness": "toughness", "mana value": "mana_value"}
#: PAR-284: "where x is **the mana value of that spell**" / "the power of the exiled card" is the possessive reading
#: "that spell's mana value" with the characteristic named first (same referent, same measurement).
_OF_ORDER_RE = re.compile(
    r"\bwhere x is the (?P<what>power|toughness|mana value) of "
    rf"(?P<owner>that (?:{PRONOUN_NOUN_ALT}|enchantment|planeswalker|battle|card|spell)|the (?:{_REFERENT_CARD_VERBS}) card"
    r"|the spell|the creature that died)\b",
    re.IGNORECASE,
)


#: PAR-284: "the power of the creature that died" is a dies trigger's own subject, the same referent "that creature's
#: power" names (RULE 700.4 / 608.2h last-known information).
_OF_ORDER_OWNERS = {"the creature that died": "that creature"}


def _replace_x(node: Any) -> "tuple[Any, bool]":
    """``node`` with each "x" magnitude in its nested effect specs swapped for the bound ``$n``."""
    if isinstance(node, dict):
        replaced = False
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _X_PARAM_KEYS and value == "x":
                out[key] = "$n"
                replaced = True
            elif key in ("power", "toughness") and value == "-x":
                out[key] = "-$n"  # "gets -X/-X ..., where X is ..." (`BindEffect._substitute` negates the measurement)
                replaced = True
            else:
                out[key], inner = _replace_x(value)
                replaced = replaced or inner
        return out, replaced
    if isinstance(node, list):
        pairs = [_replace_x(item) for item in node]
        return [p[0] for p in pairs], any(p[1] for p in pairs)
    return node, False


_COUNTER_UNLESS_ITS_MV_RE = re.compile(
    r"(?P<rest>counter target [a-z ]*?spell unless its controller pays \{x\}),? where x is its mana value", re.IGNORECASE,
)


def referent_characteristic_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """See `_REFERENT_WHAT`; ``None`` unless the body reads as one X-taking effect."""
    text = _OF_ORDER_RE.sub(lambda g: f"where x is {_OF_ORDER_OWNERS.get(g.group('owner').lower(), g.group('owner'))}'s {g.group('what')}", body.strip().rstrip(".").strip())
    counter_cost = _COUNTER_UNLESS_ITS_MV_RE.fullmatch(text)
    if counter_cost is not None:
        # RULE 118.12 / 608.2h: "counter target spell unless its controller pays {X}, where X is its mana value" -- "its"
        # is the one spell this clause targets, measured as the counter resolves.
        return bind_x_specs(
            counter_cost.group("rest"),
            {"kind": "characteristic", "characteristic": _CHARACTERISTIC_NAMES["mana value"], "of": "target"},
            reading=reading.unattached(),
        )
    has_referent = (reading.self_subject or reading.group_subject or reading.previous_subject
                    or reading.attached_subject or bool(reading.referents_of(REVEALED, MILLED)))
    if not has_referent and not re.search(r"\btarget\b", text):
        return None
    mid = _WHERE_X_MID_BODY_RE.match(text)
    if mid is not None and re.fullmatch(
        rf"{_REFERENT_POSSESSIVE} {_REFERENT_WHAT}", mid.group("phrase"), re.I,
    ):
        # The library-selection body reads the same X in a later sentence.
        # Move only its definition, preserving the body and its reading.
        text = f"{mid.group('head')}. {mid.group('tail')}, where x is {mid.group('phrase')}"
    m = WHERE_X_CHARACTERISTIC_RE.match(text)
    if m is not None:
        rest = m.group("rest")
    else:
        m = _EQUAL_TO_CHARACTERISTIC_RE.match(text)
        if m is not None:
            rest = f"{m.group('verb')} x {m.group('noun')}{m.group('tail') or ''}"
        elif (m := _DAMAGE_RECIPIENT_EQUAL_CHARACTERISTIC_RE.match(text)) is not None:
            rest = f"{m.group('verb')} x damage {m.group('recipient')}"
        else:
            m = _COUNTERS_EQUAL_CHARACTERISTIC_RE.match(text)
            if m is not None:
                rest = f"put x {m.group('kind') or ''}counters on {m.group('where')}"
            else:
                m = _TOKENS_EQUAL_CHARACTERISTIC_RE.match(text)
                if m is None:
                    return None
                rest = f"create x {m.group('what_token')} tokens"
    if re.match(r"(?:gains|draws|loses|discards|mills|sacrifices)\b", rest.strip(), re.IGNORECASE):
        # A third-person verb with no subject of its own ("…, then gains life equal to that
        # creature's toughness") acts for whoever the clause before it named — not necessarily "you".
        return None
    explicit_source = bool(re.match(r"~ (?:gets?|deals?)\b", rest) or re.match(r"put x .+ counters? on ~(?!\w)", rest))
    # RULE 701.20: after "reveal the top card of your library and put it into your hand" the pronoun and "that
    # card" name that card, not the ability's source (`GameContext.revealed_card`, or the card the exile left).
    revealed = next((r for r in reading.referents if r.kind == REVEALED), None)
    # PAR-284: "the exiled card's" / "the discarded card's" and "the spell's" name what "that card's" / "that spell's"
    # name; the participle only restates which earlier clause produced it, which the referent environment decides.
    possessive = m.group("possessive").lower()
    # RULE 701.17: "the milled card's" after a one-card mill is measured over the ``milled`` this-way pool.
    milled_pool = possessive == "the milled card's" and bool(reading.referents_of(MILLED))
    event_spell_mv = False
    if possessive.startswith("the ") and possessive.endswith(" card's"):
        possessive = "that card's"
    elif possessive == "the spell's":
        possessive = "that spell's"
    if milled_pool:
        referent = MILLED
    elif revealed is not None and (possessive == "that card's" or (possessive == "its" and not explicit_source)):
        referent = revealed.noun
    elif possessive == "that spell's":
        # RULE 608.2h: last-known information of the spell an earlier clause countered. A token the clause before
        # made is not that spell ("create a token. Put X counters on it, where X is that spell's mana value" names
        # the spell that fired the trigger), so only a counter antecedent binds it.
        if reading.referents_of(COUNTERED):
            referent = "previous_subject"
        elif reading.self_subject and not reading.previous_subject and m.group("what").lower() == "mana value":
            # RULE 601.2i: under a "whenever you cast ..." head the spell is the firing `SPELL_CAST` event's own
            # ``mana_value`` (X resolved), the same read `_incubate_x` / `_damage_spell_mv` make.
            event_spell_mv, referent = True, "source"  # `referent` unused: the amount reads the event
        else:
            return None
    elif possessive == "that card's" and (reading.referents_of(CREATED) or not reading.previous_subject):
        return None  # a made token is no "card"; with no card picked earlier the noun has no antecedent
    elif possessive != "its":
        # a self trigger establishes no "that creature/artifact" antecedent (`same_clause_target` below may supply one)
        referent = ("previous_target" if reading.previous_subject else
                    "trigger_subject" if reading.group_subject else "")
    else:
        referent = ("source" if explicit_source else "previous_target" if reading.previous_subject else
                    "source" if reading.self_subject else "trigger_subject")
    # PAR-284 / RULE 608.2h: "target creature gets +X/+X, where X is its power" / "put X counters on target creature,
    # where X is that creature's mana value" -- with no earlier clause, trigger subject or host to name, the pronoun
    # is the one target this same clause announces (read before the body applies, like Drain Life's `of: target`).
    same_clause_target = (
        not event_spell_mv and not explicit_source and possessive != "that card's" and possessive != "that spell's"
        and not (reading.previous_subject or reading.group_subject or reading.attached_subject
                 or reading.referents_of(REVEALED))
        and _SAME_CLAUSE_TARGET_BODY_RE.match(rest) is not None
    )
    if same_clause_target:
        referent = "target"
    elif not has_referent or not referent:
        return None
    amount = {
        "kind": "characteristic", "characteristic": _CHARACTERISTIC_NAMES[m.group("what").lower()],
        "of": referent,
    } if not event_spell_mv else {"kind": "trigger_event", "field": "mana_value"}
    if milled_pool:
        amount = {"kind": "this_way_sum", "pool": MILLED, "characteristic": _CHARACTERISTIC_NAMES[m.group("what").lower()]}
    if referent == "trigger_subject":
        amount["event_key"] = GROUP_SUBJECT_KEY_SENTINEL
    inner = parse_effect_body(
        rest.strip(), reading=reading.unattached(),
    )
    if not inner:
        return None
    if not all(spec.type == "grant_until" and spec.params.get("static", {}).get("type") == "type_change"
               for spec in inner):
        # RULE 107.1b: preserve signed base P/T settings, while calculated
        # modifier/count/life results use zero instead of a negative value.
        amount["minimum"] = 0
    if same_clause_target:
        kinds = _announced_target_kinds([spec.to_dict() for spec in inner])
        if len(kinds) != 1 or kinds[0] not in CREATURE_TARGET_KINDS:
            return None  # exactly one announced permanent target, or the pronoun has no single referent
    effects: list[dict[str, Any]] = []
    bound_any = False
    for spec in inner:
        if spec.type in ("create_turn_trigger", "create_delayed_trigger"):
            return None  # the future trigger measures its characteristic when it resolves
        data, replaced = _replace_x(spec.to_dict())
        if (len(inner) > 1 and not bound_any and not replaced
                and not (spec.type == "trigger_subject_referent" and not spec.params.get("effects"))):
            return None  # an earlier non-X instruction may change the measured characteristic
        bound_any = bound_any or replaced
        effects.append(data)
    if not bound_any:
        return None
    bound = EffectSpec("bind", {"name": "n", "amount": amount, "effects": effects})
    if reading.attached_subject and IT_DEALS_RE.search(rest) and deals_damage(bound):
        bound = stamp_damage_dealer(bound)
    return [bound]


def _announced_target_kinds(node: Any) -> list[str]:
    """Every string ``target_kind`` param in a nested spec dict tree (RULE 115: the targets a clause announces)."""
    if isinstance(node, dict):
        found = [node["target_kind"]] if isinstance(node.get("target_kind"), str) else []
        return found + [k for v in node.values() for k in _announced_target_kinds(v)]
    if isinstance(node, (list, tuple)):
        return [k for v in node for k in _announced_target_kinds(v)]
    return []


#: PAR-128: the player-subject slot. "each player mills 3 cards", "each opponent gains 10
#: life", "target opponent becomes the monarch" — the verb's own grammar already reads
#: "target player `<verb>`" (one player target, nothing else), so the subject is a
#: slot over that reading rather than a word in every verb's row: "each player / each
#: opponent" iterates the body over those players (`for_each` hands each one to it as
#: its target, APNAP order, RULE 101.4), and "target opponent" narrows the target.
PLAYER_SCOPE_SUBJECT_RE = re.compile(
    r"^(?P<who>each other player|each player|each opponent|target opponent|target player|that player) (?P<rest>.+)$", re.IGNORECASE
)


def player_action_outcome_specs(body: str, reading: ClauseReading) -> Optional[list[EffectSpec]]:
    """Bind a qualified payoff to the preceding shared player instruction."""
    match = re.fullmatch(
        r"(?P<before>each (?:other player|player|opponent) (?:may )?"
        r"(?P<verb>discards?|draws?|sacrifices?) (?P<n>a|an|\d+) [^.]+?)"
        r"(?:\.\s*|,? then )(?P<after>.+)", body, re.I,
    )
    if match is None:
        return None
    verb = base_verb(match['verb'])
    event = {'discard': 'DISCARD_CARD', 'draw': 'DRAW', 'sacrifice': 'SACRIFICE'}[verb]
    count = 1 if match['n'] in ('a', 'an') else int(match['n'])
    after = match['after']
    qualifier = re.search(
        r"(?P<set>each (?:other player|player|opponent)) who "
        r"(?P<condition>"
        r"(?:discarded|drew|sacrificed) (?:(?:a|an|\d+) )?(?:nonland |creature |noncreature )?cards? this way|"
        r"didn't discard (?:(?:a|an|\d+) )?(?:nonland |creature |noncreature )?cards? this way|"
        r"can't|cannot|doesn't|didn't|does|did)"
        r"(?=,| (?:draws?|loses?|gains?|discards?|may|creates?)\b|$)", after, re.I,
    )
    if qualifier is None:
        return None
    condition = qualifier['condition']
    past = {'discard': 'discarded', 'draw': 'drew', 'sacrifice': 'sacrificed'}[verb]
    if 'this way' in condition and not (condition.startswith(past + ' ') or (verb == 'discard' and condition.startswith("didn't discard "))):
        return None
    leading = parse_effect_body(match['before'], reading=reading)
    rewritten = after[:qualifier.start()] + qualifier['set'] + after[qualifier.end():]
    trailing = player_scope_specs(rewritten, reading=reading) or parse_effect_body(rewritten, reading=reading)
    if not leading or not trailing:
        return None
    # Only a single shared player loop is the payoff; unsupported instructions
    # and separately announced targets cannot be smuggled into this scope.
    if len(trailing) != 1 or trailing[0].type != 'for_each':
        return None
    params = trailing[0].params
    if params.get('over', {}).get('players') != PLAYER_SETS[qualifier['set']]:
        return None
    if 'this way' in condition:
        printed_count = re.search(r'\b(a|an|\d+)\b', condition)
        count = int(printed_count[1]) if printed_count and printed_count[1].isdigit() else 1
    result = {'event': event, 'start': '$action_start', 'count': count,
              'negated': condition in ("can't", 'cannot', "doesn't", "didn't") or condition.startswith("didn't ")}
    typed = re.search(r'\b(nonland|creature|noncreature) card', condition)
    if typed:
        if verb != 'discard':
            return None
        result['card_type'] = typed[1]
    payoff = EffectSpec('for_each', {**params, 'over': {**params['over'], 'action_result': result}})
    return [EffectSpec('bind', {'name': 'action_start', 'amount': {'kind': 'event_cursor'},
                               'effects': [e.to_dict() for e in leading] + [payoff.to_dict()]})]


def player_scope_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """See `PLAYER_SCOPE_SUBJECT_RE`; ``None`` unless every effect of the "target
    player" reading targets exactly that one player and nothing else."""
    qualified = re.fullmatch(
        r"(?P<who>each (?:other player|player|opponent) who .+?) "
        r"(?P<rest>(?:draws?|discards?|loses?|gains?|mills?|sacrifices?|creates?|may) .+)", body.strip(), re.I,
    )
    if qualified is not None:
        over = qualified_player_set(qualified['who'])
        if over is None:
            return None
        inner = player_scope_specs('each player ' + qualified['rest'], reading=reading)
        if not inner or len(inner) != 1 or inner[0].type != 'for_each':
            return None
        return [EffectSpec('for_each', {**inner[0].params, 'over': over})]
    m = PLAYER_SCOPE_SUBJECT_RE.match(body.strip())
    if m is None:
        return None
    if m.group("who").lower() == "target player":
        return None  # the singular operation itself must exist; do not re-enter this scope adapter
    if m.group("who").lower() == "that player" and (
        reading.previous_subject or reading.attached_subject or any(r.kind == PLAYER for r in reading.referents)
    ):
        return None  # an earlier pick/host supplies the player; retain its contextual reading
    inner = parse_effect_body(
        f"target player {m.group('rest')}", reading=reading.unattached(),
    )
    if not inner:
        return None
    for spec in inner:
        named = [spec.params[k] for k in TARGET_PARAM_KEYS if spec.params.get(k) is not None]
        if named != ["player"] or spec.type in ("for_each", "bind", "if_else", "seq"):
            return None
    who = m.group("who").lower()
    if who == "that player":
        return [EffectSpec("trigger_subject_referent", {
            "referent": "trigger_player",
            "event_player_events": ["SPELL_CAST", "DAMAGE", "BECOMES_TARGET", *DEFENDING_PLAYER_COMBAT_EVENTS,
                                    "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER"],
            "effects": [spec.to_dict() for spec in inner],
        })]
    if who == "target opponent":
        return [
            EffectSpec(spec.type, {**spec.params, "target_kind": "opponent"}, condition=spec.condition)
            for spec in inner
        ]
    return [EffectSpec("for_each", {
        "over": quantified_set(who, reading),
        "effects": [spec.to_dict() for spec in inner],
    })]


#: PAR-112: the object-scope sibling of the player-subject slot above — a *leading*
#: "for each `<count phrase>`, `<body>`" whose body names the iterated object as "it"
#: ("for each token you control that entered this turn, create a token that's a copy of
#: it" — Ocelot Pride, Chief Magistrate of Mercadia, Saheeli the Gifted). RULE 101.4:
#: one pass per object, each a separate instruction. The body is parsed with the
#: pronoun reading on, and only effects that name their object through a ``referent``
#: are accepted — each is re-pointed at `GameContext.iteration_item`. Anything else (a
#: body that targets, or a pronoun some other effect family reads) fails closed.
_LEADING_FOR_EACH_OBJECT_RE = re.compile(
    r"^for each (?P<group>[a-z0-9+/ '~-]{3,80}?), (?P<rest>.+)$", re.IGNORECASE
)
#: The ``referent`` values that are the pronoun "it" — re-pointed at the loop item.
_ITERATION_REFERENTS = frozenset({"previous"})
#: The zones a leading "for each <objects>" may iterate: the battlefield, and exile (cards a prior clause exiled).
_ITERATION_ZONES = frozenset({"battlefield", "exile"})


#: RULE 705 (PAR-151): "for each flip you win, `<effect>`" — the leading spelling of the suffix
#: "`<effect>` for each flip you won": the effect's one printed magnitude is bound to the
#: ``coin_flips`` amount (`count_amount` reads the same phrase), so it fails closed on any body
#: without exactly one scalable count.
_LEADING_FOR_EACH_FLIP_RE = re.compile(
    r"^for each (?P<what>flip you (?:win|lose|won|lost)|(?:even|odd|different) result),\s*(?P<rest>.+)$", re.IGNORECASE
)


def leading_for_each_flip_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    m = _LEADING_FOR_EACH_FLIP_RE.match(body.strip())
    if m is None:
        return None
    return for_each_amount_specs(
        m, m.group("what").lower(), reading=reading.unattached(),
    )


def multi_copy_tail(specs: list[EffectSpec], after: str) -> Optional[list[EffectSpec]]:
    tail = parse_effect_body(after, reading=ClauseReading(
        previous_subject=True, referents=(CREATED_GROUP_REFERENT, TARGET_REFERENT),
    ))
    if tail is None:
        return None
    for spec in tail:
        if spec.type == "create_delayed_trigger":
            spec.params["capture"] = "created_objects"
        elif spec.params.get("previous_subject"):
            spec.params["referent"] = "created"
    return specs + tail


def leading_for_each_object_specs(body: str, *, reading: ClauseReading = STANDALONE) -> "Optional[list[EffectSpec]]":
    """See `_LEADING_FOR_EACH_OBJECT_RE`."""
    m = _LEADING_FOR_EACH_OBJECT_RE.match(body.strip())
    if m is None:
        return None
    amount = count_amount(m.group("group"), reading=reading)
    if amount is not None and not re.search(
        r"\b(?:it|its|that|those|them|they|their)\b", m.group("rest")
    ):
        # Member-relative bodies ("its controller draws") must iterate;
        # scaling one previous target would give every result to one player.
        bound = bound_for_each_amount(m, amount, reading=reading)
        if bound is not None and not announces_real_target(bound):
            return bound
    over: dict[str, Any]
    announcement: list[EffectSpec] = []
    target_controller = re.fullmatch(r"(?P<noun>.+) target (?P<who>player|opponent) controls", m.group("group"))
    if target_controller:
        selector = object_set(target_controller.group("noun"), reading)
        if selector is None:
            return None
        over = {"selector": {**selector, "of": "context", "controller_ref": "previous_player"}}
        announcement = [EffectSpec("choose_targets", {"kinds": [target_controller.group("who")]})]
    elif m.group("group") == "of them":
        # PAR-119: "whenever 1 or more tokens … enter, for each of them, …" (Kambal) — the
        # members of the firing batch that matched its head (``matching_ids``); the
        # segmenter keeps it off any head that isn't a batch.
        over = {"batch_members": True}
    else:
        scope = quantified_set("each " + m.group("group"), reading)
        selector = parse_count_phrase(m.group("group"))
        if scope is not None:
            over = scope
        # PAR-153: a card zone too — "for each creature card you own in exile with a memory counter on it,
        # create a … token that's a copy of it" (Altaïr); `ForEachEffect` reads the zone's cards.
        elif (
            selector is None or selector.get("zone") not in _ITERATION_ZONES or "terms" in selector
            or "distinct" in selector or "aggregate" in selector
        ):
            return None
        else:
            over = {"selector": selector}
    rest = m.group("rest").strip()
    # A body independent of the member still executes once per member. Preserve
    # the meaning of "you", and never replace a separately announced target.
    independent = parse_effect_body(rest, reading=reading)
    if independent and not any(
        names_a_target(spec) or spec.type in ("coin_flip", "roll_die") for spec in independent
    ) and not re.search(
        r"\b(?:it|its|that|those|them|they|their)\b", rest
    ):
        return announcement + [EffectSpec("for_each", {"over": over, "effects": [e.to_dict() for e in independent]})]
    inner_reading = ClauseReading(previous_subject=True, referents=(Referent(PLAYER),)) if "players" in over else ClauseReading(previous_subject=True)
    inner = parse_effect_body(rest, reading=inner_reading)
    if inner and any(spec.params.get("referent") not in _ITERATION_REFERENTS for spec in inner):
        inner = object_phrase_specs(rest, inner_reading, match_clause) or inner
    if not inner:
        return None
    effects = []
    for spec in inner:
        if (spec.type == "trigger_subject_referent"
                and spec.params.get("referent") in ("previous_subject", "previous_player")):
            effects.append({"type": spec.type, "params": {**spec.params, "referent": "iteration"}})
            continue
        if spec.params.get("referent") not in _ITERATION_REFERENTS or names_a_target(spec):
            return None
        entry: dict[str, Any] = {
            "type": spec.type, "params": {**spec.params, "referent": "iteration"},
        }
        if spec.condition is not None:
            entry["condition"] = dict(spec.condition)
        effects.append(entry)
    return announcement + [EffectSpec("for_each", {"over": over, "effects": effects})]


#: PAR-284 / RULE 301.5, 303.4, 608.2: "~ deals 2 damage to each creature for each Aura attached to that creature" (Baki's
#: Curse) -- the per-object amount is read against each member the sentence iterates, not against one referent, so every
#: member takes its own total. The set is the plain object set ("creature", "creature you control", ...) and the counted
#: attachments are the objects whose host is that member (`attached_to_reference`).
_PER_MEMBER_ATTACHMENT_RE = re.compile(
    r"^(?P<source>~) deals (?P<n>\d+) damage to each (?P<set>(?P<noun>creature|planeswalker|permanent)(?: (?:you|an opponent) controls?)?) "
    r"for each (?P<what>[a-z -]+?) attached to that (?P=noun)$"
)
#: The member the iteration binds, as the effect clause names it.
_PER_MEMBER_CLAUSE = "~ deals x damage to that {noun}"


def per_member_attachment_specs(body: str, *, reading: ClauseReading = STANDALONE) -> "Optional[list[EffectSpec]]":
    """See `_PER_MEMBER_ATTACHMENT_RE`; the ``for_each`` over the set whose body measures the attachments of the member
    (``reference: iteration``, `effect_amounts` via `effect_conditions.subject_of`)."""
    m = _PER_MEMBER_ATTACHMENT_RE.match(body.strip().rstrip("."))
    if m is None:
        return None
    over = quantified_set("each " + m.group("set"), reading)
    counted = parse_count_phrase(f"{m.group('what')} attached to it")
    if over is None or not isinstance(counted, dict) or not (counted.get("filter") or {}).get("attached_to_reference"):
        return None
    amount = {"kind": "count_selector", "selector": counted, "reference": "iteration", "multiply": int(m.group("n"))}
    bound = bind_x_specs(
        _PER_MEMBER_CLAUSE.format(noun=m.group("noun")), amount, reading=ClauseReading(previous_subject=True),
    )
    if bound is None or len(bound) != 1:
        return None

    def re_aim(node: Any) -> Any:
        """The member the clause names is the loop item: ``previous_subject`` referents become ``iteration``."""
        if isinstance(node, dict):
            return {k: ("iteration" if k == "referent" and v == "previous_subject" else re_aim(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [re_aim(v) for v in node]
        return node

    return [EffectSpec("for_each", {"over": over, "effects": [re_aim(bound[0].to_dict())]})]


def bind_x(effects: list[EffectSpec], amount: dict[str, Any]) -> "Optional[list[EffectSpec]]":
    """Bind the single X-holding param of a one-effect body to ``amount``
    (the `where_x_specs` idiom, for a caller that already has the amount).
    ``None`` unless exactly one effect carries an X — the measured number
    must have exactly one unambiguous place to go."""
    if len(effects) != 1:
        return None
    wrapped = effects[0].params.get("effects") if effects[0].type == "trigger_subject_referent" else None
    if wrapped and len(wrapped) == 1 and not effects[0].params.get("acting"):
        # "put that many +1/+1 counters on **it**": the X sits in the firing-object wrapper's one body.
        bound = bind_x([EffectSpec(wrapped[0]["type"], wrapped[0].get("params") or {})], amount)
        if bound is None:
            return None
        return [EffectSpec(
            "trigger_subject_referent", {**effects[0].params, "effects": [bound[0].to_dict()]},
            condition=effects[0].condition,
        )]
    params = dict(effects[0].params)
    holders = [k for k in _X_PARAM_KEYS if params.get(k) == "x"]
    if not holders or any(v == "-x" for v in params.values()):
        return None
    for key in holders:
        params[key] = "$n"
    return [EffectSpec("bind", {
        "name": "n",
        "amount": amount,
        "effects": [{"type": effects[0].type, "params": params}],
    }, condition=effects[0].condition)]


# Late-bound entry points other modules of this package call before this one is defined (see `late`).
register(bind_x_specs=bind_x_specs)


#: "that many" / "that much" in one step of a body.
_THAT_MANY_STEP_RE = re.compile(r"\bthat (?:many|much)\b", re.IGNORECASE)

#: A boundary between ordered steps of one body: a sentence end, or ", then".
_THAT_MANY_STEP_SPLIT_RE = re.compile(r"\.\s+|,\s*then\s+", re.IGNORECASE)


_DISCARD_THAT_MANY_RE = re.compile(r"(?:you )?discard that many cards?", re.IGNORECASE)


def bind_each_that_many_step(
    body: str, amount: "dict[str, Any]", reading: "ClauseReading"
) -> "Optional[list[EffectSpec]]":
    """``body`` read step by step when more than one step says "that many / that much": each step is parsed with a
    literal X bound to the head's ``amount`` (so every step counts the same event), a step naming no amount is parsed
    as it stands; ``None`` when any step is unclaimed or a counting step does not carry exactly one X."""
    effects: "list[EffectSpec]" = []
    for step in _THAT_MANY_STEP_SPLIT_RE.split(body.strip().rstrip(".")):
        counts = _THAT_MANY_STEP_RE.search(step) is not None
        parsed = parse_effect_body(_THAT_MANY_STEP_RE.sub("x", step), reading=reading)
        if parsed is None and counts and _DISCARD_THAT_MANY_RE.fullmatch(step.strip()):
            # Only a "discard that many cards" step is read this way; a bare "discard X cards" stays unclaimed
            # elsewhere (its X is the spell's, and "cards equal to its power" would misbind).
            parsed = [EffectSpec("discard", {"count": "x"})]
        bound = (bind_x(parsed, amount) if counts else parsed) if parsed else None
        if not bound:
            return None
        effects.extend(bound)
    return effects
