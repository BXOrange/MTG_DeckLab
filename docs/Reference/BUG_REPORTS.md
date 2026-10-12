# Local bug reports

Moved out of CLAUDE.md. Load when asked to analyze a bug report.

The bug icon beside Settings opens a report dialog. `POST /api/bug-reports`
saves gzip-compressed UTF-8 JSON (`.json.gz`, report version 2) in the Git-ignored **`bug-reports/`** directory at the repo
root (override: `MTG_BUG_REPORT_DIR` or config.json `paths.bug_report_dir`).
Reports include the description, originating view, session mode, current
portable replay and diagnostic state, plus the last **12 actions** by default
(user-selectable up to the retained history limit). Each retained action has
its label, actor, step cursor, pre-action replay and diagnostic state. Reports
outside a game have `game: null`. Files contain hidden game zones and are local
user data; do not commit them or delete them without an explicit request.

Report v2 stores card descriptors once (content-keyed variants preserve tokens,
transforms and copies) and one chronological base position plus lossless deltas
for subsequent pre-action positions and the current position. These are storage
changes only; gameplay HTTP/WebSocket views are unchanged. Read both legacy v1
JSON and v2 gzip reports with `services.bug_report_codec.load_report(path)`.
To expand for inspection, run from the repo root:
`PYTHONPATH=backend backend/venv/bin/python -m mtg_analyzer.services.bug_report_codec bug-reports/<id>.json.gz /tmp/mtg-report-expanded.json`
(the destination must not already exist).

When asked to analyze a bug report, inspect this folder (or its configured
location), expand it with the codec and start with `description` and
`game.recent_actions` in chronological order. Extract `game.replay` or an
entry's `replay_before` into a temporary JSON file to import in Replay mode.
Use `state`/`state_before` to inspect stack, pending choices and other diagnostic
context. Portable Replay restores an editable board, not every runtime engine
continuation; do not assume it faithfully reproduces a pending stack/choice.
Action labels are descriptive, not executable action payloads. Reproduce the
reported interaction, consult the Rules-Wiki when rules are involved, and add
an appropriate regression test before fixing it. Keep investigation notes
in temporary unversioned files; record only verified lasting conclusions in
project documentation. Preserve the original report.
