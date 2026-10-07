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
import copy
from typing import Any, Callable, Optional, Union

from ...models.cards import card_query
from ...models.cards.card import Card
from ...models.game.emblem import Emblem
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject, Zone
from ...models.game.game_state import DelayedTrigger, GameState, StackItem
from ...models.mana.mana_cost import ManaCost
from ...models.game.player import Player
from ...parser.oracle.catalogue.keywords import parse_keywords
from ...parser.oracle.catalogue.saga import all_chapter_numbers
from .. import card_registry, combat, continuous, copy_mechanics, dungeons, face_down, variants
from ..combat import is_protected_from
from ..costs import DISCARD_HAND, ActivationCost, parse_activation_cost
from ..mana_abilities import restriction_predicate_for_cast
from ..effects.core import (
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
from .. import continuations

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




# RULE 707.10: casting choices are copied; cast history and mana expenditure are not.
_SPELL_COPY_CHOICES = (
    "kicker_count", "kicker_x_paid", "additional_cost_paid", "teamwork_paid", "bargained",
    "gift_promised", "gift_recipient_id", "blitz_cost_paid", "offered_additional_costs",
    "sacrificed_cost_mana_value", "sacrificed_cost_power", "sacrificed_cost_toughness",
    "sacrificed_cost_counters", "sacrificed_cost_card_types", "sacrificed_cost_was_suspected",
)


class CopiesMixin:
    """Copy effects, becoming a copy, and face changes (transform/manifest/face-down)."""

    def _copy_effect_memo(self, old_source=None, new_source=None, targets=()):
        memo = {id(self): self, id(self.state): self.state, id(self.context): self.context}
        for player in self.state.players:
            memo[id(player)] = player
            for zone in player.zones.values():
                memo.update({id(obj): obj for obj in zone})
        memo.update({id(obj): obj for obj in self.state.battlefield})
        for item in self.state.stack:
            memo[id(item)] = item
            for obj in (item.obj, item.source):
                if obj is not None:
                    memo[id(obj)] = obj
        memo.update({id(target): target for target in targets})
        if old_source is not None:
            memo[id(old_source)] = old_source if new_source is None else new_source
        return memo

    def _copied_spell_effects(self, item, obj):
        from ..binding.core import build_effects

        memo = self._copy_effect_memo(item.obj, obj, item.targets)
        effects = []
        for original in item.effects:
            spec = getattr(original, "_bound_spec", None)
            if spec is not None:
                effects.extend(build_effects([copy.deepcopy(spec, memo)], obj))
            else:
                effects.append(copy.deepcopy(original, memo))
        return effects

    def _advance_copy_targets(self):
        from ..stack_copy_targets import advance

        advance(self)

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
        set_colors: Optional[list[str]] = None,
        add_colors: Optional[list[str]] = None,
    ) -> list[GameObject]:
        """Create ``count`` token copies of ``source`` (RULE 707.2 / 111.5).

        A token copy takes ``source``'s *copiable* characteristics — for this
        basic version, its printed `Card` (the front face if it's transformed,
        RULE 712.4a) — and enters as a token under ``controller_id``. Reuses
        `create_token`, so the copy's own abilities bind and it follows the
        token cease-to-exist lifecycle (RULE 704.5d).

        ``add_types``/``add_subtypes``/``not_legendary`` are a copy effect's
        own "except it's a(n) X in addition to its other types"/"except it
        isn't legendary" clause (RULE 707.10 — Copy Artifact/Rite of
        Replication/Multiversal Recruitment-shaped), the same `Card.as_copy`
        modifiers `copy_mechanics.become_copy` already applies for the
        enters-as-a-copy replacement shape.
        """
        copiable = getattr(source, "_front_card", source.card)
        if add_colors:
            # "…in addition to its other colors" (PAR-135): the copiable colours plus these, expressed
            # through `Card.as_copy`'s replace-only ``set_colors`` so the card model needs no change.
            set_colors = sorted({*(set_colors if set_colors is not None else copiable.color_identity), *add_colors})
        if (add_types or add_subtypes or not_legendary or set_power is not None
                or set_toughness is not None or set_colors is not None):
            copiable = copiable.as_copy(
                add_types=add_types, add_subtypes=add_subtypes, not_legendary=not_legendary,
                set_power=set_power, set_toughness=set_toughness, set_colors=set_colors,
            )
        tokens = self.create_token(controller_id, copiable, count)
        # MEC-98: a copy carries the original's perpetual changes (Alchemy).
        for token in tokens:
            token.copy_perpetual_from(source)
        return tokens

    def _apply_populate_enter_state(
        self, tokens: list[GameObject], enter_state: Optional[dict]
    ) -> None:
        """RULE 508.4 / 110.5a rider on a populate: "…That token enters
        tapped and attacking." (Ghired, Conclave Exile). Applied to the copy
        the moment it enters, so nothing sees it untapped/non-attacking."""
        if not enter_state:
            return
        for tok in tokens:
            if enter_state.get("tapped"):
                tok.tapped = True
            if enter_state.get("attacking"):
                self.put_onto_battlefield_attacking(tok)

    def populate(
        self, player: Player, enter_state: Optional[dict] = None
    ) -> list[GameObject]:
        """"Populate" (RULE 701.36a): put a token onto the battlefield that's
        a copy of a creature token ``player`` controls. RULE 701.36b — if
        they control no creature tokens, populate does nothing.

        Degenerate cases resolve without asking, the same way `request_
        manifest_dread` does: no creature tokens → nothing; exactly one →
        copy it with no choice to make; two or more → an interactive
        `populate` `pending_choice` (RULE 701.36a's "a creature token he or
        she controls" is the controller's own free choice). The copy is
        itself a token, made via `copy_permanent`, so it binds its own
        abilities and follows the RULE 704.5d token lifecycle.

        ``enter_state`` (``{"tapped": bool, "attacking": bool}``) is a
        trailing "That token enters tapped and attacking" rider — applied to
        the copy here in the degenerate paths, carried on the
        ``pending_choice`` for the interactive one (`_resume_populate`).
        """
        tokens = [
            obj
            for obj in self.state.battlefield
            if obj.controller_id == player.id
            and getattr(obj, "is_token", False)
            and getattr(obj, "is_creature", False)
        ]
        if not tokens:
            return []
        if len(tokens) == 1:
            made = self.copy_permanent(player.id, tokens[0])
            self._apply_populate_enter_state(made, enter_state)
            return made
        self.open_choice({
            "kind": "populate",
            "player_id": player.id,
            "prompt": "Bevölkern: welches Kreaturen-Token wird kopiert?",
            "options": [
                {"id": str(obj.instance_id), "label": obj.name, "instance_id": obj.instance_id}
                for obj in tokens
            ],
            **({"enter_state": dict(enter_state)} if enter_state else {}),
        })
        return []
    @continuations.choice("populate", answer=continuations.ANSWER_INT, rule="701.36")
    def _resume_populate(self, choice: dict[str, Any], instance_id: Optional[int]) -> None:
        """Answer a pending `populate` choice: create a token copy of the
        chosen creature token. A missing/unrecognized answer defaults to the
        first offered token — populate is mandatory once you control one
        (RULE 701.36a has no "you may")."""
        player = self.state.player_by_id(choice["player_id"])
        offered = [opt["instance_id"] for opt in choice["options"]]
        chosen_id = instance_id if instance_id in offered else (offered[0] if offered else None)
        chosen = self._object_by_instance_id(chosen_id) if chosen_id is not None else None
        if chosen is not None:
            made = self.copy_permanent(player.id, chosen)
            self._apply_populate_enter_state(made, choice.get("enter_state"))
        self.check_state_based_actions()
    def _fire_spell_copied(self, item: StackItem) -> None:
        """RULE 707.10: copying triggers Magecraft, but never cast/storm history."""
        obj = item.obj
        if obj is None:
            return
        self.state.fire_event(GameEvent(
            EventType.SPELL_COPIED, player_id=item.controller_id,
            instance_id=obj.instance_id, stack_id=item.stack_id,
            object_types=sorted(obj.type_words), card_id=obj.card.id, spell=obj.name,
            mana_value=obj.mana_value, x_paid=item.x,
            target_instance_ids=[getattr(target, "instance_id", None)
                                 for target in item.targets or []
                                 if getattr(target, "instance_id", None) is not None],
        ))

    def copy_spell(
        self,
        target: Any,
        controller_id: str,
        count: int = 1,
        new_targets: Optional[list[Any]] = None,
        *, choose_new_targets: bool = False, defer_choice: bool = False,
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
        from ..binding.core import bind_from_catalogue  # function-scoped: avoid cycle

        item = self._stack_item_for(target)
        if item is None or item.obj is None:
            return []
        # RULE 707.10 / 715.3c: copy the spell's characteristics on the stack,
        # including an Adventure half rather than the card's creature face.
        copiable = item.obj.card
        copies: list[StackItem] = []
        for _ in range(count):
            copy_obj = GameObject(
                copiable.as_copy(), owner_id=controller_id, zone=Zone.STACK
            )
            # RULE 709.5b: even a copied right-half spell retains both Room halves.
            from ..rooms import has_doors

            if has_doors(item.obj._front_card):
                copy_obj._front_card = item.obj._front_card.as_copy()
            copy_obj.is_token = True
            copy_obj.is_copy = True
            copy_obj.x_paid = item.x
            for field in _SPELL_COPY_CHOICES:
                if hasattr(item.obj, field):
                    setattr(copy_obj, field, copy.deepcopy(getattr(item.obj, field)))
            # RULE 707.10: copying a spell copies alternative-cost decisions.
            copy_obj.blitz_cost_paid = item.obj.blitz_cost_paid
            bind_from_catalogue(copy_obj)
            copy_item = StackItem(
                kind="spell",
                controller_id=controller_id,
                effects=self._copied_spell_effects(item, copy_obj),
                obj=copy_obj,
                description=f"{item.obj.name} (Kopie)",
                targets=list(item.targets) if new_targets is None else list(new_targets),
                x=item.x,
                target_groups=item.target_groups if new_targets is None else None,
            )
            if new_targets is None:
                copy_item.target_incarnations = list(item.target_incarnations)
            copies.append(copy_item)
        from ..stack_copy_targets import stage

        stage(self, copies, may_choose=choose_new_targets and new_targets is None, defer=defer_choice)
        return copies
    def conjure_duplicate_into_hand(
        self, target: Any, controller_id: str,
    ) -> Optional[GameObject]:
        """"Conjure a duplicate of that spell into your hand." (Spellchain
        Scatter, PAR-124) — the hand-zone sibling of `copy_spell` above: a
        real, castable copy of a spell's own card, sitting in a hand rather
        than resolving off the stack. RULE 707's "a copy of a card" mechanic
        never actually distinguishes *where* the copy ends up (a token
        permanent, a stack item, or — this project's first instance — a hand
        card); only the destination zone differs from every other copy
        primitive here.
        """
        item = self._stack_item_for(target)
        if item is None or item.obj is None:
            return None
        from ..binding.core import bind_from_catalogue  # function-scoped: avoid cycle

        copiable = getattr(item.obj, "_front_card", item.obj.card)
        copy_obj = GameObject(copiable.as_copy(), owner_id=controller_id, zone=Zone.HAND)
        copy_obj.is_token = True
        copy_obj.is_copy = True
        # RULE 704.5d exempts a token only while it stays a permanent; this
        # one is deliberately created off the battlefield and meant to
        # persist there (`GameObject.conjured_into_hand`, see its own
        # docstring) — without this, `_remove_stranded_tokens` would reap it
        # the instant the next SBA pass ran, before it could ever be cast or
        # discarded.
        copy_obj.conjured_into_hand = True
        copy_obj.copy_perpetual_from(item.obj)  # MEC-98: a duplicate keeps perpetual changes
        bind_from_catalogue(copy_obj)
        player = self.state.player_by_id(controller_id)
        if player is None:
            return None
        player.hand.append(copy_obj)
        return copy_obj

    def copy_ability(
        self, target: Any, controller_id: str, new_targets: Optional[list[Any]] = None,
        *, choose_new_targets: bool = False, defer_choice: bool = False,
    ) -> Optional[StackItem]:
        """Put a copy of the activated ability ``target`` onto the stack
        (RULE 707.10 — Rings of Brighthearth's "copy that ability").

        The ability-item sibling of `copy_spell` above. An ability
        `StackItem` has no `GameObject` of its own to clone (`.obj` is
        ``None`` — RULE 707.10/ENG-26's `StackItem.stack_id` identity
        exists for exactly this), and its `ActivatedAbility` effect object
        (`.effects[0]`, bound once at bind-on-load to the permanent whose
        ability this is) is a stateless wrapper around its own ``effects``/
        ``source`` — nothing about it is per-activation, so the copy safely
        *reuses* the original's `effects` list rather than needing a fresh
        rebuild the way a spell copy's freshly-bound `spell_effects` does.
        Controlled by ``controller_id`` (RULE 707.10, the copier — always
        this same player for Rings, since it only copies abilities *you*
        activate). Keeps the original's targets by default (RULE 707.10c,
        extended to abilities by RULE 707.10); ``new_targets`` overrides
        that for "you may choose new targets for the copy". Pushed above
        the original so it resolves first (RULE 608.2 — LIFO).
        """
        item = self._stack_item_for(target)
        if item is None or item.kind != "ability":
            return None
        copy_item = StackItem(
            kind="ability",
            controller_id=controller_id,
            effects=copy.deepcopy(item.effects, self._copy_effect_memo(item.source, targets=item.targets)),
            source=item.source,
            description=f"{item.description} (Kopie)" if item.description else None,
            targets=list(item.targets) if new_targets is None else list(new_targets),
            x=item.x,
            target_groups=item.target_groups if new_targets is None else None,
            # A copy of "this ability" counts toward its resolutions too
            # (Ashling the Pilgrim's ruling: Rings of Brighthearth's copy counts).
            ability_key=item.ability_key,
            trigger_event=item.trigger_event,
        )
        copy_item.source_zone_incarnation = item.source_zone_incarnation
        if new_targets is None:
            copy_item.target_incarnations = list(item.target_incarnations)
        from ..stack_copy_targets import stage

        stage(self, [copy_item], may_choose=choose_new_targets and new_targets is None, defer=defer_choice)
        return copy_item
    def copy_self_spell(
        self, obj: GameObject, controller_id: str, targets: Optional[list[Any]] = None,
        *, choose_new_targets: bool = False,
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
        from ..binding.core import bind_from_catalogue  # function-scoped: avoid cycle

        original = self.context.resolving_stack_item
        if original is None or original.obj is not obj:
            original = next((frame.get("stack_item") for frame in reversed(self.state.deferred_effects)
                             if getattr(frame.get("stack_item"), "obj", None) is obj), None)
        if original is not None:
            # Temporarily expose the resolving item to the ordinary copy primitive.
            self.state.stack.append(original)
            try:
                copies = self.copy_spell(original, controller_id, choose_new_targets=choose_new_targets)
            finally:
                self.state.stack.remove(original)
            return copies[0] if copies else None
        copy_obj = GameObject(obj.card.as_copy(), owner_id=controller_id, zone=Zone.STACK)
        copy_obj.is_token = copy_obj.is_copy = True
        copy_obj.x_paid = obj.x_paid
        bind_from_catalogue(copy_obj)
        copy_item = StackItem(kind="spell", controller_id=controller_id,
                              effects=self._effects_for_spell(copy_obj), obj=copy_obj,
                              description=f"{obj.name} (Kopie)", targets=list(targets or []), x=obj.x_paid)
        from ..stack_copy_targets import stage

        stage(self, [copy_item], may_choose=choose_new_targets)
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
        add_keywords: Optional[list[str]] = None,
        not_legendary: bool = False,
    ) -> None:
        """``obj`` itself becomes a copy of ``target`` (RULE 707.2).

        Delegates to `copy_mechanics.become_copy` — moved there so
        `game/continuous.py`'s layer-1 conditional-copy pass can call the
        same mutate/rebind logic without importing this module (which would
        be circular). ``add_keywords``/``not_legendary`` are the copy's own "except …" clause (PAR-142)."""
        copy_mechanics.become_copy(
            obj, target, add_types, add_subtypes, add_keywords=add_keywords, not_legendary=not_legendary,
        )
    def become_copy_until_end_of_turn(
        self,
        obj: GameObject,
        target: GameObject,
        add_types: Optional[list[str]] = None,
        add_subtypes: Optional[list[str]] = None,
        add_keywords: Optional[list[str]] = None,
        not_legendary: bool = False,
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
        copy_mechanics.become_copy(
            obj, target, add_types, add_subtypes, add_keywords=add_keywords, not_legendary=not_legendary,
        )
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
        from ..binding.core import bind_from_catalogue  # function-scoped: avoid a cycle

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
        from ..binding.core import bind_from_catalogue  # function-scoped: avoid a cycle

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
        # RULE 712.8: "whenever ~ transforms into <name>, …" (Brutal Cathar).
        # Fired after the flip + rebind so the freshly-bound trigger is
        # already attached and the payload names the *new* face.
        if obj in self.state.battlefield:
            self.state.fire_event(
                GameEvent(
                    EventType.TRANSFORMED,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    controller_id=obj.controller_id,
                    object_types=sorted(obj.type_words),
                    face_name=obj.name,
                )
            )
        return True
    def meld(
        self, obj_a: GameObject, obj_b: GameObject, result_name: str
    ) -> Optional[GameObject]:
        """RULE 701.42a: meld the two cards ``obj_a``/``obj_b`` — exile them
        and return a *single* new permanent, the meld pair's back-face
        ``result_name`` card, under ``obj_a``'s controller's control.

        RULE 701.42b/701.42c: only two real meld cards can be melded — a
        token, or a partner this engine can't resolve to a cached card, or
        an already-melded object, aborts the whole thing with **nothing
        exiled** (a deliberate strengthening of 701.42c's "they stay in
        their current zone": since the only caller is a self-checking
        trigger, refusing before the exile is simpler and reaches the same
        board state). Returns the melded permanent, or ``None`` if it
        couldn't happen.
        """
        from ...services.card_lookup import card_by_name  # function-scoped: cache access

        if obj_a is None or obj_b is None or obj_a is obj_b:
            return None
        if any(getattr(o, "is_token", False) or getattr(o, "is_melded", False)
               for o in (obj_a, obj_b)):
            return None
        result_card = card_by_name(result_name)
        if result_card is None:
            return None  # offline/empty cache — RULE 608.2b "do as much as possible"

        controller = self.state.player_by_id(obj_a.controller_id)
        # RULE 701.42a "exile them" — a real zone visit so LEAVES_BATTLEFIELD /
        # EXILE fire for each front face, then lift both out of exile into the
        # melded permanent's limbo (`zone = None`, held on `melded_components`).
        components: list[GameObject] = []
        for comp in (obj_a, obj_b):
            self._detach_attachments_from(comp)
            self.exile(comp)
            owner = self.state.player_by_id(comp.owner_id)
            owner.remove_from_zone(comp, Zone.EXILE)
            comp.reset_as_new_object()
            comp.zone = None
            components.append(comp)

        melded = GameObject(result_card, owner_id=controller.id, zone=Zone.BATTLEFIELD)
        melded.controller_id = controller.id
        melded.is_melded = True
        melded.melded_components = components
        self._put_searched_card(controller, melded, "battlefield")
        self.state.fire_event(GameEvent(
            EventType.MELDED,
            object=melded.name,
            instance_id=melded.instance_id,
            controller_id=melded.controller_id,
            object_types=sorted(melded.type_words),
        ))
        return melded
    def _split_melded_after_move(self, obj: GameObject, zone: Zone) -> None:
        """RULE 712.19: a melded permanent that has just left the battlefield
        for ``zone`` separates back into its two component cards, which move
        to that same zone. Called at the tail of every battlefield-exit
        primitive (`_move_to_graveyard`/`exile`/`return_to_hand`/
        `return_to_library`/`shuffle_into_library`) right after the melded
        object was placed — a no-op for anything not `is_melded`.
        """
        if not getattr(obj, "is_melded", False) or not obj.melded_components:
            return
        components = obj.melded_components
        obj.is_melded = False
        obj.melded_components = []
        owner = self.state.player_by_id(obj.owner_id)
        owner.remove_from_zone(obj, zone)
        for comp in components:
            comp.reset_as_new_object()
            self.state.player_by_id(comp.owner_id).add_to_zone(comp, zone)
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
        # RULE 701.40g/701.58g: an instant or sorcery is revealed and stays
        # face down, and nothing triggers.
        hidden = obj.face_down and (obj._face_up_snapshot or {}).get("card")
        if hidden is not None and (getattr(hidden, "is_instant", False)
                                   or getattr(hidden, "is_sorcery", False)):
            return False
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
    def _request_manifest_dread(self, player: Player) -> list[GameObject]:
        """"Manifest dread": look at the top two cards of ``player``'s
        library, manifest one face down and put the other into the graveyard.

        Its own `pending_choice` kind rather than a `_request_choose_objects`
        call, because the generic chooser only ever *acts on the picks* — it
        has no notion of "and the ones you didn't pick go somewhere else",
        which is the entire second half of this keyword action. Degenerate
        libraries resolve without asking: one card left is manifested with no
        choice to make, an empty one does nothing (RULE 701.40f).

        Returns what it manifested *now* (the one-card library); an answered choice hands the permanent to a
        suspended "then attach ~ to that creature" itself (`_resume_manifest_dread`).
        """
        looked = player.library[-2:]
        if not looked:
            return []
        if len(looked) == 1:
            return self.manifest(player, 1)
        self.open_choice({
            "kind": "manifest_dread",
            "player_id": player.id,
            # RULE 608.2: where the rest of the resolving effect list parks if this choice suspends it
            # (`_apply_effects_partitioned` inserts it at the depth it saw before the effect ran).
            "deferred_depth": len(self.state.deferred_effects),
            "prompt": "Manifest dread: welche Karte wird verdeckt gespielt?",
            "options": [
                {"id": str(obj.instance_id), "label": obj.name, "instance_id": obj.instance_id}
                for obj in reversed(looked)  # top card first
            ],
        })
    @continuations.choice("manifest_dread", answer=continuations.ANSWER_INT, rule="701.62")
    def _resume_manifest_dread(self, choice: dict[str, Any], instance_id: Optional[int]) -> None:
        """Answer a pending manifest-dread choice: manifest the chosen card,
        mill the other. A missing/unrecognized answer defaults to the top
        card — the choice is mandatory (RULE 701.40a's "put one … and the
        other …"), so declining can't mean "neither"."""
        player = self.state.player_by_id(choice["player_id"])
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
        # "…manifest dread, then attach ~ to that creature": the clause after the pause reads the manifested
        # permanent as `created_objects`, which the suspended remainder carried before it existed.
        depth = choice.get("deferred_depth")
        if chosen is not None and depth is not None and len(self.state.deferred_effects) > depth:
            frame = self.state.deferred_effects[depth]
            if frame.get("kind") != self.DEFERRED_ITERATION:
                frame["created_objects"] = list(frame.get("created_objects") or []) + [chosen]
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
