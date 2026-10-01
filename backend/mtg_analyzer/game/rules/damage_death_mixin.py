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
from ..combat import has_infect, has_wither, is_protected_from, toxic_value
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
    ReplacementRegistry,
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
    if what == "planeswalker":
        return obj.card.is_planeswalker
    if what == "battle":
        return obj.card.is_battle
    if what == "nonland":
        # "…sacrifice a nonland permanent of their choice or discard a
        # card." (Tergrid's Lantern, MEC-43 round 4E) — the negated-type
        # sibling of the plain type words above; every permanent that
        # isn't a land qualifies, tokens included (unlike `nontoken_
        # creature` below).
        return not obj.is_land
    if what == "nontoken_creature":
        # RULE 111.8/701.17: "each player sacrifices a nontoken creature of
        # their choice" (Accursed Marauder/Liliana, Dreadhorde General's own
        # -4 — the edict family's most common creature-type qualifier).
        return obj.is_creature and not obj.is_token
    if what == "artifact_or_creature":
        # Deadly Dispute/Costly Plunder-shaped "sacrifice an artifact or
        # creature" additional cost.
        return obj.is_creature or obj.card.is_artifact
    if what == "creature_or_planeswalker":
        # RULE 306/302: Tevesh Szat's "another creature or planeswalker" —
        # the one compound word any shipped card needs.
        return obj.is_creature or obj.card.is_planeswalker
    if what == "creature_or_land":
        # PAR-117: Tainted Aether's own edict — "its controller sacrifices
        # a creature or land of their choice."
        return obj.is_creature or obj.is_land
    if what == "creature_artifact_or_land":
        # PAR-13: "sacrifice a creature, artifact, or land of their choice"
        # (Tomb of Annihilation's "Sandfall Cell" dungeon room) — the
        # payer's own choice of *type*, not "any permanent" (which would
        # wrongly also license sacrificing an enchantment/planeswalker).
        return obj.is_creature or obj.card.is_artifact or obj.is_land
    return True  # unknown type word → any permanent, so the cost is payable


#: PAR-78: a damage-prevention shield's own source qualifier — "Prevent all
#: damage that would be dealt to `<recipient>` **by `<source filter>`**."
#: (Argothian Pixies/Champion Lancer/Prismatic Ward/…, ~50 real cards on
#: this template family). A closed, fail-closed whitelist matching
#: `_matches_permanent_type`'s own discipline: an unrecognized filter key
#: never silently widens to "any source" — the caller (the parser) simply
#: doesn't build a `source_filter` dict for a phrase this doesn't cover, so
#: that card stays unclaimed rather than half-modeled. Checked once per
#: `DAMAGE` event, against whatever `GameObject` `event["source_id"]`
#: names (fails closed — no live source object, e.g. a spell already off
#: the stack, never matches a filtered shield).
def _damage_source_matches(
    state: GameState, event: GameEvent, source_filter: Optional[dict], protected_player_id: Optional[str],
) -> bool:
    if not source_filter:
        return True
    source_id = event.get("source_id")
    source = state.find_object(source_id) if source_id is not None else None
    if source is None:
        return False
    if source_filter.get("creature") and not source.is_creature:
        return False
    if source_filter.get("artifact") and not source.card.is_artifact:
        return False
    subtype = source_filter.get("subtype")
    if subtype and subtype.lower() not in source.card.type_line.lower():
        return False
    keyword = source_filter.get("keyword")
    if keyword and not combat.has(source, keyword):
        return False
    without_keyword = source_filter.get("without_keyword")
    if without_keyword and combat.has(source, without_keyword):
        return False
    controller = source_filter.get("controller")
    if controller == "you" and source.controller_id != protected_player_id:
        return False
    if controller == "not_you" and source.controller_id == protected_player_id:
        return False
    color = source_filter.get("color")
    if color and color.upper() not in (source.colors or set()):
        return False
    if source_filter.get("attacking") and not getattr(source, "attacking", False):
        return False
    if source_filter.get("enchanted"):
        # "…by enchanted creatures." (Wall of Putrid Flesh) — the source
        # itself currently has an Aura attached, not the shield's own host.
        if not any(
            o.attached_to == source.instance_id and "aura" in o.card.type_line.lower()
            for o in state.permanents()
        ):
            return False
    return True


class _MaxLifeTotalMarker:
    """MEC-54: a permanent "your maximum life total is N." marker on
    `Player.player_effects` (You Compleat Me). Duck-typed like
    `effects.PlayerShieldEffect`'s `player_life_locked` — the only attribute
    anything reads is ``max_life_total``."""

    def __init__(self, cap: int) -> None:
        self.max_life_total = int(cap)


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




