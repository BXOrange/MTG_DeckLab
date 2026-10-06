from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dancer_s_chakrams() -> list[AbilitySpec]:
    """Job select (When this Equipment enters, create a 1/1 colorless Hero creature token, then attach this to it.)
    Equipped creature gets +2/+2, has lifelink and "Other commanders you control get +2/+2 and have lifelink," and is a Performer in addition to its other types.
    Krishna — Equip {3}

    — PLAY-ALL (Scions & Spellcraft). Job select and Equip are keywords. The static is the parser's anthem/lifelink/
    Performer plus Scion of Halaster's `grant_static_ability` for the quoted anthem: the equipped creature carries an anthem
    and lifelink over ``commander_creatures_you_own`` excluding itself.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["lifelink"]}),
                EffectSpec("type_change", {"affects": "attached_permanent", "add_subtypes": ["Performer"]}),
                EffectSpec("grant_static_ability", {
                    "affects": "attached_permanent",
                    "static_specs": [
                        {"type": "anthem", "params": {
                            "affects": "commander_creatures_you_own", "power": 2, "toughness": 2, "exclude_self": True,
                        }},
                        {"type": "grant_keyword", "params": {
                            "affects": "commander_creatures_you_own", "keywords": ["lifelink"], "exclude_self": True,
                        }},
                    ],
                }),
            ],
        ),
    ]


register("Dancer's Chakrams", _dancer_s_chakrams)
