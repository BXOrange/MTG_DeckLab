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

## PAR-166 · Shared body/state grammar residue batch

- **Started / last update:** 2026-10-19 / 2026-10-19
- **Goal of this run:** re-size each PAR-166 axis (`PARSER_LONG_TAIL.md`, "Face-audit follow-ups: PAR-166 / PAR-167") over fronts and backs at PARSER_VERSION 692, then land the highest-yield shared shapes through existing primitives.
- **Done (built + tested):** PARSER_VERSION 693 (+31 / -0 vs v692 snapshot): `where x is the amount of life you gained/lost this turn` (`_WHERE_X_AMOUNT_RE`); standing `maximum hand size is reduced/increased by N` (`static_handlers._HAND_SIZE_MODIFIER_RE` -> `hand_size_modifier`); standing colour statements (`_color_statement_specs` -> `color_change`: self / attached / group, `+N/+M and is <color>` aura); `you've cast another spell this turn` (`history_phrase`, `spell_filter.not_reference`) for self cost reductions + resolution conditions; `put a loyalty counter on ~` (`add_loyalty_counter`, source only; `test_par135_named_counters` reserved-kind pin updated for it); `target opponent chooses a <type> they control. Destroy that <type>` (`opponent_chooses_then`; `DestroyEffect.previous_subject`); `~ deals N damage to target player/opponent and each creature that player controls` (`DealDamageEffect.group_and_players="scoped_player"`). Tests: `backend/tests/test_par166_shared_body_state_family.py` (22).
- **Done, run 2 (v694, +14 / -0 vs v693):** "<you / target opponent|player / that player / they / defending player> loses half (a third of) their life, rounded up/down" (`_LOSE_FRACTION_OF_LIFE_RE`; `lose_life` with a halved `resource` amount; new `trigger_player` + `active_player` referents in `effect_conditions.subject_of`; `event_player_events` marker admits DAMAGE / ATTACKS / CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER; `effect_amounts` resource amount with no `of` now means the acting/resolving controller, which fixes Havoc Festival's active player) and "where x is half the number of <phrase>, rounded up/down" (`_WHERE_X_HALF_COUNT_RE`, one X for the whole sentence). +Alpharael, Blood Tribute, Cruel Bargain, Dark Leo & Shredder, Dire Fleet Ravager, Ebonblade Reaper, Ghoulcaller's Harvest, Havoc Festival, Infernal Contract, Quietus Spike, Radioactive Man, Scytheclaw, Shard of the Nightbringer, Virtus the Veiled. Tests: +11 in `test_par166_shared_body_state_family.py` (33 total), executed on real cards and negative controls (non-combat hit, other player's upkeep, unkicked, round down). Full-cache gate green (14783 passed, 1 skipped).
- **In progress:** nothing.
- **Next step:** orchestrator reviews and commits v694. Re-sized axes (see Residue): the remaining shapes are small or need a runtime mechanic; PAR-166 can close once the orchestrator decides whether the target-plus-shared-color group becomes a MEC ticket (told to user first, per close-tickets rule).
- **Decisions:** selected by the orchestrator (lowest eligible ID after PAR-132 closed; MEC-125 excluded by user). PAR-132 is closed; its leftovers are in `singletons.md` Batch 7, do not re-open them here. Exile verb of the opponent-choice edict NOT claimed (no `previous_subject` reader on `ExileEffect`).
- **Baselines / artefacts:** v692 snapshot via HEAD worktree (scratchpad); `parser_probe.py diff` = +31 / -0.
- **Known failures:** —
- **Residue:** "target X and each other Y that shares a color/type/name with it" group (Cleansing Beam, Rally the Righteous, Incite Hysteria, Surge of Zeal, Wojek x3, Leave No Trace, Bathe in Light ... ~10 cards; needs a `shares_color_with_reference` filter + target-seeded group = runtime mechanic); `where x` in a targeting-time filter ("mana value X or less ... where X is life gained": Celestine, Moseo, Rodolf, Ratchet); absolute "maximum hand size is N" (Cecily, Doctor Octopus, Null Profusion, Necrodominance, Cursed Rack; needs a set-mode on `hand_size_modifier`); multi-chooser "each opponent chooses a creature they control. <tap and goad|exile>"; edict "Exile that creature"; Ezzaroot Channeler/Licia (per-life cost reduction); Essence Pulse ("each creature gets -x/-x" is unparsed even with a fixed number); Leyline of the Guildpact ("each nonland permanent you control is all colors"); Ghostfire (spell-body "~ is colorless").
- **Re-sizing, run 2 (v693 -> v694):** (a) half/rounded: life loss (done, 14 incl. Harvest); the rest are singletons or blocked elsewhere: Banshee, Eternal Flame ("half x damage ... to you"), Catacomb Dragon ("half the creature's power"), Freyalise Supplicant ("half the sacrificed creature's power"), Colorless Ultimatum / Ulamog the Defiler ("exiles half ... library"), Singularity Rupture ("any number of target players each mill half"), Lord Xander / Rush of Dread ("discards / sacrifices half ...", both also blocked by other clauses), Fraying Omnipotence / Pox Plague / Pox (multi-step "then ... round each time"), Halving Season / Vorinclex Monstrous Raider (replacement), Sokrates, Punctuate, Dark Sphere / Ghosts of the Innocent (prevention halves), Heartless Hidetsugu, Lurking Evil (pay half life), Wan Shi Tong, Chainer's Torment, Imskir, Floodgate, Aspect of Wolf. (b) opponent-chooses beyond destroy: only 3 solo cards remain, not ~48 (the 48 was a wider "chooses ... they control" net): Eunuchs' Intrigues / Goblin War Cry ("other creatures they control can't block" after the pick), Fell Beast's Shriek ("tap and goad the chosen creatures"); no "Exile that creature" card is left, so `ExileEffect.previous_subject` has no customer. The rest of that net is the each-player keep-N-then-sacrifice/destroy-the-rest family (Razia's Purification, Divine Reckoning, Covetous Elegy, Single Combat, Fall of the First Civilization, Urza's Sylex, Planar Overlay, Consuming Tide): needs `ChoosePlayerObjectsEffect` to gain a keep-count (today only per-type `keep_types`) = an engine extension, 3-5 cards. (c) "target X and each other Y that shares a color with it": 11 solo cards (Cleansing Beam, Wojek Embermage/Apothecary/Siren, Brightflame, Rally the Righteous, Surge of Zeal, Incite Hysteria, Leave No Trace, Bathe in Light + Heirloom Blade / Tajuru Paragon / Titan of Littjara which use "shares a creature type with it" as a plain reveal/count filter). NOT a filter-only extension: the group filter needs a reference object (the announced target), but mass effects (`DealDamageEffect.selector`, destroy, pump, grants, prevention) each call `group_selector_objects(src=self.source)` with no `previous_targets`; it needs a new composite (announce one target, then iterate `[target] + others sharing a colour` with `ForEachEffect`'s `item_as_target`) plus a `shares_color_with_reference` predicate in `combat.matches_object_filter`. Stopped per instruction: this is a runtime mechanic (MEC candidate, ~8 cards). (d) untargeted subset choices: no shared sub-shape (59 solo cards across "perpetually" Alchemy text = permanent non-goal, "choose a creature you control. <body>" = 5 different bodies, distribute counters, "choose a kind of counter"...).
