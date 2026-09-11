"""Card -> AbilitySpec catalogue entries, part 003 of 016.

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

def _seedborn_muse() -> list[AbilitySpec]:
    """Untap all permanents you control during each other player's untap
    step.

    — Seedborn Muse. A new ``"not_you"`` group-trigger controller scope
    (`effect_binder._group_ok`, the mirror image of the existing ``"you"``
    scope) plus a new `TapEffect` ``"permanents_you_control"`` selector
    (`continuous.group_selector_objects` already supported the selector
    itself; only `effects._TAP_SELECTORS`'s whitelist was missing it).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"untap": True, "selector": "permanents_you_control"})],
            trigger={
                "event": EventType.UNTAP,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        )
    ]


register("Seedborn Muse", _seedborn_muse)


def _nether_void() -> list[AbilitySpec]:
    """Whenever a player casts a spell, counter it unless that player pays
    {3}.

    — Nether Void. A plain "group" trigger subject with no ``"controller"``
    filter already matches *any* player's `SPELL_CAST` (the vocabulary's
    unrestricted default); `CounterSpellEffect`'s own ``target_spec``
    (``kind="spell"``) is gathered interactively same as any other
    triggered ability's target — since the triggering spell is pushed onto
    `state.stack` before `SPELL_CAST` fires, it's already a legal option by
    the time the ability asks.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {"unless_pays": "{3}"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group"}},
        )
    ]


register("Nether Void", _nether_void)


def _spellseeker() -> list[AbilitySpec]:
    """When this creature enters, you may search your library for an
    instant or sorcery card with mana value 2 or less, reveal it, put it
    into your hand, then shuffle.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": ["Instant", "Sorcery"], "max_mana_value": 2},
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Spellseeker", _spellseeker)


def _windfall() -> list[AbilitySpec]:
    """Each player discards their hand, then draws cards equal to the
    greatest number of cards a player discarded this way.

    ENG-37 B7 retired the fused `windfall` type. Every player discards their
    whole hand, so "the greatest number a player discarded this way" is the
    greatest hand size *before* the discard — a `bind` whose ``amount``
    measures ``resource: hand_size`` with ``aggregate: max`` over
    ``each_player`` (taken once, before the body), feeding the mass `draw`.
    The mass `discard` (``scope="each_player"``, ``whole_hand=True``) is the
    same first half as Wheel of Fortune.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {
                    "kind": "resource", "resource": "hand_size",
                    "aggregate": "max", "scope": "each_player",
                },
                "effects": [
                    {"type": "discard",
                     "params": {"scope": "each_player", "whole_hand": True}},
                    {"type": "draw",
                     "params": {"selector": "each_player", "count": "$n"}},
                ],
            })],
        )
    ]


register("Windfall", _windfall)


def _ephemerate() -> list[AbilitySpec]:
    """Exile target creature you control, then return it to the
    battlefield under its owner's control.
    Rebound (If you cast this spell from your hand, exile it as it
    resolves. At the beginning of your next upkeep, you may cast this
    card from exile without paying its mana cost.)

    — Ephemerate. Rebound (RULE 702.88b) is now modeled, reusing the
    `create_delayed_trigger`/`GameState.delayed_triggers` primitive Mana
    Drain's own batch built (this docstring previously deferred it as
    blocked on exactly that primitive, citing Mana Drain among others —
    stale the moment that batch shipped; see `AbilitySpec.rebound`'s
    docstring for the "standing free-cast window instead of a forced
    yes/no choice" simplification). The `rebound` marker rides on its own
    empty-effects spec, the same "scan every spec" shape `impulsive_draw_
    on_combat_damage` uses; the blink half is unchanged (`game/effects/core.py`'s
    `BlinkEffect`/`RulesEngine.blink`, RULE 400.7's "exile then immediately
    return").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("blink", {"target_kind": "creature_you_control"})],
        ),
        AbilitySpec(
            "static",
            [],
            rebound=True,
        ),
    ]


register("Ephemerate", _ephemerate)


def _city_of_traitors() -> list[AbilitySpec]:
    """When you play another land, sacrifice this land.
    {T}: Add {C}{C}.

    — City of Traitors. The mana ability is covered by the engine's mana
    model directly off the printed text (no spec needed, same as Eiganjo,
    Seat of the Empire's own `{T}: Add {W}.`). The sacrifice trigger needed
    a new ``"LAND_PLAYED"`` entry in `effect_binder._GROUP_CONTROLLER_
    EVENT_KEYS` (that event only ever carried ``player_id``) plus a stamped
    ``instance_id`` on the event itself (`GameEngine.play_land`) so the
    ``"other"`` subject-condition flag can exclude this land's own play —
    otherwise a land with no other lands yet in play would immediately
    sacrifice itself the moment it was played.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {})],
            trigger={
                "event": EventType.LAND_PLAYED,
                "condition": {"subject": "group", "type": "land", "controller": "you", "other": True},
            },
        )
    ]


register("City of Traitors", _city_of_traitors)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch B3
# ---------------------------------------------------------------------------


def _elesh_norn_grand_cenobite() -> list[AbilitySpec]:
    """Vigilance. Other creatures you control get +2/+2. Creatures your
    opponents control get -2/-2.

    — Elesh Norn, Grand Cenobite. Vigilance is a keyword, already covered
    by the parser's keyword catalogue. The two-sided anthem is two
    independent ``anthem`` static effects on one card — one scoped
    ``"other_creatures_you_control"`` (the existing lord vocabulary), the
    other reusing `group_selector_objects`'s ``"opponents_permanents"``
    selector (built for Manglehorn's "Artifacts your opponents control
    enter tapped.") narrowed to creatures via the shared ``card_type``
    selector param — no new engine surface needed for either half.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "affects": "other_creatures_you_control", "power": 2, "toughness": 2,
                }),
                EffectSpec("anthem", {
                    "affects": "opponents_permanents", "card_type": "creature",
                    "power": -2, "toughness": -2,
                }),
            ],
        )
    ]


