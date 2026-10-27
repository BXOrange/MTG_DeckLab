"""Helpers and the `EffectHandler` row type shared by several `effect_rows` modules (PAR-172 M2: moved mechanically out of `handlers.py`)."""

from __future__ import annotations

import re

from ..clause_reading import STANDALONE, ClauseReading
from dataclasses import dataclass
from typing import Any, Callable, Optional
from ..clause_primitives import grantable_flag_slug, split_keywords_with_parametric
from ..count_phrase import COMBAT_RELATION_TAILS, parse_count_phrase
from ..counters import KEYWORD_COUNTER_KINDS
from ..referent_condition import PRONOUN_NOUN_ALT
from ..static_handlers import object_filter
from ..subgrammars import (
    COLOR_LETTERS,
    devotion_selector,
    NOT_YOU_TAIL,
    NOT_YOU_TARGET_KINDS,
    OTHER_TARGET_KINDS,
    resolve_color_word,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    SOURCE_EXCLUDED_TARGET_KINDS,
    TARGET,
    target_is_optional,
    target_kind_allowed,
    target_macro,
    target_quality_filter,
)
from ...normalize import SELF
from ...spec import EffectSpec, GROUP_SUBJECT_KEY_SENTINEL
from ..clause_hooks import match_clause_once


#: Colour words → their WUBRG symbol (for a created token's colours).
#: PAR-63: the shared map, not a local copy.
COLOR_WORDS = COLOR_LETTERS
#: Words in a token's description that are supertypes/joiners, not its subtype.
_TOKEN_NOISE_WORDS: frozenset[str] = frozenset(
    {"artifact", "enchantment", "legendary", "snow", "colorless", "and", "or"}
)


@dataclass(frozen=True)
class EffectHandler:
    """One catalogue row: a full-clause regex + a builder emitting `EffectSpec`s."""

    name: str
    regex: re.Pattern[str]
    build: Callable[..., Optional[list[EffectSpec]]]
    #: The reading facts this row needs (`ClauseReading.satisfies`); a row is offered only when the clause is being
    #: read under all of them. Bare pronouns mean different objects under different readings, and a clause alone
    #: cannot tell them apart, so a pronoun row declares the reading it serves rather than claiming blind:
    #:   * ``self_subject``: "**it**" is the ability's own source ("when ~ enters, it fights …"). English writes
    #:     that pronoun the same way for a *previously targeted* creature ("target creature you control gets
    #:     +1/+2 until end of turn. it fights …", Epic Confrontation), so the row is offered only when the caller
    #:     states the implicit subject really is the source (`segment_line`, an unsplit self-subject trigger
    #:     body). Claiming it blind would model Epic Confrontation as "the *sorcery* fights".
    #:   * ``previous_subject``: "it"/"that creature" is what an **earlier clause of the same ability** chose
    #:     (`GameContext.previous_targets`); offered only when `parse_effect_body` has just parsed such a clause
    #:     and it announced a creature target. Never together with ``self_subject``.
    #:   * ``group_subject`` (MEC-28): "it"/"that creature" is whichever object matched a RULE 603.1 group-subject
    #:     trigger condition, varying every firing (`effect_binder._retarget_implicit_subject_effects` turns the
    #:     resulting ``target_kind: None`` into a live per-firing read).
    #:   * ``previous_selector`` (MEC-28): "they" is the group a mass selector in the preceding clause acted on
    #:     (untargeted, so never in `previous_targets`; `segmenter._announces_group_selector`).
    #:   * ``attached_subject`` (PAR-117): "its" is RULE 303.4/301.5's attached host (the trigger condition is
    #:     ``{"subject": "attached_permanent"}``); read through `effect_conditions.subject_of("attached", ...)`.
    requires: ClauseReading = STANDALONE
    #: A builder that must see the reading it runs under takes it as a second argument (``build(m, reading)``) --
    #: for the few that re-enter the table (`match_clause_once`) or branch on ``reading.group_clause`` -- instead of
    #: reading a global. Every other builder takes the match alone.
    reading_aware: bool = False
    #: PAR-169: names the rows this one is the *fallback* for. ``HANDLERS`` order is semantics (the first row to
    #: claim a clause wins), and where a generalized grammar and an older, narrower-vocabulary row both claim a
    #: clause with different IR, the older row is kept only for the clauses the primary declines. Declaring it
    #: here makes that overlap explicit rather than accidental: the row must come *after* every row it names, and
    #: `test_handler_table_shadowing` allows a same-clause/different-IR pair only through this field (or a
    #: context-gated row preceding an ungated one).
    fallback_for: tuple[str, ...] = ()

    def match(self, clause: str, reading: ClauseReading = STANDALONE) -> Optional[list[EffectSpec]]:
        """Effects for ``clause`` if this handler claims it whole, else ``None``.

        A builder may still return ``None`` after a regex match (e.g. an
        unrecognised target phrase) — that also means "not claimed", keeping
        the gate fail-closed.
        """
        m = self.regex.fullmatch(clause.strip())
        if m is None:
            return None
        specs = self.build(m, reading) if self.reading_aware else self.build(m)
        if specs is not None and not _target_qualities_kept(m, specs):
            return None
        return specs


def _carries_filter(node: object, fragment: dict) -> bool:
    """Whether some ``creature_filter`` inside ``node`` (an effect's params, nested) holds ``fragment``."""
    if isinstance(node, dict):
        held = node.get("creature_filter")
        if isinstance(held, dict) and all(held.get(k) == v for k, v in fragment.items()):
            return True
        return any(_carries_filter(v, fragment) for v in node.values())
    if isinstance(node, (list, tuple)):
        return any(_carries_filter(v, fragment) for v in node)
    return False


def _target_qualities_kept(m: re.Match[str], specs: list[EffectSpec]) -> bool:
    """PAR-141: a matched TARGET phrase's negated quality ("without flying") must reach a spec.

    `resolve_target_kind` drops the quality from the kind, so a builder that never merges
    `resolve_target_creature_state_filter` would resolve against *every* creature — the silent
    over-wide claim v409 fixed for the combat-state adjectives. Refusing here keeps the slot
    fail-closed for all ~hundred `{TARGET}` handlers at once instead of trusting each builder.
    """
    for name, text in m.groupdict().items():
        if text and (name == "target" or name.startswith("target_")):
            fragment = target_quality_filter(text)
            if fragment and not any(_carries_filter(spec.params, fragment) for spec in specs):
                return False
    return True


