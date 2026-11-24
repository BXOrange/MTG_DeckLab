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
- **Next step:** <the exact next action a fresh session takes>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PAR-292 · Library inspection and search

- **Started / last update:** 2026-11-23 / 2026-11-24 10:00
- **Goal:** close the generic library pieces of `P2 Bibliothek` (614 / 483 / 181 at v1054). Build a piece only when one generic part serves several cards; single cards go to `singletons.md`. Close when no such shape is left.
- **Done (M1–M24, v1027–1054, +185 library cards, +18 pile cards; detail in `Done_Backend.md` "Library inspection and search (PAR-292 ...)" / "Two-pile splits", per-milestone notes in git history of this block):**
  - M1–M10 search: dynamic bounds, hand-reveal-named searches, subtype unions, conditional replacement searches, found-card riders, other searchers, slot searches, exile searches, distinct keys, shuffle-then-top.
  - M11–M15 inspection: look/reveal-top digs with bounds and ordered bottoms, exile-and-cast picks, shuffle-into-library, reveal-until by another player, hits under the ability controller.
  - M16–M20: same-name sweeps from an earlier pick, opponent splits, "that many" digs, free-cast digs, exile-until with a free cast.
  - M21–M23: piles (library, public zones), cast pools with a cap, Aura searches attached on entry. M22 (piles over permanents) was outside the family.
  - M24: target opponent's library searches with "Then that player shuffles".
