"""The continuous-effects layer engine (RULE 613).

Static abilities (`StaticAbility`, from `effects.py`) don't *do* anything when
they resolve — they continuously reshape other permanents' characteristics.
RULE 613 says how overlapping ones combine: apply them in a fixed sequence of
**layers**, so the board's derived characteristics are well-defined no matter
what order the abilities entered play.

This module implements every layer this engine meets:

* **Layer 1** — copy effects (RULE 707), *conditional/continuous* ones only:
  "as long as [condition], ~ is a copy of [target]" (Vesuvan Shapeshifter).
  Transition-only (see `_apply_copy_layer`) — the other two copy mechanisms
  this engine models are discrete mutations instead, since neither needs to
  revert on its own: the permanent "you may have this enter as a copy of
  target X" (RULE 614.1c/614.12, Clever Impersonator — `RulesEngine.
  _offer_enter_as_copy`, resolved *before* the object is added to the
  battlefield) and the temporary "… until end of turn" copy (Cursed Mirror —
  `RulesEngine.become_copy_until_end_of_turn`, reverted at cleanup). All
  three share `game/copy_mechanics.py`'s mutate/snapshot/restore primitives
  — see docs/11 §"Copying objects" for why they're split rather than
  unified.
* **Layer 2** — control-changing effects ("you control enchanted creature");
* **Layer 3** — text-changing effects (RULE 612), *scoped*: word-substitution
  over `GameObject.effective_oracle_text`, consumed today only by
  `combat.protections_of_text` (the canonical Artificial-Evolution "protection
  from red" → "protection from blue" case). This is **not** a full oracle-text
  re-parse — bound abilities/keywords still come from the *printed* text once
  at bind time, unaffected. A card that grants *another* ability to other
  permanents ("Elves you control have '{T}: Add {B}.'" — Tyvar Kell; "Elves
  you control have '<triggered ability>'" — Dionus, Elvish Archdruid) is
  **not** a layer-3 case despite CR 612.1's mention of "text … granted… by
  other effects": RULE 613.1 puts ability-adding/removing in layer 6, and
  that's what these are, templated exactly like the layer-6 keyword grants
  below (`grant_keyword`) — just granting a mana ability or a full triggered
  ability instead of a bare keyword.
* **Layer 4** — type-changing effects ("… are creatures");
* **Layer 5** — colour-changing effects ("enchanted creature is black");
* **Layer 6** — ability-adding effects ("… have flying");
* **Layer 7** — power/toughness, in full sublayer order: 7a characteristic-
  defining P/T, 7b set, 7c counters, 7d modify (anthems), 7e switch.

Plus a non-layer bucket, **cost adjustments** (RULE 601.2f — "spells cost {N}
less"), which aren't part of 613 but are the other everyday static effect and
are computed here for the same recompute.

RULE 613.8's *dependency* system (an effect whose order depends on another
applying first) is modeled **only within layer 2** (`_order_control_effects`)
— confirmed by tracing every selector this engine has that a same-sublayer
effect could depend on: a `pt_cda`'s count-selectors (`_count_selector`) can
only *count* objects (creatures/lands/permanents/artifacts you control, cards
in a graveyard), never read another object's power/toughness, so no 7a
dependency is constructible at all; every other sublayer (pt_set/pt_mod/
pt_switch/type/color/ability) can't construct one either. Layer 2 is the one
real case: a controller-scoped `affects` ("creatures you control") can see a
different object set depending on whether another control-change ran first —
the textbook CR 613.8 example. Elsewhere, ordering is by timestamp only
(RULE 613.7, `_in_layer`).

`recompute(state)` resets every battlefield object's derived characteristics
and re-derives them from scratch, stamping the result — and a per-object,
per-layer **trace** — back onto each `GameObject` (`_derived_power`,
`_granted_keywords`, `_added_types`, `static_trace`). The engine calls it
whenever the board settles (state-based actions) and before serialization, so
reads of `obj.power`/`obj.is_creature`/`combat.keywords_of` see the live layer
stack.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional

from .effects import EffectRegistry, StaticAbility, TriggeredAbility

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


def has_subtype(obj: "GameObject", subtype: str) -> bool:
    """Public wrapper over `_has_subtype` for callers outside this module
    (e.g. `game_engine`'s "tap N untapped Elves you control" cost, RULE
    602.1 — `game/costs.py`'s ``tap_others``)."""
    return _has_subtype(obj, subtype)


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


def group_selector_objects(
    state: "GameState",
    controller_id: Optional[str],
    affects: str,
    params: Optional[dict[str, Any]] = None,
    src: Optional["GameObject"] = None,
) -> list["GameObject"]:
    """The battlefield objects an ``affects`` selector picks out.

    The selector vocabulary a static anthem's ``affects``/``params`` name
    (`affected_objects`, below); factored out so a one-shot group effect —
    e.g. a Saga chapter's "creatures you control get +N/+N until end of
    turn" (`PumpEffect.selector`) — can resolve the same "creatures you
    control"/subtype/colour/token/exclude-self vocabulary without a
    `StaticAbility` to hang it off. "you control" is scoped by
    ``controller_id``; with none given (a bare test fixture) those selectors
    match nothing. ``src`` is only needed for ``"self"``/``"attached_
    permanent"``/``"other_creatures_you_control"``/``exclude_self``.
    """
    params = params or {}
    battlefield = state.battlefield

    if affects == "self":
        result = [src] if src is not None and src in battlefield else []
    elif affects == "all_creatures":
        result = [o for o in battlefield if o.is_creature]
    elif affects == "all_permanents":
        result = list(battlefield)
    elif affects == "attached_permanent":
        host_id = getattr(src, "attached_to", None)
        result = [o for o in battlefield if host_id is not None and o.instance_id == host_id]
    elif controller_id is None:
        result = []
    elif affects == "creatures_you_control":
        result = [o for o in battlefield if o.is_creature and o.controller_id == controller_id]
    elif affects == "other_creatures_you_control":
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id and o is not src
        ]
    elif affects == "permanents_you_control":
        result = [o for o in battlefield if o.controller_id == controller_id]
    elif affects == "lands_you_control":
        result = [o for o in battlefield if o.is_land and o.controller_id == controller_id]
    else:
        result = []

    subtype = params.get("subtype")
    if subtype:
        result = [o for o in result if _has_subtype(o, str(subtype))]
    color = params.get("color")
    if color:  # colour-scoped anthem ("Black creatures get +1/+1", Bad Moon)
        result = [o for o in result if _has_color(o, list(color))]
    if params.get("tokens"):  # "creature tokens you control …" (RULE 111)
        result = [o for o in result if getattr(o, "is_token", False)]
    if params.get("exclude_self"):  # a global "Other creatures …" anthem
        result = [o for o in result if o is not src]

    # RULE 613.6-style conditional static: "as long as this [permanent]'s own
    # <counter> is in range" — Leveler's mutually-exclusive P/T/keyword tiers
    # (RULE 711, ``affects="self"``, gated on the source's own ``level``) and
    # a Class's cumulative per-level grants (RULE 716, gated on
    # ``class_level``, even though ``affects`` targets other permanents —
    # the *condition* is always about the ability's own source, never each
    # affected object's counters). Mirrors ``attached_permanent``'s "recompute
    # fresh every pass, empty list = inactive" shape.
    min_level = params.get("min_level")
    max_level = params.get("max_level")
    if min_level is not None or max_level is not None:
        counter_kind = params.get("level_counter") or "level"
        n = src.counters.get(counter_kind, 0) if src is not None else 0
        if (min_level is not None and n < min_level) or (max_level is not None and n > max_level):
            return []
    return result


