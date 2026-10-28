"""Composable bounded inspections: a lead, selections and destinations (PAR-213)."""
from __future__ import annotations

import re
from typing import Callable

from ..spec import EffectSpec
from .dig import parse_criteria as _parse_criteria
from .characteristic_phrase import parse_head

_LIBRARY = r"(?:your library|target (?P<target>player|opponent)'s library)"
_LEAD = re.compile(
    rf"(?P<verb>look at|reveal) the top (?:(?P<count>\d+) cards|card) of {_LIBRARY}"
    r"|target (?P<hand_target>player|opponent) reveals their hand"
    r"|target (?P<library_target>player|opponent) reveals the top (?:(?P<target_count>\d+) cards|card) of their library"
    r"|(?P<each>each player) reveals the top card of their library", re.I,
)
_DEST = {
    'into your hand': 'hand', 'into your graveyard': 'graveyard',
    'onto the battlefield': 'battlefield', 'onto the battlefield tapped': 'battlefield_tapped',
    "into that player's graveyard": 'graveyard', 'into their graveyard': 'graveyard',
    'on the bottom of your library in a random order': 'bottom_random',
    'on the bottom of your library in any order': 'bottom',
    'on top of your library in any order': 'top',
    'back on top of your library in any order': 'top',
    'on top of their library in any order': 'top',
    'on the bottom of your library': 'bottom',
}
_REF = r"(?:it|them|that card|those cards|the chosen cards|the revealed cards)"
_FROM = r"(?:from among (?:them|the revealed cards)|from it|of (?:them|those cards)|revealed this way)"
_PICK = re.compile(
    rf"(?P<may>you may )?(?:(?P<opponent>an opponent) |you )?"
    rf"(?P<verb>choose|chooses|reveal|put|exile) "
    rf"(?P<quant>an?|1|\d+|up to \d+|any number of|all) "
    rf"(?:(?P<criteria>(?:.+? )?cards?) )?{_FROM}"
    rf"(?: and put {_REF})?(?: (?P<dest>.+))?", re.I,
)


