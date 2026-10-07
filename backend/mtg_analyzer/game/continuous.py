"""The continuous-effects layer engine (RULE 613).

Static abilities (`StaticAbility`, from `effects.py`) don't *do* anything when
they resolve — they continuously reshape other permanents' characteristics.
RULE 613 says how overlapping ones combine: apply them in a fixed sequence of
**layers**, so the board's derived characteristics are well-defined no matter
what order the abilities entered play.

This module implements every layer this engine meets:

* **Layer 1** — copy effects (RULE 707), *conditional/continuous* ones only:
  "as long as [condition], ~ is a copy of [target]" (Vesuvan Shapeshifter).
  Transition-only (see `_apply_copy_layer`) — the other two copy mechanisms
  this engine models are discrete mutations instead, since neither needs to
  revert on its own: the permanent "you may have this enter as a copy of
  target X" (RULE 614.1c/614.12, Clever Impersonator — `RulesEngine.
  _offer_enter_as_copy`, resolved *before* the object is added to the
  battlefield) and the temporary "… until end of turn" copy (Cursed Mirror —
  `RulesEngine.become_copy_until_end_of_turn`, reverted at cleanup). All
  three share `game/copy_mechanics.py`'s mutate/snapshot/restore primitives
  — see docs/11 §"Copying objects" for why they're split rather than
  unified.
* **Layer 2** — control-changing effects ("you control enchanted creature");
* **Layer 3** — text-changing effects (RULE 612), *scoped*: word-substitution
  over `GameObject.effective_oracle_text`, consumed by any per-recompute
  oracle-text scan that reads a quality off the object rather than off a
  bound ability — `combat.protections_of_text` (the canonical
  Artificial-Evolution "protection from red" → "protection from blue" case)
  and `combat._landwalk_slugs` (the same word-substitution applied to a
  "`<type>walk`" clause). This is **not** a full oracle-text re-parse — bound
  abilities/keywords still come from the *printed* text once at bind time,
  unaffected. A card that grants *another* ability to other
  permanents ("Elves you control have '{T}: Add {B}.'" — Tyvar Kell; "Elves
  you control have '<triggered ability>'" — Dionus, Elvish Archdruid) is
  **not** a layer-3 case despite CR 612.1's mention of "text … granted… by
  other effects": RULE 613.1 puts ability-adding/removing in layer 6, and
  that's what these are, templated exactly like the layer-6 keyword grants
  below (`grant_keyword`) — just granting a mana ability or a full triggered
  ability instead of a bare keyword.
* **Layer 4** — type-changing effects ("… are creatures");
* **Layer 5** — colour-changing effects ("enchanted creature is black");
* **Layer 6** — ability-adding effects ("… have flying");
* **Layer 7** — power/toughness, in full sublayer order: 7a characteristic-
  defining P/T, 7b set, 7c counters, 7d modify (anthems), 7e switch.

Plus a non-layer bucket, **cost adjustments** (RULE 601.2f — "spells cost {N}
less"), which aren't part of 613 but are the other everyday static effect and
are computed here for the same recompute.

RULE 613.8's *dependency* system (an effect whose order depends on another
applying first) is modeled **only within layer 2** (`_order_control_effects`)
— confirmed by tracing every selector this engine has that a same-sublayer
effect could depend on: a `pt_cda`'s count-selectors (`_count_selector`) can
only *count* objects (creatures/lands/permanents/artifacts you control, cards
in a graveyard), never read another object's power/toughness, so no 7a
dependency is constructible at all; every other sublayer (pt_set/pt_mod/
pt_switch/type/color/ability) can't construct one either. Layer 2 is the one
real case: a controller-scoped `affects` ("creatures you control") can see a
different object set depending on whether another control-change ran first —
the textbook CR 613.8 example. Elsewhere, ordering is by timestamp only
(RULE 613.7, `_in_layer`).

`recompute(state)` resets every battlefield object's derived characteristics
and re-derives them from scratch, stamping the result — and a per-object,
per-layer **trace** — back onto each `GameObject` (`_derived_power`,
`_granted_keywords`, `_added_types`, `static_trace`). The engine calls it
whenever the board settles (state-based actions) and before serialization, so
reads of `obj.power`/`obj.is_creature`/`combat.keywords_of` see the live layer
stack.
"""

from __future__ import annotations

import copy
import re
from typing import TYPE_CHECKING, Any, Optional, Union

from . import durations, static_conditions, variants
from .costs import parse_activation_cost
from .creature_types import CREATURE_SUBTYPES
from .effects.core import (
    ActivatedAbility, ConditionalEffect, EffectRegistry, ReplacementEffect,
    ReplacementRegistry, StaticAbility, TriggeredAbility,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models.game.game_object import GameObject
    from ..models.game.game_state import GameState
    from ..models.game.player import Player


#: An asymmetric P/T counter kind ("+0/+1", "-0/-2") — each half a signed delta per counter.
_PT_COUNTER_KIND_RE = re.compile(r"([+-]\d+)/([+-]\d+)")


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


#: RULE 305.6's five basic land types, lowercased — the trigger for RULE
#: 305.7's "setting a land's subtype removes its rules text and abilities"
#: (Blood Moon/Magus of the Moon), which is what tells an ordinary layer-4
#: subtype overwrite apart from a land-type one.
_BASIC_LAND_TYPES: frozenset[str] = frozenset(
    {"plains", "island", "swamp", "mountain", "forest"}
)


def _has_subtype(obj: "GameObject", subtype: str) -> bool:
    """Whether ``obj`` has creature subtype ``subtype`` (RULE 205.3, tribal lords).

    A case-insensitive match against the printed type line's subtype portion —
    the same substring approach the tutor's `card_query` uses ("Goblin" matches
    "Creature — Goblin Warrior"). Changeling (RULE 702.73) is every creature
    type, so it matches every subtype in the CR creature-type list.

    A layer-4 "type overwrite" static (RULE 613.5 — `_derived_subtypes`,
    e.g. Blood Moon's "Nonbasic lands are Mountains") takes priority when
    set: the object's *printed* subtypes (and Changeling) no longer apply at
    all once its subtype set has been wholesale replaced. This isn't a fixed
    precedence between the two attributes, though — RULE 613.7's timestamp
    order decides which one an "add" grant (Urborg/Yavimaya's "in addition
    to its other land types") actually lands in: the layer-4 loop below
    folds an add that runs *after* an overwrite directly into
    `_derived_subtypes` (so it stacks on top — a land can end up "Mountain
    Swamp"), while one that ran *before* the overwrite stays in
    `_added_subtypes` and is correctly wiped out the moment the overwrite
    replaces the set outright.
    """
    override = getattr(obj, "_derived_subtypes", None)
    if override is not None:
        words = {s.lower() for s in override}
        return subtype.lower() in words or (ALL_CREATURE_TYPES in words and subtype.lower().replace("’", "'") in CREATURE_SUBTYPES)
    added = getattr(obj, "_added_subtypes", None)
    # PAR-109: "equipped creature … is every creature type" (Amorphous Axe, Runed Stalactite) adds the
    # `ALL_CREATURE_TYPES` marker — a changeling, granted rather than printed (RULE 702.73a).
    if added and (subtype.lower() in {s.lower() for s in added} or (ALL_CREATURE_TYPES in {s.lower() for s in added} and subtype.lower().replace("’", "'") in CREATURE_SUBTYPES)):
        # RULE 613.4a: a layer-4 "~ is the chosen type in addition to its
        # other types" grant (`add_subtypes`/`add_subtypes_from_source`,
        # Adaptive Automaton/A-Thran Portal-shaped) — additive, unlike
        # `_derived_subtypes`'s full RULE 613.5 overwrite above.
        return True
    type_line = obj.card.type_line.lower()
    if "changeling" in type_line or "changeling" in obj.intrinsic_keywords:
        if subtype.lower().replace("’", "'") in CREATURE_SUBTYPES:
            return True
    _, _, sub = type_line.partition("—")  # subtypes follow the em dash
    return subtype.lower() in sub


#: The marker `type_change`'s ``add_subtypes`` carries for "is every creature type" — read by `has_subtype`.
ALL_CREATURE_TYPES = "changeling"


def derived_subtype_words(obj: "GameObject") -> frozenset[str]:
    """``obj``'s *current* subtypes, lowercased — the printed ones plus any a layer-4 effect added (or, under a
    RULE 613.5 overwrite, only those). The last-known-information snapshot a leaves-the-battlefield event carries
    (RULE 603.10a/608.2h): "…if it wasn't a Demon" must see a Demon the layer engine made it, not just the type
    line. Changeling expands to RULE 205.3m creature types, never artifact/land types."""
    override = getattr(obj, "_derived_subtypes", None)
    if override is not None:
        words = {str(s).lower() for s in override}
        changeling = ALL_CREATURE_TYPES in words
    else:
        _, _, printed = str(getattr(getattr(obj, "card", None), "type_line", "") or "").partition("—")
        added = getattr(obj, "_added_subtypes", None) or ()
        words = { *printed.lower().split(), *(str(s).lower() for s in added) }
        changeling = ALL_CREATURE_TYPES in words or "changeling" in obj.intrinsic_keywords
    if changeling:
        words.update(CREATURE_SUBTYPES)
    return frozenset(words)


def has_subtype(obj: "GameObject", subtype: str) -> bool:
    """Public wrapper over `_has_subtype` for callers outside this module
    (e.g. `game_engine`'s "tap N untapped Elves you control" cost, RULE
    602.1 — `game/costs.py`'s ``tap_others``)."""
    return _has_subtype(obj, subtype)


#: RULE 122.1b: the counter kinds that are *keyword counters* → the keyword
#: slug (`combat.COMBAT_KEYWORDS`' vocabulary) a permanent carrying one gains.
#: Counter kinds are stored as the oracle prints them ("first strike"), the
#: slug is the underscore form every other keyword grant uses. `decayed` and
#: `exalted` (also listed in 122.1b) are left out: neither is a combat keyword
#: the layer engine reads today, so a counter of either stays an inert tracker.
KEYWORD_COUNTER_SLUGS: dict[str, str] = {
    "flying": "flying", "first strike": "first_strike", "double strike": "double_strike",
    "deathtouch": "deathtouch", "haste": "haste", "hexproof": "hexproof",
    "indestructible": "indestructible", "lifelink": "lifelink", "menace": "menace",
    "reach": "reach", "shadow": "shadow", "trample": "trample", "vigilance": "vigilance",
}

#: Printed card-type word → the `Card` boolean flag it reads (RULE 300-ish
#: type vocabulary) — the small, closed set the "opponent-scoped enters-
#: tapped"/"activation prohibition"/"type overwrite" static families narrow
#: their `affects` selector by (`card_type` param, `parser.oracle.catalogue.
#: static_handlers._CARD_TYPE_WORDS`).
_CARD_TYPE_ATTRS: dict[str, str] = {
    "artifact": "is_artifact",
    "creature": "is_creature",
    "enchantment": "is_enchantment",
    "land": "is_land",
    "planeswalker": "is_planeswalker",
    # Added for `_spell_type_matches`'s "instant and sorcery spells you cast
    # cost {N} less to cast" (Baral, Chief of Compliance-shaped) — every
    # existing `_has_card_type` caller before this had only ever needed the
    # five permanent-type words above (a battlefield permanent is never an
    # instant/sorcery/battle), so a spell-type check naming one of these
    # three silently always returned ``False``. No shipped card exercised
    # this path yet — Thalia/Thorn of Amethyst/Vryn Wingmare's "noncreature"
    # scope bypasses `_has_card_type` entirely via its own special case.
    "instant": "is_instant",
    "sorcery": "is_sorcery",
    "battle": "is_battle",
}


def _has_card_type(obj: "GameObject", card_type: str) -> bool:
    """Whether ``obj``'s *printed* card is of ``card_type`` — reads the
    `Card` flags directly (not layer-4 `_added_types`), since every static
    family that uses this filters on the entering/affected object's own
    printed identity (an artifact staying an artifact regardless of any
    other layer effect in play). ``"permanent"`` (RULE 110.1) always
    matches — everything on the battlefield is one."""
    if card_type == "permanent":
        return True
    attr = _CARD_TYPE_ATTRS.get(card_type)
    return bool(attr and getattr(obj.card, attr, False))


def has_card_type(obj: "GameObject", card_type: str) -> bool:
    """Public wrapper over `_has_card_type` for callers outside this module
    (e.g. `game_engine`'s "tap an untapped creature you control" `tap_others`
    cost — RULE 602.1/118.9 — whose printed word is a *main* type, unlike
    `has_subtype`'s "tap N untapped Elves" wording)."""
    return _has_card_type(obj, card_type)


#: ENG-51: the colour words a cost may qualify a permanent by ("sacrifice a
#: black creature") → the WUBRG letter `GameObject.colors` carries.
_COST_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}
#: Supertypes a cost may qualify a permanent by ("sacrifice a basic land").
_COST_SUPERTYPE_WORDS: frozenset[str] = frozenset({"basic", "snow", "legendary", "world"})


def matches_permanent_word(obj: "GameObject", word: str) -> bool:
    """Whether ``obj`` fits a cost's permanent phrase (ENG-51).

    ``word`` is `costs.parse_activation_cost`'s encoding of a phrase like
    "an artifact or creature" (``artifact_or_creature`` — either half), "a
    noncreature artifact" (``noncreature_artifact`` — every part), or a
    single word: a card type, colour, supertype, "token"/"non<type>", a
    tapped state, "defender"/"flying", else a subtype (RULE 205.3). "other"
    always matches here — excluding the ability's own source is the
    caller's job, since only it knows the source."""
    if "_or_" in word:
        return any(matches_permanent_word(obj, part) for part in word.split("_or_"))
    if "_" in word:
        return all(matches_permanent_word(obj, part) for part in word.split("_"))
    if word in ("permanent", "other", "another"):
        return True
    if word == "creature":
        return obj.is_creature
    if word == "land":
        return obj.is_land
    if word in _CARD_TYPE_ATTRS:
        return _has_card_type(obj, word)
    if word in _COST_COLOR_WORDS:
        return _COST_COLOR_WORDS[word] in (obj.colors or ())
    if word == "colorless":
        return not obj.colors
    if word == "multicolored":
        return len(obj.colors or ()) > 1
    if word in _COST_SUPERTYPE_WORDS:
        return word in (obj.card.type_line or "").lower().split("—")[0]
    if word == "token":
        return bool(getattr(obj, "is_token", False))
    if word == "nontoken":
        return not getattr(obj, "is_token", False)
    if word.startswith("non") and len(word) > len("non"):
        return not matches_permanent_word(obj, word[len("non"):])
    if word in ("tapped", "untapped"):
        return bool(obj.tapped) == (word == "tapped")
    if word in ("defender", "flying"):
        from . import combat  # function-scoped: combat imports continuous

        return combat.has_defender(obj) if word == "defender" else combat.has_flying(obj)
    return _has_subtype(obj, word)


def _is_nonbasic(obj: "GameObject") -> bool:
    """RULE 205.4a: a land with no "Basic" supertype (the same substring
    check `game/targeting.py`'s "nonbasic land" filter already uses)."""
    return "basic" not in obj.card.type_line.lower()


def _has_color(obj: "GameObject", colors: list) -> bool:
    """Whether ``obj`` is any of ``colors`` (RULE 105 / colour-scoped anthems).

    Reads the object's effective ``colors`` (a layer-5 colour-changing effect
    if one applies, else the printed ``color_identity`` — the same field the
    tutor's `card_query` matches on). ``"C"`` means colourless — no WUBRG.
    """
    identity = obj.colors
    wubrg = identity & {"W", "U", "B", "R", "G"}
    for c in colors:
        if c == "C":
            if not wubrg:
                return True
        elif c in identity:
            return True
    return False


def group_selector_objects(
    state: "GameState",
    controller_id: Optional[str],
    affects: "str | dict[str, Any]",
    params: Optional[dict[str, Any]] = None,
    src: Optional["GameObject"] = None,
) -> list["GameObject"]:
    """The battlefield objects an ``affects`` selector picks out.

    The selector vocabulary a static anthem's ``affects``/``params`` name
    (`affected_objects`, below); factored out so a one-shot group effect —
    e.g. a Saga chapter's "creatures you control get +N/+N until end of
    turn" (`PumpEffect.selector`) — can resolve the same "creatures you
    control"/subtype/colour/token/exclude-self vocabulary without a
    `StaticAbility` to hang it off. "you control" is scoped by
    ``controller_id``; with none given (a bare test fixture) those selectors
    match nothing. ``src`` is only needed for ``"self"``/``"attached_
    permanent"``/``"other_creatures_you_control"``/``exclude_self``.

    ``affects`` is a named string (the vocabulary below) or, since
    PARSER_VERSION 473, a structured ``{"zone", "of", "filter"}`` selector
    (`_structured_selector_objects` — the same shape `count_selector`
    already accepts, this function's own object-returning sibling). This
    function is inherently battlefield-scoped (its own docstring), so a
    structured selector naming any other zone matches nothing here rather
    than reading that zone — a caller asking this function for "the group"
    means the *battlefield* group.
    """
    params = params or {}
    # RULE 702.26c: a phased-out permanent is treated as though it doesn't
    # exist — invisible to every static-ability selector below.
    battlefield = state.permanents()

    if isinstance(affects, dict):
        if affects.get("zone", "battlefield") != "battlefield":
            return []
        result = _structured_selector_objects(state, controller_id, affects, src)
    elif affects == "objects":
        # A RULE 611 floating static aimed at *specific* permanents chosen
        # when it resolved ("target creature gains flying until your next
        # turn") — the ids travel on the ability, since a target isn't
        # expressible as a selector. A permanent that has since left simply
        # drops out, which is RULE 611.2c: the effect keeps applying to the
        # others.
        wanted = set(params.get("object_ids") or [])
        result = [o for o in battlefield if o.instance_id in wanted]
    elif affects == "self":
        result = [src] if src is not None and src in battlefield else []
    elif affects == "all_creatures":
        result = [o for o in battlefield if o.is_creature]
    elif affects == "all_other_creatures":
        # RULE 109.5 — an unscoped "each other creature" excludes only
        # the ability's source, irrespective of controller.
        result = [o for o in battlefield if o.is_creature and o is not src]
    elif affects == "all_permanents":
        result = list(battlefield)
    elif affects == "attached_permanent":
        host_id = getattr(src, "attached_to", None)
        result = [o for o in battlefield if host_id is not None and o.instance_id == host_id]
    elif affects == "chosen_permanent":
        # RULE 601.2b-adjacent "the chosen permanent" (MEC-26, Scheming
        # Fence's "as this creature enters, you may choose a nonland
        # permanent" — the object-choice sibling of `attached_permanent`
        # just above, reading `GameObject.chosen_permanent_id` instead of
        # `.attached_to`. Naturally yields nothing while undeclined/
        # declined or once the chosen permanent has left the battlefield.
        chosen_id = getattr(src, "chosen_permanent_id", None)
        result = [o for o in battlefield if chosen_id is not None and o.instance_id == chosen_id]
    elif affects == "soulbond_pair":
        # RULE 702.94b: "As long as ~ is paired with another creature, **each
        # of those creatures** has …" — the source and its partner, and only
        # while the pair actually holds (`GameObject.paired_with`, which
        # `RulesEngine.break_illegal_soulbond_pairs` clears as an SBA the
        # moment it stops being legal). Unpaired, this selects nothing at
        # all, so the grant simply isn't there.
        partner_id = getattr(src, "paired_with", None)
        result = (
            []
            if src is None or partner_id is None or src not in battlefield
            else [o for o in battlefield if o.instance_id in (src.instance_id, partner_id)]
        )
    elif affects == "all_lands":
        result = [o for o in battlefield if o.is_land]
    elif affects == "opponents_permanents":
        # "Artifacts your opponents control enter tapped." (Manglehorn) —
        # the mirror image of every "you control" selector below: everyone
        # *except* the ability's own source's controller. Unlike those,
        # ``controller_id`` here is the reference point ("you"), not a
        # membership filter, so it still needs its own None-guard rather
        # than falling into the shared ``elif controller_id is None`` below.
        result = [] if controller_id is None else [
            o for o in battlefield if o.controller_id not in (None, controller_id)
        ]
    elif controller_id is None:
        result = []
    elif affects == "creatures_opponents_control":
        # "Goad all creatures your opponents control." / "…all creatures you
        # don't control." — the creature-scoped sibling of
        # ``opponents_permanents`` above, sharing its name with the
        # already-existing `count_selector` of the same shape so one idiom
        # covers both counting them and acting on them.
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id not in (None, controller_id)
        ]
    elif affects == "creatures_opponents_control_with_a_counter":
        # "Creatures your opponents control with counters on them can't
        # attack or block." (Kulrath Knight) — the opponent-scoped sibling
        # of ``creatures_you_control_with_a_counter`` below; any counter
        # kind, any positive count (RULE 122.1).
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id not in (None, controller_id)
            and any(v for v in (o.counters or {}).values())
        ]
    elif affects == "creatures_you_control":
        result = [o for o in battlefield if o.is_creature and o.controller_id == controller_id]
    elif affects == "non_human_creatures_you_control":
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id
            and not _has_subtype(o, "human")
        ]
    elif affects == "creatures_you_control_with_a_counter":
        # "Each creature you control with a counter on it gains firebending
        # N …" (Iroh, Dragon of the West, PAR-30) — any counter kind, any
        # positive count (RULE 122.1 / 701.19).
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id
            and any(v for v in (o.counters or {}).values())
        ]
    elif affects == "nontoken_creatures_you_control":
        # "Nontoken creatures you control are Forest lands in addition to
        # their other types." (Ashaya, Soul of the Wild, MEC-12) — the
        # token-excluding sibling of ``creatures_you_control``, RULE 108.3's
        # "nontoken" filter applied to the controller-scoped creature set.
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id and not o.is_token
        ]
    elif affects == "other_creatures_you_control":
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id and o is not src
        ]
    elif affects == "other_planeswalkers_you_control":
        # "…and a loyalty counter on each **other** planeswalker you
        # control." (Ajani Steadfast's own -2, MEC-30) — the planeswalker-
        # scoped sibling of ``other_creatures_you_control`` just above,
        # same RULE 109.5 "another" self-exclusion.
        result = [
            o for o in battlefield
            if o.is_planeswalker and o.controller_id == controller_id and o is not src
        ]
    elif affects == "other_nonhuman_creatures_you_control":
        # "Other non-Human creatures you control get +1/+1 and have
        # undying." (Mikaeus, the Unhallowed) — ``other_creatures_you_
        # control`` narrowed by a negated subtype, the same shape
        # `nonlegendary_creatures_you_control` uses for a negated
        # supertype.
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id and o is not src
            and not _has_subtype(o, "human")
        ]
    elif affects == "attacking_creatures":
        # "Attacking creatures get +1/+1 until end of turn." (Motivated
        # Pony) — unscoped by controller, matching the literal printed
        # text (every creature currently attacking, same convention
        # `count_selector`'s own ``"attacking_creatures"`` uses).
        result = [o for o in battlefield if o.is_creature and o.attacking]
    elif affects == "other_attacking_creatures":
        # RULE 702.92a Battle Cry — "each *other* attacking creature gets
        # +1/+0 until end of turn": ``attacking_creatures`` minus the
        # source, the same RULE 109.5 self-exclusion ``other_creatures_
        # you_control`` applies (PAR-24).
        result = [
            o for o in battlefield
            if o.is_creature and o.attacking and o is not src
        ]
    elif affects == "attacking_creatures_you_control":
        # "Attacking creatures you control have first strike …" — the
        # controller-scoped sibling of ``attacking_creatures``.
        result = [
            o for o in battlefield
            if o.is_creature and o.attacking and o.controller_id == controller_id
        ]
    elif affects.startswith("attacking_creatures_you_control_of_type_"):
        # "Attacking Pests/Vampires/Pirates/Elves you control get/have …"
        # (Blight Mound, Crossway Troublemakers, Dire Fleet Neckbreaker,
        # Elderfang Venom, PAR-60 wave 19) — ``attacking_creatures_you_
        # control`` narrowed by a printed creature subtype, the combat-state
        # sibling of ``creatures_you_control_of_type_<subtype>`` above.
        creature_type = affects[len("attacking_creatures_you_control_of_type_"):]
        result = [
            o for o in battlefield
            if o.is_creature and o.attacking and o.controller_id == controller_id
            and _has_subtype(o, creature_type)
        ]
    elif affects == "legendary_creatures_you_control":
        # "Legendary creatures you control get +2/+1 and have ward {1}."
        # (Flowering of the White Tree) — RULE 205.4a's supertype, the
        # same printed-type-line check `count_selector`'s own
        # ``legendary_creatures_you_control`` counter uses.
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id
            and "legendary" in o.card.type_line.lower()
        ]
    elif affects == "legendary_permanents_you_control":
        # "Each legendary permanent you control has ward {2}." (Gold-Forged
        # Thopteryx) — RULE 205.4a's supertype on any permanent, the
        # non-creature sibling of ``legendary_creatures_you_control`` above.
        result = [
            o for o in battlefield
            if o.controller_id == controller_id and "legendary" in o.card.type_line.lower()
        ]
    elif affects == "nonlegendary_creatures_you_control":
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id
            and "legendary" not in o.card.type_line.lower()
        ]
    elif affects == "permanents_you_control":
        result = [o for o in battlefield if o.controller_id == controller_id]
    elif affects.startswith("creatures_you_control_of_type_"):
        # "Elves you control get +2/+2 and gain deathtouch until end of
        # turn." (Elvish Warmaster/Ezuri, Renegade Leader-shaped) — the
        # one-shot-pump sibling of `count_selector`'s own identically-named
        # branch (that one *counts* matching creatures; this one *picks*
        # them out to pump/grant a keyword to).
        creature_type = affects[len("creatures_you_control_of_type_"):]
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id and _has_subtype(o, creature_type)
        ]
    elif affects.startswith("creatures_you_control_of_color_"):
        # "Untap all white creatures you control." (Battle Cry, PAR-124) —
        # the colour-scoped sibling of `creatures_you_control_of_type_`
        # just above; `GameObject.colors` is the layer-5 derived colour set
        # (RULE 105), same accessor the count-selector/damage-filter
        # colour checks elsewhere in this file already read.
        letter = affects[len("creatures_you_control_of_color_"):].upper()
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id and letter in (o.colors or ())
        ]
    elif affects == "nonland_permanents_you_control":
        # "Untap all nonland permanents you control." (Dramatic Reversal)
        result = [
            o for o in battlefield
            if not o.is_land and o.controller_id == controller_id
        ]
    elif affects == "lands_you_control":
        result = [o for o in battlefield if o.is_land and o.controller_id == controller_id]
    elif affects.startswith("lands_you_control_of_type_"):
        # "Untap all Forests you control." (Woodland Guidance — RULE 205.3i
        # land subtypes), the land sibling of ``creatures_you_control_of_
        # type_<x>`` just above.
        land_subtype = affects[len("lands_you_control_of_type_"):]
        result = [
            o for o in battlefield
            if o.is_land and o.controller_id == controller_id
            and land_subtype in o.card.type_line.lower()
        ]
    elif affects == "commander_creatures_you_own":
        # "Commander creatures you own have '<ability>'." (Acolyte of
        # Bahamut/Agent of the Iron Throne/Candlekeep Sage-shaped) —
        # ownership (RULE 108.3), not control: a commander that's changed
        # hands (control-stealing) still belongs to its owner for this
        # purpose, unlike every "_you_control" selector above/below, which
        # is why this checks ``owner_id`` rather than ``controller_id``.
        result = [
            o for o in battlefield
            if o.is_creature and o.is_commander and o.owner_id == controller_id
        ]
    elif affects == "artifacts_you_control":
        result = [o for o in battlefield if o.card.is_artifact and o.controller_id == controller_id]
    elif affects == "enchanted_or_equipped_creatures_you_control":
        # Halvar, God of Battle's "creatures you control that are enchanted
        # or equipped" — a creature you control with *anything* (Aura or
        # Equipment) currently attached to it.
        attached_hosts = {o.attached_to for o in battlefield if o.attached_to is not None}
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id and o.instance_id in attached_hosts
        ]
    else:
        result = []

    # RULE 613.6: the ability's "as long as <condition>" gate, if any. One
    # whitelisted vocabulary (`game/static_conditions.py`) evaluated live
    # every recompute — an inactive gate means nothing here matches at all,
    # so the whole static simply isn't there this pass. ``condition`` is the
    # general form; `condition_from_legacy_params` covers the three gates
    # that predate it (``active_player_only`` — "During your turn, creatures
    # you control have first strike", Nahiri; ``min_level``/``max_level`` —
    # a Class/Leveler's own counters; ``min_count_selector``/``min_count`` —
    # Metalcraft) so both spellings run through the same evaluator.
    #
    # Spelled ``active_if`` rather than the obvious ``condition``: a
    # ``combat_restriction`` static already carries a ``condition`` param of
    # its own — "~ can't attack **unless** defending player controls an
    # Island" — evaluated at *combat* time against a defending player, which
    # nothing here can see. Two different vocabularies under one key would
    # have made each fail closed on the other's dicts.
    for gate in (
        params.get("active_if"),
        static_conditions.condition_from_legacy_params(params),
    ):
        if gate and not static_conditions.condition_holds(gate, state, src, controller_id):
            return []

    # "… of the chosen type/color …" (RULE 601.2b, Adaptive Automaton/Ward
    # Sliver-shaped) — the dynamic sibling of the literal ``subtype``/
    # ``color`` params below: reads the ability's own source's `chosen_type`/
    # `chosen_color` (stamped by `RulesEngine._resume_choose_creature_type`) fresh
    # every recompute, rather than a fixed literal baked in at parse time.
    # ``None`` (the choice hasn't happened yet, or the source has left)
    # narrows to "nothing" — the same safe fallback a plain unset filter gets.
    if params.get("subtype_from_source"):
        subtype = getattr(src, "chosen_type", None)
        if not subtype:  # choice not made yet (or source has left) → nothing matches
            return []
    else:
        subtype = params.get("subtype")
    if subtype:
        result = [o for o in result if _has_subtype(o, str(subtype))]
    if params.get("color_from_source"):
        chosen_color = getattr(src, "chosen_color", None)
        if not chosen_color:
            return []
        color = [chosen_color]
    else:
        color = params.get("color")
    if color:  # colour-scoped anthem ("Black creatures get +1/+1", Bad Moon)
        result = [o for o in result if _has_color(o, list(color))]
    if params.get("card_name_from_source"):
        # "… with the chosen name …" (MEC-12, Pithing Needle/Phyrexian
        # Revoker) — the naming-choice sibling of ``subtype_from_source``/
        # ``color_from_source`` just above: reads the ability's own
        # source's `chosen_card_name` (stamped by `RulesEngine.
        # _resume_choose_creature_type`) fresh every recompute. ``None`` (the
        # choice hasn't happened yet, or the source has left) narrows to
        # "nothing", the same safe fallback those two selectors use.
        chosen_name = getattr(src, "chosen_card_name", None)
        if not chosen_name:
            return []
        result = [o for o in result if getattr(o.card, "name", None) == chosen_name]
    if params.get("tokens"):  # "creature tokens you control …" (RULE 111)
        result = [o for o in result if getattr(o, "is_token", False)]
    if params.get("exclude_self"):  # a global "Other creatures …" anthem
        result = [o for o in result if o is not src]
    card_type = params.get("card_type")
    if card_type:  # "Artifacts your opponents control…", "Nonbasic lands are…"
        # A list means an "or" of types ("…activate abilities of artifacts,
        # creatures, or enchantments" — Grand Abolisher/Myrel, Shield of
        # Argive), the plural sibling of the single-string literal every
        # other caller still passes.
        types = card_type if isinstance(card_type, (list, tuple)) else [card_type]
        result = [o for o in result if any(_has_card_type(o, str(t)) for t in types)]
    if params.get("nonbasic"):  # "Nonbasic lands …" (RULE 205.4a)
        result = [o for o in result if _is_nonbasic(o)]
    # PAR-134: a state/supertype/designation adjective or a coordinated list
    # ("Tapped creatures …", "Nonlegendary artifact creatures …", "Ninja and
    # Rogue creatures …", "Commanders …") — one `combat.matches_object_filter`
    # dict, the project's single object-characteristic vocabulary, instead of
    # the parser guessing the adjective is a creature subtype. ``src`` is the
    # filter's reference object (``not_reference`` = "other …" inside a list).
    object_filter = params.get("object_filter")
    if object_filter:
        from . import combat  # function-scoped: combat imports continuous

        result = [
            o for o in result
            if combat.matches_object_filter(o, object_filter, reference=src, state=state)
        ]

    # A per-object power/toughness qualifier on the scope itself ("Each
    # creature you control **with power 4 or greater** can't be blocked by
    # more than one creature." — Challenger Troll/Flopsie-shaped), unlike
    # every filter above (all about a *type*/colour, never the affected
    # object's own characteristics). Reads *derived* power/toughness, same as
    # `combat.matches_object_filter`'s own min/max keys, so an anthem that
    # fired earlier this same recompute pass is honoured (`continuous.
    # recompute` stamps combat restrictions after the layer-7 P/T pass for
    # exactly this reason).
    min_power = params.get("min_power")
    if min_power is not None:
        result = [o for o in result if (o.power or 0) >= min_power]
    max_power = params.get("max_power")
    if max_power is not None:
        result = [o for o in result if (o.power or 0) <= max_power]
    min_toughness = params.get("min_toughness")
    if min_toughness is not None:
        result = [o for o in result if (o.toughness or 0) >= min_toughness]
    max_toughness = params.get("max_toughness")
    if max_toughness is not None:
        result = [o for o in result if (o.toughness or 0) <= max_toughness]

    # "Creatures you control **with +1/+1 counters on them** …" (MEC-21,
    # Agatha's Soul Cauldron) — a counter-presence qualifier on the scope
    # itself, the same "filter the affected group by the object's own
    # state" idiom as the min/max power/toughness keys just above.
    has_counter_kind = params.get("has_counter_kind")
    if has_counter_kind:
        result = [o for o in result if o.counters.get(str(has_counter_kind), 0) > 0]

    # The *dynamic* sibling of the literal min/max keys just above: a
    # threshold read off the board rather than fixed at parse time
    # ("Creatures your opponents control **with power less than ~'s power**
    # are goaded." — Baeloth Barrityl). Strict ``<``/``>``, matching the
    # printed "less/greater than"; the "N or more/less" phrasings keep using
    # the inclusive literal keys. Same idea `combat.matches_object_filter`'s
    # ``power_lt_count_selector`` already applies to a board count, and the
    # same reason it has to be dynamic: ~'s own power is itself layer-engine
    # output, so an anthem on ~ moves the threshold.
    for key, keep in (
        ("power_lt_selector", lambda p, n: p < n),
        ("power_gt_selector", lambda p, n: p > n),
    ):
        selector = params.get(key)
        if not selector:
            continue
        threshold = dynamic_threshold(state, controller_id, str(selector), src)
        if threshold is None:
            return []  # the source is gone — nothing to compare against
        result = [o for o in result if keep(o.power or 0, threshold)]

    return result


def dynamic_threshold(
    state: "GameState",
    controller_id: Optional[str],
    selector: str,
    source: Optional["GameObject"] = None,
) -> Optional[int]:
    """A power/toughness comparison threshold read off the board.

    Two vocabularies in one lookup, because both appear in the same printed
    position ("with power less than **~'s power**" / "with power less than
    **the number of Islands you control**"): the source's own *derived*
    characteristics first, then `count_selector`'s whole board-count list —
    which, like everywhere else it's used, answers ``0`` for a name it
    doesn't know rather than raising. ``None`` only when the source itself is
    needed and absent, which the caller reads as "nothing matches".
    """
    if selector == "source_power":
        return None if source is None else int(getattr(source, "power", 0) or 0)
    if selector == "source_toughness":
        return None if source is None else int(getattr(source, "toughness", 0) or 0)
    return count_selector(state, controller_id, selector, source)


def affected_objects(state: "GameState", ability: StaticAbility) -> list["GameObject"]:
    """The battlefield objects a static ability's ``affects`` selector picks
    out — a thin wrapper over `group_selector_objects` reading the selector,
    controller and params off the ability's own source (RULE 613).

    ``"attached_permanent"`` is the Aura/Equipment/Fortify/Reconfigure case —
    "enchanted/equipped creature", "fortified land" — resolved off the
    ability's own source's ``attached_to`` (RULE 303.4/301.5), not a
    controller-scoped set. It naturally yields nothing while unattached or
    once the source itself has left the battlefield (`_battlefield_static_
    abilities` only gathers abilities from objects currently in play).
    """
    src = ability.source
    controller = getattr(src, "controller_id", None)
    params = ability.params
    # A RULE 611 floating static carries its chosen permanents on the ability
    # (`StaticAbility.object_ids`) rather than in ``params``, since they're
    # resolution-time data and not card-text-derived; fold them in for the
    # ``objects`` selector without mutating the shared params dict.
    object_ids = getattr(ability, "object_ids", None)
    if object_ids:
        params = {**params, "object_ids": list(object_ids)}
    # "You" for a floating static is the player who created it, not the
    # source's current controller — a stolen source doesn't re-aim an
    # already-resolved continuous effect (RULE 611.2b).
    owner = (getattr(ability, "duration_data", None) or {}).get("player_id")
    if owner is not None:
        controller = owner
    return group_selector_objects(state, controller, ability.affects, params, src=src)


def _source_name(ability: StaticAbility) -> str:
    # An emblem's synthetic `source` (RULE 114.5: no name of its own, unlike
    # a real permanent) has no `.name` — falls back to "static" the same as
    # no source at all.
    src = ability.source
    return getattr(src, "name", None) or "static"


def _trace(
    obj: "GameObject",
    layer: Any,
    label: str,
    description: str,
    power: Any = None,
    toughness: Any = None,
    duration: str = "static",
) -> None:
    # ``duration`` classifies how long the effect lasts, for the board's
    # per-card effect summary: ``"static"`` (a static ability / Aura /
    # Equipment / anthem — lasts while its source stays in play),
    # ``"permanent"`` (counters — RULE 122, they don't wear off on their own),
    # or ``"end_of_turn"`` (a resolved "until end of turn" pump/keyword grant,
    # cleared at cleanup — RULE 514.2).
    obj.static_trace.append(
        {
            "layer": layer,
            "source": label,
            "description": description,
            "power": power,
            "toughness": toughness,
            "duration": duration,
        }
    )


