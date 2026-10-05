from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _last_march_of_the_ents() -> list[AbilitySpec]:
    """This spell can't be countered.
    Draw cards equal to the greatest toughness among creatures you control,
    then put any number of creature cards from your hand onto the
    battlefield.

    — PLAY-ALL Step 2 (Raggadragga). `cant_be_countered` is the parser's own
    claim for the first line (Altered Ego's). The body is a `draw` whose
    ``count`` is a `count_selector` operand over the new
    ``greatest_toughness_you_control`` selector (`continuous.count_selector`,
    sibling of Return of the Wildspeaker's greatest-power one), then
    `put_from_hand_onto_battlefield` for creature cards with the established
    ``99`` "any number of" count sentinel; the pick is optional one card at a
    time. The draw resolves first, so the new cards are eligible, as the
    printed "then" says.
    """
    return [
        AbilitySpec("static", [EffectSpec("cant_be_countered", {})]),
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {
                    "count": {"kind": "count_selector", "selector": "greatest_toughness_you_control"},
                }),
                EffectSpec("put_from_hand_onto_battlefield", {"criteria": "Creature", "count": 99}),
            ],
        ),
    ]


register("Last March of the Ents", _last_march_of_the_ents)