def affected_objects(state: "GameState", ability: StaticAbility) -> list["GameObject"]:
    """The battlefield objects a static ability's ``affects`` selector picks
    out — a thin wrapper over `group_selector_objects` reading the selector,
    controller and params off the ability's own source (RULE 613).

    ``"attached_permanent"`` is the Aura/Equipment/Fortify/Reconfigure case —
    "enchanted/equipped creature", "fortified land" — resolved off the
    ability's own source's ``attached_to`` (RULE 303.4/301.5), not a
    controller-scoped set. It naturally yields nothing while unattached or
    once the source itself has left the battlefield (`_battlefield_static_
    abilities` only gathers abilities from objects currently in play).
    """
    src = ability.source
    controller = getattr(src, "controller_id", None)
    return group_selector_objects(state, controller, ability.affects, ability.params, src=src)


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


def _granted_trigger_condition(target: "GameObject", controllers_turn_only: bool):
    """The `TriggeredAbility.condition` for one object's granted ability.

    Each object under a "X have '<triggered ability>'" grant (Dionus, Elvish
    Archdruid) gets its *own* `TriggeredAbility` instance (see `recompute`'s
    layer-6 pass) — without this, every one of them would react to the
    triggering event regardless of which specific object it was about (e.g.
    one Elf being tapped would also untap every *other* Elf under the same
    anthem). Scoped by the event's own ``instance_id`` when it carries one
    (RULE 603.2's "this creature" is about *this* object specifically); an
    event shape with no ``instance_id`` isn't filtered by identity at all —
    there's no card in the pool granting a trigger off such an event today.
    """

    def condition(event: Any, context: Any) -> bool:
        event_instance = event.get("instance_id")
        if event_instance is not None and event_instance != target.instance_id:
            return False
        if controllers_turn_only and context.state.active_player.id != target.controller_id:
            return False
        return True

    return condition


