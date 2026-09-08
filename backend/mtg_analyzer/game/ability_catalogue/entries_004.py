"""Card -> AbilitySpec catalogue entries, part 004 of 016.

Mechanically split, in original file order, from the single flat
`ability_catalogue.py` module (now `core.py` for the shared registry
infrastructure + this package's `entries_NNN.py` files for the actual
per-card factories). Boundaries are purely positional -- not organized
by mechanic or card type -- see `__init__.py` for the full picture.
"""

from __future__ import annotations

from ...models.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

def _geistwave() -> list[AbilitySpec]:
    """Return target nonland permanent to its owner's hand. If you
    controlled that permanent, draw a card.

    — Geistwave. A new atomic `ReturnToHandDrawIfControlledEffect` this
    batch — the target's controller has to be read *before*
    `ReturnToHandEffect` would move it, the same reason
    `ExileGainLifeToControllerEffect` is one atomic effect rather than two
    composed ones.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand_draw_if_controlled", {"target_kind": "nonland_permanent"})],
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

    — Pongify. Reuses `destroy_create_token` (Beast Within), with
    ``can_be_regenerated=False`` for the "can't be regenerated" clause.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_create_token", {
                "target_kind": "creature",
                "power": 3, "toughness": 3, "colors": ["G"], "subtypes": ["Ape"],
                "can_be_regenerated": False,
            })],
        )
    ]


register("Pongify", _pongify)


def _rapid_hybridization() -> list[AbilitySpec]:
    """Destroy target creature. It can't be regenerated. That creature's
    controller creates a 3/3 green Frog Lizard creature token.

    — Rapid Hybridization. Pongify's blue sibling (`destroy_create_token`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_create_token", {
                "target_kind": "creature",
                "power": 3, "toughness": 3, "colors": ["G"],
                "subtypes": ["Frog", "Lizard"], "token_name": "Frog Lizard",
                "can_be_regenerated": False,
            })],
        )
    ]


register("Rapid Hybridization", _rapid_hybridization)


def _swan_song() -> list[AbilitySpec]:
    """Counter target enchantment, instant, or sorcery spell. Its controller
    creates a 2/2 blue Bird creature token with flying.

    — Swan Song. A new `counter_create_token` effect this batch — the
    stack-side sibling of `destroy_create_token`: the token goes to the
    countered spell's own controller.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_create_token", {
                "card_types": ["enchantment", "instant", "sorcery"],
                "power": 2, "toughness": 2, "colors": ["U"],
                "subtypes": ["Bird"], "keywords": ["flying"],
            })],
        )
    ]


register("Swan Song", _swan_song)


def _strix_serenade() -> list[AbilitySpec]:
    """Counter target artifact, creature, or planeswalker spell. Its
    controller creates a 2/2 blue Bird creature token with flying.

    — Strix Serenade. Swan Song's mirror over the other card-type triplet
    (`counter_create_token`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_create_token", {
                "card_types": ["artifact", "creature", "planeswalker"],
                "power": 2, "toughness": 2, "colors": ["U"],
                "subtypes": ["Bird"], "keywords": ["flying"],
            })],
        )
    ]


register("Strix Serenade", _strix_serenade)


