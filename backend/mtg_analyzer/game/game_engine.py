"""The game engine: turn/phase/step loop, actions, goldfish (docs/02 R4.*).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R4.1-R4.3 (Game Loop, Priority,
Action Validation), UC3 (Goldfisch), docs/07 PART 1/8.

`RulesEngine` is the toolbox of rules primitives; `GameEngine` is the
loop that drives it: it walks a `TurnSequence`, opens priority windows in
which the stack resolves (RULE 117/608), runs step bodies (untap, draw,
combat damage, cleanup), and exposes validated player actions (play a
land, cast a spell, attack) plus a `legal_actions` query the UI/bot can
ask instead of guessing (docs/02 R4.3 — the frontend has no such check
today). `run_goldfish_turn` wires those together into a solo auto-turn
(UC3).

`GameEngine` itself (ENG-20) is a composition of nine per-responsibility
mixins under `game/engine/` — turn loop (incl. `new_game`), combat,
casting, lands, activation, mana, legal-actions, misc, rooms — rather than one
class carrying all ~130 methods. This is a pure file-organization split:
every mixin operates on the same shared `self.state`/`self.rules`/etc.
instance state, method names/signatures are unchanged, and nothing outside
`game/` needs to know the class is assembled this way.
"""

from __future__ import annotations

from .rules_engine import RulesEngine
from .engine.activation_mixin import ActivationMixin
from .engine.casting_mixin import CastingMixin
from .engine.combat_mixin import CombatMixin
from .engine.lands_mixin import LandsMixin
from .engine.legal_actions_mixin import LegalActionsMixin
from .engine.mana_mixin import ManaMixin
from .engine.misc_mixin import MiscMixin
from .engine.rooms_mixin import RoomsMixin
from .engine.turn_loop_mixin import MAX_HAND_SIZE, TurnLoopMixin

__all__ = ["GameEngine", "MAX_HAND_SIZE"]