def compile_clause(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# --- Builders ---------------------------------------------------------------
# Each returns the effect list, or None when the clause can't be safely modeled
# (an unknown target phrase → fail-closed, don't guess).


#: RULE 115.1a "up to one" (`subgrammars.target_is_optional`) → the
#: `{"optional": True}` param sliver every `{TARGET}`-based builder below
#: merges in, or ``{}`` for a bare "target X" (still required, unchanged).
def optional_param(m: re.Match[str]) -> dict:
    return {"optional": True} if target_is_optional(m) else {}


#: RULE 115.1a generalized to N>=2 — "destroy **two** target creatures",
#: "destroy **up to two** target artifacts and/or enchantments", "deals N
#: damage to each of **up to two** target creatures and/or planeswalkers".
#: A deliberately separate, self-contained grammar from the shared `TARGET`
#: macro above (`_TARGET_ROWS` is singular-only and reused by many other
#: handler families — return_to_hand/tap/attach/… — that this feature
#: doesn't touch): a plural noun phrase never collides with `TARGET`'s bare
#: "target X"/"up to one target X" shapes, so there's no dispatch ambiguity
#: registering both. Wired up for `destroy`/`exile`/`damage`/`tap`/
#: `return_to_hand`/`add_counters`/`return_from_graveyard` — every effect
#: class `game/effects/core.py` loops a `count` over. `return_from_graveyard`
#: doesn't reuse this alternation directly (graveyard clauses have their own
#: scope/type-word grammar, `_RETURN_FROM_GRAVEYARD_MULTI_RE`) but shares
#: `_MULTI_TARGET_QUANTIFIER`.
_MULTI_TARGET_ROWS: list[tuple[str, str]] = [
    (r"target creatures and/or planeswalkers", "any"),
    (r"target artifacts and/or enchantments", "artifact_or_enchantment"),
    # "exile X target artifacts and/or creatures" (Hide on the Ceiling) — its own pool, like the row above.
    (r"target artifacts and/or creatures", "artifact_or_creature"),
    (r"target creatures", "creature"),
    # "return 1 or 2 target nonland permanents to their owners' hands"
    # (Wanderwine Farewell) — tried before the bare `target permanents` row
    # below since RAW excludes lands, unlike that row.
    (r"target nonland permanents", "nonland_permanent"),
    (r"target permanents", "permanent"),
    # The single-type pools (`targeting.TARGET_FRAMES`' artifact/enchantment/land): "destroy X
    # target artifacts" must not offer a creature or a land.
    (r"target artifacts", "artifact"),
    (r"target enchantments", "enchantment"),
    (r"target lands", "land"),
    (r"target players", "player"),
]
#: PAR-128: the controller scope on a plural target phrase ("tap up to 2 target
#: creatures your opponents control"). Only the rows whose kind has a scoped
#: pool in `subgrammars.NOT_YOU_TARGET_KINDS` compose it; "target artifacts",
#: "target lands" and the like read as the broad ``permanent`` kind, so scoping
#: them would claim a narrower pool than the engine offers — they stay unclaimed.
MULTI_TARGET_SCOPE_TAIL = r" (?:your opponents control|an opponent controls|you don'?t control|you control)"
#: "…each of up to 2 target creatures **you control**" — the plural mirror of the singular
#: `<kind>_you_control` pools (`targeting.TARGET_FRAMES`' ``SCOPE_YOU``).
MULTI_TARGET_YOU_KINDS: dict[str, str] = {
    "land": "land_you_control",
    "creature": "creature_you_control", "permanent": "permanent_you_control",
    "nonland_permanent": "nonland_permanent_you_control",
    "creature_or_planeswalker": "targetable_creature_or_planeswalker_you_control",
}
_MULTI_TARGET_SCOPED_KINDS: dict[str, str] = {
    "target lands": "land",
    r"target creatures and/or planeswalkers": "creature_or_planeswalker",
    r"target creatures": "creature",
    r"target nonland permanents": "nonland_permanent",
    r"target permanents": "permanent",
    r"target artifacts and/or enchantments": "artifact_or_enchantment",
}
MULTI_TARGET_ALT = (
    "(?:(?:" + "|".join(f"(?:{frag})" for frag, _ in _MULTI_TARGET_ROWS) + ")"
    f"(?:{MULTI_TARGET_SCOPE_TAIL})?)"
)


def _multi_target_kind_with_spell(phrase: str) -> Optional[str]:
    text = phrase.strip()
    if re.fullmatch(r"target spells", text, re.IGNORECASE):
        return "spell"
    return _multi_target_kind(phrase)


def _multi_target_kind(phrase: str) -> Optional[str]:
    text = phrase.strip()
    scoped = re.fullmatch(rf"(?P<base>.*?)(?P<tail>{MULTI_TARGET_SCOPE_TAIL})", text, re.IGNORECASE)
    if scoped is not None:
        base = _MULTI_TARGET_SCOPED_KINDS.get(scoped.group("base").lower())
        if base is None:
            return None
        if scoped.group("tail").strip() == "you control":
            return MULTI_TARGET_YOU_KINDS.get(base)
        return NOT_YOU_TARGET_KINDS.get(base)
    for frag, kind in _MULTI_TARGET_ROWS:
        if re.fullmatch(frag, text, re.IGNORECASE):
            return kind
    return None


#: A numeric quantifier before a plural TARGET phrase: "two "/"three " (a
#: mandatory count — RULE 601.2c needs that many legal targets to even be
#: castable) or "up to two "/"up to three " (optional, 0..N — never locks
#: casting, same as "up to one"). Digits only — `normalize.py` already
#: folds spelled-out numbers up to twelve. PAR-15's "any number of" is a
#: third alternative — RULE 115.1a's genuinely unbounded, freely-chosen
#: count (0..however many are legal), modeled the same way this codebase's
#: one pre-existing hand-authored example already did (`card_registry.
#: _fire_covenant`'s own comment: "a real board never has X-1's worth of
#: relevant creatures beyond that") — a generous fixed cap
#: (`_ANY_NUMBER_TARGET_CAP`) rather than a live `legal_targets` count,
#: since the existing "up to N, offered one at a time, stop early" round-
#: gathering machinery (`RulesEngine._continue_trigger_multi_target`)
#: already handles running out of legal targets *or* the player stopping
#: voluntarily before the cap — the cap only needs to never be the *true*
#: bottleneck.
ANY_NUMBER_TARGET_CAP = 10
#: ENG-30: RULE 601.2c's third quantifier shape — a genuine mandatory
#: *range* ("one or two target creatures", digits already folded by
#: `normalize.py`) — at least ``range_min``, at most ``range_max``, unlike
#: "up to N" whose floor is always 0. Tried before the plain ``count``
#: alternative below so "1 or 2 " isn't swallowed by a bare `\d+` match on
#: just the "1" (`targeting.TargetSpec.count_max`).
MULTI_TARGET_QUANTIFIER = (
    r"(?:(?P<any_number>any number of )"
    r"|(?P<range_min>\d+) or (?P<range_max>\d+) "
    r"|(?P<up_to>up to )?(?P<count>\d+) )"
    # PAR-128: "each of up to 2 **other** target creatures" (Felidar Savior) — RULE 109.5, not
    # the ability's own source. `_multi_target_params` reads it (`_OTHER_MULTI_KINDS`).
    r"(?P<other>other )?"
)


#: An optional trailing "controlled by different players/controllers"
#: clause (Run Away Together/Protector of the Wastes-shaped, RULE 115.1a's
#: N>=2 generalized with a cross-target constraint — `targeting.TargetSpec.
#: distinct_controllers`) — appended right after `_MULTI_TARGET_ALT`'s
#: target phrase in whichever multi-target handler regex opts in.
MULTI_TARGET_DISTINCT_CONTROLLERS = r"(?P<dc> controlled by different (?:players|controllers))?"


#: PAR-128: "destroy **X** target creatures" / "tap **up to X** target creatures" — the target
#: count is the spell's or ability's announced {X} (`TargetSpec.count_selector="source_x_paid"`,
#: read at announce time). Only the handlers whose effect class takes a `count_selector` opt in
#: through this variant; every other handler keeps `_MULTI_TARGET_QUANTIFIER` and so never sees
#: an "x" count.
MULTI_TARGET_QUANTIFIER_X = rf"(?:(?P<x_count>(?P<x_up_to>up to )?x )|{MULTI_TARGET_QUANTIFIER})"
_OTHER_MULTI_SIBLINGS: dict[str, str] = dict(OTHER_TARGET_KINDS)


def multi_target_params(m: re.Match[str], allow_spell: bool = False) -> Optional[dict]:
    """The shared ``{target_kind, count, optional?, distinct_controllers?}``
    params for a `_MULTI_TARGET_QUANTIFIER` + `_MULTI_TARGET_ALT` match, or
    ``None`` if the target phrase isn't recognized or the count is < 2 (the
    N=1 "up to one"/bare-target case is the existing singular handler's
    job, not this one's — a count of exactly 1 here would just be a
    confusing duplicate route to the same effect). PAR-15's "any number of"
    always carries ``optional=True`` (RULE 115.1a — 0 is always a legal
    choice) and a capped ``count`` (`_ANY_NUMBER_TARGET_CAP`). ENG-30's
    "N or M" range sets ``count`` to the RULE 601.2c *minimum* and
    ``count_max`` to the ceiling (`targeting.TargetSpec.count_max`) — never
    ``optional``, since fewer than the minimum isn't a legal choice.

    ``allow_spell=True`` (only `exile_multi_target`) additionally recognizes
    "target spells" — see `_MULTI_TARGET_ALT_WITH_SPELL`'s docstring for why
    this isn't just folded into the shared alternation every caller reads.
    """
    kind = (
        _multi_target_kind_with_spell(m.group("target"))
        if allow_spell else _multi_target_kind(m.group("target"))
    )
    if kind is None:
        return None
    if m.groupdict().get("other"):
        # The pool must already leave the source out, or have an "other" sibling.
        if kind in _OTHER_MULTI_SIBLINGS:
            kind = _OTHER_MULTI_SIBLINGS[kind]
        elif kind not in SOURCE_EXCLUDED_TARGET_KINDS:
            return None
    if m.groupdict().get("x_count"):
        # `count` is the cap `_chosen_targets` slices a resolved pick list to; the announced X
        # (`count_selector`) decides how many picks were offered.
        params: dict = {
            "target_kind": kind, "count": ANY_NUMBER_TARGET_CAP,
            "count_selector": "source_x_paid", "optional": True,
        }
    elif m.groupdict().get("any_number"):
        params = {"target_kind": kind, "count": ANY_NUMBER_TARGET_CAP, "optional": True}
    elif m.groupdict().get("range_min") is not None:
        range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
        if range_min < 1 or range_max <= range_min:
            return None  # fail closed on a nonsensical/degenerate range
        params = {"target_kind": kind, "count": range_min, "count_max": range_max}
    else:
        count = int(m.group("count"))
        if count < 2:
            return None
        params = {"target_kind": kind, "count": count}
        if m.groupdict().get("up_to"):
            params["optional"] = True
    if m.groupdict().get("dc"):
        params["distinct_controllers"] = True
    return params

#: RULE 205.3: subtypes of the other card types — a creature target never carries them, so a "target <word> you
#: control" naming one is some other target kind (an Equipment, an Aura, a Gate…) and not this row's business.
NONCREATURE_SUBTYPE_WORDS: frozenset[str] = frozenset({
    # artifact (205.3g)
    "attraction", "blood", "clue", "contraption", "equipment", "food", "fortification", "gold", "incubator",
    "junk", "map", "powerstone", "treasure", "vehicle", "lander", "shard", "role",
    # enchantment (205.3h)
    "aura", "background", "case", "class", "curse", "rune", "saga", "shard", "shrine", "cartouche", "room",
    # land (205.3i)
    "cave", "desert", "forest", "gate", "island", "lair", "locus", "mine", "mountain", "plains", "power-plant",
    "sphere", "swamp", "tower", "town", "urza's",
    # spell / planeswalker / battle (205.3j-k)
    "adventure", "arcane", "lesson", "omen", "trap", "siege",
})


#: RULE 601.2c's mass/untargeted-selector vocabulary — shared by the
#: damage/lose_life/player-counter "each creature/player/opponent" families
#: below, not RULE 115 targeting (see `subgrammars._TARGET_ROWS`'s note on
#: why "each opponent"/"each player" stay out of that grammar). Each
#: family's own regex alternation still independently gates which of these
#: keys it can actually capture — this dict is a pure value lookup, not a
#: regex-alternation source — *except* `_DAMAGE_SELECTOR_ALT` below, which
#: intentionally reads only the damage-legal subset rather than every key
#: here, since no card prints "deals damage to each other player".
SELECTOR_WORD_MAP: dict[str, str] = {
    "each creature": "each_creature",
    # PAR-128: RULE 109.5 — every creature but the damage's own source.
    "each other creature": "each_other_creature",
    "each player": "each_player",
    "each opponent": "each_opponent",
    # "each of your opponents" (Aurelia, the Law Above) — the same group, spelled for a trigger controlled by "you".
    "each of your opponents": "each_opponent",
    # Symmetric mass-damage board wipes (RULE 601.2c) — the global-scope
    # union selectors `DealDamageEffect` already resolves. "each creature
    # and each player" (Cave-In / Fire Tempest / Inferno / Pestilence-
    # shaped, ~32 SOLO); "each creature and each planeswalker" (Star of
    # Extinction / Dragonback Assault, ~7 SOLO). Only the `damage` family's
    # own regex row (`damage_selector`) opts these keys in.
    "each creature and each player": "each_creature_and_player",
    "each creature and each planeswalker": "each_creature_and_planeswalker",
    # "~ deals N damage to each creature your opponents control." (Village
    # Pillagers) / "…an opponent controls" — `DealDamageEffect`'s
    # ``each_creature_opponents_control`` (opponents' creatures, no players).
    "each creature your opponents control": "each_creature_opponents_control",
    "each creature an opponent controls": "each_creature_opponents_control",
    # "~ deals N damage to **you**" (RULE 109.5 — the source's own
    # controller, and only them; Mana Vault / Fledgling Djinn / Juzám Djinn
    # / Sulfuric Vortex-shaped upkeep bleed). `DealDamageEffect`'s
    # ``"controller"`` selector.
    "you": "controller",
    # "each other player" (Urborg Syphon-Mage, lose_life/rad-counter only) —
    # functionally identical to "each opponent" in this engine (no
    # team-variant life sharing, RULE 809/810/811 — PLR-14, still unbuilt).
    "each other player": "each_opponent",
    "each other opponent": "each_other_opponent",
    # "whenever a player casts a spell, ~ deals 2 damage to that player."
    # (Spellshock-shaped) — the player named by the trigger's own firing
    # event (`effects.DealDamageEffect`'s ``"event_player"`` selector), not
    # an untargeted group like the rows above.
    "that player": "event_player",
    # PAR-132: "~ deals 3 damage to that spell or ability's controller" (Retromancer) — the BECOMES_TARGET event's
    # ``player_id`` is the targeting spell/ability's controller (`_fire_becomes_target_events`).
    "that spell or ability's controller": "event_player",
    # "…if it's not their turn, ~ deals 4 damage to them." (Scytheclaw
    # Raptor) — same firing-event player, just the pronoun object form
    # rather than "that player".
    "them": "event_player",
}
SINGULAR_GROUP_HEADS = re.compile(r"\b(creature|planeswalker|permanent|artifact|land|enchantment)\b(?!s)")


#: The player a mass-damage group can be scoped to (`DealDamageEffect.group_player`).
DAMAGE_GROUP_PLAYER_TAILS: dict[str, str] = {
    " defending player controls": "defending",
    " that player controls": "event_player",
    " target player controls": "player",
    " target opponent controls": "opponent",
}


def selector_devotion_builder(effect_type: str):
    """The shared "X to each opponent/player equal to your devotion to
    `<colour>`" body: `_damage_selector_devotion`/`_lose_life_selector_devotion`
    differ only in which `EffectSpec` type the resolved selector/devotion
    amount get attached to."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        selector = SELECTOR_WORD_MAP[m.group("selector")]
        dsel = devotion_selector(m)
        if not dsel:
            return None
        return [EffectSpec(effect_type, {"amount_from_count_selector": dsel, "selector": selector})]

    return build


def split_token_mid_words(mid: str) -> tuple[list[str], list[str], bool]:
    """A created token's "<mid>" description words (everything between its
    P/T and "creature token") → ``(colors, subtypes, is_artifact)``.

    "artifact" is a `_TOKEN_NOISE_WORDS` entry — recognized, not just
    dropped: "colorless Construct **artifact** creature token" (Construct/
    Thopter/Servo-shaped) needs `CreateTokenEffect.is_artifact` set, or the
    synthesized token silently comes out as a bare Creature missing the
    Artifact card type entirely (RULE 704.5f's zero-toughness check, a
    "sacrifice an artifact" cost, and any artifact-count anthem all read
    `Card.is_artifact`). The one shared word-splitting loop for all three
    "<mid> creature token[s]" handler shapes (`_xx_token_mid_params`,
    `_inline_create_token_params`, `_create_named_legendary_token`) — kept
    as one function specifically so a future noise word only needs adding
    here once, not independently in three near-identical copies.
    """
    colors: list[str] = []
    subtypes: list[str] = []
    is_artifact = False
    for word in mid.split():
        if word in COLOR_WORDS:
            colors.append(COLOR_WORDS[word])
        elif word == "artifact":
            is_artifact = True
        elif word in _TOKEN_NOISE_WORDS:
            continue
        else:
            subtypes.append(word.capitalize())
    return colors, subtypes, is_artifact


def xx_token_mid_params(mid: str, kw: Optional[str]) -> Optional[dict]:
    """The shared ``colors``/``subtypes``/``keywords`` params for an X/X
    token clause's "<mid> token[ with <kw>]" tail — the same word-splitting
    `_inline_create_token_params` uses for a literal-stats token, factored
    out since neither of the two X/X handlers below share that function's
    other (count/tapped/legendary) groups."""
    colors, subtypes, is_artifact = split_token_mid_words(mid)
    keywords: list[str] = []
    if kw:
        parsed = token_keywords(kw)
        if parsed is None:
            return None
        keywords = parsed
    params: dict = {"colors": colors, "subtypes": subtypes, "keywords": keywords}
    if is_artifact:
        params["is_artifact"] = True
    if subtypes:
        params["token_name"] = " ".join(subtypes)
    return params
SACRIFICE_EDICT_WHAT_WORDS: dict[str, str] = {
    "creature": "creature", "artifact": "artifact", "land": "land", "permanent": "permanent",
}


#: PAR-117 (PAR-115's group-subject residue): "whenever a `<type>` [you
#: control] `<verb>`, its controller `<verb2>` …" (Poisonbelly Ogre-shaped
#: — "whenever another creature enters, its controller loses 1 life.") —
#: "its" is RULE 603.1's own group-subject referent (whichever object
#: satisfied the trigger condition, a different one every firing), not a
#: creature an earlier clause of this body targeted (`_ITS_CONTROLLER_*`
#: above) or the ability's own source. `effect_conditions.subject_of
#: ("entering", ...)` already resolves exactly this — the firing event's
#: own ``instance_id`` (built for MEC-28's `group_subject_only` pronoun
#: gate) — so the same ``{"of": …, "as": "controller"}`` referent
#: `GainLifeEffect`/`LoseLifeEffect`/`DrawCardEffect`/`DiscardEffect`
#: already read via `_operand_player` (PAR-115) works unchanged; only
#: `MillEffect` needs a new selector value, the `"previous_subject_
#: controller"` sibling for this referent instead of `previous_targets`.
ENTERING_CONTROLLER: dict = {"of": "entering", "as": "controller"}
BECOMES_TARGET_EVENT = "BECOMES_TARGET"
EVENT_PLAYER_EVENTS_KEY = "event_player_events"


#: The single-printed-type permanent target kinds `resolve_target_kind`
#: resolves "target artifact"/"target enchantment"/"target land" to (RULE
#: 115.1c) — added to every guard tuple below that already accepted the
#: broad, untyped "target permanent" kind, so narrowing that mapping (fixing
#: e.g. Abrade's "Destroy target artifact." from wrongly offering any
#: permanent, including lands) doesn't regress these families to UNMODELED.
SINGLE_TYPE_PERMANENT_KINDS: tuple[str, ...] = (
    "artifact", "enchantment", "land", "room",
    # "destroy/exile target nonbasic land [an opponent controls]" (Fulminator
    # Mage / Dust Bowl / Field of Ruin / Ravenous Baboons — 21 SOLO on the
    # bare form). RULE 205.4 supertype filter; `targeting.legal_targets` has
    # a fully-implemented `nonbasic_land` branch and a new `nonbasic_land_
    # you_dont_control` sibling — same narrow-single-noun shape as `land`.
    "nonbasic_land", "nonbasic_land_you_dont_control",
)


def two_color_letters(m: re.Match[str]) -> Optional[list[str]]:
    """A `(?P<c1>…) or (?P<c2>…)` colour pair → [W/U/B/R/G, …], or ``None``
    (an unrecognised colour word, or the same colour twice)."""
    colors = [resolve_color_word(m.group("c1")), resolve_color_word(m.group("c2"))]
    if not all(colors) or colors[0] == colors[1]:
        return None
    return colors


#: A creature's power/toughness/keyword *quality* filter (RULE 115/601.2c —
#: "destroy target creature with power 4 or greater"/"…with flying"-shaped,
#: `targeting.TargetSpec.creature_filter`). English keyword word → the
#: internal snake_case token `combat.has` checks; only single-word-in-text
#: keywords a "with <keyword>" clause plausibly names are listed (extend as
#: a real card needs one — fail-closed for anything else via the ``kw``
#: alternation below).
CREATURE_FILTER_KEYWORD_WORDS: dict[str, str] = {
    "flying": "flying", "defender": "defender", "first strike": "first_strike",
    "double strike": "double_strike", "trample": "trample", "vigilance": "vigilance",
    "deathtouch": "deathtouch", "lifelink": "lifelink", "menace": "menace",
    "haste": "haste", "indestructible": "indestructible", "hexproof": "hexproof",
    "reach": "reach", "horsemanship": "horsemanship",
}
#: One power/toughness/keyword clause, with named groups suffixed by
#: ``suffix`` so the same fragment can appear twice in one regex (a compound
#: "with power 4 or greater and flying" filter — two independent clauses
#: joined by "and", RULE 115/601.2c) without a group-name collision.
def _creature_filter_clause(suffix: str) -> str:
    return (
        rf"power (?P<pwr{suffix}>\d+) or (?P<pwr_cmp{suffix}>greater|less)"
        rf"|toughness (?P<tough{suffix}>\d+) or (?P<tough_cmp{suffix}>greater|less)"
        rf"|(?P<kw{suffix}>{'|'.join(CREATURE_FILTER_KEYWORD_WORDS)})"
        # "with a -1/-1 counter on it" (Liliana, Death Wielder's -3 —
        # `TargetSpec.creature_filter` ``has_counter_kind``) / the kindless
        # "with a counter on it" (``has_counter``). Longer alternative first.
        rf"|a (?P<ctrkind{suffix}>-1/-1|\+1/\+1) counter on it"
        rf"|a (?P<ctrany{suffix}>counter) on it"
    )


#: The qualifier suffix shared by `_DESTROY_CREATURE_FILTER_RE`/
#: `_EXILE_CREATURE_FILTER_RE` — appended right after "target creature". The
#: trailing group is an optional second " and [with] <clause>" — only two
#: clauses (the real-card ceiling found so far); a third would need a third
#: suffixed group set.
CREATURE_FILTER_SUFFIX = (
    rf"with (?:{_creature_filter_clause('')})"
    rf"(?: and (?:with )?(?:{_creature_filter_clause('2')}))?"
)


#: PAR-128: the controller scope on a quality-filtered creature target, on
#: either side of the filter ("target creature an opponent controls with power
#: 2 or less", "target creature with flying an opponent controls"). Used by the
#: rows that read `_scoped_creature_kind`; the can't-be-blocked row keeps the
#: bare suffix.
CREATURE_FILTER_SCOPED = (
    rf"(?P<scope_pre>{NOT_YOU_TAIL})? {CREATURE_FILTER_SUFFIX}(?P<scope_post>{NOT_YOU_TAIL})?"
)


def scoped_creature_kind(m: re.Match[str]) -> Optional[str]:
    """The creature target kind a `_CREATURE_FILTER_SCOPED` match names, or
    ``None`` when the scope is written on both sides of the filter."""
    groups = m.groupdict()
    pre, post = groups.get("scope_pre"), groups.get("scope_post")
    if pre and post:
        return None
    return "creature_you_dont_control" if pre or post else "creature"


def _creature_quality_filter_clause(groups: dict, suffix: str) -> Optional[dict]:
    if groups.get(f"pwr{suffix}"):
        n = int(groups[f"pwr{suffix}"])
        return {"min_power": n} if groups[f"pwr_cmp{suffix}"] == "greater" else {"max_power": n}
    if groups.get(f"tough{suffix}"):
        n = int(groups[f"tough{suffix}"])
        return {"min_toughness": n} if groups[f"tough_cmp{suffix}"] == "greater" else {"max_toughness": n}
    if groups.get(f"kw{suffix}"):
        return {"keyword": CREATURE_FILTER_KEYWORD_WORDS[groups[f"kw{suffix}"]]}
    if groups.get(f"ctrkind{suffix}"):
        return {"has_counter_kind": groups[f"ctrkind{suffix}"]}
    if groups.get(f"ctrany{suffix}"):
        return {"has_counter": True}
    return None


def creature_quality_filter(m: re.Match[str]) -> Optional[dict]:
    groups = m.groupdict()
    first = _creature_quality_filter_clause(groups, "")
    if first is None:
        return None
    second = _creature_quality_filter_clause(groups, "2")
    if second is None:
        return first
    return {**first, **second}


#: "target creature [an opponent controls] **that was dealt damage this turn**" (Initiate of Blood, Tail Spikes, Mercenary
#: Informer-style removal; PAR-154/MEC-115) — RULE 115/601.2c's `TargetSpec.creature_filter` ``damaged_this_turn``
#: (`combat.matches_object_filter`, RULE 514.2: marked damage this turn). The controller scope may sit before it.
DAMAGED_THIS_TURN_TAIL = rf"(?P<scope_pre>{NOT_YOU_TAIL})? that was dealt damage this turn"


def damaged_creature_kind(m: re.Match[str]) -> str:
    return "creature_you_dont_control" if m.group("scope_pre") else "creature"
#: The mana-value bound's own magnitude accepts ``x`` (Meltdown's own
#: "with mana value X or less", X being this spell's announced {X}) as well
#: as a literal digit — `_mass_destroy_filter_dict` carries the ``"x"``
#: sentinel straight into `DestroyEffect.filter`'s ``max_mana_value``/
#: ``min_mana_value`` key, which `RulesEngine._substitute_x` now knows how
#: to walk into (a plain digit bound like Damnation's own "mana value 3 or
#: less" never reaches this branch at all).
MASS_DESTROY_FILTER = (
    r"(?: with (?:mana value (?P<mv>\d+|x) or (?P<mv_cmp>greater|less)"
    r"|toughness (?P<tough>\d+) or greater"
    r"|power (?P<power>\d+) or (?P<power_cmp>greater|less)"
    # PAR-74: "destroy all permanents with that spell's mana value."
    # (Celestial Kirin) — the exact-match sibling of the ``mv``/``mv_cmp``
    # bound above, reading the firing SPELL_CAST event's own mana value
    # (`_mass_selector_objects`'s new ``mana_value_from_trigger_event`` key).
    r"|(?P<trigger_mv>that spell'?s mana value)))?"
)


def mass_destroy_filter_dict(m: re.Match[str]) -> Optional[dict]:
    groups = m.groupdict()
    filt: dict = {}
    if groups.get("mv"):
        n: Any = int(groups["mv"]) if groups["mv"] != "x" else "x"
        filt["max_mana_value" if groups["mv_cmp"] == "less" else "min_mana_value"] = n
    if groups.get("tough"):
        filt["min_toughness"] = int(groups["tough"])
    if groups.get("power"):
        n = int(groups["power"])
        filt["max_power" if groups["power_cmp"] == "less" else "min_power"] = n
    if groups.get("trigger_mv"):
        filt["mana_value_from_trigger_event"] = True
    return filt or None
_MASS_GROUP_REFUSED_WORDS = (
    "target", "that player", "other than", "except", "chosen", "blocking", "blocked", "graveyard",
    "hand", "library", "exile", "sacrificed", "this way", "named",
)


def mass_group_params(text: str, quant: str) -> Optional[dict]:
    """``{"group", "group_player"?}`` for a mass verb's "all/each `<group>`" object, or ``None``."""

    group_player = None
    for tail, who in DAMAGE_GROUP_PLAYER_TAILS.items():
        if text.endswith(tail):
            text, group_player = text[: -len(tail)], who
            break
    # The combat-relation tails (`COMBAT_RELATION_TAILS`) name their relation to the source and are read by the
    # count grammar; any *other* use of "blocking"/"blocked" stays refused.
    refusal_text = next((tail.sub("", text) for tail, _ in COMBAT_RELATION_TAILS if tail.search(text)), text)
    if any(word in refusal_text for word in _MASS_GROUP_REFUSED_WORDS):
        return None
    if quant == "each":
        text = SINGULAR_GROUP_HEADS.sub(r"\1s", text)
    # RULE 105.2c: not colorless means at least one of the five colors.
    # Reuse grouped mass effects and the existing color-union filter.
    colored = re.fullmatch(r"(?P<noun>artifacts) that aren't colorless", text)
    group = parse_count_phrase(colored.group("noun") if colored else text)
    if colored and group is not None:
        group = {**group, "filter": {**group.get("filter", {}), "color_any": ["W", "U", "B", "R", "G"]}}
    if group is None or group.get("zone") != "battlefield":
        return None
    params: dict = {"group": group}
    if group_player is not None:
        # The group is that player's own: written `of: "you"`, evaluated for them.
        if group.get("of") != "any":
            return None
        params["group"] = {**group, "of": "you"}
        params["group_player"] = group_player
    return params


