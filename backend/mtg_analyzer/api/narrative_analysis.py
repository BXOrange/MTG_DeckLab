"""ANA-1: narrative analysis for a saved deck, alongside static analysis."""
from collections import Counter
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from typing import Literal

from mtg_analyzer.api.dependencies import get_deck_database, get_lazy_card_loader
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.services.bot_strategy import build_strategy
from mtg_analyzer.services.llm_client import LLMError
from mtg_analyzer.services.narrative_analysis import default_narrative_analysis

router = APIRouter(prefix='/api/decks', tags=['analysis'])


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    force: bool = False
    language: Literal['de', 'en'] = 'de'


def _source(deck):
    return (deck.commander_text, deck.mainboard_text, deck.sideboard_text, deck.archetypes)


@router.post('/{deck_id}/analyze')
def analyze(deck_id: str, request: AnalyzeRequest = AnalyzeRequest(),
            decks=Depends(get_deck_database), loader=Depends(get_lazy_card_loader),
            service=Depends(default_narrative_analysis)):
    deck = decks.get_deck(deck_id)
    if deck is None:
        raise HTTPException(404, 'Deck not found')
    source = _source(deck)
    parsed = parse_deck_sections(deck.commander_text, deck.mainboard_text, deck.sideboard_text)
    if parsed.parse_errors:
        raise HTTPException(422, {"message": "Decklist could not be parsed", "errors": parsed.parse_errors})
    entries = parsed.all_cards + parsed.sideboard
    loaded = loader.load_cards(list(dict.fromkeys(e.name for e in entries)))
    if loaded.not_found:
        raise HTTPException(422, {'message': 'Cards could not be resolved', 'notFound': loaded.not_found})
    counts = Counter()
    for entry in entries:
        counts[entry.name] += entry.qty
    cards = [loaded.cards[e.name] for e in parsed.main_deck for _ in range(e.qty)]
    commanders = [loaded.cards[e.name] for e in parsed.commanders for _ in range(e.qty)]
    strategy = build_strategy(cards, commanders)
    payload = {'language': request.language, 'commander_text': deck.commander_text,
               'mainboard_text': deck.mainboard_text, 'sideboard_text': deck.sideboard_text,
               'selected_archetypes': deck.archetypes or [], 'colour_identity': sorted(strategy.identity),
               'cards': [{'name': loaded.cards[name].name, 'quantity': quantity,
                          'oracle_text': loaded.cards[name].oracle_text or '',
                          'mana_cost': loaded.cards[name].mana_cost_string or '',
                          'type_line': loaded.cards[name].type_line} for name, quantity in counts.items()],
               'matched_combos': [{'pieces': c.pieces, 'outputs': c.outputs} for c in strategy.combos]}
    try:
        record = service.analyze(deck_id, payload, force=request.force)
    except LLMError as exc:
        raise HTTPException(503, str(exc)) from None
    # Do not overwrite unrelated changes made while the provider was working.
    latest = decks.get_deck(deck_id)
    if latest is not None and _source(latest) == source:
        latest.analysis_id = record['id']
        decks.save_deck(latest)
    return record


@router.get('/{deck_id}/analysis')
def cached_analysis(deck_id: str, decks=Depends(get_deck_database), service=Depends(default_narrative_analysis)):
    deck = decks.get_deck(deck_id)
    if deck is None:
        raise HTTPException(404, 'Deck not found')
    result = service.database.get(deck.analysis_id) if deck.analysis_id else None
    if result is None or result['deck_id'] != deck_id:
        raise HTTPException(404, 'No current narrative analysis')
    return result | {'cached': True}
