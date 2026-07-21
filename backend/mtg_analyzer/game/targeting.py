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

from dataclasses import dataclass
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
        "creature_you_control", "land_you_control",
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
    ability's own target choice already gathers one per effect
    automatically (`_continue_trigger_multi_target`); a spell/activated
    ability's caller must supply ``target_groups`` explicitly (no real card
    needs this yet, so nothing auto-derives it from a plain flat list — see
    `docs/implementation-state/ToDo_Backend.md` for the remaining
    cross-target-constraint gap, e.g. "two creatures controlled by
    *different* players"). ``description`` is a short UI label.
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

    def label(self) -> str:
        return self.description or _graveyard_label(self.kind) or {
            "any": "beliebiges Ziel",
            "creature": "Kreatur",
            "permanent": "bleibende Karte",
            "player": "Spieler",
            "spell": "Zauberspruch",
            "creature_you_control": "Kreatur unter deiner Kontrolle",
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
        spec = getattr(effect, "target_spec", None)
        if spec is not None:
            specs.append(spec)
    if not specs and "enchant" in (getattr(obj, "parametric_keywords", None) or {}):
        specs.append(TargetSpec(kind="permanent", description="zu verzauberndes Ziel"))
    return specs


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
    docstring for the key vocabulary)."""
    min_power = filt.get("min_power")
    if min_power is not None and (obj.power or 0) < min_power:
        return False
    max_power = filt.get("max_power")
    if max_power is not None and (obj.power or 0) > max_power:
        return False
    min_toughness = filt.get("min_toughness")
    if min_toughness is not None and (obj.toughness or 0) < min_toughness:
        return False
    max_toughness = filt.get("max_toughness")
    if max_toughness is not None and (obj.toughness or 0) > max_toughness:
        return False
    keyword = filt.get("keyword")
    if keyword is not None and not combat.has(obj, keyword):
        return False
    return True


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
            return [
                {"instance_id": o.instance_id, "name": o.name}
                for o in state.permanents()
                if (o.is_creature or o.card.is_artifact)
                and o is not source
                and _targetable_by(o, source)
            ]
        if attachment_kind == "reconfigure":
            return [
                {"instance_id": o.instance_id, "name": o.name}
                for o in state.permanents()
                if o.is_creature and o is not source and _targetable_by(o, source)
            ]
        if attachment_kind == "fortify":
            return [
                {"instance_id": o.instance_id, "name": o.name}
                for o in state.permanents()
                if o.is_land and o is not source and _targetable_by(o, source)
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
    if kind in ("creature_you_control", "land_you_control"):
        # RULE 115/603.3c controller-restricted pick — and the same shape for
        # a non-"target" resolve-time choice among the controller's own
        # permanents (a bounce-land's "return a land you control…").
        wants_land = kind == "land_you_control"
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.permanents()
            if (o.is_land if wants_land else o.is_creature)
            and o.controller_id == controller_id
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
                "count": spec.count,
                "label": spec.label(),
                "options": legal_targets(state, controller_id, spec, source=obj),
                "distinct_controllers": spec.distinct_controllers,
            }
        )
    return out


def all_requirements_satisfiable(requirements: list[dict[str, Any]]) -> bool:
    """Whether every requirement has enough legal targets to be castable.

    RULE 601.2c: a mandatory "N target X" needs at least ``N`` legal
    options to be castable at all; an "up to N" requirement is never
    locked (0 is always a legal choice, same as the existing "up to one").
    """
    return all(
        req["optional"] or len(req["options"]) >= req.get("count", 1) for req in requirements
    )
