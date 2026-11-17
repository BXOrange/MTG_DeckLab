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
- **Done:** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <the exact next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <where baselines, dumps and probes live>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PAR-283 · Condition vocabulary

- **Started / last update:** 2026-11-17 / 2026-11-17
- **Goal of this run:** `P1-A Bedingungen` (708 sentences / 675 touched / 280 only at the v923 re-scan; 287 cards whose only open clauses are P1-A): leading and trailing `if`, `unless`. Build the missing predicates once in the shared condition vocabulary (`static_rows/static_conditions.py` `static_condition` + `game/static_conditions.py`), largest clusters first.
- **Ranked table (v923 re-scan, open predicate shapes, sentences / solo cards):** "you do" 156/15 (needs the *preceding* clause, not a predicate: outcome chain `if_you_do_from`, see residue), "you don't" 26/3, "you can't" 16/5, **X thresholds** 8/6 (+17 solo cards with "if x is N or more" in other sentences, probe), **kicked with its {cost} kicker** 12 cards (engine: no per-cost kicker record), **Trap alt-cost conditions** ("if <state>, you may pay {c} rather than pay this spell's mana cost") 33 solo (alt-cost row, own condition vocabulary), referent type phrases ("it's an artifact creature", "that creature was a Human") ~25 cards, "that player ..." phase-trigger gates ~10, "the sacrificed X was Y" ~10 (needs sacrificed-cost LKI reader; `sacrificed_cost_subtype` exists), "you controlled that permanent" 5, "~ is in your graveyard" 6, "your team ..." 3, hand-size comparison 3.
- **Done (milestone 1, PARSER_VERSION 924):** X thresholds (`x_paid`), referent type phrases over card type/supertype/token/any subtype (conjunction and "or"), "that spell was kicked", "that spell's mana value was N or less", "~ wasn't kicked", "~ is in your graveyard", "~ didn't attack this turn", "no creatures are on the battlefield", "your team ..." (= you), "you have more cards in hand than each opponent" (new engine kind `you_have_most_cards_in_hand`). Masked diff vs fresh v923 baseline: 64 gained, 0 lost, 10 already-MODELED cards change repr, 8 key-order only, Boneyard Scourge / Furious Forebear gain the `source_in_graveyard` gate (verified executing). Tests `backend/tests/test_par283_condition_vocabulary.py`.
- **Done (milestone 2, PARSER_VERSION 925):** "if that player ..." on per-player phase triggers through the new `as_active_player` combinator (+7: Ebony Owl Netsuke, Misers' Cage, Razor Pendulum, Rivalry, Impatience, Predatory Advantage, Spiritual Sanctuary; 0 lost, 0 changed vs m1). `where_x_threshold_body` declines an unreadable "where X is ..." threshold instead of letting the announced-X reading claim it. Full suite green (23505 passed, 505 skipped); no `--full-cache` run.
- **In progress:** nothing; coherent stop.
- **Next step:** (1) "the sacrificed X was Y" / "the discarded card was a Z" (Falkenrath Aristocrat/Torturer, Gríma Wormtongue, Evereth, Foundry Helix, Hellish Sideswipe, Splitting the Powerstone, Boneyard Desecrator, Thallid Omnivore, Necromancer's Stockpile): `sacrificed_cost_subtype` exists in `effect_conditions`, widen to card type/supertype/token and add the parser row. (2) Trap alt-cost conditions (33 solo, see residue). (3) "you controlled that permanent/creature" (Boomerang Basics, Gleeful Demolition, Kellan, Hotshot Investigators, Dreamdew Entrancer): needs the picked object's controller as last-known info.
- **Decisions:** fail closed (unknown predicate never holds); every new predicate kind has an engine reader; "it's <type phrase>" contraction leaves `of` off (source in a static, rescoped to the pick by `peel_condition`); "it's a creature card" stays with the library-card route (BUG-68); pytest `--full-cache` only at close if the ticket splits (owner rule).
- **Baselines / artefacts:** scratchpad `par283/base923.json` (masked baseline), `m1.json` / `m2.json` (milestones 1/2), scan `backend/data/exports/offene-fragmente-2026-11-17-v923-vollpool-*`.
- **Known failures:** -
- **Residue (ranked, v923 scan minus milestones):** (a) "if you do / you don't / you can't / they do" 200+ sentences, not predicates: the *preceding* optional/cost clause is what stays unclaimed (Akuta, Act of Authority, Egon, Eldrazi Monument, Woebringer Demon, Urgoros), needs the outcome-chain (`if_you_do_from`) widened per antecedent verb; (b) Trap alt-cost conditions 33 solo (Archive/Baloth Cage/Lavaball/Needlebite/Nemesis/Ravenous/Ricochet/Runeflare/Slingbow/Summoning/Whiplash/Pitfall Trap, Mine Collapse, Blasphemous Edict): the alt-cost row's `condition` takes a closed key set (`ALLOWED_FREE_CAST_CONDITION_KEYS`), would need the shared vocabulary there plus per-turn opponent tallies; (c) "it was kicked with its {cost} kicker" 12 cards (Battlemage cycle, Anavolver cycle): engine records one Kicker cost only (`_kicker_cost`), needs a per-cost kicker record = MEC decision; (d) "the sacrificed X was Y" ~10 (next step 1); (e) "you controlled that permanent" 5; (f) "this card is suspended" 3, "this ability has been activated N or more times this turn" 2 (activation count, not resolution count), "a dragon was beheld" 2, "you have the windy city's blessing" 3 (designation), "there is no monarch"/"an opponent is the monarch" 4 (kinds exist, no parser row), "defending player controls no X / is poisoned / has N or fewer cards" ~9 attack-trigger gates (`defending_player` subject), "it has madness", "it entered from your graveyard or you cast it from", number words above ten ("thirty or more artifacts"), "you have N or more cards in your library", "exactly N life".