def _battlefield_static_abilities(state: "GameState") -> list[StaticAbility]:
    # RULE 702.26c: a phased-out permanent's static abilities don't apply —
    # `state.permanents()` already excludes it from being a source.
    # RULE 114.4: an emblem's abilities "function in the command zone" —
    # every player's `Player.emblems` is scanned alongside the battlefield
    # so a static emblem ability (e.g. "Creatures you control get +1/+1.")
    # applies exactly like a permanent's own.
    # RULE 901.7/902.4/904.9: the same is true of the casual variants' own
    # command-zone cards — the face-up plane, a Vanguard avatar and any
    # face-up ongoing scheme all have abilities that function from there
    # (`game/variants.py`'s `command_zone_ability_sources`).
    sources: list[Any] = list(state.permanents())
    for player in state.players:
        sources.extend(player.emblems)
    sources.extend(variants.command_zone_ability_sources(state))
    abilities = [
        ab
        for src in sources
        for ab in getattr(src, "static_effects", [])
        if isinstance(ab, StaticAbility)
    ]
    # MEC-55: a nested static granted by "X have '<static ability>'"
    # (Inspiring Leader) — populated per affected battlefield object during
    # `_apply_layer_6_ability`, then an ordinary static source from here on
    # (same layers/timestamp ordering). Empty until layer 6 runs, so
    # `recompute` re-gathers this list after that pass for layers 7+.
    for obj in state.battlefield:
        abilities.extend(
            ab for ab in getattr(obj, "_granted_static_abilities", ())
            if isinstance(ab, StaticAbility)
        )
    # RULE 112.7a's own printed exception — "As long as this card is in
    # your graveyard [and `<condition>`], `<static>`." (Anger/Brawn/Filth/
    # Valor/Wonder-shaped) is one of the rare statics that explicitly
    # functions from a zone other than the battlefield. Scanned separately
    # from `sources` above, and filtered to just the ``from_graveyard``-
    # marked ability, so a graveyard card's *other*, ordinary abilities
    # (which do NOT function there) can't leak through by sharing a source
    # with this one. Re-derived fresh every pass like everything else here:
    # the moment the card leaves the graveyard it's simply not found here
    # again, no separate "un-stamp on leave" bookkeeping needed.
    for player in state.players:
        for obj in player.graveyard:
            for ab in getattr(obj, "static_effects", []):
                if isinstance(ab, StaticAbility) and ab.params.get("from_graveyard"):
                    abilities.append(ab)
    # RULE 112.6 — an Eminence ability ("As long as ~ is in the command zone or on the battlefield, …", The Ur-Sphinx)
    # functions from the command zone; only the ``from_command_zone``-marked ability does, same isolation as above.
    for player in state.players:
        for obj in player.command:
            for ab in getattr(obj, "static_effects", []):
                if isinstance(ab, StaticAbility) and ab.params.get("from_command_zone"):
                    abilities.append(ab)
    # RULE 611: continuous effects created by a *resolving* spell or ability
    # rather than printed on a permanent ("Until your next turn, creatures you
    # control get +1/+1"). They live on the state (`GameState.
    # floating_statics`) because 611.2b makes them independent of their
    # source, but from here on they are ordinary statics — same layers, same
    # timestamp ordering, same dependency pass. `durations.active_statics`
    # drops any whose "for as long as" condition has stopped holding.
    abilities.extend(
        ab for ab in durations.active_statics(state) if isinstance(ab, StaticAbility)
    )
    return abilities


def _in_layer(abilities: list[StaticAbility], layer: str) -> list[StaticAbility]:
    """Abilities in one (sub)layer, ordered by timestamp (RULE 613.7b).

    Within a layer, effects apply in timestamp order (newest last); an
    unsourced fixture ability sorts first (timestamp 0). A true dependency
    pass (RULE 613.8) is still a simplification — timestamps cover the
    overwhelmingly common non-dependent case.

    A bind-time printed static's own `StaticAbility.timestamp` is None, so
    it falls back to its source permanent's own entry timestamp — the
    ordinary case. A resolve-time grant (`effects.GrantUntilEffect`, MEC-43
    round 4E — Swift Reconfiguration's granted Crew ability) stamps its
    *own* timestamp instead, since "when did this continuous effect start
    existing" is whenever it was created, not whenever whatever permanent
    it happens to affect entered the battlefield — those can differ by an
    arbitrary number of other events in between.
    """
    picked = [a for a in abilities if a.layer == layer]
    return sorted(
        picked,
        key=lambda a: a.timestamp if getattr(a, "timestamp", None) is not None
        else getattr(a.source, "timestamp", 0),
    )


#: Colour word → WUBRG letter, for the ``devotion_to_<colour>`` selectors
#: (RULE 202.2f). Colourless has no devotion (a {C} pip is not a colour).
_DEVOTION_COLOURS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

#: The five two-colour "wedge" names a multi-colour devotion clause may
#: print instead of spelling out its colours ("your devotion to Abzan" —
#: Devoted Abzan/Jeskai/Mardu/Sultai/Temur) → their WUBRG letters, for the
#: ``devotion_to_<wedge>`` selector suffix `subgrammars.devotion_selector`
#: produces verbatim (unlike the multi-colour case, which is pre-resolved
#: to sorted letters at parse time since there's no fixed name for it).
_DEVOTION_WEDGES: dict[str, str] = {
    "abzan": "WBG", "jeskai": "URW", "mardu": "RWB", "sultai": "BGU", "temur": "GUR",
}


#: The zones a structured count selector may name, and the `Player` attribute each
#: is read from (a card outside the battlefield is counted by its *owner's* zone).
COUNT_SELECTOR_ZONES: dict[str, str] = {
    "graveyard": "graveyard", "hand": "hand", "exile": "exile", "library": "library",
}
#: What a ``distinct`` selector counts different values of ("creatures with
#: different powers").
_DISTINCT_KEYS: dict[str, Any] = {
    "power": lambda o: o.power, "toughness": lambda o: o.toughness,
    "mana_value": lambda o: o.card.converted_mana_cost, "name": lambda o: o.name,
}

#: The card types of RULE 205.2a an object can carry in a real game ("kindred"
#: and its pre-rename spelling "tribal" included). `GameObject.type_words` also
#: returns supertypes ("legendary", "snow", "basic") and the synthetic
#: "permanent" marker, none of which is a card type — "the number of card types
#: among cards in all graveyards" (Tarmogoyf) must not count them.
CARD_TYPE_WORDS: frozenset[str] = frozenset({
    "artifact", "battle", "creature", "enchantment", "instant", "kindred", "land",
    "planeswalker", "sorcery", "tribal",
})


def card_types_of(obj: "GameObject") -> set[str]:
    """``obj``'s card types (RULE 205.2a), supertypes and "permanent" excluded."""
    return set(getattr(obj, "type_words", None) or ()) & CARD_TYPE_WORDS


#: A ``distinct`` key whose value is a *set* per object — "the number of card
#: types among cards in your graveyard" (Tarmogoyf) and "the number of colors
#: among permanents you control" (Squawkroaster) count the union, since one
#: artifact creature contributes two card types.
_DISTINCT_SET_KEYS: dict[str, Any] = {
    "card_type": card_types_of,
    "color": lambda o: set(getattr(o, "colors", None) or ()),
}

#: What an ``aggregate`` selector measures on each matched object —
#: "the greatest mana value among creatures you control" (Dodgy Jalopy),
#: "the total mana value of other creatures you control" (Ancient Ooze),
#: "the number of +1/+1 counters on lands you control" (Toph; ``counters``
#: reads ``counter_kind``, or every kind when that is absent).
_AGGREGATE_VALUES: dict[str, Any] = {
    "mana_value": lambda o, _k: int(getattr(o.card, "converted_mana_cost", 0) or 0),
    "power": lambda o, _k: int(o.power or 0),
    "toughness": lambda o, _k: int(o.toughness or 0),
    "counters": lambda o, k: (
        int((getattr(o, "counters", None) or {}).get(k, 0) or 0) if k
        else sum(int(v or 0) for v in (getattr(o, "counters", None) or {}).values())
    ),
}


def _structured_selector_objects(
    state: "GameState", controller_id: Optional[str], spec: dict[str, Any],
    source: Optional["GameObject"] = None,
) -> list[Any]:
    """PAR-120: the objects a structured selector describes.

    ``{"zone": "battlefield"|"graveyard"|"hand"|"exile"|"library", "of": "you"|
    "opponents"|"any", "filter": <matches_object_filter dict>}`` — one
    representation for "creatures you control", "creature cards in your
    graveyard", "lands your opponents control", "cards in your hand", read
    through the same filter every trigger head and target phrase uses,
    instead of one named branch per phrase. ``of`` is relative to
    ``controller_id`` ("you" is that player; a battlefield object is picked
    by its *controller*, a card in another zone by its *owner*). Shared by
    `_count_structured` (which additionally counts/distinct-counts the
    result) and `group_selector_objects` (PARSER_VERSION 473 — the same
    selector shape naming an actual *group* to iterate over or apply a
    static/one-shot effect to, not just a number).
    """
    from .combat import matches_object_filter  # local: combat imports models lazily too

    if controller_id is None:
        return []
    scope = spec.get("of", "you")
    players = [
        p for p in state.players
        if scope == "any"
        or (scope == "you" and p.id == controller_id)
        or (scope == "opponents" and p.id != controller_id)
        or (scope == "chosen" and source is not None
            and p.id == getattr(source, "chosen_player_id", None))
        # "…for each tapped creature **its controller** controls" (Observed Stasis) — the controller of the
        # permanent this Aura/Equipment is attached to.
        or (scope == "attached_controller" and source is not None
            and p.id == getattr(state.find_object(getattr(source, "attached_to", None)), "controller_id", None))
    ]
    zone = spec.get("zone", "battlefield")
    filt = spec.get("filter") or None
    matched: list[Any] = []
    for player in players:
        if zone == "battlefield":
            candidates = state.permanents_controlled_by(player.id)
        elif zone in COUNT_SELECTOR_ZONES:
            candidates = list(getattr(player, COUNT_SELECTOR_ZONES[zone]))
        else:
            return []
        matched.extend(
            o for o in candidates if matches_object_filter(o, filt, reference=source, state=state)
        )
    return matched


def _count_structured(
    state: "GameState", controller_id: Optional[str], spec: dict[str, Any],
    source: Optional["GameObject"] = None,
) -> int:
    """PAR-120: count the objects a structured selector describes — see
    `_structured_selector_objects`. ``distinct`` counts different values
    instead of objects.
    """
    matched = _structured_selector_objects(state, controller_id, spec, source)
    distinct = spec.get("distinct")
    if distinct is not None:
        set_getter = _DISTINCT_SET_KEYS.get(distinct)
        if set_getter is not None:
            values: set[Any] = set()
            for o in matched:
                values |= set_getter(o)
            return len(values)
        getter = _DISTINCT_KEYS.get(distinct)
        return len({getter(o) for o in matched}) if getter else 0
    aggregate = spec.get("aggregate")
    if aggregate is not None:
        if spec.get("value") == "mana_symbols":
            from ..models.mana.mana_cost import ManaCost  # function-scoped model import

            colour = spec.get("color")
            return sum(
                1 for obj in matched
                for symbol in ManaCost.parse(obj.card.mana_cost_string).symbols
                if colour in symbol.colors
            )
        measure = _AGGREGATE_VALUES.get(spec.get("value", ""))
        if measure is None:
            return 0
        values_list = [measure(o, spec.get("counter_kind")) for o in matched]
        if aggregate == "max":
            return max(values_list, default=0)  # an empty group's greatest value is 0
        if aggregate == "sum":
            return sum(values_list)
        return 0
    return len(matched)


def _count_expression(
    state: "GameState", controller_id: Optional[str], spec: dict[str, Any],
    source: Optional["GameObject"] = None,
) -> int:
    """PAR-120: arithmetic over count selectors — ``{"terms": [<selector>, …],
    "times": k, "plus": n}`` is ``k × Σ terms + n``. "1 plus twice the number
    of age counters on it" (Mwonvuli Ooze), "the number of Forests you control
    plus the number of Treefolk you control" (Dauntless Dourbark), and a
    Lhurgoyf's toughness, "that number plus 1". A term is any selector
    `count_selector` accepts, named or structured."""
    total = sum(count_selector(state, controller_id, term, source) for term in spec.get("terms", ()))
    return total * int(spec.get("times", 1)) + int(spec.get("plus", 0))


def _counters_on_source(spec: dict[str, Any], source: Optional["GameObject"]) -> int:
    """``{"counters_on": "source", "kind": <kind>}`` — "the number of fade
    counters on it" (Rusting Golem): read straight off the source object's own
    counters (RULE 122.1; they aren't a continuous effect). Every kind is
    summed when ``kind`` is absent; ``0`` without a source."""
    if source is None:
        return 0
    counters = getattr(source, "counters", None) or {}
    kind = spec.get("kind")
    if kind:
        return int(counters.get(kind, 0) or 0)
    return sum(int(v or 0) for v in counters.values())


def is_modified(state: "GameState", obj: "GameObject") -> bool:
    """RULE 700.9: a permanent is modified if it has a counter on it, is
    equipped, or is enchanted by an Aura its own controller controls.

    Equipment counts whoever controls it (RULE 301.5 — "equipped" is just
    "has an Equipment attached"); only an Aura has to share the permanent's
    controller. Used by the ``modified`` object-filter key and the
    ``modified_creatures_you_control`` count selector, so the two can't drift.
    """
    if any(int(v or 0) > 0 for v in (getattr(obj, "counters", None) or {}).values()):
        return True
    if getattr(obj, "plus_one_counters", 0):
        return True
    for attachment in state.battlefield:
        if getattr(attachment, "attached_to", None) != obj.instance_id:
            continue
        if _has_subtype(attachment, "equipment"):
            return True
        if _has_subtype(attachment, "aura") and attachment.controller_id == obj.controller_id:
            return True
    return False


