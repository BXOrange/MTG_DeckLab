"""Card -> AbilitySpec catalogue entries, part 015 of 016.

Mechanically split, in original file order, from the single flat
`ability_catalogue.py` module (now `core.py` for the shared registry
infrastructure + this package's `entries_NNN.py` files for the actual
per-card factories). Boundaries are purely positional -- not organized
by mechanic or card type -- see `__init__.py` for the full picture.
"""

from __future__ import annotations

from ...models.events import EventType
from ..costs import SACRIFICE_COUNT_X
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

def _chainer_dementia_master() -> list[AbilitySpec]:
    """All Nightmares get +1/+1.
    {B}{B}{B}, Pay 3 life: Put target creature card from a graveyard onto
    the battlefield under your control. That creature is black and is a
    Nightmare in addition to its other creature types.
    When Chainer leaves the battlefield, exile all Nightmares.

    — MEC-43 round 2. The anthem is reproduced verbatim (whole-card
    hand-authoring replaces the parser's own output, which would
    otherwise have claimed it alone). The reanimation ability reuses
    `grant_until`'s type/colour addition exactly like Rise from the Grave;
    "Pay 3 life" is a plain life-payment cost component. The leaves
    trigger reuses `exile_all_graveyards`'s sibling mass-exile shape via
    the new ``"exile"`` ``filter={"subtype": ...}`` key — a *battlefield*
    sweep this time, not a graveyard one.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "all_creatures", "subtype": "nightmare", "power": 1, "toughness": 1})],
            raw_text="Alle Alpträume erhalten +1/+1.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "under_your_control": True,
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "type_change", "params": {"add_subtypes": ["Nightmare"]}},
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "color_change", "params": {"colors": ["B"], "set": False}},
                }),
            ],
            cost={"text": "{B}{B}{B}", "pay_life": 3},
            raw_text="{B}{B}{B}, Bezahle 3 Lebenspunkte: Bringe eine Zielkreaturenkarte "
                     "aus einem Friedhof unter deine Kontrolle ins Spiel. Diese Kreatur ist "
                     "schwarz und zusätzlich zu ihren anderen Kreaturentypen ein Alptraum.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"selector": "all_creatures", "filter": {"subtype": "nightmare"}})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Chainer das Spielfeld verlässt, exiliere alle Alpträume.",
        ),
    ]


register("Chainer, Dementia Master", _chainer_dementia_master)


def _kenriths_transformation() -> list[AbilitySpec]:
    """Enchant creature
    When this Aura enters, draw a card.
    Enchanted creature loses all abilities and is a green Elk creature
    with base power and toughness 3/3.

    — MEC-43 round 2, the "Elk" template (Oko, Thief of Crowns' +1 shares
    the same clause but needs its own resolve-time `grant_until` wiring
    plus its other two loyalty abilities — a bigger lift left open).
    "Enchant creature"/the attach itself comes from the RULE 702 keyword
    catalogue, unaffected by hand-authoring. **Documented simplification**:
    only the creature type is *added* (`type_change`'s ``add_types``), the
    permanent's other printed card types aren't stripped — `Card.
    is_artifact`/``is_enchantment`` read the printed card directly, not a
    layer-4-aware property (`GameObject.is_land`'s own docstring already
    flags this as a gap worth extending, not yet done) — low practical
    impact, since the Elk has no abilities left to use any type distinction.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Verzauberung ins Spiel kommt, ziehe eine Karte.",
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("remove_all_abilities", {"affects": "attached_permanent"}),
                EffectSpec("type_change", {
                    "affects": "attached_permanent", "add_types": ["creature"],
                    "set_subtypes": ["Elk"], "power": 3, "toughness": 3,
                }),
                EffectSpec("color_change", {"affects": "attached_permanent", "colors": ["G"], "set": True}),
            ],
            raw_text="Verzauberte Kreatur verliert alle Fähigkeiten und ist ein grüner "
                     "Elch mit den Grundwerten 3/3.",
        ),
    ]


register("Kenrith's Transformation", _kenriths_transformation)


def _conquerors_flail() -> list[AbilitySpec]:
    """Equipped creature gets +1/+1 for each color among permanents you
    control.
    As long as this Equipment is attached to a creature, your opponents
    can't cast spells during your turn.
    Equip {2}

    — MEC-43 round 2. The anthem reuses the new `count_selector`
    ``"colors_among_permanents_you_control"`` (the P/T sibling of ENG-27's
    same-named mana-ability selector). The cast lockdown needs two
    independent gates ANDed at once — attached, and only during the
    Equipment's controller's own turn — which no single `static_
    conditions` ``kind`` could express before this batch's new ``"all"``
    combinator. "Equip {2}" is the RULE 702.6 keyword, unaffected by
    hand-authoring.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "colors_among_permanents_you_control",
                "toughness_count": "colors_among_permanents_you_control",
            })],
            raw_text="Bezauberte Kreatur erhält +1/+1 für jede Farbe unter den Permanenten, "
                     "die du kontrollierst.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "opponents",
                "active_if": {
                    "kind": "all",
                    "conditions": [{"kind": "source_attached"}, {"kind": "your_turn"}],
                },
            })],
            raw_text="Solange diese Ausrüstung an eine Kreatur angelegt ist, können deine "
                     "Gegner während deines Zuges keine Zaubersprüche wirken.",
        ),
    ]


register("Conqueror's Flail", _conquerors_flail)


def _faeburrow_elder() -> list[AbilitySpec]:
    """Vigilance
    This creature gets +1/+1 for each color among permanents you control.
    {T}: For each color among permanents you control, add one mana of
    that color.

    — MEC-43 round 2. Vigilance and the mana ability both already parse on
    their own (the latter via `mana_abilities_for`'s own oracle-text read,
    entirely independent of `bind_from_catalogue`/hand-authoring — see
    CLAUDE.md's RULE 605 note); only the P/T anthem needs hand-authoring,
    reusing Conqueror's Flail's own new ``colors_among_permanents_you_
    control`` selector with ``affects="self"``.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "self", "power": 1, "toughness": 1,
                "power_count": "colors_among_permanents_you_control",
                "toughness_count": "colors_among_permanents_you_control",
            })],
            raw_text="~ erhält +1/+1 für jede Farbe unter den Permanenten, die du "
                     "kontrollierst.",
        )
    ]


register("Faeburrow Elder", _faeburrow_elder)