def _apply_copy_layer(state: "GameState") -> None:
    """Layer 1: conditional "become a copy of target" effects (RULE 707.2,
    Vesuvan Shapeshifter-style "as long as untapped, ~ is a copy of …").

    Transition-only, unlike every other layer here: `copy_mechanics.
    become_copy` wipes and rebinds the object's whole ability set from the
    copied card, so re-running it every single pass regardless of whether
    anything changed would destroy per-turn bookkeeping on the copy's own
    granted triggered abilities. There is also deliberately no "ability
    disappeared -> revert" branch: per the real Vesuvan Shapeshifter ruling,
    a successful copy that lands on a creature without a similar ability
    *consumes* the very ability that caused it — the object simply stays
    what it currently is from then on, it doesn't revert on its own.
    """
    from . import copy_mechanics  # function-scoped: avoid an import cycle

    for src in state.battlefield:
        ability = next(
            (ab for ab in getattr(src, "static_effects", [])
             if isinstance(ab, StaticAbility) and ab.layer == "copy"),
            None,
        )
        if ability is None:
            continue  # nothing driving a copy/revert here right now

        condition_holds = not (ability.params.get("requires_untapped") and src.tapped)
        if not condition_holds:
            if src._copy_base is not None:
                copy_mechanics.restore_face(src, src._copy_base)
                src._copy_base = None
                src._copy_applied_target_id = None
            continue

        target_id = src.copy_target_id
        if target_id is not None and target_id != src._copy_applied_target_id:
            target = state.find_object(target_id)
            if target is not None and target in state.battlefield and target is not src:
                if src._copy_base is None:
                    src._copy_base = copy_mechanics.snapshot_face(src)
                copy_mechanics.become_copy(
                    src, target, ability.params.get("add_types"), ability.params.get("add_subtypes")
                )
                src._copy_applied_target_id = target_id


def _order_control_effects(abilities: list[StaticAbility]) -> list[StaticAbility]:
    """RULE 613.8, bounded to layer 2 (see module docstring for why only
    here): a controller-scoped ``affects`` selector ("creatures you
    control") can see a different object set depending on whether another
    control-change already ran, so those must apply *after* every direct-
    scoped ability (``self``/``attached_permanent``) regardless of
    timestamp. Two buckets, each still timestamp-ordered internally
    (``abilities`` is already `_in_layer`-sorted) — not a general
    dependency graph, since nothing else in this engine's vocabulary needs
    one.
    """
    direct = [a for a in abilities if a.affects in ("self", "attached_permanent")]
    scoped = [a for a in abilities if a not in direct]
    return direct + scoped


