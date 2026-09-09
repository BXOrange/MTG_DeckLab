"""Card -> AbilitySpec catalogue entries, part 007 of 016.

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

def _motivated_pony() -> list[AbilitySpec]:
    """Trample, haste
    Whenever this creature attacks, attacking creatures get +1/+1 until
    end of turn. If a Food entered under your control this turn, untap
    those creatures and they get an additional +2/+2 until end of turn.

    Simplified: narrowed to the unconditional first half (attacking
    creatures get +1/+1) — the "if a Food entered this turn" bonus/untap
    branch isn't modeled (no "permanent of type X entered this turn"
    tracker exists, unlike `creatures_died_this_turn`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"power": 1, "toughness": 1, "selector": "attacking_creatures"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Motivated Pony", _motivated_pony)


def _of_herbs_and_stewed_rabbit() -> list[AbilitySpec]:
    """I — Put a +1/+1 counter on up to one target creature. Create a Food
    token.
    II — Draw a card. Create a Food token.
    III — Create a 1/1 white Halfling creature token for each Food you
    control.

    Chapters I/II are carried over verbatim from what the parser already
    resolves on its own; only chapter III (a "for each Food you control"
    dynamic count no `create_token` handler recognizes yet) needed
    hand-authoring — same shape as Vault 12: The Necropolis's own chapter
    II, just with the new ``foods_you_control`` count selector.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"target_kind": "creature", "optional": True}),
                EffectSpec("create_token", {"count": 1, "token_name": "Food"}),
            ],
            trigger={"event": "SAGA_CHAPTER", "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1}), EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={"event": "SAGA_CHAPTER", "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Halfling"],
                "token_name": "Halfling", "count_selector": "foods_you_control",
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
        ),
    ]


register("Of Herbs and Stewed Rabbit", _of_herbs_and_stewed_rabbit)


def _peregrin_took() -> list[AbilitySpec]:
    """If one or more tokens would be created under your control, those
    tokens plus an additional Food token are created instead.
    Sacrifice three Foods: Draw a card.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("additional_named_token", {"token_name": "Food"})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"sacrifice_count": (3, "food")},
        ),
    ]


register("Peregrin Took", _peregrin_took)


def _prize_pig() -> list[AbilitySpec]:
    """Whenever you gain life, put that many ribbon counters on this
    creature. Then if there are three or more ribbon counters on this
    creature, remove those counters and untap it.
    {T}: Add one mana of any color.

    Simplified: narrowed to the counter accumulation — the "at 3+, remove
    and untap" follow-up isn't modeled (no "then if this permanent's own
    counter count reaches N, do X" primitive exists yet). The counters
    still visibly accumulate, so the card isn't a no-op, just missing its
    payoff.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "ribbon", "amount_from_trigger_event": "amount"})],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
        ),
    ]


register("Prize Pig", _prize_pig)


def _shire_shirriff() -> list[AbilitySpec]:
    """Vigilance
    When this creature enters, you may sacrifice a token. When you do,
    exile target creature an opponent controls until this creature leaves
    the battlefield.

    Simplified: the "you may sacrifice a token" cost gate on the exile
    isn't modeled as an interactive optional choice — the exile always
    happens (still linked, still returned when Shire Shirriff leaves), a
    strictly *more* generous approximation than requiring a token
    sacrifice.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "creature_you_dont_control", "remember": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Shire Shirriff", _shire_shirriff)


def _tireless_provisioner() -> list[AbilitySpec]:
    """Landfall — Whenever a land you control enters, create a Food token
    or a Treasure token.

    Simplified: narrowed to always creating a Food token — the "or a
    Treasure" choice isn't modeled (no interactive "choose one of two
    token types" primitive for a plain trigger body exists yet).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "land", "controller": "you", "other": False},
            },
        ),
    ]


register("Tireless Provisioner", _tireless_provisioner)


def _treebeard_gracious_host() -> list[AbilitySpec]:
    """Trample, ward {2}
    When Treebeard enters, create two Food tokens.
    Whenever you gain life, put that many +1/+1 counters on target
    Halfling or Treefolk.

    Simplified: the target is widened to "target creature you control"
    (no subtype-filtered RULE 115 target kind exists yet — every real
    target_kind is either broad main-type or a fixed single subtype, not
    an ad-hoc "Halfling or Treefolk" OR-list).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 2, "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "target_kind": "creature_you_control", "amount_from_trigger_event": "amount",
            })],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
        ),
    ]


register("Treebeard, Gracious Host", _treebeard_gracious_host)


def _smeagol_helpful_guide() -> list[AbilitySpec]:
    """At the beginning of your end step, if a creature died under your
    control this turn, the Ring tempts you.
    Whenever the Ring tempts you, target opponent reveals cards from the
    top of their library until they reveal a land card. Put that card
    onto the battlefield tapped under your control and the rest into
    their graveyard.

    Simplified: the ring-tempted payoff is narrowed to *your own* library
    instead of a chosen opponent's (`RulesEngine.dig_until` always digs
    the ability's own controller — no "dig a chosen player's library"
    variant exists), the found land enters untapped (`dig_until`'s
    "battlefield" hit destination doesn't apply RULE 614.1 tapped-entry),
    and the rest goes to exile rather than graveyard (`dig_until`'s own
    "exile" default `rest_destination`, the only one it supports besides
    a random bottom-of-library shuffle).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec(
                "the_ring_tempts_you", {},
                condition={"creatures_died_this_turn_at_least": 1},
            )],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": {"type": "Land"}, "hit_destination": "battlefield", "rest_destination": "exile",
            })],
            trigger={"event": EventType.RING_TEMPTED, "condition": {"subject": "you"}},
        ),
    ]


register("Sméagol, Helpful Guide", _smeagol_helpful_guide)


def _the_battle_of_bywater() -> list[AbilitySpec]:
    """Destroy all creatures with power 3 or greater. Then create a Food
    token for each creature you control.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"selector": "all_creatures", "filter": {"min_power": 3}}),
                EffectSpec("create_token", {"token_name": "Food", "count_selector": "creatures_you_control"}),
            ],
        ),
    ]


register("The Battle of Bywater", _the_battle_of_bywater)


