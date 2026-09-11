"""Stack interaction, protection, sacrifice, and control entries."""

from __future__ import annotations

from ...models.game.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

def _geistwave() -> list[AbilitySpec]:
    """Return target nonland permanent to its owner's hand. If you
    controlled that permanent, draw a card.

    — Geistwave. The bounce and rider are an ordinary sequence: the draw
    names the announced object through `previous_target`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_to_hand", {"target_kind": "nonland_permanent"}),
                EffectSpec(
                    "draw", {"count": 1},
                    condition={"kind": "is_you", "of": "previous_target"},
                ),
            ],
        )
    ]


register("Geistwave", _geistwave)


def _paradigm_shift() -> list[AbilitySpec]:
    """Exile all cards from your library. Then shuffle your graveyard into
    your library.

    — Paradigm Shift. Two new, generically reusable effects this batch:
    `ExileLibraryEffect` (an untargeted hidden-zone-to-exile mass move,
    distinct from `ExileEffect.selector`'s battlefield-only board-wipe
    vocabulary) and `ShuffleGraveyardIntoLibraryEffect` (the graveyard-only
    sibling of `RulesEngine.shuffle_hand_and_graveyard_into_library`'s
    "hand AND graveyard" wheel template).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_library", {}), EffectSpec("shuffle_graveyard_into_library", {})],
        )
    ]


register("Paradigm Shift", _paradigm_shift)


def _endurance() -> list[AbilitySpec]:
    """Flash. Reach. When this creature enters, up to one target player
    puts all the cards from their graveyard on the bottom of their library
    in a random order. Evoke—Exile a green card from your hand.

    — Endurance. Flash/Reach are keywords, already covered by the parser's
    keyword catalogue. A new `GraveyardToLibraryBottomRandomEffect` this
    batch (RULE 701.20-adjacent — randomizes only the moved batch's own
    relative order, leaving the rest of the library's order alone). MEC-65
    binds its printed exile-a-green-card Evoke cost through the shared RULE
    702.74 alternate-cast path.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("graveyard_to_library_bottom_random", {
                "target_kind": "player", "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Endurance", _endurance)


def _borne_upon_a_wind() -> list[AbilitySpec]:
    """You may cast spells this turn as though they had flash. Draw a card.

    — Borne Upon a Wind. A new `GrantFlashUntilEndOfTurnEffect` this batch:
    stamps `GameState.temp_flash_until_turn` for the caster, consulted by
    `GameEngine.can_cast`'s existing RULE 702.8b Flash timing gate
    alongside the printed-keyword/`conditional_flash` checks it already
    made.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("grant_flash_until_eot", {}), EffectSpec("draw", {"count": 1})],
        )
    ]


register("Borne Upon a Wind", _borne_upon_a_wind)


# ---------------------------------------------------------------------------
# Batch 14 — "destroy/counter target X; its controller creates a token"
# cluster and further cube singles whose effect primitives already exist.
# ---------------------------------------------------------------------------


