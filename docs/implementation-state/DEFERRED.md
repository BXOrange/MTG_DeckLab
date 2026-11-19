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
- **Chosen-artist Un-cards.** Zombie Fanboy, Drawn Together, Circle of Protection: Art, Persecute
  Artist and Aesthetic Consultation (`as ~ enters, choose an artist` / `art by the chosen artist`) were
  removed from the singleton queue by owner decision (2026-11-05); they are not in the Commander Cube.
  Do not re-promote them from scans.
- **Un-set cards without an operation family (from PAR-312).** Parked by owner decision
  (2026-11-16): cards from Scryfall `set_type` `funny` (Un-sets, holiday and playtest joke
  cards) whose open sentences fit no parser family, 250 sentences on 200 cards at
  PARSER_VERSION 912 (68 cards have no other open sentence). Un-set cards with ordinary text
  stay in their family tickets. `find_fragments.py --all-cards --axes` lists them as
  `GEPARKT Un-Sets`; promote by moving this block back to `BACKLOG.md`. Their amount sentences over
  non-rules quantities (words, letters, art, seats) stay parked here too (PAR-284, v961: Busted!,
  Goblin Cruciverbalist, Mana Flair, Mistakes Were Made, Questionable Cuisine, Staff of the Letter
  Magus, When Fluffy Bunnies Attack, capital offense, Pygmy Giant). Object filters over non-rules
  properties (name, art, legs, watermark, original deck) stay parked too (PAR-285 close, v986): Bar
  Entry, Decorated Knight // Present Arms, Duh, Framed!, Jermane Pride of the Circus, Oddly Uneven,
  Orcish Paratroopers, The Collector, The Fearsome Flock, Very Cryptic Command, World-Bottling Kit,
  Zzzyxas's Abyss.
- **Horde challenge-deck cards (from PAR-312).** Parked by owner decision (2026-11-16): the
  five open "Battle the Horde" cards (set `tbth`: Altar of Mogis, Massacre Totem, Plundered
  Statue, Refreshing Elixir, Vitality Salve) need a Horde player that casts cards on its own.
  Listed as `GEPARKT Horde-Challenge-Deck` by the axis scan.
- **Other non-Commander special cards (PAR-312).** Owner decision (2026-11-16): text that
  fits no parser family is supported only on Commander-legal cards. The residue on cards
  that are not Commander-legal is parked: 70 sentences on 52 cards at PARSER_VERSION 912
  (Mystery Booster 2 playtest cards, celebration and memorabilia one-offs, the My Little
  Pony cards, Gleemox, and banned Nadu, Winged Wisdom). Listed as
  `GEPARKT Nicht Commander-legale Sonderkarten`; a card that becomes Commander-legal
  leaves this package on the next scan and must get a family ticket.



---

## Permanent non-goals

Never to be built — not gaps.

- **Deadhead's physical hand-contact condition.** The project owner explicitly
  excluded this card: whether an opponent is physically touching their hand
  cannot be inferred from game state. The shared support policy labels this
  condition `physical_action` / `NEVER_SUPPORTED`; it is not a parser backlog.

- **Ante (RULE 407).** The owner excluded ante permanently (2026-11-16). Every card
  whose text names the mechanic (nine cards, e.g. Contract from Below, Jeweled Bird)
  gets the shared `ante` / `NEVER_SUPPORTED` verdict from `support_policy.py`.

- **Alchemy-only cards and digital mechanics.** Permanently Unsupported (Specialize,
  perpetual effects, conjure/seek/spellbook); their parser and engine paths were
  removed (PAR-170) and are not parked implementation work.
- **Cross-game interactions (MEC-125).** DeckLab has no interactions between
  separate games. Cards carrying effects, permissions, participants or objects
  into or between games are permanently Unsupported; no cross-game persistence
  or participant/card-identity subsystem is scheduled.
- **Stickers (RULE 123), Attractions (RULE 718) and Contraptions.**
  These cards/mechanics receive the shared permanent `NEVER_SUPPORTED` verdict
  and the Unsupported label, rather than appearing as ordinary parser gaps.
  Sticker Sheet inserts remain excluded from the coverage denominator
  (RULE 123.2); ordinary cards mentioning these mechanics still count.
- **Conspiracy draft-matters.** Physical draft instructions and hidden/double
  agenda mechanics are permanently Unsupported. Opening a booster pack during
  an ordinary game is not itself a draft exclusion.
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