#: "Untap this creature" (Devoted Druid's counter-cost untap ability) / "tap
#: ~" — the *self* form, no RULE 115 target at all (`target_kind=None` makes
#: `TapEffect` act on its own source, mirroring `AttachEffect`'s ``~``/"it"
#: self-reference).
SELF_SUBJECT = (
    r"(?:~|it|this permanent|this creature|this artifact|this land|this enchantment)"
)


#: "enchanted creature"/"equipped creature"/"fortified land" — an Aura/
#: Equipment/Fortify's own activated-ability body implicitly acting on
#: whatever it's attached to (RULE 303.4/301.5), no player choice at all
#: (`TapEffect`/`PumpEffect`'s ``"attached_permanent"`` mode) — the
#: activated-ability sibling of `effect_binder._subject_condition`'s
#: ``"attached_permanent"`` *trigger*-subject concept. The same five printed
#: subject phrases `static_handlers._ATTACHED_SUBJECTS` lists — "enchanted
#: permanent"/"enchanted land" appear on real Auras that enchant something
#: other than a creature (Flood the Engine's "When ~ enters, tap enchanted
#: permanent.", Animal Boneyard).
ATTACHED_SUBJECT = (
    r"(?:enchanted creature|equipped creature|fortified land"
    r"|enchanted permanent|enchanted land)"
)