def _delney_streetwise_lookout() -> list[AbilitySpec]:
    """Creatures you control with power 2 or less can't be blocked by
    creatures with power 3 or greater.
    If a triggered ability of a creature you control with power 2 or less
    triggers, that ability triggers an additional time.

    — MEC-43 round 2. The first clause is the already-shipped qualified
    combat-restriction shape (Challenger Troll/Flopsie's own group
    ``min_power``/``max_power`` scoping, here on the *restricted* side
    instead), just with a blocker-power filter instead of a group-scope
    P/T qualifier. The second reuses `TriggerDoublerEffect`'s new
    ``max_power`` axis — unscoped by "another" (the printed clause names
    none, unlike Roaming Throne's), so Delney's own future triggers would
    double themselves too, though this card prints no other trigger of
    its own for that to matter today.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("combat_restriction", {
                "affects": "creatures_you_control", "max_power": 2,
                "kind": "cant_be_blocked_by", "filter": {"min_power": 3},
            })],
            raw_text="Kreaturen, die du kontrollierst und die Stärke 2 oder weniger haben, "
                     "können nicht von Kreaturen mit Stärke 3 oder mehr geblockt werden.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {"max_power": 2})],
            raw_text="Falls eine ausgelöste Fähigkeit einer Kreatur, die du kontrollierst "
                     "und die Stärke 2 oder weniger hat, ausgelöst wird, wird sie ein "
                     "zusätzliches Mal ausgelöst.",
        ),
    ]


register("Delney, Streetwise Lookout", _delney_streetwise_lookout)


def _runic_armasaur() -> list[AbilitySpec]:
    """Whenever an opponent activates an ability of a creature or land
    that isn't a mana ability, you may draw a card.

    — MEC-43 round 2. `EventType.ACTIVATED_ABILITY` already fires for
    every non-mana activated ability (RULE 605.1a mana abilities never use
    the stack, so they never reach this event at all — "isn't a mana
    ability" needs no separate check), with `object_types`/``controller_id``
    already matching this trigger's own default group-subject keys. The
    only real gap was the group-subject ``type`` filter's shape: it only
    ever took one word before this batch, and "creature or land" needs
    two ORed together (`effect_binder._group_ok`'s new list-``type``
    support). **Documented simplification**: "may" is read as
    unconditional, the same accepted convention every other untargeted
    "you may draw"/"you may `<upside>`" trigger with no real downside to
    declining already gets in this engine (Selvala, Heart of the Wilds's
    own docstring names the same precedent).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "type": ["creature", "land"], "controller": "not_you"},
            },
            raw_text="Immer wenn ein Gegner eine Fähigkeit einer Kreatur oder eines Landes "
                     "aktiviert, die keine Manafähigkeit ist, darfst du eine Karte ziehen.",
        )
    ]


register("Runic Armasaur", _runic_armasaur)


def _peer_into_the_abyss() -> list[AbilitySpec]:
    """Target player draws cards equal to half the number of cards in
    their library and loses half their life. Round up each time.

    — MEC-43 round 2. `DrawCardEffect`'s new ``count_selector=
    "half_target_library_round_up"`` and `LoseLifeEffect`'s new
    ``amount_from_half_target_life`` are the *targeted* siblings of the
    existing "half your own life" shapes (MEC-37's Doomsday), both scoped
    to whichever player the single "target player" resolves to rather
    than the caster. `LoseLifeEffect.previous_subject` reads that same
    resolved target back (`GameContext.previous_targets`) instead of
    declaring a second RULE 115 target of its own — the real card only
    targets once, for both verbs.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {
                    "target_kind": "player", "count_selector": "half_target_library_round_up",
                }),
                EffectSpec("lose_life", {
                    "previous_subject": True, "amount_from_half_target_life": True,
                }),
            ],
            raw_text="Zielspieler zieht so viele Karten, wie die Hälfte der Karten in "
                     "seiner Bibliothek beträgt, und verliert die Hälfte seines Lebens. "
                     "Runde jeweils auf.",
        )
    ]


register("Peer into the Abyss", _peer_into_the_abyss)


def _soul_conduit() -> list[AbilitySpec]:
    """{6}, {T}: Two target players exchange life totals.

    — MEC-43 round 2. The new `ExchangeLifeTotalsEffect` — a genuinely new
    one-shot, since every other life effect in this engine is a single-
    player delta.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_life_totals", {})],
            cost={"text": "{6}", "taps_self": True},
            raw_text="{6}, {T}: Zwei Zielspieler tauschen ihre Lebenspunkte.",
        )
    ]


register("Soul Conduit", _soul_conduit)


def _grim_hireling() -> list[AbilitySpec]:
    """Whenever one or more creatures you control deal combat damage to a
    player, create two Treasure tokens.
    {B}, Sacrifice X Treasures: Target creature gets -X/-X until end of
    turn. Activate only as a sorcery.

    — MEC-43 round 4A. The trigger is already fully `MODELED` by the
    oracle-text parser (MEC-29's aggregate
    ``EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER``) — reused as-is,
    not re-derived. Only the activated ability needs hand-authoring:
    "Sacrifice X Treasures" is `costs.ActivationCost.sacrifice_count`'s
    ``(count, subtype)`` shape, widened by this same ticket with a new
    `costs.SACRIFICE_COUNT_X` sentinel — the `REMOVE_COUNTERS_X` sibling
    for a sacrifice-cost component whose count is RULE 601.2b's announced
    ``x`` rather than a printed number. The stack item's own ``x``
    (`GameEngine.activate_ability`'s ``x`` param, stamped onto
    ``source.x_paid``) then reaches "gets -X/-X" through the existing
    ``"-x"`` sentinel `RulesEngine._substitute_x` already rewrites on
    `PumpEffect.power`/``toughness`` for any spell/ability — no new
    effect-side code.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 2, "token_name": "Treasure"})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {"subject": "you"},
            },
            raw_text="Whenever one or more creatures you control deal combat "
                     "damage to a player, create two Treasure tokens.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": "-x", "toughness": "-x", "target_kind": "creature",
            })],
            cost={"text": "{B}", "sacrifice_count": (SACRIFICE_COUNT_X, "treasure"),
                  "sorcery_speed_only": True},
            raw_text="{B}, Sacrifice X Treasures: Target creature gets -X/-X "
                     "until end of turn. Activate only as a sorcery.",
        ),
    ]


register("Grim Hireling", _grim_hireling)


def _ikra_shidiqi_the_usurper() -> list[AbilitySpec]:
    """Menace
    Whenever a creature you control deals combat damage to a player, you
    gain life equal to that creature's toughness.
    Partner (You can have two commanders if both have partner.)

    — MEC-43 round 4A. Menace and Partner are both RULE 702 keywords,
    folded in automatically by the keyword catalogue regardless of
    registration — only the triggered life-gain needs hand-authoring here.
    The trigger itself is the exact group-subject "a creature you control
    deals combat damage to a player" shape the oracle parser already fully
    models for Bident of Thassa/Deepfathom Skulker (confirmed by parsing
    that trigger's own text in isolation — reused verbatim, not re-derived);
    what blocks the *whole card* from `MODELED` is the effect body, "gain
    life equal to **that creature's** toughness" — a new
    `GainLifeEffect.amount_from_trigger_source_toughness`, which reads the
    firing DAMAGE event's own ``source_id`` (`GameContext.trigger_event`,
    the same "read this firing's own payload" idiom
    `DestroyEffect.target_from_trigger_event` already uses for Mikaeus, the
    Unhallowed) and that creature's current live toughness.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount_from_trigger_source_toughness": True})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "type": "creature", "other": False, "controller": "you"},
                "filter": {"is_player": True, "combat": True},
            },
            raw_text="Whenever a creature you control deals combat damage "
                     "to a player, you gain life equal to that creature's "
                     "toughness.",
        ),
    ]


register("Ikra Shidiqi, the Usurper", _ikra_shidiqi_the_usurper)