def _pongify() -> list[AbilitySpec]:
    """Destroy target creature. It can't be regenerated. Its controller
    creates a 3/3 green Ape creature token.

    — Pongify. ENG-37 B3: a `seq` of `destroy` (``can_be_regenerated=False``
    for the "can't be regenerated" clause) then `create_token` with
    ``creators="previous_target_controller"``, retiring the fused
    ``destroy_create_token``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "destroy", "params": {
                    "target_kind": "creature", "can_be_regenerated": False,
                }},
                {"type": "create_token", "params": {
                    "power": 3, "toughness": 3, "colors": ["G"],
                    "subtypes": ["Ape"],
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Pongify", _pongify)


def _rapid_hybridization() -> list[AbilitySpec]:
    """Destroy target creature. It can't be regenerated. That creature's
    controller creates a 3/3 green Frog Lizard creature token.

    — Rapid Hybridization. Pongify's blue sibling (ENG-37 B3: `seq` of
    `destroy` + `create_token` with ``creators="previous_target_controller"``).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "destroy", "params": {
                    "target_kind": "creature", "can_be_regenerated": False,
                }},
                {"type": "create_token", "params": {
                    "power": 3, "toughness": 3, "colors": ["G"],
                    "subtypes": ["Frog", "Lizard"], "token_name": "Frog Lizard",
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Rapid Hybridization", _rapid_hybridization)


def _swan_song() -> list[AbilitySpec]:
    """Counter target enchantment, instant, or sorcery spell. Its controller
    creates a 2/2 blue Bird creature token with flying.

    — Swan Song. ENG-37 B3: a `seq` of `counter` (``card_types`` restricts the
    legal spell targets) then `create_token` with ``creators="previous_target_
    controller"`` — the countered spell object keeps its ``controller_id`` in
    the graveyard (RULE 608.2h) — retiring the fused ``counter_create_token``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "counter", "params": {
                    "card_types": ["enchantment", "instant", "sorcery"],
                }},
                {"type": "create_token", "params": {
                    "power": 2, "toughness": 2, "colors": ["U"],
                    "subtypes": ["Bird"], "keywords": ["flying"],
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Swan Song", _swan_song)


def _strix_serenade() -> list[AbilitySpec]:
    """Counter target artifact, creature, or planeswalker spell. Its
    controller creates a 2/2 blue Bird creature token with flying.

    — Strix Serenade. Swan Song's mirror over the other card-type triplet
    (ENG-37 B3: `seq` of `counter` + `create_token` with
    ``creators="previous_target_controller"``).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "counter", "params": {
                    "card_types": ["artifact", "creature", "planeswalker"],
                }},
                {"type": "create_token", "params": {
                    "power": 2, "toughness": 2, "colors": ["U"],
                    "subtypes": ["Bird"], "keywords": ["flying"],
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Strix Serenade", _strix_serenade)


def _an_offer_you_cant_refuse() -> list[AbilitySpec]:
    """Counter target noncreature spell. Its controller creates two Treasure
    tokens.

    — An Offer You Can't Refuse. ENG-37 B3: a `seq` of `counter`
    (``noncreature``) then `create_token` for two Treasures with
    ``creators="previous_target_controller"``. As a bare named token with no
    inline stats, `create_token` now pulls the **curated** Treasure from the
    token database — so its "{T}, Sacrifice this artifact: Add one mana of any
    colour" ability *is* bound, which the retired ``counter_create_token``
    synthesise path couldn't do.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "counter", "params": {"noncreature": True}},
                {"type": "create_token", "params": {
                    "token_name": "Treasure", "count": 2,
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("An Offer You Can't Refuse", _an_offer_you_cant_refuse)


def _path_to_exile() -> list[AbilitySpec]:
    """Exile target creature. Its controller may search their library for a
    basic land card, put that card onto the battlefield tapped, then shuffle.

    — Path to Exile. Reuses `exile_controller_searches_basic_land` (the same
    "exile + the target's controller ramps a tapped basic" primitive Swords
    to Plowshares' sibling family established).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_controller_searches_basic_land", {
                "target_kind": "creature",
            })],
        )
    ]


register("Path to Exile", _path_to_exile)


def _cyclonic_rift() -> list[AbilitySpec]:
    """Return target nonland permanent you don't control to its owner's hand.
    (Overload {6}{U} — not modeled.)

    — Cyclonic Rift. The base (non-overload) mode via `return_to_hand` with
    the new ``nonland_permanent_you_dont_control`` target kind. Overload
    (RULE 702.96 — an alternative cost that rewrites "target" to "each") has
    no parser/engine support yet, so only the single-target mode is offered;
    documented drop per the Sword-of-Forge-and-Frontier partial precedent.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {
                "target_kind": "nonland_permanent_you_dont_control",
            })],
        )
    ]


register("Cyclonic Rift", _cyclonic_rift)


def _alchemists_retrieval() -> list[AbilitySpec]:
    """Return target nonland permanent [you control] to its owner's hand.
    (Cleave {1}{U} — not modeled.)

    — Alchemist's Retrieval. The base (non-cleave) mode via `return_to_hand`
    with ``nonland_permanent_you_control``. Cleave (RULE 702.150 — an
    alternative cost that removes the bracketed words, here broadening the
    target to any nonland permanent) has no parser/engine support yet;
    documented drop.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {
                "target_kind": "nonland_permanent_you_control",
            })],
        )
    ]


