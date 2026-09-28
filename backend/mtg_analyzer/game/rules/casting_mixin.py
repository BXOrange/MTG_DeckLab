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

import dataclasses
import re
from contextlib import contextmanager
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
    ChooseBasicLandTypeReplacement,
    ChooseCardNameReplacement,
    ChooseColorReplacement,
    ChooseCreatureTypeReplacement,
    ChooseNamedModeReplacement,
    ChooseNumberReplacement,
    ChooseOpponentReplacement,
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
    ReturnToHandEffect,
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

#: RULE 702.108a Converge's colors — the five WUBRG colors, never colorless
#: ``"C"`` (`ManaPool.pool`'s own key vocabulary includes colorless, which
#: Converge explicitly doesn't count).
_FIVE_COLORS: tuple[str, ...] = ("W", "U", "B", "R", "G")

#: Adamant's payment fact needs the same five colours *and* colorless: one
#: printed rider (Desecrate Reality) asks whether three colorless mana paid
#: the spell.  Keep this separate from Converge's intentionally narrower
#: vocabulary above.
_ADAMANT_MANA_TYPES: tuple[str, ...] = ("C", *_FIVE_COLORS)


def _saga_final_chapter(card: Card) -> int:
    """The highest chapter number a Saga has (RULE 714.2c), 0 if unreadable.

    Read off the oracle text's roman-numeral chapter markers ("I —", "II, III —",
    "IV —"); the largest is the final chapter. Shares its numeral grammar with
    the oracle-parser front-end's chapter-ability recognition
    (`parser.oracle.catalogue.saga`, RULE 714.2d) rather than duplicating it."""
    return max(all_chapter_numbers(card.oracle_text or ""), default=0)


def _cast_history_traits(obj: "GameObject") -> dict[str, Any]:
    """The spell's colours and subtype words, stamped on its SPELL_CAST event so the
    per-turn history ("if an opponent has cast a blue or black spell this turn", "the
    first Dragon spell you cast each turn") is derivable from the event alone — the cast
    object is no longer findable once it has resolved."""
    return {
        "colors": sorted(obj.colors),
        "subtypes": obj.card.type_line.partition("—")[2].strip().lower().split(),
    }


def _targets_a_permanent(targets: Optional[list[Any]]) -> bool:
    """Whether a spell's chosen ``targets`` include at least one permanent
    (a `GameObject` currently on the battlefield) — RULE 608.2b's own
    reading of "a spell that targets one or more permanents" (Tiller of
    Flesh). Stamped onto the `SPELL_CAST` event so a "whenever you cast a
    spell that targets one or more permanents" trigger has a flag to key
    off, rather than re-deriving it from a stack item that may already be
    gone by the time the trigger resolves."""
    for t in targets or []:
        if isinstance(t, GameObject) and getattr(t, "zone", None) == Zone.BATTLEFIELD:
            return True
    return False


def _target_instance_ids(targets: Optional[list[Any]]) -> frozenset:
    """The `instance_id`s of a spell's chosen object targets — stamped onto
    the `SPELL_CAST` event so a Heroic-style "whenever you cast a spell that
    targets ~" trigger (RULE 702.34a's un-keyworded template — Akroan
    Skyguard / Battlewise Hoplite / Hero of Iroas) can tell whether the
    ability's own source was among them, without a lookup back to a stack
    item that may already have resolved."""
    return frozenset(
        t.instance_id for t in (targets or [])
        if isinstance(t, GameObject) and getattr(t, "instance_id", None) is not None
    )


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


#: RULE 305.6's five basic land types — the fixed, always-offered option list
#: for a "choose a basic land type" pick (PAR-4), unlike `_creature_type_
#: options`'s open-ended board scan: there's no analogous "irrelevant to
#: offer" case, since any of the five is always a legal, meaningful choice
#: regardless of what's actually on the board.
_BASIC_LAND_TYPE_OPTIONS: list[str] = ["Plains", "Island", "Swamp", "Mountain", "Forest"]




