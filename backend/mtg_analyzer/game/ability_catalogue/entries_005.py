"""Card -> AbilitySpec catalogue entries, part 005 of 016.

Mechanically split, in original file order, from the single flat
`ability_catalogue.py` module (now `core.py` for the shared registry
infrastructure + this package's `entries_NNN.py` files for the actual
per-card factories). Boundaries are purely positional -- not organized
by mechanic or card type -- see `__init__.py` for the full picture.
"""

from __future__ import annotations

from ...models.game.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

def _boromir_warden_of_the_tower() -> list[AbilitySpec]:
    """Vigilance
    Whenever an opponent casts a spell, if no mana was spent to cast it,
    counter that spell.
    Sacrifice Boromir: Creatures you control gain indestructible until end
    of turn. The Ring tempts you.

    — Boromir, Warden of the Tower. Shares Lavinia's ``mana_spent`` trigger
    verbatim (see her entry). Vigilance comes from the RULE 702 keyword
    catalogue, independent of this registry.

    "The Ring tempts you." (RULE 701.51a) is now real: `RulesEngine.
    the_ring_tempts_you` levels the tempting player's Ring emblem up (0–4,
    `Player.ring_level`) and re-chooses their Ring-bearer (`Player.
    ring_bearer_id`, an interactive ``ring_bearer`` `pending_choice` when
    there's more than one creature to pick). The emblem's four abilities are
    all source-less like the monarch's and the initiative's — ability 1 is a
    static split between `continuous._apply_ring_bearer_static` (legendary)
    and `GameEngine.can_block` (the greater-power blocking restriction),
    abilities 2–4 are built fresh per firing by `RulesEngine.
    _collect_ring_triggers`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "filter": {"mana_spent": 0},
                "reflexive": True,
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "keywords": ["indestructible"],
                "selector": "creatures_you_control",
            }), EffectSpec("the_ring_tempts_you", {})],
            cost={"sacrifice": "self"},
        ),
    ]


register("Boromir, Warden of the Tower", _boromir_warden_of_the_tower)


def _hope_of_ghirapur() -> list[AbilitySpec]:
    """Flying
    Sacrifice Hope of Ghirapur: Until your next turn, target player who was
    dealt combat damage by Hope of Ghirapur this turn can't cast noncreature
    spells.

    — Hope of Ghirapur. Two firsts here, both forced by the card:

    * a **history-filtered target kind** (`targeting.py`'s
      ``player_dealt_combat_damage_by_source``). By the time the sacrifice
      ability is activated the combat damage step is long over and nothing
      on the board records who got hit, so `GameState.
      combat_damage_to_players_this_turn` keeps the tally (keyed by source,
      so two copies each track their own victims). With no one hit this
      turn the ability simply has no legal target and RULE 601.2c makes it
      unactivatable — exactly right, and fail-closed.
    * a **player-scoped cast prohibition with no permanent behind it**
      (`PlayerCastRestrictionEffect`). Hope has sacrificed *itself* to pay
      for this, so there is nothing for `continuous.recompute` to read a
      static off; it lives on `Player.player_effects` for the same reason
      the RULE 615 damage shield does, and lapses when the *controller's*
      next turn begins (RULE 611.2b, swept in `GameEngine.begin_turn`).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("player_cast_restriction", {"noncreature": True})],
            cost={"sacrifice": "self"},
        ),
    ]


register("Hope of Ghirapur", _hope_of_ghirapur)


def _thassas_oracle() -> list[AbilitySpec]:
    """When this creature enters, look at the top X cards of your library,
    where X is your devotion to blue. Put up to one of them on top of your
    library and the rest on the bottom of your library in a random order.
    If X is greater than or equal to the number of cards in your library,
    you win the game.

    — Thassa's Oracle. Needed the **devotion** count selector (RULE 202.2f):
    `Card.mana_cost` already tallies symbols per colour *and* already counts
    a hybrid pip toward both of its colours, which is precisely devotion's
    definition, so `continuous.count_selector`'s ``devotion_to_<colour>``
    entries read it directly with no cost re-parse.

    The win check (RULE 104.2a) is evaluated *before* anything moves and
    routes through `RulesEngine.player_wins`, the same choke point Jace,
    Wielder of Mysteries uses — so a "you can't win the game" effect would
    stop both in one place. Note X >= 0 wins on an empty library even with
    devotion 0, which is correct and is the actual cEDH line (Oracle after
    Demonic Consultation).

    **Documented simplification**: the dig itself is non-interactive —
    the top card stays on top, the rest go to the bottom. In every real line
    the card is cast to *win*, not to filter, so the choice is a formality;
    this matches the non-interactive auto-pick the engine already makes for
    sacrifice/discard costs.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("look_top_keep_one_on_top", {
                "count_selector": "devotion_to_blue",
                "win_if_count_at_least_library": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
        ),
    ]


register("Thassa's Oracle", _thassas_oracle)


def _eldritch_evolution() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Search your library for a creature card with mana value X or less, where
    X is 2 plus the sacrificed creature's mana value. Put that card onto the
    battlefield, then shuffle. Exile Eldritch Evolution.

    — Eldritch Evolution. The additional cost (RULE 601.2b) was already
    modeled; what was missing is that nothing *remembered what was
    sacrificed*. `StackItem.x` only ever threads a spell's announced {X},
    so the sacrificed permanent's mana value now gets its own channel
    (`GameObject.sacrificed_cost_mana_value`, stamped by `GameEngine.
    _pay_additional_cast_cost` right before the victim leaves) and
    `SearchLibraryEffect.mana_value_from` binds it into the search criteria
    at resolution time. With no cost paid it fails closed to "nothing
    matches" rather than searching unrestricted.

    "Exile Eldritch Evolution." is its own replacement of the normal
    graveyard destination — the shipped `ExileEffect` self mode
    (``target_kind=None``, no target), which `RulesEngine.resolve_top_of_
    stack` already honours by *not* also routing the card to the graveyard.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": {"type": "Creature"},
                    "destination": "battlefield",
                    "mana_value_from": {"source": "sacrificed_cost", "plus": 2, "cmp": "le"},
                }),
                EffectSpec("exile", {"target_kind": None}),
            ],
            additional_cost={"sacrifice": "creature"},
        ),
    ]


register("Eldritch Evolution", _eldritch_evolution)


def _neoform() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Search your library for a creature card with mana value equal to 1 plus
    the sacrificed creature's mana value, put that card onto the battlefield
    with an additional +1/+1 counter on it, then shuffle.

    — Neoform. Eldritch Evolution's sibling (see that entry for the
    ``mana_value_from`` channel), with two differences: the bound is
    *exact* rather than "or less" (``"cmp": "eq"``, emitted as a two-sided
    min/max since `models.cards.card_query` has no single "exactly N" key), and
    the found card arrives with a counter already on it
    (``extra_counters``, applied by `RulesEngine._finish_search` the moment
    it reaches the battlefield — RULE 614.1c-adjacent, but applied here
    rather than as an entry replacement because the counter comes from the
    *searching effect*, not the card's own printed text).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"},
                "destination": "battlefield",
                "mana_value_from": {"source": "sacrificed_cost", "plus": 1, "cmp": "eq"},
                "extra_counters": {"kind": "+1/+1", "count": 1},
            })],
            additional_cost={"sacrifice": "creature"},
        ),
    ]


register("Neoform", _neoform)


def _rite_of_flame() -> list[AbilitySpec]:
    """Add {R}{R}, then add {R} for each card named Rite of Flame in each
    graveyard.

    — Rite of Flame. Two halves of one `AddManaEffect`: the flat ``{R}{R}``
    as printed symbols, plus the board-reading bonus via the new
    ``amount_selector`` (`continuous.count_selector`'s
    ``cards_named_source_in_all_graveyards`` — a cross-player aggregate like
    the existing ``total_rad_counters_among_players``, but name-keyed).

    The name comes from the effect's **own source object**, never from a
    free-text literal in the spec — putting an arbitrary card name through
    the spec boundary would buy nothing and widen it. The resolving copy is
    on the stack rather than in a graveyard, so it never counts itself.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {
                "colors": ["R", "R"],
                "color": "R",
                "amount_selector": "cards_named_source_in_all_graveyards",
            })],
        ),
    ]


