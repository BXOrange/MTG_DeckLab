"""`AbilitySpec` — the intermediate representation between parse and bind.

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE INTERMEDIATE
REPRESENTATION").

One parsed ability = one `AbilitySpec`: pure, JSON-serializable data that
carries *no behaviour*. It is the contract the whole parser hangs off:

* the **front-end** (later phases) produces it from oracle text,
* it is what gets cached/versioned and, above all, **validated** — it is
  the security boundary, so nothing derived from card text ever becomes
  code; an effect is named by a whitelisted string + a params dict,
* the **back-end** (`game/effect_binder.py`) turns it into `GameEffect`
  objects via the `EffectRegistry`.

This module is intentionally **pure** (no `game/` imports). It validates
*structure* and clamps numeric magnitudes; whether an effect *type* is
actually known is the binder's check, because that requires the registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

#: The kinds of ability an `AbilitySpec` can describe (docs/09 IR).
#: Mirrors the effect hierarchy in game/effects.py plus "keyword".
ALLOWED_ABILITY_KINDS: frozenset[str] = frozenset(
    {"spell_effect", "triggered", "activated", "static", "replacement",
     "enter_replacement", "keyword"}
)

#: Ability kinds that resolve one or more one-shot effects (and therefore
#: must carry at least one `EffectSpec`).
_EFFECT_BEARING_KINDS: frozenset[str] = frozenset(
    {"spell_effect", "triggered", "activated", "enter_replacement"}
)

#: `AbilitySpec.strive_cost`'s shape: one or more brace-delimited symbols
#: (``"{2}{U}"``, ``"{1}"``, ``"{X}"``) — mirrors `parser/oracle/catalogue/
#: keywords.py`'s ``_COST_RUN`` (that module can't be imported here without
#: pulling its whole keyword-table machinery in for one regex).
_STRIVE_COST_RE = re.compile(r"(\{[^{}]+\})+")

#: Hard cap on numeric effect parameters. A malformed/hostile spec must not
#: be able to wedge a game session with an absurd loop count (e.g. "draw
#: 10^9 cards"); numeric params are clamped into ``[0, MAX_EFFECT_MAGNITUDE]``
#: at validation time (docs/09 "SECURITY MODEL": clamp params).
MAX_EFFECT_MAGNITUDE: int = 10_000

#: Numeric effect params subject to clamping (includes a keyword's "n", and
#: replacement-effect scale factors ``plus``/``multiplier`` — Angel of
#: Vitality/Hardened Scales/Fiery Emancipation).
_CLAMPED_PARAM_KEYS: tuple[str, ...] = (
    "amount", "count", "x", "n", "generic", "plus", "multiplier",
)

#: `EffectSpec.condition`'s whitelisted keys — see that field's docstring.
#: ``"target_is_controller"`` (RULE 603.4-style, gated on the *chosen
#: target* rather than an announced-cost flag — "target player gets two
#: rad counters. If that player is you, create a Treasure token." The
#: Ghoul, Gunslinger-shaped) checks the ability's own resolved target
#: (`game/effects.py`'s `ConditionalEffect._condition_holds`) against this
#: effect's controller.
#: ``"bargained"`` (RULE 701.x, Beseech the Mirror's "if this spell was
#: bargained, …") is Kicker's own ``"kicked"`` gate for a different optional
#: additional cost — same `GameObject`-flag shape, same resolve-time check.
#: ``"kicked_at_least"`` (PAR-17, RULE 702.34a — "if it was kicked twice,
#: `<effect>`.", Archangel of Wrath) is Multikicker's own count threshold,
#: an int rather than a bool (``kicker_count >= n``).
#: ``"life_gained_this_turn_at_least"`` (RULE 119.3 — "if you gained N or
#: more life this turn, `<effect>`.", Frodo, Adventurous Hobbit) reads
#: `GameState.life_gained_this_turn`. ``"is_ring_bearer"``/``"ring_tempted_
#: at_least"`` (RULE 701.51b/701.52a, Tales of Middle-earth) read `Player.
#: ring_bearer_id`/``ring_level`` — Frodo's own second clause is the first
#: card needing *both* of a condition dict's keys to hold together, which
#: is why `effects.ConditionalEffect._condition_holds` ANDs every key
#: present instead of picking the first recognised one.
_ALLOWED_CONDITION_KEYS: frozenset[str] = frozenset(
    {
        "kicked", "kicked_at_least", "bargained", "target_is_controller",
        "life_gained_this_turn_at_least", "opponent_lost_life_this_turn_at_least",
        "is_ring_bearer", "ring_tempted_at_least",
        "controls_none_of_type", "source_x_paid_at_least",
        "creatures_died_this_turn_at_least", "graveyard_has_type", "target_is_player",
        "not_already_exerted", "is_first_combat_phase", "is_your_turn",
        "opponent_cast_color_this_turn", "no_creatures_on_battlefield",
        "source_is_renowned", "shares_type_with_linked_exile", "source_was_cast",
        "source_entered_untapped", "cast_outside_sorcery_speed",
        "cards_in_graveyard_at_least", "entering_object_unique_name",
        # MEC-43 round 4C: Dark Petition's Spell mastery (a graveyard-count
        # gate narrowed to instant/sorcery cards) and Poison the Cup's
        # Foretell-gated scry (wired but unreachable — see `effects.py`'s
        # `_condition_holds` for why nothing sets `GameObject.foretold` yet).
        "instant_sorcery_cards_in_graveyard_at_least", "source_was_foretold",
        # RULE 701.30d (PAR-29): "clash with an opponent. if you win, … /
        # otherwise, …" — the outcome an earlier `ClashEffect` in the same
        # resolution stashed on `GameContext.clash_won` (or the firing
        # `CLASHED` event's own ``won``).
        "clash_won",
        # PAR-30: the pre-daybound Innistrad werewolf day/night check
        # (RULE 603.4 intervening-if) — "if no spells were cast last turn,
        # transform ~." / "if a player cast 2 or more spells last turn,
        # transform ~." Both read `GameState._last_turn_spell_count`.
        "no_spells_cast_last_turn", "two_or_more_spells_cast_last_turn",
        # PAR-30 / RULE 601.2b: "if this spell's additional cost was paid,
        # `<effect>`." / "… unless <its> additional cost was paid." — the
        # generic optional-additional-cost sibling of ``bargained``, reading
        # `GameObject.additional_cost_paid` (see that field). A bool; ``False``
        # is the "unless … paid" negative.
        "additional_cost_paid",
        # PAR-30 threaten/damage-rider after-tails, gated on the creature a
        # *previous* clause in the same resolution chose
        # (`GameContext.previous_targets`; `effects.ConditionalEffect.
        # _condition_holds`): ``previous_target_has_subtype`` (Goatnap "if
        # that creature is a Goat, …"), ``previous_target_is_equipped``
        # (Awaken the Sleeper), ``previous_target_power_at_most``
        # (Driftgloom Coyote), and ``previous_target_is_creature`` (Searing
        # Barb "~ deals N damage to any target. If it's a creature, it
        # can't block this turn." — the "any target" clause can land on a
        # non-creature). All bool except ``*_at_most``/``*_has_subtype``.
        "previous_target_has_subtype", "previous_target_is_equipped",
        "previous_target_power_at_most", "previous_target_is_creature",
        # PAR-30 Suspect one-off shapes / RULE 701.60c: "choose up to one
        # target creature. If it's suspected, exile it. Otherwise, suspect
        # it." (Agrus Kos, Spirit of Justice) — an if/else over the chosen
        # creature's own suspected state, expressed as two mutually
        # complementary conditionals (the `clash_won`/`ring_tempted_at_most`
        # idiom). Read off this effect's own resolved ``targets`` first, then
        # `GameContext.previous_targets`. A bool.
        "previous_target_is_suspected",
        # PAR-30: RULE 603.4 intervening-if on the ability's own source's
        # current (derived) subtypes — "If this creature is a Detective, …"
        # (Tenth District Hero). A string subtype word.
        "source_has_subtype",
        # PAR-30 / RULE 701.6x: "then if you've done all four this turn,
        # transform ~." (Avatar Aang) — every bending keyword action
        # (waterbend/earthbend/firebend/airbend) is in the ability
        # controller's `GameState.bends_this_turn` set. A bool.
        "did_all_bends_this_turn",
    }
)

#: `AbilitySpec.conditional_flash`'s whitelisted keys — see that field's
#: docstring. A deliberately separate whitelist from `_ALLOWED_CONDITION_KEYS`
#: above: that one gates whether an already-resolving *effect* applies;
#: this one gates a *cast/activation legality* check instead (RULE 601.3a's
#: sorcery-speed timing / RULE 606.3's loyalty timing), so the two security
#: boundaries stay distinct per docs/09.
#: ``"targets_a_commander"`` (Timely Ward-shaped, MEC-7) — see
#: `condition_query.conditional_flash_holds`'s docstring for why this one
#: alone is checked against the caster's actual chosen targets rather than
#: purely off the object/state the way ``"entered_this_turn"`` is.
#: ``"unconditional"`` (MEC-44, Necromancy — "You may cast this spell as
#: though it had flash.", no gate at all) is the trivially-true member every
#: other key here lacked: a plain, unqualified flash grant still needs a
#: `conditional_flash` entry to reach `combat.has(obj, "flash")`-shaped
#: legality (`can_cast`'s own check), it just never has anything to test.
#: ``"controller_beholds_subtype"`` (PAR-30, Molten Exhale — "you may cast
#: this spell as though it had flash if you behold a Dragon as an additional
#: cost") — a string subtype word; holds when the caster controls a
#: permanent of that subtype or holds a card of it in hand (i.e. *could*
#: behold one). **Documented simplification:** the behold reveal itself and
#: its being an additional cost aren't separately modeled — the same "the
#: 'or pay {N}' behold alternative is dropped" precedent PAR-29 set.
ALLOWED_CAST_CONDITION_KEYS: frozenset[str] = frozenset(
    {"entered_this_turn", "targets_a_commander", "unconditional",
     "controller_beholds_subtype"}
)

#: RULE 601.2f/117.3a-adjacent: "If you control a commander, you may cast
#: this spell without paying its mana cost." (Deadly Rollick/Deflecting
#: Swat/Fierce Guardianship-shaped) — a condition-gated *alternative* cost
#: (free, not just reduced), whitelisted the same way `conditional_flash`
#: gates a cast-*timing* permission; this one instead gates a cast-*cost*
#: permission, so it's its own field/whitelist (`AbilitySpec.
#: free_cast_condition`) rather than reusing that one.
ALLOWED_FREE_CAST_CONDITION_KEYS: frozenset[str] = frozenset(
    {
        "control_commander",
        # RULE 500.7-adjacent "if it's not your turn"/"if it's your turn"
        # (Force of Negation/Force of Vigor's own alt-cost gate, MEC-15) —
        # shares this whitelist/evaluator rather than getting its own, since
        # both are "is this alternative cost/cast option available right
        # now" checks (`AbilitySpec.alt_cost`'s own ``condition`` key reuses
        # this exact vocabulary).
        "not_your_turn",
        "your_turn",
        # "If an opponent cast three or more spells this turn, you may pay
        # {0} rather than pay this spell's mana cost." (Mindbreak Trap,
        # MEC-12) — a board-count threshold rather than the other keys'
        # plain booleans, so its value is a positive int instead of
        # ``True``.
        "opponent_spells_cast_this_turn_at_least",
        # "If an opponent controls a Forest and you control an Island, you
        # may cast this spell without paying its mana cost." (Submerge) — a
        # fixed named board-state gate, same boolean shape as
        # ``control_commander``.
        "opponent_controls_forest_and_you_control_island",
        # "If you control a Swamp, you may pay 4 life rather than pay this
        # spell's mana cost." (RULE 118.9, Snuff Out, MEC-12) — a basic
        # land-type word rather than a plain boolean, unlike every other
        # key above.
        "control_land_type",
        # PAR-19: "If 3 or more creatures are attacking, you may pay `<cost>`
        # rather than pay this spell's mana cost." (Lethargy Trap/Arrow
        # Volley Trap-shaped RULE 702 "Trap" template) — the combat-count
        # sibling of ``opponent_spells_cast_this_turn_at_least``, same
        # int-threshold shape.
        "creatures_attacking_at_least",
    }
)

#: RULE 118.9 "You may pay `<cost>` rather than pay this spell's mana
#: cost." (Force of Will/Force of Negation/Force of Vigor/Daze-shaped,
#: MEC-15) — a single spell-level alternative *payment*, as opposed to
#: `free_cast_condition`'s alternative of paying *nothing*. A dict from
#: this small closed vocabulary (mirrors `additional_cost`'s "fixed
#: template, not open cost text" reasoning): ``pay_life`` (an int),
#: ``return_to_hand`` (a permanent subtype word — Daze's own Island),
#: ``exile_hand_card_color`` (a WUBRG letter — the Force cycle's own
#: "exile a `<color>` card from your hand"), and ``condition`` (optional,
#: `ALLOWED_FREE_CAST_CONDITION_KEYS`-shaped — Force of Negation/Vigor's
#: own "if it's not your turn" gate). At least one payment key is
#: required; ``game/costs.py``'s `ActivationCost` is the actual charging
#: engine (`game/effect_binder.py` builds one from this dict, mirroring
#: `additional_cost`'s own `parse_activation_cost` reuse).
ALLOWED_ALT_COST_KEYS: frozenset[str] = frozenset(
    {
        "pay_life", "return_to_hand", "exile_hand_card_color", "condition",
        # MEC-12's remaining "pitch" shapes: a genuinely different fixed
        # mana cost (the Bringer cycle's "{W}{U}{B}{R}{G}"), a bare
        # sacrifice type word (Downhill Charge's "a Mountain" — reuses
        # `additional_cost`'s own vocabulary rather than duplicating it),
        # a qualifier-filtered sacrifice (Flare of Denial's "a nontoken
        # blue creature" — `combat.matches_object_filter`-shaped),
        # a counted sacrifice (`ActivationCost.sacrifice_count`'s own
        # ``(count, subtype)`` shape), a counted return-to-hand
        # (Gush's "return two Islands"), and Angelic Favor's "tap an
        # untapped creature you control" (`ActivationCost.tap_others`'s own
        # ``(count, subtype)`` shape, reused the same way).
        "mana", "sacrifice", "sacrifice_count", "sacrifice_filter", "return_to_hand_count",
        "tap_others",
        # PAR-19's own wider tail: the counted sibling of
        # ``exile_hand_card_color`` (Soul Spike/Sunscour/Allosaurus Rider's
        # "exile 2 `<color>` cards…") and the discard-zone "Pitch" basic-
        # land cycle (Abolish/Flameshot/Outbreak/Snag's "discard a
        # `<land type>` card…") — see `game/costs.py`'s `ActivationCost.
        # exile_hand_card_color_count`/``discard_land_type``.
        "exile_hand_card_color_count", "discard_land_type",
        # PAR-19: "Spend only mana produced by Treasures to cast it this
        # way." (Security Rhox) — scopes the ``mana`` key above to one
        # `game/mana_abilities.MANA_SOURCE_KINDS` bucket. Not itself a
        # payment component (it modifies ``mana``, the same way
        # ``condition`` modifies the whole cost rather than paying
        # anything on its own) — excluded from the "at least one real
        # payment component" check below.
        "mana_source_kind",
    }
)

#: RULE 605.3a's ``ManaPool.pool_by_source`` bucket vocabulary (PAR-19) —
#: shared by `AbilitySpec.alt_cost`'s ``mana_source_kind`` key and
#: `AbilitySpec.cast_mana_source_restriction` below, so both validate
#: against the same closed set `game/mana_abilities.MANA_SOURCE_KINDS`
#: defines (not imported directly — `parser/oracle/**` must have no
#: `game/` imports, the front-end security boundary).
MANA_SOURCE_KINDS: frozenset[str] = frozenset({"treasure", "basic_land", "creature"})

#: RULE 601.2b/604.3 "as an additional cost to cast this spell, <cost>." —
#: the closed vocabulary an `AbilitySpec.additional_cost` may name. Kept this
#: small (rather than reusing the free-text `ActivationCost` parser) because
#: an additional cost is recognized off a fixed template, not open cost text;
#: `game/costs.py`'s `parse_activation_cost` still does the actual charging,
#: fed this dict the same way it already accepts an `AbilitySpec.cost` dict.
_ADDITIONAL_COST_SACRIFICE_TYPES: frozenset[str] = frozenset(
    {
        "creature", "artifact", "land", "artifact_or_creature",
        # "…sacrifice a green creature." (Natural Order, MEC-43) — the
        # same ``"<color>_creature"`` sentinel `_matches_sacrifice_type`
        # (`game/engine/activation_mixin.py`) already recognizes.
        "white_creature", "blue_creature", "black_creature", "red_creature", "green_creature",
    }
)


class SpecValidationError(ValueError):
    """An `AbilitySpec` was structurally invalid (fail-closed)."""


@dataclass(frozen=True)
class ParserProvenance:
    """Where a spec came from — for audit and cache invalidation (docs/09).

    Present from day one so the (future) LLM tier and human review drop in
    without a data migration. ``source`` is ``"rule:<id>"`` for a catalogue
    handler, ``"llm"`` for the model tier, or ``"manual"`` for a
    hand-authored spec (as in the Phase 0 fixtures).
    """

    version: str = "0"
    source: str = "manual"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "source": self.source, "confidence": self.confidence}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParserProvenance":
        return cls(
            version=str(data.get("version", "0")),
            source=str(data.get("source", "manual")),
            confidence=float(data.get("confidence", 1.0)),
        )


@dataclass
class EffectSpec:
    """One whitelisted effect named by ``type`` + a ``params`` dict.

    ``type``/``params`` match `EffectRegistry.create(type, params)` exactly,
    so binding is a direct lookup (e.g. ``EffectSpec("damage", {"amount": 3})``).

    ``condition`` (parallel to `AbilitySpec.modes`) gates whether this
    *specific* effect fires at resolve time, checked against runtime state
    the binder wraps in a `game.effects.ConditionalEffect` — today just
    RULE 702.33b's "if this spell was kicked, <effect>." (``{"kicked":
    True}``, checked against ``obj.kicker_count``). A whitelisted shape
    (`_ALLOWED_CONDITION_KEYS`), not an arbitrary predicate — it can only
    gate whether an already-whitelisted effect applies, never choose *which*
    effect runs, so it doesn't widen the security boundary docs/09 sets out.

    A magnitude param (``"amount"``/``"count"``) may also be the literal
    string ``"x"`` instead of an int — the same "tie this to the spell/
    ability's own announced {X}" idiom `additional_cost`'s ``pay_life: "x"``
    uses (RULE 601.2b/107.3c). ``_clamp_params`` only touches ``int``
    values, so the sentinel string passes validation untouched;
    `RulesEngine.resolve_top_of_stack`'s ``_substitute_x`` swaps it for
    `StackItem.x` immediately before the effect applies.
    """

    type: str
    params: dict[str, Any] = field(default_factory=dict)
    condition: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type, "params": dict(self.params)}
        if self.condition is not None:
            d["condition"] = dict(self.condition)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EffectSpec":
        condition = data.get("condition")
        return cls(
            type=str(data["type"]),
            params=dict(data.get("params") or {}),
            condition=dict(condition) if condition else None,
        )


@dataclass
class AbilitySpec:
    """A single ability parsed off a card, as pure data (docs/09 IR)."""

    ability_kind: str
    effects: list[EffectSpec] = field(default_factory=list)
    #: Triggered abilities: ``{"event": EventType, "condition": {...}?}``.
    trigger: Optional[dict[str, Any]] = None
    #: Activated abilities: ``{"mana": "{2}{R}", "taps_self": bool, ...}``.
    cost: Optional[dict[str, Any]] = None
    #: What the ability may target, e.g. ``{"kind": "any", "count": 1}``.
    target: Optional[dict[str, Any]] = None
    #: Keyword abilities: the parsed identity + any single parameter, e.g.
    #: ``{"name": "flying"}``, ``{"name": "annihilator", "n": 2}``,
    #: ``{"name": "kicker", "cost": "{2}{R}"}``, ``{"name": "protection",
    #: "quality": "red"}`` (docs/09 "Keyword abilities: the privileged
    #: fast-path handler class"). ``name`` is a catalogue slug (RULE 702.x).
    keyword: Optional[dict[str, Any]] = None
    #: A modal "Choose one —" block (RULE 700.2), ``spell_effect`` or
    #: ``triggered``: ``{"or_both": bool, "at_least": bool, "choose": int,
    #: "options": [[EffectSpec, ...], ...], "descriptions": [str, ...]}`` —
    #: one entry per printed mode, in printed order. ``or_both`` is RULE
    #: 700.2e ("Choose one or both —"): the engine also offers casting/
    #: resolving both modes together. ``choose`` is RULE 700.2's "choose
    #: *N* —" header (``N>=2`` — "Choose two —"/"Choose three —"; ``1`` for
    #: the ordinary "choose one" case, the default when the key is absent so
    #: old specs keep working). ``at_least`` is "Choose *N* or more —" (a
    #: *variable* count, Farewell-shaped): ``choose`` becomes a minimum
    #: rather than an exact count, and any number of modes up to every mode
    #: may be chosen — mutually exclusive with ``or_both`` (Scryfall never
    #: prints both suffixes on one header). When set, the ability carries no
    #: top-level ``effects`` of its own — each mode's effects only apply
    #: once chosen. A ``spell_effect`` offers one cast action per *legal
    #: combination* of ``choose`` modes (`game/game_engine.py`, like an
    #: MDFC's two faces — `itertools.combinations` for ``choose > 1``, every
    #: size from ``choose`` to all modes when ``at_least``); a ``triggered``
    #: ability's mode(s) are instead chosen as it's put on the stack (RULE
    #: 603.3), via an iterative `trigger_mode` interactive choice
    #: (`game/rules_engine.py`'s `_place_triggers`/`resolve_trigger_mode_
    #: choice` — one mode picked per round, already-picked ones excluded
    #: from the next offer, mirroring the existing library-search
    #: `_search_choice`/`resolve_search_choice` "pick up to N one at a time"
    #: pattern, plus a "done" option once ``choose`` are picked when
    #: ``at_least``) — the same "choice made before the target/optional
    #: choice" ordering RULE 601.2c already uses for a spell's own mode.
    #: ``entwine`` (RULE 702.42, ``spell_effect`` only) is the mana-cost
    #: string of an Entwine additional cost: paying it upgrades the header
    #: from "choose one" to "choose *all*", so the engine offers a second,
    #: separately-priced cast action alongside the per-mode ones. Unlike
    #: ``or_both`` — which hands both modes over for free — the combined
    #: offer is locked when the entwine cost isn't affordable.
    modes: Optional[dict[str, Any]] = None
    #: RULE 601.2b/604.3: a spell's "as an additional cost to cast this
    #: spell, <cost>." clause — ``spell_effect`` only, a single-key dict from
    #: a small closed vocabulary: ``{"sacrifice": "creature"|"artifact"|
    #: "land"}``, ``{"discard": <count>}``, or ``{"pay_life": <N>|"x"}`` (the
    #: literal string ``"x"`` ties the payment to the spell's own announced
    #: X, RULE 601.2b). May ride on a spec that otherwise carries no effects
    #: at all — the additional-cost line is its own oracle-text line,
    #: standalone from the spell's actual effect (see
    #: `game/effect_binder.py`'s `attach_to_object`, which scans every spec
    #: for this field regardless of which one carries the "real" effects).
    additional_cost: Optional[dict[str, Any]] = None
    #: PAR-30 / RULE 601.2b: whether the ``additional_cost`` above is
    #: *optional* — "as an additional cost to cast this spell, **you may**
    #: waterbend {N}." (Katara Seeking Revenge, Ruinous Waterbending, …).
    #: An optional additional cost is offered as its own cast variant and,
    #: when paid, sets `GameObject.additional_cost_paid` for a following
    #: ``{"additional_cost_paid": …}`` `EffectSpec.condition`. Mandatory
    #: (the default, ``False``) folds in unconditionally as before.
    additional_cost_optional: bool = False
    #: RULE 702.8b/606.3: "you may cast this spell as though it had flash if
    #: <condition>" / "you may activate this permanent's loyalty abilities
    #: any time you could cast an instant if <condition>" (The Wandering
    #: Emperor-shaped) — a single-key dict from `ALLOWED_CAST_CONDITION_KEYS`
    #: (``{"entered_this_turn": True}``, RULE 606.3's "as long as ~ entered
    #: the battlefield this turn", or ``{"targets_a_commander": True}``,
    #: Timely Ward-shaped MEC-7 — the one key checked against the caster's
    #: actual chosen targets rather than purely off the object/state, see
    #: `condition_query.conditional_flash_holds`). A deliberately separate
    #: whitelist from `EffectSpec.condition`'s (see that constant's
    #: docstring) — this one gates *cast/activation timing*
    #: (`game/condition_query.py`, checked live off the object each time),
    #: not whether a resolving effect applies. May ride on any spec
    #: regardless of ``ability_kind``, same "scan every spec, attach to the
    #: object regardless of which one carries the real effects" idiom
    #: `additional_cost` uses (`game/effect_binder.py`'s `attach_to_object`).
    conditional_flash: Optional[dict[str, Any]] = None
    #: RULE 601.2f-adjacent: "If you control a commander, you may cast this
    #: spell without paying its mana cost." — a single-key dict from
    #: `ALLOWED_FREE_CAST_CONDITION_KEYS` (today just ``{"control_commander":
    #: True}``). Checked live off the game state at cast time
    #: (`game/condition_query.py`'s `free_cast_condition_holds`), mirroring
    #: `conditional_flash`'s "may ride on any spec regardless of
    #: ``ability_kind``" idiom — the clause is its own oracle-text line,
    #: standalone from the spell's actual effect.
    free_cast_condition: Optional[dict[str, Any]] = None
    #: RULE 118.9: "You may pay `<cost>` rather than pay this spell's mana
    #: cost." (Force of Will/Negation/Vigor, Daze — MEC-15) — see
    #: `ALLOWED_ALT_COST_KEYS`'s own docstring for the vocabulary. Hand-
    #: authored only (`game/ability_catalogue.py`); no oracle-text grammar
    #: recognizes this shape yet — real cards phrase the payment too
    #: variably for one fixed template. Same "may ride on any spec
    #: regardless of ``ability_kind``, own oracle-text line standalone from
    #: the spell's actual effect" idiom `free_cast_condition` uses.
    alt_cost: Optional[dict[str, Any]] = None
    #: PAR-19: "Spend only mana produced by basic lands/creatures to cast
    #: this spell." (Imperiosaur/Myr Superion) — a standing restriction on
    #: the spell's own *printed* mana cost (unlike `alt_cost`'s own
    #: ``mana_source_kind``, which scopes an *alternative* cost instead — no
    #: real card needs both). One of `MANA_SOURCE_KINDS`. Bound onto the
    #: object as a plain attribute (`effect_binder.attach_to_object` →
    #: `GameObject.mana_source_kind_restriction`, the same "dynamic,
    #: getattr-read" convention `alt_cast_cost`/`alt_cast_condition`
    #: already use), consulted by `RulesEngine.cast_spell`/`GameEngine.
    #: can_cast`'s ordinary mana-payment branch.
    cast_mana_source_restriction: Optional[str] = None
    #: "Spend only `<color>` mana on X." (Drain Life, MEC-43) — a WUBRG
    #: letter naming which color the spell's own printed ``{X}`` (not its
    #: other pips) must be paid with; ``None`` for an ordinary spell.
    #: Distinct from `cast_mana_source_restriction` above (that one scopes
    #: the whole cost by mana *source*, this one scopes only the ``{X}``
    #: portion by *color*) — no real card needs both. Bound the same
    #: "dynamic, getattr-read" way (`GameObject.x_spend_color_restriction`),
    #: consulted by `GameEngine.effective_cast_cost`'s ``{X}``-resolution
    #: branch (`models.mana_cost.ManaCost.with_x_colored`).
    cast_x_color_restriction: Optional[str] = None
    #: "Strive — This spell costs `<cost>` more to cast for each target
    #: beyond the first." (MEC-4) — not a RULE 702 keyword at all (no CR
    #: entry defines it; Scryfall's `keywords` array is the only place it's
    #: named), so it rides as its own field rather than going through
    #: `keywords.py`'s numbered catalogue, same "own oracle-text line,
    #: standalone from the spell's actual effect" idiom `free_cast_condition`
    #: uses just above. The raw mana-cost string (e.g. ``"{2}{U}"``,
    #: ``"{1}"``) — `game/effect_binder.py`'s `attach_to_object` parses it
    #: into a real `ManaCost` on `obj.strive_cost`; `GameEngine.
    #: effective_cast_cost` adds one copy of it per target *beyond the
    #: first* in the caster's actually-chosen ``targets`` (RULE 601.2c
    #: precedes 601.2f — the total cost is calculated only after targets are
    #: already chosen, unlike `conditional_flash`'s pre-cast timing check).
    strive_cost: Optional[str] = None
    #: RULE 603.4-style per-firing marker: "whenever ~ deals combat damage
    #: to a player, exile the top card of *that player's* library. Until
    #: end of turn, you may cast that card." (Ragavan, Nimble Pilferer) —
    #: the damaged player varies per firing, which a bind-on-load
    #: `TriggeredAbility`'s one fixed effects list can't carry (see that
    #: class's docstring, `game/effects.py`), so this rides as a plain
    #: marker dict (``{"count": N}``, ``N>=1``) stamped onto the
    #: `GameObject` at bind time instead of an ordinary effect —
    #: `RulesEngine._collect_impulsive_draw_triggers` reads it fresh off
    #: the event's own source every time a DAMAGE event fires, building the
    #: per-firing `ImpulsiveDrawEffect` the same way `_collect_inherent_
    #: triggers` already does for the Monarch/Initiative combat-damage
    #: swap. Hand-authored only (`game/ability_catalogue.py`) — the
    #: oracle-text parser front-end never produces this field. May ride on
    #: any spec regardless of ``ability_kind``, same "scan every spec,
    #: attach to the object" idiom `additional_cost`/`conditional_flash` use
    #: (`game/effect_binder.py`'s `attach_to_object`).
    impulsive_draw_on_combat_damage: Optional[dict[str, Any]] = None
    #: RULE 702.88b Rebound marker: "If you cast this spell from your hand,
    #: exile it as it resolves. At the beginning of your next upkeep, you
    #: may cast this card from exile without paying its mana cost."
    #: (Ephemerate) — hand-authored only, no effects of its own, same "scan
    #: every spec, attach to the object" idiom as `impulsive_draw_on_combat_
    #: damage`. Read by `RulesEngine.cast_spell` (arms ``obj.rebound_
    #: pending`` when cast from hand) and `resolve_top_of_stack` (exiles
    #: instead of routing to the graveyard, then arms the free-cast window
    #: via `GameState.free_cast_instance_ids` — a *standing* until-end-of-
    #: that-upkeep's-turn permission rather than a forced yes/no choice at
    #: the delayed trigger's own resolution, the same simplification
    #: `exile_with_play_permission`'s impulsive-draw window already uses).
    rebound: bool = False
    #: RULE 614.12: "If ~ would enter, you may discard a land card instead.
    #: If you do, put ~ onto the battlefield. If you don't, put it into its
    #: owner's graveyard." (Mox Diamond) — hand-authored only (confirmed a
    #: singleton template cache-wide), same "scan every spec, attach a bare
    #: flag to the object" idiom as `rebound`. Read by `RulesEngine.
    #: _resolve_permanent_spell`/`_offer_enter_or_graveyard`, which offer
    #: this choice *before* every other battlefield-entry step — declining
    #: (or having no land to discard) means the object never becomes a
    #: permanent at all.
    enter_or_graveyard_discard_land: bool = False
    #: RULE 603.7-style per-firing marker: "whenever a creature you control
    #: with a counter of ``counter_kind`` on it dies, return that card to
    #: the battlefield under your control at the beginning of the next end
    #: step." (Marchesa, the Black Rose) — the dying creature varies per
    #: firing, so this rides as a marker (mirroring `impulsive_draw_on_
    #: combat_damage`'s own per-firing shape) rather than a bind-once
    #: `TriggeredAbility`; `RulesEngine._collect_counter_death_return_
    #: triggers` reads it fresh off every `DIES` event, checking the dying
    #: object's counters (snapshotted onto the event by `_move_to_graveyard`
    #: since the object may already be gone from the battlefield by the
    #: time this runs). Hand-authored only. ``{"counter_kind": "+1/+1"}``
    #: (default) — a single optional key, no other counter kind needed yet.
    counter_death_return: Optional[dict[str, Any]] = None
    #: RULE 728's own "whenever ~ deals combat damage to a player, they get
    #: N rad counters" (Glowing One)/"...that many rad counters" (Infesting
    #: Radroach) — the damaged player varies per firing, same per-firing
    #: marker shape as `impulsive_draw_on_combat_damage`.
    #: ``{"count": <int>}`` for a flat amount, or ``{"count":
    #: "damage_amount"}`` for "that many" (the damage just dealt).
    #: ``{"else": "proliferate"}`` (Vexing Radgull: "...if they don't have
    #: any rad counters. Otherwise, proliferate.") branches to a
    #: `ProliferateEffect` instead whenever the damaged player already has
    #: >=1 of the granted ``kind``. ``{"kind": "rad"}`` (default) names
    #: which counter kind — every real card in this family grants "rad",
    #: kept as a key rather than hardcoded since the shape is otherwise
    #: generic. Hand-authored only (`game/ability_catalogue.py`) — the
    #: oracle-text parser front-end has no "that many"/branching grammar
    #: yet. `RulesEngine._collect_rad_counter_damage_triggers` reads it
    #: fresh off the DAMAGE event's own source, mirroring `_collect_
    #: impulsive_draw_triggers`.
    rad_counters_on_combat_damage: Optional[dict[str, Any]] = None
    #: RULE 506.4/728's "whenever a player attacks you with one or more
    #: creatures, that player gets twice that many rad counters" (Struggle
    #: for Project Purity's Enclave mode) — the attacking player *and* the
    #: amount (tied to `EventType.PLAYER_ATTACKED`'s own ``count``) vary per
    #: firing, same per-firing marker shape as `rad_counters_on_combat_
    #: damage`. ``{"multiplier": <int>}`` (default 1) scales the granted
    #: amount; ``{"requires_mode": <str>}`` additionally gates this marker
    #: to only apply while `GameObject.chosen_mode` matches (Struggle for
    #: Project Purity's own named-mode choice — see `AbilitySpec.trigger`'s
    #: ``"named_mode"`` key for the ordinary-ability equivalent this marker
    #: mechanism can't use, since it isn't a bind-once `TriggeredAbility` at
    #: all). Hand-authored only. `RulesEngine._collect_attacks_you_rad_
    #: counter_triggers` reads it fresh off every permanent on `PLAYER_
    #: ATTACKED`, mirroring `_collect_counter_death_return_triggers`'s
    #: "scan every permanent" style (the source isn't the event's own
    #: subject here either).
    rad_counters_on_attacked: Optional[dict[str, Any]] = None
    #: RULE 112.6a: "Whenever an opponent mills a nonland card, if this
    #: creature is in your graveyard, you may return it to your hand."
    #: (Infesting Radroach) — the one triggered ability in this catalogue
    #: that must still fire while its own source sits in a *graveyard*,
    #: not the battlefield, so it can't ride the ordinary `obj.
    #: triggered_abilities` scan (`RulesEngine._collect_triggers` only
    #: walks `state.permanents()`). Rides as a bind-once marker instead
    #: (mirroring `counter_death_return`'s own per-firing-scan shape),
    #: read fresh off every player's graveyard by `RulesEngine._collect_
    #: mill_return_from_graveyard_triggers`. A plain flag, not a dict —
    #: unlike its rad-counter siblings, this ability's shape ("opponent
    #: mills a nonland card" → "you may return this to hand") has no
    #: card-varying parameter, the same reasoning `rebound` is a bare
    #: bool. Hand-authored only.
    mill_return_from_graveyard: bool = False
    optional: bool = False  # "you may"
    raw_text: str = ""
    parser: ParserProvenance = field(default_factory=ParserProvenance)

    def validate(self) -> "AbilitySpec":
        """Structurally validate and normalize (clamp) in place; return self.

        Raises `SpecValidationError` on any structural problem (fail-closed).
        Does **not** check whether an effect *type* is registered — that is
        the binder's job, since it needs the `EffectRegistry`.
        """
        if self.ability_kind not in ALLOWED_ABILITY_KINDS:
            raise SpecValidationError(
                f"unknown ability_kind {self.ability_kind!r} "
                f"(expected one of {sorted(ALLOWED_ABILITY_KINDS)})"
            )

        for effect in self.effects:
            if not isinstance(effect, EffectSpec) or not effect.type:
                raise SpecValidationError(f"malformed effect spec: {effect!r}")
            self._clamp_params(effect.params)
            if effect.condition is not None:
                self._validate_condition(effect.condition)

        if (
            self.ability_kind in _EFFECT_BEARING_KINDS
            and not self.effects
            and not self.modes
            and not self.additional_cost
            and not self.free_cast_condition
            and not self.alt_cost
            and not self.conditional_flash
            and not self.strive_cost
            and not self.cast_mana_source_restriction
            and not self.cast_x_color_restriction
        ):
            raise SpecValidationError(
                f"{self.ability_kind!r} ability must carry at least one effect"
            )

        if self.modes is not None:
            self._validate_modes()

        if self.additional_cost is not None:
            self._validate_additional_cost()

        if self.conditional_flash is not None:
            self._validate_conditional_flash()

        if self.free_cast_condition is not None:
            self._validate_free_cast_condition()

        if self.alt_cost is not None:
            self._validate_alt_cost()

        if self.cast_mana_source_restriction is not None:
            if self.cast_mana_source_restriction not in MANA_SOURCE_KINDS:
                raise SpecValidationError(
                    f"'cast_mana_source_restriction' must be one of {sorted(MANA_SOURCE_KINDS)}, "
                    f"got {self.cast_mana_source_restriction!r}"
                )

        if self.cast_x_color_restriction is not None:
            if self.cast_x_color_restriction not in ("W", "U", "B", "R", "G"):
                raise SpecValidationError(
                    f"'cast_x_color_restriction' must be a WUBRG letter, "
                    f"got {self.cast_x_color_restriction!r}"
                )

        if self.strive_cost is not None:
            self._validate_strive_cost()

        if self.impulsive_draw_on_combat_damage is not None:
            self._validate_impulsive_draw_on_combat_damage()

        if not isinstance(self.rebound, bool):
            raise SpecValidationError("'rebound' must be a bool")

        if not isinstance(self.enter_or_graveyard_discard_land, bool):
            raise SpecValidationError("'enter_or_graveyard_discard_land' must be a bool")

        if self.counter_death_return is not None:
            self._validate_counter_death_return()

        if self.rad_counters_on_combat_damage is not None:
            self._validate_rad_counters_on_combat_damage()

        if self.rad_counters_on_attacked is not None:
            self._validate_rad_counters_on_attacked()

        if not isinstance(self.mill_return_from_graveyard, bool):
            raise SpecValidationError("'mill_return_from_graveyard' must be a bool")

        if self.ability_kind == "triggered":
            if not self.trigger or "event" not in self.trigger:
                raise SpecValidationError("triggered ability needs a trigger with an 'event'")

        if self.keyword is not None:
            if not isinstance(self.keyword, dict) or not self.keyword.get("name"):
                raise SpecValidationError("keyword spec needs a non-empty 'name'")
            self._clamp_params(self.keyword)  # clamp an integer "n" the same way

        return self

    def _validate_modes(self) -> None:
        """Structural check for a modal ``modes`` block (RULE 700.2).

        ``"activated"`` (MEC-43, Umezawa's Jitte's "Remove a charge
        counter: Choose one — …") is the activated-ability sibling of the
        already-supported spell/triggered kinds — `effect_binder.
        bind_ability`'s activated branch only wires the plain "choose one"
        shape (``modes_choose == 1``, no "or both"/"choose N or more"), but
        the *structural* validation here doesn't need to know that; an
        activated `AbilitySpec` asking for a wider shape than the binder
        supports fails loudly there instead of silently here.
        """
        if self.ability_kind not in ("spell_effect", "triggered", "activated"):
            raise SpecValidationError(
                "'modes' is only supported on spell_effect/triggered/activated abilities"
            )
        if not isinstance(self.modes, dict):
            raise SpecValidationError("'modes' must be a dict")
        options = self.modes.get("options")
        if not isinstance(options, list) or len(options) < 2:
            raise SpecValidationError("'modes' needs at least two options")
        for option in options:
            if not isinstance(option, list) or not option:
                raise SpecValidationError("each mode needs at least one effect")
            for effect in option:
                if not isinstance(effect, EffectSpec) or not effect.type:
                    raise SpecValidationError(f"malformed effect spec in mode: {effect!r}")
                self._clamp_params(effect.params)
        descriptions = self.modes.get("descriptions")
        if descriptions is not None and (
            not isinstance(descriptions, list) or len(descriptions) != len(options)
        ):
            raise SpecValidationError("'modes' descriptions must match its options 1:1")
        choose = self.modes.get("choose", 1)
        if isinstance(choose, bool) or not isinstance(choose, int) or not 1 <= choose <= len(options):
            raise SpecValidationError(
                f"'modes' choose count must be an int in [1, {len(options)}]"
            )
        if self.modes.get("or_both") and self.modes.get("at_least"):
            raise SpecValidationError("'modes' or_both and at_least are mutually exclusive")
        if self.modes.get("optional") and (
            self.modes.get("or_both") or self.modes.get("at_least") or choose != 1
        ):
            raise SpecValidationError(
                "'modes' optional (RULE 700.2's 'choose up to one') requires a plain choose-one block"
            )
        entwine = self.modes.get("entwine")
        if entwine is not None:
            # RULE 702.42a: Entwine is an *additional* cost that upgrades the
            # header from "choose one" to "choose all" — so it only makes
            # sense on a plain "Choose one —" block, never alongside the
            # free-of-charge `or_both` (RULE 700.2e) or a variable
            # `at_least` count.
            if not isinstance(entwine, str) or not entwine.strip():
                raise SpecValidationError("'modes' entwine must be a mana-cost string")
            if self.modes.get("or_both") or self.modes.get("at_least") or choose != 1:
                raise SpecValidationError(
                    "'modes' entwine requires a plain 'choose one' block"
                )
        mode_costs = self.modes.get("mode_costs")
        if mode_costs is not None:
            # RULE 702.172a Spree: unlike Entwine (one shared upgrade cost),
            # every mode carries its *own* additional cost — so this is only
            # meaningful on the "choose one or more" shape (`at_least`, not
            # `or_both`/a fixed `choose`), one entry per option.
            if not isinstance(mode_costs, list) or len(mode_costs) != len(options):
                raise SpecValidationError("'modes' mode_costs must match its options 1:1")
            for cost in mode_costs:
                if not isinstance(cost, str) or not cost.strip():
                    raise SpecValidationError("'modes' mode_costs entries must be mana-cost strings")
            if not self.modes.get("at_least") or choose != 1:
                raise SpecValidationError(
                    "'modes' mode_costs (Spree) requires a 'choose one or more' block"
                )

    def _validate_additional_cost(self) -> None:
        """Structural check for an ``additional_cost`` clause (RULE 601.2b/604.3)."""
        if self.ability_kind != "spell_effect":
            raise SpecValidationError(
                "'additional_cost' is only supported on spell_effect abilities"
            )
        cost = self.additional_cost
        if not isinstance(cost, dict) or len(cost) != 1:
            raise SpecValidationError("'additional_cost' must be a single-key dict")
        key, value = next(iter(cost.items()))
        if key == "sacrifice":
            if value not in _ADDITIONAL_COST_SACRIFICE_TYPES:
                raise SpecValidationError(
                    f"unsupported additional_cost sacrifice type {value!r}"
                )
        elif key == "discard":
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SpecValidationError("'additional_cost' discard count must be a positive int")
        elif key == "pay_life":
            valid_int = isinstance(value, int) and not isinstance(value, bool) and value > 0
            if value != "x" and not valid_int:
                raise SpecValidationError(
                    "'additional_cost' pay_life must be a positive int or 'x'"
                )
        elif key == "exile_from_graveyard":
            # RULE 601.2b (PAR-41): "exile N [<type>] cards from your
            # graveyard." — value is ``{"count": <positive int>, "type":
            # <word>?}``.
            if not isinstance(value, dict):
                raise SpecValidationError(
                    "'additional_cost' exile_from_graveyard must be a {count, type?} dict"
                )
            cnt = value.get("count")
            if isinstance(cnt, bool) or not isinstance(cnt, int) or cnt <= 0:
                raise SpecValidationError(
                    "'additional_cost' exile_from_graveyard count must be a positive int"
                )
            gy_type = value.get("type")
            if gy_type is not None and (not isinstance(gy_type, str) or not gy_type.strip()):
                raise SpecValidationError(
                    "'additional_cost' exile_from_graveyard type must be a non-empty word"
                )
        elif key == "behold":
            # RULE 701.4a (PAR-29): "behold a `<type>` or pay {N}." — the
            # value is the type word to reveal. The "or pay {N}" alternative
            # is a documented simplification, not represented here (same as
            # `_ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE`).
            if not isinstance(value, str) or not value.strip():
                raise SpecValidationError("'additional_cost' behold must be a non-empty type word")
        elif key == "behold_exile":
            # RULE 701.4a (PAR-30 — the Lorwyn "Champion" cycle reflavoured):
            # "behold a `<type>` and exile it." — a *mandatory* additional
            # cost (no "or pay {N}" alternative), value is the type word.
            # The exiled card is returned by the card's own
            # `LEAVES_BATTLEFIELD` `return_linked_exile` trigger.
            if not isinstance(value, str) or not value.strip():
                raise SpecValidationError(
                    "'additional_cost' behold_exile must be a non-empty type word"
                )
        elif key == "behold_two_shared_type":
            # RULE 701.4a (PAR-30 — Celestial Reunion): "you may choose a
            # creature type and behold two creatures of that type." A bool;
            # always the optional (`additional_cost_optional`) shape.
            if value is not True:
                raise SpecValidationError(
                    "'additional_cost' behold_two_shared_type must be True"
                )
        elif key == "blight":
            # RULE 701.68 (PAR-29): "blight N or pay {M}." — N -1/-1 counters
            # on a creature you control. Same "or pay {M}" documented
            # simplification as `behold`.
            valid = isinstance(value, int) and not isinstance(value, bool) and value > 0
            if not valid:
                raise SpecValidationError("'additional_cost' blight must be a positive int")
        elif key == "waterbend":
            # ENG-32 (RULE 701.67): "as an additional cost to cast this
            # spell, waterbend {N}." — a {N} generic mana cost paid inside
            # the additional cost. The Convoke-style helper ("tap your
            # artifacts and creatures to help") is a documented
            # simplification, dropped. ``"x"`` for "waterbend {X}".
            valid_int = isinstance(value, int) and not isinstance(value, bool) and value > 0
            if value != "x" and not valid_int:
                raise SpecValidationError("'additional_cost' waterbend must be a positive int or 'x'")
        elif key == "forage":
            # RULE 701.61 (PAR-29): "forage [or pay {M}]." — same "or pay
            # {M}" documented drop as `behold`/`blight`. A bare bool.
            if value is not True:
                raise SpecValidationError("'additional_cost' forage must be True")
        else:
            raise SpecValidationError(f"unknown additional_cost kind {key!r}")

    def _validate_conditional_flash(self) -> None:
        """Structural check for a ``conditional_flash`` clause."""
        cond = self.conditional_flash
        if not isinstance(cond, dict) or len(cond) != 1:
            raise SpecValidationError("'conditional_flash' must be a single-key dict")
        key, value = next(iter(cond.items()))
        if key not in ALLOWED_CAST_CONDITION_KEYS:
            raise SpecValidationError(f"unknown conditional_flash key {key!r}")
        if key == "entered_this_turn" and not isinstance(value, bool):
            raise SpecValidationError("'entered_this_turn' condition must be a bool")
        if key == "targets_a_commander" and not isinstance(value, bool):
            raise SpecValidationError("'targets_a_commander' condition must be a bool")
        if key == "unconditional" and not isinstance(value, bool):
            raise SpecValidationError("'unconditional' condition must be a bool")
        if key == "controller_beholds_subtype" and (
            not isinstance(value, str) or not value.strip()
        ):
            raise SpecValidationError(
                "'controller_beholds_subtype' condition must be a non-empty string"
            )

    def _validate_impulsive_draw_on_combat_damage(self) -> None:
        """Structural check for an ``impulsive_draw_on_combat_damage`` marker."""
        spec = self.impulsive_draw_on_combat_damage
        if not isinstance(spec, dict):
            raise SpecValidationError("'impulsive_draw_on_combat_damage' must be a dict")
        count = spec.get("count", 1)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_EFFECT_MAGNITUDE:
            raise SpecValidationError(
                "'impulsive_draw_on_combat_damage' count must be an int in "
                f"[1, {MAX_EFFECT_MAGNITUDE}]"
            )

    def _validate_rad_counters_on_combat_damage(self) -> None:
        """Structural check for a ``rad_counters_on_combat_damage`` marker."""
        spec = self.rad_counters_on_combat_damage
        if not isinstance(spec, dict):
            raise SpecValidationError("'rad_counters_on_combat_damage' must be a dict")
        count = spec.get("count", 1)
        if count != "damage_amount":
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_EFFECT_MAGNITUDE:
                raise SpecValidationError(
                    "'rad_counters_on_combat_damage' count must be an int in "
                    f"[1, {MAX_EFFECT_MAGNITUDE}] or the literal string 'damage_amount'"
                )
        else_branch = spec.get("else")
        if else_branch is not None and else_branch != "proliferate":
            raise SpecValidationError(
                "'rad_counters_on_combat_damage' else must be the literal string 'proliferate'"
            )
        kind = spec.get("kind", "rad")
        if not isinstance(kind, str) or not kind:
            raise SpecValidationError("'rad_counters_on_combat_damage' kind must be a non-empty str")

    def _validate_rad_counters_on_attacked(self) -> None:
        """Structural check for a ``rad_counters_on_attacked`` marker."""
        spec = self.rad_counters_on_attacked
        if not isinstance(spec, dict):
            raise SpecValidationError("'rad_counters_on_attacked' must be a dict")
        multiplier = spec.get("multiplier", 1)
        if (
            isinstance(multiplier, bool)
            or not isinstance(multiplier, int)
            or not 1 <= multiplier <= MAX_EFFECT_MAGNITUDE
        ):
            raise SpecValidationError(
                f"'rad_counters_on_attacked' multiplier must be an int in [1, {MAX_EFFECT_MAGNITUDE}]"
            )
        requires_mode = spec.get("requires_mode")
        if requires_mode is not None and (not isinstance(requires_mode, str) or not requires_mode):
            raise SpecValidationError("'rad_counters_on_attacked' requires_mode must be a non-empty str")

    def _validate_counter_death_return(self) -> None:
        """Structural check for a ``counter_death_return`` marker."""
        spec = self.counter_death_return
        if not isinstance(spec, dict):
            raise SpecValidationError("'counter_death_return' must be a dict")
        kind = spec.get("counter_kind", "+1/+1")
        if not isinstance(kind, str) or not kind:
            raise SpecValidationError("'counter_death_return' counter_kind must be a non-empty str")

    def _validate_strive_cost(self) -> None:
        """Structural check for a ``strive_cost`` clause: a non-empty run of
        brace-delimited mana/generic symbols (``"{2}{U}"``, ``"{1}"``) — the
        same shape `game/costs.py`/`ManaCost.parse` expect, checked here only
        for well-formedness (no `game/` import at this layer's boundary)."""
        cost = self.strive_cost
        if not isinstance(cost, str) or not _STRIVE_COST_RE.fullmatch(cost.strip()):
            raise SpecValidationError(f"'strive_cost' must be a run of mana symbols, got {cost!r}")

    def _validate_free_cast_condition(self) -> None:
        """Structural check for a ``free_cast_condition`` clause."""
        cond = self.free_cast_condition
        if not isinstance(cond, dict) or len(cond) != 1:
            raise SpecValidationError("'free_cast_condition' must be a single-key dict")
        key, value = next(iter(cond.items()))
        if key not in ALLOWED_FREE_CAST_CONDITION_KEYS:
            raise SpecValidationError(f"unknown free_cast_condition key {key!r}")
        if key == "control_commander" and not isinstance(value, bool):
            raise SpecValidationError("'control_commander' condition must be a bool")
        if key in (
            "not_your_turn", "your_turn", "opponent_controls_forest_and_you_control_island",
        ) and not isinstance(value, bool):
            raise SpecValidationError(f"{key!r} condition must be a bool")
        if key == "opponent_spells_cast_this_turn_at_least" and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1
        ):
            raise SpecValidationError(
                "'opponent_spells_cast_this_turn_at_least' condition must be a positive int"
            )
        if key == "control_land_type" and (not isinstance(value, str) or not value):
            raise SpecValidationError("'control_land_type' condition must be a non-empty str")

    def _validate_alt_cost(self) -> None:
        """Structural check for an ``alt_cost`` clause (RULE 118.9)."""
        cost = self.alt_cost
        if not isinstance(cost, dict) or not cost:
            raise SpecValidationError("'alt_cost' must be a non-empty dict")
        for key in cost:
            if key not in ALLOWED_ALT_COST_KEYS:
                raise SpecValidationError(f"unknown alt_cost key {key!r}")
        pay_life = cost.get("pay_life")
        if pay_life is not None and (isinstance(pay_life, bool) or not isinstance(pay_life, int) or pay_life < 1):
            raise SpecValidationError("'alt_cost' pay_life must be a positive int")
        return_to_hand = cost.get("return_to_hand")
        if return_to_hand is not None and (not isinstance(return_to_hand, str) or not return_to_hand):
            raise SpecValidationError("'alt_cost' return_to_hand must be a non-empty str")
        color = cost.get("exile_hand_card_color")
        if color is not None and color not in ("W", "U", "B", "R", "G"):
            raise SpecValidationError(f"'alt_cost' exile_hand_card_color must be a WUBRG letter, got {color!r}")
        mana = cost.get("mana")
        if mana is not None and (not isinstance(mana, str) or not mana):
            raise SpecValidationError("'alt_cost' mana must be a non-empty str")
        sacrifice = cost.get("sacrifice")
        if sacrifice is not None and (not isinstance(sacrifice, str) or not sacrifice):
            raise SpecValidationError("'alt_cost' sacrifice must be a non-empty str")
        for count_key in ("sacrifice_count", "return_to_hand_count", "tap_others"):
            pair = cost.get(count_key)
            if pair is not None:
                if (
                    not isinstance(pair, (list, tuple)) or len(pair) != 2
                    or isinstance(pair[0], bool) or not isinstance(pair[0], int) or pair[0] < 1
                    or not isinstance(pair[1], str) or not pair[1]
                ):
                    raise SpecValidationError(f"'alt_cost' {count_key} must be [positive int, non-empty str]")
        sac_filter = cost.get("sacrifice_filter")
        if sac_filter is not None and (not isinstance(sac_filter, dict) or not sac_filter):
            raise SpecValidationError("'alt_cost' sacrifice_filter must be a non-empty dict")
        exile_color_count = cost.get("exile_hand_card_color_count")
        if exile_color_count is not None:
            if (
                not isinstance(exile_color_count, (list, tuple)) or len(exile_color_count) != 2
                or isinstance(exile_color_count[0], bool) or not isinstance(exile_color_count[0], int)
                or exile_color_count[0] < 1
                or exile_color_count[1] not in ("W", "U", "B", "R", "G")
            ):
                raise SpecValidationError(
                    "'alt_cost' exile_hand_card_color_count must be [positive int, WUBRG letter]"
                )
        discard_land_type = cost.get("discard_land_type")
        if discard_land_type is not None and (not isinstance(discard_land_type, str) or not discard_land_type):
            raise SpecValidationError("'alt_cost' discard_land_type must be a non-empty str")
        mana_source_kind = cost.get("mana_source_kind")
        if mana_source_kind is not None:
            if mana_source_kind not in MANA_SOURCE_KINDS:
                raise SpecValidationError(
                    f"'alt_cost' mana_source_kind must be one of {sorted(MANA_SOURCE_KINDS)}, "
                    f"got {mana_source_kind!r}"
                )
            if "mana" not in cost:
                raise SpecValidationError("'alt_cost' mana_source_kind requires a 'mana' key to scope")
        if not any(
            k in cost for k in (
                "pay_life", "return_to_hand", "exile_hand_card_color", "mana", "sacrifice",
                "sacrifice_count", "sacrifice_filter", "return_to_hand_count", "tap_others",
                "exile_hand_card_color_count", "discard_land_type",
            )
        ):
            raise SpecValidationError("'alt_cost' must carry at least one real payment component")
        condition = cost.get("condition")
        if condition is not None:
            if not isinstance(condition, dict) or len(condition) != 1:
                raise SpecValidationError("'alt_cost' condition must be a single-key dict")
            ckey, cvalue = next(iter(condition.items()))
            if ckey not in ALLOWED_FREE_CAST_CONDITION_KEYS:
                raise SpecValidationError(f"unknown alt_cost condition key {ckey!r}")
            if ckey == "control_land_type":
                if not isinstance(cvalue, str) or not cvalue:
                    raise SpecValidationError("'control_land_type' alt_cost condition must be a non-empty str")
            elif ckey in ("opponent_spells_cast_this_turn_at_least", "creatures_attacking_at_least"):
                # PAR-19: an int-threshold condition, same shape
                # `_validate_free_cast_condition` already accepts for these
                # two keys on the sibling `free_cast_condition` field — this
                # branch previously only special-cased ``control_land_type``,
                # so an alt_cost using either of these (a real, valid shape)
                # would have been silently rejected as "must be a bool".
                if isinstance(cvalue, bool) or not isinstance(cvalue, int) or cvalue < 1:
                    raise SpecValidationError(f"{ckey!r} alt_cost condition must be a positive int")
            elif not isinstance(cvalue, bool):
                raise SpecValidationError(f"{ckey!r} alt_cost condition must be a bool")

    @staticmethod
    def _validate_condition(condition: dict[str, Any]) -> None:
        """Structural check for an `EffectSpec.condition` (RULE 702.33b's
        kicked-gate, and the target-based ``"target_is_controller"`` gate)."""
        if not isinstance(condition, dict) or not condition:
            raise SpecValidationError(f"malformed effect condition: {condition!r}")
        for key, value in condition.items():
            if key not in _ALLOWED_CONDITION_KEYS:
                raise SpecValidationError(f"unknown effect condition key {key!r}")
            if key == "kicked" and not isinstance(value, bool):
                raise SpecValidationError("'kicked' condition must be a bool")
            if key == "target_is_controller" and not isinstance(value, bool):
                raise SpecValidationError("'target_is_controller' condition must be a bool")
            if key == "clash_won" and not isinstance(value, bool):
                raise SpecValidationError("'clash_won' condition must be a bool")
            if key == "additional_cost_paid" and not isinstance(value, bool):
                raise SpecValidationError("'additional_cost_paid' condition must be a bool")
            if key == "previous_target_is_suspected" and not isinstance(value, bool):
                raise SpecValidationError(
                    "'previous_target_is_suspected' condition must be a bool"
                )
            if key == "kicked_at_least":
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise SpecValidationError("'kicked_at_least' condition must be a positive int")
            if key == "source_has_subtype" and (not isinstance(value, str) or not value.strip()):
                raise SpecValidationError("'source_has_subtype' condition must be a non-empty string")

    @staticmethod
    def _clamp_params(params: dict[str, Any]) -> None:
        for key in _CLAMPED_PARAM_KEYS:
            value = params.get(key)
            if isinstance(value, bool):  # bool is an int subclass — leave flags alone
                continue
            if isinstance(value, int):
                params[key] = max(0, min(value, MAX_EFFECT_MAGNITUDE))
        # ENG-31: parametric keyword grants carry their number one level down,
        # in ``[{"name": str, "n": int}, ...]`` — clamp each nested "n" too so
        # a synthesized ``["R"] * n`` can't be handed an unbounded amount.
        for entry in params.get("parametric_keywords") or []:
            if isinstance(entry, dict) and isinstance(entry.get("n"), int) and not isinstance(entry["n"], bool):
                entry["n"] = max(0, min(entry["n"], MAX_EFFECT_MAGNITUDE))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ability_kind": self.ability_kind,
            "effects": [e.to_dict() for e in self.effects],
            "trigger": self.trigger,
            "cost": self.cost,
            "target": self.target,
            "keyword": self.keyword,
            "modes": self._modes_to_dict(),
            "additional_cost": self.additional_cost,
            "additional_cost_optional": self.additional_cost_optional,
            "conditional_flash": self.conditional_flash,
            "free_cast_condition": self.free_cast_condition,
            "optional": self.optional,
            "raw_text": self.raw_text,
            "parser": self.parser.to_dict(),
        }

    def _modes_to_dict(self) -> Optional[dict[str, Any]]:
        if self.modes is None:
            return None
        return {
            "or_both": bool(self.modes.get("or_both", False)),
            "at_least": bool(self.modes.get("at_least", False)),
            "choose": int(self.modes.get("choose", 1)),
            "options": [[e.to_dict() for e in opt] for opt in self.modes.get("options", [])],
            "descriptions": list(self.modes.get("descriptions") or []),
            "mode_costs": list(self.modes.get("mode_costs") or []) or None,
        }

    @staticmethod
    def _modes_from_dict(data: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not data:
            return None
        return {
            "or_both": bool(data.get("or_both", False)),
            "at_least": bool(data.get("at_least", False)),
            "choose": int(data.get("choose", 1)),
            "options": [
                [EffectSpec.from_dict(e) for e in opt] for opt in (data.get("options") or [])
            ],
            "descriptions": list(data.get("descriptions") or []),
            "mode_costs": list(data.get("mode_costs") or []) or None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AbilitySpec":
        return cls(
            ability_kind=str(data["ability_kind"]),
            effects=[EffectSpec.from_dict(e) for e in (data.get("effects") or [])],
            trigger=data.get("trigger"),
            cost=data.get("cost"),
            target=data.get("target"),
            keyword=data.get("keyword"),
            modes=cls._modes_from_dict(data.get("modes")),
            additional_cost=data.get("additional_cost"),
            additional_cost_optional=bool(data.get("additional_cost_optional", False)),
            conditional_flash=data.get("conditional_flash"),
            free_cast_condition=data.get("free_cast_condition"),
            optional=bool(data.get("optional", False)),
            raw_text=str(data.get("raw_text", "")),
            parser=ParserProvenance.from_dict(data.get("parser") or {}),
        )
