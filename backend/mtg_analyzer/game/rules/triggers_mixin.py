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
    HauntLinkedDeathEffect,
    ImpulsiveDrawEffect,
    IncreaseSpeedEffect,
    MarchesaDelayedReturnEffect,
    ProliferateEffect,
    PumpEffect,
    RadiationMillEffect,
    ReboundFreeCastWindowEffect,
    ReplacementEffect,
    ReturnFromGraveyardEffect,
    ReturnSelfFromGraveyardEffect,
    SiegeDefeatedEffect,
    StaticAbility,
    StaticEffect,
    SuspendUpkeepEffect,
    TakeInitiativeEffect,
    TriggeredAbility,
    UndyingPersistReturnEffect,
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


def _has_suspend(obj: GameObject) -> bool:
    """RULE 702.62: whether ``obj`` carries Suspend, printed or granted
    (Delay's "if it doesn't have suspend, it gains suspend" —
    `GameObject.granted_suspend`). Shared by `_collect_suspend_triggers`
    below so either source is treated identically."""
    if getattr(obj, "granted_suspend", False):
        return True
    return bool((getattr(obj, "parametric_keywords", None) or {}).get("suspend"))


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




class TriggerCollectionMixin:
    """Trigger collection (per-firing built and inherent) and placement/ordering/mode/target interactive choices (RULE 603)."""

    def _collect_triggers(self, event: GameEvent) -> None:
        if continuous.trigger_suppressed(self.state, event):
            # RULE 603: "Creatures entering don't cause abilities to
            # trigger." (Tocatli Honor Guard/Hushwing Gryff/Torpor Orb) —
            # silences every triggered ability that would otherwise fire off
            # this event, including the entering creature's own, for as long
            # as the static is in play.
            return
        for obj in self.state.permanents():
            # RULE 613.7f: a permanent stripped of all abilities (Humility,
            # Dress Down) has no triggered abilities to fire — not even a
            # layer-6-granted one, which is itself an ability it no longer has.
            if getattr(obj, "loses_all_abilities", False):
                continue
            # Elesh Norn, Mother of Machines (MEC-40) — the opponent-scoped
            # sibling of the global check above, decided per candidate
            # object since it depends on *whose* ability would fire.
            if continuous.trigger_suppressed_for(self.state, event, obj.controller_id):
                continue
            # `granted_triggered_abilities` (RULE 613.7f — a layer-6 "X have
            # '<triggered ability>'" static grant, e.g. Dionus, Elvish
            # Archdruid) sits alongside the object's own intrinsic abilities;
            # both fire through the same check/place pipeline.
            for ability in obj.triggered_abilities + obj.granted_triggered_abilities:
                if isinstance(ability, TriggeredAbility) and ability.check_trigger(
                    event, self.context
                ):
                    if ability.mana_ability:
                        # RULE 605.4: a *triggered mana ability* never uses
                        # the stack — it resolves right here, so its mana is
                        # in the pool in time for the payment that triggered
                        # it (Wild Growth, Kinnan). Queueing it would make
                        # the extra mana arrive a full stack resolution too
                        # late to spend, which is the entire point of both.
                        self._resolve_mana_trigger(ability, event)
                        continue
                    # RULE 603.3d: Roaming Throne-shaped "if a triggered
                    # ability of another creature you control of the chosen
                    # type triggers, it triggers an additional time" —
                    # placed as extra, independent copies rather than a
                    # multiplier baked into the ability itself, since each
                    # copy is separately orderable/targetable (RULE 603.3b)
                    # once 2+ end up pending together.
                    copies = 1 + continuous.trigger_doubler_bonus(self.state, obj, event=event)
                    for _ in range(copies):
                        self.pending_triggers.append((ability, event))
        # RULE 114.4: an emblem's abilities function in the command zone —
        # scanned the same way as a permanent's, just off `Player.emblems`
        # instead of the battlefield (see `models/emblem.py`).
        for player in self.state.players:
            for emblem in player.emblems:
                for ability in emblem.triggered_abilities:
                    if ability.check_trigger(event, self.context):
                        self.pending_triggers.append((ability, event))
        # RULE 901.7/902.4/904.9: likewise for the casual variants' own
        # command-zone cards — the face-up plane's planeswalk/chaos
        # abilities, a scheme's "when you set this scheme in motion", a
        # Vanguard avatar's own triggers.
        for source in variants.command_zone_ability_sources(self.state):
            for ability in getattr(source, "triggered_abilities", []):
                if isinstance(ability, TriggeredAbility) and ability.check_trigger(
                    event, self.context
                ):
                    self.pending_triggers.append((ability, event))
        self._collect_inherent_triggers(event)
        self._collect_self_cast_triggers(event)
        self._collect_impulsive_draw_triggers(event)
        self._collect_rad_counter_damage_triggers(event)
        self._collect_attacks_you_rad_counter_triggers(event)
        self._collect_temporary_player_triggers(event)
        self._advance_turn_controls(event)
        self._collect_counter_death_return_triggers(event)
        self._collect_undying_persist_triggers(event)
        self._collect_mill_return_from_graveyard_triggers(event)
        self._collect_graveyard_function_triggers(event)
        self._collect_cycled_triggers(event)
        self._collect_suspend_triggers(event)
    def _resolve_mana_trigger(self, ability: "TriggeredAbility", event: GameEvent) -> None:
        """Apply a triggered mana ability immediately (RULE 605.4).

        The stack-free counterpart of `_place_trigger`: no `StackItem`, no
        priority window, no targets (RULE 605.1a forbids a mana ability from
        targeting at all, so there is nothing to choose). The firing event is
        exposed as `GameContext.trigger_event` for the duration, exactly as a
        stack resolution would — Kinnan's "one mana of any type **that
        permanent** produced" and Wild Growth's "**its** controller" both
        read it — and restored afterward, since this can run inside another
        resolution.
        """
        outer = self.context.trigger_event
        self.context.trigger_event = event
        try:
            ability.apply(self.context)
        finally:
            self.context.trigger_event = outer
    def _collect_inherent_triggers(self, event: GameEvent) -> None:
        """RULE 725.2/726.2/728.1: the Monarch's, the Initiative's, and rad
        counters' triggered abilities "have no source" — they aren't
        attached to any permanent, so the object scan above can never find
        them. Built fresh here instead, each time a matching event fires:
        for monarch/initiative, since who currently holds either
        designation (and so who controls the ability) can change turn to
        turn; RULE 726.2's "venture into the dungeon" trigger isn't modeled
        (dungeons/RULE 309 aren't built yet — see `TakeInitiativeEffect`'s
        docstring). Rad counters differ in that the ability is always
        controlled by the active player rather than following a
        designation, so no lookup is needed beyond `state.active_player`.
        """
        monarch = self.state.player_by_id(self.state.monarch_id) if self.state.monarch_id else None
        if monarch is not None and not monarch.has_lost:
            # "At the beginning of the monarch's end step, that player draws
            # a card."
            if (
                event.type == EventType.STEP_BEGIN
                and event.get("step") == "end"
                and self.state.active_player.id == monarch.id
            ):
                ability = TriggeredAbility(
                    trigger_event=EventType.STEP_BEGIN,
                    effects=[DrawCardEffect(count=1, player=monarch)],
                    controller_id=monarch.id,
                    description="The monarch draws a card.",
                )
                self.pending_triggers.append((ability, event))
            # "Whenever a creature deals combat damage to the monarch, its
            # controller becomes the monarch."
            if (
                event.type == EventType.DAMAGE
                and event.get("combat")
                and event.get("is_player")
                and event.get("target_id") == monarch.id
            ):
                new_monarch_id = event.get("source_controller_id")
                if new_monarch_id and new_monarch_id != monarch.id:
                    ability = TriggeredAbility(
                        trigger_event=EventType.DAMAGE,
                        effects=[BecomeMonarchEffect(player=self.state.player_by_id(new_monarch_id))],
                        controller_id=new_monarch_id,
                        description="Whenever a creature deals combat damage to the monarch, its controller becomes the monarch.",
                    )
                    self.pending_triggers.append((ability, event))
        initiative = (
            self.state.player_by_id(self.state.initiative_id) if self.state.initiative_id else None
        )
        if initiative is not None and not initiative.has_lost:
            # RULE 726.2: "At the beginning of the upkeep of the player who
            # has the initiative, that player ventures into Undercity." —
            # RULE 701.49d's named variant, never a free choice of dungeon.
            if (
                event.type == EventType.STEP_BEGIN
                and event.get("step") == "upkeep"
                and self.state.active_player.id == initiative.id
            ):
                ability = TriggeredAbility(
                    trigger_event=EventType.STEP_BEGIN,
                    effects=[
                        VentureIntoTheDungeonEffect(
                            dungeon=dungeons.UNDERCITY, player=initiative
                        )
                    ],
                    controller_id=initiative.id,
                    description=(
                        "At the beginning of the upkeep of the player who has the "
                        "initiative, that player ventures into Undercity."
                    ),
                )
                self.pending_triggers.append((ability, event))
            # "Whenever one or more creatures a player controls deal combat
            # damage to the player who has the initiative, the controller of
            # those creatures takes the initiative." Simplified to one
            # trigger per damage event rather than batching every attacker
            # a single player controls into one firing — RULE 726.2's own
            # wording ("one or more creatures") makes that batching a
            # presentation detail, not a rules difference: either way only
            # one designation change results.
            if (
                event.type == EventType.DAMAGE
                and event.get("combat")
                and event.get("is_player")
                and event.get("target_id") == initiative.id
            ):
                new_holder_id = event.get("source_controller_id")
                if new_holder_id and new_holder_id != initiative.id:
                    ability = TriggeredAbility(
                        trigger_event=EventType.DAMAGE,
                        effects=[TakeInitiativeEffect(player=self.state.player_by_id(new_holder_id))],
                        controller_id=new_holder_id,
                        description=(
                            "Whenever one or more creatures a player controls deal combat "
                            "damage to the player who has the initiative, the controller of "
                            "those creatures takes the initiative."
                        ),
                    )
                    self.pending_triggers.append((ability, event))
        # RULE 728.1: "At the beginning of each player's precombat main
        # phase, if that player has one or more rad counters, that player
        # mills..." — "each player's precombat main phase" just means
        # whichever player's turn this is (there's exactly one precombat
        # main per turn, always the active player's, `game/phases.py`), not
        # an APNAP loop over every player. Controlled by the active player
        # (an explicit exception to RULE 113.8, unlike monarch/initiative
        # which follow whoever currently holds the designation).
        if event.type == EventType.STEP_BEGIN and event.get("step") == "main1":
            active = self.state.active_player
            if not active.has_lost and active.counters.get("rad", 0) > 0:
                ability = TriggeredAbility(
                    trigger_event=EventType.STEP_BEGIN,
                    effects=[RadiationMillEffect(player=active)],
                    controller_id=active.id,
                    description=(
                        "At the beginning of each player's precombat main phase, if that "
                        "player has one or more rad counters, that player mills a number of "
                        "cards equal to the number of rad counters they have. For each "
                        "nonland card milled this way, that player loses 1 life and removes "
                        "one rad counter from themselves."
                    ),
                )
                self.pending_triggers.append((ability, event))

        # RULE 726.2's third inherent ability: "Whenever a player takes the
        # initiative, that player ventures into Undercity." Keyed off the
        # `TOOK_INITIATIVE` event rather than the designation itself, so RULE
        # 726.5's re-take (same player, no new designation) still ventures.
        if event.type == EventType.TOOK_INITIATIVE:
            taker = self.state.player_by_id(event.get("player_id"))
            if taker is not None and not taker.has_lost:
                ability = TriggeredAbility(
                    trigger_event=EventType.TOOK_INITIATIVE,
                    effects=[
                        VentureIntoTheDungeonEffect(dungeon=dungeons.UNDERCITY, player=taker)
                    ],
                    controller_id=taker.id,
                    description=(
                        "Whenever a player takes the initiative, that player "
                        "ventures into Undercity."
                    ),
                )
                self.pending_triggers.append((ability, event))

        # PAR-28 / RULE 702.179d: the sourceless inherent ability every
        # player with 1+ speed has — "Whenever one or more opponents lose
        # life during your turn, if your speed is less than 4, your speed
        # increases by 1. This ability triggers only once each turn."
        # Controlled by the active player, following whoever's turn it is
        # (like the rad-counter ability above, not a designation).
        if event.type == EventType.LIFE_LOST:
            active = self.state.active_player
            loser_id = event.get("player_id")
            if (
                not active.has_lost
                and 1 <= int(getattr(active, "speed", 0) or 0) < 4
                and not active.speed_increased_this_turn
                and loser_id is not None
                and loser_id != active.id
                and self.state.player_by_id(loser_id) is not None
            ):
                active.speed_increased_this_turn = True
                ability = TriggeredAbility(
                    trigger_event=EventType.LIFE_LOST,
                    effects=[IncreaseSpeedEffect(player=active, amount=1)],
                    controller_id=active.id,
                    description=(
                        "Whenever one or more opponents lose life during your turn, if "
                        "your speed is less than 4, your speed increases by 1. This "
                        "ability triggers only once each turn."
                    ),
                )
                self.pending_triggers.append((ability, event))

        # RULE 309.4c: a room ability of a dungeon in someone's command zone.
        self._collect_dungeon_room_triggers(event)

        self._collect_ring_triggers(event)
    def _collect_ring_triggers(self, event: GameEvent) -> None:
        """RULE 701.51a: the Ring emblem's abilities 2–4, which trigger.

        Source-less like the monarch's and the initiative's above — the Ring
        emblem isn't a permanent, and (unlike a RULE 114 emblem) has no
        quoted card text to bind, so there is nothing for the per-permanent
        trigger scan to find. Built fresh here off live state instead, which
        also means each one automatically follows the *current* Ring-bearer
        rather than whichever creature was bearer when the ability was
        gained. Ability 1 is a static and lives in `game/continuous.py`
        (legendary) and `GameEngine.can_block` (the blocking restriction).
        """
        for player in self.state.players:
            level = int(getattr(player, "ring_level", 0) or 0)
            if level < 2 or player.has_lost:
                continue
            bearer = continuous.ring_bearer_of(self.state, player)
            if bearer is None:
                continue

            # 2: "Whenever your Ring-bearer attacks, draw a card, then
            # discard a card."
            if (
                event.type == EventType.ATTACKS
                and event.get("instance_id") == bearer.instance_id
            ):
                self.pending_triggers.append((
                    TriggeredAbility(
                        trigger_event=EventType.ATTACKS,
                        effects=[
                            DrawCardEffect(count=1, player=player),
                            DiscardEffect(count=1, player=player),
                        ],
                        controller_id=player.id,
                        description="Whenever your Ring-bearer attacks, draw a card, then discard a card.",
                    ),
                    event,
                ))

            # 3: "Whenever your Ring-bearer becomes blocked by a creature,
            # that creature's controller sacrifices it at end of combat."
            # BECOMES_BLOCKED fires once per attacker rather than once per
            # blocker (RULE 509.5), and every blocker is already assigned by
            # then, so one trigger carrying the whole set is equivalent to
            # the per-blocker firings the rules describe — the same batching
            # `_collect_inherent_triggers` justifies for the initiative.
            if (
                level >= 3
                and event.type == EventType.BECOMES_BLOCKED
                and event.get("instance_id") == bearer.instance_id
            ):
                blockers = [
                    obj for obj in self.state.battlefield
                    if obj.instance_id in bearer.blocked_by
                ]
                if blockers:
                    self.pending_triggers.append((
                        TriggeredAbility(
                            trigger_event=EventType.BECOMES_BLOCKED,
                            effects=[
                                SacrificeSpecificEffect(blockers, delay_step="end_combat")
                            ],
                            controller_id=player.id,
                            description=(
                                "Whenever your Ring-bearer becomes blocked by a creature, "
                                "that creature's controller sacrifices it at end of combat."
                            ),
                        ),
                        event,
                    ))

            # 4: "Whenever your Ring-bearer deals combat damage to a player,
            # each opponent loses 3 life."
            if (
                level >= 4
                and event.type == EventType.DAMAGE
                and event.get("combat")
                and event.get("is_player")
                and event.get("source_id") == bearer.instance_id
            ):
                self.pending_triggers.append((
                    TriggeredAbility(
                        trigger_event=EventType.DAMAGE,
                        # ``each_opponent`` is relative to the effect's own
                        # source's controller, so the Ring-bearer stands in
                        # as source — "your" opponents are exactly its
                        # controller's, which is what the emblem means.
                        effects=[
                            LoseLifeEffect(amount=3, selector="each_opponent", source=bearer)
                        ],
                        controller_id=player.id,
                        description=(
                            "Whenever your Ring-bearer deals combat damage to a player, "
                            "each opponent loses 3 life."
                        ),
                    ),
                    event,
                ))
    def _collect_combat_damage_marker_trigger(
        self,
        event: GameEvent,
        marker_attr: str,
        build_effect: Callable[[dict, "GameObject", "Player", "Player"], GameEffect],
        description: Callable[["GameObject"], str],
    ) -> None:
        """Shared "whenever ~ deals combat damage to a player, `<per-firing
        effect>`" scaffold: the damaged player (and, per-marker, the amount)
        varies per firing, which a bind-on-load `TriggeredAbility`'s one
        fixed ``effects`` list can't carry (see that class's docstring,
        `game/effects.py`) — so this is built fresh right here, the same
        "per-firing data baked in right when the event fires" shape
        `_collect_inherent_triggers` above uses for the Monarch/Initiative
        combat-damage swap, queued through the ordinary ``pending_triggers``
        pipeline (RULE 603.3 ordering/choices) rather than `check_rampage`/
        `check_ward`'s "place immediately" shortcut, since this *is* a
        genuine source-bound triggered ability, just one no object scan
        could ever find pre-built. ``build_effect``/``description`` are the
        only per-marker-family pieces (`_collect_impulsive_draw_triggers`/
        `_collect_rad_counter_damage_triggers`); everything else — the
        combat-damage-to-a-player guard, the source/marker/player lookups —
        is identical between them.
        """
        if event.type != EventType.DAMAGE or not event.get("combat") or not event.get("is_player"):
            return
        source_id = event.get("source_id")
        if source_id is None:
            return
        source = self.state.find_object(source_id)
        if source is None:
            return
        marker = getattr(source, marker_attr, None)
        if not marker:
            return
        try:
            damaged_player = self.state.player_by_id(event["target_id"])
            controller = self.state.player_by_id(source.controller_id)
        except KeyError:
            return
        effect = build_effect(marker, source, damaged_player, controller)
        ability = TriggeredAbility(
            trigger_event=EventType.DAMAGE,
            effects=[effect],
            controller_id=controller.id,
            source=source,
            description=description(source),
        )
        self.pending_triggers.append((ability, event))
    def _collect_impulsive_draw_triggers(self, event: GameEvent) -> None:
        """"Whenever ~ deals combat damage to a player, exile the top card of
        *that player's* library. Until end of turn, you may cast that card."
        (Ragavan, Nimble Pilferer, `AbilitySpec.impulsive_draw_on_combat_
        damage`). See `_collect_combat_damage_marker_trigger` for the shared
        scaffold this and `_collect_rad_counter_damage_triggers` both ride.
        """
        def build_effect(
            marker: dict, source: "GameObject", damaged_player: "Player", controller: "Player"
        ) -> GameEffect:
            return ImpulsiveDrawEffect(
                count=int(marker.get("count", 1)),
                player=damaged_player,
                permission_player=controller,
                same_turn_only=True,
                source=source,
            )

        self._collect_combat_damage_marker_trigger(
            event,
            "impulsive_draw_on_combat_damage",
            build_effect,
            lambda source: f"{source.name}: verbanne die oberste Karte der gegnerischen Bibliothek",
        )
    def _collect_rad_counter_damage_triggers(self, event: GameEvent) -> None:
        """"Whenever ~ deals combat damage to a player, they get N rad
        counters." (Glowing One)/"...that many rad counters." (Infesting
        Radroach, `AbilitySpec.rad_counters_on_combat_damage`). See
        `_collect_combat_damage_marker_trigger` for the shared scaffold this
        and `_collect_impulsive_draw_triggers` both ride.

        ``marker["else"] == "proliferate"`` (Vexing Radgull: "...if they
        don't have any rad counters. Otherwise, proliferate.") branches on
        whether the damaged player currently has any of the granted
        ``kind`` — checked live against the *pre-damage* count (this fires
        off the same `DAMAGE` event `add_player_counters` would use, before
        this ability's own grant), so "don't have any yet" reads correctly
        even on the very first hit.
        """
        def build_effect(
            marker: dict, source: "GameObject", damaged_player: "Player", controller: "Player"
        ) -> GameEffect:
            count = marker.get("count", 1)
            amount = int(event.get("amount", 0)) if count == "damage_amount" else int(count)
            kind = marker.get("kind", "rad")
            if marker.get("else") == "proliferate" and damaged_player.counters.get(kind, 0) > 0:
                return ProliferateEffect(source=source)
            return AddPlayerCountersEffect(amount=amount, kind=kind, player=damaged_player, source=source)

        self._collect_combat_damage_marker_trigger(
            event,
            "rad_counters_on_combat_damage",
            build_effect,
            lambda source: f"{source.name}: gib der geschädigten Spielerin/dem geschädigten Spieler Rad-Marken",
        )
    def _collect_attacks_you_rad_counter_triggers(self, event: GameEvent) -> None:
        """"Whenever a player attacks you with one or more creatures, that
        player gets twice that many rad counters." (Struggle for Project
        Purity's Enclave mode, `AbilitySpec.rad_counters_on_attacked`) —
        the attacking player and the amount (tied to `EventType.
        PLAYER_ATTACKED`'s own ``count``) vary per firing, the same
        "build fresh right here" shape every other rad-counter marker
        collector uses; scans every permanent for the marker rather than
        reading it off the event's own subject, since the event is about a
        *player* attacking, not this ability's source
        (`_collect_counter_death_return_triggers`'s same "scan every
        permanent" style, for the same reason).
        """
        if event.type != EventType.PLAYER_ATTACKED:
            return
        defending_player_id = event.get("defending_player_id")
        attacking_player_id = event.get("attacking_player_id")
        if defending_player_id is None or attacking_player_id is None:
            return
        for obj in self.state.permanents():
            marker = getattr(obj, "rad_counters_on_attacked", None)
            if not marker:
                continue
            if obj.controller_id != defending_player_id:
                continue
            requires_mode = marker.get("requires_mode")
            if requires_mode and getattr(obj, "chosen_mode", None) != requires_mode:
                continue
            try:
                attacker = self.state.player_by_id(attacking_player_id)
            except KeyError:
                continue
            amount = int(marker.get("multiplier", 1)) * int(event.get("count", 0))
            effect = AddPlayerCountersEffect(amount=amount, kind="rad", player=attacker, source=obj)
            ability = TriggeredAbility(
                trigger_event=EventType.PLAYER_ATTACKED,
                effects=[effect],
                controller_id=obj.controller_id,
                source=obj,
                description=f"{obj.name}: gib der angreifenden Spielerin/dem angreifenden Spieler Rad-Marken",
            )
            self.pending_triggers.append((ability, event))
    def _collect_temporary_player_triggers(self, event: GameEvent) -> None:
        """Re-fire and expire `GameState.temporary_player_triggers` (Nuka-
        Nuke Launcher's "until the end of defending player's next turn,
        that player gets rad counters whenever they cast a spell") — see
        `TemporaryPlayerTrigger`'s own docstring for the phase state
        machine this drives off `EventType.TURN_BEGIN`.
        """
        if not self.state.temporary_player_triggers:
            return
        remaining = []
        for trig in self.state.temporary_player_triggers:
            if trig.phase == "waiting":
                if (
                    event.type == EventType.TURN_BEGIN
                    and event.get("player_id") == trig.player_id
                    and int(event.get("turn", 0)) > trig.install_turn
                ):
                    trig.phase = "active"
                    trig.active_since_turn = int(event.get("turn", 0))
                remaining.append(trig)
                continue
            # phase == "active": the *next* TURN_BEGIN (anyone's) after their
            # own turn started means their turn just ended — drop it. For a
            # ``"this_turn"`` trigger (armed active immediately, `active_
            # since_turn` == install turn), that same check is exactly
            # "until end of this turn".
            if (
                event.type == EventType.TURN_BEGIN
                and trig.active_since_turn is not None
                and int(event.get("turn", 0)) > trig.active_since_turn
            ):
                continue
            # RULE 603.1: ``"self"`` scope fires only when the event names
            # this player; ``"any"`` fires on every matching event_type
            # (Ruinous Waterbending's "whenever **a** creature dies").
            _player_ok = (
                trig.event_player_scope == "any"
                or event.get("player_id") == trig.player_id
            )
            if event.type == trig.event_type and _player_ok:
                ability = TriggeredAbility(
                    trigger_event=trig.event_type,
                    effects=trig.effects,
                    controller_id=trig.player_id,
                    description=trig.description,
                )
                self.pending_triggers.append((ability, event))
            remaining.append(trig)
        self.state.temporary_player_triggers = remaining
    def _advance_turn_controls(self, event: GameEvent) -> None:
        """MEC-51 (RULE 720): run the `TURN_BEGIN` state machine for
        `GameState.turn_controls` — the twin of
        `_collect_temporary_player_triggers`' own phase machine.

        * ``"waiting"`` → ``"active"`` when the controlled player's own next
          turn begins (strictly *after* the turn the control was installed
          on — RULE 720.6: a control taken during that player's turn waits
          for their following one).
        * ``"active"`` entry dropped at the next `TURN_BEGIN` after
          ``active_since_turn`` — "the end of that player's turn".
        """
        controls = self.state.turn_controls
        if not controls:
            return
        if event.type == EventType.TURN_END:
            # Emrakul, the Promised End: "After that turn, that player takes
            # an extra turn." Queue it as the controlled turn *ends*, so it
            # is taken at the very next `begin_turn` (RULE 500.7) — right
            # after the controlled turn, before the normal rotation.
            ended_id = event.get("player_id")
            for tc in controls:
                if (
                    tc.phase == "active"
                    and tc.controlled_id == ended_id
                    and getattr(tc, "grant_extra_turn_after", False)
                    and tc.controlled_id not in self.state.extra_turns
                ):
                    self.state.extra_turns.append(tc.controlled_id)
            return
        if event.type != EventType.TURN_BEGIN:
            return
        turn = int(event.get("turn", 0))
        begun_id = event.get("player_id")
        remaining: list = []
        for tc in controls:
            if tc.phase == "waiting":
                if begun_id == tc.controlled_id and turn > tc.install_turn:
                    tc.phase = "active"
                    tc.active_since_turn = turn
                remaining.append(tc)
                continue
            # phase == "active": expire once a later turn than the one it
            # became active on has begun.
            if tc.active_since_turn is not None and turn > tc.active_since_turn:
                continue
            remaining.append(tc)
        if len(remaining) != len(controls):
            self.state.turn_controls = remaining

    def _collect_counter_death_return_triggers(self, event: GameEvent) -> None:
        """"Whenever a creature you control with a counter of
        ``counter_kind`` on it dies, return that card to the battlefield
        under your control at the beginning of the next end step."
        (Marchesa, the Black Rose, `AbilitySpec.counter_death_return`) — the
        dying creature varies per firing, so this is built fresh here
        exactly like `_collect_impulsive_draw_triggers` above, just scanning
        every permanent for the marker instead of reading it off the
        event's own source (Marchesa isn't the object the `DIES` event is
        about — RULE 603.1's "group" subject shape, not "self").
        """
        if event.type != EventType.DIES:
            return
        if "creature" not in (event.get("object_types") or []):
            return
        dying_controller_id = event.get("controller_id")
        dying_id = event.get("instance_id")
        if dying_controller_id is None or dying_id is None:
            return
        dying_counters = event.get("counters") or {}
        for obj in self.state.permanents():
            marker = getattr(obj, "counter_death_return", None)
            if not marker:
                continue
            # Marchesa scope: the dying creature is one *this* permanent's
            # controller owns. ``opponent`` flips it (Necroskitter / The
            # Reaper, King No More — "a creature an opponent controls …").
            if marker.get("opponent"):
                if dying_controller_id == obj.controller_id:
                    continue
            elif obj.controller_id != dying_controller_id:
                continue
            kind = marker.get("counter_kind", "+1/+1")
            if dying_counters.get(kind, 0) <= 0:
                continue
            # RULE 603.2 per-instance "do this only once each turn" (Reaper).
            if marker.get("once_per_turn") and getattr(obj, "_counter_death_return_turn", None) == self.state.turn_nr:
                continue
            dying_obj = self.state.find_object(dying_id)
            if dying_obj is None:
                continue
            if marker.get("once_per_turn"):
                obj._counter_death_return_turn = self.state.turn_nr
            if marker.get("immediate"):
                # "return/put that card to the battlefield under your
                # control" with no "next end step" delay — resolve now.
                effect: GameEffect = ReturnFromGraveyardEffect(
                    target=dying_obj, destination="battlefield",
                    under_your_control=True, optional=bool(marker.get("optional")),
                    source=obj,
                )
                desc = f"{obj.name}: {dying_obj.name} unter deine Kontrolle zurückbringen"
            else:
                effect = MarchesaDelayedReturnEffect(dying_object=dying_obj, source=obj)
                desc = f"{obj.name}: {dying_obj.name} zum Ende des Zuges zurückbringen"
            ability = TriggeredAbility(
                trigger_event=EventType.DIES,
                effects=[effect],
                controller_id=obj.controller_id,
                source=obj,
                optional=bool(marker.get("optional")),
                description=desc,
            )
            self.pending_triggers.append((ability, event))
    def _collect_undying_persist_triggers(self, event: GameEvent) -> None:
        """RULE 702.93 Undying / 702.79 Persist — "When this creature dies,
        if it had no ``<kind>`` counters on it, return it to the battlefield
        under its owner's control with a ``<kind>`` counter on it" (undying →
        ``+1/+1``, persist → ``-1/-1``).

        Collected here off the `combat._obj_keywords` union rather than
        synthesized at bind time in `effect_binder._KEYWORD_TRIGGERED_
        BUILDERS`, specifically so a *granted* undying/persist works too
        (Mikaeus, the Unhallowed; the hand-authored undying grant in
        `ability_catalogue/entries_003.py`) — the ticket's own headline gap
        was that a granted "undying" did nothing, since a layer-6 grant
        lands in `granted_keywords`, never on the keyword-spec list the bind
        pass reads. A `loses_all_abilities` creature reports no keywords at
        all (`_obj_keywords`), so it correctly loses undying/persist too.

        Self-scoped: fired for the dying object's own keyword, at DIES time
        while it is still findable (RULE 603.6a look-back). The RULE 702.93a/
        702.79a "had no such counter" guard reads the pre-death snapshot off
        the event (``counters``) — the same RULE 603.10 last-known-
        information read `_collect_counter_death_return_triggers` uses.
        """
        if event.type != EventType.DIES:
            return
        if "creature" not in (event.get("object_types") or []):
            return
        dying_id = event.get("instance_id")
        dying_obj = self.state.find_object(dying_id) if dying_id is not None else None
        if dying_obj is None:
            return
        dying_counters = event.get("counters") or {}
        for keyword, counter_kind in (("undying", "+1/+1"), ("persist", "-1/-1")):
            if not combat.has(dying_obj, keyword):
                continue
            if dying_counters.get(counter_kind, 0) > 0:
                continue
            ability = TriggeredAbility(
                trigger_event=EventType.DIES,
                effects=[UndyingPersistReturnEffect(counter_kind=counter_kind, source=dying_obj)],
                controller_id=dying_obj.owner_id,
                source=dying_obj,
                description=f"{dying_obj.name}: {keyword}",
            )
            self.pending_triggers.append((ability, event))
    def _collect_mill_return_from_graveyard_triggers(self, event: GameEvent) -> None:
        """"Whenever an opponent mills a nonland card, if this creature is
        in your graveyard, you may return it to your hand." (RULE 112.6a,
        Infesting Radroach, `AbilitySpec.mill_return_from_graveyard`) — a
        triggered ability that must keep firing while its own source sits
        in a *graveyard*, not the battlefield, so it can't ride the
        ordinary `obj.triggered_abilities` scan (`_collect_triggers` only
        walks `state.permanents()`); scanned here instead, exactly like
        `_collect_counter_death_return_triggers`'s own "per-firing marker"
        style, just over every player's graveyard rather than the
        battlefield. `_collect_graveyard_function_triggers` right below is
        this same idea's general form (PAR-16) — this one predates it and
        is kept as its own bespoke, per-firing-marker method rather than
        folded in, since it's keyed off a fresh `ReturnSelfFromGraveyardEffect`
        built new every MILL_CARD event rather than an ordinary bound
        `TriggeredAbility` already sitting on the object.

        "You"/"your" (RULE 108.4: a graveyard card has no controller, only
        an owner) is that graveyard's own player — so a player's *own* mill
        never triggers their own graveyard-sitting Radroach; only somebody
        else's does, matched by skipping the milling player's own graveyard
        entirely below rather than by the usual group-subject "not_you"
        binder machinery (this ability never goes through that pipeline at
        all — it's built fresh per firing, like every other rad-counter
        marker in this file).
        """
        if event.type != EventType.MILL_CARD:
            return
        milling_player_id = event.get("player_id")
        if milling_player_id is None:
            return
        for player in self.state.players:
            if player.id == milling_player_id:
                continue
            for obj in player.graveyard:
                if not getattr(obj, "mill_return_from_graveyard", False):
                    continue
                effect = ReturnSelfFromGraveyardEffect(obj=obj, destination="hand", source=obj)
                ability = TriggeredAbility(
                    trigger_event=EventType.MILL_CARD,
                    effects=[effect],
                    optional=True,
                    controller_id=player.id,
                    source=obj,
                    description=f"{obj.name}: zurück auf die Hand nehmen",
                )
                self.pending_triggers.append((ability, event))
    def _collect_graveyard_function_triggers(self, event: GameEvent) -> None:
        """RULE 113.6a (PAR-16): a triggered ability whose own effect body
        explicitly returns its source "from your graveyard" (`TriggeredAbility.
        functions_from_graveyard`, inferred by `effect_binder.bind_ability`)
        keeps functioning while that source sits in the graveyard — the
        Eidolon/Phoenix family ("Whenever you cast a multicolored spell, you
        may return this card from your graveyard to your hand." — Aurora
        Eidolon; "Whenever a Demon you control enters, return this card from
        your graveyard to your hand." — Blood Speaker). Unlike
        `_collect_mill_return_from_graveyard_triggers` above, this scans the
        object's own already-bound `triggered_abilities` — the ordinary
        `check_trigger`/subject-condition machinery works unchanged for a
        graveyard-sitting source (a card's `controller_id` already defaults
        to its `owner_id` and never diverges without a control-change effect,
        which can't reach a graveyard card), so nothing per-firing needs to
        be rebuilt here, just fired from a different scan than
        `_collect_triggers`'s battlefield-only one.
        """
        for player in self.state.players:
            for obj in player.graveyard:
                for ability in obj.triggered_abilities:
                    if not getattr(ability, "functions_from_graveyard", False):
                        continue
                    if isinstance(ability, TriggeredAbility) and ability.check_trigger(event, self.context):
                        self.pending_triggers.append((ability, event))

    def _collect_haunt_triggers(self, event: GameEvent) -> None:
        """RULE 702.55: an exiled haunter sees its linked creature die."""
        if event.type != EventType.DIES:
            return
        dying_id = event.get("instance_id")
        if dying_id is None:
            return
        for owner in self.state.players:
            for obj in owner.exile:
                if getattr(obj, "haunting_instance_id", None) != dying_id:
                    continue
                for ability in obj.triggered_abilities:
                    if not isinstance(ability, TriggeredAbility):
                        continue
                    if ability.trigger_event != EventType.DIES:
                        continue
                    if not any(isinstance(effect, HauntLinkedDeathEffect) for effect in ability.effects):
                        continue
                    self.pending_triggers.append((ability, event))
    def _collect_cycled_triggers(self, event: GameEvent) -> None:
        """RULE 702.28c: "When you cycle this card, `<effect>`." fires from
        the graveyard the Cycling cost's own ``discard_self`` just put its
        source into — `_collect_triggers`'s main loop is battlefield-only
        (`state.permanents()`), so a `CYCLED`-watching ability would
        otherwise never be seen. Gated purely on ``trigger_event ==
        EventType.CYCLED`` rather than a `functions_from_graveyard`-style
        flag (`_collect_graveyard_function_triggers`'s own idiom): every
        real card's cycling bonus watches exactly this one event and no
        other, so the event identity alone is enough to scope the scan —
        no separate marker needed.
        """
        if event.type != EventType.CYCLED:
            return
        for player in self.state.players:
            for obj in player.graveyard:
                for ability in obj.triggered_abilities:
                    if getattr(ability, "trigger_event", None) != EventType.CYCLED:
                        continue
                    if isinstance(ability, TriggeredAbility) and ability.check_trigger(event, self.context):
                        self.pending_triggers.append((ability, event))
    def _collect_self_cast_triggers(self, event: GameEvent) -> None:
        """RULE 601.2i/603.2: "When you cast this spell, `<effect>`."
        (Kozilek, Butcher of Truth's "draw four cards", the Eldrazi titan
        template) — a triggered ability that belongs to the spell *itself*,
        which is only ever on the stack, never the battlefield, at the
        moment `SPELL_CAST` fires for it (`RulesEngine.cast_spell` sets
        ``obj.zone = Zone.STACK`` before firing the event). `_collect_
        triggers`'s main loop (`state.permanents()`) is battlefield-only —
        the same "no permanent to hang an ability off, or in this case the
        wrong zone to be found in" reason `_collect_cycled_triggers`/
        `_collect_suspend_triggers` each scan a dedicated zone instead of
        relying on it.

        Narrowly scoped to the exact object `SPELL_CAST` names (`GameState.
        find_object` — spans every zone including the stack) rather than
        widening the main loop to include stack objects generally: a
        ``{"subject": "self"}`` condition already matches purely by
        `instance_id` (`effect_binder._subject_condition`), so this only
        needs to *find* the right object, not re-derive any scoping logic.

        Only abilities carrying `TriggeredAbility.functions_from_stack`
        are checked here — *not* every `SPELL_CAST`-watching ability the
        object happens to carry. Without that filter, a permanent with an
        ordinary "whenever **you** cast a spell" static (Crypt Ghast's own
        Extort) would wrongly fire off *its own* casting: at the moment
        `SPELL_CAST` fires, Crypt Ghast is still a spell on the stack, not
        yet a permanent, so Extort shouldn't function at all (RULE 113.6a
        — a permanent's ability functions from the battlefield only,
        absent an explicit "functions from Y" reminder) — but a bare
        ``{"subject": "you"}`` condition can't tell "this object casting
        itself" apart from "this object's controller casting anything
        else," since both compare the same `player_id`/`controller_id`
        pair. `functions_from_stack` is inferred at bind time purely from
        the trigger's own shape (`effect_binder.bind_ability`), so only a
        genuine "self" subject on a `SPELL_CAST` event ever qualifies.
        """
        if event.type != EventType.SPELL_CAST:
            return
        instance_id = event.get("instance_id")
        if instance_id is None:
            return
        obj = self.state.find_object(instance_id)
        if obj is None:
            return
        for ability in obj.triggered_abilities + obj.granted_triggered_abilities:
            if not getattr(ability, "functions_from_stack", False):
                continue
            if isinstance(ability, TriggeredAbility) and ability.check_trigger(event, self.context):
                self.pending_triggers.append((ability, event))
    def _collect_suspend_triggers(self, event: GameEvent) -> None:
        """RULE 702.62a: Suspend's 2nd/3rd abilities "function in the exile
        zone" — a suspended card is never a permanent, so `_collect_
        triggers`'s main loop (`state.permanents()`) can never see it, the
        same reason `_collect_cycled_triggers`/`_collect_graveyard_function_
        triggers` scan a dedicated zone instead. Built fresh each owner's
        upkeep off live suspended state (zone + `_has_suspend` + a time
        counter, RULE 702.62b's own definition) rather than a bound
        `TriggeredAbility`, the same "no permanent to hang an ability off"
        shape `_collect_inherent_triggers` uses for Monarch/Initiative —
        necessary here regardless of Delay, since Suspend can be *granted*
        mid-game with nothing printed on the card to bind at load time.
        """
        if event.type != EventType.STEP_BEGIN or event.get("step") != "upkeep":
            return
        active_id = self.state.active_player.id
        for player in self.state.players:
            for obj in list(player.exile):
                if obj.owner_id != active_id:
                    continue
                if not _has_suspend(obj) or obj.counters.get("time", 0) <= 0:
                    continue
                ability = TriggeredAbility(
                    trigger_event=EventType.STEP_BEGIN,
                    effects=[SuspendUpkeepEffect(source=obj)],
                    controller_id=obj.owner_id,
                    source=obj,
                    description=(
                        "At the beginning of your upkeep, remove a time "
                        "counter from this card. When the last is removed, "
                        "you may cast it without paying its mana cost."
                    ),
                )
                self.pending_triggers.append((ability, event))
    def put_triggers_on_stack(self) -> int:
        """Move fired triggers onto the stack (RULE 603.3). Returns count.

        Active player's triggers are placed first so they resolve last
        (RULE 603.3b APNAP ordering). When `state.interactive_ordering` is on
        and the active player has two or more simultaneous triggers, they
        choose the intra-player order via a `pending_choice` (RULE 603.3b)
        instead of a deterministic placement.
        """
        if not self.pending_triggers:
            return 0
        active_id = self.state.active_player.id
        mine = [t for t in self.pending_triggers if t[0].controller_id == active_id]
        rest = [t for t in self.pending_triggers if t[0].controller_id != active_id]

        if self.state.interactive_ordering and len(mine) >= 2 and not self.state.pending_choice:
            # Defer to the player: stash the sets and open the ordering choice.
            self._ordering_active = mine
            self._ordering_rest = rest
            self.pending_triggers.clear()
            self.state.pending_choice = self._trigger_order_choice()
            return 0

        count = len(self.pending_triggers)
        self.pending_triggers.clear()
        self._place_triggers(mine + rest)  # active first (bottom of stack)
        return count
    @staticmethod
    def _trigger_target_specs(effects: list[Any]) -> list[TargetSpec]:
        """Every targeting effect's requirement in ``effects``, in order
        (RULE 115.1).

        One `TargetSpec` per targeting effect — `_place_or_pause_trigger`
        gathers one target per spec (via `_continue_trigger_multi_target`
        for the 2+ case, `StackItem.target_groups`-partitioned so each
        effect resolves against its own target, not a shared list). Takes a
        raw effects list rather than an ability, since a modal trigger's
        *chosen mode* — not the ability's own (possibly empty) ``effects``
        — is what actually needs a target; RULE 700.2's mode choice is made
        first (see `_place_triggers`), before this ever runs on the mode's
        effects.
        """
        specs: list[TargetSpec] = []
        for effect in effects:
            # `target_specs` (not ``target_spec``) so a single effect that
            # genuinely needs two differently-typed targets — "attach target
            # Equipment you control to target creature you control" — is
            # gathered as two requirements (`GameEffect.extra_target_specs`).
            specs.extend(getattr(effect, "target_specs", None) or [])
        return specs
    def _trigger_controller_id(
        self, ability: "TriggeredAbility", event: Optional[GameEvent]
    ) -> str:
        """Which player chooses this firing's target(s)/mode/"you may" —
        ordinarily ``ability.controller_id`` (this ability's own source's
        controller), but for a group-subject trigger built with
        `TriggeredAbility.controller_from_trigger_event` (PAR-30 — Confusion
        in the Ranks' "**its** controller chooses target permanent…") it's
        the firing event's own subject controller instead, since the two can
        genuinely differ: the ability's static source triggers off *any*
        artifact/creature/enchantment entering, not just its controller's
        own. Falls back to the ordinary path if the event carries no
        ``controller_id`` (a player-only event, or no event at all)."""
        if ability.controller_from_trigger_event and event is not None:
            event_controller = event.get("controller_id")
            if event_controller is not None:
                return event_controller
        return ability.controller_id or self.state.active_player.id
    def _place_triggers(self, queue: list[tuple["TriggeredAbility", GameEvent]]) -> None:
        """Place queued triggers (RULE 603.3), pausing on one that's modal
        (RULE 700.2 — the mode is chosen first, before any target/"you may"
        choice its own effects might still need), needs a target, or is a
        "you may" with nothing to target, instead of just resolving/skipping
        it blind (RULE 115/603.3c/603.5).

        A mandatory, non-modal trigger with no targeting effect is placed
        immediately (unaffected — the overwhelming common case). One that's
        modal, targets, or is optional, opens a `pending_choice`:
        `resolve_trigger_mode_choice`/`resolve_trigger_target_choice` places
        it (or not, if declined) and resumes this same queue. A *required*
        target with no legal option at all doesn't go on the stack (RULE
        603.3c) — dropped, not placed.

        A trigger chosen via the (opt-in, off-by-default) RULE 603.3b
        interactive-ordering choice (`resolve_trigger_order_choice`) is
        placed through this same method — as a one-item ``queue`` — so it
        pauses for its own mode/target/"you may" choice exactly like the
        deterministic path; `_maybe_continue_ordering` (called once this
        method's ``queue`` drains without pausing) is what resumes the
        ordering flow for whatever's still unordered afterward.
        """
        while queue:
            ability, event = queue.pop(0)
            if getattr(ability, "reflexive", False):
                # RULE 603.3d "that permanent/spell": the target is the object
                # that fired ``event``, not a chosen one — bake it in and
                # place directly (no `trigger_target` choice). A vanished
                # object (spell already off the stack) drops the trigger
                # (RULE 603.3c), same as a required target with no legal pick.
                obj = self.state.find_object(event.get("instance_id"))
                if obj is None:
                    continue
                if ability.optional:
                    # RULE 603.5 (Perplexing Chimera — "you may exchange
                    # control of this creature and **that spell**."): still a
                    # real "do it or don't" even though the target is fixed,
                    # not chosen — the same `trigger_target` "do"/"decline"
                    # UI a targetless "you may" uses, just carrying the
                    # already-resolved object across the pause instead of
                    # nothing.
                    self._pending_trigger_ability = ability
                    self._pending_trigger_queue = queue
                    self._pending_trigger_event = event
                    self._pending_trigger_reflexive_target = obj
                    self.state.pending_choice = self._trigger_may_choice(ability, event=event)
                    return
                self._place_trigger(ability, targets=[obj], event=event)
                continue
            if ability.modes:
                if getattr(ability, "modes_exhaust_per_turn", False):
                    key = (str(getattr(getattr(ability, "source", None), "instance_id", "")), id(ability))
                    if len(self.state.trigger_mode_history.get(key, set())) >= len(ability.modes):
                        # RULE 603.3c analogue: this firing has no legal
                        # mandatory mode, so no trigger object is created.
                        continue
                self._pending_trigger_ability = ability
                self._pending_trigger_queue = queue
                self._pending_trigger_event = event
                self.state.pending_choice = self._trigger_mode_choice(ability)
                return
            if not self._place_or_pause_trigger(ability, ability.effects, queue, event=event):
                return
        self._maybe_continue_ordering()
    def _place_or_pause_trigger(
        self,
        ability: "TriggeredAbility",
        effects: list[Any],
        queue: list[tuple["TriggeredAbility", GameEvent]],
        event: Optional[GameEvent] = None,
    ) -> bool:
        """Place ``ability`` using ``effects`` as its resolve-time effects if
        it can go on the stack immediately; otherwise open the matching
        `pending_choice` and return ``False`` (the caller must stop — the
        choice resolver re-enters `_place_triggers` on ``queue`` once
        answered). Returns ``True`` when the caller's loop may continue
        synchronously (placed, or dropped for lacking a legal required
        target).

        ``effects`` is ``ability.effects`` for an ordinary trigger, or a
        modal trigger's already-chosen mode's effects (`_trigger_mode_
        choice`/`resolve_trigger_mode_choice`) — only in the latter case
        does the placed `StackItem` carry ``effects`` directly instead of
        the `TriggeredAbility` wrapper (`_place_trigger`'s
        ``effects_override``), since the ability's own fixed ``effects``
        (empty for a modal trigger) is never what should resolve.
        """
        specs = self._trigger_target_specs(effects)
        # RULE 601.2c: a requirement wanting N targets (a printed "up to two
        # target creatures", or a `count_selector` resolved against the board
        # right now — "up to **X**", "for each opponent") is gathered as N
        # consecutive single-target rounds by the multi-spec path below, then
        # collapsed back to one group per *original* spec at placement.
        # ``spans`` is that mapping; an all-ones ``spans`` means nothing was
        # expanded and every path below behaves exactly as it did before.
        specs, spans = expand_counts(
            specs,
            self.state,
            self._trigger_controller_id(ability, event),
            ability.source,
        )
        override = effects if effects is not ability.effects else None
        if not specs:
            if not ability.optional:
                self._place_trigger(ability, effects_override=override, event=event)
                return True
            # RULE 603.5: a "you may" with no target still needs a choice
            # of whether to do it at all.
            self._pending_trigger_ability = ability
            self._pending_trigger_effects = override
            self._pending_trigger_queue = queue
            self._pending_trigger_event = event
            self.state.pending_choice = self._trigger_may_choice(ability, event=event)
            return False
        if len(specs) == 1:
            # The overwhelming common case — one targeting effect, unchanged
            # from before `target_groups` existed (a flat ``targets`` list
            # of exactly this one effect's picks).
            spec = specs[0]
            controller_id = self._trigger_controller_id(ability, event)
            options = legal_targets(self.state, controller_id, spec, source=ability.source, trigger_event=event)
            if not options:
                if spec.optional:
                    # RULE 115.1a: "up to one target" is satisfied by
                    # choosing *zero* targets, so an empty board doesn't
                    # stop the ability going on the stack — it resolves with
                    # nothing chosen. Gilded Drake depends on exactly this:
                    # with no opponent's creature to exchange with, the
                    # ability must still resolve in order to make it
                    # sacrifice itself. Only a *required* target the board
                    # can't supply drops the trigger (RULE 603.3c, below).
                    self._place_trigger(ability, effects_override=override, event=event)
                return True  # RULE 603.3c: no legal target — never placed
            self._pending_trigger_ability = ability
            self._pending_trigger_effects = override
            self._pending_trigger_queue = queue
            self._pending_trigger_event = event
            # RULE 115.1a: "up to one target" is its own, target-level
            # optionality (`spec.optional`) distinct from RULE 603.5's
            # whole-ability "you may" (`ability.optional`) — a mandatory
            # trigger can still decline *its own* "up to one" target. Bug
            # found while building Displacer Kitten (MEC-12): the "no legal
            # targets at all" branch just above already reads `spec.
            # optional` correctly; this prompt-building branch didn't, so
            # "up to one" only ever showed a decline button when the whole
            # ability happened to *also* be a "you may".
            self.state.pending_choice = self._trigger_target_choice(
                ability, options, allow_decline=spec.optional or ability.optional, event=event,
            )
            return False
        # RULE 115.1/603.3c generalized: 2+ *different* targeting effects (or
        # one effect wanting 2+ targets, expanded above) — gather one target
        # per spec, one choice at a time (mirrors `_trigger_mode_choice`'s
        # "pick up to N, one at a time"), then place with `target_groups` so
        # each effect resolves against its own picks.
        return self._continue_trigger_multi_target(
            ability, override, queue, specs, [], event, spans
        )
    @staticmethod
    def _span_bounds(spans: Optional[list[int]], idx: int) -> tuple[int, int]:
        """``(start, length)`` of the expanded span holding spec ``idx`` —
        i.e. which *original* requirement it belongs to and how many rounds
        that requirement was split into (`targeting.expand_counts`).
        ``(idx, 1)`` when nothing was expanded."""
        if not spans:
            return idx, 1
        start = 0
        for span in spans:
            if start <= idx < start + span:
                return start, span
            start += span
        return idx, 1
    @classmethod
    def _span_picks(
        cls, groups: list[list[Any]], spans: Optional[list[int]], idx: int
    ) -> set[Any]:
        """The instance ids already picked for the *same* original
        requirement as expanded spec ``idx`` — see `targeting.expand_counts`.

        Empty when nothing was expanded (``spans`` all ones, or absent), so
        the unexpanded path filters nothing and behaves as it always has.
        """
        if not spans:
            return set()
        start, _ = cls._span_bounds(spans, idx)
        return {
            getattr(obj, "instance_id", None)
            for group in groups[start:idx]
            for obj in group
            if getattr(obj, "instance_id", None) is not None
        }
    def _continue_trigger_multi_target(
        self,
        ability: "TriggeredAbility",
        override: Optional[list[Any]],
        queue: list[tuple["TriggeredAbility", GameEvent]],
        specs: list[TargetSpec],
        groups: list[list[Any]],
        event: Optional[GameEvent] = None,
        spans: Optional[list[int]] = None,
    ) -> bool:
        """Gather the next not-yet-filled spec's target (RULE 115.1), one at
        a time, for a trigger with 2+ *different* targeting effects.

        ``groups`` is what's been picked so far, in spec order; once every
        spec has a group, the ability is placed with `target_groups=groups`
        (`_place_trigger`). A spec with no legal option is skipped (empty
        group) if it's "up to N" (``optional``), or drops the whole ability
        (RULE 603.3c — a required target the board can't supply) otherwise.

        ``spans`` maps these specs back onto the *original* requirements when
        `targeting.expand_counts` split a multi-target one into a round each;
        the groups are collapsed by it at placement so every effect still
        receives one flat list of its own picks.
        """
        idx = len(groups)
        if idx >= len(specs):
            self._place_trigger(
                ability,
                target_groups=collapse_groups(groups, spans) if spans else groups,
                effects_override=override,
                event=event,
            )
            return True
        spec = specs[idx]
        controller_id = self._trigger_controller_id(ability, event)
        options = legal_targets(self.state, controller_id, spec, source=ability.source, trigger_event=event)
        # RULE 601.2c: the same object can't be chosen twice for one
        # requirement, so the rounds an expanded multi-target spec was split
        # into exclude each other's picks. Cross-*requirement* exclusion is a
        # different rule and stays `distinct_from_others`' job.
        picked = self._span_picks(groups, spans, idx)
        if picked:
            options = [o for o in options if o.get("instance_id") not in picked]
        if not options:
            if spec.optional:
                return self._continue_trigger_multi_target(
                    ability, override, queue, specs, groups + [[]], event, spans
                )
            return True  # RULE 603.3c: no legal target — never placed
        self._pending_trigger_ability = ability
        self._pending_trigger_effects = override
        self._pending_trigger_queue = queue
        self._pending_trigger_event = event
        self._pending_trigger_specs = specs
        self._pending_trigger_groups = groups
        self._pending_trigger_spans = spans
        # RULE 603.5: "you may" is asked once, on the *first* target — from
        # then on the ability is already committed to, so later specs are
        # never declinable on their own.
        choice = self._trigger_target_choice(
            ability, options, kind="trigger_target_multi",
            allow_decline=(idx == 0 and ability.optional), event=event,
        )
        # RULE 115.1a: "up to N target …" lets the player stop before N. That
        # is a *different* answer from the "you may" decline just above —
        # stopping keeps the ability and resolves it against however many
        # were picked, declining abandons it — so it is its own option rather
        # than an overloaded "decline". Only offered on a requirement that
        # was actually expanded into several rounds; a plain "up to one"
        # keeps expressing "none" through the decline it already had.
        _, span_len = self._span_bounds(spans, idx)
        if spec.optional and span_len > 1:
            choice["options"].append({"id": "stop", "label": "Keine weiteren"})
        self.state.pending_choice = choice
        return False
    def _trigger_modal_choice_config(self, ability: "TriggeredAbility") -> tuple[int, bool]:
        """Active count for a triggered conditional modal header."""
        choose, at_least = ability.modes_choose, ability.modes_at_least
        override = getattr(ability, "modes_override", None) or {}
        condition = override.get("condition") if isinstance(override, dict) else None
        if not isinstance(condition, dict):
            return choose, at_least
        player = next((p for p in self.state.players if p.id == ability.controller_id), None)
        if player is None:
            return choose, at_least
        kind = condition.get("kind")
        active = False
        if kind == "card_types_in_graveyard_at_least":
            types: set[str] = set()
            for card in player.graveyard:
                types |= card.type_words
            types.discard("permanent")
            active = len(types) >= int(condition.get("amount", 0))
        elif kind == "life_total_exactly":
            active = player.life == int(condition.get("amount", -1))
        elif kind == "descended_this_turn":
            active = player.id in (getattr(self.state, "permanent_card_to_graveyard_this_turn", set()) or set())
        elif kind == "controls_commander_as_cast":
            active = any(o.controller_id == player.id and o.is_commander for o in self.state.battlefield)
        if active:
            return int(override.get("choose", choose)), bool(override.get("at_least", False))
        return choose, at_least

    def _trigger_mode_choice(
        self, ability: "TriggeredAbility", chosen: Optional[list[int]] = None
    ) -> dict[str, Any]:
        """Build the `pending_choice` for a modal triggered ability's mode
        (RULE 700.2) — chosen as it's put on the stack, before any target/
        "you may" choice the chosen mode's own effects might still need
        (`resolve_trigger_mode_choice` hands off to `_place_or_pause_
        trigger` for that).

        ``chosen`` is the indices already picked in an earlier round of a
        "choose *N*" (``N>=2``) or "choose *N* or more" ability — excluded
        from this round's offer so the same mode can't be picked twice,
        mirroring the library search's "pick up to N, one at a time"
        pattern (`_search_choice`). Absent/empty for the first round and for
        the ordinary "choose one" case (``modes_choose == 1`` and not
        ``modes_at_least``).
        """
        options = ability.modes or []
        choose, at_least = self._trigger_modal_choice_config(ability)
        picked = set(chosen or [])
        repeatable = bool(getattr(ability, "modes_repeatable", False))
        history_key = (
            str(getattr(getattr(ability, "source", None), "instance_id", "")), id(ability),
        )
        exhausted = (
            self.state.trigger_mode_history.get(history_key, set())
            if getattr(ability, "modes_exhaust_per_turn", False)
            else set()
        )
        choice_options: list[dict[str, Any]] = [
            {"id": str(i), "label": opt.get("description") or f"Modus {i + 1}"}
            for i, opt in enumerate(options)
            if (repeatable or i not in picked) and i not in exhausted
        ]
        if (
            ability.modes_or_both and choose == 1 and len(options) == 2 and not picked
            and not ({0, 1} & exhausted)
        ):
            # RULE 700.2e — only offered for the fixed choose-1-of-2 case.
            choice_options.append({"id": "both", "label": "Beides"})
        if at_least and len(picked) >= choose and len(picked) < len(options):
            # RULE 700.2 "choose N or more" — the minimum is met, so the
            # player may stop here instead of picking every remaining mode.
            choice_options.append({"id": "done", "label": "Fertig"})
        if ability.modes_optional and not picked:
            # RULE 700.2 "choose up to one —" (Hullbreaker Horror) — the
            # 0-or-1 sibling of the plain "choose one": a real decline,
            # unlike `modes_at_least`'s "done" (which only appears once a
            # nonzero minimum is already met).
            choice_options.append({"id": "decline", "label": "Nichts wählen"})
        return {
            "kind": "trigger_mode",
            "player_id": ability.controller_id or self.state.active_player.id,
            "prompt": ability.description or "Modus für ausgelöste Fähigkeit wählen",
            "options": choice_options,
            "chosen": list(chosen or []),
            "mode_history_key": history_key,
        }
    def resolve_trigger_mode_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `trigger_mode` choice (RULE 700.2): pick which
        mode(s) this firing uses, then continue exactly like a non-modal
        trigger via `_place_or_pause_trigger` — the chosen mode's own
        effects may still need their own target/"you may" choice next, so
        this doesn't necessarily place anything itself. ``answer`` is a
        mode's index (as a string), ``"both"`` (RULE 700.2e), or ``"done"``
        (RULE 700.2 "choose N or more", only once the minimum is met); an
        unrecognized/missing answer defaults to the first not-yet-chosen
        mode rather than dropping a mandatory choice.

        For a "choose *N*" ability (``modes_choose > 1``, RULE 700.2) this
        picks one mode per call — once fewer than ``modes_choose`` are
        picked, the choice re-opens (excluding what's already picked)
        instead of placing anything, exactly like `resolve_search_choice`
        offering a library search "one card at a time". For "choose *N* or
        more" (``modes_at_least``) the choice keeps re-opening past the
        minimum too, until either every mode is picked or the player answers
        "done". Once enough are picked, every chosen mode's effects combine
        **in printed order** (not pick order) — RULE 700.2's modes resolve
        in the order the ability's text lists them, same as RULE 700.2e
        "both" already did.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "trigger_mode":
            raise ValueError("no pending trigger mode choice to resolve")
        ability = self._pending_trigger_ability
        queue = self._pending_trigger_queue
        event = self._pending_trigger_event

        options = (ability.modes or []) if ability is not None else []
        if ability is None or not options:
            self.state.pending_choice = None
            self._pending_trigger_ability = None
            self._pending_trigger_queue = []
            self._pending_trigger_event = None
            self._place_triggers(queue)
            return

        already_chosen: list[int] = list(choice.get("chosen") or [])
        choose, at_least = self._trigger_modal_choice_config(ability)

        if (
            answer == "both" and ability.modes_or_both and ability.modes_choose == 1
            and len(options) == 2 and not getattr(ability, "modes_exhaust_per_turn", False)
        ):
            effects: list[Any] = []
            for opt in options:
                effects.extend(opt["effects"])
        elif (
            answer == "done"
            and at_least
            and len(already_chosen) >= choose
        ):
            effects = []
            for i in sorted(already_chosen):
                effects.extend(options[i]["effects"])
        elif answer == "decline" and ability.modes_optional and not already_chosen:
            # RULE 700.2 "choose up to one —": nothing chosen, nothing
            # resolves — the same "declined, no effects at all" outcome a
            # plain optional trigger's own decline reaches, not "auto-pick
            # the first mode" (which the generic fallback below would do
            # for an unrecognized answer).
            effects = []
        else:
            history_key = tuple(choice.get("mode_history_key") or ())
            exhausted = (
                self.state.trigger_mode_history.get(history_key, set())
                if getattr(ability, "modes_exhaust_per_turn", False)
                else set()
            )
            available = [
                i for i in range(len(options))
                if (getattr(ability, "modes_repeatable", False) or i not in already_chosen)
                and i not in exhausted
            ]
            if not available:
                # Every per-turn mode is exhausted. This firing has no legal
                # mandatory choice, so it simply produces no stack object.
                effects = []
                self.state.pending_choice = None
                self._pending_trigger_ability = None
                self._pending_trigger_queue = []
                self._pending_trigger_event = None
                self._place_triggers(queue)
                return
            try:
                idx = int(answer) if answer is not None else available[0]
            except (TypeError, ValueError):
                idx = available[0]
            if idx not in available:
                idx = available[0]
            if getattr(ability, "modes_exhaust_per_turn", False):
                self.state.trigger_mode_history.setdefault(history_key, set()).add(idx)
            picked = already_chosen + [idx]
            more_needed = len(picked) < choose or (
                at_least and len(picked) < len(options)
            )
            if more_needed:
                # RULE 700.2 "choose N"/"choose N or more": re-open, excluding what's picked.
                self.state.pending_choice = self._trigger_mode_choice(ability, chosen=picked)
                return
            # Enough modes picked — combine in printed order, not pick order.
            effects = []
            for i in sorted(picked):
                effects.extend(options[i]["effects"])

        self.state.pending_choice = None
        self._pending_trigger_ability = None
        self._pending_trigger_queue = []
        self._pending_trigger_event = None
        if self._place_or_pause_trigger(ability, effects, queue, event=event):
            self._place_triggers(queue)
    def _trigger_target_choice(
        self,
        ability: "TriggeredAbility",
        options: list[dict[str, Any]],
        kind: str = "trigger_target",
        allow_decline: Optional[bool] = None,
        event: Optional[GameEvent] = None,
    ) -> dict[str, Any]:
        """Build the `pending_choice` offering ``options`` as an ability's
        target — one button per legal permanent/player, matching the generic
        choice UI's `{"id", "label", "instance_id"?}` option shape (the same
        one search/cascade/discover/order_triggers already use).

        ``kind``/``allow_decline`` are only overridden by
        `_continue_trigger_multi_target` (2+ *different* targeting effects,
        ``"trigger_target_multi"`` — its own resolver,
        `resolve_trigger_target_multi_choice`, so the single-spec path below
        stays byte-for-byte unchanged); ``allow_decline=None`` keeps this
        method's original behaviour of following ``ability.optional``
        (RULE 603.5 "you may"). ``event`` is only consulted (via
        `_trigger_controller_id`) for a `controller_from_trigger_event`
        ability (PAR-30, Confusion in the Ranks) — every other trigger keeps
        prompting `ability.controller_id` exactly as before.
        """
        choice_options: list[dict[str, Any]] = []
        for opt in options:
            if "instance_id" in opt:
                choice_options.append(
                    {"id": str(opt["instance_id"]), "label": opt["name"], "instance_id": opt["instance_id"]}
                )
            else:
                choice_options.append({"id": opt["player_id"], "label": opt["name"]})
        decline = ability.optional if allow_decline is None else allow_decline
        if decline:
            choice_options.append({"id": "decline", "label": "Nichts wählen"})
        return {
            "kind": kind,
            "player_id": self._trigger_controller_id(ability, event),
            "prompt": ability.description or "Ziel für ausgelöste Fähigkeit wählen",
            "options": choice_options,
        }
    def _trigger_may_choice(
        self, ability: "TriggeredAbility", event: Optional[GameEvent] = None,
    ) -> dict[str, Any]:
        """Build the `pending_choice` for a targetless "you may" trigger
        (RULE 603.5) — do it, or don't. Reuses the ``trigger_target`` kind
        (same resolver, same generic choice UI); ``"do"`` is the sentinel
        `resolve_trigger_target_choice` recognizes as "yes, without a
        target"."""
        return {
            "kind": "trigger_target",
            "player_id": self._trigger_controller_id(ability, event),
            "prompt": ability.description or "Ausgelöste Fähigkeit ausführen?",
            "options": [
                {"id": "do", "label": "Ausführen"},
                {"id": "decline", "label": "Nichts tun"},
            ],
        }
    def resolve_trigger_target_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `trigger_target` choice, then resume `_place_
        triggers` on whatever was still queued behind it.

        ``answer`` is the chosen option's ``id`` — a permanent's stringified
        ``instance_id``, a player's id, or ``"do"`` for a targetless "you
        may" — or `None`/``"decline"`` to not do the (optional) ability at
        all, which simply never goes on the stack.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "trigger_target":
            raise ValueError("no pending trigger target choice to resolve")
        self.state.pending_choice = None
        ability = self._pending_trigger_ability
        queue = self._pending_trigger_queue
        effects_override = self._pending_trigger_effects
        event = self._pending_trigger_event
        reflexive_target = self._pending_trigger_reflexive_target
        self._pending_trigger_ability = None
        self._pending_trigger_queue = []
        self._pending_trigger_effects = None
        self._pending_trigger_event = None
        self._pending_trigger_reflexive_target = None

        if answer == "do":
            if ability is not None:
                # RULE 603.3d + 603.5: a reflexive "you may" carries its
                # already-fixed target across the pause instead of a
                # targetless "you may" (`_place_triggers`'s reflexive
                # branch) — see `_pending_trigger_reflexive_target`.
                self._place_trigger(
                    ability,
                    targets=[reflexive_target] if reflexive_target is not None else None,
                    effects_override=effects_override, event=event,
                )
            self._place_triggers(queue)
            return

        if answer is not None and answer != "decline" and ability is not None:
            target = self._resolve_choice_option(choice["options"], str(answer))
            if target is not None:
                self._place_trigger(
                    ability, targets=[target], effects_override=effects_override, event=event
                )
        self._place_triggers(queue)
    def resolve_trigger_target_multi_choice(self, answer: Optional[str]) -> None:
        """Answer a pending `trigger_target_multi` choice — one target for
        the *next* not-yet-filled targeting effect of a trigger with 2+
        *different* targeting effects (`_continue_trigger_multi_target`).

        ``answer`` is the chosen option's ``id``, same shape as
        `resolve_trigger_target_choice`. A decline (only ever offered on the
        first spec, RULE 603.5 "you may") abandons the whole ability — every
        spec after the first is already committed to. Once every spec has a
        target (or an empty pick for one that's "up to N" with nothing
        legal), the ability is placed with `target_groups` so each effect
        resolves against its own pick, not a shared list.
        """
        choice = self.state.pending_choice
        if not choice or choice.get("kind") != "trigger_target_multi":
            raise ValueError("no pending multi-target trigger choice to resolve")
        self.state.pending_choice = None
        ability = self._pending_trigger_ability
        queue = self._pending_trigger_queue
        effects_override = self._pending_trigger_effects
        specs = self._pending_trigger_specs
        groups = self._pending_trigger_groups
        spans = getattr(self, "_pending_trigger_spans", None)
        event = self._pending_trigger_event
        self._pending_trigger_ability = None
        self._pending_trigger_queue = []
        self._pending_trigger_effects = None
        self._pending_trigger_specs = []
        self._pending_trigger_groups = []
        self._pending_trigger_spans = None
        self._pending_trigger_event = None

        if answer == "stop" and ability is not None:
            # RULE 115.1a: stop short of N on an expanded "up to N"
            # requirement — the remaining rounds of *this* span are filled
            # with empty picks and the next requirement (if any) continues.
            start, span_len = self._span_bounds(spans, len(groups))
            groups = groups + [[]] * (start + span_len - len(groups))
            if self._continue_trigger_multi_target(
                ability, effects_override, queue, specs, groups, event, spans
            ):
                self._place_triggers(queue)
            return
        if answer is not None and answer != "decline" and ability is not None:
            target = self._resolve_choice_option(choice["options"], str(answer))
            groups = groups + [[target] if target is not None else []]
            if self._continue_trigger_multi_target(
                ability, effects_override, queue, specs, groups, event, spans
            ):
                self._place_triggers(queue)
            return
        # Declined (or nothing left to resolve against) — the whole ability
        # is abandoned, same as a single-spec "you may" decline.
        self._place_triggers(queue)
    def _resolve_choice_option(self, options: list[dict[str, Any]], answer: str) -> Any:
        """The permanent/spell/player a `trigger_target` option ``answer``
        names.

        ``instance_id`` options aren't always a *battlefield* permanent —
        ``kind="spell"`` (`targeting.legal_targets`, Nether Void-shaped
        "whenever a player casts a spell, counter it unless…") offers a
        `StackItem`'s own object, which `state.permanents()` alone would
        never find (RULE 111.7: a spell isn't a permanent). `state.
        find_object` already searches every zone, stack included.
        """
        match = next((o for o in options if o["id"] == answer), None)
        if match is None:
            return None
        if "instance_id" in match:
            return self.state.find_object(match["instance_id"])
        try:
            return self.state.player_by_id(match["id"])
        except KeyError:
            return None
    def _place_trigger(
        self,
        ability: "TriggeredAbility",
        targets: Optional[list[Any]] = None,
        effects_override: Optional[list[Any]] = None,
        target_groups: Optional[list[list[Any]]] = None,
        event: Optional[GameEvent] = None,
    ) -> None:
        """Push ``ability`` onto the stack. ``effects_override``, when given,
        replaces the usual ``[ability]`` wrapper with a raw effects list — a
        modal trigger's already-chosen mode (`_place_or_pause_trigger`),
        which resolves those effects directly rather than through
        `TriggeredAbility.apply()` reading the ability's own (empty)
        ``effects``. `StackItem._derive_category` still classifies the item
        as ``"triggered_ability"`` either way (any non-spell ability item
        defaults to that), so nothing downstream needs to know.

        ``target_groups``, when given (2+ *different* targeting effects,
        gathered one at a time by `_continue_trigger_multi_target`),
        partitions ``targets`` per effect — see `StackItem.target_groups`.
        ``targets`` itself is then derived as the flattened union (unless
        explicitly given) so every existing flat-``targets`` consumer
        (`check_ward` below, Aura attachment, the stack display) still sees
        every chosen target, same as before ``target_groups`` existed.
        """
        if target_groups is not None and targets is None:
            targets = [t for group in target_groups for t in group]
        controller_id = ability.controller_id or self.state.active_player.id
        item = StackItem(
            kind="ability",
            controller_id=controller_id,
            effects=effects_override if effects_override is not None else [ability],
            description=ability.description or "triggered ability",
            targets=targets,
            target_groups=target_groups,
            source=ability.source,
            trigger_event=event,
        )
        self.state.stack.append(item)
        try:
            controller = self.state.player_by_id(controller_id)
        except KeyError:
            controller = None
        if controller is not None:
            self.check_ward(item, controller)
    def _trigger_order_choice(self) -> dict[str, Any]:
        """Build the `pending_choice` for ordering the active player's triggers.

        Each option is one still-to-be-placed trigger; the player picks the one
        to put on the stack next (RULE 603.3b). Picked first → placed first →
        resolves last (the stack is LIFO). ``label`` is the ability's own
        oracle text (`description` is `spec.raw_text` wherever the binder set
        it — see `effect_binder.py`), and ``source_name`` the permanent/card
        it's on, kept as a separate field (rather than folded into the
        label) so the frontend can tell two identically-worded triggers from
        different sources apart without string-parsing a combined label."""
        options = [
            {
                "id": str(i),
                "label": ability.description or "Ausgelöste Fähigkeit",
                "source_name": ability.source.name if ability.source is not None else None,
            }
            for i, (ability, _event) in enumerate(self._ordering_active)
        ]
        return {
            "kind": "order_triggers",
            "player_id": self.state.active_player.id,
            "prompt": "Reihenfolge der ausgelösten Fähigkeiten wählen",
            "options": options,
        }
    def resolve_trigger_order_choice(self, index: Optional[int]) -> None:
        """Place the chosen trigger next (RULE 603.3b), then re-ask or finish.

        ``index`` selects one of the remaining active-player triggers (by its
        option id). Placement goes through `_place_triggers` as a one-item
        queue, so a modal/targeted/optional trigger opens its own choice
        exactly as it would outside an ordering sequence, instead of being
        placed blind — `_maybe_continue_ordering` (invoked once that queue
        drains without pausing) picks up from there: re-opening this same
        choice while 2+ still remain, auto-placing (still pause-aware) once
        only one is left, then flushing the non-active-player triggers the
        same way."""
        if not self._ordering_active:
            self.state.pending_choice = None
            return
        # Default to the first if the index is missing/out of range.
        if index is None or not 0 <= index < len(self._ordering_active):
            index = 0
        ability, event = self._ordering_active.pop(index)
        self.state.pending_choice = None
        self._place_triggers([(ability, event)])
    def _maybe_continue_ordering(self) -> None:
        """Resume the RULE 603.3b ordering flow once a `_place_triggers`
        queue has drained without pausing for a nested choice.

        No-op outside an ordering sequence — `_ordering_active`/
        `_ordering_rest` are empty except while one is in progress, so this
        runs harmlessly at the end of the ordinary (non-interactive)
        placement path too. Re-opens the order choice while 2+ of the active
        player's triggers remain unordered; once exactly one is left there's
        nothing left to choose, so it's placed directly (still through
        `_place_triggers`, so it still pauses for its own mode/target/"you
        may" choice); once none remain, the non-active-player triggers are
        placed the same pause-aware way."""
        if self._ordering_active:
            if len(self._ordering_active) > 1:
                self.state.pending_choice = self._trigger_order_choice()
                return
            ability, event = self._ordering_active.pop(0)
            self._place_triggers([(ability, event)])
            return
        if self._ordering_rest:
            rest = self._ordering_rest
            self._ordering_rest = []
            self._place_triggers(rest)