def _the_one_ring() -> list[AbilitySpec]:
    """Indestructible
    When The One Ring enters, if you cast it, you gain protection from
    everything until your next turn.
    At the beginning of your upkeep, you lose 1 life for each burden
    counter on The One Ring.
    {T}: Put a burden counter on The One Ring, then draw a card for each
    burden counter on The One Ring.

    Simplified: the ETB "if you cast it" protection-from-everything grant
    isn't modeled (no "if this was cast, not put onto the battlefield
    another way" condition exists, and no generic "protection from
    everything" grant primitive) — the burden-counter draw engine/life-
    loss loop (this card's real ongoing engine) is fully modeled.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount_from_burden_counters_on_self": True})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"kind": "burden", "amount": 1}),
                EffectSpec("draw", {"count_selector": "burden_counters_on_self"}),
            ],
            cost={"taps_self": True},
        ),
    ]


register("The One Ring", _the_one_ring)


def _frodo_saurons_bane() -> list[AbilitySpec]:
    """{W/B}{W/B}: If Frodo is a Citizen, it becomes a Halfling Scout with
    base power and toughness 2/3 and lifelink.
    {B}{B}{B}: If Frodo is a Scout, it becomes a Halfling Rogue with
    "Whenever this creature deals combat damage to a player, that player
    loses the game if the Ring has tempted you four or more times this
    game. Otherwise, the Ring tempts you."

    — RULE 205.1b's "becomes a copy-independent creature with a new type
    line", turned out to need no new engine primitive after all despite the
    BACKLOG's earlier read: it's a two-step RULE 613.6 standing conditional
    static, gated on the permanent's own progress, driven by a plain custom
    counter (``frodo_stage``, no whitelist restricts `AddCountersEffect`'s
    ``kind`` — a "level"/"class_level" counter in spirit, just not literally
    either mechanic).

    Each activated ability's own legality ("if Frodo is a Citizen/Scout")
    is `ActivationCost.activation_condition` (PAR-10) reading the same
    `source_counters` gate a static's `active_if` does, so activating out
    of order is simply illegal rather than a no-op. Its own effect is
    nothing but bumping the counter — the actual transformation lives in
    the two `static` specs below, each gated ``active_if: source_counters``
    with a **``min`` and no ``max``**, deliberately: both stay active once
    unlocked (not mutually-exclusive bands like a Leveler's tiers), so the
    Rogue-stage static — which never restates a P/T — doesn't need to; RULE
    613.7 timestamp layering keeps the still-active Scout static's own
    ``pt_set``/type-change-with-P/T (RULE 613.4's "becomes an X/Y creature"
    shape, ``type_change``'s own ``power``/``toughness`` params) under the
    Rogue static's later ``set_subtypes`` override, exactly matching the
    printed card.

    The granted Rogue-stage trigger's "that player loses the game … .
    Otherwise, the Ring tempts you." is a genuine if/else the engine had no
    shape for: `ConditionalEffect` only ever gated a single existing
    effect, with no "otherwise" branch, and `grant_triggered_ability`'s own
    ``grant_effects`` list was built via a bare `EffectRegistry.create`
    with no way to condition an entry at all. Closed generally rather than
    with a one-off: `continuous._build_grant_effect` now honours an
    optional per-entry ``condition`` key the same shape `EffectSpec.
    condition` already has, and `ConditionalEffect` gained the symmetric
    ``ring_tempted_at_most`` key alongside the existing ``ring_tempted_at_
    least`` — two independently-gated conditionals with complementary
    bounds standing in for one if/else, the same pattern the front face's
    own compound clause already established for AND rather than OR. "That
    player" (not "you") is `LoseGameTriggerDamagedPlayerEffect`, the
    player-flavoured mirror of `ExileTriggerDamagedCreatureEffect`'s
    "that creature" pronoun off the granted ability's own firing `DAMAGE`
    event, since Frodo's controller and the player he just hit are usually
    different people.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"kind": "frodo_stage", "amount": 1})],
            cost={
                "mana": "{W/B}{W/B}",
                "activation_condition": {"kind": "source_counters", "counter": "frodo_stage", "max": 0},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"kind": "frodo_stage", "amount": 1})],
            cost={
                "mana": "{B}{B}{B}",
                "activation_condition": {"kind": "source_counters", "counter": "frodo_stage", "min": 1, "max": 1},
            },
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("type_change", {
                    "set_subtypes": ["Halfling", "Scout"], "power": 2, "toughness": 3,
                    "active_if": {"kind": "source_counters", "counter": "frodo_stage", "min": 1},
                }),
                EffectSpec("grant_keyword", {
                    "affects": "self",
                    "keywords": ["lifelink"],
                    "active_if": {"kind": "source_counters", "counter": "frodo_stage", "min": 1},
                }),
            ],
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("type_change", {
                    "set_subtypes": ["Halfling", "Rogue"],
                    "active_if": {"kind": "source_counters", "counter": "frodo_stage", "min": 2},
                }),
                EffectSpec("grant_triggered_ability", {
                    "affects": "self",
                    "trigger_event": EventType.DAMAGE,
                    "filter": {"combat": True, "is_player": True},
                    "grant_effects": [
                        {
                            "type": "if_else",
                            "params": {
                                "condition": {"kind": "ring_tempted", "min": 4},
                                "then": [
                                    {"type": "lose_game_trigger_damaged_player",
                                     "params": {}},
                                ],
                                "else": [
                                    {"type": "the_ring_tempts_you", "params": {}},
                                ],
                            },
                        },
                    ],
                    "active_if": {"kind": "source_counters", "counter": "frodo_stage", "min": 2},
                }),
            ],
        ),
    ]


register("Frodo, Sauron's Bane", _frodo_saurons_bane)


# ---------------------------------------------------------------------------
# "Wyleth Equip" saved-deck-priority batch (continued)
# ---------------------------------------------------------------------------


