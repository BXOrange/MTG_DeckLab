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
    "permanent": lambda o: o.is_creature or o.is_land or o.is_planeswalker
    or bool(o.card.is_artifact or o.card.is_enchantment),
    "nonland_permanent": lambda o: o.is_creature or o.is_planeswalker
    or bool(o.card.is_artifact or o.card.is_enchantment),
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
        # "target player who was dealt combat damage by ~ this turn" (Hope of
        # Ghirapur) — `player` narrowed by a per-turn damage *history*, the
        # one target kind here answered from a record rather than the board.
        "player_dealt_combat_damage_by_source",
        "creature_you_control", "land_you_control",
        # RULE 109.5's "*another* target creature you control" (Giver of
        # Runes) — `creature_you_control` minus the ability's own source.
        "other_creature_you_control",
        # "target creature you **don't** control" (Archdruid's Charm's second
        # mode) — the mirror image of `creature_you_control`.
        "creature_you_dont_control",
        # RULE 702.140a's "target **non-Human** creature you own" — mutate's
        # own target line. Note *own*, not control (RULE 108.3): a creature
        # you own but an opponent controls is still a legal mutate host, and
        # the Human exclusion is the reason Humans dodge the mechanic.
        "non_human_creature_you_own",
        # "target artifact or enchantment" (Archdruid's Charm) — the union of
        # the two single-type kinds, a common printed phrasing.
        "artifact_or_enchantment",
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
    #: beyond the bare "target spell". ``None``/``{}`` means unfiltered.
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

    def label(self) -> str:
        return self.description or _graveyard_label(self.kind) or {
            "any": "beliebiges Ziel",
            "creature": "Kreatur",
            "permanent": "bleibende Karte",
            "player": "Spieler",
            "player_dealt_combat_damage_by_source":
                "Spieler, dem diese Karte in diesem Zug Kampfschaden zugefügt hat",
            "spell": "Zauberspruch",
            "creature_you_control": "Kreatur unter deiner Kontrolle",
            "other_creature_you_control": "andere Kreatur unter deiner Kontrolle",
            "non_human_creature_you_own": "Nicht-Mensch-Kreatur, die du besitzt",
            "creature_you_dont_control": "Kreatur, die du nicht kontrollierst",
            "artifact_or_enchantment": "Artefakt oder Verzauberung",
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
        specs.extend(getattr(effect, "target_specs", None) or [])
    if not specs and "enchant" in (getattr(obj, "parametric_keywords", None) or {}):
        specs.append(TargetSpec(kind="permanent", description="zu verzauberndes Ziel"))
    return specs


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
    if kind in ("artifact", "enchantment"):
        # RULE 115 single-type permanent target (also the enter-as-copy
        # candidate pool for Copy Artifact / Copy Enchantment).
        want_artifact = kind == "artifact"
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.card.is_artifact if want_artifact else o.card.is_enchantment)
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
        ]
    if kind == "spell":
        items = [
            item
            for item in state.stack
            if item.kind == "spell" and item.obj is not None and item.obj is not source
        ]
        if spec.spell_filter:
            items = [item for item in items if _spell_matches_filter(item.obj, spec.spell_filter)]
        return [
            {"instance_id": item.obj.instance_id, "name": item.description or item.obj.name}
            for item in items
        ]
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
    """
    expanded: list[TargetSpec] = []
    spans: list[int] = []
    for spec in specs:
        n = max(0, resolved_count(spec, state, controller_id, source))
        if n <= 1:
            expanded.append(spec)
            spans.append(1)
            continue
        # Each round asks for one target; "up to N" stays declinable per
        # round (RULE 115.1a lets the player stop early), a mandatory "N
        # target X" stays mandatory.
        expanded.extend(replace(spec, count=1, count_selector=None) for _ in range(n))
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
    return [
        spec
        for effect in (getattr(ability, "effects", None) or [])
        for spec in (getattr(effect, "target_specs", None) or [])
    ]


def requirements_with_targets(
    state: GameState, controller_id: str, obj: GameObject
) -> list[dict[str, Any]]:
    """Each of ``obj``'s target requirements paired with its legal options."""
    out: list[dict[str, Any]] = []
    for spec in spell_target_specs(obj):
        out.append(
            {
                "kind": spec.kind,
                "optional": spec.optional,
                # RULE 601.2c: resolved now, since a `count_selector` reads
                # the board as the spell is announced.
                "count": resolved_count(spec, state, controller_id, obj),
                "label": spec.label(),
                "options": legal_targets(state, controller_id, spec, source=obj),
                "distinct_controllers": spec.distinct_controllers,
                "distinct_from_others": spec.distinct_from_others,
            }
        )
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