register("Alchemist's Retrieval", _alchemists_retrieval)


def _copy_enchantment() -> list[AbilitySpec]:
    """You may have this enchantment enter as a copy of any enchantment on the
    battlefield.

    — Copy Enchantment. Same `enter_as_copy` mechanism as Clever Impersonator
    (see its docstring), narrowed to ``target_kind="enchantment"`` (the new
    single-type target kind).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "enchantment"})],
        )
    ]


register("Copy Enchantment", _copy_enchantment)


def _gitaxian_probe() -> list[AbilitySpec]:
    """Look at target player's hand. Draw a card.

    — Gitaxian Probe. The "look at target player's hand" clause is pure
    information (no game-state change) and, in a full-information goldfish/
    replay session, a no-op — so only the "draw a card" cantrip half is
    bound; documented drop of the reveal clause.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("draw", {"count": 1})],
        )
    ]


register("Gitaxian Probe", _gitaxian_probe)


def _reanimate() -> list[AbilitySpec]:
    """Put target creature card from a graveyard onto the battlefield under
    your control. You lose life equal to that creature's mana value.

    — Reanimate. `return_from_graveyard` with ``under_your_control`` (the
    Reanimate shape) plus the new ``lose_life_equal_mv`` rider, which reads
    the returned creature's mana value and makes the caster lose that much
    life.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "any_graveyard_creature",
                "destination": "battlefield",
                "under_your_control": True,
                "lose_life_equal_mv": True,
            })],
        )
    ]


register("Reanimate", _reanimate)


def _noxious_revival() -> list[AbilitySpec]:
    """Put target card from a graveyard on top of its owner's library.

    — Noxious Revival. `return_from_graveyard` with the new ``library_top``
    destination (the card goes to its *owner's* library top, the engine
    default when no controller override is given).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "any_graveyard_card",
                "destination": "library_top",
            })],
        )
    ]


register("Noxious Revival", _noxious_revival)


def _dramatic_reversal() -> list[AbilitySpec]:
    """Untap all nonland permanents you control.

    — Dramatic Reversal. `TapEffect` in its untargeted mass-untap mode via
    the new ``nonland_permanents_you_control`` group selector.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("tap", {
                "untap": True, "selector": "nonland_permanents_you_control",
            })],
        )
    ]


register("Dramatic Reversal", _dramatic_reversal)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 15 (new core primitive: EventType.SACRIFICE)
# ---------------------------------------------------------------------------


def _mayhem_devil() -> list[AbilitySpec]:
    """Whenever a player sacrifices a permanent, Mayhem Devil deals 1 damage
    to any target.

    — Mayhem Devil. First consumer of the new `EventType.SACRIFICE`
    occurrence (RULE 701.17), fired by `RulesEngine._move_to_graveyard` for
    every `put_into_graveyard` sacrifice in addition to DIES/LEAVES. The
    trigger carries no subject condition — "a player" means *any* player's
    sacrifice, and SACRIFICE only ever fires for a permanent being
    sacrificed, so a bare trigger matches exactly the intended events. The
    1-damage effect targets "any target" (RULE 115.4), gathered
    interactively at resolution like any other targeted trigger.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "target_kind": "any"})],
            trigger={"event": EventType.SACRIFICE},
        )
    ]


