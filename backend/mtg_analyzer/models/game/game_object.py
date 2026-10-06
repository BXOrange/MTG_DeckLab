"""Zones and in-game card instances (RULE 400 zones, RULE 110 permanents).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R1.3 (Game State — Zones,
Stack, permanents), docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md.

A `Card` (models/card.py) is the immutable *definition* of a card — its
printed characteristics. A `GameObject` is one *instance* of that card
inside a running game: a specific object in a specific zone with its own
mutable state (tapped, damage, counters, summoning sickness) and its own
identity, so two copies of the same card, or the same physical card seen
in two zones over time, stay distinguishable. This mirrors the rules'
distinction between a card and the object it becomes in play.
"""

from __future__ import annotations

import itertools
import re
from enum import Enum
from typing import Any, Optional

from ..cards.card import Card


class Zone(str, Enum):
    """The zones a game object can occupy (RULE 400)."""

    LIBRARY = "library"
    HAND = "hand"
    BATTLEFIELD = "battlefield"
    GRAVEYARD = "graveyard"
    STACK = "stack"
    EXILE = "exile"
    COMMAND = "command"


#: Process-wide counter giving every GameObject a unique instance id.
_instance_counter = itertools.count(1)


def _combat_display_keywords(
    card: Card,
    granted: Optional[set[str]] = None,
    removed: Optional[set[str]] = None,
    granted_protections: Optional[set[str]] = None,
) -> list[str]:
    """Combat/evasion keyword labels for a card's board badges, including any
    granted by a layer-6 static ability (RULE 613.7f) and excluding any it
    stripped ("loses <keyword>"). ``granted_protections`` is the same layer's
    standing RULE 702.16 protection grant, which the badge row shows even on
    a permanent whose printed text mentions no protection at all.

    Local (function-scoped) import of the pure `game.combat` recognition so
    the model layer gains no import-time dependency on `game/` (RULE-keyword
    recognition lives with the combat rules that consume it)."""
    from ...game.combat import display_keywords

    return display_keywords(card, granted, removed, granted_protections)


def _saga_final_chapter_number(card: Card) -> Optional[int]:
    """A Saga's final chapter number (RULE 714.2d) for the board's chapter
    badge — ``None`` if the oracle text has no recognizable chapter line.

    Local import of the pure chapter-numeral grammar (`parser/oracle/
    catalogue/saga.py` — no `game/` imports itself), the same one
    `RulesEngine._saga_final_chapter` (`game/rules_engine.py`) uses, so the
    two never drift apart."""
    from ...parser.oracle.catalogue.saga import all_chapter_numbers

    return max(all_chapter_numbers(card.oracle_text or ""), default=0) or None