def parse_criteria(phrase: str) -> dict | None:
    """Dig criteria with the shared, closed characteristic vocabulary."""
    criteria = _parse_criteria(phrase)
    def known(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ('type', 'all_types', 'without_type'):
                    if any(parse_head(word) is None for word in (value if isinstance(value, list) else [value])):
                        return False
                elif not known(value):
                    return False
        elif isinstance(node, list):
            return all(known(value) for value in node)
        return True
    return criteria if criteria is not None and known(criteria) else None


def parse_inspection(text: str, parse_tail: Callable) -> list[EffectSpec] | None:
    """Read each step independently; an unknown step rejects the complete sequence.

    Existing whole-block handlers keep precedence. X and measured counts are
    deliberately outside this bounded grammar (PAR-144's safety boundary).
    """
    parts = [s.strip().rstrip('.') for s in re.split(r'\.\s+', text.strip().rstrip('.'))]
    lead = _LEAD.fullmatch(parts[0])
    if lead is None:
        return None
    target = lead['target'] or lead['hand_target'] or lead['library_target']
    params = {'zone': 'hand' if lead['hand_target'] else 'library',
              'count': int(lead['count'] or lead['target_count'] or 1), 'reveal': lead['verb'] == 'reveal' or bool(lead['hand_target'] or lead['library_target'] or lead['each']),
              'scope': 'each_player' if lead['each'] else 'target' if target else 'you'}
    if target:
        params['target_kind'] = target
    steps = []
    markers = []
    selected = False
    # Coordinated steps share exactly the same inspected pool.
    sentences = []
    for part in parts[1:]:
        # Coordinated quantified selections reuse the same source pool.
        part = re.sub(r' and (?=up to \d+ .+? from among)', '. put ', part)
        # Ellipsis repeats the selection's object and verb (Moment of Truth).
        part = re.sub(r', (?:and )?(\d+) (into your (?:hand|graveyard)|on the bottom of your library)',
                      r'. put \1 of them \2', part)
        part = re.sub(r' and the rest ', '. put the rest ', part)
        sentences.extend(re.split(r'\. |,? (?:and |then )?(?=(?:put|exile) the rest\b)', part))
    for sentence in sentences:
        sentence = re.sub(r'^then ', '', sentence)
        conditional = re.fullmatch(r"if you (?:(?P<negative>don't|didn't|do not)|do),\s*(?P<body>.+)", sentence)
        condition = None
        if conditional:
            if not selected:
                return None
            condition = 'not_chosen' if conditional['negative'] else 'chosen'
            sentence = conditional['body']
        if condition:
            # A guarded step is parsed recursively through the same step grammar,
            # then attached to the already established selection.
            nested = parse_inspection(parts[0] + '. choose a card from among them. ' + sentence, parse_tail)
            if not nested or len(nested) != 1:
                return None
            guarded = nested[0].params['steps'][1:]
            steps.extend({**step, 'condition': condition} for step in guarded)
            continue
        if sentence in ('that player shuffles', 'shuffle', 'shuffle your library'):
            steps.append({'op': 'shuffle', 'owners': sentence == 'that player shuffles'})
            continue
        rest = re.fullmatch(r'(?:put (?:the rest(?: of (?:the cards revealed this way|the revealed cards|them))?|the other) (.+)|exile the rest)', sentence)
        if rest:
            dest = 'exile' if sentence == 'exile the rest' else _DEST.get(rest[1])
            if dest is None:
                return None
            steps.append({'op': 'move', 'pool': 'rest', 'destination': dest})
            continue
        pick = _PICK.fullmatch(sentence)
        if pick:
            criteria = parse_criteria(pick['criteria'] or 'card')
            if criteria is None:
                return None
            quant = pick['quant']
            count = 'all' if quant in ('all', 'any number of') else int(quant.split()[-1]) if quant.split()[-1].isdigit() else 1
            optional = bool(pick['may']) or quant.startswith('up to') or quant == 'any number of'
            random_pick = pick['dest'] == 'at random'
            dest = 'exile' if pick['verb'] == 'exile' else _DEST.get(pick['dest'] or '')
            if pick['dest'] and (dest is None or pick['verb'] == 'exile' and not random_pick):
                return None
            if pick['verb'] in ('put', 'reveal') and dest is None and pick['verb'] != 'reveal':
                return None
            steps.append({'op': 'choose', 'criteria': criteria, 'count': count, 'optional': optional,
                          'chooser': 'opponent' if pick['opponent'] else 'you',
                          'all': quant == 'all', 'random': random_pick})
            selected = True
            if pick['verb'] == 'reveal':
                steps.append({'op': 'reveal', 'pool': 'chosen'})
            if dest:
                steps.append({'op': 'move', 'pool': 'chosen', 'destination': dest})
            continue
        move = re.fullmatch(rf'(?:put {_REF} (.+)|(?:that player |they )?discards? {_REF}|exile {_REF})', sentence)
        if move and selected:
            dest = 'discard' if 'discard' in sentence else 'exile' if sentence.startswith('exile') else _DEST.get(move[1])
            if dest is None:
                return None
            steps.append({'op': 'move', 'pool': 'chosen', 'destination': dest})
            continue
        # A payoff counts the original per-player revealed set, not the rest.
        payoff = re.fullmatch(r'for each (?P<criteria>.+? cards?) revealed this way, (?P<body>.+)', sentence)
        if payoff:
            criteria = parse_criteria(payoff['criteria'])
            effects = parse_tail(re.sub(r'^you ', '', payoff['body']))
            if criteria is None or not effects:
                return None
            steps.append({'op': 'payoff', 'criteria': criteria, 'effects': [s.to_dict() for s in effects]})
            continue
        if sentence in ('put those cards into their owners\' hands', 'each player puts the card they revealed this way into their hand'):
            steps.append({'op': 'move', 'pool': 'all', 'destination': 'hand'})
            continue
        # A free tail must not announce targets hidden inside this resolution-only sequence.
        if re.search(r'\btarget\b', sentence):
            return None
        single_reveal_condition = (params['count'] == 1 and params['zone'] == 'library' and params['reveal']
                                   and re.match(r"if (?:it's|it is|that card is) ", sentence))
        if not single_reveal_condition and re.search(r"\b(?:it|its|them|they|that card|those cards|revealed this way)\b", sentence):
            return None
        effects = parse_tail(sentence)
        if effects and single_reveal_condition:
            def revealed(node):
                if isinstance(node, dict):
                    return {**{k: revealed(v) for k, v in node.items()}, **({'of': 'revealed'} if node.get('kind') in ('is_card_type', 'is_color', 'is_subtype') and 'of' not in node else {})}
                if isinstance(node, list):
                    return [revealed(v) for v in node]
                return node
            effects = [EffectSpec(e.type, revealed(e.params), condition=revealed(e.condition)) for e in effects]
            # "If it's a land card, untap this creature and it gets +1/+1": the leading "if" gates the whole
            # sentence, but the shared tail attaches it to the first effect only. Gate the compound as one unit.
            gate = effects[0].condition
            if gate is None or any(e.condition not in (None, gate) for e in effects):
                return None
            if len(effects) > 1:
                effects = [EffectSpec('seq', {'effects': [EffectSpec(e.type, e.params).to_dict() for e in effects]},
                                      condition=gate)]
        if effects is None:
            return None
        markers.extend(e for e in effects if e.type.endswith('_marker'))
        executable = [e for e in effects if not e.type.endswith('_marker')]
        if executable:
            steps.append({'op': 'effects', 'effects': [s.to_dict() for s in executable]})
    params['steps'] = steps
    return [EffectSpec('inspect_cards', params), *markers]


def starts_inspection(text: str) -> bool:
    return _LEAD.fullmatch(re.split(r"\.\s+", text.strip().rstrip('.'))[0]) is not None


_PRONOUN_FOLLOW_UP = re.compile(r"\b(?:it|its|them|they|that card|those cards|the revealed cards?)\b", re.I)


#: "equal to its / that card's mana value" after a lone "reveal the top card of your library" measures that revealed
#: card (RULE 701.20), which `InspectCardsEffect` leaves as `GameContext.revealed_card`; it is not a dangling pronoun.
_REVEALED_AMOUNT_FOLLOW_UP = re.compile(r"\bequal to (?:its|that card's) (?:mana value|power|toughness)\b", re.I)


def leaves_dangling_reference(specs: list, follow_up: str) -> bool:
    """True if ``specs`` end in a bare lead (no steps) and ``follow_up`` refers back to what it inspected.

    A bare lead is a legitimate whole ability ("look at the top card of your library"), but as the first half of
    "Reveal the top card. If it's a creature card, put it into your hand." the pronoun would otherwise bind to the
    ability's source (RULE 608.2c). Such a pair belongs to the whole-block Dig grammar or stays unclaimed."""
    def bare_lead(node) -> bool:
        if isinstance(node, dict):
            if node.get('type') == 'inspect_cards' and not (node.get('params') or {}).get('steps'):
                return True
            return any(bare_lead(v) for v in node.values())
        return isinstance(node, list) and any(bare_lead(v) for v in node)
    if _REVEALED_AMOUNT_FOLLOW_UP.search(follow_up):
        return False
    return bool(specs) and bare_lead([e.to_dict() for e in specs[-1:]]) and _PRONOUN_FOLLOW_UP.search(follow_up) is not None