register("Rite of Flame", _rite_of_flame)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 2: mana primitives
#
# The headline new mechanism is the **triggered mana ability** (RULE
# 605.1b/605.4, `TriggeredAbility.mana_ability`): an ability that triggers
# off a mana ability and only produces mana never uses the stack at all — it
# resolves on the spot, so its mana is in the pool in time for the very
# payment that triggered it. Queueing it like an ordinary trigger would put
# the extra mana one full stack resolution too late to spend, which is the
# entire reason both Wild Growth and Kinnan are played.
#
# Alongside it: `GameContext.trigger_event` (RULE 603.1 — the firing event,
# exposed for exactly the resolution window, so an effect can depend on
# *which* firing without every `apply()` growing an event parameter) and the
# generalized `pay_cost_then` optional payment (RULE 118.3).
# ---------------------------------------------------------------------------


def _wild_growth() -> list[AbilitySpec]:
    """Enchant land
    Whenever enchanted land is tapped for mana, its controller adds an
    additional {G}.

    — Wild Growth. A **triggered mana ability** (RULE 605.1b): it triggers
    off a mana ability and produces only mana, so RULE 605.4 keeps it off
    the stack entirely and `RulesEngine._collect_triggers` resolves it
    immediately. That timing is the card — an extra {G} that arrived after a
    stack resolution would be useless for the spell you tapped the land to
    cast.

    The recipient is ``event_controller``, not the Aura's own controller:
    the text says "**its** controller", and RULE 110.2 lets those diverge
    under a control-change effect.

    Enchant land comes from the RULE 702 keyword catalogue; the trigger's
    subject is the shipped ``attached_permanent`` scoping (RULE 603.1), so
    it stops firing the instant the Aura is unattached, with no teardown.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["G"], "recipient": "event_controller"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "attached_permanent"},
                "mana_ability": True,
            },
        ),
    ]


register("Wild Growth", _wild_growth)


def _kinnan_bonder_prodigy() -> list[AbilitySpec]:
    """Whenever you tap a nonland permanent for mana, add one mana of any
    type that permanent produced.
    {5}{G}{U}: Look at the top five cards of your library. You may put a
    non-Human creature card from among them onto the battlefield. Put the
    rest on the bottom of your library in a random order.

    — Kinnan, Bonder Prodigy. Wild Growth's sibling — the same RULE 605.4
    triggered mana ability — but the *type* isn't printed: "any type that
    permanent produced" is only knowable from the firing, so
    `MirrorProducedManaEffect` reads the `TAPPED_FOR_MANA` event's
    ``produced`` payload off `GameContext.trigger_event`. That is narrower
    than `AddManaEffect`'s ``"ANY"`` sentinel (which offers every colour):
    Basalt Monolith copies {C}, and a Bloom Tender copies only what it
    actually made.

    The trigger's group subject is ``{"controller": "you"}`` with a
    nonland type filter, so an opponent's taps and your own lands are both
    correctly ignored.

    **Documented simplification**: with 2+ distinct types produced in a
    single tap (only possible for an "any combination of colours" ability)
    the first is copied rather than opening a choice — see
    `MirrorProducedManaEffect`. The activated ability's "non-Human" filter
    likewise collapses to a plain creature filter, the same simplification
    the shipped `impulsive_look` grammar already makes for subtype-negated
    filters elsewhere.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mirror_produced_mana", {"count": 1})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "controller": "you", "type": "nonland"},
                "mana_ability": True,
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("impulsive_look", {
                "count": 5,
                "criteria": "Creature",
                "hit_destination": "battlefield",
                "miss_destination": "library_bottom",
                "optional": True,
            })],
            cost={"text": "{5}{G}{U}"},
        ),
    ]


register("Kinnan, Bonder Prodigy", _kinnan_bonder_prodigy)