#: "Sacrifice ~ unless you pay `<cost>`." (RULE 701.17 + an "unless"
#: payment) — the single most common upkeep-trigger body on older cards
#: (Arcades Sabboth, Breeding Pit, Child of Gaea, Chromium, Kuro; Aura
#: Flux/Coral Net grant it onto another permanent). Unlike `_sacrifice_self`
#: this is a *choice*: `SacrificeUnlessPayEffect` opens the same
#: pay-or-lose-it `pending_choice` ward uses.
#:
#: The cost is a deliberately **closed** list of shapes rather than free
#: text handed to `costs.parse_activation_cost`, because that function
#: returns a *free* cost for anything it doesn't understand — which here
#: would silently read as "pay nothing to keep it". Every excluded variant
#: is one the engine genuinely can't honour and so stays unclaimed:
#:
#: * "pay its echo cost"/"pay its upkeep cost for each age counter on it" —
#:   Echo and Cumulative Upkeep's own reminder text, a self-referential cost
#:   (and those two keywords aren't modeled at all).
#: * "pay {G} **for each** wind counter on it" (Sandstorm Ambush) — a scaled
#:   cost; `parse_activation_cost` would quietly drop the multiplier.
#: * (PAR-208 lifted: "discard a card at random" and "discard a `<type>` card" are read since ENG-49 and
#:   paid by `_pay_player_cost`; the vetted words are the alternation below.)
#: * "sacrifice **four** creatures" — `ActivationCost.sacrifice` is one
#:   permanent.
#:
#: "discard **N** cards" (a plain count — Avatar of Discord's "discard 2
#: cards", Skull of Orm) *is* included: `parse_activation_cost` reads the
#: count correctly and `_pay_player_cost` honours `cost.discard` as a
#: number.
UNLESS_COST = (
    r"(?:pay (?:\{[^{}]+\})+"
    r"|pay \d+ life"
    # PAR-208: "discard a land card" / "discard a noncreature card" (typed, `ActivationCost.discard_filter`) and
    # "discard a card at random" (`discard_random`), read by `costs.parse_activation_cost` since ENG-49.
    r"|discard an? (?:(?:land|creature|noncreature|artifact|enchantment|instant|sorcery) )?card(?: at random)?"
    r"|discard (?:\d+|two|three|four) cards"
    r"|sacrifice (?:a|another) (?:creature|permanent|artifact|enchantment|land))"
)


