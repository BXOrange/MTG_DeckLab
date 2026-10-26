"""Clause primitives shared by the segmenter, the effect handlers and the static handlers (PAR-172).

A **leaf** module: it imports none of `segmenter`, `handlers` or `static_handlers`
(guarded by `tests/test_parser_import_graph.py`). Before PAR-172 these helpers lived inside
those three modules, which therefore imported each other through ~45 function-scoped
imports and 22 cross-module private names. Anything two of them both need belongs here.

Groups:
* the activation / trigger *marker* effect types a handler emits and the binder strips
  (`*_MARKER`);
* splitting a "<kw>, <kw> and firebending N" grant list (`split_keywords_with_parametric`);
* "does this parsed clause announce a target" and the counters-on-the-referent stamp
  (`announces_creature_target`, `stamp_counters_on_referent`).

Pure regex + data — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..spec import EffectSpec
from .keywords import KEYWORDS, UNGRANTABLE_FLAG_KEYWORDS, KeywordShape, keyword_slug, resolve_keyword
from .subgrammars import target_kind_allowed

# ---- Activation / trigger limit markers ----


#: RULE 602.1-adjacent per-instance activation cap: "Activate only once each
#: turn." (Quirion Ranger/Scryb Ranger-shaped) — a plain trailing sentence in
#: an activated ability's own body (after the cost's colon), sitting
#: alongside its real effect ("Untap target creature. Activate only once
#: each turn." — two sentences `parse_effect_body`'s connector-splitting
#: already tries independently). Not a real one-shot effect: this handler
#: claims the clause but emits a *marker* `EffectSpec` `effect_binder.
#: bind_ability`'s "activated" branch recognizes and strips before binding,
#: turning it into `ActivatedAbility.once_per_turn` instead of a `GameEffect`
#: (mirroring `TriggeredAbility.once_per_turn`'s own RULE 603.2 stamp).
ONCE_PER_TURN_MARKER = "once_per_turn_marker"


#: RULE 603.2's own once-per-turn limiter, PAR-14 — "This ability triggers
#: only once each turn." (Chance-Met Elves/Prudent Fateseer-shaped) — a
#: trailing sentence in a *triggered* ability's own body, the exact same
#: "claim the clause, emit a marker, let the binder fold it into a flag"
#: shape `ONCE_PER_TURN_MARKER` above uses for an *activated* ability, but
#: textually distinct ("this ability triggers", not "activate"), so its own
#: row rather than widening that one. `segmenter.segment_line`'s "triggered"
#: dispatch strips this marker from the parsed body and folds it into
#: `AbilitySpec.trigger["limit"]`, consumed by `effect_binder.bind_ability`
#: as `TriggeredAbility.once_per_turn` — a primitive that already existed
#: (built for Dionus, Elvish Archdruid's *granted* ability) but no
#: oracle-text recognizer had ever reached from an ordinary printed card.
TRIGGER_ONCE_PER_TURN_MARKER = "trigger_once_per_turn_marker"


#: PAR-135: "…, you may draw a card. **Do this only once each turn.**" — the once-per-turn limit on the
#: *action* a trigger offers, not on the trigger: it still triggers every time, the controller just can't
#: perform the optional action a second time this turn, and declining the first doesn't use it up. So it is
#: not `TRIGGER_ONCE_PER_TURN_MARKER` (Ondu Spiritdancer, Irreverent Gremlin). The binder strips the marker
#: into `TriggeredAbility.action_once_per_turn`; `gate._action_limit_ok` refuses it anywhere else.
ACTION_ONCE_PER_TURN_MARKER = "action_once_per_turn_marker"


#: RULE 602.5d timing restriction: "Activate only as a sorcery." (older
#: template) / "Activate this ability only any time you could cast a sorcery."
#: (current) — like `ONCE_PER_TURN_MARKER`, a trailing sentence in the
#: activated ability's own body, not a real one-shot effect. Claimed as a
#: marker `EffectSpec` that `effect_binder.bind_ability`'s "activated" branch
#: strips and folds into `ActivationCost.sorcery_speed_only` (already enforced
#: by `game_engine.can_activate` via `_sorcery_speed_ok`), the same lever the
#: engine already uses for level-up / Class-level sorcery-speed abilities.
#: Only the two canonical *sorcery-speed* phrasings (RULE 605.3b / "any time
#: you could cast a sorcery"). Deliberately not "only during your turn"
#: (its own, wider `ONLY_DURING_YOUR_TURN_MARKER` below — folding it in
#: here would be *wrong*, since a non-empty stack is still legal for that
#: one) or "before attackers are declared" (still unclaimed, fail-closed,
#: until modeled precisely).
SORCERY_SPEED_MARKER = "sorcery_speed_marker"


#: PAR-109, RULE 605.3a: "Spend only black mana on X." (Crypt Rats, Crimson Hellkite) — a trailing sentence of an
#: activated ability's body, folded by `effect_binder.bind_ability` into `ActivationCost.x_spend_color` (the
#: `SORCERY_SPEED_MARKER` shape).
X_SPEND_COLOR_MARKER = "x_spend_color_marker"

#: MEC-131: "X can't be greater than the number of snow lands you control." — a spell line bounding the announced X by
#: a count selector (`GameObject.x_cap_selector`, read by `GameEngine.can_cast`).
X_CAP_MARKER = "x_cap_marker"


#: RULE 602.5d's *other* timing restriction: "Activate only during your
#: turn." (Wishclaw Talisman-shaped) — deliberately left unclaimed above
#: (see `SORCERY_SPEED_MARKER`'s own docstring) since it's a genuinely
#: different, wider window than sorcery-speed (still legal at instant
#: speed with a non-empty stack — just not outside the controller's own
#: turn). Same marker-then-strip shape, folded by `effect_binder.
#: bind_ability` into `ActivationCost.only_during_your_turn`
#: (`GameEngine._only_during_your_turn_ok`) instead of `sorcery_speed_only`.
ONLY_DURING_YOUR_TURN_MARKER = "only_during_your_turn_marker"


#: PAR-165: "Activate only during your turn, before attackers are declared." -- the own-turn marker plus a step cut-off
#: (`ActivationCost.only_before_attackers`, `GameEngine._before_attackers_declared_ok`).
ONLY_BEFORE_ATTACKERS_MARKER = "only_before_attackers_marker"


# PAR-28: marker `EffectSpec`s synthesized by `segmenter._segment_keyword_
# labeled_ability` for the "Keyword — [ability]" families (Boast/Exhaust/
# Power-up/Forecast — RULE 702.142/702.177/702.57). They carry no oracle
# text of their own (there is no regex row here — the keyword name *is* the
# recognition), and `effect_binder.bind_ability`'s "activated" branch strips
# and folds each into an `ActivatedAbility`/`ActivationCost` flag exactly
# like `ONCE_PER_TURN_MARKER` above.
#: RULE 702.177a / Power-up — "Activate only once." (per game, per ability).
ACTIVATE_ONLY_ONCE_MARKER = "activate_only_once_marker"


#: Power-up — "Reduce the cost by its mana cost if it entered this turn."
POWERUP_COST_REDUCTION_MARKER = "powerup_cost_reduction_marker"


#: RULE 702.57a — a forecast ability is activated from the card's hand.
FROM_HAND_MARKER = "from_hand_marker"


# PAR-10: "Activate only as a sorcery and only if `<condition>`." (Cabal
# Inquisitor/Dread Wanderer/Hall of Oracles/Jin-Gitaxias // The Great
# Synthesis) and its bare sibling "Activate only if `<condition>`."
# (Potioner's Trove) — RULE 602.5d timing stacked with (or standing in for)
# an activation-legality board condition, a second marker `effect_binder.
# bind_ability`'s "activated" branch folds into `ActivationCost.
# activation_condition`, checked by `GameEngine.can_activate` via
# `game/static_conditions.condition_holds` — the same RULE 613.6 whitelist a
# permanent's own "as long as `<condition>`" static already uses, so a
# condition recognized for one is recognized (and evaluated identically) for
# both.
#
# `game/static_conditions.py`'s full vocabulary lives behind
# `catalogue.static_handlers.static_condition` — which this module can't
# import (`static_handlers` already imports `SORCERY_SPEED_MARKER` from
# *here*, so the reverse import would cycle). This is deliberately a small,
# independent subset covering only the phrasings real cards actually pair
# with an activation condition today: hand/graveyard card counts and "cast
# an instant or sorcery spell this turn" (`cast_instant_or_sorcery_this_
# turn` is new — see `static_conditions.py` and `static_handlers.py`'s own
# `_STATIC_CONDITION_RES` row, which picks up the same phrase for free for
# the "created" ~250-clause "as long as" family: Haunting Figment/Leapfrog/
# Piston-Fist Cyclops). Every one of the ~150 *other* "Activate only if …"
# phrasings in the cache (`you control a Plains`, `this creature is
# attacking`, `a creature died this turn`, …) is real, standing PAR-12 tail
# work, not part of this ticket — fail-closed here, same as everywhere else.
ACTIVATION_CONDITION_MARKER = "activation_condition_marker"


# ---- Keyword-grant list splitting ----


def grantable_flag_slug(part: str) -> Optional[str]:
    """A single keyword token → its grantable slug, or ``None`` if it isn't a
    FLAG keyword, bare "hexproof", or a landwalk variant (PAR-74) — the three
    shapes `_token_keywords`/`split_keywords_with_parametric` can grant
    without a separate quality param. Shared so the two callers (a token's
    "with <keywords>" clause and a temporary "gains <keywords> until end of
    turn" pump) stay in lockstep."""
    slug = keyword_slug(part)
    kdef = KEYWORDS.get(slug)
    if kdef is not None and kdef.slug in UNGRANTABLE_FLAG_KEYWORDS:
        return None
    if kdef is not None and (kdef.shape is KeywordShape.FLAG or kdef.slug == "hexproof"):
        return kdef.slug
    resolved = resolve_keyword(slug)
    if resolved is not None and resolved.slug == "landwalk" and slug != "landwalk":
        return slug
    return None


#: ENG-31: the parametric keywords a *grant* ("gains firebending N until end
#: of turn", "has firebending N as long as …", a token "with firebending N")
#: can model — the ones whose RULE 702 text is a triggered ability
#: `effect_binder._KEYWORD_TRIGGERED_BUILDERS` re-synthesizes off the granted
#: N, plus toxic (PAR-102), which no builder needs: `combat.toxic_value` reads the granted N live at
#: damage time. Every other NUMBER-shape keyword (renown, …) stays fail-closed for a grant.
GRANTABLE_PARAMETRIC_KEYWORDS: frozenset[str] = frozenset(
    {"firebending", "annihilator", "afflict", "bushido", "toxic"}
)


def split_keywords_with_parametric(
    text: str,
) -> Optional[tuple[list[str], list[dict[str, object]]]]:
    """A "<kw>[, <kw> and firebending N …]" list → ``(flag_slugs,
    [{"name", "n"}, ...])``, or ``None`` if any entry is neither a FLAG
    keyword nor a grantable parametric one (fail-closed, like
    `_token_keywords`). ``"firebending 2"`` / ``"annihilator 1"`` entries go
    to the parametric list; everything else must be a plain flag."""
    flags: list[str] = []
    parametric: list[dict[str, object]] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        pm = re.fullmatch(r"([a-z]+)\s+(\d+)", part)
        if pm and pm.group(1) in GRANTABLE_PARAMETRIC_KEYWORDS:
            parametric.append({"name": pm.group(1), "n": int(pm.group(2))})
            continue
        slug = grantable_flag_slug(part)
        if slug is None:
            return None
        flags.append(slug)
    return flags, parametric


# ---- Target announcement + counters-on-referent stamping ----


#: The param keys an `EffectSpec` names a RULE 115 requirement under — the
#: same "differently-named keys" `CREATURE_TARGET_KINDS` documents, read here
#: to answer "does this clause announce a target at all".
TARGET_PARAM_KEYS: frozenset[str] = frozenset(
    {"target_kind", "fighter_kind", "other_kind", "dealer_kind", "kinds"}
)


#: Target kinds that make a clause a legal antecedent for the next clause's
#: creature pronoun. `EffectSpec` params name their target kinds in a handful
#: of differently-named keys (``target_kind`` for the damage/tap/destroy
#: families, ``fighter_kind``/``other_kind``/``dealer_kind`` for the fight
#: ones, a ``kinds`` list for `effects.ChooseTargetsEffect`), so this scans
#: values rather than assuming one key.
CREATURE_TARGET_KINDS: frozenset[str] = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control",
     "other_creature_you_control",
     # Not only creatures: the tap-then-lock family ("Tap target **land**. It
     # doesn't untap …") refers back to a land/artifact/permanent with the
     # same pronoun, and a permanent pronoun is no more ambiguous than a
     # creature one — the gate is about *whether the previous clause chose
     # something at all*, not about what type it chose.
     "land", "artifact", "permanent", "nonland_permanent",
     "artifact_creature_or_land", "artifact_or_creature",
     # PAR-124: "target land you control becomes a 4/4 … creature … **it**
     # must be blocked this turn if able." (Disturbed Slumber/Elemental
     # Uprising/Vengeant Earth) — the animate-land family's own target
     # kinds, referred back to the same "it" way a bare "land" already is.
     "land_you_control", "creature_or_land_you_control",
     # "destroy target artifact, enchantment, or creature with flying. If that permanent's mana value was …"
     "artifact_creature_or_enchantment"}
)


