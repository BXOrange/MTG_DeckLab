"""Shared predicates and serialized-branch helpers for rules subsystems."""
from __future__ import annotations

import re
from typing import Any, Optional
from ...models.cards.card import Card
from ...models.game.game_object import GameObject
from ...models.game.game_state import GameState
from ...models.mana.mana_cost import ManaCost
from ...parser.oracle.catalogue.saga import all_chapter_numbers
from .. import continuous
from ..costs import ActivationCost


#: MEC-117: the pending-choice kind for which planar-die face counts (Ichor Elixir's "ignore one").
CHOOSE_PLANAR_FACE_KIND = "choose_planar_face"

#: ENG-48: the highest {X} a resolve-time "you may pay {X}" offers. Payment
#: comes from the payer's mana pool only (`_can_pay_player_cost`), so the real
#: bound is almost always the pool itself; this only stops the affordability
#: scan (and the one-button-per-value prompt) from running away on a combo's
#: effectively unbounded pool — 30 is past any X a fair game ever pays.
PAY_COST_THEN_MAX_X = 30
#: Turntimber Symbiosis: "If that card has mana value 3 or less, it enters with three additional +1/+1 counters
#: on it." — the printed mana-value ceiling and the number of bonus counters.
CHEAP_CREATURE_MAX_MANA_VALUE = 3
CHEAP_CREATURE_BONUS_COUNTERS = 3

#: ENG-48: the option-id prefix a `pay_cost_then` choice uses for "pay with
#: X = n" (``"pay_x:3"``); a bare ``"pay"`` still answers, as the largest X.
PAY_X_OPTION_PREFIX = "pay_x:"


def _cost_with_x(cost: ActivationCost, x: int, x_color: Optional[str] = None) -> ActivationCost:
    """``cost`` with its mana's ``{X}`` announced as ``x`` (RULE 107.3a). ``x_color`` is "pay any amount of
    {R}" (Leyline Tyrant): the cost is then just ``x`` pips of that colour instead of ``x`` generic mana."""
    from dataclasses import replace  # function-scoped: only this helper needs it

    if x_color:
        return replace(cost, mana=ManaCost.parse(f"{{{x_color.upper()}}}" * x if x else "{0}"))
    return replace(cost, mana=cost.mana.with_x(x))


#: RULE 205.2a's card types — the words `_card_type_words` keeps from an object's type words.
_CARD_TYPE_WORDS = frozenset({
    "artifact", "battle", "creature", "enchantment", "instant", "land", "planeswalker", "sorcery",
    "conspiracy", "dungeon", "kindred", "phenomenon", "plane", "scheme", "vanguard",
})


def _card_type_words(obj: Any) -> set[str]:
    """The RULE 205.2a card types of ``obj`` (lowercase), without supertypes/subtypes."""
    return set(getattr(obj, "type_words", None) or ()) & _CARD_TYPE_WORDS


def _distinct_card_type_assignment(type_sets: list[set[str]]) -> bool:
    """Can every selected card represent a different card type (RULE 205.2b)?

    Reassign earlier multi-type cards when necessary; an arbitrary initial
    assignment must not hide a legal later pick.
    """
    assigned: dict[str, int] = {}

    def augment(index: int, visited: set[str]) -> bool:
        for card_type in sorted(type_sets[index]):
            if card_type in visited:
                continue
            visited.add(card_type)
            previous = assigned.get(card_type)
            if previous is None or augment(previous, visited):
                assigned[card_type] = index
                return True
        return False

    return all(augment(index, set()) for index in range(len(type_sets)))