def _an_offer_you_cant_refuse() -> list[AbilitySpec]:
    """Counter target noncreature spell. Its controller creates two Treasure
    tokens.

    — An Offer You Can't Refuse (`counter_create_token`, ``noncreature`` +
    ``count=2``). The Treasure tokens are created as artifact tokens named
    "Treasure"; their own "sacrifice for mana" ability isn't bound (no
    generic Treasure-behaviour primitive yet) — the token exists on the
    board but can't yet be cracked for mana.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_create_token", {
                "noncreature": True, "count": 2,
                "subtypes": ["Treasure"], "token_name": "Treasure",
            })],
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


# ---------------------------------------------------------------------------
# RULE 728 Rad counters — "whenever ~ deals combat damage to a player, they
# get N rad counters" cards whose *damaged player* varies per firing (the
# oracle-text parser has no such per-firing grammar; see
# `AbilitySpec.rad_counters_on_combat_damage`, `RulesEngine._collect_rad_
# counter_damage_triggers`, `game/effects/core.py`'s `AddPlayerCountersEffect`).
# Each card's *other*, unrelated ability is a "whenever a player/an opponent
# mills a nonland card, ..."/"whenever one or more nonland cards are milled,
# ..." trigger (RULE 701.13) — now modeled too, off `EventType.MILL_CARD`
# (`RulesEngine.mill`, fired once per nonland card, never for a land) and its
# `effect_binder`-level "group" subject scoping, the same generic machinery
# `LIBRARY_SEARCHED`'s "an opponent searches" trigger already uses. Both
# clauses are hand-authored per card below — a 3-card family, same "narrow,
# real-card-driven" bar the oracle-text parser front-end itself uses before
# it's worth generalizing a whole new segmenter grammar for one, rather than
# building genuine parser recognition — so printed RULE 702 keywords
# (Deathtouch/Flying) are still picked up automatically regardless of
# registration (`specs_for`'s unconditional keyword fold-in), but nothing
# else on these cards falls through to the oracle-text parser.
# ---------------------------------------------------------------------------


def _glowing_one() -> list[AbilitySpec]:
    """Deathtouch
    Whenever this creature deals combat damage to a player, they get four
    rad counters.
    Whenever a player mills a nonland card, you gain 1 life.

    — Glowing One. The mill trigger is an ordinary bind-once
    `TriggeredAbility` off `EventType.MILL_CARD` with an unscoped ``"group"``
    subject (no ``controller`` key — any player's mill counts, including
    your own).
    """
    return [
        AbilitySpec(
            "static",
            [],
            rad_counters_on_combat_damage={"count": 4},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 1})],
            trigger={"event": EventType.MILL_CARD, "condition": {"subject": "group"}},
        ),
    ]


register("Glowing One", _glowing_one)


def _infesting_radroach() -> list[AbilitySpec]:
    """Flying
    This creature can't block.
    Whenever this creature deals combat damage to a player, they get that
    many rad counters.
    Whenever an opponent mills a nonland card, if this creature is in your
    graveyard, you may return it to your hand.

    — Infesting Radroach. "That many" ties the rad-counter amount to the
    combat damage just dealt (`rad_counters_on_combat_damage`'s
    ``"damage_amount"`` sentinel, `RulesEngine._collect_rad_counter_damage_
    triggers`). The graveyard-return-on-opponent-mill ability is RULE
    112.6a's own family — a triggered ability that must keep functioning
    while its source sits in the graveyard, not a bind-once
    `TriggeredAbility` at all — see `AbilitySpec.mill_return_from_graveyard`/
    `RulesEngine._collect_mill_return_from_graveyard_triggers`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"keywords": ["cant_block"], "affects": "self"})],
        ),
        AbilitySpec(
            "static",
            [],
            rad_counters_on_combat_damage={"count": "damage_amount"},
        ),
        AbilitySpec(
            "static",
            [],
            mill_return_from_graveyard=True,
        ),
    ]


register("Infesting Radroach", _infesting_radroach)


