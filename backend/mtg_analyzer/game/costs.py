"""Activated-ability costs, recognized from cost text the regex way (RULE 602).

An activated ability is written ``[Cost]: [Effect].`` (RULE 602.1) — the cost
is everything left of the first colon, a comma-separated list of cost items.
Those items follow a small, regular grammar, so a handful of regexes read them
into a structured `ActivationCost` the engine can actually charge:

* mana symbols ``{2}{R}`` — the mana portion, handed to `ManaCost`;
* ``{T}`` / ``{Q}`` — tap / untap the source (RULE 602.1, 107.5);
* "Sacrifice ~ / a creature / an artifact" (RULE 701.17);
* "Pay N life" (RULE 118.4);
* "Discard a card / N cards / your hand" (RULE 701.8);
* "Remove a +1/+1 counter / N loyalty counters" (RULE 701.19).

Pure data + parsing only (it composes `ManaCost` and holds no game state), so
the binder and engine can share it. Charging a parsed cost against a player is
the engine's job (`GameEngine.activate_ability`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from ..models.mana.mana_cost import ManaCost

from ..parser.oracle.catalogue.cost_text import (
    NUMBER_WORDS as _NUMBER_WORDS,
    WARD_X_SELECTOR_PHRASES as _WARD_X_SELECTOR_PHRASES,
    scan_cost_text,
)

#: Sentinel for "discard your hand" — count isn't known until pay time.
DISCARD_HAND = -1

#: RULE 601.2b's "discard X cards" additional cost.  Kept distinct from
#: ``DISCARD_HAND`` because X is announced while casting, not inferred from
#: the hand size at payment time.
DISCARD_X = -2

#: Sentinel for "pay X life" (RULE 601.2b's ~ additional-cost template) — the
#: amount isn't known until pay time, since it's tied to the spell's own
#: announced X, not a printed number.
PAY_LIFE_X = -1

#: RULE 602.2b: X energy is announced and paid while activating.
PAY_ENERGY_X = -1

#: RULE 601.2b's "exile X cards from your graveyard" additional cost.
EXILE_FROM_GRAVEYARD_X = -1

#: Sentinels for `ActivationCost.remove_counters`'s ``count`` half, mirroring
#: `PAY_LIFE_X`'s idiom — the actual amount isn't a printed number, it's
#: announced at activation time (RULE 601.2b's template, applied to a
#: non-mana cost component): "Remove X counters" (`REMOVE_COUNTERS_X` — the
#: activation's own announced X, the same `x` a co-occurring `{X}` mana
#: symbol would also use, e.g. Chamber Sentry/Marath; several real cards
#: have no `{X}` mana at all, e.g. Blademane Baku, so X is announced purely
#: by this cost clause) and "Remove any number of counters"
#: (`REMOVE_COUNTERS_ANY` — a freely chosen amount, 0..however many are on
#: the permanent, not tied to any other X — the Mana Battery cycle/storage
#: lands). Both are paid/validated against the same `x` parameter
#: `activate_ability` already threads through for mana `{X}`.
REMOVE_COUNTERS_X = -1
REMOVE_COUNTERS_ANY = -2
#: "Remove all `<kind>` counters from `<this/~>`" as a *cost* (PAR-67, Sage
#: of Hours) — unlike `REMOVE_COUNTERS_ANY`, this is not the payer's choice
#: of amount: the cost is always exactly however many of that kind currently
#: sit on the source (0 is a legal, empty payment — RULE 602.1's "sacrifice
#: all `<x>`" cost family is payable the same way with nothing to give up),
#: so it is never exposed as an announced ``x`` the way X/ANY are.
REMOVE_COUNTERS_ALL = -3

#: ENG-49: `ActivationCost.return_to_hand`'s value for "Return ~ to its
#: owner's hand" (Rootha, Mercurial Artist) — the ability's own source, not a
#: chosen permanent of a type.
RETURN_SELF_TO_HAND = "self"

#: ENG-51: `ActivationCost.sacrifice`'s value for "Sacrifice enchanted
#: creature" (Betrothed of Fire) — the permanent the source Aura is attached to.
SACRIFICE_ENCHANTED = "enchanted"
#: ENG-51: `ActivationCost.remove_counters`'s kind for "Remove a counter from
#: ~" (Brambleback Brute) — a counter of any kind pays it.
REMOVE_COUNTERS_ANY_KIND = "*"
#: ENG-51: `ActivationCost.discard_filter`'s value for "Discard another card
#: named ~" (Baru, Fist of Krosa's Grandeur).
DISCARD_FILTER_SAME_NAME = "same_name"
#: ENG-51: `ActivationCost.pay_life` sentinel for "Pay half your life, rounded
#: up" (Lurking Evil) — the amount depends on the life total at payment.
PAY_LIFE_HALF_UP = -2
#: `ActivationCost.pay_life` sentinel for "Pay life equal to the number of
#: colors in your commanders' color identity" (War Room) — the amount is
#: the controller's RULE 903.4 identity size, only known at payment.
PAY_LIFE_COMMANDER_COLORS = -3

#: MEC-43 round 4 (Grim Hireling): the `ActivationCost.sacrifice_count`
#: sibling of `REMOVE_COUNTERS_X` — "Sacrifice X Treasures" isn't a printed
#: count either, it's RULE 601.2b's announce-X template applied to a
#: sacrifice cost component instead of a mana `{X}`/counter-removal one.
#: Threaded through the same `x` param `activate_ability` already carries.
SACRIFICE_COUNT_X = -1
#: Announced X for "Tap X untapped tokens you control" (Hazel).
TAP_OTHERS_X = -1


def _word_to_int(word: str) -> int:
    word = word.strip().lower()
    if word.isdigit():
        return int(word)
    return _NUMBER_WORDS.get(word, 1)


def _permanent_word(*parts: Optional[str]) -> str:
    """Join a cost's permanent-phrase parts into the one ``_``-separated word
    `continuous.matches_permanent_word` reads (every part must hold) — e.g.
    ``("other", "black", None, "creature")`` → ``other_black_creature``."""
    return "_".join(part.lower() for part in parts if part)


def _permanent_phrase(word: str) -> str:
    """`_permanent_word`'s encoding read back as words, for a cost label."""
    return word.replace("_or_", " or ").replace("other_", "other ").replace("_", " ")


def _singularize(word: str) -> str:
    """A plural creature type → singular ("elves"→"elf", "goblins"→"goblin")."""
    if word.endswith("ves"):
        return word[:-3] + "f"
    if word.endswith("s"):
        return word[:-1]
    return word


