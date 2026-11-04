# Working on — resumable state of the ticket in progress

**The working memory for a ticket that is being built right now.** It exists so that a
new session — after the prompt cache expired, a crash, an update, a context compaction —
continues exactly where the last one stopped instead of re-deriving the state from the
code, the git log and the backlog.

Rules:

- **Read this file first** when you start or resume work on any ticket. If your ticket has
  a block below, continue from its *Next step*; do not re-evaluate what it records as done.
- **One block per ticket in progress**, headed `## <TICKET-ID> · <title>`. Several sessions
  may share this working tree, so never edit another ticket's block.
- **A partly done ticket's residue lives here, not in `BACKLOG.md`.** When a run ends with
  part of the ticket still open, keep its block and record under *Residue* exactly what is
  left (card clusters, blockers, which cards each needs) plus the *Next step*; `BACKLOG.md`
  keeps only the ticket's terse open point (id, title, one-clause scope).
- **Update the block at every milestone**, not only at the end: after a sub-step is built
  and tested, after a decision, before a long-running command (full test tier, coverage
  run), before a commit. Write it so a reader with *no* conversation context can act on it.
- Keep it terse and current — replace stale lines instead of appending. Keep only
  the current resumable state; session logs belong in unversioned temporary files.
- **Commit every iteration** (each green milestone: sub-step built + tested), not only at
  ticket close; update the block first so the commit carries the current state. Stage only
  your own files (see the shared-tree note in memory), never `git stash`.
- **On closing the ticket, delete its whole block.** Durable results for shared
  engine/parser features belong in `Done_Backend.md` / `Done_Frontend.md`;
  individually modeled cards stay documented in their implementations and tests,
  not in `Done_Backend.md`. A ticket is closed only once its residue is done too.
  With no ticket in progress this file is just this header and the empty template
  — no ticket id, no log.

Block template (do not change this, copy below the line, fill in there):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## VIS-24 · Localized server messages

- **Started / last update:** 2026-11-04 / 2026-11-04 (milestone 1 committed)
- **Goal of this run:** full VIS-24.
- **Done (built + tested):** `backend/mtg_analyzer/i18n/` (catalogue de/en ~130 codes, `message`, `resolve_lang`, `api_error`, `error_from`, `LocalizedError`); `api/errors.py` handler adds `message` to every `{"code"}` detail; all plain-string `HTTPException`s in `api/` converted (138 sites inventoried: ~50 plain text, ~50 code-only, 8 composite 422 bodies, rest engine passthrough); `LobbyError`/`AssetQuotaError`/`ArchidektFetchError` now `LocalizedError`; WS `disconnected` frames carry `message`, `error` frames `code`+`message`; frontend `serverError.js` (`serverErrorText`) used by goldfish/solo/replay/board/multiplayer/analysis/api.js, `accountView` falls back to server message, `lobbySocket` passes the server message. Tests: `tests/services/test_server_message_catalogue.py`, `tests/api/test_api_server_messages.py`, additions in queue/multiplayer/identity tests. Docs: OPERATIONS.md "Server messages". Playwright (temp data dirs, both languages) OK, ESLint + i18n-verify OK.
- **In progress:** milestone 2 (residue below).
- **Next step:** give deck-legality / validation results codes + params (`commander_legality.py`, `deck_validation.py`, `api/game.py` `resolve_seat_deck`) and catalogue the `services/game_session.py` refusals (own `ValueError`/`GameActionError` texts, ~59); engine `game/` texts stay `action_rejected` passthrough (outside ticket scope).
- **Decisions:** engine/`game_session` refusals pass through as `action_rejected` with their English text (not catalogued). Text/plain guard/proxy rejects (`request_guard`, `frontend_proxy`) stay English (operator diagnostics).
- **Baselines / artefacts:** HEAD c052c5bf; baseline 19025 passed; milestone 1: 19066 passed, 489 skipped (orchestrator rerun).
- **Known failures (corrected; final full-cache recheck pending):** -
- **Residue:** German deck-legality texts (`commander_legality.py`, `deck_validation.py`, `api/game.py` `resolve_seat_deck` errors) are data lists inside validation results, not yet catalogued; `game_session` ValueError/GameActionError texts untranslated; admin UI stays German with its own map.