def count_selector(
    state: "GameState",
    controller_id: Optional[str],
    selector: "str | dict[str, Any]",
    source: Optional["GameObject"] = None,
) -> int:
    """Evaluate a "number of X" count selector, scoped to ``controller_id``.

    ``selector`` is a *named* selector (the string vocabulary below) or, since
    PAR-120, a structured ``{"zone", "of", "filter"}`` dict (`_count_structured`),
    an arithmetic ``{"terms", "times", "plus"}`` expression over selectors
    (`_count_expression`), or ``{"counters_on": "source"}`` (`_counters_on_source`).

    The vocabulary a layer-7a characteristic-defining P/T (RULE 613.7c/604.3
    — a ``*/*`` creature like Nightmare's Swamps, a graveyard-count beater)
    is defined by; also reused by a ward cost's own "where X is …"
    definition (RULE 702.21b, `costs.ActivationCost.x_selector`) — one
    authored list rather than two. "you control"/"your graveyard" is scoped
    to ``controller_id``; ``None`` (no controller context) matches nothing.

    ``source`` is the object the selector is being evaluated *for*, needed
    only by the self-referential entries ("cards named ~", Rite of Flame) —
    every other selector answers purely from ``state``/``controller_id``, so
    callers without a source in hand can keep omitting it.
    """
    if isinstance(selector, dict):
        if "terms" in selector:
            return _count_expression(state, controller_id, selector, source)
        if selector.get("counters_on") == "source":
            return _counters_on_source(selector, source)
        return _count_structured(state, controller_id, selector, source)
    bf = state.battlefield
    _source_card_name = getattr(source, "name", None)
    if selector == "creatures_in_your_party":
        # RULE 700.8: a party has at most one Cleric, Rogue, Warrior and
        # Wizard. A creature with several of those subtypes can fill only one
        # role, so this is a small bipartite matching rather than four
        # independent presence tests.
        if controller_id is None:
            return 0
        roles = ("cleric", "rogue", "warrior", "wizard")
        candidates = [
            {role for role in roles if _has_subtype(obj, role)}
            for obj in bf if obj.is_creature and obj.controller_id == controller_id
        ]
        assigned: dict[str, int] = {}
        def _assign(index: int, seen: set[str]) -> bool:
            for role in candidates[index]:
                if role in seen:
                    continue
                seen.add(role)
                previous = assigned.get(role)
                if previous is None or _assign(previous, seen):
                    assigned[role] = index
                    return True
            return False
        # At four roles, trying each creature against the currently free
        # roles is sufficient for the bounded quantity this selector returns.
        for index in range(len(candidates)):
            _assign(index, set())
        return len(assigned)
    if selector == "all_creatures":
        # Chain Reaction — an unscoped count, unlike the controller-relative
        # creature selectors below (RULE 107.3 / 608.2h).
        return sum(1 for obj in bf if obj.is_creature)
    if selector == "exiled_with_count":
        # "Create a token for each permanent exiled this way." (MEC-12,
        # Abdel Adrian, Gorion's Ward) — "that many" always refers back to
        # ``source``'s own `GameObject.exiled_with_ids` (MEC-21's
        # accumulating tracker), not a board count at all; ``source`` must
        # be given (a bare test fixture omitting it gets 0, the same safe
        # fallback every self-referential selector here gets).
        return len(getattr(source, "exiled_with_ids", None) or [])
    if selector == "revealed_with_count":
        # "Reveal any number of green cards in your hand. …, where X is the
        # number of cards revealed this way." (Ivy Seer, Scent of Ivy,
        # PAR-80) — the reveal-choice sibling of `exiled_with_count` above,
        # reading `GameObject.revealed_with_ids` (populated by
        # `RevealAnyNumberHandCardsEffect`'s ``"reveal"`` chooser action)
        # instead of `exiled_with_ids`.
        return len(getattr(source, "revealed_with_ids", None) or [])
    if selector == "source_x_paid":
        # "When this creature enters, incubate 3 **X times**." (Progenitor
        # Exarch) — the repeat count is the source permanent's own announced
        # {X} (`GameObject.x_paid`, RULE 107.3c, set at cast time), not a
        # board count. ``source`` required; a fixture without one gets 0,
        # the same safe fallback `exiled_with_count` above takes.
        return int(getattr(source, "x_paid", 0) or 0)
    if selector == "source_power":
        # "…gets +X/+X …, where X is ~'s power." (Hardy Outlander's granted
        # attack trigger, PAR-32) — the source's own *derived* power (RULE
        # 613), the amount sibling of `dynamic_threshold`'s identically-
        # named comparison branch. ``source`` required.
        return int(getattr(source, "power", 0) or 0) if source is not None else 0
    if selector == "source_toughness":
        return int(getattr(source, "toughness", 0) or 0) if source is not None else 0
    if selector == "plus_one_counters_on_source":
        # "…create a token for each +1/+1 counter on ~." (Mycoloth,
        # Ribtruss Roaster, PAR-60) — the `+1/+1`-kind sibling of
        # ``charge_counters_on_source`` below.
        return int(getattr(source, "plus_one_counters", 0) or 0) if source is not None else 0
    if selector == "study_counters_on_source":
        # "…equal to the number of study counters on ~." (Lattice Library,
        # PAR-60) — the "study"-kind sibling of ``charge_counters_on_source``.
        return int((getattr(source, "counters", None) or {}).get("study", 0)) if source is not None else 0
    if selector == "charge_counters_on_source":
        # "…where X is the number of charge counters on this artifact."
        # (Wickersmith's Tools) — read straight off ``source.counters``
        # (counters aren't a continuous effect); ``0`` without a source.
        return int((getattr(source, "counters", None) or {}).get("charge", 0)) if source is not None else 0
    if selector == "converge":
        # RULE 702.108a Converge — "where X is the number of colors of mana
        # spent to cast this spell." (Painful Truths). The mana-payment
        # solver stamps `GameObject.colors_spent_to_cast` (a WUBRG
        # frozenset) on the spell at cast; ``0`` without a source.
        return len(getattr(source, "colors_spent_to_cast", None) or ()) if source is not None else 0
    if selector == "sacrificed_cost_mana_value":
        # "…target player mills cards equal to the sacrificed creature's
        # mana value." (MEC-43) — reads `GameObject.sacrificed_cost_mana_
        # value`, stamped fresh by whatever cost payment just sacrificed
        # something for ``source``; ``0`` (not ``None``) when nothing was
        # sacrificed, the same safe self-referential fallback every other
        # entry here gets.
        return int(getattr(source, "sacrificed_cost_mana_value", None) or 0)
    if selector == "sacrificed_cost_power":
        # The power sibling (Altar of Dementia) of the entry just above.
        return int(getattr(source, "sacrificed_cost_power", None) or 0)
    if selector == "sacrificed_cost_toughness":
        return int(getattr(source, "sacrificed_cost_toughness", None) or 0)
    if selector == "station_tapped_power":
        # RULE 702.184a Station: "Put a number of charge counters on this
        # permanent equal to the tapped creature's power." — reads
        # `GameObject.station_tapped_power`, stamped fresh by whatever
        # `station` cost payment just tapped a creature for ``source``;
        # ``0`` for the same safe self-referential fallback every other
        # entry here gets.
        return int(getattr(source, "station_tapped_power", None) or 0)
    if selector == "snow_mana_spent_to_cast":
        # "You gain 1 life for each {S} spent to cast this spell." (Search
        # for Glory, MEC-43 round 3) — `GameObject.mana_spent_to_cast_snow`,
        # stamped by `RulesEngine.cast_spell`'s own before/after diff of
        # `ManaPool.snow_pool` (the same idiom `colors_spent_to_cast`/
        # Converge already uses for *which colors* paid a cost, just
        # snow-tagged instead of color-tagged); ``0`` for the same
        # self-referential fallback every other entry here gets.
        return int(getattr(source, "mana_spent_to_cast_snow", None) or 0)
    if selector == "spells_cast_this_turn":
        # "…costs {1} more to cast for each other spell that player has
        # cast this turn." (MEC-36, Damping Sphere) — `_cost_static_amount`
        # passes the *casting* player as ``controller_id`` here (not this
        # static's own owner), and `RulesEngine._track_spell_cast`
        # increments `GameState.spells_cast_this_turn` strictly *after*
        # the spell's own cost is computed, so this already reads "every
        # **other** spell cast this turn" with no off-by-one to correct.
        if controller_id is None:
            return 0
        return state.spells_cast_this_turn.get(controller_id, 0)
    if selector == "greatest_instant_sorcery_mv_this_turn":
        # "…where X is the greatest mana value among instant and sorcery
        # spells you've cast this turn." (Rootha, Mastering the Moment,
        # PAR-60) — a running max maintained by `_track_spell_cast`.
        if controller_id is None:
            return 0
        return int(getattr(state, "greatest_instant_sorcery_mv_this_turn", {}).get(controller_id, 0))
    if selector == "cards_discarded_this_turn":
        # "…for each card you've discarded this turn." (Living Laser's
        # self-copy count; Change of Fortune / Astonishing Spider-Man's
        # "draw a card for each card you've discarded this turn") —
        # `GameState.cards_discarded_this_turn`, bumped at every
        # `DISCARD_CARD` fire site (`RulesEngine._note_discarded`).
        if controller_id is None:
            return 0
        return state.cards_discarded_this_turn.get(controller_id, 0)
    if selector == "cards_put_into_graveyard_from_hand_or_library_this_turn":
        # "…the number of cards that were put into your graveyard from your hand or library this turn."
        # (Welcome the Dead) — `GameState`'s PUT_INTO_GRAVEYARD arrivals read through `turn_history`.
        if controller_id is None:
            return 0
        return state.cards_put_into_graveyard_from_hand_or_library_this_turn.get(controller_id, 0)
    if selector == "nontoken_creatures_you_entered_this_turn":
        # "…equal to the number of nontoken creatures you had enter the
        # battlefield under your control this turn." (Gyome, Master Chef,
        # PAR-60) — `GameState.nontoken_creatures_entered_this_turn`.
        if controller_id is None:
            return 0
        entered = getattr(state, "nontoken_creatures_entered_this_turn", None) or {}
        return int(entered.get(controller_id, 0) or 0)
    if selector == "tokens_you_created_this_turn":
        # "…where X is the number of tokens you created this turn." (Thalisse, Reverent Medium) — a
        # token's creation is its entry (`turn_history.tokens_entered`), counted per controller.
        if controller_id is None:
            return 0
        from ..models.game import turn_history

        return int(turn_history.tokens_entered(state.events_this_turn()).get(controller_id, 0) or 0)
    if selector == "creatures_that_left_battlefield_this_turn":
        # MEC-84 — "…for each creature that left the battlefield under your
        # control this turn." (Kutzil's Flanker). `GameState.creatures_left_
        # battlefield_this_turn`, incremented at the `remove_from_battlefield`
        # chokepoint, reset per turn.
        if controller_id is None:
            return 0
        left = getattr(state, "creatures_left_battlefield_this_turn", None) or {}
        return int(left.get(controller_id, 0) or 0)
    if selector == "life_lost_this_turn":
        # "…where X is the amount of life you lost this turn." (Rowan, Scion
        # of War) — derived from this turn's events (RULE 119.3).
        if controller_id is None:
            return 0
        lost = getattr(state, "life_lost_this_turn", None) or {}
        return int(lost.get(controller_id, 0) or 0)
    if selector == "opponents_life_lost_this_turn":
        # "…where X is the total amount of life your opponents lost this turn." (Florian, Voldaren Scion; Rakdos, Lord of
        # Riots' "for each 1 life your opponents have lost this turn") — RULE 119.3, summed over every opponent.
        if controller_id is None:
            return 0
        lost = getattr(state, "life_lost_this_turn", None) or {}
        return sum(int(lost.get(p.id, 0) or 0) for p in state.players if p.id != controller_id)
    if selector == "players_who_lost_life_this_turn":
        # "…for each player who lost life this turn." (Reaper's Scythe) — event-derived (`life_lost_this_turn`).
        lost = getattr(state, "life_lost_this_turn", None) or {}
        return sum(1 for p in state.living_players() if int(lost.get(p.id, 0) or 0) > 0)
    if selector == "life_gained_this_turn":
        # "…where X is the amount of life you gained this turn." (Defiling
        # Daemogoth, Blossoming Bogbeast, PAR-60) — `GameState.
        # life_gained_this_turn`, bumped at `RulesEngine.gain_life`'s choke
        # point, reset per turn.
        if controller_id is None:
            return 0
        gained = getattr(state, "life_gained_this_turn", None) or {}
        return int(gained.get(controller_id, 0) or 0)
    if selector == "opponents_dealt_combat_damage_this_turn":
        # "...where X is the number of opponents that were dealt combat
        # damage this turn." (Tymna the Weaver, MEC-42) — unlike `GameState.
        # combat_damage_to_players_this_turn`'s own keyed-by-source shape
        # (built for "player damaged **by ~**"), this reads it unscoped by
        # source: any opponent hit by *any* creature this turn counts,
        # regardless of who controlled the attacker.
        if controller_id is None:
            return 0
        opponent_ids = {p.id for p in state.living_players() if p.id != controller_id}
        hit: set[str] = set()
        for victims in state.combat_damage_to_players_this_turn.values():
            hit |= victims
        return len(hit & opponent_ids)
    if selector.startswith("opponents_dealt_combat_damage_by_self_or_") and selector.endswith("_this_turn"):
        # "…where X is the number of your opponents who were dealt combat damage by ~ or a Dragon this turn."
        # (Estinien Varlineau) — `opponents_dealt_combat_damage_this_turn` narrowed to dealers that are the source
        # itself or a creature of the named subtype (read in any zone: the dealer may have died, RULE 400.7).
        if controller_id is None:
            return 0
        wanted = selector[len("opponents_dealt_combat_damage_by_self_or_"):-len("_this_turn")].lower()
        opponent_ids = {p.id for p in state.living_players() if p.id != controller_id}
        hit: set[str] = set()
        for dealer_id, victims in state.combat_damage_to_players_this_turn.items():
            dealer = state.find_object(dealer_id)
            if dealer is None:
                continue
            if dealer is source or wanted in {w.lower() for w in derived_subtype_words(dealer)} \
                    or wanted in dealer.card.type_line.lower().partition("—")[2].split():
                hit |= victims
        return len(hit & opponent_ids)
    if selector == "noncombat_damage_to_opponents_this_turn":
        # "This spell costs {X} less to cast, where X is the total amount
        # of noncombat damage dealt to your opponents this turn." (Chandra's
        # Incinerator, MEC-45) — unlike `opponents_dealt_combat_damage_this_
        # turn` above (a per-source *hit-set*, since RULE 120.3 only ever
        # asks "was this player hit", never "how much"), this is a running
        # *amount* summed per dealing player — `RulesEngine.deal_damage`
        # increments it directly, so no union/re-derivation is needed here.
        if controller_id is None:
            return 0
        return state.noncombat_damage_to_opponents_this_turn.get(controller_id, 0)
    if selector == "nonartifact_spells_cast_this_turn":
        # "Each player who has cast a nonartifact spell this turn can't
        # cast additional nonartifact spells." (Ethersworn Canonist,
        # MEC-43) — the nonartifact sibling of `noncreature_spells_cast_
        # this_turn`, read by `cast_prohibited`'s own ``min_count_selector``
        # gate rather than any cost-reduction `per`.
        if controller_id is None:
            return 0
        return state.nonartifact_spells_cast_this_turn.get(controller_id, 0)
    if selector == "instant_and_sorcery_spells_cast_this_turn":
        # "You've cast four or more instant and sorcery spells this turn."
        # (Case of the Ransacked Lab's "To solve") — `turn_history`'s own
        # ``"instant_or_sorcery"`` tally, read like its siblings above.
        if controller_id is None:
            return 0
        counts = state.spell_type_cast_counts_this_turn.get(controller_id, {})
        return counts.get("instant_or_sorcery", 0)
    if selector == "colors_among_permanents_you_control":
        # "…gets +1/+1 for each color among permanents you control."
        # (MEC-43 round 2, Conqueror's Flail/Faeburrow Elder) — the P/T-
        # anthem sibling of `ManaAbility.color_selector`'s own same-named
        # entry (ENG-27, Bloom Tender): count, don't enumerate, since a
        # `count_selector` answers "how many", not "which".
        if controller_id is None:
            return 0
        colors_present: set[str] = set()
        for permanent in bf:
            if permanent.controller_id == controller_id:
                colors_present |= (permanent.colors or set())
        return len(colors_present)
    if selector == "colors_among_other_legendary_permanents_you_control":
        # "…for each color among **other legendary** permanents you control." (Sisay, Weatherlight
        # Captain) — `colors_among_permanents_you_control` above, minus ``source`` itself (RULE
        # 109.5 "other") and restricted to legendary permanents.
        if controller_id is None:
            return 0
        legendary_colors: set[str] = set()
        for permanent in bf:
            if (
                permanent.controller_id == controller_id and permanent is not source
                and getattr(permanent.card, "is_legendary", False)
            ):
                legendary_colors |= (permanent.colors or set())
        return len(legendary_colors)
    if selector == "basic_land_types_among_lands_you_control":
        # Collective Restraint — RULE 305.6's five basic land types count
        # once each, even if several lands share one type or one land has
        # several (for example, a Forest Plains).
        if controller_id is None:
            return 0
        present: set[str] = set()
        for permanent in bf:
            if permanent.is_land and permanent.controller_id == controller_id:
                present.update(
                    land_type for land_type in _BASIC_LAND_TYPES
                    if _has_subtype(permanent, land_type)
                )
        return len(present)
    if selector == "your_life_total":
        if controller_id is None:
            return 0
        player = state.player_by_id(controller_id)
        return player.life if player is not None else 0
    if selector == "unspent_mana_you_have":
        # "…for each unspent mana you have." (Omnath, Locus of the Void) — every mana in the pool, restricted lots included.
        player = state.player_by_id(controller_id) if controller_id is not None else None
        return player.mana_pool.total() if player is not None else 0
    if selector == "cards_in_your_hand":
        # "…where X is the number of cards in your hand." (Baldin, Century Herdmaster)
        player = state.player_by_id(controller_id) if controller_id is not None else None
        return len(player.hand) if player is not None else 0
    if selector == "total_toughness_other_creatures_you_control":
        # "…where X is the total toughness of other creatures you control." (Towering Titan) — read as it
        # enters, so ``source`` is not yet on the battlefield and "other" is free; excluded anyway for a live read.
        return sum(
            max(0, int(o.toughness or 0)) for o in bf
            if o.is_creature and o.controller_id == controller_id and o is not source
        )
    if selector == "opponents_controlling_more_creatures":
        # "…the number of opponents who control more creatures than you." (Heidegger, Shinra Executive)
        mine = sum(1 for o in bf if o.is_creature and o.controller_id == controller_id)
        return sum(
            1 for p in state.living_players()
            if p.id != controller_id and sum(1 for o in bf if o.is_creature and o.controller_id == p.id) > mine
        )
    if selector == "opponents_controlling_creature_power_4_or_greater":
        # "…the number of opponents who control a creature with power 4 or greater." (Summon: Yojimbo IV)
        return sum(
            1 for p in state.living_players()
            if p.id != controller_id and any(
                o.is_creature and o.controller_id == p.id and (o.power or 0) >= 4 for o in bf
            )
        )
    if selector == "opponents_with_more_cards_in_hand":
        # "…once for each opponent who has more cards in hand than you." (Wojek Investigator) — a count of
        # players, not objects: every other living player whose hand is larger than ``controller_id``'s.
        if controller_id is None:
            return 0
        mine = state.player_by_id(controller_id)
        if mine is None:
            return 0
        return sum(
            1 for p in state.players
            if p.id != controller_id and not p.has_lost and len(p.hand) > len(mine.hand)
        )
    if selector == "creatures_you_control":
        return sum(1 for o in bf if o.is_creature and o.controller_id == controller_id)
    if selector.startswith("greatest_") and selector.endswith("_you_control") and "_among_" in selector:
        # PAR-80 second increment: "target creature gets +X/+X until end of
        # turn, where X is the greatest mana value among permanents you
        # control." (Accelerated Mutation, Boon of Boseiju) / "…greatest
        # power among creatures you control." (Oaken Power Suit) — one
        # shared reader for the whole "greatest <metric> among <scope> you
        # control" family instead of a hand-rolled loop per phrase (the
        # shape `greatest_non_human_creature_power_you_control` below
        # would otherwise have grown a third near-duplicate of).
        metric_name, _, scope_name = selector[len("greatest_"):-len("_you_control")].partition("_among_")
        metric = {
            "mana_value": lambda o: int(getattr(o.card, "converted_mana_cost", 0) or 0),
            "power": lambda o: int(o.power or 0),
        }.get(metric_name)
        in_scope = {
            "permanents": lambda o: True,
            "creatures": lambda o: o.is_creature,
            "artifacts": lambda o: bool(o.card.is_artifact),
        }.get(scope_name)
        if metric is None or in_scope is None:
            return 0
        eligible = [metric(o) for o in bf if o.controller_id == controller_id and in_scope(o)]
        return max(eligible, default=0)
    if selector == "greatest_non_human_creature_power_you_control":
        # Return of the Wildspeaker: this is a magnitude, not a target
        # restriction. Derived power is read live at resolution (RULE 613),
        # and an empty eligible set has greatest value zero.
        eligible = [
            int(o.power or 0) for o in bf
            if o.is_creature and o.controller_id == controller_id
            and not _has_subtype(o, "human")
        ]
        return max(eligible, default=0)
    if selector == "greatest_toughness_you_control":
        # "Draw cards equal to the greatest toughness among creatures you
        # control." (Last March of the Ents) — the toughness sibling of
        # `greatest_non_human_creature_power_you_control` above, with no
        # subtype filter; derived toughness is read live (RULE 613) and an
        # empty board has greatest value zero.
        return max(
            (int(o.toughness or 0) for o in bf if o.is_creature and o.controller_id == controller_id),
            default=0,
        )
    if selector == "multicolored_permanents_you_control":
        # "…if an opponent controls a multicolored permanent." (Ghostfire
        # Slice's own `active_if`, read via `opponent_count`'s per-opponent
        # scoping) — `GameObject.colors` is the layer-5 derived colour set,
        # same field `cost_reduction_for`'s own colour filter already reads.
        return sum(1 for o in bf if o.controller_id == controller_id and len(o.colors or ()) >= 2)
    if selector == "creatures_on_battlefield":
        # "This spell costs {1} less to cast for each creature on the
        # battlefield." (Blasphemous Act) — every creature regardless of
        # controller, the unscoped sibling of `creatures_you_control`.
        return sum(1 for o in bf if o.is_creature)
    if selector == "instant_sorcery_or_adventure_cards_in_your_graveyard":
        # "the number of cards in your graveyard that are instant cards,
        # sorcery cards, and/or have an Adventure." (Frantic Firebolt) —
        # RULE 715's Adventure card is itself an instant/sorcery half of a
        # creature card, so "has an Adventure" only ever adds creature
        # cards printing one to the instant-or-sorcery count above.
        if controller_id is None:
            return 0
        try:
            graveyard = state.player_by_id(controller_id).graveyard
        except (KeyError, ValueError):
            return 0
        return sum(
            1 for o in graveyard
            if o.card.is_instant or o.card.is_sorcery
            or "adventure" in (o.card.type_line or "").lower()
        )
    if selector == "instant_or_sorcery_cards_in_your_graveyard":
        # "This spell costs {1} less to cast for each instant and sorcery
        # card in your graveyard." (Cryptic Serpent / Tolarian Terror /
        # Furygale Flocking) — the plain instant-OR-sorcery count, without
        # the Adventure union `instant_sorcery_or_adventure_…` above adds.
        if controller_id is None:
            return 0
        try:
            graveyard = state.player_by_id(controller_id).graveyard
        except (KeyError, ValueError):
            return 0
        return sum(1 for o in graveyard if o.card.is_instant or o.card.is_sorcery)
    if selector == "tapped_lands_opponents_control":
        # "Add {R} for each tapped land your opponents control." (Mana
        # Geyser) — every opponent's tapped land, unioned rather than
        # scoped to any one of them (there's no single "the opponent" in
        # a multiplayer game).
        if controller_id is None:
            return 0
        return sum(
            1 for o in bf
            if o.is_land and o.tapped and o.controller_id is not None and o.controller_id != controller_id
        )
    if selector.startswith("permanents_opponents_control_of_color_"):
        # "for each black permanent your opponents control" — a general
        # colour-filtered opponent count, evaluated from final layer-5
        # colours so colour-changing effects are respected.
        color = selector.removeprefix("permanents_opponents_control_of_color_").upper()
        if color not in {"W", "U", "B", "R", "G"}:
            return 0
        return sum(
            1 for o in bf
            if o.controller_id not in (None, controller_id) and color in (o.colors or set())
        )
    if selector == "tapped_creatures_you_control":
        # "…each opponent loses life equal to the number of tapped
        # creatures you control." (Throne of the God-Pharaoh) — a plain
        # board count, unrelated to attacking/blocking status.
        return sum(1 for o in bf if o.is_creature and o.tapped and o.controller_id == controller_id)
    if selector.startswith("tapped_") and selector.endswith("_you_control"):
        # "the number of tapped `<type>`[ and/or `<type>`] you control"
        # (MEC-27's own qualifier grammar — Aang and Katara/Alibou, Ancient
        # Witness/Lydia Frye), the tapped sibling of the bare/subtype
        # selectors above: each ``and/or``-joined part is either one of the
        # bare category words those selectors already use, or (`"type_…"`)
        # a creature subtype, matched with the same `_has_subtype` helper.
        parts = selector[len("tapped_"):-len("_you_control")].split("_and_or_")

        def _tapped_matches(o: "GameObject", part: str) -> bool:
            if part == "creatures":
                return o.is_creature
            if part == "artifacts":
                return o.card.is_artifact
            if part == "lands":
                return o.is_land
            if part == "enchantments":
                return o.card.is_enchantment
            if part == "planeswalkers":
                return o.is_planeswalker
            if part == "permanents":
                return True
            if part.startswith("type_"):
                return _has_subtype(o, part[len("type_"):])
            return False

        return sum(
            1 for o in bf
            if o.tapped and o.controller_id == controller_id and any(_tapped_matches(o, p) for p in parts)
        )
    if selector.startswith("creatures_you_control_with_power_"):
        # "the number of creatures you control with power N or less/
        # greater" (MEC-27's own qualifier grammar — Arabella, Abandoned
        # Doll/Dragonhawk, Fate's Tempest/The Boulder, Ready to Rumble) —
        # `GameObject.power` is the layer-engine-derived value, same as
        # every other live board-count selector here.
        op, _, n_str = selector[len("creatures_you_control_with_power_"):].partition("_")
        n = int(n_str)
        if op == "le":
            return sum(
                1 for o in bf
                if o.is_creature and o.controller_id == controller_id and o.power is not None and o.power <= n
            )
        if op == "ge":
            return sum(
                1 for o in bf
                if o.is_creature and o.controller_id == controller_id and o.power is not None and o.power >= n
            )
        return 0
    if selector == "attacking_creatures_you_control":
        # "for each attacking creature you control" (Embercleave's own
        # self-cost-reduction, MEC-6) — read live off `GameObject.attacking`
        # (RULE 508.1), so casting after declare attackers sees the real
        # count; before that step it's simply 0, same as any other
        # `self_cost_reduction_for` count read at cast time.
        return sum(1 for o in bf if o.is_creature and o.attacking and o.controller_id == controller_id)
    if selector == "creatures_attacking_you":
        # "…where X is the number of creatures attacking you." (Arachnogenesis) — attackers whose declared
        # defender is this player (planeswalkers/battles they protect don't count: RULE 506.2 "attacking you").
        return sum(
            1 for o in bf
            if o.is_creature and o.attacking
            and (o.combat_defender or {}).get("kind") == "player" and (o.combat_defender or {}).get("id") == controller_id
        )
    if selector == "attacking_creatures":
        # The unscoped sibling — "for each attacking creature" with no "you
        # control" (Ancient Stone Idol/Static Snare/Stone Idol Trap) — every
        # attacker regardless of whose.
        return sum(1 for o in bf if o.is_creature and o.attacking)
    if selector == "lands_you_control":
        return sum(1 for o in bf if o.is_land and o.controller_id == controller_id)
    if selector.startswith("attacking_creatures_you_control_of_type_"):
        # "you gain 1 life for each attacking Elf you control" (Dwynen,
        # Gilt-Leaf Daen) — `attacking_creatures_you_control` narrowed by a
        # creature-subtype, same split `creatures_you_control_of_type_`
        # below is to the unattacking `creatures_you_control`.
        creature_type = selector[len("attacking_creatures_you_control_of_type_"):]
        return sum(
            1 for o in bf
            if o.is_creature and o.attacking and o.controller_id == controller_id
            and _has_subtype(o, creature_type)
        )
    if selector.startswith("creatures_of_type_"):
        # "…add an additional {G} for each Elf **on the battlefield**."
        # (Elvish Guidance) — the unscoped sibling of
        # `creatures_you_control_of_type_`: every matching creature
        # regardless of controller, the same scoping `attacking_creatures`
        # is to `attacking_creatures_you_control`.
        creature_type = selector[len("creatures_of_type_"):]
        return sum(1 for o in bf if o.is_creature and _has_subtype(o, creature_type))
    if selector.startswith("creatures_you_control_of_type_"):
        # "X is the number of Halflings you control" (Farmer Cotton) — the
        # creature-subtype sibling of the land-subtype selector just below,
        # same "you control" scoping.
        creature_type = selector[len("creatures_you_control_of_type_"):]
        return sum(
            1 for o in bf
            if o.is_creature and o.controller_id == controller_id and _has_subtype(o, creature_type)
        )
    if selector.startswith("planeswalkers_you_control_of_type_"):
        # "as long as you control a Lukka planeswalker" (Lukka, Coppercoat
        # Outcast's own granted cast permission) — the planeswalker-subtype
        # sibling of `creatures_you_control_of_type_` just above.
        planeswalker_type = selector[len("planeswalkers_you_control_of_type_"):]
        return sum(
            1 for o in bf
            if o.is_planeswalker and o.controller_id == controller_id
            and _has_subtype(o, planeswalker_type)
        )
    if selector.startswith("permanents_you_control_of_type_"):
        # "X is the number of Bobbleheads you control as you activate this
        # ability" (Agility Bobblehead) — the subtype-of-any-permanent sibling
        # of `creatures_you_control_of_type_`, for a subtype (Bobblehead,
        # Equipment, Vehicle, …) that isn't a creature type.
        permanent_type = selector[len("permanents_you_control_of_type_"):]
        return sum(
            1 for o in bf
            if o.controller_id == controller_id and _has_subtype(o, permanent_type)
        )
    if selector == "foods_you_control":
        # "…for each Food you control." (Of Herbs and Stewed Rabbit's own
        # Saga chapter III) — same closed Food/Clue/Treasure named-token
        # vocabulary `_NAMED_TOKEN_WORDS`/`_SACRIFICE_TYPE_TRIGGER_RE`
        # already trust.
        return sum(
            1 for o in bf
            if o.controller_id == controller_id and _has_subtype(o, "food")
        )
    if selector == "treasures_you_control":
        return sum(
            1 for o in bf
            if o.controller_id == controller_id and _has_subtype(o, "treasure")
        )
    if selector.startswith("lands_you_control_of_type_"):
        # "the number of Islands you control" (Kraken of the Straits'
        # `combat.matches_object_filter`'s ``power_lt_count_selector`` —
        # a dynamic threshold, not a literal int) — one basic land type,
        # scoped to ``controller_id`` like every "you control" selector above.
        land_type = selector[len("lands_you_control_of_type_"):]
        return sum(
            1 for o in bf
            if o.is_land and o.controller_id == controller_id and _has_subtype(o, land_type)
        )
    if selector == "permanents_you_control":
        return sum(1 for o in bf if o.controller_id == controller_id)
    if selector == "nonland_permanents_you_control":
        return sum(1 for o in bf if o.controller_id == controller_id and not o.is_land)
    if selector.startswith("source_") and selector.endswith("_counters") and source is not None:
        # "X is the number of arrow counters on this creature." (Archery
        # Training) — a live count on the effect source, rather than a board
        # count owned by its controller.
        kind = selector[len("source_"):-len("_counters")]
        return int((getattr(source, "counters", None) or {}).get(kind, 0) or 0)
    if selector == "legendary_creatures_you_control":
        # "for each legendary creature you control" (Eiganjo, Seat of the
        # Empire's Channel cost reduction) — RULE 205.4a's supertype, read
        # off the printed type line the same way `_is_nonbasic` reads
        # "basic".
        return sum(
            1 for o in bf
            if o.is_creature and o.controller_id == controller_id
            and "legendary" in o.card.type_line.lower()
        )
    if selector == "legendary_creatures_and_planeswalkers_you_control":
        return sum(
            1 for o in bf
            if o.controller_id == controller_id and "legendary" in o.card.type_line.lower()
            and (o.is_creature or o.is_planeswalker)
        )
    if selector.startswith("other_permanents_you_control_of_subtype_"):
        subtype = selector[len("other_permanents_you_control_of_subtype_"):]
        source_id = getattr(source, "instance_id", None)
        return sum(
            1 for o in bf
            if o.controller_id == controller_id and o.instance_id != source_id and _has_subtype(o, subtype)
        )
    if selector.startswith("permanents_you_control_of_subtype_"):
        subtype = selector[len("permanents_you_control_of_subtype_"):]
        return sum(1 for o in bf if o.controller_id == controller_id and _has_subtype(o, subtype))
    if selector in ("equipped_creatures_you_control", "equipped_attacking_creatures_you_control"):
        # "…the number of equipped creatures you control" (Barret Wallace) / "…for each equipped attacking creature you control" (Cloud, Ex-SOLDIER).
        attacking_only = selector == "equipped_attacking_creatures_you_control"
        return sum(
            1 for o in bf
            if o.is_creature and o.controller_id == controller_id and (o.attacking or not attacking_only)
            and any(a.attached_to == o.instance_id and _has_subtype(a, "equipment") for a in bf)
        )
    if selector == "greatest_power_among_creatures_you_control":
        # "…the greatest power among creatures you control" (Lifestream's Blessing's X).
        return max(
            (int(o.power or 0) for o in bf if o.is_creature and o.controller_id == controller_id), default=0,
        )
    if selector == "opponents_you_attacked_this_turn":
        return len({e.get("defending_player_id") for e in state.events_this_turn()
                    if e.type == "ATTACKS" and e.get("declared") and e.get("player_id") == controller_id
                    and e.get("defender_kind") == "player" and e.get("defending_player_id") != controller_id})
    if selector == "counters_on_permanents_you_control":
        # "…the number of counters among permanents you control" (Dimension X Pizzasaur) — every kind, every permanent.
        return sum(
            sum(v for v in (getattr(o, "counters", None) or {}).values() if v and v > 0)
            for o in bf if o.controller_id == controller_id
        )
    if selector == "counters_on_creatures_you_control":
        # "…the number of counters among creatures you control" (Maester Seymour's Monstrosity X) — every kind.
        return sum(
            sum(v for v in (getattr(o, "counters", None) or {}).values() if v and v > 0)
            for o in bf if o.is_creature and o.controller_id == controller_id
        )
    if selector == "plus_one_counters_on_creatures_you_control":
        return sum(
            int(getattr(o, "plus_one_counters", 0) or 0)
            for o in bf if o.is_creature and o.controller_id == controller_id
        )
    if selector == "modified_creatures_you_control":
        return sum(
            1 for creature in bf
            if creature.is_creature and creature.controller_id == controller_id
            and is_modified(state, creature)
        )
    if selector == "artifacts_you_control":
        return sum(1 for o in bf if o.card.is_artifact and o.controller_id == controller_id)
    if selector == "enchantments_you_control":
        return sum(1 for o in bf if o.card.is_enchantment and o.controller_id == controller_id)
    if selector == "commander_casts_this_game":
        # "…for each time you've cast your commander from the command zone
        # this game." (Vanguard of the Restless, Commander's Insight,
        # PAR-60) — `Player.commander_casts` is the per-commander cast tally
        # already kept for RULE 903.8 commander tax; sum it across the
        # controller's commanders.
        if controller_id is None:
            return 0
        try:
            player = state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return 0
        return sum(int(v or 0) for v in (getattr(player, "commander_casts", None) or {}).values())
    if selector == "total_power_creatures_you_control":
        # "This spell costs {X} less to cast, where X is the total power of
        # creatures you control." (Volcanic Salvo, PAR-60) — sum of derived
        # power over the controller's creatures (never negative).
        return max(0, sum(
            int(o.power or 0) for o in bf
            if o.is_creature and o.controller_id == controller_id
        ))
    if selector == "greatest_commander_mana_value":
        # "the greatest mana value among your commanders" / "…of a commander you own on the battlefield or in the
        # command zone" (Cloudkill, Imposing Grandeur, Majestic Genesis, Tangleweave Armor): a commander is owned,
        # not controlled (RULE 108.3), and counts in either zone; no commander is 0.
        owner = state.player_by_id(controller_id) if controller_id else None
        owned = [o for o in bf if o.is_commander and o.owner_id == controller_id]
        owned += list(getattr(owner, "command", None) or [])
        return max((o.card.converted_mana_cost or 0 for o in owned), default=0)
    if selector == "commanders_you_control":
        # "as long as you control your commander"/"if you control your
        # commander" (RULE 903.4 — Angelic Field Marshal, Loyal Drake and
        # the rest of the "Loyal" Commander-legends cycle, PAR-120). RULE
        # 108.4: control only applies to a battlefield permanent, so a
        # commander sitting in the command zone doesn't count — unlike
        # `condition_query.free_cast_condition_holds`'s looser
        # ``"control_commander"`` key (whether a commander is *available* to
        # cast at all, command zone included), this is the narrower "is it
        # actually on the battlefield under your control right now" read
        # the printed phrase means.
        return sum(1 for o in bf if o.is_commander and o.controller_id == controller_id)
    if selector == "total_power_attacking_creatures_you_control":
        # "if you attacked with creatures with total power N or greater this
        # combat" (Gnoll Hunter and the rest of the Onslaught-block "Pack
        # tactics" cluster, PAR-120) — the same sum-of-power reading as
        # `total_power_creatures_you_control` above, scoped to `o.attacking`
        # (RULE 508.1) the same way `attacking_creatures_you_control` scopes
        # a plain count. Checked at the attack trigger's own resolution,
        # after declare attackers, so the live flag is already correct.
        return max(0, sum(
            int(o.power or 0) for o in bf
            if o.is_creature and o.attacking and o.controller_id == controller_id
        ))
    if selector == "auras_you_control":
        # "for each Aura you control" (Eidolon of Countless Battles) and its
        # "…that's attached to a creature" narrowing (Sage's Reverie) —
        # Aura is a subtype (after the type-line em dash), so a printed
        # type-line scan rather than an `is_enchantment` main-type check.
        # The "attached to a creature" qualifier is a documented
        # simplification here (a stray unattached Aura is a rules corner
        # these singleton decks never reach).
        return sum(
            1 for o in bf
            if "aura" in (o.card.type_line or "").lower() and o.controller_id == controller_id
        )
    if selector == "artifacts_and_or_enchantments_you_control":
        return sum(
            1 for o in bf
            if (o.card.is_artifact or o.card.is_enchantment) and o.controller_id == controller_id
        )
    if selector == "creatures_opponents_control":
        # "for each creature your opponents control" (Riot Control) — the
        # mirror image of "creatures_you_control" above, same "opponents"
        # idiom as "artifacts_and_or_enchantments_opponents_control" below.
        return sum(
            1 for o in bf
            if o.is_creature and o.controller_id not in (None, controller_id)
        )
    if selector.startswith("creatures_opponents_control_with_power_ge_"):
        threshold = int(selector.removeprefix("creatures_opponents_control_with_power_ge_"))
        return sum(
            1 for o in bf
            if o.is_creature and o.controller_id not in (None, controller_id)
            and o.power is not None and o.power >= threshold
        )
    if selector == "artifacts_and_or_enchantments_opponents_control":
        # "the number of artifacts and enchantments your opponents control"
        # (Dockside Extortionist) — the mirror image of the "you control"
        # entry above: everyone *except* the reference controller, same
        # "opponents" idiom `group_selector_objects`'s own
        # ``"opponents_permanents"`` uses.
        return sum(
            1 for o in bf
            if (o.card.is_artifact or o.card.is_enchantment)
            and o.controller_id not in (None, controller_id)
        )
    if selector == "equipment_you_control":
        # "~ gets +1/+1 for each Equipment you control." (Adelbert Steiner,
        # PAR-43) — the board-wide sibling of `_pt_mod_count`'s own
        # ``"equipment_attached_to_self"`` (that one counts what's attached
        # to *this* creature; this one counts every Equipment permanent the
        # controller owns, attached or not).
        return sum(
            1 for o in bf if o.controller_id == controller_id and _has_subtype(o, "equipment")
        )
    if selector == "other_enchantments_on_the_battlefield":
        # "enchanted creature gets +2/+2 for each other enchantment on the
        # battlefield." (Ancestral Mask, PAR-43) — every enchantment on the
        # battlefield minus the Aura bearing this ability itself.
        source_id = getattr(source, "instance_id", None)
        return sum(1 for o in bf if o.card.is_enchantment and o.instance_id != source_id)
    if selector == "other_creatures_you_control":
        # "~ gets +1/+0 for each other creature you control." (Leonardo, Big
        # Brother, PAR-43) — `creatures_you_control` minus the source itself
        # (RULE 109.5's "other" excludes the object bearing the ability).
        source_id = getattr(source, "instance_id", None)
        return sum(
            1 for o in bf
            if o.is_creature and o.controller_id == controller_id and o.instance_id != source_id
        )
    if selector == "other_artifacts_you_control":
        # "for each other artifact you control" (Iron Man, Master of
        # Machines; Krang, Master Mind, PAR-43) — the artifact sibling of
        # `other_creatures_you_control` just above.
        source_id = getattr(source, "instance_id", None)
        return sum(
            1 for o in bf
            if o.card.is_artifact and o.controller_id == controller_id and o.instance_id != source_id
        )
    if selector == "transformed_permanents_you_control":
        # "~ gets +1/+0 for each transformed permanent you control."
        # (Mutagen Connoisseur, PAR-43) — `GameObject.transformed` (RULE 712).
        return sum(1 for o in bf if o.controller_id == controller_id and o.transformed)
    if selector == "poison_counters_opponents_have":
        # "~ gets +1/+1 for each poison counter your opponents have."
        # (Mycosynth Fiend, PAR-43) — summed across every opponent, the
        # player-counter sibling of `creatures_opponents_control`.
        if controller_id is None:
            return 0
        return sum(
            p.poison for p in state.living_players() if p.id != controller_id
        )
    if selector == "experience_counters_you_have":
        # "~ gets +1/+1 for each experience counter you have." (Kalemne,
        # Disciple of Iroas; Kelsien, the Plague; Azula, Ruthless Firebender,
        # PAR-43) — RULE 122's free-form player counters.
        if controller_id is None:
            return 0
        try:
            player = state.player_by_id(controller_id)
        except (KeyError, ValueError):
            return 0
        return int(player.counters.get("experience", 0))
    if selector == "total_counters_on_source":
        # "equipped creature gets +1/+1 for each counter on it." (Gavel of
        # the Righteous, Luxior, Giada's Gift, PAR-43) — every counter kind
        # on ``source``, unlike ``source_<kind>_counters``'s single-kind read.
        if source is None:
            return 0
        counters = getattr(source, "counters", None) or {}
        return int(getattr(source, "plus_one_counters", 0) or 0) + sum(
            int(v or 0) for v in counters.values()
        )
    if selector == "source_colors_count":
        # "equipped creature gets +1/+0 for each of its colors." (Civic
        # Saber; Blessing of the Nephilim, PAR-43) — the source's own
        # layer-5 derived colour set (RULE 105.2a).
        return len(getattr(source, "colors", None) or ()) if source is not None else 0
    if selector == "cards_in_your_graveyard":
        try:
            player = state.player_by_id(controller_id) if controller_id else None
        except KeyError:
            player = None
        return len(player.graveyard) if player is not None else 0
    if selector == "creature_cards_in_your_graveyard":
        # "Incubate X, where X is the number of creature cards in your
        # graveyard." (Blight Titan, PAR-30) — the creature-filtered sibling
        # of ``cards_in_your_graveyard`` just above.
        try:
            player = state.player_by_id(controller_id) if controller_id else None
        except KeyError:
            player = None
        return sum(1 for c in player.graveyard if c.card.is_creature) if player is not None else 0
    if selector.startswith("devotion_to_"):
        # RULE 202.2f/700.5: "your devotion to <colour>" is the number of
        # mana symbols of that colour in the mana costs of permanents you
        # control (Thassa's Oracle) — with a hybrid pip counting toward
        # *both* of its colours, which `ManaSymbol.colors` already models as
        # a set (Kitchen Finks' {G/W}{G/W} is 2 green *and* 2 white
        # devotion). Read off the printed cost string rather than
        # `Card.mana_cost`'s per-colour dict, which is only populated for
        # cards that came from Scryfall.
        #
        # "Devotion to two [or three] colors" (RULE 700.6's own
        # multi-colour reading, Athreos/Karametra-shaped "white and black")
        # sums across all named colours instead of one — parsed here as a
        # short lowercase-letter suffix (``"wb"``) by `subgrammars.
        # devotion_selector`, distinct from the single full colour word
        # every existing single-colour selector already uses, so there's no
        # collision between the two suffix shapes.
        from ..models.mana.mana_cost import ManaCost  # function-scoped: see module header

        suffix = selector[len("devotion_to_"):]
        if suffix == "hybrid":
            # "Devotion to hybrid" (Blended Twistling) — any hybrid mana
            # symbol counts once, regardless of *which* two colours it's
            # between, unlike ordinary devotion where a hybrid pip counts
            # toward *both* named colours. A mono-hybrid pip ({2/W}) isn't a
            # mix of colours at all (it's generic-or-colour), so it doesn't
            # count here even though it's colour-flexible the same way.
            from ..models.mana.mana_cost import HYBRID, ManaCost  # function-scoped: see module header

            return sum(
                sum(
                    1
                    for symbol in ManaCost.parse(o.card.mana_cost_string).symbols
                    if symbol.kind == HYBRID
                )
                for o in bf
                if o.controller_id == controller_id
            )
        colour = _DEVOTION_COLOURS.get(suffix)
        wedge = _DEVOTION_WEDGES.get(suffix)
        if colour is not None:
            letters = {colour}
        elif wedge is not None:
            letters = set(wedge)
        elif suffix and suffix.isalpha() and 2 <= len(suffix) <= 5 and set(suffix.upper()) <= set("WUBRG"):
            letters = set(suffix.upper())
        else:
            return 0
        return sum(
            sum(
                1
                for symbol in ManaCost.parse(o.card.mana_cost_string).symbols
                if letters & symbol.colors
            )
            for o in bf
            if o.controller_id == controller_id
        )
    if selector == "cards_named_source_in_all_graveyards":
        # "for each card named ~ in each graveyard" (Rite of Flame) — a
        # cross-player aggregate like `total_rad_counters_among_players`
        # below, but name-keyed, and keyed to the *effect's own source's*
        # name rather than a literal from card text (which would put a
        # free-form string through the spec boundary for no benefit).
        # ``controller_id`` is unused: every graveyard counts, not just
        # yours. The resolving spell itself is on the stack, not in a
        # graveyard, so it never counts itself.
        name = (_source_card_name or "").strip().lower()
        if not name:
            return 0
        return sum(
            1
            for p in state.players
            for card in p.graveyard
            if (card.name or "").strip().lower() == name
        )
    if selector == "total_rad_counters_among_players":
        # Vault 12: The Necropolis chapter II: "X is the total number of rad
        # counters among players" — the one cross-player aggregate amount in
        # this pool, unlike every entry above (all scoped to ``controller_id``):
        # sums `Player.counters["rad"]` across *every* player regardless of
        # who controls this effect's source.
        return sum(p.counters.get("rad", 0) for p in state.players)
    if selector == "creatures_died_this_turn":
        # "…where X is the number of creatures that died this turn." (MEC-43
        # round 4C, Spoils of Blood) — another cross-player aggregate
        # (RULE 700.4's "died" has no controller scope in the card's own
        # wording), summed off `GameState.creatures_died_this_turn`
        # (`RulesEngine._track_creature_death`'s own per-controller tally,
        # cleared once per real turn by `turn_loop_mixin`), the same
        # "sum across every player" shape `total_rad_counters_among_players`
        # just above uses.
        return sum(state.creatures_died_this_turn.values())
    if selector == "nontoken_creatures_died_this_turn":
        # Gadrak, the Crown-Scourge: "…for each nontoken creature that died this turn" — the
        # `creatures_died_this_turn` tally across every player, minus tokens (the DIES event's own
        # ``is_token`` snapshot).
        return sum(state.nontoken_creatures_died_this_turn.values())
    if selector == "creatures_you_controlled_died_this_turn":
        # "…the number of creatures that died under your control this turn" (Priest of the Crossing) — the
        # controller's own entry of the per-controller DIES tally (`creatures_died_this_turn` sums them all).
        return int(state.creatures_died_this_turn.get(controller_id, 0))
    if selector == "creatures_attacked_this_turn":
        # RULE 508.1a/508.4: a creature put onto the battlefield attacking
        # did not attack. Count each declared attacker's object once even if
        # another combat phase let it attack again this turn.
        return len({event.get("instance_id") for event in state.events_this_turn()
                    if event.type == "ATTACKS" and event.get("declared")
                    and event.get("instance_id") is not None
                    and "creature" in (event.get("object_types") or ())})
    if selector == "creatures_you_attacked_with_this_turn":
        # "…if you attacked with two or more creatures this turn" (Minas Tirith) — `creatures_attacked_this_turn`
        # scoped to the attacks the controller declared (the ATTACKS event's ``player_id``, RULE 508.1a).
        return len({event.get("instance_id") for event in state.events_this_turn()
                    if event.type == "ATTACKS" and event.get("declared")
                    and event.get("player_id") == controller_id
                    and event.get("instance_id") is not None
                    and "creature" in (event.get("object_types") or ())})
    return 0


def _count_selector(state: "GameState", ability: StaticAbility, selector: str) -> int:
    """`count_selector`, scoped to a `StaticAbility`'s own source's
    controller (RULE 613.7c/604.3) — see `count_selector` for the
    vocabulary."""
    return count_selector(
        state, getattr(ability.source, "controller_id", None), selector, source=ability.source
    )


def _attached_subtype_count(state: "GameState", obj: "GameObject", subtype: str) -> int:
    """How many permanents of a given subtype are currently attached to
    ``obj`` itself — a *per-object* count (Bruenor Battlehammer's "for each
    Equipment attached to it", Kor Spiritdancer's "for each Aura attached to
    it"), unlike every `count_selector` entry above (one number shared by
    every object a static ability affects)."""
    return sum(
        1 for o in state.battlefield
        if o.attached_to == obj.instance_id and subtype in (o.card.type_line or "").lower()
    )


def _equipment_attached_count(state: "GameState", obj: "GameObject") -> int:
    return _attached_subtype_count(state, obj, "equipment")


def _pt_mod_count(
    state: "GameState", ability: StaticAbility, obj: "GameObject", selector: "str | dict[str, Any]"
) -> int:
    """A layer-7d anthem's per-unit multiplier — either a per-object count
    (``"equipment_attached_to_self"``), the ability's own source's counters
    (``"plus_one_counters_on_self"`` — Lion Sash's "for each +1/+1 counter
    on this Equipment"), or the ordinary controller-scoped `count_selector`
    vocabulary (Blackblade Reforged's "for each land you control",
    Nettlecyst's "for each artifact and/or enchantment you control")."""
    if selector == "equipment_attached_to_self":
        return _equipment_attached_count(state, obj)
    if selector == "times_attacked_this_turn_self":
        return int(getattr(obj, "times_attacked_this_turn", 0) or 0)  # Moraug
    if selector == "auras_attached_to_self":
        # "gets +2/+2 for each Aura attached to it" (Kor Spiritdancer) — the
        # Aura sibling of ``equipment_attached_to_self``.
        return _attached_subtype_count(state, obj, "aura")
    if selector == "equipment_and_auras_attached_to_self":
        # "~ gets +2/+2 for each Aura and Equipment attached to it."
        # (Champion of the Flame; Mantle of the Ancients, PAR-43) — the sum
        # of the two single-subtype counts above.
        return _equipment_attached_count(state, obj) + _attached_subtype_count(state, obj, "aura")
    if selector == "plus_one_counters_on_self":
        return getattr(ability.source, "plus_one_counters", 0)
    if selector == "counters_on_self":
        # "…get +1/+1 for each unity counter on this enchantment." (Call
        # for Unity) — the *named*-counter-kind sibling of
        # ``plus_one_counters_on_self``, kind read off ``counter_kind``
        # (default "+1/+1" so an unparameterized use still means the plain
        # kind).
        counters = getattr(ability.source, "counters", None) or {}
        kind = str(ability.params.get("counter_kind", "+1/+1"))
        return int(counters.get(kind, 0))
    if isinstance(selector, dict) and _selector_filter_names_its_object(selector):
        # PAR-123: "for each other creature that shares a creature type with **it**" / "…blocking it" —
        # "it" is the creature the static affects, whichever that is (an Aura's host, an anthem's
        # recipient), so the counted-against reference is ``obj`` rather than the ability's source.
        return count_selector(
            state, getattr(ability.source, "controller_id", None), selector, source=obj
        )
    return _count_selector(state, ability, selector)


def _selector_filter_names_its_object(selector: dict[str, Any]) -> bool:
    """Whether a structured selector's filter is relative to "it" (the object it is evaluated for)."""
    filt = selector.get("filter")
    return isinstance(filt, dict) and bool(
        filt.get("shares_creature_type_with_reference") or filt.get("blocking_source")
    )


def commander_color_identity(state: "GameState", controller_id: str) -> frozenset[str]:
    """RULE 903.4's fixed colour identity of ``controller_id``'s commander(s)
    — the union of every ``is_commander`` object's printed
    ``Card.color_identity`` this player owns, searched across every personal
    zone plus the battlefield (not just the command zone: a commander
    spends most of a real game on the battlefield, and RULE 903.4 doesn't
    change once the game starts regardless of which zone it's currently
    in). Commander's Plate's dynamic protection grant (MEC-43,
    `_protection_qualities`'s ``protection_from_colors_not_in_commanders_
    identity``) is the one live consumer so far — no prior card needed a
    live read of "your commander's color identity" during a game.
    """
    try:
        player = state.player_by_id(controller_id)
    except (KeyError, ValueError):
        return frozenset()
    identity: set[str] = set()
    for zone_objects in player.zones.values():
        for obj in zone_objects:
            if getattr(obj, "is_commander", False) and obj.card is not None:
                identity |= set(obj.card.color_identity)
    for obj in state.battlefield:
        if (
            obj.owner_id == controller_id
            and getattr(obj, "is_commander", False)
            and obj.card is not None
        ):
            identity |= set(obj.card.color_identity)
    return frozenset(identity)


def _protection_qualities(ability: StaticAbility, state: "GameState") -> set[str]:
    """A layer-6 `grant_protection` ability's RULE 702.16 qualities, as
    `combat.protections_of_text` tokens.

    ``protections`` is the printed word list ("black", "rats") the parser
    emits verbatim (it can't normalize them itself — the front end is
    barred from importing `game/`). ``protection_from_chosen_color`` is the
    RULE 601.2b dynamic variant (Flickering Ward/Benevolent Blessing's "…
    protection from **the chosen color**"), read fresh off the ability's own
    source every pass — the same live re-read the ``color_from_source``/
    ``subtype_from_source`` selectors do — so re-choosing in Replay/Puzzle
    mode updates the board rather than baking the choice in once.
    ``protection_from_chosen_type`` is the same idea for a chosen *creature
    type* ("protection from creatures of **the chosen type**", Riders of
    Gavony) — `GameObject.chosen_type` is already a bare subtype word
    (`_quality_matches_type` matches it against a card's subtypes verbatim,
    no colour-style normalization needed).
    ``protection_from_colors_not_in_commanders_identity`` (Commander's
    Plate, MEC-43) is the complement of `commander_color_identity` for this
    ability's own *controller* (RULE 301.5c — "your" on an Equipment's own
    static ability means the Equipment's controller, not necessarily the
    equipped creature's) — read fresh every pass, same live-reread idiom as
    the two ``chosen_*`` branches above.
    """
    from . import combat  # function-scoped: combat imports this module
    from ..models.cards.card import VALID_COLORS

    words = ability.params.get("protections") or []
    quals: set[str] = set()
    for word in words:
        quals |= combat.protections_of_text(f"protection from {word}.")
    if ability.params.get("protection_from_chosen_color"):
        # `GameObject.chosen_color` is already a WUBRG identity letter (see
        # `RulesEngine._ANY_COLOR_LABELS`) — the exact token
        # `is_protected_from` matches against a source's own `colors`, so it
        # goes in directly rather than through the colour-*word* fold above.
        chosen = getattr(ability.source, "chosen_color", None)
        if chosen:
            quals.add(str(chosen).upper())
    if ability.params.get("protection_from_chosen_type"):
        chosen_type = getattr(ability.source, "chosen_type", None)
        if chosen_type:
            quals.add(str(chosen_type).lower())
    if ability.params.get("protection_from_mana_values_among_artifacts"):
        # RULE 702.16a: "protection from each mana value among artifacts you control" is one protection per distinct
        # mana value; `combat._quality_matches_type` matches a ``mv:N`` quality against the source's mana value.
        controller_id = getattr(ability.source, "controller_id", None)
        quals |= {
            f"mv:{int(getattr(o.card, 'converted_mana_cost', 0) or 0)}"
            for o in state.battlefield if o.controller_id == controller_id and o.card.is_artifact
        }
    if ability.params.get("protection_from_colors_not_in_commanders_identity"):
        controller_id = getattr(ability.source, "controller_id", None)
        if controller_id is not None:
            identity = commander_color_identity(state, controller_id)
            quals |= (VALID_COLORS - identity)
    return quals


def player_static_protections(state: "GameState", player: "Player") -> set[str]:
    """RULE 702.16 qualities ``player`` has from standing grants ("You and creatures you control have protection from the
    chosen card type", Serra's Emissary) — a ``grant_protection_static`` carrying ``protects_controller``. A player has no
    text of its own, so `RulesEngine.deal_damage` asks this instead of `combat.is_protected_from` (damage being the one
    DEBT letter a player is subject to in this model)."""
    quals: set[str] = set()
    for ability in _battlefield_static_abilities(state):
        if (
            ability.layer == "ability"
            and ability.params.get("protects_controller")
            and getattr(ability.source, "controller_id", None) == player.id
        ):
            quals |= _protection_qualities(ability, state)
    return quals


#: Mirrors `effect_binder._SUBJECT_EVENT_KEYS` — which event-data key
#: identifies *which object* a grantable event is about. Kept as a local
#: copy rather than imported (`continuous.py` stays free of `effect_binder`
#: imports; it's one entry, not worth a shared-module indirection).
_GRANTED_EVENT_KEYS: dict[str, str] = {"DAMAGE": "source_id", "COUNTER": "target_id"}

#: RULE 119.3 player-subject grantable events ("Equipped creature has
#: 'Whenever **you** gain life, …'" — Field-Tested Frying Pan/Light of
#: Promise/Sunbond) — like `STEP_BEGIN`, these carry no object-identity key
#: at all (`LIFE_GAINED` carries ``player_id``/``amount``, not an
#: `instance_id`/``source_id``), but unlike `STEP_BEGIN` the scoping isn't
#: "whose turn it is" — it's "whose life total changed", checked against the
#: granted-to permanent's own controller (the same "resolve 'your' against
#: `target`, not the granting source's controller" rule `phase_relation`
#: documents below).
_PLAYER_SUBJECT_GRANTED_EVENTS = frozenset(
    {"LIFE_GAINED", "DRAW", "SPELL_CAST", "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER"}
)


def _granted_trigger_condition(
    target: "GameObject",
    controllers_turn_only: bool,
    trigger_event: Optional[str] = None,
    event_filter: Optional[dict[str, Any]] = None,
    phase_relation: Optional[str] = None,
):
    """The `TriggeredAbility.condition` for one object's granted ability.

    Each object under a "X have '<triggered ability>'" grant (Dionus, Elvish
    Archdruid; a quoted Aura/Equipment grant, `static_handlers.
    _quoted_ability_grant_effects`) gets its *own* `TriggeredAbility`
    instance (see `recompute`'s layer-6 pass) — without this, every one of
    them would react to the triggering event regardless of which specific
    object it was about (e.g. one Elf being tapped would also untap every
    *other* Elf under the same anthem). Scoped by the event's own subject key
    (``source_id`` for ``DAMAGE``, ``instance_id`` for everything else — see
    `_GRANTED_EVENT_KEYS`, the same convention `effect_binder.
    _subject_event_key` uses for an ordinary printed trigger).
    ``event_filter`` is the same small exact-match dict
    `effect_binder._trigger_condition`'s ``"filter"`` ANDs on — needed for
    DAMAGE's ``{"combat": ..., "is_player": ...}`` (RULE 120.3 "deals combat
    damage to a player/creature") and for a granted RULE 500.7 phase
    trigger's own ``{"step": "upkeep"}``.

    ``phase_relation`` ("you"/"not_you") is that phase trigger's scope. A
    ``STEP_BEGIN`` event carries no object key at all, so identity scoping
    is a deliberate no-op for it; what makes "Enchanted creature has 'At the
    beginning of **your** upkeep, …'" (Commander's Authority/Aura Flux)
    mean the right thing is resolving "your" against ``target`` — the
    permanent the ability was granted *to* — rather than the granting
    source's controller, which is why this can't reuse `effect_binder.
    _trigger_condition`'s own `phase_relation` branch.

    ENG-11: ``STEP_BEGIN`` is the *only* legitimate no-subject case. Every
    other grant is about one specific object, so an event that doesn't carry
    the key `_GRANTED_EVENT_KEYS` maps its `trigger_event` to is a
    registration gap (a new event shape nobody added there), not a
    genuinely subject-less one — fail closed rather than let the fail-open
    reading ("no key -> don't filter") fire the ability for *every* object
    under the same grant, mirroring `effect_binder._subject_condition`'s own
    "missing instance_id -> False" rule for the ordinary (non-granted)
    self-subject case. The parser front-end
    (`static_handlers._quoted_ability_grant_effects`) only ever emits a
    non-``STEP_BEGIN`` grant for a ``{"subject": "self"}`` trigger, which by
    construction only exists for events `_TRIGGER_VERBS` has matched to a
    verb whose event *does* carry an identity key — so this is a safety net
    against a future hand-authored `card_catalogue` entry naming an
    unregistered event, not a path any card exercises today.
    """
    key = _GRANTED_EVENT_KEYS.get(trigger_event or "", "instance_id")
    filt = dict(event_filter) if event_filter else None
    # STEP_BEGIN is intrinsically subject-less.  An unscoped "at the
    # beginning of each upkeep" ability therefore fires once for every
    # permanent that has received the grant; a phase relation, when present,
    # merely narrows that already-valid event stream to its controller's (or
    # opponents') turn.
    no_object_subject = trigger_event == "STEP_BEGIN"
    player_subject = trigger_event in _PLAYER_SUBJECT_GRANTED_EVENTS

    def condition(event: Any, context: Any) -> bool:
        if player_subject:
            # "Whenever **you** gain life, …" granted onto a permanent means
            # that permanent's own controller, not the granting source's —
            # same "resolve against target" rule STEP_BEGIN's phase_relation
            # branch below uses, just keyed on player_id instead of turn.
            if event.get("player_id") != target.controller_id:
                return False
        else:
            event_subject = event.get(key)
            if event_subject is None:
                if not no_object_subject:
                    # ENG-11: only a STEP_BEGIN phase trigger legitimately fires
                    # off an event with no object subject at all (scoped by
                    # whose turn it is, below, instead). Any other grant is
                    # about one specific object, so an event that doesn't carry
                    # the key `_GRANTED_EVENT_KEYS` maps `trigger_event` to is a
                    # registration gap, not a subject-less event — fail closed
                    # rather than let every object under the same grant react to
                    # an event about none of them.
                    return False
            elif event_subject != target.instance_id:
                return False
        if filt and not all(event.get(k) == v for k, v in filt.items()):
            return False
        if controllers_turn_only and context.state.active_player.id != target.controller_id:
            return False
        if phase_relation in ("you", "not_you"):
            active = getattr(context.state, "active_player", None)
            if active is None:
                return False
            is_yours = active.id == target.controller_id
            if is_yours is not (phase_relation == "you"):
                return False
        return True

    return condition


