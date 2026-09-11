"""Card -> AbilitySpec catalogue entries, part 013 of 016.

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

def _allosaurus_shepherd() -> list[AbilitySpec]:
    """Allosaurus Shepherd (Creature — Elf Shaman, {G})

    "This spell can't be countered.
    Green spells you control can't be countered.
    {4}{G}{G}: Until end of turn, each Elf creature you control has base
    power and toughness 5/5 and becomes a Dinosaur in addition to its
    other creature types."

    The self-uncounterable static is already parser-claimable. The second
    static reuses `GrantCantBeCounteredEffect`'s new ``color`` param
    (MEC-40). The activated ability reuses the standing ``creatures_you_
    control_of_type_elf`` group selector (`continuous.group_selector_
    objects`, an already-general subtype-scoped anthem affects string) via
    `GrantUntilEffect` wrapping ``type_change`` — the same "until end of
    turn" resolve-time grant Crew's own "becomes an artifact creature"
    reuses (MEC-29).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_cant_be_countered", {"scope": "color_spells_you_control", "color": "G"})],
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "grant_until",
                    {
                        "static": {
                            "type": "type_change",
                            "params": {
                                "power": 5, "toughness": 5, "add_subtypes": ["Dinosaur"],
                                "affects": "creatures_you_control_of_type_elf",
                            },
                        },
                        "duration": "end_of_turn",
                        "target_kind": None,
                    },
                )
            ],
            cost={"text": "{4}{G}{G}"},
        ),
    ]


register("Allosaurus Shepherd", _allosaurus_shepherd)


def _domri_anarch_of_bolas() -> list[AbilitySpec]:
    """Domri, Anarch of Bolas (Legendary Planeswalker — Domri, {1}{R}{G})

    "Creatures you control get +1/+0.
    +1: Add {R} or {G}. Creature spells you cast this turn can't be
    countered.
    −2: Target creature you control fights target creature you don't
    control."

    The anthem and the fight ability are already parser-claimable as-is.
    The +1's mana half is the existing ``add_mana``/``colors=["ANY"]``
    single-choice shape narrowed to R/G; its "can't be countered" half
    reuses `arm_spell_watcher` (RULE 118.3, Dual Strike-shaped) with
    ``card_types=["creature"]`` and ``repeat=True`` (Veil of Summer's own
    "for the rest of the turn" idiom) feeding `MarkCantBeCounteredEffect`
    via ``then_specs`` — no new primitive needed at all.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"power": 1, "toughness": 0, "affects": "creatures_you_control"})],
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_mana", {"colors": ["ANY"], "any_color_choices": ["R", "G"]}),
                EffectSpec(
                    "arm_spell_watcher",
                    {"card_types": ["creature"], "repeat": True,
                     "then_specs": [{"type": "mark_cant_be_countered", "params": {}}]},
                ),
            ],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("fight", {"fighter_kind": "creature_you_control", "other_kind": "creature_you_dont_control"})],
            cost={"loyalty": -2},
        ),
    ]


register("Domri, Anarch of Bolas", _domri_anarch_of_bolas)


def _eladamri_korvecdal() -> list[AbilitySpec]:
    """Eladamri, Korvecdal (Legendary Creature — Elf Warrior, {1}{G}{G})

    "You may look at the top card of your library any time.
    You may cast creature spells from the top of your library.
    {G}, {T}, Tap two untapped creatures you control: Reveal a card from
    your hand or the top card of your library. If you reveal a creature
    card this way, put it onto the battlefield. Activate only during your
    turn."

    The "look" permission is already parser-claimable; the "cast creature
    spells from the top" clause is the same standing static widened with
    `TopLibraryPermissionEffect.creature_only` (MEC-40). **Documented
    simplification** on the reveal ability: `SearchLibraryEffect`'s
    ``zones`` param has no "just the top card" source (only whole-zone
    scans — "library"/"graveyard"/"hand"/"exile"), so it's modeled as
    "reveal a card from your hand" only, dropping the "or the top card of
    your library" alternative — Eladamri's own standing "look at the top
    card any time" permission still lets a player plan around what that
    card is even though this ability can't reach it directly.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"look": True})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"cast_spells": True, "creature_only": True})],
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "search",
                    {
                        "criteria": {"type": "creature"}, "zones": ["hand"],
                        "destination": "battlefield", "optional": True, "count": 1,
                    },
                )
            ],
            cost={"text": "{G}, {T}, Tap two untapped creatures you control"},
        ),
    ]


register("Eladamri, Korvecdal", _eladamri_korvecdal)


def _elesh_norn_mother_of_machines() -> list[AbilitySpec]:
    """Elesh Norn, Mother of Machines (Legendary Creature — Phyrexian
    Praetor, {4}{W})

    "Vigilance
    If a permanent entering causes a triggered ability of a permanent you
    control to trigger, that ability triggers an additional time.
    Permanents entering don't cause abilities of permanents your opponents
    control to trigger."

    Vigilance is already parser-claimable. The trigger-doubling clause is
    `TriggerDoublerEffect`'s new ``cause_filter`` scoping (MEC-40, unscoped
    by the doubled permanent's own type, unlike Roaming Throne's
    ``chosen_type`` gate). The suppression clause reuses the standing
    ``trigger_prohibition`` static (Tocatli Honor Guard/Torpor Orb-shaped)
    widened with a new ``scope="opponents"`` (`continuous.trigger_
    suppressed_for`), since the printed clause silences only *opponents'*
    triggers, not the controller's own.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {"cause_filter": [EventType.ENTERS_BATTLEFIELD]})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("trigger_prohibition", {"event": EventType.ENTERS_BATTLEFIELD, "scope": "opponents"})],
        ),
    ]


register("Elesh Norn, Mother of Machines", _elesh_norn_mother_of_machines)


def _flamescroll_celebrant() -> list[AbilitySpec]:
    """Flamescroll Celebrant // Revel in Silence (Creature — Human Shaman,
    {1}{R})

    "Whenever an opponent activates an ability that isn't a mana ability,
    this creature deals 1 damage to that player.
    {1}{R}: This creature gets +2/+0 until end of turn."

    The pump ability is already parser-claimable. The trigger is Harsh
    Mentor/Immolation Shaman's own already-shipped shape (RULE 602.2's
    `EventType.ACTIVATED_ABILITY`, which mana abilities never reach at all
    since they resolve through the separate `tap_for_mana` fast path
    instead of the stack — "isn't a mana ability" needs no extra filter),
    just copied verbatim.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"power": 2, "toughness": 0})],
            cost={"text": "{1}{R}"},
        ),
    ]


