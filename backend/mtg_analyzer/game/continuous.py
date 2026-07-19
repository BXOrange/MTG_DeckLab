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

    A layer-4 "type overwrite" static (RULE 613.5 — `_derived_subtypes`,
    e.g. Blood Moon's "Nonbasic lands are Mountains") takes priority when
    set: the object's *printed* subtypes (and Changeling) no longer apply at
    all once its subtype set has been wholesale replaced.
    """
    override = getattr(obj, "_derived_subtypes", None)
    if override is not None:
        return subtype.lower() in {s.lower() for s in override}
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


#: Printed card-type word → the `Card` boolean flag it reads (RULE 300-ish
#: type vocabulary) — the small, closed set the "opponent-scoped enters-
#: tapped"/"activation prohibition"/"type overwrite" static families narrow
#: their `affects` selector by (`card_type` param, `parser.oracle.catalogue.
#: static_handlers._CARD_TYPE_WORDS`).
_CARD_TYPE_ATTRS: dict[str, str] = {
    "artifact": "is_artifact",
    "creature": "is_creature",
    "enchantment": "is_enchantment",
    "land": "is_land",
    "planeswalker": "is_planeswalker",
}


def _has_card_type(obj: "GameObject", card_type: str) -> bool:
    """Whether ``obj``'s *printed* card is of ``card_type`` — reads the
    `Card` flags directly (not layer-4 `_added_types`), since every static
    family that uses this filters on the entering/affected object's own
    printed identity (an artifact staying an artifact regardless of any
    other layer effect in play). ``"permanent"`` (RULE 110.1) always
    matches — everything on the battlefield is one."""
    if card_type == "permanent":
        return True
    attr = _CARD_TYPE_ATTRS.get(card_type)
    return bool(attr and getattr(obj.card, attr, False))


def _is_nonbasic(obj: "GameObject") -> bool:
    """RULE 205.4a: a land with no "Basic" supertype (the same substring
    check `game/targeting.py`'s "nonbasic land" filter already uses)."""
    return "basic" not in obj.card.type_line.lower()


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
    # RULE 702.26c: a phased-out permanent is treated as though it doesn't
    # exist — invisible to every static-ability selector below.
    battlefield = state.permanents()

    if affects == "self":
        result = [src] if src is not None and src in battlefield else []
    elif affects == "all_creatures":
        result = [o for o in battlefield if o.is_creature]
    elif affects == "all_permanents":
        result = list(battlefield)
    elif affects == "attached_permanent":
        host_id = getattr(src, "attached_to", None)
        result = [o for o in battlefield if host_id is not None and o.instance_id == host_id]
    elif affects == "all_lands":
        result = [o for o in battlefield if o.is_land]
    elif affects == "opponents_permanents":
        # "Artifacts your opponents control enter tapped." (Manglehorn) —
        # the mirror image of every "you control" selector below: everyone
        # *except* the ability's own source's controller. Unlike those,
        # ``controller_id`` here is the reference point ("you"), not a
        # membership filter, so it still needs its own None-guard rather
        # than falling into the shared ``elif controller_id is None`` below.
        result = [] if controller_id is None else [
            o for o in battlefield if o.controller_id not in (None, controller_id)
        ]
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
    elif affects == "nonland_permanents_you_control":
        # "Untap all nonland permanents you control." (Dramatic Reversal)
        result = [
            o for o in battlefield
            if not o.is_land and o.controller_id == controller_id
        ]
    elif affects == "lands_you_control":
        result = [o for o in battlefield if o.is_land and o.controller_id == controller_id]
    elif affects == "artifacts_you_control":
        result = [o for o in battlefield if o.card.is_artifact and o.controller_id == controller_id]
    elif affects == "enchanted_or_equipped_creatures_you_control":
        # Halvar, God of Battle's "creatures you control that are enchanted
        # or equipped" — a creature you control with *anything* (Aura or
        # Equipment) currently attached to it.
        attached_hosts = {o.attached_to for o in battlefield if o.attached_to is not None}
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id and o.instance_id in attached_hosts
        ]
    else:
        result = []

    if params.get("active_player_only") and (
        state.active_player is None or state.active_player.id != controller_id
    ):
        # "During your turn, creatures you control have first strike"
        # (Nahiri, Storm of Stone) — RULE 613.6-style conditional static,
        # gated on whose turn it currently is rather than any counter/board
        # count; checked before the subtype/color/tokens narrowing below
        # (an inactive gate means nothing here matches at all).
        return []

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
    card_type = params.get("card_type")
    if card_type:  # "Artifacts your opponents control…", "Nonbasic lands are…"
        result = [o for o in result if _has_card_type(o, str(card_type))]
    if params.get("nonbasic"):  # "Nonbasic lands …" (RULE 205.4a)
        result = [o for o in result if _is_nonbasic(o)]

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

    # A Metalcraft/Threshold-style board-count condition ("as long as you
    # control three or more artifacts") — unlike `min_level`/`max_level`
    # above (the source's own *counter*), this reads a `count_selector`
    # over the whole board (Indomitable Archangel's Metalcraft).
    min_count_selector = params.get("min_count_selector")
    min_count = params.get("min_count")
    if min_count_selector is not None and min_count is not None:
        if count_selector(state, controller_id, str(min_count_selector)) < min_count:
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
    duration: str = "static",
) -> None:
    # ``duration`` classifies how long the effect lasts, for the board's
    # per-card effect summary: ``"static"`` (a static ability / Aura /
    # Equipment / anthem — lasts while its source stays in play),
    # ``"permanent"`` (counters — RULE 122, they don't wear off on their own),
    # or ``"end_of_turn"`` (a resolved "until end of turn" pump/keyword grant,
    # cleared at cleanup — RULE 514.2).
    obj.static_trace.append(
        {
            "layer": layer,
            "source": label,
            "description": description,
            "power": power,
            "toughness": toughness,
            "duration": duration,
        }
    )