@dataclass
class ActivationCost:
    """The parsed cost of an activated ability (RULE 602.1), as pure data.

    ``mana`` is the mana portion; the rest are the non-mana cost items the
    engine charges in turn. ``sacrifice`` is what must be sacrificed —
    ``"self"`` for "Sacrifice ~", otherwise a type word ("creature",
    "artifact", "permanent", …). ``discard`` is a card count (or `DISCARD_HAND`
    for "your hand"); ``remove_counters`` is ``(kind, count)``.
    """

    mana: ManaCost = field(default_factory=ManaCost)
    taps_self: bool = False
    untaps_self: bool = False
    sacrifice: Optional[str] = None
    #: "Sacrifice a Swamp and a Forest" (Jarad, Golgari Lich Lord): the *second*, distinct permanent word charged
    #: alongside ``sacrifice`` (never the same object). The engine picks it (the cost UI offers the first only).
    sacrifice_also: Optional[str] = None
    #: PAR-87 / RULE 601.2b: mutually exclusive "sacrifice a creature or
    #: pay {M}" additional cost. The mana branch is selected by default.
    sacrifice_or_mana: bool = False
    #: "Exile a creature you control: …" (Food Chain, MEC-40) — a genuine
    #: RULE 605.1a mana-ability cost component (paid, not targeted, so it
    #: doesn't disqualify the ability from being a mana ability the way a
    #: real target would) — a bool rather than `sacrifice`'s type-word
    #: string since no printed card needs anything but "a creature" here.
    exile_creature: bool = False
    pay_life: int = 0
    #: RULE 122 energy: how many energy counters this cost pays (a player-
    #: level resource, `Player.counters["energy"]` — the same generic
    #: per-player counter dict "rad"/"poison" already use). Parsed from
    #: ``{E}`` pips in the cost text (`_parse_text`); charged by
    #: `GameEngine._pay_activation_cost` via `RulesEngine.add_player_counters`.
    pay_energy: int = 0
    #: "Note the type of mana spent to pay this activation cost." (Jeweled
    #: Amulet, MEC-43) — stamps `GameObject.noted_mana_color` off `Player.
    #: mana_pool.last_payment_types` right after this cost's own mana is
    #: paid (`GameEngine._pay_ability_cost`). Never set by the text parser
    #: (a project-level singleton phrasing, hand-authored only).
    note_spent_color: bool = False
    discard: int = 0
    #: ENG-49: the card type/subtype a "discard a `<type>` card" cost demands
    #: (Fauna Shaman's "creature"), matched against the type line; ``None``
    #: accepts any card.
    discard_filter: Optional[str] = None
    #: ENG-49: "discard a card at random" (Amok) — RULE 701.8d, the payer
    #: doesn't choose.
    discard_random: bool = False
    #: Channel (RULE 702.29)/Cycling (RULE 702.28): the cost is discarding
    #: *this specific card* from hand, not a player's choice of any card —
    #: distinct from ``discard`` (a battlefield ability's "discard N cards"),
    #: and paid from hand rather than off a battlefield permanent.
    discard_self: bool = False
    #: RULE 702.28c's own trigger condition ("When you cycle this card,
    #: `<effect>`.") needs to fire only when ``discard_self`` was paid
    #: specifically as a *Cycling* cost, not Channel's (both share
    #: ``discard_self`` above) — set only by `effect_binder._cycling_
    #: activated_ability` and the oracle-parsed Cycling-keyword-line cost,
    #: never by a plain "Discard this card:" Channel ability. Read by
    #: `GameEngine._pay_activation_cost` to decide whether to fire
    #: `EventType.CYCLED`.
    is_cycling: bool = False
    #: PAR-10: "`<cost>`: Return this card from your graveyard to the
    #: battlefield[, tapped]." (Dread Wanderer/Reassembling Skeleton &c) —
    #: like `discard_self`, this is the one shape activated from a zone
    #: other than the battlefield; unlike it, the *cost itself* is ordinary
    #: (mana/sacrifice/tap-others/…), so it can't reuse that flag. Stamped
    #: by `effect_binder.bind_ability` when the ability's own effect list
    #: contains a `ReturnSelfFromGraveyardToBattlefieldEffect` — every real
    #: card printing this shape has it as the ability's *entire* body, so
    #: the effect and the zone always travel together.
    graveyard_zone: bool = False
    #: "{N}: Put this card from your hand onto the battlefield." (Talon
    #: Gates of Madara-shaped) — `graveyard_zone`'s hand-zone sibling, same
    #: inference idiom (`effect_binder.bind_ability`, keyed on
    #: `PutSelfOntoBattlefieldFromHandEffect` instead).
    hand_zone: bool = False
    remove_counters: Optional[tuple[str, int]] = None
    #: RULE 702.138b (Escape): how many *other* cards must be exiled from the
    #: payer's own graveyard — "Exile four other cards from your graveyard".
    #: Also RULE 601.2b's "as an additional cost to cast this spell, exile N
    #: [<type>] cards from your graveyard" (Cobbled Lancer / Abhorrent
    #: Oculus / Makeshift Mauler), narrowed by ``exile_from_graveyard_
    #: filter`` when set.
    exile_from_graveyard: int = 0
    #: A card-type word ("creature") the ``exile_from_graveyard`` cards must
    #: match — "exile **a creature card** from your graveyard" (PAR-41).
    #: ``None`` = any card (Escape's own cost, Abhorrent Oculus's untyped
    #: "exile 6 cards").
    exile_from_graveyard_filter: Optional[str] = None
    #: RULE 701.59a (Collect Evidence, PAR-29 — Murders at Karlov Manor): the
    #: **total-mana-value threshold** — "exile any number of cards with total
    #: mana value N or greater from your graveyard". The MV-sum sibling of
    #: ``exile_from_graveyard``'s flat card count. Charged by `GameEngine.
    #: _pay_activation_cost` / `RulesEngine._pay_player_cost` via
    #: `RulesEngine.collect_evidence`, which auto-picks graveyard cards
    #: (a documented simplification — the same "auto-pick, no chooser"
    #: idiom `discard`/`put_hand_cards_on_top` use for a value-neutral
    #: selection).
    collect_evidence: int = 0
    #: RULE 701.61a (Forage, PAR-29 — Bloomburrow): a compound "exile three
    #: cards from your graveyard **or** sacrifice a Food" non-mana cost.
    #: A bool — the "N" is fixed at three. Charged by `RulesEngine.forage`
    #: (auto-picks between the two halves) from `_pay_activation_cost` /
    #: `_pay_player_cost`.
    forage: bool = False
    #: RULE 701.4a (Behold, PAR-29 — Tarkir: Dragonstorm): "as an additional
    #: cost to cast this spell, behold a `<type>` or pay {N}." — the type
    #: word to reveal (a creature type for every real card). Charged by
    #: `GameEngine._pay_additional_cast_cost` / `RulesEngine._pay_player_
    #: cost` via `RulesEngine.behold`. **Documented simplification:** the
    #: "or pay {N}" mana alternative isn't modeled (same precedent as
    #: `segmenter._ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE`) — the behold is
    #: attempted, and the spell casts whether or not it succeeds; it never
    #: blocks casting.
    behold: Optional[str] = None
    #: "reveal a `<type>` card from your hand" as one side of "…or pay {N}" (Daring Buccaneer, Flamekin Bladewhirl,
    #: Thunderherd Migration): the creature-type word of the card to reveal. Only payable while the caster's hand
    #: holds such a card besides the spell itself; paying moves nothing.
    reveal_from_hand: Optional[str] = None
    #: RULE 701.4a (Behold, PAR-30 — the Lorwyn "Champion" cycle reflavoured):
    #: "as an additional cost to cast this spell, behold a `<type>` **and
    #: exile it**." — the mandatory sibling of ``behold`` (no "or pay {N}"
    #: alternative), so it *does* block casting when the caster controls no
    #: matching permanent and holds no matching card. The type word to
    #: behold; the beheld object is exiled and its `instance_id` stamped onto
    #: the spell (`GameObject.linked_exile_id`, the O-Ring field) so the
    #: card's own "when ~ leaves the battlefield, return the exiled card to
    #: its owner's hand" trigger (`ReturnLinkedExileEffect(destination=
    #: "hand")`) can give it back. Charged by `GameEngine.
    #: _pay_additional_cast_cost`.
    behold_exile: Optional[str] = None
    #: RULE 701.4a (Behold, PAR-30 — Celestial Reunion): "as an additional
    #: cost to cast this spell, **you may** choose a creature type and behold
    #: two creatures of that type." A bool — always the optional
    #: (`additional_cost_optional`) shape. When paid, a shared creature type
    #: is chosen and stamped on `GameObject.chosen_type`, and
    #: `GameObject.additional_cost_paid` is set, so the resolving search can
    #: put the found creature onto the battlefield if it is that type.
    behold_two_shared_type: bool = False
    #: RULE 701.68 (Blight N, PAR-29 — Bloomburrow): "put N -1/-1 counters on
    #: a creature you control", paid as a cost — an activated-ability cost
    #: ("{T}, Blight 1:" — Gristle Glutton), an additional cast cost
    #: ("blight N or pay {M}" — Bogslither's Embrace), or a `pay_cost_then`
    #: half ("you may blight N. If you do, …"). The standalone-verb *effect*
    #: form is `effects.BlightEffect`; this is the cost integration.
    #: Charged non-interactively via `RulesEngine.blight(..., interactive=
    #: False)` (auto-picks the highest-toughness creature — payment can't
    #: pause for a chooser).
    blight: int = 0
    #: "Tap N untapped <type>s you control" (Birchlore Rangers, Heritage
    #: Druid) — ``(count, singular type word)``; taps *other* permanents
    #: instead of the source. Not limited by the tapped permanents' own
    #: summoning sickness (RULE 302.6 only restricts a permanent's own
    #: {T}-cost ability, not being tapped as someone else's cost).
    tap_others: Optional[tuple[int, str]] = None
    #: "Sacrifice N <type>s" (Samwise Gamgee: "Sacrifice three Foods:") —
    #: ``(count, singular subtype word)``, the `tap_others`-shaped sibling
    #: for a sacrifice cost that names a *count* rather than the single
    #: ``sacrifice`` field's implicit one. Subtype-matched via `continuous.
    #: has_subtype` (Food/Clue/Treasure/a creature type), not
    #: `_matches_sacrifice_type`'s broad main-type words. ``count`` may also
    #: be `SACRIFICE_COUNT_X` (Grim Hireling's "Sacrifice X Treasures",
    #: MEC-43) — the announced-X sibling of `REMOVE_COUNTERS_X`, resolved
    #: against the activation's own ``x`` in `GameEngine._can_pay_
    #: activation_cost`/`_pay_activation_cost`.
    sacrifice_count: Optional[tuple[int, str]] = None
    #: "Put a <kind> counter on this creature" as a *cost* (Devoted Druid's
    #: untap ability) — ``(kind, count)``; always payable (no minimum to
    #: check), unlike `remove_counters`.
    add_counters_cost: Optional[tuple[str, int]] = None
    #: "Return a Forest you control to its owner's hand" (Quirion Ranger/
    #: Scryb Ranger) — a non-mana additional cost; the lowercased subtype
    #: word (`continuous.has_subtype`-compatible) of the permanent to
    #: return, or ``None`` when this isn't such a cost.
    return_to_hand: Optional[str] = None
    #: "…exile a `<color>` card from your hand rather than pay this spell's
    #: mana cost." (RULE 118.9, Force of Will/Negation/Vigor — MEC-15) — a
    #: WUBRG letter naming which color the exiled hand card must be, or
    #: ``None`` when this isn't such a cost. Distinct from
    #: ``exile_self_from_hand`` below (that one is always *this specific
    #: card*, no choice at all); this is the payer's choice of any
    #: qualifying card elsewhere in hand. Charged by `GameEngine.
    #: _pay_alt_cast_cost` — a spell's own alternative-cost payment, not an
    #: activated ability's, so it's never consulted by `_can_pay_
    #: activation_cost`/`_pay_activation_cost`.
    exile_hand_card_color: Optional[str] = None
    #: PAR-19: "…exile 2 `<color>` cards from your hand rather than pay this
    #: spell's mana cost." (Soul Spike/Sunscour/Allosaurus Rider-shaped) —
    #: ``(count, WUBRG letter)``, the counted sibling of
    #: ``exile_hand_card_color`` above (that field's implicit count of 1
    #: can't express "2"), the same `sacrifice`/`sacrifice_count` and
    #: `return_to_hand`/`return_to_hand_count` singular/counted split
    #: already used twice in this dataclass. Alt-cast-only.
    exile_hand_card_color_count: Optional[tuple[int, str]] = None
    #: PAR-19: "…discard a `<basic land type>` card rather than pay this
    #: spell's mana cost." (Abolish/Flameshot/Outbreak/Snag — the "Pitch"
    #: basic-land cycle) — the discard-zone sibling of
    #: ``exile_hand_card_color``, keyed by land type word instead of color
    #: since these all pitch a specific basic land rather than a colored
    #: card. Alt-cast-only, same as every other RULE 118.9 field here.
    discard_land_type: Optional[str] = None
    #: PAR-19: "Spend only mana produced by Treasures to cast it this way."
    #: (Security Rhox) — scopes an alt-cast ``mana`` payment (RULE 118.9) to
    #: one `game/mana_abilities.py` `MANA_SOURCE_KINDS` bucket
    #: (`ManaPool.pool_by_source`'s own key), the alt-cast-only sibling of
    #: `GameObject.mana_source_kind_restriction` below (which scopes the
    #: spell's *ordinary* cost instead — Imperiosaur/Myr Superion print no
    #: alternative cost at all, just a standing restriction on their real
    #: mana cost, so that one lives on the object, not in an
    #: `ActivationCost`).
    mana_source_kind: Optional[str] = None
    #: "…return two Islands you control to their owner's hand rather than
    #: pay this spell's mana cost." (RULE 118.9, Gush) — ``(count, subtype
    #: word)``, the alt-cast-only sibling of ``return_to_hand`` (that one's
    #: implicit count of 1 can't express Gush's two). Subtype-matched via
    #: `continuous.has_subtype`, same as ``sacrifice_count``. Charged by
    #: `GameEngine._pay_alt_cast_cost`, never `_pay_activation_cost` — no
    #: activated ability prints this shape yet.
    return_to_hand_count: Optional[tuple[int, str]] = None
    #: "…sacrifice a nontoken blue creature rather than pay this spell's
    #: mana cost." (RULE 118.9, Flare of Denial) — a `combat.matches_
    #: object_filter`-shaped dict (``card_type``/``color``/``nontoken``)
    #: for an alt-cast sacrifice whose qualifier is more than a single
    #: subtype word (``sacrifice_count`` can't express "blue" or
    #: "nontoken"). Alt-cast-only, like ``return_to_hand_count`` above.
    sacrifice_filter: Optional[dict] = None
    #: "Exile this card from your hand" (Elvish Spirit Guide) — an
    #: alternative-zone cost the engine doesn't charge yet (no hand-zone
    #: activation path); recognised so the ability is never treated as a
    #: free battlefield tap (see `game/mana_abilities.py`).
    exile_self_from_hand: bool = False
    #: "Exile ~" as a battlefield activation cost (RULE 602.2b) — the
    #: permanent goes to exile as the cost is paid.
    exile_self: bool = False
    #: "Exile ~ and four other artifact creatures and/or Vehicles you control" (Mechtitan Core) — ``(count, permanent word)`` of
    #: *other* permanents the controller exiles as the cost is paid (RULE 602.2b), picked from the `sacrifice_count`-style pool
    #: (`GameEngine._sacrifice_count_pool`, so the word may be a compound like ``other_artifact_creature_or_vehicle``). They are
    #: recorded on the source's `GameObject.exiled_with_ids` (RULE 607.2a).
    exile_others: Optional[tuple[int, str]] = None
    #: "Spend only mana of the chosen color to activate this ability" (Throne
    #: of Eldraine's second ability, RULE 601.2b/106.6) — a colour-lock on
    #: *this ability's own* mana cost (as opposed to a spend restriction on
    #: mana the ability *produces*): the whole mana cost must be paid with
    #: mana of the source's `GameObject.chosen_color`. Enforced by
    #: `GameEngine._can_pay_activation_cost`/`_pay_activation_cost`.
    #: "Spend only black mana on X." (Crypt Rats, Crimson Hellkite; PAR-109) — a WUBRG letter locking only the
    #: ``{X}`` portion of this ability's mana cost to one colour (`ManaCost.with_x_colored`), unlike
    #: ``spend_only_chosen_color`` below, which locks the whole cost. Folded in from the body's marker sentence.
    x_spend_color: Optional[str] = None
    spend_only_chosen_color: bool = False
    #: "Exile the top card(s) of your library" (Thought Lash's 1, Seasoned
    #: Tactician's 4, MEC-30) — a non-mana additional cost paid off the
    #: payer's own library, charged by `GameEngine._pay_activation_cost` via
    #: `RulesEngine.exile`. ``0`` means no such cost; the count itself
    #: (rather than a bare bool) since `_EXILE_TOP_LIBRARY_RE` now recognizes
    #: a printed number too — every existing truthiness check (``if cost.
    #: exile_top_of_library:``) still reads correctly for any positive count.
    exile_top_of_library: int = 0
    #: "Put a card from your hand on top of your library" (Penance, MEC-30)
    #: — a non-mana additional cost paid from hand, charged by `GameEngine.
    #: _pay_activation_cost` via `RulesEngine.put_hand_card_on_top_of_
    #: library`. Only ever exactly one card on any printed card so far, so
    #: (unlike ``exile_top_of_library``) this stays a plain bool.
    put_hand_card_on_library: bool = False
    #: Loyalty-ability cost (RULE 606.5c): the signed change to the source's
    #: loyalty counters — ``+2`` for ``[+2]``, ``-3`` for ``[-3]``, ``0`` for
    #: ``[0]``. ``None`` means this is not a loyalty ability.
    loyalty: Optional[int] = None
    #: RULE 606.5c's ``[-X]`` (Jeska, Thrice Reborn's "−X: Jeska deals X
    #: damage to each of up to three targets"): the loyalty removed is the
    #: *announced* X rather than a printed constant, so ``loyalty`` is left
    #: at 0 and the real amount is resolved at activation from the same
    #: ``x`` every other X-scaled magnitude reads. Kept as a flag rather
    #: than a magic ``loyalty`` value so the arithmetic in
    #: `GameEngine._can_pay_activation_cost`/`_pay_activation_cost` stays
    #: plain ints.
    loyalty_is_x: bool = False
    #: Sorcery-speed timing restriction (RULE 711.4b Leveler / 716.4c Class
    #: level-up abilities) that isn't tied to a planeswalker — see
    #: `GameEngine._sorcery_speed_ok`. Not itself a cost component.
    sorcery_speed_only: bool = False
    #: RULE 602.5d "Activate only during your turn." — a *different*, wider
    #: timing window than `sorcery_speed_only` (Wishclaw Talisman-shaped):
    #: still legal at instant speed with a non-empty stack, only ruled out
    #: outside the controller's own turn. Deliberately its own flag rather
    #: than folded into `sorcery_speed_only` — see `GameEngine.
    #: _only_during_your_turn_ok`.
    only_during_your_turn: bool = False
    #: RULE 602.5d's converse — "You can't activate this ability during
    #: combat." (PAR-30, Djinn of Infinite Deceits) — a *narrower* window
    #: than `sorcery_speed_only`: still legal at instant speed with a
    #: non-empty stack or outside the controller's own turn, only ruled out
    #: during the combat phase specifically. See `GameEngine.
    #: _not_during_combat_ok`.
    not_during_combat: bool = False
    #: "… and only once each turn." (Vivi Ornitier's mana ability) — a
    #: per-*ability*, per-turn activation cap, distinct from RULE 606.3's
    #: standing "only one loyalty ability per turn" (`GameObject.
    #: activated_loyalty_this_turn`, unconditional and scoped to the whole
    #: permanent) and from `ActivatedAbility.once_per_turn` (the stack-based
    #: activated-ability path's own tracking, keyed on that bound object's
    #: identity — a mana ability has no such persistent identity, since
    #: `ManaAbility` is re-parsed fresh every query). Tracked instead on
    #: `GameObject.mana_abilities_activated_this_turn`, keyed by this
    #: ability's stable `ability_index` (`mana_abilities_for`'s enumeration
    #: order) — see `GameEngine.tap_for_mana`/`_only_once_this_turn_ok`.
    once_per_turn: bool = False
    #: "Exhaust — {G}, {T}: Add three mana of any one color." (RULE 702.177a,
    #: Loot, the Pathfinder) — a per-*ability*, per-game activation cap on a
    #: **mana** ability, the no-stack sibling of `ActivatedAbility.
    #: once_per_game`. Tracked like `once_per_turn`, by `ability_index`, on
    #: `GameObject.mana_abilities_used_this_game`; `mana_abilities_for` then
    #: blanks a spent ability's options so nothing offers it again.
    once_per_game: bool = False
    #: "Any player may activate this ability." (Mercenaries, MEC-30) — RULE
    #: 602.2a's *eligibility* is normally "the permanent's controller only";
    #: this is a standing exception widening it to any player at the table,
    #: enforced by `GameEngine.can_activate` skipping its ordinary
    #: ``source.controller_id != player.id`` gate. Not itself a resource
    #: paid, so `game/mana_potential.py`'s tap-plan simulation (which only
    #: cares about resource payability) needs no matching check.
    any_player_may_activate: bool = False
    #: "Only your opponents may activate this ability." (Oft-Nabbed Goat) —
    #: the inverse standing exception to `any_player_may_activate`: the
    #: eligibility set becomes *every player except this permanent's own
    #: controller*. Enforced in `GameEngine.can_activate` (the controller is
    #: rejected, non-controllers admitted) and offered to non-controllers by
    #: `legal_actions` exactly like `any_player_may_activate`.
    only_opponents_may_activate: bool = False
    #: PAR-10: "…and only if `<condition>`." stacked on (or standing in
    #: for) sorcery-speed timing (Cabal Inquisitor/Dread Wanderer/Hall of
    #: Oracles/Jin-Gitaxias/Potioner's Trove) — a `game/static_conditions.py`
    #: whitelisted condition dict, checked live by `GameEngine.can_activate`
    #: via `static_conditions.condition_holds` the same way a permanent's
    #: own "as long as `<condition>`" static is. Not itself a cost
    #: component, like `sorcery_speed_only` above.
    activation_condition: Optional[dict[str, Any]] = None
    #: RULE 716.3/716.4c: this ability advances a Class to this level — legal
    #: only when the Class's current `class_level` is exactly one less. A
    #: legality precondition riding along with the cost, not something paid.
    class_level: Optional[int] = None
    #: "Unattach this Equipment" as its own cost component (Sunforger/Akiri,
    #: Fearless Voyager's second ability) — RULE 301.5c-adjacent: legal only
    #: while the source is actually attached to something (`GameEngine.
    #: _pay_activation_cost` checks/clears `attached_to`), distinct from
    #: Reconfigure's own "or unattach" *effect* (an alternative the Equip-
    #: like activated ability itself offers, not a cost paid to reach it).
    unattach_self: bool = False
    #: A quoted ability granted by an attached Aura/Equipment can name the
    #: granting permanent in its cost ("Unattach Blinding Powder"), rather
    #: than the creature that currently has the ability.  The id is stamped
    #: at layer-6 grant time and charged by `ActivationMixin`.
    unattach_grant_source_id: Optional[int] = None
    #: RULE 702.21b: a ward cost's own "where X is …" definition for an
    #: unresolved ``{X}`` in ``mana`` — one of `_WARD_X_SELECTOR_PHRASES`'
    #: values, resolved at the *ward ability's* resolution time (not when it
    #: triggers) by `RulesEngine._resolve_ward_x`. ``None`` when ``mana``
    #: has no `{X}`, or the "where X is …" clause wasn't recognized (X stays
    #: 0 — RULE 107.3c).
    x_selector: Optional[str] = None
    #: "This ability costs {1} less to activate for each rad counter you
    #: have." (Mariposa Military Base) — ``{"kind": "rad", "generic_per":
    #: 1}``: the generic mana cost drops by ``generic_per`` for every
    #: counter of ``kind`` the *activating player* (not the source) has,
    #: read live each activation (`GameEngine._reduced_activation_mana`).
    #: The magnitude may instead come from the *board* rather than a player
    #: counter — ``{"count_selector": "legendary_creatures_you_control",
    #: "generic_per": 1}`` is Eiganjo, Seat of the Empire's "costs {1} less
    #: to activate for each legendary creature you control", resolved
    #: through `continuous.count_selector` (the same vocabulary a ward
    #: cost's `x_selector` reads). ``count_selector`` wins when both are set.
    #: Unlike `continuous.activation_cost_reduction_for`'s Power Artifact-
    #: shaped static (a fixed amount granted by a *different* permanent),
    #: this is the ability's own printed, dynamically-scaled reduction —
    #: hand-authored only (`game/card_catalogue`); no oracle-text
    #: grammar for it yet.
    dynamic_reduction: Optional[dict[str, Any]] = None
    #: ``"equip"``/``"fortify"``/``"reconfigure"`` on the cost of an attach keyword's own ability (`binding.core._keyword_activated_ability`),
    #: so a static can target "equip {N}" costs specifically ("Equipment you control have equip {0}", Puresteel Paladin).
    attach_kind: Optional[str] = None
    #: Whether the ability's effects target a creature its controller controls (stamped at bind time, `binding.core.bind_ability`) — what "the first
    #: activated ability you activate during your turn that targets a creature you control" (Professor Hojo) asks about.
    targets_own_creature: bool = False
    #: ENG-32 (RULE 701.67 Waterbend): which Convoke-style "tap your
    #: artifacts and creatures to help pay this cost" helper applies, or
    #: ``None``. Currently only ``"waterbend"`` and only *recorded* — the
    #: helper itself (generalizing `casting_mixin`'s Convoke/Delve/Improvise
    #: pool to an arbitrary cost) is a documented simplification, dropped;
    #: the {N} generic is paid as plain mana.
    help_pay_kind: Optional[str] = None
    #: PAR-28 / Power-up: "Reduce the cost by its mana cost if it entered
    #: this turn." A generic-mana reduction equal to the *source permanent's
    #: own mana value*, applied only while it entered the battlefield this
    #: turn (`GameObject.turn_entered`), read live each activation in
    #: `GameEngine._reduced_activation_mana`.
    powerup_cost_reduction: bool = False
    #: RULE 702.122a (Crew): "Tap any number of other untapped creatures you
    #: control with total power N or greater: this permanent becomes an
    #: artifact creature until end of turn." — the power *threshold* a
    #: chosen subset of creatures must meet or exceed, unlike `tap_others`
    #: (an exact count of one named subtype). ``None`` means this isn't a
    #: Crew ability. Resolved by `GameEngine._resolve_crew_cost`/
    #: `_crew_pool`; the tapped creatures are recorded on the crewed
    #: permanent's own `GameObject.crewed_by_ids` (RULE 702.122c).
    crew_power: Optional[int] = None
    #: RULE 702.171a: "Saddle N" — "Tap any number of other untapped
    #: creatures you control with total power N or greater: This permanent
    #: becomes saddled until end of turn." (Guardian Sunmare, MEC-40) —
    #: structurally identical to ``crew_power``'s own "any number from a
    #: pool, sized by a power threshold" shape (`_resolve_crew_cost`/
    #: `_crew_pool` are reused unchanged), just a different result: a
    #: `GameObject.saddled_until_turn` stamp instead of becoming a
    #: creature. RULE 702.171d: activate only as a sorcery — see
    #: `sorcery_speed_only`, already general.
    saddle_power: Optional[int] = None
    #: RULE 702.184a/721 Station: "Tap another untapped creature you
    #: control: Put a number of charge counters on this permanent equal to
    #: the tapped creature's power. Activate only as a sorcery." — genuinely
    #: different from ``crew_power``/``saddle_power``'s own "any number from
    #: a pool, sized by a power threshold" shape: this taps **exactly one**
    #: other untapped creature the player chooses (`GameEngine.
    #: _resolve_station_cost`, reusing `_crew_pool`'s own "other untapped
    #: creatures you control" pool unchanged, with an exact count of one —
    #: `_resolve_pool_cost`'s shape, not `_resolve_crew_cost`'s threshold
    #: one), and the chosen creature's own power is what the *resolving
    #: effect* needs to read afterward, not merely a threshold gate paying
    #: the cost. Paying it stamps `GameObject.station_tapped_power` (the
    #: `sacrificed_cost_power` idiom's cost-payment sibling), read back by
    #: `continuous.count_selector`'s ``"station_tapped_power"`` entry. No
    #: once-per-turn cap (RULE 721.4 — Station may be activated repeatedly
    #: regardless of how many charge counters are already on the
    #: permanent); `sorcery_speed_only` (already general) carries RULE
    #: 702.184a's own timing restriction.
    station: bool = False
    #: "…unless they sacrifice a nonland permanent of their choice or
    #: discard a card." (Tergrid's Lantern, MEC-43 round 4E) — RULE 118.3's
    #: "unless" idiom applied to a *compound* cost where the payer picks
    #: which of two payment kinds to use, not both (every other field on
    #: this dataclass is AND-combined — this is the one deliberate OR).
    #: Confirmed against the cache as a recurring template (Starseer
    #: Mentor/Thornplate Intimidator/Torment of Scarabs/Torment of Venom
    #: all print the same "…sacrifice a nonland permanent of their choice
    #: or discard a card" phrase), so it's a real cost-shape field rather
    #: than a Tergrid-only special case, even though only Tergrid's
    #: Lantern is hand-authored against it yet. `_can_pay_player_cost`
    #: treats it as payable when *either* half is; `_pay_player_cost`
    #: auto-picks the only available half, or opens a small dedicated
    #: `sacrifice_or_discard` choice when the payer genuinely has both.
    sacrifice_or_discard: bool = False
    #: RULE 601.2b "<cost A> or <cost B>" additional cast cost with no mana half (Bone Shards "sacrifice a creature or
    #: discard a card"): this object is branch A, ``either_alt`` is branch B. The caster picks one when casting — A is
    #: the plain cast, B the `pay_additional` variant (the same two-variant shape `or_mana` uses).
    either_alt: Optional["ActivationCost"] = None
    raw: str = ""
    #: ENG-49: the words of ``raw`` no cost recognizer read (``None`` when the
    #: whole text was understood). A fragment dropped here is never charged,
    #: so an ability carrying one is refused at bind time
    #: (`binding.core.bind_from_catalogue`) instead of being claimed cheaper
    #: than printed.
    unrecognized: Optional[str] = None
    #: ENG-51: where ``remove_counters`` comes off when it isn't the source —
    #: a permanent word ("creature", "permanent", "nonland_permanent") for
    #: "from a creature you control"; with ``remove_counters_among``, the
    #: count may be spread over several ("from among creatures you control").
    remove_counters_from: Optional[str] = None
    remove_counters_among: bool = False
    #: "from among **other** artifacts, creatures, and planeswalkers you control" (Tekuthal): the
    #: ability's own source is not a legal place to take them from.
    remove_counters_other: bool = False
    #: ENG-51: "Exert ~" as a cost (RULE 701.43) — it won't untap during its
    #: controller's next untap step.
    exert_self: bool = False
    #: ENG-51: "Mill N cards" as a cost.
    mill: int = 0
    #: ENG-51: "Exile the top [`<type>`] card of your graveyard" — the type
    #: word, or ``"card"`` for any.
    exile_graveyard_top: Optional[str] = None
    #: ENG-51: "Exile N cards from your hand" (Cadaverous Bloom).
    exile_hand_cards: int = 0
    #: ENG-51: "Tap enchanted creature/land" — the source Aura's host.
    tap_attached: bool = False

    @property
    def is_loyalty(self) -> bool:
        """Whether this is a planeswalker loyalty ability (RULE 606.5c)."""
        return self.loyalty is not None

    @property
    def is_free(self) -> bool:
        """No cost at all — nothing to pay (RULE 118.5 "cost of {0}" analogue)."""
        return not (
            self.mana.symbols
            or self.taps_self
            or self.untaps_self
            or self.sacrifice
            or self.exile_creature
            or self.pay_life
            or self.pay_energy
            or self.discard
            or self.discard_self
            or self.remove_counters
            or self.loyalty is not None
            or self.exile_from_graveyard
            or self.collect_evidence
            or self.forage
            or self.behold
            or self.reveal_from_hand
            or self.behold_exile
            or self.behold_two_shared_type
            or self.blight
            or self.tap_others
            or self.sacrifice_count
            or self.add_counters_cost
            or self.exile_self_from_hand
            or self.exile_self
            or self.exile_others
            or self.return_to_hand
            or self.return_to_hand_count
            or self.sacrifice_filter
            or self.exile_hand_card_color
            or self.crew_power
            or self.saddle_power
            or self.station
            or self.sacrifice_or_discard
            or self.exert_self
            or self.mill
            or self.exile_graveyard_top
            or self.exile_hand_cards
            or self.tap_attached
        )

    def label(self) -> str:
        """A short "{T}, Sacrifice a creature, Pay 2 life" style summary."""
        parts: list[str] = []
        # An "X or pay {N}" additional cost keeps the mana half in `mana` as the *default* branch; its label is the
        # other half (the branch `pay_additional` selects).
        if self.mana.symbols and not self.sacrifice_or_mana:
            parts.append(self.mana.raw or "".join(f"{{{s.kind}}}" for s in self.mana.symbols))
        if self.taps_self:
            parts.append("{T}")
        if self.untaps_self:
            parts.append("{Q}")
        if self.sacrifice:
            if self.sacrifice == "self":
                what = "~"
            elif self.sacrifice == "creature_artifact_or_land":
                what = "a creature, artifact, or land"
            elif self.sacrifice == SACRIFICE_ENCHANTED:
                what = "enchanted creature"
            else:
                phrase = _permanent_phrase(self.sacrifice)
                what = f"an{phrase[len('other'):]}" if phrase.startswith("other ") else f"a {phrase}"
            if self.sacrifice_also:
                also = _permanent_phrase(self.sacrifice_also)
                what = f"{what} and a {also}"
            parts.append(f"Sacrifice {what}")
        if self.exile_creature:
            parts.append("Exile a creature you control")
        if self.pay_life:
            parts.append("Pay X life" if self.pay_life == PAY_LIFE_X
                         else "Pay half your life, rounded up" if self.pay_life == PAY_LIFE_HALF_UP
                         else "Pay life equal to the number of colors in your commanders' color identity"
                         if self.pay_life == PAY_LIFE_COMMANDER_COLORS
                         else f"Pay {self.pay_life} life")
        if self.pay_energy:
            parts.append("Pay X {E}" if self.pay_energy == PAY_ENERGY_X else f"Pay {'{E}' * self.pay_energy}")
        if self.discard:
            parts.append("Discard your hand" if self.discard == DISCARD_HAND
                         else "Discard X cards" if self.discard == DISCARD_X
                         else f"Discard {self.discard} card(s)")
        if self.discard_self:
            parts.append("Discard this card")
        if self.remove_counters:
            kind, count = self.remove_counters
            kind = "any" if kind == REMOVE_COUNTERS_ANY_KIND else kind
            if count == REMOVE_COUNTERS_X:
                parts.append(f"Remove X {kind} counter(s)")
            elif count == REMOVE_COUNTERS_ANY:
                parts.append(f"Remove any number of {kind} counters")
            elif count == REMOVE_COUNTERS_ALL:
                parts.append(f"Remove all {kind} counters")
            else:
                parts.append(f"Remove {count} {kind} counter(s)")
        if self.exile_from_graveyard:
            count = "X" if self.exile_from_graveyard == EXILE_FROM_GRAVEYARD_X else self.exile_from_graveyard
            parts.append(f"Exile {count} other card(s) from your graveyard")
        if self.collect_evidence:
            parts.append(f"Collect evidence {self.collect_evidence}")
        if self.forage:
            parts.append("Forage")
        if self.behold:
            parts.append(f"Behold a {self.behold}")
        if self.reveal_from_hand:
            parts.append(f"Reveal a {self.reveal_from_hand} card from your hand")
        if self.behold_exile:
            parts.append(f"Behold a {self.behold_exile} and exile it")
        if self.behold_two_shared_type:
            parts.append("Choose a creature type and behold two creatures of that type")
        if self.blight:
            parts.append(f"Blight {self.blight}")
        if self.tap_others:
            count, subtype = self.tap_others
            parts.append(f"Tap {'X' if count == TAP_OTHERS_X else count} untapped {_permanent_phrase(subtype)}(s) you control")
        if self.sacrifice_count:
            count, subtype = self.sacrifice_count
            parts.append(f"Sacrifice {count} {_permanent_phrase(subtype)}(s)")
        if self.add_counters_cost:
            kind, count = self.add_counters_cost
            parts.append(f"Put {count} {kind} counter(s) on this")
        if self.exile_self_from_hand:
            parts.append("Exile this card from your hand")
        if self.exile_self:
            parts.append("Exile ~")
        if self.exile_others:
            count, word = self.exile_others
            parts.append(f"Exile {count} other {_permanent_phrase(word)}(s)")
        if self.return_to_hand:
            parts.append(f"Return a {self.return_to_hand.capitalize()} you control to its owner's hand")
        if self.return_to_hand_count:
            count, subtype = self.return_to_hand_count
            parts.append(f"Return {count} {subtype.capitalize()}s you control to their owner's hand")
        if self.sacrifice_filter:
            parts.append("Sacrifice a permanent")
        if self.exile_hand_card_color:
            parts.append(f"Exile a {self.exile_hand_card_color} card from your hand")
        if self.exile_hand_card_color_count:
            count, color = self.exile_hand_card_color_count
            parts.append(f"Exile {count} {color} card(s) from your hand")
        if self.discard_land_type:
            parts.append(f"Discard a {self.discard_land_type.capitalize()} card")
        if self.loyalty is not None:
            parts.append(f"[{'+' if self.loyalty >= 0 else ''}{self.loyalty}]")
        if self.crew_power:
            parts.append(f"Tap any number of other untapped creatures you control with total power {self.crew_power} or greater")
        if self.station:
            parts.append("Tap another untapped creature you control")
        if self.sacrifice_or_discard:
            parts.append("Sacrifice a nonland permanent or discard a card")
        if self.exert_self:
            parts.append("Exert ~")
        if self.mill:
            parts.append(f"Mill {self.mill} card(s)")
        if self.exile_graveyard_top:
            parts.append(f"Exile the top {self.exile_graveyard_top} of your graveyard")
        if self.exile_hand_cards:
            parts.append(f"Exile {self.exile_hand_cards} card(s) from your hand")
        if self.tap_attached:
            parts.append("Tap enchanted permanent")
        return ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mana": self.mana.raw,
            "taps_self": self.taps_self,
            "untaps_self": self.untaps_self,
            "sacrifice": self.sacrifice,
            "sacrifice_also": self.sacrifice_also,
            "pay_life": self.pay_life,
            "pay_energy": self.pay_energy,
            "discard": self.discard,
            "discard_self": self.discard_self,
            "is_cycling": self.is_cycling,
            "remove_counters": list(self.remove_counters) if self.remove_counters else None,
            "exile_from_graveyard": self.exile_from_graveyard,
            "exile_from_graveyard_filter": self.exile_from_graveyard_filter,
            "collect_evidence": self.collect_evidence,
            "forage": self.forage,
            "behold": self.behold,
            "reveal_from_hand": self.reveal_from_hand,
            "behold_exile": self.behold_exile,
            "behold_two_shared_type": self.behold_two_shared_type,
            "blight": self.blight,
            "tap_others": list(self.tap_others) if self.tap_others else None,
            "sacrifice_count": list(self.sacrifice_count) if self.sacrifice_count else None,
            "add_counters_cost": list(self.add_counters_cost) if self.add_counters_cost else None,
            "exile_self_from_hand": self.exile_self_from_hand,
            "exile_self": self.exile_self,
            "exile_others": list(self.exile_others) if self.exile_others else None,
            "return_to_hand": self.return_to_hand,
            "return_to_hand_count": list(self.return_to_hand_count) if self.return_to_hand_count else None,
            "sacrifice_filter": dict(self.sacrifice_filter) if self.sacrifice_filter else None,
            "exile_hand_card_color": self.exile_hand_card_color,
            "exile_hand_card_color_count": (
                list(self.exile_hand_card_color_count) if self.exile_hand_card_color_count else None
            ),
            "discard_land_type": self.discard_land_type,
            "mana_source_kind": self.mana_source_kind,
            "loyalty": self.loyalty,
            "loyalty_is_x": self.loyalty_is_x,
            "x_selector": self.x_selector,
            "crew_power": self.crew_power,
            "station": self.station,
            "sacrifice_or_discard": self.sacrifice_or_discard,
            "label": self.label(),
        }