register("Elesh Norn, Grand Cenobite", _elesh_norn_grand_cenobite)


def _beast_within() -> list[AbilitySpec]:
    """Destroy target permanent. Its controller creates a 3/3 green Beast
    creature token.

    — Beast Within. ENG-37 B3: a `seq` of `destroy` then `create_token` with
    ``creators="previous_target_controller"`` (the destroyed permanent's
    last-known controller, RULE 608.2h — it survives the move to the
    graveyard), retiring the fused ``destroy_create_token``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "destroy", "params": {"target_kind": "permanent"}},
                {"type": "create_token", "params": {
                    "power": 3, "toughness": 3, "colors": ["G"],
                    "subtypes": ["Beast"],
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Beast Within", _beast_within)


def _natures_claim() -> list[AbilitySpec]:
    """Destroy target artifact or enchantment. Its controller gains 4 life.

    — Nature's Claim. Shipped as a welded `destroy_gain_life_to_controller`
    effect, for the same reason Swords to Plowshares did: the life goes to
    the *target's own* controller, and an operand could not name a referent.
    ENG-37 retired both — the recipient is now
    ``{"of": "previous_target", "as": "controller"}`` on an ordinary
    `gain_life`, with no `bind` needed here because 4 is printed rather than
    measured. ``target_kind="permanent"`` (broader than "artifact or
    enchantment") mirrors Feed the Swarm's composition (`destroy` + `bind`, ENG-37)'s own
    documented simplification.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"target_kind": "permanent"}),
                EffectSpec("gain_life", {
                    "amount": 4,
                    "player": {"of": "previous_target", "as": "controller"},
                }),
            ],
        )
    ]


register("Nature's Claim", _natures_claim)


def _toxic_deluge() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, pay X life.
    All creatures get -X/-X until end of turn.

    — Toxic Deluge. X here comes entirely from the announced additional-
    cost life payment (RULE 601.2b), not a mana ``{X}`` — `RulesEngine.
    cast_spell`/`GameEngine._pay_additional_cast_cost` already thread a
    caller-supplied ``x`` through ``additional_cost={"pay_life": "x"}``
    regardless of whether the printed mana cost itself has a variable
    symbol. `RulesEngine._substitute_x` was extended this batch to also
    rewrite a `pump` effect's own ``power``/``toughness`` fields (not just
    ``amount``/``count``), including a new ``"-x"`` sentinel for an
    X-scaled *debuff* whose X isn't itself negative.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("pump", {"power": "-x", "toughness": "-x", "selector": "all_creatures"})],
            additional_cost={"pay_life": "x"},
        )
    ]


register("Toxic Deluge", _toxic_deluge)


def _goblin_recruiter() -> list[AbilitySpec]:
    """When this creature enters, search your library for any number of
    Goblin cards, reveal them, then shuffle and put those cards on top in
    any order.

    — Goblin Recruiter. The generic search grammar's "up to N" choice loop
    already lets a player decline at any point, and `RulesEngine._finish_
    search` already shuffles first and then places each chosen card at the
    library's top one at a time (the *last* one chosen ends up on top —
    full order control, just reversed-order picking, matching "in any
    order"). "Any number" is modeled as a generous fixed cap (99, far above
    any real deck's Goblin count) rather than a genuinely open-ended count —
    the same "big enough constant" idiom no real deck can actually reach
    the edge of.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Goblin"}, "destination": "library_top", "count": 99,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Goblin Recruiter", _goblin_recruiter)


def _archivist_of_oghma() -> list[AbilitySpec]:
    """Flash. Whenever an opponent searches their library, you gain 1 life
    and draw a card.

    — Archivist of Oghma. Flash is a keyword, already covered by the
    parser's keyword catalogue. `RulesEngine._request_search` already fires
    ``EventType.LIBRARY_SEARCHED`` (``player_id``-keyed) for every search,
    real or fizzled (no eligible cards) — this batch added it to
    `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` so the existing "group" +
    ``controller: "not_you"`` trigger-subject scope (built for Seedborn
    Muse) applies here too.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 1}), EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.LIBRARY_SEARCHED,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        )
    ]


register("Archivist of Oghma", _archivist_of_oghma)


def _leonin_relic_warder() -> list[AbilitySpec]:
    """When this creature enters, you may exile target artifact or
    enchantment. When this creature leaves the battlefield, return the
    exiled card to the battlefield under its owner's control.

    — Leonin Relic-Warder. A new O-Ring-shaped linkage primitive this
    batch: `ExileEffect(remember=True)` stamps the exiled card's own
    ``instance_id`` onto this creature's `GameObject.linked_exile_id`
    (survives however long it stays exiled, arbitrarily many turns);
    `ReturnLinkedExileEffect`, on this creature's own leaves-battlefield
    trigger, reads it back and returns that exact card, clearing the link.
    ``target_kind="permanent"`` (broader than "artifact or enchantment" —
    no target kind unions two card types) is the same documented
    `_TARGET_ROWS` simplification several other catalogue entries use.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "permanent", "optional": True, "remember": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Leonin Relic-Warder", _leonin_relic_warder)


def _dockside_extortionist() -> list[AbilitySpec]:
    """When this creature enters, create X Treasure tokens, where X is the
    number of artifacts and enchantments your opponents control.

    — Dockside Extortionist. A new opponents-scoped `continuous.
    count_selector` entry this batch (``artifacts_and_or_enchantments_
    opponents_control``, the mirror image of the existing "you control"
    one) plus a new `CreateTokenEffect.count_selector` param reading it
    live at resolution.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Treasure",
                "count_selector": "artifacts_and_or_enchantments_opponents_control",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Dockside Extortionist", _dockside_extortionist)