def _sword_of_feast_and_famine() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has protection from black and from
    green.
    Whenever equipped creature deals combat damage to a player, that
    player discards a card and you untap all lands you control.
    Equip {2}

    — MEC-43 round 4A. The static half is already fully `MODELED` by the
    oracle-text parser (the anthem + `grant_protection_static` pair every
    other Sword already uses) — reused as-is. Only the trigger needs
    hand-authoring: the "whenever equipped creature deals combat damage to
    a player" shape itself is the parser's own already-shipped
    ``condition={"subject": "attached_permanent"}`` (confirmed by parsing
    that clause alone against a simpler effect), but this card's own effect
    body has two new pieces — `DiscardEffect.player_from_trigger_event`
    ("that player" is the DAMAGE event's own recipient, not a target) and
    `TapEffect`'s ``selector`` whitelist widened with ``"lands_you_control"``
    (`continuous.group_selector_objects` already supports it; only the
    `TapEffect`-side gate was missing it).
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"power": 2, "toughness": 2, "affects": "attached_permanent"}),
                EffectSpec("grant_protection_static", {
                    "affects": "attached_permanent", "protections": ["black", "green"],
                }),
            ],
            raw_text="Equipped creature gets +2/+2 and has protection from "
                     "black and from green.",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("discard", {"count": 1, "player_from_trigger_event": True}),
                EffectSpec("tap", {"untap": True, "selector": "lands_you_control"}),
            ],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "attached_permanent"},
                "filter": {"is_player": True, "combat": True},
            },
            raw_text="Whenever equipped creature deals combat damage to a "
                     "player, that player discards a card and you untap "
                     "all lands you control.",
        ),
    ]


register("Sword of Feast and Famine", _sword_of_feast_and_famine)


def _umezawas_jitte() -> list[AbilitySpec]:
    """Whenever equipped creature deals combat damage, put two charge
    counters on Umezawa's Jitte.
    Remove a charge counter from Umezawa's Jitte: Choose one —
    • Equipped creature gets +2/+2 until end of turn.
    • Target creature gets -1/-1 until end of turn.
    • You gain 2 life.
    Equip {2}

    — MEC-43 round 4A. The trigger is the same "attached_permanent" DAMAGE
    subject every other Sword uses, minus the "is_player" filter (this one
    fires on **any** combat damage, not just to a player); "put two charge
    counters on ~" is a plain untargeted `AddCountersEffect` (no
    ``target_kind``, so it acts on its own source). The activated ability
    is this round's real primitive gap: RULE 700.2 modal choice
    (``AbilitySpec.modes``) had never been wired for an *activated*
    ability before, only spell/triggered ones — `AbilitySpec._validate_
    modes` now permits ``"activated"``, `effect_binder.bind_ability` builds
    `ActivatedAbility.modes` off the same `_build_mode_entries` helper a
    modal spell/triggered ability already shares, and `GameEngine.
    activate_ability` gained a ``mode`` param (`_resolve_activation_mode`)
    that picks the chosen mode's own effects *before* targets are
    gathered — mirroring a modal spell's own mode-before-target ordering,
    and `_place_trigger`'s existing `effects_override` idiom for a modal
    trigger's chosen mode. `legal_actions`'s activate-ability offer
    (`_activate_actions_for`) now emits one action per mode the same way
    `_modal_cast_actions` already does for spells. Deliberately scoped to
    the plain "choose one" shape only — no printed activated ability needs
    "choose N"/"or both" yet.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"amount": 2, "kind": "charge"})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True},
            },
            raw_text="Whenever equipped creature deals combat damage, put "
                     "two charge counters on Umezawa's Jitte.",
        ),
        AbilitySpec(
            "activated",
            [],
            cost={"remove_counters": ("charge", 1)},
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("pump", {
                        "power": 2, "toughness": 2, "target_kind": "attached_permanent",
                    })],
                    [EffectSpec("pump", {
                        "power": -1, "toughness": -1, "target_kind": "creature",
                    })],
                    [EffectSpec("gain_life", {"amount": 2})],
                ],
                "descriptions": [
                    "Equipped creature gets +2/+2 until end of turn.",
                    "Target creature gets -1/-1 until end of turn.",
                    "You gain 2 life.",
                ],
            },
            raw_text="Remove a charge counter from Umezawa's Jitte: Choose "
                     "one — Equipped creature gets +2/+2 until end of "
                     "turn. Target creature gets -1/-1 until end of turn. "
                     "You gain 2 life.",
        ),
    ]


register("Umezawa's Jitte", _umezawas_jitte)


def _commanders_plate() -> list[AbilitySpec]:
    """Equipped creature gets +3/+3 and has protection from each color
    that's not in your commander's color identity.
    Equip commander {3}
    Equip {5}

    — MEC-43 round 4A. The static anthem+protection half needed one new
    `continuous.commander_color_identity` selector (the union of every
    ``is_commander`` object's printed `Card.color_identity` this player
    owns, searched live across every zone) plus a matching
    ``protection_from_colors_not_in_commanders_identity`` param on
    `grant_protection_static`'s existing layer-6 machinery — no card had
    ever needed a live read of "your commander's color identity" during a
    game before. The ordinary "Equip {5}" is the automatic keyword-catalogue
    ability every Equipment gets; "Equip commander {3}" (RULE 702.6e) is a
    genuinely *second*, coexisting Equip ability restricted to only ever
    attach to a commander, hand-authored here via `AttachEffect`'s new
    ``creature_filter`` param (a new ``"is_commander"``
    `combat.matches_object_filter` key). Along the way, fixed a real
    pre-existing parser bug this card's own text exposed: the "equip"
    keyword's plain COST-shape regex was greedy enough to swallow "Equip
    commander {3}" and report **that** as the ordinary Equip cost instead of
    the real {5} (`parser/oracle/catalogue/keywords.py`'s new
    ``_SPECIAL_REGEX["equip"]`` override, negative-lookahead-excluding
    "commander" as a qualifier word) — silently mispricing the plain Equip
    ability for both cache cards that print this template.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"power": 3, "toughness": 3, "affects": "attached_permanent"}),
                EffectSpec("grant_protection_static", {
                    "affects": "attached_permanent",
                    "protection_from_colors_not_in_commanders_identity": True,
                }),
            ],
            raw_text="Equipped creature gets +3/+3 and has protection from "
                     "each color that's not in your commander's color "
                     "identity.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("attach", {
                "target_kind": "creature", "creature_filter": {"is_commander": True},
            })],
            cost={"text": "{3}"},
            raw_text="Equip commander {3}",
        ),
    ]


register("Commander's Plate", _commanders_plate)


