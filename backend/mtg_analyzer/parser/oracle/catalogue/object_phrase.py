"""Shared quantified object operands for existing effect clauses (PAR-210).

Operations stay in the handler table. This grammar reads an operand, asks the
same table for its singular targeted operation and composes its existing IR.
A missing operation or an unbound reference remains unclaimed.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Optional

from .characteristic_phrase import parse_object_phrase
from .clause_primitives import TARGET_PARAM_KEYS
from .count_phrase import NUMBER_WORD_PATTERN, number_value
from .clause_reading import ClauseReading, CREATED, PLAYER, TARGET
from .subgrammars import resolve_target_kind
from .quantifier_scope import quantified_set
from .referent_condition import PRONOUN_NOUN_ALT
from .referent_condition import parse_referent_condition
from ..spec import EffectSpec, GROUP_SUBJECT_KEY_SENTINEL


@dataclass(frozen=True)
class ObjectPhrase:
    kind: str
    noun: str = 'permanent'
    filter: Optional[dict] = None
    controller: Optional[str] = None
    count: int = 1
    optional: bool = False
    referent: Optional[str] = None
    over: Optional[dict] = None


# "another/other target X" excludes the source (RULE 109.1 identity); no target frame models that for a
# permanent, so an operand preceded by it is refused rather than read as plain "target X".
_START = re.compile(
    rf"(?<!another )(?<!other )(?<![\w'])\b(?:up to {NUMBER_WORD_PATTERN} target|{NUMBER_WORD_PATTERN} target|target|each other|all other|each|all|"
    rf"that player|that (?:{PRONOUN_NOUN_ALT}|card|enchantment|planeswalker|battle)|"
    r"those [a-z-]+|them|they|it)\b(?!')|~"
)
_REFERENCES = {
    'it': ('singular', 'permanent'), 'that creature': ('singular', 'creature'),
    'that permanent': ('singular', 'permanent'), 'that artifact': ('singular', 'artifact'),
    'that land': ('singular', 'land'), 'that card': ('singular', 'permanent'),
    'them': ('plural', 'permanent'), 'they': ('plural', 'permanent'),
    'those creatures': ('plural', 'creature'), 'those permanents': ('plural', 'permanent'),
    'those cards': ('plural', 'permanent'),
}
_QUANTIFIER = re.compile(rf'^(?:(?P<up>up to )?(?P<n>{NUMBER_WORD_PATTERN}) target|(?P<target>target)|(?P<group>each|all)(?P<other> other)?) (?P<object>.+)$')
_TYPE_WORDS = frozenset({'creature', 'artifact', 'enchantment', 'land', 'planeswalker', 'battle', 'permanent'})
_SCOPE_TAIL = {'you': ' you control', 'not_you': " you don't control"}
# A plural subject (an explicit group or a plural pronoun reference) agrees with the plural verb form.
_PLURAL_KINDS = frozenset({'group', 'references', 'selector_reference', 'created_references'})
_SINGULAR_REFERENCE = re.compile(rf"that (?P<noun>{PRONOUN_NOUN_ALT}|card|enchantment|planeswalker|battle)")


def _reference_info(text: str) -> Optional[tuple[str, str]]:
    if text in _REFERENCES:
        return _REFERENCES[text]
    singular = _SINGULAR_REFERENCE.fullmatch(text)
    if singular:
        noun = singular['noun']
        return 'singular', noun if noun in _TYPE_WORDS else 'permanent'
    if text.startswith('those '):
        parsed = parse_object_phrase(text.removeprefix('those '), plural=True)
        if parsed is not None and parsed[1] is None:
            noun = parsed[0].get('card_type', 'permanent')
            return 'plural', noun if noun in _TYPE_WORDS else 'permanent'
    return None


def parse_operand(text: str, reading: ClauseReading) -> Optional[ObjectPhrase]:
    """One shared target/group/reference grammar; unknown words never disappear."""
    if text == 'that player':
        if any(r.kind == PLAYER for r in reading.referents):
            return ObjectPhrase('reference', 'player', referent='previous_player')
        return None
    if text == '~':
        return ObjectPhrase('reference', referent='self')
    reference = _reference_info(text)
    if reference:
        number, noun = reference
        creations = [ref for ref in reading.referents if ref.kind == CREATED]
        if number == 'plural':
            if any(ref.group for ref in creations):
                return ObjectPhrase('created_references', noun)
            if reading.previous_subject and any(r.kind == TARGET and r.group for r in reading.referents):
                return ObjectPhrase('references', noun)
            if reading.previous_selector:
                return ObjectPhrase('selector_reference', noun)
            return None
        if creations:
            if any(ref.group for ref in creations):
                return None
            return ObjectPhrase('reference', noun, referent='created')
        if reading.previous_subject:
            if any(ref.kind == TARGET and ref.group for ref in reading.referents):
                return None
            return ObjectPhrase('reference', noun, referent='previous_subject')
        # Only the bare "it" names the attached host; "that creature" after "equipped creature deals damage to a
        # creature" / "blocks a creature" is the other object (Sword of Kaldra, Shield of the Righteous).
        if reading.attached_subject and text == 'it':
            return ObjectPhrase('reference', noun, referent='attached')
        if reading.group_subject:
            return ObjectPhrase('reference', noun, referent='trigger_subject')
        if text == 'it' and reading.self_subject:
            return ObjectPhrase('reference', noun, referent='self')
        return None
    match = _QUANTIFIER.fullmatch(text)
    if match is None:
        return None
    if match['group']:
        over = quantified_set(text, reading)
        if over is None:
            return None
        # The damage grammar resolves the defending player from its dealer,
        # which may be an Equipment's host rather than this ability's source.
        if (over.get('selector') or {}).get('of') == 'defending':
            return None
        filt = (over.get('selector') or {}).get('filter') or {}
        noun = 'player' if 'players' in over else filt.get('card_type', 'permanent')
        return ObjectPhrase('group', noun if noun in _TYPE_WORDS or noun == 'player' else 'permanent',
                            filt, over=over)
    plural = bool(match['n'])
    parsed = parse_object_phrase(match['object'], plural=plural)
    if parsed is None:
        return None
    filt, controller = parsed
    if controller not in (None, *_SCOPE_TAIL):
        return None
    filt = dict(filt)
    noun = filt.get('card_type', 'permanent')
    if noun not in _TYPE_WORDS:
        noun = 'permanent'
    count = number_value(match['n']) if match['n'] else 1
    if count <= 0:
        return None
    return ObjectPhrase('target', noun, filt, controller, count, bool(match['up']))


def _operation(text: str, operand: ObjectPhrase, start: int, end: int, reading: ClauseReading, match) -> Optional[list[EffectSpec]]:
    if text[:start].strip() == 'sacrifice' and not text[end:].strip():
        if operand.kind == 'target' or operand.noun == 'player':
            return None  # RULE 701.17: sacrifice does not target and only your permanents can be sacrificed.
        return [EffectSpec('sacrifice_target', {'controller_only': True})]
    nouns = (operand.noun,) if operand.noun == 'player' else tuple(dict.fromkeys((operand.noun, 'permanent', 'creature')))
    for noun in nouns:
        # RULE 205.1a: "it becomes a ... creature" may turn a non-creature into one, so an unknown "it" is never
        # re-read as an already-creature target (that would skip the animation rows' retention gate).
        if noun == 'creature' and operand.noun != 'creature' and re.match(r'\s*becomes?\b', text[end:]):
            continue
        phrase = f'target {noun}'
        tail = text[end:]
        optional = operand.noun == 'player' and not text[:start].strip() and tail.startswith(' may ')
        if optional:
            tail = ' ' + tail.removeprefix(' may ')
        if not text[:start].strip() and operand.kind in _PLURAL_KINDS:
            # RULE 608.2c: the plural subject changes agreement, never the duration.
            tail = re.sub(r'^ (get|gain|lose|draw|discard|mill|become|attack|block|assign)\b', lambda m: ' ' + m[1] + 's', tail)
        rewritten = text[:start] + phrase + tail
        rewritten = re.sub(r"\bto their owners?' hands\b", "to its owner's hand", rewritten)
        if rewritten == text:
            continue
        effects = match(rewritten, reading=reading)
        if not effects or len(effects) != 1:
            continue
        spec = effects[0]
        if spec.type == 'attach' and operand.referent == 'self' and text.startswith('attach it to'):
            # "attach it to ~": the `attach` row reads "it" as the attaching source and the operand as its destination, so
            # the self wrapper would attach the source to itself -- the opposite of an earlier-picked Equipment moving
            # onto this permanent (Thieving Skydiver).
            continue
        kind = resolve_target_kind(phrase)
        # Exactly one target slot. A fight, attachment, divided damage or a fused
        # sequence may have other operands and must retain its own composition.
        if (spec.params.get('target_kind') != kind or any(
                key != 'target_kind' and spec.params.get(key) is not None for key in TARGET_PARAM_KEYS)
                or any(key in spec.params for key in ('effects', 'divided', 'count_selector', 'count_max'))):
            continue
        return [EffectSpec('optional', {'player': 'target', 'effects': [e.to_dict() for e in effects]})] if optional else effects
    return None


#: RULE 115.1: the qualities the singular body ("destroy target permanent with mana value 3") states on its *target*.
#: A `for_each` over a group announces nothing, so they have to move to the group's own filter or the loop would hit
#: every member (Dauntless Dismantler, Pernicious Deed, Vicious Rivalry, Swift Demise destroyed everything).
_TARGET_BOUND_KEYS = ('exact_mana_value', 'max_mana_value', 'min_mana_value')


def _fold_target_bounds_into_group(
    over: dict, effects: list[EffectSpec],
) -> Optional[tuple[dict, list[EffectSpec]]]:
    """``(group, body)`` with the body's target-only bounds moved onto the group's selector filter, or ``None``."""
    if len(effects) != 1:
        return over, effects
    spec = effects[0]
    bounds = {k: spec.params[k] for k in _TARGET_BOUND_KEYS if spec.params.get(k) is not None}
    quality = spec.params.get('creature_filter')
    if not bounds and not quality:
        return over, effects
    selector = over.get('selector')
    if not isinstance(selector, dict):
        return None  # a player group has no object filter to carry them
    if quality and set(quality) & set(selector.get('filter') or {}):
        return None  # the same key twice would silently pick one meaning
    params = {k: v for k, v in spec.params.items() if k not in _TARGET_BOUND_KEYS and k != 'creature_filter'}
    folded = {**over, 'selector': {**selector, 'filter': {**(selector.get('filter') or {}), **bounds, **(quality or {})}}}
    return folded, [EffectSpec(spec.type, params, condition=spec.condition)]


def ambiguous_object_reference(text: str, reading: ClauseReading, match: Callable) -> bool:
    """A singular object cannot silently choose one member of an earlier plural pick."""
    if not any(ref.kind == TARGET and ref.group for ref in reading.referents):
        return False
    if any(ref.kind == CREATED and not ref.group for ref in reading.referents):
        return False
    for found in _START.finditer(text):
        phrase = found.group()
        info = _reference_info(phrase)
        if info is None or info[0] != 'singular':
            continue
        if _operation(text, ObjectPhrase('reference', info[1]),
                      found.start(), found.end(), reading, match):
            return True
    return False


def _compose(operand: ObjectPhrase, effects: list[EffectSpec]) -> Optional[list[EffectSpec]]:
    body = [e.to_dict() for e in effects]
    if operand.kind == 'reference':
        params = {'referent': operand.referent, 'effects': body}
        if operand.referent == 'trigger_subject':
            params['event_key'] = GROUP_SUBJECT_KEY_SENTINEL
        return [EffectSpec('trigger_subject_referent', params)]
    if operand.kind in ('references', 'selector_reference', 'created_references'):
        over = {dict(references='previous_targets', selector_reference='previous_selector',
                     created_references='created_objects')[operand.kind]: True, 'simultaneous': True}
        return [EffectSpec('for_each', {'over': over, 'effects': body})]
    if operand.kind == 'group':
        over = dict(operand.over or {})
        folded = _fold_target_bounds_into_group(over, effects)
        if folded is None:
            return None
        over, effects = folded
        body = [e.to_dict() for e in effects]
        if 'selector' in over:
            over.update(remember=True, simultaneous=True)
        return [EffectSpec('for_each', {'over': over, 'effects': body})]
    kind = resolve_target_kind(f'target {operand.noun}' + _SCOPE_TAIL.get(operand.controller, ''))
    if kind is None:
        return None
    announce = EffectSpec('choose_targets', {
        'kinds': [kind], 'count': operand.count, 'optional': operand.optional,
        'creature_filter': operand.filter or {},
    })
    iterate = EffectSpec('for_each', {'over': {'targets': True, 'simultaneous': True}, 'effects': body})
    return [EffectSpec('seq', {'effects': [announce.to_dict(), iterate.to_dict()]})]


def conditional_object_specs(text: str, reading: ClauseReading, parse_body: Callable) -> Optional[list[EffectSpec]]:
    """RULE 115.1: a target introduced in the condition is announced only once.

    The shared operand grammar narrows that target; the shared predicate vocabulary
    then tests it at resolution. The condition is never a target restriction.
    """
    found = re.fullmatch(r'if (?P<object>target .+?) (?P<predicate>is .+?|has .+?), (?P<body>.+)', text)
    if found is None:
        return None
    operand = parse_operand(found['object'], reading)
    condition = parse_referent_condition('it ' + found['predicate'])
    if operand is None or operand.kind != 'target' or operand.count != 1 or condition is None:
        return None
    effects = parse_body(found['body'], reading=ClauseReading(previous_subject=True))
    if not effects:
        return None
    kind = resolve_target_kind(f'target {operand.noun}' + _SCOPE_TAIL.get(operand.controller, ''))
    if kind is None:
        return None
    announce = EffectSpec('choose_targets', {'kinds': [kind], 'count': 1, 'creature_filter': operand.filter or {}})
    # One if_else node tests once before any effect can change the condition.
    guarded = EffectSpec('if_else', {
        'condition': {**condition, 'of': 'previous_target'},
        'then': [e.to_dict() for e in effects], 'else': [],
    })
    return [EffectSpec('seq', {'effects': [announce.to_dict(), guarded.to_dict()]})]


def object_phrase_specs(
    text: str, reading: ClauseReading, match: Callable, *, references_only: bool = False,
) -> Optional[list[EffectSpec]]:
    """Back off to the singular operation only after an exact operand parse."""
    if re.search(r"\bwhere x is\b", text, re.I):
        return None  # the shared X binder measures once before any object iteration
    # RULE 615: a plural recipient/dealer is a set even without an explicit
    # "each" (Commencement of Festivities). The targeted shield keeps its duration.
    plural_prevention = re.fullmatch(r'(prevent all (?:combat )?damage that would be dealt (?:to|by) )((?:players|opponents|creatures)(?: [a-z0-9+/-]+)*)( this turn)', text)
    if plural_prevention:
        text = plural_prevention[1] + 'all ' + plural_prevention[2] + plural_prevention[3]
    for start in _START.finditer(text):
        for end in reversed([m.end() for m in re.finditer(r"[^\s,.;]+", text[start.start():])]):
            end += start.start()
            phrase = text[start.start():end]
            if references_only and _reference_info(phrase) is None and phrase != 'that player':
                continue
            operand = parse_operand(phrase, reading)
            if operand is None:
                continue
            effects = _operation(text, operand, start.start(), end, reading, match)
            # A bare "it" in a copy clause may be the cast spell, not the permanent (RULE 707.10 vs 707.2):
            # the copy rows already gate that on the attacking shape, so the pronoun is not re-read as ~ here.
            if (effects is not None and phrase == 'it' and operand.referent == 'self'
                    and any(e.type == 'copy_permanent' for e in effects)):
                continue
            if effects is not None:
                composed = _compose(operand, effects)
                if composed is not None:
                    return composed
    return None