def _zealous_conscripts() -> list[AbilitySpec]:
    """Haste. When this creature enters, gain control of target permanent
    until end of turn. Untap that permanent. It gains haste until end of
    turn.

    — Zealous Conscripts. Haste is a keyword, already covered by the
    parser's keyword catalogue. The ETB is a new atomic
    `GainControlUntilEndOfTurnEffect` this batch — control change, untap,
    and the target's own "gains haste" all bundled into one effect over one
    shared target (no existing "gain control until end of turn" primitive
    existed before this batch; confirmed via `game/effects/core.py` before
    building it — a temporary control change is a materially different,
    simpler shape than Gilded Drake's still-missing *permanent exchange*).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_control_until_eot", {"target_kind": "permanent"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Zealous Conscripts", _zealous_conscripts)


def _liliana_dreadhorde_general() -> list[AbilitySpec]:
    """Whenever a creature you control dies, draw a card.
    +1: Create a 2/2 black Zombie creature token.
    −4: Each player sacrifices two creatures of their choice.
    −9: Each opponent chooses a permanent they control of each permanent
    type and sacrifices the rest.

    — Liliana, Dreadhorde General. The first three abilities are exactly
    what the oracle-text parser already claims (`author_card.py reuse`) —
    pasted as-is. Only the -9 needed a hand-written spec: reframed as
    "sacrifice all but one of each type, one type at a time" —
    `EffectSpec("sacrifice", {"selector": "each_opponent", "what": <type>,
    "count": "all_but_one"})`, `effects.SacrificeEffect`'s dynamic
    ``"all_but_one"`` count sentinel (`RulesEngine.sacrifice`) — six
    separate top-level effects, one per RULE 300-ish permanent type,
    relying on `_apply_effects_partitioned`'s existing "suspend the rest
    when one effect opens a pending_choice" sequencing (RULE 608.2) to run
    them one at a time rather than a bespoke chaining structure.

    Documented simplification: real Liliana lets the *same* multi-typed
    permanent (an artifact creature, say) count as the kept pick for two
    different types in one settling; processing types independently in
    sequence here means a permanent spared by an earlier type's cut can
    still be swept by a later type's own cut if a *different* permanent is
    kept for that type instead. Unobservable for the overwhelming majority
    of real boards (single-typed permanents), and still strictly a choice
    each affected player makes themselves, never an auto-pick.
    """
    types = ["battle", "planeswalker", "creature", "land", "artifact", "enchantment"]
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "type": "creature", "controller": "you", "other": False},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["B"],
                "subtypes": ["Zombie"], "keywords": [], "token_name": "Zombie",
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("sacrifice", {"selector": "each_player", "what": "creature", "count": 2})],
            cost={"loyalty": -4},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("sacrifice", {"selector": "each_opponent", "what": t, "count": "all_but_one"})
                for t in types
            ],
            cost={"loyalty": -9},
        ),
    ]


register("Liliana, Dreadhorde General", _liliana_dreadhorde_general)


def _mutiny() -> list[AbilitySpec]:
    """Target creature an opponent controls deals damage equal to its power
    to another target creature that player controls.

    — Mutiny. The one-sided "fight" shape `effects.DamageEqualToPowerEffect`
    already implements for Rabid Bite ("target creature you control deals
    damage equal to its power to target creature you don't control") — only
    the *dealer* here is also an opponent's creature (RULE 115.1a two
    independent `creature_you_dont_control` targets, `extra_target_specs`),
    not the caster's own.

    Documented simplification: RAW's "**that player**" ties the second
    target to the specific opponent who controls the first (only matters at
    3+ players); both targets are modeled as plain "an opponent controls"
    independently rather than tracking which specific opponent the first
    pick named — the two coincide by construction in any 2-player game, and
    no card in scope needs the distinction (no "same specific opponent"
    targeting constraint exists in this engine yet).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage_equal_to_power", {
                "dealer_kind": "creature_you_dont_control",
                "target_kind": "creature_you_dont_control",
            })],
        ),
    ]


register("Mutiny", _mutiny)


def _anger() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Mountain, creatures you control have haste.

    — Anger. RULE 112.7a's own printed exception: a static ability that
    explicitly functions from the graveyard rather than the battlefield
    (the "Timeshifted enemy-color cycle" — Brawn/Filth/Valor/Wonder are
    the same shape onto trample/swampwalk/first strike/flying, not in
    scope here). ``"from_graveyard": True`` is what `continuous.
    _battlefield_static_abilities` reads to scan each player's graveyard
    for this one marked ability instead of the battlefield — everything
    downstream (the layer-6 keyword grant, the "you control a Mountain"
    `active_if` gate) is the same machinery an ordinary battlefield anthem
    already uses; only the *source's own zone* is unusual. Re-evaluated
    fresh every `continuous.recompute` pass, so this stops granting haste
    the instant either half of the condition stops holding — Anger leaves
    the graveyard, or the last Mountain does.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["haste"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_mountain",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
        ),
    ]


register("Anger", _anger)


def _brawn() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Forest, creatures you control have trample.

    — Brawn, `_anger`'s green sibling (MEC-22): identical
    ``"from_graveyard": True`` shape, just trample/Forest in place of
    haste/Mountain. Brawn's own printed Trample (its first oracle-text
    line) needs no `AbilitySpec` of its own — that's the creature's plain
    printed keyword, read directly off `Card.keywords` by
    `combat.py`/`continuous.py` like any other, independent of this
    catalogue entry.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["trample"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_forest",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
        ),
    ]


register("Brawn", _brawn)


