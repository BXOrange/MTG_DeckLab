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
- **Baselines / artefacts:** <where baselines, dumps and probes live>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PAR-285 · Object filters

- **Started / last update:** 2026-11-18 / 2026-11-18
- **Goal of this run:** shrink the `P1-C Objektfilter` package one measured slot family per milestone (one commit each).
- **Done (v970–983, each 0 lost; tests `backend/tests/test_par285_*.py`, parser -> binder -> engine on real cards):**
  M1 X-or-less stat bounds on creature targets (+5). M2 can't-block row carries target quality; `CantBlockEffect.creature_filter` (+3).
  M3 "another target X" -> `excludes_source` (+21, +5 authored). M4 sequential "another target" -> `distinct_from_others` (+4).
  M5 controller's own sacrifice of a qualified pool (+17). M6 search qualifiers legendary/nonlegendary/non<type> (+6, +3 authored).
  M7 graveyard multi-pick scope/tapped/card-type slots (+5, +1 authored). M8 graveyard single-pick subtype slot, `has_subtype` match (+33, +4 authored).
  M9 X / any-number target counts; single-type artifact/enchantment/land frames now apply `creature_filter`, `without_type` read (+12, +5 authored).
  M10 graveyard "creature or land" union; counter-spell `color_any` / `non_color` / `without_card_types` / `without_subtype` / Aura (+10).
  M11 creature stat-bound slots: measured bound `stat_count_bound` (life total, counters on ~, hand/graveyard/land counts), "power or toughness N", "total power and toughness N"; targets and mass `for_each` share `combat.matches_object_filter` (+8, 0 authored).
  M12 stacked negations: comma list "nonwhite, nonblack" on targets, `nonsnow` / `noncommander` / `nonblocking` / "non-outlaw" kinds (fixes silent bogus subtype filters), mass "<adj> creatures can't block this turn" row (+8, 0 authored; `test_par285_negation_lists.py`).
  M13 library search bounded by a measured mana value (`search_mv_measured` row -> `mana_value_from` count_selector; devotion, zone counts, counters on ~; +3, 0 authored; `test_par285_measured_mv_search.py`).
  M14 (v983) "other <subtype|attacking|blocking|modified> creatures [you control]" and "other <A> and <Bs>" as a pump group subject (`effect_rows.shared._GROUP`; +6: Faerie Noble, Phyrexian Driver, Orc General, Bolg, Qala, Marton; 0 authored; `test_par285_other_group_pumps.py`).
  M15 (v984) "<adj> permanents <scope>" / "attacking <quality> creatures you control" as grant/loss group subjects (`shared._GROUP`; +2: Exterminatus, War Machine Avenging Arsenal; Dora Milaje Elite parses its sacrifice ability but stays on the named Vibranium token = PAR-297; `test_par285_qualified_permanent_groups.py`).
  M15 fix: `_search_mv_measured` refuses the unqualified lands bound (`_SEARCH_MV_LANDS_QUALIFIER_RE.fullmatch`), fixing the M13 shadowing failure (Beseech spec unchanged, no IR change, 984 kept; `--full-cache` test_par169_handler_shadowing 5 passed).
  M16 (v985) graveyard pick quality / mana-value-bound slots: shared `_GRAVEYARD_MANA_VALUE_SLOT` (N or less, exact N, X, X or less, <= / strict < ~'s power = new `source_power_less_than`), `qual` (legendary, multicolored, legendary-or-<subtype> `any_of`), single colour on exile, type words `instant` / `noncreature artifact`, `ExileEffect.exact_mana_value` (+12: Abiding Grace, Arcane Proxy, Narset Enlightened Exile, Nashi Moon's Legacy, Nucklavee, Obscura Charm, Reborn Hope, Salvaging Station, Scrivener, Sequence Engine, Mirari Conjecture, Toshiro Umezawa; +2 authored; `test_par285_graveyard_quality_bound.py`).
