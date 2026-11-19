"""Standing restrictions (PAR-290): what a player or permanent may not do, for exactly its subject.

Every row here reads one printed restriction onto an engine primitive that already enforces it live:

* "<creatures> can't attack you [or planeswalkers you control]" -> ``cant_attack_defender`` (RULE 508.1a; the host form
  "enchanted creature can't attack you ..." filters to the permanent's own host).
* "<enchanted/equipped permanent> [can't block|gets -1/-1|doesn't untap ...] and its activated abilities can't be
  activated" -> the half the shared grammar already reads plus an ``activation_prohibition`` on the host (RULE 602.5).
* "You can't cast <type> spells." / "<Type> spells can't be cast." -> ``cast_prohibition`` (RULE 601.3a).
* "Players can't play lands." / "You can't play lands." -> ``land_play_prohibition`` (RULE 305.1).
* "You can't lose the game and your opponents can't win the game." -> the Platinum Angel pair (RULE 104.3b).
* "<Type> spells can't be countered." -> ``grant_cant_be_countered`` with an every-controller scope (RULE 101.2).
* "~ can't have counters put on it." / "<creatures> can't have <kind> counters put on them." ->
  ``counter_placement_prohibition`` (RULE 122.1 / 101.2).

Each regex is a ``fullmatch`` over the whole clause, so a trailing qualifier ("unless ...", "this turn") leaves the
clause unclaimed rather than silently dropping the qualifier. Pure regex + data; no ``game/`` imports.
"""

from __future__ import annotations

import re
from typing import Optional

from ...spec import EffectSpec
from ..clause_hooks import static_effect_specs
from ..subtype_vocabulary import SUBTYPES
from .combat_restrictions import ATTACHED_SUBJECT_PATTERN
from .matcher_types import StaticContext, StaticResult
from .object_scope import object_filter, scoped_group_selector

#: "creatures" with no qualifier: every creature, which is what an empty attacker filter already means.
_ANY_CREATURE_FILTER = {"card_type": "creature"}

_CANT_ATTACK_YOU_RE = re.compile(
    rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN}|(?:[a-z][a-z -]*? )?creatures(?: [a-z0-9 -]+?)?) can'?t attack you"
    r"(?P<walkers> or planeswalkers you control)?"
)


def static_cant_attack_you(ctx: StaticContext) -> StaticResult:
    """RULE 508.1a: "Creatures with power 2 or less can't attack you." / "Enchanted creature can't attack you or
    planeswalkers you control." The protected player is the static's own controller (the printed "you")."""
    m = _CANT_ATTACK_YOU_RE.fullmatch(ctx.text)
    if m is None:
        return None
    subject = m.group("subject")
    if re.fullmatch(ATTACHED_SUBJECT_PATTERN, subject):
        attacker_filter: dict = {"attached_to_source": True}
    else:
        phrase = re.sub(r"^(?:all|each) ", "", subject)
        filt = object_filter(phrase)
        # A subject the shared grammar cannot read is never widened to "every creature".
        if filt is None or filt.get("card_type") != "creature" or "subtype" in filt:
            return None
        attacker_filter = {} if filt == _ANY_CREATURE_FILTER else {"object_filter": filt}
    scope = "player_or_planeswalker" if m.group("walkers") else "player"
    return [EffectSpec("cant_attack_defender", {"defender_scope": scope, "attacker_filter": attacker_filter})]


_ACTIVATION_BAN_RE = re.compile(
    rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN})(?P<head>.*?)(?:'s|,? and its) activated abilities can'?t be activated"
    r"(?P<mana> unless they'?re mana abilities)?"
)


def static_attached_activation_ban(ctx: StaticContext) -> StaticResult:
    """RULE 602.5 / 611.3b: the host of an Aura or Equipment can't activate its abilities, together with whatever else
    the same sentence says about the host (Demotion: "can't block"; Viper's Kiss: "gets -1/-1"; Encrust: "doesn't untap
    during its controller's untap step"). The other half is read by the shared grammar as its own whole clause, so a half
    it cannot read leaves the whole sentence unclaimed (fail closed)."""
    m = _ACTIVATION_BAN_RE.fullmatch(ctx.text)
    if m is None:
        return None
    subject = m.group("subject")
    specs: list[EffectSpec] = []
    head = m.group("head").strip()
    if head:
        # "can't block" / "gets -1/-1" / "doesn't untap during its controller's untap step"
        specs = static_effect_specs(f"{subject} {head}") or []
        if not specs:
            return None
    ban: dict = {"affects": "attached_permanent"}
    if m.group("mana"):
        ban["except_mana_abilities"] = True  # RULE 605.1a
    return [*specs, EffectSpec("activation_prohibition", ban)]