register("Mayhem Devil", _mayhem_devil)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 17 (new core primitive: spell-copy, RULE 707.10)
# ---------------------------------------------------------------------------


def _dualcaster_mage() -> list[AbilitySpec]:
    """Flash. When Dualcaster Mage enters, copy target instant or sorcery
    spell. You may choose new targets for the copy.

    — Dualcaster Mage. Flash is a keyword (folded in by `specs_for`'s RULE
    702 keyword catalogue, so it isn't authored here). The ETB trigger is
    the first consumer of the new `copy_spell` effect (`RulesEngine.
    copy_spell`, RULE 707.10): it targets an instant/sorcery spell on the
    stack and puts a copy above it. "You may choose new targets" is the
    effect's documented MVP simplification (keeps the original's targets —
    always legal, RULE 707.10c).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Dualcaster Mage", _dualcaster_mage)


def _flare_of_duplication() -> list[AbilitySpec]:
    """You may sacrifice a nontoken red creature rather than pay this spell's
    mana cost. Copy target instant or sorcery spell. You may choose new
    targets for the copy.

    — Flare of Duplication. The copy effect is the `copy_spell` primitive.
    **Deliberately dropped**: the optional "sacrifice a nontoken red creature
    rather than pay this spell's mana cost" *alternative* casting cost (RULE
    118.9 — an alt-cost, the Force-of-Will/pitch family the engine doesn't
    model yet). Dropping it leaves the card fully playable at its normal mana
    cost, only without the optional discount — the same
    partial-model-with-explicit-drop precedent as Batch 14's Cyclonic Rift
    (Overload) and Gitaxian Probe (reveal).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
        )
    ]


register("Flare of Duplication", _flare_of_duplication)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 20 (new core primitive: the "tapped for mana"
# event, RULE 605.1 — `EventType.TAPPED_FOR_MANA`)
# ---------------------------------------------------------------------------


def _price_of_glory() -> list[AbilitySpec]:
    """Whenever a player taps a land for mana, if it's not that player's
    turn, destroy that land.

    — Price of Glory. First consumer of the new `EventType.TAPPED_FOR_MANA`
    occurrence (`GameEngine.tap_for_mana`, RULE 605.1). Three primitives
    compose here, no bespoke code: the ``"group"`` subject scopes it to a
    *land* being tapped (`condition.type == "land"`, any player — no
    ``controller`` scoping); ``not_controllers_turn`` is the RULE 603.4
    intervening-if ("if it's not that player's turn", checked against the
    live active player, `effect_binder._trigger_condition`); and
    ``reflexive`` bakes in *that* land as the destroy target from the
    event's ``instance_id`` (RULE 603.3d, batch 16) — no target choice, and
    the trigger drops if the land somehow already left. Destroying a land is
    an ordinary stack trigger (not a mana ability), so normal resolution is
    correct.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy", {"target_kind": "land"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land"},
                "not_controllers_turn": True,
                "reflexive": True,
            },
        )
    ]


register("Price of Glory", _price_of_glory)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 19 (new core primitive: divided damage,
# RULE 601.2d — `DealDamageEffect(divided=True)`)
# ---------------------------------------------------------------------------


def _shatterskull_smashing() -> list[AbilitySpec]:
    """Shatterskull Smashing deals X damage divided as you choose among up to
    two target creatures and/or planeswalkers. If X is 6 or more, it deals
    twice X divided among them instead.

    — Shatterskull Smashing (the sorcery *front* face of the MDFC; its back is
    the land Shatterskull, the Hammer Pass, so the spell casts as an ordinary
    {X}{R}{R} sorcery — no modal-DFC machinery needed for this face). First
    consumer of the `divided` damage primitive: the announced {X} pool is
    split across the chosen targets (``divided`` + ``count`` 2 ``optional``),
    doubling at ``double_at=6`` (RULE 107.3). **Documented simplifications**:
    the "and/or planeswalkers" half of the target set is dropped (``creature``
    only — planeswalker damage targeting), and the "as you choose" split
    defaults to an even distribution (`DealDamageEffect._apply_divided`) — the
    total dealt and which creatures take it are exact; only the freedom to
    lump it unevenly is auto-made.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": "x", "target_kind": "creature", "count": 2,
                "optional": True, "divided": True, "double_at": 6,
            })],
        )
    ]


