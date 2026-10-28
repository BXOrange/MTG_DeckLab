"""MEC-126: "<effect> target X **and each other X that shares a color with it**" (Radiance, RULE 702.xx-free
ability word) — one target is announced, and at resolution the body also applies to every other X sharing a
colour with it. The clause is read as its plain one-target form and the resulting effects are wrapped in a
`target_group` node (`game/effects/composition.py`); nothing here derives code from card text.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from ..spec import EffectSpec

#: The permanent-type words the group may be made of ("each other creature/enchantment …"); the engine
#: filter is ``card_type`` on the same word, so only words `matches_object_filter` knows may appear.
_GROUP_TYPES = frozenset({"creature", "enchantment", "artifact", "land"})

_NAME_GROUP_PHRASE = re.compile(
    r"target (?P<t>creature|artifact|enchantment|land|nonland permanent|permanent) and "
    r"(?P<quant>all|each) other (?P<others>creatures?|artifacts?|enchantments?|lands?|permanents?) with the same name as that "
    r"(?:creature|artifact|enchantment|land|permanent)(?P<verb> (?:gain|get)\b)?"
)

_GROUP_PHRASE = re.compile(
    r"target (?P<t>[a-z]+) and each other (?P=t) that shares a colou?r with it(?P<verb> (?:gain|get)\b)?"
)

#: Brightflame's tail: a total over the whole group, measured once after the loop (`DAMAGE_DEALT_SENTINEL`).
_LIFE_FROM_DAMAGE = " you gain life equal to the damage dealt this way."

#: Rally the Righteous's "Those creatures get +2/+0": the group, i.e. the loop's current member (the
#: previous-subject reading `target_group`'s per-member body already supplies).
_THOSE_CREATURES = re.compile(r"\bthose creatures (?P<verb>get|gain)\b")

_DAMAGE_DEALT_SENTINEL = "$damage_dealt"  # = composition.DAMAGE_DEALT_SENTINEL (parser cannot import game/)


def target_group_specs(body: str, parse: Callable[..., Optional[list[EffectSpec]]]) -> Optional[list[EffectSpec]]:
    pattern = _NAME_GROUP_PHRASE if _NAME_GROUP_PHRASE.search(body) else _GROUP_PHRASE
    m = pattern.search(body)
    if m is None or len(pattern.findall(body)) != 1:
        return None
    same_name = pattern is _NAME_GROUP_PHRASE
    if not same_name and m.group("t") not in _GROUP_TYPES:
        return None
    if same_name and (m['quant'] == 'all') != m['others'].endswith('s'):
        return None
    then_effects: list[dict] = []
    plain = body
    if plain.endswith(_LIFE_FROM_DAMAGE):
        plain = plain[: -len(_LIFE_FROM_DAMAGE)].rstrip()
        then_effects = [{"type": "gain_life", "params": {"amount": _DAMAGE_DEALT_SENTINEL}}]
    verb = m.group("verb")
    replacement = f"target {m.group('t')}" + (f"{verb}s" if verb else "")
    plain = pattern.sub(replacement, plain, count=1)
    if same_name:
        plain = plain.replace("to their owners' hands", "to its owner's hand")
    plain = _THOSE_CREATURES.sub(lambda g: f"it {g.group('verb')}s", plain)
    inner = parse(plain)
    if not inner:
        return None
    # Exactly one announced target (the first effect's); every later effect must read that group member as
    # "it" (previous subject) or be untargeted, else the fan-out would be wrong.
    if any(spec.type in ("for_each", "bind", "if_else", "seq", "target_group") for spec in inner):
        return None
    params: dict = {
        "shares": "name" if same_name else "color",
        "filter": ({"card_type": m['others'].removesuffix('s')} if m['others'] != 'permanents' else {})
                  if same_name else {"card_type": m.group("t")},
        "effects": [spec.to_dict() for spec in inner],
    }
    if then_effects:
        params["then_effects"] = then_effects
    return [EffectSpec("target_group", params)]
