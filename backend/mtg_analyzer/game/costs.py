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

#: Every ``{...}`` token in a cost string.
_BRACE_RE = re.compile(r"\{([^}]+)\}")

#: Number words a cost might spell out ("Discard two cards"); "a"/"an" == 1.
#: The tens words (twenty/thirty/forty/fifty) exist only for a "Pay N {E}"
#: energy cost's own outsized real counts (Aetherflux Conduit's "fifty").
_NUMBER_WORDS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}
#: RULE 122 energy: "Pay <word> {E}" (Aethersquall Ancient's "Pay eight
#: {E}", Aetherflux Conduit's "Pay fifty {E}") — a single ``{E}`` pip with a
#: spelled-out count in front, unlike the ordinary repeated-pip form
#: ("Pay {E}{E}{E}{E}", Guide of Souls) `_parse_text`'s brace loop already
#: counts directly.
_PAY_ENERGY_WORD_RE = re.compile(
    r"pay\s+(?P<n>" + "|".join(_NUMBER_WORDS) + r")\s+\{e\}", re.IGNORECASE
)

_SACRIFICE_RE = re.compile(
    r"sacrifice\s+(this\s+\w+|~|an?\s+(\w+)|another\s+(\w+))", re.IGNORECASE
)
#: "Exile a creature you control: …" (Food Chain, MEC-40) — a genuine RULE
#: 605.1a mana-ability cost component distinct from `_SACRIFICE_RE` above
#: (a different disposition, exile rather than the graveyard).
_EXILE_CREATURE_RE = re.compile(r"exile a creature you control", re.IGNORECASE)
#: PAR-13's compound sacrifice cost — see its check-site below. Real
#: printings vary on whether "artifact"/"land" repeat their own article
#: ("a creature, an artifact, or a land" vs. "a creature, artifact, or
#: land") — both are accepted.
_SACRIFICE_CREATURE_ARTIFACT_OR_LAND_RE = re.compile(
    r"sacrifice a creature,\s*(?:an?\s+)?artifact,?\s*(?:or|and)\s*(?:an?\s+)?land",
    re.IGNORECASE,
)
_PAY_LIFE_RE = re.compile(r"pay\s+(\d+)\s+life", re.IGNORECASE)
_DISCARD_RE = re.compile(
    r"discard\s+(your\s+hand|a\s+card|\d+\s+cards?|[a-z]+\s+cards?)", re.IGNORECASE
)
#: Channel (RULE 702.29)/Cycling (RULE 702.28)'s own cost component:
#: "Discard this card: <effect>." / "{cost}, Discard this card: Draw a
#: card." — discarding the *specific* card bearing the ability, not a
#: player's choice of any card from hand (`_DISCARD_RE`'s generic shape).
#: Checked first so "this card" never falls through to `_DISCARD_RE` and
#: gets misread as "discard a card".
_DISCARD_SELF_RE = re.compile(r"discard this card", re.IGNORECASE)
_REMOVE_COUNTERS_RE = re.compile(
    r"remove\s+(\d+|[a-z]+)\s+([+\-]?\d+/[+\-]?\d+|[a-z]+)\s+counters?", re.IGNORECASE
)
#: "Remove any number of <kind> counters from ~" (the Mana Battery cycle/
#: storage lands/Geistflame Reservoir/Rhys the Evermore/The Astonishing
#: Ant-Man) — checked before `_REMOVE_COUNTERS_RE` since "any number of"
#: doesn't fit that regex's single-token count group at all.
_REMOVE_ANY_COUNTERS_RE = re.compile(
    r"remove\s+any number of\s+([+\-]?\d+/[+\-]?\d+|[a-z]+)\s+counters?", re.IGNORECASE
)
#: RULE 702.x-adjacent bulk-tap cost: "Tap two untapped Elves you control"
#: (Birchlore Rangers, Heritage Druid) — taps *other* permanents of a
#: creature type instead of the source itself. The type word is kept as
#: printed (plural, e.g. "Elves") and singularised by `_singularize` below.
_TAP_OTHERS_RE = re.compile(
    r"tap\s+(\d+|[a-z]+)\s+untapped\s+([a-z]+)\s+you control", re.IGNORECASE
)
#: "Put a -1/-1 counter on this creature" (Devoted Druid) as an activation
#: *cost* — distinct from `_REMOVE_COUNTERS_RE` (paying by removing existing
#: counters): adding one is always payable.
_ADD_COUNTER_COST_RE = re.compile(
    r"put an?\s+([+\-]?\d+/[+\-]?\d+|[a-z]+)\s+counter on (?:this\s+\w+|~)",
    re.IGNORECASE,
)
#: An alternative-zone cost: "Exile this creature/card from your hand"
#: (Elvish/Simian Spirit Guide) — the ability is activated from hand, not
#: the battlefield; `game/mana_abilities.py`'s `hand_mana_abilities`/
#: `GameEngine.activate_hand_mana_ability` charge it (paid by
#: `RulesEngine.exile`, not through this file's battlefield-oriented
#: `_pay_activation_cost`), and `parse_mana_abilities`'s battlefield path
#: excludes it so such a line is never mistaken for a free/costless
#: battlefield tap ability.
_EXILE_FROM_HAND_RE = re.compile(
    r"exile this \w+ from your hand", re.IGNORECASE
)
#: RULE 702.138b — Escape's own cost component: "Exile N other cards from
#: your graveyard". ``N`` may be a digit or a spelled-out number word.
_EXILE_GRAVEYARD_RE = re.compile(
    r"exile\s+(\d+|[a-z]+)\s+other\s+cards?\s+from\s+your\s+graveyard", re.IGNORECASE
)
#: RULE 701.59a "Collect evidence N" — a non-mana cost (an activated
#: ability's, or an additional cast cost) sized by a total-mana-value
#: threshold rather than a card count (`ActivationCost.collect_evidence`).
_COLLECT_EVIDENCE_RE = re.compile(r"collect\s+evidence\s+(\d+)", re.IGNORECASE)
#: RULE 701.61a "Forage" — a compound "exile three graveyard cards or
#: sacrifice a Food" non-mana cost (`ActivationCost.forage`, a bool).
_FORAGE_RE = re.compile(r"\bforage\b", re.IGNORECASE)
#: RULE 701.68 "Blight N" — a non-mana cost (an activated ability's, or an
#: additional cast cost): put N -1/-1 counters on a creature you control
#: (`ActivationCost.blight`). Previously silently dropped from a cost
#: string — the standalone-verb effect handler covered "blight N" only
#: mid-sentence, never `{cost}, Blight N: <effect>`.
_BLIGHT_RE = re.compile(r"\bblight\s+(\d+)", re.IGNORECASE)
#: "Exile the top card of your library" (Thought Lash) / "Exile the top
#: four cards of your library" (Seasoned Tactician, MEC-30) — a non-mana
#: additional cost paid straight off the payer's own library, distinct from
#: `exile_self_from_hand`'s hand-zone alternative-cost shape (which the
#: engine still doesn't charge through this path — see that field's own
#: docstring) since this one always has a real battlefield source to pay it
#: from. The count word is optional (bare "top card" implies exactly one).
_EXILE_TOP_LIBRARY_RE = re.compile(
    r"exile\s+the\s+top\s+(?:(?P<n>\d+|" + "|".join(_NUMBER_WORDS) + r")\s+)?cards?\s+of\s+your\s+library",
    re.IGNORECASE,
)
#: "Put a card from your hand on top of your library" (Penance, MEC-30) — a
#: non-mana additional cost paid from hand, the chosen-card sibling of
#: `_EXILE_TOP_LIBRARY_RE`'s library-sourced cost. Charged via
#: `RulesEngine.put_hand_card_on_top_of_library`, resolved by
#: `ActivationMixin._resolve_put_hand_card_cost` (the same "chosen_ids, or
#: auto-pick" shape `_resolve_discard_cost` already uses for a plain
#: discard-N cost).
_PUT_HAND_CARD_ON_LIBRARY_RE = re.compile(
    r"put\s+a\s+card\s+from\s+your\s+hand\s+on\s+top\s+of\s+your\s+library", re.IGNORECASE
)
#: "Return a Forest you control to its owner's hand" (Quirion Ranger/Scryb
#: Ranger) — a non-mana additional cost that returns a permanent of a given
#: type the payer controls to hand, the same shape `_SACRIFICE_RE` uses for
#: "sacrifice a/an <type>" but for bounce instead of sacrifice. The type word
#: is kept as printed (singular on real cards — "Forest", not "Forests") and
#: lowercased for `continuous.has_subtype`'s case-insensitive match.
_RETURN_TO_HAND_RE = re.compile(
    r"return an?\s+([a-z]+)\s+you control to (?:its|your) owner'?s?\s*hand", re.IGNORECASE
)
#: A planeswalker loyalty ability's cost — the ``[+2]`` / ``[-3]`` / ``[0]``
#: bracket at the start of the ability (RULE 606.5c). A leading "+" or no sign
#: means add loyalty; "−"/"-" means remove it. Accepts the Unicode minus too.
_LOYALTY_RE = re.compile(r"^\s*\[\s*([+\-−]?)\s*(\d+)\s*\]")