register("Flamescroll Celebrant", _flamescroll_celebrant)


def _gandalf_the_white() -> list[AbilitySpec]:
    """Gandalf the White (Legendary Creature — Avatar Wizard, {3}{W}{W})

    "Flash
    You may cast legendary spells and artifact spells as though they had
    flash.
    If a legendary permanent or an artifact entering or leaving the
    battlefield causes a triggered ability of a permanent you control to
    trigger, that ability triggers an additional time."

    Flash is already parser-claimable. The standing flash-permission
    static reuses `flash_permission`'s new ``type_filter`` (MEC-40,
    ``noncreature_only``/``creature_only``'s sibling for a closed
    "legendary"/"artifact" word list). The trigger-doubling clause is
    Elesh Norn's own ``cause_filter`` widened to *two* event types
    ("entering **or** leaving") plus the new ``cause_type_filter``
    (unlike Elesh Norn's own unscoped "**a** permanent", this one is
    narrowed to legendary permanents/artifacts specifically).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("flash_permission", {"type_filter": ["legendary", "artifact"]})],
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec(
                    "trigger_doubler",
                    {
                        "cause_filter": [EventType.ENTERS_BATTLEFIELD, EventType.LEAVES_BATTLEFIELD],
                        "cause_type_filter": ["legendary", "artifact"],
                    },
                )
            ],
        ),
    ]


register("Gandalf the White", _gandalf_the_white)


def _guardian_project() -> list[AbilitySpec]:
    """Guardian Project (Enchantment, {3}{G})

    "Whenever a nontoken creature you control enters, if it doesn't have
    the same name as another creature you control or a creature card in
    your graveyard, draw a card."

    The RULE 603.1 group-subject trigger condition ("a nontoken creature
    you control enters") is already-general segmenter vocabulary. The
    "if it doesn't have the same name as…" gate is the new
    ``entering_object_unique_name`` `EffectSpec.condition` key (MEC-40).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "draw", {"count": 1},
                    condition={"entering_object_unique_name": True},
                )
            ],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "type": "creature"},
            },
        ),
    ]


register("Guardian Project", _guardian_project)


def _guardian_sunmare() -> list[AbilitySpec]:
    """Guardian Sunmare (Creature — Horse Mount, {3}{W}{W})

    "Ward {2}
    Whenever this creature attacks while saddled, search your library for
    a nonland permanent card with mana value 3 or less, put it onto the
    battlefield, then shuffle.
    Saddle 4"

    Ward and Saddle are both already parser-claimable keywords — Saddle's
    own cost/state (`ActivationCost.saddle_power`, `GameObject.saddled_
    until_turn`, `effects.BecomeSaddledEffect`) is new real behaviour
    (MEC-40; previously keyword-recognized only, per RULE 702.171). The
    attack trigger's own "while saddled" gate is the new ``requires_
    saddled`` trigger-condition key, the same "checks the source's own
    live state" idiom `requires_equipped` uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "search",
                    {
                        "criteria": {
                            "type": ["Creature", "Artifact", "Enchantment", "Planeswalker", "Battle"],
                            "without_type": "Land", "max_mana_value": 3,
                        },
                        "destination": "battlefield",
                    },
                )
            ],
            trigger={
                "event": EventType.ATTACKS, "condition": {"subject": "self"}, "requires_saddled": True,
            },
        ),
    ]


register("Guardian Sunmare", _guardian_sunmare)


def _kutzil_malamet_exemplar() -> list[AbilitySpec]:
    """Kutzil, Malamet Exemplar (Legendary Creature — Cat Warrior, {1}{G}{W})

    "Your opponents can't cast spells during your turn.
    Whenever one or more creatures you control each with power greater
    than its base power deals combat damage to a player, draw a card."

    The first static is already parser-claimable (``cast_prohibition``
    with an ``active_if: your_turn`` RULE 613.6 gate). The trigger is the
    new ``contributor_power_gt_base`` aggregate-event qualifier (MEC-40,
    `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`'s own sibling to
    MEC-29's ``contributor_power_at_least``/``contributor_subtype``).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {"scope": "opponents", "active_if": {"kind": "your_turn"}})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "you"},
                "contributor_power_gt_base": True,
            },
        ),
    ]


register("Kutzil, Malamet Exemplar", _kutzil_malamet_exemplar)


def _moon_blessed_cleric() -> list[AbilitySpec]:
    """Moon-Blessed Cleric (Creature — Human Elf Cleric, {2}{W})

    "Divine Intervention — When this creature enters, you may search your
    library for an enchantment card, reveal it, then shuffle and put that
    card on top."

    A plain optional search onto the library's own top — the ability-word
    "Divine Intervention —" prefix carries no separate rules meaning
    (RULE 207.2c reminder-text-style flavour heading).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "enchantment"}, "destination": "library_top"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            optional=True,
        ),
    ]


register("Moon-Blessed Cleric", _moon_blessed_cleric)


def _sigarda_font_of_blessings() -> list[AbilitySpec]:
    """Sigarda, Font of Blessings (Legendary Creature — Angel, {2}{G}{W})

    "Flying
    Other permanents you control have hexproof.
    You may look at the top card of your library any time.
    You may cast Angel spells and Human spells from the top of your
    library."

    Flying and the hexproof anthem are already parser-claimable. The look
    permission is already-general `top_library_permission`. The cast
    permission reuses its own new ``subtypes`` filter (MEC-40, Eladamri's
    sibling ``creature_only`` narrowed to two named creature types
    instead) — union semantics, either subtype qualifies.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"look": True})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"cast_spells": True, "subtypes": ["Angel", "Human"]})],
        ),
    ]


register("Sigarda, Font of Blessings", _sigarda_font_of_blessings)


