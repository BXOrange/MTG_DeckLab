"""The game engine: turn/phase/step loop, actions, goldfish (docs/02 R4.*).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R4.1-R4.3 (Game Loop, Priority,
Action Validation), UC3 (Goldfisch), docs/07 PART 1/8.

`RulesEngine` is the toolbox of rules primitives; `GameEngine` is the
loop that drives it: it walks a `TurnSequence`, opens priority windows in
which the stack resolves (RULE 117/608), runs step bodies (untap, draw,
combat damage, cleanup), and exposes validated player actions (play a
land, cast a spell, attack) plus a `legal_actions` query the UI/bot can
ask instead of guessing (docs/02 R4.3 — the frontend has no such check
today). `run_goldfish_turn` wires those together into a solo auto-turn
(UC3).
"""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from typing import Any, Optional

from ...models.card import Card
from ...models.events import EventType, GameEvent
from ...models.game_object import GameObject, Zone
from ...models.game_state import GameState, StackItem
from ...models.mana_cost import ManaCost
from ...models.player import Player
from .. import combat, condition_query, continuous, durations, face_down, variants
from ...models import game_format
from ...models.game_format import GameFormat, get_format
from ..costs import (
    DISCARD_HAND,
    PAY_LIFE_X,
    REMOVE_COUNTERS_ANY,
    REMOVE_COUNTERS_X,
    ActivationCost,
    parse_activation_cost,
)
from ..effects.core import ActivatedAbility
from ..mana_abilities import (
    hand_mana_abilities_for,
    mana_abilities_for,
    option_label,
    restriction_predicate_for_activation,
    restriction_predicate_for_cast,
    validate_color_split,
)
from ..phases import GamePhase, GameStep, default_turn_sequence
from ..rules_engine import RulesEngine
from ..targeting import (
    TargetSpec,
    ability_target_specs,
    all_requirements_satisfiable,
    legal_targets,
    partition_targets,
    requirements_with_targets,
    resolved_count,
    spell_target_specs,
)
from ..graveyard_cast import graveyard_cast_grant_for
from ..top_library import (
    may_cast_flash_from_top_of_library,
    may_cast_spell_from_top_of_library,
    may_play_land_from_top_of_library,
    top_library_life_payment_required,
)

#: Maximum hand size enforced at cleanup (RULE 402.2 / 514.1).