#: Spell-type words a "can't cast <type> spells" clause may name, each mapped to the `cast_prohibition` params that
#: select exactly those spells (`continuous.cast_prohibited`: ``spell_types`` is OR over the ``is_<word>`` card flags).
_CAST_TYPE_PARAMS: dict[str, dict] = {
    "creature": {"spell_types": ["creature"]},
    "noncreature": {"noncreature": True},
    # RULE 110.4: a permanent spell is any spell that is not an instant or sorcery.
    "permanent": {"spell_types": ["artifact", "battle", "creature", "enchantment", "land", "planeswalker"]},
}
_CAST_TYPES = "|".join(_CAST_TYPE_PARAMS)
_CANT_CAST_YOU_RE = re.compile(rf"you can'?t cast (?P<type>{_CAST_TYPES}) spells")
_CANT_CAST_ALL_RE = re.compile(rf"(?P<type>{_CAST_TYPES}) spells can'?t be cast")


def static_cant_cast_spell_type(ctx: StaticContext) -> StaticResult:
    """RULE 601.3a: "You can't cast creature spells." binds only the controller; "Creature spells can't be cast."
    binds every player."""
    for pattern, scope in ((_CANT_CAST_YOU_RE, "you"), (_CANT_CAST_ALL_RE, "all")):
        m = pattern.fullmatch(ctx.text)
        if m is not None:
            return [EffectSpec("cast_prohibition", {"scope": scope, **_CAST_TYPE_PARAMS[m.group("type")]})]
    return None


_CANT_PLAY_LANDS_RE = re.compile(r"(?P<who>players|you) can'?t play lands")


def static_cant_play_lands(ctx: StaticContext) -> StaticResult:
    """RULE 305.1: "Players can't play lands." / "You can't play lands." (playing, not putting onto the battlefield)."""
    m = _CANT_PLAY_LANDS_RE.fullmatch(ctx.text)
    if m is None:
        return None
    return [EffectSpec("land_play_prohibition", {"scope": "you" if m.group("who") == "you" else "all"})]


_CANT_LOSE_WIN_RE = re.compile(r"you can'?t lose the game and your opponents can'?t win the game")


def static_cant_lose_and_opponents_cant_win(ctx: StaticContext) -> StaticResult:
    """RULE 104.3b: Platinum Angel's pair, the same two markers Herald of Eternal Dawn is authored with."""
    if _CANT_LOSE_WIN_RE.fullmatch(ctx.text):
        return [EffectSpec("cant_lose_game", {}), EffectSpec("opponents_cant_win", {})]
    return None


_SPELLS_CANT_BE_COUNTERED_RE = re.compile(
    r"(?:(?P<creature>creature)|(?P<subtype>[a-z]+)) spells can'?t be countered"
)


def static_spells_cant_be_countered(ctx: StaticContext) -> StaticResult:
    """RULE 101.2: "Creature spells can't be countered." (Gaea's Herald) / "Sliver spells can't be countered." (Root
    Sliver) — every player's matching spell, unlike the "you control" grant the older row reads."""
    m = _SPELLS_CANT_BE_COUNTERED_RE.fullmatch(ctx.text)
    if m is None:
        return None
    if m.group("creature"):
        return [EffectSpec("grant_cant_be_countered", {"scope": "creature_spells"})]
    word = m.group("subtype")
    if word not in SUBTYPES:  # RULE 205.3: a subtype word only; any other adjective keeps its own scope or stays open
        return None
    return [EffectSpec("grant_cant_be_countered", {"scope": "subtype_spells", "subtype": word})]


_INSTANT_SORCERY_UNCOUNTERABLE_RE = re.compile(r"instant and sorcery spells you control can'?t be countered")


def static_instant_sorcery_cant_be_countered(ctx: StaticContext) -> StaticResult:
    if _INSTANT_SORCERY_UNCOUNTERABLE_RE.fullmatch(ctx.text):
        return [EffectSpec("grant_cant_be_countered", {"scope": "instant_sorcery_spells_you_control"})]
    return None


_CANT_HAVE_COUNTERS_RE = re.compile(
    r"(?:(?P<self>~)|(?P<group>creatures (?:you|your opponents) control)) can'?t have "
    r"(?P<kind>\+1/\+1 |-1/-1 )?counters put on (?:it|them)"
)


def static_cant_have_counters(ctx: StaticContext) -> StaticResult:
    """RULE 122.1 / 101.2: a standing bar on counters being put on the subject, of one kind or of every kind."""
    m = _CANT_HAVE_COUNTERS_RE.fullmatch(ctx.text)
    if m is None:
        return None
    params: dict = {"counter_kind": (m.group("kind") or "all").strip()}
    if m.group("self"):
        params["affects"] = "self"
    else:
        of = "opponents" if "opponents" in m.group("group") else "you"
        params["affects"] = scoped_group_selector(of, {"card_type": "creature"})
    return [EffectSpec("counter_placement_prohibition", params)]
