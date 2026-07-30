"""Emblem: a command-zone marker with no characteristics but abilities
(RULE 114).

"[Player] gets an emblem with '[ability]'" puts an emblem — owned and
controlled by that player — into the command zone (RULE 114.2). It is
neither a card nor a permanent (RULE 114.5): no name, mana cost, or types,
just the ability the creating effect names, and that ability "functions in
the command zone" (RULE 114.4) for as long as the game lasts (nothing
removes an emblem in practice).

Rather than model this as a real `GameObject` sitting in a zone — which
would need every permanent-shaped attribute (`card`, `power`, `zone`, …)
most of which an emblem simply has none of — an `Emblem` is a minimal
stand-in that only carries what the effect system actually reads off a
"source": `controller_id` (so a "you control"/"you" selector or
phase-relation trigger resolves who "you" is, the same way it would off a
real permanent's controller) and `timestamp` (RULE 613.7b layer ordering,
same field a battlefield object stamps on entry). `game/rules_engine.py`'s
`create_emblem` binds the quoted ability's already-parsed `AbilitySpec`
against one of these as its `source`; `game/continuous.py` and
`RulesEngine._collect_triggers` read `static_effects`/`triggered_abilities`
off every player's `Player.emblems` the same way they read a permanent's.
"""

from __future__ import annotations

from typing import Any

from .game_object import _instance_counter


class Emblem:
    """One emblem in a player's command zone (RULE 114)."""

    def __init__(self, controller_id: str, timestamp: int = 0, description: str = "") -> None:
        self.controller_id = controller_id
        #: RULE 114.2: owner and controller are always the same player.
        self.owner_id = controller_id
        self.timestamp = timestamp
        self.description = description
        #: `StaticAbility` instances (RULE 114.4) — read by
        #: `game/continuous.py`'s static-ability source scan.
        self.static_effects: list[Any] = []
        #: `TriggeredAbility` instances — read by `RulesEngine._collect_triggers`.
        self.triggered_abilities: list[Any] = []
        #: RULE 114.4 also permits an emblem's own activated ability (rare —
        #: no real emblem prints one yet, `RulesEngine.create_emblem` files
        #: it here instead of dropping it). `instance_id` shares `GameObject`'s
        #: own counter so `GameState.find_object`/`GameEngine.can_activate`/
        #: `activate_ability`/`legal_actions` can treat an emblem exactly like
        #: a permanent when offering and dispatching it.
        self.instance_id: int = next(_instance_counter)
        self.activated_abilities: list[Any] = []
        #: Always empty — nothing grants an *emblem* an ability the way
        #: Umbral Mantle grants a permanent one. Kept only so the
        #: `source.activated_abilities + source.granted_activated_abilities`
        #: idiom every activation call site already uses works unchanged.
        self.granted_activated_abilities: list[Any] = []
        #: No card frame to read a name off (RULE 114.5) — used only in the
        #: error-message/UI-label formatting the ordinary `GameObject` paths
        #: already do (`f"{source.name} ..."`).
        self.name = "Emblem"

    def to_dict(self) -> dict[str, Any]:
        return {
            "controller_id": self.controller_id,
            "description": self.description,
        }

    def __repr__(self) -> str:
        return f"Emblem(controller_id={self.controller_id!r}, description={self.description!r})"
