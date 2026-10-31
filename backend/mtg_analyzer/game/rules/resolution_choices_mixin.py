"""Resolution-time player decisions and combat recipients."""
from __future__ import annotations

from typing import Any, Optional
from ...models.game.game_object import GameObject, Zone
from ...models.game.player import Player
from .. import continuations
from .misc_helpers import (
    _substitute_x_specs,
)


class ResolutionChoicesMixin:
    """Resolution-time player decisions and combat recipients."""
    def _request_word_of_command(
        self,
        controller: Player,
        target: Player,
        source: Optional[GameObject] = None,
    ) -> None:
        """MEC-51b (Word of Command): open a `word_of_command`
        `pending_choice` addressed to ``controller``, listing every card in
        ``target``'s hand. `GameEngine._resume_word_of_command` then
        has ``target`` play the chosen card. No card in hand → nothing to
        choose, the effect fizzles (RULE 720-adjacent "if able")."""
        hand = list(target.hand)
        if not hand:
            return
        self.state.word_of_command = {
            "controller_id": controller.id,
            "target_id": target.id,
            "chosen_instance_id": None,
        }
        self.open_choice({
            "kind": "word_of_command",
            "player_id": controller.id,   # the *controller* picks
            "target_player_id": target.id,
            "prompt": f"Word of Command — wähle eine Karte aus {target.name}s Hand",
            "description": f"Word of Command: Karte aus {target.name}s Hand",
            "eligible": [
                {"instance_id": o.instance_id, "name": o.name} for o in hand
            ],
            "options": [
                {"id": str(o.instance_id), "label": o.name,
                 "instance_id": o.instance_id}
                for o in hand
            ],
        })

    @continuations.choice("word_of_command", answer=continuations.ANSWER_INT, rule="723")
    def _resume_word_of_command(
        self, choice: dict[str, Any], instance_id: Optional[int]
    ) -> None:
        """MEC-51b: the Word of Command caster has picked ``instance_id``
        from the target's hand — now have the target *play* it "if able".

        A land → straight onto the battlefield under the target's control
        (`_put_searched_card`; a documented simplification of RULE 305's
        land-play special action — it doesn't consume the target's
        land-for-turn). Anything else → `cast_without_paying` under the
        target's control (the effect-driven free-cast primitive cascade/
        discover use — no target selection, no mana paid; RULE 720's "only
        land mana, only for that card" restriction is moot under the free
        cast). Then the `word_of_command` window closes.
        """
        woc = self.state.word_of_command
        if woc is None:
            return
        try:
            target = self.state.player_by_id(woc["target_id"])
        except KeyError:
            self.state.word_of_command = None
            return
        obj = next((o for o in target.hand if o.instance_id == instance_id), None)
        # Missing/invalid answer — the first card in hand (RULE 720: the
        # caster must choose, "nothing" isn't an option).
        if obj is None and target.hand:
            obj = target.hand[0]
        if obj is not None:
            woc["chosen_instance_id"] = obj.instance_id
            try:
                if obj.card.is_land:
                    target.remove_from_zone(obj, Zone.HAND)
                    self._put_searched_card(target, obj, "battlefield")
                else:
                    self.cast_without_paying(target, obj)
            except (ValueError, KeyError):
                pass  # "if able" — a play that can't be made simply doesn't
        self.state.word_of_command = None

    def _request_villainous_choice(
        self,
        source: Optional[GameObject],
        controller_id: str,
        facing_ids: Optional[list[str]] = None,
        option_a: Optional[list[dict[str, Any]]] = None,
        option_b: Optional[list[dict[str, Any]]] = None,
        labels: Optional[tuple[str, str]] = None,
        captured_previous: Optional[list[Any]] = None,
        rounds: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """RULE 701.55: "`<player>` faces a villainous choice — `<A>`, or
        `<B>`." Each facing player in ``facing_ids`` (already resolved and
        APNAP-ordered by `FaceVillainousChoiceEffect`) chooses one of the
        two options and that option's effects resolve **for that player** —
        applied with the facing player as the target, so an option's
        `sacrifice`/`discard`/`lose_life` spec (no selector) lands on them.
        A "you …" clause in an option stays scoped to ``controller_id``
        (the effect's own controller default, since those specs carry no
        target).

        The `_request_vote` sweep shape, minus the tally: each player
        applies their own pick rather than everyone feeding one aggregate
        outcome. RULE 701.55b's "if one option is impossible, they must
        choose the other" is a **documented simplification** — both options
        are always offered; an impossible pick simply does as little as
        RULE 608.2b allows.

        ``rounds`` (MEC-52 — Hunted by The Family: "For each of them, that
        creature's controller faces a villainous choice — …") is the
        per-firing sibling of the flat ``facing_ids`` sweep: an explicit
        list of ``{"facing_id", "option_a", "option_b", "labels",
        "captured"}`` dicts, one queued choice each, so *different* option
        bodies / RULE 608.2 referents can face *different* players in one
        resolution (each chosen creature's own controller decides about
        that creature). The flat form builds a one-round-per-id queue
        sharing ``option_a``/``option_b``/``labels``/``captured_previous``.
        """
        default_labels = tuple(labels) if labels else ("Option A", "Option B")
        if rounds is None:
            shared_captured = list(captured_previous) if captured_previous else None
            rounds = [
                {
                    "facing_id": fid,
                    "option_a": [dict(d) for d in (option_a or [])],
                    "option_b": [dict(d) for d in (option_b or [])],
                    "labels": default_labels,
                    "captured": list(shared_captured) if shared_captured else None,
                }
                for fid in (facing_ids or [])
            ]
        else:
            rounds = [
                {
                    "facing_id": rnd["facing_id"],
                    "option_a": [dict(d) for d in rnd.get("option_a", [])],
                    "option_b": [dict(d) for d in rnd.get("option_b", [])],
                    "labels": tuple(rnd.get("labels") or default_labels),
                    "captured": list(rnd["captured"]) if rnd.get("captured") else None,
                }
                for rnd in rounds
            ]
        self._pending_villainous = {
            #: FIFO queue of still-unasked choices; each is popped into
            #: ``current`` when its prompt opens (`_advance_villainous_choice`).
            "rounds": rounds,
            "current": None,
            "source": source,
            "controller_id": controller_id,
        }
        self._advance_villainous_choice()
    def _advance_villainous_choice(self) -> None:
        """Ask the next still-pending facing player in a
        `_request_villainous_choice` sweep, or clear it once done."""
        pending = self._pending_villainous
        if pending is None:
            return
        queue: list[dict[str, Any]] = pending["rounds"]
        while queue:
            rnd = queue.pop(0)
            try:
                player = self.state.player_by_id(rnd["facing_id"])
            except (KeyError, ValueError):
                continue
            if player.has_lost:
                continue
            pending["current"] = rnd
            la, lb = rnd["labels"]
            self.open_choice({
                "kind": "villainous_choice",
                "player_id": player.id,
                "prompt": f"Schurkische Wahl: {la} / {lb}",
                "options": [
                    {"id": "0", "label": la},
                    {"id": "1", "label": lb},
                ],
            })
            return  # a real choice opened — resumed via _resume_villainous_choice
        self._pending_villainous = None
    @continuations.choice("villainous_choice", answer=continuations.ANSWER_STR, rule="701.55")
    def _resume_villainous_choice(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `villainous_choice`: apply the chosen option's
        effects for that facing player (a missing/unknown answer defaults to
        option A, RULE 701.55b's "each player must choose"), then advance."""
        pending = self._pending_villainous
        if pending is None:
            return
        rnd = pending.get("current")
        if rnd is None:
            return
        try:
            facing = self.state.player_by_id(choice["player_id"])
        except (KeyError, ValueError):
            facing = None
        specs = rnd["option_b"] if str(answer) == "1" else rnd["option_a"]
        if facing is not None:
            captured = rnd.get("captured")
            if captured:
                # Re-seed the RULE 608.2 referent for this option's own
                # `copy_permanent` ``referent="previous"`` / pronoun specs
                # (the resolution that opened the choice is long gone).
                saved = list(self.context.previous_targets)
                self.context.previous_targets = list(captured)
                try:
                    self._apply_effect_specs(specs, pending["source"], targets=[facing])
                finally:
                    self.context.previous_targets = saved
            else:
                self._apply_effect_specs(specs, pending["source"], targets=[facing])
        self._advance_villainous_choice()
    def _request_number_choice(
        self, player: Player, minimum: int, maximum: int, effect_specs: list[dict], source: Optional[GameObject],
    ) -> None:
        """"Choose a number between ``minimum`` and ``maximum``" at resolution (RULE 601.2b-style, Expel the
        Interlopers): the answer binds the ``"x"`` sentinel of ``effect_specs`` (`_resume_number_choice`)."""
        self.open_choice({
            "kind": "choose_number_resolve",
            "player_id": player.id,
            "prompt": f"Zahl zwischen {minimum} und {maximum} wählen",
            "options": [{"id": str(n), "label": str(n)} for n in range(int(minimum), int(maximum) + 1)],
            "then_specs": [dict(spec) for spec in effect_specs],
            "source_id": getattr(source, "instance_id", None),
        })

    @continuations.choice("choose_number_resolve", answer=continuations.ANSWER_STR, rule="601.2b")
    def _resume_number_choice(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `choose_number_resolve`: mandatory, so a missing/unparseable answer is the lowest number."""
        valid = [int(o["id"]) for o in choice["options"]]
        try:
            number = int(str(answer))
        except (TypeError, ValueError):
            number = valid[0] if valid else 0
        if number not in valid and valid:
            number = valid[0]
        source = self._object_by_instance_id(choice.get("source_id"))
        self._apply_effect_specs(_substitute_x_specs(list(choice.get("then_specs") or []), number), source)

    def _apply_effect_specs(
        self,
        effect_specs: list[dict],
        source: Optional[GameObject],
        targets: Optional[list[Any]] = None,
    ) -> None:
        """Build and apply serialized `EffectSpec` dicts right now, off the
        stack — the shared tail of every "if you do / if you don't" branch
        (`_resume_pay_cost_then`, `_resume_pay_energy_then`).
        Goes through `build_effects`, so the whitelist still gates every
        effect type (docs/09 security boundary)."""
        if not effect_specs:
            return
        from ...parser.oracle.spec import EffectSpec
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle

        built = build_effects(
            [
                EffectSpec(type=d["type"], params=dict(d.get("params") or {}), condition=d.get("condition"))
                for d in effect_specs
            ],
            source,
        )
        for effect in built:
            effect.apply(self.context, targets)
    def _attack_defender_specs(self, attacker_controller: Player) -> list[dict[str, Any]]:
        """Who ``attacker_controller``'s creatures could attack: every other living player, planeswalkers
        they don't control and battles protected by someone else (RULE 508.1a, 310.8b) — the defender
        universe `GameEngine.legal_defenders_for` offers, mirrored here because `RulesEngine` does not
        import the high-level engine."""
        specs: list[dict[str, Any]] = [
            {"kind": "player", "id": player.id, "label": player.name}
            for player in self.state.living_players() if player.id != attacker_controller.id
        ]
        specs.extend(
            {"kind": "planeswalker", "instance_id": o.instance_id, "label": o.name}
            for o in self.state.battlefield
            if o.controller_id != attacker_controller.id and o.is_planeswalker
        )
        specs.extend(
            {"kind": "battle", "instance_id": o.instance_id, "label": o.name}
            for o in self.state.battlefield
            if o.is_battle and o.protector_id not in (None, attacker_controller.id)
        )
        return specs

    def _request_damage_recipient(
        self, chooser: Player, source: Optional[GameObject], amount: Any, player: Player,
        walkers: list[GameObject],
    ) -> None:
        """"…damage to that player or a planeswalker that player controls" (RULE 120.3): ``chooser`` picks the
        recipient among ``player`` and the planeswalkers they control; the damage is dealt on the answer."""
        options = [{"id": f"player:{player.id}", "label": player.name}]
        options += [{"id": f"planeswalker:{o.instance_id}", "label": o.name} for o in walkers]
        self.open_choice({
            "kind": "damage_recipient", "player_id": chooser.id, "options": options,
            "prompt": "Wähle, wer den Schaden erhält",
            "source_id": getattr(source, "instance_id", None), "amount": amount,
        })

    @continuations.choice("damage_recipient", answer=continuations.ANSWER_STR, rule="120.3")
    def _resume_damage_recipient(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        source = self.state.find_object(choice["source_id"]) if choice.get("source_id") is not None else None
        # An unanswerable/declined pick falls back to the first option — the player (damage is not optional).
        picked = next((o for o in choice["options"] if o["id"] == answer), choice["options"][0])
        kind, _, key = picked["id"].partition(":")
        target = self.state.player_by_id(key) if kind == "player" else self.state.find_object(int(key))
        if target is not None:
            self.deal_damage(target, int(choice["amount"]), source=source)

    def _offer_attack_defenders(
        self, chooser: Player, pairs: list[tuple[GameObject, Optional[str]]],
    ) -> None:
        """RULE 508.4a: "…tapped and attacking **that player or a planeswalker they control**" (Adeline, Zara,
        Hans Eriksson). Each ``(creature, defending_player_id)`` was already put into combat attacking that
        player (the deterministic choice); its controller may instead pick a planeswalker that player controls.
        The picks are asked one creature at a time (`reselect_attack` carries the rest in ``remaining``), and
        nothing is asked for a creature whose player controls no planeswalker."""
        queue = [
            {"attacker_id": creature.instance_id, "player_id": player_id}
            for creature, player_id in pairs if player_id is not None and getattr(creature, "attacking", False)
        ]
        self._open_next_attack_defender(chooser.id, queue)

    def _open_next_attack_defender(self, chooser_id: str, queue: list[dict[str, Any]]) -> None:
        """Open the first queued defender pick that has a real alternative; the rest wait in ``remaining``."""
        while queue:
            head, queue = queue[0], queue[1:]
            attacker = self.state.find_object(head["attacker_id"])
            if attacker is None or not getattr(attacker, "attacking", False):
                continue
            controller = self.state.player_by_id(head["player_id"])
            walkers = [
                {"kind": "planeswalker", "instance_id": o.instance_id, "label": o.name}
                for o in self.state.battlefield if o.is_planeswalker and o.controller_id == head["player_id"]
            ]
            if controller is None or not walkers:
                continue
            defenders = [{"kind": "player", "id": controller.id, "label": controller.name}, *walkers]
            self._request_reselect_attack(self.state.player_by_id(chooser_id), attacker, defenders)
            self.state.pending_choice["remaining"] = queue
            return

    def _request_reselect_attack(self, chooser: Player, attacker: GameObject, defenders: list[dict[str, Any]]) -> None:
        """RULE 506.4/508.1b-adjacent "you may reselect which player or permanent target attacking
        creature is attacking" (Misleading Signpost): open a defender pick for ``chooser`` — a player
        or a planeswalker/battle the attacker's controller could have attacked — or keep the current one."""
        options = []
        for spec in defenders:
            key = spec["id"] if spec.get("kind") == "player" else spec["instance_id"]
            options.append({"id": f'{spec["kind"]}:{key}', "label": spec.get("label", str(key))})
        options.append({"id": "decline", "label": "Angriffsziel beibehalten"})
        self.open_choice({
            "kind": "reselect_attack", "player_id": chooser.id, "attacker_id": attacker.instance_id,
            "prompt": f"Neues Angriffsziel für {attacker.name} wählen?", "options": options,
            "defenders": [dict(d) for d in defenders],
        })

    @continuations.choice("reselect_attack", answer=continuations.ANSWER_STR, rule="508.1b")
    def _resume_reselect_attack(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        try:
            attacker = self.state.find_object(choice["attacker_id"])
            if answer not in (None, "decline") and attacker is not None and getattr(attacker, "attacking", False):
                # (RULE 608.2b: an attacker that left combat meanwhile is simply skipped)
                for spec in choice.get("defenders", []):
                    key = spec["id"] if spec.get("kind") == "player" else spec["instance_id"]
                    if answer == f'{spec["kind"]}:{key}':
                        attacker.combat_defender = dict(spec)
                        break
        finally:
            # RULE 508.4a: the next creature of the same instruction (`_offer_attack_defenders`) asks next.
            remaining = choice.get("remaining") or []
            if remaining:
                self._open_next_attack_defender(choice["player_id"], remaining)
