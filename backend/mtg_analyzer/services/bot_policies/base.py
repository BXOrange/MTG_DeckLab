"""Bot policy; shared registry/driver is services.bots."""
from __future__ import annotations

import random
import hashlib
import json
from typing import Any, Optional



#: The only pre-combat step where `play` has had its sorcery-speed window;
#: arming a yield earlier would skip that window entirely.
PRE_COMBAT_STEPS = ("main1",)

#: Steps after attackers were (or were not) declared; a bot that did nothing
#: by then has nothing left before its end step.
POST_ATTACK_STEPS = ("declare_attackers", "declare_blockers", "combat_damage", "end_combat", "main2")

#: Own-turn windows a bot keeps: its attack declaration and end-step plays.
BOT_OWN_STOPS = ("declare_attackers", "end")

#: Opponent-turn windows stay as before; "Pass this turn" decides there.
ALL_STEPS = ("upkeep", "draw", "main1", "begin_combat", "declare_attackers",
             "declare_blockers", "combat_damage", "end_combat", "main2", "end")


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
        self.action_feedback: list[dict[str, Any]] = []
        #: MEC-46: a RULE 701.38 vote has no "safe default" the way a "you
        #: may" prompt does — every option is a real, deliberate choice.
        #: A bot with no evaluation picks one at random, but seeded off its
        #: own id so a bot-vs-bot table still replays identically.
        self._vote_rng = random.Random(hash(self.player_id) & 0xFFFFFFFF)

    def prepare(self, session) -> None:
        """Attach policy-owned session context before reading a fresh view."""
        view = session.view(perspective=self.player_id)
        position = json.dumps({'state': view['state'], 'setup': view['setup'],
                               'priority': view.get('priority'),
                               'actions': view.get('legal_actions')}, sort_keys=True)
        key = hashlib.sha256(position.encode()).hexdigest()
        contexts = getattr(session, '_bot_failure_context', {})
        memory = contexts.setdefault(self.player_id, {})
        if memory.get('position') != key:
            memory.update(position=key, failed=set(), feedback=[])
        self._failed = memory['failed']
        self.action_feedback = memory['feedback']
        session._bot_failure_context = contexts

    waiting = False

    # -- The dispatcher ------------------------------------------------

    def decide(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """The next action this bot wants to take, or None for "nothing"."""
        failed_blocks = ('declare_blockers',) in self._failed and any(
            a['type'] == 'declare_blockers' for a in actions)
        actions = [a for a in actions if self._signature(a) not in self._failed]
        # A pending choice blocks everything else (`GameSession._dispatch`),
        # so it has to be answered before anything is even considered.
        answers = [a for a in actions if a["type"] in ("choose", "decline")]
        if answers:
            answer = self.answer_choice(view, answers)
            if answer is None and self.waiting:
                return None
            return self._offered_choice(view, answers, answer)
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
        if failed_blocks:
            return {"type": "declare_blockers", "assignments": []}
        if not self.has_priority(view):
            return None
        # VIS-12: a bot accepts "Pass this turn" exactly as a human can arm
        # it — through the same `set_yield` action — but only when its own
        # policy says it would pass every remaining window of this turn.
        if self.wants_turn_yield(view, actions):
            return {"type": "set_yield", "mode": "turn"}
        if self.wants_own_turn_stops(view):
            return {"type": "set_stops", "own": list(BOT_OWN_STOPS), "opponent": list(ALL_STEPS)}
        action = self.play(view, [a for a in actions if a["type"] != "declare_blockers"])
        if action is None and self.wants_end_step_yield(view, actions):
            return {"type": "set_yield", "mode": "end_step"}
        return action

    def _offered_choice(self, view, answers, answer):
        """Keep policy decisions inside the server's current choice contract."""
        if isinstance(answer, dict):
            if answer.get("type") == "decline":
                offered = next((a for a in answers if a["type"] == "decline"), None)
                if offered is not None:
                    return dict(offered)
            elif answer.get("type") == "choose":
                pending = view.get("pending_choice") or {}
                if "option_ids" in answer:
                    # Atomic Proliferate picks are parameterized, but every member
                    # must still come from the offered set for this selection.
                    ids = answer["option_ids"]
                    offered_ids = {a.get("option_id") for a in answers if a["type"] == "choose"}
                    if (pending.get("kind") == "proliferate"
                            and answer.get("selection_id") == pending.get("selection_id")
                            and isinstance(ids, list) and all(isinstance(i, str) for i in ids)
                            and len(set(ids)) == len(ids) and set(ids) <= offered_ids):
                        return answer
                else:
                    option_id = answer.get("option_id", answer.get("instance_id"))
                    for offered in answers:
                        if offered["type"] != "choose":
                            continue
                        if offered.get("free_text"):
                            return answer
                        if option_id is not None and str(option_id) == str(offered.get("option_id")):
                            return dict(offered)
        # A policy may rank options; it cannot invent a new option or pass
        # instead of answering a mandatory choice. Keep a visible diagnostic
        # and use the base policy on the same, still-untried offers.
        self.action_feedback.append({"action": answer, "reason": "Bot choice was not offered"})
        self.action_feedback[:] = self.action_feedback[-3:]
        return Bot.answer_choice(self, view, answers)

    # -- Policy hooks --------------------------------------------------

    def can_pass_turn(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> bool:
        """VIS-12 heuristic gate: would this bot pass every remaining
        priority window of the opponent's turn it is looking at?

        Answering yes lets it arm "Pass this turn" (`set_yield`), which skips
        its remaining windows — and the one-bot-action-per-poll tick each
        would cost in Solo — while the server still hands it priority the
        moment another player has a spell or ability on the stack
        (`GameSession._yield_wants_pass`). So the question is only about
        windows with an *empty* stack. Default: no — an unknown policy never
        gives up windows it might want; each subclass states its own.
        """
        return False

    def wants_turn_yield(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> bool:
        """Whether to arm "Pass this turn" now. Read off the bot's own
        (redacted) view only, like everything else it does: a shared game, an
        opponent's turn, nothing armed yet, an empty stack and no pending
        choice — then the policy's `can_pass_turn` decides. The server
        validates the action anyway."""
        priority = view.get("priority") or {}
        state = view["state"]
        if not priority.get("interactive") or self.is_active(view):
            return False
        if (priority.get("yields") or {}).get(self.player_id):
            return False
        if state.get("stack") or state.get("game_over") or view.get("pending_choice"):
            return False
        return self.can_pass_turn(view, actions)

    #: Whether this policy skips its own remaining windows once `play` has
    #: nothing left to do. Off by default: only policies whose `play` is a
    #: complete statement of what they want opt in.
    skips_to_end_step = False

    def wants_end_step_yield(self, view: dict[str, Any], actions: list[dict[str, Any]]) -> bool:
        """Own-turn counterpart of `wants_turn_yield`: `play` returned nothing,
        so arm "Skip to end step" instead of burning one pass per step. Only
        after combat, or earlier only when it has no untapped creature (attackers
        offered at declare-attackers must not be swallowed by a yield). The
        server holds priority at the end step, so end-step instants remain
        possible, and still stops for any opponent stack item."""
        priority = view.get("priority") or {}
        state = view["state"]
        if not self.skips_to_end_step or not priority.get("interactive") or not self.is_active(view):
            return False
        if (priority.get("yields") or {}).get(self.player_id):
            return False
        if state.get("stack") or state.get("game_over") or view.get("pending_choice"):
            return False
        # Holding an instant or a usable ability means it may still want to act
        # this turn: then it must not give up its windows.
        if not self.can_pass_turn(view, actions):
            return False
        step = state.get("current_step")
        if step in POST_ATTACK_STEPS:
            return True
        if step not in PRE_COMBAT_STEPS:
            return False
        # Before combat: only when no creature could attack, so the yield
        # cannot swallow the attack declaration.
        return not any(
            o.get("controller_id") == self.player_id and o.get("is_creature")
            and not o.get("tapped") and not o.get("summoning_sick")
            for o in state.get("battlefield", [])
        )

    def wants_own_turn_stops(self, view: dict[str, Any]) -> bool:
        """Whether to replace the default "stop at every step" with the
        steps a bot can use: attack declaration and the end step (the
        mains are always kept). Upkeep and draw have nothing to offer, so
        the server passes them instead of costing a tick each."""
        priority = view.get("priority") or {}
        if not self.skips_to_end_step or not priority.get("interactive"):
            return False
        return (priority.get("stops") or {}).get(self.player_id) is None

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
        if kind == "opponent_target" and answers:
            return self.pick_opponent_target(view, answers)
        if kind == "opponent_chooser" and answers:
            return self.pick_opponent_chooser(view, answers)
        if kind == "legend_rule" and answers:
            # RULE 704.5j: keep the copy worth most (counters raise its visible power/toughness).
            return max((a for a in answers if a["type"] == "choose"),
                       key=lambda a: self._option_worth(view, a), default=answers[0])
        if kind == "blight" and answers:
            return self.pick_blight_creature(view, answers)
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

    def pick_blight_creature(
        self, view: dict[str, Any], answers: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """RULE 701.68: the creature this bot puts its own -1/-1 counters on -- the one it can least miss.

        Prefers a creature that survives the counters, then the lowest `_option_worth`, so tokens and spent bodies
        are blighted before the board's best creature (the generic fallback took whatever was offered first)."""
        amount = int((view.get("pending_choice") or {}).get("amount") or 1)
        choices = [a for a in answers if a["type"] == "choose"] or answers

        def cost(answer: dict[str, Any]) -> tuple[int, int]:
            obj = self._visible_object(view, answer) or {}
            dies = int((obj.get("toughness") or 0) <= amount)
            return dies, self._option_worth(view, answer)

        return min(choices, key=cost)

    def _option_worth(self, view: dict[str, Any], answer: dict[str, Any]) -> int:
        """A crude "how much is this permanent worth" for choosing among offered targets: power + toughness + mana
        value off the (redacted) view, 0 for a player or anything not visible."""
        obj = self._visible_object(view, answer)
        return sum(int(obj.get(key) or 0) for key in ("power", "toughness", "mana_value")) if obj else 0

    @staticmethod
    def _visible_object(view: dict[str, Any], answer: dict[str, Any]) -> Optional[dict[str, Any]]:
        """The battlefield or graveyard object an offered option names, as the bot's own view shows it."""
        state = view["state"]
        pools = [state.get("battlefield", [])] + [p.get("graveyard", []) for p in state.get("players", [])]
        return next((o for pool in pools for o in pool if o.get("instance_id") == answer.get("instance_id")), None)

    def pick_opponent_target(
        self, view: dict[str, Any], answers: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """MEC-118 (RULE 601.2c): this bot is the opponent picking a target for someone else's spell or ability.

        Reads only its own view. Against a harmful effect (the default: anything not marked beneficial) it hands the
        spell's controller as much damage to their own side as the pool allows -- their most valuable permanent --
        and otherwise sacrifices its own least valuable one; for an effect that helps its target (a return from the
        graveyard, polarity unset) the reverse."""
        pending = view.get("pending_choice") or {}
        controller = pending.get("controller_id")
        beneficial = pending.get("polarity") != "harmful"
        choices = [a for a in answers if a["type"] == "choose"] or answers

        def side(answer: dict[str, Any]) -> int:
            # 1 = the spell controller's own object or the controller as a player, 0 = anything else.
            if answer.get("option_id") == controller:
                return 1
            obj = self._visible_object(view, answer)
            return int(obj is not None and (obj.get("controller_id") or obj.get("owner_id")) == controller)

        hurts_them = [a for a in choices if side(a) == (0 if beneficial else 1)]
        if hurts_them:
            return max(hurts_them, key=lambda a: self._option_worth(view, a))
        return min(choices, key=lambda a: self._option_worth(view, a))

    def pick_opponent_chooser(
        self, view: dict[str, Any], answers: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """MEC-118: this bot controls the spell and names the opponent who will pick its target. Default: the
        first one offered (no judgement about which opponent would choose worst)."""
        return next((a for a in answers if a["type"] == "choose"), answers[0])

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
                # ENG-52: a player pick is keyed by ``player_id`` ("any other target" can be a player).
                taken = {
                    (pick.get("player_id"), pick.get("instance_id"))
                    for group in groups for pick in group
                    if pick.get("instance_id") is not None or pick.get("player_id") is not None
                }
                ranked = [o for o in ranked if (o.get("player_id"), o.get("instance_id")) not in taken]
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
            action.get("option_id"),
        )

    def note_failure(self, action: dict[str, Any], reason: str = "") -> None:
        self.action_feedback.append({"action": dict(action), "reason": reason})
        self.action_feedback[:] = self.action_feedback[-3:]
        self._failed.add(self._signature(action))
        if action['type'] == 'attack':
            for instance_id in action.get('instance_ids', []):
                self._failed.add(self._signature({'type': 'attack', 'instance_id': instance_id}))