#: A graveyard clause's card-*type* word, right before "card" — "target
#: [instant or sorcery/sorcery/nonland permanent/creature/artifact/
#: enchantment/land/permanent] card", or no word at all for a bare "target
#: card" (longest-alternative-first so "nonland permanent" wins over
#: "permanent"; ``sorcery`` alone — MEC-24, Recoup's own "target **sorcery**
#: card" — doesn't need the same ordering care since it starts on a
#: different word than "instant or sorcery").
#: PAR-77: "target **rebel/mercenary permanent** card" (Ramosian
#: Revivalist) — the graveyard-return sibling of PAR-70's own "`<subtype>`
#: permanent card" search qualifier; same fixed enum (Rebel/Mercenary are
#: exclusively creature subtypes in paper Magic, so no separate creature-
#: subtype vocabulary is needed here either). Tried before the bare
#: "permanent" alternative so it isn't swallowed by it.
GRAVEYARD_TYPE_WORD = (
    r"equipment, instant, or sorcery|noncreature, nonland|noncreature|"  # PAR-163 (Thor; Practiced Scrollsmith)
    # PAR-162: the battle unions and the Zombie subtype named on a "put ... on top of your library" card.
    r"instant, sorcery, or battle|creature or planeswalker|creature or battle|zombie|"
    r"instant or sorcery|sorcery|nonland permanent|rebel permanent|"
    r"mercenary permanent|artifact (?:and|or) enchantment|artifact or creature|creature|artifact|"
    r"non-aura enchantment|enchantment|land|permanent"
)
#: A graveyard clause's *scope* — whose graveyard — "your"/"a" (any single
#: graveyard)/"an opponent's" (longest-alternative-first, same reason).
GRAVEYARD_SCOPE_WORD = r"an opponent'?s|your|a"
#: Scope word → `targeting._GRAVEYARD_SCOPE_PREFIXES` key.
_GRAVEYARD_SCOPE_KIND: dict[str, str] = {
    "your": "graveyard", "a": "any_graveyard", "an opponents": "opponent_graveyard",
    "defending players": "defending_graveyard", "that players": "that_player_graveyard",
}


def graveyard_target_kind(type_word: Optional[str], scope_word: str) -> Optional[str]:
    """A graveyard clause's ``(type_word, scope_word)`` → engine
    ``target_kind`` string (`game/targeting.py`'s `_GRAVEYARD_TARGET_KINDS`),
    or ``None`` if either half isn't one of the recognised shapes."""
    scope_key = _GRAVEYARD_SCOPE_KIND.get(re.sub(r"'", "", scope_word.strip().lower()))
    if scope_key is None:
        return None
    type_key = {
        "": "card", "instant or sorcery": "instant_or_sorcery",
        "nonland permanent": "nonland_permanent",
        "non-aura enchantment": "non_aura_enchantment",
        "rebel permanent": "rebel_permanent",
        "mercenary permanent": "mercenary_permanent",
        "artifact and enchantment": "artifact_or_enchantment",
        "artifact or enchantment": "artifact_or_enchantment",
        "artifact or creature": "artifact_or_creature",
        "equipment, instant, or sorcery": "equipment_instant_or_sorcery",
        "noncreature, nonland": "noncreature_nonland",
        "zombie": "zombie_card",
        "creature or battle": "creature_or_battle",
        "creature or planeswalker": "creature_or_planeswalker",
        "instant, sorcery, or battle": "instant_sorcery_or_battle",
    }.get((type_word or "").strip().lower(), (type_word or "").strip().lower() or "card")
    return f"{scope_key}_{type_key}"


#: PAR-167: the targeted graveyard casting window, one grammar over its independent axes -- origin graveyard
#: (yours / an opponent's / any), the card filter (type words, a colour, a mana-value cap that is a literal or
#: "the source's power"), normal versus "without paying its mana cost" (RULE 118.9), a one-resolution
#: permission (RULE 608.2g, no window word) versus a turn-long one ("this turn" / a leading "until end of turn"),
#: and the optional "if that spell would be put into <a> graveyard, exile it instead" rider (RULE 614.1).
#: Every combination lands on `GrantFlashbackToTargetEffect`'s ``as_permission`` mode.
CAST_WINDOW_COLORS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}


# --- RULE 701.14 fight ------------------------------------------------------
# "Target creature you control fights target creature you don't control."
# (Prey Upon), "it fights up to one target creature you don't control."
# (Kogla's ETB), "when this Aura enters, enchanted creature fights …" — one
# `fight` effect (`game/effects/core.py`'s `FightEffect`) in all three, differing
# only in who the *fighter* is.

#: The target kinds a fight clause may name. Both fighters must be creatures
#: (RULE 701.14a), so a `TARGET` row resolving to anything else — "any
#: target", "target permanent" — leaves the clause unclaimed rather than
#: widening the fight to a non-creature.
_FIGHT_TARGET_KINDS: frozenset[str] = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control"}
)

#: The second requirement's `TARGET`, group-renamed so both fit one regex.
TARGET_B = target_macro("_b")


def fight_kind(phrase: str) -> Optional[str]:
    kind = resolve_target_kind(phrase)
    return kind if target_kind_allowed(kind, _FIGHT_TARGET_KINDS) else None


#: "you may **have** it fight …" — `peel_optional` strips the "you may",
#: leaving the causative "have <subject> fight" (uninflected verb), so both
#: inflections are accepted in one row. A leading "then " survives the
#: segmenter's split on ". " (its own "then" connector only strips the
#: comma-less mid-sentence form), so every pronoun row tolerates it.
THEN = r"(?:then )?"
#: The pronouns a later clause uses for the creature an earlier one chose.
PREVIOUS_SUBJECT = r"(?:it|that creature|the chosen creature)"


def token_keywords(text: str) -> Optional[list[str]]:
    """Validate a token's "with <keywords>" clause → flag-keyword slugs, or None.

    Fail-closed: if any listed ability isn't a parameterless (flag) keyword, the
    whole token clause is left unclaimed rather than dropping the ability
    (a token that silently lacks "flying" would be a wrong game state). The
    one parametric exception is a *bare* "hexproof" — RULE 702.11b's
    QUALITY shape (PAR-5) exists for the scoped "hexproof from <colour>"
    variant, but plain "hexproof" with no "from" is still its own complete,
    unscoped keyword (the shape it had before PAR-5), so it's granted here
    exactly like a FLAG keyword. A scoped "hexproof from black" never
    reaches this branch: `keyword_slug` only resolves the bare "hexproof"/
    "hexproof from" spellings, so a real quality suffix keeps `kdef` ``None``
    and still fails closed below. A landwalk variant ("forestwalk") is the
    same kind of exception, same reasoning as `static_handlers._flag_
    keywords`' own — RULE 702.14's land type lives in the slug itself, so
    the grant needs no separate quality param.
    """
    slugs: list[str] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        slug = grantable_flag_slug(part)
        if slug is None:
            return None
        slugs.append(slug)
    return slugs


#: A closed vocabulary of the popular colourless "named" artifact tokens
#: (no inline P/T, no "creature" word — Treasure/Clue/Food-shaped) that
#: `services/token_database.py`'s `data/tokens.json` actually defines with
#: their own real abilities (a Treasure's mana ability, a Clue's sacrifice-
#: to-draw, a Food's sacrifice-to-gain-life, a Blood's discard-and-draw).
#: Deliberately **not** every name real cards print (Map/Gold/Incubator/
#: Powerstone aren't in that JSON yet) — claiming one of those here would silently synthesize a
#: blank token missing its real ability (`CreateTokenEffect.apply`'s
#: fallback), the exact half-resolved outcome docs/09's fail-closed
#: discipline forbids. Keep this dict in sync with `data/tokens.json`
#: whenever a new named token is added there.
NAMED_TOKEN_WORDS: dict[str, str] = {
    "treasure": "Treasure", "clue": "Clue", "food": "Food", "blood": "Blood", "mutagen": "Mutagen",
    "powerstone": "Powerstone", "lander": "Lander", "junk": "Junk",
}


def signed_int(token: str) -> int:
    """A signed integer literal, tolerating the unicode minus ``−`` (U+2212)."""
    return int(token.replace("−", "-"))


