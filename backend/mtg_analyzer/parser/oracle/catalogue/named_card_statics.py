"""MEC-134: the statics that read "the chosen name" -- the card name a permanent stamped on itself as it entered
(`GameObject.chosen_card_name`, "As ~ enters, choose a card name", RULE 201.2 / 601.2b / 614.12).

One closed table of whole-clause shapes, each mapped onto an existing engine primitive whose ``card_name_from_source``
param (or its own named sibling) reads the stamped name fresh on every check; nothing here is derived from card text at
run time. Pure -- no `game/` imports.

=============================================================  =====================================================
"Spells with the chosen name can't be cast."                    ``cast_prohibition`` (everyone, RULE 101.2)
"Your opponents can't cast spells with the chosen name."        ``cast_prohibition`` (opponents)
"Activated abilities of sources with the chosen name can't be   ``activation_prohibition`` (RULE 602.5; the optional
 activated [unless they're mana abilities]."                     rider is RULE 605's mana-ability carve-out)
"Spells [your opponents cast | you cast | enchanted player      ``cost_reduction`` (RULE 601.2f) scoped to the caster
 casts] with the chosen name cost {N} more/less to cast."
"Activated abilities of sources with the chosen name cost {N}   ``cost_reduction`` with ``scope="activation"``
 more to activate [unless they're mana abilities]."
"Prevent all damage that would be dealt to you and permanents   ``prevent_damage_from_chosen_name`` (RULE 615.1)
 you control by sources with the chosen name."
"You have protection from the chosen [card] name."              ``grant_protection_static`` over the controller
                                                                (RULE 702.16)
"Lands your opponents control with the chosen name lose all     layer-4 ``type_change`` + layer-6 ``remove_all_abilities``
 land types and abilities, and they gain "{T}: Add one mana     + ``grant_mana_ability`` (RULE 305.7, 613.1d/f)
 of any color.""
=============================================================  =====================================================
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ..spec import EffectSpec
from .name_atoms import name_reference

_MANA_ABILITY_RIDER = r"(?P<unless> unless they'?re mana abilities)?"

_SPELLS_CANT_BE_CAST = re.compile(r"spells with the chosen name can'?t be cast")
_OPPONENTS_CANT_CAST = re.compile(r"your opponents can'?t cast spells with the chosen name")
_ACTIVATION_PROHIBITED = re.compile(
    rf"activated abilities of sources with the chosen name can'?t be activated{_MANA_ABILITY_RIDER}"
)
_SPELL_COST = re.compile(
    r"spells (?:(?P<who_before>your opponents cast) )?with the chosen name"
    r"(?: (?P<who_after>you cast|enchanted player casts))? cost \{(?P<n>\d+)\} (?P<dir>more|less) to cast"
)
_ACTIVATION_COST = re.compile(
    rf"activated abilities of sources with the chosen name cost \{{(?P<n>\d+)\}} (?P<dir>more|less) to activate{_MANA_ABILITY_RIDER}"
)
_PREVENT_DAMAGE = re.compile(
    r"prevent all damage that would be dealt to you and permanents you control by sources with the chosen name"
)
_PROTECTION = re.compile(r"you have protection from the chosen (?:card )?name")
_ALPINE_MOON = re.compile(
    r"lands your opponents control with the chosen name lose all land types and abilities, "
    r"and they gain \"\{t\}: add (?:one|1) mana of any color\.?\""
)

#: RULE 105.1: "one mana of any color" -- the five options a granted mana ability offers.
_ANY_COLOR_MANA: list[dict[str, int]] = [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}]


def named_card_static_specs(text: str) -> Optional[list[EffectSpec]]:
    """The specs for a static clause that reads "the chosen name", or ``None`` when ``text`` is none of the table's shapes."""
    text = text.strip().rstrip(".").strip().lower()
    prohibition = re.fullmatch(r"(?P<who>your opponents|players) can't cast spells with the same name as (?P<ref>.+)", text)
    if prohibition:
        reference = name_reference(prohibition['ref'])
        return [EffectSpec("cast_prohibition", {
            "scope": "opponents" if prohibition['who'] == 'your opponents' else 'all',
            "name_reference": reference,
        })] if reference else None
    if "the chosen" not in text:
        return None
    if _SPELLS_CANT_BE_CAST.fullmatch(text):
        return [EffectSpec("cast_prohibition", {"scope": "all", "card_name_from_source": True})]
    if _OPPONENTS_CANT_CAST.fullmatch(text):
        return [EffectSpec("cast_prohibition", {"scope": "opponents", "card_name_from_source": True})]
    m = _ACTIVATION_PROHIBITED.fullmatch(text)
    if m is not None:
        params: dict[str, Any] = {"affects": "all_permanents", "card_name_from_source": True}
        if m.group("unless"):
            params["except_mana_abilities"] = True
        return [EffectSpec("activation_prohibition", params)]
    m = _SPELL_COST.fullmatch(text)
    if m is not None:
        who = m.group("who_before") or m.group("who_after")
        affects = {
            None: "all_spells", "your opponents cast": "opponents_spells", "you cast": "your_spells",
            "enchanted player casts": "enchanted_player_spells",
        }[who]
        if m.group("who_before") and m.group("who_after"):
            return None
        return [EffectSpec("cost_reduction", {
            "affects": affects, "generic": int(m.group("n")), "increase": m.group("dir") == "more",
            "card_name_from_source": True,
        })]
    m = _ACTIVATION_COST.fullmatch(text)
    if m is not None:
        params = {
            "scope": "activation", "affects": "all_permanents", "generic": int(m.group("n")),
            "increase": m.group("dir") == "more", "card_name_from_source": True,
        }
        if m.group("unless"):
            params["except_mana_abilities"] = True
        return [EffectSpec("cost_reduction", params)]
    if _PREVENT_DAMAGE.fullmatch(text):
        return [EffectSpec("prevent_damage_from_chosen_name", {})]
    if _PROTECTION.fullmatch(text):
        # A player has no object to carry the grant: ``affects="objects"`` with no ids selects nothing, and
        # ``protects_controller`` makes `continuous.player_static_protections` read it for the source's controller.
        return [EffectSpec("grant_protection_static", {
            "affects": "objects", "protects_controller": True, "protection_from_chosen_name": True,
        })]
    if _ALPINE_MOON.fullmatch(text):
        scope = {"affects": "opponents_permanents", "card_type": "land", "card_name_from_source": True}
        return [
            EffectSpec("type_change", {**scope, "remove_land_types": True}),
            EffectSpec("remove_all_abilities", dict(scope)),
            EffectSpec("grant_mana_ability", {**scope, "mana": [dict(option) for option in _ANY_COLOR_MANA]}),
        ]
    return None