def _filth() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Swamp, creatures you control have swampwalk.

    — Filth, `_anger`'s black sibling (MEC-22). ``"swampwalk"`` is a
    landwalk slug, not a FLAG keyword, but `grant_keyword`'s
    `keywords` list already accepts either shape identically
    (`combat._landwalk_slugs` matches any granted keyword ending
    "walk"), so no different EffectSpec params are needed here than
    Anger's/Brawn's.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["swampwalk"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_swamp",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
        ),
    ]


register("Filth", _filth)


def _valor() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Plains, creatures you control have first strike.

    — Valor, `_anger`'s white sibling (MEC-22).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["first strike"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_plains",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
        ),
    ]


register("Valor", _valor)


def _wonder() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control an
    Island, creatures you control have flying.

    — Wonder, `_anger`'s blue sibling (MEC-22).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["flying"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_island",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
        ),
    ]


register("Wonder", _wonder)


def _riftstone_portal() -> list[AbilitySpec]:
    """{T}: Add {C}.
    As long as this card is in your graveyard, lands you control have
    "{T}: Add {G} or {W}."

    — MEC-22's fifth "from the graveyard" card, and unlike Anger/Brawn/
    Filth/Valor/Wonder it grants a mana ability rather than a keyword
    (`grant_mana_ability` in place of `grant_keyword`, same
    ``"from_graveyard": True`` gate) onto lands rather than creatures
    (``affects="lands_you_control"``), and with no board-state gate of
    its own — unconditional once the card is in the graveyard. Its own
    printed "{T}: Add {C}." mana ability needs no `AbilitySpec` either,
    same reasoning as Brawn's own printed Trample: an ordinary printed
    mana ability is read directly by `mana_abilities.py`, not through
    this catalogue.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "lands_you_control",
                "mana": [{"G": 1}, {"W": 1}],
                "from_graveyard": True,
            })],
        ),
    ]


register("Riftstone Portal", _riftstone_portal)


def _arcane_denial() -> list[AbilitySpec]:
    """Counter target spell. Its controller may draw up to two cards at
    the beginning of the next turn's upkeep.
    You draw a card at the beginning of the next turn's upkeep.

    — Arcane Denial. The second sentence is exactly what the oracle-text
    parser already claims on its own (`author_card.py reuse`) — a plain
    "you draw a card next upkeep" `create_delayed_trigger`, pasted as-is.
    Only the first sentence needed a hand-written spec: the delayed draw
    belongs to the *countered spell's controller*, not this ability's own
    caster — `effects.CreateDelayedTriggerEffect`'s new
    ``capture="target_controller"`` (built for this card), which both
    arms the delayed trigger for *that* player's next upkeep and hands
    the drawn cards to them, reading the countered spell's own
    `GameObject.controller_id` at resolution (the countered spell is long
    gone by the time the delayed half actually fires).

    Documented simplification: "may draw **up to** two" is modeled as an
    unconditional draw of 2 — declining is a real but exceedingly rare
    choice (avoiding a self-mill/deck-out effect), and a delayed trigger
    has no interactive pending_choice machinery to offer it yet.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("counter", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    # "**the** next turn's upkeep" — the very next one,
                    # whoever's turn that turns out to be, not specifically
                    # the countered spell's controller's own next turn
                    # (same reading the parser already gave the second
                    # sentence's identical phrasing, `scope: "any"` below).
                    "scope": "any",
                    "capture": "target_controller",
                    "effects": [{"type": "draw", "params": {"count": 2}}],
                    "description": "Arcane Denial: 2 Karten ziehen",
                }),
            ],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("create_delayed_trigger", {
                "step": "upkeep",
                "scope": "any",
                "effects": [{"type": "draw", "params": {"count": 1}}],
                "description": "Arcane Denial: 1 Karte ziehen",
            })],
        ),
    ]


register("Arcane Denial", _arcane_denial)