def recompute(state: "GameState") -> None:
    """Re-derive every battlefield permanent's characteristics (RULE 613)."""
    # Restore any controller a prior layer-2 pass changed, so this pass
    # re-applies control effects from a clean base (RULE 613.2, idempotent).
    for obj in state.battlefield:
        if obj._control_base is not None:
            obj.controller_id = obj._control_base
            obj._control_base = None
        obj.reset_derived()

    # -- Layer 1: copy effects (RULE 707) — must run before `abilities` is
    # gathered below, so a permanent that just became a copy has its freshly
    # rebound abilities picked up by every other layer in this same pass.
    _apply_copy_layer(state)

    abilities = [ab for ab in _battlefield_static_abilities(state) if ab.layer != "cost"]

    # -- Layer 2: control-changing effects (RULE 613.2).
    for ability in _order_control_effects(_in_layer(abilities, "control")):
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

    # -- Layer 3: text-changing effects (RULE 612), scoped (see module
    # docstring): word-substitution over `effective_oracle_text`, chained in
    # timestamp order if 2+ apply to the same object.
    for ability in _in_layer(abilities, "text"):
        replace = {str(k): str(v) for k, v in (ability.params.get("replace") or {}).items()}
        if not replace:
            continue
        for obj in affected_objects(state, ability):
            text = obj._derived_oracle_text if obj._derived_oracle_text is not None else (obj.card.oracle_text or "")
            for old, new in replace.items():
                text = re.sub(rf"\b{re.escape(old)}\b", new, text, flags=re.IGNORECASE)
            obj._derived_oracle_text = text
            _trace(obj, 3, _source_name(ability), f"text: {replace}")

    # -- Layer 4: type-changing effects (may add "creature" + animation P/T).
    animation_pt: dict[int, tuple[int, int]] = {}

    # RULE 702.151b: a Reconfigure permanent stops being a creature for as
    # long as it's attached to another creature (it's an Equipment while
    # attached). This is inherent to the permanent's own attached state, not
    # an "affects other objects" static ability, so it's special-cased here
    # rather than going through a `StaticAbility`/`affected_objects` pass.
    for obj in state.battlefield:
        if obj.attached_to is not None and "reconfigure" in (obj.parametric_keywords or {}):
            obj._removed_types.add("creature")

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

    # -- Layer 6: ability-adding effects (keyword / mana / triggered-ability
    # grants — RULE 613.7f). A grant is re-derived every pass exactly like
    # every other layer effect here, so it disappears on its own the moment
    # its source stops applying — no separate removal code (RULE 613.6).
    live_grant_keys: set[tuple[int, int]] = set()
    for ability in _in_layer(abilities, "ability"):
        keywords = ability.params.get("keywords", [])
        mana = ability.params.get("mana", [])
        trigger_event = ability.params.get("trigger_event")
        for obj in affected_objects(state, ability):
            if keywords:
                obj._granted_keywords.update(keywords)
                _trace(obj, 6, _source_name(ability), "gains " + ", ".join(keywords))
            if mana:
                obj._granted_mana.extend(mana)
                _trace(obj, 6, _source_name(ability), "gains a mana ability")
            if trigger_event:
                key = (id(ability), obj.instance_id)
                live_grant_keys.add(key)
                granted = state._granted_ability_cache.get(key)
                if granted is None:
                    granted = TriggeredAbility(
                        trigger_event=trigger_event,
                        effects=[
                            EffectRegistry.create(spec["type"], dict(spec.get("params", {})))
                            for spec in ability.params.get("grant_effects", [])
                        ],
                        condition=_granted_trigger_condition(
                            obj, bool(ability.params.get("controllers_turn_only", False))
                        ),
                        optional=bool(ability.params.get("optional", False)),
                        once_per_turn=bool(ability.params.get("once_per_turn", False)),
                        controller_id=obj.controller_id,
                        source=obj,
                        description=ability.description or "granted triggered ability",
                    )
                    state._granted_ability_cache[key] = granted
                else:
                    # `obj.controller_id` can change turn to turn (a control-
                    # changing effect, layer 2, resolves earlier this same
                    # pass) — keep the cached instance's controller current.
                    granted.controller_id = obj.controller_id
                obj._granted_triggered_abilities.append(granted)
                _trace(obj, 6, _source_name(ability), "gains a triggered ability")
    # Prune cache entries for relationships that no longer hold (the granting
    # ability left, or this object is no longer among its `affects`) — so a
    # later re-grant starts a fresh instance (fresh "once per turn" state),
    # rather than resurrecting old turn-tracking from an unrelated stretch of
    # the game.
    for key in list(state._granted_ability_cache):
        if key not in live_grant_keys:
            del state._granted_ability_cache[key]

    # Temporary "until end of turn" keyword grants from a resolved effect
    # ("target creature gains flying until end of turn") — same layer 6, but
    # sourced off the object rather than a battlefield static ability. Cleared
    # at cleanup (RULE 514.2).
    for obj in state.battlefield:
        if obj.temp_keywords:
            obj._granted_keywords.update(obj.temp_keywords)
            _trace(obj, 6, "Until-EOT", "gains " + ", ".join(sorted(obj.temp_keywords)))

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

    # 7d (cont.): temporary "until end of turn" P/T bonuses from a resolved
    # pump effect (Giant Growth) — same sublayer as anthems (RULE 613.4d);
    # addition commutes so within-layer order doesn't change the result.
    # Sourced off the object; cleared at cleanup (RULE 514.2).
    for obj in state.battlefield:
        if obj.instance_id in base and (obj.temp_power or obj.temp_toughness):
            base[obj.instance_id][0] += obj.temp_power
            base[obj.instance_id][1] += obj.temp_toughness
            p, t = base[obj.instance_id]
            _trace(obj, 7, "Until-EOT",
                   f"{_signed(obj.temp_power)}/{_signed(obj.temp_toughness)}", p, t)

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
        if p.get("keywords"):
            return "grants " + ", ".join(p.get("keywords", []))
        if p.get("mana"):
            return "grants a mana ability"
        if p.get("trigger_event"):
            return "grants a triggered ability"
        return "grants an ability"
    if ability.layer == "type":
        return "makes " + ", ".join(p.get("add_types", []))
    if ability.layer == "color":
        return "colours " + ", ".join(p.get("colors", []))
    if ability.layer == "control":
        return f"controls {ability.affects}"
    if ability.layer == "copy":
        return "is a copy of another target creature while untapped" if p.get("requires_untapped") else "is a copy of a target"
    if ability.layer == "text":
        return "rewrites text: " + ", ".join(f"{k}→{v}" for k, v in (p.get("replace") or {}).items())
    if ability.layer == "cost":
        return f"spells cost {{{p.get('generic', 0)}}} {'more' if p.get('increase') else 'less'}"
    return ability.affects
