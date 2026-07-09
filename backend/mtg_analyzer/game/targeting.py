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

#: The target categories the engine can resolve to concrete board objects.
#: "any" is Magic's "any target" (RULE 115.4): any creature or player (we
#: don't model planeswalkers/battles yet). Extend as new restrictions land.
ALLOWED_TARGET_KINDS: frozenset[str] = frozenset(
    {"any", "creature", "permanent", "player", "spell"}
)


@dataclass(frozen=True)
class TargetSpec:
    """One required target of a targeting effect (RULE 115.1).

    ``kind`` is one of `ALLOWED_TARGET_KINDS`; ``optional`` marks "up to one
    target" (RULE 115.1a), which never locks a spell (zero targets is a legal
    choice). ``description`` is a short UI label.
    """

    kind: str = "any"
    optional: bool = False
    description: str = ""

    def label(self) -> str:
        return self.description or {
            "any": "beliebiges Ziel",
            "creature": "Kreatur",
            "permanent": "bleibende Karte",
            "player": "Spieler",
            "spell": "Zauberspruch",
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


def legal_targets(
    state: GameState,
    controller_id: str,
    spec: TargetSpec,
    source: Optional[GameObject] = None,
) -> list[dict[str, Any]]:
    """The currently legal targets for ``spec`` as JSON-able descriptors.

    Players are returned as ``{"player_id", "name"}``; objects as
    ``{"instance_id", "name"}``. Excludes ``source`` itself so a spell can't
    target itself where that's illegal (RULE 115.6 for the common cases here).
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
                for o in state.battlefield
                if (o.is_creature or o.card.is_artifact) and o is not source
            ]
        if attachment_kind == "reconfigure":
            return [
                {"instance_id": o.instance_id, "name": o.name}
                for o in state.battlefield
                if o.is_creature and o is not source
            ]
        if attachment_kind == "enchant":
            quality = ((source.parametric_keywords or {}).get("enchant") or {}).get("quality", "")
            quality = str(quality).strip().lower()
            if not quality or quality in {"permanent", "anything"}:
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.battlefield
                    if o is not source
                ]
            if quality == "creature":
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.battlefield
                    if o.is_creature and o is not source
                ]
            if quality == "artifact":
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.battlefield
                    if o.card.is_artifact and o is not source
                ]
            if quality == "enchantment":
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.battlefield
                    if o.card.is_enchantment and o is not source
                ]
            if quality == "land":
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.battlefield
                    if o.is_land and o is not source
                ]
            if quality == "planeswalker":
                return [
                    {"instance_id": o.instance_id, "name": o.name}
                    for o in state.battlefield
                    if o.is_planeswalker and o is not source
                ]
    if kind == "player":
        return [
            {"player_id": p.id, "name": p.name}
            for p in state.living_players()
        ]
    if kind == "any":
        objs = [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.battlefield
            if o.is_creature and o is not source
        ]
        players = [{"player_id": p.id, "name": p.name} for p in state.living_players()]
        return objs + players
    if kind in ("creature", "permanent"):
        return [
            {"instance_id": o.instance_id, "name": o.name}
            for o in state.battlefield
            if (kind == "permanent" or o.is_creature) and o is not source
        ]
    if kind == "spell":
        return [
            {"instance_id": item.obj.instance_id, "name": item.description or item.obj.name}
            for item in state.stack
            if item.kind == "spell" and item.obj is not None and item.obj is not source
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
                "label": spec.label(),
                "options": legal_targets(state, controller_id, spec, source=obj),
            }
        )
    return out


def all_requirements_satisfiable(requirements: list[dict[str, Any]]) -> bool:
    """Whether every non-optional requirement has at least one legal target."""
    return all(req["optional"] or req["options"] for req in requirements)