def _goldspan_dragon() -> list[AbilitySpec]:
    """Flying, haste
    Whenever this creature attacks or becomes the target of a spell,
    create a Treasure token.
    Treasures you control have "{T}, Sacrifice this artifact: Add two
    mana of any one color."

    — Goldspan Dragon. Flying/haste are keywords, already covered by the
    parser's keyword catalogue. The compound "attacks or becomes the
    target of a spell" trigger is two `AbilitySpec`s (MEC-19's
    `EventType.BECOMES_TARGET` added the second — same "one AbilitySpec
    per event" idiom `_SELF_MULTI_EVENT_RE`/Matoya, Archon Elder's "you
    scry or surveil" use for a compound RULE 603.1 condition), not a
    generalized "attacks or becomes the target of a spell [an opponent
    controls]" parser grammar — only Goldspan Dragon and Tectonic Giant
    print this exact compound (Giggling Skitterspike's own 3-way "attacks,
    blocks, or becomes the target of a spell" is a third, still wider
    shape), too narrow a family to be worth a general regex over two
    hand-authored entries.

    MEC-25 closed this card's own documented simplification: the granted
    ability now upgrades Treasure's printed one-mana version to the real
    printed two — `effects.grant_mana_ability`'s new ``cost`` param
    (`continuous._apply_layer_6_ability`'s ``mana_ability_cost`` handling)
    lets a grant carry a non-``{T}``-only cost and *replace* a matching
    printed ability instead of adding an independent second one (see
    `mana_abilities.mana_abilities_for`'s replace-matching). ``mana`` is
    the same 5-option "any one colour" menu shape `mana_abilities.
    _parse_clause` builds for Treasure's own printed text, just at amount 2.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={
                "event": EventType.BECOMES_TARGET,
                "condition": {"subject": "self"},
                "filter": {"item_kind": "spell"},
            },
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "permanents_you_control",
                "subtype": "Treasure",
                "cost": {"text": "{T}, Sacrifice this artifact"},
                "mana": [{color: 2} for color in ("W", "U", "B", "R", "G")],
            })],
        ),
    ]


register("Goldspan Dragon", _goldspan_dragon)


def _tectonic_giant() -> list[AbilitySpec]:
    """Whenever this creature attacks or becomes the target of a spell an
    opponent controls, choose one —
    • This creature deals 3 damage to each opponent.
    • Exile the top two cards of your library. Choose one of them. Until
    the end of your next turn, you may play that card.

    — Tectonic Giant, MEC-19's second named card. Same "one AbilitySpec per
    compound-triggered event" idiom as Goldspan Dragon's own entry (this
    trigger only needs the ``caster_relation: "opponent"`` filter Goldspan
    Dragon's plain "of a spell" doesn't).

    Documented simplification on the second mode: "exile the top two
    cards, **choose one of them**, until the end of your next turn you may
    play *that* card" is a distinct RULE 601.3b shape from the already-
    shipped `ImpulsiveDrawEffect` ("exile N, *all* of them stay playable")
    — a filtered choice-and-route dig, not a plain reveal-and-window one.
    No shipped primitive covers "exile N, pick 1 to keep playable, discard
    the rest" (7 real cache cards total, `parser_probe.py cards` — its own
    small, real gap, orthogonal to MEC-19's `BECOMES_TARGET` work and not
    built here). Modeled instead with the closest existing effect,
    `impulsive_draw` at ``count=2``: strictly more generous than print
    (both exiled cards stay playable, not just one chosen), same
    "until the end of your next turn" window (``same_turn_only=False``).
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("damage", {"amount": 3, "selector": "each_opponent"})],
                    [EffectSpec("impulsive_draw", {"count": 2, "same_turn_only": False})],
                ],
                "descriptions": [
                    "~ fügt jedem Gegner 3 Schadenspunkte zu.",
                    "Exiliere die obersten zwei Karten deiner Bibliothek. Du "
                    "darfst sie bis zum Ende deines nächsten Zuges spielen.",
                ],
            },
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("damage", {"amount": 3, "selector": "each_opponent"})],
                    [EffectSpec("impulsive_draw", {"count": 2, "same_turn_only": False})],
                ],
                "descriptions": [
                    "~ fügt jedem Gegner 3 Schadenspunkte zu.",
                    "Exiliere die obersten zwei Karten deiner Bibliothek. Du "
                    "darfst sie bis zum Ende deines nächsten Zuges spielen.",
                ],
            },
            trigger={
                "event": EventType.BECOMES_TARGET,
                "condition": {"subject": "self"},
                "filter": {"item_kind": "spell"},
                "caster_relation": "opponent",
            },
        ),
    ]


register("Tectonic Giant", _tectonic_giant)


def _kiki_jiki_mirror_breaker() -> list[AbilitySpec]:
    """Haste
    {T}: Create a token that's a copy of target nonlegendary creature you
    control, except it has haste. Sacrifice it at the beginning of the
    next end step.

    — Kiki-Jiki, Mirror Breaker. Haste is a keyword, already covered by
    the parser's keyword catalogue. The activated ability needed a hand
    spec for its "except it has haste" + "sacrifice it at the beginning
    of the next end step" pair — `effects.CopyPermanentEffect`'s new
    ``haste`` param (grants the copy temp haste directly, rather than a
    second untargeted keyword-grant effect that couldn't tell *which*
    creature just got made), then `create_delayed_trigger`'s new
    ``capture="created_objects"`` to arm a RULE 603.7 delayed
    ``sacrifice_specific`` naming that exact token (`GameContext.
    created_objects`, the same "the tokens…" referent Fabricate/Martial
    Coup already read) — this batch's general primitive for the whole
    "create/return X, it gains haste, [sacrifice/exile] it at the
    beginning of the next end step" template family (~40 real cards
    total between this shape and Puppeteer Clique's reanimate-and-exile
    sibling), not a one-off for this card alone.

    Documented simplification: the real printed restriction is "target
    **nonlegendary** creature you control" — this engine's targeting
    vocabulary has no "nonlegendary" creature kind yet (only the positive
    "legendary permanent"), so it's modeled as a plain "creature you
    control" target; illegally copying a legendary creature just runs
    into the ordinary RULE 704.5j legend-rule SBA like any other route to
    a second legendary permanent, rather than being refused as an illegal
    target the way real Kiki-Jiki refuses it outright.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": "creature_you_control", "count": 1, "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "any",
                    "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "description": "Kiki-Jiki: Kopie opfern",
                }),
            ],
            cost={"taps_self": True},
        ),
    ]


register("Kiki-Jiki, Mirror Breaker", _kiki_jiki_mirror_breaker)


def _puppeteer_clique() -> list[AbilitySpec]:
    """When this creature enters, put target creature card from an
    opponent's graveyard onto the battlefield under your control. It
    gains haste. At the beginning of your next end step, exile it.

    — Puppeteer Clique. The reanimate-and-exile sibling of Kiki-Jiki's
    copy-and-sacrifice template (same batch, same primitives):
    `effects.ReturnFromGraveyardEffect`'s new ``haste`` param plus
    `create_delayed_trigger`'s ``capture="created_objects"`` to arm a
    RULE 603.7 delayed ``exile`` naming the exact permanent this
    resolution just reanimated (`GameContext.created_objects`) — see
    `_kiki_jiki_mirror_breaker`'s docstring for the shared design.
    ``target_kind="opponent_graveyard_creature"`` already exists in
    `targeting.py` for exactly this card (its own docstring names
    Puppeteer Clique as the motivating example).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "opponent_graveyard_creature",
                    "destination": "battlefield",
                    "under_your_control": True,
                    "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "controller",
                    "capture": "created_objects",
                    "effects": [{"type": "exile", "params": {"target_kind": None}}],
                    "description": "Puppeteer Clique: Kreatur verbannen",
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Puppeteer Clique", _puppeteer_clique)


