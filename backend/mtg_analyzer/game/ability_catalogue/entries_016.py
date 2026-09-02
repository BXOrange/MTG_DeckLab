"""Card -> AbilitySpec catalogue entries, part 016 of 016.

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

def _worldgorger_dragon() -> list[AbilitySpec]:
    """Flying, trample
    When this creature enters, exile all other permanents you control.
    When this creature leaves the battlefield, return the exiled cards to
    the battlefield under their owners' control.

    — MEC-43 round 4D. Both keywords are plain flag keywords. The ETB
    half is `ExileEffect` with the new mandatory ``"other_permanents_you_
    control"`` mass selector (`_MASS_DESTROY_SELECTORS`/
    `_mass_selector_objects`'s newest member — unlike `ExileAnyNumber
    YouControlEffect`'s "any number" *choice*, this is unconditional, so
    it belongs with the plain board-wipe-shaped selectors instead) plus
    ``track_exiled_with=True`` (MEC-21's accumulating `GameObject.
    exiled_with_ids` tracker, newly wired into the selector branch
    alongside its pre-existing targeted-branch support). The
    leaves-battlefield half reuses `ReturnAllExiledWithEffect`
    (``"return_all_exiled_with"``) completely unchanged — built for
    Parallax Wave, and exactly the same shape here: several permanents,
    each returning to *their own* owner, which for Worldgorger Dragon is
    always its own controller since it only ever exiles its own stuff.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "selector": "other_permanents_you_control", "track_exiled_with": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, exiliere alle anderen "
                     "Permanenten, die du kontrollierst.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_all_exiled_with", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur das Schlachtfeld verlässt, bringt jeder "
                     "Besitzer die auf diese Weise exilierten Karten unter seiner "
                     "Kontrolle auf das Schlachtfeld zurück.",
        ),
    ]


register("Worldgorger Dragon", _worldgorger_dragon)


def _jodah_the_unifier() -> list[AbilitySpec]:
    """Legendary creatures you control get +X/+X, where X is the number of
    legendary creatures you control.
    Whenever you cast a legendary spell from your hand, exile cards from
    the top of your library until you exile a legendary nonland card with
    lesser mana value. You may cast that card without paying its mana
    cost. Put the rest on the bottom of your library in a random order.

    — MEC-43 round 4D. The anthem needs no new primitive at all:
    `"anthem"`'s existing ``power_count``/``toughness_count`` params
    (Blackblade Reforged/Nettlecyst-shaped per-unit multipliers) already
    fall through to the ordinary controller-scoped `count_selector`
    vocabulary, which already has a ``"legendary_creatures_you_control"``
    entry (built for Eiganjo, Seat of the Empire's Channel discount) — so
    both the anthem's scope and its own magnitude read the same live
    count, correctly counting Jodah himself. The cast trigger is the new
    `LegendarySpellFreeDigEffect`, riding `RulesEngine.dig_until` (the
    cascade/Possibility Storm-shaped generalized dig) with a criteria
    dict built fresh each firing from the *casting* `SPELL_CAST` event's
    own ``mana_value`` — mirrors Sram, Senior Edificer's own "whenever
    you cast a `<X>` spell" trigger shape (`spell_card_types`, `condition:
    {"controller": "you"}`) plus the `Possibility Storm`-established
    ``filter: {"from_hand": True}`` for "from your hand".
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "legendary_creatures_you_control",
                # ``power``/``toughness`` are the *per-unit* amount when a
                # ``_count`` selector is also set (`continuous.
                # _apply_layer_7_pt`'s own ``pt_mod`` sublayer: "power ...
                # multiplied by that count instead of added as a flat
                # delta") -- 1 per legendary creature, matching the printed
                # "+X/+X, where X is the number of...".
                "power": 1, "toughness": 1,
                "power_count": "legendary_creatures_you_control",
                "toughness_count": "legendary_creatures_you_control",
            })],
            raw_text="Legendäre Kreaturen, die du kontrollierst, erhalten +X/+X, "
                     "wobei X der Anzahl legendärer Kreaturen entspricht, die du "
                     "kontrollierst.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("legendary_spell_free_dig", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["legendary"],
                "filter": {"from_hand": True},
            },
            raw_text="Immer wenn du einen legendären Zauberspruch von deiner Hand "
                     "wirkst, exiliere Karten von oben deiner Bibliothek, bis du "
                     "eine legendäre Nichtlandkarte mit geringerem Manawert "
                     "exilierst. Du kannst jene Karte wirken, ohne ihre "
                     "Manakosten zu bezahlen. Lege den Rest in zufälliger "
                     "Reihenfolge unter deine Bibliothek.",
        ),
    ]


register("Jodah, the Unifier", _jodah_the_unifier)


