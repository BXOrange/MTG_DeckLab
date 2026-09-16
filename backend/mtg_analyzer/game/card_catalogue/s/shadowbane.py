from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shadowbane() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you
    and/or creatures you control this turn, prevent that damage. If damage
    from a black source is prevented this way, you gain that much life.

    — ``recipient="you_and_creatures_you_control"`` (MEC-30) — the one-shot
    chooser's own new dynamic-recipient-set shape (`RulesEngine.prevent_
    damage_to_player_and_their_creatures`), the Family B sibling of Family
    A's `recipient_union`. ``rider={"if_source_color": "B", ...}`` (also
    MEC-30) gates the life-gain follow-up on the *watched source's* own
    colour — unlike every other rider kind, this one only sometimes fires.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "recipient": "you_and_creatures_you_control", "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you", "if_source_color": "B"},
            })],
        ),
    ]


register("Shadowbane", _shadowbane)