def _ardenn_intrepid_archaeologist() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, you may attach any number
    of Auras and Equipment you control to target permanent or player.
    Partner (You can have two commanders if both have partner.)

    Simplified: narrowed to attaching *one* Aura/Equipment already
    attached to something you control, to another target creature you
    control — the "any number, freely among permanents or players" mass
    rearrange has no primitive (`AttachChosenEffect`, built for Halvar's
    own single-object clause, is the closest shape this engine has).
    (Partner is bound by the keyword catalogue automatically.)
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_chosen", {
                "what_kind": "attached_aura_or_equipment_you_control", "to_kind": "creature_you_control",
            })],
            # Bug report, 2026-09-04 (same typo as Sam, Loyal Attendant's own
            # entry): the real step name (`game/phases.py`) is "begin_combat",
            # not "combat" — this never matched, so the ability never fired.
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
            optional=True,
        ),
    ]


register("Ardenn, Intrepid Archaeologist", _ardenn_intrepid_archaeologist)


def _armored_skyhunter() -> list[AbilitySpec]:
    """Flying
    Whenever this creature attacks, look at the top six cards of your
    library. You may put an Aura or Equipment card from among them onto
    the battlefield. If an Equipment is put onto the battlefield this
    way, you may attach it to a creature you control. Put the rest of
    those cards on the bottom of your library in a random order.

    Simplified: the found Aura/Equipment enters unattached — the "you may
    attach it to a creature you control" follow-up isn't modeled (no
    "dig hit, then optionally attach what was just found" primitive), and
    the rest go to exile instead of a random spot on the bottom of the
    library (`dig_until`'s own supported rest destinations).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": {"type": ["Aura", "Equipment"]}, "hit_destination": "battlefield",
                "rest_destination": "exile",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Armored Skyhunter", _armored_skyhunter)


def _martial_coup() -> list[AbilitySpec]:
    """Create X 1/1 white Soldier creature tokens. If X is 5 or more,
    destroy all other creatures.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("create_token", {
                    "count": "x", "power": 1, "toughness": 1, "colors": ["W"],
                    "subtypes": ["Soldier"], "token_name": "Soldier",
                }),
                EffectSpec(
                    "destroy", {"selector": "all_creatures", "exclude_created": True},
                    condition={"source_x_paid_at_least": 5},
                ),
            ],
        ),
    ]


register("Martial Coup", _martial_coup)


