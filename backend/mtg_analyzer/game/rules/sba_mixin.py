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




class StateBasedActionsMixin:
    """RULE 704 state-based actions and game-loss/game-over bookkeeping."""

    def check_state_based_actions(self) -> bool:
        """Apply SBAs until none apply (RULE 704.3). Returns whether any did.

        Covers the MVP subset (docs/02 R2.8): life <= 0 loss, drawing from
        an empty library loss, 0-toughness creatures, lethal marked damage,
        and the legend rule.
        """
        any_action = False
        while True:
            acted = self._sba_pass()
            if not acted:
                break
            any_action = True
        return any_action
    def _sba_pass(self) -> bool:
        """One RULE 704.3 sweep: each `_sba_check_*` below is one lettered
        RULE 704.5 sub-check (or an adjacent RULE 310 battle/RULE 714 Saga
        rule checked at the same cadence), tried in order and stopping at
        the first that acts — same order, same early-return-on-first-action
        shape the whole method always had, just named per check instead of
        one 236-line body, so each can be found/cited by its own RULE
        number and a debugger's stack trace names the actual failing check.
        """
        # A pending_choice (e.g. the RULE 903.9a commander-zone choice) pauses
        # SBA processing until it's answered — mirrors the guard
        # `resolve_until_stable`/`pass_priority` already apply after calling
        # `check_state_based_actions`.
        if self.state.pending_choice:
            return False

        # Re-derive continuous effects first (RULE 613) so P/T, types and
        # granted keywords are current before any SBA reads them — an anthem
        # dropping a creature to 0 toughness must be seen here.
        continuous.recompute(self.state)

        # 702.145c/d/f/g: not itself a state-based action, but "any time" is
        # otherwise unmodeled continuous timing — checked at SBA cadence.
        if self._check_day_night():
            return True

        # RULE 702.131b: Ascend on a permanent is "any time you control ten
        # or more permanents and you don't have the city's blessing, you get
        # it" — a live board check, not an event trigger, so it's swept here
        # rather than fired off any one zone change. (Ascend on a spell is a
        # one-shot resolution effect instead — `GetCityBlessingEffect`.)
        if self._sba_check_ascend():
            return True

        # RULE 702.195a: Storied is the same live-board-count shape as
        # Ascend just above, gated on a three-way type/subtype/supertype
        # OR instead of a flat permanent tally (PAR-51).
        if self._sba_check_storied():
            return True

        # PAR-28 / RULE 702.179a: Start Your Engines! is a state-based action
        # — a permanent's controller with no speed gets speed 1.
        if self._sba_check_start_your_engines():
            return True

        # RULE 702.94c: a Soulbond pair breaks the moment either creature
        # leaves the battlefield, stops being a creature, or the two stop
        # sharing a controller — swept here so none of those sites has to
        # remember to tear the pair down itself.
        if self.break_illegal_soulbond_pairs():
            return True

        # RULE 701.52d: likewise for the Ring-bearer designation — no
        # re-check needed afterwards, since dropping it can't itself change
        # anything else on the board.
        self._sweep_ring_bearer()

        if self._sba_check_player_loss():
            return True
        if self._sba_check_zero_toughness():
            return True
        if self._sba_check_zero_loyalty():
            return True
        if self._sba_check_siege_defeat():
            return True
        if self._sba_check_battle_zero_defense():
            return True
        if self._sba_check_battle_protector():
            return True
        if self._sba_check_saga_completion():
            return True
        if self._sba_check_lethal_damage():
            return True
        if self._sba_check_counter_annihilation():
            return True

        # 704.5m/n: a permanent still attached to a *legal* host when it was
        # attached can become illegally attached later — most commonly the
        # host gaining protection from the attachment's quality, but also a
        # changed control (equip/reconfigure/fortify's "you control") or a
        # quality no longer matching ("enchant creature" on a host that's
        # been turned into a noncreature). `_detach_attachments_from` only
        # fires when the *host* leaves the battlefield; this is the other
        # half, re-checked every SBA pass against the live board.
        if self._revalidate_attachments():
            return True

        # RULE 702.103f: a bestowed Aura that is no longer attached to a
        # creature ceases to be bestowed and becomes a creature again. The
        # un-attach paths (`_detach_attachments_from`/`_revalidate_
        # attachments`) already call `_end_bestow` themselves; this is the
        # catch-all at SBA cadence for any other route to "unattached".
        if self._sba_check_unbestow():
            return True

        # 704.5j: legend rule — same-named legendaries a player controls.
        if self._apply_legend_rule():
            return True

        if self._sba_check_commander_zone_choice():
            return True

        # 704.5d: a token in any zone other than the battlefield ceases to
        # exist. It *did* reach that zone (its owner's graveyard/exile/…) long
        # enough for its leaves-the-battlefield / dies triggers to have fired
        # when it was moved there — this SBA then removes it from the game, and
        # RULE 111.7-8 keep it from ever returning to another zone.
        if self._remove_stranded_tokens():
            return True

        return False

    def _sba_check_ascend(self) -> bool:
        """RULE 702.131b: a permanent with ascend grants its controller the
        city's blessing the moment they control ten or more permanents, if
        they don't already have it. Read straight off `intrinsic_keywords`/
        `granted_keywords` via `combat.has` — ascend carries no parameters,
        so there's nothing to bind beyond the flag keyword `attach_keyword`
        already docks (`effect_binder.attach_keyword`)."""
        for obj in self.state.permanents():
            if not combat.has(obj, "ascend"):
                continue
            controller = self.state.player_by_id(obj.controller_id)
            if controller is None or controller.has_city_blessing:
                continue
            if continuous.count_selector(self.state, controller.id, "permanents_you_control") >= 10:
                self.get_city_blessing(controller)
                return True
        return False

    def _sba_check_storied(self) -> bool:
        """RULE 702.195a: a permanent with storied grants its controller an
        enduring story designation the moment they control three or more
        permanents that are artifacts, Sagas, and/or legendary — the exact
        same shape as `_sba_check_ascend` above, just a three-way OR'd
        type/subtype/supertype count instead of a flat permanent tally.
        ``card.is_artifact``/the Saga subtype read the object's printed
        characteristics, the same simplification `continuous.py`'s other
        artifact/Saga tallies already make; ``is_legendary`` is the one
        derived property of the three, already covering a granted legendary
        (`GameObject._granted_legendary`)."""
        for obj in self.state.permanents():
            if not combat.has(obj, "storied"):
                continue
            controller = self.state.player_by_id(obj.controller_id)
            if controller is None or controller.has_enduring_story:
                continue
            count = sum(
                1
                for o in self.state.permanents()
                if o.controller_id == controller.id
                and (o.card.is_artifact or o.is_legendary or continuous.has_subtype(o, "Saga"))
            )
            if count >= 3:
                self.get_enduring_story(controller)
                return True
        return False

    def _sba_check_start_your_engines(self) -> bool:
        """PAR-28 / RULE 702.179a: "If a player controls a permanent with
        start your engines! and that player has no speed, their speed
        becomes 1. This is a state-based action." Read straight off
        `combat.has` like `_sba_check_ascend` above — a flag keyword."""
        for obj in self.state.permanents():
            if not combat.has(obj, "start_your_engines"):
                continue
            controller = self.state.player_by_id(obj.controller_id)
            if controller is None or int(getattr(controller, "speed", 0) or 0) != 0:
                continue
            self.start_engines(controller)
            return True
        return False

    def _sba_check_player_loss(self) -> bool:
        """704.5a/c: player at 0 or less life, drawing from empty, or 10+
        poison loses. 704.5m/903.10a: 21+ combat damage from a single
        commander also loses — checked in the same per-player pass since
        both read `_loss_prevented(player)` first."""
        for player in self.state.players:
            if player.has_lost:
                continue
            drew_empty = getattr(player, "attempted_draw_from_empty", False)
            # 704.5c: 0-or-less life, drawing from empty, or 10+ poison loses.
            poisoned = player.poison >= 10
            if (player.life <= 0 or drew_empty or poisoned) and not self._loss_prevented(player):
                if player.loss_reason:
                    reason = player.loss_reason
                elif player.life <= 0:
                    reason = "life"
                elif poisoned:
                    reason = "poison"
                else:
                    reason = "draw_from_empty"
                self._player_loses(player, reason)
                return True
            # 704.5m / 903.10a: 21+ combat damage from a single commander.
            if not self._loss_prevented(player) and any(
                entry["amount"] >= 21 for entry in player.commander_damage.values()
            ):
                self._player_loses(player, "commander_damage")
                return True
        return False

    def _sba_check_zero_toughness(self) -> bool:
        """704.5f: creature with toughness <= 0 goes to graveyard."""
        for obj in self.state.permanents():
            if obj.is_creature and obj.toughness is not None and obj.toughness <= 0:
                self._move_to_graveyard(obj)
                return True
        return False

    def _sba_check_zero_loyalty(self) -> bool:
        """704.5i: a planeswalker with 0 loyalty is put into its owner's
        graveyard. Only planeswalkers with a printed starting loyalty are
        subject to this (they always enter with loyalty counters)."""
        for obj in self.state.permanents():
            if obj.is_planeswalker and obj.card.loyalty is not None and obj.loyalty <= 0:
                self._move_to_graveyard(obj)
                return True
        return False

    def _sba_check_siege_defeat(self) -> bool:
        """RULE 310.11b: a Siege's intrinsic "when the last defense counter
        is removed from this permanent, exile it, then you may cast it
        transformed without paying its mana cost". A *triggered* ability,
        not an SBA — but noticing the transition is what an SBA pass is
        for, and doing it here (rather than in `deal_damage`) means every
        route to zero defense is covered, not just damage. Placed straight
        on the stack like `check_ward`/`check_rampage` rather than through
        the RULE 603.3 queue, since it's built per firing; the latch stops
        the next pass from re-firing it while it's still on the stack.
        """
        for obj in self.state.permanents():
            if (
                obj.card.is_siege
                and obj.card.defense
                and obj.defense <= 0
                and not obj.battle_defeat_triggered
            ):
                obj.battle_defeat_triggered = True
                self._place_trigger(
                    TriggeredAbility(
                        trigger_event=EventType.BATTLE_DEFEATED,
                        effects=[SiegeDefeatedEffect(source=obj)],
                        controller_id=obj.controller_id,
                        source=obj,
                        description=f"{obj.name}: besiegt — ins Exil, dann transformiert wirken",
                    )
                )
                # Announced *after* the trigger is placed so anything else
                # watching a battle's defeat sees a stack that already holds
                # the Siege's own ability, matching RULE 603.3's ordering.
                self.state.fire_event(
                    GameEvent(
                        EventType.BATTLE_DEFEATED,
                        instance_id=obj.instance_id,
                        controller_id=obj.controller_id,
                        object=obj.name,
                    )
                )
                return True
        return False

    def _sba_check_battle_zero_defense(self) -> bool:
        """RULE 310.7: a battle with 0 defense that isn't itself the source
        of an ability which has triggered but not yet left the stack is put
        into its owner's graveyard — the exact shape of the Saga check
        below, and the reason a defeated Siege survives long enough for its
        own 310.11b trigger (`_sba_check_siege_defeat`) to exile it instead.
        Only battles with a printed defense are subject (mirroring the
        loyalty check above: a battle that never had defense counters was
        never at "0 defense" in the 310.4c sense).
        """
        for obj in self.state.permanents():
            if not (obj.is_battle and obj.card.defense and obj.defense <= 0):
                continue
            if any(item.source is obj for item in self.state.stack):
                continue
            self._move_to_graveyard(obj)
            return True
        return False

    def _sba_check_battle_protector(self) -> bool:
        """RULE 310.10: a battle that isn't being attacked and has no valid
        protector gets a fresh one chosen by its controller; with no
        eligible player at all it's put into its owner's graveyard. For the
        only real battle type (Siege, 310.11a) "eligible" means an opponent
        of the controller, so this is what cleans up a Siege whose
        protector has left the game — and what makes a Siege cast in a solo
        goldfish (no opponents at all) fall off the battlefield rather than
        sit there unattackable forever.
        """
        for obj in self.state.permanents():
            if not obj.is_battle or self.battle_is_being_attacked(obj):
                continue
            eligible = self._eligible_protectors(obj)
            if obj.protector_id is not None and any(p.id == obj.protector_id for p in eligible):
                continue
            if not eligible:
                self._move_to_graveyard(obj)
                return True
            # A single eligible player is no choice at all (RULE 310.10's
            # "chooses" degenerates); with several, the same auto-pick this
            # engine already makes for a non-interactive pick applies, since
            # an SBA has no window to open a `pending_choice` in.
            obj.protector_id = eligible[0].id
            return True
        return False

    def _sba_check_saga_completion(self) -> bool:
        """704.5x/RULE 714.4: a Saga with lore counters >= its final chapter
        number, and not itself the source of one of its own chapter
        abilities that has triggered but not yet left the stack, is put
        into its owner's graveyard. Checked against *this Saga's own*
        chapter trigger specifically (its `StackItem.source`/
        `trigger_event`, stamped by `_place_trigger_on_stack`) rather than
        "is the whole stack empty" — an unrelated spell/ability sitting on
        the stack (an opponent's instant, another permanent's trigger)
        must not delay this Saga's own sacrifice.
        """
        for obj in self.state.permanents():
            if not obj.card.is_saga:
                continue
            final = _saga_final_chapter(obj.card)
            if final and obj.lore >= final and not any(
                item.source is obj
                and item.trigger_event is not None
                and item.trigger_event.type == EventType.SAGA_CHAPTER
                for item in self.state.stack
            ):
                self._move_to_graveyard(obj)
                return True
        return False

    def _sba_check_lethal_damage(self) -> bool:
        """704.5g: creature with lethal marked damage is destroyed — or one
        that was dealt any damage by a deathtouch source (RULE 702.2b makes
        that lethal). Indestructible (RULE 702.12b) is destroyed by
        neither. Routed through `destroy` (not a raw `_move_to_graveyard`)
        so a regeneration shield (RULE 701.16) gets a chance to intercept
        it — the classic regenerate-a-blocker use case.
        """
        for obj in self.state.permanents():
            if not obj.is_creature or obj.toughness is None:
                continue
            if combat.has_indestructible(obj):
                continue
            lethal_marked = obj.toughness > 0 and obj.damage_marked >= obj.toughness
            if lethal_marked or (obj.dealt_deathtouch_damage and obj.damage_marked > 0):
                self.destroy(obj)
                return True
        return False

    def _sba_check_counter_annihilation(self) -> bool:
        """704.5q: a permanent with both +1/+1 and -1/-1 counters removes an
        equal number of each. Done before the toughness/damage checks would
        normally settle, so a creature that nets out to 0 toughness after
        annihilation is then caught by 704.5f
        (`_sba_check_zero_toughness`) on the next pass.
        """
        for obj in self.state.permanents():
            plus = obj.counters.get("+1/+1", 0)
            minus = obj.counters.get("-1/-1", 0)
            if plus > 0 and minus > 0:
                removed = min(plus, minus)
                obj.add_counters("+1/+1", -removed)
                obj.add_counters("-1/-1", -removed)
                return True
        return False

    def _sba_check_unbestow(self) -> bool:
        """RULE 702.103f: a bestowed Aura not attached to a creature ceases
        to be bestowed — it stops being an Aura and is a creature again,
        remaining on the battlefield. `_end_bestow` clears the flag and the
        synthetic "enchant" keyword; the next `recompute` at the top of the
        following SBA pass then re-derives it as a creature.
        """
        for obj in self.state.permanents():
            if getattr(obj, "bestowed", False) and obj.attached_to is None:
                self._end_bestow(obj)
                return True
        return False

    def _sba_check_commander_zone_choice(self) -> bool:
        """903.9a: a commander freshly landed in a graveyard or exile may be
        moved to the command zone by its owner instead — a one-time SBA
        offer (`_flag_commander_zone_choice` marks eligibility at the
        moment it lands there; consumed and cleared here the instant it's
        offered, so it isn't re-asked on every subsequent SBA pass).
        """
        for player in self.state.players:
            for zone in (Zone.GRAVEYARD, Zone.EXILE):
                for obj in player.zones[zone]:
                    if obj.commander_zone_choice_pending:
                        obj.commander_zone_choice_pending = False
                        self.open_choice(self._commander_zone_choice(obj, zone))
                        return True
        return False
    def _remove_stranded_tokens(self) -> bool:
        """Remove any token that has left the battlefield (RULE 704.5d) —
        except a prepared copy still exempt under RULE 722.3c, a token
        with an open free-cast window (`GameState.free_cast_instance_ids`
        — Isochron Scepter's own imprinted-card copy, `CopyImprintedCard
        Effect`: a token placed straight into exile, never on the
        battlefield at all, that stays there only until it's either cast
        or its window closes at cleanup, at which point it's no longer in
        that set and this sweeps it on the very next pass), or a token
        deliberately conjured straight into a hand (`GameObject.
        conjured_into_hand`, RULE 707.9 — Spellchain Scatter's "conjure a
        duplicate … into your hand", PAR-124), which — unlike a `copy_spell`
        stack copy — is never meant to touch the battlefield at all before
        being cast or discarded."""
        for player in self.state.players:
            for zone in Player.PERSONAL_ZONES:  # every non-battlefield zone
                cards = player.zones[zone]
                for obj in cards:
                    if (
                        obj.is_token
                        and not self._is_prepared_copy(obj)
                        # Only exempt while it's still sitting in the hand it
                        # was conjured into — once cast (leaves this sweep's
                        # zones entirely) or discarded (moves to the
                        # graveyard), it's an ordinary stranded token again.
                        and not (zone == Zone.HAND and getattr(obj, "conjured_into_hand", False))
                        and obj.instance_id not in self.state.free_cast_instance_ids
                    ):
                        cards.remove(obj)
                        return True
        return False
    def _is_prepared_copy(self, obj: GameObject) -> bool:
        """RULE 722.3c: a prepared copy is exempt from the RULE 704.5d token
        cleanup for as long as its source stays on the battlefield with the
        prepared designation — the instant either stops being true (the
        source is unprepared some other way, or leaves the battlefield), the
        next SBA pass reaps the copy via `_remove_stranded_tokens` above.
        """
        if obj.prepared_source_id is None:
            return False
        source = self.state.find_object(obj.prepared_source_id)
        return source is not None and source in self.state.battlefield and source.prepared
    def _apply_legend_rule(self) -> bool:
        seen: dict[tuple[str, str], GameObject] = {}
        for obj in self.state.permanents():
            if not obj.is_legendary:
                continue
            controller = self.state.player_by_id(obj.controller_id)
            if controller is not None and continuous.player_ignores_legend_rule(self.state, controller):
                continue
            key = (obj.controller_id, obj.name)
            if key in seen:
                # Keep the first seen, put this duplicate in the graveyard.
                self._move_to_graveyard(obj)
                return True
            seen[key] = obj
        return False
    def _loss_prevented(self, player: Player) -> bool:
        return any(
            isinstance(e, WinConditionEffect) and e.prevents_loss()
            for e in player.player_effects
        )
    def _player_loses(self, player: Player, reason: str) -> None:
        """A player loses the game — RULE 104.2/104.3, however it happened
        (a state-based loss such as 0 life/poison/empty library, a
        concession, an opponent's alternative win condition, or a
        "target player loses the game" effect all funnel through here).

        The RULE 800.4a cleanup (their objects leave the game with them) is
        deliberately **deferred** rather than run inline, because a loss can
        fire mid-turn (a combat-damage SBA, a concession, a resolving spell)
        and pulling a whole board out from under the remaining players right
        then is disorienting: the id is parked on
        `GameState.pending_leave_ids` and swept by `GameEngine.begin_turn`
        when the next player's turn starts. Once only one living player is
        left the game is over anyway, so the board is simply left standing
        for the end-of-match review and the sweep never runs.
        """
        player.has_lost = True
        player.loss_reason = reason
        self.state.fire_event(
            GameEvent(EventType.PLAYER_LOST, player_id=player.id, reason=reason)
        )
        self._check_game_over()
        if not self.state.game_over and player.id not in self.state.pending_leave_ids:
            self.state.pending_leave_ids.append(player.id)
    def concede(self, player: Player) -> None:
        """RULE 104.3a: ``player`` concedes and leaves the game immediately.

        Conceding is the one thing a player may do at *any* time, without
        holding priority — it is not an action that uses the stack, so
        unlike every other action here it isn't gated on timing. The
        RULE 800.4a board cleanup this triggers is deferred by
        `_player_loses` itself; see its docstring.
        """
        if player.has_lost:
            return
        self._player_loses(player, "conceded")
    def remove_player_from_game(self, player: Player) -> None:
        """RULE 800.4a: every object a departing player owns leaves the game.

        Their permanents (and anything they control that they don't own —
        RULE 800.4a hands those back, but with no exchange-of-control
        modeled at this level the simple reading is used: only *owned*
        objects go) leave the battlefield, their personal zones empty, and
        anything of theirs still on the stack ceases to exist. Called by
        `GameEngine.begin_turn` for each id `_player_loses` parked on
        `GameState.pending_leave_ids`, not directly by the loss itself.

        RULE 725.4/726.4 (MEC-9): a departing Monarch/Initiative-holder
        designation passes to the active player rather than simply
        vanishing — checked here, the one place both this cleanup and the
        rules text key off "leaves the game". By the time this runs,
        `GameEngine.begin_turn` has already rotated `active_player_index`
        past every departing id (`GameState.next_active_index` skips
        `has_lost`), so `self.state.active_player` is already the correct
        recipient and is never the player leaving — the "active player is
        also leaving"/"no active player" fallback in both rules never
        actually triggers in this engine, but is honoured (designation
        simply cleared) rather than assumed away.
        """
        if self.state.monarch_id == player.id:
            active = self.state.active_player
            if active.id != player.id:
                self.become_monarch(active)
            else:
                self.state.monarch_id = None
        if self.state.initiative_id == player.id:
            active = self.state.active_player
            # RULE 726.4 says the active player *takes* the initiative — the
            # same verb 726.2's "whenever a player takes the initiative, that
            # player ventures into Undercity" trigger keys off, so this goes
            # through `take_initiative` (which fires `TOOK_INITIATIVE`)
            # rather than setting `initiative_id` directly.
            if active.id != player.id:
                self.take_initiative(active)
            else:
                self.state.initiative_id = None
        for obj in [o for o in self.state.battlefield if o.owner_id == player.id]:
            self.state.remove_from_battlefield(obj)
        self.state.stack = [
            item for item in self.state.stack if getattr(item.source, "owner_id", None) != player.id
        ]
        for zone in Player.PERSONAL_ZONES:
            player.zones[zone].clear()
    def player_wins(self, player: Player) -> None:
        """RULE 104.2: ``player`` wins the game outright (Jace, Wielder of
        Mysteries/Laboratory Maniac-shaped alternative win condition) —
        every other living player loses, the same "someone wins" case a
        solo/2-player match already reduces to via `_player_loses`. Fires
        no separate "won" event of its own today (no card needs one); the
        derived `GameState.game_over`/`winner_id` `_check_game_over` sets
        is the externally-visible signal, same as any other win/loss path.
        A solo (1-player) match has no "other player" to lose, so the
        win/game-over state is set directly instead.
        """
        for other in list(self.state.living_players()):
            if other is not player:
                self._player_loses(other, "opponent_won")
        if len(self.state.players) == 1:
            self.state.game_over = True
            self.state.winner_id = player.id
        else:
            self._check_game_over()
    def _check_game_over(self) -> None:
        living = self.state.living_players()
        if len(self.state.players) > 1 and len(living) <= 1:
            self.state.game_over = True
            self.state.winner_id = living[0].id if living else None