def _kodama_of_the_east_tree() -> list[AbilitySpec]:
    """Reach
    Whenever another permanent you control enters, if it wasn't put onto
    the battlefield with this ability, you may put a permanent card with
    equal or lesser mana value from your hand onto the battlefield.
    Partner (You can have two commanders if both have partner.)

    — MEC-43 round 4D. Reach and Partner are plain flag keywords. The
    trigger's own body is the new `PutEqualOrLesserManaValueFromHandEffect`
    — the dynamic-mana-value-cap sibling of `PutFromHandOntoBattlefield
    Effect` (Tooth and Nail), reading the just-entered permanent's own
    mana value fresh off `GameContext.trigger_event` each firing rather
    than a literal the catalogue could bake in. It places its pick via
    the new `"hand_to_battlefield"` `request_choose_objects` action
    (`RulesEngine._apply_chosen_object`) specifically so the new
    permanent gets `GameObject.entered_via_ability_id` stamped — read
    back by the trigger's own new ``not_entered_via_self`` condition
    (`effect_binder._build_group_ok`) to satisfy the printed "if it
    wasn't put onto the battlefield with this ability" guard (a
    Panharmonicon-shaped self-recursion block: a permanent Kodama itself
    just placed must not re-trigger Kodama).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("put_equal_or_lesser_mv_from_hand", {})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "permanent", "controller": "you",
                    "other": True, "not_entered_via_self": True,
                },
            },
            raw_text="Immer wenn eine andere Permanente, die du kontrollierst, ins "
                     "Spiel kommt, kannst du, falls sie nicht mit dieser Fähigkeit "
                     "ins Spiel gelegt wurde, eine Permanentenkarte mit gleichem "
                     "oder geringerem Manawert von deiner Hand ins Spiel legen.",
        ),
    ]


register("Kodama of the East Tree", _kodama_of_the_east_tree)


# ---------------------------------------------------------------------------
# MEC-43 round 4E — Tergrid God of Fright, Swift Reconfiguration, Angel's
# Grace, Mesmeric Orb, Smokestack, Oko Thief of Crowns
# ---------------------------------------------------------------------------


def _tergrid_god_of_fright() -> list[AbilitySpec]:
    """Menace
    Whenever an opponent sacrifices a nontoken permanent or discards a
    permanent card, you may put that card from a graveyard onto the
    battlefield under your control.

    — Tergrid, God of Fright's front face (MEC-43 round 4E). Menace comes
    from the RULE 702 keyword catalogue. The trigger is a compound RULE
    603.1 subject ("an opponent sacrifices... or discards...") over *two*
    different event types with the same effect body, so — like Orcish
    Bowmasters' ETB-and-draw pair — it's two `AbilitySpec`s sharing one
    effect list rather than one spec naming two events: `EventType.
    SACRIFICE`'s own ``"nontoken"`` group-subject condition (widened this
    round to apply on its own, not only alongside a ``subtypes`` filter —
    see `effect_binder._build_group_ok`) for the first half, `EventType.
    DISCARD_CARD`'s ``"type"`` condition (an OR-list of every permanent
    type word) for the second — the latter needed `DISCARD_CARD` widened
    to actually carry ``object_types`` at all (`draw_discard_mixin.
    _main_type_words`), since nothing had ever needed to tell a discarded
    permanent card apart from a discarded instant/sorcery before.

    "You may put that card from a graveyard onto the battlefield under
    your control" is `ReturnFromGraveyardEffect`'s own ``trigger_subject_
    key`` mode (RULE 400.7/701.3 reanimation of the *exact* object the
    firing event named, not a fresh RULE 115 target), wrapped in a
    ``cost=""`` `PayCostThenEffect` purely for its "you may... if you do"
    framing (Tenacious Dead's same "remember the trigger subject before
    the interactive choice, since `context.trigger_event` isn't live once
    it's answered" idiom) — genuinely free, no cost is actually paid here.
    """
    _reanimate_sacrificed_or_discarded = EffectSpec("pay_cost_then", {
        "cost": "", "remember_trigger_subject": True,
        "prompt": "Karte unter deine Kontrolle ins Spiel bringen?",
        "effects": [{
            "type": "return_from_graveyard",
            "params": {
                "trigger_subject_key": "remembered", "destination": "battlefield",
                "under_your_control": True,
            },
        }],
    })
    return [
        AbilitySpec(
            "triggered",
            [_reanimate_sacrificed_or_discarded],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "group", "controller": "not_you", "nontoken": True},
            },
            raw_text="Immer wenn ein Gegner eine nicht-Token-Karte für bleibende Karten "
                     "opfert, darfst du jene Karte aus einem Friedhof unter deine "
                     "Kontrolle ins Spiel bringen.",
        ),
        AbilitySpec(
            "triggered",
            [_reanimate_sacrificed_or_discarded],
            trigger={
                "event": EventType.DISCARD_CARD,
                "condition": {
                    "subject": "group", "controller": "not_you",
                    "type": ["artifact", "creature", "enchantment", "land", "planeswalker", "battle"],
                },
            },
            raw_text="Immer wenn ein Gegner eine Karte für bleibende Karten abwirft, "
                     "darfst du jene Karte aus einem Friedhof unter deine Kontrolle "
                     "ins Spiel bringen.",
        ),
    ]


register("Tergrid, God of Fright", _tergrid_god_of_fright)


def _tergrids_lantern() -> list[AbilitySpec]:
    """{T}: Target player loses 3 life unless they sacrifice a nonland
    permanent of their choice or discard a card.
    {3}{B}: Untap Tergrid's Lantern.

    — Tergrid's Lantern, Tergrid's back face (MEC-43 round 4E, registered
    separately — `GameObject.transform` swaps ``card`` to the printed
    back face, whose own ``name`` has no "//" for `specs_for`'s front-face
    fallback to strip, so it needs its own catalogue entry keyed on that
    back name directly).

    "Unless they sacrifice a nonland permanent of their choice or discard
    a card" is a new compound-cost primitive, `ActivationCost.sacrifice_
    or_discard` (confirmed against the cache as a recurring template —
    Starseer Mentor/Thornplate Intimidator/Torment of Scarabs/Torment of
    Venom all print the exact same phrase) — the payer's own choice
    between the two, unlike every other `ActivationCost` field (AND-
    combined). `PayCostThenEffect`'s new ``payer="target"`` mode (this
    round's other new primitive) asks *the targeted player*, not this
    ability's own controller — `request_pay_cost_then`'s existing "pay or
    decline" choice, "pay" now able to open a further `sacrifice_or_
    discard` sub-choice when the payer genuinely has both options
    available (``_pay_sacrifice_or_discard``/`resolve_sacrifice_or_
    discard_choice`, `game/rules/misc_mixin.py`).

    The untap ability reuses `TapEffect`'s existing ``target_kind=None``
    self-untap mode (Grinding Station-shaped) — no new primitive.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("pay_cost_then", {
                "cost": "", "sacrifice_or_discard": True, "payer": "target",
                "target_kind": "player",
                "else_effects": [{"type": "lose_life", "params": {"amount": 3, "target_kind": "player"}}],
            })],
            cost={"text": "{T}"},
            raw_text="{T}: Ein Zielspieler verliert 3 Lebenspunkte, es sei denn, er "
                     "opfert eine nichtländische bleibende Karte eigener Wahl oder "
                     "wirft eine Karte ab.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"target_kind": None, "untap": True})],
            cost={"text": "{3}{B}"},
            raw_text="{3}{B}: Enttappe Tergrids Laterne.",
        ),
    ]


register("Tergrid's Lantern", _tergrids_lantern)


def _swift_reconfiguration() -> list[AbilitySpec]:
    """Flash
    Enchant creature or Vehicle
    Enchanted permanent is a Vehicle artifact with crew 5 and it loses all
    other card types. (It's not a creature unless it's crewed.)

    — MEC-43 round 4E. Flash/"Enchant creature or Vehicle" come from the
    RULE 702 keyword catalogue — the latter needed `targeting.py`'s
    "enchant" quality dispatch widened for a genuine RULE 702.5 compound
    quality (``_ENCHANT_QUALITY_PREDICATES``, unioned by ``" or "`` — every
    real printed card only ever pairs two simple type/subtype words this
    way), since "Vehicle" is a subtype word no existing single-quality
    branch recognized.

    The permanent overwrite is Vraska, Betrayal's Sting's own ``-2``
    template (`type_change`'s ``remove_types``/``add_types``/
    ``add_subtypes``, RULE 613.7f) applied as a *standing* Aura static
    (``affects="attached_permanent"``, Kenrith's Transformation-shaped)
    instead of a resolve-time ``grant_until`` — this is a permanent
    attachment effect, not a one-shot cast trigger. Crew 5 is granted via
    the general `grant_activated_ability` static (its own default
    ``affects="attached_permanent"``), built to exactly mirror what a
    *printed* "Crew N" keyword binds to (`effect_binder._crew_activated_
    ability`): an `ActivationCost.crew_power` cost and a self-targeted
    ``grant_until``/``type_change`` "becomes a creature until end of turn"
    effect — `grant_activated_ability` is a *layer-6 grant*, unlike the
    printed keyword's bind-on-load dispatch, which is exactly what makes
    this reachable at all (the enchanted permanent's own printed keywords
    never include Crew).

    **Documented simplification**: the granted Crew ability doesn't pass
    ``power``/``toughness`` overrides the way `_crew_activated_ability`
    does for a *printed* Vehicle's own ``vehicle_power``/
    ``vehicle_toughness`` — for the overwhelmingly common case (enchanting
    an ordinary creature), this needs no override at all: `Card.power`
    stays whatever was printed regardless of the current layer-4 type
    words, so the crewed permanent's base P/T falls out of the same
    `continuous.recompute` base array every creature already reads. Only
    the rare case of enchanting an *already-printed* Vehicle (rather than
    a creature) would fall back to 0/0 when crewed, since that Vehicle's
    own ``vehicle_power``/``vehicle_toughness`` isn't threaded through a
    static grant authored once for any target.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("type_change", {
                    "affects": "attached_permanent",
                    "add_types": ["artifact"],
                    "remove_types": ["creature", "enchantment", "land", "planeswalker", "battle"],
                    "add_subtypes": ["Vehicle"],
                }),
                EffectSpec("grant_activated_ability", {
                    "affects": "attached_permanent",
                    "cost": {"crew_power": 5},
                    "grant_effects": [{
                        "type": "grant_until",
                        "params": {
                            "target_kind": None, "duration": "end_of_turn",
                            "static": {"type": "type_change", "params": {"add_types": ["creature"]}},
                        },
                    }],
                }),
            ],
            raw_text="Verzauberte bleibende Karte ist ein Vehikel-Artefakt mit Crew 5 "
                     "und verliert alle anderen Kartentypen. (Es ist keine Kreatur, "
                     "außer es ist bemannt.)",
        ),
    ]


register("Swift Reconfiguration", _swift_reconfiguration)


def _angels_grace() -> list[AbilitySpec]:
    """Split second
    You can't lose the game this turn and your opponents can't win the
    game this turn. Until end of turn, damage that would reduce your life
    total to less than 1 reduces it to 1 instead.

    — MEC-43 round 4E. Split second is a plain printed keyword (RULE
    702.60, already enforced by the RULE 702 keyword catalogue's cast-
    timing gate). "You can't lose the game this turn" reuses the existing
    `WinConditionEffect`/`_loss_prevented` machinery (built for a
    *permanent's* standing "you can't lose" static, e.g. Platinum Angel)
    via the new `RulesEngine.grant_cant_lose_this_turn` — installs one
    directly onto the caster's own `player_effects`, turn-scoped instead
    of standing. The damage floor is the new `RulesEngine.
    cap_damage_life_floor` (RULE 104.3a — `Player.player_effects`-scoped
    exactly like RULE 615's `prevent_damage_to_player`, just rewriting the
    amount to land on a fixed floor instead of subtracting a prevented
    chunk).

    **Documented simplification**: "your opponents can't win the game
    this turn" has no engine consequence today — nothing in this engine
    ever makes a player win the game outright (no Door to Nothingness/
    Barren Glory-shaped alternate win condition is modeled; every game
    ends by every-other-player-losing, which "you can't lose" above
    already fully covers for the games this card is actually cast in).
    Tracked nowhere as an open gap since no card needing an explicit win
    condition exists in this project yet.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("grant_cant_lose_this_turn", {}),
                EffectSpec("damage_life_floor", {"floor": 1}),
            ],
            raw_text="Du kannst diesen Zug nicht verlieren und deine Gegner können "
                     "diesen Zug nicht gewinnen. Bis zum Ende des Zuges wird Schaden, "
                     "der deine Lebenspunkte auf weniger als 1 reduzieren würde, "
                     "stattdessen auf 1 reduziert.",
        ),
    ]


register("Angel's Grace", _angels_grace)


def _mesmeric_orb() -> list[AbilitySpec]:
    """Whenever a permanent becomes untapped, that permanent's controller
    mills a card.

    — MEC-43 round 4E, the ticket's own headline engine gap: "becomes
    untapped" had no per-permanent engine event to trigger off at all
    (`EventType.UNTAP` fires once per untap *step*, keyed by player, never
    per permanent). Closed at the root rather than special-cased for this
    one card — `RulesEngine.set_tapped` (already the untap direction's
    real choke point, mirroring how it already fires `TAPPED` for the tap
    direction) now also fires the new `EventType.UNTAPPED`, and every
    other real untap route that used to bypass it (the untap step's own
    per-permanent loop, an ability's own ``{Q}``/"Untap ~" cost) was
    switched to call it too — `TapEffect`'s own ``untap=True`` mode
    already went through `set_tapped` unconditionally, so it needed no
    change to pick this up. `parser/oracle/segmenter.py`'s `_TRIGGER_VERBS`
    then gained the matching "becomes untapped" row, so a future oracle-
    text card with this same trigger phrase parses for free.

    The card's own effect — "**that permanent's controller** mills a
    card", not "you" — needed `MillEffect` widened with a new
    ``selector="event_controller"`` (mirroring `LoseLifeEffect.
    selector="event_player"`/`DealDamageEffect.selector`'s identical
    "read the firing event's own payload" idiom via the shared
    `_event_player` helper), since nothing had ever needed "whoever the
    firing event names" as *mill's* own subject before. Hand-authored
    since the front-end has no grammar yet for a group condition's own
    matched object flowing into its effect's subject.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mill", {"count": 1, "selector": "event_controller"})],
            trigger={"event": EventType.UNTAPPED},
            raw_text="Immer wenn eine bleibende Karte enttappt wird, mischt deren "
                     "Beherrscher eine Karte seiner Bibliothek in seinen Friedhof.",
        ),
    ]


register("Mesmeric Orb", _mesmeric_orb)


def _smokestack() -> list[AbilitySpec]:
    """At the beginning of your upkeep, you may put a soot counter on this
    artifact.
    At the beginning of each player's upkeep, that player sacrifices a
    permanent of their choice for each soot counter on this artifact.

    — MEC-43 round 4E. The first ability is a plain optional self-counter
    add (RULE 122.1), same shape countless other upkeep triggers already
    use. The second reuses Tangle Wire's own "read the count live off the
    source's own counters, offer N picks via the general chooser" shape
    (`TapPermanentsPerCounterEffect`) — its new sibling,
    `SacrificePermanentsPerCounterEffect`, swaps ``action="tap"`` for
    ``"sacrifice"`` and drops Tangle Wire's own artifact/creature/land +
    untapped-only filter (Smokestack taxes *any* permanent).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "soot", "amount": 1})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            optional=True,
            raw_text="Zu Beginn deines Versorgungssegments darfst du eine Rußmarke "
                     "auf dieses Artefakt legen.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_permanents_per_counter", {"kind": "soot"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
            raw_text="Zu Beginn des Versorgungssegments jedes Spielers opfert jener "
                     "Spieler eine bleibende Karte eigener Wahl für jede Rußmarke auf "
                     "diesem Artefakt.",
        ),
    ]


register("Smokestack", _smokestack)


def _oko_thief_of_crowns() -> list[AbilitySpec]:
    """+2: Create a Food token.
    +1: Target artifact or creature loses all abilities and becomes a
    green Elk creature with base power and toughness 3/3.
    -5: Exchange control of target artifact or creature you control and
    target creature an opponent controls with power 3 or less.

    — MEC-43 round 4E. "+2" is a plain Food token creation, the same
    ``create_token`` shape every other Food-maker in this cache already
    uses. "+1" is the already-shipped Elk template (Kenrith's
    Transformation) reused resolve-time — two chained ``grant_until``
    effects at ``duration="rest_of_game"`` (Vraska, Betrayal's Sting's own
    ``-2`` established this exact "permanent characteristic overwrite via
    a resolve-time grant, not a `temp_*` pump" idiom), the second reusing
    the first's own target via ``previous_subject`` so only one RULE 115
    target is asked for both clauses.

    "-5" needed `ExchangeControlEffect` widened into a genuine **two-
    target** mode (``first_target_kind``/``second_creature_filter``, via
    `GameEffect.extra_target_specs`): unlike Gilded Drake/Volatile
    Stormdrake (always "this creature and up to one target creature" —
    one side is the ability's own source), *both* sides here are
    independently-chosen targets, neither optional (Oko's own text prints
    no "up to"/failure clause). The first target's own kind
    (``artifact_or_creature_you_control``) and the second's own qualifier
    (``creature_you_dont_control`` + ``creature_filter={"max_power": 3}``)
    both needed small `targeting.py` additions — a controller-scoped
    "artifact or creature" union kind (mirroring `creature_or_
    planeswalker_you_control`'s identical shape for its own pair), and
    `creature_you_dont_control` honouring `TargetSpec.creature_filter` at
    all (every existing caller of that kind never set one, so this is
    purely additive).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            cost={"loyalty": 2},
            raw_text="+2: Erschaffe einen Nahrungs-Spielstein.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "target_kind": "artifact_or_creature", "duration": "rest_of_game",
                    "static": {"type": "remove_all_abilities", "params": {}},
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {
                        "type": "type_change",
                        "params": {
                            "add_types": ["creature"], "set_subtypes": ["Elk"],
                            "power": 3, "toughness": 3,
                        },
                    },
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "color_change", "params": {"colors": ["G"], "set": True}},
                }),
            ],
            cost={"loyalty": 1},
            raw_text="+1: Ziel-Artefakt oder Ziel-Kreatur verliert alle Fähigkeiten und "
                     "wird zu einem grünen Elch mit den Grundwerten 3/3.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_control", {
                "first_target_kind": "artifact_or_creature_you_control",
                "target_kind": "creature_you_dont_control",
                "second_creature_filter": {"max_power": 3},
            })],
            cost={"loyalty": -5},
            raw_text="−5: Tausche die Kontrolle über Ziel-Artefakt oder Ziel-Kreatur "
                     "unter deiner Kontrolle und Ziel-Kreatur, die ein Gegner "
                     "kontrolliert, mit Stärke 3 oder weniger.",
        ),
    ]


register("Oko, Thief of Crowns", _oko_thief_of_crowns)


def _krrik_son_of_yawgmoth() -> list[AbilitySpec]:
    """Lifelink
    For each {B} in a cost, you may pay 2 life rather than pay that mana.
    Whenever you cast a black spell, put a +1/+1 counter on K'rrik.

    — MEC-43 round 4F. Lifelink is a plain printed keyword, bound
    independent of catalogue registration (see Tymna the Weaver's own
    docstring for the convention). The alternative-payment clause is a
    genuinely new primitive — broader than every existing wildcard-color
    mechanism (RULE 605.1a's `grant_any_color_for_activation`/
    `GameState.mana_wildcard_permission`, both of which only ever relax
    *which* mana pays a pip): `grant_life_for_mana_pip` is a standing
    permission (`continuous.life_for_mana_pip_color`) consulted at the two
    real cost-payment sites — casting (`game/engine/casting_mixin.py`'s
    `can_cast`, `game/rules/casting_mixin.py`'s actual payment) and
    activating (`game/engine/activation_mixin.py`'s `_can_pay_activation_
    cost`/`_pay_activation_cost`/`_max_x_for_mana`) — threaded into
    `ManaPool.can_pay`/`pay`'s new `extra_life_color` param, which gives a
    plain {B} pip the same life-payment option a printed Phyrexian pip
    already has (`mana_pool.KRRIK_LIFE_PER_BLACK_PIP` — 2 life, same price
    RULE 702.85a already charges). The counter trigger reuses the existing
    `cast_of_color` trigger-condition key (Runaway Steam-Kin's own
    template) with no intervening-if.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_life_for_mana_pip", {"color": "B"})],
            raw_text="Für jedes {B} in den Kosten darfst du 2 Lebenspunkte "
                     "bezahlen, anstatt dieses Mana zu bezahlen.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "amount": 1, "target_kind": None})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "cast_of_color": "B",
            },
            raw_text="Immer wenn du einen schwarzen Zauberspruch wirkst, "
                     "lege eine +1/+1-Marke auf K'rrik.",
        ),
    ]


register("K'rrik, Son of Yawgmoth", _krrik_son_of_yawgmoth)


def _maralen_of_the_mornsong() -> list[AbilitySpec]:
    """Players can't draw cards.
    At the beginning of each player's draw step, that player loses 3 life,
    searches their library for a card, puts it into their hand, then
    shuffles.

    — MEC-43 round 4F. Both clauses were nearly free once diagnosed
    against Omen Machine (MEC-33), which already built the identical
    "Players can't draw cards. At the beginning of each player's draw
    step, …" template. (1) The flat `draw_limit` static at
    `max_per_turn=0` needs no new code at all — same as Omen Machine's own
    first clause. (2) The replacement action reuses Omen Machine's own
    unscoped `STEP_BEGIN`/"draw" trigger (only the active player ever has
    a draw step, so leaving it unnarrowed by `phase_relation` already
    fires it once per turn, for whoever that is — RULE 500.7). Its body
    needed exactly one new selector: `LoseLifeEffect.selector` gained
    `"active_player"` (mirroring `DealDamageEffect`'s own sentinel of the
    same name); `SearchLibraryEffect` needed nothing new at all — its
    untargeted `player` resolution (`apply`'s ``player = self.player or
    context.active_player``) already defaults to the active player
    whenever no explicit ``player`` is given, exactly what an unscoped
    "that player searches…" clause needs.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("draw_limit", {"max_per_turn": 0})],
            raw_text="Players can't draw cards.",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"amount": 3, "selector": "active_player"}),
                EffectSpec("search", {"criteria": "", "destination": "hand", "optional": False}),
            ],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "draw"}},
            raw_text="Zu Beginn des Ziehschritts jedes Spielers verliert dieser "
                     "Spieler 3 Lebenspunkte, durchsucht seine Bibliothek nach "
                     "einer Karte, nimmt sie auf die Hand und mischt danach "
                     "seine Bibliothek.",
        ),
    ]


register("Maralen of the Mornsong", _maralen_of_the_mornsong)


def _keen_duelist() -> list[AbilitySpec]:
    """At the beginning of your upkeep, you and target opponent each
    reveal the top card of your library. You each lose life equal to the
    mana value of the card revealed by the other player. You each put the
    card you revealed into your hand.

    — MEC-43 round 4F. A genuinely new simultaneous, two-player
    reveal-and-compare — no existing shape combines "each of two players
    reveals a card" with "each player's own life loss reads the *other*
    player's reveal" (the single-player `RevealTopThenTakeAndLoseLifeEffect`
    (MEC-12, Dark Confidant) only ever reads a player's own revealed
    card). Built as one atomic `MutualRevealCompareManaValueEffect`
    (`mutual_reveal_compare_mana_value`) rather than two effects sharing a
    resolve-time referent, since both reveals must happen before either
    life total changes. Fully deterministic (no player choice beyond RULE
    115's own opponent target), so no interactive `pending_choice`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mutual_reveal_compare_mana_value", {"target_kind": "opponent"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            raw_text="Zu Beginn deines Aufwärmschritts deckt jeder Spieler, "
                     "du und ein Gegner deiner Wahl, die oberste Karte "
                     "seiner Bibliothek auf. Jeder Spieler verliert so "
                     "viele Lebenspunkte, wie der Manawert der vom anderen "
                     "Spieler aufgedeckten Karte beträgt. Jeder Spieler "
                     "nimmt die von ihm aufgedeckte Karte auf die Hand.",
        ),
    ]


register("Keen Duelist", _keen_duelist)


def _scroll_rack() -> list[AbilitySpec]:
    """{1}, {T}: Exile any number of cards from your hand face down. Put
    that many cards from the top of your library into your hand. Then
    look at the exiled cards and put them on top of your library in any
    order.

    — MEC-43 round 4F. RULE 701.20a-adjacent: reuses `GameObject.
    face_down_in_exile` (Beseech the Mirror's own face-down exile),
    `RulesEngine.request_choose_objects`'s ``track_exiled_with`` (MEC-21)
    for the "any number" pick, and the scry/surveil two-phase "order the
    rest back on top" machinery (`RulesEngine._LOOK_TOP_KINDS`) for the
    final ordering step — the only genuinely new piece is putting cards
    that started in *exile* back onto the library instead of reordering
    cards already there (`_finish_look_top`'s new ``"scroll_rack"``
    branch, `RulesEngine.open_scroll_rack_order_choice`). Built as two
    chained effects (`scroll_rack_exile`/`scroll_rack_finish`,
    `ScrollRackEffect`/`ScrollRackFinishEffect`) rather than one, since
    "how many cards to draw and which need reordering" is only known once
    the exile-any-number choice actually resolves (``then_specs``).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("scroll_rack_exile", {})],
            cost={"text": "{1}", "taps_self": True},
            raw_text="{1}, {T}: Verbanne eine beliebige Anzahl Karten "
                     "verdeckt aus deiner Hand. Nimm so viele Karten vom "
                     "oberen Ende deiner Bibliothek auf die Hand. Sieh dir "
                     "danach die verbannten Karten an und lege sie in "
                     "beliebiger Reihenfolge oben auf deine Bibliothek.",
        ),
    ]


register("Scroll Rack", _scroll_rack)


def _dance_of_the_dead() -> list[AbilitySpec]:
    """Enchant creature card in a graveyard
    When this Aura enters, if it's on the battlefield, it loses "enchant
    creature card in a graveyard" and gains "enchant creature put onto
    the battlefield with this Aura." Put enchanted creature card onto the
    battlefield tapped under your control and attach this Aura to it.
    When this Aura leaves the battlefield, that creature's controller
    sacrifices it.
    Enchanted creature gets +1/+1 and doesn't untap during its
    controller's untap step.
    At the beginning of the upkeep of enchanted creature's controller,
    that player may pay {1}{B}. If the player does, untap that creature.

    — MEC-43 round 4F, RULE 704.5n Necromancy-shaped. Reuses Animate
    Dead's own reanimate-Aura core wholesale (`ReturnFromGraveyardEffect
    (target_kind="self_enchant_target")`/`AttachEffect(target_kind=
    "created")`/`SacrificeAttachedPermanentEffect` — see that entry's own
    docstring for the three primitives the whole family rides on:
    `GameObject.reanimate_target_id`, the graveyard-wide `targeting.
    legal_targets` branch, and `RulesEngine._resolve_permanent_spell`'s
    "leave unattached instead of failing" special-case for a graveyard-zone
    attach target). The one difference from Animate Dead's reanimate
    clause is "tapped" instead of a P/T rider — already a plain param
    (`tapped=True`, MEC-43 round 2's Tenacious Dead). The +1/+1 anthem and
    "doesn't untap" are both free, already-``affects="attached_permanent"``
    reuses (`anthem`/`no_untap` — Paralyzing Grasp already prints the
    latter on an enchanted host). The pay-or-untap upkeep clause needed two
    small, genuinely general additions rather than a one-off: RULE 500.7's
    ``phase_relation`` gained a third value, ``"attached_permanent"``
    (`effect_binder._trigger_condition`, read live off `source.
    attached_to`'s *current* controller rather than the ability's own
    source's controller — so the trigger stays correctly silent during the
    brief window before the ETB trigger has attached this Aura to
    anything), and `PayCostThenEffect.payer` (RULE 118.3) gained the same
    sentinel, so "that player may pay" asks the *enchanted creature's*
    controller, not the Aura's own. The untap itself is `TapEffect
    (target_kind="attached_permanent", untap=True)`, already built for
    Freed from the Real/Pemmin's Aura.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "self_enchant_target",
                    "under_your_control": True,
                    "tapped": True,
                }),
                EffectSpec("attach", {"target_kind": "created"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When this Aura enters, if it's on the battlefield, "
                     "it loses \"enchant creature card in a graveyard\" "
                     "and gains \"enchant creature put onto the "
                     "battlefield with this Aura.\" Put enchanted "
                     "creature card onto the battlefield tapped under "
                     "your control and attach this Aura to it.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_attached_permanent", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When this Aura leaves the battlefield, that "
                     "creature's controller sacrifices it.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1})],
            raw_text="Enchanted creature gets +1/+1.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("no_untap", {"affects": "attached_permanent"})],
            raw_text="Enchanted creature doesn't untap during its "
                     "controller's untap step.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{1}{B}",
                "payer": "attached_permanent",
                "effects": [
                    {"type": "tap", "params": {"target_kind": "attached_permanent", "untap": True}},
                ],
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "attached_permanent",
            },
            raw_text="At the beginning of the upkeep of enchanted "
                     "creature's controller, that player may pay {1}{B}. "
                     "If the player does, untap that creature.",
        ),
    ]


register("Dance of the Dead", _dance_of_the_dead)


def _rings_of_brighthearth() -> list[AbilitySpec]:
    """Whenever you activate an ability, if it isn't a mana ability, you may
    pay {2}. If you do, copy that ability. You may choose new targets for
    the copy.

    — Rings of Brighthearth, MEC-43 round 4G. `EventType.ACTIVATED_ABILITY`
    already fires for every non-mana activated ability (RULE 605.1a mana
    abilities never use the stack, so "isn't a mana ability" needs no
    separate check — the same fact `Flamescroll Celebrant`/`Runic Armasaur`
    already document), and `pay_cost_then` (RULE 118.3) already handles the
    optional {2}. The genuinely new part is copying an ability that's
    already on the stack (RULE 706.10): `CopyAbilityEffect`/`RulesEngine.
    copy_ability` are the ability-item siblings of the existing spell-copy
    machinery (`CopySpellEffect`/`copy_spell`), identifying "that ability"
    by `StackItem.stack_id` (ENG-26) instead of a `GameObject.instance_id`
    — remembered onto `GameObject.remembered_stack_id` by
    `remember_trigger_stack_id=True` at the ability's first, still-live
    `apply()`, since the "if you do" branch only runs once the pay-or-not
    choice is answered, by which point `context.trigger_event` has closed.

    **Documented simplification**: "you may choose new targets for the
    copy" keeps the original's targets, the same MVP `CopySpellEffect`
    already establishes for a spell copy.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{2}",
                "effects": [{"type": "copy_ability", "params": {}}],
                "remember_trigger_stack_id": True,
            })],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "you"},
            },
            raw_text="Immer wenn du eine Fähigkeit aktivierst, darfst du, "
                     "falls es keine Manafähigkeit ist, {2} bezahlen. Falls "
                     "du dies tust, kopiere diese Fähigkeit. Du kannst neue "
                     "Ziele für die Kopie wählen.",
        )
    ]


register("Rings of Brighthearth", _rings_of_brighthearth)


def _isochron_scepter() -> list[AbilitySpec]:
    """Imprint — When this artifact enters, you may exile an instant card
    with mana value 2 or less from your hand.
    {2}, {T}: You may copy the exiled card. If you do, you may cast the
    copy without paying its mana cost.

    — Isochron Scepter, MEC-43 round 4G. The first line is `ImprintEffect`
    (MEC-17, Chrome Mox) widened with two new filter params —
    ``include_card_type="instant"`` (an *inclusion* filter, the opposite
    direction of Chrome Mox's own exclusion list) and ``max_mana_value=2``.
    The repeatable activated ability is the genuinely new part —
    `CopyImprintedCardEffect`: builds a fresh token copy of the imprinted
    card straight into exile (never touching the battlefield, the same
    RULE 722.3c idiom `make_prepared` already uses) and opens its
    `grant_free_cast_window_from_exile` window, the same MEC-20/Beseech
    the Mirror "reaches the ordinary cast action with full targeting"
    idiom — repeatable, since the original imprinted card is never itself
    cast and stays put for the rest of the game.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("imprint", {
                "include_card_type": "instant",
                "max_mana_value": 2,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Imprint — Wenn dieses Artefakt ins Spiel kommt, darfst "
                     "du eine Spontanzauber-Karte mit Manawert 2 oder "
                     "weniger aus deiner Hand exilieren.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("copy_imprinted_card", {})],
            cost={"text": "{2}", "taps_self": True},
            raw_text="{2}, {T}: Du kannst die exilierte Karte kopieren. "
                     "Falls du dies tust, kannst du die Kopie wirken, ohne "
                     "ihre Manakosten zu bezahlen.",
        ),
    ]


register("Isochron Scepter", _isochron_scepter)


def _aluren() -> list[AbilitySpec]:
    """Any player may cast creature spells with mana value 3 or less
    without paying their mana costs and as though they had flash.

    — Aluren, MEC-43 round 4G. A standing, board-wide free-cast permission
    scoped to **any** player, not just this enchantment's own controller —
    the first free-cast grant in this engine not scoped to one controller.
    Modeled as a genuine standing permission (`continuous.has_standing_
    free_cast_permission`/`standing_free_cast_grants_flash`, `EffectSpec(
    "free_cast_permission", ...)`), consulted live by `GameEngine.can_cast`
    and offered by `_offer_cast`/`_castable_now_or_via_potential` (the same
    "second, independent payment method alongside the plain mana-cost one"
    idiom MEC-15 already built for a per-object `free_cast_condition`) —
    not an armed per-card flag, since Aluren covers every qualifying
    creature spell in every hand at the table, not one specific card.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("free_cast_permission", {
                "creature_only": True,
                "max_mana_value": 3,
                "any_player": True,
                "grants_flash": True,
            })],
            raw_text="Jeder Spieler darf Kreaturenzaubersprüche mit "
                     "Manawert 3 oder weniger wirken, ohne ihre Manakosten "
                     "zu bezahlen, und so, als hätten sie Blitzschnelligkeit.",
        )
    ]


register("Aluren", _aluren)


def _knowledge_pool() -> list[AbilitySpec]:
    """Imprint — When this artifact enters, each player exiles the top
    three cards of their library.
    Whenever a player casts a spell from their hand, that player exiles
    it. If the player does, they may cast a spell from among other cards
    exiled with this artifact without paying its mana cost.

    — Knowledge Pool, MEC-43 round 4G. The first line is `ExileTopOfLibrary
    Effect` widened with ``player_selector="each_player"``/``count=3``/
    ``track_exiled_with=True`` — the RULE 601.2c mass "each player" form,
    each player's own top three seeding the shared imprint pool
    (`GameObject.exiled_with_ids`, MEC-21). The second line is a genuine
    cast-substitution mechanism (`ExileCastSpellIntoImprintPoolEffect`):
    intercepts *any* player's cast from hand (RULE 603.3d reflexive,
    Possibility Storm-shaped trigger — unscoped "a player", not just this
    artifact's controller), exiles the just-cast spell straight off the
    stack into the same shared pool via `RulesEngine.move_spell_off_stack`,
    then offers that player a `request_choose_objects` pick of exactly one
    *other* pool member to grant a free-cast window (MEC-20's `"grant_free_
    cast"` action) — already zone-agnostic, so an exiled candidate reaches
    `legal_actions` with full targeting exactly like a hand card would.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_top_of_library", {
                "player_selector": "each_player",
                "count": 3,
                "track_exiled_with": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Imprint — Wenn dieses Artefakt ins Spiel kommt, "
                     "exiliert jeder Spieler die obersten drei Karten "
                     "seiner Bibliothek.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_cast_spell_into_imprint_pool", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "filter": {"from_hand": True},
                "reflexive": True,
            },
            raw_text="Immer wenn ein Spieler einen Zauberspruch aus seiner "
                     "Hand wirkt, exiliert jener Spieler ihn. Falls das "
                     "geschieht, kann er einen Zauberspruch unter den "
                     "anderen mit diesem Artefakt exilierten Karten "
                     "wirken, ohne dessen Manakosten zu bezahlen.",
        ),
    ]


