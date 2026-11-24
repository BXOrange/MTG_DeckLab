"""Same-name operands composed with the existing operation grammar."""
from __future__ import annotations

import re
from .clause_hooks import parse_effect_body
from .clause_reading import ClauseReading
from ..spec import EffectSpec
from ....models.cards.creature_types import CREATURE_SUBTYPES
from .count_phrase import parse_count_phrase
from .filter_slots import PICKED_CARD_VALUE_PHRASE
from .modal import PERMANENT_CARD_TYPE_WORDS
from .name_atoms import name_reference
from .object_phrase import parse_operand
from .subgrammars import resolve_target_kind

_SEARCH = re.compile(
    r"(?P<before>.+?)\. search its (?P<who>controller|owner)'s graveyard, hand, and library "
    r"for (?P<quantity>all|any number of) cards with the same name as that "
    r"(?:spell|card|creature|artifact|enchantment|land|permanent) and exile them\. then that player shuffles\.?"
)
_CHOOSE_GRAVEYARD = re.compile(r"choose target card in a graveyard other than a basic land card")


#: RULE 608.2c / 701.20 / 701.9: "reveal a [<type>] card in/from your hand. Search your library for a card with the
#: same name as that card ..." (Assembly Hall, Infernal Tutor) and "you may discard a [<type>] card. If you do, search
#: your library for a card with the same mana value as that card ..." (Disciple of Deceit). The pick is made while the
#: ability resolves, so the whole second sentence rides the pick as its follow-up (`choose_objects` ``then``); the
#: engine reads the picked card as the follow-up's `previous_subject`, so "that card" is the card the player chose,
#: and its name / mana value are measured when the search opens (a discarded card keeps both in the graveyard).
_PICK_THEN_SEARCH = re.compile(
    r"(?:(?P<may>you may )discard|(?P<reveal>reveal)) an? (?P<kind>[a-z]+ )?card(?: (?:in|from) your hand)?\."
    r"(?(may)\s*if you do,)\s*(?P<rest>search your library [^.]+)"
    # RULE 614.1 / 608.2c: Infernal Tutor's hellbent clause replaces the whole instruction when the hand is empty.
    r"(?:\.\s*if you have no cards in hand, instead (?P<instead>search your library for a card, "
    r"put it into your hand, then shuffle))?"
)
#: The condition the "if you have no cards in hand" gate parses to (`effect_conditions`, RULE 402.1).
#: The `card_query` key `resolve_search_names` writes for an undefined name: the empty name overlaps no card.
NAME_MATCHES_NOTHING = "same_name_as"
HAND_EMPTY_CONDITION = {"kind": "cards_in_hand_at_most", "amount": 0}
_SAME_NAME_AS_THAT_CARD = " with the same name as that card"
_SAME_VALUE_AS_THAT_CARD = " with the same mana value as that card"


#: RULE 608.2d / 201.2a: "choose a land you control. Then search your library for up to 2 basic land cards which have the
#: same name as the chosen land, ..." (Canoptek Wraith): the same pick-then-search with the pick made among the
#: controller's own permanents of one type; the choice changes nothing, only the follow-up reads it.
_CHOOSE_THEN_SEARCH = re.compile(
    r"choose an? (?P<kind>land|creature|artifact|enchantment) you control\.\s*then (?P<rest>search your library [^.]+)"
)


def _choose_then_search_specs(body: str):
    match = _CHOOSE_THEN_SEARCH.fullmatch(body.strip().rstrip("."))
    if match is None:
        return None
    chosen = f" which have the same name as the chosen {match['kind']}"
    rest = match["rest"]
    if rest.count(chosen) != 1:
        return None
    follow = parse_effect_body(rest.replace(chosen, _SAME_NAME_AS_THAT_CARD), reading=ClauseReading(previous_subject=True))
    if not follow or len(follow) != 1 or "previous_subject" not in repr(follow[0].to_dict()):
        return None
    return [EffectSpec("choose_objects", {
        "action": "select_referent", "what": "permanent", "count": 1, "optional": False,
        "permanent_filter": {"card_type": match["kind"]}, "then": [spec.to_dict() for spec in follow],
    })]