def _legolass_quick_reflexes() -> list[AbilitySpec]:
    """Split second (As long as this spell is on the stack, players can't
    cast spells or activate abilities that aren't mana abilities.)
    Untap target creature. Until end of turn, it gains hexproof, reach,
    and "Whenever this creature becomes tapped, it deals damage equal to
    its power to up to one target creature."

    — MEC-43 round 4A. Split Second was already parser-recognized (RULE
    702.61, a flag keyword) but genuinely inert — no card had ever needed
    its actual restriction enforced before. Built as
    `continuous.split_second_active` (any spell with the keyword on
    `GameState.stack`), checked at the very top of both `GameEngine.
    can_cast`/`can_activate` — mana abilities never call either (RULE
    605.3b keeps them off the stack), so neither gate needs an exemption.
    The untap+grant clause chains three effects off one real target
    (`TapEffect.untap`) via `PumpEffect`/`GrantUntilEffect`'s existing
    ``previous_subject`` pronoun mode (`GameContext.previous_targets`):
    the temporary keywords ride the ordinary "until end of turn" `temp_*`
    path, and the granted triggered ability is `grant_triggered_ability`'s
    already-general layer-6 machinery (Dionus, Elvish Archdruid's own
    shape) wrapped in `GrantUntilEffect` for its "until end of turn"
    lifespan — `damage_equal_to_power`'s ``dealer_kind=None`` reads
    whichever creature the grant actually landed on (late-bound
    `effect.source`, `_apply_effects_partitioned`'s existing mechanism),
    not the spell itself.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("tap", {"untap": True, "target_kind": "creature"}),
                EffectSpec("pump", {"keywords": ["hexproof", "reach"], "previous_subject": True}),
                EffectSpec("grant_until", {
                    "target_kind": None, "previous_subject": True, "duration": "end_of_turn",
                    "static": {
                        "type": "grant_triggered_ability",
                        "params": {
                            "trigger_event": "TAPPED",
                            "grant_effects": [
                                {"type": "damage_equal_to_power", "params": {
                                    "target_kind": "creature", "optional": True,
                                }},
                            ],
                        },
                    },
                }),
            ],
            raw_text="Untap target creature. Until end of turn, it gains "
                     "hexproof, reach, and \"Whenever this creature "
                     "becomes tapped, it deals damage equal to its power "
                     "to up to one target creature.\"",
        ),
    ]


register("Legolas's Quick Reflexes", _legolass_quick_reflexes)


def _final_punishment() -> list[AbilitySpec]:
    """Target player loses life equal to the damage already dealt to that
    player this turn.

    — MEC-43 round 4A. RULE 120.3's plain "damage dealt to a player" had no
    per-turn *amount* tracker at all — `GameState.combat_damage_to_players_
    this_turn` is a combat-only per-source hit-*set* ("was this player
    hit", never "how much") and `noncombat_damage_to_opponents_this_turn`
    is keyed by the *dealing* player and scoped to opponents only. New
    `GameState.damage_dealt_to_players_this_turn` (``{player_id: summed
    amount}``, combat and noncombat alike, from any source) closes that —
    incremented at both of `RulesEngine.deal_damage`'s player-damage sites
    (the ordinary branch and the infect-diverted one, since 702.90b
    redirects the life-loss consequence but the damage is still "dealt"),
    reset in `GameEngine.begin_turn`. `LoseLifeEffect`'s new
    ``amount_from_damage_dealt_this_turn`` reads it for whichever player
    this effect resolves against, the same "resolve the target first"
    shape ``amount_from_half_target_life`` (Peer into the Abyss, MEC-43
    round 2) already uses.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("lose_life", {
                "target_kind": "player", "amount_from_damage_dealt_this_turn": True,
            })],
            raw_text="Target player loses life equal to the damage already "
                     "dealt to that player this turn.",
        ),
    ]


register("Final Punishment", _final_punishment)


def _drain_life() -> list[AbilitySpec]:
    """Spend only black mana on X.
    Drain Life deals X damage to any target. You gain life equal to the
    damage dealt, but not more life than the player's life total before
    the damage was dealt, the planeswalker's loyalty before the damage
    was dealt, or the creature's toughness.

    — MEC-43 round 4A. Two new primitives, plus a real pre-existing engine
    bug the card's own "or the planeswalker's loyalty" clause exposed.
    "Spend only `<color>` mana on X" is a genuinely different RULE 605.3a
    shape from every existing spend restriction (`costs.ActivationCost.
    spend_only_chosen_color` locks an *activated ability's whole* cost;
    `mana_source_kind_restriction` locks a *spell's whole* cost by mana
    *source*): the new `AbilitySpec.cast_x_color_restriction` (bound onto
    `GameObject.x_spend_color_restriction`, read by `GameEngine.
    effective_cast_cost`'s ``{X}``-resolution branch) locks only the
    ``{X}`` portion by *color*, via `ManaCost.with_x_colored` — resolving
    ``{X}`` into ``x`` real `COLOR`-kind pips instead of one generic
    `VARIABLE` pip reuses `ManaPool`'s existing colored-pip backtracking
    solver for free, no pool changes needed. The damage+drain clause is one
    new atomic `DamageAndDrainCappedEffect` (the life-gain cap needs the
    target's own life/loyalty/toughness read *before* the damage, the same
    "read first, then act" shape `DestroyLoseLifeEqualManaValueEffect`
    already uses). Along the way: `targeting.legal_targets`'s own "any
    target" (RULE 115.4) turned out to only ever offer creatures and
    players — planeswalkers and battles were never added, a stale gap from
    before either card type was modeled (its own comment said so
    explicitly) — now widened to the real four-way definition, which is
    what makes this card's own planeswalker case reachable at all, and
    should also unlock a stray planeswalker/battle target on every other
    "any target" card already in the cache.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage_and_drain_capped", {"amount": "x", "target_kind": "any"})],
            cast_x_color_restriction="B",
            raw_text="Spend only black mana on X.\n"
                     "Drain Life deals X damage to any target. You gain "
                     "life equal to the damage dealt, but not more life "
                     "than the player's life total before the damage was "
                     "dealt, the planeswalker's loyalty before the damage "
                     "was dealt, or the creature's toughness.",
        ),
    ]


register("Drain Life", _drain_life)


# ---------------------------------------------------------------------------
# MEC-43 round 4B: cEDH staples 2 / K'rrik cEDH trigger-composition cluster
# (ETB / cast / upkeep triggers) — 7 of 8 cards, new primitives: `RulesEngine.
# _collect_self_cast_triggers` (RULE 601.2i "when you cast this spell"),
# `continuous.hand_size_modifier_for`, `ChooseObjectsEffect.player_selector`,
# `ConniveEffect` (RULE 701.47), and `effect_binder`'s new
# `spell_characteristic_equals_chosen_number` trigger predicate. Kozilek's
# own third clause is left a documented gap — see its own docstring.
# ---------------------------------------------------------------------------


def _bontus_monument() -> list[AbilitySpec]:
    """Black creature spells you cast cost {1} less to cast.
    Whenever you cast a creature spell, each opponent loses 1 life and you
    gain 1 life.

    — MEC-43 round 4B. The cast trigger already parses on its own —
    reproduced verbatim. The cost reduction is `cost_reduction`'s existing
    `spell_type`/`spell_color` combination — Ruby Medallion's own
    `spell_color` filter plus the ordinary `spell_type="creature"` one,
    which already compose via plain AND in `continuous.cost_reduction_for`
    but had never been exercised together by a real card before this one.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"}),
                EffectSpec("gain_life", {"amount": 1}),
            ],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "you"},
                "spell_card_types": ["creature"],
            },
            raw_text="Immer wenn du einen Kreaturenzauberspruch wirkst, verliert "
                     "jeder Gegner 1 Leben und du gewinnst 1 Leben.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "spell_type": "creature", "spell_color": "B"})],
            raw_text="Schwarze Kreaturenzaubersprüche, die du wirkst, kosten {1} "
                     "weniger.",
        ),
    ]


register("Bontu's Monument", _bontus_monument)


