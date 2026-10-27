"""PAR-167: the casting window after an exile clause -- "Exile the top N cards of your library. Until end of turn,
you may cast spells from among them [without paying their mana costs]." (Narset, Enlightened Master; Dream
Pillager-, Eager Flameguide- and Hostage Taker-shaped bodies).

The pair is parsed as one clause so the pronoun ("that card", "them", "the exiled cards") can only ever name what the
first sentence exiled; the first sentence is handed back to the caller's ``match_clause`` (any exile clause the
catalogue already reads, restricted to the exiling effect types) and only the second sentence is parsed here, along
its independent axes:

* **pool** -- one card ("that card", "it") or the whole batch ("them", "the exiled cards"), narrowed to "`<type>`
  spells" / "a `<type>` spell [with mana value N or less] from among them";
* **verb** -- cast (spells only) or play (lands too);
* **cost** -- normal, "without paying its mana cost" (RULE 118.9), or the any-colour / any-type mana rider (RULE 605.1a);
* **permission** -- no window word is a one-resolution offer (RULE 608.2g); "this turn" / "until end of turn", "until
  the end of your next turn" and "for as long as it remains exiled" are windows.

Pure data in, `EffectSpec`s out (no ``game/`` imports: the security boundary).
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from ..spec import EffectSpec
from .characteristic_phrase import parse_object_phrase

#: First-sentence effect types that really exile cards this resolution (`GameContext.exiled_objects`).
_EXILING_TYPES = frozenset({"exile_top_of_library", "exile"})

_WINDOW = (
    r"this turn|until (?:the )?end of turn|until the end of your next turn|"
    r"for as long as (?:that card|they|it) remain(?:s)? exiled"
)
_PLURAL_POOL = r"them|those cards|the exiled cards|those exiled cards|cards exiled this way|the cards exiled this way"
#: PAR-214: "the exiled card" names the one card of a single-card exile as plainly as "that card" does.
_SINGULAR_POOL = r"that card|it|the exiled card|that exiled card"
#: "`<type>` spells" words -> the `combat.matches_object_filter` fragment they mean.
_TYPE_FILTERS: dict[str, dict] = {
    "creature": {"card_type": "creature"},
    "noncreature": {"without_card_type": "creature"},
    "artifact": {"card_type": "artifact"},
    "instant": {"card_type": "instant"},
    "sorcery": {"card_type": "sorcery"},
    "instant or sorcery": {"card_type_any": ["instant", "sorcery"]},
    "instant and sorcery": {"card_type_any": ["instant", "sorcery"]},
    "instant and/or sorcery": {"card_type_any": ["instant", "sorcery"]},
    "permanent": {"card_type_any": ["artifact", "battle", "creature", "enchantment", "planeswalker"]},
}
_TYPE_WORD = "|".join(sorted(map(re.escape, _TYPE_FILTERS), key=len, reverse=True))
_WILD_TAIL = (
    r"(?P<wild>,? and (?:you may spend mana as though it were mana of any (?P<wild_what>color|type) to cast "
    r"(?:that|those) spells?|mana of any (?P<wild_what2>color|type) can be spent to cast (?:that|those) spells?))"
)

_CAST_PAIR_RE = re.compile(
    r"(?P<exile>(?:exile|mill|target (?:player|opponent) mills|each opponent mills) [^.]+)\.\s+"
    # PAR-214: "If it's a Goblin or an artifact card, you may play it this turn." -- for a one-card pool the condition
    # on the card is the pool's filter (nothing else is in the pool to be told apart from it).
    r"(?:if (?:it(?:'s| is)|that card is) (?:an? )?(?P<cond>[^,.]+?)(?: card)?, )?"
    rf"(?:(?P<pre>{_WINDOW}), )?(?:you may )?(?P<verb>cast|play) "
    r"(?:"
    rf"(?P<singular>{_SINGULAR_POOL})"
    rf"|(?P<plural>{_PLURAL_POOL})"
    r"|(?:(?P<quant>an?|any number of) )?(?:(?P<type>" + _TYPE_WORD + r") )?(?P<spell>spells?)"
    r"(?: with mana value (?P<cap>\d+|x) or less)? "
    rf"from among (?:{_PLURAL_POOL})"
    r")"
    rf"(?P<post> (?:{_WINDOW}))?"
    r"(?P<free> without paying (?:its|their) mana costs?)?"
    rf"(?:{_WILD_TAIL})?\.?",
    re.IGNORECASE,
)


def parse_exile_cast_window(
    text: str, match_clause: Callable[..., Optional[list[EffectSpec]]],
) -> Optional[list[EffectSpec]]:
    """The exile clause plus its casting window, or ``None`` when any axis is outside the vocabulary."""
    m = _CAST_PAIR_RE.fullmatch(text.strip())
    if m is None:
        return None
    exile = match_clause(m.group("exile"))
    if not exile or len(exile) != 1 or exile[0].type not in _EXILING_TYPES | {"mill"} or exile[0].params.get("face_down"):
        return None
    is_mill = exile[0].type == "mill"
    # The PAR-163 window row already owns "[until the end of your next turn,] you may play/cast that card [...]" after
    # an exile clause; keep its spec rather than restating it here.
    earlier = match_clause(text.strip().split(".", 1)[1].strip().rstrip("."))
    # PAR-169: only for an exile that leaves its cards as the previous clause's referent (`ExileEffect`); a library
    # exile (`exile_top_of_library`) records exact zone visits instead, which `cast_window_exiled_pool` reads.
    if (not is_mill and earlier and len(earlier) == 1 and earlier[0].type == "grant_play_window_previous_exiled"
            and exile[0].type != "exile_top_of_library"):
        return [exile[0], earlier[0]]
    window = (m.group("pre") or "").strip(), (m.group("post") or "").strip()
    if window[0] and window[1]:
        return None  # one window phrase only
    word = window[0] or window[1]
    verb = m.group("verb").lower()
    free = bool(m.group("free"))
    wild = m.group("wild_what") or m.group("wild_what2")
    if free and wild:
        return None
    params: dict = {}
    if verb == "cast":
        params["only_spells"] = True
    # The pool: a lone card is only ever the answer to a one-card exile.
    if m.group("singular") and (is_mill or not _exiles_one_card(exile[0])):
        return None
    card_filter: dict = {}
    any_number = False
    if m.group("cond"):
        # Only a single exiled card can be "it"; a pool-wide condition is not a filter on any card among many.
        if not m.group("singular") or is_mill or not _exiles_one_card(exile[0]):
            return None
        condition = parse_object_phrase(m.group("cond").lower() + " card")
        if condition is None or condition[1] is not None:
            return None
        card_filter.update(condition[0])
    if m.group("type"):
        card_filter.update(_TYPE_FILTERS[m.group("type").lower()])
    if m.group("cap"):
        card_filter["max_mana_value"] = "x" if m.group("cap").lower() == "x" else int(m.group("cap"))
    quant = (m.group("quant") or "").lower()
    if m.group("spell"):
        # "a spell" is one cast, a bare "spells" / "any number of spells" is the whole selection.
        if (m.group("spell").lower() == "spell") != (quant in ("a", "an")):
            return None
    if quant == "any number of" or (m.group("spell") or "").lower() == "spells":
        any_number = True
    one_of = quant in ("a", "an")
    if not word:
        # RULE 608.2g: no window word -- the casting is offered during this resolution (spells only: a land is played,
        # not cast, and "play" here would need the land-drop machinery).
        if verb != "cast":
            return None
        params["resolution_local"] = True
        if any_number or (m.group("plural") and not one_of):
            params["any_number"] = True
    else:
        if one_of:
            return None  # "a spell" from a window cannot be limited to one cast
        lowered = word.lower()
        if lowered in ("this turn", "until end of turn", "until the end of turn"):
            params["same_turn_only"] = True
        elif lowered.startswith("for as long as"):
            params["standing"] = True
        # "until the end of your next turn" is the effect's default window.
    if is_mill:
        if word or verb != "cast":
            return None  # standing mill windows need a per-pool cast-count permission
        params["pool_zone"] = "graveyard"
    if card_filter:
        params["card_filter"] = card_filter
    if free:
        params["free"] = True
    if wild:
        params["mana_wildcard"] = wild.lower()
    return [exile[0], EffectSpec("cast_window_exiled_pool", params)]


def _exiles_one_card(spec: EffectSpec) -> bool:
    """Whether the exile clause moves exactly one card ("that card" would name it)."""
    if spec.type == "exile_top_of_library":
        return (
            spec.params.get("count") == 1 and spec.params.get("player_selector") in ("controller", "target")
            and spec.params.get("position", "top") == "top"
        )
    params = spec.params
    return not params.get("selector") and params.get("count", 1) == 1 and not params.get("any_number")


# --- the free cast from your hand / graveyard, one resolution --------------------------------------------------

_COLOR_LETTERS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
#: "`<type>` spell(s)/card(s)" words -> the `card_query` fragment they mean.
_CARD_TYPE_CRITERIA: dict[str, dict] = {
    "sorcery": {"type": "sorcery"},
    "instant": {"type": "instant"},
    "instant or sorcery": {"type": ["instant", "sorcery"]},
    "instant and/or sorcery": {"type": ["instant", "sorcery"]},
    "artifact": {"type": "artifact"},
    "creature": {"type": "creature"},
    "noncreature": {"without_type": "creature"},
    "permanent": {"type": ["artifact", "battle", "creature", "enchantment", "land", "planeswalker"]},
}
_CARD_TYPE_WORD = "|".join(sorted(map(re.escape, _CARD_TYPE_CRITERIA), key=len, reverse=True))
#: A mana-value cap: "N or less", "X or less" (with a trailing "where x is …"), "less than or equal to <amount>" and
#: the exact "equal to <amount>"; the amount is "that damage" or any quantity `count_phrase.parse_amount_phrase` reads.
_AMOUNT_PHRASE = r"that damage|(?:the|twice|\d+ plus) [a-z0-9+/'{} ,~-]+?"
_MV_CAP = (
    r"(?:(?P<lit>\d+) or less|(?P<xcap>x) or less|less than or equal to (?P<le>" + _AMOUNT_PHRASE + r")"
    r"|equal to (?P<eq>" + _AMOUNT_PHRASE + r"))"
)
#: The same grammar with its groups anonymous: it appears twice in the clause pattern (before and after the zone) and
#: is re-read with names by `parse_free_cast_zone`.
_MV_CAP_ANON = re.sub(r"\(\?P<\w+>", "(?:", _MV_CAP)
_MV_CAP_RE = re.compile(_MV_CAP, re.IGNORECASE)
_FREE_CAST_ZONE_RE = re.compile(
    r"(?:you may )?cast (?:(?P<quant>an?|any number of) )?(?:(?P<color>white|blue|black|red|green) )?"
    rf"(?:(?P<type>{_CARD_TYPE_WORD}) )?(?P<noun>spells?|cards?)"
    rf"(?: with mana value (?P<cap_a>{_MV_CAP_ANON}))? from your (?P<zone>hand|graveyard)"
    rf"(?: with mana value (?P<cap_b>{_MV_CAP_ANON}))? without paying (?:its|their) mana costs?"
    r"(?:, where x is (?P<xamt>[^.]+))?\.?",
    re.IGNORECASE,
)
_TRIGGER_AMOUNT = {"kind": "trigger_event", "field": "amount"}


def parse_free_cast_zone(
    text: str, parse_amount: Callable[[str], object],
) -> Optional[list[EffectSpec]]:
    """"[You may] cast `<a / any number of>` `<type>` spell(s) from your hand/graveyard [with mana value `<cap>`] without
    paying its mana cost" as one resolution's `free_cast_from_hand` offer (RULE 608.2g, 118.9)."""
    m = _FREE_CAST_ZONE_RE.fullmatch(text.strip())
    if m is None:
        return None
    quant = (m.group("quant") or "").lower()
    noun = m.group("noun").lower()
    if (noun.endswith("s")) == (quant in ("a", "an")):
        return None  # "a spell" / "any number of spells": the noun's number must agree with the quantity
    if m.group("quant") is None:
        return None  # a bare plural does not specify how many resolution-local casts to offer
    cap_a, cap_b = m.group("cap_a"), m.group("cap_b")
    if cap_a and cap_b:
        return None
    zone = m.group("zone").lower()
    params: dict = {"zones": [zone], "during_resolution": True}
    criteria: dict = {}
    if m.group("type"):
        criteria.update(_CARD_TYPE_CRITERIA[m.group("type").lower()])
    if m.group("color"):
        criteria["color"] = _COLOR_LETTERS[m.group("color").lower()]
    if m.group("noun").lower().startswith("card") and zone == "hand":
        return None  # a card in hand is cast as a spell; the "card" wording is the graveyard's
    if criteria:
        params["card_criteria"] = criteria
    if quant == "any number of":
        params["arm_all"] = True
    cap = cap_a or cap_b
    if cap:
        cm = _MV_CAP_RE.fullmatch(cap)
        if cm is None:
            return None
        if cm.group("lit"):
            params["max_mana_value"] = int(cm.group("lit"))
        elif cm.group("xcap"):
            amount = parse_amount(m.group("xamt") or "")
            if not amount:
                return None
            params["max_mana_value_amount"] = {"kind": "count_selector", "selector": amount}
        else:
            phrase = (cm.group("le") or cm.group("eq")).lower()
            if phrase == "that damage":
                params["max_mana_value_amount"] = dict(_TRIGGER_AMOUNT)
            else:
                amount = parse_amount(phrase)
                if not amount:
                    return None
                params["max_mana_value_amount"] = {"kind": "count_selector", "selector": amount}
            if cm.group("eq"):
                params["exact_mana_value"] = True
    if m.group("xamt") and not (cap and _MV_CAP_RE.fullmatch(cap).group("xcap")):
        return None
    return [EffectSpec("free_cast_from_hand", params)]


