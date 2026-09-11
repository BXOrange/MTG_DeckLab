"""Competitive interaction, free spells, tutors, and disruption entries."""

from __future__ import annotations

from ...models.game.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

def _jeskas_will() -> list[AbilitySpec]:
    """Choose one. If you control a commander as you cast this spell, you
    may choose both instead.
    • Add {R} for each card in target opponent's hand.
    • Exile the top three cards of your library. You may play them this
    turn.

    — Imodane deck batch. Mode 1 needed a genuinely new `AddManaEffect`
    shape (``target_kind``/``amount_from_target_hand_size`` — every prior
    use of that effect was untargeted); mode 2 is `ImpulsiveDrawEffect`
    unchanged (``count=3, same_turn_only=True`` — Ragavan, Nimble
    Pilferer's own shorter "this turn" window rather than Light Up the
    Stage's "until your next turn"). **Documented simplification**:
    ``or_both`` is offered unconditionally rather than gated on "if you
    control a commander" — this app's decks are Commander decks by
    construction, so the gate is true in every real game this engine
    plays; a genuinely commander-less game would let this spell over-
    offer the combined mode.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "or_both": True,
                "options": [
                    [EffectSpec("add_mana", {
                        "color": "R", "target_kind": "opponent", "amount_from_target_hand_size": True,
                    })],
                    [EffectSpec("impulsive_draw", {"count": 3, "same_turn_only": True})],
                ],
                "descriptions": [
                    "Füge {R} für jede Karte auf der Hand eines Zielgegners hinzu.",
                    "Exiliere die obersten drei Karten deiner Bibliothek. Du "
                    "kannst sie in diesem Zug ausspielen.",
                ],
            },
        ),
    ]


register("Jeska's Will", _jeskas_will)


def _play_with_fire() -> list[AbilitySpec]:
    """Play with Fire deals 2 damage to any target. If a player is dealt
    damage this way, scry 1.

    — Imodane deck batch. The scry rider is `ConditionalEffect`'s new
    ``target_is_player`` condition key (this batch, shares its shared-
    targets-list idiom with the existing ``target_is_controller``), same
    shape as Trystan's ``graveyard_has_type``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 2, "target_kind": "any"}),
                EffectSpec("scry", {"amount": 1}, condition={"target_is_player": True}),
            ],
        ),
    ]


register("Play with Fire", _play_with_fire)


def _vandalblast() -> list[AbilitySpec]:
    """Destroy target artifact you don't control.
    Overload {4}{R} (You may cast this spell for its overload cost. If
    you do, change "target" in its text to "each.")

    — Imodane deck batch. The base mode needed a new `artifact_you_dont_
    control` target kind, the artifact-typed mirror of the existing
    `creature_you_dont_control`. **Documented simplification**: Overload
    (RULE 702.96) isn't modeled, matching the standing precedent Winds of
    Abandon/Damn/Cyclonic Rift already set in this catalogue — no
    alternative-cost mechanism stamps "was this spell cast via its
    overload cost" anywhere yet.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "artifact_you_dont_control"})],
        ),
    ]


register("Vandalblast", _vandalblast)


def _witchs_mark() -> list[AbilitySpec]:
    """You may discard a card. If you do, draw two cards.
    Create a Wicked Role token attached to up to one target creature you
    control. (If you control another Role on it, put that one into the
    graveyard. Enchanted creature gets +1/+1. When this token is put
    into a graveyard, each opponent loses 1 life.)

    — Imodane deck batch. The loot half is `pay_cost_then` (RULE 118.3),
    the same "discard a card. If you do, …" shape Formidable Speaker's
    ETB already uses. **Documented simplification**: the Role token
    (RULE 701.62, an Aura-shaped token type this engine has no synthesis
    support for — `synthesize_token_card` only builds Creature/Artifact
    tokens, not Enchantment-Aura ones) isn't modeled; the card's real
    functional value (the loot) is fully modeled.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("pay_cost_then", {
                "cost": "Discard a card",
                "effects": [{"type": "draw", "params": {"count": 2}}],
            })],
        ),
    ]


register("Witch's Mark", _witchs_mark)


def _wheel_of_misfortune() -> list[AbilitySpec]:
    """Each player secretly chooses a number 0 or greater, then all
    players reveal those numbers simultaneously and determine the
    highest and lowest numbers revealed this way. Wheel of Misfortune
    deals damage equal to the highest number to each player who chose
    that number. Each player who didn't choose the lowest number
    discards their hand, then draws seven cards.

    — Imodane deck batch. **Documented simplification** (the whole card):
    no "secretly choose a number, then reveal simultaneously" primitive
    exists (a genuinely new interactive-choice subsystem, out of scope
    for the value of one card), so the highest/lowest voting sub-game and
    its damage aren't modeled at all. What's modeled instead is the
    card's Wheel-of-Fortune-shaped headline effect: every player
    discards their hand and draws seven — `DiscardEffect(count=99,
    scope="each_player")` is the same "count large enough to force the
    whole hand" idiom Fire Covenant's own ``count=10`` "any number" UI
    cap uses elsewhere, since `discard_choice` already forces without a
    prompt once ``count`` reaches hand size.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("discard", {"count": 99, "scope": "each_player"}),
                EffectSpec("draw", {"count": 7, "selector": "each_player"}),
            ],
        ),
    ]


register("Wheel of Misfortune", _wheel_of_misfortune)


def _volcanic_spite() -> list[AbilitySpec]:
    """Volcanic Spite deals 3 damage to target creature, planeswalker, or
    battle. You may put a card from your hand on the bottom of your
    library. If you do, draw a card.

    — Imodane deck batch. The target kind is the new `creature_
    planeswalker_or_battle`. The loot rider is the new `put_hand_card_on_
    bottom_then_draw` primitive (`RulesEngine.put_hand_card_on_bottom_
    then_draw`) — see its docstring for why the "may" is auto-taken
    rather than opening a real chooser.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 3, "target_kind": "creature_planeswalker_or_battle"}),
                EffectSpec("put_hand_card_on_bottom_then_draw", {}),
            ],
        ),
    ]