def _squee_the_immortal() -> list[AbilitySpec]:
    """Squee, the Immortal (Legendary Creature — Goblin, {1}{R}{R})

    "You may cast this card from your graveyard or from exile."

    A bare self-referential zone permission — `SelfGraveyardOrExileCast
    PermissionEffect` (MEC-40), read directly off this object's own
    ``static_effects`` regardless of which of the two zones it's
    currently sitting in.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("self_graveyard_or_exile_cast_permission", {})],
        ),
    ]


register("Squee, the Immortal", _squee_the_immortal)


def _sylvan_library() -> list[AbilitySpec]:
    """Sylvan Library (Enchantment, {1}{G})

    "At the beginning of your draw step, you may draw two additional
    cards. If you do, choose two cards in your hand drawn this turn. For
    each of those cards, pay 4 life or put the card on top of your
    library."

    The whole "you may draw… if you do, choose… for each, pay-or-return"
    sequence is `SylvanLibraryEffect` (MEC-40) — see its own docstring for
    the documented "always the two just-drawn cards" simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sylvan_library", {"life": 4, "count": 2})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "draw"}, "phase_relation": "you",
            },
            optional=True,
        ),
    ]


register("Sylvan Library", _sylvan_library)


def _the_jolly_balloon_man() -> list[AbilitySpec]:
    """The Jolly Balloon Man (Legendary Creature — Human Clown, {1}{R}{W})

    "Haste
    {1}, {T}: Create a token that's a copy of another target creature you
    control, except it's a 1/1 red Balloon creature in addition to its
    other colors and types and it has flying and haste. Sacrifice it at
    the beginning of the next end step. Activate only as a sorcery."

    Haste is already parser-claimable. The activated ability reuses
    `CopyPermanentEffect`'s new ``set_power``/``set_toughness``
    (MEC-40, "except it's a 1/1") and ``extra_temp_keywords`` (flying,
    alongside the existing ``haste`` bool) plus its existing
    ``add_subtypes``; the delayed self-sacrifice reuses the already-general
    `CreateDelayedTriggerEffect` (RULE 603.7, step="end") the Marchesa
    V4.2 batch's Kiki-Jiki primitive established. **Documented
    simplification**: the token doesn't actually gain the printed extra
    "red" colour (`Card` has no colour-override field — colours are
    derived from mana cost, which a token has none of to override) —
    cosmetic only, no gameplay-visible effect for a token sacrificed at
    the next end step.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "copy_permanent",
                    {
                        "target_kind": "other_creature_you_control",
                        "set_power": 1, "set_toughness": 1,
                        "add_subtypes": ["Balloon"],
                        "haste": True, "extra_temp_keywords": ["flying"],
                    },
                ),
                EffectSpec(
                    "create_delayed_trigger",
                    {
                        "step": "end", "scope": "any", "capture": "created_objects",
                        "effects": [{"type": "sacrifice_specific", "params": {}}],
                        "description": "The Jolly Balloon Man: Balloon-Token am "
                                        "nächsten Endsegment opfern",
                    },
                ),
            ],
            cost={"text": "{1}, {T}", "sorcery_speed_only": True},
        ),
    ]


register("The Jolly Balloon Man", _the_jolly_balloon_man)


def _yasharn_implacable_earth() -> list[AbilitySpec]:
    """Yasharn, Implacable Earth (Legendary Creature — Elemental Boar,
    {2}{G}{W})

    "When Yasharn enters, search your library for a basic Forest card and
    a basic Plains card, reveal those cards, put them into your hand, then
    shuffle.
    Players can't pay life or sacrifice nonland permanents to cast spells
    or activate abilities."

    The ETB is two independent single-card searches (a Forest, then a
    Plains — `SearchLibraryEffect` has no "two distinct named basics in
    one search" shape, but running it twice with different criteria is
    rules-equivalent and simpler). The restriction reuses the new
    ``cost_restriction`` static (MEC-40), checked at every cost-payment
    choke point that offers a pay-life/sacrifice component.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("search", {"criteria": {"basic": True, "type": "Forest"}, "destination": "hand"}),
                EffectSpec("search", {"criteria": {"basic": True, "type": "Plains"}, "destination": "hand"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_restriction", {"kinds": ["pay_life", "sacrifice_nonland_permanent"]})],
        ),
    ]


register("Yasharn, Implacable Earth", _yasharn_implacable_earth)


# MEC-41: [cEDH] Glarb Bloomsday's remaining 8 gaps, done to completion


def _ad_nauseam() -> list[AbilitySpec]:
    """Reveal the top card of your library and put that card into your
    hand. You lose life equal to its mana value. You may repeat this
    process any number of times.

    — MEC-41. New `reveal_top_hand_lose_life_loop`/`RulesEngine.request_
    reveal_top_hand_lose_life_loop` — the engine's second open-ended,
    self-re-opening loop (see its own docstring for why it's a genuinely
    distinct shape from Lim-Dûl's Vault's `look_top_pay_life_loop`, not a
    parameterization of it): life lost varies per revealed card instead of
    a flat cost, the destination is hand instead of back into the library,
    and nothing stops the loop at 0 life (RULE 118.4 doesn't apply to a
    life-*loss* effect, only to paying life as a cost) — SBAs simply
    aren't checked mid-resolution.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("reveal_top_hand_lose_life_loop", {})],
        ),
    ]


register("Ad Nauseam", _ad_nauseam)


def _autumns_veil() -> list[AbilitySpec]:
    """Spells you control can't be countered by blue or black spells this
    turn, and creatures you control can't be the targets of blue or black
    spells this turn.

    — MEC-41. New `grant_cant_be_target_of_spell_color` for the second
    clause — RULE 115's own targeting restriction, deliberately narrower
    than hexproof (which also blocks *abilities*, and which this engine
    has no colour-qualified form of yet — Veil of Summer's own entry
    documents that gap) and than full protection (which also blocks
    damage/blocking/enchanting); see the effect's own docstring.
    **Documented simplification**: the first clause is modeled as
    unconditional "can't be countered this turn" (Veil of Summer's own
    `mark_your_spells_on_stack_cant_be_countered`/`arm_spell_watcher
    (repeat=True)` shape) rather than qualified by the countering spell's
    own colour — `RulesEngine._is_cant_be_countered`'s RULE 118 check has
    no notion of *what* is doing the countering at all, only whether the
    target carries the marker, and this is a strict *widening* (protects
    against every counterspell, not just blue/black ones) rather than a
    wrongly-narrower one; non-blue/black counterspells are rare enough
    that building the qualified form is disproportionate to this one card.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("mark_your_spells_on_stack_cant_be_countered", {}),
                EffectSpec("arm_spell_watcher", {
                    "then_specs": [{"type": "mark_cant_be_countered", "params": {}}],
                    "repeat": True,
                }),
                EffectSpec("grant_cant_be_target_of_spell_color", {
                    "colors": ["U", "B"], "selector": "creatures_you_control",
                }),
            ],
        ),
    ]