def _masterwork_of_ingenuity() -> list[AbilitySpec]:
    """You may have this Equipment enter as a copy of any Equipment on the
    battlefield.

    Simplified: widened to "any permanent" — the target-kind vocabulary
    (docs/11 §10) has no Equipment-only restriction, matching the same
    documented looseness `Clever Impersonator`'s own catalogue entry
    already accepts for "any nonland permanent".
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "permanent"})],
        ),
    ]


register("Masterwork of Ingenuity", _masterwork_of_ingenuity)


def _raph_and_leo_sibling_rivals() -> list[AbilitySpec]:
    """Whenever Raph & Leo attack, if it's the first combat phase of the
    turn, untap one or two target attacking creatures. After this phase,
    there is an additional combat phase.

    MEC-28: the same RULE 603.4 intervening-if extra-combat template as
    Finest Hour/Karlach, Fury of Avernus/Raiyuu, Storm's Edge (all four now
    parser-`MODELED`) — hand-authored here only because of its own
    remaining gap, a genuine RULE 601.2c "N or M target X" range. ENG-30
    built that primitive (`targeting.TargetSpec.count_max`) — this entry now
    uses the real "one or two" range (``count=1, count_max=2``) instead of
    the single-mandatory-target simplification it shipped with.

    Still hand-authored, not deleted in favor of the oracle-text parser: the
    parser's shared multi-target grammar (`catalogue.handlers.
    _MULTI_TARGET_ROWS`) has no row for a *targeted* "attacking creatures"
    phrase — only the untargeted mass-selector "untap all attacking
    creatures" form ENG-29 built. Adding one is real, separate scope (a new
    row plus threading a `creature_filter` through `_multi_target_params`,
    which has no such param today) that only this one card would exercise;
    left for whenever a second real card needs it rather than built
    speculatively here.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "tap",
                    {
                        "target_kind": "creature", "creature_filter": {"attacking": True}, "untap": True,
                        "count": 1, "count_max": 2,
                    },
                    condition={"is_first_combat_phase": True},
                ),
                EffectSpec("extra_combat_phase", {}, condition={"is_first_combat_phase": True}),
            ],
            trigger={"event": "ATTACKS", "condition": {"subject": "self"}},
        ),
    ]


register("Raph & Leo, Sibling Rivals", _raph_and_leo_sibling_rivals)


def _balthier_and_fran() -> list[AbilitySpec]:
    """Reach
    Vehicles you control get +1/+1 and have vigilance and reach.
    Whenever a Vehicle crewed by Balthier and Fran this turn attacks, if
    it's the first combat phase of the turn, you may pay {1}{R}{G}. If you
    do, after this phase, there is an additional combat phase.

    MEC-29: the last of MEC-28's own five-card list, closed by building the
    two primitives its own diagnosis named. RULE 702.122 **Crew** as real
    engine state (`ActivationCost.crew_power`, `GameEngine._resolve_crew_
    cost`/`_crew_pool`, `GameObject.crewed_by_ids`, `effect_binder._crew_
    activated_ability`) — "Crew N" had been parser-*recognized* the whole
    time (the coverage gate's own keyword catalogue), just never bound to
    behaviour anywhere in `game/`/`models/` (`grep -rn "crewed_by"` found
    nothing before this), the same "recognized but inert" gap Cycling had
    before PAR-9 — and a new `"crewed_by_self"` RULE 603.1 group-subject
    trigger-condition key (`effect_binder._build_group_ok`) reading it live
    off the board. Hand-authored here rather than left to the oracle-text
    parser: "a Vehicle crewed by ~ this turn attacks" is a genuinely
    singleton phrasing (`parser_probe.py cards 'crewed by'` finds exactly
    one other cached card, Mighty Servant of Leuk-o, printing a completely
    different "crewed by exactly N creatures" template) not worth a
    dedicated grammar row for.

    The anthem clause is duplicated here rather than left to the parser for
    a narrower reason: it already parses correctly on its own (a real fix
    below), but registering this card for its trigger clause means
    `ability_catalogue.specs_for` takes *all* of this card's non-keyword
    abilities from the registry instead — "Reach" alone still auto-attaches
    from `parse_keywords`, which runs regardless of registration.

    Building Crew surfaced two real, previously-invisible bugs, both fixed
    at the root rather than worked around for this one card:

    1. `_ANTHEM_RE`'s `_scope` (`parser/oracle/catalogue/static_handlers.
       py`) had no non-creature-**subtype** guard the way `_NONCREATURE_
       TYPES` already gives it for non-creature main *types* ("Artifacts
       you control…"), so a bare "Vehicles" scope silently fell through to
       the ordinary creature-subtype reading and produced ``affects:
       creatures_you_control`` — wrong, since a Vehicle isn't a creature
       until crewed, so the anthem would have excluded every uncrewed
       Vehicle it's printed to buff. No real card had ever reached this
       shape's *whole* card fully-MODELED before, so it silently shipped
       wrong without ever showing up as a coverage regression. Fixed with
       `_ARTIFACT_SUBTYPES`/`_vehicle_scope_params`, reused by
       `_GRANT_RE`/`_QUOTED_GRANT_RE`'s existing PAR-3 fallback chain too —
       any other "Vehicles [you control] get/have …" card benefits for
       free, not just this one.
    2. A freshly crewed Vehicle had no power/toughness at all —
       `Card.__init__`'s own invariant refuses P/T on a noncreature, so a
       Vehicle's *printed* P/T (RULE 208.1: some noncreature permanents,
       Vehicles chief among them, print P/T that matters once something
       else makes them a creature) had never been captured anywhere in
       this engine's `Card` model. Without it, `type_change`'s "becomes an
       artifact creature" grant left the crewed Vehicle at 0/0, dying to
       RULE 704.5f the instant the next state-based action check ran —
       Crew would have bound correctly while being unusable in any real
       game. Fixed with `Card.vehicle_power`/`vehicle_toughness`
       (deliberately separate fields, not a relaxation of the existing
       invariant, so every reader that treats "power is not None" as a
       creature check stays correct), populated by `scryfall_client.
       card_from_scryfall_data` for any noncreature Vehicle and read by
       `effect_binder._crew_activated_ability` when building the grant.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "power": 1, "toughness": 1,
                    "affects": "artifacts_you_control", "subtype": "Vehicle",
                }),
                EffectSpec("grant_keyword", {
                    "keywords": ["vigilance", "reach"],
                    "affects": "artifacts_you_control", "subtype": "Vehicle",
                }),
            ],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "pay_cost_then",
                    {
                        "cost": "{1}{R}{G}",
                        "effects": [{"type": "extra_combat_phase", "params": {}}],
                    },
                    condition={"is_first_combat_phase": True},
                ),
            ],
            trigger={
                "event": "ATTACKS",
                "condition": {"subject": "group", "subtypes": ["vehicle"], "crewed_by_self": True},
            },
        ),
    ]


register("Balthier and Fran", _balthier_and_fran)


def _tifa_martial_artist() -> list[AbilitySpec]:
    """Melee (Whenever this creature attacks, it gets +1/+1 until end of
    turn for each opponent you attacked this combat.)
    Whenever one or more creatures you control with power 7 or greater deal
    combat damage to a player, untap all creatures you control. If it's the
    first combat phase of your turn, there is an additional combat phase
    after this phase.

    MEC-29: the other half of MEC-28's own five-card list, closed by
    building the two primitives its own diagnosis named — though the
    diagnosis itself needed correcting first (this repo's standing rule:
    verify a "needs a new primitive" claim against current code before
    trusting it, even when the claim is this ticket's own). RULE 603.1's
    DAMAGE-subject group scoping for "you control" already existed
    (`_GROUP_CONTROLLER_EVENT_KEYS["DAMAGE"]`, built for Bident of Thassa/
    Deepfathom Skulker's own "a creature you control deals combat damage to
    a player") — the real, still-open gap was the **"one or more"**
    quantifier: RULE 603.1's ordinary group subject fires once *per
    creature*, but "one or more creatures … deal combat damage" describes a
    single condition about the whole combat damage step. This engine
    already has the identical shape solved once, for a different verb: RULE
    506.4's "a player attacks you **with one or more creatures**" is
    exactly why `EventType.PLAYER_ATTACKED` exists instead of reusing the
    per-declaration `ATTACKS` event (see that event's own docstring) — two
    creatures qualifying simultaneously must trigger this ability *once*,
    not twice (this card's own payoff, an extra combat phase, would
    otherwise double up per RULE 508.6/509.5's simultaneous combat damage).
    Built the combat-damage sibling the same way:
    `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`
    (`GameEngine._apply_combat_damage`), fired once per (contributing
    creatures' controller, player hit) pair after a damage step, carrying
    ``max_power`` — the highest power among that pair's contributors — for
    a new `"contributor_power_at_least"` trigger-condition threshold
    (`effect_binder._trigger_condition`, mirroring the existing
    ``spell_mana_value_at_most`` idiom) to check: the aggregate event names
    no single acting object a `"group"` condition's own per-object
    ``min_power`` filter could read off the board.

    Hand-authored rather than left to the oracle-text parser: this
    "one or more `<type>` you control with power `<n>` or greater deal
    combat damage to a player" template is, per `parser_probe.py cards
    'deal combat damage to a player'`, printed on exactly this one cached
    card — not worth a dedicated grammar row for a single user. "If it's
    the first combat phase of **your** turn" (not "…of **the** turn",
    `_FIRST_COMBAT_PHASE_CONDITION_RE`'s own exact wording) rides the same
    RULE 603.4 intervening-if `ConditionalEffect` key
    (``is_first_combat_phase``) under a harmless wording variant: a combat
    phase only ever happens on its own active player's turn, so "the turn"
    and "your turn" name the same thing for every real card printing
    either.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("tap", {"selector": "creatures_you_control", "untap": True}),
                EffectSpec("extra_combat_phase", {}, condition={"is_first_combat_phase": True}),
            ],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "you"},
                "contributor_power_at_least": 7,
            },
        ),
    ]


register("Tifa, Martial Artist", _tifa_martial_artist)


def _sokenzan_crucible_of_defiance() -> list[AbilitySpec]:
    """{T}: Add {R}.
    Channel — {3}{R}, Discard this card: Create two 1/1 colorless Spirit
    creature tokens. They gain haste until end of turn. This ability
    costs {1} less to activate for each legendary creature you control.

    (The mana ability is bound automatically off the printed "{T}: Add
    {R}." text.) Simplified: the "{1} less for each legendary creature"
    cost reduction isn't modeled (`continuous.activation_cost_reduction_
    for` has no per-count scaling for a hand-zone Channel-style cost yet,
    only a flat subtype-scoped one) — Channel itself (offered and payable
    from hand, discarding this card as its cost) is fully modeled at its
    full printed price.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 2, "power": 1, "toughness": 1, "colors": [],
                "subtypes": ["Spirit"], "keywords": ["haste"], "token_name": "Spirit",
            })],
            cost={"mana": "{3}{R}", "discard_self": True},
        ),
    ]


register("Sokenzan, Crucible of Defiance", _sokenzan_crucible_of_defiance)


def _valakut_awakening() -> list[AbilitySpec]:
    """Put any number of cards from your hand on the bottom of your
    library, then draw that many cards plus one.

    Simplified: narrowed to "draw a card" — no primitive puts a player-
    chosen number of hand cards on the bottom of the library paired with a
    scaled draw yet (`PutHandCardsOnTopEffect` is a fixed count, to the
    top, with no paired draw).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("draw", {"count": 1})],
        ),
    ]


register("Valakut Awakening", _valakut_awakening)
register("Valakut Awakening // Valakut Stoneforge", _valakut_awakening)


def _boseiju_who_endures() -> list[AbilitySpec]:
    """{T}: Add {G}.
    Channel — {1}{G}, Discard this card: Destroy target artifact,
    enchantment, or nonbasic land an opponent controls. That player may
    search their library for a land card with a basic land type, put it
    onto the battlefield, then shuffle. This ability costs {1} less to
    activate for each legendary creature you control.

    — Eliferate deck batch. The mana ability is bound automatically off
    the printed "{T}: Add {G}." text. Same Channel/`dynamic_reduction`
    shape as `Eiganjo, Seat of the Empire`'s own per-legendary-creature
    discount (`costs.ActivationCost.dynamic_reduction`'s
    `legendary_creatures_you_control` count_selector). The destroy+search
    body is a new primitive, `effects.
    DestroyControllerMaySearchBasicLandEffect` — pairs `RulesEngine.destroy`
    (unlike Winds of Abandon's exile-then-search sibling, so an
    indestructible/regeneration-shielded target survives) with an
    *optional*, untapped basic-land search offered to the destroyed
    permanent's own controller. `target_kind` drops the "an opponent
    controls" restriction — the same documented simplification
    `ExileControllerSearchesBasicLandEffect` already uses (no target kind
    carries an ownership exclusion yet).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("destroy_controller_may_search_basic_land", {})],
            cost={
                "text": "{1}{G}, Discard this card",
                "dynamic_reduction": {
                    "count_selector": "legendary_creatures_you_control",
                    "generic_per": 1,
                },
            },
        ),
    ]


register("Boseiju, Who Endures", _boseiju_who_endures)


def _otawara_soaring_city() -> list[AbilitySpec]:
    """{T}: Add {U}.
    Channel — {3}{U}, Discard this card: Return target artifact, creature,
    enchantment, or planeswalker to its owner's hand. This ability costs
    {1} less to activate for each legendary creature you control.

    Same Channel/`dynamic_reduction` shape as `Eiganjo, Seat of the
    Empire`/`Boseiju, Who Endures` (MEC-12) — the mana ability binds
    automatically off the printed "{T}: Add {U}." text, and the per-
    legendary-creature discount is `costs.ActivationCost.dynamic_reduction`
    with the same `legendary_creatures_you_control` count_selector. The
    bounce targets `targeting.py`'s new `artifact_creature_enchantment_
    or_planeswalker` kind (MEC-12) — the four-permanent-type union this
    card's own printed wording needs, not yet used by any other card.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec(
                "return_to_hand",
                {"target_kind": "artifact_creature_enchantment_or_planeswalker"},
            )],
            cost={
                "text": "{3}{U}, Discard this card",
                "dynamic_reduction": {
                    "count_selector": "legendary_creatures_you_control",
                    "generic_per": 1,
                },
            },
        ),
    ]


register("Otawara, Soaring City", _otawara_soaring_city)


def _takenuma_abandoned_mire() -> list[AbilitySpec]:
    """{T}: Add {B}.
    Channel — {3}{B}, Discard this card: Mill three cards, then return a
    creature or planeswalker card from your graveyard to your hand. This
    ability costs {1} less to activate for each legendary creature you
    control.

    — Eliferate deck batch, same Channel/`dynamic_reduction` shape as
    `Boseiju, Who Endures`/`Eiganjo, Seat of the Empire`. "Return a creature
    or planeswalker card from your graveyard to your hand" is untargeted
    RAW (no "target"), but reuses `ReturnFromGraveyardEffect`'s own new
    `graveyard_creature_or_planeswalker` kind (`targeting.py`'s
    `_GRAVEYARD_TYPE_FILTERS`) as a targeted choice instead — the same
    targeted-vs-untargeted-choice simplification this engine's whole
    Regrowth-adjacent recursion family already makes.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("mill", {"count": 3}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature_or_planeswalker",
                    "destination": "hand",
                }),
            ],
            cost={
                "text": "{3}{B}, Discard this card",
                "dynamic_reduction": {
                    "count_selector": "legendary_creatures_you_control",
                    "generic_per": 1,
                },
            },
        ),
    ]


register("Takenuma, Abandoned Mire", _takenuma_abandoned_mire)


def _dwynen_gilt_leaf_daen() -> list[AbilitySpec]:
    """Reach
    Other Elf creatures you control get +1/+1.
    Whenever Dwynen attacks, you gain 1 life for each attacking Elf you
    control.

    — Eliferate deck batch. Reach and the anthem already parse; the attack
    trigger's amount is `continuous.count_selector`'s new
    `attacking_creatures_you_control_of_type_<x>` (`GainLifeEffect.
    count_selector`) — the attacking-scoped sibling of the existing
    `creatures_you_control_of_type_` selector.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {
                "count_selector": "attacking_creatures_you_control_of_type_elf",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Dwynen, Gilt-Leaf Daen", _dwynen_gilt_leaf_daen)


def _elvish_warmaster() -> list[AbilitySpec]:
    """Whenever one or more other Elves you control enter, create a 1/1
    green Elf Warrior creature token. This ability triggers only once each
    turn.
    {5}{G}{G}: Elves you control get +2/+2 and gain deathtouch until end of
    turn.

    — Eliferate deck batch. The pump ability already parses; the ETB
    trigger is the same "whenever one or more other X you control enter…
    triggers only once each turn" shape `Merry, Warden of Isengard` already
    uses for artifacts, just subtype-scoped to Elf instead of type-scoped
    to artifact.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Elf", "Warrior"], "keywords": [], "token_name": "Elf Warrior",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "subtypes": ["elf"],
                    "controller": "you", "other": True,
                },
                "limit": True,
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 2, "toughness": 2, "keywords": ["deathtouch"],
                "selector": "creatures_you_control_of_type_elf",
            })],
            cost={"text": "{5}{G}{G}"},
        ),
    ]


register("Elvish Warmaster", _elvish_warmaster)


def _morcants_loyalist() -> list[AbilitySpec]:
    """Other Elves you control get +1/+1.
    When this creature dies, return another target Elf card from your
    graveyard to your hand.

    — Eliferate deck batch. The anthem already parses; the dies trigger
    reuses `ReturnFromGraveyardEffect`'s new `subtype` filter
    (`targeting.TargetSpec.subtype`) scoped to "elf", which also excludes
    this card's own now-in-the-graveyard copy the same way an ordinary
    battlefield "another" target excludes its own source.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "subtype": "elf",
                "destination": "hand",
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Morcant's Loyalist", _morcants_loyalist)


def _elvish_harbinger() -> list[AbilitySpec]:
    """When this creature enters, you may search your library for an Elf
    card, reveal it, then shuffle and put that card on top.
    {T}: Add one mana of any color.

    — Eliferate deck batch. The mana ability is bound automatically off the
    printed "{T}: Add one mana of any color." text; the ETB tutor is a
    plain `SearchLibraryEffect` — an optional, `{"type": "Elf"}`-filtered
    library search to the top of the library, the same "reveal" simplification
    (not separately modeled) every other tutor in this catalogue makes.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Elf"}, "destination": "library_top", "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Elvish Harbinger", _elvish_harbinger)


def _elvish_guidance() -> list[AbilitySpec]:
    """Enchant land
    Whenever enchanted land is tapped for mana, its controller adds an
    additional {G} for each Elf on the battlefield.

    — Eliferate deck batch. `Wild Growth`'s own triggered-mana-ability
    shape (RULE 605.1b/605.4), just with a board-scaled amount instead of a
    flat one: `AddManaEffect.amount_selector`'s new unscoped
    `creatures_of_type_<x>` count (`continuous.count_selector`) rather
    than the `_you_control`-scoped form every existing consumer used —
    "on the battlefield" here means every Elf, regardless of controller.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {
                "color": "G", "amount_selector": "creatures_of_type_elf",
                "recipient": "event_controller",
            })],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "attached_permanent"},
                "mana_ability": True,
            },
        ),
    ]


register("Elvish Guidance", _elvish_guidance)


def _vanquishers_banner() -> list[AbilitySpec]:
    """As this artifact enters, choose a creature type.
    Creatures you control of the chosen type get +1/+1.
    Whenever you cast a creature spell of the chosen type, draw a card.

    — Eliferate deck batch. The ETB type choice and the anthem parse on
    their own (`choose_creature_type_on_enter`/`anthem` with
    `subtype_from_source`) — reproduced here verbatim (whole-card hand-
    authoring replaces the parser's own specs entirely, `specs_for`'s
    registry-wins precedence, so a partial registration would silently
    drop them) — alongside the one clause that didn't: the cast trigger.
    That's a new `effect_binder` predicate, `"cast_of_chosen_type"` —
    reads `GameObject.chosen_type` live at check time (unlike the
    fixed-at-bind `"subtypes"` group filter, the wanted type isn't known
    until the ETB choice resolves) against the live-looked-up cast spell's
    own printed subtypes.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "power": 1, "toughness": 1, "affects": "creatures_you_control",
                "subtype_from_source": True,
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "type": "creature", "controller": "you"},
                "cast_of_chosen_type": True,
            },
        ),
    ]


register("Vanquisher's Banner", _vanquishers_banner)


def _realmwalker() -> list[AbilitySpec]:
    """Changeling (This card is every creature type.)
    As this creature enters, choose a creature type.
    You may look at the top card of your library any time.
    You may cast creature spells of the chosen type from the top of your
    library.

    — Eliferate deck batch. Changeling (keyword) and the ETB type choice
    (`choose_creature_type_on_enter`) already parse on their own —
    reproduced here verbatim, since whole-card hand-authoring replaces the
    parser's own output wholesale (`specs_for`'s registry-wins precedence).
    The standing permission is `top_library_permission`'s new
    `chosen_type_creature_only` flag — the same `Oracle of Mul Daya`/
    `Glarb, Calamity's Augur` family, narrowed by `GameObject.chosen_type`
    read live (`game/top_library.py`) instead of a fixed mana-value/
    noncreature gate.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {
                "look": True, "cast_spells": True, "chosen_type_creature_only": True,
            })],
        ),
    ]