def _chrome_mox() -> list[AbilitySpec]:
    """Imprint — When this artifact enters, you may exile a nonartifact,
    nonland card from your hand.
    {T}: Add one mana of any of the exiled card's colors.

    — Chrome Mox (ENG-27's own sibling primitive, MEC-17 — RULE 702.45-
    adjacent Imprint's solo real card). The mana ability parses on its own
    (`game/mana_abilities.py`'s new ``_IMPRINTED_COLOR_ADD_RE`` →
    `ManaAbility.color_selector`'s ``"imprinted_card_colors"``, read fresh
    off `GameObject.linked_exile_id` every tap, unconditionally — mana
    abilities are parsed straight from the printed card, not gated on
    hand-authoring, the same reason ENG-27's Bloom Tender/Carpet of
    Flowers primitives needed no catalogue entry either); only the ETB
    exile-and-remember half is hand-authored here, via `ImprintEffect`
    (``exclude_card_types=["artifact", "land"]`` — Chrome Mox's own
    "nonartifact, nonland" filter) with ``remember=True`` threaded through
    `RulesEngine._request_choose_objects`'s general chooser.
    """
    # `optional` deliberately stays off the *spec* — the trigger itself is
    # unconditionally put on the stack (there's no separate RULE 603.5 "you
    # may" gating the trigger header, unlike a plain "you may draw a card"
    # body); `ImprintEffect`'s own `optional=True` default is what asks the
    # real "you may exile…" question at resolution, one prompt not two.
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("imprint", {"exclude_card_types": ["artifact", "land"]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Chrome Mox", _chrome_mox)


def _carpet_of_flowers() -> list[AbilitySpec]:
    """At the beginning of each of your main phases, if you haven't added
    mana with this ability this turn, you may add X mana of any one
    color, where X is the number of Islands target opponent controls.

    — Carpet of Flowers (ENG-27). Unlike Wild Growth/Kinnan just above,
    this one genuinely **targets** ("target opponent"), which RULE 605.5a
    disqualifies from ever being a mana ability at all regardless of what
    it produces — so it's an ordinary triggered ability that goes on the
    stack, not the RULE 605.4 off-stack shape. Two standing entries, one
    per main phase: the engine fires a real ``step="main1"``/``"main2"``
    event, never a generic ``"main"`` one (that spelling is `Mana Drain`'s
    own delayed-trigger-only sentinel, a different mechanism entirely).

    Both ride the same new primitives: `AddManaEffect.
    amount_from_target_count_selector` (X evaluated against the *resolved
    target*, not this permanent's own controller — `continuous.
    count_selector`'s pre-existing ``lands_you_control_of_type_island``,
    scoped to whichever opponent got picked) and `once_per_turn_ability`
    (`GameObject.added_mana_with_ability_this_turn`, reset each untap
    step). ``optional=True`` is RULE 603.5's "you may" — declining never
    puts the trigger on the stack at all, so a decline never touches the
    once-per-turn flag either, exactly matching a real "no, thanks" at the
    table. **Documented simplification**: the "if you haven't added mana…"
    gate is a resolve-time no-op rather than a full RULE 603.4
    intervening-if, so the "you may" prompt can still appear on a turn
    it would do nothing (see `AddManaEffect`'s own docstring) — no
    observable difference once resolved, since it just adds no mana either way.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {
                "colors": ["ANY"],
                "target_kind": "opponent",
                "amount_from_target_count_selector": "lands_you_control_of_type_island",
                "once_per_turn_ability": True,
            })],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": step},
                "phase_relation": "you",
            },
            optional=True,
        )
        for step in ("main1", "main2")
    ]


register("Carpet of Flowers", _carpet_of_flowers)


def _mana_web() -> list[AbilitySpec]:
    """Whenever a land an opponent controls is tapped for mana, tap all
    lands that player controls that could produce any type of mana that land
    could produce.

    — Mana Web. *Not* a mana ability (it produces none), so unlike Wild
    Growth/Kinnan above it uses the stack like any ordinary trigger.

    Both halves of "that player" / "that land" come from the firing event
    (`GameContext.trigger_event`). The reference land's production is
    re-derived from `game/mana_abilities.py` rather than read off the
    event's ``produced`` payload, because RULE 605.1a's wording is about
    what a land *could* produce: a dual land tapped for {U} still locks
    down every land making {U} **or** its other colour, which is the
    difference between Mana Web being a real prison piece and a rounding
    error.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap_matching_lands", {})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "controller": "not_you", "type": "land"},
            },
        ),
    ]


register("Mana Web", _mana_web)


def _mana_vault() -> list[AbilitySpec]:
    """This artifact doesn't untap during your untap step.
    At the beginning of your upkeep, you may pay {4}. If you do, untap this
    artifact.
    At the beginning of your draw step, if this artifact is tapped, it deals
    1 damage to you.
    {T}: Add {C}{C}{C}.

    — Mana Vault. Three of the four lines were already expressible; the two
    that weren't are now general primitives rather than one-offs:

    * "you may pay {4}. If you do, untap ~." is the new ``pay_cost_then``
      (RULE 118.3) — the general form of the shipped, energy-only
      `PayEnergyThenEffect`, reusing the very same `_can_pay_player_cost`/
      `_pay_player_cost` machinery ward and "sacrifice ~ unless you pay"
      share, so an arbitrary `ActivationCost` works without a fourth
      parallel payment path. `UntapSelfEffect` deliberately bypasses the
      untap-step restriction the card's own first line imposes — that
      restriction is about RULE 502.4, not about this ability.
    * "if this artifact is tapped" is a RULE 603.4 intervening-if about the
      ability's **own source's** state (`effect_binder`'s new
      ``source_state`` trigger key), rather than about the event or whose
      turn it is — the two intervening-if flavours that already existed.

    The mana ability and the untap restriction both come from the engine
    directly (the printed mana ability needs no spec; the restriction is the
    shipped ``no_untap`` static).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("no_untap", {})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{4}",
                "effects": [{"type": "untap_self", "params": {}}],
            })],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": "upkeep"},
                "phase_relation": "you",
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "target_kind": None, "selector": "controller"})],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": "draw"},
                "phase_relation": "you",
                "source_state": "tapped",
            },
        ),
    ]


register("Mana Vault", _mana_vault)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 3: control & zone effects
#
# Five shapes the engine had no way to express, each now a whitelisted
# primitive: a two-way control **exchange** (RULE 701.10, distinct from both
# shipped control shapes), **mass phasing** plus a player-scoped life lock
# (RULE 702.26b/119.6), pulling a **spell** off the stack into hand (RULE
# 400.1, distinct from bouncing a permanent), a bounce whose legal set
# depends on the *entering* permanent, and putting cards onto the
# battlefield from **hand**.
# ---------------------------------------------------------------------------


def _gilded_drake() -> list[AbilitySpec]:
    """Flying
    When this creature enters, exchange control of this creature and up to
    one target creature an opponent controls. If you don't or can't make an
    exchange, sacrifice this creature. This ability still resolves if its
    target becomes illegal.

    — Gilded Drake. Needed a genuine **control-exchange** primitive (RULE
    701.10): the shipped layer-2 ``control_change`` static reassigns one
    permanent for as long as its source sticks around, and
    `GainControlUntilEndOfTurnEffect` is a one-way, end-of-turn grab.
    Exchange is two-way, permanent, and survives its source leaving — the
    drake dying afterwards must *not* hand the creature back, which is
    exactly why the card sees play. So it's modeled as a straight
    `controller_id` swap (RULE 701.10c's one-shot change of control), not as
    a pair of continuous effects.

    "If you don't or can't make an exchange, sacrifice this creature" is
    RULE 701.10d — an exchange with only one exchangeable permanent doesn't
    happen at all — and falls out naturally: ``optional=True`` on the target
    makes "no target" a legal choice, so the ability resolves, the exchange
    doesn't, and the sacrifice does (RULE 701.16c: sacrifice, never
    destruction, so nothing can regenerate out of it).

    Flying comes from the RULE 702 keyword catalogue.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control", {
                "target_kind": "creature",
                "sacrifice_self_if_no_exchange": True,
                "optional": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
        ),
    ]


