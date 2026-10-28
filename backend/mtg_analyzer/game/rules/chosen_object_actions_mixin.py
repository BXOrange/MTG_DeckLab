"""Apply the closed vocabulary of chosen-object actions."""
from __future__ import annotations

from ..control import gain_control
from typing import Optional
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject, Zone
from ...models.game.game_state import DelayedTrigger
from ...models.game.player import Player
from .. import continuous
from ..effects.core import SacrificeObjectEffect
from .misc_helpers import (
    CHEAP_CREATURE_MAX_MANA_VALUE,
    CHEAP_CREATURE_BONUS_COUNTERS,
)


class ChosenObjectActionsMixin:
    """Apply the closed vocabulary of chosen-object actions."""
    def _apply_chosen_object(
        self,
        player: Player,
        obj: GameObject,
        action: str,
        source: Optional[GameObject],
        remember: bool = False,
        hideaway_incarnation: Optional[int] = None,
        track_exiled_with: bool = False,
        prevent_shield: Optional[dict] = None,
        redirect_shield: Optional[dict] = None,
        connive: bool = False,
        control_recipient_id: Optional[str] = None,
        source_incarnation: Optional[int] = None,
    ) -> None:
        """Do the one thing a `choose_objects` action names to one pick."""
        if action == "select_only":
            return
        if action == "return_from_exile_finality":
            # "…put a permanent card from among them onto the battlefield with a finality counter on it." (Winter,
            # Cynical Opportunist) — the exiled card enters under its owner's... the chooser's control, RULE 400.7.
            self._remove_from_current_zone(player, obj)
            self._put_searched_card(player, obj, "battlefield")
            obj.controller_id = player.id
            self.add_counters(obj, 1, "finality")
            return
        if action == "tap":
            self.set_tapped(obj, True)
        elif action == "phase_out":
            obj.phased_out = True
            for other in self.state.battlefield:
                if other.attached_to == obj.instance_id:  # same detaching as `PhaseOutEffect`
                    other.attached_to = None
        elif action == "untap":
            # "Untap up to three lands." (Frantic Search, Snap-shaped) — untargeted, so a pick, not a target.
            self.set_tapped(obj, False)
        elif action == "strip_all_counters":
            # Eventide's Shadow: remove every counter from the pick, via the
            # negative-`add_counters` idiom (`ProliferateEffect`/
            # `RemoveCountersEffect`) so a "counter removed" consumer still
            # sees it correctly.
            for kind in list((obj.counters or {}).keys()):
                amount = obj.counters.get(kind, 0)
                if amount:
                    self.add_counters(obj, -amount, kind)
        elif action == "sacrifice":
            # RULE 701.17a: non-destructive, so no regeneration shield saves it.
            self.note_sacrificed(source, obj)
            self.put_into_graveyard(obj)
        elif action == "exploit":
            # RULE 702.110b: the creature exploits a creature when its controller sacrifices one as the exploit
            # ability resolves. ``source`` is the exploiting creature; if the sacrifice did not happen (a
            # replacement effect), nothing was exploited.
            # A creature that sacrifices *itself* still exploits (it triggers off the battlefield, as a
            # leaves-the-battlefield ability would), so the event fires before the sacrifice in that case.
            exploited = GameEvent(
                EventType.EXPLOITS,
                instance_id=getattr(source, "instance_id", None),
                controller_id=player.id,
                related_ids=[obj.instance_id],
            )
            if source is obj:
                self.state.fire_event(exploited)
                self.put_into_graveyard(obj)
            else:
                self.put_into_graveyard(obj)
                if source is not None and obj not in self.state.battlefield:
                    self.state.fire_event(exploited)
        elif action == "suspect":
            self.suspect(obj)
        elif action == "destroy":
            # Immoral Bargain (PAR-60 round 4): RULE 701.7 "destroy" — honours
            # regeneration and indestructible, unlike ``sacrifice`` above.
            self.destroy(obj)
        elif action == "return_to_hand":
            self.return_to_hand(obj)
        elif action == "return_from_graveyard":
            self.return_from_graveyard(
                obj, "battlefield", controller_id=control_recipient_id,
            )
        elif action == "return_from_graveyard_tapped":
            self.return_from_graveyard(
                obj, "battlefield_tapped", controller_id=control_recipient_id,
            )
        elif action == "return_from_graveyard_to_hand":
            self.return_from_graveyard(obj, "hand")
        elif action == "return_from_graveyard_to_library_top":
            self.return_from_graveyard(obj, "library_top")
        elif action == "free_cast_exile":
            # "…If that spell would be put into your graveyard, exile it instead." — the same exile-then-window
            # route `CastGraveyardInstantSorceryFreeExileEffect`'s targeted form takes (RULE 614.1 rider).
            obj.exile_after_free_cast = True
            self.exile(obj)
            self.grant_free_cast_window_from_exile(obj, caster=player)
        elif action == "graveyard_to_library":
            # Quandrix Command mode 4: move the pick from its owner's
            # graveyard to its owner's library, then shuffle that library
            # (RULE 701.20). ``player`` here is the spell's controller (the
            # chooser), who need not own the card.
            owner = self.state.player_by_id(obj.owner_id)
            if owner is not None and obj in owner.graveyard:
                owner.remove_from_zone(obj, Zone.GRAVEYARD)
                obj.zone = Zone.LIBRARY
                owner.add_to_zone(obj, Zone.LIBRARY)
                self.shuffle_library(owner)
        elif action == "discard":
            # RULE 701.47 (connive, MEC-43 — Ledger Shredder): "if a
            # nonland card was discarded this way, put a +1/+1 counter on
            # it [the conniving permanent]." Checked *before* the move —
            # `GameObject.is_land` is a card-type property unaffected by
            # zone, but reading it off the still-in-hand object is the
            # more obviously-correct order.
            is_land = obj.is_land
            self.discard_specific(obj, cause=source)
            if connive and not is_land and source is not None:
                self.add_counters(source, 1, kind="+1/+1", source=source)
        elif action == "hand_to_library_bottom":
            # Jace, Multiverse Architect's +1: the chooser's own hand card goes to the bottom of its owner's library.
            self.return_to_library(obj, "bottom")
        elif action in ("hand_to_library_top", "hand_to_library_third"):
            # Painful Memories / Agonizing Memories / Lost Hours: the hand's owner puts the chosen card into their own
            # library (RULE 401.7 for "third from the top"); ``player`` here is the chooser, who need not own it.
            self.return_to_library(obj, "top", 3 if action == "hand_to_library_third" else 1)
        elif action == "reveal":
            # PAR-80 (Ivy Seer/Scent of Ivy): reveal has no mechanical
            # weight of its own (`RevealTopEffect`'s own docstring) — the
            # pick stays in hand. Only accumulates onto `source`'s own
            # `GameObject.revealed_with_ids`, the reveal-choice sibling of
            # MEC-21's ``track_exiled_with``/``exiled_with_ids``, for a
            # following clause's ``"revealed_with_count"`` count_selector.
            if source is not None:
                source.revealed_with_ids.append(obj.instance_id)
        elif action == "remember_source" and prevent_shield is not None:
            # MEC-30 (RULE 615/616.1d "a source of your choice" — Circle of
            # Protection/Rune of Protection): the pick becomes a
            # `watched_source_id`, not an action on ``obj`` itself.
            if prevent_shield.get("recipient_scope") == "you_and_creatures_you_control":
                # Shadowbane, MEC-30 — a dynamic recipient set, not one
                # fixed id; ``recipient_id`` still names the player (always
                # a player for this scope).
                player = self.state.player_by_id(prevent_shield["recipient_id"])
                if player is not None:
                    self.prevent_damage_to_player_and_their_creatures(
                        player, prevent_shield.get("amount", "all"),
                        watched_source_id=obj.instance_id, rider=prevent_shield.get("rider"),
                    )
            elif prevent_shield.get("recipient_scope") == "any":
                # Penance, MEC-30 — no recipient qualifier at all ("…would
                # deal damage this turn, prevent that damage."): the
                # unscoped-recipient one-shot shield, which needs only the
                # chosen source, not a resolved recipient.
                self.prevent_damage_from_source(
                    obj, prevent_shield.get("amount", "all"), rider=prevent_shield.get("rider"),
                )
            else:
                recipient = (
                    self.state.player_by_id(prevent_shield["recipient_id"])
                    if prevent_shield.get("recipient_is_player")
                    else self._object_by_instance_id(prevent_shield["recipient_id"])
                )
                if recipient is not None:
                    method = (
                        self.prevent_damage_to_player
                        if prevent_shield.get("recipient_is_player")
                        else self.prevent_damage_to_target
                    )
                    method(
                        recipient, prevent_shield.get("amount", "all"),
                        watched_source_id=obj.instance_id, rider=prevent_shield.get("rider"),
                        once=bool(prevent_shield.get("once")),
                    )
        elif action == "remember_source_redirect" and redirect_shield is not None:
            # MEC-30 (RULE 616.1c "that damage is dealt to `<X>` instead" —
            # Opal-Eye, Konda's Yojimbo): the pick becomes a redirect's own
            # watched source.
            recipient = (
                self.state.player_by_id(redirect_shield["recipient_id"])
                if redirect_shield.get("recipient_is_player")
                else self._object_by_instance_id(redirect_shield["recipient_id"])
            )
            if recipient is not None:
                self.redirect_damage_from_source(
                    obj, recipient, redirect_shield.get("amount", "all"),
                    only_to_player_id=redirect_shield.get("only_to_player_id"),
                    only_to_object_id=redirect_shield.get("only_to_object_id"), once=bool(redirect_shield.get("once")),
                )
        elif action == "select_referent":
            self.context.previous_targets = [obj]
        elif action == "remember_source_coinflip":
            # Desperate Gambit, MEC-30: "Choose a source you control and
            # flip a coin. If you win the flip, ... double .... If you
            # lose the flip, ... prevent ...." — the chosen permanent is
            # both the coin flip's own subject and the shield's watched
            # source, so no shield payload is needed at all.
            if self.coin_flip():
                self.grant_damage_multiplier_from_source(obj)
            else:
                self.prevent_damage_from_source(obj, "all")
        elif action in ("exile", "exile_face_down_linked", "exile_until_source_leaves"):
            if action == "exile_until_source_leaves":
                from ..effects.exile_control import ExileEffect

                ExileEffect(source=source, until_source_leaves=True).apply(self.context, [obj])
            else:
                self.exile(obj)
            if action == "exile_face_down_linked":
                obj.face_down_in_exile = True
                obj.face_down_exile_viewers = {player.id}
                obj.hideaway_source_id = getattr(source, "instance_id", None)
                event = self.context.trigger_event or {}
                incarnation = (hideaway_incarnation if hideaway_incarnation is not None else
                               event.get("hideaway_incarnation", getattr(source, "hideaway_incarnation", None)))
                if source is not None and source.hideaway_incarnation == incarnation:
                    source.hideaway_exile_ids.add(obj.instance_id)
                    source.linked_exile_id = obj.instance_id
                    if obj.instance_id not in source.linked_exile_ids:
                        source.linked_exile_ids.append(obj.instance_id)
            # RULE 608.2's "it"/"that card" referent for a following clause
            # (MEC-52 — Back from the Brink prices "pay its mana cost" off
            # the just-exiled graveyard card), the same seeding
            # `ExileEffect`'s own trigger-subject branch does.
            self.context.previous_targets = [obj]
            if remember and source is not None:
                # MEC-17: Imprint's own "remember the exiled card" —
                # `linked_exile_id`'s "keep pointing at the exiled card
                # after this resolves" shape, same field `ExileEffect
                # (remember=True)` uses for the unrelated O-Ring return.
                source.linked_exile_id = obj.instance_id
            if track_exiled_with and source is not None:
                # MEC-12: Abdel Adrian's own "exile any number of…" —
                # `remember`'s accumulating sibling, same field
                # `ExileEffect(track_exiled_with=True)` uses.
                self.state.track_exiled_with(source, obj, source_incarnation if source_incarnation is not None
                                             else self.context.resolving_source_incarnation)
        elif action in (
            "library_to_battlefield", "library_to_battlefield_tapped", "library_to_battlefield_attacking",
            "library_to_battlefield_spell_attacking",
            "library_to_battlefield_cheap_bonus",
        ):
            # MEC-41 (Nissa, Steward of Elements' 0 ability): the object is
            # still sitting in the library at this point (unlike every
            # other action above, which acts on a battlefield permanent or
            # a hand card) — `_finish_search`'s own `_remove_search_hit`
            # does the same library-pop-then-move split.
            if obj in player.library:
                player.remove_from_zone(obj, Zone.LIBRARY)
            if action == "library_to_battlefield_cheap_bonus" and (
                int(obj.mana_value or 0) <= CHEAP_CREATURE_MAX_MANA_VALUE
            ):
                obj.entry_bonus_counters["+1/+1"] = CHEAP_CREATURE_BONUS_COUNTERS  # "enters with" — see `_apply_entry_counters`
            entry_specs = None
            if action == "library_to_battlefield_spell_attacking":
                # The Sprinkler of Stardust explicitly makes spell cards into permanents;
                # RULE 613.4b/613.4f gives it 2/2 and its combat-damage ability.
                entry_specs = [{"type": "grant_until", "params": {
                    "duration": "rest_of_game", "self_subject": True, "target_kind": None,
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "remove_types": ["instant", "sorcery"],
                        "power": 2, "toughness": 2,
                    }},
                    "extra_statics": [{"type": "grant_triggered_ability", "params": {
                        "trigger_event": "DAMAGE", "filter": {"combat": True, "is_player": True},
                        "recipient_relation": "opponent",
                        "grant_effects": [{"type": "copy_imprinted_card", "params": {"from_self": True}}],
                    }}],
                }}]
            self._put_searched_card(
                player, obj,
                "battlefield_attacking" if action.endswith("_attacking")
                else "battlefield_tapped" if action.endswith("_tapped") else "battlefield",
                entry_specs=entry_specs,
            )
        elif action in ("grant_temp_play_same_turn", "grant_temp_play_next_turn"):
            self._grant_temp_play_permission(
                obj, player, source.name if source is not None else None,
                action.endswith("_same_turn"), None,
            )
        elif action == "library_to_hand":
            # MEC-72 (Eclipsed Flamekin): move the picked card from library to hand.
            self._remove_from_current_zone(player, obj)
            obj.zone = Zone.HAND
            player.add_to_zone(obj, Zone.HAND)
        elif action == "library_to_graveyard":
            # RULE 400.7 / 603.2: this is a real zone move, so Soulcipher
            # Board's graveyard-arrival trigger sees the selected card.
            self._remove_from_current_zone(player, obj)
            self._move_to_graveyard(obj)
        elif action == "sacrifice_for_descendants_fury":
            # MEC-72 (Descendants' Fury): sacrifice the chosen combat damage dealer
            # and reveal cards until a creature sharing a creature type is revealed.
            subtypes: set[str] = set()
            if "changeling" in obj.card.type_line.lower() or "changeling" in obj.intrinsic_keywords:
                subtypes.add("changeling")
            else:
                _, _, sub = obj.card.type_line.lower().partition("—")
                subtypes.update(s.strip() for s in sub.split() if s.strip())
            self.put_into_graveyard(obj)
            self.reveal_until_creature_type(
                player,
                creature_types=subtypes,
                count=1,
                hit_destination="battlefield",
                rest_destination="library_bottom_random",
            )
        elif action == "zone_to_battlefield":
            if obj.zone not in (Zone.HAND, Zone.COMMAND, Zone.GRAVEYARD, Zone.EXILE):
                return
            owner = self.state.player_by_id(obj.owner_id)
            self._remove_from_current_zone(owner, obj)
            obj.reset_as_new_object()
            obj.controller_id = player.id
            self._put_searched_card(player, obj, "battlefield")
            self.context.previous_targets = [obj]
        elif action == "hand_to_battlefield":
            # MEC-43 round 4D (Kodama of the East Tree): the hand-zone
            # sibling of "library_to_battlefield" just above — the object
            # is still sitting in the controller's hand at this point.
            # Stamps `GameObject.entered_via_ability_id` with ``source``'s
            # own instance_id (Kodama itself) so its own trigger's "if it
            # wasn't put onto the battlefield with this ability" guard
            # (`effect_binder`'s ``not_entered_via_self`` condition) can
            # tell this arrival apart from any other entering permanent.
            if obj in player.hand:
                player.remove_from_zone(obj, Zone.HAND)
            # Stamped *before* the placement below, not after: `_put_
            # searched_card` fires `EventType.ENTERS_BATTLEFIELD`
            # synchronously (`GameState.fire_event` notifies every
            # subscriber, including trigger collection, before returning),
            # so the guard this field feeds (`not_entered_via_self`) must
            # already be true by the time that event goes out or Kodama's
            # own trigger would see an unstamped object and re-fire on its
            # own put.
            if source is not None:
                obj.entered_via_ability_id = source.instance_id
            self._put_searched_card(player, obj, "battlefield")
        elif action == "hand_to_battlefield_haste_sacrifice":
            # RULE 400.7: a hand card entering the battlefield is a new
            # object. It is selected first, then reset before the entry event
            # so its ETB abilities see the fresh permanent.
            if obj not in player.hand:
                return
            player.remove_from_zone(obj, Zone.HAND)
            obj.reset_as_new_object()
            obj.controller_id = player.id
            self._put_searched_card(player, obj, "battlefield")
            obj.temp_keywords.add("haste")
            continuous.recompute(self.state)
            source_name = source.name if source is not None else None
            label = f"{obj.name}: geopfert" + (f" ({source_name})" if source_name else "")
            # RULE 603.7: "the next end step" is the next end step of any
            # player's turn, and captures this particular new object.
            self.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=player.id,
                    step="end",
                    scope="any",
                    effects=[SacrificeObjectEffect(obj, source=source)],
                    description=label,
                )
            )
        elif action == "turn_face_up":
            self.turn_face_up(obj)
        elif action in ("put_onto_battlefield", "put_onto_battlefield_tapped", "put_onto_battlefield_attacking"):
            # "Put a creature card from [defending player's] hand onto the battlefield under your control [tapped
            # and attacking]" (Zara): the chooser controls it as it enters (RULE 110.2); RULE 508.4 puts it into combat.
            owner = self.state.player_by_id(obj.owner_id)
            if owner is not None and obj in owner.hand:
                owner.remove_from_zone(obj, Zone.HAND)
                obj.controller_id = player.id
                destination = "battlefield_attacking" if action.endswith("attacking") else (
                    "battlefield_tapped" if action.endswith("tapped") else "battlefield"
                )
                self._put_searched_card(
                    player, obj, destination,
                    attacking_player_id=owner.id if destination == "battlefield_attacking" else None,
                )
        elif action == "manifest_from_hand":
            if obj in player.hand:
                player.remove_from_zone(obj, Zone.HAND)
                obj.controller_id = player.id
                # RULE 708.3: turned face down before it enters, so its own ETB abilities never trigger.
                self.turn_face_down(obj, "manifest")
                self._put_searched_card(player, obj, "battlefield")
        elif action == "choose_permanent" and source is not None:
            # MEC-26: Scheming Fence's own ETB pick — nothing happens to
            # ``obj`` itself, just a pointer stamped onto the source
            # (`continuous.group_selector_objects`'s ``"chosen_permanent"``
            # selector reads it back every recompute).
            source.chosen_permanent_id = obj.instance_id
        elif action == "gain_control":
            # MEC-46 (Expropriate): control moves to the chooser,
            # indefinitely — an SBA pass / the session view recompute
            # picks up the new characteristics (RULE 613.1).
            if obj.controller_id != player.id:
                gain_control(self.state, obj, player.id)
                continuous.recompute(self.state)
        elif action == "gain_control_and_untap":
            # Turf War: `gain_control`, then the land untaps (RULE 701.26b).
            if obj.controller_id != player.id:
                gain_control(self.state, obj, player.id)
                continuous.recompute(self.state)
            self.set_tapped(obj, False)
        elif action == "gain_control_for" and control_recipient_id is not None:
            # PAR-30 (Cultural Exchange): control moves to a *third*
            # player, not the chooser — see `_request_choose_objects`'s own
            # docstring for ``control_recipient_id``.
            if obj.controller_id != control_recipient_id:
                gain_control(self.state, obj, control_recipient_id)
                obj.summoning_sick = True
                continuous.recompute(self.state)
        elif action == "soulbond_pair" and source is not None:
            # RULE 702.94a: the pairing is recorded on both creatures.
            source.paired_with = obj.instance_id
            obj.paired_with = source.instance_id
        elif action == "library_top":
            owner = self.state.player_by_id(obj.owner_id) or player
            self._remove_from_current_zone(owner, obj)
            owner.add_to_zone(obj, Zone.LIBRARY)
        elif action == "cast_free":
            self.cast_without_paying(player, obj)
        elif action == "grant_free_cast":
            # MEC-20: arm the pick's free-cast window without casting it —
            # see `CHOOSE_OBJECT_ACTIONS`'s own docstring for why this is
            # deliberately not `cast_without_paying`. Also registered in
            # `temp_play_permissions` (same-turn-only) purely so
            # `GameEngine._step_cleanup`'s existing sweep tears both down
            # together — a hand card needs no actual play-permission grant
            # to be castable (it already is), but `free_cast_instance_ids`'
            # own cleanup only keeps entries also found there.
            #
            # RULE 601.2f/718 rulings actually require this free cast to
            # happen *as the Expertise spell resolves*, not at leisure later
            # in the turn — this engine has no "pause mid-resolution for a
            # full nested cast+targeting cycle" primitive, so a same-turn
            # window is offered instead (documented simplification: strictly
            # more permissive than print, never less).
            self.state.free_cast_instance_ids.add(obj.instance_id)
            self._grant_temp_play_permission(
                obj, player, source.name if source is not None else None,
                same_turn_only=True, mana_wildcard=None,
            )
        elif action == "remove_suspected":
            # PAR-30 Suspect one-off shapes / RULE 701.60a's reverse: "You
            # may have it become no longer suspected." (Deadly Complication).
            # Nothing is created or moved — the pick just clears its own
            # suspected designation.
            self.remove_suspected([obj])