register("Autumn's Veil", _autumns_veil)


def _bring_to_light() -> list[AbilitySpec]:
    """Converge — Search your library for a creature, instant, or sorcery
    card with mana value less than or equal to the number of colors of
    mana spent to cast this spell, exile that card, then shuffle. You may
    cast that card without paying its mana cost.

    — MEC-41. RULE 702.108a Converge's own count (`GameObject.colors_
    spent_to_cast`, diffed off the payer's `ManaPool` before vs. after
    payment at `RulesEngine.cast_spell`) reaches `SearchLibraryEffect`'s
    criteria the same way the existing ``"x"``/``"source_x_paid"``
    sentinels do — `RulesEngine._substitute_x`'s own criteria-walking pass
    gained a third sentinel, ``"colors_spent_to_cast"``. The exile-then-
    standing-free-cast destination (``"exile_free_cast"``) is also new
    (see `SearchLibraryEffect`'s own docstring) — distinct from the
    already-shipped ``"cast_free"`` (which casts immediately, Sunforger-
    shaped): here the found card sits in exile with a standing permission
    until the caster chooses to use it, exactly as printed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": {
                    "type": ["Creature", "Instant", "Sorcery"],
                    "max_mana_value": "colors_spent_to_cast",
                },
                "destination": "exile_free_cast",
                "zones": ["library"],
            })],
        ),
    ]


register("Bring to Light", _bring_to_light)


def _counterbalance() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, you may reveal the top card of
    your library. If you do, counter that spell if it has the same mana
    value as the revealed card.

    — MEC-41. ENG-37 B5: `reveal_top` stashes the top card as the
    `revealed` referent, then `if_else` gates on `amount_compare`
    (revealed card's mana value == the firing `SPELL_CAST` event's own
    ``mana_value`` — the new `trigger_event` `effect_amounts` kind) and,
    when it matches, `counter` the triggering spell
    (``target_from_trigger_event="instance_id"``) so RULE 118 "can't be
    countered" is still honoured. "You may reveal" is a documented
    simplification to unconditional, as in the retired fused effect.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "reveal_top", "params": {"whose": "you"}},
                {"type": "if_else", "params": {
                    "condition": {"kind": "amount_compare", "op": "eq",
                                  "left": {"kind": "characteristic",
                                           "characteristic": "mana_value", "of": "revealed"},
                                  "right": {"kind": "trigger_event", "field": "mana_value"}},
                    "then": [{"type": "counter",
                              "params": {"target_from_trigger_event": "instance_id"}}],
                    "else": [],
                }},
            ]})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group", "controller": "not_you"},
            },
        ),
    ]


register("Counterbalance", _counterbalance)


def _lazotep_quarry() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}, Sacrifice a creature: Add one mana of any color.
    {X}{2}, {T}, Sacrifice a Desert: Exile target creature card with mana
    value X from your graveyard. Create a token that's a copy of it,
    except it's a 4/4 black Zombie. Activate only as a sorcery.

    — MEC-41. The two mana abilities are plain oracle-derived RULE 605.1a
    lines (`game/mana_abilities.py`'s `parse_mana_abilities`, read off the
    card's own printed text unconditionally regardless of catalogue
    registration — see this module's own opening docstring) and need no
    entry here; only the third needs hand-authoring. New
    `exile_own_graveyard_card_mana_value_x` (reading the ability's own
    announced ``{X}`` via `GameObject.x_paid`, now stamped for an
    activated ability's own source too — see `GameEngine.activate_
    ability`) chained via ``then_specs`` into `create_token_copy_of_
    linked_exile`. **Documented simplifications**: RULE 115's "target" is
    read as a resolve-time pick instead (see the first effect's own
    docstring for why); colour ("black") is dropped, the same
    simplification The Jolly Balloon Man's own entry accepts (`Card.
    as_copy` has no colour override).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exile_own_graveyard_card_mana_value_x", {
                "then_specs": [
                    {"type": "copy_permanent", "params": {
                        "target_kind": None, "referent": "linked_exile",
                        "set_power": 4, "set_toughness": 4, "add_subtypes": ["Zombie"],
                    }},
                ],
            })],
            cost={"text": "{X}{2}, {T}, Sacrifice a Desert", "sorcery_speed_only": True},
        ),
    ]


register("Lazotep Quarry", _lazotep_quarry)


def _nissa_steward_of_elements() -> list[AbilitySpec]:
    """+2: Scry 2.
    0: Look at the top card of your library. If it's a land card or a
    creature card with mana value less than or equal to the number of
    loyalty counters on Nissa, Steward of Elements, you may put that card
    onto the battlefield.
    −6: Untap up to two target lands you control. They become 5/5
    Elemental creatures with flying and haste until end of turn. They're
    still lands.

    — MEC-41. +2 is the already-shipped plain ``scry`` effect. The 0
    ability is an ENG-37 B5 `seq`: `reveal_top` stashes the top card as
    the `revealed` referent, an `if_else` gates on "land **or** (creature
    **and** its mana value ≤ this planeswalker's loyalty)" (`any`/`all`
    combinators + an `amount_compare` of `characteristic(mana_value, of:
    revealed)` against `counters(loyalty, of: source)`), and its `then` is
    an `optional` (RULE 601.2b "you may") wrapping `put_revealed_card`
    onto the battlefield. The −6 reuses Kamahl,
    Heart of Krosa's own "target land becomes a creature until end of
    turn, still a land" `grant_until`/`type_change`+`grant_keyword` chain
    (MEC-12) verbatim, just widened to "up to two" targets — `TapEffect`'s
    own pre-existing "untap up to two target lands" shape (Snap-shaped) —
    instead of Kamahl's single one.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("scry", {"count": 2})],
            cost={"loyalty": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("seq", {"effects": [
                {"type": "reveal_top", "params": {"whose": "you"}},
                {"type": "if_else", "params": {
                    "condition": {"kind": "any", "conditions": [
                        {"kind": "is_card_type", "of": "revealed", "card_type": "land"},
                        {"kind": "all", "conditions": [
                            {"kind": "is_card_type", "of": "revealed", "card_type": "creature"},
                            {"kind": "amount_compare", "op": "le",
                             "left": {"kind": "characteristic",
                                      "characteristic": "mana_value", "of": "revealed"},
                             "right": {"kind": "counters",
                                       "counter": "loyalty", "of": "source"}},
                        ]},
                    ]},
                    "then": [{"type": "optional", "params": {
                        "effects": [{"type": "put_revealed_card",
                                     "params": {"destination": "battlefield"}}],
                        "prompt": "Karte ins Spiel bringen?",
                    }}],
                    "else": [],
                }},
            ]})],
            cost={"loyalty": 0},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("tap", {
                    "target_kind": "land_you_control", "count": 2, "optional": True, "untap": True,
                }),
                EffectSpec("grant_until", {
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "add_subtypes": ["Elemental"],
                        "power": 5, "toughness": 5,
                    }},
                    "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
                }),
                EffectSpec("grant_until", {
                    "static": {"type": "grant_keyword", "params": {"keywords": ["flying", "haste"]}},
                    "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
                }),
            ],
            cost={"loyalty": -6},
        ),
    ]