def pick_then_search_specs(body: str, reading: ClauseReading):
    chosen = _choose_then_search_specs(body)
    if chosen is not None:
        return chosen
    match = _PICK_THEN_SEARCH.fullmatch(body.strip().rstrip("."))
    if match is None:
        return None
    kind = (match["kind"] or "").strip() or None
    pool = parse_count_phrase(f"{kind + ' ' if kind else ''}cards in your hand")
    if not isinstance(pool, dict) or pool.get("zone") != "hand" or pool.get("of") != "you" or "distinct" in pool:
        return None
    rest = match["rest"]
    if rest.count(_SAME_NAME_AS_THAT_CARD) + rest.count(_SAME_VALUE_AS_THAT_CARD) != 1:
        return None
    if match["reveal"] and _SAME_VALUE_AS_THAT_CARD in rest:
        return None  # only the printed pairings: a revealed card feeds a name, a discarded card a mana value
    if match["may"] and _SAME_NAME_AS_THAT_CARD in rest:
        return None
    rest = rest.replace(_SAME_VALUE_AS_THAT_CARD, f" with mana value equal to {PICKED_CARD_VALUE_PHRASE}")
    follow = parse_effect_body(rest, reading=ClauseReading(previous_subject=True))
    if not follow or len(follow) != 1 or not {"previous_subject"} & set(re.findall(r"previous_subject", repr(follow[0].to_dict()))):
        return None
    params = {
        "action": "discard" if match["may"] else "reveal", "what": "permanent", "count": 1,
        "optional": bool(match["may"]), "pool_zones": ["hand"],
        "then": [spec.to_dict() for spec in follow],
    }
    if pool.get("filter"):
        params["permanent_filter"] = dict(pool["filter"])
    if match["reveal"]:
        # RULE 701.19b / 701.23c: with no card to reveal the name is undefined, so the search can find nothing -- but
        # the search still happens and the library is still shuffled. (A declined "If you do" discard skips it all.)
        empty = follow[0].to_dict()
        criteria = dict(empty["params"].get("criteria") or {})
        if criteria.pop("name_reference", None) is None:
            return None
        empty["params"] = {**empty["params"], "criteria": {**criteria, NAME_MATCHES_NOTHING: ""}}
        params["else_effects"] = [empty]
    pick = EffectSpec("choose_objects", params)
    if not match["instead"]:
        return [pick]
    fallback = parse_effect_body(match["instead"], reading=ClauseReading())
    if not fallback or len(fallback) != 1 or fallback[0].type != "search" or not match["reveal"]:
        return None
    # An empty hand offers nothing to pick, so the replacement is decided before the pick (RULE 608.2c).
    return [EffectSpec("if_else", {
        "condition": dict(HAND_EMPTY_CONDITION), "then": [fallback[0].to_dict()], "else": [pick.to_dict()],
    })]


#: RULE 701.19 / 701.23 / 701.20: the Cranial Extraction family's same-name sweep with a name taken from the card a clause
#: of the same spell just picked, targeted or exiled (the chosen-NAME family is `named_choice`'s `exile_named_from_zones`).
#: ``<lead>. [if <cond>, ]search <the player's> graveyard, hand, and library for <all | any number of> cards with the same
#: name as <that card>[ and exile them. | , exile those cards,] [then] that player shuffles[, then draws a card for each card
#: exiled from their hand this way]``. Only the sweep sentence is read here; the lead is one of the shapes `_sweep_lead`
#: knows. The name and the player are read from the reference card (RULE 608.2h: before the lead moves it) and the library
#: owner shuffles once at the end (RULE 701.20).
_SWEEP_WHERE = (
    r"(?:its (?P<who>controller|owner)'s graveyard, hand, and library"
    r"|(?P<that>that player's graveyard, hand, and library)"
    r"|the graveyard, hand, and library of that spell's (?P<who2>controller))"
)
_SWEEP_REFERENCE = r"(?:that (?:spell|card|creature|artifact|enchantment|permanent)|the (?:chosen|exiled) card)"
_SWEEP_SENTENCE = re.compile(
    r"(?:(?P<each>for each card exiled this way), )?(?:if (?P<cond>[^,]+), )?"
    rf"search {_SWEEP_WHERE} for (?P<quantity>all|any number of) cards with the same name as (?P<ref>{_SWEEP_REFERENCE})"
    r"(?: and exile them\.|, exile those cards,) (?:then )?that player shuffles"
    r"(?P<draw>, then draws a card for each card exiled from their hand this way)?\.?"
)
#: The sweep's own "draws a card for each card exiled from their hand this way" (`$n` = that count).
_SWEEP_DRAW = [{"type": "draw", "params": {"count": "$n"}}]
#: "the exiled card is a God card" (Deicide): a gate on the reference card's printed card type / subtype, one word.
_SWEEP_REFERENCE_IS = re.compile(r"the exiled card is an? (?P<kind>[a-z]+) card")
_SWEEP_DELIRIUM_PROBE = "if {cond}, draw a card."

