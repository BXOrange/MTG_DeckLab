# Documentation map

This folder holds *developer/design* documentation, organized by what kind
of question it answers. If you want to know how to *use* the app instead
(deck import, Goldfisch, Replay/Puzzle, settings, …), see
[`../user-docs/`](../user-docs/) — that's separate on purpose, aimed at
players rather than contributors.

| Folder | Answers | Contents |
| --- | --- | --- |
| [`requirements/`](requirements/) | *What is this app supposed to do?* | Use cases, actors, functional/non-functional requirements, the MVP cut. |
| [`concepts/`](concepts/) | *How is it designed, and why?* | Architecture, the server/client split, the game/effect system, the UI/UX design, card graphics & caching, the oracle-text→effect parser design, the [PlantUML architecture diagrams](concepts/12_ARCHITECTURE_DIAGRAMS.md), and — on the parser's structure — the [granularity/composition review](concepts/13_ORACLE_PARSER_GRAMMAR_REVIEW.md) (evidence) plus the [atom/composition design](concepts/14_PARSER_GRAMMAR_DESIGN.md) (proposal, not implemented). |
| [`Reference/`](Reference/) | *How do I do a specific recurring task, or look something up?* | The card-cache export/import format, the card-catalogue authoring guide (hand-wiring a card's abilities), the Comprehensive Rules text itself, and `rules_wiki/` (a generated index mapping every `RULE <n>`/glossary term to its line in the CR source — see its own `README.md`). |
| [`implementation-state/`](implementation-state/) | *What's actually built, right now?* | The dependency-ordered completion roadmap, `Done_Backend.md`/`Done_Frontend.md` (shipped work, with the "why"), and the original phased build guide. |

## Where "implementation state" actually lives

`implementation-state/10_COMPLETION_ROADMAP.md` is the **synthesized**
status (milestones, CR-area coverage table) — start there. It reconciles
sources that it doesn't duplicate, so check those directly for the
finest-grained/most current detail:

- Granular **open** items: [`implementation-state/BACKLOG.md`](implementation-state/BACKLOG.md)
  — one categorized ticket list covering backend *and* frontend (ids
  `ENG`/`PAR`/`MEC`/`PLR`/`VIS`/`DB`/`ANA`/`BUG`). Open scope only: closing
  a ticket means deleting it here and filing its narrative into the
  matching subsystem entry of the matching `Done_*.md` catalogue.
- **In progress**: [`implementation-state/workingOn.md`](implementation-state/workingOn.md)
  — working memory of the ticket being built right now (done / next step /
  decisions), so a new session resumes instead of re-deriving the state.
  Emptied back to its template when the ticket closes.
- **Examples / calibration**: [`implementation-state/PARSER_LONG_TAIL.md`](implementation-state/PARSER_LONG_TAIL.md)
  — the standing strategy for the indefinite oracle-parser tail, the
  recurring lessons, and enumerated worked samples. Neither a backlog nor a
  worklog.
- **Shipped** work, with the "why": [`implementation-state/Done_Backend.md`](implementation-state/Done_Backend.md),
  [`implementation-state/Done_Frontend.md`](implementation-state/Done_Frontend.md)
  — catalogues organized by game-mechanic/app-area rather than
  chronologically; these *do* live under `docs/` since they're durable
  reference rather than something edited in lockstep with in-progress code.
- User-facing engine coverage: the in-app **Engine-Status** tab
  (`../frontend/src/js/implementationStatusView.js`)

## Orientation

- [`../CLAUDE.md`](../CLAUDE.md) — the top-level orientation doc (start
  here first if you're new to the repo); it links into all of the above.