register("Volcanic Spite", _volcanic_spite)


def _imodane_the_pyrohammer() -> list[AbilitySpec]:
    """Whenever an instant or sorcery spell you control that targets only
    a single creature deals damage to that creature, Imodane deals that
    much damage to each opponent.

    — Imodane deck batch, the commander's own signature ability and this
    batch's biggest new-primitive investment: `DealDamageEffect.amount_
    from_trigger_event` (new — every other damage-doubling/mirroring
    card in this catalogue reads a count selector or a flat override, not
    a *firing event's own* damage amount) reads the DAMAGE event's
    ``amount`` field the trigger fired with. Two new event flags make the
    trigger condition possible at all: `RulesEngine.deal_damage`/
    `DealDamageEffect.apply` now stamp ``source_is_instant_or_sorcery``
    (the source's own printed card type) and ``source_targets_only_
    single_creature`` (computed from the *resolving effect's own*
    ``target_spec`` — count 1, not optional, not a mass selector — and
    the target's own `is_creature`) onto every DAMAGE event; two matching
    `effect_binder._trigger_condition` predicate keys
    (``requires_source_instant_or_sorcery``/``requires_single_creature_
    target``) check them. "You control" is the ordinary ``"subject":
    "group", "controller": "you"`` group-subject check (DAMAGE's group-
    controller key is already ``source_controller_id``).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "amount_from_trigger_event": "amount", "selector": "each_opponent",
            })],
            trigger={
                "event": "DAMAGE",
                "condition": {"subject": "group", "controller": "you"},
                "requires_source_instant_or_sorcery": True,
                "requires_single_creature_target": True,
            },
        ),
    ]


register("Imodane, the Pyrohammer", _imodane_the_pyrohammer)


# --- cEDH lists batch: RULE 118.9 "pitch" alternative-cost family -----------
#
# Force of Will/Negation/Vigor and Daze all print "You may <cost> rather
# than pay this spell's mana cost." — RULE 118.9, an alternative *casting*
# cost the engine doesn't model yet (see `_flare_of_duplication`'s own
# precedent for this same drop). Each card below is hand-authored for its
# *resolution effect only*, fully castable at its real printed mana cost
# (all four have one) — a strict subset of the real card, not a fake one.
# **Documented simplification, all four**: the free/discounted alternative
# cost is dropped; tracked as a real open primitive (RULE 118.9) in
# BACKLOG.md rather than silently rebuilt per card.


def _force_of_will() -> list[AbilitySpec]:
    """You may pay 1 life and exile a blue card from your hand rather than
    pay this spell's mana cost.
    Counter target spell.

    RULE 118.9's own alternative cost (MEC-15, previously dropped — see
    `Done_Backend.md`'s original cEDH batch entry for why it was deferred)
    now ships as a second `spell_effect` spec carrying only `alt_cost` and
    no effects of its own — `effect_binder.attach_to_object` scans every
    spec for it regardless of which one carries the "real" effects, the
    same idiom `additional_cost`/`free_cast_condition` already use. No
    condition: this alt cost is always available, unlike Force of
    Negation/Vigor's "if it's not your turn" gate below. Still also fully
    castable at its printed {3}{U}{U}.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {})],
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"pay_life": 1, "exile_hand_card_color": "U"},
        ),
    ]


register("Force of Will", _force_of_will)


def _force_of_negation() -> list[AbilitySpec]:
    """If it's not your turn, you may exile a blue card from your hand
    rather than pay this spell's mana cost.
    Counter target noncreature spell. If that spell is countered this way,
    exile it instead of putting it into its owner's graveyard.

    RULE 118.9's alternative cost now ships (MEC-15), gated by the
    `alt_cost` dict's own ``condition`` key (`ALLOWED_FREE_CAST_CONDITION_
    KEYS`'s ``not_your_turn`` — shared with `free_cast_condition`'s own
    vocabulary/evaluator, see `condition_query.free_cast_condition_holds`).

    **Documented simplification**: the "exile instead of graveyard" rider
    is still dropped (a real but narrow gap — the counter succeeds either
    way, only the destination zone differs). Still also fully castable at
    its printed {1}{U}{U}.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {"noncreature": True})],
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"exile_hand_card_color": "U", "condition": {"not_your_turn": True}},
        ),
    ]


register("Force of Negation", _force_of_negation)


def _force_of_vigor() -> list[AbilitySpec]:
    """If it's not your turn, you may exile a green card from your hand
    rather than pay this spell's mana cost.
    Destroy up to two target artifacts and/or enchantments.

    RULE 118.9's alternative cost now ships (MEC-15), same "if it's not
    your turn" gate as Force of Negation just above. Still also fully
    castable at its printed {2}{G}{G}; the "up to two" destroy is the
    already-shipped RULE 115.1a N>=2 idiom (`DestroyEffect(count=2,
    optional=True)`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {
                "target_kind": "artifact_or_enchantment", "count": 2, "optional": True,
            })],
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"exile_hand_card_color": "G", "condition": {"not_your_turn": True}},
        ),
    ]


register("Force of Vigor", _force_of_vigor)