register("Gilded Drake", _gilded_drake)


def _volatile_stormdrake() -> list[AbilitySpec]:
    """Flying, hexproof from activated and triggered abilities

    When this creature enters, exchange control of this creature and
    target creature an opponent controls. If you do, you get {E}{E}{E}{E},
    then sacrifice that creature unless you pay an amount of {E} equal to
    its mana value.

    — Volatile Stormdrake, MEC-43. The Gilded Drake-shaped exchange
    (RULE 701.10) plus an Energy-conditional sacrifice-unless-pay bundled
    into one composite effect (`exchange_control_then_energy_sacrifice`,
    `ExchangeControlThenEnergySacrificeEffect`), since RULE 608.2b's "if
    you do" here gates on whether the exchange itself happened — the same
    "action, if you do, consequence" shape Temur Sabertooth/Akiri's own
    bespoke effects already use rather than a cross-effect signal
    `_apply_effects_partitioned` has no channel for. Flying/hexproof come
    from the RULE 702 keyword catalogue.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control_then_energy_sacrifice", {
                "target_kind": "creature",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
        ),
    ]


register("Volatile Stormdrake", _volatile_stormdrake)


def _teferis_protection() -> list[AbilitySpec]:
    """Until your next turn, your life total can't change and you gain
    protection from everything. All permanents you control phase out.
    Exile Teferi's Protection.

    — Teferi's Protection. Three simultaneous effects sharing one duration,
    so they're one primitive:

    * **mass phasing** (RULE 702.26b) — the shipped `PhaseOutEffect` only
      ever phased a single permanent, and deliberately unattached any Aura/
      Equipment on it. Here host and attachment phase out *together*, so the
      attachment stays valid throughout (RULE 702.26e) — which is the whole
      point of the card as a board-preserving answer. The duration needs no
      bookkeeping of its own: `GameEngine._step_untap`'s existing RULE
      702.26a sweep phases everything back in at your next untap step.
    * **"your life total can't change"** (RULE 119.6) — a *prohibition*, not
      a replacement that rewrites an amount, so `RulesEngine.gain_life`/
      `lose_life` check it at their choke points rather than routing it
      through `apply_replacements`.
    * **protection from everything** for a *player* (RULE 702.16e), which
      reduces to "is dealt no damage" — the only half a player can be
      subject to. Checked in `deal_damage` alongside the permanent-side
      `is_protected_from`, which can't answer it (players carry no printed
      protection).

    The latter two live on `Player.player_effects` (`PlayerShieldEffect`)
    for the same reason Hope of Ghirapur's lock does: the spell is already
    in the graveyard, so there is no permanent to derive a static from. Both
    lapse together in `GameEngine.begin_turn` (RULE 611.2b).

    "Exile Teferi's Protection." is the shipped `ExileEffect` self mode.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("phase_out_all_you_control", {}),
                EffectSpec("exile", {"target_kind": None}),
            ],
        ),
    ]


register("Teferi's Protection", _teferis_protection)


def _narsets_reversal() -> list[AbilitySpec]:
    """Copy target instant or sorcery spell, then return it to its owner's
    hand. You may choose new targets for the copy.

    — Narset's Reversal. The copy half was already shipped
    (`CopySpellEffect`); the *bounce* half needed a new engine primitive:
    every existing "return to hand" moves a battlefield permanent, and this
    one pulls a `StackItem` off the stack entirely (`RulesEngine.
    return_spell_to_hand`, RULE 400.1). Practically that's a counter that
    leaves the card in hand instead of the graveyard — which is why it beats
    "can't be countered".

    Kept as one atomic effect rather than two composed ones for the same
    reason `GainControlUntilEndOfTurnEffect` is: both clauses act on the
    *same* chosen spell, and two separate targeting effects would prompt for
    it twice. Order matters and is the card's whole trick — the copy is made
    **first**, so it survives the original being picked up.

    **Documented simplification**: "You may choose new targets for the copy"
    keeps the original's targets, the same MVP choice `CopySpellEffect`'s
    own docstring already documents for every card in this family.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]}),
                EffectSpec("return_to_hand", {
                    "previous_subject": True, "spell_or_permanent": True,
                }),
            ],
        ),
    ]


register("Narset's Reversal", _narsets_reversal)


def _reiterate() -> list[AbilitySpec]:
    """Buyback {3}
    Copy target instant or sorcery spell. You may choose new targets for the
    copy.

    — Reiterate. Needed nothing new at all: Buyback (RULE 702.27) has been a
    real, payable additional cost since the keyword catalogue landed
    (`GameEngine._buyback_cost`/`GameObject.buyback_paid`, with
    `RulesEngine.resolve_top_of_stack` returning the card to hand instead of
    the graveyard), and `CopySpellEffect` was already built — its own
    docstring names Reiterate. It was simply never registered, so the
    fail-closed coverage gate left the card `UNMODELED` on the strength of
    the unparsed body. Registering it is the whole fix.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
        ),
    ]


