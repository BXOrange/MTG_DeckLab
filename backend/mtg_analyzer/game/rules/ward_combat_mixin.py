"""Counter payments, ward and attack-triggered keyword actions."""
from __future__ import annotations

from typing import Any, Optional
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject
from ...models.game.game_state import StackItem
from ...models.mana.mana_cost import ManaCost
from ...models.game.player import Player
from .. import combat, continuous
from ..costs import ActivationCost, parse_activation_cost
from ..effects.core import AddCountersEffect, PumpEffect, TriggeredAbility, WardEffect
from .. import continuations


class WardCombatMixin:
    """Counter payments, ward and attack-triggered keyword actions."""
    def counter_unless_pays(
        self,
        target: Any,
        unless_pays: Optional[str],
        source: Optional[GameObject] = None,
        suspend_time_counters: Optional[int] = None,
        on_pay_effect_specs: Optional[list[dict]] = None,
        tap_lands_empty_pool_if_unpaid: bool = False,
        exile_instead: bool = False,
        library_choice: bool = False,
        destination: Optional[str] = None,
    ) -> None:
        """`CounterSpellEffect`'s resolve-time logic (RULE 118/601/701.5).

        ``exile_instead`` only applies to the plain (no ``unless_pays``) counter. ``destination`` (Syncopate-style
        "unless its controller pays {X}. If that spell is countered this way, exile it instead …") applies on every
        branch that ends in the spell being countered, the declined and the cannot-pay ones included.

        Refuses outright if ``target`` carries a "can't be countered" marker
        (RULE 118 — the spell stays on the stack, unaffected). With no
        ``unless_pays`` cost this is a plain `counter_spell`. Otherwise it's
        RULE 601's "Mana Leak" template: if the target's controller *can*
        pay ``unless_pays``, this opens an interactive `counter_unless_pays`
        `pending_choice` for them (`_resume_counter_unless_pays`
        finishes it); a controller who genuinely cannot pay has no real
        decision, so the spell is simply countered without pausing — this is
        also what keeps a passive goldfish-dummy opponent (who never holds
        mana) from stalling resolution on a choice nobody can act on.

        ``suspend_time_counters`` (Delay, MEC-42) is threaded straight
        through to every `counter_spell` call this method makes, including
        the interactive decline path (stashed as `_pending_counter_suspend`,
        the same convention `_pending_counter_target`/`_pending_counter_cost`
        already use) — no real card combines "unless pays" with Delay's own
        redirect today, but nothing here assumes they're mutually exclusive.

        ``on_pay_effect_specs`` (Assimilate Essence — "…unless its
        controller pays {4}. If they do, you incubate 2.") are serialized
        `EffectSpec` dicts applied *only* on the branch where the target's
        controller pays, from `_resume_counter_unless_pays` — stashed
        alongside the other `_pending_counter_*` fields. Inert on every
        branch that ends in a `counter_spell` (they didn't pay).
        """
        item = self._stack_item_for(target)
        if item is None or item.obj is None:
            return
        obj = item.obj
        if self._is_cant_be_countered(obj):
            return
        countered_by = self.context.resolving_controller_id or getattr(source, "controller_id", None)
        if not unless_pays:
            self.counter_spell(
                target, suspend_time_counters=suspend_time_counters, countered_by=countered_by,
                exile_instead=exile_instead, library_choice=library_choice, destination=destination,
            )
            return
        cost = ManaCost.parse(unless_pays)
        if cost.has_variable:
            cost = cost.with_x(getattr(source, "x_paid", 0) or 0)
        controller = self.state.player_by_id(obj.controller_id)
        if controller is None or not controller.mana_pool.can_pay(
            cost, life_available=controller.life
        ):
            self.counter_spell(
                target, suspend_time_counters=suspend_time_counters, countered_by=countered_by, destination=destination,
            )
            if tap_lands_empty_pool_if_unpaid and controller is not None:
                self._tap_lands_and_empty_pool(controller)  # couldn't pay = "doesn't"
            return
        self._pending_counter_tap_penalty = bool(tap_lands_empty_pool_if_unpaid)
        self._pending_counter_target = target
        self._pending_counter_cost = cost
        self._pending_counter_suspend = suspend_time_counters
        self._pending_counter_destination = destination
        self._pending_counter_on_pay_specs = list(on_pay_effect_specs or [])
        self._pending_counter_on_pay_source = source
        self.open_choice({
            "kind": "counter_unless_pays",
            "countered_by": countered_by,
            "player_id": controller.id,
            "prompt": f"{obj.name}: {unless_pays} zahlen, um es vor dem Countern zu bewahren?",
            "options": [
                {"id": "pay", "label": f"{unless_pays} zahlen"},
                {"id": "decline", "label": "Nicht zahlen"},
            ],
        })
    @continuations.choice("counter_unless_pays", answer=continuations.ANSWER_STR, rule="118.3")
    def _resume_counter_unless_pays(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `counter_unless_pays` choice (RULE 601).

        ``answer == "pay"`` deducts the cost from the target spell's
        controller and leaves it on the stack, then applies any
        ``on_pay_effect_specs`` stashed for this choice (Assimilate
        Essence's "If they do, you incubate 2."); anything else (``None``/
        ``"decline"``) counters it and the on-pay effects never fire.
        """
        target = self._pending_counter_target
        cost = self._pending_counter_cost
        suspend_time_counters = getattr(self, "_pending_counter_suspend", None)
        destination = getattr(self, "_pending_counter_destination", None)
        self._pending_counter_destination = None
        on_pay_specs = list(getattr(self, "_pending_counter_on_pay_specs", None) or [])
        on_pay_source = getattr(self, "_pending_counter_on_pay_source", None)
        tap_penalty = bool(getattr(self, "_pending_counter_tap_penalty", False))
        self._pending_counter_tap_penalty = False
        penalised = self._stack_item_for(target) if target is not None else None
        penalised_player = (
            self.state.player_by_id(penalised.obj.controller_id)
            if penalised is not None and penalised.obj is not None else None
        )
        self._pending_counter_target = None
        self._pending_counter_cost = None
        self._pending_counter_suspend = None
        self._pending_counter_on_pay_specs = []
        self._pending_counter_on_pay_source = None
        if target is None:
            return
        if answer == "pay" and cost is not None:
            item = self._stack_item_for(target)
            if item is not None and item.obj is not None:
                controller = self.state.player_by_id(item.obj.controller_id)
                if controller is not None:
                    life_spent = controller.mana_pool.pay(cost, life_available=controller.life)
                    self.lose_life(controller, life_spent, cause="cost")
            if on_pay_specs:
                self._apply_effect_specs(on_pay_specs, on_pay_source)
            return
        self.counter_spell(
            target, suspend_time_counters=suspend_time_counters,
            countered_by=choice.get("countered_by"), destination=destination,
        )
        if tap_penalty and penalised_player is not None:
            self._tap_lands_and_empty_pool(penalised_player)  # Power Sink: "if that player doesn't"
    def _tap_lands_and_empty_pool(self, player: Player) -> None:
        """"…they tap all lands with mana abilities they control and lose all unspent mana." (Power Sink)
        Every untapped land ``player`` controls that has a mana ability is tapped (without producing mana —
        it is a penalty, not a payment), then the mana pool is emptied (RULE 106.4)."""
        from ..mana_abilities import mana_abilities_for  # function-scoped: mana_abilities imports the models

        for permanent in list(self.state.permanents_controlled_by(player.id)):
            if permanent.is_land and not permanent.tapped and mana_abilities_for(permanent, self.state):
                self.set_tapped(permanent, True)
        player.mana_pool.empty()
    def _fire_becomes_target_events(self, item: StackItem) -> None:
        """MEC-19: fire `EventType.BECOMES_TARGET` once per target of
        ``item`` — see that constant's own docstring for the full field
        list and the reasoning for piggy-backing on `check_ward`'s own
        choke point rather than a fourth call site. Ward itself is
        untouched by this (still its own direct RULE 702.21 cast-time
        check, right below); this is a parallel, general-purpose event so
        anything else can key a trigger off "became a target" the same way
        it already can for damage/counters/etc.
        """
        for index, target in enumerate(item.targets or []):
            if (isinstance(target, GameObject) and index < len(item.target_incarnations)
                    and item.target_incarnations[index] not in (None, target.zone_incarnation)):
                continue  # RULE 400.7 / 707.10c: an unchanged stale target is not this new object.
            if isinstance(target, GameObject):
                is_player = False
                instance_id: Optional[str] = target.instance_id
                target_controller_id: Optional[str] = target.controller_id
            elif isinstance(target, Player):
                is_player = True
                instance_id = None
                target_controller_id = None
            else:
                continue  # not a real RULE 115 target (e.g. an already-resolved value)
            self.state.fire_event(GameEvent(
                EventType.BECOMES_TARGET,
                instance_id=instance_id,
                instance_zone_incarnation=getattr(target, "zone_incarnation", None),
                target_controller_id=target_controller_id,
                is_player=is_player,
                controller_id=item.controller_id,
                # The acting player — "…becomes the target of a spell an
                # opponent controls, ~ deals 3 damage to **that player**"
                # (Thunderbreak Regent): `event_player` reads ``player_id``.
                player_id=item.controller_id,
                item_kind=item.kind,
                item_category=item.category,
                stack_id=item.stack_id,
            ))
    def check_ward(self, item: StackItem, caster: Player, *, defer_stack: bool = False) -> list[StackItem]:
        """RULE 702.21/601.2c/603.3: after ``item`` (a spell, activated
        ability, or triggered ability) is placed on the stack with its final
        targets — fire MEC-19's RULE 603.1 "becomes the target of a spell/
        ability" event for every target (`_fire_becomes_target_events`, see
        `EventType.BECOMES_TARGET`'s own docstring), then push a genuine ward
        triggered-ability `StackItem` for every target that has ward against
        ``caster`` — one per warded target (RULE 702.21c), each on top of
        ``item``.

        This is what makes ward rules-accurate rather than an inline choice:
        like any triggered ability, it becomes its own object on the stack
        (RULE 603.3 — "the next time a player would receive priority"), so
        both players get a normal priority window to respond to *it* (cast
        an instant, activate an ability) before it resolves, and it resolves
        before ``item`` since it went on top (RULE 608.1 LIFO) — see
        `resolve_ward_effect` for the resolution itself. Constructed and
        pushed directly here (not via the generic `TriggeredAbility`/event
        pipeline `_collect_triggers` drives) because each firing needs its
        own per-instance data (which item, which caster) baked in — a
        `TriggeredAbility` binds one fixed `effects` list once at
        bind-on-load and reuses it for every firing, which can't carry that.

        Controlled by the warded permanent (RULE 603.3a: a triggered
        ability's controller is whoever controlled its source when it
        triggered) — the caster only *pays* it, they don't control it.

        A no-op when ``item`` targets nothing warded — the overwhelming
        common case — so every call site can call this unconditionally right
        after a spell/ability's targets are finalized. The method keeps its
        ward-specific name (every call site already reads it that way) even
        though it's now also the one choke point `BECOMES_TARGET` fires
        from — a second, sibling call at each of the three sites would risk
        a future call site adding one but not the other.
        """
        if self._open_opponent_slots(item):
            # MEC-118: an opponent still has a target to pick; the targets are announced (and warded) once all are in.
            return []
        # Sequential copy instructions capture the trigger now but place it
        # after their choices finish, preserving source/controller/cost LKI.
        self._fire_becomes_target_events(item)
        wards = []
        for index, target in enumerate(item.targets or []):
            if (isinstance(target, GameObject) and index < len(item.target_incarnations)
                    and item.target_incarnations[index] not in (None, target.zone_incarnation)):
                continue  # RULE 400.7 / 707.10c: an unchanged stale target is not this new object.
            if not isinstance(target, GameObject) or target not in self.state.permanents():
                continue  # RULE 702.21: ward functions on battlefield permanents.
            ward = (getattr(target, "parametric_keywords", None) or {}).get("ward")
            cost_text = ward.get("cost") if ward else None
            if not cost_text:
                # A *granted* Ward (`GrantWardEffect` — Hexing Squelcher's
                # "Other creatures you control have 'Ward—Pay 2 life.'"),
                # unlike this object's own printed keyword above — a
                # separate field since `parametric_keywords` is bound once
                # from the card's own text (`models/game_object.py`) and
                # never re-derived by `continuous.recompute` the way a
                # flag `granted_keywords` entry is.
                cost_text = getattr(target, "granted_ward_cost", None)
            if target.controller_id == caster.id:
                continue  # "opponent" doesn't include its own controller
            if not cost_text:
                continue  # no ward, or cost couldn't be recognized from the card text
            cost = parse_activation_cost(cost_text)
            wards.append(
                StackItem(
                    kind="ability",
                    controller_id=target.controller_id,
                    effects=[WardEffect(item, caster.id, cost, source=target)],
                    description=f"Ward {cost.label()} ({target.name})",
                    source=target,
                )
            )
        if not defer_stack:
            self.state.stack.extend(wards)
        return wards
    def resolve_ward_effect(
        self,
        item: StackItem,
        caster_id: str,
        cost: ActivationCost,
        ability_controller_id: Optional[str] = None,
    ) -> None:
        """A ward ability's own resolution (RULE 702.21a) — the caster pays
        ``cost`` (any mix of mana/life/discard/sacrifice, the same
        vocabulary `costs.parse_activation_cost` gives an activated
        ability's cost) or ``item`` is countered.

        A no-op if ``item`` already left the stack (RULE 608.2b: nothing
        left to counter — e.g. an earlier simultaneous ward already
        countered it, RULE 702.21c) — this is also where "look back in
        time" naturally falls out: the caster and cost were fixed when
        `check_ward` triggered, so nothing about the warded permanent's
        current state matters here — *except* an unresolved ``{X}`` in
        ``cost.mana`` (RULE 702.21b): "some ward abilities include an X in
        their cost and state what X is equal to. This value is determined
        at the time the ability resolves, not locked in as the ability
        triggers" — resolved fresh right here, against the *current* board,
        scoped to ``ability_controller_id`` (the warded permanent's
        controller — RULE 603.3a, who controls this ability — not the
        caster who pays it). ``cost.x_selector`` is `None` when the "where X
        is …" clause wasn't recognized from the card's own text; X then
        stays 0 (RULE 107.3c's safe default) rather than guessed.
        """
        if self._stack_item_for(item) is None:
            return
        if cost.mana.has_variable:
            x_value = (
                continuous.count_selector(self.state, ability_controller_id, cost.x_selector)
                if cost.x_selector
                else 0
            )
            cost.mana = cost.mana.with_x(x_value)
        try:
            caster = self.state.player_by_id(caster_id)
        except KeyError:
            caster = None
        if caster is None or not self._can_pay_player_cost(caster, cost):
            # No real decision — countered outright, same "don't stall a
            # passive goldfish opponent on a choice nobody can act on"
            # shortcut `counter_unless_pays` uses.
            self.counter_spell(item, countered_by=ability_controller_id)
            return
        self.state.pending_ward = {"item": item, "caster_id": caster_id, "cost": cost}
        cost_label = cost.label()
        self.open_choice({
            "kind": "ward", "countered_by": ability_controller_id,
            "player_id": caster.id,
            "prompt": f"Ward {cost_label} — zahlen, um deinen Zauberspruch/deine Fähigkeit zu "
            "behalten?",
            "options": [
                {"id": "pay", "label": f"{cost_label} zahlen"},
                {"id": "decline", "label": "Nicht zahlen"},
            ],
        })
    def check_rampage(self, attacker: GameObject, blocker_count: int) -> None:
        """RULE 702.23: place Rampage's triggered ability, if any, right when
        ``attacker`` becomes blocked — built directly (not via the generic
        `TriggeredAbility`/`_collect_triggers` event pipeline `_place_trigger`
        normally drives *from*, though it still ends by calling that same
        method to go on the stack) because its pump amount is fixed *at
        trigger time* to this specific block's blocker count (RULE 603.4),
        which a bind-on-load `TriggeredAbility` — one fixed `effects` list,
        reused for every firing — can't carry. The identical "per-firing
        data" problem `check_ward` solves the same way, for the same reason.

        A no-op when ``attacker`` has no Rampage, or wasn't blocked by more
        than one creature (RULE 702.23a: "for each creature blocking it
        beyond the first" — zero bonus for a single blocker, so nothing to
        place).
        """
        # RULE 702.23b: each rampage instance triggers separately, each with its own N: the printed one, then a granted one.
        printed = (getattr(attacker, "parametric_keywords", None) or {}).get("rampage")
        granted = (getattr(attacker, "_granted_parametric_keywords", None) or {}).get("rampage")
        amounts = [int(p["n"]) for p in (printed,) if p and p.get("n") is not None]
        amounts += [int(granted)] if granted is not None else []
        for n in amounts:
            bonus = n * max(0, blocker_count - 1)
            if bonus <= 0:
                continue
            ability = TriggeredAbility(
                trigger_event=EventType.BECOMES_BLOCKED,
                effects=[PumpEffect(power=bonus, toughness=bonus)],
                controller_id=attacker.controller_id,
                source=attacker,
                description=f"Rampage {n}",
            )
            self._place_trigger(ability)
    def _check_myriad(self, attacker: GameObject) -> None:
        """RULE 702.116a Myriad: "Whenever this creature attacks, for each opponent other than defending
        player, you may create a token that's a copy of this creature that's tapped and attacking that player
        or a planeswalker they control. Exile the tokens at end of combat."

        Built per declaration, like `check_dethrone`, so a *granted* myriad (Legion Loyalty, Blade of Selves) is
        seen. The body is ordinary composition: a `for_each` over the other opponents, each iteration a "you
        may" around the tapped-and-attacking copy plus its own end-of-combat exile (RULE 603.7). The tokens are
        put onto the battlefield attacking, never declared, so no attack trigger fires for them (RULE 508.3a),
        and a 2-player game has no such opponent, so nothing is created. RULE 702.116b: each myriad instance triggers
        separately, so a creature with a printed and a granted instance (or two grants) places one trigger per
        instance (`combat.keyword_instances`, ENG-53)."""
        instances = combat.keyword_instances(attacker, "myriad")
        if not instances:
            return
        from ...parser.oracle.spec import EffectSpec
        from ..binding.core import build_effects  # function-scoped: binder imports the rules mixins

        defending = self._dethrone_defending_player(attacker)
        if defending is None:
            return
        if not [p for p in self.state.living_players() if p.id not in (attacker.controller_id, defending.id)]:
            return
        for _ in range(instances):
            ability = TriggeredAbility(
                trigger_event=EventType.ATTACKS, controller_id=attacker.controller_id, source=attacker,
                description="Myriad",
                effects=build_effects([EffectSpec("for_each", {
                    "over": {"players": "each_opponent_except_defending"},
                    "effects": [{"type": "optional", "params": {
                        "prompt": "Myriad: Kopie erstellen?",
                        "effects": [
                            {"type": "copy_permanent", "params": {
                                "target_kind": None, "tapped": True, "attacking": True,
                                "attack_iteration_player": True}},
                            {"type": "create_delayed_trigger", "params": {
                                "step": "end_combat", "scope": "any", "capture": "created_objects",
                                "effects": [{"type": "exile_specific", "params": {}}]}},
                        ]}}],
                })], attacker),
            )
            self._place_trigger(ability, event=GameEvent(
                EventType.ATTACKS, instance_id=attacker.instance_id, player_id=attacker.controller_id,
                defending_player_id=defending.id,
            ))

    def check_dethrone(self, attacker: GameObject) -> None:
        """RULE 702.107: place Dethrone's own triggered ability, if any,
        right when ``attacker`` is declared — built directly (like
        `check_rampage`, for the same "per-firing dynamic" reason) rather
        than as a bind-on-load `TriggeredAbility`
        (`effect_binder._keyword_triggered_abilities`) since `combat.has`
        must be read fresh at attack-declaration time: Dethrone isn't only
        ever printed on the attacker itself, it's also grantable to "other
        creatures you control" by a layer-6 static (Marchesa, the Black
        Rose) that never runs the bind-on-load machinery on those other
        creatures — only a check at the moment of the actual attack sees a
        dynamically-granted keyword at all.

        A no-op when ``attacker`` doesn't currently have dethrone, or the
        defending player (its controller, for a planeswalker/battle attack —
        RULE 702.107a's ruling that Dethrone cares about the defending
        *player*'s life regardless of what's actually being attacked) isn't
        at or tied for the game's highest life total.
        """
        if not combat.has(attacker, "dethrone"):
            return
        defender = self._dethrone_defending_player(attacker)
        if defender is None:
            return
        living = self.state.living_players()
        if not living or defender.life < max(p.life for p in living):
            return
        ability = TriggeredAbility(
            trigger_event=EventType.ATTACKS,
            effects=[AddCountersEffect(amount=1, source=attacker)],
            controller_id=attacker.controller_id,
            source=attacker,
            description="Dethrone",
        )
        self._place_trigger(ability)
    def _dethrone_defending_player(self, attacker: GameObject) -> Optional[Player]:
        """Resolve ``attacker.combat_defender`` (`GameEngine.declare_attackers`/
        `_assign_defender`) to the defending *player*, for `check_dethrone`.
        Distinct from `GameEngine._resolve_combat_defender` — that one
        returns the actual damage-assignment target (a planeswalker object
        itself), while Dethrone needs that permanent's *controller*.
        """
        spec = getattr(attacker, "combat_defender", None)
        if not spec:
            return None
        if spec.get("kind") == "player":
            try:
                return self.state.player_by_id(spec["id"])
            except KeyError:
                return None
        if spec.get("kind") in ("planeswalker", "battle"):
            obj = self.state.find_object(spec["instance_id"])
            if obj is None:
                return None
            # RULE 310.8d: a battle's defending player is its protector, not
            # its controller — see `GameEngine._defending_player`.
            player_id = obj.protector_id if obj.is_battle else obj.controller_id
            if player_id is None:
                return None
            try:
                return self.state.player_by_id(player_id)
            except KeyError:
                return None
        return None
    def _eligible_protectors(self, obj: GameObject) -> list[Player]:
        """Who may be ``obj``'s protector (RULE 310.8a), by battle type.

        RULE 310.11a: a Siege's protector must be an **opponent** of its
        controller — which is what makes a Siege attackable by its own
        controller (310.8b). A battle with no battle type at all falls back
        to 310.8a's "its controller becomes its protector".

        Losers are excluded: a player who's out of the game can neither be
        attacked nor block, so leaving them as protector would strand the
        battle. That's exactly the case RULE 310.10's SBA exists to repair.
        """
        alive = [p for p in self.state.players if not p.has_lost]
        if obj.card.is_siege:
            return [p for p in alive if p.id != obj.controller_id]
        return [p for p in alive if p.id == obj.controller_id]
    def battle_is_being_attacked(self, obj: GameObject) -> bool:
        """Whether any creature is currently attacking ``obj`` (RULE 310.10's
        "a battle that isn't being attacked" carve-out — the protector of a
        battle already under attack must not be swapped out from under the
        combat that's resolving)."""
        return any(
            other.attacking
            and (other.combat_defender or {}).get("kind") == "battle"
            and (other.combat_defender or {}).get("instance_id") == obj.instance_id
            for other in self.state.battlefield
        )
    def exile_siege_for_transformed_cast(self, obj: GameObject) -> bool:
        """RULE 310.11b: exile a defeated Siege, then open its controller's
        "you may cast it transformed without paying its mana cost" window.

        The exile half is a genuine RULE 400.7 zone change (a new object, so
        `reset_as_new_object` drops the spent defense counters and the
        protector), after which the object is flipped onto its **back** face
        — so the card sitting in exile simply *is* the transformed card, and
        the ordinary cast path needs no notion of "cast this face instead".
        The free-cast permission is `grant_free_cast_window_from_exile`, the
        same one Rebound and Beseech the Mirror use.

        Simplification worth knowing: that permission lasts the rest of the
        turn, whereas RULE 310.11b's "you may cast it" is strictly a
        window *during this ability's resolution*. Declining and casting it
        two spells later is therefore legal here and wouldn't be in paper.
        This is the shape the engine already had, shared with the two
        callers above rather than a second, stricter mechanism.

        Returns whether the Siege actually flipped — ``False`` (exiled, but
        no free cast offered) for a battle with no back face at all, which
        no real Siege is but a Replay-editor board could produce.
        """
        controller = self.state.player_by_id(obj.controller_id)
        self._detach_attachments_from(obj)
        self.exile(obj)
        obj.reset_as_new_object()
        obj.controller_id = controller.id
        if not self.transform_permanent(obj):
            return False
        self.grant_free_cast_window_from_exile(obj)
        return True
    def choose_protector(self, obj: GameObject, player_id: Optional[str]) -> None:
        """Set ``obj``'s protector (RULE 310.8a), validated against its battle
        type. An unrecognized/missing ``player_id`` falls back to the first
        eligible player — the same treatment `_resume_choose_creature_type` gives a
        missing answer to a mandatory choice, so a battle is never left
        without one (which RULE 310.10 would then punish with a graveyard
        move)."""
        eligible = self._eligible_protectors(obj)
        if not eligible:
            obj.protector_id = None
            return
        match = next((p for p in eligible if p.id == player_id), None)
        obj.protector_id = (match or eligible[0]).id
