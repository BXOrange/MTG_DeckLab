"""PAR-203 (RULE 608.2d): "Choose a creature type / a color / a card name. `<clauses naming the choice>`".

The choice is an instruction of the resolving spell or ability, made as it resolves, and the clauses after it
say "of the chosen type", "that color", "the chosen name". The parser cannot know the answer, so the body is
read in two halves:

* the lead-in becomes one ``choose_for_source`` effect (the engine opens the choice and stamps the answer on
  the source), and
* the tail is read as an ordinary effect body *with the choice swapped for a stand-in word* (a creature
  type / colour the tail cannot otherwise mention), then every value equal to the stand-in is replaced by the
  ``$chosen_*`` placeholder `composition._build` resolves against the stamped answer.

Reusing the whole existing clause grammar for the tail means every shape that already parses for a literal
"Elf"/"green" parses here, and nothing here is derived from card text at run time: the stand-in is chosen
from a closed list and verified absent from the tail, the placeholders are fixed strings, and a tail that
mentions the choice in any way the rewrite does not recognise is refused (fail closed).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

from ..spec import CHOSEN_COLOR_SENTINEL, CHOSEN_NAME_SENTINEL, CHOSEN_TYPE_SENTINEL, EffectSpec
from .dig import parse_criteria

#: The creature type the tail is read with. Any subtype the clause grammar knows would do; the tail is refused if
#: it names this one itself, so a value equal to it can only have come from the chosen-type phrase.
_TYPE_STAND_IN = "elf"
_TYPE_STAND_IN_RE = re.compile(r"\belf\b|\belves\b|\belf-")

#: RULE 105.1: the five colours, as (word, symbol). The stand-in is the first one the tail does not mention.
_COLOR_STAND_INS: tuple[tuple[str, str], ...] = (
    ("green", "G"), ("white", "W"), ("blue", "U"), ("black", "B"), ("red", "R"),
)

#: "a nonland card name" and its siblings: the `card_query` filter a legal answer must satisfy (RULE 201.3), checked by
#: `_resume_choose_for_source` against cards the game knows by name.
_QUALIFIER_FILTERS: dict[str, dict[str, Any]] = {
    "": {},
    "nonland": {"without_type": "land"},
    "creature": {"type": "creature"},
    "artifact": {"type": "artifact"},
    "noncreature, nonland": {"without_type": ["creature", "land"]},
    "nonartifact, nonland": {"without_type": ["artifact", "land"]},
}

#: MEC-134 (RULE 201.3): the card filter an "as ~ enters" naming choice carries for its printed qualifier. The ones the
#: resolution-time "choose a ... card name" already knows, plus "nonbasic land".
_ENTER_QUALIFIER_FILTERS: dict[str, dict[str, Any]] = {
    **_QUALIFIER_FILTERS,
    "nonbasic land": {"type": "land", "not_basic": True},
}
_ENTER_CARD_NAME = re.compile(
    r"as ~ enters, choose an? (?:(?P<qual>" + "|".join(re.escape(q) for q in _ENTER_QUALIFIER_FILTERS if q) + r") )?card name"
)
#: Sorcerous Spyglass / Anointed Peacekeeper: the looking step comes first, then "any card name" (no qualifier).
_ENTER_LOOK_THEN_NAME = re.compile(r"as ~ enters, look at an opponent's hand, then choose any card name")


def enter_card_name_specs(text: str) -> Optional[list[EffectSpec]]:
    """RULE 601.2b / 614.12: "As ~ enters, choose a [nonland] card name." -> the pre-entry naming choice
    (`choose_card_name_on_enter`, free text validated against the printed qualifier), flagged ``look_at_opponent_hand`` for the
    Spyglass wording. ``None`` for any other text (fail closed)."""
    text = text.strip().rstrip(".").strip().lower()
    if _ENTER_LOOK_THEN_NAME.fullmatch(text):
        return [EffectSpec("choose_card_name_on_enter", {"look_at_opponent_hand": True})]
    m = _ENTER_CARD_NAME.fullmatch(text)
    if m is None:
        return None
    card_filter = _ENTER_QUALIFIER_FILTERS[m.group("qual") or ""]
    return [EffectSpec("choose_card_name_on_enter", {"card_filter": dict(card_filter)} if card_filter else {})]


#: The card name a tail is read with when it only needs "<noun> named X" (`dig.parse_criteria`); verified absent from the
#: tail like the other stand-ins.
_NAME_STAND_IN = "zzname"
_NAME_NOUN = re.compile(r"\b(?P<art>an? |all )?(?P<noun>cards?)(?P<of> of them)? with (?:that|the chosen) name\b")
_NAME = r"(?:that|the chosen) name"

#: "Search target player's graveyard, hand, and library for `<N | any number of | all>` cards with that name and exile
#: them. Then that player shuffles[, then draws a card / creates a 2/2 black Zombie for each card exiled from their hand
#: this way]." -- Slaughter Games, Cranial Extraction, Lost Legacy, Unmoored Ego, Necromentia, ...
_SEARCH_EXILE = re.compile(
    r"search target (?P<who>opponent|player)'s graveyard, hand, and library for "
    rf"(?P<q>up to (?P<n>\d+)|any number of|all) cards? with {_NAME} and exile them\.\s*"
    r"(?:then )?that player shuffles"
    r"(?:, then (?P<follow>draws a card|creates a 2/2 black zombie creature token) "
    r"for each card exiled from their hand this way)?\.?"
)
#: Thought Hemorrhage: reveal the hand and hit for each copy, then the same search-and-exile.
_THOUGHT_HEMORRHAGE = re.compile(
    r"target player reveals their hand\. ~ deals (?P<d>\d+) damage to that player for each card with "
    r"the chosen name revealed this way\. search that player's graveyard, hand, and library for all cards with "
    r"that name and exile them\. then that player shuffles\.?"
)
_REVEAL_DISCARD_NAMED = re.compile(rf"target player reveals their hand and discards all cards with {_NAME}\.?")
_BRAIN_PRY = re.compile(
    rf"target player reveals their hand\. that player discards a card with {_NAME}\. if they can't, you draw a card\.?"
)

#: Demonic Consultation / Divining Witch: exile the top N, then dig for the named card; every other revealed card is exiled.
_DIG_EXILE_NAMED = re.compile(
    r"exile the top (?P<n>\d+) cards of your library, then reveal cards from the top of your library until you reveal "
    rf"a card with {_NAME}\. put that card into your hand and exile all other cards revealed this way\.?"
)
#: Wood Sage / Desperate Research: reveal the top N, every card with the name goes to the hand, the rest to a zone.
_REVEAL_TOP_NAMED = re.compile(
    r"reveal the top (?P<n>\d+) cards of your library and put all of them with "
    rf"{_NAME} into your hand\. (?:put the rest into your (?P<gy>graveyard)|(?P<ex>exile) the rest)\.?"
)

_FOLLOW_UPS: dict[str, dict[str, Any]] = {
    "draws a card": {"type": "draw", "params": {"count": "$n"}},
    "creates a 2/2 black zombie creature token": {"type": "create_token", "params": {
        "count": "$n", "power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Zombie"], "keywords": [],
        "token_name": "Zombie",
    }},
}


def _name_tail_effects(tail: str) -> Optional[list[dict[str, Any]]]:
    """The effects of the card-name tails that map onto a dedicated primitive (search-and-exile, hand discard), as spec
    dicts carrying the ``$chosen_name`` placeholder, or ``None`` when the tail is none of those shapes."""
    m = _SEARCH_EXILE.fullmatch(tail)
    if m is not None:
        params: dict[str, Any] = {
            "name": CHOSEN_NAME_SENTINEL, "target_kind": m.group("who"),
            "quantity": int(m.group("n")) if m.group("n") else "all",
        }
        if m.group("follow"):
            params["then_effects"] = [dict(_FOLLOW_UPS[m.group("follow")])]
        return [{"type": "exile_named_from_zones", "params": params}]
    m = _THOUGHT_HEMORRHAGE.fullmatch(tail)
    if m is not None:
        return [{"type": "exile_named_from_zones", "params": {
            "name": CHOSEN_NAME_SENTINEL, "target_kind": "player", "quantity": "all",
            "damage_per_hand_card": int(m.group("d")),
        }}]
    if _REVEAL_DISCARD_NAMED.fullmatch(tail):
        return [{"type": "reveal_hand_discard_all", "params": {
            "target_kind": "player", "card_filter": {"name": CHOSEN_NAME_SENTINEL},
        }}]
    m = _DIG_EXILE_NAMED.fullmatch(tail)
    if m is not None:
        return [{"type": "dig_until", "params": {
            "criteria": {"name": CHOSEN_NAME_SENTINEL}, "pre_exile": int(m.group("n")),
            "hit_destination": "hand", "rest_destination": "exile",
        }}]
    m = _REVEAL_TOP_NAMED.fullmatch(tail)
    if m is not None:
        return [{"type": "inspect_top_choose", "params": {
            "count": int(m.group("n")), "action": "library_to_hand", "max_picks": "all", "optional": False,
            "criteria": {"name": CHOSEN_NAME_SENTINEL},
            "rest_destination": "graveyard" if m.group("gy") else "exile",
        }}]
    if _BRAIN_PRY.fullmatch(tail):
        return [{"type": "reveal_hand_discard_all", "params": {
            "target_kind": "player", "card_filter": {"name": CHOSEN_NAME_SENTINEL}, "count": 1, "draw_if_none": True,
        }}]
    return None

_LEAD = re.compile(
    # An optional leading "if <condition>, " gates the choice together with everything after it (Aven Warcraft).
    r"(?:if (?P<cond>[^,.]+), )?choose (?:"
    r"(?P<type>a creature type(?: other than (?P<other>[a-z]+))?)"
    r"|(?P<color>a color)"
    r"|(?P<name>an? (?:(?P<qual>nonland|creature|artifact|noncreature, nonland|nonartifact, nonland) )?card name"
    r"(?P<notbasic> other than a basic land card name)?)"
    r")(?P<join>\.\s*|,\s*then\s+)(?P<tail>.+)",
    re.DOTALL,
)

#: "<noun> [you control] of the chosen type" / "<noun> [you control] that aren't of the chosen type".
_NOUN = r"(?P<noun>(?:creature cards?|creatures?|permanents?|cards?))(?P<ctl> you control| your opponents control)?"
_TYPE_OF = re.compile(rf"{_NOUN} of (?:the chosen|that) (?:creature )?type\b")
_TYPE_NOT_OF = re.compile(rf"{_NOUN} that aren't of (?:the chosen|that) (?:creature )?type\b")
_COLOR_OF = re.compile(rf"{_NOUN} of (?:the chosen|that) color\b")
_COLOR_PHRASES = re.compile(r"(?:the chosen|that) color\b")
#: Any wording of the choice that survived the rewrite: refuse rather than guess at it.
#: "creatures you control **also** gain protection ..." -- the "also" only says the grant adds to another one.
_ALSO = re.compile(r"\balso (gain|gains|have|has|get|gets)\b")
_LEFTOVER = re.compile(r"\b(?:the chosen|that) (?:creature )?(?:type|color|name)\b|\bchosen (?:type|color|name)\b")


def _replace_values(node: Any, matches: Callable[[str], bool], placeholder: str) -> Any:
    """``node`` with every string value that ``matches`` replaced by ``placeholder`` (dict keys are left alone)."""
    if isinstance(node, str):
        return placeholder if matches(node) else node
    if isinstance(node, dict):
        return {k: _replace_values(v, matches, placeholder) for k, v in node.items()}
    if isinstance(node, list):
        return [_replace_values(v, matches, placeholder) for v in node]
    return node


#: "Target player reveals their hand and discards all `<kind>` cards" (Persecute) read after the stand-in rewrite: ``<kind>``
#: is whatever `dig.parse_criteria` reads ("green", "elf creature"). The "that player" form (Crosis, a combat-damage trigger's
#: player) is deliberately not read: a suspended resolution resumes outside the firing event's window
#: (`resume_deferred_effects`), so the damaged player would be gone by the time the discard runs.
_REVEAL_DISCARD_ALL = re.compile(
    r"target player reveals their hand and discards all (?P<kind>[a-z' -]+? cards?)\.?"
)


def _reveal_discard_all_specs(rewritten: str) -> Optional[list[EffectSpec]]:
    m = _REVEAL_DISCARD_ALL.fullmatch(rewritten)
    if m is None:
        return None
    criteria = parse_criteria(m.group("kind"))
    if not criteria:
        return None  # an unreadable kind must not become "discards all cards"
    return [EffectSpec("reveal_hand_discard_all", {"card_filter": criteria, "target_kind": "player"})]


def _sequenced(*specs: EffectSpec) -> list[EffectSpec]:
    """The choice and what follows it as ONE ``seq`` node. A resolution that runs its effects with a plain loop (a paid
    "if you do" branch, `RulesEngine._apply_effect_specs`) would otherwise carry on past the open choice; a ``seq`` runs its
    body through `_apply_effects_partitioned`, which parks the tail until the answer is in (RULE 608.2)."""
    return [EffectSpec("seq", {"effects": [spec.to_dict() for spec in specs]})]


#: Spellings of "the thing the firing event names". A resolution that waits behind the choice resumes outside that event's
#: window (`RulesEngine.resume_deferred_effects`), so a tail reading it would act on nothing: refuse such a tail rather than
#: claim it (fail closed).
_EVENT_REFERENTS = (
    "trigger_event_key", "event_key", "trigger_subject", "__group_subject__", "damaged_player", "event_player",
    "attacked_player", "attacking_player", "trigger_player", "player_from_trigger_event",
)


#: Effects that open a trigger of their own: the referents inside are that new trigger's, not the resolving ability's.
_OWN_TRIGGER_EFFECTS = frozenset({"create_turn_trigger", "create_delayed_trigger", "grant_triggered_ability"})


def _reads_firing_event(node: Any) -> bool:
    if isinstance(node, list):
        return any(_reads_firing_event(item) for item in node)
    if not isinstance(node, dict):
        return False
    if node.get("type") in _OWN_TRIGGER_EFFECTS:
        return False
    if any(key in _EVENT_REFERENTS or node.get(key) in _EVENT_REFERENTS for key in node if isinstance(key, str)):
        return True
    return any(_reads_firing_event(value) for value in node.values())


def _stand_in_removed(specs: list[EffectSpec], matches: Callable[[str], bool], placeholder: str) -> Optional[list[dict]]:
    """The tail specs as dicts with the stand-in replaced, or ``None`` when no value carried the stand-in (the
    tail never actually read the choice, so the rewrite matched something it should not have)."""
    original = [spec.to_dict() for spec in specs]
    swapped = _replace_values(original, matches, placeholder)
    return swapped if swapped != original else None


#: RULE 205.1a / 613.4a: "<creatures> becomes that type until end of turn" -- the chosen creature type *replaces* the
#: creature's types (Mistform Dreamer's own reading, `type_change.set_subtypes_from_source`), unlike an "in addition to its
#: other types" grant. Subject -> (``target_kind``, group ``affects``).
_BECOMES_THAT_TYPE = re.compile(
    r"(?P<subject>target creature|each creature you control|creatures you control|each creature|all creatures)"
    r" becomes? (?:that|the chosen) type until end of turn"
)
_BECOMES_SUBJECTS: dict[str, tuple[Optional[str], Optional[str]]] = {
    "target creature": ("creature", None),
    "each creature you control": (None, "creatures_you_control"),
    "creatures you control": (None, "creatures_you_control"),
    "each creature": (None, "all_creatures"),
    "all creatures": (None, "all_creatures"),
}


def _becomes_that_type(tail: str) -> Optional[list[EffectSpec]]:
    m = _BECOMES_THAT_TYPE.fullmatch(tail.rstrip("."))
    if m is None:
        return None
    target_kind, affects = _BECOMES_SUBJECTS[m.group("subject")]
    type_params: dict[str, Any] = {"set_subtypes_from_source": True}
    if affects is not None:
        type_params["affects"] = affects
    params: dict[str, Any] = {
        "static": {"type": "type_change", "params": type_params},
        "duration": "end_of_turn", "target_kind": target_kind,
    }
    if affects is not None:
        params["lock_group"] = True  # RULE 611.2c: only the creatures on the battlefield as it resolves
    return [EffectSpec("grant_until", params)]


def named_choice_specs(
    body: str, parse: Callable[[str], Optional[list[EffectSpec]]],
) -> Optional[list[EffectSpec]]:
    """``choose <a creature type|a color|a card name>. <tail>`` → ``[choose_for_source, seq(tail)]``, else ``None``."""
    m = _LEAD.fullmatch(body.strip())
    if m is None:
        return None
    tail = _ALSO.sub(r"\1", m.group("tail").strip())
    params: dict[str, Any]
    if m.group("type"):
        becomes = _becomes_that_type(tail) if not m.group("cond") else None
        if becomes is not None:
            params = {"kind": "creature_type"}
            if m.group("other"):
                params["other_than"] = [m.group("other")]
            return _sequenced(EffectSpec("choose_for_source", params), *becomes)
        if _TYPE_STAND_IN_RE.search(tail):
            return None
        rewritten = _TYPE_NOT_OF.sub(lambda g: f"non-{_TYPE_STAND_IN} {g.group('noun')}{g.group('ctl') or ''}", tail)
        rewritten = _TYPE_OF.sub(lambda g: f"{_TYPE_STAND_IN} {g.group('noun')}{g.group('ctl') or ''}", rewritten)
        if rewritten == tail or _LEFTOVER.search(rewritten):
            return None
        params = {"kind": "creature_type"}
        if m.group("other"):
            params["other_than"] = [m.group("other")]
        matches: Callable[[str], bool] = lambda v: v.lower() == _TYPE_STAND_IN
        placeholder = CHOSEN_TYPE_SENTINEL
    elif m.group("color"):
        stand_in = next(
            ((word, symbol) for word, symbol in _COLOR_STAND_INS
             if not re.search(rf"\b{word}\b|\{{{symbol.lower()}\}}", tail)), None,
        )
        if stand_in is None:
            return None
        word, symbol = stand_in
        rewritten = _COLOR_OF.sub(lambda g: f"{word} {g.group('noun')}{g.group('ctl') or ''}", tail)
        rewritten = _COLOR_PHRASES.sub(word, rewritten)
        if rewritten == tail or _LEFTOVER.search(rewritten):
            return None
        params = {"kind": "color"}
        matches = lambda v, symbol=symbol, word=word: v in (symbol, word, word.capitalize())
        placeholder = CHOSEN_COLOR_SENTINEL
    else:
        # RULE 201.3: a card name. The tail is either one of the shapes with a dedicated primitive, or read like the
        # others with "cards named <stand-in>" for "cards with that name".
        if m.group("cond"):
            return None
        params = {"kind": "card_name"}
        card_filter = dict(_QUALIFIER_FILTERS[m.group("qual") or ""])
        if m.group("notbasic"):
            card_filter["not_basic"] = True
        if card_filter:
            params["card_filter"] = card_filter
        direct = _name_tail_effects(tail)
        if direct is not None:
            return _sequenced(EffectSpec("choose_for_source", params), EffectSpec("seq", {"effects": direct}))
        if _NAME_STAND_IN in tail:
            return None
        rewritten = _NAME_NOUN.sub(
            lambda g: f"{g.group('art') or ''}{g.group('noun')} named {_NAME_STAND_IN}", tail,
        )
        if rewritten == tail or _LEFTOVER.search(rewritten):
            return None
        matches = lambda v: v.lower() == _NAME_STAND_IN
        placeholder = CHOSEN_NAME_SENTINEL
    condition = m.group("cond")
    inner = None if condition else _reveal_discard_all_specs(rewritten)
    if inner is None:
        inner = parse(f"if {condition}, {rewritten}" if condition else rewritten)
    if not inner:
        return None
    gate = inner[0].condition if condition else None
    if condition and (gate is None or any(spec.condition != gate for spec in inner)):
        return None  # the "if" must gate the whole tail, or it is not the shape this reads
    swapped = _stand_in_removed(
        [EffectSpec(spec.type, spec.params) for spec in inner] if condition else inner, matches, placeholder,
    )
    if swapped is None or _reads_firing_event(swapped):
        return None
    out = _sequenced(EffectSpec("choose_for_source", params), EffectSpec("seq", {"effects": swapped}))
    if gate is not None:
        out = [EffectSpec(out[0].type, out[0].params, condition=gate)]
    return out