def counter_sign(token: str) -> str:
    """"+1/+1" (default) or "-1/-1" from a captured counter-kind sign, tolerating
    the unicode minus ``−`` (U+2212) — both shift net P/T through the same
    machinery (RULE 122)."""
    return "-1/-1" if token.lstrip()[0] in "-−" else "+1/+1"


#: RULE 122.1's *named* (non-P/T) counter kinds: the plain "put a `<kind>` counter on X"
#: shape and every row that shares its kind vocabulary. `AddCountersEffect.kind` is a free
#: string (RULE 122.1a — any permanent, any named counter type), so a pure card-text tracker
#: ("spore", "feather", "bloodstain") needs no engine change and **the kind is an open axis**
#: (PAR-135) — a closed list of the tracker words printed so far kept missing the next set's.
#:
#: What is *not* open is the small set whose name the engine itself keys off, where a generic
#: `obj.counters[kind]` bump would half-model: the subsystem counters (`age` cumulative upkeep, `fade` fading, `level` leveler, `loyalty` planeswalker,
#: `lore` Saga, `defense` battle), the player counters (`rad`, `energy`, `experience`,
#: `poison`) and the RULE 122.1b keyword counters no layer reader exists for (`decayed`,
#: `exalted`). `stun` (RULE 122.1c, `set_tapped`) and `shield` (RULE 122.1c,
#: `deal_damage`/`destroy`) carry replacement effects, and both are engine-enforced now, so
#: they are ordinary members. `time` also uses the shared counter primitive now that
#: actual removals notify exile abilities and Suspend's separate cast trigger. A test (`test_par135_named_counters.py`) scans `game/` for
#: counter-kind literals so a *new* reader can't slip in unreserved.
RESERVED_COUNTER_KINDS: tuple[str, ...] = (
    "age", "fade", "level", "loyalty", "lore", "defense",
    "rad", "energy", "experience", "poison", "decayed", "exalted", "finality", "ticket",
)
#: Multi-word RULE 122.1b keyword kinds first, so "first strike" isn't read as kind "first".
NAMED_COUNTER_KIND = (
    rf"(?!(?:{'|'.join(RESERVED_COUNTER_KINDS)})\b)"
    rf"(?:{'|'.join(sorted(KEYWORD_COUNTER_KINDS, key=len, reverse=True))}|[a-z]+)"
)


def pump_target(m: re.Match[str]) -> Optional[tuple[Optional[str], Optional[str]]]:
    """The pump's ``(target_kind, selector)`` — or ``None`` to signal fail-closed.

    Exactly one of the pair is set for a targeted or group subject; both are
    ``None`` for a self-pump ("~ gets …", untargeted single object) so the
    caller can tell it apart from an unrecognised target (real ``None``
    overall).
    """
    groupdict = m.groupdict()
    if groupdict.get("selfref"):
        return (None, None)  # untargeted self-pump (an activated "~ gets +1/+0 …")
    if groupdict.get("group"):
        selector = _group_selector(re.sub(r"'", "", groupdict["group"]))
        return None if selector is None else (None, selector)
    if groupdict.get("attached"):
        return ("attached_permanent", None)  # "enchanted creature gains …" (Aura activated ability)
    kind = resolve_target_kind(m.group("target"))
    # The controller-scoped creature kinds are as pumpable as a bare
    # "target creature" — `targeting.legal_targets` resolves them all, and a
    # pump doesn't care *whose* creature it lands on (`other_creature_you_
    # control` is RULE 109.5 "another target creature you control", source
    # excluded). Anything else (a player, a spell) has no P/T to modify, so
    # it stays fail-closed.
    if not target_kind_allowed(kind, (
        "creature", "permanent", "creature_you_control", "creature_you_dont_control",
        "other_creature_you_control", "attacking_or_blocking_creature",
    )):
        return None
    return (kind, None)


def pump_target_creature_filter(m: re.Match[str]) -> Optional[dict]:
    """The RULE 508/509 board-state qualifier (attacking/blocking/tapped/
    untapped) `_pump_target`'s own ``(target_kind, selector)`` pair
    discards — see `subgrammars.resolve_target_creature_state_filter` and
    `_destroy`'s own comment on the same fix. Every `_pump_target(m)` caller
    that threads its ``target_kind`` straight into an `EffectSpec` should
    also merge this into its own ``creature_filter``, or "target tapped
    creature gets -1/-1" (etc.) silently pumps *any* creature. A no-op for
    every match whose ``target`` group didn't come from a qualified phrase
    (``None`` — most callers).
    """
    target_text = m.groupdict().get("target")
    if not target_text:
        return None
    return resolve_target_creature_state_filter(target_text)


#: "Creatures **target player controls** get -2/-2 until end of turn" — the group scoped to the player the spell
#: targets (`PumpEffect.group_player`): written for "you", evaluated for that player.
_TARGET_PLAYER_GROUP_RE = re.compile(r"creatures target (player|opponent) controls")


def pump_(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    scoped = _TARGET_PLAYER_GROUP_RE.fullmatch(m.groupdict().get("group") or "")
    subject = (None, {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}}) if scoped else (
        pump_target(m))
    if subject is None:
        return None
    target_kind, selector = subject
    params: dict = {
        "power": signed_int(m.group("p")),
        "toughness": signed_int(m.group("t")),
    }
    if scoped:
        params["group_player"] = scoped.group(1)
    keywords: list[str] = []
    parametric: list[dict[str, object]] = []
    if m.groupdict().get("kw"):
        # PAR-102: "gains flying and toxic 1" — a grantable parametric keyword rides beside the flags.
        split = split_keywords_with_parametric(m.group("kw"))
        if split is None:
            return None  # unmodeled granted ability → fail-closed
        keywords.extend(split[0])
        parametric.extend(split[1])
    if m.groupdict().get("must_blocked"):
        # PAR-124: "…until end of turn and must be blocked this turn if
        # able." (Compelled Duel/Emergent Growth/Joraga Invocation) — a
        # plain flag keyword (RULE 509.1c), same as any other granted one.
        keywords.append("must_be_blocked")
    if keywords:
        params["keywords"] = keywords
    if parametric:
        params["parametric_keywords"] = parametric
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = {**(params.get("creature_filter") or {}), **state_filter}
    return [EffectSpec("pump", params)]


def temporary_keyword_change(
    m: re.Match[str], *, previous_referent: bool = False,
) -> Optional[list[EffectSpec]]:
    """Layer-6 keyword gains/removals that last until cleanup (MEC-105).

    A single ``pump`` spec carries both halves so a compound "gains X and
    loses Y" sentence chooses/resolves its recipient only once. The same
    effect already owns targeted, self, group and previous-subject routing;
    ``removed_keywords`` is its ability-removing mirror of ``keywords``.
    """
    params: dict = {}
    if m.groupdict().get("p") is not None:
        params["power"] = signed_int(m.group("p"))
        params["toughness"] = signed_int(m.group("t"))
    if m.groupdict().get("kw"):
        keywords = token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    removed = token_keywords(m.group("lost"))
    if removed is None:
        return None
    params["removed_keywords"] = removed
    if previous_referent:
        params["previous_subject"] = True
        return [EffectSpec("pump", params)]
    subject = pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    state_filter = pump_target_creature_filter(m)
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("pump", params)]


#: PAR-150: the plural ("up to N target ...") forms of gain control / goad / counter / keyword grants -- each
#: opts the effect into the shared `_MULTI_TARGET_QUANTIFIER`/`_multi_target_params` machinery destroy, tap and
#: return already use. The effect classes read the count as `target_count` (pump, gain control, counter) or
#: `count` (goad), the keys each factory in `EffectRegistry` already names.
def renamed_target_count(params: dict) -> dict:
    """``_multi_target_params``' ``count``/``count_max`` -> the ``target_count``/``target_count_max`` keys of the
    pump/gain-control/counter factories (a bare ``count`` there is an amount, not a target count)."""
    out = {k: v for k, v in params.items() if k not in ("count", "count_max")}
    out["target_count"] = params["count"]
    if "count_max" in params:
        out["target_count_max"] = params["count_max"]
    return out