register("Shatterskull Smashing", _shatterskull_smashing)


def _fire_covenant() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, pay X life. Fire Covenant
    deals X damage divided as you choose among any number of target creatures.

    — Fire Covenant. Combines the `divided` damage primitive with the same
    ``additional_cost={"pay_life": "x"}`` X-from-life shape as Toxic Deluge
    (RULE 601.2b — X is defined by the announced life payment, not a mana
    {X}, and threaded into the ``"x"`` amount by `RulesEngine._substitute_x`).
    "Any number of target creatures" is capped at ``count`` 10 for target
    offering (a UI cap — a real board never has X-1's worth of relevant
    creatures beyond that); the even-split "as you choose" simplification is
    the same as Shatterskull's.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": "x", "target_kind": "creature", "count": 10,
                "optional": True, "divided": True,
            })],
            additional_cost={"pay_life": "x"},
        )
    ]


register("Fire Covenant", _fire_covenant)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 18 (new core primitive: extra turns,
# RULE 500.7 — `GameState.extra_turns` + `take_extra_turn` effect,
# consumed by `GameEngine.begin_turn`)
# ---------------------------------------------------------------------------


def _final_fortune() -> list[AbilitySpec]:
    """Take an extra turn after this one. At the beginning of that turn's end
    step, you lose the game.

    — Final Fortune. First consumer of the extra-turn primitive (`take_extra_
    turn` → `GameState.extra_turns`, RULE 500.7). The downside reuses the
    batch-22 delayed-trigger primitive: a `lose_game` armed for the
    controller's *end* step, with ``min_turn_offset`` 1 so it fires at *that*
    (extra) turn's end step — not the current turn's, which would otherwise be
    the very next end step to begin. The extra turn is queued first, then the
    delayed loss armed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("take_extra_turn", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "controller",
                    "min_turn_offset": 1,
                    "effects": [{"type": "lose_game", "params": {"reason": "final_fortune"}}],
                    "description": "Final Fortune: du verlierst das Spiel",
                }),
            ],
        )
    ]


register("Final Fortune", _final_fortune)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 23 (new core primitive: granted protection,
# RULE 702.16 — `GameObject.temp_protections` read by `combat.is_protected_
# from`, granted via the interactive `grant_protection` effect)
# ---------------------------------------------------------------------------


def _mother_of_runes() -> list[AbilitySpec]:
    """{T}: Target creature you control gains protection from the color of
    your choice until end of turn.

    — Mother of Runes. First consumer of the granted-protection primitive: the
    `grant_protection` effect opens an interactive colour pick
    (`RulesEngine.grant_protection_choice`) and stashes the chosen quality in
    the target's ``temp_protections``, which `combat.is_protected_from` now
    reads alongside printed text (cleared at cleanup, RULE 514.2).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_protection", {"target_kind": "creature_you_control"})],
            cost={"taps_self": True},
        )
    ]


register("Mother of Runes", _mother_of_runes)