register("Knowledge Pool", _knowledge_pool)


def _earthshape() -> list[AbilitySpec]:
    """Earthshape (Instant, {2}{W})

    "Earthbend 3. Then each creature you control with power less than or
    equal to that land's power gains hexproof and indestructible until end
    of turn. You gain hexproof until end of turn."

    — PAR-30, the last card of the Earthbend residue cluster. Hand-authored
    rather than parsed: the "power <= that land's power" threshold is a
    read of the just-earthbent land's power that no general handler
    warrants building for one Avatar-set singleton.

    Two documented simplifications:
    - **"that land's power" is modeled as the literal earthbend amount
      (3).** RULE 701.66's earthbend makes the target land a 0/0 that then
      gets N +1/+1 counters, i.e. exactly N/N, so "that land's power" is 3
      absent any other P/T modifier on that land — the common case.
      `PumpEffect.creature_filter` (which now also narrows the
      ``selector``-group branch, not just the targeted one) carries the
      ``max_power`` bound; `combat.matches_object_filter` is the same
      predicate `TargetSpec.creature_filter` uses everywhere else. The
      animated land itself is a 3/3 creature you control and so is
      (correctly) among the protected creatures.
    - **"You gain hexproof until end of turn" is dropped.** Player-level
      hexproof is a deliberately-unmodeled concept in this engine (same
      call as Veil of Summer's player-level hexproof in the Kinnan/M-K
      batch) — a whole targeting-legality subsystem for one rider.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("earthbend", {"amount": 3}),
                EffectSpec("pump", {
                    "selector": "creatures_you_control",
                    "creature_filter": {"max_power": 3},
                    "keywords": ["hexproof", "indestructible"],
                }),
            ],
            raw_text="Erdbändige 3. Dann erhält jede Kreatur, die du kontrollierst "
                     "und deren Stärke kleiner oder gleich der Stärke jenes Landes "
                     "ist, Fluchsicherheit und Unzerstörbarkeit bis zum Ende des "
                     "Zuges. Du erhältst Fluchsicherheit bis zum Ende des Zuges.",
        )
    ]


register("Earthshape", _earthshape)


# ---------------------------------------------------------------------------
# Incubate (RULE 701.53) residue — the three cache singletons the PAR-30
# parser trail left, each blocked on its own bespoke shape rather than on
# incubate grammar (that shipped in v160/v162). Hand-authored per this
# repo's escape valve (docs/Reference/11); the incubate itself is the
# standard `create_token` "Incubator" + `extra_counters` {+1/+1} pattern
# `Glissa, Herald of Predation` established, sized by a count source.
# ---------------------------------------------------------------------------


def _traumatic_revelation() -> list[AbilitySpec]:
    """Target opponent reveals their hand. You may choose a creature or
    battle card from it. If you do, that player discards that card. If you
    don't, incubate 3.

    — the "if you don't, `<effect>`" *else*-branch on an optional
    `reveal_hand_choose_discard` (Thoughtseize's own template) is the only
    new shape: `RevealHandChooseDiscardEffect` gains ``optional`` +
    ``else_specs``, threaded through `request_choose_objects`' new
    ``else_specs`` (the mirror of its long-standing ``then_specs``), which
    fires when the choice ends with nothing picked — including when the
    revealed hand held no creature or battle card to begin with. "battle"
    joins the effect's own ``card_types`` filter. The else body is the
    plain incubate-3 `create_token`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("reveal_hand_choose_discard", {
                "target_kind": "opponent",
                "card_types": ["creature", "battle"],
                "optional": True,
                "else_specs": [
                    {"type": "create_token", "params": {
                        "token_name": "Incubator",
                        "extra_counters": {"kind": "+1/+1", "count": 3},
                    }},
                ],
            })],
            raw_text="Ein Zielgegner zeigt seine Hand vor. Du kannst eine Kreaturen- "
                     "oder Kampfkarte daraus wählen. Falls du das tust, wirft jener "
                     "Spieler jene Karte ab. Falls du das nicht tust, inkubiere 3.",
        ),
    ]