# A pump's subject: a targeted creature/permanent, the self-reference ``~``
# (a creature's own activated "~ gets +1/+0 …"), or an untargeted *group*
# ("creatures you control get +2/+1 …" — RULE 601.2c, not a target at all;
# the common Saga-chapter/anthem-spell shape, or the board-wide "all
# creatures get -N/-N until end of turn" mass-removal shape, Infest/Blight
# Grenade-shaped). Shared by the pump handlers.
#: PAR-13's own two additions — "creatures your opponents control"/
#: "creatures you don't control" (Mouth of the Storm/Behold the
#: Unspeakable-shaped mass debuffs) — both the same `continuous.
#: group_selector_objects` selector as each other (every creature not
#: yours, the plain-English reading of either phrasing).
_GROUP = (
    r"(?P<group>other creatures you control"
    # PAR-128: the unscoped "other" (RULE 109.5) — Shefet Archfiend's "all other
    # creatures", Honored Crop-Captain's "other attacking creatures"; the
    # count-phrase grammar already reads "other" as ``not_reference``.
    r"|all other creatures|other attacking creatures"
    # "Each creature you control with a counter on it gains firebending N …"
    # (Iroh, Dragon of the West) — a counter-presence filter on the
    # controller-scoped creature set; tried before the bare
    # "each creature you control" alternative below.
    r"|each creature you control with a counter on it"
    # PAR-74: "each other creature you control gets …" (Kodama of the South
    # Tree) — the distributive-singular phrasing of "other creatures you
    # control" just above, same `other_creatures_you_control` selector, the
    # same relationship "each creature you control" already has to
    # "creatures you control". Tried before the bare "each creature you
    # control" row below so "other" isn't swallowed by it.
    r"|each other creature you control"
    r"|each other creature"
    r"|each creature you control"
    # "all creatures you control gain deathtouch until end of turn" (Venom
    # Connoisseur) — the same group as "creatures you control", with the
    # emphatic "all"; tried before the unscoped "all creatures" below.
    r"|all creatures you control"
    r"|creatures you control|all creatures"
    r"|creatures your opponents control|creatures you don'?t control|permanents your opponents control"
    r"|creatures target (?:player|opponent) controls"
    r"|permanents you control|elves you control|elf creatures you control"
    # PAR-109: "Dragons you control get +1/+0 until end of turn" (Lathliss, Ran and Shaw) — any plural subtype
    # or "<adjective> creatures" group; `_group_selector` (the count-phrase grammar) fails closed on a word that
    # is none of its vocabulary.
    r"|other [a-z]+s you control|[a-z]+ creatures you control|[a-z]+s you control"
    # PAR-203: the controller-less subtype/colour/negated groups ("all Elf creatures get -1/-1", "non-Elf creatures get
    # -3/-3" -- the shapes a "choose a creature type" body reads as once the chosen type is substituted); the count-phrase
    # grammar still decides whether the words are a real group, so an unknown word fails closed in `_group_selector`.
    r"|non-[a-z]+ creatures|all non-[a-z]+ creatures|all [a-z]+ creatures|[a-z]+ creatures"
    # PAR-19: "Attacking creatures get -3/-0 until end of turn." (Lethargy
    # Trap-shaped) — unscoped by controller, the same `group_selector_
    # objects` "attacking_creatures" branch Motivated Pony's anthem and
    # `TapEffect.selector` (MEC-28) already reuse.
    r"|attacking creatures)"
)
SUBJECT = (
    rf"(?:{TARGET}|(?P<selfref>{re.escape(SELF)})|{_GROUP}|(?P<attached>{ATTACHED_SUBJECT}))"
)
#: A matched ``group`` phrase → its `continuous.group_selector_objects`
#: selector, for the phrases `parse_count_phrase` doesn't reach (checked
#: individually, not assumed — PAR-120, PARSER_VERSION 474): "other"/"each
#: other" (`not_reference` isn't reachable through this entry point —
#: confirmed directly, the same gap found retiring `_CONTROL_COUNT_
#: SELECTORS`/`_SELF_ANTHEM_FOR_EACH_SELECTORS`), "all creatures" (no "you
#: control"/"in your graveyard" tail for the grammar to anchor on), and the
#: negated "you don't control" phrasing (the grammar has no negation
#: reading — RULE-equivalent to "your opponents control", already covered,
#: but not worth building an alias mechanism for the one phrase that needs
#: it). "Each creature you control **with a counter on it**" turned out to
#: already be covered too (the grammar's own `has_counter` filter key,
#: proven equivalent to the old `creatures_you_control_with_a_counter`
#: string on a real board) — no residual entry needed for it at all.
_GROUP_SELECTORS: dict[str, "str | dict"] = {
    "other creatures you control": "other_creatures_you_control",
    "each other creature you control": "other_creatures_you_control",
    "all creatures": "all_creatures",
    "creatures you dont control": "creatures_opponents_control",
    # PAR-128: the unscoped "each other creature" (singular, so `parse_count_phrase`
    # can't read it) — every creature but the effect's source.
    "each other creature": {
        "zone": "battlefield", "of": "any",
        "filter": {"card_type": "creature", "not_reference": True},
    },
}


def _group_selector(phrase: str) -> "Optional[str | dict]":
    """A matched ``group`` phrase (`_GROUP`) → a `group_selector_objects`
    argument, structured or named. Tried before the residual table above;
    "each `<X>`" is the distributive-singular of plain "`<X>`" ("each
    creature you control gains …" reads the identical group as "creatures
    you control" — Avacyn/Griselbrand), so it's retried with that prefix
    stripped — but only a bare "each ", never "each other ", since that
    "other" is a real exclusion the grammar doesn't express (residual
    table, above).
    """

    structured = parse_count_phrase(phrase)
    if structured is not None:
        return structured
    if phrase.startswith("each ") and not phrase.startswith("each other "):
        structured = parse_count_phrase(phrase[len("each "):])
        if structured is not None:
            return structured
    if phrase == "all other creatures":
        return parse_count_phrase(phrase[len("all "):])
    if phrase == "all creatures you control":
        # The emphatic "all" names the same group; bare "all creatures" (no
        # controller tail) stays the residual table's unscoped selector.
        return parse_count_phrase(phrase[len("all "):])
    if phrase.startswith("all ") and phrase != "all creatures":
        # PAR-203: "all Elf creatures" / "all non-Elf creatures" -- the emphatic "all" again.
        return parse_count_phrase(phrase[len("all "):])
    return _GROUP_SELECTORS.get(phrase)
#: A signed P/T delta, "+3/+3" / "-2/-2" / "+0/-1" (ASCII or unicode minus).
PT_DELTA = r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"


DELAYED_TAIL_INNER = {
    "sacrifice": "sacrifice_specific",
    "exile": "exile_specific",
    "destroy": "destroy_specific",  # Old Hob, Alleycat Blues
    "return": "return_specific_to_hand",  # Ilharg, Zara, Alora
}


#: PAR-30: the singular-pronoun sibling of `_PUMP_PREVIOUS_TARGETS_*_RE` —
#: "it [also] gets +N/+N [and gains `<kw>`] until end of turn" / "it [also]
#: gains `<kw>` until end of turn", where "it"/"that creature"/"that
#: permanent" is the single RULE 115 target the preceding split clause chose
#: (`GameContext.previous_targets`, `PumpEffect.previous_subject`). Real
#: cards run this off a threaten clause's own restatement tail ("gain
#: control of target creature until end of turn. untap that creature. **it**
#: gains haste …") when a further sentence keeps `segmenter.
#: _GAIN_CONTROL_HASTE_TAIL_RE` from absorbing the pair whole, and off clash
#: "if you win, **that creature** gets +2/+2 …" payoffs (RULE 701.30d).
#: Gated `previous_subject_only`, so it only competes once the preceding
#: clause actually bound the pronoun.
PREV_SUBJECT_SINGULAR = r"(?:it|that creature|that permanent|that artifact|that token|the token)"

#: PAR-79 sixth increment: "…except by N or more creatures" (Unquenchable
#: Fury) — a blocker-*count* requirement (RULE 509.1c), not a characteristic
#: filter, so it routes to `combat.min_blockers` (the same ``"min_blockers"``
#: restriction kind `static_handlers._TAIL_RES` already uses for the
#: standing-static "can't be blocked except by N or more creatures" form)
#: rather than through `object_filter` — which would otherwise mis-read "2"
#: as a bogus subtype word before `_scope`'s own digit guard (PAR-79 third
#: increment) correctly failed it closed. Checked before the general filter
#: route in `_cant_be_blocked_turn` below.
_CANT_BE_BLOCKED_TURN_MIN_BLOCKERS_RE = re.compile(
    r"^(?P<n>\d+) or more creatures\.?$", re.IGNORECASE
)


def except_by_restriction(text: str) -> Optional[dict]:
    """The RULE 509.1b restriction dict for an "…except by `<filter>`" tail:
    a blocker-count requirement (RULE 509.1c) or a permitted-blocker filter."""
    min_blockers = _CANT_BE_BLOCKED_TURN_MIN_BLOCKERS_RE.fullmatch(text.strip())
    if min_blockers is not None:
        return {"kind": "min_blockers", "count": int(min_blockers.group("n"))}

    filt = object_filter(text)
    if filt is None:
        return None
    return {"kind": "only_blocked_by", "filter": filt}
#: PAR-141/142: the body after the verb — "a `<N/N>` `<subtype/type words>` [with `<keywords>`] in
#: addition to its other types [and gains `<keyword>`] [until end of turn]" (Archangel Elspeth's "and gains
#: flying", Answered Prayers' "a 3/3 Angel creature with flying", Call a Surprise Witness' "it's a Spirit").
#: Keywords come through the same vocabulary the "with `<keyword>`" tails read. A base P/T needs the word
#: "creature" (a non-creature has none) and rides the same layer-4 static, exactly as the animate rows do.
BIA_KEYWORD = "|".join(sorted(CREATURE_FILTER_KEYWORD_WORDS, key=len, reverse=True))
BIA_KEYWORD_LIST = rf"(?:{BIA_KEYWORD})(?:(?:, and |, | and )(?:{BIA_KEYWORD}))*"


# --- The table --------------------------------------------------------------
# ORDER IS SEMANTICS: a clause is claimed by the first eligible handler whose full-clause regex matches, and the
# IR that handler builds is the clause's IR. Every pattern is anchored to the whole clause by
# `EffectHandler.match`'s `fullmatch`, so no partial claims. Two rows may claim one clause with different IR only
# in two declared ways (`tests/test_par169_handler_shadowing.py` re-measures every clause the full card cache
# hands this table and fails on any other pair):
#   * a context-gated row (``self_subject_only`` &c.) comes before the ungated row for the same words: the
#     context's reading of a pronoun overrides the default one;
#   * the older, narrower-vocabulary row is a declared ``fallback_for`` the generalized row (the shared group /
#     count / window grammars): it comes after the primary and only keeps what the primary declines.
# Put a new generalized row *before* the rows it generalizes and declare them fallbacks, or retire them.
# Rows of a `_subject_handlers` table declare every subject reading of one verb at once (PAR-121), so a reading
# no pool card prints yet is kept as part of that one declaration.