register("Nissa, Steward of Elements", _nissa_steward_of_elements)


def _valley_floodcaller() -> list[AbilitySpec]:
    """Flash
    You may cast noncreature spells as though they had flash.
    Whenever you cast a noncreature spell, Birds, Frogs, Otters, and Rats
    you control get +1/+1 until end of turn. Untap them.

    — MEC-41. Flash and the standing flash-permission clause are already
    parser-MODELED (copied verbatim per the hand-author-card skill's own
    guidance — `flash_permission`'s ``noncreature_only``, already built
    with this very card in mind, see its own registry comment); the third
    clause needed `PumpEffect`/`TapEffect`'s own new ``subtypes`` param —
    a ``selector`` group narrowed by a subtype list, the sibling
    `AddCountersEffect.subtypes` already had, that neither previously did.
    **Documented note**: the pump and untap clauses each carry their own
    copy of the four-subtype list rather than a cross-clause pronoun,
    since `GameContext.previous_selector` (MEC-28) only carries the bare
    selector *name*, not any subtype narrowing layered on top of it.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flash"}),
        AbilitySpec(
            "static",
            [EffectSpec("flash_permission", {"noncreature_only": True})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("pump", {
                    "power": 1, "toughness": 1, "selector": "creatures_you_control",
                    "subtypes": ["bird", "frog", "otter", "rat"],
                }),
                EffectSpec("tap", {
                    "selector": "creatures_you_control", "untap": True,
                    "subtypes": ["bird", "frog", "otter", "rat"],
                }),
            ],
            trigger={
                "event": "SPELL_CAST", "condition": {"subject": "you"},
                "spell_exclude_card_types": ["creature"],
            },
        ),
    ]


register("Valley Floodcaller", _valley_floodcaller)


def _gifts_ungiven() -> list[AbilitySpec]:
    """Search your library for up to four cards with different names and
    reveal them. Target opponent chooses two of those cards. Put the
    chosen cards into your graveyard and the rest into your hand. Then
    shuffle.

    — MEC-41. Intuition's own two-phase `intuition_search`/`RulesEngine.
    _request_intuition` shape, generalized with ``search_optional``/
    ``distinct_names``/``chosen_count``/``chosen_destination``/
    ``rest_destination`` — see that method's own docstring for exactly how
    Gifts Ungiven's shape differs from Intuition's (2 chosen instead of 1,
    and the chosen/rest destinations swapped — Gifts Ungiven's opponent
    pick sends the *chosen* pair to the graveyard and the *rest* to the
    searcher's hand, the mirror image of Intuition's "chosen → hand, rest
    → graveyard").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("intuition_search", {
                "count": 4, "search_optional": True, "distinct_names": True,
                "chosen_count": 2, "chosen_destination": "graveyard",
                "rest_destination": "hand",
            })],
        ),
    ]


register("Gifts Ungiven", _gifts_ungiven)


# ---------------------------------------------------------------------------
# MEC-42: `cEDH staples`'s remaining 12 gaps
# ---------------------------------------------------------------------------


def _ashling_the_limitless() -> list[AbilitySpec]:
    """Elemental permanent spells you cast from your hand gain evoke {4} as
    you cast them. (If you cast a spell for its evoke cost, it's
    sacrificed when it enters.)
    Whenever you sacrifice a nontoken Elemental, create a token that's a
    copy of it. The token gains haste until end of turn. At the beginning
    of your next end step, sacrifice it unless you pay {W}{U}{B}{R}{G}.

    — MEC-42. Evoke (RULE 702.74) had never been built at all — Solitude's
    own catalogue entry explicitly documented it as unmodeled — so this
    card needed the real primitive, not just a per-card workaround: a new
    ``evoke`` cast branch threaded through `can_cast`/`effective_cast_cost`/
    `cast_spell` exactly like Mutate's own substitution (`GameEngine.
    _evoke_cost`, `GameObject.cast_via_evoke`), and a genuinely new "sacrifice
    it when it enters" consequence (not a replacement — its own ETB trigger
    fires first) added right after `_resolve_permanent_spell`'s
    ENTERS_BATTLEFIELD event. This closes the *mana-cost* Evoke family for
    free (Mulldrifter/Shriekmaw/Wall of Reverence-shaped, whose printed
    Evoke line is a plain mana cost parsed straight into `parametric_
    keywords` like Mutate/Escalate's own cost-bearing keywords). MEC-65
    subsequently extended the same keyword binding and cast path to
    Solitude/Endurance/Fury/Subtlety/Grief's "exile a `<color>` card from
    your hand" payment, storing `exile_hand_card_color` in the existing
    parametric-keyword payload.
    Ashling's own *grant* ("Elemental permanent spells you cast from your
    hand gain evoke {4}") is a new `grant_evoke` static
    (`continuous.granted_evoke_cost_for`, the hand-cast-cost sibling of
    `has_standing_flash_permission`'s "permission static outside the layer
    engine" idiom, since a card still in hand has nothing for RULE 613's
    layer engine to have stamped).

    The second ability needed two more small primitives: `CopyPermanentEffect`'s
    new ``referent="trigger_event"`` (reads the firing SACRIFICE event's own
    ``instance_id`` via `GameState.find_object`, which searches every zone —
    the sacrificed creature is already in the graveyard by the time this
    trigger resolves, so neither the existing ``"source"`` nor ``"previous"``
    referent could name it), and `SacrificeUnlessPayEffect`'s new ``target``
    override (falls back to its own source, as every existing caller already
    relies on) so `CreateDelayedTriggerEffect`'s existing ``capture=
    "created_objects"`` — the same Kiki-Jiki/Puppeteer Clique "create/
    reanimate with haste, [sacrifice/exile] it at the beginning of the next
    end step" primitive — can bake the *token*, not Ashling herself, into
    the delayed "unless you pay" sacrifice. The trigger itself is RULE
    701.17's `EventType.SACRIFICE`, scoped ``sacrifice_type="elemental"`` +
    ``filter={"is_token": False}`` + ``condition={"subject": "you"}`` —
    entirely off the event's own existing payload, no new trigger-condition
    vocabulary needed.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_evoke", {"cost": "{4}", "subtype": "elemental"})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": None, "referent": "trigger_event", "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "controller",
                    "capture": "created_objects",
                    "effects": [
                        {"type": "sacrifice_unless_pay", "params": {"cost": "{W}{U}{B}{R}{G}"}},
                    ],
                    "description": "Ashling, the Limitless: Kopie opfern, "
                                   "außer {W}{U}{B}{R}{G} wird bezahlt",
                }),
            ],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "sacrifice_type": "elemental",
                "filter": {"is_token": False},
            },
        ),
    ]


register("Ashling, the Limitless", _ashling_the_limitless)


def _derevi_empyrial_tactician() -> list[AbilitySpec]:
    """Flying
    When Derevi enters and whenever a creature you control deals combat
    damage to a player, you may tap or untap target permanent.
    {1}{G}{W}{U}: Put Derevi onto the battlefield from the command zone.

    — MEC-42. Flying is a plain printed keyword, recognized independent
    of catalogue registration. The shared "you may tap or untap target
    permanent" clause needed a genuine new choice — `TapEffect`'s existing
    ``untap`` bool is fixed at bind time, but this is a real decision at
    resolution, layered on top of RULE 115's own "up to one" target
    optionality — so `TapEffect.choose_tap_or_untap` opens a new, small
    `RulesEngine._request_tap_or_untap_choice` `pending_choice` instead of
    applying a fixed tap/untap directly; two `AbilitySpec`s (ETB self,
    and the already-general RULE 603.1 group-subject "a creature you
    control deals combat damage to a player" shape Bident of Thassa/
    Deepfathom Skulker/Rapacious Guest already use) share the same effect
    *shape*, each its own fresh `EffectSpec` instance.

    Documented simplification: the third ability — "{1}{G}{W}{U}: Put
    Derevi onto the battlefield from the command zone." — is a genuinely
    different mechanism from RULE 903's ordinary command-zone *casting*
    (which this engine already fully supports, tax and all): a bare
    battlefield-entry with no stack, spell, or ETB-timing restriction,
    activated from a zone (command) no other activated ability in this
    engine can be offered from. Left unmodeled — RULE 903's normal
    "cast Derevi from the command zone" path already reaches the same
    outcome (Derevi returns to the battlefield), just through the stack
    and at full (taxed) cost rather than this flat discount, so nothing
    about the card is actually unplayable without it.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {
                "target_kind": "permanent", "optional": True, "choose_tap_or_untap": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {
                "target_kind": "permanent", "optional": True, "choose_tap_or_untap": True,
            })],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "type": "creature", "controller": "you", "other": False},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Derevi, Empyrial Tactician", _derevi_empyrial_tactician)


def _dauthi_voidwalker() -> list[AbilitySpec]:
    """Shadow (This creature can block or be blocked by only creatures
    with shadow.)
    If a card would be put into an opponent's graveyard from anywhere,
    instead exile it with a void counter on it.
    {T}, Sacrifice this creature: Choose an exiled card an opponent owns
    with a void counter on it. You may play it this turn without paying
    its mana cost.

    — MEC-42. Shadow is a plain printed evasion keyword, already
    recognized independent of catalogue registration. The graveyard
    redirect is a new standing `void_counter_redirect` static
    (`continuous.void_counter_redirect_controller_for`, the same
    battlefield-static-scan idiom Opposition Agent's `search_redirect`
    already uses), checked from `RulesEngine._move_to_graveyard` — the one
    choke point every graveyard-bound move funnels through — right
    alongside the existing Lurrus/Yawgmoth's Will redirects there;
    `GameState.void_counter_holder` (``instance_id -> holder player_id``)
    is the marker itself, never swept. The activated ability's own
    `ChooseVoidCounterCardEffect` gathers the live candidate pool (every
    opponent's exile zone, filtered to that marker) and reuses MEC-20's
    already-general ``"grant_free_cast"`` chooser action — a same-turn
    free-cast window, exactly what "you may play it this turn without
    paying its mana cost" asks for.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("void_counter_redirect", {})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("choose_void_counter_card", {})],
            cost={"text": "{T}, Sacrifice this creature"},
        ),
    ]


register("Dauthi Voidwalker", _dauthi_voidwalker)


def _mana_crypt() -> list[AbilitySpec]:
    """At the beginning of your upkeep, flip a coin. If you lose the flip,
    this artifact deals 3 damage to you.
    {T}: Add {C}{C}.

    — MEC-42. `CoinFlipEffect`'s already-established "damage with
    ``selector='controller'``" shape (Mana Vault's own "deals 1 damage to
    you", Vivi B4 batch) at Mana Crypt's own printed amount; no win
    branch (losing the flip is the only outcome with a consequence). The
    mana ability needs no catalogue entry at all — `game/mana_abilities.py`
    reads a card's plain "{T}: Add …" text unconditionally, independent of
    catalogue registration (confirmed by Lazotep Quarry, MEC-41).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("coin_flip", {
                "lose_effects": [{"type": "damage", "params": {"selector": "controller", "amount": 3}}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Mana Crypt", _mana_crypt)


def _march_of_swirling_mist() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may exile any number
    of blue cards from your hand. This spell costs {2} less to cast for
    each card exiled this way.
    Up to X target creatures phase out. (While they're phased out,
    they're treated as though they don't exist. Each one phases in before
    its controller untaps during their next untap step.)

    — MEC-42. Neither clause had a primitive: the additional cost needed a
    genuine RULE 601.2b "announce a value, adjust cost, then pay it"
    shape (mirroring Kicker's own sequencing exactly, just subtracting
    generic instead of adding it) — new `cast_spell`/`can_cast`/`effective_
    cast_cost` param ``exile_discount``, gated by a new `exile_discount_
    cost` static (`continuous.exile_discount_spec_for`, read straight off
    the spell's own `static_effects` in hand, the same way Delve/
    Affinity's own printed "costs less" static already is) so the
    mechanism stays generic rather than hardcoded to blue/{2}. "Up to X
    target creatures phase out" needed `PhaseOutEffect` widened from a
    single fixed target to a real multi-target count (`TargetSpec.
    count_selector`'s new ``"source_x_paid"`` entry, reading `GameObject.
    x_paid` — the spell's own announced {X} — fresh at target-gathering
    time, the same "read a live count, not a printed one" idiom Goad's
    own count-selector already established for a different source).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("exile_discount_cost", {"color": "U", "generic_per_card": 2})],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("phase_out", {
                "target_kind": "creature", "optional": True, "count_selector": "source_x_paid",
            })],
        ),
    ]


register("March of Swirling Mist", _march_of_swirling_mist)


def _orcish_bowmasters() -> list[AbilitySpec]:
    """Flash
    When this creature enters and whenever an opponent draws a card
    except the first one they draw in each of their draw steps, this
    creature deals 1 damage to any target. Then amass Orcs 1.

    — MEC-42. Flash is a plain printed keyword. "Except the first one
    they draw in each of their draw steps" is MEC-32's own `EventType.
    DRAW` ``first_in_draw_step`` flag (`RulesEngine._single_draw`, already
    built for Notion Thief/Chains of Mephistopheles' replacement effects)
    — the first *trigger* consumer of it, via a plain ``filter`` exact-
    match (`{"first_in_draw_step": False}`) rather than a replacement
    condition. Amass (RULE 701.48) had no primitive at all yet — new
    `AmassEffect`. Two `AbilitySpec`s (ETB self, and the opponent-scoped
    DRAW trigger) share the same effect *shape*, each its own fresh
    `EffectSpec` instance, the same split Derevi's own ETB-and-combat-
    damage pair uses right above.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("damage", {"amount": 1, "target_kind": "any"}),
                EffectSpec("amass", {"subtype": "Orc", "count": 1}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("damage", {"amount": 1, "target_kind": "any"}),
                EffectSpec("amass", {"subtype": "Orc", "count": 1}),
            ],
            trigger={
                "event": EventType.DRAW,
                "condition": {"subject": "group", "controller": "not_you"},
                "filter": {"first_in_draw_step": False},
            },
        ),
    ]


register("Orcish Bowmasters", _orcish_bowmasters)


def _praetors_grasp() -> list[AbilitySpec]:
    """Search target opponent's library for a card and exile it face down.
    Then that player shuffles. You may play that card for as long as it
    remains exiled.

    — MEC-42. RULE 701.19a "search **target opponent's** library" needed
    `SearchLibraryEffect`'s own controller (who actually picks) to differ
    from the library it searches/shuffles (the RULE 115 target) — new
    ``player_from_target`` (resolves ``player`` to the targeted opponent)
    threading a real ``chooser`` through `RulesEngine._request_search`
    down to `_search_choice`/`_finish_search`/`_put_searched_card`
    (``player_id`` in the pending choice becomes "who answers", a new
    ``library_owner_id`` carries "whose library" — the general "who's
    searching vs. who owns the library" split, reusable by any future
    Bribery/Mind's Desire-shaped card). The new ``"exile_face_down_
    standing_cast"`` destination combines the existing face-down-in-exile
    marker (Beseech the Mirror) with a standing (never-swept)
    `GameState.exile_cast_condition` grant to the *chooser*, not the
    searched player — the ordinary-cost sibling of Bring to Light's own
    same-player ``"exile_free_cast"`` (MEC-41). Also fixed a real, general
    gap found on the way: `can_play_land` never checked `_has_conditional_
    exile_permission` at all, so this permission (or Lukka's own) could
    never actually offer a land.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": "", "destination": "exile_face_down_standing_cast",
                "player_from_target": True,
            })],
        ),
    ]


register("Praetor's Grasp", _praetors_grasp)


def _sevinnes_reclamation() -> list[AbilitySpec]:
    """Return target permanent card with mana value 3 or less from your
    graveyard to the battlefield. If this spell was cast from a
    graveyard, you may copy this spell and may choose a new target for
    the copy.
    Flashback {4}{W} (You may cast this card from your graveyard for its
    flashback cost. Then exile it.)

    — MEC-42. Flashback is a plain printed cost-bearing keyword, already
    read straight off `parametric_keywords` independent of catalogue
    registration. The reanimation half is `ReturnFromGraveyardEffect`'s
    already-general ``target_kind="graveyard_permanent"``/``max_mana_
    value`` (RULE 701.3 family). "If this spell was cast from a
    graveyard, you may copy this spell..." needed a genuine new self-copy
    primitive — new `RulesEngine.copy_self_spell`, the sibling of `copy_
    spell` that builds the copy `StackItem` directly off this spell's own
    `GameObject` rather than looking up a live stack entry, since by the
    time this trailing clause resolves the original has already been
    popped off `GameState.stack` for resolution. Reads `GameObject.
    cast_via_flashback` directly (still true at this point — the "exile
    instead of graveyard" clearing happens only after every effect,
    this one included, has resolved). **Documented simplification**: "may
    choose a new target" keeps the original's own already-gathered target
    by default (RULE 707.10c's default outcome) rather than opening a
    genuine new-target choice — the same "no real new-targeting yet"
    simplification `CopySpellEffect` already documents for every other
    copy-a-spell card in this engine, not a fresh gap; reanimating the
    same (now already-battlefield) permanent a second time is simply a
    no-op, same as a real player declining to bother re-choosing.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_permanent", "max_mana_value": 3,
                    "destination": "battlefield",
                }),
                EffectSpec("if_else", {"condition": {"kind": "source_cast_via_flashback"},
                            "then": [{"type": "copy_self_spell", "params": {}}], "else": []}),
            ],
        ),
    ]


register("Sevinne's Reclamation", _sevinnes_reclamation)


def _teferi_time_raveler() -> list[AbilitySpec]:
    """Each opponent can cast spells only any time they could cast a
    sorcery.
    +1: Until your next turn, you may cast sorcery spells as though they
    had flash.
    −3: Return up to one target artifact, creature, or enchantment to
    its owner's hand. Draw a card.

    — MEC-42. The static needed a genuinely new restriction — new
    `sorcery_speed_only` (`continuous.forced_sorcery_speed_only`,
    consulted directly in `GameEngine.can_cast`'s own timing computation,
    forcing RULE 601.3b sorcery-speed timing for a restricted opponent
    even over an instant/Flash spell) — the mirror image of `flash_
    permission`'s existing "permission static outside the layer engine"
    treatment. The +1 reuses that same `flash_permission` static with a
    widened ``type_filter`` (``"sorcery"``, `continuous.has_standing_
    flash_permission`'s own word-list check) wrapped in `GrantUntilEffect`
    at the ``"your_next_turn"`` duration RULE 611.2b already supports.
    The −3 is fully `MODELED` by the oracle-text parser already
    (`ReturnToHandEffect` + `DrawCardEffect`); reused as-is via the
    `hand-author-card` skill's own `reuse` command rather than re-derived.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("sorcery_speed_only", {})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "flash_permission", "params": {"type_filter": ["sorcery"]}},
                "duration": "your_next_turn",
                "target_kind": None,
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_to_hand", {"target_kind": "permanent", "optional": True}), EffectSpec("draw", {"count": 1})],
            cost={"loyalty": -3},
        ),
    ]


register("Teferi, Time Raveler", _teferi_time_raveler)


def _touch_the_spirit_realm() -> list[AbilitySpec]:
    """When this enchantment enters, exile up to one target artifact or
    creature until this enchantment leaves the battlefield.
    Channel — {1}{W}, Discard this card: Exile target artifact or
    creature. Return it to the battlefield under its owner's control at
    the beginning of the next end step.

    — MEC-42. The ETB half is the established O-Ring shape (`ExileEffect
    (remember=True)` + `ReturnLinkedExileEffect` on LEAVES_BATTLEFIELD,
    Shire Shirriff/Leonin Relic-Warder-shaped), just a new union target
    kind — `targeting`'s new ``"artifact_or_creature"``, the same "two
    single-type kinds getting their own combined kind" idiom
    ``artifact_or_enchantment`` already established. Channel (RULE
    702.29) needed no new primitive at all: its "Discard this card:" cost
    is already `ActivationCost.discard_self`, already fully wired for a
    hand-zone activation (`GameEngine.can_activate`'s own documented
    Channel/Cycling branch) — just never bound to a real card doing
    anything but Cycling before. Its own return clause reuses `Return
    LinkedExileEffect` again, this time fired from a plain
    `create_delayed_trigger` (``step="end", scope="any"``) rather than a
    LEAVES_BATTLEFIELD trigger, since nothing here is attached to a
    permanent still on the battlefield to fire that trigger.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "artifact_or_creature", "optional": True, "remember": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": "artifact_or_creature", "remember": True}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "any",
                    "effects": [{"type": "return_linked_exile", "params": {}}],
                    "description": "Touch the Spirit Realm: exiliertes "
                                   "Objekt zurückbringen",
                }),
            ],
            cost={"text": "{1}{W}, Discard this card"},
        ),
    ]


register("Touch the Spirit Realm", _touch_the_spirit_realm)


def _tymna_the_weaver() -> list[AbilitySpec]:
    """Lifelink
    At the beginning of each of your postcombat main phases, you may pay
    X life, where X is the number of opponents that were dealt combat
    damage this turn. If you do, draw X cards.
    Partner (You can have two commanders if both have partner.)

    — MEC-42. Lifelink/Partner are plain printed keywords, recognized
    independent of catalogue registration (Partner is a legality flag
    `services/commander_legality.py` reads, not a gameplay ability with
    anything to bind). The trigger's own X needed a genuine new count
    selector — `continuous.count_selector`'s new
    ``"opponents_dealt_combat_damage_this_turn"``, aggregating `GameState.
    combat_damage_to_players_this_turn` (RULE 120.3, previously only ever
    read per-source) across every source that hit this turn, unlike that
    field's own keyed-by-source shape. The pay-X-draw-X body is the new
    `PayLifeEqualToOpponentsCombatDamagedDrawThatManyEffect` — computes X
    once, then opens the already-general `RulesEngine.request_pay_cost_
    then` choice with a dynamically built cost/effect pair, since neither
    the printed cost text nor the effect amount is a fixed value.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_life_equal_to_opponents_combat_damaged_draw_that_many", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "main2"}, "phase_relation": "you"},
        ),
    ]


register("Tymna the Weaver", _tymna_the_weaver)


# ---------------------------------------------------------------------------
# MEC-43: `cEDH staples 2`'s undiagnosed remainder — first batch, near-free
# reuses of primitives shipped for entirely different cards.
# ---------------------------------------------------------------------------
