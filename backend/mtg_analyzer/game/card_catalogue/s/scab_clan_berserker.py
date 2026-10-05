from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scab_clan_berserker() -> list[AbilitySpec]:
    """Haste
    Renown 1 (When this creature deals combat damage to a player, if it
    isn't renowned, put a +1/+1 counter on it and it becomes renowned.)
    Whenever an opponent casts a noncreature spell, if this creature is
    renowned, this creature deals 2 damage to that player.

    — Haste/Renown both come from the RULE 702 keyword catalogue
    (`effect_binder._keyword_triggered_abilities`, unaffected by this
    registration — see Relic Seeker's own entry); this only adds the
    card's own third ability, gated by the new `EffectSpec.condition` key
    ``source_is_renowned``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"},
                        condition={"source_is_renowned": True})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
        )
    ]


register("Scab-Clan Berserker", _scab_clan_berserker)