register("Reiterate", _reiterate)


def _cloudstone_curio() -> list[AbilitySpec]:
    """Whenever a nonartifact permanent you control enters, you may return
    another permanent you control that shares a permanent type with it to
    its owner's hand.

    — Cloudstone Curio. "Shares a permanent type **with it**" is why this
    can't be an ordinary bounce with a target kind: the legal set depends on
    the *entering* permanent, which is only known per firing. It reads
    `GameContext.trigger_event` (the RULE 603.1 firing event, exposed for
    exactly the resolution window) and narrows to permanents sharing one of
    its RULE 205.2a main types.

    The trigger's group subject uses the negated type filter added for
    Kinnan (``"type": "nonartifact"``), so the artifact half of the printed
    restriction is real rather than dropped.

    **Documented simplification**: the "you may … return" *pick* is
    non-interactive (most recently added matching permanent). The trigger
    itself is already ``optional``, so the machinery does ask whether to
    bounce at all — and Cloudstone Curio's real use is a deliberate two-card
    loop where the intended permanent is unambiguous.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_shared_type_permanent", {})],
            optional=True,
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "controller": "you", "type": "nonartifact",
                },
            },
        ),
    ]


register("Cloudstone Curio", _cloudstone_curio)


def _tooth_and_nail() -> list[AbilitySpec]:
    """Choose one —
    • Search your library for up to two creature cards, reveal them, put
      them into your hand, then shuffle.
    • Put up to two creature cards from your hand onto the battlefield.
    Entwine {2}

    — Tooth and Nail. The second mode needed the one genuinely new shape:
    every "put onto the battlefield" in the engine moves a card out of a
    *library* (a search) or a *graveyard* (reanimation), never an open pick
    from hand. `PutFromHandOntoBattlefieldEffect` reuses `RulesEngine.
    _request_search`'s interactive one-at-a-time choice against a new
    ``"hand"`` search zone, so the prompt, the undo snapshots and the "up to
    N" semantics match every other pick rather than needing a parallel
    choice kind wired through the session and frontend. `_request_search`
    already keys its shuffle and its `LIBRARY_SEARCHED` event to
    ``"library"``, so a hand pick correctly does neither.

    **Entwine (RULE 702.42a)** is now a real additional cost rather than the
    free RULE 700.2e ``or_both`` flag it used to borrow: the ``entwine`` key
    on the modes block prices the combined offer, so "choose all" costs
    {2} more and is *locked* when that {2} isn't available — which matters,
    because the both-modes line (tutor two creatures, then put them onto the
    battlefield) is the entire reason the card is played, and getting it for
    free made the spell strictly better than printed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "entwine": "{2}",
                "options": [
                    [EffectSpec("search", {
                        "criteria": {"type": "Creature"},
                        "destination": "hand",
                        "count": 2,
                    })],
                    [EffectSpec("put_from_hand_onto_battlefield", {
                        "criteria": {"type": "Creature"},
                        "count": 2,
                    })],
                ],
                "descriptions": [
                    "Durchsuche deine Bibliothek nach bis zu zwei Kreaturenkarten "
                    "und nimm sie auf die Hand.",
                    "Bringe bis zu zwei Kreaturenkarten aus deiner Hand ins Spiel.",
                ],
            },
        ),
    ]


register("Tooth and Nail", _tooth_and_nail)


def _wandering_archaic() -> list[AbilitySpec]:
    """Whenever an opponent casts an instant or sorcery spell, they may pay
    {2}. If they don't, you may copy that spell. You may choose new targets
    for the copy.

    — Wandering Archaic // Explore the Vastlands. The tax is the new
    ``pay_cost_then`` (RULE 118.3), with two features this card is what
    forced: the **payer** is the player named by the triggering event (the
    opponent who cast the spell), not the effect's own controller; and the
    "**If they don't**, …" branch is where all the action is — the
    else-branch is what copies the spell.

    "That spell" is the RULE 603.3d ``reflexive`` trigger shape, so the copy
    acts on the exact spell that fired the trigger rather than a freshly
    chosen target — the same mechanism Lavinia's "counter that spell" uses.
    An opponent who can't afford {2} is never asked (the shortcut ward and
    `counter_unless_pays` already take), and the else-branch fires straight
    away.

    **Documented simplification**: "you *may* copy" is taken (the copy is
    the only reason the trigger exists), and new targets aren't chosen — the
    same `CopySpellEffect` MVP the whole copy family shares. The back face
    "Explore the Vastlands" is a modal-DFC land half, covered by the shipped
    MDFC machinery independently of this registration.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{2}",
                "payer": "event_player",
                "effects": [],
                "else_effects": [
                    {"type": "copy_spell", "params": {"card_types": ["instant", "sorcery"]}},
                ],
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_card_types": ["instant", "sorcery"],
                "reflexive": True,
            },
        ),
    ]


register("Wandering Archaic", _wandering_archaic)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 4: naming a card, and the three loops
#
# Four genuinely new engine shapes, each previously listed as its own
# blocker:
#
# * **naming a card** (`_request_name_card`) — the only choice in the engine
#   whose answer space isn't enumerable from game state.
# * **dig-until-a-predicate** (`RulesEngine.dig_until`) — the cascade dig
#   generalized so both the predicate and both destinations are parameters.
# * **repeat-until-a-predicate** (`MillUntilCreatureEffect`) — every other
#   repetition here had its count fixed before it started.
# * **an open-ended loop** (`_request_look_top_pay_life_loop`) — bounded by
#   its own life payment rather than by any counter.
# ---------------------------------------------------------------------------


def _demonic_consultation() -> list[AbilitySpec]:
    """Choose a card name. Exile the top six cards of your library, then
    reveal cards from the top of your library until you reveal a card with
    the chosen name. Put that card into your hand and exile all other cards
    revealed this way.

    — Demonic Consultation. Two firsts, composed:

    * **Naming a card** (`NameCardThenEffect`). Every other `pending_choice`
      picks from a set the engine can enumerate; a player may name any card
      in Magic. So the choice offers the names the player can actually see
      (their own hand/library/graveyard) as *suggestions* and accepts an
      arbitrary string, which is then only ever compared against card names
      — never interpreted — keeping docs/09's security boundary intact.
    * **Dig-until-a-predicate** (`RulesEngine.dig_until`), the cascade dig
      with the predicate and both destinations made parameters. The chosen
      name reaches it through the ``"named_card"`` criteria sentinel,
      substituted at answer time exactly like `_substitute_x` handles an
      announced {X}.

    Naming a card that *isn't* in the library exiles the whole library
    rather than erroring — which is not a degenerate case but the actual
    cEDH line: Consultation into an empty library, then Thassa's Oracle.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("name_card_then", {
                "effects": [{
                    "type": "dig_until",
                    "params": {
                        "criteria": {"name": "named_card"},
                        "pre_exile": 6,
                        "hit_destination": "hand",
                        "rest_destination": "exile",
                    },
                }],
            })],
        ),
    ]


