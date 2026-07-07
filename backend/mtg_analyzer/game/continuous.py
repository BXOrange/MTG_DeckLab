"""The continuous-effects layer engine (RULE 613).

Static abilities (`StaticAbility`, from `effects.py`) don't *do* anything when
they resolve — they continuously reshape other permanents' characteristics.
RULE 613 says how overlapping ones combine: apply them in a fixed sequence of
**layers**, so the board's derived characteristics are well-defined no matter
what order the abilities entered play.

This module implements the layers this engine meets:

* **Layer 4** — type-changing effects ("… are creatures");
* **Layer 6** — ability-adding effects ("… have flying");
* **Layer 7** — power/toughness, in sublayer order: 7b set, 7c counters,
  7d modify (anthems). 7a CDAs and 7e P/T switches are not modeled yet.

Plus a non-layer bucket, **cost adjustments** (RULE 601.2f — "spells cost {N}
less"), which aren't part of 613 but are the other everyday static effect and
are computed here for the same recompute.

`recompute(state)` resets every battlefield object's derived characteristics
and re-derives them from scratch, stamping the result — and a per-object,
per-layer **trace** — back onto each `GameObject` (`_derived_power`,
`_granted_keywords`, `_added_types`, `static_trace`). The engine calls it
whenever the board settles (state-based actions) and before serialization, so
reads of `obj.power`/`obj.is_creature`/`combat.keywords_of` see the live layer
stack. Ordering *within* a layer is a simplification (registration order, not
true dependency/timestamp order, RULE 613.7) — enough for the anthems, grants
and animations the card pool needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .effects import StaticAbility

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models.game_object import GameObject
    from ..models.game_state import GameState
    from ..models.player import Player


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def _has_subtype(obj: "GameObject", subtype: str) -> bool:
    """Whether ``obj`` has creature subtype ``subtype`` (RULE 205.3, tribal lords).

    A case-insensitive match against the printed type line's subtype portion —
    the same substring approach the tutor's `card_query` uses ("Goblin" matches
    "Creature — Goblin Warrior"). Changeling (RULE 702.73) is every creature
    type, so it matches any subtype.
    """
    type_line = obj.card.type_line.lower()
    if "changeling" in type_line or "changeling" in obj.intrinsic_keywords:
        return True
    _, _, sub = type_line.partition("—")  # subtypes follow the em dash
    return subtype.lower() in sub


def _has_color(obj: "GameObject", colors: list) -> bool:
    """Whether ``obj`` is any of ``colors`` (RULE 105 / colour-scoped anthems).

    Reads the object's effective ``colors`` (a layer-5 colour-changing effect
    if one applies, else the printed ``color_identity`` — the same field the
    tutor's `card_query` matches on). ``"C"`` means colourless — no WUBRG.
    """
    identity = obj.colors
    wubrg = identity & {"W", "U", "B", "R", "G"}
    for c in colors:
        if c == "C":
            if not wubrg:
                return True
        elif c in identity:
            return True
    return False


def affected_objects(state: "GameState", ability: StaticAbility) -> list["GameObject"]:
    """The battlefield objects an ability's ``affects`` selector picks out.

    "you control" is scoped by the ability's source controller; an unsourced
    ability (a bare test fixture) matches nothing for those selectors. A
    ``params["subtype"]`` narrows the base set to that creature type — the
    tribal-lord filter (Goblin King's "Other Goblin creatures you control …").
    """
    src = ability.source
    controller = getattr(src, "controller_id", None)
    battlefield = state.battlefield
    affects = ability.affects

    if affects == "self":
        result = [src] if src is not None and src in battlefield else []
    elif affects == "all_creatures":
        result = [o for o in battlefield if o.is_creature]
    elif affects == "all_permanents":
        result = list(battlefield)
    elif controller is None:
        result = []
    elif affects == "creatures_you_control":
        result = [o for o in battlefield if o.is_creature and o.controller_id == controller]
    elif affects == "other_creatures_you_control":
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller and o is not src
        ]
    elif affects == "permanents_you_control":
        result = [o for o in battlefield if o.controller_id == controller]
    elif affects == "lands_you_control":
        result = [o for o in battlefield if o.is_land and o.controller_id == controller]
    else:
        result = []

    subtype = ability.params.get("subtype")
    if subtype:
        result = [o for o in result if _has_subtype(o, str(subtype))]
    color = ability.params.get("color")
    if color:  # colour-scoped anthem ("Black creatures get +1/+1", Bad Moon)
        result = [o for o in result if _has_color(o, list(color))]
    if ability.params.get("tokens"):  # "creature tokens you control …" (RULE 111)
        result = [o for o in result if getattr(o, "is_token", False)]
    if ability.params.get("exclude_self"):  # a global "Other creatures …" anthem
        result = [o for o in result if o is not src]
    return result


def _source_name(ability: StaticAbility) -> str:
    src = ability.source
    return src.name if src is not None else "static"


def _trace(
    obj: "GameObject",
    layer: int,
    label: str,
    description: str,
    power: Any = None,
    toughness: Any = None,
) -> None:
    obj.static_trace.append(
        {
            "layer": layer,
            "source": label,
            "description": description,
            "power": power,
            "toughness": toughness,
        }
    )


def _battlefield_static_abilities(state: "GameState") -> list[StaticAbility]:
    return [
        ab
        for src in state.battlefield
        for ab in getattr(src, "static_effects", [])
        if isinstance(ab, StaticAbility)
    ]


def _in_layer(abilities: list[StaticAbility], layer: str) -> list[StaticAbility]:
    """Abilities in one (sub)layer, ordered by source timestamp (RULE 613.7b).

    Within a layer, effects apply in timestamp order (newest last); an
    unsourced fixture ability sorts first (timestamp 0). A true dependency
    pass (RULE 613.8) is still a simplification — timestamps cover the
    overwhelmingly common non-dependent case.
    """
    picked = [a for a in abilities if a.layer == layer]
    return sorted(picked, key=lambda a: getattr(a.source, "timestamp", 0))


def _count_selector(state: "GameState", ability: StaticAbility, selector: str) -> int:
    """Evaluate a layer-7a characteristic-defining count (RULE 613.7c / 604.3).

    A small vocabulary of "number of X" selectors a ``*/*`` creature's power or
    toughness can be defined by — enough for the common CDAs (Nightmare's
    Swamps, a graveyard-count beater). "you control" is scoped to the source's
    controller."""
    bf = state.battlefield
    controller = getattr(ability.source, "controller_id", None)
    if selector == "creatures_you_control":
        return sum(1 for o in bf if o.is_creature and o.controller_id == controller)
    if selector == "lands_you_control":
        return sum(1 for o in bf if o.is_land and o.controller_id == controller)
    if selector == "permanents_you_control":
        return sum(1 for o in bf if o.controller_id == controller)
    if selector == "artifacts_you_control":
        return sum(1 for o in bf if o.card.is_artifact and o.controller_id == controller)
    if selector == "cards_in_your_graveyard":
        try:
            player = state.player_by_id(controller) if controller else None
        except KeyError:
            player = None
        return len(player.graveyard) if player is not None else 0
    return 0


def recompute(state: "GameState") -> None:
    """Re-derive every battlefield permanent's characteristics (RULE 613)."""
    # Restore any controller a prior layer-2 pass changed, so this pass
    # re-applies control effects from a clean base (RULE 613.2, idempotent).
    for obj in state.battlefield:
        if obj._control_base is not None:
            obj.controller_id = obj._control_base
            obj._control_base = None
        obj.reset_derived()

    abilities = [ab for ab in _battlefield_static_abilities(state) if ab.layer != "cost"]

    # -- Layer 2: control-changing effects (RULE 613.2).
    for ability in _in_layer(abilities, "control"):
        new_controller = ability.params.get("controller") or getattr(
            ability.source, "controller_id", None
        )
        if new_controller is None:
            continue
        for obj in affected_objects(state, ability):
            if obj.controller_id != new_controller:
                obj._control_base = obj.controller_id
                obj.controller_id = new_controller
                _trace(obj, 2, _source_name(ability), f"controlled by {new_controller}")

    # -- Layer 4: type-changing effects (may add "creature" + animation P/T).
    animation_pt: dict[int, tuple[int, int]] = {}
    for ability in _in_layer(abilities, "type"):
        added = ability.params.get("add_types", [])
        power, toughness = ability.params.get("power"), ability.params.get("toughness")
        for obj in affected_objects(state, ability):
            for type_name in added:
                obj._added_types.add(type_name)
            if power is not None and toughness is not None:
                animation_pt[obj.instance_id] = (power, toughness)
            _trace(obj, 4, _source_name(ability), "becomes " + ", ".join(added))

    # -- Layer 5: colour-changing effects (RULE 613.4b).
    for ability in _in_layer(abilities, "color"):
        colors = [str(c).upper() for c in ability.params.get("colors", [])]
        replace = bool(ability.params.get("set", True))
        for obj in affected_objects(state, ability):
            if obj._derived_colors is None or replace:
                obj._derived_colors = set() if replace else obj.colors
            obj._derived_colors.update(colors)
            _trace(obj, 5, _source_name(ability), "becomes " + ", ".join(colors))

    # -- Layer 6: ability-adding effects (keyword grants).
    for ability in _in_layer(abilities, "ability"):
        keywords = ability.params.get("keywords", [])
        for obj in affected_objects(state, ability):
            obj._granted_keywords.update(keywords)
            _trace(obj, 6, _source_name(ability), "gains " + ", ".join(keywords))

    # -- Layer 7: power/toughness, on working base values so the sublayers
    # apply in order (7a CDA → 7b set → 7c counters → 7d modify → 7e switch).
    base: dict[int, list[int]] = {}
    for obj in state.battlefield:
        if not obj.is_creature:
            continue
        if obj.instance_id in animation_pt:
            base[obj.instance_id] = list(animation_pt[obj.instance_id])
        else:
            base[obj.instance_id] = [obj.card.power or 0, obj.card.toughness or 0]

    # 7a: characteristic-defining P/T ("power/toughness equal to the number of …").
    for ability in _in_layer(abilities, "pt_cda"):
        p_sel = ability.params.get("power_count")
        t_sel = ability.params.get("toughness_count")
        for obj in affected_objects(state, ability):
            if obj.instance_id not in base:
                continue
            if p_sel:
                base[obj.instance_id][0] = _count_selector(state, ability, str(p_sel))
            if t_sel:
                base[obj.instance_id][1] = _count_selector(state, ability, str(t_sel))
            p, t = base[obj.instance_id]
            _trace(obj, 7, _source_name(ability), f"defined as {p}/{t}", p, t)

    # 7b: set power/toughness to a specific value.
    for ability in _in_layer(abilities, "pt_set"):
        power = ability.params.get("power", 0)
        toughness = ability.params.get("toughness", 0)
        for obj in affected_objects(state, ability):
            if obj.instance_id in base:
                base[obj.instance_id] = [power, toughness]
                _trace(obj, 7, _source_name(ability), f"set to {power}/{toughness}", power, toughness)

    # 7c: counters (RULE 613.7 counters sublayer / 122).
    for obj in state.battlefield:
        if obj.instance_id in base:
            counters = obj.plus_one_counters
            if counters:
                base[obj.instance_id][0] += counters
                base[obj.instance_id][1] += counters
                p, t = base[obj.instance_id]
                _trace(obj, 7, "Counters", f"{_signed(counters)}/{_signed(counters)}", p, t)

    # 7d: modify (but don't set) power/toughness — anthems.
    for ability in _in_layer(abilities, "pt_mod"):
        d_power = ability.params.get("power", 0)
        d_toughness = ability.params.get("toughness", 0)
        for obj in affected_objects(state, ability):
            if obj.instance_id in base:
                base[obj.instance_id][0] += d_power
                base[obj.instance_id][1] += d_toughness
                p, t = base[obj.instance_id]
                _trace(obj, 7, _source_name(ability), f"{_signed(d_power)}/{_signed(d_toughness)}", p, t)

    # 7e: switch power and toughness (RULE 613.7e / 701.28). Applied last, so it
    # swaps the fully-computed values.
    for ability in _in_layer(abilities, "pt_switch"):
        for obj in affected_objects(state, ability):
            if obj.instance_id in base:
                base[obj.instance_id].reverse()
                p, t = base[obj.instance_id]
                _trace(obj, 7, _source_name(ability), f"switched to {p}/{t}", p, t)

    for obj in state.battlefield:
        if obj.instance_id in base:
            obj._derived_power, obj._derived_toughness = base[obj.instance_id]


def cost_reduction_for(state: "GameState", player: "Player") -> tuple[int, list[dict[str, Any]]]:
    """Net generic-mana reduction for a spell ``player`` casts (RULE 601.2f).

    Sums "cost {N} less" statics and subtracts "cost {N} more" ones that apply
    to the player's spells, returning ``(net_reduction, contributors)`` where a
    positive reduction lowers the generic cost (never below zero, applied by
    the caller) and ``contributors`` describes each for the UI.
    """
    net = 0
    contributors: list[dict[str, Any]] = []
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cost":
            continue
        if ability.affects == "your_spells" and getattr(ability.source, "controller_id", None) != player.id:
            continue
        amount = ability.params.get("generic", 0)
        signed = -amount if ability.params.get("increase") else amount
        net += signed
        contributors.append(
            {
                "source": _source_name(ability),
                "amount": signed,
                "description": f"Spells cost {{{amount}}} {'more' if ability.params.get('increase') else 'less'}",
            }
        )
    return net, contributors


def active_static_abilities(state: "GameState") -> list[dict[str, Any]]:
    """A flat summary of every static ability in play, for the UI's panel."""
    summary: list[dict[str, Any]] = []
    for ability in _battlefield_static_abilities(state):
        summary.append(
            {
                "source": _source_name(ability),
                "layer": ability.layer_number if ability.layer != "cost" else "cost",
                "kind": ability.layer,
                "affects": ability.affects,
                "description": ability.description or _describe_ability(ability),
            }
        )
    return summary


def _describe_ability(ability: StaticAbility) -> str:
    p = ability.params
    if ability.layer == "pt_mod":
        return f"{_signed(p.get('power', 0))}/{_signed(p.get('toughness', 0))} to {ability.affects}"
    if ability.layer == "pt_set":
        return f"sets {ability.affects} to {p.get('power', 0)}/{p.get('toughness', 0)}"
    if ability.layer == "pt_switch":
        return f"switches P/T of {ability.affects}"
    if ability.layer == "pt_cda":
        return f"defines P/T of {ability.affects}"
    if ability.layer == "ability":
        return "grants " + ", ".join(p.get("keywords", []))
    if ability.layer == "type":
        return "makes " + ", ".join(p.get("add_types", []))
    if ability.layer == "color":
        return "colours " + ", ".join(p.get("colors", []))
    if ability.layer == "control":
        return f"controls {ability.affects}"
    if ability.layer == "cost":
        return f"spells cost {{{p.get('generic', 0)}}} {'more' if p.get('increase') else 'less'}"
    return ability.affects