# --- "until end of turn, you may play lands and cast spells from your graveyard" ---------------------------------

#: The player-scoped turn window `graveyard_play_permission_this_turn` stamps (lands and spells both), and the
#: turn-long "would be put into your graveyard from anywhere, exile it instead" replacement that usually rides along.
_GRAVEYARD_PLAY_WINDOW_RE = re.compile(
    r"(?:(?P<pre>until end of turn), )?(?:you may )?play lands and cast spells from your graveyard"
    r"(?P<post> (?:until end of turn|this turn))?"
    r"(?:\.?\s*(?P<redirect>if a card would be put into your graveyard from anywhere this turn, "
    r"exile (?:that card|it) instead))?\.?",
    re.IGNORECASE,
)
_GRAVEYARD_REDIRECT_RE = re.compile(
    r"if a card would be put into your graveyard from anywhere this turn, exile (?:that card|it) instead\.?",
    re.IGNORECASE,
)


_GRAVEYARD_CAST_POOL_RE = re.compile(
    r"(?:(?P<pre>until end of turn), )?(?:you may )?cast "
    rf"(?:(?P<type>{_CARD_TYPE_WORD}|instant and sorcery) )?spells from (?P<scope>your|any) graveyard"
    r"(?P<post> (?:until end of turn|this turn))?"
    r"(?P<free> without paying their mana costs)?"
    r"(?:\.\s*if a spell cast this way would be put into a graveyard, (?P<rider>exile it instead))?\.?",
    re.IGNORECASE,
)