def _mikaeus_the_unhallowed() -> list[AbilitySpec]:
    """Whenever a Human deals damage to you, destroy it.
    Other non-Human creatures you control get +1/+1 and have undying.

    — Mikaeus, the Unhallowed. The anthem is `other_nonhuman_creatures_
    you_control` (`continuous.group_selector_objects`'s new branch — the
    negated-subtype sibling of the existing `other_creatures_you_control`/
    `nonlegendary_creatures_you_control`), carrying both the +1/+1 anthem
    and the undying keyword grant.

    The first clause needed two small additions of its own: a group-
    subject DAMAGE trigger scoped to the *player* recipient specifically
    (`effect_binder`'s new ``condition["recipient_is_you"]`` — the
    existing ``condition["recipient"]`` only ever matches a *permanent*
    recipient's controller, since `RulesEngine.deal_damage` stamps
    ``target_controller_id`` as ``None`` for a player target), and
    `effects.DestroyEffect`'s new ``target_from_trigger_event="source_id"``
    to destroy the Human that actually dealt the damage — a group-subject
    trigger has no single chosen creature the way a self-subject "when ~
    enters" trigger's implicit "it" would, so "it" here has to be read
    back off the firing DAMAGE event itself.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy", {"target_kind": None, "target_from_trigger_event": "source_id"})],
            trigger={
                "event": "DAMAGE",
                "condition": {"subject": "group", "subtypes": ["human"], "recipient_is_you": True},
            },
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "affects": "other_nonhuman_creatures_you_control", "power": 1, "toughness": 1,
                }),
                EffectSpec("grant_keyword", {
                    "affects": "other_nonhuman_creatures_you_control", "keywords": ["undying"],
                }),
            ],
        ),
    ]


register("Mikaeus, the Unhallowed", _mikaeus_the_unhallowed)


def _spark_double() -> list[AbilitySpec]:
    """You may have this creature enter as a copy of a creature or
    planeswalker you control, except it enters with an additional +1/+1
    counter on it if it's a creature, it enters with an additional
    loyalty counter on it if it's a planeswalker, and it isn't legendary.

    — Spark Double. `effects.EnterAsCopyReplacement` (RULE 614.1c/614.12,
    Clever Impersonator's own mechanism), with two additions this batch
    needed: ``target_kind="creature_or_planeswalker_you_control"``
    (`targeting.py`'s new controller-scoped sibling of the existing bare
    "creature or planeswalker" union kind), and the new
    ``extra_counter_if_creature``/``extra_counter_if_planeswalker`` pair
    (`RulesEngine.add_counters`, applied once the copy is made and the
    resulting permanent's real type is known).

    Documented simplification: "**and it isn't legendary**" is not
    modeled — this engine's copy mechanism (`copy_mechanics.become_copy`)
    has no "strip a supertype" primitive (only `add_types`/`add_subtypes`
    exist), so a Spark Double copying a legendary permanent comes in as a
    second copy of that same legendary permanent and runs into the
    ordinary RULE 704.5j legend-rule SBA like any other route to one,
    rather than being exempted from it the way the real card is.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature_or_planeswalker_you_control",
                "extra_counter_if_creature": "+1/+1",
                "extra_counter_if_planeswalker": "loyalty",
            })],
        ),
    ]


register("Spark Double", _spark_double)


def _kari_zevs_expertise() -> list[AbilitySpec]:
    """Gain control of target creature or Vehicle until end of turn.
    Untap it. It gains haste until end of turn.
    You may cast a spell with mana value 2 or less from your hand without
    paying its mana cost.

    — Kari Zev's Expertise. The threaten half reuses `effects.
    GainControlUntilEndOfTurnEffect` (built for Zealous Conscripts,
    already bundling the control change/untap/haste grant) with
    ``target_kind="permanent"`` rather than a creature-only kind, so a
    Vehicle target (an artifact, not a creature until crewed) is reachable
    the same way — narrower than the printed "creature or Vehicle" (any
    artifact is technically eligible here, not just Vehicles), a one-word
    substitution rather than a dedicated Vehicle target kind for this one
    card.

    MEC-20 closed the second sentence — RULE 601.2f's "Expertise" cycle
    template ("you may cast a spell with mana value N or less from your
    hand without paying its mana cost", also on Sram's/Yahenni's/Baral's/
    Rishkar's Expertise), via the new `effects.FreeCastFromHandEffect` and
    the oracle-text handler that now claims the other four automatically
    (`parser/oracle/catalogue/handlers.py`'s ``free_cast_from_hand`` row) —
    this card stays hand-authored only for its first, threaten sentence.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("gain_control_until_eot", {"target_kind": "permanent"})],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("free_cast_from_hand", {"max_mana_value": 2})],
        ),
    ]


register("Kari Zev's Expertise", _kari_zevs_expertise)


def _electrodominance() -> list[AbilitySpec]:
    """Electrodominance deals X damage to any target. You may cast a spell
    with mana value X or less from your hand without paying its mana cost.

    — Electrodominance (MEC-20's own X-scaled "Expertise" cousin — RULE
    601.2f, same template as the Expertise cycle just with an announced
    {X} instead of a literal N, `effects.FreeCastFromHandEffect`'s
    ``criteria={"max_mana_value": "x"}``). Hand-authored rather than
    reached through the oracle-text parser's own ``damage`` handler:
    that handler's regex is digit-only (``NUMBER``, not ``COUNT_X``) and
    widening it to accept the "x" sentinel is a separate, real gap of its
    own (X-cost burn spells generally — Fireball/Rolling Thunder/Banefire-
    shaped, a family this ticket didn't size) rather than a one-line
    change safe to fold into this batch unreviewed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": "x", "target_kind": "any"})],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("free_cast_from_hand", {"max_mana_value": "x"})],
        ),
    ]