#: RULE 702.21b: "Some ward abilities include an X in their cost and state
#: what X is equal to." A ward cost's own "where X is …" clause — recognized
#: only for the small "count of X you control"/"cards in your graveyard"
#: vocabulary `game/continuous.py`'s `count_selector` already evaluates for
#: a characteristic-defining P/T (RULE 613.7c/604.3), so both share one
#: authored selector list rather than guessing a second one. No real card
#: needs this yet (`docs/implementation-state/BACKLOG.md`) — an
#: unrecognized/absent clause leaves ``x_selector`` unset, so `{X}` stays 0
#: (RULE 107.3c's safe default) rather than guessed.
_WARD_X_SELECTOR_RE = re.compile(
    r"where x is the number of (?P<phrase>[a-z ]+?)\s*(?=[.\n]|$)", re.IGNORECASE
)
_WARD_X_SELECTOR_PHRASES: dict[str, str] = {
    "creatures you control": "creatures_you_control",
    "lands you control": "lands_you_control",
    "permanents you control": "permanents_you_control",
    "artifacts you control": "artifacts_you_control",
    "cards in your graveyard": "cards_in_your_graveyard",
}

#: Sentinel for "discard your hand" — count isn't known until pay time.
DISCARD_HAND = -1

#: Sentinel for "pay X life" (RULE 601.2b's ~ additional-cost template) — the
#: amount isn't known until pay time, since it's tied to the spell's own
#: announced X, not a printed number.
PAY_LIFE_X = -1

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