register("Demonic Consultation", _demonic_consultation)


def _helm_of_obedience() -> list[AbilitySpec]:
    """{X}, {T}: Target opponent mills a card, then repeats this process
    until a creature card or X cards have been put into their graveyard this
    way, whichever comes first. If one or more creature cards were put into
    that graveyard this way, sacrifice this artifact and put one of them
    onto the battlefield under your control. X can't be 0.

    — Helm of Obedience. The engine's first **repeat-until-a-predicate**
    loop: every other repetition primitive (mill N, draw N, proliferate) has
    its count fixed before it starts. Here X is only a *cap* and the real
    stopping condition is what the mill turned up, so the loop has to
    re-check after every iteration.

    Bounded on both sides by construction — X caps the iterations, an empty
    library ends it early — which is the property that makes having a
    "repeat until" primitive safe at all. "X can't be 0" falls out of the
    same guard.

    Note the reanimated creature arrives under **your** control (RULE
    110.2), not its owner's, and the Helm sacrifices itself only when a
    creature was actually hit (RULE 701.16c: sacrifice, so nothing can
    regenerate out of it).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("mill_until_creature", {"amount": "x", "target_kind": "player"})],
            cost={"text": "{X}", "taps_self": True},
        ),
    ]


register("Helm of Obedience", _helm_of_obedience)


def _lim_duls_vault() -> list[AbilitySpec]:
    """Look at the top five cards of your library. As many times as you
    choose, you may pay 1 life, put those cards on the bottom of your
    library in any order, then look at the top five cards of your library.
    Then shuffle and put the last cards you looked at this way on top in any
    order.

    — Lim-Dûl's Vault. The engine's only **open-ended** loop: every other
    repetition has a fixed count or a hard cap, whereas here the player
    decides after each iteration whether to go again. Driven by a
    `pending_choice` that re-opens itself (the same self-re-opening shape a
    multi-card search already uses) with no counter running down.

    It is still bounded, by the card's own payment rather than a safety
    valve bolted on: each iteration costs 1 life and the choice simply isn't
    offered once the player couldn't survive another (RULE 118.4).

    Stopping shuffles **first** and puts the last batch back on top
    afterwards — RULE 701.19e's ordering, the same one `_finish_search`
    already uses for a library destination; the other order would scatter
    the very cards the card promises to leave on top.

    **Documented simplification**: "in any order" isn't an interactive
    five-card reorder — the batch keeps its relative order. The card is
    played to *find* something, and the top card is what the next draw takes
    either way.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("look_top_pay_life_loop", {"count": 5, "life_cost": 1})],
        ),
    ]


register("Lim-Dûl's Vault", _lim_duls_vault)


def _tibalts_trickery() -> list[AbilitySpec]:
    """Counter target spell. Choose 1, 2, or 3 at random. Its controller
    mills that many cards, then exiles cards from the top of their library
    until they exile a nonland card with a different name than that spell.
    They may cast that card without paying its mana cost. Then they put the
    exiled cards on the bottom of their library in a random order.

    — Tibalt's Trickery. One atomic `ScrambleSpellEffect`, shared with
    Possibility Storm below: both answer a spell and then dig **its
    controller's** library for a replacement they may cast free, differing
    only in how the spell is answered and what the dig looks for. A
    composition of separate counter/mill/dig effects couldn't work — every
    clause is about the same spell and the same (not-the-caster) player, and
    the dig's predicate is derived from that spell's own name via the new
    ``not_name`` criteria key (`models.cards.card_query`), the negated form of an
    exact name match, kept as its own key rather than a magic value inside
    ``name`` so a criteria dict stays literal data.

    **Documented simplifications**, both about hidden information the
    goldfish/replay model has no place for yet: "choose 1, 2, or 3 at
    random" is resolved by the engine rather than by a secret simultaneous
    number choice (there is no hidden-information channel between players),
    and "they may cast that card" is taken automatically — the free cast is
    the only reason anyone resolves this. Tracked in
    `docs/implementation-state/BACKLOG.md`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("scramble_spell", {
                "answer": "counter",
                "match": "different_name",
                "mill_random_max": 3,
            })],
        ),
    ]


register("Tibalt's Trickery", _tibalts_trickery)


def _possibility_storm() -> list[AbilitySpec]:
    """Whenever a player casts a spell from their hand, that player exiles
    it, then exiles cards from the top of their library until they exile a
    card that shares a card type with it. That player may cast that card
    without paying its mana cost. Then they put all cards exiled with this
    enchantment on the bottom of their library in a random order.

    — Possibility Storm. Three things had to exist for this:

    * "casts a spell **from their hand**" — the `SPELL_CAST` event now
      carries ``from_hand``, snapshotted before the card leaves its zone
      (by the time the event fires it already sits on the stack).
    * "**that** spell" is the RULE 603.3d ``reflexive`` trigger shape, so
      the exile acts on the exact spell that fired the trigger.
    * "shares a card type **with it**" (RULE 205.2) is read off the
      answered spell's own types, snapshotted before it leaves the stack.

    Note "that player **exiles** it" is a zone change, not a counter
    (`RulesEngine.move_spell_off_stack`) — which is why Possibility Storm
    also gets around "can't be countered". The whole tail runs against the
    *casting* player, who may be an opponent: Possibility Storm scrambles
    everyone's spells, which is the point.

    **Documented simplification**: "they may cast that card" is taken
    automatically, the same MVP choice the cascade family's own free cast
    documents.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("scramble_spell", {
                "answer": "exile",
                "match": "shares_card_type",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "filter": {"from_hand": True},
                "reflexive": True,
            },
        ),
    ]