class GameEngine(
    TurnLoopMixin,
    CombatMixin,
    CastingMixin,
    LandsMixin,
    ActivationMixin,
    ManaMixin,
    LegalActionsMixin,
    MiscMixin,
    RoomsMixin,
):
    """Drives a `GameState` through turns using a `RulesEngine`.

    Construction and `new_game` (the class's public entry point for
    building a fresh game) live in `TurnLoopMixin` alongside the rest of
    turn/game setup — see that module for both.
    """

    def __init__(self, state: "GameState") -> None:
        self.state = state
        self.rules = RulesEngine(state)
        #: Cursor for interactive step-by-step play (see ``start`` /
        #: ``advance_step``): the current turn's ``(phase, step)`` list and
        #: how far through it we are. ``run_turn``/``run_goldfish_turn`` do
        #: not use these — they run a whole turn at once.
        self._cursor = 0
        #: RULE 117: whether every priority window is *played out* by real
        #: players (multiplayer) instead of auto-drained. Off by default, so
        #: every solo path — goldfish, replay, every existing test — keeps
        #: resolving the stack the moment a step opens, exactly as before.
        #: On, `_run_step` only puts triggers on the stack and then leaves
        #: it alone: the active player holds priority and the session drives
        #: `pass_priority(player)` around the table (`services/
        #: game_session.py`). See `GameSession._pass_priority`.
        self.interactive_priority = False

    @property
    def _turn_steps(self):
        return self.state.turn_steps

    @_turn_steps.setter
    def _turn_steps(self, steps):
        self.state.turn_steps = steps

    def _has_resolution_play_permission(self, player, obj) -> bool:
        choice = self.state.resolution_play_choice
        return bool(choice and choice["player_id"] == player.id
                    and obj.instance_id in choice["instance_ids"]
                    and obj.zone.value == choice.get("zone", "exile"))

    def play_resolution_card(self, player, obj, targets=None, x=0, *, face="front", **cast_options):
        """Play an offered card using ordinary target, mode and cost validation.

        Finish the suspended outer effect before giving priority; the new
        spell stays on the stack so other players can respond (RULE 608.2g).
        """
        cast_options.update(targets=targets, x=x)
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "play_during_resolution" or not self._has_resolution_play_permission(player, obj):
            raise ValueError("this card is not offered for playing during resolution")
        if choice.get("free", True) and (face in ("face_down", "bestow", "fuse") or any(cast_options.get(key) for key in (
            "free", "alt_cost", "evoke", "surge", "mutate", "exile_discount",
        ))):
            raise ValueError("cannot combine alternative costs with this free cast")
        card = self._face_card(obj, face)
        if card is None:
            raise ValueError("this card has no playable requested face")
        if choice.get("only_spells") and card.is_land:
            raise ValueError("this effect permits casting spells only")
        if choice.get("max_mana_value") is not None and card.converted_mana_cost >= choice["max_mana_value"]:
            raise ValueError("the resulting spell must have lesser mana value")
        if choice.get("free", True) and cast_options.get("x", 0) and "{X}" in (card.mana_cost_string or ""):
            raise ValueError("X in a free spell's mana cost must be zero")
        self.state.pending_choice = None
        previous_controller = obj.controller_id
        previous_exile = obj.exile_after_free_cast
        previous_rider = obj.granted_haste_sacrifice
        obj.exile_after_free_cast = previous_exile or choice.get("exile_after_cast", False)
        obj.controller_id = player.id
        try:
            if card.is_land:
                result = self.play_land(player, obj, face=face)
            else:
                result = self.cast_spell(player, obj, face=face, **cast_options)
        except Exception:
            obj.controller_id = previous_controller
            obj.exile_after_free_cast = previous_exile
            obj.granted_haste_sacrifice = previous_rider
            self.state.pending_choice = choice
            raise
        if self.state.pending_cast_payment is not None:
            # Additional-cost choices suspend this same immediate cast, not its permission.
            self.state.pending_cast_payment["resolution_play"] = choice
            return result
        if choice.get("cast_rider") == "haste_sacrifice" and card.is_creature:
            obj.granted_haste_sacrifice = True
        if choice.get("lock_casting"):
            self.state.no_more_spells_this_turn.add(player.id)
        if choice.get("owner_life_loss") and not card.is_land:
            choice["owner_life_losses"].append({"owner_id": obj.owner_id, "amount": int(obj.mana_value or 0)})
        self.rules._finish_resolution_play_permission(played_id=obj.instance_id)
        if choice.get("repeat"):
            self.state.resolution_play_followup = {
                "player_id": player.id,
                "instance_ids": [iid for iid in choice["instance_ids"] if iid != obj.instance_id],
                "zone": choice.get("zone", "exile"),
                "only_spells": choice.get("only_spells", False),
                "max_mana_value": choice.get("max_mana_value"),
                "free": choice.get("free", True), "exile_after_cast": choice.get("exile_after_cast", False),
                "mana_wildcard": choice.get("mana_wildcard"), "cast_rider": choice.get("cast_rider"),
                "owner_life_loss": choice.get("owner_life_loss", False),
                "owner_life_losses": list(choice.get("owner_life_losses", [])),
            }
        self._finish_resolution_play()
        return result

    def _finish_resolution_play(self):
        if not self.state.pending_choice and self.state.resolution_play_followup is not None:
            followup = self.state.resolution_play_followup
            self.state.resolution_play_followup = None
            cards = [self.state.find_object(iid) for iid in followup["instance_ids"]]
            zone = followup.get("zone", "exile")
            cards = [obj for obj in cards if obj is not None and obj.zone.value == zone]
            self.rules._request_resolution_play(
                self.state.player_by_id(followup["player_id"]), cards, repeat=True,
                zone=zone, only_spells=followup.get("only_spells", False),
                max_mana_value=followup.get("max_mana_value"),
                free=followup.get("free", True), exile_after_cast=followup.get("exile_after_cast", False),
                mana_wildcard=followup.get("mana_wildcard"), cast_rider=followup.get("cast_rider"),
                owner_life_loss=followup.get("owner_life_loss", False),
                owner_life_losses=followup.get("owner_life_losses"),
            )
        while not self.state.pending_choice and self.rules.resume_deferred_effects():
            pass
        if not self.state.pending_choice:
            self.state.resolution_play_waiting = False
            self.give_priority(self.state.active_player)

    def resolution_play_actions(self, player):
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "play_during_resolution" or choice["player_id"] != player.id:
            return []
        actions = [{"type": "decline"}]
        for iid in choice["instance_ids"]:
            obj = self.state.find_object(iid)
            if obj is None or not self._has_resolution_play_permission(player, obj):
                continue
            for face in ("front", "back"):
                card = self._face_card(obj, face)
                if card is None:
                    continue
                if ((choice.get("only_spells") and card.is_land)
                        or (choice.get("max_mana_value") is not None
                            and card.converted_mana_cost >= choice["max_mana_value"])):
                    continue
                if card.is_land and self.can_play_land(player, obj, face=face):
                    actions.append(self._land_action(obj, face=face))
                elif not card.is_land:
                    if face == "front":
                        self._offer_cast(actions, player, obj)
                    elif self.can_cast(player, obj, face=face):
                        actions.append(self._cast_action(player, obj, face=face))
        for action in actions:
            if action["type"] == "cast_spell" and choice.get("free", True):
                action["has_x"] = False
                action["max_x"] = 0
        if not choice.get("free", True):
            return actions  # RULE 601.2b: a paid offer permits ordinary alternative costs.
        return [action for action in actions if action.get("face") not in ("face_down", "bestow", "fuse")
                and not any(action.get(key) for key in ("free", "alt_cost", "evoke", "surge", "mutate", "exile_discount"))]