def parse_graveyard_play_window(text: str) -> Optional[list[EffectSpec]]:
    """The turn-long graveyard play permission (and its exile replacement) or the replacement alone."""
    stripped = text.strip()
    pool = _GRAVEYARD_CAST_POOL_RE.fullmatch(stripped)
    if pool:
        if bool(pool.group("pre")) == bool(pool.group("post")):
            return None
        params = {"any_graveyard": pool.group("scope").lower() == "any"}
        kind = pool.group("type")
        if kind:
            params["spell_criteria"] = dict(_CARD_TYPE_CRITERIA[
                "instant or sorcery" if kind.lower() == "instant and sorcery" else kind.lower()
            ])
        if pool.group("free"):
            return None  # free dynamic pools need a cost override, not only a zone permission
        if pool.group("rider"):
            params["exile_if_would_be_put_into_graveyard"] = True
        return [EffectSpec("graveyard_cast_pool_this_turn", params)]
    if _GRAVEYARD_REDIRECT_RE.fullmatch(stripped):
        return [EffectSpec("graveyard_redirect_to_exile_this_turn", {})]
    m = _GRAVEYARD_PLAY_WINDOW_RE.fullmatch(stripped)
    if m is None or bool(m.group("pre")) == bool(m.group("post")):
        return None  # exactly one window phrase: without one the permission is a standing static, not this turn's
    specs = [EffectSpec("graveyard_play_permission_this_turn", {})]
    if m.group("redirect"):
        specs.append(EffectSpec("graveyard_redirect_to_exile_this_turn", {}))
    return specs