def _korvold_fae_cursed_king() -> list[AbilitySpec]:
    """Flying
    Whenever Korvold enters or attacks, sacrifice another permanent.
    Whenever you sacrifice a permanent, put a +1/+1 counter on Korvold and
    draw a card.

    — MEC-43 round 4B. Flying folds in via the ordinary keyword catalogue.
    The first trigger is the shipped "~ enters or attacks" multi-event
    trigger (The Wise Mothman) paired with `ChooseObjectsEffect`'s
    mandatory (``optional=False`` default) form — the same "player picks
    which" shape Vraska, Golgari Queen's own sacrifice already uses, just
    forced rather than "you may," with ``exclude_self=True`` for
    "another." The second is Mayhem Devil's `EventType.SACRIFICE` (RULE
    701.17) scoped to ``{"subject": "you"}`` (Rapacious Guest/Mirkwood
    Bats's own precedent for "whenever you sacrifice a permanent/token"),
    pairing `AddCountersEffect`'s default (self, +1/+1, amount 1) with a
    plain draw.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_objects", {"action": "sacrifice", "what": "permanent", "exclude_self": True})],
            trigger={
                "event": [EventType.ENTERS_BATTLEFIELD, EventType.ATTACKS],
                "condition": {"subject": "self"},
            },
            raw_text="Immer wenn Korvold ins Spiel kommt oder angreift, opfere eine "
                     "andere bleibende Karte.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {}), EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.SACRIFICE, "condition": {"subject": "you"}},
            raw_text="Immer wenn du eine bleibende Karte opferst, lege einen "
                     "+1/+1-Marker auf Korvold und ziehe eine Karte.",
        ),
    ]


register("Korvold, Fae-Cursed King", _korvold_fae_cursed_king)


def _kozilek_butcher_of_truth() -> list[AbilitySpec]:
    """When you cast this spell, draw four cards.
    Annihilator 4 (Whenever this creature attacks, defending player
    sacrifices four permanents of their choice.)
    When Kozilek is put into a graveyard from anywhere, its owner shuffles
    their graveyard into their library.

    — MEC-43 round 4B. Annihilator folds in via the ordinary keyword
    catalogue (already real behaviour, RULE 702.86 — `SacrificeEffect`'s
    own ``selector="defending_player"``), unaffected by registering this
    card. The cast trigger needed a genuinely new primitive: "when you
    cast this spell, `<effect>`" (RULE 601.2i/603.2) is a triggered
    ability belonging to the *spell itself*, which only ever exists on the
    stack, not the battlefield, at the moment `SPELL_CAST` fires for it —
    `_collect_triggers`'s main loop is battlefield-only
    (`state.permanents()`), so it could never see this without a
    dedicated scan (`RulesEngine._collect_self_cast_triggers`, new,
    mirroring `_collect_cycled_triggers`/`_collect_suspend_triggers`'s own
    "wrong zone for the main loop" shape).

    **Documented simplification**: the trailing "put into a graveyard
    from anywhere, its owner shuffles their graveyard into their library"
    is left unmodeled — the same call Hostility's own catalogue entry
    already made for the identical primitive gap. RULE 400.7's "from
    anywhere" needs a graveyard-entry event fired uniformly regardless of
    the card's *previous* zone, and this engine's graveyard-bound moves
    reach the graveyard through more than a dozen independent call sites
    across `draw_discard_mixin.py`/`search_mixin.py`/`casting_mixin.py`/
    `damage_death_mixin.py`/`misc_mixin.py`/`copies_mixin.py`/
    `effects.py` (`_move_to_graveyard` is the funnel for only *some* of
    them — sacrifice, SBA death, and a spell resolving to the graveyard,
    not discard or mill, which set `zone = Zone.GRAVEYARD` directly) — a
    genuinely large, cross-cutting primitive disproportionate to build
    correctly for one clause in this batch, unlike the cast trigger above
    (a single well-scoped predicate addition). Left as an open gap rather
    than a half-built event that only fires from some of those sites.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 4})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "self"}},
            raw_text="Wenn du diesen Zauberspruch wirkst, ziehe vier Karten.",
        ),
    ]


register("Kozilek, Butcher of Truth", _kozilek_butcher_of_truth)


def _jin_gitaxias_core_augur() -> list[AbilitySpec]:
    """Flash
    At the beginning of your end step, draw seven cards.
    Each opponent's maximum hand size is reduced by seven.

    — MEC-43 round 4B. Flash folds in via the ordinary keyword catalogue.
    The end-step trigger already parses on its own — reproduced verbatim
    (registering this card makes `specs_for` skip the parser wholesale for
    it, so the parser-claimed half needs reproducing rather than being
    left to fall through, The Wise Mothman's own precedent). The
    hand-size clause is `hand_size_modifier` (new — the numeric sibling of
    the shipped boolean `no_max_hand_size`, `continuous.
    hand_size_modifier_for`), ``affects="opponents"``. ``amount`` is a
    non-negative magnitude — `EffectSpec._clamp_params` floors a literal
    negative int at 0 — with the default (no ``increase`` flag) meaning
    "reduced by," matching `cost_reduction`'s own magnitude+flag
    convention.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 7})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
            raw_text="Zu Beginn deines Endsegments ziehst du sieben Karten.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("hand_size_modifier", {"amount": 7, "affects": "opponents"})],
            raw_text="Die maximale Handkartenanzahl jedes Gegners wird um sieben "
                     "verringert.",
        ),
    ]


register("Jin-Gitaxias, Core Augur", _jin_gitaxias_core_augur)


def _sheoldred_whispering_one() -> list[AbilitySpec]:
    """Swampwalk
    At the beginning of your upkeep, return target creature card from your
    graveyard to the battlefield.
    At the beginning of each opponent's upkeep, that player sacrifices a
    creature of their choice.

    — MEC-43 round 4B. Swampwalk folds in via the ordinary keyword
    catalogue. The first trigger already parses on its own — reproduced
    verbatim (same registered-card reproduction reason as Jin-Gitaxias
    above). The second needed `ChooseObjectsEffect`'s new
    ``player_selector="active_player"`` (the "no subject of its own, read
    live off `GameState.active_player`" idiom `ExileTopOfLibraryEffect`/
    `LandOrFreeCastEffect` already established for Omen Machine) paired
    with a ``phase_relation="not_you"`` upkeep trigger — "each opponent's
    upkeep" fires exactly when the active player is an opponent, so "that
    player" is simply whoever is active when this checks.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_creature", "destination": "battlefield"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            raw_text="Zu Beginn deines Aufwachsegments bringst du eine Ziel-"
                     "Kreaturenkarte aus deinem Friedhof ins Spiel zurück.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_objects", {
                "action": "sacrifice", "what": "creature", "player_selector": "active_player",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "not_you"},
            raw_text="Zu Beginn des Aufwachsegments jedes Gegners opfert dieser "
                     "Spieler eine Kreatur eigener Wahl.",
        ),
    ]


register("Sheoldred, Whispering One", _sheoldred_whispering_one)


def _ledger_shredder() -> list[AbilitySpec]:
    """Flying
    Whenever a player casts their second spell each turn, this creature
    connives.

    — MEC-43 round 4B. Flying folds in via the ordinary keyword catalogue.
    The trigger shape (``is_nth_spell_cast_this_turn``) already parses on
    its own (Hearthborn Battler's own precedent); what blocked the whole
    card was "connives" itself, RULE 701.47 — draw a card, then discard a
    card, +1/+1 counter if the discard was nonland — genuinely new
    (`ConniveEffect`, `RulesEngine.request_choose_objects`'s new
    ``connive`` flag).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("connive", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group"},
                "is_nth_spell_cast_this_turn": 2,
            },
            raw_text="Immer wenn eine Spielerin oder ein Spieler den zweiten "
                     "Zauberspruch in einem Zug wirkt, erlangt diese Kreatur "
                     "Arglist.",
        ),
    ]


register("Ledger Shredder", _ledger_shredder)


def _talion_the_kindly_lord() -> list[AbilitySpec]:
    """Flying
    As Talion enters, choose a number between 1 and 10.
    Whenever an opponent casts a spell with mana value, power, or
    toughness equal to the chosen number, that player loses 2 life and
    you draw a card.

    — MEC-43 round 4B. Flying folds in via the ordinary keyword catalogue.
    The ETB choice is the shipped `ChooseNumberReplacement` (Sanctum
    Prelate's own free-text-numeric RULE 601.2b primitive — no "between 1
    and 10" range validation, the same accepted UI-level simplification
    Sanctum Prelate's own unranged pick already carries). The trigger
    needed one new predicate (``spell_characteristic_equals_chosen_
    number``, `effect_binder._trigger_condition`) comparing `SPELL_CAST`'s
    ``mana_value``/``power``/``toughness`` (the latter two newly stamped
    onto the event by `RulesEngine.cast_spell`/`cast_without_paying`)
    against `GameObject.chosen_number`; "that player loses 2 life" is
    `LoseLifeEffect`'s existing ``selector="event_player"`` (Sheoldred,
    the Apocalypse's own precedent).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_number_on_enter", {})],
            raw_text="Wenn Talion ins Spiel kommt, wähle eine Zahl zwischen 1 und "
                     "10.",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"selector": "event_player", "amount": 2}),
                EffectSpec("draw", {"count": 1}),
            ],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_characteristic_equals_chosen_number": True,
            },
            raw_text="Immer wenn ein Gegner einen Zauberspruch mit Manawert, Stärke "
                     "oder Widerstandskraft gleich der gewählten Zahl wirkt, "
                     "verliert dieser Spieler 2 Leben und du ziehst eine Karte.",
        ),
    ]