def _daze() -> list[AbilitySpec]:
    """You may return an Island you control to its owner's hand rather than
    pay this spell's mana cost.
    Counter target spell unless its controller pays {1}.

    RULE 118.9's alternative cost now ships (MEC-15) as `alt_cost`'s
    ``return_to_hand`` key — the same subtype-word shape `game/costs.py`'s
    `ActivationCost.return_to_hand` already uses for an activated ability's
    "Return a Forest you control…" cost (Quirion Ranger-shaped), reused
    here for a spell's alternative *cast* cost instead. No condition:
    always available. Still also fully castable at its printed {1}{U};
    the "unless controller pays" half is the existing `CounterSpellEffect.
    unless_pays` primitive (Mana Leak's own shape).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {"unless_pays": "1"})],
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"return_to_hand": "island"},
        ),
    ]


register("Daze", _daze)


# --- cEDH lists batch: tax-draw family ("unless that player pays") --------
#
# New primitive: `TaxedDrawEffect` (RULE 118.3's "unless" idiom applied to a
# draw, not a sacrifice) — the payer is the *triggering spell's own caster*,
# read off `GameContext.trigger_event`, not this ability's controller.


def _rhystic_study() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, you may draw a card unless that
    player pays {1}.

    — `TaxedDrawEffect`, see the batch header above.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("taxed_draw", {"cost": "{1}"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        )
    ]


register("Rhystic Study", _rhystic_study)


def _mystic_remora() -> list[AbilitySpec]:
    """Cumulative upkeep {1}.
    Whenever an opponent casts a noncreature spell, you may draw a card
    unless that player pays {4}.

    Cumulative upkeep (RULE 702.24, MEC-16) now ships as real behaviour —
    this entry only ever carried the `taxed_draw` trigger; the keyword
    itself binds independently (`game/binding/core.py`'s keyword dispatch
    table reads `Card.keywords`/oracle text directly, regardless of
    whether the rest of the card is hand-authored), so Mystic Remora
    correctly has to be paid for again, closing the previous "dropped,
    never has to be paid for" simplification without touching this spec
    at all.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("taxed_draw", {"cost": "{4}"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
        )
    ]


register("Mystic Remora", _mystic_remora)


def _esper_sentinel() -> list[AbilitySpec]:
    """Whenever an opponent casts their first noncreature spell each turn,
    draw a card unless that player pays {X}, where X is this creature's
    power.

    **Documented simplification**: "their first ... each turn" isn't
    tracked (no per-player per-turn "first qualifying spell" counter exists
    yet) — this fires on *every* qualifying opponent spell instead of just
    the first, a strict upgrade rather than a broken card.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("taxed_draw", {"amount_from_source_power": True})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
        )
    ]


register("Esper Sentinel", _esper_sentinel)


def _smothering_tithe() -> list[AbilitySpec]:
    """Whenever an opponent draws a card, that player may pay {2}. If the
    player doesn't, you create a Treasure token.

    MEC-12 — the same tax-draw family as Rhystic Study/Mystic Remora/Esper
    Sentinel above, but the trigger event is `EventType.DRAW` (an
    ``"opponent draws"`` group condition needed its own
    `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` entry, ``DRAW``:
    ``"player_id"`` — `RulesEngine.draw` already fired that event with the
    right shape, only this table row was missing) and the "if you don't"
    branch is a Treasure, not a card — `effects.PayCostThenEffect`'s
    general RULE 118.3 "you may pay `<cost>`. If you don't, `<effect>`."
    shape (``payer="event_player"`` reads the *drawing* player off the
    triggering DRAW event, same as `TaxedDrawEffect`'s payer read for its
    own family; the create-token effect resolves under this permanent's
    own controller, matching "**you** create a Treasure token").
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec(
                "pay_cost_then",
                {
                    "cost": "{2}",
                    "payer": "event_player",
                    "else_effects": [
                        {
                            "type": "create_token",
                            "params": {"token_name": "Treasure", "count": 1},
                        }
                    ],
                },
            )],
            trigger={
                "event": EventType.DRAW,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        )
    ]


register("Smothering Tithe", _smothering_tithe)


def _imperial_recruiter() -> list[AbilitySpec]:
    """When ~ enters, you may search your library for a creature card with
    power 2 or less, reveal it, put it into your hand, then shuffle.

    MEC-12 fourth pass — the generalized tutor grammar (`SearchLibraryEffect`/
    `models.cards.card_query`) doesn't parse a power/toughness qualifier after the
    search noun phrase (a documented gap on the parser side, same family as
    the already-unclaimed "with mana value X or less"); hand-authored
    directly onto the new `card_query.max_power` criteria key instead.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "max_power": 2},
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Imperial Recruiter", _imperial_recruiter)


def _recruiter_of_the_guard() -> list[AbilitySpec]:
    """When ~ enters, you may search your library for a creature card with
    toughness 2 or less, reveal it, put it into your hand, then shuffle.

    MEC-12 fourth pass — same gap and same fix as Imperial Recruiter above,
    on `card_query.max_toughness` instead of `max_power`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "max_toughness": 2},
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Recruiter of the Guard", _recruiter_of_the_guard)


def _wheel_of_fortune() -> list[AbilitySpec]:
    """Each player discards their hand, then draws seven cards.

    ENG-37 B7 retired the fused `wheel_of_fortune` type: a `seq` of a mass
    `discard` (``scope="each_player"``, ``whole_hand=True`` — every player
    discards whatever they hold) and a mass `draw` (``selector="each_player"``,
    flat 7). Windfall is the same shape with the draw count `bind`-measured
    instead of fixed. No oracle-text recognizer yet — this printed line is a
    one-card template, not a family.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("seq", {"effects": [
            {"type": "discard", "params": {"scope": "each_player", "whole_hand": True}},
            {"type": "draw", "params": {"selector": "each_player", "count": 7}},
        ]})])
    ]


register("Wheel of Fortune", _wheel_of_fortune)


def _ruination() -> list[AbilitySpec]:
    """Destroy all nonbasic lands.

    MEC-12 fourth pass — `effects.DestroyEffect`'s existing
    ``selector="all_lands"`` mass-wipe path, narrowed by the new
    ``filter={"nonbasic": True}`` key (mirrors ``max_mana_value``'s
    selector+filter split for every other qualified board wipe).
    """
    return [AbilitySpec("spell_effect", [EffectSpec("destroy", {
        "selector": "all_lands", "filter": {"nonbasic": True},
    })])]


register("Ruination", _ruination)


def _city_of_brass() -> list[AbilitySpec]:
    """Whenever this land becomes tapped, it deals 1 damage to you.
    {T}: Add one mana of any color.

    The mana ability itself is covered by the engine's plain mana model
    (`mana_abilities_for`, no spec needed) — only the "becomes tapped"
    drawback needs a spec, `EventType.TAPPED` (already fired for every
    genuine untapped→tapped transition, not just a mana tap).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"selector": "controller"})],
            trigger={"event": EventType.TAPPED, "condition": {"subject": "self"}},
        )
    ]