# --- "exile cards from the top of your library until you exile a nonland card. You may cast that card ..." -------

_DIG_PREDICATES: dict[str, dict] = {
    "a nonland": {"without_type": "land"},
    "an instant or sorcery": {"type": ["instant", "sorcery"]},
    "a creature": {"type": "creature"},
    "an artifact": {"type": "artifact"},
}
_DIG_CAST_RE = re.compile(
    r"(?P<who>exile|target opponent exiles) cards from the top of (?P<lib>your|their) library until "
    r"(?:you|they) exile (?P<pred>" + "|".join(map(re.escape, _DIG_PREDICATES)) + r") card\.\s+"
    r"(?:(?P<window>until end of turn), )?(?:you may )?cast (?:that card|the exiled card) "
    r"without paying its mana cost\.?",
    re.IGNORECASE,
)


def parse_dig_cast_free(text: str) -> Optional[list[EffectSpec]]:
    """The exile-until dig whose hit its digger / the controller may cast for free: during this resolution
    (RULE 608.2g) or, with "until end of turn", through the free cast window; an uncast hit stays exiled."""
    m = _DIG_CAST_RE.fullmatch(text.strip())
    if m is None:
        return None
    opponent = m.group("who").lower().startswith("target")
    if opponent != (m.group("lib").lower() == "their"):
        return None  # "exile ... your library" / "target opponent exiles ... their library" only
    params: dict = {
        "criteria": dict(_DIG_PREDICATES[m.group("pred").lower()]),
        "hit_destination": "cast_free_window" if m.group("window") else "cast_during_resolution",
        "rest_destination": "exile", "uncast_hit": "stay",
    }
    if opponent:
        params.update(digger="facing", caster="controller", target_kind="opponent")
    elif m.group("window"):
        return None  # a window over one's own dig is the pool-window grammar's, with its own pool
    return [EffectSpec("dig_until", params)]


