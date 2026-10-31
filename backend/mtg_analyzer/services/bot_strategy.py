"""Deck knowledge for Smart Bot, never runtime hidden-zone knowledge.

Built from the supplied deck before play. Spellbook is read only when a local
snapshot exists; starting a game never downloads combo data. Strategies are
heuristics, not proof that a combo can currently resolve or win.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import logging
import re
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


def normalize(name: str) -> str:
    return ' '.join(name.casefold().split())


#: Coloured (and colourless) mana symbols a printed cost can require.
COST_COLOURS = 'WUBRGC'


def cost_requirements(cost: str) -> tuple[Counter, int]:
    """``({colour: pips}, generic)`` of a printed cost such as ``{2}{G}{U}``.

    ``{X}`` counts as 0 and any other symbol (hybrid, Phyrexian, snow) as one
    generic mana: a cheap lower bound that only ever errs towards "payable",
    which is what a pre-check before the engine's own validation needs.
    """
    pips: Counter = Counter()
    generic = 0
    for symbol in re.findall(r'\{([^}]*)\}', cost or ''):
        if symbol in COST_COLOURS:
            pips[symbol] += 1
        elif symbol.isdigit():
            generic += int(symbol)
        elif symbol != 'X':
            generic += 1
    return pips, generic


ROLE_PATTERNS = {
    'ramp': r'add (?:\{|.*mana)|search your library for .*land',
    'draw': r'draw (?:a|two|three|four|x|\d+) cards?',
    'tutor': r'search your library',
    'removal': r'destroy target|exile target|deals? .*damage to',
    'counter': r'counter target .*spell',
    'tokens': r'create .*tokens?',
    'graveyard': r'from your graveyard|in your graveyard|mill ',
    'sacrifice': r'sacrifice (?:a|another|one)|whenever .*dies',
    'lifegain': r'gain .*life|whenever you gain life',
    'voltron': r'equip|enchanted creature|equipped creature',
    'spellslinger': r'whenever you cast .*instant|whenever you cast .*sorcery|noncreature spell',
    'poison': r'infect|toxic \d+|poison counter|corrupted|proliferate',
    'group-slug': r'each player loses|whenever a player|whenever an opponent casts|whenever a land is tapped',
    'stompy': r'power 4 or greater|power 5 or greater|greater than its base power',
    'vehicles': r'crew \d+|vehicle',
    'energy': r'pay \{e\}|get \{e\}|energy counter',
    'cascade': r'cascade|discover \d+',
    'clones': r'copy of target|token that\'s a copy|as a copy of',
    'wincon': r'you win the game|opponent loses the game|each opponent loses|each opponent.*damage|creatures you control get \+\d+/\+\d+|trample.*until end of turn',
}


@dataclass(frozen=True)
class CardPlan:
    name: str
    text: str
    cost: str
    mana_value: float
    identity: frozenset[str]
    types: str
    roles: frozenset[str]

    @classmethod
    def from_card(cls, card: Any) -> 'CardPlan':
        text = (card.oracle_text or '').casefold()
        types = card.type_line.casefold()
        roles = frozenset(role for role, pattern in ROLE_PATTERNS.items() if re.search(pattern, text))
        if 'land' in types:
            # A fetch land searches the library but is not a tutor: the role
            # would add the tutor bonus to every land activation and discard.
            roles -= {'tutor'}
        return cls(card.name, text, card.mana_cost_string or '',
                   float(card.converted_mana_cost or 0), frozenset(card.color_identity or ()),
                   types, roles)


@dataclass(frozen=True)
class ComboPlan:
    pieces: tuple[tuple[str, int], ...]
    outputs: tuple[str, ...] = ()


ARCHETYPE_PHILOSOPHIES = {
    # combat
    'aggro': 'combat', 'stompy': 'combat', 'voltron': 'combat', 'extra-combats': 'combat',
    'flying': 'combat', 'defender': 'combat', 'deathtouch': 'combat', 'mutate': 'combat',
    # control
    'control': 'control', 'stax': 'control', 'hatebears': 'control', 'pillowfort': 'control',
    'group-hug': 'control', 'group-slug': 'control', 'goad': 'control', 'monarch': 'control',
    'dungeon': 'control', 'theft': 'control', 'wheels': 'control', 'flash': 'control',
    # combo
    'combo': 'combo', 'burn': 'combo', 'lifegain': 'combo', 'blink': 'combo',
    'superfriends': 'combo', 'legendary-matters': 'combo', 'sagas': 'combo', 'morph': 'combo', 'chaos': 'combo',
    # resources
    'artifacts-matter': 'resources', 'tokens': 'resources', 'treasure': 'resources', 'food': 'resources',
    'clues': 'resources', 'vehicles': 'resources', 'energy': 'resources', 'equipment': 'resources',
    'auras': 'resources', 'enchantress': 'resources', 'snow': 'resources',
    # graveyard
    'aristocrats': 'graveyard', 'reanimator': 'graveyard', 'graveyard-recursion': 'graveyard',
    'madness': 'graveyard', 'pod': 'graveyard', 'mill': 'graveyard', 'cycling': 'graveyard',
    # spells
    'spellslinger': 'spells', 'spells-matter-cantrips': 'spells', 'storm': 'spells', 'cascade': 'spells',
    'clones': 'spells', 'polymorph': 'spells', 'extra-turns': 'spells',
    # lands
    'landfall': 'lands', 'ramp': 'lands', 'land-destruction': 'lands',
    # counters
    'plus1-counters': 'counters', 'proliferate': 'counters', 'poison': 'counters'
}


@dataclass
class DeckStrategy:
    cards: dict[str, CardPlan] = field(default_factory=dict)
    quantities: dict[str, int] = field(default_factory=dict)
    commanders: frozenset[str] = frozenset()
    identity: frozenset[str] = frozenset()
    archetype: str = 'midrange'
    archetypes: tuple[str, ...] = ('midrange',)
    philosophies: tuple[str, ...] = ('midrange',)
    themes: frozenset[str] = frozenset()
    combos: tuple[ComboPlan, ...] = ()


def build_strategy(cards: list[Any], commanders: list[Any], combos=None,
                   archetypes: tuple[str, ...] | list[str] | None = None) -> DeckStrategy:
    plans = [CardPlan.from_card(c) for c in cards + commanders]
    counts = Counter(normalize(c.name) for c in plans)
    if combos is None:
        # Read a local snapshot only. Do not make network availability a
        # prerequisite for starting a bot game.
        from mtg_analyzer.services.commander_spellbook_database import CommanderSpellbookDatabase
        database = CommanderSpellbookDatabase()
        try:
            combos = database.matches([{'name': p.name, 'quantity': counts[normalize(p.name)]}
                                       for p in {normalize(p.name): p for p in plans}.values()]) \
                if database.status()['initialized'] else []
        except (OSError, ValueError, sqlite3.Error) as exc:
            logger.warning('Smart Bot could not read local combo snapshot: %s', exc)
            combos = []
        finally:
            database.close()
    combo_plans = []
    for combo in combos:
        if combo.get('requirements'):
            continue  # unresolved template predicates are not verified deck ingredients
        ingredients = Counter()
        for use in combo.get('uses', []):
            ingredients[normalize(use['name'])] += int(use.get('quantity', 1))
        pieces = tuple(sorted(ingredients.items()))
        if pieces and all(counts[n] >= q for n, q in pieces):
            combo_plans.append(ComboPlan(pieces, tuple(combo.get('produces') or ())))
    # An engine-supported recipe remains usable without a downloaded
    # snapshot. Only include it when both actual ingredients are in the deck.
    oracle_recipe = (("thassa's oracle", 1), ('demonic consultation', 1))
    if all(counts[n] >= q for n, q in oracle_recipe):
        if not any(set(dict(c.pieces)) == set(dict(oracle_recipe)) for c in combo_plans):
            combo_plans.append(ComboPlan(oracle_recipe, ('Win the game',)))
    weights = Counter()
    commander_names = frozenset(normalize(c.name) for c in commanders)
    for p in plans:
        for role in p.roles:
            weights[role] += 3 if normalize(p.name) in commander_names else 1
    themes = frozenset(r for r in ('tokens', 'graveyard', 'sacrifice', 'lifegain', 'voltron',
                                  'spellslinger', 'poison', 'group-slug', 'stompy',
                                  'vehicles', 'energy', 'cascade', 'clones')
                       if weights[r] >= 3)
    identity = frozenset(c for p in plans for c in p.identity)
    creatures = [p for p in plans if 'creature' in p.types]
    nonlands = [p for p in plans if 'land' not in p.types]

    if archetypes:
        final_archetypes = tuple(archetypes[:2])
        primary = final_archetypes[0] if final_archetypes else 'midrange'
    else:
        found = []
        if combo_plans:
            found.append('combo')
        sorted_themes = sorted(themes, key=lambda r: weights[r], reverse=True)
        for t in sorted_themes:
            if t not in found:
                found.append(t)
                if len(found) >= 2:
                    break
        if len(found) < 2:
            if weights['counter'] + weights['removal'] >= max(4, len(nonlands) * .3):
                if 'control' not in found:
                    found.append('control')
            elif creatures and len(creatures) >= len(nonlands) * .5 and sum(p.mana_value for p in creatures) / len(creatures) <= 3:
                if 'aggro' not in found:
                    found.append('aggro')
            elif 'G' in identity and weights['ramp'] >= 5:
                if 'ramp' not in found:
                    found.append('ramp')
        if not found:
            found.append('midrange')
        primary = found[0]
        final_archetypes = tuple(found[:2])

    philosophies = tuple(sorted(set(ARCHETYPE_PHILOSOPHIES.get(a, 'midrange') for a in final_archetypes)))
    return DeckStrategy({normalize(p.name): p for p in plans}, dict(counts), commander_names, identity,
                        primary, final_archetypes, philosophies, themes, tuple(combo_plans))