register("Realmwalker", _realmwalker)


def _selfless_safewright() -> list[AbilitySpec]:
    """Flash
    Convoke (Your creatures can help cast this spell. Each creature you tap
    while casting this spell pays for {1} or one mana of that creature's
    color.)
    When this creature enters, choose a creature type. Other permanents you
    control of that type gain hexproof and indestructible until end of
    turn.

    — Eliferate deck batch. Flash/Convoke come from the RULE 702 keyword
    catalogue automatically. The ETB clause is a *resolve-time* "choose a
    creature type" (RulesEngine._request_choose_creature_type_grant — see
    its docstring for why this is a different primitive from RULE 601.2b's
    as-it-enters `choose_creature_type_on_enter`), immediately followed by
    the grant (`grant_keywords_to_chosen_type_until_eot`) as its own
    ``then_specs`` tail, parked/resumed by the existing RULE 608.2
    suspended-resolution machinery (`GameState.deferred_effects`) rather
    than any new continuation plumbing.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("_request_choose_creature_type_grant", {
                "then_specs": [
                    {
                        "type": "grant_keywords_to_chosen_type_until_eot",
                        "params": {"keywords": ["hexproof", "indestructible"]},
                    },
                ],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Selfless Safewright", _selfless_safewright)


def _roaming_throne() -> list[AbilitySpec]:
    """Ward {2}
    As this creature enters, choose a creature type.
    This creature is the chosen type in addition to its other types.
    If a triggered ability of another creature you control of the chosen
    type triggers, it triggers an additional time.

    — Eliferate deck batch, closing the one remaining gap the 2026-08-05
    Eliferate/Keywords Showcase batch deliberately left open (Done_Backend.md
    called out "Roaming Throne's trigger-doubling" by name). Ward, the ETB
    type choice, and the self type-grant already parse on their own —
    reproduced here verbatim (whole-card hand-authoring replaces the
    parser's own output wholesale). The doubling itself is a genuinely new
    RULE 603.3d primitive: `effects.TriggerDoublerEffect`, a continuous
    marker (no `apply()` behaviour of its own, the same
    `TopLibraryPermissionEffect`/`CantBeCounteredEffect` idiom) that
    `continuous.trigger_doubler_bonus` scans for from `game/rules/
    triggers_mixin.py`'s `_collect_triggers` — the one place every
    permanent's own triggered ability gets placed on the stack — which now
    appends `1 + bonus` copies instead of always exactly one. Placed as
    independent extra copies (not a single ability that "resolves twice")
    so 2+ pending copies are still separately orderable (RULE 603.3b) if a
    second trigger is also waiting.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {"affects": "self", "add_subtypes_from_source": True})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {})],
        ),
    ]


