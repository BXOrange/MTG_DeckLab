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
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-208 · Clause separators and outcome chains

- **Started / last update:** 2026-10-27 / 2026-10-27
- **Goal of this run:** first measurable slice on top of PAR-204's `pay_cost_then`/`may_effect_then` and PAR-207's `seq.if_you_do_from`; no second chain mechanism.
- **Done (built + tested):** SLICE 2 (v772, +48 covered by probe, 0 regressions vs v771; history in PARSER_VERSION_HISTORY.md): other-library search (`search_other_library`, +10), unless-discard costs/unions (+12), `any_player_may` + `counter ~` + half-life payment (+10), "defending player discards" (+8), untargeted own-graveyard return + `peel_optional` guard for "you may X. Then Y" (+8). Tests: tests/test_par208_{other_library_search,unless_discard,any_player_may,defending_player_discard,return_own_graveyard}.py. SLICE 1:  PARSER_VERSION 771 (details in PARSER_VERSION_HISTORY.md): `action_if_you_do` row (mandatory action + "If you do ... Otherwise/If you don't") as `seq`+`if_you_do_from`+`else_effects`; `else_effects` on `IfYouDoEffect`/`SeqEffect`/`OptionalEffect` (declined, impossible, accepted-but-nothing-changed); `pay_cost_then_general` splits "If you don't,"; `may_effect_then` own-graveyard pick + else; sacrificed-referent payoffs ("that creature's power") with `RulesEngine.sacrifice(source=)` stamping `pay_cost_then` costs; `remove_counters` as observable antecedent; comma-series "A, B, and C / A, B, then C" connector (`_SERIES_COMMA_CONNECTOR`); life-total comparison gates (`opponent_has_more` over `your_life_total`, new `opponent_has_fewer`). Tests `tests/test_par208_outcome_chains.py` (23, real engine, incl. else branches). Tests adjusted: test_eng33 (now gated MODELED), test_par121 (random discard), handler_row_order.txt.
- **In progress:** nothing; slice 2 committed with testing cut short on user request (PARSER_VERSION 772).
- **Next step:** owed verification for slice 2 before any closure: --full-cache tier, full-pool spec diff vs v771 (only the probe `diff` ran: 0 regressions; changed specs of previously modeled cards NOT checked, notably the `peel_optional` guard), find-fragments rescan and coverage_report. Then re-evaluate closure: remaining PAR-208-own families are small (below).
- **Decisions:** extend existing composition only; a targeted payoff after a targeted action stays unclaimed (two pronoun-ambiguous targets); the old "stays unmodeled" pins for exile-own-graveyard and random discard were replaced by gated-sequence assertions (both are correct now).
- **Baselines / artefacts:** v770: coverage 22,649/35,051 (64.6%), find-fragments pool 32,116 / covered 22,043 / open 9,905, 14,721 open sentences, 4,830 follow-up sentences (sentence_index>0) on 3,642 cards, 4,055 multi-sentence open parent clauses, 974 cards whose only open fragment is a follow-up. v771: coverage 22,686/35,051 (64.7%), find-fragments covered 22,079 / open 9,869, 14,667 open sentences, 4,802 follow-ups on 3,618 cards, 4,030 multi-sentence parents, 970 follow-up-only cards. Full-pool spec diff vs v770: +37 newly covered (probe), 0 regressions, 0 changed specs of the 21,293 previously parser-modeled cards.
- **Known failures:** none. Default suite green at slice 2 (16,678 passed + 2 stale pins updated: test_par30 typed discard, test_sacrifice_unless_pay random discard, both now real costs). SKIPPED (user request): --full-cache tier, full-pool spec diff/execution sweeps, find-fragments rescan, coverage_report; slice-2 coverage numbers not re-measured.
- **Residue:** the ticket is NOT done: multi-sentence open parents only fell 4,055 -> 4,030 because the follow-up usually fails on its own phrase, not on the separator. Follow-up-only cards (970) by family: conditional follow-ups "if that/it's/this/<state>, ..." 330; pronoun-led "it/that creature/its owner/its controller/that player ..." 96 (need a referent captured from the previous sentence's object); "if you do / if you don't / otherwise" 54 (payoffs and antecedents that lack a row: "defending player discards N", "draw cards equal to the number of spells you've cast", "cast ... from among them", exile-target + "its controller gains control of ~", "that spell" copy payoffs); "then <effect>" 49 ("Then return up to N creature cards from your graveyard to your hand" needs an untargeted "up to N" graveyard pick row; counter-threshold "then if it has N or more X counters on it, remove them and transform it" needs a remove-all-and-transform row); "unless" payment chains "draw N cards. Then discard M unless you discard an instant or sorcery card" (~7: needs union types in `costs.ActivationCost.discard_filter`); activate-only/limit sentences 37; "you may ..." follow-ups 31; "for each ..." 22; "until end of ..." 20; "when you do" 13; other 318.
- **Residue (slice 2):** PAR-208-own remainder is mostly long tail: "each player reveals the top card ... for each nonland card revealed this way ... Then each player draws a card" (7 cards, needs a revealed-cards pool + per-item repeat); same-name graveyard/hand/library sweep after exile/counter (~17 cards, new primitive); "any player may" with non-cost choices ("have ~ deal N damage to them", graveyard exile) ~6; Life's Finale (destroy, then opponent-library search) 1; `then if <counter threshold>` is PAR-212 scope; pronoun payoffs ("that creature") PAR-210. Known caveat: the any-player payoff runs right after cost payment starts, before an interactive sacrifice pick resolves. Likely closeable once the rescan confirms nothing PAR-208-own above ~6 cards remains (the two clusters above are MEC-sized; singletons: Life's Finale, Mimeofacture, Dichotomancy).