register("Possibility Storm", _possibility_storm)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 5: keyword mechanics
#
# Four RULE 702 keywords that were bare `FLAG`/parametric recognition with no
# behaviour behind them — Fading (702.32), Soulbond (702.94), Mutate
# (702.140) and Bargain — plus a *granted* Escape (702.138 from Underworld
# Breach rather than printed on the card), and the Pacts, which needed
# nothing new at all beyond the `pay_cost_then` primitive wave 2 built.
# ---------------------------------------------------------------------------


def _tangle_wire() -> list[AbilitySpec]:
    """Fading 4
    At the beginning of each player's upkeep, that player taps an untapped
    artifact, creature, or land they control for each fade counter on this
    artifact.

    — Tangle Wire. **Fading (RULE 702.32)** is now a real keyword rather
    than a recognized-but-inert one, and both halves live with the keyword
    (not with this card), so every Fading/Vanishing card gets them:

    * 702.32a's entry counters are placed by `RulesEngine.
      _apply_entry_counters`, read off the **parsed keyword** rather than
      the reminder sentence — the keyword *is* the rule, and the reminder
      text isn't guaranteed to be printed.
    * 702.32b's "At the beginning of your upkeep, remove a fade counter. If
      you can't, sacrifice it." is synthesized in
      `effect_binder._keyword_triggered_abilities`, alongside annihilator/
      afflict/bushido. Note "if you can't" means *no counter left*, not a
      choice — which is why Fading N lasts N+1 of your upkeeps, not N.

    The card's own ability then reads the counter count **live** each
    upkeep, so the tax shrinks as Fading counts down — which is the entire
    design of the card.

    **Documented simplification**: which permanents get tapped is an
    auto-pick, the same non-interactive choice the engine already makes for
    every other "that player chooses" cost.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap_permanents_per_counter", {
                "kind": "fade",
                "types": ["artifact", "creature", "land"],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
        ),
    ]


register("Tangle Wire", _tangle_wire)


def _deadeye_navigator() -> list[AbilitySpec]:
    """Soulbond
    As long as Deadeye Navigator is paired with another creature, each of
    those creatures has "{1}{U}: Exile this creature, then return it to the
    battlefield under your control."

    — Deadeye Navigator. **Soulbond (RULE 702.94)** is now real pairing
    rather than a bare flag keyword. The pair itself is genuine game state
    (`GameObject.paired_with`, held on both objects) rather than a
    continuous effect, because RULE 702.94c breaks it on *events* — either
    creature leaving the battlefield, stopping being a creature, or the two
    ceasing to share a controller — which `RulesEngine.
    break_illegal_soulbond_pairs` sweeps as a state-based action so no
    individual site has to remember to tear it down.

    The pairing trigger is synthesized from the keyword itself
    (`effect_binder`), as *two* abilities: "when **either** enters" means it
    must fire both when Deadeye arrives and when a later unpaired creature
    joins it.

    The grant is then an ordinary layer-6 `grant_activated_ability` static
    over the new ``soulbond_pair`` selector, which resolves to the source
    plus its partner *and only while paired* — so an unpaired Navigator
    grants nothing, with no separate teardown. The granted ability is the
    shipped `blink` effect (RULE 400.7's genuine zone change, which is why
    it re-triggers enters-the-battlefield abilities — the whole point).

    **Documented simplification**: the partner is an auto-pick (the first
    other unpaired creature you control). The trigger is already
    ``optional``, so a player who wants a different partner declines.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_activated_ability", {
                "affects": "soulbond_pair",
                "cost": {"text": "{1}{U}"},
                "grant_effects": [{"type": "blink", "params": {}}],
            })],
        ),
    ]


register("Deadeye Navigator", _deadeye_navigator)


def _lore_drakkis() -> list[AbilitySpec]:
    """Mutate {U/R}{U/R}
    Whenever this creature mutates, return target instant or sorcery card
    from your graveyard to your hand.

    — Lore Drakkis. **Mutate (RULE 702.140)** is now a real cast mode rather
    than a recognized-but-inert keyword:

    * the Mutate cost is an *alternative* cast cost (`GameEngine.
      _mutate_cost`), substituted the same way Flashback/Escape already
      substitute theirs;
    * a mutate cast targets a creature you own and, on resolution, merges
      onto it instead of entering the battlefield
      (`RulesEngine.mutate_onto`). The **host** stays the surviving
      `GameObject`, which is what RULE 702.140c requires — the merged
      permanent is the *same* permanent, so counters, damage, Auras and
      summoning sickness all carry over, and no enters-the-battlefield
      trigger fires;
    * "the creature on top plus all abilities from under it" is modeled by
      banking whichever card ends up *underneath* on `GameObject.
      merged_oracle_text` and re-deriving abilities through the ordinary
      bind path — so the pile keeps accumulating abilities as further
      creatures mutate onto it, and mutate needs no ability-construction
      code of its own. Both directions of "over **or** under" work: which
      one applies is chosen as the spell is cast (RULE 702.140a,
      `GameObject.mutate_under`), and only which card supplies the printed
      face changes.
    * `EventType.MUTATES` then gives "whenever this creature mutates"
      something to trigger on — deliberately distinct from
      ENTERS_BATTLEFIELD, which mutate specifically does not fire.

    * the host is validated against a real ``non_human_creature_you_own``
      target kind (RULE 702.140a) — ownership rather than control (RULE
      108.3), and Humans genuinely excluded. Checked by `GameEngine.
      can_cast`/`_cast_current_face` directly, since a mutate creature
      spell carries no targeting *effect* for the ordinary RULE 115
      machinery to read.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_instant_or_sorcery",
                "destination": "hand",
            })],
            trigger={
                "event": EventType.MUTATES,
                "condition": {"subject": "self"},
            },
        ),
    ]


register("Lore Drakkis", _lore_drakkis)


def _beseech_the_mirror() -> list[AbilitySpec]:
    """Bargain
    Search your library for a card, exile it face down, then shuffle. If
    this spell was bargained, you may cast the exiled card without paying
    its mana cost if that spell's mana value is 4 or less. Put the exiled
    card into your hand if it wasn't cast this way.

    — Beseech the Mirror. **Bargain** is the optional additional cost
    "sacrifice an artifact, enchantment, or token as you cast this spell",
    now genuinely payable (`GameEngine.cast_spell(..., bargained=True)`,
    charged alongside every other additional cost) and recorded on
    `GameObject.bargained`.

    "If this spell was bargained, …" is then the existing
    `EffectSpec.condition` gate with a new ``"bargained"`` key — the exact
    shape Kicker's own ``"kicked"`` gate already had, reading a flag instead
    of a counter, so `ConditionalEffect` needed one branch rather than a new
    mechanism.

    The exile round trip is now genuinely modeled rather than collapsed to
    "tutor to hand, then cheat something into play": the search's
    ``"exile_face_down"`` destination sets `GameObject.face_down_in_exile`
    (RULE 701.20a — hidden from everyone but its owner), and
    `CastExiledFaceDownEffect` then hands out Rebound's own free-cast window
    (`RulesEngine.grant_free_cast_window_from_exile`) so the card is cast
    from exile through the ordinary action loop, with its full targeting and
    modal choices. The "put the exiled card into your hand if it wasn't cast
    this way" half is a `DelayedTrigger` at the next end step, and applies
    immediately instead when the card was never eligible to be cast (the
    spell wasn't bargained, or the card costs more than {4}).

    Note the two halves have *different* conditions, which is why this isn't
    a `ConditionalEffect` around a single cast: only the cast is gated on
    ``bargained``, while the return-to-hand always happens.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": "",
                    "destination": "exile_face_down",
                    "count": 1,
                }),
                EffectSpec(
                    "cast_exiled_face_down",
                    {"max_mana_value": 4, "require_bargained": True},
                ),
            ],
        ),
    ]