class CastingResolutionMixin:
    """Casting a spell onto the stack and resolving it, incl. RULE 614.1 entry-tapped/counters and every ETB interactive choice."""

    def _apply_entry_counters(self, obj: GameObject, x_paid: int = 0) -> None:
        """Put ``obj``'s RULE 614.1-style "enters with N counters" starting
        counters on it, read off its printed text.

        Called at every battlefield-entry site right after the tapped-entry
        check (`card_registry.enters_tapped`) and before ``obj`` is
        actually added to the battlefield, so the counters are already
        present when ENTERS_BATTLEFIELD fires and any trigger/continuous
        pass reads them. ``x_paid`` is the object's actual paid X (RULE
        107.3c) — 0 for anything that didn't just resolve off a cast-for-X
        (a token, a card reanimated/searched onto the battlefield, …).
        """
        # RULE 702.32a Fading N / RULE 702.61a Vanishing N: "this permanent
        # enters with N <fade|time> counters on it". Read off the parsed
        # keyword rather than the reminder text — the keyword *is* the rule,
        # and the reminder sentence isn't guaranteed to be printed.
        for kind, keyword in (("fade", "fading"), ("time", "vanishing")):
            param = (getattr(obj, "parametric_keywords", None) or {}).get(keyword)
            if param and int(param.get("n", 0) or 0) > 0:
                obj.add_counters(kind, int(param["n"]))

        condition = card_registry.entry_counters(obj.card)
        if condition is None:
            return
        if condition.get("kicked_gate") or condition.get("kicked_scale"):
            # RULE 702.33b: gated/scaled on how many times Kicker was paid
            # (`GameObject.kicker_count`, stamped at cast time) — 0 for
            # anything that didn't just resolve off a kicked cast (a token,
            # a card reanimated/searched onto the battlefield, …).
            kicker_count = getattr(obj, "kicker_count", 0) or 0
            if condition.get("kicked_x_scale"):
                # PAR-7: Kicker's own announced {X} (Emblazoned Golem), not a
                # fixed per-kick amount — `kicker_count` is still the gate
                # (0 unless kicked at all), but the amount comes from
                # `kicker_x_paid` instead of `condition["count"]`.
                amount = getattr(obj, "kicker_x_paid", 0) or 0 if kicker_count > 0 else 0
            elif condition.get("kicked_gate"):
                amount = condition["count"] if kicker_count > 0 else 0
            else:
                amount = condition["count"] * kicker_count
            grant_keyword = condition.get("grant_keyword")
            if grant_keyword and kicker_count > 0:
                # The same kicked gate as the counters, applied to a granted
                # keyword instead (RULE 702.33b's "...and with <keyword>."
                # tail) — a one-time additive mutation onto `intrinsic_
                # keywords`, not a continuous static: `kicker_count` never
                # changes after cast, so this is exact, not an
                # approximation, and it's read fresh every layer-engine
                # pass the same way a card's own printed flag keywords are
                # (`effect_binder.attach_to_object`'s flag-keyword handling).
                obj.intrinsic_keywords.add(grant_keyword)
        elif condition.get("cast_from_hand_gate"):
            amount = condition["count"] if getattr(obj, "was_cast_from_hand", False) else 0
        elif condition.get("revolt_gate"):
            # MEC-84 Revolt: ``count`` if a permanent left the battlefield
            # under this permanent's controller this turn, else 0. Read at
            # entry, the same "history question, gate at resolution" shape as
            # the kicked gate above.
            left = getattr(self.state, "permanents_left_battlefield_this_turn", None) or {}
            amount = condition["count"] if left.get(getattr(obj, "controller_id", None), 0) > 0 else 0
        elif condition.get("raid_gate"):
            # PAR-64 / Raid: the controller must have actually declared an
            # attacker this turn (RULE 508.1a), not merely put one attacking
            # onto the battlefield later.
            attacked = getattr(self.state, "players_attacked_this_turn", None) or set()
            amount = condition["count"] if getattr(obj, "controller_id", None) in attacked else 0
        elif condition.get("mana_color_spent_gate"):
            # Adamant reads an exact per-type payment amount, not Converge's
            # presence-only set.  Non-cast entries have an empty record.
            gate = condition["mana_color_spent_gate"]
            paid = getattr(obj, "mana_by_color_spent_to_cast", None) or {}
            amount = condition["count"] if int(paid.get(gate["color"], 0)) >= int(gate["amount"]) else 0
        elif condition.get("another_color_spell_unless"):
            color = str(condition["another_color_spell_unless"]).upper()
            counts = getattr(self.state, "spell_color_cast_counts_this_turn", None) or {}
            # This permanent's own spell was recorded at cast time, before
            # resolution.  The replacement therefore applies only if that
            # count has not reached two ("another" excludes this spell).
            amount = condition["count"] if int(
                (counts.get(getattr(obj, "controller_id", None), {}) or {}).get(color, 0)
            ) < 2 else 0
        elif condition.get("chosen_opponent_creatures_scale"):
            chosen_id = getattr(obj, "chosen_player_id", None)
            amount = condition["count"] * sum(
                1
                for permanent in self.state.battlefield
                if permanent.controller_id == chosen_id and permanent.is_creature
            )
        elif condition.get("colors_spent_scale"):
            # RULE 702.43a Sunburst: ``count`` per distinct colour of mana
            # actually spent to cast ``obj`` (`GameObject.colors_spent_to_
            # cast`, recorded by the mana-payment solver). 0 for a token /
            # reanimated / searched-in permanent that never paid a cost.
            colors = getattr(obj, "colors_spent_to_cast", None) or frozenset()
            amount = condition["count"] * len(colors)
        else:
            amount = x_paid if condition["is_x"] else condition["count"]
        if amount > 0:
            obj.add_counters(condition["counter_type"], amount)

    def _apply_granted_entry_counters(self, obj: GameObject) -> None:
        """MEC-56: any live ``extra_etb_counter`` static's contribution
        (Master Chef) — a *granted* sibling of `_apply_entry_counters`'
        printed-condition read, called at the same site right after it so
        the extra counter(s) are present before `obj` joins the
        battlefield/ENTERS_BATTLEFIELD fires, same as a printed one.
        """
        for kind, amount in continuous.extra_etb_counters_for(self.state, obj).items():
            if amount > 0:
                obj.add_counters(kind, amount)

    def enter_land_tapped(self, obj: GameObject) -> None:
        """Resolve ``obj``'s RULE 614.1 tapped-entry as it's played.

        The deterministic conditional shapes — check lands ("unless you
        control a Mountain or a Forest"), fast/slow lands ("unless you
        control two or fewer/more other lands", or the basic-land-counting
        variant, "… two or more basic lands") and Commander "Battlebond"
        lands ("unless you have two or more opponents") — are decided
        immediately off the board/game state ``obj``'s controller already
        has (`land_tap_condition` is read *before* ``obj`` itself is added
        to the battlefield, so "other lands" naturally excludes it). A
        shock land's "you may pay N life" is a genuine choice: ``obj``
        defaults tapped (as if declined) and a `land_tapped` `pending_choice`
        opens; `_resume_land_tapped` flips it untapped if the
        controller pays.
        """
        condition = card_registry.land_tap_condition(obj.card)
        kind = condition["kind"]
        if kind == "unless_types":
            types = condition["types"]
            controlled = [
                o
                for o in self.state.battlefield
                if o.is_land and o.controller_id == obj.controller_id
            ]
            obj.tapped = not any(
                any(t in o.card.type_line.lower() for t in types) for o in controlled
            )
        elif kind == "unless_count":
            type_word = condition.get("type")
            if type_word:
                # "Sanctuary" cycle (Mystic Sanctuary-shaped): counts only
                # lands whose subtype word matches (RULE 205.3i, after the
                # printed em dash) rather than any land or every basic.
                other_lands = sum(
                    1
                    for o in self.state.battlefield
                    if o.is_land
                    and o.controller_id == obj.controller_id
                    and type_word in o.card.type_line.lower()
                )
            elif condition.get("basic"):
                other_lands = sum(
                    1
                    for o in self.state.battlefield
                    if o.is_land
                    and o.controller_id == obj.controller_id
                    and "basic" in o.card.type_line.lower()
                )
            else:
                other_lands = sum(
                    1
                    for o in self.state.battlefield
                    if o.is_land and o.controller_id == obj.controller_id
                )
            if condition["cmp"] == "le":
                obj.tapped = not (other_lands <= condition["count"])
            else:
                obj.tapped = not (other_lands >= condition["count"])
        elif kind == "unless_opponents":
            # RULE 614.1 / Battlebond lands: untapped iff the game itself has
            # enough opponents — a property of the game, not the board.
            opponents = [
                p for p in self.state.living_players() if p.id != obj.controller_id
            ]
            obj.tapped = not (len(opponents) >= condition["count"])
        elif kind == "unless_opponents_count":
            # "Turbulent" land cycle: untapped iff the *total* lands across
            # all opponents (not the controller's own) compares as stated.
            opponent_lands = sum(
                1
                for o in self.state.battlefield
                if o.is_land and o.controller_id != obj.controller_id
            )
            if condition["cmp"] == "le":
                obj.tapped = not (opponent_lands <= condition["count"])
            else:
                obj.tapped = not (opponent_lands >= condition["count"])
        elif kind == "unless_life":
            # Innistrad "slow land" life cycle (Abandoned Campground &c):
            # untapped iff *any* player (RULE 614.1 — "a player", not
            # scoped to the controller) is at or below the threshold.
            obj.tapped = not any(
                p.life <= condition["count"] for p in self.state.living_players()
            )
        elif kind == "unless_turn_at_most":
            # Starting Town (MEC-43): untapped iff the game is still early.
            # **Documented simplification**: RULE 614.1's "your Nth turn"
            # means the controller's *own* turn count (RULE 500.1 — every
            # player's turn is a turn), which this engine tracks nowhere;
            # `GameState.turn_nr` ("how often the turn has come back
            # to whoever started", CLAUDE.md) is used as the proxy instead
            # — exact for the overwhelming common case (every seat started
            # together, nobody's mid-game player count changed), wrong only
            # if players joined/left after turn 1.
            obj.tapped = not (self.state.turn_nr <= condition["count"])
        elif kind == "pay_life":
            obj.tapped = True
            self._pending_land_choice_obj = obj
            self._pending_land_choice_amount = condition["amount"]
            self.open_choice(self._land_tapped_choice(obj, condition["amount"]))
        elif kind == "optional_bonus_rad":
            # Mariposa Military Base: the mirror image of a shock land —
            # untapped by default, with the controller able to choose
            # tapped instead for a rad-counter bonus.
            obj.tapped = False
            self._pending_land_choice_obj = obj
            self._pending_land_choice_amount = condition["amount"]
            self.open_choice(self._land_tapped_bonus_choice(obj, condition["amount"]))
        elif kind == "reveal_types":
            # "Reveal land" cycle: untapped iff the controller both *can*
            # (holds a matching card) and *chooses to* reveal one — unlike
            # `unless_types`, holding the card alone doesn't decide it, so
            # this only opens a choice when there's actually something to
            # reveal; with nothing to reveal there's no decision to make.
            obj.tapped = True
            types = condition["types"]
            player = self.state.player_by_id(obj.controller_id)
            has_match = any(
                any(t in c.card.type_line.lower() for t in types) for c in player.hand
            )
            if has_match:
                self._pending_land_choice_obj = obj
                self.open_choice(self._land_tapped_reveal_choice(obj))
        else:
            obj.tapped = kind == "always"
        if not obj.tapped:
            # RULE 614.1, board-wide: a *different* permanent's standing
            # effect ("Nonbasic lands your opponents control enter tapped."
            # — Archon of Emeria) can still force this land tapped even when
            # its own printed clause (if any) would have left it untapped —
            # a shock land's pending pay-life choice already defaults tapped
            # above, so this only ever adds a tap, never removes the choice.
            obj.tapped = continuous.enters_tapped_from_static(self.state, obj)
    def predict_land_tapped(self, obj: GameObject, card: Optional[Card] = None) -> Optional[bool]:
        """Read-only preview of `enter_land_tapped`'s RULE 614.1 outcome for
        ``obj`` as it currently sits — before it's actually played, and
        without mutating anything. Backs a `play_land` action's
        ``enters_tapped`` hint (`legal_actions_mixin._land_action`), which
        `services/bots.py`'s `GreedyBot` reads to prefer an untapped land
        when it has a choice.

        Mirrors every *deterministic* branch of `enter_land_tapped` (the
        check/fast/slow/Battlebond conditional shapes, read off the board
        exactly as playing the land would). The two genuine payment-choice
        kinds — a shock land's "you may pay N life", Mariposa Military
        Base's mirror-image "you may enter tapped for rad counters" — have
        no single answer before the choice is made, so those read as
        ``None`` rather than guessing; a client is free to treat that as
        "tied" against a known-untapped land.

        ``card`` previews a specific face (a modal DFC's back, `_face_card`)
        rather than ``obj.card`` — the same "rebind read-only" idiom
        `_cast_action`'s own ``face="back"`` preview uses.
        """
        card = card or obj.card
        condition = card_registry.land_tap_condition(card)
        kind = condition["kind"]
        if kind == "unless_types":
            types = condition["types"]
            controlled = [
                o for o in self.state.battlefield
                if o.is_land and o.controller_id == obj.controller_id
            ]
            tapped = not any(
                any(t in o.card.type_line.lower() for t in types) for o in controlled
            )
        elif kind == "unless_count":
            if condition.get("basic"):
                other_lands = sum(
                    1 for o in self.state.battlefield
                    if o.is_land and o.controller_id == obj.controller_id
                    and "basic" in o.card.type_line.lower()
                )
            else:
                other_lands = sum(
                    1 for o in self.state.battlefield
                    if o.is_land and o.controller_id == obj.controller_id
                )
            tapped = not (
                other_lands <= condition["count"] if condition["cmp"] == "le"
                else other_lands >= condition["count"]
            )
        elif kind == "unless_opponents":
            opponents = [p for p in self.state.living_players() if p.id != obj.controller_id]
            tapped = not (len(opponents) >= condition["count"])
        elif kind == "unless_opponents_count":
            opponent_lands = sum(
                1 for o in self.state.battlefield
                if o.is_land and o.controller_id != obj.controller_id
            )
            tapped = not (
                opponent_lands <= condition["count"] if condition["cmp"] == "le"
                else opponent_lands >= condition["count"]
            )
        elif kind == "unless_life":
            tapped = not any(
                p.life <= condition["count"] for p in self.state.living_players()
            )
        elif kind == "unless_turn_at_most":
            tapped = not (self.state.turn_nr <= condition["count"])
        elif kind in ("pay_life", "optional_bonus_rad", "reveal_types"):
            return None
        else:
            tapped = kind == "always"
        if not tapped:
            tapped = continuous.enters_tapped_from_static(self.state, obj)
        return tapped
    def _land_tapped_choice(self, obj: GameObject, amount: int) -> dict[str, Any]:
        """Build the `pending_choice` for a shock land's pay-life decision."""
        return {
            "kind": "land_tapped",
            "player_id": obj.controller_id,
            "prompt": f"{obj.name}: {amount} Leben zahlen, um ungetappt ins Spiel zu kommen?",
            "options": [
                {"id": "pay", "label": f"{amount} Leben zahlen"},
                {"id": "decline", "label": "Getappt ins Spiel kommen lassen"},
            ],
        }
    @continuations.choice("land_tapped", answer=continuations.ANSWER_STR, rule="614.1")
    def _resume_land_tapped(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending shock-land `land_tapped` choice.

        ``answer`` is ``"pay"`` to pay the life and keep it untapped, or
        anything else (``None``/``"decline"``) to leave it tapped — already
        the default `enter_land_tapped` set while the choice was open.
        """
        obj = self._pending_land_choice_obj
        amount = self._pending_land_choice_amount
        self._pending_land_choice_obj = None
        self._pending_land_choice_amount = 0
        if obj is not None and answer == "pay":
            player = self.state.player_by_id(obj.controller_id)
            self.lose_life(player, amount, cause="cost")
            obj.tapped = False
    def _land_tapped_bonus_choice(self, obj: GameObject, amount: int) -> dict[str, Any]:
        """Build the `pending_choice` for Mariposa Military Base's own
        "you may have this enter tapped, for a bonus" decision — the
        mirror image of `_land_tapped_choice`'s shock-land prompt."""
        return {
            "kind": "land_tapped_bonus",
            "player_id": obj.controller_id,
            "prompt": f"{obj.name}: getappt ins Spiel kommen lassen, um {amount} "
                      "Rad-Marken zu erhalten?",
            "options": [
                {"id": "tap", "label": f"Getappt ins Spiel kommen lassen ({amount} Rad-Marken)"},
                {"id": "decline", "label": "Ungetappt ins Spiel kommen lassen"},
            ],
        }
    @continuations.choice("land_tapped_bonus", answer=continuations.ANSWER_STR, rule="614.1")
    def _resume_land_tapped_bonus(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `land_tapped_bonus` choice (Mariposa Military
        Base). ``answer`` is ``"tap"`` to enter tapped and get the rad
        counters, or anything else (``None``/``"decline"``) to stay
        untapped (already the default `enter_land_tapped` set while the
        choice was open) with no bonus.
        """
        obj = self._pending_land_choice_obj
        amount = self._pending_land_choice_amount
        self._pending_land_choice_obj = None
        self._pending_land_choice_amount = 0
        if obj is not None and answer == "tap":
            obj.tapped = True
            player = self.state.player_by_id(obj.controller_id)
            self.add_player_counters(player, amount, "rad", source=obj)
    def _land_tapped_reveal_choice(self, obj: GameObject) -> dict[str, Any]:
        """Build the `pending_choice` for a "reveal land"'s reveal-or-not
        decision (only opened when the controller actually holds a matching
        card — see `enter_land_tapped`)."""
        return {
            "kind": "land_tapped_reveal",
            "player_id": obj.controller_id,
            "prompt": f"{obj.name}: eine passende Karte aus der Hand zeigen, "
                      "um ungetappt ins Spiel zu kommen?",
            "options": [
                {"id": "reveal", "label": "Karte zeigen"},
                {"id": "decline", "label": "Getappt ins Spiel kommen lassen"},
            ],
        }
    @continuations.choice("land_tapped_reveal", answer=continuations.ANSWER_STR, rule="614.1")
    def _resume_land_tapped_reveal(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending "reveal land" `land_tapped_reveal` choice.

        ``answer`` is ``"reveal"`` to reveal a matching card and enter
        untapped, or anything else (``None``/``"decline"``) to leave it
        tapped — already the default `enter_land_tapped` set while the
        choice was open. No specific card is named (RULE 614.1 doesn't
        distinguish *which* matching card was revealed — only that one was),
        matching the read-only `has_match` check that opened the choice.
        """
        obj = self._pending_land_choice_obj
        self._pending_land_choice_obj = None
        if obj is not None and answer == "reveal":
            obj.tapped = False
    def is_permanent_spell(self, card: Card) -> bool:
        """A spell that becomes a permanent on resolution (RULE 608.3)."""
        return not (card.is_instant or card.is_sorcery)
    def cast_spell(
        self,
        player: Player,
        obj: GameObject,
        targets: Optional[list[Any]] = None,
        x: int = 0,
        cost: Optional[ManaCost] = None,
        target_groups: Optional[list[list[Any]]] = None,
    ) -> StackItem:
        """Pay the cost, move the card to the stack (RULE 601).

        ``x`` is the announced value (RULE 601.2b) for a cost containing
        ``{X}``; ignored otherwise. ``cost`` lets the caller supply an already
        adjusted cost (X resolved, static reductions applied — RULE 601.2f);
        omitted, the printed cost is used. Timing/priority legality is enforced
        by the caller; this performs the mechanical cast. Raises ValueError if
        the mana cost can't be paid.

        ``target_groups``, when given, partitions ``targets`` per targeting
        effect — see `StackItem.target_groups`. Needed only when ``obj``
        carries 2+ *different* targeting effects; omitted (``None``), every
        effect reads ``targets`` directly, unchanged from before this existed.
        ``targets`` itself is derived as the flattened union when not given
        explicitly, so `check_ward` below and every other flat-``targets``
        consumer still sees every chosen target.
        """
        if target_groups is not None and targets is None:
            targets = [t for group in target_groups for t in group]
        if cost is None:
            cost = self.mana_cost_of(obj.card)
            if cost.has_variable:
                cost = cost.with_x(x)
        # RULE 702.88b Rebound: cast from hand arms the "exile instead of
        # graveyard, then reopen a free-cast window next upkeep" behaviour
        # `resolve_top_of_stack` checks for below — recast later from that
        # same window (zone already EXILE here), Rebound doesn't repeat.
        if getattr(obj, "has_rebound", False) and obj.zone == Zone.HAND:
            obj.rebound_pending = True
        obj.was_cast_from_hand = obj.zone == Zone.HAND
        # RULE 702.88b's own free-cast window (`ReboundFreeCastWindowEffect`)
        # — consumed the instant it's used, same "check, then discard" shape
        # `mana_wildcard_permission`'s per-card grant already uses.
        free_cast = obj.instance_id in self.state.free_cast_instance_ids
        if free_cast:
            life_spent = 0
        else:
            allows_restriction = restriction_predicate_for_cast(obj, has_x=cost.has_variable)
            # RULE 605.1a "you may spend mana as though it were mana of any
            # color/type" (Mnemonic Betrayal-shaped), scoped to casting this
            # one exiled card — see `GameState.mana_wildcard_permission`.
            wildcard = self.state.mana_wildcard_permission.get(obj.instance_id)
            # PAR-19: "Spend only mana produced by basic lands/creatures to
            # cast this spell." (Imperiosaur/Myr Superion) — a standing
            # restriction on the spell's own printed cost, bound onto the
            # object by `effect_binder.attach_to_object` as a plain
            # attribute (`GameObject.mana_source_kind_restriction`), same
            # "dynamic, getattr-read" convention `alt_cast_cost`/
            # `alt_cast_condition` already use.
            require_source_kind = getattr(obj, "mana_source_kind_restriction", None)
            # MEC-43: K'rrik, Son of Yawgmoth's standing "pay 2 life instead
            # of a {B} pip" permission (`continuous.life_for_mana_pip_color`).
            extra_life_color = continuous.life_for_mana_pip_color(self.state, player)
            if not player.mana_pool.can_pay(
                cost, life_available=player.life, allows_restriction=allows_restriction, wildcard=wildcard,
                require_source_kind=require_source_kind, extra_life_color=extra_life_color,
            ):
                raise ValueError(f"{player.id} cannot pay for {obj.name}")
            # RULE 702.108a Converge: which colors actually paid for this
            # cast, including whatever colors happened to cover the generic
            # portion — `ManaPool.pay()` itself only tracks colors spent on
            # *constrained* pips (`_find_payment`'s own ``colored_spends``),
            # so this diffs the pool before/after instead of touching the
            # payment solver (`GameObject.colors_spent_to_cast`).
            pool_before = dict(player.mana_pool.pool)
            snow_before = sum(player.mana_pool.snow_pool.values())
            treasure_before = sum(player.mana_pool.pool_by_source.get("treasure", {}).values())
            life_spent = player.mana_pool.pay(
                cost, life_available=player.life, allows_restriction=allows_restriction, wildcard=wildcard,
                require_source_kind=require_source_kind, extra_life_color=extra_life_color,
            )
            obj.colors_spent_to_cast = frozenset(
                color for color in _FIVE_COLORS
                if pool_before.get(color, 0) > player.mana_pool.pool.get(color, 0)
            )
            obj.mana_by_color_spent_to_cast = {
                mana_type: pool_before.get(mana_type, 0) - player.mana_pool.pool.get(mana_type, 0)
                for mana_type in _ADAMANT_MANA_TYPES
                if pool_before.get(mana_type, 0) > player.mana_pool.pool.get(mana_type, 0)
            }
            # MEC-43 round 3: the snow sibling of the Converge diff just
            # above (`GameObject.mana_spent_to_cast_snow`).
            obj.mana_spent_to_cast_snow = snow_before - sum(player.mana_pool.snow_pool.values())
            obj.mana_spent_to_cast_treasure = (
                treasure_before - sum(player.mana_pool.pool_by_source.get("treasure", {}).values())
            )
        self.lose_life(player, life_spent, cause="cost")
        if free_cast:
            self.state.free_cast_instance_ids.discard(obj.instance_id)
            self.state.free_cast_ignore_timing_instance_ids.discard(obj.instance_id)
        # RULE 601.2b: remember the announced X on the object itself (not
        # just this ephemeral StackItem) — an "unless its controller pays
        # {X}" tied to *this* spell's own X (Logic Knot's Delve-adjacent
        # template) needs it after the spell has already left the stack.
        obj.x_paid = x
        # RULE 202.1/601.2h: how much mana was actually spent — 0 for a free
        # cast, otherwise the resolved value of the cost that was paid
        # (already X-resolved and reduction-adjusted by the caller).
        # `ManaCost.resolved_value`, not `converted_mana_cost` — the latter
        # deliberately keeps reporting 0 for `{X}` (RULE 202.3b's printed-
        # cost model), which would silently undercount an {X} spell's own
        # real spend (Mockingbird-shaped: "mana value <= the amount of mana
        # spent to cast this creature"). Read by the "if no mana was spent
        # to cast it" trigger family via the `SPELL_CAST` event's
        # ``mana_spent`` key below.
        obj.mana_spent_to_cast = 0 if free_cast else cost.resolved_value

        # RULE 601.2a: which zone the spell was cast *from* — snapshotted
        # before the move below, since by the time `SPELL_CAST` fires the
        # object already sits on the stack. "Whenever a player casts a spell
        # from their hand" (Possibility Storm) reads it as the event's
        # ``from_hand`` key.
        from_hand = obj.zone == Zone.HAND
        cast_from_zone = obj.zone.value
        obj.cast_from_exile = obj.zone == Zone.EXILE
        obj.was_cast = True
        # Zone-agnostic (not just hand/command) so an Adventure creature can
        # be cast from exile (RULE 715.3d) with no dedicated branch here.
        self._remove_from_current_zone(player, obj)
        obj.adventure_castable = False
        if obj.prepared_source_id is not None:
            # RULE 722.3c: the source loses "prepared" the moment its
            # exiled copy becomes cast — not when the copy later resolves.
            source = self.state.find_object(obj.prepared_source_id)
            if source is not None:
                source.prepared = False
        obj.zone = Zone.STACK
        item = StackItem(
            kind="spell",
            controller_id=player.id,
            effects=self._effects_for_spell(obj),
            obj=obj,
            description=obj.name,
            targets=targets,
            x=x,
            target_groups=target_groups,
        )
        self.state.stack.append(item)
        self._note_crime(item)
        self.state.record_stat(
            player.id, "spell", cmc=obj.card.converted_mana_cost, name=obj.name
        )
        self.state.fire_event(
            GameEvent(
                EventType.SPELL_CAST, player_id=player.id, card_id=obj.card.id, spell=obj.name,
                instance_id=obj.instance_id, object_types=sorted(obj.type_words),
                mana_spent=obj.mana_spent_to_cast,
                from_hand=from_hand,
                # PAR-119: the zone the spell was cast from ("from your graveyard", "from anywhere other than your hand").
                from_zone=cast_from_zone,
                # RULE 601.2a: cast from exile (Passionate Archaeologist's
                # granted "whenever you cast a spell from exile" trigger).
                from_exile=getattr(obj, "cast_from_exile", False),
                # "…where X is that spell's mana value" (Shark Typhoon-shaped
                # spell-cast payoffs) — read live off the event rather than
                # requiring a lookup back to a stack item that may have
                # already resolved and left the stack by the time a
                # triggered ability referencing it does.
                mana_value=obj.card.converted_mana_cost,
                # "Whenever you cast a spell with {X} in its mana cost, …"
                # (Elementalist's Palette, the Quandrix {X}-first-spell
                # cluster, PAR-60) — read off the printed mana cost string
                # rather than whether an X was actually announced, so a
                # {0}-for-X cast still counts (RULE 107.3).
                has_x="{X}" in (getattr(obj.card, "mana_cost_string", "") or "").upper(),
                # "your first spell with {X} in its mana cost each turn"
                # (PAR-60) — true only for this player's first {X} cast this
                # turn; the tracker is bumped just below, after the event.
                first_x_spell=(
                    "{X}" in (getattr(obj.card, "mana_cost_string", "") or "").upper()
                    and player.id not in self.state.cast_x_spell_this_turn
                ),
                # "…with mana value, power, or toughness equal to the chosen
                # number…" (Talion, the Kindly Lord, MEC-43) — the spell's
                # own printed characteristics, read live off `GameObject.
                # power`/`toughness`'s existing off-battlefield fallback
                # (a stack-zoned object reports its printed P/T, `None` for
                # a noncreature spell, correctly never matching either).
                power=obj.power,
                toughness=obj.toughness,
                # "Whenever you cast a spell that targets one or more
                # permanents, incubate 2." (Tiller of Flesh) — RULE 608.2b.
                targets_a_permanent=_targets_a_permanent(targets),
                target_instance_ids=_target_instance_ids(targets),
                # What `GameState`'s per-turn cast tallies (`turn_history`) read back.
                **_cast_history_traits(obj),
            )
        )
        self.check_ward(item, player)
        return item
    def cast_without_paying(
        self,
        player: Player,
        obj: GameObject,
        targets: Optional[list[Any]] = None,
        target_groups: Optional[list[list[Any]]] = None,
    ) -> StackItem:
        """Cast a card *without paying its mana cost* (RULE 118.9 / 601.3b).

        The free-cast half of the cast/put/draw split: unlike a "put onto the
        battlefield" (a direct zone change, no stack), this is a real cast —
        the card goes on the **stack** and resolves normally (a permanent ends
        up on the battlefield firing `ENTERS_BATTLEFIELD`, an instant/sorcery
        applies its effects then hits the graveyard). It fires `SPELL_CAST`
        with ``free=True`` so a "when you cast" trigger still sees it.

        Reusable by every free-cast mechanic — cascade, discover, "you may
        cast it without paying its mana cost", suspend — from whatever zone
        the card currently sits in (hand, exile, library, graveyard).

        ``target_groups`` partitions ``targets`` per targeting effect exactly
        as in `cast_spell` — a free cast of a two-requirement spell is still
        a cast of that spell.
        """
        if target_groups is not None and targets is None:
            targets = [t for group in target_groups for t in group]
        from_hand = obj.zone == Zone.HAND
        cast_from_zone = obj.zone.value
        obj.cast_from_exile = obj.zone == Zone.EXILE
        obj.was_cast = True
        self._remove_from_current_zone(player, obj)
        obj.zone = Zone.STACK
        # RULE 108.4 / 601.2f: whoever casts the spell controls it (and the
        # permanent it may become). Usually a no-op — a free cast is nearly
        # always of the caster's own card — but not when casting a card out
        # of *another* player's graveyard/exile (Memory Vampire, Mnemonic
        # Betrayal), where ``owner_id`` stays that other player but control
        # passes to ``player``.
        obj.controller_id = player.id
        # RULE 202.1: a free cast spends no mana at all — the "if no mana was
        # spent to cast it" family (Lavinia/Boromir) keys off this rather
        # than ``free``, since a *paid* cast can also come to 0 (see
        # `EventType.SPELL_CAST`).
        obj.mana_spent_to_cast = 0
        item = StackItem(
            kind="spell",
            controller_id=player.id,
            effects=self._effects_for_spell(obj),
            obj=obj,
            description=obj.name,
            targets=targets,
            target_groups=target_groups,
        )
        self.state.stack.append(item)
        self._note_crime(item)
        self.state.fire_event(
            GameEvent(
                EventType.SPELL_CAST,
                player_id=player.id,
                card_id=obj.card.id,
                spell=obj.name,
                instance_id=obj.instance_id,
                object_types=sorted(obj.type_words),
                free=True,
                mana_spent=0,
                from_hand=from_hand,
                # PAR-119: the zone the spell was cast from ("from your graveyard", "from anywhere other than your hand").
                from_zone=cast_from_zone,
                # RULE 601.2a: cast from exile (Passionate Archaeologist's
                # granted "whenever you cast a spell from exile" trigger).
                from_exile=getattr(obj, "cast_from_exile", False),
                # See the matching comment on `cast_spell`'s own SPELL_CAST
                # firing — a free cast is still a cast (RULE 601.2f/118.9)
                # for Talion, the Kindly Lord's own "whenever an opponent
                # casts a spell with mana value, power, or toughness equal
                # to the chosen number" purposes.
                power=obj.power,
                toughness=obj.toughness,
                has_x="{X}" in (getattr(obj.card, "mana_cost_string", "") or "").upper(),
                first_x_spell=(
                    "{X}" in (getattr(obj.card, "mana_cost_string", "") or "").upper()
                    and player.id not in self.state.cast_x_spell_this_turn
                ),
                targets_a_permanent=_targets_a_permanent(targets),
                target_instance_ids=_target_instance_ids(targets),
                # What `GameState`'s per-turn cast tallies (`turn_history`) read back.
                **_cast_history_traits(obj),
            )
        )
        self.check_ward(item, player)
        return item
    @contextmanager
    def graveyard_exit_batch(self):
        """Group simultaneous graveyard exits into one RULE 603.3f event."""
        depth = getattr(self, "_graveyard_exit_batch_depth", 0)
        if depth == 0:
            self._graveyard_exit_batch_cards: list[dict[str, Any]] = []
        self._graveyard_exit_batch_depth = depth + 1
        try:
            yield
        finally:
            self._graveyard_exit_batch_depth -= 1
            if self._graveyard_exit_batch_depth == 0:
                cards = self._graveyard_exit_batch_cards
                self._graveyard_exit_batch_cards = []
                if cards:
                    self.state.fire_event(GameEvent(EventType.CARDS_LEFT_GRAVEYARD, cards=cards))

    def _note_graveyard_exit(self, obj: GameObject) -> None:
        """Record a card leaving its owner's graveyard before it becomes new.

        This is called from the one zone-removal choke point, covering casts,
        reanimation, exile, shuffle-in and any future route using it.
        """
        card = {
            "instance_id": obj.instance_id,
            "mana_value": int(getattr(obj.card, "converted_mana_cost", 0) or 0),
            "owner_id": obj.owner_id,
            "graveyard_owner_id": obj.owner_id,
        }
        # RULE 603.3f per-turn tracker for "if a card left your graveyard
        # this turn" intervening-ifs (reset each `begin_turn`).
        self.state.cards_left_graveyard_this_turn.add(obj.owner_id)
        if getattr(self, "_graveyard_exit_batch_depth", 0):
            self._graveyard_exit_batch_cards.append(card)
        else:
            self.state.fire_event(GameEvent(EventType.CARDS_LEFT_GRAVEYARD, cards=[card]))

    def _remove_from_current_zone(self, player: Player, obj: GameObject) -> None:
        """Pull ``obj`` out of whichever zone currently holds it.

        Checks *every* player's zones, not just ``player``'s own — usually
        the same thing (a card sits in its owner's zone, and ``player`` is
        that owner), but not always: a Ragavan/Mnemonic Betrayal-shaped
        temp play/cast permission (`exile_with_play_permission`/
        `exile_graveyard_with_cast_permission`) can let ``player`` cast a
        card actually sitting in a *different* player's exile zone (RULE
        400.3: a card's zone is keyed by its owner, not by whoever currently
        has permission to play it).

        RULE 400.7: leaving its zone also turns a face-down exiled card
        (Beseech the Mirror) face up — nothing stays face down across a zone
        change, and this is the one point every cast path funnels through.
        """
        obj.face_down_in_exile = False
        left_graveyard = obj.zone == Zone.GRAVEYARD
        for candidate in self.state.players:
            for cards in candidate.zones.values():
                if obj in cards:
                    cards.remove(obj)
                    if left_graveyard:
                        self._note_graveyard_exit(obj)
                    return
        if obj in self.state.battlefield:
            self.state.remove_from_battlefield(obj)
    def _attachment_kind(self, obj: GameObject) -> Optional[str]:
        """The attachment family this object uses (Aura/Equipment/etc.)."""
        if not hasattr(obj, "parametric_keywords"):
            return None
        keywords = obj.parametric_keywords or {}
        for name in ("enchant", "equip", "fortify", "reconfigure"):
            if name in keywords:
                return name
        return None
    def _attachment_legal(self, obj: GameObject, target: Any) -> bool:
        """Whether ``obj`` can legally attach to ``target`` (basic MVP rules)."""
        kind = self._attachment_kind(obj)
        # RULE 303.4a/702.5: a Curse Aura's ``Enchant player`` target is a
        # player, not a permanent. Its attachment identity is the stable
        # player id (parallel to a permanent's instance id); unlike a normal
        # Aura host it has no protection/phase/type state to re-check.
        if isinstance(target, Player):
            quality = str(((obj.parametric_keywords or {}).get("enchant") or {}).get(
                "quality", ""
            )).strip().lower()
            return kind == "enchant" and quality == "player" and not target.has_lost
        if target not in self.state.permanents():
            return False  # RULE 702.26c: can't attach to a phased-out permanent
        if target.is_battle:
            # RULE 310.9: a battle can't be attached to, full stop. The
            # equip/reconfigure branches below already exclude it by
            # requiring a creature; this is what stops a broadly-worded Aura
            # ("enchant permanent") from landing on one.
            return False
        if kind is None:
            return False
        if is_protected_from(target, obj) and not (
            kind == "enchant" and getattr(obj, "_protection_self_exempt", False)
        ):
            # RULE 702.16c/d: protection from ``obj``'s stated quality means
            # ``target`` can't be enchanted/equipped/fortified by it — checked
            # here rather than only at target-selection time so a permanent
            # that *gains* protection after ``obj`` is already attached is
            # caught by the RULE 704.5m/n re-validation in
            # `_revalidate_attachments`. RULE 702.16n/p's own carve-out
            # ("This effect doesn't remove this Aura.") is the
            # `_protection_self_exempt` exception below it.
            return False
        if kind == "equip":
            # RULE 301.5b/702.6a: "target creature you control" — control
            # of the creature matters both when the ability is activated
            # and when it resolves, which is why this is re-checked here
            # rather than only at offer time (`targeting.legal_targets`).
            # Only the Equipment's own controller may activate its equip
            # ability (RULE 301.5d), so that's the controller who must
            # match — not necessarily the target's *owner*.
            return target.is_creature and target.controller_id == obj.controller_id
        if kind == "reconfigure":
            # RULE 702.151a: "another target creature you control."
            return (
                target.is_creature
                and target.controller_id == obj.controller_id
                and target is not obj
            )
        if kind == "fortify":
            # RULE 702.67a: "target land you control."
            return target.is_land and target.controller_id == obj.controller_id
        if kind == "enchant":
            enchant_params = (obj.parametric_keywords or {}).get(kind) or {}
            quality = str(enchant_params.get("quality", "")).strip().lower()
            # RULE 303.4c/704.5m (bug report, 2026-09-04, same gap as
            # `targeting.legal_targets`' own enchant dispatch): "Enchant
            # creature you control"/"… you don't control"/"… an opponent
            # controls" is a real attachment restriction, re-checked here
            # too so an Aura whose enchanted permanent's controller changes
            # after attachment (a control-magic effect, say) correctly
            # becomes illegally attached and falls off via SBA, not just
            # rejected at the original target-selection offer.
            enchant_controller = enchant_params.get("controller")
            if enchant_controller == "you" and target.controller_id != obj.controller_id:
                return False
            if enchant_controller == "not_you" and target.controller_id == obj.controller_id:
                return False
            if not quality or quality in {"permanent", "anything"}:
                return True
            if quality == "creature":
                return target.is_creature
            if quality == "artifact":
                return target.card.is_artifact
            if quality == "enchantment":
                return target.card.is_enchantment
            if quality == "land":
                return target.is_land
            if quality == "planeswalker":
                return target.is_planeswalker
            return True
        return True
    def attach_to_target(self, obj: GameObject, target: Any) -> bool:
        """Attach an Aura/Equipment-like object to a legal target (RULE 303/301.5)."""
        if not self._attachment_legal(obj, target):
            return False
        obj.attached_to = target.id if isinstance(target, Player) else target.instance_id
        return True

    def _begin_bestow(self, obj: GameObject) -> None:
        """RULE 702.103b: reshape ``obj`` into a bestowed Aura spell — an
        Aura enchantment that gains "enchant creature" and stops being a
        creature (`GameObject.bestowed` → `is_creature` False, RULE
        702.103d). The synthetic ``parametric_keywords["enchant"]`` entry
        is what every existing Aura code path keys off (attachment kind,
        `targeting.spell_target_specs`, the resolve-time attach), so nothing
        downstream needs a bestow special case. Undone by `_end_bestow`.
        """
        obj.bestowed = True
        obj.parametric_keywords = {
            **(obj.parametric_keywords or {}),
            "enchant": {"quality": "creature", "bestow": True},
        }

    def _end_bestow(self, obj: GameObject) -> None:
        """RULE 702.103e/f: ``obj`` ceases to be bestowed — it stops being
        an Aura and is a creature again, staying on the battlefield. Removes
        only the synthetic "enchant" entry `_begin_bestow` added (a real
        Aura card never carries Bestow, so this can't strip a printed one).
        """
        obj.bestowed = False
        enchant = (obj.parametric_keywords or {}).get("enchant")
        if isinstance(enchant, dict) and enchant.get("bestow"):
            obj.parametric_keywords.pop("enchant", None)
    def _detach_attachments_from(self, host: GameObject) -> None:
        """Unattach permanents attached to ``host`` when it leaves the battlefield.

        RULE 704.5m: an Aura not attached to a legal object goes to its
        owner's graveyard. RULE 704.5n: an Equipment or Fortification (which
        includes a Reconfigure permanent acting as one, RULE 702.151b) merely
        becomes unattached and remains on the battlefield.
        """
        for attached in list(self.state.permanents()):
            if attached.attached_to != host.instance_id:
                continue
            attached.attached_to = None
            if getattr(attached, "is_licid_aura", False):
                # MEC-47: a Licid whose host left — clear the flag so its
                # `for_as_long_as` type-change static self-sweeps and a
                # later reanimation comes back a plain creature.
                attached.is_licid_aura = False
            if getattr(attached, "bestowed", False):
                # RULE 702.103f: a bestowed Aura that becomes unattached
                # ceases to be bestowed and stays on the battlefield as a
                # creature — the exception to RULE 704.5m below.
                self._end_bestow(attached)
            elif self._attachment_kind(attached) == "enchant":
                self._move_to_graveyard(attached)
    def _revalidate_attachments(self) -> bool:
        """RULE 704.5m/n: unattach any permanent whose attachment has become
        illegal since it was attached, with its *host* still on the
        battlefield (a host that leaves is `_detach_attachments_from`'s job).

        Checked against the same `_attachment_legal` an initial attach uses,
        so any new legality rule added there (protection, quality, control)
        is re-validated here for free. Returns on the first permanent it
        unattaches, matching every other SBA check's "one action, then
        re-check the whole board" cadence.
        """
        for attached in self.state.permanents():
            host_id = attached.attached_to
            if host_id is None:
                continue
            player_host = next((p for p in self.state.players if p.id == host_id), None)
            if player_host is not None:
                if self._attachment_legal(attached, player_host):
                    continue
                attached.attached_to = None
                if self._attachment_kind(attached) == "enchant":
                    self._move_to_graveyard(attached)
                return True
            host = self._object_by_instance_id(host_id)
            if host is None or host not in self.state.battlefield or host.phased_out:
                # Host leaving the battlefield is `_detach_attachments_from`'s
                # job; a phased-out host (RULE 702.26g/`PhaseOutAllYouControl
                # Effect`) took `attached` phased-out with it, so `attached`
                # is already absent from `self.state.permanents()` in the
                # normal case — this guards the same-host-different-
                # controller edge no shipped card reaches yet.
                continue
            if self._attachment_legal(attached, host):
                continue
            attached.attached_to = None
            if getattr(attached, "bestowed", False):
                # RULE 702.103f: an exception to RULE 704.5m — the bestowed
                # Aura becomes unattached and stays on the battlefield as a
                # creature rather than being put into its owner's graveyard.
                self._end_bestow(attached)
                return True
            if getattr(attached, "is_licid_aura", False):
                # MEC-47: a Licid whose host left is an Aura attached to
                # nothing → owner's graveyard (RULE 704.5m). Clear the flag
                # so its `for_as_long_as` type-change static self-sweeps and
                # a later reanimation comes back a plain creature.
                attached.is_licid_aura = False
            if self._attachment_kind(attached) == "enchant":
                self._move_to_graveyard(attached)  # RULE 704.5m
            return True  # RULE 704.5n: Equipment/Fortification just unattaches
        return False
    @staticmethod
    def _effects_for_spell(obj: GameObject) -> list[Any]:
        """Effects a spell applies when it resolves.

        For a permanent spell this is empty (resolving just puts it onto
        the battlefield); instants/sorceries carry their oracle-derived
        effects here once oracle-text parsing exists (docs/07 PART 5). The
        game object's own ``static_effects`` list is used as a hook so
        tests/fixtures can attach behavior without a parser yet.
        """
        return list(getattr(obj, "spell_effects", []))
    @staticmethod
    def _substitute_x(effects: list[Any], x: int) -> None:
        """Replace the ``"x"``/``"-x"`` sentinel amount/count/power/
        toughness on any of ``effects`` with the spell/ability's actually-
        announced {X} (RULE 107.3c/601.2b) — ``"-x"`` is its negation, for
        an X-scaled *debuff* whose X isn't itself negative (Toxic Deluge's
        "All creatures get -X/-X", where X comes from an ``additional_cost``
        life payment, not a mana ``{X}``, but is threaded through the exact
        same ``obj.x_paid``/`StackItem.x` mechanism regardless).
        ``"half_x_up"``/``"half_x_down"`` are the division-of-X sentinels
        (Contaminated Drink's "you get half X rad counters, rounded up") —
        no real card needs a plain (non-X) division yet, so this only
        covers the {X}-scaled case. ``"kicker_x"`` (PAR-17) is a
        *different* X — Kicker's own announced ``{X}`` (PAR-7's
        `GameObject.kicker_x_paid`), read off the effect's own ``source``
        rather than this stack item's ``x`` param, since a triggered
        ability's "if it was kicked, put X counters on it" was never
        itself cast/activated for X — only Kicker's separate cost was.

        Mirrors `_apply_entry_counters`'s ``is_x``-flag idiom, just generic
        over every one-shot effect's magnitude field instead of one
        hand-authored counter clause — a real int param never equals the
        literal string ``"x"``/``"-x"``, so this can't misfire on an
        unrelated ``amount``/``count``/``power``/``toughness`` value.

        Also walks a ``filter``/``criteria`` dict attribute (`DestroyEffect`/
        `ExileEffect`'s mass-wipe filter, `SearchLibraryEffect`'s search
        criteria) for an ``"x"``/``"-x"``/``"source_x_paid"``/
        ``"colors_spent_to_cast"`` sentinel on its own ``max_mana_value``/
        ``min_mana_value`` key — "destroy all creatures with mana value X
        or less" (Meltdown), "search your library for a creature card with
        mana value X or less" (Green Sun's Zenith/Chord of Calling/Finale
        of Devastation), and RULE 702.108a Converge's own count (Bring to
        Light, MEC-41) all need the substitution one level deeper than a
        plain effect attribute, which the per-``attr`` loop
        below can't reach on its own.

        Unwraps a `ConditionalEffect` (RULE 702.33b's "if it was kicked, …"
        wrapper) to reach the magnitude field on its ``inner`` effect —
        the wrapper itself never carries one, so without this an
        X-scaled inner effect's sentinel would never actually get
        substituted (caught by an execute-level test, not the parse-level
        ones: PAR-17's "if it was kicked, draw X cards" left `DrawCardEffect.
        count` as the literal string ``"kicker_x"`` until this was added).
        """
        for wrapper in effects:
            effect = wrapper
            while hasattr(effect, "inner"):
                effect = effect.inner
            for dict_attr in ("filter", "criteria"):
                mapping = getattr(effect, dict_attr, None)
                if not isinstance(mapping, dict):
                    continue
                for mv_key in ("max_mana_value", "min_mana_value"):
                    mv_value = mapping.get(mv_key)
                    if mv_value == "x":
                        mapping[mv_key] = x
                    elif mv_value == "-x":
                        mapping[mv_key] = -x
                    elif mv_value == "source_x_paid":
                        # "search … for a creature card with mana value X or
                        # less" on a *later-firing* triggered ability (RULE
                        # 601.2b/603.1 — Invasion of Ikoria's own ETB, not
                        # part of the original casting resolution at all) —
                        # this stack item's own ``item.x`` is 0 (a trigger
                        # was never cast with an announced X), so the real
                        # value has to come from the permanent's own
                        # `GameObject.x_paid` (stamped once at cast time,
                        # `RulesEngine.cast_spell`) instead.
                        mapping[mv_key] = getattr(effect.source, "x_paid", 0) or 0
                    elif mv_value == "colors_spent_to_cast":
                        # RULE 702.108a Converge — "…mana value less than or
                        # equal to the number of colors of mana spent to
                        # cast this spell." (Bring to Light, MEC-41). A
                        # *count* of the resolving spell's own
                        # `GameObject.colors_spent_to_cast` (diffed off the
                        # payer's `ManaPool` at `RulesEngine.cast_spell`),
                        # not an X at all — reuses this same substitution
                        # choke point since it's the identical "criteria's
                        # own mana-value bound, known only at resolution"
                        # shape ``"x"``/``"source_x_paid"`` already cover.
                        mapping[mv_key] = len(
                            getattr(effect.source, "colors_spent_to_cast", None) or ()
                        )
            # "Exile target artifact, creature, or enchantment with mana
            # value X or less." (March of Otherworldly Light, MEC-43) — the
            # identical sentinel shape as ``filter``/``criteria`` just
            # above, but `ExileEffect`/`DestroyEffect`'s own ``max_mana_
            # value``/``min_mana_value`` folds straight into their
            # `TargetSpec` at construction time (a genuine RULE 115
            # target-offer cap, not a mass-selector filter), so it needs
            # its own substitution site rather than sharing the ``filter``/
            # ``criteria`` dict loop above.
            target_spec = getattr(effect, "target_spec", None)
            if target_spec is not None:
                # `TargetSpec` is a frozen dataclass — `dataclasses.replace`
                # builds the substituted copy rather than mutating in place.
                updates: dict[str, int] = {}
                for mv_key in ("max_mana_value", "min_mana_value"):
                    mv_value = getattr(target_spec, mv_key, None)
                    if mv_value == "x":
                        updates[mv_key] = x
                    elif mv_value == "-x":
                        updates[mv_key] = -x
                if updates:
                    effect.target_spec = dataclasses.replace(target_spec, **updates)
            for attr in ("amount", "count", "power", "toughness", "times"):
                value = getattr(effect, attr, None)
                if value == "x":
                    setattr(effect, attr, x)
                elif value == "-x":
                    setattr(effect, attr, -x)
                elif value == "half_x_up":
                    setattr(effect, attr, -(-x // 2))  # ceiling division
                elif value == "half_x_down":
                    setattr(effect, attr, x // 2)
                elif value == "kicker_x":
                    # RULE 702.33b/PAR-17: "if it was kicked, <effect scaled
                    # by X>" (Kangee, Aerie Keeper/Verdeloth the Ancient-
                    # shaped) — a *different* X than the spell/ability's own
                    # ``x`` above (Emblazoned Golem's Kicker {X}, PAR-7's
                    # `GameObject.kicker_x_paid`), read off the effect's own
                    # source rather than this stack item's announced ``x``,
                    # since a triggered ability was never itself "cast for
                    # X" — only Kicker's own separate {X} was.
                    setattr(effect, attr, getattr(effect.source, "kicker_x_paid", 0) or 0)
                elif value == "cycling_x":
                    # RULE 702.28c: "when you cycle this card, create an
                    # X/X ... token" (Shark Typhoon) — the same shape as
                    # ``kicker_x`` just above: the *Cycling* cost's own
                    # announced {X} (`GameObject.cycling_x_paid`, stamped by
                    # `GameEngine._pay_activation_cost`), not this stack
                    # item's own ``x`` — a "when you cycle" trigger's own
                    # StackItem was never itself activated for X, only the
                    # separate Cycling activation was.
                    setattr(effect, attr, getattr(effect.source, "cycling_x_paid", 0) or 0)
            # "When you next cast an instant or sorcery spell this turn, copy that spell X
            # times." (Storm King's Thunder, PAR-124) — the sentinel isn't on this top-level
            # `CreateTurnTriggerEffect` itself but nested in `inner_specs`' raw `{"type",
            # "params"}` dicts, built into a real effect only once its own trigger fires
            # (`CreateTurnTriggerEffect.apply`) — long after this spell's own `x` is gone.
            # Substituted here, at this earlier point where `x` is still known, the same way
            # every other sentinel on this spell's effects is.
            for inner_spec in getattr(effect, "inner_specs", None) or []:
                params = inner_spec.get("params") if isinstance(inner_spec, dict) else None
                if not isinstance(params, dict):
                    continue
                for attr in ("amount", "count", "power", "toughness", "times"):
                    value = params.get(attr)
                    if value == "x":
                        params[attr] = x
                    elif value == "-x":
                        params[attr] = -x
    def resolve_top_of_stack(self) -> Optional[StackItem]:
        """Resolve the topmost stack object (RULE 608). Returns it, or None."""
        if not self.state.stack:
            return None
        item = self.state.stack.pop()  # LIFO
        # RULE 603.1: expose the firing event for exactly this resolution, so
        # an effect that genuinely depends on *this* firing can read it
        # (`GameContext.trigger_event`). Restored rather than cleared,
        # because resolving one item can recursively resolve another.
        outer_trigger_event = self.context.trigger_event
        outer_resolving_controller_id = self.context.resolving_controller_id
        self.context.trigger_event = item.trigger_event
        self.context.resolving_controller_id = item.controller_id
        try:
            return self._apply_stack_item(item)
        finally:
            self.context.trigger_event = outer_trigger_event
            self.context.resolving_controller_id = outer_resolving_controller_id
    #: `GameState.deferred_effects` frame kinds (ENG-35).
    #:
    #: ``"tail"`` is the original and still the overwhelmingly common shape:
    #: the *rest of a flat effect list*, parked by
    #: `_apply_effects_partitioned` at the position a choice opened. An entry
    #: with no ``kind`` key is a tail — old snapshots and every existing
    #: caller keep working untouched.
    #:
    #: ``"iteration"`` is what `14_` S1 means by making this **structure-
    #: aware**, and it is the piece ENG-37 blocks on. A tail can only say
    #: "continue after position N of one list"; it has no way to say *resume
    #: this body for item k, then run it again for k+1*. That is exactly what
    #: a `for_each` node needs (a body that may pause inside any iteration),
    #: and what `optional` needs to re-enter a body after a yes/no answer.
    #: Nesting itself already worked — `deferred_effects` is a LIFO stack, so
    #: an inner pause parks before the outer one and pops first — the missing
    #: piece was never the stack, only the loop counter.
    DEFERRED_TAIL = "tail"
    DEFERRED_ITERATION = "iteration"

    def defer_iteration(
        self,
        effects: list["GameEffect"],
        items: list[Any],
        *,
        index: int = 0,
        source: Optional[GameObject] = None,
        targets: Optional[list[Any]] = None,
        specs: Optional[list[dict[str, Any]]] = None,
        item_as_target: bool = False,
    ) -> None:
        """Park a loop body so it resumes at ``items[index]`` (ENG-35).

        The structure-aware counterpart to `_apply_effects_partitioned`'s
        tail parking. `resume_deferred_effects` runs the body once per
        remaining item, re-parking with an advanced ``index`` each time the
        body pauses on a choice — so a `for_each` whose body asks a question
        gets one prompt per item, in order, instead of losing its place.

        The current item is exposed to the body as
        `GameContext.iteration_item`, which is how a body clause names
        "that creature" / "that player" for the iteration it is running in.

        ENG-37 added the two keyword-only options a `for_each` node needs.
        ``specs`` parks the body as `EffectSpec`-shaped dicts instead of
        built effects, so **each iteration builds its own**: a `GameEffect`
        is not always reusable across passes (`SacrificeEffect` and friends
        stash per-pass remainders on themselves), and a spec list is plain
        data that survives the `state.clone()` undo takes. ``item_as_target``
        hands the current item to the body as its ``targets`` — which is what
        lets an ordinary registered effect ("draw a card", "deal 2 damage")
        serve as a loop body with no knowledge that it is in one.
        """
        if index >= len(items):
            return
        self.state.deferred_effects.append({
            "kind": self.DEFERRED_ITERATION,
            "effects": list(effects),
            "specs": [dict(d) for d in specs] if specs is not None else None,
            "items": list(items),
            "index": index,
            "source": source,
            "targets": targets,
            "item_as_target": bool(item_as_target),
        })

    @continuations.choice(
        "composite_optional",
        answer=continuations.ANSWER_FLAG,
        yes="yes",
        rule="601.2b",
    )
    def _resume_composite_optional(self, choice: dict[str, Any], accepted: bool = False) -> None:
        """Answer an ``optional`` composition node (ENG-37, RULE 601.2b).

        Declining does nothing at all, which is what "you may" means — there
        is no "if you don't" branch here; a card printing one spells it as an
        ``if_else`` around the same question.

        The body runs through `_apply_effects_partitioned`, not a plain
        `apply` loop, so a body that itself opens a choice parks the rest of
        itself the same way it would have at the top level.
        """
        if not accepted:
            return
        specs = choice.get("effect_specs") or []
        if not specs:
            return
        source = self.state.find_object(choice.get("source_id"))             if choice.get("source_id") is not None else None
        # RULE 608.2h: the resolution that chose this referent is over, so it
        # is re-found by id — a target that has since left is simply dropped,
        # the same last-known-information handling every resumed branch does.
        previous = [
            obj for obj in (
                self.state.find_object(instance_id)
                for instance_id in (choice.get("previous_target_ids") or [])
            ) if obj is not None
        ]
        from ..binding.core import build_effects  # function-scoped: binder cycle
        from ...parser.oracle.spec import EffectSpec

        built = build_effects(
            [EffectSpec(type=d["type"], params=dict(d.get("params") or {}),
                        condition=d.get("condition"))
             for d in specs],
            source,
        )
        # RULE 601.2c/608.2h: the announced targets, re-found by id across the
        # pause. One that has left a zone is dropped rather than substituted —
        # the same last-known-information handling as the referent above.
        announced = [
            obj for obj in (
                self.state.find_object(instance_id)
                for instance_id in (choice.get("target_ids") or [])
            ) if obj is not None
        ]
        revealed_id = choice.get("revealed_card_id")
        revealed = self.state.find_object(revealed_id) if revealed_id is not None else None
        # PAR-117: "its controller may `<effect>`" — the same RULE 603.1
        # referent that picked *who* is asked (`OptionalEffect.apply`'s own
        # ``player`` resolution) is what the body itself acts as ("its
        # controller" both chooses and does), so a body clause reading
        # ``{"of": "entering", …}`` (`DrawCardEffect.player`/
        # `CreateTokenEffect.creators="trigger_subject_controller"`) needs
        # `context.trigger_event` live again — restored to a minimal
        # synthetic event naming just the referent object, the same
        # RULE 608.2h re-find-by-id treatment `previous`/`revealed` above
        # already get, not the full original `DAMAGE`/… payload (gone by
        # now, and unneeded — every reader of this referent only ever asks
        # "what object", never a field off the original event itself).
        outer_trigger_event = self.context.trigger_event
        referent_subject_id = choice.get("referent_subject_id")
        if referent_subject_id is not None:
            self.context.trigger_event = {"instance_id": referent_subject_id}
        try:
            _apply_effects_partitioned(
                built, self.context, announced or None, None, source=source,
                previous_targets=previous, revealed_card=revealed,
            )
        finally:
            self.context.trigger_event = outer_trigger_event

    def _resume_iteration(self, frame: dict[str, Any]) -> None:
        """Run one iteration of a parked loop body, then queue the next.

        The next iteration is parked *before* the body runs, so that if the
        body pauses on a choice its own tail parks on top of it and pops
        first — the same innermost-first ordering `resume_deferred_effects`
        already relies on. Running the body first and parking afterwards
        would invert that and interleave the iterations.
        """
        items = frame["items"]
        index = frame["index"]
        if index >= len(items):
            return
        if index + 1 < len(items):
            self.defer_iteration(
                frame["effects"], items, index=index + 1,
                source=frame.get("source"), targets=frame.get("targets"),
                specs=frame.get("specs"),
                item_as_target=bool(frame.get("item_as_target")),
            )
        item = items[index]
        specs = frame.get("specs")
        if specs is not None:
            # Built fresh for this pass — see `defer_iteration`'s ``specs``.
            from ..binding.core import build_effects  # function-scoped: binder cycle
            from ...parser.oracle.spec import EffectSpec

            effects = build_effects(
                [EffectSpec(type=d["type"], params=dict(d.get("params") or {}),
                            condition=d.get("condition"))
                 for d in specs],
                frame.get("source"),
            )
        else:
            effects = list(frame["effects"])
        targets = [item] if frame.get("item_as_target") else frame.get("targets")
        outer_item = getattr(self.context, "iteration_item", None)
        self.context.iteration_item = item
        try:
            _apply_effects_partitioned(
                effects,
                self.context,
                targets,
                None,
                source=frame.get("source"),
            )
        finally:
            self.context.iteration_item = outer_item

    def resume_deferred_effects(self) -> bool:
        """Pick a suspended effect list back up (RULE 608.2), innermost first.

        `_apply_effects_partitioned` parks the remainder of a resolution
        whenever one of its effects opens a `pending_choice`, because the
        game state holds only one at a time — a second interactive effect
        running now would overwrite the first player's prompt. Called by
        `GameEngine.resolve_until_stable` once nothing is pending, it drains
        one entry (which may itself pause again and re-park what's left of
        it). Returns whether anything was resumed.

        ENG-35: an entry is now one of two **frame kinds** (`DEFERRED_TAIL`
        / `DEFERRED_ITERATION`) rather than always the tail of a flat list.
        Everything below the dispatch is the original tail path, unchanged.

        The resumed effects run *outside* the `GameContext.trigger_event`
        window their original resolution had — an effect that reads the
        firing event has to be the one that pauses, not one after it. No
        shipped card is shaped that way; the alternative (persisting the
        event through the suspension) would have to survive the state
        `clone()` that undo takes, which the event object is not built for.

        MEC-37 (Doomsday): a parked entry belonging to a top-level *spell*
        (as opposed to a triggered/activated ability) also carries that
        spell's own `StackItem`. If the drained remainder finishes with
        nothing left to pause on, `_finish_spell_routing` runs here — the
        spell was not actually done resolving (RULE 608.2m) while its own
        interactive effect was still open, so routing it to the graveyard/
        etc. had to wait for exactly this moment rather than happening
        eagerly back when `_apply_stack_item` first paused on it.
        """
        if self.state.pending_choice or not self.state.deferred_effects:
            return False
        resumed = self.state.deferred_effects.pop()
        if resumed.get("kind") == self.DEFERRED_ITERATION:
            self._resume_iteration(resumed)
            return True
        stack_item = resumed.get("stack_item")
        deferred_again = _apply_effects_partitioned(
            resumed["effects"],
            self.context,
            resumed["targets"],
            resumed["target_groups"],
            source=resumed.get("source"),
            group_index=resumed.get("group_index", 0),
            previous_targets=resumed.get("previous_targets"),
            created_objects=resumed.get("created_objects"),
            life_lost_this_way=resumed.get("life_lost_this_way", 0),
            permanents_destroyed_this_way=resumed.get("permanents_destroyed_this_way", 0),
            objects_exiled_this_way=resumed.get("objects_exiled_this_way", 0),
            counters_removed_this_way=resumed.get("counters_removed_this_way", 0),
            damaged_this_way=resumed.get("damaged_this_way"),
            previous_selector=resumed.get("previous_selector"),
            revealed_card=resumed.get("revealed_card"),
            clash_won=resumed.get("clash_won"),
            clashed_opponent=resumed.get("clashed_opponent"),
            stack_item=stack_item,
        )
        if not deferred_again and stack_item is not None:
            # RULE 608.2m: this remainder just finished with nothing left
            # to pause on — the spell it belongs to is only *now* actually
            # done resolving, so route it to its next zone (ordinarily the
            # graveyard) here, the same tail `_apply_stack_item` runs
            # synchronously when nothing pauses at all.
            if not self._finish_spell_routing(stack_item):
                self.check_state_based_actions()
        return True
    def _apply_stack_item(self, item: StackItem) -> Optional[StackItem]:
        """Apply an already-popped stack item's effects and route the card
        that produced it (RULE 608.2m/608.3) — `resolve_top_of_stack`'s body,
        split out only so that method can wrap it in the
        `GameContext.trigger_event` window."""
        if len(item.effects) == 1 and hasattr(item.effects[0], "effects"):
            # A single `TriggeredAbility`/`ActivatedAbility` wrapper — it
            # owns its *own* sub-effects list (`self.effects`, invisible to
            # this loop), so the per-effect partitioning has to happen one
            # level down, inside its own `apply()` (`_apply_effects_
            # partitioned`). Pass `target_groups` straight through rather
            # than treating the wrapper itself as "one targeting effect".
            self._substitute_x(item.effects[0].effects, item.x)
            item.effects[0].apply(self.context, item.targets, item.target_groups)
        else:
            self._substitute_x(item.effects, item.x)
            # RULE 115.1/601.2c: each effect gets only *its own* slice of
            # the partitioned targets, not the whole shared list — see
            # `StackItem.target_groups`. Shared with the nested (wrapper)
            # path above so both get the same partitioning *and* the same
            # RULE 608.2 suspend-on-pending-choice behaviour. ``stack_item``
            # (MEC-37) is what lets `resume_deferred_effects` find its way
            # back here once a paused remainder finally finishes.
            if _apply_effects_partitioned(
                item.effects, self.context, item.targets, item.target_groups, stack_item=item,
            ):
                # RULE 608.2m: one of this spell's own effects opened an
                # interactive choice — it isn't actually done resolving
                # yet, so routing it to the graveyard/etc. now would be
                # premature (and, for a search naming the caster's own
                # graveyard, visibly wrong: the still-resolving spell would
                # show up as a candidate in its own search). `resume_
                # deferred_effects` finishes the routing once the paused
                # remainder truly drains.
                return item

        if not self._finish_spell_routing(item):
            self.check_state_based_actions()
        return item
    def _finish_spell_routing(self, item: StackItem) -> bool:
        """RULE 608.2m/608.3: send a resolved spell to its next zone
        (ordinarily the graveyard) now that every one of its effects has
        actually happened — split out of `_apply_stack_item` so `resume_
        deferred_effects` can reach the exact same tail once a deferred
        remainder it was waiting on finally finishes. Returns whether it
        already ran its own state-based-action check (the permanent-spell
        branch, self-contained since it may itself pause on an
        `enter_as_copy` choice — RULE 614.1c/614.12), so the caller knows
        not to run a second, redundant one.
        """
        if item.kind != "spell" or item.obj is None:
            return False
        obj = item.obj
        if self.is_permanent_spell(obj.card):
            self._resolve_permanent_spell(item, obj)
            return True
        if obj.adventure_snapshot is not None:
            # RULE 715.3d: the Adventure instant/sorcery resolved — exile
            # the card (as the creature, not the spell half) instead of
            # the graveyard; it may be cast as the creature from there.
            snapshot = obj.adventure_snapshot
            obj.adventure_snapshot = None
            self.restore_face(obj, snapshot)
            self.exile(obj)
            obj.adventure_castable = True
        elif obj.buyback_paid:
            # RULE 702.27a: Buyback's additional cost was paid at cast
            # time — return the card to its owner's hand instead of the
            # graveyard, reusing the same zone-routing `return_to_hand`
            # an Unsummon-style bounce uses.
            obj.buyback_paid = False
            self.return_to_hand(obj)
        elif obj.cast_via_flashback:
            # RULE 702.34a: a spell cast via Flashback is exiled instead
            # of going to the graveyard when it resolves.
            obj.cast_via_flashback = False
            self.exile(obj)
        elif obj.rebound_pending:
            # RULE 702.88b: a Rebound spell cast from hand is exiled
            # instead of going to the graveyard, then a delayed trigger
            # reopens its free-cast window at the controller's next
            # upkeep (`ReboundFreeCastWindowEffect`).
            obj.rebound_pending = False
            self.exile(obj)
            self.state.delayed_triggers.append(
                DelayedTrigger(
                    controller_id=obj.controller_id,
                    step="upkeep",
                    scope="controller",
                    effects=[ReboundFreeCastWindowEffect(source=obj)],
                    description=f"{obj.name}: ohne Bezahlen der Manakosten aus dem Exil wirken",
                )
            )
        elif obj.zone != Zone.STACK:
            # One of this instant/sorcery's own resolving effects already
            # moved it elsewhere — a trailing "Exile ~." self-exile
            # clause (Mnemonic Betrayal/Teferi's Protection-shaped,
            # `ExileEffect`'s ``target_kind=None`` self mode) is the only
            # shape that does this today. Honour it instead of also
            # routing the card to the graveyard afterward.
            pass
        else:
            self._move_to_graveyard(obj)
        self.state.fire_event(
            GameEvent(EventType.SPELL_RESOLVED, spell=obj.name, controller_id=item.controller_id)
        )
        return False
    def _resolve_permanent_spell(self, item: StackItem, obj: GameObject) -> None:
        """Finish resolving a permanent spell (RULE 608.3): summoning
        sickness, RULE 614.1 tapped-entry, the battlefield zone change,
        Aura attachment, and the ENTERS_BATTLEFIELD/SPELL_RESOLVED events.

        If ``obj`` carries an `enter_as_copy_effects` "you may have this
        enter as a copy of target X" (RULE 614.1c/614.12) and/or
        `enter_choice_effects` "as ~ enters, choose a creature type/color"
        (RULE 601.2b), those choices must be resolved *first* — before the
        object is ever added to the battlefield/fires ENTERS_BATTLEFIELD as
        itself — unlike every other resolution path here, this can pause on
        a `pending_choice` (possibly more than one, in sequence) and resume
        later from `_resume_enter_as_copy`/`_resume_choose_creature_type`.
        """
        def _finish() -> None:
            if obj.cast_via_mutate:
                # RULE 702.140b-d: a mutate spell never enters the
                # battlefield as its own permanent — it merges onto the
                # creature it targeted, which stays the surviving object
                # (and so fires no ENTERS_BATTLEFIELD, RULE 702.140c).
                obj.cast_via_mutate = False
                host = next((t for t in item.targets if isinstance(t, GameObject)), None)
                if host is not None and host in self.state.permanents():
                    self.mutate_onto(obj, host, under=obj.mutate_under)
                else:
                    # RULE 608.2b: the mutate target is gone, so the spell
                    # resolves as an ordinary creature spell instead.
                    obj.summoning_sick = True
                    self.state.add_to_battlefield(obj)
                self.state.fire_event(
                    GameEvent(
                        EventType.SPELL_RESOLVED,
                        spell=obj.name,
                        controller_id=item.controller_id,
                    )
                )
                self.check_state_based_actions()
                return
            obj.summoning_sick = True
            # RULE 614.1: either the object's own printed tapped-entry
            # clause, or a *different* permanent's board-wide standing
            # effect ("Artifacts your opponents control enter tapped." —
            # Manglehorn/Dauntless Dismantler/Archon of Emeria-shaped).
            obj.tapped = card_registry.enters_tapped(obj.card) or continuous.enters_tapped_from_static(
                self.state, obj
            )
            self._apply_entry_counters(obj, x_paid=getattr(obj, "x_paid", 0) or 0)
            self._apply_granted_entry_counters(obj)
            # RULE 702.155b/714.3b: Read Ahead's chosen count (if any —
            # `_offer_read_ahead` stashes it here) replaces the ordinary
            # single lore counter `add_to_battlefield` would otherwise seed —
            # RULE 702.155a means only the chapter matching that exact count
            # fires; every lower chapter is skipped outright, not merely
            # delayed, so this must never let the default chapter-1 firing
            # happen first.
            read_ahead_count = self._pending_read_ahead_count
            self._pending_read_ahead_count = None
            self.state.add_to_battlefield(obj, saga_lore_override=read_ahead_count)
            if self._attachment_kind(obj) == "enchant":
                targets = [t for t in item.targets if isinstance(t, (GameObject, Player))]
                target = targets[0] if targets else None
                # RULE 303.4f (MEC-34): "Enchant creature card in a
                # graveyard" — the target isn't a permanent at all, so it
                # can never attach the ordinary way. Leave the Aura on the
                # battlefield unattached instead of sending it straight back
                # to the graveyard for the "failed" attach: its own "when
                # this enters" ability (queued by the ENTERS_BATTLEFIELD
                # event just below) is what reanimates the stashed target
                # and attaches this Aura to the result.
                target_in_graveyard = isinstance(target, GameObject) and target.zone == Zone.GRAVEYARD
                if target_in_graveyard:
                    obj.reanimate_target_id = target.instance_id
                elif not (target is not None and self.attach_to_target(obj, target)):
                    if getattr(obj, "bestowed", False):
                        # RULE 702.103e/608.3b: a bestowed Aura spell whose
                        # target is illegal as it begins resolving ceases to
                        # be bestowed and finishes resolving as a creature
                        # spell — it enters the battlefield rather than
                        # fizzling. Fall through to the ordinary ETB below.
                        self._end_bestow(obj)
                    else:
                        self._move_to_graveyard(obj)
                        self.state.fire_event(
                            GameEvent(
                                EventType.SPELL_RESOLVED,
                                spell=obj.name,
                                controller_id=item.controller_id,
                            )
                        )
                        self.check_state_based_actions()
                        return
            self.state.fire_event(
                GameEvent(
                    EventType.ENTERS_BATTLEFIELD,
                    controller_id=obj.controller_id,
                    card_id=obj.card.id,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
            if obj.cast_via_evoke:
                # RULE 702.74a: "it's sacrificed when it enters the
                # battlefield" — a consequence of entering, not a
                # replacement, so the ENTERS_BATTLEFIELD event (and
                # whatever ETB trigger it queues) fires first, above.
                obj.cast_via_evoke = False
                if obj in self.state.permanents():
                    self.put_into_graveyard(obj)
            if obj.granted_suspend_haste:
                # RULE 702.62a: "If you cast a creature spell this way, it
                # gains haste…" — stamped by `SuspendUpkeepEffect` when the
                # free-cast window opened, consumed once here exactly like
                # `cast_via_evoke` above.
                obj.granted_suspend_haste = False
                if obj in self.state.permanents():
                    obj.temp_keywords.add("haste")
            if getattr(obj, "cast_via_dash", False):
                # RULE 702.109c/d (PAR-26): a creature cast for its dash
                # cost gains haste and is returned to its owner's hand at
                # the beginning of the next end step — same "consequence of
                # entering, consumed once here" shape as `cast_via_evoke`.
                obj.cast_via_dash = False
                if obj in self.state.permanents():
                    obj.temp_keywords.add("haste")
                    self.state.delayed_triggers.append(
                        DelayedTrigger(
                            controller_id=obj.owner_id,
                            step="end",
                            scope="any",
                            effects=[ReturnToHandEffect(target_kind=None, source=obj)],
                            targets=[obj],
                            description=f"{obj.name}: Dash — im nächsten Endsegment auf die Hand",
                        )
                    )
            self.state.fire_event(
                GameEvent(EventType.SPELL_RESOLVED, spell=obj.name, controller_id=item.controller_id)
            )
            self.check_state_based_actions()

        def _after_enter_choices() -> None:
            # RULE 702.155/714.3b: Read Ahead's "choose a number" pick (if
            # any) is the last of this pipeline's entry choices, offered
            # right before the object actually joins the battlefield.
            self._offer_read_ahead(obj, _finish)

        def _after_protector_choice() -> None:
            # RULE 601.2b: a "choose a creature type/color" pick (if any)
            # also happens before the object is added to the battlefield —
            # after the enter-as-copy choice (a copy takes on the copied
            # permanent's text, so its own "as ~ enters" clauses, if any,
            # are what should be offered — no real card in the pool combines
            # both, so the ordering is for correctness-in-principle only).
            self._offer_enter_choices(obj, _after_enter_choices)

        def _after_copy_choice() -> None:
            # RULE 310.8a/310.11a: a battle's protector is chosen "as it
            # enters", the same pre-entry window as every choice around it,
            # so it joins this pipeline rather than getting a bespoke one.
            self._offer_protector_choice(obj, _after_protector_choice)

        def _after_replacement_choice() -> None:
            if obj.enter_as_copy_effects:
                self._offer_enter_as_copy(obj, _after_copy_choice)
            else:
                _after_copy_choice()

        if obj.enter_or_graveyard_discard_land:
            self._offer_enter_or_graveyard(obj, _after_replacement_choice)
        else:
            _after_replacement_choice()
    def _offer_enter_or_graveyard(
        self, obj: GameObject, continuation: Callable[[], None]
    ) -> None:
        """RULE 614.12: offer ``obj``'s "you may discard a land card instead"
        choice *before* anything else about entering the battlefield is even
        considered (Mox Diamond) — declining sends it straight to its
        owner's graveyard, the same way a spell that never became a
        permanent always has (`_send_to_graveyard_unentered`).

        No prompt at all when the controller has no land card to discard
        (RULE 601.2c-style: nothing to choose, nothing pauses) — straight to
        the graveyard, mirroring `_offer_enter_as_copy`'s no-legal-target
        case exactly.
        """
        player = self.state.player_by_id(obj.controller_id)
        lands = [c for c in player.hand if c.card.is_land] if player is not None else []
        if not lands:
            self._send_to_graveyard_unentered(obj)
            return
        self._pending_enter_or_graveyard_obj = obj
        self._pending_enter_or_graveyard_continuation = continuation
        options = [
            {"id": str(c.instance_id), "label": c.name, "instance_id": c.instance_id}
            for c in lands
        ]
        options.append({"id": "decline", "label": "Nicht abwerfen (auf den Friedhof)"})
        self.open_choice({
            "kind": "enter_or_graveyard",
            "player_id": obj.controller_id,
            "prompt": f"{obj.name}: Land abwerfen, um es ins Spiel zu bringen?",
            "options": options,
        })
    @continuations.choice("enter_or_graveyard", answer=continuations.ANSWER_STR, rule="614.12")
    def _resume_enter_or_graveyard(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `enter_or_graveyard` choice (RULE 614.12), then
        either resume whatever battlefield-entry work `_offer_enter_or_
        graveyard` deferred (a land was discarded) or route the object
        straight to its owner's graveyard instead (declined).

        ``answer`` is a land card's stringified ``instance_id``, or
        ``None``/``"decline"`` to decline.
        """
        obj = self._pending_enter_or_graveyard_obj
        continuation = self._pending_enter_or_graveyard_continuation
        self._pending_enter_or_graveyard_obj = None
        self._pending_enter_or_graveyard_continuation = None
        if obj is None:
            return
        if answer is None or str(answer) == "decline":
            self._send_to_graveyard_unentered(obj)
            return
        land = self._resolve_choice_option(choice["options"], str(answer))
        player = self.state.player_by_id(obj.controller_id)
        if land is not None and player is not None and land in player.hand:
            player.remove_from_zone(land, Zone.HAND)
            player.add_to_zone(land, Zone.GRAVEYARD)
            self.state.fire_event(
                GameEvent(
                    EventType.DISCARD_CARD, player_id=player.id, instance_id=land.instance_id,
                    # "…discards a permanent card." (Tergrid, God of
                    # Fright, MEC-43 round 4E) — see `draw_discard_mixin.
                    # _main_type_words`'s identical stamp; always a land
                    # here (RULE 118.9's Pitch cycle), kept for consistency
                    # rather than assuming callers never widen this route.
                    object_types=sorted(
                        w for w in land.card.type_line.partition("—")[0].strip().lower().split() if w
                    ),
                )
            )
            self.state.fire_event(GameEvent(EventType.DISCARD, player_id=player.id, count=1))
        if continuation is not None:
            continuation()
    def _send_to_graveyard_unentered(self, obj: GameObject) -> None:
        """RULE 614.12's "don't pay" branch: ``obj`` never becomes a
        permanent at all — no `ENTERS_BATTLEFIELD`. Straight to its owner's
        graveyard, the same `_move_to_graveyard`-shaped placement a resolving
        non-permanent spell already ends with (`obj` is fresh off the stack
        here, not sitting in any per-player zone list, so there's nothing to
        remove it *from* first — `resolve_top_of_stack` already popped it).
        """
        owner = self.state.player_by_id(obj.owner_id)
        owner.add_to_zone(obj, Zone.GRAVEYARD)
        self.state.fire_event(
            GameEvent(EventType.SPELL_RESOLVED, spell=obj.name, controller_id=obj.controller_id)
        )
        self.check_state_based_actions()
    def _offer_protector_choice(self, obj: GameObject, continuation: Callable[[], None]) -> None:
        """RULE 310.8a/310.11a: offer a battle's "choose a player to protect
        it" pick *before* it's added to the battlefield — the `_offer_enter_
        choices` sibling for battles, same continuation-passing shape.

        Calls ``continuation`` immediately when there's nothing to ask: a
        non-battle, or a battle with fewer than two eligible players. The
        one-eligible case still *sets* the protector (RULE 310.8a is
        mandatory, and a Siege with no protector would be swept up by RULE
        310.10's SBA) — it just doesn't stop to ask about a choice of one.
        With none eligible at all (a Siege in a solo goldfish, where its
        controller has no opponents) the protector stays ``None`` and that
        same SBA moves it to the graveyard, which is the rules-correct
        outcome rather than a special case worth coding around here.
        """
        if not obj.is_battle:
            continuation()
            return
        eligible = self._eligible_protectors(obj)
        if len(eligible) < 2:
            obj.protector_id = eligible[0].id if eligible else None
            continuation()
            return

        self._pending_protector_obj = obj
        self._pending_protector_continuation = continuation
        self.open_choice({
            "kind": "choose_protector",
            "player_id": obj.controller_id,
            "prompt": f"{obj.name}: Beschützer wählen (Regel 310.11a)",
            "options": [{"id": p.id, "label": p.name} for p in eligible],
        })
    @continuations.choice("choose_protector", answer=continuations.ANSWER_STR, rule="310.8")
    def _resume_choose_protector(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `choose_protector` choice (RULE 310.8a), then
        resume whatever `_offer_protector_choice` deferred.

        Mandatory, with no "decline" option offered — an unrecognized or
        missing ``answer`` falls back to the first eligible player, the same
        treatment `_resume_choose_creature_type` gives a skipped mandatory pick.
        """
        obj = self._pending_protector_obj
        continuation = self._pending_protector_continuation
        self._pending_protector_obj = None
        self._pending_protector_continuation = None
        if obj is not None:
            self.choose_protector(obj, str(answer) if answer is not None else None)
        if continuation is not None:
            continuation()
    def _offer_enter_as_copy(self, obj: GameObject, continuation: Callable[[], None]) -> None:
        """RULE 614.1c/614.12: offer ``obj``'s "you may have this enter as a
        copy of target X" choice *before* it's added to the battlefield.

        Calls ``continuation`` immediately if there's no legal target to
        offer (RULE 603.3c-style: nothing to choose, nothing pauses);
        otherwise opens an ``enter_as_copy`` `pending_choice` and stashes
        ``continuation`` for `_resume_enter_as_copy` to resume.
        ``obj`` is not yet on the battlefield at this point — `legal_targets`
        only needs it for exclusion/protection checks, both fine against an
        object that isn't in ``state.battlefield`` yet.
        """
        effect = obj.enter_as_copy_effects[0]
        max_mana_value = obj.mana_spent_to_cast if effect.max_mana_value_from_mana_spent else None
        spec = TargetSpec(kind=effect.target_kind, max_mana_value=max_mana_value)
        options = legal_targets(self.state, obj.controller_id, spec, source=obj)
        if not options:
            continuation()
            return
        choice_options = [
            {"id": str(o["instance_id"]), "label": o["name"], "instance_id": o["instance_id"]}
            for o in options
            if "instance_id" in o
        ]
        if effect.optional:
            choice_options.append({"id": "decline", "label": "Nichts wählen"})
        self._pending_enter_as_copy_obj = obj
        self._pending_enter_as_copy_effect = effect
        self._pending_enter_as_copy_continuation = continuation
        self.open_choice({
            "kind": "enter_as_copy",
            "player_id": obj.controller_id,
            "prompt": effect.description or "Als Kopie ins Spiel kommen lassen?",
            "options": choice_options,
        })
    @continuations.choice("enter_as_copy", answer=continuations.ANSWER_STR, rule="614.1")
    def _resume_enter_as_copy(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `enter_as_copy` choice, then resume whatever
        battlefield-entry work `_offer_enter_as_copy` deferred.

        ``answer`` is a target's stringified ``instance_id``, or
        ``None``/``"decline"`` to enter as itself."""
        obj = self._pending_enter_as_copy_obj
        effect = self._pending_enter_as_copy_effect
        continuation = self._pending_enter_as_copy_continuation
        self._pending_enter_as_copy_obj = None
        self._pending_enter_as_copy_effect = None
        self._pending_enter_as_copy_continuation = None

        if answer is not None and answer != "decline" and obj is not None and effect is not None:
            target = self._resolve_choice_option(choice["options"], str(answer))
            if target is not None and target is not obj:
                # Snapshot ~'s own abilities *before* `become_copy` clears
                # them (RULE 707.2) — Sakashima of a Thousand Faces' own
                # "except it has ~'s other abilities" clause adds them back
                # once the copy's abilities are bound.
                own_triggered = list(obj.triggered_abilities) if effect.keep_own_abilities else []
                own_static = list(obj.static_effects) if effect.keep_own_abilities else []
                own_activated = list(obj.activated_abilities) if effect.keep_own_abilities else []
                own_replacement = list(obj.replacement_effects) if effect.keep_own_abilities else []
                # "…except it has [keyword] if [the copied creature] doesn't
                # have [keyword]" (Flesh Duplicate) — checked against the
                # *target*'s own printed keywords before the copy overwrites
                # obj.card, since afterwards obj.card *is* target's card.
                # Compared by keyword *name* (the word before any trailing
                # number — "Vanishing" out of "Vanishing 3") since a bare
                # `Card.keywords` entry never carries the printed N.
                target_keyword_names = {
                    str(kw).split()[0].lower()
                    for kw in (getattr(target.card, "keywords", []) or [])
                    if str(kw).strip()
                }
                conditional_keywords = [
                    kw for kw in effect.add_keywords_if_target_lacks
                    if kw.split()[0].lower() not in target_keyword_names
                ]
                copy_mechanics.become_copy(
                    obj, target, effect.add_types, effect.add_subtypes,
                    only_types=effect.only_types,
                    add_keywords=effect.add_keywords + conditional_keywords,
                )
                if effect.keep_own_abilities:
                    obj.triggered_abilities.extend(own_triggered)
                    obj.static_effects.extend(own_static)
                    obj.activated_abilities.extend(own_activated)
                    obj.replacement_effects.extend(own_replacement)
                # "…enters with an additional +1/+1/loyalty counter…"
                # (Spark Double) — applied post-copy, once the resulting
                # permanent's real type is known.
                if obj.is_creature and effect.extra_counter_if_creature:
                    self.add_counters(obj, 1, kind=effect.extra_counter_if_creature)
                # "…except it enters with X additional +1/+1 counters on it."
                # (Altered Ego, PAR-60) — X is this copy spell's own
                # announced {X}.
                if obj.is_creature and getattr(effect, "extra_counters_from_x", False):
                    x = int(getattr(obj, "x_paid", 0) or 0)
                    if x > 0:
                        self.add_counters(obj, x, kind="+1/+1")
                if obj.card.is_planeswalker and effect.extra_counter_if_planeswalker:
                    self.add_counters(obj, 1, kind=effect.extra_counter_if_planeswalker)
                if effect.grant_mana_option:
                    # `GameObject.granted_mana_options` is a read-only,
                    # every-recompute-rederived property (from live static
                    # abilities on the board) — not a settable field — so
                    # the grant is a real `StaticAbility` appended onto the
                    # copy's own `static_effects`, the same "grant_mana_
                    # ability" shape a printed "X have '{T}: Add …'" static
                    # uses, just `affects="self"`.
                    obj.static_effects.append(
                        StaticAbility(
                            "ability", affects="self",
                            params={"mana": [dict(effect.grant_mana_option)]},
                            source=obj,
                        )
                    )
        if continuation is not None:
            continuation()
    def _offer_enter_choices(self, obj: GameObject, continuation: Callable[[], None]) -> None:
        """RULE 601.2b: offer ``obj``'s queued "as it enters, choose a
        creature type/color" pick(s) *before* it's added to the battlefield —
        the `enter_choice_effects` sibling of `_offer_enter_as_copy`.

        Offers one at a time (a card only ever has one in the pool this
        engine models, but the queue shape mirrors `enter_choice_effects`
        exactly in case a future card stacks two): pops the first queued
        effect, opens its `pending_choice`, and stashes a continuation that
        re-enters this method for whatever remains before finally calling
        ``continuation``. Calls ``continuation`` immediately once the queue
        is empty (or was empty to begin with — nothing to choose, nothing
        pauses), same as `_offer_enter_as_copy`'s no-legal-target case.
        """
        if not obj.enter_choice_effects:
            continuation()
            return
        effect = obj.enter_choice_effects[0]
        remaining = obj.enter_choice_effects[1:]

        def _next() -> None:
            obj.enter_choice_effects = remaining
            self._offer_enter_choices(obj, continuation)

        if isinstance(effect, ChooseCreatureTypeReplacement):
            kind = "choose_creature_type"
            prompt = "Kreaturentyp wählen"
            options = [{"id": t, "label": t} for t in _creature_type_options(self.state, obj.controller_id)]
        elif isinstance(effect, ChooseBasicLandTypeReplacement):
            kind = "choose_basic_land_type"
            prompt = "Standard-Landtyp wählen"
            options = [{"id": t, "label": t} for t in _BASIC_LAND_TYPE_OPTIONS]
        elif isinstance(effect, ChooseNamedModeReplacement):
            kind = "choose_named_mode"
            prompt = "Modus wählen"
            options = [{"id": label.strip().lower(), "label": label} for label in effect.options]
        elif isinstance(effect, ChooseCardNameReplacement):
            kind = "choose_card_name"
            prompt = "Kartenname wählen"
            # Unlike every other RULE 601.2b pick above, the answer space
            # isn't enumerable (any Magic card is a legal name, not just one
            # on this board) — the battlefield's own names are offered as
            # convenience suggestions only, the same idiom `_request_name_card`
            # uses; `_resume_choose_creature_type` accepts any string for this kind.
            options = [
                {"id": name, "label": name}
                for name in sorted({o.card.name for o in self.state.battlefield})
            ]
        elif isinstance(effect, ChooseNumberReplacement):
            kind = "choose_number"
            prompt = "Zahl wählen"
            # Sanctum Prelate (MEC-43): the same "answer space isn't
            # enumerable" shape `choose_card_name` uses — any non-negative
            # integer is a legal choice, not just a small fixed set.
            options = []
        elif isinstance(effect, ChooseOpponentReplacement):
            kind = "choose_opponent_on_enter"
            prompt = "Gegner wählen"
            options = [
                {"id": p.id, "label": p.name}
                for p in self.state.living_players() if p.id != obj.controller_id
            ]
        else:
            kind = "choose_color"
            prompt = "Farbe wählen"
            options = [{"id": color, "label": label} for color, label in self._ANY_COLOR_LABELS.items()]

        if not options and kind not in ("choose_card_name", "choose_number"):
            # RULE 601.2b's choice still has to happen in principle, but
            # with no legal answer (e.g. a puzzle board with no creature
            # cards anywhere) there's nothing to pause on — chosen_type/
            # chosen_color stays None, and every dependent selector then
            # just matches nothing, the same safe fallback an ordinary
            # unset subtype/colour filter already gets. ``choose_card_name``/
            # ``choose_number`` are exempt: a free-text choice has a legal
            # answer (any string/integer) regardless of whether the board
            # offers any suggestions.
            _next()
            return

        self._pending_enter_choice_obj = obj
        self._pending_enter_choice_effect = effect
        self._pending_enter_choice_continuation = _next
        self.open_choice({
            "kind": kind,
            "player_id": obj.controller_id,
            "prompt": prompt,
            "options": options,
            **({"free_text": True} if kind in ("choose_card_name", "choose_number") else {}),
        })
    @continuations.choice(
        "choose_creature_type", "choose_color", "choose_named_mode",
        "choose_basic_land_type", "choose_card_name", "choose_number", "choose_opponent_on_enter",
        answer=continuations.ANSWER_STR,
        rule="601.2b",
    )
    def _resume_choose_creature_type(
        self, choice: dict[str, Any], answer: Optional[str]
    ) -> None:
        """Answer a pending `choose_creature_type`/`choose_color` choice
        (RULE 601.2b), then resume whatever `_offer_enter_choices` deferred —
        which may open the *next* queued choice rather than finishing entry
        outright.

        A mandatory choice (there's no "decline" option offered at all): an
        unrecognized/missing ``answer`` defaults to the first offered option,
        the same treatment `_resume_add_mana_any_color` gives a
        missing mandatory answer, so a dependent selector is never silently
        starved by a skipped pick. ``choose_card_name`` is the one exception —
        like `_resume_name_card`, its answer isn't validated against
        the offered (suggestion-only) options at all; a missing answer names
        the empty string, which simply matches no permanent.
        """
        obj = self._pending_enter_choice_obj
        continuation = self._pending_enter_choice_continuation
        self._pending_enter_choice_obj = None
        self._pending_enter_choice_effect = None
        self._pending_enter_choice_continuation = None

        options = choice["options"]
        if choice["kind"] == "choose_card_name":
            chosen = str(answer) if answer else ""
        elif choice["kind"] == "choose_number":
            # Sanctum Prelate (MEC-43): a missing/unparseable answer
            # defaults to 0 — the same "skipped mandatory pick" safe
            # fallback every other RULE 601.2b choice here gets, not a
            # printed default (RULE 601.2b names no default for a "choose a
            # number" clause).
            try:
                chosen = str(int(str(answer)))
            except (TypeError, ValueError):
                chosen = "0"
        else:
            valid_ids = {str(o["id"]) for o in options}
            chosen = str(answer) if answer is not None and str(answer) in valid_ids else (
                str(options[0]["id"]) if options else None
            )
        if obj is not None and chosen is not None:
            if choice["kind"] in ("choose_creature_type", "choose_basic_land_type"):
                obj.chosen_type = chosen
            elif choice["kind"] == "choose_named_mode":
                obj.chosen_mode = chosen
            elif choice["kind"] == "choose_card_name":
                obj.chosen_card_name = chosen
            elif choice["kind"] == "choose_number":
                obj.chosen_number = int(chosen)
            elif choice["kind"] == "choose_opponent_on_enter":
                obj.chosen_player_id = chosen
            else:
                obj.chosen_color = chosen
        if continuation is not None:
            continuation()
    def _offer_read_ahead(self, obj: GameObject, continuation: Callable[[], None]) -> None:
        """RULE 702.155/714.3b: a Saga with Read Ahead lets its controller
        choose a number from 1 to its final chapter number as it enters,
        instead of the ordinary single lore counter — offered *before*
        battlefield entry, alongside `_offer_enter_as_copy`/
        `_offer_enter_choices` (same continuation-passing shape).

        RULE 702.155a: only the chapter ability whose number *exactly*
        matches the chosen count fires — every lower chapter is skipped for
        good (not merely delayed), so a choice of N doesn't replay chapters
        1..N-1 first. `_finish` in `_resolve_permanent_spell` reads the
        stashed `_pending_read_ahead_count` and passes it straight to
        `GameState.add_to_battlefield`'s ``saga_lore_override``, which seeds
        the Saga with that many counters and fires one `SAGA_CHAPTER` event
        for that exact count — the same single-event shape an ordinary
        Saga's entry uses for chapter 1.
        """
        final = _saga_final_chapter(obj.card)
        if (
            obj.is_token
            or not obj.card.is_saga
            or final <= 1
            or "read_ahead" not in obj.intrinsic_keywords
        ):
            continuation()
            return
        self._pending_read_ahead_obj = obj
        self._pending_read_ahead_continuation = continuation
        self.open_choice({
            "kind": "read_ahead",
            "player_id": obj.controller_id,
            "prompt": f"{obj.name}: Voraus lesen — Kapitelmarke wählen (1-{final})",
            "options": [{"id": str(n), "label": f"Kapitel {n}"} for n in range(1, final + 1)],
        })
    @continuations.choice("read_ahead", answer=continuations.ANSWER_STR, rule="714.3")
    def _resume_read_ahead(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `read_ahead` choice (RULE 702.155), then resume
        whatever `_offer_read_ahead` deferred.

        A mandatory choice (no "decline" option is ever offered): an
        unrecognized/missing ``answer`` defaults to 1 (no read-ahead), the
        same missing-mandatory-answer treatment `_resume_choose_creature_type` gives.
        """
        obj = self._pending_read_ahead_obj
        continuation = self._pending_read_ahead_continuation
        self._pending_read_ahead_obj = None
        self._pending_read_ahead_continuation = None

        valid_ids = {str(o["id"]) for o in choice["options"]}
        chosen = str(answer) if answer is not None and str(answer) in valid_ids else "1"
        self._pending_read_ahead_count = int(chosen) if obj is not None else None
        if continuation is not None:
            continuation()