def _battlefield_static_abilities(state: "GameState") -> list[StaticAbility]:
    # RULE 702.26c: a phased-out permanent's static abilities don't apply —
    # `state.permanents()` already excludes it from being a source.
    return [
        ab
        for src in state.permanents()
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


def count_selector(state: "GameState", controller_id: Optional[str], selector: str) -> int:
    """Evaluate a "number of X" count selector, scoped to ``controller_id``.

    The vocabulary a layer-7a characteristic-defining P/T (RULE 613.7c/604.3
    — a ``*/*`` creature like Nightmare's Swamps, a graveyard-count beater)
    is defined by; also reused by a ward cost's own "where X is …"
    definition (RULE 702.21b, `costs.ActivationCost.x_selector`) — one
    authored list rather than two. "you control"/"your graveyard" is scoped
    to ``controller_id``; ``None`` (no controller context) matches nothing.
    """
    bf = state.battlefield
    if selector == "creatures_you_control":
        return sum(1 for o in bf if o.is_creature and o.controller_id == controller_id)
    if selector == "lands_you_control":
        return sum(1 for o in bf if o.is_land and o.controller_id == controller_id)
    if selector == "permanents_you_control":
        return sum(1 for o in bf if o.controller_id == controller_id)
    if selector == "artifacts_you_control":
        return sum(1 for o in bf if o.card.is_artifact and o.controller_id == controller_id)
    if selector == "artifacts_and_or_enchantments_you_control":
        return sum(
            1 for o in bf
            if (o.card.is_artifact or o.card.is_enchantment) and o.controller_id == controller_id
        )
    if selector == "artifacts_and_or_enchantments_opponents_control":
        # "the number of artifacts and enchantments your opponents control"
        # (Dockside Extortionist) — the mirror image of the "you control"
        # entry above: everyone *except* the reference controller, same
        # "opponents" idiom `group_selector_objects`'s own
        # ``"opponents_permanents"`` uses.
        return sum(
            1 for o in bf
            if (o.card.is_artifact or o.card.is_enchantment)
            and o.controller_id not in (None, controller_id)
        )
    if selector == "cards_in_your_graveyard":
        try:
            player = state.player_by_id(controller_id) if controller_id else None
        except KeyError:
            player = None
        return len(player.graveyard) if player is not None else 0
    return 0


def _count_selector(state: "GameState", ability: StaticAbility, selector: str) -> int:
    """`count_selector`, scoped to a `StaticAbility`'s own source's
    controller (RULE 613.7c/604.3) — see `count_selector` for the
    vocabulary."""
    return count_selector(state, getattr(ability.source, "controller_id", None), selector)


def _equipment_attached_count(state: "GameState", obj: "GameObject") -> int:
    """How many Equipment are currently attached to ``obj`` itself — a
    *per-object* count (Bruenor Battlehammer's "for each Equipment attached
    to it"), unlike every `count_selector` entry above (one number shared by
    every object a static ability affects)."""
    return sum(
        1 for o in state.battlefield
        if o.attached_to == obj.instance_id and "equipment" in o.card.type_line.lower()
    )


def _pt_mod_count(state: "GameState", ability: StaticAbility, obj: "GameObject", selector: str) -> int:
    """A layer-7d anthem's per-unit multiplier — either a per-object count
    (``"equipment_attached_to_self"``), the ability's own source's counters
    (``"plus_one_counters_on_self"`` — Lion Sash's "for each +1/+1 counter
    on this Equipment"), or the ordinary controller-scoped `count_selector`
    vocabulary (Blackblade Reforged's "for each land you control",
    Nettlecyst's "for each artifact and/or enchantment you control")."""
    if selector == "equipment_attached_to_self":
        return _equipment_attached_count(state, obj)
    if selector == "plus_one_counters_on_self":
        return getattr(ability.source, "plus_one_counters", 0)
    return _count_selector(state, ability, selector)


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
        set_subtypes = ability.params.get("set_subtypes")
        power, toughness = ability.params.get("power"), ability.params.get("toughness")
        for obj in affected_objects(state, ability):
            for type_name in added:
                obj._added_types.add(type_name)
            if set_subtypes is not None:
                # RULE 613.5 full overwrite ("Nonbasic lands are Mountains.")
                # — replaces the subtype set outright, unlike `add_types`
                # above (which only adds "creature" alongside whatever the
                # object already was).
                obj._derived_subtypes = set(set_subtypes)
            if power is not None and toughness is not None:
                animation_pt[obj.instance_id] = (power, toughness)
            label = ", ".join(added) if added else ", ".join(set_subtypes or [])
            _trace(obj, 4, _source_name(ability), f"becomes {label}")

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
        remove_keywords = ability.params.get("remove_keywords", [])
        lose_all = bool(ability.params.get("lose_all_abilities", False))
        mana = ability.params.get("mana", [])
        trigger_event = ability.params.get("trigger_event")
        for obj in affected_objects(state, ability):
            if lose_all:
                # RULE 613.7f (Humility, Dress Down): strip *every* ability —
                # keywords go via `_obj_keywords`, triggered/activated abilities
                # are gated at fire/activate time on this flag.
                obj._loses_all_abilities = True
                _trace(obj, 6, _source_name(ability), "loses all abilities")
            if keywords:
                obj._granted_keywords.update(keywords)
                _trace(obj, 6, _source_name(ability), "gains " + ", ".join(keywords))
            if remove_keywords:
                obj._removed_keywords.update(remove_keywords)
                _trace(obj, 6, _source_name(ability), "loses " + ", ".join(remove_keywords))
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
            # Attribute each keyword to its source spell/ability where the
            # resolved effect recorded one (`temp_effects`); keywords granted
            # by paths that don't (haste/first-strike/indestructible helpers)
            # fall through to a single generic "Until-EOT" line.
            attributed: set[str] = set()
            for entry in obj.temp_effects:
                kws = entry.get("keywords") or []
                if kws:
                    attributed.update(kws)
                    _trace(obj, 6, entry.get("source") or "Until-EOT",
                           "gains " + ", ".join(sorted(kws)), duration="end_of_turn")
            residual = obj.temp_keywords - attributed
            if residual:
                _trace(obj, 6, "Until-EOT", "gains " + ", ".join(sorted(residual)),
                       duration="end_of_turn")

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
                _trace(obj, 7, "+1/+1-Marken", f"{_signed(counters)}/{_signed(counters)}",
                       p, t, duration="permanent")

    # 7d: modify (but don't set) power/toughness — anthems, including a
    # per-count anthem ("+1/+1 for each land you control", Blackblade
    # Reforged/Nettlecyst; "+2/+0 for each Equipment attached to it", Bruenor
    # Battlehammer) — `power`/`toughness` become the *per-unit* amount when
    # `power_count`/`toughness_count` is set, multiplied by that count
    # instead of added as a flat delta.
    for ability in _in_layer(abilities, "pt_mod"):
        d_power = ability.params.get("power", 0)
        d_toughness = ability.params.get("toughness", 0)
        p_sel = ability.params.get("power_count")
        t_sel = ability.params.get("toughness_count")
        for obj in affected_objects(state, ability):
            if obj.instance_id in base:
                power = d_power * _pt_mod_count(state, ability, obj, str(p_sel)) if p_sel else d_power
                toughness = (
                    d_toughness * _pt_mod_count(state, ability, obj, str(t_sel)) if t_sel else d_toughness
                )
                base[obj.instance_id][0] += power
                base[obj.instance_id][1] += toughness
                p, t = base[obj.instance_id]
                _trace(obj, 7, _source_name(ability), f"{_signed(power)}/{_signed(toughness)}", p, t)

    # 7d (cont.): temporary "until end of turn" P/T bonuses from a resolved
    # pump effect (Giant Growth) — same sublayer as anthems (RULE 613.4d);
    # addition commutes so within-layer order doesn't change the result.
    # Sourced off the object; cleared at cleanup (RULE 514.2).
    for obj in state.battlefield:
        if obj.instance_id not in base or not (obj.temp_power or obj.temp_toughness):
            continue
        # Attribute the bonus to each source that recorded one; addition
        # commutes, so applying them one at a time gives the same total while
        # the trace can name Giant Growth / Monstrous Rage individually.
        pt_entries = [e for e in obj.temp_effects if e.get("power") or e.get("toughness")]
        for entry in pt_entries:
            ep, et = entry.get("power", 0), entry.get("toughness", 0)
            base[obj.instance_id][0] += ep
            base[obj.instance_id][1] += et
            p, t = base[obj.instance_id]
            _trace(obj, 7, entry.get("source") or "Until-EOT",
                   f"{_signed(ep)}/{_signed(et)}", p, t, duration="end_of_turn")
        # Any bonus from a path that didn't record a source (older effects)
        # still shows, as one generic residual line.
        residual_p = obj.temp_power - sum(e.get("power", 0) for e in pt_entries)
        residual_t = obj.temp_toughness - sum(e.get("toughness", 0) for e in pt_entries)
        if residual_p or residual_t:
            base[obj.instance_id][0] += residual_p
            base[obj.instance_id][1] += residual_t
            p, t = base[obj.instance_id]
            _trace(obj, 7, "Until-EOT",
                   f"{_signed(residual_p)}/{_signed(residual_t)}", p, t, duration="end_of_turn")

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


def _cost_static_amount(ability: StaticAbility, state: "GameState", controller_id: Optional[str]) -> int:
    """Signed generic-mana delta for one "cost" static (positive = reduction).

    ``params.get("per")`` is an optional `count_selector` name for a
    per-count scaling reduction (Delve's "for each card in your graveyard",
    Affinity's "for each artifact you control") — the same "multiply a base
    amount by a board count" shape a layer-7d anthem's ``_pt_mod_count``
    already uses, reused here rather than reinvented.
    """
    amount = ability.params.get("generic", 0)
    per = ability.params.get("per")
    if per:
        amount *= count_selector(state, controller_id, per)
    return -amount if ability.params.get("increase") else amount


def _spell_type_matches(obj: "GameObject", spell_type: str) -> bool:
    """Whether the spell ``obj`` matches a `cost_reduction` static's
    ``spell_type`` filter ("noncreature spells cost {1} more…", Thalia,
    Guardian of Thraben/Thorn of Amethyst/Vryn Wingmare) — ``"noncreature"``
    is its own case (no ``Card.is_noncreature`` flag to read), everything
    else is a plain `_has_card_type` lookup on the object being cast."""
    if spell_type == "noncreature":
        return not obj.card.is_creature
    return _has_card_type(obj, spell_type)


def cost_reduction_for(
    state: "GameState", player: "Player", obj: Optional["GameObject"] = None
) -> tuple[int, list[dict[str, Any]]]:
    """Net generic-mana reduction for a spell ``player`` casts (RULE 601.2f).

    Sums "cost {N} less" statics and subtracts "cost {N} more" ones that apply
    to the player's spells, returning ``(net_reduction, contributors)`` where a
    positive reduction lowers the generic cost (never below zero, applied by
    the caller) and ``contributors`` describes each for the UI. Only reads
    *battlefield* statics ("permanents you control cost less") — a reduction
    printed on the spell card itself (Delve/Affinity) is `self_cost_reduction_for`.

    ``obj`` is the spell actually being cast/previewed — required to evaluate
    a ``spell_type``-filtered static ("noncreature spells cost {1} more to
    cast", RULE 601.2f — Thalia/Thorn of Amethyst/Vryn Wingmare-shaped); a
    caller that omits it (``None``, the pre-existing default) simply never
    matches such a static, unaffected by this parameter's addition.
    """
    net = 0
    contributors: list[dict[str, Any]] = []
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cost":
            continue
        if ability.params.get("scope") == "activation":
            # Power Artifact-shaped — an *activated ability's* own cost, not
            # a spell's cast cost; see `activation_cost_reduction_for`.
            continue
        if ability.affects == "your_spells" and getattr(ability.source, "controller_id", None) != player.id:
            continue
        spell_type = ability.params.get("spell_type")
        if spell_type and (obj is None or not _spell_type_matches(obj, spell_type)):
            continue
        signed = _cost_static_amount(ability, state, player.id)
        net += signed
        contributors.append(
            {
                "source": _source_name(ability),
                "amount": signed,
                "description": f"Spells cost {{{abs(signed)}}} {'more' if signed < 0 else 'less'}",
            }
        )
    return net, contributors


def self_cost_reduction_for(obj: "GameObject", state: "GameState") -> tuple[int, list[dict[str, Any]]]:
    """Net generic-mana reduction from a "cost" static printed on ``obj``
    itself (Delve/Affinity-shaped: "This spell costs {1} less to cast for
    each ...") while ``obj`` is still in hand/graveyard/etc.

    `_battlefield_static_abilities` only scans `state.battlefield`, so a
    card that hasn't been cast yet needs its own static read straight off
    ``obj.static_effects`` — the binder attaches a spell's own statics there
    regardless of zone, same as any other static.
    """
    net = 0
    contributors: list[dict[str, Any]] = []
    controller_id = getattr(obj, "controller_id", None)
    for ability in getattr(obj, "static_effects", []):
        if not isinstance(ability, StaticAbility) or ability.layer != "cost" or ability.affects != "self":
            continue
        signed = _cost_static_amount(ability, state, controller_id)
        net += signed
        contributors.append(
            {
                "source": _source_name(ability),
                "amount": signed,
                "description": f"Costs {{{abs(signed)}}} {'more' if signed < 0 else 'less'} to cast",
            }
        )
    return net, contributors


def activation_cost_reduction_for(state: "GameState", source: "GameObject") -> tuple[int, int]:
    """Net generic-mana reduction for *activating* ``source``'s own
    activated ability (Power Artifact-shaped "Enchanted artifact's
    activated abilities cost {2} less to activate.") — the activation-cost
    analogue of `cost_reduction_for` (a *spell's* cast cost); consulted by
    `GameEngine._reduced_activation_mana`.

    Only a ``"cost"``-layer static with ``params["scope"] == "activation"``
    counts (`cost_reduction_for` explicitly skips these, so a static never
    double-applies to both a spell's cast cost and an ability's activation
    cost). Only the ``affects="attached_permanent"`` scope is implemented
    today — the one shape the pool needs; an unscoped "activated abilities
    you control cost less" variant would need its own `affects` branch here,
    not yet built since nothing needs it.

    Returns ``(net_reduction, floor)`` where ``floor`` is the highest
    "can't reduce the mana in that cost to less than N mana" clause among
    the contributing statics (0 — no floor — if none set one).
    """
    net = 0
    floor = 0
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cost" or ability.params.get("scope") != "activation":
            continue
        if ability.affects == "attached_permanent":
            if getattr(ability.source, "attached_to", None) != source.instance_id:
                continue
        else:
            continue
        net += int(ability.params.get("generic", 0))
        floor = max(floor, int(ability.params.get("min_total", 0)))
    return net, floor


def activation_prohibited(state: "GameState", source: "GameObject") -> bool:
    """Whether a board-wide static ("Activated abilities of artifacts can't
    be activated." — RULE 602, Collector Ouphe/Stony Silence/Null Rod)
    silences ``source``'s activated abilities right now.

    Consulted by `GameEngine.can_activate` — the single choke point both
    `activate_ability`'s validation and `legal_actions`'s offer list already
    go through, so one check here covers both. Reuses the ordinary
    ``affects``/``card_type`` selector vocabulary (`affected_objects`) rather
    than a bespoke predicate: the default ``affects="all_permanents"`` is
    global (not scoped to the prohibiting permanent's own controller) and
    carries no self-exemption, matching these three cards' plain wording —
    Null Rod is itself an artifact and silences its own (non-existent here,
    but any future artifact-with-abilities') activated abilities too.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer == "activation_prohibition" and source in affected_objects(state, ability):
            return True
    return False


def max_spells_per_turn(state: "GameState") -> Optional[int]:
    """The most restrictive "Each player can't cast more than N spells each
    turn." cap in play (RULE 601-area — Eidolon of Rhetoric/Rule of Law/
    Archon of Emeria), or ``None`` if no such static applies.

    Global and player-agnostic by construction (all three seed cards say
    "each player", not "each opponent"/"you") — every player is held to the
    same, most-restrictive cap; `GameEngine.can_cast` compares it against
    `GameState.spells_cast_this_turn`.
    """
    limits = [
        ab.params.get("max_per_turn")
        for ab in _battlefield_static_abilities(state)
        if ab.layer == "cast_limit" and ab.params.get("max_per_turn") is not None
    ]
    return min(limits) if limits else None


def max_draws_per_turn(state: "GameState") -> Optional[int]:
    """The most restrictive "Each player can't draw more than N cards each
    turn." cap in play (RULE 121.5-adjacent — Spirit of the Labyrinth), or
    ``None`` if no such static applies. The draw-side mirror of
    `max_spells_per_turn`; `RulesEngine._single_draw` compares it against
    `GameState.cards_drawn_this_turn`.
    """
    limits = [
        ab.params.get("max_per_turn")
        for ab in _battlefield_static_abilities(state)
        if ab.layer == "draw_limit" and ab.params.get("max_per_turn") is not None
    ]
    return min(limits) if limits else None


def has_no_untap_static(state: "GameState", obj: "GameObject") -> bool:
    """Whether ``obj`` is under a "doesn't untap during your untap step"
    static (RULE 502.3-adjacent — Basalt Monolith/Grim Monolith/Mana Vault's
    own self-restriction, or an Aura/Equipment's grant onto its host —
    Paralyzing Grasp's "enchanted creature doesn't untap during its
    controller's untap step").

    Goes through the ordinary ``affects``/selector machinery
    (`affected_objects`) like every other static family here, so both the
    self-scoped and ``"attached_permanent"``-scoped printings resolve the
    same way. Consulted by `GameEngine._step_untap` — a separate "{N}: Untap
    this artifact." activated ability (Basalt/Grim Monolith) or an "you may
    pay {4}. If you do, untap" trigger (Mana Vault) is an unrelated code path
    (an ordinary ``untap`` one-shot effect) and isn't affected by this
    restriction at all.
    """
    return any(
        ab.layer == "no_untap" and obj in affected_objects(state, ab)
        for ab in _battlefield_static_abilities(state)
    )


def untap_cap_for_lands(state: "GameState") -> Optional[int]:
    """The global cap on how many lands *any* player may untap during their
    untap step this turn (RULE 502.3-adjacent, Winter Orb-shaped: "As long
    as this artifact is untapped, players can't untap more than one land
    during their untap steps.") — ``None`` when no such static is currently
    active.

    Unlike `has_no_untap_static` (a single permanent's own restriction) or
    `enters_tapped_from_static` (a board-wide but ownership-scoped effect),
    this is a flat, unscoped cap that applies to *every* player's untap
    step identically, gated on the static's own source currently being
    untapped ("as long as ~ is untapped" — checked live, not the source's
    controller/affected-set machinery every other static family here
    uses). Two+ simultaneous instances don't stack (RULE 613's "the most
    restrictive" isn't quite right either — real Magic just has each
    Orb apply its own 1-land cap independently, so the effective cap is
    whichever is *smallest*), hence ``min()`` rather than summing.
    """
    caps = [
        ability.params.get("count", 1)
        for ability in _battlefield_static_abilities(state)
        if ability.layer == "untap_cap" and ability.source is not None and not ability.source.tapped
    ]
    return min(caps) if caps else None


def trigger_suppressed(state: "GameState", event: Any) -> bool:
    """Whether a global static ("Creatures entering don't cause abilities to
    trigger." — RULE 603, Tocatli Honor Guard/Hushwing Gryff/Torpor Orb)
    blocks every triggered ability from firing off ``event`` right now.

    Checked once per event (`RulesEngine._collect_triggers`, the single
    choke point both a permanent's own `triggered_abilities` and a layer-6
    `granted_triggered_abilities` go through) rather than per-ability —
    cheaper, and it naturally covers *both* the entering creature's own ETB
    trigger and any other permanent's "whenever a creature enters" trigger
    reacting to the same event, matching the real card's scope. Global: unlike
    every ``affects`` selector above, this isn't scoped to the static's own
    controller — Torpor Orb silences ETB triggers for *every* player's
    creatures, not just its controller's.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "trigger_prohibition":
            continue
        if ability.params.get("event") != event.type:
            continue
        subject_type = ability.params.get("subject_type")
        if subject_type and subject_type not in (event.get("object_types") or []):
            continue
        return True
    return False


def enters_tapped_from_static(state: "GameState", obj: "GameObject") -> bool:
    """Whether a board-wide static ("Artifacts your opponents control enter
    tapped." — RULE 614.1, Manglehorn/Dauntless Dismantler/Archon of
    Emeria-shaped; or an unscoped "Artifacts and lands enter tapped." — Root
    Maze-shaped, ``affects="all_permanents"``, no ownership restriction at
    all) forces ``obj`` to enter tapped right now.

    Distinct from `ability_catalogue.enters_tapped` (a card's own printed
    tapped-entry clause about *itself*) — this is a *different* permanent's
    standing effect. Checked at the moment ``obj`` is about to join the
    battlefield (`RulesEngine._resolve_permanent_spell`/token creation),
    before it's actually added to `state.battlefield` — so unlike every
    other consult in this module, it can't go through `affected_objects`
    (which only ever scans *existing* battlefield membership); the
    ``opponents_permanents``/``all_permanents``/``card_type``/``nonbasic``
    filters are applied to ``obj`` directly instead, duplicating that small
    slice of `group_selector_objects`'s narrowing logic rather than the
    whole battlefield-scanning shape.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "enters_tapped":
            continue
        if ability.affects != "all_permanents":
            controller = getattr(ability.source, "controller_id", None)
            if controller is None or obj.controller_id in (None, controller):
                continue  # not "your opponents" from the static's own perspective
        card_type = ability.params.get("card_type")
        if card_type and not _has_card_type(obj, str(card_type)):
            continue
        if ability.params.get("nonbasic") and not _is_nonbasic(obj):
            continue
        return True
    return False


#: Static "layer" buckets that aren't a real RULE 613 layer at all (each
#: `StaticAbility.LAYER_NUMBERS.get(..., 99)` defaults to the same numeric
#: bucket "cost" already used) — shown as their own named ``kind`` in the
#: UI's layer-trace panel rather than a bare "99", same treatment "cost"
#: already got before any of these existed.
_NON_RULE_613_LAYERS: frozenset[str] = frozenset(
    {"cost", "no_untap", "enters_tapped", "activation_prohibition", "cast_limit", "draw_limit",
     "trigger_prohibition", "untap_cap"}
)


def active_static_abilities(state: "GameState") -> list[dict[str, Any]]:
    """A flat summary of every static ability in play, for the UI's panel."""
    summary: list[dict[str, Any]] = []
    for ability in _battlefield_static_abilities(state):
        summary.append(
            {
                "source": _source_name(ability),
                "layer": ability.layer if ability.layer in _NON_RULE_613_LAYERS else ability.layer_number,
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
        if p.get("set_subtypes"):
            return "becomes " + "/".join(p["set_subtypes"])
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
        prefix = f"{p['spell_type']} spells" if p.get("spell_type") else "spells"
        return f"{prefix} cost {{{p.get('generic', 0)}}} {'more' if p.get('increase') else 'less'}"
    if ability.layer == "activation_prohibition":
        scope = f"{p['card_type']}s'" if p.get("card_type") else ""
        return f"{scope} activated abilities can't be activated".strip()
    if ability.layer == "cast_limit":
        return f"each player can't cast more than {p.get('max_per_turn', 1)} spell(s) each turn"
    if ability.layer == "draw_limit":
        return f"each player can't draw more than {p.get('max_per_turn', 1)} card(s) each turn"
    if ability.layer == "no_untap":
        return "doesn't untap during its controller's untap step"
    if ability.layer == "trigger_prohibition":
        subject = f"{p['subject_type']}s" if p.get("subject_type") else "objects"
        return f"{subject} entering don't cause abilities to trigger"
    if ability.layer == "enters_tapped":
        scope = f"nonbasic {p['card_type']}" if p.get("nonbasic") and p.get("card_type") else p.get("card_type", "permanents")
        who = "" if ability.affects == "all_permanents" else "your opponents control "
        return f"{scope}s {who}enter tapped"
    if ability.layer == "untap_cap":
        return f"players can't untap more than {p.get('count', 1)} land(s) during their untap steps"
    return ability.affects
