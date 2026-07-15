# Documentation map

This folder holds *developer/design* documentation, organized by what kind
of question it answers. If you want to know how to *use* the app instead
(deck import, Goldfisch, Replay/Puzzle, settings, …), see
[`../user-docs/`](../user-docs/) — that's separate on purpose, aimed at
players rather than contributors.

| Folder | Answers | Contents |
| --- | --- | --- |
| [`requirements/`](requirements/) | *What is this app supposed to do?* | Use cases, actors, functional/non-functional requirements, the MVP cut. |
| [`concepts/`](concepts/) | *How is it designed, and why?* | Architecture, the server/client split, the game/effect system, the UI/UX design, card graphics & caching, the oracle-text→effect parser design, and the [PlantUML architecture diagrams](concepts/12_ARCHITECTURE_DIAGRAMS.md). |
| [`Reference/`](Reference/) | *How do I do a specific recurring task, or look something up?* | The card-cache export/import format, the card-catalogue authoring guide (hand-wiring a card's abilities), the Comprehensive Rules text itself, and `rules_wiki/` (a generated index mapping every `RULE <n>`/glossary term to its line in the CR source — see its own `README.md`). |
| [`implementation-state/`](implementation-state/) | *What's actually built, right now?* | The dependency-ordered completion roadmap, `Done_Backend.md`/`Done_Frontend.md` (shipped work, with the "why"), the original phased build guide, and the archived Weeks 1–4 status log. |

## Where "implementation state" actually lives

`implementation-state/10_COMPLETION_ROADMAP.md` is the **synthesized**
status (milestones, CR-area coverage table) — start there. It reconciles
sources that it doesn't duplicate, so check those directly for the
finest-grained/most current detail:

- Granular **open** items: [`../backend/ToDo_Backend.md`](../backend/ToDo_Backend.md),
  [`../frontend/ToDo_Frontend.md`](../frontend/ToDo_Frontend.md) — these two
  stay next to the code they track (not under `docs/`) since they're living
  backlogs edited alongside nearly every change; moving them would make
  them easy to forget mid-change.
- **Shipped** work, with the "why": [`implementation-state/Done_Backend.md`](implementation-state/Done_Backend.md),
  [`implementation-state/Done_Frontend.md`](implementation-state/Done_Frontend.md)
  — these *do* live under `docs/`, since they're append-only history rather
  than something edited in lockstep with in-progress code.
- Narrow, deliberately-unhandled **edge cases** of an already-shipped
  feature (as opposed to a large open feature, which stays in the ToDo files
  above): [`implementation-state/ToDo_EdgeCases.md`](implementation-state/ToDo_EdgeCases.md)
  — a cross-cutting index, not a replacement for the ToDo/Done files' own
  in-situ mentions.
- User-facing engine coverage: the in-app **Engine-Status** tab
  (`../frontend/src/js/implementationStatusView.js`)

## Orientation

- [`../CLAUDE.md`](../CLAUDE.md) — the top-level orientation doc (start
  here first if you're new to the repo); it links into all of the above.