register("Beseech the Mirror", _beseech_the_mirror)


def _underworld_breach() -> list[AbilitySpec]:
    """Each nonland card in your graveyard has escape. The escape cost is
    equal to the card's mana cost plus exile three other cards from your
    graveyard.
    At the beginning of the end step, sacrifice this enchantment.

    — Underworld Breach. A **granted** Escape (RULE 702.138), which is a
    different thing from the printed keyword the engine already supported:
    it applies to cards in a *graveyard*, so no battlefield selector and no
    printed-keyword scan could ever reach them, and its cost has to be
    assembled per-card (each card's own mana cost plus the exile clause)
    rather than read from a fixed printed string.

    Modeled as a ``grant_escape`` static consulted by `GameEngine.
    _graveyard_cast_keyword`/`_escape_cost` (`continuous.
    granted_escape_for`), which is why the rest of the escape machinery —
    the zone gate, the alternative cost, `_pay_escape_graveyard_cost` —
    needed no changes at all. Kept out of `recompute` proper for the same
    reason the other permission statics are: nothing about the affected
    card's *characteristics* changes, so there is no layer to write it into.

    The self-sacrifice is the shipped `sacrifice_self` effect on an end-step
    trigger.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_escape", {
                "nonland_only": True,
                "exile_from_graveyard": 3,
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
        ),
    ]


register("Underworld Breach", _underworld_breach)


def _summoners_pact() -> list[AbilitySpec]:
    """Search your library for a green creature card, reveal it, put it into
    your hand, then shuffle.
    At the beginning of your next upkeep, pay {2}{G}{G}. If you don't, you
    lose the game.

    — Summoner's Pact. Needed **nothing new**: `CreateDelayedTriggerEffect`
    (RULE 603.7) has named "the Pacts" in its docstring since it was built,
    and wave 2's `pay_cost_then` supplies the missing half — the *mandatory*
    payment with a consequence. The Pact is simply `pay_cost_then` with an
    empty "if you do" branch and `lose_game` as the "if you don't" one,
    which is exactly how the card reads.

    A player who *can't* afford the payment is never asked and loses
    immediately — the same "don't stall on a choice nobody can act on"
    shortcut ward and "sacrifice ~ unless you pay" already take, and here it
    is also the correct outcome.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": {"type": "Creature", "color": "G"},
                    "destination": "hand",
                    "count": 1,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    "scope": "controller",
                    "description": "Summoner's Pact: {2}{G}{G} bezahlen oder das Spiel verlieren",
                    "effects": [{
                        "type": "pay_cost_then",
                        "params": {
                            "cost": "{2}{G}{G}",
                            "effects": [],
                            "else_effects": [{"type": "lose_game", "params": {}}],
                        },
                    }],
                }),
            ],
        ),
    ]


register("Summoner's Pact", _summoners_pact)


def _pact_of_negation() -> list[AbilitySpec]:
    """Counter target spell.
    At the beginning of your next upkeep, pay {3}{U}{U}. If you don't, you
    lose the game.

    — Pact of Negation. Summoner's Pact's sibling; see that entry for why
    the delayed "pay or lose" needed no new primitive. Note the counter half
    was already parsed — only the Pact clause left the card `UNMODELED`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("counter", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    "scope": "controller",
                    "description": "Pact of Negation: {3}{U}{U} bezahlen oder das Spiel verlieren",
                    "effects": [{
                        "type": "pay_cost_then",
                        "params": {
                            "cost": "{3}{U}{U}",
                            "effects": [],
                            "else_effects": [{"type": "lose_game", "params": {}}],
                        },
                    }],
                }),
            ],
        ),
    ]


register("Pact of Negation", _pact_of_negation)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 6: the bespoke tail
#
# The new shared primitive here is **two independently-chosen targets of
# different kinds in one clause** (`GameEffect.extra_target_specs`): the
# gathering paths (`RulesEngine._trigger_target_specs`,
# `targeting.spell_target_specs`) now read `target_specs` (plural), and
# `_apply_effects_partitioned` hands such an effect all of its groups
# flattened. That single change unblocks Brass Squire, Halvar and Archdruid's
# Charm, which were the whole "two independent targeting effects on one
# ability" entry on the blocker list.
# ---------------------------------------------------------------------------