register("Talion, the Kindly Lord", _talion_the_kindly_lord)


def _crypt_ghast() -> list[AbilitySpec]:
    """Extort
    Whenever you tap a Swamp for mana, add an additional {B}.

    — MEC-43 round 4B. Extort was parser-recognized (the keyword
    catalogue) but never bound to real behaviour — built here as a
    composition of two already-shipped primitives, not a new one:
    `PayCostThenEffect` (RULE 118.3, ``payer="controller"`` default) for
    the "you may pay {W/B}" optional payment, and `GainLifeEffect`'s
    existing ``count_selector="life_lost_this_way"`` (`GameContext.
    life_lost_this_way`, Gray Merchant of Asphodel's own RULE 119 drain
    accumulator) for "you gain **that much** life" — the total across
    every opponent, not a flat 1, which matters the moment there are 2+
    opponents. The mana ability is Wild Growth's own `EventType.
    TAPPED_FOR_MANA` triggered-mana-ability shape (RULE 605.1b), scoped by
    the ``subtypes`` filter `effect_binder._build_group_ok` already
    supports generically for any subtype word, land or creature alike
    (Burning Earth's own live "nonbasic" board check is the sibling
    precedent for a filter this event doesn't pre-stamp).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{W/B}",
                "effects": [
                    {"type": "lose_life", "params": {"amount": 1, "selector": "each_opponent"}},
                    {"type": "gain_life", "params": {"count_selector": "life_lost_this_way"}},
                ],
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}},
            raw_text="Extort (Immer wenn du einen Zauberspruch wirkst, kannst du "
                     "{W/B} bezahlen. Falls du dies tust, verliert jeder Gegner 1 "
                     "Leben und du gewinnst so viel Leben dazu.)",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["B"]})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land", "subtypes": ["swamp"], "controller": "you"},
                "mana_ability": True,
            },
            raw_text="Immer wenn du einen Sumpf für Mana tappst, erzeuge "
                     "zusätzlich {B}.",
        ),
    ]


register("Crypt Ghast", _crypt_ghast)


# ---------------------------------------------------------------------------
# MEC-43 round 4, cluster C: library / graveyard / search / tokens
# ---------------------------------------------------------------------------


def _syphon_mind() -> list[AbilitySpec]:
    """Syphon Mind (Sorcery, {3}{B})

    "Each other player discards a card. You draw a card for each card
    discarded this way."

    `DiscardEffect`'s new ``draw_per_discard`` param (MEC-43 round 4C)
    queues a ``draw`` as `discard_choice`'s own ``then_specs`` tail for
    every opponent asked to discard — see its own docstring in
    `effects.py` for why this rides that "if you do" tail instead of a
    same-resolution `GameContext` accumulator (`life_lost_this_way`'s
    idiom): a non-forced discard is interactive (the discarding player
    picks their own card), so the true count isn't known synchronously
    the way a destroy/life-loss effect's own count already is.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("discard", {
                "count": 1, "scope": "each_opponent", "draw_per_discard": True,
            })],
            raw_text="Jede andere Spielerin und jeder andere Spieler wirft eine Karte ab. "
                     "Du ziehst für jede auf diese Weise abgeworfene Karte eine Karte.",
        )
    ]


register("Syphon Mind", _syphon_mind)


def _spoils_of_blood() -> list[AbilitySpec]:
    """Spoils of Blood (Instant, {B})

    "Create an X/X black Horror creature token, where X is the number of
    creatures that died this turn."

    `CreateTokenEffect`'s new ``pt_from_count_selector`` param plus
    `continuous.count_selector`'s new ``"creatures_died_this_turn"`` entry
    (both MEC-43 round 4C) — the board-count sibling of the already-
    shipped ``pt_from_trigger_event`` (an X/X token sized off a firing
    event's own field instead of a live board count).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("create_token", {
                "count": 1, "colors": ["B"], "subtypes": ["Horror"],
                "pt_from_count_selector": "creatures_died_this_turn",
            })],
            raw_text="Erschaffe einen X/X schwarzen Schrecken-Kreaturenspielstein, wobei X "
                     "der Anzahl an Kreaturen entspricht, die in diesem Zug gestorben sind.",
        )
    ]


register("Spoils of Blood", _spoils_of_blood)


def _dark_petition() -> list[AbilitySpec]:
    """Dark Petition (Sorcery, {3}{B}{B})

    "Search your library for a card, put that card into your hand, then
    shuffle.
    Spell mastery — If there are two or more instant and/or sorcery cards
    in your graveyard, add {B}{B}{B}."

    The search half is already parser-``MODELED`` as-is (`author_card.py
    reuse`); hand-authored anyway so Spell mastery's own conditional bonus
    mana rides alongside it in one entry, the same "flat effect + a
    conditional extra one" shape Cabal Ritual's Threshold already uses.
    `EffectSpec.condition`'s new ``instant_sorcery_cards_in_graveyard_at_
    least`` key (MEC-43 round 4C) is `cards_in_graveyard_at_least`'s
    type-filtered sibling, reusing `continuous.count_selector`'s already-
    shipped ``"instant_sorcery_or_adventure_cards_in_your_graveyard"``
    entry instead of re-deriving the type filter.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {"criteria": {}, "destination": "hand"}),
                EffectSpec(
                    "add_mana", {"colors": ["B", "B", "B"]},
                    condition={"instant_sorcery_cards_in_graveyard_at_least": 2},
                ),
            ],
            raw_text="Durchsuche deine Bibliothek nach einer Karte, nimm diese Karte auf "
                     "deine Hand und mische danach.\nZaubermeisterschaft — Falls sich "
                     "mindestens zwei Spontanzauber- und/oder Hexereikarten in deinem "
                     "Friedhof befinden, füge {B}{B}{B} hinzu.",
        )
    ]


register("Dark Petition", _dark_petition)