register("City of Brass", _city_of_brass)


def _forbidden_orchard() -> list[AbilitySpec]:
    """{T}: Add one mana of any color.
    Whenever you tap this land for mana, target opponent creates a 1/1
    colorless Spirit creature token.

    **Documented simplification**: "target opponent" becomes every
    opponent (`CreateTokenEffect`'s ``each_opponent`` creator) — no single-
    opponent target choice for a land-tap trigger yet; correct in 1v1,
    an overstatement in multiplayer.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "creators": "each_opponent", "power": 1, "toughness": 1,
                "colors": [], "subtypes": ["Spirit"], "token_name": "Spirit",
            })],
            trigger={"event": EventType.TAPPED_FOR_MANA, "condition": {"subject": "self"}},
        )
    ]


register("Forbidden Orchard", _forbidden_orchard)


# --- cEDH lists batch: RULE 115.4 "change the target" -----------------------
#
# New primitive: `ChangeTargetEffect`/`RulesEngine.change_target` (RULE
# 115.4/601.2c) — a genuine retarget of an *existing* stack item, not the
# already-shipped "choose new targets for a freshly-made copy" (RULE
# 707.10c). Scoped to a spell with exactly one existing target (see
# `ChangeTargetEffect`'s own docstring); both real cards below only ever
# retarget a single-target spell.


def _misdirection() -> list[AbilitySpec]:
    """You may exile a blue card from your hand rather than pay this
    spell's mana cost.
    Change the target of target spell with a single target.

    **Documented simplification**: the free-cast alternative cost (RULE
    118.9, same drop precedent as the Force of Will cycle) is dropped.
    Fully castable at its printed {3}{U}{U}; the retarget itself is the
    new `change_target` primitive above, mandatory (no "may") per the
    printed text.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("change_target", {"single_target": True})],
        )
    ]


register("Misdirection", _misdirection)


def _deflecting_swat() -> list[AbilitySpec]:
    """If you control a commander, you may cast this spell without paying
    its mana cost.
    You may choose new targets for target spell or ability.

    **Documented simplifications**: the commander-tax-free alternative
    cast (RULE 601.2f's `free_cast_condition` — confirmed unreachable from
    a real game session regardless, see BACKLOG.md) is dropped, fully
    castable at its printed {2}{R}. "Spell or ability" is now the real
    printed scope (ENG-26, `spell_or_ability=True` — was **spell**-only
    before the RULE 115 targetable-ability-on-the-stack primitive shipped).
    ``optional=True`` is the printed "you may" (unlike Misdirection's
    mandatory "Change the target").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("change_target", {"optional": True, "spell_or_ability": True})],
        )
    ]


register("Deflecting Swat", _deflecting_swat)


def _stifle() -> list[AbilitySpec]:
    """Counter target activated or triggered ability. (Mana abilities
    can't be targeted.)

    — Stifle. The direct payoff of ENG-26's RULE 115/701.5b primitive
    (`counter_ability`/`CounterAbilityEffect`, `targeting.py`'s
    ``"ability"`` kind): a one-clause card that exercises it end to end.
    The parenthetical is reminder text (RULE 115.9c already excludes a
    mana ability from every targetable-ability kind — it never uses the
    stack at all — so nothing extra needs enforcing here).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_ability", {})],
        )
    ]


register("Stifle", _stifle)


def _trickbind() -> list[AbilitySpec]:
    """Split second (As long as this spell is on the stack, players can't
    cast spells or activate abilities that aren't mana abilities.)
    Counter target activated or triggered ability. If a permanent's
    ability is countered this way, activated abilities of that permanent
    can't be activated this turn. (Mana abilities can't be targeted.)

    — Trickbind. Shares Stifle's `counter_ability` core.

    **Documented simplifications**: RULE 702.61 Split Second (nothing in
    the codebase recognizes it yet — a cast-timing restriction, not a
    targeting/effect shape, so it's out of ENG-26's own scope) and the
    "activated abilities of that permanent can't be activated this turn"
    post-counter lockout (would need its own per-object, turn-scoped flag
    consulted by `GameEngine.can_activate` — a real but narrow primitive
    no other printed card needs yet) are both dropped; the core "counter
    target activated or triggered ability" line is real behaviour.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_ability", {})],
        )
    ]


register("Trickbind", _trickbind)


def _finale_of_devastation() -> list[AbilitySpec]:
    """Search your library and/or graveyard for a creature card with mana
    value X or less and put it onto the battlefield. If you search your
    library this way, shuffle. If X is 10 or more, creatures you control
    get +X/+X and gain haste until end of turn.

    — MEC-12 (fifth pass): the "search library and/or graveyard" half
    reuses `SearchLibraryEffect`'s ``zones``/``criteria`` exactly like the
    oracle-text `search_zone_put` handler does, just with the search's own
    ``max_mana_value`` bound left as the ``"x"`` sentinel
    `RulesEngine._substitute_x` now knows to walk into a nested
    ``criteria`` dict (a fifth-pass primitive, alongside Meltdown's
    matching `filter` case); the bonus half is `Martial Coup`'s own
    `source_x_paid_at_least` `ConditionalEffect` gate wrapping a
    `creatures_you_control`-selector `PumpEffect`. Not built as a general
    oracle-text handler (unlike the plain single-zone "with mana value X
    or less" qualifier, which is): this card's own two-sentence shape —
    a conditional bonus keyed to the *same* spell's {X} as its search —
    is a singleton template cache-wide, the sanctioned hand-authoring
    escape valve rather than a family worth its own grammar yet.

    Simplified: the search always shuffles the library when it's among
    the search zones (the same `search_zone_put` simplification the
    oracle-text handler already documents — it doesn't track which zone
    the found card actually came from), so this always shuffles rather
    than only "if you search your library this way".
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": {"type": "Creature", "max_mana_value": "x"},
                    "destination": "battlefield",
                    "zones": ["library", "graveyard"],
                }),
                EffectSpec(
                    "pump",
                    {"power": "x", "toughness": "x", "keywords": ["haste"], "selector": "creatures_you_control"},
                    condition={"source_x_paid_at_least": 10},
                ),
            ],
        ),
    ]


