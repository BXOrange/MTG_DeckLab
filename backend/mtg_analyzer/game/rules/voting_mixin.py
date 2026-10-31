"""Player and object votes, tallies and outcomes."""
from __future__ import annotations

from typing import Any, Optional
from ...models.game.game_object import GameObject
from ...models.game.player import Player
from .. import continuations


class VotingMixin:
    """Player and object votes, tallies and outcomes."""
    def _request_vote(
        self,
        source: Optional[GameObject],
        controller_id: str,
        options: list[str],
        majority_specs: Optional[list[list[dict[str, Any]]]] = None,
        tie_index: Optional[int] = None,
        per_vote_specs: Optional[list[dict[str, Any]]] = None,
        winner_specs: Optional[list[Optional[list[dict[str, Any]]]]] = None,
    ) -> None:
        """RULE 701.38: "Starting with you, each player votes for one of
        ``options``." An APNAP sweep — every living player, beginning with
        the active player and proceeding in turn order, picks one option;
        the running tally is kept in ``_pending_vote``. Once everyone has
        voted, `_tally_and_apply_vote` resolves the outcome, applied with
        ``controller_id``'s player as the target (the printed "you").

        Three outcome shapes, exactly one supplied:

        * ``majority_specs`` — one serialized effect list per option (same
          index order as ``options``). The option with the strictly most
          votes has its list applied; ``tie_index`` names the option whose
          branch wins if no option is a sole leader (RULE 701.38d — "or the
          vote is tied").
        * ``per_vote_specs`` — a list of ``{"option": <index>, "effects":
          [...], "scale": <int>}`` entries: each entry's effects are
          applied once, with every ``count``/``amount`` param multiplied by
          ``scale`` × that option's vote total ("put a +1/+1 counter on ~
          for each strength vote"). MEC-46: an entry may instead be
          ``{"option": <index>, "per_voter_gain_control": true}`` —
          Expropriate's "for each money vote, choose a permanent owned by
          the voter and gain control of it", which needs the *individual
          ballots*, not just a total.
        * ``winner_specs`` (MEC-46) — like ``majority_specs``, but applied
          for **every** option that is tied for most votes, not only a sole
          leader ("~ gains protection from each color with the most votes
          or tied for most votes" — Council Guardian).

        Built as a chain of ordinary single-player choices over the same
        `_apply_effect_specs` tail every "if you do" branch already uses,
        the same way `_request_all_players_decline_or` is.
        """
        start = self.state.active_player_index
        n = len(self.state.players)
        order = [
            self.state.players[(start + i) % n].id
            for i in range(n)
            if not self.state.players[(start + i) % n].has_lost
        ]
        self._pending_vote = {
            "remaining_ids": order,
            "tally": {i: 0 for i in range(len(options))},
            # MEC-46: the individual (voter_id, option_index) ballots, in
            # ask order — needed by an outcome that acts per voter rather
            # than per total (Expropriate's per-money-vote gain-control).
            "ballots": [],
            "current_voter_id": None,
            "options": list(options),
            "source": source,
            "controller_id": controller_id,
            "majority_specs": [[dict(d) for d in lst] for lst in majority_specs] if majority_specs else None,
            "tie_index": tie_index,
            "per_vote_specs": [dict(d) for d in per_vote_specs] if per_vote_specs else None,
            "winner_specs": (
                [[dict(d) for d in lst] if lst else None for lst in winner_specs]
                if winner_specs else None
            ),
        }
        self._advance_vote()
    def _advance_vote(self) -> None:
        """Ask the next still-pending voter in a `_request_vote` sweep; once
        everyone has voted, tally and apply the outcome."""
        pending = self._pending_vote
        if pending is None:
            return
        remaining: list[str] = pending["remaining_ids"]
        options: list[str] = pending["options"]
        while remaining:
            player_id = remaining.pop(0)
            try:
                player = self.state.player_by_id(player_id)
            except (KeyError, ValueError):
                continue
            if player.has_lost:
                continue
            pending["current_voter_id"] = player.id
            # RULE 701.38f (MEC-46): "You choose how each player votes this
            # turn." (Illusion of Choice) — while `forced_vote_controller_id`
            # is set, that player answers *every* seat's vote; the real
            # voter's name still rides in the prompt so the deciding player
            # knows whose ballot they are filling in. A missing answer
            # defaults to option 0.
            decider_id, prompt_prefix = self._vote_decider(player)
            self.open_choice({
                "kind": "vote",
                "player_id": decider_id,
                "prompt": prompt_prefix + "Abstimmung: " + " / ".join(options),
                "options": [
                    {"id": str(i), "label": opt} for i, opt in enumerate(options)
                ],
            })
            return  # a real choice opened — resumed via _resume_vote
        self._tally_and_apply_vote()
    def _vote_decider(self, voter: Player) -> tuple[str, str]:
        """Who actually answers ``voter``'s ballot, and a prompt prefix.

        RULE 701.38f: normally the voter themselves; while a forced-vote
        controller is set for the turn (Illusion of Choice), that player
        answers instead and the prompt names whose vote it is."""
        forced_id = getattr(self.state, "forced_vote_controller_id", None)
        if forced_id:
            try:
                forcer = self.state.player_by_id(forced_id)
            except (KeyError, ValueError):
                forcer = None
            if forcer is not None and not forcer.has_lost:
                return forced_id, f"Stimme für {voter.name} — "
        return voter.id, ""
    @continuations.choice("vote", answer=continuations.ANSWER_STR, rule="701.38")
    def _resume_vote(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `vote` choice: record this player's vote for the
        chosen option index (a missing/unknown answer defaults to option 0,
        RULE 701.38b's "each player must choose"), then move on."""
        pending = self._pending_vote
        if pending is None:
            return
        tally: dict[int, int] = pending["tally"]
        try:
            idx = int(answer) if answer is not None else 0
        except (TypeError, ValueError):
            idx = 0
        if idx not in tally:
            idx = 0
        tally[idx] += 1
        voter_id = pending.get("current_voter_id")
        if voter_id is not None:
            pending["ballots"].append((voter_id, idx))
        self._advance_vote()
    def _tally_and_apply_vote(self) -> None:
        """Resolve a finished `_request_vote` sweep's outcome (majority
        branch, per-vote scaling, or per-winning-option) and clear it."""
        pending = self._pending_vote
        self._pending_vote = None
        if pending is None:
            return
        tally: dict[int, int] = pending["tally"]
        source = pending["source"]
        ballots: list[tuple[str, int]] = list(pending.get("ballots") or [])
        try:
            controller = self.state.player_by_id(pending["controller_id"])
        except (KeyError, ValueError):
            controller = None
        targets = [controller] if controller is not None else None

        if pending["majority_specs"] is not None:
            specs_by_option: list[list[dict]] = pending["majority_specs"]
            top = max(tally.values()) if tally else 0
            leaders = [i for i, v in tally.items() if v == top]
            winner = leaders[0] if len(leaders) == 1 else pending.get("tie_index", 0)
            if 0 <= winner < len(specs_by_option):
                self._apply_effect_specs(specs_by_option[winner], source, targets)
            return

        # MEC-46: "~ gains protection from each color with the most votes
        # or tied for most votes" (Council Guardian) — apply every leading
        # option's spec list, not just a sole leader's.
        if pending.get("winner_specs") is not None:
            winner_specs: list[Optional[list[dict]]] = pending["winner_specs"]
            top = max(tally.values()) if tally else 0
            if top > 0:
                for i, v in tally.items():
                    if v == top and 0 <= i < len(winner_specs) and winner_specs[i]:
                        self._apply_effect_specs(winner_specs[i], source, targets)
            return

        for entry in pending["per_vote_specs"] or []:
            opt = int(entry.get("option", 0))
            # MEC-46: Expropriate's "for each money vote, choose a permanent
            # owned by the voter and gain control of it" — one gain-control
            # pick per *ballot* cast for this option, resolved through a
            # `choose_objects` chain (`_advance_expropriate_gain_control`).
            if entry.get("per_voter_gain_control"):
                money_voters = [vid for vid, o in ballots if o == opt]
                self._advance_expropriate_gain_control(source, pending["controller_id"], money_voters)
                continue
            scale = int(entry.get("scale", 1) or 1) * int(tally.get(opt, 0))
            if scale <= 0:
                continue
            def scale_spec(spec: dict) -> dict:
                """Scale quantitative leaves through a composite body."""
                params = dict(spec.get("params") or {})
                for key in ("count", "amount"):
                    if isinstance(params.get(key), int):
                        params[key] *= scale
                for key in ("effects", "then", "else"):
                    if isinstance(params.get(key), list):
                        params[key] = [scale_spec(dict(child)) for child in params[key]]
                return {"type": spec["type"], "params": params}

            scaled = [scale_spec(dict(spec)) for spec in entry.get("effects", [])]
            self._apply_effect_specs(scaled, source, targets)
    def _advance_expropriate_gain_control(
        self, source: Optional[GameObject], controller_id: str, voter_ids: list[str]
    ) -> None:
        """MEC-46 (Expropriate): for the next voter in ``voter_ids``, let
        ``controller_id`` choose one permanent that voter owns and gain
        control of it (RULE 701.38 outcome body), then recurse on the rest.

        The remaining queue rides in the `choose_objects` decision's own
        ``then_specs`` (an `expropriate_gain_control` effect), so it is
        clone-safe for the undo snapshots `GameState` takes — there is no
        engine-side queue object."""
        while voter_ids:
            voter_id, rest = voter_ids[0], voter_ids[1:]
            try:
                caster = self.state.player_by_id(controller_id)
            except (KeyError, ValueError):
                return
            # Every permanent the voter *owns* is a legal pick (RULE
            # 701.38 — "a permanent owned by the voter"); one the caster
            # already controls just makes the gain-control a no-op.
            owned = [
                obj for obj in self.state.permanents()
                if getattr(obj, "owner_id", None) == voter_id
            ]
            if not owned:
                voter_ids = rest
                continue
            self._request_choose_objects(
                caster, owned, action="gain_control", count=1, source=source,
                prompt="Dauerhaften Permanent übernehmen",
                then_specs=[{
                    "type": "expropriate_gain_control",
                    "params": {"voter_ids": list(rest)},
                }],
            )
            return
    def _request_object_vote(
        self,
        source: Optional[GameObject],
        controller_id: str,
        candidates: list[GameObject],
        outcome: str,
        prompt: str = "Abstimmung",
    ) -> None:
        """MEC-46 (RULE 701.38): the tally-over-objects sibling of
        `_request_vote`. "Starting with you, each player votes for `<one of
        these objects>`. `<verb>` each `<object>` with the most votes or
        tied for most votes."

        An APNAP sweep in which every living player picks one of
        ``candidates`` — a board permanent (Council's Judgment) or a
        graveyard card (Custodi Squire) — then every object tied for most
        votes has ``outcome`` applied. ``outcome`` is ``"exile"`` or
        ``"return_to_hand"`` (a graveyard card's owner is its controller —
        "to your hand" for Custodi Squire needs no separate recipient).

        Chained one `vote_object` choice at a time, `_pending_object_vote`
        holding the tally, exactly like `_pending_vote`.
        """
        start = self.state.active_player_index
        n = len(self.state.players)
        order = [
            self.state.players[(start + i) % n].id
            for i in range(n)
            if not self.state.players[(start + i) % n].has_lost
        ]
        pool = [obj for obj in candidates if obj is not None]
        if not pool or not order:
            return
        self._pending_object_vote = {
            "remaining_ids": order,
            "current_voter_id": None,
            "tally": {obj.instance_id: 0 for obj in pool},
            "candidate_ids": [obj.instance_id for obj in pool],
            "source": source,
            "controller_id": controller_id,
            "outcome": outcome,
            "prompt_text": prompt,
        }
        self._advance_object_vote()
    def _advance_object_vote(self) -> None:
        """Ask the next still-pending voter in a `_request_object_vote`
        sweep; once everyone has voted, tally and apply the outcome."""
        pending = self._pending_object_vote
        if pending is None:
            return
        remaining: list[str] = pending["remaining_ids"]
        while remaining:
            player_id = remaining.pop(0)
            try:
                player = self.state.player_by_id(player_id)
            except (KeyError, ValueError):
                continue
            if player.has_lost:
                continue
            options: list[dict[str, Any]] = []
            for iid in pending["candidate_ids"]:
                obj = self._object_by_instance_id(iid)
                if obj is None:
                    continue  # left its zone since the sweep began
                opt: dict[str, Any] = {"id": str(iid), "label": obj.name, "instance_id": iid}
                card = getattr(obj, "card", None)
                if card is not None and getattr(card, "id", None):
                    opt["card_id"] = card.id
                options.append(opt)
            if not options:
                self._pending_object_vote = None
                return
            pending["current_voter_id"] = player.id
            decider_id, prompt_prefix = self._vote_decider(player)
            self.open_choice({
                "kind": "vote_object",
                "player_id": decider_id,
                "prompt": prompt_prefix + pending["prompt_text"],
                "options": options,
            })
            return  # resumed via _resume_vote_object
        self._tally_and_apply_object_vote()
    @continuations.choice("vote_object", answer=continuations.ANSWER_STR, rule="701.38")
    def _resume_vote_object(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `vote_object` choice: record this player's vote
        for the chosen candidate (a missing/unknown answer defaults to the
        first candidate, RULE 701.38b), then move on."""
        pending = self._pending_object_vote
        if pending is None:
            return
        tally: dict[int, int] = pending["tally"]
        try:
            iid: Optional[int] = int(answer) if answer is not None else None
        except (TypeError, ValueError):
            iid = None
        if iid not in tally:
            iid = pending["candidate_ids"][0] if pending["candidate_ids"] else None
        if iid in tally:
            tally[iid] += 1
        self._advance_object_vote()
    def _tally_and_apply_object_vote(self) -> None:
        """Resolve a finished `_request_object_vote` sweep: apply ``outcome``
        to every candidate tied for most votes (RULE 701.38d)."""
        pending = self._pending_object_vote
        self._pending_object_vote = None
        if pending is None:
            return
        tally: dict[int, int] = pending["tally"]
        top = max(tally.values()) if tally else 0
        if top <= 0:
            return
        winners = [iid for iid, v in tally.items() if v == top]
        outcome = pending["outcome"]
        for iid in winners:
            obj = self._object_by_instance_id(iid)
            if obj is None:
                continue
            if outcome == "exile":
                self.exile(obj)
            elif outcome == "return_to_hand":
                self.return_to_hand(obj)
