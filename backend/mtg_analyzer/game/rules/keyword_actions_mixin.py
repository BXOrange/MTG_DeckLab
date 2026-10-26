"""Resolving keyword actions and their continuations."""
from __future__ import annotations

from typing import Any, Optional
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject, Zone
from ...models.game.player import Player
from .. import continuous
from .triggers_mixin import _has_suspend
from .. import continuations


class KeywordActionsMixin:
    """Resolving keyword actions and their continuations."""
    def monstrosity(self, obj: GameObject, amount: int) -> bool:
        """RULE 701.37a: "If this permanent isn't monstrous, put ``amount``
        +1/+1 counters on it and it becomes monstrous."

        One atomic primitive rather than counters-plus-a-flag at the call
        site, for the same reason `RenownEffect` is one (RULE 702.112b): the
        701.37a guard, the counters and the designation are a single
        conditional — a monstrosity ability activated a second time must put
        *no* counters on, which two separate steps would get wrong.

        Returns whether it actually became monstrous, so a caller that has
        follow-up behaviour ("monstrosity 3. When it becomes monstrous, …")
        can tell the no-op case apart. ``amount`` is clamped at 0: a
        "monstrosity X" with X=0 still flips the designation (701.37a puts
        zero counters on, which is a legal number of counters to put on) and
        still fires the trigger.
        """
        if obj.is_monstrous:
            return False
        self.add_counters(obj, max(0, int(amount)), "+1/+1", source=obj)
        obj.is_monstrous = True
        # RULE 701.37c: another ability of this permanent may refer to the X
        # it became monstrous with, so remember the announced value.
        obj.monstrosity_x = max(0, int(amount))
        self.state.fire_event(
            GameEvent(
                EventType.BECAME_MONSTROUS,
                instance_id=obj.instance_id,
                controller_id=obj.controller_id,
                object=obj.name,
                object_types=sorted(obj.type_words),
                amount=obj.monstrosity_x,
            )
        )
        return True
    def adapt(self, obj: GameObject, amount: int) -> bool:
        """RULE 701.46a: "If this permanent has no +1/+1 counters on it, put
        ``amount`` +1/+1 counters on it."

        Monstrosity's sibling and deliberately *not* the same primitive: the
        gate is the permanent's current counters, not a designation, so adapt
        can happen again and again as counters come and go, and there is no
        "becomes adapted" event to fire (701.46 defines no designation — the
        real cards' "as long as ~ has a +1/+1 counter on it" statics read the
        counters directly, which the layer engine's existing ``min_level``
        gate already does).
        """
        if obj.counters.get("+1/+1", 0) > 0 or obj.plus_one_counters > 0:
            return False
        self.add_counters(obj, max(0, int(amount)), "+1/+1", source=obj)
        return True
    def harness(self, obj: GameObject) -> bool:
        """MEC-79 / RULE 701.64a: "Harness [this permanent]" — "if this
        permanent isn't harnessed, it becomes harnessed."

        `monstrosity`'s designation-flip half without the counters or the
        amount: the Marvel Infinity Stones' ``{cost}, {T}: Harness ~`` ability.
        Idempotent (701.64a's guard) and returns whether it actually flipped,
        so a caller with follow-up behaviour can tell the no-op apart. Fires
        `HARNESSED` only on the transition. 701.64b's "stays harnessed until it
        leaves the battlefield" is `GameObject.reset_as_new_object` (RULE 400.7).
        """
        if obj.harnessed:
            return False
        obj.harnessed = True
        self.state.fire_event(
            GameEvent(
                EventType.HARNESSED,
                instance_id=obj.instance_id,
                controller_id=obj.controller_id,
                object=obj.name,
                object_types=sorted(obj.type_words),
            )
        )
        return True
    def recruit(self, player: Player) -> None:
        """"Recruit" (RULE 701.70a — Tales of Middle-earth): ``player`` draws
        a card, then discards a card; if the discarded card was a **nonland**
        card, they create a 1/1 white Human Soldier creature token.

        The "which card to discard" is a `recruit` `pending_choice`
        (`_resume_recruit`) whenever the hand has 2+ cards after the
        draw; one card → discarded with no choice, an empty hand → the
        discard simply doesn't happen (RULE 701.70a is "discard a card", not
        "you may"). The nonland check + token are `_recruit_discard`.
        Deliberately its own small primitive rather than reusing
        `_request_choose_objects`'s ``connive`` machinery — the payoff is a
        token, not a counter on a source, and this shape (draw, then a
        mandatory conditional discard) is the same `explore_bin`/`bolster`
        idiom the other PAR-29 keyword actions use.
        """
        self.draw(player, 1)
        if not player.hand:
            return
        if len(player.hand) == 1:
            self._recruit_discard(player, player.hand[0])
            return
        self.open_choice({
            "kind": "recruit",
            "player_id": player.id,
            "prompt": "Rekrutieren: welche Karte abwerfen?",
            "options": [
                {"id": str(o.instance_id), "label": o.name, "instance_id": o.instance_id}
                for o in player.hand
            ],
        })
    def _recruit_discard(self, player: Player, card: GameObject) -> None:
        """The discard + conditional token half of `recruit` (RULE
        701.70a). ``is_land`` is read before the move — a card-type property
        unaffected by zone, but the obviously-correct order (the same one
        `_apply_chosen_object`'s connive branch uses)."""
        is_land = card.is_land
        self.discard_specific(card)
        if not is_land:
            from ...services.token_database import synthesize_token_card  # function-scoped: avoid cycle

            token = synthesize_token_card(
                name="Soldier", power=1, toughness=1, colors=["W"],
                subtypes=["Human", "Soldier"],
            )
            self.create_token(player.id, token, 1)
    @continuations.choice("recruit", answer=continuations.ANSWER_INT, rule="701.70")
    def _resume_recruit(self, choice: dict[str, Any], instance_id: Optional[int]) -> None:
        """Answer a pending `recruit` discard choice. A missing/unknown answer
        defaults to the first card — RULE 701.70a's discard is mandatory."""
        player = self.state.player_by_id(choice["player_id"])
        offered = [opt["instance_id"] for opt in choice["options"]]
        chosen_id = instance_id if instance_id in offered else (offered[0] if offered else None)
        card = next(
            (o for o in player.hand if o.instance_id == chosen_id), None
        )
        if card is None and player.hand:
            card = player.hand[0]
        if card is not None:
            self._recruit_discard(player, card)
        self.check_state_based_actions()
    def learn(self, player: Player, source: Optional[GameObject] = None) -> None:
        """"Learn" (RULE 701.48a — Strixhaven): ``player`` may **either**
        reveal a Lesson card they own from outside the game and put it into
        their hand, **or** discard a card, then — if they discarded a card
        this way — draw a card.

        **Documented simplification:** the "Lesson from outside the game"
        branch is dropped. This engine has no sideboard / outside-the-game
        zone with any Commander-legal use (the same call the `ability_
        catalogue` already makes for Karn's -2,
        `punishers.py`), so Learn
        collapses to its other, fully-modelable half: an optional
        discard-a-card-then-draw-a-card, driven straight through
        `_request_choose_objects`'s existing ``optional`` + ``then_specs``
        machinery (a real discard fires the draw; a decline does nothing).
        An empty hand → nothing happens (nothing to discard, and the Lesson
        branch is gone).
        """
        if not player.hand:
            return
        self._request_choose_objects(
            player, list(player.hand), "discard", count=1, optional=True,
            prompt="Lernen — eine Karte abwerfen, dann eine Karte ziehen?",
            source=source,
            then_specs=[{"type": "draw", "params": {"count": 1}}],
        )
    def collect_evidence_possible(self, player: Player, amount: int) -> bool:
        """Whether ``player``'s graveyard holds cards whose **total mana
        value** is ``amount`` or greater (RULE 701.59a) — the affordability
        check shared by every "collect evidence N" cost site."""
        total = sum(c.mana_value for c in player.graveyard)
        return total >= amount

    def collect_evidence(self, player: Player, amount: int) -> bool:
        """RULE 701.59a: exile cards from ``player``'s graveyard whose total
        mana value is ``amount`` or greater, then fire
        `EventType.COLLECTED_EVIDENCE` (701.59b — process-complete, fired
        even if ``amount`` was 0). Returns whether the exile met the
        threshold.

        **Documented simplification:** which cards leave is an auto-choice
        — **highest** mana value first, so the *fewest* cards are spent to
        clear the threshold — rather than an interactive pick. The same
        "auto-pick, no chooser in this MVP" idiom `_pay_escape_graveyard_
        cost` / `discard` / `put_hand_cards_on_top` already use for a
        value-neutral cost selection.
        """
        picked: list[GameObject] = []
        running = 0
        for card in sorted(
            player.graveyard, key=lambda c: c.mana_value, reverse=True
        ):
            if running >= amount:
                break
            picked.append(card)
            running += card.mana_value
        met = running >= amount
        for card in picked:
            self.exile(card)
        self.state.fire_event(GameEvent(
            EventType.COLLECTED_EVIDENCE,
            player_id=player.id, controller_id=player.id, amount=amount,
        ))
        return met
    def forage_possible(self, player: Player) -> bool:
        """Whether ``player`` could forage right now (RULE 701.61a) — three
        cards in their graveyard to exile, or a Food they control to
        sacrifice."""
        if len(player.graveyard) >= 3:
            return True
        return any(
            continuous.has_subtype(o, "Food")
            for o in self.state.permanents_controlled_by(player.id)
        )

    def forage(self, player: Player) -> bool:
        """RULE 701.61a: ``player`` exiles three cards from their graveyard
        **or** sacrifices a Food. Fires `EventType.FORAGED` afterwards
        (701.61b — process-complete, fired even if neither was possible).
        Returns whether either option was actually carried out.

        **Documented simplification:** no interactive choice between the two
        halves — a Food is sacrificed whenever ``player`` controls one
        (keeping the three graveyard cards, the strictly more valuable
        line), otherwise the three oldest graveyard cards are exiled (the
        same "auto-pick, no chooser in this MVP" idiom `collect_evidence` /
        `_pay_escape_graveyard_cost` use).
        """
        did = False
        foods = [
            o for o in self.state.permanents_controlled_by(player.id)
            if continuous.has_subtype(o, "Food")
        ]
        if foods:
            self.put_into_graveyard(foods[0])  # RULE 701.17 sacrifice
            did = True
        elif len(player.graveyard) >= 3:
            for card in list(player.graveyard)[:3]:
                self.exile(card)
            did = True
        self.state.fire_event(GameEvent(
            EventType.FORAGED, player_id=player.id, controller_id=player.id,
        ))
        return did
    #: The four bending keyword actions (RULE 701.6x — Avatar: The Last
    #: Airbender). `record_bend`'s ``kind`` is one of these.
    BEND_KINDS = ("waterbend", "earthbend", "firebend", "airbend")
    def record_bend(
        self, player: Player, kind: str, amount: int = 0,
        source: Optional[GameObject] = None,
    ) -> None:
        """Register that ``player`` has performed a bending keyword action
        (RULE 701.6x — ``kind`` in `BEND_KINDS`): stamp `GameState.
        bends_this_turn` (derived from) `EventType.BENT`, which this fires.

        Called from each bending primitive once its own procedure is
        complete — `earthbend` (after the land is animated + countered),
        the waterbend additional-cast-cost payment (RULE 701.67c — "triggers
        whenever that player pays a waterbend cost"), `ExileEffect` with
        ``bend_kind`` set (airbend), and the Firebending attack trigger's
        `RecordBendEffect` marker. Mirrors `collect_evidence`/`forage`/
        `behold`: fire an event so a "whenever you `<bend>`" trigger (Avatar
        Aang) can see an action that otherwise leaves no board trace.
        """
        if kind not in self.BEND_KINDS:
            return
        self.state.fire_event(GameEvent(
            EventType.BENT,
            player_id=player.id, controller_id=player.id,
            kind=kind, amount=int(amount or 0),
        ))
    def behold(
        self, player: Player, quality: str, source: Optional[GameObject] = None
    ) -> bool:
        """"Behold" (RULE 701.4a — Tarkir: Dragonstorm): ``player`` reveals a
        permanent they control with ``quality``, or a card with ``quality``
        from their hand. Returns whether a behold actually happened (a
        matching object existed to reveal), firing `EventType.BEHELD` in
        that case.

        ``quality`` is a creature-type word for every real card that uses
        this (dragon/elf/kithkin/merfolk), matched case-insensitively via
        `continuous.has_subtype` against the printed type line — the same
        substring approach the "tap N Elves you control" cost uses.

        Beholding has no game-state effect of its own; it's the reveal that
        matters at a real table. In this engine it's reached as an
        *additional cast cost* ("behold a dragon or pay {N}") — see
        `GameEngine._pay_additional_cast_cost` and the **documented
        simplification** there (the "or pay {N}" alternative isn't modeled,
        mirroring the existing `_ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE`
        precedent): a spell casts whether or not the behold succeeds.
        """
        revealed: Optional[GameObject] = None
        for obj in self.state.battlefield:
            if obj.controller_id == player.id and continuous.has_subtype(obj, quality):
                revealed = obj
                break
        if revealed is None:
            for card_obj in player.hand:
                if continuous.has_subtype(card_obj, quality):
                    revealed = card_obj
                    break
        if revealed is None:
            return False
        self.state.fire_event(GameEvent(
            EventType.BEHELD,
            player_id=player.id, controller_id=player.id,
            instance_id=revealed.instance_id, quality=quality,
        ))
        return True
    def time_travel(self, player: Player, times: int = 1) -> None:
        """"Time travel" (RULE 701.56a — Doctor Who): "For each suspended
        card you own and each permanent you control with a time counter on
        it, you may add or remove a time counter." ``times`` repeats the
        whole process ("time travel, then time travel").

        **Documented simplification** — no per-object interactive add/
        remove choice: a **suspended card** ``player`` owns loses one time
        counter (acceleration — the reason to time travel your own
        suspended spells; if that empties it, the RULE 702.62a free-cast
        window opens exactly as the upkeep trigger would), and a
        **Vanishing/Fading**-style permanent ``player`` controls (a time
        counter on a battlefield permanent) gains one (prolongs it — the
        reason to time travel those). Both are the beneficial-to-you
        direction. A time counter on something that is neither is left
        alone.
        """
        for _ in range(max(1, int(times))):
            for obj in list(player.exile):
                if obj.owner_id != player.id or obj.counters.get("time", 0) <= 0:
                    continue
                if not _has_suspend(obj):
                    continue
                self.remove_suspend_time_counter(obj)
            for obj in self.state.permanents_controlled_by(player.id):
                if obj.counters.get("time", 0) > 0:
                    obj.add_counters("time", 1)
        self.check_state_based_actions()
    def remove_suspend_time_counter(self, obj: GameObject) -> bool:
        """Remove one time counter in exile and queue its triggered abilities.

        RULE 702.62a: Suspend's cast permission is a separate last-counter
        trigger, so no permission exists before that ability resolves.
        """
        if obj.zone != Zone.EXILE or obj.counters.get("time", 0) <= 0:
            return False
        self.add_counters(obj, -1, "time")
        return obj.counters.get("time", 0) == 0
    def _endure_make_token(self, player: Player, amount: int) -> None:
        """The token half of `endure` (RULE 701.63a) — an N/N white Spirit
        creature token."""
        from ...services.token_database import synthesize_token_card  # function-scoped: avoid cycle

        card = synthesize_token_card(
            name="Spirit", power=amount, toughness=amount, colors=["W"]
        )
        self.create_token(player.id, card, 1)
    def endure(
        self, permanent: Optional[GameObject], amount: int, player: Optional[Player] = None
    ) -> None:
        """"Endure N" (RULE 701.63a — Bloomburrow): the controller of
        ``permanent`` **either** puts N +1/+1 counters on it **or** creates an
        N/N white Spirit creature token.

        A genuine modal choice (`endure` `pending_choice`,
        `_resume_endure`) — but only when the counters branch is
        actually possible: if ``permanent`` has left the battlefield or isn't
        a creature, only the token is available (RULE 608.2b), so it resolves
        without asking. Counters go on through `add_counters` so RULE 122.5
        triggers and doublers apply; the token through `create_token`.
        """
        if amount <= 0:
            return
        controller_id = getattr(permanent, "controller_id", None)
        if player is None and controller_id is not None:
            try:
                player = self.state.player_by_id(controller_id)
            except KeyError:
                player = None
        if player is None:
            return
        counters_possible = (
            permanent is not None
            and getattr(permanent, "is_creature", False)
            and permanent in self.state.battlefield
        )
        if not counters_possible:
            self._endure_make_token(player, amount)
            return
        self.open_choice({
            "kind": "endure",
            "player_id": player.id,
            "amount": amount,
            "permanent_id": permanent.instance_id,
            "prompt": f"Ausharren {amount}: {amount} +1/+1-Marken oder ein {amount}/{amount} weißer Geist-Token?",
            "options": [
                {"id": "counters", "label": f"{amount} +1/+1-Marken auf {permanent.name}"},
                {"id": "token", "label": f"{amount}/{amount} weißer Geist-Token"},
            ],
        })
    @continuations.choice(
        "endure",
        answer=continuations.ANSWER_FLAG,
        yes="token",
        rule="701.63",
    )
    def _resume_endure(self, choice: dict[str, Any], to_token: bool = False) -> None:
        """Answer a pending `endure` choice. A missing/unknown answer defaults
        to the counters branch (the permanent is still there — RULE 701.63a
        has no "you may", one of the two must happen)."""
        player = self.state.player_by_id(choice["player_id"])
        amount = int(choice["amount"])
        perm = self._object_by_instance_id(choice.get("permanent_id"))
        if not to_token and perm is not None and perm in self.state.battlefield:
            self.add_counters(perm, amount, "+1/+1", source=perm)
        else:
            # token chosen, or "it" left the battlefield before resolution
            self._endure_make_token(player, amount)
        self.check_state_based_actions()
    def goad(self, obj: GameObject, goader_id: str, permanent: bool = False) -> None:
        """RULE 701.15a: ``goader_id`` goads ``obj`` until their next turn.

        The designation is stored on the creature as the *set* of players who
        have goaded it (RULE 701.15c — several players goading one creature
        each add their own combat requirement; 701.15d — the same player
        goading twice adds nothing, which a set gives for free). Expiry is
        `GameEngine.begin_turn`'s job: "until the next turn of the
        controller" means the entry is dropped as that player's turn begins.

        ``permanent`` is the "…goaded **for the rest of the game**" wording
        (Rendmaw, Jon Irenicus): same designation, no expiry, so it goes in
        the sibling set the turn-begin sweep leaves alone.

        Goading a creature that isn't a creature, or one already goaded by
        this player, is legal and simply records/re-records the designation —
        the event fires either way, since "whenever you goad" cares that the
        action happened (701.15d only makes the *requirement* a no-op).
        """
        (obj.goaded_permanently if permanent else obj.goaded_by).add(goader_id)
        self.state.fire_event(
            GameEvent(
                EventType.GOADED,
                instance_id=obj.instance_id,
                goader_id=goader_id,
                controller_id=goader_id,
                object=obj.name,
                object_types=sorted(obj.type_words),
            )
        )
    def suspect(self, obj: Optional[GameObject]) -> None:
        """RULE 701.60a: ``obj`` becomes **suspected** (menace + can't block,
        RULE 701.60b — both read off `GameObject.is_suspected` at combat
        time, `combat.is_suspected`).

        A no-op if ``obj`` isn't a creature. Re-suspecting an already-
        suspected creature is legal and changes nothing (RULE 701.60c), but
        the event fires either way — "whenever you suspect a creature" cares
        that the action happened, mirroring `goad`.
        """
        if obj is None or not getattr(obj, "is_creature", False):
            return
        # PAR-30 Suspect one-off shapes / RULE 701.60c — a static "can't
        # become suspected" (Airtight Alibi, hand-authored) rides a
        # ``grant_keyword`` slug the layer engine stamps onto the affected
        # creature; honour it here, the one place the designation is applied.
        if "cant_become_suspected" in getattr(obj, "granted_keywords", ()):
            return
        obj.is_suspected = True
        self.state.fire_event(
            GameEvent(
                EventType.SUSPECTED,
                instance_id=obj.instance_id,
                controller_id=obj.controller_id,
                object=obj.name,
                object_types=sorted(obj.type_words),
            )
        )
    def detain(self, obj: Optional[GameObject], detainer_id: str) -> None:
        """RULE 701.35a: ``detainer_id`` detains ``obj`` until their next turn.

        Stored as the *set* of players detaining it (mirroring `goad` — in
        practice always one), so `GameEngine.begin_turn` can drop it the same
        way it drops goad, "until the next turn of the controller of the
        spell or ability" (RULE 701.35b). While detained, RULE 701.35b's
        three consequences — can't attack, can't block, activated abilities
        can't be activated — are enforced by `_can_attack` / `can_block` /
        `can_activate` consulting `combat.is_detained`.

        A no-op-safe re-detain (already detained by this player) still fires
        the event, like `goad`/`suspect`.
        """
        if obj is None or getattr(obj, "instance_id", None) is None:
            return
        obj.detained_by.add(detainer_id)
        self.state.fire_event(
            GameEvent(
                EventType.DETAINED,
                instance_id=obj.instance_id,
                detainer_id=detainer_id,
                controller_id=detainer_id,
                object=obj.name,
                object_types=sorted(obj.type_words),
            )
        )
    def remove_suspected(self, objs: list[GameObject]) -> None:
        """"... is/are no longer suspected." (RULE 701.60a's reverse) — clear
        the designation on each of ``objs``. Used both for the mass
        "all suspected creatures are no longer suspected" (Absolving Lammasu)
        and a single named creature."""
        for obj in objs:
            if obj is not None:
                obj.is_suspected = False
    def clash(
        self,
        player: Optional[Player],
        with_opponent: bool = True,
        source: Optional[GameObject] = None,
    ) -> bool:
        """RULE 701.30: ``player`` clashes — reveals the top card of their
        library — and, for "clash with an opponent" (``with_opponent``, RULE
        701.30b), one opponent reveals theirs too. Returns whether ``player``
        **won** (RULE 701.30d — their revealed card's mana value is strictly
        higher than every other card revealed in the clash), which the "if
        you win, `<effect>`. / otherwise, `<effect>`." branch reads back via
        `effects.ClashEffect` → `GameContext.clash_won`.

        After revealing, each player who revealed a card chooses whether it
        stays on top or goes on the bottom.  The choices are asked in APNAP
        order and the selected cards move only after all answers, as RULE
        701.30c requires.  `GameState.clash_revealed` makes both faces public
        to every board view while that decision is in progress.

        With no opponent at all (a 1-player Goldfisch/Replay board) or every
        opponent's library empty, no *other* card is revealed, so ``player``
        wins on the strength of their own reveal alone — a deliberate reading
        of 701.30b's "choose an opponent" when there is none, keeping clash
        cards functional in solo play. If ``player``'s own library is empty
        they reveal nothing and cannot win.

        Fires `EventType.CLASHED` (always, for "whenever you clash") and
        `EventType.WON_CLASH` (only on a win, for "whenever you win a clash").
        """
        if player is None:
            return False
        top = player.library[-1] if player.library else None
        my_mv = top.mana_value if top is not None else -1
        revealed: list[tuple[Player, GameObject]] = []
        if top is not None:
            revealed.append((player, top))
        other_mvs: list[int] = []
        #: RULE 701.30b: which opponent this clash was "with" — recorded so a
        #: following "if you win, `<X> that player <does Y>`" / "otherwise,
        #: that player …" branch (Captivating Glance, Pollen Lullaby) has a
        #: referent. **Documented simplification** (same as `GainControlBy
        #: SourceEffect`): the first living opponent, not an interactive
        #: "choose an opponent" pick — unambiguous in 1v1 goldfish/Replay,
        #: auto-picked in multiplayer. Read back via `effects.ClashEffect`
        #: → `GameContext.clashed_opponent`.
        self._last_clash_opponent_id = None
        if with_opponent:
            for opp in self.state.living_players():
                if opp.id == player.id:
                    continue
                if self._last_clash_opponent_id is None:
                    self._last_clash_opponent_id = opp.id
                opp_top = opp.library[-1] if opp.library else None
                if opp_top is not None:
                    other_mvs.append(opp_top.mana_value)
                    revealed.append((opp, opp_top))
                # RULE 701.30b is one opponent, not every opponent.  Choosing
                # the first living one remains this engine's documented
                # multiplayer simplification.
                break
        won = top is not None and all(my_mv > mv for mv in other_mvs)
        self.state.clash_revealed = [obj.instance_id for _, obj in revealed]
        self.state.fire_event(GameEvent(
            EventType.CLASHED, player_id=player.id, controller_id=player.id, won=won,
        ))
        if won:
            self.state.fire_event(GameEvent(
                EventType.WON_CLASH, player_id=player.id, controller_id=player.id,
            ))
        self._open_clash_choice(revealed, source=source)
        return won

    def _open_clash_choice(
        self,
        revealed: list[tuple[Player, GameObject]],
        *,
        source: Optional[GameObject] = None,
        queue: Optional[list[tuple[str, int]]] = None,
        bottom: Optional[list[tuple[str, int]]] = None,
    ) -> None:
        """Open the next RULE 701.30c clash-placement decision in APNAP order.

        The cards stay in their libraries throughout all choices; only the
        final branch moves every elected card to its owner's library bottom.
        This keeps the public reveal visible and avoids one player's decision
        changing another player's "top card" midway through the action.
        """
        if queue is None:
            by_player = {p.id: obj.instance_id for p, obj in revealed}
            living = self.state.living_players()
            start = next(
                (i for i, p in enumerate(living) if p.id == self.state.active_player.id), 0
            )
            ordered = living[start:] + living[:start]
            queue = [(p.id, by_player[p.id]) for p in ordered if p.id in by_player]
        bottom = list(bottom or [])
        if not queue:
            for player_id, instance_id in bottom:
                owner = self.state.player_by_id(player_id)
                obj = self._object_by_instance_id(instance_id)
                if obj is not None and obj in owner.library:
                    owner.library.remove(obj)
                    owner.library.insert(0, obj)
            self.state.clash_revealed = []
            return
        player_id, instance_id = queue[0]
        chooser = self.state.player_by_id(player_id)
        card = self._object_by_instance_id(instance_id)
        if card is None or card not in chooser.library:
            self._open_clash_choice(revealed, source=source, queue=queue[1:], bottom=bottom)
            return
        self.open_choice({
            "kind": "clash",
            "player_id": chooser.id,
            "instance_id": card.instance_id,
            "queue": list(queue),
            "bottom": bottom,
            "source_name": source.name if source is not None else None,
            "prompt": "Clash: Lege deine aufgedeckte Karte oben oder unten in deine Bibliothek?",
            "options": [
                {"id": "top", "label": "Oben lassen"},
                {"id": "bottom", "label": "Unter die Bibliothek legen"},
            ],
        })

    @continuations.choice("clash", answer=continuations.ANSWER_STR, rule="701.30")
    def _resume_clash_choice(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Record one clash placement, then ask the next APNAP player."""
        queue = [(str(pid), int(iid)) for pid, iid in choice.get("queue", [])]
        bottom = [(str(pid), int(iid)) for pid, iid in choice.get("bottom", [])]
        if not queue:
            raise ValueError("clash choice has no queued card")
        player_id, instance_id = queue[0]
        if answer == "bottom":
            bottom.append((player_id, instance_id))
        elif answer not in ("top", None):
            raise ValueError(f"{answer!r} is not a legal clash choice")
        self._open_clash_choice(
            [], queue=queue[1:], bottom=bottom,
        )