def _apply_copy_layer(state: "GameState") -> None:
    """Layer 1: conditional "become a copy of target" effects (RULE 707.2,
    Vesuvan Shapeshifter-style "as long as untapped, ~ is a copy of …").

    Transition-only, unlike every other layer here: `copy_mechanics.
    become_copy` wipes and rebinds the object's whole ability set from the
    copied card, so re-running it every single pass regardless of whether
    anything changed would destroy per-turn bookkeeping on the copy's own
    granted triggered abilities. There is also deliberately no "ability
    disappeared -> revert" branch: per the real Vesuvan Shapeshifter ruling,
    a successful copy that lands on a creature without a similar ability
    *consumes* the very ability that caused it — the object simply stays
    what it currently is from then on, it doesn't revert on its own.
    """
    from . import copy_mechanics  # function-scoped: avoid an import cycle

    for src in state.battlefield:
        ability = next(
            (ab for ab in getattr(src, "static_effects", [])
             if isinstance(ab, StaticAbility) and ab.layer == "copy"),
            None,
        )
        if ability is None:
            continue  # nothing driving a copy/revert here right now

        condition_holds = not (ability.params.get("requires_untapped") and src.tapped)
        if not condition_holds:
            if src._copy_base is not None:
                copy_mechanics.restore_face(src, src._copy_base)
                src._copy_base = None
                src._copy_applied_target_id = None
            continue

        target_id = src.copy_target_id
        if target_id is not None and target_id != src._copy_applied_target_id:
            target = state.find_object(target_id)
            if target is not None and target in state.battlefield and target is not src:
                if src._copy_base is None:
                    src._copy_base = copy_mechanics.snapshot_face(src)
                copy_mechanics.become_copy(
                    src, target, ability.params.get("add_types"), ability.params.get("add_subtypes")
                )
                src._copy_applied_target_id = target_id


def _order_control_effects(abilities: list[StaticAbility]) -> list[StaticAbility]:
    """RULE 613.8, bounded to layer 2 (see module docstring for why only
    here): a controller-scoped ``affects`` selector ("creatures you
    control") can see a different object set depending on whether another
    control-change already ran, so those must apply *after* every direct-
    scoped ability (``self``/``attached_permanent``) regardless of
    timestamp. Two buckets, each still timestamp-ordered internally
    (``abilities`` is already `_in_layer`-sorted) — not a general
    dependency graph, since nothing else in this engine's vocabulary needs
    one.
    """
    direct = [a for a in abilities if a.affects in ("self", "attached_permanent")]
    scoped = [a for a in abilities if a not in direct]
    return direct + scoped


#: `Zone`s an "off the battlefield" type-extending static ability reaches —
#: RULE 613.4a applied to objects the layer engine's ordinary battlefield
#: walk never touches (Arcane Adaptation/Leyline of Transformation's "…
#: creature cards you own that aren't on the battlefield", Ashes of the
#: Fallen's "each creature card in your graveyard"). Spells on the stack are
#: handled separately (they live in `GameState.stack`, not a player zone).
_OFF_BATTLEFIELD_ZONE_ATTRS: tuple[str, ...] = ("hand", "graveyard", "library", "exile")


def _off_battlefield_objects(state: "GameState", scope: str, controller_id: Optional[str]):
    """The off-battlefield `GameObject`s a type-extending static reaches.

    ``"cards_you_own"`` — Arcane Adaptation's "creature spells you control
    and creature cards you own that aren't on the battlefield": every zone
    of the ability's controller *plus* any spell they control on the stack.
    ``"your_graveyard"`` — Ashes of the Fallen's narrower "each creature
    card in your graveyard".
    """
    if controller_id is None:
        return []
    player = next((p for p in state.players if p.id == controller_id), None)
    if player is None:
        return []
    if scope == "your_graveyard":
        return list(player.graveyard)
    if scope != "cards_you_own":
        return []
    out: list[Any] = []
    for attr in _OFF_BATTLEFIELD_ZONE_ATTRS:
        out.extend(getattr(player, attr, None) or [])
    for item in getattr(state, "stack", None) or []:
        obj = getattr(item, "obj", None)
        if obj is not None and getattr(item, "controller_id", None) == controller_id:
            out.append(obj)
    return out


def _apply_off_battlefield_types(state: "GameState", abilities: list[StaticAbility]) -> None:
    """RULE 613.4a type grants that reach *past* the battlefield.

    Arcane Adaptation/Leyline of Transformation ("The same is true for
    creature spells you control and creature cards you own that aren't on
    the battlefield") and Ashes of the Fallen ("Each creature card in your
    graveyard has the chosen creature type in addition to its other types")
    both extend a chosen creature type onto objects `recompute`'s ordinary
    battlefield walk never visits, so `reset_derived` never clears them
    either. Every object stamped by a previous pass is therefore tracked on
    the state and reset here first — that's what makes the grant disappear
    on its own the moment its source leaves (RULE 613.6), exactly like every
    battlefield-side layer effect.

    Only `_added_subtypes` is stamped: `has_subtype` reads it directly, so
    a tribal check ("target Zombie card in your graveyard", a Cavern of
    Souls-shaped named-type cast restriction) sees the extension without any
    caller needing to know about it.
    """
    previous = getattr(state, "_off_battlefield_typed", None) or []
    for obj in previous:
        obj._added_subtypes = set()
    stamped: list[Any] = []

    for ability in _in_layer(abilities, "type"):
        scope = ability.params.get("off_battlefield")
        if not scope:
            continue
        add_subtypes = list(ability.params.get("add_subtypes", []))
        if ability.params.get("add_subtypes_from_source"):
            chosen = getattr(ability.source, "chosen_type", None)
            if chosen:
                add_subtypes.append(chosen)
        if not add_subtypes:
            continue
        controller_id = getattr(ability.source, "controller_id", None)
        for obj in _off_battlefield_objects(state, str(scope), controller_id):
            # RULE 205.3: the clause only ever names *creature* cards.
            if not getattr(obj.card, "is_creature", False):
                continue
            obj._added_subtypes.update(add_subtypes)
            stamped.append(obj)

    state._off_battlefield_typed = stamped


def ring_bearer_of(state: "GameState", player: Any) -> Optional[Any]:
    """RULE 701.52a: ``player``'s Ring-bearer, or ``None``.

    Resolved fresh off `Player.ring_bearer_id` against the live battlefield
    rather than held as an object reference, so a bearer that has left the
    battlefield (or changed controller) simply stops being one — the same
    "re-derive, never un-stamp" discipline every layer effect here follows.
    """
    bearer_id = getattr(player, "ring_bearer_id", None)
    if not bearer_id:
        return None
    for obj in state.battlefield:
        if obj.instance_id == bearer_id and obj.controller_id == player.id:
            return obj
    return None


def ring_level_of(state: "GameState", obj: Any) -> int:
    """How many times the Ring has tempted ``obj``'s controller, if ``obj``
    is currently their Ring-bearer — 0 otherwise (RULE 701.51a).

    The single question every Ring ability asks, so combat and the
    inherent-trigger scan can both ask it without repeating the lookup.
    """
    player = state.player_by_id(obj.controller_id)
    if player is None or ring_bearer_of(state, player) is not obj:
        return 0
    return int(getattr(player, "ring_level", 0) or 0)


def _apply_ring_bearer_static(state: "GameState") -> None:
    """RULE 701.51a, the Ring emblem's first ability: "Your Ring-bearer is
    legendary and can't be blocked by creatures with greater power."

    Only the legendary half is a characteristic (layer 4, stamped here); the
    blocking restriction is a combat rule, enforced by `GameEngine.can_block`
    off `ring_level_of` at declare-blockers time.
    """
    for player in state.players:
        if int(getattr(player, "ring_level", 0) or 0) < 1:
            continue
        bearer = ring_bearer_of(state, player)
        if bearer is not None:
            bearer._granted_legendary = True
            _trace(bearer, 4, "The Ring", "legendary (Ring-bearer)")


def _apply_layer_2_control(state: "GameState", abilities: list) -> None:
    # -- Layer 2: control-changing effects (RULE 613.2).
    for ability in _order_control_effects(_in_layer(abilities, "control")):
        new_controller = ability.params.get("controller") or getattr(
            ability.source, "controller_id", None
        )
        if new_controller is None:
            continue
        for obj in affected_objects(state, ability):
            if obj.controller_id != new_controller:
                obj._control_base = obj.controller_id
                obj.controller_id = new_controller
                _trace(obj, 2, _source_name(ability), f"controlled by {new_controller}")


def _apply_layer_3_text(state: "GameState", abilities: list) -> None:
    # -- Layer 3: text-changing effects (RULE 612), scoped (see module
    # docstring): word-substitution over `effective_oracle_text`, chained in
    # timestamp order if 2+ apply to the same object.
    for ability in _in_layer(abilities, "text"):
        replace = {str(k): str(v) for k, v in (ability.params.get("replace") or {}).items()}
        if not replace:
            continue
        for obj in affected_objects(state, ability):
            text = obj._derived_oracle_text if obj._derived_oracle_text is not None else (obj.card.oracle_text or "")
            for old, new in replace.items():
                text = re.sub(rf"\b{re.escape(old)}\b", new, text, flags=re.IGNORECASE)
            obj._derived_oracle_text = text
            _trace(obj, 3, _source_name(ability), f"text: {replace}")


def _apply_layer_4_type(state: "GameState", abilities: list) -> dict[int, tuple[int, int]]:
    # -- Layer 4: type-changing effects (may add "creature" + animation P/T).
    animation_pt: dict[int, tuple[int, int]] = {}

    # RULE 702.151b: a Reconfigure permanent stops being a creature for as
    # long as it's attached to another creature (it's an Equipment while
    # attached). This is inherent to the permanent's own attached state, not
    # an "affects other objects" static ability, so it's special-cased here
    # rather than going through a `StaticAbility`/`affected_objects` pass.
    for obj in state.battlefield:
        if obj.attached_to is not None and "reconfigure" in (obj.parametric_keywords or {}):
            obj._removed_types.add("creature")

    for ability in _in_layer(abilities, "type"):
        added = ability.params.get("add_types", [])
        # "…and loses all other card types…" (Vraska, Betrayal's Sting's
        # -2 — "target creature becomes a Treasure artifact … and loses
        # all other card types and abilities") — the removal-side mirror
        # of `add_types`, read by `GameObject.type_words`/`is_creature`
        # the same way `_removed_types` already strips creature-ness for
        # RULE 702.151b's Reconfigure-while-attached case.
        removed = ability.params.get("remove_types", [])
        set_subtypes = ability.params.get("set_subtypes")
        # A resolution-time sibling of the standing "is the chosen type in
        # addition" effect: Mistform's "becomes the creature type of your
        # choice" overwrites, rather than adds to, its creature subtypes.
        if ability.params.get("set_subtypes_from_source"):
            chosen = getattr(ability.source, "chosen_type", None)
            if chosen:
                set_subtypes = [chosen]
        # "~ is the chosen type in addition to its other types" (RULE
        # 601.2b/613.4a, Adaptive Automaton/A-Thran Portal-shaped) — reads
        # the ability's own source's `chosen_type` fresh every recompute,
        # same as the `subtype_from_source` selector param above; ``None``
        # (no choice made yet) simply adds nothing.
        add_subtypes = list(ability.params.get("add_subtypes", []))
        if ability.params.get("add_subtypes_from_source"):
            chosen = getattr(ability.source, "chosen_type", None)
            if chosen:
                add_subtypes.append(chosen)
        power, toughness = ability.params.get("power"), ability.params.get("toughness")
        pt_selector = ability.params.get("pt_selector")
        if ability.params.get("from_linked_exile"):
            # "As long as a card exiled with this creature is a creature card, this creature has the power,
            # toughness, and creature types of the last creature card exiled with it." (Duplicant) — read off
            # the source's own Imprint link (`linked_exile_id`) fresh every pass; no creature card there, no effect.
            linked = state.find_object(getattr(ability.source, "linked_exile_id", None))
            if (
                linked is None or getattr(getattr(linked, "zone", None), "value", None) != "exile"
                or not linked.card.is_creature
            ):
                continue
            power, toughness = linked.card.power, linked.card.toughness
            if not (isinstance(power, int) and isinstance(toughness, int)):
                power = toughness = None
            add_subtypes += linked.card.type_line.partition("—")[2].split()
        for obj in affected_objects(state, ability):
            if pt_selector == "mana_value":
                obj_power = obj_toughness = getattr(obj.card, "converted_mana_cost", 0) or 0
            elif pt_selector == "vehicle":
                # "Target Vehicle becomes an artifact creature until end of turn." (Mech Hangar, Peacewalker Colossus)
                # — RULE 301.7: it has the printed Vehicle P/T of *whichever* Vehicle was chosen.
                obj_power = getattr(obj.card, "vehicle_power", None)
                obj_toughness = getattr(obj.card, "vehicle_toughness", None)
            else:
                obj_power, obj_toughness = power, toughness
            # RULE 613.7b: `abilities` is already timestamp-sorted, so a
            # later effect must be able to *reverse* an earlier one for the
            # same type word (Swift Reconfiguration's Aura removes
            # "creature"; its own granted Crew ability, activated well
            # after, adds "creature" back while crewed — MEC-43 round
            # 4E). `_added_types`/`_removed_types` are read as plain "is
            # this word currently added/removed" sets (`GameObject.
            # is_creature`/`type_words`), so each must hold only the words
            # whose *most recent* operation was that kind — discarding the
            # word from the opposite set is what makes a later add/remove
            # actually override an earlier one instead of the two
            # silently coexisting forever.
            for type_name in added:
                obj._added_types.add(type_name)
                obj._removed_types.discard(type_name)
            for type_name in removed:
                obj._removed_types.add(type_name)
                obj._added_types.discard(type_name)
            for subtype_name in add_subtypes:
                # RULE 613.7: `abilities` is already timestamp-sorted, so an
                # add that runs *after* an overwrite already stamped on this
                # object (Urborg/Yavimaya entering after Blood Moon) has to
                # stack directly onto `_derived_subtypes` — the override
                # `_has_subtype` reads — rather than the now-ignored
                # `_added_subtypes`, or it would silently vanish even though
                # its own timestamp is the newer one. An add that runs
                # *before* any overwrite still goes to `_added_subtypes` and
                # is correctly discarded the moment `set_subtypes` below
                # replaces the set outright.
                if obj._derived_subtypes is not None:
                    obj._derived_subtypes.add(subtype_name)
                else:
                    obj._added_subtypes.add(subtype_name)
            if set_subtypes is not None:
                # RULE 613.5 full overwrite ("Nonbasic lands are Mountains.")
                # — replaces the subtype set outright, unlike `add_types`/
                # `add_subtypes` above (which only *add* alongside whatever
                # the object already was).
                obj._derived_subtypes = set(set_subtypes)
                # RULE 305.7: setting a land's subtype to a *basic* land type
                # also strips its rules text and abilities — a Blood-Moon'd
                # Underground Sea makes only {R}, and a Blood-Moon'd
                # Wasteland can't be activated at all. The intrinsic mana
                # ability of the new (and any later-stacked) basic type comes
                # back from `mana_abilities_for`'s generic RULE 305.6
                # derivation, which reads this same `_derived_subtypes` set
                # once every layer-4 effect above has resolved.
                if obj.is_land and any(
                    str(t).lower() in _BASIC_LAND_TYPES for t in set_subtypes
                ):
                    obj._loses_all_abilities = True
            if obj_power is not None and obj_toughness is not None:
                animation_pt[obj.instance_id] = (obj_power, obj_toughness)
            if ability.params.get("legendary"):
                # RULE 205.4a: "it becomes a legendary creature…" (Tenth
                # District Hero's second level) — the same `_granted_
                # legendary` flag The Ring's "your Ring-bearer is legendary"
                # sets, so the RULE 704.5j legend-rule SBA sees it.
                obj._granted_legendary = True
            label = ", ".join(added + add_subtypes) if (added or add_subtypes) else ", ".join(set_subtypes or [])
            _trace(obj, 4, _source_name(ability), f"becomes {label}")

    # Still layer 4, but off the battlefield (Arcane Adaptation/Ashes of the
    # Fallen) — see `_apply_off_battlefield_types`.
    _apply_off_battlefield_types(state, abilities)

    # Also layer 4 (RULE 205.4/613.2d), but sourced from a *designation*
    # rather than a permanent: RULE 701.51a's Ring emblem, whose first
    # ability reads "Your Ring-bearer is legendary…". There's no permanent
    # to hang a `StaticAbility` on and no `Emblem` object either (the
    # emblem's abilities are fixed by the rules, not quoted from a card), so
    # it's applied here off live player state — the same treatment
    # `extra_land_plays_for`/`has_no_maximum_hand_size` give the other
    # non-permanent-sourced statics.
    _apply_ring_bearer_static(state)

    return animation_pt


def _apply_layer_5_color(state: "GameState", abilities: list) -> None:
    # -- Layer 5: colour-changing effects (RULE 613.4b).
    for ability in _in_layer(abilities, "color"):
        colors = [str(c).upper() for c in ability.params.get("colors", [])]
        replace = bool(ability.params.get("set", True))
        for obj in affected_objects(state, ability):
            if obj._derived_colors is None or replace:
                obj._derived_colors = set() if replace else obj.colors
            obj._derived_colors.update(colors)
            _trace(obj, 5, _source_name(ability), "becomes " + ", ".join(colors))


#: A ``grant_effects`` param value naming the *granting* permanent ("…you may have it fight Grothama") —
#: replaced by that permanent's instance id as the granted effect is built.
GRANTOR_SENTINEL = "$grantor"


def _build_grant_effect(spec: dict, obj: Optional["GameObject"] = None, grantor: Optional["GameObject"] = None) -> Any:
    """One entry of a `grant_triggered_ability`/`grant_activated_ability`'s
    ``grant_effects`` list → a real `GameEffect`.

    An optional ``condition`` key (the same shape `parser.oracle.spec.
    EffectSpec.condition`/`effects.ConditionalEffect` already use for a
    printed ability's own "if `<condition>`, `<effect>`." clause) wraps the
    built effect so a *granted* ability's own body can have one too —
    "…that player loses the game if the Ring has tempted you four or more
    times this game. Otherwise, the Ring tempts you." (Frodo, Sauron's
    Bane) is two of these in the same ``grant_effects`` list, one gated
    ``ring_tempted_at_least``, the other its complementary
    ``ring_tempted_at_most``. Without this, a granted ability could only
    ever be an unconditional list of effects, unlike an ordinary printed
    one.

    ``obj`` (MEC-43 round 4E — Swift Reconfiguration's granted Crew 5,
    the first ``grant_effects`` entry that actually needs it) is stamped
    onto the built effect's own ``.source`` — every printed ability's
    effects get their `.source` from `effect_binder.bind_ability` at bind
    time, but `EffectRegistry.create` alone never sets one, so a granted
    effect that resolves *itself* (e.g. `GrantUntilEffect(target_kind=
    None)`'s "becomes a creature" self-target, or anything reading
    `_controller_of(self.source, ...)`) silently no-opped instead of
    acting on the affected permanent. `Deadeye Navigator`/`Samite
    Blessing`'s own existing ``grant_effects`` (blink/prevent-damage) never
    hit this, since both take their subject from a real RULE 115 target
    instead of ``self.source`` — this was a latent, previously-unreachable
    gap, not a regression.
    """
    params = dict(spec.get("params", {}))
    if grantor is not None:
        params = {k: (grantor.instance_id if v == GRANTOR_SENTINEL else v) for k, v in params.items()}
    effect = EffectRegistry.create(spec["type"], params)
    if obj is not None:
        effect.source = obj
    condition = spec.get("condition")
    if condition:
        effect = ConditionalEffect(dict(condition), effect, source=obj)
    return effect


def _apply_layer_6_ability(state: "GameState", abilities: list) -> None:
    # -- Layer 6: ability-adding effects (keyword / mana / triggered-ability
    # grants — RULE 613.7f). A grant is re-derived every pass exactly like
    # every other layer effect here, so it disappears on its own the moment
    # its source stops applying — no separate removal code (RULE 613.6).
    live_grant_keys: set[tuple[int, int]] = set()
    for ability in _in_layer(abilities, "ability"):
        keywords = ability.params.get("keywords", [])
        #: ENG-31: parametric keyword *grants* — ``[{"name": "firebending",
        #: "n": 2}, ...]``. A number-carrying keyword can't ride the flat
        #: `keywords` slug list; stamped onto `GameObject.
        #: _granted_parametric_keywords` and, where the keyword's RULE 702
        #: text is itself a triggered ability, re-synthesized onto
        #: `_granted_triggered_abilities` every pass.
        parametric_grants = ability.params.get("parametric_keywords", [])
        remove_keywords = ability.params.get("remove_keywords", [])
        lose_all = bool(ability.params.get("lose_all_abilities", False))
        mana = ability.params.get("mana", [])
        mana_restriction = ability.params.get("mana_restriction")
        mana_any_combination = bool(ability.params.get("mana_any_combination", False))
        mana_ability_cost = ability.params.get("mana_ability_cost")
        trigger_event = ability.params.get("trigger_event")
        activated_cost = ability.params.get("activated_cost")
        # RULE 702.16 standing protection grant ("Cats you control have
        # protection from Rats" — Hungry Lynx; "Enchanted creature has
        # protection from the chosen color" — Flickering Ward). The parser
        # front-end can't normalize the quality itself (it must stay free of
        # `game/` imports), so the raw printed words are folded through
        # `combat.protections_of_text`'s own vocabulary here, once per
        # ability rather than once per affected object.
        protections = _protection_qualities(ability, state)
        #: RULE 702.21b's quoted grant sibling of `protections` above —
        #: "Other creatures you control have 'Ward—Pay 2 life.'" (Hexing
        #: Squelcher) — since Ward carries a cost `_flag_keywords` can't
        #: express as a bare keyword slug, it rides `grant_keyword`'s own
        #: ``ward_cost`` param instead of a separate static kind.
        ward_cost = ability.params.get("ward_cost")
        cumulative_upkeep_cost = ability.params.get("cumulative_upkeep_cost")
        graveyard_to_library_replacement = bool(
            ability.params.get("graveyard_to_library_replacement", False)
        )
        if protections and ability.params.get("exempt_own_attachment"):
            # RULE 702.16n/p — a per-*source* flag (the Aura, not its host),
            # since the exemption is about this specific grant not causing
            # its own attachment to fall off, not about the host's
            # protection generally.
            ability.source._protection_self_exempt = True
        for obj in affected_objects(state, ability):
            if lose_all:
                # RULE 613.7f (Humility, Dress Down): strip *every* ability —
                # keywords go via `_obj_keywords`, triggered/activated abilities
                # are gated at fire/activate time on this flag.
                obj._loses_all_abilities = True
                _trace(obj, 6, _source_name(ability), "loses all abilities")
            if keywords:
                obj._granted_keywords.update(keywords)
                _trace(obj, 6, _source_name(ability), "gains " + ", ".join(keywords))
            for pk in parametric_grants:
                pname = str(pk.get("name") or "")
                pn = pk.get("n")
                if not pname or pn is None:
                    continue
                obj._granted_parametric_keywords[pname] = int(pn)
                _trace(obj, 6, _source_name(ability), f"gains {pname} {int(pn)}")
                # ``int(pn)`` in the key so a changed amount (a dynamic grant)
                # mints a fresh ability and the stale one is pruned below.
                key = (id(ability), obj.instance_id, "parametric", pname, int(pn))
                live_grant_keys.add(key)
                built = state._granted_ability_cache.get(key)
                if built is None:
                    from .binding.core import parametric_keyword_triggered_abilities  # local: avoid an import cycle

                    built = parametric_keyword_triggered_abilities(obj, pname, int(pn))
                    state._granted_ability_cache[key] = built
                obj._granted_triggered_abilities.extend(built)
            if remove_keywords:
                obj._removed_keywords.update(remove_keywords)
                _trace(obj, 6, _source_name(ability), "loses " + ", ".join(remove_keywords))
            if protections:
                obj._granted_protections.update(protections)
                _trace(obj, 6, _source_name(ability),
                       "gains protection from " + ", ".join(sorted(protections)))
            if ward_cost:
                obj.granted_ward_cost = ward_cost
                _trace(obj, 6, _source_name(ability), f"gains Ward—{ward_cost}")
            if cumulative_upkeep_cost:
                key = (id(ability), obj.instance_id, "cumulative_upkeep", str(cumulative_upkeep_cost))
                live_grant_keys.add(key)
                built = state._granted_ability_cache.get(key)
                if built is None:
                    from ..parser.oracle.spec import AbilitySpec
                    from .binding.core import _kw_cumulative_upkeep

                    spec = AbilitySpec(
                        "keyword",
                        keyword={"name": "cumulative_upkeep", "cost": str(cumulative_upkeep_cost)},
                    )
                    built = _kw_cumulative_upkeep(obj, spec, None)
                    state._granted_ability_cache[key] = built
                obj._granted_triggered_abilities.extend(built)
                _trace(obj, 6, _source_name(ability), "gains cumulative upkeep")
            if graveyard_to_library_replacement:
                obj._graveyard_to_library_replacement = True
                _trace(obj, 6, _source_name(ability), "replaces graveyard move with library top")
            if mana and mana_ability_cost:
                # MEC-25 upgrade shape — not a bare ``{T}``, so it replaces a
                # matching printed ability instead of stacking a second one
                # alongside it (`mana_abilities.mana_abilities_for`).
                obj._granted_mana_upgrades.append(
                    {"cost": parse_activation_cost(dict(mana_ability_cost)), "options": [dict(o) for o in mana]}
                )
                _trace(obj, 6, _source_name(ability), "gains an upgraded mana ability")
            elif mana:
                granted_mana_cost = ability.params.get("granted_mana_cost")
                if mana_restriction or mana_any_combination or granted_mana_cost:
                    obj._granted_mana_abilities.append({
                        "options": [dict(option) for option in mana],
                        "restriction": dict(mana_restriction) if mana_restriction else None,
                        "any_combination": mana_any_combination,
                        "cost": granted_mana_cost,
                    })
                else:
                    obj._granted_mana.extend(mana)
                _trace(obj, 6, _source_name(ability), "gains a mana ability")
            if trigger_event:
                key = (id(ability), obj.instance_id)
                live_grant_keys.add(key)
                granted = state._granted_ability_cache.get(key)
                if granted is None:
                    group_condition = ability.params.get("group_condition")
                    if ability.params.get("contributors"):
                        from .binding.core import _contributor_condition

                        cond = _contributor_condition({
                            "event": trigger_event,
                            "condition": group_condition or {"subject": "you"},
                            "contributors": ability.params["contributors"],
                        }, obj)
                    elif group_condition:
                        # PAR-32: "X have 'Whenever an artifact or creature
                        # you control dies, …'" (Agent of the Iron Throne).
                        # Reuse `effect_binder`'s printed-trigger group
                        # predicate, sourced on the *granted-to* permanent
                        # so "you control"/"other" re-scope to it.
                        from .binding.core import _build_group_ok  # local: avoid an import cycle

                        cond = _build_group_ok(
                            group_condition, obj, {"event": trigger_event}, obj.instance_id
                        )
                    else:
                        cond = _granted_trigger_condition(
                            obj, bool(ability.params.get("controllers_turn_only", False)),
                            trigger_event, ability.params.get("filter"),
                            ability.params.get("phase_relation"),
                        )
                    # PAR-32: AND any firing-event gate flags the re-granted
                    # trigger carried ("no opponent has more life than that
                    # player" — Guild Artisan; "cast a spell from exile" —
                    # Passionate Archaeologist; a phase trigger's RULE 603.4
                    # intervening-if — Cloakwood Hermit), each scoped to the
                    # granted-to permanent's controller.
                    from .binding.core import (
                        regrant_active_if_predicate,
                        regrant_trigger_gate_predicate,
                    )

                    _gates = [
                        regrant_trigger_gate_predicate(
                            _k, obj.controller_id, obj, ability.params.get(_k)
                        )
                        for _k in ("attacked_player_has_lowest_life", "spell_from_exile",
                                   "spell_shares_creature_type_with_source", "spell_exclude_card_types",
                                   "spell_filter", "spell_cast_from",
                                   "recipient_relation", "recipient_filter")
                        if ability.params.get(_k)
                    ]
                    if isinstance(ability.params.get("active_if"), dict):
                        _gates.append(
                            regrant_active_if_predicate(ability.params["active_if"], obj)
                        )
                    for _gate in _gates:
                        if _gate is None:
                            continue
                        _base_cond = cond

                        def cond(event, context, _b=_base_cond, _g=_gate):  # noqa: F811
                            return _b(event, context) and _g(event, context)
                    granted = TriggeredAbility(
                        trigger_event=trigger_event,
                        effects=[
                            _build_grant_effect(spec, obj, grantor=ability.source)
                            for spec in ability.params.get("grant_effects", [])
                        ],
                        condition=cond,
                        optional=bool(ability.params.get("optional", False)),
                        once_per_turn=bool(ability.params.get("once_per_turn", False)),
                        controller_id=obj.controller_id,
                        source=obj,
                        description=ability.description or "granted triggered ability",
                    )
                    state._granted_ability_cache[key] = granted
                else:
                    # `obj.controller_id` can change turn to turn (a control-
                    # changing effect, layer 2, resolves earlier this same
                    # pass) — keep the cached instance's controller current.
                    granted.controller_id = obj.controller_id
                obj._granted_triggered_abilities.append(granted)
                _trace(obj, 6, _source_name(ability), "gains a triggered ability")
            if activated_cost:
                # "<host> has '{cost}: <effect>.'" (Umbral Mantle/Squirrel
                # Nest-shaped) — the activated-ability sibling of the
                # trigger_event branch above, same cache/dedup shape. A
                # 3-element key (vs. the 2-element one above) so the two
                # grant kinds never collide sharing one cache dict, even
                # though nothing in this codebase currently grants both off
                # the same StaticAbility.
                key = (id(ability), obj.instance_id, "activated")
                live_grant_keys.add(key)
                granted_activated = state._granted_ability_cache.get(key)
                if granted_activated is None:
                    cost_dict = dict(activated_cost)
                    if cost_dict.pop("unattach_grant_source", False):
                        grant_source = getattr(ability, "source", None)
                        if grant_source is not None:
                            cost_dict["unattach_grant_source_id"] = grant_source.instance_id
                    cost = parse_activation_cost(cost_dict)
                    cost.sorcery_speed_only = bool(ability.params.get("sorcery_speed_only", False))
                    granted_activated = ActivatedAbility(
                        effects=[
                            _build_grant_effect(spec, obj)
                            for spec in ability.params.get("grant_effects", [])
                        ],
                        cost=cost,
                        source=obj,
                        description=ability.description or "granted activated ability",
                        once_per_turn=bool(ability.params.get("once_per_turn", False)),
                    )
                    state._granted_ability_cache[key] = granted_activated
                obj._granted_activated_abilities.append(granted_activated)
                _trace(obj, 6, _source_name(ability), "gains an activated ability")
            static_specs = ability.params.get("static_specs")
            if static_specs:
                # MEC-55: "X have '<static ability>'" (Inspiring Leader) —
                # build the nested static once per affected object, sourced
                # on that object so its own "you control" selector resolves
                # against the granted-to permanent's controller. Cached on
                # `_granted_ability_cache` (identity-stable across passes)
                # and yielded by `_battlefield_static_abilities`.
                for i, spec in enumerate(static_specs):
                    key = (id(ability), obj.instance_id, "static", i)
                    live_grant_keys.add(key)
                    granted_static = state._granted_ability_cache.get(key)
                    if granted_static is None:
                        # MEC-57: the nested spec's ``type`` can also name a
                        # `ReplacementEffect` (Scion of Halaster's granted
                        # "first draw each turn" rewrite) rather than a
                        # `StaticAbility` — `EffectRegistry` stays the
                        # primary lookup (every existing static_specs user:
                        # anthem/grant_keyword/extra_etb_counter/…),
                        # `ReplacementRegistry` a fallback for the shapes
                        # that only ever exist as a granted replacement.
                        if EffectRegistry.is_registered(spec["type"]):
                            granted_static = EffectRegistry.create(
                                spec["type"], dict(spec.get("params", {}))
                            )
                        else:
                            granted_static = ReplacementRegistry.create(
                                spec["type"], dict(spec.get("params", {}))
                            )
                        granted_static.source = obj
                        state._granted_ability_cache[key] = granted_static
                    if isinstance(granted_static, ReplacementEffect):
                        obj._granted_replacement_effects.append(granted_static)
                    else:
                        obj._granted_static_abilities.append(granted_static)
                _trace(obj, 6, _source_name(ability), "gains a static ability")

    # ENG-31: "until end of turn" parametric keyword grants from a resolved
    # effect ("target creature gains firebending N until end of turn" — Fire
    # Nation Palace). The parametric sibling of the `temp_keywords` merge
    # below; folded in here (before the prune) so its synthesized abilities
    # share the same `_granted_ability_cache` identity-preservation. Cleared
    # at cleanup (RULE 514.2) with `temp_keywords`.
    for obj in state.battlefield:
        for pname, pn in (obj.temp_parametric_keywords or {}).items():
            if pn is None:
                continue
            obj._granted_parametric_keywords[pname] = int(pn)
            key = (id(obj), obj.instance_id, "parametric_temp", pname, int(pn))
            live_grant_keys.add(key)
            built = state._granted_ability_cache.get(key)
            if built is None:
                from .binding.core import parametric_keyword_triggered_abilities  # local: avoid an import cycle

                built = parametric_keyword_triggered_abilities(obj, pname, int(pn))
                state._granted_ability_cache[key] = built
            obj._granted_triggered_abilities.extend(built)
            _trace(obj, 6, "Until-EOT", f"gains {pname} {int(pn)}", duration="end_of_turn")

    # Prune cache entries for relationships that no longer hold (the granting
    # ability left, or this object is no longer among its `affects`) — so a
    # later re-grant starts a fresh instance (fresh "once per turn" state),
    # rather than resurrecting old turn-tracking from an unrelated stretch of
    # the game.
    for key in list(state._granted_ability_cache):
        if key not in live_grant_keys:
            del state._granted_ability_cache[key]

    # Temporary "until end of turn" keyword grants from a resolved effect
    # ("target creature gains flying until end of turn") — same layer 6, but
    # sourced off the object rather than a battlefield static ability. Cleared
    # at cleanup (RULE 514.2).
    for obj in state.battlefield:
        if obj.temp_keywords:
            obj._granted_keywords.update(obj.temp_keywords)
            # Attribute each keyword to its source spell/ability where the
            # resolved effect recorded one (`temp_effects`); keywords granted
            # by paths that don't (haste/first-strike/indestructible helpers)
            # fall through to a single generic "Until-EOT" line.
            attributed: set[str] = set()
            for entry in obj.temp_effects:
                kws = entry.get("keywords") or []
                if kws:
                    attributed.update(kws)
                    _trace(obj, 6, entry.get("source") or "Until-EOT",
                           "gains " + ", ".join(sorted(kws)), duration="end_of_turn")
            residual = obj.temp_keywords - attributed
            if residual:
                _trace(obj, 6, "Until-EOT", "gains " + ", ".join(sorted(residual)),
                       duration="end_of_turn")
        if obj.temp_removed_keywords:
            obj._removed_keywords.update(obj.temp_removed_keywords)
            attributed_removed: set[str] = set()
            for entry in obj.temp_effects:
                removed = entry.get("removed_keywords") or []
                if removed:
                    attributed_removed.update(removed)
                    _trace(
                        obj, 6, entry.get("source") or "Until-EOT",
                        "loses " + ", ".join(sorted(removed)), duration="end_of_turn",
                    )
            residual_removed = obj.temp_removed_keywords - attributed_removed
            if residual_removed:
                _trace(
                    obj, 6, "Until-EOT",
                    "loses " + ", ".join(sorted(residual_removed)), duration="end_of_turn",
                )
        # MEC-98: perpetual keyword grants — same layer, never cleared.
        if obj.perpetual_keywords:
            obj._granted_keywords.update(obj.perpetual_keywords)
            _trace(obj, 6, "Perpetual", "gains " + ", ".join(sorted(obj.perpetual_keywords)),
                   duration="permanent")

    # RULE 122.1b / 613.1f: a keyword counter ("flying", "first strike", …)
    # makes its permanent gain that keyword — layer 6, re-derived every pass
    # from `obj.counters`, so removing the last counter takes the keyword
    # straight back off (no separate cleanup).
    for obj in state.battlefield:
        counters = obj.counters
        if not counters:
            continue
        counted = sorted(
            kind for kind in KEYWORD_COUNTER_SLUGS if int(counters.get(kind, 0) or 0) > 0
        )
        if counted:
            obj._granted_keywords.update(KEYWORD_COUNTER_SLUGS[kind] for kind in counted)
            _trace(obj, 6, "Keyword counter", "gains " + ", ".join(counted), duration="permanent")

    # Still layer 6, but reaching *hand* cards rather than battlefield
    # permanents (PAR-8) — see `_apply_hand_cycling_grants`.
    _apply_hand_cycling_grants(state, abilities)