def parse_activation_cost(
    cost: Union[None, str, dict[str, Any], ActivationCost]
) -> ActivationCost:
    """Recognize an `ActivationCost` from a cost text, a spec dict, or nothing.

    A **string** is the raw cost text (the part before the ability's colon,
    which callers may pass with or without the trailing effect). A **dict** is
    an `AbilitySpec.cost` — its explicit structured keys (``mana``,
    ``taps_self``, …) win over anything a ``text``/``cost_text`` field parses,
    so hand-authored specs stay authoritative. `None` yields a free cost.
    """
    if cost is None:
        return ActivationCost()
    if isinstance(cost, ActivationCost):
        return cost
    if isinstance(cost, str):
        return _parse_text(cost)

    if cost.get("or_mana"):
        # "<cost> or pay {N}" (RULE 601.2b): the cost's own components for the `pay_additional` branch, the mana for
        # the default one — the `sacrifice_or_mana` flag's meaning, for any single additional-cost component.
        choice = cost["or_mana"]
        parsed = parse_activation_cost(choice["cost"])
        parsed.mana = ManaCost.parse(str(choice["mana"]))
        parsed.sacrifice_or_mana = True
        return parsed
    if cost.get("either"):
        # "<cost A> or <cost B>" (RULE 601.2b): two single-component branches, A primary and B the alternative.
        first, second = cost["either"]
        parsed = parse_activation_cost(first)
        parsed.either_alt = parse_activation_cost(second)
        return parsed
    # dict: parse any free text, then let explicit structured fields override.
    text = str(cost.get("text") or cost.get("cost_text") or "")
    parsed = _parse_text(text) if text else ActivationCost()
    if cost.get("mana"):
        parsed.mana = ManaCost.parse(str(cost["mana"]))
    if "taps_self" in cost:
        parsed.taps_self = bool(cost["taps_self"])
    if "untaps_self" in cost:
        parsed.untaps_self = bool(cost["untaps_self"])
    if cost.get("sacrifice"):
        parsed.sacrifice = str(cost["sacrifice"])
    if cost.get("sacrifice_also"):
        parsed.sacrifice_also = str(cost["sacrifice_also"])
    if cost.get("sacrifice_or_mana"):
        choice = cost["sacrifice_or_mana"]
        parsed.sacrifice = str(choice["sacrifice"])
        parsed.mana = ManaCost.parse(str(choice["mana"]))
        parsed.sacrifice_or_mana = True
    if "pay_life" in cost:
        value = cost["pay_life"]
        parsed.pay_life = (
            PAY_LIFE_X if value == "x"
            else PAY_LIFE_COMMANDER_COLORS if value == "commander_colors"
            else int(value)
        )
    if "pay_energy" in cost:
        parsed.pay_energy = int(cost["pay_energy"])
    if "note_spent_color" in cost:
        parsed.note_spent_color = bool(cost["note_spent_color"])
    if "discard" in cost:
        parsed.discard = DISCARD_X if cost["discard"] == "x" else int(cost["discard"])
    if "discard_self" in cost:
        parsed.discard_self = bool(cost["discard_self"])
    if "is_cycling" in cost:
        parsed.is_cycling = bool(cost["is_cycling"])
    if cost.get("loyalty") is not None:
        raw_loyalty = cost["loyalty"]
        if isinstance(raw_loyalty, str) and raw_loyalty.strip().lower() in ("-x", "−x"):
            # RULE 606.5c's [-X] — resolved against the announced X at
            # activation time (see `loyalty_is_x`).
            parsed.loyalty = 0
            parsed.loyalty_is_x = True
        else:
            parsed.loyalty = int(raw_loyalty)
    if "exile_from_graveyard" in cost:
        raw = cost["exile_from_graveyard"]
        if isinstance(raw, dict):
            # RULE 601.2b additional-cost shape (PAR-41): {"count", "type"?}.
            count = raw.get("count", 0)
            parsed.exile_from_graveyard = (
                EXILE_FROM_GRAVEYARD_X if count == "x" else int(count)
            )
            if raw.get("type"):
                parsed.exile_from_graveyard_filter = str(raw["type"])
        else:
            # Escape's own dict form (`grant`), a bare int.
            parsed.exile_from_graveyard = int(raw)
    if cost.get("exile_from_graveyard_filter"):
        parsed.exile_from_graveyard_filter = str(cost["exile_from_graveyard_filter"])
    if cost.get("collect_evidence"):
        parsed.collect_evidence = int(cost["collect_evidence"])
    if cost.get("forage"):
        parsed.forage = True
    if cost.get("behold"):
        parsed.behold = str(cost["behold"])
    if cost.get("reveal_from_hand"):
        parsed.reveal_from_hand = str(cost["reveal_from_hand"])
    if cost.get("behold_exile"):
        parsed.behold_exile = str(cost["behold_exile"])
    if cost.get("behold_two_shared_type"):
        parsed.behold_two_shared_type = True
    if cost.get("blight"):
        parsed.blight = int(cost["blight"])
    if cost.get("tap_others"):
        count, subtype = cost["tap_others"]
        parsed.tap_others = (int(count), str(subtype))
    if cost.get("sacrifice_count"):
        count, subtype = cost["sacrifice_count"]
        parsed.sacrifice_count = (int(count), str(subtype))
    if cost.get("add_counters_cost"):
        kind, count = cost["add_counters_cost"]
        parsed.add_counters_cost = (str(kind), int(count))
    if cost.get("remove_counters"):
        kind, count = cost["remove_counters"]
        parsed.remove_counters = (str(kind), int(count))
    if cost.get("x_selector"):
        parsed.x_selector = str(cost["x_selector"])
    if cost.get("crew_power"):
        parsed.crew_power = int(cost["crew_power"])
    if "sacrifice_or_discard" in cost:
        parsed.sacrifice_or_discard = bool(cost["sacrifice_or_discard"])
    if "exile_self_from_hand" in cost:
        parsed.exile_self_from_hand = bool(cost["exile_self_from_hand"])
    if "exile_self" in cost:
        parsed.exile_self = bool(cost["exile_self"])
    if cost.get("exile_others"):
        count, word = cost["exile_others"]
        parsed.exile_others = (int(count), str(word))
    if "spend_only_chosen_color" in cost:
        parsed.spend_only_chosen_color = bool(cost["spend_only_chosen_color"])
    if "any_player_may_activate" in cost:
        parsed.any_player_may_activate = bool(cost["any_player_may_activate"])
    if "only_opponents_may_activate" in cost:
        parsed.only_opponents_may_activate = bool(cost["only_opponents_may_activate"])
    if "exile_top_of_library" in cost:
        # int(True) == 1, so a hand-authored bool (meaning "one card") and a
        # real printed count both parse correctly through the same line.
        parsed.exile_top_of_library = int(cost["exile_top_of_library"])
    if "put_hand_card_on_library" in cost:
        parsed.put_hand_card_on_library = bool(cost["put_hand_card_on_library"])
    if cost.get("return_to_hand"):
        parsed.return_to_hand = str(cost["return_to_hand"])
    if cost.get("return_to_hand_count"):
        count, subtype = cost["return_to_hand_count"]
        parsed.return_to_hand_count = (int(count), str(subtype))
    if cost.get("sacrifice_filter"):
        parsed.sacrifice_filter = dict(cost["sacrifice_filter"])
    if cost.get("exile_hand_card_color"):
        parsed.exile_hand_card_color = str(cost["exile_hand_card_color"])
    if cost.get("exile_hand_card_color_count"):
        count, color = cost["exile_hand_card_color_count"]
        parsed.exile_hand_card_color_count = (int(count), str(color))
    if cost.get("discard_land_type"):
        parsed.discard_land_type = str(cost["discard_land_type"])
    if cost.get("mana_source_kind"):
        parsed.mana_source_kind = str(cost["mana_source_kind"])
    if cost.get("attach_kind") is not None:
        kind = cost["attach_kind"]
        if kind not in {"equip", "fortify", "reconfigure"}:
            raise ValueError(f"Unknown attachment ability: {kind}")
        parsed.attach_kind = kind
    if "sorcery_speed_only" in cost:
        parsed.sorcery_speed_only = bool(cost["sorcery_speed_only"])
    if "only_during_your_turn" in cost:
        parsed.only_during_your_turn = bool(cost["only_during_your_turn"])
    if "not_during_combat" in cost:
        parsed.not_during_combat = bool(cost["not_during_combat"])
    if cost.get("class_level") is not None:
        parsed.class_level = int(cost["class_level"])
    if cost.get("activation_condition"):
        # The hand-authored counterpart of PAR-10's marker-based path
        # (`effect_binder.bind_ability`'s "activated" branch, which folds
        # an `ACTIVATION_CONDITION_MARKER` `EffectSpec` here for a card
        # recognized from oracle text) — a spec built directly in
        # `card_catalogue` has no marker to strip, so it can just
        # set the field on its own `cost` dict (Frodo, Sauron's Bane).
        parsed.activation_condition = dict(cost["activation_condition"])
    if "unattach_self" in cost:
        parsed.unattach_self = bool(cost["unattach_self"])
    if cost.get("unattach_grant_source_id") is not None:
        parsed.unattach_grant_source_id = int(cost["unattach_grant_source_id"])
        # Blinding Powder: the text's "Unattach ~" names the granting
        # Equipment, not the creature the ability was granted to.
        parsed.unattach_self = bool(cost.get("unattach_self", False))
    if cost.get("dynamic_reduction"):
        parsed.dynamic_reduction = dict(cost["dynamic_reduction"])
    if "waterbend" in cost:
        # ENG-32 (RULE 701.67): "as an additional cost to cast this spell,
        # waterbend {N}." — a {N}/{X} generic mana cost. The Convoke-style
        # helper is a documented simplification (dropped).
        wb = cost["waterbend"]
        parsed.mana = ManaCost.parse("{X}" if wb == "x" else f"{{{int(wb)}}}")
        parsed.help_pay_kind = "waterbend"
    parsed.raw = parsed.raw or text
    return parsed


