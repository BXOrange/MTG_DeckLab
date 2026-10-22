"""Mechanic evidence and style vectors; deliberately independent of SmartBot 1.

Names identify deck entries and Spellbook ingredients, never action bonuses.
A feature is heuristic evidence, not an engine-support verdict.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import json
import re

from mtg_analyzer.services.bot_strategy import CardPlan, DeckStrategy, build_strategy, normalize
from mtg_analyzer.services.archetype_database import default_archetype_database
from mtg_analyzer.services.archetype_analysis import detect_typal_signals

PROFILE_VERSION = 1
# Commander evidence matters, but cannot overwhelm a whole deck's composition.
COMMANDER_EVIDENCE_WEIGHT = 2
# A family needs corroboration; one incidental support card isn't a deck plan.
MIN_THEME_EVIDENCE = 3
# Ratios remain comparable between a normal deck and a diagnostic pool.
STYLE_SCALE = 4.0

ROLE_PATTERNS = {
    'ramp': r'\badd (?:\{|[a-z0-9 ]*mana)|search your library for [^.]*land',
    'draw': r'\bdraw (?:a|two|three|four|x|\d+|cards equal)',
    'tutor': r'search your library',
    'removal': r'destroy (?:target|all)|exile (?:target|all)|deals? [^.]*damage to',
    'counter': r'counter target [^.]*spell',
    'bounce': r'return target [^.]*to (?:its|their|the) owner',
    'wipe': r'(?:destroy|exile) all|each creature [^.]*damage|damage to each creature',
    'tokens': r'create [^.]*tokens?',
    'graveyard': r'(?:from|in|into) your graveyard|\bmill\b|\bdelirium\b',
    'reanimate': r'return [^.]*from (?:your|a|the) graveyard [^.]*battlefield|put [^.]*from [^.]*graveyard [^.]*battlefield',
    'sacrifice': r'sacrifice (?:a|another|one|two|three|x)|whenever [^.]*dies|whenever you sacrifice',
    'death-payoff': r'whenever [^.]*dies|whenever [^.]*sacrifice|whenever [^.]*leaves the battlefield',
    'lifegain': r'gain [^.]*life|whenever you gain life',
    'voltron': r'\bequip\b|enchanted creature|equipped creature',
    'spellslinger': r'whenever you cast [^.]*spell|whenever [^.]*instant or sorcery|magecraft',
    'cantrip': r'\bdraw a card',
    'flashback': r'\bflashback\b',
    'storm': r'\bstorm\b',
    'landfall': r'\blandfall\b|whenever a land [^.]*enters',
    'land-ramp': r'search your library for [^.]*land',
    'land-cycle': r'landcycling|basic landcycling',
    'proliferate': r'\bproliferate\b',
    'counter-synergy': r'\+1/\+1 counter|[−-]1/[−-]1 counter',
    'poison': r'\binfect\b|\btoxic \d+|poison counter',
    'energy': r'\{e\}|energy counter',
    'vehicles': r'\bcrew\b|\bvehicle\b',
    'stompy': r'power (?:4|5|6) or greater|greater than its base power',
    'anthem': r'(?:creatures|[a-z]+) you control get \+\d+/\+\d+',
    'attack': r'whenever [^.]*attacks?\b|whenever you attack',
    'combat-hit': r'combat damage to (?:a player|an opponent)|deals combat damage',
    'blink': r'exile [^.]*return [^.]*battlefield',
    'clones': r'copy of|as a copy',
    'stax': r"can.t (?:cast|activate|draw|attack)|spells [^.]*cost [^.]*more|can cast only",
    'group-slug': r'each opponent loses|whenever an opponent [^.]*damage',
    'group-hug': r'target opponent draws|each player draws',
    'drain': r'each opponent loses|damage to each opponent|damage to each of your opponents',
    'alt-win': r'you win the game|opponent loses the game',
    'library-win': r'if [^.]*number of cards in your library|if you would draw [^.]*no cards',
    'library-exile': r'exile [^.]*your library',
    'toughness-combat': r'combat damage equal to its toughness|assigns [^.]*damage [^.]*toughness',
}

# All scored families consume actual roles. Unknown catalogue families fall back
# to mechanic evidence, not a growing table of named-card exceptions.
FAMILY_ROLES = {
    'combat': frozenset({'attack', 'combat-hit', 'stompy', 'voltron', 'toughness-combat', 'anthem'}),
    'control': frozenset({'counter', 'removal', 'wipe', 'bounce', 'stax'}),
    'resources': frozenset({'ramp', 'draw', 'tokens', 'vehicles', 'energy'}),
    'graveyard': frozenset({'graveyard', 'reanimate', 'sacrifice', 'death-payoff'}),
    'spells': frozenset({'spellslinger', 'cantrip', 'flashback', 'storm'}),
    'lands': frozenset({'landfall', 'land-ramp', 'land-cycle'}),
    'counters': frozenset({'counter-synergy', 'proliferate', 'poison'}),
}
ALIASES = {'graveyard': 'graveyard', 'sacrifice': 'graveyard', 'midrange': 'resources',
           'aggro': 'combat', 'control': 'control', 'combo': 'combo', 'tempo': 'spells'}


@lru_cache(maxsize=8192)
def rules_text(text: str) -> tuple[str, str]:
    """Separate parenthesized reminder/token definitions from main instructions.

    Kept as separate evidence: a Wicked Role's death trigger is not the source
    spell's own guaranteed table damage. Explicit keywords still count outside
    their reminder text. Nested parentheses are handled without discarding it.
    """
    main, reminder = [], []
    depth = 0
    for char in text.casefold():
        if char == '(':
            depth += 1
        elif char == ')':
            depth = max(0, depth - 1)
        else:
            (reminder if depth else main).append(char)
    return ''.join(main), ''.join(reminder)


@lru_cache(maxsize=8192)
def roles_for(text: str, types: str = '') -> frozenset[str]:
    main, _ = rules_text(text)
    roles = {role for role, pattern in ROLE_PATTERNS.items() if re.search(pattern, main)}
    if 'land' in types.casefold():
        roles.discard('tutor')
    return frozenset(roles)


@dataclass
class Profile(DeckStrategy):
    styles: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, dict] = field(default_factory=dict)
    typal: tuple[str, ...] = ()
    fingerprint: str = ''
    version: int = PROFILE_VERSION
    faces: dict[str, dict] = field(default_factory=dict)


def local_combos(cards, commanders):
    """Use the existing matcher on a strictly read-only initialized snapshot."""
    import logging
    import sqlite3
    from mtg_analyzer.config import COMMANDER_SPELLBOOK_DB_PATH
    from mtg_analyzer.services.commander_spellbook_database import CommanderSpellbookDatabase
    path = COMMANDER_SPELLBOOK_DB_PATH
    if not path.exists():
        return []
    database = CommanderSpellbookDatabase(path)
    try:
        # Pre-open ro so the service's lazy open cannot run schema migrations.
        database._connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        if not database.status()['initialized']:
            return []
        quantities = Counter(c.name for c in cards + commanders)
        return database.matches([{'name': n, 'quantity': q} for n, q in sorted(quantities.items())])
    except (OSError, ValueError, sqlite3.Error) as exc:
        logging.getLogger(__name__).warning('Smart2 combo snapshot unavailable: %s', exc)
        return []
    finally:
        database.close()


def build_profile(cards, commanders, combos=None, archetypes=None, *, named_signals=True):
    """Build immutable-deck prior; never takes a runtime session or library order."""
    if combos is None:
        combos = local_combos(cards, commanders)
    base = build_strategy(cards, commanders, combos=combos, archetypes=archetypes)
    commander_names = {normalize(c.name) for c in commanders}
    plans, evidence, counts, faces = {}, {}, Counter(), {}
    for card in cards + commanders:
        old = CardPlan.from_card(card)
        roles = roles_for(old.text, old.types)
        plans[normalize(card.name)] = CardPlan(old.name, old.text, old.cost, old.mana_value,
                                             old.identity, old.types, roles)
        for face in ('back', 'fuse'):
            other = card.back_face() if face == 'back' else card.fuse_face()
            if other is not None:
                op = CardPlan.from_card(other)
                fp = CardPlan(op.name, op.text, op.cost, op.mana_value, op.identity, op.types, roles_for(op.text,op.types))
                faces[normalize(card.name)+'|'+face] = {'plan':fp,'power':other.power,'toughness':other.toughness,
                    'is_creature':other.is_creature,'is_land':other.is_land}
        main, reminder = rules_text(old.text)
        evidence[normalize(card.name)] = {'roles': sorted(roles), 'main_text': main,
                                        'token_reminder': reminder, 'confidence': 'heuristic', 'power': card.power, 'toughness': card.toughness}
        counts.update({r: COMMANDER_EVIDENCE_WEIGHT if normalize(card.name) in commander_names else 1
                       for r in roles})
    catalogue = default_archetype_database()
    families = set()
    selected = list(archetypes or [])
    # Catalogue patterns corroborate mechanics. Named signals may improve profile
    # labels, never add an action score merely for matching a card's name.
    if not selected:
        votes = []
        for entry in catalogue.all_archetypes():
            vote = sum(any(re.search(p, c.text, re.I) for p in entry.get('synergy_patterns', []))
                       for c in plans.values())
            if named_signals:
                signal = entry.get('signal_cards', {})
                vote += sum(normalize(n) in plans for n in signal.get('core', []))
            if vote >= MIN_THEME_EVIDENCE:
                votes.append((-vote, entry['id']))
        selected = [a for _, a in sorted(votes)[:2]]
    for a in selected:
        entry = catalogue.get(a)
        family = ALIASES.get(a) or (entry or {}).get('philosophy')
        if family:
            families.add(family)
    for family, roles in FAMILY_ROLES.items():
        if sum(counts[r] for r in roles) >= MIN_THEME_EVIDENCE:
            families.add(family)
    # Quantity-weighted denominator, matching the role evidence above.
    nonlands = [plans[normalize(c.name)] for c in cards + commanders
                if 'land' not in plans[normalize(c.name)].types]
    n = max(1, len(nonlands))
    ratio = lambda *rs: min(1.0, sum(counts[r] for r in rs) / n * STYLE_SCALE)
    creatures = [p for p in nonlands if 'creature' in p.types]
    cheap = sum(p.mana_value <= 3 for p in creatures) / n
    styles = {'initiative': min(1.0, cheap * STYLE_SCALE),
              'reactivity': ratio('counter', 'removal', 'bounce'),
              'engine': ratio('death-payoff', 'spellslinger', 'landfall', 'combat-hit'),
              'wide': ratio('tokens'), 'concentrated': ratio('voltron'),
              'graveyard': ratio('graveyard', 'reanimate', 'sacrifice'),
              'spells': ratio('spellslinger', 'cantrip', 'storm'),
              'lands': ratio('landfall', 'land-ramp'), 'counters': ratio('counter-synergy', 'proliferate'),
              'mana': ratio('ramp'), 'draw': ratio('draw'), 'drain': ratio('drain'),
              'poison': ratio('poison'), 'library': ratio('library-win', 'alt-win')}
    quantities = Counter(normalize(c.name) for c in cards + commanders)
    fingerprint = hashlib.sha256(json.dumps([sorted(quantities.items()), sorted(commander_names),
                                sorted(archetypes or []), PROFILE_VERSION,
                                [(c.pieces, c.outputs) for c in base.combos],
                                [(n,p.text,p.cost,p.types) for n,p in sorted(plans.items())]], sort_keys=True).encode()).hexdigest()
    return Profile(cards=plans, quantities=dict(quantities), commanders=frozenset(commander_names),
                   identity=base.identity, archetype=(selected or ['midrange'])[0],
                   archetypes=tuple(selected or ['midrange']), philosophies=tuple(sorted(families)),
                   themes=frozenset(r for r in counts if counts[r] >= MIN_THEME_EVIDENCE),
                   combos=base.combos, styles=styles, evidence=evidence,
                   typal=tuple(s.creature_type for s in detect_typal_signals(cards + commanders)),
                   fingerprint=fingerprint, faces=faces)