#: The hand-pick leads: "<player> reveals their hand[,|.] [then] you choose <a ... card | up to X nonland cards> from it
#: [and exile that card | and exile them]". ``that player`` (a combat-damage trigger's damaged player) is stamped by the
#: segmenter into the trigger's player referent before this reads it, so only the "target" spellings are read.
_SWEEP_PICK_FILTERS: dict[str, dict] = {
    "a card": {},
    "a nonland card": {"exclude_land": True},
    "a card other than a basic land card": {"card_filter": {"not_basic_land": True}},
}
_SWEEP_PICK_LEAD = re.compile(
    r"(?P<who>target player|target opponent) reveals their hand(?:, then |\. )you choose "
    r"(?:(?P<filter>a card|a nonland card|a card other than a basic land card)|up to (?P<x>x) (?P<xfilter>nonland) cards)"
    r" from it(?P<exile> and exile (?:that card|them))?"
)


def _sweep_lead(lead: str, reading: ClauseReading):
    """``(effects, spec_list_for_pick, role)``: how the lead supplies the name -- ``("target", effects)`` for a targeted
    counter / exile / destroy, ``("pick", reveal_params, exiles)`` for a hand pick, else ``None``."""
    pick = _SWEEP_PICK_LEAD.fullmatch(lead)
    if pick is not None:
        params: dict = {"target_kind": "opponent" if pick["who"] == "target opponent" else "player"}
        if pick["x"]:
            params.update({"exclude_land": True, "count": "x", "up_to": True})
            if not pick["exile"] or pick["exile"].endswith("that card"):
                return None
        else:
            params.update(_SWEEP_PICK_FILTERS[pick["filter"]])
            if pick["exile"] and not pick["exile"].endswith("that card"):
                return None
        return "pick", params, bool(pick["exile"])
    before = parse_effect_body(lead, reading=reading)
    # A single object provides both the name and the pre-move controller.
    if not before or len(before) != 1 or before[0].type not in {"counter", "exile", "destroy"}:
        return None
    if before[0].params.get("count", 1) != 1 or before[0].params.get("count_max") is not None:
        return None
    if (before[0].type != "counter" and not before[0].params.get("target_kind")) or before[0].params.get("selector"):
        return None
    return "target", [effect.to_dict() for effect in before]


def _sweep_specs(body: str, reading: ClauseReading):
    text = re.sub(r"\s*\n\s*", " ", body.strip())
    for boundary in (m.end() for m in re.finditer(r"\. ", text)):
        lead, tail = text[:boundary - 2], text[boundary:]
        match = _SWEEP_SENTENCE.fullmatch(tail)
        if match is not None:
            break
    else:
        return None
    read = _sweep_lead(lead, reading)
    if read is None:
        return None
    params: dict = {"any_number": match["quantity"] == "any number of"}
    if match["draw"]:
        params["then_effects"] = [dict(effect) for effect in _SWEEP_DRAW]
    if match["cond"]:
        gate = _SWEEP_REFERENCE_IS.fullmatch(match["cond"])
        if gate is not None:
            if gate["kind"] not in CREATURE_SUBTYPES | PERMANENT_CARD_TYPE_WORDS:
                return None  # an unknown word must not become a filter
            params["reference_filter"] = {"type": gate["kind"].capitalize()}
        else:
            probe = parse_effect_body(_SWEEP_DELIRIUM_PROBE.format(cond=match["cond"]), reading=ClauseReading())
            if not probe or len(probe) != 1 or probe[0].type != "draw" or probe[0].condition is None:
                return None
            params["condition"] = dict(probe[0].condition)
    if read[0] == "target":
        # "its controller's / owner's" or "that spell's controller": the object's own player (RULE 608.2h).
        if match["that"] or match["each"] or match["ref"].startswith("the "):
            return None
        params["player_role"] = match["who"] or match["who2"]
        params["effects"] = read[1]
        return [EffectSpec("same_name_search", params)]
    # A hand pick: the picked card(s) feed the sweep as the previous subject; "that player" is the picked cards' owner.
    if match["who"] or match["who2"] or not match["that"]:
        return None
    if bool(match["each"]) != (read[1].get("count") == "x"):
        return None
    sweep = EffectSpec("same_name_search", {**params, "player_role": "owner", "from_previous": True}).to_dict()
    follow = [sweep]
    if read[2]:
        # RULE 701.20 / 400.3: the exile is the pick's own action, done before the sweep reads the name.
        follow.insert(0, {"type": "exile", "params": {"target_kind": "previous_target", "previous_zone": "hand"}})
    # BUG-83, RULE 608.2c: "Then that player shuffles" does not depend on the pick finding anything.
    pick_params = {**read[1], "then_specs": [{"type": "seq", "params": {"effects": follow}}], "shuffle_if_none": True}
    if "condition" in params:
        pick_params["shuffle_condition"] = dict(params["condition"])  # Pick the Brain's delirium gates the shuffle too
    return [EffectSpec("reveal_hand_choose_discard", pick_params)]