def _the_wise_mothman() -> list[AbilitySpec]:
    """Flying
    Whenever The Wise Mothman enters or attacks, each player gets a rad
    counter.
    Whenever one or more nonland cards are milled, put a +1/+1 counter on
    each of up to X target creatures, where X is the number of nonland
    cards milled this way.

    — The Wise Mothman. The first ability is otherwise fully covered by the
    oracle-text parser's own "~ enters or attacks" grammar and its
    ``add_player_counters``/``each_player`` selector (confirmed by direct
    `parse_oracle` output — see `docs/implementation-state/Done_Backend.md`
    "Library-top ... closeout" batch), but registering this card at all
    (needed for the second ability, below) makes `specs_for` skip the
    parser entirely for it (registry wins wholesale), so it's reproduced
    here verbatim rather than left to fall through.

    The second ability is *simplified*: rather than a genuinely dynamic
    "up to X target creatures where X is milled this way" (X varying per
    firing the way Rampage's block-count bonus does — this catalogue's
    sanctioned answer for that shape is building a fresh `TriggeredAbility`
    directly at the firing call site, `RulesEngine.check_rampage`), this
    reuses the same per-nonland-card `EventType.MILL_CARD` Glowing One/
    Infesting Radroach's mill triggers use: "put a +1/+1 counter on up to
    one target creature" fires once *per* nonland card milled (any player's
    mill, unscoped ``"group"`` subject, same as Glowing One). Across N
    simultaneous nonland mills this reaches the identical set of possible
    end states as the real card's single "up to X targets" choice — for
    each of N independent chances you may put a counter on some creature or
    decline — just as N separate optional triggers instead of one modal
    "choose up to X targets" ability; only trigger *count* (irrelevant to
    every card in this engine's corpus today) differs. The same "for each,
    optionally act" broadcast simplification `_dismantling_wave`-shaped
    entries elsewhere in this catalogue already use for a fixed-count
    "for each opponent" case, just driven by a per-firing count instead.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 1, "kind": "rad", "selector": "each_player"})],
            trigger={"event": [EventType.ENTERS_BATTLEFIELD, EventType.ATTACKS], "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "amount": 1, "target_kind": "creature", "optional": True})],
            trigger={"event": EventType.MILL_CARD, "condition": {"subject": "group"}},
            # RULE 115.1a's "up to one target" — this codebase's trigger-
            # placement UI (`RulesEngine._trigger_target_choice`) only offers
            # a skip/decline option when the *ability* itself is marked
            # ``optional`` (RULE 603.5), so this also needs setting here even
            # though "up to one" isn't literally a "you may": without it a
            # player with a legal creature on board couldn't decline putting
            # the counter at all, contradicting "up to".
            optional=True,
        ),
    ]


register("The Wise Mothman", _the_wise_mothman)


def _bloatfly_swarm() -> list[AbilitySpec]:
    """Flying
    This creature enters with five +1/+1 counters on it.
    If damage would be dealt to this creature while it has a +1/+1 counter
    on it, prevent that damage, remove that many +1/+1 counters from it,
    then give each player a rad counter for each +1/+1 counter removed this
    way.

    — Bloatfly Swarm. Flying and the entry counters are picked up
    unconditionally (RULE 702 keyword fold-in / `entry_counters`, neither
    routed through the catalogue registry at all) — only the compound
    damage-prevention replacement needs hand-authoring here: "that many"
    ties both the counters removed *and* the rad counters granted to the
    damage amount that would have been dealt, known only inside the
    replacement itself at resolution time (`effects.
    _prevent_damage_convert_counters_replacement`), not a shape the oracle
    parser's plain `prevent_damage`/one-shot grammar can express.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage_convert_counters", {
                "to": "self", "remove_kind": "+1/+1", "grant_kind": "rad",
                "grant_selector": "each_player",
            })],
        ),
    ]


register("Bloatfly Swarm", _bloatfly_swarm)


def _vexing_radgull() -> list[AbilitySpec]:
    """Flying
    Whenever this creature deals combat damage to a player, that player
    gets two rad counters if they don't have any rad counters. Otherwise,
    proliferate.

    — Vexing Radgull. Flying picked up unconditionally (RULE 702 keyword
    fold-in). The branch is the same per-firing marker mechanism Glowing
    One/Infesting Radroach use (`rad_counters_on_combat_damage`, the
    damaged player varies per firing — no oracle-text grammar for that at
    all), extended with its own ``else`` key
    (`RulesEngine._collect_rad_counter_damage_triggers`): the damaged
    player gets 2 rad counters if they currently have none, otherwise a
    real RULE 701.30 proliferate happens instead (`game/effects/core.py`'s
    `ProliferateEffect`, which now also proliferates player-level counters
    — a documented gap this card is the first to actually need closed).
    """
    return [
        AbilitySpec(
            "static",
            [],
            rad_counters_on_combat_damage={"count": 2, "kind": "rad", "else": "proliferate"},
        ),
    ]


register("Vexing Radgull", _vexing_radgull)