# --- "Exile target <card> from a graveyard. Copy it. You may cast the copy [without paying its mana cost]." -------

_COPY_CAST_RE = re.compile(
    r"(?P<exile>exile [^.]+?)(?: and copy (?:it|that card)|\.\s+copy (?:it|that card))(?:\.\s+|, then )"
    r"(?:you may )?cast the copy(?P<free> without paying its mana cost)?\.?",
    re.IGNORECASE,
)


def parse_exile_copy_cast(
    text: str, exile_clause: Callable[[str], Optional[list[EffectSpec]]],
) -> Optional[list[EffectSpec]]:
    """An exile of one targeted graveyard card, then a copy of it cast during this resolution (RULE 707.12, 608.2g):
    `copy_imprinted_card`'s ``from_previous`` mode, free or at normal cost."""
    m = _COPY_CAST_RE.fullmatch(text.strip())
    if m is None:
        return None
    exile = exile_clause(m.group("exile"))
    if not exile or len(exile) != 1 or exile[0].type != "exile" or not exile[0].params.get("target_kind"):
        return None
    if exile[0].params.get("selector") or exile[0].params.get("count", 1) != 1:
        return None  # one targeted card: "copy it" names exactly that card
    params: dict = {"from_previous": True}
    if not m.group("free"):
        params["free"] = False
    return [exile[0], EffectSpec("copy_imprinted_card", params)]