def _giver_of_runes() -> list[AbilitySpec]:
    """{T}: Another target creature you control gains protection from
    colorless or from the color of your choice until end of turn.

    — Giver of Runes. Same primitive as Mother of Runes, with Giver's extra
    "colorless" option (``allow_colorless``). **Documented simplification**:
    the "*another*" restriction (Giver can't target itself) is dropped — no
    "other creature you control" target kind exists yet, so it's modeled as
    the plain "creature you control" Mother uses; the only lost fidelity is
    that Giver could illegally target itself, which a real player never wants.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_protection", {
                "target_kind": "creature_you_control", "allow_colorless": True,
            })],
            cost={"taps_self": True},
        )
    ]


register("Giver of Runes", _giver_of_runes)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 24 (new core primitive: board-wide ability strip,
# layer 6 — `remove_all_abilities` static → `GameObject.loses_all_abilities`)
# ---------------------------------------------------------------------------


def _humility() -> list[AbilitySpec]:
    """All creatures lose all abilities and have base power and toughness 1/1.

    — Humility. First consumer of the ability-strip primitive: a layer-6
    `remove_all_abilities` static (RULE 613.7f — every creature's keywords via
    `combat._obj_keywords`, its triggered/activated abilities gated at
    fire/activate time) plus a layer-7b `pt_set` to base 1/1. Two static
    abilities on one card, both scoped to ``all_creatures`` (Humility is itself
    a non-creature enchantment, so it isn't self-affected).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("remove_all_abilities", {"affects": "all_creatures"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("pt_set", {"power": 1, "toughness": 1, "affects": "all_creatures"})],
        ),
    ]


register("Humility", _humility)


# ---------------------------------------------------------------------------
# Impulsive draw's dual-player extension — Ragavan, Nimble Pilferer's
# damaged-player-library exile + Mnemonic Betrayal's whole-graveyard, "any
# type" mana-wildcard exile. See `game/effects/core.py`'s `ImpulsiveDrawEffect`/
# `GraveyardImpulsiveCastEffect`/`ReturnRemainingExiledEffect`,
# `RulesEngine._collect_impulsive_draw_triggers`/`exile_with_play_permission`/
# `exile_graveyard_with_cast_permission`, and `ManaPool`'s ``wildcard`` param.
# ---------------------------------------------------------------------------


def _ragavan_nimble_pilferer() -> list[AbilitySpec]:
    """Whenever Ragavan deals combat damage to a player, create a Treasure
    token and exile the top card of that player's library. Until end of
    turn, you may cast that card.
    Dash {1}{R}

    — Ragavan, Nimble Pilferer. Splits into two triggered abilities sharing
    the same "self deals combat damage to a player" condition: the Treasure
    token has no per-firing variance, so it's an ordinary bound
    `TriggeredAbility` below; the exile-and-cast-permission half needs the
    *damaged* player baked in fresh per firing (a bind-on-load ability's one
    fixed effects list can't carry that), so it's a marker
    (`impulsive_draw_on_combat_damage`) `RulesEngine.
    _collect_impulsive_draw_triggers` reads off the event's own source
    instead — see that method's docstring. Dash is a plain RULE 702 keyword,
    covered by the keyword catalogue.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
        AbilitySpec(
            "static",
            [],
            impulsive_draw_on_combat_damage={"count": 1},
        ),
    ]


register("Ragavan, Nimble Pilferer", _ragavan_nimble_pilferer)


def _mnemonic_betrayal() -> list[AbilitySpec]:
    """Exile all opponents' graveyards. You may cast spells from among
    those cards this turn, and mana of any type can be spent to cast them.
    At the beginning of the next end step, if any of those cards remain
    exiled, return them to their owners' graveyards.
    Exile Mnemonic Betrayal.

    — Mnemonic Betrayal. The trailing "Exile ~." is the ordinary
    `ExileEffect` ``target_kind=None`` self mode (already claimed by the
    oracle-text parser — see `backend/tests/test_cube_batch_a1.py`'s
    ``test_mnemonic_betrayal_and_teferis_protection_self_exile_claimed``);
    only the graveyard-impulsive-cast body needed hand authoring, via
    `GraveyardImpulsiveCastEffect`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile_opponents_graveyards_impulsive_cast", {"mana_wildcard": "type"}),
                EffectSpec("exile", {"target_kind": None}),
            ],
        )
    ]


register("Mnemonic Betrayal", _mnemonic_betrayal)


