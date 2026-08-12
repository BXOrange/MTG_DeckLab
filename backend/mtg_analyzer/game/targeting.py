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

from ..models.game_object import GameObject
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
    "instant_or_sorcery": lambda o: bool(o.card.is_instant or o.card.is_sorcery),
    # "target **sorcery** card in your graveyard gains flashback…" (MEC-24,
    # Recoup) — the sorcery-only narrowing of the combined filter above.
    "sorcery": lambda o: bool(o.card.is_sorcery),
    "permanent": lambda o: o.is_creature or o.is_land or o.is_planeswalker
    or bool(o.card.is_artifact or o.card.is_enchantment),
    "nonland_permanent": lambda o: o.is_creature or o.is_planeswalker
    or bool(o.card.is_artifact or o.card.is_enchantment),
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
#: "any" is Magic's "any target" (RULE 115.4): any creature or player (we
#: don't model planeswalkers/battles yet). Extend as new restrictions land.
#: ``creature_you_control``/``land_you_control`` narrow a battlefield pick to
#: the controller's own permanents (RULE 115/603.3c, or a non-"target"
#: resolve-time choice among one's own permanents modeled the same way, e.g.
#: a bounce-land's "return a land you control…"); the `graveyard_*`/
#: `any_graveyard_*`/`opponent_graveyard_*` family (see
#: `_GRAVEYARD_TARGET_KINDS`) is a card of some type in some graveyard.
ALLOWED_TARGET_KINDS: frozenset[str] = frozenset(
    {
        "any", "creature", "permanent", "player", "spell",
        # Single-type permanent targets (RULE 115.1c — "target artifact"/
        # "target enchantment"/"target land"), any controller's.
        "artifact", "enchantment", "land",
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
        # RULE 109.5's "*another* target creature you control" (Giver of
        # Runes) — `creature_you_control` minus the ability's own source.
        "other_creature_you_control",
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
        # RULE 702.140a's "target **non-Human** creature you own" — mutate's
        # own target line. Note *own*, not control (RULE 108.3): a creature
        # you own but an opponent controls is still a legal mutate host, and
        # the Human exclusion is the reason Humans dodge the mechanic.
        "non_human_creature_you_own",
        # "target artifact or enchantment" (Archdruid's Charm) — the union of
        # the two single-type kinds, a common printed phrasing.
        "artifact_or_enchantment",
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
        "nonbasic_land",
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
    }
) | _GRAVEYARD_TARGET_KINDS

