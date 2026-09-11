"""Card-draw, library-search, and casting-denial entries."""

from __future__ import annotations

from ...models.game.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

def _penance() -> list[AbilitySpec]:
    """Put a card from your hand on top of your library: The next time a
    black or red source of your choice would deal damage this turn,
    prevent that damage.

    — Penance (MEC-30, Phase 8). Unlike every other card in this family,
    the printed text has no "to you" at all — "prevent that damage"
    protects whoever the chosen source would have hit, not one fixed
    recipient — `RequestPreventDamageSourceEffect`'s new ``recipient=
    "any"`` (reaching `RulesEngine.prevent_damage_from_source`'s existing
    unscoped-recipient shield via `_apply_chosen_object`'s matching
    branch, rather than `prevent_damage_to_player`/`_to_target`'s fixed-
    recipient ones). ``source_filter``'s ``color_any`` (already shipped for
    Greater Realm of Preservation) covers "a black **or** red source"
    directly. The cost is the new "put a card from your hand on top of
    your library" non-mana cost (`costs.py`'s own
    ``_PUT_HAND_CARD_ON_LIBRARY_RE``/`RulesEngine.put_hand_card_on_top_of_
    library`) — which card leaves the hand is a genuine RULE 602.1 choice,
    resolved the same "chosen_ids, or auto-pick" way a plain discard-N cost
    already is (`ActivationMixin._resolve_put_hand_card_cost`).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_any": ["B", "R"]}, "amount": "all", "recipient": "any",
            })],
            cost={"text": "Put a card from your hand on top of your library"},
        ),
    ]


register("Penance", _penance)


def _seasoned_tactician() -> list[AbilitySpec]:
    """{3}, Exile the top four cards of your library: The next time a
    source of your choice would deal damage to you this turn, prevent
    that damage.

    — Seasoned Tactician (MEC-30, Phase 8). Otherwise the ordinary Circle
    of Protection template (unqualified ``source_filter``, default
    recipient — "to you"); the cost needed `costs.py`'s
    ``exile_top_of_library`` widened from a bare bool (Thought Lash's
    always-exactly-one) to a real printed count, since
    ``_EXILE_TOP_LIBRARY_RE`` only ever recognized "the top card" —
    checked every existing caller (`game/engine/activation_mixin.py`'s
    legality/payment, `game/mana_potential.py`'s tap-plan simulation)
    before widening so Thought Lash's own behaviour doesn't regress.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"text": "{3}, Exile the top four cards of your library"},
        ),
    ]


register("Seasoned Tactician", _seasoned_tactician)


def _bone_mask() -> list[AbilitySpec]:
    """{2}, {T}: The next time a source of your choice would deal damage
    to you this turn, prevent that damage. Exile cards from the top of
    your library equal to the damage prevented this way.

    — Bone Mask (MEC-30, Phase 8). The trailing sentence is a new
    `RulesEngine.apply_prevent_rider` kind, ``"exile_top_of_library_
    scaled"`` — `mill`'s exile-instead-of-graveyard sibling, since no
    existing primitive exiled a fixed count off the top of the library in
    one call.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all", "rider": {"kind": "exile_top_of_library_scaled"},
            })],
            cost={"text": "{2}, {T}"},
        ),
    ]


register("Bone Mask", _bone_mask)


def _mercenaries() -> list[AbilitySpec]:
    """{3}: The next time this creature would deal damage to you this
    turn, prevent that damage. Any player may activate this ability.

    — Mercenaries (MEC-30, Phase 7). RULE 602.2b: whoever activates an
    ability is that ability's controller for the purposes of its
    resolution, so "you" here means the *activator* — not Mercenaries'
    own permanent controller, which is who every other card in this
    family's "prevent damage to you" shape protects. Needed two small new
    primitives together: `ActivationCost.any_player_may_activate` widens
    `GameEngine.can_activate`'s ordinary "only the permanent's controller"
    eligibility gate; `GameContext.resolving_controller_id` (RULE 602.2b's
    activator, threaded through `RulesEngine.resolve_top_of_stack` around
    a stack item's own resolution, mirroring `trigger_event`'s existing
    save/restore pattern) is what `PreventDamageEffect`'s new
    `recipient_is_activator` reads instead of the permanent's printed
    controller. `watched_source_is_self` narrows the shield to
    Mercenaries' own damage specifically — the fixed-source, no-chooser-
    needed sibling of `RequestPreventDamageSourceEffect`'s "a source of
    your choice".
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("prevent_damage_shield", {
                "amount": "all", "watched_source_is_self": True, "recipient_is_activator": True,
            })],
            cost={"mana": "{3}", "any_player_may_activate": True},
        ),
    ]


register("Mercenaries", _mercenaries)


def _rhystic_circle() -> list[AbilitySpec]:
    """{1}: Any player may pay {1}. If no one does, the next time a source
    of your choice would deal damage to you this turn, prevent that
    damage.

    — Rhystic Circle (MEC-30, Phase 7 — the one flagged genuinely large
    build). "Any player may pay {1}." is a *resolve-time* tax, not the
    already-shipped single-payer `TaxedDrawEffect`/`pay_cost_then` shape —
    every player independently gets a chance to pay, in turn order, and
    the shield only grants once literally everyone has declined; the
    first player to pay cancels the whole thing. New primitive:
    `RequestAllPlayersDeclineOrEffect`/`RulesEngine.request_all_players_
    decline_or` (a chain of ordinary single-player pay/decline choices,
    the aggregate-outcome mirror of PAR-13's `_request_each_player_pay_or`
    — that one applies its effect *per decliner*, this one applies it
    *once*, only if *every* player declined). The activation cost itself
    ({1}) is ordinary — unlike Mercenaries, only Rhystic Circle's own
    controller may activate this ability at all; it's the ability's own
    *effect* that reaches out to every player at the table.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("all_players_decline_or", {
                "cost": "{1}",
                "effects": [{"type": "request_prevent_damage_source", "params": {"amount": "all"}}],
            })],
            cost={"mana": "{1}"},
        ),
    ]


register("Rhystic Circle", _rhystic_circle)


def _desperate_gambit() -> list[AbilitySpec]:
    """Choose a source you control and flip a coin. If you win the flip,
    the next time that source would deal damage this turn, it deals
    double that damage instead. If you lose the flip, the next time it
    would deal damage this turn, prevent that damage.

    — Desperate Gambit (MEC-30, last card of the family). A genuinely
    conditional effect-selection shape, not a rider: which of "double" or
    "prevent" applies isn't known until the coin lands, and both branches
    are scoped to the one chosen source rather than the caster's whole
    side. `ChooseSourceCoinFlipEffect` — the chosen-source chooser
    family's third member, narrowed to "a source **you control**" instead
    of "of your choice" — flips the coin only once the pick actually
    resolves and branches into the new `RulesEngine.grant_damage_
    multiplier_from_source` (win, the single-source-scoped sibling of
    `grant_damage_multiplier_this_turn`'s controller-wide shape) or the
    already-shipped `prevent_damage_from_source` (lose). The printed
    "Double" keyword is the ordinary keyword fold-in and needs no separate
    handling — it's just the cached card's own marker for the "deals
    double damage" clause, which the coin-flip branch above already fully
    expresses.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("choose_source_coinflip", {})],
        ),
    ]


