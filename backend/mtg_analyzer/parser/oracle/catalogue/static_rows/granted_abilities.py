"""Static-ability helpers: granted abilities (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Any, Optional
from ...spec import EffectSpec, ParserProvenance
from ..clause_primitives import ONCE_PER_TURN_MARKER, SORCERY_SPEED_MARKER
from ..keywords import cumulative_upkeep_dash_payable, cumulative_upkeep_mana_alternatives
from ..subgrammars import COLOR_LETTERS
from ..clause_hooks import segment_line
from ..subtype_vocabulary import SUBTYPES
from ...normalize import normalize
from .anthem_patterns import (
    CHOSEN_TAIL,
    GRANTABLE_TRIGGER_EVENTS,
    QUOTED_GRANT_RE,
    REGRANT_PASSTHROUGH_TRIGGER_KEYS,
    REGRANT_SAFE_GROUP_KEYS,
)
from .combat_restrictions import ATTACHED_SUBJECT_PATTERN
from .keyword_flags import GRANTED_WARD_RE, flag_keywords_and_ward

#: WUBRG, for a granted "add N mana of any [one] color" ability — one
#: single-colour production option per colour, the payer picking which
#: (mirrors `game/mana_abilities.py`'s own `_parse_clause` representation
#: exactly; kept as a local literal rather than imported, since this module
#: must stay free of `game/` imports).
_GRANTED_MANA_COLORS = ("W", "U", "B", "R", "G")

#: A granted **mana** ability's inner body — "{T}: Add {B}." (Tyvar Kell),
#: "{T}: Add 1 mana of any color." (Abundant Growth), "{T}: Add 2 mana of any
#: 1 color." (Find the Path — `normalize` folds both number words to digits,
#: including the "any *one* color" one). Recognised *here* rather than by the
#: nested `segment_line` parse below because a plain top-level mana ability is
#: claimed-**without**-a-spec by `segmenter.py`: mana production is covered
#: directly by `game/mana_abilities.py`'s own text recognition off the printed
#: card, not by the `EffectRegistry` pipeline, so the recursive parse comes
#: back with `spec is None` and nothing to re-emit. `grant_mana_ability`
#: (`game/effects/core.py`, layer 6/RULE 613.7f) is the existing engine primitive
#: — only this front end was missing.
#:
_GRANTED_MANA_PIPS = r"(?:\{[wubrgc]\})+"
_GRANTED_MANA_ABILITY_RE = re.compile(
    # PAR-326 (Lotus Ring, Minimus Containment): "{T}, Sacrifice this <host>: Add ..." -- the combined cost; the "~" is the
    # host that holds the granted ability (RULE 113.7a: the object the ability is on), not the Aura/Equipment.
    r"(?P<cost>\{t\}, sacrifice (?:this permanent|~)|\{t\}|sacrifice (?:this permanent|~)):\s*add\s+(?:"
    rf"(?P<syms>{_GRANTED_MANA_PIPS}(?:(?:,\s*{_GRANTED_MANA_PIPS})*,?\s+or\s+{_GRANTED_MANA_PIPS})?)"
    r"|(?P<n>\d+) mana of any (?:1 )?colou?r"
    r")\.?"
    # PAR-109 (Nexos, Resonating Lute): "Spend this mana only on costs that contain {X}" / "…only to cast instant
    # and sorcery spells" — the two spend restrictions a granted land ability prints; the same dict shapes
    # `game/mana_abilities._parse_restriction` reads for a printed one (this package cannot import `game/`).
    r"(?: spend this mana only (?P<restr>on costs that contain \{x\}|to cast instant and sorcery spells)\.?)?",
    re.IGNORECASE,
)
_GRANTED_MANA_RESTRICTIONS: dict[str, dict] = {
    "on costs that contain {x}": {"kind": "contains_x"},
    "to cast instant and sorcery spells": {"kind": "instant_or_sorcery_spell"},
}
_GRANTED_MANA_COMBINATION_RE = re.compile(
    r"\{t\}:\s*add\s+(?P<n>\d+) mana in any combination of colou?rs\.\s*"
    r"spend this mana only to cast spells\.?",
    re.IGNORECASE,
)


def _granted_mana_options(inner: str) -> Optional[tuple[list[dict[str, int]], str, Optional[dict]]]:
    """A quoted mana ability's ``mana`` production options, or ``None``.

    Returns the same "list of ``{colour: amount}`` options, payer picks one"
    shape `mana_abilities.mana_options_for` already consumes for a printed
    ability — a fixed pip run collapses to a single option, an "any colour"
    clause fans out to one option per colour.
    """
    m = _GRANTED_MANA_ABILITY_RE.fullmatch(inner.strip())
    if m is None:
        return None
    restriction = _GRANTED_MANA_RESTRICTIONS[m.group("restr").lower()] if m.group("restr") else None
    syms = m.group("syms")
    if syms:
        options = []
        for run in re.split(r",?\s+or\s+|,\s*", syms):
            option: dict[str, int] = {}
            for sym in re.findall(r"\{([wubrgc])\}", run, re.IGNORECASE):
                option[sym.upper()] = option.get(sym.upper(), 0) + 1
            options.append(option)
        return options, m.group("cost"), restriction
    amount = int(m.group("n"))
    if amount < 1:
        return None
    return [{color: amount} for color in _GRANTED_MANA_COLORS], m.group("cost"), restriction


def quoted_ability_grant_effects(inner: str) -> Optional[EffectSpec]:
    """Recursively parse a quoted granted-ability body into a single
    `grant_triggered_ability`/`grant_activated_ability`/`grant_mana_ability`
    `EffectSpec`, or ``None``. Thin wrapper over `_quoted_ability_grant_
    effects_list` for the callers that only ever expect one spec — returns
    ``None`` when the body would produce more than one (a compound-event
    trigger; those callers pass through the list-returning helper instead)."""
    specs = quoted_ability_grant_effects_list(inner)
    return specs[0] if specs and len(specs) == 1 else None


#: A newly granted attachment-relative static can begin applying in layer 6
#: (keywords) or layer 7 (P/T modifiers), which the continuous engine projects
#: after creating the ability. Earlier-layer type/color changes would need a
#: different layer dependency mechanism and must remain unclaimed here.
_GRANTED_ATTACHMENT_STATIC_TYPES = frozenset({"grant_keyword", "anthem"})


def quoted_ability_grant_effects_list(inner: str) -> Optional[list[EffectSpec]]:
    """Recursively parse a quoted granted-ability body into one or more
    grant `EffectSpec`s, or ``None`` if it isn't a plain self-scoped trigger
    on a `GRANTABLE_TRIGGER_EVENTS` event (incl. a compound "enters or
    leaves the battlefield" one → one `grant_triggered_ability` per event),
    a controller-scoped phase trigger, a plain `<cost>: <effect>` activated
    ability, or a bare `{T}: Add <mana>` mana ability (see the module
    comment above `ATTACHED_QUOTED_GRANT_RE`)."""

    # A quotation embedded before a following static clause is commonly
    # written as `has "…," and is …` (Black Mage's Rod).  That comma belongs
    # to the outer English list, not the granted ability, and would otherwise
    # make the recursive effect-body parse fail closed.
    inner = normalize(inner).rstrip(" ,.;")
    nested = QUOTED_GRANT_RE.fullmatch(inner)
    if nested is not None and nested['quote'] == "'":
        # A quotation inside a quoted grant uses single delimiters. Feed
        # the ordinary segmenter its normal double-quoted form, preserving
        # apostrophes within the granted ability itself.
        start, end = nested.span('inner')
        inner = inner[:start - 1] + '"' + inner[start:end] + '"' + inner[end + 1:]
    # RULE 114.2: a quotation nested inside a granted ability uses single
    # quotation marks; preserve apostrophes within that emblem's ability.
    inner = re.sub(r"(emblem with )'(.+)'$", r'\1"\2"', inner)
    # "another +1/+1 counter" is one additional counter instruction, not a
    # distinct counter kind.  Canonicalise the tightly-scoped printed form so
    # the ordinary counter body can be recursively parsed in any granted
    # ability (rather than teaching every outer lord/state template about it).
    inner = re.sub(
        r"\bput another (?P<counter>[+-]\d+/[+-]\d+ counter)\b",
        r"put a \g<counter>", inner, flags=re.IGNORECASE,
    )

    # MEC-88 / RULE 702.22b: "bands with other <quality>" is its own named
    # ability, distinct from plain Banding, but the *quality* restriction
    # only matters for RULE 702.22c's interactive attacking-band
    # declaration — out of scope here (no Commander-legal card in this
    # batch ever declares a real attacking band; every one just grants the
    # ability). `keywords.py`'s own `_ALIASES["bands_with_other"] =
    # "banding"` already treats the two as interchangeable for a card that
    # *prints* the keyword itself; this mirrors that same precedent for a
    # card that *grants* it as a quoted ability, dropping the quality
    # tail rather than threading a second parametric keyword through the
    # grant machinery for a restriction nothing here enforces yet.
    if re.fullmatch(r"bands with other [a-z][a-z' -]*", inner.strip().rstrip("."), re.IGNORECASE):
        return [EffectSpec("grant_keyword", {
            "keywords": ["banding"], "affects": "attached_permanent",
        })]

    # RULE 702.24: this is a cost-bearing keyword, not a numeric parametric
    # keyword, so it cannot use the ordinary `parametric_keywords` grant
    # path.  Layer 6 rebuilds its existing keyword trigger per host.
    cumulative = re.fullmatch(
        r"cumulative upkeep(?:—|\s+)(?P<cost>.+?)\.?", inner.strip(), re.IGNORECASE
    )
    if cumulative is not None:
        cost = cumulative.group("cost").strip()
        # BUG-64: a granted dash cost must be one the upkeep trigger can pay (a mana run or a payable non-mana cost).
        dash_form = "\u2014" in inner
        if not dash_form and re.search(r"\bor\b", cost, re.I):
            # RULE 702.24a: "{G} or {W}" is a per-counter choice, recorded as one hybrid symbol; any other alternative is unclaimed.
            alternatives = cumulative_upkeep_mana_alternatives(f"cumulative upkeep {cost}")
            if alternatives is None:
                return None
            cost = alternatives
        if cost and (not dash_form or cumulative_upkeep_dash_payable(cost)):
            return [EffectSpec("grant_keyword", {
                "cumulative_upkeep_cost": cost,
                "affects": "attached_permanent",
            })]

    combination_mana = _GRANTED_MANA_COMBINATION_RE.fullmatch(inner.strip())
    if combination_mana is not None:
        amount = int(combination_mana.group("n"))
        if amount < 1:
            return None
        return [EffectSpec("grant_mana_ability", {
            "mana": [{color: amount} for color in _GRANTED_MANA_COLORS],
            "mana_any_combination": True,
            "mana_restriction": {"kind": "spell"},
            "affects": "attached_permanent",
        })]

    mana_grant = _granted_mana_options(inner)
    if mana_grant is not None:
        mana, mana_cost, mana_restriction = mana_grant
        params: dict[str, Any] = {"mana": mana, "affects": "attached_permanent"}
        if mana_restriction:
            params["mana_restriction"] = dict(mana_restriction)
        # A bare "{T}: Add …" (Tyvar Kell) folds onto the granted-to permanent's
        # own tap ability the same way its hand-authored catalogue entry does
        # (`continuous.recompute`'s plain `_granted_mana` bucket) — only the
        # non-tap "sacrifice this permanent: …" variant needs its cost recorded
        # (routing through the separate `_granted_mana_abilities` bucket
        # instead); tagging *every* grant with its cost, `{T}` included, was
        # silently routing the common case through that other bucket too,
        # which `GameObject.granted_mana_options` never reads.
        if mana_cost.strip().lower() != "{t}":
            params["granted_mana_cost"] = mana_cost
        return [EffectSpec("grant_mana_ability", params)]

    ward = GRANTED_WARD_RE.fullmatch(inner.strip().rstrip("."))
    if ward is not None:
        return [EffectSpec("grant_keyword", {
            "ward_cost": ward.group("cost").strip(), "affects": "attached_permanent",
        })]

    # A self-scoped replacement body.  Keeping it in the recursive quote
    # parser lets the outer static provide its normal generic group selector
    # (subtype, controller, attachment, and so on).
    if re.fullmatch(
        r"if (?:this permanent|~) would be put into a graveyard, you may put it on top of its owner(?:'|’)?s library instead",
        inner.strip().rstrip("."), re.IGNORECASE,
    ):
        return [EffectSpec("grant_graveyard_to_library_replacement", {
            "affects": "attached_permanent",
        })]

    # "This permanent becomes the creature type of your choice in addition
    # to its other types until end of turn."  The choice and the temporary
    # layer-4 type addition are pre-existing generic building blocks; this
    # only composes them for a quoted activated ability of any cost/group.
    chosen_type = re.fullmatch(
        r"(?P<cost>.+?):\s*(?:this permanent|~) becomes the creature type of your choice in addition to its other types until end of turn",
        inner.strip().rstrip("."), re.IGNORECASE,
    )
    if chosen_type is not None:
        return [EffectSpec("grant_activated_ability", {
            "cost": {"text": chosen_type.group("cost").strip()},
            "grant_effects": [{
                "type": "_request_choose_creature_type_grant",
                "params": {"then_specs": [{
                    "type": "grant_until",
                    "params": {
                        "duration": "end_of_turn", "self_subject": True,
                        "static": {"type": "type_change", "params": {
                            "add_subtypes_from_source": True,
                        }},
                    },
                }]},
            }],
            "affects": "attached_permanent",
        })]

    # Generic activation composition: a coin flip chooses between a self
    # exile plus an already-supported delayed self-return, and self
    # sacrifice.  No named card or creature type belongs to this shape.
    flicker_coin = re.fullmatch(
        r"(?P<cost>.+?):\s*if (?:this permanent|~) is on the battlefield, flip a coin\.\s*"
        r"if you win the flip, exile (?:this permanent|~) and return (?:it|this permanent|~) to the battlefield under its owner's control at the beginning of the next end step\.\s*"
        r"if you lose the flip, sacrifice (?:it|this permanent|~)",
        inner.strip().rstrip("."), re.IGNORECASE,
    )
    if flicker_coin is not None:
        return [EffectSpec("grant_activated_ability", {
            "cost": {"text": flicker_coin.group("cost").strip()},
            "grant_effects": [{
                "type": "coin_flip",
                "params": {
                    "win_effects": [
                        {"type": "exile", "params": {"target_kind": None}},
                        {"type": "create_delayed_trigger", "params": {
                            "step": "end", "scope": "any",
                            "effects": [{"type": "return_self_to_battlefield", "params": {}}],
                        }},
                    ],
                    "lose_effects": [{"type": "sacrifice_self", "params": {}}],
                },
            }],
            "affects": "attached_permanent",
        })]

    # Name a card, reveal one random opposing hand card, then conditionally
    # discard it.  Naming substitution and the random-reveal/name-comparison
    # operation are generic catalog entries; this only maps their printed
    # sequence into a quoted activated ability.
    named_random_discard = re.fullmatch(
        r"(?P<cost>.+?):\s*choose a card name\.\s*target opponent reveals a card at random from their hand\.\s*"
        r"if that card has the chosen name, that player discards it\.\s*activate only during your turn",
        inner.strip().rstrip("."), re.IGNORECASE,
    )
    if named_random_discard is not None:
        return [EffectSpec("grant_activated_ability", {
            "cost": {"text": named_random_discard.group("cost").strip()},
            "grant_effects": [{
                "type": "name_card_then",
                "params": {"effects": [{
                    "type": "reveal_random_hand_card_if_named",
                    "params": {"named_card": "named_card", "target_kind": "opponent"},
                }]},
            }],
            "sorcery_speed_only": True,
            "affects": "attached_permanent",
        })]

    segment = segment_line(
        inner.strip(),
        allow_spell_effect=False,
        provenance=ParserProvenance(version="nested", source="rule:oracle"),
    )
    spec = segment.spec
    if spec is None or spec.modes:
        return None

    if spec.ability_kind == "activated":
        # "<host> has '{cost}: <effect>.'" (Umbral Mantle/Squirrel
        # Nest-shaped) — layer 6, ability-adding (RULE 613.7f), granting a
        # full activated ability. `once_per_turn`/`sorcery_speed_only`
        # markers mirror `effect_binder.bind_ability`'s own stripping for a
        # top-level activated ability (no real card needs either yet, but a
        # quoted "Activate only once each turn." shouldn't silently leak a
        # marker EffectSpec into `grant_effects` for `build_effects` to choke
        # on) — this nested parse doesn't go through `bind_ability` itself.
        effect_specs = spec.effects
        limits = [int(e.params.get("count", 1)) for e in effect_specs if e.type == ONCE_PER_TURN_MARKER]
        per_turn_limit = min(limits) if limits else 0
        once_per_turn = per_turn_limit == 1
        sorcery_speed_only = any(e.type == SORCERY_SPEED_MARKER for e in effect_specs)
        effect_specs = [
            e for e in effect_specs
            if e.type not in (ONCE_PER_TURN_MARKER, SORCERY_SPEED_MARKER)
        ]
        cost = dict(spec.cost or {})
        if re.match(r"\s*unattach\b", inner, re.IGNORECASE):
            # The printed name refers to the Aura/Equipment providing this
            # ability, not to its host (RULE 113.7a). Layer 6 stamps that
            # object's identity onto the activated cost.
            cost["unattach_grant_source"] = True
        return [EffectSpec("grant_activated_ability", {
            "cost": cost,
            "grant_effects": [{"type": e.type, "params": e.params} for e in effect_specs],
            "once_per_turn": once_per_turn,
            **({"per_turn_limit": per_turn_limit} if per_turn_limit > 1 else {}),
            "sorcery_speed_only": sorcery_speed_only,
            "affects": "attached_permanent",
        })]

    if spec.ability_kind == "static":
        # RULE 113.7: the recipient is the source of its granted static.
        # Both self and attached scopes therefore resolve from that object:
        # a Rune grants its enchanted Equipment an ability affecting the
        # Equipment's equipped creature, not the Aura's own attachment.
        if not spec.effects:
            return None
        if any(e.params.get("affects") is None for e in spec.effects):
            return None
        if any(e.params.get("affects") == "attached_permanent"
               and e.type not in _GRANTED_ATTACHMENT_STATIC_TYPES for e in spec.effects):
            return None
        return [EffectSpec("grant_static_ability", {
            "static_specs": [{"type": e.type, "params": e.params} for e in spec.effects],
            "affects": "attached_permanent",
        })]

    if spec.ability_kind != "triggered":
        return None
    trigger = spec.trigger or {}
    event = trigger.get("event")
    # A compound "enters or leaves the battlefield" inner trigger
    # (`segmenter._SELF_MULTI_EVENT_RE`) stamps a *list* of events on
    # `AbilitySpec.trigger`. Re-grant it as one `grant_triggered_ability`
    # per event (each independently identity-scoped by
    # `_granted_trigger_condition`) — every event in the list must itself be
    # grantable and `{"subject": "self"}`, else fail closed for the whole
    # body. `LEAVES_BATTLEFIELD` fires *before* removal (RULE 603.6a), so
    # the granted-to permanent (and its granted ability) still exists when
    # the trigger is collected.
    events = event if isinstance(event, list) else [event]
    if any(e not in GRANTABLE_TRIGGER_EVENTS for e in events):
        return None
    if len(events) > 1 and trigger.get("condition") != {"subject": "self"}:
        return None
    if len(events) == 1:
        event = events[0]
    group_condition: Optional[dict] = None
    if event == "STEP_BEGIN":
        # A RULE 500.7 phase trigger carries no object subject to re-scope
        # (see `GRANTABLE_TRIGGER_EVENTS`).  An unscoped "each upkeep"
        # trigger is still well-defined: every permanent with the granted
        # ability fires once at every matching upkeep.  Scoped forms add the
        # host-controller-relative `phase_relation` filter below.
        if trigger.get("phase_relation") not in (None, "you", "not_you"):
            return None
    elif event in ("LIFE_GAINED", "DRAW", "SPELL_CAST", "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER"):
        # A player-subject condition (`{"subject": "you"}`) rather than the
        # object-subject the `elif` below requires — "Whenever **you** gain
        # life …" / "Whenever **you** cast a spell …" (Passionate
        # Archaeologist) / "Whenever 1 or more creatures **you control**
        # deal combat damage to a player …" (Feywild Visitor). `game/
        # continuous.py`'s `_granted_trigger_condition` resolves "you"
        # against the granted-to permanent's own controller once regranted
        # (`_PLAYER_SUBJECT_GRANTED_EVENTS`).
        condition = trigger.get("condition") or {}
        if condition == {"subject": "you"}:
            pass
        elif condition.get("subject") == "group" and set(condition) <= REGRANT_SAFE_GROUP_KEYS:
            # "Whenever an opponent casts a spell" is just as host-relative
            # as the other safe group filters: the regranted ability's host
            # supplies the meaning of "you" for ``not_you``.
            group_condition = dict(condition)
        else:
            return None
    elif trigger.get("controls_none_matching") and not trigger.get("condition"):
        pass  # RULE 603.8 state trigger: the gate (re-evaluated against the host) is the whole condition
    elif len(events) == 1 and trigger.get("condition") != {"subject": "self"}:
        cond = trigger.get("condition") or {}
        # PAR-32: a `{"subject": "group"}` condition re-grants fine as long
        # as every key stays meaningful relative to the granted-to
        # permanent (`REGRANT_SAFE_GROUP_KEYS`) — "whenever an artifact or
        # creature you control dies, …" (Agent of the Iron Throne).
        if (
            cond.get("subject") == "group"
            and set(cond) <= REGRANT_SAFE_GROUP_KEYS
        ):
            group_condition = dict(cond)
        else:
            return None  # any other subject wouldn't mean the same thing once regranted
    grant_effects = [{"type": e.type, "params": e.params} for e in spec.effects]
    out: list[EffectSpec] = []
    for ev in events:
        params: dict = {
            "trigger_event": ev,
            "grant_effects": grant_effects,
            "optional": spec.optional,
            "affects": "attached_permanent",
        }
        if group_condition is not None:
            params["group_condition"] = group_condition
        if trigger.get("filter"):  # RULE 120.3 DAMAGE combat/is_player, STEP_BEGIN's step
            params["filter"] = dict(trigger["filter"])
        if trigger.get("phase_relation"):
            params["phase_relation"] = trigger["phase_relation"]
        if isinstance(trigger.get("active_if"), dict):
            # PAR-32: a re-granted phase trigger's RULE 603.4 intervening-if
            # (Cloakwood Hermit / Dragon Cultist) — evaluated against the
            # granted-to permanent in `_apply_layer_6_ability`.
            params["trigger_active_if"] = dict(trigger["active_if"])
        if trigger.get("limit"):
            # RULE 603.2's once-per-turn cap ("this ability triggers only
            # once each turn" — Folk Hero) survives re-granting.
            params["once_per_turn"] = True
        # PAR-32: firing-event gate flags that survive re-granting — each has
        # its own `effect_binder` predicate `_apply_layer_6_ability`
        # composes onto the granted trigger (the "no opponent has more life
        # than that player" gate, "cast a spell from exile", …).
        for key in REGRANT_PASSTHROUGH_TRIGGER_KEYS:
            if trigger.get(key):
                params[key] = trigger[key]
        out.append(EffectSpec("grant_triggered_ability", params))
    return out


# RULE 702.16 **standing** protection grants — the layer-6 sibling of the
# resolve-time "until end of turn" grant (Mother of Runes) the engine
# already had. Three printed subjects, each its own regex because the verb
# and the `affects` selector differ:
#
#   * a controlled/global group — "Cats you control have protection from
#     Rats." (Hungry Lynx), "White creatures you control have protection
#     from black." (Righteous War), "All creatures have protection from
#     black." (Absolute Grace/Absolute Law). Shares `parse_scope`/`parse_scope_params`
#     with `ANTHEM_RE`/`GRANT_RE`.
#   * an attached permanent — "Enchanted creature has protection from the
#     chosen color." (Flickering Ward/Cho-Manno's Blessing/Pentarch Ward).
#   * the source itself — "~ has protection from the chosen color." (Voice
#     of All/Order of the Stars).
#
# These must be checked *before* `GRANT_RE`/`ATTACHED_GRANT_RE`, whose
# `flag_keywords` would reject "protection from black" outright (protection
# isn't a RULE 702 flag keyword — it carries a parameter) and fail the whole
# clause closed.
#
# The quality itself is captured as printed and normalized engine-side
# (`continuous._protection_qualities` → `combat.protections_of_text`), which
# is what keeps this module free of `game/` imports. "…and from <quality>"
# multi-quality tails (the Sword cycle's printed form) are left to that same
# splitter by passing the whole clause through.
_PROTECTION_QUALITY = r"(?P<quality>the chosen colou?r|[a-z][a-z ]*?)"
# RULE 702.16n/p's own carve-out on an attached-permanent grant — "This
# effect doesn't remove this Aura/these Auras and Equipment." (Black Ward &c,
# Benevolent Blessing) — an Aura whose granted protection would otherwise
# make *itself* an illegal attachment (RULE 704.5m) the next SBA pass
# (`RulesEngine._attachment_legal`'s `_protection_self_exempt` check). Kept
# optional and non-capturing since it's purely a modifier on the grant, not
# a separate effect; only the attached-permanent shape needs it — no shipped
# card pairs this tail with the group/self forms.
_PROTECTION_SELF_EXEMPT_TAIL = r"(?P<exempt>\. this effect doesn'?t remove [^.]*)?"
GROUP_PROTECTION_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ,/]*?)(?P<yours> you control)?"
    rf"{CHOSEN_TAIL} "
    rf"have protection from {_PROTECTION_QUALITY}",
    re.IGNORECASE,
)
ATTACHED_PROTECTION_RE = re.compile(
    rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN}) has protection from {_PROTECTION_QUALITY}"
    rf"{_PROTECTION_SELF_EXEMPT_TAIL}",
    re.IGNORECASE,
)
SELF_PROTECTION_RE = re.compile(
    rf"~ has protection from {_PROTECTION_QUALITY}", re.IGNORECASE
)

# The compound "+N/+N **and** protection" forms — the whole Sword-of-X-and-Y
# cycle ("Equipped creature gets +2/+2 and has protection from red and from
# blue.", 24 cards) and its group sibling (Feline Sovereign/Haytham Kenway's
# "Other Cats you control get +1/+1 and have protection from Dogs."). These
# need their own rows rather than an extra tail on `ATTACHED_ANTHEM_RE`/
# `ANTHEM_RE`, whose "and has/have <keywords>" tail goes through
# `flag_keywords` — protection isn't a RULE 702 flag keyword (it carries a
# parameter), so that tail rejects it and fails the whole clause closed.
ATTACHED_ANTHEM_PROTECTION_RE = re.compile(
    rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN}) gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) "
    rf"and has protection from {_PROTECTION_QUALITY}"
    rf"{_PROTECTION_SELF_EXEMPT_TAIL}",
    re.IGNORECASE,
)
GROUP_ANTHEM_PROTECTION_RE = re.compile(
    r"(?:(?P<scope>other) )?(?P<body>[a-z][a-z ,/]*?)(?P<yours> you control)?"
    rf"{CHOSEN_TAIL} "
    rf"get (?P<p>[+-]\d+)/(?P<t>[+-]\d+) and have protection from {_PROTECTION_QUALITY}",
    re.IGNORECASE,
)


def protection_params(quality: str) -> Optional[dict]:
    """The `grant_protection` quality params for a captured ``quality``, or
    ``None`` for one this can't express (fail-closed).

    "the chosen color" (RULE 601.2b) becomes the dynamic flag the layer
    engine re-reads off the source every pass; "each color"/"each colour"
    (Spectra Ward) is a fixed blanket quality — unlike Rebbec's "each mana
    value among..." below, it names no board-dependent computation, so it
    folds to the same "all colors" word `combat.protections_of_text`
    already recognizes. Anything else is passed through verbatim as a
    printed quality word for that function to normalize. Rebbec's
    "protection from each mana value among artifacts you control" and
    Pledge of Loyalty's "the colors of permanents you control" are
    deliberately *not* expressible — a per-source computed quality, not a
    fixed one — and neither is a plain quality word/phrase, so both fall out
    here (" each "/" of ") rather than being mis-stored as one.
    """
    quality = quality.strip().rstrip(".").strip()
    if quality in ("the chosen color", "the chosen colour"):
        return {"protection_from_chosen_color": True}
    if quality in ("each color", "each colour"):
        return {"protections": ["all colors"]}
    if quality == "creatures of the chosen type":
        return {"protection_from_chosen_type": True}
    if not quality or " each " in f" {quality} " or " of " in f" {quality} ":
        return None
    return {"protections": [q.strip() for q in re.split(r"\s+and\s+from\s+", quality)]}


# PAR-8: "Each [<filter>] card in your hand has cycling `<cost>`." (Jo
# Grant/Rhet-Tomb Mystic/Tectonic Reformation) — a layer-6 ability grant
# whose *targets* are hand cards, a zone `parse_scope`/`GRANT_RE`'s battlefield
# selectors never reach; `game/continuous.py`'s dedicated
# `_apply_hand_cycling_grants` pass is the engine side. ``filter`` is an
# optional printed card type, or "historic" (CR glossary: legendary, an
# artifact, or a Saga) — bare "each card in your hand" (no filter) is also
# real wording (the ticket's own example) and simply omits the group. Never
# collides with `GRANT_RE`/`ANTHEM_RE` (plural "have"/"get") or the
# attached-subject rows (enchanted/equipped/fortified only) — this is
# singular "has" over a subject none of those recognize.
_HAND_CYCLING_TYPES = (
    "creature", "land", "artifact", "enchantment", "instant", "sorcery",
    "planeswalker", "historic",
)
HAND_CYCLING_GRANT_RE = re.compile(
    rf"each (?:(?P<filter>{'|'.join(_HAND_CYCLING_TYPES)}) )?card in your hand "
    rf"has cycling (?P<cost>\{{[^}}]+\}}(?:\{{[^}}]+\}})*)",
    re.IGNORECASE,
)


# ENG-67: "Each [<filter>] card in your graveyard has unearth `<cost>`." (Sedris, the Traitor King; Dregscape Sliver;
# Mishra, Tamer of Mak Fawa; Solemn Doomguide: "... that's a Cleric, Rogue, Warrior, and/or Wizard") and "Each
# [<filter>] card in your hand has miracle `<cost>`." (Lorehold, the Historian). Only a keyword whose printed behaviour
# the engine really builds is accepted (`ZONE_KEYWORD_GRANTS`): Encore, Jump-start and typecycling grants stay
# unclaimed (BUG-75). The cost is a literal mana cost; an "{X}, where X is its mana value" cost is not matched.
ZONE_KEYWORD_GRANT_RE = re.compile(
    r"(?:each )?(?P<filter>[a-z][a-z, /]*?) cards? in your (?P<zone>graveyard|hand)"
    r"(?: that'?s an? (?P<subs>[a-z][a-z, /]*?))? (?:has|have) (?P<kw>unearth|miracle|encore|scavenge|ninjutsu) "
    r"(?P<cost>(?:\{[^}]+\})+)\.?",
    re.IGNORECASE,
)


# MEC-53 / PAR-31: "[<filter>] cards in your graveyard have retrace."
# (Wrenn and Six's −7 emblem — "instant and sorcery cards …"; Deeproot
# Historian — "Merfolk and Druid cards …"; bare "cards in your graveyard
# have retrace"). Retrace is the only keyword that means anything on a
# *graveyard* card (RULE 702.81 — a cast-from-graveyard permission), so
# this row hardcodes it rather than sharing `flag_keywords`. `<filter>`
# is an optional list of main-type words (`card_types`) and/or creature
# subtypes (`subtypes`), split in `graveyard_retrace_grant_specs`.
GRAVEYARD_RETRACE_GRANT_RE = re.compile(
    r"(?:(?P<filter>[a-z][a-z, ]*?) )?cards in your graveyard have retrace",
    re.IGNORECASE,
)


# RULE 702.196b (MEC-139): "<attached subject> [doesn't untap during its controller's untap step and] can't be
# beamed up." (Marooned) -- the host creature can't be the one a beam me up cost returns. A synthetic layer-6 flag
# like `cant_attack` (`combat.has(obj, "cant_be_beamed_up")`), so it rides the same `grant_keyword` plumbing.
CANT_BE_BEAMED_UP_RE = re.compile(
    rf"(?P<subject>~|{ATTACHED_SUBJECT_PATTERN})"
    r"(?P<no_untap> doesn'?t untap during its controller'?s untap step and)? can'?t be beamed up",
    re.IGNORECASE,
)

# RULE 702.196a (MEC-139): "During your main phase, each card in your graveyard has beam me up. The beam me up
# cost is equal to that spell's mana cost. ~ can't be beamed up to cast a spell this way." (Scotty, Miracle
# Worker) -- a granted beam me up onto graveyard cards. Only this exact three-sentence shape is claimed.
GRAVEYARD_BEAM_ME_UP_GRANT_RE = re.compile(
    r"during your main phase, each card in your graveyard has beam me up\. "
    r"the beam me up cost is equal to that spell'?s mana cost\.(?P<self_excluded> ~ can'?t be beamed up to cast a spell this way)?\.?",
    re.IGNORECASE,
)

#: PAR-142: "<attached subject> [gets +N/+N,] [has <keywords>,] is a `<type words>` [creature with base
#: power and toughness N/N] in addition to its other types [, and has "<ability>"]" — an Aura/Equipment
#: that adds a type (Dub, Raven Wings, Ninja's Blades, Ensoul Artifact). One row composing the parts
#: those cards recombine, each already modelled on its own: the anthem, the keyword grant, a layer-4
#: `type_change` (RULE 205.1b — "in addition" keeps the host's own types; a base P/T rides the same
#: static, layer 7b) and a quoted-ability grant. The "it's …" spelling is what
#: `conditional_static_specs` leaves after rewriting the pronoun to the attached subject.
ATTACHED_TYPE_ADDITION_RE = re.compile(
    rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN}) "
    # "…has base power and toughness 5/5, has menace, and is a black Demon …" (Blade of the Oni)
    r"(?:has base power and toughness (?P<bp2>\d+)/(?P<bt2>\d+)(?:, and |, | and ))?"
    r"(?:gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+)(?:, and |, | and ))?"
    r"(?:has (?P<kw>[a-z0-9][a-z0-9,{}— ]*?)(?:, and |, | and ))?"  # `_KW_WITH_WARD`, defined below
    r"(?: ?is|'s) an? (?P<words>[a-z]+(?: [a-z]+)*?)"
    r"(?: with base power and toughness (?P<bp>\d+)/(?P<bt>\d+))?"
    # "…in addition to its other colors and types" — the colour words in ``words`` are *added* (layer 5).
    r" in addition to its other (?P<colors_too>colors and )?types"
    r'(?:(?:, and |, | and )has "(?P<inner>.+)")?',
    re.IGNORECASE | re.DOTALL,
)
ATTACHED_TRAILING_TYPE_RE = re.compile(
    rf"(?P<main>(?:{ATTACHED_SUBJECT_PATTERN}) .+?)\.?\s+it'?s an? (?P<words>[a-z]+(?: [a-z]+)*?) "
    r"in addition to its other types\.?",
    re.IGNORECASE | re.DOTALL,
)
_TYPE_ADDITION_CARD_TYPES = frozenset({"artifact", "creature", "enchantment", "land"})


def type_addition_params(words: str) -> Optional[dict]:
    """"`<subtype> <type>`" words of an "…in addition to its other types" clause → the
    ``add_types``/``add_subtypes``/``legendary`` params of a layer-4 `type_change`, or ``None``
    for a word that is none of them (fail closed — never a guessed subtype)."""

    add_types: list[str] = []
    add_subtypes: list[str] = []
    legendary = False
    for word in words.lower().split():
        if word == "legendary":
            legendary = True
        elif word in _TYPE_ADDITION_CARD_TYPES:
            add_types.append(word)
        elif word in SUBTYPES:
            add_subtypes.append(word.capitalize())
        else:
            return None
    if not (add_types or add_subtypes or legendary):
        return None
    return {
        **({"add_types": add_types} if add_types else {}),
        **({"add_subtypes": add_subtypes} if add_subtypes else {}),
        **({"legendary": True} if legendary else {}),
    }


def attached_type_addition(m: "re.Match[str]") -> Optional[list[EffectSpec]]:
    words = m.group("words").lower().split()
    colors: list[str] = []
    if m.group("colors_too"):
        # "a white Angel in addition to its other colors and types": the leading colour words are added colours.
        while words and words[0] in COLOR_LETTERS and words[0] != "colorless":
            colors.append(COLOR_LETTERS[words.pop(0)])
        if not colors:
            return None
    elif any(w in COLOR_LETTERS for w in words):
        return None  # a colour without "…other colors and types" means "is exactly that colour" — not modelled
    type_params = type_addition_params(" ".join(words)) if words else {}
    if type_params is None:
        return None
    base = (m.group("bp"), m.group("bt")) if m.group("bp") is not None else (m.group("bp2"), m.group("bt2"))
    if base[0] is not None:
        if m.group("bp") is not None and "creature" not in type_params.get("add_types", []):
            return None  # a base P/T after "is a …" belongs to a creature
        type_params = {**type_params, "power": int(base[0]), "toughness": int(base[1])}
    specs: list[EffectSpec] = []
    if colors:
        specs.append(EffectSpec("color", {"affects": "attached_permanent", "colors": colors, "set": False}))
    if m.group("p") is not None:
        specs.append(EffectSpec("anthem", {
            "power": int(m.group("p")), "toughness": int(m.group("t")), "affects": "attached_permanent",
        }))
    if m.group("kw"):
        resolved = flag_keywords_and_ward(m.group("kw"))
        if resolved is None:
            return None
        keywords, ward_cost = resolved
        grant: dict = {"affects": "attached_permanent"}
        if keywords:
            grant["keywords"] = keywords
        if ward_cost:
            grant["ward_cost"] = ward_cost
        specs.append(EffectSpec("grant_keyword", grant))
    if type_params:
        specs.append(EffectSpec("type_change", {"affects": "attached_permanent", **type_params}))
    if m.group("inner"):
        grants = quoted_ability_grant_effects_list(m.group("inner"))
        if grants is None:
            return None
        specs.extend(grants)
    return specs


# "<equipped/enchanted/fortified subject> gets +N/+N [and has <keywords>]"
# (attached-permanent anthem, +grant) — singular "gets"/"has", unlike the
# plural "get"/"have" of `ANTHEM_RE`/`GRANT_RE` above (those two families
# never collide on the same clause text).
#: The keyword-list character class widened to admit Ward's "{cost}" (PAR-65
#: — braces/digits alongside the ordinary bare-word list), consumed via
#: `_flag_keywords_and_ward` rather than the plain `flag_keywords`.
_KW_WITH_WARD = r"[a-z0-9][a-z0-9,{}— ]*?"
ATTACHED_ANTHEM_RE = re.compile(
    rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN}) "
    r"gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    rf"(?: and has (?P<kw>{_KW_WITH_WARD}))?"
    # RULE 701.15b: "…and is goaded" (Acquired Mutation and 7 siblings — the
    # single most common goad phrasing on a card). A tail rather than its own
    # row because it only ever appears *after* the P/T (and optionally the
    # keyword) grant of the same Aura/Equipment.
    r"(?P<goaded> and is goaded)?"
    # PAR-109: "…and is every creature type" (Amorphous Axe, Runed Stalactite) — a granted changeling.
    r"(?P<every_type> and is every creature type)?",
    re.IGNORECASE,
)
# MEC-105: the ability-removing sibling. Starforged Sword/Colossus Hammer
# combine the loss with an attached P/T bonus; Mammoth Harness is the bare
# "enchanted creature loses flying" form. Both are standing layer-6
# effects, unlike handlers.py's cleanup-scoped temporary removal.
ATTACHED_REMOVE_KEYWORD_RE = re.compile(
    rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN}) "
    r"(?:gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) and )?"
    r"loses (?P<kw>[a-z, ]+)",
    re.IGNORECASE,
)
# "<equipped/enchanted/fortified subject> has <keywords>"  (keyword-only grant)
ATTACHED_GRANT_RE = re.compile(
    rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN}) has (?P<kw>{_KW_WITH_WARD})"
    r"(?P<goaded> and is goaded)?"
    # PAR-122: RULE 509.1c's "… and must be blocked if able" (The Masamune) — the same
    # synthetic ``must_be_blocked`` flag `MUST_BE_BLOCKED_RE` grants on its own.
    r"(?P<must_be_blocked> and must be blocked if able)?",
    re.IGNORECASE,
)
# "<enchanted subject> is goaded" — the bare designation with no other grant
# alongside it (RULE 701.15b).
ATTACHED_GOADED_RE = re.compile(
    rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN}) is goaded",
    re.IGNORECASE,
)
# RULE 613.6/701.37b: "As long as ~ is monstrous, it has <keywords>."
# (Chillerpillar, Colossus of Akros &c) — the *conditional* sibling of the
# self-grant rows, gating the grant on the source's own monstrous
# designation. Only the keyword-grant tail is claimed: the two real cards
# whose tail also says "and can attack as though it didn't have defender" /
# "can block an additional 99 creatures" stay unclaimed, whole clause, rather
# than being half-modeled.
_MONSTROUS_GRANT_RE = re.compile(
    r"as long as ~ is monstrous, (?:it|~) has (?P<kw>[a-z][a-z, ]*)",
    re.IGNORECASE,
)