register("Traumatic Revelation", _traumatic_revelation)


def _phyrexian_incubator() -> list[AbilitySpec]:
    """{3}, {T}, Sacrifice Phyrexian Incubator: Search your library for any
    number of Phyrexian cards or cards with phyrexian back faces, exile
    them, then incubate 2 that many times. Then shuffle.

    — "incubate 2 **that many times**", where "that many" is the count of
    cards the search exiled, across the RULE 608.2 pending-choice
    suspension the search opens. Solved without a `GameContext`
    accumulator: `SearchLibraryEffect(track_exiled_with=True)` appends each
    exiled card to the source's own `GameObject.exiled_with_ids` (the same
    list `ExileEffect.track_exiled_with` writes), which lives on the
    permanent and so survives the suspend/resume; the following
    `create_token` reads it back with ``count_selector="exiled_with_count"``
    (Abdel Adrian's own "for each permanent exiled this way" selector).
    "Then shuffle" is `_finish_search`'s default (library zone, no
    exile_rest).

    **Documented simplification**: "or cards with phyrexian back faces" is
    dropped — `card_query`'s type-line substring match claims "Phyrexian
    cards" (the Phyrexian subtype) but not a DFC whose *back* face is
    Phyrexian while the front isn't; no such card is in a normal library
    search target for this artifact's real decks.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("search", {
                    "criteria": {"type": "Phyrexian"},
                    "count": 99,  # "any number of" — the shared search sentinel
                    "optional": True,
                    "destination": "exile",
                    "track_exiled_with": True,
                }),
                EffectSpec("create_token", {
                    "token_name": "Incubator",
                    "count_selector": "exiled_with_count",
                    "extra_counters": {"kind": "+1/+1", "count": 2},
                }),
            ],
            cost={"text": "{3}, {T}, Sacrifice ~"},
            raw_text="{3}, {T}, Opfere Phyrexianischen Inkubator: Durchsuche deine "
                     "Bibliothek nach beliebig vielen phyrexianischen Karten, "
                     "exiliere sie und inkubiere dann so oft 2. Mische danach.",
        ),
    ]


register("Phyrexian Incubator", _phyrexian_incubator)


def _progenitor_exarch() -> list[AbilitySpec]:
    """When this creature enters, incubate 3 X times.
    {T}: Transform target Incubator token you control.

    — "incubate 3 **X times**": the repeat count is the creature's own
    announced {X} ({X}{X} in its cost), `GameObject.x_paid` (RULE 107.3c,
    stamped at cast time and still present when the ETB trigger resolves —
    the same field enters-with-X-counters reads). New
    `continuous.count_selector` key ``"source_x_paid"``, consumed by
    `create_token`'s existing ``count_selector`` path.

    The "{T}: Transform target Incubator token you control" ability reuses
    the `Incubator` token's own transform shape exactly (`grant_until` /
    ``type_change`` / ``rest_of_game`` — a genuinely permanent RULE 712.8
    animation into a 0/0 Phyrexian artifact creature, its +1/+1 counters
    doing the rest), just with a RULE 115 target instead of self: the new
    ``incubator_token_you_control`` target kind (a token named "Incubator"
    this ability's controller controls).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Incubator",
                "count_selector": "source_x_paid",
                "extra_counters": {"kind": "+1/+1", "count": 3},
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, inkubiere X-mal 3.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "rest_of_game",
                "target_kind": "incubator_token_you_control",
                "static": {
                    "type": "type_change",
                    "params": {
                        "add_types": ["creature"], "add_subtypes": ["Phyrexian"],
                        "power": 0, "toughness": 0,
                    },
                },
            })],
            cost={"text": "{T}"},
            raw_text="{T}: Transformiere einen Ziel-Inkubator-Spielstein unter deiner "
                     "Kontrolle.",
        ),
    ]