def _parse_text(text: str) -> ActivationCost:
    """Regex a cost string into an `ActivationCost` (the "very REGEX way").

    Which words each component reads is `parser.oracle.catalogue.cost_text.
    scan_cost_text`'s job (shared with the segmenter, so the parser claims
    exactly the costs this charges); this maps each recognized component
    onto its field, and records whatever nothing read as ``unrecognized``
    (ENG-49)."""
    # Only look at the cost — the part before the first colon (RULE 602.1).
    cost_text = text.split(":", 1)[0] if ":" in text else text

    cost = ActivationCost(raw=cost_text.strip())
    scan = scan_cost_text(cost_text)
    hits = scan.hits

    # A loyalty ability's whole cost is its ``[±N]`` bracket (RULE 606.5c);
    # when present it is the entire cost, so return it directly.
    loyalty = hits.get("loyalty")
    if loyalty:
        magnitude = int(loyalty.group(2))
        sign = loyalty.group(1)
        cost.loyalty = -magnitude if sign in ("-", "−") else magnitude
        return cost

    # Mana + the {T}/{Q} symbols share the {...} syntax; split them apart.
    mana_tokens: list[str] = []
    energy_pips = 0
    for token in scan.braces:
        upper = token.upper()
        if upper == "T":
            cost.taps_self = True
        elif upper == "Q":
            cost.untaps_self = True
        elif upper == "E":
            # RULE 122: "Pay {E}{E}..." — each repeated pip pays one energy
            # counter; the "Pay <word> {E}" spelled-out form overrides this
            # count below.
            energy_pips += 1
        else:
            mana_tokens.append(token)
    if mana_tokens:
        cost.mana = ManaCost.parse("".join(f"{{{t}}}" for t in mana_tokens))
    if energy_pips:
        word_pay = hits.get("pay_energy_word")
        cost.pay_energy = _word_to_int(word_pay.group("n")) if word_pay else energy_pips
    selector_match = hits.get("ward_x_selector")
    if selector_match:
        # RULE 702.21b: a ward cost may define what its own {X} means.
        cost.x_selector = _WARD_X_SELECTOR_PHRASES.get(
            selector_match.group("phrase").strip().lower()
        )

    if "exile_creature" in hits:
        cost.exile_creature = True
    if "sacrifice_creature_artifact_or_land" in hits:
        # PAR-13: "Sacrifice a creature, artifact, or land [of your/their
        # choice]." (Tomb of Annihilation's "Sandfall Cell") — read ahead of
        # the generic single-type sacrifice, which would otherwise only see
        # "a creature" and drop the rest of the list.
        cost.sacrifice = "creature_artifact_or_land"
    pair = hits.get("sacrifice_pair")
    if pair:
        # "Sacrifice a Swamp and a Forest" — two distinct permanents, one of each subtype word.
        cost.sacrifice = _permanent_word(None, None, None, pair.group("first").lower())
        cost.sacrifice_also = _permanent_word(None, None, None, pair.group("second").lower())
    sac = hits.get("sacrifice")
    if sac:
        whole = sac.group("whole").lower()
        if whole.startswith("this") or whole in ("~", "it"):
            cost.sacrifice = "self"
        elif whole.startswith("enchanted"):
            # ENG-51: "Sacrifice enchanted creature" (Betrothed of Fire).
            cost.sacrifice = SACRIFICE_ENCHANTED
        else:
            # ENG-51: the qualified phrase joined into one permanent word —
            # "another black creature" → ``other_black_creature``, "a Goblin
            # creature" → ``goblin_creature``, "a creature with defender" →
            # ``defender_creature`` (`continuous.matches_permanent_word`).
            kind = _permanent_word(
                "other" if sac.group("article").lower() == "another" else None,
                sac.group("qual"), sac.group("kw"), sac.group("type") or "permanent",
                sac.group("tail"),
            )
            if sac.group("alt"):
                # ENG-49: "an artifact or creature" — either type pays it; the
                # engine's sacrifice matchers split the word on ``_or_``.
                kind = f"{kind}_or_{sac.group('alt').lower()}"
            cost.sacrifice = kind
    sac_count = hits.get("sacrifice_count")
    if sac_count:
        # ENG-49: "Sacrifice two lands" / "Sacrifice X lands" (Copper-Leaf
        # Angel) — X is the activation's own announced value (RULE 601.2b).
        amount = sac_count.group("n").lower()
        count = SACRIFICE_COUNT_X if amount == "x" else _word_to_int(amount)
        # "ten nonland permanents" (Bolas's Citadel), "three white creatures"
        # (Teysa, Orzhov Scion), "two other creatures" (Eater of Hope).
        kind = _permanent_word(
            sac_count.group("other"), sac_count.group("qual"), None,
            _singularize(sac_count.group("type").lower()),
        )
        cost.sacrifice_count = (count, kind)

    life = hits.get("pay_life")
    if life:
        cost.pay_life = int(life.group(1))
    elif "pay_half_life" in hits:
        cost.pay_life = PAY_LIFE_HALF_UP  # ENG-51: Lurking Evil

    if "discard_self" in hits:
        cost.discard_self = True
    if "discard_same_name" in hits:
        # ENG-51: "Discard another card named ~" (Baru's Grandeur).
        cost.discard = 1
        cost.discard_filter = DISCARD_FILTER_SAME_NAME
    discard = hits.get("discard")
    if discard:
        if "hand" in discard.group("what").lower():
            cost.discard = DISCARD_HAND
        else:
            amount = discard.group("n").lower()
            cost.discard = DISCARD_X if amount == "x" else _word_to_int(amount)
            # ENG-49: "Discard a creature card" (Fauna Shaman) / "… at random"
            # (Amok) — read instead of dropped.
            if discard.group("type"):
                cost.discard_filter = discard.group("type").lower()
            cost.discard_random = bool(discard.group("random"))

    any_counters = hits.get("remove_any_counters")
    if any_counters:
        cost.remove_counters = (any_counters.group(1).lower(), REMOVE_COUNTERS_ANY)
    counters = hits.get("remove_counters")
    if counters:
        amount_word = counters.group(1).strip().lower()
        count = REMOVE_COUNTERS_X if amount_word == "x" else _word_to_int(amount_word)
        # ENG-51: no kind named ("remove a counter from ~") — any kind pays.
        kind = (counters.group(2) or REMOVE_COUNTERS_ANY_KIND).lower()
        cost.remove_counters = (kind, count)
    removal = any_counters or counters
    if removal is not None:
        # ENG-51: off a permanent you control, or spread among several,
        # rather than off the source.
        if removal.group("from_one"):
            cost.remove_counters_from = removal.group("from_one").lower().replace(" ", "_")
        elif removal.group("from_among"):
            among = removal.group("from_among").lower()
            cost.remove_counters_other = among.startswith("other ")
            among = among.removeprefix("other ")
            # "artifacts, creatures, and planeswalkers" -> `matches_permanent_word`'s "a_or_b_or_c" union.
            kinds = [_singularize(w) for w in re.split(r"[\s,]+", among) if w and w != "and"]
            cost.remove_counters_from = "_or_".join(kinds)
            cost.remove_counters_among = True

    exile_graveyard = hits.get("exile_from_graveyard")
    if exile_graveyard:
        amount = exile_graveyard.group("n").lower()
        cost.exile_from_graveyard = (
            EXILE_FROM_GRAVEYARD_X if amount == "x" else _word_to_int(amount)
        )
        if exile_graveyard.group("type"):
            cost.exile_from_graveyard_filter = exile_graveyard.group("type").lower().replace(" ", "_")
    graveyard_top = hits.get("exile_graveyard_top")
    if graveyard_top:
        # ENG-51: "Exile the top [creature] card of your graveyard" (Alms).
        cost.exile_graveyard_top = (graveyard_top.group("type") or "card").lower()
    hand_card = hits.get("exile_hand_card")
    if hand_card:
        cost.exile_hand_cards = _word_to_int(hand_card.group("n"))  # ENG-51: Cadaverous Bloom
    if "exert" in hits:
        cost.exert_self = True  # ENG-51 / RULE 701.43
    mill = hits.get("mill")
    if mill:
        cost.mill = _word_to_int(mill.group("n"))  # ENG-51: Deranged Assistant
    if "tap_attached" in hits:
        cost.tap_attached = True  # ENG-51: Krovikan Plague's "Tap enchanted creature"
    if "reveal_self_from_hand" in hits:
        # ENG-51: "Reveal ~ from your hand" — activated from the hand.
        cost.hand_zone = True

    collect_ev = hits.get("collect_evidence")
    if collect_ev:
        cost.collect_evidence = int(collect_ev.group(1))

    if "forage" in hits:
        cost.forage = True

    blight_cost = hits.get("blight")
    if blight_cost:
        cost.blight = int(blight_cost.group(1))
    elif "blight_one" in hits:
        cost.blight = 1  # "Put a -1/-1 counter on a creature you control" = Blight 1

    exile_top = hits.get("exile_top_of_library")
    if exile_top:
        n = exile_top.group("n")
        cost.exile_top_of_library = _word_to_int(n) if n else 1

    if "put_hand_card_on_library" in hits:
        cost.put_hand_card_on_library = True

    tap_others = hits.get("tap_others")
    if tap_others:
        amount = tap_others.group("n").lower()
        count = TAP_OTHERS_X if amount == "x" else _word_to_int(amount)
        kind = _permanent_word(
            "other" if amount == "another" else None, tap_others.group("qual"),
            tap_others.group("kw"), _singularize(tap_others.group("type").lower()),
        )
        if tap_others.group("alt"):
            # ENG-51: "artifacts and/or creatures" — either type.
            kind = f"{kind}_or_{_singularize(tap_others.group('alt').lower())}"
        cost.tap_others = (count, kind)

    add_counter = hits.get("add_counters_cost")
    if add_counter:
        cost.add_counters_cost = (add_counter.group(1).lower(), 1)

    if "exile_self_from_hand" in hits:
        cost.exile_self_from_hand = True
    elif "exile_self_from_graveyard" in hits:
        # ENG-49: "Exile this card from your graveyard" — activated from the
        # graveyard, paid by exiling the source from there.
        cost.exile_self = True
        cost.graveyard_zone = True
    elif "exile_self" in hits:
        cost.exile_self = True

    return_to_hand = hits.get("return_to_hand")
    if return_to_hand:
        cost.return_to_hand = return_to_hand.group(1).lower()
    elif "return_self_to_hand" in hits:
        # ENG-49: "Return ~ to its owner's hand" (Rootha) — the source itself.
        cost.return_to_hand = RETURN_SELF_TO_HAND
    return_count = hits.get("return_count_to_hand")
    if return_count:
        # ENG-51: "Return two lands you control to their owner's hand".
        cost.return_to_hand_count = (
            _word_to_int(return_count.group("n")),
            _singularize(return_count.group("type").lower()),
        )

    if "unattach" in hits:
        # "Unattach ~" — a granted ability's dict names the granting object
        # instead (`unattach_grant_source_id`, which then clears this).
        cost.unattach_self = True

    if "waterbend" in hits:
        # RULE 701.67 as an activation cost ("Waterbend {3}: …") — the same
        # recorded-only helper the "waterbend" dict key sets above.
        cost.help_pay_kind = "waterbend"

    cost.unrecognized = scan.leftover
    return cost