def _apply_hand_cycling_grants(state: "GameState", abilities: list[StaticAbility]) -> None:
    """RULE 702.28 Cycling granted onto cards in hand ("Each historic card
    in your hand has cycling {2}{W}." — Jo Grant/Rhet-Tomb Mystic/Tectonic
    Reformation), a layer-6 ability grant whose *targets* are hand cards — a
    zone `affected_objects`/`group_selector_objects` never reach (RULE 613
    selectors are all battlefield-scoped). Mirrors `_apply_off_battlefield_
    types`'s "track what was stamped last pass, clear it, re-derive" shape,
    and the ordinary layer-6 ``activated_cost`` grant's `state.
    _granted_ability_cache` identity-preservation (a fresh `ActivatedAbility`
    instance every recompute would be harmless today — Cycling carries no
    per-instance state — but keeping the same shape as every other grant in
    this layer costs nothing and avoids a future footgun if one ever does).

    ``card_type`` is an optional printed-type filter (`_has_card_type`'s
    vocabulary) or ``"historic"`` (CR glossary: legendary, an artifact, or a
    Saga) — ``None`` grants to every card in hand, the ticket's own "Each
    card in your hand has cycling {2}" example.
    """
    previous = getattr(state, "_hand_cycling_granted", None) or []
    for obj in previous:
        obj._granted_activated_abilities = [
            a for a in obj._granted_activated_abilities
            if not getattr(a, "_hand_cycling_grant", False)
        ]
    stamped: list[Any] = []
    live_keys: set[tuple[int, int]] = set()

    for ability in _in_layer(abilities, "ability"):
        cost_text = ability.params.get("grant_cycling_cost")
        if not cost_text:
            continue
        controller_id = getattr(ability.source, "controller_id", None)
        player = next((p for p in state.players if p.id == controller_id), None)
        if player is None:
            continue
        card_type = ability.params.get("card_type")
        for obj in list(player.hand):
            if card_type and not _hand_card_matches_type(obj, card_type):
                continue
            key = (id(ability), obj.instance_id)
            live_keys.add(key)
            granted = state._hand_cycling_ability_cache.get(key)
            if granted is None:
                granted = ActivatedAbility(
                    effects=[EffectRegistry.create("draw", {"count": 1})],
                    cost=parse_activation_cost(f"{cost_text}, Discard this card"),
                    source=obj,
                    description=f"Cycling {cost_text}",
                )
                granted._hand_cycling_grant = True
                state._hand_cycling_ability_cache[key] = granted
            obj._granted_activated_abilities.append(granted)
            _trace(obj, 6, _source_name(ability), f"gains cycling {cost_text}")
            stamped.append(obj)

    for key in list(state._hand_cycling_ability_cache):
        if key not in live_keys:
            del state._hand_cycling_ability_cache[key]

    state._hand_cycling_granted = stamped


def _hand_card_matches_type(obj: "GameObject", card_type: str) -> bool:
    """RULE-glossary "historic" (legendary, an artifact, or a Saga), or an
    ordinary `_has_card_type` printed-type filter for everything else."""
    if card_type == "historic":
        return bool(
            getattr(obj.card, "is_legendary", False)
            or getattr(obj.card, "is_artifact", False)
            or "saga" in (getattr(obj.card, "type_line", "") or "").lower()
        )
    return _has_card_type(obj, card_type)


def _apply_layer_7_pt(
    state: "GameState", abilities: list, animation_pt: dict[int, tuple[int, int]]
) -> None:
    # -- Layer 7: power/toughness, on working base values so the sublayers
    # apply in order (7a CDA → 7b set → 7c counters → 7d modify → 7e switch).
    base: dict[int, list[int]] = {}
    for obj in state.battlefield:
        if not obj.is_creature:
            continue
        if obj.instance_id in animation_pt:
            base[obj.instance_id] = list(animation_pt[obj.instance_id])
        else:
            base[obj.instance_id] = [obj.card.power or 0, obj.card.toughness or 0]

    # 7a: characteristic-defining P/T ("power/toughness equal to the number of …").
    for ability in _in_layer(abilities, "pt_cda"):
        p_sel = ability.params.get("power_count")
        t_sel = ability.params.get("toughness_count")
        for obj in affected_objects(state, ability):
            if obj.instance_id not in base:
                continue
            if p_sel:
                base[obj.instance_id][0] = _count_selector(state, ability, p_sel)
            if t_sel:
                base[obj.instance_id][1] = _count_selector(state, ability, t_sel)
            p, t = base[obj.instance_id]
            _trace(obj, 7, _source_name(ability), f"defined as {p}/{t}", p, t)

    # 7b: set power/toughness to a specific value. ``power``/``toughness`` of
    # ``None`` leaves that half at its layer-7a value — "Exchange target
    # opponent's life total with ~'s toughness." (Tree of Perdition) sets
    # only the toughness.
    for ability in _in_layer(abilities, "pt_set"):
        power = ability.params.get("power", 0)
        toughness = ability.params.get("toughness", 0)
        # "…have base power and toughness X/X, where X is the number of cards in your hand" (Jolrael): a
        # `count_selector` read live on every pass, so it follows the count as it changes.
        if ability.params.get("power_count"):
            power = _count_selector(state, ability, ability.params["power_count"])
        if ability.params.get("toughness_count"):
            toughness = _count_selector(state, ability, ability.params["toughness_count"])
        for obj in affected_objects(state, ability):
            if obj.instance_id in base:
                new_p = base[obj.instance_id][0] if power is None else power
                new_t = base[obj.instance_id][1] if toughness is None else toughness
                base[obj.instance_id] = [new_p, new_t]
                _trace(obj, 7, _source_name(ability), f"set to {new_p}/{new_t}", new_p, new_t)

    # Base P/T includes layer 7a/7b, before counters and modifiers (RULE 613.4).
    for obj in state.battlefield:
        if obj.instance_id in base:
            obj._base_power, obj._base_toughness = base[obj.instance_id]

    # 7c: counters (RULE 613.7 counters sublayer / 122).
    for obj in state.battlefield:
        if obj.instance_id in base:
            counters = obj.plus_one_counters
            if counters:
                base[obj.instance_id][0] += counters
                base[obj.instance_id][1] += counters
                p, t = base[obj.instance_id]
                _trace(obj, 7, "+1/+1-Marken", f"{_signed(counters)}/{_signed(counters)}",
                       p, t, duration="permanent")
            # RULE 122.1a: any other "+a/+b" counter ("+0/+1" — Coral Reef, Shield Sphere;
            # "-0/-2" — Spirit Shackle) is its own kind, each one worth its printed delta.
            for kind, amount in obj.counters.items():
                pt_delta = _PT_COUNTER_KIND_RE.fullmatch(kind)
                if pt_delta is None or kind in ("+1/+1", "-1/-1") or amount <= 0:
                    continue
                d_power, d_toughness = int(pt_delta.group(1)) * amount, int(pt_delta.group(2)) * amount
                base[obj.instance_id][0] += d_power
                base[obj.instance_id][1] += d_toughness
                p, t = base[obj.instance_id]
                _trace(obj, 7, f"{kind}-Marken", f"{_signed(d_power)}/{_signed(d_toughness)}",
                       p, t, duration="permanent")

    # 7d: modify (but don't set) power/toughness — anthems, including a
    # per-count anthem ("+1/+1 for each land you control", Blackblade
    # Reforged/Nettlecyst; "+2/+0 for each Equipment attached to it", Bruenor
    # Battlehammer) — `power`/`toughness` become the *per-unit* amount when
    # `power_count`/`toughness_count` is set, multiplied by that count
    # instead of added as a flat delta.
    for ability in _in_layer(abilities, "pt_mod"):
        d_power = ability.params.get("power", 0)
        d_toughness = ability.params.get("toughness", 0)
        p_sel = ability.params.get("power_count")
        t_sel = ability.params.get("toughness_count")
        for obj in affected_objects(state, ability):
            if obj.instance_id in base:
                power = d_power * _pt_mod_count(state, ability, obj, p_sel) if p_sel else d_power
                toughness = (
                    d_toughness * _pt_mod_count(state, ability, obj, t_sel) if t_sel else d_toughness
                )
                base[obj.instance_id][0] += power
                base[obj.instance_id][1] += toughness
                p, t = base[obj.instance_id]
                _trace(obj, 7, _source_name(ability), f"{_signed(power)}/{_signed(toughness)}", p, t)

    # 7d (cont.): temporary "until end of turn" P/T bonuses from a resolved
    # pump effect (Giant Growth) — same sublayer as anthems (RULE 613.4d);
    # addition commutes so within-layer order doesn't change the result.
    # Sourced off the object; cleared at cleanup (RULE 514.2).
    for obj in state.battlefield:
        if obj.instance_id not in base or not (obj.temp_power or obj.temp_toughness):
            continue
        # Attribute the bonus to each source that recorded one; addition
        # commutes, so applying them one at a time gives the same total while
        # the trace can name Giant Growth / Monstrous Rage individually.
        pt_entries = [e for e in obj.temp_effects if e.get("power") or e.get("toughness")]
        for entry in pt_entries:
            ep, et = entry.get("power", 0), entry.get("toughness", 0)
            base[obj.instance_id][0] += ep
            base[obj.instance_id][1] += et
            p, t = base[obj.instance_id]
            _trace(obj, 7, entry.get("source") or "Until-EOT",
                   f"{_signed(ep)}/{_signed(et)}", p, t, duration="end_of_turn")
        # Any bonus from a path that didn't record a source (older effects)
        # still shows, as one generic residual line.
        residual_p = obj.temp_power - sum(e.get("power", 0) for e in pt_entries)
        residual_t = obj.temp_toughness - sum(e.get("toughness", 0) for e in pt_entries)
        if residual_p or residual_t:
            base[obj.instance_id][0] += residual_p
            base[obj.instance_id][1] += residual_t
            p, t = base[obj.instance_id]
            _trace(obj, 7, "Until-EOT",
                   f"{_signed(residual_p)}/{_signed(residual_t)}", p, t, duration="end_of_turn")

    # 7d (cont.): MEC-98 Alchemy *perpetual* P/T changes — same sublayer as a
    # resolved pump, but never cleared (see `GameObject.perpetual_power`).
    for obj in state.battlefield:
        if obj.instance_id not in base or not (obj.perpetual_power or obj.perpetual_toughness):
            continue
        base[obj.instance_id][0] += obj.perpetual_power
        base[obj.instance_id][1] += obj.perpetual_toughness
        p, t = base[obj.instance_id]
        sources = sorted({e.get("source") or "Perpetual" for e in obj.perpetual_effects
                          if e.get("power") or e.get("toughness")}) or ["Perpetual"]
        _trace(obj, 7, ", ".join(sources),
               f"{_signed(obj.perpetual_power)}/{_signed(obj.perpetual_toughness)}", p, t,
               duration="permanent")

    # 7e: switch power and toughness (RULE 613.7e / 701.28). Applied last, so it
    # swaps the fully-computed values.
    for ability in _in_layer(abilities, "pt_switch"):
        for obj in affected_objects(state, ability):
            if obj.instance_id in base:
                base[obj.instance_id].reverse()
                p, t = base[obj.instance_id]
                _trace(obj, 7, _source_name(ability), f"switched to {p}/{t}", p, t)

    # A *resolving* one-shot switch (Twisted Image-shaped — PAR-81), as
    # opposed to a granted/printed static ability above: applied after
    # every static `pt_switch`, same coarser "until end of turn residual"
    # timestamp treatment `temp_power`/`temp_toughness` already accepts a
    # few lines up. Two independent switches on one object still correctly
    # cancel out either way.
    for obj in state.battlefield:
        if obj.instance_id in base and getattr(obj, "temp_pt_switch_count", 0) % 2 == 1:
            base[obj.instance_id].reverse()
            p, t = base[obj.instance_id]
            _trace(obj, 7, "Until-EOT", f"switched to {p}/{t}", p, t, duration="end_of_turn")

    for obj in state.battlefield:
        if obj.instance_id in base:
            obj._derived_power, obj._derived_toughness = base[obj.instance_id]


def _apply_post_layer_combat_restrictions_and_goad(state: "GameState", abilities: list) -> None:
    # -- Not a RULE 613 layer: parameterized combat restrictions (RULE
    # 508.1a/509.1b). "~ can't be blocked by creatures with power 2 or less",
    # "can't attack unless defending player controls an Island", "can't
    # attack alone" — none of these change a *characteristic*, so there's
    # nothing to fold into a layer; they're stamped onto the affected objects
    # here (re-derived every pass, so they follow their source in and out of
    # play exactly like `_granted_protections` does) and read at combat time
    # by `GameEngine._can_attack`/`can_block`/`declare_blockers`, which are
    # the only places that know who's defending and who else is attacking.
    # Deliberately placed *after* the layer-7 P/T pass above (unlike every
    # other bucket in this function, stamped inline with its RULE 613 layer):
    # a scope qualifier ("each creature you control **with power 4 or
    # greater**…", `group_selector_objects`'s ``min_power``/``max_power``) has
    # to see this same pass's anthems, not last pass's stale derived P/T.
    for ability in _in_layer(abilities, "combat_restriction"):
        # Only the restriction's own keys — ``affects``/``subtype``/``color``/
        # ``card_type``/``min_power``/``max_power``/… in the same params dict
        # belong to the *selector* (which objects this applies to) and would
        # be read as a blocker filter if they leaked through.
        entry = {
            k: ability.params[k]
            for k in ("kind", "filter", "count", "condition", "defender_kind")
            if ability.params.get(k) is not None
        }
        for obj in affected_objects(state, ability):
            obj._combat_restrictions.append(dict(entry))
            # A *string* layer label, not a number: this bucket isn't a RULE
            # 613 layer at all, so the board shows the word rather than a
            # meaningless "L99" (see `gameBoardView.js`'s trace renderer).
            _trace(obj, "Kampf", _source_name(ability), _describe_combat_restriction(entry))

    # -- Also not a RULE 613 layer: the RULE 701.15b **goad** designation
    # granted by a standing static ("Enchanted creature gets +2/+2 and is
    # goaded", Acquired Mutation; "Creatures your opponents control with
    # power less than ~'s power are goaded", Baeloth Barrityl). Goaded is
    # explicitly *not* an ability and not a copiable value (701.15b), so it
    # can't be a layer-6 grant; it's stamped here for the same reason a
    # combat restriction is, and read at combat time by `combat.goaders`
    # alongside the sticky, resolve-time `GameObject.goaded_by`.
    #
    # Placed after the P/T pass with the restrictions above, and for the same
    # reason: Baeloth's scope is a power comparison, so it must see this
    # pass's anthems. The goader is the *static's* controller — that is who
    # 701.15b says the creature must then attack around.
    for ability in _in_layer(abilities, "goaded"):
        goader_id = getattr(ability.source, "controller_id", None)
        if goader_id is None:
            continue
        for obj in affected_objects(state, ability):
            obj._goaded_by_static.add(goader_id)
            _trace(obj, "Kampf", _source_name(ability), "wird aufgestachelt (goaded)")


def _apply_borrowed_activated_abilities(state: "GameState", abilities: list) -> None:
    """"Creatures you control with +1/+1 counters on them have all activated
    abilities of all creature cards exiled with ~." (MEC-21, Agatha's Soul
    Cauldron) — layer 6, but the granted-ability *set* is read live off the
    board rather than fixed at parse time, so it can't reuse
    `_apply_layer_6_ability`'s own ``activated_cost`` branch (one fixed
    ability per static). ``ability.source.exiled_with_ids`` (`ExileEffect`'s
    generalized ``track_exiled_with`` — see its docstring) names every card
    ever exiled "with" this static's own source; each id is re-resolved
    fresh every pass (`GameState.find_object`), dropping anything gone or no
    longer actually sitting in exile (recurred to hand, cast, …) — the same
    "a dead reference is harmless, just re-check it" contract
    `mana_abilities.resolve_options`'s ``imprinted_card_colors`` reader uses
    for the singular `linked_exile_id` sibling, just zone-checked too, since
    unlike an Imprint permission a *borrowed ability* would otherwise still
    apply after the source card left exile for hand/battlefield.

    Each borrowed ability is a fresh `ActivatedAbility` per (grantee, exiled
    card, ability index): same cost/effects the exiled card's own printed
    ability bound at bind-on-load, but with every nested effect's `.source`
    redirected to the *grantee* rather than the exiled card (RULE 113.7c:
    "Any ability that a permanent gains by another spell/ability applies to
    that permanent, not to the object that granted it") via a shallow
    `copy.copy` per effect — `GameEffect` subclasses hold no per-instance
    mutable state beyond `.source`, so this is safe and cheap. Cached in
    `GameState._borrowed_ability_cache` (its own dict — see that field's
    docstring for why) so a borrowed ability's "once per turn" state
    survives across passes for as long as the (grantee, exiled card)
    relationship holds, the same per-relationship identity-preservation
    `_apply_layer_6_ability`'s own grants already rely on.

    ``source_mode`` (MEC-26) picks *which* permanents are the donors —
    `exiled_with_ids` above is only the ``"exiled_with"`` case (the
    default); ``"group"`` reads a live `affects` selector straight off the
    battlefield (``source_affects``, e.g. Drana and Linvala's "all
    creatures your opponents control") and ``"chosen_permanent"`` reads the
    single donor named by the grantee's own `GameObject.chosen_permanent_id`
    (Scheming Fence). Both skip the ``exile``-zone check ``exiled_with``
    needs, since a group/chosen donor is a live battlefield permanent, not
    a card that may or may not still be sitting in exile.
    """
    live_keys: set[tuple[int, int, int, int]] = set()
    for ability in _in_layer(abilities, "borrowed_activated_ability"):
        source = ability.source
        creature_only = bool(ability.params.get("creature_only", True))
        exclude_loyalty = bool(ability.params.get("exclude_loyalty", False))
        source_mode = ability.params.get("source_mode", "exiled_with")
        donors: list["GameObject"] = []
        if source_mode == "exiled_with":
            exiled_ids = getattr(source, "exiled_with_ids", None) or []
            for iid in exiled_ids:
                card_obj = state.find_object(iid)
                if card_obj is None or getattr(card_obj, "zone", None) != "exile":
                    continue
                if creature_only and not getattr(card_obj.card, "is_creature", False):
                    continue
                donors.append(card_obj)
        elif source_mode == "group":
            controller_id = getattr(source, "controller_id", None)
            donors = group_selector_objects(
                state, controller_id, str(ability.params.get("source_affects", "")), src=source,
            )
            if creature_only:
                donors = [d for d in donors if d.is_creature]
        elif source_mode == "chosen_permanent":
            donors = affected_objects(
                state,
                StaticAbility("ability", affects="chosen_permanent", source=source),
            )
            if creature_only:
                donors = [d for d in donors if d.is_creature]
        elif source_mode == "top_of_library":
            # "As long as the top card of your library is a Goblin card, ~
            # has all activated abilities of that card." (Conspicuous
            # Snoop, MEC-43) — a library card is never boarded/bound the
            # way a battlefield/exile/graveyard donor already is, so a
            # scratch, off-zone `GameObject` is built and bound purely to
            # read its `.activated_abilities`; never added to any zone or
            # `state` list, and rebuilt fresh every pass (a fresh
            # `instance_id` each time, unlike every other donor here) — an
            # accepted simplification that loses a borrowed ability's own
            # "once per turn" state across passes, not worth a persistent
            # cache slot for one card.
            controller_id = getattr(source, "controller_id", None)
            player = next((p for p in state.players if p.id == controller_id), None)
            top_card = player.library[-1].card if player and player.library else None
            if top_card is not None:
                from .binding.core import bind_from_catalogue  # local: avoid an import cycle
                from ..models.game.game_object import GameObject as _GameObject

                scratch = _GameObject(top_card, owner_id=controller_id, controller_id=controller_id)
                bind_from_catalogue(scratch)
                donor_subtype = ability.params.get("donor_subtype")
                if not donor_subtype or has_subtype(scratch, str(donor_subtype)):
                    donors = [scratch]
        elif source_mode == "all_graveyards":
            # "~ has all activated abilities of all creature cards in all
            # graveyards." (Necrotic Ooze-shaped, MEC-12) — every player's
            # graveyard is a live, always-current zone list (unlike
            # ``exiled_with``'s snapshot of ids that may have moved on), so
            # this reads straight off `Player.graveyard` with no staleness
            # check needed. ``creature_only`` is always effectively True
            # here (only a creature card ever has activated abilities worth
            # borrowing this way), but the flag is still honoured for
            # consistency with the other two modes.
            for player in state.players:
                donors.extend(player.graveyard)
            if creature_only:
                donors = [d for d in donors if d.card.is_creature]
        if not donors:
            continue
        for obj in affected_objects(state, ability):
            for donor in donors:
                if donor is obj:
                    # A donor never lends its own abilities back to itself —
                    # relevant only for "group"/"chosen_permanent" modes,
                    # since an exiled card can't also be the battlefield
                    # grantee at the same time.
                    continue
                # RULE 605.1: mana abilities are activated abilities too.
                # Preserve their entire cost/production definition and evaluate
                # self-references against the grantee when it is activated.
                from copy import deepcopy
                from .mana_abilities import parse_mana_abilities
                obj._borrowed_mana_abilities.extend(deepcopy(parse_mana_abilities(donor.card)))
                for idx, base in enumerate(donor.activated_abilities):
                    if exclude_loyalty and base.cost is not None and base.cost.is_loyalty:
                        continue
                    key = (id(ability), obj.instance_id, donor.instance_id, idx)
                    live_keys.add(key)
                    granted = state._borrowed_ability_cache.get(key)
                    if granted is None:
                        granted = ActivatedAbility(
                            effects=[_retarget_effect_source(e, obj) for e in base.effects],
                            cost=base.cost,
                            source=obj,
                            description=base.description,
                            once_per_turn=base.once_per_turn,
                        )
                        state._borrowed_ability_cache[key] = granted
                    obj._granted_activated_abilities.append(granted)
                    _trace(obj, 6, _source_name(ability), f"gains {donor.name}'s activated ability")
    for key in list(state._borrowed_ability_cache):
        if key not in live_keys:
            del state._borrowed_ability_cache[key]


def _retarget_effect_source(effect: Any, new_source: "GameObject") -> Any:
    """A shallow copy of ``effect`` with `.source` redirected to
    ``new_source`` — see `_apply_borrowed_activated_abilities`."""
    retargeted = copy.copy(effect)
    retargeted.source = new_source
    return retargeted


def recompute(state: "GameState") -> None:
    """Re-derive every battlefield permanent's characteristics (RULE 613)."""
    # Restore any controller a prior layer-2 pass changed, so this pass
    # re-applies control effects from a clean base (RULE 613.2, idempotent).
    for obj in state.battlefield:
        if obj._control_base is not None:
            obj.controller_id = obj._control_base
            obj._control_base = None
        obj.reset_derived()

    # -- Layer 1: copy effects (RULE 707) — must run before `abilities` is
    # gathered below, so a permanent that just became a copy has its freshly
    # rebound abilities picked up by every other layer in this same pass.
    _apply_copy_layer(state)

    abilities = [ab for ab in _battlefield_static_abilities(state) if ab.layer != "cost"]
    _apply_layer_2_control(state, abilities)
    _apply_layer_3_text(state, abilities)
    animation_pt = _apply_layer_4_type(state, abilities)
    _apply_layer_5_color(state, abilities)
    _apply_layer_6_ability(state, abilities)
    _apply_borrowed_activated_abilities(state, abilities)
    # MEC-55: layer 6 may have populated `_granted_static_abilities` on
    # affected objects ("X have '<anthem/lord>'" — Inspiring Leader). Re-
    # gather so those nested statics reach layers 7+ in this same pass; an
    # ability-*layer* granted static (a granted keyword/lord) still settles
    # on the next recompute (always ≤1 SBA-loop lag).
    if any(getattr(o, "_granted_static_abilities", None) for o in state.battlefield):
        abilities = [ab for ab in _battlefield_static_abilities(state) if ab.layer != "cost"]
        # A nested static can itself live in layer 6 (for example Giant's
        # Amulet grants its host the self-scoped static "has hexproof while
        # untapped"). Apply that newly materialized level once in the same
        # recompute, without replaying the outer grants and duplicating their
        # triggered/activated ability objects.
        nested_ability_statics = [
            ab for obj in state.battlefield
            for ab in getattr(obj, "_granted_static_abilities", ())
            if isinstance(ab, StaticAbility) and ab.layer == "ability"
        ]
        if nested_ability_statics:
            _apply_layer_6_ability(state, nested_ability_statics)
    _apply_layer_7_pt(state, abilities, animation_pt)
    _apply_post_layer_combat_restrictions_and_goad(state, abilities)
    # RULE 702.75a / 406.3: controlling the Hideaway source permits looking;
    # that permission persists after a later control change or source removal.
    for player in state.players:
        for card in player.exile:
            source = state.find_object(getattr(card, "hideaway_source_id", None))
            if (source is not None and source in state.permanents()
                    and card.instance_id in source.hideaway_exile_ids):
                card.face_down_exile_viewers.add(source.controller_id)


def _cost_static_amount(ability: StaticAbility, state: "GameState", controller_id: Optional[str]) -> int:
    """Signed generic-mana delta for one "cost" static (positive = reduction).

    ``params.get("per")`` is an optional `count_selector` name for a
    per-count scaling reduction (Delve's "for each card in your graveyard",
    Affinity's "for each artifact you control") — the same "multiply a base
    amount by a board count" shape a layer-7d anthem's ``_pt_mod_count``
    already uses, reused here rather than reinvented.
    """
    amount = ability.params.get("generic", 0)
    per = ability.params.get("per")
    if per:
        # ``source`` lets a self-referential selector ("for each +1/+1 counter on this creature") read its own permanent.
        amount *= count_selector(state, controller_id, per, ability.source)
    return -amount if ability.params.get("increase") else amount


def _spell_type_matches(obj: "GameObject", spell_type: Union[str, list]) -> bool:
    """Whether the spell ``obj`` matches a `cost_reduction` static's
    ``spell_type`` filter ("noncreature spells cost {1} more…", Thalia,
    Guardian of Thraben/Thorn of Amethyst/Vryn Wingmare) — ``"noncreature"``
    is its own case (no ``Card.is_noncreature`` flag to read), everything
    else is a plain `_has_card_type` lookup on the object being cast. A
    ``list`` (Baral, Chief of Compliance's "Instant and sorcery spells you
    cast cost {1} less to cast.") ORs each word — any one matching is
    enough, mirroring how the printed "and" reads for a spell that's only
    ever exactly one type at a time."""
    if isinstance(spell_type, list):
        return any(_spell_type_matches(obj, t) for t in spell_type)
    if spell_type == "noncreature":
        return not obj.card.is_creature
    return _has_card_type(obj, spell_type)


def turn_cost_reduction_applies(entry: dict[str, Any], obj: Optional["GameObject"]) -> bool:
    """Whether a `GameState.turn_cost_reductions` entry discounts ``obj``.

    A filtered entry needs the spell itself; with ``obj=None`` (an offer-time
    probe) only an unfiltered one applies, like the static filters below.
    """
    filtered = (
        entry.get("spell_type") or entry.get("spell_colors") or entry.get("face_down") or entry.get("object_ids")
    )
    if obj is None:
        return not filtered
    if entry.get("object_ids") and obj.instance_id not in entry["object_ids"]:
        return False  # "spells you cast this way" — only the cards this grant named (Urianger Augurelt)
    if entry.get("spell_type") and not _spell_type_matches(obj, entry["spell_type"]):
        return False
    colors = entry.get("spell_colors")
    if colors and not set(colors) & set(obj.colors or set()):
        return False  # "that are black and/or red": either colour is enough
    if entry.get("face_down") and not getattr(obj, "face_down", False):
        return False
    return True


def consume_next_spell_cost_reductions(
    state: "GameState", player_id: str, obj: "GameObject"
) -> None:
    """Use up every "the next spell you cast this turn" discount ``obj`` got."""
    state.turn_cost_reductions = [
        entry for entry in getattr(state, "turn_cost_reductions", None) or []
        if not (entry.get("next_only") and entry.get("player_id") == player_id
                and turn_cost_reduction_applies(entry, obj))
    ]