register("Desperate Gambit", _desperate_gambit)


def _scab_clan_berserker() -> list[AbilitySpec]:
    """Haste
    Renown 1 (When this creature deals combat damage to a player, if it
    isn't renowned, put a +1/+1 counter on it and it becomes renowned.)
    Whenever an opponent casts a noncreature spell, if this creature is
    renowned, this creature deals 2 damage to that player.

    — Haste/Renown both come from the RULE 702 keyword catalogue
    (`effect_binder._keyword_triggered_abilities`, unaffected by this
    registration — see Relic Seeker's own entry); this only adds the
    card's own third ability, gated by the new `EffectSpec.condition` key
    ``source_is_renowned``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"},
                        condition={"source_is_renowned": True})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
        )
    ]


register("Scab-Clan Berserker", _scab_clan_berserker)


def _kamahl_heart_of_krosa() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, creatures you control get
    +3/+3 and gain trample until end of turn.
    {1}{G}: Until end of turn, target land you control becomes a 1/1
    Elemental creature with vigilance, indestructible, and haste. It's
    still a land.
    Partner (You can have two commanders if both have partner.)

    — Partner and the combat-trigger pump are already parser-`MODELED`
    (`gate.parse_oracle` claims both; copied verbatim here rather than
    re-derived, per the hand-author-card skill's own guidance) — hand-
    authoring is only needed at all because of the third ability's "target
    land you control becomes a 1/1 … creature … It's still a land" shape
    (MEC-12), which no prior card had needed: RULE 611's `GrantUntilEffect`
    already covers "until end of turn", and `targeting.py` already has
    ``land_you_control``, but nothing had chained *two* `grant_until`
    statics onto the *same* resolve-time target before. Built as two
    ordinary `grant_until` `EffectSpec`s in one effect list — the first
    targets the land and stamps a `type_change` (``add_types=["creature"]``,
    literal 1/1), the second reuses `GameContext.previous_targets` via
    `GrantUntilEffect`'s own existing ``previous_subject`` pronoun (the
    same "Tap target land. It doesn't untap …" idiom `_apply_effects_
    partitioned` already threads through any effect exposing `target_specs`)
    to lay a `grant_keyword` static onto that exact land without
    re-targeting — no new engine primitive, just the first card to combine
    two already-shipped ones this way. "It's still a land" needs no code:
    `type_change`'s ``add_types`` only *adds* the creature type, never
    removing land — though it did surface a real, general bug fixed
    alongside this card: see Ashaya, Soul of the Wild's own entry just
    below for the `GameObject.is_land` fix that direction depends on too.
    """
    return [
        AbilitySpec(
            "keyword", [], keyword={"name": "partner"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "power": 3, "toughness": 3, "keywords": ["trample"],
                "selector": "creatures_you_control",
            })],
            trigger={
                "event": "STEP_BEGIN",
                "filter": {"step": "begin_combat"},
                "phase_relation": "you",
            },
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "power": 1, "toughness": 1,
                    }},
                    "duration": "end_of_turn", "target_kind": "land_you_control",
                }),
                EffectSpec("grant_until", {
                    "static": {"type": "grant_keyword", "params": {
                        "keywords": ["vigilance", "indestructible", "haste"],
                    }},
                    "duration": "end_of_turn", "target_kind": None,
                    "previous_subject": True,
                }),
            ],
            cost={"mana": "{1}{G}"},
        ),
    ]


register("Kamahl, Heart of Krosa", _kamahl_heart_of_krosa)


