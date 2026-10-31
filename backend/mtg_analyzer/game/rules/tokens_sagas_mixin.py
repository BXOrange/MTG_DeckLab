"""Token creation, attacking entry, Sagas and cast tracking."""
from __future__ import annotations

from typing import Any, Callable, Optional
from ...models.cards.card import Card
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject, Zone
from ...models.game import turn_history
from ...models.game.game_state import StackItem, UncounterableGrant
from ...models.game.player import Player
from .. import card_registry, continuous


class TokensSagasMixin:
    """Token creation, attacking entry, Sagas and cast tracking."""

    def _finish_token_entry_object(self, token: GameObject, token_card: Card, controller_id: str) -> None:
        token.summoning_sick = True  # RULE 302.6 applies to tokens too
        # RULE 614.1 — see the matching comment in
        # `_resolve_permanent_spell` above.
        token.tapped = card_registry.enters_tapped(
            token_card
        ) or continuous.enters_tapped_from_static(self.state, token)
        self._apply_entry_counters(token)  # a token was never cast, so X is 0
        self.state.add_to_battlefield(token)
        self.state.fire_event(
            GameEvent(
                EventType.ENTERS_BATTLEFIELD,
                from_zone=None,  # RULE 111.2: created, not moved from a zone
                controller_id=controller_id,
                card_id=token_card.id,
                object=token.name,
                is_token=True,
                instance_id=token.instance_id,
                object_types=sorted(token.type_words),
            )
        )

    def _create_tokens_loop(
        self, token_card: Card, controller_id: str, zone: Zone, remaining: int, created: list[GameObject],
    ) -> None:
        """Create ``remaining`` tokens one by one, each through its pre-entry choices (RULE 614.12); resumable from the
        state-owned ``pending_token_entry`` via `_finish_token_entry`."""
        from ..binding.core import bind_from_catalogue  # function-scoped: avoid cycle
        if remaining <= 0:
            return
        token = GameObject(
            token_card,
            owner_id=controller_id,
            zone=zone,
            is_token=True,
        )
        bind_from_catalogue(token)  # token abilities are live like any card's
        if zone != Zone.BATTLEFIELD:
            self.state.player_by_id(controller_id).add_to_zone(token, zone)
            created.append(token)
            self._create_tokens_loop(token_card, controller_id, zone, remaining - 1, created)
            return

        def _after_copy() -> None:
            # RULE 614.12 / 400.7: the pending token and the rest of its batch live in `GameState`, so an
            # "as ~ enters" choice survives clone/undo (`_enter_choice_exit` -> `_finish_token_entry`).
            self.state.pending_token_entry = {
                "obj": token, "token_card": token_card, "controller_id": controller_id,
                "remaining": remaining - 1, "created": created,
            }
            self._offer_enter_choices(token, lambda: self._finish_token_entry(self.state.pending_token_entry))

        if token.enter_as_copy_effects:
            # RULE 614.1c/614.12: a token can carry its own "you may
            # have this enter as a copy of target X" replacement —
            # e.g. a token copy of Clever Impersonator, via
            # `copy_permanent`/RULE 707.2 — and gets the same
            # pre-entry choice a cast permanent does
            # (`_resolve_permanent_spell`/`_offer_enter_as_copy`).
            # `_offer_enter_as_copy` calls its continuation right away
            # when there's no legal target to offer, so the common
            # case (no card in the pool combines "create N token
            # copies" with a *second* legal target at creation time)
            # still finishes this whole loop synchronously; a real
            # choice instead stashes its continuation and resumes it
            # from `_resume_enter_as_copy`, at which point the
            # remaining tokens in this batch (if any) are built.
            self._offer_enter_as_copy(token, _after_copy)
        else:
            _after_copy()

    def _finish_token_entry(self, entry: dict[str, Any]) -> None:
        """RULE 111.5 / 614.12: a token whose "as ~ enters" choices are answered enters, then the rest of its batch is
        created. ``entry`` is the state-owned ``pending_token_entry``, so this also runs after a clone/undo."""
        self.state.pending_token_entry = None
        self._finish_token_entry_object(entry["obj"], entry["token_card"], entry["controller_id"])
        entry["created"].append(entry["obj"])
        self._create_tokens_loop(
            entry["token_card"], entry["controller_id"], Zone.BATTLEFIELD, entry["remaining"], entry["created"],
        )

    def create_token(
        self,
        controller_id: str,
        token_card: Card,
        count: int = 1,
        zone: Zone = Zone.BATTLEFIELD,
        on_created: Optional[Callable[[list[GameObject]], None]] = None,
        _creation_replacements_applied: bool = False,
    ) -> list[GameObject]:
        """Create ``count`` tokens under ``controller_id`` (RULE 111.5).

        Each token is a fresh `GameObject` flagged ``is_token`` (so RULE 704.5d
        removes it once it's stranded outside the battlefield), with its
        abilities bound from the token's own definition — exactly like a real
        permanent. The token's owner *and* controller is the creating player
        (RULE 111.4). Returns the tokens.

        ``zone`` defaults to the battlefield (the common case: entering play
        firing `ENTERS_BATTLEFIELD`, summoning sickness, RULE 614.1
        enters-tapped). Passing e.g. ``Zone.EXILE`` instead (RULE 722.3c's
        prepared copy, `make_prepared`) skips all of that battlefield-entry
        handling and just adds the token straight to the given zone — it
        never "enters the battlefield" at all, and (matching that: it was
        never really "created under a player's control" in the RULE 111.5
        sense either) isn't subject to token-doubling replacements below.

        ``on_created`` continues a battlefield-token effect after creation
        replacements finish, including an interactive RULE 616 order choice.
        It runs before the next SBA pass (Empower Jace starts at zero loyalty).

        A battlefield-bound ``count`` is routed through `apply_replacements`
        first, so a "create twice that many instead" replacement (RULE
        616.1, e.g. Doubling Season/Parallel Lives) can rewrite it before any
        token exists. No caller of `create_token`/`copy_permanent` currently
        depends on the *synchronous* return value beyond the common
        zero-ambiguity case (where it still resolves and returns
        immediately, same as before) — if a RULE 616.1 choice opens instead,
        this returns an empty list right away and the actual tokens are
        created later, once `_resume_replacement_order` finishes the
        chain. A token's own `enter_as_copy_effects` choice (below) can pause
        the very same way, for the very same reason.

        """
        from ..binding.core import bind_from_catalogue  # function-scoped: avoid cycle

        def _build(final_count: int) -> list[GameObject]:
            created: list[GameObject] = []
            self._create_tokens_loop(token_card, controller_id, zone, max(0, final_count), created)
            return created

        if zone != Zone.BATTLEFIELD or count <= 0 or _creation_replacements_applied:
            return _build(count)

        event = GameEvent(
            EventType.CREATE_TOKENS, controller_id=controller_id, amount=count,
            # "If you would create a Clue, Food, or Treasure token, instead
            # create one of each." (Academy Manufactor) / "…those tokens
            # plus an additional Food token are created instead." (Peregrin
            # Took) — both need to know *which* token is being made, not
            # just how many; `_double_tokens_replacement`'s own amount-only
            # scaling can't express either.
            token_name=token_card.name,
            # "If one or more creature tokens would be created under your control, …" (Divine
            # Visitation) — whether this token is a creature, which the name alone doesn't say.
            is_creature=bool(getattr(token_card, "is_creature", False)),
            # "If one or more artifact tokens would be created…" (Stridehangar Automaton).
            is_artifact=bool(getattr(token_card, "is_artifact", False)),
        )
        result: list[GameObject] = []

        def _finish(resolved: Optional[GameEvent]) -> None:
            nonlocal result
            if resolved is None:
                return
            substitute = resolved.get("token_definition")
            if substitute:
                # "If you would create a Fish token, create a 3/3 Shark instead." (Fisher's Talent): the
                # substitute is made in the original's place, and is not itself replaced again here — the
                # replacement chain (RULE 616.1) already ran before this point.
                from ...services.token_database import synthesize_token_card
                result = self.create_token(
                    controller_id,
                    synthesize_token_card(
                        name=substitute.get("token_name", "Creature"), power=substitute.get("power", 1),
                        toughness=substitute.get("toughness", 1), colors=substitute.get("colors", []),
                        subtypes=substitute.get("subtypes", []), keywords=substitute.get("keywords", []),
                    ),
                    resolved.get("amount", count), _creation_replacements_applied=True,
                )
            else:
                result = _build(resolved.get("amount", count))
            for batch in resolved.get("additional_tokens", []):
                from ...services.token_database import synthesize_token_card
                definition = batch["definition"]
                extra_card = synthesize_token_card(
                    name=definition.get("token_name", "Creature"), power=definition.get("power", 1),
                    toughness=definition.get("toughness", 1), colors=definition.get("colors", []),
                    subtypes=definition.get("subtypes", []), keywords=definition.get("keywords", []),
                    is_artifact=bool(definition.get("is_artifact", False)),
                )
                result.extend(self.create_token(
                    controller_id, extra_card, batch["amount"],
                    _creation_replacements_applied=True,
                ))
            # "The first time you create one or more tokens each turn, …"
            # (Mirrormind Crown) — same missing broadcast `add_counters`
            # had: `apply_replacements` only used this event to compute the
            # final amount, so nothing ever reached `_collect_triggers`.
            self.state.fire_event(resolved)

            if on_created is not None:
                on_created(result)

        self.apply_replacements(event, on_resolved=_finish)
        return result
    def put_onto_battlefield_attacking(
        self, obj: GameObject, defender: Optional[dict[str, Any]] = None
    ) -> bool:
        """RULE 508.4: an already-on-the-battlefield creature is put into
        combat *attacking* without having been declared — it doesn't tap for
        the attack (RULE 508.4) and summoning sickness doesn't stop it (it
        never "attacked"). RULE 508.4a: the effect's controller chooses which
        defender it attacks; with one obvious defender — the common
        two-player combat, or whatever the rest of this combat is already
        attacking — that choice is auto-made here. It deliberately does
        **not** fire `ATTACKS` or set ``attacked_this_turn``: RULE 508.3a says
        neither "whenever [this creature] attacks" nor declaration-history
        effects such as Boast see a creature put onto the battlefield
        attacking.

        This is the shared primitive behind "create a … token that's tapped
        **and attacking**" and "put a card … onto the battlefield tapped
        **and attacking**" (RULE 508.4) — the ``tapped`` half is applied
        separately by the caller. Returns whether the object actually joined
        combat. A missing/invalid defender leaves the object on the battlefield
        but not attacking (RULE 506.3b/c, 508.4a).
        """
        active = self.state.active_player
        if (
            not obj.is_creature
            or obj.controller_id != active.id
            or self.state.current_phase != "combat"
        ):
            return False

        # `RulesEngine` deliberately does not import the high-level
        # `GameEngine`, so mirror only the defender *universe* here (not its
        # declaration restrictions): 508.4c says those restrictions do not
        # apply to a creature entering attacking.
        ask_all_defenders = False
        legal: list[dict[str, Any]] = [
            {"kind": "player", "id": player.id, "label": player.name}
            for player in self.state.living_players()
            if player.id != active.id
        ]
        legal.extend(
            {"kind": "planeswalker", "instance_id": permanent.instance_id,
             "label": permanent.name}
            for permanent in self.state.battlefield
            if permanent.controller_id != active.id and permanent.is_planeswalker
        )
        legal.extend(
            {"kind": "battle", "instance_id": permanent.instance_id,
             "label": permanent.name}
            for permanent in self.state.battlefield
            if permanent.is_battle and permanent.protector_id not in (None, active.id)
        )

        def _same_defender(left: dict[str, Any], right: dict[str, Any]) -> bool:
            if left.get("kind") != right.get("kind"):
                return False
            key = "id" if left.get("kind") == "player" else "instance_id"
            return left.get(key) == right.get(key)

        if defender is not None:
            candidate = dict(defender)
            if not any(_same_defender(candidate, legal_defender) for legal_defender in legal):
                return False
        elif (source_defender := self._resolving_source_defender(obj, legal, _same_defender)) is not None:
            # RULE 508.4: the source supplies a convenient default, but an
            # unrestricted placement must offer every legal defender.
            candidate = dict(source_defender)
            ask_all_defenders = len(legal) > 1
        else:
            # RULE 508.4 supplies a choice. The engine has no priority-time
            # chooser for this primitive, so infer it only when the existing
            # combat or the legal defender set makes it unambiguous; never
            # silently pick the first opponent in multiplayer.
            current = [
                o.combat_defender
                for o in self.state.battlefield
                if o is not obj
                and getattr(o, "attacking", False)
                and o.combat_defender is not None
                and any(
                    _same_defender(o.combat_defender, legal_defender)
                    for legal_defender in legal
                )
            ]
            candidates = [
                legal_defender for legal_defender in legal
                if any(_same_defender(legal_defender, current_defender) for current_defender in current)
            ]
            if len(candidates) == 1:
                candidate = dict(candidates[0])
                ask_all_defenders = len(legal) > 1
            elif len(legal) == 1:
                candidate = dict(legal[0])
            elif legal:
                # RULE 508.4a: several defenders and nothing to infer from (no source attacking, no other attacker
                # to join): the creature enters attacking the first and its controller is asked where it goes.
                candidate = dict(legal[0])
                ask_all_defenders = True
            else:
                return False
        obj.attacking = True
        obj.combat_defender = candidate
        if ask_all_defenders:
            self._request_reselect_attack(self.state.player_by_id(obj.controller_id), obj, legal)
        return True

    def _resolving_source_defender(
        self, obj: GameObject, legal: list[dict[str, Any]], same_defender: Any,
    ) -> Optional[dict[str, Any]]:
        """The defender of the attacking creature whose triggered/activated ability is resolving now, when
        ``obj`` (its controller's) is put into combat by it and that defender is still a legal one."""
        item = getattr(self.context, "resolving_stack_item", None)
        source = getattr(item, "source", None)
        if source is None:
            source = self.state.find_object(getattr(self.context, "choice_source_id", None))
        if (
            source is None or source is obj or not getattr(source, "attacking", False)
            or source.controller_id != obj.controller_id or source.combat_defender is None
        ):
            return None
        defender = source.combat_defender
        return defender if any(same_defender(defender, d) for d in legal) else None

    def advance_sagas(self, player: Player) -> None:
        """Add a lore counter to each Saga ``player`` controls (RULE 714.3c).

        A turn-based action as the controller's precombat main phase begins
        (`GameEngine._step_main1`) — not off the draw step, despite this
        living there before it was fixed to match the CR. Fires
        `SAGA_CHAPTER` so a chapter ability whose number the new count
        reaches goes on the stack through the normal triggered-ability
        pipeline (RULE 714.2d). The 0-chapter-remaining Saga is sacrificed by
        a state-based action (`check_state_based_actions`), so this only
        advances the chapter here."""
        for obj in self.state.permanents_controlled_by(player.id):
            if obj.card.is_saga:
                obj.add_counters("lore", 1)
                self.state.fire_event(
                    GameEvent(
                        EventType.SAGA_CHAPTER,
                        object=obj.name,
                        instance_id=obj.instance_id,
                        controller_id=player.id,
                        chapter=obj.lore,
                    )
                )
    def _note_crime(self, item: StackItem) -> None:
        """RULE 700.13: fire `CRIME_COMMITTED` if ``item`` (a spell, or an activated or triggered
        ability, just put on the stack) targets an opponent, a permanent an opponent controls, or a
        spell, ability or card of an opponent's graveyard. "Opponent" is any other player."""
        me = item.controller_id
        for target in item.targets or []:
            if isinstance(target, Player):
                hostile = target.id != me
            elif isinstance(target, StackItem):
                hostile = target.controller_id != me
            elif isinstance(target, GameObject):
                if target.zone == Zone.GRAVEYARD:
                    hostile = target.owner_id != me
                else:  # battlefield, or a spell on the stack
                    hostile = target.controller_id not in (None, me)
            else:
                continue
            if hostile:
                self.state.fire_event(GameEvent(EventType.CRIME_COMMITTED, player_id=me, controller_id=me))
                return

    def _grant_uncounterable(
        self,
        player: Player,
        card_types: Optional[list[str]] = None,
        next_only: bool = False,
    ) -> None:
        """"Spells you control can't be countered this turn." (Veil of Summer) / "Creature
        spells you cast this turn can't be countered." (Domri) / "The next spell you cast
        this turn can't be countered." (Mistrise Village) — see `UncounterableGrant`.
        """
        turn = self.state.internal_turn.number
        grants = [g for g in self.state.uncounterable_grants if g.turn == turn]
        grants.append(UncounterableGrant(
            player.id, turn, card_types, next_only,
            casts_before=turn_history.spells_cast(self.state.events_this_turn())[player.id],
        ))
        self.state.uncounterable_grants = grants

    def _covered_by_uncounterable_grant(self, obj: GameObject) -> bool:
        """Is ``obj`` protected by a this-turn `UncounterableGrant` of its controller?"""
        turn = self.state.internal_turn.number
        types = getattr(obj, "type_words", None) or set()
        for grant in self.state.uncounterable_grants:
            if grant.turn != turn or grant.controller_id != obj.controller_id:
                continue
            if grant.card_types and not any(t in types for t in grant.card_types):
                continue
            if grant.next_only and obj.instance_id != self._next_cast_after(grant):
                continue
            return True
        return False

    def _next_cast_after(self, grant: "UncounterableGrant") -> Optional[int]:
        """The instance id of the first spell of ``grant``'s types its controller cast after
        the grant resolved — derived from the turn's `SPELL_CAST` events (oldest first)."""
        casts = [
            e for e in reversed(list(self.state.events_this_turn()))
            if e.type == EventType.SPELL_CAST and e.get("player_id") == grant.controller_id
        ]
        for event in casts[grant.casts_before:]:
            if not grant.card_types or any(t in (event.get("object_types") or []) for t in grant.card_types):
                return event.get("instance_id")
        return None
