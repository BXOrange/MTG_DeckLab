"""Card -> AbilitySpec catalogue entries, part 014 of 016.

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

def _contamination() -> list[AbilitySpec]:
    """At the beginning of your upkeep, sacrifice this enchantment unless
    you sacrifice a creature.
    If a land is tapped for mana, it produces {B} instead of any other
    type and amount.

    — MEC-43. The upkeep clause is already fully `MODELED` by the
    oracle-text parser (`sacrifice_unless_pay`); reused as-is. The second
    clause is an exact param match for `mana_type_override` (built for
    Damping Sphere's "if a land is tapped for 2 or more mana, {C}
    instead") — unscoped (``affects="all_lands"``, matching Damping
    Sphere's own unqualified reach) with ``min_amount=1`` instead of 2
    and ``to="B"`` instead of ``"C"``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_unless_pay", {"cost": "sacrifice a creature"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("mana_type_override", {"min_amount": 1, "to": "B"})],
        ),
    ]


register("Contamination", _contamination)


def _leveler() -> list[AbilitySpec]:
    """When this creature enters, exile all cards from your library.

    — MEC-43. `ExileLibraryEffect`/`"exile_library"` was already
    registered (built for Paradigm Shift) but had no real consumer yet.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_library", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Leveler", _leveler)


def _natural_order() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a green
    creature.
    Search your library for a green creature card, put it onto the
    battlefield, then shuffle.

    — MEC-43. The search half is already fully `MODELED` by the
    oracle-text parser; reused as-is. The additional cost needed a new
    color+type compound sacrifice-cost sentinel — `_matches_sacrifice_
    type`'s new ``"<color>_creature"`` branch (a catalogue-chosen
    sentinel, not derived from printed text by a parser handler),
    matched against the object's own layer-5 derived colours.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "color": "G"}, "destination": "battlefield",
            })],
            additional_cost={"sacrifice": "green_creature"},
        ),
    ]


register("Natural Order", _natural_order)


def _magda_brazen_outlaw() -> list[AbilitySpec]:
    """Other Dwarves you control get +1/+0.
    Whenever a Dwarf you control becomes tapped, create a Treasure
    token.
    Sacrifice five Treasures: Search your library for an artifact or
    Dragon card, put that card onto the battlefield, then shuffle.

    — MEC-43. The anthem and the tap-trigger are already fully `MODELED`
    by the oracle-text parser; reused as-is. The activated ability is
    `costs.ActivationCost.sacrifice_count`'s already-shipped ``(count,
    subtype)`` shape (Trail of Crumbs/Cauldron Familiar-family, ``(3,
    "food")``) at Magda's own ``(5, "Treasure")``, plus the already-
    general `SearchLibraryEffect` with an "artifact or Dragon" criteria
    union.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "power": 1, "toughness": 0, "affects": "other_creatures_you_control", "subtype": "Dwarf",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={
                "event": EventType.TAPPED,
                "condition": {
                    "subject": "group", "subtypes": ["dwarf"], "nontoken": False,
                    "controller": "you", "other": False,
                },
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": ["Artifact", "Dragon"]}, "destination": "battlefield",
            })],
            cost={"sacrifice_count": (5, "treasure")},
        ),
    ]


register("Magda, Brazen Outlaw", _magda_brazen_outlaw)


def _unmarked_grave() -> list[AbilitySpec]:
    """Search your library for a nonlegendary card, put that card into
    your graveyard, then shuffle.

    — MEC-43. Plain `SearchLibraryEffect(destination="graveyard")`; only
    needed a new ``"nonlegendary": True`` key in the search-criteria
    vocabulary (`models/card_query.py`), the negation of the already-
    supported "legendary" type-line word.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {"criteria": {"nonlegendary": True}, "destination": "graveyard"})],
        ),
    ]


register("Unmarked Grave", _unmarked_grave)


def _unsubstantiate() -> list[AbilitySpec]:
    """Return target spell or creature to its owner's hand.

    — MEC-43. Reuses `RulesEngine.bounce_spell_or_permanent` (Sink into
    Stupor/Hullbreaker Horror's own "still on the stack" bounce,
    MEC-12 M-K) — that method is already fully generic (falls back to
    ordinary `return_to_hand` whenever the target *isn't* currently a
    spell on the stack), so only a new, narrower `targeting` union kind
    (``"spell_or_creature"``, the "target spell or ability" (ENG-26)
    idiom applied to a permanent instead of an ability) was needed, not a
    new resolve-time mechanism.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {
                "target_kind": "spell_or_creature", "spell_or_permanent": True,
            })],
        ),
    ]


register("Unsubstantiate", _unsubstantiate)


