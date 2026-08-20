"""The rules engine: mana, casting, stack, replacements, triggers, SBAs.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.2-R2.8,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 2/3).

This owns the *rules primitives* — the operations whose consequences are
defined by the Comprehensive Rules — so they live in exactly one place:

* draw / deal damage / destroy / discard, each routed through replacement
  effects (RULE 614/616) and firing events that collect triggers (603).
* the stack (RULE 608, LIFO resolution).
* state-based actions (RULE 704).
* mana cost lookup and payment (RULE 601.2g / 504) via `ManaPool`.

The higher-level turn/phase/priority loop lives in `game_engine.py`; this
engine is the toolbox that loop drives.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional, Union

from ...models import card_query
from ...models.card import Card
from ...models.emblem import Emblem
from ...models.events import EventType, GameEvent
from ...models.game_object import GameObject, Zone
from ...models.game_state import DelayedTrigger, GameState, StackItem
from ...models.mana_cost import ManaCost
from ...models.player import Player
from ...parser.oracle.catalogue.keywords import parse_keywords
from ...parser.oracle.catalogue.saga import all_chapter_numbers
from .. import ability_catalogue, combat, continuous, copy_mechanics, dungeons, face_down, variants
from ..combat import is_protected_from
from ..costs import DISCARD_HAND, ActivationCost, parse_activation_cost
from ..mana_abilities import restriction_predicate_for_cast
from ..effects import (
    _apply_effects_partitioned,
    AddCountersEffect,
    CompleteDungeonEffect,
    VentureIntoTheDungeonEffect,
    AddPlayerCountersEffect,
    BecomeMonarchEffect,
    CantBeCounteredEffect,
    ChooseColorReplacement,
    ChooseCreatureTypeReplacement,
    ChooseNamedModeReplacement,
    DiscardEffect,
    DrawCardEffect,
    LoseLifeEffect,
    ReturnUncastExiledEffect,
    SacrificeSpecificEffect,
    TheRingTemptsYouEffect,
    GameContext,
    GameEffect,
    ImpulsiveDrawEffect,
    MarchesaDelayedReturnEffect,
    ProliferateEffect,
    PumpEffect,
    RadiationMillEffect,
    ReboundFreeCastWindowEffect,
    ReplacementEffect,
    ReturnSelfFromGraveyardEffect,
    SiegeDefeatedEffect,
    StaticAbility,
    StaticEffect,
    TakeInitiativeEffect,
    TriggeredAbility,
    WardEffect,
    WinConditionEffect,
)
from ..targeting import TargetSpec, collapse_groups, expand_counts, legal_targets

def _saga_final_chapter(card: Card) -> int:
    """The highest chapter number a Saga has (RULE 714.2c), 0 if unreadable.

    Read off the oracle text's roman-numeral chapter markers ("I —", "II, III —",
    "IV —"); the largest is the final chapter. Shares its numeral grammar with
    the oracle-parser front-end's chapter-ability recognition
    (`parser.oracle.catalogue.saga`, RULE 714.2d) rather than duplicating it."""
    return max(all_chapter_numbers(card.oracle_text or ""), default=0)


def _matches_permanent_type(obj: GameObject, what: str) -> bool:
    """Whether ``obj`` matches a sacrifice cost/effect's type word (RULE
    701.17), e.g. ``"creature"``/``"artifact"``/``"enchantment"``/``"land"``/
    ``"permanent"``. Mirrors `GameEngine._matches_sacrifice_type` (the
    cost-payment path) for the effect-driven path (`RulesEngine.sacrifice`);
    kept as its own small copy rather than a cross-module import, since
    `game_engine.py` imports `rules_engine.py`, not the reverse."""
    if what in ("permanent", "another"):
        return True
    if what == "creature":
        return obj.is_creature
    if what == "artifact":
        return obj.card.is_artifact
    if what == "enchantment":
        return obj.card.is_enchantment
    if what == "land":
        return obj.is_land
    if what == "creature_or_planeswalker":
        # RULE 306/302: Tevesh Szat's "another creature or planeswalker" —
        # the one compound word any shipped card needs.
        return obj.is_creature or obj.card.is_planeswalker
    return True  # unknown type word → any permanent, so the cost is payable


def _creature_type_options(state: GameState, controller_id: Optional[str]) -> list[str]:
    """The creature-type choices to offer for a RULE 601.2b "as ~ enters,
    choose a creature type" pick.

    RAW technically lets a player name *any* creature type, including one no
    card in the game has — an unbounded, ~300-entry vocabulary this engine
    has no canonical list of (unlike a scoped tribal-lord subtype match,
    which just substring-tests against whatever's actually printed,
    `continuous._has_subtype`). Offering every official type as a button
    isn't a real UI, so this instead offers every creature subtype among
    cards ``controller_id`` actually has anywhere in the game (battlefield,
    hand, library, graveyard, exile, command) — the practically relevant
    set for boosting *their own* creatures, which is what every real card in
    this family (Adaptive Automaton/Arcane Adaptation-shaped) is for. A
    puzzle board with no creature cards anywhere offers nothing — see
    `RulesEngine._offer_enter_choices`'s empty-options handling.
    """
    player = state.player_by_id(controller_id) if controller_id else None
    if player is None:
        return []
    objects = [o for o in state.battlefield if o.owner_id == controller_id]
    objects += list(player.library) + list(player.hand) + list(player.graveyard)
    objects += list(player.exile) + list(player.command)
    types: set[str] = set()
    for obj in objects:
        type_line = (getattr(obj.card, "type_line", "") or "").lower()
        if "creature" not in type_line:
            continue
        _, _, sub = type_line.partition("—")
        for word in re.findall(r"[a-z]+", sub):
            types.add(word.capitalize())
    return sorted(types)




class CopiesMixin:
    """Copy effects, becoming a copy, and face changes (transform/manifest/face-down)."""

    def copy_permanent(
        self,
        controller_id: str,
        source: GameObject,
        count: int = 1,
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
        not_legendary: bool = False,
        set_power: Optional[int] = None,
        set_toughness: Optional[int] = None,
    ) -> list[GameObject]:
        """Create ``count`` token copies of ``source`` (RULE 707.2 / 111.5).

        A token copy takes ``source``'s *copiable* characteristics — for this
        basic version, its printed `Card` (the front face if it's transformed,
        RULE 712.4a) — and enters as a token under ``controller_id``. Reuses
        `create_token`, so the copy's own abilities bind and it follows the
        token cease-to-exist lifecycle (RULE 704.5d).

        ``add_types``/``add_subtypes``/``not_legendary`` are a copy effect's
        own "except it's a(n) X in addition to its other types"/"except it
        isn't legendary" clause (RULE 706.10 — Copy Artifact/Rite of
        Replication/Multiversal Recruitment-shaped), the same `Card.as_copy`
        modifiers `copy_mechanics.become_copy` already applies for the
        enters-as-a-copy replacement shape.
        """
        copiable = getattr(source, "_front_card", source.card)
        if add_types or add_subtypes or not_legendary or set_power is not None or set_toughness is not None:
            copiable = copiable.as_copy(
                add_types=add_types, add_subtypes=add_subtypes, not_legendary=not_legendary,
                set_power=set_power, set_toughness=set_toughness,
            )
        return self.create_token(controller_id, copiable, count)
    def copy_spell(
        self,
        target: Any,
        controller_id: str,
        count: int = 1,
        new_targets: Optional[list[Any]] = None,
    ) -> list[StackItem]:
        """Put ``count`` copies of the spell ``target`` onto the stack (RULE
        707.10 — Dualcaster Mage/Reiterate/Flare of Duplication "copy target
        instant or sorcery spell").

        ``target`` is the spell's `StackItem` or its underlying `GameObject`
        (whatever `CopySpellEffect` was handed). A copy is a brand-new
        `StackItem` controlled by ``controller_id`` (RULE 707.10c — the
        copier, who may differ from the original's controller), carrying a
        fresh token `GameObject` of the spell's copiable card so its own
        resolve-time effects rebind cleanly (`_effects_for_spell`) rather
        than sharing the original's effect instances. The copy keeps the
        original's targets by default (RULE 707.10c "the copy has the same
        targets") and its announced {X} (RULE 707.10e) — ``new_targets``
        overrides the former for the "you may choose new targets" clause.
        Copies are pushed **above** the original so they resolve first
        (RULE 608.2 — LIFO). A copy of a permanent spell resolves into a
        token permanent; a copy of an instant/sorcery applies its effects
        then ceases to exist (its token `GameObject` is reaped by the RULE
        704.5d stranded-token SBA the moment the resolve path routes it off
        the stack).
        """
        from ..effect_binder import bind_from_catalogue  # function-scoped: avoid cycle

        item = self._stack_item_for(target)
        if item is None or item.obj is None:
            return []
        copiable = getattr(item.obj, "_front_card", item.obj.card)
        copies: list[StackItem] = []
        for _ in range(count):
            copy_obj = GameObject(
                copiable.as_copy(), owner_id=controller_id, zone=Zone.STACK
            )
            copy_obj.is_token = True
            copy_obj.is_copy = True
            copy_obj.x_paid = item.x
            bind_from_catalogue(copy_obj)
            copy_item = StackItem(
                kind="spell",
                controller_id=controller_id,
                effects=self._effects_for_spell(copy_obj),
                obj=copy_obj,
                description=f"{item.obj.name} (Kopie)",
                targets=list(item.targets) if new_targets is None else list(new_targets),
                x=item.x,
                target_groups=item.target_groups if new_targets is None else None,
            )
            self.state.stack.append(copy_item)
            copies.append(copy_item)
        return copies
    def copy_self_spell(
        self, obj: GameObject, controller_id: str, targets: Optional[list[Any]] = None,
    ) -> Optional[StackItem]:
        """"You may copy this spell [and may choose a new target for the
        copy]." (Sevinne's Reclamation's own trailing clause, MEC-42) —
        the self-copy sibling of `copy_spell` above, needed because by the
        time a spell's own *trailing* effect resolves, the original has
        already been popped off `GameState.stack` (RULE 608.2m — this
        function runs from inside that same resolution), so there is no
        live `StackItem` left for `_stack_item_for` to find. Builds the
        copy directly off ``obj`` (still a valid `GameObject` reference)
        instead.

        ``targets`` keeps the original's own already-gathered targets by
        default (RULE 707.10c's default outcome) — the same "no genuine
        new-target choice, MVP keeps the original's" simplification
        `copy_spell` already documents for every other consumer, not a
        fresh gap. Passing ``self.source``'s own resolving ``targets``
        (the shared list every effect on the same stack item reads) is
        what makes the copy actually reanimate something instead of
        finding no target at all and quietly doing nothing.
        """
        from ..effect_binder import bind_from_catalogue  # function-scoped: avoid cycle

        copiable = getattr(obj, "_front_card", obj.card)
        copy_obj = GameObject(copiable.as_copy(), owner_id=controller_id, zone=Zone.STACK)
        copy_obj.is_token = True
        copy_obj.is_copy = True
        bind_from_catalogue(copy_obj)
        copy_item = StackItem(
            kind="spell",
            controller_id=controller_id,
            effects=self._effects_for_spell(copy_obj),
            obj=copy_obj,
            description=f"{obj.name} (Kopie)",
            targets=list(targets or []),
        )
        self.state.stack.append(copy_item)
        return copy_item
    def make_prepared(self, obj: GameObject) -> None:
        """``obj`` becomes prepared (RULE 722.3a — a preparation card's
        "~ becomes prepared" effect).

        A no-op if ``obj`` is already prepared (RULE 722.3a: "can't gain
        this designation if the permanent already has it") or has no
        prepare spell at all (``back_face()`` is ``None``). Otherwise sets
        the `prepared` designation and creates one token copy of the
        prepare spell's characteristics directly into ``obj``'s
        controller's exile (RULE 722.3c) — not the battlefield, so
        `create_token`'s battlefield-entry handling (summoning sickness,
        `ENTERS_BATTLEFIELD`) correctly never runs for it. The copy is
        linked back via `prepared_source_id`; `_remove_stranded_tokens`
        keeps it alive only for as long as ``obj`` stays on the battlefield
        with `prepared` still set — no separate cleanup/expiry needed here.
        """
        if obj.prepared:
            return
        prepare_spell = obj.card.back_face()
        if prepare_spell is None:
            return
        obj.prepared = True
        copies = self.create_token(obj.controller_id, prepare_spell, zone=Zone.EXILE)
        copies[0].prepared_source_id = obj.instance_id
    def become_copy(
        self,
        obj: GameObject,
        target: GameObject,
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
    ) -> None:
        """``obj`` itself becomes a copy of ``target`` (RULE 706/707.2).

        Delegates to `copy_mechanics.become_copy` — moved there so
        `game/continuous.py`'s layer-1 conditional-copy pass can call the
        same mutate/rebind logic without importing this module (which would
        be circular)."""
        copy_mechanics.become_copy(obj, target, add_types, add_subtypes)
    def become_copy_until_end_of_turn(
        self,
        obj: GameObject,
        target: GameObject,
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
    ) -> None:
        """``obj`` becomes a copy of ``target`` until end of turn (Cursed
        Mirror-style: "{T}: ~ becomes a copy of target creature until end of
        turn."). Unlike `become_copy`'s permanent mutation, `GameEngine.
        _step_cleanup` (RULE 514.2, the same step that ends pump/keyword
        "until end of turn" effects) reverts this via the snapshot stashed
        here — taken only the *first* time this turn, so a second activation
        before cleanup doesn't overwrite the true original with an
        already-copied state."""
        if obj._copy_until_eot_base is None:
            obj._copy_until_eot_base = copy_mechanics.snapshot_face(obj)
        copy_mechanics.become_copy(obj, target, add_types, add_subtypes)
    def set_copy_target(self, obj: GameObject, target: GameObject) -> None:
        """Choose/change the target a layer-1 conditional-copy static ability
        copies (Vesuvan Shapeshifter's "you may have it be a copy of another
        target creature") — `continuous.recompute`'s layer-1 pass reads
        `obj.copy_target_id` fresh every recompute, the same idiom
        `attached_to` uses."""
        if target is not None and target is not obj:
            obj.copy_target_id = target.instance_id
    def snapshot_face(self, obj: GameObject) -> dict[str, Any]:
        """Capture ``obj``'s current `Card` + catalogue-derived bindings.

        Pairs with `restore_face` to undo a `switch_to_face` — used when
        previewing or attempting a modal DFC's un-chosen face (RULE 712.10)
        so a rejected cast never leaves the object silently switched.
        Delegates to `copy_mechanics.snapshot_face`."""
        return copy_mechanics.snapshot_face(obj)
    def restore_face(self, obj: GameObject, snapshot: dict[str, Any]) -> None:
        """Undo a `switch_to_face`, restoring exactly what `snapshot_face`
        saved. Delegates to `copy_mechanics.restore_face`."""
        copy_mechanics.restore_face(obj, snapshot)
    def switch_to_face(self, obj: GameObject, card: Card) -> None:
        """Rebind ``obj`` onto ``card`` — another face of the same physical
        object (RULE 712.10, choosing a modal DFC's face to cast/play).

        Mirrors `become_copy`'s "clear + rebind catalogue-derived abilities"
        treatment: a face's activated/triggered/static/spell effects and
        keywords are its own, not shared with the other face, so they must be
        rebound from ``card`` rather than left pointing at the old face's.
        Unlike `become_copy` this doesn't touch counters/zone/control — it's
        a face choice, not a copy effect."""
        from ..effect_binder import bind_from_catalogue  # function-scoped: avoid a cycle

        obj.card = card
        obj.spell_effects = []
        obj.triggered_abilities = []
        obj.activated_abilities = []
        obj.static_effects = []
        obj.replacement_effects = []
        obj.enter_as_copy_effects = []
        obj.intrinsic_keywords = set()
        obj.parametric_keywords = {}
        bind_from_catalogue(obj)
    def transform_permanent(self, obj: GameObject) -> bool:
        """Flip a double-faced permanent to its other face (RULE 712.8).

        Mirrors `switch_to_face`'s "clear + rebind catalogue-derived
        abilities" treatment: `GameObject.transform` only swaps ``card``, so
        without this a transformed permanent would keep its *other* face's
        keywords/triggered/activated/static abilities forever (e.g. a
        daybound/nightbound permanent's own daybound/nightbound keyword,
        RULE 702.145, would never update). Returns whether it flipped — a
        no-op (``False``) for a card with no back face, same as
        `GameObject.transform`."""
        from ..effect_binder import bind_from_catalogue  # function-scoped: avoid a cycle

        if not obj.transform():
            return False
        obj.spell_effects = []
        obj.triggered_abilities = []
        obj.activated_abilities = []
        obj.static_effects = []
        obj.replacement_effects = []
        obj.enter_as_copy_effects = []
        obj.intrinsic_keywords = set()
        obj.parametric_keywords = {}
        bind_from_catalogue(obj)
        return True
    def turn_face_down(self, obj: GameObject, kind: str) -> None:
        """Turn ``obj`` face down as ``kind`` (RULE 708.2 — ``"morph"``/
        ``"disguise"``/``"manifest"``/``"cloak"``, see `game/face_down.py`).

        The object's whole face-up bundle is stashed on it and its `Card` is
        swapped for the synthetic 2/2 — the same "swap the face, rebind the
        abilities" shape `switch_to_face` uses for a DFC, except that here
        the new face has no text at all, so there is nothing to bind and the
        clear *is* the rebind. RULE 702.168a/701.58a's ward {2} is stamped on
        for the disguise/cloak variants, since a face-down object's
        characteristics are exactly what the rule that made it face down
        lists — nothing is read off the card underneath.
        """
        obj.turn_face_down(face_down.face_down_card(kind), kind)
        if kind in face_down.WARD_KINDS:
            obj.intrinsic_keywords = {"ward"}
            obj.parametric_keywords = {"ward": {"cost": "{2}"}}
    def turn_face_up(self, obj: GameObject, megamorph: bool = False) -> bool:
        """Turn a face-down permanent face up (RULE 708.8). Returns whether
        it was face down at all.

        Restores the stashed face-up characteristics and abilities, then —
        for a megamorph cost being paid (RULE 702.37b) — puts a +1/+1 counter
        on it *as* it turns face up, which is why the counter is placed
        directly rather than through `add_counters` (that would fire a
        replaceable COUNTER event for something the rules treat as part of
        the turn-face-up itself). RULE 708.8: entering-the-battlefield
        abilities don't trigger — the permanent has been on the battlefield
        all along — so the only event fired is `EventType.TURNED_FACE_UP`.
        """
        if not obj.turn_face_up():
            return False
        if megamorph:
            obj.counters["+1/+1"] = obj.counters.get("+1/+1", 0) + 1
        self.state.fire_event(
            GameEvent(
                EventType.TURNED_FACE_UP,
                instance_id=obj.instance_id,
                controller_id=obj.controller_id,
                object=obj.name,
                card_id=obj.card.id,
                object_types=sorted(obj.type_words),
            )
        )
        self.check_state_based_actions()
        return True
    def manifest(self, player: Player, count: int = 1, kind: str = "manifest") -> list[GameObject]:
        """Manifest (RULE 701.40a) or cloak (RULE 701.58a) the top ``count``
        cards of ``player``'s library: turn each face down and put it onto
        the battlefield as a 2/2 face-down creature.

        RULE 701.40e/701.58e: multiple cards are manifested **one at a
        time**, which is what this loop is — each card is turned face down
        and enters before the next is looked at, so a replacement effect or
        an ETB trigger on the first can see the second still in the library.
        Returns the permanents created (empty for an empty library — RULE
        701.40f's "nothing to manifest" case).
        """
        made: list[GameObject] = []
        for _ in range(max(0, count)):
            if not player.library:
                break
            obj = player.library[-1]
            player.remove_from_zone(obj, Zone.LIBRARY)
            obj.controller_id = player.id
            self.turn_face_down(obj, kind)
            # RULE 708.3: the card is turned face down *before* it enters,
            # so its own enters-the-battlefield abilities never trigger —
            # already true here, since `turn_face_down` cleared them.
            self._put_searched_card(player, obj, "battlefield")
            made.append(obj)
        return made
    def request_manifest_dread(self, player: Player) -> None:
        """"Manifest dread": look at the top two cards of ``player``'s
        library, manifest one face down and put the other into the graveyard.

        Its own `pending_choice` kind rather than a `request_choose_objects`
        call, because the generic chooser only ever *acts on the picks* — it
        has no notion of "and the ones you didn't pick go somewhere else",
        which is the entire second half of this keyword action. Degenerate
        libraries resolve without asking: one card left is manifested with no
        choice to make, an empty one does nothing (RULE 701.40f).
        """
        looked = player.library[-2:]
        if not looked:
            return
        if len(looked) == 1:
            self.manifest(player, 1)
            return
        self.state.pending_choice = {
            "kind": "manifest_dread",
            "player_id": player.id,
            "prompt": "Manifest dread: welche Karte wird verdeckt gespielt?",
            "options": [
                {"id": str(obj.instance_id), "label": obj.name, "instance_id": obj.instance_id}
                for obj in reversed(looked)  # top card first
            ],
        }
    def resolve_manifest_dread_choice(self, instance_id: Optional[int]) -> None:
        """Answer a pending manifest-dread choice: manifest the chosen card,
        mill the other. A missing/unrecognized answer defaults to the top
        card — the choice is mandatory (RULE 701.40a's "put one … and the
        other …"), so declining can't mean "neither"."""
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "manifest_dread":
            raise ValueError("no pending manifest-dread choice to resolve")
        player = self.state.player_by_id(choice["player_id"])
        self.state.pending_choice = None
        offered = [opt["instance_id"] for opt in choice["options"]]
        chosen_id = instance_id if instance_id in offered else offered[0]
        chosen = self._object_by_instance_id(chosen_id)
        others = [self._object_by_instance_id(i) for i in offered if i != chosen_id]
        if chosen is not None:
            player.remove_from_zone(chosen, Zone.LIBRARY)
            chosen.controller_id = player.id
            self.turn_face_down(chosen, "manifest")
            self._put_searched_card(player, chosen, "battlefield")
        for other in others:
            if other is not None and other in player.library:
                player.remove_from_zone(other, Zone.LIBRARY)
                player.add_to_zone(other, Zone.GRAVEYARD)
        self.check_state_based_actions()
    def exile_return_transformed(self, obj: GameObject) -> bool:
        """"Exile ~, then return it to the battlefield transformed under its
        owner's control" (RULE 400.7 + RULE 712.8 combined — a transforming
        Saga's own final chapter, Fable of the Mirror-Breaker-shaped, or a
        transform-flip permanent's activated ability that phrases its flip
        this way instead of a plain in-place `transform_permanent`,
        Ayara/Clive/Jin-Gitaxias-shaped).

        Unlike `transform_permanent` (an in-place face swap on the same
        object), this is a genuine RULE 400.7 zone change — `blink` plus a
        forced flip onto the back face: a brand-new object enters directly
        already transformed, so leaves/enters-the-battlefield triggers
        refire, counters/attachments/"until end of turn" effects fall off,
        and it re-enters with summoning sickness. Always ends up on the back
        face regardless of which face ``obj`` started on
        (`reset_as_new_object` always presents the front face first, RULE
        711.8, then `transform_permanent` flips it exactly once). Returns
        whether it flipped — ``False`` (a no-op, nothing exiled) for a card
        with no back face at all — checked against ``_front_card`` rather
        than ``obj.card`` so it's correct even if ``obj`` happened to
        already be on its back face when this resolves.
        """
        if obj._front_card.back_face() is None:
            return False
        owner = self.state.player_by_id(obj.owner_id)
        self._detach_attachments_from(obj)
        self.exile(obj)
        obj.reset_as_new_object()
        obj.controller_id = owner.id
        self.transform_permanent(obj)
        self._put_searched_card(owner, obj, "battlefield")
        return True
