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

import copy
import dataclasses
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
    ChooseBasicLandTypeReplacement,
    ChooseCardTypeReplacement,
    ChooseCardNameReplacement,
    ChooseColorReplacement,
    ChooseCreatureTypeReplacement,
    ChooseEnterCounterReplacement,
    ChooseNamedModeReplacement,
    ChooseNumberReplacement,
    ChooseOpponentReplacement,
    DiscardEffect,
    DrawCardEffect,
    LoseLifeEffect,
    ReturnUncastExiledEffect,
    SacrificeSelfEffect,
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


def _targets_permanent_or_player(targets: Optional[list[Any]]) -> bool:
    """Whether any chosen target is a battlefield permanent or a player — Shiko and Narset, Unified's "copy that
    spell if it targets a permanent or player" (a spell aimed only at a spell on the stack, or at a card in a
    graveyard, doesn't qualify)."""
    from ...models.game.player import Player

    for t in targets or []:
        if isinstance(t, Player):
            return True
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
#: RULE 205.2a card types a "choose a card type" pick offers, as the protection-quality word each answer is stored as
#: (`combat._CARD_TYPE_PROTECTIONS`'s vocabulary; "creatures" is `is_protected_from`'s own branch).
_CARD_TYPE_OPTIONS: list[tuple[str, str]] = [
    ("artifacts", "Artifact"), ("battles", "Battle"), ("creatures", "Creature"), ("enchantments", "Enchantment"),
    ("instants", "Instant"), ("lands", "Land"), ("planeswalkers", "Planeswalker"), ("sorceries", "Sorcery"),
]




#: The magnitude attributes `_substitute_x` rewrites in place.
_X_MAGNITUDE_ATTRS: tuple[str, ...] = ("amount", "count", "power", "toughness", "times", "any_amount")
#: The mana-value bounds it rewrites inside a ``filter``/``criteria`` dict.
_X_MANA_VALUE_KEYS: tuple[str, ...] = ("max_mana_value", "min_mana_value")
#: `CreateDelayedTriggerEffect` captures that write their own value into the
#: ``"x"`` sentinel of their nested ``inner_specs`` — `_substitute_x` must
#: leave those nested sentinels alone rather than fill them with this spell's X.
_X_OWNING_CAPTURES: frozenset[str] = frozenset({"target_mana_value"})


def _restore_x_sentinels(effect: Any) -> None:
    """Put back the ``"x"``-style sentinels `_substitute_x` overwrote on an
    earlier resolution, or record them the first time round.

    `_substitute_x` writes the announced number into the effect object
    itself, and an activated or triggered ability's effects are the same
    objects on every resolution: "{X}: You gain X life." activated for 3 and
    then for 5 gained 3 both times, and Zaxara's second Hydra copied the first
    one's X. Snapshotting what was printed before the first rewrite, and
    restoring it before every later one, makes each resolution see its own X
    (RULE 107.3c/601.2b) without changing how a single resolution substitutes.
    """
    saved = getattr(effect, "_x_sentinels", None)
    if saved is not None:
        for attr, value in saved["attrs"].items():
            setattr(effect, attr, value)
        for dict_attr, values in saved["maps"].items():
            mapping = getattr(effect, dict_attr, None)
            if isinstance(mapping, dict):
                mapping.update(values)
        if saved["target_spec"] is not None:
            effect.target_spec = saved["target_spec"]
        for index, values in saved["inner"].items():
            inner = (getattr(effect, "inner_specs", None) or [])[index]
            inner["params"].update(values)
        return
    attrs = {
        attr: getattr(effect, attr) for attr in _X_MAGNITUDE_ATTRS
        if isinstance(getattr(effect, attr, None), str)
    }
    maps: dict[str, dict[str, Any]] = {}
    for dict_attr in ("filter", "criteria"):
        mapping = getattr(effect, dict_attr, None)
        if isinstance(mapping, dict):
            strings = {k: mapping[k] for k in _X_MANA_VALUE_KEYS if isinstance(mapping.get(k), str)}
            if strings:
                maps[dict_attr] = strings
    target_spec = getattr(effect, "target_spec", None)
    keep_spec = target_spec if target_spec is not None and any(
        isinstance(getattr(target_spec, k, None), str) for k in _X_MANA_VALUE_KEYS
    ) else None
    inner_saved: dict[int, dict[str, Any]] = {}
    for index, inner in enumerate(getattr(effect, "inner_specs", None) or []):
        params = inner.get("params") if isinstance(inner, dict) else None
        if isinstance(params, dict):
            strings = {k: params[k] for k in _X_MAGNITUDE_ATTRS if isinstance(params.get(k), str)}
            if strings:
                inner_saved[index] = strings
    if attrs or maps or keep_spec is not None or inner_saved:
        try:
            effect._x_sentinels = {
                "attrs": attrs, "maps": maps, "target_spec": keep_spec, "inner": inner_saved,
            }
        except AttributeError:  # an effect with __slots__ — nothing to remember on
            pass



#: Card-type words that make a check-land phrase about permanents rather than land subtypes.
_CHECK_PERMANENT_TYPE_WORDS = frozenset({"creature", "artifact", "enchantment", "planeswalker"})


def _controls_check_type(state: Any, controller_id: Optional[str], types: list[str]) -> bool:
    """Whether ``controller_id`` controls a permanent a "tapped unless you control <type>" clause names (RULE 614.1).

    A land-subtype phrase ("Plains or Island" — the check lands) is looked up among the controller's lands. A phrase
    with a card-type word ("a legendary creature" — Minas Tirith) needs every word on the type line of any permanent."""
    for t in types:
        words = t.lower().split()
        if _CHECK_PERMANENT_TYPE_WORDS & set(words):
            if any(
                o.controller_id == controller_id and all(w in o.card.type_line.lower() for w in words)
                for o in state.battlefield
            ):
                return True
        elif any(
            o.is_land and o.controller_id == controller_id and t in o.card.type_line.lower()
            for o in state.battlefield
        ):
            return True
    return False