def _teferi_master_of_time() -> list[AbilitySpec]:
    """You may activate loyalty abilities of Teferi on any player's turn
    any time you could cast an instant.
    +1: Draw a card, then discard a card.
    −3: Target creature you don't control phases out.
    −10: Take two extra turns after this one.

    — MEC-43. The instant-speed activation clause reuses The Wandering
    Emperor's own `conditional_flash` mechanism (`GameEngine._can_
    activate_loyalty`), just with MEC-44's already-shipped
    ``"unconditional": True`` member (Necromancy's own "as though it had
    flash" with no gate at all) instead of Emperor's own "entered this
    turn" gate — carried on the first loyalty ability below, the same
    "`effect_binder.attach_to_object` scans every spec regardless of
    which one carries it" convention Emperor's own entry documents.
    −3 is `PhaseOutEffect(target_kind="creature_you_dont_control")`
    (already-general). −10 is `TakeExtraTurnEffect` listed twice — it
    has no ``count`` param, so "two" is just two queued turns.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1}), EffectSpec("discard", {"count": 1})],
            cost={"loyalty": 1},
            conditional_flash={"unconditional": True},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("phase_out", {"target_kind": "creature_you_dont_control"})],
            cost={"loyalty": -3},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("take_extra_turn", {}), EffectSpec("take_extra_turn", {})],
            cost={"loyalty": -10},
        ),
    ]


register("Teferi, Master of Time", _teferi_master_of_time)


def _march_of_otherworldly_light() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may exile any
    number of white cards from your hand. This spell costs {2} less to
    cast for each card exiled this way.
    Exile target artifact, creature, or enchantment with mana value X
    or less.

    — MEC-43. The additional cost is an exact recolor of March of
    Swirling Mist's own `exile_discount_cost` static (MEC-42) — white
    instead of blue, otherwise identical. The exile clause is an
    ordinary targeted `ExileEffect` with an MV filter, off the spell's
    own announced X (`max_mana_value_selector`-style — read fresh via
    the same `_substitute_x` sentinel machinery already generalized in
    MEC-41 for Bring to Light).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("exile_discount_cost", {"color": "W", "generic_per_card": 2})],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile", {
                "target_kind": "artifact_creature_or_enchantment", "max_mana_value": "x",
            })],
        ),
    ]


register("March of Otherworldly Light", _march_of_otherworldly_light)


# MEC-42: cEDH staples's last card, Delay


def _delay() -> list[AbilitySpec]:
    """Counter target spell. If the spell is countered this way, exile it
    with three time counters on it instead of putting it into its owner's
    graveyard. If it doesn't have suspend, it gains suspend. (At the
    beginning of its owner's upkeep, they remove a time counter. When the
    last is removed, they may play it without paying its mana cost. If
    it's a creature, it has haste.)

    — MEC-42. `parser_probe.py blocked` confirms this exact template is a
    genuine singleton (SOLO on 1, no other cached card shares it), but it
    was left open for two prior batches because closing it correctly needs
    RULE 702.62 Suspend's own time-counter/cast-on-zero mechanism, which
    had never been built at all (only keyword-recognized) — this batch
    builds that as a real, general primitive rather than special-casing
    Delay alone:

    * `RulesEngine.counter_spell`'s new `suspend_time_counters` param
      (threaded through `counter_unless_pays`, `CounterSpellEffect`'s own
      new `suspend_instead`, and `GameContext.counter`) redirects the
      countered spell to exile with N time counters instead of the
      graveyard, and stamps `GameObject.granted_suspend` when the card has
      no printed Suspend of its own (RULE 702.62's "if it doesn't have
      suspend, it gains suspend").
    * RULE 702.62a's second and third abilities — "at the beginning of your
      upkeep, remove a time counter" and "when the last is removed, you may
      cast it without paying its mana cost" — are collected fresh every
      owner's upkeep by `_collect_suspend_triggers` (`game/rules/
      triggers_mixin.py`) rather than bound once at load time: a suspended
      card sits in exile, never a permanent, so `_collect_triggers`'s
      battlefield-only scan can never see it, and Suspend can be *granted*
      mid-game with nothing printed on the card to have pre-attached a
      bound `TriggeredAbility` to in the first place — the same "no
      permanent to hang an ability off" shape `_collect_inherent_triggers`
      already uses for Monarch/Initiative. `SuspendUpkeepEffect`
      (`game/effects/core.py`) is the combined atomic action (remove one
      counter; at zero, open the free-cast window), the same "remove, then
      branch on empty" shape Vanishing's own upkeep pair
      (`RemoveCounterOrSacrificeEffect`) already established.
    * The free-cast offer itself reuses `RulesEngine.grant_free_cast_
      window_from_exile` — the same same-turn-only standing permission
      Rebound's own delayed half already grants (`ReboundFreeCastWindow
      Effect`), a documented fidelity trade-off for "no synchronous
      mid-resolution yes/no chooser" rather than a new one invented for
      Suspend. "If you cast a creature spell this way, it gains haste" is
      `GameObject.granted_suspend_haste`, stamped alongside the window and
      consumed once at resolution exactly like `cast_via_evoke`.

    RULE 702.62a's first ability (the hand-zone special action) is provided
    by `GameEngine.suspend` (MEC-64): it pays the printed Suspend cost,
    exiles the card with its printed number of time counters, and leaves the
    existing exile-zone upkeep scanner to do the rest.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {"suspend_instead": 3})],
        ),
    ]


register("Delay", _delay)


def _gaddock_teeg() -> list[AbilitySpec]:
    """Noncreature spells with mana value 4 or greater can't be cast.
    Noncreature spells with {X} in their mana costs can't be cast.

    — MEC-43, one of `cast_prohibition`'s two "shared primitive" clusters:
    the first clause needed a **literal** threshold (`max_mana_value`, new
    — every prior `cast_prohibition` card read a dynamic `count_selector`
    instead), the second a wholly independent flat check on the printed
    cost string (`has_x_cost`) unrelated to mana value at all. Two
    separate statics rather than one combined check, since a spell can
    trip either clause without the other (a noncreature {X} spell of mana
    value 2 is still illegal). ``scope="all"``: unlike the "opponents"
    default this static family started with, Gaddock Teeg restricts
    *every* player, its own controller included.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True, "max_mana_value": 3,
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True, "has_x_cost": True,
            })],
        ),
    ]


register("Gaddock Teeg", _gaddock_teeg)


def _sanctum_prelate() -> list[AbilitySpec]:
    """As this creature enters, choose a number.
    Noncreature spells with mana value equal to the chosen number can't
    be cast.

    — MEC-43. The other half of `cast_prohibition`'s literal-threshold
    cluster: an "equal to" comparison (`cmp="eq"`, new) against a number
    picked as this enters, not a fixed constant — `ChooseNumberReplacement`
    (new, a fifth `enter_choice_effects` sibling of `ChooseCreatureType
    Replacement`/`ChooseColorReplacement`/`ChooseNamedModeReplacement`/
    `ChooseCardNameReplacement`) offers a free-text numeric pick the same
    way `ChooseCardNameReplacement` offers a free-text name, stamping
    `GameObject.chosen_number`; `max_mana_value`'s new ``"chosen_number"``
    sentinel reads it back live off this object every check, so a Replay-
    mode edit to the choice is honoured immediately.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_number_on_enter", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True,
                "max_mana_value": "chosen_number", "cmp": "eq",
            })],
        ),
    ]


register("Sanctum Prelate", _sanctum_prelate)


def _chalice_of_the_void() -> list[AbilitySpec]:
    """This artifact enters with X charge counters on it.
    Whenever a player casts a spell with mana value equal to the number
    of charge counters on this artifact, counter that spell.

    — MEC-43, the "counter-trigger sibling" of Gaddock Teeg/Sanctum
    Prelate's `cast_prohibition` cluster: unlike those two, Chalice
    doesn't stop the spell from being *cast* at all — it lets it be cast
    and then counters it, RULE 701.5's actual mechanism, so this is a
    triggered ability rather than a third `cast_prohibition`. The first
    clause needs no code at all: `ability_catalogue.entry_counters`
    (`parser.oracle.catalogue.counters.entry_counters`) already recognizes
    "enters with X `<kind>` counters" generically off the card's own raw
    oracle text at every battlefield-entry site, independent of whether
    the card has a catalogue registration — confirmed live against this
    card's cached text. The trigger reuses `CounterSpellEffect.
    target_from_trigger_event` (Vexing Bauble's own "if no mana was spent
    to cast it, counter that spell" shape) for "counter *that* spell" —
    the very spell whose cast fired this ability, not a chosen target —
    and a new `mana_value_equals_source_counters` trigger-condition key
    (`effect_binder._trigger_condition`) for the live "mana value == this
    permanent's own charge-counter count" comparison, since no existing
    predicate reads a counter count off the ability's own source.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {"target_from_trigger_event": "instance_id"})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group"},
                "mana_value_equals_source_counters": "charge",
            },
        ),
    ]


register("Chalice of the Void", _chalice_of_the_void)


def _ethersworn_canonist() -> list[AbilitySpec]:
    """Each player who has cast a nonartifact spell this turn can't cast
    additional nonartifact spells.

    — MEC-43, `cast_prohibition`'s second shared-primitive cluster: a
    boolean-flag restriction rather than any mana-value comparison at
    all — "already cast a nonartifact spell this turn", a different shape
    from the literal/selector mana-value family Gaddock Teeg/Sanctum
    Prelate use. `GameState.nonartifact_spells_cast_this_turn` (new, the
    nonartifact-scoped sibling of `noncreature_spells_cast_this_turn`,
    incremented in lockstep by the same `RulesEngine._track_spell_cast`)
    backs a new `min_count_selector` param: prohibited once that count is
    >= 1 **for the casting player**, checked before the current cast's own
    increment lands (the same "already reflects the very spell" ordering
    every other `spells_cast_this_turn`-family check relies on, so a
    player's own *first* nonartifact spell is never wrongly caught). RULE
    613.6-adjacent ``scope="all"``: the restriction binds every player,
    Canonist's own controller included, exactly like Gaddock Teeg.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "nonartifact": True,
                "min_count_selector": "nonartifact_spells_cast_this_turn",
            })],
        ),
    ]


register("Ethersworn Canonist", _ethersworn_canonist)


def _birthing_pod() -> list[AbilitySpec]:
    """{1}{G/P}, {T}, Sacrifice a creature: Search your library for a
    creature card with mana value equal to 1 plus the sacrificed
    creature's mana value, put that card onto the battlefield, then
    shuffle. Activate only as a sorcery.

    — MEC-43, the other shared-primitive cluster: `GameObject.sacrificed_
    cost_mana_value` was only ever stamped for a *spell's* RULE 601.2b
    additional cost (`_pay_additional_cast_cost`) — an *activated
    ability's* own sacrifice cost (`_pay_activation_cost`) stamped
    nothing at all. Mirroring the same stamp there (right after the
    victim reaches the graveyard, cleared unconditionally at the top of
    every payment the same way the cast-cost site does) is the one new
    piece; `SearchLibraryEffect.mana_value_from` (Eldritch Evolution/
    Neoform's own "N plus the sacrificed X's mana value" shape) already
    reads it generically off whatever `GameObject` an effect's ``source``
    resolves to — an activated ability's own permanent, here — with no
    changes needed on the search side at all.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"},
                "destination": "battlefield",
                "mana_value_from": {"source": "sacrificed_cost", "plus": 1, "cmp": "eq"},
            })],
            cost={"text": "{1}{G/P}, {T}, Sacrifice a creature", "sorcery_speed_only": True},
        ),
    ]


register("Birthing Pod", _birthing_pod)


def _oswald_fiddlebender() -> list[AbilitySpec]:
    """Magical Tinkering — {W}, {T}, Sacrifice an artifact: Search your
    library for an artifact card with mana value equal to 1 plus the
    sacrificed artifact's mana value, put it onto the battlefield, then
    shuffle. Activate only as a sorcery.

    — MEC-43, Birthing Pod's own artifact-scoped mirror, closing the same
    activation-cost sacrifice-stamp cluster's second card. "Magical
    Tinkering" is a bare ability word (RULE 207.2c) — flavour only, no
    rules meaning, so it's dropped rather than modeled.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact"},
                "destination": "battlefield",
                "mana_value_from": {"source": "sacrificed_cost", "plus": 1, "cmp": "eq"},
            })],
            cost={"text": "{W}, {T}, Sacrifice an artifact", "sorcery_speed_only": True},
        ),
    ]


register("Oswald Fiddlebender", _oswald_fiddlebender)


def _chandras_incinerator() -> list[AbilitySpec]:
    """This spell costs {X} less to cast, where X is the total amount of
    noncombat damage dealt to your opponents this turn.
    Trample
    Whenever a source you control deals noncombat damage to an opponent,
    this creature deals that much damage to target creature or
    planeswalker that player controls.

    — MEC-45 (Ojer cEDH's last gap). The cost reduction reuses
    `self_cost_reduction_for`'s existing "generic-times-count_selector"
    multiply-by-`per` shape (Delve/Affinity's own mechanism) — the only
    new piece is `GameState.noncombat_damage_to_opponents_this_turn`, a
    running per-player *amount* total (`RulesEngine.deal_damage`
    increments it directly on any noncombat hit against an opponent),
    registered as a `count_selector` value the same way every other
    per-turn tracker is. The trigger's amount half is already fully
    general (`DealDamageEffect.amount_from_trigger_event`, Imodane's own
    primitive); its target half needed two genuinely new pieces: a
    `requires_damage_to_opponent` trigger-condition predicate (the DAMAGE
    event's recipient must be some player other than this ability's own
    controller — the "group"/"controller": "you" check only ever scopes
    the *source*, not who was hit) combined with the DAMAGE event's own
    already-general ``"filter": {"combat": False}`` for "noncombat", and a
    wholly new `targeting.py` kind, ``creature_or_planeswalker_that_
    player_controls`` — "that player" is whichever opponent the *firing*
    trigger event actually named, not a fixed "opponent" role, so
    `legal_targets` needed a new ``trigger_event`` parameter threaded from
    `triggers_mixin.py`'s own two target-gathering call sites.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 1,
                "per": "noncombat_damage_to_opponents_this_turn",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "target_kind": "creature_or_planeswalker_that_player_controls",
                "amount_from_trigger_event": "amount",
            })],
            trigger={
                "event": "DAMAGE",
                "condition": {"subject": "group", "controller": "you"},
                "filter": {"combat": False},
                "requires_damage_to_opponent": True,
            },
        ),
    ]


register("Chandra's Incinerator", _chandras_incinerator)


# ---------------------------------------------------------------------------
# MEC-43 "near-free reuses" batch (2026-08-21) — cEDH staples 2's remaining
# gaps that only needed an existing primitive recoloured/param-widened, per
# BACKLOG.md's own clustering. See Done_Backend.md's "MEC-43" entry for the
# primitives each of these closed along the way (sacrificed_cost_power,
# graveyard_redirect, cast_prohibition's color/creature_only/zones knobs,
# dig_until's graveyard rest destination, grant_borrowed_activated_ability's
# top_of_library source mode, the each_player_pay_or scope/effect_targets
# widening, the Uba Mask draw replacement, and several small trigger-
# condition/target-kind additions).
# ---------------------------------------------------------------------------


def _aetherflux_reservoir() -> list[AbilitySpec]:
    """Whenever you cast a spell, you gain 1 life for each spell you've
    cast this turn.
    Pay 50 life: This artifact deals 50 damage to any target.

    — MEC-43. The life-gain trigger reuses `continuous.count_selector`'s
    existing ``"spells_cast_this_turn"`` entry — incremented synchronously
    at cast time, so it already includes the just-cast spell by the time
    this ability resolves off the stack; the activated ability is a plain
    RULE 118.4 ``{"pay_life": 50}`` cost into an ordinary any-target damage
    effect.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"count_selector": "spells_cast_this_turn"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 50, "target_kind": "any"})],
            cost={"pay_life": 50},
        ),
    ]


register("Aetherflux Reservoir", _aetherflux_reservoir)


def _altar_of_dementia() -> list[AbilitySpec]:
    """Sacrifice a creature: Target player mills cards equal to the
    sacrificed creature's power.

    — MEC-43. Needed the power sibling of `GameObject.sacrificed_cost_
    mana_value` (`sacrificed_cost_power`, now stamped by `GameEngine.
    _pay_ability_cost` alongside the mana-value one) and a new `MillEffect.
    count_selector` param reading it back via `continuous.count_selector`'s
    matching new entry.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("mill", {
                "target_kind": "player", "count_selector": "sacrificed_cost_power",
            })],
            cost={"sacrifice": "creature"},
        ),
    ]


register("Altar of Dementia", _altar_of_dementia)


def _burnt_offering() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Add X mana in any combination of {B} and/or {R}, where X is the
    sacrificed creature's mana value.

    — MEC-43. The same "any combination of `<colors>`" simplification
    (`AddManaEffect.any_color_choices`) Culling Ritual already established,
    with the amount now driven by the widened ``amount_selector`` ANY-branch
    reading `GameObject.sacrificed_cost_mana_value` (stamped by the
    RULE 601.2b additional-cost payment, the same channel Eldritch
    Evolution/Neoform already use).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {
                "colors": ["ANY"], "any_color_choices": ["B", "R"],
                "amount_selector": "sacrificed_cost_mana_value",
            })],
            additional_cost={"sacrifice": "creature"},
        ),
    ]


register("Burnt Offering", _burnt_offering)


def _sacrifice() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Add an amount of {B} equal to the sacrificed creature's mana value.

    — MEC-43. Burnt Offering's fixed-colour sibling: `AddManaEffect`'s
    existing ``color``/``amount_selector`` variable-count form (the same
    shape Mana Drain already used), reading `sacrificed_cost_mana_value`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {"color": "B", "amount_selector": "sacrificed_cost_mana_value"})],
            additional_cost={"sacrifice": "creature"},
        ),
    ]


register("Sacrifice", _sacrifice)


def _rain_of_filth() -> list[AbilitySpec]:
    """Until end of turn, lands you control gain "Sacrifice this land:
    Add {B}."

    — MEC-43. `GrantUntilEffect` wrapping the existing quoted-mana-ability
    grant (`grant_mana_ability`, Tyvar Kell's "Elves you control have
    '{T}: Add {B}.'") with its own ``cost`` upgrade (MEC-25, Goldspan
    Dragon) set to a self-sacrifice instead of the bare default {T} — an
    *added* ability on each land, not a replacement of anything printed,
    since a self-sacrifice cost never matches a land's own {T}-shaped mana
    ability. Untargeted (``target_kind=None``): the static's own ``affects``
    already scopes it to "lands you control".
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("grant_until", {
                "static": {
                    "type": "grant_mana_ability",
                    "params": {
                        "mana": [{"color": "B", "amount": 1}],
                        "cost": {"sacrifice": "self"},
                        "affects": "lands_you_control",
                    },
                },
                "duration": "end_of_turn",
                "target_kind": None,
            })],
        ),
    ]


register("Rain of Filth", _rain_of_filth)


def _conspicuous_snoop() -> list[AbilitySpec]:
    """Play with the top card of your library revealed.
    You may cast Goblin spells from the top of your library.
    As long as the top card of your library is a Goblin card, this
    creature has all activated abilities of that card.

    — MEC-43. The first two lines are `top_library.py`'s existing standing
    permission (`TopLibraryPermissionEffect`, ``subtypes=["goblin"]`` —
    "play with revealed" is this permission's own always-on visibility
    side effect, per its docstring, so it needs no separate clause here);
    the third is `grant_borrowed_activated_ability`'s new ``source_mode=
    "top_of_library"`` — a scratch, off-zone `GameObject` bound purely to
    read the top card's own activated abilities (a library card is never
    otherwise boarded), narrowed by the new ``donor_subtype`` filter.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {
                "look": True, "cast_spells": True, "subtypes": ["goblin"],
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self", "source_mode": "top_of_library",
                "donor_subtype": "goblin", "creature_only": False,
            })],
        ),
    ]


register("Conspicuous Snoop", _conspicuous_snoop)


def _defense_of_the_heart() -> list[AbilitySpec]:
    """At the beginning of your upkeep, if an opponent controls three or
    more creatures, sacrifice this enchantment, search your library for up
    to two creature cards, put those cards onto the battlefield, then
    shuffle.

    — MEC-43. A RULE 500.7 upkeep trigger gated by the new ``min_opponent_
    creatures`` RULE 603.4 intervening-if (`effect_binder._trigger_
    condition`), whose effects are a plain `sacrifice_self` followed by
    `SearchLibraryEffect(count=2, destination="battlefield")` — "up to two"
    is that effect's own existing ``optional=True`` default.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("sacrifice_self", {}),
                EffectSpec("search", {
                    "criteria": {"type": "Creature"}, "count": 2, "destination": "battlefield",
                }),
            ],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "min_opponent_creatures": 3,
            },
        ),
    ]


register("Defense of the Heart", _defense_of_the_heart)


def _earthcraft() -> list[AbilitySpec]:
    """Tap an untapped creature you control: Untap target basic land.

    — MEC-43. `ActivationCost.tap_others`'s existing bare-main-type
    matching (``(1, "creature")`` — RULE 118.9-style "an untapped creature
    you control" as a cost, already recognized for Dark Triumph's own
    "cycle" siblings) into `TapEffect`'s ``untap=True`` mode, targeting the
    new ``"basic_land"`` kind (the inverse filter of the existing
    ``"nonbasic_land"``).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"untap": True, "target_kind": "basic_land"})],
            cost={"tap_others": [1, "creature"]},
        ),
    ]


register("Earthcraft", _earthcraft)


def _hermit_druid() -> list[AbilitySpec]:
    """{G}, {T}: Reveal cards from the top of your library until you
    reveal a basic land card. Put that card into your hand and all other
    cards revealed this way into your graveyard.

    — MEC-43. `dig_until`'s existing dig with the new ``rest_destination=
    "graveyard"`` value (`RulesEngine._graveyard_remaining`, the graveyard
    sibling of the existing library-bottom/shuffled destinations) — the
    hit destination stays the default ``"hand"``.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("dig_until", {
                "criteria": {"basic": True}, "hit_destination": "hand",
                "rest_destination": "graveyard",
            })],
            cost={"text": "{G}, {T}"},
        ),
    ]


register("Hermit Druid", _hermit_druid)


def _kogla_the_titan_ape() -> list[AbilitySpec]:
    """When Kogla enters, it fights up to one target creature you don't
    control.
    Whenever Kogla attacks, destroy target artifact or enchantment
    defending player controls.
    {1}{G}: Return target Human you control to its owner's hand. Kogla
    gains indestructible until end of turn.

    — MEC-43. The ETB fight was already parser-MODELED; the other two are
    hand-authored here so the whole card is AUTHORED. The attack trigger
    needed a new ``defending_player_id`` field on the `EventType.ATTACKS`
    event itself (the already-resolved RULE 508.1a defender, not
    previously threaded into the event) and a matching `targeting.py`
    kind reading it, the same trigger-event-scoped idiom `creature_or_
    planeswalker_that_player_controls` uses for a DAMAGE event's
    recipient. The activated ability's "target Human you control" reuses
    `TargetSpec.creature_filter` (now threaded through `ReturnToHandEffect`
    too) rather than a new fixed target kind.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("fight", {
                "fighter_kind": None, "other_kind": "creature_you_dont_control",
                "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy", {
                "target_kind": "artifact_or_enchantment_defending_player_controls",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("return_to_hand", {
                    "target_kind": "creature_you_control", "creature_filter": {"subtype": "human"},
                }),
                EffectSpec("pump", {"power": 0, "toughness": 0, "keywords": ["indestructible"]}),
            ],
            cost={"text": "{1}{G}"},
        ),
    ]


register("Kogla, the Titan Ape", _kogla_the_titan_ape)


def _leyline_of_the_void() -> list[AbilitySpec]:
    """If this card is in your opening hand, you may begin the game with
    it on the battlefield.
    If a card would be put into an opponent's graveyard from anywhere,
    exile it instead.

    — MEC-43. The opening-hand permission is read straight off oracle text
    by `opening_hand_battlefield_permission` independent of catalogue
    registration (see its own docstring) — nothing to author here. The
    redirect is the new `graveyard_redirect` static (``scope="opponent"``,
    the default), the plain-exile sibling of Dauthi Voidwalker's
    `void_counter_redirect`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_redirect", {"scope": "opponent"})],
        ),
    ]


register("Leyline of the Void", _leyline_of_the_void)


def _rest_in_peace() -> list[AbilitySpec]:
    """When this enchantment enters, exile all graveyards.
    If a card or token would be put into a graveyard from anywhere, exile
    it instead.

    — MEC-43. The ETB is the already-shipped `ExileAllGraveyardsEffect`
    (Farewell's own mass-exile mode); the static is `graveyard_redirect`
    with ``scope="any"`` (unscoped, unlike Leyline of the Void's
    opponent-only reading).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_all_graveyards", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_redirect", {"scope": "any"})],
        ),
    ]


register("Rest in Peace", _rest_in_peace)


def _soulless_jailer() -> list[AbilitySpec]:
    """Permanent cards in graveyards can't enter the battlefield.
    Players can't cast noncreature spells from graveyards or exile.

    — MEC-43. The first clause is `graveyard_library_entry_prohibition`'s
    new ``card_type="permanent"`` value (unconditionally true — everything
    this check is ever reached for is already a permanent card); the
    second is `cast_prohibition`'s new ``zones`` allowlist (the sibling of
    its existing ``hand_only`` single-zone exemption) combined with the
    already-shipped ``noncreature``/``scope="all"``.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_library_entry_prohibition", {"card_type": "permanent"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True, "zones": ["graveyard", "exile"],
            })],
        ),
    ]


register("Soulless Jailer", _soulless_jailer)


def _chain_of_smog() -> list[AbilitySpec]:
    """Target player discards two cards. That player may copy this spell
    and may choose a new target for that copy.

    — MEC-43. The discard is ordinary; the copy is the new
    `CopySelfControlledByPreviousTargetEffect` — the discard target
    (`GameContext.previous_targets`) becomes the copy's controller,
    mirroring `CopySelfIfCastFromGraveyardEffect`'s own "may" simplification
    (always copies, keeps the same target) rather than opening a fresh
    interactive retarget.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("discard", {"count": 2, "target_kind": "player"}),
                EffectSpec("copy_self_spell", {
                    "controller": {"of": "target", "as": "self"},
                }),
            ],
        ),
    ]


register("Chain of Smog", _chain_of_smog)


def _destiny_spinner() -> list[AbilitySpec]:
    """Creature and enchantment spells you control can't be countered.
    {3}{G}: Target land you control becomes an X/X Elemental creature with
    trample and haste until end of turn, where X is the number of
    enchantments you control. It's still a land.

    — MEC-43. Only the first clause is authored here (`GrantCantBeCountered
    Effect`'s new ``"creature_or_enchantment_spells_you_control"`` scope,
    the two-type union sibling of the existing creature-only one); the
    land-animation activated ability is the recurring "animate a
    noncreature permanent into an X/Y creature" gap `BACKLOG.md` already
    tracks as its own open item, deliberately left unbound rather than
    stubbed here.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_cant_be_countered", {"scope": "creature_or_enchantment_spells_you_control"})],
        ),
    ]


register("Destiny Spinner", _destiny_spinner)


def _llawan_cephalid_empress() -> list[AbilitySpec]:
    """When Llawan enters, return all blue creatures your opponents
    control to their owners' hands.
    Your opponents can't cast blue creature spells.

    — MEC-43. The ETB is `ReturnToHandEffect`'s new ``"opponents_
    creatures"`` mass selector (the opponent-scoped sibling of the existing
    ``"all_creatures"``) combined with its also-new ``filter={"color":
    "U"}``; the static is `cast_prohibition`'s new ``color``/
    ``creature_only`` combination (MEC-43's first card needing both a
    card-type and a colour restriction on the same clause).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {
                "selector": "opponents_creatures", "filter": {"color": "U"},
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "opponents", "creature_only": True, "color": "U",
            })],
        ),
    ]


register("Llawan, Cephalid Empress", _llawan_cephalid_empress)


def _mana_breach() -> list[AbilitySpec]:
    """Whenever a player casts a spell, that player returns a land they
    control to its owner's hand.

    — MEC-43. A plain "group" subject with no ``controller`` filter (any
    player's cast, the same idiom Nether Void's own unscoped trigger
    uses); the new `BounceOwnLandFromTriggerEffect` reads the firing
    `SPELL_CAST` event's own ``player_id`` as the chooser/owner instead of
    this ability's own controller.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bounce_own_land_from_trigger", {})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group"}},
        ),
    ]


register("Mana Breach", _mana_breach)


def _selvala_heart_of_the_wilds() -> list[AbilitySpec]:
    """Whenever another creature enters, its controller may draw a card if
    its power is greater than each other creature's power.
    {G}, {T}: Add X mana in any combination of colors, where X is the
    greatest power among creatures you control.

    — MEC-43. The mana ability is a plain RULE 605 ability, parsed by
    `mana_abilities_for` rather than bound here. The trigger is the new
    `DrawIfTriggerObjectGreatestPowerEffect` — RULE 603.1's "its" resolves
    to the firing `ENTERS_BATTLEFIELD` event's own object, compared live
    against every other creature's derived power.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw_if_trigger_object_greatest_power", {})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "creature", "other": True},
            },
        ),
    ]


register("Selvala, Heart of the Wilds", _selvala_heart_of_the_wilds)


def _shifting_woodland() -> list[AbilitySpec]:
    """This land enters tapped unless you control a Forest.
    {T}: Add {G}.
    Delirium — {2}{G}{G}: This land becomes a copy of target permanent
    card in your graveyard until end of turn. Activate only if there are
    four or more card types among cards in your graveyard.

    — MEC-43. The enters-tapped clause is read straight off oracle text by
    `land_tap_condition` independent of catalogue registration, and the
    mana ability is a plain RULE 605 ability — neither needs authoring
    here. The Delirium-gated copy ability is `BecomeCopyUntilEndOfTurnEffect`
    retargeted at the new ``"graveyard_permanent"`` kind (the existing
    graveyard-target family's own ``"permanent"`` filter, own-graveyard
    scoped), gated by `ActivationCost.activation_condition` reusing RULE
    702.137 Delirium's existing `static_conditions` kind.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("become_copy_until_eot", {"target_kind": "graveyard_permanent"})],
            cost={
                "text": "{2}{G}{G}",
                "activation_condition": {"kind": "card_types_in_graveyard_at_least", "amount": 4},
            },
        ),
    ]


register("Shifting Woodland", _shifting_woodland)


def _tataru_taru() -> list[AbilitySpec]:
    """When Tataru Taru enters, you draw a card and target opponent may
    draw a card.
    Scions' Secretary — Whenever an opponent draws a card, if it isn't
    that player's turn, create a tapped Treasure token. This ability
    triggers only once each turn.

    — MEC-43. The ETB is a plain self-draw plus an optional targeted
    opponent draw. The second ability reuses `effect_binder`'s existing
    ``not_controllers_turn`` predicate (checked against the firing DRAW
    event's own actor, exactly "if it isn't **that player's** turn") and
    `TriggeredAbility.once_per_turn`.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("draw", {"count": 1, "target_kind": "opponent", "optional": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Treasure", "subtypes": ["Treasure"],
                "is_artifact": True, "tapped": True,
            })],
            trigger={
                "event": EventType.DRAW,
                "condition": {"subject": "group", "controller": "not_you"},
                "not_controllers_turn": True,
                "limit": True,
            },
        ),
    ]


register("Tataru Taru", _tataru_taru)


def _uba_mask() -> list[AbilitySpec]:
    """If a player would draw a card, that player exiles that card face up
    instead.
    Each player may play lands and cast spells from among cards they
    exiled with ~ this turn.

    — MEC-43. One replacement effect (`draw_exile_face_up`) covers both
    printed lines: it performs the exile itself and stamps `GameState.
    temp_play_permissions` on the exiled card in the same step, so the
    second line is a consequence of the first rather than a separate
    clause — the same "castable/playable from exile this turn" marker
    every other temp-exile-permission card already reads from `can_cast`/
    `can_play_land`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("draw_exile_face_up", {})],
        ),
    ]


register("Uba Mask", _uba_mask)


def _acererak_the_archlich() -> list[AbilitySpec]:
    """When Acererak enters, if you haven't completed Tomb of Annihilation,
    return Acererak to its owner's hand and venture into the dungeon.
    Whenever Acererak attacks, for each opponent, you create a 2/2 black
    Zombie creature token unless that player sacrifices a creature of
    their choice.

    — MEC-43. The ETB combines the new ``not_completed_dungeon`` RULE
    603.4 intervening-if (reading `Player.completed_dungeons`, RULE 309.7)
    with the already-shipped self-bounce + `venture` effects. The attack
    trigger is `EachPlayerPayOrEffect`'s new ``scope="each_opponent"``/
    ``effect_targets="controller"`` combination — every opponent
    independently chooses whether to sacrifice, and only a decliner's
    absence of payment lets Acererak's own controller make the token,
    never the decliner themselves.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_to_hand", {"target_kind": None}),
                EffectSpec("venture", {}),
            ],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
                "not_completed_dungeon": "Tomb of Annihilation",
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("each_player_pay_or", {
                "cost": "Sacrifice a creature",
                "scope": "each_opponent",
                "effect_targets": "controller",
                "effects": [{
                    "type": "create_token",
                    "params": {
                        "count": 1, "power": 2, "toughness": 2, "colors": ["B"],
                        "subtypes": ["Zombie"], "token_name": "Zombie",
                    },
                }],
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Acererak the Archlich", _acererak_the_archlich)


def _jeweled_amulet() -> list[AbilitySpec]:
    """{1}, {T}: Put a charge counter on this artifact. Note the type of
    mana spent to pay this activation cost. Activate only if there are no
    charge counters on this artifact.
    {T}, Remove a charge counter from this artifact: Add one mana of this
    artifact's last noted type.

    — MEC-43 (the ticket's one deliberately-deferred card, closed in a
    follow-up pass rather than a third deferral). "Note the type of mana
    spent" needed a genuinely new primitive: `ManaPool.pay` now stamps
    `last_payment_types` (which type(s) it actually drained — this card's
    own {1} cost has no fixed pip of its own to read instead), and
    `ActivationCost.note_spent_color` copies that onto `GameObject.
    noted_mana_color` right after payment (`GameEngine._pay_ability_cost`).
    This engine has no interactive "which color pays a generic pip" choice
    (`ManaPool._spend_generic`'s own colorless-first order decides it
    deterministically), so what gets noted isn't always a genuine player
    pick — an accepted simplification, the same tier every other "spend
    from the pool" caller already gets. The second ability reads it back
    via `AddManaEffect`'s new `color_from_source_noted_color`, the exact
    sibling of the existing `color_from_source_chosen_color` (Utopia
    Sprawl-shaped RULE 601.2b colour choices already use it the same way).
    "Activate only if there are no charge counters" is `ActivationCost.
    activation_condition` reusing the existing `source_counters` kind.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"kind": "charge", "count": 1}),
            ],
            cost={
                "text": "{1}, {T}",
                "note_spent_color": True,
                "activation_condition": {"kind": "source_counters", "counter": "charge", "max": 0},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {"color_from_source_noted_color": True})],
            cost={"taps_self": True, "remove_counters": ["charge", 1]},
        ),
    ]


register("Jeweled Amulet", _jeweled_amulet)


def _sanctifier_en_vec() -> list[AbilitySpec]:
    """Protection from black and from red
    When this creature enters, exile all cards that are black or red from
    all graveyards.
    If a black or red permanent, spell, or card not on the battlefield
    would be put into a graveyard, exile it instead.

    — MEC-43 round 2. Protection comes from the RULE 702 keyword catalogue
    (unaffected by hand-authoring — read straight off the printed card
    regardless of registration). The ETB sweep reuses `exile_all_
    graveyards`' new `colors` filter (round 1's Rest in Peace made the
    selector itself; this just narrows it). The replacement reuses round
    1's `graveyard_redirect` static with its new `colors` param instead of
    `scope` — Sanctifier's clause names no owner at all, so it always
    passes ``scope="any"`` alongside the colour filter that does the real
    work.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_all_graveyards", {"colors": ["B", "R"]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_redirect", {"scope": "any", "colors": ["B", "R"]})],
        ),
    ]


register("Sanctifier en-Vec", _sanctifier_en_vec)


def _beacon_of_unrest() -> list[AbilitySpec]:
    """Put target artifact or creature card from a graveyard onto the
    battlefield under your control. Shuffle Beacon of Unrest into its
    owner's library.

    — MEC-43 round 2, the reanimation-family batch. ``target_kind=
    "graveyard_artifact_or_creature"`` is the new combined graveyard-
    target filter; ``shuffle_self_into_library`` (Green Sun's Zenith) is
    reused verbatim for the second clause.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_artifact_or_creature", "under_your_control": True,
                }),
                EffectSpec("shuffle_self_into_library", {}),
            ],
        )
    ]


register("Beacon of Unrest", _beacon_of_unrest)


def _rise_from_the_grave() -> list[AbilitySpec]:
    """Put target creature card from a graveyard onto the battlefield
    under your control. That creature is a black Zombie in addition to
    its other colors and types.

    — MEC-43 round 2. The type/colour addition is `grant_until`'s
    ``previous_subject``/``duration="rest_of_game"`` combination (RULE
    611.2c — a resolving spell's own effect with no stated duration lasts
    indefinitely), reading back the just-reanimated creature the same way
    "It fights…" reads a prior clause's target — RULE 400.7 keeps the
    object's `instance_id` (and so its place in `previous_targets`) stable
    across the graveyard-to-battlefield zone change.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "under_your_control": True,
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "type_change", "params": {"add_subtypes": ["Zombie"]}},
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "color_change", "params": {"colors": ["B"], "set": False}},
                }),
            ],
        )
    ]


register("Rise from the Grave", _rise_from_the_grave)


def _tenacious_dead() -> list[AbilitySpec]:
    """When this creature dies, you may pay {1}{B}. If you do, return it
    to the battlefield tapped under its owner's control.

    — MEC-43 round 2. ``remember_trigger_subject`` (`PayCostThenEffect`)
    stamps the dying creature's own `instance_id` onto `GameObject.
    remembered_instance_id` before the interactive pay-or-decline choice
    opens (`context.trigger_event` is only live for the first, synchronous
    `apply()` call — the "if you do" branch runs later); the new
    `return_from_graveyard` `trigger_subject_key="remembered"` mode reads
    it back instead of taking a RULE 115 target, and the new ``tapped``
    param is the printed "return it to the battlefield **tapped**".
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{1}{B}",
                "remember_trigger_subject": True,
                "effects": [{
                    "type": "return_from_graveyard",
                    "params": {"trigger_subject_key": "remembered", "tapped": True},
                }],
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        )
    ]


register("Tenacious Dead", _tenacious_dead)