def _vault_12_the_necropolis() -> list[AbilitySpec]:
    """I — Each player gets three rad counters.
    II — Create X 2/2 black Zombie Mutant creature tokens, where X is the
    total number of rad counters among players.
    III — Put two +1/+1 counters on each creature you control that's a
    Zombie or Mutant.

    — Vault 12: The Necropolis. Chapter I parses fine on its own (it's
    registered here only because chapters II/III need hand-authoring, and a
    registered card's other specs no longer fall back to the parser —
    `ability_catalogue.specs_for`), so it's just carried over verbatim.
    Chapter II needs two things no card in this pool needed before: a
    cross-player aggregate count (`continuous.count_selector`'s new
    ``"total_rad_counters_among_players"``, unlike every other entry there,
    which scopes to a single controller) and a "create X tokens, where X is
    ..." dynamic count (`CreateTokenEffect.count_selector` — the same
    primitive Dockside Extortionist already uses, just with this new
    selector). Chapter III needs a tribal mass-counter filter
    (`AddCountersEffect`'s new ``subtypes`` param).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 3, "kind": "rad", "selector": "each_player"})],
            trigger={"event": "SAGA_CHAPTER", "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count_selector": "total_rad_counters_among_players",
                "power": 2, "toughness": 2, "colors": ["B"],
                "subtypes": ["Zombie", "Mutant"], "token_name": "Zombie Mutant",
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "amount": 2, "kind": "+1/+1", "selector": "each_creature_you_control",
                "subtypes": ["Zombie", "Mutant"],
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
        ),
    ]


register("Vault 12: The Necropolis", _vault_12_the_necropolis)


def _struggle_for_project_purity() -> list[AbilitySpec]:
    """As this enchantment enters, choose Brotherhood or Enclave.
    • Brotherhood — At the beginning of your upkeep, each opponent draws a
    card. You draw a card for each card drawn this way.
    • Enclave — Whenever a player attacks you with one or more creatures,
    that player gets twice that many rad counters.

    — Struggle for Project Purity. A "choose a named mode as this enters,
    persisting for the rest of the game" shape (RULE 601.2b-adjacent, but
    choosing between two flavour-named ability sets rather than a creature
    type/colour) — a new third `enter_choice_effects` sibling
    (`ChooseNamedModeReplacement`, alongside `ChooseCreatureTypeReplacement`/
    `ChooseColorReplacement`), stamping `GameObject.chosen_mode`. Brotherhood
    is an ordinary `TriggeredAbility`, just gated by `effect_binder._trigger_
    condition`'s new ``"named_mode"`` predicate so it only fires once
    "brotherhood" was actually chosen; its "you draw a card for each card
    drawn this way" is `DrawCardEffect`'s new ``"opponents_you_have"``
    count_selector. Enclave needs a genuinely new aggregate event
    (`EventType.PLAYER_ATTACKED`, fired once per combat rather than once per
    attacking creature — see its own docstring) plus the same per-firing
    marker mechanism the other rad-counter cards use
    (`rad_counters_on_attacked`, gated the same way via its own
    ``requires_mode`` key, since it's resolved by a dedicated collector
    rather than the ordinary `TriggeredAbility` condition machinery).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_named_mode", {"options": ["Brotherhood", "Enclave"]})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1, "selector": "each_opponent"}),
                EffectSpec("draw", {"count_selector": "opponents_you_have"}),
            ],
            trigger={
                "event": "STEP_BEGIN", "filter": {"step": "upkeep"},
                "phase_relation": "you", "named_mode": "brotherhood",
            },
        ),
        AbilitySpec(
            "static",
            [],
            rad_counters_on_attacked={"multiplier": 2, "requires_mode": "enclave"},
        ),
    ]


register("Struggle for Project Purity", _struggle_for_project_purity)