def cost_reduction_for(
    state: "GameState", player: "Player", obj: Optional["GameObject"] = None,
    targets: Optional[list[Any]] = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Net generic-mana reduction for a spell ``player`` casts (RULE 601.2f).

    Sums "cost {N} less" statics and subtracts "cost {N} more" ones that apply
    to the player's spells, returning ``(net_reduction, contributors)`` where a
    positive reduction lowers the generic cost (never below zero, applied by
    the caller) and ``contributors`` describes each for the UI. Only reads
    *battlefield* statics ("permanents you control cost less") — a reduction
    printed on the spell card itself (Delve/Affinity) is `self_cost_reduction_for`.

    ``obj`` is the spell actually being cast/previewed — required to evaluate
    a ``spell_type``-filtered static ("noncreature spells cost {1} more to
    cast", RULE 601.2f — Thalia/Thorn of Amethyst/Vryn Wingmare-shaped); a
    caller that omits it (``None``, the pre-existing default) simply never
    matches such a static, unaffected by this parameter's addition.
    """
    net = 0
    contributors: list[dict[str, Any]] = []
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cost":
            continue
        if ability.params.get("scope") == "activation":
            # Power Artifact-shaped — an *activated ability's* own cost, not
            # a spell's cast cost; see `activation_cost_reduction_for`.
            continue
        if ability.affects == "your_spells" and getattr(ability.source, "controller_id", None) != player.id:
            continue
        # "Spells your opponents cast cost {N} more to cast." (Grand
        # Arbiter Augustin IV-shaped) — the tax-only mirror of
        # ``"your_spells"``: applies to every player *except* the
        # permanent's own controller.
        if ability.affects == "opponents_spells" and getattr(ability.source, "controller_id", None) == player.id:
            continue
        # "…that target ~ cost {N} more to cast." (Icefall Regent) — the
        # spell being cast must target this static's own source. Targets are
        # chosen before the cost is locked in (RULE 601.2c precedes
        # 601.2f), so ``targets`` is the caster's already-picked list.
        if ability.params.get("targets_source"):
            src_id = getattr(ability.source, "instance_id", None)
            chosen_ids = {
                getattr(t, "instance_id", None) for t in (targets or [])
            }
            if src_id is None or src_id not in chosen_ids:
                continue
        # An additional *life* cost is not generic mana — see `cast_life_tax_for`.
        if ability.params.get("life"):
            continue
        # "…that target you or a permanent you control cost {N} more to cast."
        # (Kasmina/Esior/Monastery Siege) — see `_spell_targets_hit`. A tax
        # needs the chosen targets, so the offer-time probe (``targets is
        # None``) leaves it off; a discount is left on, as `reduce_if_targets`.
        if_targets = ability.params.get("if_targets")
        if if_targets:
            if targets is None:
                if ability.params.get("increase"):
                    continue
            elif not _spell_targets_hit(targets, if_targets, state, ability.source):
                continue
        if ability.params.get("card_name_from_source"):
            chosen = getattr(ability.source, "chosen_card_name", None)
            if not chosen or obj is None or obj.card.name != chosen:
                continue
        spell_type = ability.params.get("spell_type")
        if ability.params.get("spell_type_from_source_mode"):
            # Cloud Key's "spells you cast of the chosen type": the card type picked as it entered
            # (`ChooseNamedModeReplacement` -> `GameObject.chosen_mode`, read live like
            # `cast_prohibited`'s ``type_from_source_mode``). Nothing chosen yet discounts nothing.
            spell_type = getattr(ability.source, "chosen_mode", None) or "none_chosen"
        if spell_type and (obj is None or not _spell_type_matches(obj, spell_type)):
            continue
        # "Creature spells you cast with power 4 or greater cost {2} less to cast." (Goreclaw) — the
        # spell's printed power (RULE 208: a spell off the battlefield has only its printed value).
        spell_min_power = ability.params.get("spell_min_power")
        if spell_min_power is not None:
            printed = getattr(getattr(obj, "card", None), "power", None)
            if not isinstance(printed, int) or printed < int(spell_min_power):
                continue
        # "Spells you cast from anywhere other than your hand cost {N} less."
        # (Advanced Reconstruction level 3, PAR-60) — the spell's own
        # cast-origin flags; ``obj is None`` (offer-time probe) leaves the
        # discount available so affordability isn't understated.
        # "Spells you cast from your graveyard cost {2} less to cast." (Emet-Selch): the card is still in the
        # graveyard while its cost is computed (the offer-time probe included).
        if ability.params.get("from_graveyard") and (
            obj is None or getattr(getattr(obj, "zone", None), "value", None) != "graveyard"
        ):
            continue
        if ability.params.get("not_from_hand") and obj is not None and not (
            getattr(obj, "cast_from_exile", False)
            or getattr(obj, "cast_via_flashback", False)
            or getattr(obj, "cast_via_escape", False)
        ):
            continue
        # "Spells you cast that target a creature cost {2} less to cast."
        # (Killian, Ink Duelist, PAR-60) — a RULE 601.2f reduction gated on
        # the chosen targets, the battlefield-static sibling of
        # `self_cost_reduction_for`'s own ``reduce_if_targets``. ``targets``
        # is None only at the offer-time / can-cast probe (targets not
        # chosen yet) — treat the discount as available then so
        # affordability isn't understated.
        reduce_if_targets = ability.params.get("reduce_if_targets")
        matching_targets = 1
        if reduce_if_targets and targets is not None:
            matching_targets = sum(
                1 for t in targets
                if _obj_matches_target_criteria(t, reduce_if_targets, state, player.id)
            )
            if not matching_targets:
                continue
        # "…costs {1} less to cast for each creature it targets." (Battlefield
        # Thaumaturge) — `per_target` scales the discount by how many chosen
        # targets matched `reduce_if_targets` instead of applying it once. At
        # the offer-time probe (``targets is None``) the count is unknown, so
        # it counts as one, like the other target-gated discounts above.
        per_target = bool(ability.params.get("per_target")) and reduce_if_targets
        # "Red spells you cast cost {1} less to cast." (the Medallion
        # cycle) — a colour filter, orthogonal to `spell_type`'s card-type
        # one; `GameObject.colors` reads the layer-5 derived colour, same
        # as every other colour-scoped consumer in this file. ``"colorless"``
        # (Eye of Ugin's "Colorless Eldrazi spells…") is the empty-set check
        # instead of a membership one, mirroring `card_query`'s own
        # ``color``-key special case.
        spell_color = ability.params.get("spell_color")
        if spell_color:
            if obj is None:
                continue
            if str(spell_color).lower() == "colorless":
                if obj.colors:
                    continue
            elif spell_color.upper() not in (obj.colors or set()):
                continue
        # "Colorless Eldrazi spells you cast cost {2} less to cast." (Eye of
        # Ugin) — a creature-*subtype* filter, orthogonal to both of the
        # above (`spell_type` only ever checks a main card type). Combines
        # with ``spell_color="colorless"`` above via plain AND (both keys
        # present, both must hold) rather than a new combined key, since
        # every other cost-reduction filter here already composes the same
        # way.
        spell_subtype = ability.params.get("spell_subtype")
        if ability.params.get("spell_subtype_from_source"):
            # "Creature spells you cast of the chosen type cost {1} less to cast." (Herald's Horn) — the type
            # picked as the source entered (`GameObject.chosen_type`); nothing chosen discounts nothing.
            spell_subtype = getattr(ability.source, "chosen_type", None) or "none_chosen"
        if spell_subtype:
            # A list ORs its subtypes ("Angel spells and Human spells you cast…", Herald of War).
            wanted = spell_subtype if isinstance(spell_subtype, (list, tuple)) else [spell_subtype]
            if obj is None or not any(has_subtype(obj, str(w)) for w in wanted):
                continue
        # "**Other** Sphinx spells you cast cost {1} less to cast." (The Ur-Sphinx) — never the ability's own source.
        if ability.params.get("other_spells") and obj is not None and obj is ability.source:
            continue
        # "Legendary spells you cast cost {1} less to cast." (Kethis, the Hidden Hand) — RULE 205.4.
        if ability.params.get("spell_legendary") and (obj is None or not getattr(obj.card, "is_legendary", False)):
            continue
        # RULE 613.6's ordinary ability-source-relative gate ("During your
        # turn, spells your opponents cast cost {1} more…" — Tithe Taker) —
        # `cost_floor_for` just below already checks this; this function
        # never had, a latent gap MEC-12 closed rather than working around.
        active_if = ability.params.get("active_if")
        source_controller = getattr(ability.source, "controller_id", None)
        if active_if and not static_conditions.condition_holds(
            active_if, state, ability.source, source_controller
        ):
            continue
        # "…except during its controller's turn." (Defense Grid) — "its"
        # means the *taxed spell's* controller, i.e. ``player`` (the actual
        # caster), not this static's own controller — so this is checked
        # directly rather than through the ability-source-relative gate above.
        if ability.params.get("except_caster_own_turn") and state.active_player is player:
            continue
        signed = _cost_static_amount(ability, state, player.id)
        if per_target:
            signed *= matching_targets
        net += signed
        contributors.append(
            {
                "source": _source_name(ability),
                "amount": signed,
                "description": f"Spells cost {{{abs(signed)}}} {'more' if signed < 0 else 'less'}",
            }
        )
    for entry in getattr(state, "turn_cost_reductions", None) or []:
        if entry.get("player_id") != player.id or not turn_cost_reduction_applies(entry, obj):
            continue
        amount = max(0, int(entry.get("amount", 0) or 0))
        signed = -amount if entry.get("increase") else amount
        net += signed
        contributors.append({
            "source": str(entry.get("source") or ""),
            "amount": signed,
            "description": f"Spells cost {{{amount}}} {'more' if signed < 0 else 'less'} this turn",
        })
    return net, contributors


def standing_mana_wildcard(state: "GameState", player: "Player") -> Optional[str]:
    """RULE 605.1a: "You may spend mana as though it were mana of any color." (Chromatic Orrery) — the
    `ManaPool` ``wildcard`` token (``"color"``) while a `mana_wildcard` static controlled by ``player``
    is on the battlefield, else ``None``. The standing sibling of the per-card
    `GameState.mana_wildcard_permission` grant; callers use whichever is set."""
    for ability in _battlefield_static_abilities(state):
        if ability.layer == "mana_wildcard" and getattr(ability.source, "controller_id", None) == player.id:
            return str(ability.params.get("wildcard") or "color")
    return None


def player_has_hexproof(state: "GameState", player_id: str) -> bool:
    """RULE 702.11b for a *player*: "You … have hexproof." (Shalai, Voice of Plenty; Leyline of
    Sanctity-shaped) — true while a `player_hexproof` static controlled by ``player_id`` is on the
    battlefield (or in an emblem/command zone — `_battlefield_static_abilities`). Not a RULE 613
    layer: nothing here is a characteristic, so it is read live by `targeting.legal_targets`, which
    removes such a player from an *opponent's* target pool (the hexproof player can still target
    themself, like any hexproof object)."""
    return any(
        ability.layer == "player_hexproof"
        and getattr(ability.source, "controller_id", None) == player_id
        for ability in _battlefield_static_abilities(state)
    )


def mana_production_multiplier_for(state: "GameState", player: "Player") -> int:
    """"If you tap a permanent for mana, it produces N times as much of
    that mana instead." (Nyxbloom Ancient/Mana Reflection/Zendikar
    Resurgent-shaped) — scoped to the *tapping* player owning the
    multiplying static (not to which permanent gets tapped, unlike every
    other mana-ability param here), so it's its own standalone lookup
    rather than folded into `mana_abilities_for`. Only `GameEngine.
    tap_for_mana` consults this — a triggered/hand-zone/ritual mana source
    was never *tapped*, so RULE 605.1's "tap a permanent for mana" wording
    correctly leaves those alone. Multiple copies don't stack additively
    (two Nyxbloom Ancients don't make mana ×6); the highest multiplier in
    play wins, mirroring `cost_floor_for`'s same "take the max" reading of
    several independent floor/multiplier effects.
    """
    multiplier = 1
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "mana_multiplier":
            continue
        if getattr(ability.source, "controller_id", None) != player.id:
            continue
        multiplier = max(multiplier, int(ability.params.get("multiplier", 1) or 1))
    return multiplier


def skipped_steps_for(state: "GameState", player: "Player") -> set[str]:
    """Step names ``player`` skips outright ("Skip your draw step." — MEC-38,
    Necropotence) — a new `StaticAbility` layer, ``"skip_step"``, scoped to
    its own controller (``affects="self"``, the same convention
    `mana_production_multiplier_for` above uses) and consulted directly by
    `RulesEngine.should_skip_step` alongside its pre-existing (but never
    actually wired to any card) `Player.player_effects`/`StaticEffect`
    check.

    Deliberately a live battlefield read rather than something added to
    `player_effects` when the source enters the battlefield and removed
    when it leaves: `_battlefield_static_abilities` already re-derives
    every permanent's static abilities fresh on every recompute, so there
    is no separate lifecycle to build — the same reasoning
    `mana_type_override_for`/`activation_prohibited` already lean on for
    their own "consulted live, not synced onto the player" shape.
    """
    steps: set[str] = set()
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "skip_step":
            continue
        if getattr(ability.source, "controller_id", None) != player.id:
            continue
        step = ability.params.get("step")
        if step:
            steps.add(str(step))
    return steps


def search_redirect_controller_for(
    state: "GameState", searching_player: "Player"
) -> Optional[str]:
    """"While an opponent is searching their library, they exile each card
    they find. You may play those cards for as long as they remain
    exiled, and you may spend mana as though it were mana of any color to
    cast them." (MEC-39, Opposition Agent) — returns the controller who
    gains the exile-cast + any-color-mana permission for each card
    ``searching_player`` finds this search, or ``None`` if no such static
    applies to them.

    Deliberately doesn't model the card's own leading "You control your
    opponents while they're searching their libraries" as an actual RULE
    269.4 control exchange of the *player* — this engine's search flow has
    no other decision point during a search a genuine control swap would
    change (the searching player still picks which cards they find; only
    where those cards *end up* is redirected), so the mechanical outcome
    this function implements is the whole of what the card does. A new
    `StaticAbility` layer, `"search_redirect"`, scoped to its own
    controller (``affects="self"``) the same way `mana_type_override`'s
    own unscoped-vs-scoped statics are told apart.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "search_redirect":
            continue
        owner_id = getattr(ability.source, "controller_id", None)
        if owner_id is None or owner_id == searching_player.id:
            continue
        return owner_id
    return None


def proliferate_multiplier(state: "GameState", controller_id: Optional[str]) -> int:
    """RULE 701.34 / 616: "If you would proliferate, proliferate twice instead." (Tekuthal, Inquiry
    Dominus) — how many times a proliferate by ``controller_id`` is performed. Each such permanent
    replaces the (already doubled) action again, so ``n`` of them give ``2 ** n``; with none it is 1.
    Read off the standing ``proliferate_twice`` static, outside the layer engine, like the other
    "permission/restriction" statics here."""
    doublers = sum(
        1 for ability in _battlefield_static_abilities(state)
        if ability.layer == "proliferate_twice"
        and getattr(ability.source, "controller_id", None) == controller_id
    )
    return 2 ** doublers


def forced_sorcery_speed_only(state: "GameState", player: "Player") -> bool:
    """Whether ``player`` is under a standing "can cast spells only any
    time they could cast a sorcery" restriction (Teferi, Time Raveler's
    own static, MEC-42) — forces RULE 601.3b sorcery-speed timing even
    for a spell that otherwise carries Flash/is an instant. Checked
    directly in `GameEngine.can_cast`'s own timing computation, the same
    "permission/restriction static outside the layer engine" treatment
    `has_standing_flash_permission` gets for the opposite direction.
    "Each **opponent**" — this only ever restricts a player other than
    the granting permanent's own controller.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "sorcery_speed_only":
            continue
        controller_id = getattr(ability.source, "controller_id", None)
        if controller_id is None or controller_id == player.id:
            continue
        return True
    return False


def attack_tax_per_creature_for(
    state: "GameState", defending_player_id: str, defender_kind: str = "player",
    attacker: Any = None,
) -> int:
    """RULE 508.1g — "creatures can't attack you unless their controller pays
    {N} for each creature they control that's attacking you" (Propaganda /
    Ghostly Prison / Windborn Muse). Returns the total {N} charged **per
    newly-declared attacking creature** by every such static whose own
    controller is ``defending_player_id`` (the "you" the clause protects); 0
    if there is none. `combat_mixin.declare_attackers` multiplies this by how
    many of that player's creatures are being declared against the taxed
    player and pays the sum before the attack locks in. ``defender_kind`` is
    the chosen RULE 508.1a defender: the ordinary Propaganda wording taxes
    only a player, while Sphere of Safety includes that player's planeswalkers
    as printed. Battles are not covered by either wording (RULE 310.8d's
    defending-player relation does not turn "attack you" into "attack a
    battle you protect").
    """
    total = 0
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "attack_tax":
            continue
        if getattr(ability.source, "controller_id", None) != defending_player_id:
            continue
        params = ability.params or {}
        # RULE 613.6 gate ("As long as ~ is untapped, …" — Archangel of Tithes).
        gate = params.get("active_if")
        if gate and not static_conditions.condition_holds(
            gate, state, ability.source, getattr(ability.source, "controller_id", None)
        ):
            continue
        scope = str(params.get("defender_scope", "player"))
        if defender_kind != "player" and not (
            defender_kind == "planeswalker" and scope == "player_or_planeswalker"
        ):
            continue
        # Nils, Discipline Enforcer (PAR-60) — a per-attacker filtered,
        # per-attacker-variable tax: only attackers matching ``attacker_
        # filter`` are taxed, and each pays its own counter count.
        attacker_filter = params.get("attacker_filter")
        per_counter = params.get("amount_per_attacker_counter")
        if (attacker_filter or per_counter) and attacker is not None:
            if not _defender_attack_ban_matches(
                state, attacker, ability.source, attacker_filter or {}
            ):
                continue
            if per_counter:
                counters = getattr(attacker, "counters", {}) or {}
                if str(per_counter) == "any":
                    total += sum(int(v) for v in counters.values() if int(v) > 0)
                else:
                    total += max(0, int(counters.get(str(per_counter), 0)))
                continue
        selector = params.get("amount_count_selector")
        if selector:
            total += count_selector(state, defending_player_id, str(selector), ability.source)
        else:
            total += int(params.get("amount", 0))
    return total


def block_tax_per_creature(state: "GameState") -> int:
    """RULE 509.1c — "creatures can't block unless their controller pays {N}
    for each of those creatures" (Archangel of Tithes while attacking).
    Returns the total {N} charged **per declared blocking creature** by every
    ``block_tax`` static whose ``active_if`` gate holds; a creature of any
    controller is taxed. `combat_mixin.declare_blockers` multiplies this by
    the creatures being declared and pays the sum before the block locks in."""
    total = 0
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "block_tax":
            continue
        params = ability.params or {}
        gate = params.get("active_if")
        if gate and not static_conditions.condition_holds(
            gate, state, ability.source, getattr(ability.source, "controller_id", None)
        ):
            continue
        total += int(params.get("amount", 0))
    return total


def _defender_attack_ban_matches(
    state: "GameState", attacker: Any, static_source: Any, filt: dict[str, Any]
) -> bool:
    """Whether ``attacker`` satisfies a ``cant_attack_defender`` static's
    ``attacker_filter`` (all keys AND-combined). An empty filter matches
    every creature ("Creatures can't attack you", Peacekeeper-style)."""
    if not filt:
        return True
    controller_id = getattr(static_source, "controller_id", None)
    subtype = filt.get("subtype")
    if subtype and not has_subtype(attacker, str(subtype)):
        return False
    keyword = filt.get("keyword")
    if keyword:
        # "Creatures with flying can't attack you or planeswalkers you control." (Sandwurm Convergence)
        from . import combat  # function-scoped: combat imports this module

        if not combat.has(attacker, str(keyword)):
            return False
    counter_kind = filt.get("has_counter_kind")
    counters = getattr(attacker, "counters", {}) or {}
    if counter_kind and int(counters.get(counter_kind, 0)) <= 0:
        return False
    if filt.get("has_any_counter") and not any(int(v) > 0 for v in counters.values()):
        return False
    if filt.get("enchanted_by_controller_aura"):
        aid = getattr(attacker, "instance_id", None)
        if not any(
            getattr(o, "attached_to", None) == aid
            and "aura" in (getattr(o.card, "type_line", "") or "").lower()
            and getattr(o, "controller_id", None) == controller_id
            for o in state.battlefield
        ):
            return False
    return True


def defender_attack_prohibited(
    state: "GameState",
    attacker: Any,
    defending_player_id: str,
    defender_kind: str = "player",
) -> bool:
    """RULE 508.1 — whether ``attacker`` is under a standing "can't attack
    you [or planeswalkers you control]" bar whose protected player is
    ``defending_player_id`` (Eriette of the Charmed Apple's Aura clause,
    Combat Calligrapher's "Inklings can't attack you…"). The mirror of
    `attack_tax_per_creature_for` — same battlefield-static scan scoped to
    the clause's own controller — but an absolute bar rather than a tax.

    ``defender_kind`` is the chosen RULE 508.1a defender; a static whose
    ``defender_scope`` is ``"player"`` protects only the player, one whose
    scope is ``"player_or_planeswalker"`` (the default, and every real
    Strixhaven card's wording) also protects that player's planeswalkers.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cant_attack_defender":
            continue
        if getattr(ability.source, "controller_id", None) != defending_player_id:
            continue
        params = ability.params or {}
        scope = str(params.get("defender_scope", "player_or_planeswalker"))
        if defender_kind == "planeswalker" and scope != "player_or_planeswalker":
            continue
        if _defender_attack_ban_matches(
            state, attacker, ability.source, params.get("attacker_filter") or {}
        ):
            return True
    return False


def exile_discount_spec_for(obj: Any) -> Optional[dict[str, Any]]:
    """"As an additional cost to cast this spell, you may exile any number
    of `<color>` cards from your hand. This spell costs `<N>` less to cast
    for each card exiled this way." (March of Swirling Mist, MEC-42) —
    ``{"color": "U", "generic_per_card": 2}`` if ``obj`` prints this
    clause, else ``None``. Read straight off ``obj.static_effects`` the
    same way `self_cost_reduction_for` reads a spell's own printed "costs
    less" static while it's still in hand — an `exile_discount_cost`
    layer, not a battlefield-scoped one.
    """
    for ability in getattr(obj, "static_effects", None) or ():
        if getattr(ability, "layer", None) == "exile_discount_cost":
            return dict(ability.params)
    return None


def void_counter_redirect_controller_for(state: "GameState", obj: Any) -> Optional[str]:
    """"If a card would be put into an opponent's graveyard from anywhere,
    instead exile it with a void counter on it." (Dauthi Voidwalker,
    MEC-42) — ``obj`` is about to enter *its own owner's* graveyard (RULE
    404.4/700.4), so "an opponent's graveyard" means any Dauthi Voidwalker
    whose controller differs from ``obj.owner_id``; returns that
    controller (who earns the void counter, `GameState.void_counter_
    holder`), or ``None``. Same battlefield-static-scan idiom as `search_
    redirect_controller_for`, checked from `RulesEngine._move_to_graveyard`
    alongside the Lurrus/Yawgmoth's Will redirects already there.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "void_counter_redirect":
            continue
        controller_id = getattr(ability.source, "controller_id", None)
        if controller_id is None or controller_id == getattr(obj, "owner_id", None):
            continue
        return controller_id
    return None


def graveyard_redirect_active(state: "GameState", obj: Any) -> bool:
    """"If a card would be put into an opponent's graveyard from anywhere,
    exile it instead." (Leyline of the Void)/"If a card or token would be
    put into a graveyard from anywhere, exile it instead." (Rest in Peace,
    MEC-43) — the plain-exile sibling of Dauthi Voidwalker's
    `void_counter_redirect_controller_for` (no counter, no holder
    tracking), ``scope``-parameterized so one static covers both "an
    opponent's graveyard" (``scope="opponent"``, the default) and every
    graveyard (``scope="any"``). Checked from `RulesEngine._move_to_
    graveyard`'s redirect chain, right alongside the void-counter one.

    ``colors`` (MEC-43 round 2, Sanctifier en-Vec — "If a **black or red**
    permanent, spell, or card not on the battlefield would be put into a
    graveyard, exile it instead.") is a second, independent scoping axis:
    whose-graveyard (``scope``) and which-card (``colors``) both gate when
    both are set, matching how Sanctifier's own clause names no owner —
    unlike Leyline/Rest in Peace, it's whose-*color*-scoped, not
    whose-*graveyard*-scoped, so it always passes ``scope="any"``
    alongside its own ``colors`` list.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "graveyard_redirect":
            continue
        colors = ability.params.get("colors")
        if colors and not (set(getattr(obj, "colors", None) or ()) & set(colors)):
            continue
        if ability.params.get("scope", "opponent") == "any":
            return True
        controller_id = getattr(ability.source, "controller_id", None)
        if controller_id is not None and controller_id != getattr(obj, "owner_id", None):
            return True
    return False


def mana_type_override_for(
    state: "GameState", source: "GameObject", total_produced: int
) -> Optional[str]:
    """"If a land is tapped for 2 or more mana, it produces {C} instead of
    any other type and amount." (MEC-36, Damping Sphere) — unscoped by
    controller (any land tapped by anyone, not just this static's own
    controller's), consulted by `GameEngine.tap_for_mana` right alongside
    `mana_production_multiplier_for` above, after that multiplier has
    already been applied — ``total_produced`` is the true amount that
    would land in the pool this tap, which is what the printed threshold
    actually cares about. Multiple copies don't compound (a boolean
    override, not an additive one); the first applicable static found
    wins.
    """
    if not source.is_land:
        return None
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "mana_type_override":
            continue
        min_amount = int(ability.params.get("min_amount", 2) or 2)
        if total_produced >= min_amount:
            return str(ability.params.get("to", "C"))
    return None


def life_gain_prohibited_for(state: "GameState", player: "Player") -> bool:
    """Whether ``player`` currently can't gain life because of a standing
    battlefield static — "Players can't gain life." (Everlasting Torment /
    Forsaken Wastes / Havoc Festival / Leyline of Punishment / Sulfuric
    Vortex, unscoped: stops *everyone*, including the static's own
    controller) or "Your opponents can't gain life." (Erebos, God of the
    Dead — scoped to the static's controller's opponents). Consulted by
    `RulesEngine.gain_life`. Same "live battlefield read, no separate
    lifecycle" shape as `skipped_steps_for` / `mana_type_override_for`.
    Honours any `active_if` gate (Erebos-shaped "as long as your devotion …").
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "life_gain_prohibition":
            continue
        active_if = ability.params.get("active_if")
        src_controller = getattr(ability.source, "controller_id", None)
        if active_if and not static_conditions.condition_holds(
            active_if, state, ability.source, src_controller
        ):
            continue
        if ability.params.get("scope") == "opponents":
            if player.id != src_controller:
                return True
        else:
            return True
    return False


def damage_prevention_globally_disabled(state: "GameState") -> bool:
    """"Damage can't be prevented." (Everlasting Torment) — a standing
    battlefield static making RULE 615 prevention shields inert while it is
    on the battlefield, the board-permanent sibling of the turn-scoped
    `GameState.damage_prevention_disabled`. Consulted by
    `RulesEngine._run_replacement_loop`. Same "live battlefield read, no
    separate lifecycle" shape as `life_gain_prohibited_for`.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer == "damage_prevention_prohibition":
            return True
    return False


def global_wither_active(state: "GameState") -> bool:
    """"All damage is dealt as though its source had wither." (Everlasting
    Torment) — RULE 609.4b as-though, a standing battlefield static that
    recolours every source's damage to creatures into -1/-1 counters.
    Consulted by `RulesEngine.deal_damage` on top of the source's own
    `has_wither`. Same live-read shape as `damage_prevention_globally_disabled`.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer == "global_wither":
            return True
    return False


def cost_floor_for(state: "GameState", player: "Player", obj: Optional["GameObject"] = None) -> int:
    """"Each spell that would cost less than N mana to cast costs N mana to
    cast instead." (Trinisphere) — a floor, not a delta, so it's kept out of
    `cost_reduction_for`'s additive net entirely: two floors of different
    values take the higher one, not their sum, and each has its own
    ``active_if`` gate (Trinisphere's own "as long as this artifact is
    untapped"). Same ownership scoping (``"your_spells"``/``"opponents_
    spells"``/unscoped ``"all_spells"``) as `cost_reduction_for`.
    """
    floor = 0
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cost":
            continue
        min_generic = ability.params.get("min_generic")
        if not min_generic:
            continue
        source_controller = getattr(ability.source, "controller_id", None)
        if ability.affects == "your_spells" and source_controller != player.id:
            continue
        if ability.affects == "opponents_spells" and source_controller == player.id:
            continue
        active_if = ability.params.get("active_if")
        if active_if and not static_conditions.condition_holds(
            active_if, state, ability.source, source_controller
        ):
            continue
        floor = max(floor, int(min_generic))
    return floor


def _obj_matches_target_criteria(
    target: Any, criteria: dict[str, Any], state: "GameState",
    caster_id: Optional[str] = None, source_controller_id: Optional[str] = None,
) -> bool:
    """Whether a resolved spell target matches a `reduce_if_targets` criteria
    dict (RULE 601.2f "if it targets a `<criteria>`"). ``target`` may be a
    `GameObject` or an instance-id/descriptor; a player target never matches
    (every printed criterion in this cycle names a permanent).

    ``controller`` is relative to the caster (``"you"``/``"not_you"``, a
    discount printed on the spell) or, for a tax a permanent imposes on
    someone else's spell, to that permanent's controller
    (``"source_controller"``, ``source_controller_id``)."""
    from . import combat  # function-scoped: combat imports this module

    obj = target
    if not hasattr(obj, "instance_id"):
        iid = target.get("instance_id") if isinstance(target, dict) else target
        obj = state.find_object(iid) if iid is not None else None
    if obj is None or not hasattr(obj, "card"):
        return False
    crit = dict(criteria)
    # "a permanent you control" names the battlefield, not a spell on the stack.
    if crit.pop("permanent", False) and obj not in state.battlefield:
        return False
    card_type = crit.pop("card_type", None)
    if card_type and card_type.lower() not in obj.card.type_line.lower():
        return False
    if crit.pop("legendary", False) and "legendary" not in obj.card.type_line.lower():
        return False
    if crit.pop("is_token", False) and not getattr(obj, "is_token", False):
        return False
    controller = crit.pop("controller", None)
    if controller == "source_controller" and (
        source_controller_id is None or getattr(obj, "controller_id", None) != source_controller_id
    ):
        return False
    if controller == "you" and getattr(obj, "controller_id", None) != caster_id:
        return False
    if controller == "not_you" and getattr(obj, "controller_id", None) == caster_id:
        return False
    return combat.matches_object_filter(obj, crit) if crit else True


def _spell_targets_hit(
    targets: list[Any], alternatives: list[dict[str, Any]], state: "GameState", source: Any,
) -> bool:
    """Whether any of a spell's chosen ``targets`` is one a cost static's
    ``if_targets`` names (RULE 601.2f, after 601.2c's targets are chosen).

    ``alternatives`` is an OR-list; each member is one of ``{"source": True}``
    (the static's own permanent — "that target ~"), ``{"player":
    "controller"}`` (its controller as a player — "that target you"), or a
    `_obj_matches_target_criteria` dict whose ``controller`` may be
    ``"source_controller"`` ("a creature you control", read from the
    permanent's controller, not the caster's)."""
    controller_id = getattr(source, "controller_id", None)
    source_id = getattr(source, "instance_id", None)
    for target in targets:
        is_object = hasattr(target, "instance_id")
        for alt in alternatives:
            if alt.get("player") == "controller":
                if not is_object and controller_id is not None and (
                    getattr(target, "id", target) == controller_id
                ):
                    return True
            elif not is_object:
                continue  # every other alternative names a permanent
            elif alt.get("source"):
                if source_id is not None and target.instance_id == source_id:
                    return True
            elif _obj_matches_target_criteria(
                target, alt, state, source_controller_id=controller_id,
            ):
                return True
    return False


def cast_life_tax_for(
    state: "GameState", player: "Player", obj: Optional["GameObject"],
    targets: Optional[list[Any]],
) -> int:
    """Life ``player`` must pay in addition to casting ``obj`` (RULE 601.2f).

    "Spells your opponents cast that target ~ cost an additional 3 life to
    cast." (Terror of the Peaks) — a ``cost``-layer static with a ``life``
    param, gated exactly like `cost_reduction_for`'s mana taxes (the
    ``affects`` scope and the chosen-target filters). Needs the chosen
    ``targets``: with none (an offer-time probe) it is 0, as the mana taxes are.
    """
    if not targets:
        return 0
    total = 0
    for ability in _battlefield_static_abilities(state):
        life = ability.params.get("life")
        if ability.layer != "cost" or not life:
            continue
        controller_id = getattr(ability.source, "controller_id", None)
        if ability.affects == "your_spells" and controller_id != player.id:
            continue
        if ability.affects == "opponents_spells" and controller_id == player.id:
            continue
        active_if = ability.params.get("active_if")
        if active_if and not static_conditions.condition_holds(active_if, state, ability.source, controller_id):
            continue
        hit = ability.params.get("targets_source") and _spell_targets_hit(
            targets, [{"source": True}], state, ability.source
        )
        hit = hit or (
            ability.params.get("if_targets")
            and _spell_targets_hit(targets, ability.params["if_targets"], state, ability.source)
        )
        if not hit:
            continue
        total += int(life)
    return total


def self_cost_reduction_for(
    obj: "GameObject", state: "GameState", caster_id: Optional[str] = None,
    targets: Optional[list[Any]] = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Net generic-mana reduction from a "cost" static printed on ``obj``
    itself (Delve/Affinity-shaped: "This spell costs {1} less to cast for
    each ...") while ``obj`` is still in hand/graveyard/etc.

    `_battlefield_static_abilities` only scans `state.battlefield`, so a
    card that hasn't been cast yet needs its own static read straight off
    ``obj.static_effects`` — the binder attaches a spell's own statics there
    regardless of zone, same as any other static.

    ``caster_id`` is the player actually attempting to cast ``obj`` right
    now — distinct from ``obj.controller_id`` (which for an exiled/hand
    card is ordinarily just its owner, not "whoever's about to cast it").
    Needed for `except_same_controller_as` (MEC-12, Soul Partition's own
    "**a spell cast by an opponent** this way costs {2} more" — a per-
    instance tax stamped directly onto a specific exiled card at the
    moment it was exiled, exempting only the exiler themself).
    """
    net = 0
    contributors: list[dict[str, Any]] = []
    controller_id = getattr(obj, "controller_id", None)
    for ability in getattr(obj, "static_effects", []):
        if not isinstance(ability, StaticAbility) or ability.layer != "cost" or ability.affects != "self":
            continue
        # RULE 613.6: "This spell costs {N} less to cast if `<condition>`."
        # (Ghostfire Slice's "if an opponent controls a multicolored
        # permanent") — the same whitelisted `active_if` gate a battlefield
        # static already reads in `_battlefield_static_abilities`, just
        # evaluated here too since a spell's own printed reduction is read
        # straight off `static_effects` rather than that battlefield scan.
        active_if = ability.params.get("active_if")
        if active_if and not static_conditions.condition_holds(active_if, state, obj, controller_id):
            continue
        # RULE 601.2f: "This spell costs {N} less to cast **if it targets a
        # `<criteria>`**." (Ajani's Response / Knockout Blow cycle) — the
        # discount only applies once the spell's targets are known and at
        # least one matches. ``targets is None`` is the offer-time /
        # can-cast probe (targets not chosen yet): treat the discount as
        # available so affordability isn't understated, the same best-case
        # treatment `help_pay`/kicker get.
        reduce_if_targets = ability.params.get("reduce_if_targets")
        if reduce_if_targets and targets is None and ability.params.get("increase"):
            # A *tax* "if it targets a `<criteria>`" (Dragon's Prey) needs the chosen targets; the offer-time
            # probe has none, and — unlike a discount — must not assume the worst case.
            continue
        if reduce_if_targets and targets is not None:
            if not any(
                _obj_matches_target_criteria(t, reduce_if_targets, state, caster_id)
                for t in targets
            ):
                continue
        except_same = ability.params.get("except_same_controller_as")
        if except_same is not None and caster_id == except_same:
            continue
        signed = _cost_static_amount(ability, state, controller_id)
        net += signed
        colored = ability.params.get("colored")
        contributors.append(
            {
                "source": _source_name(ability),
                "amount": signed,
                **({"colored": colored} if colored else {}),
                "description": (
                    "Costs " + "".join(f"{{{c}}}" * n for c, n in colored.items()) + " less to cast"
                    if colored else f"Costs {{{abs(signed)}}} {'more' if signed < 0 else 'less'} to cast"
                ),
            }
        )
    return net, contributors


#: A reduction large enough to take any printed equip cost to {0} ("Equipment you control have equip {0}").
_SET_COST_TO_ZERO_REDUCTION = 1000


def activation_cost_reduction_for(
    state: "GameState", source: "GameObject", is_mana_ability: bool = False, cost: Any = None,
) -> tuple[int, int]:
    """Net generic-mana reduction for *activating* ``source``'s own
    activated ability (Power Artifact-shaped "Enchanted artifact's
    activated abilities cost {2} less to activate.") — the activation-cost
    analogue of `cost_reduction_for` (a *spell's* cast cost); consulted by
    `GameEngine._reduced_activation_mana`. A negative result is a genuine
    *tax* (MEC-12, Suppression Field/Tithe Taker's "…cost {N} more to
    activate") — the caller applies it the same way `_adjust_cost` already
    applies `cost_reduction_for`'s own signed net to a spell.

    Only a ``"cost"``-layer static with ``params["scope"] == "activation"``
    counts (`cost_reduction_for` explicitly skips these, so a static never
    double-applies to both a spell's cast cost and an ability's activation
    cost). Five group scopes: ``affects="attached_permanent"`` (Power
    Artifact), a ``subtype`` filter (Sam, Loyal Attendant's "Foods you
    control"), a ``card_type`` filter (Training Grounds's "creatures you
    control" — a main card type rather than a creature subtype, so it reads
    `_has_card_type` instead of `has_subtype`), ``affects=
    "opponents_permanents"`` (Tithe Taker's "abilities your opponents
    activate…" — the activation-cost mirror of `activation_prohibited`'s own
    opponents scope), or ``affects="all_permanents"`` (Suppression Field's
    unqualified "activated abilities cost {N} more…", unscoped by controller
    entirely).

    ``is_mana_ability`` mirrors `activation_prohibited`'s own param — a
    static carrying ``except_mana_abilities`` (both real cards of this
    shape print it) then never taxes a mana ability's own cost. Also
    consults the ordinary ability-source-relative ``active_if`` gate (Tithe
    Taker's "**during your turn**, …") — `cost_reduction_for`'s own sibling
    check, same reasoning.

    Returns ``(net_reduction, floor)`` where ``floor`` is the highest
    "can't reduce the mana in that cost to less than N mana" clause among
    the contributing statics (0 — no floor — if none set one; meaningless
    for a tax, which never contributes to it since a floor only bounds how
    far a *reduction* can go).
    """
    net = 0
    floor = 0
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cost" or ability.params.get("scope") != "activation":
            continue
        if is_mana_ability and ability.params.get("except_mana_abilities"):
            continue
        source_controller = getattr(ability.source, "controller_id", None)
        if ability.params.get("first_targeting_own_creature"):
            # "The first activated ability you activate during your turn that targets a creature you control costs {2} less to activate."
            # (Professor Hojo): this ability must target a creature you control, and no earlier activation of yours this turn did.
            player_id = getattr(ability.source, "controller_id", None)
            if source.controller_id != player_id or not getattr(cost, "targets_own_creature", False):
                continue
            gate = ability.params.get("active_if")
            if gate and not static_conditions.condition_holds(gate, state, ability.source, player_id):
                continue
            if any(
                e.type == "ACTIVATED_ABILITY" and e.get("player_id") == player_id and e.get("targets_own_creature")
                for e in state.events_this_turn()
            ):
                continue
            net += int(ability.params.get("generic", 1))
            continue
        if ability.params.get("set_to_zero"):
            # "Equipment you control have equip {0}" (Puresteel Paladin): only the named attach keyword's own ability, on the
            # controller's own permanents of ``subtype``, while ``active_if`` (metalcraft) holds.
            if getattr(cost, "attach_kind", None) != ability.params.get("attach_kind") or source.controller_id != source_controller:
                continue
            if ability.params.get("subtype") and not has_subtype(source, str(ability.params["subtype"])):
                continue
            gate = ability.params.get("active_if")
            if gate and not static_conditions.condition_holds(gate, state, ability.source, source_controller):
                continue
            net += _SET_COST_TO_ZERO_REDUCTION
            continue
        if ability.affects == "attached_permanent":
            if getattr(ability.source, "attached_to", None) != source.instance_id:
                continue
        elif ability.params.get("subtype"):
            # "Activated abilities of Foods you control cost {1} less to
            # activate." (Sam, Loyal Attendant) — the unscoped, subtype-
            # narrowed variant this docstring flagged as unbuilt; scoped to
            # the reducing permanent's own controller, matching the "you
            # control" every printed card of this shape carries.
            if source.controller_id != source_controller or not has_subtype(
                source, str(ability.params["subtype"])
            ):
                continue
        elif ability.params.get("card_type"):
            # "Activated abilities of creatures you control cost {2} less
            # to activate." (Training Grounds) — the same "you control"
            # group scope as the subtype branch above, narrowed by a main
            # card type instead of a creature subtype.
            if source.controller_id != source_controller or not _has_card_type(
                source, str(ability.params["card_type"])
            ):
                continue
        elif ability.affects == "opponents_permanents":
            if source_controller is None or source.controller_id == source_controller:
                continue
        elif ability.affects == "all_permanents":
            pass  # unscoped — Suppression Field
        else:
            continue
        active_if = ability.params.get("active_if")
        if active_if and not static_conditions.condition_holds(
            active_if, state, ability.source, source_controller
        ):
            continue
        net += _cost_static_amount(ability, state, source_controller)
        floor = max(floor, int(ability.params.get("min_total", 0)))
    return net, floor


def activation_prohibited(
    state: "GameState", source: "GameObject", is_mana_ability: bool = False
) -> bool:
    """Whether a board-wide static ("Activated abilities of artifacts can't
    be activated." — RULE 602, Collector Ouphe/Stony Silence/Null Rod)
    silences ``source``'s activated abilities right now.

    Consulted by `GameEngine.can_activate` — the single choke point both
    `activate_ability`'s validation and `legal_actions`'s offer list already
    go through, so one check here covers both. Reuses the ordinary
    ``affects``/``card_type`` selector vocabulary (`affected_objects`) rather
    than a bespoke predicate: the default ``affects="all_permanents"`` is
    global (not scoped to the prohibiting permanent's own controller) and
    carries no self-exemption, matching these three cards' plain wording —
    Null Rod is itself an artifact and silences its own (non-existent here,
    but any future artifact-with-abilities') activated abilities too.

    ``is_mana_ability`` says whether the ability being checked is a RULE
    605.1a mana ability — set by `GameEngine.tap_for_mana`, the one caller
    that activates one. A prohibition printed with the
    ``except_mana_abilities`` rider ("…and its activated abilities can't be
    activated unless they're mana abilities" — Kasmina's Transmutation/
    Imprisoned in the Moon-shaped) then doesn't apply; an unqualified one
    still does, which is what makes Null Rod stop an artifact's ``{T}: Add
    {C}`` as well as everything else.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "activation_prohibition":
            continue
        if is_mana_ability and ability.params.get("except_mana_abilities"):
            continue
        player_id = ability.params.get("player_id")
        if player_id is not None:
            if source.controller_id == player_id:
                return True
            continue
        if source in affected_objects(state, ability):
            return True
    return False


def graveyard_library_cast_prohibited(state: "GameState", zone: Optional[str] = None) -> bool:
    """RULE 601.3a: "Players can't cast spells from graveyards or
    libraries." (Grafdigger's Cage/Weathered Runestone) — a flat, unscoped
    prohibition (no card in the cache prints a "you"-only version) over
    every standing graveyard/library-cast *permission* this engine has
    (Flashback/Escape/Jump-start's keyword route, a Lurrus-shaped granted
    `graveyard_cast_permission`, and `game/top_library.py`'s play/cast-from-
    the-top permission) — `GameEngine.can_cast`'s single choke point for
    all of them, checked once ``obj`` is already known to be sitting in a
    graveyard or library rather than duplicated into each permission
    source separately.

    ``zone`` (MEC-43 round 2, Kunoros, Hound of Athreos — "Players can't
    cast spells from **graveyards**", no "or libraries") is the object's own
    current zone name ("graveyard"/"library"); a static whose own ``zones``
    param doesn't include it doesn't apply. Omitted (the historic call
    shape) means "don't care which zone", matching every prior card, which
    all print the unscoped "graveyards or libraries" pair.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "graveyard_library_cast_prohibition":
            continue
        zones = ability.params.get("zones")
        if zones and zone is not None and zone not in zones:
            continue
        return True
    return False


def graveyard_library_entry_prohibited(state: "GameState", card: Any, zone: Optional[str] = None) -> bool:
    """RULE 601.3a-adjacent "`<type>` cards in graveyards and libraries
    can't enter the battlefield." (Grafdigger's Cage's ``"creature"``,
    Weathered Runestone's ``"nonland permanent"``) — checked wherever a
    card would move from a graveyard or library *straight onto the
    battlefield* (reanimation, a tutor whose destination is the
    battlefield), not filtered by whose graveyard/library or who would
    have controlled it — both real cards are unscoped.

    Deliberately not a universal `GameState.add_to_battlefield` hook: this
    engine has no single choke point every graveyard/library-to-battlefield
    route already funnels through (reanimation and library-search-to-
    battlefield are the two `game/effects/core.py` sites that check it; a rarer
    per-card route missing this check is a documented simplification, the
    same shape this repo already accepts for other narrow gaps rather than
    reworking a foundational model method's contract for it).

    ``zone`` (MEC-43 round 2, Kunoros, Hound of Athreos — "Creature cards
    in **graveyards** can't enter the battlefield", no "and libraries")
    is the card's own current zone name; a static whose own ``zones`` param
    doesn't include it doesn't apply. Omitted means "don't care", matching
    every prior (unscoped, "graveyards and libraries") card.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "graveyard_library_entry_prohibition":
            continue
        zones = ability.params.get("zones")
        if zones and zone is not None and zone not in zones:
            continue
        filt = str(ability.params.get("card_type", "creature"))
        if filt == "nonland_permanent":
            if getattr(card, "is_land", False):
                continue
            if not any(
                getattr(card, attr, False) for attr in (
                    "is_creature", "is_artifact", "is_enchantment", "is_planeswalker", "is_battle",
                )
            ):
                continue
            return True
        if filt == "permanent":
            # "Permanent cards in graveyards can't enter the battlefield."
            # (Soulless Jailer, MEC-43) — unlike ``"nonland_permanent"``
            # above, this includes lands too; every card this check is ever
            # reached for is already headed to the battlefield, so "is a
            # permanent card" is unconditionally true here.
            return True
        if _has_card_type(_CardTypeProbe(card), filt):
            return True
    return False


class _CardTypeProbe:
    """Adapts a bare `Card` to `_has_card_type`'s `GameObject`-shaped
    ``obj.card`` access — `graveyard_library_entry_prohibited` is checked
    against a graveyard/library *card*, which has no `GameObject` wrapper
    of its own at that point (it hasn't entered a zone that gets one)."""

    __slots__ = ("card",)

    def __init__(self, card: Any) -> None:
        self.card = card


def uncast_creature_entry_exiled(state: "GameState", card: Any) -> bool:
    """RULE 616.1-adjacent "If a nontoken creature would enter and it
    wasn't cast, exile it instead." (MEC-43 round 4D, Containment Priest)
    — checked at the same two graveyard/library-to-battlefield choke
    points `graveyard_library_entry_prohibited` just above already uses
    (reanimation, a tutor whose destination is the battlefield): both
    routes are definitionally "wasn't cast" (RULE 601's whole cast
    procedure never runs for either), so the only extra condition to check
    here is "nontoken creature card" — trivially true at both sites, since
    a graveyard/library *card* (as opposed to a `GameObject` already on the
    battlefield) is never a token in the first place (RULE 111.7: a token
    that leaves the battlefield ceases to exist, so it can never be
    sitting in a graveyard or library to search/reanimate).

    Same "not a universal `add_to_battlefield` hook" scope as its sibling
    above — a rarer uncast-entry route (a commander cheated out of the
    command zone, a bespoke "return this to the battlefield" delayed
    trigger) is a documented simplification, not a bug to chase down.
    """
    if not getattr(card, "is_creature", False):
        return False
    for ability in _battlefield_static_abilities(state):
        if ability.layer == "uncast_creature_entry_exile":
            return True
    return False


def max_spells_per_turn(state: "GameState") -> Optional[int]:
    """The most restrictive "Each player can't cast more than N spells each
    turn." cap in play (RULE 601-area — Eidolon of Rhetoric/Rule of Law/
    Archon of Emeria), or ``None`` if no such static applies.

    Global and player-agnostic by construction (all three seed cards say
    "each player", not "each opponent"/"you") — every player is held to the
    same, most-restrictive cap; `GameEngine.can_cast` compares it against
    `GameState.spells_cast_this_turn`.
    """
    limits = [
        ab.params.get("max_per_turn")
        for ab in _battlefield_static_abilities(state)
        if ab.layer == "cast_limit" and ab.params.get("max_per_turn") is not None
        and not ab.params.get("noncreature")
    ]
    return min(limits) if limits else None


def max_noncreature_spells_per_turn(state: "GameState") -> Optional[int]:
    """`max_spells_per_turn`'s noncreature-only sibling — "Each player
    can't cast more than N **noncreature** spells each turn." (Deafening
    Silence) — checked by `GameEngine.can_cast` against `GameState.
    noncreature_spells_cast_this_turn` only when the card being cast is
    itself noncreature; a creature spell is never capped by this static.
    """
    limits = [
        ab.params.get("max_per_turn")
        for ab in _battlefield_static_abilities(state)
        if ab.layer == "cast_limit" and ab.params.get("max_per_turn") is not None
        and ab.params.get("noncreature")
    ]
    return min(limits) if limits else None


def cast_prohibited(state: "GameState", player: "Player", card: Any, zone: Optional[str] = None) -> bool:
    """Whether a standing ``"cast_prohibition"`` static forbids ``player``
    from casting ``card`` right now (RULE 601.3a).

    The *conditional* sibling of `max_spells_per_turn`'s flat per-turn cap:
    instead of counting how many spells were cast, this vetoes a specific
    spell by its own characteristics, re-evaluated live against the board.
    Lavinia, Azorius Renegade — "Each opponent can't cast noncreature spells
    with mana value greater than the number of lands that player controls."
    — is the seed, and needs all three knobs together:

    * ``scope`` — whose casts are restricted, from the static's own source's
      controller: ``"opponents"`` (default) or ``"all"``.
    * ``noncreature`` — restrict only noncreature spells (RULE 302/307).
    * ``max_mana_value_selector`` — a `count_selector` name evaluated **for
      the casting player**, not the static's controller ("*that player*'s"
      lands): the spell is forbidden when its mana value exceeds that count.
      Omitted, the prohibition is unconditional on mana value.
    * ``max_mana_value`` — a **literal** threshold (MEC-43, Gaddock Teeg:
      "mana value 4 or greater can't be cast" — no board count involved at
      all) rather than a `count_selector` name; also accepts the sentinel
      ``"chosen_number"``, read live off ``ability.source.chosen_number``
      (Sanctum Prelate's own RULE 601.2b "as this enters, choose a number").
      Takes precedence over ``max_mana_value_selector`` when both are set.
    * ``cmp`` — how ``max_mana_value``/``max_mana_value_selector`` compares:
      ``"gt"`` (default — prohibited when mana value exceeds the threshold,
      the pre-existing behaviour) or ``"eq"`` (Sanctum Prelate: prohibited
      only when mana value *equals* the chosen number, everything else
      still castable).
    * ``has_x_cost`` — "Noncreature spells with {X} in their mana costs
      can't be cast." (Gaddock Teeg's second, independent clause) — a flat
      check on the card's own printed cost, unrelated to mana *value*.
    * ``even_mana_value`` — "…spells with even mana values. (Zero is
      even.)" (Void Winnower, MEC-12) — another independent flat check,
      same idiom as ``has_x_cost``.
    * ``nonartifact`` — the `noncreature` sibling scoped the other way:
      restrict only *nonartifact* spells (Ethersworn Canonist).
    * ``min_count_selector`` — MEC-43's Ethersworn Canonist: "Each player
      who has cast a nonartifact spell this turn can't cast additional
      nonartifact spells." — no mana-value component at all; prohibited
      once a `count_selector` read **for the casting player** is >= 1.
      Mutually exclusive with the mana-value knobs above (a static uses one
      family or the other).
    * ``hand_only`` — "…can't cast spells from anywhere other than their
      hands." (Drannith Magistrate) — restricted to the zone the card is
      actually being cast *from* (``zone``, RULE 601.2a), so an ordinary
      hand-cast is untouched but flashback/foretell/a graveyard-cast permit
      all become illegal.

    Kept out of the RULE 613 layer engine for the same reason
    ``cast_limit``/``draw_limit`` are — it changes what a player *may do*,
    not any object's characteristics — and consulted directly by
    `GameEngine.can_cast`.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cast_prohibition":
            continue
        controller_id = getattr(ability.source, "controller_id", None)
        # RULE 613.6's own gate ("During your turn, your opponents can't cast
        # spells …" — Grand Abolisher/Myrel, Shield of Argive), evaluated the
        # same way `group_selector_objects` does for every other static —
        # this loop just isn't routed through that helper (`cast_prohibition`
        # picks a *spell*, not a set of battlefield objects), so it needs its
        # own gate check rather than inheriting one for free.
        gate = ability.params.get("active_if") or static_conditions.condition_from_legacy_params(
            ability.params
        )
        if gate and not static_conditions.condition_holds(gate, state, ability.source, controller_id):
            continue
        if ability.params.get("player_id") is not None and ability.params["player_id"] != player.id:
            continue
        spell_types = ability.params.get("spell_types")
        if spell_types and not any(getattr(card, f"is_{word}", False) for word in spell_types):
            continue
        scope = ability.params.get("scope", "opponents")
        if scope == "opponents" and player.id in (None, controller_id):
            continue
        if ability.params.get("noncreature") and getattr(card, "is_creature", False):
            continue
        if ability.params.get("nonartifact") and getattr(card, "is_artifact", False):
            continue
        if ability.params.get("creature_only") and not getattr(card, "is_creature", False):
            continue
        color = ability.params.get("color")
        if color and color not in (getattr(card, "color_identity", None) or set()):
            # "Your opponents can't cast blue creature spells." (Llawan,
            # Cephalid Empress, MEC-43) — combines with ``creature_only``
            # above rather than duplicating it, the same additive-knob
            # idiom every other pair of flags here already uses.
            continue
        if ability.params.get("hand_only") and zone in (None, "hand"):
            continue
        if ability.params.get("type_from_source_mode"):
            # "Players can't cast spells of the chosen type." (MEC-43 round
            # 4D, Archon of Valor's Reach) — RULE 601.2b's own answer, read
            # live off `GameObject.chosen_mode` (`ChooseNamedModeReplacement`
            # slugs its printed option labels to lowercase, so "Artifact"
            # becomes "artifact" — exactly the ``is_<word>`` attribute name
            # a `Card` carries for each of the five real templates this
            # ever prints: artifact/enchantment/instant/sorcery/
            # planeswalker). No prohibition at all if the choice was never
            # made (a puzzle board that skipped battlefield entry).
            wanted = getattr(ability.source, "chosen_mode", None)
            if wanted is None or not getattr(card, f"is_{wanted}", False):
                continue
        zones = ability.params.get("zones")
        if zones and (zone is None or zone not in zones):
            # "Players can't cast noncreature spells from graveyards or
            # exile." (Soulless Jailer, MEC-43) — the zone-*allowlist*
            # sibling of ``hand_only``'s single-zone exemption, for a
            # prohibition scoped to specific non-hand zones instead.
            continue
        if ability.params.get("has_x_cost"):
            if "X" not in (getattr(card, "mana_cost_string", "") or ""):
                continue
            return True
        if ability.params.get("even_mana_value"):
            # Void Winnower (MEC-12): "spells with even mana values.
            # (Zero is even.)" — a latent bug fixed alongside MEC-43's own
            # `max_mana_value` addition (see the matching comment in
            # `effects.py`'s ``cast_prohibition`` factory).
            if getattr(card, "converted_mana_cost", 0) % 2 != 0:
                continue
            return True
        min_selector = ability.params.get("min_count_selector")
        if min_selector is not None:
            count = count_selector(state, player.id, str(min_selector), source=ability.source)
            if count < 1:
                continue
            return True
        literal = ability.params.get("max_mana_value")
        cmp = ability.params.get("cmp", "gt")
        if literal is not None:
            allowed = (
                getattr(ability.source, "chosen_number", None)
                if literal == "chosen_number" else literal
            )
            if allowed is None:
                # RULE 601.2b's choice was never made (a puzzle board that
                # skipped battlefield entry, or `chosen_number` still unset)
                # — fail closed to "no prohibition" rather than guessing.
                continue
            mv = getattr(card, "converted_mana_cost", 0)
            if cmp == "eq":
                if mv != allowed:
                    continue
            elif mv <= allowed:
                continue
        else:
            selector = ability.params.get("max_mana_value_selector")
            if selector is not None:
                allowed = count_selector(state, player.id, str(selector), source=ability.source)
                mv = getattr(card, "converted_mana_cost", 0)
                if cmp == "eq":
                    if mv != allowed:
                        continue
                elif mv <= allowed:
                    continue
        return True
    return False


def cost_restricted(state: "GameState", kind: str) -> bool:
    """Whether a standing static ("Players can't pay life or sacrifice
    nonland permanents to cast spells or activate abilities." — Yasharn,
    Implacable Earth, MEC-40) forbids paying a ``kind``-shaped cost
    component right now (RULE 601.2h/602.2b — additional/activation costs).

    ``kind`` is ``"pay_life"`` or ``"sacrifice_nonland_permanent"``. Global
    (no ``affects``/controller scoping — the printed "**Players** can't…"
    binds everyone, including Yasharn's own controller), checked at every
    cost-payment choke point that offers a ``pay_life``/``sacrifice``
    component (`GameEngine.can_cast`/`can_activate` and their paired
    ``_pay_*_cost`` methods) rather than as a `continuous.recompute` layer,
    the same "permission, not a characteristic" treatment `cast_prohibited`
    gets.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cost_restriction":
            continue
        if kind in (ability.params.get("kinds") or ()):
            return True
    return False


def split_second_active(state: "GameState") -> bool:
    """RULE 702.61a: whether a spell with split second is currently on the
    stack — while true, RULE 702.61b says players can't cast spells or
    activate abilities that aren't mana abilities (Legolas's Quick
    Reflexes, MEC-43). Mana abilities never reach this check at all: RULE
    605.3b keeps them off the stack entirely, so `GameEngine.tap_for_mana`/
    `activate_hand_mana_ability` never call `can_cast`/`can_activate` in
    the first place — no exemption needed here. Checked once at the top of
    both gates, the same standing-prohibition choke-point idiom
    `cost_restricted` above uses for Yasharn's own "can't pay life or
    sacrifice" restriction.
    """
    from . import combat  # function-scoped: combat imports this module

    return any(
        getattr(item, "kind", None) == "spell"
        and getattr(item, "obj", None) is not None
        and combat.has(item.obj, "split_second")
        for item in state.stack
    )


def granted_escape_for(state: "GameState", obj: "GameObject") -> Optional[dict[str, Any]]:
    """The ``"grant_escape"`` static granting ``obj`` Escape right now (RULE
    702.138 as a *granted* keyword), as its params dict, or ``None``.

    "Each nonland card in your graveyard has escape. The escape cost is
    equal to the card's mana cost plus exile three other cards from your
    graveyard." (Underworld Breach) — a layer-6 ability grant onto cards in
    a **graveyard**, which no printed-keyword scan and no battlefield
    selector could reach. Kept out of `recompute` proper for the same reason
    the other permission statics are: nothing about the affected object's
    *characteristics* changes, so there is no layer to write it into.

    ``nonland_only`` mirrors Underworld Breach's own restriction; the grant
    is scoped to the granting permanent's controller's own graveyard
    ("**your** graveyard"), so an opponent's graveyard is untouched.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "grant_escape":
            continue
        controller_id = getattr(ability.source, "controller_id", None)
        if controller_id is None:
            continue
        owner = next((p for p in state.players if p.id == controller_id), None)
        # Membership rather than a `Zone` comparison, so this module keeps
        # its no-runtime-`models`-import rule (see the module header) —
        # the same shape `_off_battlefield_objects` above already uses.
        if owner is None or obj not in owner.graveyard:
            continue
        if ability.params.get("nonland_only") and obj.card.is_land:
            continue
        granted_type = str(ability.params.get("card_type") or "").lower()
        if granted_type and not getattr(obj.card, f"is_{granted_type}", False):
            continue
        return dict(ability.params)
    return None


def granted_retrace_for(state: "GameState", obj: "GameObject") -> Optional[dict[str, Any]]:
    """The ``"grant_retrace"`` static granting ``obj`` Retrace right now
    (RULE 702.81 as a *granted* keyword), as its params dict, or ``None``.

    "Instant and sorcery cards in your graveyard have retrace." (Wrenn and
    Six's −7 emblem); "Merfolk and Druid cards in your graveyard have
    retrace." (Deeproot Historian); "…nonland permanent cards in your
    graveyard have retrace." (Six). The exact `granted_escape_for` idiom —
    a layer-6 ability grant onto cards in a **graveyard**, kept out of
    `recompute` proper (nothing about the card's characteristics changes),
    scoped to the granting permanent's controller's own graveyard.

    Optional filters, all AND-combined: ``card_types`` (a list of main-type
    words, ORed — "instant"/"sorcery"), ``subtypes`` (a list, ORed —
    "Merfolk"/"Druid"), ``nonland_only``. No filter = every card.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "grant_retrace":
            continue
        controller_id = getattr(ability.source, "controller_id", None)
        if controller_id is None:
            continue
        owner = next((p for p in state.players if p.id == controller_id), None)
        if owner is None or obj not in owner.graveyard:
            continue
        if ability.params.get("nonland_only") and obj.card.is_land:
            continue
        card_types = ability.params.get("card_types")
        if card_types and not any(_has_card_type(obj, str(t)) for t in card_types):
            continue
        subtypes = ability.params.get("subtypes")
        if subtypes and not any(_has_subtype(obj, str(s)) for s in subtypes):
            continue
        return dict(ability.params)
    return None


def extra_etb_counters_for(state: "GameState", obj: "GameObject") -> dict[str, int]:
    """Extra RULE 614.1-style entry counters ``obj`` gets from any live
    ``"extra_etb_counter"`` static (MEC-56 — Master Chef's twin-quoted
    grant), as ``{kind: total_amount}``. Called from `RulesEngine._apply_
    entry_counters` right after the object's own printed entry-counter
    condition, so a granted extra counter is present at the same moment a
    printed one would be — before `obj` is added to the battlefield and
    before ENTERS_BATTLEFIELD fires.

    Each qualifying ability contributes its own ``count`` for its own
    ``kind`` (summed across kinds and across multiple granting sources —
    real Magic doesn't merge two separate replacement effects into one).
    ``self_only`` scopes to the granting ability's own ``source`` (the
    commander creature "this creature enters with…" was granted to);
    unset scopes to every *other* creature that source's controller
    controls ("other creatures you control enter with…") — creature-only
    (`obj.is_creature`), matching both printed clauses' own wording.
    """
    totals: dict[str, int] = {}
    if not getattr(obj, "is_creature", False):
        return totals
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "extra_etb_counter":
            continue
        source = ability.source
        controller_id = getattr(source, "controller_id", None)
        if controller_id is None:
            continue
        if ability.params.get("self_only"):
            if obj is not source:
                continue
        elif ability.params.get("nontoken"):
            # "Nontoken creatures you control enter with…" (Gorma, the
            # Gullet) — includes the granting source itself if it's nontoken.
            if obj.controller_id != controller_id or getattr(obj, "is_token", False):
                continue
        elif ability.params.get("filter"):
            # PAR-139: "Each other Warrior creature you control enters with an additional +1/+1 counter
            # on it." / "Each Dragon you control enters with …" — a `combat.matches_object_filter` on the
            # entering object; the granting source is excluded unless the text says "each <X>" without
            # "other" (``other`` False — Dragonstorm Globe counts itself only if it is a Dragon).
            if obj.controller_id != controller_id:
                continue
            if obj is source and ability.params.get("other", True):
                continue
            from . import combat  # function-scoped: combat imports this module

            if not combat.matches_object_filter(obj, ability.params["filter"], reference=source, state=state):
                continue
        else:
            if obj.controller_id != controller_id or obj is source:
                continue
        # "Whenever you cast a creature spell with mana value 5 or greater, that creature enters with X additional
        # +1/+1 counters on it, where X is its mana value minus 4." (Runadi): only a *cast* creature, with a
        # mana-value floor, and an amount that scales with its mana value.
        if ability.params.get("cast_only") and not getattr(obj, "was_cast", False):
            continue
        mana_value = int(getattr(obj.card, "converted_mana_cost", 0) or 0)
        if mana_value < int(ability.params.get("min_mana_value", 0) or 0):
            continue
        kind = str(ability.params.get("kind", "+1/+1"))
        selector = ability.params.get("count_selector")
        if selector:
            amount = count_selector(state, controller_id, selector if isinstance(selector, dict) else str(selector), source)
        elif ability.params.get("count_per_artifact_mana"):
            # "…an additional +1/+1 counter on it for each mana from an artifact source spent to cast it." (Coin of Mastery)
            amount = int(getattr(obj, "mana_spent_to_cast_artifact", 0) or 0)
        elif ability.params.get("count_mana_value_minus") is not None:
            amount = max(0, mana_value - int(ability.params["count_mana_value_minus"]))
        else:
            amount = int(ability.params.get("count", 1) or 1)
        if amount:
            totals[kind] = totals.get(kind, 0) + amount
    return totals


def dungeon_room_trigger_doubler_bonus(state: "GameState", player_id: Optional[str]) -> int:
    """RULE 603.3d: how many *additional* times ``player_id``'s own RULE
    309.4c dungeon-room triggered ability should be placed on the stack
    (Dungeon Delver's "Room abilities of dungeons you own trigger an
    additional time.") — the `trigger_doubler_bonus`/`TriggerDoublerEffect`
    idiom (Roaming Throne), narrowed to a dungeon-room trigger specifically:
    that trigger is built off a `Dungeon` in the command zone
    (`RulesEngine._collect_dungeon_room_triggers`), never a battlefield
    `GameObject`, so `trigger_doubler_bonus`'s own ``obj: GameObject``
    signature can't reach it — consulted out-of-band, the
    `granted_escape_for`/`granted_retrace_for`/`extra_etb_counters_for`
    convention, instead.

    Every active ``dungeon_room_trigger_doubler`` whose granting source's
    controller is ``player_id`` contributes ``+1`` (additive stacking,
    same as every other RULE 603.3d doubler — two Dungeon Delvers make a
    room trigger three times, not four).
    """
    if player_id is None:
        return 0
    bonus = 0
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "dungeon_room_trigger_doubler":
            continue
        if getattr(ability.source, "controller_id", None) == player_id:
            bonus += 1
    return bonus


def max_draws_per_turn(state: "GameState", player: Optional["Player"] = None) -> Optional[int]:
    """The most restrictive "Each player can't draw more than N cards each
    turn." cap in play (RULE 121.5-adjacent — Spirit of the Labyrinth), or
    ``None`` if no such static applies. The draw-side mirror of
    `max_spells_per_turn`; `RulesEngine._single_draw` compares it against
    `GameState.cards_drawn_this_turn`.

    ``player`` (the one about to draw) scopes an ``affects="opponents"``
    static ("Each **opponent** can't draw more than one card each turn." —
    Narset, Parter of Veils) to skip its own controller — unlike Spirit of
    the Labyrinth's unqualified "each player", which stays global via the
    default ``affects="all"`` and applies regardless of ``player``.
    """
    limits = []
    for ab in _battlefield_static_abilities(state):
        if ab.layer != "draw_limit" or ab.params.get("max_per_turn") is None:
            continue
        if ab.affects == "opponents" and player is not None:
            controller_id = getattr(ab.source, "controller_id", None)
            if player.id in (None, controller_id):
                continue
        limits.append(ab.params["max_per_turn"])
    return min(limits) if limits else None


def has_no_untap_static(state: "GameState", obj: "GameObject") -> bool:
    """Whether ``obj`` is under a "doesn't untap during your untap step"
    static (RULE 502.3-adjacent — Basalt Monolith/Grim Monolith/Mana Vault's
    own self-restriction, or an Aura/Equipment's grant onto its host —
    Paralyzing Grasp's "enchanted creature doesn't untap during its
    controller's untap step").

    Goes through the ordinary ``affects``/selector machinery
    (`affected_objects`) like every other static family here, so both the
    self-scoped and ``"attached_permanent"``-scoped printings resolve the
    same way. Consulted by `GameEngine._step_untap` — a separate "{N}: Untap
    this artifact." activated ability (Basalt/Grim Monolith) or an "you may
    pay {4}. If you do, untap" trigger (Mana Vault) is an unrelated code path
    (an ordinary ``untap`` one-shot effect) and isn't affected by this
    restriction at all.
    """
    for ab in _battlefield_static_abilities(state):
        if ab.layer == "no_untap" and obj in affected_objects(state, ab):
            return True
        if ab.layer == "no_untap_optional" and obj.skip_untap and obj in affected_objects(state, ab):
            return True
    return False


def activates_as_though_haste(state: "GameState", obj: "GameObject") -> bool:
    """Whether a "you may activate abilities of creatures you control as though those creatures had haste"
    static (Thousand-Year Elixir, Shang-Chi, Tyvar; PAR-109) covers ``obj`` — RULE 302.6's tap-symbol
    restriction only; attacking still needs real haste."""
    return any(
        ab.layer == "activate_as_though_haste" and obj in affected_objects(state, ab)
        for ab in _battlefield_static_abilities(state)
    )


def untaps_in_every_untap_step(state: "GameState", obj: "GameObject") -> bool:
    """Whether ``obj`` carries "Untap ~ during each other player's untap step" (Bender's Waterskin, Thousand
    Moons Infantry, Endbringer, Victory Chimes; PAR-109) — consulted by `GameEngine._step_untap` for the
    permanents of the players whose untap step it is *not*."""
    return any(
        ab.layer == "untap_each_untap_step" and obj in affected_objects(state, ab)
        for ab in _battlefield_static_abilities(state)
    )


def has_optional_no_untap_permission(state: "GameState", obj: "GameObject") -> bool:
    """Whether ``obj`` carries a "you may choose not to untap ~ during your
    untap step" permission (RULE 502.1 — Rubinia Soulsinger/Hivis of the
    Scale/The Pandorica-shaped), regardless of whether `GameObject.
    skip_untap` is currently toggled on. Consulted by `GameEngine.
    set_skip_untap` to validate the toggle is actually legal before setting
    it — `has_no_untap_static` above is the gated "does it actually skip
    untapping right now" check the untap step itself uses.
    """
    return any(
        ab.layer == "no_untap_optional" and obj in affected_objects(state, ab)
        for ab in _battlefield_static_abilities(state)
    )


def extra_land_plays_for(state: "GameState", player: "Player") -> int:
    """How many *additional* lands ``player`` may play this turn, on top of
    the base one (RULE 305.2, Exploration/Dryad of the Ilysian Grove/Azusa-
    shaped) — every currently-active `"extra_land_drop"` static grant, summed
    (two Explorations really do stack). A ``affects="you"`` grant (the
    default — "you may play an additional land…") counts only for its own
    source's controller; ``affects="each_player"`` ("each player may play an
    additional land…", Rites of Flourishing/Storm Cauldron-shaped) counts for
    every player regardless of who controls the source. `GameEngine.
    can_play_land` also adds the one-turn `Player.extra_land_plays_this_turn`
    counter (`ExtraLandPlayEffect`'s resolve-time grant) on top of this.
    """
    total = 0
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "extra_land_drop":
            continue
        gate = ability.params.get("active_if")
        if gate and not static_conditions.condition_holds(gate, state, ability.source, ability.source.controller_id):
            continue
        if ability.affects == "each_player" or getattr(ability.source, "controller_id", None) == player.id:
            total += int(ability.params.get("count", 1))
    return total


def has_no_maximum_hand_size(state: "GameState", player: "Player") -> bool:
    """Whether ``player`` is exempt from RULE 402.2's cleanup-step maximum
    hand size right now ("You have no maximum hand size." — A-Wizard Class/
    Body of Knowledge-shaped, or the unscoped "Players have no maximum hand
    size." — Anvil of Bogardan-shaped, ``affects="each_player"``) — consulted
    by `GameEngine._step_cleanup` in place of the flat `MAX_HAND_SIZE`
    comparison. A resolve-time-granted, durational version of this exemption
    ("…for the rest of the game") is a different, unmodeled shape (Card-pool
    Batch 8's writeup).
    """
    # Spirit Water Revival — a resolve-time "…for the rest of the game"
    # grant, keyed by player id on `GameState` rather than a battlefield
    # static (RULE 400.7-safe, no duration to track).
    if player.id in getattr(state, "no_max_hand_size_player_ids", set()):
        return True
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "no_max_hand_size":
            continue
        if ability.affects == "each_player" or getattr(ability.source, "controller_id", None) == player.id:
            return True
    return False


def hand_size_modifier_for(state: "GameState", player: "Player") -> int:
    """Net RULE 402.2 maximum-hand-size adjustment for ``player`` — the
    numeric sibling of `has_no_maximum_hand_size`'s boolean exemption
    ("Each opponent's maximum hand size is reduced by seven." — Jin-
    Gitaxias, Core Augur, MEC-43). Consulted by `GameEngine._step_cleanup`
    alongside the boolean check, added to the flat `MAX_HAND_SIZE` before
    the excess comparison — never floored here, since a negative effective
    max just means "discard down to 0," which the ordinary excess math
    already handles correctly.

    ``affects``: ``"you"`` (default) scopes to the static's own controller
    (a hypothetical "your maximum hand size is increased by N"),
    ``"opponents"`` to everyone *except* the controller (Jin-Gitaxias'
    own scope), ``"each_player"`` to everyone — the same three-way
    vocabulary `cost_reduction_for`'s ``"your_spells"``/``"opponents_
    spells"`` pair establishes, plus the unscoped case `no_max_hand_size`
    already has.
    """
    modifier = 0
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "hand_size_modifier":
            continue
        controller_id = getattr(ability.source, "controller_id", None)
        affects = ability.affects
        if affects == "opponents":
            if controller_id is None or controller_id == player.id:
                continue
        elif affects == "each_player":
            pass
        else:  # "you" (default) — the static's own controller only
            if controller_id != player.id:
                continue
        # ``amount`` is a non-negative magnitude (`EffectSpec._clamp_
        # params` floors a literal negative int at 0); ``increase`` picks
        # the sign, the same "magnitude + direction flag" split
        # `cost_reduction`'s own `increase` param already uses.
        amount = int(ability.params.get("amount", 0))
        modifier += amount if ability.params.get("increase") else -amount
    return modifier


def counters_prohibited_for(state: "GameState", obj: "GameObject", kind: str, *, as_enters: bool = False) -> bool:
    """RULE 101.2 / 122: a standing prohibition overrides counter placement.

    Entry counters consult the permanent's own abilities as if it were on
    the battlefield (RULE 614.12). A shallow, read-only evaluation view keeps
    the ordinary group selectors without adding the entrant to real state.
    """
    view = state
    if as_enters and obj not in state.battlefield:
        view = copy.copy(state)
        view.battlefield = [*state.battlefield, obj]
    for ability in _battlefield_static_abilities(view):
        if (ability.layer == "counter_placement_prohibition"
                and ability.params.get("counter_kind") in (kind, "all")
                and not getattr(ability.source, "loses_all_abilities", False)
                and obj in affected_objects(view, ability)):
            return True
    return False


def player_cant_lose(state: "GameState", player: "Player") -> bool:
    """RULE 104.3b — a standing "You can't lose the game" static (Herald of Eternal Dawn) controlled by ``player``.
    Conceding (RULE 104.3a) is exempt and never asks."""
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cant_lose_game" or getattr(ability.source, "controller_id", None) != player.id:
            continue
        gate = ability.params.get("active_if")
        if gate and not static_conditions.condition_holds(gate, state, ability.source, player.id):
            continue
        return True
    return False


def player_cant_win(state: "GameState", player: "Player") -> bool:
    """RULE 104.3b — a standing "Your opponents can't win the game" static controlled by someone other than
    ``player`` (Herald of Eternal Dawn)."""
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "opponents_cant_win":
            continue
        controller_id = getattr(ability.source, "controller_id", None)
        if controller_id is None or controller_id == player.id:
            continue
        gate = ability.params.get("active_if")
        if gate and not static_conditions.condition_holds(gate, state, ability.source, controller_id):
            continue
        return True
    return False


def player_ignores_legend_rule(state: "GameState", player: "Player") -> bool:
    """Whether RULE 704.5j (the legend rule) is switched off for permanents
    ``player`` controls right now ("The 'legend rule' doesn't apply to
    permanents you control." — Sakashima of a Thousand Faces-shaped) —
    consulted by `RulesEngine._apply_legend_rule` in place of its ordinary
    same-name-same-controller SBA check. Same shape as
    `has_no_maximum_hand_size` above.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "ignore_legend_rule":
            continue
        if ability.affects == "each_player" or getattr(ability.source, "controller_id", None) == player.id:
            return True
    return False


def _printed_subtype_words(card: Any) -> set[str]:
    """Lowercase subtypes after the em dash of ``card``'s printed type line (empty if none)."""
    _, _, subtypes = (getattr(card, "type_line", "") or "").partition("—")
    return {w for w in subtypes.lower().split() if w}


def has_standing_flash_permission(state: "GameState", player: "Player", card: Any) -> bool:
    """Whether ``player`` may cast ``card`` at instant speed right now via a
    standing "You may cast spells as though they had flash." grant (High
    Fae Trickster/Valley Floodcaller-shaped) — the *blanket* sibling of
    `game/top_library.py`'s own permission family (scoped to a specific
    zone/card, not every spell a player might cast). ``noncreature_only``/
    ``creature_only`` narrow it the same way a real card's own wording can
    ("you may cast **noncreature** spells as though they had flash.").
    Consulted directly by `GameEngine.can_cast`'s timing check, the same
    non-layer-engine treatment `cast_limit`/`cast_prohibited` get (a
    permission, not a characteristic).
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "flash_permission":
            continue
        if getattr(ability.source, "controller_id", None) != player.id:
            continue
        if ability.params.get("noncreature_only") and getattr(card, "is_creature", False):
            continue
        if ability.params.get("creature_only") and not getattr(card, "is_creature", False):
            continue
        # "You may cast **green** creature spells as though they had flash." (Yeva, Nature's Herald)
        color = ability.params.get("color")
        if color and str(color).upper() not in (getattr(card, "color_identity", None) or set()):
            continue
        type_filter = ability.params.get("type_filter")
        if type_filter:
            words = {str(w).lower() for w in type_filter}
            matches = (
                ("legendary" in words and getattr(card, "is_legendary", False))
                or ("artifact" in words and getattr(card, "is_artifact", False))
                or ("creature" in words and getattr(card, "is_creature", False))
                # "You may cast **sorcery** spells as though they had
                # flash." (Teferi, Time Raveler's own +1, MEC-42).
                or ("sorcery" in words and bool(getattr(card, "is_sorcery", False)))
                # "You may cast sorcery spells and **Dragon** spells as though they had flash."
                # (Whirlwing Stormbrood) — any other word is a subtype of the card's printed type line.
                or bool(words & _printed_subtype_words(card))
            )
            if not matches:
                continue
        gate = ability.params.get("active_if")
        controller_id = getattr(ability.source, "controller_id", None)
        if gate and not static_conditions.condition_holds(gate, state, ability.source, controller_id):
            continue
        return True
    return False


def _active_free_cast_permission(
    state: "GameState", player: "Player", card: Any, obj: Any = None
) -> Optional[StaticAbility]:
    """The first active ``"free_cast_permission"`` static (Aluren-shaped:
    "Any player may cast creature spells with mana value N or less without
    paying their mana costs and as though they had flash.") that covers
    ``player`` casting ``card`` right now, or ``None``.

    Deliberately its own static kind rather than widening the pre-existing
    `has_standing_flash_permission`'s ``flash_permission`` layer: that one
    is a *pure* flash grant with no cost component, always scoped to the
    granting permanent's own controller (High Fae Trickster/Valley
    Floodcaller/Gandalf the White/Teferi, Time Raveler-shaped) — Aluren
    bundles a free cost *and* flash into one indivisible permission and,
    printed "**any** player", is deliberately *not* controller-scoped at
    all (``any_player=True`` skips that check entirely) — different enough
    in both dimensions that reusing the same layer would have meant a
    third param just to turn its own controller check off for everyone
    else's benefit too.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "free_cast_permission":
            continue
        if not ability.params.get("any_player") and (
            getattr(ability.source, "controller_id", None) != player.id
        ):
            continue
        if ability.params.get("creature_only") and not getattr(card, "is_creature", False):
            continue
        # "You may cast spells **from your hand** without paying their mana costs" (Tamiyo, Field Researcher's
        # emblem): the permission covers a spell cast from the hand only, read off the card object being cast.
        if ability.params.get("from_hand") and getattr(getattr(obj, "zone", None), "value", None) != "hand":
            continue
        zones = ability.params.get("zones")
        if zones and getattr(getattr(obj, "zone", None), "value", None) not in zones:
            continue
        if ability.params.get("once_per_turn") and _once_per_turn_spent(state, "free_cast", ability):
            continue
        max_mv = ability.params.get("max_mana_value")
        if max_mv is not None and getattr(card, "converted_mana_cost", 0) > max_mv:
            continue
        gate = ability.params.get("active_if")
        controller_id = getattr(ability.source, "controller_id", None)
        if gate and not static_conditions.condition_holds(gate, state, ability.source, controller_id):
            continue
        return ability
    return None


def _once_per_turn_spent(state: "GameState", kind: str, ability: Any) -> bool:
    """Whether a "once during each of your turns" standing grant (``kind``, its source) was used this turn."""
    used = getattr(state, "once_per_turn_grants_used", None) or {}
    return used.get((kind, getattr(ability.source, "instance_id", None))) == state.internal_turn.number


def note_free_cast_permission_used(state: "GameState", player: "Player", card: Any, obj: Any = None) -> None:
    """Spend the "once during each of your turns" standing free-cast grant covering this cast, if there is one."""
    ability = _active_free_cast_permission(state, player, card, obj)
    if ability is not None and ability.params.get("once_per_turn"):
        state.once_per_turn_grants_used[("free_cast", ability.source.instance_id)] = state.internal_turn.number


def has_standing_free_cast_permission(
    state: "GameState", player: "Player", card: Any, obj: Any = None,
) -> bool:
    """Whether ``player`` may cast ``card`` right now without paying its
    mana cost, via a standing "Any player may cast `<filter>` spells
    without paying their mana costs …" grant (Aluren) — consulted by
    `GameEngine.can_cast`'s ``free=True`` branch alongside the existing
    per-object `GameObject.free_cast_condition` (RULE 601.2f), and by
    `_offer_cast`/`_castable_now_or_via_potential`'s own offer-time guard,
    neither of which previously had any board-wide, class-of-spells
    permission to check — only a condition already bound onto the specific
    object being cast.
    """
    return _active_free_cast_permission(state, player, card, obj) is not None


def standing_free_cast_grants_flash(
    state: "GameState", player: "Player", card: Any, obj: Any = None,
) -> bool:
    """Whether the standing free-cast permission covering ``card`` (if any)
    also grants flash timing for *that same cast* (Aluren's own trailing
    "and as though they had flash").

    Deliberately consulted only when the caller is actually resolving a
    ``free=True`` cast (`GameEngine.can_cast`'s sorcery-speed check) —
    Aluren's flash exemption is part of *its own* permission, not a
    blanket "this creature always has flash" grant: paying the card's real
    mana cost at sorcery speed is still just an ordinary cast, unaffected.
    """
    ability = _active_free_cast_permission(state, player, card, obj)
    return ability is not None and bool(ability.params.get("grants_flash"))


def granted_alt_cast_cost_for(
    state: "GameState", player: "Player", card: Any
) -> Optional[Any]:
    """An `ActivationCost` a standing ``"granted_alt_cast_cost"`` static
    (Conspiracy Unraveler — "You may collect evidence N rather than pay the
    mana cost for spells you cast.") lets ``player`` pay in place of
    ``card``'s mana cost right now, or ``None``.

    The RULE 118.9 *alternative cost* sibling of
    `_active_free_cast_permission` (Aluren): that one is genuinely free,
    this replaces the mana cost with a payable non-mana cost. Controller-
    scoped, with the same optional ``creature_only`` / ``max_mana_value``
    narrowing.
    """
    from .costs import parse_activation_cost  # function-scoped: import cycle

    for ability in _battlefield_static_abilities(state):
        if ability.layer != "granted_alt_cast_cost":
            continue
        if getattr(ability.source, "controller_id", None) != player.id:
            continue
        if ability.params.get("creature_only") and not getattr(card, "is_creature", False):
            continue
        max_mv = ability.params.get("max_mana_value")
        if max_mv is not None and getattr(card, "converted_mana_cost", 0) > max_mv:
            continue
        # "…permanent spells you cast" (Nissa, Worldsoul Speaker): no instant or sorcery.
        if ability.params.get("permanent_only") and (
            getattr(card, "is_instant", False) or getattr(card, "is_sorcery", False)
        ):
            continue
        card_type = str(ability.params.get("card_type") or "").lower()
        if card_type and not getattr(card, f"is_{card_type}", False):
            continue
        if ability.params.get("once_per_turn") and _once_per_turn_spent(state, "alt_cost", ability):
            continue
        n = int(ability.params.get("collect_evidence") or 0)
        energy = int(ability.params.get("pay_energy") or 0)
        if ability.params.get("pay_life_equal_mv"):
            # "…by paying life equal to its mana value rather than paying its mana cost" (Demon of Fate's Design).
            cost = parse_activation_cost({"pay_life": int(getattr(card, "converted_mana_cost", 0) or 0)})
        elif n <= 0 and energy <= 0:
            continue
        else:
            # "You may pay eight {E} rather than pay the mana cost…" — the energy sibling of collect evidence (RULE 118.9).
            cost = parse_activation_cost({"collect_evidence": n} if n > 0 else {"pay_energy": energy})
        if ability.params.get("once_per_turn"):
            cost.grant_key = ("alt_cost", ability.source.instance_id)
        return cost
    return None


def stun_counters_locked(state: "GameState", obj: Any) -> bool:
    """RULE 122.1c with a lock: "Stun counters can't be removed from permanents your opponents control." (Fear of
    Sleep Paralysis) — true while a ``"stun_lock"`` static on the battlefield belongs to a player who is an opponent of
    ``obj``'s controller. A permanent whose stun counter can't be removed simply stays tapped."""
    controller_id = getattr(obj, "controller_id", None)
    return any(
        ability.layer == "stun_lock"
        and getattr(ability.source, "controller_id", None) not in (None, controller_id)
        for ability in _battlefield_static_abilities(state)
    )


def granted_miracle_cost_for(state: "GameState", player: "Player", obj: Any) -> Optional["ManaCost"]:
    """The Miracle cost a standing ``"grant_miracle"`` static gives ``obj`` (a card ``player`` just drew), or ``None``.

    "Each enchantment card in your hand has miracle. Its miracle cost is equal to its mana cost reduced by {4}."
    (Aminatou, Veil Piercer, RULE 702.94) — the card's printed mana cost minus ``reduce_generic`` generic mana (never
    below zero), for a card of the named ``card_type`` in the granting permanent's controller's hand.
    """
    from ..models.mana.mana_cost import ManaCost  # local: avoid a continuous<->models import cycle

    card = getattr(obj, "card", None)
    if card is None or card.is_land:
        return None
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "grant_miracle":
            continue
        if getattr(ability.source, "controller_id", None) != player.id:
            continue
        wanted = str(ability.params.get("card_type") or "").lower()
        if wanted and not getattr(card, f"is_{wanted}", False):
            continue
        return ManaCost.from_card(card).reduce_generic(int(ability.params.get("reduce_generic") or 0))
    return None


def granted_evoke_cost_for(state: "GameState", obj: Any) -> Optional["ManaCost"]:
    """Whether ``obj`` (a card still in hand, being considered for casting)
    has been granted Evoke by a standing battlefield static ("Elemental
    permanent spells you cast from your hand gain evoke {4} as you cast
    them." — Ashling, the Limitless, MEC-42) — the hand-cast-cost sibling
    of `has_standing_flash_permission`'s own "permission static outside the
    layer engine" idiom, since a card sitting in hand has no `static_trace`
    of its own for RULE 613's layer engine to have stamped anything onto.
    Returns the granted cost as a `ManaCost`, or ``None``.
    """
    from ..models.mana.mana_cost import ManaCost  # local: avoid a continuous<->models import cycle

    card = getattr(obj, "card", None)
    if card is None:
        return None
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "grant_evoke":
            continue
        if getattr(ability.source, "controller_id", None) != getattr(obj, "controller_id", None):
            continue
        cost = ability.params.get("cost")
        if not cost:
            continue
        subtype = ability.params.get("subtype")
        if subtype:
            sub = (getattr(card, "type_line", "") or "").partition("—")[2].strip().lower().split()
            if str(subtype).lower() not in sub:
                continue
        return ManaCost.parse(str(cost))
    return None


def granted_offspring_cost_for(state: "GameState", obj: Any) -> Optional["ManaCost"]:
    """RULE 702.175: the Offspring cost a standing battlefield static grants ``obj`` (a creature card being
    cast) — "Creature spells you cast gain offspring {2} as you cast them." (Zinnia, Valley's Voice). The
    offspring sibling of `granted_evoke_cost_for`; ``None`` when no static applies or ``obj`` isn't a creature.
    """
    from ..models.mana.mana_cost import ManaCost  # local: avoid a continuous<->models import cycle

    card = getattr(obj, "card", None)
    if card is None or not getattr(card, "is_creature", False):
        return None
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "grant_offspring":
            continue
        if getattr(ability.source, "controller_id", None) != getattr(obj, "controller_id", None):
            continue
        cost = ability.params.get("cost")
        if cost:
            return ManaCost.parse(str(cost))
    return None


def any_color_for_activation(state: "GameState", player: "Player", source: "GameObject") -> Optional[str]:
    """The `ManaPool` ``wildcard`` token to use when ``player`` pays
    ``source``'s activation cost right now (RULE 605.1a-adjacent wildcard
    permission), or ``None`` if no such grant applies.

    Returns ``"color"`` for an unrestricted grant (MEC-21 — Agatha's Soul
    Cauldron's "You may spend mana as though it were mana of any color to
    activate abilities of creatures you control.": any of the five colors
    pays any colored pip) — or a single WUBRG letter for a grant narrowed to
    *one* source color (MEC-23 — Quicksilver Elemental's "You may spend
    **blue** mana as though it were mana of any color to pay the activation
    costs of this creature's abilities.": only blue mana substitutes, see
    `ManaPool._solve`'s matching branch). Consulted by `game/engine/
    activation_mixin.py`'s cost-paying trio (`_max_x_for_mana`/
    `_can_pay_activation_cost`/`_pay_activation_cost`), which pass the
    result straight on to `ManaPool.can_pay`/`pay`'s own ``wildcard`` param
    (already shipped for the RULE 605.1a *casting*-side grant, `GameState.
    mana_wildcard_permission`).

    Same "permission static outside the layer engine proper" treatment as
    `has_no_maximum_hand_size`/`no_untap_optional` — this isn't a
    characteristic of ``source`` itself, so RULE 613's layer engine has no
    slot for it. ``creature_abilities_only`` (every printed card so far)
    scopes the grant to abilities whose *source* is a creature; a future
    card without that restriction would set it ``False``. ``self_only``
    (MEC-23) narrows the grant to abilities whose source is this *exact*
    granting permanent, rather than Agatha's unscoped "creatures you
    control" (any creature the grant's controller controls).
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "any_color_for_activation":
            continue
        if ability.params.get("creature_abilities_only", True) and not getattr(source, "is_creature", False):
            continue
        if ability.params.get("self_only"):
            if ability.source is not source:
                continue
        elif not (ability.affects == "each_player" or getattr(ability.source, "controller_id", None) == player.id):
            continue
        return ability.params.get("from_color") or "color"
    return None


def has_radiation_life_gain(state: "GameState", player: "Player") -> bool:
    """RULE 728.1a: "You gain life rather than lose life from radiation."
    (Strong, the Brutish Thespian) — consulted by `RulesEngine.lose_life`
    before applying a ``cause="radiation"`` life loss, same "permission
    static outside the layer engine proper" treatment as
    `has_no_maximum_hand_size`/`no_untap_optional`.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "radiation_life_gain":
            continue
        if ability.affects == "each_player" or getattr(ability.source, "controller_id", None) == player.id:
            return True
    return False


def pip_life_options_for(
    state: "GameState", player: "Player", obj: Optional["GameObject"],
) -> list[tuple[str, int]]:
    """The ``(colour, how many pips)`` a spell may pay 2 life for instead of that coloured mana — "As an
    additional cost to cast green permanent spells, you may pay 2 life. Those spells cost {G} less to cast
    if you paid life this way. This effect reduces only the amount of green mana you pay." (Defiler of
    Vigor). Net effect: one ``{G}`` of a green permanent spell becomes ``{G/P}`` (see
    `ManaCost.with_phyrexian_pips`). ``spell_type`` is a `_spell_type_matches` word/list and ``spell_color``
    a WUBRG letter, both read off the spell being cast; with no spell (an offer-time probe) nothing
    applies. Read off the standing ``pip_life_option`` static, outside the layer engine."""
    if obj is None or cost_restricted(state, "pay_life"):
        return []
    options: list[tuple[str, int]] = []
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "pip_life_option":
            continue
        if getattr(ability.source, "controller_id", None) != player.id:
            continue
        spell_color = ability.params.get("spell_color")
        if spell_color and spell_color not in (obj.colors or ()):
            continue
        spell_type = ability.params.get("spell_type")
        if spell_type and not _spell_type_matches(obj, spell_type):
            continue
        options.append((str(ability.params.get("color", "G")), int(ability.params.get("pips", 1))))
    return options


def life_for_mana_pip_color(state: "GameState", player: "Player") -> Optional[str]:
    """The single WUBRG letter ``player`` may pay `mana_pool.
    KRRIK_LIFE_PER_BLACK_PIP` life for instead of a plain colored pip of
    that color, in *any* cost they pay right now (MEC-43 — K'rrik, Son of
    Yawgmoth: "For each {B} in a cost, you may pay 2 life rather than pay
    that mana."), or ``None`` if no such grant applies.

    Broader than every existing wildcard-color mechanism
    (`any_color_for_activation`/RULE 605.1a's own mana_wildcard_permission,
    both of which only ever relax *which* mana pays a pip) — this instead
    adds a way to skip paying mana for the pip at all, mirroring a printed
    Phyrexian pip's own life option (`models/mana_cost.ManaSymbol.
    payment_options`) but conferred by a standing permission rather than
    printed on the symbol. Consulted by both the casting and activation
    cost-payment sites (`game/engine/casting_mixin.py`'s `can_cast`, `game/
    rules/casting_mixin.py`'s actual payment, `game/engine/
    activation_mixin.py`'s `_can_pay_activation_cost`/`_pay_activation_cost`)
    and passed straight on to `ManaPool.can_pay`/`pay`'s ``extra_life_color``
    param — same "permission static outside the layer engine proper"
    treatment as `any_color_for_activation`. Same "you"-scoped ``affects``
    convention as `has_radiation_life_gain`; unlike that helper, only one
    grant can ever matter for a given color (there's nothing to "stack").
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "life_for_mana_pip":
            continue
        if ability.affects == "each_player" or getattr(ability.source, "controller_id", None) == player.id:
            return ability.params.get("color", "B")
    return None


def active_untap_caps(state: "GameState") -> list[dict[str, Any]]:
    """Every currently-active "players can't untap more than N `<type>`
    during their untap steps" restriction (RULE 502.3-adjacent — Winter
    Orb's lands, Static Orb's permanents, Winter Moon's nonbasic lands),
    each as ``{"count", "card_type", "nonbasic"}``.

    Unlike `has_no_untap_static` (a single permanent's own restriction) or
    `enters_tapped_from_static` (a board-wide but ownership-scoped effect),
    this is a flat, unscoped-by-controller cap that applies to *every*
    player's untap step identically. Any tap-state gate a card prints
    ("as long as this artifact is untapped" — Winter Orb/Static Orb) rides
    the ordinary ``active_if`` RULE 613.6 wrapper like any other conditional
    static, rather than a hardcoded tapped check — Winter Moon prints no
    such gate and is unconditional. 2+ simultaneous instances don't merge
    into one cap (RULE 613's "most restrictive" doesn't quite apply either —
    real Magic has each Orb/Static Orb/Winter Moon enforce its own cap
    independently), so `GameEngine._step_untap` checks each entry this
    returns against its own running count rather than a single combined one.
    """
    caps: list[dict[str, Any]] = []
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "untap_cap":
            continue
        active_if = ability.params.get("active_if")
        if active_if:
            controller_id = getattr(ability.source, "controller_id", None)
            if not static_conditions.condition_holds(active_if, state, ability.source, controller_id):
                continue
        caps.append(
            {
                "count": ability.params.get("count", 1),
                "card_type": ability.params.get("card_type", "land"),
                "nonbasic": bool(ability.params.get("nonbasic")),
            }
        )
    return caps


def all_untap_steps_skipped(state: "GameState") -> bool:
    """RULE 502.3-adjacent "Players skip their untap steps." (Stasis) —
    unlike `active_untap_caps` (a *count* limit) this is unconditional and
    total, so `GameEngine._step_untap` checks it once up front rather than
    per-permanent; Stasis's own tap-state gate ("as long as this artifact is
    untapped, …" — it doesn't print one, but a hypothetical future card
    could) rides the ordinary ``active_if`` wrapper like any other
    conditional static.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "skip_untap_step":
            continue
        active_if = ability.params.get("active_if")
        if active_if:
            controller_id = getattr(ability.source, "controller_id", None)
            if not static_conditions.condition_holds(active_if, state, ability.source, controller_id):
                continue
        return True
    return False


def matches_untap_cap_filter(obj: "GameObject", cap: dict[str, Any]) -> bool:
    """Whether ``obj`` counts toward an `active_untap_caps` entry's cap —
    its ``card_type`` (``_has_card_type``, "permanent" always matches) plus
    an optional ``nonbasic`` land narrowing (Winter Moon), the same two
    filters `group_selector_objects` applies for every other static family.
    """
    if not _has_card_type(obj, cap["card_type"]):
        return False
    if cap.get("nonbasic") and not (obj.is_land and _is_nonbasic(obj)):
        return False
    return True


def trigger_suppressed(state: "GameState", event: Any) -> bool:
    """Whether a global static ("Creatures entering don't cause abilities to
    trigger." — RULE 603, Tocatli Honor Guard/Hushwing Gryff/Torpor Orb)
    blocks every triggered ability from firing off ``event`` right now.

    Checked once per event (`RulesEngine._collect_triggers`, the single
    choke point both a permanent's own `triggered_abilities` and a layer-6
    `granted_triggered_abilities` go through) rather than per-ability —
    cheaper, and it naturally covers *both* the entering creature's own ETB
    trigger and any other permanent's "whenever a creature enters" trigger
    reacting to the same event, matching the real card's scope. Global: unlike
    every ``affects`` selector above, this isn't scoped to the static's own
    controller — Torpor Orb silences ETB triggers for *every* player's
    creatures, not just its controller's.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "trigger_prohibition":
            continue
        if ability.params.get("scope", "all") != "all":
            # Opponent-scoped (Elesh Norn, Mother of Machines, MEC-40) —
            # this fast global path can't answer "whose ability", so it's
            # checked per-object instead by `trigger_suppressed_for`.
            continue
        if ability.params.get("event") != event.type:
            continue
        subject_type = ability.params.get("subject_type")
        if subject_type and subject_type not in (event.get("object_types") or []):
            continue
        return True
    return False


def trigger_suppressed_for(state: "GameState", event: Any, controller_id: Optional[str]) -> bool:
    """The opponent-scoped sibling of `trigger_suppressed` above — "Permanents
    entering don't cause abilities of permanents **your opponents**
    control to trigger." (Elesh Norn, Mother of Machines, MEC-40).

    Unlike the ``scope="all"`` case, this can't be decided once for the
    whole event: it depends on whose ability would fire, so
    `RulesEngine._collect_triggers` checks it per candidate object
    (``controller_id``) rather than upfront.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "trigger_prohibition" or ability.params.get("scope") != "opponents":
            continue
        if ability.params.get("event") != event.type:
            continue
        subject_type = ability.params.get("subject_type")
        if subject_type and subject_type not in (event.get("object_types") or []):
            continue
        source_controller = getattr(ability.source, "controller_id", None)
        if source_controller is None or source_controller == controller_id:
            continue  # not an opponent of the static's own controller
        return True
    return False


def enters_untapped_from_static(state: "GameState", obj: "GameObject") -> bool:
    """"Lands you control enter untapped." (Horizon Explorer) — whether a standing ``enters_untapped`` static
    makes the land ``obj`` enter untapped, overriding its own tapped-entry clause (the printed text is the
    permission: it replaces "enters tapped", RULE 614.1). Only the static's controller's lands."""
    if not getattr(obj, "is_land", False):
        return False
    return any(
        ability.layer == "enters_untapped"
        and getattr(ability.source, "controller_id", None) == obj.controller_id
        for ability in _battlefield_static_abilities(state)
    )


def enters_tapped_from_static(state: "GameState", obj: "GameObject") -> bool:
    """Whether a board-wide static ("Artifacts your opponents control enter
    tapped." — RULE 614.1, Manglehorn/Dauntless Dismantler/Archon of
    Emeria-shaped; or an unscoped "Artifacts and lands enter tapped." — Root
    Maze-shaped, ``affects="all_permanents"``, no ownership restriction at
    all) forces ``obj`` to enter tapped right now.

    Distinct from `card_registry.enters_tapped` (a card's own printed
    tapped-entry clause about *itself*) — this is a *different* permanent's
    standing effect. Checked at the moment ``obj`` is about to join the
    battlefield (`RulesEngine._resolve_permanent_spell`/token creation),
    before it's actually added to `state.battlefield` — so unlike every
    other consult in this module, it can't go through `affected_objects`
    (which only ever scans *existing* battlefield membership); the
    ``opponents_permanents``/``all_permanents``/``card_type``/``nonbasic``
    filters are applied to ``obj`` directly instead, duplicating that small
    slice of `group_selector_objects`'s narrowing logic rather than the
    whole battlefield-scanning shape.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "enters_tapped":
            continue
        if ability.affects != "all_permanents":
            controller = getattr(ability.source, "controller_id", None)
            if controller is None or obj.controller_id in (None, controller):
                continue  # not "your opponents" from the static's own perspective
        card_type = ability.params.get("card_type")
        if card_type and not _has_card_type(obj, str(card_type)):
            continue
        if ability.params.get("nonbasic") and not _is_nonbasic(obj):
            continue
        return True
    return False


#: Static "layer" buckets that aren't a real RULE 613 layer at all (each
#: `StaticAbility.LAYER_NUMBERS.get(..., 99)` defaults to the same numeric
#: bucket "cost" already used) — shown as their own named ``kind`` in the
#: UI's layer-trace panel rather than a bare "99", same treatment "cost"
#: already got before any of these existed.
_NON_RULE_613_LAYERS: frozenset[str] = frozenset(
    {"cost", "no_untap", "no_untap_optional", "untap_each_untap_step", "activate_as_though_haste", "enters_tapped", "activation_prohibition",
     "cast_limit", "cast_prohibition", "draw_limit", "trigger_prohibition", "untap_cap",
     "extra_land_drop", "no_max_hand_size", "hand_size_modifier", "ignore_legend_rule", "radiation_life_gain", "grant_escape", "grant_retrace",
     "combat_restriction", "goaded", "any_color_for_activation", "skip_untap_step",
     "graveyard_library_cast_prohibition", "graveyard_library_entry_prohibition",
     "uncast_creature_entry_exile",
     "mana_multiplier", "mana_type_override", "skip_step", "search_redirect",
     "cost_restriction", "life_gain_prohibition",
     "damage_prevention_prohibition", "global_wither", "attack_tax", "block_tax", "cant_lose_game", "opponents_cant_win", "player_hexproof",
     "mana_wildcard", "retain_mana", "unspent_mana_colorless", "spell_help_pay_grant", "entry_counters_self", "counter_placement_prohibition"}
)


def empty_mana_pool(state: "GameState", player: "Player", expire: tuple[str, ...] = ()) -> None:
    """RULE 500.4: empty ``player``'s pool as a step or phase ends — except mana of a colour a standing
    ``retain_mana`` static they control lets them keep ("You don't lose unspent red mana as steps and
    phases end.", Leyline Tyrant; ``colors`` absent means every colour, Omnath-shaped). Unrestricted
    pool mana only; restricted lots empty as ever."""
    colors: Optional[set[str]] = set()
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "retain_mana" or getattr(ability.source, "controller_id", None) != player.id:
            continue
        listed = ability.params.get("colors")
        if not listed:
            colors = None  # every colour
            break
        colors.update(str(c).upper() for c in listed)
    pool = player.mana_pool
    keep = {
        c: n for c, n in pool.pool.items() if n and (colors is None or c.upper() in colors)
    } if colors != set() else {}
    # RULE 614.1 — "If you would lose unspent mana, that mana becomes colorless instead." (Omnath, Locus of the Void):
    # what would be lost (the unrestricted mana not kept above) stays in the pool as colourless. Restricted lots empty as ever.
    to_colorless = any(
        ability.layer == "unspent_mana_colorless" and getattr(ability.source, "controller_id", None) == player.id
        for ability in _battlefield_static_abilities(state)
    )
    before = dict(pool.pool)
    pool.empty(expire=expire)
    lost_to_colorless = (
        sum(n - pool.pool.get(c, 0) for c, n in before.items() if n and c not in keep) if to_colorless else 0
    )
    for color, amount in keep.items():
        pool.add(color, amount)
    if lost_to_colorless:
        pool.add("C", lost_to_colorless)


#: A `combat_restriction` entry → the one-line description the board's
#: static-effect panel shows (both as a per-object `static_trace` row and in
#: `active_static_abilities`). Kept terse and English like every other
#: `_describe_ability` string.
def _describe_combat_restriction(entry: dict[str, Any]) -> str:
    kind = entry.get("kind")
    if kind == "cant_be_blocked_by":
        return "can't be blocked by " + _describe_filter(entry.get("filter"))
    if kind == "only_blocked_by":
        return "can't be blocked except by " + _describe_filter(entry.get("filter"))
    if kind == "max_blockers":
        return f"can't be blocked by more than {entry.get('count', 1)} creature(s)"
    if kind == "min_blockers":
        return f"can't be blocked except by {entry.get('count', 2)} or more creatures"
    if kind == "cant_be_blocked_if_attacking_alone":
        return "can't be blocked while attacking alone"
    if kind == "cant_attack_alone":
        return "can't attack alone"
    if kind == "cant_block_alone":
        return "can't block alone"
    if kind in ("cant_attack_unless", "cant_block_unless"):
        verb = "attack" if kind == "cant_attack_unless" else "block"
        return f"can't {verb} unless " + _describe_condition(entry.get("condition"))
    if kind == "extra_blocks":
        return f"can block {entry.get('count', 1)} additional creature(s) each combat"
    if kind == "unlimited_blocks":
        return "can block any number of creatures"
    if kind == "must_block_target":
        return "must block a specific creature this turn if able"
    if kind == "must_block_if_able":
        return "blocks this turn if able"
    return str(kind or "combat restriction")


def _describe_filter(filt: Optional[dict[str, Any]]) -> str:
    if not filt:
        return "creatures"
    bits: list[str] = []
    for key, label in (("subtype", ""), ("color", ""), ("card_type", "")):
        if filt.get(key):
            bits.append(str(filt[key]))
    if filt.get("subtype_any"):
        bits.append(" or ".join(str(s) for s in filt["subtype_any"]))
    if filt.get("min_power") is not None:
        bits.append(f"power {filt['min_power']}+")
    if filt.get("max_power") is not None:
        bits.append(f"power {filt['max_power']} or less")
    if filt.get("keyword"):
        bits.append(str(filt["keyword"]))
    if filt.get("keyword_any"):
        bits.append(" or ".join(str(k) for k in filt["keyword_any"]))
    if filt.get("power_vs_reference"):
        bits.append(f"{filt['power_vs_reference']} power")
    return (" ".join(bits) + " creatures").strip()


def _describe_condition(condition: Optional[dict[str, Any]]) -> str:
    if not condition:
        return "(unconditional)"
    return str(condition.get("kind", "a condition")).replace("_", " ")


def active_static_abilities(state: "GameState") -> list[dict[str, Any]]:
    """A flat summary of every static ability in play, for the UI's panel.

    Carries the two *bounds* a continuous effect can have alongside what it
    does, since neither is visible anywhere else on the board: ``duration``
    (RULE 611 — when it ends, empty for a standing one) and ``condition``
    (RULE 613.6's "as long as" gate), plus ``active``, whether that gate holds
    right now. A gated static that is currently *off* still appears in the
    list — it is genuinely in play and will apply again — but says so, which
    is the whole reason the condition is worth showing.
    """
    summary: list[dict[str, Any]] = []
    for ability in _battlefield_static_abilities(state):
        src = ability.source
        controller_id = getattr(src, "controller_id", None)
        gate = ability.params.get("active_if") or static_conditions.condition_from_legacy_params(
            ability.params
        )
        summary.append(
            {
                "source": _source_name(ability),
                "layer": ability.layer if ability.layer in _NON_RULE_613_LAYERS else ability.layer_number,
                "kind": ability.layer,
                "affects": ability.affects,
                "description": ability.description or _describe_ability(ability),
                "duration": durations.describe(ability),
                "condition": static_conditions.describe(gate),
                "active": static_conditions.condition_holds(gate, state, src, controller_id),
            }
        )
    return summary


def _describe_ability(ability: StaticAbility) -> str:
    p = ability.params
    if ability.layer == "pt_mod":
        return f"{_signed(p.get('power', 0))}/{_signed(p.get('toughness', 0))} to {ability.affects}"
    if ability.layer == "pt_set":
        return f"sets {ability.affects} to {p.get('power', 0)}/{p.get('toughness', 0)}"
    if ability.layer == "pt_switch":
        return f"switches P/T of {ability.affects}"
    if ability.layer == "pt_cda":
        return f"defines P/T of {ability.affects}"
    if ability.layer == "ability":
        if p.get("keywords"):
            return "grants " + ", ".join(p.get("keywords", []))
        if p.get("mana"):
            return "grants a mana ability"
        if p.get("trigger_event"):
            return "grants a triggered ability"
        return "grants an ability"
    if ability.layer == "type":
        if p.get("set_subtypes"):
            return "becomes " + "/".join(p["set_subtypes"])
        if p.get("add_subtypes_from_source"):
            return "is also the chosen type"
        if p.get("add_subtypes"):
            return "is also " + "/".join(p["add_subtypes"])
        return "makes " + ", ".join(p.get("add_types", []))
    if ability.layer == "color":
        return "colours " + ", ".join(p.get("colors", []))
    if ability.layer == "control":
        return f"controls {ability.affects}"
    if ability.layer == "copy":
        return "is a copy of another target creature while untapped" if p.get("requires_untapped") else "is a copy of a target"
    if ability.layer == "text":
        return "rewrites text: " + ", ".join(f"{k}→{v}" for k, v in (p.get("replace") or {}).items())
    if ability.layer == "cost":
        prefix = f"{p['spell_type']} spells" if p.get("spell_type") else "spells"
        return f"{prefix} cost {{{p.get('generic', 0)}}} {'more' if p.get('increase') else 'less'}"
    if ability.layer == "activation_prohibition":
        scope = f"{p['card_type']}s'" if p.get("card_type") else ""
        tail = " unless they're mana abilities" if p.get("except_mana_abilities") else ""
        return f"{scope} activated abilities can't be activated{tail}".strip()
    if ability.layer == "combat_restriction":
        return _describe_combat_restriction(p)
    if ability.layer == "cast_limit":
        return f"each player can't cast more than {p.get('max_per_turn', 1)} spell(s) each turn"
    if ability.layer == "draw_limit":
        return f"each player can't draw more than {p.get('max_per_turn', 1)} card(s) each turn"
    if ability.layer == "no_untap":
        return "doesn't untap during its controller's untap step"
    if ability.layer == "activate_as_though_haste":
        return "its controller may activate abilities of their creatures as though they had haste"
    if ability.layer == "untap_each_untap_step":
        return "untaps during each other player's untap step"
    if ability.layer == "no_untap_optional":
        return "controller may choose not to untap it during their untap step"
    if ability.layer == "extra_land_drop":
        who = "each player" if ability.affects == "each_player" else "its controller"
        return f"{who} may play {p.get('count', 1)} additional land(s) each turn"
    if ability.layer == "no_max_hand_size":
        who = "each player" if ability.affects == "each_player" else "its controller"
        return f"{who} has no maximum hand size"
    if ability.layer == "hand_size_modifier":
        who = {"each_player": "each player's", "opponents": "each opponent's"}.get(
            ability.affects, "its controller's"
        )
        amount = int(p.get("amount", 0))
        verb = "increased" if p.get("increase") else "reduced"
        return f"{who} maximum hand size is {verb} by {amount}"
    if ability.layer == "ignore_legend_rule":
        clause = "each player controls" if ability.affects == "each_player" else "its controller controls"
        return f"the legend rule doesn't apply to permanents {clause}"
    if ability.layer == "radiation_life_gain":
        who = "each player" if ability.affects == "each_player" else "its controller"
        return f"{who} gains life rather than loses life from radiation"
    if ability.layer == "trigger_prohibition":
        subject = f"{p['subject_type']}s" if p.get("subject_type") else "objects"
        return f"{subject} entering don't cause abilities to trigger"
    if ability.layer == "enters_tapped":
        scope = f"nonbasic {p['card_type']}" if p.get("nonbasic") and p.get("card_type") else p.get("card_type", "permanents")
        who = "" if ability.affects == "all_permanents" else "your opponents control "
        return f"{scope}s {who}enter tapped"
    if ability.layer == "untap_cap":
        return f"players can't untap more than {p.get('count', 1)} land(s) during their untap steps"
    if ability.layer == "any_color_for_activation":
        scope = "creatures'" if p.get("creature_abilities_only", True) else "permanents'"
        return f"may spend mana as though it were mana of any color to activate {scope} abilities"
    if ability.layer == "borrowed_activated_ability":
        return "gains all activated abilities of creature cards exiled with it"
    return ability.affects


def _doubler_kind(obj: Any) -> str:
    """What a doubled trigger's source is: an ``"emblem"`` (RULE 114.4), a ``"spell"`` on the
    stack (its own cast triggers — cascade, storm), or an ordinary ``"permanent"``."""
    from ..models.game.emblem import Emblem  # local: continuous imports models lazily
    from ..models.game.game_object import Zone

    if isinstance(obj, Emblem):
        return "emblem"
    return "spell" if getattr(obj, "zone", None) == Zone.STACK else "permanent"


def _doubler_side_matches(
    state: "GameState", doubler: "GameObject", side: dict, obj: Any
) -> bool:
    """One alternative of a compound doubler subject (`trigger_doubler._alternative`)."""
    from .combat import matches_object_filter  # local: combat imports models lazily too

    kind = _doubler_kind(obj)
    if kind == "emblem":
        return bool(side.get("emblem")) and obj.owner_id == doubler.controller_id
    if side.get("emblem") or bool(side.get("spell")) != (kind == "spell"):
        return False
    if side.get("self"):
        return obj is doubler
    if side.get("other") and obj is doubler:
        return False
    if side.get("attached_to_doubler") and getattr(obj, "attached_to", None) != doubler.instance_id:
        return False
    filt = side.get("filter")
    return not filt or matches_object_filter(obj, filt, reference=doubler, state=state)


def _composed_doubler_applies(
    state: "GameState", doubler: "GameObject", effect: Any, obj: Any,
    event: Any, context: Any,
) -> bool:
    """PAR-122: whether a `TriggerDoublerEffect` built from a ``cause`` and/or
    ``subject`` doubles ``obj``'s trigger caused by ``event``.

    The subject half is the doubled permanent's own filter; the cause half is a
    trigger-shaped dict answered by the same predicate a triggered ability of that
    shape would use (`binding.core._trigger_condition`), so "a creature you control
    attacking" means exactly what "whenever a creature you control attacks" means.
    ``obj`` is a permanent unless the subject names a spell/emblem side (`_doubler_kind`).
    """
    from .combat import matches_object_filter  # local: combat imports models lazily too

    subject = effect.subject or {}
    if subject.get("any_of"):
        # A compound "<A> or <B>" subject: the trigger doubles if either side names ``obj``.
        if not any(_doubler_side_matches(state, doubler, side, obj) for side in subject["any_of"]):
            return False
        subject = {}
    elif _doubler_kind(obj) != "permanent":
        return False  # "a permanent you control" never names a spell or an emblem
    if subject.get("other") and doubler is obj:
        return False
    if subject.get("attached") and getattr(doubler, "attached_to", None) != obj.instance_id:
        return False
    subject_filter = subject.get("filter")
    if subject_filter and not matches_object_filter(
        obj, subject_filter, reference=doubler, state=state
    ):
        return False
    cause = effect.cause
    if cause is None:
        return True
    if event is None:
        return False
    events = cause["event"] if isinstance(cause["event"], (list, tuple)) else [cause["event"]]
    firing = getattr(event.type, "name", str(event.type))
    if firing not in events:
        return False
    from .binding.core import _trigger_condition  # local: binding imports this module

    if context is None:
        # A caller outside the engine (a unit test, a bot's look-ahead): every
        # trigger predicate reads the game only through ``context.state``.
        from types import SimpleNamespace

        context = SimpleNamespace(state=state)
    predicate = _trigger_condition({**cause, "event": firing}, doubler)
    return predicate is None or bool(predicate(event, context))


def _active_doublers(
    state: "GameState", obj: Any, event: Any, context: Any
) -> list[tuple["GameObject", Any]]:
    """Every ``(holder, TriggerDoublerEffect)`` that doubles ``obj``'s trigger caused by
    ``event`` — the holder being the permanent that has the doubler (an Equipment's granted
    doubler is held by its host, `TriggerDoublerEffect.attached`)."""
    from .effects.core import TriggerDoublerEffect  # local: effects imports this module

    if obj.controller_id is None:
        return []
    found: list[tuple["GameObject", Any]] = []
    for doubler in state.battlefield:
        for effect in getattr(doubler, "static_effects", None) or []:
            if not isinstance(effect, TriggerDoublerEffect):
                continue
            holder = doubler
            if effect.attached:
                holder = next(
                    (o for o in state.battlefield if o.instance_id == getattr(doubler, "attached_to", None)),
                    None,
                )
                if holder is None:
                    continue
            if holder.controller_id != obj.controller_id:
                continue
            if effect.active_if and not static_conditions.condition_holds(
                effect.active_if, state, doubler, doubler.controller_id
            ):
                continue
            if _composed_doubler_applies(state, holder, effect, obj, event, context):
                found.append((holder, effect))
    return found


def trigger_doubler_tap_offers(
    state: "GameState", obj: Any, event: Any = None, context: Any = None
) -> list[tuple["GameObject", Any]]:
    """The paid doublers ("tap any number of Fish you control … an additional time for each",
    The Fish Brewer) that apply to ``obj``'s trigger: ``(holder, effect)`` pairs whose extra
    copies the controller buys when the trigger is put on the stack, not free ones."""
    return [(h, e) for h, e in _active_doublers(state, obj, event, context) if e.tap_cost]


def doubler_tap_candidates(state: "GameState", holder: "GameObject", effect: Any) -> list["GameObject"]:
    """The untapped permanents ``holder``'s controller may tap to pay ``effect.tap_cost``."""
    from .combat import matches_object_filter  # local: combat imports models lazily too

    filt = (effect.tap_cost or {}).get("filter")
    return [
        o for o in state.battlefield
        if o.controller_id == holder.controller_id and not o.tapped
        and (not filt or matches_object_filter(o, filt, reference=holder, state=state))
    ]


def trigger_doubler_bonus(
    state: "GameState", obj: "GameObject", event: Any = None, context: Any = None
) -> int:
    """RULE 603.3d: how many *additional* times a triggered ability of
    ``obj`` should be placed on the stack (0 in the overwhelming common
    case), from every active `effects.TriggerDoublerEffect` a
    same-controller permanent carries (Roaming Throne's "if a triggered
    ability of another creature you control of the chosen type triggers,
    it triggers an additional time").

    Multiple simultaneous doublers stack additively (RULE 603.3d/611.2b
    "additional time" instances are independent) — two Roaming Thrones of
    the same chosen type make a matching trigger fire three times total,
    not four, matching how the rule itself composes rather than
    multiplying.

    ``event`` is the `GameEvent` that fired ``obj``'s own trigger and ``context``
    the `GameContext` its predicate reads — consulted only by a doubler whose
    `TriggerDoublerEffect.cause` is set (see `_composed_doubler_applies`).
    """
    return sum(1 for _, effect in _active_doublers(state, obj, event, context) if not effect.tap_cost)


def granted_help_pay_keyword(state: "GameState", obj: Any) -> Optional[str]:
    """"Nonartifact spells you cast have improvise." (Inspiring Statuary) — the Convoke/Delve/Improvise keyword a ``spell_help_pay_grant`` static gives the spell
    ``obj`` its controller is casting (``exclude_card_type`` leaves out the named type), or ``None``."""
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "spell_help_pay_grant":
            continue
        if getattr(ability.source, "controller_id", None) != getattr(obj, "controller_id", None):
            continue
        excluded = ability.params.get("exclude_card_type")
        if excluded and _has_card_type(obj, str(excluded)):
            continue
        return str(ability.params.get("keyword") or "")
    return None


def granted_cast_keyword_instances(state, obj, event, keyword):
    """Spell keyword grants are evaluated once the cast's mana is paid."""
    from . import static_conditions
    from ..models.game.events import EventType

    instances = 0
    for ability in _battlefield_static_abilities(state):
        src = ability.source
        if (ability.layer != "ability"
                or ability.affects not in ("spells_you_cast", "instant_sorcery_spells_you_cast")
                or keyword not in ability.params.get("keywords", [])
                or getattr(src, "controller_id", None) != obj.controller_id
                or getattr(src, "loses_all_abilities", False)):
            continue
        def matches(cast):
            if cast.type != EventType.SPELL_CAST or cast.get("player_id") != obj.controller_id:
                return False
            if (ability.affects == "instant_sorcery_spells_you_cast"
                    and not {"instant", "sorcery"}.intersection(cast.get("object_types", []))):
                return False
            # "Enchantment spells you cast from your hand have cascade." (Wildsear, Scouring Maw)
            card_types = ability.params.get("card_types")
            if card_types and not {str(t).lower() for t in card_types}.intersection(cast.get("object_types", [])):
                return False
            if ability.params.get("from_hand") and not cast.get("from_hand"):
                return False
            kind = ability.params.get("mana_source_kind")
            return kind is None or cast.get("mana_spent_by_source", {}).get(kind, 0) > 0
        if not matches(event):
            continue
        if (ability.params.get("first_matching_each_turn")
                and any(e is not event and matches(e) for e in state.events_this_turn())):
            continue
        if not static_conditions.condition_holds(
                ability.params.get("active_if"), state, src, obj.controller_id):
            continue
        instances += 1
    return instances