- **In progress:** (nothing)
- **Next step:** class (i) below, one group per milestone, order G, C, E, then R once its blocker is built (re-measure P1-C at v984 first). R blocker: "shares a color/type with it" / "same name as that creature" need the trigger subject as filter reference, but mass destroy/tap/sacrifice resolve groups against the effect source (`life_sacrifice._mass_group_objects` -> `_group_objects(src=source)`): a parser-only claim (Spreading Plague) binds the wrong reference and was reverted; build a `reference: trigger_subject` on group effects first (engine), then Spreading Plague / Faces of the Past (also a tap-or-untap choice) / Martyr's Bond (needs `shares_card_type`) / Eye of Singularity (pairwise same-name) / Legion's End (hand+graveyard) / Dual Nature (copy token) each have a second gap.
- **Decisions:** milestones commit one at a time; the orchestrator runs `--full-cache` every fifth loop iteration (last: M5, M10). `combat.matches_object_filter` silently ignores unknown keys, so every new filter key needs a reader check. Hand-put per-player family is not object-filter work: filed as MEC-150.
- **Baselines / artefacts:** P1-C: v982 198 sentences / 195 touched / 182 only (export in scratch, not committed); v983 not re-measured (expected 189 touched); v969 277/271/145, v975 234/228/113, v979 217/212/99, v980 208/204/92, v981 202/199/88. Exports `backend/data/exports/offene-fragmente-2026-11-18-v9*-vollpool-*`.
- **Known failures:** (none)
- **Residue:** P1-C at v982 = 195 cards, minus the 6 built in M14 = 189, classed (i) buildable shared slot / (ii) <3 cards, two passes / (iii) owned by another ticket / (iv) mis-scanned:
  - (i) 25 cards, 4 groups + R blocked (H done in M15; Dora Milaje Elite left on PAR-297): R 6 (Dual Nature, Spreading Plague, Faces of the Past, Martyr's Bond, Legion's End, Eye of Singularity: same name / shares quality with trigger subject or target; `reference` plumbing exists: `named_as_reference`, `shares_creature_type_with_reference`; pool-wide the probes show 53 / 67 solo-blocker cards for "same name as" / "shares a ...", mostly in other packages); C 4 (Shivan Sand-Mage, Timebender, Timecrafting, Dust of Moments: "permanent with a time counter on it or suspended card", put and remove; needs suspended-card counters in exile); D left 6 after M16 (Kaervek, the Punisher lose-life rider; Lara Croft discovery counter + play; Massimo granted ability; Nahiri the Unforgiving and Tamiyo Compleated Sage token copy of the exiled card (Nahiri also a loyalty bound, not built: no card finishes with it); The Animus copy-from-exile ability: all pick slots now parse, riders are separate tickets); G 3 (Angel of Serenity, Aurelia's Vindicator, Savior of Ollenbock: battlefield and/or graveyard target pool); E 6 (Fatal Grudge, Ultimate Nullification, Savage Order, Louisoix's Sacrifice, Lethal Throwdown, Nahiri's Sacrifice: qualified additional-cost sacrifice via `additional_cost_dict`; 5 of 6 also have a second open clause).
  - (ii) 29 -> singletons.md candidates: that was put there this turn (Abyssal Harvester); sequential another (Biomantic Mastery, Trick Shot); counter move onto another creature with same controller (Bioshift, Simic Guildmage); superlative target (Culling Scales, Topple); for each opponent + qualified target (Desecrate Reality, Sylvan Primordial); share a word in name (Everythingamajig, Urza's Hot Tub); keyword-quality targets (Merfolk Assassin islandwalk, Arcbound Overseer modular, Thraben Exorcism, Eaten by Spiders, Whip Vine, Ravager Wurm); single: Display of Dominance, Ent-Draught Basin, Lulu, Scavenger's Talent, Sorin Lord of Innistrad, Spelltwine, Eowyn Fearless Knight, Ugin the Spirit Dragon, Shadows' Verdict, Rampaging Yao Guai, Krovikan Horror, Sol Advocate Eternal.
  - (iii) 100 owned elsewhere: PAR-303 18 (hand/graveyard zone-exile: Identity Crisis, Worldfire, Thought Distortion, Haunting Echoes, Saprazzan Bailiff, Ashiok, Bottled Cloister, Duplicity, Moonring Mirror, Ignorant Bliss, Wormfang Behemoth; Ice Cauldron, Semblance Anvil, Tinybones, Leonardo da Vinci, Idol of Endurance, Evelyn, Epochrasite); PAR-297 18 (named tokens Koma x2 / Urza's Hot Dog Stand, token riders Brimaz / Inquisitorial Rosette / Sigiled Sword / Parhelion II "that's attacking", two-token create Forbidden Friendship / Wurmcoil Engine / Wurmcoil Larva, quoted-ability tokens, delayed tokens Rukh Egg / Transluminant / Giant Caterpillar, that-many Basri Ket / Bottle-Cap Blast; the attacking-rider and two-token groups are buildable shapes, 4 and 3 cards); MEC-145 / PAR-287 referents 17 (Argentum Masticore, Endemic Plague, Sanguine Praetor, Resplendent Marshal, Unleash the Inferno, Nihiloor, Simic Manipulator, Mandate of Abaddon, Calamity of the Titans, Public Execution, Kogla and Yidaro, Arcbond, Void, Wrath of the Skies, Sundering Archaic, Saruman, Soundwave); PAR-292 search 10; PAR-298 choices 6 (Extinction Event, Mutinous Massacre, Thanos, Wild Swing, Rivals' Duel, V.A.T.S.); PAR-308 stack 6; PAR-300 counters 4 (Cleopatra, Katsumasa, Master's Guidance, Rhino); PAR-286 heads 3 (Sapphire Charm, Spear of Bashenga, Lobelia); small 5 (PAR-288/298/309); MEC-150 2 (Kastral, Thran Temporal Gateway); PAR-296 2, PAR-301 2, PAR-302 2, PAR-304 2, PAR-306 2, PAR-295 1.
  - (iv) 27 mis-scanned: 12 "becomes a N/N <type> with <quality>" (PAR-293 Charakteristik: Animate Spell, Ascendant Spirit, Cosmium Confluence, Domesticated Watercourse, Figure of Fable, Fractalize, Gideon Champion of Justice, Opal Guardian, Opal Titan, Optimus Prime, Veiled Sentry, Woodcaller Automaton); 14 Un-/printed-property text (Apocalypse Chime, Bar Entry, Duh, The Collector, Oddly Uneven, Framed!, Very Cryptic Command, World-Bottling Kit, Zzzyxas's Abyss, Fluttershy, Jermane, Orcish Paratroopers, Decorated Knight, Saga of Krark: GEPARKT Un-Sets); 1 condition (Primal Empathy).
  - Estimate: ~6 milestones for (i), realistic yield 15-20 cards; then P1-C holds only (ii) singletons, (iii) hand-over and (iv) re-assignment (orchestrator moves them; this block does not edit BACKLOG).
  - Unverified in play (carried): Aryel X-from-tap cost; Changeling spell vs "non-Faerie" (Faerie Trickery) before the binder sets `intrinsic_keywords`. Golden-Tail Trainer's "other modified creatures" now parses; its second clause is PAR-301.
