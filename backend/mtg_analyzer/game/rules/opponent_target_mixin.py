"""Targets chosen by an opponent: "target `<X>` of an opponent's choice" (MEC-118, RULE 115.1 / 601.2c).

An ordinary requirement is answered by the player putting the spell or ability on the stack.  Some printed
requirements hand that pick to another player: the controller chooses an opponent, then that opponent chooses the
target as the spell or ability is put on the stack (Evangelize's and Preacher's rulings: "This is not a choice made on
resolution").  The controller still controls the object -- hexproof and protection are judged against the controller's
source, and "you" in the requirement stays the controller (Cuombajj Witches' ruling).

The controller's own announcement leaves an empty group for each such requirement (`targeting.with_chooser_slots`);
this mixin fills them in right after the object is on the stack, through the ordinary choice continuations, so a
human opponent answers from the same choice UI and a bot from its own view (`legal_actions`).  Nobody can respond
while the choice is open, so the stack object is complete before any player receives priority (RULE 117.3c).
"""

from __future__ import annotations

from typing import Any, Optional

from ...models.game.game_state import StackItem
from .. import continuations
from ..targeting import chooser_opponents, chooser_options, effects_target_specs, TargetSpec

#: The `pending_choice` kinds this mixin opens.  `RulesEngine._place_triggers` pauses its queue while one is open.
OPPONENT_TARGET_KIND = "opponent_target"
OPPONENT_CHOOSER_KIND = "opponent_chooser"
OPPONENT_CHOICE_KINDS = frozenset({OPPONENT_TARGET_KIND, OPPONENT_CHOOSER_KIND})
#: Resolve-time sibling ("sacrifice a land of an opponent's choice"): the sacrificing player names the opponent.
OPPONENT_SACRIFICE_CHOOSER_KIND = "opponent_sacrifice_chooser"


