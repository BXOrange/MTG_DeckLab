"""Static-ability helpers: rows player rules (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from dataclasses import replace
from ..casting_window import parse_linked_play
from ..library_permission import parse_graveyard_cast_permission, parse_top_library_permission
from ...spec import EffectSpec
from .anthem_patterns import CARD_TYPE_WORDS
from .object_scope import group_selector, scoped_group_selector, singularize
from .combat_restrictions import ATTACHED_ABILITY_LOSS_RE, NO_UNTAP_ATTACHED_RE, color_statement_specs
from .cost_patterns import (
    ALL_ENTER_TAPPED_RE,
    BASIC_LAND_WORDS,
    GRAVEYARD_LAND_PLAY_PERMISSION_RE,
    GRAVEYARD_LIBRARY_CAST_PROHIBITION_RE,
    GRAVEYARD_LIBRARY_ENTRY_PROHIBITION_RE,
    HAND_SIZE_MODIFIER_RE,
    HAND_SIZE_SET_RE,
    HAND_SIZE_SUBJECT_AFFECTS,
    LAND_IS_BASIC_TYPE_RE,
    LOOK_AT_TOP_ANY_TIME_RE,
    NOT_A_CREATURE_RE,
    NO_MAX_HAND_SIZE_RE,
    NO_UNTAP_GROUP_POWER_RE,
    NO_UNTAP_NONBASIC_LANDS_RE,
    NO_UNTAP_OPTIONAL_RE,
    NO_UNTAP_RE,
    OPPONENTS_ENTER_TAPPED_RE,
    PLAYERS_CANT_GAIN_LIFE_RE,
    RADIATION_LIFE_GAIN_RE,
    SKIP_UNTAP_STEPS_RE,
    SKIP_YOUR_STEP_RE,
    TOP_LIBRARY_PERMISSION_RE,
    TOP_LIBRARY_TAILS,
    TOP_LIBRARY_VERB_PARAMS,
    TRIGGER_PROHIBITION_RE,
    TYPE_OVERWRITE_RE,
    UNTAP_CAP_RE,
)
from .static_conditions import static_condition
from .matcher_types import DECLINE, StaticContext, StaticResult, claim
from .rows_attached import static_attached_anthem

# RULE 704.5j: "The "legend rule" doesn't apply to permanents you control." (Sakashima of a Thousand Faces,
# Mirror Gallery-shaped). Only the whole-board form: the engine's `ignore_legend_rule` exempts every permanent of the
# controller, so the narrower scopes ("creature tokens you control", "this turn") stay unclaimed rather than widened.
_IGNORE_LEGEND_RULE_RE = re.compile(r"the \"legend rule\" doesn't apply to permanents you control", re.IGNORECASE)


def static_ignore_legend_rule(ctx: StaticContext) -> StaticResult:
    if _IGNORE_LEGEND_RULE_RE.fullmatch(ctx.text.strip().rstrip(".")):
        return [EffectSpec("ignore_legend_rule", {"affects": "you"})]
    return None


#: PAR-284 milestone 23 / RULE 704.5a, 104.3b: "You don't lose the game for having 0 or less life." (Lich's Tomb,
#: Transcendence) -- the life-only exemption of `cant_lose_game` (``reason: life``): the state-based action that would end
#: the game for 0 life is skipped, but every other loss still applies (`continuous.player_cant_lose`). Only the bare
#: whole-sentence form; "as long as ~ is attached ..." and combined sentences stay with their own cards.
_NO_LOSS_FOR_LIFE_RE = re.compile(r"you don't lose the game for having 0 or less life", re.IGNORECASE)
CANT_LOSE_FOR_LIFE_REASON = "life"


def static_cant_lose_for_life(ctx: StaticContext) -> StaticResult:
    if _NO_LOSS_FOR_LIFE_RE.fullmatch(ctx.text.strip().rstrip(".")):
        return [EffectSpec("cant_lose_game", {"reason": CANT_LOSE_FOR_LIFE_REASON})]
    return None


def static_no_max_hand_size(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = NO_MAX_HAND_SIZE_RE.fullmatch(text)
    if m is not None:
        affects = "each_player" if m.group("subject").lower() == "players have" else "you"
        return [EffectSpec("no_max_hand_size", {"affects": affects})]
    return None


def static_color_statement_specs(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    color_specs = color_statement_specs(text)
    if color_specs is not None:
        return claim(color_specs)
    return None


def static_hand_size_modifier(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = HAND_SIZE_MODIFIER_RE.fullmatch(text)
    if m is not None:
        params = {"affects": HAND_SIZE_SUBJECT_AFFECTS[m.group("subject").lower()], "amount": int(m.group("n"))}
        if m.group("direction").lower() == "increased":
            params["increase"] = True
        return [EffectSpec("hand_size_modifier", params)]
    m = HAND_SIZE_SET_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("hand_size_set", {"affects": "you", "amount": int(m.group("n"))})]
    return None


def static_skip_untap_steps(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if SKIP_UNTAP_STEPS_RE.fullmatch(text):
        return [EffectSpec("skip_untap_step", {})]
    return None


def static_players_cant_draw(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if re.fullmatch(r"players can't draw cards(?: or gain life)?", text):
        effects = [EffectSpec("draw_limit", {"max_per_turn": 0})]
        if text.endswith(" or gain life"):
            effects.append(EffectSpec("prevent_all_life_gain", {}))
        return claim(effects)
    return None


def static_players_cant_gain_life(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = PLAYERS_CANT_GAIN_LIFE_RE.fullmatch(text)
    if m is not None:
        params = {"scope": "opponents"} if (m.group("scope") or "").lower() == "your opponents" else {}
        return [EffectSpec("prevent_all_life_gain", params)]
    return None


#: PAR-216, RULE 615.12: the scoped forms of "damage can't be prevented" -- the damage source named by "that would be dealt
#: by `<source>`" and/or the combat qualifier. ``source`` is the engine's closed scope vocabulary
#: (`continuous.damage_prevention_globally_disabled`).
_DAMAGE_CANT_BE_PREVENTED_RE = re.compile(
    r"(?P<combat>combat )?damage(?: that would be dealt by (?P<source>~|creatures you control))? can't be prevented"
)
_UNPREVENTABLE_SOURCE_SCOPES: dict[str, str] = {"~": "self", "creatures you control": "your_creatures"}


def static_damage_cant_be_prevented(ctx: StaticContext) -> StaticResult:
    # "Damage can't be prevented." (Leyline of Punishment, Sunspine Lynx) -- the standing, board-wide prohibition
    # `continuous.damage_prevention_globally_disabled` reads live (Everlasting Torment's own effect).
    m = _DAMAGE_CANT_BE_PREVENTED_RE.fullmatch(ctx.text)
    if m is None:
        return None
    params: dict[str, object] = {}
    if m.group("combat"):
        params["combat_only"] = True
    if m.group("source"):
        params["source"] = _UNPREVENTABLE_SOURCE_SCOPES[m.group("source")]
    return [EffectSpec("damage_cant_be_prevented", params)]


def static_skip_your_step(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = SKIP_YOUR_STEP_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("skip_step", {"step": m.group("step").lower()})]
    return None


def static_graveyard_library_cast_prohibition(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = GRAVEYARD_LIBRARY_CAST_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        params: dict = {} if m.group("libraries") else {"zones": ["graveyard"]}
        return [EffectSpec("graveyard_library_cast_prohibition", params)]
    return None


def static_graveyard_library_entry_prohibition(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = GRAVEYARD_LIBRARY_ENTRY_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        word = m.group("type").lower()
        card_type = "nonland_permanent" if word == "nonland permanent" else word
        params = {"card_type": card_type}
        if not m.group("libraries"):
            params["zones"] = ["graveyard"]
        return [EffectSpec("graveyard_library_entry_prohibition", params)]
    return None


def static_radiation_life_gain(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if RADIATION_LIFE_GAIN_RE.fullmatch(text):
        return [EffectSpec("radiation_life_gain", {})]
    return None


def static_linked_exile_permission(ctx: StaticContext) -> StaticResult:
    return parse_linked_play(ctx.text, static=True)


def static_top_library_permission(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = TOP_LIBRARY_PERMISSION_RE.fullmatch(text)
    if m is not None:
        params: dict = {"look": True, **TOP_LIBRARY_VERB_PARAMS[m.group("verb").lower()]}
        if m.group("mv"):
            params["min_mana_value"] = int(m.group("mv"))
        tail = m.group("tail")
        if tail is not None:
            params[TOP_LIBRARY_TAILS[tail.lower()]] = True
        return [EffectSpec("top_library_permission", params)]
    return None


# PAR-105: the general "you may [play `<lands>` and] cast `<spells>` from the top of your library" grammar —
# after the closed-vocabulary row above, which keeps its five phrasings byte-for-byte.
def static_top_library(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    top_library = parse_top_library_permission(text)
    if top_library is not None:
        return claim(top_library)
    return None


def static_graveyard_cast(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    graveyard_cast = parse_graveyard_cast_permission(text)
    if graveyard_cast is not None:
        return claim(graveyard_cast)
    return None


def static_graveyard_land_play_permission(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if GRAVEYARD_LAND_PLAY_PERMISSION_RE.fullmatch(text):
        return [EffectSpec("graveyard_cast_permission", {"lands_only": True})]
    return None


def static_look_at_top_any_time(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if LOOK_AT_TOP_ANY_TIME_RE.fullmatch(text):
        return [EffectSpec("top_library_permission", {"look": True})]
    return None


def static_not_a_creature(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if NOT_A_CREATURE_RE.fullmatch(text):
        return [EffectSpec("type_change", {"remove_types": ["creature"]})]
    return None


def static_activate_as_though_haste(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if re.fullmatch(
        r"you may activate abilities of creatures you control as though those creatures had haste",
        text, re.IGNORECASE,
    ):
        return [EffectSpec("activate_as_though_haste", {"affects": group_selector(True, {"card_type": "creature"})})]  # PAR-109
    return None


def static_untap_each_untap_step(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if re.fullmatch(r"untap (?:~|this [a-z]+) during each other player'?s untap step", text, re.IGNORECASE):
        return [EffectSpec("untap_each_untap_step", {"affects": "self"})]  # PAR-109
    return None


def static_no_untap_optional(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if NO_UNTAP_OPTIONAL_RE.fullmatch(text):
        return [EffectSpec("no_untap_optional", {})]
    return None


def static_no_untap(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = NO_UNTAP_RE.fullmatch(text)
    if m is not None:
        params = {"affects": "self"}
        if m.group("cond"):
            # RULE 502.3: depletion lands keep their ordinary untap restriction
            # only while its condition holds; reuse the shared state grammar.
            condition = static_condition(m.group("cond"))
            if condition is None:
                return DECLINE
            params["active_if"] = condition
        return [EffectSpec("no_untap", params)]
    return None


def static_no_untap_attached(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = NO_UNTAP_ATTACHED_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("no_untap", {"affects": "attached_permanent"})]
    return None


def static_attached_ability_loss(ctx: StaticContext) -> StaticResult:
    m = ATTACHED_ABILITY_LOSS_RE.fullmatch(ctx.text)
    if m is None:
        return None
    # Only these two same-subject compositions are modeled here. Do not turn
    # this into general conjunction splitting or consume an unexplained tail.
    if not (m.group("pump") or m.group("no_untap")) or (m.group("pump") and m.group("no_untap")):
        return DECLINE
    loss = [EffectSpec("remove_all_abilities", {"affects": "attached_permanent"})]
    if m.group("pump"):
        text = f"{m.group('subject')} {m.group('pump')}"
        modifier = static_attached_anthem(replace(ctx, clause=text, text=text))
        return DECLINE if modifier is None or modifier is DECLINE else [*modifier, *loss]
    if m.group("no_untap"):
        text = f"{m.group('subject')} {m.group('no_untap')}"
        modifier = static_no_untap_attached(replace(ctx, clause=text, text=text))
        return DECLINE if modifier is None or modifier is DECLINE else [*loss, *modifier]
    return loss


def static_no_untap_group_power(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = NO_UNTAP_GROUP_POWER_RE.fullmatch(text)
    if m is not None:
        return [EffectSpec("no_untap", {"affects": group_selector(False, {"card_type": "creature", "min_power": int(m.group("n"))})})]
    return None


def static_no_untap_nonbasic_lands(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    if NO_UNTAP_NONBASIC_LANDS_RE.fullmatch(text):
        return [EffectSpec("no_untap", {"affects": group_selector(False, {"card_type": "land", "nonbasic": True})})]
    return None


def static_untap_cap(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = UNTAP_CAP_RE.fullmatch(text)
    if m is not None:
        card_type = singularize(m.group("word").lower())
        if card_type not in CARD_TYPE_WORDS:
            return DECLINE  # fail-closed — an unrecognised type-scope
        params: dict = {"count": int(m.group("n")), "card_type": card_type}
        if m.group("nonbasic"):
            params["nonbasic"] = True
        return [EffectSpec("untap_cap", params)]
    return None


def static_trigger_prohibition(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = TRIGGER_PROHIBITION_RE.fullmatch(text)
    if m is not None:
        subject_type = singularize(m.group("word"))
        if subject_type not in CARD_TYPE_WORDS:
            return DECLINE
        specs = [
            EffectSpec(
                "trigger_prohibition",
                {"event": "ENTERS_BATTLEFIELD", "subject_type": subject_type},
            )
        ]
        if m.group("dying"):
            specs.append(
                EffectSpec("trigger_prohibition", {"event": "DIES", "subject_type": subject_type})
            )
        return claim(specs)
    return None


def static_opponents_enter_tapped(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = OPPONENTS_ENTER_TAPPED_RE.fullmatch(text)
    if m is not None:
        specs = []
        for part in m.group("parts").split(" and "):
            nonbasic = part.startswith("nonbasic ")
            word = part[len("nonbasic "):] if nonbasic else part
            card_type = singularize(word)
            if card_type not in CARD_TYPE_WORDS:
                return DECLINE
            filt: dict = {"card_type": card_type}
            if nonbasic:
                filt["nonbasic"] = True
            specs.append(EffectSpec("enters_tapped_static", {"affects": scoped_group_selector("opponents", filt)}))
        return claim(specs)
    return None


def static_all_enter_tapped(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = ALL_ENTER_TAPPED_RE.fullmatch(text)
    if m is not None:
        card_types = [singularize(w) for w in m.group("words").split(" and ")]
        if any(t not in CARD_TYPE_WORDS for t in card_types):
            return DECLINE
        specs = []
        for card_type in card_types:
            filt = {"card_type": card_type}
            if m.group("nonbasic"):
                filt["nonbasic"] = True
            specs.append(EffectSpec("enters_tapped_static", {"affects": group_selector(False, filt)}))
        return claim(specs)
    return None


def static_type_overwrite(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = TYPE_OVERWRITE_RE.fullmatch(text)
    if m is not None:
        basic_type = BASIC_LAND_WORDS.get(m.group("word").lower())
        if basic_type is None:
            return DECLINE  # fail-closed — an unrecognised "are <X>" overwrite
        return [
            EffectSpec("type_change", {
                "affects": group_selector(False, {"card_type": "land", "nonbasic": True}),
                "set_subtypes": [basic_type],
            }),
        ]
    return None


def static_land_is_basic_type(ctx: StaticContext) -> StaticResult:
    text = ctx.text
    m = LAND_IS_BASIC_TYPE_RE.fullmatch(text)
    if m is not None:
        basic_type = BASIC_LAND_WORDS.get(m.group("word").lower())
        if basic_type is None:
            return DECLINE  # fail-closed — an unrecognised "is a <X>" grant
        return [EffectSpec("type_change", {"affects": group_selector(False, {"card_type": "land"}), "add_subtypes": [basic_type]})]
    return None


#: "All Mountains are Plains." (Conversion, Glaciers) -- RULE 305.7: a basic land type set by an effect replaces the old
#: land type and the land loses the abilities that type granted. The five basic land types, as printed.
_BASIC_LAND_TYPES_PLURAL = "plains|islands|swamps|mountains|forests"
_BASIC_LAND_TYPES_SINGULAR = "plains|island|swamp|mountain|forest"
_ALL_LANDS_BECOME_BASIC_RE = re.compile(
    rf"all (?P<old>{_BASIC_LAND_TYPES_PLURAL}) are (?P<new>{_BASIC_LAND_TYPES_SINGULAR})", re.IGNORECASE
)


def static_all_basic_type_becomes(ctx: StaticContext) -> StaticResult:
    m = _ALL_LANDS_BECOME_BASIC_RE.fullmatch(ctx.text)
    if m is None:
        return None
    old = BASIC_LAND_WORDS.get(m.group("old").lower())
    new = BASIC_LAND_WORDS.get(m.group("new").lower())
    if old is None or new is None or old == new:
        return None
    return [EffectSpec("type_change", {
        "affects": group_selector(False, {"card_type": "land", "subtype": old}),  # every player's lands of the old type
        "set_land_types": [new],
    })]