class CastingResolutionMixin:
    """Casting a spell onto the stack and resolving it, incl. RULE 614.1 entry-tapped/counters and every ETB interactive choice."""

    def _add_entry_counters(self, obj: GameObject, kind: str, amount: int) -> None:
        # RULE 614.12 / 101.2: an entrant's own counter prohibition also applies.
        if amount > 0 and continuous.counters_prohibited_for(self.state, obj, kind, as_enters=True):
            return
        obj.add_counters(kind, amount)

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
                self._add_entry_counters(obj, kind, int(param["n"]))

        # RULE 702.156a Ravenous: "enters with X +1/+1 counters on it" (X is the announced {X}).
        if "ravenous" in (getattr(obj, "intrinsic_keywords", None) or ()) and x_paid > 0:
            self._add_entry_counters(obj, "+1/+1", x_paid)
        # "…enters with a number of +1/+1 counters equal to 1 plus the number of other creatures you control." (Boss's
        # Chauffeur) — a self static counted as the permanent enters (it is not on the battlefield yet, so "other" is free).
        for ability in getattr(obj, "static_effects", None) or ():
            if getattr(ability, "layer", None) != "entry_counters_self":
                continue
            removed = 0
            if ability.params.get("remove_counters_scope") == "artifacts_creatures_enchantments":
                # "As Sin enters, remove all counters from any number of artifacts, creatures, and enchantments. Sin enters with X
                # +1/+1 counters, where X is twice the number of counters removed this way." — **simplification:** every such
                # permanent loses its counters (the "any number" choice is taken as "all").
                for other in list(self.state.battlefield):
                    if other is obj or not (other.card.is_artifact or other.is_creature or other.card.is_enchantment):
                        continue
                    for kind, n in list((other.counters or {}).items()):
                        if n and n > 0:
                            self.add_counters(other, -n, kind, source=obj)
                            removed += n
            amount = int(ability.params.get("base", 0)) + int(ability.params.get("multiplier", 1)) * (removed + (
                continuous.count_selector(
                    self.state, obj.controller_id, ability.params.get("count_selector", ""), source=obj,
                ) if ability.params.get("count_selector") else 0
            ))
            if amount > 0:
                self._add_entry_counters(obj, str(ability.params.get("kind", "+1/+1")), amount)

        if obj.entry_bonus_creature_counters:
            if obj.is_creature:
                for kind, amount in obj.entry_bonus_creature_counters.items():
                    obj.entry_bonus_counters[kind] = obj.entry_bonus_counters.get(kind, 0) + amount
            obj.entry_bonus_creature_counters.clear()
        if obj.entry_bonus_counters:
            for kind, amount in obj.entry_bonus_counters.items():
                if amount > 0:
                    self._add_entry_counters(obj, kind, amount)
            obj.entry_bonus_counters = {}
        if obj.gains_sunburst:
            # RULE 702.43a Sunburst *granted* to a spell (Lux Artillery): a +1/+1 counter per colour of
            # mana spent for a creature, a charge counter otherwise — the same colours count as the
            # printed keyword's `colors_spent_scale` below.
            obj.gains_sunburst = False
            spent = len(getattr(obj, "colors_spent_to_cast", None) or ())
            if spent > 0:
                self._add_entry_counters(obj, "+1/+1" if obj.is_creature else "charge", spent)

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
        elif condition.get("land_cards_in_graveyards"):
            # "…equal to the number of land cards in all graveyards" (Centaur Vinecrasher): every player's graveyard.
            amount = condition["count"] * sum(
                1 for player in self.state.players for card in player.graveyard if card.card.is_land
            )
        elif condition.get("roll_x_dice_sides"):
            # "As ~ enters, roll X d6. It enters with a number of +1/+1 counters equal to the total" (Neverwinter
            # Hydra, RULE 706): X is the announced {X}; the controller rolls and the kept results are summed.
            roller = self.state.player_by_id(obj.controller_id)
            dice = int(getattr(obj, "x_paid", 0) or 0)
            rolled = self.roll_die(roller, sides=int(condition["roll_x_dice_sides"]), count=dice) if dice > 0 else []
            amount = condition["count"] * sum(rolled)
        elif condition.get("mana_spent_scale"):
            # "…a number of +1/+1 counters equal to the amount of mana spent to cast it" (Kurbis): every mana
            # paid, of any kind (`GameObject.mana_spent_to_cast`; 0 for anything never cast).
            amount = condition["count"] * int(getattr(obj, "mana_spent_to_cast", 0) or 0)
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
            self._add_entry_counters(obj, condition["counter_type"], amount)
        # "~ enters with a +1/+1 counter and a flying counter on it." — the
        # compound's remaining counters, placed together with the first.
        for extra in condition.get("extra_counters", ()):
            self._add_entry_counters(obj, extra["counter_type"], extra["count"])

    def _apply_granted_entry_counters(self, obj: GameObject) -> None:
        """MEC-56: any live ``extra_etb_counter`` static's contribution
        (Master Chef) — a *granted* sibling of `_apply_entry_counters`'
        printed-condition read, called at the same site right after it so
        the extra counter(s) are present before `obj` joins the
        battlefield/ENTERS_BATTLEFIELD fires, same as a printed one.
        """
        for kind, amount in continuous.extra_etb_counters_for(self.state, obj).items():
            if amount > 0:
                self._add_entry_counters(obj, kind, amount)

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
        if continuous.enters_untapped_from_static(self.state, obj):
            obj.tapped = False  # "Lands you control enter untapped." (Horizon Explorer) — no tapped-entry applies
            return
        condition = card_registry.land_tap_condition(obj.card)
        kind = condition["kind"]
        if kind == "unless_types":
            obj.tapped = not _controls_check_type(self.state, obj.controller_id, condition["types"])
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
            # "…unless you revealed a Dragon card this way or you control a Dragon" (Temple of the
            # Dragon Queen): controlling one skips the question — any permanent, not only a land.
            if condition.get("or_control") and self._controls_permanent_of_types(obj, types):
                obj.tapped = False
            elif has_match:
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
    def _controls_permanent_of_types(self, obj: GameObject, types: list[str]) -> bool:
        """Whether ``obj``'s controller controls a permanent whose type line names one of ``types``
        (derived subtypes included — a changeling counts as a Dragon)."""
        return any(
            o is not obj and o.controller_id == obj.controller_id
            and any(t in o.card.type_line.lower() or continuous.has_subtype(o, t) for t in types)
            for o in self.state.battlefield
        )
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
        if continuous.enters_untapped_from_static(self.state, obj):
            return False  # Horizon Explorer: the land enters untapped whatever its own clause says
        card = card or obj.card
        condition = card_registry.land_tap_condition(card)
        kind = condition["kind"]
        if kind == "unless_types":
            tapped = not _controls_check_type(self.state, obj.controller_id, condition["types"])
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
        elif kind == "reveal_types" and condition.get("or_control") and self._controls_permanent_of_types(
            obj, condition["types"]
        ):
            tapped = False
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
    @staticmethod
    def _is_omen_card(card: Card) -> bool:
        """Whether ``card`` (the front face) is an Omen card (RULE 720): the cache stores it with the
        Adventure layout, its inset half's type line being "<Instant|Sorcery> — Omen" (RULE 205.3k)."""
        return card.is_adventure and "omen" in (card.back_type_line or "").lower().partition("—")[2]

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
        free_cast = (obj.instance_id in self.state.free_cast_instance_ids
                     and self.state.resolution_play_choice is None)
        source_mana_spent = {}
        obj.colors_spent_to_cast = frozenset()
        obj.mana_spent_to_cast_treasure = 0
        obj.mana_spent_to_cast_creature = 0
        obj.mana_spent_to_cast_artifact = 0
        if free_cast:
            life_spent = 0
        else:
            allows_restriction = restriction_predicate_for_cast(obj, has_x=cost.has_variable)
            # RULE 605.1a "you may spend mana as though it were mana of any
            # color/type" (Mnemonic Betrayal-shaped), scoped to casting this
            # one exiled card — see `GameState.mana_wildcard_permission`.
            wildcard = (
                self.state.mana_wildcard_permission.get(obj.instance_id)
                or continuous.standing_mana_wildcard(self.state, player)
            )
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
                cost, life_available=player.life - getattr(obj, "_cast_pip_life_cost", 0),
                allows_restriction=allows_restriction, wildcard=wildcard,
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
            sources_before = {kind: sum(pool.values()) for kind, pool in player.mana_pool.pool_by_source.items()
                              if kind is not None}
            snow_before = sum(player.mana_pool.snow_pool.values())
            life_spent = player.mana_pool.pay(
                cost, life_available=player.life - getattr(obj, "_cast_pip_life_cost", 0),
                allows_restriction=allows_restriction, wildcard=wildcard,
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
            source_mana_spent = {
                kind: sources_before.get(kind, 0)
                      - sum(player.mana_pool.pool_by_source.get(kind, {}).values())
                      + player.mana_pool.last_payment_by_kind.get(kind, 0)
                for kind in sources_before.keys() | player.mana_pool.last_payment_by_kind.keys()
            }
            obj.mana_spent_to_cast_treasure = source_mana_spent.get("treasure", 0)
            obj.mana_spent_to_cast_creature = source_mana_spent.get("creature", 0) + source_mana_spent.get("artifact_creature", 0)
            # Every artifact source, Treasures included (Coin of Mastery's "for each mana from an artifact source spent to cast it").
            obj.mana_spent_to_cast_artifact = source_mana_spent.get("treasure", 0) + source_mana_spent.get("artifact", 0) + source_mana_spent.get("artifact_creature", 0)
        life_spent += getattr(obj, "_cast_pip_life_cost", 0)
        self.lose_life(player, life_spent, cause="cost")
        self.state.next_spell_flash_grants = [
            g for g in self.state.next_spell_flash_grants
            if not (g['player_id'] == player.id and g['turn'] == self.state.internal_turn.number
                    and (not g['card_types'] or set(g['card_types']) & obj.type_words))
        ]
        # "The next spell you cast this turn costs {N} less" is used up by
        # this cast, whether or not the discount mattered (RULE 601.2f).
        continuous.consume_next_spell_cost_reductions(self.state, player.id, obj)
        if free_cast:
            self.state.free_cast_instance_ids.discard(obj.instance_id)
            if obj.instance_id in self.state.free_cast_owner_loses_life_ids:
                # "…each player who owns a spell you cast this way loses life equal to its mana value." (Kefka)
                self.state.free_cast_owner_loses_life_ids.discard(obj.instance_id)
                self.lose_life(self.state.player_by_id(obj.owner_id), int(obj.mana_value or 0))
            self.state.free_cast_ignore_timing_instance_ids.discard(obj.instance_id)
            self._consume_free_cast_type_slot(obj)  # Aminatou's Augury: one cast per nonland card type
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
        obj.cast_from_zone = cast_from_zone
        obj.cast_from_exile = obj.zone == Zone.EXILE
        # RULE 702.35a: the only way to cast a madness-exiled card from exile is for its madness cost.
        obj.madness_cost_paid = bool(getattr(obj, "madness_exiled", False)) and obj.cast_from_exile
        obj.was_cast = True
        # Zone-agnostic (not just hand/command) so an Adventure creature can
        # be cast from exile (RULE 715.3d) with no dedicated branch here.
        self._remove_from_current_zone(player, obj)
        obj.adventure_castable = False
        obj.controller_id = player.id
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
            player.id, "spell", cmc=obj.mana_value, name=obj.name
        )
        self.state.fire_event(
            GameEvent(
                EventType.SPELL_CAST, player_id=player.id, card_id=obj.card.id, spell=obj.name,
                instance_id=obj.instance_id, object_types=sorted(obj.type_words),
                zone_incarnation=obj.zone_incarnation,
                mana_spent=obj.mana_spent_to_cast,
                colors_spent=sorted(obj.colors_spent_to_cast),
                creature_mana_spent=getattr(obj, "mana_spent_to_cast_creature", 0) or 0,
                mana_spent_by_source=source_mana_spent,
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
                mana_value=ManaCost.from_card(obj.card).with_x(x).resolved_value,
                # "Whenever you cast a spell with {X} in its mana cost, create a
                # 0/0 Hydra token, then put X +1/+1 counters on it." (Zaxara, the
                # Exemplary) — its ruling: X is the cast spell's X. Carried on
                # the event so the trigger resolves with it (`_place_trigger`).
                x_paid=int(getattr(obj, "x_paid", 0) or 0),
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
                # "Whenever you cast a spell with one or more targets, draw that many cards."
                # (Voracious Bibliophile) — RULE 115.1: how many targets were chosen.
                target_count=len([t for t in (targets or []) if t is not None]),
                targets_permanent_or_player=_targets_permanent_or_player(targets),
                # What `GameState`'s per-turn cast tallies (`turn_history`) read back.
                **_cast_history_traits(obj),
            )
        )
        self._fire_expend_events(player, obj)
        self.check_ward(item, player)
        return item

    def _fire_expend_events(self, player: Player, obj: GameObject) -> None:
        """RULE 700.14: fire one `EXPEND` per N this payment crossed.

        The running total is read back off the turn's `SPELL_CAST` events (which
        already include this cast), so no separate counter can drift. A player
        expends N when the total *before* this payment was below N and is at
        least N after it, i.e. N in (before, after].
        """
        spent = int(obj.mana_spent_to_cast or 0)
        if spent <= 0:
            return
        after = int(self.state.mana_spent_on_spells_this_turn.get(player.id, 0))
        before = after - spent
        # The interval is finite (bounded by the mana actually paid).  Do not
        # cap it at today's printed thresholds: RULE 700.14 defines arbitrary
        # N, and future/custom cards must be able to listen above 8 as well.
        for amount in range(before + 1, after + 1):
            self.state.fire_event(
                GameEvent(
                    EventType.EXPEND, player_id=player.id, amount=amount,
                    spell=obj.name, instance_id=obj.instance_id,
                )
            )

    #: The nonland card types a type-slot free cast (Aminatou's Augury) hands out one cast apiece for (RULE 205.2a).
    FREE_CAST_SLOT_TYPES: tuple[str, ...] = ("artifact", "battle", "creature", "enchantment", "instant", "planeswalker", "sorcery")

    def _consume_free_cast_type_slot(self, obj: GameObject) -> None:
        """Spend a type slot for a free-cast pool card being cast now ("for each nonland card type, you may cast a
        spell of that type" — Aminatou's Augury): the spell uses one of its own types' still-open slots, and every other
        card in the pool that no longer has an open slot of any of its types loses its free cast."""
        for pool in list(self.state.free_cast_type_pools):
            if obj.instance_id not in pool["ids"]:
                continue
            own = [t for t in self.FREE_CAST_SLOT_TYPES if getattr(obj.card, f"is_{t}", False) and t in pool["slots"]]
            if own:
                pool["slots"].discard(own[0])
            pool["ids"].discard(obj.instance_id)
            for other_id in list(pool["ids"]):
                other = self.state.find_object(other_id)
                if other is None or not any(
                    getattr(other.card, f"is_{t}", False) for t in pool["slots"]
                ):
                    pool["ids"].discard(other_id)
                    self.state.free_cast_instance_ids.discard(other_id)
                    self.state.temp_play_permissions.pop(other_id, None)

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
        obj.cast_from_zone = cast_from_zone
        obj.cast_from_exile = obj.zone == Zone.EXILE
        obj.madness_cost_paid = bool(getattr(obj, "madness_exiled", False)) and obj.cast_from_exile
        obj.was_cast = True
        # RULE 702.174a: a cast that pays no additional costs promises no gift (and must not
        # inherit the promise of an earlier cast of the same card).
        obj.gift_promised = False
        obj.gift_recipient_id = None
        self._remove_from_current_zone(player, obj)
        obj.zone = Zone.STACK
        self._consume_free_cast_type_slot(obj)
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
        if obj.instance_id in self.state.free_cast_owner_loses_life_ids:
            self.state.free_cast_owner_loses_life_ids.discard(obj.instance_id)
            self.lose_life(self.state.player_by_id(obj.owner_id), int(obj.mana_value or 0))
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
                # "Whenever you cast a spell with one or more targets, draw that many cards."
                # (Voracious Bibliophile) — RULE 115.1: how many targets were chosen.
                target_count=len([t for t in (targets or []) if t is not None]),
                targets_permanent_or_player=_targets_permanent_or_player(targets),
                # What `GameState`'s per-turn cast tallies (`turn_history`) read back.
                **_cast_history_traits(obj),
            )
        )
        self.check_ward(item, player)
        return item
    def _note_graveyard_exit(self, obj: GameObject) -> None:
        """Record a card leaving its owner's graveyard before it becomes new.

        This is called from the one zone-removal choke point, covering casts,
        reanimation, exile, shuffle-in and any future route using it.
        """
        card = {
            "instance_id": obj.instance_id,
            "mana_value": int(getattr(obj, "mana_value", 0) or 0),
            "owner_id": obj.owner_id,
            "graveyard_owner_id": obj.owner_id,
            # "one or more **creature** cards leave your graveyard" (PAR-119) — the
            # card's types as it last existed there (RULE 603.10, look back in time).
            "object_types": sorted(obj.type_words),
        }
        # RULE 603.3f per-turn tracker for "if a card left your graveyard
        # this turn" intervening-ifs (reset each `begin_turn`).
        self.state.cards_left_graveyard_this_turn.add(obj.owner_id)
        self.state.note_graveyard_exit(card)

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
        if obj.zone == Zone.EXILE:
            obj.hideaway_incarnation += 1
        obj.hideaway_source_id = None
        left_graveyard = obj.zone == Zone.GRAVEYARD
        if left_graveyard:
            self.state.temp_graveyard_cast_permissions.pop(obj.instance_id, None)
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
    def _attachment_legal(self, obj: GameObject, target: Any, check_control: bool = True) -> bool:
        """Whether ``obj`` can legally attach to ``target`` (basic MVP rules).

        ``check_control`` is the "creature you control" half of equip/reconfigure/fortify. RULE 301.5b
        says control of the creature matters *only when the ability is activated and when it resolves*,
        and 301.5d that changing control of either permanent doesn't detach anything — so the state-
        based re-check (`_revalidate_attachments`) and a spell or ability that attaches an Equipment
        (Magnetic Theft — "attach target Equipment to target creature", PAR-135) both pass ``False``;
        only the equip-style activation keeps the default. An Aura's own "enchant creature you control"
        is its restriction, not the equip family's, and is always checked."""
        kind = self._attachment_kind(obj)
        # RULE 303.4a/702.5: a Curse Aura's ``Enchant player`` target is a
        # player, not a permanent. Its attachment identity is the stable
        # player id (parallel to a permanent's instance id); unlike a normal
        # Aura host it has no protection/phase/type state to re-check.
        if isinstance(target, Player):
            quality = str(((obj.parametric_keywords or {}).get("enchant") or {}).get(
                "quality", ""
            )).strip().lower()
            # "Enchant opponent" (Tenuous Truce) narrows the same player host to someone other than the Aura's
            # controller.
            player_ok = quality == "player" or (quality == "opponent" and target.id != obj.controller_id)
            return kind == "enchant" and player_ok and not target.has_lost
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
            return target.is_creature and (not check_control or target.controller_id == obj.controller_id)
        if kind == "reconfigure":
            # RULE 702.151a: "another target creature you control."
            return (
                target.is_creature
                and (not check_control or target.controller_id == obj.controller_id)
                and target is not obj
            )
        if kind == "fortify":
            # RULE 702.67a: "target land you control."
            return target.is_land and (not check_control or target.controller_id == obj.controller_id)
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
    def attach_to_target(self, obj: GameObject, target: Any, check_control: bool = True) -> bool:
        """Attach an Aura/Equipment-like object to a legal target (RULE 303/301.5).

        ``check_control=False`` is an effect attaching it outside the equip ability — see
        `_attachment_legal`."""
        if not self._attachment_legal(obj, target, check_control):
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
                if self._attachment_legal(attached, player_host, check_control=False):
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
            if self._attachment_legal(attached, host, check_control=False):
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
        ``"twice_x"`` is "twice X" (2 × the announced X).
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
            _restore_x_sentinels(effect)
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
                for mv_key in ("max_mana_value", "min_mana_value", "exact_mana_value"):
                    mv_value = getattr(target_spec, mv_key, None)
                    if mv_value == "x":
                        updates[mv_key] = x
                    elif mv_value == "-x":
                        updates[mv_key] = -x
                if updates:
                    effect.target_spec = dataclasses.replace(target_spec, **updates)
            for attr in _X_MAGNITUDE_ATTRS:
                value = getattr(effect, attr, None)
                if value == "x":
                    setattr(effect, attr, x)
                elif value == "-x":
                    setattr(effect, attr, -x)
                elif value == "twice_x":
                    setattr(effect, attr, 2 * x)  # "twice X" (Drown in Dreams, Heliod's Intervention)
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
            # every other sentinel on this spell's effects is. Skipped when the
            # effect's own ``capture`` fills that sentinel with a *different*
            # number at its own resolution (Mana Drain's "that spell's mana
            # value", `CreateDelayedTriggerEffect`) — this spell's X would
            # otherwise overwrite it first (ENG-50) — and likewise when the
            # effect announces an X of its own at resolution ("you may pay
            # {X}. If you do, …", `PayCostThenEffect.owns_x_sentinel`, ENG-48).
            if (
                getattr(effect, "capture", None) in _X_OWNING_CAPTURES
                or getattr(effect, "owns_x_sentinel", False)
            ):
                continue
            for inner_spec in getattr(effect, "inner_specs", None) or []:
                params = inner_spec.get("params") if isinstance(inner_spec, dict) else None
                if not isinstance(params, dict):
                    continue
                for attr in _X_MAGNITUDE_ATTRS:
                    value = params.get(attr)
                    if value == "x":
                        params[attr] = x
                    elif value == "-x":
                        params[attr] = -x
                    elif value == "twice_x":
                        params[attr] = 2 * x
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
        outer_resolution_count = self.context.ability_resolution_count
        outer_stack_item = self.context.resolving_stack_item
        self.context.resolving_stack_item = item
        outer_source_incarnation = getattr(self.context, "resolving_source_incarnation", None)
        self.context.resolving_source_incarnation = item.source_zone_incarnation
        self.context.trigger_event = item.trigger_event
        self.context.resolving_controller_id = item.controller_id
        self.context.ability_resolution_count = self._count_ability_resolution(item)
        try:
            return self._apply_stack_item(item)
        finally:
            self.context.resolving_stack_item = outer_stack_item
            self.context.resolving_source_incarnation = outer_source_incarnation
            self.context.trigger_event = outer_trigger_event
            self.context.resolving_controller_id = outer_resolving_controller_id
            self.context.ability_resolution_count = outer_resolution_count

    def _count_ability_resolution(self, item: StackItem) -> Optional[int]:
        """Record that ``item`` (an ability) is resolving and return which
        resolution of that ability of that object this turn it is — the one
        now resolving included, so the first resolution is 1 ("if this is the
        second time this ability has resolved this turn"; the rulings count
        resolutions, not activations, whoever controlled them, copies
        included). ``None`` for a spell or an unkeyed ability."""
        source = item.source
        if item.kind != "ability" or item.ability_key is None or source is None:
            return None
        resolutions = getattr(source, "ability_resolutions", None)
        if resolutions is None:
            return None
        turn = self.state.turn_nr
        stamped_turn, count = resolutions.get(item.ability_key, (turn, 0))
        count = (count if stamped_turn == turn else 0) + 1
        resolutions[item.ability_key] = (turn, count)
        return count
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
    #: A paid `pay_cost_then` whose payment opened a choice (the sacrifice pick): its "if you do" half waits here.
    DEFERRED_PAID_COST = "paid_cost"

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
            "acting_player_id": self.context.acting_player_id or self.context.resolving_controller_id,
        })

    @continuations.choice(
        "composite_optional",
        answer=continuations.ANSWER_FLAG,
        yes="yes",
        rule="601.2b",
    )
    def _resume_composite_optional(self, choice: dict[str, Any], accepted: bool = False) -> None:
        """Answer an ``optional`` composition node (ENG-37, RULE 601.2b).

        Declining does nothing at all, which is what "you may" means — unless the
        node carries ``else_effects`` ("…may sacrifice it. If they don't, ~ deals
        5 damage to that player." — Star Athlete, Enchanter's Bane), which run in
        that case instead.

        The body runs through `_apply_effects_partitioned`, not a plain
        `apply` loop, so a body that itself opens a choice parks the rest of
        itself the same way it would have at the top level.
        """
        specs = (choice.get("effect_specs") if accepted else choice.get("else_specs")) or []
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
        previous.extend(self.state.player_by_id(player_id)
                        for player_id in choice.get("previous_player_ids", []))
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
        announced.extend(self.state.player_by_id(player_id)
                         for player_id in choice.get("target_player_ids", []))
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
        outer_acting = self.context.acting_player_id
        self.context.acting_player_id = choice.get("acting_player_id")
        try:
            _apply_effects_partitioned(
                built, self.context, announced or None, None, source=source,
                previous_targets=previous, revealed_card=revealed,
            )
        finally:
            self.context.trigger_event = outer_trigger_event
            self.context.acting_player_id = outer_acting

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
            self.state.deferred_effects[-1]["acting_player_id"] = frame.get("acting_player_id")
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
        outer_acting = self.context.acting_player_id
        self.context.acting_player_id = frame.get("acting_player_id")
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
            self.context.acting_player_id = outer_acting

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
        if resumed.get("kind") == self.DEFERRED_PAID_COST:
            self._finish_paid_cost_then(resumed["pending"])
            if self._pending_each_player_pay_or is not None:
                self._advance_each_player_pay_or()
            return True
        stack_item = resumed.get("stack_item")
        # RULE 109.5: a paused body keeps the player it was acting as.
        # Restoring the outer scope also prevents that player leaking into
        # another ability's continuation after this nested body completes.
        outer_acting = self.context.acting_player_id
        self.context.acting_player_id = resumed.get("acting_player_id")
        try:
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
                excess_damage_this_way=resumed.get("excess_damage_this_way", 0),
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
        finally:
            self.context.acting_player_id = outer_acting
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
        # RULE 608.2b: an untargeted rider (including Empower Jace) must
        # not run when every announced target of the whole item is illegal.
        from ..targeting import effects_target_specs, partition_targets
        body = item.effects
        if len(body) == 1 and hasattr(body[0], "effects"):
            body = body[0].effects
        specs = effects_target_specs(body)
        groups = item.target_groups or partition_targets(specs, item.targets)
        checks = zip(specs, groups) if groups is not None else (
            (spec, item.targets or []) for spec in specs
        )

        resolution_targets, resolution_groups = item.targets, item.target_groups
        copy_legal = None
        if item.copy_target_roles:
            from ..stack_copy_targets import resolution_targets as copy_resolution_targets

            resolution_targets, resolution_groups, copy_legal = copy_resolution_targets(self, item)
            item.resolution_target_slots = resolution_targets
        def still_in_target_zone(spec, target):
            # Stack targets are StackItems, unlike battlefield/graveyard
            # targets. A zone move cannot leave an untargeted rider alive.
            if isinstance(target, StackItem):
                return target in self.state.stack
            if isinstance(target, Player):
                return target in self.state.living_players()
            if isinstance(target, GameObject):
                indices = [i for i, t in enumerate(item.targets) if t is target]
                if indices and not any(i >= len(item.target_incarnations)
                                       or item.target_incarnations[i] in (None, target.zone_incarnation)
                                       for i in indices):
                    return False
                if "graveyard" in spec.kind:
                    return target.zone == Zone.GRAVEYARD and any(
                        target in player.graveyard for player in self.state.players
                    )
                if spec.kind in {"spell", "spell_you_control", "spell_you_dont_control", "spell_or_ability"} or (
                    "spell" in spec.kind and target.zone == Zone.STACK
                ):
                    return any(entry.obj is target for entry in self.state.stack)
                return target.zone == Zone.BATTLEFIELD and target in self.state.battlefield
            return True

        any_legal = (any(copy_legal) if copy_legal is not None else any(
            still_in_target_zone(spec, target) for spec, group in checks for target in group
        ))
        fallback_creature = (item.obj is not None and (item.obj.bestowed or item.obj.cast_via_mutate))
        if item.targets and (specs or copy_legal is not None) and not any_legal and not fallback_creature:
            if item.kind == "spell" and item.obj is not None:
                obj = item.obj
                if obj.cast_via_flashback:
                    obj.cast_via_flashback = False
                    self.exile(obj)
                else:
                    if obj.adventure_snapshot is not None:
                        snapshot = obj.adventure_snapshot
                        obj.adventure_snapshot = None
                        self.restore_face(obj, snapshot)
                    self.state.player_by_id(obj.owner_id).add_to_zone(obj, Zone.GRAVEYARD)
                    self._flag_commander_zone_choice(obj)
            self.check_state_based_actions()
            return item

        if (
            item.kind == "spell" and item.obj is not None
            and item.obj.gift_promised and not self.is_permanent_spell(item.obj.card)
        ):
            # RULE 702.174j: an instant/sorcery's gift happens before any of its
            # other abilities. Here, not at cast time, so a countered spell (which
            # never reaches this point) gives no gift.
            self.give_gift(item.obj)
        if len(item.effects) == 1 and hasattr(item.effects[0], "effects"):
            # A single `TriggeredAbility`/`ActivatedAbility` wrapper — it
            # owns its *own* sub-effects list (`self.effects`, invisible to
            # this loop), so the per-effect partitioning has to happen one
            # level down, inside its own `apply()` (`_apply_effects_
            # partitioned`). Pass `target_groups` straight through rather
            # than treating the wrapper itself as "one targeting effect".
            self._substitute_x(item.effects[0].effects, item.x)
            item.effects[0].apply(self.context, resolution_targets, resolution_groups)
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
                item.effects, self.context, resolution_targets, resolution_groups, stack_item=item,
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
    #: RULE 702.174f/i: the fixed tokens a gift can be. Named Food/Treasure come from the
    #: token catalogue (they carry their mana/life abilities); the rest are inline.
    _GIFT_INLINE_TOKENS = {
        "tapped fish": dict(name="Fish", power=1, toughness=1, colors=["U"], tapped=True),
        "octopus": dict(name="Octopus", power=8, toughness=8, colors=["U"], tapped=False),
    }

    def give_gift(self, source: GameObject) -> bool:
        """RULE 702.174d-i: the chosen opponent receives ``source``'s promised gift.

        Returns whether a gift was actually given. Nothing happens if no gift was promised,
        or if the chosen opponent has since left the game. Fires `GIFT_GIVEN` (RULE 702.174c,
        "whenever you give a gift").
        """
        if not source.gift_promised or source.gift_recipient_id is None:
            return False
        recipient = self.state.player_by_id(source.gift_recipient_id)
        if recipient is None or recipient.has_lost:
            return False
        quality = str(((source.parametric_keywords or {}).get("gift") or {}).get("quality") or "").strip().lower()
        if quality == "card":
            self.draw(recipient, 1)                      # 702.174e
        elif quality in ("food", "treasure"):            # 702.174d / 702.174h
            from ...services.token_database import default_token_database  # avoid a services↔game cycle
            token = default_token_database().get_token(quality)
            if token is None:
                return False
            self.create_token(recipient.id, token, 1)
        elif quality in self._GIFT_INLINE_TOKENS:        # 702.174f / 702.174i
            from ...services.token_database import synthesize_token_card
            spec = dict(self._GIFT_INLINE_TOKENS[quality])
            tapped = spec.pop("tapped")
            name = spec.pop("name")
            made = self.create_token(recipient.id, synthesize_token_card(name, **spec), 1)
            if tapped:
                for token in made:
                    self.set_tapped(token, True)
        elif quality == "extra turn":                    # 702.174g
            self.state.extra_turns.append(recipient.id)
        else:
            return False
        self.state.fire_event(GameEvent(
            EventType.GIFT_GIVEN, controller_id=source.controller_id,
            recipient_id=recipient.id, quality=quality, instance_id=source.instance_id,
        ))
        return True

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
            if self._is_omen_card(obj.card):
                # RULE 720.3d: an Omen spell is shuffled into its owner's library as it resolves,
                # instead of going to the graveyard (an Adventure is exiled and castable instead).
                self.shuffle_into_library(obj)
            else:
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
        self.state.pending_permanent_entry = {"item": item, "obj": obj}

        def _finish() -> None:
            target_slots = item.resolution_target_slots if item.resolution_target_slots is not None else item.targets
            self.state.pending_permanent_entry = None
            if obj.cast_via_mutate:
                # RULE 702.140b-d: a mutate spell never enters the
                # battlefield as its own permanent — it merges onto the
                # creature it targeted, which stays the surviving object
                # (and so fires no ENTERS_BATTLEFIELD, RULE 702.140c).
                obj.cast_via_mutate = False
                host = next((t for t in target_slots if isinstance(t, GameObject)), None)
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
            ) or bool(getattr(obj, "enters_tapped_from_cast_grant", False))
            if obj.tapped and continuous.enters_untapped_from_static(self.state, obj):
                obj.tapped = False  # a land entering by an effect, under Horizon Explorer
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
            from ..blitz import resolve_blitz

            self.state.add_to_battlefield(obj, saga_lore_override=read_ahead_count)
            resolve_blitz(self.state, obj, item.controller_id)
            if self._attachment_kind(obj) == "enchant":
                targets = [t for t in target_slots if isinstance(t, (GameObject, Player))]
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
                    from_zone=Zone.STACK.value,
                    cast_from_zone=obj.cast_from_zone,
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
        if (self.state.pending_permanent_entry
                and self.state.pending_permanent_entry["obj"] is obj):
            self.state.pending_permanent_entry = None
        owner = self.state.player_by_id(obj.owner_id)
        obj.blitz_cost_paid = False  # RULE 400.7: this spell did not become a permanent.
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
        spec = TargetSpec(
            kind=effect.target_kind, max_mana_value=max_mana_value, creature_filter=effect.creature_filter,
        )
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
                if effect.until_end_of_turn and obj._copy_until_eot_base is None:
                    # Cursed Mirror: reverted at cleanup (RULE 514.2), see `become_copy_until_end_of_turn`.
                    obj._copy_until_eot_base = copy_mechanics.snapshot_face(obj)
                as_token = obj.is_token and bool(effect.token_add_subtypes or effect.token_set_colors)
                copy_mechanics.become_copy(
                    obj, target, effect.add_types,
                    effect.add_subtypes + (effect.token_add_subtypes if as_token else []),
                    only_types=effect.only_types,
                    add_keywords=effect.add_keywords + conditional_keywords,
                    not_legendary=getattr(effect, "not_legendary", False),
                    set_colors=effect.token_set_colors if as_token else None,
                )
                if effect.set_name:
                    # "…except his name is ~." — after binding (which is keyed by the copied name).
                    renamed = copy.copy(obj.card)
                    renamed.name = effect.set_name
                    obj.card = obj._front_card = renamed
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
        if getattr(effect, "is_enter_effect", False):
            # RULE 614.12: these instructions run before any entry event.
            # Consume the instruction before asking, so snapshots retain its remainder.
            obj.enter_choice_effects = remaining
            outer_actor = self.context.acting_player_id
            self.context.acting_player_id = obj.controller_id
            try:
                effect.apply(self.context)
            finally:
                self.context.acting_player_id = outer_actor
            if self.state.pending_choice:
                self.state.pending_choice["entry_effect"] = True
            else:
                self._offer_enter_choices(obj, continuation)
            return
        if isinstance(effect, ChooseColorReplacement) and effect.count > 1:
            # "choose two colors": one prompt per colour, the next one offered once this is answered.
            remaining = [ChooseColorReplacement(count=effect.count - 1), *remaining]

        def _next() -> None:
            obj.enter_choice_effects = remaining
            self._offer_enter_choices(obj, continuation)

        if isinstance(effect, ChooseCreatureTypeReplacement):
            kind = "choose_creature_type"
            prompt = "Kreaturentyp wählen"
            options = [{"id": t, "label": t} for t in _creature_type_options(self.state, obj.controller_id)]
        elif isinstance(effect, ChooseCardTypeReplacement):
            kind = "choose_card_type"
            prompt = "Kartentyp wählen"
            options = [{"id": quality, "label": label} for quality, label in _CARD_TYPE_OPTIONS]
        elif isinstance(effect, ChooseBasicLandTypeReplacement):
            kind = "choose_basic_land_type"
            prompt = "Standard-Landtyp wählen"
            options = [{"id": t, "label": t} for t in _BASIC_LAND_TYPE_OPTIONS]
        elif isinstance(effect, ChooseNamedModeReplacement):
            kind = "choose_named_mode"
            prompt = "Modus wählen"
            options = [{"id": label.strip().lower(), "label": label} for label in effect.options]
        elif isinstance(effect, ChooseEnterCounterReplacement):
            # RULE 614.1 + 122.1b: "enters with your choice of a flying counter
            # or a first strike counter" — the option id is the index, since
            # two options may share a kind and differ only in amount.
            kind = "choose_enter_counter"
            prompt = "Marke wählen, mit der es ins Spiel kommt"
            options = [
                {"id": str(i), "label": f"{o['count']}× {o['kind']}" if o["count"] > 1 else o["kind"]}
                for i, o in enumerate(effect.options)
            ]
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
            prompt = "Spieler wählen" if effect.include_self else "Gegner wählen"
            options = [
                {"id": p.id, "label": p.name}
                for p in self.state.living_players() if effect.include_self or p.id != obj.controller_id
            ]
        else:
            kind = "choose_color"
            prompt = "Farbe wählen"
            options = [
                {"id": color, "label": label} for color, label in self._ANY_COLOR_LABELS.items()
                if color not in obj.chosen_colors  # a second pick must differ from the first
            ]

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
        "choose_basic_land_type", "choose_card_type", "choose_card_name", "choose_number", "choose_opponent_on_enter",
        "choose_enter_counter",
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
        effect = self._pending_enter_choice_effect
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
            if choice["kind"] in ("choose_creature_type", "choose_basic_land_type", "choose_card_type"):
                obj.chosen_type = chosen
            elif choice["kind"] == "choose_named_mode":
                obj.chosen_mode = chosen
            elif choice["kind"] == "choose_card_name":
                obj.chosen_card_name = chosen
            elif choice["kind"] == "choose_number":
                obj.chosen_number = int(chosen)
            elif choice["kind"] == "choose_opponent_on_enter":
                obj.chosen_player_id = chosen
            elif choice["kind"] == "choose_enter_counter":
                picked = effect.options[int(chosen)] if effect is not None else None
                if picked is not None:
                    self._add_entry_counters(obj, picked["kind"], picked["count"])
            else:
                obj.chosen_color = obj.chosen_color or chosen
                obj.chosen_colors.append(chosen)
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
