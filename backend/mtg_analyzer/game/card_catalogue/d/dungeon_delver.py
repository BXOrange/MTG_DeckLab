from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dungeon_delver() -> list[AbilitySpec]:
    """Commander creatures you own have "Room abilities of dungeons you
    own trigger an additional time."

    — PAR-32 / MEC-61. Hand-authored: RULE 309.4c's room trigger is built
    off a `Dungeon` in the command zone (`RulesEngine._collect_dungeon_
    room_triggers`), a source-less path the general RULE 603.3d
    `trigger_doubler_bonus` (keyed on a battlefield `GameObject`) can't
    reach — new `continuous.dungeon_room_trigger_doubler_bonus` narrows
    the same idiom to this specific trigger family via a bare
    ``dungeon_room_trigger_doubler`` marker static, the
    `grant_escape`/`grant_retrace`/`extra_etb_counter` out-of-band
    convention MEC-55/56 already established.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("grant_static_ability", {
                    "affects": "commander_creatures_you_own",
                    "static_specs": [
                        {"type": "dungeon_room_trigger_doubler", "params": {}},
                    ],
                }),
            ],
        ),
    ]


register("Dungeon Delver", _dungeon_delver)
