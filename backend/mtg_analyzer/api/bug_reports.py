"""Persist local bug reports with server-owned replay diagnostics."""
from datetime import datetime, timezone
import gzip
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from mtg_analyzer import config
from mtg_analyzer.api.dependencies import get_game_session_manager
from mtg_analyzer.services.bug_report_codec import encode_report
from mtg_analyzer.services.game_session import GameSessionManager, MAX_HISTORY

# Twelve moves usually cover the triggering interaction without a large report.
DEFAULT_ACTION_COUNT = 12
# Bounded by the session's retained undo history.
MAX_ACTION_COUNT = MAX_HISTORY
MAX_DESCRIPTION_LENGTH = 20000  # Enough for detailed reproduction steps.
router = APIRouter(prefix="/api/bug-reports", tags=["bug-reports"])


class BugReportRequest(BaseModel):
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    session_id: str | None = None
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


@router.post("", status_code=201)
def create_bug_report(
    request: BugReportRequest,
    sessions: GameSessionManager = Depends(get_game_session_manager),
) -> dict:
    if _reports_dir_full():
        raise HTTPException(
            507, "Bug-report storage is full; please archive or delete old reports in the bug-reports folder"
        )
    context = None
    if request.session_id:
        try:
            session = sessions.get(request.session_id)
        except KeyError:
            raise HTTPException(404, "Game session no longer exists") from None
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
        raise HTTPException(500, "Could not save bug report; please try again") from None
    return {"id": report_id, "filename": filename}