register("Progenitor Exarch", _progenitor_exarch)


def _hedge_whisperer() -> list[AbilitySpec]:
    """You may choose not to untap this creature during your untap step.
    {3}{G}, {T}, Collect evidence 4: Target land you control becomes a 5/5
    green Plant Boar creature with haste for as long as this creature
    remains tapped. It's still a land. Activate only as a sorcery.

    — Collect Evidence activated-body residue (sub-cluster b). The animate
    body is a targeted `grant_until` on `land_you_control`: a layer-4
    `type_change` (Plant Boar 5/5, `add_types` keeps the land type — "it's
    still a land") plus a layer-6 `grant_keyword` haste, both on the one
    picked land via the new `extra_statics` list. The "for as long as ~
    remains tapped" bound is `condition={"kind": "source_tapped"}` (RULE
    611.2b — the effect *ends*, doesn't merely pause, when Hedge Whisperer
    untaps). ``sorcery_speed_only`` carries "Activate only as a sorcery".
    The keep-tapped static is the general `no_untap_optional`.
    """
    return [
        AbilitySpec("static", [EffectSpec("no_untap_optional", {})],
                    raw_text="Du kannst dich entscheiden, diese Kreatur während deines "
                             "Enttappsegments nicht zu enttappen."),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn",  # overridden to for_as_long_as by `condition`
                "target_kind": "land_you_control",
                "condition": {"kind": "source_tapped"},
                # Documented simplification: "green" isn't modeled —
                # `type_change`'s layer-4 params have no colour field (same
                # call as Restless Cottage). The animated land keeps
                # whatever colour identity it already had.
                "static": {
                    "type": "type_change",
                    "params": {
                        "add_types": ["creature"],
                        "add_subtypes": ["Plant", "Boar"],
                        "power": 5, "toughness": 5,
                    },
                },
                "extra_statics": [
                    {"type": "grant_keyword", "params": {"keywords": ["haste"]}},
                ],
            })],
            cost={"text": "{3}{G}, {T}, Collect evidence 4", "sorcery_speed_only": True},
            raw_text="{3}{G}, {T}, Sammle Beweise 4: Ein Zielland, das du kontrollierst, "
                     "wird zu einer 5/5 grünen Pflanzen-Eber-Kreatur mit Eile, solange "
                     "diese Kreatur getappt bleibt. Es ist weiterhin ein Land. Aktiviere "
                     "nur wie eine Hexerei.",
        ),
    ]


