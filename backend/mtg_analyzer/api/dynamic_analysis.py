"""ANA-4: run N headless goldfish matches as a background job and poll it.

* ``POST /api/analysis/dynamic``           — resolve a deck (same gate as
                                              `api/game.py`'s goldfish
                                              start), start the simulation
                                              job, return its id.
* ``GET  /api/analysis/dynamic/{job_id}``  — state (queued/running/done/failed/
                                              cancelled), queue position,
                                              progress, result.
* ``DELETE /api/analysis/dynamic/{job_id}`` — cancel a queued/running job (owner only).

A start is queued (ANA-6); a full queue answers 503 ``analysis_queue_full``,
an owner at their pending limit 429 ``analysis_owner_limit``, both with
``Retry-After`` — never by evicting another job.

Reference: docs/implementation-state/BACKLOG.md "ANA-4",
mtg_analyzer/services/dynamic_analysis.py.
"""

from __future__ import annotations

from mtg_analyzer.i18n import api_error
from mtg_analyzer import config
from fastapi import APIRouter, Depends

from mtg_analyzer.api.viewer import Viewer, play_viewer, viewer
from mtg_analyzer.api.dependencies import get_deck_database, get_dynamic_analysis_jobs, get_lazy_card_loader
from mtg_analyzer.api.game import expand_entries
from mtg_analyzer.api.schemas import DynamicAnalysisRequest
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.services.bots import BOT_TYPES
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.deck_validation import apply_legality
from mtg_analyzer.services.dynamic_analysis import DynamicAnalysisJobs
from mtg_analyzer.services.job_runner import REFUSAL_OWNER_LIMIT, QueueRefused
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post("/dynamic")
def start_dynamic_analysis(
    request: DynamicAnalysisRequest,
    jobs: DynamicAnalysisJobs = Depends(get_dynamic_analysis_jobs),
    decks: DeckDatabase = Depends(get_deck_database),
    loader: LazyCardLoader = Depends(get_lazy_card_loader),
    who: Viewer = Depends(play_viewer),
) -> dict[str, str]:
    """Resolve the deck exactly like `POST /api/game/goldfish` does, then
    hand it to a background simulation job."""
    if request.bot_kind not in BOT_TYPES:
        raise api_error(422, "unknown_bot_kind", kind=request.bot_kind)

    commander_text = request.commander_text
    mainboard_text = request.mainboard_text
    sideboard_text = request.sideboard_text
    favorite_cards = request.favorite_cards

    if request.deck_id:
        deck = decks.get_readable(request.deck_id, who.player_uuid)
        if deck is None:
            raise api_error(404, "deck_not_found", deck_id=request.deck_id)
        commander_text = deck.commander_text
        mainboard_text = deck.mainboard_text
        sideboard_text = deck.sideboard_text
        if not favorite_cards:
            favorite_cards = deck.favorite_cards or []

    parsed = parse_deck_sections(commander_text, mainboard_text, sideboard_text)
    resolved = loader.load_cards([e.name for e in parsed.commanders] + [e.name for e in parsed.all_cards])
    apply_legality(parsed, resolved)

    library, missing_lib = expand_entries(parsed.main_deck, resolved.cards)
    commanders, missing_cmd = expand_entries(parsed.commanders, resolved.cards)
    missing = sorted(set(missing_lib) | set(missing_cmd) | set(resolved.not_found))

    if not parsed.validation.is_legal:
        raise api_error(
            422,
            "deck_not_legal_simulation",
            errors=parsed.validation.errors,
            validation=parsed.validation.to_dict(),
            notFound=missing,
        )
    if not library and not commanders:
        raise api_error(422, "deck_no_resolvable_cards", notFound=missing)

    try:
        job_id = jobs.start(
            library,
            commanders,
            bot_kind=request.bot_kind,
            opponent_count=request.opponent_count,
            num_matches=request.num_matches,
            max_turns=request.max_turns,
            starting_life=request.starting_life,
            starting_hand=request.starting_hand,
            game_format=request.game_format,
            owner=who.owner,
            favorite_card_names=set(favorite_cards),
            combo_specs=[
                {
                    "id": combo.id,
                    "uses": [
                        {"name": use.name, "quantity": use.quantity}
                        for use in combo.uses
                    ],
                }
                for combo in request.combos
            ],
        )
    except QueueRefused as refusal:
        owner_limit = refusal.code == REFUSAL_OWNER_LIMIT
        raise api_error(
            429 if owner_limit else 503,
            refusal.code,
            headers={"Retry-After": str(config.DYNAMIC_ANALYSIS_RETRY_AFTER_SECONDS)},
        ) from refusal
    return {"jobId": job_id}


@router.get("/dynamic/{job_id}")
def get_dynamic_analysis_job(
    job_id: str,
    jobs: DynamicAnalysisJobs = Depends(get_dynamic_analysis_jobs),
    who: Viewer = Depends(viewer),
) -> dict[str, object]:
    # PLR-9b: a job's result is derived from the starter's (possibly private) deck.
    job = jobs.get(job_id)
    if job is None or not who.owner or job.owner != who.owner:
        raise api_error(404, "analysis_job_not_found", job_id=job_id)
    return jobs.view(job)


@router.delete("/dynamic/{job_id}")
def cancel_dynamic_analysis_job(
    job_id: str,
    jobs: DynamicAnalysisJobs = Depends(get_dynamic_analysis_jobs),
    who: Viewer = Depends(viewer),
) -> dict[str, object]:
    """Cancel a queued or running job; a finished job is returned unchanged."""
    job = jobs.cancel(job_id, who.owner) if who.owner else None
    if job is None:
        raise api_error(404, "analysis_job_not_found", job_id=job_id)
    return jobs.view(job)