def _ashaya_soul_of_the_wild() -> list[AbilitySpec]:
    """Ashaya's power and toughness are each equal to the number of lands
    you control.
    Nontoken creatures you control are Forest lands in addition to their
    other types. (They're still affected by summoning sickness.)

    — Both clauses are genuinely new ground for the layer engine (MEC-12),
    not reachable by the oracle-text parser today. The first is RULE
    604.3's ordinary characteristic-defining P/T, built on `pt_cda`
    (registered in `effects.py` since an earlier batch but never bound by
    any card until now) reading the already-existing ``"lands_you_control"``
    `continuous.count_selector`. The second is the *reverse* direction of
    every other "X becomes a land" grant this engine has modeled so far — a
    creature gaining the land type, rather than a land gaining the creature
    type — which needed two things: `continuous.affected_objects`'s new
    ``"nontoken_creatures_you_control"`` scope (RULE 108.3's token filter
    applied to the ordinary controller-scoped creature set), and a real,
    general latent bug fix: `GameObject.is_land` had only ever read the
    printed card, never folding in a layer-4 `add_types` grant the way
    `is_creature` already does — so *no* card could ever have made
    something a land this way, regardless of phrasing. Fixed generally
    (mirrors `is_creature`'s own printed-or-added/removed pattern) rather
    than special-cased for this card; Kamahl, Heart of Krosa's own land-to-
    creature direction (this same batch) doesn't depend on it, since
    `is_creature` already had the fix, but any future "a land becomes a
    creature and loses land-ness" or "a creature becomes a land" card now
    reads correctly either way. Once `is_land` is fixed, the Forest subtype
    grant automatically reaches `mana_abilities._derived_basic_mana_
    options`'s existing RULE 305.6 "a land with a basic land type has that
    type's intrinsic mana ability" pass — so a creature Ashaya grants
    Forest to picks up "{T}: Add {G}." with no extra code — and equally
    automatically becomes a legal casualty of land destruction. The
    reminder text's "still affected by summoning sickness" needs no code:
    nothing about gaining an additional type touches `GameObject.
    summoning_sick`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("pt_cda", {
                "affects": "self",
                "power_count": "lands_you_control", "toughness_count": "lands_you_control",
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {
                "affects": "nontoken_creatures_you_control",
                "add_types": ["land"], "add_subtypes": ["Forest"],
            })],
        ),
    ]


register("Ashaya, Soul of the Wild", _ashaya_soul_of_the_wild)


def _yawgmoths_will() -> list[AbilitySpec]:
    """Until end of turn, you may play lands and cast spells from your
    graveyard.
    If a card would be put into your graveyard from anywhere this turn,
    exile that card instead.

    — Two new player-scoped, turn-limited primitives (MEC-12), neither
    expressible as a permanent-anchored static since the sorcery granting
    them is gone from every zone but graveyard/exile long before end of
    turn — there is no permanent left on the battlefield for the layer
    engine to scan. `GraveyardPlayPermissionThisTurnEffect` stamps
    `Player.graveyard_play_permission_until_turn`, read by
    `game/graveyard_cast.py`'s new `has_temporary_graveyard_play_
    permission` from both `GameEngine.can_play_land` (lands) and
    `_graveyard_cast_permission` (spells) — the first graveyard-cast
    permission source that has ever covered lands too, since Lurrus of the
    Dream-Den's own permanent-anchored grant explicitly excludes them.
    `GraveyardRedirectToExileEffect` stamps `Player.graveyard_redirect_
    to_exile_until_turn`, checked directly in `RulesEngine.
    _move_to_graveyard` — the one choke point every graveyard-bound move
    funnels through regardless of cause — against whichever player *owns*
    the moving card, since a card only ever enters its own owner's
    graveyard (RULE 404.4/700.4), the player-scoped, whole-turn sibling of
    the existing per-*object* `cast_via_graveyard_cast_permission_until_
    turn` check (Lurrus's own trailing "exile instead" clause) already
    sitting right above it. Together: anything cast/played this way that
    would otherwise die/be discarded/be countered this same turn is exiled
    instead of returning to the graveyard for a second recursion — the
    actual point of the card.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("graveyard_play_permission_this_turn", {}),
                EffectSpec("graveyard_redirect_to_exile_this_turn", {}),
            ],
        ),
    ]


register("Yawgmoth's Will", _yawgmoths_will)


def _protean_hulk() -> list[AbilitySpec]:
    """When this creature dies, search your library for any number of
    creature cards with total mana value 6 or less, put them onto the
    battlefield, then shuffle.

    — Needed a genuinely new `SearchLibraryEffect` primitive (MEC-12):
    every existing multi-pick search bounds each round by a fixed
    per-card ``max_mana_value`` in ``criteria``, but this is a *running
    total* shared across the whole open-ended pick — a creature that costs
    5 and one that costs 1 are both individually well under 6, but picking
    both exhausts the budget for a third. `SearchLibraryEffect.total_mana_
    value_budget` (`RulesEngine._request_search`/`_search_choice`/
    `_resume_search`, all three threading a `spent_mana_value`
    running total through the recursive multi-round loop) narrows each
    round's own eligible pool to whatever still fits the *remaining*
    budget, on top of `criteria`'s ordinary type filter — orthogonal to,
    and reusable alongside, a real per-card cap should some future card
    need both at once. "Any number" reuses the already-established
    ``count=99`` sentinel other open-ended searches use, since the real
    stopping condition here is the budget running out, not the count.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"}, "destination": "battlefield",
                "count": 99, "optional": True, "total_mana_value_budget": 6,
            })],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
        ),
    ]


register("Protean Hulk", _protean_hulk)


def _helm_of_the_host() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, create a token that's a
    copy of equipped creature, except the token isn't legendary. That
    token gains haste.
    Equip {5}

    — Equip is synthesized by the keyword catalogue; the triggered ability
    itself needed no new primitive at all (MEC-12). `CopyPermanentEffect`
    already supports ``target_kind="attached_permanent"`` (Mirrormind
    Crown's own "copies of equipped creature"), ``not_legendary``
    (Multiversal Recruitment-shaped), and ``haste`` (Kiki-Jiki, Mirror
    Breaker-shaped) — Helm of the Host is simply the first card combining
    exactly these three already-shipped params on one effect.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {
                "target_kind": "attached_permanent", "not_legendary": True, "haste": True,
            })],
            trigger={
                "event": "STEP_BEGIN",
                "filter": {"step": "begin_combat"},
                "phase_relation": "you",
            },
        ),
    ]


register("Helm of the Host", _helm_of_the_host)


def _twinflame() -> list[AbilitySpec]:
    """Strive — This spell costs {2}{R} more to cast for each target
    beyond the first.
    Choose any number of target creatures you control. For each of them,
    create a token that's a copy of that creature, except it has haste.
    Exile those tokens at the beginning of the next end step.

    — Strive itself is an already-shipped primitive (`AbilitySpec.
    strive_cost`, `GameEngine`'s per-extra-target cost scaling); the real
    gap was `CopyPermanentEffect` only ever copying its *first* target,
    even when RULE 115.1a's own "any number of target creatures" widens
    the target count past one (MEC-12). Widened with a genuinely new
    ``target_count``/``target_count_max``/``target_optional`` param triple
    (deliberately distinct from the existing ``count``, which still means
    "N copies of the (one) target" — Rite of Replication-shaped, and could
    combine with this on some future card): when the target spec's own
    ``effective_count != 1``, `apply()` now makes one token copy *per*
    chosen target instead of ``count`` copies of just the first, mirroring
    the established `PumpEffect`/`AddCountersEffect` "each of up to N gets
    the full amount" idiom. "Any number of" reuses the parser's own
    ``_ANY_NUMBER_TARGET_CAP`` (10) sentinel. The delayed exile needed one
    small new primitive: `ExileSpecificEffect`, the plural sibling of
    `SacrificeSpecificEffect` (Kiki-Jiki-shaped) — the existing
    `CreateDelayedTriggerEffect`'s ``capture="created_objects"`` branch
    already special-cased any inner effect exposing a plain ``.objects``
    list, but `ExileEffect` only ever carries one ``.target``, silently
    dropping every token past the first for a multi-target source like
    this one.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": "creature_you_control", "target_count": 10,
                    "target_optional": True, "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "exile_specific", "params": {}}],
                }),
            ],
            strive_cost="{2}{R}",
        ),
    ]


register("Twinflame", _twinflame)


def _heat_shimmer() -> list[AbilitySpec]:
    """Create a token that's a copy of target creature, except it has
    haste and "At the beginning of the end step, exile this token."

    — The single-target sibling of Twinflame's own delayed-exile shape
    (MEC-12, this same batch): rather than literally granting a quoted
    triggered ability onto the freshly-made token (a real but heavier
    mechanism this engine already avoids for exactly this template — see
    Kiki-Jiki/Puppeteer Clique's own "create/reanimate with haste,
    [sacrifice/exile] it at the beginning of the next end step" primitive
    in `Done_Backend.md`'s Marchesa V4.2 entry), the caster-side
    `create_delayed_trigger`/`exile_specific` pair reaches the identical
    board outcome — the token is gone at the next end step regardless of
    which player controls it. Target is any creature (not "you control"),
    unlike Twinflame — `CopyPermanentEffect`'s plain ``"creature"``
    ``target_kind`` default already matches.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("copy_permanent", {"target_kind": "creature", "haste": True}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "exile_specific", "params": {}}],
                }),
            ],
        ),
    ]


register("Heat Shimmer", _heat_shimmer)


def _necrotic_ooze() -> list[AbilitySpec]:
    """As long as this creature is on the battlefield, it has all
    activated abilities of all creature cards in all graveyards.

    — The third ``source_mode`` for `grant_borrowed_activated_ability`
    (MEC-12, alongside MEC-21/MEC-26's ``exiled_with``/``group``/
    ``chosen_permanent``): ``"all_graveyards"`` reads straight off every
    player's live `Player.graveyard` list rather than a single donor or a
    battlefield selector — the "in all graveyards" scope this card is
    actually named for. `continuous._apply_borrowed_activated_abilities`'s
    existing per-(grantee, donor, ability-index) caching, RULE 113.7c
    source-redirect, and creature-only donor filter are all reused as-is;
    "as long as this creature is on the battlefield" needs no `active_if`
    gate — a static ability only ever applies while its own source is on
    the battlefield in the first place (RULE 613.1).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self",
                "source_mode": "all_graveyards",
            })],
        ),
    ]


register("Necrotic Ooze", _necrotic_ooze)


def _alms_collector() -> list[AbilitySpec]:
    """Flash
    If an opponent would draw two or more cards, instead you and that
    player each draw a card.

    — MEC-32. Flash is the ordinary keyword fold-in. The draw-replacement
    clause needed a genuinely new primitive: no per-card `DRAW` event can
    see "the whole attempted instruction was for 2+ cards" (each card in a
    multi-draw is independently replaceable per RULE 120.3), so
    `RulesEngine.draw` was restructured to fire one `EventType.DRAW_
    INSTRUCTION` event for the whole call before splitting into per-card
    `DRAW` events — see that event's own docstring and `effects.
    _split_multi_draw_replacement`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("split_multi_draw", {"min_count": 2})],
        ),
    ]


register("Alms Collector", _alms_collector)


def _notion_thief() -> list[AbilitySpec]:
    """Flash
    If an opponent would draw a card except the first one they draw in
    each of their draw steps, instead that player skips that draw and you
    draw a card.

    — MEC-32. Flash is the ordinary keyword fold-in. The exemption clause
    ("except the first one … in each of their draw steps") needed a new
    `GameState.first_draw_done_this_step` per-player tracker, reset right
    as a player's own draw step begins (`game/engine/turn_loop_mixin.py`'s
    `_run_step`) — distinct from the existing whole-turn `cards_drawn_
    this_turn`, since a draw from a spell earlier in the same turn must
    not count as the step's own first draw. See `effects.
    _steal_non_first_draw_replacement`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("steal_non_first_draw", {})],
        ),
    ]


register("Notion Thief", _notion_thief)


def _chains_of_mephistopheles() -> list[AbilitySpec]:
    """If a player would draw a card except the first one they draw in
    each of their draw steps, that player discards a card instead. If the
    player discards a card this way, they draw a card. If the player
    doesn't discard a card this way, they mill a card.

    — MEC-32. The same ``first_in_draw_step`` exemption Notion Thief's
    entry above reads, but table-wide (no opponent/you scoping) and its
    own three-branch discard/draw/mill body, genuinely bespoke enough to
    need its own replacement type rather than a combination of existing
    ones — see `effects._discard_instead_of_non_first_draw_replacement`
    for the full RULE 616.1f recursive-termination reasoning (each
    replaced draw's own compensating draw can itself be replaced again,
    strictly shrinking the affected player's hand each time, until it's
    empty and the mill branch fires instead).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("discard_instead_of_non_first_draw", {})],
        ),
    ]


register("Chains of Mephistopheles", _chains_of_mephistopheles)


def _animate_dead() -> list[AbilitySpec]:
    """Enchant creature card in a graveyard
    When this Aura enters, if it's on the battlefield, it loses "enchant
    creature card in a graveyard" and gains "enchant creature put onto the
    battlefield with this Aura." Return enchanted creature card to the
    battlefield under your control and attach this Aura to it. When this
    Aura leaves the battlefield, that creature's controller sacrifices it.
    Enchanted creature gets -1/-0.

    — MEC-34, RULE 303.4f's reanimator-Aura template: the Aura's own cast
    target is a graveyard *card*, not a battlefield permanent, so it can't
    attach the ordinary way as it resolves. Needed three pieces, none of
    them previously reachable by any shipped card: (1) `RulesEngine.
    _resolve_permanent_spell` recognizes a graveyard-zone attach target
    and leaves the Aura on the battlefield unattached instead of sending
    it to the graveyard for the "failed" attach, stashing the target on
    the new `GameObject.reanimate_target_id`; (2) `targeting.legal_
    targets` gained a graveyard-wide branch for an "Enchant `<type>` card
    in a graveyard" quality, since the existing "enchant" branch only ever
    searched the battlefield; (3) the ETB ability itself —
    `ReturnFromGraveyardEffect`'s new ``target_kind="self_enchant_
    target"`` reads that stashed id back (rather than a fresh RULE 115
    target) to reanimate the right card under this Aura's controller, then
    the already-shipped `AttachEffect(target_kind="created")` attaches
    this Aura to whatever `ReturnFromGraveyardEffect` just put onto the
    battlefield. The "when this Aura leaves the battlefield, sacrifice
    it" clause is the new `SacrificeAttachedPermanentEffect` (reads
    `attached_to` live, since `GameState.remove_from_battlefield` never
    clears it). The self-referential "it loses/gains" text-change clause
    is RULE 303.4f reminder text describing exactly this behavior with no
    separate gameplay effect — not modeled as its own clause. RULE 704.5n's
    "Aura attached to nothing → owner's graveyard" SBA sweep never
    interferes: it only ever revalidates a permanent whose `attached_to`
    is already set, so the brief window where this Aura is on the
    battlefield but not yet attached is naturally safe.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "self_enchant_target",
                    "under_your_control": True,
                }),
                EffectSpec("attach", {"target_kind": "created"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_attached_permanent", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": -1, "toughness": 0})],
        ),
    ]


register("Animate Dead", _animate_dead)


def _damping_sphere() -> list[AbilitySpec]:
    """If a land is tapped for two or more mana, it produces {C} instead of
    any other type and amount.
    Each spell a player casts costs {1} more to cast for each other spell
    that player has cast this turn.

    — MEC-36. Two independent unscoped statics, neither previously
    reachable. The first is a new `StaticAbility` layer,
    `"mana_type_override"`, consulted directly by `GameEngine.
    tap_for_mana` (`continuous.mana_type_override_for`) right alongside
    the already-shipped `mana_multiplier` (Nyxbloom Ancient) — a boolean
    override on the *true*, post-multiplier produced total, not a layer-6
    ability grant. The second is `cost_reduction`'s existing `per`
    count-selector vocabulary widened with a new `"spells_cast_this_turn"`
    key: `continuous._cost_static_amount` already evaluates `per` against
    the *casting* player (not this static's own controller), and
    `RulesEngine._track_spell_cast` increments `GameState.spells_cast_
    this_turn` strictly after cost is computed for the spell just cast —
    so "for each other spell" falls out for free with no off-by-one
    correction needed. That field's own reset had to widen from
    "just the incoming active player" (its original RULE 731.2-only
    scope) to every player, every turn, since a non-active player's own
    running total needs to stay accurate too.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("mana_type_override", {"min_amount": 2, "to": "C"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "all_spells",
                "generic": 1,
                "increase": True,
                "per": "spells_cast_this_turn",
            })],
        ),
    ]


register("Damping Sphere", _damping_sphere)


def _doomsday() -> list[AbilitySpec]:
    """Search your library and graveyard for five cards and exile the
    rest. Put the chosen cards on top of your library in any order. You
    lose half your life, rounded up.

    — MEC-37. The original ticket framing ("exile up to five cards in a
    pile") turned out to describe a mechanic Doomsday doesn't actually
    have — its real printed text needed no new search primitive at all,
    only a re-check against the real oracle text: `SearchLibraryEffect`
    already supports `zones=["library", "graveyard"]` (combined-zone
    search), `exile_rest` (its own docstring already says
    "…Doomsday-shaped", built with this exact card in mind but never
    reached before now), and `destination="library_top"` — and since a
    multi-card `library_top` search already offers its picks one at a
    time and stacks each new pick *above* the last, the player already
    has full control over the final order simply by choosing which card
    to name each round (name the card that should be drawn last first,
    the one that should be drawn first last) — RULE 601.2c's "in any
    order" falls out for free. The only genuinely new piece is
    `LoseLifeEffect`'s new `amount_from_half_own_life` param — "half your
    life, rounded up" (RULE 107.3) — reading this ability's own controller
    at resolution.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": "",
                    "destination": "library_top",
                    "count": 5,
                    "optional": False,
                    "zones": ["library", "graveyard"],
                    "exile_rest": True,
                }),
                EffectSpec("lose_life", {"amount_from_half_own_life": True}),
            ],
        ),
    ]


register("Doomsday", _doomsday)


def _necropotence() -> list[AbilitySpec]:
    """Skip your draw step.
    Whenever you discard a card, exile that card from your graveyard.
    Pay 1 life: Exile the top card of your library face down. Put that
    card into your hand at the beginning of your next end step.

    — MEC-38. Three real pieces, none previously reachable: (1) "Skip
    your draw step" is a new `StaticAbility` layer, `"skip_step"` —
    `RulesEngine.should_skip_step` already existed but had never had a
    real card wired to it (its own `Player.player_effects`/`StaticEffect`
    path is a designed-but-never-instantiated primitive; this uses a live
    battlefield read instead, `continuous.skipped_steps_for`, the same
    "no separate enter/leave lifecycle to build" shape `mana_type_
    override`/MEC-36 already established). (2) The discard trigger needed
    a new per-card `EventType.DISCARD_CARD` (the existing `DISCARD` only
    ever carried an aggregate `count`, the same granularity gap MEC-32
    found on the draw side — `RulesEngine.discard`/`discard_specific`/RULE
    614.12's "discard a land instead" now all fire it) plus `ExileEffect`'s
    new `target_kind="trigger_subject"` (mirroring `TapEffect`'s own),
    reading the discarded card's `instance_id` straight off the firing
    event rather than a chosen target — by the time this resolves the
    card is already sitting in the graveyard (discard moves it there
    before firing), so this is a real zone change into exile. (3) The
    activation cost is the already-shipped `ActivationCost.pay_life`; the
    effect needed a new `ExileTopOfLibraryEffect` (deterministic top-card
    exile, unlike `SearchLibraryEffect`'s real choice among the whole
    zone even at `count=1`) feeding `CreateDelayedTriggerEffect`'s
    existing `capture="created_objects"`, widened with a third captured
    attribute name (`exiled_object`, alongside the pre-existing `objects`/
    `target`) so the delayed half can reuse `ReturnUncastExiledEffect`
    unchanged — previously only ever constructed directly in Python
    (Beseech the Mirror/Rebound's own "if it wasn't cast this way" tail),
    never reachable through the `EffectSpec` whitelist until this card
    needed it as an ordinary delayed effect rather than a bespoke one.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("skip_step", {"step": "draw"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "trigger_subject"})],
            trigger={"event": "DISCARD_CARD", "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile_top_of_library", {"face_down": True}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [
                        {"type": "return_uncast_exiled", "params": {"destination": "hand"}}
                    ],
                }),
            ],
            cost={"text": "Pay 1 life"},
        ),
    ]


register("Necropotence", _necropotence)


def _opposition_agent() -> list[AbilitySpec]:
    """Flash
    You control your opponents while they're searching their libraries.
    While an opponent is searching their library, they exile each card
    they find. You may play those cards for as long as they remain
    exiled, and you may spend mana as though it were mana of any color to
    cast them.

    — MEC-39. Flash is the ordinary keyword fold-in. The "you control
    your opponents while searching" clause is deliberately not modeled as
    a genuine RULE 269.4 control exchange of the player — this engine's
    search flow has no other decision point during a search a real
    control swap would change (the searching player still picks which
    cards they find; only where those cards end up is redirected), so
    the second, fully mechanical paragraph already describes the whole
    gameplay outcome. `RulesEngine._finish_search` now consults a new
    `StaticAbility` layer, `"search_redirect"` (`continuous.search_
    redirect_controller_for`), right where it computes each found card's
    destination: an opponent's search has *every* found card's
    destination overridden to exile, and the already-shipped `GameState.
    exile_cast_condition`/`mana_wildcard_permission` pair (every other
    "play a card from exile" mechanism already uses these) is granted to
    this permanent's controller rather than the found card's own owner —
    the one genuine generalization needed, since every existing grantor
    of those two maps had only ever pointed them at the exiled card's own
    owner.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("search_redirect", {})],
        ),
    ]


register("Opposition Agent", _opposition_agent)


def _leonin_arbiter() -> list[AbilitySpec]:
    """Players can't search libraries. Any player may pay {2} for that
    player to ignore this effect until end of turn.

    — MEC-35. Two pieces. (1) The already-shipped `grant_search_
    prohibited` (Stranglehold's own effect type) gained a new `scope`
    param: `"opponents"` (the pre-existing default, matching Stranglehold's
    "**your opponents** can't…") vs. `"all"` (this card's own unqualified
    "**Players** can't…", which also restricts its own controller). (2)
    "Any player may pay {2}… to ignore this effect until end of turn" is a
    genuine RULE 116.2a special action — no stack, no timing restriction,
    repeatable (paying twice just wastes {2}, same as the real card) —
    `GameEngine.pay_search_exemption`/`pay_search_exemption_actions`,
    mirroring `turn_face_up`'s own established "offered only when payable,
    reclaims priority for its taker" shape exactly. `GameState.search_
    exempt_until_turn` is the same "stops matching once the turn advances,
    no cleanup bookkeeping needed" idiom `temp_flash_until_turn` already
    uses. The exemption is read as "ignore every current search
    prohibition," not just this one specific effect (the printed wording
    says "this effect") — no shipped card yet combines Leonin Arbiter with
    a second, independent prohibition source, so the simpler reading costs
    nothing today; narrow it if that ever changes.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_search_prohibited", {"scope": "all"})],
        ),
    ]


register("Leonin Arbiter", _leonin_arbiter)


def _return_the_favor() -> list[AbilitySpec]:
    """Spree (Choose one or more additional costs.)
    + {1} — Copy target instant spell, sorcery spell, activated ability, or
    triggered ability. You may choose new targets for the copy.
    + {1} — Change the target of target spell or ability with a single
    target.

    — MEC-31, the ticket's own named card (`Ojer cEDH`). RULE 702.172a
    Spree — a genuine new modal shape, not RULE 700.2's "choose N or more"
    with a shared cost: every mode prices *itself*
    (`AbilitySpec.modes["mode_costs"]`, one raw mana-cost string per
    option, parallel to ``options``/``descriptions`` — the parser's own
    `catalogue/modal.split_spree_block` builds the same dict for a
    cache-wide Spree card; this one is hand-authored only for its first
    mode's effect body, not its modal shape). `effect_binder._build_mode_
    entries` folds ``mode_costs[i]`` onto ``spell_modes[i]["cost"]``;
    `GameEngine._modal_extra_cost` sums the chosen combination's own costs
    on top of the printed {R}{R}, consulted by `effective_cast_cost`/
    `can_cast`/`_auto_tap_for_cast_if_needed` and surfaced per legal-action
    combination by `_modal_cast_actions`/`_cast_action` (each combination
    locks independently when its own total isn't affordable).

    The second mode ("change the target…") is exactly the parser's own
    already-built `_change_target` handler output — `EffectSpec
    ("change_target", {"spell_or_ability": True})`, ENG-26's union
    spell-or-ability stack-item lookup, unchanged.

    The first mode ("copy target … spell, activated ability, or triggered
    ability … choose new targets") is hand-authored with the same two
    simplifications every other targeted-copy catalogue entry already
    carries (Reiterate/Narset's Reversal/Dualcaster Mage) —
    `CopySpellEffect`'s own docstring names both: it only targets a real
    spell (`TargetSpec(kind="spell")`, RULE 707.10's copiable-object rule
    still applies fine to instants/sorceries but `RulesEngine.copy_spell`
    has no path for an *ability* StackItem at all, whose `obj` is always
    `None` — a real, separate primitive this card doesn't need to build to
    become playable, tracked as its own future gap rather than silently
    modeled here), and it keeps the original's targets rather than opening
    an interactive "choose new targets" pick (`copy_spell`'s own
    `new_targets` param exists but no caller wires an interactive choice to
    it yet). Both match every real card sharing this template today.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "at_least": True,
                "mode_costs": ["{1}", "{1}"],
                "options": [
                    [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
                    [EffectSpec("change_target", {"spell_or_ability": True})],
                ],
                "descriptions": [
                    "Copy target instant spell, sorcery spell, activated ability, "
                    "or triggered ability. You may choose new targets for the copy.",
                    "Change the target of target spell or ability with a single target.",
                ],
            },
        ),
    ]


register("Return the Favor", _return_the_favor)


def _omen_machine() -> list[AbilitySpec]:
    """Players can't draw cards.
    At the beginning of each player's draw step, that player exiles the
    top card of their library. If it's a land card, the player puts it
    onto the battlefield. Otherwise, the player casts it without paying
    its mana cost if able.

    — MEC-33. Two independent pieces, neither needing a genuinely new
    engine mechanism once diagnosed against what already exists. (1) "Players
    can't draw cards" is just RULE 121.5-adjacent `draw_limit`
    (`continuous.max_draws_per_turn`, already built for Spirit of the
    Labyrinth/Narset, Parter of Veils) at `max_per_turn=0` with its
    already-default `affects="all"` — a flat cap of zero *is* an outright
    ban, no new code at all, just a value the primitive had never been
    asked for before. (2) The replacement action is a `STEP_BEGIN`
    trigger on the "draw" step with no `phase_relation` at all (RULE
    500.7 — since only the active player ever has a draw step, an
    unscoped "at the beginning of the draw step" trigger fires exactly
    once per turn, for whoever that is — the same "each player's step"
    shape a `phase_relation` of "you"/"not_you" would otherwise narrow,
    just left unnarrowed here) chaining `ExileTopOfLibraryEffect`'s new
    `player_selector="active_player"` (mirroring `DealDamageEffect`'s own
    `"active_player"` selector, the established "no subject of its own,
    read live off `GameState.active_player`" idiom — Roiling Vortex-
    shaped) into the new `LandOrFreeCastEffect`, which reads whatever
    `ExileTopOfLibraryEffect` just exiled (`GameContext.created_objects`)
    and either puts a land onto the battlefield or attempts a free cast
    "if able" (RULE 601.2c — no legal target, and it just stays exiled;
    the printed text names no other fallback). The same tail also prints
    on Wild Evocation (off a *revealed random hand card* instead of an
    exiled library card), confirming `LandOrFreeCastEffect` is a real
    two-card shared primitive worth building generally rather than a
    one-off tied to how the card got there.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("draw_limit", {"max_per_turn": 0})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_top_of_library", {"player_selector": "active_player"}),
                EffectSpec("land_or_free_cast", {"player_selector": "active_player"}),
            ],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "draw"}},
        ),
    ]


register("Omen Machine", _omen_machine)


def _necromancy() -> list[AbilitySpec]:
    """You may cast this spell as though it had flash. If you cast it any
    time a sorcery couldn't have been cast, the controller of the
    permanent it becomes sacrifices it at the beginning of the next
    cleanup step.
    When this enchantment enters, if it's on the battlefield, it becomes
    an Aura with "enchant creature put onto the battlefield with
    Necromancy." Put target creature card from a graveyard onto the
    battlefield under your control and attach this enchantment to it.
    When this enchantment leaves the battlefield, that creature's
    controller sacrifices it.

    — MEC-44, RULE 303.4f's *non-Aura* reanimator template (Animate Dead's
    own sibling ticket, MEC-34 — that card is a real Aura from load time;
    this one prints as a plain Enchantment and only becomes an Aura once
    it resolves). Three real gaps closed, none needing as much new
    machinery as first diagnosed. (1) The unconditional flash grant needed
    only a trivially-true `conditional_flash={"unconditional": True}`
    key (`ALLOWED_CAST_CONDITION_KEYS`/`condition_query.
    conditional_flash_holds`), since every prior key gated on something.
    (2) "If cast at a time a sorcery couldn't have been cast, sacrifice at
    next cleanup" needed a new `GameObject.cast_outside_sorcery_speed`
    flag, stamped once at cast time (`GameEngine._cast_current_face`,
    since the board — and so the answer — has moved on by the time this
    resolves) and read by a new `EffectSpec.condition` key of the same
    name gating a `create_delayed_trigger`/`sacrifice_self` pair — no new
    delayed-trigger primitive at all: `CreateDelayedTriggerEffect`'s
    existing `step`/`scope` params already cover "at the beginning of the
    next cleanup step" (RULE 514), and `sacrifice_self` already exists
    (Dress Down/Underworld Breach). (3) "It becomes an Aura with
    '`<quoted text>`'" — the ticket's own flagged "real blocker" — turned
    out to need far less than fresh threading through every
    `_attachment_kind`/`_attachment_legal`/`_detach_attachments_from`
    reader: all three already read `GameObject.parametric_keywords` fresh
    off the live object every call, never a load-time snapshot, so the
    new `BecomeAuraEffect` just writes `parametric_keywords["enchant"]`
    directly and every reader picks it up for free.

    Reuses Animate Dead's own `ReturnFromGraveyardEffect`/`AttachEffect
    (target_kind="created")`/`SacrificeAttachedPermanentEffect` wholesale,
    but with a genuine RULE 115 target on the *reanimate* clause itself
    (`target_kind="any_graveyard_creature"` — "**a** graveyard", any
    player's, unlike Animate Dead's own printed-on-the-Aura target)
    rather than Animate Dead's stashed-at-cast-time shape, since Necromancy
    carries no "Enchant" line at cast time at all for `_resolve_permanent_
    spell`'s graveyard-attach recognition to key off — its target is
    chosen when the *triggered ability* resolves instead. **Documented
    simplification**, matching Animate Dead's own: the "it loses/gains"
    self-referential quality-text-change isn't modeled as its own clause
    (RULE 303.4f reminder text describing exactly this behavior, no
    separate gameplay effect) — `BecomeAuraEffect`'s `quality="creature"`
    default is close enough that `_attachment_legal`'s permissive fallback
    (any quality string it doesn't recognize matches everything) covers it
    regardless.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("become_aura", {"quality": "creature"}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "any_graveyard_creature",
                    "under_your_control": True,
                }),
                EffectSpec("attach", {"target_kind": "created"}),
                EffectSpec(
                    "create_delayed_trigger",
                    {
                        "step": "cleanup", "scope": "controller",
                        "effects": [{"type": "sacrifice_self", "params": {}}],
                        "description": "Necromancy: am Anfang des nächsten "
                                        "Aufräumschritts opfern",
                    },
                    condition={"cast_outside_sorcery_speed": True},
                ),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            conditional_flash={"unconditional": True},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_attached_permanent", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Necromancy", _necromancy)


# ---------------------------------------------------------------------------
# MEC-40: cEDH Rocco / cEDH staples remaining gaps (batch 1)
# ---------------------------------------------------------------------------


def _culling_ritual() -> list[AbilitySpec]:
    """Culling Ritual (Sorcery, {2}{B}{G})

    "Destroy each nonland permanent with mana value 2 or less. Add {B} or
    {G} for each permanent destroyed this way."

    The destroy half is a plain parser-claimable mass wipe on its own
    (`_MASS_DESTROY_NOUNS_SINGULAR`'s new "nonland permanent" entry) —
    hand-authored here only because the mana rider needs a same-resolution
    accumulator (`GameContext.permanents_destroyed_this_way`, mirroring the
    existing `life_lost_this_way`) the parser has no vocabulary for yet.

    **Documented simplification**: the real card lets you split the
    produced mana between {B} and {G} independently, mana by mana (RULE
    106.1); `AddManaEffect.any_color_choices` offers one colour choice for
    the *whole* amount instead (see its own docstring for why) — no
    per-unit "how many of each" interactive shape exists yet. Still fully
    usable colored mana, just less flexible than printed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec(
                    "destroy",
                    {"selector": "all_nonland_permanents", "filter": {"max_mana_value": 2}},
                ),
                EffectSpec(
                    "add_mana",
                    {
                        "colors": ["ANY"],
                        "any_color_choices": ["B", "G"],
                        "any_amount_from_context": "permanents_destroyed_this_way",
                    },
                ),
            ],
        ),
    ]


register("Culling Ritual", _culling_ritual)


def _cabal_ritual() -> list[AbilitySpec]:
    """Cabal Ritual (Instant, {1}{B})

    "Add {B}{B}{B}.
    Threshold — Add {B}{B}{B}{B}{B} instead if there are seven or more
    cards in your graveyard."

    Modeled as a flat 3 B plus a *conditional extra 2 B* rather than a true
    "instead" override — mathematically identical (5 = 3 + 2) and avoids
    needing the general, still-unbuilt "if kicked, `<effect>` instead"
    override primitive (CLAUDE.md's Notable Gaps) for what is, arithmetically,
    an additive bonus. `EffectSpec.condition`'s new `cards_in_graveyard_at_
    least` key (RULE 702.19 Threshold's own gate) is a plain graveyard-size
    read, reusable by any future Threshold card with the same "Add X
    instead" phrasing.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("add_mana", {"colors": ["B", "B", "B"]}),
                EffectSpec(
                    "add_mana", {"colors": ["B", "B"]},
                    condition={"cards_in_graveyard_at_least": 7},
                ),
            ],
        ),
    ]


register("Cabal Ritual", _cabal_ritual)


def _ranger_captain_of_eos() -> list[AbilitySpec]:
    """Ranger-Captain of Eos (Creature — Human Soldier Ranger, {1}{W}{W})

    "When this creature enters, you may search your library for a creature
    card with mana value 1 or less, reveal it, put it into your hand, then
    shuffle.
    Sacrifice this creature: Your opponents can't cast noncreature spells
    this turn."

    The ETB is already parser-claimable as-is (`author_card.py reuse`
    confirms it); hand-authored only because the sacrifice ability's own
    "this turn" duration needs `GrantUntilEffect` to wrap the standing
    `cast_prohibition` static (Gaddock Teeg-shaped) instead of a
    permanent's own always-on line — `target_kind=None` since the
    prohibition is scoped by the static's own ``scope="opponents"``
    (read off the ability's ``source``, i.e. this card, which survives
    being sacrificed since `GameEffect.source` keeps its object reference
    regardless of zone), not by a chosen target.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "search",
                    {"criteria": {"type": "creature", "max_mana_value": 1}, "destination": "hand"},
                )
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            optional=True,
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "grant_until",
                    {
                        "static": {
                            "type": "cast_prohibition",
                            "params": {"scope": "opponents", "noncreature": True},
                        },
                        "duration": "end_of_turn",
                        "target_kind": None,
                    },
                )
            ],
            cost={"text": "Sacrifice ~"},
        ),
    ]


register("Ranger-Captain of Eos", _ranger_captain_of_eos)


def _vexing_shusher() -> list[AbilitySpec]:
    """Vexing Shusher (Creature — Goblin Shaman, {1}{R})

    "This spell can't be countered.
    {R/G}: Target spell can't be countered."

    The static is already parser-claimable as-is; hand-authored only for
    the activated ability, which is `MarkCantBeCounteredEffect`'s existing
    resolve-time marker (built for Mistrise Village's untargeted "next
    spell you cast") widened with a real `target_kind="spell"` RULE 115
    target instead.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("mark_cant_be_countered", {"target_kind": "spell"})],
            cost={"text": "{R/G}"},
        ),
    ]


register("Vexing Shusher", _vexing_shusher)


def _tinder_wall() -> list[AbilitySpec]:
    """Tinder Wall (Creature — Plant Wall, {G})

    "Defender (This creature can't attack.)
    Sacrifice this creature: Add {R}{R}.
    {R}, Sacrifice this creature: It deals 2 damage to target creature it's
    blocking."

    Defender and the plain sacrifice-for-mana ability are both already
    picked up independent of this registration (`parse_keywords`/
    `mana_abilities_for` scan the card's own oracle text directly, not
    gated by `ability_catalogue` registration) — hand-authored only for
    the damage ability, which needs the new `"creature_source_is_
    blocking"` target kind (`game/targeting.py`) no existing card had.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"target_kind": "creature_source_is_blocking", "amount": 2})],
            cost={"text": "{R}, Sacrifice ~"},
        ),
    ]