def announces_creature_target(specs: list[EffectSpec]) -> bool:
    """Whether the last of ``specs`` picks a permanent (or a graveyard card,
    or — PAR-71 — a countered spell) the next clause can refer back to as
    "it"/"that creature"/"that card"/"that spell".

    A ``graveyard_*``/``any_graveyard_*``/``opponent_graveyard_*`` kind
    (PAR-18 — "exile up to 1 target creature card from a graveyard. Create a
    token that's a copy of **that card**.") is recognized by prefix rather
    than an enumerated set: this module has no `game/` import (the front-end
    security boundary), so it can't pull `game/targeting.py`'s
    `_GRAVEYARD_TARGET_KINDS` frozenset directly, and the prefix is the same
    one `catalogue.effect_rows.shared.graveyard_target_kind` builds every such kind
    from.
    """
    if not specs:
        return False
    last = specs[-1]
    # "earthbend N, then untap **that land**." (Avatar Kyoshi — PAR-30): an
    # ``earthbend`` spec always picks a target land you control (the
    # `TargetSpec` is built inside `EarthbendEffect.__init__`, not surfaced
    # as a param), so it's recognised by type here rather than by scanning
    # params like every other kind below.
    if last.type == "earthbend" and not last.params.get("previous_subject"):
        return True
    # "Create a token …. **It** gains haste until end of turn." (PAR-30 —
    # God-Pharaoh's Gift, Harried Dronesmith, Molten Duplication, Mordor on
    # the March): a create/copy clause makes an object the next clause's
    # "it" points at, read at resolve time off `GameContext.created_objects`
    # rather than `previous_targets` (`PumpEffect.previous_subject`'s own
    # fallback). ``copy_permanent``/``become_copy`` included since the
    # reanimator-token grammar routes "a token that's a copy of that card"
    # through them.
    # "Manifest dread, then put two +1/+1 counters on **that creature**" (Experimental Lab, Weight Room): the manifested
    # card is left as the next clause's referent (`created_objects`, also across the look-at-two pause).
    if last.type in ("create_token", "copy_permanent", "become_copy", "manifest", "manifest_dread"):
        return True
    # PAR-152: "…put a Vampire card from your hand onto the battlefield tapped and attacking. **It** gains
    # indestructible until end of turn." (Strefan) — the placed card is the pronoun's referent; the rider travels
    # with the placement (`_fold_placement_tails`) so it still has it once the pick is answered.
    if last.type in PLACEMENT_WITH_RIDERS:
        return True
    # "Return it to the battlefield … with 2 +1/+1 counters on it. It's a Demon in addition …" (PAR-142):
    # the returned permanent is what the rider's "it" names (`ReturnSelfToBattlefieldEffect` sets it).
    if last.type == "return_self_to_battlefield":
        return True
    # "Counter target spell. Discover X, where X is that spell's mana
    # value." (Hurl into History/Access Denied/Overwhelming Intellect/Spell
    # Swindle-shaped, PAR-71) — a ``counter`` spec's own RULE 115 target is
    # the countered spell, so a following clause's "that spell" refers back
    # to it the same way `MillEffect.selector="previous_subject_controller"`
    # (Broken Ambitions) already reads it via `GameContext.previous_targets`
    # (RULE 608.2h last-known info — the countered spell is in a graveyard,
    # with no controller, by the time a later clause asks).
    if last.type == "counter":
        return True
    # "Tap enchanted creature. If …, put three stun counters on **it**." (Kitnap — PAR-135): the Aura's host is
    # the pick the pronoun names though nothing targeted it (`TapEffect` leaves it in `previous_targets`).
    if last.type == "tap" and last.params.get("target_kind") == "attached_permanent":
        return True
    if last.type == "tap" and last.params.get("target_kind") == "source":
        return False  # "tap ~" picks nothing: the source is not a referent a later "it" can reach
    values: list[Any] = []
    for value in last.params.values():
        values.extend(value if isinstance(value, list) else [value])
    return any(
        isinstance(v, str) and (
            target_kind_allowed(v, CREATURE_TARGET_KINDS)
            or v.startswith(("graveyard_", "any_graveyard_", "opponent_graveyard_"))
        )
        for v in values
    )