def _that_many_value(then_that_many: Optional[dict], objs: list[Any]) -> int:
    """What "that many" counts after a `choose_objects` pick: how many were picked, or — with
    ``measure: "power"`` ("you gain X life and draw X cards, where X is that creature's power",
    Disciple of Bolas) — their total power. Read from the objects *before* they are sacrificed,
    since a card in the graveyard no longer has a battlefield power."""
    if (then_that_many or {}).get("measure") == "power":
        return sum(int(getattr(o, "power", 0) or 0) for o in objs)
    if (then_that_many or {}).get("measure") == "mana_value":
        # RULE 202.3 / 608.2h: capture the battlefield card face before
        # sacrificing it, rather than reading a reset graveyard object.
        def mana_value(obj):
            if getattr(obj, "face_down", False):
                return 0
            if getattr(obj, "is_melded", False):
                return sum(mana_value(part) for part in obj.melded_components)
            from ..rooms import has_doors

            if has_doors(getattr(obj, "card", None)):
                return obj.mana_value
            card = getattr(obj, "card", None)
            front = getattr(obj, "_front_card", None)
            # RULE 202.3b: a genuine transforming back uses the front's
            # cost. A copy of just that back has no two-face card metadata.
            if (getattr(obj, "transformed", False) and front is not None
                    and (front.back_name or front.back_type_line) and front.layout != "modal_dfc"):
                card = front
            return int(getattr(card, "converted_mana_cost", 0) or 0)
        return sum(mana_value(obj) for obj in objs)
    return len(objs)


def _substitute_x_specs(specs: list[dict], x: Optional[int]) -> list[dict]:
    """Serialized branch `EffectSpec` dicts with the ``"x"`` sentinel bound to
    a resolve-time payment's announced X (ENG-48). ``x=None`` — the cost had
    no {X} — leaves them untouched, so a branch whose "X" means the *spell's*
    own announced X (`GameObject.x_paid`) still reads that at apply time."""
    if x is None:
        return specs
    from ..effects.composition import _resolve_x  # function-scoped: effects↔rules cycle

    return [{**d, "params": _resolve_x(dict(d.get("params") or {}), x)} for d in specs]


def _substitute_x_modes(modes: dict[str, Any], x: int) -> dict[str, Any]:
    """`_substitute_x_specs` over a reflexive modal payoff's option lists."""
    if not modes.get("options"):
        return modes
    return {**modes, "options": [_substitute_x_specs(list(opt), x) for opt in modes["options"]]}


def _saga_final_chapter(card: Card) -> int:
    """The highest chapter number a Saga has (RULE 714.2c), 0 if unreadable.

    Read off the oracle text's roman-numeral chapter markers ("I —", "II, III —",
    "IV —"); the largest is the final chapter. Shares its numeral grammar with
    the oracle-parser front-end's chapter-ability recognition
    (`parser.oracle.catalogue.saga`, RULE 714.2d) rather than duplicating it."""
    return max(all_chapter_numbers(card.oracle_text or ""), default=0)


def _names_other_word(word: str) -> bool:
    """Whether a cost's permanent word says "another"/"other" — mirrors `activation_mixin._names_other`
    (kept as its own copy: `game_engine.py` imports `rules_engine.py`, not the reverse)."""
    return word.startswith("other_") or word == "another"


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
        return obj.is_artifact
    if what == "enchantment":
        return obj.is_enchantment
    if what == "land":
        return obj.is_land
    if what == "planeswalker":
        return obj.is_planeswalker
    if what == "battle":
        return obj.is_battle
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
    if what == "creature_or_planeswalker":
        # RULE 306/302: Tevesh Szat's "another creature or planeswalker" —
        # the one compound word any shipped card needs.
        return obj.is_creature or obj.is_planeswalker
    if what == "artifact_or_creature":
        # Deadly Dispute/Costly Plunder-shaped "sacrifice an artifact or
        # creature" additional cost — the single most-repeated compound
        # sacrifice cost in the cache.
        return obj.is_creature or obj.is_artifact
    if what == "creature_artifact_or_land":
        # PAR-13: "sacrifice a creature, artifact, or land of their choice"
        # (Tomb of Annihilation's "Sandfall Cell" dungeon room) — the
        # payer's own choice of *type*, not "any permanent" (which would
        # wrongly also license sacrificing an enchantment/planeswalker).
        return obj.is_creature or obj.is_artifact or obj.is_land
    if "_" in what:
        # ENG-49/ENG-51: `costs.parse_activation_cost`'s permanent-phrase
        # encoding — "an artifact or creature", "a nonland permanent" —
        # read by the same matcher the activation cost path uses.
        return continuous.matches_permanent_word(obj, what)
    # PAR-152: a word none of the above names is a subtype/state/colour/token word ("sacrifice two Blood tokens",
    # Strefan; "sacrifice a Treasure") — the shared cost matcher reads it, never "any permanent".
    return continuous.matches_permanent_word(obj, what)


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