register("Electrodominance", _electrodominance)


def _danny_pink() -> list[AbilitySpec]:
    """Creatures you control have "Whenever one or more counters are put
    on this creature for the first time each turn, draw a card."

    — Danny Pink. `grant_triggered_ability` (layer 6, the same quoted-
    ability-grant mechanism the hand-authored Dionus, Elvish Archdruid
    uses for its own per-creature "once each turn" grant): each creature
    you control gets its own `TriggeredAbility` watching its own
    `EventType.COUNTER` firing, capped by ``once_per_turn`` — RULE 603.2's
    "for the first time each turn" phrasing exactly.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec(
                    "grant_triggered_ability",
                    {
                        "affects": "creatures_you_control",
                        "trigger_event": EventType.COUNTER,
                        "once_per_turn": True,
                        "grant_effects": [{"type": "draw", "params": {"count": 1}}],
                    },
                )
            ],
        ),
    ]


register("Danny Pink", _danny_pink)


def _black_market_connections() -> list[AbilitySpec]:
    """At the beginning of your first main phase, choose one or more —
    • Sell Contraband — Create a Treasure token. You lose 1 life.
    • Buy Information — Draw a card. You lose 2 life.
    • Hire a Mercenary — Create a 3/2 colorless Shapeshifter creature
    token with changeling. You lose 3 life.

    — Black Market Connections. The modal shape (RULE 700.2's "choose one
    or more") reuses Farewell's own ``modes={"choose": 1, "at_least":
    True, "options": [...]}`` structure verbatim — the only difference is
    the wrapper: a `STEP_BEGIN` main-phase trigger (``filter: {"step":
    "main1"}``, ``phase_relation: "you"``, the same shape Trystan/Wall of
    Vipers-esque "at the beginning of your first main phase" grants
    already use) instead of a plain spell.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            modes={
                "choose": 1,
                "at_least": True,
                "options": [
                    [
                        EffectSpec("create_token", {"count": 1, "token_name": "Treasure"}),
                        EffectSpec("lose_life", {"amount": 1}),
                    ],
                    [
                        EffectSpec("draw", {"count": 1}),
                        EffectSpec("lose_life", {"amount": 2}),
                    ],
                    [
                        EffectSpec("create_token", {
                            "count": 1, "power": 3, "toughness": 2, "colors": [],
                            "subtypes": ["Shapeshifter"], "keywords": ["changeling"],
                            "token_name": "Shapeshifter",
                        }),
                        EffectSpec("lose_life", {"amount": 3}),
                    ],
                ],
                "descriptions": [
                    "Sell Contraband: Erzeuge einen Schatz. Verliere 1 Leben.",
                    "Buy Information: Ziehe eine Karte. Verliere 2 Leben.",
                    "Hire a Mercenary: Erzeuge einen 3/2 farblosen Gestaltwandler "
                    "mit Wandelbar. Verliere 3 Leben.",
                ],
            },
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "main1"},
                "phase_relation": "you",
            },
        ),
    ]


register("Black Market Connections", _black_market_connections)


def _agathas_soul_cauldron() -> list[AbilitySpec]:
    """You may spend mana as though it were mana of any color to activate
    abilities of creatures you control.
    Creatures you control with +1/+1 counters on them have all activated
    abilities of all creature cards exiled with this artifact.
    {T}: Exile target card from a graveyard. When a creature card is
    exiled this way, put a +1/+1 counter on target creature you control.

    — Agatha's Soul Cauldron. MEC-21 closed both of this card's previously
    unmodeled clauses:

    - The mana-spend permission is `effects.grant_any_color_for_activation`
      (a standing RULE 605.1a wildcard over activation-cost mana, distinct
      from the shipped RULE 605.3a `restriction_predicate_for_cast`/
      `_for_activation` machinery, which restricts *what* a lot of mana can
      pay for rather than *what color* it counts as) — `continuous.
      any_color_for_activation`, consulted by every activation-cost payment
      site in `game/engine/activation_mixin.py`.
    - The dynamic ability grant is `effects.grant_borrowed_activated_
      ability`, reading live off `GameObject.exiled_with_ids` — the
      generalized, *accumulating* "cards exiled with ~" list this card's
      own activated ability below now stamps via `ExileEffect`'s new
      ``track_exiled_with`` param (MEC-21's other named primitive,
      reusable by any future "exile with ~" card; ~185 cached cards print
      that shape). `continuous._apply_borrowed_activated_abilities` builds
      one fresh `ActivatedAbility` per (grantee, exiled creature, ability
      index), reusing the exiled card's own cost/effects (bound once at
      bind-on-load, same as any other permanent's) with each nested
      effect's `.source` redirected to the grantee (RULE 113.7c).

    Documented simplification on the activated ability: the counter
    placement is unconditional rather than gated on "if a **creature** card
    was exiled this way" — this engine's ``exile`` effect has no
    "conditional on the exiled card's own type" follow-up yet (RULE 608.2's
    "when you do" sub-trigger machinery this would need is the same one
    Maestros Theater's cycle uses for its own mandatory "sacrifice it, then
    search" shape, not directly reusable for an optional target's *type*
    instead of a fixed antecedent) — so a noncreature exile still grows a
    counter, strictly more generous than print.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": "any_graveyard_card", "track_exiled_with": True}),
                EffectSpec("add_counters", {"amount": 1, "target_kind": "creature"}),
            ],
            cost={"taps_self": True},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_any_color_for_activation", {"creature_abilities_only": True})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "creatures_you_control",
                "has_counter_kind": "+1/+1",
                "creature_only": True,
            })],
        ),
    ]


register("Agatha's Soul Cauldron", _agathas_soul_cauldron)


def _coercive_recruiter() -> list[AbilitySpec]:
    """Whenever this creature or another Pirate you control enters, gain
    control of target creature until end of turn. Untap that creature.
    Until end of turn, it gains haste and becomes a Pirate in addition to
    its other types.

    — Coercive Recruiter. Simplified in two ways, documented rather than
    guessed at: the trigger only fires on this creature's *own* entry
    (dropping "or another Pirate you control enters" — `GameObject.
    type_words`, the only vocabulary a "group" trigger subject's ``type``
    filter reads, is main card types only, never subtypes, so "Pirate"
    can't be recognized there without a new subtype-aware ENTERS_
    BATTLEFIELD trigger scope, out of this batch's size); and the granted
    "...becomes a Pirate in addition to its other types" tail is dropped
    (no layer-6 temporary-type-grant-on-a-temporarily-controlled-permanent
    primitive exists). Both per the Sword of Forge and Frontier precedent
    (a genuinely partial model, documented, rather than skipping the whole
    card) — the control-change/untap/haste half is the same
    `GainControlUntilEndOfTurnEffect` Zealous Conscripts uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_control_until_eot", {"target_kind": "creature"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Coercive Recruiter", _coercive_recruiter)