PLACEMENT_WITH_RIDERS: frozenset[str] = frozenset(
    {"put_from_hand_onto_battlefield", "put_from_defending_hand", "inspect_top_choose"}
)


#: "…put N +1/+1 counters on **it**." ending a clause whose predecessor chose
#: or created an object.
COUNTERS_ON_IT_RE = re.compile(r"\bcounters? on it\.?$", re.IGNORECASE)


#: The `add_counters` params that already say where the counters go.
ADD_COUNTERS_PLACEMENT_KEYS = (
    "target_kind", "selector", "trigger_subject_key", "previous_subject", "ring_bearer",
)


def stamp_counters_on_referent(part: str, specs: list[EffectSpec]) -> list[EffectSpec]:
    """PAR-120: "Create a 0/0 Fractal creature token. Put three +1/+1
    counters on **it**." — `effect_rows.counters_blocking._add_counters` reads a bare "it" as the
    ability's own source (its `_SELF_SUBJECT` alternation), which put the
    counters on Additive Evolution itself and let the 0/0 token die. When the
    previous clause chose or created an object, "it" is that object (RULE
    608.2c), so the spec is re-pointed at it (``previous_subject``, which
    `AddCountersEffect` resolves from `previous_targets`, else
    `created_objects`). An explicit "~"/"this creature" never matches."""
    if not specs or not COUNTERS_ON_IT_RE.search(part.split(", where x is")[0]):
        return specs
    if len(specs) > 1:
        # MEC-108: "put a +1/+1 counter and a flying counter on it" — one
        # `add_counters` per kind, every one of them aimed at the same "it".
        if all(
            spec.type == "add_counters"
            and not any(spec.params.get(key) for key in ADD_COUNTERS_PLACEMENT_KEYS)
            for spec in specs
        ):
            return [
                EffectSpec("add_counters", {**spec.params, "previous_subject": True},
                           condition=spec.condition)
                for spec in specs
            ]
        return specs
    spec = specs[0]
    if spec.type == "bind":
        # "Put X +1/+1 counters on it, where X is …" — the measured sibling.
        inner = spec.params.get("effects") or []
        if len(inner) != 1 or inner[0].get("type") != "add_counters":
            return specs
        inner_params = inner[0].get("params") or {}
        if any(inner_params.get(key) for key in ADD_COUNTERS_PLACEMENT_KEYS):
            return specs
        restamped = {**inner[0], "params": {**inner_params, "previous_subject": True}}
        return [EffectSpec("bind", {**spec.params, "effects": [restamped]}, condition=spec.condition)]
    if spec.type != "add_counters":
        return specs
    if any(spec.params.get(key) for key in ADD_COUNTERS_PLACEMENT_KEYS):
        return specs
    return [EffectSpec("add_counters", {**spec.params, "previous_subject": True},
                       condition=spec.condition)]
