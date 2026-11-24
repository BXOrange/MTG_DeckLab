"""ENG-68: granted Equip abilities (RULE 702.6, 113.6, 613.6).

"Clues you control are Equipment in addition to their other types and have "Equipped creature gets +2/+0" and equip {2}."
(Armed with Proof, Arterial Alchemy, Dan Lewis, Gemcutter Buccaneer, Bram, Baguette Brawler, Bludgeon Brawl) is one
continuous effect in three layers: a layer-4 type addition (Equipment), and two layer-6 grants (the quoted static and
an Equip activated ability). Two pieces live here:

* the *group lock* (RULE 613.6): the set of objects such an effect applies to is fixed when it starts to apply in its
  first layer, so the layer-6 grants reach exactly the objects the layer-4 part made Equipment. Without it Dan Lewis's
  "non-Equipment artifacts" selector would exclude every artifact it had just turned into an Equipment by layer 6;
* the *granted Equip ability* itself, built once per receiving object and cached like every other layer-6 grant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .costs import parse_activation_cost

if TYPE_CHECKING:  # pragma: no cover
    from ..models.game.game_object import GameObject
    from .game_state import GameState

#: The ``attach_kind`` of an Equip ability's cost (RULE 702.6a); what Puresteel Paladin-style cost statics test.
EQUIP_ATTACH_KIND = "equip"

#: The one dynamic Equip cost the grammar models: "equip {X}, where X is that artifact's mana value" (Bludgeon Brawl).
EQUIP_COST_SOURCE_MANA_VALUE = "source_mana_value"


def record_locked_group(state: "GameState", ability: Any, objects: list["GameObject"]) -> None:
    """RULE 613.6: remember who a tagged layer-4 effect affected, for the layer-6 parts of the same effect."""
    tag = ability.params.get("locks_group_tag")
    if not tag:
        return
    locked = getattr(state, "_locked_group_members", None)
    if locked is None:
        locked = state._locked_group_members = {}
    locked[(ability.source.instance_id, str(tag))] = [o.instance_id for o in objects]


def locked_group_objects(state: "GameState", ability: Any) -> list["GameObject"]:
    """The objects a layer-6 part of a tagged effect applies to: those the layer-4 part affected this pass."""
    key = (ability.source.instance_id, str(ability.params["locked_group_tag"]))
    ids = set((getattr(state, "_locked_group_members", None) or {}).get(key, ()))
    return [o for o in state.battlefield if o.instance_id in ids]


def _equip_cost_text(entry: dict[str, Any], obj: "GameObject") -> Optional[str]:
    """The mana cost text of one granted Equip entry for ``obj`` (``None`` if the grant is malformed)."""
    if entry.get("cost_from") == EQUIP_COST_SOURCE_MANA_VALUE:
        # Bludgeon Brawl: "equip {X}" where X is the artifact's own mana value, re-read every recompute (RULE 202.3).
        return "{" + str(int(getattr(obj, "mana_value", 0) or 0)) + "}"
    cost = entry.get("cost")
    return str(cost) if cost else None


def grant_equip_abilities(
    state: "GameState", ability: Any, obj: "GameObject", entries: list[dict[str, Any]], live_grant_keys: set,
) -> list[Any]:
    """Build (or reuse) one RULE 702.6a Equip activated ability on ``obj`` per entry and return them.

    Each entry is ``{"cost": "{2}"}`` or ``{"cost_from": "source_mana_value"}``, optionally ``"qualifier"`` (a creature
    subtype: "Equip Pirate {1}" may only attach to a Pirate, RULE 702.6a/702.6c). RULE 113.2c / 702.6d: every grant is its
    own ability, separate from any printed Equip on the same object. The cache key carries the cost so a changed
    amount mints a fresh ability and the stale one is pruned with the other grant keys."""
    from .effects.attachments_transforms import AttachEffect
    from .effects.core import ActivatedAbility

    built: list[Any] = []
    for index, entry in enumerate(entries):
        cost_text = _equip_cost_text(entry, obj)
        if cost_text is None:
            continue
        qualifier = str(entry.get("qualifier") or "")
        key = (id(ability), obj.instance_id, "equip", index, cost_text, qualifier)
        live_grant_keys.add(key)
        granted = state._granted_ability_cache.get(key)
        if granted is None:
            cost = parse_activation_cost(cost_text)
            # RULE 702.6a: Equip is activated only as a sorcery and never taps its source.
            cost.sorcery_speed_only = True
            cost.attach_kind = EQUIP_ATTACH_KIND
            cost.targets_own_creature = True
            effect = AttachEffect(
                target_kind="creature_you_control",
                creature_filter={"subtype": qualifier} if qualifier else None,
            )
            label = f"Equip {qualifier.title() + ' ' if qualifier else ''}{cost_text}"
            granted = ActivatedAbility(
                effects=[effect], cost=cost, source=obj, description=label, attach_kind=EQUIP_ATTACH_KIND,
            )
            state._granted_ability_cache[key] = granted
        built.append(granted)
    return built


def grant_crew_abilities(
    state: "GameState", ability: Any, obj: "GameObject", entries: list[dict[str, Any]], live_grant_keys: set,
) -> list[Any]:
    """RULE 702.122a / 113.2c: one real Crew N activated ability per entry, built by the printed Crew binding so the
    cost, the "becomes an artifact creature until end of turn" effect and the crewed event are the same as a printed
    Crew's; cached per (grant, object, N) and separate from any printed Crew on the object."""
    from .binding.core import _crew_activated_ability  # function-scoped: binding imports this module's callers
    from ..parser.oracle.spec import AbilitySpec

    built: list[Any] = []
    for index, entry in enumerate(entries):
        n = int(entry.get("n") or 0)
        if n <= 0:
            continue
        key = (id(ability), obj.instance_id, "crew", index, n)
        live_grant_keys.add(key)
        granted = state._granted_ability_cache.get(key)
        if granted is None:
            granted = _crew_activated_ability(obj, AbilitySpec("static"), {"n": n})
            if granted is None:
                continue
            state._granted_ability_cache[key] = granted
        built.append(granted)
    return built