def _demonic_bargain() -> list[AbilitySpec]:
    """Demonic Bargain (Sorcery, {2}{B})

    "Exile the top thirteen cards of your library, then search your
    library for a card. Put that card into your hand, then shuffle."

    `ExileTopOfLibraryEffect`'s ``count`` param (MEC-43 round 4C, widened
    from its original top-**one**-card-only shape) for the first clause;
    the search itself is the plain, already-generic `SearchLibraryEffect`
    — its own "then shuffle" always fires (RULE 701.19e), over whatever
    thirteen fewer cards remain after the exile.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile_top_of_library", {"count": 13}),
                EffectSpec("search", {"criteria": {}, "destination": "hand"}),
            ],
            raw_text="Exiliere die obersten dreizehn Karten deiner Bibliothek, durchsuche "
                     "danach deine Bibliothek nach einer Karte. Nimm diese Karte auf deine "
                     "Hand und mische danach.",
        )
    ]


register("Demonic Bargain", _demonic_bargain)


def _doomsday_excruciator() -> list[AbilitySpec]:
    """Doomsday Excruciator (Creature — Demon, {B}{B}{B}{B}{B}{B}, 6/6)

    "Flying
    When this creature enters, if it was cast, each player exiles all but
    the bottom six cards of their library face down.
    At the beginning of your upkeep, draw a card."

    `ExileTopOfLibraryEffect`'s new ``player_selector="each_player"``/
    ``keep_bottom`` params (MEC-43 round 4C) close the ETB's mass,
    deterministic library exile — "all but the bottom six" is just "the
    top (library size minus six)", no chooser needed since library order
    isn't a real chosen thing this engine exposes a distinction for.
    `EffectSpec.condition`'s existing ``source_was_cast`` (Rocco, Cabaretti
    Caterer) gates it on "if it was cast" (RULE 601.2 — not a reanimated/
    searched/tutored-onto-battlefield entry).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}, raw_text="Flugfähigkeit"),
        AbilitySpec(
            "triggered",
            [EffectSpec(
                "exile_top_of_library",
                {"player_selector": "each_player", "keep_bottom": 6, "face_down": True},
                condition={"source_was_cast": True},
            )],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt: Falls sie gewirkt wurde, exiliert "
                     "jede Spielerin und jeder Spieler alle bis auf die untersten sechs "
                     "Karten ihrer bzw. seiner Bibliothek mit der Bildseite nach unten.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "upkeep"}, "phase_relation": "you"},
            raw_text="Zu Beginn deines Versorgungssegments ziehst du eine Karte.",
        ),
    ]


register("Doomsday Excruciator", _doomsday_excruciator)


def _mizzixs_mastery() -> list[AbilitySpec]:
    """Mizzix's Mastery (Sorcery, {3}{R})

    "Exile target card that's an instant or sorcery from your graveyard.
    For each card exiled this way, copy it, and you may cast the copy
    without paying its mana cost. Exile Mizzix's Mastery.
    Overload {5}{R}{R}{R} (You may cast this spell for its overload cost.
    If you do, change "target" in its text to "each.")"

    Modeled as a direct free-cast window on the exiled card itself
    (`ExileEffect`'s new ``grant_free_cast_window`` param, MEC-43 round
    4C, reusing `RulesEngine.grant_free_cast_window_from_exile` exactly
    as `ExileTopFromEachPlayerCastFreeEffect`/`ReboundFreeCastWindowEffect`
    already do) rather than literally instantiating a second "copy"
    object — nothing this engine tracks distinguishes an uncast copy from
    the real exiled card, and RULE 706.10a means an uncast copy simply
    ceases to exist either way if it isn't cast, so the two are
    behaviourally identical. The trailing self-exile is `ExileEffect`'s
    plain, untargeted self form (``target_kind=None`` — Mnemonic Betrayal-
    shaped).

    **Documented simplification**: Overload (RULE 702.96) isn't bound to
    real behaviour yet — the same posture `Selfless Safewright`'s and
    `City on Fire`'s own catalogue entries already take, which note it
    "come[s] from the RULE 702 keyword catalogue automatically" with no
    real "target"→"each" mode swap. Building that (a genuinely different,
    untargeted effect body reached via an alternative cost) is out of
    scope for this single card's own coverage gate.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {
                    "target_kind": "graveyard_instant_or_sorcery",
                    "grant_free_cast_window": True,
                }),
                EffectSpec("exile", {"target_kind": None}),
            ],
            raw_text="Exiliere eine Zielkarte, die ein Spontanzauber oder eine Hexerei ist, "
                     "aus deinem Friedhof. Kopiere für jede auf diese Weise exilierte Karte "
                     "diese Karte, und du darfst die Kopie wirken, ohne ihre Manakosten zu "
                     "bezahlen. Exiliere Mizzix' Meisterschaft.",
        ),
        AbilitySpec(
            "keyword", [], keyword={"name": "overload", "cost": "{5}{R}{R}{R}"},
            raw_text="Überladung {5}{R}{R}{R}",
        ),
    ]


register("Mizzix's Mastery", _mizzixs_mastery)


def _poison_the_cup() -> list[AbilitySpec]:
    """Poison the Cup (Instant, {1}{B}{B})

    "Destroy target creature. If this spell was foretold, scry 2.
    Foretell {1}{B} (During your turn, you may pay {2} and exile this
    card from your hand face down. Cast it on a later turn for its
    foretell cost.)"

    `EffectSpec.condition`'s new ``source_was_foretold`` key (MEC-43
    round 4C, `GameObject.foretold`) gates the scry — see its own
    docstring in `effects.py` for why nothing ever actually sets that
    flag yet.

    **Documented simplification**: RULE 702.143's own special action
    ("during your turn, pay {2} and exile this card from your hand face
    down; cast it on a later turn for its foretell cost") is a genuinely
    new subsystem — a hand-zone special action plus an alt-cast-from-
    exile path distinct from every alt-cost this engine already has —
    out of scope for this single card's own coverage gate, the same
    posture as Mizzix's Mastery's Overload just above. The Destroy clause
    is real and unconditional either way; the scry is simply never
    reachable until that subsystem lands.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"target_kind": "creature"}),
                EffectSpec("scry", {"count": 2}, condition={"source_was_foretold": True}),
            ],
            raw_text="Zerstöre eine Zielkreatur. Falls dieser Zauberspruch vorausgesagt "
                     "wurde, blicke die obersten 2 Karten deiner Bibliothek durch.",
        ),
        AbilitySpec(
            "keyword", [], keyword={"name": "foretell", "cost": "{1}{B}"},
            raw_text="Vorhersage {1}{B}",
        ),
    ]


register("Poison the Cup", _poison_the_cup)