def _mariposa_military_base() -> list[AbilitySpec]:
    """You may have this land enter tapped. If you do, you get two rad
    counters.
    {T}: Add {C}.
    {5}, {T}: Draw a card. This ability costs {1} less to activate for
    each rad counter you have.

    — Mariposa Military Base. The tapped-entry choice is picked up
    unconditionally, no registration needed at all
    (`parser.oracle.catalogue.lands.tap_clause_condition`'s new
    ``"optional_bonus_rad"`` shape, resolved by `RulesEngine.
    enter_land_tapped`/`resolve_land_tapped_bonus_choice` — the mirror
    image of a shock land's pay-life choice). The plain "{T}: Add {C}."
    mana ability is likewise picked up unconditionally
    (`game/mana_abilities.py` reads oracle text directly, regardless of
    catalogue registration). Only the draw ability's own "costs {1} less
    ... for each rad counter you have" needs hand-authoring here — a
    dynamically-scaled activation-cost reduction no oracle-text grammar
    exists for yet (`costs.ActivationCost.dynamic_reduction`, consulted by
    `GameEngine._reduced_activation_mana`).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{5}, {T}", "dynamic_reduction": {"kind": "rad", "generic_per": 1}},
        ),
    ]


register("Mariposa Military Base", _mariposa_military_base)


def _nuka_nuke_launcher() -> list[AbilitySpec]:
    """Equipped creature gets +3/+0 and has intimidate.
    Whenever equipped creature attacks, until the end of defending
    player's next turn, that player gets two rad counters whenever they
    cast a spell.
    Equip {3}

    — Nuka-Nuke Launcher. The +3/+0-and-intimidate anthem grant and Equip
    cost both parse generically (an ordinary attached-permanent static +
    the standard Equip keyword ability). Only the triggered ability
    needs hand-authoring: a *recurring*, bounded-duration player-scoped
    trigger (`InstallTemporaryPlayerTriggerEffect`/`GameState.temporary_
    player_triggers`) — no oracle-text grammar exists for "until the end
    of X's next turn, <recurring effect>" (a genuinely different shape
    from RULE 603.7's existing one-shot `CreateDelayedTriggerEffect`).
    The "whenever equipped creature attacks" trigger subject itself does
    parse generically now (`_ATTACHED_SUBJECT_RE`), so this AbilitySpec's
    ``trigger`` is written the same way the parser would emit it.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("install_temporary_player_trigger", {
                "event_type": "SPELL_CAST",
                "effects": [{"type": "add_player_counters", "params": {"amount": 2, "kind": "rad"}}],
                "description": "Nuka-Nuke Launcher: Rad-Marken bei Zauberspruch",
            })],
            trigger={"event": "ATTACKS", "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Nuka-Nuke Launcher", _nuka_nuke_launcher)


def _harold_and_bob() -> list[AbilitySpec]:
    """Vigilance, reach
    When Harold and Bob dies, if it was a creature, return it to the
    battlefield. It's an Aura enchantment with enchant Forest you control
    and "{T}: Add three mana of any one color. You get two rad counters."
    Harold and Bob loses all other abilities.

    — Harold and Bob, First Numens. Vigilance/reach are picked up
    unconditionally (RULE 702 keyword fold-in). "If it was a creature" is a
    no-op condition given how this engine already only ever fires DIES for
    an object that was a creature (`RulesEngine._move_to_graveyard`'s own
    ``was_creature`` gate) — always true in practice, so no separate check
    is needed. The return itself is a wholly new compound shape, well
    beyond RULE 712.8's ordinary "return transformed" (which needs a real
    printed back face this card doesn't have):
    `ReturnDiesAsNewPermanentEffect`/`RulesEngine.return_dies_as_new_
    permanent` swaps the returned object's own `Card` for a synthetic Aura
    built from the quoted text right here, attached to a real RULE 115
    target ("enchant Forest you control", `targeting.py`'s new
    ``forest_you_control`` kind) — "loses all other abilities" is made
    literal by simply never re-binding the original creature's catalogue
    specs onto the new permanent. The granted "{T}: Add three mana of any
    one color. You get two rad counters." is a genuine compound mana
    ability (`game/mana_abilities.py`'s ``self_rad_counters`` rider,
    alongside fixing a latent "any one color" amount bug — the parser
    always produced 1 mana regardless of a printed fixed count > 1, since
    no card before this one printed one) — read live off the synthetic
    card's own oracle text, no further hand-authoring needed for it.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_dies_as_new_permanent", {
                "new_type_line": "Enchantment — Aura",
                "new_oracle_text": "Enchant Forest you control\n{T}: Add three mana of any "
                                   "one color. You get two rad counters.",
                "target_kind": "forest_you_control",
            })],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
        ),
    ]


register("Harold and Bob, First Numens", _harold_and_bob)


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