class OpponentTargetMixin:
    @staticmethod
    def _item_target_specs(item: StackItem) -> list[TargetSpec]:
        """``item``'s requirements in announcement order -- the same list the groups in `item.target_groups` index
        (a wrapped triggered/activated ability keeps its effects one level down)."""
        body = item.effects
        if len(body) == 1 and hasattr(body[0], "effects"):
            body = body[0].effects
        return effects_target_specs(body)

    def _opponent_target_pending(self) -> bool:
        """Whether an opponent-target choice (or the choice of which opponent) is currently open."""
        pending = self.state.pending_choice
        return bool(pending) and pending.get("kind") in OPPONENT_CHOICE_KINDS

    def _open_opponent_slots(self, item: StackItem) -> list[int]:
        """Indices of ``item``'s "of an opponent's choice" requirements the opponent has not picked yet."""
        groups = item.target_groups
        if not groups:
            return []
        specs = self._item_target_specs(item)
        return [
            index for index, spec in enumerate(specs)
            if spec.chooser and index < len(groups) and not groups[index] and index not in item.opponent_done
        ]

    def _begin_opponent_targets(self, item: StackItem) -> None:
        """RULE 601.2c: once ``item`` is on the stack, ask the chosen opponent for each requirement they pick.

        Opens at most one choice (`GameState.pending_choice` holds one); `_resume_opponent_target` continues with the
        next slot, then finishes the announcement (ward / "becomes the target" events, the paused trigger queue)."""
        if self._open_opponent_slots(item):
            self._advance_opponent_targets(item)

    def _advance_opponent_targets(self, item: StackItem) -> None:
        specs = self._item_target_specs(item)
        while True:
            open_slots = self._open_opponent_slots(item)
            if not open_slots:
                self._finish_opponent_targets(item)
                return
            slot = open_slots[0]
            spec = specs[slot]
            able = [
                opponent for opponent in chooser_opponents(self.state, item.controller_id)
                if chooser_options(self.state, item.controller_id, opponent.id, spec,
                                   source=item.source or item.obj, trigger_event=item.trigger_event)
            ]
            if not able:
                # RULE 601.2c ensured a legal pick existed when announced; it can only be gone if a response was
                # impossible, so the slot is simply left without a target (RULE 608.2b handles the rest).
                item.opponent_done.add(slot)
                continue
            chooser_id = item.opponent_chosen.get(slot)
            if chooser_id is None and len(able) == 1:
                chooser_id = able[0].id
            if chooser_id is None:
                # More than one opponent could pick: the controller names which (Volcanic Offering's ruling).
                self.open_choice({
                    "kind": OPPONENT_CHOOSER_KIND, "player_id": item.controller_id,
                    "prompt": f"{self._opponent_target_source_name(item)}: Gegner wählen, der das Ziel bestimmt",
                    "options": [{"id": p.id, "label": p.name} for p in able],
                    "stack_id": item.stack_id, "slot": slot, "category": item.category,
                })
                return
            item.opponent_chosen[slot] = chooser_id
            options = chooser_options(
                self.state, item.controller_id, chooser_id, spec,
                source=item.source or item.obj, trigger_event=item.trigger_event,
            )
            self.open_choice({
                "kind": OPPONENT_TARGET_KIND, "player_id": chooser_id,
                "prompt": f"{self._opponent_target_source_name(item)}: Ziel wählen",
                "options": [self._opponent_target_option(option) for option in options],
                "stack_id": item.stack_id, "slot": slot, "category": item.category,
                "controller_id": item.controller_id, "polarity": spec.polarity,
            })
            return

    @staticmethod
    def _opponent_target_source_name(item: StackItem) -> str:
        origin = item.source or item.obj
        return getattr(origin, "name", None) or item.description

    @staticmethod
    def _opponent_target_option(option: dict[str, Any]) -> dict[str, Any]:
        """One `legal_targets` descriptor as a generic choice option (same shape `_trigger_target_choice` offers)."""
        if "instance_id" in option:
            return {"id": str(option["instance_id"]), "label": option["name"], "instance_id": option["instance_id"]}
        return {"id": option["player_id"], "label": option["name"]}

    def _request_opponent_sacrifice(self, victim: Player, what: str, count: Any) -> None:
        """"`victim` sacrifices `<what>` of an opponent's choice" (RULE 701.17a, MEC-118): untargeted, so it is made as
        the effect resolves -- one of ``victim``'s opponents picks which permanent goes.  With several opponents
        ``victim`` names the one who picks (`_resume_opponent_sacrifice_chooser`)."""
        opponents = [p for p in self.state.living_players() if p.id != victim.id]
        if not opponents:
            return
        if len(opponents) == 1:
            self.sacrifice(victim, what, count, chooser=opponents[0])
            return
        self.open_choice({
            "kind": OPPONENT_SACRIFICE_CHOOSER_KIND, "player_id": victim.id,
            "prompt": "Gegner wählen, der das Opfer bestimmt",
            "options": [{"id": p.id, "label": p.name} for p in opponents],
            "victim_id": victim.id, "what": what, "count": count,
        })

    @continuations.choice(OPPONENT_SACRIFICE_CHOOSER_KIND, answer=continuations.ANSWER_STR, rule="701.17a")
    def _resume_opponent_sacrifice_chooser(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        ids = [str(option["id"]) for option in choice["options"]]
        picker = self.state.player_by_id(answer if answer in ids else ids[0])
        victim = self.state.player_by_id(choice["victim_id"])
        self.sacrifice(victim, choice["what"], choice["count"], chooser=picker)

    def _stack_item_by_id(self, stack_id: Any) -> Optional[StackItem]:
        return next((entry for entry in self.state.stack if entry.stack_id == stack_id), None)

    @continuations.choice(OPPONENT_CHOOSER_KIND, answer=continuations.ANSWER_STR, rule="601.2c")
    def _resume_opponent_chooser(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """The controller names the opponent who will pick the target (mandatory: a bad answer takes the first)."""
        item = self._stack_item_by_id(choice.get("stack_id"))
        if item is None:
            return
        ids = [str(option["id"]) for option in choice["options"]]
        item.opponent_chosen[choice["slot"]] = answer if answer in ids else ids[0]
        self._advance_opponent_targets(item)

    @continuations.choice(OPPONENT_TARGET_KIND, answer=continuations.ANSWER_STR, rule="601.2c")
    def _resume_opponent_target(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """The chosen opponent picks the target (mandatory: a bad answer takes the first option)."""
        item = self._stack_item_by_id(choice.get("stack_id"))
        if item is None:
            return
        options = choice["options"]
        ids = [str(option["id"]) for option in options]
        picked_id = answer if answer in ids else (ids[0] if ids else None)
        slot = choice["slot"]
        target = self._resolve_choice_option(options, picked_id) if picked_id is not None else None
        item.opponent_done.add(slot)
        if target is not None:
            groups = [list(group) for group in item.target_groups]
            groups[slot] = [target]
            item.target_groups = groups
            # Every flat-`targets` consumer (ward, the stack display, copy-on-cast) must see the new pick (RULE 115.1).
            item.targets = [t for group in groups for t in group]
            item.target_incarnations = [
                getattr(t, "zone_incarnation", getattr(getattr(t, "obj", None), "zone_incarnation", None))
                for t in item.targets
            ]
        self._advance_opponent_targets(item)

    def _finish_opponent_targets(self, item: StackItem) -> None:
        """Every opponent pick is in: announce the finished targets, then carry on with whatever was paused."""
        controller = self.state.player_by_id(item.controller_id)
        if controller is not None:
            self.check_ward(item, controller)
        queue, self._opponent_resume_queue = self._opponent_resume_queue, []
        if queue:
            self._place_triggers(queue)
        else:
            self._maybe_continue_ordering()
