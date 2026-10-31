---
name: find-fragments
description: Mine the still-open Commander-legal card pool clause by clause — record which exact oracle clause the parser leaves unclaimed, group the clauses by template and trigger/body axis, rank groups by how many cards they would unlock, and turn the top groups into an implementation plan. Use when asked which parser phrases are still open, to size the remaining parser tail, to choose the next PAR/MEC/singleton work from data, or to replace guesswork plans with a measured fragment list. Ships find_fragments.py.
---

# find-fragments

Card-by-card, clause-by-clause data mining of what the parser still misses.
`commander_tail_report.py` buckets whole *cards*; this skill goes one level
down and ranks *clauses*, by cards **unlocked** (a card counts only once all
its real open clauses are covered). Read-only: it never writes `coverage.db`.

## 1. Scan

```bash
cd backend
venv/bin/python ../.claude/skills/find-fragments/scripts/find_fragments.py            # full pool, several minutes
venv/bin/python ../.claude/skills/find-fragments/scripts/find_fragments.py --limit 400  # smoke test
```

Writes to `backend/data/exports/` (Git-ignored), named with the parser version:

- `offene-fragmente-<date>-v<N>.jsonl` — one row per open **sentence**: `card`,
  `type_line`, `clause` (the sentence), `parent_clause`, `sentence_index`,
  `previous_sentence`, `claims_with_previous`, `template`, and
  `kind`/`head`/`head_template`/`body_template` (trigger/cost head split via
  `CompositionProbe`).
- `offene-fragmente-<date>-v<N>-gruppen.md` — grouped ranking: templates, body
  templates, heads, and the wrapper-only "re-measure" cards.

Clauses are split at sentence boundaries (`SENTENCE_BOUNDARY_RE`) and each
sentence is checked alone; only the unclaimable ones become fragments.
`claims_with_previous=true` means the sentence claims together with its
predecessor, i.e. the gap is a cross-sentence reference ("it", "the rest",
"the copy"), one binding mechanism rather than a missing phrase handler.
Splitting at "and" was measured and is not worth it: the missing half is a
specific phrase, and bare halves lack their subject.

Wrapper headers and modal bodies that already claim alone are not fragments
(same filter as `commander_tail_report.analyse_card`). Parser version moves
with every batch, so never reuse an old file: rescan after each batch.

## 2. Group and rank

Add `--ngrams` (with `--from-jsonl` to skip the scan) for the blocker-phrase
view: `offene-fragmente-<date>-v<N>-phrasen.md` lists word sequences that sit
mostly in open cards (`share` = open cards / all pool cards with the phrase;
`nur` = upper bound on unlocks). Co-occurrence, not proof. `--ablate` deletes
each top phrase from its sentences and re-checks the remainder (`Rest claimt`):
high = removable modifier that blocks the sentence (a cheap handler), 0 = core
construct (needs grammar; deletion just breaks the sentence, so it says nothing
about the cause). Read it as a hint and confirm with `parser_probe`.


The `-gruppen.md` ranks greedily: `marginal` = extra cards unlocked given the
templates picked above, `solo` = cards whose every open clause is that one
template, `touched` = cards containing it at all. `--from-jsonl FILE` regroups an existing scan in seconds. Then sweep the axes the
exact-template check misses (singleton-sweeper method): tight regexes over the
JSONL for phrase families, e.g. a shared trigger head or modifier.

`--slots` decomposes each open sentence into atoms (`ATOM_SEPARATOR_RE`),
drops atoms that claim with a subject prefix or with a stand-in antecedent for a
back-reference (counted as binding gaps, not missing blocks), tags the rest with
slots (action, object, scope, duration, quantity, condition, reference, zone)
and ranks slot *combinations* by open share against a 6000-card modelled
baseline: `offene-fragmente-<date>-v<N>-slots.md`. It needs the card cache.

`scripts/generalization_matrix.py` is a separate probe of the parser itself:
a verb × object-form grid showing which object phrases each verb row accepts.
Empty columns are object forms the shared grammar lacks; re-run it after any
object-grammar ticket.

## 3. Classify each top group

- **PAR**: a parser handler/grammar suffices (`extend-parser` skill).
- **MEC**: grep for an existing primitive first (`game-engine`, `engine_bench.py`);
  only a verified absent primitive is MEC, and a MEC ticket includes its parser.
- **Singleton**: one-off, hand-author (`hand-author-card`).

## 4. Plan

Draft the plan with the user before filing. File tickets via `ticket-management`
(terse BACKLOG entries, no narrative). Order by unlocked cards per effort.

## Rules

- A MODELED verdict is not runtime proof: execute newly unlocked cards
  (`engine_bench.py`); wrong-but-MODELED keeps turning up.
- A second deferral means hand-author or promote; finish tickets, no residue.
- Never point `MTG_CACHE_DIR` at the production cache when running tests.
