"""Validated object selections and resumable multi-pick choices."""
from __future__ import annotations

from typing import Any, Optional
from ...models.game.game_object import GameObject, Zone
from ...models.game.player import Player
from ..effects.core import ProliferateEffect
from .. import continuations
from .misc_helpers import (
    _card_type_words,
    _distinct_card_type_assignment,
    _that_many_value,
    _substitute_x_specs,
)


class ObjectSelectionMixin:
    """Validated object selections and resumable multi-pick choices."""
    #: The closed vocabulary `_request_choose_objects` accepts, mapping each
    #: action name to what it does to a chosen object. Deliberately small
    #: and data-only: the whole choice (candidates, action, how many are
    #: left) lives in `GameState.pending_choice`, so it survives the
    #: `clone()` undo snapshots takes — unlike a callback, which is why
    #: this replaced the "auto-pick the first candidate" convention rather
    #: than passing a continuation closure around.
    CHOOSE_OBJECT_ACTIONS = frozenset(
        {
            # Winter, Cynical Opportunist: a pure selection (the picked cards are acted on afterwards, together, by the
            # ``then`` effect — a set whose legality depends on *all* picks can't be applied pick by pick), and the
            # exile-zone pick that becomes a permanent with a finality counter (RULE 122.1h).
            "select_only", "return_from_exile_finality",
            "tap", "untap", "sacrifice", "suspect", "return_to_hand", "return_from_graveyard",
            # RULE 702.26: "those permanents phase out" (Ripples of Potential).
            "phase_out",
            # PAR-143: an untargeted graveyard pick ("return a land card from your graveyard to the
            # battlefield tapped / to your hand").
            "return_from_graveyard_tapped", "return_from_graveyard_to_hand", "soulbond_pair", "library_top", "discard",
            # PAR-162: an untargeted graveyard pick put on top of its owner's library ("put a land card from your
            # graveyard on top of your library").
            "return_from_graveyard_to_library_top",
            # Diviner of Mist: an untargeted graveyard instant/sorcery pick that is exiled into a free-cast window.
            "free_cast_exile",
            "library_to_hand", "library_to_graveyard", "sacrifice_for_descendants_fury",
            # A hand pick the owner puts into their own library (Painful/Agonizing Memories, Lost Hours).
            "hand_to_library_top", "hand_to_library_third", "hand_to_library_bottom",
            "turn_face_up",  # Zimone — RULE 708.8 by an effect
            # "{T}: Manifest a card from your hand." (Scroll of Fate) — a hand pick put onto the battlefield face down
            # (RULE 701.40a: manifesting "a card" is not limited to the library's top).
            "manifest_from_hand",
            # RULE 508.4/110.2: a pick from another player's hand put onto the battlefield under the chooser's control
            # (Zara, Renegade Recruiter).
            "put_onto_battlefield", "put_onto_battlefield_tapped", "put_onto_battlefield_attacking",
            # "Exile a face-down permanent you control face up: You may play that card this turn." (Primordial Mist)
            # RULE 702.110a/b: an exploit ability's optional sacrifice — a sacrifice that also fires `EXPLOITS`.
            "exploit",
            # Quandrix Command mode 4 ("target player shuffles up to three
            # target cards from their graveyard into their library") — the
            # pick moves from its owner's graveyard to its owner's library,
            # which is then shuffled (RULE 701.20). A graveyard-zone pick,
            # unlike the battlefield/hand actions around it.
            "graveyard_to_library",
            # PAR-13 (Dungeon of the Mad Mage's "Mad Wizard's Lair" — "Draw
            # three cards and reveal them. You may cast one of them without
            # paying its mana cost."): a hand-zone pick, unlike every other
            # action above (all battlefield picks), cast through the
            # ordinary free-cast path (`RulesEngine.cast_without_paying`) —
            # general enough for any future "reveal some cards, cast one
            # free" template to reuse rather than a one-off.
            "cast_free",
            # Gemstone Caverns' "if you do, exile a card from your hand"
            # pregame-setup tail (`offer_opening_hand_battlefield_choice`) —
            # another hand-zone pick, general enough for any future "exile a
            # card from your hand" cost/effect to reuse.
            "exile",
            "exile_until_source_leaves",  # RULE 610.3, selected permanents
            "exile_face_down_linked",  # RULE 702.75a Hideaway's selected library card
            # MEC-20 (the "Expertise" cycle): another hand-zone pick, but
            # unlike ``"cast_free"`` this only *arms* the pick's temporary
            # free-cast permission (`GameState.free_cast_instance_ids`)
            # rather than casting it immediately — a hand card is already a
            # legal cast zone, so the caster casts it (or doesn't) through
            # the ordinary `legal_actions` cast option afterward, getting
            # its full targeting/modal choices. See `FreeCastFromHandEffect`.
            "grant_free_cast",
            # MEC-26 (Scheming Fence's "As this creature enters, you may
            # choose a nonland permanent."): stamps the pick onto
            # ``source``'s own `GameObject.chosen_permanent_id` rather than
            # acting on the chosen object at all — the object-choice
            # sibling of ``remember``'s `linked_exile_id` stamp, its own
            # action rather than overloading ``remember`` since nothing
            # here gets exiled.
            "choose_permanent",
            # MEC-30 (RULE 615/616.1d "a source of your choice" — Circle of
            # Protection/Rune of Protection): nothing happens to the chosen
            # permanent either — it opens a `prevent_damage_to_player`/
            # `_to_target`-shaped shield scoped to it, via the choice's own
            # ``prevent_shield`` payload (`_request_choose_objects`'s own
            # docstring).
            "remember_source",
            # MEC-30 (RULE 616.1c "that damage is dealt to `<X>` instead" —
            # Opal-Eye, Konda's Yojimbo): the redirect sibling of
            # ``remember_source`` just above — same chooser, but opens
            # `RulesEngine.redirect_damage_from_source` via the choice's own
            # ``redirect_shield`` payload instead of a prevention shield.
            "remember_source_redirect",
            # MEC-30 (Desperate Gambit — "Choose a source you control and
            # flip a coin. If you win, ... double ... . If you lose, ...
            # prevent ..."): the chosen permanent IS the coin flip's own
            # subject, so no shield payload is needed at all — the coin is
            # flipped and the branch resolved entirely inside
            # `_apply_chosen_object`.
            "remember_source_coinflip",
            # Untargeted selection for a following effect (RULE 701.71).
            "select_referent",
            # MEC-41 (Nissa, Steward of Elements' 0 ability — "Look at the
            # top card of your library. ... you may put that card onto the
            # battlefield."): a library-zone pick, unlike every other
            # action above — general enough for any future "look at the
            # top card, you may put it onto the battlefield" template to
            # reuse rather than a one-off.
            "library_to_battlefield",
            # Turntimber Symbiosis: "…onto the battlefield. If that card has mana value 3 or less, it enters with
            # three additional +1/+1 counters on it." — `library_to_battlefield` plus `entry_bonus_counters`.
            "library_to_battlefield_cheap_bonus",
            # PAR-144: "put up to two land cards from among them onto the battlefield tapped".
            "library_to_battlefield_tapped",
            # PAR-148 (RULE 508.4): "…from among them onto the battlefield tapped and attacking" (Jet, Rebel Leader).
            "library_to_battlefield_attacking",
            "library_to_battlefield_spell_attacking",
            # PAR-137: "exile the top two cards … choose 1 of them. You may play that card this turn /
            # until the end of your next turn" — the pick (already in exile) alone gets the permission.
            "grant_temp_play_same_turn", "grant_temp_play_next_turn",
            # MEC-43 round 4D (Kodama of the East Tree — "you may put a
            # permanent card with equal or lesser mana value from your
            # hand onto the battlefield"): a hand-zone pick placed
            # straight onto the battlefield, the hand-zone sibling of
            # ``"library_to_battlefield"`` just above. Stamps
            # `GameObject.entered_via_ability_id` so a Panharmonicon-
            # shaped "if it wasn't put onto the battlefield with this
            # ability" trigger guard (`effect_binder`'s
            # ``not_entered_via_self`` condition) can tell a card THIS
            # ability just placed apart from any other entering permanent.
            "hand_to_battlefield",
            "zone_to_battlefield",
            # MEC-73: Sneak Attack / Incandescent Soulstoke's selected hand
            # creature enters with haste and a RULE 603.7 delayed sacrifice.
            "hand_to_battlefield_haste_sacrifice",
            # MEC-46 (Expropriate — "choose a permanent owned by the voter
            # and gain control of it"): the chosen permanent's control
            # moves to the *chooser* (``player``), indefinitely (RULE 701.38
            # outcome body, no duration — a bare `controller_id`
            # reassignment, the same shape `GainControlBySourceEffect`
            # uses). Nothing else happens to it.
            "gain_control",
            # Turf War: "gains control of one of those lands of their choice and untaps it."
            "gain_control_and_untap",
            # PAR-30 (RULE 701.10i residue — Cultural Exchange): the same
            # bare `controller_id` reassignment as `"gain_control"`, but to
            # a specific *other* player named by `control_recipient_id`
            # rather than to the chooser.
            "gain_control_for",
            # PAR-30 Suspect one-off shapes / RULE 701.60a's reverse ("You
            # may have it become no longer suspected." — Deadly
            # Complication): nothing is created or moved, the pick just
            # clears its own suspected designation. ``optional`` so declining
            # keeps the menace a suspected creature has.
            "remove_suspected",
            # "Remove any number of counters from among permanents on the
            # battlefield. You draw cards and lose life equal to the number
            # of counters removed this way." (Eventide's Shadow) — each
            # chosen permanent has *all* its counters removed (a documented
            # permanent-granularity simplification of "any number of
            # counters", the same RULE 122 precision `MoveCountersEffect`
            # already accepts); the caller tallies the total via a
            # cards-removed delta in its ``then_specs``.
            "strip_all_counters",
            # Immoral Bargain (PAR-60 round 4) — "Destroy X target nonland
            # permanents", where X is only known after the additional-cost
            # sacrifice is resolved: the destroy sibling of ``sacrifice``,
            # applying `RulesEngine.destroy` (RULE 701.7, regeneration- and
            # indestructible-respecting) to any battlefield permanent, not
            # only the chooser's own.
            "destroy",
            # PAR-80 (Ivy Seer/Scent of Ivy — "reveal any number of green
            # cards in your hand"): a hand-zone pick like "discard"/"exile"
            # above, but nothing moves — RULE 701.20 reveal has no
            # mechanical weight of its own (`RevealTopEffect`'s own
            # docstring). Only accumulates each pick onto `GameObject.
            # revealed_with_ids`, read back by a following clause via the
            # ``"revealed_with_count"`` count_selector.
            "reveal",
        }
    )
    def _request_choose_objects(
        self,
        player: Player,
        candidates: list[GameObject],
        action: str,
        count: int = 1,
        optional: bool = False,
        prompt: str = "",
        source: Optional[GameObject] = None,
        then_specs: Optional[list[dict]] = None,
        then_specs_if_commander: Optional[list[dict]] = None,
        remember: bool = False,
        track_exiled_with: bool = False,
        prevent_shield: Optional[dict] = None,
        redirect_shield: Optional[dict] = None,
        connive: bool = False,
        else_specs: Optional[list[dict]] = None,
        control_recipient_id: Optional[str] = None,
        rest_ids: Optional[list[int]] = None,
        rest_destination: Optional[str] = None,
        decline_leaves_untouched: bool = False,
        total_mana_value_budget: Optional[int] = None,
        then_that_many: Optional[dict] = None,
        distinct_card_types: bool = False,
        total_power_budget: Optional[int] = None,
        minimum_card_types: int = 0,
        force_choice: bool = False,
    ) -> None:
        """Open a "choose N of these objects" decision (RULE 601.2c-style).

        The general chooser for every effect that names *what kind* of
        object to act on but leaves *which one* to the player: Cloudstone
        Curio's bounce, Tangle Wire's tap, Tevesh Szat's and Professor
        Onyx's sacrifices, Deadeye Navigator's Soulbond partner, Lim-Dûl's
        Vault's and Thassa's Oracle's library reordering. Each of those used
        to auto-pick the first legal candidate.

        Offered one object at a time (`_resume_choose_objects`
        re-opens until ``count`` are picked or the pool runs dry), exactly
        like a library search — same UI shape, same undo granularity.
        ``optional`` adds a decline option ("you **may** return…"); a
        mandatory choice with nothing to choose between still resolves
        without a prompt, since there's no decision to make.

        ``action`` names what happens to each pick, from
        `CHOOSE_OBJECT_ACTIONS`. ``source`` is only needed by
        ``soulbond_pair``, which pairs each pick *with* it (RULE 702.94a).

        ``then_specs`` are serialized `EffectSpec` dicts to apply once at
        least one pick was made — the "**If you do**, draw two cards" half
        of an optional sacrifice (Tevesh Szat), which can only be decided
        after the choice rather than before it.
        ``then_specs_if_commander`` adds RULE 903's "if a commander was
        sacrificed this way" tail on top; both are carried as data on the
        choice, so they survive the state `clone()` undo takes.

        ``remember=True`` (MEC-17, Imprint — Chrome Mox's own "you may
        exile a nonartifact, nonland card from your hand") additionally
        stamps whichever object gets ``action="exile"``ed onto ``source``'s
        own `GameObject.linked_exile_id` — the same field an `ExileEffect`
        with its own ``remember=True`` already uses for the O-Ring-shaped
        "when this leaves, return the exiled card" half, reused here so a
        later mana ability/static can read back *which* card this
        permanent has imprinted. Only meaningful with ``count=1`` (a
        multi-pick "remembers" only its own last pick, overwriting the
        rest — no printed Imprint card needs more than one).

        ``track_exiled_with=True`` (MEC-12, Abdel Adrian, Gorion's Ward —
        "exile **any number of** other nonland permanents you control") is
        ``remember``'s accumulating sibling for a *multi*-pick exile,
        mirroring `ExileEffect.track_exiled_with`'s own `GameObject.
        exiled_with_ids` list exactly (every pick appended, not just the
        last), for a "choose N/any number, unlike a RULE 115 target" shape
        `ExileEffect`'s own target-gathering can't express — there is no
        "target" here at all, just a selection among permanents this
        player controls.

        ``prevent_shield`` (MEC-30, ``action="remember_source"`` only —
        RULE 615/616.1d's "a source of your choice") carries the shield to
        open once a pick is made: ``{"recipient_id", "recipient_is_player",
        "amount", "rider"}``, resolved by `_apply_chosen_object` into a
        `RulesEngine.prevent_damage_to_player`/`_to_target` call scoped to
        whichever permanent gets picked. Carried as data on the choice, like
        ``then_specs``, so it survives the state `clone()` undo takes.

        ``redirect_shield`` (MEC-30, ``action="remember_source_redirect"``
        only — RULE 616.1c "that damage is dealt to `<X>` instead", Opal-Eye)
        is ``prevent_shield``'s redirect sibling: ``{"recipient_id",
        "recipient_is_player", "amount"}``, resolved into a `RulesEngine.
        redirect_damage_from_source` call instead.

        ``else_specs`` are ``then_specs``' mirror: serialized `EffectSpec`
        dicts applied only when the choice ends with **nothing** picked —
        the "**If you don't**, incubate 3." half of Traumatic Revelation's
        "you may choose a creature or battle card … If you don't, …". Also
        fires when the candidate pool is empty to begin with (no legal card
        to choose ⇒ "you didn't"). Carried as data on the choice so it
        survives the `clone()` undo takes.

        ``connive=True`` (RULE 701.47, MEC-43 — Ledger Shredder's "this
        creature connives") marks an ``action="discard"`` pick for the
        conditional half connive's own template needs: "if a **nonland**
        card was discarded this way, put a +1/+1 counter on it [the
        conniving permanent]." Unlike ``then_specs_if_commander`` (a plain
        boolean gate on *whether any pick happened to be one*), this
        depends on *which* card was picked, so it's threaded straight
        through to `_apply_chosen_object` rather than tracked as a
        choice-level flag the way ``commander_taken`` is.

        ``control_recipient_id`` (PAR-30 — Cultural Exchange's "choose any
        number of creatures target player controls[.] … control moves to a
        **third** player, not the chooser") is ``action="gain_control_for"``'s
        own payload: unlike the plain ``"gain_control"`` action (control
        moves to ``player``, the chooser), this hands each pick to whichever
        player's id is carried here instead — the caster picks, but someone
        *else* receives.

        ``then_that_many`` (MEC-103, RULE 603.12 — "sacrifice up to three
        Zombies. When you sacrifice one or more Zombies this way, each
        opponent sacrifices **that many** creatures") is ``{"effects": […],
        "trigger": […]}``: serialized specs whose ``"x"`` sentinel is bound
        to how many objects were actually picked (`_substitute_x_specs`).
        ``effects`` resolve at once; ``trigger`` becomes the reflexive
        trigger (`enqueue_reflexive_trigger`), so it may carry targets. Only
        fires when something was picked, like ``then_specs``.
        """
        if action not in self.CHOOSE_OBJECT_ACTIONS:
            raise ValueError(f"unknown choose-objects action {action!r}")
        pool = [obj for obj in candidates if obj is not None]
        if minimum_card_types:
            from ..continuous import card_types_of

            # RULE 608.2d: an impossible optional set cannot be selected.
            if len(set().union(*(card_types_of(obj) for obj in pool))) < minimum_card_types:
                return
        if distinct_card_types:
            pool = [obj for obj in pool if _card_type_words(obj)]
        if total_mana_value_budget is not None:
            pool = [obj for obj in pool if int(
                getattr(obj, "mana_value", 0) or 0
            ) <= int(total_mana_value_budget)]
        if total_power_budget is not None:
            # "…any number of creatures … with total power 4 or less" (Slaughter the Strong, Reunion of the House):
            # the picked objects' summed power may not exceed the budget, so only objects that still fit are offered.
            pool = [obj for obj in pool if int(self._power_for_budget(obj)) <= int(total_power_budget)]
        if not pool or count <= 0:
            # Nothing to choose ⇒ "you didn't choose" — run the else branch
            # (Traumatic Revelation's "If you don't, incubate 3." when the
            # revealed hand holds no creature or battle card).
            if not pool and count > 0 and else_specs:
                self._apply_effect_specs(list(else_specs), source)
            return
        # RULE 401.4: even when all cards must move, their library order is a choice.
        ordered_library_move = action == "hand_to_library_top" and len(pool) > 1
        if len(pool) <= count and not optional and not force_choice and not ordered_library_move and (
            not distinct_card_types or _distinct_card_type_assignment([_card_type_words(o) for o in pool])
        ):
            # Forced: every candidate is taken anyway, so asking would be
            # theatre. (An *optional* one still asks — declining matters.)
            commander_taken = False
            that_many_value = _that_many_value(then_that_many, list(pool))
            with self.state.simultaneous():  # RULE 603.2c: every forced pick is one event
                for obj in pool:
                    commander_taken = commander_taken or obj.is_commander
                    self._apply_chosen_object(
                        player, obj, action, source, remember=remember,
                        track_exiled_with=track_exiled_with, prevent_shield=prevent_shield,
                        redirect_shield=redirect_shield, connive=connive,
                        control_recipient_id=control_recipient_id,
                    )
            if rest_destination and rest_ids:
                taken_ids = {o.instance_id for o in pool}
                unpicked_rest = [iid for iid in rest_ids if iid not in taken_ids]
                self._handle_rest_inspected(player, unpicked_rest, rest_destination)
            self._apply_choose_objects_tail(
                source, then_specs, then_specs_if_commander, commander_taken,
                then_that_many, that_many_value,
                chosen_ids=[obj.instance_id for obj in pool],
            )
            return
        self.open_choice(self._choose_objects_choice(
            player, pool, action, count, optional, prompt,
            source_id=source.instance_id if source is not None else None,
            picked=[], then_specs=then_specs,
            then_specs_if_commander=then_specs_if_commander, remember=remember,
            track_exiled_with=track_exiled_with,
            prevent_shield=prevent_shield, redirect_shield=redirect_shield,
            connive=connive, else_specs=else_specs,
            control_recipient_id=control_recipient_id,
            rest_ids=rest_ids, rest_destination=rest_destination,
            decline_leaves_untouched=decline_leaves_untouched,
            total_mana_value_budget=total_mana_value_budget,
            then_that_many=then_that_many,
            distinct_card_types=distinct_card_types,
            total_power_budget=total_power_budget,
            minimum_card_types=minimum_card_types,
        ))
    @staticmethod
    def _power_for_budget(obj: GameObject) -> int:
        """An object's power as a "total power N or less" budget counts it: the derived power on the battlefield,
        the printed power for a card in a graveyard (RULE 208 — a card off the battlefield has only printed values)."""
        if obj.zone == Zone.BATTLEFIELD:
            return max(0, int(obj.power or 0))
        printed = getattr(obj.card, "power", None)
        return max(0, int(printed)) if isinstance(printed, int) or str(printed or "").lstrip("-").isdigit() else 0
    def _apply_choose_objects_tail(
        self,
        source: Optional[GameObject],
        then_specs: Optional[list[dict]],
        then_specs_if_commander: Optional[list[dict]],
        commander_taken: bool,
        then_that_many: Optional[dict] = None,
        picked_count: int = 0,
        chosen_ids: Optional[list[int]] = None,
    ) -> None:
        """Apply a `choose_objects` decision's "if you do" follow-up."""
        def capture(value):
            if isinstance(value, dict):
                if value == {"kind": "sacrificed_card_types"}:
                    return list(getattr(source, "sacrificed_cost_card_types", []))
                if value == {"kind": "chosen_instance_ids"}:
                    return list(chosen_ids or [])
                if value == {"kind": "chosen_object_visits"}:
                    return [[obj.instance_id, obj.zone_incarnation] for iid in chosen_ids or []
                            if (obj := self.state.find_object(iid)) is not None]
                return {key: capture(item) for key, item in value.items()}
            if isinstance(value, list):
                return [capture(item) for item in value]
            return value

        # Preserve last-known types before subsequent opponents sacrifice.
        then_specs = capture(then_specs)
        # "…it's a black Zombie in addition to its other types" — the picked objects are the follow-up's "it"
        # (`GameContext.previous_targets`), exactly as a targeted clause's targets would be.
        outer_previous = getattr(self.context, "previous_targets", [])
        picked_objects = [o for o in (self.state.find_object(i) for i in chosen_ids or []) if o is not None]
        if chosen_ids is not None:
            self.context.previous_targets = picked_objects
        try:
            self._apply_effect_specs(list(then_specs or []), source)
        finally:
            self.context.previous_targets = outer_previous
        if commander_taken:
            self._apply_effect_specs(list(then_specs_if_commander or []), source)
        if then_that_many and picked_count > 0:
            # MEC-103: "that many" = how many were picked, bound like ENG-48's X.
            self._apply_effect_specs(
                _substitute_x_specs(list(then_that_many.get("effects") or []), picked_count), source,
            )
            self.enqueue_reflexive_trigger(
                _substitute_x_specs(list(then_that_many.get("trigger") or []), picked_count), source,
            )
    @continuations.choice("proliferate", answer=continuations.ANSWER_SELECTION, rule="701.34a")
    def _resume_proliferate(self, choice: dict[str, Any], answer: Any) -> None:
        ProliferateEffect.resume(self.context, choice, answer)

    def _choose_objects_choice(
        self,
        player: Player,
        pool: list[GameObject],
        action: str,
        count: int,
        optional: bool,
        prompt: str,
        source_id: Optional[int],
        picked: list[int],
        then_specs: Optional[list[dict]] = None,
        then_specs_if_commander: Optional[list[dict]] = None,
        remember: bool = False,
        track_exiled_with: bool = False,
        prevent_shield: Optional[dict] = None,
        redirect_shield: Optional[dict] = None,
        connive: bool = False,
        else_specs: Optional[list[dict]] = None,
        control_recipient_id: Optional[str] = None,
        rest_ids: Optional[list[int]] = None,
        rest_destination: Optional[str] = None,
        decline_leaves_untouched: bool = False,
        total_mana_value_budget: Optional[int] = None,
        then_that_many: Optional[dict] = None,
        distinct_card_types: bool = False,
        total_power_budget: Optional[int] = None,
        minimum_card_types: int = 0,
    ) -> dict[str, Any]:
        """Build the serializable `choose_objects` `pending_choice`."""
        source = self._object_by_instance_id(source_id)
        source_incarnation = self.context.resolving_source_incarnation
        if source_incarnation is None:
            source_incarnation = getattr(source, 'zone_incarnation', None)
        options = [
            {"id": str(obj.instance_id), "label": obj.name, "instance_id": obj.instance_id}
            for obj in pool
            if obj.instance_id not in picked
        ]
        if optional:
            from ..continuous import card_types_of

            picked_types = set().union(*(card_types_of(obj) for obj in
                (self._object_by_instance_id(i) for i in picked) if obj is not None))
            if not picked or len(picked_types) >= minimum_card_types:
                options.append({"id": "decline", "label": "Auswahl abschließen" if picked and minimum_card_types else "Nichts wählen"})
            elif minimum_card_types:
                options.append({"id": "-1", "label": "Nichts ins Exil schicken"})
        remaining = count - len(picked)
        label = prompt or "Wähle ein Objekt"
        return {
            "kind": "choose_objects",
            "effect_controller_id": self.context.acting_player_id or self.context.resolving_controller_id,
            "source_incarnation": source_incarnation,
            "player_id": player.id,
            "action": action,
            "source_id": source_id,
            "count": count,
            "optional": optional,
            "picked": list(picked),
            # RULE 400.7: a pure selection names the offered visit even
            # while subsequent picks or an undo snapshot are pending.
            "selection_visits": ({str(o.instance_id): o.zone_incarnation for o in pool}
                                 if action == "select_referent" else None),
            "remaining": remaining,
            "prompt": f"{label} (noch {remaining})" if count > 1 else label,
            "prompt_base": label,
            "options": options,
            "then_specs": [dict(spec) for spec in (then_specs or [])],
            # Traumatic Revelation's "If you don't, incubate 3." — applied
            # only when the choice ends with nothing picked (`then_specs`'
            # mirror).
            "else_specs": [dict(spec) for spec in (else_specs or [])],
            # MEC-30: the shield `_apply_chosen_object` opens once a source
            # is picked (``action="remember_source"`` only) — see
            # `_request_choose_objects`'s own docstring.
            "prevent_shield": dict(prevent_shield) if prevent_shield else None,
            # MEC-30: `redirect_shield`'s own sibling — see
            # `_request_choose_objects`'s own docstring.
            "redirect_shield": dict(redirect_shield) if redirect_shield else None,
            # PAR-30: `action="gain_control_for"`'s own recipient payload —
            # see `_request_choose_objects`'s own docstring.
            "control_recipient_id": control_recipient_id,
            "then_specs_if_commander": [
                dict(spec) for spec in (then_specs_if_commander or [])
            ],
            # RULE 903: whether any pick so far was a commander, which the
            # "if a commander was sacrificed this way" tail reads.
            "commander_taken": False,
            # MEC-17: whether this pick should also be remembered onto
            # ``source`` (`GameObject.linked_exile_id`) — see
            # `_request_choose_objects`'s own docstring.
            "remember": remember,
            # MEC-12: whether every ``"exile"`` pick should accumulate onto
            # ``source`` (`GameObject.exiled_with_ids`) — see
            # `_request_choose_objects`'s own docstring.
            "track_exiled_with": track_exiled_with,
            # MEC-43 (RULE 701.47, connive): whether an ``action="discard"``
            # pick should also check the discarded card's own ``is_land``
            # and place a +1/+1 counter on ``source`` — see
            # `_request_choose_objects`'s own docstring.
            "connive": connive,
            "rest_ids": list(rest_ids) if rest_ids else None,
            "rest_destination": rest_destination,
            "decline_leaves_untouched": decline_leaves_untouched,
            "total_mana_value_budget": total_mana_value_budget,
            "total_power_budget": total_power_budget,
            "distinct_card_types": bool(distinct_card_types),
            "minimum_card_types": minimum_card_types,
            "then_that_many": dict(then_that_many) if then_that_many else None,
        }
    @continuations.choice("choose_objects", answer=continuations.ANSWER_INT, rule="601.2b")
    def _resume_choose_objects(self, choice: dict[str, Any], instance_id: Optional[int]) -> None:
        """Answer a pending `choose_objects` decision: apply the action to
        the chosen object, then re-ask while picks remain (or stop on a
        decline — RULE 601.2c's "up to"/"may" shape)."""
        player = self.state.player_by_id(choice["player_id"])
        picked: list[int] = list(choice["picked"])
        if instance_id == -1 and choice.get("minimum_card_types") and any(
            option["id"] == "-1" for option in choice["options"]
        ):
            self.state.pending_choice = None
            self.state.release_batches()
            return
        if instance_id is None and picked and choice.get("minimum_card_types"):
            from ..continuous import card_types_of

            selected_types = set().union(*(card_types_of(obj) for obj in
                (self._object_by_instance_id(i) for i in picked) if obj is not None))
            if len(selected_types) < choice["minimum_card_types"]:
                self.state.pending_choice = choice
                raise ValueError("Choose a set with enough card types, or cancel the selection")
        if instance_id is None and not choice.get("optional"):
            self.state.pending_choice = choice
            raise ValueError("This choice is mandatory")
        offered = {o["instance_id"] for o in choice["options"] if "instance_id" in o}
        visits = choice.get("selection_visits")
        if visits is not None:
            offered = {iid for iid in offered
                       if (obj := self._object_by_instance_id(iid)) is not None
                       and obj.zone_incarnation == visits.get(str(iid))}
        if instance_id is not None:
            if instance_id not in offered:
                # resolve_choice claims the continuation before dispatch;
                # an invalid answer must leave this untouched choice open.
                self.state.pending_choice = choice
                raise ValueError(f"{instance_id} is not a legal choice")
            picked.append(instance_id)
        source = self._object_by_instance_id(choice.get("source_id"))
        declined = instance_id is None
        chosen = self._object_by_instance_id(instance_id) if instance_id is not None else None
        picked_card_types = [set(types) for types in choice.get("picked_card_types", [])]
        if chosen is not None and choice.get("distinct_card_types"):
            picked_card_types.append(_card_type_words(chosen))
        # Applied as each pick is made rather than all at the end: tapping
        # or sacrificing one permanent can change what the remaining
        # candidates even are (RULE 608.2's "as the effect resolves").
        commander_taken = bool(choice.get("commander_taken"))
        if int(choice.get("count") or 1) > 1:
            # RULE 603.2c: the picks of one multi-pick choice are one event; the batch
            # stays open until the choice completes (`release_batches` below).
            self.state.hold_batches()
        picked_measure = int(choice.get("picked_measure", 0) or 0)
        if chosen is not None:
            picked_measure += _that_many_value(choice.get("then_that_many"), [chosen])
        if chosen is not None and player is not None:
            commander_taken = commander_taken or chosen.is_commander
            self._apply_chosen_object(
                player, chosen, choice["action"], source, remember=bool(choice.get("remember")),
                track_exiled_with=bool(choice.get("track_exiled_with")),
                prevent_shield=choice.get("prevent_shield"),
                redirect_shield=choice.get("redirect_shield"),
                connive=bool(choice.get("connive")),
                control_recipient_id=choice.get("control_recipient_id"),
                hideaway_incarnation=choice.get("hideaway_incarnation"),
                source_incarnation=choice.get("source_incarnation"),
            )
        remaining_pool = [
            obj
            for obj in self._choose_objects_pool(choice, picked)
            if obj is not None
        ]
        budget = choice.get("total_mana_value_budget")
        if budget is not None:
            spent = sum(
                int(getattr(getattr(self._object_by_instance_id(i), "card", None), "converted_mana_cost", 0) or 0)
                for i in picked
            )
            remaining_pool = [
                obj for obj in remaining_pool
                if int(getattr(obj, "mana_value", 0) or 0) <= int(budget) - spent
            ]
        power_budget = choice.get("total_power_budget")
        if power_budget is not None:
            spent_power = sum(
                self._power_for_budget(o) for o in (self._object_by_instance_id(i) for i in picked) if o is not None
            )
            remaining_pool = [
                obj for obj in remaining_pool if self._power_for_budget(obj) <= int(power_budget) - spent_power
            ]
        if choice.get("distinct_card_types"):
            remaining_pool = [o for o in remaining_pool if _distinct_card_type_assignment(
                picked_card_types + [_card_type_words(o)]
            )]
        if declined or len(picked) >= choice["count"] or not remaining_pool:
            # (a choice the pick itself opened — RULE 508.4a's planeswalker offer for a creature just put into
            # combat — is a newer decision than this one and stays open)
            if self.state.pending_choice is choice:
                self.state.pending_choice = None
            self.state.release_batches()
            if choice.get("rest_destination") and choice.get("rest_ids"):
                if declined and choice.get("decline_leaves_untouched"):
                    pass
                else:
                    unpicked_rest = [iid for iid in choice["rest_ids"] if iid not in picked]
                    self._handle_rest_inspected(player, unpicked_rest, choice["rest_destination"])
            outer_controller = self.context.resolving_controller_id
            self.context.resolving_controller_id = choice.get("effect_controller_id")
            try:
                if picked:
                    # RULE 601.2c: "if you do, …" only fires when something was
                    # actually chosen — a declined optional choice does nothing.
                    self._apply_choose_objects_tail(
                        source, choice.get("then_specs"),
                        choice.get("then_specs_if_commander"), commander_taken,
                        choice.get("then_that_many"),
                        picked_measure if (choice.get("then_that_many") or {}).get("measure") else len(picked),
                        chosen_ids=[iid for iid in picked if visits is None or
                                    ((obj := self._object_by_instance_id(iid)) is not None
                                     and obj.zone_incarnation == visits.get(str(iid)))],
                    )
                elif choice.get("else_specs"):
                    # "If you don't, incubate 3." (Traumatic Revelation) — the
                    # declined-optional-choice branch `then_specs` deliberately
                    # skips.
                    self._apply_effect_specs(list(choice["else_specs"]), source)
            finally:
                self.context.resolving_controller_id = outer_controller
            return
        next_choice = self._choose_objects_choice(
            player, remaining_pool, choice["action"], choice["count"],
            choice["optional"], choice.get("prompt_base", ""),
            source_id=choice.get("source_id"), picked=picked,
            then_specs=choice.get("then_specs"),
            then_specs_if_commander=choice.get("then_specs_if_commander"),
            remember=bool(choice.get("remember")),
            track_exiled_with=bool(choice.get("track_exiled_with")),
            prevent_shield=choice.get("prevent_shield"),
            redirect_shield=choice.get("redirect_shield"),
            connive=bool(choice.get("connive")),
            rest_ids=choice.get("rest_ids"),
            rest_destination=choice.get("rest_destination"),
            decline_leaves_untouched=bool(choice.get("decline_leaves_untouched")),
            total_mana_value_budget=choice.get("total_mana_value_budget"),
            then_that_many=choice.get("then_that_many"),
            distinct_card_types=bool(choice.get("distinct_card_types")),
            total_power_budget=choice.get("total_power_budget"),
            minimum_card_types=int(choice.get("minimum_card_types", 0)),
        )
        next_choice["effect_controller_id"] = choice.get("effect_controller_id")
        next_choice["source_incarnation"] = choice.get("source_incarnation")
        next_choice["selection_visits"] = choice.get("selection_visits")
        for key in ("hand_visibility", "visible_hand_visits"):
            if key in choice:
                next_choice[key] = choice[key]
        next_choice["commander_taken"] = commander_taken
        next_choice["picked_measure"] = picked_measure
        next_choice["picked_card_types"] = [sorted(types) for types in picked_card_types]
        self.open_choice(next_choice)
    def _choose_objects_pool(
        self, choice: dict[str, Any], picked: list[int]
    ) -> list[GameObject]:
        """The still-offerable objects from a `choose_objects` choice."""
        return [
            self._object_by_instance_id(o["instance_id"])
            for o in choice["options"]
            if "instance_id" in o and o["instance_id"] not in picked
            and (choice.get("selection_visits") is None or
                 ((obj := self._object_by_instance_id(o["instance_id"])) is not None
                  and obj.zone_incarnation == choice["selection_visits"].get(str(obj.instance_id))))
        ]
    def _object_by_instance_id(self, instance_id: Optional[int]) -> Optional[GameObject]:
        """Any `GameObject` anywhere in the game, by id — the reverse lookup
        a serialized `pending_choice` needs to get back to real objects."""
        if instance_id is None:
            return None
        for obj in self.state.battlefield:
            if obj.instance_id == instance_id:
                return obj
        for player in self.state.players:
            for cards in player.zones.values():
                for obj in cards:
                    if obj.instance_id == instance_id:
                        return obj
        # A spell mid-resolution is in no zone (popped off the stack, not yet routed to its graveyard): its
        # suspended remainder (RULE 608.2) is where it still lives.
        if self.state.pending_permanent_entry:
            obj = self.state.pending_permanent_entry["obj"]
            if obj.instance_id == instance_id:
                return obj
        for frame in self.state.deferred_effects:
            for candidate in (frame.get("source"), getattr(frame.get("stack_item"), "obj", None)):
                if candidate is not None and getattr(candidate, "instance_id", None) == instance_id:
                    return candidate
        return None