def _hoarding_broodlord() -> list[AbilitySpec]:
    """Hoarding Broodlord (Creature — Dragon, {5}{B}{B}{B}, 7/6)

    "Convoke
    Flying
    When this creature enters, search your library for a card, exile it
    face down, then shuffle. For as long as that card remains exiled, you
    may play it.
    Spells you cast from exile have convoke."

    The ETB is `SearchLibraryEffect`'s already-shipped
    ``destination="exile_face_down_standing_cast"`` (Praetor's Grasp,
    MEC-42) verbatim — face down, standing (never turn-swept) play
    permission granted to the searcher, ordinary mana cost still applies:
    an exact match for "for as long as that card remains exiled, you may
    play it."

    **Documented simplification**: Convoke (RULE 702.51) isn't bound to
    real creature-tapping cost-payment behaviour yet — the same posture
    `Selfless Safewright`'s/`City on Fire`'s own catalogue entries already
    take, which note it "come[s] from the RULE 702 keyword catalogue
    automatically." The trailing "spells you cast from exile have
    convoke" static grant is left unmodeled for the same reason (nothing
    real to grant until Convoke itself is bound) — both are out of scope
    for this single card's own coverage gate; a real RULE 702.51 build is
    general enough to be worth its own ticket (119 cached cards print
    Convoke).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "convoke"}, raw_text="Anwerben"),
        AbilitySpec("keyword", [], keyword={"name": "flying"}, raw_text="Flugfähigkeit"),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {}, "destination": "exile_face_down_standing_cast",
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, durchsuche deine Bibliothek nach "
                     "einer Karte, exiliere sie mit der Bildseite nach unten und mische "
                     "danach. Du darfst diese Karte spielen, solange sie exiliert bleibt.",
        ),
    ]


register("Hoarding Broodlord", _hoarding_broodlord)


# ---------------------------------------------------------------------------
# MEC-43 round 4D — control / zone changes / entry-choice statics
# ---------------------------------------------------------------------------


def _homeward_path() -> list[AbilitySpec]:
    """Land
    {T}: Add {C}.
    {T}: Each player gains control of all creatures they own.

    — MEC-43 round 4D. The mana ability needs no catalogue entry (a plain
    "{T}: Add {C}." is recognized generically by `mana_abilities_for`).
    The second ability is the new `RegainControlOfOwnedCreaturesEffect`
    (RULE 108.4/110.2) — a straight `GameObject.controller_id` write back
    to each creature's own owner, the untargeted "every player at once"
    sibling of `ExchangeControlEffect`'s single-pair swap.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("regain_control_of_owned_creatures", {})],
            cost={"text": "{T}"},
            raw_text="{t}: Jeder Spieler übernimmt die Kontrolle über alle "
                     "Kreaturen, die ihm gehören.",
        ),
    ]


register("Homeward Path", _homeward_path)


def _heliod_sun_crowned() -> list[AbilitySpec]:
    """Indestructible
    As long as your devotion to white is less than five, Heliod isn't a
    creature.
    Whenever you gain life, put a +1/+1 counter on target creature or
    enchantment you control.
    {1}{W}: Another target creature gains lifelink until end of turn.

    — MEC-43 round 4D. The devotion-gated "isn't a creature" static is
    already fully `MODELED` by the oracle-text parser (`author_card.py`'s
    own "reuse" output, pasted verbatim below) — the two remaining
    clauses need hand-authoring since registering this card overrides the
    parser fallback entirely rather than merging with it. The life-gain
    trigger reuses `EventType.LIFE_GAINED`'s existing ``{"subject": "you"}``
    condition (Prize Pig/Angel of Vitality-shaped) plus a new
    `targeting.py` kind, ``"creature_or_enchantment_you_control"`` (the
    two-type-union sibling of `creature_you_control`). The lifelink grant
    is `PumpEffect`'s already-general 0/0-pump-plus-keyword shape
    (``target_kind="creature"`` already excludes the ability's own source
    by construction, matching the printed "**another** target creature" —
    no new target kind needed).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {
                "remove_types": ["creature"],
                "active_if": {"kind": "control_count", "selector": "devotion_to_white", "max": 4},
            })],
            raw_text="Solange deine Hingabe zu Weiß weniger als fünf beträgt, "
                     "ist Heliod keine Kreatur.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "kind": "+1/+1", "amount": 1,
                "target_kind": "creature_or_enchantment_you_control",
            })],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
            raw_text="Immer wenn du Leben gewinnst, lege eine +1/+1-Marke auf "
                     "eine Zielkreatur oder Zielverzauberung, die du kontrollierst.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"keywords": ["lifelink"], "target_kind": "creature"})],
            cost={"text": "{1}{W}"},
            raw_text="{1}{W}: Eine andere Zielkreatur erhält Lebensverknüpfung "
                     "bis zum Ende des Zuges.",
        ),
    ]


register("Heliod, Sun-Crowned", _heliod_sun_crowned)


def _containment_priest() -> list[AbilitySpec]:
    """Flash
    If a nontoken creature would enter and it wasn't cast, exile it instead.

    — MEC-43 round 4D. Flash is a plain flag keyword (Scryfall-recognized,
    no catalogue entry needed). The replacement effect is the new
    `"uncast_creature_entry_exile"` static (`continuous.
    uncast_creature_entry_exiled`), checked at the same two graveyard/
    library-to-battlefield choke points `graveyard_library_entry_
    prohibited` (Grafdigger's Cage) already uses — reanimation
    (`ReturnFromGraveyardEffect._apply_one`) and a tutor whose destination
    is the battlefield (`RulesEngine._finish_search`) — redirecting to
    exile instead of the plain no-op that prohibition static gives. Same
    documented "not a universal `add_to_battlefield` hook" scope as its
    sibling: a rarer uncast-entry route (cheating a commander out of the
    command zone, a bespoke delayed "return to the battlefield" trigger)
    is left uncovered rather than reworking a foundational engine method.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("uncast_creature_entry_exile", {})],
            raw_text="Falls eine namenlose Kreatur ins Spiel kommen würde und sie "
                     "nicht gewirkt wurde, exiliere sie stattdessen.",
        ),
    ]


register("Containment Priest", _containment_priest)


def _archon_of_valors_reach() -> list[AbilitySpec]:
    """Flying, vigilance, trample
    As this creature enters, choose artifact, enchantment, instant,
    sorcery, or planeswalker.
    Players can't cast spells of the chosen type.

    — MEC-43 round 4D. All three keywords are plain flag keywords
    (Scryfall-recognized, no catalogue entries needed). The "choose a
    card type" pick reuses `ChooseNamedModeReplacement` (RULE 601.2b's
    "as ~ enters, choose <Label1> or <Label2>" family, Struggle for
    Project Purity-shaped) rather than a new replacement class: its five
    printed options slug to exactly the ``is_artifact``/``is_enchantment``/
    ``is_instant``/``is_sorcery``/``is_planeswalker`` attribute names a
    `Card` already carries, so `GameObject.chosen_mode` doubles as the
    chosen card type with no new field. `cast_prohibition` gained a
    matching ``type_from_source_mode`` gate reading it back
    (`continuous.cast_prohibited`), unscoped by ``scope`` (the printed
    "**Players** can't…" already binds this card's own controller too,
    the default whenever ``scope`` isn't narrowed to "opponents").
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_named_mode", {
                "options": ["Artifact", "Enchantment", "Instant", "Sorcery", "Planeswalker"],
            })],
            raw_text="Wenn diese Kreatur ins Spiel kommt, wähle Artefakt, "
                     "Verzauberung, Spontanzauber, Hexerei oder Planeswalker.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {"scope": "all", "type_from_source_mode": True})],
            raw_text="Spieler können keine Zaubersprüche des gewählten Typs wirken.",
        ),
    ]


register("Archon of Valor's Reach", _archon_of_valors_reach)


def _command_beacon() -> list[AbilitySpec]:
    """Land
    {T}: Add {C}.
    {T}, Sacrifice this land: Put your commander into your hand from the
    command zone.

    — MEC-43 round 4D. The mana ability needs no catalogue entry. The
    second is the new `PutCommanderIntoHandEffect` (RULE 903.7) — the
    reverse direction of the far more common "return to the command
    zone" replacement family, a plain zone move for every commander
    currently sitting in this ability's own controller's command zone.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("put_commander_into_hand", {})],
            cost={"text": "{T}, Sacrifice this land"},
            raw_text="{t}, Opfere dieses Land: Nimm deinen Commander aus dem "
                     "Befehlsbereich auf deine Hand.",
        ),
    ]


register("Command Beacon", _command_beacon)