#: PAR-292 M24, RULE 701.19a / 401.2 / 201.2: "Choose target permanent an opponent controls. Search that player's library
#: for a card with the same name and put it onto the battlefield under your control. Then that player shuffles."
#: (Mimeofacture). The chosen permanent is announced, its controller's library is the one searched (and shuffled), the
#: spell's controller looks through it, and the found card enters under that controller (it stays owned by the library's
#: owner, RULE 108.3). The name is the chosen permanent's, read as it is when the search opens.
_CHOOSE_TARGET_LIBRARY_SEARCH = re.compile(
    r"choose (?P<target>target [a-z ]+? an opponent controls)\.\s*search that player's library for a card with the same name "
    r"and put it onto the battlefield under your control\.\s*then that player shuffles"
)


def _choose_target_library_search_specs(body: str):
    match = _CHOOSE_TARGET_LIBRARY_SEARCH.fullmatch(body.strip().rstrip("."))
    if match is None:
        return None
    operand = parse_operand(match["target"], ClauseReading())
    kind = resolve_target_kind(match["target"])
    if operand is None or operand.kind != "target" or operand.count != 1 or kind is None:
        return None
    return [
        EffectSpec("choose_targets", {"kinds": [kind], "creature_filter": operand.filter or {}}),
        EffectSpec("search", {
            "criteria": {"name_reference": {"kind": "previous_subject"}}, "destination": "battlefield",
            "count": 1, "player": "previous_target_controller", "searched_by_controller": True,
        }),
    ]


def same_name_specs(body: str, reading: ClauseReading):
    chosen_library = _choose_target_library_search_specs(body)
    if chosen_library is not None:
        return chosen_library
    picked = pick_then_search_specs(body, reading)
    if picked is not None:
        return picked
    search = _reference_search(body, reading)
    if search is not None:
        return search
    match = _SEARCH.fullmatch(body)
    if match is None:
        return _sweep_specs(body, reading)
    if _CHOOSE_GRAVEYARD.fullmatch(match['before']):
        before = [EffectSpec('choose_targets', {
            'kinds': ['any_graveyard_card'], 'creature_filter': {'not_basic_land': True},
        })]
    else:
        before = parse_effect_body(match['before'], reading=reading)
        # A single object provides both the name and the pre-move controller.
        if not before or len(before) != 1 or before[0].type not in {'counter', 'exile', 'destroy'}:
            return None
        if before[0].params.get('count', 1) != 1 or before[0].params.get('count_max') is not None:
            return None
        if (before[0].type != 'counter' and not before[0].params.get('target_kind')) or before[0].params.get('selector'):
            return None
    return [EffectSpec('same_name_search', {
        'effects': [effect.to_dict() for effect in before],
        'player_role': match['who'], 'any_number': match['quantity'] == 'any number of',
    })]


_NAME_SEARCH = re.compile(
    r"(?P<before>(?:you may )?search your library(?: and/or graveyard)? for .+?) "
    r"with the same name as (?P<reference>.+?)(?P<after>, (?:reveal|put).+)"
)


def _reference_search(body: str, reading: ClauseReading):
    match = _NAME_SEARCH.fullmatch(body.rstrip('.'))
    if match is None:
        return None
    ref = name_reference(match['reference'])
    announce = []
    if ref is None:
        operand = parse_operand(match['reference'], reading)
        if operand is None or operand.count != 1:
            return None
        if operand.kind == 'reference':
            ref = {'kind': operand.referent}
        elif operand.kind == 'target':
            kind = resolve_target_kind('target ' + operand.noun + {'you': ' you control', 'not_you': " you don't control"}.get(operand.controller, ''))
            if kind is None:
                return None
            announce = [EffectSpec('choose_targets', {'kinds': [kind],
                'creature_filter': operand.filter or {}})]
            ref = {'kind': 'target'}
        else:
            return None
    specs = parse_effect_body(match['before'] + match['after'], reading=reading)
    if not specs:
        return None
    def bind(node):
        if node['type'] == 'search':
            node['params']['criteria']['name_reference'] = ref
            return True
        children = node.get('params', {}).get('effects', [])
        return len(children) == 1 and bind(children[0])
    nodes = [spec.to_dict() for spec in specs]
    if len(nodes) != 1 or not bind(nodes[0]):
        return None
    return announce + [EffectSpec(node['type'], node['params']) for node in nodes]
