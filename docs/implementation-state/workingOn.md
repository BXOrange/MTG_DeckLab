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

## PAR-128 · Target/group-grammar slots

- **Started / last update:** — / 2026-09-30 (v540 batch)
- **Goal of this run:** extend the scope slots to the axes below.
- **Done (built + tested):** the controller-scope, "another" and player-subject slots are in
  the shared target grammar (PARSER_VERSION 485; narrative in `Done_Backend.md` → "PAR-128").
  v519–v525 (+38, 0 regressed; narrative in the same entry): "another/other" on graveyard cards, and
  "all other creatures" / "other attacking creatures" / "each other creature" as group
  subjects + `each_other_creature` damage selector; controller scope around a quality filter
  (destroy/exile/damage), on plural targets, on "doesn't untap", on a keyword-filtered group
  damage and on divided damage. Full suite and `--full-cache` tier green.
- **In progress:** —
- **Next step (a cluster bigger than the residue below):** the rest of the mass-damage tail
  (`blocked 'deals? (?:x|\d+) damage to each (?:other )?creature'`, ~45 left: "it deals" under a
  sacrifice/trigger (Bloodletter, Battle-Scarred Goblin), "…for each aura attached",
  kicker/"instead" variants (Cinderclasm), "each creature and each planeswalker" + X
  (Calamitous Cave-In — a count-phrase sum), "each creature blocking it"; Crypt Rats' "spend
  only black mana on x" is a separate 3-card mana-restriction rider. Then the remaining mass-tap cluster (`blocked '(?:^|, |\. )tap all '` — ~13 solo:
  "… that player controls"
  under a trigger/event player (Nature's Will, Tectonic Instability, Pretender's Claim, Monsoon),
  Sleep's "don't untap during that player's next untap step" (needs the chosen player
  recorded as the group's owner)), the "you don't control" tail (Lost in the Maze), then the
  "other" residue (Themberchaud, Lae'zel) and "target spell an opponent
  controls" (The Crimson Avenger). (The Fifth Doctor's "each
  creature you control that didn't attack or enter this turn. Untap those creatures." needs
  the *filtered* group as a referent — the context records only a selector name.)
- **Decisions:** "another" on a graveyard target is a pure grammar slot (the engine's graveyard
  branch already excludes the source), not a new `TargetSpec` field.
- **Baselines / artefacts:** PARSER_VERSION 548, 18,245 / 34,811; Commander-legal 17,524 / 31,830.
- **Known failures:** —
- **Residue:**
  - The remaining "other" groups: "each other creature without flying and each player" (Themberchaud),
    "other creatures you control and creature cards in your hand perpetually get +1/+1"
    (Lae'zel).
  - A **group referent** for the next sentence: Polukranos's "each of those creatures deals
    damage equal to its power to ~" (`PumpEffect`/`AddCountersEffect` don't read the
    `damaged_this_way` sentinel yet either).
  - "target spell an opponent controls" (The Crimson Avenger).
  - Graveyard "another" cards still blocked by something else: Illicit Masquerade ("up to 1
    other target …"), Soul of Emancipation ("up to 3 other target nonland permanents").
- **Log:** 2026-09-29 — residue migrated from `BACKLOG.md`. 2026-09-29 — v519: graveyard
  "another" + unscoped "other" groups + `each_other_creature` damage, docs synced. 2026-09-29 —
  v522: scoped quality filter, plural scope, scoped "doesn't untap"; docs synced. 2026-09-29 —
  v523: scoped keyword-group damage + divided damage; docs synced. 2026-09-29 — v524: "each other
  player sacrifices"; docs synced. 2026-09-29 — v525: opponent-scoped destroy-all, "return all
  other nonland permanents"; docs synced. 2026-09-30 — v531: mass-selector "those creatures"
  (untap/tap/don't untap); coverage docs synced, Done_Backend.md filed. 2026-09-30 — v532:
  mass-damage group referent (Thundermaw); suite green, docs synced. 2026-09-30 — v533:
  mass-counter group referent (+5); suite green, docs synced. 2026-09-30 — v534: targeted
  body under "for each" (+21) + plain `discard` "target opponent" kind; suite + full-cache green,
  docs synced. 2026-09-30 — v535: Duress-family opponent kind + comma form (+2); green, docs synced.
  2026-09-30 — v536: scoped mass "can't block" (+1, Stoneshock Giant); green, docs synced.
  2026-09-30 — v537: counters on "each of them" (+7, `previous_group`); green, docs synced.
  2026-09-30 — v538: general mass tap `tap_all_group` (+27, structured tap selector,
  `AddCountersEffect.previous_selector`); suite + full-cache green, docs synced.
  2026-09-30 — v539: player-scoped mass tap (+6, `TapEffect.selector_player`); green, docs synced.
  2026-09-30 — v540: named counter on a mass group (+3, `AddCountersEffect.group`); green, docs synced.

## PAR-122 · Trigger doublers

- **Started / last update:** — / 2026-09-29 (residue migrated from `BACKLOG.md`)
- **Goal of this run:** close the fail-closed doubler shapes below.
- **Done (built + tested):** the composed `trigger_doubler` (cause × subject); v530 the compound
  "<A> or <B>" subject (`any_of`) and the "while" gate; v526 the passive-gerund
  and "turning … face up" causes (Valiant Emberkin).
- **In progress:** —
- **Next step:** The Fish Brewer's tap-for-extra-copies and The Masamune's granted quoted doubler
  (below); Wayta's fight-cost reduction and Panoptic Projektor's face-down cost reduction block
  those two cards, not the doubler.
- **Decisions:** —
- **Baselines / artefacts:** —
- **Known failures:** —
- **Residue:**
  - The causes now parse (v526); the *cards* Wayta ("{2}{G}, {T}: … fights another target
    creature. This ability costs {2} less …") and Panoptic Projektor ("the next face-down
    creature spell you cast this turn costs {3} less") stay blocked on those other lines.
  - *Compound subject:* "a colorless spell you control or another colorless permanent you
    control" (Echoes of Eternity) — a *spell's* own triggered abilities (cascade/storm) do not
    pass through `trigger_doubler_bonus`, which takes a permanent. (Cloud's "~ or an Equipment
    attached to it" and Sanctum of All's "while you control N or more Shrines" parse as of v530;
    Sanctum and Cloud, Ex-SOLDIER stay blocked on their *other* clauses.)
  - The Fish Brewer's tap-for-extra-copies; The Masamune's granted quoted doubler.
- **Log:** 2026-09-29 — residue migrated from `BACKLOG.md`. 2026-09-29 — v526: gerund/face-up causes. 2026-09-29 — v530: compound subject + while gate.

## PAR-123 · Group-subject pronouns

- **Started / last update:** — / 2026-09-30 (v541)
- **Goal of this run:** read the group trigger's firing object in the effect types below.
- **Done (built + tested):** v528/v529: the dealer of "it deals …" under a group trigger
  (`damage_equal_to_power` and `damage` via `dealer_event_key`; Dragon Tempest's wrong claim
  fixed) and the binder resolving the group placeholder inside composition nodes. v527 the "gets +N/+M for each `<quantity>`" pump (+21;
  `_bound_pump_for_each`). A bare "it"/"that creature" under a group trigger is the firing
  object for `tap` / `return_to_hand` / `exile` / blink, and for the plain "it gets +N/+N [and
  gains `<keyword>`] until end of turn" / "it gains `<keyword>`" pump
  (`PumpEffect.trigger_subject`).
- **In progress:** —
- **Next step:** add each effect type as it is exercised, and execute the card, as
  `test_par123_group_pronoun.py` does.
- **Decisions:** a bare "it" under a `self_or_group` subject stays refused by the composed head
  (Kappa Cannoneer is correct only because "~" is named first).
- **Baselines / artefacts:** —
- **Known failures:** —
- **Residue:**
  - "for each other …" *under a group trigger* needs a count referent that is the firing
    creature, not the source (Shared Animosity's "…that shares a creature type with it" is the
    same gap). Other where-X amounts (Altar of the Goyf's "card types among cards in all
    graveyards", Ashroot Animist's "~'s power") are count-phrase gaps, not pronoun gaps.
  - "it fights up to 1 target creature you don't control with the same mana value" (Boxing
    Ring — the "with the same mana value" target filter is the gap); `copy_permanent`.
- **Log:** 2026-09-29 — residue migrated from `BACKLOG.md`. 2026-09-29 — v527: for-each pump. 2026-09-29 — v528/v529: group-trigger damage dealer,
  nested placeholder fix. 2026-09-30 — v541: "it gets +X/+X, where X is …" for the group /
  self / previous pronoun (+5); suite + full-cache green, coverage docs synced (18,170).
  2026-09-30 — v542 (PAR-128): "without `<keyword>`" object-phrase tail (+3); green, docs synced.
  2026-09-30 — v543: "any player may activate this ability" rider (+15, reaches MEC-30's
  `any_player_may_activate`); green, docs synced.
  2026-09-30 — v544: "can't be regenerated this turn" (+8, `temp_cant_be_regenerated` +
  `CantBeRegeneratedEffect`); green, docs synced.
  2026-09-30 — v545: regen + exile-instead rider pair (+3, `creature_only`); green, docs synced.
  2026-09-30 — v546: general mass damage `damage_group` (+29, `DealDamageEffect.group`); green, docs synced.
  2026-09-30 — v547: player-scoped mass damage (`group_player`) + X on `damage_selector` (+14); green, docs synced.
  2026-09-30 — v548: group + "and each player/opponent" (+3); green, docs synced.