register("Finale of Devastation", _finale_of_devastation)


def _ghostfire_slice() -> list[AbilitySpec]:
    """Devoid (This card has no color.)
    This spell costs {2} less to cast if an opponent controls a
    multicolored permanent.
    Ghostfire Slice deals 4 damage to any target.

    — MEC-12 (fifth pass): a genuine gap, not just a missing handler —
    `game/continuous.self_cost_reduction_for`/`EffectRegistry`'s
    ``"cost_reduction"`` factory both already support an `active_if` gate
    (this pass's own primitive, alongside `multicolored_permanents_you_
    control`'s new `count_selector`), but the oracle-text *parser* only
    ever reaches that static path for a **permanent** — `parser/oracle/
    segmenter.py`'s `allow_spell_effect` gate routes every clause on a
    true instant/sorcery through the one-shot `spell_effect` dispatch
    instead, which has no static-ability shape to emit at all. Hand-
    authored as two independent `AbilitySpec`s instead of widening that
    routing (a real but separate architectural gap — `attach_to_object`'s
    `spell_effect` branch would need to split a `StaticAbility` out of its
    bound effects into `obj.static_effects`, which no other card needs
    yet): ``"static"`` doesn't care what kind of card its owner is, so a
    hand-authored `AbilitySpec("static", …)` on an Instant reaches
    `self_cost_reduction_for` exactly like Embercleave's parsed one does
    on an Equipment.

    Simplified: Devoid (a purely cosmetic colour-identity keyword with no
    gameplay effect this engine's card model can't already represent via
    printed colourless mana cost) isn't separately modeled.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 2,
                "active_if": {
                    "kind": "opponent_count",
                    "selector": "multicolored_permanents_you_control",
                    "min": 1,
                },
            })],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"target_kind": "any", "amount": 4})],
        ),
    ]


register("Ghostfire Slice", _ghostfire_slice)


def _mox_diamond() -> list[AbilitySpec]:
    """If this artifact would enter, you may discard a land card instead.
    If you do, put this artifact onto the battlefield. If you don't, put
    it into its owner's graveyard.
    {T}: Add one mana of any color.

    — MEC-12 (sixth pass): RULE 614.12's own worked example, confirmed a
    singleton template cache-wide (a raw-text grep for "would enter, you
    may" turns up only this card). `AbilitySpec.enter_or_graveyard_discard_
    land` (`RulesEngine._offer_enter_or_graveyard`, offered *before* every
    other battlefield-entry step, since declining means this never becomes
    a permanent at all) is a new, genuinely general RULE 614.12 primitive
    even though only one card needs it today — a bare marker flag, not a
    parametrized cost, since a second card of this shape would almost
    certainly print the identical "discard a land card" cost anyway. The
    mana ability itself needs no hand-authoring: a plain "{T}: Add one
    mana of any color." is recognized generically by `mana_abilities_for`.
    """
    return [
        AbilitySpec(
            "static", [],
            enter_or_graveyard_discard_land=True,
        ),
    ]


register("Mox Diamond", _mox_diamond)


def _eye_of_ugin() -> list[AbilitySpec]:
    """Colorless Eldrazi spells you cast cost {2} less to cast.
    {7}, {T}: Search your library for a colorless creature card, reveal
    it, put it into your hand, then shuffle.

    — MEC-12 (sixth pass). The search half is left to the oracle-text
    parser (`_SEARCH_COLOR_WORD`'s new "colorless" entry, matched onto
    `models.cards.card_query`'s own colour-emptiness check) rather than
    duplicated here — only the static half is hand-authored, since a
    combined colour-emptiness-**and**-creature-subtype cost filter
    ("Colorless Eldrazi spells", as opposed to a bare colour or a bare
    main-card-type filter) is this pass's own new primitive
    (`continuous.cost_reduction_for`'s `spell_color="colorless"` +
    `spell_subtype="Eldrazi"`, composed by plain AND) with no other real
    card on this exact combined shape yet — not worth a general "<colour-
    or-colorless> <optional creature subtype> spells [you cast] cost {N}
    less" grammar until a second one does. Both abilities are hand-
    authored on the same registered card regardless, since a registered
    card's catalogue entry replaces the parser's own output wholesale
    rather than merging with it — the search line below is simply the
    identical shape the parser would already produce for this card on
    its own.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 2,
                "spell_color": "colorless", "spell_subtype": "Eldrazi",
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "color": "colorless"},
                "destination": "hand",
            })],
            cost={"text": "{7}, {T}"},
        ),
    ]


register("Eye of Ugin", _eye_of_ugin)


def _tainted_pact() -> list[AbilitySpec]:
    """Exile the top card of your library. You may put that card into
    your hand unless it has the same name as another card exiled this
    way. Repeat this process until you put a card into your hand or you
    exile two cards with the same name, whichever comes first.

    — MEC-12 (sixth pass). `ExileUntilDuplicateNameEffect`/`RulesEngine.
    exile_until_duplicate_name` — a new, genuinely general RULE 701.19-
    adjacent loop shape (see its own docstring for why it's not an
    instance of `dig_until`), confirmed a singleton template cache-wide
    but built as a real primitive anyway since the loop has no card-
    specific data in it. A real interactive choice each time a fresh
    (non-duplicate) name comes up with cards still left in the library —
    take it, or keep digging (the real reason this card is played: paired
    with Thassa's Oracle in a singleton deck, deliberately declining every
    hit mills the whole library on purpose).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_until_duplicate_name", {})],
        ),
    ]


register("Tainted Pact", _tainted_pact)


def _transmute_artifact() -> list[AbilitySpec]:
    """Sacrifice an artifact. If you do, search your library for an
    artifact card. If that card's mana value is less than or equal to the
    sacrificed artifact's mana value, put it onto the battlefield. If
    it's greater, you may pay {X}, where X is the difference. If you do,
    put it onto the battlefield. If you don't, put it into its owner's
    graveyard. Then shuffle.

    — MEC-12 (sixth pass). `TransmuteArtifactEffect`/`RulesEngine.
    transmute_artifact` — confirmed a singleton cost-comparison-gated
    placement cache-wide, self-contained (its own three `pending_choice`
    kinds: sacrifice, search, and an optional pay-the-difference) rather
    than composed from the general search/sacrifice/`pay_cost_then`
    primitives, none of which can express a cost computed from what a
    different, just-made choice turned out to be.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("transmute_artifact", {})],
        ),
    ]


register("Transmute Artifact", _transmute_artifact)


def _chain_of_vapor() -> list[AbilitySpec]:
    """Return target nonland permanent to its owner's hand. Then that
    permanent's controller may sacrifice a land of their choice. If the
    player does, they may copy this spell and may choose a new target for
    that copy.

    — Vivi B4 batch. `return_to_hand` for the bounce; `PayCostThenEffect`'s
    general "you may pay `<cost>`. If you do, nothing further." (RULE
    118.3) models the land sacrifice itself with a new
    ``payer="previous_target_controller"`` (`GameContext.previous_targets`
    — it's the *bounced permanent's* controller being asked, almost always
    an opponent, not this spell's own caster). **Documented
    simplification**: "they may copy this spell and may choose a new
    target for that copy" is dropped rather than approximated —
    `CopySpellEffect.copy_self` ("copy this spell" while it's still
    resolving) can't reach back through a `pending_choice` pause (by the
    time the player answers "pay", the original has already finished
    resolving and left the stack for the graveyard, RULE 608.2m), and a
    same-target "copy" would fizzle for real play anyway: the only target
    this MVP can default to is the permanent the first sentence just
    bounced, which is no longer a legal "target nonland permanent" once
    it's sitting in hand — RAW's own "you may choose new targets" is
    exactly there to route around that, and this engine doesn't offer that
    choice yet. Sacrificing the land is still a real, correctly-costed
    decision on its own.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_to_hand", {"target_kind": "nonland_permanent"}),
                EffectSpec("pay_cost_then", {
                    "cost": "sacrifice a land",
                    "payer": "previous_target_controller",
                    "effects": [],
                }),
            ],
        ),
    ]


register("Chain of Vapor", _chain_of_vapor)


def _intuition() -> list[AbilitySpec]:
    """Search your library for three cards and reveal them. Target
    opponent chooses one. Put that card into your hand and the rest into
    your graveyard. Then shuffle.

    — Vivi B4 batch. `IntuitionEffect`/`RulesEngine._request_intuition` —
    a genuinely two-player interactive search (the caster picks the three
    cards, then the *targeted opponent* picks which one is kept), self-
    contained rather than composed from `_request_search` (whose single
    ``destination`` has no way to hand off to a second player's choice).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("intuition_search", {"count": 3})],
        ),
    ]


register("Intuition", _intuition)


def _ral_monsoon_mage() -> list[AbilitySpec]:
    """Whenever you cast an instant or sorcery spell during your turn, flip
    a coin. If you lose the flip, ~ deals 1 damage to you. If you win the
    flip, you may exile ~. If you do, return him to the battlefield
    transformed under his owner's control.

    — Vivi B4 batch. New `CoinFlipEffect`/`RulesEngine.coin_flip` (RULE
    705.1, previously built but unused by any card) branches into the loss
    (``damage`` with the existing ``selector="controller"``, Mana Vault's
    own "deals 1 damage to you" shape) and win (`exile_return_transformed`,
    RULE 400.7/712.8's existing transform-via-zone-change primitive)
    halves. "During your turn" reuses `phase_relation="you"` — built for
    RULE 500.7 "at the beginning of your `<step>`" triggers, but its
    predicate only checks whose turn it currently is, so it gates a
    SPELL_CAST trigger exactly as well. **Documented simplification**:
    "you may exile ~" is modeled as unconditional (always taken) — the
    same accepted simplification `CoinFlipEffect` itself already documents.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("coin_flip", {
                "lose_effects": [{"type": "damage", "params": {"selector": "controller", "amount": 1}}],
                "win_effects": [{"type": "exile_return_transformed", "params": {}}],
            })],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "you"},
                "spell_card_types": ["instant", "sorcery"],
                "phase_relation": "you",
            },
        ),
    ]


register("Ral, Monsoon Mage", _ral_monsoon_mage)


def _talon_gates_of_madara() -> list[AbilitySpec]:
    """When this land enters, up to one target creature phases out.
    {T}: Add {C}.
    {1}, {T}: Add one mana of any color.
    {4}: Put this card from your hand onto the battlefield.

    — Vivi B4 batch. The two mana abilities are already oracle-parsed
    (RULE 605); only the ETB phase-out trigger (`PhaseOutEffect`) and the
    new `PutSelfOntoBattlefieldFromHandEffect`/`ActivationCost.hand_zone`
    ("play this land from hand for a generic cost, bypassing RULE 305's
    per-turn land drop — an activated ability, not a land play") needed
    hand-authoring.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("phase_out", {"target_kind": "creature", "optional": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("put_self_onto_battlefield_from_hand", {})],
            cost="{4}",
        ),
    ]


register("Talon Gates of Madara", _talon_gates_of_madara)


def _urzas_saga() -> list[AbilitySpec]:
    """I — This Saga gains "{T}: Add {C}."
    II — This Saga gains "{2}, {T}: Create a 0/0 colorless Construct
    artifact creature token with 'This token gets +1/+1 for each artifact
    you control.'"
    III — Search your library for an artifact card with mana value 0 or 1,
    put it onto the battlefield, then shuffle.

    — Vivi B4 batch. Chapters I/II are `GrantSelfActivatedAbilityEffect`
    (RULE 714.2c's *lasting* self-grant — new, since a Saga chapter's
    "gains an ability" outlives the trigger that grants it, unlike the
    turn-scoped `grant_graveyard_cast_permission_this_turn` shape it
    otherwise mirrors), each wrapping the ability it grants as nested
    ``EffectSpec`` dicts. Chapter II's Construct token gets its own
    self-scaling +1/+1-per-artifact ability via `CreateTokenEffect.
    grant_self_anthem` (new — appends a real ``anthem``-shaped
    `StaticAbility` onto the *created token itself* rather than the
    effect's source, reusing the oracle-parsed "creatures you control get
    +N/+N" static's own ``power_count``/``toughness_count`` per-count
    scaling). Chapter III is a plain `search`. **Documented
    simplification**: chapter I's granted mana ability resolves through
    the stack like any other granted activated ability (`grant_activated_
    ability`'s general form) rather than as a genuine no-stack RULE 605.1a
    mana ability — functionally equivalent (the mana still reaches the
    pool), just one extra `activate_ability` step instead of an instant
    tap-for-mana shortcut.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_self_activated_ability", {
                "cost": {"taps_self": True},
                "effects": [{"type": "add_mana", "params": {"colors": ["C"]}}],
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_self_activated_ability", {
                "cost": {"mana": "{2}", "taps_self": True},
                "effects": [{"type": "create_token", "params": {
                    "power": 0, "toughness": 0, "colors": [], "subtypes": ["Construct"],
                    "token_name": "Construct", "is_artifact": True,
                    "grant_self_anthem": {
                        "power": 1, "toughness": 1,
                        "power_count": "artifacts_you_control",
                        "toughness_count": "artifacts_you_control",
                    },
                }}],
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact", "max_mana_value": 1},
                "destination": "battlefield",
                "optional": False,
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
        ),
    ]


register("Urza's Saga", _urzas_saga)


def _quicksilver_elemental() -> list[AbilitySpec]:
    """{U}: This creature gains all activated abilities of target creature
    until end of turn. (If any of the abilities use that creature's name,
    use this creature's name instead.)
    You may spend blue mana as though it were mana of any color to pay the
    activation costs of this creature's abilities.

    — MEC-23, the one card the Vivi B4 batch (2026-08-10) left open. Two new
    general primitives, both closing this ticket:

    - `effects.GainActivatedAbilitiesOfTargetEffect` (``"gain_target_
      activated_abilities"``) is the resolve-time, single-target sibling of
      MEC-21's standing layer-6 `grant_borrowed_activated_ability`
      (Agatha's Soul Cauldron): it snapshots ``target.activated_abilities``
      once, at resolution, redirecting each via the same `continuous.
      _retarget_effect_source` (RULE 113.7c), onto a turn-scoped
      `GameObject.temp_granted_activated_abilities` field rather than
      re-deriving live off a standing static every recompute — a later
      change to the target's own ability set doesn't retroactively change
      what was copied, matching the card's own ruling.
    - `continuous.any_color_for_activation` (MEC-21's wildcard-activation
      permission) gained ``from_color``/``self_only`` params: Agatha's
      grant is unscoped ("creatures you control") and lets *any* of the
      five colors pay any colored pip, while this card's is self-scoped
      ("this creature's abilities") and only blue mana counts as the
      wildcard (`ManaPool._solve`'s matching single-color branch) — a red
      pip still needs real red or blue mana, never green/white/black.

    The card's own parenthetical ("use this creature's name instead") is
    reminder text about the *retargeting itself* (RULE 113.7c), not a
    separate behaviour — already covered by `_retarget_effect_source`
    redirecting each borrowed effect's ``.source`` to Quicksilver Elemental.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("gain_target_activated_abilities", {})],
            cost={"mana": "{U}"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_any_color_for_activation", {
                "creature_abilities_only": True,
                "from_color": "U",
                "self_only": True,
            })],
        ),
    ]


register("Quicksilver Elemental", _quicksilver_elemental)


def _drana_and_linvala() -> list[AbilitySpec]:
    """Flying, vigilance
    Activated abilities of creatures your opponents control can't be
    activated.
    Drana and Linvala has all activated abilities of all creatures your
    opponents control. You may spend mana as though it were mana of any
    color to activate those abilities.

    — MEC-26, the first of the two cards a second MEC-23 deferral had left
    open (found while sizing MEC-21, 2026-07-22; deferred again by MEC-23,
    2026-08-11 — this batch is the mandatory "hand-author or promote" close
    per the project's no-half-implementations rule). Needed a genuinely
    **standing, group-scoped** sibling of MEC-21's `grant_borrowed_
    activated_ability` (Agatha's Soul Cauldron) rather than MEC-23's own
    resolve-time single-target snapshot: the donor set here is "all
    creatures your opponents control", read live off the battlefield every
    recompute, not a fixed exiled-card or once-copied list. One new
    ``source_mode="group"`` on the existing static (`continuous.
    _apply_borrowed_activated_abilities`) covers it — reusing the ordinary
    ``affects`` selector vocabulary (`"creatures_opponents_control"`,
    already built for Manglehorn/goad-adjacent cards) as the *donor* scope
    rather than the *grantee* scope `affects` already served.

    The other two printed lines turned out to need no new machinery at
    all: "Activated abilities of creatures your opponents control can't be
    activated" is `activation_prohibition`'s own existing, already-general
    ``affects`` selector (Collector Ouphe-shaped, just never scoped to
    ``"creatures_opponents_control"`` by a real card before); and "You may
    spend mana as though it were mana of any color to activate **those**
    abilities" is MEC-23's `grant_any_color_for_activation`'s own
    ``self_only=True`` — the original MEC-26 filing worried ``self_only``
    would over-scope to "any ability Drana and Linvala has", not just the
    borrowed set, but Drana and Linvala prints no *other* activated
    ability of her own, so in practice the two sets are identical and no
    third param was needed. (Scheming Fence, below, is the same story.)
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {"affects": "creatures_opponents_control"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self",
                "source_mode": "group",
                "source_affects": "creatures_opponents_control",
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_any_color_for_activation", {
                "creature_abilities_only": True,
                "self_only": True,
            })],
        ),
    ]


register("Drana and Linvala", _drana_and_linvala)


def _scheming_fence() -> list[AbilitySpec]:
    """As this creature enters, you may choose a nonland permanent.
    Activated abilities of the chosen permanent can't be activated.
    This creature has all activated abilities of the chosen permanent
    except for loyalty abilities. You may spend mana as though it were
    mana of any color to activate those abilities.

    — MEC-26's second card, the ``source_mode="chosen_permanent"`` sibling
    of Drana and Linvala's ``"group"`` mode: a single donor picked once
    ("the chosen permanent") rather than a whole group, needing its own
    new selector rather than reusing an existing ``affects`` value —
    `GameObject.chosen_permanent_id` (a new ``chosen_*`` field alongside
    `chosen_type`/`chosen_color`/`chosen_player_id`), a new
    ``"chosen_permanent"`` `continuous.group_selector_objects` case (the
    `attached_permanent` idiom, reading a chosen id instead of an
    attachment), and a new `ChoosePermanentEffect`/``"choose_permanent"``
    `RulesEngine._request_choose_objects` action to make the pick (an
    ordinary interactive ETB trigger, not a pre-entry RULE 601.2b
    replacement like `chosen_type`/`chosen_color` — see `GameObject.
    chosen_permanent_id`'s own docstring for why the "as it enters" wording
    doesn't need a pre-entry choice here). "You may" makes this genuinely
    optional (`ChoosePermanentEffect(optional=True)`, the default),
    unlike `chosen_type`/`chosen_color`'s always-mandatory pick.

    "…except for loyalty abilities" is `grant_borrowed_activated_ability`'s
    new ``exclude_loyalty`` param — a planeswalker-only RULE 606.5c concept
    that makes no sense copied onto a creature, dropped at the source
    rather than granted-and-then-unusable. Candidates are *any* nonland
    permanent on the whole battlefield, not just this creature's
    controller's own (`ChoosePermanentEffect`'s own docstring) — Scheming
    Fence borrows an opponent's activated ability just as readily as its
    own controller's.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_permanent", {"optional": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {"affects": "chosen_permanent"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self",
                "source_mode": "chosen_permanent",
                "exclude_loyalty": True,
                # "a nonland permanent" — unlike Drana and Linvala's
                # creature-only donor pool, the chosen permanent can be any
                # nonland type (artifact/enchantment/planeswalker/battle),
                # so the default creature-only donor filter must be off.
                "creature_only": False,
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_any_color_for_activation", {
                "creature_abilities_only": True,
                "self_only": True,
            })],
        ),
    ]


register("Scheming Fence", _scheming_fence)


def _combat_celebrant() -> list[AbilitySpec]:
    """If this creature hasn't been exerted this turn, you may exert it as
    it attacks. When you do, untap all other creatures you control and
    after this phase, there is an additional combat phase.

    — Combat Celebrant. RULE 702.19's Exert is otherwise a plain oracle-text
    parse (`parser/oracle/segmenter.py`'s ``_EXERT_TRIGGER_RE``/
    ``_EXERT_PLAYER_TRIGGER_RE``, `EventType.EXERTED`) — this is the one
    card in the cache printing exert's optional "if ~ hasn't been exerted
    this turn" self-loop guard, hand-authored rather than building a general
    "once per turn" trigger-condition primitive for a single card. Without
    it, this ability's own granted extra combat phase would let the
    creature attack, exert, and grant *another* extra combat phase forever
    — a real infinite loop, not just a flavour simplification. The generic
    parser handler still claims this card's text (it just drops the guard),
    so this entry exists purely to override that with the safe,
    conditioned version; `ConditionalEffect`'s ``not_already_exerted`` key
    reads the firing `EventType.EXERTED` event's own ``already_exerted``
    snapshot (`GameEngine.declare_attackers`), not the object's live
    `exerted_this_turn` flag — that flag is already true by the time this
    trigger resolves.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "tap",
                    {"selector": "other_creatures_you_control", "untap": True},
                    condition={"not_already_exerted": True},
                ),
                EffectSpec(
                    "extra_combat_phase", {},
                    condition={"not_already_exerted": True},
                ),
            ],
            trigger={"event": "EXERTED", "condition": {"subject": "self"}},
        ),
    ]


register("Combat Celebrant", _combat_celebrant)


def _polymorph() -> list[AbilitySpec]:
    """Destroy target creature. It can't be regenerated. Its controller
    reveals cards from the top of their library until they reveal a
    creature card. The player puts that card onto the battlefield, then
    shuffles all other cards revealed this way into their library.

    — MEC-12 (cEDH Kinnan). `DestroyExileThenControllerRevealCreatureEffect`
    is the new general primitive: one atomic effect rather than a two-effect
    list, since the dig has to be run by the *destroyed creature's own
    controller* (read before the RULE 400.7 zone change, the same "read it
    before it leaves the battlefield" idiom Nature's Claim's composition (`destroy` + a referent recipient, ENG-37)
    already uses) — not this spell's own caster. Reuses `dig_until`'s new
    ``rest_destination="library_shuffled"`` (a real shuffle, not just "the
    bottom in a random order" — the two read identically to a player, but
    match Polymorph's actual printed wording).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_exile_then_controller_reveal_creature", {
                "target_kind": "creature", "mode": "destroy", "criteria": "Creature",
            })],
        ),
    ]


register("Polymorph", _polymorph)