def _marchesa_the_black_rose() -> list[AbilitySpec]:
    """Dethrone (Whenever this creature attacks the player with the most
    life or tied for most life, put a +1/+1 counter on it.)
    Other creatures you control have dethrone.
    Whenever a creature you control with a +1/+1 counter on it dies,
    return that card to the battlefield under your control at the
    beginning of the next end step.

    — Marchesa, the Black Rose. Her own printed Dethrone needs no
    hand-authoring — it's a plain Scryfall keyword flag `combat.has` already
    recognizes (`RulesEngine.check_dethrone`, called from `GameEngine.
    declare_attackers` since Dethrone's amount is fixed per-firing rather
    than bind-on-load, the same "per-firing dynamic" reason `check_rampage`
    isn't a bind-time `TriggeredAbility` either). The "Other creatures you
    control have dethrone" static *is* hand-authored here, below, as an
    ordinary layer-6 `grant_keyword` — `check_dethrone` reads `combat.has`
    fresh at attack-declaration time, so a creature holding the granted
    keyword dethrones exactly like one with it printed. The third clause
    (the RULE 603.7 delayed-return trigger) is modeled via
    `AbilitySpec.counter_death_return`/`RulesEngine._collect_counter_
    death_return_triggers` — a good showcase card for the "planned"
    delayed-trigger UI panel, same reason Ephemerate/Sneak Attack/Meek
    Attack were picked.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "keywords": ["dethrone"],
            })],
        ),
        AbilitySpec(
            "static",
            [],
            counter_death_return={"counter_kind": "+1/+1"},
        )
    ]


register("Marchesa, the Black Rose", _marchesa_the_black_rose)


def _sneak_attack() -> list[AbilitySpec]:
    """{R}: You may put a creature card from your hand onto the
    battlefield. That creature gains haste. Sacrifice the creature at the
    beginning of the next end step.

    — Sneak Attack. `CheatCreatureFromHandEffect` (`game/effects/core.py`)
    covers the whole line in one atomic effect: the RULE 701 "cheat into
    play", the haste grant, and arming the RULE 603.7 delayed sacrifice.
    The hand-card pick is auto-chosen — no chooser in this MVP,
    `RulesEngine.discard`'s established precedent for an un-targeted
    hand-card pick — rather than an interactive choice among several
    eligible creatures.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("cheat_creature_from_hand", {})],
            cost={"text": "{R}"},
        )
    ]


register("Sneak Attack", _sneak_attack)


def _meek_attack() -> list[AbilitySpec]:
    """{1}{R}: You may put a creature card with total power and toughness
    5 or less from your hand onto the battlefield. That creature gains
    haste. At the beginning of the next end step, sacrifice that creature.

    — Meek Attack (Sneak Attack's Unhinged sibling): the same
    `CheatCreatureFromHandEffect`, just with its ``max_total_pt`` filter
    set to 5 instead of unrestricted.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("cheat_creature_from_hand", {"max_total_pt": 5})],
            cost={"text": "{1}{R}"},
        )
    ]


register("Meek Attack", _meek_attack)



def _riot_control() -> list[AbilitySpec]:
    """You gain 1 life for each creature your opponents control. Prevent
    all damage that would be dealt to you this turn.

    — Riot Control. The lifegain half is an ordinary `GainLifeEffect` with
    the new `count_selector="creatures_opponents_control"` (mirroring the
    existing "you control"/"opponents control" selector pairs in
    `continuous.count_selector`). The prevention half is the new one-shot
    `prevent_damage_shield` family (`PreventDamageEffect`/`RulesEngine.
    prevent_damage_to_player`) this card and Thought Lash's own activated
    ability motivated — a turn-scoped shield living on `Player.
    player_effects`, distinct from `regenerate`'s permanent-scoped one and
    from `ReplacementRegistry`'s unrelated standing-permanent `"prevent_
    damage"` factory (the Sphere/Absorb/Shield of the Realm family, MEC-30).
    ``amount="all"`` here since Riot Control prevents everything, not a
    capped amount.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("gain_life", {"count_selector": "creatures_opponents_control"}),
                EffectSpec("prevent_damage_shield", {"amount": "all"}),
            ],
        )
    ]