class CombatMixin:
    """Combat: restrictions/requirements, attacker/blocker declaration, combat damage."""

    @property
    def attackers(self) -> list[GameObject]:
        """Creatures currently declared as attackers (RULE 508).

        Derived from the battlefield rather than stored on the engine, so
        combat survives a rewind: a `GameSession` restores by wrapping a
        *fresh* engine around a cloned `GameState`, which carries each
        object's ``attacking`` flag with it — an engine-side list would be
        lost.
        """
        return [obj for obj in self.state.battlefield if obj.attacking]
    def _clear_combat(self) -> None:
        """End combat: no creature is attacking or blocking (RULE 511.3)."""
        for obj in self.state.battlefield:
            obj.attacking = False
            obj.combat_defender = None
            obj.blocking = None
            obj.additional_blocking = []
            obj.blocked_by = []
            obj.dealt_deathtouch_damage = False
        # RULE 509.1a: nobody has "already declared blockers" for a combat
        # that hasn't happened yet — reset alongside the per-object flags
        # above (`GameState.declared_blockers_this_combat`'s own docstring).
        self.state.declared_blockers_this_combat.clear()
    def _enforce_attacks_if_able(self) -> None:
        """RULE 508.1a: a creature under an "attacks each combat if able"
        static must be declared as an attacker if it's able to.

        `declare_attackers` is additive (the UI declares one creature at a
        time) and has no "I'm done" signal of its own, so the natural gate is
        here — the moment the caller tries to leave the declare-attackers
        step. Checked against `_can_attack` before anything about this combat
        (blocks, damage) has changed the board, so a creature this flag
        applies to is still evaluated on the same terms `declare_attackers`
        itself would have accepted.
        """
        active = self.state.active_player
        for obj in self.state.permanents_controlled_by(active.id):
            if (
                (combat.has(obj, "attacks_if_able") or combat.is_goaded(obj))
                and not obj.attacking
                and self._can_attack(active, obj)
            ):
                # RULE 701.15b's first half: a goaded creature "attacks each
                # combat if able" — the same requirement the flag keyword
                # imposes, so it rides the same check rather than a parallel
                # one. Its second half (*whom* it must attack) is
                # `_enforce_goad_requirements`, since that can only be judged
                # once the whole attack is declared.
                raise ValueError(f"{obj.name} attacks each combat if able")
    def _enforce_goad_requirements(self) -> None:
        """RULE 701.15b's second half: a goaded creature "attacks a player
        other than the controller of the [goading] permanent, spell, or
        ability if able".

        A requirement about the *chosen defender*, so unlike the "attacks if
        able" half it can only be judged once the attack is declared — hence
        this sits beside `_enforce_attack_alone_restrictions` on the way out
        of the declare-attackers step rather than inside `declare_attackers`.

        "If able" is the whole difficulty. The creature is only in violation
        when a legal *alternative* existed: another defender it could have
        attacked that isn't one of its goaders (or something they control).
        With only the goader attackable — a two-player game, the usual case,
        where "a player other than you" has no answer — attacking them is
        correct and this must stay silent. RULE 701.15c's several goaders are
        handled by requiring the defender to satisfy *every* goad it carries,
        which is the strictest reading and the one that matches "creates
        additional combat requirements".
        """
        active = self.state.active_player
        for obj in self.state.battlefield:
            if not obj.attacking or obj.controller_id != active.id:
                continue
            goaded_by = combat.goaders(obj)
            if not goaded_by:
                continue
            attacked = self._defending_player(obj.combat_defender)
            if attacked is None or attacked.id not in goaded_by:
                continue  # already attacking someone this goad doesn't forbid
            # Attacking a goader — legal only if no permitted defender was
            # available to this creature at all.
            #
            # Asked with `_attack_conditions_ok` rather than `_can_attack`:
            # by now the creature is declared and (without vigilance) tapped,
            # so `_can_attack` would answer "no" for *every* defender — it
            # would be reading the state this very declaration created.
            # Everything it checks beyond the defender-dependent conditions
            # (tapped, summoning sickness, defender, "can't attack") is
            # defender-*independent* and was already satisfied when
            # `declare_attackers` accepted this creature, so the only open
            # question left is the per-defender one.
            alternatives = [
                spec
                for spec in self.legal_defenders_for(active)
                if (defender := self._defending_player(spec)) is not None
                and defender.id not in goaded_by
                and self._attack_conditions_ok(obj, active, defender)
            ]
            if alternatives:
                raise ValueError(
                    f"{obj.name} is goaded and must attack a player other than "
                    f"{attacked.name} if able"
                )
    def _enforce_attack_alone_restrictions(self) -> None:
        """RULE 508.1a: "~ can't attack alone." — a restriction on the *whole*
        declared attack, not on one creature in isolation, so like
        `_enforce_attacks_if_able` above it's checked as the caller tries to
        leave the declare-attackers step (the additive, multi-call
        `declare_attackers` has no other "I'm done" signal; rejecting mid-way
        would wrongly bite the first creature declared in a legal pair).
        """
        for obj in self.state.battlefield:
            if not obj.attacking:
                continue
            if combat.combat_restrictions(obj, "cant_attack_alone") and self._attacking_alone(obj):
                raise ValueError(f"{obj.name} can't attack alone")
    def _fire_attacks_alone_event(self) -> None:
        """RULE 506.5-adjacent "whenever ~ attacks alone" (`EventType.
        ATTACKS_ALONE`) — an aggregate over the finished attack, for the same
        reason `PLAYER_ATTACKED` is one: `ATTACKS` fires per creature as it's
        declared, so the very first declaration of a two-creature attack
        would always look "alone". Fires at most once per combat, for the
        single attacking creature.
        """
        attacking = [o for o in self.state.battlefield if o.attacking]
        if len(attacking) != 1:
            return
        obj = attacking[0]
        self.state.fire_event(
            GameEvent(
                EventType.ATTACKS_ALONE,
                attacker=obj.name,
                player_id=obj.controller_id,  # RULE 508.1a: the attacker's controller
                instance_id=obj.instance_id,
                object_types=sorted(obj.type_words),
            )
        )
    def _fire_player_attacked_events(self) -> None:
        """RULE 506.4's "a player attacks you with one or more creatures" —
        see `EventType.PLAYER_ATTACKED`'s docstring for why this needs its
        own aggregate event rather than reusing `ATTACKS`. Groups every
        currently-attacking creature by (its controller, the player it's
        attacking) and fires one event per group.
        """
        counts: dict[tuple[str, str], int] = {}
        for obj in self.state.battlefield:
            if not obj.attacking:
                continue
            spec = obj.combat_defender
            if not spec or spec.get("kind") != "player":
                continue
            key = (obj.controller_id, spec["id"])
            counts[key] = counts.get(key, 0) + 1
        for (attacker_id, defender_id), count in counts.items():
            self.state.fire_event(
                GameEvent(
                    EventType.PLAYER_ATTACKED,
                    attacking_player_id=attacker_id,
                    defending_player_id=defender_id,
                    count=count,
                )
            )
    def _enforce_block_requirements(self) -> None:
        """RULE 509.1c/d: a blocking *requirement* — the mirror image of the
        RULE 509.1a/b restrictions above — constrains the defending player's
        declared blocks. Checked as they try to leave the declare-blockers
        step, mirroring `_enforce_attacks_if_able`'s "leaving
        declare_attackers" hook (`declare_blockers` is additive too, so
        there's no other "I'm done" signal).

        Two shapes, both read off live board state rather than tracked
        separately: the standing attacker-side statics ("~ must be blocked
        if able." / "All creatures able to block ~ do so.", synthetic flag
        keywords exactly like `attacks_if_able`), and the resolve-time
        pairwise "target creature blocks ~ this turn if able." (a
        `must_block_target` `combat_restriction` naming a specific attacker
        by instance id, `GrantCombatRestrictionEffect`'s
        ``restrict_to_source``).

        A requirement only binds a defending creature through `can_block`,
        which already reflects every restriction *and* every remaining
        block capacity (`combat.has_block_capacity`) — so a creature already
        fully committed elsewhere is correctly excused, matching RULE
        509.1c's "obey as many requirements as possible" when two collide,
        without a full requirement-satisfaction optimizer.
        """
        for attacker in self.attackers:
            must_any = combat.has(attacker, "must_be_blocked")
            must_all = combat.has(attacker, "all_must_block")
            if not must_any and not must_all:
                continue
            defender = self._defending_player(attacker.combat_defender)
            if defender is None:
                continue
            candidates = [
                o for o in self.state.permanents_controlled_by(defender.id)
                if self.can_block(defender, o, attacker)
            ]
            if must_all:
                for candidate in candidates:
                    if attacker.instance_id not in combat.blocking_attacker_ids(candidate):
                        raise ValueError(f"{candidate.name} must block {attacker.name}")
            elif must_any and candidates and not attacker.blocked_by:
                raise ValueError(f"{attacker.name} must be blocked if able")

        for obj in self.state.permanents():
            for entry in combat.combat_restrictions(obj, "must_block_target"):
                attacker_id = (entry.get("filter") or {}).get("instance_id")
                if attacker_id is None:
                    continue
                attacker = self.state.find_object(attacker_id)
                if (
                    attacker is None
                    or not attacker.attacking
                    or attacker.instance_id in combat.blocking_attacker_ids(obj)
                ):
                    continue
                defender = self.state.player_by_id(obj.controller_id)
                if self.can_block(defender, obj, attacker):
                    raise ValueError(
                        f"{obj.name} must block {attacker.name} this turn if able"
                    )
    def _combat_has_first_strikers(self) -> bool:
        """Whether any attacker or blocker has first or double strike (→ two
        damage steps, RULE 702.7e)."""
        combatants = list(self.attackers) + [
            b for b in self.state.battlefield if combat.blocking_attacker_ids(b)
        ]
        return any(
            combat.has_first_strike(c) or combat.has_double_strike(c) for c in combatants
        )
    @staticmethod
    def _deals_in_step(obj: GameObject, first_strike_step: bool) -> bool:
        """Whether ``obj`` deals damage in this combat-damage step.

        First-strike step: first strike *or* double strike. Regular step:
        double strike (again) or a creature with neither — a pure first-striker
        has already dealt and deals nothing more.
        """
        fs = combat.has_first_strike(obj)
        ds = combat.has_double_strike(obj)
        return (fs or ds) if first_strike_step else (ds or not fs)
    def _deal_combat_damage_step(self, first_strike_step: bool) -> None:
        # (target, amount, source) gathered before anything is dealt.
        assignments: list[tuple[Any, int, GameObject]] = []
        for attacker in self.attackers:
            if not self._deals_in_step(attacker, first_strike_step):
                continue
            power = attacker.power or 0
            if power <= 0:
                continue
            if attacker.blocked_by:
                # Blocked (RULE 509.1h: it stays blocked even if every blocker
                # has left) — damage goes to whatever blockers remain, with
                # trample overflow to the defender.
                living = [
                    b
                    for b in (self.state.find_object(i) for i in attacker.blocked_by)
                    if b is not None and b in self.state.battlefield
                ]
                assignments.extend(self._assign_blocked_attacker(attacker, power, living))
            else:
                defender = self._resolve_combat_defender(attacker.combat_defender)
                if defender is not None:  # None → bare swing (solo goldfish)
                    assignments.append((defender, power, attacker))

        # Blockers strike the attacker(s) they're blocking (RULE 510.1c).
        for blocker in self.state.battlefield:
            attacker_ids = combat.blocking_attacker_ids(blocker)
            if not attacker_ids or not self._deals_in_step(blocker, first_strike_step):
                continue
            power = blocker.power or 0
            if power <= 0:
                continue
            blocked_attackers = [
                a
                for a in (self.state.find_object(i) for i in attacker_ids)
                if a is not None and a in self.state.battlefield
            ]
            assignments.extend(self._split_blocker_damage(blocker, power, blocked_attackers))

        self._apply_combat_damage(assignments)
    def _split_blocker_damage(
        self, blocker: GameObject, power: int, attackers: list[GameObject]
    ) -> list[tuple[Any, int, GameObject]]:
        """Divide ``blocker``'s power among every attacker it's blocking (RULE
        510.1c: "divided as its controller chooses among the attacking
        creatures it's blocking") — an auto-pick even split (remainder to the
        earliest-blocked attackers), the same non-interactive simplification
        `_sacrifice_candidate` and friends already make elsewhere for a choice
        this engine has no UI to ask interactively. Degenerates to the
        ordinary single-attacker case unchanged (the overwhelming majority):
        the whole ``power`` goes to that one attacker, exactly as before
        RULE 509.1b multi-block grants existed.
        """
        if not attackers:
            return []
        base, extra = divmod(power, len(attackers))
        out: list[tuple[Any, int, GameObject]] = []
        for index, attacker in enumerate(attackers):
            amount = base + (1 if index < extra else 0)
            if amount > 0:
                out.append((attacker, amount, blocker))
        return out
    def _assign_blocked_attacker(
        self, attacker: GameObject, power: int, blockers: list[GameObject]
    ) -> list[tuple[Any, int, GameObject]]:
        """Spread a blocked attacker's ``power`` across its blockers (RULE
        510.1c ordering, lethal-first), trampling the excess onto the defender
        if it has trample (RULE 702.19), else soaking the remainder on the last
        blocker. Deathtouch shrinks "lethal" to 1 (RULE 702.2b) so trample
        needs assign only 1 per blocker before spilling over.
        """
        out: list[tuple[Any, int, GameObject]] = []
        trample = combat.has_trample(attacker)
        if not blockers:
            # Every blocker gone: only trample leaks to the defender.
            if trample:
                defender = self._resolve_combat_defender(attacker.combat_defender)
                if defender is not None:
                    out.append((defender, power, attacker))
            return out

        remaining = power
        for index, blocker in enumerate(blockers):
            if remaining <= 0:
                break
            last = index == len(blockers) - 1
            lethal = combat.lethal_damage(blocker, attacker)
            if trample:
                amount = min(remaining, lethal)
            else:
                amount = remaining if last else min(remaining, lethal)
            if amount > 0:
                out.append((blocker, amount, attacker))
                remaining -= amount
        if trample and remaining > 0:
            defender = self._resolve_combat_defender(attacker.combat_defender)
            if defender is not None:
                out.append((defender, remaining, attacker))
        return out
    def _apply_combat_damage(
        self, assignments: list[tuple[Any, int, GameObject]]
    ) -> None:
        """Deal one damage step's gathered assignments, applying protection,
        deathtouch and lifelink to each."""
        # MEC-29/RULE 603.1: "whenever one or more creatures you control
        # [with `<characteristic>`] deal combat damage to a player" is an
        # aggregate condition over this whole step, not a per-hit one — see
        # `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`'s docstring.
        # Tracked live alongside the ordinary per-hit `DAMAGE` firing below
        # (every assignment whose ``target`` is a `Player` is by
        # construction an attacking creature's own damage — RULE 510.1c
        # blockers only ever strike the attacker(s) they're blocking, never
        # a player, so no blocker-sourced entry can reach this branch), then
        # fired once per (contributing controller, player hit) pair after
        # the loop.
        # ``subtypes`` per pair is the union of every contributing creature's
        # own subtypes ("whenever one or more **Pirates** you control deal
        # combat damage to a player" — Malcolm, Keen-Eyed Navigator) — an
        # aggregate-condition characteristic alongside ``max_power``, not a
        # per-hit one, same reasoning as the docstring above.
        player_hits: dict[tuple[Optional[str], Any], dict[str, Any]] = {}
        for target, amount, source in assignments:
            # Protection prevents the damage from a source of the named quality
            # (RULE 702.16c; `rules.deal_damage` enforces this too, so no
            # damage lands even if a caller skips this check) — checked here
            # as well so deathtouch/lifelink below don't fire off damage that
            # never happened. Players carry no protection in this model.
            if isinstance(target, GameObject) and combat.is_protected_from(target, source):
                continue
            self.rules.deal_damage(target, amount, source=source, combat=True)
            if amount <= 0:
                continue
            # Deathtouch: mark any creature damaged by a deathtouch source for
            # the SBA to destroy (RULE 702.2b).
            if isinstance(target, GameObject) and combat.has_deathtouch(source):
                target.dealt_deathtouch_damage = True
            # Lifelink: the source's controller gains that much life (702.15b).
            if combat.has_lifelink(source):
                self.rules.gain_life(self.state.player_by_id(source.controller_id), amount)
            if not isinstance(target, GameObject):
                key = (source.controller_id, target.id)
                entry = player_hits.setdefault(
                    key, {
                        "max_power": 0, "amount": 0, "subtypes": set(), "is_commander": False,
                        "power_gt_base": False, "any_nontoken": False, "contributor_ids": [],
                        "any_base_power_0": False, "base_power_0_amount": 0,
                    }
                )
                entry["contributor_ids"].append(source.instance_id)
                entry["max_power"] = max(entry["max_power"], source.power or 0)
                # "…creatures you control **with base power 0**…" (Primo, the
                # Unbounded, PAR-60) — "base power" is the printed/copied
                # value (`Card.power`, RULE 707.2), not the derived
                # `source.power` (counters + statics), the same distinction
                # ``power_gt_base`` just below draws. ``base_power_0_amount``
                # is the combat damage those base-power-0 creatures dealt to
                # this player this step (Primo's "the damage dealt").
                if int(getattr(source.card, "power", 0) or 0) == 0:
                    entry["any_base_power_0"] = True
                    entry["base_power_0_amount"] += amount
                # "whenever **1 or more nontoken creatures** you control deal
                # combat damage to a player" (Feywild Visitor's granted
                # trigger) — true once any contributor to this pair is a
                # nontoken creature (RULE 111.9).
                if not getattr(source, "is_token", False):
                    entry["any_nontoken"] = True
                # "…each with power greater than its base power…" (Kutzil,
                # Malamet Exemplar, MEC-40) — "base power" is the printed
                # value (`Card.power`, already the *copied* value for a
                # token/copy — RULE 707.2 rebases it there), unlike the
                # current derived `source.power` (counters + static
                # boosts). An "or greater" aggregate can't reuse
                # ``max_power`` here: that's a single number, not "was
                # *this* contributor's power above *its own* base".
                if (source.power or 0) > (source.card.power or 0):
                    entry["power_gt_base"] = True
                # "…it deals **that much damage** to each other opponent."
                # (Kediss, Emberclaw Familiar) — the actual combat damage
                # total dealt to this opponent this step, distinct from
                # ``max_power`` (a *threshold* `contributor_power_at_least`
                # reads, not a summed amount — the two only coincide for
                # the common single-unblocked-attacker case).
                entry["amount"] += amount
                # `GameObject.type_words` is *main* types only ("creature",
                # "legendary permanent") — a tribal filter needs the actual
                # subtype words after the em dash, honouring a layer-4
                # subtype overwrite/add the same way `continuous._has_
                # subtype` does (its own logic inlined here since that
                # function tests one subtype at a time, not the whole set;
                # RULE 702.73 Changeling is the one thing it handles that
                # this aggregate doesn't — a vanishingly rare combination
                # with a tribal aggregate payoff).
                derived = getattr(source, "_derived_subtypes", None)
                if derived is not None:
                    entry["subtypes"].update(s.lower() for s in derived)
                else:
                    entry["subtypes"].update(
                        s.lower() for s in (getattr(source, "_added_subtypes", None) or set())
                    )
                    entry["subtypes"].update(
                        source.card.type_line.lower().partition("—")[2].split()
                    )
                # "whenever a **commander** you control deals combat damage
                # to an opponent, …" (Kediss, Emberclaw Familiar) — same
                # aggregate-characteristic reasoning as ``subtypes``: RULE
                # 903's designation, read off whichever contributor(s) had
                # it, since this event names none of them individually.
                if getattr(source, "is_commander", False):
                    entry["is_commander"] = True
        for (controller_id, target_id), entry in player_hits.items():
            self.state.fire_event(
                GameEvent(
                    EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                    player_id=controller_id,
                    target_id=target_id,
                    # The recipient is always a player by construction — set
                    # so a "target … that player controls" target kind
                    # (`targeting`) can scope to it (Popular Entertainer).
                    is_player=True,
                    max_power=entry["max_power"],
                    amount=entry["amount"],
                    subtypes=sorted(entry["subtypes"]),
                    contributor_is_commander=entry["is_commander"],
                    contributor_power_gt_base=entry["power_gt_base"],
                    contributor_any_nontoken=entry["any_nontoken"],
                    contributor_ids=entry["contributor_ids"],
                    any_base_power_0=entry["any_base_power_0"],
                    base_power_0_amount=entry["base_power_0_amount"],
                )
            )
    def _resolve_combat_defender(self, spec: Optional[dict[str, Any]]) -> Optional[Any]:
        """Turn a stored ``combat_defender`` spec back into the live target.

        Returns the defending `Player`, the planeswalker or battle
        `GameObject`, or None (a bare swing / a defender that has since
        left). Robust to a rewind having swapped in a fresh state —
        everything is re-looked-up by id, never held by reference.
        """
        if not spec:
            return None
        if spec.get("kind") == "player":
            try:
                player = self.state.player_by_id(spec["id"])
            except KeyError:
                return None
            return None if player.has_lost else player
        if spec.get("kind") in ("planeswalker", "battle"):
            # Both resolve to the permanent itself; what differs is what
            # `RulesEngine.deal_damage` then does with it (loyalty counters
            # vs. RULE 310.6 defense counters), which it decides off the
            # object's own type rather than off this spec.
            obj = self.state.find_object(spec["instance_id"])
            if obj is not None and obj in self.state.battlefield:
                return obj
        return None
    def declare_attackers(
        self, player: Player, declarations: list[Any]
    ) -> None:
        """Declare attackers (RULE 508), each against a chosen defender.

        Each entry is either a bare `GameObject` (the engine picks the
        defender when it is unambiguous) or a ``{"attacker": obj, "defender":
        spec, "exert": bool, "pay_attack_tax": bool}`` dict, where ``spec`` is one of the entries
        `legal_defenders_for` returns (or None for a bare swing). Declaring is
        *additive* — the UI declares creatures one at a time so each can pick
        its own target below it — so repeated calls accumulate the combat.
        Taps each attacker and fires ATTACKS.

        ``exert=True`` is RULE 702.19a's own declare-time choice — "as it's
        declared as an attacker, its controller may exert it" — not a
        separate priority window or `pending_choice`, since real Magic asks
        it in the same breath as the attack declaration itself. Only legal
        for a creature that actually has exert (`combat.has(obj, "exert")`);
        a client offering it to anything else is a bug, not a choice, so this
        raises rather than silently ignoring it.
        """
        if player is not self.state.active_player:
            raise ValueError("only the active player declares attackers")
        if self.state.current_step != "declare_attackers":
            raise ValueError("not in the declare-attackers step")

        legal = self.legal_defenders_for(player)
        resolved: list[tuple[GameObject, Optional[dict[str, Any]], bool]] = []
        pay_attack_tax = True
        for entry in declarations:
            if isinstance(entry, dict):
                obj = entry["attacker"]
                defender = entry.get("defender")
                exert = bool(entry.get("exert"))
                # RULE 508.1g is a declaration-time choice. A client can
                # explicitly decline it, which leaves this submitted attack
                # illegal and, crucially, spends none of the player's mana.
                # Omitting the flag preserves the goldfish auto-pay default.
                pay_attack_tax = pay_attack_tax and bool(entry.get("pay_attack_tax", True))
            else:
                obj, defender, exert = entry, None, False
            # RULE 508.1a: a creature is declared as an attacker once per
            # combat — a second declaration of the same (still-untapped,
            # e.g. vigilant) creature must never re-run the declaration
            # (re-tap/re-fire ATTACKS/re-check dethrone). `legal_actions`
            # no longer offers an already-attacking creature at all (bug
            # report, 2026-09-04 — Frodo, Adventurous Hobbit's Vigilance
            # kept it re-offered, and a bot that takes every "attack" offer
            # re-declared it every poll, firing its trigger 953 times); this
            # is the same guard kept here too, for a client that submits a
            # stale offer anyway.
            if obj.attacking:
                raise ValueError(f"{obj.name} is already attacking")
            if exert and not combat.has(obj, "exert"):
                raise ValueError(f"{obj.name} doesn't have exert")
            assigned = self._assign_defender(obj, defender, legal)
            # RULE 508.1a is checked against the *assigned* defender, not just
            # "somebody" — "~ can't attack unless defending player controls an
            # Island" is only legal against the player who actually has one.
            if not self._can_attack(player, obj, self._defending_player(assigned)):
                raise ValueError(f"{obj.name} cannot attack")
            resolved.append((obj, assigned, exert))

        # RULE 508.1g attack tax (Propaganda / Ghostly Prison / Windborn
        # Muse): "creatures can't attack you unless their controller pays {N}
        # for each creature they control that's attacking you." Summed over
        # every taxed defending player in this declaration and auto-paid from
        # the active player's mana (floating first, then an auto-tap plan) —
        # the same "make the cost happen so the card functions" treatment
        # `_auto_tap_for_cast_if_needed` gives spell costs in a solo/goldfish
        # session. If it genuinely can't be paid, the whole declaration is
        # illegal (RULE 508.1g — those attackers are removed from combat).
        tax_total = 0
        for _obj, _defender, _exert in resolved:
            defending = self._defending_player(_defender)
            if defending is not None:
                defender_kind = str((_defender or {}).get("kind", "player"))
                tax_total += continuous.attack_tax_per_creature_for(
                    self.state, defending.id, defender_kind, attacker=_obj
                )
        if tax_total > 0:
            if not pay_attack_tax:
                raise ValueError("attack tax declined; those creatures cannot be declared as attackers")
            tax_cost = ManaCost.parse(f"{{{tax_total}}}")
            if not player.mana_pool.can_pay(tax_cost):
                try:
                    self.auto_tap_for(player, cost=tax_cost)
                except ValueError:
                    raise ValueError(
                        f"cannot pay the {{{tax_total}}} attack tax to declare these attackers"
                    )
            if not player.mana_pool.can_pay(tax_cost):
                raise ValueError(
                    f"cannot pay the {{{tax_total}}} attack tax to declare these attackers"
                )
            player.mana_pool.pay(tax_cost)

        for obj, defender, exert in resolved:
            # Vigilance (RULE 702.21b): attacking doesn't cause it to tap.
            if not combat.has_vigilance(obj):
                self.rules.set_tapped(obj, True)
            obj.attacking = True
            obj.attacked_this_turn = True  # PAR-28 RULE 702.142a (Boast)
            obj.combat_defender = defender
            self.state.fire_event(
                GameEvent(
                    EventType.ATTACKS,
                    attacker=obj.name,
                    player_id=player.id,  # RULE 508.1a: the attacker's controller
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                    # "…destroy target artifact or enchantment defending
                    # player controls." (Kogla, the Titan Ape, MEC-43) — the
                    # already-resolved defending player (`_defending_player`
                    # just above, RULE 508.1a's own legality check reads the
                    # same value), so a per-attacker trigger's own target
                    # can be scoped to it without re-deriving it from
                    # `combat_defender` a second time at resolution.
                    defending_player_id=getattr(self._defending_player(defender), "id", None),
                )
            )
            if exert:
                # RULE 702.19b: "doesn't untap during its controller's next
                # untap step" — a one-time consequence consumed by
                # `_step_untap`, not the sticky `skip_untap` toggle.
                obj.skip_next_untap = True
                # Read *before* setting: Combat Celebrant's own "if ~ hasn't
                # been exerted this turn" guard (RULE 603.4-style intervening
                # if, `ConditionalEffect`'s ``not_already_exerted`` key) needs
                # whether this is a *repeat* exert this turn, which the flag
                # itself can't answer once it's been set.
                already_exerted = obj.exerted_this_turn
                obj.exerted_this_turn = True
                self.state.fire_event(
                    GameEvent(
                        EventType.EXERTED,
                        attacker=obj.name,
                        player_id=player.id,
                        instance_id=obj.instance_id,
                        object_types=sorted(obj.type_words),
                        already_exerted=already_exerted,
                    )
                )
            # RULE 702.107: Dethrone's own per-firing dynamic check — see
            # `RulesEngine.check_dethrone` for why this can't go through the
            # ordinary annihilator/afflict/bushido `TriggeredAbility` path.
            self.rules.check_dethrone(obj)
    def ninjutsu(self, player: Player, ninja: GameObject, returned_attacker: GameObject) -> None:
        """RULE 702.49a Ninjutsu — "[cost], Return an unblocked attacker you
        control to hand: Put this card onto the battlefield from your hand
        tapped and attacking." A RULE 702.49b special action, legal only for
        the active player during the declare-blockers step (PAR-26).

        The ninja takes the returned attacker's place in combat — same
        defender, tapped and attacking, and it doesn't tap for its own
        attack (it's *put* there, not declared). Its own ``ATTACKS`` event
        fires so an "whenever ~ attacks" trigger (Ninja of the Deep
        Hours-shaped) still works; ETB fires normally.
        """
        cost = getattr(ninja, "ninjutsu_cost", None)
        if cost is None:
            raise ValueError(f"{ninja.name} has no ninjutsu")
        if player is not self.state.active_player or self.state.current_step != "declare_blockers":
            raise ValueError("ninjutsu can only be used during your declare-blockers step")
        if ninja not in player.hand:
            raise ValueError(f"{ninja.name} is not in hand")
        if not (returned_attacker.attacking and returned_attacker.controller_id == player.id
                and not returned_attacker.blocked_by):
            raise ValueError(f"{returned_attacker.name} is not an unblocked attacker you control")
        if not player.mana_pool.can_pay(cost):
            raise ValueError("cannot pay the ninjutsu cost")

        player.mana_pool.pay(cost)
        defender = returned_attacker.combat_defender
        self.rules.return_to_hand(returned_attacker)  # RULE 702.49a's own cost

        player.remove_from_zone(ninja, Zone.HAND)
        ninja.tapped = True
        ninja.attacking = True
        ninja.attacked_this_turn = True
        ninja.summoning_sick = False
        ninja.combat_defender = defender
        self.state.add_to_battlefield(ninja)
        self.state.fire_event(
            GameEvent(
                EventType.ENTERS_BATTLEFIELD, controller_id=ninja.controller_id,
                card_id=ninja.card.id, object=ninja.name, instance_id=ninja.instance_id,
                object_types=sorted(ninja.type_words),
            )
        )
        self.state.fire_event(
            GameEvent(
                EventType.ATTACKS, attacker=ninja.name, player_id=player.id,
                instance_id=ninja.instance_id, object_types=sorted(ninja.type_words),
                defending_player_id=getattr(self._defending_player(defender), "id", None),
            )
        )
    def _assign_defender(
        self, obj: GameObject, defender: Any, legal: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """Validate/normalize an attacker's declared defender (RULE 508.1a).

        With no defender given: auto-assign when exactly one is legal (the
        common two-player case — no need to make the player pick), a bare
        swing when none is legal (solo goldfish), and an error when the
        choice is ambiguous (2+ legal defenders — the UI must pass one).
        """
        if defender is None:
            if not legal:
                return None
            if len(legal) == 1:
                return dict(legal[0])
            raise ValueError(f"{obj.name} must choose which defender to attack")
        spec = self._defender_spec(defender)
        if not any(self._same_defender(spec, cand) for cand in legal):
            raise ValueError(f"{obj.name} cannot attack that defender")
        return spec
    @staticmethod
    def _defender_spec(defender: Any) -> dict[str, Any]:
        """Coerce a Player / planeswalker or battle `GameObject` / spec dict
        → a spec."""
        if isinstance(defender, dict):
            return dict(defender)
        if isinstance(defender, Player):
            return {"kind": "player", "id": defender.id, "label": defender.name}
        if isinstance(defender, GameObject):
            return {
                # RULE 310.5: a battle is its own defender kind — combat
                # damage to it removes defense counters (310.6) rather than
                # loyalty, and its "defending player" is its protector
                # (310.8d), neither of which the planeswalker branch does.
                "kind": "battle" if defender.is_battle else "planeswalker",
                "instance_id": defender.instance_id,
                "label": defender.name,
            }
        raise ValueError(f"invalid defender: {defender!r}")
    @staticmethod
    def _same_defender(a: dict[str, Any], b: dict[str, Any]) -> bool:
        if a.get("kind") != b.get("kind"):
            return False
        if a.get("kind") == "player":
            return a.get("id") == b.get("id")
        return a.get("instance_id") == b.get("instance_id")
    def _can_attack(
        self, player: Player, obj: GameObject, defending_player: Optional[Player] = None
    ) -> bool:
        """RULE 508.1a: whether ``obj`` may be declared as an attacker.

        ``defending_player`` is only needed by the *conditional* restrictions
        ("~ can't attack unless defending player controls an Island") — it
        can't be folded into the standing restriction at recompute time
        because it isn't known until a defender is assigned. Passing ``None``
        (the offer-time callers: `legal_actions`, `_enforce_attacks_if_able`)
        asks the weaker question "could this attack *somebody*", so a
        creature stays offered as long as at least one legal defender
        satisfies its condition; `declare_attackers` re-checks against the
        actual chosen defender.
        """
        return (
            obj.controller_id == player.id
            and obj.is_creature
            and obj in self.state.permanents()  # RULE 702.26c: excludes a phased-out creature
            and not obj.tapped
            # Haste (RULE 702.10b) lets a creature attack the turn it arrives.
            and (not obj.summoning_sick or combat.has_haste(obj))
            # Defender (RULE 702.3b) can never attack — unless something
            # grants "can attack as though it didn't have defender" (RULE
            # 508.1a permission, Colossus of Akros). The keyword itself
            # stays: this lifts the attack restriction only.
            and (
                not combat.has_defender(obj)
                or bool(combat.combat_restrictions(obj, "attacks_as_though_no_defender"))
            )
            # "~ can't attack." / "enchanted creature can't attack [or
            # block]." — a synthetic layer-6 flag, not a real keyword; see
            # `parser/oracle/catalogue/static_handlers.py`'s combat-
            # restriction family.
            and not combat.has(obj, "cant_attack")
            # RULE 701.35b: a detained permanent can't attack.
            and not combat.is_detained(obj)
            # "~ can't attack unless <condition>." — the parameterized
            # sibling of that flag (`GameObject.combat_restrictions`).
            and self._attack_conditions_ok(obj, player, defending_player)
            # "You can't attack that player this turn." (Call for Aid) —
            # RULE 508.1a, a player-pair bar. Only enforced once a defender
            # is actually assigned (offer-time, with `defending_player`
            # None, stays permissive — the player may still have another
            # legal opponent to swing at).
            and not (
                defending_player is not None
                and (player.id, getattr(defending_player, "id", None))
                in self.state.no_attack_pairs_this_turn
            )
            # "Each creature that's enchanted by an Aura you control can't
            # attack you or planeswalkers you control." (Eriette of the
            # Charmed Apple) / "Inklings can't attack you…" (Combat
            # Calligrapher) — RULE 508.1 standing bar, checked only once a
            # defender is assigned (offer-time stays permissive: the creature
            # may still have another legal opponent to swing at). Passed
            # `defender_kind="player"` here; every real card with this clause
            # also protects that player's planeswalkers (the default
            # ``player_or_planeswalker`` scope), so a `_defending_player`
            # standing in for a planeswalker defender is covered too.
            and not (
                defending_player is not None
                and continuous.defender_attack_prohibited(
                    self.state, obj, defending_player.id, "player"
                )
            )
        )
    def _attack_conditions_ok(
        self, obj: GameObject, player: Player, defending_player: Optional[Player]
    ) -> bool:
        """Every ``cant_attack_unless`` restriction on ``obj``, against a known
        defender — or, with none given, against *any* player it could attack
        (see `_can_attack`)."""
        restrictions = combat.combat_restrictions(obj, "cant_attack_unless")
        if not restrictions:
            return True
        if defending_player is not None:
            candidates = [defending_player]
        else:
            candidates = [p for p in self.state.players if p.id != player.id]
        return any(
            self._combat_restrictions_allow(
                obj, "cant_attack_unless", defending_player=candidate, attacker=obj
            )
            for candidate in candidates
        )
    def _combat_restrictions_allow(
        self,
        obj: GameObject,
        kind: str,
        defending_player: Optional[Player],
        attacker: Optional[GameObject] = None,
    ) -> bool:
        """Whether every ``kind`` (``cant_attack_unless``/``cant_block_unless``)
        restriction on ``obj`` has its condition met (RULE 508.1a/509.1a)."""
        for entry in combat.combat_restrictions(obj, kind):
            if not self._combat_condition_met(
                obj, entry.get("condition") or {}, defending_player, attacker
            ):
                return False
        return True
    #: The ``condition`` vocabulary a ``cant_attack_unless``/``cant_block_
    #: unless`` restriction may name — a whitelist, like every other spec
    #: string crossing the parser→engine boundary. Anything else is *not*
    #: silently treated as satisfied: `_combat_condition_met` returns False
    #: (the restriction bites), so a mis-parse fails closed toward "can't
    #: attack" rather than quietly deleting the restriction.
    _COMBAT_CONDITIONS: frozenset[str] = frozenset(
        {
            "defending_player_controls",
            "you_control",
            "more_creatures_than_opponent",
            "more_lands_than_opponent",
            "cards_in_graveyard",
            "cards_in_hand",
            "opponent_is_monarch",
            "opponent_is_poisoned",
            "creature_died_this_turn",
        }
    )

    def _combat_condition_met(
        self,
        obj: GameObject,
        condition: dict[str, Any],
        defending_player: Optional[Player],
        attacker: Optional[GameObject],
    ) -> bool:
        """Evaluate one ``unless`` condition against live game state.

        "Defending player" is `defending_player` when attacking; when this is
        a *blocking* restriction the printed subject is the attacking player
        instead, so both roles resolve through the same "the other player in
        this combat" reference (`opponent`) — RULE 508/509 phrase them
        symmetrically ("more creatures than defending player" /
        "…than attacking player") and every real card only ever names the
        one it isn't.
        """
        kind = str(condition.get("kind", ""))
        if kind not in self._COMBAT_CONDITIONS:
            return False
        try:
            controller = self.state.player_by_id(obj.controller_id)
        except KeyError:
            return False
        # The other side of this combat: the defender for an attack
        # restriction, the attacker's controller for a block restriction.
        opponent = defending_player
        if opponent is None and attacker is not None and attacker is not obj:
            opponent = self.state.player_by_id(attacker.controller_id)  # a block restriction
        mine = self.state.permanents_controlled_by(controller.id)

        if kind == "defending_player_controls":
            if opponent is None:
                return False
            return any(
                combat.matches_object_filter(o, condition.get("filter"))
                for o in self.state.permanents_controlled_by(opponent.id)
            )
        if kind == "you_control":
            filt = condition.get("filter")
            matches = [
                o for o in mine
                if combat.matches_object_filter(o, filt, reference=obj)
                and not (condition.get("other") and o is obj)
            ]
            return len(matches) >= int(condition.get("min", 1))
        if kind in ("more_creatures_than_opponent", "more_lands_than_opponent"):
            if opponent is None:
                return False
            attr = "is_creature" if kind.startswith("more_creatures") else "is_land"
            ours = sum(1 for o in mine if getattr(o, attr, False))
            theirs = sum(
                1 for o in self.state.permanents_controlled_by(opponent.id)
                if getattr(o, attr, False)
            )
            return ours > theirs
        if kind == "cards_in_graveyard":
            return self._count_in_range(len(controller.graveyard), condition)
        if kind == "cards_in_hand":
            return self._count_in_range(len(controller.hand), condition)
        if kind == "opponent_is_monarch":
            return opponent is not None and self.state.monarch_id == opponent.id
        if kind == "opponent_is_poisoned":
            # RULE 122/704.5c's "poisoned" — one or more poison counters.
            return opponent is not None and opponent.poison >= 1
        if kind == "creature_died_this_turn":
            # RULE 700.4-adjacent history question no live board can answer —
            # see `GameState.creatures_died_this_turn`. "under your control"
            # scopes it to the restricted creature's own controller.
            return self.state.creatures_died_this_turn.get(controller.id, 0) >= 1
        return False
    @staticmethod
    def _count_in_range(value: int, condition: dict[str, Any]) -> bool:
        """A ``min``/``max`` window over a counted quantity ("seven or more
        cards in your graveyard", "one or fewer cards in hand")."""
        minimum = condition.get("min")
        maximum = condition.get("max")
        if minimum is not None and value < int(minimum):
            return False
        if maximum is not None and value > int(maximum):
            return False
        return True
    def _attacking_alone(self, obj: GameObject) -> bool:
        """RULE 506.5-adjacent "attacking alone": ``obj`` is attacking and no
        other creature is (used by both the "can't attack alone" restriction
        and the `ATTACKS_ALONE` trigger event)."""
        attacking = [o for o in self.state.battlefield if o.attacking]
        return len(attacking) == 1 and attacking[0] is obj
    @staticmethod
    def _summoning_sick_for_tap(obj: GameObject) -> bool:
        """Whether summoning sickness stops ``obj`` paying a {T}/{Q} cost.

        RULE 302.6 / 602.5e: a creature can't activate an ability whose cost
        includes the tap or untap symbol unless its controller has controlled
        it continuously since their most recent turn began (i.e. it isn't
        summoning sick) — and this covers a creature's mana ability just as
        much as any other, since a mana ability *is* an activated ability
        (RULE 605.1a). Haste (RULE 702.10b) lifts the restriction, and
        non-creature permanents (lands, mana rocks) are never affected.
        """
        return obj.is_creature and obj.summoning_sick and not combat.has_haste(obj)
    def declare_blockers(self, player: Player, assignments: list[Any]) -> None:
        """Declare ``player``'s creatures as blockers (RULE 509).

        ``player`` is a *defending* player (not the active/attacking one).
        Each entry is a ``{"blocker": obj, "attacker": obj}`` dict or a
        ``(blocker, attacker)`` pair. A blocker may be assigned to an
        attacker only if that attacker is attacking this player (or a
        planeswalker they control). Additive, like `declare_attackers`.

        Goldfish's passive dummy never blocks, so in solo play this stays
        dormant; it's the engine half of interactive/multiplayer combat.
        """
        if self.state.current_step != "declare_blockers":
            raise ValueError("not in the declare-blockers step")
        if player is self.state.active_player:
            raise ValueError("the attacking player does not declare blockers")
        resolved: list[tuple[GameObject, GameObject]] = []
        for entry in assignments:
            if isinstance(entry, dict):
                blocker, attacker = entry["blocker"], entry["attacker"]
            else:
                blocker, attacker = entry
            if not self.can_block(player, blocker, attacker):
                raise ValueError(f"{blocker.name} cannot block {attacker.name}")
            resolved.append((blocker, attacker))

        # Menace (RULE 702.111b): a blocked menacing attacker must be blocked
        # by two or more creatures — and its printed-in-full siblings, "~
        # can't be blocked except by three or more creatures" (a higher
        # floor) and "~ can't be blocked by more than one creature" (a cap),
        # ride the same check via `combat.min_blockers`/`max_blockers`.
        # Validated over the resulting block — counting blockers already
        # assigned plus this call's — *before* any mutation, so an illegal
        # block leaves state untouched. (A whole legal block for one attacker
        # is therefore declared in one call, matching how the UI submits
        # blocks.)
        projected: dict[int, set[int]] = {}
        for blocker, attacker in resolved:
            projected.setdefault(attacker.instance_id, set(attacker.blocked_by)).add(
                blocker.instance_id
            )
        for attacker_id, blocker_ids in projected.items():
            attacker = self.state.find_object(attacker_id)
            if attacker is None:
                continue
            floor = combat.min_blockers(attacker)
            if len(blocker_ids) < floor:
                if combat.has_menace(attacker) and floor == 2:
                    raise ValueError(
                        f"{attacker.name} has menace and must be blocked by two or more creatures"
                    )
                raise ValueError(
                    f"{attacker.name} can't be blocked except by "
                    f"{floor} or more creatures"
                )
            cap = combat.max_blockers(attacker)
            if cap is not None and len(blocker_ids) > cap:
                raise ValueError(
                    f"{attacker.name} can't be blocked by more than {cap} creature(s)"
                )

        # RULE 509.1a: "~ can't block alone." — like its attacking sibling
        # this is a property of the whole block, so it's validated over the
        # projection above rather than per-assignment in `can_block`. Counts
        # every creature this player has blocking *after* this call, since
        # `declare_blockers` is additive too.
        projected_blockers = {b.instance_id for b, _ in resolved} | {
            o.instance_id
            for o in self.state.permanents_controlled_by(player.id)
            if combat.blocking_attacker_ids(o)
        }
        if len(projected_blockers) == 1:
            lone = self.state.find_object(next(iter(projected_blockers)))
            if lone is not None and combat.combat_restrictions(lone, "cant_block_alone"):
                raise ValueError(f"{lone.name} can't block alone")

        # RULE 702.130/702.45/702.23 (afflict/bushido/rampage): capture, before
        # any mutation, which attackers are transitioning from unblocked to
        # blocked this call — BECOMES_BLOCKED fires once per such attacker,
        # never once per blocker, only on that transition (RULE 509.5).
        newly_blocked = [
            attacker
            for attacker in {attacker.instance_id: attacker for _, attacker in resolved}.values()
            if not attacker.blocked_by
        ]

        for blocker, attacker in resolved:
            # RULE 509.1b multi-block permission: a blocker with room for
            # more than one (`extra_blocks`/`unlimited_blocks`) files every
            # attacker after its first onto `additional_blocking` instead —
            # an ordinary blocker (no such grant) only ever takes this
            # branch once, since `can_block` already refused a second
            # assignment past its capacity.
            if blocker.blocking is None:
                blocker.blocking = attacker.instance_id
            elif attacker.instance_id not in combat.blocking_attacker_ids(blocker):
                blocker.additional_blocking.append(attacker.instance_id)
            if blocker.instance_id not in attacker.blocked_by:
                attacker.blocked_by.append(blocker.instance_id)
            self.state.fire_event(
                GameEvent(
                    EventType.BLOCKS,
                    blocker=blocker.name,
                    player_id=player.id,  # RULE 509.1b: the blocker's controller
                    instance_id=blocker.instance_id,
                    object_types=sorted(blocker.type_words),
                )
            )

        for attacker in newly_blocked:
            blocker_count = len(attacker.blocked_by)
            self.state.fire_event(
                GameEvent(
                    EventType.BECOMES_BLOCKED,
                    attacker=attacker.name,
                    player_id=attacker.controller_id,  # the attacker's own controller
                    instance_id=attacker.instance_id,
                    object_types=sorted(attacker.type_words),
                    blocker_count=blocker_count,
                )
            )
            # RULE 702.23: Rampage's own per-firing dynamic pump — see
            # `RulesEngine.check_rampage` for why this can't go through the
            # ordinary annihilator/afflict/bushido `TriggeredAbility` path.
            self.rules.check_rampage(attacker, blocker_count)
        # RULE 509.1a: "declares no blocks" is itself a complete answer, so
        # this is stamped whether or not `assignments` was empty — the only
        # way `legal_actions_mixin` can tell "this player is done declaring
        # blockers for this combat" apart from "hasn't gone yet" once there's
        # nothing left on the board to mark (`GameState.
        # declared_blockers_this_combat`'s own docstring).
        self.state.declared_blockers_this_combat.add(player.id)
    def can_block(self, player: Player, blocker: GameObject, attacker: GameObject) -> bool:
        """RULE 509.1a: an untapped creature ``player`` controls may block an
        attacker that is attacking ``player`` (or a planeswalker they control,
        or a battle they *protect* — RULE 310.8c, which falls out of
        `_attacker_attacks_player` resolving a battle to its protector rather
        than needing its own check here).

        Plus the evasion half (RULE 509.1b): flying can only be blocked by
        flying/reach, protection stops a block by the protected-from quality
        (see `combat.can_block`), and landwalk (RULE 702.14b) makes the
        attacker unblockable while this player controls a land of that type.
        Menace — a *group* requirement — is checked over the whole assignment
        in `declare_blockers`, not here.
        """
        if combat.unblockable_by_landwalk(attacker, self._lands_controlled_by(player.id)):
            return False
        if getattr(attacker, "temp_unblockable", False):
            # "Target creature can't be blocked this turn" (Rogue's Passage) —
            # a resolve-time grant, unlike landwalk's static evasion above;
            # cleared at cleanup (RULE 514.2) like every other temp_* flag.
            return False
        if combat.has(attacker, "cant_be_blocked"):
            # "~ can't be blocked." / "equipped creature can't be blocked."
            # — the printed-static sibling of `temp_unblockable` above; see
            # `parser/oracle/catalogue/static_handlers.py`'s combat-
            # restriction family.
            return False
        if getattr(blocker, "temp_cant_block", False):
            # "Target creature can't block this turn" (Falter's whole family)
            # — the blocker-side mirror of `temp_unblockable` above, likewise
            # cleared at cleanup (RULE 514.2).
            return False
        if combat.combat_restrictions(attacker, "cant_be_blocked_if_attacking_alone") and (
            self._attacking_alone(attacker)
        ):
            # "~ can't be blocked as long as it's attacking alone." — a
            # conditional evasion, so it's re-asked per block declaration
            # rather than baked in at recompute time.
            return False
        if not combat.blocker_allowed(attacker, blocker, state=self.state):
            # RULE 509.1b's *qualified* restrictions ("can't be blocked by
            # creatures with power 3 or greater", "…except by Walls", or a
            # dynamic count-selector threshold — Kraken of the Straits).
            return False
        if not combat.blocker_may_block(blocker, attacker):
            # …and their mirror image printed on the blocker instead ("~ can
            # block only creatures with flying" — RULE 509.1a).
            return False
        if not self._combat_restrictions_allow(
            blocker, "cant_block_unless", defending_player=player, attacker=attacker
        ):
            # "~ can't block unless you control another Wolf." (RULE 509.1a)
            return False
        # RULE 701.51a, the Ring emblem's first ability: "Your Ring-bearer
        # is legendary and can't be blocked by creatures with greater
        # power." Read off live designation state rather than any permanent
        # (`continuous.ring_level_of`); its legendary half is layer 4.
        if continuous.ring_level_of(self.state, attacker) >= 1:
            if (blocker.power or 0) > (attacker.power or 0):
                return False
        return (
            blocker.controller_id == player.id
            and blocker.is_creature
            and blocker in self.state.permanents()  # RULE 702.26c: excludes a phased-out creature
            and not blocker.tapped
            # RULE 509.1b: ordinarily one block each — `has_block_capacity`
            # generalizes the old bare "not already blocking" check to honour
            # a "~ can block an additional creature"/"…any number of
            # creatures" grant (`GameObject.additional_blocking`).
            and combat.has_block_capacity(blocker)
            # "~ can't block." / "enchanted creature can't block [or
            # attack]." — a synthetic layer-6 flag, same family as above.
            and not combat.has(blocker, "cant_block")
            # RULE 701.60b: a suspected creature can't block.
            and not combat.is_suspected(blocker)
            # RULE 701.35b: a detained permanent can't block.
            and not combat.is_detained(blocker)
            and attacker.attacking
            and self._attacker_attacks_player(attacker, player)
            and combat.can_block(attacker, blocker)
        )
    def _lands_controlled_by(self, player_id: str) -> list[GameObject]:
        return [
            o for o in self.state.permanents()
            if o.is_land and o.controller_id == player_id
        ]
    def _defending_player(self, defender: Optional[dict[str, Any]]) -> Optional[Player]:
        """The player being attacked by an assigned ``combat_defender`` spec —
        the player themselves, or a defending planeswalker's controller (RULE
        508.1a's "defending player" covers both). ``None`` for a bare swing
        (solo goldfish, no legal defender at all).

        RULE 310.8d: for a **battle** the defending player is its *protector*,
        not its controller — which is the whole reason a Siege can be
        attacked by the player who controls it (310.8b). Everything that asks
        "who is the defending player" (block legality, "~ can't attack unless
        defending player controls…", Dethrone) goes through here, so that
        substitution only has to be made once.
        """
        if not defender:
            return None
        if defender.get("kind") == "player":
            try:
                return self.state.player_by_id(defender.get("id"))
            except KeyError:
                return None
        obj = self.state.find_object(defender.get("instance_id"))
        if obj is None:
            return None
        player_id = obj.protector_id if obj.is_battle else obj.controller_id
        if player_id is None:
            return None
        try:
            return self.state.player_by_id(player_id)
        except KeyError:
            return None
    def _attacker_attacks_player(self, attacker: GameObject, player: Player) -> bool:
        """Whether ``attacker`` is attacking ``player`` — directly, or via a
        permanent they're the defending player for (RULE 508.1a, and RULE
        310.8d for a battle they protect)."""
        defender = attacker.combat_defender
        if not defender:
            return False
        if defender.get("kind") == "player":
            return defender.get("id") == player.id
        return self._defending_player(defender) is player
