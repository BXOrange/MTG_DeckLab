"""Same-name operands composed with the existing operation grammar."""
from __future__ import annotations

import re
from .clause_hooks import parse_effect_body
from .clause_reading import ClauseReading
from ..spec import EffectSpec
from .count_phrase import parse_count_phrase
from .filter_slots import PICKED_CARD_VALUE_PHRASE
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


def same_name_specs(body: str, reading: ClauseReading):
    picked = pick_then_search_specs(body, reading)
    if picked is not None:
        return picked
    search = _reference_search(body, reading)
    if search is not None:
        return search
    match = _SEARCH.fullmatch(body)
    if match is None:
        return None
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
