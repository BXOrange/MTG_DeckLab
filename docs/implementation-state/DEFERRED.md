# Deferred — parked tickets and permanent non-goals

Pulled out of [BACKLOG.md](BACKLOG.md) so that file stays lean (it's read in
full, often — every line there costs every future read). Nothing here is
scheduled work:

- **Parked tickets** — real but low-priority or large-and-unscheduled. They
  keep their ids and their full write-up; move one back into `BACKLOG.md`'s
  matching section if it becomes active.
- **Permanent non-goals** — never to be built. Kept as guardrails so the
  same idea doesn't get re-proposed as a gap.

Same three-kinds-of-document discipline as `BACKLOG.md`: this file is *open
scope only*, no history. Closing a parked ticket = deleting it here and
appending its narrative to the matching `Done_*.md` section, exactly as if
it had lived in `BACKLOG.md`.

---

## Parked tickets

- **MEC-48 · Specialize riders (Alchemy — digital keyword).** The core
  Specialize keyword shipped in MEC-48 (v223): parser recognition of a bare
  "Specialize {cost}" line, `effect_binder._specialize_activated_ability`
  (a real sorcery-speed "{cost}, Discard a card" activated ability →
  `SpecializeEffect`, a `GameObject.is_specialized` designation +
  `EventType.SPECIALIZED`; the per-colour face swap is a documented
  simplification, no face data in the seed), and the "specializes" trigger
  verb — see `Done_Backend.md`.

  > **Low priority — no Commander-legal payoff.** Every Specialize card is
  > from `hbg` (*Alchemy Horizons: Baldur's Gate*), a digital-only set:
  > `legalities.commander == not_legal` for all of them (Arena-only —
  > Historic / Timeless / Gladiator / Brawl). Specialize isn't in the paper
  > CR and no paper set has printed it. So this ticket moves **0** cards in
  > the Commander-legal coverage slice (the number that matters for
  > Goldfisch / Deck-Analyzer) — its only benefit is correctness for a
  > Brawl / Historic goldfish session that boards one of these ~5 cards
  > directly. Don't schedule a batch here expecting coverage movement;
  > pick it up only as incidental cleanup alongside nearby activated-
  > ability-modifier work.

  **Still open:** a handful of cards print
  the keyword *with a rules rider on the same line*, held UNMODELED by
  `segmenter._SPECIALIZE_WITH_RIDER_RE` rather than greedily over-claimed —
  each is a small activated-ability-modifier follow-up:
  - "Specialize {5}. This ability costs {3} less to activate if there are
    2+ instant/sorcery cards in your graveyard." (Imoen) — a conditional
    activation-cost reduction.
  - "Specialize {2}. Activate only if a player has 13 or less life." /
    "…if you control 6 or more lands." (Shadowheart, Lukamina) — an
    `ACTIVATION_CONDITION_MARKER` gated on a `static_conditions` predicate
    (needs a `player_life_at_most` kind).
  - "Specialize {6}. You may also activate this ability if ~ is in your
    graveyard." (Karlach) — an alternate activation zone on an activated
    ability (`ActivationCost.graveyard_zone` as an *also*, not a
    replacement).

- **PLR-14 · Team variants (RULE 809/810/811).** Two-Headed Giant, Emperor
  and Grand Melee are the part of CR 8 that `models/game_format.py`
  deliberately doesn't model: unlike the RULE 9 variants (which add a card
  pool beside the game) these change the **turn structure itself** — a
  shared life total, two players taking one turn together, a "defending
  team" in combat, RULE 810.8's shared damage assignment. That's a turn-loop
  and combat project, not a format record. The seats it needs exist now (a
  table opens for up to four), so what's left is genuinely the turn loop;
  reaching it from the UI follows the same already-shipped format-picker
  pattern the RULE 9 variants use (Done_Backend.md "PLR-13").

---

## Permanent non-goals

Never to be built — not gaps.

- **Stickers (RULE 123) and Attractions (RULE 717).** `gate.parse_oracle`
  classifies mentions of the former `NEVER_SUPPORTED`, a verdict kept out
  of both the coverage count and the backlog ranking.
- **Conspiracy draft-matters.** Moved out of `BACKLOG.md`'s Bucket C
  2026-09-14 once traced card-by-card (`scripts/commander_tail_report.py`
  tags it 13 Commander-legal cards): every unclaimed clause is literally
  draft-mechanic text — `"draft this card face up"`, passing the last card
  of a booster pack, "secretly" numbering a pick — with no function outside
  a physical/digital draft, confirmed by sampling `Agent of Acquisitions`
  and `Canal Dredger`'s full unclaimed clause sets. Unlike Stickers, this
  doesn't carry a `NEVER_SUPPORTED` gate verdict — it stays UNMODELED and
  counted in the raw coverage percentage — this is a backlog-ranking
  decision, not a `parser/oracle/gate.py` classification: no ticket will
  ever be filed to close it.
  (Banding and Horsemanship, tagged alongside Conspiracy by the same
  Bucket C pass, were reconsidered the same day and moved to `BACKLOG.md`
  instead — see `MEC-87`/`MEC-88` — once combat.py turned out to have zero
  engine support for either, and both keywords are demonstrably live on
  legal Commander cards, e.g. `Riding the Dilu Horse` granting Horsemanship
  and `Cathedral of Serra` granting Banding to creatures that don't
  natively have it: real, functional gaps, not dead print-only text.)
- **Vanguard (RULE 902) beyond its already-shipped hand-size/life-total
  modifiers.** Its ~107 avatars are a small, long-retired
  supplemental-product pool (not a real deck, no set is designed around it
  today), so neither a per-seat avatar picker (every seat just gets a
  random avatar — the modifiers apply regardless of which one) nor parser
  handlers for individual avatars' extra rules text will be built.
  Structurally enforced already, not just documented:
  `scripts/import_bulk.py`'s `_SKIP_LAYOUTS` drops the Scryfall `vanguard`
  layout from `cache/db/cards.db` entirely (0 of the 34,208 cached cards),
  so avatar text can never surface in `coverage_report.py`/
  `processing_list.py`'s ranking in the first place — the committed
  `services/variant_card_database.py` pool they live in instead is never
  read by either. `game/effect_binder.bind_from_catalogue` still binds
  whatever a general-purpose handler happens to already recognize when an
  avatar is actually boarded (RULE 902.2), same as any other unregistered
  card — that's ordinary runtime behavior, not scheduled work, and needs no
  special-casing to stay that way.
