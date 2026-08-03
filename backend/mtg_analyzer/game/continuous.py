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

import re
from typing import TYPE_CHECKING, Any, Optional

from . import durations, static_conditions, variants
from .costs import parse_activation_cost
from .effects import ActivatedAbility, EffectRegistry, StaticAbility, TriggeredAbility

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models.game_object import GameObject
    from ..models.game_state import GameState
    from ..models.player import Player


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
    type, so it matches any subtype.

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
        return subtype.lower() in {s.lower() for s in override}
    added = getattr(obj, "_added_subtypes", None)
    if added and subtype.lower() in {s.lower() for s in added}:
        # RULE 613.4a: a layer-4 "~ is the chosen type in addition to its
        # other types" grant (`add_subtypes`/`add_subtypes_from_source`,
        # Adaptive Automaton/A-Thran Portal-shaped) — additive, unlike
        # `_derived_subtypes`'s full RULE 613.5 overwrite above.
        return True
    type_line = obj.card.type_line.lower()
    if "changeling" in type_line or "changeling" in obj.intrinsic_keywords:
        return True
    _, _, sub = type_line.partition("—")  # subtypes follow the em dash
    return subtype.lower() in sub


def has_subtype(obj: "GameObject", subtype: str) -> bool:
    """Public wrapper over `_has_subtype` for callers outside this module
    (e.g. `game_engine`'s "tap N untapped Elves you control" cost, RULE
    602.1 — `game/costs.py`'s ``tap_others``)."""
    return _has_subtype(obj, subtype)


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
    affects: str,
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
    """
    params = params or {}
    # RULE 702.26c: a phased-out permanent is treated as though it doesn't
    # exist — invisible to every static-ability selector below.
    battlefield = state.permanents()

    if affects == "objects":
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
    elif affects == "all_permanents":
        result = list(battlefield)
    elif affects == "attached_permanent":
        host_id = getattr(src, "attached_to", None)
        result = [o for o in battlefield if host_id is not None and o.instance_id == host_id]
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
    elif affects == "creatures_you_control":
        result = [o for o in battlefield if o.is_creature and o.controller_id == controller_id]
    elif affects == "other_creatures_you_control":
        result = [
            o for o in battlefield
            if o.is_creature and o.controller_id == controller_id and o is not src
        ]
    elif affects == "permanents_you_control":
        result = [o for o in battlefield if o.controller_id == controller_id]
    elif affects == "nonland_permanents_you_control":
        # "Untap all nonland permanents you control." (Dramatic Reversal)
        result = [
            o for o in battlefield
            if not o.is_land and o.controller_id == controller_id
        ]
    elif affects == "lands_you_control":
        result = [o for o in battlefield if o.is_land and o.controller_id == controller_id]
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
    # `chosen_color` (stamped by `RulesEngine.resolve_enter_choice`) fresh
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
    if params.get("tokens"):  # "creature tokens you control …" (RULE 111)
        result = [o for o in result if getattr(o, "is_token", False)]
    if params.get("exclude_self"):  # a global "Other creatures …" anthem
        result = [o for o in result if o is not src]
    card_type = params.get("card_type")
    if card_type:  # "Artifacts your opponents control…", "Nonbasic lands are…"
        result = [o for o in result if _has_card_type(o, str(card_type))]
    if params.get("nonbasic"):  # "Nonbasic lands …" (RULE 205.4a)
        result = [o for o in result if _is_nonbasic(o)]

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
    """Abilities in one (sub)layer, ordered by source timestamp (RULE 613.7b).

    Within a layer, effects apply in timestamp order (newest last); an
    unsourced fixture ability sorts first (timestamp 0). A true dependency
    pass (RULE 613.8) is still a simplification — timestamps cover the
    overwhelmingly common non-dependent case.
    """
    picked = [a for a in abilities if a.layer == layer]
    return sorted(picked, key=lambda a: getattr(a.source, "timestamp", 0))


#: Colour word → WUBRG letter, for the ``devotion_to_<colour>`` selectors
#: (RULE 202.2f). Colourless has no devotion (a {C} pip is not a colour).
_DEVOTION_COLOURS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}


def count_selector(
    state: "GameState",
    controller_id: Optional[str],
    selector: str,
    source: Optional["GameObject"] = None,
) -> int:
    """Evaluate a "number of X" count selector, scoped to ``controller_id``.

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
    bf = state.battlefield
    _source_card_name = getattr(source, "name", None)
    if selector == "creatures_you_control":
        return sum(1 for o in bf if o.is_creature and o.controller_id == controller_id)
    if selector == "attacking_creatures_you_control":
        # "for each attacking creature you control" (Embercleave's own
        # self-cost-reduction, MEC-6) — read live off `GameObject.attacking`
        # (RULE 508.1), so casting after declare attackers sees the real
        # count; before that step it's simply 0, same as any other
        # `self_cost_reduction_for` count read at cast time.
        return sum(1 for o in bf if o.is_creature and o.attacking and o.controller_id == controller_id)
    if selector == "attacking_creatures":
        # The unscoped sibling — "for each attacking creature" with no "you
        # control" (Ancient Stone Idol/Static Snare/Stone Idol Trap) — every
        # attacker regardless of whose.
        return sum(1 for o in bf if o.is_creature and o.attacking)
    if selector == "lands_you_control":
        return sum(1 for o in bf if o.is_land and o.controller_id == controller_id)
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
    if selector == "artifacts_you_control":
        return sum(1 for o in bf if o.card.is_artifact and o.controller_id == controller_id)
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
    if selector == "cards_in_your_graveyard":
        try:
            player = state.player_by_id(controller_id) if controller_id else None
        except KeyError:
            player = None
        return len(player.graveyard) if player is not None else 0
    if selector.startswith("devotion_to_"):
        # RULE 202.2f/700.5: "your devotion to <colour>" is the number of
        # mana symbols of that colour in the mana costs of permanents you
        # control (Thassa's Oracle) — with a hybrid pip counting toward
        # *both* of its colours, which `ManaSymbol.colors` already models as
        # a set (Kitchen Finks' {G/W}{G/W} is 2 green *and* 2 white
        # devotion). Read off the printed cost string rather than
        # `Card.mana_cost`'s per-colour dict, which is only populated for
        # cards that came from Scryfall.
        from ..models.mana_cost import ManaCost  # function-scoped: see module header

        colour = _DEVOTION_COLOURS.get(selector[len("devotion_to_"):])
        if colour is None:
            return 0
        return sum(
            sum(
                1
                for symbol in ManaCost.parse(o.card.mana_cost_string).symbols
                if colour in symbol.colors
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
    return 0


def _count_selector(state: "GameState", ability: StaticAbility, selector: str) -> int:
    """`count_selector`, scoped to a `StaticAbility`'s own source's
    controller (RULE 613.7c/604.3) — see `count_selector` for the
    vocabulary."""
    return count_selector(
        state, getattr(ability.source, "controller_id", None), selector, source=ability.source
    )


def _equipment_attached_count(state: "GameState", obj: "GameObject") -> int:
    """How many Equipment are currently attached to ``obj`` itself — a
    *per-object* count (Bruenor Battlehammer's "for each Equipment attached
    to it"), unlike every `count_selector` entry above (one number shared by
    every object a static ability affects)."""
    return sum(
        1 for o in state.battlefield
        if o.attached_to == obj.instance_id and "equipment" in o.card.type_line.lower()
    )


def _pt_mod_count(state: "GameState", ability: StaticAbility, obj: "GameObject", selector: str) -> int:
    """A layer-7d anthem's per-unit multiplier — either a per-object count
    (``"equipment_attached_to_self"``), the ability's own source's counters
    (``"plus_one_counters_on_self"`` — Lion Sash's "for each +1/+1 counter
    on this Equipment"), or the ordinary controller-scoped `count_selector`
    vocabulary (Blackblade Reforged's "for each land you control",
    Nettlecyst's "for each artifact and/or enchantment you control")."""
    if selector == "equipment_attached_to_self":
        return _equipment_attached_count(state, obj)
    if selector == "plus_one_counters_on_self":
        return getattr(ability.source, "plus_one_counters", 0)
    return _count_selector(state, ability, selector)


def _protection_qualities(ability: StaticAbility) -> set[str]:
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
    """
    from . import combat  # function-scoped: combat imports this module

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
    return quals


#: Mirrors `effect_binder._SUBJECT_EVENT_KEYS` — which event-data key
#: identifies *which object* a grantable event is about. Kept as a local
#: copy rather than imported (`continuous.py` stays free of `effect_binder`
#: imports; it's one entry, not worth a shared-module indirection).
_GRANTED_EVENT_KEYS: dict[str, str] = {"DAMAGE": "source_id"}


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
    against a future hand-authored `ability_catalogue.py` entry naming an
    unregistered event, not a path any card exercises today.
    """
    key = _GRANTED_EVENT_KEYS.get(trigger_event or "", "instance_id")
    filt = dict(event_filter) if event_filter else None
    no_object_subject = phase_relation in ("you", "not_you")

    def condition(event: Any, context: Any) -> bool:
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
        set_subtypes = ability.params.get("set_subtypes")
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
        for obj in affected_objects(state, ability):
            for type_name in added:
                obj._added_types.add(type_name)
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
            if power is not None and toughness is not None:
                animation_pt[obj.instance_id] = (power, toughness)
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


def _apply_layer_6_ability(state: "GameState", abilities: list) -> None:
    # -- Layer 6: ability-adding effects (keyword / mana / triggered-ability
    # grants — RULE 613.7f). A grant is re-derived every pass exactly like
    # every other layer effect here, so it disappears on its own the moment
    # its source stops applying — no separate removal code (RULE 613.6).
    live_grant_keys: set[tuple[int, int]] = set()
    for ability in _in_layer(abilities, "ability"):
        keywords = ability.params.get("keywords", [])
        remove_keywords = ability.params.get("remove_keywords", [])
        lose_all = bool(ability.params.get("lose_all_abilities", False))
        mana = ability.params.get("mana", [])
        trigger_event = ability.params.get("trigger_event")
        activated_cost = ability.params.get("activated_cost")
        # RULE 702.16 standing protection grant ("Cats you control have
        # protection from Rats" — Hungry Lynx; "Enchanted creature has
        # protection from the chosen color" — Flickering Ward). The parser
        # front-end can't normalize the quality itself (it must stay free of
        # `game/` imports), so the raw printed words are folded through
        # `combat.protections_of_text`'s own vocabulary here, once per
        # ability rather than once per affected object.
        protections = _protection_qualities(ability)
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
            if remove_keywords:
                obj._removed_keywords.update(remove_keywords)
                _trace(obj, 6, _source_name(ability), "loses " + ", ".join(remove_keywords))
            if protections:
                obj._granted_protections.update(protections)
                _trace(obj, 6, _source_name(ability),
                       "gains protection from " + ", ".join(sorted(protections)))
            if mana:
                obj._granted_mana.extend(mana)
                _trace(obj, 6, _source_name(ability), "gains a mana ability")
            if trigger_event:
                key = (id(ability), obj.instance_id)
                live_grant_keys.add(key)
                granted = state._granted_ability_cache.get(key)
                if granted is None:
                    granted = TriggeredAbility(
                        trigger_event=trigger_event,
                        effects=[
                            EffectRegistry.create(spec["type"], dict(spec.get("params", {})))
                            for spec in ability.params.get("grant_effects", [])
                        ],
                        condition=_granted_trigger_condition(
                            obj, bool(ability.params.get("controllers_turn_only", False)),
                            trigger_event, ability.params.get("filter"),
                            ability.params.get("phase_relation"),
                        ),
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
                    cost = parse_activation_cost(dict(activated_cost))
                    cost.sorcery_speed_only = bool(ability.params.get("sorcery_speed_only", False))
                    granted_activated = ActivatedAbility(
                        effects=[
                            EffectRegistry.create(spec["type"], dict(spec.get("params", {})))
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
                base[obj.instance_id][0] = _count_selector(state, ability, str(p_sel))
            if t_sel:
                base[obj.instance_id][1] = _count_selector(state, ability, str(t_sel))
            p, t = base[obj.instance_id]
            _trace(obj, 7, _source_name(ability), f"defined as {p}/{t}", p, t)

    # 7b: set power/toughness to a specific value.
    for ability in _in_layer(abilities, "pt_set"):
        power = ability.params.get("power", 0)
        toughness = ability.params.get("toughness", 0)
        for obj in affected_objects(state, ability):
            if obj.instance_id in base:
                base[obj.instance_id] = [power, toughness]
                _trace(obj, 7, _source_name(ability), f"set to {power}/{toughness}", power, toughness)

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
                power = d_power * _pt_mod_count(state, ability, obj, str(p_sel)) if p_sel else d_power
                toughness = (
                    d_toughness * _pt_mod_count(state, ability, obj, str(t_sel)) if t_sel else d_toughness
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

    # 7e: switch power and toughness (RULE 613.7e / 701.28). Applied last, so it
    # swaps the fully-computed values.
    for ability in _in_layer(abilities, "pt_switch"):
        for obj in affected_objects(state, ability):
            if obj.instance_id in base:
                base[obj.instance_id].reverse()
                p, t = base[obj.instance_id]
                _trace(obj, 7, _source_name(ability), f"switched to {p}/{t}", p, t)

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
            for k in ("kind", "filter", "count", "condition")
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
    _apply_layer_7_pt(state, abilities, animation_pt)
    _apply_post_layer_combat_restrictions_and_goad(state, abilities)


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
        amount *= count_selector(state, controller_id, per)
    return -amount if ability.params.get("increase") else amount


def _spell_type_matches(obj: "GameObject", spell_type: str) -> bool:
    """Whether the spell ``obj`` matches a `cost_reduction` static's
    ``spell_type`` filter ("noncreature spells cost {1} more…", Thalia,
    Guardian of Thraben/Thorn of Amethyst/Vryn Wingmare) — ``"noncreature"``
    is its own case (no ``Card.is_noncreature`` flag to read), everything
    else is a plain `_has_card_type` lookup on the object being cast."""
    if spell_type == "noncreature":
        return not obj.card.is_creature
    return _has_card_type(obj, spell_type)


def cost_reduction_for(
    state: "GameState", player: "Player", obj: Optional["GameObject"] = None
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
        spell_type = ability.params.get("spell_type")
        if spell_type and (obj is None or not _spell_type_matches(obj, spell_type)):
            continue
        signed = _cost_static_amount(ability, state, player.id)
        net += signed
        contributors.append(
            {
                "source": _source_name(ability),
                "amount": signed,
                "description": f"Spells cost {{{abs(signed)}}} {'more' if signed < 0 else 'less'}",
            }
        )
    return net, contributors


def self_cost_reduction_for(obj: "GameObject", state: "GameState") -> tuple[int, list[dict[str, Any]]]:
    """Net generic-mana reduction from a "cost" static printed on ``obj``
    itself (Delve/Affinity-shaped: "This spell costs {1} less to cast for
    each ...") while ``obj`` is still in hand/graveyard/etc.

    `_battlefield_static_abilities` only scans `state.battlefield`, so a
    card that hasn't been cast yet needs its own static read straight off
    ``obj.static_effects`` — the binder attaches a spell's own statics there
    regardless of zone, same as any other static.
    """
    net = 0
    contributors: list[dict[str, Any]] = []
    controller_id = getattr(obj, "controller_id", None)
    for ability in getattr(obj, "static_effects", []):
        if not isinstance(ability, StaticAbility) or ability.layer != "cost" or ability.affects != "self":
            continue
        signed = _cost_static_amount(ability, state, controller_id)
        net += signed
        contributors.append(
            {
                "source": _source_name(ability),
                "amount": signed,
                "description": f"Costs {{{abs(signed)}}} {'more' if signed < 0 else 'less'} to cast",
            }
        )
    return net, contributors


def activation_cost_reduction_for(state: "GameState", source: "GameObject") -> tuple[int, int]:
    """Net generic-mana reduction for *activating* ``source``'s own
    activated ability (Power Artifact-shaped "Enchanted artifact's
    activated abilities cost {2} less to activate.") — the activation-cost
    analogue of `cost_reduction_for` (a *spell's* cast cost); consulted by
    `GameEngine._reduced_activation_mana`.

    Only a ``"cost"``-layer static with ``params["scope"] == "activation"``
    counts (`cost_reduction_for` explicitly skips these, so a static never
    double-applies to both a spell's cast cost and an ability's activation
    cost). Only the ``affects="attached_permanent"`` scope is implemented
    today — the one shape the pool needs; an unscoped "activated abilities
    you control cost less" variant would need its own `affects` branch here,
    not yet built since nothing needs it.

    Returns ``(net_reduction, floor)`` where ``floor`` is the highest
    "can't reduce the mana in that cost to less than N mana" clause among
    the contributing statics (0 — no floor — if none set one).
    """
    net = 0
    floor = 0
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cost" or ability.params.get("scope") != "activation":
            continue
        if ability.affects == "attached_permanent":
            if getattr(ability.source, "attached_to", None) != source.instance_id:
                continue
        else:
            continue
        net += int(ability.params.get("generic", 0))
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
        if source in affected_objects(state, ability):
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
    ]
    return min(limits) if limits else None


def cast_prohibited(state: "GameState", player: "Player", card: Any) -> bool:
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

    Kept out of the RULE 613 layer engine for the same reason
    ``cast_limit``/``draw_limit`` are — it changes what a player *may do*,
    not any object's characteristics — and consulted directly by
    `GameEngine.can_cast`.
    """
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "cast_prohibition":
            continue
        controller_id = getattr(ability.source, "controller_id", None)
        scope = ability.params.get("scope", "opponents")
        if scope == "opponents" and player.id in (None, controller_id):
            continue
        if ability.params.get("noncreature") and getattr(card, "is_creature", False):
            continue
        selector = ability.params.get("max_mana_value_selector")
        if selector is not None:
            allowed = count_selector(state, player.id, str(selector), source=ability.source)
            if getattr(card, "converted_mana_cost", 0) <= allowed:
                continue
        return True
    return False


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
        return dict(ability.params)
    return None


def max_draws_per_turn(state: "GameState") -> Optional[int]:
    """The most restrictive "Each player can't draw more than N cards each
    turn." cap in play (RULE 121.5-adjacent — Spirit of the Labyrinth), or
    ``None`` if no such static applies. The draw-side mirror of
    `max_spells_per_turn`; `RulesEngine._single_draw` compares it against
    `GameState.cards_drawn_this_turn`.
    """
    limits = [
        ab.params.get("max_per_turn")
        for ab in _battlefield_static_abilities(state)
        if ab.layer == "draw_limit" and ab.params.get("max_per_turn") is not None
    ]
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
    for ability in _battlefield_static_abilities(state):
        if ability.layer != "no_max_hand_size":
            continue
        if ability.affects == "each_player" or getattr(ability.source, "controller_id", None) == player.id:
            return True
    return False


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


def untap_cap_for_lands(state: "GameState") -> Optional[int]:
    """The global cap on how many lands *any* player may untap during their
    untap step this turn (RULE 502.3-adjacent, Winter Orb-shaped: "As long
    as this artifact is untapped, players can't untap more than one land
    during their untap steps.") — ``None`` when no such static is currently
    active.

    Unlike `has_no_untap_static` (a single permanent's own restriction) or
    `enters_tapped_from_static` (a board-wide but ownership-scoped effect),
    this is a flat, unscoped cap that applies to *every* player's untap
    step identically, gated on the static's own source currently being
    untapped ("as long as ~ is untapped" — checked live, not the source's
    controller/affected-set machinery every other static family here
    uses). Two+ simultaneous instances don't stack (RULE 613's "the most
    restrictive" isn't quite right either — real Magic just has each
    Orb apply its own 1-land cap independently, so the effective cap is
    whichever is *smallest*), hence ``min()`` rather than summing.
    """
    caps = [
        ability.params.get("count", 1)
        for ability in _battlefield_static_abilities(state)
        if ability.layer == "untap_cap" and ability.source is not None and not ability.source.tapped
    ]
    return min(caps) if caps else None


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
        if ability.params.get("event") != event.type:
            continue
        subject_type = ability.params.get("subject_type")
        if subject_type and subject_type not in (event.get("object_types") or []):
            continue
        return True
    return False


def enters_tapped_from_static(state: "GameState", obj: "GameObject") -> bool:
    """Whether a board-wide static ("Artifacts your opponents control enter
    tapped." — RULE 614.1, Manglehorn/Dauntless Dismantler/Archon of
    Emeria-shaped; or an unscoped "Artifacts and lands enter tapped." — Root
    Maze-shaped, ``affects="all_permanents"``, no ownership restriction at
    all) forces ``obj`` to enter tapped right now.

    Distinct from `ability_catalogue.enters_tapped` (a card's own printed
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
    {"cost", "no_untap", "no_untap_optional", "enters_tapped", "activation_prohibition",
     "cast_limit", "cast_prohibition", "draw_limit", "trigger_prohibition", "untap_cap",
     "extra_land_drop", "no_max_hand_size", "radiation_life_gain", "grant_escape",
     "combat_restriction", "goaded"}
)


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
    if ability.layer == "no_untap_optional":
        return "controller may choose not to untap it during their untap step"
    if ability.layer == "extra_land_drop":
        who = "each player" if ability.affects == "each_player" else "its controller"
        return f"{who} may play {p.get('count', 1)} additional land(s) each turn"
    if ability.layer == "no_max_hand_size":
        who = "each player" if ability.affects == "each_player" else "its controller"
        return f"{who} has no maximum hand size"
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
    return ability.affects
