"""Bot policy; shared registry/driver is services.bots."""
from __future__ import annotations

import random
from typing import Any, Optional



class Bot:
    """Base class: the dispatcher, plus the decisions every bot must answer.

    Subclasses override the policy hooks — `play` is the interesting one;
    `blocks`, `answer_choice` and `setup` have defaults that are already
    right for a bot that does nothing.

    `decide` returns the single action to take next, or ``None`` for "I'm
    done" — which `run_bots` turns into a pass when the bot holds priority.
    Deciding one action at a time (rather than a whole turn) is what keeps
    a bot honest: every action it takes goes through the engine's
    validation and produces a fresh view, exactly as if a human had
    clicked it.
    """

    #: Registry key (`BOT_TYPES`) and what the lobby stores on the seat.
    kind = "bot"
    #: Shown in the lobby UI.
    label = "Bot"
    description = ""

    def __init__(self, player_id: str, name: str = "") -> None:
        self.player_id = str(player_id)
        self.name = name or self.label
        #: Actions that raised this run, so a bot that keeps being offered
        #: something it can't actually complete (a block that violates RULE
        #: 702.111b menace, a cast whose targets it picked badly) gives up
        #: on that offer instead of retrying it until the action cap.
        self._failed: set[tuple] = set()
        #: MEC-46: a RULE 701.38 vote has no "safe default" the way a "you
        #: may" prompt does — every option is a real, deliberate choice.
        #: A bot with no evaluation picks one at random, but seeded off its
        #: own id so a bot-vs-bot table still replays identically.
        self._vote_rng = random.Random(hash(self.player_id) & 0xFFFFFFFF)

    def prepare(self, session) -> None:
        """Attach policy-owned session context before reading a fresh view."""

    waiting = False

    # -- The dispatcher ------------------------------------------------

    def decide(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """The next action this bot wants to take, or None for "nothing"."""
        actions = [a for a in actions if self._signature(a) not in self._failed]
        # A pending choice blocks everything else (`GameSession._dispatch`),
        # so it has to be answered before anything is even considered.
        answers = [a for a in actions if a["type"] in ("choose", "decline")]
        if answers:
            return self.answer_choice(view, answers)
        if not view["setup"]["complete"]:
            keep = next((a for a in actions if a["type"] == "keep_hand"), None)
            return self.setup(view, actions) if keep is not None else None
        # RULE 509.1a: declaring blocks is a turn-based action taken by the
        # *defending* player, so it can be offered while somebody else holds
        # priority — it isn't part of the "what do I do on my turn" question
        # below and is answered first.
        offers = [a for a in actions if a["type"] == "declare_blockers"]
        if offers:
            assignments = self.blocks(view, offers)
            if assignments:
                return {"type": "declare_blockers", "assignments": assignments}
        if not self.has_priority(view):
            return None
        return self.play(view, [a for a in actions if a["type"] != "declare_blockers"])

    # -- Policy hooks --------------------------------------------------

    def setup(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
        """RULE 103.4: no bot mulligans — it keeps whatever it was dealt.

        Which means `keep_hand` never has to bottom anything, since
        bottoming is one card per mulligan taken.
        """
        return {"type": "keep_hand", "bottom_instance_ids": []}

    def answer_choice(
        self, view: dict[str, Any], answers: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Answer a `pending_choice`. Default: decline if declining is offered.

        Declining is the choice that changes least, which is what a bot
        with no judgement should prefer — and, for the many "you may …"
        prompts, the one that can't cost it anything.

        MEC-46 exception: a RULE 701.38 vote (`vote` / `vote_object`) never
        offers a decline and has no least-change option, so the bot picks
        one of the offered options at random (`self._vote_rng`, seeded off
        its id — a bot-vs-bot table still replays the same).

        Bug report, 2026-09-04: a fetch land's sacrifice is its own,
        already-paid *cost* — by the time this search choice is even open,
        that land is gone from the battlefield either way, so "declining
        changes least" is backwards here: declining is strictly worse than
        finding *any* legal card, not the safe default. A `"search"` choice
        therefore prefers its first real option over declining (still
        declines when nothing eligible is offered at all — an empty/
        wrong-color library, say, where there's genuinely nothing to lose
        by declining because there's nothing to gain either).

        Bug report, 2026-09-04 (same batch): RULE 903.9a/9b's
        `"commander_zone"` choice ("put the commander into the command
        zone instead") is the same shape — "decline" leaves it stuck in
        the graveyard/exile (or hand/library) it was heading to, which a
        bot has no way to leverage, while the command zone is always
        freely recastable. So this always takes ``"command"`` rather than
        declining, the one choice kind here with a genuine default
        judgement call. Opening-hand permissions (RULE 103.6) likewise
        prefer the offered destination over declining, so bots actually
        use their pregame cards and answer any mandatory follow-up cost.
        """
        kind = (view.get("pending_choice") or {}).get("kind")
        if kind in ("vote", "vote_object") and answers:
            return self._vote_rng.choice(answers)
        # RULE 103.6: use offered opening-hand permissions, including
        # Gemstone Caverns and its mandatory follow-up hand-card exile.
        if kind in ("search", "commander_zone", "opening_hand_battlefield"):
            hit = next((a for a in answers if a["type"] == "choose"), None)
            if hit is not None:
                return hit
        decline = next((a for a in answers if a["type"] == "decline"), None)
        return decline or answers[0]

    def blocks(
        self, view: dict[str, Any], offers: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Blocker → attacker assignments (RULE 509.1a). Default: none."""
        return []

    def play(
        self, view: dict[str, Any], actions: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """What to do while holding priority. Default: nothing (pass)."""
        return None

    # -- Reading the (redacted) view -----------------------------------

    def has_priority(self, view: dict[str, Any]) -> bool:
        return view["state"].get("priority_player_id") == self.player_id

    def is_active(self, view: dict[str, Any]) -> bool:
        return view["state"].get("active_player_id") == self.player_id

    def my_pool(self, view: dict[str, Any]) -> dict[str, int]:
        """This bot's mana pool as ``{colour: amount}`` (RULE 106)."""
        for player in view["state"].get("players", []):
            if player.get("id") == self.player_id:
                pool = player.get("mana_pool") or {}
                return {k: v for k, v in pool.items() if isinstance(v, int)}
        return {}

    def controls(self, view: dict[str, Any], instance_id: Any) -> bool:
        return any(
            obj.get("instance_id") == instance_id and obj.get("controller_id") == self.player_id
            for obj in view["state"].get("battlefield", [])
        )

    def in_command_zone(self, view: dict[str, Any], instance_id: Any) -> bool:
        """Whether ``instance_id`` is this bot's own command zone (RULE 903)."""
        for player in view["state"].get("players", []):
            if player.get("id") != self.player_id:
                continue
            return any(obj.get("instance_id") == instance_id for obj in player.get("command", []))
        return False

    # -- Targeting (RULE 115) ------------------------------------------

    def rank_targets(
        self,
        view: dict[str, Any],
        options: list[dict[str, Any]],
        polarity: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Order one requirement's legal targets. Default: as offered.

        ``polarity`` is the requirement's own `targeting.TargetSpec.
        polarity` hint ("harmful"/"beneficial"/``None`` — see its
        docstring), passed through by `pick_target_groups` for a subclass
        that wants it; unused by this base default.
        """
        return list(options)

    def pick_targets(
        self, view: dict[str, Any], action: dict[str, Any]
    ) -> Optional[list[dict[str, Any]]]:
        """Fill in an offered action's targets, or None if it can't be filled.

        Walks `requirements_with_targets`' output in order and takes the
        top-ranked options for each — the flat, in-order ``targets`` list
        `GameSession._resolve_targets` expects. An "up to N" requirement
        (RULE 115.1a) is filled to N as well; a bot with no judgement has
        no reason to decline a free target, and 0 is what `rank_targets`
        returning nothing already produces.

        `pick_target_groups` wraps this to also report the *per-requirement*
        partition, which is what a spell with 2+ requirements needs (RULE
        115.1, `StackItem.target_groups`).
        """
        groups = self.pick_target_groups(view, action)
        if groups is None:
            return None
        return [pick for group in groups for pick in group]

    def pick_targets_and_groups(
        self, view: dict[str, Any], action: dict[str, Any]
    ) -> Optional[tuple[list[dict[str, Any]], Optional[list[list[dict[str, Any]]]]]]:
        """`pick_targets` plus the groups to send alongside it (``None`` when
        there's only one requirement and nothing to partition)."""
        groups = self.pick_target_groups(view, action)
        if groups is None:
            return None
        flat = [pick for group in groups for pick in group]
        return flat, (groups if len(groups) > 1 else None)

    def pick_target_groups(
        self, view: dict[str, Any], action: dict[str, Any]
    ) -> Optional[list[list[dict[str, Any]]]]:
        """One list of picks per offered requirement, in printed order."""
        requirements = action.get("targets") or []
        groups: list[list[dict[str, Any]]] = []
        for requirement in requirements:
            count = max(1, int(requirement.get("count", 1) or 1))
            ranked = self.rank_targets(
                view, requirement.get("options") or [], requirement.get("polarity")
            )
            if requirement.get("distinct_from_others"):
                # RULE 109.5's "another target creature" (Pit Fight): the
                # other half of the same clause already took one, and this
                # requirement may not repeat it.
                taken = {
                    pick.get("instance_id")
                    for group in groups for pick in group
                    if pick.get("instance_id") is not None
                }
                ranked = [o for o in ranked if o.get("instance_id") not in taken]
            if requirement.get("distinct_controllers"):
                # RULE 601.2c variant ("target creature *each opponent*
                # controls"-shaped): one pick per controller, not N picks
                # off the same board half.
                seen: set[Any] = set()
                unique: list[dict[str, Any]] = []
                for option in ranked:
                    owner = option.get("controller_id") or option.get("player_id")
                    if owner in seen:
                        continue
                    seen.add(owner)
                    unique.append(option)
                ranked = unique
            if len(ranked) < count and not requirement.get("optional"):
                return None
            groups.append(list(ranked[:count]))
        return groups

    # -- Bookkeeping ---------------------------------------------------

    @staticmethod
    def _signature(action: dict[str, Any]) -> tuple:
        """A stable key for "this offer", for the failed-action memory.

        Deliberately coarse for `declare_blockers`: the offers are per
        creature but the *action* is the whole block, so one failure means
        "this bot can't build a legal block here" rather than "not with
        that creature".
        """
        if action["type"] == "declare_blockers":
            return ("declare_blockers",)
        return (
            action["type"],
            action.get("instance_id"),
            action.get("ability_index"),
            str(action.get("mode")),
        )

    def note_failure(self, action: dict[str, Any]) -> None:
        self._failed.add(self._signature(action))