register("Roaming Throne", _roaming_throne)


def _vraska_betrayals_sting() -> list[AbilitySpec]:
    """Compleated ({B/P} can be paid with {B} or 2 life.)
    0: You draw a card and lose 1 life. Proliferate.
    −2: Target creature becomes a Treasure artifact with "{T}: Add one
    mana of any color" and loses all other card types and abilities.
    −9: If target player has fewer than nine poison counters, they get a
    number of poison counters equal to the difference.

    — Eliferate deck batch. Compleated (keyword) and "0:" already parse on
    their own — reproduced here verbatim (whole-card hand-authoring
    replaces the parser's own output wholesale).

    "−2:" is a genuinely permanent (RAW has no "until") characteristic
    overwrite, so it's two chained `grant_until` effects at
    ``duration="rest_of_game"`` rather than a `temp_*`-field pump: the
    first carries the real target and applies `type_change`'s new
    `remove_types`/`add_types`/`add_subtypes` (RULE 613.7f's own
    creature-type-removal path, `GameObject._removed_types`, generalized
    from the Reconfigure-only special case it used to be); the second
    reuses that same target via `previous_subject` (the "Tap target
    land. **It** doesn't untap…" pronoun idiom) to layer on
    `remove_all_abilities` (RULE 613.7f's Humility/Dress Down strip) and
    `grant_mana_ability`. **Documented simplification**: the granted mana
    ability is modeled as a plain "{T}: Add one mana of any color" rather
    than "{T}, Sacrifice this artifact: …" — `granted_mana_options`
    (`GameObject`'s own layer-6 grant list `mana_abilities_for` reads once
    `loses_all_abilities` is set) only ever carries a tap cost, and
    `Card.is_artifact` itself (the printed, immutable characteristic a
    few older code paths read directly rather than through the
    layer-aware `type_words`/`is_creature`) isn't flipped — a spell that
    specifically targets "artifact" via one of those paths won't
    recognize this creature as one, while every layer-aware consumer is
    correct.

    "−9:" is `top_up_player_counter` — a threshold top-up (RULE 122.1)
    rather than a flat amount, new alongside the flat `add_player_counters`
    every other poison-granting card already used.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("lose_life", {"amount": 1}),
                EffectSpec("proliferate", {}),
            ],
            cost={"loyalty": 0},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "duration": "rest_of_game", "target_kind": "creature",
                    "static": {
                        "type": "type_change",
                        "params": {
                            "add_types": ["artifact"], "remove_types": ["creature"],
                            "add_subtypes": ["Treasure"],
                        },
                    },
                }),
                EffectSpec("grant_until", {
                    "duration": "rest_of_game", "previous_subject": True,
                    "static": {"type": "remove_all_abilities", "params": {}},
                }),
                EffectSpec("grant_until", {
                    "duration": "rest_of_game", "previous_subject": True,
                    "static": {"type": "grant_mana_ability", "params": {"mana": [{"ANY": 1}]}},
                }),
            ],
            cost={"loyalty": -2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("top_up_player_counter", {"kind": "poison", "threshold": 9})],
            cost={"loyalty": -9},
        ),
    ]


register("Vraska, Betrayal's Sting", _vraska_betrayals_sting)


def _vraska_golgari_queen() -> list[AbilitySpec]:
    """+2: You may sacrifice another permanent. If you do, you gain 1 life
    and draw a card.
    −3: Destroy target nonland permanent with mana value 3 or less.
    −9: You get an emblem with "Whenever a creature you control deals
    combat damage to a player, that player loses the game."

    — Eliferate deck batch. "−3:" already parses (destroy, max_mana_value
    3) — reproduced here verbatim. "+2:" is the shipped `choose_objects`
    wrapper (`ChooseObjectsEffect`, the general "you may sacrifice/tap/
    return a permanent you control" chooser — Tevesh Szat's own "you may
    sacrifice another creature or planeswalker" precedent) with a `then`
    tail; "−9:" is the same quoted-emblem-at-loyalty shape `Tyvar Kell`'s
    own −6 introduced (a genuine nested `AbilitySpec`, since there's no
    card text to recursively parse the way the oracle-text front-end's
    `_emblem_ability_spec` does for a spell/triggered clause).
    """
    emblem_ability = AbilitySpec(
        "triggered",
        [EffectSpec("lose_game_trigger_damaged_player", {})],
        trigger={
            "event": EventType.DAMAGE,
            "condition": {"subject": "group", "type": "creature", "controller": "you", "combat": True},
        },
    )
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("choose_objects", {
                "action": "sacrifice", "what": "permanent", "optional": True, "exclude_self": True,
                "then": [
                    {"type": "gain_life", "params": {"amount": 1}},
                    {"type": "draw", "params": {"count": 1}},
                ],
            })],
            cost={"loyalty": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("destroy", {"target_kind": "permanent", "max_mana_value": 3})],
            cost={"loyalty": -3},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {"ability": emblem_ability.to_dict()})],
            cost={"loyalty": -9},
        ),
    ]


register("Vraska, Golgari Queen", _vraska_golgari_queen)


def _vraskas_fall() -> list[AbilitySpec]:
    """Each opponent sacrifices a creature or planeswalker of their choice
    and gets a poison counter.

    — Eliferate deck batch. `SacrificeEffect`'s existing `selector=
    "each_opponent"` (Professor Onyx's −3 precedent) already opens a real
    RULE 601.2c-style choice *for that opponent* rather than an auto-pick
    when ``greatest_power`` isn't set, and `what="creature_or_planeswalker"`
    is the one compound sacrifice-type word this catalogue already
    recognizes (Tevesh Szat). The poison half is the plain
    `add_player_counters` every other poison-granting card uses, same
    `selector="each_opponent"`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("sacrifice", {
                    "selector": "each_opponent", "what": "creature_or_planeswalker",
                }),
                EffectSpec("add_player_counters", {
                    "selector": "each_opponent", "kind": "poison", "amount": 1,
                }),
            ],
        ),
    ]


register("Vraska's Fall", _vraskas_fall)


def _glissa_sunslayer() -> list[AbilitySpec]:
    """First strike, deathtouch
    Whenever Glissa Sunslayer deals combat damage to a player, choose one —
    • You draw a card and lose 1 life.
    • Destroy target enchantment.
    • Remove up to three counters from target permanent.

    — Eliferate deck batch. First strike/deathtouch come from the RULE 702
    keyword catalogue automatically. The modal trigger reuses `Bloodforged
    Battle-Axe`'s own "deals combat damage to a player" trigger shape
    (`filter={"combat": True, "is_player": True}`) plus a `triggered`-kind
    `modes` block — RULE 603.3's own "a triggered ability's mode(s) chosen
    as it's put on the stack" path, already shipped and used by parsed
    modal triggers, just not yet by a hand-authored one. The third mode's
    `remove_counters` with `max_count` is the exact primitive
    `RemoveCountersEffect`'s own docstring already names Glissa Sunslayer
    for — built for this card, never previously wired to it.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
            modes={
                "options": [
                    [
                        EffectSpec("draw", {"count": 1}),
                        EffectSpec("lose_life", {"amount": 1}),
                    ],
                    [EffectSpec("destroy", {"target_kind": "enchantment"})],
                    [EffectSpec("remove_counters", {"target_kind": "permanent", "max_count": 3})],
                ],
                "descriptions": [
                    "Du ziehst eine Karte und verlierst 1 Leben.",
                    "Zerstöre eine Zielverzauberung.",
                    "Entferne bis zu drei Marken von einer bleibenden Zielkarte.",
                ],
            },
        ),
    ]


register("Glissa Sunslayer", _glissa_sunslayer)


def _glissa_herald_of_predation() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, choose one —
    • Incubate 2 twice. (To incubate 2, create an Incubator token with two
      +1/+1 counters on it and "{2}: Transform this token." It transforms
      into a 0/0 Phyrexian artifact creature.)
    • Transform all Incubator tokens you control.
    • Phyrexians you control gain first strike and deathtouch until end of
      turn.

    — Eliferate deck batch. Incubate (RULE 701.51-adjacent) is modeled as
    a genuine two-state token, the same way morph/manifest's face-down
    permanents are: "Incubate 2 twice" creates two power/toughness-less
    "Incubator" tokens (`services.token_database.synthesize_token_card`
    makes a bare token with no P/T a plain noncreature "Token Artifact"
    on its own) each carrying 2 +1/+1 counters (`create_token`'s new
    `extra_counters` param), and the standalone `Incubator` catalogue
    entry below binds onto every one of them (`bind_from_catalogue` reads
    a token's abilities off its own name, "exactly like a real
    permanent") its own "{2}: Transform this token" — a permanent
    (RAW: no "until") `type_change` animation into a 0/0 Phyrexian
    artifact creature, so its counters do the rest. The second mode,
    "transform all Incubator tokens you control", reuses that exact same
    animation en masse via the new `transform_named_tokens` primitive
    rather than a bespoke one-off. The third mode is a plain `pump` with a
    subtype-scoped `selector`, the same `creatures_you_control_of_type_<x>`
    vocabulary `Elvish Warmaster`'s pump ability already uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                "phase_relation": "you",
            },
            modes={
                "options": [
                    [EffectSpec("create_token", {
                        "count": 2, "token_name": "Incubator",
                        "extra_counters": {"kind": "+1/+1", "count": 2},
                    })],
                    [EffectSpec("transform_named_tokens", {
                        "token_name": "Incubator", "add_types": ["creature"],
                        "add_subtypes": ["Phyrexian"], "power": 0, "toughness": 0,
                    })],
                    [EffectSpec("pump", {
                        "selector": "creatures_you_control_of_type_phyrexian",
                        "keywords": ["first_strike", "deathtouch"],
                    })],
                ],
                "descriptions": [
                    "Inkubiere 2 zweimal.",
                    "Transformiere alle Inkubator-Spielsteine unter deiner Kontrolle.",
                    "Phyrexianer unter deiner Kontrolle erhalten Erstschlag und "
                    "Todesberührung bis zum Ende des Zuges.",
                ],
            },
        ),
    ]


register("Glissa, Herald of Predation", _glissa_herald_of_predation)


