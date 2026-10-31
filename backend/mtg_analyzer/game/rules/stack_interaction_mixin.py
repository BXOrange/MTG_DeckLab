"""Retarget, mutate, counter and move spells and abilities."""
from __future__ import annotations

from ..control import gain_control
from typing import Any, Optional
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject, Zone
from ...models.game.game_state import StackItem
from .. import continuous
from .triggers_mixin import _has_suspend
from ..effects.core import CantBeCounteredEffect, GrantCantBeCounteredEffect
from ..targeting import legal_targets
from .. import continuations


class StackInteractionMixin:
    """Retarget, mutate, counter and move spells and abilities."""
    def _stack_item_for(self, target: Any) -> Optional[StackItem]:
        """The `StackItem` a counter effect's ``target`` names, or ``None``.

        ``target`` is either a `StackItem` itself or its underlying
        `GameObject` — `CounterSpellEffect` (and the search/choice machinery
        upstream) pass whichever it was handed.
        """
        for candidate in self.state.stack:
            if candidate is target or candidate.obj is target:
                return candidate
        return None
    def change_target(
        self, target: Any, optional: bool = False, source: Optional[GameObject] = None,
        redirect_to_source: bool = False,
    ) -> None:
        """`ChangeTargetEffect`'s resolve-time logic (RULE 115.4/601.2c —
        Misdirection/Deflecting Swat).

        The player *changing* the target is this effect's own controller
        (RULE 115.4a — not the targeted spell's controller, and per
        115.4a a target description's "you"/"your" still refers to the
        original spell's own controller, which is why `legal_targets` is
        computed with ``item.controller_id`` below, not the changer's).
        Legal alternatives are recomputed fresh against the *current*
        board (RULE 115.1c), not whatever was legal when the targeted
        spell was originally cast.

        Scoped to a stack item with exactly one existing target and one
        targeting effect — see `ChangeTargetEffect`'s own docstring for why
        a version retargeting any number of targets at once isn't built.
        ``target`` may be a *spell* (``item.obj``) or, since ENG-26, an
        *ability* (``item.source`` — a plain activated/triggered ability's
        stack image has no `GameObject` of its own; `targeting.py`'s
        ``"ability"`` kind names it by `StackItem.stack_id` instead) — the
        RULE 115.4a legality recompute below reads whichever one is the
        actual source of the effect being retargeted. No legal alternative
        (or an ``optional`` decline) leaves the target untouched, same as
        RULE 115.4a's own "if no legal targets are available, the target
        doesn't change."
        """
        item = self._stack_item_for(target)
        if item is None or source is None:
            return
        stack_source = item.obj if item.obj is not None else item.source
        if stack_source is None:
            return
        if len(item.targets) != 1 or item.target_groups is not None:
            return
        effect = next(
            (e for e in item.effects if getattr(e, "target_spec", None) is not None), None
        )
        if effect is None:
            return
        options = legal_targets(self.state, item.controller_id, effect.target_spec, source=stack_source)
        if not options:
            return
        if redirect_to_source:
            # Spellskite/Hydroelectric Specimen-shaped: the only
            # alternative on offer is this effect's own source — narrow the
            # legal-options list to just that (RULE 115.4a's "no legal
            # target, doesn't change" if it isn't even legal), then fall
            # through to the ordinary mandatory-auto-apply/optional-decline
            # handling below exactly as if that had been the only option
            # `legal_targets` ever returned. Spellskite prints no "you may"
            # (``optional=False``): with one option and not optional, that
            # auto-applies with no prompt. Hydroelectric Specimen's "you
            # may" does need the player's yes/no, which is `optional`'s
            # existing decline branch.
            options = [o for o in options if o.get("instance_id") == source.instance_id]
            if not options:
                return
        if not optional and len(options) == 1:
            item.targets = [self._target_from_descriptor(options[0])]
            return
        self.open_choice(self._change_target_choice(
            source.controller_id, item.stack_id, options, optional
        ))
    def _target_from_descriptor(self, descriptor: dict[str, Any]) -> Any:
        """A `targeting.legal_targets` descriptor, resolved back to the
        live `GameObject`/`Player` it names."""
        if "instance_id" in descriptor:
            return self.state.find_object(descriptor["instance_id"])
        return self.state.player_by_id(descriptor["player_id"])
    def _change_target_choice(
        self,
        changer_id: str,
        stack_id: int,
        options: list[dict[str, Any]],
        optional: bool,
    ) -> dict[str, Any]:
        """Build the `change_target` `pending_choice` — same generic
        ``{"id", "label", "instance_id"?}`` option shape `_trigger_target_
        choice` uses, so the existing choice UI renders it with no new
        frontend work. ``stack_id`` (not a `GameObject` id — ENG-26) is
        the being-retargeted item's own `StackItem.stack_id`, which works
        the same way for a spell or an ability."""
        choice_options: list[dict[str, Any]] = []
        for opt in options:
            if "instance_id" in opt:
                choice_options.append(
                    {"id": str(opt["instance_id"]), "label": opt["name"], "instance_id": opt["instance_id"]}
                )
            else:
                choice_options.append({"id": opt["player_id"], "label": opt["name"]})
        if optional:
            choice_options.append({"id": "decline", "label": "Nichts ändern"})
        return {
            "kind": "change_target",
            "player_id": changer_id,
            "stack_id": stack_id,
            "prompt": "Neues Ziel wählen",
            "options": choice_options,
        }
    @continuations.choice("change_target", answer=continuations.ANSWER_STR, rule="115.4")
    def _resume_change_target(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `change_target` choice (RULE 115.4/601.2c).

        ``answer`` is the chosen new target's option id, same shape as
        `_resume_trigger_target`; a decline (only offered when
        `ChangeTargetEffect.optional` was set) leaves the spell's existing
        target untouched.
        """
        if answer is None or answer == "decline":
            return
        item = next(
            (i for i in self.state.stack if i.stack_id == choice["stack_id"]), None
        )
        if item is None:
            return
        target = self._resolve_choice_option(choice["options"], str(answer))
        if target is not None:
            item.targets = [target]
    def mutate_onto(
        self, mutating: GameObject, host: GameObject, under: bool = False
    ) -> None:
        """RULE 702.140b-d: merge ``mutating`` onto ``host``.

        The **host** stays the surviving `GameObject` — RULE 702.140c is
        explicit that the merged permanent is the *same* permanent, not a
        new one, which is exactly why mutate keeps counters, damage marked,
        attachments and summoning-sickness state, and why it fires no
        enters-the-battlefield trigger. So this rewrites the host's card
        rather than creating anything.

        "The creature on top plus all abilities from under it": the host
        takes on ``mutating``'s printed characteristics (name, P/T, types)
        while its own previous oracle text is banked on
        `GameObject.merged_oracle_text` and folded back in when abilities are
        re-derived — so the pile keeps accumulating abilities as further
        creatures mutate onto it, which is the mechanic's whole point.

        ``under=True`` is the other half of RULE 702.140b's "over **or
        under**": the pile keeps the *host's* characteristics and gains the
        mutating card's abilities instead. Same merge, opposite direction —
        which card's text ends up banked in ``merged_oracle_text`` and which
        supplies the printed face simply swap, so one code path covers both.

        The mutating spell's own object is left in exile: it has become part
        of the merged permanent and must not linger on the battlefield or in
        a graveyard as a second permanent.
        """
        from ..binding.core import bind_from_catalogue  # function-scoped: avoid cycle

        # Whichever card ends up *under* contributes only its abilities; the
        # one on top supplies the printed face the pile shows.
        beneath = mutating.card if under else host.card
        merged = list(host.merged_oracle_text)
        under_text = (beneath.oracle_text or "").strip()
        if under_text and under_text not in merged:
            merged.append(under_text)
        under_keywords = list(beneath.keywords or [])
        # Always work on a private copy of the top face: the printed `Card`
        # is shared by every instance of that card, and the merge below
        # rewrites its text.
        top_card = (mutating.card if not under else host.card).as_copy()
        if not under:
            # A fresh top face, so its own text is the base and every banked
            # under-text is folded back in on top of it.
            top_card.oracle_text = "\n".join(
                [top_card.oracle_text or ""] + merged
            ).strip()
        else:
            # The top face is unchanged and already carries everything
            # merged before now — only the new under-text is appended, or
            # earlier merges would be duplicated.
            top_card.oracle_text = "\n".join(
                [top_card.oracle_text or "", under_text]
            ).strip()
        top_card.keywords = list(
            dict.fromkeys(list(top_card.keywords or []) + under_keywords)
        )
        host.card = top_card
        host._front_card = top_card
        host.merged_oracle_text = merged
        # Re-derive the merged pile's abilities through the ordinary bind
        # path, so nothing about mutate needs its own ability-construction
        # code. Both halves of "abilities" have to carry: the oracle text
        # (parsed into triggered/activated/static abilities) *and* the RULE
        # 702 keyword list, which the keyword catalogue reads directly
        # rather than off the text.
        bind_from_catalogue(host)

        owner = self.state.player_by_id(mutating.owner_id)
        self._remove_from_current_zone(owner, mutating)
        mutating.zone = Zone.EXILE
        owner.add_to_zone(mutating, Zone.EXILE)

        continuous.recompute(self.state)
        self.state.fire_event(
            GameEvent(
                EventType.MUTATES,
                instance_id=host.instance_id,
                controller_id=host.controller_id,
                object_types=sorted(host.type_words),
            )
        )
    def break_illegal_soulbond_pairs(self) -> bool:
        """RULE 702.94c: a pair breaks the moment either creature leaves the
        battlefield, stops being a creature, or the two stop sharing a
        controller. Swept as a state-based action so nothing has to remember
        to tear a pair down at each of those sites."""
        changed = False
        for obj in list(self.state.battlefield):
            partner_id = getattr(obj, "paired_with", None)
            if partner_id is None:
                continue
            partner = self.state.find_object(partner_id)
            still_legal = (
                partner is not None
                and partner in self.state.battlefield
                and partner.is_creature
                and obj.is_creature
                and partner.controller_id == obj.controller_id
            )
            if not still_legal:
                obj.paired_with = None
                if partner is not None:
                    partner.paired_with = None
                changed = True
        return changed
    def move_spell_off_stack(self, target: Any, destination: str = "hand") -> bool:
        """Pull a spell off the stack into ``destination`` (RULE 400.1).

        Distinct from `return_to_hand`/`exile`, which move a *battlefield*
        permanent: this removes a `StackItem` entirely, so the spell never
        resolves at all. Practically it is a counter that sends the card
        somewhere other than the graveyard — which is exactly why Narset's
        Reversal ("…then return it to its owner's hand") and Possibility
        Storm ("that player exiles it") both dodge "can't be countered".

        A *copy* on the stack (RULE 707.10a/111.7) isn't a card and has
        nowhere to go: it simply ceases to exist. Returns whether anything
        was moved.
        """
        item = self._stack_item_for(target)
        if item is None or item.obj is None:
            return False
        self._capture_stack_copy_departure(item)
        self.state.stack.remove(item)
        obj = item.obj
        owner = self.state.player_by_id(obj.owner_id)
        if obj.is_token or destination == "exile":
            obj.zone = Zone.EXILE
            if not obj.is_token:
                owner.add_to_zone(obj, Zone.EXILE)
            return True
        if destination in ("library_top", "library_bottom"):
            # "…puts it on their choice of the top or bottom of their library." (Endless Detour) — a copy/token has
            # nowhere to go (above); a card goes to its owner's library.
            obj.zone = Zone.LIBRARY
            if destination == "library_bottom":
                owner.library.insert(0, obj)
            else:
                owner.library.append(obj)
            return True
        obj.zone = Zone.HAND
        owner.add_to_zone(obj, Zone.HAND)
        return True
    def return_spell_to_hand(self, target: Any) -> bool:
        """`move_spell_off_stack` to hand — Narset's Reversal's own clause."""
        return self.move_spell_off_stack(target, "hand")
    def _is_cant_be_countered(self, obj: GameObject) -> bool:
        """RULE 118-area: does ``obj`` carry a "this spell can't be
        countered" marker (`CantBeCounteredEffect`, docked via either the
        `spell_effect` or `static` ability_kind — see that class's
        docstring for why both feed the same check), or is its controller
        granted one by a standing battlefield permanent (`GrantCantBe
        CounteredEffect` — Hexing Squelcher's "Spells you control can't be
        countered.")?
        """
        effects = list(getattr(obj, "spell_effects", []) or [])
        effects += list(getattr(obj, "static_effects", []) or [])
        if any(isinstance(e, CantBeCounteredEffect) for e in effects):
            return True
        # PAR-216: "If X is 5 or more, this spell can't be countered ..." (Banefire) / Hellbent (Demonfire) -- the marker
        # gated on a condition, read now, while the spell is on the stack.
        from ..effects.game_status import ConditionalEffect  # function-scoped: the effects package imports the engine

        if any(
            isinstance(e, ConditionalEffect) and isinstance(e.inner, CantBeCounteredEffect)
            and e._condition_holds(self.context) for e in effects
        ):
            return True
        if self._covered_by_uncounterable_grant(obj):
            return True
        is_creature = "creature" in (getattr(obj, "type_words", None) or set())
        is_enchantment = "enchantment" in (getattr(obj, "type_words", None) or set())
        for permanent in self.state.battlefield:
            for effect in getattr(permanent, "static_effects", None) or []:
                if not isinstance(effect, GrantCantBeCounteredEffect):
                    continue
                if effect.scope == "all_spells":
                    # "Spells can't be countered." (Lier, Disciple of the Drowned) — every
                    # spell, whoever controls it or the permanent.
                    return True
                if permanent.controller_id != obj.controller_id:
                    continue
                if effect.scope == "creature_spells_you_control" and not is_creature:
                    continue
                if (
                    effect.scope == "creature_or_enchantment_spells_you_control"
                    and not (is_creature or is_enchantment)
                ):
                    # "Creature and enchantment spells you control can't be
                    # countered." (Destiny Spinner, MEC-43) — the two-type
                    # union sibling of the creature-only scope just above.
                    continue
                if effect.scope == "color_spells_you_control":
                    if effect.color not in (getattr(obj, "colors", None) or set()):
                        continue
                return True
        return False
    def counter_spell(
        self, target: Any, suspend_time_counters: Optional[int] = None, countered_by: Optional[str] = None,
        exile_instead: bool = False, library_choice: bool = False, destination: Optional[str] = None,
    ) -> None:
        """Remove a spell (a `StackItem` or its game object) from the stack.

        ``destination`` (PAR-175 M4: "If that spell is countered this way, `<exile it | put it on top of its owner's
        library | put it into its owner's hand>` instead of putting it into its owner's graveyard.") is the
        replacement landing zone, one of `COUNTER_DESTINATIONS`; a token that would go to a library or hand ceases to
        exist (RULE 111.7), as it does for ``library_choice``.

        ``library_choice`` (Hinder — "put that card on your choice of the top or bottom of its owner's library
        instead of into that player's graveyard"): the card waits on top of its owner's library until the countering
        player answers the `library_position` choice (RULE 701.5g replaced; a token or copy just ceases to exist).

        ``exile_instead`` (Transcendent Dragon — "exile it instead of putting it into its owner's
        graveyard") sends the countered card to exile rather than the graveyard.

        A countered spell goes to its owner's graveyard (RULE 701.5g) and
        never resolves. Unconditional — callers that must honour "can't be
        countered" (RULE 118) or an "unless its controller pays" condition
        (RULE 601) go through `counter_unless_pays` instead, which calls this
        only once both are settled.

        ``suspend_time_counters`` (Delay, MEC-42, RULE 702.62): "exile it
        with N time counters on it instead of putting it into its owner's
        graveyard. If it doesn't have suspend, it gains suspend." — redirects
        the landing zone and arms `GameObject.granted_suspend` when the card
        has no printed Suspend of its own, so `_collect_suspend_triggers`
        (`game/rules/triggers_mixin.py`) picks it up from exile exactly as a
        printed-Suspend card would. The commander-zone-choice replacement
        (RULE 903.9) only ever applies to a graveyard-or-library-bound move,
        so it's skipped on this branch.
        """
        item = self._stack_item_for(target)
        if item is None:
            return
        self._capture_stack_copy_departure(item)
        self.state.stack.remove(item)
        if item.obj is not None:
            item.obj.blitz_cost_paid = False  # RULE 400.7: the countered spell is a new object.
            owner = self.state.player_by_id(item.obj.owner_id)
            if library_choice:
                # Held on top of the owner's library until the countering player picks an end (`_resume_library_position`).
                if item.obj.is_token:
                    item.obj.zone = Zone.EXILE
                else:
                    owner.add_to_zone(item.obj, Zone.LIBRARY)
            elif exile_instead or destination == "exile":
                owner.add_to_zone(item.obj, Zone.EXILE)
            elif destination in ("hand", "library_top"):
                if item.obj.is_token:
                    item.obj.zone = Zone.EXILE
                else:
                    owner.add_to_zone(item.obj, Zone.HAND if destination == "hand" else Zone.LIBRARY)
                    self._flag_commander_zone_choice(item.obj)  # RULE 903.9b: a hand/library move may be redirected
            elif suspend_time_counters:
                owner.add_to_zone(item.obj, Zone.EXILE)
                if not _has_suspend(item.obj):
                    item.obj.granted_suspend = True
                item.obj.add_counters("time", suspend_time_counters)
            else:
                owner.add_to_zone(item.obj, Zone.GRAVEYARD)
                self._flag_commander_zone_choice(item.obj)
        self.state.fire_event(
            GameEvent(EventType.SPELL_RESOLVED, spell=item.description, countered=True)
        )
        self.state.fire_event(GameEvent(
            EventType.SPELL_COUNTERED, player_id=countered_by or self.context.resolving_controller_id,
            controller_id=countered_by or self.context.resolving_controller_id, spell=item.description,
            spell_controller_id=getattr(item.obj, "controller_id", None),
        ))
        if library_choice and item.obj is not None and not item.obj.is_token:
            chooser_id = countered_by or self.context.resolving_controller_id
            if chooser_id is not None:  # with nobody to ask it simply stays on top, the declined-choice default
                self._request_library_position(self.state.player_by_id(chooser_id), item.obj)
    def bounce_spell_or_permanent(self, target: Any) -> None:
        """"Return target spell or nonland permanent … to its owner's
        hand." (Sink into Stupor-shaped) — the RULE 701.3-onto-the-stack
        sibling of `counter_spell`: pulled straight off the stack (never
        resolving) rather than through `return_to_hand`'s battlefield/zone
        removal, which has no idea `GameState.stack` even exists and would
        silently duplicate the object instead of moving it. Not a
        "counter" for any card-text purpose (nothing here checks/marks
        "can't be countered" — this ability's printed template never
        claims to counter anything, it plainly returns).

        Falls back to the ordinary `return_to_hand` when ``target`` isn't
        currently a spell on the stack (a permanent bounce), so one call
        covers "spell or nonland permanent" without the caller needing to
        know which kind of target it got handed.
        """
        item = self._stack_item_for(target)
        if item is None:
            self.return_to_hand(target)
            return
        self._capture_stack_copy_departure(item)
        self.state.stack.remove(item)
        if item.obj is not None:
            owner = self.state.player_by_id(item.obj.owner_id)
            owner.add_to_zone(item.obj, Zone.HAND)
            self._flag_commander_zone_choice(item.obj)
        self.state.fire_event(
            GameEvent(EventType.SPELL_RESOLVED, spell=item.description, countered=False)
        )
    def gain_control_of_spell(self, target: Any, new_controller_id: str) -> None:
        """"Gain control of target noncreature spell." (Commandeer) — RULE
        608.2m/111.5's owner/controller split applied to a spell still on
        the stack rather than a permanent: only `StackItem.controller_id`
        (and the underlying object's own, mirrored so both agree) changes,
        so a spell that goes on to resolve as a permanent (an artifact/
        enchantment/planeswalker, per the card's own reminder text) enters
        under the *new* controller directly — no separate zone-change
        control flip needed the way a permanent already on the battlefield
        would (`gain_control_by_source`/`exchange_control`).
        """
        item = self._stack_item_for(target)
        if item is None:
            return
        if not gain_control(self.state, item, new_controller_id):
            return
        if item.obj is not None:
            if (item.obj.controller_id != new_controller_id and item.obj.granted_suspend_haste
                    and item.obj.granted_suspend_haste.get("duration") == "until_control_lost"):
                item.obj.granted_suspend_haste = False
            gain_control(self.state, item.obj, new_controller_id)
    def end_the_turn(self) -> None:
        """"End the turn." (Day's Undoing/Time Stop-shaped reminder text —
        RULE 500-adjacent, not a printed rule number of its own): "Exile
        all spells and abilities from the stack, including this card" —
        the caster's own resolving spell is exiled *instead of* going to
        its owner's graveyard, the same trailing-self-override idiom
        `ShuffleSelfIntoLibraryEffect` already uses (`_apply_stack_item`'s
        own zone check). The rest of the reminder text ("discard down to
        your maximum hand size. Damage wears off, and 'this turn'/'until
        end of turn' effects end") is RULE 514.1/514.2's own cleanup-step
        body, applied by `GameEngine.advance_step` once `GameState.
        end_turn_requested` is set below — a `RulesEngine` method has no
        back-reference to `GameEngine`'s `_turn_steps`/`_cursor` (or its
        `_step_cleanup`), the same reason `ExtraCombatPhaseEffect` queues
        onto `GameState` instead of reaching the engine directly.
        """
        for item in list(self.state.stack):
            self._capture_stack_copy_departure(item)
            self.state.stack.remove(item)
            if item.obj is not None:
                owner = self.state.player_by_id(item.obj.owner_id)
                owner.add_to_zone(item.obj, Zone.EXILE)
                self.state.fire_event(
                    GameEvent(EventType.EXILE, player_id=owner.id, object=item.obj.name)
                )
        self.state.end_turn_requested = True
    def counter_ability(self, target: Any) -> None:
        """RULE 701.5b: counter a target activated or triggered ability
        (Stifle/Trickbind, ENG-26) — the ability-item sibling of
        `counter_spell`, which already handles an ability `StackItem`
        correctly on its own (no `.obj` to move to a graveyard; RULE
        701.5g's "its owner's graveyard" only ever applies to a spell).
        Refuses a "can't be countered" ability the same way
        `counter_unless_pays` refuses a spell's own.
        """
        item = self._stack_item_for(target)
        if item is None or item.kind != "ability":
            return
        if self._is_cant_be_countered(item.source):
            return
        self.counter_spell(target)
