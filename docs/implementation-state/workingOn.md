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
- Keep it terse and current — replace stale lines instead of appending. The log is one
  line per milestone, newest last.
- **On closing the ticket, delete its whole block** (the narrative belongs in
  `Done_Backend.md` / `Done_Frontend.md`); a ticket is closed only once its residue is done
  too. With no ticket in
  progress this file is just this header and the empty template — no ticket id, no log.

Block template (copy below the line, fill in):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <what is half-built right now, and in which files>
- **Next step:** <the exact next action — command to run or change to make>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
- **Log:** <YYYY-MM-DD HH:MM — one line per milestone>
```

---

## PLAY-ALL · Make every saved deck playable (order of work)

- **Started / last update:** 2026-10-01 / 2026-10-01
- **Goal of this run:** Plan only. Fix the order of work that takes every non-cube saved deck to N/N in `scripts/deck_coverage.py`.
- **Done (built + tested):** Nothing built. Measured at PARSER_VERSION 564: 56 decks, 20 already N/N, 35 non-cube decks open (725 distinct uncovered cards, about 870 unclaimed clauses), plus the Commander Cube (300 uncovered, ~241 in no other deck, a pool and not a deck).
- **In progress:** Nothing.
- **Next step:** Step 2 — pick the cheapest open deck from `deck_coverage.py --uncovered` (re-measure first; batches 4–6 shrank several), hand-author what the new axes did not close, then the Step 2 deck list (batch 7 only for the deck being worked). Size each with `parser_probe.py blocked` over the whole cache first (batches 1–2 paid off as general axes, not per-deck lists). Then batches 4–7, then the Step 2 deck list.
- **Decisions:**
  - Decks barely overlap (Tarkir 115 uncovered = 115 distinct, Duskmourn 102 = 102). Finishing one deck does not help the next, so order by marginal cost, not by set. Set-by-set is only a familiarity choice.
  - 599 of the 725 cards have exactly one unclaimed clause and no two share an exact template. Hand-authoring dominates, and only ~83 cards sit on an open BACKLOG cluster. Handlers shrink the bill but do not remove it.
  - Per-deck size is flat (16 to 35 missing). The real levers are the free wins in Step 0 and the handler batches in Step 1.
  - Cube is last and optional. Step 1 handlers (PAR-102 especially) shrink it for free.
- **Baselines / artefacts:** `scripts/deck_coverage.py --uncovered` (2.7s). Per-card unclaimed clauses come from `parse_oracle(card).unclaimed` as in `commander_tail_report.py`. Singleton rows were last checked at PARSER_VERSION 552, so re-run `parser_probe.py blocked` before hand-authoring each card.
- **Known failures:** None known.
- **Residue:**
  - **Step 0, DONE 2026-10-01:** War Room hand-authored (`PAY_LIFE_COMMANDER_COLORS`); 14 Universes Beyond alt names in 6 saved decks renamed to the real Oracle names (backup of decks.db in the session scratchpad only). Vivi B4, Ojer cEDH, cEDH staples 2, Silverquill Influence now N/N; Raggadragga/SpongeBob/Kodama each lost their unresolved lines.
  - **Step 1, handler batches before the big decks.** Counts are saved-deck cards touching the clause, an upper bound (a card with several unclaimed clauses needs all of them). Measure the real unlock with `parser_probe.py` first.
    1. **DONE 2026-10-01 (PAR-144, v565, +115):** the dig grammar (`catalogue/dig.py`). Of the 12 saved-deck cards, 7 are now MODELED (Grisly Salvage, Growing Rites, Monumental Henge, Muxus, Paradox Surveyor, Ureni, Weatherlight). Left for hand-authoring at their decks: Genesis Hydra, Genesis Wave, Geometer's Arthropod (all `x`, refused on purpose), Atraxa, Grand Unifier (per-card-type pick), Wrenn and Seven (its `0:` ability is a separate gap). Open dig axes are listed in the Done_Backend PAR-144 entry.
    2. **DONE 2026-10-01 (v566, +99):** PAR-136 (flicker + delayed return), PAR-137 (impulse-draw variants), PAR-138 ("counters are put on" head) closed and deleted from BACKLOG; PAR-139 then closed completely in a follow-up run (madness-`{X}` overrides, corpse-counter reanimation with `exile_instead_of_leaving`, Phyrexian Vindicator's reflexive rider, one-shot shields with riders, counter-gated shields) — deleted from BACKLOG; narratives are in the Done_Backend entries. Three general parser fixes rode along (sentence windows, mid-body "where x is", list commas in a trigger condition). Leftover clusters per ticket are in the Done_Backend entry.
    3. **PAR-109 DONE 2026-10-01 (v567, +131 with PAR-139; terse residue in BACKLOG). PAR-102 DONE 2026-10-01 (v568, quoted grant / keyword choice / "that creature dies this turn" / while-tapped / toxic / all types; closed and deleted from BACKLOG, leftovers in the Done_Backend entry).**
    4. **DONE 2026-10-01 (v569, +31): token copy** — see the Done_Backend "Batch 4" entry (leftovers listed there; not ticketed).
    5. **DONE 2026-10-01 (v570, +84): PAR-105 + counters on each [other] `<group>` + graveyard cast permissions** — see the Done_Backend "PAR-105 + batch 5" entry (PAR-105 deleted from BACKLOG; leftovers listed there).
    6. **DONE 2026-10-01 (v571, +111, 1 dropped on purpose): the cycles, as shared axes** — see the Done_Backend "Batch 6" entry (all saved-deck cards on the list are MODELED and execute; PAR-99 closed 2026-10-01 (v572, +5: the targeted-spell tax, see Done_Backend), PAR-111 lost the Enduring bullet; leftovers listed there).
    7. PAR-104 DONE 2026-10-01 (v576, +34; see Done_Backend). PAR-107 to PAR-114 residue batches: only for the deck being worked.
  - **Step 2, decks in marginal-cost order (missing cards):** Goblins 8; Jeskai Striker 16; Family Matters 19; Raggadragga 19 (+1 alias); yshtola 19; Riveteer Rampage 23; Animated Army 19; Hydranten 20; Abzan Armor 23; Wick Snail Boom 23; Counter Intelligence 21; Kodama 22 (+4 aliases); Eternal Might 24; Jump Scare! 25; World Shaper 22; Sultai Arisen 26; Oops! All Night's Whispers 25; Squirreled Away 24; Mardu Surge 22; Death Toll 24; Shorikai Vehicles 26; SpongeBob and the legendary Burger 21 (+3 aliases); Endless Punishment 28; Scions & Spellcraft 27; Peace Offering 24; Living Energy 26; Temur Roar 28; Miracle Worker 25; Revival Trance 31; Counter Blitz 32; Turtle Power! 35 (PAR-104 first); Hope to the last 30; Limit Break 35.
    - Cards in several decks: hand-author them at the first deck that has one (Mosswort Bridge in 4 decks; Tear Asunder, Time Wipe, Combustible Gearhulk, Victimize, Multani, Disciple of Bolas in 3 each; War Room is already done).
  - **Step 3, Commander Cube (last, optional):** ~241 cube-only cards, ~275 clauses of hand-authoring.
  - **Effort estimate:** ~725 cards; if Step 1 closes 100 to 150, ~600 remain by hand. At about one deck per session earlier (Marchesa, Vivi), expect ~30 to 35 sessions for Steps 2 and 3, 1 to 2 for Step 0, 4 to 6 for Step 1.
- **Log:**
  - 2026-10-01 — Coverage measured, cards classified, order proposed, block filed.
  - 2026-10-01 — Step 0 done: War Room + alias renames; full pytest 9998 passed (before the deck renames, which touch no tests).
  - 2026-10-01 — Step 1 batch 1 done: PAR-144 dig family (v565, 19,176 / 35,095, +115, 0 regressed); full pytest incl. `--full-cache` 10348 passed; CLAUDE.md/PARSER_LONG_TAIL/status.{de,en}.js/Done_Backend/BACKLOG ids synced.
  - 2026-10-01 — Step 1 batch 2 done: PAR-136/137/138 closed, PAR-139 mostly (v566, 19,275 / 35,095, +99, 0 regressed); full pytest incl. `--full-cache` green after two stale test pins were updated (Professor Onyx's +1 is now dig-claimed; the condition-vocabulary pins gained `madness_cost_paid`).
  - 2026-10-01 — Step 1 batch 3 part 1: PAR-139 closed, PAR-109 closed to a terse residue (v567, 19,406 / 35,095, 0 regressed); full pytest incl. `--full-cache` 10445 passed; docs/number sync + memory done. Stormforged Armor/Kari Zev need Alchemy `conjure` (~170-card family) — not filed, user to be told.
  - 2026-10-01 — Alchemy declared a permanent non-goal by the user (DEFERRED.md already lists it; memory saved). PAR-102 part 1 built: quoted grant / all types / while-tapped / toxic / keyword choice (+38 in the probe).
  - 2026-10-01 — Step 1 batch 3 part 2: PAR-102 closed (v568, 19,452 / 35,095, Commander 18,699 / 32,116, 0 regressed); full pytest incl. `--full-cache` 10474 passed; docs/number sync + memory done.
  - 2026-10-01 — Step 1 batch 4: token copy (v569, 19,483 / 35,095, Commander 18,728 / 32,116, +31, 0 regressed); full pytest incl. `--full-cache` 10508 passed; docs/number sync done.
  - 2026-10-01 — Step 1 batch 5: PAR-105 + graveyard cast permissions + group counters (v570, 19,567 / 35,095, Commander 18,808 / 32,116, +84, 0 regressed); full pytest incl. `--full-cache` green after one stale pin ("each nonblack creature") was updated; docs/number sync done.
  - 2026-10-01 — Step 1 batch 6: Siege/Enduring/twice-X/wheel/greatest-stat/damage-equal-count (v571, 19,677 / 35,095, Commander 18,917 / 32,116, +111, Secluded Starforge dropped on purpose); full pytest incl. `--full-cache` green (one random planar-deck flake in `test_casual_variants`, passes alone); docs/number sync done.
  - 2026-10-01 — PAR-99 (the targeted-spell tax, closed and deleted from BACKLOG): v572, 19,682 / 35,095, Commander 18,922 / 32,116, +5, 0 regressed; full pytest incl. `--full-cache` 10589 passed; docs/number sync done.
  - 2026-10-01 — PAR-111 (closed and deleted from BACKLOG; BUG-2 filed): v573, 19,709 / 35,095, Commander 18,947 / 32,116, +27, 0 regressed; Exploit is now a real mechanic; docs/number sync done.
  - 2026-10-01 — PAR-104 (closed and deleted from BACKLOG): v576, 19,743 / 35,095, Commander 18,979 / 32,116, +34, 0 regressed; full pytest incl. `--full-cache` green after one stale pin was replaced; docs/number sync done.

## PAR-107…114 · Small residue batches (graveyard/library/exile, misc, board wipes, combat triggers, costs)

- **Started / last update:** 2026-10-01 / 2026-10-02 (PARSER_VERSION 578, run 2 not committed; run 1 is commit 56889705)
- **Goal of this run:** work every open clause cluster of PAR-107, 108, 110, 113, 114 (PAR-109 is a terse residue, PAR-111/112 closed). BACKLOG counts were stale — re-measure with a scan-once multi-regex script (session scratchpad `multi.py`, not committed) instead of one `parser_probe.py blocked` per clause (25 s each).
- **Done (built + tested; probe diff vs PV 576: +221 covered = 19,964 / 56.89 %, 0 regressed):**
  - Tests: `tests/test_par107_114_graveyard_library_family.py` (19), `…_misc_family.py` (29), `…_costs_family.py` (16) — all green; full pytest earlier green except `test_parser_version_lock` (needs the bump) and `test_continuations` public-method cap (bumped 172→175 with a comment).
  - Library/graveyard: `return_to_library` `depth` (Nth from top, RULE 401.7) + self form + `group` (Terminus); `search` destination `library_third`; counter-unless-pays-per-graveyard-card; `exile_hand_card` `zone=graveyard`; `TargetSpec.min_mana_value` (exile/destroy "or greater"); graveyard type words "artifact and enchantment"/"artifact or creature"; `look_reorder_top` (+ `reorder_top` look kind, X via `, where x is …, then …`, `may_shuffle` → `shuffle_offer` choice); `look_at_hand` (informational `look_hand` choice, frontend renders faces); plural/tapped/owner blink (Displace, Gandalf); named search criteria (instant-or-flash, land with a basic land type).
  - Amounts: the sacrificed creature's power/toughness/mana value (`count_phrase.SACRIFICED_TERM`, `RulesEngine.note_sacrificed` stamps costs *and* effect sacrifices); `where x is the greatest …`; `…minus N` floored; `-X/-X` bound as `-$n`; `greatest_commander_mana_value`; "…destroyed/exiled this way" tallies; `this spell costs {X} less, where X is <amount>` (also unlocked devotion/total-power ones); `scry/surveil x`.
  - Misc: `is tapped for mana` trigger verb + Wild Growth family + "an additional" mana wording; `counter` target kind `spell_or_ability`, `mana_value: x`; `you win the game`; edicts by greatest power/mana value (sacrifice or exile, tie = chosen); `mill half`; `add N {R}`, `add that much {G}`; "you get that many {E}"; `not_your_turn` cost discount; played-from-exile turn tally (`cards_played_from_exile_this_turn`, history phrase).
  - Costs/mana: `additional_cost["or_mana"]` (`<cost> or pay {N}` for discard/sacrifice/exile-graveyard/reveal-from-hand; reuses the `sacrifice_or_mana` flag; `legal_actions` now offers the paid variant when only it is castable); `ManaPool.kept` + trailing "you don't lose this mana as steps and phases end" sentence (`keep_until`).
  - Two engine bugs fixed on the way: `effect_operands._is_player`/`effect_conditions._object_or_none` treated an ability `StackItem` as a player / nobody ("its controller" of a countered ability).
- **In progress:** nothing half-built. Run 2 closed out: PARSER_VERSION 578, lock refreshed, coverage 19,995 / 35,095 (57.0 %), Commander 19,228 / 32,116 (59.9 %), full pytest 10,433 passed and `--full-cache` tier 10,749 passed (stale pins updated: "sacrifice a permanent" now claimed, Inflame's group-row pin), CLAUDE.md / PARSER_LONG_TAIL / `status.{de,en}.js` numbers synced, Done_Backend run-2 entry filed, BACKLOG PAR-108/114 trimmed.
- **Next step:** commit when the user asks. Then the next residue cluster from the Residue line (best first: the kept-mana cluster — 11 cards, ~8 distinct amount shapes, needs `ManaPool` restriction+`keep_until` together — then the sacrificed-creature sub-shapes, then the remaining mass-damage riders). Re-measure with `parser_probe.py blocked` per clause before building.
- **Decisions:** `look at the top N … put them back in any order` emits `look_reorder_top` (was `scry`, which wrongly offered the bottom). "2 mana in any combination of colors" is two single any-colour picks (equivalent, no combination chooser). Visions of Phyrexia stays open: it needs a Powerstone token (not in `data/tokens.json`, no art offline) and the "can't be spent to cast nonartifact spells" mana restriction — the played-from-exile tally is built and tested but has no consuming card yet.
- **Baselines / artefacts:** probe baseline at PV 576 = 19,743 covered; scratchpad `base.json`, `rows.pkl`, `newly.py` (lists newly covered cards with oracle text).
- **Known failures:** none.
- **Residue (exact open points; PAR-107/108/110/113/114 keep terse points in BACKLOG):** PAR-107 — Hildibrand/Mosswood Dreadknight (Adventure from graveyard), Sabin/Tenacious Underdog (Blitz from graveyard), Lluwen, Prison Break/Graveyard Shazam, Shattered Ego, Open the Vaults, Graveyard Shovel/Grave Birthing riders, Visions of Phyrexia (needs a Powerstone token and the "can't be spent to cast nonartifact spells" restriction). PAR-108 — Carnivorous Canopy, Chameleon/Mercurial Pretender (copy "except" name/quoted ability), Bulwark (hand-size difference), Spellstutter Sprite (X from a count in the target filter), Sister of Silence, Spy Network, the sacrificed-creature sub-shapes. PAR-110 — remaining mass-damage riders (Firespout's per-colour hits, Flame Sweep's "except for creatures you control with flying", Baki's Curse, Calamitous Cave-In's summed amount, Radiant Flames, Kaervek's Hex/Tropical Storm "additional damage", Planequake's plot booster), mass-tap (Monsoon, Angel's Trumpet), Living Death/End, Destined Confrontation/Slaughter the Strong, Blood Money/Aligned Hedron Network/Deadly Tempest, Singularity Rupture/Terisian Mindbreaker. PAR-113 — the kept-mana cluster with a restriction or a non-trivial head: Avatar Roku (a player attacks), Grand Warlord Radha ("that much mana in any combination of {r} and/or {g}"), Karn Legacy Reforged ("can't be spent to cast nonartifact spells"), Kessig Naturalist ("add {r} or {g}"), Klauth (total power, spend only on spells), Neheb ×2, Photon, Tanuki Transplanter, The Bloodsky Massacre, Tundra Fumarole, Sap Sucker; Shizuko, Obeka, Aurora Shifter. PAR-114 — Anthropede ("discard a card or pay {2}" at resolution), Baru (same-name discard cost), Nahiri's Sacrifice/Dargo (X-valued / any-number sacrifice), Visions of Dread/Ruin (flashback discount parsed; their bodies are not).
- **Log:**
  - 2026-10-01 — part 1 (graveyard/library) built + tested.
  - 2026-10-01 — part 2 (misc) and part 3 (costs/mana) built + tested; probe +221, 0 regressed. workingOn updated on request.
  - 2026-10-01 — v577 measured and docs synced; full tiers green.
  - 2026-10-02 — run 2 (uncommitted on top of commit 56889705, PARSER_VERSION still 577, bump pending): (a) either/or additional cast costs with no mana half (`additional_cost["either"]`, `ActivationCost.either_alt`, branch B = `pay_additional` variant; `tap_others` in cast costs; `or_mana` gained "tap an untapped artifact you control"): Bone Shards family, Final Payment, Souls of the Lost, Disruption Protocol, compound sacrifice (Final Flare/Vengeance, Heartfire, Merciless Resolve) +11; (b) `reveal_hand_choose_discard` `count`/`up_to`/`destination` (Mind Warp, Extortion, Abandon Hope, Agonizing/Painful Memories, Lost Hours, Discordant Dirge, Thrull Surgeon) +8; (c) "during turns other than yours" gate + gated self-animation (Mesa Lynx, Glory of Warfare, Vibrating Sphere, Oak Street Innkeeper, Warden of the Wall, Midnight Mangler) +8. Tests: `test_par107_114_costs_family.py` (extended), `…_hand_pick_family.py`, `…_other_turns_family.py`. Probe +27 vs PV 577 baseline, 0 regressed.