def _spirit_of_the_labyrinth() -> list[AbilitySpec]:
    """Each player can't draw more than one card each turn.

    — Spirit of the Labyrinth. A new `draw_limit` static layer this batch,
    the draw-side mirror of the existing `cast_limit` family (Eidolon of
    Rhetoric/Rule of Law/Archon of Emeria) — `RulesEngine._single_draw`
    consults `continuous.max_draws_per_turn` against a new per-player
    `GameState.cards_drawn_this_turn` counter before each individual draw,
    the same "flat global cap, most restrictive wins" shape.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("draw_limit", {"max_per_turn": 1})],
        )
    ]


register("Spirit of the Labyrinth", _spirit_of_the_labyrinth)


def _snap() -> list[AbilitySpec]:
    """Return target creature to its owner's hand. Untap up to two lands.

    — Snap. Two independent targeting effects on one spell (RULE 115.1a) —
    the bounce and the "up to two" land untap — resolved via `StackItem.
    target_groups` (2026-07-16's generalization, previously only exercised
    for a triggered ability's own auto-gathered per-effect target; a caller
    must supply ``target_groups`` explicitly for a spell). `TapEffect`
    gained a ``count`` param this batch (RULE 115.1a's N>=2 generalization,
    mirroring `DestroyEffect.count`) for the "up to two" half.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_to_hand", {"target_kind": "creature"}),
                EffectSpec("tap", {
                    "target_kind": "land_you_control", "untap": True,
                    "optional": True, "count": 2,
                }),
            ],
        )
    ]


register("Snap", _snap)


def _ponder() -> list[AbilitySpec]:
    """Look at the top three cards of your library, then put them back in
    any order. You may shuffle. Draw a card.

    — Ponder. Reuses the existing non-interactive `scry` resolution exactly
    as `RulesEngine.scry` already documents it (a goldfish/solo session has
    no chooser, so it deterministically keeps every looked-at card on top
    in its existing order) — "put them back in any order" and "you may
    shuffle" both have "leave everything exactly as it is" among their
    legal outcomes, so ``scry(3)`` already resolves Ponder correctly at
    this engine's fidelity; a literal "always shuffle" would be a
    *different*, wrong resolution (shuffling is optional, not automatic).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("scry", {"count": 3}), EffectSpec("draw", {"count": 1})],
        )
    ]


register("Ponder", _ponder)


def _mirrormade() -> list[AbilitySpec]:
    """You may have this enchantment enter as a copy of any artifact or
    enchantment on the battlefield.

    — Mirrormade. The same `enter_as_copy` replacement mechanism Phyrexian
    Metamorph/Clever Impersonator use; ``target_kind="permanent"`` is the
    same documented "no type-union target kind" simplification those
    entries already use (admits a creature/land/planeswalker pick too,
    never correct oracle-text-wise but not currently prevented).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "permanent"})],
        )
    ]


register("Mirrormade", _mirrormade)



def _stangg_echo_warrior() -> list[AbilitySpec]:
    """Whenever Stangg attacks, create Stangg Twin, a legendary 3/4 red and
    green Human Warrior creature token. It enters tapped and attacking. For
    each Aura and Equipment attached to Stangg, create a token that's a copy
    of it attached to Stangg Twin. Sacrifice all tokens created this way at
    the beginning of the next end step.

    -- Stangg, Echo Warrior. Hand-authored rather than parsed: (1)
    `normalize` folds the token name "Stangg Twin" -> "~ Twin" (it contains
    the card's own given name), which no `create_token` handler can read;
    (2) the attachment copies use generic `copy_permanent` and `attach`
    operands: the copy reads each attachment on the source and the attach
    node links those copies to the first token this resolution made. The
    delayed "sacrifice all tokens
    created this way" is `create_delayed_trigger`'s existing
    ``capture="created_objects"`` (Kiki-Jiki's template), which grabs the
    whole `created_objects` list -- Stangg Twin plus every attachment copy.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "token_name": "Stangg Twin",
                    "legendary": True,
                    "power": 3,
                    "toughness": 4,
                    "colors": ["R", "G"],
                    "subtypes": ["Human", "Warrior"],
                    "tapped": True,
                    "attacking": True,
                }),
                EffectSpec("seq", {"effects": [
                    {"type": "copy_permanent", "params": {
                        "target_kind": None, "referent": "attachments_each",
                    }},
                    {"type": "attach", "params": {
                        "mover": "created_after_first", "target_kind": "first_created",
                    }},
                ]}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "any",
                    "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "description": "Stangg: erzeugte Tokens opfern",
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Stangg, Echo Warrior", _stangg_echo_warrior)
