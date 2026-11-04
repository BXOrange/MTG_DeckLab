"""Persist local bug reports with server-owned replay diagnostics."""
from datetime import datetime, timezone
import gzip
import json
import logging
from uuid import uuid4

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from mtg_analyzer.i18n import api_error
from mtg_analyzer import config
from mtg_analyzer.api.dependencies import get_game_session_manager, get_lobby
from mtg_analyzer.api.auth import AuthContext, current_context
from mtg_analyzer.services.bug_report_codec import encode_report
from mtg_analyzer.services.game_session import MULTIPLAYER, GameSession, GameSessionManager, MAX_HISTORY
from mtg_analyzer.services.lobby import Lobby

# Twelve moves usually cover the triggering interaction without a large report.
DEFAULT_ACTION_COUNT = 12
# Bounded by the session's retained undo history.
MAX_ACTION_COUNT = MAX_HISTORY
MAX_DESCRIPTION_LENGTH = 20000  # Enough for detailed reproduction steps.
router = APIRouter(prefix="/api/bug-reports", tags=["bug-reports"])


class BugReportRequest(BaseModel):
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    session_id: str | None = None
    #: BUG-45: the reporter's lobby id; the session account must own it
    #: (PLR-9c) to prove a seat at the table when the session is a multiplayer table.
    player_id: str | None = None
    action_count: int = Field(default=DEFAULT_ACTION_COUNT, ge=1, le=MAX_ACTION_COUNT)
    view: str = Field(default="", max_length=100)

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Please describe the bug")
        return value.strip()


def _reports_dir_full() -> bool:
    """BUG-43: whether the report directory already holds its maximum.

    Reports are the user's own evidence and are never rotated or deleted by
    the app, so a full directory refuses new reports instead.
    """
    try:
        sizes = [p.stat().st_size for p in config.BUG_REPORT_DIR.glob("*.json.gz")]
    except OSError:
        return False
    return len(sizes) >= config.BUG_REPORT_MAX_COUNT or sum(sizes) >= config.BUG_REPORT_MAX_TOTAL_BYTES


def _require_seat_at_table(
    session: GameSession, session_id: str, player_id: Optional[str], ctx: Optional[AuthContext], lobby: Lobby
) -> None:
    """BUG-45: a report stores every hidden zone, so for a lobby table only
    a seated player (the session account owns that seat, PLR-9c) may file it.

    Goldfish, replay and Solo-vs-bots sessions hold no other human's hidden
    information and stay open. Observers are refused: they never see hands.
    A table session whose lobby game is gone cannot be verified, so it is
    refused too. The 403 is identical for every failure.
    """
    if session.mode != MULTIPLAYER or session.solo:
        return
    game = next((g for g in lobby.games() if g.session_id == session_id), None)
    seated = game is not None and player_id is not None and game.seat_for(player_id) is not None
    owner = ctx.account.player_uuid if ctx is not None else None
    if not (seated and lobby.owned_by(player_id, owner)):
        raise api_error(403, "bug_report_needs_seat")


@router.post("", status_code=201)
def create_bug_report(
    request: BugReportRequest,
    sessions: GameSessionManager = Depends(get_game_session_manager),
    lobby: Lobby = Depends(get_lobby),
    ctx: Optional[AuthContext] = Depends(current_context),
) -> dict:
    if _reports_dir_full():
        raise api_error(507, "bug_report_storage_full")
    context = None
    if request.session_id:
        try:
            session = sessions.get(request.session_id)
        except KeyError:
            raise api_error(404, "bug_report_session_gone") from None
        _require_seat_at_table(session, request.session_id, request.player_id, ctx, lobby)
        context = session.bug_report_context(request.action_count)
    now = datetime.now(timezone.utc)
    report_id = f"{now:%Y%m%dT%H%M%S}-{uuid4().hex}"
    report = {
        "format": "mtg-bug-report", "version": 1, "id": report_id,
        "created_at": now.isoformat(), "description": request.description,
        "view": request.view, "session_id": request.session_id,
        "requested_action_count": request.action_count, "game": context,
    }
    report = encode_report(report)
    filename = f"{report_id}.json.gz"
    try:
        config.BUG_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        with gzip.open(config.BUG_REPORT_DIR / filename, "xt", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
    except OSError:
        logging.getLogger(__name__).exception("Could not save bug report")
        raise api_error(500, "bug_report_not_saved") from None
    return {"id": report_id, "filename": filename}
