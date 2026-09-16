# Singleton queue

Cards found, during backlog triage, to be genuinely one-of-a-kind: each
was checked with `parser_probe.py blocked` against a regex over its own
unclaimed clause and came back **SOLO on 1** with no plausible sibling
shape elsewhere in the ~35k-card cache — not merely "nobody's built it
yet," but "no other cached card would benefit from building it." That is
what earns a line here instead of a `PAR-*`/`MEC-*` ticket: this project's
own standing rule is that a ticket is for schedulable work with a real
cluster behind it, and a singleton doesn't have one — see the
`extend-parser` skill's "When to stop parsing and hand-author" and
[11_CARD_CATALOGUE_AUTHORING_GUIDE.md](../Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md).

**This is a queue, not a ticket.** Entries stay UNMODELED until someone
runs them through `hand-author-card` (or, for the handful below that need
a wholly new interactive primitive first, through `game-engine`). Before
picking one up, re-run its `parser_probe.py blocked` check — the standing
warning applies here too: a later, unrelated batch can turn a singleton
into a two-card cluster (a shared primitive built for a different card
now reaches this one too), at which point it should be **promoted out**
into a real ticket instead of hand-authored alone. Delete a row once its
card is closed (hand-authored or, having gained a sibling, promoted) —
same "closing = deleting" discipline as `BACKLOG.md`.

| Card | Gap | Notes |
| --- | --- | --- |
| Blufferfish | Interactive true/false bluffing guess (an opponent states something, secretly notes true/false, you guess) | Needs a new `RulesEngine`/`continuations` primitive — no bluffing mechanic exists at all. |
| Smart Ass | Hidden-information reveal-or-not (opponent may reveal their hand to disprove a named card) | Same family as Blufferfish/Gollum below — each is its own distinct interactive shape, not one shared mechanic. |
| Gollum, Scheming Guide | Card-guessing minigame (opponent guesses land/nonland on a revealed top card) | Ditto — a third distinct hidden-information primitive. |
| Kamiz, Obscura Oculus | Connive, then choose *another* attacking creature with lesser power | The "lesser power" comparison against a just-connived creature has no composition yet. |
| Sewers of Estark | Branches on whether the target is attacking vs. blocking | An attacking-or-blocking conditional effect body, not a trigger condition. |
| Wedding Invitation | "If it's a vampire, it also gains lifelink" — a target-subtype-conditional keyword tail | A one-off conditional-grant-on-target shape. |
| Long River Lurker | ETB-targeted creature, then a delayed exile-and-return keyed to *that* creature dealing combat damage | The delayed trigger needs to reference an ETB-time RULE 115 target, not a self/previous-object referent. |
| Atomic Microsizer | Equip-trigger: choose a target, that creature becomes unblockable **and** animates to a fixed base P/T | The choose-then-animate compound on an equip trigger. |
| Zhuge Jin, Wu Strategist | "Activate only during your turn, before attackers are declared" | An activation-timing restriction tied to a combat sub-step, not just "your turn". |
| Dreadlight Monstrosity | "Activate only if you own a card in exile" | An ownership-scoped (not controller-scoped) exile-zone activation condition. |
| Secret Tunnel | "2 target creatures you control that share a creature type" | A same-type-as-each-other multi-target filter (cross-target constraint, not a fixed filter). |
| Open into Wonder | X target creatures, then a quoted-grant tail on "those creatures" | X-count multi-target combined with a group quoted-ability grant. |
| Trygon Prime | "Put a counter on it AND on target `<X>`" — two objects countered by one trigger | A dual-counter body (self + a separate target), not the single-counter shape every existing handler expects. |
| Unquenchable Fury | "Each minotaur can't be blocked this turn except by 2 or more creatures" | Mass/subtype-scoped unblockable with a *count*-based (not filter-based) except-by clause; `UnblockableEffect.selector` is a closed name enum, not filterable. |
| Chromium, the Mutable | "Becomes a human with base P/T 1/1, loses all abilities, and gains hexproof" | `_BASE_PT`-shaped, not `_ANIMATE_SELF`-shaped — a "loses all abilities" clause combined with a base-P/T set and a keyword grant in one sentence. |
| Writ of Passage | "Whenever enchanted creature attacks, if its power is 2 or less, `<effect>`" | An intervening-if reading the *attacker's own* power — the existing `attacked_player_has_most/lowest_life`-style gates all read the defender's state, a different subject. |
| Evie Frye | Loot (draw then discard), with a sub-trigger conditioned on the discarded card's type | The "when you discard a `<type>` card this way" sub-trigger inside a loot ability. |
| Mistford River Turtle | "Another target attacking **non-human** creature" | A subtype-*negation* qualifier on an attacking-creature target; no other cached card pairs "non-`<type>`" with this target shape. |
| Shrouded Serpent | "Defending player may pay `{4}`. If that player doesn't, `<effect>`" | A combat-trigger tax-or-else composition, distinct from the shipped attack-tax statics (this one gates a *different* effect on non-payment, not the attack itself). |
| Temmet, Vizier of Naktamun | "Target creature **token** you control" combined with pump + unblockable in one trigger | The "token" qualifier on this exact combined effect body; the one other cached card sharing "target creature token you control" (Kaya, Geist Hunter) is blocked on unrelated clauses too, so no real shared yield today. |
| First Responder | Untargeted "return another creature you control to hand, **then** put counters on ~ equal to that creature's power" | Related to PAR-98's targeted-return-then-measure bucket but a third, distinct shape: "then" (not "if you do") sequencing, and a magnitude reading the just-returned creature's *power* rather than gating on success. |
| Indoctrination Attendant | "If you do, create a 1/1 … token with toxic 1 **and** '`<quoted static ability>`'" | A printed-keyword-count-plus-quoted-ability token-creation compound; no token-creation handler combines both yet. |

See `docs/implementation-state/BACKLOG.md`'s PAR-98 entry for the related
*clustered* residue these were sorted out of (2+ cards sharing one gap —
those are tickets, not singletons).
