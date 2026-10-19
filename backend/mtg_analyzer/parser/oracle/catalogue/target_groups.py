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
    m = _GROUP_PHRASE.search(body)
    if m is None or m.group("t") not in _GROUP_TYPES or len(_GROUP_PHRASE.findall(body)) != 1:
        return None
    then_effects: list[dict] = []
    plain = body
    if plain.endswith(_LIFE_FROM_DAMAGE):
        plain = plain[: -len(_LIFE_FROM_DAMAGE)].rstrip()
        then_effects = [{"type": "gain_life", "params": {"amount": _DAMAGE_DEALT_SENTINEL}}]
    verb = m.group("verb")
    replacement = f"target {m.group('t')}" + (f"{verb}s" if verb else "")
    plain = _GROUP_PHRASE.sub(replacement, plain, count=1)
    plain = _THOSE_CREATURES.sub(lambda g: f"it {g.group('verb')}s", plain)
    inner = parse(plain)
    if not inner:
        return None
    # Exactly one announced target (the first effect's); every later effect must read that group member as
    # "it" (previous subject) or be untargeted, else the fan-out would be wrong.
    if any(spec.type in ("for_each", "bind", "if_else", "seq", "target_group") for spec in inner):
        return None
    params: dict = {
        "shares": "color",
        "filter": {"card_type": m.group("t")},
        "effects": [spec.to_dict() for spec in inner],
    }
    if then_effects:
        params["then_effects"] = then_effects
    return [EffectSpec("target_group", params)]