register("Riot Control", _riot_control)


def _thought_lash() -> list[AbilitySpec]:
    """Exile the top card of your library: Prevent the next 1 damage that
    would be dealt to you this turn.

    — Thought Lash. Only this repeatable activated ability is hand-authored
    here; the card's own Cumulative Upkeep (RULE 702.24) now binds for free
    regardless (MEC-16 — `game/binding/core.py`'s keyword dispatch reads
    `Card.keywords`/oracle text independently of whatever a hand-authored
    entry supplies), so it no longer needs claiming here. Its own trailing
    "when a player doesn't pay this enchantment's cumulative upkeep, that
    player exiles all cards from their library" rider is still unclaimed
    though — the base mechanic never fires a paid-vs-not-paid event a
    second trigger could hook, only a real but narrower residual gap now.
    This entry only supplies the activated ability so the shared
    `prevent_damage_shield` primitive has its second real, amount-capped/
    repeatable-use exercising card (Riot Control's own use is the single
    uncapped "all" case). The cost is a plain "Exile the top card of your
    library" cost (`costs.py`'s existing library-exile cost grammar); the
    effect passes ``amount=1`` — a fresh `RulesEngine.
    prevent_damage_to_player` shield is opened on each activation, so
    repeated activations in a turn stack independent 1-point shields
    exactly like `regenerate`'s own multiple-activations-stack behaviour.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("prevent_damage_shield", {"amount": 1})],
            cost={"text": "Exile the top card of your library"},
        )
    ]


register("Thought Lash", _thought_lash)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 1: state-tracking primitives
#
# Six cards whose only real blocker was that the engine kept no *record* of
# something that had already happened: how much mana a spell was paid with,
# who a creature connected with in combat, what was sacrificed to an
# additional cost, how many symbols of a colour are on the board. Each is now
# a first-class piece of state (`GameObject.mana_spent_to_cast`/
# `sacrificed_cost_mana_value`, `GameState.combat_damage_to_players_this_turn`,
# `continuous.count_selector`'s devotion/legendary/named-card entries) rather
# than something re-derived — none of it *can* be re-derived after the fact.
# ---------------------------------------------------------------------------


def _lavinia_azorius_renegade() -> list[AbilitySpec]:
    """Each opponent can't cast noncreature spells with mana value greater
    than the number of lands that player controls.
    Whenever an opponent casts a spell, if no mana was spent to cast it,
    counter that spell.

    — Lavinia, Azorius Renegade. Both halves needed a new primitive:

    * the prohibition is the first ``cast_prohibition`` static (RULE 601.3a)
      — a *conditional* veto on one specific spell, unlike the pre-existing
      ``cast_limit``'s flat per-turn count. Its ``max_mana_value_selector``
      is evaluated for the **casting** player ("*that player*'s lands"), not
      the static's own controller, which is why it can't be a plain layer-
      engine value (`continuous.cast_prohibited`).
    * the counter-trigger reads the `SPELL_CAST` event's new ``mana_spent``
      key (RULE 202.1/601.2h). Deliberately *not* the pre-existing ``free``
      flag: a spell cast for an alternative cost of {0}, or one whose cost
      was reduced to {0}, spends no mana while still being a paid cast —
      Lavinia catches those too, which is most of why she is played.
      "Counter that spell" is the already-built RULE 603.3d ``reflexive``
      trigger shape (`TriggeredAbility.reflexive`), whose docstring named
      this card as its motivating example before it had one.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "opponents",
                "noncreature": True,
                "max_mana_value_selector": "lands_you_control",
            })],
        ),
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
    ]


register("Lavinia, Azorius Renegade", _lavinia_azorius_renegade)