#: German noun phrase per `_GRAVEYARD_TYPE_FILTERS` suffix, for `_graveyard_label`.
_GRAVEYARD_TYPE_LABELS: dict[str, str] = {
    "card": "Karte",
    "creature": "Kreaturenkarte",
    "land": "Landkarte",
    "artifact": "Artefaktkarte",
    "enchantment": "Verzauberungskarte",
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
            "non_human_creature_you_own": "Nicht-Mensch-Kreatur, die du besitzt",
            "creature_you_dont_control": "Kreatur, die du nicht kontrollierst",
            "artifact_you_dont_control": "Artefakt, das du nicht kontrollierst",
            "artifact_or_enchantment": "Artefakt oder Verzauberung",
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
            "battle_or_opponent": "Schlacht oder Gegner",
            "creature_planeswalker_or_battle": "Kreatur, Planeswalker oder Schlacht",
            "attached_aura_or_equipment_you_control":
                "Aura oder Ausrüstung an einer Kreatur unter deiner Kontrolle",
            "land_you_control": "Land unter deiner Kontrolle",
            "attached_equipment_you_control": "befestigte Ausrüstung unter deiner Kontrolle",
            "equipment_you_control": "Ausrüstung unter deiner Kontrolle",
            "nonbasic_land": "nichtgrundlegendes Land",
            "legendary_permanent": "legendäre bleibende Karte",
            "forest_you_control": "Wald unter deiner Kontrolle",
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
    return True


def _creature_matches_filter(obj: GameObject, filt: dict[str, Any]) -> bool:
    """Whether ``obj`` satisfies a `TargetSpec.creature_filter` (see its
    docstring for the key vocabulary).

    Delegates to `combat.matches_object_filter`, which owns the same key
    vocabulary for RULE 509.1b's qualified blocking restrictions ("can't be
    blocked by creatures with power 2 or less") — one predicate rather than
    two that can drift. That superset also understands subtype/colour/
    card-type/relative-power keys this field's own docstring doesn't
    advertise; a `TargetSpec` simply never sets them today.
    """
    return combat.matches_object_filter(obj, filt)


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
    """
    kind = spec.kind
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
            if not quality or quality in {"permanent", "anything"}:
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.permanents()
                    if o is not source and _targetable_by(o, source)
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
        objs = [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_creature and o is not source and _targetable_by(o, source)
            and (not spec.color or spec.color in o.colors)
        ]
        players = [{"player_id": p.id, "name": p.name} for p in state.living_players()]
        return objs + (players if not spec.color else [])
    if kind in ("creature", "permanent"):
        return [
            # ``controller_id`` is only ever consumed client-side when
            # `spec.distinct_controllers` is set (`gameBoardView.js`'s
            # per-round exclusion) — harmless to always include otherwise.
            {"instance_id": o.instance_id, "name": o.name, "controller_id": o.controller_id}
            for o in state.permanents()
            if (kind == "permanent" or o.is_creature)
            and o is not source
            and _targetable_by(o, source)
            and (not spec.color or spec.color in o.colors)
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
            and (not spec.creature_filter or _creature_matches_filter(o, spec.creature_filter))
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
            and (not spec.color or spec.color in o.colors)
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
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
            and (not spec.color or spec.color in o.colors)
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
            and (not spec.color or spec.color in o.colors)
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
        ]
    if kind == "creature_you_dont_control":
        # RULE 115: the mirror image of `creature_you_control` — an
        # opponent's creature (or, strictly, any creature this ability's
        # controller doesn't control).
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_creature
            and o.controller_id != controller_id
            and _targetable_by(o, source)
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
    if kind in ("artifact", "enchantment", "land"):
        # RULE 115 single-type permanent target (also the enter-as-copy
        # candidate pool for Copy Artifact / Copy Enchantment). Any
        # controller's, unlike `land_you_control`.
        _SINGLE_TYPE_PREDICATE = {
            "artifact": lambda o: o.card.is_artifact,
            "enchantment": lambda o: o.card.is_enchantment,
            "land": lambda o: o.is_land,
        }
        predicate = _SINGLE_TYPE_PREDICATE[kind]
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if predicate(o)
            and o is not source
            and _targetable_by(o, source)
            and (not spec.color or spec.color in o.colors)
            and (spec.max_mana_value is None or o.card.converted_mana_cost <= spec.max_mana_value)
        ]
    if kind == "nonbasic_land":
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if o.is_land and "basic" not in o.card.type_line.lower()
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
            and (not spec.color or spec.color in o.colors)
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
            and o is not source
        ]
    if kind == "spell":
        items = [
            item
            for item in state.stack
            if item.kind == "spell" and item.obj is not None and item.obj is not source
        ]
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
TARGET_COUNT_SELECTORS: frozenset[str] = frozenset({"opponents", "source_monstrosity_x"})


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


def ability_target_specs(ability: Any) -> list[TargetSpec]:
    """Every RULE 115.1 requirement an activated/triggered ability announces,
    in printed order — the ability-side sibling of `spell_target_specs`, and
    the same `GameEffect.target_specs` read `RulesEngine._trigger_target_specs`
    does (so a *single* effect wanting two differently-typed targets announces
    both)."""
    specs: list[TargetSpec] = []
    for effect in getattr(ability, "effects", None) or []:
        polarity = effect.target_polarity()
        specs.extend(_with_polarity(spec, polarity) for spec in (getattr(effect, "target_specs", None) or []))
    return specs


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
