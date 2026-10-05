from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _parallax_wave() -> list[AbilitySpec]:
    """Fading 5 (This enchantment enters with five fade counters on it. At
    the beginning of your upkeep, remove a fade counter from it. If you
    can't, sacrifice it.)
    Remove a fade counter from this enchantment: Exile target creature.
    When this enchantment leaves the battlefield, each player returns to
    the battlefield all cards they own exiled with it.

    — MEC-12 (cEDH staples 2). Fading is an already-bound keyword. The new
    `ReturnAllExiledWithEffect`/`"return_all_exiled_with"` is the mass
    sibling of the O-Ring family's `ReturnLinkedExileEffect` — reading
    `GameObject.exiled_with_ids` (MEC-21's accumulating tracker) instead of
    the single-slot `linked_exile_id`, since this activated ability can
    exile a different creature every time a fade counter is spent (up to
    five times), each potentially owned by a different player, all
    returning together the moment Parallax Wave itself leaves.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exile", {"target_kind": "creature", "track_exiled_with": True})],
            cost={"remove_counters": ["fade", 1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_all_exiled_with", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Parallax Wave", _parallax_wave)
