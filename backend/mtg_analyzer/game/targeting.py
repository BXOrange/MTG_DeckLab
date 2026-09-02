"""Targeting: what an effect may target and which targets are legal *now*.

Reference: RULE 115 (targets), RULE 601.2c (a spell can't be cast unless the
required number of legal targets is available), RULE 608.2b (on resolution a
spell/ability with no legal targets doesn't resolve).

An effect either **targets** ("deal 3 damage to *target* creature") or acts
**globally / on a fixed set** ("each player draws", "destroy all creatures",
"you gain 3 life"). This module is the one place that (a) names *what kind*
of target a targeting effect wants (`TargetSpec`) and (b) computes the
*currently legal* targets from a `GameState` (`legal_targets`). The engine
uses it to gate an action: if a spell needs a target and the board offers
none, the action is offered **locked** rather than castable — the offer-time
half of RULE 601.2c.

Kept dependency-light: it reads models and duck-types an effect's
``target_spec`` attribute, so `game/effects.py` can import `TargetSpec` from
here without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

from ..models.game_object import GameObject, Zone
from ..models.game_state import GameState
from . import combat

#: A graveyard-card target's *scope* — whose graveyard(s) are searched — by
#: its `graveyard_*`/`any_graveyard_*`/`opponent_graveyard_*` kind prefix.
#: ``"own"`` is the controller's own graveyard (RULE 115, the recursion/
#: reanimation family — Regrowth/Reanimate-shaped, always says "your
#: graveyard"); ``"any"`` is Magic's "a graveyard" — one card from any single
#: graveyard, whosever it is (Deathrite Shaman, Virtue of Persistence);
#: ``"opponent"`` is "an opponent's graveyard" specifically (Puppeteer
#: Clique). Each maps to a `_GRAVEYARD_TYPE_FILTERS` suffix appended after
#: the prefix, e.g. ``graveyard_creature``/``any_graveyard_land``/
#: ``opponent_graveyard_card``.
_GRAVEYARD_SCOPE_PREFIXES: dict[str, str] = {
    "graveyard": "own",
    "any_graveyard": "any",
    "opponent_graveyard": "opponent",
}
#: A graveyard-card target's card-*type* filter, by kind suffix — the same
#: characteristics `_spell_matches_filter` checks for a "spell" target, just
#: read off the graveyard card's printed characteristics instead (no
#: layer-engine pass applies to a card that isn't on the battlefield).
_GRAVEYARD_TYPE_FILTERS: dict[str, Any] = {
    "card": lambda o: True,
    "creature": lambda o: o.is_creature,
    "land": lambda o: o.is_land,
    "artifact": lambda o: bool(o.card.is_artifact),
    "enchantment": lambda o: bool(o.card.is_enchantment),
    # "exile up to one target non-Aura enchantment card from your graveyard"
    # (Anikthea, Hand of Erebos — PAR-30 reanimator-token residue): an
    # enchantment whose printed type line carries no "Aura" subtype.
    "non_aura_enchantment": lambda o: bool(o.card.is_enchantment)
    and "aura" not in o.card.type_line.lower(),
    "instant_or_sorcery": lambda o: bool(o.card.is_instant or o.card.is_sorcery),
    # "target **sorcery** card in your graveyard gains flashback…" (MEC-24,
    # Recoup) — the sorcery-only narrowing of the combined filter above.
    "sorcery": lambda o: bool(o.card.is_sorcery),
    "permanent": lambda o: o.is_creature or o.is_land or o.is_planeswalker
    or bool(o.card.is_artifact or o.card.is_enchantment),
    "nonland_permanent": lambda o: o.is_creature or o.is_planeswalker
    or bool(o.card.is_artifact or o.card.is_enchantment),
    # "Put target artifact or creature card from a graveyard onto the
    # battlefield…" (MEC-43 round 2, Beacon of Unrest) — the artifact
    # sibling of `creature_or_planeswalker` below.
    "artifact_or_creature": lambda o: o.is_creature or bool(o.card.is_artifact),
    # "return a creature or planeswalker card from your graveyard to your
    # hand" (Takenuma, Abandoned Mire's Channel ability) — the union of the
    # two single-type filters, same idiom as `instant_or_sorcery` above.
    "creature_or_planeswalker": lambda o: o.is_creature or o.is_planeswalker,
}
#: Every ``{prefix}_{suffix}`` combination — the full graveyard-target kind
#: vocabulary (docs/09's Regrowth/Reanimate/Deathrite Shaman/Virtue of
#: Persistence family). ``graveyard_creature`` keeps its pre-existing bare
#: name (no redundant "_card"), matching the one kind this module already
#: had before generalizing.
_GRAVEYARD_TARGET_KINDS: frozenset[str] = frozenset(
    f"{prefix}_{suffix}" for prefix in _GRAVEYARD_SCOPE_PREFIXES for suffix in _GRAVEYARD_TYPE_FILTERS
)

#: The target categories the engine can resolve to concrete board objects.
#: "any" is Magic's "any target" (RULE 115.4): a creature, player,
#: planeswalker, or battle (MEC-43 widened `legal_targets`'s own "any"
#: branch to the last two — previously creature/player only, a stale
#: simplification from before either card type was modeled). Extend as new
#: restrictions land.
#: ``creature_you_control``/``land_you_control`` narrow a battlefield pick to
#: the controller's own permanents (RULE 115/603.3c, or a non-"target"
#: resolve-time choice among one's own permanents modeled the same way, e.g.
#: a bounce-land's "return a land you control…"); the `graveyard_*`/
#: `any_graveyard_*`/`opponent_graveyard_*` family (see
#: `_GRAVEYARD_TARGET_KINDS`) is a card of some type in some graveyard.
#: RULE 702.5's "Enchant `<X>` or `<Y>`" compound quality (Swift
#: Reconfiguration, MEC-43 round 4E) — one predicate per word an Aura's
#: printed "Enchant" line can name, unioned by ``" or "`` in
#: `legal_targets`'s own ``attachment_kind == "enchant"`` branch above.
#: "vehicle" is a subtype word, not one of `Card`'s own main-type flags
#: (a Vehicle's *main* type is Artifact, already covered by "artifact"
#: here), so it's matched off the printed type line directly — the same
#: idiom `legal_targets`'s ``attached_aura_or_equipment_you_control``
#: branch already uses for "equipment"/"aura".
_ENCHANT_QUALITY_PREDICATES: dict[str, Any] = {
    "creature": lambda o: o.is_creature,
    "artifact": lambda o: bool(o.card.is_artifact),
    "enchantment": lambda o: bool(o.card.is_enchantment),
    "land": lambda o: o.is_land,
    "planeswalker": lambda o: o.is_planeswalker,
    "vehicle": lambda o: "vehicle" in o.card.type_line.lower(),
}


ALLOWED_TARGET_KINDS: frozenset[str] = frozenset(
    {
        "any", "creature", "permanent", "player", "spell",
        # RULE 702.165a Backup — "target creature" that explicitly includes
        # the source itself (PAR-26); the plain `creature` branch minus its
        # RULE 115.6-style self-exclusion.
        "creature_including_self",
        # Single-type permanent targets (RULE 115.1c — "target artifact"/
        # "target enchantment"/"target land"), any controller's.
        "artifact", "enchantment", "land", "noncreature_artifact",
        # "target activated or triggered ability" (RULE 115/608.2b — Stifle/
        # Trickbind-shaped, ENG-26) — the stack-item-identity sibling of
        # ``"spell"``: an ability `StackItem` has no `.obj` a target
        # descriptor could key off (see `StackItem.stack_id`'s own
        # docstring), so this kind is keyed by that instead. Not narrowed to
        # just triggered or just activated — no printed card needs that
        # split yet, and every real template says "activated or triggered".
        "ability",
        # "target spell or ability" (Deflecting Swat's real printed
        # wording) — the union of ``"spell"`` and ``"ability"`` above, both
        # option shapes side by side in one list.
        "spell_or_ability",
        # "target player who was dealt combat damage by ~ this turn" (Hope of
        # Ghirapur) — `player` narrowed by a per-turn damage *history*, the
        # one target kind here answered from a record rather than the board.
        "player_dealt_combat_damage_by_source",
        # "target opponent" (MEC-11's Indoraptor-shaped, simplified from "an
        # opponent **at random**" — see the catalogue entry) — `player`
        # narrowed to exclude the ability's own controller.
        "opponent",
        "creature_you_control", "land_you_control",
        # "target land an opponent controls" (Political Trickery/Vedalken
        # Plotter's own exchange-control targets, PAR-29) — the
        # `land_you_control` mirror, same "you control"/"you don't
        # control" pairing `nonland_permanent_you_control`/`_dont_control`
        # already has.
        "land_you_dont_control",
        # RULE 109.5's "*another* target creature you control" (Giver of
        # Runes) — `creature_you_control` minus the ability's own source.
        "other_creature_you_control",
        # "target creature or enchantment you control" (MEC-43 round 4D,
        # Heliod, Sun-Crowned) — the two-type-union sibling of
        # `creature_you_control`, same "you control" scoping.
        "creature_or_enchantment_you_control",
        # "target creature you **don't** control" (Archdruid's Charm's second
        # mode) — the mirror image of `creature_you_control`.
        "creature_you_dont_control",
        # "target artifact you don't control" (Vandalblast) — the same
        # mirror-image shape as `creature_you_dont_control`, for artifacts.
        "artifact_you_dont_control",
        # "target permanent an opponent controls" (Assassin's Trophy/
        # Geomancer's Gambit) — the same mirror-image shape, unscoped by
        # permanent type (unlike the narrower `nonland_permanent_you_dont_
        # control` a couple of names).
        "permanent_you_dont_control",
        # "target permanent you own/control." (Reality Scramble) — the
        # controller-scoped mirror of `permanent_you_dont_control` above.
        "permanent_you_control",
        # "target permanent you neither own nor control" (PAR-30 — Conjured
        # Currency) — the double-negative sibling excluding both ownership
        # and control, unlike either single-negative kind above.
        "permanent_you_neither_own_nor_control",
        # "{T}: Transform target Incubator token you control." (Progenitor
        # Exarch) — a name-keyed token target, the Incubate family's own
        # two-state token (`ability_catalogue` "Incubator").
        "incubator_token_you_control",
        # "target nonland permanent" (Retraction Helix-shaped) — any
        # controller's, unlike the `_you_control`/`_you_dont_control`
        # suffixed forms (which have their own `legal_targets` branch); the
        # bare unscoped form's own `legal_targets` branch already existed
        # but was never whitelisted.
        "nonland_permanent",
        # "target nonland permanent an opponent controls" / "… you don't
        # control" (Lyev Skyknight/New Prahv Guildmage's detain, PAR-29) and
        # its "you control" mirror — the `legal_targets` branch has always
        # handled both (see the ``nonland_permanent_you_control`` case), just
        # never whitelisted here until a real card's TARGET row needed it.
        "nonland_permanent_you_control", "nonland_permanent_you_dont_control",
        # "target spell or nonland permanent an opponent controls" (Sink
        # into Stupor) — the ``"spell"``/``nonland_permanent_you_dont_
        # control`` union.
        "spell_or_nonland_permanent_you_dont_control",
        # "target spell or creature" (Unsubstantiate, MEC-43).
        "spell_or_creature",
        # "target spell you don't control" (Hullbreaker Horror) — the
        # controller-scoped mirror of the plain ``"spell"`` kind.
        "spell_you_dont_control",
        # RULE 702.140a's "target **non-Human** creature you own" — mutate's
        # own target line. Note *own*, not control (RULE 108.3): a creature
        # you own but an opponent controls is still a legal mutate host, and
        # the Human exclusion is the reason Humans dodge the mechanic.
        "non_human_creature_you_own",
        # "target artifact or enchantment" (Archdruid's Charm) — the union of
        # the two single-type kinds, a common printed phrasing.
        "artifact_or_enchantment",
        "artifact_or_enchantment_defending_player_controls",
        # "target artifact or creature" (Touch the Spirit Realm, MEC-42).
        "artifact_or_creature",
        # "target artifact or creature **you control**" (Oko, Thief of
        # Crowns' -5, MEC-43 round 4E) — the controller-scoped sibling of
        # the bare union above, same shape `creature_or_planeswalker_you_
        # control` already is for its own pair of types.
        "artifact_or_creature_you_control",
        # "target artifact, creature, or enchantment" (March of
        # Otherworldly Light, MEC-43) — the three-kind union, no
        # planeswalker (unlike `artifact_creature_enchantment_or_
        # planeswalker`, a different printed template).
        "artifact_creature_or_enchantment",
        # "target artifact, enchantment, or nonbasic land" (Boseiju, Who
        # Endures's Channel ability) — `artifact_or_enchantment` widened
        # with `nonbasic_land`, the same three-kind-union idiom
        # `artifact_creature_planeswalker_or_opponent` already uses.
        "artifact_enchantment_or_nonbasic_land",
        # "target opponent or planeswalker" (MEC-11's Enrage cluster —
        # Frilled Deathspitter/Sun-Crowned Hunters-shaped, but a common
        # printed phrasing well beyond just those two) — a player who isn't
        # this ability's own controller, unioned with any planeswalker.
        "opponent_or_planeswalker",
        # "target Aura or Equipment attached to a creature you control"
        # (Halvar, God of Battle) — `attached_equipment_you_control` widened
        # to Auras, and narrowed to hosts you control.
        "attached_aura_or_equipment_you_control",
        # An Equipment you control that's *currently attached* to something
        # (Akiri, Fearless Voyager's "unattach an Equipment from a creature
        # you control") — narrower than a bare "Equipment you control", since
        # an unattached one has nothing to unattach *from*.
        "attached_equipment_you_control",
        # An Equipment you control, attached or not (Nahiri, Heir of the
        # Ancients' +1: "you may attach an Equipment you control to it") —
        # broader than `attached_equipment_you_control` above.
        "equipment_you_control",
        # "Target nonbasic land" (Encroaching Wastes) — any player's, unlike
        # the controller-restricted kinds above.
        "nonbasic_land", "basic_land",
        # "Target legendary permanent" (Minamo, School at Water's Edge,
        # RULE 205.4a) — any player's, supertype-filtered.
        "legendary_permanent",
        # "Target Forest" (Arbor Elf) — any player's, subtype-filtered to
        # one specific basic land type. Only Forest exists so far (the one
        # real card in this codebase needing it); add its WUBRG siblings
        # here the same way once a card needs "target Island"/etc.
        "forest",
        # "target artifact, creature, planeswalker, or opponent" (PAR-2,
        # Price of Betrayal's "Remove up to five counters from target
        # artifact, creature, planeswalker, or opponent.") — RULE 122.5 lets
        # "remove counters" name a player (their poison/energy/experience)
        # right alongside the three permanent types; wider than `any` (which
        # deliberately excludes non-creature artifacts, RULE 115.9c) and
        # wider than `opponent_or_planeswalker` (which excludes artifacts).
        "artifact_creature_planeswalker_or_opponent",
        # "target artifact, creature, enchantment, or planeswalker" (Otawara,
        # Soaring City's Channel ability) — the same four-permanent-type
        # union idiom, no player half, enchantment instead of opponent.
        "artifact_creature_enchantment_or_planeswalker",
        # "target creature or planeswalker that player controls" (Chandra's
        # Incinerator, MEC-45 — "that player" is whichever opponent the
        # firing DAMAGE trigger event named as its recipient, not a fixed
        # "opponent" role) — the trigger-event-scoped sibling of
        # `creature_or_planeswalker_you_control`; only resolvable when
        # `legal_targets` is given the firing ``trigger_event``.
        "creature_or_planeswalker_that_player_controls",
        # "target creature or planeswalker" (Imodane deck batch —
        # Stonesplitter Bolt/Lithomantic Barrage/Torch Breath/Torch the
        # Tower, a hugely common modern removal-spell template) — the
        # two-kind union idiom `artifact_or_enchantment` already uses.
        "creature_or_planeswalker",
        # "a creature or planeswalker you control" (Spark Double's own
        # enter-as-copy candidate pool) — the controller-scoped sibling of
        # the bare union kind just above.
        "creature_or_planeswalker_you_control",
        # "another target battle or opponent" (Invasion of Regatha) — the
        # `opponent_or_planeswalker`-shaped union, just with a battle
        # (RULE 310) instead of a planeswalker.
        "battle_or_opponent",
        # "target creature, planeswalker, or battle" (Volcanic Spite) —
        # the same three-permanent-type union idiom, no player half.
        "creature_planeswalker_or_battle",
        # "enchant Forest you control" (Harold and Bob, First Numens) —
        # `forest` narrowed to the controller's own, the same split
        # `land_you_control` is to a bare "land".
        "forest_you_control",
        # "target creature it's blocking" (Tinder Wall, MEC-40) — narrowed
        # to whichever attacker(s) this ability's own source currently has
        # assigned via `GameObject.blocking`/`additional_blocking`.
        "creature_source_is_blocking",
    }
) | _GRAVEYARD_TARGET_KINDS

#: German noun phrase per `_GRAVEYARD_TYPE_FILTERS` suffix, for `_graveyard_label`.
_GRAVEYARD_TYPE_LABELS: dict[str, str] = {
    "card": "Karte",
    "creature": "Kreaturenkarte",
    "land": "Landkarte",
    "artifact": "Artefaktkarte",
    "enchantment": "Verzauberungskarte",
    "non_aura_enchantment": "Nicht-Aura-Verzauberungskarte",
    "instant_or_sorcery": "Spontanzauber- oder Hexereikarte",
    "permanent": "Karte eines bleibenden Kartentyps",
    "nonland_permanent": "Karte eines nichtländlichen bleibenden Kartentyps",
}
#: German "whose graveyard" phrase per `_GRAVEYARD_SCOPE_PREFIXES` scope.
_GRAVEYARD_SCOPE_LABELS: dict[str, str] = {
    "own": "in deinem Friedhof",
    "any": "in einem Friedhof",
    "opponent": "im Friedhof eines Gegners",
}


def _graveyard_label(kind: str) -> Optional[str]:
    """A `TargetSpec.label()` for a `_GRAVEYARD_TARGET_KINDS` member, or
    ``None`` for any other kind."""
    for prefix, scope in _GRAVEYARD_SCOPE_PREFIXES.items():
        if kind.startswith(prefix + "_"):
            suffix = kind[len(prefix) + 1:]
            type_label = _GRAVEYARD_TYPE_LABELS.get(suffix)
            if type_label is None:
                return None
            return f"{type_label} {_GRAVEYARD_SCOPE_LABELS[scope]}"
    return None


@dataclass(frozen=True)
class TargetSpec:
    """One required target of a targeting effect (RULE 115.1).

    ``kind`` is one of `ALLOWED_TARGET_KINDS`; ``optional`` marks "up to
    ``count``" (RULE 115.1a's "up to one" generalized to "up to N"), which
    never locks a spell (fewer than ``count`` targets, including zero, is a
    legal choice). ``count`` is how many targets this one targeting effect
    wants — ``1`` for an ordinary single target, ``N`` for "N target
    creatures"/"choose N target X" (mandatory, ``optional=False``) or "up to
    N target X" (``optional=True``, 0..N).

    A single targeting effect consuming a flat resolved-targets list this
    way is the common case; when a spell/ability carries 2+ *different*
    targeting effects, each needing its own target, `StackItem.target_groups`
    partitions the list per effect instead (`game/rules_engine.py`'s
    `resolve_top_of_stack`/`_apply_effects_partitioned`) — a triggered
    ability's own target choice gathers one per effect automatically
    (`_continue_trigger_multi_target`), a spell/activated ability's caller
    may supply ``target_groups`` explicitly (the board UI does, since only
    it can say which *optional* requirement was declined), and otherwise
    `partition_targets` derives them from the flat, in-printed-order list.
    ``description`` is a short UI label.
    """

    kind: str = "any"
    optional: bool = False
    count: int = 1
    description: str = ""
    #: For ``kind="spell"`` only — a structured filter on *which* spells are
    #: legal targets (RULE 601.2c/115), e.g. ``{"noncreature": True}``,
    #: ``{"card_types": ["instant", "sorcery"]}``, ``{"mana_value": 2}``, or
    #: any combination — narrows "counter target noncreature spell" /
    #: "target instant or sorcery spell" / "target spell with mana value N"
    #: beyond the bare "target spell". ``single_target: True`` (Misdirection's
    #: "target spell **with a single target**") is checked against the stack
    #: item's own current ``targets`` count instead of the spell's printed
    #: characteristics, since it's a fact about the stack, not the card.
    #: ``None``/``{}`` means unfiltered.
    spell_filter: Optional[dict[str, Any]] = None
    #: A WUBRG colour letter (``"W"``/``"U"``/``"B"``/``"R"``/``"G"``)
    #: narrowing a ``"creature"``/``"permanent"``/``"any"`` target to that
    #: colour (RULE 105) — the old-templating "target blue permanent"/
    #: "target permanent if it's blue" color-hoser shape (Red Elemental
    #: Blast/Pyroblast), a battlefield-object sibling of ``spell_filter``'s
    #: own ``"color"`` key (the ``"spell"`` kind's equivalent — kept as a
    #: separate field since spells and permanents resolve through different
    #: `legal_targets` branches). ``None`` means unfiltered.
    color: Optional[str] = None
    #: An OR of 2+ WUBRG letters (RULE 105) — "target white **or** blue
    #: creature" (Rending Volley-shaped) — ``color``'s multi-letter
    #: sibling; the two are mutually exclusive per spec (the segmenter only
    #: ever emits one or the other), checked together by `_color_ok` below
    #: so every `color`-narrowed `legal_targets` branch gets this for free.
    #: ``None`` means unfiltered.
    colors: Optional[tuple[str, ...]] = None
    #: A mana-value cap on a ``"creature"``/``"permanent"`` target (RULE
    #: 115/601.2c, Abrupt Decay-shaped "target nonland permanent with mana
    #: value 3 or less") — checked at *offer* time (an over-cost permanent
    #: is never a legal target to begin with, not merely a no-op if chosen),
    #: mirroring ``color``'s narrowing. ``None`` means unfiltered.
    max_mana_value: Optional[int] = None
    #: A power/toughness/keyword quality filter on a ``"creature"``/
    #: ``"permanent"`` target (RULE 115/601.2c, "destroy target creature
    #: with power 4 or greater"/"…with flying"-shaped) — checked at offer
    #: time, mirroring ``color``/``max_mana_value``. Keys (all optional,
    #: AND-combined): ``min_power``/``max_power``/``min_toughness``/
    #: ``max_toughness`` (int) and ``keyword`` (a single `combat.has`
    #: keyword string). ``None`` means unfiltered.
    creature_filter: Optional[dict[str, Any]] = None
    #: RULE 115.1a's fixed/"up to N" ``count`` generalizes to N independent
    #: targets, but says nothing about how those N targets relate to each
    #: other — this is the one such cross-target constraint modeled so far
    #: (Run Away Together/Protector of the Wastes-shaped "N target
    #: creatures/permanents controlled by **different players**"): every
    #: chosen target must have a different controller from every other one
    #: chosen for this same requirement. Unlike every other field above
    #: (checked per-candidate, independent of what else was picked), this is
    #: enforced at *offer* time across rounds, not per-candidate — see
    #: `legal_targets`'s docstring and `gameBoardView.js`'s
    #: `expandMultiTargetRequirements`, which excludes an already-picked
    #: round's controller from later rounds' options the same way it
    #: already excludes an already-picked *object* (`excludePicked`).
    #: ``False`` means unrestricted (independent picks, the overwhelming
    #: common case). Only meaningful with ``count >= 2``.
    distinct_controllers: bool = False
    #: RULE 109.5's "**another** target creature" when "another" is relative
    #: to a *different requirement's* pick rather than to the ability's own
    #: source — "target creature you control fights **another** target
    #: creature" (Pit Fight, Ulvenwald Tracker, Domri Rade). The source-
    #: relative reading needs no field at all (`legal_targets`' plain
    #: ``creature`` kind already excludes the source); this one can't be
    #: answered per-candidate, because what it excludes is whatever the
    #: *other* requirement of the same cast ends up choosing. Like
    #: ``distinct_controllers`` it is therefore an **offer-time, across-
    #: rounds** constraint (`gameBoardView.js` drops every already-picked
    #: object from a flagged requirement's pool), with a resolve-time
    #: backstop in the effect itself (`effects.FightEffect` won't let one
    #: creature fight itself when the clause said "another"), since nothing
    #: server-side re-validates a submitted target list.
    distinct_from_others: bool = False
    #: ``count`` read off the board at *announce* time instead of being fixed
    #: at parse time (RULE 601.2c — the number of targets is chosen as the
    #: spell/ability is put on the stack, so it may depend on state that
    #: didn't exist when the card was bound). Two real shapes, both in the
    #: goad pool: "goad up to **X** target creatures your opponents control"
    #: where X is the monstrosity that just happened (Death Kiss), and "**for
    #: each opponent**, goad up to one target creature that player controls"
    #: (4 cards), which is one requirement of "as many as there are
    #: opponents" with `distinct_controllers` doing the "that player" half.
    #: See `TARGET_COUNT_SELECTORS`. ``None`` (the common case) keeps
    #: ``count`` exactly as printed.
    count_selector: Optional[str] = None
    #: A creature-subtype filter on a `_GRAVEYARD_TARGET_KINDS` target
    #: (Morcant's Loyalist's "return **another target Elf** card from your
    #: graveyard to your hand") — narrows the kind's own card-type filter
    #: (e.g. ``graveyard_creature``) by a tribal subtype, lower-cased to
    #: match `_has_subtype`'s own convention. ``None`` means unfiltered.
    #: Only meaningful for a graveyard kind; ignored elsewhere.
    subtype: Optional[str] = None
    #: Best-effort "is this target on the receiving end of something good or
    #: bad" hint — ``"harmful"``/``"beneficial"``/``None`` (no opinion).
    #: Not rules data and never read by the engine itself: stamped by
    #: `spell_target_specs`/`ability_target_specs` from the owning
    #: `GameEffect.target_polarity()` (see `game/effects.py`) purely so
    #: `services/bots.py`'s `GreedyBot` can point a removal spell at an
    #: opponent's permanent and a pump spell at its own — see that method's
    #: docstring for the classification and its documented blind spots.
    polarity: Optional[str] = None
    #: ENG-30: RULE 601.2c's third target-count shape — a genuine *range*,
    #: "N or M target X" (at least ``count``, at most ``count_max`` — unlike
    #: ``optional``'s "up to N" the minimum here is never 0, so declining
    #: below ``count`` isn't legal and the requirement still locks a cast
    #: when fewer than ``count`` legal targets exist). ``None`` (the default)
    #: means the ordinary fixed/``optional`` shapes above apply unchanged;
    #: only meaningful when it's a genuine value greater than ``count``.
    #: Read by `effective_count` (the resolve-time slicing cap every
    #: `game/effects.py` consumer uses instead of ``count`` directly),
    #: `expand_counts` (which rounds are mandatory vs. declinable) and
    #: `requirements_with_targets`/`gameBoardView.js` (how many rounds to
    #: offer, and where the "stop early" boundary sits).
    count_max: Optional[int] = None

    @property
    def effective_count(self) -> int:
        """The largest number of targets this spec could ever resolve to —
        ``count_max`` when set (a genuine range), else the plain ``count``.
        This, not ``count``, is the right cap for slicing a shared
        ``targets`` list at resolution time (`effects._chosen_targets` and
        its callers): for a range spec ``count`` is the RULE 601.2c
        *minimum*, and a shorter cap would silently drop a legally chosen
        target above the minimum."""
        return self.count_max if self.count_max is not None else self.count

    def label(self) -> str:
        return self.description or _graveyard_label(self.kind) or {
            "any": "beliebiges Ziel",
            "creature": "Kreatur",
            "permanent": "bleibende Karte",
            "artifact": "Artefakt",
            "enchantment": "Verzauberung",
            "land": "Land",
            "player": "Spieler",
            "player_dealt_combat_damage_by_source":
                "Spieler, dem diese Karte in diesem Zug Kampfschaden zugefügt hat",
            "spell": "Zauberspruch",
            "ability": "aktivierte oder ausgelöste Fähigkeit",
            "spell_or_ability": "Zauberspruch oder Fähigkeit",
            "creature_you_control": "Kreatur unter deiner Kontrolle",
            "other_creature_you_control": "andere Kreatur unter deiner Kontrolle",
            "creature_or_enchantment_you_control": "Kreatur oder Verzauberung unter deiner Kontrolle",
            "non_human_creature_you_own": "Nicht-Mensch-Kreatur, die du besitzt",
            "creature_you_dont_control": "Kreatur, die du nicht kontrollierst",
            "artifact_you_dont_control": "Artefakt, das du nicht kontrollierst",
            "artifact_or_enchantment": "Artefakt oder Verzauberung",
            "artifact_or_creature": "Artefakt oder Kreatur",
            "artifact_or_creature_you_control": "Artefakt oder Kreatur unter deiner Kontrolle",
            "spell_or_creature": "Zauberspruch oder Kreatur",
            "artifact_creature_or_enchantment": "Artefakt, Kreatur oder Verzauberung",
            "artifact_enchantment_or_nonbasic_land":
                "Artefakt, Verzauberung oder nichtgrundlegendes Land",
            "opponent": "Gegner",
            "opponent_or_planeswalker": "Gegner oder Planeswalker",
            "artifact_creature_planeswalker_or_opponent":
                "Artefakt, Kreatur, Planeswalker oder Gegner",
            "artifact_creature_enchantment_or_planeswalker":
                "Artefakt, Kreatur, Verzauberung oder Planeswalker",
            "creature_or_planeswalker": "Kreatur oder Planeswalker",
            "creature_or_planeswalker_you_control":
                "Kreatur oder Planeswalker unter deiner Kontrolle",
            "creature_or_planeswalker_that_player_controls":
                "Kreatur oder Planeswalker unter der Kontrolle dieses Spielers",
            "battle_or_opponent": "Schlacht oder Gegner",
            "creature_planeswalker_or_battle": "Kreatur, Planeswalker oder Schlacht",
            "attached_aura_or_equipment_you_control":
                "Aura oder Ausrüstung an einer Kreatur unter deiner Kontrolle",
            "land_you_control": "Land unter deiner Kontrolle",
            "land_you_dont_control": "Land, das du nicht kontrollierst",
            "attached_equipment_you_control": "befestigte Ausrüstung unter deiner Kontrolle",
            "equipment_you_control": "Ausrüstung unter deiner Kontrolle",
            "nonbasic_land": "nichtgrundlegendes Land",
            "legendary_permanent": "legendäre bleibende Karte",
            "forest_you_control": "Wald unter deiner Kontrolle",
            "creature_source_is_blocking": "Kreatur, die dies blockiert",
        }.get(self.kind, self.kind)


def spell_target_specs(obj: GameObject) -> list[TargetSpec]:
    """The target requirements a spell announces, gathered from its effects.

    Most permanent spells (creature/artifact/…) have no `spell_effects` and so
    no requirements; an instant/sorcery contributes one `TargetSpec` per
    targeting effect it carries (``DealDamageEffect`` → "any", ``DestroyEffect``
    → "permanent", ``CounterSpellEffect`` → "spell"). Non-targeting effects
    (draw/gain-life/search/…) carry ``target_spec = None`` and add nothing.

    An Aura is the other permanent-spell exception (RULE 303.4a): it must
    target what it will enchant *as it's cast*, so an "enchant" attachment
    kind synthesizes a "permanent" requirement here — `legal_targets` then
    narrows it by the Aura's own "enchant" quality (creature/land/…).
    """
    specs: list[TargetSpec] = []
    for effect in getattr(obj, "spell_effects", []) or []:
        # `target_specs` (not ``target_spec``) so an effect that genuinely
        # needs two differently-typed targets in one clause announces both
        # — see `game/effects.py`'s `GameEffect.extra_target_specs`.
        polarity = effect.target_polarity()
        specs.extend(_with_polarity(spec, polarity) for spec in (getattr(effect, "target_specs", None) or []))
    if not specs and "enchant" in (getattr(obj, "parametric_keywords", None) or {}):
        specs.append(
            TargetSpec(
                kind="permanent",
                description="zu verzauberndes Ziel",
                polarity=_aura_enchant_polarity(obj),
            )
        )
    return specs


def _with_polarity(spec: TargetSpec, polarity: Optional[str]) -> TargetSpec:
    """``spec``, tagged with ``polarity`` unless it already carries its own
    (none currently do — every `TargetSpec` is built without one and picks
    it up here from its owning effect — but a future one that sets it
    explicitly should win)."""
    if polarity is None or spec.polarity is not None:
        return spec
    return replace(spec, polarity=polarity)


def _aura_enchant_polarity(obj: GameObject) -> Optional[str]:
    """Best-effort polarity for an Aura's synthesized "enchant" target (the
    branch above this fires for an Aura whose whole ability is a static —
    Rancor, Pacifism — so there's no `EffectSpec`/`GameEffect` clause to ask
    `target_polarity()`). Reads the Aura's own bound layer-7 P/T static on
    ``attached_permanent`` (bound at load time regardless of zone, so this
    works before the Aura is even cast): a positive P/T grant is a buff
    (beneficial to whatever it's attached to), a negative one a curse
    (harmful). An Aura with no P/T clause at all (Pacifism-shaped
    keyword-only curses) reads ``None`` — which leaves `GreedyBot`'s
    existing "prefer an opponent's permanent" default in place, and that
    default happens to be right for exactly this case.
    """
    for effect in getattr(obj, "static_effects", None) or []:
        if getattr(effect, "affects", None) != "attached_permanent":
            continue
        if effect.layer not in ("pt_set", "pt_mod", "pt_cda"):
            continue
        power = effect.params.get("power", 0) or 0
        toughness = effect.params.get("toughness", 0) or 0
        if power < 0 or toughness < 0:
            return "harmful"
        if power > 0 or toughness > 0:
            return "beneficial"
    return None


def _is_human(obj: "GameObject") -> bool:
    """RULE 205.3m: whether ``obj`` currently has the Human creature type —
    layer-4 aware, via a function-scoped import of `game/continuous.py`
    (which imports `game/effects.py`, which imports this module, so a
    module-level import would cycle)."""
    from . import continuous

    return continuous.has_subtype(obj, "Human")


def _color_ok(spec: "TargetSpec", obj_colors: Any) -> bool:
    """``TargetSpec.color``/``colors`` narrowing, combined — unfiltered if
    neither is set, single-letter membership if ``color`` is, OR-membership
    if ``colors`` is (the two are mutually exclusive per spec)."""
    if spec.color and spec.color not in obj_colors:
        return False
    if spec.colors and not (set(spec.colors) & set(obj_colors)):
        return False
    return True


def _targetable_by(obj: GameObject, source: Optional[GameObject]) -> bool:
    """Whether ``obj`` is a legal target/attachment host for ``source`` under
    protection and hexproof (RULE 702.16b/e: protection prevents being
    targeted by, or enchanted/equipped/fortified by, a source of the stated
    quality; RULE 702.11b: hexproof prevents being targeted by a spell/
    ability an *opponent* controls — unlike protection, a controller's own
    spells/abilities can still target their own hexproof permanent)."""
    if source is None:
        return True
    if combat.is_protected_from(obj, source):
        return False
    if combat.has_hexproof(obj) and obj.controller_id != source.controller_id:
        return False
    # RULE 702.18b: shroud can't be targeted by *any* spell or ability,
    # its own controller's included — no opponent-scoping, unlike hexproof
    # just above (PAR-22).
    if combat.has_shroud(obj):
        return False
    # "Creatures you control can't be the targets of blue or black spells
    # this turn." (Autumn's Veil, MEC-41) — narrower than hexproof (spells
    # only, never abilities) and unlike protection/hexproof above, not
    # scoped to an *opponent's* source (the printed text has no "your
    # opponents control" qualifier). No activated/triggered ability in this
    # engine has its own source's ``zone`` be anything but the permanent it
    # lives on (almost always the battlefield), so "not a battlefield
    # permanent" is this engine's proxy for "is a spell being cast" — the
    # same simplification every X-cost-target gap in this file already
    # accepts rather than threading a genuine ``is_spell`` flag through
    # every one of `legal_targets`' many call sites.
    restricted_colors = getattr(obj, "temp_cant_be_target_of_spell_colors", None)
    if restricted_colors and source.zone != Zone.BATTLEFIELD:
        if set(getattr(source, "colors", None) or set()) & restricted_colors:
            return False
    return True


def _creature_matches_filter(
    obj: GameObject,
    filt: dict[str, Any],
    reference: Optional[GameObject] = None,
    state: Optional[GameState] = None,
) -> bool:
    """Whether ``obj`` satisfies a `TargetSpec.creature_filter` (see its
    docstring for the key vocabulary).

    Delegates to `combat.matches_object_filter`, which owns the same key
    vocabulary for RULE 509.1b's qualified blocking restrictions ("can't be
    blocked by creatures with power 2 or less") — one predicate rather than
    two that can drift. That superset also understands subtype/colour/
    card-type/relative-power keys this field's own docstring doesn't
    advertise. ``reference``/``state`` are the comparison anchors the
    relative keys need (``power_vs_reference`` — Mentor's "with lesser
    power", PAR-24 — and ``power_lt_count_selector``); passed through from
    the ``creature`` branch, ``None`` elsewhere (no `TargetSpec` outside
    that branch sets a relative key).
    """
    return combat.matches_object_filter(obj, filt, reference=reference, state=state)


def _spell_matches_filter(obj: GameObject, spell_filter: dict[str, Any]) -> bool:
    """Whether a stack spell's underlying ``obj`` satisfies a "spell" target's
    ``spell_filter`` (RULE 601.2c/115) — see `TargetSpec.spell_filter`.

    ``card_types`` is an *or* over the listed words ("instant or sorcery"
    matches either); ``noncreature``/``card_types``/``mana_value`` compose
    with each other (all present conditions must hold). Reads the object's
    *printed* card, mirroring how a spell's other characteristics are looked
    up before it resolves (no layer-engine pass runs on the stack).
    """
    if spell_filter.get("noncreature") and obj.is_creature:
        return False
    color = spell_filter.get("color")
    if color and color not in obj.colors:
        return False
    card_types = spell_filter.get("card_types")
    if card_types:
        type_checks = {
            "creature": obj.is_creature,
            "instant": bool(obj.card.is_instant),
            "sorcery": bool(obj.card.is_sorcery),
            "artifact": bool(obj.card.is_artifact),
            "enchantment": bool(obj.card.is_enchantment),
            "planeswalker": obj.is_planeswalker,
            # "counter target creature or battle spell" (Assimilate Essence)
            "battle": bool(obj.card.is_battle),
        }
        if not any(type_checks.get(t, False) for t in card_types):
            return False
    mana_value = spell_filter.get("mana_value")
    if mana_value is not None and obj.card.converted_mana_cost != mana_value:
        return False
    return True


def legal_targets(
    state: GameState,
    controller_id: str,
    spec: TargetSpec,
    source: Optional[GameObject] = None,
    trigger_event: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """The currently legal targets for ``spec`` as JSON-able descriptors.

    Players are returned as ``{"player_id", "name"}``; objects as
    ``{"instance_id", "name"}``. Excludes ``source`` itself so a spell can't
    target itself where that's illegal (RULE 115.6 for the common cases here),
    and excludes any object protected from ``source`` (RULE 702.16b: can't be
    the target of, or be enchanted/equipped/fortified by, a source of the
    protected quality) or hexproof against it (RULE 702.11b: can't be
    targeted by an opponent's spell/ability) — the offer-time half, matching
    how a locked action
    already keeps a spell with no legal targets from being cast (601.2c).
    Determinism/serializability matters: these descriptors flow to the UI and
    back through `game_session._resolve_targets`.

    ``trigger_event`` is the `GameEvent` payload that fired the *triggered
    ability* being targeted, when there is one — needed only by
    ``kind="creature_or_planeswalker_that_player_controls"`` (MEC-45), which
    reads whichever player the event names as its recipient rather than a
    fixed "you"/"opponent" role; every other kind ignores it, so a caller
    with no event in hand (an ordinary spell/activated-ability cast) simply
    omits it.
    """
    kind = spec.kind
    # "…with mana value X or less." as a genuine RULE 115 target bound
    # (March of Otherworldly Light, MEC-43) — unlike `_substitute_x`'s
    # resolve-time-only substitution (a search/mass-effect criteria dict,
    # never a `TargetSpec`), a real target has to be gathered/offered
    # *before* the spell resolves, so the sentinel must resolve here, off
    # `GameObject.x_paid` — which `GameEngine._cast_current_face` stamps
    # early (before this target-offer step runs) precisely so this can
    # read it, not just at the usual post-resolution point `cast_spell`
    # stamps it for real.
    if spec.max_mana_value in ("x", "-x"):
        x_paid = int(getattr(source, "x_paid", 0) or 0)
        spec = replace(spec, max_mana_value=x_paid if spec.max_mana_value == "x" else -x_paid)
    if kind == "permanent" and source is not None:
        attachment_kind = None
        if hasattr(source, "parametric_keywords"):
            keywords = source.parametric_keywords or {}
            for name in ("equip", "fortify", "reconfigure", "enchant"):
                if name in keywords:
                    attachment_kind = name
                    break
        if attachment_kind == "equip":
            # RULE 702.6a: "Attach this permanent to target creature you
            # control." Control is the *activating player's* — this is an
            # ability of the Equipment, whose own controller need not be the
            # equipped creature's controller (RULE 301.5d) — not the
            # Equipment's own, so this checks `controller_id`, not `source`.
            return [
                {"instance_id": o.instance_id, "name": o.name}
                for o in state.permanents()
                if o.is_creature
                and o.controller_id == controller_id
                and o is not source
                and _targetable_by(o, source)
            ]
        if attachment_kind == "reconfigure":
            # RULE 702.151a: "Attach this permanent to another target
            # creature you control."
            return [
                {"instance_id": o.instance_id, "name": o.name}
                for o in state.permanents()
                if o.is_creature
                and o.controller_id == controller_id
                and o is not source
                and _targetable_by(o, source)
            ]
        if attachment_kind == "fortify":
            # RULE 702.67a: "Attach this Fortification to target land you
            # control."
            return [
                {"instance_id": o.instance_id, "name": o.name}
                for o in state.permanents()
                if o.is_land
                and o.controller_id == controller_id
                and o is not source
                and _targetable_by(o, source)
            ]
        if attachment_kind == "enchant":
            quality = ((source.parametric_keywords or {}).get("enchant") or {}).get("quality", "")
            quality = str(quality).strip().lower()
            if quality.endswith("card in a graveyard"):
                # RULE 303.4f (MEC-34): "Enchant creature card in a
                # graveyard" (Animate Dead-shaped reanimator Auras) — the
                # target is a graveyard *card*, not a battlefield permanent,
                # so it's drawn from every player's graveyard instead and
                # skips `_targetable_by`'s protection/hexproof checks
                # entirely (those are battlefield-only qualities a
                # graveyard card never has). ``type_word`` is whatever
                # precedes "card in a graveyard" ("creature" for every
                # printed card today; bare "card in a graveyard" — no type
                # word — matches anything).
                type_word = quality[: -len("card in a graveyard")].strip()
                results = []
                for player in state.players:
                    for o in player.graveyard:
                        if type_word == "creature" and not o.is_creature:
                            continue
                        results.append({"instance_id": o.instance_id, "name": o.name})
                return results
            if not quality or quality in {"permanent", "anything"}:
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.permanents()
                    if o is not source and _targetable_by(o, source)
                ]
            if " or " in quality:
                # "Enchant creature or Vehicle" (Swift Reconfiguration,
                # MEC-43 round 4E) — RULE 702.5's compound quality: the
                # union of each word's own predicate. Every real printed
                # card pairs two simple type/subtype words this way, so a
                # plain split is safe; an unrecognized word is just
                # dropped (fails closed toward fewer legal targets, never
                # a crash) rather than widened to "anything".
                words = [w.strip() for w in quality.split(" or ") if w.strip()]
                predicates = [
                    _ENCHANT_QUALITY_PREDICATES[w] for w in words
                    if w in _ENCHANT_QUALITY_PREDICATES
                ]
                if predicates:
                    return [
                        {"instance_id": o.instance_id, "name": o.name}
                        for o in state.permanents()
                        if any(p(o) for p in predicates)
                        and o is not source and _targetable_by(o, source)
                    ]
            if quality == "creature":
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.permanents()
                    if o.is_creature and o is not source and _targetable_by(o, source)
                ]
            if quality == "artifact":
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.permanents()
                    if o.card.is_artifact and o is not source and _targetable_by(o, source)
                ]
            if quality == "enchantment":
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.permanents()
                    if o.card.is_enchantment and o is not source and _targetable_by(o, source)
                ]
            if quality == "land":
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.permanents()
                    if o.is_land and o is not source and _targetable_by(o, source)
                ]
            if quality == "planeswalker":
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.permanents()
                    if o.is_planeswalker and o is not source and _targetable_by(o, source)
                ]
    if kind == "player":
        return [
            {"player_id": p.id, "name": p.name}
            for p in state.living_players()
        ]
    if kind == "player_dealt_combat_damage_by_source":
        # "target player who was dealt combat damage by ~ this turn" (Hope of
        # Ghirapur) — a *history*-filtered player target (RULE 115/120.3),
        # answered from `GameState.combat_damage_to_players_this_turn` rather
        # than any live board state: by the time this ability is activated
        # the damage step is long over. Fails closed to no legal targets when
        # the source hasn't connected this turn, which is exactly right —
        # RULE 601.2c then makes the ability unactivatable.
        hit = state.combat_damage_to_players_this_turn.get(
            getattr(source, "instance_id", None), set()
        )
        return [
            {"player_id": p.id, "name": p.name}
            for p in state.living_players()
            if p.id in hit
        ]
    if kind == "any":
        # RULE 115.4: "any target" is a creature, player, planeswalker, or
        # battle — not just creature/player (MEC-43, Drain Life's own
        # "or the planeswalker's loyalty" rider text has no legal
        # planeswalker target to actually apply to without this). Battles
        # and planeswalkers carry no printed colour identity worth gating
        # on the same ``_color_ok`` a coloured-source restriction checks
        # for creatures (no real card restricts "any target" by colour
        # *and* wants a planeswalker/battle to still qualify), so they skip
        # that filter rather than being excluded by it.
        objs = [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_creature and o is not source and _targetable_by(o, source)
            and _color_ok(spec, o.colors)
        ]
        other_permanents = [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.is_planeswalker or o.is_battle) and not o.is_creature
            and o is not source and _targetable_by(o, source)
        ]
        players = [{"player_id": p.id, "name": p.name} for p in state.living_players()]
        return objs + other_permanents + (players if not (spec.color or spec.colors) else [])
    if kind in ("creature", "permanent", "creature_including_self"):
        # RULE 702.165a Backup — "put N +1/+1 counters on target creature"
        # explicitly *may* target the source itself (the common line: it
        # enters alone). `"creature_including_self"` is the plain `creature`
        # branch without the RULE 115.6-style self-exclusion below (PAR-26).
        allow_self = kind == "creature_including_self"
        want_creature = kind != "permanent"
        return [
            # ``controller_id`` is only ever consumed client-side when
            # `spec.distinct_controllers` is set (`gameBoardView.js`'s
            # per-round exclusion) — harmless to always include otherwise.
            {"instance_id": o.instance_id, "name": o.name, "controller_id": o.controller_id}
            for o in state.permanents()
            if (not want_creature or o.is_creature)
            and (allow_self or o is not source)
            and _targetable_by(o, source)
            and _color_ok(spec, o.colors)
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
            and (
                not spec.creature_filter
                or _creature_matches_filter(o, spec.creature_filter, source, state)
            )
        ]
    if kind == "permanent_you_control":
        # RULE 115: "target permanent you own/control." (Reality Scramble-
        # shaped) — the controller-scoped mirror of ``permanent_you_dont_
        # control`` just below.
        return [
            {"instance_id": o.instance_id, "name": o.name, "controller_id": o.controller_id}
            for o in state.permanents()
            if o.controller_id == controller_id
            and o is not source
            and _targetable_by(o, source)
            and _color_ok(spec, o.colors)
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
        ]
    if kind == "incubator_token_you_control":
        # "{T}: Transform target Incubator token you control." (Progenitor
        # Exarch) — a token named "Incubator" (RULE 111.1) this ability's
        # controller controls; the Incubate family's own two-state token.
        return [
            {"instance_id": o.instance_id, "name": o.name, "controller_id": o.controller_id}
            for o in state.permanents()
            if o.controller_id == controller_id
            and getattr(o, "is_token", False)
            and (o.name or "") == "Incubator"
            and o is not source
            and _targetable_by(o, source)
        ]
    if kind == "permanent_you_dont_control":
        # RULE 115: "target permanent an opponent controls." (Assassin's
        # Trophy/Geomancer's Gambit-shaped) — the controller-scoped sibling
        # of the bare ``permanent`` branch above (any permanent type,
        # including lands, unlike ``nonland_permanent_you_dont_control``
        # just below), narrowed to whoever isn't this ability's controller.
        return [
            {"instance_id": o.instance_id, "name": o.name, "controller_id": o.controller_id}
            for o in state.permanents()
            if o.controller_id not in (None, controller_id)
            and o is not source
            and _targetable_by(o, source)
            and _color_ok(spec, o.colors)
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
        ]
    if kind == "permanent_you_neither_own_nor_control":
        # RULE 115 (PAR-30 — Conjured Currency's "target permanent you
        # **neither own nor control**"): excludes both this ability's
        # controller's own cards (even one they've lost control of, unlike
        # ``permanent_you_dont_control``'s controller-only exclusion) and
        # any permanent someone else owns but *this* controller currently
        # controls (a control-effect target that already changed hands) —
        # the double negative RULE 108.4/701.10 exchange cards specifically
        # want so the target can't be swapped right back to where it came
        # from another way.
        return [
            {"instance_id": o.instance_id, "name": o.name, "controller_id": o.controller_id}
            for o in state.permanents()
            if o.owner_id != controller_id
            and o.controller_id != controller_id
            and o is not source
            and _targetable_by(o, source)
            and _color_ok(spec, o.colors)
        ]
    if kind == "nonland_permanent":
        # RULE 115: every permanent that isn't a land (Geistwave/Beast
        # Within-adjacent). Mirrors the "permanent" branch above, minus lands.
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.is_creature or o.is_planeswalker
                or o.card.is_artifact or o.card.is_enchantment)
            and o is not source
            and _targetable_by(o, source)
            and _color_ok(spec, o.colors)
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
        ]
    if kind in ("nonland_permanent_you_control", "nonland_permanent_you_dont_control"):
        # RULE 115 controller-scoped nonland-permanent bounce: Cyclonic Rift
        # ("… you don't control"), Alchemist's Retrieval / Chain of Vapor
        # ("… you control"). The `nonland_permanent` branch above, narrowed
        # by whose permanent it is.
        wants_own = kind == "nonland_permanent_you_control"
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.is_creature or o.is_planeswalker
                or o.card.is_artifact or o.card.is_enchantment)
            and ((o.controller_id == controller_id) == wants_own)
            and o is not source
            and _targetable_by(o, source)
            and _color_ok(spec, o.colors)
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
        ]
    if kind == "creature_source_is_blocking":
        # "{R}, Sacrifice ~: It deals 2 damage to target creature it's
        # blocking." (Tinder Wall, MEC-40) — a genuine RULE 115 target (RULE
        # 115.1a still applies, so a hexproof/protected attacker can't be
        # named even though it's the only creature this Wall is currently
        # blocking), narrowed to `source.blocking`/`source.additional_
        # blocking` (RULE 509.1b's multi-block permission's own ids) instead
        # of the whole battlefield. `_targetable_by` still runs — this is a
        # target restriction, not a bypass of one.
        attacker_ids = {i for i in ([source.blocking] if source.blocking else [])}
        attacker_ids |= set(getattr(source, "additional_blocking", []) or [])
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.instance_id in attacker_ids
            and _targetable_by(o, source)
        ]
    if kind == "spell_or_nonland_permanent_you_dont_control":
        # "Return target spell or nonland permanent an opponent controls to
        # its owner's hand." (Sink into Stupor) — the union of the plain
        # ``"spell"`` branch's own options (any spell on the stack; nothing
        # printed here restricts by spell type/colour/etc, unlike
        # Misdirection's own ``single_target`` narrowing) and
        # ``nonland_permanent_you_dont_control``'s options, side by side —
        # the same two-branches-concatenated idiom ``spell_or_ability``
        # uses for its own spell+ability union.
        spells = [
            {"instance_id": item.obj.instance_id, "name": item.description or item.obj.name}
            for item in state.stack
            if item.kind == "spell" and item.obj is not None and item.obj is not source
        ]
        permanents = [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.is_creature or o.is_planeswalker
                or o.card.is_artifact or o.card.is_enchantment)
            and o.controller_id not in (None, controller_id)
            and o is not source
            and _targetable_by(o, source)
        ]
        return spells + permanents
    if kind == "spell_or_creature":
        # "Return target spell or creature to its owner's hand."
        # (Unsubstantiate, MEC-43) — the same two-branches-concatenated
        # idiom as ``spell_or_nonland_permanent_you_dont_control`` just
        # above, narrowed to creatures and with no controller restriction.
        spells = [
            {"instance_id": item.obj.instance_id, "name": item.description or item.obj.name}
            for item in state.stack
            if item.kind == "spell" and item.obj is not None and item.obj is not source
        ]
        creatures = [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_creature and o is not source and _targetable_by(o, source)
        ]
        return spells + creatures
    if kind == "creature_you_dont_control":
        # RULE 115: the mirror image of `creature_you_control` — an
        # opponent's creature (or, strictly, any creature this ability's
        # controller doesn't control). ``creature_filter`` (Oko, Thief of
        # Crowns' -5, MEC-43 round 4E — "…with power 3 or less") narrows it
        # the same way the `creature_you_control` family below already
        # honours; every existing caller that never sets it is unaffected.
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_creature
            and o.controller_id != controller_id
            and _targetable_by(o, source)
            and (not spec.creature_filter or _creature_matches_filter(o, spec.creature_filter))
        ]
    if kind == "artifact_you_dont_control":
        # RULE 115: the artifact-typed mirror of `creature_you_dont_control`
        # (Vandalblast's base, non-Overload mode — RULE 702.96 Overload
        # itself is a documented non-goal, same as Winds of Abandon/Damn/
        # Cyclonic Rift).
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.card.is_artifact
            and o.controller_id != controller_id
            and _targetable_by(o, source)
        ]
    if kind == "attached_aura_or_equipment_you_control":
        # "target Aura or Equipment attached to a creature you control"
        # (Halvar) — both the attachment *and* its host must be yours, which
        # is what makes this narrower than a bare "Equipment you control".
        hosts = {
            o.instance_id
            for o in state.permanents()
            if o.is_creature and o.controller_id == controller_id
        }
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.controller_id == controller_id
            and o.attached_to in hosts
            and ("aura" in o.card.type_line.lower() or "equipment" in o.card.type_line.lower())
            and _targetable_by(o, source)
        ]
    if kind == "land_you_dont_control":
        # "target land an opponent controls" (PAR-29) — the controller-
        # scoped mirror of `land_you_control` just below, same "you don't
        # control" shape `nonland_permanent_you_dont_control` already has.
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_land
            and o.controller_id != controller_id
            and _targetable_by(o, source)
        ]
    if kind in (
        "creature_you_control", "land_you_control", "other_creature_you_control"
    ):
        # RULE 115/603.3c controller-restricted pick — and the same shape for
        # a non-"target" resolve-time choice among the controller's own
        # permanents (a bounce-land's "return a land you control…").
        #
        # ``other_creature_you_control`` is the RULE 109.5 "*another* target
        # creature you control" narrowing (Giver of Runes), which excludes
        # the ability's own source; the two unprefixed kinds deliberately do
        # *not* — "target creature you control" includes the source itself
        # (Mother of Runes protecting herself is the card's whole point).
        wants_land = kind == "land_you_control"
        exclude_source = kind.startswith("other_")
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.is_land if wants_land else o.is_creature)
            and o.controller_id == controller_id
            and not (exclude_source and o is source)
            and _targetable_by(o, source)
            and (not spec.creature_filter or _creature_matches_filter(o, spec.creature_filter))
            # "return target `<c1>` or `<c2>` creature you control …" (Escape
            # Routes) — the same `_color_ok` narrowing every other creature
            # branch above applies; a no-op when ``colors``/``color`` unset.
            and _color_ok(spec, o.colors)
        ]
    if kind == "creature_or_enchantment_you_control":
        # "put a +1/+1 counter on target creature or enchantment you
        # control." (MEC-43 round 4D, Heliod, Sun-Crowned) — the two-type
        # union sibling of `creature_you_control`/`artifact_or_enchantment`,
        # same "you control" scoping, source included (no printed "another").
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.is_creature or o.card.is_enchantment)
            and o.controller_id == controller_id
            and _targetable_by(o, source)
        ]
    if kind == "non_human_creature_you_own":
        # RULE 702.140a: mutate's own target. Keyed to *ownership* (RULE
        # 108.3), not control, and excluding Humans by subtype (RULE 205.3m).
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_creature
            and o.owner_id == controller_id
            and not _is_human(o)
            and _targetable_by(o, source)
        ]
    if kind in ("opponent", "opponent_or_planeswalker"):
        # "target opponent" — a living player besides this ability's own
        # controller. "target opponent or planeswalker" unions it with the
        # planeswalker half, the same `artifact_or_enchantment`-style
        # two-kind union.
        players = [
            {"player_id": p.id, "name": p.name}
            for p in state.living_players()
            if p.id != controller_id
        ]
        if kind == "opponent":
            return players
        planeswalkers = [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_planeswalker and o is not source and _targetable_by(o, source)
        ]
        return players + planeswalkers
    if kind == "artifact_creature_planeswalker_or_opponent":
        # "target artifact, creature, planeswalker, or opponent" (PAR-2,
        # Price of Betrayal) — three permanent types unioned with a player,
        # the same `artifact_or_enchantment`/`opponent_or_planeswalker`
        # two-kind-union idiom, just wider.
        permanents = [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.card.is_artifact or o.is_creature or o.is_planeswalker)
            and o is not source
            and _targetable_by(o, source)
        ]
        players = [
            {"player_id": p.id, "name": p.name}
            for p in state.living_players()
            if p.id != controller_id
        ]
        return permanents + players
    if kind == "artifact_creature_enchantment_or_planeswalker":
        # "target artifact, creature, enchantment, or planeswalker"
        # (Otawara, Soaring City's Channel ability) — the same four-
        # permanent-type union idiom as `artifact_creature_planeswalker_
        # or_opponent`, minus the player half and with enchantment added.
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.card.is_artifact or o.is_creature or o.card.is_enchantment or o.is_planeswalker)
            and o is not source
            and _targetable_by(o, source)
        ]
    if kind == "artifact_or_enchantment":
        # "Exile target artifact or enchantment." (Archdruid's Charm's third
        # mode) — the union of the two single-type kinds below, which is a
        # common enough printed phrasing to deserve its own kind rather than
        # two effects with two prompts.
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.card.is_artifact or o.card.is_enchantment)
            and o is not source
            and _targetable_by(o, source)
        ]
    if kind == "artifact_or_enchantment_defending_player_controls":
        # "…destroy target artifact or enchantment defending player
        # controls." (Kogla, the Titan Ape, MEC-43) — "defending player" is
        # the firing `ATTACKS` event's own ``defending_player_id`` (the
        # already-resolved RULE 508.1a defender), the same trigger-event-
        # scoped idiom `creature_or_planeswalker_that_player_controls` uses
        # for a DAMAGE event's recipient; no event in hand means no legal
        # player to scope to, so this fails closed to an empty list.
        event = trigger_event or {}
        defending_player_id = event.get("defending_player_id")
        if defending_player_id is None:
            return []
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.card.is_artifact or o.card.is_enchantment)
            and o.controller_id == defending_player_id
            and o is not source
            and _targetable_by(o, source)
        ]
    if kind == "artifact_or_creature":
        # "Exile target artifact or creature." (Touch the Spirit Realm,
        # MEC-42) — the same union idiom as ``artifact_or_enchantment``
        # just above, just the other pairing.
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.card.is_artifact or o.is_creature)
            and o is not source
            and _targetable_by(o, source)
        ]
    if kind == "artifact_or_creature_you_control":
        # "Exchange control of target artifact or creature you control…"
        # (Oko, Thief of Crowns' -5, MEC-43 round 4E) — the controller-
        # scoped sibling of the bare union just above.
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.card.is_artifact or o.is_creature)
            and o.controller_id == controller_id
            and o is not source
            and _targetable_by(o, source)
        ]
    if kind == "artifact_creature_or_enchantment":
        # "Exile target artifact, creature, or enchantment with mana
        # value X or less." (March of Otherworldly Light, MEC-43) —
        # the three-kind union, honouring ``spec.max_mana_value`` like
        # the plain ``permanent``/``permanent_you_control`` kinds do.
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.card.is_artifact or o.is_creature or o.card.is_enchantment)
            and o is not source
            and _targetable_by(o, source)
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
        ]
    if kind == "artifact_enchantment_or_nonbasic_land":
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (
                o.card.is_artifact
                or o.card.is_enchantment
                or (o.is_land and "basic" not in o.card.type_line.lower())
            )
            and o is not source
            and _targetable_by(o, source)
        ]
    if kind == "battle_or_opponent":
        battles = [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_battle and o is not source and _targetable_by(o, source)
        ]
        players = [
            {"player_id": p.id, "name": p.name}
            for p in state.living_players()
            if p.id != controller_id
        ]
        return battles + players
    if kind == "creature_planeswalker_or_battle":
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.is_creature or o.is_planeswalker or o.is_battle)
            and o is not source
            and _targetable_by(o, source)
        ]
    if kind == "creature_or_planeswalker":
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.is_creature or o.is_planeswalker)
            and o is not source
            and _targetable_by(o, source)
        ]
    if kind == "creature_or_planeswalker_that_player_controls":
        # "target creature or planeswalker **that player** controls"
        # (Chandra's Incinerator, MEC-45) — "that player" is whoever the
        # firing DAMAGE trigger event named as its recipient
        # (``target_id``, only meaningful when ``is_player`` is set); no
        # event in hand (or a non-player recipient) means no legal player
        # to scope to, so this fails closed to an empty list rather than
        # guessing a fixed role.
        event = trigger_event or {}
        target_player_id = event.get("target_id") if event.get("is_player") else None
        if target_player_id is None:
            return []
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.is_creature or o.is_planeswalker)
            and o.controller_id == target_player_id
            and o is not source
            and _targetable_by(o, source)
        ]
    if kind == "creature_or_planeswalker_you_control":
        # "…a copy of a creature or planeswalker **you control**." (Spark
        # Double) — the controller-scoped sibling of the bare kind above;
        # not a RULE 115 "target" (RULE 614.12's "any" phrasing), but this
        # engine's enter-as-copy choice reuses the same candidate-pool
        # machinery regardless.
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.is_creature or o.is_planeswalker)
            and o.controller_id == controller_id
            and o is not source
        ]
    if kind in ("artifact", "enchantment", "land", "noncreature_artifact"):
        # RULE 115 single-type permanent target (also the enter-as-copy
        # candidate pool for Copy Artifact / Copy Enchantment). Any
        # controller's, unlike `land_you_control`. ``noncreature_artifact``
        # (Karn, the Great Creator's own "becomes an artifact creature"
        # animate — RULE 115.1c excludes an already-creature artifact, the
        # one real printed qualifier no other row here needs).
        _SINGLE_TYPE_PREDICATE = {
            "artifact": lambda o: o.card.is_artifact,
            "enchantment": lambda o: o.card.is_enchantment,
            "land": lambda o: o.is_land,
            "noncreature_artifact": lambda o: o.card.is_artifact and not o.is_creature,
        }
        predicate = _SINGLE_TYPE_PREDICATE[kind]
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if predicate(o)
            and o is not source
            and _targetable_by(o, source)
            and _color_ok(spec, o.colors)
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
        ]
    if kind == "nonbasic_land":
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_land and "basic" not in o.card.type_line.lower()
            and o is not source and _targetable_by(o, source)
        ]
    if kind == "basic_land":
        # "Untap target basic land." (Earthcraft, MEC-43) — the inverse
        # filter of ``nonbasic_land`` just above.
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_land and "basic" in o.card.type_line.lower()
            and o is not source and _targetable_by(o, source)
        ]
    if kind == "forest":
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_land and "forest" in o.card.type_line.lower()
            and o is not source and _targetable_by(o, source)
        ]
    if kind == "forest_you_control":
        # "enchant Forest you control" (Harold and Bob, First Numens's own
        # dies-return-as-an-Aura shape) — `land_you_control` narrowed to
        # just the Forest subtype, the same split `forest` above is to
        # `nonbasic_land`.
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_land and "forest" in o.card.type_line.lower()
            and o.controller_id == controller_id
            and o is not source and _targetable_by(o, source)
        ]
    if kind == "legendary_permanent":
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.card.is_legendary and o is not source and _targetable_by(o, source)
            and _color_ok(spec, o.colors)
        ]
    if kind == "attached_equipment_you_control":
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if "equipment" in o.card.type_line.lower()
            and o.controller_id == controller_id
            and o.attached_to is not None
            and _targetable_by(o, source)
        ]
    if kind == "equipment_attached_to_source":
        # "destroy target Equipment attached to **it**" — "it" is this
        # ability's own source (Shackles of Treachery's granted trigger:
        # the creature it handed the quoted ability to).
        src_id = getattr(source, "instance_id", None)
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if "equipment" in o.card.type_line.lower()
            and src_id is not None and o.attached_to == src_id
            and _targetable_by(o, source)
        ]
    if kind == "equipment_you_control":
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if "equipment" in o.card.type_line.lower()
            and o.controller_id == controller_id
            and _targetable_by(o, source)
        ]
    if kind in _GRAVEYARD_TARGET_KINDS:
        # RULE 115: a card of some type in some graveyard — the Regrowth/
        # Reanimate ("your graveyard"), Deathrite Shaman/Virtue of
        # Persistence ("a graveyard" — any single graveyard, whosever it
        # is), and Puppeteer Clique ("an opponent's graveyard") families.
        # A graveyard card is never targetable *by* anything (it isn't a
        # permanent/spell), so no protection/hexproof filtering applies —
        # unlike every battlefield-object branch above.
        prefix, suffix = next(
            (p, kind[len(p) + 1:]) for p in _GRAVEYARD_SCOPE_PREFIXES if kind.startswith(p + "_")
        )
        scope = _GRAVEYARD_SCOPE_PREFIXES[prefix]
        type_filter = _GRAVEYARD_TYPE_FILTERS[suffix]
        if scope == "own":
            try:
                graveyards = [state.player_by_id(controller_id).graveyard]
            except KeyError:
                graveyards = []
        elif scope == "opponent":
            graveyards = [p.graveyard for p in state.living_players() if p.id != controller_id]
        else:  # "any": every player's graveyard, including the controller's own
            graveyards = [p.graveyard for p in state.living_players()]
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for gy in graveyards
            for o in gy
            if type_filter(o)
            and (not spec.subtype or spec.subtype in o.card.type_line.lower())
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
            # "exile target red, white, or black creature card from your
            # graveyard" (Offspring's Revenge) — the same `_color_ok` colour
            # narrowing the battlefield-object branches apply (RULE 105).
            and _color_ok(spec, o.colors)
            and o is not source
        ]
    if kind in ("spell", "spell_you_dont_control"):
        items = [
            item
            for item in state.stack
            if item.kind == "spell" and item.obj is not None and item.obj is not source
        ]
        if kind == "spell_you_dont_control":
            # "Return target spell you don't control…" (Hullbreaker
            # Horror) — the controller-scoped sibling of the plain
            # ``"spell"`` kind, keyed by `StackItem.controller_id` (RULE
            # 115.4a: whoever put it on the stack), not the underlying
            # object's own `controller_id` — the two agree for a spell
            # (it has no controller of its own until it resolves), but
            # ``item.controller_id`` is the one RULE 115 actually means.
            items = [item for item in items if item.controller_id != controller_id]
        if spec.spell_filter:
            card_filter = dict(spec.spell_filter)
            if card_filter.pop("single_target", False):
                items = [item for item in items if len(item.targets) == 1]
            if card_filter:
                items = [item for item in items if _spell_matches_filter(item.obj, card_filter)]
        return [
            {"instance_id": item.obj.instance_id, "name": item.description or item.obj.name}
            for item in items
        ]
    if kind in ("ability", "spell_or_ability"):
        # `.obj` is `None` for an ability item, so this is keyed by
        # `StackItem.stack_id` instead — see that field's own docstring
        # (ENG-26). ``item.source is None`` is the rare hand-built ability
        # with no bound permanent (`StackItem`'s own docstring); fail closed
        # on it the same way a spell target fails closed on `item.obj is
        # None` above, rather than offering an untargetable option.
        options = [
            {"stack_id": item.stack_id, "name": item.description or item.source.name}
            for item in state.stack
            if item.kind == "ability" and item.source is not None
        ]
        if kind == "spell_or_ability":
            # "target spell or ability" (Deflecting Swat) — the plain
            # ``"spell"`` branch's own options, unfiltered by
            # ``spell_filter`` since neither real card restricts by spell
            # type, alongside the ability ones just built.
            options = [
                {"instance_id": item.obj.instance_id, "name": item.description or item.obj.name}
                for item in state.stack
                if item.kind == "spell" and item.obj is not None and item.obj is not source
            ] + options
        return options
    return []


#: The vocabulary `TargetSpec.count_selector` may name. Whitelisted like
#: every other card-text-derived name in this package; an unknown one falls
#: back to the printed ``count``.
TARGET_COUNT_SELECTORS: frozenset[str] = frozenset({"opponents", "source_monstrosity_x", "source_x_paid"})


def resolved_count(
    spec: TargetSpec,
    state: Optional[GameState] = None,
    controller_id: Optional[str] = None,
    source: Optional[GameObject] = None,
) -> int:
    """How many targets ``spec`` wants *right now* (RULE 601.2c).

    ``spec.count`` unless it carries a `TARGET_COUNT_SELECTORS` name, in
    which case the number is read off the board as the spell/ability is
    announced. Never below 0 and never below the printed ``count`` when the
    board can't answer, so a caller can always treat the result as the number
    of picks to offer.
    """
    selector = spec.count_selector
    if not selector or selector not in TARGET_COUNT_SELECTORS or state is None:
        return spec.count
    if selector == "opponents":
        return sum(1 for p in state.living_players() if p.id != controller_id)
    if selector == "source_x_paid":
        # "Up to X target creatures phase out." (March of Swirling Mist,
        # MEC-42) — the spell's own announced {X} (`GameObject.x_paid`,
        # stamped by `RulesEngine.cast_spell`), read fresh at target-
        # gathering time rather than a fixed printed count.
        return max(0, int(getattr(source, "x_paid", 0) or 0))
    # "goad up to X target creatures" where X is the monstrosity just
    # announced — `GameObject.monstrosity_x` is stamped by
    # `RulesEngine.monstrosity` precisely so a *later* ability of the same
    # permanent can read the value that was paid rather than a fresh one.
    return max(0, int(getattr(source, "monstrosity_x", 0) or 0))


def expand_counts(
    specs: list[TargetSpec],
    state: Optional[GameState] = None,
    controller_id: Optional[str] = None,
    source: Optional[GameObject] = None,
) -> tuple[list[TargetSpec], list[int]]:
    """Split every multi-target requirement into one single-target spec each.

    The trigger-targeting path gathers **one pick per spec** (`RulesEngine.
    _continue_trigger_multi_target`), so an "up to N target creatures"
    requirement is offered as N consecutive rounds of the same spec rather
    than needing its own multi-select prompt. Returns the expanded list plus
    a parallel "span" list saying how many expanded specs each original one
    became, so the gathered groups can be collapsed back to one group per
    *original* spec before resolution — which is what `_apply_effects_
    partitioned` maps onto `GameEffect.target_specs`.

    A ``count`` of 1 (the overwhelming common case) expands to itself with a
    span of 1, so an unexpanded list is returned unchanged.

    ENG-30's ``count_max`` range ("N or M target X") expands to
    ``count_max`` rounds instead of ``count`` — the first ``count`` (the
    RULE 601.2c minimum) stay mandatory, the rest are marked ``optional``
    so `_continue_trigger_multi_target`'s existing "stop early" idiom (built
    for "up to N") is what lets the player decline once the minimum is met,
    without ever letting them decline below it.
    """
    expanded: list[TargetSpec] = []
    spans: list[int] = []
    for spec in specs:
        minimum = max(0, resolved_count(spec, state, controller_id, source))
        n = spec.count_max if spec.count_max is not None else minimum
        if n <= 1:
            expanded.append(spec)
            spans.append(1)
            continue
        # Each round asks for one target; "up to N" stays declinable per
        # round (RULE 115.1a lets the player stop early), a mandatory "N
        # target X" stays mandatory. A range spec mixes both: the first
        # ``minimum`` rounds mandatory, the rest declinable.
        for i in range(n):
            round_optional = spec.optional if spec.count_max is None else i >= minimum
            expanded.append(replace(spec, count=1, count_selector=None, optional=round_optional, count_max=None))
        spans.append(n)
    return expanded, spans


def collapse_groups(groups: list[list[Any]], spans: list[int]) -> list[list[Any]]:
    """The inverse of `expand_counts`: N gathered groups → one per original
    spec, so each effect still receives a single flat list of its own picks."""
    out: list[list[Any]] = []
    index = 0
    for span in spans:
        merged: list[Any] = []
        for _ in range(span):
            if index < len(groups):
                merged.extend(groups[index])
            index += 1
        out.append(merged)
    return out


def effects_target_specs(effects: Any) -> list[TargetSpec]:
    """Every RULE 115.1 requirement a raw effects list announces, in printed
    order — the shared body `ability_target_specs` wraps. Takes a bare
    effects list (not an ability) so a **modal** activated ability's own
    *chosen mode* (RULE 700.2, `ActivatedAbility.modes` — MEC-43's Umezawa's
    Jitte) can compute its own target requirements the same way
    `RulesEngine._trigger_target_specs` already lets a modal *triggered*
    ability's chosen mode do, without needing a throwaway ability-like
    wrapper object."""
    specs: list[TargetSpec] = []
    for effect in effects or []:
        polarity = effect.target_polarity()
        specs.extend(_with_polarity(spec, polarity) for spec in (getattr(effect, "target_specs", None) or []))
    return specs


def ability_target_specs(ability: Any) -> list[TargetSpec]:
    """Every RULE 115.1 requirement an activated/triggered ability announces,
    in printed order — the ability-side sibling of `spell_target_specs`, and
    the same `GameEffect.target_specs` read `RulesEngine._trigger_target_specs`
    does (so a *single* effect wanting two differently-typed targets announces
    both)."""
    return effects_target_specs(getattr(ability, "effects", None) or [])


def requirements_with_targets(
    state: GameState, controller_id: str, obj: GameObject
) -> list[dict[str, Any]]:
    """Each of ``obj``'s target requirements paired with its legal options."""
    out: list[dict[str, Any]] = []
    for spec in spell_target_specs(obj):
        entry = {
            "kind": spec.kind,
            "optional": spec.optional,
            # RULE 601.2c: resolved now, since a `count_selector` reads
            # the board as the spell is announced. For a `count_max` range
            # this is the *minimum* — the number of rounds that stay
            # mandatory; `count_max` below is how many rounds to offer in
            # total (ENG-30).
            "count": resolved_count(spec, state, controller_id, obj),
            "label": spec.label(),
            "options": legal_targets(state, controller_id, spec, source=obj),
            "distinct_controllers": spec.distinct_controllers,
            "distinct_from_others": spec.distinct_from_others,
            "polarity": spec.polarity,
        }
        if spec.count_max is not None:
            entry["count_max"] = spec.count_max
        out.append(entry)
    return out


def partition_targets(
    specs: list[TargetSpec], targets: Optional[list[Any]]
) -> Optional[list[list[Any]]]:
    """A flat, in-printed-order ``targets`` list → one group per spec.

    RULE 115.1: a caster picks targets requirement by requirement in printed
    order (`requirements_with_targets`, and the board UI walks exactly that
    list), so a flat list of the expected length is unambiguously the
    concatenation of the groups — which is what `StackItem.target_groups`
    wants when 2+ *different* effects each need their own target ("target
    creature you control gets +1/+2 …. It fights target creature you don't
    control.").

    Returns ``None`` — meaning "keep the old shared-list behaviour" — for
    anything ambiguous: fewer than two requirements (nothing to partition),
    or a length that doesn't match the requirements' total ``count``, which
    is exactly what an *optional* requirement declined mid-list produces
    (the picks shift and no server-side rule can tell which slot was
    skipped). A client that can decline has to send explicit
    ``target_groups`` instead; `gameBoardView.js` does.
    """
    if targets is None or len(specs) < 2:
        return None
    if len(targets) != sum(max(1, spec.count) for spec in specs):
        return None
    groups: list[list[Any]] = []
    index = 0
    for spec in specs:
        take = max(1, spec.count)
        groups.append(list(targets[index:index + take]))
        index += take
    return groups


def all_requirements_satisfiable(requirements: list[dict[str, Any]]) -> bool:
    """Whether every requirement has enough legal targets to be castable.

    RULE 601.2c: a mandatory "N target X" needs at least ``N`` legal
    options to be castable at all; an "up to N" requirement is never
    locked (0 is always a legal choice, same as the existing "up to one").
    """
    return all(
        req["optional"] or len(req["options"]) >= req.get("count", 1) for req in requirements
    )