- **In progress:** -
- **Next step:** pick the largest generic shape from the backlog scope, size it with `parser_probe` / `find_fragments --axes`, build it once: (1) hand cards put on top / bottom of the library after a draw ("draw 3, then put 2 cards from your hand on top of your library in any order", 16 cards, 10 only that sentence); (2) peeking at the top card of a player's library (21, 7); (3) revealing any number of <quality> cards from hand plus its "for each card revealed this way" consumer (11, 10: the Seer cycle); (4) bare "shuffle your library" (5, 3); then the owner-scoped multi-object moves (6 + 5 + 5). Before each, check whether the blocker is really library-specific or a shared axis (back-reference, whose library, amount, condition, object filter); a shared-axis gap is fixed in the shared grammar for every family, not per card.
- **Decisions:** worktree `.claude/worktrees/par-grind-2026-11-23`, branch `ticket-grind/2026-11-23-par`; `--full-cache` every 5 iterations (last green: c876ecc2, parser 1054, 27,360 passed, 4 skipped). Generalise an existing primitive, never a parallel one. Re-scoped 2026-11-24 after the v1054 measurement: every split-off tail ("then shuffle", "put the rest on the bottom", 81 sentences) is open only through its front sentence, and about 60% of the open fronts carry a shared-axis marker.
- **Baselines / artefacts:** v1054 `find_fragments --axes --slots` (Commander-legal): pool 32,643, covered 26,418, open 6,057 cards / 9,081 sentences; `P2 Bibliothek` 614 / 483 / 181 (9th by solo cards). Library fronts by marker: back-reference 150 cards, whose library 97, amount 79, condition 70, object filter 51, none 180. Scan files in the scratchpad (`frag1054/`), not kept.
- **Known failures:** -
- **Residue (multi-card mechanisms in scope; single cards are in `singletons.md`, piles on PAR-298, outside-the-game on MEC-144, prowl on PAR-299):**
  - Owner-scoped moves: "~ and <object> into / on top of their owners' libraries" (Elixir of Immortality, Serene Remembrance, Floodpits Drowner, Void Stalker, Gomazoa, Vortex Elemental); "shuffle all permanents you own" (Lich's Mirror, Sway of the Stars, Warp World, Glimpse of Tomorrow, Collision of Realms); a target player's / each owner's graveyard shuffled (Repopulate, Loaming Shaman, Witness the Future, Turn the Earth, The Three Seasons); owner shuffles, then a follow-up in the owner's name (Zoyowa's Justice, Audacious Swap, Chaos Wrap, This Is How It Ends).
  - Loops: "for each <permanent>, search ... same name" and per-permanent search loops (Doubling Chant, Clarion Ultimatum, Dire-Strain Rampage, Krenko's Buzzcrusher, From the Ashes, Wave of Vitriol).
  - Dig shapes: reveal-then-bottom-all with no pick (Stomping Slabs, Sanity Grinding, Petals of Insight); one card per subtype slot (Harper Recruiter, Kaalia Zenith Seeker, Eivor); hits relative to a spell (Jodah, Possibility Storm, Tibalt's Trickery, Unpredictable Cyclone, Guff Rewrites History); "shuffle N <name> cards into their library" (Fludge, The Gunky Runner and the other gunk cards).
  - Known simplifications (documented, not open work): a split search with fewer finds than "chooses N" makes every find chosen; declining an exact-count may-search still shuffles; filed as bugs: BUG-81 (look-at / reveal-until cards staged in exile), BUG-82 (an Aura that can't enchant ~ enters anyway), BUG-83 (an empty same-name sweep skips the shuffle).

## MEC-176 · Printed triggered and static keywords without behaviour

- **Started / last update:** 2026-11-24 / 2026-11-24 (milestone 2: 12 keywords wired, parser 1069, suites run)
- **Goal of this run:** wire the refused triggered / static keywords through the binder, largest first, dropping each from `KEYWORDS_WITHOUT_BEHAVIOUR`.
- **Done (all on real cards, `backend/tests/test_mec176_keywords.py`, 85 tests):** echo 50 (`_kw_echo`, `keyword_mechanics.EchoEffect/echo_due`, `GameObject.control_since_turn/echo_settled_turn`; dash costs "Discard a card" / "Sacrifice two lands"), soulshift 26, bloodthirst 21 (N and X, `casting_mixin._add_bloodthirst_counters`), sunburst 15 (`_add_printed_sunburst_counters`), graft 13, unleash 13 (as-enters `ChooseEnterCounterReplacement` with a zero-count decline + `combat.keyword_bars_blocking`), extort 11 (Crypt Ghast's hand-authored entry now uses the keyword spec), champion 11 (`ChampionEffect` + `return_linked_exile`), amplify 9 (`effects/amplify_entry.py`), ingest 8, provoke 8, increment 6, gravestorm 3 (`triggers_mixin._collect_storm_triggers`), decayed (printed + tokens + grants, 14 cards gained through tokens/grants). Grantable now: extort, decayed, provoke, ingest, increment (`GRANTED_TRIGGERED_FLAG_KEYWORDS`); unleash, sunburst, gravestorm stay ungrantable. PARSER_VERSION 1069, lock + history written; vs 1068: +207 gained, 0 lost.
- **In progress:** -
- **Next step:** remaining refused keywords of the ticket: ripple (5; needs a reveal-top-N / cast-same-name-free primitive), epic (702.50: spell copy each upkeep + can't cast spells, 3 cards), offering (702.48: alternative-cost casting via a sacrificed creature type, ~10 cards, a casting-pipeline change), conspire (702.78, additional-cost "tap two creatures" + copy), rebound / recover / cipher / umbra armor / for mirrodin! (also in the set, not in this ticket's list). Each: read RULE 702.x, wire, remove from the set, bump PARSER_VERSION.
- **Decisions:** Echo's "came under your control since your last upkeep" is `control_since_turn < current turn` and not settled; control changed by a layer-2 static (an Aura) or by control returning at end of turn is not stamped (documented simplification); `gain_control` is.
- **Baselines / artefacts:** parser 1068 (commit fd5b481a) snapshot `scratchpad/base1068.json`; diff output `scratchpad/mec176_diff_full.out`.
- **Known failures:** -
- **Residue:** unleash / amplify / bloodthirst only act for a permanent entering through the normal entry path (cast, put onto battlefield via `_offer_enter_choices` / `_collect_entry_counters`); granted unleash / amplify are not modelled. Graft's "you may" prompt opens before the resolution recheck, so the player is asked even when the counter is already gone (nothing moves). Graft's and increment's intervening "if" is re-checked on resolution (`ConditionalEffect`: `source_counters`, new `cast_mana_exceeds_source_stat`). Echo does not stamp control changes by a layer-2 static. Epic / ripple / offering / conspire still refused.