register("Hedge Whisperer", _hedge_whisperer)


def _airtight_alibi() -> list[AbilitySpec]:
    """Flash
    Enchant creature
    When this Aura enters, untap enchanted creature. It gains hexproof
    until end of turn. If it's suspected, it's no longer suspected.
    Enchanted creature gets +2/+2 and can't become suspected.

    — PAR-30 Suspect one-off shapes. Flash / Enchant creature parse off the
    printed text directly. The ETB's three clauses are all shared
    primitives keyed to the Aura's host: `TapEffect` untap
    (``target_kind="attached_permanent"``), `PumpEffect` hexproof-until-EOT
    (the parser's own `pump` shape), and `RemoveSuspectedEffect`'s
    ``attached`` form — RULE 701.60a's reverse already no-ops on a
    non-suspected creature, so "if it's suspected, ..." needs no explicit
    gate. The static is a +2/+2 anthem plus a ``grant_keyword`` slug
    ``"cant_become_suspected"`` the layer engine stamps and
    `RulesEngine.suspect` honours — the only card printing that prohibition,
    so a bespoke keyword rather than a new static kind.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("tap", {"target_kind": "attached_permanent", "untap": True}),
                EffectSpec("pump", {"keywords": ["hexproof"], "target_kind": "attached_permanent"}),
                EffectSpec("remove_suspected", {"attached": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Aura ins Spiel kommt, enttappe die verzauberte Kreatur. "
                     "Sie erhält bis zum Ende des Zuges Fluchsicherheit. Falls sie "
                     "verdächtigt ist, ist sie nicht mehr verdächtigt.",
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent", "keywords": ["cant_become_suspected"],
                }),
            ],
            raw_text="Verzauberte Kreatur erhält +2/+2 und kann nicht verdächtigt werden.",
        ),
    ]


register("Airtight Alibi", _airtight_alibi)


# --- PAR-30 · RULE 701.10 exchange-control residue -------------------------
#
# The remaining ten cards the shared cross-target predicates (PARSER_VERSION
# 211) didn't reach — each its own bespoke primitive, hand-authored per
# BACKLOG.md rather than widened parser grammar (none of these shapes
# repeats across more than this one card).


def _confusion_in_the_ranks() -> list[AbilitySpec]:
    """Whenever an artifact, creature, or enchantment enters, its
    controller chooses target permanent another player controls that
    shares a card type with it. Exchange control of those permanents.

    — The chooser is the *entering permanent's* controller, not this
    Enchantment's own controller (`TriggeredAbility.controller_from_
    trigger_event`, PAR-30's own new primitive) — a RULE 603.1 group
    trigger with no controller restriction of its own (any player's
    permanent). `ExchangeControlEffect(first_target_kind="trigger_subject")`
    reads the entering permanent straight off the firing event; `shares_
    type="card"` is the ordinary cross-target predicate every other "shares
    a card type" exchange card already uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control", {
                "first_target_kind": "trigger_subject",
                "target_kind": "permanent_you_dont_control",
                "shares_type": "card",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": ["artifact", "creature", "enchantment"]},
                "chooser": "trigger_subject_controller",
            },
            raw_text="Wann immer ein Artefakt, eine Kreatur oder ein Verzauberung ins Spiel "
                     "kommt, wählt ihr Beherrscher ein Zielpermanent, das ein anderer Spieler "
                     "kontrolliert und das mit ihm einen Kartentyp teilt. Tauscht die Kontrolle "
                     "über diese Permanents.",
        ),
    ]


register("Confusion in the Ranks", _confusion_in_the_ranks)


def _conjured_currency() -> list[AbilitySpec]:
    """At the beginning of your upkeep, you may exchange control of this
    enchantment and target permanent you neither own nor control.

    — The new `permanent_you_neither_own_nor_control` target kind
    (`targeting.legal_targets`); the self+target `ExchangeControlEffect`
    mode (`target_kind` only, no `first_target_kind`) Avarice Totem-shaped
    cards already use.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control", {
                "target_kind": "permanent_you_neither_own_nor_control",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            optional=True,
            raw_text="Zu Beginn deines Versorgungssegments kannst du die Kontrolle über "
                     "diese Verzauberung und ein Zielpermanent, das du weder besitzt noch "
                     "kontrollierst, tauschen.",
        ),
    ]


register("Conjured Currency", _conjured_currency)


def _djinn_of_infinite_deceits() -> list[AbilitySpec]:
    """Flying
    {T}: Exchange control of two target nonlegendary creatures. You can't
    activate this ability during combat.

    — The multi-target `count=2` mode's own shared filter (`second_
    creature_filter={"nonlegendary": True}`, new `combat.matches_object_
    filter` key) plus the new `ActivationCost.not_during_combat` timing
    flag (RULE 602.5d's converse of `sorcery_speed_only`).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_control", {
                "target_kind": "creature", "count": 2,
                "second_creature_filter": {"nonlegendary": True},
            })],
            cost={"text": "{T}", "not_during_combat": True},
            raw_text="Fliegend\n{T}: Tausche die Kontrolle über zwei nichtlegendäre "
                     "Zielkreaturen. Du kannst diese Fähigkeit nicht während des Kampfes "
                     "aktivieren.",
        ),
    ]


register("Djinn of Infinite Deceits", _djinn_of_infinite_deceits)


def _gauntlets_of_chaos() -> list[AbilitySpec]:
    """{5}, Sacrifice this artifact: Exchange control of target artifact,
    creature, or land you control and target permanent an opponent
    controls that shares one of those types with it. If those permanents
    are exchanged this way, destroy all Auras attached to them.

    — The two-explicit-targets mode plus both new `ExchangeControlEffect`
    riders: `shares_type="card"` (the cross-target predicate) and
    `destroy_auras_if_exchanged` (RULE 701.10c's own after-effect, gated on
    the exchange actually happening).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_control", {
                "first_target_kind": "permanent_you_control",
                "target_kind": "permanent_you_dont_control",
                "shares_type": "card",
                "destroy_auras_if_exchanged": True,
            })],
            cost={"text": "{5}, Sacrifice ~"},
            raw_text="{5}, Opfere dieses Artefakt: Tausche die Kontrolle über ein "
                     "Zielartefakt, eine Zielkreatur oder ein Zielland, das du "
                     "kontrollierst, und ein Zielpermanent, das ein Gegner kontrolliert "
                     "und das mit ihm einen dieser Typen teilt. Falls diese Permanents auf "
                     "diese Weise getauscht werden, zerstöre alle Verzauberungen vom Typ "
                     "Aura, die an ihnen befestigt sind.",
        ),
    ]


register("Gauntlets of Chaos", _gauntlets_of_chaos)


def _modify_memory() -> list[AbilitySpec]:
    """Exchange control of two target creatures controlled by different
    players. If you control neither creature, draw three cards.

    — The multi-target `count=2` + `distinct_controllers` mode (already
    shipped) plus the new `draw_if_neither_controlled` rider.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exchange_control", {
                "target_kind": "creature", "count": 2, "distinct_controllers": True,
                "draw_if_neither_controlled": 3,
            })],
            raw_text="Tausche die Kontrolle über zwei Zielkreaturen, die von "
                     "unterschiedlichen Spielern kontrolliert werden. Falls du keine der "
                     "beiden Kreaturen kontrollierst, ziehe drei Karten.",
        ),
    ]


register("Modify Memory", _modify_memory)


def _psychic_transfer() -> list[AbilitySpec]:
    """If the difference between your life total and target player's life
    total is 5 or less, exchange life totals with that player.

    — The new `ExchangeLifeTotalsEffect.life_difference_at_most` pre-effect
    numeric gate.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exchange_life_totals", {
                "target_kind": "player", "life_difference_at_most": 5,
            })],
            raw_text="Falls der Unterschied zwischen deinem Lebenspunktestand und dem "
                     "Lebenspunktestand des Zielspielers 5 oder weniger beträgt, tauscht "
                     "die Lebenspunktestände mit diesem Spieler.",
        ),
    ]


register("Psychic Transfer", _psychic_transfer)


def _mirror_mirror() -> list[AbilitySpec]:
    """This artifact enters tapped.
    {7}, {T}, Sacrifice this artifact: Choose target player. At the
    beginning of the next end step, exchange life totals with that player,
    exchange control of all permanents you and that player control, and
    exchange cards in your hands, cards in your libraries, and cards in
    your graveyards.

    — "This artifact enters tapped" needs no entry here at all:
    `ability_catalogue.core.enters_tapped` derives RULE 614.1 tap-lands (and
    this same shape on any other permanent) straight from the card's own
    printed oracle text (`parser.oracle.catalogue.lands.land_tap_condition`),
    independent of this hand-authored registry.
    `CreateDelayedTriggerEffect(step="end", scope="any", capture=
    "target_player")` arms the delayed firing (RULE 603.7), baking in the
    player chosen when the ability first resolved; `choose_targets` is what
    actually offers that RULE 115 pick — a `target_groups=None` ability
    passes its whole ``targets`` list to every one of its own effects, so
    the delayed-trigger effect sees the same pick with no `target_spec` of
    its own. The new `TripleExchangeEffect` (`capture="target_player"`'s
    own new mode) is the delayed effect itself — see its docstring for why
    the three swaps are one bespoke effect rather than three.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("choose_targets", {"kinds": ["player"]}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any", "capture": "target_player",
                    "effects": [{"type": "triple_exchange", "params": {}}],
                    "description": "Mirror Mirror: Lebenspunkte, Permanents und Zonen tauschen",
                }),
            ],
            cost={"text": "{7}, {T}, Sacrifice ~"},
            raw_text="{7}, {T}, Opfere dieses Artefakt: Wähle einen Zielspieler. Zu Beginn "
                     "des nächsten Endsegments tauscht ihr die Lebenspunktestände, die "
                     "Kontrolle über alle Permanents, die du und dieser Spieler "
                     "kontrolliert, und die Karten in euren Händen, Bibliotheken und "
                     "Friedhöfen.",
        ),
    ]


register("Mirror Mirror", _mirror_mirror)


def _cultural_exchange() -> list[AbilitySpec]:
    """Choose any number of creatures target player controls. Choose the
    same number of creatures another target player controls. Those players
    exchange control of those creatures. (This effect lasts indefinitely.)

    — See `CulturalExchangeEffect`'s own docstring for the two chained
    interactive rounds and its documented "same number" simplification.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("cultural_exchange", {})],
            raw_text="Wähle eine beliebige Anzahl Kreaturen, die ein Zielspieler "
                     "kontrolliert. Wähle die gleiche Anzahl Kreaturen, die ein anderer "
                     "Zielspieler kontrolliert. Diese Spieler tauschen die Kontrolle über "
                     "diese Kreaturen. (Dieser Effekt hält unbegrenzt an.)",
        ),
    ]


register("Cultural Exchange", _cultural_exchange)


def _juxtapose() -> list[AbilitySpec]:
    """You and target player exchange control of the creature you each
    control with the greatest mana value. Then exchange control of
    artifacts the same way. If two or more permanents a player controls
    are tied for greatest, their controller chooses one of them.

    — See `JuxtaposeEffect`'s own docstring for the two selection+exchange
    rounds and its documented tie-break simplification.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("juxtapose", {})],
            raw_text="Du und der Zielspieler tauscht die Kontrolle über die Kreatur mit "
                     "dem höchsten Manawert, die ihr jeweils kontrolliert. Tauscht dann auf "
                     "die gleiche Weise die Kontrolle über Artefakte. Falls zwei oder mehr "
                     "Permanents, die ein Spieler kontrolliert, für den höchsten Wert "
                     "gleichauf sind, wählt ihr Beherrscher eines davon.",
        ),
    ]


register("Juxtapose", _juxtapose)


def _perplexing_chimera() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, you may exchange control of
    this creature and that spell. If you do, you may choose new targets
    for the spell. (If the spell becomes a permanent, you control that
    permanent.)

    — RULE 603.3d's reflexive "that spell" (the firing SPELL_CAST event's
    own subject, never a RULE 115 target) combined with RULE 603.5's "you
    may" (`TriggeredAbility.optional` — `_place_triggers`'s reflexive
    branch now pauses on a do/decline choice instead of placing blind when
    both are set, PAR-30's own new primitive). `ExchangeControlSpellEffect
    (reflexive_spell=True)` is the still-on-the-stack sibling of the
    ordinary battlefield `ExchangeControlEffect`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control_spell", {"reflexive_spell": True})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "reflexive": True,
            },
            optional=True,
            raw_text="Wann immer ein Gegner einen Zauberspruch wirkt, kannst du die "
                     "Kontrolle über diese Kreatur und diesen Zauberspruch tauschen. Wenn "
                     "du dies tust, kannst du für den Zauberspruch neue Ziele bestimmen.",
        ),
    ]


register("Perplexing Chimera", _perplexing_chimera)


def _sudden_substitution() -> list[AbilitySpec]:
    """Split second (As long as this spell is on the stack, players can't
    cast spells or activate abilities that aren't mana abilities.)
    Exchange control of target noncreature spell and target creature. Then
    the spell's controller may choose new targets for it.

    — `ExchangeControlSpellEffect`'s two-independent-targets mode
    (``permanent_target_kind="creature"``, ``spell_filter={"noncreature":
    True}``); Split Second is a plain flag keyword, already parsed off the
    printed text.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exchange_control_spell", {
                "permanent_target_kind": "creature",
                "spell_filter": {"noncreature": True},
            })],
            raw_text="Split Second (Solange sich dieser Zauberspruch auf dem Stapel "
                     "befindet, können Spieler keine Zaubersprüche wirken oder Fähigkeiten "
                     "aktivieren, die keine Manafähigkeiten sind.)\n"
                     "Tausche die Kontrolle über einen nichtkreaturischen Zielzauberspruch "
                     "und eine Zielkreatur. Danach kann der Beherrscher des "
                     "Zauberspruchs neue Ziele für ihn bestimmen.",
        ),
    ]


register("Sudden Substitution", _sudden_substitution)


def _arteeoh_dread_scavenger() -> list[AbilitySpec]:
    """Flying, deathtouch
    Whenever Arteeoh deals combat damage to a player, you may exchange
    control of two other target artifacts. When you do, create a token
    that's a copy of target artifact you don't control, except it's a 1/1
    green Squirrel creature token in addition to its other colors and
    types.

    — See `ExchangeControlThenCopyTokenEffect`'s own docstring for the
    exchange + RULE 603.11 reflexive copy-token connector and its
    documented colour-addition simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control_then_copy_token", {})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
            optional=True,
            raw_text="Fliegend, Todesberührung\nImmer wenn Arteeoh einem Spieler "
                     "Kampfschaden zufügt, kannst du die Kontrolle über zwei andere "
                     "Zielartefakte tauschen. Wenn du dies tust, erschaffe einen Marker, "
                     "der eine Kopie eines Zielartefakts ist, das du nicht kontrollierst, "
                     "außer dass er zusätzlich zu seinen anderen Farben und Typen ein "
                     "grüner 1/1 Eichhörnchen-Kreaturenmarker ist.",
        ),
    ]


register("Arteeoh, Dread Scavenger", _arteeoh_dread_scavenger)


# ---------------------------------------------------------------------------
# PAR-30 — Waterbend (RULE 701.67) residue: the remaining per-card bodies.
# The shared "waterbend {X}" announcement (v215) folds the {X} into the
# spell's total and stamps `GameObject.x_paid`; each body below is bespoke.
# ---------------------------------------------------------------------------


def _waterbending_lesson() -> list[AbilitySpec]:
    """Draw three cards. Then discard a card unless you waterbend {2}.

    — RULE 118.3 resolve-time pay-or-discard: `pay_cost_then` with an
    ``else_effects`` discard, the cost being the waterbend {2} (modeled as a
    plain {2}, the same documented-simplification drop of the "tap your
    artifacts and creatures to help" helper as every other waterbend cost).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": 3}),
                EffectSpec("pay_cost_then", {
                    "cost": "{2}",
                    "effects": [],
                    "else_effects": [{"type": "discard", "params": {"count": 1}}],
                    "prompt": "Wasserbändige {2}, sonst wirf eine Karte ab.",
                }),
            ],
            raw_text="Ziehe drei Karten. Wirf dann eine Karte ab, es sei denn, du "
                     "wasserbändigst {2}.",
        ),
    ]


register("Waterbending Lesson", _waterbending_lesson)


def _water_tribe_rallier() -> list[AbilitySpec]:
    """Waterbend {5}: Look at the top four cards of your library. You may
    reveal a creature card with power 3 or less from among them and put it
    into your hand. Put the rest on the bottom of your library in a random
    order.

    — the `look_top_select` reveal-filter variant (PAR-30): ``select_
    optional`` ("you may reveal") + ``select_filter`` ({card_type: creature,
    max_power: 3}) + ``rest_order="random"``. Cost is the waterbend {5} as a
    plain {5} activated cost.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("look_top_select", {
                "count": 4,
                "select_count": 1,
                "select_optional": True,
                "select_filter": {"card_type": "creature", "max_power": 3},
                "rest_destination": "library_bottom",
                "rest_order": "random",
            })],
            cost={"mana": "{5}"},
            raw_text="Wasserbändige {5}: Sieh dir die obersten vier Karten deiner "
                     "Bibliothek an. Du darfst eine Kreaturenkarte mit Stärke 3 oder "
                     "weniger von ihnen offenbaren und auf deine Hand nehmen. Lege "
                     "den Rest in zufälliger Reihenfolge unter deine Bibliothek.",
        ),
    ]


register("Water Tribe Rallier", _water_tribe_rallier)


def _ruinous_waterbending() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may waterbend {4}.
    All creatures get -2/-2 until end of turn. If this spell's additional
    cost was paid, whenever a creature dies this turn, you gain 1 life.

    — the -2/-2 board sweep parses on its own (`pump` selector
    ``all_creatures``); the paid-branch grant is the new *event-based,
    this-turn* floating triggered ability — `install_temporary_player_
    trigger` with ``duration="this_turn"`` (armed active immediately,
    dropped at the next `TURN_BEGIN`), ``event_player_scope="any"``
    ("whenever **a** creature dies", not "a creature you control") and
    ``recipient="controller"`` ("**you** gain 1 life").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("pump", {"power": -2, "toughness": -2, "selector": "all_creatures"}),
                EffectSpec("install_temporary_player_trigger", {
                    "event_type": "DIES",
                    "duration": "this_turn",
                    "event_player_scope": "any",
                    "recipient": "controller",
                    "effects": [{"type": "gain_life", "params": {"amount": 1}}],
                    "description": "Immer wenn in diesem Zug eine Kreatur stirbt, gewinnst du 1 Leben.",
                }, condition={"additional_cost_paid": True}),
            ],
            additional_cost={"waterbend": 4},
            additional_cost_optional=True,
            raw_text="Alle Kreaturen erhalten -2/-2 bis zum Ende des Zuges. Falls die "
                     "zusätzlichen Kosten dieses Zauberspruchs bezahlt wurden, gewinnst "
                     "du 1 Leben, immer wenn in diesem Zug eine Kreatur stirbt.",
        ),
    ]


register("Ruinous Waterbending", _ruinous_waterbending)


def _spirit_water_revival() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may waterbend {6}.
    Draw two cards. If this spell's additional cost was paid, instead
    shuffle your graveyard into your library, draw seven cards, and you
    have no maximum hand size for the rest of the game.
    Exile Spirit Water Revival.

    — the additional-cost-paid *override* ("instead"): the plain "draw two"
    is gated `{"additional_cost_paid": False}`, the bigger line
    `{"additional_cost_paid": True}` (RULE 118.3's "instead" = the two
    branches are mutually exclusive complements, the `clash_won` idiom).
    "no maximum hand size for the rest of the game" is the new
    `no_max_hand_size_rest_of_game` effect (`GameState.no_max_hand_size_
    player_ids`). "Exile ~" is the self-exile-on-resolution tail.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": 2}, condition={"additional_cost_paid": False}),
                EffectSpec("shuffle_graveyard_into_library", {},
                           condition={"additional_cost_paid": True}),
                EffectSpec("draw", {"count": 7}, condition={"additional_cost_paid": True}),
                EffectSpec("no_max_hand_size_rest_of_game", {},
                           condition={"additional_cost_paid": True}),
                EffectSpec("exile", {"target_kind": None}),
            ],
            additional_cost={"waterbend": 6},
            additional_cost_optional=True,
            raw_text="Ziehe zwei Karten. Falls die zusätzlichen Kosten dieses "
                     "Zauberspruchs bezahlt wurden, mische stattdessen deinen Friedhof "
                     "in deine Bibliothek, ziehe sieben Karten und du hast für den Rest "
                     "des Spiels keine maximale Handkartenzahl. Schicke Spirit Water "
                     "Revival ins Exil.",
        ),
    ]


register("Spirit Water Revival", _spirit_water_revival)


def _waterbenders_restoration() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, waterbend {X}.
    Exile X target creatures you control. Return those cards to the
    battlefield under their owner's control at the beginning of the next
    end step.

    — a mass delayed-return flicker: `exile` X targets with ``track_exiled_
    with`` + a RULE 603.7 `create_delayed_trigger` at the next end step
    running `return_all_exiled_with` (each card back under its own owner's
    control — the effect's default). The mandatory waterbend {X} announces
    X (v215) and `_substitute_x` resolves the ``"x"`` target count.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {
                    "target_kind": "creature_you_control",
                    "count_selector": "source_x_paid",
                    "track_exiled_with": True,
                }),
                # "at the beginning of **the** next end step" (not "your") —
                # scope "any", the very next end step whoever's turn it is.
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any",
                    "effects": [{"type": "return_all_exiled_with", "params": {}}],
                    "description": "Bringe diese Karten am Anfang des nächsten "
                                   "Endsegments ins Spiel zurück.",
                }),
            ],
            additional_cost={"waterbend": "x"},
            raw_text="Schicke X Zielkreaturen, die du kontrollierst, ins Exil. Bringe "
                     "diese Karten am Anfang des nächsten Endsegments unter der "
                     "Kontrolle ihrer Besitzer ins Spiel zurück.",
        ),
    ]


register("Waterbender's Restoration", _waterbenders_restoration)


def _foggy_swamp_visions() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, waterbend {X}.
    Exile X target creature cards from graveyards. For each creature card
    exiled this way, create a token that's a copy of it. At the beginning
    of your next end step, sacrifice those tokens.

    — `exile` X graveyard creature cards → `copy_permanent` with the new
    ``referent="previous_each"`` (one token copy of *each* card an earlier
    clause of this resolution exiled, `GameContext.previous_targets`) → a
    RULE 603.7 `create_delayed_trigger` at the next end step sacrificing
    the captured tokens (``capture="created_objects"``).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {
                    "target_kind": "any_graveyard_creature",
                    "count_selector": "source_x_paid",
                }),
                EffectSpec("copy_permanent", {
                    "referent": "previous_each", "target_kind": None,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "controller", "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "description": "Opfere diese Marker am Anfang deines nächsten "
                                   "Endsegments.",
                }),
            ],
            additional_cost={"waterbend": "x"},
            raw_text="Schicke X Zielkreaturenkarten aus Friedhöfen ins Exil. Erschaffe "
                     "für jede auf diese Weise ins Exil geschickte Kreaturenkarte einen "
                     "Marker, der eine Kopie von ihr ist. Opfere diese Marker am Anfang "
                     "deines nächsten Endsegments.",
        ),
    ]


register("Foggy Swamp Visions", _foggy_swamp_visions)


def _crashing_wave() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, waterbend {X}.
    Tap up to X target creatures, then distribute three stun counters among
    any number of tapped creatures your opponents control.

    — `tap` up to X targets (`TargetSpec.count_selector="source_x_paid"`,
    resolved at announce time off `x_paid`) → `add_counters` ``divided`` +
    ``previous_subject`` (a 3-stun-counter pool auto-split across the
    creatures this spell just tapped). **Documented simplification:** the
    stun distribution isn't a RULE 115 target (the printed text has no
    "target" for it — it's "any number of tapped creatures your opponents
    control"), so it's modeled as "the creatures this spell tapped", split
    evenly, rather than a fresh interactive "distribute among any number
    of" choice restricted to opponent-controlled creatures.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("tap", {
                    "target_kind": "creature",
                    "count_selector": "source_x_paid", "optional": True,
                }),
                EffectSpec("add_counters", {
                    "kind": "stun", "amount": 3, "divided": True,
                    "previous_subject": True,
                }),
            ],
            additional_cost={"waterbend": "x"},
            raw_text="Tappe bis zu X Zielkreaturen, dann verteile drei "
                     "Betäubungsmarken unter einer beliebigen Anzahl getappter "
                     "Kreaturen, die deine Gegner kontrollieren.",
        ),
    ]


register("Crashing Wave", _crashing_wave)


def _invasion_submersible() -> list[AbilitySpec]:
    """When this Vehicle enters, return up to one other target nonland
    permanent to its owner's hand.
    Exhaust — Waterbend {3}: This Vehicle becomes an artifact creature. Put
    three +1/+1 counters on it. (Activate each exhaust ability only once.)

    — the ETB parses on its own (v215 "up to one other target nonland
    permanent"), reproduced here since a catalogue entry replaces the
    parser fallback. The Exhaust body is hand-authored: "becomes an
    artifact creature" is a `grant_until` rest-of-game `type_change`
    (0/0 base — this Vehicle's printed crew P/T — plus the three counters
    = a 3/3), and RULE 702.177a's once-per-game restriction is the
    `activate_only_once_marker` the binder folds into ``once_per_game``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {
                "target_kind": "nonland_permanent", "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn dieses Fahrzeug ins Spiel kommt, bringe bis zu eine andere "
                     "Ziel-Nichtland-bleibende-Karte auf die Hand ihres Besitzers zurück.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "duration": "rest_of_game", "target_kind": None,
                    "static": {"type": "type_change", "params": {
                        "add_types": ["artifact", "creature"], "power": 0, "toughness": 0,
                    }},
                }),
                EffectSpec("add_counters", {"kind": "+1/+1", "amount": 3, "target_kind": None}),
                EffectSpec("activate_only_once_marker", {}),
            ],
            cost={"mana": "{3}"},
            raw_text="Auslaugen — Wasserbändige {3}: Dieses Fahrzeug wird eine "
                     "Artefaktkreatur. Lege drei +1/+1-Marken darauf.",
        ),
    ]


register("Invasion Submersible", _invasion_submersible)


def _the_master_gallifreys_end() -> list[AbilitySpec]:
    """Make Them Pay — Whenever a nontoken artifact creature you control
    dies, you may exile it. If you do, choose an opponent with the most life
    among your opponents. That player faces a villainous choice — They lose
    4 life, or you create a token that's a copy of that card.

    — MEC-52. Hand-authored: the DIES group trigger with a nontoken +
    artifact filter and the "you may exile **it**" reflexive on the dying
    creature (RULE 603.6e last-known info, `ExileEffect` ``target_kind=
    "trigger_subject"``) are past what the parser's villainous grammar
    reaches. Two general engine primitives it drove:
    `FaceVillainousChoiceEffect` ``subject="opponent_with_most_life"`` (RULE
    701.55 pre-selection; ties → first in APNAP order, a documented
    simplification of the printed "your choice") and ``capture_previous`` —
    the just-exiled card (`context.previous_targets`, now also seeded by
    `ExileEffect`'s trigger-subject branch) is baked into the choice so
    option B's `copy_permanent` ``referent="previous"`` still resolves once
    the choice is *answered*, well after this resolution's context is gone.
    ``optional`` on the whole ability is the "you may exile it. If you do,
    …" gate: decline and nothing happens; accept and the exile always
    succeeds (the creature is in the graveyard), so the "if you do" is
    exact rather than simplified.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile", {"target_kind": "trigger_subject"}),
                EffectSpec("face_villainous_choice", {
                    "subject": "opponent_with_most_life",
                    "capture_previous": True,
                    "option_a": [{"type": "lose_life",
                                  "params": {"amount": 4, "target_kind": "player"}}],
                    "option_b": [{"type": "copy_permanent",
                                  "params": {"target_kind": None, "referent": "previous"}}],
                }),
            ],
            trigger={
                "event": EventType.DIES,
                "condition": {
                    "subject": "group", "controller": "you",
                    "type": "artifact", "nontoken": True,
                },
            },
            optional=True,
            raw_text="Lass sie bezahlen — Immer wenn eine Nicht-Token-"
                     "Artefaktkreatur, die du kontrollierst, stirbt, darfst du "
                     "sie ins Exil schicken. Falls du dies tust, wähle einen "
                     "Gegner mit den meisten Lebenspunkten unter deinen "
                     "Gegnern. Jener Spieler trifft eine schurkische Wahl — Er "
                     "verliert 4 Lebenspunkte, oder du erschaffst einen Marker, "
                     "der eine Kopie jener Karte ist.",
        ),
    ]


register("The Master, Gallifrey's End", _the_master_gallifreys_end)