#: MEC-43 round 4 (Grim Hireling): the `ActivationCost.sacrifice_count`
#: sibling of `REMOVE_COUNTERS_X` — "Sacrifice X Treasures" isn't a printed
#: count either, it's RULE 601.2b's announce-X template applied to a
#: sacrifice cost component instead of a mana `{X}`/counter-removal one.
#: Threaded through the same `x` param `activate_ability` already carries.
SACRIFICE_COUNT_X = -1


def _word_to_int(word: str) -> int:
    word = word.strip().lower()
    if word.isdigit():
        return int(word)
    return _NUMBER_WORDS.get(word, 1)


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
    #: "Spend only mana of the chosen color to activate this ability" (Throne
    #: of Eldraine's second ability, RULE 601.2b/106.6) — a colour-lock on
    #: *this ability's own* mana cost (as opposed to a spend restriction on
    #: mana the ability *produces*): the whole mana cost must be paid with
    #: mana of the source's `GameObject.chosen_color`. Enforced by
    #: `GameEngine._can_pay_activation_cost`/`_pay_activation_cost`.
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
    #: hand-authored only (`game/ability_catalogue.py`); no oracle-text
    #: grammar for it yet.
    dynamic_reduction: Optional[dict[str, Any]] = None
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
    raw: str = ""

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
            or self.behold_exile
            or self.behold_two_shared_type
            or self.blight
            or self.tap_others
            or self.sacrifice_count
            or self.add_counters_cost
            or self.exile_self_from_hand
            or self.return_to_hand
            or self.return_to_hand_count
            or self.sacrifice_filter
            or self.exile_hand_card_color
            or self.crew_power
            or self.saddle_power
            or self.station
            or self.sacrifice_or_discard
        )

    def label(self) -> str:
        """A short "{T}, Sacrifice a creature, Pay 2 life" style summary."""
        parts: list[str] = []
        if self.mana.symbols:
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
            else:
                what = f"a {self.sacrifice}"
            parts.append(f"Sacrifice {what}")
        if self.exile_creature:
            parts.append("Exile a creature you control")
        if self.pay_life:
            parts.append("Pay X life" if self.pay_life == PAY_LIFE_X else f"Pay {self.pay_life} life")
        if self.pay_energy:
            parts.append(f"Pay {'{E}' * self.pay_energy}")
        if self.discard:
            parts.append("Discard your hand" if self.discard == DISCARD_HAND
                         else f"Discard {self.discard} card(s)")
        if self.discard_self:
            parts.append("Discard this card")
        if self.remove_counters:
            kind, count = self.remove_counters
            if count == REMOVE_COUNTERS_X:
                parts.append(f"Remove X {kind} counter(s)")
            elif count == REMOVE_COUNTERS_ANY:
                parts.append(f"Remove any number of {kind} counters")
            else:
                parts.append(f"Remove {count} {kind} counter(s)")
        if self.exile_from_graveyard:
            parts.append(f"Exile {self.exile_from_graveyard} other card(s) from your graveyard")
        if self.collect_evidence:
            parts.append(f"Collect evidence {self.collect_evidence}")
        if self.forage:
            parts.append("Forage")
        if self.behold:
            parts.append(f"Behold a {self.behold}")
        if self.behold_exile:
            parts.append(f"Behold a {self.behold_exile} and exile it")
        if self.behold_two_shared_type:
            parts.append("Choose a creature type and behold two creatures of that type")
        if self.blight:
            parts.append(f"Blight {self.blight}")
        if self.tap_others:
            count, subtype = self.tap_others
            parts.append(f"Tap {count} untapped {subtype}(s) you control")
        if self.sacrifice_count:
            count, subtype = self.sacrifice_count
            parts.append(f"Sacrifice {count} {subtype}(s)")
        if self.add_counters_cost:
            kind, count = self.add_counters_cost
            parts.append(f"Put {count} {kind} counter(s) on this")
        if self.exile_self_from_hand:
            parts.append("Exile this card from your hand")
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
        return ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mana": self.mana.raw,
            "taps_self": self.taps_self,
            "untaps_self": self.untaps_self,
            "sacrifice": self.sacrifice,
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
            "behold_exile": self.behold_exile,
            "behold_two_shared_type": self.behold_two_shared_type,
            "blight": self.blight,
            "tap_others": list(self.tap_others) if self.tap_others else None,
            "sacrifice_count": list(self.sacrifice_count) if self.sacrifice_count else None,
            "add_counters_cost": list(self.add_counters_cost) if self.add_counters_cost else None,
            "exile_self_from_hand": self.exile_self_from_hand,
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
    if "pay_life" in cost:
        value = cost["pay_life"]
        parsed.pay_life = PAY_LIFE_X if value == "x" else int(value)
    if "pay_energy" in cost:
        parsed.pay_energy = int(cost["pay_energy"])
    if "note_spent_color" in cost:
        parsed.note_spent_color = bool(cost["note_spent_color"])
    if "discard" in cost:
        parsed.discard = int(cost["discard"])
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
            parsed.exile_from_graveyard = int(raw.get("count", 0))
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
        # `ability_catalogue.py` has no marker to strip, so it can just
        # set the field on its own `cost` dict (Frodo, Sauron's Bane).
        parsed.activation_condition = dict(cost["activation_condition"])
    if "unattach_self" in cost:
        parsed.unattach_self = bool(cost["unattach_self"])
    if cost.get("unattach_grant_source_id") is not None:
        parsed.unattach_grant_source_id = int(cost["unattach_grant_source_id"])
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
    """Regex a cost string into an `ActivationCost` (the "very REGEX way")."""
    # Only look at the cost — the part before the first colon (RULE 602.1).
    cost_text = text.split(":", 1)[0] if ":" in text else text

    cost = ActivationCost(raw=cost_text.strip())

    # A loyalty ability's whole cost is its ``[±N]`` bracket (RULE 606.5c);
    # when present it is the entire cost, so return it directly.
    loyalty = _LOYALTY_RE.match(cost_text)
    if loyalty:
        magnitude = int(loyalty.group(2))
        sign = loyalty.group(1)
        cost.loyalty = -magnitude if sign in ("-", "−") else magnitude
        return cost

    # Mana + the {T}/{Q} symbols share the {...} syntax; split them apart.
    mana_tokens: list[str] = []
    energy_pips = 0
    for token in _BRACE_RE.findall(cost_text):
        upper = token.strip().upper()
        if upper == "T":
            cost.taps_self = True
        elif upper == "Q":
            cost.untaps_self = True
        elif upper == "E":
            # RULE 122: "Pay {E}{E}..." — each repeated pip pays one energy
            # counter; `_PAY_ENERGY_WORD_RE` below overrides this count for
            # the differently-worded "Pay <word> {E}" spelled-out form.
            energy_pips += 1
        else:
            mana_tokens.append(token.strip())
    if mana_tokens:
        cost.mana = ManaCost.parse("".join(f"{{{t}}}" for t in mana_tokens))
    if energy_pips:
        word_pay = _PAY_ENERGY_WORD_RE.search(cost_text)
        cost.pay_energy = _NUMBER_WORDS[word_pay.group("n").lower()] if word_pay else energy_pips
    if cost.mana.has_variable:
        # RULE 702.21b: a ward cost may define what its own {X} means.
        selector_match = _WARD_X_SELECTOR_RE.search(cost_text)
        if selector_match:
            cost.x_selector = _WARD_X_SELECTOR_PHRASES.get(
                selector_match.group("phrase").strip().lower()
            )

    if _EXILE_CREATURE_RE.search(cost_text):
        cost.exile_creature = True
    if _SACRIFICE_CREATURE_ARTIFACT_OR_LAND_RE.search(cost_text):
        # PAR-13: "Sacrifice a creature, artifact, or land [of your/their
        # choice]." (Tomb of Annihilation's "Sandfall Cell") — the one
        # compound-type sacrifice cost any shipped card needs, ahead of the
        # generic single-word `_SACRIFICE_RE` below (which would otherwise
        # only see "a creature" and drop the rest of the list).
        cost.sacrifice = "creature_artifact_or_land"
    else:
        sac = _SACRIFICE_RE.search(cost_text)
        if sac:
            whole = sac.group(1).lower()
            if whole.startswith("this") or whole == "~":
                cost.sacrifice = "self"
            else:
                cost.sacrifice = (sac.group(2) or sac.group(3) or "permanent").lower()

    life = _PAY_LIFE_RE.search(cost_text)
    if life:
        cost.pay_life = int(life.group(1))

    if _DISCARD_SELF_RE.search(cost_text):
        cost.discard_self = True
    else:
        discard = _DISCARD_RE.search(cost_text)
        if discard:
            phrase = discard.group(1).lower()
            if "hand" in phrase:
                cost.discard = DISCARD_HAND
            else:
                cost.discard = _word_to_int(phrase.split()[0])

    any_counters = _REMOVE_ANY_COUNTERS_RE.search(cost_text)
    if any_counters:
        cost.remove_counters = (any_counters.group(1).lower(), REMOVE_COUNTERS_ANY)
    else:
        counters = _REMOVE_COUNTERS_RE.search(cost_text)
        if counters:
            amount_word = counters.group(1).strip().lower()
            count = REMOVE_COUNTERS_X if amount_word == "x" else _word_to_int(amount_word)
            cost.remove_counters = (counters.group(2).lower(), count)

    exile_graveyard = _EXILE_GRAVEYARD_RE.search(cost_text)
    if exile_graveyard:
        cost.exile_from_graveyard = _word_to_int(exile_graveyard.group(1))

    collect_ev = _COLLECT_EVIDENCE_RE.search(cost_text)
    if collect_ev:
        cost.collect_evidence = int(collect_ev.group(1))

    if _FORAGE_RE.search(cost_text):
        cost.forage = True

    blight_cost = _BLIGHT_RE.search(cost_text)
    if blight_cost:
        cost.blight = int(blight_cost.group(1))

    exile_top = _EXILE_TOP_LIBRARY_RE.search(cost_text)
    if exile_top:
        n = exile_top.group("n")
        cost.exile_top_of_library = _word_to_int(n) if n else 1

    if _PUT_HAND_CARD_ON_LIBRARY_RE.search(cost_text):
        cost.put_hand_card_on_library = True

    tap_others = _TAP_OTHERS_RE.search(cost_text)
    if tap_others:
        count = _word_to_int(tap_others.group(1))
        cost.tap_others = (count, _singularize(tap_others.group(2).lower()))

    add_counter = _ADD_COUNTER_COST_RE.search(cost_text)
    if add_counter:
        cost.add_counters_cost = (add_counter.group(1).lower(), 1)

    if _EXILE_FROM_HAND_RE.search(cost_text):
        cost.exile_self_from_hand = True

    return_to_hand = _RETURN_TO_HAND_RE.search(cost_text)
    if return_to_hand:
        cost.return_to_hand = return_to_hand.group(1).lower()

    return cost