register("Tinder Wall", _tinder_wall)


# ---------------------------------------------------------------------------
# MEC-40: cEDH Rocco's remaining gaps, done to completion
# ---------------------------------------------------------------------------


def _academy_rector() -> list[AbilitySpec]:
    """Academy Rector (Creature — Human Cleric, {3}{W})

    "When this creature dies, you may exile it. If you do, search your
    library for an enchantment card, put that card onto the battlefield,
    then shuffle."

    The "you may X. If you do, Y." shape collapses to the ability's own
    `optional=True` (the same idiom Ranger-Captain of Eos's ETB and
    Necromancy's reanimate already use) since there's no *further*
    decision point between the exile and the search — declining the whole
    ability leaves Academy Rector undisturbed in the graveyard.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile", {"target_kind": None}),
                EffectSpec("search", {"criteria": {"type": "enchantment"}, "destination": "battlefield"}),
            ],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            optional=True,
        ),
    ]


register("Academy Rector", _academy_rector)


def _ajani_nacatl_pariah() -> list[AbilitySpec]:
    """Ajani, Nacatl Pariah // Ajani, Nacatl Avenger (Legendary Creature —
    Cat Warrior, {1}{W})

    "When Ajani enters, create a 2/1 white Cat Warrior creature token.
    Whenever one or more other Cats you control die, you may exile Ajani,
    then return him to the battlefield transformed under his owner's
    control."

    The ETB token is already parser-claimable as-is. The transform trigger
    reuses `ExileReturnTransformedEffect` (RULE 400.7/712.8, built for
    Ayara/Clive/Jin-Gitaxias) completely unchanged — untargeted and always
    self, exactly this shape. **Documented simplification**: a group DIES
    trigger fires once per dying Cat rather than once per simultaneous
    batch (RULE 603.3b's stricter "one or more" reading isn't modeled),
    self-limiting in practice since the first firing exiles Ajani, and
    every further firing that turn finds no source left to act on.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "create_token",
                    {"count": 1, "power": 2, "toughness": 1, "colors": ["W"],
                     "subtypes": ["Cat", "Warrior"], "keywords": [], "token_name": "Cat Warrior"},
                )
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_return_transformed", {})],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "controller": "you", "subtypes": ["cat"]},
            },
            optional=True,
        ),
    ]


register("Ajani, Nacatl Pariah", _ajani_nacatl_pariah)