#: PAR-121: the subject-scope slot of a verb. A clause whose subject is a bare pronoun ("it"/"that creature") means
#: a different object under each kind of ability — the source (``self``), an earlier clause's pick (``previous``),
#: the creature a group trigger fired for (``group``), an Aura/Equipment's host (``attached``) — and
#: `EffectHandler` gates each reading with its own `requires`. A verb used to register one near-identical row per
#: reading; `_subject_handlers` declares it once: ``(row name, subject, regex, builder)`` per reading.
_SUBJECT_REQUIRES: dict[str, ClauseReading] = {
    "any": STANDALONE,
    "self": ClauseReading(self_subject=True),
    "previous": ClauseReading(previous_subject=True),
    "group": ClauseReading(group_subject=True),
    "attached": ClauseReading(attached_subject=True),
}


def subject_handlers(
    rows: "list[tuple[str, str, re.Pattern[str], Callable[[re.Match[str]], Optional[list[EffectSpec]]]]]",
) -> list[EffectHandler]:
    return [EffectHandler(name, regex, build, requires=_SUBJECT_REQUIRES[subject]) for name, subject, regex, build in rows]


#: "that creature's controller" / "that land's power" — under a group trigger the same possessive
#: as "its", so every "its …" row serves both spellings.
_THAT_OBJECTS_POSSESSIVE_RE = re.compile(rf"\bthat {PRONOUN_NOUN_ALT}'s\b")

#: "that hero" / "that sliver" — a creature subtype naming the firing object.
_THAT_SUBTYPE_RE = re.compile(rf"\bthat (?!creature\b|permanent\b|artifact\b|land\b|token\b){PRONOUN_NOUN_ALT}\b")

_THAT_CREATURE_RE = re.compile(r"\bthat creature\b")

#: "…target creature you control **other than that creature**" — the group trigger's firing object.
_OTHER_THAN_THAT_RE = re.compile(rf"\s+other than (?:it|that {PRONOUN_NOUN_ALT})$")

#: A plural referent ("put a counter on each of **those** creatures") names a group, which the
#: one object a group trigger fired for cannot stand for.
_PLURAL_PRONOUN_RE = re.compile(r"\b(?:those|them|they|these|each of)\b")


def match_clause_reading(
    clause: str, *, reading: ClauseReading,
) -> Optional[list[EffectSpec]]:
    other_than = _OTHER_THAN_THAT_RE.search(clause) if reading.group_subject else None
    if other_than is not None:
        # "put a +1/+1 counter on target creature you control **other than that creature**": the
        # firing object is excluded from the choice, whatever verb the clause has.
        effects = match_clause_reading(
            clause[:other_than.start()], reading=reading,
        )
        if effects is None or not any(e.params.get("target_kind") for e in effects):
            return None
        return [
            EffectSpec(e.type, {**e.params, "excluding_trigger_subject": True}, condition=e.condition)
            if e.params.get("target_kind") else e
            for e in effects
        ]
    if reading.group_subject and _THAT_CREATURE_RE.search(clause) is None:
        # "that hero"/"that sliver" under a group trigger for that subtype is "that creature" —
        # unless the clause also says "that creature", which would then be a *second* object
        # ("that archer deals that much damage to that creature's controller").
        clause = _THAT_SUBTYPE_RE.sub("that creature", clause)
    effects = match_clause_once(clause, reading=reading)
    if effects is None and reading.group_subject and _THAT_OBJECTS_POSSESSIVE_RE.search(clause):
        clause = _THAT_OBJECTS_POSSESSIVE_RE.sub("its", clause)
        effects = match_clause_once(clause, reading=reading.only(group_subject=True))
    if effects is None and reading.group_subject and not reading.previous_subject and _PLURAL_PRONOUN_RE.search(clause) is None:
        effects = match_clause_once(clause, reading=reading.only(previous_subject=True))
        if effects is not None:
            return [EffectSpec("trigger_subject_referent", {"event_key": GROUP_SUBJECT_KEY_SENTINEL}), *effects]
        return group_pronoun_as_target(clause, reading) or _group_controller_as_you(clause, reading)
    return effects


#: The object pronoun of a group-trigger clause ("destroy **it**", "put a counter on **that
#: creature**") — not the possessive "its"/"it's".
_OBJECT_PRONOUN_RE = re.compile(rf"\b(?:it|that {PRONOUN_NOUN_ALT})\b(?!')")


#: Nested effect bodies that hand their ``targets`` on to what they contain. Any other body
#: (a payment's "if you do", a "you may", a delayed trigger) runs later or elsewhere, without
#: the firing object the wrapper supplies.
_TARGET_PASSING_NODES = frozenset({"bind", "seq", "if_else"})


def _runs_against_targets(spec: Any) -> bool:
    """Whether every effect nested in ``spec`` is run with the ``targets`` its parent got."""
    if isinstance(spec, dict):
        nested = isinstance(spec.get("type"), str) and "params" in spec
        if nested and any(_has_nested_spec(v) for v in spec["params"].values()) and (
            spec["type"] not in _TARGET_PASSING_NODES
        ):
            return False
        return all(_runs_against_targets(v) for v in spec.values())
    if isinstance(spec, list):
        return all(_runs_against_targets(v) for v in spec)
    return True


def _has_nested_spec(value: Any) -> bool:
    if isinstance(value, dict):
        return (isinstance(value.get("type"), str) and "params" in value) or any(
            _has_nested_spec(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_nested_spec(v) for v in value)
    return False


#: "**its controller**" / "**that creature's controller**" — the player who controls the object a
#: group trigger fired for — with the verb that follows it, if any.
_CONTROLLER_PRONOUN_RE = re.compile(
    rf"\b(?:its|that {PRONOUN_NOUN_ALT}'s) controller(?P<poss>'s)?(?: (?P<verb>[a-z]+))?"
)

#: Third-person verbs that do not just drop their "s"/"es" to reach the base form.
_IRREGULAR_BASE_VERBS = {"has": "have", "does": "do"}


def base_verb(word: str) -> str:
    if word in _IRREGULAR_BASE_VERBS:
        return _IRREGULAR_BASE_VERBS[word]
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    return word[:-1] if word.endswith("s") else word


#: The effect types that read "you" through `GameContext.acting_player_id` (`_controller_of`,
#: `effect_conditions._controller_id`, or directly), each pinned by `test_par123_referent.py`. An
#: effect that resolves "you" some other way would quietly act for the wrong player, so the rewrite
#: is offered only for these.
_ACTING_AS_CONTROLLER_TYPES: frozenset[str] = frozenset({
    "damage", "create_token", "tap", "add_player_counters", "draw", "lose_life", "gain_life",
})


def _group_controller_as_you(clause: str, reading: ClauseReading) -> Optional[list[EffectSpec]]:
    """PAR-123: "its controller creates a 1/1 Snake token" is "you create a 1/1 Snake token"
    done by the firing object's controller (RULE 109.5). The clause is read as its second-person
    form and run acting as that player (`trigger_subject_referent` ``acting``), so every effect
    with a "you" reading gains the "its controller" one — creating, sacrificing, drawing, tapping
    "lands you control" — without a row of its own.

    Refused when the clause names another player or carries a second pronoun (the two would
    need to be told apart), and when the effect would run later than this resolution."""
    found = list(_CONTROLLER_PRONOUN_RE.finditer(clause))
    if len(found) != 1 or _OBJECT_PRONOUN_RE.search(clause) or re.search(r"\b(?:you|your|target)\b", clause):
        return None
    hit = found[0]
    verb = hit.group("verb")
    if hit.group("poss"):
        replacement = "your" + (f" {verb}" if verb else "")
    elif verb == "may":
        replacement = "you may"
    elif verb:
        replacement = f"you {base_verb(verb)}"
    else:
        replacement = "you"
    rewritten = clause[:hit.start()] + replacement + clause[hit.end():]
    rewritten = re.sub(r"\bof their choice\b", "of your choice", rewritten)
    rewritten = re.sub(r"\btheir\b", "your", rewritten)
    effects = match_clause_once(rewritten, reading=reading.only())
    if (
        effects is None or not all(_runs_against_targets(e.to_dict()) for e in effects)
        or not all(e.type in _ACTING_AS_CONTROLLER_TYPES for e in effects)
    ):
        return None
    return [EffectSpec("trigger_subject_referent", {
        "event_key": GROUP_SUBJECT_KEY_SENTINEL, "acting": "controller",
        "effects": [e.to_dict() for e in effects],
    })]


def group_pronoun_as_target(clause: str, reading: ClauseReading) -> Optional[list[EffectSpec]]:
    """PAR-123: a group trigger's bare "it"/"that creature" read through the *targeted* form of
    the same clause. "destroy it" is "destroy target permanent" whose one target the trigger
    already fixed, so any effect that has a targeted row gains the firing-object reading with no
    row of its own: the clause is parsed with the pronoun spelled as a target, and the result
    runs against the firing object (`trigger_subject_referent`'s body) instead of a chosen one.

    Refused unless the pronoun is the clause's *only* possible target — a second "target"
    ("it fights target creature you don't control") would be hidden by the wrapper, which
    announces none — and only for the creature/permanent spellings, the objects a group
    trigger fires for."""
    pronouns = _OBJECT_PRONOUN_RE.findall(clause)
    if len(pronouns) != 1 or "target" in clause:
        return None
    noun = re.match(r"that (creature|permanent|artifact|land|token)$", pronouns[0])
    # A creature that died is a card in a graveyard by the time the trigger resolves (RULE 603.10a).
    for kind in dict.fromkeys(
        ((noun.group(1) if noun else "creature"), "creature", "permanent", "card from a graveyard")
    ):
        rewritten = _OBJECT_PRONOUN_RE.sub(f"target {kind}", clause)
        effects = match_clause_once(rewritten, reading=reading.only())
        if effects is not None and all(_runs_against_targets(e.to_dict()) for e in effects):
            return [EffectSpec("trigger_subject_referent", {
                "event_key": GROUP_SUBJECT_KEY_SENTINEL,
                "effects": [e.to_dict() for e in effects],
            })]
    return None
