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

- **Started / last update:** — / 2026-09-29 (residue migrated from `BACKLOG.md`)
- **Goal of this run:** extend the scope slots to the axes below.
- **Done (built + tested):** the controller-scope, "another" and player-subject slots are in
  the shared target grammar (PARSER_VERSION 485; narrative in `Done_Backend.md` → "PAR-128").
- **In progress:** —
- **Next step:** measure with `parser_probe.py composition mods --axis "control|another|scope"`
  and take the largest axis below.
- **Decisions:** —
- **Baselines / artefacts:** —
- **Known failures:** —
- **Residue:**
  - **Group** selectors with "other"/scope: "it deals 1 damage to each other creature",
    "other attacking creatures get +1/+0", "all other creatures get -2/-2", "destroy all
    creatures your opponents control", "each creature with flying your opponents control",
    "each other player sacrifices".
  - The hand-rolled **graveyard** target grammar: "return another target artifact card from
    your graveyard to your hand" (Junk Diver ×3, Deadwood Treefolk ×2, Gixian Puppeteer,
    Carrion Thrash).
  - **Plural multi-target** scope: "tap up to 2 target creatures your opponents control",
    "… divided among any number of target creatures and/or planeswalkers your opponents
    control".
  - A **quality filter before the scope**: "destroy target creature with flying an opponent
    controls", "… an opponent controls with power 2 or less".
  - "target opponent `<verb>` for each …" (Honden of Night's Reach, Bishop of the
    Bloodstained).
  - The Duress-family `reveal_hand_choose_discard` row collapses "target opponent" to `player`
    (can target yourself), and its comma form ("…, you choose … from it, then that player
    discards that card") is unclaimed — together they block Devour Intellect's "instead"
    override.
- **Log:** 2026-09-29 — residue migrated from `BACKLOG.md`.

## PAR-122 · Trigger doublers

- **Started / last update:** — / 2026-09-29 (residue migrated from `BACKLOG.md`)
- **Goal of this run:** close the fail-closed doubler shapes below.
- **Done (built + tested):** the composed `trigger_doubler` (cause × subject).
- **In progress:** —
- **Next step:** PAR-131 put "becomes the target of …" and "is dealt damage" into the
  composed object head (`trigger_condition_dict` reads both); Valiant Emberkin's / Wayta's
  causes print the gerund ("becoming the target", "being dealt damage"), so they need only a
  gerund → finite rewrite in front of it. "Turning … face up" still lacks a head.
- **Decisions:** —
- **Baselines / artefacts:** —
- **Known failures:** —
- **Residue:**
  - *Player-event cause* — each needs its head in a composed head first (PAR-131): "turning a
    face-down permanent face up" (Panoptic Projektor), "a creature you control becoming the
    target of …" (Valiant Emberkin), "being dealt damage" (Wayta).
  - *Compound subject:* "~ or an Equipment attached to it" (Cloud), "another colorless
    permanent or a colorless spell" (Echoes of Eternity), "while you control six or more
    Shrines" (Sanctum of All).
  - The Fish Brewer's tap-for-extra-copies; The Masamune's granted quoted doubler.
- **Log:** 2026-09-29 — residue migrated from `BACKLOG.md`.

## PAR-123 · Group-subject pronouns

- **Started / last update:** — / 2026-09-29 (residue migrated from `BACKLOG.md`)
- **Goal of this run:** read the group trigger's firing object in the effect types below.
- **Done (built + tested):** a bare "it"/"that creature" under a group trigger is the firing
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
  - The amount forms of that pump ("it gets +X/+X where X …", "+1/+0 for each …" — Angelic
    Exaltation, Asari Captain, Shared Animosity, Thoughtweft Imbuer; a `bind` over the
    trigger subject).
  - "it fights …" (Boxing Ring); "it deals damage equal to its power" (Stalking Vengeance,
    Warstorm Surge); `copy_permanent`.
  - Known small wrong claim: Dragon Tempest's "**it** deals X damage" is dealt by the
    Enchantment, not the entering Dragon (visible only through lifelink / deathtouch /
    protection); the `damage` dealer needs the same `trigger_subject` mode.
- **Log:** 2026-09-29 — residue migrated from `BACKLOG.md`.