class DamageDeathMixin:
    """Damage/life-loss and every zone move off the battlefield (destroy/sacrifice/exile/bounce/graveyard), plus life gain and damage prevention."""

    def deal_damage(
        self,
        target: Any,
        amount: int,
        source: Optional[GameObject] = None,
        combat: bool = False,
        single_target_hint: bool = False,
    ) -> None:
        is_player = isinstance(target, Player)
        # RULE 615/510.1e: a source-scoped prevention effect (Loafing Giant),
        # or a creature that assigns no combat damage this turn (Gaze of
        # Pain, MEC-99), stops all combat damage this object would deal,
        # irrespective of recipient — a one-shot ability the creature deals
        # separately (`combat=False`) is unaffected either way.
        if combat and source is not None and getattr(source, "temp_prevent_combat_damage_dealt", False):
            return
        # RULE 702.16c: protection prevents *all* damage from a source of the
        # stated quality, not just combat damage — a burn spell from a
        # protected colour fizzles here same as a blocked attacker would.
        # Players carry no protection in this model.
        if not is_player and source is not None and is_protected_from(target, source):
            return
        # RULE 702.16e: a *player* with protection from everything (Teferi's
        # Protection) is dealt no damage at all — the player-side mirror of
        # the permanent check above, which `is_protected_from` can't answer
        # because players carry no printed protection.
        if is_player and self._player_protected_from_everything(target):
            return
        # MEC-62 (Noble Heritage): "you gain protection from that player" —
        # the single-player-scoped sibling just above, checked only when a
        # source is actually known (an unattributed/sourceless damage event
        # can't match "controlled by that player" either way).
        if is_player and source is not None and self._player_protected_from_source_controller(target, source):
            return
        target_id = target.id if is_player else target.instance_id
        event = GameEvent(
            EventType.DAMAGE,
            amount=amount,
            is_player=is_player,
            target_id=target_id,
            # RULE 603.1 recipient-scoped "a creature you control is dealt
            # damage" (MEC-11, Rite of Passage-shaped) — the mirror of
            # ``source_controller_id`` below, for a `"group"` condition
            # `effect_binder._build_group_ok` marks with
            # ``condition["recipient"]``. Only meaningful for an object
            # target (a player has no controller); ``None`` for a player
            # target fails the "you control" check closed rather than
            # matching, which is correct — "you control" a permanent, not a
            # player.
            target_controller_id=(target.controller_id if not is_player else None),
            # Carried so a doubling/additional-damage replacement (RULE
            # 616.1, e.g. Furnace of Rath/Torbran) can filter by "a source
            # you control" / "combat damage" / "a red source" — see
            # `_double_damage_replacement`/`_additional_damage_replacement`.
            source_id=source.instance_id if source is not None else None,
            source_controller_id=source.controller_id if source is not None else None,
            source_colors=tuple(getattr(source.card, "color_identity", None) or ()) if source is not None else (),
            # Gratuitous Violence-shaped "a *creature* you control" doubling
            # (as opposed to Furnace of Rath's unscoped "a source") needs
            # this to tell the two apart — see `_double_damage_replacement`.
            source_is_creature=bool(getattr(source, "is_creature", False)),
            combat=combat,
            # "Whenever an instant or sorcery spell you control … deals
            # damage to that creature, Imodane deals that much damage to
            # each opponent." (Imodane, the Pyrohammer) — two flags computed
            # at the call site (where the effect still knows both its own
            # card type and its target_spec's shape) rather than derived
            # generically here, since "targets only a single creature" is a
            # property of the *resolving effect*, not of damage in general.
            source_is_instant_or_sorcery=bool(
                source is not None
                and (getattr(source.card, "is_instant", False) or getattr(source.card, "is_sorcery", False))
            ),
            source_targets_only_single_creature=bool(
                single_target_hint and not is_player and getattr(target, "is_creature", False)
            ),
        )

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is None:
                return
            final = resolved.get("amount", amount)
            if final <= 0:
                return
            # MEC-30: a redirect (`RulesEngine.redirect_damage_from_source`,
            # RULE 616.1c — "that damage is dealt to `<X>` instead") rewrites
            # ``target_id``/``is_player`` on the event itself; re-derive the
            # *actual* recipient from the resolved event rather than the
            # outer closure's original ``target``/``is_player``, so every
            # branch below lands on wherever the damage actually ends up.
            # Falls back to the original target if the resolved event's own
            # id can't be found (shouldn't happen, but never silently drops
            # damage on the floor).
            final_is_player = bool(resolved.get("is_player", is_player))
            if final_is_player == is_player and resolved.get("target_id") == target_id:
                final_target = target
            elif final_is_player:
                final_target = self.state.player_by_id(resolved.get("target_id")) or target
            else:
                final_target = self.state.find_object(resolved.get("target_id")) or target
            # RULE 122.1c: "If damage would be dealt to this permanent, prevent that damage and
            # remove a shield counter from it." Checked on the *resolved* recipient (after any
            # redirect, RULE 616.1c) and before any result of the damage — infect/wither's -1/-1
            # counters, loyalty/defense loss, the DAMAGE event its triggers watch — because
            # prevented damage is never dealt (RULE 615.1). One counter per damage event,
            # however large the damage.
            if not final_is_player and getattr(final_target, "counters", {}).get("shield", 0) > 0:
                self.add_counters(final_target, -1, "shield")
                return
            # RULE 702.90b/c: damage from an infect source is never marked/
            # doesn't cause life loss at all — it is dealt as -1/-1 counters
            # (creature) or poison counters (player) instead. RULE 702.91a's
            # Wither is the creature-only half of that same substitution,
            # with a player still just losing life. Both are checked off the
            # *source*, so an infect source's damage to a planeswalker/battle
            # still falls through to the ordinary loyalty/defense branches
            # below (neither rule mentions those permanent types).
            infect = source is not None and has_infect(source)
            wither = source is not None and has_wither(source)
            if not wither:
                # "All damage is dealt as though its source had wither."
                # (Everlasting Torment) — RULE 609.4b as-though, a standing
                # battlefield static that recolours *every* source's damage
                # to creatures into -1/-1 counters.
                from .. import continuous  # local: avoid the continuous↔rules cycle

                wither = continuous.global_wither_active(self.state)
            if final_is_player and infect:
                self.add_player_counters(final_target, final, "poison", source=source)
                self.state.record_stat(final_target.id, "damage_taken", amount=final)
                # RULE 120.3 (Final Punishment, MEC-43): damage is still
                # "dealt" here even though 702.90b redirects its life-loss
                # consequence into poison counters instead — the DAMAGE event fired
                # below is what the per-turn damage history is derived from.
                if source is not None:
                    self.state.record_stat(source.controller_id, "damage_dealt", amount=final)
                    if combat and source.is_commander:
                        final_target.add_commander_damage(source.instance_id, source.name,
                                                          final * self._commander_damage_multiplier(final_target))
            elif final_is_player:
                # RULE 120.3: damage dealt to a player causes that much life
                # loss. This is a *consequence* of damage, not a separate
                # event a player chose to trigger — go through the same
                # `lose_life` choke point as any other life loss so triggers
                # watching for "loses life" fire consistently regardless of
                # cause.
                self.lose_life(final_target, final, cause="damage")
                self.state.record_stat(final_target.id, "damage_taken", amount=final)
                if source is not None:
                    self.state.record_stat(source.controller_id, "damage_dealt", amount=final)
                    # RULE 903.10a: combat damage from a commander is tallied
                    # separately toward the 21-damage loss threshold.
                    if combat and source.is_commander:
                        final_target.add_commander_damage(source.instance_id, source.name,
                                                          final * self._commander_damage_multiplier(final_target))
            elif getattr(final_target, "is_planeswalker", False):
                # RULE 306.9: damage to a planeswalker removes that many
                # loyalty counters (the 0-loyalty SBA then sends it to the
                # graveyard).
                final_target.add_counters("loyalty", -final)
            elif getattr(final_target, "is_battle", False):
                # RULE 310.6: damage to a battle removes that many defense
                # counters — combat *and* non-combat alike (a burn spell
                # chips a battle down exactly like an attacker does), which
                # is why this sits here rather than in the combat path.
                # Hitting zero isn't handled here: the SBA pass owns both
                # the Siege's own RULE 310.11b defeat trigger and RULE
                # 310.7's graveyard move, so *every* route to zero defense
                # (a "remove a defense counter" effect as much as damage)
                # goes through one place. `add_counters` floors at zero, so
                # overkill damage can't leave a negative count behind.
                final_target.add_counters("defense", -final)
            elif getattr(final_target, "is_creature", False) and (infect or wither):
                # RULE 702.90b/702.91a: damage from an infect or wither
                # source is put on a creature as -1/-1 counters instead of
                # being marked — routed through the ordinary `add_counters`
                # choke point (not `deal_damage` again) so this placement is
                # itself subject to RULE 122's own counter-doubling
                # replacements (Doubling Season et al.), same as any other
                # counters being put on a permanent.
                self.add_counters(final_target, final, "-1/-1", source=source)
            else:
                final_target.damage_marked += final
            # RULE 702.164c: combat damage dealt to a *player* by a source
            # with toxic gives that player poison counters equal to the
            # source's total toxic value, "in addition to the damage's
            # other results" — additive, not a substitution like infect
            # (702.90b) above, so this runs regardless of which branch just
            # ran and composes with infect if a source somehow has both
            # (a rare real shape): infect already converted this same hit
            # into `final` poison counters instead of life loss, and toxic
            # piles its own N on top of that. Combat-only per 702.164c's own
            # wording (unlike infect, which recolors *all* damage, not just
            # combat damage) — read the resolved event's own `combat` flag
            # rather than the outer closure's, since a replacement effect
            # could in principle rewrite it same as `target_id`/`is_player`.
            if final_is_player and bool(resolved.get("combat", combat)) and source is not None:
                toxic_n = toxic_value(source)
                if toxic_n:
                    self.add_player_counters(final_target, toxic_n, "poison", source=source)
            # MEC-49: "whenever a creature dealt damage by ~ this turn dies, …"
            # (`GameState.creatures_damaged_by_source_this_turn`, derived from the
            # DAMAGE event below, which is flagged when its recipient is a creature).
            # Any damage to a creature, combat or not, infect/wither included
            # (RULE 702.90b/702.91a still deal damage, just recolor its result).
            target_is_creature = not final_is_player and getattr(final_target, "is_creature", False)
            # `copy_with` (not a fresh `GameEvent`) so `source_id`/`combat`/
            # `source_controller_id` survive onto the broadcast event — a
            # "whenever equipped creature deals combat damage to a player"
            # trigger (`effect_binder._trigger_condition`'s ``filter``) reads
            # exactly these fields, and they'd otherwise be silently dropped
            # here even though the pre-replacement ``event`` above carried them.
            self.state.fire_event(resolved.copy_with(amount=final, target_is_creature=target_is_creature))

        self.apply_replacements(event, on_resolved=_finish)
    def lose_life(self, player: Player, amount: int, cause: str = "effect") -> None:
        """A player loses life (RULE 118-119), outside of the damage system.

        The single choke point for life loss, whatever causes it — damage
        (`deal_damage`, RULE 120.3), a cost paid with life (Phyrexian mana,
        RULE 118.4), or a direct effect (e.g. "target player loses 2 life").
        `cause` is metadata only ("damage" / "cost" / "effect") for
        logging/UI; nothing in the rules distinguishes *why* life was lost
        for trigger purposes, so every path fires the same `LIFE_LOST`
        event — except RULE 728.1a's ``cause="radiation"`` (rad counters'
        own inherent mill trigger, `RadiationMillEffect`), which a player
        can redirect into a life *gain* instead via "You gain life rather
        than lose life from radiation." (Strong, the Brutish Thespian,
        `continuous.has_radiation_life_gain`) — checked here rather than
        through the ordinary `ReplacementEffect`/`apply_replacements`
        machinery, since that only ever rewrites an event's amount, never
        redirects it into a different engine call.
        """
        if amount <= 0:
            return
        if self._life_locked(player):
            # RULE 119.6/611.2b: "your life total can't change" (Teferi's
            # Protection) — a continuous effect that simply forbids the
            # change, not a replacement that rewrites its amount, so it is
            # checked at this choke point rather than via
            # `apply_replacements`.
            return
        if cause == "radiation" and continuous.has_radiation_life_gain(self.state, player):
            self.gain_life(player, amount)
            return
        player.lose_life(amount)
        # Every life-loss path funnels through here (see this method's docstring), so
        # this one event is what `GameState.life_lost_this_turn` is derived from.
        self.state.fire_event(
            GameEvent(EventType.LIFE_LOST, player_id=player.id, amount=amount, cause=cause)
        )
    def destroy(
        self, obj: GameObject, can_be_regenerated: bool = True, by_effect: bool = True,
    ) -> None:
        """RULE 701.6: destroy ``obj`` — replaceable (RULE 616), chiefly by a
        regeneration shield (RULE 701.16, `regenerate`) consuming the event
        instead of letting the permanent reach the graveyard. Not the entry
        point for a *non*-destruction move to the graveyard (sacrifice, 0
        toughness, …) — those go through `put_into_graveyard`/
        `_move_to_graveyard` directly, since RULE 701.16c says regeneration
        never applies to them.

        ``can_be_regenerated=False`` (Wrath of God's "They can't be
        regenerated.") skips the replacement pass entirely — a card-specific
        override of RULE 701.16, not RULE 701.16c (which is about sacrifice/
        0-toughness, unrelated to this) — so an existing shield simply
        doesn't get a chance to intercept this particular destroy. A creature
        carrying ``temp_cant_be_regenerated`` ("can't be regenerated this
        turn", `CantBeRegeneratedEffect`) is treated the same way.

        ``by_effect`` is RULE 122.1c's own qualifier: a shield counter replaces destruction
        "as the result of an effect" only, so the RULE 704.5g lethal-damage pass
        (`_sba_check_lethal_damage`, ``by_effect=False``) is not protected by one. It sits
        ahead of the regeneration opt-out because "can't be regenerated" says nothing about a
        shield counter, which isn't regeneration.
        """
        if by_effect and obj.counters.get("shield", 0) > 0:
            self.add_counters(obj, -1, "shield")
            return
        if not can_be_regenerated or getattr(obj, "temp_cant_be_regenerated", False):
            self._move_to_graveyard(obj)
            return
        event = GameEvent(EventType.DESTROY, target_id=obj.instance_id, object=obj.name)

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is not None:
                self._move_to_graveyard(obj)

        self.apply_replacements(event, on_resolved=_finish)
    def regenerate(self, obj: GameObject) -> None:
        """RULE 701.16: give ``obj`` a regeneration shield.

        The next time this turn ``obj`` would be destroyed (`destroy`, e.g.
        via RULE 704.5g lethal damage), the shield replaces that event with:
        remove it from combat, tap it, and remove all damage marked on it —
        instead of moving it to the graveyard. RULE 701.16c: this never
        applies to sacrifice, 0 toughness, or any other non-destruction move
        to the graveyard.

        Consumed on first use; each call adds its own independent shield
        (RULE 701.16a — several activations stack several shields). Any
        shield still unused simply sits in ``replacement_effects`` until
        `GameEngine._step_cleanup` sweeps it at end of turn (RULE 514.2),
        identified by the ``regeneration_shield`` marker so cleanup doesn't
        touch a card's own bind-time replacement effects living in the same
        list.
        """
        effect = ReplacementEffect(
            event_type=EventType.DESTROY,
            replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
            condition=lambda e, c: e.get("target_id") == obj.instance_id,
            source=obj,
            description=f"{obj.name}: Regenerationsschild",
        )
        effect.regeneration_shield = True

        def _replace(event: GameEvent, _context: GameContext) -> Optional[GameEvent]:
            if effect in obj.replacement_effects:
                obj.replacement_effects.remove(effect)
            obj.attacking = False
            obj.combat_defender = None
            obj.blocking = None
            obj.additional_blocking = []
            obj.blocked_by = []
            obj.dealt_deathtouch_damage = False
            obj.tapped = True
            obj.damage_marked = 0
            return None

        effect.replacement_fn = _replace
        obj.replacement_effects.append(effect)
    def heal(self, obj: GameObject) -> int:
        """RULE 701.69a: heal the damage already dealt to ``obj`` — remove
        all marked damage from it. Returns how much was removed (0 if there
        was none, or ``obj`` isn't a permanent that marks damage).

        The narrower "heal N damage" (701.69a's first sentence) isn't a
        shape any card prints — every real use is "heal all damage" / "…is
        healed", the second sentence — so this takes no amount. The
        `-1/-1`-counter removal a caller might also want (regeneration's own
        `_regenerate_replacement` above already does its own
        ``damage_marked = 0``, and infect/wither damage is counters, not
        marked damage, so "heal" per the CR never touches them) stays
        `remove_counters`' job.
        """
        removed = int(getattr(obj, "damage_marked", 0) or 0)
        if removed:
            obj.damage_marked = 0
        return removed
    def put_into_graveyard(self, obj: GameObject) -> None:
        """Move ``obj`` to its owner's graveyard *without* going through
        `destroy` (RULE 701.16c: sacrifice is not destruction and can't be
        replaced by regeneration) — the entry point for a specific,
        already-chosen sacrifice victim (`GameEngine`'s cost-payment
        sacrifice path). `sacrifice`'s own auto-picked effect-driven
        sacrifice (RULE 701.17) uses this too, for the same reason.
        """
        self._move_to_graveyard(obj, cause="sacrifice")
    def sacrifice(self, player: Player, what: str = "permanent", count: "int | str" = 1) -> None:
        """``player`` sacrifices up to ``count`` permanents matching ``what``
        (RULE 701.17) — an effect-driven sacrifice (annihilator, RULE
        702.86), not a cost payment (`GameEngine._sacrifice_candidate`
        handles that separate path, since a cost is paid in one synchronous
        call and can't pause for a chooser — see `GameEngine._pay_activation_
        cost`'s own ``sacrifice_choice``).

        A real interactive choice via `_request_choose_objects` (RULE 601.2c-
        style) rather than an auto-pick: with ``count`` >= however many
        candidates exist there's nothing to decide (every one is taken, same
        as before), but a defending player facing Annihilator on a board
        with more permanents than the trigger demands genuinely gets to
        choose which ones go.

        ``count="all_but_one"`` (Liliana, Dreadhorde General's -9 — "choose
        a permanent of each type and sacrifice the rest", reframed as
        "sacrifice all but one of each type in turn") resolves against the
        *live* candidate count at this call, same "choose which ones go"
        shape as a literal int, just always leaving exactly one behind
        (0 candidates → nothing to do, 1 → nothing to choose, forced).
        """
        candidates = [
            obj
            for obj in self.state.permanents_controlled_by(player.id)
            if _matches_permanent_type(obj, what)
            # "You can't sacrifice those creatures this turn." (Call for Aid)
            and not obj.cant_be_sacrificed_this_turn
        ]
        if count == "all_but_one":
            count = max(0, len(candidates) - 1)
        self._request_choose_objects(
            player, candidates, "sacrifice", count=count,
            prompt="Wähle eine bleibende Karte zum Opfern",
        )
    def exile(self, obj: GameObject) -> None:
        """Move ``obj`` to its owner's exile zone (RULE 406), from anywhere.

        Fires `LEAVES_BATTLEFIELD` when it was in play, then `EXILE`. RULE
        903.9a covers a commander landing in exile exactly like one landing
        in a graveyard — `_flag_commander_zone_choice` marks it for the same
        SBA-offered move to the command zone.
        """
        was_on_battlefield = obj in self.state.battlefield
        # RULE 400.7 / Laelia, the Blade Reforged (PAR-60): the zone this
        # card is leaving, snapshotted before the move for the `EXILE`
        # event's own ``from_zone`` — a "…put into exile from your library
        # and/or your graveyard" trigger needs to know where it came from.
        _from_zone = getattr(getattr(obj, "zone", None), "value", None) or (
            "battlefield" if was_on_battlefield else None
        )
        owner = self.state.player_by_id(obj.owner_id)
        if was_on_battlefield:
            # RULE 603.6a "look back in time" — fire before removal, see
            # `_move_to_graveyard` for the full rationale.
            self.state.fire_event(
                GameEvent(
                    EventType.LEAVES_BATTLEFIELD,
                    # Where it went — "leaves the battlefield without dying" (PAR-119).
                    to_zone="exile",
                    object=obj.name,
                    owner_id=obj.owner_id,
                    controller_id=obj.controller_id,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                    # RULE 603.10a last-known counters — a "for each counter on it" leaves-the-
                    # battlefield trigger of this same object reads them after it is gone.
                    counters=dict(obj.counters),
                    # "…target opponent loses life equal to its power."
                    # (Rapacious Guest-shaped) — snapshotted for the same
                    # RULE 400.7 reason `counters`/`subtypes` are elsewhere
                    # in this module: read via `LoseLifeEffect.
                    # amount_from_trigger_event`, since a live re-lookup
                    # after this fires would see the *new* post-move object.
                    power=obj.power,
                    # MEC-49: the toughness sibling — "you gain life equal to
                    # that creature's toughness" on a DIES trigger (Abattoir
                    # Ghoul), read the same RULE 400.7 last-known way.
                    toughness=obj.toughness,
                )
            )
            self.state.remove_from_battlefield(obj)
        else:
            self._remove_from_current_zone(owner, obj)
        obj.tapped = False
        obj.damage_marked = 0
        owner.add_to_zone(obj, Zone.EXILE)
        self._split_melded_after_move(obj, Zone.EXILE)  # RULE 712.19
        self._flag_commander_zone_choice(obj)
        self.state.fire_event(
            GameEvent(
                EventType.EXILE, object=obj.name, owner_id=obj.owner_id,
                instance_id=obj.instance_id, from_zone=_from_zone,
            )
        )
    def return_to_hand(self, obj: GameObject) -> None:
        """Return ``obj`` to its owner's hand (RULE 701.3 "return"), from
        anywhere — the Unsummon/bounce-land shape. Mirrors `exile`'s "move to
        another zone, from wherever it is" shape: fires `LEAVES_BATTLEFIELD`
        when it was in play. A token bounced this way never really "reaches"
        hand — the next SBA pass's RULE 704.5d stranded-token cleanup
        (`_remove_stranded_tokens`) reaps it the instant it's off the
        battlefield.

        RULE 903.9b: unlike graveyard/exile (903.9a, an *SBA* offered after
        the fact), a commander headed to hand (or library) gets a
        *replacement* choice — conceptually offered before the move, so it
        may never touch hand at all. This MVP applies the same
        default-then-fixup shape `enters_tapped`'s shock-land choice already
        uses: ``obj`` lands in hand as normal (the "declined" outcome) and a
        `commander_zone` `pending_choice` opens immediately to redirect it to
        the command zone if the owner chooses to.
        """
        was_on_battlefield = obj in self.state.battlefield
        owner = self.state.player_by_id(obj.owner_id)
        if was_on_battlefield:
            # RULE 603.6a "look back in time" — fire before removal, see
            # `_move_to_graveyard` for the full rationale.
            self.state.fire_event(
                GameEvent(
                    EventType.LEAVES_BATTLEFIELD,
                    # Where it went — "leaves the battlefield without dying" (PAR-119).
                    to_zone="hand",
                    object=obj.name,
                    owner_id=obj.owner_id,
                    controller_id=obj.controller_id,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                    # RULE 603.10a last-known counters — a "for each counter on it" leaves-the-
                    # battlefield trigger of this same object reads them after it is gone.
                    counters=dict(obj.counters),
                    # "…target opponent loses life equal to its power."
                    # (Rapacious Guest-shaped) — snapshotted for the same
                    # RULE 400.7 reason `counters`/`subtypes` are elsewhere
                    # in this module: read via `LoseLifeEffect.
                    # amount_from_trigger_event`, since a live re-lookup
                    # after this fires would see the *new* post-move object.
                    power=obj.power,
                    # MEC-49: the toughness sibling — "you gain life equal to
                    # that creature's toughness" on a DIES trigger (Abattoir
                    # Ghoul), read the same RULE 400.7 last-known way.
                    toughness=obj.toughness,
                )
            )
            self.state.remove_from_battlefield(obj)
        else:
            self._remove_from_current_zone(owner, obj)
        obj.tapped = False
        obj.damage_marked = 0
        owner.add_to_zone(obj, Zone.HAND)
        self._split_melded_after_move(obj, Zone.HAND)  # RULE 712.19
        if obj.is_commander:
            self.open_choice(self._commander_zone_choice(obj, Zone.HAND))
    def return_to_library(self, obj: GameObject, position: str = "top") -> None:
        """Put ``obj`` on top (default) or the bottom of its owner's library
        (RULE 701.3's "put" — Time Ebb/Griptide/Roil Spout-shaped tempo
        bounce, distinct from `shuffle_into_library`'s "shuffle into", which
        randomizes rather than placing), from anywhere — the same "move to
        another zone, from wherever it is" shape as `return_to_hand`/
        `exile`. RULE 903.9b's commander redirect applies here exactly as it
        does for a commander headed to hand.
        """
        was_on_battlefield = obj in self.state.battlefield
        owner = self.state.player_by_id(obj.owner_id)
        if was_on_battlefield:
            self.state.fire_event(
                GameEvent(
                    EventType.LEAVES_BATTLEFIELD,
                    # Where it went — "leaves the battlefield without dying" (PAR-119).
                    to_zone="library",
                    object=obj.name,
                    owner_id=obj.owner_id,
                    controller_id=obj.controller_id,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                    # RULE 603.10a last-known counters — a "for each counter on it" leaves-the-
                    # battlefield trigger of this same object reads them after it is gone.
                    counters=dict(obj.counters),
                )
            )
            self.state.remove_from_battlefield(obj)
        else:
            self._remove_from_current_zone(owner, obj)
        obj.tapped = False
        obj.damage_marked = 0
        if position == "bottom":
            obj.zone = Zone.LIBRARY
            owner.library.insert(0, obj)
        else:
            owner.add_to_zone(obj, Zone.LIBRARY)  # top (index -1)
        self._split_melded_after_move(obj, Zone.LIBRARY)  # RULE 712.19
        if obj.is_commander:
            self.open_choice(self._commander_zone_choice(obj, Zone.LIBRARY))
    def shuffle_into_library(self, obj: GameObject) -> None:
        """Move ``obj`` into its owner's library, then shuffle (RULE 701.20 —
        Green Sun's Zenith's own trailing "Shuffle ~ into its owner's
        library.", from wherever it currently is, mirroring `return_to_hand`/
        `exile`'s "move to another zone, from wherever it is" shape). Unlike
        `shuffle_hand_and_graveyard_into_library` (a fixed hand+graveyard
        sweep), this moves one named object — typically the resolving spell
        itself, still on the stack when its own last effect runs (RULE
        608.2m: `_apply_stack_item`'s ``obj.zone != Zone.STACK`` check
        already treats *any* self-move away from the stack as an override of
        the default "goes to the graveyard" routing, the same way a trailing
        "Exile ~." self-exile clause does — no special-casing needed here).
        """
        was_on_battlefield = obj in self.state.battlefield
        owner = self.state.player_by_id(obj.owner_id)
        if was_on_battlefield:
            self.state.fire_event(
                GameEvent(
                    EventType.LEAVES_BATTLEFIELD,
                    # Where it went — "leaves the battlefield without dying" (PAR-119).
                    to_zone="library",
                    object=obj.name,
                    owner_id=obj.owner_id,
                    controller_id=obj.controller_id,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                    # RULE 603.10a last-known counters — a "for each counter on it" leaves-the-
                    # battlefield trigger of this same object reads them after it is gone.
                    counters=dict(obj.counters),
                )
            )
            self.state.remove_from_battlefield(obj)
        else:
            self._remove_from_current_zone(owner, obj)
        obj.tapped = False
        obj.damage_marked = 0
        owner.add_to_zone(obj, Zone.LIBRARY)
        self._split_melded_after_move(obj, Zone.LIBRARY)  # RULE 712.19
        self.shuffle_library(owner)
    def blink(self, obj: GameObject, controller: Optional[Player] = None) -> None:
        """Exile ``obj``, then immediately return it to the battlefield under
        its owner's control (RULE 400.7's "leaves and re-enters" — Ephemerate/
        Momentary Blink-shaped "exile target permanent, then return it").

        Reuses `exile` (a real zone visit, so `LEAVES_BATTLEFIELD`/`EXILE`
        fire like any other exile) then `_put_searched_card`'s battlefield-
        entry handling — the same choke point `return_from_graveyard` uses —
        so the object re-enters as a fresh `ENTERS_BATTLEFIELD` occurrence
        (RULE 400.7: a new object, ETB triggers refire, summoning sickness
        resets) rather than a no-op move.

        ``controller``, when given, is Restoration Angel's own "return that
        card to the battlefield **under your control**" shape — the caster,
        not necessarily the owner (`return_from_graveyard`'s own
        ``controller_id`` param is the graveyard-recursion sibling of this
        same idea). Every real card in this shape also restricts its target
        to "creature **you control**", so ``controller`` and ``owner`` are
        the same player in the overwhelming majority of games; the param
        exists for the rarer case (a control-stolen creature) where they
        aren't. Omitted (the default), this is plain blink: always under
        the owner's own control, since no ordinary blink spell lets the
        caster keep an opponent's creature.
        """
        owner = self.state.player_by_id(obj.owner_id)
        new_controller = controller or owner
        # RULE 400.7: a new object remembers nothing of the old one — unlike
        # `exile` on its own (which leaves counters/attachments alone, e.g.
        # for a card that's merely *staying* in exile), drop everything
        # before re-entry. `exile` doesn't call `_detach_attachments_from`
        # itself (only `_move_to_graveyard` does today), so any Aura/
        # Equipment that was on ``obj`` falls off here.
        self._detach_attachments_from(obj)
        self.exile(obj)
        # `exile()` appended ``obj`` onto `owner.exile`; `_put_searched_card`'s
        # battlefield branch only appends to `state.battlefield` (its usual
        # callers already popped the card off whatever zone held it), so
        # without this it would linger in `owner.exile` too — a phantom
        # duplicate reference (the object's own `.zone` reads BATTLEFIELD
        # correctly either way, but the exile *zone list* itself wouldn't).
        owner.remove_from_zone(obj, Zone.EXILE)
        obj.reset_as_new_object()
        obj.controller_id = new_controller.id
        self._put_searched_card(new_controller, obj, "battlefield")
    def return_from_graveyard(
        self,
        obj: GameObject,
        destination: str = "battlefield",
        controller_id: Optional[str] = None,
        transformed: bool = False,
    ) -> None:
        """Return ``obj`` from a graveyard to ``destination`` (RULE 701.3,
        the Regrowth/Reanimate-shaped recursion family).

        Reuses `_put_searched_card`'s battlefield-entry handling (the same
        choke point RULE 701.19's search-to-battlefield destination uses) so
        a reanimated permanent's `ENTERS_BATTLEFIELD` triggers fire exactly
        like a tutored one's, rather than reimplementing that zone-entry
        machinery here.

        ``controller_id``, when given, is the Reanimate/Virtue of
        Persistence "put … onto the battlefield **under your control**"
        shape: ``obj`` enters under that player's control (stamped onto
        ``obj.controller_id`` before the battlefield add, so triggers/layer
        effects see it too) instead of its owner's — real Magic only ever
        pairs this with ``destination="battlefield"``, never "hand" (a card
        can't go to a hand that isn't its owner's).

        ``transformed`` (RULE 400.7 + RULE 712.8, Bruce Banner-shaped "return
        this card to the battlefield transformed") flips ``obj`` onto its
        back face (`transform_permanent`) right after it lands — mirroring
        `exile_return_transformed`'s "new object enters already transformed"
        treatment, just sourced from a graveyard instead of an exile-and-
        blink; only meaningful with a battlefield-shaped ``destination``,
        and a no-op flip for a card with no back face at all
        (`transform_permanent` already handles that gracefully).

        RULE 400.7: leaving the graveyard makes this a new object regardless
        of destination — `GameObject.reset_as_new_object` drops whatever it
        died with (most visibly counters: a creature that died with +1/+1
        counters must not bring them back via Reanimate/Regrowth) before it
        lands anywhere.
        """
        owner = self.state.player_by_id(obj.owner_id)
        self._remove_from_current_zone(owner, obj)
        obj.reset_as_new_object()
        if controller_id is not None and destination in ("battlefield", "battlefield_tapped"):
            obj.controller_id = controller_id
            self._put_searched_card(self.state.player_by_id(controller_id), obj, destination)
        else:
            # RULE 108.4: absent an explicit new controller, a new object
            # defaults to its owner's control — ``obj.controller_id`` could
            # otherwise still read a stale prior controller (e.g. it died
            # while under a "gain control" effect; `_move_to_graveyard`
            # never resets this field, since most graveyard visits aren't
            # followed by a return at all).
            obj.controller_id = owner.id
            self._put_searched_card(owner, obj, destination)
        if transformed and destination in ("battlefield", "battlefield_tapped"):
            self.transform_permanent(obj)
    def return_dies_as_new_permanent(
        self,
        obj: GameObject,
        new_type_line: str,
        new_oracle_text: str,
        attach_to: Optional[GameObject] = None,
    ) -> None:
        """RULE 400.7: "When ~ dies, return it to the battlefield. It's a[n]
        <type> with '<ability>'. ~ loses all other abilities." (Harold and
        Bob, First Numens) — a *different* card entirely, not RULE 712.8's
        ordinary "return transformed" (`return_from_graveyard(transformed=
        True)`/`exile_return_transformed`, both of which need a real
        printed back face): ``obj`` becomes a synthetic `Card` built here
        from ``new_type_line``/``new_oracle_text`` — same name/owner/set,
        everything else is now this new printed text. "Loses all other
        abilities" is made literal by simply never re-attaching the old
        card's catalogue specs (`effect_binder.bind_from_catalogue` is only
        ever called once, when a `GameObject` is first built — this method
        doesn't call it again) — only whatever the new oracle text itself
        implies (a plain mana ability is read live off it,
        `game/mana_abilities.py`; anything needing catalogue/parser
        specs would need an explicit re-bind, not needed by the one real
        card using this shape today.

        ``attach_to``, when given, is stamped directly onto the returned
        object (RULE 303.4a's own "target what it will enchant" — already
        resolved by the calling effect's own target choice before this
        runs, mirroring `AttachEffect`).

        Reuses `return_from_graveyard`'s own `_remove_from_current_zone` +
        `reset_as_new_object` + `_put_searched_card` sequence, just with
        the card swap slotted in between the identity reset and the
        battlefield add, so `ENTERS_BATTLEFIELD`'s own ``object_types``
        payload already reflects the new permanent type.
        """
        owner = self.state.player_by_id(obj.owner_id)
        self._remove_from_current_zone(owner, obj)
        obj.reset_as_new_object()
        obj.controller_id = owner.id
        obj.card = Card(
            id=obj.card.id,
            name=obj.card.name,
            type_line=new_type_line,
            oracle_text=new_oracle_text,
            set_code=obj.card.set_code,
        )
        # "~ loses all other abilities" — unlike an ordinary blink/return-
        # transformed object (`reset_as_new_object`'s own docstring: bound-
        # once abilities are deliberately left alone there, since they'd
        # come back byte-identical from a re-bind), this card's own printed
        # text says the *old* card's abilities are gone for good, not just
        # not-yet-rebound. Clears every bind-on-load field so nothing of
        # the original creature (vigilance/reach, the DIES trigger itself)
        # lingers on the new permanent.
        obj.triggered_abilities = []
        obj.activated_abilities = []
        obj.static_effects = []
        obj.replacement_effects = []
        obj.intrinsic_keywords = set()
        obj.parametric_keywords = {}
        # RULE 702 keywords printed in the new text (here, just "Enchant
        # Forest you control") are docked structurally — via the same
        # `attach_keyword` an ordinary bind-on-load uses — even though no
        # other ability rebinds: RULE 704.5m/n's own re-validation
        # (`_revalidate_attachments`) reads `parametric_keywords["enchant"]`
        # to tell a real Aura attachment from an illegal one, and that has
        # to see this permanent's new "enchant" quality, not the old
        # creature's (cleared) keyword set.
        from ..binding.core import attach_keyword

        for kw_spec in parse_keywords(obj.card):
            attach_keyword(obj, kw_spec)
        if attach_to is not None:
            obj.attached_to = attach_to.instance_id
        self._put_searched_card(owner, obj, "battlefield")
    @staticmethod
    def _life_locked(player: Player) -> bool:
        """RULE 119.6: "your life total can't change" (Teferi's Protection),
        a marker on `Player.player_effects` — see `PlayerShieldEffect`."""
        return any(getattr(e, "player_life_locked", False) for e in player.player_effects)

    @staticmethod
    def _max_life_total(player: Player) -> Optional[int]:
        """MEC-54: the tightest "your maximum life total is N" cap in force
        on ``player`` (You Compleat Me), or ``None``. A duck-typed marker on
        `Player.player_effects` (`max_life_total` attr), the `player_life_
        locked` idiom; permanent ("for the rest of the game")."""
        caps = [
            int(getattr(e, "max_life_total"))
            for e in player.player_effects
            if getattr(e, "max_life_total", None) is not None
        ]
        return min(caps) if caps else None

    def set_max_life_total(self, player: Player, cap: int) -> None:
        """RULE 119-adjacent (MEC-54): install a permanent "your maximum life
        total is ``cap``" effect and clamp a currently-higher total down to
        it at once (You Compleat Me's own "…it becomes 10." rider handles
        the same clamp for the exact-10 case, but this stands on its own)."""
        player.player_effects.append(_MaxLifeTotalMarker(cap))
        if player.life > cap:
            player.lose_life(player.life - cap)
    @staticmethod
    def _player_protected_from_everything(player: Player) -> bool:
        """RULE 702.16e: "you gain protection from everything" (Teferi's
        Protection) — for a *player* this reduces to "can't be dealt
        damage", the only half a player can actually be subject to here."""
        return any(
            getattr(e, "player_protected_from_everything", False)
            for e in player.player_effects
        )
    @staticmethod
    def _player_protected_from_source_controller(player: Player, source: GameObject) -> bool:
        """RULE 702.16e-adjacent: "you gain protection from [that player]"
        (Noble Heritage, MEC-62) — the single-player-scoped sibling of
        `_player_protected_from_everything`: only damage from a source
        ``player`` doesn't control but the *protected-from* player does is
        prevented, read off each `PlayerShieldEffect.protected_from_
        player_id` marker."""
        source_controller = getattr(source, "controller_id", None)
        if source_controller is None:
            return False
        return any(
            getattr(e, "protected_from_player_id", None) == source_controller
            for e in player.player_effects
        )
    def gain_life(self, player: Player, amount: int) -> None:
        if amount <= 0:
            return
        if self._life_locked(player):
            return  # RULE 119.6 — see `lose_life`
        # "Players can't gain life." (Everlasting Torment / Forsaken Wastes /
        # Leyline of Punishment) — a standing board-wide rule modification,
        # read live off the battlefield (`continuous.life_gain_globally_
        # prohibited`); cancels the gain outright, no replacement/event.
        if continuous.life_gain_prohibited_for(self.state, player):
            return
        # RULE 119.3/616.1: a life gain is routed through `apply_replacements`
        # first, so a "you gain that much life plus N / twice that much
        # instead" replacement (Angel of Vitality/Boon Reflection) can
        # rewrite the amount before any life lands — mirroring `deal_damage`/
        # `add_counters`'s own pre-event replacement hook. With no such
        # replacement active (the overwhelmingly common case) `_finish` runs
        # synchronously with the unchanged amount, exactly as before.
        event = GameEvent(EventType.LIFE_GAIN, player_id=player.id, amount=amount)

        def _finish(resolved: Optional[GameEvent]) -> None:
            if resolved is None:
                return
            final = int(resolved.get("amount", amount) or 0)
            # MEC-54: "your maximum life total is N." (You Compleat Me) — a
            # gain can raise the total only up to the cap, never past it.
            cap = self._max_life_total(player)
            if cap is not None:
                final = min(final, max(cap - player.life, 0))
            if final <= 0:
                return
            player.gain_life(final)
            self.state.fire_event(
                GameEvent(EventType.LIFE_GAINED, player_id=player.id, amount=final)
            )

        self.apply_replacements(event, on_resolved=_finish)

    def prevent_life_gain_this_turn(self, players: list[Player]) -> None:
        """RULE 119.3/616.1: "`<players>` can't gain life this turn."
        (Roiling Vortex — an activated-ability rider, not a static; Erebos,
        God of the Dead prints the same clause as a standing "as long as
        devotion" static instead, a separate, unbuilt shape). A turn-scoped
        `ReplacementEffect` per player on `Player.player_effects`, the same
        home/sweep idiom `prevent_damage_to_player` uses — cancels the
        `LIFE_GAIN` pre-event outright (``None``, not a reduced amount:
        RULE 119.3's "can't gain life" is absolute, no partial-prevention
        bank to track) rather than reusing that method's own numeric-shield
        shape, which doesn't fit "no gain at all, however much is offered".
        """
        for player in players:
            effect = ReplacementEffect(
                event_type=EventType.LIFE_GAIN,
                replacement_fn=lambda e, c: None,
                condition=lambda e, c, pid=player.id: e.get("player_id") == pid,
                description=f"{player.name}: kann kein Leben dazugewinnen",
            )
            effect.life_gain_prevention_shield = True
            player.player_effects.append(effect)

    def prevent_damage_to_player(
        self,
        player: Player,
        amount: Union[int, str] = "all",
        watched_source_id: Optional[int] = None,
        rider: Optional[dict] = None,
        combat_only: bool = False,
        source_filter: Optional[dict] = None,
    ) -> None:
        """RULE 615: grant ``player`` a turn-scoped damage-prevention shield
        (Riot Control's "all", Thought Lash's repeatable "the next 1") —
        Regenerate-shaped (a `ReplacementEffect` built and attached at
        resolve time, not bind time), but player- rather than object-scoped:
        it lives on `Player.player_effects` (already `_all_replacement_
        effects`'s second collection source, see `regenerate` for the
        permanent-scoped sibling) since nothing is being regenerated here.

        ``amount="all"`` prevents every point of damage dealt to ``player``
        for the rest of the turn and never self-removes (an "all" shield
        has no bank to exhaust). An int opens a cumulative bank of that
        many points, spent (possibly across several `EventType.DAMAGE`
        events) until exhausted, then self-removes — Thought Lash's own
        activated ability can be paid more than once a turn, each call
        opening an *independent* shield exactly like `regenerate`'s own
        multiple-activations-stack behaviour. Either shape is swept at
        cleanup regardless of remaining balance (RULE 514.2 "this turn"
        expiry) by `GameEngine._step_cleanup`'s `damage_prevention_shield`
        marker check, mirroring the existing unused-regeneration-shield
        sweep.

        ``watched_source_id`` (RULE 615/616.1d's "the next time **a source
        of your choice** would deal damage to you this turn" — the Circle of
        Protection/Rune of Protection family) narrows the shield to one
        specific source instance, matched against the `DAMAGE` event's own
        ``source_id`` — the shield still self-expires/gets swept exactly as
        before even if that source never actually deals damage this turn.
        ``rider`` fires a follow-up off the real prevented amount — see
        `apply_prevent_rider` (Deflecting Palm/Reverse Damage-shaped).

        ``combat_only`` (Inkshield — "Prevent all combat damage that would be
        dealt to you this turn") narrows the shield to RULE 510 combat
        damage, checked against the `DAMAGE` event's own ``combat`` flag the
        same way `prevent_all_combat_damage_this_turn` does.

        ``source_filter`` (PAR-78 — "…by creatures"/"…by sources you don't
        control"/…) narrows the shield to damage from a matching source,
        via `_damage_source_matches` (checked against this player's own id
        for the ``"controller"`` key).
        """
        remaining = None if amount == "all" else int(amount)
        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
            condition=lambda e, c: (
                bool(e.get("is_player")) and e.get("target_id") == player.id
                and (watched_source_id is None or e.get("source_id") == watched_source_id)
                and (not combat_only or bool(e.get("combat")))
                and _damage_source_matches(c.state, e, source_filter, player.id)
            ),
            description=f"{player.name}: Schadensverhinderung",
        )
        effect.damage_prevention_shield = True
        effect.prevents_damage = True  # MEC-30: "damage can't be prevented" filter

        def _replace(event: GameEvent, context: Any) -> Optional[GameEvent]:
            nonlocal remaining
            dealt = int(event.get("amount", 0) or 0)
            if remaining is None:
                prevented = dealt
            else:
                prevented = min(remaining, dealt)
                remaining -= prevented
                if remaining <= 0 and effect in player.player_effects:
                    player.player_effects.remove(effect)
            self.apply_prevent_rider(rider, prevented, event, player.id)
            if remaining is None:
                return None  # "all" — every point prevented, shield persists
            new_amount = dealt - prevented
            return event.copy_with(amount=new_amount) if new_amount > 0 else None

        effect.replacement_fn = _replace
        player.player_effects.append(effect)

    def grant_cant_lose_this_turn(self, player: Player) -> None:
        """RULE 104.3a: "You can't lose the game this turn." (Angel's
        Grace, MEC-43 round 4E) — reuses the existing `WinConditionEffect`/
        `_loss_prevented` machinery (built for a *permanent's* standing
        "you can't lose" static, e.g. Platinum Angel) by installing one
        directly onto ``player``'s own `player_effects`, turn-scoped
        instead of standing (swept at the next cleanup by
        `GameEngine._step_cleanup`'s ``win_condition_grant`` marker check,
        the same "this turn" idiom `prevent_damage_to_player`'s own
        ``damage_prevention_shield`` marker above already uses).
        """
        effect = WinConditionEffect(condition_type="prevent_loss")
        effect.win_condition_grant = True
        player.player_effects.append(effect)

    def cap_damage_life_floor(self, player: Player, floor: int = 1) -> None:
        """RULE 104.3a's damage-floor half of Angel's Grace: "Until end of
        turn, damage that would reduce your life total to less than
        `floor` reduces it to `floor` instead." A turn-scoped `Player.
        player_effects` replacement, `prevent_damage_to_player` (RULE 615)
        -shaped — same player-scoped condition and cleanup-marker idiom —
        but rewriting the amount to land exactly on ``floor`` rather than
        subtracting a prevented chunk.

        **Documented simplification**: doesn't chase the rare corner case
        of a life total already below ``floor`` from a *non-damage* cause
        (paying life as a cost, say) when the next damage event fires this
        turn — real Magic lets Angel's Grace raise your life back up to 1
        in that case, but `deal_damage`'s shared ``_finish`` closure drops
        any non-positive replaced amount before this replacement's own
        caller ever sees it, and no card in this project's cache needs
        that corner case reachable without deliberately contriving it.
        """
        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=lambda e, c: e,
            condition=lambda e, c: bool(e.get("is_player")) and e.get("target_id") == player.id,
            description=f"{player.name}: Lebenspunkte-Untergrenze {floor}",
        )
        effect.damage_life_floor_grant = True

        def _replace(event: GameEvent, context: Any) -> Optional[GameEvent]:
            dealt = int(event.get("amount", 0) or 0)
            if dealt <= 0:
                return event
            would_be = player.life - dealt
            if would_be >= floor:
                return event
            capped = player.life - floor
            return event.copy_with(amount=capped) if capped > 0 else None

        effect.replacement_fn = _replace
        player.player_effects.append(effect)

    def prevent_damage_to_player_and_their_creatures(
        self,
        player: Player,
        amount: Union[int, str] = "all",
        watched_source_id: Optional[int] = None,
        rider: Optional[dict] = None,
        scope: str = "creatures",
        source_filter: Optional[dict] = None,
    ) -> None:
        """RULE 615/616.1d's "…would deal damage to you **and/or creatures
        you control** this turn" (Shadowbane, MEC-30) — the recipient-union
        sibling of `prevent_damage_to_player` just above: same one-chosen-
        source shield shape, but the condition matches *either* ``player``
        themself *or* any permanent of ``scope`` they currently control
        (checked live — control can change mid-turn), instead of one fixed
        id. ``scope="creatures"`` (the original, Shadowbane-shaped) or
        ``"permanents"`` (PAR-78 — "…you and **permanents** you control
        this turn" — Endure/Channel Harm).

        ``source_filter`` (PAR-78) — see `prevent_damage_to_player`.
        """
        remaining = None if amount == "all" else int(amount)

        def _condition(e: GameEvent, c: Any) -> bool:
            if watched_source_id is not None and e.get("source_id") != watched_source_id:
                return False
            if not _damage_source_matches(c.state, e, source_filter, player.id):
                return False
            if e.get("is_player"):
                return e.get("target_id") == player.id
            target_obj = c.state.find_object(e.get("target_id"))
            if target_obj is None or target_obj.controller_id != player.id:
                return False
            return target_obj.is_creature if scope == "creatures" else True

        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
            condition=_condition,
            description=f"{player.name}: Schadensverhinderung",
        )
        effect.damage_prevention_shield = True
        effect.prevents_damage = True  # MEC-30: "damage can't be prevented" filter

        def _replace(event: GameEvent, context: Any) -> Optional[GameEvent]:
            nonlocal remaining
            dealt = int(event.get("amount", 0) or 0)
            if remaining is None:
                prevented = dealt
            else:
                prevented = min(remaining, dealt)
                remaining -= prevented
                if remaining <= 0 and effect in player.player_effects:
                    player.player_effects.remove(effect)
            self.apply_prevent_rider(rider, prevented, event, player.id)
            if remaining is None:
                return None
            new_amount = dealt - prevented
            return event.copy_with(amount=new_amount) if new_amount > 0 else None

        effect.replacement_fn = _replace
        player.player_effects.append(effect)

    def prevent_damage_to_target(
        self,
        target: Any,
        amount: Union[int, str] = "all",
        watched_source_id: Optional[int] = None,
        rider: Optional[dict] = None,
        source_filter: Optional[dict] = None,
        shield_controller_id: Optional[str] = None,
    ) -> None:
        """RULE 615, the *any-target* sibling of `prevent_damage_to_player`
        (PAR-15's "prevent the next N damage ... to any number of targets,
        divided as you choose" — Embolden/Remedy/Angel of Salvation): a
        turn-scoped shield for whichever single target (player *or*
        permanent) a divided prevention pool was allotted to.

        ``target`` may be a `Player` (shield lives on `Player.player_effects`,
        swept by `GameEngine._step_cleanup`'s existing `damage_prevention_
        shield` pass) or a `GameObject` (shield lives on its own
        `replacement_effects`, swept by that same method's per-permanent
        loop — see the `regeneration_shield` sweep it sits beside). Same
        cumulative-bank semantics as the player-only method.

        ``watched_source_id``/``rider`` — see `prevent_damage_to_player`
        (Kithkin Armor's "a source of your choice" shielding *enchanted
        creature* rather than a player is what needs this sibling instead
        of the player-only method).
        """
        is_player = isinstance(target, Player)
        target_id = target.id if is_player else target.instance_id
        protected_player_id = target.id if is_player else target.controller_id
        remaining = None if amount == "all" else int(amount)
        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
            condition=lambda e, c: (
                bool(e.get("is_player")) == is_player and e.get("target_id") == target_id
                and (watched_source_id is None or e.get("source_id") == watched_source_id)
                and _damage_source_matches(c.state, e, source_filter, protected_player_id)
            ),
            description="Schadensverhinderung",
        )
        effect.damage_prevention_shield = True
        effect.prevents_damage = True  # MEC-30: "damage can't be prevented" filter
        holder = target.player_effects if is_player else target.replacement_effects

        def _replace(event: GameEvent, context: Any) -> Optional[GameEvent]:
            nonlocal remaining
            dealt = int(event.get("amount", 0) or 0)
            if remaining is None:
                prevented = dealt
            else:
                prevented = min(remaining, dealt)
                remaining -= prevented
                if remaining <= 0 and effect in holder:
                    holder.remove(effect)
            # ``shield_controller_id``: whose "you" a rider means — the spell's controller (PAR-139, "you gain
            # life equal to the damage prevented"), not necessarily the shielded permanent's.
            self.apply_prevent_rider(
                rider, prevented, event,
                shield_controller_id or (target_id if is_player else getattr(target, "controller_id", None)),
            )
            if remaining is None:
                return None  # "all" — every point prevented, shield persists
            new_amount = dealt - prevented
            return event.copy_with(amount=new_amount) if new_amount > 0 else None

        effect.replacement_fn = _replace
        holder.append(effect)

    def _request_prevent_damage_chosen_color(
        self, player: Player, recipient: Any, amount: Union[int, str] = "all",
    ) -> None:
        """RULE 615/616.1d's "sources of **the color of your choice**"
        (Avacyn, Guardian Angel, PAR-78) — genuinely different from
        `RequestPreventDamageSourceEffect`'s "**a source** of your choice"
        (Circle of Protection family): the shield here matches *every*
        source of a chosen colour for the rest of the turn, not one
        specific permanent, so there is no object to open `_request_choose_
        objects`'s chooser over.

        Also distinct from RULE 601.2b's own ``"choose_color"`` kind
        (`casting_mixin._offer_enter_choices`): that one only ever fires
        once, as a permanent enters, and stamps `GameObject.chosen_color`
        for its whole battlefield lifetime. Avacyn's colour is picked fresh
        at *each* activation, so it can't reuse that stamp — this opens its
        own ``"prevent_damage_chosen_color"`` choice instead and, once
        answered, feeds the pick straight into `prevent_damage_to_player`/
        `_to_target`'s existing ``source_filter={"color": …}`` key (PAR-78)
        rather than adding a new filter shape.
        """
        recipient_is_player = isinstance(recipient, Player)
        self.open_choice({
            "kind": "prevent_damage_chosen_color",
            "player_id": player.id,
            "prompt": "Farbe wählen",
            "options": [{"id": color, "label": label} for color, label in self._ANY_COLOR_LABELS.items()],
            "recipient_id": recipient.id if recipient_is_player else recipient.instance_id,
            "recipient_is_player": recipient_is_player,
            "amount": amount,
        })

    @continuations.choice(
        "prevent_damage_chosen_color", answer=continuations.ANSWER_STR, rule="615",
    )
    def _resume_prevent_damage_chosen_color(
        self, choice: dict[str, Any], answer: Optional[str]
    ) -> None:
        """Answer a pending `prevent_damage_chosen_color` choice, then open
        the shield for whichever colour was picked. Mandatory (no decline
        offered) — an unrecognized/missing answer defaults to the first
        offered colour, the same fallback RULE 601.2b's own colour choice
        (`casting_mixin._resume_choose_creature_type`) gives a skipped pick.
        """
        options = choice["options"]
        valid_ids = {str(o["id"]) for o in options}
        chosen = str(answer) if answer is not None and str(answer) in valid_ids else (
            str(options[0]["id"]) if options else None
        )
        if chosen is None:
            return
        amount = choice.get("amount", "all")
        if choice.get("recipient_is_player"):
            recipient = self.state.player_by_id(choice["recipient_id"])
            if recipient is not None:
                self.prevent_damage_to_player(recipient, amount, source_filter={"color": chosen})
        else:
            recipient = self._object_by_instance_id(choice["recipient_id"])
            if recipient is not None:
                self.prevent_damage_to_target(recipient, amount, source_filter={"color": chosen})

    def redirect_damage_from_source(
        self, source: GameObject, new_recipient: Any, amount: Union[int, str] = "all",
    ) -> None:
        """RULE 616.1c "the next time a source of your choice would deal
        damage this turn, that damage is dealt to `<X>` instead" (Opal-Eye,
        Konda's Yojimbo, MEC-30) — the redirect sibling of `prevent_damage_
        from_source`: same one-watched-source shield shape, but rewrites
        the `DAMAGE` event's own recipient (``target_id``/``is_player``)
        instead of reducing ``amount``, so the damage still happens, just to
        someone else. Deliberately **not** marked `prevents_damage` — a
        redirect isn't a prevention (RULE 615 doesn't apply to it at all),
        so "damage can't be prevented this turn" must not block it.

        Filed on ``source``'s own controller's `player_effects`, same home
        `prevent_damage_from_source` uses, swept by the same `damage_
        prevention_shield` cleanup pass (the flag still drives cleanup
        timing even though this isn't a prevention effect semantically).
        """
        controller = self.state.player_by_id(source.controller_id) if source.controller_id else None
        if controller is None:
            return
        watched_source_id = source.instance_id
        remaining = None if amount == "all" else int(amount)
        new_is_player = not hasattr(new_recipient, "instance_id")
        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
            condition=lambda e, c: e.get("source_id") == watched_source_id,
            description=f"{source.name}: Schadensumleitung",
        )
        effect.damage_prevention_shield = True

        def _replace(event: GameEvent, context: Any) -> Optional[GameEvent]:
            nonlocal remaining
            dealt = int(event.get("amount", 0) or 0)
            if remaining is not None:
                redirected = min(remaining, dealt)
                remaining -= redirected
                if remaining <= 0 and effect in controller.player_effects:
                    controller.player_effects.remove(effect)
            else:
                redirected = dealt
            if redirected <= 0:
                return event
            leftover = dealt - redirected
            if leftover > 0:
                # A finite redirect budget can be exhausted mid-event: the
                # un-redirected remainder still hits the original recipient
                # as ordinary damage, since one replaced event can only
                # carry a single recipient — this replacement's own budget
                # is already spent (removed above) so the recursive event
                # below can't loop back through it.
                original_is_player = bool(event.get("is_player", False))
                original_target_id = event.get("target_id")
                original_target = (
                    self.state.player_by_id(original_target_id) if original_is_player
                    else self.state.find_object(original_target_id)
                )
                if original_target is not None:
                    self.deal_damage(
                        original_target, leftover, source=source, combat=bool(event.get("combat", False)),
                    )
            overrides: dict[str, Any] = {
                "amount": redirected,
                "target_id": new_recipient.id if new_is_player else new_recipient.instance_id,
                "is_player": new_is_player,
            }
            if not new_is_player:
                overrides["target_controller_id"] = new_recipient.controller_id
            return event.copy_with(**overrides)

        effect.replacement_fn = _replace
        controller.player_effects.append(effect)

    def redirect_damage_from_target(
        self, protected: GameObject, new_recipient: Any, amount: Union[int, str] = "all",
    ) -> None:
        """Redirect the next damage headed to one permanent (en-Kor).

        Unlike :meth:`redirect_damage_from_source`, the watched side of the
        DAMAGE event is its recipient.  This is a redirect, not prevention,
        and a finite shield can split one event exactly like the source-based
        sibling above.
        """
        controller = self.state.player_by_id(protected.controller_id) if protected.controller_id else None
        if controller is None:
            return
        protected_id = protected.instance_id
        remaining = None if amount == "all" else int(amount)
        new_is_player = not hasattr(new_recipient, "instance_id")
        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=lambda e, c: e,
            condition=lambda e, c: not e.get("is_player") and e.get("target_id") == protected_id,
            description=f"{protected.name}: Schadensumleitung",
        )
        effect.damage_prevention_shield = True

        def _replace(event: GameEvent, context: Any) -> Optional[GameEvent]:
            nonlocal remaining
            dealt = int(event.get("amount", 0) or 0)
            redirected = dealt if remaining is None else min(remaining, dealt)
            if remaining is not None:
                remaining -= redirected
                if remaining <= 0 and effect in controller.player_effects:
                    controller.player_effects.remove(effect)
            if redirected <= 0:
                return event
            leftover = dealt - redirected
            if leftover > 0:
                self.deal_damage(protected, leftover, source=self.state.find_object(event.get("source_id")), combat=bool(event.get("combat", False)))
            overrides: dict[str, Any] = {
                "amount": redirected,
                "target_id": new_recipient.id if new_is_player else new_recipient.instance_id,
                "is_player": new_is_player,
            }
            if not new_is_player:
                overrides["target_controller_id"] = new_recipient.controller_id
            return event.copy_with(**overrides)

        effect.replacement_fn = _replace
        controller.player_effects.append(effect)

    def prevent_damage_from_source(
        self, source: GameObject, amount: Union[int, str] = "all", rider: Optional[dict] = None,
    ) -> None:
        """RULE 615/616.1d's *unscoped-recipient* one-shot shield — "the next
        time **target creature** would deal damage this turn, prevent that
        damage" (Awe Strike/Dazzling Reflection, ``source`` already pinned by
        ordinary RULE 115 targeting, no "of your choice" chooser needed) and
        Desperate Gambit's "a source you control" chooser sibling. Protects
        *whoever* ``source`` would have hit, not one fixed recipient — the
        mirror image of `prevent_damage_to_target`, which fixes the recipient
        and (optionally) narrows the source; this fixes the source and never
        narrows the recipient.

        Filed on ``source``'s own controller's `player_effects` (an
        arbitrary but consistent home — the condition itself doesn't check
        "to", so whose list it sits on doesn't change what it does), swept
        by the same `damage_prevention_shield` cleanup pass.
        """
        controller = self.state.player_by_id(source.controller_id) if source.controller_id else None
        if controller is None:
            return
        watched_source_id = source.instance_id
        remaining = None if amount == "all" else int(amount)
        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
            condition=lambda e, c: e.get("source_id") == watched_source_id,
            description=f"{source.name}: Schadensverhinderung",
        )
        effect.damage_prevention_shield = True
        effect.prevents_damage = True  # MEC-30: "damage can't be prevented" filter

        def _replace(event: GameEvent, context: Any) -> Optional[GameEvent]:
            nonlocal remaining
            dealt = int(event.get("amount", 0) or 0)
            if remaining is None:
                prevented = dealt
            else:
                prevented = min(remaining, dealt)
                remaining -= prevented
                if remaining <= 0 and effect in controller.player_effects:
                    controller.player_effects.remove(effect)
            self.apply_prevent_rider(rider, prevented, event, controller.id)
            if remaining is None:
                return None  # "all" — every point prevented, shield persists
            new_amount = dealt - prevented
            return event.copy_with(amount=new_amount) if new_amount > 0 else None

        effect.replacement_fn = _replace
        controller.player_effects.append(effect)

    def grant_damage_multiplier_from_source(
        self, source: GameObject, multiplier: int = 2,
    ) -> None:
        """RULE 616's *single-source-scoped* damage-doubling shield —
        Desperate Gambit's coin-flip "win" branch (MEC-30): "the next time
        **that source** would deal damage this turn, it deals double that
        damage instead." The doubling mirror of `prevent_damage_from_
        source` just above (same ``condition=lambda e, c: e.get(
        "source_id") == watched_source_id`` shape, same "float on the
        source's own controller's `player_effects`" home), *not*
        `grant_damage_multiplier_this_turn`'s controller-wide `your_
        sources_only` — that flag doubles *every* source the controller
        has, whereas this narrows to one already-chosen permanent, the
        same distinction `prevent_damage_from_source` already draws
        against the standing, unscoped `_double_damage_replacement`
        factory. Marked `damage_multiplier_grant` (not `damage_prevention_
        shield`), the same cleanup-sweep marker `grant_damage_multiplier_
        this_turn` uses, since this isn't a prevention effect and must
        never be filtered by `disable_damage_prevention_this_turn`.
        """
        controller = self.state.player_by_id(source.controller_id) if source.controller_id else None
        if controller is None:
            return
        watched_source_id = source.instance_id
        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
            condition=lambda e, c: e.get("source_id") == watched_source_id,
            description=f"{source.name}: Schadensverdopplung",
        )
        effect.damage_multiplier_grant = True

        def _replace(event: GameEvent, context: Any) -> Optional[GameEvent]:
            dealt = int(event.get("amount", 0) or 0)
            if dealt <= 0:
                return event
            return event.copy_with(amount=dealt * multiplier)

        effect.replacement_fn = _replace
        controller.player_effects.append(effect)

    def apply_prevent_rider(
        self,
        rider: Optional[dict],
        prevented: int,
        event: GameEvent,
        shield_controller_id: Optional[str],
        shield_source: Optional[GameObject] = None,
    ) -> None:
        """Fire a "…and `<X>` this way" follow-up (RULE 616.1-adjacent) off
        the *actual* amount a `prevent_damage`/`prevent_damage_to_*`/
        `prevent_damage_from_source` shield just stopped — Swans of Bryn
        Argoll's "the source's controller draws that many cards", Deflecting
        Palm's "deals that much damage to that source's controller", Nine
        Lives's "…and put an incarnation counter on this enchantment", and
        siblings. Mirrors `_prevent_damage_convert_counters_replacement`'s
        (`game/effects/core.py`) established pattern of calling an ordinary
        engine method mid-replacement with the real computed amount, rather
        than a second effect resolving independently later.

        ``rider["recipient"]`` is ``"you"`` (the shield's own controller,
        ``shield_controller_id``) or ``"source_controller"`` (whoever
        controls the damage source that was just prevented — ``event``'s own
        ``source_controller_id``) — unused by ``"add_self_counter"``, the one
        rider kind that isn't scaled by ``prevented`` at all (Nine Lives adds
        exactly one counter regardless of how much damage was actually
        stopped), which is also the only kind needing ``shield_source`` (the
        standing shield's own permanent — the one-shot `prevent_damage_to_*`/
        `prevent_damage_from_source` callers have no such "self" and simply
        omit it).

        ``rider`` may also be a list of rider dicts (New Way Forward's own
        "deals that much damage to that source's controller **and** you draw
        that many cards" — two independent follow-ups off the same prevented
        amount) — each is applied in turn.

        ``rider["if_source_color"]`` (Shadowbane/Honorable Passage, MEC-30)
        gates the whole rider on the *watched source's own* colour — "if
        damage from a **black** source is prevented this way, you gain that
        much life" is a rider that only sometimes fires, unlike every other
        rider kind above (which always fires once anything was prevented at
        all) — checked against ``event``'s own precomputed ``source_colors``.
        """
        if not rider or prevented <= 0:
            return
        if isinstance(rider, list):
            for one in rider:
                self.apply_prevent_rider(one, prevented, event, shield_controller_id, shield_source)
            return
        wanted_color = rider.get("if_source_color")
        if wanted_color is not None and wanted_color not in (event.get("source_colors") or ()):
            return
        # "…from a black **or red** source…" (Samite Ministration, PAR-78) —
        # ``if_source_color``'s multi-colour sibling, same "any of" idiom
        # `color_any` uses elsewhere in this file.
        wanted_colors_any = rider.get("if_source_color_any")
        if wanted_colors_any and not any(
            c in (event.get("source_colors") or ()) for c in wanted_colors_any
        ):
            return
        kind = rider.get("kind")
        if kind == "reflexive_damage":
            # PAR-139, Phyrexian Vindicator: "…prevent that damage. When damage is prevented this way, ~ deals
            # that much damage to any other target." — a fresh triggered ability (RULE 603.11: its target is
            # chosen when it is put on the stack), sized by the amount actually prevented.
            if shield_source is not None:
                self.enqueue_reflexive_trigger(
                    [{"type": "damage", "params": {"amount": prevented, "target_kind": "any"}}],
                    shield_source, event,
                )
            return
        if kind == "add_scaled_counters":
            # PAR-139: "…prevent that damage. Put a -1/-1 counter on ~ for each 1 damage prevented this
            # way." (Phyrexian Hydra, Stormwild Capridor) / "… on that creature …" (Vigor) — one counter
            # per point actually prevented, on the shield's own permanent (``on="self"``) or on the
            # permanent the damage was going to hit (``on="recipient"``, the DAMAGE event's target).
            if rider.get("on") == "recipient":
                target_id = event.get("target_id")
                counted_on = self.state.find_object(target_id) if target_id is not None else None
            else:
                counted_on = shield_source
            if counted_on is not None:
                self.add_counters(counted_on, prevented, str(rider.get("counter", "+1/+1")), source=shield_source)
            return
        if kind == "add_self_counter":
            if shield_source is not None:
                self.add_counters(shield_source, 1, str(rider.get("counter", "+1/+1")), source=shield_source)
            return
        if kind == "remove_self_counter":
            # "…prevent that damage. Remove a +1/+1 counter from ~." (the
            # Phantom cycle — Phantom Centaur / Phantom Flock / Phantom
            # Nantuko / Phantom Nishoba / …). A *fixed* count (1 on every
            # real card), unscaled by ``prevented`` — the counter loss is
            # the price of the shield, not proportional to the hit. Once the
            # last +1/+1 counter goes the RULE 704.5g "0 toughness" SBA
            # (these are printed 0/0) kills it, no extra code.
            if shield_source is not None:
                counter = str(rider.get("counter", "+1/+1"))
                count = prevented if rider.get("scaled") else int(rider.get("count", 1))
                # "…remove that many +1/+1 counters from it" (PAR-139, Ugin's Conjurant): only as many as
                # it actually holds.
                held = shield_source.plus_one_counters if counter == "+1/+1" else shield_source.counters.get(counter, 0)
                self.add_counters(shield_source, -min(count, held), counter)
            return
        if kind == "deal_damage_to_source_controller":
            # Always the *source's* controller, unconditionally — never the
            # generic ``recipient`` resolution below, which would otherwise
            # default to the shield's own controller (``"you"``) and hand
            # the reflected damage straight back to the very player the
            # shield protects: a DAMAGE event from the *same* watched
            # source, to the *same* protected recipient — the shield would
            # intercept its own reflection and recurse forever (confirmed
            # by a real `RecursionError` while wiring Deflecting Palm).
            source_controller_id = event.get("source_controller_id")
            if source_controller_id is None:
                return
            try:
                source_controller = self.state.player_by_id(source_controller_id)
            except (KeyError, ValueError):
                return
            source_id = event.get("source_id")
            source_obj = self.state.find_object(source_id) if source_id is not None else None
            self.deal_damage(source_controller, prevented, source=source_obj)
            return
        recipient_key = rider.get("recipient", "you")
        recipient_id = (
            shield_controller_id if recipient_key == "you" else event.get("source_controller_id")
        )
        if recipient_id is None:
            return
        try:
            recipient = self.state.player_by_id(recipient_id)
        except (KeyError, ValueError):
            return
        if kind == "gain_life":
            self.gain_life(recipient, prevented)
        elif kind == "draw_cards":
            self.draw(recipient, prevented)
        elif kind == "mill":
            # "…prevent that damage and mill twice that many cards" (Angel of Suffering): ``factor``.
            self.mill(recipient, prevented * int(rider.get("factor", 1)))
        elif kind == "exile_top_of_library_scaled":
            # Bone Mask (MEC-30): "Exile cards from the top of your library
            # equal to the damage prevented this way." — `mill`'s
            # exile-instead-of-graveyard sibling; no existing primitive
            # exiles a fixed count off the top in one call, so this loops
            # `exile` directly the same way `mill` loops its own move.
            for _ in range(prevented):
                if not recipient.library:
                    break
                self.exile(recipient.library[-1])
        elif kind == "create_tokens_scaled":
            from ...services.token_database import default_token_database, synthesize_token_card

            token = dict(rider.get("token") or {})
            token_name = token.get("token_name")
            card = None
            if token_name and token.get("power") is None and token.get("toughness") is None:
                card = default_token_database().get_token(token_name)
            if card is None:
                subtypes = list(token.get("subtypes", []))
                card = synthesize_token_card(
                    token_name or (subtypes[0] if subtypes else "Token"),
                    power=token.get("power"),
                    toughness=token.get("toughness"),
                    colors=list(token.get("colors", [])),
                    subtypes=subtypes,
                    keywords=list(token.get("keywords", [])),
                    legendary=bool(token.get("legendary", False)),
                    is_artifact=bool(token.get("is_artifact", False)),
                )
            self.create_token(recipient.id, card, count=prevented)

    def prevent_all_combat_damage_this_turn(
        self, controller: Player, exclude_subtype: Optional[str] = None,
    ) -> None:
        """RULE 615: "Prevent all combat damage that would be dealt this
        turn." (Fog) — unlike `prevent_damage_to_player`/`_to_target`
        (a shield for one chosen recipient), this is *unscoped*: it
        intercepts every RULE 510 combat-damage event for the rest of the
        turn regardless of source, target, or controller — no target was
        ever chosen for it to key off of.

        ``controller`` (the resolving spell's caster) is only where the
        shield physically lives — `Player.player_effects`, the same
        `damage_prevention_shield`-marked, cleanup-swept home every other
        RULE 615 shield uses (`GameEngine._step_cleanup`) — its
        `condition` doesn't reference ``controller`` at all, so the effect
        applies identically no matter whose damage it is.

        ``exclude_subtype`` (Galadhrim Ambush's "…by **non-Elf** creatures")
        is the one qualified variant this engine models: damage from a
        source currently carrying that creature subtype is let through
        (looked up live off `GameEvent.source_id`, so a mid-turn subtype
        change is honoured), every other source's combat damage is still
        prevented. Any other qualifier ("…by enchanted creatures"/"…except
        Spiders") stays unclaimed rather than guessed at.
        """
        def _condition(e: GameEvent, c: Any) -> bool:
            if not e.get("combat"):
                return False
            if exclude_subtype:
                source_id = e.get("source_id")
                obj = c.state.find_object(source_id) if source_id is not None else None
                if obj is not None:
                    from .. import continuous  # local: avoid the continuous↔rules cycle

                    if continuous._has_subtype(obj, exclude_subtype):
                        return False
            return True

        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=lambda e, c: None,  # every point of combat damage prevented
            condition=_condition,
            description="Fog: gesamter Kampfschaden in diesem Zug verhindert",
        )
        effect.damage_prevention_shield = True
        effect.prevents_damage = True  # MEC-30: "damage can't be prevented" filter
        controller.player_effects.append(effect)

    def _prevent_damage_to_creatures(
        self,
        controller: Player,
        recipient_scope: str = "all",
        recipient_filter: Optional[dict] = None,
        source_filter: Optional[dict] = None,
    ) -> None:
        """RULE 615: "Prevent all damage that would be dealt to creatures
        [you control] this turn." (PAR-78 — Forfend/Bubble Matrix/Inner
        Sanctum/Emmara Tandris/Iroas/Ethersworn Shieldmage) — unlike
        `prevent_damage_to_player`/`_to_target` (a shield for one chosen
        recipient) or `prevent_all_combat_damage_this_turn` (unscoped by
        recipient entirely), this shields *every* creature matching
        ``recipient_scope``/``recipient_filter`` live, board-wide, the same
        "no RULE 115 target was ever chosen" shape Fog's own method is, just
        narrowed to creature-only recipients instead of "everyone".

        ``recipient_scope`` is ``"all"`` (every creature) or
        ``"you_control"`` (only ``controller``'s own, checked live).
        ``recipient_filter`` narrows further by the recipient's own
        characteristics — ``{"token": True}`` (Emmara Tandris' "creature
        **tokens** you control"), ``{"subtype": "artifact"}``-shaped via
        ``{"artifact": True}`` (Ethersworn Shieldmage's "artifact
        creatures"), ``{"attacking": True}`` (Iroas' "attacking creatures
        you control"). ``source_filter`` — see `prevent_damage_to_player`
        (Light of Sanction's "…by sources you control").

        Lives on ``controller``'s own `Player.player_effects` purely as a
        physical home (cleanup-swept the same way every other RULE 615
        shield is) — the condition itself never reads ``controller`` for
        ``recipient_scope="all"``.
        """
        def _recipient_ok(target_obj: GameObject) -> bool:
            if not target_obj.is_creature:
                return False
            if recipient_scope == "you_control" and target_obj.controller_id != controller.id:
                return False
            if recipient_filter:
                if recipient_filter.get("token") and not getattr(target_obj, "is_token", False):
                    return False
                if recipient_filter.get("artifact") and not target_obj.card.is_artifact:
                    return False
                if recipient_filter.get("attacking") and not target_obj.attacking:
                    return False
            return True

        def _condition(e: GameEvent, c: Any) -> bool:
            if e.get("is_player"):
                return False
            target_obj = c.state.find_object(e.get("target_id"))
            if target_obj is None or not _recipient_ok(target_obj):
                return False
            return _damage_source_matches(c.state, e, source_filter, controller.id)

        effect = ReplacementEffect(
            event_type=EventType.DAMAGE,
            replacement_fn=lambda e, c: None,  # every matching point prevented
            condition=_condition,
            description="Kreaturen: Schadensverhinderung",
        )
        effect.damage_prevention_shield = True
        effect.prevents_damage = True  # MEC-30: "damage can't be prevented" filter
        controller.player_effects.append(effect)

    def disable_damage_prevention_this_turn(self) -> None:
        """RULE 615: "Damage can't be prevented this turn." (Insult //
        Injury/Isengard Unleashed, MEC-30) — a plain `GameState`-level flag
        (`damage_prevention_disabled`), not a replacement effect: it has no
        recipient or source of its own to key a `ReplacementEffect.
        condition` off, it just excludes every effect `RulesEngine.
        _run_replacement_loop` finds marked `prevents_damage` from that
        turn's candidate list. Reset at cleanup like any other "this turn"
        flag.
        """
        self.state.damage_prevention_disabled = True

    def grant_damage_multiplier_this_turn(
        self, controller: Player, source: GameObject, multiplier: int = 2,
        to_opponent_only: bool = False,
    ) -> None:
        """RULE 616: "If a source you control would deal damage this turn,
        it deals double/triple that damage instead." — the *spell-cast*
        sibling of `_double_damage_replacement` (`game/effects/core.py`): that
        factory only ever attaches to a *permanent's* own `replacement_
        effects` (Furnace of Rath/Fiery Emancipation-shaped); a one-shot
        sorcery (Insult // Injury/Isengard Unleashed, MEC-30) has no
        permanent to attach to once it resolves, so this builds the exact
        same replacement via `ReplacementRegistry.create` and files it on
        the caster's `Player.player_effects` instead — the same "float on
        the controller, not a permanent" idiom every one-shot RULE 615
        shield above already uses. ``source`` (the resolving spell) is what
        `your_sources_only` (always on here) reads its controller from —
        a spell object still carries a `controller_id` after it leaves the
        stack. Marked `damage_multiplier_grant` (not `damage_prevention_
        shield` — this isn't a prevention effect and must *not* be filtered
        by `disable_damage_prevention_this_turn`) for `GameEngine._step_
        cleanup`'s own matching sweep.
        """
        effect = ReplacementRegistry.create("double_damage", {
            "multiplier": multiplier, "your_sources_only": True,
            "to_opponent_only": to_opponent_only,
        })
        effect.source = source
        effect.damage_multiplier_grant = True
        controller.player_effects.append(effect)

    def _commander_damage_multiplier(self, recipient: Player) -> int:
        """Replacement multiplier for commander-damage bookkeeping only."""
        multiplier = 1
        for permanent in self.state.battlefield:
            for ability in getattr(permanent, "static_effects", []):
                if getattr(ability, "layer", None) != "commander_damage_multiplier":
                    continue
                if permanent.controller_id == recipient.id:
                    multiplier *= int(ability.params.get("multiplier", 3))
        return multiplier

    def _move_to_graveyard(self, obj: GameObject, cause: Optional[str] = None) -> None:
        """Put ``obj`` into its owner's graveyard (RULE 704.5), firing the
        leave/dies triggers. ``cause="sacrifice"`` additionally fires
        `EventType.SACRIFICE` (RULE 701.17) — set only by `put_into_graveyard`,
        the single choke point every genuine sacrifice funnels through.

        Lurrus-shaped redirect first (RULE 616): this is the one function
        every graveyard-bound move funnels through regardless of cause
        (destroy, sacrifice, SBA "dies") — while `obj.cast_via_graveyard_
        cast_permission_until_turn` still matches the current turn, exile
        it instead of proceeding, per the permission source's own trailing
        "if a spell cast this way would be put into a graveyard this turn,
        exile it instead" clause (`GraveyardCastPermissionEffect.exile_
        if_would_be_put_into_graveyard`).
        """
        if getattr(obj, "exile_after_free_cast", False):
            obj.exile_after_free_cast = False
            self.exile(obj)
            return
        if obj.cast_via_graveyard_cast_permission_until_turn == self.state.internal_turn.number:
            self.exile(obj)
            return
        owner = self.state.player_by_id(obj.owner_id)
        # "If a card would be put into your graveyard from anywhere this
        # turn, exile that card instead." (Yawgmoth's Will's own second
        # clause, MEC-12) — a card only ever enters its own *owner's*
        # graveyard (RULE 404.4/700.4), which is exactly what "your
        # graveyard" means here; the player-scoped, whole-turn sibling of
        # the per-object check just above.
        if owner is not None and owner.graveyard_redirect_to_exile_until_turn == self.state.internal_turn.number:
            self.exile(obj)
            return
        # "If a card would be put into an opponent's graveyard from
        # anywhere, instead exile it with a void counter on it." (Dauthi
        # Voidwalker, MEC-42) — a standing (never-swept) redirect, unlike
        # the two turn-scoped checks just above.
        void_holder_id = continuous.void_counter_redirect_controller_for(self.state, obj)
        if void_holder_id is not None:
            self.exile(obj)
            self.state.void_counter_holder[obj.instance_id] = void_holder_id
            return
        # "If a card [or token] would be put into [an opponent's/a]
        # graveyard from anywhere, exile it instead." (Leyline of the
        # Void/Rest in Peace, MEC-43) — the plain-exile sibling of the
        # void-counter redirect just above.
        if continuous.graveyard_redirect_active(self.state, obj):
            self.exile(obj)
            return
        # A self-only replacement granted through layer 6.  This common
        # choke point covers destruction, sacrifice and non-damage moves;
        # the derived flag means the granting static can use any ordinary
        # affected-object group.  Beneficial optional replacements follow
        # the engine's established default and are taken.
        if getattr(obj, "_graveyard_to_library_replacement", False):
            self.return_to_library(obj, "top")
            return
        was_on_battlefield = obj in self.state.battlefield
        was_creature = obj.is_creature

        # RULE 616.1: a "if ~ would die, exile it instead" replacement
        # (Gloomshrieker/Corpseweaver Prodigy) intercepts a creature's
        # battlefield→graveyard move before any DIES trigger fires. Modeled
        # like regeneration's shield: the matching replacement's own fn does
        # the exile as a side effect and returns None (event consumed), so a
        # None result here means "already redirected — don't also move it to
        # the graveyard". Only fired for a creature actually leaving the
        # battlefield (RULE 700.4 "dies"); every other graveyard path is
        # untouched.
        if was_on_battlefield and was_creature:
            would_die = GameEvent(
                EventType.WOULD_DIE,
                target_id=obj.instance_id,
                controller_id=obj.controller_id,
            )
            if self.apply_replacements(would_die) is None:
                return

        if was_on_battlefield:
            # RULE 603.6a "look back in time": fire while `obj` is still on
            # the battlefield so `_collect_triggers` (which only scans
            # `state.permanents()`) finds this object's own leave/dies
            # triggers. Mirrors `GameState.add_to_battlefield`'s
            # append-then-fire ordering for SAGA_CHAPTER/CLASS_LEVEL.
            self.state.fire_event(
                GameEvent(
                    EventType.LEAVES_BATTLEFIELD,
                    # Where it went — "leaves the battlefield without dying" (PAR-119).
                    to_zone="graveyard",
                    object=obj.name,
                    owner_id=obj.owner_id,
                    controller_id=obj.controller_id,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                    # RULE 603.10a last-known counters — a "for each counter on it" leaves-the-
                    # battlefield trigger of this same object reads them after it is gone.
                    counters=dict(obj.counters),
                    # "…target opponent loses life equal to its power."
                    # (Rapacious Guest-shaped) — snapshotted for the same
                    # RULE 400.7 reason `counters`/`subtypes` are elsewhere
                    # in this module: read via `LoseLifeEffect.
                    # amount_from_trigger_event`, since a live re-lookup
                    # after this fires would see the *new* post-move object.
                    power=obj.power,
                    # MEC-49: the toughness sibling — "you gain life equal to
                    # that creature's toughness" on a DIES trigger (Abattoir
                    # Ghoul), read the same RULE 400.7 last-known way.
                    toughness=obj.toughness,
                    # The characteristics "if it was a `<type>`" asks about (`trigger_event_object`), on
                    # the leaves event too so a self "leaves the battlefield" trigger can read them.
                    subtypes=sorted(continuous.derived_subtype_words(obj)),
                    colors=sorted(obj.colors),
                )
            )
            # RULE 700.4: "dies" means "is put into a graveyard from the
            # battlefield" — for *any* permanent, not just a creature
            # (Rancor's "When this Aura dies, return it to its owner's
            # hand.", Ashiok's Reaper's "Whenever an enchantment you control
            # dies, …"). Every consumer that does mean creatures
            # specifically already narrows on the event's own
            # ``object_types`` (`effect_binder._build_group_ok`'s ``type``
            # filter, `_collect_counter_death_return_triggers`'s explicit
            # check), so widening the firing condition can't over-fire them.
            self.state.fire_event(
                GameEvent(
                    EventType.DIES,
                    object=obj.name,
                    owner_id=obj.owner_id,
                    controller_id=obj.controller_id,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                    # Snapshotted live (before `remove_from_battlefield`
                    # below): a "dies with a counter on it" trigger
                    # condition (Marchesa, the Black Rose-shaped,
                    # `_collect_counter_death_return_triggers`) needs
                    # this off the event, not a live re-lookup — the
                    # dying object may already be gone from the
                    # battlefield by the time that check runs.
                    counters=dict(obj.counters),
                    # A tribal "another nontoken Zombie or Mutant you
                    # control dies" subject filter (The Ghoul, Gunslinger,
                    # `effect_binder._build_group_ok`) needs both off the
                    # event for the same reason — the object is already
                    # gone from the battlefield by the time that check
                    # runs.
                    is_token=obj.is_token,
                    # Derived, not just printed (RULE 603.10a): a Demon the layer engine made it is still a
                    # Demon when "if it wasn't a Demon" is asked (Infernal Vessel).
                    subtypes=sorted(continuous.derived_subtype_words(obj)),
                    # "whenever a **green** creature dies" (Bereavement,
                    # PAR-117) — `_build_group_ok`'s ``color`` key needs the
                    # same RULE 400.7 last-known snapshot as ``object_types``/
                    # ``subtypes`` just above; a live re-lookup after this
                    # fires would miss a dead object entirely.
                    colors=sorted(obj.colors),
                    # RULE 701.15b's designation, for the same reason: "whenever
                    # a **goaded** attacking or blocking creature dies" (Baeloth
                    # Barrityl) can't re-derive it once the object is gone. Also
                    # snapshots whether it was in combat, since 506.4 removes a
                    # permanent from combat as it leaves the battlefield.
                    goaded=bool(combat.is_goaded(obj)),
                    in_combat=bool(obj.attacking) or obj.blocking is not None,
                    # RULE 400.7 last-known information: "whenever a nonland
                    # creature you control dies, earthbend X, where X is
                    # **that creature's power**" (Beifong's Bounty Hunters) —
                    # read via `EarthbendEffect.amount_from_trigger_event`,
                    # since a live re-lookup after this fires sees nothing.
                    # Mirrors the same snapshot on LEAVES_BATTLEFIELD above.
                    power=obj.power,
                    # "…dies, **if its toughness was less than 1**, draw a
                    # card." (Massacre Girl, Known Killer —
                    # `ConditionalEffect.dying_creature_toughness_below`),
                    # the same RULE 400.7 last-known snapshot as ``power``.
                    toughness=obj.toughness,
                    # "Whenever an enchanted creature dies, draw a card for
                    # each Aura you controlled that was attached to it."
                    # (Hateful Eidolon, PAR-60) — the DIES trigger resolves
                    # after RULE 704.5m has already put every attached Aura
                    # in a graveyard, so the per-controller tally of Auras
                    # on this creature is snapshotted here (fired while
                    # `obj` is still on the battlefield, RULE 603.6a), the
                    # same last-known-info idiom as ``counters``/``power``.
                    attached_aura_controller_ids=[
                        a.controller_id for a in self.state.battlefield
                        if getattr(a, "attached_to", None) == obj.instance_id
                        and "aura" in (getattr(a.card, "type_line", "") or "").lower()
                    ],
                )
            )
            if cause == "sacrifice":
                # RULE 701.17: a sacrifice both leaves/dies *and* is a
                # distinct "was sacrificed" occurrence — fire it last so a
                # dies-trigger and a sacrifice-trigger batch in that order.
                self.state.fire_event(
                    GameEvent(
                        EventType.SACRIFICE,
                        object=obj.name,
                        owner_id=obj.owner_id,
                        controller_id=obj.controller_id,
                        # The player who sacrificed (RULE 701.17a: only a
                        # permanent's controller can) — the key a "…deals 2
                        # damage to them"/"that player" body reads through
                        # `event_player`, as on every other player-acted event.
                        player_id=obj.controller_id,
                        instance_id=obj.instance_id,
                        object_types=sorted(obj.type_words),
                        # "Whenever you sacrifice a Food/Clue/Treasure, …"
                        # (`effect_binder._trigger_condition`'s
                        # `sacrifice_type` predicate) needs the *subtype*
                        # half of the printed type line — ``object_types``
                        # above is main types only (mirrors DIES's own
                        # ``subtypes`` field just above).
                        subtypes=obj.card.type_line.partition("—")[2].strip().lower().split(),
                        # "Whenever you sacrifice a token, …" (Mirkwood Bats-
                        # shaped, the sacrifice-side mirror of ENTERS_
                        # BATTLEFIELD's own ``is_token`` stamp) — a plain
                        # exact-match ``filter`` key, not a new condition
                        # subject.
                        is_token=obj.is_token,
                    )
                )
            self.state.remove_from_battlefield(obj)
            self._detach_attachments_from(obj)

        obj.tapped = False
        obj.damage_marked = 0
        owner.add_to_zone(obj, Zone.GRAVEYARD)
        self._split_melded_after_move(obj, Zone.GRAVEYARD)  # RULE 712.19
        self._flag_commander_zone_choice(obj)
    def _flag_commander_zone_choice(self, obj: GameObject) -> None:
        """RULE 903.9a: a commander that just landed in a graveyard or exile
        may be moved to the command zone by its owner instead — offered once,
        as a state-based action (`_sba_pass`), not baked into the move
        itself. Marks ``obj`` eligible; the SBA consumes and clears the flag
        the moment it opens the `pending_choice`."""
        if obj.is_commander and obj.zone in (Zone.GRAVEYARD, Zone.EXILE):
            obj.commander_zone_choice_pending = True
    _COMMANDER_ZONE_LABELS = {
        Zone.GRAVEYARD: "Friedhof",
        Zone.EXILE: "Exil",
        Zone.HAND: "Hand",
        Zone.LIBRARY: "Bibliothek",
    }
    #: German dative-article gender for each label above ("aus **dem**
    #: Friedhof"/"aus **der** Hand") — feminine zones (Hand, Bibliothek) take
    #: "der", the rest (masculine/neuter) take "dem".
    _COMMANDER_ZONE_FEMININE = {Zone.HAND, Zone.LIBRARY}
    def _commander_zone_choice(self, obj: GameObject, zone: str) -> dict[str, Any]:
        """Build the RULE 903.9a/9b `pending_choice` offering to move a
        commander from ``zone`` (graveyard/exile — 903.9a, already there; or
        hand/library — 903.9b, about to land there) into the command zone
        instead."""
        label = self._COMMANDER_ZONE_LABELS.get(zone, str(zone))
        feminine = zone in self._COMMANDER_ZONE_FEMININE
        article = "der" if feminine else "dem"
        stay_prefix = "In der" if feminine else "Im"  # "im" = "in dem" contracted
        return {
            "kind": "commander_zone",
            "player_id": obj.owner_id,
            "instance_id": obj.instance_id,
            "prompt": f"{obj.name}: aus {article} {label} in die Kommandozone legen?",
            "options": [
                {"id": "command", "label": "In die Kommandozone legen"},
                {"id": "decline", "label": f"{stay_prefix} {label} bleiben"},
            ],
        }
    @continuations.choice("commander_zone", answer=continuations.ANSWER_STR, rule="903.9")
    def _resume_commander_zone(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending RULE 903.9a/9b `commander_zone` choice.

        ``"command"`` moves the commander into the command zone from
        whichever zone currently holds it; anything else (``None``/
        ``"decline"``) leaves it exactly where it already is.
        """
        if answer != "command":
            return
        obj = self.state.find_object(choice["instance_id"])
        if obj is None:
            return
        owner = self.state.player_by_id(obj.owner_id)
        self._remove_from_current_zone(owner, obj)
        # RULE 400.7 (bug report, 2026-09-04): a commander redirected here
        # came from the graveyard/exile/hand/library, each of which only
        # ever reset `tapped`/`damage_marked` on the way there — its
        # battlefield-only state (`attacking`/`combat_defender`/`blocking`/
        # counters/attachments/…) was still sitting on the object,
        # unnoticed while it stayed off the battlefield. Left alone, that
        # state survives all the way to a later recast, since `_resolve_
        # permanent_spell` never resets it either — a commander that died
        # mid-combat could re-enter the battlefield *this* turn already
        # "attacking" a defender from a previous combat, corrupting
        # `attackers()`/every per-attacker aggregate (`_fire_player_
        # attacked_events` et al.) built from that flag. The same "new
        # object, no memory" reset `blink`/`return_from_graveyard` already
        # give a battlefield-bound move applies just as well to this one.
        obj.reset_as_new_object()
        owner.add_to_zone(obj, Zone.COMMAND)
