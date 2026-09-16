from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vraska_betrayals_sting() -> list[AbilitySpec]:
    """Compleated ({B/P} can be paid with {B} or 2 life.)
    0: You draw a card and lose 1 life. Proliferate.
    −2: Target creature becomes a Treasure artifact with "{T}: Add one
    mana of any color" and loses all other card types and abilities.
    −9: If target player has fewer than nine poison counters, they get a
    number of poison counters equal to the difference.

    — Eliferate deck batch. Compleated (keyword) and "0:" already parse on
    their own — reproduced here verbatim (whole-card hand-authoring
    replaces the parser's own output wholesale).

    "−2:" is a genuinely permanent (RAW has no "until") characteristic
    overwrite, so it's two chained `grant_until` effects at
    ``duration="rest_of_game"`` rather than a `temp_*`-field pump: the
    first carries the real target and applies `type_change`'s new
    `remove_types`/`add_types`/`add_subtypes` (RULE 613.7f's own
    creature-type-removal path, `GameObject._removed_types`, generalized
    from the Reconfigure-only special case it used to be); the second
    reuses that same target via `previous_subject` (the "Tap target
    land. **It** doesn't untap…" pronoun idiom) to layer on
    `remove_all_abilities` (RULE 613.7f's Humility/Dress Down strip) and
    `grant_mana_ability`. **Documented simplification**: the granted mana
    ability is modeled as a plain "{T}: Add one mana of any color" rather
    than "{T}, Sacrifice this artifact: …" — `granted_mana_options`
    (`GameObject`'s own layer-6 grant list `mana_abilities_for` reads once
    `loses_all_abilities` is set) only ever carries a tap cost, and
    `Card.is_artifact` itself (the printed, immutable characteristic a
    few older code paths read directly rather than through the
    layer-aware `type_words`/`is_creature`) isn't flipped — a spell that
    specifically targets "artifact" via one of those paths won't
    recognize this creature as one, while every layer-aware consumer is
    correct.

    "−9:" is `top_up_player_counter` — a threshold top-up (RULE 122.1)
    rather than a flat amount, new alongside the flat `add_player_counters`
    every other poison-granting card already used.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("lose_life", {"amount": 1}),
                EffectSpec("proliferate", {}),
            ],
            cost={"loyalty": 0},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "duration": "rest_of_game", "target_kind": "creature",
                    "static": {
                        "type": "type_change",
                        "params": {
                            "add_types": ["artifact"], "remove_types": ["creature"],
                            "add_subtypes": ["Treasure"],
                        },
                    },
                }),
                EffectSpec("grant_until", {
                    "duration": "rest_of_game", "previous_subject": True,
                    "static": {"type": "remove_all_abilities", "params": {}},
                }),
                EffectSpec("grant_until", {
                    "duration": "rest_of_game", "previous_subject": True,
                    "static": {"type": "grant_mana_ability", "params": {"mana": [{"ANY": 1}]}},
                }),
            ],
            cost={"loyalty": -2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("top_up_player_counter", {"kind": "poison", "threshold": 9})],
            cost={"loyalty": -9},
        ),
    ]


register("Vraska, Betrayal's Sting", _vraska_betrayals_sting)
