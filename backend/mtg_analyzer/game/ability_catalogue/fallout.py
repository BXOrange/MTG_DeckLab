"""Fallout deck entries, including rad-counter and wasteland mechanics."""

from __future__ import annotations

from ...models.game.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

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
    enter_land_tapped`/`_resume_land_tapped_bonus` — the mirror
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