class GameObject:
    """One instance of a card in a game, with its mutable in-play state."""

    def __init__(
        self,
        card: Card,
        owner_id: str,
        zone: Zone = Zone.LIBRARY,
        controller_id: Optional[str] = None,
        is_commander: bool = False,
        is_token: Optional[bool] = None,
    ) -> None:
        self.instance_id: int = next(_instance_counter)
        self.card = card
        #: The front face this object was created with (RULE 712.2). ``card``
        #: is swapped to the back face by `transform` and back by
        #: `transform_back`; this keeps the front so the swap is reversible.
        self._front_card = card
        #: Whether a double-faced permanent is currently on its back face
        #: (RULE 712.8). Combat/continuous read `card`, so a transform is just
        #: this swap — everything downstream sees the active face.
        self.transformed: bool = False
        #: RULE 715.2b: while this object's Adventure instant/sorcery half is
        #: on the stack, the creature's pre-cast face snapshot (`snapshot_face`)
        #: is stashed here so resolution can restore it before exiling —
        #: distinct from a rejected-cast rollback, which restores immediately
        #: and never reaches this field. None otherwise.
        self.adventure_snapshot: Optional[dict[str, Any]] = None
        #: RULE 715.3d: set when this object's Adventure half resolves and it
        #: is exiled instead of going to the graveyard — the card may be cast
        #: as the creature from exile any time thereafter. Cleared once cast.
        self.adventure_castable: bool = False
        #: RULE 722.3a: the "prepared" designation on a permanent with a
        #: prepare spell — set by `RulesEngine.make_prepared` (some other
        #: ability's "~ becomes prepared" effect), which also creates an
        #: exiled token copy of the prepare spell. Cleared the instant that
        #: copy is actually cast (RULE 722.3c), or by any other "becomes
        #: unprepared" effect (RULE 722.3b) — either way the copy then loses
        #: its RULE 704.5d token-cleanup exemption on the very next SBA pass.
        self.prepared: bool = False
        #: RULE 722.3c: on a prepared *copy* (a token sitting in exile, never
        #: on a normal permanent), the `instance_id` of the source permanent
        #: it's linked to — the copy is exempt from the RULE 704.5d token
        #: cleanup only for as long as that source stays on the battlefield
        #: with `prepared` still set. None on every other object.
        self.prepared_source_id: Optional[int] = None
        #: RULE 707.9 (PAR-124, Spellchain Scatter's "conjure a duplicate of
        #: that spell into your hand"): a token deliberately created *in
        #: hand* rather than on the stack or battlefield, meant to persist
        #: there like any other card until cast or discarded — unlike a
        #: `copy_spell` stack copy (reaped the instant it leaves the stack,
        #: RULE 704.5d), this one's whole point is to survive off the
        #: battlefield, so `_remove_stranded_tokens` exempts it the same way
        #: `prepared_source_id`/`GameState.free_cast_instance_ids` already
        #: exempt their own off-battlefield tokens.
        self.conjured_into_hand: bool = False
        #: RULE 702.33b: how many times Kicker was paid when this spell was
        #: cast — 0 (not kicked), 1 for a plain Kicker, or 0..N for
        #: Multikicker. Set once at cast time by `GameEngine._cast_current_face`
        #: and left on the object afterward as a record of what was paid.
        self.kicker_count: int = 0
        # RULE 601.2b/602.2b: no X has been announced on a fresh object.
        self.x_paid: int = 0
        #: RULE 702.33b: the value announced for Kicker's own ``{X}`` (PAR-7,
        #: Emblazoned Golem-shaped — a Kicker cost that is itself variable,
        #: distinct from the *spell's* own announced X `_apply_entry_counters`
        #: reads via ``x_paid``) — 0 unless kicked with a nonzero X. Set once
        #: at cast time by `GameEngine._cast_current_face` alongside
        #: ``kicker_count``.
        self.kicker_x_paid: int = 0
        #: RULE 702.27a: whether Buyback's additional cost was paid when this
        #: spell was cast — if so, `RulesEngine.resolve_top_of_stack` returns
        #: it to hand instead of the graveyard, then clears this flag.
        self.buyback_paid: bool = False
        #: RULE 601.2b (PAR-30): whether a spell's *optional* "as an
        #: additional cost to cast this spell, you may <…>." clause was paid
        #: when this spell was cast — read by a following
        #: `ConditionalEffect(condition={"additional_cost_paid": …})` for
        #: "if this spell's additional cost was paid, <effect>." /
        #: "… unless <its> additional cost was paid." (Katara Seeking
        #: Revenge, Ruinous Waterbending, …). Kicker's own ``buyback_paid``/
        #: ``kicker_count`` shape for a different optional additional cost.
        #: A *mandatory* additional cost sets it True too (it was paid).
        self.additional_cost_paid: bool = False
        #: RULE 702.194: this spell's optional Teamwork additional cost was
        #: paid.  Kept on the stack object so modal overrides and conditional
        #: riders consult the actual cast, never merely the printed keyword.
        self.teamwork_paid: bool = False
        #: RULE 202.1/601.2h: how much mana was actually *spent* casting this
        #: spell — the converted value of the cost that was paid, 0 for a
        #: free/alternative-{0} cast. Reassigned on every cast (like
        #: `cast_via_flashback`) and also stamped onto the `SPELL_CAST` event
        #: as ``mana_spent``. "If no mana was spent to cast it" (Lavinia,
        #: Azorius Renegade / Boromir, Warden of the Tower) reads it; the
        #: object copy exists because a resolving effect can need it after
        #: the spell has already left the stack. Deliberately *not* the same
        #: as the event's ``free`` flag — see `EventType.SPELL_CAST`.
        self.mana_spent_to_cast: int = 0
        #: RULE 702.108a Converge's own count: which of the five colors
        #: (never colorless) actually paid for this spell's cost — every
        #: colored pip's own color plus whatever colors happened to cover
        #: its generic portion, diffed off the payer's `ManaPool` before vs.
        #: after payment (`RulesEngine.cast_spell`). Empty for a free/
        #: alternative-cost cast, same as `mana_spent_to_cast`. Read by
        #: `SearchLibraryEffect.mana_value_from`'s ``"colors_spent_to_cast"``
        #: source (Bring to Light, MEC-41) via ``len(...)``.
        self.colors_spent_to_cast: frozenset = frozenset()
        #: RULE 702.43a: a spell that "gains sunburst" (Lux Artillery) — set while it is on the stack,
        #: consumed (and cleared) by `RulesEngine._apply_entry_counters` when it enters.
        self.gains_sunburst: bool = False
        #: Counters this object is about to enter with *in addition* to its own entry-counter clause, stamped
        #: just before it is put onto the battlefield and consumed (then cleared) by
        #: `RulesEngine._apply_entry_counters` — "…it enters with three additional +1/+1 counters on it"
        #: (Turntimber Symbiosis).
        self.entry_bonus_counters: dict[str, int] = {}
        #: Conditional entry riders, evaluated after entry-copy choices.
        self.entry_bonus_creature_counters: dict[str, int] = {}
        #: Adamant's per-colour sibling of ``colors_spent_to_cast``.  This
        #: preserves *how much* of each WUBRG colour paid the spell, not just
        #: whether that colour appeared at least once.
        self.mana_by_color_spent_to_cast: dict[str, int] = {}
        #: The snow sibling of `colors_spent_to_cast` (MEC-43 round 3,
        #: Search for Glory's "gain 1 life for each {S} spent to cast this
        #: spell") — how much mana tapped from a snow-typed source (RULE
        #: 205.4g) paid this spell's cost, diffed off `ManaPool.snow_pool`
        #: the same before/after way, not a real per-symbol {S} in the
        #: printed cost (this engine has no snow-typed mana pips at all;
        #: "{S} spent" always means snow-*sourced* mana of any color/type).
        #: Read via `continuous.count_selector`'s ``"snow_mana_spent_to_
        #: cast"`` entry. 0, same as `mana_spent_to_cast`, for a free/
        #: alternative-cost cast.
        self.mana_spent_to_cast_snow: int = 0
        #: Mana from a Treasure used for this cast (RULE 601.2h). Read by
        #: PAR-120's Treasure payment condition on the resolving spell or its
        #: enters trigger. The pool's source buckets make this an actual
        #: payment fact, not a guess from which permanents were tapped.
        self.mana_spent_to_cast_treasure: int = 0
        #: Mana from creature-sourced mana abilities spent on this spell's cast (Inga and Esika).
        self.mana_spent_to_cast_creature: int = 0
        #: The same fact for this permanent's most recent activation (Jetmir's
        #: Fixer) — stamped at payment like `counters_removed_as_cost`.
        self.mana_spent_to_activate_treasure: int = 0
        #: Whether this permanent actually went through `RulesEngine.
        #: cast_spell`/`cast_without_paying` (RULE 601.2), as opposed to
        #: being put onto the battlefield directly (a search/reanimation
        #: destination, a token, cheated in by "you may put ~ onto the
        #: battlefield") — "When ~ enters, **if you cast it**, `<effect>`."
        #: (Rocco, Cabaretti Caterer-shaped, ~57 cache-wide cards). Reset
        #: `False` at construction so a token/searched permanent defaults
        #: correctly with no extra call needed anywhere.
        self.was_cast: bool = False
        #: Whether this spell was cast from exile (RULE 601.2a's zone-of-
        #: origin, the Foretell/Suspend/Adventure-rebound idiom) — "If this
        #: spell was cast from exile, `<effect>` instead." (Delayed Blast
        #: Fireball-shaped). Stamped alongside `mana_spent_to_cast` at cast
        #: time (`RulesEngine.cast_spell`), same "survives past the object
        #: leaving the stack" reasoning.
        self.cast_from_exile: bool = False
        #: RULE 702.143: set by Foretell's special action and retained on
        #: the subsequently cast spell for "if this spell was foretold".
        self.foretold: bool = False
        #: The internal turn on which this card was foretold.  Foretell only
        #: permits casting it on a later turn.
        self.foretold_turn: Optional[int] = None
        #: RULE 601.3a: whether this spell was cast at a time a sorcery
        #: couldn't have been (not the caster's main phase, a nonempty
        #: stack, or not their own turn) — legal only via a flash grant
        #: (`conditional_flash`, `combat.has(obj, "flash")`, …), not RULE
        #: 601.3a's own default window. "If you cast it any time a sorcery
        #: couldn't have been cast, `<downside>`." (Necromancy-shaped, MEC-44)
        #: — stamped once at cast time (`GameEngine._cast_current_face`,
        #: alongside `mana_spent_to_cast`) since the board (and so the
        #: answer) changes by the time anything reads it later; consumed by
        #: `EffectSpec.condition`'s ``"cast_outside_sorcery_speed"`` gate.
        self.cast_outside_sorcery_speed: bool = False
        #: Addendum's "if you cast this spell during your main phase" (RULE
        #: 505.1) — stamped beside `cast_outside_sorcery_speed`, stack or not.
        self.cast_during_your_main_phase: bool = False
        #: RULE 702.94a Soulbond: the `instance_id` of the creature this one
        #: is paired with, held on **both** objects, or ``None`` when
        #: unpaired. A genuine piece of game state rather than a continuous
        #: effect — the *grant* a pair confers is a layer-6 static that reads
        #: this, and RULE 702.94c breaks the pair the moment either creature
        #: leaves the battlefield or changes controller (swept by
        #: `RulesEngine.check_state_based_actions`).
        self.paired_with: Optional[int] = None
        #: RULE 702.140b: whether this spell was cast for its Mutate cost —
        #: set at cast time by `GameEngine._cast_current_face` and consumed
        #: by `RulesEngine._resolve_permanent_spell`, which merges it onto
        #: its target instead of letting it enter the battlefield as its own
        #: permanent. Reassigned on every cast, like `cast_via_flashback`.
        self.cast_via_mutate: bool = False
        #: RULE 702.140b: whether that Mutate cast chose "under" rather than
        #: "over" — the pile then keeps the *target's* characteristics and
        #: only gains this card's abilities. Set alongside `cast_via_mutate`
        #: and consumed by the same resolution branch.
        self.mutate_under: bool = False
        #: RULE 701.x Bargain: whether the optional "sacrifice an artifact,
        #: enchantment, or token as you cast this spell" additional cost was
        #: paid — read by `EffectSpec.condition`'s ``"bargained"`` gate, the
        #: same shape Kicker's own ``"kicked"`` condition uses.
        self.bargained: bool = False
        #: RULE 702.174k (MEC-106): the caster promised a gift — declared the
        #: intention to pay the gift cost while casting — and to whom. Stamped by
        #: `GameEngine.cast_spell` next to `bargained`; read by the ``gift_promised``
        #: flag condition ("if the gift was promised"), by the RULE 702.174b ETB
        #: trigger on a permanent, and by `RulesEngine.give_gift` at resolution.
        self.gift_promised: bool = False
        self.gift_recipient_id: Optional[str] = None
        #: RULE 702.35: the spell was cast by paying its madness cost (cast from exile, having been
        #: exiled by `RulesEngine._maybe_madness`) — stamped at cast time by `RulesEngine.cast_spell`
        #: and read by the ``madness_cost_paid`` flag condition ("if its madness cost was paid").
        self.madness_cost_paid: bool = False
        #: RULE 702.117: this spell was cast for its Surge cost (stamped by
        #: `GameEngine.cast_spell`, read by the ``surge_cost_paid`` flag
        #: condition — "if its surge cost was paid").
        self.surge_cost_paid: bool = False
        #: RULE 701.20a: this card was exiled **face down** (Beseech the
        #: Mirror's "search your library for a card, exile it face down").
        #: A face-down card in exile has no characteristics anyone but its
        #: owner may look at, so the session view hides its identity from
        #: everyone else (`to_dict`). Cleared the moment it leaves exile or
        #: is turned face up — nothing keeps a card face down across a zone
        #: change (RULE 400.7).
        self.face_down_in_exile: bool = False
        self.face_down_exile_viewers: set[str] = set()
        self.hideaway_source_id: Optional[int] = None
        self.hideaway_exile_ids: set[int] = set()
        self.hideaway_incarnation: int = 0
        #: RULE 701.42a / 712: whether this permanent is a **melded**
        #: permanent — a single object representing two cards, its
        #: characteristics coming from the meld pair's back-face result card
        #: (`RulesEngine.meld`). ``melded_components`` holds the two front-face
        #: `GameObject`s in limbo (`zone` ``None``); RULE 712.19 —
        #: `RulesEngine._split_melded_after_move` swaps this one permanent
        #: back for those two the moment it leaves the battlefield.
        self.is_melded: bool = False
        self.melded_components: list["GameObject"] = []
        #: RULE 708.2: whether this object is **face down** — a 2/2 creature
        #: with no text, no name, no subtypes and no mana cost (morph/
        #: disguise cast face down, or a manifested/cloaked card put onto the
        #: battlefield that way). Unlike `face_down_in_exile` above (which
        #: only hides a card's identity in the view), this is a genuine
        #: characteristic change: `card` itself is swapped for the synthetic
        #: face-down face (`game/face_down.py`), so the layer engine, combat
        #: and the board all read the 2/2 with no special case. Cleared by
        #: `turn_face_up`.
        self.face_down: bool = False
        #: Which rule put this object face down — ``"morph"``/``"disguise"``
        #: (RULE 702.37/702.168, cast face down) or ``"manifest"``/
        #: ``"cloak"`` (RULE 701.40/701.58, put onto the battlefield face
        #: down). It decides how the permanent may be turned face up
        #: (`game/face_down.py`'s `turn_face_up_options`), which is why the
        #: *way in* has to be remembered rather than just the fact.
        self.face_down_kind: Optional[str] = None
        #: The face-up `Card` + catalogue-derived bindings stashed while this
        #: object is face down (`game/copy_mechanics.py`'s `snapshot_face`
        #: shape, the same bundle a transform/copy swap saves). ``None``
        #: unless `face_down` is set; restored wholesale by `turn_face_up`,
        #: which is what makes RULE 708.8's "it regains its normal
        #: characteristics" a single assignment rather than a re-parse.
        self._face_up_snapshot: Optional[dict[str, Any]] = None
        #: RULE 702.103 Bestow: this creature card was cast for its bestow
        #: cost, so for as long as it stays attached it's an Aura
        #: enchantment with "enchant creature" and is **not** a creature
        #: (702.103b/d). A synthetic ``parametric_keywords["enchant"]``
        #: entry is added alongside this flag (`RulesEngine._begin_bestow`)
        #: so every Aura code path — `_attachment_kind`,
        #: `targeting.spell_target_specs`, `_resolve_permanent_spell`'s
        #: attach branch — treats it as an ordinary Aura with no special
        #: case. Cleared, and the synthetic entry removed, the moment it
        #: stops being attached (RULE 702.103e/f — `_end_bestow`, driven by
        #: `_sba_check_unbestow` and the un-attach paths), at which point it
        #: is a creature again.
        self.bestowed: bool = False
        #: RULE 702.140c Mutate: the abilities merged in from *under* this
        #: permanent — the oracle text of every card mutated onto it, kept as
        #: text so `effect_binder.bind_from_catalogue` can re-derive real
        #: abilities from it exactly as it does for a printed face. Empty for
        #: every permanent that was never a mutate host.
        self.merged_oracle_text: list[str] = []
        #: RULE 601.2b: the mana value of the permanent sacrificed to pay this
        #: spell's *additional* cost ("as an additional cost to cast this
        #: spell, sacrifice a creature" — Eldritch Evolution/Neoform), or
        #: ``None`` when no such cost was paid. `StackItem.x` only ever
        #: threads a spell's *announced* {X}, so a resolving effect whose
        #: magnitude is "the sacrificed creature's mana value" needs its own
        #: channel; read by `SearchLibraryEffect`'s ``mana_value_from``.
        self.sacrificed_cost_mana_value: Optional[int] = None
        self.sacrificed_cost_card_types: list[str] = []
        #: The card types of the card(s) discarded as this spell's additional cost ("If the discarded card wasn't a land card", Grab the
        #: Prize) — stamped by `GameEngine._pay_additional_cast_cost`, read by `effect_conditions`' ``discarded_cost_card_is``.
        self.discarded_cost_card_types: list[str] = []
        self.sacrificed_cost_was_suspected: bool = False
        #: The *power* sibling of the field above (MEC-43, Altar of
        #: Dementia: "Sacrifice a creature: target player mills cards equal
        #: to the sacrificed creature's power.") — stamped alongside it by
        #: `GameEngine._pay_ability_cost`'s own sacrifice-cost branch, read
        #: back by `continuous.count_selector`'s ``"sacrificed_cost_power"``
        #: entry.
        self.sacrificed_cost_power: Optional[int] = None
        #: The toughness sibling, retained as last-known information for an
        #: activated ability whose sacrifice cost names it (Animal Boneyard).
        self.sacrificed_cost_toughness: Optional[int] = None
        #: RULE 702.184a/721 Station: the power of the single other creature
        #: tapped to pay this permanent's own Station cost — the exact-one-
        #: creature sibling of `sacrificed_cost_power` above, stamped fresh
        #: by `GameEngine._pay_activation_cost`'s ``station`` branch and read
        #: back by `continuous.count_selector`'s ``"station_tapped_power"``
        #: entry (`AddCountersEffect.amount_from_count_selector`, the charge
        #: counters Station itself puts on this permanent). ``None`` when
        #: nothing has been tapped to pay it yet.
        self.station_tapped_power: Optional[int] = None
        #: RULE 106.4-adjacent: the WUBRG/C type of mana this permanent's
        #: own activated ability most recently had spent to pay it (Jeweled
        #: Amulet, MEC-43: "Note the type of mana spent to pay this
        #: activation cost.") — stamped from `Player.mana_pool.last_
        #: payment_types` by `GameEngine._pay_ability_cost` when
        #: `ActivationCost.note_spent_color` is set. ``None`` until noted at
        #: least once.
        self.noted_mana_color: Optional[str] = None
        #: RULE 702.34a: whether this spell was cast from the graveyard via
        #: Flashback — if so, `RulesEngine.resolve_top_of_stack` exiles it
        #: instead of sending it to the graveyard, then clears this flag.
        self.cast_via_flashback: bool = False
        #: RULE 702.138 (PAR-60, Woe Strider): whether this permanent spell
        #: was cast for its Escape cost — read by a hand-authored ETB to
        #: gate an "enters with N +1/+1 counters" rider. Reassigned every
        #: cast, like `cast_via_flashback`.
        self.cast_via_escape: bool = False
        self.was_cast_from_hand: bool = False
        #: RULE 702.74a (MEC-42): whether this permanent spell was cast for
        #: its Evoke cost — if so, `RulesEngine._resolve_permanent_spell`
        #: sacrifices it right after it enters the battlefield (a
        #: consequence, not a replacement — its own ETB trigger still
        #: fires first), then clears this flag.
        self.blitz_cost_paid: bool = False  # RULE 702.152, through stack→battlefield.
        self.cast_via_evoke: bool = False
        #: RULE 702.109c/d (PAR-26): whether this creature spell was cast
        #: for its Dash cost — if so, `RulesEngine`'s permanent-spell
        #: resolution grants it haste and arms a "return to owner's hand at
        #: the beginning of the next end step" delayed trigger right after
        #: it enters, then clears this flag (same shape as `cast_via_evoke`).
        self.cast_via_dash: bool = False
        #: RULE 702.51c — instance ids of the creatures tapped to pay this spell's Convoke ("each creature that
        #: convoked this spell …", Lethal Scheme). Stamped by `_consume_cast_help`; reset as a new object.
        self.convoked_by_ids: list = []
        #: RULE 601.2a — the zone this object was cast from ("graveyard", "hand", …); ``None`` if never cast.
        #: Stamped at cast time and carried on its `ENTERS_BATTLEFIELD` event as ``cast_from_zone`` ("…or was cast
        #: from a graveyard", Kotis, Sibsig Champion).
        self.cast_from_zone: Optional[str] = None
        #: RULE 702.35 (PAR-26): whether this card has Madness — set at
        #: bind alongside `alt_cast_cost` (the madness cost). `draw_discard_
        #: mixin._maybe_madness` reads it to exile the card on discard
        #: rather than sending it to the graveyard, and to arm the "to
        #: graveyard if still exiled at the next end step" delayed trigger.
        self.madness: bool = False
        #: RULE 702.35b (PAR-26): set while this Madness card sits in exile
        #: after a discard — `_offer_cast` reads it (together with a live
        #: ``zone == EXILE`` check) to offer only the madness-cost cast, not
        #: the printed-cost one the `temp_play_permissions` window would
        #: otherwise allow.
        self.madness_exiled: bool = False
        #: RULE 702.94 (PAR-26): whether this card has Miracle — set at bind
        #: alongside `alt_cast_cost` (the miracle cost). `draw_discard_mixin.
        #: _arm_miracle` sets `miracle_armed` when it's the first card drawn
        #: this turn; `_offer_cast` offers the miracle-cost cast only while
        #: `miracle_armed` (torn down at cleanup).
        self.miracle: bool = False
        self.miracle_armed: bool = False
        #: RULE 702.62 (MEC-42, Delay): whether this object has Suspend
        #: *granted* onto it rather than printed ("If it doesn't have
        #: suspend, it gains suspend.") — `_has_suspend` (`game/rules/
        #: triggers_mixin.py`) reads this alongside `parametric_keywords`'s
        #: own printed "suspend" entry so `_collect_suspend_triggers` treats
        #: either source identically. Never reset per-cast like
        #: `cast_via_evoke` above — once granted it's a standing
        #: characteristic of the object for as long as it exists, mirroring
        #: `has_rebound`.
        self.granted_suspend: bool = False
        #: RULE 702.62a's third ability ("If you cast a creature spell this
        #: way, it gains haste…"): stamped by `SuspendUpkeepEffect` right
        #: before it opens the free-cast window (`grant_free_cast_window_
        #: from_exile`), consumed by `RulesEngine._resolve_permanent_spell`
        #: exactly like `cast_via_evoke` above — set, read once at
        #: resolution, cleared.
        self.granted_suspend_haste: bool = False
        #: Lurrus of the Dream-Den-shaped: the turn number this spell was
        #: cast via a standing graveyard-cast permission
        #: (`game/graveyard_cast.py`), or ``None`` if it wasn't. Consulted
        #: by `RulesEngine._move_to_graveyard` — while it still equals the
        #: *current* turn number, a graveyard-bound move for this object is
        #: exiled instead (the permission source's own trailing "if a spell
        #: cast this way would be put into a graveyard this turn, exile it
        #: instead" clause). Reassigned (not just set) on every cast, like
        #: `cast_via_flashback`, so a later normal recast this same turn
        #: clears a stale value rather than leaving it to misfire.
        self.cast_via_graveyard_cast_permission_until_turn: Optional[int] = None
        #: RULE 702.88b: whether this card has Rebound — a printed-
        #: characteristic-like marker, bound once from `AbilitySpec.rebound`
        #: (`game/binding/core.py`) and never reset, unlike the transient
        #: flags below. Ephemerate-shaped.
        self.has_rebound: bool = False
        #: RULE 702.88b: set by `RulesEngine.cast_spell` when a `has_rebound`
        #: card is cast *from hand* — `resolve_top_of_stack` checks this to
        #: exile the card instead of routing it to the graveyard (and arm
        #: the delayed free-cast window), then clears it. Left ``False``
        #: when recast later from exile via that same window, so the second
        #: cast resolves as an ordinary spell (Rebound doesn't repeat).
        self.rebound_pending: bool = False
        self.owner_id = owner_id
        #: Who currently controls the object; defaults to its owner
        #: (RULE 108.4). Control can change but ownership can't.
        self.controller_id = controller_id or owner_id
        self.zone = zone
        #: Whether this in-play object is a token (RULE 111). Stored, not
        #: derived from `card.is_token`, because a *token copy* of a real card
        #: carries a nontoken card definition yet is still a token — and the
        #: rules-critical consequence (a token ceases to exist as a state-based
        #: action once it leaves the battlefield, RULE 704.5d) hangs off this
        #: flag, not the printed definition. Defaults to the card's own token-ness.
        self.is_token: bool = card.is_token if is_token is None else is_token
        #: Whether this object is a commander (RULE 903.6) — governs whether
        #: its owner may move it into the command zone instead of wherever
        #: it would otherwise go when it would leave play (RULE 903.9, see
        #: `RulesEngine._commander_zone_choice`/`_resume_commander_zone`).
        self.is_commander = is_commander
        #: RULE 903.9a: set the instant this commander lands in a graveyard
        #: or exile zone, offering its owner a one-time SBA choice to move it
        #: to the command zone instead; cleared the moment that choice opens
        #: (`RulesEngine._sba_pass`), so it's a transient "just arrived, not
        #: yet offered" marker, not a persistent commander-ness fact.
        self.commander_zone_choice_pending: bool = False

        # Permanent state (meaningful on the battlefield).
        self.tapped: bool = False
        #: RULE 502.1 standing toggle for a "you may choose not to untap ~
        #: during your untap step" permission (`"no_untap_optional"`
        #: `StaticAbility`, Rubinia Soulsinger/Hivis of the Scale/The
        #: Pandorica-shaped) — the engine has no mid-untap-step pause to ask
        #: fresh every turn, so the controller flips this any time
        #: (`GameEngine.set_skip_untap`) and it stays sticky until changed
        #: again. Inert unless the object actually carries that permission
        #: (`continuous.has_no_untap_static` checks both).
        self.skip_untap: bool = False
        #: RULE 702.19b's one-time consequence of being exerted (or any
        #: future one-shot "doesn't untap during its controller's next
        #: untap step" effect): unlike `skip_untap` above this isn't a
        #: sticky permission the controller re-decides every turn — it's
        #: consumed exactly once, by the very next `_step_untap` that sees
        #: it true, which also clears it back to False.
        self.skip_next_untap: bool = False
        #: RULE 702.19a: whether this permanent has already been exerted
        #: this turn — universal bookkeeping (harmless for any exert
        #: creature) that Combat Celebrant's own "if ~ hasn't been exerted
        #: this turn" guard reads via the `EXERTED` event's own
        #: ``already_exerted`` snapshot, taken before this flips. Reset at
        #: the normal untap step, same as `summoning_sick`.
        self.exerted_this_turn: bool = False
        #: Summoning sickness (RULE 302.6): a creature can't attack/tap
        #: until its controller has controlled it since their last turn
        #: began. Set when it enters, cleared at that controller's untap.
        self.summoning_sick: bool = True
        #: The turn number this permanent entered the battlefield (RULE
        #: 606.3-adjacent "as long as ~ entered the battlefield this turn"
        #: conditions, The Wandering Emperor-shaped) — stamped once by
        #: `GameState.add_to_battlefield`, read live by
        #: `game/condition_query.py`'s ``entered_this_turn`` check. ``None``
        #: for an object that has never been on the battlefield.
        self.turn_entered: Optional[int] = None
        #: RULE 702.26 (phasing): while ``True``, this permanent is treated
        #: as though it doesn't exist — untargetable, can't attack/block,
        #: ignored by static/continuous effects and SBAs. Still structurally
        #: in `Zone.BATTLEFIELD` (phasing out is not a zone change, RULE
        #: 702.26b), so every "live battlefield" reader must go through
        #: `GameState.permanents`/`permanents_controlled_by` (which filter
        #: this out) rather than the raw `battlefield` list — the one place
        #: that still needs the raw list is `GameEngine._step_untap`'s own
        #: RULE 702.26a phase-in sweep, which must see phased-out objects to
        #: flip them back. Set/cleared by `game/card_catalogue`'s
        #: phase-out effects and that same untap-step sweep.
        self.phased_out: bool = False
        #: Damage marked this turn (RULE 120); cleared during cleanup.
        self.damage_marked: int = 0
        #: Counters on the permanent, keyed by kind (RULE 122): e.g.
        #: ``{"+1/+1": 2, "-1/-1": 1}``, ``{"loyalty": 3}``, ``{"charge": 1}``.
        #: +1/+1 and -1/-1 are tracked as *distinct* kinds (they don't merge
        #: on the object — they annihilate as a state-based action, RULE
        #: 704.5q, applied by the rules engine) so a "remove a +1/+1 counter"
        #: or "counts +1/+1 counters" effect stays correct. Power/toughness
        #: read the net (`plus_one_counters`).
        self.counters: dict[str, int] = {}

        #: Combat state (RULE 508). ``attacking`` marks a creature declared
        #: as an attacker this combat; ``combat_defender`` is *what* it is
        #: attacking — a serializable dict ``{"kind": "player", "id": ...}``
        #: or ``{"kind": "planeswalker", "instance_id": ...}``, or None for a
        #: "bare" swing with no legal defender (solo goldfish). Kept on the
        #: object (not the engine) so it survives a `GameState.clone()` for
        #: rewind. Cleared when the combat phase ends (RULE 511.3).
        self.attacking: bool = False
        self.combat_defender: Optional[dict[str, Any]] = None
        #: PAR-28 / RULE 702.142a Boast: whether this creature was declared as
        #: an attacker at any point this turn. Unlike ``attacking`` (cleared
        #: the instant combat ends, RULE 511.3) this survives into the second
        #: main phase so a boast ability is still activatable then; reset each
        #: untap step, like ``activated_loyalty_this_turn``.
        self.attacked_this_turn: bool = False
        #: How many times this creature has been declared as an attacker this turn (an extra combat phase can make
        #: it more than one) — "…+1/+0 for each time it has attacked this turn" (Moraug, Fury of Akoum). Reset with
        #: ``attacked_this_turn`` in the untap step.
        self.times_attacked_this_turn: int = 0
        #: PAR-28 / RULE 719.3b: the "solved" designation a Case permanent can
        #: have. Once set it stays until the Case leaves the battlefield (not
        #: reset per turn, not a copiable value).
        self.is_solved: bool = False
        #: PAR-28 / RULE 719.3a: the "To solve — [Condition]" whitelisted
        #: condition dict (`game/static_conditions.py` vocabulary), checked at
        #: the beginning of the controller's end step. ``None`` for a
        #: non-Case permanent.
        self.solve_condition: Optional[dict[str, Any]] = None
        #: PAR-28 / RULE 702.177a Exhaust & Power-up: the descriptions of this
        #: permanent's "Activate only once" abilities already activated this
        #: game. Never reset (per-game, not per-turn).
        #: "Do this only once each turn." (PAR-135): the turn number an *action* of this object's ability —
        #: keyed by the ability's own text — was last performed. `game_status.ActionStampEffect` writes it
        #: when the action is taken; the `action_unused_this_turn` condition (and the trigger prompt) read it.
        self.action_turns: dict[str, int] = {}
        self.used_once_per_game_abilities: set[str] = set()
        #: The mana-ability sibling of the set above (`ActivationCost.
        #: once_per_game` — Loot, the Pathfinder's "Exhaust — {G}, {T}: Add
        #: three mana …"): the `mana_abilities_for` indices already activated.
        self.mana_abilities_used_this_game: set[int] = set()
        #: "…if this is the second time this ability has resolved this turn"
        #: (Omnath, Locus of Creation; Rumor Gatherer, PAR-120): per ability
        #: of *this object*, ``key → (turn_number, resolutions)``. Stamped with
        #: the turn instead of cleared at each turn start, so a stale entry
        #: simply reads as zero. Counts resolutions, not activations or
        #: triggers, whoever controlled them, copies included (the cards'
        #: rulings); a new object (RULE 400.7) starts from zero.
        self.ability_resolutions: dict[str, tuple[int, int]] = {}
        #: Whether a loyalty ability of this planeswalker has been activated
        #: this turn (RULE 606.3: only one per turn). Reset each untap step.
        self.activated_loyalty_this_turn: bool = False
        #: How many times this object's own `GraveyardCastPermissionEffect`
        #: grant (Lurrus of the Dream-Den-shaped, `game/graveyard_cast.py`)
        #: has been used this turn — gates its ``once_per_turn`` restriction.
        #: Reset each untap step, same as `activated_loyalty_this_turn`.
        self.graveyard_casts_this_turn: int = 0
        #: PAR-105: uses this turn of this permanent's own "once each turn, you may cast … from the top of
        #: your library" grant (`top_library.record_top_library_use`). Reset each untap step.
        self.top_library_uses_this_turn: int = 0
        #: RULE 605.1a mana ability, "… and only once each turn." (Vivi
        #: Ornitier) — the *indices* (`mana_abilities_for`'s own enumeration
        #: order, stable per object) of this permanent's mana abilities
        #: already activated this turn, gating `ActivationCost.once_per_
        #: turn`. A set rather than `activated_loyalty_this_turn`'s bare
        #: bool since RULE 606.3's cap is over the whole permanent's loyalty
        #: abilities together, while this one is per *individual* mana
        #: ability — a permanent with two, independently-restricted mana
        #: abilities (none observed in the cache yet) must track them
        #: separately. Reset each untap step, same as `activated_loyalty_
        #: this_turn`. See `GameEngine.tap_for_mana`.
        self.mana_abilities_activated_this_turn: set[int] = set()
        #: "Exile a creature you control: Add X mana of any one color,
        #: where X is 1 plus the exiled creature's mana value." (Food
        #: Chain, MEC-40) — the mana value of whichever creature most
        #: recently paid this permanent's own `ActivationCost.
        #: exile_creature` cost, stamped by `GameEngine._pay_activation_
        #: cost` right as it's exiled and read immediately afterward by
        #: `GameEngine.tap_for_mana` to size the mana actually produced —
        #: nothing overwrites or resets it, since it's only ever consulted
        #: in that same narrow window.
        self.last_cost_exiled_object_mv: Optional[int] = None
        #: RULE 702.171c: the turn number "Saddle N" (Guardian Sunmare,
        #: MEC-40) last resolved on this permanent — "becomes saddled
        #: until end of turn" needs no separate cleanup-step reset the way
        #: a `temp_*` field would: `is_saddled` below just checks this
        #: against the *current* turn number, so it naturally goes stale
        #: the instant the turn changes.
        self.saddled_until_turn: Optional[int] = None
        #: ENG-27: whether this object's own "if you haven't added mana
        #: with this ability this turn, you may add …" trigger (Carpet of
        #: Flowers) already has this turn. A per-*ability* gate, unlike
        #: `GameState.cards_drawn_this_turn`'s per-*player* one, since the
        #: printed condition names "this ability" specifically — a second
        #: mana source on the same controller's board is unaffected. Reset
        #: each untap step, same as `activated_loyalty_this_turn`.
        self.added_mana_with_ability_this_turn: bool = False
        #: MEC-29/RULE 702.122c: the instance ids of every creature tapped to
        #: pay one of this permanent's own Crew costs since its controller's
        #: last untap step — "crewed by ~ this turn" (Balthier and Fran).
        #: Accumulates across repeat Crew activations in the same turn rather
        #: than being overwritten (a fact that becomes true stays true for
        #: the rest of the turn, the same "this turn" convention every other
        #: field on this list uses); reset each untap step, same as
        #: `activated_loyalty_this_turn`. Stamped by `GameEngine.
        #: _pay_activation_cost`'s `crew_power` branch, read live by
        #: `effect_binder._build_group_ok`'s ``crewed_by_self`` condition.
        self.crewed_by_ids: list[int] = []
        #: Blocking (RULE 509): ``blocking`` is the instance id of the
        #: attacker this creature is declared to block (None if not
        #: blocking); ``blocked_by`` lists the blocker instance ids assigned
        #: to this attacker. Both are cleared when combat ends (RULE 511.3).
        self.blocking: Optional[int] = None
        #: RULE 509.1b multi-block permissions ("~ can block an additional
        #: creature each combat."/"~ can block any number of creatures.") —
        #: every attacker this creature is blocking *beyond* the first,
        #: which still lives on ``blocking`` above so an ordinary blocker
        #: (the overwhelming majority) is untouched. `game/combat.py`'s
        #: `blocking_attacker_ids` reads the two together;
        #: `GameEngine._split_blocker_damage` divides this creature's power
        #: among every attacker named across both. Cleared with the rest of
        #: combat state at end-of-combat, same as ``blocking``.
        self.additional_blocking: list[int] = []
        self.blocked_by: list[int] = []
        #: Set when this creature was dealt combat damage by a deathtouch
        #: source this combat (RULE 702.2b): any such creature is destroyed as
        #: a state-based action regardless of how little damage it took.
        #: Transient — cleared with the rest of combat state at end-of-combat.
        self.dealt_deathtouch_damage: bool = False

        #: The permanent this object is attached to (RULE 301.5 Equipment /
        #: RULE 303.4 Aura): the host's ``instance_id``, or None if not
        #: attached. Drives the "attached cards grouped around their host"
        #: display; set by the (future) equip/enchant resolution.
        self.attached_to: Optional[int] = None
        #: The host this object was just detached from, stamped by
        #: `GameEngine._pay_activation_cost`'s ``unattach_self`` cost
        #: component (Sunforger/Akiri, Fearless Voyager) the instant before
        #: it clears `attached_to` — the ability's own effect (resolving
        #: *after* the cost is already paid) has no other way to reach "that
        #: creature" the unattach cost named.
        self.last_unattached_from_id: Optional[int] = None

        #: RULE 108.4-adjacent "gain control of target permanent until end
        #: of turn" (Zealous Conscripts/Coercive Recruiter-shaped,
        #: `game/effects/core.py`'s `GainControlUntilEndOfTurnEffect`) — the
        #: *original* controller, stamped the moment control changes so
        #: `GameEngine._step_cleanup` can hand it back at the next cleanup;
        #: ``None`` means this object isn't under a temporary control change.
        self.control_change_until_eot: Optional[str] = None

        #: An O-Ring-shaped "exile target X; when this leaves the
        #: battlefield, return the exiled card" pair (Leonin Relic-Warder-
        #: shaped) — the exiled card's own ``instance_id``, stamped by
        #: `ExileEffect`'s ``remember=True`` mode and consumed by
        #: `ReturnLinkedExileEffect` on this object's own leaves-battlefield
        #: trigger. ``None`` when nothing is currently linked.
        self.linked_exile_id: Optional[int] = None
        #: "Exile target creature an opponent controls until an opponent becomes the monarch." (Palace Jailer) — the
        #: exiler's player id; `RulesEngine.become_monarch` returns the card when someone else takes the crown.
        self.exiled_until_opponent_monarch_of: Optional[str] = None
        #: Edgar, Master Machinist's "that artifact enters tapped" — set when cast through such a graveyard grant.
        self.enters_tapped_from_cast_grant: bool = False
        #: Strago and Relm: a creature cast through the dig's free-cast window gains haste and is sacrificed at the end step.
        self.granted_haste_sacrifice: bool = False
        #: Coin of Fate: the instance ids of the cards its cost exiled from the graveyard (read by the resolving effect).
        self.last_cost_exiled_ids: list[int] = []
        #: Every card one remembering exile took, when it took more than one
        #: ("for each opponent, exile up to one target … until ~ leaves the
        #: battlefield" — PAR-130). `linked_exile_id` keeps naming the last of
        #: them for its single-card readers; `ReturnLinkedExileEffect` returns
        #: the whole set.
        self.linked_exile_ids: list[int] = []
        #: RULE 702.55 Haunt: the creature this exiled card currently haunts.
        #: The link is cleared by any later zone change (`reset_as_new_object`).
        self.haunting_instance_id: Optional[int] = None
        #: A one-shot free-cast rider (Impulsivity): exile this spell rather
        #: than letting it reach a graveyard after it resolves.
        self.exile_after_free_cast: bool = False
        #: MEC-21's generalized sibling of `linked_exile_id` above — "cards
        #: exiled **with** ~" (Agatha's Soul Cauldron/Dark Impostor/Bruna,
        #: Light of Alabaster-shaped, ~185 cached cards per this ticket's
        #: sizing), which *accumulates* every card this object has ever
        #: exiled "with itself" rather than overwriting a single slot —
        #: `ExileEffect`'s ``track_exiled_with=True`` mode appends here
        #: instead of stamping `linked_exile_id`. A stale id (the exiled
        #: card since left exile) is left in place rather than pruned on
        #: removal — every consumer (`continuous._apply_borrowed_activated_
        #: abilities`) already re-resolves each id fresh and drops what it
        #: can't find, the same "dead reference is harmless" contract
        #: `linked_exile_id`'s own `imprinted_card_colors` reader uses.
        self.exiled_with_ids: list[int] = []
        #: PAR-80: the reveal-choice sibling of `exiled_with_ids` just
        #: above — "reveal any number of `<X>` cards in your hand" (Ivy
        #: Seer, Scent of Ivy) accumulates each pick's instance id here
        #: (`_apply_chosen_object`'s ``"reveal"`` action) rather than moving
        #: it anywhere; read back only for its length, by the
        #: ``"revealed_with_count"`` count_selector. Cleared at the start of
        #: each `RevealAnyNumberHandCardsEffect.apply` so a repeatable
        #: ability starts fresh per activation.
        self.revealed_with_ids: list[int] = []
        #: A generic single-slot "remember an object across a resolution
        #: gap" field — `context.trigger_event` is only live for the one
        #: resolution window a trigger's own effects run in (RULE 603.3), so
        #: an effect that opens an *interactive* pause first (`pay_cost_
        #: then`'s "you may pay") can't read the original firing event by
        #: the time its "if you do" branch actually runs. `PayCostThenEffect`'s
        #: ``remember_trigger_subject=True`` stamps the trigger's subject id
        #: here at the (still-live) first `apply()`; `AddCountersEffect`'s
        #: ``trigger_subject_key="remembered"`` reads it back on the deferred
        #: side (Emiel the Blessed's "you may pay `<cost>`. If you do, put a
        #: counter on **it**." referring to a creature that entered, not a
        #: real RULE 115 target). ``None`` when nothing is remembered.
        self.remembered_instance_id: Optional[int] = None
        #: The `StackItem.stack_id` sibling of `remembered_instance_id`
        #: above, for the same resolution-gap problem when what needs
        #: remembering is a stack item rather than a `GameObject` — an
        #: ability `StackItem` has no `instance_id` of its own to stash
        #: (`.obj` is `None`, RULE 707.10/ENG-26). `PayCostThenEffect`'s
        #: ``remember_trigger_stack_id=True`` stamps it here at the first,
        #: still-live `apply()`; `CopyAbilityEffect` reads it back once the
        #: "if you do" branch actually runs (Rings of Brighthearth's "you
        #: may pay `<cost>`. If you do, copy that ability.").
        self.remembered_stack_id: Optional[int] = None

        #: Effects this object contributes while in play, consulted by the
        #: rules engine (mtg_analyzer/game/). Typed loosely to avoid a
        #: model→game import; they hold `GameEffect` subclasses.
        self.triggered_abilities: list[Any] = []
        self.replacement_effects: list[Any] = []
        #: "You may have this enter the battlefield as a copy of target X"
        #: (RULE 614.1c/614.12, `EnterAsCopyReplacement`) — consulted by
        #: `RulesEngine._offer_enter_as_copy` *before* this object is added
        #: to the battlefield, unlike `replacement_effects`'s event-transform
        #: `ReplacementEffect`s.
        self.enter_as_copy_effects: list[Any] = []
        #: "As ~ enters, choose a creature type/color" (RULE 601.2b-style
        #: characteristic-defining choice made as part of entering, not a
        #: triggered ability) — `ChooseCreatureTypeReplacement`/
        #: `ChooseColorReplacement`, bound the same `enter_replacement` way as
        #: `enter_as_copy_effects` (a different family, so its own list; see
        #: `effect_binder.bind_ability`'s routing). Consulted by
        #: `RulesEngine._offer_enter_choices` right alongside
        #: `_offer_enter_as_copy`, before this object is added to the
        #: battlefield.
        self.enter_choice_effects: list[Any] = []
        #: RULE 614.12: "If ~ would enter, you may discard a land card
        #: instead. If you do, put ~ onto the battlefield. If you don't, put
        #: it into its owner's graveyard." (Mox Diamond) — consulted by
        #: `RulesEngine._offer_enter_or_graveyard` *before*
        #: `enter_as_copy_effects`/`enter_choice_effects` even get a look
        #: (if this is declined, the object never becomes a permanent at
        #: all, so nothing else about entering matters). A plain flag
        #: rather than a generic cost, since real-cache-wide this template
        #: is a singleton (confirmed via a raw-text grep) — not worth a
        #: general `ActivationCost`-shaped alternative-entry-cost primitive
        #: until a second card actually needs one.
        self.enter_or_graveyard_discard_land: bool = False
        #: The creature type/color chosen by this object's own "as ~ enters,
        #: choose a …" ability (`enter_choice_effects` above), e.g.
        #: ``"Goblin"`` / ``"R"``. Read by `game/continuous.py`'s
        #: ``subtype_from_source``/``color_from_source`` selector params
        #: (Adaptive Automaton/Arcane Adaptation-shaped lords) — ``None``
        #: until the choice is made, or if the card has no such ability.
        #: RULE 400.7: a new object hasn't made the choice yet either, so
        #: `reset_as_new_object` clears both.
        self.chosen_type: Optional[str] = None
        self.chosen_color: Optional[str] = None
        #: "As ~ enters, choose two colors." (Tablet of the Guilds) — every colour picked, in pick order;
        #: `chosen_color` stays the first one. Cleared with the other ETB picks (RULE 400.7).
        self.chosen_colors: list[str] = []
        #: The battle's **protector** (RULE 310.8) — the player id chosen as
        #: this battle enters (310.11a, for a Siege: an opponent of its
        #: controller). Genuinely distinct from `controller_id`: the
        #: protector is the "defending player" when the battle is attacked
        #: (310.8d) and the only player who may block for it (310.8c), while
        #: the *controller* is who its abilities belong to — which is
        #: exactly why a Siege can be attacked by its own controller
        #: (310.8b). ``None`` for a non-battle, or a battle whose subtype
        #: has no protector. RULE 400.7: a new object picks afresh, so
        #: `reset_as_new_object` clears it.
        self.protector_id: Optional[str] = None
        #: Whether this Siege's RULE 310.11b "when the last defense counter
        #: is removed" ability has already fired. A latch, not a state: the
        #: SBA pass is what notices defense reached 0 (so *every* route
        #: there is covered, not just damage), and it runs repeatedly until
        #: nothing changes — without this the same defeat would re-trigger
        #: on every pass while the first trigger still sat on the stack.
        self.battle_defeat_triggered: bool = False
        #: A named-mode choice from this object's own "as ~ enters, choose
        #: <Label1> or <Label2>" ability (Struggle for Project Purity's
        #: "choose Brotherhood or Enclave") — a lowercase slug of the chosen
        #: label (e.g. ``"brotherhood"``), read by `effect_binder._trigger_
        #: condition`'s ``"named_mode"`` gate so only that mode's own
        #: ability actually fires. ``None`` until chosen, same RULE 400.7
        #: reset-on-new-object treatment as `chosen_type`/`chosen_color`.
        self.chosen_mode: Optional[str] = None
        #: RULE 601.2b-adjacent "as ~ enters, choose a player" (Stuffy
        #: Doll) — the player-choice sibling of `chosen_type`/`chosen_
        #: color`/`chosen_mode`, same reset-on-new-object treatment.
        self.chosen_player_id: Optional[str] = None
        #: "As this creature enters, you may choose a nonland permanent."
        #: (MEC-26, Scheming Fence) — an *object*-choice sibling of
        #: `chosen_player_id`, but modeled as an ordinary interactive ETB
        #: trigger (`RulesEngine._request_choose_objects`'s new
        #: ``"choose_permanent"`` action) rather than a pre-entry RULE
        #: 601.2b replacement like `chosen_type`/`chosen_color`: unlike
        #: those, the pick never feeds back into *this object's own*
        #: printed characteristics, only into other statics
        #: (`continuous.group_selector_objects`'s ``"chosen_permanent"``
        #: selector) that already re-read live state every recompute
        #: regardless of when the choice landed. ``None`` until chosen (or
        #: declined — the clause is optional), same RULE 400.7
        #: reset-on-new-object treatment as the other ``chosen_*`` fields.
        self.chosen_permanent_id: Optional[int] = None
        #: "As ~ enters the battlefield, choose a card name." (MEC-12,
        #: Pithing Needle/Phyrexian Revoker-shaped) — a free-text RULE
        #: 601.2b sibling of `chosen_type`/`chosen_color`: unlike those, the
        #: answer space isn't enumerable from game state (any Magic card
        #: name is legal, not just one already on this board), so it's
        #: stamped verbatim rather than validated against an options list.
        #: Read by `continuous.group_selector_objects`'s
        #: ``card_name_from_source`` selector param. ``None`` until chosen,
        #: same RULE 400.7 reset-on-new-object treatment as the other
        #: ``chosen_*`` fields.
        self.chosen_card_name: Optional[str] = None
        #: "As this creature enters, choose a number." (Sanctum Prelate,
        #: MEC-43) — the free-text-numeric sibling of `chosen_card_name`,
        #: same "answer space isn't enumerable" shape, just an int instead
        #: of a card name. Read by `continuous.cast_prohibited`'s
        #: ``max_mana_value="chosen_number"`` sentinel. ``None`` until
        #: chosen, same RULE 400.7 reset-on-new-object treatment as the
        #: other ``chosen_*`` fields.
        self.chosen_number: Optional[int] = None
        #: RULE 603.1 Panharmonicon-shaped self-recursion marker: which
        #: permanent's own "put a card onto the battlefield" ability placed
        #: this object here (MEC-43 round 4D, Kodama of the East Tree's "if
        #: it wasn't put onto the battlefield with this ability" guard) —
        #: `RulesEngine._apply_chosen_object`'s ``"hand_to_battlefield"``
        #: action stamps the granting permanent's own `instance_id`;
        #: `effect_binder._build_group_ok`'s ``not_entered_via_self``
        #: condition reads it back to skip re-triggering off the ability's
        #: own puts. ``None`` for an ordinary cast/search/reanimate arrival,
        #: and (RULE 400.7) for a brand-new object regardless of how its
        #: predecessor got here.
        self.entered_via_ability_id: Optional[int] = None
        #: RULE 303.4f (MEC-34, Animate Dead-shaped): "Enchant creature card
        #: in a graveyard" — the graveyard card this Aura was targeting at
        #: cast time, stashed here because it isn't a permanent and so can't
        #: actually attach as the Aura resolves the ordinary way (`RulesEngine.
        #: _resolve_permanent_spell` leaves it unattached on the battlefield
        #: instead of sending it to the graveyard for the failed attach).
        #: The Aura's own "when this enters" ability reads this back
        #: (`ReturnFromGraveyardEffect`'s ``target_kind="self_enchant_
        #: target"``) to reanimate the right card and attach itself to the
        #: result. ``None`` for every ordinary Aura, and reset on a new
        #: object the same as every other cast-time-scoped field.
        self.reanimate_target_id: Optional[int] = None
        #: Static abilities (`StaticAbility`) this object grants through the
        #: layer system (RULE 613) — anthems, keyword grants, type changes,
        #: cost reductions. Read by `game/continuous.py`.
        self.static_effects: list[Any] = []
        self.activated_abilities: list[Any] = []
        #: Intrinsic keyword abilities bound off the card's own text (RULE 702),
        #: as catalogue slugs — the flag keywords the parser catalogue produced
        #: and the binder docked here (e.g. ``{"flying", "deathtouch"}``).
        #: Combat unions these with the card's recognized keywords; unlike
        #: `_granted_keywords` they are the object's *own* keywords, so they are
        #: not cleared by `reset_derived`.
        self.intrinsic_keywords: set[str] = set()
        #: Parametric keyword abilities the binder docked with their one
        #: parameter (RULE 702), keyed by slug: ``{"annihilator": {"n": 2},
        #: "kicker": {"cost": "{2}{R}"}, "landwalk": {"quality": "island"}}``.
        #: The carried parameter the cost/combat-math consumers read.
        self.parametric_keywords: dict[str, Any] = {}

        #: Derived characteristics stamped by the continuous-effects layer
        #: engine (`game/continuous.py`, RULE 613). ``None`` / empty until a
        #: recompute runs, in which case they supersede the printed values;
        #: they fold in counters too, so an on-battlefield permanent reads its
        #: whole layer stack here. `reset_derived` clears them before a pass.
        self._base_power: Optional[int] = None
        self._base_toughness: Optional[int] = None
        self._derived_power: Optional[int] = None
        self._derived_toughness: Optional[int] = None
        self._granted_keywords: set[str] = set()
        #: ENG-31: a *granted* parametric keyword's number, keyed by slug —
        #: "target creature gains firebending N until end of turn" (Fire
        #: Nation Palace), "~ has firebending N as long as <cond>" (Fire
        #: Nation Cadets). Re-derived every `continuous.recompute` pass from
        #: the layer-6 grant / `temp_parametric_keywords`, unlike
        #: `parametric_keywords` which is bound once from printed text.
        #: `parametric_keyword_value` reads the two together.
        self._granted_parametric_keywords: dict[str, int] = {}
        #: A *granted* Ward's cost text (RULE 702.21b — "Other creatures
        #: you control have 'Ward—Pay 2 life.'", Hexing Squelcher-shaped),
        #: re-derived every `continuous.recompute` pass by
        #: `_apply_grant_ward`. ``None`` when nothing grants this object
        #: Ward. Separate from `parametric_keywords` (bound once from the
        #: card's own printed text, never re-derived) since a grant is
        #: continuous, layer-6 state.
        self.granted_ward_cost: Optional[str] = None
        #: Flag keywords a layer-6 "loses <keyword>" static ability strips
        #: this pass (RULE 613.7f — Colossus Hammer's "Equipped creature …
        #: loses flying"), unioned out of `_obj_keywords` by
        #: `game/combat.py`. Reset every recompute exactly like
        #: `_granted_keywords`.
        self._removed_keywords: set[str] = set()
        #: RULE 702.16 protection qualities granted by a layer-6 *standing*
        #: static ability ("Cats you control have protection from Rats" —
        #: Hungry Lynx; "Enchanted creature has protection from the chosen
        #: color" — Flickering Ward). Already-normalized tokens in
        #: `game/combat.py`'s `protections_of_text` vocabulary (``"B"``,
        #: ``"creatures"``, ``"rats"``), unioned into `is_protected_from`'s
        #: printed set. Distinct from `temp_protections`, which is a
        #: *resolve-time* "until end of turn" grant (Mother of Runes) rather
        #: than a continuously re-derived one. Reset every recompute exactly
        #: like `_granted_keywords`.
        self._granted_protections: set[str] = set()
        #: RULE 702.16n/p: this object's *own* protection grant onto its
        #: attached host ("Enchanted creature has protection from black.
        #: **This effect doesn't remove this Aura.**", Black Ward &c) is
        #: exempted from RULE 704.5m/n's normal "illegal attachment falls
        #: off" check — without this, a black Aura granting its host
        #: protection from black would immediately detach itself the next
        #: SBA pass. Set on the *granting object itself* (not the host) by
        #: `continuous.py`'s layer-6 pass, read by `_attachment_legal`/
        #: `_revalidate_attachments`. Reset every recompute like
        #: `_granted_protections`.
        self._protection_self_exempt: bool = False
        #: RULE 508.1a/509.1b combat *restrictions* granted by a standing
        #: static ability that carry a parameter the synthetic flag keywords
        #: (`cant_attack`/`cant_block`/`cant_be_blocked`) can't: "can't be
        #: blocked by creatures with power 2 or less", "can't be blocked
        #: except by Walls", "can't attack unless defending player controls
        #: an Island", "can't attack alone". Each entry is a small clamped
        #: param dict in `game/combat.py`'s `COMBAT_RESTRICTIONS` vocabulary,
        #: evaluated at *combat time* (the defending player, and who else is
        #: attacking, aren't known at recompute time) by `GameEngine.
        #: _can_attack`/`can_block`. Not a characteristic, so it's a
        #: `continuous.py` non-RULE-613 bucket rather than a layer — but
        #: re-derived every recompute like `_granted_protections`, so it
        #: disappears on its own when its source leaves.
        self._combat_restrictions: list[dict[str, Any]] = []
        #: RULE 701.15b goad from a *standing static* rather than a one-shot
        #: effect ("Enchanted creature gets +2/+2 and is goaded", Acquired
        #: Mutation; "Creatures your opponents control with power less than
        #: ~'s power are goaded", Baeloth Barrityl). The goaders' ids, and
        #: like `_combat_restrictions` above re-derived every recompute — the
        #: designation has to vanish the moment the Aura does, which the
        #: sticky, resolve-time `goaded_by` set deliberately doesn't. Read
        #: together with it by `combat.goaders`.
        self._goaded_by_static: set[str] = set()
        #: RULE 205.4/613.2d: a layer-4 static ability making this permanent
        #: legendary even though its printed type line isn't ("Your
        #: Ring-bearer is legendary" — RULE 701.51's Ring emblem, the only
        #: source today). Read by `is_legendary`; reset every recompute like
        #: the other `_granted_*` fields, so it follows the Ring-bearer
        #: designation automatically instead of having to be un-stamped.
        self._granted_legendary: bool = False
        #: Whether a layer-6 "loses all abilities" static ability (RULE 613.7f
        #: — Humility, Dress Down) is stripping *every* ability off this object
        #: this pass: all keywords (`game/combat.py`'s `_obj_keywords` returns
        #: empty), and its triggered/activated abilities stop functioning
        #: (checked at fire/activate time). Reset every recompute like the
        #: `_granted_*`/`_removed_*` fields.
        self._loses_all_abilities: bool = False
        #: RULE 702.112b: whether Renown's own "it becomes renowned" has
        #: already happened — never reset by an ordinary recompute (a
        #: one-time-ever flag per object, unlike every ``_derived_*``/
        #: ``_granted_*`` field above), so the keyword's "if it isn't
        #: renowned" guard only fires once per object. `reset_as_new_object`
        #: *does* clear it — RULE 400.7's new object hasn't become renowned
        #: either.
        self.renowned: bool = False
        #: RULE 701.60a: whether this creature is **suspected** (Murders at
        #: Karlov Manor). A designation, like `is_monstrous`/`goaded_by`, not
        #: an ability — RULE 701.60b's "has menace and can't block" is read
        #: off this flag at combat time (`combat.is_suspected`), never via the
        #: layer engine. Survives an ordinary recompute; ends only when an
        #: effect says "no longer suspected" (`RemoveSuspectedEffect`) or the
        #: object leaves the battlefield — so `reset_as_new_object` clears it
        #: (RULE 400.7's new object isn't suspected).
        self.is_suspected: bool = False
        #: RULE 701.35b: the ids of players who have **detained** this
        #: permanent. A designation like `goaded_by` (a set, though in
        #: practice only ever one entry): while detained the permanent can't
        #: attack or block and its activated abilities can't be activated
        #: (`combat.is_detained`, checked in `_can_attack` / `can_block` /
        #: `can_activate`). Entries expire "until your next turn"
        #: (RULE 701.35b) — dropped as the detaining player's turn begins,
        #: the same `GameEngine.begin_turn` sweep `goaded_by` uses.
        self.detained_by: set[str] = set()
        #: RULE 701.37b: whether this permanent is **monstrous**. A
        #: designation with no rules meaning of its own — it exists so
        #: monstrosity's own "if this permanent isn't monstrous" guard can
        #: fire once (701.37a) and so "as long as ~ is monstrous" statics and
        #: "when ~ becomes monstrous" triggers have something to read. Like
        #: `renowned` above it survives an ordinary recompute and is cleared
        #: by `reset_as_new_object` — 701.37b's "stays monstrous until it
        #: leaves the battlefield" is exactly RULE 400.7's new object.
        self.is_monstrous: bool = False
        #: MEC-79 / RULE 701.64b: whether this permanent is **harnessed** (the
        #: Marvel Infinity Stones). A designation exactly like `is_monstrous`
        #: above — no rules meaning of its own, existing only so 701.64a's "if
        #: this permanent isn't harnessed" guard fires once and so the Stones'
        #: `∞` ability (`static_conditions`' ``source_harnessed``) has
        #: something to read. Survives an ordinary recompute; cleared by
        #: `reset_as_new_object` — 701.64b's "stays harnessed until it leaves
        #: the battlefield" is RULE 400.7's new object.
        self.harnessed: bool = False
        #: MEC-47: a Licid (Tempest — Gliding/Enraging/Corrupting/…) has used
        #: its "{cost}, {T}: this creature loses this ability and becomes an
        #: Aura enchantment … attach it to target creature. You may pay
        #: {cost} to end this effect." ability and is currently an Aura
        #: attached to `attached_to`. Drives: (1) a `for_as_long_as`
        #: floating `type_change` static that strips Creature / adds
        #: Enchantment—Aura while this holds (self-sweeps the instant this
        #: goes ``False``); (2) `static_conditions` `is_licid_aura` /
        #: `not_licid_aura`, which gate the two activated abilities so the
        #: transform is offered only as a creature and the "pay to end" only
        #: as an Aura. Cleared by `LicidRevertEffect` and by
        #: `reset_as_new_object` (RULE 400.7 — a Licid that leaves and
        #: returns is a fresh creature).
        self.is_licid_aura: bool = False
        #: MEC-48: this permanent has resolved its "Specialize {cost}"
        #: activated ability (an Arena-only digital keyword — see
        #: `EventType.SPECIALIZED`). A designation like `is_monstrous`,
        #: readable by a "when ~ specializes" trigger / "as long as ~ is
        #: specialized" static; `specialized_color` is a colour of the
        #: discarded card when one was determinable, else ``None``. The
        #: five specialized faces aren't in this repo's card seed, so no
        #: characteristic swap happens — this flag + the event are the whole
        #: model. Cleared by `reset_as_new_object` (RULE 400.7).
        self.is_specialized: bool = False
        self.specialized_color: Optional[str] = None
        #: RULE 701.37c: the value of X as this permanent became monstrous,
        #: so another of its abilities that refers to that X (Death Kiss's
        #: "when ~ becomes monstrous, goad up to X target creatures") reads
        #: the value that was announced, not a fresh one. 0 for a
        #: "monstrosity N" with a literal N.
        self.monstrosity_x: int = 0
        #: RULE 701.15b: the ids of the players who have **goaded** this
        #: creature. A designation, not an ability, and per 701.15c one
        #: creature can carry several at once (each adding its own combat
        #: requirement), which is why this is a set of goaders rather than a
        #: flag. Entries expire at the start of that goader's next turn
        #: (701.15a, `GameEngine.begin_turn`); the *static* half ("enchanted
        #: creature … is goaded") is re-derived every recompute into
        #: `_goaded_by_static` instead, since it must vanish with its source.
        self.goaded_by: set[str] = set()
        #: Territorial Hellkite: the player this creature "attacks … this combat if able"
        #: (`ForceAttackUnattackedOpponentEffect`), a requirement like goad's but naming the defender.
        #: Set at the beginning of combat, dropped as that combat ends (RULE 511.3).
        self.must_attack_player_id: Optional[str] = None
        #: The players this creature attacked in its controller's most recent combat (empty if it did not
        #: attack in it) — what "an opponent that ~ didn't attack during your last combat" reads. Recorded
        #: as each of that player's combats ends (`CombatMixin._record_last_combat`).
        self.last_combat_attacked_ids: set[str] = set()
        #: The same designation with **no** expiry — "The tokens are goaded
        #: for the rest of the game." (Rendmaw, Jon Irenicus). RULE 701.15a's
        #: "until your next turn" is the printed default that `goaded_by`
        #: models, and the only thing these cards change is the duration, so
        #: they get a second set rather than a per-entry expiry stamp: the
        #: turn-begin sweep simply never touches this one. `combat.goaders`
        #: reads all three sets as one.
        self.goaded_permanently: set[str] = set()
        #: Mana-production options granted by a layer-6 "X have '{T}: Add
        #: …'" static ability (Tyvar Kell) — folded onto the printed ones by
        #: `mana_abilities.mana_options_for`. Reset each recompute.
        self._granted_mana: list[dict[str, int]] = []
        #: Full layer-6 mana grants whose restriction or colour-split mode
        #: cannot be represented by the legacy options-only list above.
        self._granted_mana_abilities: list[dict[str, Any]] = []
        self._borrowed_mana_abilities: list[Any] = []
        #: MEC-25 sibling of `_granted_mana` above for a granted mana
        #: ability whose cost isn't a bare ``{T}`` — see
        #: `granted_mana_ability_upgrades`. Reset each recompute.
        self._granted_mana_upgrades: list[dict[str, Any]] = []
        #: Triggered abilities granted by a layer-6 "X have '<ability>'"
        #: static ability (Dionus, Elvish Archdruid). Rebuilt each recompute
        #: from a stable per-relationship cache (`GameState._granted_ability_
        #: cache`) so an instance — and any "once per turn" state on it —
        #: survives across passes for as long as the grant holds, and simply
        #: stops appearing here the moment it doesn't (RULE 613.6: no
        #: separate removal code needed, same as `_granted_keywords`).
        self._granted_triggered_abilities: list[Any] = []
        #: Layer-6-granted activated abilities (RULE 613.7f) — the
        #: `ActivatedAbility` sibling of `_granted_triggered_abilities`
        #: above, same per-relationship cache/rebuild shape (Umbral Mantle/
        #: Squirrel Nest-shaped "<host> has '{cost}: <effect>.'").
        self._granted_activated_abilities: list[Any] = []
        #: MEC-55: layer-6-granted *static* abilities (RULE 613.7f) — a
        #: nested anthem/lord/keyword-grant, re-derived per affected object
        #: each `continuous.recompute`, that `_battlefield_static_abilities`
        #: then yields as an ordinary static source ("X have '<static>'" —
        #: Inspiring Leader). Same "re-derived every pass, gone the moment
        #: the grant stops" shape as `_granted_triggered_abilities`.
        self._granted_static_abilities: list[Any] = []
        #: MEC-57: layer-6-granted *replacement* effects (RULE 613.7f/616) —
        #: `_granted_static_abilities`' sibling for a nested grant whose
        #: ``static_specs`` type resolves to a `ReplacementEffect` rather
        #: than a `StaticAbility` (Scion of Halaster's granted "first draw
        #: each turn" rewrite). Re-derived per affected object each
        #: `continuous.recompute`, read by `RulesEngine._all_replacement_
        #: effects` alongside a permanent's own printed ones.
        self._granted_replacement_effects: list[Any] = []
        #: A layer-6 self-only zone-change replacement.  Any quoted or
        #: unquoted ability may grant it to an ordinary affected-object group;
        #: the zone mover never needs a card-name or subtype branch.
        self._graveyard_to_library_replacement: bool = False
        self._added_types: set[str] = set()
        #: Creature *subtypes* a layer-4 "~ is the chosen type in addition to
        #: its other types"/"… of the chosen type …" static ability adds
        #: (RULE 613.4a) — distinct from `_added_types` (card-type words like
        #: "creature") and from `_derived_subtypes` (a full RULE 613.5
        #: overwrite): this only *adds* a subtype alongside the printed ones,
        #: so `continuous._has_subtype` checks it in addition to the printed
        #: type line. Reset each recompute.
        self._added_subtypes: set[str] = set()
        #: Types a layer-4 effect strips off (RULE 613.4a) — currently just
        #: Reconfigure (RULE 702.151b): the permanent stops being a creature
        #: for as long as it's attached to another creature.
        self._removed_types: set[str] = set()
        #: A layer-4 "type overwrite" static's replacement subtype set (RULE
        #: 613.5 — "the object loses all other types/subtypes", e.g. Blood
        #: Moon's "Nonbasic lands are Mountains"), or ``None`` when no such
        #: override applies, in which case `continuous._has_subtype` falls
        #: back to the printed type line's own subtypes as before. Distinct
        #: from `_added_types` (which only *adds*, the ordinary "are also
        #: creatures" shape) — a full overwrite must also stop matching the
        #: permanent's original subtypes (a Blood-Moon'd Underground Sea is
        #: no longer an Island or a Swamp).
        self._derived_subtypes: Optional[set[str]] = None
        #: Colours set/added by a layer-5 static ability (RULE 613.4b). ``None``
        #: means no colour-changing effect applies, so `colors` falls back to
        #: the printed card's ``color_identity``.
        self._derived_colors: Optional[set[str]] = None
        #: Oracle text rewritten by a layer-3 "text_change" static ability
        #: (RULE 612), or ``None`` if none applies. Consulted today only by
        #: `combat.protections_of_text` via `effective_oracle_text` below —
        #: bound abilities are still derived from the *printed* text once at
        #: bind time, unaffected (a live full re-parse is out of scope).
        self._derived_oracle_text: Optional[str] = None
        #: Timestamp for within-a-layer ordering (RULE 613.7b), stamped when the
        #: object enters the battlefield. Later timestamp = applied later.
        self.timestamp: int = 0
        #: The controller a layer-2 control-changing effect (RULE 613.2) took
        #: this object from — restored at the start of each recompute so the
        #: layer re-applies idempotently. ``None`` when no control effect is on
        #: it. Persists across a recompute (not cleared by `reset_derived`).
        self._control_base: Optional[str] = None
        #: Per-object record of which static abilities changed it and how, in
        #: layer order — the data the UI's layer-trace view renders.
        self.static_trace: list[dict[str, Any]] = []

        #: "Until end of turn" modifications from a resolved one-shot effect —
        #: a pump ("target creature gets +3/+3 until end of turn", RULE 613.4d)
        #: and a temporary keyword grant ("gains flying until end of turn",
        #: layer 6). Unlike counters (RULE 122) these are *effects*: they don't
        #: survive the object leaving and re-entering (`reset_as_new_object`),
        #: and the cleanup step (RULE 514.2) clears them each turn.
        #: `continuous.recompute` folds them into derived P/T and
        #: `_granted_keywords`, so they are *not*
        #: cleared by `reset_derived` (they must outlive a mid-turn recompute).
        self.temp_power: int = 0
        self.temp_toughness: int = 0
        self.temp_keywords: set[str] = set()
        #: MEC-105: flag keywords removed by a resolving "loses <keyword>
        #: until end of turn" effect.  This is the ability-removing mirror
        #: of ``temp_keywords``: it survives continuous-effect recomputes,
        #: is subtracted by ``combat._obj_keywords`` after every keyword
        #: source is combined, and expires at RULE 514.2 cleanup.
        self.temp_removed_keywords: set[str] = set()
        #: ENG-31: "until end of turn" grants of a *parametric* keyword
        #: ("target creature gains firebending N until end of turn" — Fire
        #: Nation Palace), slug → number. The parametric sibling of
        #: `temp_keywords`; `continuous.recompute` folds it into
        #: `_granted_parametric_keywords` and synthesizes the keyword's
        #: triggered ability. Cleared at cleanup (RULE 514.2) alongside
        #: `temp_keywords`.
        self.temp_parametric_keywords: dict[str, int] = {}
        #: Per-source breakdown of the "until end of turn" buffs above, for the
        #: board's per-card effect summary (source attribution the aggregate
        #: ints can't carry) — a list of
        #: ``{"source": name, "power": int, "toughness": int, "keywords": [..]}``
        #: entries, one per resolved pump/keyword-grant effect (Giant Growth,
        #: Monstrous Rage). Display-only: the aggregate ints above stay the
        #: source of truth for the layer-7 math. Cleared at cleanup (RULE 514.2)
        #: alongside `temp_power`; survives a mid-turn recompute like them.
        self.temp_effects: list[dict[str, Any]] = []
        #: "Target creature can't be blocked this turn" (Rogue's Passage) —
        #: a resolve-time grant read directly by `GameEngine.can_block`
        #: (not a layer-6 keyword; RULE 509.1a's blocking legality isn't
        #: part of the continuous-characteristics system). Cleared at
        #: cleanup (RULE 514.2) alongside `temp_power`/`temp_keywords`.
        self.temp_unblockable: bool = False
        #: RULE 701.28/613.7e's "switch `<X>`'s power and toughness until
        #: end of turn" from a *resolving* effect (Twisted Image-shaped),
        #: as opposed to a granted/printed static "pt_switch" ability — an
        #: odd/even counter, not a bool: RULE 613 applies each of a
        #: permanent's continuous effects in timestamp order, so two
        #: independent switches on the same object in the same turn must
        #: cancel back out, and only the parity survives that (a third
        #: switch behaves like a first). `continuous.recompute`'s own
        #: layer 7e pass reverses P/T once more for every odd count here,
        #: on top of whatever any static `pt_switch` ability already did.
        #: Cleared at cleanup (RULE 514.2) alongside `temp_power`.
        self.temp_pt_switch_count: int = 0
        #: "Target creature can't block this turn" (Falter/Goblin War Drums'
        #: whole family) — the mirror image of `temp_unblockable` above:
        #: a resolve-time RULE 509.1a restriction on the *blocker* rather
        #: than an evasion grant on the attacker, read directly by
        #: `GameEngine.can_block` and cleared at cleanup (RULE 514.2).
        self.temp_cant_block: bool = False
        #: RULE 701.16 / "can't be regenerated this turn" (Gravebind, Incinerate's rider) —
        #: `RulesEngine.destroy` skips the regeneration replacement pass; cleared at cleanup.
        self.temp_cant_be_regenerated: bool = False
        #: "You can't sacrifice those creatures this turn." (Call for Aid —
        #: an anti-abuse rider on a mass threaten). Checked by
        #: `RulesEngine.sacrifice` / `GameEngine._sacrifice_candidate`;
        #: cleared at cleanup (RULE 514.2) alongside `temp_keywords`.
        self.cant_be_sacrificed_this_turn: bool = False
        #: "~ can't be blocked by creatures with power 2 or less **this
        #: turn**" (Cavern Stomper/Tower of Coireall) — the resolve-time
        #: sibling of `_combat_restrictions`, in the same
        #: `game/combat.py` `COMBAT_RESTRICTIONS` param vocabulary but
        #: granted by a resolving effect rather than re-derived from a
        #: standing static, so it's cleared at cleanup (RULE 514.2) instead.
        #: `combat.combat_restrictions` reads the two together.
        self.temp_combat_restrictions: list[dict[str, Any]] = []
        #: "Gains protection from <quality> until end of turn" (Mother/Giver of
        #: Runes) — a set of protection qualities (a WUBRG colour letter, or
        #: ``"colorless"``) read by `combat.is_protected_from`. Cleared at
        #: cleanup (RULE 514.2) alongside `temp_keywords`/`temp_power`. Not a
        #: printed-text protection, so it's kept off the card and unioned in at
        #: check time instead.
        self.temp_protections: set[str] = set()
        #: "Creatures you control can't be the targets of blue or black
        #: spells this turn." (Autumn's Veil, MEC-41) — RULE 115's own
        #: targeting restriction, narrower than `temp_protections`'
        #: full RULE 702.16 protection (which also blocks damage/blocking/
        #: enchanting) and than hexproof (which also blocks *abilities*):
        #: only a spell whose own color is in this set is refused as a
        #: target, checked by `targeting._targetable_by`. Cleared at
        #: cleanup (RULE 514.2) alongside `temp_protections`.
        self.temp_cant_be_target_of_spell_colors: set[str] = set()
        #: "~ gains all activated abilities of target creature until end of
        #: turn." (MEC-23, Quicksilver Elemental) — a resolve-time snapshot
        #: of the target's `activated_abilities` at the moment of
        #: resolution (each redirected onto this object via
        #: `continuous._retarget_effect_source`, RULE 113.7c), *not* a live
        #: re-derivation the way `_granted_activated_abilities` (layer-6,
        #: rebuilt every `continuous.recompute` pass) is — later changes to
        #: the target's own ability set don't retroactively change what was
        #: copied, matching Quicksilver Elemental's own ruling. Read
        #: together with both of those by the `granted_activated_abilities`
        #: property below. Cleared at cleanup (RULE 514.2) alongside
        #: `temp_keywords`/`temp_power`.
        self.temp_granted_activated_abilities: list[Any] = []

        #: MEC-98: Alchemy "perpetually gets +N/+N / gains <keyword>" — a
        #: digital-only duration (not in the paper CR; MTG Arena's Alchemy
        #: rules) that, unlike every ``temp_*`` field above, is *never*
        #: forgotten: not at cleanup (RULE 514.2), not on a zone change
        #: (`reset_as_new_object` deliberately leaves these alone, the one
        #: exception to RULE 400.7's "effects are not retained"), and not by
        #: `reset_derived`. It reaches cards in hand/library/graveyard too, so
        #: the off-battlefield `power`/`toughness` fallback folds it in as
        #: well as `continuous.recompute`'s layer 7d/layer 6 passes. Carried
        #: onto a copy of the card (`copy_perpetual_from`).
        #: ``perpetual_effects`` is the display-only per-source breakdown,
        #: `temp_effects`' shape.
        self.perpetual_power: int = 0
        self.perpetual_toughness: int = 0
        self.perpetual_keywords: set[str] = set()
        self.perpetual_effects: list[dict[str, Any]] = []

        #: "Another target creature" a layer-1 conditional-copy static
        #: ability (Vesuvan Shapeshifter) should copy — read fresh every
        #: `continuous.recompute` pass, the same idiom `attached_to` uses.
        #: Set by `RulesEngine.set_copy_target`.
        self.copy_target_id: Optional[int] = None
        #: Stashed pre-copy face+ability bundle (`copy_mechanics.
        #: snapshot_face`'s shape) — set the first time a layer-1 copy
        #: ability transitions into applying, so the condition going false
        #: can restore it. `None` whenever no layer-1 copy is currently
        #: applied. Persists across a recompute (not cleared by
        #: `reset_derived`).
        self._copy_base: Optional[dict[str, Any]] = None
        #: Which `copy_target_id` is *currently* applied (distinct from the
        #: condition itself) — lets `continuous.recompute` tell "already
        #: copying this exact target, no-op" from "target changed, re-copy"
        #: without re-running the mutate/rebind (and destroying granted-
        #: ability bookkeeping) on every single pass. `None` whenever
        #: nothing is currently applied.
        self._copy_applied_target_id: Optional[int] = None
        #: Stashed pre-copy snapshot for a "becomes a copy … until end of
        #: turn" effect (Cursed Mirror-style, `RulesEngine.
        #: become_copy_until_end_of_turn`) — taken only the first time this
        #: turn, restored by `GameEngine._step_cleanup` (RULE 514.2).
        self._copy_until_eot_base: Optional[dict[str, Any]] = None

    def reset_derived(self) -> None:
        """Clear layer-engine output before a fresh `continuous.recompute`."""
        self._base_power = None
        self._base_toughness = None
        self._derived_power = None
        self._derived_toughness = None
        self._granted_keywords = set()
        self._granted_parametric_keywords = {}
        self.granted_ward_cost = None
        self._removed_keywords = set()
        self._granted_protections = set()
        self._protection_self_exempt = False
        self._combat_restrictions = []
        self._goaded_by_static = set()
        self._granted_legendary = False
        self._loses_all_abilities = False
        self._granted_mana = []
        self._granted_mana_abilities = []
        self._borrowed_mana_abilities = []
        self._granted_mana_upgrades = []
        self._granted_triggered_abilities = []
        self._granted_activated_abilities = []
        self._granted_static_abilities = []
        self._granted_replacement_effects = []
        self._graveyard_to_library_replacement = False
        self._added_types = set()
        self._added_subtypes = set()
        self._removed_types = set()
        self._derived_subtypes = None
        self._derived_colors = None
        self._derived_oracle_text = None
        self.static_trace = []

    def reset_as_new_object(self) -> None:
        """Wipe every field RULE 400.7 says a "new object" remembers nothing
        of — called by `RulesEngine.blink`/`return_from_graveyard` right
        before an object re-enters the battlefield from exile/graveyard (a
        library→battlefield arrival, e.g. a tutor or cascade hit, never
        needs this: a fresh `GameObject` already starts with every field
        below at its zero value).

        RULE 400.7: "An object that moves from one zone to another becomes a
        new object, even if it returns to a zone it was in before... Counters
        that were on it are not retained... effects that changed its
        characteristics or its controller are not retained... 'until end of
        turn' or 'for as long as' effects that applied to it are not
        retained." Concretely: counters, attachment linkage, control-change/
        copy state, cast-time flags (kicked/buyback/flashback/adventure/
        prepared), the one-time renown flag, every "until end of turn" pump/
        keyword/protection/unblockable grant, and all combat/summoning-
        sickness state.

        Deliberately does **not** touch `instance_id`: it is this engine's
        bookkeeping handle, not literally RULE 400.7's abstract "object"
        concept, and every self-referential trigger closure
        (`effect_binder._subject_condition`'s ``"self"`` scoping) captures it
        as a fixed snapshot at bind time — changing it here would silently
        break "whenever ~ attacks" on the very card this method runs for,
        without a full re-bind. RULE 400.7's *observable* consequences (ETB
        triggers refiring, summoning sickness resetting, every buff/counter/
        attachment gone) are all achieved by the field resets below plus the
        caller's fresh `ENTERS_BATTLEFIELD` event and `GameState.
        add_to_battlefield`'s new timestamp — instance-id churn adds risk
        without adding correctness. Likewise leaves `triggered_abilities`/
        `activated_abilities`/`static_effects`/`intrinsic_keywords`/
        `parametric_keywords` alone: they're bound once from the card's own
        printed text and would come back byte-identical from a re-bind, so
        there's nothing to "forget" there — same reasoning `reset_derived`'s
        `_granted_*`/`_derived_*` fields already get via the next
        `continuous.recompute` pass rather than an explicit clear here.
        """
        # MEC-98: `perpetual_*` is deliberately *not* reset here — a
        # perpetual change survives every zone change.
        # RULE 708.9: a face-down permanent is revealed as it changes zones,
        # so a new object is never still face down (and never keeps the old
        # object's stashed face-up bundle).
        self.turn_face_up()
        if self.transformed:
            self.card = self._front_card  # RULE 711.8: a new object presents its front face
        self._front_card = self.card
        self.transformed = False
        self.adventure_snapshot = None
        self.adventure_castable = False
        self.prepared = False
        self.prepared_source_id = None
        self.conjured_into_hand = False
        self.ability_resolutions = {}
        self.kicker_count = 0
        self.x_paid = 0
        self.kicker_x_paid = 0
        self.buyback_paid = False
        self.additional_cost_paid = False
        self.teamwork_paid = False
        self.mana_spent_to_cast = 0
        self.colors_spent_to_cast = frozenset()
        self.mana_by_color_spent_to_cast = {}
        self.mana_spent_to_cast_snow = 0
        self.mana_spent_to_cast_treasure = 0
        self.mana_spent_to_cast_creature = 0
        self.mana_spent_to_activate_treasure = 0
        self.was_cast = False
        self.cast_outside_sorcery_speed = False
        self.cast_during_your_main_phase = False
        self.sacrificed_cost_mana_value = None
        self.sacrificed_cost_card_types = []
        self.discarded_cost_card_types = []
        self.sacrificed_cost_was_suspected = False
        self.sacrificed_cost_power = None
        self.station_tapped_power = None
        self.paired_with = None
        self.merged_oracle_text = []
        self.cast_via_mutate = False
        self.mutate_under = False
        self.bargained = False
        self.gift_promised = False
        self.gift_recipient_id = None
        self.madness_cost_paid = False
        self.surge_cost_paid = False
        self.face_down_in_exile = False
        self.face_down_exile_viewers = set()
        self.hideaway_source_id = None
        self.hideaway_exile_ids = set()
        self.hideaway_incarnation += 1
        self.cast_via_flashback = False
        self.blitz_cost_paid = False
        self.cast_via_evoke = False
        self.cast_via_dash = False
        self.convoked_by_ids = []
        self.cast_from_zone = None
        self.granted_suspend_haste = False
        self.rebound_pending = False
        self.commander_zone_choice_pending = False
        self.tapped = False
        self.skip_untap = False
        self.skip_next_untap = False
        self.exerted_this_turn = False
        self.summoning_sick = True
        self.turn_entered = None
        self.phased_out = False
        self.damage_marked = 0
        self.counters = {}
        self.attacking = False
        self.combat_defender = None
        self.activated_loyalty_this_turn = False
        self.graveyard_casts_this_turn = 0
        self.top_library_uses_this_turn = 0
        self.mana_abilities_activated_this_turn = set()
        # RULE 400.7 / 702.177a: a new object's Exhaust abilities are fresh.
        self.used_once_per_game_abilities = set()
        self.action_turns = {}
        self.mana_abilities_used_this_game = set()
        self.added_mana_with_ability_this_turn = False
        self.blocking = None
        self.additional_blocking = []
        self.blocked_by = []
        self.dealt_deathtouch_damage = False
        self.attached_to = None
        self.last_unattached_from_id = None
        self.control_change_until_eot = None
        self.linked_exile_id = None
        self.exiled_until_opponent_monarch_of = None
        self.enters_tapped_from_cast_grant = False
        self.granted_haste_sacrifice = False
        self.last_cost_exiled_ids = []
        self.linked_exile_ids = []
        self.haunting_instance_id = None
        self.exile_after_free_cast = False
        self.exiled_with_ids = []
        self.revealed_with_ids = []
        self.remembered_instance_id = None
        self.remembered_stack_id = None
        #: RULE 702.112b: a new object hasn't become renowned yet either —
        #: the "never reset" rule on this flag only ever meant "not reset by
        #: an ordinary recompute", not "not reset ever" (no code implemented
        #: a genuine RULE 400.7 transition until this method existed).
        self.renowned = False
        #: RULE 701.37b/400.7: monstrous "stays until it leaves the
        #: battlefield" — leaving *is* this transition, so the new object is
        #: no longer monstrous and its monstrosity X is forgotten with it.
        self.is_monstrous = False
        self.monstrosity_x = 0
        #: MEC-79 / RULE 701.64b/400.7: harnessed "stays until it leaves the
        #: battlefield" — leaving *is* this transition, so the new object is no
        #: longer harnessed.
        self.harnessed = False
        #: MEC-47/400.7: a Licid that left the battlefield comes back a plain
        #: creature — the "became an Aura" effect ended with the object.
        self.is_licid_aura = False
        #: MEC-48/400.7: a specialized permanent that left is a new object;
        #: whether it re-enters as its base or specialized version is Arena
        #: card data this repo doesn't model, so it simply re-enters base.
        self.is_specialized = False
        self.specialized_color = None
        #: RULE 701.60a/400.7: suspected ends when the creature leaves the
        #: battlefield — leaving *is* this transition, so the new object is
        #: no longer suspected.
        self.is_suspected = False
        #: RULE 701.35b/400.7: detain likewise doesn't survive the zone
        #: change — what comes back is a new object, not detained.
        self.detained_by = set()
        #: RULE 701.15b: goaded is not part of a permanent's copiable values
        #: and doesn't survive the zone change either — including the
        #: "rest of the game" variant, whose duration outlasts a turn but
        #: still not the *object* (400.7: what comes back is a new one).
        self.goaded_by = set()
        self.goaded_permanently = set()
        self.must_attack_player_id = None
        self.last_combat_attacked_ids = set()
        #: RULE 601.2b/400.7: a new object hasn't made its "as it enters,
        #: choose a creature type/color" pick yet either.
        self.chosen_type = None
        self.chosen_color = None
        self.chosen_colors = []
        self.protector_id = None
        self.battle_defeat_triggered = False
        self.chosen_mode = None
        self.chosen_player_id = None
        self.chosen_permanent_id = None
        self.chosen_card_name = None
        self.chosen_number = None
        self.entered_via_ability_id = None
        self.reanimate_target_id = None
        self.temp_power = 0
        self.temp_toughness = 0
        self.temp_keywords = set()
        self.temp_removed_keywords = set()
        self.temp_parametric_keywords = {}
        self.temp_effects = []
        self.temp_unblockable = False
        self.temp_pt_switch_count = 0
        self.temp_cant_block = False
        self.temp_cant_be_regenerated = False
        self.temp_combat_restrictions = []
        self.temp_protections = set()
        self.temp_cant_be_target_of_spell_colors = set()
        self.temp_granted_activated_abilities = []
        self.copy_target_id = None
        self._copy_base = None
        self._copy_applied_target_id = None
        self._copy_until_eot_base = None
        self._control_base = None
        self.static_trace = []

    @property
    def colors(self) -> set[str]:
        """Effective colours (RULE 105 / layer 5), or the printed identity.

        Prefers colours a layer-5 static ability stamped (`_derived_colors`);
        otherwise the printed card's ``color_identity`` — the model's colour
        proxy the combat/anthem code already reads."""
        if self._derived_colors is not None:
            return set(self._derived_colors)
        return set(self.card.color_identity or set())

    @property
    def effective_oracle_text(self) -> str:
        """Effective oracle text (RULE 612 / layer 3), or the printed text.

        Prefers text a layer-3 "text_change" static ability rewrote
        (`_derived_oracle_text`); otherwise the printed card's own
        ``oracle_text``."""
        if self._derived_oracle_text is not None:
            return self._derived_oracle_text
        return self.card.oracle_text or ""

    # -- Delegated characteristics (read from the printed card) ---------

    @property
    def name(self) -> str:
        return self.card.name

    @property
    def is_creature(self) -> bool:
        # RULE 702.103b/d: a spell cast bestowed, or the permanent it
        # becomes while attached, is an Aura enchantment — not a creature —
        # until it ceases to be bestowed (702.103e/f).
        if self.bestowed:
            return False
        # Printed creature (unless a layer-4 effect strips it, RULE 702.151b),
        # or made one by a layer-4 type-changing effect.
        if self.card.is_creature:
            return "creature" not in self._removed_types
        return "creature" in self._added_types

    @property
    def is_land(self) -> bool:
        # Printed land, or made one by a layer-4 type-changing effect (e.g.
        # Ashaya, Soul of the Wild's "nontoken creatures you control are
        # Forest lands in addition to their other types") — mirrors
        # `is_creature`'s own printed-or-added/removed pattern, which this
        # property had never picked up.
        if self.card.is_land:
            return "land" not in self._removed_types
        return "land" in self._added_types

    @property
    def is_legendary(self) -> bool:
        """RULE 205.4: printed legendary, or made so by a layer-4 static.

        The only source of the latter today is RULE 701.51's Ring emblem
        ("Your Ring-bearer is legendary…"), stamped by `game/continuous.py`'s
        layer pass — which is why it reads a derived flag rather than the
        card alone. It matters to exactly one rule the engine models, the
        RULE 704.5j legend-rule SBA.
        """
        return self.card.is_legendary or self._granted_legendary

    @property
    def is_planeswalker(self) -> bool:
        return self.card.is_planeswalker

    @property
    def is_battle(self) -> bool:
        """Whether this is a battle (RULE 310) — the attackable, non-creature
        permanent type whose "toughness" is its defense-counter count."""
        return self.card.is_battle

    @property
    def type_words(self) -> set[str]:
        """Lowercase current card-type words (RULE 613 layer 4 aware).

        Used by `game/binding/core.py`'s trigger-condition "group" subject
        scoping (RULE 603.1, e.g. "whenever a creature dies") to check *what
        kind* of object an event was about. Starts from the printed type
        line's main (pre-em-dash) words — so a supertype like "legendary"
        rides along harmlessly, only the recognised type words matter to a
        caller — folds in any layer-4 `_added_types`/removes `_removed_types`
        the same way `is_creature` does, and always includes "permanent"
        (everything on the battlefield is one, RULE 110.1) so a bare
        "whenever a permanent enters…" scope needs no special case.
        """
        main = self.card.type_line.partition("—")[0]
        words = {w for w in re.split(r"\s+", main.strip().lower()) if w}
        words |= self._added_types
        words -= self._removed_types
        words.add("permanent")
        if self.bestowed:
            # RULE 702.103b: an Aura enchantment, not a creature, while bestowed.
            words.discard("creature")
            words.add("enchantment")
        return words

    @property
    def loyalty(self) -> int:
        """Current loyalty (RULE 606.5b) — the count of loyalty counters."""
        return self.counters.get("loyalty", 0)

    @property
    def defense(self) -> int:
        """Current defense of a battle (RULE 310.4c) — its defense-counter
        count. The exact mirror of `loyalty`: a battle enters with counters
        equal to its printed defense (310.4b) and damage *removes* them
        (310.6) rather than being tracked as marked damage, so there is no
        separate "current defense" field to drift out of sync."""
        return self.counters.get("defense", 0)

    @property
    def lore(self) -> int:
        """Current chapter of a Saga (RULE 714) — its lore-counter count."""
        return self.counters.get("lore", 0)

    @property
    def level(self) -> int:
        """Level counters on a Leveler creature (RULE 711.4a)."""
        return self.counters.get("level", 0)

    @property
    def class_level(self) -> int:
        """Current class level of a Class enchantment (RULE 716.2c)."""
        return self.counters.get("class_level", 0)

    @property
    def plus_one_counters(self) -> int:
        """Net +1/+1 counters (positive) vs. -1/-1 counters (negative).

        The single number power/toughness are shifted by (RULE 122.3): a
        creature with two +1/+1 and one -1/-1 counter reads +1 here. Kept as
        a read/write property over the typed `counters` dict so older code
        and fixtures that set a bare net still work.
        """
        return self.counters.get("+1/+1", 0) - self.counters.get("-1/-1", 0)

    @plus_one_counters.setter
    def plus_one_counters(self, value: int) -> None:
        self.counters.pop("+1/+1", None)
        self.counters.pop("-1/-1", None)
        if value > 0:
            self.counters["+1/+1"] = value
        elif value < 0:
            self.counters["-1/-1"] = -value

    def add_counters(self, kind: str, amount: int = 1) -> None:
        """Add (or, with a negative ``amount``, remove) counters of ``kind``.

        Counter totals never go below zero — removing more than are present
        drops the kind entirely (RULE 122.1c: a counter you can't remove
        simply isn't there).
        """
        total = self.counters.get(kind, 0) + amount
        if total > 0:
            self.counters[kind] = total
        else:
            self.counters.pop(kind, None)

    @property
    def power(self) -> Optional[int]:
        """Effective power (RULE 613 layer 7), or None for non-creatures.

        Prefers the value the continuous-effects engine stamped (which already
        folds in counters and any static modifiers); falls back to printed
        power plus counters when no layer pass has run (off-battlefield, unit
        tests). None only for something that is not a creature and has no
        layer-7 value (so an animated land still reports its P/T)."""
        if self._derived_power is not None:
            return self._derived_power
        if self.card.power is None:
            return None
        return self.card.power + self.plus_one_counters + self.perpetual_power

    @property
    def toughness(self) -> Optional[int]:
        """Effective toughness (RULE 613 layer 7); see `power`."""
        if self._derived_toughness is not None:
            return self._derived_toughness
        if self.card.toughness is None:
            return None
        return self.card.toughness + self.plus_one_counters + self.perpetual_toughness

    def copy_perpetual_from(self, other: "GameObject") -> None:
        """MEC-98: a copy of a card carries that card's perpetual changes
        (Alchemy — "conjure a duplicate" keeps a perpetual +1/+1)."""
        self.perpetual_power = other.perpetual_power
        self.perpetual_toughness = other.perpetual_toughness
        self.perpetual_keywords = set(other.perpetual_keywords)
        self.perpetual_effects = [dict(e) for e in other.perpetual_effects]

    @property
    def granted_keywords(self) -> set[str]:
        """Keyword slugs granted by layer-6 static abilities (RULE 613.7f)."""
        return set(self._granted_keywords)

    def parametric_keyword_value(self, name: str) -> Optional[int]:
        """ENG-31: the effective number for a parametric keyword — a
        *granted* value (`_granted_parametric_keywords`, re-derived each
        `continuous.recompute` from a layer-6 grant or
        `temp_parametric_keywords`) if one applies, else the printed value
        bound once onto `parametric_keywords` (``{"n": ...}``). ``None`` when
        the object has the keyword by neither route."""
        granted = self._granted_parametric_keywords.get(name)
        if granted is not None:
            return int(granted)
        printed = (self.parametric_keywords or {}).get(name)
        if isinstance(printed, dict) and printed.get("n") is not None:
            return int(printed["n"])
        return None

    @property
    def removed_keywords(self) -> set[str]:
        """Keyword slugs stripped by a layer-6 "loses <keyword>" static
        ability (RULE 613.7f, e.g. Colossus Hammer)."""
        return set(self._removed_keywords)

    @property
    def granted_protections(self) -> set[str]:
        """RULE 702.16 protection qualities granted by a layer-6 standing
        static ability, as `combat.protections_of_text` tokens — see
        `_granted_protections`."""
        return set(self._granted_protections)

    @property
    def combat_restrictions(self) -> list[dict[str, Any]]:
        """RULE 508.1a/509.1b parameterized combat restrictions granted by a
        standing static ability — see `_combat_restrictions`. Copied out so a
        caller can't mutate the recompute's own list."""
        return [dict(entry) for entry in self._combat_restrictions]

    @property
    def loses_all_abilities(self) -> bool:
        """Whether a layer-6 "loses all abilities" static ability (Humility,
        Dress Down) is stripping every ability off this object (RULE 613.7f)."""
        return self._loses_all_abilities

    @property
    def granted_mana_options(self) -> list[dict[str, int]]:
        """Mana-production options a layer-6 "X have '{T}: Add …'" static
        ability grants this object (Tyvar Kell) — folded onto the printed
        ones by `mana_abilities.mana_options_for`."""
        return list(self._granted_mana)

    @property
    def granted_mana_ability_upgrades(self) -> list[dict[str, Any]]:
        """MEC-25: the *non*-tap-only sibling of `granted_mana_options` —
        "X have '{cost}: Add …'" grants whose cost isn't a bare ``{T}``
        (Goldspan Dragon's "Treasures you control have '{T}, Sacrifice this
        artifact: Add two mana of any one color.'"). Each entry is
        ``{"cost": ActivationCost, "options": [...]}``. Unlike
        `granted_mana_options`, this *replaces* a printed ability whose cost
        has the same shape rather than adding an independent one alongside
        it — see `mana_abilities.mana_abilities_for`."""
        return list(self._granted_mana_upgrades)

    @property
    def granted_triggered_abilities(self) -> list[Any]:
        """Triggered abilities a layer-6 static ability granted this object."""
        return list(self._granted_triggered_abilities)

    @property
    def granted_activated_abilities(self) -> list[Any]:
        """Activated abilities a layer-6 static ability granted this object
        (Umbral Mantle/Squirrel Nest-shaped "<host> has '{cost}: <effect>.'")
        plus any resolve-time, turn-scoped grant (MEC-23's
        `temp_granted_activated_abilities` — Quicksilver Elemental's own
        "gains all activated abilities of target creature until end of
        turn") — read together with `activated_abilities` (this object's
        own printed ones) by `GameEngine.can_activate`/`activate_ability`/
        `legal_actions`, mirroring `granted_triggered_abilities`."""
        return list(self._granted_activated_abilities) + list(self.temp_granted_activated_abilities)

    # -- State transitions ----------------------------------------------

    def tap(self) -> None:
        self.tapped = True

    def untap(self) -> None:
        self.tapped = False

    #: The catalogue-derived fields a face-down swap replaces wholesale —
    #: kept in step with `game/copy_mechanics.py`'s `_FACE_ATTRS` (the same
    #: bundle a copy/transform swap saves), duplicated here rather than
    #: imported so the model layer keeps its no-`game/`-at-import-time rule.
    _FACE_ATTRS: tuple[str, ...] = (
        "spell_effects",
        "triggered_abilities",
        "activated_abilities",
        "static_effects",
        "replacement_effects",
        "enter_as_copy_effects",
        "intrinsic_keywords",
        "parametric_keywords",
    )

    def _face_snapshot(self) -> dict[str, Any]:
        """This object's current `Card` + catalogue-derived bindings."""
        snapshot: dict[str, Any] = {"card": self.card}
        for attr in self._FACE_ATTRS:
            value = getattr(self, attr, None)
            if isinstance(value, set):
                snapshot[attr] = set(value)
            elif isinstance(value, dict):
                snapshot[attr] = dict(value)
            else:
                snapshot[attr] = list(value or [])
        return snapshot

    def turn_face_down(self, card: Card, kind: str) -> None:
        """Become a face-down object presenting ``card`` (RULE 708.2).

        Stashes the face-up bundle (`_face_up_snapshot`) and clears every
        catalogue-derived ability, since a face-down object has no text at
        all — a morph creature's own ETB/attack triggers must not fire while
        it's face down, and RULE 708.3 says its enters-the-battlefield
        abilities don't even trigger on the way in. RULE 708.2b: a face-down
        permanent can't be turned face down again, so this is a no-op then.
        """
        if self.face_down:
            return
        self._face_up_snapshot = self._face_snapshot()
        self.card = card
        self.face_down = True
        self.face_down_kind = kind
        self.spell_effects = []
        self.triggered_abilities = []
        self.activated_abilities = []
        self.static_effects = []
        self.replacement_effects = []
        self.enter_as_copy_effects = []
        self.intrinsic_keywords = set()
        self.parametric_keywords = {}

    def turn_face_up(self) -> bool:
        """Regain the normal characteristics (RULE 708.8) — restores exactly
        what `turn_face_down` stashed. Returns whether anything changed.

        The bare state transition only: the rules consequences that go with
        the *special action* (paying a morph/manifest cost, RULE 702.37b's
        megamorph counter, the "turned face up" trigger) belong to
        `RulesEngine.turn_face_up`, which wraps this. Called directly — with
        no event — by `GameState.remove_from_battlefield`, since RULE 708.9's
        "reveal it as it moves" is not a turn-face-up that anything triggers
        off (RULE 701.40g's own wording for the analogous case)."""
        if not self.face_down:
            return False
        snapshot = self._face_up_snapshot or {}
        for attr, value in snapshot.items():
            setattr(self, attr, value)
        self.face_down = False
        self.face_down_kind = None
        self._face_up_snapshot = None
        return True

    def transform(self) -> bool:
        """Turn a double-faced permanent to its other face (RULE 712.8).

        Swaps ``card`` between the front and the back face (built from the
        card's ``back_*`` fields). Returns whether it flipped — a no-op (False)
        for a card with no back face. Loyalty is re-seeded when the new face is
        a planeswalker with no loyalty yet (a transforming planeswalker)."""
        if self.transformed:
            new_card = self._front_card
        else:
            new_card = self._front_card.back_face()
            if new_card is None:
                return False
        self.card = new_card
        self.transformed = not self.transformed
        if new_card.is_planeswalker and new_card.loyalty and "loyalty" not in self.counters:
            self.counters["loyalty"] = new_card.loyalty
        return True

    def to_dict(self) -> dict[str, Any]:
        """Serialize the instance's game state (for the wire protocol)."""
        display_keywords = _combat_display_keywords(
            self.card, self._granted_keywords | self.intrinsic_keywords,
            self._removed_keywords, self._granted_protections
        )
        # A summoning-sickness marker has meaning only for a creature
        # permanent. Haste removes the restriction immediately (RULE 702.10),
        # including a Haste grant applied after the permanent entered.
        is_summoning_sick = (
            self.zone == Zone.BATTLEFIELD
            and self.is_creature
            and self.summoning_sick
            and "Haste" not in display_keywords
        )
        return {
            "instance_id": self.instance_id,
            "card_id": self.card.id,
            "name": self.card.name,
            "owner_id": self.owner_id,
            "controller_id": self.controller_id,
            "zone": self.zone.value,
            "tapped": self.tapped,
            # Whether a double-faced permanent is on its back face (RULE 712.8).
            "transformed": self.transformed,
            # Whether this object *has* another face to show at all — read
            # off `_front_card` (stable across a transform) rather than the
            # currently-displayed `self.card`, so it stays true even while
            # showing the back. The frontend's "🔄 peek other face" toggle
            # uses this to decide whether to offer the button at all.
            "has_back_face": self._front_card.has_back_face,
            "summoning_sick": is_summoning_sick,
            "phased_out": self.phased_out,
            "damage_marked": self.damage_marked,
            "power": self.power,
            "toughness": self.toughness,
            "base_power": self.card.power,
            "base_toughness": self.card.toughness,
            # Card type info + combat/attachment state the board UI needs to
            # sort permanents into rows, group attachments, and show which
            # creature is attacking whom.
            "type_line": self.card.type_line,
            # `is_creature` honours a layer-4 type change (an animated land);
            # the rest read the printed card until those layers model them.
            "is_creature": self.is_creature,
            "is_land": self.card.is_land,
            "is_artifact": self.card.is_artifact,
            "is_enchantment": self.card.is_enchantment,
            "is_planeswalker": self.card.is_planeswalker,
            # Current loyalty for a planeswalker's board display (RULE 606.5b).
            "loyalty": self.loyalty if self.card.is_planeswalker else None,
            # RULE 310: a battle's defense-counter count for the board's own
            # badge (mirrors the loyalty badge above), plus its protector
            # (310.8) as a player id the board resolves against the players
            # it already has, so it can label the battle "protected by X".
            "is_battle": self.card.is_battle,
            "defense": self.defense if self.card.is_battle else None,
            "protector_id": self.protector_id if self.card.is_battle else None,
            # RULE 714: a Saga's chapter progress for the board's own badge
            # (mirrors the loyalty badge above) — `saga_final_chapter` is the
            # highest chapter number it has (0/no chapter lines → None, so
            # the frontend can tell "no chapters recognized" from "chapter 0").
            "is_saga": self.card.is_saga,
            "saga_final_chapter": (
                _saga_final_chapter_number(self.card) if self.card.is_saga else None
            ),
            # A token badge for the board (RULE 111); it also disappears from
            # non-battlefield zones by RULE 704.5d, so it only shows in play.
            "is_token": self.is_token,
            # RULE 715.3d: an exiled Adventure creature the player may cast.
            "adventure_castable": self.adventure_castable,
            # RULE 701.20a: exiled face down (Beseech the Mirror) — the board
            # renders a card back rather than the art. The name/type stay in
            # the payload: this app's goldfish/Replay views are all shown to
            # the card's own owner, who is exactly who *may* look at it.
            "face_down_in_exile": self.face_down_in_exile,
            "face_down_exile_viewers": sorted(self.face_down_exile_viewers),
            "hideaway_source_id": self.hideaway_source_id,
            # RULE 708.2: a face-down spell/permanent — the board renders the
            # active card-back sleeve rather than art, and shows the 2/2 that
            # `power`/`toughness` above already report. ``face_down_kind``
            # says which rule put it there (morph/disguise/manifest/cloak),
            # which is what decides how it may be turned face up. The card's
            # own identity is *not* in this payload at all: `card_id`/`name`/
            # `type_line` above read `self.card`, which is the synthetic
            # face-down face while it's down, so RULE 708.5's "only you may
            # look" holds for every viewer by construction.
            "face_down": self.face_down,
            "face_down_kind": self.face_down_kind,
            # RULE 722.3c: this object *is* a prepared copy sitting in exile,
            # castable as long as its source stays prepared — the mirror
            # image of `prepared` below (which flags the source permanent).
            "prepared_copy": self.prepared_source_id is not None,
            # RULE 722.3a: this permanent has become prepared (its exiled
            # copy is castable — see the "adventure_castable"-style scan of
            # the exile zone for that copy's own board tile/actions).
            "prepared": self.prepared,
            # RULE 702.33b/27a/34a: alt-cost casting state, for the board to
            # show a kicked/bought-back/flashed-back spell's own badge.
            "kicker_count": self.kicker_count,
            "kicker_x_paid": self.kicker_x_paid,
            "buyback_paid": self.buyback_paid,
            "cast_via_flashback": self.cast_via_flashback,
            # Types added by a layer-4 effect (e.g. "creature"), for the board.
            "added_types": sorted(self._added_types),
            # "As ~ enters, choose a creature type/color" (RULE 601.2b) — the
            # board shows this so a Sliver-lord-shaped permanent's chosen
            # tribe/color is visible, not just its effect.
            "chosen_type": self.chosen_type,
            "chosen_color": self.chosen_color,
            "chosen_colors": list(self.chosen_colors),
            "chosen_card_name": self.chosen_card_name,
            "chosen_number": self.chosen_number,
            "attacking": self.attacking,
            "attacked_this_turn": self.attacked_this_turn,
            # PAR-28 RULE 719.3b: the "solved" designation, for the board to
            # show a Case's solved badge and enable its Solved ability.
            "is_solved": self.is_solved,
            # RULE 701.60a: the "suspected" designation (menace + can't block),
            # for the board to show a badge.
            "is_suspected": self.is_suspected,
            # RULE 701.35b: "detained" (can't attack/block, abilities can't be
            # activated) — a bool for the board; the per-detainer set is
            # engine-internal.
            "is_detained": bool(self.detained_by),
            "combat_defender": self.combat_defender,
            "blocking": self.blocking,
            "additional_blocking": list(self.additional_blocking),
            "blocked_by": list(self.blocked_by),
            # Combat/evasion keyword labels the board shows as badges — the
            # same recognition the combat engine honours (printed keywords plus
            # any bound off the card by the parser and any granted by a layer-6
            # static ability), so display matches behaviour. Imported at call
            # time: `game.combat` is pure (no runtime model imports), so this
            # reads keywords without turning the model→game boundary into an
            # import cycle.
            "keywords": display_keywords,
            "counters": dict(self.counters),
            "attached_to": self.attached_to,
            # Layer-by-layer record of static effects that reshaped this object
            # (RULE 613), surfaced by the UI's optional static-effects panel.
            "static_trace": [dict(entry) for entry in self.static_trace],
        }

    def __repr__(self) -> str:
        return f"GameObject(#{self.instance_id} {self.card.name!r} in {self.zone.value})"
